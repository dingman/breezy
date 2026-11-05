"""The process-wide owner of shared NWS-ingest state and services.

Governing ruling: ``docs/plans/archive/PHASE1_ACTOR_BRIEF.md`` SS3.6, with the startup
preconditions of SS6 step 0.

Breezy runs **one Actor per ``(venue, city)``** -- five in production. Two
mechanisms need state no single Actor can own, and this module is their home:

* **The cross-site 403 burst signal.** One Actor sees one city. A burst of
  same-cause 403s *across* cities is the strongest UA-trap evidence there is,
  and only something process-scoped can see it.
* **The :class:`~breezy.ingest.gate.SettlementGate` instance.** All five Actors
  must drive **one** gate object over **one**
  :class:`~breezy.ingest.gate.StateStore`. The gate now reads its global entry
  through to the store on every access, so a sibling instance can no longer
  serve a stale ``ua_trap_blocked``; the shared-instance rule stands anyway,
  because two mechanisms guarding one invariant is correct for something whose
  failure mode is "the UA trap silently fails to block the other four cities".

It also owns the single :class:`~breezy.ingest.product_index.ProductIntegrityIndex`
and the single :class:`~breezy.ingest.http.HttpTransport`, and it runs the two
deployment preconditions exactly once, at construction.

Null hypothesis (the project's prime directive), checked before this module was
written, against the installed ``nautilus_trader==1.231.0``:

* ``Actor.register_base`` (``common/actor.pyx:691-732``) wires exactly four
  things into an Actor -- ``portfolio``, ``msgbus``, ``cache``, ``clock``.
  There is no hook, slot or registry for a process-scoped service, and
  ``[n for n in dir(Actor()) if 'shared'/'service'/'registry'/'container' in n]``
  is empty.
* ``Cache``'s general store is **bytes-keyed-by-str** (``cache/cache.pyx:1686``,
  ``:2834``; ``Cache.add(key, object())`` raises ``TypeError`` -- executed), so
  it structurally cannot hold a live ``SettlementGate``. It was also evaluated
  for the *persistence* half and rejected on measured evidence (``Cache.add``
  returns before the write is durable, ``Cache.get`` never reads the database,
  ``Cache.reset()`` can launder a permanent halt -- see
  ``breezy.runtime.sqlite_store``). So Nautilus gives us neither half here, and
  both the store and this container are Breezy-owned.
* ``MessageBus`` routes messages, not object references.
* ``Trader.add_actor`` gives every Actor its **own** ``Clock`` instance
  (``trading/trader.py:342``, ``clock = self._clock.__class__()``). Five Actors
  therefore hold five clock objects, so a signal correlated *across* Actors --
  which the burst window is -- must not be timed off any one of them. The
  single injected ``Callable[[], int]`` this container owns and hands to the
  gate, the index, the transport and the window is the fix.
* ``ActorConfig`` is a ``msgspec.Struct``; it can technically carry a live
  object, but that is constructor injection with extra steps and it breaks
  ``ImportableActorConfig`` serialisation. It is not a shared-instance
  guarantee.

**Conclusion:** Nautilus provides neither a durable key-value seam fit for a
settlement halt nor a per-process service container; both are built here, from
Breezy-owned parts only, and the durability of the store is PROVEN at startup
rather than assumed (``gate.assert_state_store_durable``). This
module imports ``nautilus_trader`` nowhere and modifies it nowhere.

**Wiring.** The composition root constructs one :class:`SharedIngestState`,
constructs each Actor itself with ``shared=`` injected, and registers them
through the NATIVE ``Trader.add_actor`` (``trading/trader.py:312``, reached via
``TradingNode.trader`` at ``live/node.py:139``). The ``ImportableActorConfig``
route cannot be used for these Actors: ``ActorFactory.create`` ends in
``actor_cls(config)`` (``common/config.py:614``) -- one positional argument,
with no seam for a live object. A second independent construction raises. There
is deliberately **no** module-level ``current()`` accessor: a global getter
would make the shared object reachable without injection, and "reachable from
anywhere" is how a second, unnoticed graph of components gets built in the
first place.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from breezy.ingest.gate import (
    DEFAULT_BURST_POLICY,
    CrossSiteBurstPolicy,
    SettlementGate,
    StateStore,
    StateStoreOpener,
    assert_state_store_durable,
)
from breezy.ingest.http import DEFAULT_BASE_URL, HttpTransport
from breezy.ingest.product_index import ProductIntegrityIndex
from breezy.persistence.catalog import (
    FilesystemProbe,
    assert_writer_lock_filesystem_supported,
    probe_filesystem,
    station_catalog_path,
)
from breezy.registry.sites import SiteNotFoundError, SiteRegistry

logger = logging.getLogger(__name__)

#: The only host this process may fetch settlement data from.
DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset({"api.weather.gov"})

#: The cause label an ordinary 403 is recorded under.
#:
#: ``ingest/http.py`` raises a bare ``ForbiddenError`` for every 403 -- it has
#: no finer discriminator to offer -- so today this is the only label the Actor
#: passes, and every 403 therefore combines. That is the deliberate direction:
#: combining is what detects the trap. The per-cause partition exists so that a
#: 403 class we later learn to distinguish (via ``polymarket-us-discovery`` or
#: an NWS service-change notice) cannot be *added* to this bucket by default
#: and dilute it. All five Actors run one code path referencing this one
#: constant, so the partition cannot fragment through a typo in practice.
FORBIDDEN_403_CAUSE = "forbidden_403"


class SharedIngestStateError(RuntimeError):
    """Base class for every failure this module raises."""


class DuplicateSharedIngestStateError(SharedIngestStateError):
    """Raised on a second, independent :class:`SharedIngestState` construction.

    This is the invariant that makes "all five Actors share one gate" an
    asserted property rather than a convention. A convention that is silent
    when violated is not a safeguard: a second container would hand its Actors
    a second gate whose UA-trap latch the first four cities never see.
    """


class SiteSetError(SharedIngestStateError, ValueError):
    """Raised when the configured ``(venue, city)`` set is empty, duplicated,
    or names a site the registry does not know.
    """


class UnknownSiteError(SharedIngestStateError, KeyError):
    """Raised when a ``(venue, city)`` outside the configured set is used."""


class DuplicateSiteRegistrationError(SharedIngestStateError):
    """Raised when a second Actor registers for an already-claimed station.

    One Actor per station root is a design invariant, not a preference -- the
    catalog's writer lock treats a second writer as a deployment defect
    (``ConcurrentWriterError``). Catching it at startup is cheaper than
    catching it at the first concurrent write.
    """


class ForeignComponentError(SharedIngestStateError):
    """Raised when a registering Actor presents a component that is not this
    container's own -- i.e. it built its own gate or index somewhere else.
    """


# ---------------------------------------------------------------------------
# The cross-site 403 burst window
#
# ``CrossSiteBurstPolicy``/``DEFAULT_BURST_POLICY`` now live in ``gate.py``,
# defined ONCE, and are imported (re-exported) here rather than redefined --
# two definitions of "what counts as a burst" is exactly the drift that let
# the UA-trap gap this fixes exist in the first place. See ``gate.py`` for
# both the policy's full derivation and the reason its name stayed
# ``DEFAULT_BURST_POLICY`` rather than the ``DEFAULT_CROSS_SITE_BURST_POLICY``
# an earlier design note used.
# ---------------------------------------------------------------------------


class CrossSite403Window:
    """Sliding, per-cause record of which sites have recently seen a 403.

    **In-memory, deliberately not persisted.** Three reasons, in order of
    weight:

    1. The *verdict* is already durable. A detected burst drives
       ``SettlementGate.record_forbidden_403``, which writes ``ua_trap_blocked``
       to the shared store as a cross-restart latch. Persisting the evidence
       window too would be a second, weaker copy of a safety property that is
       already durable -- with its own corruption surface, which under this
       codebase's fail-closed posture means bit-flips turning into global halts.
    2. The restart gap this class's own in-memory evidence cannot cover --
       a trap whose 403s straddle a process restart, with every site merely
       abuse-degrading on either side of it -- is now covered a different
       way: the gate derives its OWN burst signal from the per-site
       ``abuse_403_last_ns`` it already persists durably
       (``SettlementGate._derive_cross_site_burst``), read straight through
       the shared store the same way ``_load_global`` is. An earlier version
       of this comment claimed the cold-start ``any_site_ever_succeeded``
       arm already covered every restart case; it does not -- that arm only
       catches a restart with NO site ever having succeeded, not a
       mid-session onset whose two halves happen to land on either side of
       one. This class keeps its in-memory copy anyway (point 1), OR-ed in
       with the gate's derivation during the transition, so it can only ever
       *over*-halt, never under-halt, relative to the gate alone.
    3. Persisting would put a cache-database write on the failure path, at the
       exact moment the system is least healthy.

    The clock is injected as a ``Callable[[], int]`` of UNIX nanoseconds, the
    same discipline (and, via :class:`SharedIngestState`, the same object) as
    ``SettlementGate``, ``HttpTransport`` and ``ProductIntegrityIndex``.
    """

    def __init__(self, *, clock: Callable[[], int], policy: CrossSiteBurstPolicy) -> None:
        self._clock = clock
        self._policy = policy
        self._lock = threading.RLock()
        # cause -> {(venue, city): last_observed_ns}. Bounded by
        # (sites x causes); one entry per site per cause, overwritten in place.
        self._observations: dict[str, dict[tuple[str, str], int]] = {}

    @property
    def policy(self) -> CrossSiteBurstPolicy:
        return self._policy

    def observe(self, venue: str, city: str, *, cause: str) -> bool:
        """Record a 403 for ``(venue, city)`` and report whether the window now
        shows a cross-site burst for ``cause``.

        Returns ``True`` exactly when at least ``policy.site_threshold``
        distinct sites have shown this cause within ``policy.window_ns``.
        """
        validated_cause = _require_cause(cause)
        with self._lock:
            now = self._clock()
            bucket = self._observations.setdefault(validated_cause, {})
            bucket[(venue, city)] = now
            fresh = _within_window(bucket, now, self._policy.window_ns)
            self._observations[validated_cause] = fresh
            detected = len(fresh) >= self._policy.site_threshold
        if detected:
            logger.critical(
                "cross-site 403 burst: %d distinct sites reported cause=%s within %d ns "
                "-- treating as UA-trap evidence. sites=%s",
                len(fresh),
                validated_cause,
                self._policy.window_ns,
                sorted(fresh),
            )
        return detected

    def active_sites(self, *, cause: str) -> tuple[tuple[str, str], ...]:
        """Sites currently inside the window for ``cause``, sorted. Read-only."""
        validated_cause = _require_cause(cause)
        with self._lock:
            now = self._clock()
            bucket = self._observations.get(validated_cause, {})
            return tuple(sorted(_within_window(bucket, now, self._policy.window_ns)))

    def clear(self) -> None:
        """Drop every observation. Called on container disposal."""
        with self._lock:
            self._observations.clear()


def _require_cause(cause: str) -> str:
    stripped = cause.strip()
    if not stripped:
        raise ValueError("`cause` must be a non-empty label")
    return stripped


def _within_window(
    bucket: dict[tuple[str, str], int], now: int, window_ns: int
) -> dict[tuple[str, str], int]:
    """Entries still inside the window.

    A FUTURE-dated entry (``at_ns > now``, i.e. the clock jumped backwards)
    yields a negative age and is therefore KEPT. That is the deliberate
    direction: a backward clock must not silently evict trap evidence, and
    holding evidence too long biases toward halting, which is the cheap error.
    """
    return {site: at_ns for site, at_ns in bucket.items() if now - at_ns < window_ns}


# ---------------------------------------------------------------------------
# The container
# ---------------------------------------------------------------------------

_PROCESS_LOCK = threading.Lock()
_LIVE_INSTANCE: SharedIngestState | None = None


class SharedIngestState:
    """The single owner of every process-wide NWS-ingest component.

    Construct **once** per process, in the composition root, before any Actor
    starts. A second construction raises
    :class:`DuplicateSharedIngestStateError`.

    Construction is startup: it runs both deployment preconditions of the
    brief's SS6 step 0 -- ``assert_state_store_durable`` (an empirical
    round-trip through ``store`` and an independent handle on its backing
    medium) and ``assert_writer_lock_filesystem_supported`` per station root.
    Both are unenforceable later and silent when violated. Neither is an
    import-time side effect: nothing at this module's scope calls them.

    Parameters
    ----------
    registry : SiteRegistry
        The single source of truth for site identity. Every configured site is
        checked against it, so a typo cannot create a bogus station root.
    sites : Sequence[tuple[str, str]]
        The ``(venue, city)`` pairs this process serves -- explicit rather than
        defaulted from the registry, so a partial deployment is a stated
        intention rather than an accident.
    catalog_base : Path
        Root of the NWS data island.
    store : StateStore
        The ONE durable key-value seam. The gate and the index both receive
        this object; their key namespaces (``gate:`` and ``productidx:``) do
        not collide by design.
    clock : Callable[[], int]
        The ONE nanosecond clock, handed to the gate, the index, the transport
        and the burst window. Nautilus gives every Actor its own ``Clock``
        object (``trading/trader.py:342``), so a cross-Actor signal cannot be
        timed off any single Actor's clock.
    store_opener : StateStoreOpener
        Opens a NEW, independent handle on the same backing medium as
        ``store``. Used once, at construction, by
        ``gate.assert_state_store_durable`` to PROVE by round-trip that
        ``store`` really persists -- the one precondition that cannot be
        established from a declared flag, because a store that merely appears
        to persist is the exact failure being defended against.
    burst_policy : CrossSiteBurstPolicy
        See :data:`DEFAULT_BURST_POLICY`.
    allowed_hosts, base_url, user_agent, check_proxy_env
        Forwarded verbatim to :class:`~breezy.ingest.http.HttpTransport`.
    probe : Callable[[Path], FilesystemProbe]
        Injected for the same reason ``assert_writer_lock_filesystem_supported``
        takes a probe rather than a path: every verdict stays reachable in a
        test without a real mount.
    """

    def __init__(
        self,
        *,
        registry: SiteRegistry,
        sites: Sequence[tuple[str, str]],
        catalog_base: Path,
        store: StateStore,
        clock: Callable[[], int],
        store_opener: StateStoreOpener,
        burst_policy: CrossSiteBurstPolicy = DEFAULT_BURST_POLICY,
        allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str | None = None,
        check_proxy_env: bool = True,
        probe: Callable[[Path], FilesystemProbe] = probe_filesystem,
    ) -> None:
        # Claim the process slot FIRST, so a genuine duplicate is reported as a
        # duplicate even when it would also have failed a precondition. Release
        # it again if anything below raises: a misconfigured deployment must
        # stay fixable in place, not wedge the process behind a half-built
        # container that can never be disposed because nobody holds it.
        _claim_process_slot(self)
        try:
            self._sites = _validate_sites(registry, sites)
            self._registry = registry
            self._catalog_base = Path(catalog_base)
            self._store = store
            self._clock = clock
            self._burst_policy = burst_policy

            self._assert_deployment_preconditions(
                store_opener=store_opener,
                probe=probe,
            )

            # The gate's own persisted-state cross-site-burst derivation
            # needs the FULL configured site set -- passing anything less
            # (or the empty default the gate constructor deliberately does
            # not have) would silently under-count siblings with no error
            # and no log, the exact footgun shape that caused the defect
            # this composition-root wiring closes. `self._sites` is already
            # validated (non-empty, no duplicates, every site registry-known)
            # by `_validate_sites` above. Same `burst_policy` as the legacy
            # in-memory window below, so the two burst signals can never
            # silently disagree on what counts as a burst.
            self._gate = SettlementGate(
                store=store, clock=clock, sites=frozenset(self._sites), burst_policy=burst_policy
            )
            self._product_index = ProductIntegrityIndex(store=store, clock=clock)
            self._transport = HttpTransport(
                allowed_hosts=allowed_hosts,
                clock=clock,
                base_url=base_url,
                user_agent=user_agent,
                check_proxy_env=check_proxy_env,
            )
            self._burst_window = CrossSite403Window(clock=clock, policy=burst_policy)

            self._registration_lock = threading.RLock()
            self._registered: dict[tuple[str, str], str] = {}
        except BaseException:
            _release_process_slot(self)
            raise

        logger.info(
            "shared ingest state ready: sites=%s catalog_base=%s burst_policy=%s",
            self._sites,
            self._catalog_base,
            self._burst_policy,
        )

    # -- startup preconditions ------------------------------------------

    def _assert_deployment_preconditions(
        self,
        *,
        store_opener: StateStoreOpener,
        probe: Callable[[Path], FilesystemProbe],
    ) -> None:
        """Run both SS6 step-0 preconditions, once, at construction.

        Neither is enforceable at runtime and both are silent when violated:
        gate state that is never persisted looks identical to gate state that
        happens not to have changed, and an ``flock`` on a network filesystem
        returns success while excluding nobody.

        The first precondition is a round-trip PROBE, not a settings check.
        Its predecessor asserted five Nautilus ``Cache``-persistence settings;
        that guard demanded ``CacheConfig.database is not None`` while the
        kernel accepts only ``'redis'`` there, so no Redis-free node config
        could satisfy it, and it described a mechanism this codebase had
        already abandoned in favour of
        ``breezy.runtime.sqlite_store.SqliteStateStore``. What replaces it
        checks the store actually in use, empirically.
        """
        assert_state_store_durable(self._store, opener=store_opener)
        self._station_roots: dict[tuple[str, str], Path] = {}
        for venue, city in self._sites:
            root = station_catalog_path(self._catalog_base, venue, city)
            assert_writer_lock_filesystem_supported(probe(root))
            self._station_roots[(venue, city)] = root

    # -- shared components ----------------------------------------------

    @property
    def gate(self) -> SettlementGate:
        """The ONE settlement gate every Actor in this process must drive."""
        return self._gate

    @property
    def product_index(self) -> ProductIntegrityIndex:
        """The ONE product-integrity index (first-write-wins evidence)."""
        return self._product_index

    @property
    def transport(self) -> HttpTransport:
        """The ONE NWS transport."""
        return self._transport

    @property
    def store(self) -> StateStore:
        """The ONE durable store behind the gate and the index."""
        return self._store

    @property
    def clock(self) -> Callable[[], int]:
        """The ONE nanosecond clock behind every component here."""
        return self._clock

    @property
    def registry(self) -> SiteRegistry:
        return self._registry

    @property
    def catalog_base(self) -> Path:
        return self._catalog_base

    @property
    def sites(self) -> tuple[tuple[str, str], ...]:
        """The configured ``(venue, city)`` pairs, in configuration order."""
        return self._sites

    @property
    def burst_policy(self) -> CrossSiteBurstPolicy:
        return self._burst_policy

    def station_root(self, venue: str, city: str) -> Path:
        """The validated catalog root for one configured site.

        Computed and symlink-checked once at startup, so every caller gets the
        identical path and none of them re-derives it.
        """
        return self._station_roots[self._require_configured(venue, city)]

    # -- Actor registration ---------------------------------------------

    def register_site_actor(
        self,
        venue: str,
        city: str,
        *,
        component_id: str,
        gate: SettlementGate,
        product_index: ProductIntegrityIndex,
    ) -> None:
        """Register the Actor serving ``(venue, city)``, proving it holds the
        shared components.

        The second of the two mechanisms guarding the shared-instance
        invariant. Mechanism one makes a second container impossible;
        this one makes an Actor that built its *own* gate or index -- from a
        stray constructor call rather than a second container -- fail at
        startup instead of silently trading against private state.

        Raises
        ------
        UnknownSiteError
            If ``(venue, city)`` is not in the configured set.
        DuplicateSiteRegistrationError
            If another Actor already claimed this station.
        ForeignComponentError
            If ``gate`` or ``product_index`` is not this container's object.
        """
        site = self._require_configured(venue, city)
        if gate is not self._gate:
            raise ForeignComponentError(
                f"{component_id} presented a gate that is not the shared "
                f"SettlementGate for {venue}/{city}. All five Actors must drive "
                "ONE gate object, or a UA-trap latch set by one city will not "
                "block the others."
            )
        if product_index is not self._product_index:
            raise ForeignComponentError(
                f"{component_id} presented a product_index that is not the "
                f"shared ProductIntegrityIndex for {venue}/{city}. A private "
                "index makes first-write-wins evidence per-Actor, which "
                "launders a mutated product."
            )
        with self._registration_lock:
            existing = self._registered.get(site)
            if existing is not None:
                raise DuplicateSiteRegistrationError(
                    f"{venue}/{city} is already served by {existing}; "
                    f"{component_id} would be a second writer for one station "
                    "root, which the catalog's writer lock treats as a "
                    "deployment defect."
                )
            self._registered[site] = component_id
        logger.info("registered ingest Actor %s for %s/%s", component_id, venue, city)

    def registered_sites(self) -> tuple[tuple[str, str], ...]:
        """Sites with a registered Actor, in configuration order."""
        with self._registration_lock:
            claimed = set(self._registered)
        return tuple(site for site in self._sites if site in claimed)

    # -- cross-site 403 window -------------------------------------------

    def observe_forbidden_403(
        self, venue: str, city: str, *, cause: str = FORBIDDEN_403_CAUSE
    ) -> bool:
        """Record a 403 for one site and return the ``cross_site_burst_detected``
        signal the Actor passes to ``SettlementGate.record_forbidden_403``.

        The gate owns the UA-trap-vs-abuse *decision*; this container owns the
        cross-site *timing* it cannot see -- the same division of labour as
        ``final_window_elapsed`` and ``conflict_window_elapsed``.
        """
        self._require_configured(venue, city)
        return self._burst_window.observe(venue, city, cause=cause)

    def active_forbidden_403_sites(
        self, *, cause: str = FORBIDDEN_403_CAUSE
    ) -> tuple[tuple[str, str], ...]:
        """Sites currently inside the burst window, for logs and 07:30 triage."""
        return self._burst_window.active_sites(cause=cause)

    # -- lifecycle --------------------------------------------------------

    def dispose(self) -> None:
        """Release the process slot and drop registrations.

        Orderly shutdown, and the only way a second container may legitimately
        be built. It does not weaken the guard: disposal is an explicit act,
        whereas the failure this module exists to prevent is a *silent* second
        construction. Idempotent, and a stale handle can never release a
        successor's slot.
        """
        with self._registration_lock:
            self._registered.clear()
        self._burst_window.clear()
        _release_process_slot(self)

    def _require_configured(self, venue: str, city: str) -> tuple[str, str]:
        site = (venue, city)
        if site not in self._station_roots:
            raise UnknownSiteError(
                f"{venue}/{city} is not one of this process's configured sites {self._sites}"
            )
        return site


def _validate_sites(
    registry: SiteRegistry, sites: Sequence[tuple[str, str]]
) -> tuple[tuple[str, str], ...]:
    ordered = tuple(sites)
    if not ordered:
        raise SiteSetError("at least one (venue, city) site must be configured")
    if len(set(ordered)) != len(ordered):
        raise SiteSetError(f"duplicate site in configured set: {ordered}")
    for venue, city in ordered:
        try:
            registry.settlement_site(venue, city)
        except SiteNotFoundError as exc:
            raise SiteSetError(
                f"configured site {venue}/{city} is not in the registry "
                "(sites.toml is the single source of truth; never hardcode a "
                "station identifier)"
            ) from exc
    return ordered


def _claim_process_slot(instance: SharedIngestState) -> None:
    global _LIVE_INSTANCE
    with _PROCESS_LOCK:
        if _LIVE_INSTANCE is not None:
            raise DuplicateSharedIngestStateError(
                "a SharedIngestState has already been constructed in this "
                "process. All ingest Actors must share ONE container, one "
                "SettlementGate and one StateStore -- a second container would "
                "give four of the five cities a gate blind to the UA-trap latch "
                "the fifth just set. Pass the existing instance in, or dispose "
                "it first."
            )
        _LIVE_INSTANCE = instance


def _release_process_slot(instance: SharedIngestState) -> None:
    """Release the slot only if ``instance`` is the one holding it.

    The identity check is the point: without it, a stale handle calling
    ``dispose()`` a second time would unlock the slot its successor is holding,
    and the duplicate-construction guard would quietly stop guarding.
    """
    global _LIVE_INSTANCE
    with _PROCESS_LOCK:
        if _LIVE_INSTANCE is instance:
            _LIVE_INSTANCE = None
