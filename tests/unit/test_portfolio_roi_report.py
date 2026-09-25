"""RED-first tests for AUD-04 stages C1a and C1b: loaders, fill bucketing,
per-leg realised P&L, capital deployed, the balance-series parser (C1a), and
the cash-identity reconciliation, settlement-date proxy classification,
settled-through cutoff, permanently-unsettled detection and ROI-vs-baselines
(C1b).

Scope note: this is stages C1a-C1b of
``docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md``
-- section 7 steps 1-2 only. The JSON schema/reader, the Markdown report
header assembly, the D8 freshness detector, the D9 alert emission and
ROI-gating reader, the fill->trial_id join via
``score_live_trials.read_filled_trials_state_db``, and the CLI are later
stages and are NOT tested here.

All hermetic: `tmp_path` sqlite stores and in-memory string fixtures only --
never the real `~/.local/share`.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.persistence.residual_fills import EXCLUDED_FILLS_FILENAME
from breezy.persistence.scored_trial_store import write_scored_trials
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.settlement.trial_scorer import FilledTrial, ScoredTrial, SettlementBasis

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_module() -> ModuleType:
    path = _SCRIPTS_ANALYSIS_DIR / "portfolio_roi_report.py"
    spec = importlib.util.spec_from_file_location("portfolio_roi_report", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_prr = _load_module()

FEE_RECONCILED_LABEL = _prr.FEE_RECONCILED_LABEL
FEE_UNRECONCILED_LABEL = _prr.FEE_UNRECONCILED_LABEL
AttributedFill = _prr.AttributedFill
BalancePoint = _prr.BalancePoint
FillBucket = _prr.FillBucket
admissible_scored_trials = _prr.admissible_scored_trials
bucket_ledger_fills = _prr.bucket_ledger_fills
capital_deployed_for_fill = _prr.capital_deployed_for_fill
daily_balance_series = _prr.daily_balance_series
fee_reconciliation_label = _prr.fee_reconciliation_label
leg_of_fill = _prr.leg_of_fill
parse_account_state_line = _prr.parse_account_state_line
read_ledger_fills = _prr.read_ledger_fills
total_capital_deployed = _prr.total_capital_deployed
total_realised_pnl_admissible = _prr.total_realised_pnl_admissible
total_realised_pnl_all_settled = _prr.total_realised_pnl_all_settled

# -- C1b additions --
MIN_LAG_SAMPLE_N = _prr.MIN_LAG_SAMPLE_N
PROCEEDS_DATE_PROXY_LABEL = _prr.PROCEEDS_DATE_PROXY_LABEL
UNEXPLAINED_OK_LABEL = _prr.UNEXPLAINED_OK_LABEL
UNEXPLAINED_CAPITAL_FLOW_LABEL = _prr.UNEXPLAINED_CAPITAL_FLOW_LABEL
UNEXPLAINED_PROXY_LAG_LABEL = _prr.UNEXPLAINED_PROXY_LAG_LABEL
BASELINE_B0_CASH = _prr.BASELINE_B0_CASH
settlement_payout = _prr.settlement_payout
proceeds_date = _prr.proceeds_date
settlement_lag_days = _prr.settlement_lag_days
per_day_tolerance = _prr.per_day_tolerance
reconcile_daily = _prr.reconcile_daily
compute_settled_through = _prr.compute_settled_through
settled_through_statistic_label = _prr.settled_through_statistic_label
apply_settled_through = _prr.apply_settled_through
cumulative_reconciliation = _prr.cumulative_reconciliation
permanently_unsettled_trials = _prr.permanently_unsettled_trials
max_settlement_horizon_ns = _prr.max_settlement_horizon_ns
roi = _prr.roi
baseline_b1_fee_drag = _prr.baseline_b1_fee_drag
roi_against_baselines = _prr.roi_against_baselines

# -- C2 additions --
PORTFOLIO_ROI_SCHEMA_VERSION = _prr.PORTFOLIO_ROI_SCHEMA_VERSION
ROI_STATUS_OK = _prr.ROI_STATUS_OK
ROI_STATUS_GATED_UNSETTLED_CAPITAL = _prr.ROI_STATUS_GATED_UNSETTLED_CAPITAL
UnknownPortfolioRoiSchemaError = _prr.UnknownPortfolioRoiSchemaError
UnsettledCapitalRoiError = _prr.UnsettledCapitalRoiError
PortfolioRoiReportData = _prr.PortfolioRoiReportData
build_portfolio_roi_report_data = _prr.build_portfolio_roi_report_data
write_portfolio_roi_json = _prr.write_portfolio_roi_json
read_portfolio_roi_report = _prr.read_portfolio_roi_report
render_markdown_report = _prr.render_markdown_report
journal_line = _prr.journal_line
FROZEN_INPUTS_EVENT = _prr.FROZEN_INPUTS_EVENT
FROZEN_INPUTS_CLEARED_EVENT = _prr.FROZEN_INPUTS_CLEARED_EVENT
PERMANENTLY_UNSETTLED_EVENT = _prr.PERMANENTLY_UNSETTLED_EVENT
is_input_fresh = _prr.is_input_fresh
days_since_newest_input = _prr.days_since_newest_input
apply_freshness_ladder = _prr.apply_freshness_ladder
apply_unsettled_positions_ladder = _prr.apply_unsettled_positions_ladder

# -- defect-fix additions (AUD-04 C2 defect fix) --
residual_trial_ids_pooled = _prr.residual_trial_ids_pooled
read_scored_trials_pooled = _prr.read_scored_trials_pooled
attribute_fills_via_family_manifests = _prr.attribute_fills_via_family_manifests
FamilyManifestAttribution = _prr.FamilyManifestAttribution
_run = _prr._run

# -- REVIEW-FIX additions (F1-F9) --
LedgerReadResult = _prr.LedgerReadResult
read_ledger_fills_with_counts = _prr.read_ledger_fills_with_counts
assert_ledger_partition = _prr.assert_ledger_partition
LedgerPartitionViolationError = _prr.LedgerPartitionViolationError
DuplicateScoredTrialEconomicsMismatchError = _prr.DuplicateScoredTrialEconomicsMismatchError
BALANCE_UNKNOWN_LABEL = _prr.BALANCE_UNKNOWN_LABEL
fill_side_label = _prr.fill_side_label
UnknownOrderSideError = _prr.UnknownOrderSideError
UNRECONCILED_EXIT_LABEL = _prr.UNRECONCILED_EXIT_LABEL
PortfolioRoiReportMalformedFieldError = _prr.PortfolioRoiReportMalformedFieldError
CumulativeReconciliation = _prr.CumulativeReconciliation
power_caveat = _prr.power_caveat

# -- G1-G4 final-fix-stage additions --
NO_PRIOR_BALANCE_LABEL = _prr.NO_PRIOR_BALANCE_LABEL
OPENING_BALANCE_LOOKBACK_DAYS = _prr.OPENING_BALANCE_LOOKBACK_DAYS
_latest_balance_before = _prr._latest_balance_before
DailyUnexplainedSummaryRow = _prr.DailyUnexplainedSummaryRow

# -- Stage C3 additions (per-trial P&L breakdown) --
PortfolioRoiTrialRow = _prr.PortfolioRoiTrialRow
trial_rows_of = _prr.trial_rows_of
scored_trial_family_ids = _prr.scored_trial_family_ids
leg_of_scored_trial = _prr.leg_of_scored_trial
UNKNOWN_TRIAL_FAMILY_LABEL = _prr.UNKNOWN_TRIAL_FAMILY_LABEL

from breezy.runtime import alert_ladder as _ladder

alert_ladder = _ladder

_FRESH_LATCH = _ladder.LatchState(
    schema_version=_ladder.LATCH_SCHEMA_VERSION,
    streak=0,
    last_alert_severity=None,
    last_alert_period_key=None,
)


def _ns_of(day: str, hour: int = 0) -> int:
    dt = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000) + hour * 3_600_000_000_000


def _report_data(
    *,
    unsettled_capital_positions: int = 0,
    max_days_past_horizon: int = 0,
    n_fills: int = 6,
    n_scored: int = 4,
    n_residual: int = 2,
    n_unreconciled: int = 0,
    n_unexplained_capital_flow_days: int = 0,
    n_unexplained_proxy_lag_days: int = 0,
) -> Any:
    # Return type is `Any`, not `PortfolioRoiReportData`: that class object is
    # loaded dynamically via `_load_module()` (module docstring above), which
    # mypy cannot resolve as a static type -- the same constraint every other
    # dynamically-loaded class in this file (e.g. `AttributedFill`,
    # `BalancePoint`) is never used as an annotation for.
    return PortfolioRoiReportData(
        period_start="2026-01-01",
        period_end="2026-01-10",
        n_fills=n_fills,
        n_scored=n_scored,
        n_residual=n_residual,
        n_unreconciled=n_unreconciled,
        power_caveat="n=6 settled fills over 10 days; NOT a statistically "
        "powered estimate of improvement over B0 or B1 at this sample size.",
        realised_pnl_after_fees_total=Decimal("0.57"),
        capital_deployed_total=Decimal("2.15"),
        roi=Decimal("0.265"),
        roi_minus_b0=Decimal("0.265"),
        roi_minus_b1=Decimal("0.34"),
        unexplained_flow_days=0,
        settled_through="2026-01-08",
        settled_through_statistic="max",
        lag_sample_n=4,
        roi_status=(
            ROI_STATUS_GATED_UNSETTLED_CAPITAL
            if unsettled_capital_positions > 0
            else ROI_STATUS_OK
        ),
        unsettled_capital_positions=unsettled_capital_positions,
        max_days_past_horizon=max_days_past_horizon,
        n_unexplained_capital_flow_days=n_unexplained_capital_flow_days,
        n_unexplained_proxy_lag_days=n_unexplained_proxy_lag_days,
    )


class TestJsonSchemaVersion:
    def test_the_json_sibling_carries_a_schema_version(self, tmp_path: Path) -> None:
        data = _report_data()
        path = tmp_path / "report.json"

        write_portfolio_roi_json(path, data)

        raw = json.loads(path.read_text())
        # Stage C3 bumps this to 2 (the per-trial `trial_rows` breakdown).
        assert raw["schema_version"] == PORTFOLIO_ROI_SCHEMA_VERSION == 2
        # D6: the JSON is PRIVATE, mode 0600.
        assert (path.stat().st_mode & 0o777) == 0o600

        view = read_portfolio_roi_report(path)
        assert view.schema_version == PORTFOLIO_ROI_SCHEMA_VERSION
        assert view.roi == data.roi
        assert view.n_fills == data.n_fills

    def test_a_reader_refuses_an_unknown_schema_version(self, tmp_path: Path) -> None:
        path = tmp_path / "report.json"
        payload = json.loads(json.dumps({"schema_version": 999}))
        path.write_text(json.dumps(payload))

        with pytest.raises(UnknownPortfolioRoiSchemaError):
            read_portfolio_roi_report(path)

    def test_a_position_that_opens_and_never_settles_gates_the_roi_reader(
        self, tmp_path: Path
    ) -> None:
        """§6 D9 (d): `roi_status == "GATED_UNSETTLED_CAPITAL"` and the D7
        reader raises `UnsettledCapitalRoiError` on `roi`/`roi_minus_b0`/
        `roi_minus_b1` -- while every non-ROI field (including
        `capital_deployed_total`, the denominator) stays readable."""
        gated_data = _report_data(unsettled_capital_positions=1, max_days_past_horizon=10)
        path = tmp_path / "gated.json"
        write_portfolio_roi_json(path, gated_data)

        view = read_portfolio_roi_report(path)
        assert view.roi_status == ROI_STATUS_GATED_UNSETTLED_CAPITAL
        assert view.unsettled_capital_positions == 1
        # Non-ROI fields are never gated.
        assert view.capital_deployed_total == gated_data.capital_deployed_total
        assert view.n_fills == gated_data.n_fills

        with pytest.raises(UnsettledCapitalRoiError):
            _ = view.roi
        with pytest.raises(UnsettledCapitalRoiError):
            _ = view.roi_minus_b0
        with pytest.raises(UnsettledCapitalRoiError):
            _ = view.roi_minus_b1

        # Negative half: an ungated report never raises.
        ok_data = _report_data(unsettled_capital_positions=0)
        ok_path = tmp_path / "ok.json"
        write_portfolio_roi_json(ok_path, ok_data)
        ok_view = read_portfolio_roi_report(ok_path)
        assert ok_view.roi_status == ROI_STATUS_OK
        assert ok_view.roi == ok_data.roi


class TestPerTrialPnlBreakdown:
    """Stage C3: the per-trial P&L breakdown (`trial_rows`) an AUD-07-style
    consumer joins on `trial_id`, so an equal-and-opposite per-trial error
    can never cancel invisibly inside a report-level total."""

    def test_trial_rows_of_sums_exactly_to_the_total_and_is_sorted_by_trial_id(
        self,
    ) -> None:
        trial_b = _scored_trial(
            trial_id="fam_b/trial/LAX/2026-01-02", pnl=Decimal("0.30"), climate_day="2026-01-02"
        )
        trial_a = _scored_trial(
            trial_id="fam_a/trial/LAX/2026-01-01", pnl=Decimal("0.27"), climate_day="2026-01-01"
        )
        family_ids = {
            "fam_a/trial/LAX/2026-01-01": "fam_a",
            "fam_b/trial/LAX/2026-01-02": "fam_b",
        }

        # Given out of order -- the output must still be sorted.
        rows = trial_rows_of((trial_b, trial_a), family_ids_by_trial_id=family_ids)

        assert [row.trial_id for row in rows] == [
            "fam_a/trial/LAX/2026-01-01",
            "fam_b/trial/LAX/2026-01-02",
        ]
        assert sum((row.pnl for row in rows), start=Decimal(0)) == total_realised_pnl_all_settled(
            (trial_a, trial_b)
        )
        assert rows[0].family_id == "fam_a"
        assert rows[0].climate_day == "2026-01-01"
        assert rows[0].side == "yes"
        assert rows[0].settlement_basis == "nws_final"

    def test_trial_rows_of_uses_the_unknown_label_when_the_family_map_has_no_entry(
        self,
    ) -> None:
        trial = _scored_trial(trial_id="fam_x/trial/LAX/2026-01-03", pnl=Decimal("0.05"))

        rows = trial_rows_of((trial,), family_ids_by_trial_id={})

        assert rows[0].family_id == UNKNOWN_TRIAL_FAMILY_LABEL

    def test_leg_of_scored_trial_identifies_the_no_leg_via_the_composite_symbol(
        self,
    ) -> None:
        yes_trial = _scored_trial(trial_id="t-yes", pnl=Decimal("0.01"))
        no_trial = dataclasses.replace(
            _scored_trial(trial_id="t-no", pnl=Decimal("0.01")),
            instrument_id="LAX-92-94^no.POLYMARKET_US",
        )

        assert leg_of_scored_trial(yes_trial) == "yes"
        assert leg_of_scored_trial(no_trial) == "no"

    def test_scored_trial_family_ids_maps_trial_id_to_its_store_subdirectory(
        self, tmp_path: Path
    ) -> None:
        scored_trials_dir = tmp_path / "scored_trials"
        trial_a = _scored_trial(trial_id="fam_a/trial/LAX/2026-01-01", pnl=Decimal("0.10"))
        trial_b = _scored_trial(trial_id="fam_b/trial/LAX/2026-01-02", pnl=Decimal("0.20"))
        write_scored_trials(scored_trials_dir / "fam_a", [trial_a], now_ns=1)
        write_scored_trials(scored_trials_dir / "fam_b", [trial_b], now_ns=2)

        family_ids = scored_trial_family_ids(scored_trials_dir)

        assert family_ids == {
            "fam_a/trial/LAX/2026-01-01": "fam_a",
            "fam_b/trial/LAX/2026-01-02": "fam_b",
        }

    def test_scored_trial_family_ids_returns_empty_for_an_absent_directory(
        self, tmp_path: Path
    ) -> None:
        assert scored_trial_family_ids(tmp_path / "does_not_exist") == {}

    def test_the_json_sibling_carries_trial_rows_summing_to_the_total(
        self, tmp_path: Path
    ) -> None:
        row_a = PortfolioRoiTrialRow(
            trial_id="fam_a/trial/1",
            family_id="fam_a",
            climate_day="2026-01-01",
            side="no",
            pnl=Decimal("0.27"),
            settlement_basis="venue_last_fair_price_fallback",
        )
        row_b = PortfolioRoiTrialRow(
            trial_id="fam_b/trial/1",
            family_id="fam_b",
            climate_day="2026-01-02",
            side="yes",
            pnl=Decimal("0.30"),
            settlement_basis="nws_final",
        )
        data = dataclasses.replace(_report_data(), trial_rows=(row_a, row_b))
        # Sanity: `_report_data()`'s default total is exactly 0.27 + 0.30.
        assert (
            sum((row.pnl for row in data.trial_rows), start=Decimal(0))
            == data.realised_pnl_after_fees_total
        )

        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())

        assert raw["schema_version"] == PORTFOLIO_ROI_SCHEMA_VERSION == 2
        assert raw["trial_rows"] == [
            {
                "trial_id": "fam_a/trial/1",
                "family_id": "fam_a",
                "climate_day": "2026-01-01",
                "side": "no",
                "pnl": "0.27",
                "settlement_basis": "venue_last_fair_price_fallback",
            },
            {
                "trial_id": "fam_b/trial/1",
                "family_id": "fam_b",
                "climate_day": "2026-01-02",
                "side": "yes",
                "pnl": "0.30",
                "settlement_basis": "nws_final",
            },
        ]

        view = read_portfolio_roi_report(path)
        assert view.trial_rows == (row_a, row_b)
        assert (
            sum((row.pnl for row in view.trial_rows), start=Decimal(0))
            == view.realised_pnl_after_fees_total
        )

    def test_an_old_schema_version_one_report_surfaces_trial_rows_as_none(
        self, tmp_path: Path
    ) -> None:
        """A pre-existing report predates this field entirely (it predates
        schema_version=2 itself) -- `None` (unknown), never `()` (which
        would misreport a genuinely empty, but KNOWN, trial set)."""
        data = _report_data()
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        raw["schema_version"] = 1
        del raw["trial_rows"]
        path.write_text(json.dumps(raw))

        view = read_portfolio_roi_report(path)

        assert view.schema_version == 1
        assert view.trial_rows is None
        # Every other field is still fully readable at the old version.
        assert view.n_fills == data.n_fills
        assert view.roi == data.roi

    def test_a_schema_version_two_report_missing_trial_rows_is_malformed(
        self, tmp_path: Path
    ) -> None:
        data = _report_data()
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        del raw["trial_rows"]
        path.write_text(json.dumps(raw))

        with pytest.raises(PortfolioRoiReportMalformedFieldError):
            read_portfolio_roi_report(path)


class TestReportHeader:
    def test_the_report_header_states_the_sample_size_and_its_power_caveat(self) -> None:
        data = _report_data()
        report = render_markdown_report(data)

        assert (
            "n=6 settled fills over 10 days; NOT a statistically powered "
            "estimate of improvement over B0 or B1 at this sample size."
        ) in report
        assert "settled_through_statistic=max lag_sample_n=4" in report or (
            "settled_through_statistic=max" in report and "lag_sample_n=4" in report
        )


class TestJournalLineNoCurrency:
    def test_the_journal_line_carries_no_currency_denominated_field(self) -> None:
        data = _report_data()
        line = journal_line(data)

        assert "$" not in line
        # No Decimal-shaped currency figure (e.g. "0.57") anywhere in the
        # line -- every field is an integer count, a date, or an enum label.
        assert not re.search(r"\d+\.\d+", line)
        assert "PORTFOLIO_ROI" in line
        assert f"n_fills={data.n_fills}" in line

    def test_the_frozen_inputs_alert_carries_no_currency_denominated_field(self) -> None:
        _latch, decision = apply_freshness_ladder(
            days_since_newest_input=10,
            latch=alert_ladder_state(streak=2),
            now_ns=_ns_of("2026-02-01"),
        )
        assert decision.should_alert is True
        assert "$" not in decision.detail
        assert not re.search(r"\d+\.\d\d\b", decision.detail)


def alert_ladder_state(
    *, streak: int, last_alert_severity: str | None = None, last_alert_period_key: str | None = None
) -> _ladder.LatchState:
    return _ladder.LatchState(
        schema_version=_ladder.LATCH_SCHEMA_VERSION,
        streak=streak,
        last_alert_severity=last_alert_severity,
        last_alert_period_key=last_alert_period_key,
    )


class TestFrozenInputDetector:
    def test_three_consecutive_stale_input_runs_emit_inputs_frozen_at_warn(self) -> None:
        latch = _FRESH_LATCH
        now_ns = _ns_of("2026-02-01")
        decisions = []
        for _ in range(3):
            latch, decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns
            )
            decisions.append(decision)

        assert [d.should_alert for d in decisions] == [False, False, True]
        assert decisions[-1].severity == "WARN"
        assert decisions[-1].event == FROZEN_INPUTS_EVENT

    def test_a_thirty_day_outage_re_alerts_weekly_then_escalates_to_daily_critical(self) -> None:
        latch = _FRESH_LATCH
        emitted: list[tuple[int, str]] = []
        for day_offset in range(30):
            now_ns = _ns_of("2026-01-01") + day_offset * _prr._NS_PER_DAY
            latch, decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns
            )
            if decision.should_alert:
                emitted.append((day_offset + 1, decision.severity))

        # streak==3 (day 3) is the first WARN; escalates to CRITICAL at
        # streak==14 (day 14), then daily thereafter.
        warns = [day for day, severity in emitted if severity == "WARN"]
        criticals = [day for day, severity in emitted if severity == "CRITICAL"]
        assert warns[0] == 3
        assert all(severity != "CRITICAL" for day, severity in emitted if day < 14)
        assert 14 in criticals
        # daily cadence from day 14 to day 30 inclusive.
        assert criticals == list(range(14, 31))

    def test_a_same_period_rerun_does_not_re_alert(self) -> None:
        latch = _FRESH_LATCH
        now_ns = _ns_of("2026-02-01")
        for _ in range(3):
            latch, _decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns
            )
        # A second run at the SAME instant (same ISO week) does not re-alert.
        latch, decision = apply_freshness_ladder(
            days_since_newest_input=10, latch=latch, now_ns=now_ns
        )
        assert decision.should_alert is False

    def test_the_latch_survives_a_process_restart_without_re_alerting(
        self, tmp_path: Path
    ) -> None:
        latch_path = tmp_path / ".input_freshness.json"
        latch = _FRESH_LATCH
        now_ns = _ns_of("2026-02-01")
        for _ in range(3):
            latch, _decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns
            )
        alert_ladder.write_latch_state(latch_path, latch)

        reloaded = alert_ladder.read_latch_state(latch_path)
        _new_latch, decision = apply_freshness_ladder(
            days_since_newest_input=10, latch=reloaded, now_ns=now_ns
        )
        assert decision.should_alert is False

    def test_a_missing_or_corrupt_latch_file_re_alerts_rather_than_failing_silent(
        self, tmp_path: Path
    ) -> None:
        latch_path = tmp_path / ".input_freshness.json"
        latch_path.write_text("{ not json")

        reloaded = alert_ladder.read_latch_state(latch_path)
        assert reloaded.streak == 0

        now_ns = _ns_of("2026-02-01")
        latch = reloaded
        decisions = []
        for _ in range(3):
            latch, decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns
            )
            decisions.append(decision)
        assert decisions[-1].should_alert is True

    def test_fresh_input_clears_the_streak_emits_one_info_and_fully_re_arms(self) -> None:
        latch = _FRESH_LATCH
        now_ns = _ns_of("2026-02-01")
        for _ in range(3):
            latch, _decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns
            )
        assert latch.streak == 3

        latch, clear_decision = apply_freshness_ladder(
            days_since_newest_input=1, latch=latch, now_ns=now_ns
        )
        assert clear_decision.should_alert is True
        assert clear_decision.severity == "INFO"
        assert clear_decision.event == FROZEN_INPUTS_CLEARED_EVENT
        assert latch.streak == 0

        # Full re-arm: a later freeze fires WARN again at streak == 3.
        decisions = []
        for _ in range(3):
            latch, decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns
            )
            decisions.append(decision)
        assert decisions[-1].should_alert is True
        assert decisions[-1].severity == "WARN"

    def test_severity_never_de_escalates_within_one_streak(self) -> None:
        latch = _FRESH_LATCH
        for day_offset in range(14):
            now_ns_i = _ns_of("2026-01-01") + day_offset * _prr._NS_PER_DAY
            latch, decision = apply_freshness_ladder(
                days_since_newest_input=10, latch=latch, now_ns=now_ns_i
            )
        assert decision.severity == "CRITICAL"
        # One more stale run, same day: no de-escalation to WARN.
        latch, decision2 = apply_freshness_ladder(
            days_since_newest_input=10,
            latch=latch,
            now_ns=now_ns_i + 3_600_000_000_000,
        )
        assert decision2.severity in (None, "CRITICAL")


class TestPermanentlyUnsettledAlert:
    def test_an_unsettled_position_alert_carries_no_currency_denominated_field(self) -> None:
        _latch, decision = apply_unsettled_positions_ladder(
            unsettled_count=1,
            max_days_past_horizon=5,
            latch=alert_ladder_state(streak=2),
            now_ns=_ns_of("2026-02-01"),
        )
        assert decision.should_alert is True
        assert decision.event == PERMANENTLY_UNSETTLED_EVENT
        assert "$" not in decision.detail
        assert "count=1" in decision.detail
        assert "max_days_past_horizon=5" in decision.detail

    def test_clearing_unsettled_positions_emits_one_info(self) -> None:
        latch = _FRESH_LATCH
        now_ns = _ns_of("2026-02-01")
        for _ in range(3):
            latch, _decision = apply_unsettled_positions_ladder(
                unsettled_count=1, max_days_past_horizon=10, latch=latch, now_ns=now_ns
            )
        latch, clear_decision = apply_unsettled_positions_ladder(
            unsettled_count=0, max_days_past_horizon=0, latch=latch, now_ns=now_ns
        )
        assert clear_decision.should_alert is True
        assert clear_decision.severity == "INFO"

# Shape-verbatim `AccountState(` line captured read-only from
# ~/.local/share/breezy/logs/breezy-trade-20260921T165055Z.log (step 0(c) of
# the plan) -- an account id and a balance figure, no credential. The three
# amounts were replaced with clearly synthetic values per plan D6 (no
# dollar figure in any committed file); the timestamp, logger name, field
# order, account id label, and event id are byte-identical to the live
# line so the parser is still exercised on the true shape.
_REAL_ACCOUNT_STATE_LINE = (
    "\x1b[1m2026-09-21T16:50:57.980817596Z\x1b[0m [INFO] BREEZY-L001.Portfolio: "
    "Updated AccountState(account_id=POLYMARKET_US-MAIN, account_type=CASH, "
    "base_currency=USD, is_reported=True, "
    "balances=[AccountBalance(total=100.00 USD, locked=0.00 USD, free=100.00 USD)], "
    "margins=[], event_id=f015c49e-d9ce-4327-bd2d-d9a4555eaada)\x1b[0m"
)

_FILL_KEY_PREFIX = "exec/polymarket_us/fill/"


def _fill(
    *,
    venue_order_id: str = "vo-1",
    instrument_id: str = "LAX-92-94.POLYMARKET_US",
    order_side: str = "BUY",
    cumulative_qty: Decimal = Decimal(1),
    cumulative_cost: Decimal = Decimal("0.40"),
    cumulative_fee: Decimal = Decimal("0.03"),
    fee_reconciled: bool = True,
    ts_event: int = 1_700_000_000_000_000_000,
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"client-{venue_order_id}",
        instrument_id=instrument_id,
        order_side=order_side,
        cumulative_qty=cumulative_qty,
        cumulative_cost=cumulative_cost,
        cumulative_fee=cumulative_fee,
        fee_reconciled=fee_reconciled,
        ts_event=ts_event,
    )


def _scored_trial(
    *,
    trial_id: str,
    pnl: Decimal,
    climate_day: str = "2026-09-21",
    scored_at_ns: int = 1_700_000_000_000_000_000,
    settlement_basis: SettlementBasis = "nws_final",
    held: bool = True,
    fill_px: Decimal = Decimal("0.40"),
    fee: Decimal = Decimal("0.03"),
) -> ScoredTrial:
    return ScoredTrial(
        trial_id=trial_id,
        station="LAX",
        climate_day=climate_day,
        instrument_id="LAX-92-94.POLYMARKET_US",
        settlement_tmax_f=93,
        held=held,
        pnl=pnl,
        revision_seq=1,
        raw_sha256="a" * 64,
        scored_at_ns=scored_at_ns,
        score_seq=1,
        settlement_basis=settlement_basis,
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=Decimal("0.40"),
        fill_px=fill_px,
        fee=fee,
    )


def _ns_of_day(day: str) -> int:
    """Midnight UTC of an ISO calendar-day string, in epoch nanoseconds."""
    dt = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)


def _filled_trial(
    *,
    trial_id: str,
    scheduled_release_day: str,
    filled_at_day: str | None = None,
) -> FilledTrial:
    filled_at_day = filled_at_day or scheduled_release_day
    return FilledTrial(
        trial_id=trial_id,
        station="LAX",
        climate_day=scheduled_release_day,
        instrument_id="LAX-92-94.POLYMARKET_US",
        bucket=None,
        fill_px=Decimal("0.40"),
        fee=Decimal("0.03"),
        qty=Decimal(1),
        filled_at_ns=_ns_of_day(filled_at_day),
        entry_ask=Decimal("0.40"),
        scheduled_release_at_ns=_ns_of_day(scheduled_release_day),
    )


class TestReadLedgerFills:
    def test_an_absent_ledger_returns_none_not_zero(self, tmp_path: Path) -> None:
        assert read_ledger_fills(tmp_path / "does_not_exist.sqlite") is None

    def test_reads_only_fill_prefixed_rows_and_skips_other_keys(self, tmp_path: Path) -> None:
        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            fill = _fill(venue_order_id="vo-42")
            store.set(f"{_FILL_KEY_PREFIX}vo-42", fill.to_bytes())
            store.set("current_rung_hold/trial/LAX/2026-09-21", b"not a fill record")
        finally:
            store.close()

        fills = read_ledger_fills(store_path)

        assert fills is not None
        assert len(fills) == 1
        assert fills[0].venue_order_id == "vo-42"


class TestLegAwareCapitalDeployed:
    def test_a_no_leg_and_a_yes_leg_fill_on_one_station_day_are_both_counted_in_capital_deployed(
        self,
    ) -> None:
        yes_fill = _fill(
            venue_order_id="vo-yes",
            instrument_id="LAX-92-94.POLYMARKET_US",
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        no_fill = _fill(
            venue_order_id="vo-no",
            instrument_id="LAX-92-94^no.POLYMARKET_US",
            cumulative_cost=Decimal("0.35"),
            cumulative_fee=Decimal("0.02"),
        )

        assert leg_of_fill(yes_fill) == "yes"
        assert leg_of_fill(no_fill) == "no"

        total = total_capital_deployed([yes_fill, no_fill])

        # Never netted: the sum of BOTH legs' cost+fee, not a station-day
        # accumulator that could cancel one leg against the other.
        assert total == Decimal("0.40") + Decimal("0.03") + Decimal("0.35") + Decimal("0.02")
        assert capital_deployed_for_fill(yes_fill) == Decimal("0.43")
        assert capital_deployed_for_fill(no_fill) == Decimal("0.37")


class TestFeeReconciliationLabel:
    def test_a_fill_whose_fee_is_unreconciled_is_labelled_not_silently_modelled(self) -> None:
        unreconciled = _fill(fee_reconciled=False, cumulative_fee=Decimal("0.02"))
        reconciled = _fill(fee_reconciled=True, cumulative_fee=Decimal("0.03"))

        assert fee_reconciliation_label(unreconciled) == FEE_UNRECONCILED_LABEL
        assert fee_reconciliation_label(reconciled) == FEE_RECONCILED_LABEL

        # The fee itself is never silently zeroed or substituted -- an
        # unreconciled fee is still exactly what the ledger recorded.
        assert capital_deployed_for_fill(unreconciled) == (
            unreconciled.cumulative_cost + unreconciled.cumulative_fee
        )


class TestFillBucketing:
    def test_every_ledger_fill_lands_in_exactly_one_bucket(self) -> None:
        scored_fill = AttributedFill(fill=_fill(venue_order_id="vo-1"), trial_id="t-scored")
        residual_fill = AttributedFill(fill=_fill(venue_order_id="vo-2"), trial_id="t-residual")
        unreconciled_fill = AttributedFill(fill=_fill(venue_order_id="vo-3"), trial_id=None)
        fills = (scored_fill, residual_fill, unreconciled_fill)

        buckets = bucket_ledger_fills(
            fills,
            scored_trial_ids=frozenset({"t-scored"}),
            residual_trial_ids=frozenset({"t-residual"}),
        )

        assert buckets[FillBucket.SCORED] == (scored_fill,)
        assert buckets[FillBucket.RESIDUAL] == (residual_fill,)
        assert buckets[FillBucket.UNRECONCILED] == (unreconciled_fill,)
        total_bucketed = sum(len(rows) for rows in buckets.values())
        assert total_bucketed == len(fills)

    def test_an_unattributed_fill_is_unreconciled_even_if_its_id_would_otherwise_match(
        self,
    ) -> None:
        """`trial_id is None` means "never attributed" -- it must never be
        treated as a wildcard match against either set."""
        unattributed = AttributedFill(fill=_fill(venue_order_id="vo-9"), trial_id=None)

        buckets = bucket_ledger_fills(
            (unattributed,),
            scored_trial_ids=frozenset({"t-scored"}),
            residual_trial_ids=frozenset(),
        )

        assert buckets[FillBucket.UNRECONCILED] == (unattributed,)
        assert buckets[FillBucket.SCORED] == ()


class TestRealisedPnlNeverScopedByAdmissibility:
    def test_a_residual_fill_is_counted_in_portfolio_pnl_but_never_in_n(self) -> None:
        """I3: `n` (admissibility-filtered) excludes a residual trial_id
        even when a `ScoredTrial` row exists for it; the account-level
        portfolio P&L must not."""
        residual_scored = _scored_trial(trial_id="t-residual", pnl=Decimal("0.57"))
        clean_scored = _scored_trial(trial_id="t-clean", pnl=Decimal("-0.40"))
        all_rows = (residual_scored, clean_scored)
        residual_ids = frozenset({"t-residual"})

        n_admissible = admissible_scored_trials(all_rows, residual_trial_ids=residual_ids)
        assert {t.trial_id for t in n_admissible} == {"t-clean"}

        portfolio_pnl = total_realised_pnl_all_settled(all_rows)
        assert portfolio_pnl == Decimal("0.17")

        admissible_pnl = total_realised_pnl_admissible(
            all_rows, residual_trial_ids=residual_ids
        )
        assert admissible_pnl == Decimal("-0.40")
        # The residual fill's pnl is in the portfolio total but not the
        # narrower admissible total -- the exact I3 property.
        assert portfolio_pnl != admissible_pnl


class TestAccountStateFixtureCarriesOnlySyntheticAmounts:
    def test_the_account_state_fixture_carries_only_synthetic_amounts(self) -> None:
        """AUD-04 D6 (no dollar figure in any committed file): the fixture
        above is shape-verbatim from a live log line but its three amounts
        were replaced with clearly synthetic values. This pins those exact
        values so a future "refresh the fixture from a live log" swap
        cannot silently re-introduce a real account balance."""
        point = parse_account_state_line(_REAL_ACCOUNT_STATE_LINE)
        assert point is not None
        assert point.total_usd == Decimal("100.00")

        amounts = re.findall(r"(\d+\.\d{2}) USD", _REAL_ACCOUNT_STATE_LINE)
        assert amounts == ["100.00", "0.00", "100.00"]


class TestBalanceSeriesParser:
    def test_parses_the_verbatim_fixture_line(self) -> None:
        point = parse_account_state_line(_REAL_ACCOUNT_STATE_LINE)

        assert point is not None
        assert isinstance(point, BalancePoint)
        assert point.account_id == "POLYMARKET_US-MAIN"
        assert point.total_usd == Decimal("100.00")
        assert point.ts_iso == "2026-09-21T16:50:57.980817596Z"

    def test_a_line_without_the_account_state_token_is_unknown(self) -> None:
        assert parse_account_state_line("2026-09-21T00:00:00Z [INFO] unrelated line") is None

    def test_a_garbled_account_state_line_is_unknown_never_a_fallback_regex(self) -> None:
        garbled = "2026-09-21T00:00:00.000000000Z [INFO] AccountState(totally not the shape)"
        assert parse_account_state_line(garbled) is None


# ---------------------------------------------------------------------------
# C1b -- the cash-identity reconciliation (§6 D4), the settlement-date proxy
# (D4 R3), the settled-through cutoff (D4 R4/R5/R6), the D9 permanently-
# unsettled detector's pure core, and ROI vs the two registered baselines
# (D5).
# ---------------------------------------------------------------------------


class TestWorkedOpenThenSettleExample:
    def test_the_worked_open_then_settle_example_reconciles_to_zero_on_both_days(
        self,
    ) -> None:
        """§6 D4 worked example, reproduced verbatim as a fixture: 'One YES
        contract bought on day 1 at ask $0.40 with fee $0.03, settling HIGH
        on day 5 for $1.00' -- 'Cumulative cross-check ... asserted by the
        same test: Sum_D Delta_balance = -0.43 + 1.00 = +0.57 = Sum realised
        P&L, and Sum_D unexplained = 0.'
        """
        open_fill = _fill(
            venue_order_id="vo-open",
            ts_event=_ns_of_day("2026-01-02"),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        settled_trial = _scored_trial(
            trial_id="t-1",
            pnl=Decimal("0.57"),
            held=True,
            climate_day="2026-01-02",
            scored_at_ns=_ns_of_day("2026-01-06"),
            fill_px=Decimal("0.40"),
            fee=Decimal("0.03"),
        )
        daily_balances = {
            "2026-01-01": Decimal("100.00"),
            "2026-01-02": Decimal("99.57"),
            "2026-01-03": Decimal("99.57"),
            "2026-01-04": Decimal("99.57"),
            "2026-01-05": Decimal("99.57"),
            "2026-01-06": Decimal("100.57"),
        }

        rows = reconcile_daily(
            fills=[open_fill], scored_trials=[settled_trial], daily_balances=daily_balances
        )
        rows_by_day = {row.day: row for row in rows}

        assert rows_by_day["2026-01-02"].unexplained == Decimal("0.00")
        assert rows_by_day["2026-01-06"].unexplained == Decimal("0.00")
        # G1: 2026-01-01 (the earliest known-balance day) is now its own
        # `NO_PRIOR_BALANCE` row with `unexplained=None` -- excluded from
        # this cumulative sum exactly like a `BALANCE_UNKNOWN` row.
        assert rows_by_day["2026-01-01"].classification == NO_PRIOR_BALANCE_LABEL
        cumulative_unexplained = sum(
            (row.unexplained for row in rows if row.unexplained is not None), start=Decimal(0)
        )
        assert cumulative_unexplained == Decimal("0.00")

        cumulative_delta_balance = sum(
            (row.delta_balance for row in rows if row.delta_balance is not None),
            start=Decimal(0),
        )
        realised_pnl = total_realised_pnl_all_settled([settled_trial])
        assert cumulative_delta_balance == Decimal("0.57") == realised_pnl


class TestPayoutCountedExactlyOnce:
    def test_a_settled_position_payout_is_never_counted_in_both_proceeds_and_capital_deployed(
        self,
    ) -> None:
        """§6 D4: 'Every DurableFillRecord contributes to capital_deployed on
        exactly one date (its open) and to proceeds on exactly one date (its
        settlement) ... No row is counted twice, and the settlement payout
        appears in the cash identity exactly once.'
        """
        open_fill = _fill(
            venue_order_id="vo-open",
            ts_event=_ns_of_day("2026-01-02"),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        settled_trial = _scored_trial(
            trial_id="t-1",
            pnl=Decimal("0.57"),
            held=True,
            climate_day="2026-01-02",
            scored_at_ns=_ns_of_day("2026-01-06"),
        )

        capital_by_day = _prr.capital_deployed_by_day([open_fill])
        proceeds_by_day = _prr.proceeds_by_day([settled_trial])

        assert capital_by_day == {"2026-01-02": Decimal("0.43")}
        assert proceeds_by_day == {"2026-01-06": Decimal("1.00")}
        # Disjoint days -- the open day carries no proceeds and the
        # settlement day carries no capital-deployed contribution.
        assert "2026-01-06" not in capital_by_day
        assert "2026-01-02" not in proceeds_by_day


class TestLosingSettlementSameIdentity:
    def test_a_losing_settlement_uses_the_same_identity_with_no_sign_special_case(self) -> None:
        """§6 D4: 'A losing settlement (payout = 0.00 on D5) gives
        Delta_balance(D5) = 0.00, unexplained(D5) = 0.00 and realised P&L
        -0.43 -- the same identity with no sign special-case.'
        """
        open_fill = _fill(
            venue_order_id="vo-open",
            ts_event=_ns_of_day("2026-01-02"),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        losing_trial = _scored_trial(
            trial_id="t-1",
            pnl=Decimal("-0.43"),
            held=False,
            climate_day="2026-01-02",
            scored_at_ns=_ns_of_day("2026-01-06"),
        )
        daily_balances = {
            "2026-01-01": Decimal("100.00"),
            "2026-01-02": Decimal("99.57"),
            "2026-01-06": Decimal("99.57"),
        }

        rows = reconcile_daily(
            fills=[open_fill], scored_trials=[losing_trial], daily_balances=daily_balances
        )
        rows_by_day = {row.day: row for row in rows}

        assert settlement_payout(losing_trial) == Decimal("0.00")
        assert rows_by_day["2026-01-06"].delta_balance == Decimal("0.00")
        assert rows_by_day["2026-01-06"].unexplained == Decimal("0.00")
        assert total_realised_pnl_all_settled([losing_trial]) == Decimal("-0.43")


class TestUnexplainedTolerance:
    def test_an_unexplained_balance_delta_is_reported_and_never_netted_into_roi(self) -> None:
        """§6 D4: a genuine capital flow (deposit/withdrawal) breaches
        tolerance and is reported as UNEXPLAINED_CAPITAL_FLOW, never folded
        into realised P&L or silently netted away."""
        daily_balances = {
            "2026-01-01": Decimal("100.00"),
            "2026-01-02": Decimal("150.00"),  # an unexplained $50 deposit
        }

        rows = reconcile_daily(fills=[], scored_trials=[], daily_balances=daily_balances)
        rows_by_day = {row.day: row for row in rows}

        row = rows_by_day["2026-01-02"]
        assert row.unexplained == Decimal("50.00")
        assert row.breaches_tolerance is True
        assert row.classification == UNEXPLAINED_CAPITAL_FLOW_LABEL
        # Realised P&L is computed over settled trials only -- this flow
        # never entered that computation and is not netted against it.
        assert total_realised_pnl_all_settled([]) == Decimal(0)

    def test_the_unexplained_tolerance_is_one_cent_per_fill_not_a_literal(self) -> None:
        """§6 D4: 'The tolerance is not an asserted constant: it is
        TOLERANCE_day = n_fills_that_day x $0.01 ... the maximum accumulated
        round-up error on a day is exactly one cent per fill.'
        """
        day = "2026-01-02"
        fills = [
            _fill(
                venue_order_id=f"vo-{i}",
                ts_event=_ns_of_day(day),
                cumulative_cost=Decimal("0.40"),
                cumulative_fee=Decimal("0.01"),
            )
            for i in range(3)
        ]
        assert per_day_tolerance(3) == Decimal("0.03")
        assert per_day_tolerance(1) == Decimal("0.01")

        # capital_deployed(day) = 3 * 0.41 = 1.23; the real venue debit was
        # 1.20 (a 1-cent-per-fill rounding gap accumulated across 3 fills).
        daily_balances = {"2026-01-01": Decimal("100.00"), day: Decimal("98.80")}
        rows = reconcile_daily(fills=fills, scored_trials=[], daily_balances=daily_balances)
        row = next(r for r in rows if r.day == day)

        assert row.unexplained == Decimal("0.03")
        assert row.tolerance == Decimal("0.03")
        # At the boundary (magnitude == tolerance) this is NOT a breach --
        # a literal single-cent tolerance would have wrongly flagged it.
        assert row.breaches_tolerance is False
        assert Decimal("0.01") < abs(row.unexplained)


class TestProceedsDatingProxy:
    def test_proceeds_are_dated_by_scored_at_ns_not_by_climate_day(self) -> None:
        """§6 D4 R3: 'proceeds(D) is dated by the UTC calendar day of
        scored_at_ns, and by nothing else.'"""
        trial = _scored_trial(
            trial_id="t-1",
            pnl=Decimal("0.57"),
            held=True,
            climate_day="2026-01-02",
            scored_at_ns=_ns_of_day("2026-01-05"),
        )

        assert proceeds_date(trial) == "2026-01-05"
        assert proceeds_date(trial) != trial.climate_day

        proceeds = _prr.proceeds_by_day([trial])
        assert proceeds == {"2026-01-05": Decimal("1.00")}

        daily_balances = {
            "2026-01-01": Decimal("100.00"),
            "2026-01-05": Decimal("101.00"),
        }
        rows = reconcile_daily(fills=[], scored_trials=[trial], daily_balances=daily_balances)
        row = next(r for r in rows if r.day == "2026-01-05")
        assert row.proceeds_date_proxy == PROCEEDS_DATE_PROXY_LABEL


