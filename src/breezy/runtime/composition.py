"""The Breezy ingestion composition root.

One function, :func:`ingest_runtime`, turns a validated
:class:`~breezy.runtime.settings.BreezyRuntimeSettings` into every live object
the process needs, and guarantees they are torn down again -- on the happy
path, on a body exception, and on a construction failure part-way through.

Ordering is load-bearing in both directions:

* **Up:** node config (pure, no resources) -> registry (read-only file) ->
  :class:`~breezy.runtime.sqlite_store.SqliteStateStore` (opens a file handle)
  -> :class:`~breezy.ingest.shared_state.SharedIngestState` (claims the
  process-wide slot and runs the startup preconditions).
* **Down:** exactly the reverse. ``SharedIngestState.dispose()`` releases the
  process slot; ``SqliteStateStore.close()`` closes the sqlite handle. A
  construction error must leak neither -- a leaked slot makes the failure
  unrecoverable in-process (the next attempt raises
  ``DuplicateSharedIngestStateError`` instead of the real cause), and a leaked
  handle keeps a WAL open on a database nobody owns.

``contextlib.ExitStack`` provides that guarantee natively; no bespoke teardown
machinery is written here.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode

from breezy.ingest.config import NwsIngestActorConfig
from breezy.ingest.gate import ClosableStateStore
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import FilesystemProbe, probe_filesystem
from breezy.registry.sites import SiteRegistry, default_registry, load_registry
from breezy.runtime.bootstrap_witness import enforce_bootstrap_witness
from breezy.runtime.health import AlertSink, resolve_alert_sink
from breezy.runtime.node_config import actor_component_id, build_node_config
from breezy.runtime.settings import BreezyRuntimeSettings
from breezy.runtime.sqlite_store import SqliteStateStore

logger = logging.getLogger(__name__)


StoreFactory = Callable[[Path], ClosableStateStore]
ProbeFactory = Callable[[Path], FilesystemProbe]
AlertSinkFactory = Callable[[], AlertSink]


# ---------------------------------------------------------------------------
# Per-site health snapshot paths
# ---------------------------------------------------------------------------
#
# DESIGN: one snapshot FILE PER SITE, not one file for the process.
#
# An Actor knows only its own `(venue, city)` -- `HealthSnapshot.sites` is
# populated with exactly one `SiteHealth` at `nws_actor.py::_emit_health`.
# Five Actors pointed at one path would each overwrite the others once per
# poll cycle, and the file's contents would report whichever site wrote last.
#
# The alternative considered and rejected was a process-level aggregator in
# this package: a shared, mutable, cross-thread collector merging five
# `SiteHealth`s into one document. It would need its own lock (the five
# Actors write from five separate executor threads), its own merged schema,
# and its own redaction review -- and `runtime/health.py`, which owns both
# the schema and the redaction allowlist, is out of scope for this change.
# It also HIDES the failure it would exist to show: an aggregator keeps
# rewriting a fresh file even while one site's poll cycle is wedged, so that
# site's staleness is visible only by parsing `snapshot_at_ns` INSIDE the
# document rather than from the file's mtime.
#
# The runbook property -- "a stale snapshot file means the process is dead"
# -- still holds process-wide under the per-site design, and holds strictly
# more precisely:
#
#   * process dead    => NO file in the directory is being rewritten, so
#                        `max(mtime)` over the directory goes stale. The
#                        operator/monitor check becomes "if the NEWEST file
#                        in BREEZY_HEALTH_SNAPSHOT_DIR is older than N, the
#                        process is dead", which is implied by process death
#                        and by nothing else.
#   * one site wedged => that ONE file goes stale while the others stay
#                        fresh, which the single-file design could not
#                        express at all.
#
# Nothing new is invented for the write itself: `health.write_snapshot_atomic`
# already does mkstemp + fchmod(0o600) + fsync + os.replace into the file's
# own parent directory, and creates that directory on first write.

_SAFE_SITE_LABEL = re.compile(r"\A[A-Za-z0-9_-]+\Z")


def site_snapshot_path(directory: Path, venue: str, city: str) -> Path:
    """Return the health-snapshot file for one site beneath `directory`.

    Deterministic and injective over `(venue, city)`, which is the whole
    point: the file for a site must be the same path on every restart so a
    monitor can watch a fixed name, and two sites must never resolve to one
    path.

    `venue` and `city` are validated against a strict slug pattern rather
    than merely joined. They originate from `BREEZY_SITES`, which validates
    only that both halves are non-blank, so a value like `../../etc/cron.d`
    would otherwise escape the configured directory and let an operator's
    typo (or an attacker with control of the unit file's environment) write
    a 0o600 JSON document anywhere the process can reach. Cross-checking
    against the site registry happens elsewhere; this is the containment at
    the point of path construction.
    """
    for label, value in (("venue", venue), ("city", city)):
        if not _SAFE_SITE_LABEL.match(value):
            raise ValueError(
                f"unsafe {label} {value!r} for a snapshot filename: "
                "only ASCII letters, digits, '_' and '-' are allowed"
            )
    return directory / f"health-{venue}-{city}.json"


# ---------------------------------------------------------------------------
# Per-site poll stagger
# ---------------------------------------------------------------------------


def site_stagger_offset_seconds(index: int, site_count: int, poll_interval_seconds: int) -> int:
    """Return the phase offset, in seconds, for the site at `index`.

    Five sites on a 300s interval get 0/60/120/180/240 -- evenly spread
    across exactly one poll interval, so the aggregate request rate to
    `api.weather.gov` is one request per `interval / site_count` instead of
    five simultaneous ones per interval. Simultaneous bursts under a single
    User-Agent are the documented route into the NWS UA trap, which latches
    every site at once and clears only by manual operator action.

    Deterministic and pure: derived only from the site's position in the
    configured site set, so the same deployment produces the same offsets on
    every restart and an incident is reproducible. A random or
    start-time-derived offset would not be.

    The offset never changes the CADENCE -- see
    `NwsIngestActor._stagger_start_time`, which feeds it to the native
    `Clock.set_timer(start_time=...)`.

    Distinctness holds while `site_count <= poll_interval_seconds`. Breezy
    serves five sites on a 300s default; a deployment with more sites than
    seconds in its poll interval is not a supported shape, and collapsing
    offsets there degrades to today's behaviour rather than misbehaving.
    """
    if site_count <= 0:
        raise ValueError(f"site_count must be positive, was {site_count}")
    if not 0 <= index < site_count:
        raise ValueError(f"index {index} is out of range for site_count {site_count}")
    return (index * int(poll_interval_seconds)) // site_count


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def load_site_registry(settings: BreezyRuntimeSettings) -> SiteRegistry:
    """Return the site registry: the packaged default, or ``registry_path``.

    ``default_registry()`` is ``lru_cache``d, so the common path pays for the
    TOML parse once per process. An explicit ``registry_path`` bypasses that
    cache deliberately -- a caller who names a file wants that file re-read,
    and ``load_registry`` raises ``FileNotFoundError`` if it is absent rather
    than silently falling back to the packaged one.
    """
    if settings.registry_path is None:
        return default_registry()
    return load_registry(settings.registry_path)


# ---------------------------------------------------------------------------
# The runtime bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreezyIngestRuntime:
    """Every constructed component of one ingestion process.

    Note on ``shared``: ``ActorFactory.create`` instantiates each Actor as
    ``actor_cls(config)`` (``common/config.py:614``) -- config only, with no
    seam for a live object. ``NwsIngestActor.__init__`` requires
    ``shared=``, so these Actors cannot come from ``TradingNodeConfig.actors``
    at all. :func:`build_ingest_actors` constructs them here instead and
    :func:`build_ingest_node` registers them through the native
    ``Trader.add_actor``.
    """

    settings: BreezyRuntimeSettings
    registry: SiteRegistry
    store: ClosableStateStore
    shared: SharedIngestState
    node_config: TradingNodeConfig
    #: The ONE process-wide `AlertSink`, injected into every Actor by
    #: :func:`build_ingest_actors`. Process-wide and not per-Actor for two
    #: reasons: `resolve_alert_sink()` called five times would build five
    #: `httpx.Client`s and five TLS contexts for a webhook deployment, and
    #: -- worse -- the transition/re-notify dedupe in `AlertState` would be
    #: correct per Actor while the SINK-side view of the deployment
    #: fragmented across five independent transports.
    alert_sink: AlertSink


def _close_alert_sink(sink: AlertSink) -> None:
    """Release whatever transport `sink` owns, if it owns one.

    Best-effort and never raising: teardown of an OBSERVABILITY component
    must not be able to mask the real exception that is already unwinding
    the `ExitStack`. `LoggingAlertSink` has nothing to close and is left
    alone.
    """
    closer = getattr(sink, "close", None)
    if not callable(closer):
        return
    try:
        closer()
    except Exception:  # pragma: no cover - defensive
        logger.exception("alert sink close() failed during runtime teardown")


@contextmanager
def ingest_runtime(
    settings: BreezyRuntimeSettings,
    *,
    clock: Callable[[], int] | None = None,
    probe: ProbeFactory = probe_filesystem,
    store_factory: StoreFactory = SqliteStateStore,
    alert_sink_factory: AlertSinkFactory = resolve_alert_sink,
) -> Iterator[BreezyIngestRuntime]:
    """Construct, yield, and reliably tear down one ingestion runtime.

    ``clock`` defaults to ``time.time_ns``. It is the ONE nanosecond clock the
    gate, the product index, the transport and the cross-site burst window all
    read; a per-Actor Nautilus ``Clock`` cannot serve that role because each
    Actor gets its own (``trading/trader.py:342``).

    ``probe`` and ``store_factory`` are injected for the same reason
    ``SharedIngestState`` takes a ``probe``: every teardown path stays
    reachable in a test without a real mount or a real failure.

    ``alert_sink_factory`` defaults to ``health.resolve_alert_sink``, which
    returns a ``LoggingAlertSink`` unless ``BREEZY_ALERT_WEBHOOK_URL`` is set
    -- so an unconfigured deployment builds no ``httpx.Client``, opens no
    socket, and touches no ``ssl`` module state. It is called EXACTLY ONCE
    here, and the resulting sink is shared by all five Actors.
    """
    if clock is None:
        import time

        clock = time.time_ns

    # Built first, deliberately: it allocates nothing and validates the
    # trader id, so a malformed setting fails before any handle is opened.
    node_config = build_node_config(settings)
    registry = load_site_registry(settings)

    with ExitStack() as stack:
        store = store_factory(settings.state_db_path)
        stack.callback(store.close)

        # Out-of-band bootstrap witness: detects the whole state-DB file
        # being deleted and recreated (a case no witness stored INSIDE that
        # same file can survive -- see
        # ``breezy.runtime.bootstrap_witness`` for the full rationale). Runs
        # before anything else touches ``store`` so a tampered store is
        # caught before the gate or the product index read it.
        enforce_bootstrap_witness(store, catalog_base=settings.catalog_base)

        # The durability probe needs a SECOND, independent handle on the same
        # backing medium -- for `SqliteStateStore` a fresh connection to the
        # same file. Built from the same `store_factory` and the same path, so
        # a test that injects a fake store gets a probe against that same fake
        # rather than against the real one.
        def open_state_store_view() -> ClosableStateStore:
            return store_factory(settings.state_db_path)

        shared = SharedIngestState(
            registry=registry,
            sites=settings.sites,
            catalog_base=settings.catalog_base,
            store=store,
            clock=clock,
            store_opener=open_state_store_view,
            check_proxy_env=settings.check_proxy_env,
            probe=probe,
        )
        stack.callback(shared.dispose)

        # Built after `shared` so a startup precondition failure short-
        # circuits before any transport is constructed, and released on the
        # way back out. `AlertSink` is a Protocol with only `emit`; a sink
        # that owns a transport is expected to expose `close()`, and one
        # that owns nothing (`LoggingAlertSink`) does not -- hence the
        # duck-typed check rather than a widened Protocol.
        alert_sink = alert_sink_factory()
        stack.callback(_close_alert_sink, alert_sink)

        logger.info(
            "breezy ingest runtime composed: trader_id=%s sites=%s catalog_base=%s state_db=%s",
            settings.trader_id,
            settings.sites,
            settings.catalog_base,
            settings.state_db_path,
        )

        yield BreezyIngestRuntime(
            settings=settings,
            registry=registry,
            store=store,
            shared=shared,
            node_config=node_config,
            alert_sink=alert_sink,
        )


# ---------------------------------------------------------------------------
# Actor construction and native registration
# ---------------------------------------------------------------------------
#
# Why the Actors are built here rather than declared in the node config
# ---------------------------------------------------------------------
# `ActorFactory.create` ends in ``actor_cls(config)`` (``common/config.py:614``)
# -- exactly one positional argument, produced by round-tripping the config
# through JSON. `NwsIngestActor.__init__` is ``(config, *, shared, ...)`` with
# ``shared`` REQUIRED, and `breezy.ingest.shared_state` deliberately offers no
# module-level ``current()`` accessor, because a global getter is precisely how
# a second, unnoticed component graph gets built. So the config-driven route
# cannot construct these Actors, and no amount of config shaping changes that.
#
# The native alternative needs nothing built: ``Trader.add_actor(actor)``
# (``trading/trader.py:312``; ``add_actors`` at ``:355``) accepts an
# ALREADY-CONSTRUCTED Actor, and ``TradingNode.trader`` (``live/node.py:139``)
# exposes it. ``TradingNode.__init__`` builds the kernel -- and therefore the
# trader -- before ``build()`` is called, so registration happens on a node
# that has opened no client and no socket.
#
# Nothing in NautilusTrader is modified, subclassed around, or reimplemented,
# and no DI container or service locator is introduced: the dependency is
# passed explicitly, by hand, exactly once per Actor.


class IngestNode(Protocol):
    """The `TradingNode` surface :func:`build_ingest_node` touches.

    Narrow on purpose: a test can supply a recording double without standing
    up an event loop, and this states exactly which two members the wiring
    depends on.
    """

    @property
    def trader(self) -> Any: ...


IngestNodeFactory = Callable[[TradingNodeConfig], Any]


def build_ingest_actors(runtime: BreezyIngestRuntime) -> tuple[NwsIngestActor, ...]:
    """Return one :class:`NwsIngestActor` per configured site, `shared` injected.

    Order follows ``settings.sites`` so the registration order is the
    configuration order and therefore reproducible.

    ``component_id`` comes from
    :func:`breezy.runtime.node_config.actor_component_id` -- the same function
    the config-driven route used -- because all five Actors are the same class
    and would otherwise adopt the class name as their id and collide inside
    ``Trader.add_actor``.

    Call this ONCE per runtime: ``NwsIngestActor.__init__`` registers itself
    with the shared state, and a second registration for the same site raises
    ``DuplicateSiteRegistrationError`` by design.
    """
    settings = runtime.settings
    site_count = len(settings.sites)
    snapshot_dir = settings.health_snapshot_dir

    actors: list[NwsIngestActor] = []
    for index, (venue, city) in enumerate(settings.sites):
        actor = NwsIngestActor(
            config=NwsIngestActorConfig(
                component_id=actor_component_id(venue, city),
                venue=venue,
                city=city,
                poll_interval_seconds=settings.poll_interval_seconds,
                parse_timeout_ms=settings.parse_timeout_ms,
                stagger_offset_seconds=site_stagger_offset_seconds(
                    index, site_count, settings.poll_interval_seconds
                ),
            ),
            shared=runtime.shared,
        )
        # The two post-construction seams `NwsIngestActor` exposes. They are
        # attributes rather than config fields because `ActorConfig` is
        # msgspec-serialisable and can carry neither a `Path` nor a live
        # `AlertSink`; setting them HERE is what makes the health snapshot
        # and the alerts exist in production at all. Left unset, the Actor
        # writes no file and lazily resolves its own private sink.
        actor.alert_sink = runtime.alert_sink
        if snapshot_dir is not None:
            actor.health_snapshot_path = site_snapshot_path(snapshot_dir, venue, city)
        actors.append(actor)
    return tuple(actors)


def build_ingest_node(
    runtime: BreezyIngestRuntime,
    *,
    node_factory: IngestNodeFactory = TradingNode,
) -> Any:
    """Build the node for ``runtime`` and register its ingest Actors natively.

    ``node_factory`` is injected for the same reason every other seam in this
    module is: the whole wiring stays exercisable against a recording double
    with no event loop, and against the real ``TradingNode`` without ever
    calling ``build()`` or ``run()``.

    The node is NOT built or run here. Lifecycle stays with the caller, which
    already owns ``dispose()``.
    """
    node = node_factory(runtime.node_config)
    actors = build_ingest_actors(runtime)
    for actor in actors:
        node.trader.add_actor(actor)
    logger.info(
        "registered %d ingest actor(s) via Trader.add_actor: %s",
        len(actors),
        [str(a.id) for a in actors],
    )
    return node
