"""RED-first tests for the intra-day position monitor nightly report (INC-6).

Spec: `docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md` Sec 4 ("Nightly
report") and Sec 6 INC-6. The report is a PURE function
(`build_monitor_report`) over already-read `PositionMonitorSummary` and
`ScoredTrial` rows -- no catalog/store I/O in the function under test here
except in the dedicated CLI test at the bottom.

Isolation (D2/INC-6 completion criterion): the script must never import
`live_family_tally` or `settlement/current_rung_hold_v2` -- verified here by
an AST scan of the script's own source, never by a runtime import (a runtime
import would itself violate the isolation this test exists to enforce).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.persistence.family_manifest import FamilyManifest
from breezy.settlement.trial_scorer import ScoredTrial
from breezy.strategy.current_rung_hold.monitor_records import PositionMonitorSummary

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_SCRIPT_PATH = _SCRIPTS_ANALYSIS_DIR / "position_monitor_nightly_report.py"

_BASE_SCORED_NS = 1_757_000_000_000_000_000


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    spec = importlib.util.spec_from_file_location(
        "position_monitor_nightly_report", _SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report_mod() -> ModuleType:
    return _load_module()


def _summary(**overrides: object) -> PositionMonitorSummary:
    base: dict[str, object] = {
        "trial_id": "continuous_rung_hold/trial/SFO/2026-09-01/sfo-86-87.POLYMARKET_US",
        "instrument_id": "sfo-86-87.POLYMARKET_US",
        "station": "SFO",
        "climate_day": "2026-09-01",
        "leg": "YES",
        "entry_context": "live",
        "monitor_seq": 1,
        "fill_px": Decimal("0.55"),
        "held_qty": Decimal(1),
        "mae": Decimal("0.10"),
        "mfe": Decimal("0.25"),
        "first_signal_ts_ns": None,
        "first_signal_hour_lst": None,
        "first_signal_state": None,
        "verdict_at_signal": None,
        "recoverable_value_at_signal": None,
        "held_duration_ns": 3_600_000_000_000,
        "total_frames": 10,
        "mark_missing_frames": 0,
        "settled_pnl": None,
        "settled_held": None,
    }
    base.update(overrides)
    return PositionMonitorSummary(**base)  # type: ignore[arg-type]


def _trial(**overrides: object) -> ScoredTrial:
    base: dict[str, object] = {
        "trial_id": "continuous_rung_hold/trial/SFO/2026-09-01/sfo-86-87.POLYMARKET_US",
        "station": "SFO",
        "climate_day": "2026-09-01",
        "instrument_id": "sfo-86-87.POLYMARKET_US",
        "settlement_tmax_f": 79,
        "held": True,
        "pnl": Decimal("0.45"),
        "revision_seq": 1,
        "raw_sha256": "a" * 64,
        "scored_at_ns": _BASE_SCORED_NS,
        "score_seq": 0,
        "settlement_basis": "nws_final",
        "excluded_reason": None,
        "slippage": Decimal("0.02"),
        "entry_ask": Decimal("0.40"),
        "fill_px": Decimal("0.55"),
        "fee": Decimal("0.01"),
    }
    base.update(overrides)
    return ScoredTrial(**base)  # type: ignore[arg-type]


class TestJoin:
    def test_unjoined_summary_is_counted_as_unsettled_not_dropped(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A"),
            _summary(trial_id="B"),
        )
        scored = (_trial(trial_id="A", held=True, pnl=Decimal("0.30")),)

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.total_positions == 2
        assert report.settled_count == 1
        assert report.unsettled_count == 1

    def test_counts_by_leg_and_entry_context_cover_every_summary_regardless_of_settlement(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", leg="YES", entry_context="live"),
            _summary(trial_id="B", leg="NO", entry_context="reconciled"),
            _summary(trial_id="C", leg="YES", entry_context="live"),
        )

        report = report_mod.build_monitor_report(summaries, ())

        assert dict(report.by_leg) == {"YES": 2, "NO": 1}
        assert dict(report.by_entry_context) == {"live": 2, "reconciled": 1}


class TestSettlementResolution:
    """The hypothetical-hold corpus carries its own `settled_*` fields and by
    construction never has a matching `ScoredTrial` (GAP fix): a summary must
    settle from its own `settled_held`/`settled_pnl` when no `ScoredTrial`
    joins, never fall through to unsettled just because it is not a live trial.
    """

    def test_summary_with_no_scored_trial_settles_from_its_own_settled_fields(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(
                trial_id="hypo:SFO:2026-09-01:0",
                entry_context="hypothetical",
                settled_held=True,
                settled_pnl=Decimal("0.45"),
            ),
        )

        report = report_mod.build_monitor_report(summaries, ())

        assert report.settled_count == 1
        assert report.unsettled_count == 0
        assert report.settled_from_scored_trials == 0
        assert report.settled_from_summary == 1

    def test_summary_missing_either_settled_field_stays_unsettled(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(
                trial_id="hypo:SFO:2026-09-01:0",
                entry_context="hypothetical",
                settled_held=True,
                settled_pnl=None,
            ),
            _summary(
                trial_id="hypo:SFO:2026-09-01:1",
                entry_context="hypothetical",
                settled_held=None,
                settled_pnl=Decimal("0.10"),
            ),
        )

        report = report_mod.build_monitor_report(summaries, ())

        assert report.settled_count == 0
        assert report.unsettled_count == 2
        assert report.settled_from_scored_trials == 0
        assert report.settled_from_summary == 0

    def test_joined_scored_trial_is_authoritative_over_the_summarys_own_settled_fields(
        self, report_mod: ModuleType
    ) -> None:
        # The summary claims HELD True / pnl +0.99; the joined ScoredTrial
        # (live, authoritative) disagrees: HELD False / pnl -0.50. The
        # ScoredTrial must win.
        summaries = (
            _summary(
                trial_id="A",
                entry_context="live",
                verdict_at_signal="EXIT_RECOMMENDED",
                settled_held=True,
                settled_pnl=Decimal("0.99"),
            ),
        )
        scored = (_trial(trial_id="A", held=False, pnl=Decimal("-0.50")),)

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.settled_from_scored_trials == 1
        assert report.settled_from_summary == 0
        by_verdict = {row.verdict: row for row in report.contingency_table}
        assert by_verdict["EXIT_RECOMMENDED"].settled_held_true == 0
        assert by_verdict["EXIT_RECOMMENDED"].settled_held_false == 1
        assert report.dead_precision.k == 1
        assert report.dead_precision.n == 1

    def test_mixed_corpus_counts_each_source_separately(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", entry_context="live"),
            _summary(
                trial_id="hypo:SFO:2026-09-01:0",
                entry_context="hypothetical",
                settled_held=False,
                settled_pnl=Decimal("-0.10"),
            ),
            _summary(trial_id="unresolved", entry_context="live"),
        )
        scored = (_trial(trial_id="A", held=True, pnl=Decimal("0.20")),)

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.total_positions == 3
        assert report.settled_count == 2
        assert report.unsettled_count == 1
        assert report.settled_from_scored_trials == 1
        assert report.settled_from_summary == 1


class TestContingencyByEntryContext:
    def test_contingency_table_is_broken_out_per_entry_context(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", entry_context="live", verdict_at_signal="HOLD"),
            _summary(
                trial_id="hypo:SFO:2026-09-01:0",
                entry_context="hypothetical",
                verdict_at_signal="EXIT_RECOMMENDED",
                settled_held=False,
                settled_pnl=Decimal("-0.10"),
            ),
            _summary(
                trial_id="B", entry_context="reconciled", verdict_at_signal="HOLD"
            ),
        )
        scored = (
            _trial(trial_id="A", held=True),
            _trial(trial_id="B", held=True),
        )

        report = report_mod.build_monitor_report(summaries, scored)

        assert set(report.contingency_table_by_entry_context) == {
            "live",
            "hypothetical",
            "reconciled",
        }
        live_rows = {
            row.verdict: row for row in report.contingency_table_by_entry_context["live"]
        }
        assert live_rows["HOLD"].settled_held_true == 1
        assert live_rows["HOLD"].settled_held_false == 0

        hypothetical_rows = {
            row.verdict: row
            for row in report.contingency_table_by_entry_context["hypothetical"]
        }
        assert hypothetical_rows["EXIT_RECOMMENDED"].settled_held_true == 0
        assert hypothetical_rows["EXIT_RECOMMENDED"].settled_held_false == 1

    def test_omits_contexts_with_no_settled_rows(self, report_mod: ModuleType) -> None:
        summaries = (_summary(trial_id="A", entry_context="live"),)

        report = report_mod.build_monitor_report(summaries, ())

        assert report.contingency_table_by_entry_context == {}


class TestContingencyTable:
    def test_verdict_by_settled_held_counts_and_none_verdict_normalizes_to_hold(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", verdict_at_signal=None),
            _summary(trial_id="B", verdict_at_signal="EXIT_RECOMMENDED"),
            _summary(trial_id="C", verdict_at_signal="EXIT_RECOMMENDED"),
        )
        scored = (
            _trial(trial_id="A", held=True),
            _trial(trial_id="B", held=False),
            _trial(trial_id="C", held=True),
        )

        report = report_mod.build_monitor_report(summaries, scored)
        by_verdict = {row.verdict: row for row in report.contingency_table}

        assert by_verdict["HOLD"].settled_held_true == 1
        assert by_verdict["HOLD"].settled_held_false == 0
        assert by_verdict["EXIT_RECOMMENDED"].settled_held_true == 1
        assert by_verdict["EXIT_RECOMMENDED"].settled_held_false == 1


class TestPrematureExitRate:
    def test_matches_the_repo_wilson_helper_on_the_same_k_and_n(
        self, report_mod: ModuleType
    ) -> None:
        # `report_mod` imports the repo's own Wilson helper at module scope;
        # reused here (never re-derived) to avoid a second, potentially
        # drifting import path under a static analyzer.
        wilson_interval = report_mod.wilson_interval

        # 3 EXIT_RECOMMENDED rows, 1 held (premature exit) -> k=1, n=3.
        summaries = (
            _summary(trial_id="A", verdict_at_signal="EXIT_RECOMMENDED"),
            _summary(trial_id="B", verdict_at_signal="EXIT_RECOMMENDED"),
            _summary(trial_id="C", verdict_at_signal="EXIT_RECOMMENDED"),
        )
        scored = (
            _trial(trial_id="A", held=True),
            _trial(trial_id="B", held=False),
            _trial(trial_id="C", held=False),
        )

        report = report_mod.build_monitor_report(summaries, scored)
        expected_lower, expected_upper = wilson_interval(1, 3)

        assert report.premature_exit_rate.k == 1
        assert report.premature_exit_rate.n == 3
        assert report.premature_exit_rate.point == pytest.approx(1 / 3)
        assert report.premature_exit_rate.lower == pytest.approx(expected_lower)
        assert report.premature_exit_rate.upper == pytest.approx(expected_upper)

    def test_zero_denominator_returns_a_defined_zero_estimate_not_an_error(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (_summary(trial_id="A", verdict_at_signal="HOLD"),)
        scored = (_trial(trial_id="A", held=True),)

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.premature_exit_rate.n == 0
        assert report.premature_exit_rate.point is None


class TestDeadPrecision:
    def test_pools_exit_recommended_and_missing_stop_as_dead_candidates(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", verdict_at_signal="EXIT_RECOMMENDED"),
            _summary(trial_id="B", verdict_at_signal="MISSING_STOP"),
            _summary(trial_id="C", verdict_at_signal="EXIT_RECOMMENDED"),
        )
        scored = (
            _trial(trial_id="A", held=False),
            _trial(trial_id="B", held=False),
            _trial(trial_id="C", held=True),
        )

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.dead_precision.k == 2
        assert report.dead_precision.n == 3


class TestAvoidedLoss:
    def test_sums_recoverable_minus_settled_pnl_for_losing_exit_rows_only(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(
                trial_id="A",
                verdict_at_signal="EXIT_RECOMMENDED",
                recoverable_value_at_signal=Decimal("0.30"),
            ),
            _summary(
                trial_id="B",
                verdict_at_signal="EXIT_RECOMMENDED",
                recoverable_value_at_signal=None,
            ),
            _summary(
                trial_id="C",
                verdict_at_signal="EXIT_RECOMMENDED",
                recoverable_value_at_signal=Decimal("0.20"),
            ),
        )
        scored = (
            _trial(trial_id="A", held=False, pnl=Decimal("-0.50")),
            _trial(trial_id="B", held=False, pnl=Decimal("-0.60")),
            # C settled_held True -> not a loss, excluded from the sum.
            _trial(trial_id="C", held=True, pnl=Decimal("0.45")),
        )

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.avoided_loss.total == Decimal("0.80")
        assert report.avoided_loss.n_included == 1
        assert report.avoided_loss.n_excluded_missing_mark == 1

    def test_avoided_loss_scales_settled_pnl_by_held_qty_to_match_total_dollar_units(
        self, report_mod: ModuleType
    ) -> None:
        """HIGH review fix: `recoverable_value_at_signal` is a TOTAL-POSITION
        dollar mark (`mark_vwap * held_qty - exit_fee`, `monitor_evidence.py`)
        but `settled_pnl` (`ScoredTrial.pnl`) is PER-CONTRACT
        (`1{held} - fill_px - fee`). At `held_qty=2` mixing the two units
        without scaling silently corrupts the statistic.
        """
        summaries = (
            _summary(
                trial_id="A",
                held_qty=Decimal(2),
                fill_px=Decimal("0.40"),
                verdict_at_signal="EXIT_RECOMMENDED",
                recoverable_value_at_signal=Decimal("0.50"),
            ),
        )
        scored = (_trial(trial_id="A", held=False, pnl=Decimal("-0.41")),)

        report = report_mod.build_monitor_report(summaries, scored)

        # Hand-computed in TOTAL-POSITION dollars: 0.50 - (-0.41 * 2) == 1.32.
        assert report.avoided_loss.total == Decimal("1.32")
        assert report.avoided_loss.n_included == 1

    def test_avoided_loss_at_held_qty_one_is_unchanged_by_the_unit_fix(
        self, report_mod: ModuleType
    ) -> None:
        """Regression: at `held_qty=1` scaling by 1 is a no-op, so the
        pre-existing per-contract-looking figure must stay identical.
        """
        summaries = (
            _summary(
                trial_id="A",
                held_qty=Decimal(1),
                verdict_at_signal="EXIT_RECOMMENDED",
                recoverable_value_at_signal=Decimal("0.30"),
            ),
        )
        scored = (_trial(trial_id="A", held=False, pnl=Decimal("-0.50")),)

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.avoided_loss.total == Decimal("0.80")


class TestRealizedVsMarkDelta:
    """HIGH review fix: `_mark_implied_pnl` is TOTAL-POSITION dollars
    (`recoverable_value_at_signal - fill_px * held_qty`) but `settled_pnl`
    is PER-CONTRACT -- see `TestAvoidedLoss`'s unit-fix tests for the same
    mismatch on the sibling statistic.
    """

    def test_delta_scales_settled_pnl_by_held_qty_to_match_the_marks_total_dollar_units(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(
                trial_id="A",
                held_qty=Decimal(2),
                fill_px=Decimal("0.40"),
                recoverable_value_at_signal=Decimal("0.50"),
            ),
        )
        scored = (_trial(trial_id="A", held=False, pnl=Decimal("-0.41")),)

        report = report_mod.build_monitor_report(summaries, scored)

        # implied = recoverable_value_at_signal - (fill_px * held_qty)
        #         = 0.50 - (0.40 * 2) = -0.30
        # delta   = (settled_pnl * held_qty) - implied
        #         = (-0.41 * 2) - (-0.30) = -0.52
        assert report.realized_vs_mark_delta.n == 1
        assert report.realized_vs_mark_delta.min == Decimal("-0.52")
        assert report.realized_vs_mark_delta.median == Decimal("-0.52")
        assert report.realized_vs_mark_delta.max == Decimal("-0.52")

    def test_delta_at_held_qty_one_is_unchanged_by_the_unit_fix(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(
                trial_id="A",
                held_qty=Decimal(1),
                fill_px=Decimal("0.40"),
                recoverable_value_at_signal=Decimal("0.55"),
            ),
        )
        scored = (_trial(trial_id="A", held=False, pnl=Decimal("-0.10")),)

        report = report_mod.build_monitor_report(summaries, scored)

        # implied = 0.55 - (0.40 * 1) = 0.15; delta = (-0.10 * 1) - 0.15 = -0.25
        assert report.realized_vs_mark_delta.min == Decimal("-0.25")


class TestOneSidedBookRate:
    def test_rate_is_missing_frames_over_total_frames_summed_across_positions(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", total_frames=10, mark_missing_frames=2),
            _summary(trial_id="B", total_frames=20, mark_missing_frames=3),
        )

        report = report_mod.build_monitor_report(summaries, ())

        assert report.one_sided_book.total_frames == 30
        assert report.one_sided_book.mark_missing_frames == 5
        assert report.one_sided_book.rate == pytest.approx(5 / 30)

    def test_zero_total_frames_returns_none_rate_not_a_division_error(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (_summary(trial_id="A", total_frames=0, mark_missing_frames=0),)

        report = report_mod.build_monitor_report(summaries, ())

        assert report.one_sided_book.rate is None


class TestExitTimingAndMaeMfe:
    def test_exit_timing_histogram_counts_by_hour_and_skips_none(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", first_signal_hour_lst=14),
            _summary(trial_id="B", first_signal_hour_lst=14),
            _summary(trial_id="C", first_signal_hour_lst=16),
            _summary(trial_id="D", first_signal_hour_lst=None),
        )

        report = report_mod.build_monitor_report(summaries, ())

        assert dict(report.exit_timing_histogram) == {14: 2, 16: 1}

    def test_mae_mfe_summary_reports_min_median_max_as_decimal(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", mae=Decimal("0.05"), mfe=Decimal("0.10")),
            _summary(trial_id="B", mae=Decimal("0.15"), mfe=Decimal("0.30")),
            _summary(trial_id="C", mae=Decimal("0.10"), mfe=Decimal("0.20")),
        )

        report = report_mod.build_monitor_report(summaries, ())

        assert report.mae_summary.min == Decimal("0.05")
        assert report.mae_summary.median == Decimal("0.10")
        assert report.mae_summary.max == Decimal("0.15")
        assert report.mfe_summary.min == Decimal("0.10")
        assert report.mfe_summary.median == Decimal("0.20")
        assert report.mfe_summary.max == Decimal("0.30")


class TestNGate:
    def test_below_n_min_is_labelled_insufficient_n_with_no_values(
        self, report_mod: ModuleType
    ) -> None:
        summaries = tuple(_summary(trial_id=f"T{i}") for i in range(3))
        scored = tuple(
            _trial(trial_id=f"T{i}", held=(i % 2 == 0), pnl=Decimal("0.10"))
            for i in range(3)
        )

        report = report_mod.build_monitor_report(summaries, scored, n_min=90)

        assert report.n_gated.label == "INSUFFICIENT_N"
        assert report.n_gated.observed_n == 3
        assert report.n_gated.expectancy is None
        assert report.n_gated.profit_factor is None
        assert report.n_gated.max_drawdown is None
        assert report.n_gated.win_rate is None

    def test_at_or_above_n_min_computes_real_values_via_native_statistics(
        self, report_mod: ModuleType
    ) -> None:
        n = 90
        summaries = []
        scored = []
        for i in range(n):
            trial_id = f"T{i:04d}"
            is_win = i % 3 != 0  # 60 wins, 30 losses
            pnl = Decimal("0.10") if is_win else Decimal("-0.20")
            summaries.append(_summary(trial_id=trial_id, climate_day=f"2026-09-{i:04d}"))
            scored.append(
                _trial(
                    trial_id=trial_id,
                    climate_day=f"2026-09-{i:04d}",
                    held=is_win,
                    pnl=pnl,
                )
            )

        report = report_mod.build_monitor_report(tuple(summaries), tuple(scored), n_min=90)

        assert report.n_gated.label == "COMPUTED"
        assert report.n_gated.observed_n == 90
        assert report.n_gated.win_rate == pytest.approx(60 / 90)
        assert report.n_gated.expectancy == pytest.approx(0.0, abs=1e-9)
        assert report.n_gated.profit_factor == pytest.approx(1.0)
        assert report.n_gated.max_drawdown is not None
        assert report.n_gated.max_drawdown >= 0.0


class TestCalibration:
    def test_defaults_to_uncalibrated_pending_inc_8(self, report_mod: ModuleType) -> None:
        report = report_mod.build_monitor_report((), ())

        assert report.calibration.constants_calibrated is False
        assert "INC-8" in report.calibration.reason

    def test_below_the_usable_station_day_floor_stays_uncalibrated(
        self, report_mod: ModuleType
    ) -> None:
        report = report_mod.build_monitor_report((), (), usable_station_days=5)

        assert report.calibration.constants_calibrated is False
        assert report.calibration.usable_station_days == 5

    def test_at_or_above_the_floor_is_calibrated(self, report_mod: ModuleType) -> None:
        report = report_mod.build_monitor_report((), (), usable_station_days=30)

        assert report.calibration.constants_calibrated is True


class TestExitRuleSeries:
    """INC-E5 (`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` Sec 1/3):
    realized pnl, avoided loss and premature-exit rate, keyed per exit
    rule, plus the `SETTLED` hold-control -- DESCRIPTIVE only (never an
    LD-OBF/tally input). Every number below is hand-computed: the fee
    coefficient is `CurrentRungHoldConfig().required_fee_coefficient`
    (`Decimal("0.06")`), and `0.06 * price * (1 - price)` is quantized to
    the cent with banker's rounding (`decision.py`'s `_fee`, reused via
    `monitor_evidence.exit_fee`) -- see each row's own comment.
    """

    def _fired_summary(self, **overrides: object) -> PositionMonitorSummary:
        base: dict[str, object] = {
            "exit_decision": "fired",
            "exit_reason_code": "fired",
            "fill_px": Decimal("0.50"),
        }
        base.update(overrides)
        return _summary(**base)

    def test_two_r_threat_one_r_dead_two_settled_series_match_hand_computed_arithmetic(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            # R_THREAT #1: PREMATURE -- settlement says the entry thesis
            # would have held (settled_held=True). exit_fee =
            # 0.06*0.60*0.40 = 0.0144 -> 0.01 (banker's rounding).
            # realized = 0.60 - 0.01 - 0.50 - 0.02 = 0.07.
            # avoided  = 0.07 - 0.48 (would-have-held) = -0.41.
            self._fired_summary(
                trial_id="RT1", exit_rule="R_THREAT", exit_limit_price=Decimal("0.60")
            ),
            # R_THREAT #2: AVOIDED LOSS -- settlement says the thesis died
            # (settled_held=False). exit_fee = 0.06*0.30*0.70 = 0.0126 ->
            # 0.01. realized = 0.30 - 0.01 - 0.50 - 0.02 = -0.23.
            # avoided = -0.23 - (-0.52) = 0.29.
            self._fired_summary(
                trial_id="RT2", exit_rule="R_THREAT", exit_limit_price=Decimal("0.30")
            ),
            # R_DEAD: exit_fee = 0.06*0.10*0.90 = 0.0054 -> 0.01.
            # realized = 0.10 - 0.01 - 0.50 - 0.02 = -0.43.
            # avoided = -0.43 - (-0.52) = 0.09.
            self._fired_summary(
                trial_id="RD1", exit_rule="R_DEAD", exit_limit_price=Decimal("0.10")
            ),
            # SETTLED (never exited -- backward-compat default exit_rule=None).
            _summary(trial_id="S1"),
            _summary(trial_id="S2"),
        )
        scored = (
            _trial(
                trial_id="RT1", held=True, pnl=Decimal("0.48"),
                fill_px=Decimal("0.50"), fee=Decimal("0.02"),
            ),
            _trial(
                trial_id="RT2", held=False, pnl=Decimal("-0.52"),
                fill_px=Decimal("0.50"), fee=Decimal("0.02"),
            ),
            _trial(
                trial_id="RD1", held=False, pnl=Decimal("-0.52"),
                fill_px=Decimal("0.50"), fee=Decimal("0.02"),
            ),
            _trial(trial_id="S1", held=True, pnl=Decimal("0.44")),
            _trial(trial_id="S2", held=False, pnl=Decimal("-0.56")),
        )

        report = report_mod.build_monitor_report(summaries, scored)
        series = report.exit_rule_series

        r_threat = series["R_THREAT"]
        assert r_threat.n == 2
        assert r_threat.n_excluded_missing_price_or_fee == 0
        assert r_threat.realized_pnl_total == Decimal("-0.16")
        assert r_threat.avoided_loss_total == Decimal("-0.12")
        assert r_threat.premature_exit_rate.k == 1
        assert r_threat.premature_exit_rate.n == 2

        r_dead = series["R_DEAD"]
        assert r_dead.n == 1
        assert r_dead.n_excluded_missing_price_or_fee == 0
        assert r_dead.realized_pnl_total == Decimal("-0.43")
        assert r_dead.avoided_loss_total == Decimal("0.09")
        assert r_dead.premature_exit_rate.k == 0
        assert r_dead.premature_exit_rate.n == 1

        settled = series["SETTLED"]
        assert settled.n == 2
        assert settled.realized_pnl_total == Decimal("-0.12")
        assert settled.avoided_loss_total == Decimal(0)
        assert settled.premature_exit_rate.n == 0
        assert settled.premature_exit_rate.point is None

    def test_old_summary_rows_without_exit_fields_still_render_as_settled(
        self, report_mod: ModuleType
    ) -> None:
        """Backward compat: a pre-INC-E3 summary defaults `exit_rule` to
        `None` -- it must still render, joined into `SETTLED`, never raise
        and never silently vanish from every group's count."""
        summaries = (_summary(trial_id="OLD1"),)
        scored = (_trial(trial_id="OLD1", held=True, pnl=Decimal("0.20")),)

        report = report_mod.build_monitor_report(summaries, scored)

        assert report.exit_rule_series["SETTLED"].n == 1
        assert report.exit_rule_series["R_THREAT"].n == 0
        assert report.exit_rule_series["R_DEAD"].n == 0

    def test_default_manifest_reports_armed_false_for_pm_us_crh_cont(
        self, report_mod: ModuleType
    ) -> None:
        report = report_mod.build_monitor_report((), ())

        for rule in ("R_THREAT", "R_DEAD", "SETTLED"):
            rule_series = report.exit_rule_series[rule]
            assert rule_series.armed is False
            assert rule_series.family == "pm_us_crh_cont"

    def test_markdown_renders_the_armed_line_false_for_pm_us_crh_cont(
        self, report_mod: ModuleType
    ) -> None:
        report = report_mod.build_monitor_report((), ())
        markdown = report_mod._render_markdown(report)

        assert "R_THREAT: ARMED: False family: pm_us_crh_cont" in markdown
        assert "R_DEAD: ARMED: False family: pm_us_crh_cont" in markdown
        assert "SETTLED: ARMED: False family: pm_us_crh_cont" in markdown

    def test_a_code_registered_manifest_declaring_exit_rule_arms_the_exit_rules_only(
        self, report_mod: ModuleType
    ) -> None:
        manifest = FamilyManifest(
            family_id="pm_us_crh_exit_v4",
            venue="polymarket_us",
            trial_id_prefix="current_rung_hold_exit_v4/trial/",
            d0_climate_day="2099-01-01",
            boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
            boundary_inputs_sha256="a" * 64,
            stations=("SFO",),
            status="REGISTERED",
            manifest_sha256="c" * 64,
            exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP",
        )

        report = report_mod.build_monitor_report((), (), family_manifest=manifest)

        assert report.exit_rule_series["R_THREAT"].armed is True
        assert report.exit_rule_series["R_DEAD"].armed is True
        assert report.exit_rule_series["R_THREAT"].family == "pm_us_crh_exit_v4"
        # SETTLED never "arms" -- it names the absence of an exit, not a rule.
        assert report.exit_rule_series["SETTLED"].armed is False

    def test_a_manifest_that_never_declares_exit_rule_stays_unarmed(
        self, report_mod: ModuleType
    ) -> None:
        manifest = FamilyManifest(
            family_id="pm_us_crh_cont",
            venue="polymarket_us",
            trial_id_prefix="continuous_rung_hold/trial/",
            d0_climate_day="2026-09-12",
            boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
            boundary_inputs_sha256="a" * 64,
            stations=("LAX", "MDW", "MIA", "SFO"),
            status="REGISTERED",
            manifest_sha256="d" * 64,
            exit_rule=None,
        )

        report = report_mod.build_monitor_report((), (), family_manifest=manifest)

        assert report.exit_rule_series["R_THREAT"].armed is False
        assert report.exit_rule_series["R_DEAD"].armed is False

    def test_to_dict_serializes_exit_rule_series_with_decimal_as_str(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            self._fired_summary(
                trial_id="RT1", exit_rule="R_THREAT", exit_limit_price=Decimal("0.60")
            ),
        )
        scored = (
            _trial(
                trial_id="RT1", held=True, pnl=Decimal("0.48"),
                fill_px=Decimal("0.50"), fee=Decimal("0.02"),
            ),
        )

        report = report_mod.build_monitor_report(summaries, scored)
        payload = report.to_dict()

        r_threat_payload = payload["exit_rule_series"]["R_THREAT"]
        assert isinstance(r_threat_payload["realized_pnl_total"], str)
        assert isinstance(r_threat_payload["avoided_loss_total"], str)
        assert r_threat_payload["armed"] is False
        assert r_threat_payload["family"] == "pm_us_crh_cont"

    def test_missing_entry_fee_join_excludes_the_row_from_pricing_but_counts_it(
        self, report_mod: ModuleType
    ) -> None:
        """A fired exit whose settlement resolved from the summary's own
        `settled_*` fields (INC-8 hypothetical corpus, no `ScoredTrial`,
        never a discrete entry fee) is excluded from `realized_pnl_total`/
        `avoided_loss_total` -- counted, never guessed -- but still counts
        toward `n` and the premature-exit rate, which need only
        `settled_held`.
        """
        summaries = (
            self._fired_summary(
                trial_id="hypo:SFO:2026-09-01:0",
                entry_context="hypothetical",
                exit_rule="R_THREAT",
                exit_limit_price=Decimal("0.60"),
                settled_held=True,
                settled_pnl=Decimal("0.48"),
            ),
        )

        report = report_mod.build_monitor_report(summaries, ())
        r_threat = report.exit_rule_series["R_THREAT"]

        assert r_threat.n == 1
        assert r_threat.n_excluded_missing_price_or_fee == 1
        assert r_threat.realized_pnl_total == Decimal(0)
        assert r_threat.avoided_loss_total == Decimal(0)
        assert r_threat.premature_exit_rate.k == 1
        assert r_threat.premature_exit_rate.n == 1


