"""AUT-1 WP5 stage 2b, W1: shared helpers of the fill legs (design S2-R3, S2-R15).

The outcome aliases, the finding and result constructors, the UTC-day and standard-time helpers,
and the per-audit index over every boot's C1 view, split out of ``capture_audit_fill_legs`` so each
module stays under 800 lines. Pure; the one lazy read is ``BootEvidence.stream()``, cached per
call. Non-writer, no ``breezy.adapters`` import.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from breezy.analysis.capture_audit_input_types import AuditInputs, BootEvidence, ExecFill
from breezy.analysis.capture_audit_model import (
    AuditInputError,
    Finding,
    Leg,
    LegOutcome,
    LegResult,
    TapeMark,
)
from breezy.domain.climate_day import standard_time_zone
from breezy.domain.exec_intent import utc_day_for_ns
from breezy.domain.instrument_leg import base_symbol_of
from breezy.persistence.autonomy.capture_reader import (
    C1View,
    CaptureStream,
    DecisionView,
    LifecycleEventView,
)

__all__ = [
    "FAIL",
    "FILLED",
    "HOUR_NS",
    "INFO",
    "NS",
    "PASS",
    "PENDING",
    "SKIPPED",
    "AuditContext",
    "FillIndex",
    "Streams",
    "build_index",
    "climate_day_end_ns",
    "fail",
    "fill_event",
    "in_day",
    "info",
    "leg_result",
    "make_finding",
    "offset_of",
    "skipped",
    "utc_day",
    "yes_instrument",
]

NS: Final[int] = 1_000_000_000
HOUR_NS: Final[int] = 3600 * NS
FILLED: Final[str] = "FILLED"
_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)

FAIL, PASS, PENDING, INFO, SKIPPED = (
    LegOutcome.FAIL,
    LegOutcome.PASS,
    LegOutcome.PENDING,
    LegOutcome.INFO,
    LegOutcome.SKIPPED,
)


# -- shared helpers --------------------------------------------------------------------------


def make_finding(
    leg: Leg, outcome: LegOutcome, cause: str, subject: str, detail: str = ""
) -> Finding:
    return Finding(leg, outcome, cause, subject, detail)


def fail(leg: Leg, cause: str, subject: str, detail: str = "") -> Finding:
    return make_finding(leg, FAIL, cause, subject, detail)


def info(leg: Leg, cause: str, subject: str, detail: str = "") -> Finding:
    return make_finding(leg, INFO, cause, subject, detail)


def leg_result(leg: Leg, findings: Sequence[Finding], **metrics: float) -> LegResult:
    """FAIL if any finding fails, else PENDING if any is pending, else PASS (INFO never counts)."""
    outcomes = {f.outcome for f in findings}
    outcome = FAIL if FAIL in outcomes else PENDING if PENDING in outcomes else PASS
    return LegResult(leg, outcome, tuple(findings), dict(metrics))


def skipped(leg: Leg, cause: str, subject: str) -> LegResult:
    return LegResult(leg, SKIPPED, (info(leg, cause, subject),))


def utc_day(ts_ns: int, what: str) -> dt.date:
    """The UTC day of a stored timestamp; an unusable stamp is an undecodable exec record."""
    try:
        return utc_day_for_ns(ts_ns)
    except ValueError as exc:
        raise AuditInputError("exec_record_undecodable", f"{what} timestamp unusable") from exc


def in_day(ts_ns: int, day: dt.date) -> bool:
    try:
        return utc_day_for_ns(ts_ns) == day
    except ValueError:
        return False


def offset_of(inp: AuditInputs, station: str) -> float | None:
    """The fixed standard-time offset of a station keyed by city code or ICAO id."""
    for key in (station, f"K{station}", station.removeprefix("K")):
        if key in inp.std_offsets:
            return float(inp.std_offsets[key])
    return None


def climate_day_end_ns(climate_day: dt.date, std_utc_offset_hours: float) -> int:
    """Epoch ns of local STANDARD midnight at the start of the next date (never DST-aware).

    Pinned equal to ``breezy.ingest.records.climate_day_end_ns`` (private there) by a test."""
    end = dt.datetime.combine(
        climate_day + dt.timedelta(days=1),
        dt.time(0, 0),
        tzinfo=standard_time_zone(std_utc_offset_hours),
    )
    delta = end - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * NS + delta.microseconds * 1000


def yes_instrument(instrument_id: str) -> str:
    """The YES-leg instrument of an instrument id's base slug (a NO leg maps to its YES book)."""
    symbol, dot, venue = instrument_id.partition(".")
    return f"{base_symbol_of(symbol)}{dot}{venue}"


