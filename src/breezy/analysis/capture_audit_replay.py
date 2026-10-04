"""AUT-1 WP5 stage 2b, W2: the online R2 replay and legs R1, R2 and R3 (STUB).

Owner: stage-2b worktree W2 (reconciliation). ``BootReplay`` is a ``LogSink`` (fed by the one
``scan_node_log`` pass): it switches its per-boot ``OnChangeFilter`` and ``EvalSeqCounter`` on each
``InstanceIdLine`` and partitions its outputs by the UTC day of each line, keyed
``(instance_id, day)``; reducer state carries across midnight (S2-R6). It replays WITHOUT dedupe
(S2-R4); TrySubmit lines enter the filter but never advance the counter, and guard EntryVetos are
excluded on both sides (S2-R5, ``is_guard_entry_veto``). Signatures are pinned by
``tests/unit/test_capture_audit_stubs.py`` and must not change.
"""

import datetime as dt
from collections.abc import Mapping

from breezy.analysis.capture_audit_input_types import AuditInputs, LogSink, ReplayResult
from breezy.analysis.capture_audit_model import LegResult
from breezy.analysis.capture_node_log import NodeLogEvent

__all__ = ["BootReplay", "leg_r1", "leg_r2", "leg_r3"]


class BootReplay(LogSink):
    """The online R2 reducer (a ``LogSink`` with bounded state)."""

    def __init__(self) -> None:
        raise NotImplementedError("AUT-1 stage 2b W2")

    def feed(self, event: NodeLogEvent) -> None:
        raise NotImplementedError("AUT-1 stage 2b W2")

    def results(self) -> Mapping[tuple[str, dt.date], ReplayResult]:
        """The replay result of each ``(instance_id, UTC day)`` seen."""
        raise NotImplementedError("AUT-1 stage 2b W2")


def leg_r1(inp: AuditInputs) -> LegResult:
    """A bijection between Take/TrySubmit lines and records; guard vetoes matched to refusals."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def leg_r2(inp: AuditInputs) -> LegResult:
    """The replay equals the boot's on-change ``DecisionRecord`` sequence."""
    raise NotImplementedError("AUT-1 stage 2b W2")


def leg_r3(inp: AuditInputs) -> LegResult:
    """Funnel counts against the log (Take and TrySubmit only)."""
    raise NotImplementedError("AUT-1 stage 2b W2")