class TestDecimalPurity:
    def test_avoided_loss_and_mae_mfe_stay_decimal_internally_and_str_in_to_dict(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(
                trial_id="A",
                verdict_at_signal="EXIT_RECOMMENDED",
                recoverable_value_at_signal=Decimal("0.30"),
                mae=Decimal("0.10"),
                mfe=Decimal("0.20"),
            ),
        )
        scored = (_trial(trial_id="A", held=False, pnl=Decimal("-0.50")),)

        report = report_mod.build_monitor_report(summaries, scored)

        assert isinstance(report.avoided_loss.total, Decimal)
        assert isinstance(report.mae_summary.min, Decimal)
        assert isinstance(report.mfe_summary.max, Decimal)

        payload = report.to_dict()
        assert isinstance(payload["avoided_loss"]["total"], str)
        assert isinstance(payload["mae_summary"]["min"], str)
        assert isinstance(payload["mfe_summary"]["max"], str)

    def test_to_dict_serializes_settlement_source_counts_and_contingency_by_context(
        self, report_mod: ModuleType
    ) -> None:
        summaries = (
            _summary(trial_id="A", entry_context="live", verdict_at_signal="HOLD"),
            _summary(
                trial_id="hypo:SFO:2026-09-01:0",
                entry_context="hypothetical",
                verdict_at_signal="EXIT_RECOMMENDED",
                settled_held=False,
                settled_pnl=Decimal("-0.10"),
            ),
        )
        scored = (_trial(trial_id="A", held=True),)

        report = report_mod.build_monitor_report(summaries, scored)
        payload = report.to_dict()

        assert payload["settled_from_scored_trials"] == 1
        assert payload["settled_from_summary"] == 1
        assert set(payload["contingency_table_by_entry_context"]) == {
            "live",
            "hypothetical",
        }
        assert payload["contingency_table_by_entry_context"]["hypothetical"][0][
            "verdict"
        ]