class TestProxyLagClassification:
    def test_a_breach_explained_entirely_by_proxy_lag_is_classified_not_netted(self) -> None:
        """§6 D4 R3: a settlement 'dated D but scored on D+7 (the
        venue_last_fair_price_fallback shape) ... both days breach the
        per-day tolerance, the class is UNEXPLAINED_PROXY_LAG on both,
        settlement_lag_days == 7 is reported, and Sum_D unexplained == 0.'
        """
        credit_day = "2026-01-02"
        scored_day = "2026-01-09"  # exactly 7 days later
        trial = _scored_trial(
            trial_id="t-1",
            pnl=Decimal("0.57"),
            held=True,
            climate_day=credit_day,
            scored_at_ns=_ns_of_day(scored_day),
            settlement_basis="venue_last_fair_price_fallback",
        )
        assert settlement_lag_days(trial) == 7

        daily_balances = {
            "2026-01-01": Decimal("100.00"),
            credit_day: Decimal("101.00"),  # cash credited before it is ever scored
            scored_day: Decimal("101.00"),  # no further cash movement that day
        }

        rows = reconcile_daily(fills=[], scored_trials=[trial], daily_balances=daily_balances)
        rows_by_day = {row.day: row for row in rows}
        # G1: 2026-01-01 (the earliest known-balance day) is now its own
        # `NO_PRIOR_BALANCE` row with `unexplained=None` -- excluded from
        # this cumulative sum exactly like a `BALANCE_UNKNOWN` row.
        cumulative = sum(
            (row.unexplained for row in rows if row.unexplained is not None), start=Decimal(0)
        )

        assert rows_by_day[credit_day].breaches_tolerance is True
        assert rows_by_day[scored_day].breaches_tolerance is True
        assert rows_by_day[credit_day].classification == UNEXPLAINED_PROXY_LAG_LABEL
        assert rows_by_day[scored_day].classification == UNEXPLAINED_PROXY_LAG_LABEL
        assert rows_by_day[credit_day].settlement_lag_days == 7
        assert rows_by_day[scored_day].settlement_lag_days == 7
        assert cumulative == Decimal("0.00")


