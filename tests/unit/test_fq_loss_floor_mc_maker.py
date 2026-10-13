"""MAKER S3 WP3: path model, templates, rates, config pins, deff equivalence (plan r4 delta (k)).

Verdict, frozen-cell, input and artifact tests live in ``test_fq_loss_floor_mc_maker_verdict.py``.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from breezy.analysis.fq_loss_stop_clock import first_crossing, step_clock
from breezy.strategy.weather_common.costs import venue_fee_prob
from scripts.analysis import fq_loss_floor_mc_engine as engine
from scripts.analysis import fq_loss_floor_mc_maker as maker
from scripts.analysis import fq_loss_floor_mc_maker_templates as templates_mod
from scripts.analysis.fq_loss_floor_mc_draw import advance_prepared, invert_cdf, prepare_day
from scripts.analysis.fq_loss_floor_mc_gate import (
    DEFAULT_FREEZE,
    HORIZON,
    FloorSpec,
    fully_lost_fraction,
    inclusive_days,
    keep_probability,
    rate_cal,
    repeated_crossing,
)
from scripts.analysis.fq_loss_floor_mc_report import ticking_share
from scripts.analysis.fq_loss_floor_mc_rows import (
    _normalised,
    all_lose_z,
    cell_q,
    exit_probability,
    production_variance,
    sum_cell_q,
    worst_feasible_z,
    x_piece,
)
from scripts.analysis.fq_loss_floor_mc_solve import critical_value

ICC = 0.5 / 7


def _mix(**kw: Any) -> maker.MakerMix:
    base: dict[str, Any] = {
        "fill_rate": 0.5,
        "bid": 0.75,
        "rungs": 2,
        "bid_bearing": 1.0,
        "two_fill_share": 0.5,
        "fill_icc": ICC,
    }
    base.update(kw)
    return maker.MakerMix(**base)


def _days(groups: Any) -> list[Any]:
    return [day for group in groups for day in group]


def _two_leg_days(groups: Any) -> list[Any]:
    return [day for day in _days(groups) if len(day.legs) == 2]


# ------------------------------------------------------------------------------ path model


def test_maker_be_is_bid_plus_theta_fee() -> None:
    assert maker.maker_be(0.75, 0.0695) == pytest.approx(0.75 + 0.0695 * 0.75 * 0.25, abs=1e-15)
    assert maker.maker_be(0.75, 0.0695) == pytest.approx(
        0.75 + venue_fee_prob(executable_price=0.75, fee_coefficient=0.0695), abs=1e-15
    )
    assert maker.maker_be(0.70, 0.0) == pytest.approx(0.70)
    assert maker.maker_be(0.80, 0.08) == pytest.approx(0.80 + 0.08 * 0.16)
    assert maker.maker_be(0.75, 0.0695) > 0.75


def test_maker_leg_pnl_win_is_one_minus_be_and_loss_is_minus_be() -> None:
    mix = _mix(bid=0.70)
    day = _two_leg_days(maker.build_maker_groups(mix, n_dates=80, seed=1))[0]
    be = maker.maker_be(0.70, mix.theta)
    for leg in day.legs:
        assert leg.side == "no"
        assert leg.be == pytest.approx(be, abs=1e-15)
        assert leg.price == pytest.approx(0.70)
        assert x_piece(1.0, Decimal(str(leg.be))) == pytest.approx(1.0 - be, abs=1e-12)
        assert x_piece(0.0, Decimal(str(leg.be))) == pytest.approx(-be, abs=1e-12)


def test_two_maker_legs_cannot_both_lose() -> None:
    day = _two_leg_days(maker.build_maker_groups(_mix(), n_dates=80, seed=2))[0]
    assert len({leg.rung for leg in day.legs}) == 2
    assert sum_cell_q(day) <= 1.0
    prepared = prepare_day(day)
    be_sum = sum(leg.be for leg in day.legs)
    one_lost = min(-day.legs[0].be + (1 - day.legs[1].be), -day.legs[1].be + (1 - day.legs[0].be))
    assert len(prepared.xs) == 3
    assert min(prepared.xs) == pytest.approx(one_lost, abs=1e-12)
    assert min(prepared.xs) > -be_sum + 0.5
    z_all, z_feasible = all_lose_z(day), worst_feasible_z(day, prepared.xs)
    assert z_all is not None and z_feasible is not None and z_feasible > z_all


def test_h1_bernoulli_fallback_share_is_zero_on_maker_cells() -> None:
    for bid in (0.70, 0.75, 0.80):
        groups = maker.build_maker_groups(_mix(bid=bid), n_dates=60, seed=3)
        for day in _days(groups):
            prepared = prepare_day(day, deltas=(-0.16, -0.08, -0.04))
            assert all(masses is not None for masses in prepared.h1.values())
            assert math.isclose(sum(cell_q(leg) for leg in day.legs), sum_cell_q(day))


def test_maker_s4_row_applies_exit_floor() -> None:
    """CHARACTERISATION (mutation: floor -> 0 makes the two sims identical)."""
    mix = _mix()
    groups = maker.build_maker_groups(mix, n_dates=40, seed=4)
    config = maker.maker_floor_config(groups, mix)
    assert config.pool_exit_fraction == 0.0
    assert exit_probability(config.pool_exit_fraction) == pytest.approx(0.10)
    prep = prepare_day(_two_leg_days(groups)[0])
    floor = exit_probability(config.pool_exit_fraction)

    def tick(p_exit: float, seed: int) -> float:
        step, _carry, _fallback = advance_prepared(
            prep,
            u=0.99,  # no rung wins: both NO legs pay
            rng=np.random.default_rng(seed),
            carry=0.0,
            row="S4",
            delta=None,
            netting=True,
            pnl_scale=1.0,
            p_exit=p_exit,
            half_spread=None,
            theta=config.theta,
        )
        assert step.z is not None
        return step.z

    pairs = [(tick(0.0, s), tick(floor, s)) for s in range(400)]
    charged = [(z0, z1) for z0, z1 in pairs if z1 != z0]
    assert all(z1 < z0 for z0, z1 in charged)
    # P(at least one of two legs draws an exit) = 1 - 0.9**2 = 0.19
    assert 0.10 < len(charged) / len(pairs) < 0.30


# ------------------------------------------------------------------------------- templates


def test_template_listing_bid_bearing_and_fill_rates_match_parameters() -> None:
    n = 6000
    mix = _mix(fill_rate=0.4, bid_bearing=0.8, two_fill_share=0.5)
    groups = maker.build_maker_groups(mix, n_dates=n, seed=5)
    assert len(groups) == n
    per_date = np.array([len(g) for g in groups], dtype=float)
    legs_per_sd = np.mean([len(d.legs) for d in _days(groups)])
    expect = 4 * 0.91 * 0.8 * 0.4
    assert abs(per_date.mean() - expect) < 4 * per_date.std() / math.sqrt(n)
    legs = np.array([len(d.legs) for d in _days(groups)], dtype=float)
    assert abs(legs_per_sd - 1.5) < 4 * legs.std() / math.sqrt(len(legs))
    assert {d.station for d in _days(groups)} <= {"LAX", "MDW", "MIA", "SFO"}
    assert any(len(g) == 0 for g in groups)  # fill-less dates stay as empty groups


def _realised_deff(
    monkeypatch: pytest.MonkeyPatch, icc_rung_trial: float, *, n: int, seed: int
) -> tuple[float, float]:
    """Variance inflation of the 4 per-date fill trials over independent trials, and its MC SE.

    Listing is forced to 1 so each station-day is exactly one fill trial; the count variance over
    ``4 f (1 - f)`` is then the design effect of those trials.
    """
    monkeypatch.setattr(templates_mod, "LISTING", 1.0)
    f = 0.5
    mix = _mix(fill_rate=f, fill_icc=icc_rung_trial, rungs=1, two_fill_share=0.0)
    groups = maker.build_maker_groups(mix, n_dates=n, seed=seed)
    counts = np.array([len(g) for g in groups], dtype=float)
    independent = 4 * f * (1 - f)
    centred = counts - counts.mean()
    var = float(centred.var())
    se_var = math.sqrt(float(np.mean(centred**4)) - var**2) / math.sqrt(n)
    return var / independent, se_var / independent


def test_template_fill_overdispersion_matches_pinned_design_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The REALISED variance inflation of the fill trials is the pinned 1.5, not the arithmetic."""
    assert 1 + 7 * ICC == pytest.approx(maker.DEFF_CEILING) == pytest.approx(1.5)
    assert maker.FILL_ICC == pytest.approx(ICC)
    assert maker.FILL_ICC_SD == pytest.approx(0.5 / 3)
    deff, se = _realised_deff(monkeypatch, ICC, n=40_000, seed=6)
    assert abs(deff - 1.5) < 3 * se, (deff, se)
    # the unit slip would have realised 1 + 3 * (0.5/7) = 1.214: that is many SE away
    assert abs(deff - (1 + 3 * ICC)) > 6 * se
    # and a larger (S2-estimated) rung-trial ICC scales the same way
    big, big_se = _realised_deff(monkeypatch, 0.2, n=40_000, seed=7)
    assert abs(big - (1 + 7 * 0.2)) < 3 * big_se, (big, big_se)


