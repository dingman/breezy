"""EXEC-PAR BG-10(c): the pure statistics behind the pre-registered simulation outputs.

Wilson-DEFF bound, one-way ANOVA ICC with n0 weighting, Clopper-Pearson, burst detection on arm
times, and the two-look promotion schedule (scalar reference and vectorised batch agree).
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
EXEC_PAR = REPO / "docs" / "evidence" / "exec_par"
WP0 = REPO / "docs" / "evidence" / "m1v3" / "exec_parallel_dhat.py"
NS = 10**9
HOUR = 3600 * NS


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def st() -> ModuleType:
    return _load("exec_par_bg10_stats_t", EXEC_PAR / "exec_par_bg10_stats.py")


@pytest.fixture(scope="module")
def wp0() -> ModuleType:
    return _load("exec_parallel_dhat_wp0_t", WP0)


# ---------------------------------------------------------------- Wilson-DEFF
def test_wilson_deff_one_equals_the_wp0_wilson(st: ModuleType, wp0: ModuleType) -> None:
    got = st.wilson_upper_deff(7, 39, 1.0, 1.96)
    assert got == pytest.approx(wp0.wilson_upper(7, 39), abs=1e-12)
    assert 0.325 < got < 0.335  # the 0.33 gate-arm proxy


def test_wilson_deff_shrinks_the_effective_n_not_the_proportion(st: ModuleType) -> None:
    assert st.wilson_upper_deff(6, 30, 2.0, 1.96) == pytest.approx(
        st.wilson_upper_deff(3, 15, 1.0, 1.96), abs=1e-12
    )


def test_wilson_deff_is_monotone_in_deff_and_z(st: ModuleType) -> None:
    base = st.wilson_upper_deff(6, 40, 1.0, 1.2816)
    assert st.wilson_upper_deff(6, 40, 1.5, 1.2816) > base
    assert st.wilson_upper_deff(6, 40, 1.0, 1.6449) > base


def test_wilson_deff_edges(st: ModuleType) -> None:
    assert st.wilson_upper_deff(0, 0, 1.0, 1.2816) == 1.0  # no data: no evidence
    assert 0.0 < st.wilson_upper_deff(0, 30, 1.0, 1.2816) < 0.1
    assert st.wilson_upper_deff(30, 30, 1.0, 1.2816) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        st.wilson_upper_deff(5, 4, 1.0, 1.2816)
    with pytest.raises(ValueError):
        st.wilson_upper_deff(1, 10, 0.5, 1.2816)


def test_deff_formula_and_clamp(st: ModuleType) -> None:
    assert st.deff(6.0, 0.1) == pytest.approx(1.5)
    assert st.deff(1.0, 0.1) == 1.0
    assert st.deff(0.5, 0.1) == 1.0  # fewer than one entry a day never lowers the bound


def test_z_one_sided(st: ModuleType) -> None:
    assert st.z_one_sided(0.90) == pytest.approx(1.2815516, abs=1e-6)
    assert st.z_one_sided(0.95) == pytest.approx(1.6448536, abs=1e-6)
    with pytest.raises(ValueError):
        st.z_one_sided(1.0)


def test_wilson_batch_matches_scalar(st: ModuleType) -> None:
    rng = random.Random(1)
    n = np.array([rng.randint(1, 120) for _ in range(200)])
    x = np.array([rng.randint(0, int(k)) for k in n])
    d = np.array([1.0 + rng.random() for _ in range(200)])
    got = st.wilson_upper_deff_batch(x, n, d, 1.2816)
    for i in range(200):
        assert got[i] == pytest.approx(
            st.wilson_upper_deff(int(x[i]), int(n[i]), float(d[i]), 1.2816)
        )


# ---------------------------------------------------------------- ANOVA ICC
def test_icc_hand_computed_equal_groups(st: ModuleType) -> None:
    out = st.anova_icc([(4, 2), (4, 0), (4, 4)])
    assert out.raw == pytest.approx(2 / 3, abs=1e-12)
    assert out.n0 == pytest.approx(4.0)
    assert out.used == pytest.approx(2 / 3, abs=1e-12)


def test_icc_hand_computed_unequal_groups_uses_n0_weighting(st: ModuleType) -> None:
    out = st.anova_icc([(2, 1), (6, 3), (4, 0)])
    assert out.n0 == pytest.approx((12 - 56 / 12) / 2)
    assert out.raw == pytest.approx(0.12, abs=1e-12)
    # the naive mean cluster size (4) would give a different answer: n0 is what is pinned
    assert out.n0 != pytest.approx(4.0)


def test_icc_negative_estimate_is_floored_to_point_one(st: ModuleType) -> None:
    out = st.anova_icc([(5, 1), (5, 1), (5, 1), (5, 1)])  # identical groups: MSB = 0
    assert out.raw < 0
    assert out.used == 0.1


def test_icc_floor_applies_to_a_small_positive_estimate_too(st: ModuleType) -> None:
    assert st.floor_icc(0.03) == 0.1
    assert st.floor_icc(0.4) == 0.4
    assert st.floor_icc(math.nan) == 0.1


def test_icc_perfect_clustering_is_one(st: ModuleType) -> None:
    assert st.anova_icc([(4, 4), (4, 0), (4, 4), (4, 0)]).raw == pytest.approx(1.0)


def test_icc_degenerate_inputs_use_the_floor(st: ModuleType) -> None:
    for groups in ([], [(5, 2)], [(0, 0), (3, 1)], [(1, 0), (1, 1)], [(3, 0), (3, 0)]):
        out = st.anova_icc(groups)
        assert out.used == 0.1
        assert math.isnan(out.raw)


def test_icc_rejects_impossible_groups(st: ModuleType) -> None:
    with pytest.raises(ValueError):
        st.anova_icc([(3, 4), (3, 1)])
    with pytest.raises(ValueError):
        st.anova_icc([(3, -1), (3, 1)])


def test_icc_recovers_a_known_beta_binomial_rho(st: ModuleType) -> None:
    rng = np.random.default_rng(7)
    p, rho = 0.3, 0.2
    a, b = p * (1 - rho) / rho, (1 - p) * (1 - rho) / rho
    groups = []
    for _ in range(4000):
        q = rng.beta(a, b)
        m = int(rng.integers(3, 9))
        groups.append((m, int(rng.binomial(m, q))))
    assert st.anova_icc(groups).raw == pytest.approx(rho, abs=0.03)


# ---------------------------------------------------------------- Clopper-Pearson
def test_cp_lower_known_values(st: ModuleType) -> None:
    assert st.clopper_pearson_lower(0, 10, 0.05) == 0.0
    assert st.clopper_pearson_lower(5, 10, 0.05) == pytest.approx(0.2224, abs=1e-3)
    assert st.clopper_pearson_lower(10, 10, 0.05) == pytest.approx(0.05 ** (1 / 10), abs=1e-6)


def test_cp_lower_matches_scipy_beta(st: ModuleType) -> None:
    beta = pytest.importorskip("scipy.stats").beta
    for n, x, a in [(20, 8, 0.01), (37, 14, 0.01), (60, 20, 0.05), (25, 25, 0.01)]:
        assert st.clopper_pearson_lower(x, n, a) == pytest.approx(
            float(beta.ppf(a, x, n - x + 1)), abs=1e-7
        )


def test_cp_lower_is_monotone(st: ModuleType) -> None:
    lows = [st.clopper_pearson_lower(x, 30, 0.01) for x in range(31)]
    assert lows == sorted(lows)
    assert st.clopper_pearson_lower(8, 40, 0.01) < st.clopper_pearson_lower(8, 30, 0.01)


def test_cp_lower_rejects_bad_input(st: ModuleType) -> None:
    for x, n, a in [(-1, 5, 0.01), (6, 5, 0.01), (1, 0, 0.01), (1, 5, 0.0), (1, 5, 1.0)]:
        with pytest.raises(ValueError):
            st.clopper_pearson_lower(x, n, a)


def test_cp_critical_table_agrees_with_the_lower_bound(st: ModuleType) -> None:
    crit = st.cp_critical_counts(60, 0.18, 0.01, min_n=20)
    for n in range(61):
        if n < 20:
            assert crit[n] > n  # never trips below the n >= 20 floor
            continue
        c = int(crit[n])
        assert c <= n + 1
        if c <= n:
            assert st.clopper_pearson_lower(c, n, 0.01) > 0.18
        if c >= 1:
            assert st.clopper_pearson_lower(c - 1, n, 0.01) <= 0.18


def test_cp_halts_at_the_documented_first_cases(st: ModuleType) -> None:
    crit = st.cp_critical_counts(40, 0.18, 0.01, min_n=20)
    assert crit[20] == 9  # 9/20 clears 0.18 at alpha 0.01, 8/20 does not (scipy binom.sf)
    assert crit[39] == 14


# ---------------------------------------------------------------- burst
def test_max_in_window_counts_events_inside_any_window(st: ModuleType) -> None:
    t = [0, 10 * 60 * NS, 20 * 60 * NS, 70 * 60 * NS, 75 * 60 * NS, 80 * 60 * NS]
    assert st.max_in_window(t, HOUR) == 4  # 20, 70, 75 and 80 minutes span exactly 60
    assert st.max_in_window([], HOUR) == 0
    assert st.max_in_window([5], HOUR) == 1


def test_max_in_window_boundary_is_inclusive_and_sorts_input(st: ModuleType) -> None:
    assert st.max_in_window([0, HOUR], HOUR) == 2
    assert st.max_in_window([0, HOUR + 1], HOUR) == 1
    assert st.max_in_window([HOUR, 0, 30 * 60 * NS], HOUR) == 3


def test_burst_tripped_on_arm_times(st: ModuleType) -> None:
    five = [i * 10 * 60 * NS for i in range(5)]  # 0..40 min
    assert st.burst_tripped(five, 5, HOUR) is True
    assert st.burst_tripped(five, 6, HOUR) is False
    spread = [i * 20 * 60 * NS for i in range(5)]  # 0..80 min: at most 4 inside any hour
    assert st.burst_tripped(spread, 5, HOUR) is False


def test_burst_tripped_validates_threshold(st: ModuleType) -> None:
    with pytest.raises(ValueError):
        st.burst_tripped([0], 0, HOUR)


def test_burst_threshold_rule(st: ModuleType) -> None:
    assert st.burst_threshold_applied(0.10) == 5  # not above 10%
    assert st.burst_threshold_applied(0.1001) == 6
    assert st.burst_threshold_applied(0.0) == 5


# ---------------------------------------------------------------- two-look schedule
def _entries(per_day: int, days: int = 15) -> list[int]:
    return [per_day] * days


def test_first_look_waits_for_eight_days_and_thirty_orders(st: ModuleType) -> None:
    assert st.first_look_day(_entries(6)) == 8  # 48 orders by day 8
    assert st.first_look_day(_entries(2)) == 15  # 30 orders only on day 15
    assert st.first_look_day(_entries(1)) is None  # 15 orders by the cap: hold
    assert st.first_look_day([10, 10, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == 8


def test_first_look_cap_is_fifteen_days(st: ModuleType) -> None:
    assert st.first_look_day([0] * 14 + [30]) == 15
    assert st.first_look_day([0] * 15 + [99]) is None


def test_relook_is_five_days_later_capped_at_fifteen(st: ModuleType) -> None:
    assert st.relook_day(8) == 13
    assert st.relook_day(11) == 15  # would fall on 16: happens on 15
    assert st.relook_day(15) == 15


def test_passes_at_the_first_look_when_clean(st: ModuleType) -> None:
    out = st.two_look_promotion(_entries(6), [0] * 15, level=0.33, z=1.2816, icc=0.1)
    assert out.first_look == 8
    assert out.first_pass is True
    assert out.promoted is True
    assert out.second_look is None


def test_fails_both_looks_when_ambiguous_share_is_high(st: ModuleType) -> None:
    out = st.two_look_promotion(_entries(6), _entries(3), level=0.33, z=1.2816, icc=0.1)
    assert out.first_pass is False
    assert out.second_look == 13
    assert out.promoted is False
    assert out.demoted is True


def test_second_look_is_cumulative_not_extension_only(st: ModuleType) -> None:
    # first 8 days are bad, the next 5 are clean: the cumulative rate still decides
    amb = [3] * 8 + [0] * 7
    out = st.two_look_promotion(_entries(6), amb, level=0.33, z=1.2816, icc=0.1)
    cum_n, cum_x = 6 * 13, 24
    bound = st.wilson_upper_deff(cum_x, cum_n, st.deff(cum_n / 13, 0.1), 1.2816)
    assert out.second_look == 13
    assert out.promoted is (bound <= 0.33)


def test_hold_when_the_look_minimum_is_never_met(st: ModuleType) -> None:
    out = st.two_look_promotion(_entries(1), [0] * 15, level=0.33, z=1.2816, icc=0.1)
    assert out.first_look is None
    assert out.promoted is False and out.demoted is False and out.held is True


def test_look_on_day_fifteen_relooks_on_day_fifteen_with_the_same_data(st: ModuleType) -> None:
    out = st.two_look_promotion(_entries(2), _entries(1), level=0.33, z=1.2816, icc=0.1)
    assert out.first_look == 15
    assert out.second_look == 15
    assert out.second_bound == out.first_bound
    assert out.promoted is False and out.demoted is True


def test_ninety_five_percent_bound_is_stricter(st: ModuleType) -> None:
    kw = {"level": 0.33, "icc": 0.1}
    amb = [1, 2, 1, 2, 1, 2, 1, 2] + [1] * 7
    ent = _entries(5)
    b90 = st.two_look_promotion(ent, amb, z=st.z_one_sided(0.90), **kw)
    b95 = st.two_look_promotion(ent, amb, z=st.z_one_sided(0.95), **kw)
    assert b95.first_bound >= b90.first_bound


def test_batch_agrees_with_the_scalar_reference(st: ModuleType) -> None:
    rng = np.random.default_rng(3)
    runs, days = 400, 15
    ent = rng.integers(0, 9, size=(runs, days))
    amb = rng.binomial(ent, 0.25)
    z = st.z_one_sided(0.90)
    batch = st.two_look_promotion_batch(ent, amb, level=0.33, z=z, icc=0.1)
    for i in range(runs):
        ref = st.two_look_promotion(ent[i].tolist(), amb[i].tolist(), level=0.33, z=z, icc=0.1)
        assert (batch.first_look[i] if batch.first_look[i] > 0 else None) == ref.first_look
        assert bool(batch.first_pass[i]) is ref.first_pass
        assert bool(batch.promoted[i]) is ref.promoted
        assert bool(batch.held[i]) is ref.held


def test_two_look_rejects_inconsistent_inputs(st: ModuleType) -> None:
    with pytest.raises(ValueError):
        st.two_look_promotion([1, 2], [3, 0], level=0.33, z=1.28, icc=0.1)
    with pytest.raises(ValueError):
        st.two_look_promotion([1, 2], [0], level=0.33, z=1.28, icc=0.1)
