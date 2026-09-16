"""INC-6 -- nightly report over the intra-day position monitor (SHADOW-ONLY).

Spec: `docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md` Sec 4 ("Nightly
report") and Sec 6 INC-6. Joins the monitor's per-position-day summary store
(`breezy.strategy.current_rung_hold.monitor_store.read_monitor_summaries`)
against the settlement scorer's store
(`breezy.persistence.scored_trial_store.read_scored_trials`) on `trial_id`,
and reports description-only statistics on the shadow monitor's verdict
trail. This module NEVER feeds any statistic here back into PREREG v3's
LD-OBF tally (D6) and never touches trial selection (D3/L-34) -- it is a
pure, read-only reduction over two already-persisted stores.

Isolation (D2, pinned by `test_position_monitor_nightly_report.py`'s AST
scan): this module never imports `live_family_tally` (6d's live tally) or
`settlement/current_rung_hold_v2` (the v2 LD-OBF statistic) -- the tally may
later *read* this report's output file as an informational line, never the
reverse.

L-1 note on the n-gated metrics (M9): `nautilus_trader.core.nautilus_pyo3`'s
`Expectancy` and `WinRate` implement `calculate_from_realized_pnls(list[
float])` directly -- verified against the installed 1.231.0 wheel -- and are
called NATIVELY, unmodified, below. `ProfitFactor` and `MaxDrawdown` in the
same pyo3 module implement ONLY `calculate_from_returns(dict[int, float])`
(a fractional-return, compounding-equity-curve calculation); their
`calculate_from_realized_pnls` returns `None` unconditionally (also
verified). Routing raw dollar-denominated settled PnL through a
percentage-return algorithm would silently misrepresent the statistic (the
exact unit mismatch the repo lesson "a native substitution is a unit
change" warns against), so `_profit_factor`/`_max_drawdown` below are
authored as small pure functions over the ordered dollar-PnL sequence
instead -- a genuine, narrow GAP in the native surface for this input
shape, not a declined native capability.

INC-E5 (`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` Sec 1/3, plan
row "How the measurement reads"): three further DESCRIPTIVE series, keyed
per registered exit rule (`R_THREAT`/`R_DEAD`) plus a `SETTLED` hold
-control -- realized pnl, avoided loss and a per-rule premature-exit rate.
Same D2/D6 isolation as every other series in this module: NEVER an
LD-OBF/tally input, and `RuleSeries.armed`/`.family` state plainly, from
`persistence/exit_gate.family_declares_exit_rule` (the code-registered
gate, never a manifest field alone), whether the underlying rule has ever
been allowed to submit a real order -- `False` for every family today,
since PREREG v4 (`pm_us_crh_exit_v4`) has not yet registered `exit_rule`
(plan Sec 2, INC-E1..E4: "Nothing in E1-E3 can reach the venue"). UNITS:
these three series are PER-CONTRACT throughout (mirrors `ScoredTrial.pnl`),
never the TOTAL-POSITION-dollar convention `AvoidedLossSummary`/
`_realized_vs_mark_delta` use above -- deliberate, because every
`ExitAuthorization` closes exactly 1 contract (plan Sec 1), so a
per-contract figure is the one this seam's data model supports without
inventing a partial-fill allocation this increment never measures. A
`ScoredTrial` (`settlement/trial_scorer.py`) carries no exit provenance of
its own (`trial_day_latch.TrialDayRecord.exit_reason`/`exit_px`/`exit_fee`
live on the trial-day record, not the scorer's output) -- this increment
therefore joins on `PositionMonitorSummary`'s OWN `exit_rule`/
`exit_decision`/`exit_limit_price` fields (INC-E3) instead, and reads the
entry fee from the joined `ScoredTrial.fee` when one exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from nautilus_trader.core.nautilus_pyo3 import Expectancy, WinRate

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_correction_probe import wilson_interval

from breezy.persistence.exit_gate import family_declares_exit_rule
from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.persistence.scored_trial_store import read_scored_trials
from breezy.settlement.trial_scorer import ScoredTrial
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.monitor_evidence import (
    exit_fee as _per_contract_exit_fee,
)
from breezy.strategy.current_rung_hold.monitor_records import (
    PositionMonitorSummary,
)
from breezy.strategy.current_rung_hold.monitor_store import (
    read_monitor_summaries,
)

__all__ = [
    "DEFAULT_N_MIN",
    "MonitorReport",
    "RuleSeries",
    "build_monitor_report",
    "main",
]

#: M9 n-gate floor (mirrors `mb_current_rung_edge_study.N_MIN=172`'s role
#: for archive coverage, but this is a SEPARATE gate over settled shadow
#: -monitor positions -- see the spec's own `n_min=90` default).
DEFAULT_N_MIN: Final[int] = 90

#: Rev 2.1 addendum A4, PROVISIONAL: below this many usable INC-8
#: station-days, every hysteresis/LOCKED constant stays UNCALIBRATED.
CALIBRATION_FLOOR_STATION_DAYS: Final[int] = 30

#: INC-E5: the two registered exit rules (PREREG v4 Sec 1) `PositionMonitorSummary
#: .exit_rule` can name, plus the synthetic `SETTLED` hold-control group for
#: every joined row a decider never fired an exit for.
_EXIT_RULES: Final[tuple[str, ...]] = ("R_THREAT", "R_DEAD")
_SETTLED_GROUP: Final[str] = "SETTLED"
#: The one family this report has ever covered to date; used only as the
#: `RuleSeries.family` label when no explicit `FamilyManifest` is supplied
#: (`main`'s `--family-manifest` is optional). Never influences `armed`,
#: which is `False` whenever no manifest is supplied, regardless of this
#: label.
_DEFAULT_MONITORED_FAMILY_ID: Final[str] = "pm_us_crh_cont"
#: Same per-contract fee coefficient `decision.py`/`monitor_evidence.py`
#: already require (`CurrentRungHoldConfig.required_fee_coefficient`) --
#: read from that ONE source rather than re-declaring `Decimal("0.06")`
#: here, so this report can never silently drift from the live schedule.
_FEE_COEFFICIENT: Final[Decimal] = CurrentRungHoldConfig().required_fee_coefficient

_VERDICT_ORDER: Final[tuple[str, ...]] = (
    "HOLD",
    "REDUCE_RECOMMENDED",
    "EXIT_RECOMMENDED",
    "MISSING_STOP",
    "UNKNOWN",
)
_DEAD_CANDIDATE_VERDICTS: Final[frozenset[str]] = frozenset({"EXIT_RECOMMENDED", "MISSING_STOP"})


def _normalize_verdict(verdict: str | None) -> str:
    return "HOLD" if verdict is None else verdict


def _dstr(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class WilsonEstimate:
    """A description-only Wilson 95% interval -- never merged into any LD-OBF statistic."""

    k: int
    n: int
    point: float | None
    lower: float
    upper: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "n": self.n,
            "point": self.point,
            "lower": self.lower,
            "upper": self.upper,
        }


def _wilson_estimate(k: int, n: int) -> WilsonEstimate:
    if n == 0:
        return WilsonEstimate(k=0, n=0, point=None, lower=0.0, upper=0.0)
    lower, upper = wilson_interval(k, n)
    return WilsonEstimate(k=k, n=n, point=k / n, lower=lower, upper=upper)


@dataclass(frozen=True, slots=True, kw_only=True)
class VerdictContingencyRow:
    verdict: str
    settled_held_true: int
    settled_held_false: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "settled_held_true": self.settled_held_true,
            "settled_held_false": self.settled_held_false,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DecimalRangeSummary:
    n: int
    min: Decimal | None
    median: Decimal | None
    max: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "min": _dstr(self.min),
            "median": _dstr(self.median),
            "max": _dstr(self.max),
        }


def _decimal_range_summary(values: Sequence[Decimal]) -> DecimalRangeSummary:
    if not values:
        return DecimalRangeSummary(n=0, min=None, median=None, max=None)
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    median = ordered[mid] if n % 2 == 1 else (ordered[mid - 1] + ordered[mid]) / 2
    return DecimalRangeSummary(n=n, min=ordered[0], median=median, max=ordered[-1])


@dataclass(frozen=True, slots=True, kw_only=True)
class AvoidedLossSummary:
    """Sum of `recoverable_value_at_signal - settled_pnl_total` over losing EXIT rows.

    UNITS (HIGH review fix): `recoverable_value_at_signal`
    (`monitor_evidence.py`'s `mark_vwap * held_qty - exit_fee_at_mark`) is a
    TOTAL-POSITION dollar mark, but `settled_pnl` (`ScoredTrial.pnl` /
    `trial_scorer.py:194`, and the hypothetical corpus's
    `monitor_hypothetical_core.py:476-480`) is PER-CONTRACT
    (`1{held} - fill_px - fee`, no quantity term). `total` below is computed
    entirely in TOTAL-POSITION dollars by scaling `settled_pnl` by
    `held_qty` first -- see `_avoided_loss`.

    Only rows with a `recoverable_value_at_signal` (a true depth-walked
    mark, never a post-hoc bid -- L-18) are included; a missing mark is
    excluded and counted, never treated as zero.
    """

    total: Decimal
    n_included: int
    n_excluded_missing_mark: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": str(self.total),
            "n_included": self.n_included,
            "n_excluded_missing_mark": self.n_excluded_missing_mark,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleSeries:
    """INC-E5: one §1 DESCRIPTIVE series for one exit rule (or `SETTLED`).

    NEVER an LD-OBF/tally input (module docstring). `armed`/`family` say
    plainly whether this rule has ever been allowed to submit a real order
    (`persistence/exit_gate.family_declares_exit_rule`) -- until it has,
    every number here is shadow/counterfactual. See the module docstring's
    INC-E5 paragraph for the per-contract unit convention.
    """

    rule: str
    armed: bool
    family: str
    n: int
    n_excluded_missing_price_or_fee: int
    realized_pnl_total: Decimal
    avoided_loss_total: Decimal
    premature_exit_rate: WilsonEstimate

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "armed": self.armed,
            "family": self.family,
            "n": self.n,
            "n_excluded_missing_price_or_fee": self.n_excluded_missing_price_or_fee,
            "realized_pnl_total": str(self.realized_pnl_total),
            "avoided_loss_total": str(self.avoided_loss_total),
            "premature_exit_rate": self.premature_exit_rate.to_dict(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OneSidedBookRate:
    rate: float | None
    mark_missing_frames: int
    total_frames: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": self.rate,
            "mark_missing_frames": self.mark_missing_frames,
            "total_frames": self.total_frames,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NGatedMetrics:
    """Expectancy/profit-factor/max-drawdown/win-rate, gated below `n_min` (M9)."""

    label: str
    observed_n: int
    n_min: int
    expectancy: float | None
    profit_factor: float | None
    max_drawdown: float | None
    win_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "observed_n": self.observed_n,
            "n_min": self.n_min,
            "expectancy": self.expectancy,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationStatus:
    """Rev 2.1 addendum A4: constants stay UNCALIBRATED pending an INC-8 corpus."""

    constants_calibrated: bool
    reason: str
    usable_station_days: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "constants_calibrated": self.constants_calibrated,
            "reason": self.reason,
            "usable_station_days": self.usable_station_days,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MonitorReport:
    total_positions: int
    settled_count: int
    unsettled_count: int
    settled_from_scored_trials: int
    settled_from_summary: int
    by_leg: Mapping[str, int]
    by_entry_context: Mapping[str, int]
    contingency_table: tuple[VerdictContingencyRow, ...]
    contingency_table_by_entry_context: Mapping[str, tuple[VerdictContingencyRow, ...]]
    premature_exit_rate: WilsonEstimate
    dead_precision: WilsonEstimate
    avoided_loss: AvoidedLossSummary
    one_sided_book: OneSidedBookRate
    exit_timing_histogram: Mapping[int, int]
    mae_summary: DecimalRangeSummary
    mfe_summary: DecimalRangeSummary
    #: `settled_pnl` (scaled to TOTAL-POSITION dollars) minus the
    #: signal-instant mark-implied PnL, also TOTAL-POSITION dollars -- see
    #: `_realized_vs_mark_delta`'s docstring for the unit derivation.
    realized_vs_mark_delta: DecimalRangeSummary
    n_gated: NGatedMetrics
    calibration: CalibrationStatus
    #: INC-E5: keyed by `"R_THREAT"`, `"R_DEAD"`, `"SETTLED"` -- see
    #: `RuleSeries` and the module docstring's INC-E5 paragraph.
    exit_rule_series: Mapping[str, RuleSeries]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_positions": self.total_positions,
            "settled_count": self.settled_count,
            "unsettled_count": self.unsettled_count,
            "settled_from_scored_trials": self.settled_from_scored_trials,
            "settled_from_summary": self.settled_from_summary,
            "by_leg": dict(self.by_leg),
            "by_entry_context": dict(self.by_entry_context),
            "contingency_table": [row.to_dict() for row in self.contingency_table],
            "contingency_table_by_entry_context": {
                context: [row.to_dict() for row in rows]
                for context, rows in self.contingency_table_by_entry_context.items()
            },
            "premature_exit_rate": self.premature_exit_rate.to_dict(),
            "dead_precision": self.dead_precision.to_dict(),
            "avoided_loss": self.avoided_loss.to_dict(),
            "one_sided_book": self.one_sided_book.to_dict(),
            "exit_timing_histogram": {
                str(hour): count for hour, count in sorted(self.exit_timing_histogram.items())
            },
            "mae_summary": self.mae_summary.to_dict(),
            "mfe_summary": self.mfe_summary.to_dict(),
            "realized_vs_mark_delta": self.realized_vs_mark_delta.to_dict(),
            "n_gated": self.n_gated.to_dict(),
            "calibration": self.calibration.to_dict(),
            "exit_rule_series": {
                rule: series.to_dict() for rule, series in self.exit_rule_series.items()
            },
        }


#: `_Joined.settlement_source` values -- which store answered the settlement question.
_SOURCE_SCORED_TRIAL: Final[str] = "scored_trial"
_SOURCE_SUMMARY: Final[str] = "summary"


@dataclass(frozen=True, slots=True, kw_only=True)
class _Joined:
    """One monitor summary, settled either by a joined `ScoredTrial` or by its
    own `settled_held`/`settled_pnl` (see `_join`'s docstring for the order).
    """

    summary: PositionMonitorSummary
    settled_pnl: Decimal
    settled_held: bool
    climate_day: str
    trial_id: str
    verdict_at_signal: str | None
    settlement_source: str
    #: INC-E5: the joined `ScoredTrial.fee` (entry leg, per-contract) when
    #: `settlement_source == _SOURCE_SCORED_TRIAL`. `None` for the INC-8
    #: hypothetical corpus (`_SOURCE_SUMMARY`), which never carries a
    #: separate entry-fee figure -- excluded from `RuleSeries` pricing
    #: rather than guessed (see `_realized_pnl_per_contract`).
    entry_fee: Decimal | None


def _count_by(
    summaries: Sequence[PositionMonitorSummary], key: Any
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for summary in summaries:
        value = key(summary)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _join(
    summaries: Sequence[PositionMonitorSummary], scored_trials: Sequence[ScoredTrial]
) -> tuple[tuple[_Joined, ...], int]:
    """Settle each summary, preferring the joined `ScoredTrial` over the summary's own fields.

    Resolution order: (1) a `ScoredTrial` joined on `trial_id` -- authoritative
    for live trials, scored from the live settlement pipeline; (2) else the
    summary's own `settled_held`/`settled_pnl` when BOTH are not `None` -- this
    is the INC-8 hypothetical-hold corpus's path, whose rows are joined
    offline to NWS FINAL truth and by construction never have a `ScoredTrial`;
    (3) else the summary stays unsettled. A summary is never promoted to
    settled from a partial pair (one field present, the other `None`).
    """
    scored_by_id = {trial.trial_id: trial for trial in scored_trials}
    joined: list[_Joined] = []
    unsettled = 0
    for summary in summaries:
        trial = scored_by_id.get(summary.trial_id)
        if trial is not None:
            joined.append(
                _Joined(
                    summary=summary,
                    settled_pnl=trial.pnl,
                    settled_held=trial.held,
                    climate_day=summary.climate_day,
                    trial_id=summary.trial_id,
                    verdict_at_signal=summary.verdict_at_signal,
                    settlement_source=_SOURCE_SCORED_TRIAL,
                    entry_fee=trial.fee,
                )
            )
            continue
        if summary.settled_held is not None and summary.settled_pnl is not None:
            joined.append(
                _Joined(
                    summary=summary,
                    settled_pnl=summary.settled_pnl,
                    settled_held=summary.settled_held,
                    climate_day=summary.climate_day,
                    trial_id=summary.trial_id,
                    verdict_at_signal=summary.verdict_at_signal,
                    settlement_source=_SOURCE_SUMMARY,
                    entry_fee=None,
                )
            )
            continue
        unsettled += 1
    return tuple(joined), unsettled


def _contingency_by_entry_context(
    joined: Sequence[_Joined],
) -> dict[str, tuple[VerdictContingencyRow, ...]]:
    """Contingency table per `entry_context` (live / reconciled / hypothetical).

    Only over settled rows, mirroring `_contingency_table`; a context with no
    settled rows is omitted rather than reported as an all-zero table.
    """
    contexts = sorted({row.summary.entry_context for row in joined})
    return {
        context: _contingency_table(
            tuple(row for row in joined if row.summary.entry_context == context)
        )
        for context in contexts
    }


def _contingency_table(joined: Sequence[_Joined]) -> tuple[VerdictContingencyRow, ...]:
    counts: dict[str, list[int]] = {verdict: [0, 0] for verdict in _VERDICT_ORDER}
    for row in joined:
        verdict = _normalize_verdict(row.verdict_at_signal)
        counts.setdefault(verdict, [0, 0])
        idx = 0 if row.settled_held else 1
        counts[verdict][idx] += 1
    ordered_keys = list(_VERDICT_ORDER) + sorted(k for k in counts if k not in _VERDICT_ORDER)
    return tuple(
        VerdictContingencyRow(
            verdict=verdict,
            settled_held_true=counts[verdict][0],
            settled_held_false=counts[verdict][1],
        )
        for verdict in ordered_keys
    )


def _premature_exit_rate(joined: Sequence[_Joined]) -> WilsonEstimate:
    rows = [
        row for row in joined if _normalize_verdict(row.verdict_at_signal) == "EXIT_RECOMMENDED"
    ]
    k = sum(1 for row in rows if row.settled_held)
    return _wilson_estimate(k, len(rows))


def _dead_precision(joined: Sequence[_Joined]) -> WilsonEstimate:
    rows = [
        row
        for row in joined
        if _normalize_verdict(row.verdict_at_signal) in _DEAD_CANDIDATE_VERDICTS
    ]
    k = sum(1 for row in rows if not row.settled_held)
    return _wilson_estimate(k, len(rows))


def _avoided_loss(joined: Sequence[_Joined]) -> AvoidedLossSummary:
    """See `AvoidedLossSummary`'s docstring for the TOTAL-POSITION-dollar unit fix."""
    total = Decimal(0)
    included = 0
    excluded = 0
    for row in joined:
        if row.settled_held or _normalize_verdict(row.verdict_at_signal) != "EXIT_RECOMMENDED":
            continue
        if row.summary.recoverable_value_at_signal is None:
            excluded += 1
            continue
        # `settled_pnl` is PER-CONTRACT; scale by `held_qty` (Decimal) so
        # both operands are TOTAL-POSITION dollars before subtracting.
        settled_pnl_total = row.settled_pnl * row.summary.held_qty
        total += row.summary.recoverable_value_at_signal - settled_pnl_total
        included += 1
    return AvoidedLossSummary(total=total, n_included=included, n_excluded_missing_mark=excluded)


def _rule_group(summary: PositionMonitorSummary) -> str:
    """Which INC-E5 group `summary` belongs to.

    A row belongs to its own most-recent FIRED exit rule only when that
    rule is one of the two PREREG v4 registers (`_EXIT_RULES`); every other
    row -- including every row before INC-E3 (backward compat: `exit_rule`
    defaults to `None`) and every REFUSED decision -- falls to the
    `SETTLED` hold-control group, since it was, in fact, held to
    settlement.
    """
    if summary.exit_decision == "fired" and summary.exit_rule in _EXIT_RULES:
        return summary.exit_rule
    return _SETTLED_GROUP


def _realized_pnl_per_contract(row: _Joined, group: str) -> Decimal | None:
    """The realized-pnl side of INC-E5's comparison, per contract.

    `SETTLED` (never exited): realized IS the settlement outcome --
    `row.settled_pnl` unchanged (so `avoided_loss` is trivially 0 for every
    `SETTLED` row, by construction, never a special case below).

    A FIRED exit: `exit_limit_price` (the authorised, shadow/counterfactual
    close -- pre-arming, no real fill exists) minus the exit's own
    per-contract fee, minus the entry `fill_px` and its own per-contract
    fee. `None` (excluded, never guessed) when either the authorised price
    or the joined entry fee is unavailable.
    """
    if group == _SETTLED_GROUP:
        return row.settled_pnl
    exit_price = row.summary.exit_limit_price
    if exit_price is None or row.entry_fee is None:
        return None
    fee_on_exit = _per_contract_exit_fee(exit_price, 1, _FEE_COEFFICIENT)
    return exit_price - fee_on_exit - row.summary.fill_px - row.entry_fee


def _exit_rule_series(
    joined: Sequence[_Joined], *, family_manifest: FamilyManifest | None
) -> dict[str, RuleSeries]:
    """Build the three INC-E5 `RuleSeries` (`R_THREAT`, `R_DEAD`, `SETTLED`).

    `armed` is `False` unconditionally when no manifest is supplied, and
    otherwise exactly `family_declares_exit_rule(family_manifest)` for the
    two real exit-rule groups -- `SETTLED` is never "armed" (it names the
    absence of an exit, not a rule that could fire).
    """
    family = (
        family_manifest.family_id if family_manifest is not None else _DEFAULT_MONITORED_FAMILY_ID
    )
    gate_open = family_manifest is not None and family_declares_exit_rule(family_manifest)

    series: dict[str, RuleSeries] = {}
    for group in (*_EXIT_RULES, _SETTLED_GROUP):
        is_exit_group = group != _SETTLED_GROUP
        rows = [row for row in joined if _rule_group(row.summary) == group]

        realized_total = Decimal(0)
        avoided_total = Decimal(0)
        n_excluded = 0
        for row in rows:
            realized = _realized_pnl_per_contract(row, group)
            if realized is None:
                n_excluded += 1
                continue
            realized_total += realized
            avoided_total += realized - row.settled_pnl

        premature_k = sum(1 for row in rows if row.settled_held) if is_exit_group else 0
        premature_n = len(rows) if is_exit_group else 0

        series[group] = RuleSeries(
            rule=group,
            armed=gate_open and is_exit_group,
            family=family,
            n=len(rows),
            n_excluded_missing_price_or_fee=n_excluded,
            realized_pnl_total=realized_total,
            avoided_loss_total=avoided_total,
            premature_exit_rate=_wilson_estimate(premature_k, premature_n),
        )
    return series


def _one_sided_book(summaries: Sequence[PositionMonitorSummary]) -> OneSidedBookRate:
    missing = sum(summary.mark_missing_frames for summary in summaries)
    total = sum(summary.total_frames for summary in summaries)
    rate = None if total == 0 else missing / total
    return OneSidedBookRate(rate=rate, mark_missing_frames=missing, total_frames=total)


def _exit_timing_histogram(summaries: Sequence[PositionMonitorSummary]) -> dict[int, int]:
    histogram: dict[int, int] = {}
    for summary in summaries:
        hour = summary.first_signal_hour_lst
        if hour is None:
            continue
        histogram[hour] = histogram.get(hour, 0) + 1
    return histogram


def _mark_implied_pnl(row: _Joined) -> Decimal | None:
    """PnL implied by exiting the full held quantity at the signal-instant mark.

    UNITS: TOTAL-POSITION dollars throughout -- `recoverable_value_at_signal`
    is already `mark_vwap * held_qty - exit_fee_at_mark`
    (`monitor_evidence.py`) and `fill_px * held_qty` here is the total cost
    basis, so no further scaling is needed on this side of the comparison
    (contrast `row.settled_pnl`, which is PER-CONTRACT -- see
    `_realized_vs_mark_delta`).
    """
    if row.summary.recoverable_value_at_signal is None:
        return None
    return row.summary.recoverable_value_at_signal - (row.summary.fill_px * row.summary.held_qty)


def _realized_vs_mark_delta(joined: Sequence[_Joined]) -> DecimalRangeSummary:
    """`settled_pnl` (scaled to TOTAL-POSITION dollars) minus `_mark_implied_pnl`.

    UNITS (HIGH review fix): `_mark_implied_pnl` is TOTAL-POSITION dollars
    (see its docstring), but `row.settled_pnl` (`ScoredTrial.pnl`) is
    PER-CONTRACT. Scale by `held_qty` (Decimal) before subtracting so both
    operands share a unit -- identical fix and rationale as `_avoided_loss`.
    """
    deltas = []
    for row in joined:
        implied = _mark_implied_pnl(row)
        if implied is None:
            continue
        settled_pnl_total = row.settled_pnl * row.summary.held_qty
        deltas.append(settled_pnl_total - implied)
    return _decimal_range_summary(tuple(deltas))


def _profit_factor(pnls: Sequence[float]) -> float | None:
    """Gains / |losses|; `None` (undefined) when there are no losing trials."""
    gains = sum(pnl for pnl in pnls if pnl > 0)
    losses = -sum(pnl for pnl in pnls if pnl < 0)
    if losses == 0:
        return None
    return gains / losses


def _max_drawdown(pnls: Sequence[float]) -> float:
    """Max peak-to-trough decline of the cumulative dollar-PnL equity curve."""
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return worst


def _n_gated_metrics(joined: Sequence[_Joined], *, n_min: int) -> NGatedMetrics:
    observed_n = len(joined)
    if observed_n < n_min:
        return NGatedMetrics(
            label="INSUFFICIENT_N",
            observed_n=observed_n,
            n_min=n_min,
            expectancy=None,
            profit_factor=None,
            max_drawdown=None,
            win_rate=None,
        )
    ordered = sorted(joined, key=lambda row: (row.climate_day, row.trial_id))
    pnls = [float(row.settled_pnl) for row in ordered]
    return NGatedMetrics(
        label="COMPUTED",
        observed_n=observed_n,
        n_min=n_min,
        expectancy=Expectancy().calculate_from_realized_pnls(pnls),
        profit_factor=_profit_factor(pnls),
        max_drawdown=_max_drawdown(pnls),
        win_rate=WinRate().calculate_from_realized_pnls(pnls),
    )


def _calibration_status(usable_station_days: int | None) -> CalibrationStatus:
    if usable_station_days is None:
        return CalibrationStatus(
            constants_calibrated=False,
            reason="INC-8 corpus not yet available",
            usable_station_days=None,
        )
    if usable_station_days < CALIBRATION_FLOOR_STATION_DAYS:
        return CalibrationStatus(
            constants_calibrated=False,
            reason=(
                f"usable_station_days={usable_station_days} below the PROVISIONAL floor "
                f"{CALIBRATION_FLOOR_STATION_DAYS}"
            ),
            usable_station_days=usable_station_days,
        )
    return CalibrationStatus(
        constants_calibrated=True, reason="", usable_station_days=usable_station_days
    )


def build_monitor_report(
    summaries: Sequence[PositionMonitorSummary],
    scored_trials: Sequence[ScoredTrial],
    *,
    n_min: int = DEFAULT_N_MIN,
    usable_station_days: int | None = None,
    family_manifest: FamilyManifest | None = None,
) -> MonitorReport:
    """Build the nightly report purely from already-read `summaries`/`scored_trials`.

    Never queries a catalog or store itself (D3/L-34: monitoring stays
    read-only w.r.t. trial selection). Settlement per summary resolves in
    order: a joined `ScoredTrial` (authoritative for live trials), else the
    summary's own `settled_held`/`settled_pnl` when both are present (the
    INC-8 hypothetical-hold corpus, which never has a `ScoredTrial` by
    construction), else unsettled -- see `_join`. A summary settled neither
    way is counted as unsettled, never dropped and never treated as settled.
    """
    joined, unsettled = _join(summaries, scored_trials)
    settled_from_scored_trials = sum(
        1 for row in joined if row.settlement_source == _SOURCE_SCORED_TRIAL
    )
    settled_from_summary = len(joined) - settled_from_scored_trials

    return MonitorReport(
        total_positions=len(summaries),
        settled_count=len(joined),
        unsettled_count=unsettled,
        settled_from_scored_trials=settled_from_scored_trials,
        settled_from_summary=settled_from_summary,
        by_leg=MappingProxyType(_count_by(summaries, lambda s: s.leg)),
        by_entry_context=MappingProxyType(_count_by(summaries, lambda s: s.entry_context)),
        contingency_table=_contingency_table(joined),
        contingency_table_by_entry_context=MappingProxyType(
            _contingency_by_entry_context(joined)
        ),
        premature_exit_rate=_premature_exit_rate(joined),
        dead_precision=_dead_precision(joined),
        avoided_loss=_avoided_loss(joined),
        one_sided_book=_one_sided_book(summaries),
        exit_timing_histogram=MappingProxyType(_exit_timing_histogram(summaries)),
        mae_summary=_decimal_range_summary(tuple(s.mae for s in summaries)),
        mfe_summary=_decimal_range_summary(tuple(s.mfe for s in summaries)),
        realized_vs_mark_delta=_realized_vs_mark_delta(joined),
        n_gated=_n_gated_metrics(joined, n_min=n_min),
        calibration=_calibration_status(usable_station_days),
        exit_rule_series=MappingProxyType(
            _exit_rule_series(joined, family_manifest=family_manifest)
        ),
    )


def _render_markdown(report: MonitorReport) -> str:
    calibration_word = "CALIBRATED" if report.calibration.constants_calibrated else "UNCALIBRATED"
    lines = [
        "# Position monitor nightly report",
        "",
        (
            f"positions: {report.total_positions} "
            f"(settled {report.settled_count}, unsettled {report.unsettled_count})"
        ),
        (
            f"settled by source: scored_trials={report.settled_from_scored_trials} "
            f"summary={report.settled_from_summary}"
        ),
        (
            f"premature-exit rate: point={report.premature_exit_rate.point} "
            f"[{report.premature_exit_rate.lower:.4f}, {report.premature_exit_rate.upper:.4f}] "
            f"n={report.premature_exit_rate.n}"
        ),
        f"DEAD precision: point={report.dead_precision.point} n={report.dead_precision.n}",
        (
            f"avoided-loss sum: {report.avoided_loss.total} "
            f"(n={report.avoided_loss.n_included}, "
            f"excluded-missing-mark={report.avoided_loss.n_excluded_missing_mark})"
        ),
        f"one-sided-book rate: {report.one_sided_book.rate}",
        (
            f"n-gated metrics: {report.n_gated.label} "
            f"(n={report.n_gated.observed_n}, n_min={report.n_gated.n_min})"
        ),
        f"calibration: {calibration_word} -- {report.calibration.reason}",
        "",
    ]
    for group in (*_EXIT_RULES, _SETTLED_GROUP):
        rule_series = report.exit_rule_series[group]
        lines.append(
            f"{group}: ARMED: {rule_series.armed} family: {rule_series.family} "
            f"n={rule_series.n} realized_pnl_total={rule_series.realized_pnl_total} "
            f"avoided_loss_total={rule_series.avoided_loss_total} "
            f"premature_exit_rate point={rule_series.premature_exit_rate.point} "
            f"n={rule_series.premature_exit_rate.n}"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summaries-dir", type=Path, required=True,
        help="position_monitor_summaries parquet directory (monitor_store.py)",
    )
    parser.add_argument(
        "--scored-trials-dir", type=Path, required=True,
        help="scored_trials parquet directory (scored_trial_store.py)",
    )
    parser.add_argument("--out", type=Path, required=True, help="path to write the JSON report")
    parser.add_argument(
        "--markdown", type=Path, default=None, help="optional path to write a Markdown rendering"
    )
    parser.add_argument("--n-min", type=int, default=DEFAULT_N_MIN, help="M9 n-gate floor")
    parser.add_argument(
        "--corpus-summary", type=Path, default=None,
        help='optional INC-8 corpus summary JSON: {"usable_station_days": int}',
    )
    parser.add_argument(
        "--family-manifest", type=Path, default=None,
        help=(
            "optional deploy/families/<family>.json path, so the INC-E5 "
            "RuleSeries lines can report a real armed/family label instead "
            "of the default"
        ),
    )
    args = parser.parse_args(argv)

    summaries = read_monitor_summaries(args.summaries_dir)
    scored_trials = read_scored_trials(args.scored_trials_dir)

    usable_station_days: int | None = None
    if args.corpus_summary is not None:
        payload = json.loads(args.corpus_summary.read_text())
        usable_station_days = int(payload["usable_station_days"])

    family_manifest: FamilyManifest | None = None
    if args.family_manifest is not None:
        # `allow_draft=True`: a DRAFT_NOT_REGISTERED manifest (e.g. today's
        # `pm_us_crh_exit_v4.json`) must still load so its `armed=False`
        # state can be reported, never refused just for being unregistered.
        family_manifest = load_family_manifest(args.family_manifest, allow_draft=True)

    report = build_monitor_report(
        summaries,
        scored_trials,
        n_min=args.n_min,
        usable_station_days=usable_station_days,
        family_manifest=family_manifest,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True))

    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(_render_markdown(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
