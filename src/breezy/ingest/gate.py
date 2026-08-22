"""Per-site settlement gate: the safety state machine an ingest Actor holds.

Governing rule (docs/plans/WEATHER_INGESTION_PROPOSAL.md §6):
**enrichment degrades, settlement halts.**

This module is deliberately Nautilus-free (no ``import nautilus_trader``
here) so it stays unit-testable in complete isolation. The eventual ingest
Actor is expected to construct a :class:`SettlementGate`, back its
:class:`StateStore` with ``Cache.add``/``Cache.get``, and drive its injected
clock from ``Actor.clock.timestamp_ns``.

Three states per ``(venue, city)`` site: ``OPEN``, ``DEGRADED``, ``BLOCKED``.
A site **defaults to BLOCKED** until a successful verified poll -- an
earlier design held state in memory with no initial value, which let a
crash-loop launder every halt. A site this module knows nothing about is
never open for trading.

State is persisted through an injected :class:`StateStore` and reloaded
lazily per key, so a fresh :class:`SettlementGate` instance backed by the
same store restores exactly the prior state, and one backed by an empty
store still defaults every site to ``BLOCKED``. :meth:`SettlementGate.require_open`
re-derives the state on every call rather than trusting a cached decision,
so a caller can never read a stale "was open a minute ago" answer.

The clock is always injected as a ``Callable[[], int]`` returning
nanoseconds -- never read from the wall clock directly -- so replay fidelity
holds and the freshness watchdog is fully deterministic under test.

Two different questions get two different answers, deliberately never
merged into one. ``GateStatus.reason``/``detail`` is the last transition
EVENT -- an append-friendly audit fact ("what just happened", e.g. a poll
genuinely succeeded at 07:30) -- while :meth:`SettlementGate.blocking_causes`
is a derived, read-only query of every currently-active reason a site is
not OPEN ("why is it like this right now", e.g. ACIS still disagrees even
though that poll succeeded). Do not "fix" a site that logs
``reason=SUCCESSFUL_POLL`` while still BLOCKED -- that is both fields
doing their job.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_GLOBAL_KEY = "gate:__global__"
_TRANSIENT_DEGRADE_THRESHOLD = 3
_NS_PER_SECOND = 1_000_000_000


def _site_key(venue: str, city: str) -> str:
    return f"gate:{venue}:{city}"


# ---------------------------------------------------------------------------
# Public enums / value types
# ---------------------------------------------------------------------------


class GateState(str, Enum):
    """The three states a site can be in. Ordering carries no meaning."""

    OPEN = "OPEN"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class GateReason(str, Enum):
    """Why a site is in its current state -- an operational question someone
    will ask at 07:30. Every transition records one of these plus free text.
    """

    NEVER_POLLED = "never_polled"
    SUCCESSFUL_POLL = "successful_poll"
    UA_TRAP_403 = "ua_trap_403"
    MANUAL_UA_TRAP_CLEARED = "manual_ua_trap_cleared"
    ABUSE_BLOCK_403 = "abuse_block_403"
    TRANSIENT_FAILURE = "transient_failure"
    TRANSIENT_WINDOW_ELAPSED = "transient_window_elapsed"
    PARSER_FAILURE = "parser_failure"
    SANITY_VIOLATION = "sanity_violation"
    AMBIGUOUS_HEADLINE = "ambiguous_headline"
    OVERSIZE_OR_PARSE_TIMEOUT = "oversize_or_parse_timeout"
    CROSS_CHECK_UNAVAILABLE = "cross_check_unavailable"
    CROSS_CHECK_WINDOW_ELAPSED = "cross_check_window_elapsed"
    CROSS_CHECK_RESUMED = "cross_check_resumed"
    ACIS_DISAGREEMENT = "acis_disagreement"
    ACIS_RESUMED = "acis_resumed"
    TASK_DEATH = "task_death"
    REDIRECT_INTEGRITY_ALARM = "redirect_integrity_alarm"
    CLIENT_ERROR_DEFECT = "client_error_defect"
    STALE_DEGRADED = "stale_degraded"
    STALE_BLOCKED = "stale_blocked"
    CLOCK_REGRESSION = "clock_regression"
    CORRUPT_PERSISTED_STATE = "corrupt_persisted_state"
    FINAL_CLI_OVERDUE = "final_cli_overdue"
    FINAL_RECEIVED = "final_received"
    WRITE_INTEGRITY_VIOLATION = "write_integrity_violation"
    TRANSPORT_INTEGRITY_ALARM = "transport_integrity_alarm"


# Reasons the proposal's §6 table tags CRIT, logged at CRITICAL regardless of
# the derived GateState's usual log level.
_CRIT_REASONS = frozenset(
    {
        GateReason.UA_TRAP_403,
        GateReason.PARSER_FAILURE,
        GateReason.SANITY_VIOLATION,
        GateReason.AMBIGUOUS_HEADLINE,
        GateReason.OVERSIZE_OR_PARSE_TIMEOUT,
        GateReason.TASK_DEATH,
        GateReason.REDIRECT_INTEGRITY_ALARM,
        GateReason.CLIENT_ERROR_DEFECT,
        GateReason.CLOCK_REGRESSION,
        GateReason.CORRUPT_PERSISTED_STATE,
        GateReason.FINAL_CLI_OVERDUE,
        GateReason.WRITE_INTEGRITY_VIOLATION,
        GateReason.TRANSPORT_INTEGRITY_ALARM,
    }
)

_LOG_LEVEL_BY_STATE: dict[GateState, int] = {
    GateState.OPEN: logging.INFO,
    GateState.DEGRADED: logging.WARNING,
    GateState.BLOCKED: logging.ERROR,
}


@dataclass(frozen=True, slots=True)
class GateStatus:
    """Read-only snapshot returned by every gate query/mutation."""

    venue: str
    city: str
    state: GateState
    reason: GateReason
    detail: str
    at_ns: int
    last_successful_poll_ns: int | None


class GateBlockedError(Exception):
    """Raised by :meth:`SettlementGate.require_open` when a site is not OPEN."""

    def __init__(self, status: GateStatus) -> None:
        super().__init__(
            f"{status.venue}/{status.city} is {status.state.value} "
            f"(reason={status.reason.value}: {status.detail})"
        )
        self.status = status


# ---------------------------------------------------------------------------
# Cross-site 403 burst policy
#
# Defined ONCE, here. `shared_state.py` imports and re-exports these two
# names rather than redefining them -- two definitions of "what counts as a
# burst" is exactly the drift that let the UA-trap gap this module fixes
# exist in the first place (the gate's own derivation and the legacy
# in-memory window must agree on window/threshold, or "the gate detected a
# burst" and "the window detected a burst" quietly stop meaning the same
# thing). Named `DEFAULT_BURST_POLICY`, matching the constant's pre-existing
# name in `shared_state.py` -- an earlier design note called it
# `DEFAULT_CROSS_SITE_BURST_POLICY`; that name never shipped, so this keeps
# the one that is actually in use rather than forcing every existing import
# to rename.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CrossSiteBurstPolicy:
    """What counts as a cross-site 403 burst.

    Attributes
    ----------
    window_ns : int
        How long one site's 403 stays as evidence, in nanoseconds.
    site_threshold : int
        How many DISTINCT sites must show a same-cause 403 inside that window.

    Design, and why each number is what it is
    -----------------------------------------
    **Distinct sites, never events.** Repeated 403s from one city are exactly
    the per-site abuse block the gate already handles by degrading that one
    city. Counting events would let a single city's retry loop manufacture a
    global halt -- the one direction where "bias toward halting" is actually
    wrong, because it makes an all-site halt reachable from a single-site
    fault. ``site_threshold`` below 2 is refused for that reason.

    **Two sites, not three.** A UA trap is a property of the ``User-Agent``,
    which is process-global: under a trap, every site 403s. With five sites on
    a slow poll cadence, waiting for a third city costs another full poll
    cycle, and every cycle spent 403-ing is more evidence to NWS that we are a
    bad actor. Two cities failing the same way inside two minutes has no benign
    explanation -- per-caller throttling arrives as a 429, not a 403, and NWS
    403s are not per-location. The bias is deliberate and stated in the brief:
    an unnecessary global halt costs trading time and clears with an operator
    acknowledgement; a missed UA trap costs API access outright.

    **120 seconds.** It must comfortably exceed the natural stagger between two
    cities' polls and stay far below the time a trap takes to matter. With a
    ~5-minute per-site cadence across five staggered sites, two cities' polls
    land within roughly a minute of each other; 120 s leaves a full stagger of
    headroom while keeping two genuinely unrelated 403s hours apart from
    combining. The window does **not** need to span a whole poll cycle: a trap
    403s *every* request, so the second city's very next poll supplies the
    second data point.

    This same policy now governs two independent burst signals: the legacy
    in-memory :class:`~breezy.ingest.shared_state.CrossSite403Window` (kept
    during the transition -- see :meth:`SettlementGate.record_forbidden_403`)
    and the gate's own derivation from durably persisted per-site
    ``abuse_403_last_ns`` state. One policy, two readers, so they can never
    silently disagree on what a burst is.
    """

    window_ns: int
    site_threshold: int

    def __post_init__(self) -> None:
        if self.window_ns <= 0:
            raise ValueError(f"`window_ns` must be positive, was {self.window_ns}")
        if self.site_threshold < 2:
            raise ValueError(
                "`site_threshold` must be at least 2: a threshold of 1 makes a "
                "CROSS-site window fire on a single site, which is the per-site "
                "abuse block the gate already handles -- and would let one "
                f"city's retry loop halt all five. Was {self.site_threshold}"
            )


#: Two distinct sites, same cause, inside two minutes. See
#: :class:`CrossSiteBurstPolicy` for the derivation of both numbers.
DEFAULT_BURST_POLICY = CrossSiteBurstPolicy(
    window_ns=120 * _NS_PER_SECOND,
    site_threshold=2,
)


# ---------------------------------------------------------------------------
# Injectable persistence seam
# ---------------------------------------------------------------------------


class StateStore(Protocol):
    """The minimal persistence seam this module needs.

    The eventual ingest Actor backs this with ``Cache.add(str, bytes)`` /
    ``Cache.get(str)``. Deliberately narrower than a full key-value store so
    a fake for tests is a five-line class.
    """

    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes) -> None: ...


class InMemoryStateStore:
    """A trivial in-process :class:`StateStore`, for tests and standalone use
    before an Actor wires in ``Cache.add``/``Cache.get``.
    """

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self._data[key] = value


# ---------------------------------------------------------------------------
# Internal persisted state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SiteEntry:
    last_successful_poll_ns: int | None = None
    transient_failure_count: int = 0
    transient_blocked: bool = False
    abuse_403_degraded: bool = False
    # REFRESH semantics, not latch-once: set to `now` on EVERY 403 for this
    # site (see record_forbidden_403), never only the first. A site 403ing
    # every poll for an hour must still read as CURRENT evidence to the
    # cross-site burst derivation -- latching once-until-cleared (the
    # cross_check_unavailable_since_ns idiom below) would let an actively
    # trapped site age out of its own window and silently stop counting.
    abuse_403_last_ns: int | None = None
    parser_failure: bool = False
    sanity_violation: bool = False
    ambiguous_headline: bool = False
    oversize_or_timeout: bool = False
    cross_check_unavailable_since_ns: int | None = None
    cross_check_blocked: bool = False
    acis_disagreement: bool = False
    task_dead: bool = False
    redirect_integrity_alarm: bool = False
    client_error_defect: bool = False
    clock_regression: bool = False
    final_overdue: bool = False
    final_overdue_climate_day: str | None = None
    write_integrity_violation: bool = False
    transport_integrity_alarm: bool = False
    stale_degraded: bool = False
    stale_blocked: bool = False
    last_reason: GateReason = GateReason.NEVER_POLLED
    last_detail: str = ""
    last_transition_ns: int = 0


@dataclass(frozen=True, slots=True)
class _GlobalEntry:
    ua_trap_blocked: bool = False
    reason: GateReason = GateReason.NEVER_POLLED
    detail: str = ""
    at_ns: int = 0
    # Persisted, cross-restart "has ANY site ever had a successful poll"
    # latch -- deliberately NOT a process-lifetime flag. A UA-trap
    # heuristic keyed on an in-memory flag resets to "cold start" on every
    # restart and, worse, latches permanently false after the first-ever
    # success, misclassifying a genuine mid-session UA-trap onset as a
    # per-site abuse block. See record_forbidden_403.
    any_site_ever_succeeded: bool = False


def _site_entry_to_bytes(entry: _SiteEntry) -> bytes:
    payload = asdict(entry)
    payload["last_reason"] = entry.last_reason.value
    return json.dumps(payload).encode("utf-8")


def _site_entry_from_bytes(raw: bytes) -> _SiteEntry:
    payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
    payload["last_reason"] = GateReason(payload["last_reason"])
    return _SiteEntry(**payload)


def _global_entry_to_bytes(entry: _GlobalEntry) -> bytes:
    payload = asdict(entry)
    payload["reason"] = entry.reason.value
    return json.dumps(payload).encode("utf-8")


def _global_entry_from_bytes(raw: bytes) -> _GlobalEntry:
    payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
    payload["reason"] = GateReason(payload["reason"])
    return _GlobalEntry(**payload)


def _derive_state(entry: _SiteEntry) -> GateState:
    """The single source of truth for a site's derived state.

    Written as an explicit early-return chain (rather than one boolean
    expression) so every condition is its own branch: this is a small,
    fully enumerable state machine, and an untaken branch here is a site
    trading on data it should have halted.
    """
    if entry.last_successful_poll_ns is None:
        return GateState.BLOCKED
    if entry.transient_blocked:
        return GateState.BLOCKED
    if entry.parser_failure:
        return GateState.BLOCKED
    if entry.sanity_violation:
        return GateState.BLOCKED
    if entry.ambiguous_headline:
        return GateState.BLOCKED
    if entry.oversize_or_timeout:
        return GateState.BLOCKED
    if entry.cross_check_blocked:
        return GateState.BLOCKED
    if entry.acis_disagreement:
        return GateState.BLOCKED
    if entry.task_dead:
        return GateState.BLOCKED
    if entry.redirect_integrity_alarm:
        return GateState.BLOCKED
    if entry.client_error_defect:
        return GateState.BLOCKED
    if entry.clock_regression:
        return GateState.BLOCKED
    if entry.final_overdue:
        return GateState.BLOCKED
    if entry.write_integrity_violation:
        return GateState.BLOCKED
    if entry.transport_integrity_alarm:
        return GateState.BLOCKED
    if entry.stale_blocked:
        return GateState.BLOCKED
    if entry.transient_failure_count >= _TRANSIENT_DEGRADE_THRESHOLD:
        return GateState.DEGRADED
    if entry.abuse_403_degraded:
        return GateState.DEGRADED
    if entry.cross_check_unavailable_since_ns is not None:
        return GateState.DEGRADED
    if entry.stale_degraded:
        return GateState.DEGRADED
    return GateState.OPEN


def _blocking_causes(global_entry: _GlobalEntry, entry: _SiteEntry) -> tuple[GateReason, ...]:
    """Every currently-active reason this site is not OPEN, most severe
    first (the global UA-trap, then BLOCKED-tier site causes, then
    DEGRADED-tier site causes). Purely derived -- no persisted field is
    read here beyond what :func:`_derive_state` already reads, and nothing
    is written.

    Mirrors ``_derive_state``'s condition list exactly, but APPENDS instead
    of early-returning: the concurrent case is the whole point of this
    function (a site simultaneously ``ACIS_DISAGREEMENT`` and
    ``FINAL_CLI_OVERDUE`` must report both, because clearing only one
    leaves it blocked). Empty return is therefore consistent with, and
    only with, ``_derive_state`` returning ``GateState.OPEN``.
    """
    causes: list[GateReason] = []
    if global_entry.ua_trap_blocked:
        causes.append(global_entry.reason)
    if entry.last_successful_poll_ns is None:
        causes.append(GateReason.NEVER_POLLED)
    if entry.transient_blocked:
        causes.append(GateReason.TRANSIENT_WINDOW_ELAPSED)
    if entry.parser_failure:
        causes.append(GateReason.PARSER_FAILURE)
    if entry.sanity_violation:
        causes.append(GateReason.SANITY_VIOLATION)
    if entry.ambiguous_headline:
        causes.append(GateReason.AMBIGUOUS_HEADLINE)
    if entry.oversize_or_timeout:
        causes.append(GateReason.OVERSIZE_OR_PARSE_TIMEOUT)
    if entry.cross_check_blocked:
        causes.append(GateReason.CROSS_CHECK_WINDOW_ELAPSED)
    if entry.acis_disagreement:
        causes.append(GateReason.ACIS_DISAGREEMENT)
    if entry.task_dead:
        causes.append(GateReason.TASK_DEATH)
    if entry.redirect_integrity_alarm:
        causes.append(GateReason.REDIRECT_INTEGRITY_ALARM)
    if entry.client_error_defect:
        causes.append(GateReason.CLIENT_ERROR_DEFECT)
    if entry.clock_regression:
        causes.append(GateReason.CLOCK_REGRESSION)
    if entry.final_overdue:
        causes.append(GateReason.FINAL_CLI_OVERDUE)
    if entry.write_integrity_violation:
        causes.append(GateReason.WRITE_INTEGRITY_VIOLATION)
    if entry.transport_integrity_alarm:
        causes.append(GateReason.TRANSPORT_INTEGRITY_ALARM)
    if entry.stale_blocked:
        causes.append(GateReason.STALE_BLOCKED)
    # The three lines below are each the DEGRADED-tier rung of a watchdog
    # that ALSO has a BLOCKED-tier rung above (transient / cross-check /
    # staleness): reaching the higher rung leaves the lower rung's flag set
    # too (by construction -- e.g. check_freshness sets stale_degraded=True
    # alongside stale_blocked=True), so without the "not already blocked"
    # guard these would double-report ONE escalating watchdog as if it
    # were two independent causes. abuse_403_degraded has no BLOCKED-tier
    # counterpart, so it is never guarded.
    if entry.transient_failure_count >= _TRANSIENT_DEGRADE_THRESHOLD and not entry.transient_blocked:
        causes.append(GateReason.TRANSIENT_FAILURE)
    if entry.abuse_403_degraded:
        causes.append(GateReason.ABUSE_BLOCK_403)
    if entry.cross_check_unavailable_since_ns is not None and not entry.cross_check_blocked:
        causes.append(GateReason.CROSS_CHECK_UNAVAILABLE)
    if entry.stale_degraded and not entry.stale_blocked:
        causes.append(GateReason.STALE_DEGRADED)
    return tuple(causes)


def _log_transition(venue: str, city: str, state: GateState, reason: GateReason, detail: str) -> None:
    level = logging.CRITICAL if reason in _CRIT_REASONS else _LOG_LEVEL_BY_STATE[state]
    logger.log(
        level,
        "gate transition venue=%s city=%s state=%s reason=%s detail=%s",
        venue,
        city,
        state.value,
        reason.value,
        detail,
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class SettlementGate:
    """Per-``(venue, city)`` OPEN/DEGRADED/BLOCKED state machine.

    Construct once per process, backed by a persistent :class:`StateStore`
    and an injected clock. State for a given site is loaded lazily (on
    first access) from the store, cached in memory, and written back to the
    store on every mutation -- so a fresh instance over the same store
    restores exactly the prior state, and a site never touched by this
    process still resolves to the persisted answer (or the BLOCKED default
    if the store has never seen it either).

    ``sites`` is the full ``(venue, city)`` set this gate serves, REQUIRED
    (no default) rather than an optional per-call parameter on
    :meth:`record_forbidden_403` -- an earlier design let the site set
    default to empty on any call site that forgot to pass it, silently
    disabling cross-site burst detection with no error and no log. That is
    the exact footgun shape that caused the defect this module fixes, so it
    is closed at construction instead. A ``frozenset`` because it is
    membership-tested and iterated, never indexed, and closes out
    duplicate/self-referencing entries for free -- consistent with
    ``shared_state.DEFAULT_ALLOWED_HOSTS: frozenset[str]``.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        clock: Callable[[], int],
        sites: frozenset[tuple[str, str]],
        burst_policy: CrossSiteBurstPolicy = DEFAULT_BURST_POLICY,
    ) -> None:
        self._store = store
        self._clock = clock
        self._known_sites = sites
        self._burst_policy = burst_policy
        # Per-site entries ARE cached, keyed by (venue, city): each Actor
        # calls _load_site/_save_site ONLY for the one site it owns (module
        # docstring / the ingestion proposal's per-station-Actor design), so
        # no sibling instance can race THAT cached entry stale under normal
        # per-Actor traffic. That invariant does NOT extend to a read of a
        # SIBLING site's entry initiated from within this module (the
        # persisted cross-site-burst derivation, and
        # acknowledge_ua_trap_resolved()'s evidence clear) -- those go
        # through _load_sibling_site, which reads straight through the store
        # on every call, exactly like _load_global and for the identical
        # reason: correctness here must never depend on an invariant (one
        # Actor per site) that is enforced in a DIFFERENT module
        # (shared_state.py's register_site_actor), not in this one. The
        # GLOBAL entry has no per-site-ownership guarantee at all -- see
        # _load_global -- so it is deliberately NOT cached here either.
        self._sites: dict[tuple[str, str], _SiteEntry] = {}

    def _now(self) -> int:
        return self._clock()

    def _load_site(self, venue: str, city: str) -> _SiteEntry:
        key = (venue, city)
        cached = self._sites.get(key)
        if cached is not None:
            return cached
        raw = self._store.get(_site_key(venue, city))
        if raw is None:
            entry = _SiteEntry()
        else:
            try:
                entry = _site_entry_from_bytes(raw)
            except (ValueError, TypeError, KeyError) as exc:
                # Corrupt or schema-drifted bytes must never propagate as a
                # bare decode exception out of status()/require_open() --
                # every other blocked path funnels through GateBlockedError,
                # and a caller doing the right thing (catching that type
                # around require_open) must not crash on this one path
                # instead. Fail closed to the default BLOCKED entry (never
                # polled), stamped with a reason that tells an operator this
                # was corruption, not an ordinary halt. The bad bytes are
                # left untouched in the store -- this is a purely in-memory
                # recovery, not a silent rewrite of forensic evidence.
                logger.critical(
                    "gate: corrupt persisted site state for venue=%s city=%s "
                    "-- failing closed to BLOCKED. error=%s",
                    venue,
                    city,
                    exc,
                )
                entry = replace(
                    _SiteEntry(),
                    last_reason=GateReason.CORRUPT_PERSISTED_STATE,
                    last_detail=f"corrupt persisted bytes: {exc}",
                    last_transition_ns=self._now(),
                )
        self._sites[key] = entry
        return entry

    def _load_global(self) -> _GlobalEntry:
        """Read the global entry straight through the store on EVERY call
        -- deliberately never cached.

        The five per-station Actors each construct their own
        SettlementGate over a SHARED store. If the global entry were
        cached (as it once was), Actor A setting a UA-trap block would
        write to the store while Actors B-E kept serving their own stale
        in-memory copy, so the trap would fail to block the other four
        sites -- defeating the entire reason the latch is global rather
        than per-site. One extra ``store.get`` per check against a local
        cache-backed database is a correctness requirement, not an
        optimization to weigh against cost.
        """
        raw = self._store.get(_GLOBAL_KEY)
        if raw is None:
            return _GlobalEntry()
        try:
            return _global_entry_from_bytes(raw)
        except (ValueError, TypeError, KeyError) as exc:
            # Same fail-safe posture as _load_site, but the conservative
            # default for the GLOBAL flag is the opposite of neutral:
            # corrupted global bytes could have been a live UA-trap
            # block, and silently defaulting to "not blocked" would
            # reopen every site with no verified fix -- the exact
            # silent-reopen failure mode this module exists to prevent.
            # Block everything and require the same manual
            # acknowledge_ua_trap_resolved() clear a real UA-trap needs.
            logger.critical(
                "gate: corrupt persisted global state -- failing closed, "
                "BLOCKING ALL SITES. error=%s",
                exc,
            )
            return _GlobalEntry(
                ua_trap_blocked=True,
                reason=GateReason.CORRUPT_PERSISTED_STATE,
                detail=f"corrupt persisted bytes: {exc}",
                at_ns=self._now(),
            )

    def _load_sibling_site(self, venue: str, city: str) -> tuple[_SiteEntry, bool]:
        """Read a SIBLING site's entry straight through the store on EVERY
        call -- deliberately never served from ``self._sites``, for exactly
        ``_load_global``'s rationale: this instance's per-site cache is only
        safe for the ONE site the owning Actor calls ``_load_site`` for, and
        that safety invariant is enforced in ``shared_state.py``
        (``register_site_actor``), not here. Reading a sibling through the
        cache would make cross-site burst detection depend on an invariant
        this module cannot itself verify.

        Returns ``(entry, corrupt)``. ``corrupt`` is ``True`` when the
        sibling's persisted bytes could not be decoded -- the caller
        (:meth:`_derive_cross_site_burst`) must treat that as burst evidence
        rather than silence, exactly the corrupt-sibling CRITICAL this
        method exists to make possible: a naive predicate that only counts
        sites with valid, still-fresh ``abuse_403_last_ns`` would let
        corrupting a single site's bytes silently zero out its contribution
        to the burst count -- failing OPEN on exactly the signal this module
        exists to fail closed on.
        """
        raw = self._store.get(_site_key(venue, city))
        if raw is None:
            return _SiteEntry(), False
        try:
            return _site_entry_from_bytes(raw), False
        except (ValueError, TypeError, KeyError) as exc:
            logger.critical(
                "gate: corrupt persisted SIBLING site state for venue=%s city=%s "
                "while evaluating cross-site burst evidence -- counting it TOWARD "
                "the burst (fail toward halt, never toward silently suppressing "
                "one). error=%s",
                venue,
                city,
                exc,
            )
            return (
                replace(
                    _SiteEntry(),
                    last_reason=GateReason.CORRUPT_PERSISTED_STATE,
                    last_detail=f"corrupt persisted bytes: {exc}",
                    last_transition_ns=self._now(),
                ),
                True,
            )

    def _derive_cross_site_burst(
        self, venue: str, city: str, *, now: int
    ) -> tuple[bool, int, bool]:
        """Cross-site 403 burst evidence derived from state this gate
        already persists durably (``abuse_403_last_ns`` per site), rather
        than a second, weaker in-memory copy of the same evidence -- the
        core approach of this fix. Survives a process restart because it is
        read from the same durable store every other gate decision is.

        The ACTING site (``venue``, ``city``) counts as evidence AT ``now``
        even though ``record_forbidden_403`` has not yet persisted its own
        ``abuse_403_last_ns`` when this runs -- that write happens only
        after the UA-trap-vs-abuse decision this derivation feeds. Without
        including it here, the second half of a two-site burst would never
        see itself as one of the two sites.

        Every OTHER configured site (``self._known_sites``) is read through
        :meth:`_load_sibling_site` (never the per-Actor cache) and counts as
        fresh evidence when its persisted ``abuse_403_last_ns`` is within
        ``policy.window_ns`` of ``now``, using the SAME strict ``<`` (never
        ``<=``) as ``shared_state._within_window`` -- a boundary-equal
        timestamp is NOT current evidence, and a backward clock jump
        (``now - at_ns`` negative, trivially ``< window_ns``) is KEPT rather
        than evicted, biasing toward halting on the cheap-error side. A
        sibling whose persisted bytes are undecodable counts TOWARD the
        burst unconditionally (see :meth:`_load_sibling_site`) since there
        is no timestamp to check freshness against, and corruption itself is
        exactly the kind of signal this module fails closed on.

        Returns ``(detected, distinct_site_count, near_miss)``.
        ``near_miss`` is ``True`` iff ``distinct_site_count`` is exactly one
        short of ``policy.site_threshold`` -- observability for the silent
        under-detection that would otherwise be invisible (see
        :meth:`record_forbidden_403`).
        """
        policy = self._burst_policy
        acting_site = (venue, city)
        distinct: set[tuple[str, str]] = {acting_site}
        for site in self._known_sites:
            if site == acting_site:
                continue
            sibling_venue, sibling_city = site
            entry, corrupt = self._load_sibling_site(sibling_venue, sibling_city)
            if corrupt:
                distinct.add(site)
                continue
            at_ns = entry.abuse_403_last_ns
            if at_ns is None:
                continue
            if now - at_ns < policy.window_ns:
                distinct.add(site)
        count = len(distinct)
        detected = count >= policy.site_threshold
        near_miss = count == policy.site_threshold - 1
        return detected, count, near_miss

    def _save_site(self, venue: str, city: str, entry: _SiteEntry) -> None:
        # Persist FIRST, cache second. If store.set() raises (or the process
        # dies between the two statements), the in-memory view must never
        # advance ahead of the durable one -- otherwise a halt recorded only
        # in memory is silently lost on restart, with the store still
        # holding the last good (possibly OPEN) state.
        self._store.set(_site_key(venue, city), _site_entry_to_bytes(entry))
        self._sites[(venue, city)] = entry

    def _save_global(self, entry: _GlobalEntry) -> None:
        # No cache to update: _load_global reads through on every call, so
        # persist-before-cache ordering is moot here (a simplification, not
        # a regression of that fix -- the SITE path in _save_site is
        # unchanged and still persists before mutating self._sites).
        self._store.set(_GLOBAL_KEY, _global_entry_to_bytes(entry))

    def _transition_site(
        self, venue: str, city: str, entry: _SiteEntry, *, reason: GateReason, detail: str
    ) -> None:
        at_ns = self._now()
        new_entry = replace(entry, last_reason=reason, last_detail=detail, last_transition_ns=at_ns)
        self._save_site(venue, city, new_entry)
        _log_transition(venue, city, _derive_state(new_entry), reason, detail)

    # -- queries ------------------------------------------------------

    def status(self, venue: str, city: str) -> GateStatus:
        """Re-derive and return the current status for ``(venue, city)``.

        Always recomputed from stored state -- never a cached decision.
        """
        global_entry = self._load_global()
        entry = self._load_site(venue, city)
        if global_entry.ua_trap_blocked:
            return GateStatus(
                venue=venue,
                city=city,
                state=GateState.BLOCKED,
                reason=global_entry.reason,
                detail=global_entry.detail,
                at_ns=global_entry.at_ns,
                last_successful_poll_ns=entry.last_successful_poll_ns,
            )
        return GateStatus(
            venue=venue,
            city=city,
            state=_derive_state(entry),
            reason=entry.last_reason,
            detail=entry.last_detail,
            at_ns=entry.last_transition_ns,
            last_successful_poll_ns=entry.last_successful_poll_ns,
        )

    def require_open(self, venue: str, city: str) -> None:
        """Raise :class:`GateBlockedError` unless ``(venue, city)`` is OPEN.

        Re-checked at use time: callers must call this immediately before
        acting on a site's data, never rely on a decision made earlier.
        """
        status = self.status(venue, city)
        if status.state is not GateState.OPEN:
            raise GateBlockedError(status)

    def blocking_causes(self, venue: str, city: str) -> tuple[GateReason, ...]:
        """Every currently-active reason ``(venue, city)`` is not OPEN,
        most severe first. Empty exactly when :meth:`status` reports
        ``GateState.OPEN``.

        Answers a different question than ``GateStatus.reason``/``detail``
        (see the module docstring): ``reason`` is the last transition
        EVENT ("what just happened" -- an audit-log fact, e.g. a poll
        genuinely succeeded); this is "why is it not OPEN right now" (a
        derived fact, e.g. ACIS still disagrees). A site can log
        ``reason=SUCCESSFUL_POLL`` while ``blocking_causes()`` still
        returns ``(ACIS_DISAGREEMENT,)`` -- both are true, and neither
        should overwrite the other.

        Purely derived: reads persisted state via the same ``_load_site``/
        ``_load_global`` every query uses, stores nothing, and calls
        ``store.set()`` under no circumstance -- including when it falls
        back to a default entry for corrupt bytes, which is itself a
        read-only recovery (see ``_load_site``).
        """
        global_entry = self._load_global()
        entry = self._load_site(venue, city)
        return _blocking_causes(global_entry, entry)

    # -- transitions ----------------------------------------------------

    def record_successful_poll(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """Record a verified successful poll: the only way a site opens.

        Clears every transient-cause flag (failure counters, parser/sanity/
        ambiguous/oversize blocks, cross-check unavailability, task death,
        staleness) AND this site's ``abuse_403_last_ns``/``abuse_403_degraded``
        evidence -- a recovered site must not keep contributing stale 403
        evidence toward a future cross-site burst derivation
        (:meth:`_derive_cross_site_burst`). Deliberately does **not** clear
        an active ACIS disagreement -- that halt requires its own explicit
        resume signal (:meth:`record_acis_agreement`), per the settled
        autonomous-resume rule.
        """
        entry = self._load_site(venue, city)
        now = self._now()
        new_entry = replace(
            entry,
            last_successful_poll_ns=now,
            transient_failure_count=0,
            transient_blocked=False,
            abuse_403_degraded=False,
            abuse_403_last_ns=None,
            parser_failure=False,
            sanity_violation=False,
            ambiguous_headline=False,
            oversize_or_timeout=False,
            cross_check_unavailable_since_ns=None,
            cross_check_blocked=False,
            task_dead=False,
            redirect_integrity_alarm=False,
            client_error_defect=False,
            clock_regression=False,
            write_integrity_violation=False,
            transport_integrity_alarm=False,
            stale_degraded=False,
            stale_blocked=False,
            last_reason=GateReason.SUCCESSFUL_POLL,
            last_detail=detail,
            last_transition_ns=now,
        )
        self._save_site(venue, city, new_entry)
        _log_transition(venue, city, _derive_state(new_entry), GateReason.SUCCESSFUL_POLL, detail)

        # Latch the persisted, cross-restart "any site ever succeeded"
        # signal used by record_forbidden_403's UA-trap classification.
        # One-way (False -> True only) and monotonic, so it is safe -- and
        # deliberately cheap -- to skip the durable write once already set.
        global_entry = self._load_global()
        if not global_entry.any_site_ever_succeeded:
            self._save_global(replace(global_entry, any_site_ever_succeeded=True))

        return self.status(venue, city)

    def record_forbidden_403(
        self, venue: str, city: str, *, detail: str = "", cross_site_burst_detected: bool = False
    ) -> GateStatus:
        """403 Forbidden. A UA-trap blocks every site; a per-site abuse
        block only degrades the offending one (hard backoff is the
        caller's concern).

        The gate classifies UA-trap vs abuse itself, from its OWN
        persisted, cross-restart history -- callers do not pass a
        pre-computed ``is_ua_trap`` bool. An earlier design took that bool
        from an Actor-side heuristic keyed on "no site has succeeded yet
        this process": that flag resets to cold-start on every restart, and
        worse, latches permanently false after the very first success --
        misclassifying a genuine UA-trap onset mid-session (mailbox goes
        unreachable, NWS blocklists the User-Agent) as a per-site abuse
        block, one that each of the other four cities then has to
        independently walk its own 3-strike transient counter to reach,
        instead of an immediate all-site halt.

        UA-trap iff ANY of:
          - no site tracked by this gate has EVER had a persisted
            successful poll (cross-restart cold start; see
            ``_GlobalEntry.any_site_ever_succeeded``), or
          - the caller reports ``cross_site_burst_detected`` -- the legacy,
            in-memory, per-process
            ``shared_state.CrossSite403Window``. Kept ONLY as a transition
            safety net: it is process-lifetime state, so it is exactly the
            arm that goes silent across a restart -- the defect this
            derivation exists to close. OR-ed in rather than removed so the
            transition can only ever *over*-halt (the cheap-error
            direction), never under-halt.
          - this gate's OWN derivation from durably persisted per-site
            ``abuse_403_last_ns`` state (:meth:`_derive_cross_site_burst`)
            finds ``policy.site_threshold`` or more distinct sites with
            fresh (or corrupt-and-therefore-fail-closed) 403 evidence. This
            is the arm that survives a restart: it reads the same durable
            store every other gate decision reads, so a trap whose 403s
            straddle a process restart still trips it, unlike the two arms
            above.

        The safer misclassification direction is trap-over-abuse: an
        unnecessary global halt costs trading time, a missed trap costs
        the API.
        """
        global_entry = self._load_global()
        now = self._now()
        persisted_burst, distinct_sites, near_miss = self._derive_cross_site_burst(
            venue, city, now=now
        )
        is_ua_trap = (
            (not global_entry.any_site_ever_succeeded)
            or cross_site_burst_detected
            or persisted_burst
        )
        if persisted_burst:
            # Equivalent of shared_state.CrossSite403Window.observe()'s own
            # CRITICAL log -- re-emitted here so observability does not
            # regress now that this arm can detect a burst the in-memory
            # window cannot (post-restart). Logged whenever the persisted
            # derivation itself finds a burst, independent of which arm
            # ultimately decided is_ua_trap.
            logger.critical(
                "cross-site 403 burst (persisted-state derivation): %d distinct "
                "sites show fresh or corrupt abuse-403 evidence within "
                "window_ns=%d (threshold=%d) -- treating as UA-trap evidence. "
                "triggering venue=%s city=%s",
                distinct_sites,
                self._burst_policy.window_ns,
                self._burst_policy.site_threshold,
                venue,
                city,
            )
        elif near_miss:
            # A silent under-detection is otherwise invisible: one more
            # distinct site's 403 would have tripped the persisted-state
            # burst derivation. Logged even when another arm already
            # classifies this as a trap, and even when it does not, so an
            # operator triaging at 07:30 can see how close a real per-site
            # abuse pattern is running to trap territory.
            logger.warning(
                "cross-site 403 burst NEAR-MISS (persisted-state derivation): "
                "%d distinct sites show fresh abuse-403 evidence, one short of "
                "threshold=%d within window_ns=%d. venue=%s city=%s",
                distinct_sites,
                self._burst_policy.site_threshold,
                self._burst_policy.window_ns,
                venue,
                city,
            )
        if is_ua_trap:
            new_global = replace(
                global_entry,
                ua_trap_blocked=True,
                reason=GateReason.UA_TRAP_403,
                detail=detail,
                at_ns=now,
            )
            self._save_global(new_global)
            logger.critical(
                "UA-trap 403: BLOCKING ALL SITES venue=%s city=%s detail=%s", venue, city, detail
            )
            return self.status(venue, city)
        entry = self._load_site(venue, city)
        new_entry = replace(entry, abuse_403_degraded=True, abuse_403_last_ns=now)
        self._transition_site(venue, city, new_entry, reason=GateReason.ABUSE_BLOCK_403, detail=detail)
        return self.status(venue, city)

    def acknowledge_ua_trap_resolved(self, *, detail: str = "") -> None:
        """Manually clear a UA-trap global block.

        Unlike ACIS disagreement, a UA-trap is a code/config defect (e.g. a
        stale or malformed User-Agent), so resolving it is never automatic.

        Also clears per-site abuse-403 evidence (``abuse_403_last_ns`` /
        ``abuse_403_degraded``) for EVERY site this gate knows about
        (``self._known_sites``), not only the one an operator happened to be
        looking at. Chosen over the alternative (gating burst evaluation on
        an "ignore evidence older than the last ack" timestamp) because it
        needs no new persisted field and its correctness is visible in
        exactly the same ``abuse_403_last_ns`` :meth:`_derive_cross_site_burst`
        already reads -- no second clock to keep synchronized with the
        first. Without this, stale per-site evidence from BEFORE the ack
        could combine with one unrelated ordinary 403 seconds later and
        immediately re-trip the persisted-state derivation -- a halt loop
        the operator has no way to break, since acknowledging previously
        cleared only the global latch and never the evidence that
        re-derives it.
        """
        now = self._now()
        new_global = replace(
            self._load_global(),
            ua_trap_blocked=False,
            reason=GateReason.MANUAL_UA_TRAP_CLEARED,
            detail=detail,
            at_ns=now,
        )
        self._save_global(new_global)

        for site_venue, site_city in self._known_sites:
            entry = self._load_site(site_venue, site_city)
            if entry.abuse_403_degraded or entry.abuse_403_last_ns is not None:
                cleared = replace(entry, abuse_403_degraded=False, abuse_403_last_ns=None)
                self._save_site(site_venue, site_city, cleared)

        logger.warning("UA-trap 403 condition manually cleared: %s", detail)

    def record_transient_failure(
        self, venue: str, city: str, *, detail: str = "", final_window_elapsed: bool = False
    ) -> GateStatus:
        """429 / 5xx / timeout. DEGRADED after 3 consecutive failures;
        BLOCKED once the caller signals the final retry window has elapsed.

        The window itself is owned by the caller's retry/backoff manager
        (``live/retry.py``'s ``RetryManager``, per the ingestion proposal) --
        this gate does not duplicate that timing logic, only records its
        outcome.
        """
        entry = self._load_site(venue, city)
        new_entry = replace(
            entry,
            transient_failure_count=entry.transient_failure_count + 1,
            transient_blocked=entry.transient_blocked or final_window_elapsed,
        )
        reason = (
            GateReason.TRANSIENT_WINDOW_ELAPSED
            if final_window_elapsed
            else GateReason.TRANSIENT_FAILURE
        )
        self._transition_site(venue, city, new_entry, reason=reason, detail=detail)
        return self.status(venue, city)

    def record_parser_failure(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """Malformed text / parser exception: REJECTED, BLOCK site, CRIT."""
        entry = self._load_site(venue, city)
        new_entry = replace(entry, parser_failure=True)
        self._transition_site(venue, city, new_entry, reason=GateReason.PARSER_FAILURE, detail=detail)
        return self.status(venue, city)

    def record_sanity_violation(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """A physically-impossible value: REJECTED, BLOCK site, CRIT."""
        entry = self._load_site(venue, city)
        new_entry = replace(entry, sanity_violation=True)
        self._transition_site(venue, city, new_entry, reason=GateReason.SANITY_VIOLATION, detail=detail)
        return self.status(venue, city)

    def record_ambiguous_headline(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """Classification could not determine preliminary vs final: BLOCK, CRIT."""
        entry = self._load_site(venue, city)
        new_entry = replace(entry, ambiguous_headline=True)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.AMBIGUOUS_HEADLINE, detail=detail
        )
        return self.status(venue, city)

    def record_oversize_or_parse_timeout(
        self, venue: str, city: str, *, detail: str = ""
    ) -> GateStatus:
        """Oversize body or parse timeout: rejected before parse, BLOCK site."""
        entry = self._load_site(venue, city)
        new_entry = replace(entry, oversize_or_timeout=True)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.OVERSIZE_OR_PARSE_TIMEOUT, detail=detail
        )
        return self.status(venue, city)

    def record_write_integrity_violation(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """A non-empty ``WriteOutcome.skipped`` from the catalog write path
        (full or partial): BLOCK site, CRIT.

        The poll sequence is write -> verify -> ``record_successful_poll``;
        this is the dedicated call for the middle step's failure so a
        silently-unwritten (or partially-written) record never reaches an
        OPEN gate on discipline alone. A batch where one record wrote and
        one skipped is an integrity violation, not a partial success.
        """
        entry = self._load_site(venue, city)
        new_entry = replace(entry, write_integrity_violation=True)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.WRITE_INTEGRITY_VIOLATION, detail=detail
        )
        return self.status(venue, city)

    def record_transport_integrity_alarm(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """A rejected response ``Content-Encoding`` (``ingest/http.py``'s
        ``ContentEncodingError``): BLOCK site, CRIT.

        Decompression would desync the SHA-256 digest (the provenance
        anchor) from the actual wire bytes -- an integrity signal from a
        compromised or malicious allowlisted host, not a transport hiccup.
        This routes it somewhere deliberate rather than letting it fall
        through to generic task-death supervision.
        """
        entry = self._load_site(venue, city)
        new_entry = replace(entry, transport_integrity_alarm=True)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.TRANSPORT_INTEGRITY_ALARM, detail=detail
        )
        return self.status(venue, city)

    def record_cross_check_unavailable(
        self,
        venue: str,
        city: str,
        *,
        detail: str = "",
        conflict_window_elapsed: bool = False,
    ) -> GateStatus:
        """Advisory cross-check (ACIS/METAR) unreachable: DEGRADED, then
        BLOCKED once the caller signals the conflict-review window elapsed.
        """
        entry = self._load_site(venue, city)
        since = entry.cross_check_unavailable_since_ns
        if since is None:
            since = self._now()
        new_entry = replace(
            entry,
            cross_check_unavailable_since_ns=since,
            cross_check_blocked=entry.cross_check_blocked or conflict_window_elapsed,
        )
        reason = (
            GateReason.CROSS_CHECK_WINDOW_ELAPSED
            if conflict_window_elapsed
            else GateReason.CROSS_CHECK_UNAVAILABLE
        )
        self._transition_site(venue, city, new_entry, reason=reason, detail=detail)
        return self.status(venue, city)

    def record_cross_check_available(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """The advisory cross-check is reachable again: resume the site."""
        entry = self._load_site(venue, city)
        new_entry = replace(entry, cross_check_unavailable_since_ns=None, cross_check_blocked=False)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.CROSS_CHECK_RESUMED, detail=detail
        )
        return self.status(venue, city)

    def record_acis_disagreement(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """CLI vs ACIS disagree (>=1F): halt the station (settled operator
        decision 5 -- fully autonomous, auto-resumes on agreement).
        """
        entry = self._load_site(venue, city)
        new_entry = replace(entry, acis_disagreement=True)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.ACIS_DISAGREEMENT, detail=detail
        )
        return self.status(venue, city)

    def record_acis_agreement(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """CLI and ACIS agree again: automatically resume the station.

        No human in the loop, per operator decision 5 -- this is the sole
        mechanism that clears an ACIS-disagreement halt.
        """
        entry = self._load_site(venue, city)
        new_entry = replace(entry, acis_disagreement=False)
        self._transition_site(venue, city, new_entry, reason=GateReason.ACIS_RESUMED, detail=detail)
        return self.status(venue, city)

    def record_task_death(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """The supervised ingest task died: BLOCK site, CRIT."""
        entry = self._load_site(venue, city)
        new_entry = replace(entry, task_dead=True)
        self._transition_site(venue, city, new_entry, reason=GateReason.TASK_DEATH, detail=detail)
        return self.status(venue, city)

    def record_redirect_integrity_alarm(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """A 3xx on a settlement endpoint: BLOCK site, CRIT.

        ``/products/{id}`` bodies are immutable by id -- there is no
        legitimate reason for that URL to redirect. This is an integrity
        signal on the path that determines real-money settlement, not a
        normal fetch outcome, so it fails closed for this site only (unlike
        the UA-trap 403, it implies nothing about the other four cities).
        ``ingest/http.py``'s ``RedirectError`` is the transport-layer signal
        this method is intended to consume.
        """
        entry = self._load_site(venue, city)
        new_entry = replace(entry, redirect_integrity_alarm=True)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.REDIRECT_INTEGRITY_ALARM, detail=detail
        )
        return self.status(venue, city)

    def record_client_error_defect(self, venue: str, city: str, *, detail: str = "") -> GateStatus:
        """A 400 response: BLOCK site, CRIT.

        A 400 means we sent a malformed request -- we have no data for this
        site, and a code defect that may equally be malforming other
        requests we have not yet noticed. Trading a site while we cannot
        construct valid requests for it is trading blind, so it fails
        closed for this site only.
        """
        entry = self._load_site(venue, city)
        new_entry = replace(entry, client_error_defect=True)
        self._transition_site(
            venue, city, new_entry, reason=GateReason.CLIENT_ERROR_DEFECT, detail=detail
        )
        return self.status(venue, city)

    def check_freshness(
        self, venue: str, city: str, *, degraded_after_ns: int, blocked_after_ns: int
    ) -> GateStatus:
        """Watchdog: escalate OPEN -> DEGRADED -> BLOCKED as time since the
        last successful poll (per the injected clock) grows past the given
        thresholds. A no-op if the site has never been successfully polled
        (it is already BLOCKED by default).

        There is deliberately no recovery branch here: freshness is
        *defined* by a recent successful poll, and :meth:`record_successful_poll`
        is the only legitimate way staleness clears. An earlier version
        cleared ``stale_degraded``/``stale_blocked`` whenever a later call's
        *current* elapsed time fell back under the threshold -- which is
        also exactly what happens if the clock ever moves backward, since
        ``elapsed_ns`` was never clamped to non-negative. That let a
        stale-BLOCKED site silently reopen with no new verified poll, log a
        SUCCESSFUL_POLL that never happened, and resume trading. A
        non-monotonic clock is itself a safety event for a settlement
        system (it invalidates every freshness threshold and ``ts_init``
        ordering assumption), so it fails the site closed with its own
        reason instead of being silently clamped.
        """
        entry = self._load_site(venue, city)
        if entry.last_successful_poll_ns is None:
            return self.status(venue, city)

        now = self._now()
        if now < entry.last_successful_poll_ns:
            new_entry = replace(entry, clock_regression=True)
            self._transition_site(
                venue,
                city,
                new_entry,
                reason=GateReason.CLOCK_REGRESSION,
                detail=f"clock moved backward: now={now} last_successful_poll_ns={entry.last_successful_poll_ns}",
            )
            return self.status(venue, city)

        elapsed_ns = now - entry.last_successful_poll_ns
        if elapsed_ns >= blocked_after_ns:
            new_entry = replace(entry, stale_degraded=True, stale_blocked=True)
            self._transition_site(
                venue,
                city,
                new_entry,
                reason=GateReason.STALE_BLOCKED,
                detail=f"elapsed_ns={elapsed_ns}",
            )
        elif elapsed_ns >= degraded_after_ns:
            new_entry = replace(entry, stale_degraded=True, stale_blocked=False)
            self._transition_site(
                venue,
                city,
                new_entry,
                reason=GateReason.STALE_DEGRADED,
                detail=f"elapsed_ns={elapsed_ns}",
            )
        return self.status(venue, city)

    def record_final_overdue(
        self, venue: str, city: str, climate_day: str, deadline_ns: int, *, detail: str = ""
    ) -> GateStatus:
        """The final CLI for ``climate_day`` has not arrived by
        ``deadline_ns`` (08:00 ET, or 11:00 ET inside the venue's
        CLI-vs-METAR review window): BLOCK site, CRIT.

        This is a DATA-COMPLETENESS clock, distinct from the liveness
        clock ``check_freshness`` measures. A site that keeps polling
        cleanly every five minutes and simply never receives the final
        stays "fresh" by the liveness watchdog indefinitely -- freshness
        only proves NWS is still answering, not that today's climate day
        is complete. Overloading the deadline onto ``blocked_after_ns``
        also fails a second way even before that conflation: recomputing
        ``blocked_after_ns = deadline_ns - last_successful_poll_ns`` from a
        moving ``last_successful_poll_ns`` is required for the algebra to
        hold at all (``now - last >= deadline - last`` iff ``now >=
        deadline``); cached once, it fails open. This is why the deadline
        is accepted as an explicit parameter and recorded as its own flag
        instead.

        ``deadline_ns`` is not stored as state -- it is the venue-clock
        instant the Actor (deriving it from the registry) determined had
        passed; it is recorded in the transition detail for audit only.
        Crucially, ``record_successful_poll`` does NOT clear this flag: a
        poll that returns another preliminary is still a successful poll,
        and clearing an overdue-final block on it would launder the block
        away on every clean preliminary poll after the deadline. The only
        clearing path is :meth:`record_final_received` for this specific
        ``climate_day``.
        """
        entry = self._load_site(venue, city)
        new_entry = replace(entry, final_overdue=True, final_overdue_climate_day=climate_day)
        self._transition_site(
            venue,
            city,
            new_entry,
            reason=GateReason.FINAL_CLI_OVERDUE,
            detail=detail or f"final CLI overdue for climate_day={climate_day} deadline_ns={deadline_ns}",
        )
        return self.status(venue, city)

    def record_final_received(self, venue: str, city: str, climate_day: str, *, detail: str = "") -> GateStatus:
        """The final CLI for ``climate_day`` has been received: clear an
        overdue-final block for that specific climate day.

        Keyed by climate day, not just site: a final arriving for
        yesterday must not clear an overdue block for today. A no-op
        (returns the current status unchanged) if nothing is overdue, or
        if what is overdue is a *different* climate day than the one that
        just arrived.
        """
        entry = self._load_site(venue, city)
        if not entry.final_overdue:
            return self.status(venue, city)
        if entry.final_overdue_climate_day != climate_day:
            return self.status(venue, city)
        new_entry = replace(entry, final_overdue=False, final_overdue_climate_day=None)
        self._transition_site(
            venue,
            city,
            new_entry,
            reason=GateReason.FINAL_RECEIVED,
            detail=detail or f"final received for climate_day={climate_day}",
        )
        return self.status(venue, city)


# ---------------------------------------------------------------------------
# Cache-database startup assertion
# ---------------------------------------------------------------------------
#
# Measured against the installed nautilus_trader==1.231.0 tree (never
# assumed -- an earlier draft of this assertion was written against an
# assumed surface and was wrong):
#
# - save_state / load_state live on ``NautilusKernelConfig``
#   (nautilus_trader/system/config.py:122-123, both default False), which
#   is the top-level node/engine config (e.g. ``TradingNodeConfig``) --
#   NOT on ``ActorConfig`` (common/config.py:541-561, which has exactly
#   ``component_id``/``log_events``/``log_commands``) or ``StrategyConfig``
#   (trading/config.py:33-100, same story). An assertion reading
#   ``actor_config.save_state`` either always raises against a real
#   ``ActorConfig``, or was fed something that was never one.
# - Even with save_state/load_state/``CacheConfig.database`` all correct,
#   that is not sufficient for the gate's persisted state to actually
#   survive a restart. ``Cache._general`` -- which backs this module's
#   ``StateStore`` via ``Cache.add``/``Cache.get`` -- is repopulated from
#   the database on a NEW process only via ``Cache.cache_general()``
#   (cache/cache.pyx:279-304, which sets ``self._general = {}`` when no
#   database is configured), reached only from
#   ``ExecutionEngine.load_cache()`` (execution/engine.pyx:774-793), which
#   the kernel invokes only when
#   ``config.exec_engine.load_cache and not flush_on_start``
#   (system/kernel.py:465-467, where
#   ``flush_on_start = config.cache is not None and config.cache.flush_on_start``).
#   Miss ``exec_engine.load_cache=True`` or ``cache.flush_on_start=False``
#   and a UA-trap global halt -- the exact thing this module exists to
#   make survive a crash-loop -- is silently lost on restart even though
#   every other setting looks correct.
#
# Deployment therefore requires ALL FIVE: save_state, load_state,
# cache.database set, exec_engine.load_cache=True, cache.flush_on_start=False.


@dataclass(frozen=True, slots=True)
class CachePersistenceConfig:
    """The five settings that must ALL be correct for the gate's persisted
    state to both be written (save_state/load_state/database) and actually
    survive a NautilusTrader process restart (load_cache/flush_on_start).
    """

    save_state: bool
    load_state: bool
    database: object | None
    load_cache: bool
    flush_on_start: bool


class CachePersistenceMisconfiguredError(Exception):
    """Raised when any of the five required settings is wrong -- i.e. gate
    persistence would be silently inert, or silently lost on restart.
    """


def assert_cache_persistence_configured(config: CachePersistenceConfig) -> None:
    """Raise loudly unless all five required settings are correct.

    Importable and callable without constructing a live Nautilus node --
    callers build a :class:`CachePersistenceConfig` from real
    ``NautilusKernelConfig``/``CacheConfig``/``ExecEngineConfig`` fields
    (see :func:`cache_persistence_config_from`) or pass one directly in
    tests.
    """
    missing: list[str] = []
    if not config.save_state:
        missing.append("NautilusKernelConfig.save_state=True (e.g. TradingNodeConfig.save_state)")
    if not config.load_state:
        missing.append("NautilusKernelConfig.load_state=True")
    if config.database is None:
        missing.append("CacheConfig.database (must not be None)")
    if not config.load_cache:
        missing.append("ExecEngineConfig.load_cache=True")
    if config.flush_on_start:
        missing.append("CacheConfig.flush_on_start=False")
    if missing:
        raise CachePersistenceMisconfiguredError(
            "Gate persistence requires ALL FIVE of the following, or the "
            "persisted state will not actually survive a restart (even "
            "though on_save/on_load may appear to fire correctly): "
            + "; ".join(missing)
        )


def cache_persistence_config_from(
    kernel_config: object, cache_config: object, exec_engine_config: object
) -> CachePersistenceConfig:
    """Build a :class:`CachePersistenceConfig` from three config-shaped
    objects.

    - ``kernel_config``: duck-typed against ``save_state``/``load_state``.
      Pass the ``NautilusKernelConfig`` (e.g. ``TradingNodeConfig`` or a
      backtest engine config) -- NOT an ``ActorConfig``/``StrategyConfig``,
      which carry neither field on the installed 1.231.0 tree.
    - ``cache_config``: duck-typed against ``database``/``flush_on_start``.
      Pass the ``CacheConfig``.
    - ``exec_engine_config``: duck-typed against ``load_cache``. Pass the
      ``ExecEngineConfig`` (or ``LiveExecEngineConfig``, which extends it).

    Works with real Nautilus instances or fakes in tests without this
    module importing ``nautilus_trader``.
    """
    if not hasattr(kernel_config, "save_state") or not hasattr(kernel_config, "load_state"):
        raise CachePersistenceMisconfiguredError(
            "kernel_config is missing save_state and/or load_state attributes -- "
            "pass the NautilusKernelConfig (e.g. TradingNodeConfig), not an "
            "ActorConfig/StrategyConfig, which carry neither field"
        )
    if not hasattr(cache_config, "database"):
        raise CachePersistenceMisconfiguredError("cache_config is missing a 'database' attribute")
    if not hasattr(cache_config, "flush_on_start"):
        raise CachePersistenceMisconfiguredError(
            "cache_config is missing a 'flush_on_start' attribute"
        )
    if not hasattr(exec_engine_config, "load_cache"):
        raise CachePersistenceMisconfiguredError(
            "exec_engine_config is missing a 'load_cache' attribute"
        )
    save_state = bool(kernel_config.save_state)
    load_state = bool(kernel_config.load_state)
    database = cache_config.database
    flush_on_start = bool(cache_config.flush_on_start)
    load_cache = bool(exec_engine_config.load_cache)
    return CachePersistenceConfig(
        save_state=save_state,
        load_state=load_state,
        database=database,
        load_cache=load_cache,
        flush_on_start=flush_on_start,
    )
