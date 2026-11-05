"""Entry-veto vocabulary (ARCH-0 AC 23; ARCH C5 "Entry-veto contract", :642-662).

``VetoReason`` is the closed set of 15 reasons an entry can be refused for.
There is deliberately no ``EntryVeto`` alias: that name belongs to the C1 record.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum


class VetoReason(StrEnum):
    # registry
    REGISTRY_NOT_CHAMPION = "registry_not_champion"
    REGISTRY_HALTED = "registry_halted"
    REGISTRY_UNREADABLE = "registry_unreadable"
    REGISTRY_REGRESSED = "registry_regressed"
    REGISTRY_RESTRICTIVE_PENDING = "registry_restrictive_pending"
    # dead engine
    REGISTRY_ATTEST_EXPIRED = "registry_attest_expired"
    REGISTRY_ENGINE_HEARTBEAT_STALE = "registry_engine_heartbeat_stale"
    REGISTRY_CHAIN_STALE = "registry_chain_stale"
    # transient, node-local
    FEED_STALE = "feed_stale"
    RECORDER_STALE = "recorder_stale"
    PERMIT_LAPSED = "permit_lapsed"
    CAPTURE_GAP = "capture_gap"
    CAPTURE_UNTAGGED = "capture_untagged"
    ALERTS_UNDELIVERABLE = "alerts_undeliverable"
    # position
    RUNG_NET_POSITION_HELD = "rung_net_position_held"


def compose_entry_vetoes(checks: Iterable[Callable[[], VetoReason | None]]) -> VetoReason | None:
    """The first veto any check returns, else ``None``.

    Fail closed: a check that raises, or returns anything but a ``VetoReason`` or
    ``None``, yields ``registry_unreadable``. Checks after the deciding one never run.
    """
    for check in checks:
        try:
            verdict = check()
        except Exception:  # noqa: BLE001 - fail closed: any check failure is a veto
            return VetoReason.REGISTRY_UNREADABLE
        if verdict is None:
            continue
        if not isinstance(verdict, VetoReason):
            return VetoReason.REGISTRY_UNREADABLE
        return verdict
    return None