class TestSettledThroughCutoff:
    def test_a_small_lag_sample_uses_max_not_p99_and_says_so_in_the_header(self) -> None:
        """§6 D4 R5/R6: 'below n = 20 [p99] is an extrapolation ... With
        lag_sample_n < MIN_LAG_SAMPLE_N, the cutoff uses max(observed
        settlement_lag_days) ... An EMPTY sample ... falls back to the bare
        structural floor 7.' Header fragment:
        'settled_through_statistic=<max|p99> lag_sample_n=<n>'.
        """
        now_day = "2026-02-01"

        small_lags = [1, 1, 1, 1, 2, 100]
        assert len(small_lags) == 6
        settled_through, statistic, n = compute_settled_through(now_day=now_day, lags=small_lags)
        assert statistic == "max"
        assert n == 6
        assert settled_through == "2025-10-24"  # now_day - 100 days
        assert settled_through_statistic_label(statistic_name=statistic, lag_sample_n=n) == (
            "settled_through_statistic=max lag_sample_n=6"
        )

        large_lags = [1] * 18 + [2, 100]
        assert len(large_lags) == 20
        _, statistic_large, n_large = compute_settled_through(now_day=now_day, lags=large_lags)
        assert statistic_large == "p99"
        assert n_large == 20
        assert settled_through_statistic_label(
            statistic_name=statistic_large, lag_sample_n=n_large
        ) == "settled_through_statistic=p99 lag_sample_n=20"

        settled_through_empty, _statistic_empty, n_empty = compute_settled_through(
            now_day=now_day, lags=[]
        )
        assert n_empty == 0
        assert settled_through_empty == "2026-01-25"  # now_day - 7 days, the bare floor

    def test_an_in_flight_settlement_inside_the_settled_through_window_does_not_fail_the_cumulative_check(  # noqa: E501 -- exact name pinned by the plan
        self,
    ) -> None:
        """§6 D4 R4/R5: an in-flight credit inside the provisional tail must
        not fail the settled cumulative check, but the identical breach
        placed inside the settled window must still fail it (the
        anti-suppression half)."""
        now_day = "2026-02-08"
        lags = [1, 1, 1, 2]  # step-0(f)'s measured distribution: max=2
        settled_through, _, _ = compute_settled_through(now_day=now_day, lags=lags)
        assert settled_through == "2026-02-01"  # now_day - max(7, 2) = now_day - 7

        in_flight_day = "2026-02-06"  # now_day - 2: AFTER settled_through
        daily_balances = {
            "2026-02-05": Decimal("100.00"),
            in_flight_day: Decimal("101.00"),  # a credit with no ScoredTrial yet
        }
        rows = reconcile_daily(fills=[], scored_trials=[], daily_balances=daily_balances)
        cumulative = cumulative_reconciliation(
            daily_rows=rows, settled_through=settled_through
        )

        in_flight_row = next(r for r in cumulative.all_rows if r.day == in_flight_day)
        assert in_flight_row.provisional is True
        assert in_flight_row.breaches_tolerance is True
        assert cumulative.settled_cumulative_unexplained == Decimal("0.00")
        assert cumulative.settled_cumulative_passes is True
        assert cumulative.provisional_cumulative_unexplained == Decimal("1.00")

        # Anti-suppression half: the identical breach placed INSIDE the
        # settled window must still fail the cumulative check.
        settled_day = "2026-01-20"  # well before settled_through
        daily_balances_settled = {
            "2026-01-19": Decimal("100.00"),
            settled_day: Decimal("101.00"),
        }
        rows_settled = reconcile_daily(
            fills=[], scored_trials=[], daily_balances=daily_balances_settled
        )
        cumulative_settled = cumulative_reconciliation(
            daily_rows=rows_settled, settled_through=settled_through
        )
        assert cumulative_settled.settled_cumulative_passes is False


