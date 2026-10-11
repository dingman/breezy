"""TE-2 WP0 (RED): the pure core of the FQ v1 loss taxonomy.

Plan: docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r3_2.md section 5 (WP0 tests 1-32,
47, 50, 51). Fixtures are synthetic and offline; expected values come from brute-force enumeration
in this file, never from the code under test.
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
from collections.abc import Sequence
from typing import Any

import pytest

from scripts.analysis.fq_loss_taxonomy_core import (
    ClusterOutcome,
    FillClass,
    FillFacts,
    HypothesisOutcome,
    Qualifier,
    Status,
    Sublabel,
    VerdictInputs,
    VerdictLabel,
    apply_downgrade,
    art_testability,
    classify_fills,
    cluster_probability,
    cluster_station_days,
    cluster_tail_indicator,
    decide_verdict,
    edge_distance,
    format_p_value,
    h0k_cluster_probs,
    holm_plan,
    is_boundary,
    is_material_k1a,
    is_tail,
    k1b_flags,
    lower_tail,
    min_attainable_p_sign,
    pit_midpoint,
    poisson_binomial_pmf,
    reevaluate_after_ties,
    render_footer,
    report_phrase,
    sign_test,
    spread_cluster_null,
    spread_fill,
    station_day_k7_count,
    station_day_probability,
    status_for_min_p,
    t_loc_cluster,
    t_loc_min_attainable_p,
    t_loc_p_value,
    t_spread,
    t_spread_min_attainable_p,
    t_spread_power,
    t_win,
    t_win_leave_one_out,
    t_win_power,
    t_win_testability,
)
from tests.support.te2_fixtures import fq_station_days_per_fill

_PROBS = [0.1, 0.35, 0.5, 0.9, 0.02, 0.77]
_DAY = dt.date(2026, 10, 2)
_MIA_FT = "tc-temp-miahigh-2026-10-03-gte86lt87f.POLYMARKET_US"


def _brute_pmf(probs: Sequence[float]) -> list[float]:
    out = [0.0] * (len(probs) + 1)
    for bits in itertools.product((0, 1), repeat=len(probs)):
        pr = 1.0
        for bit, p in zip(bits, probs, strict=True):
            pr *= p if bit else 1.0 - p
        out[sum(bits)] += pr
    return out


def _brute_le(probs: Sequence[float], k: int) -> float:
    return sum(_brute_pmf(probs)[: k + 1])


def _brute_ge(probs: Sequence[float], k: int) -> float:
    return sum(_brute_pmf(probs)[k:])


def _ho(
    name: str,
    status: Any = "TESTABLE",
    rejects: bool = False,
    power: float | None = None,
) -> HypothesisOutcome:
    return HypothesisOutcome(name=name, status=status, rejects=rejects, p_value=0.5, power=power)


def _vi(**over: Any) -> VerdictInputs:
    base: dict[str, Any] = {
        "t_win": _ho("T-WIN", power=0.9),
        "loo_rejects": False,
        "t_loc": _ho("T-LOC"),
        "t_spread": _ho("T-SPREAD", power=0.9),
        "t_art": _ho("T-ART", status="NOT-TESTABLE"),
    }
    base.update(over)
    return VerdictInputs(**base)


def _fact(fid: str, day: dt.date = _DAY, **over: Any) -> FillFacts:
    base: dict[str, Any] = {
        "fill_id": fid,
        "station": "LAX",
        "climate_day": day,
        "edge_dist": 3,
        "pit": 0.5,
        "won": False,
    }
    base.update(over)
    return FillFacts(**base)


def test_poisson_binomial_matches_bruteforce_enumeration() -> None:
    pmf = poisson_binomial_pmf(_PROBS)

    assert len(pmf) == len(_PROBS) + 1
    assert pmf == pytest.approx(_brute_pmf(_PROBS), abs=1e-12)
    assert sum(pmf) == pytest.approx(1.0, abs=1e-12)


def test_lower_tail_P_W_le_k_matches_bruteforce_and_k0_equals_product_of_complements() -> None:
    for k in range(len(_PROBS) + 1):
        assert lower_tail(_PROBS, k) == pytest.approx(_brute_le(_PROBS, k), abs=1e-12)

    assert lower_tail(_PROBS, 0) == pytest.approx(math.prod(1.0 - p for p in _PROBS), rel=1e-12)
    assert lower_tail(_PROBS, len(_PROBS)) == pytest.approx(1.0, abs=1e-12)


def test_station_day_collapses_exclusive_rungs_and_clamps_P_d_at_1() -> None:
    assert station_day_probability([0.3, 0.4]) == pytest.approx(0.7)
    assert station_day_probability([0.7, 0.6]) == 1.0
    assert station_day_probability([0.25]) == pytest.approx(0.25)


def test_cluster_collapse_station_event_gap_splits_and_fixture_gives_14_days_7_clusters_6_without_10_06() -> (  # noqa: E501
    None
):
    days = sorted(set(fq_station_days_per_fill()))

    clusters = cluster_station_days(days)
    without_10_06 = cluster_station_days([sd for sd in days if sd[1] != dt.date(2026, 10, 6)])

    assert len(days) == 14
    assert len(clusters) == 7
    per_station = {
        s: sum(1 for c in clusters if c.station == s) for s in ("LAX", "MDW", "MIA", "SFO")
    }
    assert per_station == {"LAX": 1, "MDW": 2, "MIA": 2, "SFO": 2}
    assert len(without_10_06) == 6
    d1, d2, d3, d4 = (dt.date(2026, 10, n) for n in (1, 2, 3, 4))
    assert len(cluster_station_days([("X", d1), ("X", d2)])) == 1  # consecutive days
    assert len(cluster_station_days([("X", d1), ("X", d3)])) == 2  # day 2 missing: a gap splits
    assert len(cluster_station_days([("X", d4), ("X", d1)])) == 2  # unsorted input, 3-day gap


def test_cluster_P_c_is_max_of_P_d_clamped_and_zero_p_prints_below_bound() -> None:
    assert cluster_probability([0.3, 0.99, 0.5]) == 0.99
    assert cluster_probability([1.0, 0.2]) == pytest.approx(1.0 - 1e-9, abs=1e-15)
    assert cluster_probability([1.0, 0.2]) < 1.0
    assert format_p_value(0.0) == "< 1e-12"
    assert format_p_value(1e-13) == "< 1e-12"
    assert "0.0125" in format_p_value(0.0125)


def test_t_win_positive_control_high_P_c_with_few_wins_rejects() -> None:
    probs = [0.99] * 7

    result = t_win(probs, 1)

    assert result.rejects is True
    assert result.p_value == pytest.approx(_brute_le(probs, 1), rel=1e-9)
    assert result.p_value < 1e-6
    assert (result.n_clusters, result.w_obs) == (7, 1)
    assert t_win([0.3] * 7, 2).rejects is False


def test_t_win_leave_one_out_drops_max_P_c_cluster_recomputes_w_obs_when_a_win_cluster_drops_and_ties_go_to_first_station() -> (  # noqa: E501
    None
):
    rest = [
        ClusterOutcome("MDW", 0.4, False),
        ClusterOutcome("MIA", 0.6, True),
        ClusterOutcome("SFO", 0.5, False),
    ]
    loss_max = [ClusterOutcome("LAX", 0.995, False), *rest]
    win_max = [ClusterOutcome("ZZZ", 0.999, True), *rest]
    tie = [ClusterOutcome("MDW", 0.9, False), ClusterOutcome("LAX", 0.9, False), *rest[1:]]

    dropped_loss = t_win_leave_one_out(loss_max)
    dropped_win = t_win_leave_one_out(win_max)

    assert dropped_loss.dropped_station == "LAX"
    assert (dropped_loss.w_obs, dropped_loss.n_clusters) == (1, 3)
    assert dropped_loss.p_value == pytest.approx(_brute_le([0.4, 0.6, 0.5], 1), rel=1e-9)
    assert dropped_win.dropped_station == "ZZZ"
    assert (dropped_win.w_obs, dropped_win.n_clusters) == (1, 3)  # 2 wins -> 1 on the remainder
    assert t_win_leave_one_out(tie).dropped_station == "LAX"


def test_h0_k_uses_max_over_cluster_and_clamp() -> None:
    got = h0k_cluster_probs([[0.1, 0.3], [0.2], [1.0, 0.4]])

    assert got[:2] == (0.3, 0.2)
    assert got[2] == pytest.approx(1.0 - 1e-9, abs=1e-15)


def test_edge_dist_inclusive_via_bucket_facts_upper_edge_inclusive_lt_gte_and_no_leg() -> None:
    assert [edge_distance(_MIA_FT, t) for t in (87, 86, 88, 85, 90)] == [0, 0, 1, 1, 3]
    lt = "tc-temp-laxhigh-2026-10-05-lt97f.POLYMARKET_US"
    assert [edge_distance(lt, t) for t in (96, 97, 100, 50)] == [
        0,
        1,
        4,
        0,
    ]  # open side never nearest
    gte = "tc-temp-laxhigh-2026-10-05-gte100f.POLYMARKET_US"
    assert [edge_distance(gte, t) for t in (100, 99, 120)] == [0, 1, 0]
    no_leg = "tc-temp-laxhigh-2026-10-05-lt97f^no.POLYMARKET_US"
    assert edge_distance(no_leg, 97) == 1  # the YES interval is used on a ^no leg


def test_pit_midpoint_for_integer_outcome_from_pmf() -> None:
    pmf = {80: 0.2, 81: 0.5, 82: 0.3}

    assert pit_midpoint(pmf, 80) == pytest.approx(0.1)
    assert pit_midpoint(pmf, 81) == pytest.approx(0.45)
    assert pit_midpoint(pmf, 82) == pytest.approx(0.85)
    assert pit_midpoint(pmf, 70) == 0.0
    assert pit_midpoint(pmf, 90) == pytest.approx(1.0)


def test_classifier_boundary_precedes_band_selection_on_overlap() -> None:
    fills = [_fact("a", edge_dist=1), _fact("b", edge_dist=1)]  # 2 lost rungs, PIT 0.5

    assert classify_fills(fills) == {"a": "BOUNDARY", "b": "BOUNDARY"}


def test_boundary_and_tail_are_mutually_exclusive() -> None:
    for edge, pit in itertools.product(range(5), (0.0, 0.0499, 0.05, 0.5, 0.95, 0.9501, 1.0)):
        assert not (is_boundary(edge, pit) and is_tail(pit))
    assert is_boundary(1, 0.05) and is_boundary(1, 0.95)
    assert not is_boundary(1, 0.0499) and not is_boundary(2, 0.5)
    assert is_tail(0.0499) and is_tail(0.9501) and not is_tail(0.05)
    assert classify_fills([_fact("t", edge_dist=1, pit=0.97)]) == {"t": "TAIL"}


def test_win_class_then_sibling_won_precede_all_other_classes_and_taxonomy_applies_to_losers_only() -> (  # noqa: E501
    None
):
    order = [c.value for c in FillClass]
    assert order[:6] == ["WIN", "SIBLING_WON", "BOUNDARY", "TAIL", "BAND_SELECTION", "BODY_MISS"]
    assert order[6:] == ["UNTESTABLE"]  # a flag appended after the primary classes, not one of them
    fills = [
        _fact("win", edge_dist=0, pit=0.99, won=True),
        _fact("sib_boundary", edge_dist=1),
        _fact("sib_tail", edge_dist=2, pit=0.01),
        _fact("solo", day=dt.date(2026, 10, 3), edge_dist=3),
    ]

    assert classify_fills(fills) == {
        "win": FillClass.WIN,
        "sib_boundary": FillClass.SIBLING_WON,
        "sib_tail": FillClass.SIBLING_WON,
        "solo": FillClass.BODY_MISS,
    }


def test_k7_per_fill_rule_when_edge_dist_differs_within_a_station_day() -> None:
    fills = [
        _fact("near", edge_dist=1),
        _fact("far", edge_dist=3),
        _fact("edge_of_central", edge_dist=3, pit=0.95),
        _fact("central_low", edge_dist=3, pit=0.10),  # [0.10, 0.90] is inclusive at both ends
        _fact("central_high", edge_dist=3, pit=0.90),
        _fact("solo", day=dt.date(2026, 10, 3), edge_dist=3),
    ]

    classes = classify_fills(fills)
    assert classes["central_low"] == classes["central_high"] == FillClass.BAND_SELECTION

    assert classes["near"] == "BOUNDARY"
    assert classes["far"] == "BAND_SELECTION"
    assert classes["edge_of_central"] == "BODY_MISS"  # PIT outside the central 80%
    assert classes["solo"] == "BODY_MISS"  # a single rung is never band selection
    assert station_day_k7_count(fills) == 1  # one station-day, however many K7 fills


def test_partition_incomplete_marks_k7_untestable() -> None:
    fills = [_fact("near", edge_dist=1), _fact("far", edge_dist=3, partition_complete=False)]

    classes = classify_fills(fills)

    assert classes == {"near": FillClass.BOUNDARY, "far": FillClass.UNTESTABLE}
    assert station_day_k7_count(fills) == 0


def test_t_spread_null_is_per_fill_decision_cycle_pmf_not_binomial_0_10() -> None:
    wide = {80: 0.02, 81: 0.3, 82: 0.5, 83: 0.18}
    narrow = {80: 0.03, 81: 0.94, 82: 0.03}

    tail = spread_fill(wide, 80)
    inside = spread_fill(wide, 82)
    other = spread_fill(narrow, 81)

    assert tail.is_tail_miss is True and tail.pit == pytest.approx(0.01)
    assert inside.is_tail_miss is False
    assert tail.q_f == inside.q_f == pytest.approx(0.02)
    assert other.q_f == pytest.approx(0.06)  # a different cycle's pmf gives a different null
    assert not math.isclose(tail.q_f, 0.10) and not math.isclose(other.q_f, 0.10)


def test_t_spread_cluster_null_is_union_upper_bound_min_1_sum_q_and_any_fill_tail_miss_and_is_conservative_vs_bruteforce() -> (  # noqa: E501
    None
):
    qs = [0.02, 0.06, 0.05]
    independent = 1.0 - math.prod(1.0 - q for q in qs)
    comonotone = max(qs)

    q_c = spread_cluster_null(qs)

    assert q_c == pytest.approx(0.13)
    assert q_c >= independent and q_c >= comonotone
    assert spread_cluster_null([0.6, 0.7]) == 1.0
    assert cluster_tail_indicator([False, True, False]) == 1
    assert cluster_tail_indicator([False, False]) == 0
    cluster_qs = [0.13, 0.13, 0.5]
    assert t_spread(cluster_qs, 2) == pytest.approx(_brute_ge(cluster_qs, 2), rel=1e-9)


def test_sign_tests_drop_zeros_and_report_n_after_drops() -> None:
    diffs = [1.0, -2.0, 0.0, 3.0, 0.0, 0.5, 4.0]

    greater = sign_test(diffs, "greater")
    two = sign_test(diffs, "two-sided")

    assert (greater.n_after_drops, greater.n_dropped, greater.n_positive) == (5, 2, 4)
    assert greater.p_value == pytest.approx(6 / 32)
    assert sign_test(diffs, "less").p_value == pytest.approx(31 / 32)
    assert two.p_value == pytest.approx(12 / 32)


def test_min_attainable_p_marks_not_testable_never_did_not_reject() -> None:
    assert min_attainable_p_sign(7, "greater") == pytest.approx(1 / 128)
    assert min_attainable_p_sign(6, "greater") == pytest.approx(1 / 64)
    assert min_attainable_p_sign(7, "two-sided") == pytest.approx(1 / 64)
    assert art_testability(7) == "TESTABLE"
    assert art_testability(6) == "NOT-TESTABLE"
    assert status_for_min_p(1 / 64, 0.01) == "NOT-TESTABLE"
    # T-WIN: the minimum attainable p is P(W = 0) = prod(1 - P_c) under H0-M
    assert t_win_testability([0.5] * 7) == "TESTABLE"  # 1/128 <= 0.02
    assert t_win_testability([0.3] * 7) == "NOT-TESTABLE"  # 0.082 > 0.02
    text = report_phrase(_ho("T-ART", status="NOT-TESTABLE"))
    assert "NOT-TESTABLE" in text and "did not reject" not in text
    assert "did not reject" in report_phrase(_ho("T-WIN"))


def test_t_loc_is_two_sided_pmf_null_and_t_art_one_sided() -> None:
    assert t_loc_p_value([1] * 7, [0.5] * 7) == pytest.approx(2 / 128)
    assert t_loc_p_value([-1] * 7, [0.5] * 7) == pytest.approx(2 / 128)
    assert t_loc_p_value([1, -1, 1, -1, 1, -1, 1], [0.5] * 7) == pytest.approx(1.0)
    assert t_loc_p_value([1] * 7, [0.9] * 7) > 0.5  # all-positive is the mode under pi=0.9
    assert sign_test([1.0] * 7, "greater").p_value == pytest.approx(1 / 128)
    assert sign_test([-1.0] * 7, "greater").p_value == pytest.approx(1.0)


def test_t_loc_collapse_uses_min_max_pi_and_reports_the_larger_p() -> None:
    signs, lo, hi = [1] * 7, [0.4] * 7, [0.6] * 7

    result = t_loc_cluster(signs, lo, hi)

    assert result.p_at_pi_min == pytest.approx(t_loc_p_value(signs, lo))
    assert result.p_at_pi_max == pytest.approx(t_loc_p_value(signs, hi))
    assert result.p_value == pytest.approx(max(result.p_at_pi_min, result.p_at_pi_max))
    assert result.p_value > t_loc_p_value(signs, [0.5] * 7)


def test_cluster_power_is_min_over_max_Pc_and_independent_union_and_reports_t_spread_power() -> (
    None
):
    null = [0.9] * 5
    alt_days = [[0.1, 0.1]] * 5
    w_star = max(w for w in range(6) if _brute_le(null, w) <= 0.02)

    power = t_win_power(null, alt_days)

    assert power.w_star == w_star == 2
    assert power.power_max_pc == pytest.approx(_brute_le([0.1] * 5, w_star))
    assert power.power_independent == pytest.approx(_brute_le([0.19] * 5, w_star))
    assert power.power == pytest.approx(min(power.power_max_pc, power.power_independent))
    qs = [0.1] * 5
    x_star = min(x for x in range(6) if _brute_ge(qs, x) <= 0.02)
    assert t_spread_power(qs) == pytest.approx(_brute_ge([0.2] * 5, x_star))  # H1-S doubles q


def test_verdict_variance_requires_power_0_8_unconditionally_testable_secondary_and_weak_label() -> (  # noqa: E501
    None
):
    strong = decide_verdict(_vi())
    weak = decide_verdict(_vi(t_spread=_ho("T-SPREAD", power=0.5)))

    assert strong.label == VerdictLabel.VARIANCE and Qualifier.WEAK not in strong.qualifiers
    assert weak.label == VerdictLabel.VARIANCE and Qualifier.WEAK in weak.qualifiers
    assert decide_verdict(_vi(t_win=_ho("T-WIN", power=0.5))).label == "INCONCLUSIVE"
    art_no_power = _vi(t_art=_ho("T-ART", power=None))  # T-ART power is never computed
    art = decide_verdict(art_no_power)
    assert art.label == VerdictLabel.VARIANCE and Qualifier.WEAK in art.qualifiers
    conditional = _ho("T-SPREAD", status="TESTABLE-CONDITIONAL", power=0.9)
    assert decide_verdict(_vi(t_spread=conditional)).label == "INCONCLUSIVE"
    loc_only = _vi(t_spread=_ho("T-SPREAD", status="NOT-TESTABLE"))
    assert decide_verdict(loc_only).label == "INCONCLUSIVE"  # T-LOC is indicative, never counts


def test_verdict_miscalibrated_unattributed_branch_and_qualifiers() -> None:
    reject = _ho("T-WIN", rejects=True, power=0.9)
    secondaries_dead = {
        "t_spread": _ho("T-SPREAD", status="NOT-TESTABLE"),
        "t_art": _ho("T-ART", status="NOT-TESTABLE"),
    }

    single = decide_verdict(_vi(t_win=reject, **secondaries_dead))
    broad = decide_verdict(_vi(t_win=reject, loo_rejects=True))
    loc_note = decide_verdict(_vi(t_win=reject, t_loc=_ho("T-LOC", rejects=True)))

    assert single.label == "MODEL_MISCALIBRATED_UNATTRIBUTED"
    # Qualifier semantics: SINGLE_CLUSTER_DRIVEN when the leave-one-out does NOT reject;
    # SECONDARIES_NOT_TESTABLE when neither T-SPREAD nor T-ART is testable.
    assert {Qualifier.SINGLE_CLUSTER_DRIVEN, Qualifier.SECONDARIES_NOT_TESTABLE} <= set(
        single.qualifiers
    )
    assert broad.label == "MODEL_MISCALIBRATED_UNATTRIBUTED" and broad.qualifiers == ()
    assert loc_note.label == "MODEL_MISCALIBRATED_UNATTRIBUTED"
    assert "T-LOC" in " ".join(loc_note.notes)


def test_verdict_inconclusive_branch_states_reason_incl_loo_only_rejection() -> None:
    low_power = decide_verdict(_vi(t_win=_ho("T-WIN", power=0.4)))
    loo_only = decide_verdict(_vi(loo_rejects=True))

    assert low_power.label == loo_only.label == "INCONCLUSIVE"
    assert low_power.reason and "power" in low_power.reason
    assert loo_only.reason and "leave-one-out" in loo_only.reason


def test_verdict_fixable_positive_path_for_k4_and_for_material_k1a() -> None:
    art = _ho("T-ART", rejects=True)

    k4 = decide_verdict(_vi(has_k4=True))
    k1a = decide_verdict(_vi(material_k1a=True, t_art=art))

    assert k4.label == k1a.label == "FIXABLE_DEFECT"
    assert "MODEL_LIMITATION" in " ".join(k1a.notes)  # the statistical label is still reported


def test_immaterial_k1a_below_0_01_without_decision_flip_is_not_fixable() -> None:
    assert is_material_k1a(0.0099, False) is False
    assert is_material_k1a(0.01, False) is False
    assert is_material_k1a(0.0101, False) is True
    assert is_material_k1a(-0.02, False) is True
    assert is_material_k1a(0.0, True) is True
    assert decide_verdict(_vi(material_k1a=False)).label != "FIXABLE_DEFECT"


def test_t_loc_alone_k3_and_k1b_never_yield_fixable() -> None:
    loc = _ho("T-LOC", rejects=True)

    flags_only = decide_verdict(_vi(k3_present=True, k1b_present=True))
    loc_only = decide_verdict(_vi(t_loc=loc))
    loc_with_win = decide_verdict(_vi(t_loc=loc, t_win=_ho("T-WIN", rejects=True, power=0.9)))

    assert flags_only.label != "FIXABLE_DEFECT" and loc_only.label != "FIXABLE_DEFECT"
    assert loc_only.label != "MODEL_LIMITATION"
    assert loc_with_win.label == "MODEL_MISCALIBRATED_UNATTRIBUTED"


def test_model_limitation_sublabels_artefact_source_both_and_t_loc_alone_never_qualifies_model_limitation_or_source() -> (  # noqa: E501
    None
):
    art = _ho("T-ART", rejects=True)
    spread = _ho("T-SPREAD", rejects=True, power=0.9)
    loc = _ho("T-LOC", rejects=True)

    only_art = decide_verdict(_vi(t_art=art))
    only_spread = decide_verdict(_vi(t_spread=spread))
    both = decide_verdict(_vi(t_art=art, t_spread=spread))
    loc_only = decide_verdict(_vi(t_loc=loc))
    spread_loc = decide_verdict(_vi(t_spread=spread, t_loc=loc))

    ml = VerdictLabel.MODEL_LIMITATION
    assert (only_art.label, only_art.sublabel) == (ml, Sublabel.ARTEFACT)
    assert (only_spread.label, only_spread.sublabel) == (ml, Sublabel.SOURCE)
    assert (both.label, both.sublabel) == (ml, Sublabel.ARTEFACT_AND_SOURCE)
    assert loc_only.label != ml and loc_only.sublabel != Sublabel.SOURCE
    assert spread_loc.sublabel == Sublabel.SOURCE and "T-LOC" in " ".join(spread_loc.notes)
    # rule 2 precedes rule 3: a qualifying secondary rejection beats a T-WIN-only miscalibration
    win = _ho("T-WIN", rejects=True, power=0.9)
    assert decide_verdict(_vi(t_win=win, t_spread=spread)).label == ml
    # a CONDITIONAL member may reject only after a prior Holm rejection: none here, so no qualify
    cond = _ho("T-SPREAD", status="TESTABLE-CONDITIONAL", rejects=True, power=0.9)
    assert decide_verdict(_vi(t_spread=cond)).label != ml


def test_downgrade_rule_cluster_level_wins_and_scope_sensitive_label() -> None:
    cluster = {"T-WIN": False, "T-SPREAD": False}
    station_day = {"T-WIN": True, "T-SPREAD": False}
    six = {"T-WIN": False, "T-SPREAD": True}

    result = apply_downgrade(cluster, station_day, six)
    same = apply_downgrade(cluster, cluster, cluster)

    assert dict(result.decisions) == cluster
    assert any("T-WIN" in note for note in result.range_notes)
    assert result.scope_sensitive == ("T-SPREAD",)
    assert same.range_notes == () and same.scope_sensitive == ()


def test_footer_is_present_and_names_t1_t2_t3_not_permission_to_rearm() -> None:
    footer = render_footer(14, 7)

    assert "diagnostic, post-hoc, n = 14 station-days in 7 clusters, non-confirmatory" in footer
    assert "This verdict is NOT permission to re-arm." in footer
    for route in ("T1 (M1-v3 CONFIRM, read on or after 12-07)", "T2 (new family and prereg)"):
        assert route in footer
    assert "T3 (new US source, F13)" in footer
    assert "RULING_FQ-v2-NO-TRADE_2026-10-08" in footer
    assert "VARIANCE does not imply positive EV." in footer


def test_holm_drops_not_testable_members_first_k_shrinks_step1_alpha_over_k_and_testable_conditional_status_incl_6_cluster_sensitivity() -> (  # noqa: E501
    None
):
    seven = holm_plan({"T-LOC": 1 / 64, "T-SPREAD": 1 / 128})
    one_dead = holm_plan({"T-LOC": 1 / 64, "T-SPREAD": 0.03})
    six = holm_plan({"T-LOC": 1 / 32, "T-SPREAD": 1 / 64})
    all_dead = holm_plan({"T-LOC": 0.05, "T-SPREAD": 0.03})

    assert seven.k == 2
    assert seven.alpha_step1 == pytest.approx(0.01)
    with pytest.raises(ValueError):  # T-EDGE is outside every family: the caller excludes it
        holm_plan({"T-LOC": 1 / 64, "T-SPREAD": 1 / 128, "T-EDGE": 0.001})
    assert seven.statuses == {"T-SPREAD": "TESTABLE", "T-LOC": "TESTABLE-CONDITIONAL"}
    assert one_dead.k == 1
    assert one_dead.alpha_step1 == pytest.approx(0.02)
    assert one_dead.statuses == {"T-SPREAD": "NOT-TESTABLE", "T-LOC": "TESTABLE"}
    assert (six.k, six.statuses["T-LOC"], six.statuses["T-SPREAD"]) == (
        1,
        "NOT-TESTABLE",
        "TESTABLE",
    )
    assert all_dead.k == 0
    # testability uses each test's own null vectors
    assert t_loc_min_attainable_p([0.5] * 7, [0.5] * 7) == pytest.approx(1 / 64)
    assert t_loc_min_attainable_p([0.4] * 7, [0.6] * 7) > 0.04
    assert t_spread_min_attainable_p([0.5] * 7) == pytest.approx(1 / 128)
    assert t_spread_min_attainable_p([0.1] * 7) == pytest.approx(1e-7, rel=1e-6)


def test_k1b_flags_five_fills_on_three_station_days_and_sensitivity_excludes_them() -> None:
    keys = [(f"f{i}", s, d) for i, (s, d) in enumerate(fq_station_days_per_fill())]

    result = k1b_flags(keys, dt.date(2026, 10, 5))

    assert len(result.flagged_fill_ids) == 5
    assert len(result.flagged_station_days) == 3
    assert {s for s, _ in result.flagged_station_days} == {"LAX", "MDW", "SFO"}
    assert {d for _, d in result.flagged_station_days} == {dt.date(2026, 10, 6)}
    assert len(result.in_scope_station_days) == 11
    assert len(cluster_station_days(result.in_scope_station_days)) == 6


def test_testability_reevaluated_after_ties_and_downgraded_test_cannot_feed_variance() -> None:
    before: dict[str, Status] = {"T-ART": "TESTABLE", "T-SPREAD": "TESTABLE"}
    after: dict[str, Status] = {"T-ART": "NOT-TESTABLE", "T-SPREAD": "TESTABLE"}

    result = reevaluate_after_ties(before, after)
    verdict = decide_verdict(
        _vi(
            t_art=_ho("T-ART", status=after["T-ART"]),
            t_spread=_ho("T-SPREAD", status="TESTABLE-CONDITIONAL", power=0.9),
        )
    )

    assert result.downgraded == ("T-ART",)
    assert dict(result.variance_eligible) == {"T-ART": False, "T-SPREAD": True}
    assert verdict.label == VerdictLabel.INCONCLUSIVE
    cond_after: dict[str, Status] = {"T-ART": "TESTABLE", "T-SPREAD": "TESTABLE-CONDITIONAL"}
    weaker = reevaluate_after_ties(before, cond_after)
    assert weaker.downgraded == ("T-SPREAD",)
    assert dict(weaker.variance_eligible) == {"T-ART": True, "T-SPREAD": False}


def test_body_miss_class_name_replaces_k9_variance_and_never_collides_with_verdict_label() -> None:
    assert classify_fills([_fact("solo", edge_dist=4)]) == {"solo": FillClass.BODY_MISS}
    classes = {c.value for c in FillClass}
    labels = [v.value for v in VerdictLabel]

    assert "BODY_MISS" in classes and "VARIANCE" not in classes
    assert labels == [
        "FIXABLE_DEFECT",
        "MODEL_LIMITATION",
        "MODEL_MISCALIBRATED_UNATTRIBUTED",
        "VARIANCE",
        "INCONCLUSIVE",
    ]
    assert not classes & set(labels)