def test_design_effects_record_both_icc_units() -> None:
    eff = maker.design_effects(maker.FILL_ICC)
    assert eff["fill_icc_rung_trial"] == pytest.approx(0.5 / 7)
    assert eff["fill_icc_station_day"] == pytest.approx(0.5 / 3)
    assert eff["design_effect_pinned"] == pytest.approx(1.5)
    assert eff["design_effect_realised"] == pytest.approx(1.5)
    assert maker.design_effects(0.2)["design_effect_realised"] == pytest.approx(2.4)
    with pytest.raises(ValueError, match="station-day"):
        _mix(fill_icc=3 / 7)  # maps to a per-station-day ICC of 1
    with pytest.raises(ValueError, match="0.5/7"):
        _mix(fill_icc=0.05)  # the floor stays on the rung-trial value


def test_template_fill_counts_match_analytic_variance_at_high_icc() -> None:
    f, rho_rt, n = 0.5, 0.2, 8000
    rho = maker.station_day_icc(rho_rt)
    groups = maker.build_maker_groups(
        _mix(fill_rate=f, fill_icc=rho_rt, rungs=1, two_fill_share=0.0), n_dates=n, seed=6
    )
    counts = np.array([len(g) for g in groups], dtype=float)
    q = 0.91 * f
    independent = 4 * q * (1 - q)
    analytic = independent + 12 * 0.91**2 * rho * f * (1 - f)
    assert counts.var() == pytest.approx(analytic, rel=0.08)
    assert counts.var() > 1.3 * independent


