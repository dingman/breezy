"""EXEC-PAR WP5b: the supervisor-side breaker watch (pure decision, no I/O).

The adapter cannot alert and the node's in-memory counters are invisible to the
supervisor, so this watch covers exactly what the node PERSISTS: the breaker
record (heartbeat, resolver-pass time, latched halt) and the slot table's
unreadable slots. ``trade_supervisor.probe_breaker_record`` does the read-only
WAL read; :func:`decide_breaker_alerts` turns a probe into alert specs.

Episode semantics: an alert fires when its condition becomes true and not again
until it has been false for one tick, so a stale heartbeat pages once per
episode, not once per supervisor poll.

BG-8: the halted, unreadable-slot and probe-unreadable conditions are probed at
ANY K, read-only, at most every ``PROBE_INTERVAL_NS``. At a configured K of 1
each fires ONCE per episode (no hourly repeat), so a breaker that is legitimately
already halted pages a K=1 operator exactly once. The dead-watcher, resolver and
stage-stamp conditions are K>1 only; the stamp one fires with the node down.
On every alert the supervisor only alerts: it never respawns or kills the node.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final

from breezy.runtime.submit_intent_slots import (
    BREAKER_FUTURE_SKEW_NS,
    BREAKER_HEARTBEAT_MAX_AGE_NS,
    BREAKER_RESOLVER_PASS_MAX_AGE_NS,
)

__all__ = [
    "ABSENT_RECORD_GRACE_NS",
    "BOOT_GRACE_NS",
    "PROBE_INTERVAL_NS",
    "REALERT_INTERVAL_NS",
    "RETRY_INTERVAL_NS",
    "STAGE_STAMP_MAX_AGE_NS",
    "UNREADABLE_DEBOUNCE_PROBES",
    "BreakerAlertDetail",
    "BreakerAlertSpec",
    "BreakerProbe",
    "BreakerWatchState",
    "decide_breaker_alerts",
]

#: How long a live K>1 node may run without any breaker record before the
#: supervisor calls the watcher dead (the latch's own grace is 60 s).
ABSENT_RECORD_GRACE_NS: Final[int] = 120 * 1_000_000_000

#: A freshly seen node pid gets this long to write its first heartbeat before a
#: stale stamp counts (the record may be the previous node's).
BOOT_GRACE_NS: Final[int] = 600 * 1_000_000_000

#: A delivered page whose condition still holds is repeated this often, so a
#: delivered-then-lost page cannot leave the condition silent.
REALERT_INTERVAL_NS: Final[int] = 3600 * 1_000_000_000

#: BG-8: the supervisor probes the store no more often than this (read-only).
PROBE_INTERVAL_NS: Final[int] = 600 * 1_000_000_000

#: BG-8: a lost send (raised or non-durable) is retried on this throttle, from the
#: cached probe; it never reopens the 10-minute store-probe throttle.
RETRY_INTERVAL_NS: Final[int] = 60 * 1_000_000_000

#: A store read can fail transiently (sqlite busy/locked): only this many
#: CONSECUTIVE unreadable probes (10 min apart) page ``PROBE_UNREADABLE``.
UNREADABLE_DEBOUNCE_PROBES: Final[int] = 2

#: Spec 1a: a stage-eval stamp older than 26 h (or never written that long) is stale.
STAGE_STAMP_MAX_AGE_NS: Final[int] = 26 * 3600 * 1_000_000_000

_CRITICAL: Final[str] = "CRITICAL"


class BreakerAlertDetail(str, Enum):
    """Closed set of ``detail`` reasons this watch ever emits (value-free, like
    ``AlertDetail``).

    A separate enum on purpose, in the ``CheckAlertDetail`` precedent:
    ``trade_supervisor_core`` is inside the autonomy code-identity import
    closure, so adding members there would force a reviewed pin for a change
    that has nothing to do with the autonomy programme.
    """

    BREAKER_WATCHER_DEAD = "breaker_watcher_dead"
    BREAKER_RESOLVER_PASS_STALE = "breaker_resolver_pass_stale"
    BREAKER_ENTRY_HALT_LATCHED = "breaker_entry_halt_latched"
    SLOT_TABLE_UNREADABLE_SLOT = "slot_table_unreadable_slot"
    STAGE_STAMP_STALE = "exec_par_stage_stamp_stale"
    PROBE_UNREADABLE = "breaker_probe_unreadable"
    #: Stamp never written and the clock anchored on this supervisor's first
    #: K>1 sighting (no K>1 epoch row exists yet).
    STAGE_STAMP_STALE_FIRST_SIGHTING = "exec_par_stage_stamp_stale_anchor=first_sighting"
    #: Stamp never written and a corrupt epoch row hides the K>1 anchor.
    STAGE_STAMP_STALE_ANCHOR_UNREADABLE = "exec_par_stage_stamp_stale_anchor=unreadable"


@dataclass(frozen=True, slots=True)
class BreakerProbe:
    """What one read-only WAL read of the store showed."""

    readable: bool
    present: bool
    halted: bool
    hb_ns: int
    resolver_pass_ns: int
    unreadable_slots: int
    #: BG-8: the BG-5 stage-eval stamp time; ``None`` = never written.
    stamp_ts_ns: int | None = None
    #: ``False`` when the stamp row exists but does not decode.
    stamp_readable: bool = True
    #: BG-8: min ``boot_ts`` (ns) of the BG-2 epoch rows with ``effective_k > 1``;
    #: ``None`` = the node has never booted at K>1.
    k_anchor_ns: int | None = None
    #: ``False`` when an epoch row did not decode (the anchor is unknown, the
    #: probe is still readable: a corrupt epoch must never hide a halt reading).
    anchor_readable: bool = True

    @classmethod
    def absent(cls) -> BreakerProbe:
        """No record and nothing unreadable: the inert reading."""
        return cls(
            readable=True,
            present=False,
            halted=False,
            hb_ns=0,
            resolver_pass_ns=0,
            unreadable_slots=0,
        )


@dataclass(frozen=True, slots=True)
class BreakerAlertSpec:
    event: str
    severity: str
    detail: BreakerAlertDetail
    #: The condition this alert reports; ``BreakerWatchState.delivered`` is keyed on it.
    key: str = ""


@dataclass
class BreakerWatchState:
    """Mutable per-supervisor memory.

    ``active`` holds only conditions whose alert was CONFIRMED delivered
    (``delivered``), so an alert the durable path could not take is re-decided
    on the next tick instead of being silently considered sent.
    """

    #: condition key -> when its alert was last CONFIRMED delivered.
    active: dict[str, int] = field(default_factory=dict)
    node_pid: int | None = None
    node_first_seen_ns: int | None = None
    #: BG-8: last store probe (the 10-minute throttle) and the first K>1 sighting
    #: (the anchor for a never-written stamp).
    last_probe_ns: int | None = None
    stamp_watch_since_ns: int | None = None
    #: Consecutive unreadable probes; the last probe and when a lost send may retry.
    unreadable_streak: int = 0
    last_probe: BreakerProbe | None = None
    last_send_fail_ns: int | None = None

    def delivered(self, spec: BreakerAlertSpec, now_ns: int) -> None:
        self.active[spec.key] = now_ns


_DEAD = BreakerAlertSpec(
    "TRADE_SUPERVISOR_BREAKER_WATCHER_DEAD", _CRITICAL, BreakerAlertDetail.BREAKER_WATCHER_DEAD
)
_RESOLVER = BreakerAlertSpec(
    "TRADE_SUPERVISOR_BREAKER_RESOLVER_PASS_STALE",
    _CRITICAL,
    BreakerAlertDetail.BREAKER_RESOLVER_PASS_STALE,
)
_HALTED = BreakerAlertSpec(
    "TRADE_SUPERVISOR_BREAKER_ENTRY_HALT_LATCHED",
    _CRITICAL,
    BreakerAlertDetail.BREAKER_ENTRY_HALT_LATCHED,
)
_UNREADABLE = BreakerAlertSpec(
    "TRADE_SUPERVISOR_SLOT_TABLE_UNREADABLE_SLOT",
    _CRITICAL,
    BreakerAlertDetail.SLOT_TABLE_UNREADABLE_SLOT,
)
_STAMP_STALE = BreakerAlertSpec(
    "TRADE_SUPERVISOR_EXEC_PAR_STAGE_STAMP_STALE",
    _CRITICAL,
    BreakerAlertDetail.STAGE_STAMP_STALE,
)
_PROBE_UNREADABLE = BreakerAlertSpec(
    "TRADE_SUPERVISOR_BREAKER_PROBE_UNREADABLE",
    _CRITICAL,
    BreakerAlertDetail.PROBE_UNREADABLE,
)


def _keyed(spec: BreakerAlertSpec, key: str) -> BreakerAlertSpec:
    return replace(spec, key=key)


def _stale(stamp_ns: int, now_ns: int, bound_ns: int) -> bool:
    """Older than the bound, or further ahead than the skew allowance (clock fault)."""
    age = now_ns - stamp_ns
    return not -BREAKER_FUTURE_SKEW_NS <= age <= bound_ns


def _watcher_conditions(
    probe: BreakerProbe, now_ns: int, first_seen_ns: int
) -> dict[str, BreakerAlertSpec]:
    since_start = now_ns - first_seen_ns
    if not probe.readable:
        return {"record_unreadable": _keyed(_DEAD, "record_unreadable")}
    if not probe.present:
        if since_start > ABSENT_RECORD_GRACE_NS:
            return {"record_absent": _keyed(_DEAD, "record_absent")}
        return {}
    if since_start <= BOOT_GRACE_NS:
        # A fresh node has not heartbeated yet and the record may be the
        # previous node's: stale stamps are not evidence of a dead watcher.
        return {}
    found: dict[str, BreakerAlertSpec] = {}
    if _stale(probe.hb_ns, now_ns, BREAKER_HEARTBEAT_MAX_AGE_NS):
        found["heartbeat_stale"] = _keyed(_DEAD, "heartbeat_stale")
    if _stale(probe.resolver_pass_ns, now_ns, BREAKER_RESOLVER_PASS_MAX_AGE_NS):
        found["resolver_pass_stale"] = _keyed(_RESOLVER, "resolver_pass_stale")
    return found


def _stamp_stale(probe: BreakerProbe, now_ns: int, watch_since_ns: int) -> bool:
    if not probe.stamp_readable:
        return True
    if probe.stamp_ts_ns is None:
        return now_ns - watch_since_ns >= STAGE_STAMP_MAX_AGE_NS
    return _stale(probe.stamp_ts_ns, now_ns, STAGE_STAMP_MAX_AGE_NS)


def _note_node(state: BreakerWatchState, node_pid: int | None, node_live: bool, now_ns: int) -> int:
    """Remember when this supervisor first saw the current node pid (its boot grace anchor)."""
    if not node_live or node_pid is None:
        state.node_pid = None
        state.node_first_seen_ns = None
        return now_ns
    if node_pid != state.node_pid or state.node_first_seen_ns is None:
        state.node_pid = node_pid
        state.node_first_seen_ns = now_ns
    return state.node_first_seen_ns


def decide_breaker_alerts(
    *,
    probe: BreakerProbe,
    k_configured: int,
    node_live: bool,
    now_ns: int,
    state: BreakerWatchState,
    node_pid: int | None = None,
    fresh: bool = True,
) -> list[BreakerAlertSpec]:
    """The alerts due this tick: conditions true now that are not yet CONFIRMED
    delivered, or were last delivered at least ``REALERT_INTERVAL_NS`` ago.

    ``state.active`` is pruned to the conditions still true (an ended episode can
    alert again) but never gains a key here: the caller marks each alert with
    ``state.delivered(spec, now_ns)`` only after the durable send succeeded. A
    node with no pid (a test double) anchors its boot grace on the first live
    sighting.

    BG-8: the halted, unreadable-slot and probe-unreadable conditions are decided
    at ANY K; at K<=1 they alert once per episode (no hourly repeat). The stamp
    condition is K>1 only and does not need a live node.

    ``fresh`` is ``False`` when ``probe`` is the cached reading re-decided for a
    lost-send retry: it must not advance the unreadable-probe streak.
    ``PROBE_UNREADABLE`` needs ``UNREADABLE_DEBOUNCE_PROBES`` consecutive fresh
    unreadable probes (one busy/locked read must not page); any good read resets.
    """
    conditions: dict[str, BreakerAlertSpec] = {}
    if probe.unreadable_slots > 0:
        conditions["unreadable_slot"] = _keyed(_UNREADABLE, "unreadable_slot")
    if probe.halted:
        conditions["halted"] = _keyed(_HALTED, "halted")
    first_seen = _note_node(state, node_pid if node_pid is not None else 0, node_live, now_ns)
    watcher_live = k_configured > 1 and node_live
    if watcher_live:
        conditions.update(_watcher_conditions(probe, now_ns, first_seen))
    if fresh:
        state.unreadable_streak = 0 if probe.readable else state.unreadable_streak + 1
    if (
        not probe.readable
        and not watcher_live
        and state.unreadable_streak >= UNREADABLE_DEBOUNCE_PROBES
    ):
        conditions["probe_unreadable"] = _keyed(_PROBE_UNREADABLE, "probe_unreadable")
    if k_configured > 1:
        if state.stamp_watch_since_ns is None:
            state.stamp_watch_since_ns = now_ns
        durable_anchor = probe.k_anchor_ns is not None
        since = probe.k_anchor_ns if probe.k_anchor_ns is not None else state.stamp_watch_since_ns
        if probe.readable and _stamp_stale(probe, now_ns, since):
            spec = _STAMP_STALE
            if probe.stamp_ts_ns is None and probe.stamp_readable and not durable_anchor:
                spec = replace(
                    spec,
                    detail=(
                        BreakerAlertDetail.STAGE_STAMP_STALE_FIRST_SIGHTING
                        if probe.anchor_readable
                        else BreakerAlertDetail.STAGE_STAMP_STALE_ANCHOR_UNREADABLE
                    ),
                )
            conditions["stamp_stale"] = _keyed(spec, "stamp_stale")
    realert = k_configured > 1
    state.active = {k: t for k, t in state.active.items() if k in conditions}
    return [
        spec
        for key, spec in conditions.items()
        if key not in state.active
        or (realert and now_ns - state.active[key] >= REALERT_INTERVAL_NS)
    ]