class TestPermanentlyUnsettledDetector:
    def test_a_position_that_opens_and_never_settles_is_flagged_not_silently_reconciled(
        self,
    ) -> None:
        """§6 D9: substituting D4's own term scoping for a never-settled
        position gives 'unexplained(D1) = 0': 'capital_deployed(D1) cancels
        the balance leg on the open day' -- the cash identity is blind by
        construction, so an independent left-anti-join detector is required.

        In scope for THIS test: the cash identity's blindness (a), the pure
        flagging function with days_past_horizon (b), and that the fill's
        capital stays in the denominator/its partition bucket (c). The
        roi_status/UnsettledCapitalRoiError gating (d) is covered by
        ``TestJsonSchemaVersion
        .test_a_position_that_opens_and_never_settles_gates_the_roi_reader``
        above, and the alert emission (e) by ``TestPermanentlyUnsettledAlert``
        above -- both now built (this module's C2 stage), not deferred.
        """
        open_day = "2026-01-02"
        trial_id = "t-stuck"
        open_fill = _fill(
            venue_order_id="vo-stuck", ts_event=_ns_of_day(open_day),
            cumulative_cost=Decimal("0.40"), cumulative_fee=Decimal("0.03"),
        )
        daily_balances = {
            "2026-01-01": Decimal("100.00"),
            open_day: Decimal("99.57"),  # exactly the capital-deployed debit
        }

        rows = reconcile_daily(fills=[open_fill], scored_trials=[], daily_balances=daily_balances)
        open_row = next(r for r in rows if r.day == open_day)
        assert open_row.unexplained == Decimal("0.00")
        cumulative = cumulative_reconciliation(daily_rows=rows, settled_through=open_day)
        assert cumulative.settled_cumulative_passes is True

        filled_trial = _filled_trial(trial_id=trial_id, scheduled_release_day=open_day)
        far_past_horizon_ns = max_settlement_horizon_ns(filled_trial.scheduled_release_at_ns) + (
            10 * 24 * 60 * 60 * 1_000_000_000
        )
        flagged = permanently_unsettled_trials(
            [filled_trial], scored_trial_ids=frozenset(), now_ns=far_past_horizon_ns
        )
        assert len(flagged) == 1
        assert flagged[0].trial_id == trial_id
        assert flagged[0].days_past_horizon == 10

        # (c) the fill's capital stays in the denominator and in its
        # partition bucket -- never dropped because it is stuck.
        attributed = AttributedFill(fill=open_fill, trial_id=None)  # never scored
        buckets = bucket_ledger_fills(
            [attributed], scored_trial_ids=frozenset(), residual_trial_ids=frozenset()
        )
        assert buckets[FillBucket.UNRECONCILED] == (attributed,)
        assert total_capital_deployed([open_fill]) == Decimal("0.43")

        # Negative half: one day INSIDE the horizon is not flagged.
        one_day_inside_ns = max_settlement_horizon_ns(filled_trial.scheduled_release_at_ns) - (
            24 * 60 * 60 * 1_000_000_000
        )
        not_flagged = permanently_unsettled_trials(
            [filled_trial], scored_trial_ids=frozenset(), now_ns=one_day_inside_ns
        )
        assert not_flagged == ()


class TestRoiAgainstBaselines:
    def test_roi_is_reported_against_both_registered_baselines(self) -> None:
        """§6 D5: 'B0 -- cash. 0.00 return on the same deployed capital'
        and 'B1 -- fee-drag null ... ROI_B1 = -Sum fee_i / Sum cost_i.'"""
        fill = _fill(
            venue_order_id="vo-1", cumulative_cost=Decimal("0.40"), cumulative_fee=Decimal("0.03")
        )
        trial = _scored_trial(trial_id="t-1", pnl=Decimal("0.57"))

        total_pnl = total_realised_pnl_all_settled([trial])
        total_capital = total_capital_deployed([fill])
        result = roi_against_baselines(
            total_realised_pnl=total_pnl, total_capital_deployed=total_capital, fills=[fill]
        )

        assert result.baseline_b0 == BASELINE_B0_CASH == Decimal(0)
        assert result.baseline_b1 == baseline_b1_fee_drag([fill])
        assert result.baseline_b1 == -(Decimal("0.03") / Decimal("0.40"))
        assert result.roi == total_pnl / total_capital
        assert result.roi_minus_b0 == result.roi
        assert result.roi_minus_b1 == result.roi - result.baseline_b1

    def test_a_missing_balance_point_is_unknown_not_interpolated(self) -> None:
        series = daily_balance_series(
            [_REAL_ACCOUNT_STATE_LINE],
            days=["2026-09-20", "2026-09-21", "2026-09-22"],
        )

        assert series["2026-09-20"] is None
        assert series["2026-09-22"] is None
        point = series["2026-09-21"]
        assert point is not None
        assert point.total_usd == Decimal("100.00")

    def test_the_last_matching_line_for_a_day_wins(self) -> None:
        earlier = (
            "2026-09-21T01:00:00.000000000Z [INFO] Updated "
            "AccountState(account_id=POLYMARKET_US-MAIN, account_type=CASH, "
            "base_currency=USD, is_reported=True, "
            "balances=[AccountBalance(total=100.00 USD, locked=0.00 USD, free=100.00 USD)], "
            "margins=[], event_id=aaaa)"
        )
        later = (
            "2026-09-21T23:00:00.000000000Z [INFO] Updated "
            "AccountState(account_id=POLYMARKET_US-MAIN, account_type=CASH, "
            "base_currency=USD, is_reported=True, "
            "balances=[AccountBalance(total=200.00 USD, locked=0.00 USD, free=200.00 USD)], "
            "margins=[], event_id=bbbb)"
        )
        series = daily_balance_series([earlier, later], days=["2026-09-21"])

        point = series["2026-09-21"]
        assert point is not None
        assert point.total_usd == Decimal("200.00")


