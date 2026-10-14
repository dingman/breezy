"""MAKER-S2 WP5 RED tests: frozen verdict table, S3 inputs, section 6.9 and rerun-from-CSV.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP5 (L173-190) + r4 delta
(a) V0/fitted ICC, (e) denominator, (f) s3_inputs.json, (g) CSV contract, (h) Test B, (i)4-(i)6.
Spec: docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md 6.0 (:211-230), 6.9 (:290-304).

Fixture geometry: 4 stations x ``n_dates`` dates, one posted position per station-day, so
n_eff_gov = n_dates * 4 / (1 + 3 * 0.5) = 1.6 * n_dates (floor 30 needs >= 19 dates).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_stats as st
from scripts.analysis import maker_stage0_tables as tb
from scripts.analysis import maker_stage0_verdict as vd
from scripts.analysis.maker_stage0_fill_events import StationDaySummary

STATIONS = ("LAX", "MDW", "MIA", "SFO")
HYP = "CONTRACTS"
THETA = 0.0695
BIDS = (0.72, 0.74, 0.76)
FIRST_DAY = dt.date(2026, 9, 1)


def day(i: int) -> str:
    return (FIRST_DAY + dt.timedelta(days=i)).isoformat()


def sd_row(
    station: str,
    climate_day: str,
    *,
    hyp: str = HYP,
    fb: int = 0,
    fs: int = 0,
    attempted: int = 1,
    **over: object,
) -> vd.SdRow:
    base: dict[str, object] = {
        "station": station,
        "climate_day": climate_day,
        "cluster_id": climate_day,
        "unit_hypothesis": hyp,
        "census_reason": "COVERED",
        "covered_bidlive": True,
        "covered": True,
        "outage_excluded": False,
        "node_log_absent": False,
        "bid_bearing": True,
        "guard_refused_only": False,
        "n_depth_frames": 10,
        "has_depth_frame": True,
        "n_attempts": 1,
        "rung_trials_attempted": attempted,
        "rung_trials_posted": attempted,
        "process_live_h": 10.0,
        "forecast_valid_h": 10.0,
        "gap_h": 0.0,
        "covered_live_h": 10.0,
        "gap_share": 0.0,
        "filled_pairs_base": fb,
        "filled_pairs_stress": fs,
        "k1_rung_id": "r1",
        "k1_filled_base": min(fb, 1),
        "k1_filled_stress": min(fs, 1),
        "nogo_driving": fs == 0,
        "positions_filled_k2_base": fb,
        "positions_filled_k2_stress": fs,
        "positions_filled_k1_base": min(fb, 1),
        "positions_filled_k1_stress": min(fs, 1),
        "delta_ns": 0,
        "truth_final": True,
        "theta": THETA,
        "n_no_book_wants": 0,
    }
    base.update(over)
    return vd.SdRow(**base)  # type: ignore[arg-type]


def pos_row(
    station: str,
    climate_day: str,
    *,
    hyp: str = HYP,
    filled_base: bool,
    filled_stress: bool,
    p: float,
    outcome: str,
    bid: float = 0.75,
    rung: str = "r1",
) -> vd.PosRow:
    return vd.PosRow(
        position_id=f"{station}|{climate_day}|{rung}",
        rung_trial_id=rung,
        station=station,
        climate_day=climate_day,
        unit_hypothesis=hyp,
        bid=bid,
        filled_base=filled_base,
        filled_stress=filled_stress,
        p_yes_point_live=p,
        truth_final=outcome,
    )


def scenario(
    *,
    hyp: str = HYP,
    n_dates: int = 20,
    fill_base: int = 40,
    fill_stress: int | None = None,
    p_f: float = 0.3,
    p_u: float = 0.3,
    loss_f: int = 5,
    loss_u: int = 3,
) -> tuple[list[vd.SdRow], list[vd.PosRow]]:
    """Station-day i = date-major; the first ``fill_base`` are filled (base), the rest unfilled."""
    stress_n = fill_base if fill_stress is None else fill_stress
    sds: list[vd.SdRow] = []
    poss: list[vd.PosRow] = []
    for i in range(n_dates * len(STATIONS)):
        station, d = STATIONS[i % 4], day(i // 4)
        fb, fs = int(i < fill_base), int(i < stress_n)
        sds.append(sd_row(station, d, hyp=hyp, fb=fb, fs=fs))
        filled = i < fill_base
        loss = (i < loss_f) if filled else (i - fill_base < loss_u)
        poss.append(
            pos_row(
                station,
                d,
                hyp=hyp,
                filled_base=bool(fb),
                filled_stress=bool(fs),
                p=p_f if filled else p_u,
                outcome="YES" if loss else "NO",
                bid=BIDS[i % 3],
            )
        )
    return sds, poss


def analyse(
    parts: Sequence[tuple[list[vd.SdRow], list[vd.PosRow]]],
) -> tuple[list[vd.HypAnalysis], vd.Decision]:
    sds = [r for part in parts for r in part[0]]
    poss = [r for part in parts for r in part[1]]
    analyses = vd.analyse_all(sds, poss)
    return analyses, vd.decide(analyses)


# --- frozen verdict table ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        ({"n_dates": 8, "fill_base": 0}, "UNDERPOWERED-WAIT"),
        ({"fill_base": 0, "loss_f": 0}, "NO-GO (fill)"),
        ({"fill_base": 40, "loss_f": 30}, "NO-GO (adverse selection)"),
        ({"fill_base": 40, "fill_stress": 0}, "NO-GO (stress)"),
        ({"fill_base": 40, "p_f": 0.05}, "NOT-KILLED-UNSCREENED"),
        ({"fill_base": 40}, "NOT-KILLED"),
    ],
)
def test_verdict_table_rows_v0_to_v5(kwargs: dict[str, object], label: str) -> None:
    _, decision = analyse([scenario(**kwargs)])  # type: ignore[arg-type]
    assert decision.label == label


def test_label_function_is_the_frozen_table() -> None:
    assert vd.verdict_label(0.05, 0.05, "PASS")[0] == "NO-GO (fill)"
    assert vd.verdict_label(0.5, 0.5, "FAIL")[0] == "NO-GO (adverse selection)"
    assert vd.verdict_label(0.5, 0.05, "PASS")[0] == "NO-GO (stress)"
    assert vd.verdict_label(0.5, 0.5, "UNSCREENED")[0] == "NOT-KILLED-UNSCREENED"
    assert vd.verdict_label(0.5, 0.5, "PASS")[0] == "NOT-KILLED"
    # the boundary: exactly 0.10 is NOT below the floor
    assert vd.verdict_label(0.10, 0.10, "PASS")[0] == "NOT-KILLED"
    label, failing = vd.verdict_label(0.05, 0.05, "FAIL")
    assert label == "NO-GO (fill)"  # first matching row sets the label
    assert failing == ("V1", "V2", "V3")  # every failing row is printed


def test_stress_below_floor_is_no_go() -> None:
    analyses, decision = analyse([scenario(fill_base=40, fill_stress=4)])
    assert analyses[0].rates["stress_sd"].point == pytest.approx(0.05)
    assert decision.label == "NO-GO (stress)"
    assert "V3" in decision.failing


def test_unscreened_never_maps_to_not_killed() -> None:
    _, decision = analyse([scenario(fill_base=40, p_f=0.02, loss_f=0)])
    assert decision.label == "NOT-KILLED-UNSCREENED"
    assert decision.label != "NOT-KILLED"


def test_v0_is_decided_by_rho_assumed_not_by_fill_outcomes() -> None:
    quiet = analyse([scenario(n_dates=8, fill_base=0, loss_f=0)])
    flipped = analyse([scenario(n_dates=8, fill_base=32, loss_f=0)])
    assert quiet[1].label == flipped[1].label == "UNDERPOWERED-WAIT"
    assert quiet[0][0].n_eff_gov == flipped[0][0].n_eff_gov == pytest.approx(12.8)
    assert quiet[0][0].n0 == flipped[0][0].n0 == 8


def test_below_effective_n_floor_is_underpowered_wait_not_no_go() -> None:
    # zero fills would be NO-GO (fill) on a powered sample; below the floor it is a wait
    analyses, decision = analyse([scenario(n_dates=18, fill_base=0, loss_f=0)])
    assert analyses[0].n_eff_gov == pytest.approx(28.8)
    assert decision.label == "UNDERPOWERED-WAIT"
    powered, powered_decision = analyse([scenario(n_dates=19, fill_base=0, loss_f=0)])
    assert powered[0].n_eff_gov == pytest.approx(30.4)
    assert powered_decision.label == "NO-GO (fill)"


def test_underpowered_wait_prints_v1_to_v5_as_threshold_comparisons() -> None:
    sds, poss = scenario(n_dates=8, fill_base=0, loss_f=0)
    blocks = tb.render_tables(sds, poss, [], code_sha="abc")
    text = blocks["verdict"]
    assert "UNDERPOWERED-WAIT" in text
    assert "descriptive, not a label" in text
    assert "base 0.0000 < 0.10" in text
    assert "stressed 0.0000 < 0.10" in text
    assert "NO-GO" not in text  # never printed as a NO-GO string under V0
    assert "n_eff_gov" in blocks["v0"]


def test_fitted_icc_matches_hand_anova_is_report_only_and_undefined_when_n_sd_equals_n0() -> None:
    # dates d0 both filled, d1 neither, d2 LAX only: groups [1,1] [0,0] [1,0] -> rho 0.5
    sds = [
        sd_row("LAX", day(0), fb=1, fs=1),
        sd_row("MDW", day(0), fb=1, fs=1),
        sd_row("LAX", day(1)),
        sd_row("MDW", day(1)),
        sd_row("LAX", day(2), fb=1, fs=1),
        sd_row("MDW", day(2)),
    ]
    analysis = vd.analyse_all(sds, [])[0]
    assert analysis.icc_station_day.rho == pytest.approx(0.5)
    assert analysis.icc_station_day.n_eff_hat == pytest.approx(4.0)
    assert vd.decide([analysis]).label == "UNDERPOWERED-WAIT"  # decided by n_eff_gov alone
    single = vd.analyse_all([sd_row("LAX", day(i), fb=i % 2) for i in range(6)], [])[0]
    assert single.icc_station_day.rho is None  # n_sd == n0: MSW has 0 df
    assert "undefined" in tb.render_tables([sd_row("LAX", day(i)) for i in range(6)], [], [])["v0"]


def test_fitted_icc_banner_when_it_disagrees_on_the_floor_but_never_decides() -> None:
    # 20 dates: n_eff_gov = 32 (>= 30) ; whole-date fills give rho = 1 so n_eff_hat = 20 (< 30)
    sds = [
        sd_row(s, day(d), fb=int(d % 2 == 0), fs=int(d % 2 == 0))
        for d in range(20)
        for s in STATIONS
    ]
    analysis = vd.analyse_all(sds, [])[0]
    assert analysis.icc_station_day.rho == pytest.approx(1.0)
    assert analysis.fitted_icc_disagrees is True
    assert vd.decide([analysis]).label != "UNDERPOWERED-WAIT"
    assert "FITTED-ICC DISAGREES ON THE FLOOR" in tb.render_tables(sds, [], [])["v0"]


def test_v0_first_on_min_n_eff_gov_then_r3_severity_order() -> None:
    wait = scenario(hyp="USD_NOTIONAL_YES", n_dates=8, fill_base=0, loss_f=0)
    no_go = scenario(hyp="USD_NOTIONAL_TAKER", n_dates=20, fill_base=0, loss_f=0)
    _, decision = analyse([wait, no_go])
    assert decision.label == "UNDERPOWERED-WAIT"  # V0 on the min n_eff_gov, before severity
    assert decision.governing == "USD_NOTIONAL_YES"
    # powered both: NO-GO > NOT-KILLED-UNSCREENED > NOT-KILLED
    ok = scenario(hyp="USD_NOTIONAL_YES", fill_base=40)
    unscreened = scenario(hyp="USD_NOTIONAL_TAKER", fill_base=40, p_f=0.05)
    assert analyse([ok, unscreened])[1].label == "NOT-KILLED-UNSCREENED"
    stress = scenario(hyp="USD_NOTIONAL_TAKER", fill_base=40, fill_stress=0)
    assert analyse([ok, stress])[1].label == "NO-GO (stress)"
    unscreened_yes = scenario(hyp="USD_NOTIONAL_YES", fill_base=40, p_f=0.05)
    mixed = analyse([unscreened_yes, stress])[1]
    assert mixed.label == "NO-GO (stress)"
    assert mixed.governing == "USD_NOTIONAL_TAKER"


def test_severity_ties_go_to_the_lower_r_lo() -> None:
    a = scenario(hyp="USD_NOTIONAL_YES", fill_base=40, fill_stress=6)  # NO-GO (stress), r_lo .075
    b = scenario(hyp="USD_NOTIONAL_TAKER", fill_base=40, fill_stress=4)  # NO-GO (stress), r_lo .05
    analyses, decision = analyse([a, b])
    assert decision.label == "NO-GO (stress)"
    assert decision.governing == "USD_NOTIONAL_TAKER"
    assert {x.name: x.rates["stress_sd"].point for x in analyses}["USD_NOTIONAL_YES"] == 0.075


def test_bracketed_unit_takes_more_severe_verdict() -> None:
    mild = scenario(hyp="USD_NOTIONAL_YES", fill_base=40)
    harsh = scenario(hyp="USD_NOTIONAL_TAKER", fill_base=0, loss_f=0)
    analyses, decision = analyse([mild, harsh])
    assert decision.label == "NO-GO (fill)"
    assert decision.per_hypothesis == {
        "USD_NOTIONAL_TAKER": "NO-GO (fill)",
        "USD_NOTIONAL_YES": "NOT-KILLED",
    }
    assert len(analyses) == 2


def test_no_bid_bearing_days_is_degenerate() -> None:
    sds = [sd_row("LAX", day(0), bid_bearing=False)]
    with pytest.raises(vd.NoBidBearingDays):
        vd.decide(vd.analyse_all(sds, []))


# --- denominator, units -----------------------------------------------------------------------


def test_denominator_is_covered_bid_bearing_days_not_print_days() -> None:
    sds = [
        sd_row("LAX", day(0)),  # covered, bid-bearing, printless: unfilled, in
        sd_row("MDW", day(0), fb=1, fs=1),  # filled, in
        sd_row("MIA", day(0), covered=False, census_reason="THIN"),  # not covered
        sd_row("SFO", day(0), bid_bearing=False),  # covered, no attempt
        sd_row("LAX", day(1), outage_excluded=True),  # outage leaves num and denom
        sd_row("MDW", day(1), guard_refused_only=True, filled_pairs_base=0),  # refused: stays in
        sd_row("MIA", day(1), bid_bearing=False, n_no_book_wants=2),  # never booked: stays in
    ]
    analysis = vd.analyse_all(sds, [])[0]
    assert analysis.n_sd == 4
    assert analysis.n_never_booked_days == 1
    assert analysis.rates["base_sd"].n == 4
    assert analysis.rates["base_sd"].k == 1  # the printless window counts as unfilled
    assert analysis.covered_days == 5  # covered and not outage: bid-bearing share denominator


def test_stricter_unit_decides() -> None:
    # 16 of 80 station-days fill one of three positions: day unit 0.2, position unit 16/240
    sds = [
        sd_row(STATIONS[i % 4], day(i // 4), fb=int(i < 16), fs=int(i < 16), attempted=3)
        for i in range(80)
    ]
    analysis = vd.analyse_all(sds, [])[0]
    assert analysis.rates["base_sd"].point == pytest.approx(0.2)
    assert analysis.rates["base_pos"].point == pytest.approx(16 / 240)
    assert analysis.base_rate == pytest.approx(16 / 240)
    assert vd.decide([analysis]).label == "NO-GO (fill)"


def test_point_estimate_and_lower_bound_are_separate() -> None:
    analysis = analyse([scenario()])[0][0]
    rate = analysis.rates["base_sd"]
    assert rate.boot is not None
    assert rate.point is not None
    assert rate.point == pytest.approx(0.5)
    assert rate.boot.low < rate.point  # the lower bound is a different number
    assert analysis.expectancy.win_rate_boot is not None
    assert analysis.expectancy.win_rate_boot.low != analysis.expectancy.win_rate


# --- section 6.9 -------------------------------------------------------------------------------


def _s69(
    filled: Sequence[tuple[float, str]], unfilled: Sequence[tuple[float, str]]
) -> vd.Section69:
    rows = [
        pos_row("LAX", day(i), filled_base=True, filled_stress=True, p=p, outcome=o)
        for i, (p, o) in enumerate(filled)
    ] + [
        pos_row("MDW", day(i), filled_base=False, filled_stress=False, p=p, outcome=o)
        for i, (p, o) in enumerate(unfilled)
    ]
    return vd.section_69(rows)


def test_pooled_below_10_expected_losses_is_unscreened() -> None:
    result = _s69([(0.05, "YES")] * 50, [(0.05, "NO")] * 50)  # E = 2.5, all filled lost
    assert result.expected_losses == pytest.approx(2.5)
    assert result.state == "UNSCREENED"  # never FAIL, even with every fill a loss


def test_pooled_fail_is_fail() -> None:
    result = _s69(
        [(0.3, "YES")] * 12 + [(0.3, "NO")] * 28,
        [(0.3, "YES")] * 1 + [(0.3, "NO")] * 39,
    )
    assert result.p_a > 0.05  # Test A alone would pass
    assert result.p_b == pytest.approx(0.0126, abs=2e-4)
    assert result.state == "FAIL"


def test_pooled_pass() -> None:
    result = _s69(
        [(0.3, "YES")] * 5 + [(0.3, "NO")] * 35,
        [(0.3, "YES")] * 3 + [(0.3, "NO")] * 37,
    )
    assert result.state == "PASS"
    assert result.clusters_a == 40


def test_stratum_results_never_set_the_state() -> None:
    filled = [(0.3, "YES")] * 5 + [(0.3, "NO")] * 95 + [(0.01, "YES")] * 3
    unfilled = [(0.3, "YES")] * 5 + [(0.3, "NO")] * 95
    result = _s69(filled, unfilled)
    strata = {s.label: s for s in result.strata}
    assert strata["[0.98,1]"].p_a < 0.05  # a stratum alone fails Test A
    assert result.state == "PASS"  # the pooled set decides


def test_unresolved_past_d14_is_loss_and_void_is_excluded() -> None:
    result = _s69(
        [(0.3, "UNRESOLVED"), (0.3, "VOID"), (0.3, "NO")], [(0.3, "UNRESOLVED"), (0.3, "NO")]
    )
    assert result.losses_filled == 1
    assert result.losses_unfilled == 1
    assert result.n_filled == 2
    assert result.n_void_excluded == 1


def test_day_without_cli_final_is_excluded_from_s69_for_filled_and_unfilled_and_counted() -> None:
    result = _s69(
        [(0.3, "YES"), (0.3, ""), (0.3, "NO")],
        [(0.3, "NO"), (0.3, ""), (0.3, "")],
    )
    assert result.n_filled == 2
    assert result.n_unfilled == 1
    assert result.excluded_no_final_filled == 1
    assert result.excluded_no_final_unfilled == 2
    assert result.expected_losses == pytest.approx(0.6)  # the excluded fill adds nothing to E


def test_test_b_prints_cluster_count_and_stratum_adjusted_ratio() -> None:
    result = _s69(
        [(0.3, "YES")] * 4 + [(0.3, "NO")] * 36,
        [(0.3, "YES")] * 2 + [(0.3, "NO")] * 38,
    )
    assert result.clusters_b == 40
    # one stratum: standardised ratio = L_f / (n_f * L_u / n_u) = 4 / (40 * 2 / 40) = 2
    assert result.mix_adjusted_ratio == pytest.approx(2.0)
    text = tb.render_s69(result)
    assert "Poisson-conditional rate-ratio test (approximation, valid at p <= 0.06)" in text
    assert "clusters" in text


def test_s69_power_line_and_state_in_block() -> None:
    result = _s69([(0.05, "NO")] * 200, [(0.05, "NO")] * 200)
    assert [row.k for row in result.power.rows] == [1.5, 2.0, 3.0]
    assert result.power.fills_needed_for_ten_expected_losses == 200
    assert "UNSCREENED-TERMINAL" in tb.render_s69(result)  # stated as not a Stage 0 object


# --- expectancy, bids ---------------------------------------------------------------------------


def test_net_expectancy_formula_by_hand() -> None:
    sds = [sd_row("LAX", day(i), fb=1, fs=1) for i in range(2)]
    poss = [
        pos_row("LAX", day(0), filled_base=True, filled_stress=True, p=0.05, outcome="NO"),
        pos_row("LAX", day(1), filled_base=True, filled_stress=True, p=0.05, outcome="YES"),
    ]
    exp = vd.analyse_all(sds, poss)[0].expectancy
    fee = THETA * 0.75 * 0.25
    assert exp.net_mean == pytest.approx(((1 - 0.75 - fee) + (0 - 0.75 - fee)) / 2)
    assert exp.win_rate == 0.5
    assert exp.mean_p_no == pytest.approx(0.95)
    assert exp.net_upper_bound is None  # two clusters: not estimable


# --- s3_inputs ---------------------------------------------------------------------------------

S3_KEYS = {
    "verdict",
    "r_lo",
    "r_lo_station_day",
    "r_lo_position",
    "r_lo_by_hypothesis",
    "r_lo_lcb_cluster_boot",
    "r_lo_lcb_by_hypothesis",
    "r_lo_se_cluster_boot",
    "r_lo_k1",
    "base_k1",
    "r_lo_k1_lcb_cluster_boot",
    "fill_icc_rung_trial_k1",
    "base_station_day_rate",
    "base_station_day_rate_ci_cluster_boot",
    "two_fill_share",
    "bid_bearing_share_of_covered_listed",
    "fill_icc_rung_trial",
    "fill_icc_station_day",
    "n0_climate_dates",
    "n_eff_gov",
    "b",
    "realised_bid_iqr",
    "n_stressed_fills",
    "realised_bid_median_base",
    "max_rungs_hypothesis",
    "unit_hypothesis",
    "code_sha",
}


def test_s3_inputs_json_has_every_named_key() -> None:
    mild = scenario(hyp="USD_NOTIONAL_YES", fill_base=40, fill_stress=40)
    harsh = scenario(hyp="USD_NOTIONAL_TAKER", fill_base=40, fill_stress=24)
    analyses, decision = analyse([mild, harsh])
    s3 = vd.build_s3_inputs(decision, analyses, code_sha="deadbeef")
    assert set(s3) == S3_KEYS
    assert "k" not in s3
    by_hyp = s3["r_lo_by_hypothesis"]
    assert isinstance(by_hyp, dict)
    assert by_hyp == {"USD_NOTIONAL_TAKER": 0.3, "USD_NOTIONAL_YES": 0.5}
    assert s3["r_lo"] == min(by_hyp.values()) == s3["r_lo_station_day"]
    assert s3["verdict"] == decision.label == "NOT-KILLED"
    assert s3["unit_hypothesis"] == decision.governing
    assert s3["code_sha"] == "deadbeef"
    assert s3["max_rungs_hypothesis"] == 2
    lcb = s3["r_lo_lcb_by_hypothesis"]
    assert isinstance(lcb, dict)
    assert s3["r_lo_lcb_cluster_boot"] == min(lcb.values())
    b = s3["b"]
    assert isinstance(b, float)
    assert 0.70 <= b <= 0.80
    assert json.loads(json.dumps(s3)) == s3  # JSON-clean (no NaN, no tuples that change shape)


def test_s3_se_comes_from_the_hypothesis_attaining_the_min_lcb() -> None:
    mild = scenario(hyp="USD_NOTIONAL_YES", fill_base=40, fill_stress=40)
    harsh = scenario(hyp="USD_NOTIONAL_TAKER", fill_base=40, fill_stress=24)
    analyses, decision = analyse([mild, harsh])
    s3 = vd.build_s3_inputs(decision, analyses, code_sha="x")
    lcbs = {a.name: a.rates["stress_sd"].boot for a in analyses}
    worst = min((a for a in analyses), key=lambda a: _lcb(lcbs[a.name]))
    boot = worst.rates["stress_sd"].boot
    assert boot is not None
    assert s3["r_lo_se_cluster_boot"] == boot.se


def _lcb(boot: st.BootInterval | None) -> float:
    assert boot is not None
    return boot.low


def test_s3_icc_is_null_never_half_when_undefined() -> None:
    sds, poss = scenario(fill_base=40, fill_stress=0)  # no stressed fills: ICC denominator 0
    analyses = vd.analyse_all(sds, poss)
    s3 = vd.build_s3_inputs(vd.decide(analyses), analyses, code_sha="x")
    assert s3["fill_icc_rung_trial"] is None
    assert s3["fill_icc_rung_trial_k1"] is None
    assert s3["fill_icc_rung_trial"] != 0.5
    assert s3["b"] is None  # no stressed fills: nothing behind b
    assert s3["n_stressed_fills"] == 0


def test_s3_bid_statistics_use_lower_median_and_inverted_cdf() -> None:
    sds = [sd_row(STATIONS[i % 4], day(i // 4), fb=1, fs=1) for i in range(8)]
    bids = [0.70, 0.72, 0.74, 0.76, 0.78, 0.71, 0.73, 0.75]
    poss = [
        pos_row(
            STATIONS[i % 4],
            day(i // 4),
            filled_base=True,
            filled_stress=i < 4,
            p=0.05,
            outcome="NO",
            bid=bid,
        )
        for i, bid in enumerate(bids)
    ]
    analyses = vd.analyse_all(sds, poss)
    s3 = vd.build_s3_inputs(vd.decide(analyses), analyses, code_sha="x")
    assert s3["n_stressed_fills"] == 4
    assert s3["b"] == 0.72  # sorted [.70 .72 .74 .76] index floor(3 / 2) = 1
    assert s3["realised_bid_iqr"] == [0.70, 0.74]
    assert s3["realised_bid_median_base"] == 0.73  # 8 base fills: sorted index 3


def test_s3_nulls_cluster_dependent_keys_below_five_clusters() -> None:
    sds = [sd_row(s, day(d), fb=1, fs=1) for d in range(3) for s in STATIONS]
    analyses = vd.analyse_all(sds, [])
    s3 = vd.build_s3_inputs(vd.decide(analyses), analyses, code_sha="x")
    assert s3["r_lo_lcb_cluster_boot"] is None
    assert s3["r_lo_se_cluster_boot"] is None
    assert s3["base_station_day_rate_ci_cluster_boot"] is None
    assert s3["r_lo"] == 1.0
    sds, poss = scenario()
    assert "not estimable" in tb.render_tables(sds[:12], poss[:12], [])["rates"]


def test_k1_rates_and_two_fill_share() -> None:
    sds = [
        sd_row("LAX", day(0), fb=2, fs=2),
        sd_row("MDW", day(0), fb=1, fs=1),
        sd_row("MIA", day(0)),
        sd_row("SFO", day(0), fb=1, fs=0, k1_filled_stress=0),
    ]
    analysis = vd.analyse_all(sds, [])[0]
    assert analysis.rates["stress_k1"].k == 2
    assert analysis.rates["base_k1"].k == 3
    assert analysis.two_fill_share == pytest.approx(0.5)  # 1 of 2 stress-filled days has 2


# --- coverage sensitivity, days to 200 ---------------------------------------------------------


def test_coverage_sensitivity_threshold_half_of_process_live_is_report_only() -> None:
    sds = [
        sd_row("LAX", day(0), fb=1, fs=1, covered_live_h=5.0, gap_h=5.0, gap_share=0.5),
        sd_row("MDW", day(0), fb=1, fs=1, covered_live_h=4.9, gap_h=5.1, gap_share=0.51),
        sd_row("MIA", day(0), covered_live_h=2.0, gap_h=8.0, gap_share=0.8),
        sd_row("SFO", day(0), covered_live_h=9.0, gap_h=1.0, gap_share=0.1),
    ]
    analysis = vd.analyse_all(sds, [])[0]
    cov = analysis.coverage
    assert cov.n_sd == 2 and cov.n_all == 4  # 5.0 >= 0.5 * 10 keeps LAX; 4.9 drops MDW
    assert cov.base_sd == pytest.approx(0.5)  # LAX filled, SFO not
    assert cov.nogo_driving == 2
    assert cov.nogo_gap_gt_half == 1  # only MIA (0.8) ; SFO is 0.1
    assert analysis.rates["base_sd"].point == pytest.approx(0.5)
    before = vd.decide([analysis]).label
    shifted = [r for r in sds if (r.covered_live_h or 0.0) >= 5.0]
    after = vd.decide(vd.analyse_all(shifted, []))
    assert before == "UNDERPOWERED-WAIT" and after.label == "UNDERPOWERED-WAIT"
    assert "report-only" in tb.render_tables(sds, [], [])["coverage"]


def test_days_to_200_divides_by_distinct_covered_dates() -> None:
    sds = [sd_row(s, day(d), fb=1, fs=1) for d in range(5) for s in STATIONS[:2]]
    sds.append(sd_row("LAX", day(9), covered=False, census_reason="THIN"))
    analysis = vd.analyse_all(sds, [])[0]
    assert analysis.days_to_200["k2_stress"] == pytest.approx(200 / 2)  # 2 positions / date
    assert analysis.days_to_200["k1_stress"] == pytest.approx(200 / 2)
    none_filled = vd.analyse_all([sd_row("LAX", day(0))], [])[0]
    assert none_filled.days_to_200["k2_base"] is None


# --- CSV contract and rerun --------------------------------------------------------------------

SD_COLUMNS = [
    "station",
    "climate_day",
    "cluster_id",
    "unit_hypothesis",
    "census_reason",
    "covered_bidlive",
    "covered",
    "outage_excluded",
    "node_log_absent",
    "bid_bearing",
    "guard_refused_only",
    "n_depth_frames",
    "has_depth_frame",
    "n_attempts",
    "n_episodes",
    "n_refused",
    "n_process_cuts",
    "n_gtd_cuts",
    "rung_trials_posted",
    "rung_trials_filled_base",
    "rung_trials_filled_stress",
    "process_live_h",
    "forecast_valid_h",
    "gap_h",
    "covered_live_h",
    "gap_share",
    "filled_pairs_base",
    "filled_pairs_stress",
    "k1_rung_id",
    "k1_filled_base",
    "k1_filled_stress",
    "bid_median_fills_stress",
    "nogo_driving",
    "positions_filled_k2_base",
    "positions_filled_k2_stress",
    "positions_filled_k1_base",
    "positions_filled_k1_stress",
    "delta_ns",
    "truth_final",
    "truth_tmax_f",
    "void",
    "unresolved_d14",
    "theta",
]
POS_COLUMNS = [
    "position_id",
    "rung_trial_id",
    "station",
    "climate_day",
    "unit_hypothesis",
    "bid",
    "filled_base",
    "filled_stress",
    "p_yes_point_live",
    "truth_final",
]


def test_csv_column_contract_and_roundtrip() -> None:
    sds, poss = scenario(n_dates=3, fill_base=5)
    unreplayed = vd.SdRow(
        station="LAX", climate_day=day(9), cluster_id=day(9), unit_hypothesis=HYP,
        census_reason="THIN",
    )  # fmt: skip
    rows = [*sds, unreplayed]
    sd_text = tb.sd_rows_to_csv(rows)
    header = sd_text.splitlines()[0].split(",")
    assert header[: len(SD_COLUMNS)] == SD_COLUMNS  # every contract column, in order
    assert set(header[len(SD_COLUMNS) :]) == {"rung_trials_attempted", "n_no_book_wants"}
    assert tb.read_station_days_csv(sd_text) == rows
    assert tb.pos_rows_to_csv(poss).splitlines()[0].split(",") == POS_COLUMNS
    assert tb.read_scored_csv(tb.pos_rows_to_csv(poss)) == poss
    assert sd_text.splitlines()[-1].split(",")[11] == ""  # non-replayed field is null


def test_sd_row_from_summary_derives_the_csv_fields() -> None:
    summary = StationDaySummary(
        station="LAX", climate_day=day(0), unit_hypothesis=HYP, bid_bearing=True,
        guard_refused_only=False, n_attempts=3, n_episodes=2, n_refused=1, n_process_cuts=1,
        n_gtd_cuts=0, rung_trials_attempted=2, rung_trials_posted=2, rung_trials_filled_base=1,
        rung_trials_filled_stress=0, rungs_ever_posted=2, filled_pairs_base=1,
        filled_pairs_stress=0, k1_rung_id="r1", k1_filled_base=1, k1_filled_stress=0,
        bid_median_fills_stress=None, delta_ns=5, truncation_refused_share=None,
        first_refusal_to_first_placement_s=None, process_live_h=10.0, forecast_valid_h=9.0,
        gap_h=1.0, covered_live_h=9.0, gap_share=1 / 9,
    )  # fmt: skip
    row = tb.sd_row_from_summary(
        summary, census_reason="COVERED", covered_bidlive=True, covered=True,
        outage_excluded=False, node_log_absent=False, n_depth_frames=7, theta=THETA,
    )  # fmt: skip
    assert row.cluster_id == day(0)
    assert row.nogo_driving is True  # in the denominator and unfilled under the stressed rule
    assert row.positions_filled_k2_base == 1 and row.positions_filled_k1_stress == 0
    assert row.rung_trials_attempted == 2
    assert row.has_depth_frame is True


def test_stats_rerun_on_scored_csv_reproduces_tables(tmp_path: Path) -> None:
    mild = scenario(hyp="USD_NOTIONAL_YES", fill_base=40)
    harsh = scenario(hyp="USD_NOTIONAL_TAKER", fill_base=40, fill_stress=24, loss_f=6)
    sds = [*mild[0], *harsh[0]]
    poss = [*mild[1], *harsh[1]]
    sds.append(sd_row("LAX", day(40), hyp="USD_NOTIONAL_YES", covered=False, census_reason="THIN"))
    tail = [
        st.TailRow("LAX", day(i), f"v{i % 3}", 0.01 * (1 + i % 5), int(i % 7 == 0))
        for i in range(30)
    ]
    (tmp_path / "scored_episodes.csv").write_text(tb.pos_rows_to_csv(poss))
    (tmp_path / "station_days.csv").write_text(tb.sd_rows_to_csv(sds))
    (tmp_path / "tail_reliability.csv").write_text(tb.tail_rows_to_csv(tail))
    live = tb.render_tables(sds, poss, tail, code_sha="cafe")
    rerun = tb.tables_from_csvs(
        tmp_path / "scored_episodes.csv",
        tmp_path / "station_days.csv",
        tmp_path / "tail_reliability.csv",
        code_sha="cafe",
    )
    assert set(rerun) == set(tb.REPRODUCIBLE_BLOCKS) | set(tb.RUNTIME_ONLY_BLOCKS)
    for name in tb.REPRODUCIBLE_BLOCKS:
        assert rerun[name].encode() == live[name].encode(), name  # byte-identical
        assert rerun[name].strip(), name
    for name in tb.RUNTIME_ONLY_BLOCKS:
        assert "run-time only, sha-pinned" in rerun[name]
    assert json.loads(rerun["s3"])["code_sha"] == "cafe"


def test_tail_annotation_never_changes_the_label() -> None:
    sds, poss = scenario()
    bad_tail = [st.TailRow("LAX", day(i), "v0", 0.01, True) for i in range(12)]
    clean = tb.render_tables(sds, poss, [], code_sha="x")["verdict"]
    flagged = tb.render_tables(sds, poss, bad_tail, code_sha="x")["verdict"]
    assert "TAIL-MISCALIBRATED" in flagged
    assert "TAIL-MISCALIBRATED" not in clean
    assert flagged.splitlines()[0] == clean.splitlines()[0]  # same label line


def test_exploratory_banner_and_never_go() -> None:
    sds, poss = scenario()
    blocks = tb.render_tables(sds, poss, [], code_sha="x")
    assert "EXPLORATORY" in blocks["verdict"]
    for text in blocks.values():
        assert not re.search(r"\bGO\b", text.replace("NO-GO", ""))


def test_wp5_modules_do_not_import_the_truth_loader() -> None:
    import ast

    for name in ("maker_stage0_verdict.py", "maker_stage0_tables.py"):
        path = Path(__file__).resolve().parents[2] / "scripts/analysis" / name
        imported = {
            a.name
            for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.ImportFrom)
            for a in n.names
        }
        assert not imported & {"load_truth", "TruthTable"}, name


def test_wp5_module_line_counts_under_ceiling() -> None:
    root = Path(__file__).resolve().parents[2] / "scripts/analysis"
    for name in ("rows", "scored", "stats", "tables", "verdict"):
        path = root / f"maker_stage0_{name}.py"
        assert len(path.read_text().splitlines()) < 400, name


def test_wp5_split_reexports_keep_public_import_paths() -> None:
    from scripts.analysis import maker_stage0_rows as rw

    for name in ("SdRow", "PosRow", "nz", "in_denominator"):
        assert getattr(vd, name) is getattr(rw, name)
    for name in (
        "sd_rows_to_csv", "pos_rows_to_csv", "tail_rows_to_csv", "read_station_days_csv",
        "read_scored_csv", "read_tail_csv", "sd_row_from_summary",
    ):  # fmt: skip
        assert getattr(tb, name) is getattr(rw, name)
