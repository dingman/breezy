"""AUT-1 WP5 stage 2b, W3: audit orchestration (STUB).

Owner: stage-2b worktree W3. ``audit_day`` is a PURE status table over the legs (S2-R9 precedence:
data-integrity causes beat PRE_CAPTURE, which beats run-time host-state causes); ``days_to_audit``
orders yesterday first, then INCONCLUSIVE re-audits, then the backfill oldest-first (S2-R6);
``write_audit_file`` writes ``evidence/capture/audit/<family>/<D>.json`` write-once through
``single_read.write_once`` (0444, schema ``capture_audit/v2``); ``run_audit`` returns the process
exit code (1 on any failed delivery, never for a merely deferred day). Signatures are pinned by
``tests/unit/test_capture_audit_stubs.py`` and must not change.
"""

import datetime as dt
from collections.abc import Mapping
from pathlib import Path

from breezy.analysis.capture_audit_input_types import AuditInputs
from breezy.analysis.capture_audit_model import AuditResult, DayStatus
from breezy.analysis.capture_settlement import AlertOffer

__all__ = ["audit_day", "days_to_audit", "run_audit", "write_audit_file"]


def audit_day(inp: AuditInputs) -> AuditResult:
    """Run every leg over ``inp`` and fold the outcomes into the day status."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def days_to_audit(today: dt.date, audited: Mapping[dt.date, DayStatus]) -> tuple[dt.date, ...]:
    """The days one run audits, in order."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def write_audit_file(data_root: Path, result: AuditResult, *, ts_ns: int) -> None:
    """Publish one day's audit file (write-once; ``<ts_ns>`` in the name when re-audited)."""
    raise NotImplementedError("AUT-1 stage 2b W3")


def run_audit(
    data_root: Path, family_id: str, today: dt.date, *, now_ns: int, offer: AlertOffer
) -> int:
    """The whole run; returns the exit code."""
    raise NotImplementedError("AUT-1 stage 2b W3")
