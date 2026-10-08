"""Neyman–Pearson upper bound on G3 power (FQ-R8-2 Stage 0).

The critical value c is the smallest H0 replicate with P0(L > c) ≤ α.
The test is randomized on that atom, so the power is exact there rather than
a lower bound. A +inf likelihood ratio always rejects.
"""

from __future__ import annotations

import math

from scripts.analysis.fq_loss_floor_mc_draw import TickDraw, prepare_day
from scripts.analysis.fq_loss_floor_mc_rows import StationDay, make_leg, make_station_day
from scripts.analysis.fq_loss_floor_mc_sim import simulate_family
from scripts.analysis.fq_loss_floor_np_stat import (
    DELTA_H1,
    E_PROJ,
    POWER_SE_FORMULA,
    TIES_EXACT,
    bound_min_with_se,
    d1_decision,
    d1_point_decision,
    day_moments,
    discrete_critical_value,
    identity_at_recorded_carries,
    identity_evidence,
    information_identity,
    information_prefix,
    linear_s_threshold_power,
    log_lr_totals,
    np_bound_power,
    np_power_report,
    np_rejects,
    outcome_log_lr,
    rejection_rate,
)


def _yes_day(be: float, *, netting: float = 0.0) -> StationDay:
    return StationDay("KPHL", (make_leg("T70", "yes", be),), netting)


def test_log_lr_on_a_two_outcome_day() -> None:
    """One YES leg: win versus residual. Masses are the engine's, not a retype."""
    prep = prepare_day(_yes_day(0.40), deltas=(DELTA_H1,))
    h1 = prep.h1[DELTA_H1]
    assert h1 is not None
    assert abs(prep.masses[0] - 0.40) < 1e-12
    assert abs(h1[0] - 0.24) < 1e-12
    win = outcome_log_lr(prep, delta=DELTA_H1, index=0, hs=None)
    lose = outcome_log_lr(prep, delta=DELTA_H1, index=1, hs=None)
    # log(h1) - log(h0) of the engine masses. The decimal ratio is the same value to 1 ulp.
    assert win == math.log(h1[0]) - math.log(prep.masses[0])
    assert lose == math.log(1.0 - h1[0]) - math.log(1.0 - prep.masses[0])
    assert math.isclose(win, math.log(0.24 / 0.40), abs_tol=1e-15)
    assert math.isclose(lose, math.log(0.76 / 0.60), abs_tol=1e-15)


def test_infinite_lr_rejects_including_when_the_critical_value_is_infinite() -> None:
    """Two NO legs whose H1 clamp is not a categorical law. (0, 0) is off the H0 support."""
    day = StationDay(
        "KPHL",
        (make_leg("T40", "no", 0.55), make_leg("T50", "no", 0.55)),
        0.0,
    )
    prep = prepare_day(day, deltas=(DELTA_H1,))
    assert prep.h1[DELTA_H1] is None
    lr = outcome_log_lr(prep, delta=DELTA_H1, index=None, hs=(0.0, 0.0))
    assert lr == math.inf
    assert np_rejects(lr, 0.0) is True
    assert np_rejects(lr, math.inf) is True
    assert np_rejects(0.0, 0.0) is False


def test_information_identity_holds_on_a_fair_day_and_fails_on_a_skewed_one() -> None:
    fair = information_identity([prepare_day(_yes_day(0.50))])
    assert fair["information_identity_holds"] is True
    assert fair["max_abs_mean_z"] <= 1e-9
    assert fair["max_abs_second_moment_gap"] <= 1e-9
    assert "I_t" not in fair

    skewed = information_identity([prepare_day(_yes_day(0.50, netting=0.25))])
    assert skewed["information_identity_holds"] is False
    assert skewed["max_abs_mean_z"] > 1e-9
    assert isinstance(skewed["I_t"], dict)
    assert skewed["I_t"]["conditional_variance_sum"] > 0.0


def test_np_bound_is_at_least_the_linear_threshold_power() -> None:
    """Same α, same replicates. The linear test thresholds −S_t. NP is the LR."""
    lr_a = math.log(0.20 / 0.50)
    lr_b = math.log(0.55 / 0.25)
    lr_c = math.log(0.25 / 0.25)
    h0_lr = [lr_a] * 50 + [lr_b] * 25 + [lr_c] * 25
    h1_lr = [lr_a] * 20 + [lr_b] * 55 + [lr_c] * 25
    h0_s = [-1.0] * 50 + [0.0] * 25 + [1.0] * 25
    h1_s = [-1.0] * 20 + [0.0] * 55 + [1.0] * 25
    alpha = 0.25
    np_power = np_bound_power(h0_lr, h1_lr, alpha)
    linear = linear_s_threshold_power(h0_s, h1_s, alpha)
    assert np_power >= linear
    assert np_power == 0.55
    # −S puts half the H0 mass on the atom and γ = 1/2, so linear power is 0.10.
    assert math.isclose(linear, 0.1)
    # The LR atom has γ = 0, so that tie stays unrejected.
    assert discrete_critical_value(h0_lr, alpha) == 0.0