class TestIsolation:
    def test_the_script_never_imports_the_banned_v2_or_tally_modules(self) -> None:
        source = _SCRIPT_PATH.read_text()
        tree = ast.parse(source, filename=str(_SCRIPT_PATH))
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_names.add(node.module)

        for banned in ("live_family_tally", "current_rung_hold_v2"):
            assert not any(banned in name for name in imported_names), (
                f"{_SCRIPT_PATH.name} must never import {banned!r}: found in {imported_names!r}"
            )


class TestCli:
    def test_writes_only_out_and_markdown_and_never_mutates_input_directories(
        self, tmp_path: Path, report_mod: ModuleType
    ) -> None:
        from breezy.persistence.scored_trial_store import write_scored_trials
        from breezy.strategy.current_rung_hold.monitor_store import write_monitor_summaries

        summaries_dir = tmp_path / "summaries"
        scored_dir = tmp_path / "scored"
        out_path = tmp_path / "out" / "report.json"
        markdown_path = tmp_path / "out" / "report.md"

        write_monitor_summaries(summaries_dir, [_summary(trial_id="A")], now_ns=1_000_000_000)
        write_scored_trials(
            scored_dir, [_trial(trial_id="A", held=True)], now_ns=1_000_000_000
        )
        summaries_before = sorted(p.name for p in summaries_dir.glob("*"))
        scored_before = sorted(p.name for p in scored_dir.glob("*"))

        exit_code = report_mod.main(
            [
                "--summaries-dir",
                str(summaries_dir),
                "--scored-trials-dir",
                str(scored_dir),
                "--out",
                str(out_path),
                "--markdown",
                str(markdown_path),
            ]
        )

        assert exit_code == 0
        assert out_path.exists()
        assert markdown_path.exists()
        payload = json.loads(out_path.read_text())
        assert payload["total_positions"] == 1
        assert sorted(p.name for p in summaries_dir.glob("*")) == summaries_before
        assert sorted(p.name for p in scored_dir.glob("*")) == scored_before