# -- the per-audit index ---------------------------------------------------------------------


@dataclass(slots=True)
class Streams:
    """Reads each boot's whole stream at most once per call, on demand."""

    _cache: dict[str, CaptureStream] = field(default_factory=dict)

    def get(self, boot: BootEvidence) -> CaptureStream:
        stream = self._cache.get(boot.instance_id)
        if stream is None:
            stream = boot.stream()
            self._cache[boot.instance_id] = stream
        return stream


@dataclass(frozen=True, slots=True)
class FillIndex:
    """Lookups over every boot's C1 view: the merged view for the join, plus the boot of each
    link and each decision (its stream holds that decision's frame copy and forecast points)."""

    view: C1View
    link_boot: Mapping[str, BootEvidence]
    decisions: Mapping[str, tuple[tuple[BootEvidence, DecisionView], ...]]
    filled_trades: frozenset[str]
    mark_ts: Mapping[str, tuple[int, ...]]


def build_index(inp: AuditInputs) -> FillIndex:
    link_boot: dict[str, BootEvidence] = {}
    decisions: dict[str, list[tuple[BootEvidence, DecisionView]]] = defaultdict(list)
    filled: set[str] = set()
    marks: dict[str, list[int]] = defaultdict(list)
    for boot in inp.boots:
        for link in boot.c1.order_links:
            link_boot.setdefault(link.client_order_id, boot)
        for decision in boot.c1.decisions:
            decisions[decision.decision_id].append((boot, decision))
        filled.update(
            e.trade_id for e in boot.c1.lifecycle_events if e.event == FILLED and e.trade_id
        )
        for mark in boot.c1.position_marks:
            marks[mark.instrument_id].append(mark.ts_ns)
    view = C1View(
        family_id=inp.family_id,
        decisions=tuple(d for b in inp.boots for d in b.c1.decisions),
        order_links=tuple(link for b in inp.boots for link in b.c1.order_links),
        lifecycle_events=(),
        position_marks=(),
        detector_events=(),
    )
    return FillIndex(
        view,
        link_boot,
        {k: tuple(v) for k, v in decisions.items()},
        frozenset(filled),
        {k: tuple(v) for k, v in marks.items()},
    )


@dataclass(slots=True)
class AuditContext:
    """One ``audit_fills`` call: the inputs, their index, the lazy streams and the tape marks
    (computed on first use by the injected ``marks_of``, so this module never imports the legs)."""

    inp: AuditInputs
    index: FillIndex
    marks_of: Callable[[AuditInputs], tuple[TapeMark, ...]]
    streams: Streams = field(default_factory=Streams)
    _marks: tuple[TapeMark, ...] | None = None

    def tape_marks(self) -> tuple[TapeMark, ...]:
        if self._marks is None:
            self._marks = self.marks_of(self.inp)
        return self._marks


def fill_event(fill: ExecFill) -> LifecycleEventView:
    return LifecycleEventView(
        event=FILLED,
        client_order_id=fill.client_order_id,
        trade_id=fill.trade_id or "",
        qty=fill.cumulative_qty,
        px="",
        fee="",
        decision_id="",
        venue_order_id_sha256=fill.venue_order_id_sha256,
        reason="",
        ts_ns=fill.ts_event,
        source="",
    )