def test_d1_fails_when_the_best_reachable_bound_is_below_e_proj() -> None:
    """A bound in [0.25, 0.30) does not count. The latest passing epoch must be ≥ e_proj."""
    short, status = d1_decision(
        {
            "2026-10-08": 0.40,
            "2026-11-01": 0.27,
            "2026-11-15": 0.25,
            "2026-12-01": 0.299,
        },
        e_proj=E_PROJ,
    )
    assert short == "2026-10-08"
    assert status == "FAIL"

    none, failed = d1_decision(
        {"2026-11-01": 0.27, "2026-12-01": 0.25},
        e_proj=E_PROJ,
    )
    assert none is None
    assert failed == "FAIL"

    cutoff, passed = d1_decision(
        {"2026-10-08": 0.10, "2026-11-01": 0.30, "2026-12-01": 0.45},
        e_proj=E_PROJ,
    )
    assert cutoff == "2026-12-01"
    assert passed == "PASS"


def test_e_proj_is_written_verbatim() -> None:
    assert E_PROJ == "2026-11-01"
    document = {"e_proj": E_PROJ, "d1": d1_decision({"2026-11-01": 0.30}, e_proj=E_PROJ)[1]}
    assert document["e_proj"] == "2026-11-01"
    assert document["d1"] == "PASS"


def test_information_prefix_stops_at_min_t_k_and_realised_n() -> None:
    path = tuple(range(10))
    cuts = (4, 10)
    assert information_prefix(path, cuts, n_days=1, t_k=3) == (0, 1, 2)
    assert information_prefix(path, cuts, n_days=1, t_k=100) == (0, 1, 2, 3)
    assert information_prefix(path, cuts, n_days=2, t_k=6) == (0, 1, 2, 3, 4, 5)


def test_atom_heavy_statistic_returns_the_randomized_power() -> None:
    """Strict exceedance drops the atom. The randomized test adds γ·P1(L = c)."""
    h0 = [0.0] * 80 + [1.0] * 15 + [2.0] * 5
    h1 = [0.0] * 10 + [1.0] * 30 + [2.0] * 60
    alpha = 0.10
    # c = 1, #{L0 > 1} = 5, #{L0 = 1} = 15, γ = (10 − 5) / 15 = 1/3.
    strict = rejection_rate(h1, discrete_critical_value(h0, alpha))
    randomized = np_bound_power(h0, h1, alpha)
    assert math.isclose(strict, 0.60)
    assert randomized > strict
    assert math.isclose(randomized, 0.70)
    report = np_power_report(h0, h1, alpha)
    assert math.isclose(report.c, 1.0)
    assert math.isclose(report.gamma, 1.0 / 3.0)
    assert report.h0_tail == 5
    assert report.power == randomized
    assert TIES_EXACT == "randomized NP test; exact at the atom"


def test_tiny_alpha_with_an_empty_strict_tail_still_randomizes() -> None:
    """floor(α·n) = 0 used to require a strict exceedance of the maximum."""
    h0 = [0.0] * 19 + [3.0]
    h1 = [3.0] * 20
    alpha = 0.04
    assert math.floor(alpha * len(h0)) == 0
    # c = 3, nothing sits above it, γ = α·n / 1 = 0.8, and every H1 draw lands on c.
    assert math.isclose(np_bound_power(h0, h1, alpha), 0.8)
    report = np_power_report(h0, h1, alpha)
    assert math.isclose(report.c, 3.0)
    assert report.h0_tail == 0
    assert math.isclose(report.gamma, 0.8)
    assert math.isclose(report.power, 0.8)
    assert rejection_rate(h1, report.c) == 0.0