def test_maker_templates_are_all_no_side() -> None:
    for rungs in (1, 2):
        mix = _mix(rungs=rungs, two_fill_share=0.5 if rungs == 2 else 0.0)
        days = _days(maker.build_maker_groups(mix, n_dates=100, seed=7))
        assert days
        assert all(leg.side == "no" for d in days for leg in d.legs)
        assert all(len(d.legs) <= rungs for d in days)
        assert all(len({leg.rung for leg in d.legs}) == len(d.legs) for d in days)


def test_templates_refuse_bid_outside_b_floor_b_cap() -> None:
    for bad in (0.69, 0.801, 0.5, 0.95):
        with pytest.raises(ValueError, match="bid"):
            _mix(bid=bad)
    for ok in (0.70, 0.75, 0.80):
        assert _mix(bid=ok).bid == ok
    with pytest.raises(ValueError, match="two_fill_share"):
        _mix(rungs=1, two_fill_share=0.1)
    with pytest.raises(ValueError, match="rungs"):
        _mix(rungs=3)


def test_fill_icc_below_ceiling_floor_is_refused() -> None:
    with pytest.raises(ValueError, match="fill_icc"):
        _mix(fill_icc=ICC * 0.99)
    assert _mix(fill_icc=ICC).fill_icc == ICC
    assert _mix(fill_icc=0.3).fill_icc == 0.3


