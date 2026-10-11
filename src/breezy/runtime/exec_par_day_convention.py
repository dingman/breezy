"""EXEC-PAR BG-5c WP-C (R1.6): the boot-time guard for the ``exec_par/day_convention`` row.

K>1 counters are keyed by per-station standard-time ``entry_day`` (convention ``v: 2``). The first
K>1 boot writes ``{"v": 2}`` through the latch. A boot that reads any other version (or cannot
read the row, or cannot write it) must not run K>1 on counters it cannot interpret: it FORCES
K=1 and raises a CRITICAL alert, the BG-3 force-then-alert pattern (a raising read or write
forces and alerts first, then re-raises).

At a configured K=1 nothing is read or written. This module is NOT imported on the K=1 boot
path; BG-5c WP-E wires :func:`enforce_day_convention_at_boot` next to the BG-3 call, K>1 only.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Final, Protocol

from breezy.runtime.exec_par_records import DAY_CONVENTION_VERSION
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert

__all__ = [
    "DAY_CONVENTION_REASON",
    "DayConventionDetail",
    "enforce_day_convention_at_boot",
]

_LOG = logging.getLogger(__name__)

_ALERT_SITE: Final[str] = "exec_par/boot"
DAY_CONVENTION_REASON: Final[str] = "day_convention is not v2 (counters not interpretable)"
_READ_FAILED_REASON: Final[str] = "day_convention read failed"
_WRITE_FAILED_REASON: Final[str] = "day_convention write failed"


class DayConventionDetail(str, Enum):
    """Closed ``detail`` set for this module's alerts (own enum, like ``ForceK1BootDetail``);
    never a stored version or any raw text."""

    MISMATCH = "EXEC_PAR_DAY_CONVENTION_MISMATCH"
    UNREADABLE = "EXEC_PAR_DAY_CONVENTION_UNREADABLE"
    WRITE_FAILED = "EXEC_PAR_DAY_CONVENTION_WRITE_FAILED"


class _Latch(Protocol):
    """The slice of ``SubmitIntentLatch`` this module uses (structural, as in the BG-3 module)."""

    def max_slots(self) -> int: ...
    def read_day_convention(self) -> int | None: ...
    def write_day_convention(self) -> bool: ...
    def force_k1(self, reason: str) -> None: ...


def _force_and_alert(
    latch: _Latch, alert_sink: AlertSink, reason: str, detail: DayConventionDetail
) -> None:
    _LOG.error("EXEC-PAR boot: %s; forcing K=1", reason)
    latch.force_k1(reason)
    emit_alert(
        alert_sink,
        AlertPayload(
            severity="CRITICAL", event=detail.value, site=_ALERT_SITE, detail=detail.value
        ),
    )


def enforce_day_convention_at_boot(latch: _Latch, *, alert_sink: AlertSink) -> bool:
    """Write the v2 row on the first K>1 boot; refuse K>1 on any other state.

    Returns ``True`` iff K was forced for a version mismatch. A read or write that raises forces
    K=1 and alerts first, then re-raises. Configured K=1 does nothing.
    """
    if latch.max_slots() <= 1:
        return False
    try:
        version = latch.read_day_convention()
    except Exception:
        _force_and_alert(latch, alert_sink, _READ_FAILED_REASON, DayConventionDetail.UNREADABLE)
        raise
    if version is None:
        try:
            latch.write_day_convention()
        except Exception:
            _force_and_alert(
                latch, alert_sink, _WRITE_FAILED_REASON, DayConventionDetail.WRITE_FAILED
            )
            raise
        return False
    if version == DAY_CONVENTION_VERSION:
        return False
    _force_and_alert(latch, alert_sink, DAY_CONVENTION_REASON, DayConventionDetail.MISMATCH)
    return True