def test_all_zero_likelihood_paths_have_power_equal_to_alpha() -> None:
    """N = 0 leaves L = 0 on every replicate. Randomization on that atom has power α."""
    totals = log_lr_totals(
        draws=((), (), (), ()),
        cuts=((0,), (0,), (0,), (0,)),
        n_days=1,
        t_k=5,
        delta=DELTA_H1,
    )
    assert totals == [0.0, 0.0, 0.0, 0.0]
    assert math.isclose(np_bound_power(totals, totals, 0.10), 0.10)
    report = np_power_report(totals, totals, 0.10)
    assert report.h0_tail == 0
    assert math.isclose(report.c, 0.0)
    assert math.isclose(report.gamma, 0.10)
    assert math.isclose(report.power, 0.10)
    assert math.isclose(np_bound_power(totals, totals, 0.10), 0.10)


def test_randomized_power_se_is_the_multinomial_delta_method() -> None:
    """Conditional on (c, γ), SE = sqrt((mean(W²) − power²) / n1). +inf would weigh 1."""
    h0 = [0.0] * 80 + [1.0] * 15 + [2.0] * 5
    h1 = [0.0] * 10 + [1.0] * 30 + [2.0] * 60
    gamma = (0.10 * 100 - 5) / 15
    weights = [0.0] * 10 + [gamma] * 30 + [1.0] * 60
    power = math.fsum(weights) / len(weights)
    second = math.fsum(weight * weight for weight in weights) / len(weights)
    se = math.sqrt((second - power * power) / len(weights))
    report = np_power_report(h0, h1, 0.10)
    assert math.isclose(report.power, power)
    assert math.isclose(report.se, se)
    assert "mean(W" in POWER_SE_FORMULA
    assert "n1" in POWER_SE_FORMULA
    # γ = 0 collapses W to a Bernoulli, so the SE is the binomial SE.
    # c = 0, #{L0 > 0} = 5 = α·n, so the atom is not randomized.
    certain = np_power_report([0.0] * 95 + [1.0] * 5, [0.0] * 10 + [1.0] * 40, 0.05)
    binomial = math.sqrt(certain.power * (1.0 - certain.power) / 50)
    assert math.isclose(certain.gamma, 0.0)
    assert math.isclose(certain.power, 0.8)
    assert math.isclose(certain.se, binomial)


def test_constant_randomized_weight_reports_zero_standard_error() -> None:
    """A constant W has variance 0. At n1 = 50_000 a naive sum goes past the 1e-12 clamp."""
    n1 = 50_000
    alpha = 0.9985
    report = np_power_report((0.0,) * 8, (0.0,) * n1, alpha)
    assert math.isclose(report.gamma, alpha)
    assert math.isclose(report.power, alpha)
    assert report.se == 0.0


def test_d1_reach_is_the_minimum_upper_limit_across_mixes() -> None:
    """Every mix must clear 0.30. The noisiest low cell must not cover a quieter one.

    A = 0.28 ± 0.015 has limit 0.31. B = 0.29 ± 0.001 has limit 0.292.
    The point minimum is A, and feeding A's SE to D1 passes. B's limit does not,
    so the epoch fails. ``d1_point`` stays on the raw minimum.
    """
    rows = (
        {
            "epoch": "2026-11-01",
            "mix": "M-pool",
            "np_bound_alpha_eff": 0.28,
            "np_bound_alpha_eff_se": 0.015,
        },
        {
            "epoch": "2026-11-01",
            "mix": "M-yes",
            "np_bound_alpha_eff": 0.29,
            "np_bound_alpha_eff_se": 0.001,
        },
    )
    bound, se, upper = bound_min_with_se(rows)
    assert bound == {"2026-11-01": 0.28}
    assert se == {"2026-11-01": 0.015}
    assert math.isclose(upper["2026-11-01"], 0.29 + 2.0 * 0.001)
    assert upper["2026-11-01"] < 0.30
    cutoff, status = d1_decision(upper, e_proj=E_PROJ)
    assert cutoff is None
    assert status == "FAIL"
    point_cutoff, point = d1_point_decision(bound, e_proj=E_PROJ)
    assert point_cutoff is None
    assert point == "FAIL"
    # The screen this replaces: A's SE lifts the point minimum over 0.30.
    covered, covered_status = d1_decision(bound, e_proj=E_PROJ, se=se)
    assert covered == "2026-11-01"
    assert covered_status == "PASS"