# ------------------------------------------------------------------------------------ rates


def test_lambda_sd_equals_template_mean_station_days_per_date() -> None:
    mix = _mix()
    groups = maker.build_maker_groups(mix, n_dates=300, seed=8)
    config = maker.maker_floor_config(groups, mix)
    assert config.lambda_sd == pytest.approx(len(_days(groups)) / 300)


def test_r_sd_times_lambda_sd_equals_template_fills_per_date() -> None:
    mix = _mix()
    groups = maker.build_maker_groups(mix, n_dates=300, seed=9)
    config = maker.maker_floor_config(groups, mix)
    legs = sum(len(d.legs) for d in _days(groups))
    assert config.r_sd * config.lambda_sd == pytest.approx(legs / 300)
    assert config.lambda_pool == pytest.approx(legs / 300)
    assert config.take_rate_lower == pytest.approx(legs / 300)


def test_maker_config_keep_probability_is_one() -> None:
    mix = _mix()
    config = maker.maker_floor_config(maker.build_maker_groups(mix, n_dates=300, seed=10), mix)
    p_keep = keep_probability(
        rate_cal(config.lambda_pool, config.take_rate_lower),
        r_sd=config.r_sd,
        lambda_sd=config.lambda_sd,
    )
    assert p_keep == pytest.approx(1.0, abs=1e-12)


def test_maker_tick_share_is_one() -> None:
    mix = _mix()
    groups = engine._partition(maker.build_maker_groups(mix, n_dates=200, seed=11))[0]
    assert ticking_share(groups) == 1.0
    assert all(production_variance(d) > 0.15 for d in _days(groups))


# -------------------------------------------------------------------------------- config pins


def test_maker_config_pins_rho_hat_half_and_fq_window() -> None:
    mix = _mix(theta=0.08)
    config = maker.maker_floor_config(maker.build_maker_groups(mix, n_dates=50, seed=12), mix)
    assert config.rho_hat == 0.5
    assert config.freeze == DEFAULT_FREEZE == date(2026, 10, 8)
    assert config.horizon == HORIZON == date(2027, 1, 25)
    assert inclusive_days(config.freeze, config.horizon) == 110
    assert config.half_spread is None and config.pool_exit_fraction == 0.0
    assert config.theta == 0.08
    spec = maker.MAKER_SPEC
    assert isinstance(spec, FloorSpec)
    assert spec.mixes == ("M-pool",) and spec.g1_path == "worst_feasible"
    assert ("S8", "persist3") in spec.binding and ("S9", "persist5") not in spec.binding
    assert spec.persist == (("persist3", 3, 0.5), ("persist5", 5, 0.9))


def test_other_freeze_is_refused() -> None:
    mix = _mix()
    groups = maker.build_maker_groups(mix, n_dates=20, seed=13)
    for freeze in (date(2026, 10, 9), date(2026, 10, 7), date(2026, 11, 23)):
        with pytest.raises(ValueError, match="freeze"):
            maker.maker_floor_config(groups, mix, freeze=freeze)
    assert maker.maker_floor_config(groups, mix, freeze=date(2026, 10, 8)).freeze == DEFAULT_FREEZE


def test_binding_run_pins_outer_resamples_and_replicates() -> None:
    assert maker.SEED == 20261012
    assert maker.N_TEMPLATE_DATES == 1000
    assert maker.SWEEP_REPLICATES == 2000
    assert maker.BINDING_REPLICATES == 10_000
    assert (maker.OUTER_RESAMPLES, maker.OUTER_REPLICATES) == (20, 2000)
    assert (maker.BORDERLINE_REPLICATES, maker.BORDERLINE_SEED) == (50_000, 20261013)
    assert maker.STRESS_THETA == 0.08 and maker.FILL_ICC == ICC
    assert (maker.B_FLOOR, maker.B_CAP, maker.MAX_RUNGS) == (0.70, 0.80, 2)
    grid = maker.sweep_mixes()
    assert len(grid) == 30
    assert {m.fill_rate for m in grid} == {0.1, 0.2, 0.3, 0.4, 0.5}
    assert {m.bid for m in grid} == {0.70, 0.75, 0.80}
    assert {m.rungs for m in grid} == {1, 2}
    assert all(m.bid_bearing == 1.0 and m.fill_icc == ICC for m in grid)
    assert all(m.two_fill_share == (0.5 if m.rungs == 2 else 0.0) for m in grid)


