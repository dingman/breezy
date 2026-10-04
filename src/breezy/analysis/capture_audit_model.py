"""AUT-1 WP5 stage 2a: the shared audit result model (plan r12 section 3.11; design S2-R3).

Enums, result types, the closed error causes, the constants and the one shared predicate. Every
type is frozen. A leg is a pure function from ``AuditInputs`` (``capture_audit_input_types``) to
these results; the wire format lives in ``capture_audit_wire``. Non-writer, stdlib only (plus the
guard veto vocabulary), no ``breezy.adapters`` import.

``subject`` of a ``Finding`` is an id or a sha, never a path; venue order ids appear only as sha256.
"""

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from breezy.persistence.autonomy.veto import VetoReason

__all__ = [
    "AUDIT_CACHE_DIR",
    "AUDIT_DIR_REL",
    "AUDIT_SCHEMA",
    "AUDIT_WORK_BUDGET_S",
    "BACKFILL_DAYS",
    "ERROR_CAUSES",
    "FLUSH_WINDOW_S",
    "GUARD_VETO_REASONS",
    "LIVE_PROOF_MAX_AGE_H",
    "LIVE_PROOF_NAME_RE",
    "METRIC_NAMES",
    "PC_MIN_OVERLAP_S",
    "R6_BASELINE",
    "SETTLEMENT_ALERT_H",
    "SETTLEMENT_PENDING_H",
    "STREAM_GAP_FAIL_S",
    "AuditInputError",
    "AuditResult",
    "DayStatus",
    "FillAudit",
    "Finding",
    "Leg",
    "LegOutcome",
    "LegResult",
    "MetricValue",
    "TapeMark",
    "WatchdogGap",
    "is_guard_entry_veto",
]

AUDIT_SCHEMA: Final[str] = "capture_audit/v2"
#: ``evidence/capture/audit/<family>/<D>.json`` below the data root (r12 section 3.11.4).
AUDIT_DIR_REL: Final[str] = "evidence/capture/audit"
#: The audit's own E-8 cache directory below the data root (never the bus-snapshot directory).
AUDIT_CACHE_DIR: Final[str] = "cache/capture_audit"
#: ``live_proof_<family_id>_<asof>.json`` (r12 section 3.11.5; the dead-man reads the newest).
LIVE_PROOF_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"live_proof_(?P<family_id>.+)_(?P<asof>\d{4}-\d{2}-\d{2})\.json"
)

#: R7: the longest tolerated gap between consecutive heartbeats while a boot ran.
STREAM_GAP_FAIL_S: Final[int] = 180
#: R1/R2/R5: the tail of a boot that the stream may legitimately not hold (r12 section 3.4.4).
FLUSH_WINDOW_S: Final[int] = 61
#: R6: the WP0-measured resolved fraction; below it minus one percentage point is CRITICAL.
R6_BASELINE: Final[float] = 0.923
SETTLEMENT_PENDING_H: Final[int] = 36
SETTLEMENT_ALERT_H: Final[int] = 48
BACKFILL_DAYS: Final[int] = 8
LIVE_PROOF_MAX_AGE_H: Final[int] = 26
#: D13: a boot must overlap the day by at least this long to face the positive control.
PC_MIN_OVERLAP_S: Final[int] = 1200
#: 1500 s unit timeout, less the 600 s ``flock -w`` wait (E-7e(f)), less a 60 s margin; measured
#: from process start.
AUDIT_WORK_BUDGET_S: Final[int] = 1500 - 600 - 60

MetricValue = int | float | str


class DayStatus(StrEnum):
    PASS = "PASS"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_INPUT = "NO_INPUT"
    PRE_CAPTURE = "PRE_CAPTURE"
    PARTIAL_EPOCH = "PARTIAL_EPOCH"
    ERROR = "ERROR"
    FAIL = "FAIL"


class Leg(StrEnum):
    L = "L"
    D = "D"
    B = "B"
    I = "I"
    E = "E"
    P = "P"
    S = "S"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"
    R7 = "R7"
    W = "W"
    O = "O"
    F = "F"
    T = "T"
    N = "N"
    PC = "PC"


class LegOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"
    INFO = "INFO"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


#: The closed set of fail-loud causes: an ``AuditInputError`` carries exactly one of these.
ERROR_CAUSES: Final[frozenset[str]] = frozenset(
    {
        "exec_snapshot_failed",
        "exec_key_prefix_unknown",
        "exec_record_undecodable",
        "node_log_unreadable",
        "node_log_unparseable",
        "node_log_missing",
        "node_log_blind",
        "journal_failed",
        "epoch_missing",
        "epoch_rewritten",
        "epoch_unlogged",
        "epoch_unreadable",
        "stream_unreadable",
        "capture_projection_failed",
        "recorder_watchdog_unarmed",
        "bus_snapshot_missing",
        "bus_snapshot_stale",
        "funnel_missing",
        # S2-R1: a node-log sink raised mid-scan. S2-R7: the eager tape index could not be read.
        "node_log_sink_failed",
        "tape_unreadable",
        # S2-R22: a settlement file could not be read; never folded into a projection failure.
        "settlement_unreadable",
        # S2-R46: R1 and R3 refuse a boot whose entry lines were capped (an unbounded scan).
        "entry_lines_capped",
    }
)