def test_d1_reach_adds_two_standard_errors_of_the_minimising_cell() -> None:
    """``bound_min_se`` keeps a tie's larger SE. D1 uses the min upper limit.

    Two cells tie at 0.27. The noisier limit is 0.31, but the quieter twin's
    limit is 0.29, so the epoch does not reach. The point rule also fails it.
    A single series still reaches when its own ``bound + 2·SE`` clears 0.30.
    """
    rows = (
        {
            "epoch": "2026-11-01",
            "mix": "M-pool",
            "np_bound_alpha_eff": 0.27,
            "np_bound_alpha_eff_se": 0.01,
        },
        {
            "epoch": "2026-11-01",
            "mix": "M-yes",
            "np_bound_alpha_eff": 0.27,
            "np_bound_alpha_eff_se": 0.02,
        },
        {
            "epoch": "2026-11-01",
            "mix": "M-no",
            "np_bound_alpha_eff": 0.50,
            "np_bound_alpha_eff_se": 0.20,
        },
        {
            "epoch": "2026-12-01",
            "mix": "M-pool",
            "np_bound_alpha_eff": 0.25,
            "np_bound_alpha_eff_se": 0.01,
        },
    )
    bound, se, upper = bound_min_with_se(rows)
    assert bound == {"2026-11-01": 0.27, "2026-12-01": 0.25}
    # The two minimizers tie; bound_min_se keeps the larger SE, not M-no's.
    assert se == {"2026-11-01": 0.02, "2026-12-01": 0.01}
    assert math.isclose(upper["2026-11-01"], 0.27 + 2.0 * 0.01)
    assert math.isclose(upper["2026-12-01"], 0.25 + 2.0 * 0.01)
    cutoff, status = d1_decision(upper, e_proj=E_PROJ)
    assert cutoff is None
    assert status == "FAIL"
    point_cutoff, point = d1_point_decision(bound, e_proj=E_PROJ)
    assert point_cutoff is None
    assert point == "FAIL"

    # 0.27 + 2·0.01 = 0.29, still short of 0.30.
    missed, missed_status = d1_decision(
        {"2026-11-01": 0.27},
        e_proj=E_PROJ,
        se={"2026-11-01": 0.01},
    )
    assert missed is None
    assert missed_status == "FAIL"

    # Reaches only on an epoch before e_proj, so the cutoff is not a pass.
    early, early_status = d1_decision(
        {"2026-10-08": 0.28, "2026-11-01": 0.20},
        e_proj=E_PROJ,
        se={"2026-10-08": 0.02, "2026-11-01": 0.0},
    )
    assert early == "2026-10-08"
    assert early_status == "FAIL"

    # Equality at 0.30 after the two-SE lift is a reach.
    exact, exact_status = d1_decision(
        {"2026-11-01": 0.29},
        e_proj=E_PROJ,
        se={"2026-11-01": 0.005},
    )
    assert exact == "2026-11-01"
    assert exact_status == "PASS"


def test_nonzero_incoming_carry_fails_the_identity_and_the_check_detects_it() -> None:
    """A quiet day's netting is the next tick's carry. Σ m z and Σ m z² move with it."""
    quiet = prepare_day(make_station_day("KPHL", (), extra_netting=-0.3))
    loud = prepare_day(_yes_day(0.50))
    sim = simulate_family(
        ((quiet, loud),),
        replicates=1,
        n_days=1,
        p_keep=1.0,
        seed=0,
        row="H0",
        record_draws=True,
    )
    assert len(sim.draws) == 1
    assert len(sim.draws[0]) == 1
    recorded = sim.draws[0][0]
    assert isinstance(recorded, TickDraw)
    assert recorded.prep.day == loud.day
    assert math.isclose(recorded.carry, -0.3)

    moments = day_moments(loud, carry=-0.3)
    assert moments is not None
    mean, second, _conditional = moments
    carried = identity_at_recorded_carries(sim.draws)
    assert carried["information_identity_holds"] is False
    assert math.isclose(carried["max_abs_mean_z"], abs(mean))
    assert math.isclose(carried["max_abs_var_minus_1"], abs(second - 1.0))
    assert abs(mean) > 1e-9
    assert abs(second - 1.0) > 1e-9

    carry0 = information_identity([loud])
    assert carry0["information_identity_holds"] is True
    payload = identity_evidence(carry0, carried)
    assert payload["identity_figures"] == "The figures pool the preps of all three mixes."
    assert payload["information_identity_holds"] is False
    assert payload["max_abs_mean_z"] == carried["max_abs_mean_z"]
    assert payload["max_abs_var_minus_1"] == carried["max_abs_var_minus_1"]
    assert payload["max_abs_mean_z_carry0"] <= 1e-9
    assert payload["max_abs_var_minus_1_carry0"] <= 1e-9
    assert "I_t" in payload
