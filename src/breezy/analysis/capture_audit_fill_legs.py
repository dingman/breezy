"""AUT-1 WP5 stage 2b, W1: the per-fill legs and the census legs O, F and R6 (STUB).

Owner: stage-2b worktree W1 (fill legs). Pure functions over one ``AuditInputs`` value
(``capture_audit_input_types``); no I/O. ``audit_fills`` covers legs L, D, B, I, E, P and S of
plan r12 section 3.11.2 for every fill with ``ts_event >= epoch_start_ns``; ``leg_o``, ``leg_f``
and ``leg_r6`` are the order census (with the ``TrySubmit`` classification), the fill census and
the refusal-frame-reference resolution; ``tape_marks`` is r8's hourly Depth10 corroboration for leg
P. Signatures are pinned by ``tests/unit/test_capture_audit_stubs.py`` and must not change.
"""

from breezy.analysis.capture_audit_input_types import AuditInputs
from breezy.analysis.capture_audit_model import FillAudit, LegResult, TapeMark

__all__ = ["audit_fills", "leg_f", "leg_o", "leg_r6", "tape_marks"]


def audit_fills(inp: AuditInputs) -> tuple[FillAudit, ...]:
    """Legs L, D, B, I, E, P and S for every audited fill, in fill order."""
    raise NotImplementedError("AUT-1 stage 2b W1")


def leg_o(inp: AuditInputs) -> LegResult:
    """r8's order census, reading ``OrderInitialized``; classifies each ``TrySubmit(submitted)``."""
    raise NotImplementedError("AUT-1 stage 2b W1")


def leg_f(inp: AuditInputs) -> LegResult:
    """r8's fill census."""
    raise NotImplementedError("AUT-1 stage 2b W1")


def leg_r6(inp: AuditInputs) -> LegResult:
    """Reference resolution: the resolved fraction of on-change refusal frame references."""
    raise NotImplementedError("AUT-1 stage 2b W1")


def tape_marks(inp: AuditInputs) -> tuple[TapeMark, ...]:
    """The catalog Depth10 best ask at each whole UTC hour for every net-position instrument."""
    raise NotImplementedError("AUT-1 stage 2b W1")