# --------------------------------------------------------------------------
# Defect fix (AUD-04 C2, live dry-run root cause): _run()'s per-family store
# layout, the D9 placeholder scheduled_release_at_ns, and the silent
# per-(family, station) refusal swallow.
# --------------------------------------------------------------------------


def _write_family_manifest(
    families_dir: Path,
    *,
    family_id: str,
    trial_id_prefix: str,
    stations: tuple[str, ...] = ("LAX",),
) -> None:
    """Minimal valid (allow_draft=True) manifest -- the same shape
    ``attribute_fills_via_family_manifests``/``_run`` load via
    ``load_family_manifest(path, allow_draft=True)``."""
    manifest = {
        "family_id": family_id,
        "venue": "polymarket_us",
        "trial_id_prefix": trial_id_prefix,
        "d0_climate_day": "2026-09-01",
        "boundary_artefact_path": "deploy/families/gs_boundary_pm_us_crh_v2.json",
        "boundary_inputs_sha256": "0" * 64,
        "composition_kind": "current_rung_hold",
        "density_artefact_path": "deploy/families/artefacts/not_applicable_density.json",
        "density_artefact_sha256": "0" * 64,
        "stations": list(stations),
        "taker_fee_coefficient": "0.06",
        "status": "DRAFT_NOT_REGISTERED",
    }
    families_dir.mkdir(parents=True, exist_ok=True)
    (families_dir / f"{family_id}.json").write_text(json.dumps(manifest))


def _write_excluded_fills_line(
    store_dir: Path, *, trial_id: str, venue_order_id: str, reason: str = "duplicate_fill"
) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    line = {
        "trial_id": trial_id,
        "station": "LAX",
        "climate_day": "2026-09-01",
        "venue_order_id": venue_order_id,
        "qty": "1",
        "reason": reason,
        "filled_at_ns": 1_700_000_000_000_000_000,
        "scored_run_utc": "2026-09-01T00:00:00Z",
    }
    path = store_dir / EXCLUDED_FILLS_FILENAME
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


class TestDefect1PooledPerFamilyStores:
    """The live layout is `<scored_trials_dir>/<family_id>/scored_trials_*
    .parquet` and `.../<family_id>/excluded_fills.jsonl` -- never a
    top-level file directly under `scored_trials_dir`. `read_scored_trials`/
    `residual_trial_ids` (the pre-fix code) never recurse, so calling them
    on the parent always returned nothing."""

    def test_scored_trials_and_residual_ids_are_pooled_across_family_subdirectories(
        self, tmp_path: Path
    ) -> None:
        scored_trials_dir = tmp_path / "scored_trials"
        trial_a = _scored_trial(trial_id="fam_a/trial/LAX/2026-09-01", pnl=Decimal("0.10"))
        trial_b = _scored_trial(trial_id="fam_b/trial/LAX/2026-09-02", pnl=Decimal("0.20"))
        write_scored_trials(
            scored_trials_dir / "fam_a", [trial_a], now_ns=1_700_000_000_000_000_000
        )
        write_scored_trials(
            scored_trials_dir / "fam_b", [trial_b], now_ns=1_700_000_000_000_000_000
        )
        _write_excluded_fills_line(
            scored_trials_dir / "fam_a",
            trial_id="fam_a/trial/LAX/2026-09-03",
            venue_order_id="vo-residual-a",
        )
        # A residual entry in the PARENT (family-agnostic) directory --
        # never a real production layout (no production caller passes the
        # parent to residual_trial_ids/read_excluded_fills); must NOT be
        # picked up.
        _write_excluded_fills_line(
            scored_trials_dir, trial_id="fam_parent/should-not-count", venue_order_id="vo-parent"
        )

        pooled = read_scored_trials_pooled(scored_trials_dir)
        assert {t.trial_id for t in pooled.rows} == {trial_a.trial_id, trial_b.trial_id}

        residual_ids = residual_trial_ids_pooled(scored_trials_dir)
        assert residual_ids == frozenset({"fam_a/trial/LAX/2026-09-03"})
        assert "fam_parent/should-not-count" not in residual_ids

    def test_a_residual_id_present_in_two_family_stores_counts_once(self, tmp_path: Path) -> None:
        scored_trials_dir = tmp_path / "scored_trials"
        # Two families' own excluded_fills.jsonl each record the SAME
        # trial_id (a synthetic edge case -- the union must not double it).
        _write_excluded_fills_line(
            scored_trials_dir / "fam_a", trial_id="shared/trial/1", venue_order_id="vo-1"
        )
        _write_excluded_fills_line(
            scored_trials_dir / "fam_b", trial_id="shared/trial/1", venue_order_id="vo-2"
        )

        residual_ids = residual_trial_ids_pooled(scored_trials_dir)
        assert residual_ids == frozenset({"shared/trial/1"})

    def test_absent_directory_returns_empty_never_an_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        assert read_scored_trials_pooled(missing).rows == ()
        assert residual_trial_ids_pooled(missing) == frozenset()


def _stub_reader(
    responses: dict[tuple[str, str], tuple[tuple[FilledTrial, ...], dict[str, Any]]],
) -> Any:
    """A drop-in substitute for `score_live_trials.read_filled_trials_state_db`,
    keyed by `(family_prefix, city)` -> `(trials, fee_reconciled_by_trial_id)`.
    `_run()` calls the real `read_filled_trials_state_db` per (manifest,
    station) pair -- building a real live exec-state store + node-preflight
    fixture for that reader is the 840-line fixture
    `tests/contract/test_live_fill_scoring_chain_contract.py` already owns;
    this stub isolates `_run()`'s OWN orchestration defect (which directory
    it reads, whether it applies `_with_scheduled_release_at_ns`, whether it
    logs/counts a refusal) from that reader's already-covered internals. A
    key with no fixture entry raises `FillSourceUnreadableError`, exactly
    one of the three refused exception types both call sites already catch.
    """

    def _reader(
        path: Path,
        *,
        family_prefix: str,
        city: str,
        cli_location: str,
        since_climate_day: str,
        stations: Any,
    ) -> Any:
        key = (family_prefix, city)
        if key not in responses:
            raise _prr.FillSourceUnreadableError(f"no fixture data for {key!r}")
        trials, fee_map = responses[key]
        return trials, (), fee_map, {}

    return _reader


