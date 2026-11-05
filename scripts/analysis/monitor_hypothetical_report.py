"""The INC-8 hypothetical-hold corpus report: aggregation and JSON shape.

Split out of ``current_rung_hold_monitor_hypothetical_hold.py`` (behaviour-
preserving; see that module's docstring for the full INC-8 spec context).
This module carries the descriptive, calibration-gated aggregation over a
sequence of replayed trials -- :func:`build_corpus_report` -- and the
``CorpusReport``/``SkippedStationDay`` schema it produces. No I/O, no catalog
access, no strategy or monitor evaluation: those inputs already exist by the
time this module sees them (``monitor_hypothetical_core.replay_monitor``'s
return values).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from monitor_hypothetical_core import HypotheticalTake, ReplayDiagnostics

from breezy.strategy.current_rung_hold.monitor_records import PositionMonitorSummary

#: A4: below this many usable station-days, firing rates are UNCALIBRATED.
#: Mirrors the kill-sentence floor (``mb_current_rung_edge_study.py``'s
#: docstring: ">= 15 afternoon-covered station-days").
CALIBRATION_FLOOR_STATION_DAYS: Final[int] = 15

_ZERO: Final[Decimal] = Decimal(0)
_P10: Final[Decimal] = Decimal("0.10")
_P50: Final[Decimal] = Decimal("0.50")
_P90: Final[Decimal] = Decimal("0.90")


@dataclass(frozen=True, slots=True, kw_only=True)
class SkippedStationDay:
    """One station-day this corpus could not use, and why (tape-coverage
    caveat, plan completion criterion)."""

    station: str
    climate_day: dt.date
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusReport:
    """The INC-8 headline artefact (plan completion criterion, A4/P5/P6)."""

    generated_at_ns: int
    window_start: str
    window_end: str
    stations: tuple[str, ...]
    usable_station_days: int
    calibration_status: Literal["CALIBRATED", "UNCALIBRATED"]
    n_trials: int
    dead_precision: Decimal | None
    dead_precision_numerator: int
    dead_precision_denominator: int
    threatened_base_rate: Decimal | None
    threatened_evaluations: int
    archive_covered_evaluations: int
    missing_stop_rate: Decimal | None
    missing_stop_numerator: int
    missing_stop_denominator: int
    recoverable_value_p10: Decimal | None
    recoverable_value_p50: Decimal | None
    recoverable_value_p90: Decimal | None
    recoverable_value_n: int
    provisional_constant_firing_rates: Mapping[str, Decimal]
    inter_confirmation_span_ns_p10: int | None
    inter_confirmation_span_ns_p50: int | None
    inter_confirmation_span_ns_p90: int | None
    inter_confirmation_span_n: int
    per_station_trial_counts: Mapping[str, int]
    per_leg_trial_counts: Mapping[str, int]
    skipped_station_days: tuple[SkippedStationDay, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at_ns": self.generated_at_ns,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "stations": list(self.stations),
            "usable_station_days": self.usable_station_days,
            "calibration_status": self.calibration_status,
            "n_trials": self.n_trials,
            "dead_precision": _decimal_or_none(self.dead_precision),
            "dead_precision_numerator": self.dead_precision_numerator,
            "dead_precision_denominator": self.dead_precision_denominator,
            "threatened_base_rate": _decimal_or_none(self.threatened_base_rate),
            "threatened_evaluations": self.threatened_evaluations,
            "archive_covered_evaluations": self.archive_covered_evaluations,
            "missing_stop_rate": _decimal_or_none(self.missing_stop_rate),
            "missing_stop_numerator": self.missing_stop_numerator,
            "missing_stop_denominator": self.missing_stop_denominator,
            "recoverable_value_p10": _decimal_or_none(self.recoverable_value_p10),
            "recoverable_value_p50": _decimal_or_none(self.recoverable_value_p50),
            "recoverable_value_p90": _decimal_or_none(self.recoverable_value_p90),
            "recoverable_value_n": self.recoverable_value_n,
            "provisional_constant_firing_rates": {
                key: str(value) for key, value in self.provisional_constant_firing_rates.items()
            },
            "inter_confirmation_span_ns_p10": self.inter_confirmation_span_ns_p10,
            "inter_confirmation_span_ns_p50": self.inter_confirmation_span_ns_p50,
            "inter_confirmation_span_ns_p90": self.inter_confirmation_span_ns_p90,
            "inter_confirmation_span_n": self.inter_confirmation_span_n,
            "per_station_trial_counts": dict(self.per_station_trial_counts),
            "per_leg_trial_counts": dict(self.per_leg_trial_counts),
            "skipped_station_days": [
                {
                    "station": row.station,
                    "climate_day": row.climate_day.isoformat(),
                    "reason": row.reason,
                }
                for row in self.skipped_station_days
            ],
        }


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _percentile(sorted_values: Sequence[Decimal], q: Decimal) -> Decimal:
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    return sorted_values[lower_index] + (
        sorted_values[upper_index] - sorted_values[lower_index]
    ) * fraction


def build_corpus_report(
    *,
    results: Sequence[tuple[HypotheticalTake, PositionMonitorSummary, ReplayDiagnostics]],
    skipped_station_days: Sequence[SkippedStationDay],
    window_start: dt.date,
    window_end: dt.date,
    stations: Sequence[str],
    generated_at_ns: int,
) -> CorpusReport:
    """Aggregate every trial's replay into the headline descriptive report
    (A4/P5/P6). Below :data:`CALIBRATION_FLOOR_STATION_DAYS` usable
    station-days, the rate fields are reported ``None`` (UNCALIBRATED) even
    though the raw numerator/denominator counts are always populated.
    """
    usable_station_days = len({(take.station, take.climate_day) for take, _, _ in results})
    calibrated = usable_station_days >= CALIBRATION_FLOOR_STATION_DAYS

    dead_denominator = sum(1 for _, _, diag in results if diag.dead_evaluations > 0)
    dead_numerator = sum(
        1
        for _, summary, diag in results
        if diag.dead_evaluations > 0
        and summary.settled_pnl is not None
        and summary.settled_pnl < _ZERO
    )
    threatened_evaluations = sum(diag.threatened_evaluations for _, _, diag in results)
    archive_covered_evaluations = sum(
        diag.archive_covered_evaluations for _, _, diag in results
    )
    missing_stop_numerator = sum(diag.missing_stop_evaluations for _, _, diag in results)
    missing_stop_denominator = sum(diag.dead_evaluations for _, _, diag in results)

    recoverable_values = sorted(
        value
        for _, _, diag in results
        for value in diag.exit_recommended_recoverable_values
    )
    spans = sorted(
        span
        for _, _, diag in results
        for span in (*diag.dead_confirmation_spans_ns, *diag.threatened_confirmation_spans_ns)
    )

    reason_totals: Counter[str] = Counter()
    total_evaluations = 0
    for _, summary, diag in results:
        reason_totals.update(diag.reason_code_counts)
        total_evaluations += summary.total_frames
    firing_rates = (
        {
            reason: Decimal(count) / Decimal(total_evaluations)
            for reason, count in sorted(reason_totals.items())
        }
        if total_evaluations > 0
        else {}
    )

    per_station: Counter[str] = Counter(take.station for take, _, _ in results)
    per_leg: Counter[str] = Counter(take.leg for take, _, _ in results)

    span_decimals = [Decimal(span) for span in spans]

    return CorpusReport(
        generated_at_ns=generated_at_ns,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        stations=tuple(stations),
        usable_station_days=usable_station_days,
        calibration_status="CALIBRATED" if calibrated else "UNCALIBRATED",
        n_trials=len(results),
        dead_precision=(
            Decimal(dead_numerator) / Decimal(dead_denominator)
            if calibrated and dead_denominator > 0
            else None
        ),
        dead_precision_numerator=dead_numerator,
        dead_precision_denominator=dead_denominator,
        threatened_base_rate=(
            Decimal(threatened_evaluations) / Decimal(archive_covered_evaluations)
            if calibrated and archive_covered_evaluations > 0
            else None
        ),
        threatened_evaluations=threatened_evaluations,
        archive_covered_evaluations=archive_covered_evaluations,
        missing_stop_rate=(
            Decimal(missing_stop_numerator) / Decimal(missing_stop_denominator)
            if calibrated and missing_stop_denominator > 0
            else None
        ),
        missing_stop_numerator=missing_stop_numerator,
        missing_stop_denominator=missing_stop_denominator,
        recoverable_value_p10=(
            _percentile(recoverable_values, _P10) if calibrated and recoverable_values else None
        ),
        recoverable_value_p50=(
            _percentile(recoverable_values, _P50) if calibrated and recoverable_values else None
        ),
        recoverable_value_p90=(
            _percentile(recoverable_values, _P90) if calibrated and recoverable_values else None
        ),
        recoverable_value_n=len(recoverable_values),
        provisional_constant_firing_rates=firing_rates if calibrated else {},
        inter_confirmation_span_ns_p10=(
            int(_percentile(span_decimals, _P10)) if calibrated and span_decimals else None
        ),
        inter_confirmation_span_ns_p50=(
            int(_percentile(span_decimals, _P50)) if calibrated and span_decimals else None
        ),
        inter_confirmation_span_ns_p90=(
            int(_percentile(span_decimals, _P90)) if calibrated and span_decimals else None
        ),
        inter_confirmation_span_n=len(spans),
        per_station_trial_counts=dict(sorted(per_station.items())),
        per_leg_trial_counts=dict(sorted(per_leg.items())),
        skipped_station_days=tuple(skipped_station_days),
    )
