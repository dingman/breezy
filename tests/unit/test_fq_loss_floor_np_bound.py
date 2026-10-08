"""Neyman–Pearson upper bound on G3 power (FQ-R8-2 Stage 0).

The critical value is the H0 quantile. Ties are not rejected, so a finite-sample
bound is conservative. A +inf likelihood ratio always rejects.
"""

from __future__ import annotations

import math

from scripts.analysis.fq_loss_floor_mc_draw import prepare_day
from scripts.analysis.fq_loss_floor_mc_rows import StationDay, make_leg
from scripts.analysis.fq_loss_floor_np_stat import (
    DELTA_H1,
    E_PROJ,
    d1_decision,
    discrete_critical_value,
    information_identity,
    information_prefix,
    linear_s_threshold_power,
    np_bound_power,
    np_rejects,
    outcome_log_lr,
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
    assert linear == 0.0
    # The H0 quantile leaves the tie mass on the boundary unrejected.
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
