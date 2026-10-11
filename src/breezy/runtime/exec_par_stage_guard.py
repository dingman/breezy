"""EXEC-PAR BG-5b: fail closed at K>1 until the in-node stage evaluator is wired.

BG-6 (the boot-pending denial and the stale-stamp halt) does not exist yet, so nothing else
stops a K>1 boot from running with no stage evaluator, no stamp and therefore none of the
D-PREREG daily stops. Until the evaluator is wired, a configured K>1 is forced to K=1 at boot
with a CRITICAL alert, the BG-3 force-then-alert pattern. K=1 is untouched.
"""

from __future__ import annotations

from typing import Final, Protocol

from breezy.runtime.health import AlertPayload, AlertSink, emit_alert

__all__ = ["EVENT_STAGE_EVAL_UNWIRED", "UNWIRED_REASON", "force_k1_unless_stage_eval_wired"]

EVENT_STAGE_EVAL_UNWIRED: Final[str] = "EXEC_PAR_STAGE_EVAL_UNWIRED"
UNWIRED_REASON: Final[str] = "stage evaluator not wired at configured K>1"
_SITE: Final[str] = "exec_par/boot"


class _Latch(Protocol):
    def max_slots(self) -> int: ...
    def force_k1(self, reason: str) -> None: ...


def force_k1_unless_stage_eval_wired(
    latch: _Latch, *, stage_eval_ports: object | None, alert_sink: AlertSink
) -> bool:
    """Force K=1 (and alert) when K>1 is configured with no stage-evaluator ports."""
    if latch.max_slots() <= 1 or stage_eval_ports is not None:
        return False
    latch.force_k1(UNWIRED_REASON)
    emit_alert(
        alert_sink,
        AlertPayload(
            severity="CRITICAL",
            event=EVENT_STAGE_EVAL_UNWIRED,
            site=_SITE,
            detail=EVENT_STAGE_EVAL_UNWIRED,
        ),
    )
    return True
