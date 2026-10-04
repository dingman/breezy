"""AUT-1 WP5 stage 2b, W2: the stream, watchdog, tape and NBP legs (STUB).

Owner: stage-2b worktree W2. Pure functions over one ``AuditInputs`` value. ``leg_w`` only COMPUTES
the watchdog evidence gaps (the daily re-send is stage 3, S2-R14); ``positive_control`` is the D13
node-log and funnel check (``node_log_blind`` / ``funnel_missing`` are raised as
``AuditInputError`` by the gatherer, so it reports the leg result). Signatures are pinned by
``tests/unit/test_capture_audit_stubs.py`` and must not change.
"""

from breezy.analysis.capture_audit_input_types import AuditInputs
from breezy.analysis.capture_audit_model import LegResult, WatchdogGap

__all__ = [
    "leg_n",
    "leg_r4",
    "leg_r5",
    "leg_r7",
    "leg_t",
    "leg_w",
    "positive_control",
]


def leg_r4(inp: AuditInputs) -> LegResult:
    """Writer-failure markers in the node log."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def leg_r5(inp: AuditInputs) -> LegResult:
    """Counted stream loss per boot and table."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def leg_r7(inp: AuditInputs) -> LegResult:
    """Stream continuity: no heartbeat gap above ``STREAM_GAP_FAIL_S``."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def leg_w(inp: AuditInputs) -> tuple[LegResult, tuple[WatchdogGap, ...]]:
    """Watchdog evidence: every recorder watchdog kill has a stall record and a delivered page."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def leg_t(inp: AuditInputs) -> LegResult:
    """r8's tape-ingest leg."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def leg_n(inp: AuditInputs) -> LegResult:
    """r8's NBP census plus a delivery record for each ``NBP_CYCLE_MISSED`` offer."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def positive_control(inp: AuditInputs) -> LegResult:
    """D13: boots overlapping the day by ``PC_MIN_OVERLAP_S`` hold decisions and funnel rows."""
    raise NotImplementedError("AUT-1 stage 2b W2")