# -------------------------------------------------------------------------------------- deff


def test_deff_variance_inflation_cancels_in_certified_stop() -> None:
    mix = _mix()
    days = _two_leg_days(maker.build_maker_groups(mix, n_dates=200, seed=14))[:40]
    prepared = [prepare_day(d) for d in days]
    root = math.sqrt(maker.DEFF_CEILING)
    rng = np.random.default_rng(14)
    unit, inflated = [], []
    for _ in range(2000):
        zs1: list[float] = []
        zs15: list[float] = []
        for _t in range(60):
            prep = prepared[int(rng.integers(0, len(prepared)))]
            x = prep.xs[invert_cdf(prep.masses, float(rng.random()))]
            for sink, scale in ((zs1, 1.0), (zs15, maker.DEFF_CEILING)):
                step = step_clock(_normalised(prep.day.station, x, 0.0, prep.variance * scale), 0.0)
                assert step.is_tick and step.z is not None
                sink.append(step.z)
        unit.append(zs1)
        inflated.append(zs15)
    for z1, z15 in zip(unit, inflated, strict=True):
        assert np.allclose(np.array(z15), np.array(z1) / root, rtol=1e-12, atol=0)
    t_min = 5
    crit1 = np.array([critical_value(z, t_min=t_min) for z in unit])
    crit15 = np.array([critical_value(z, t_min=t_min) for z in inflated])
    assert np.allclose(crit15, crit1 / root, rtol=1e-12, atol=0)
    c = float(np.median(crit1))
    c_deff = c / root
    ties = int(np.sum(np.abs(crit1 - c) < 1e-9))
    assert ties == 0
    for z1, z15, k1, k15 in zip(unit, inflated, crit1, crit15, strict=True):
        a = first_crossing(z1, c=c, t_min=t_min) is not None
        b = first_crossing(z15, c=c_deff, t_min=t_min) is not None
        if a != b:
            assert abs(k1 - c) < 1e-9  # only an fp tie may disagree
    z = float(np.median([z[0] for z in unit]))
    assert fully_lost_fraction(z / root, c=c_deff, t_low=100) == pytest.approx(
        fully_lost_fraction(z, c=c, t_low=100), rel=1e-12
    )
    assert repeated_crossing(z / root, c=c_deff, t_min=t_min, t_low=100) == repeated_crossing(
        z, c=c, t_min=t_min, t_low=100
    )


# ---------------------------------------------------------------------------------- run_cell


def test_artifact_records_c_and_c_deff() -> None:
    cell = maker.run_cell(
        _mix(fill_rate=0.5),
        replicates=150,
        outer_resamples=0,
        outer_replicates=0,
        seed=maker.SEED,
        n_dates=120,
    )
    assert cell["floor_mode"] == "sqrt_boundary", cell
    assert cell["c"] is not None
    assert cell["c_deff"] == pytest.approx(cell["c"] / math.sqrt(1.5), rel=1e-14)
    assert cell["c_deff"] != cell["c"]
    assert (cell["k"], cell["b"], cell["f"]) == (2, 0.75, 0.5)
    assert cell["h1_fallback_share_by_delta"] == {"-0.16": 0.0, "-0.08": 0.0, "-0.04": 0.0}
    assert cell["certified_ticks"] == math.floor(
        110 * cell["lambda_sd"] * cell["p_keep_gate"] * cell["tick_share"]
    )
    assert cell["replicates"] == 150 and cell["seed"] == maker.SEED
