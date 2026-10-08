"""Floor-MC solver: monotone H0 rate, grid c, binding max, S6 predicate, mutations."""

from __future__ import annotations

import math

import numpy as np
import pytest

from breezy.analysis.fq_loss_stop_core import first_crossing
from scripts.analysis.fq_loss_floor_mc_rows import (
    critical_values,
    make_leg,
    make_station_day,
    s6_station_days,
)
from scripts.analysis.fq_loss_floor_mc_solve import (
    binding_max,
    bootstrap_c_se,
    critical_value,
    crossing_rate,
    path_rate,
    rate_within_alpha,
    single_day_share,
    smallest_grid_c,
)


def test_critical_value_matches_first_crossing() -> None:
    rng = np.random.default_rng(0)
    for _ in range(40):
        increments = rng.normal(-0.15, 1.0, size=25).tolist()
        t_min = int(rng.choice([1, 2, 3, 5]))
        crit = critical_value(increments, t_min=t_min)
        for c in (0.01, 0.5, 1.25, 2.5, float(crit) if math.isfinite(crit) else 1.0):
            crossed = first_crossing(increments, c=c, t_min=t_min) is not None
            assert crossed is bool(crit > c)


def test_h0_crossing_rate_is_monotone_decreasing_in_c() -> None:
    day = make_station_day("K", (make_leg("T70", "yes", 0.5),))
    paths = critical_values((day,), row="H0", replicates=300, n_ticks=36, seed=7, return_paths=True)
    assert isinstance(paths, list)
    rates = [path_rate(paths, c, t_min=1) for c in (0.25, 0.75, 1.5, 3.0)]
    assert rates == sorted(rates, reverse=True)
    assert rates[0] > rates[-1]


def test_smallest_grid_c_is_the_first_that_meets_alpha() -> None:
    critical = np.array([0.05, 0.15, 0.25, 3.0])
    # Strict ``critical > c``. Rate at 0.14 is 0.75, at 0.15 is 0.50, at 0.25 is 0.25.
    # α = 0.50 → the 0.01-grid point 0.15 (0.20 also passes, and is not the smallest).
    assert crossing_rate(critical, 0.14) > 0.50
    assert crossing_rate(critical, 0.15) == pytest.approx(0.50)
    assert smallest_grid_c(critical, 0.50) == pytest.approx(0.15)
    assert smallest_grid_c(critical, 0.50) < 0.20
    assert crossing_rate(critical, 0.10) > 0.50


def test_binding_max_and_s4_s5_exclusion_changes_c() -> None:
    cells = {
        ("H0", "M-pool"): 1.10,
        ("H0", "M-yes"): 1.05,
        ("H0", "M-no"): 1.00,
        ("S4", "M-no"): 1.50,
        ("S5", "M-pool"): 1.20,
    }
    solved, cell = binding_max(cells)
    assert solved == pytest.approx(1.50)
    assert cell == ("S4", "M-no")
    without = {key: value for key, value in cells.items() if key[0] not in {"S4", "S5"}}
    reduced, _reduced_cell = binding_max(without)
    assert reduced == pytest.approx(1.10)
    assert reduced != solved


def test_bootstrap_se_is_finite_and_positive_when_c_moves() -> None:
    critical = np.array([0.0, 0.0, 5.0, 5.0])
    se = bootstrap_c_se({("H0", "M-pool"): critical}, alpha=0.40, seed=1, draws=40)
    assert math.isfinite(se)
    assert se > 0.0


def test_s6_keeps_only_feasible_days_and_strips_netting() -> None:
    feasible = make_station_day("K", (make_leg("T70", "yes", 0.4),), extra_netting=-0.2)
    overround = make_station_day("K", (make_leg("T60", "yes", 0.7), make_leg("T70", "yes", 0.7)))
    kept = s6_station_days((feasible, overround))
    assert len(kept) == 1
    assert kept[0].netting == 0.0
    assert kept[0].legs == feasible.legs
    assert rate_within_alpha(0.10, alpha=0.10, se=0.01)
    assert not rate_within_alpha(0.20, alpha=0.10, se=0.01)


def test_s3_single_day_share_is_the_t_equals_1_mass() -> None:
    paths = [[-10.0, 0.0], [-0.1, -0.1, -10.0], [0.1, 0.1]]
    assert single_day_share(paths, c=1.0, t_min=1) == pytest.approx(0.5)


def test_dollar_scaled_pnl_changes_the_critical_value() -> None:
    day = make_station_day("K", (make_leg("T70", "yes", 0.4),), extra_netting=-0.05)
    base = critical_values((day,), row="H0", replicates=40, n_ticks=12, seed=3, pnl_scale=1.0)
    scaled = critical_values((day,), row="H0", replicates=40, n_ticks=12, seed=3, pnl_scale=100.0)
    assert isinstance(base, np.ndarray)
    assert isinstance(scaled, np.ndarray)
    assert not np.allclose(base, scaled)


def test_dropped_overround_day_changes_the_result() -> None:
    # Two YES legs are a deterministic shrink (variance 0). A YES+NO overround ticks.
    day = make_station_day("K", (make_leg("A", "yes", 0.8), make_leg("B", "no", 0.3)))
    kept = critical_values((day,), row="H0", replicates=30, n_ticks=8, seed=1, drop_overround=False)
    dropped = critical_values(
        (day,), row="H0", replicates=30, n_ticks=8, seed=1, drop_overround=True
    )
    assert isinstance(kept, np.ndarray)
    assert isinstance(dropped, np.ndarray)
    assert np.isfinite(kept).all()
    assert np.isneginf(dropped).all()


def test_dropped_netting_shift_changes_the_critical_value() -> None:
    day = make_station_day("K", (make_leg("T70", "yes", 0.4),), extra_netting=-0.3)
    with_shift = critical_values((day,), row="H0", replicates=20, n_ticks=10, seed=4, netting=True)
    without = critical_values((day,), row="H0", replicates=20, n_ticks=10, seed=4, netting=False)
    assert isinstance(with_shift, np.ndarray)
    assert isinstance(without, np.ndarray)
    assert not np.allclose(with_shift, without)