#: The registered metric names (r8 section 3.10, r12 section 3.11.4): AUT-5 pre-registers exactly
#: these, so an audit result may carry no other metric.
METRIC_NAMES: Final[frozenset[str]] = frozenset(
    {
        "day_status",
        "fills_total",
        "fills_joined",
        "records_lost_in_flush_window",
        "refusal_frame_ref_resolved_frac",
        "watchdog_kills_unproven",
        *(f"leg_{leg.value}_pass" for leg in Leg),
    }
)


class AuditInputError(Exception):
    """An input could not be read or trusted: the day is ``ERROR`` with this ``cause``.

    ``detail`` is a short non-path, non-secret note."""

    def __init__(self, cause: str, detail: str = "") -> None:
        if cause not in ERROR_CAUSES:
            raise ValueError(f"unknown audit error cause: {cause!r}")
        super().__init__(f"{cause}: {detail}" if detail else cause)
        self.cause = cause
        self.detail = detail


def _no_metrics() -> Mapping[str, MetricValue]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Finding:
    leg: Leg
    outcome: LegOutcome
    cause: str
    #: An id or a sha, never a path.
    subject: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LegResult:
    leg: Leg
    outcome: LegOutcome
    findings: tuple[Finding, ...] = ()
    metrics: Mapping[str, MetricValue] = field(default_factory=_no_metrics)


@dataclass(frozen=True, slots=True)
class FillAudit:
    client_order_id: str
    trade_id: str
    family_id: str
    source: str
    drill: bool
    attributed: bool
    legs: tuple[LegResult, ...]
    causes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WatchdogGap:
    """Leg W: a recorder watchdog kill with no stall record or no delivered per-kill page."""

    unit: str
    invocation_id: str
    ts_ns: int
    cause: str


@dataclass(frozen=True, slots=True)
class TapeMark:
    """r8 section 3.10 ``tape_marks``: the catalog Depth10 best ask at a whole UTC hour of D for an
    instrument with a non-zero net position. Corroboration for leg P, never a C1 record."""

    instrument_id: str
    hour: int
    best_ask: float | None
    net_qty: int


@dataclass(frozen=True, slots=True)
class AuditResult:
    day: dt.date
    family_id: str
    status: DayStatus
    #: The ERROR/FAIL/INCONCLUSIVE cause, or an empty string.
    cause: str
    legs: tuple[LegResult, ...]
    fills: tuple[FillAudit, ...]
    metrics: Mapping[str, MetricValue] = field(default_factory=_no_metrics)
    watchdog_evidence_gaps: tuple[WatchdogGap, ...] = ()
    #: Byte-identical repeated decision lines (INFO only; C1, S2-R4).
    duplicate_decision_lines: int = 0
    tape_marks: tuple[TapeMark, ...] = ()

    def __post_init__(self) -> None:
        unknown = sorted(set(self.metrics) - METRIC_NAMES)
        if unknown:
            raise ValueError(f"unregistered metric names: {unknown}")


#: The reasons ``CaptureGuardedStrategy._refuse_one`` writes DIRECTLY (its ``REASON_CAPTURE_*``
#: constants, aliases of these ``VetoReason`` members). FQ's own ``VetoReason`` EntryVetos go
#: through ``FqCaptureAdapter.follow_up`` and the node's ``OnChangeFilter``, so they are not here.
#: ``tests/unit/test_capture_audit_model.py`` derives this set from ``guarded_strategy`` and pins
#: equality (the module is not imported here: it pulls Nautilus).
GUARD_VETO_REASONS: Final[frozenset[str]] = frozenset(
    {VetoReason.CAPTURE_GAP.value, VetoReason.CAPTURE_UNTAGGED.value}
)
_ENTRY_VETO: Final[str] = "EntryVeto"


def is_guard_entry_veto(kind: str, reason: str) -> bool:
    """Whether a decision record or log line is a CAPTURE-GUARD ``EntryVeto`` (B7, S2-R5).

    Guard vetoes are the capture guard's own refusals (``capture_gap``, ``capture_untagged``),
    written directly by ``CaptureGuardedStrategy._refuse_one``, matched to ``CAPTURE_REFUSED``
    lines in R1, and EXCLUDED from the R2 on-change replay on both sides. FQ's own ``VetoReason``
    EntryVetos DO enter the node's ``OnChangeFilter`` (``FqCaptureAdapter.follow_up``), so they are
    not guard vetoes and stay in the replay. One
    predicate, so R1, R2 and the fill legs never disagree about what a guard veto is."""
    return kind == _ENTRY_VETO and reason in GUARD_VETO_REASONS
