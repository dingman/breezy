"""EXEC-PAR WP5b: the supervisor-side breaker watch (pure decision, no I/O).

The adapter cannot alert and the node's in-memory counters are invisible to the
supervisor, so this watch covers exactly what the node PERSISTS: the breaker
record (heartbeat, resolver-pass time, latched halt) and the slot table's
unreadable slots. ``trade_supervisor.probe_breaker_record`` does the read-only
WAL read; :func:`decide_breaker_alerts` turns a probe into alert specs.

Episode semantics: an alert fires when its condition becomes true and not again
until it has been false for one tick, so a stale heartbeat pages once per
episode, not once per supervisor poll.

At a configured K of 1 nothing here can fire except the unreadable-slot and
latched-halt alerts, which need a v2 table or a breaker record that only a K>1
run writes. A K=1 node therefore behaves exactly as today.
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
    "REALERT_INTERVAL_NS",
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


@dataclass(frozen=True, slots=True)
class BreakerProbe:
    """What one read-only WAL read of the store showed."""

    readable: bool
    present: bool
    halted: bool
    hb_ns: int
    resolver_pass_ns: int
    unreadable_slots: int

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
) -> list[BreakerAlertSpec]:
    """The alerts due this tick: conditions true now that are not yet CONFIRMED
    delivered, or were last delivered at least ``REALERT_INTERVAL_NS`` ago.

    ``state.active`` is pruned to the conditions still true (an ended episode can
    alert again) but never gains a key here: the caller marks each alert with
    ``state.delivered(spec, now_ns)`` only after the durable send succeeded. A
    node with no pid (a test double) anchors its boot grace on the first live
    sighting.

    The supervisor returns before probing at a configured K<=1 (a K=1 node writes
    no breaker record), so the halted and unreadable-slot alerts are unreachable
    there BY DESIGN; ``k_configured`` is still honoured here for direct callers.
    """
    conditions: dict[str, BreakerAlertSpec] = {}
    if probe.unreadable_slots > 0:
        conditions["unreadable_slot"] = _keyed(_UNREADABLE, "unreadable_slot")
    if probe.halted:
        conditions["halted"] = _keyed(_HALTED, "halted")
    first_seen = _note_node(state, node_pid if node_pid is not None else 0, node_live, now_ns)
    if k_configured > 1 and node_live:
        conditions.update(_watcher_conditions(probe, now_ns, first_seen))
    state.active = {k: t for k, t in state.active.items() if k in conditions}
    return [
        spec
        for key, spec in conditions.items()
        if key not in state.active or now_ns - state.active[key] >= REALERT_INTERVAL_NS
    ]