class TestRunDefect1FamilyAgnosticJoinIsPerFamily:
    def test_scored_and_residual_counts_sum_across_registered_families(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        families_dir = tmp_path / "families"
        _write_family_manifest(families_dir, family_id="fam_a", trial_id_prefix="fam_a/trial/")
        _write_family_manifest(families_dir, family_id="fam_b", trial_id_prefix="fam_b/trial/")

        scored_trials_dir = tmp_path / "scored_trials"
        trial_a = _scored_trial(trial_id="fam_a/trial/LAX/2026-09-01", pnl=Decimal("0.10"))
        trial_b = _scored_trial(trial_id="fam_b/trial/LAX/2026-09-02", pnl=Decimal("0.20"))
        write_scored_trials(scored_trials_dir / "fam_a", [trial_a], now_ns=1)
        write_scored_trials(scored_trials_dir / "fam_b", [trial_b], now_ns=2)

        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            fill_scored_a = _fill(venue_order_id="vo-a", ts_event=_ns_of_day("2026-09-01"))
            fill_scored_b = _fill(venue_order_id="vo-b", ts_event=_ns_of_day("2026-09-02"))
            store.set(f"{_FILL_KEY_PREFIX}vo-a", fill_scored_a.to_bytes())
            store.set(f"{_FILL_KEY_PREFIX}vo-b", fill_scored_b.to_bytes())
        finally:
            store.close()

        reader = _stub_reader(
            {
                ("fam_a/trial/", "LAX"): (
                    (),
                    {"fam_a/trial/LAX/2026-09-01": (True, "vo-a", False)},
                ),
                ("fam_b/trial/", "LAX"): (
                    (),
                    {"fam_b/trial/LAX/2026-09-02": (True, "vo-b", False)},
                ),
            }
        )
        monkeypatch.setattr(_prr, "read_filled_trials_state_db", reader)

        exit_code = _run(
            exec_state_db_path=store_path,
            scored_trials_dir=scored_trials_dir,
            logs_dir=tmp_path / "logs",
            output_dir=tmp_path / "derived",
            families_dir=families_dir,
            now_ns=_ns_of_day("2026-09-05"),
            sink=_prr.resolve_alert_sink({}),
        )

        assert exit_code == 0
        report = json.loads(
            (tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-05.json").read_text()
        )
        # Pre-fix: n_scored=0 always (family-agnostic parent never recurses).
        # Post-fix: both fills join to a scored trial in their OWN family's
        # subdirectory.
        assert report["n_scored"] == 2
        assert report["n_residual"] == 0
        assert report["n_unreconciled"] == 0
        assert report["n_fills"] == 2


class TestRunEmitsPerTrialBreakdown:
    """Stage C3, end to end: `_run()` wires the per-family scored-trial
    store into `trial_rows` with the correct `family_id` attribution -- not
    just `build_portfolio_roi_report_data` in isolation."""

    def test_the_written_report_carries_trial_rows_attributed_to_their_own_family(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        families_dir = tmp_path / "families"
        _write_family_manifest(families_dir, family_id="fam_a", trial_id_prefix="fam_a/trial/")
        _write_family_manifest(families_dir, family_id="fam_b", trial_id_prefix="fam_b/trial/")

        scored_trials_dir = tmp_path / "scored_trials"
        trial_a = _scored_trial(
            trial_id="fam_a/trial/LAX/2026-09-01", pnl=Decimal("0.10"), climate_day="2026-09-01"
        )
        trial_b = _scored_trial(
            trial_id="fam_b/trial/LAX/2026-09-02", pnl=Decimal("0.20"), climate_day="2026-09-02"
        )
        write_scored_trials(scored_trials_dir / "fam_a", [trial_a], now_ns=1)
        write_scored_trials(scored_trials_dir / "fam_b", [trial_b], now_ns=2)

        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            fill_scored_a = _fill(venue_order_id="vo-a", ts_event=_ns_of_day("2026-09-01"))
            fill_scored_b = _fill(venue_order_id="vo-b", ts_event=_ns_of_day("2026-09-02"))
            store.set(f"{_FILL_KEY_PREFIX}vo-a", fill_scored_a.to_bytes())
            store.set(f"{_FILL_KEY_PREFIX}vo-b", fill_scored_b.to_bytes())
        finally:
            store.close()

        reader = _stub_reader(
            {
                ("fam_a/trial/", "LAX"): (
                    (),
                    {"fam_a/trial/LAX/2026-09-01": (True, "vo-a", False)},
                ),
                ("fam_b/trial/", "LAX"): (
                    (),
                    {"fam_b/trial/LAX/2026-09-02": (True, "vo-b", False)},
                ),
            }
        )
        monkeypatch.setattr(_prr, "read_filled_trials_state_db", reader)

        exit_code = _run(
            exec_state_db_path=store_path,
            scored_trials_dir=scored_trials_dir,
            logs_dir=tmp_path / "logs",
            output_dir=tmp_path / "derived",
            families_dir=families_dir,
            now_ns=_ns_of_day("2026-09-05"),
            sink=_prr.resolve_alert_sink({}),
        )

        assert exit_code == 0
        report = json.loads(
            (tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-05.json").read_text()
        )
        assert report["trial_rows"] == [
            {
                "trial_id": "fam_a/trial/LAX/2026-09-01",
                "family_id": "fam_a",
                "climate_day": "2026-09-01",
                "side": "yes",
                "pnl": "0.10",
                "settlement_basis": "nws_final",
            },
            {
                "trial_id": "fam_b/trial/LAX/2026-09-02",
                "family_id": "fam_b",
                "climate_day": "2026-09-02",
                "side": "yes",
                "pnl": "0.20",
                "settlement_basis": "nws_final",
            },
        ]
        pnl_sum = sum((Decimal(row["pnl"]) for row in report["trial_rows"]), start=Decimal(0))
        assert str(pnl_sum) == report["realised_pnl_after_fees_total"]

        view = read_portfolio_roi_report(
            tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-05.json"
        )
        assert view.trial_rows is not None
        assert {row.trial_id for row in view.trial_rows} == {
            "fam_a/trial/LAX/2026-09-01",
            "fam_b/trial/LAX/2026-09-02",
        }


class TestRunDefect2ScheduledReleaseIsApplied:
    def test_a_recently_filled_trial_inside_its_real_horizon_is_not_flagged_unsettled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        families_dir = tmp_path / "families"
        _write_family_manifest(families_dir, family_id="fam_a", trial_id_prefix="fam_a/trial/")

        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            fill = _fill(venue_order_id="vo-a", ts_event=_ns_of_day("2026-09-01"))
            store.set(f"{_FILL_KEY_PREFIX}vo-a", fill.to_bytes())
        finally:
            store.close()

        now_ns = _ns_of_day("2026-09-02")  # one day after the fill -- inside any real horizon
        # A raw FilledTrial the way `read_filled_trials_state_db` documents
        # its OWN return contract: `scheduled_release_at_ns=0` is the
        # PLACEHOLDER every caller other than this (pre-fix) one replaces.
        placeholder_trial = FilledTrial(
            trial_id="fam_a/trial/LAX/2026-09-01",
            station="LAX",
            climate_day="2026-09-01",
            instrument_id="LAX-92-94.POLYMARKET_US",
            bucket=None,
            fill_px=Decimal("0.40"),
            fee=Decimal("0.03"),
            qty=Decimal(1),
            filled_at_ns=_ns_of_day("2026-09-01"),
            entry_ask=Decimal("0.40"),
            scheduled_release_at_ns=0,
        )
        reader = _stub_reader({("fam_a/trial/", "LAX"): ((placeholder_trial,), {})})
        monkeypatch.setattr(_prr, "read_filled_trials_state_db", reader)

        real_deadline_ns = now_ns + 30 * 24 * 60 * 60 * 1_000_000_000  # comfortably in the future
        monkeypatch.setattr(
            _prr,
            "_with_scheduled_release_at_ns",
            lambda trial, *, venue, city: FilledTrial(
                trial_id=trial.trial_id,
                station=trial.station,
                climate_day=trial.climate_day,
                instrument_id=trial.instrument_id,
                bucket=trial.bucket,
                fill_px=trial.fill_px,
                fee=trial.fee,
                qty=trial.qty,
                filled_at_ns=trial.filled_at_ns,
                entry_ask=trial.entry_ask,
                scheduled_release_at_ns=real_deadline_ns,
            ),
        )

        exit_code = _run(
            exec_state_db_path=store_path,
            scored_trials_dir=tmp_path / "scored_trials",
            logs_dir=tmp_path / "logs",
            output_dir=tmp_path / "derived",
            families_dir=families_dir,
            now_ns=now_ns,
            sink=_prr.resolve_alert_sink({}),
        )

        assert exit_code == 0
        report = json.loads(
            (tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-02.json").read_text()
        )
        # Pre-fix: scheduled_release_at_ns stays 0 -> every trial is always
        # "past horizon" -> roi_status is GATED even one day after the fill.
        assert report["unsettled_capital_positions"] == 0
        assert report["roi_status"] == _prr.ROI_STATUS_OK


class TestRunDefect3RefusalIsLoggedAndCounted:
    def test_a_refused_family_station_pair_is_logged_and_counted_not_silently_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        families_dir = tmp_path / "families"
        _write_family_manifest(
            families_dir, family_id="fam_broken", trial_id_prefix="fam_broken/trial/"
        )

        store_path = tmp_path / "state.db"
        SqliteStateStore(store_path).close()  # empty but openable ledger

        # No fixture entry for ("fam_broken/trial/", "LAX") -> the stub
        # raises FillSourceUnreadableError, exactly one of the three
        # refused exception types both loops already catch.
        reader = _stub_reader({})
        monkeypatch.setattr(_prr, "read_filled_trials_state_db", reader)

        with caplog.at_level("WARNING"):
            exit_code = _run(
                exec_state_db_path=store_path,
                scored_trials_dir=tmp_path / "scored_trials",
                logs_dir=tmp_path / "logs",
                output_dir=tmp_path / "derived",
                families_dir=families_dir,
                now_ns=_ns_of_day("2026-09-05"),
                sink=_prr.resolve_alert_sink({}),
            )

        assert exit_code == 0
        # F8 fix: attribution and the D9 scan now share ONE enumeration pass
        # (see TestF8SharedFamilyStationEnumeration), so the single broken
        # (family, station) pair is refused and counted exactly once, not
        # twice as it was pre-fix.
        report = json.loads(
            (tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-05.json").read_text()
        )
        assert report["n_family_station_refusals"] == 1
        messages = [r.getMessage() for r in caplog.records]
        assert any("FillSourceUnreadableError" in m for m in messages)
        assert any("fam_broken" in m and "LAX" in m for m in messages)
        # The exception's own detail string is never logged (invariant:
        # only the type name).
        assert not any("no fixture data" in m for m in messages)


class TestAdditiveSchemaFieldBackwardCompat:
    def test_a_pre_existing_json_sibling_without_the_new_field_reads_as_zero(
        self, tmp_path: Path
    ) -> None:
        """§6 D7: 'additive-only within a major version' -- a JSON sibling
        written before `n_family_station_refusals` existed has no such key
        and must still read under the current schema_version, defaulting to
        0. (Stage C3 bumps `PORTFOLIO_ROI_SCHEMA_VERSION` to 2 for the
        UNRELATED `trial_rows` field -- this field's own additive-within-
        version contract is otherwise unchanged.)"""
        data = _report_data()
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        del raw["n_family_station_refusals"]
        path.write_text(json.dumps(raw))

        view = read_portfolio_roi_report(path)
        assert view.schema_version == PORTFOLIO_ROI_SCHEMA_VERSION == 2
        assert view.n_family_station_refusals == 0

    def test_the_journal_line_carries_the_new_dimensionless_count(self) -> None:
        data = _report_data()
        line = journal_line(data)
        assert "n_family_station_refusals=" in line
        assert "$" not in line


# ===========================================================================
# REVIEW-FIX stage (F1-F9): three independent reviews' VERIFIED findings.
# ===========================================================================


class TestF1CumulativeReconciliationReachesTheArtefact:
    """F1: `cumulative_reconciliation()`'s own fields never reached
    `PortfolioRoiReportData`/JSON/Markdown/journal, and the plan's per-day
    `UNEXPLAINED_CAPITAL_FLOW day=<d> magnitude_cents=<...>` line was never
    emitted anywhere."""

    def test_the_report_data_carries_the_settled_window_verdict_and_magnitudes(self) -> None:
        data = _report_data()
        assert hasattr(data, "settled_cumulative_unexplained")
        assert hasattr(data, "provisional_cumulative_unexplained")
        assert hasattr(data, "settled_cumulative_passes")

    def test_the_json_sibling_carries_the_cumulative_verdict_and_per_day_table(
        self, tmp_path: Path
    ) -> None:
        data = dataclasses.replace(
            _report_data(),
            settled_cumulative_unexplained=Decimal("0.02"),
            provisional_cumulative_unexplained=Decimal("1.00"),
            settled_cumulative_passes=False,
            daily_reconciliation=(
                _prr.DailyUnexplainedSummaryRow(
                    day="2026-01-02",
                    classification=UNEXPLAINED_CAPITAL_FLOW_LABEL,
                    magnitude_cents=2,
                    provisional=False,
                ),
            ),
        )
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())

        assert raw["settled_cumulative_unexplained"] == "0.02"
        assert raw["provisional_cumulative_unexplained"] == "1.00"
        assert raw["settled_cumulative_passes"] is False
        assert raw["daily_reconciliation"] == [
            {
                "day": "2026-01-02",
                "classification": UNEXPLAINED_CAPITAL_FLOW_LABEL,
                "magnitude_cents": 2,
                "provisional": False,
            }
        ]
        # These fields are additive-within-version (D7); the schema_version
        # bump to 2 is unrelated (Stage C3's `trial_rows` field).
        assert raw["schema_version"] == PORTFOLIO_ROI_SCHEMA_VERSION == 2

        view = read_portfolio_roi_report(path)
        assert view.settled_cumulative_passes is False

    def test_the_markdown_report_prints_the_per_day_unexplained_capital_flow_line(self) -> None:
        data = dataclasses.replace(
            _report_data(),
            settled_cumulative_unexplained=Decimal("0.02"),
            provisional_cumulative_unexplained=Decimal("0.00"),
            settled_cumulative_passes=False,
            daily_reconciliation=(
                _prr.DailyUnexplainedSummaryRow(
                    day="2026-01-02",
                    classification=UNEXPLAINED_CAPITAL_FLOW_LABEL,
                    magnitude_cents=2,
                    provisional=False,
                ),
            ),
        )
        report = render_markdown_report(data)

        assert "UNEXPLAINED_CAPITAL_FLOW day=2026-01-02 magnitude_cents=2" in report
        assert "settled_cumulative_unexplained" in report
        assert "settled_cumulative_passes" in report

    def test_the_journal_line_carries_the_verdict_and_counts_but_never_a_magnitude(self) -> None:
        data = dataclasses.replace(
            _report_data(),
            settled_cumulative_unexplained=Decimal("0.02"),
            settled_cumulative_passes=False,
        )
        line = journal_line(data)

        assert "settled_reconciliation_passes=False" in line
        # Never a magnitude/Decimal-shaped figure in the journal line (D6).
        assert not re.search(r"\d+\.\d+", line)
        assert "$" not in line


class TestF2SplitCapitalFlowVsProxyLagCounts:
    def test_capital_flow_and_proxy_lag_days_are_counted_separately(self) -> None:
        data = _report_data(
            n_unexplained_capital_flow_days=1, n_unexplained_proxy_lag_days=2
        )
        assert data.n_unexplained_capital_flow_days == 1
        assert data.n_unexplained_proxy_lag_days == 2
        # Backward-compatible: the old conflated field is still populated.
        assert data.unexplained_flow_days == 0  # unchanged default in _report_data()

        line = journal_line(data)
        assert "n_unexplained_capital_flow_days=1" in line
        assert "n_unexplained_proxy_lag_days=2" in line


class TestF3BalanceHolesAreUnknownNotZero:
    def test_a_fill_opened_on_a_hole_day_is_classified_balance_unknown(self) -> None:
        open_day = "2026-03-02"
        resume_day = "2026-03-03"
        daily_balances = {
            "2026-03-01": Decimal("100.00"),
            resume_day: Decimal("99.57"),
        }
        fill = _fill(
            ts_event=_ns_of_day(open_day),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )

        rows = reconcile_daily(fills=[fill], scored_trials=[], daily_balances=daily_balances)
        rows_by_day = {r.day: r for r in rows}

        unknown_row = rows_by_day[open_day]
        assert unknown_row.classification == BALANCE_UNKNOWN_LABEL
        assert unknown_row.delta_balance is None
        assert unknown_row.unexplained is None
        assert unknown_row.breaches_tolerance is False

        resolved_row = rows_by_day[resume_day]
        assert resolved_row.spans_hole is True
        assert resolved_row.window_start_day == open_day
        assert resolved_row.unexplained == Decimal("0.00")
        assert resolved_row.classification == UNEXPLAINED_OK_LABEL

        cumulative = cumulative_reconciliation(daily_rows=rows, settled_through=resume_day)
        assert cumulative.settled_cumulative_passes is True
        assert cumulative.n_balance_unknown_days == 1
        # The unknown day's (indeterminate) contribution never enters the sum.
        assert cumulative.settled_cumulative_unexplained == Decimal("0.00")

    def test_a_multi_day_hole_is_not_silently_attributed_to_a_single_day(self) -> None:
        daily_balances = {
            "2026-04-01": Decimal("100.00"),
            "2026-04-04": Decimal("99.20"),
        }
        fill_a = _fill(
            venue_order_id="vo-a",
            ts_event=_ns_of_day("2026-04-02"),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        fill_b = _fill(
            venue_order_id="vo-b",
            ts_event=_ns_of_day("2026-04-03"),
            cumulative_cost=Decimal("0.35"),
            cumulative_fee=Decimal("0.02"),
        )

        rows = reconcile_daily(
            fills=[fill_a, fill_b], scored_trials=[], daily_balances=daily_balances
        )
        rows_by_day = {r.day: r for r in rows}

        assert rows_by_day["2026-04-02"].classification == BALANCE_UNKNOWN_LABEL
        assert rows_by_day["2026-04-03"].classification == BALANCE_UNKNOWN_LABEL

        resolved = rows_by_day["2026-04-04"]
        assert resolved.spans_hole is True
        assert resolved.window_start_day == "2026-04-02"
        assert resolved.capital_deployed == (
            Decimal("0.40") + Decimal("0.03") + Decimal("0.35") + Decimal("0.02")
        )
        assert resolved.delta_balance == Decimal("-0.80")
        assert resolved.unexplained == Decimal("0.00")
        assert resolved.classification == UNEXPLAINED_OK_LABEL

        cumulative = cumulative_reconciliation(daily_rows=rows, settled_through="2026-04-04")
        assert cumulative.n_balance_unknown_days == 2

    def test_worked_example_and_prior_fixtures_are_unaffected_by_the_hole_fix(self) -> None:
        """Regression guard: the F3 windowing change must not alter any
        already-passing identity when there is no hole at all."""
        open_fill = _fill(
            venue_order_id="vo-open",
            ts_event=_ns_of_day("2026-01-02"),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        settled_trial = _scored_trial(
            trial_id="t-1",
            pnl=Decimal("0.57"),
            held=True,
            climate_day="2026-01-02",
            scored_at_ns=_ns_of_day("2026-01-06"),
        )
        daily_balances = {
            "2026-01-01": Decimal("100.00"),
            "2026-01-02": Decimal("99.57"),
            "2026-01-03": Decimal("99.57"),
            "2026-01-04": Decimal("99.57"),
            "2026-01-05": Decimal("99.57"),
            "2026-01-06": Decimal("100.57"),
        }
        rows = reconcile_daily(
            fills=[open_fill], scored_trials=[settled_trial], daily_balances=daily_balances
        )
        rows_by_day = {row.day: row for row in rows}
        assert rows_by_day["2026-01-02"].unexplained == Decimal("0.00")
        assert rows_by_day["2026-01-02"].spans_hole is False
        assert rows_by_day["2026-01-06"].unexplained == Decimal("0.00")


class TestF4LedgerPartitionIsAssertedNotTautological:
    def test_read_ledger_fills_with_counts_reports_raw_and_undecodable(
        self, tmp_path: Path
    ) -> None:
        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            good = _fill(venue_order_id="vo-good")
            store.set(f"{_FILL_KEY_PREFIX}vo-good", good.to_bytes())
            store.set(f"{_FILL_KEY_PREFIX}vo-bad", b"not a fill record")
        finally:
            store.close()

        result = read_ledger_fills_with_counts(store_path)

        assert result is not None
        assert len(result.fills) == 1
        assert result.n_ledger_rows == 2
        assert result.n_undecodable_ledger_rows == 1

    def test_read_ledger_fills_with_counts_is_none_on_absent_store(self, tmp_path: Path) -> None:
        assert read_ledger_fills_with_counts(tmp_path / "missing.sqlite") is None

    def test_assert_ledger_partition_passes_when_consistent(self) -> None:
        fill = _fill(venue_order_id="vo-1")
        result = LedgerReadResult(fills=(fill,), n_ledger_rows=1, n_undecodable_ledger_rows=0)
        buckets = {
            FillBucket.SCORED: (AttributedFill(fill=fill, trial_id="t-1"),),
            FillBucket.RESIDUAL: (),
            FillBucket.UNRECONCILED: (),
        }
        assert_ledger_partition(ledger_result=result, buckets=buckets)  # does not raise

    def test_assert_ledger_partition_raises_on_bucket_mismatch(self) -> None:
        fill = _fill(venue_order_id="vo-1")
        result = LedgerReadResult(fills=(fill,), n_ledger_rows=1, n_undecodable_ledger_rows=0)
        buckets = {FillBucket.SCORED: (), FillBucket.RESIDUAL: (), FillBucket.UNRECONCILED: ()}
        with pytest.raises(LedgerPartitionViolationError):
            assert_ledger_partition(ledger_result=result, buckets=buckets)

    def test_assert_ledger_partition_raises_on_raw_decoded_undecodable_mismatch(self) -> None:
        fill = _fill(venue_order_id="vo-1")
        # Deliberately inconsistent construction (never produced by the real
        # reader): raw=5 but decoded(1)+undecodable(1) == 2.
        result = LedgerReadResult(fills=(fill,), n_ledger_rows=5, n_undecodable_ledger_rows=1)
        buckets = {
            FillBucket.SCORED: (AttributedFill(fill=fill, trial_id="t-1"),),
            FillBucket.RESIDUAL: (),
            FillBucket.UNRECONCILED: (),
        }
        with pytest.raises(LedgerPartitionViolationError):
            assert_ledger_partition(ledger_result=result, buckets=buckets)


class TestF5OrderSideBranchesCapitalDeployed:
    def test_a_sell_exit_fill_is_not_double_counted_as_capital_deployed(self) -> None:
        buy_fill = _fill(
            venue_order_id="vo-open", order_side="BUY",
            cumulative_cost=Decimal("0.40"), cumulative_fee=Decimal("0.03"),
        )
        sell_exit = _fill(
            venue_order_id="vo-exit", order_side="SELL",
            cumulative_cost=Decimal("0.90"), cumulative_fee=Decimal("0.02"),
        )

        assert fill_side_label(buy_fill) == "BUY"
        assert fill_side_label(sell_exit) == "SELL"

        # The exit's cash is never folded into capital deployed.
        total = total_capital_deployed([buy_fill, sell_exit])
        assert total == Decimal("0.43")

        by_day = _prr.capital_deployed_by_day([buy_fill, sell_exit])
        assert sum(by_day.values(), start=Decimal(0)) == Decimal("0.43")

    def test_a_no_leg_buy_is_still_capital_deployed(self) -> None:
        no_leg_buy = _fill(
            venue_order_id="vo-no", order_side="BUY",
            instrument_id="LAX-92-94^no.POLYMARKET_US",
            cumulative_cost=Decimal("0.35"), cumulative_fee=Decimal("0.02"),
        )
        assert total_capital_deployed([no_leg_buy]) == Decimal("0.37")

    def test_an_unrecognised_order_side_fails_loud(self) -> None:
        weird = _fill(venue_order_id="vo-weird", order_side="BUY_SHORT")
        with pytest.raises(UnknownOrderSideError):
            fill_side_label(weird)
        with pytest.raises(UnknownOrderSideError):
            total_capital_deployed([weird])

    def test_a_sell_exit_is_labelled_unreconciled_exit_and_excluded_from_roi(self) -> None:
        """The record does not let this reader independently verify the fee
        sign / cash-proceeds semantics of a SELL exit (F5's documented
        fallback), so it is conservatively excluded from capital_deployed
        AND never guessed into `proceeds`, counted only in the dimensionless
        `n_exit_fills`."""
        sell_exit = _fill(venue_order_id="vo-exit", order_side="SELL")
        assert _prr.exit_label_for_fill(sell_exit) == UNRECONCILED_EXIT_LABEL


class TestF6PowerCaveatIsTruthful:
    def test_the_power_caveat_names_ledger_fills_and_scored_fills_separately(self) -> None:
        caveat = power_caveat(n_ledger_fills=6, n_scored=4, days=10)
        assert "n_ledger_fills=6" in caveat
        assert "n_scored" in caveat
        assert "n=6 settled fills" not in caveat


class TestF7AtomicReportWrites:
    def test_a_failed_write_leaves_no_partial_file_and_preserves_a_pre_existing_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "report.json"
        original = _report_data()
        write_portfolio_roi_json(path, original)
        original_bytes = path.read_bytes()

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated failure")

        monkeypatch.setattr(_prr.os, "replace", _boom)

        updated = _report_data(n_fills=99)
        with pytest.raises(OSError):
            write_portfolio_roi_json(path, updated)

        assert path.read_bytes() == original_bytes
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".portfolio-roi-")]
        assert leftovers == []


class TestF8SharedFamilyStationEnumeration:
    def test_the_shared_enumerator_is_called_once_and_refusals_count_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        families_dir = tmp_path / "families"
        _write_family_manifest(
            families_dir, family_id="fam_broken", trial_id_prefix="fam_broken/trial/"
        )
        store_path = tmp_path / "state.db"
        SqliteStateStore(store_path).close()

        reader = _stub_reader({})
        monkeypatch.setattr(_prr, "read_filled_trials_state_db", reader)

        with caplog.at_level("WARNING"):
            exit_code = _run(
                exec_state_db_path=store_path,
                scored_trials_dir=tmp_path / "scored_trials",
                logs_dir=tmp_path / "logs",
                output_dir=tmp_path / "derived",
                families_dir=families_dir,
                now_ns=_ns_of_day("2026-09-05"),
                sink=_prr.resolve_alert_sink({}),
            )
        assert exit_code == 0
        report = json.loads(
            (tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-05.json").read_text()
        )
        # Post-F8-fix: ONE enumeration pass -> exactly one refusal, not two.
        assert report["n_family_station_refusals"] == 1


class TestF9ReaderTypeValidation:
    def test_a_wrong_typed_field_raises_a_clear_error(self, tmp_path: Path) -> None:
        data = _report_data()
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        raw["n_fills"] = "six"  # wrong type
        path.write_text(json.dumps(raw))

        with pytest.raises(PortfolioRoiReportMalformedFieldError):
            read_portfolio_roi_report(path)

    def test_the_redundant_output_dir_mkdir_is_gone_and_run_still_creates_it(
        self, tmp_path: Path
    ) -> None:
        """F9: `_run`'s own explicit `output_dir.mkdir()` call is removed;
        the atomic writers create the directory themselves, so `_run` must
        still succeed against a not-yet-existing `output_dir`."""
        store_path = tmp_path / "state.db"
        SqliteStateStore(store_path).close()
        exit_code = _run(
            exec_state_db_path=store_path,
            scored_trials_dir=tmp_path / "scored_trials",
            logs_dir=tmp_path / "logs",
            output_dir=tmp_path / "derived" / "nested",
            families_dir=tmp_path / "families",
            now_ns=_ns_of_day("2026-09-05"),
            sink=_prr.resolve_alert_sink({}),
        )
        assert exit_code == 0
        assert (tmp_path / "derived" / "nested" / "PRIVATE_portfolio_roi_2026-09-05.json").exists()


# ===========================================================================
# Independent re-review fix stage (G1-G4).
# ===========================================================================


class TestG1OpeningDayHasNoPriorBalance:
    """G1: the earliest known-balance day of the whole series was silently
    unreconciled -- never a window end (no previous known day) and never
    `BALANCE_UNKNOWN` (its own balance IS known), so its capital/proceeds
    were computed but landed in no row at all."""

    def test_a_fill_on_the_earliest_known_balance_day_gets_a_no_prior_balance_row(
        self,
    ) -> None:
        opening_day = "2026-05-01"
        daily_balances = {opening_day: Decimal("100.00")}
        fill = _fill(
            ts_event=_ns_of_day(opening_day),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )

        rows = reconcile_daily(fills=[fill], scored_trials=[], daily_balances=daily_balances)
        rows_by_day = {r.day: r for r in rows}

        assert opening_day in rows_by_day, "the opening day was dropped entirely"
        opening_row = rows_by_day[opening_day]
        assert opening_row.classification == NO_PRIOR_BALANCE_LABEL
        assert opening_row.delta_balance is None
        assert opening_row.unexplained is None
        assert opening_row.breaches_tolerance is False
        assert opening_row.capital_deployed == Decimal("0.43")

        cumulative = cumulative_reconciliation(daily_rows=rows, settled_through=opening_day)
        assert cumulative.n_no_prior_balance_days == 1
        # Excluded from the cumulative sum, exactly like BALANCE_UNKNOWN.
        assert cumulative.settled_cumulative_unexplained == Decimal("0.00")
        assert cumulative.settled_cumulative_passes is True

    def test_a_genuine_earlier_balance_resolves_the_reports_first_day_normally(self) -> None:
        """The second branch: when a prior balance IS available for the
        report's own first day (here, supplied directly in
        `daily_balances` -- the pure function does not care whether the
        caller found it via `_run`'s log look-back or any other means),
        THAT day reconciles as an ordinary window row, never
        `NO_PRIOR_BALANCE`. The even-earlier day supplying the prior
        balance is, by construction, always the new series minimum and so
        is itself flagged `NO_PRIOR_BALANCE` -- exactly what `_run`'s own
        look-back wiring filters back out before it ever reaches the
        report (see `TestG1RunLooksBackForAPriorBalance`)."""
        even_earlier_day = "2026-04-30"
        opening_day = "2026-05-01"
        daily_balances = {
            even_earlier_day: Decimal("100.00"),
            opening_day: Decimal("99.57"),
        }
        fill = _fill(
            ts_event=_ns_of_day(opening_day),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )

        rows = reconcile_daily(fills=[fill], scored_trials=[], daily_balances=daily_balances)
        rows_by_day = {r.day: r for r in rows}

        opening_row = rows_by_day[opening_day]
        assert opening_row.classification == UNEXPLAINED_OK_LABEL
        assert opening_row.delta_balance == Decimal("-0.43")
        assert opening_row.unexplained == Decimal("0.00")

        cumulative = cumulative_reconciliation(daily_rows=rows, settled_through=opening_day)
        # Only the even-earlier anchor day is flagged -- never the report's
        # own opening day, which is the point of this test.
        assert cumulative.n_no_prior_balance_days == 1
        assert rows_by_day[even_earlier_day].classification == NO_PRIOR_BALANCE_LABEL

    def test_the_json_and_markdown_and_journal_carry_the_new_dimensionless_count(
        self, tmp_path: Path
    ) -> None:
        data = dataclasses.replace(_report_data(), n_no_prior_balance_days=1)
        line = journal_line(data)
        assert "n_no_prior_balance_days=1" in line
        assert not re.search(r"\d+\.\d+", line)

        report = render_markdown_report(data)
        assert "n_no_prior_balance_days" in report

        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        assert raw["n_no_prior_balance_days"] == 1
        view = read_portfolio_roi_report(path)
        assert view.n_no_prior_balance_days == 1

    def test_an_old_json_sibling_without_the_field_reads_as_zero(self, tmp_path: Path) -> None:
        data = _report_data()
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        del raw["n_no_prior_balance_days"]
        path.write_text(json.dumps(raw))

        view = read_portfolio_roi_report(path)
        assert view.n_no_prior_balance_days == 0


class TestG1LookbackHelper:
    def test_finds_the_latest_point_strictly_before_the_given_day_within_bound(self) -> None:
        lines = [
            _REAL_ACCOUNT_STATE_LINE.replace(
                "2026-09-21T16:50:57.980817596Z", "2026-09-18T16:50:57.980817596Z"
            ).replace("total=100.00 USD", "total=140.00 USD"),
            _REAL_ACCOUNT_STATE_LINE.replace(
                "2026-09-21T16:50:57.980817596Z", "2026-09-19T16:50:57.980817596Z"
            ).replace("total=100.00 USD", "total=139.50 USD"),
        ]
        point = _latest_balance_before(
            lines, before_day="2026-09-21", max_lookback_days=OPENING_BALANCE_LOOKBACK_DAYS
        )
        assert point is not None
        assert point.ts_iso.startswith("2026-09-19")
        assert point.total_usd == Decimal("139.50")

    def test_returns_none_when_nothing_is_found_within_the_bound(self) -> None:
        old_line = _REAL_ACCOUNT_STATE_LINE.replace(
            "2026-09-21T16:50:57.980817596Z", "2026-09-01T16:50:57.980817596Z"
        )
        point = _latest_balance_before(
            [old_line], before_day="2026-09-21", max_lookback_days=OPENING_BALANCE_LOOKBACK_DAYS
        )
        assert point is None

    def test_returns_none_when_no_line_is_before_the_day(self) -> None:
        same_day_line = _REAL_ACCOUNT_STATE_LINE  # 2026-09-21, not strictly before itself
        point = _latest_balance_before(
            [same_day_line],
            before_day="2026-09-21",
            max_lookback_days=OPENING_BALANCE_LOOKBACK_DAYS,
        )
        assert point is None


class TestG1RunLooksBackForAPriorBalance:
    def test_run_resolves_the_opening_day_using_an_earlier_log_line(
        self, tmp_path: Path
    ) -> None:
        """`_run`'s own look-back branch: a genuine `AccountState(` line
        from before the first fill lets the opening day reconcile normally
        instead of falling back to `NO_PRIOR_BALANCE`."""
        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            fill = _fill(venue_order_id="vo-a", ts_event=_ns_of_day("2026-09-05"))
            store.set(f"{_FILL_KEY_PREFIX}vo-a", fill.to_bytes())
        finally:
            store.close()

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        prior_line = _REAL_ACCOUNT_STATE_LINE.replace(
            "2026-09-21T16:50:57.980817596Z", "2026-09-04T00:00:00.000000000Z"
        )
        opening_line = _REAL_ACCOUNT_STATE_LINE.replace(
            "2026-09-21T16:50:57.980817596Z", "2026-09-05T00:00:00.000000000Z"
        ).replace("total=100.00 USD", "total=99.57 USD")
        (logs_dir / "breezy-trade-20260905T000000Z.log").write_text(
            prior_line + "\n" + opening_line + "\n"
        )

        exit_code = _run(
            exec_state_db_path=store_path,
            scored_trials_dir=tmp_path / "scored_trials",
            logs_dir=logs_dir,
            output_dir=tmp_path / "derived",
            families_dir=tmp_path / "families",
            now_ns=_ns_of_day("2026-09-05"),
            sink=_prr.resolve_alert_sink({}),
        )

        assert exit_code == 0
        report = json.loads(
            (tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-05.json").read_text()
        )
        assert report["n_no_prior_balance_days"] == 0
        opening_rows = [
            row
            for row in report["daily_reconciliation"]
            if row["day"] == "2026-09-05"
        ]
        assert opening_rows and opening_rows[0]["classification"] != NO_PRIOR_BALANCE_LABEL

    def test_run_falls_back_to_no_prior_balance_when_no_earlier_line_exists(
        self, tmp_path: Path
    ) -> None:
        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            fill = _fill(venue_order_id="vo-a", ts_event=_ns_of_day("2026-09-05"))
            store.set(f"{_FILL_KEY_PREFIX}vo-a", fill.to_bytes())
        finally:
            store.close()

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        opening_line = _REAL_ACCOUNT_STATE_LINE.replace(
            "2026-09-21T16:50:57.980817596Z", "2026-09-05T00:00:00.000000000Z"
        ).replace("total=100.00 USD", "total=99.57 USD")
        (logs_dir / "breezy-trade-20260905T000000Z.log").write_text(opening_line + "\n")

        exit_code = _run(
            exec_state_db_path=store_path,
            scored_trials_dir=tmp_path / "scored_trials",
            logs_dir=logs_dir,
            output_dir=tmp_path / "derived",
            families_dir=tmp_path / "families",
            now_ns=_ns_of_day("2026-09-05"),
            sink=_prr.resolve_alert_sink({}),
        )

        assert exit_code == 0
        report = json.loads(
            (tmp_path / "derived" / "PRIVATE_portfolio_roi_2026-09-05.json").read_text()
        )
        assert report["n_no_prior_balance_days"] == 1


class TestG2DailyReconciliationExposedOnTheView:
    def test_round_trips_through_the_sanctioned_reader(self, tmp_path: Path) -> None:
        data = dataclasses.replace(
            _report_data(),
            daily_reconciliation=(
                DailyUnexplainedSummaryRow(
                    day="2026-01-02",
                    classification=UNEXPLAINED_CAPITAL_FLOW_LABEL,
                    magnitude_cents=2,
                    provisional=False,
                ),
            ),
        )
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)

        view = read_portfolio_roi_report(path)

        assert view.daily_reconciliation == (
            DailyUnexplainedSummaryRow(
                day="2026-01-02",
                classification=UNEXPLAINED_CAPITAL_FLOW_LABEL,
                magnitude_cents=2,
                provisional=False,
            ),
        )

    def test_absent_on_an_old_json_sibling_reads_as_an_empty_tuple(self, tmp_path: Path) -> None:
        data = _report_data()
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        del raw["daily_reconciliation"]
        path.write_text(json.dumps(raw))

        view = read_portfolio_roi_report(path)
        assert view.daily_reconciliation == ()

    def test_a_wrong_typed_row_raises_the_malformed_field_error(self, tmp_path: Path) -> None:
        data = dataclasses.replace(
            _report_data(),
            daily_reconciliation=(
                DailyUnexplainedSummaryRow(
                    day="2026-01-02",
                    classification=UNEXPLAINED_CAPITAL_FLOW_LABEL,
                    magnitude_cents=2,
                    provisional=False,
                ),
            ),
        )
        path = tmp_path / "report.json"
        write_portfolio_roi_json(path, data)
        raw = json.loads(path.read_text())
        raw["daily_reconciliation"][0]["magnitude_cents"] = "two"
        path.write_text(json.dumps(raw))

        with pytest.raises(PortfolioRoiReportMalformedFieldError):
            read_portfolio_roi_report(path)


class TestG3UnknownOrderSideFailsLoudFromRun:
    def test_run_reports_the_error_type_and_venue_order_id_writes_no_report_and_exits_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store_path = tmp_path / "state.db"
        store = SqliteStateStore(store_path)
        try:
            weird = _fill(venue_order_id="vo-weird", order_side="BUY_SHORT")
            store.set(f"{_FILL_KEY_PREFIX}vo-weird", weird.to_bytes())
        finally:
            store.close()

        output_dir = tmp_path / "derived"
        exit_code = _run(
            exec_state_db_path=store_path,
            scored_trials_dir=tmp_path / "scored_trials",
            logs_dir=tmp_path / "logs",
            output_dir=output_dir,
            families_dir=tmp_path / "families",
            now_ns=_ns_of_day("2026-09-05"),
            sink=_prr.resolve_alert_sink({}),
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "UnknownOrderSideError" in captured.err
        assert "vo-weird" in captured.err
        # Never an amount/currency figure in this refusal line.
        assert "$" not in captured.err
        assert not output_dir.exists() or list(output_dir.iterdir()) == []


class TestG4NoFabricatedPlanQuotations:
    """G4: `exit_label_for_fill`'s docstring falsely attributed a quoted
    SELL-handling fallback to the plan. This pins the corrected, truthful
    content: no fabricated quotation, and the real plan sentence the module
    now cites verbatim."""

    def test_the_docstrings_no_longer_claim_a_plan_documented_sell_fallback(self) -> None:
        exit_docstring = _prr.exit_label_for_fill.__doc__ or ""
        assert "the plan's documented fallback" not in exit_docstring
        assert "the record does not let you determine it" not in exit_docstring

        module_source = Path(_prr.__file__).read_text()
        assert "a balance figure and an account id" not in module_source

    def test_the_module_cites_the_real_plan_sentence_verbatim(self) -> None:
        plan_path = (
            _REPO_ROOT
            / "docs"
            / "plans"
            / "backlog"
            / "AUDIT_2026-09-21"
            / "AUD-04-portfolio-roi-measurement.md"
        )
        plan_text = plan_path.read_text()
        quoted = "the live family never sells (G-12)"
        assert quoted in plan_text
        module_source = Path(_prr.__file__).read_text()
        assert quoted in module_source


def _ns_at(day: str, hour: int, minute: int = 0) -> int:
    """UTC instant on ``day`` at ``hour:minute``, in epoch nanoseconds."""
    return _ns_of(day, hour) + minute * 60 * 1_000_000_000


class TestSnapshotIntervalReconciliation:
    """Cash identity over (previous AccountState ts, this AccountState ts].

    A day-keyed balance with no timestamp still means end of that UTC day,
    which is what the pre-existing calendar-day fixtures encode. An explicit
    ``balance_timestamps_ns`` is the snapshot clock.
    """

    def test_a_fill_after_the_snapshot_lands_in_the_later_interval(self) -> None:
        """Fill at 18:00Z, snapshots at 16:50Z today and 16:50Z tomorrow.

        The 16:50Z print is before the fill, so today's interval must not
        book the capital. Both intervals reconcile to 0; capital is on the
        interval that closes tomorrow. The day-before 16:50Z print is only
        the prior anchor that gives today's interval a delta.
        """
        anchor = "2026-06-01"
        today = "2026-06-02"
        tomorrow = "2026-06-03"
        deployed = Decimal("0.43")
        fill = _fill(
            venue_order_id="vo-after-snapshot",
            ts_event=_ns_at(today, 18, 0),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        daily_balances = {
            anchor: Decimal("10.00"),
            today: Decimal("10.00"),
            tomorrow: Decimal("9.57"),
        }
        timestamps = {
            anchor: _ns_at(anchor, 16, 50),
            today: _ns_at(today, 16, 50),
            tomorrow: _ns_at(tomorrow, 16, 50),
        }

        rows = reconcile_daily(
            fills=[fill],
            scored_trials=[],
            daily_balances=daily_balances,
            balance_timestamps_ns=timestamps,
        )
        rows_by_day = {row.day: row for row in rows}

        assert rows_by_day[today].unexplained == Decimal("0.00")
        assert rows_by_day[tomorrow].unexplained == Decimal("0.00")
        assert rows_by_day[today].capital_deployed == Decimal("0.00")
        assert rows_by_day[tomorrow].capital_deployed == deployed
        assert rows_by_day[today].classification == UNEXPLAINED_OK_LABEL
        assert rows_by_day[tomorrow].classification == UNEXPLAINED_OK_LABEL

    def test_a_fill_exactly_at_the_closing_snapshot_ts_lands_in_that_interval(self) -> None:
        """(c) boundary: `(prev, this]` is inclusive at `this` -- a fill
        whose ts_event is EXACTLY the closing AccountState snapshot's ts is
        assigned to the interval that closes there, not the next one."""
        anchor = "2026-06-01"
        closing = "2026-06-02"
        closing_ts = _ns_at(closing, 16, 50)
        deployed = Decimal("0.43")
        fill = _fill(
            venue_order_id="vo-at-snapshot",
            ts_event=closing_ts,
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.03"),
        )
        daily_balances = {
            anchor: Decimal("10.00"),
            closing: Decimal("9.57"),
        }
        timestamps = {
            anchor: _ns_at(anchor, 16, 50),
            closing: closing_ts,
        }

        rows = reconcile_daily(
            fills=[fill],
            scored_trials=[],
            daily_balances=daily_balances,
            balance_timestamps_ns=timestamps,
        )
        row = next(r for r in rows if r.day == closing)

        assert row.capital_deployed == deployed
        assert row.unexplained == Decimal("0.00")
        assert row.classification == UNEXPLAINED_OK_LABEL

    def test_an_empty_interval_cash_jump_stays_unexplained_capital_flow(self) -> None:
        """A +40.00 balance jump with no fill and no settlement is still
        UNEXPLAINED_CAPITAL_FLOW for the full magnitude. Interval assignment
        must not swallow a real deposit."""
        opening = "2026-06-10"
        closing = "2026-06-11"
        daily_balances = {
            opening: Decimal("100.00"),
            closing: Decimal("140.00"),
        }
        timestamps = {
            opening: _ns_at(opening, 16, 50),
            closing: _ns_at(closing, 16, 50),
        }

        rows = reconcile_daily(
            fills=[],
            scored_trials=[],
            daily_balances=daily_balances,
            balance_timestamps_ns=timestamps,
        )
        row = next(r for r in rows if r.day == closing)

        assert row.capital_deployed == Decimal("0.00")
        assert row.proceeds == Decimal("0.00")
        assert row.unexplained == Decimal("40.00")
        assert row.breaches_tolerance is True
        assert row.classification == UNEXPLAINED_CAPITAL_FLOW_LABEL


class TestScoredTrialDedup:
    def test_two_rows_one_trial_id_book_payout_once(self) -> None:
        """One trial_id in two family stores must not double-count payout."""
        day = "2026-06-20"
        earlier = _scored_trial(
            trial_id="trial-shared",
            pnl=Decimal(1),
            fill_px=Decimal(0),
            fee=Decimal(0),
            climate_day="2026-06-18",
            scored_at_ns=_ns_at(day, 17, 0),
        )
        later = _scored_trial(
            trial_id="trial-shared",
            pnl=Decimal(1),
            fill_px=Decimal(0),
            fee=Decimal(0),
            climate_day="2026-06-18",
            scored_at_ns=_ns_at(day, 18, 0),
        )

        proceeds = _prr.proceeds_by_day((earlier, later))

        assert proceeds == {day: Decimal(1)}
        assert settlement_payout(later) == Decimal(1)

    def test_duplicate_count_keeps_the_latest_scored_at_ns(self) -> None:
        """Two rows sharing a trial_id that are the SAME trade (identical on
        every economic field) differ only in scored_at_ns -- the later row
        is kept. This must NOT be conflated with two rows that merely share
        a trial_id but disagree economically (see
        TestScoredTrialDedupRefusesEconomicMismatch below): that case is a
        refusal, never a pick."""
        day = "2026-06-20"
        earlier = _scored_trial(
            trial_id="trial-shared",
            pnl=Decimal(5),
            fill_px=Decimal(0),
            fee=Decimal(0),
            scored_at_ns=_ns_at(day, 17, 0),
        )
        later = _scored_trial(
            trial_id="trial-shared",
            pnl=Decimal(5),
            fill_px=Decimal(0),
            fee=Decimal(0),
            scored_at_ns=_ns_at(day, 18, 0),
        )

        kept, n_dup = _prr.dedupe_scored_trials((earlier, later))

        assert n_dup == 1
        assert len(kept) == 1
        assert kept[0].scored_at_ns == later.scored_at_ns
        assert settlement_payout(kept[0]) == Decimal(5)

    def test_identical_economics_are_collapsed_and_counted_once(self) -> None:
        """(b) Same trial_id, identical economics (differ only in
        scored_at_ns/provenance) -- collapsed, n_duplicate_scored_trials=1,
        proceeds counted once."""
        day = "2026-06-20"
        earlier = _scored_trial(
            trial_id="trial-shared",
            pnl=Decimal(1),
            fill_px=Decimal(0),
            fee=Decimal(0),
            climate_day="2026-06-18",
            scored_at_ns=_ns_at(day, 17, 0),
        )
        later = _scored_trial(
            trial_id="trial-shared",
            pnl=Decimal(1),
            fill_px=Decimal(0),
            fee=Decimal(0),
            climate_day="2026-06-18",
            scored_at_ns=_ns_at(day, 18, 0),
        )

        kept, n_dup = _prr.dedupe_scored_trials((earlier, later))
        proceeds = _prr.proceeds_by_day((earlier, later))

        assert n_dup == 1
        assert len(kept) == 1
        assert proceeds == {day: Decimal(1)}


class TestScoredTrialDedupRefusesEconomicMismatch:
    """(a) trial_id alone does not encode family (family_barrier.py:15-18):
    two DIFFERENT trades from two families can collide on trial_id. Rows
    that share a trial_id but disagree on an economic field must never be
    silently picked -- dedupe_scored_trials fails closed."""

    def test_different_pnl_under_the_same_trial_id_refuses(self) -> None:
        row_a = _scored_trial(trial_id="trial-shared", pnl=Decimal(1))
        row_b = _scored_trial(trial_id="trial-shared", pnl=Decimal(5))

        with pytest.raises(DuplicateScoredTrialEconomicsMismatchError) as exc_info:
            _prr.dedupe_scored_trials((row_a, row_b))

        assert "trial-shared" in str(exc_info.value)

    def test_the_summary_line_names_n_duplicate_scored_trials(self) -> None:
        data = dataclasses.replace(_report_data(), n_duplicate_scored_trials=1)
        line = journal_line(data)

        assert "n_duplicate_scored_trials=1" in line
        assert "$" not in line
        assert not re.search(r"\d+\.\d+", line)
