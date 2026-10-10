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

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from breezy.runtime.submit_intent_slots import (
    BREAKER_FUTURE_SKEW_NS,
    BREAKER_HEARTBEAT_MAX_AGE_NS,
    BREAKER_RESOLVER_PASS_MAX_AGE_NS,
)

__all__ = [
    "ABSENT_RECORD_GRACE_NS",
    "BreakerAlertDetail",
    "BreakerAlertSpec",
    "BreakerProbe",
    "BreakerWatchState",
    "decide_breaker_alerts",
]

#: How long a live K>1 node may run without any breaker record before the
#: supervisor calls the watcher dead (the latch's own grace is 60 s).
ABSENT_RECORD_GRACE_NS: Final[int] = 120 * 1_000_000_000

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


@dataclass
class BreakerWatchState:
    """Mutable per-supervisor memory: which conditions are currently alerting."""

    active: set[str] = field(default_factory=set)
    first_live_ns: int | None = None


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


def _stale(stamp_ns: int, now_ns: int, bound_ns: int) -> bool:
    """Older than the bound, or further ahead than the skew allowance (clock fault)."""
    age = now_ns - stamp_ns
    return not -BREAKER_FUTURE_SKEW_NS <= age <= bound_ns


def _watcher_conditions(
    probe: BreakerProbe, now_ns: int, state: BreakerWatchState
) -> dict[str, BreakerAlertSpec]:
    if not probe.readable:
        return {"record_unreadable": _DEAD}
    if not probe.present:
        if state.first_live_ns is None:
            state.first_live_ns = now_ns
        if now_ns - state.first_live_ns > ABSENT_RECORD_GRACE_NS:
            return {"record_absent": _DEAD}
        return {}
    found: dict[str, BreakerAlertSpec] = {}
    if _stale(probe.hb_ns, now_ns, BREAKER_HEARTBEAT_MAX_AGE_NS):
        found["heartbeat_stale"] = _DEAD
    if _stale(probe.resolver_pass_ns, now_ns, BREAKER_RESOLVER_PASS_MAX_AGE_NS):
        found["resolver_pass_stale"] = _RESOLVER
    return found


def decide_breaker_alerts(
    *,
    probe: BreakerProbe,
    k_configured: int,
    node_live: bool,
    now_ns: int,
    state: BreakerWatchState,
) -> list[BreakerAlertSpec]:
    """The alerts newly due this tick (episode-deduplicated through ``state``)."""
    conditions: dict[str, BreakerAlertSpec] = {}
    if probe.unreadable_slots > 0:
        conditions["unreadable_slot"] = _UNREADABLE
    if probe.halted:
        conditions["halted"] = _HALTED
    if k_configured > 1 and node_live:
        conditions.update(_watcher_conditions(probe, now_ns, state))
    else:
        state.first_live_ns = None
    fresh = [spec for key, spec in conditions.items() if key not in state.active]
    state.active = set(conditions)
    return fresh
