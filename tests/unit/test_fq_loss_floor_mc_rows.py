"""Floor-MC rows: clamp, carry, refusal, κ_exit, copula floor, outcome keys."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pytest

from breezy.analysis.fq_loss_stop_core import ReasonCode
from breezy.analysis.fq_loss_stop_shrink import shrunk_joint
from breezy.strategy.weather_common.costs import venue_fee_prob
from scripts.analysis.fq_loss_floor_mc import build_parser, default_out
from scripts.analysis.fq_loss_floor_mc_engine import run_floor
from scripts.analysis.fq_loss_floor_mc_gate import FloorConfig
from scripts.analysis.fq_loss_floor_mc_rows import (
    all_lose_z,
    apply_mix,
    clamped_leg_share,
    estimate_rho,
    exit_coefficient,
    exit_probability,
    h1_win_probability,
    kappa_exit,
    make_leg,
    make_station_day,
    partition_station_days,
    production_variance,
    rho_bind,
    stratum_rows,
    template_overround,
    walk_fixed,
)


def _obj_dict(value: object) -> dict[Any, Any]:
    assert isinstance(value, dict)
    return value


def test_kappa_exit_floors_the_half_spread_and_the_fee_is_added() -> None:
    assert kappa_exit(None) == pytest.approx(0.02)
    assert kappa_exit(0.01) == pytest.approx(0.02)
    assert kappa_exit(0.05) == pytest.approx(0.05)
    fee = venue_fee_prob(executable_price=0.4, fee_coefficient=0.0695)
    assert exit_coefficient(0.05, price=0.4, theta=0.0695) == pytest.approx(0.05 + fee)
    assert exit_probability(0.0) == pytest.approx(0.10)
    assert exit_probability(0.25) == pytest.approx(0.25)


def test_rho_bind_floors_at_a_quarter() -> None:
    assert rho_bind(None) == pytest.approx(0.25)
    assert rho_bind(0.10) == pytest.approx(0.25)
    assert rho_bind(-0.4) == pytest.approx(0.25)
    assert rho_bind(0.40) == pytest.approx(0.40)
    pits = [(0.1 + 0.01 * i, 0.1 + 0.01 * i) for i in range(8)]
    assert estimate_rho(pits) == pytest.approx(1.0)


def test_h1_clamp_is_non_negative_and_the_share_is_reported() -> None:
    assert h1_win_probability(0.10, delta=-0.16) == 0.0
    assert h1_win_probability(0.40, delta=-0.16) == pytest.approx(0.24)
    legs = (make_leg("A", "yes", 0.10), make_leg("B", "no", 0.40))
    assert clamped_leg_share(legs, delta=-0.16) == pytest.approx(0.5)
    assert h1_win_probability(0.01, delta=-0.16) >= 0.0


def test_carry_enters_the_next_tick_and_the_ratio_is_reported() -> None:
    quiet = make_station_day("K", (), extra_netting=-0.3)
    loud = make_station_day("K", (make_leg("T70", "yes", 0.5),))
    carried = walk_fixed(((quiet, None), (loud, (0.0,))))
    dropped = walk_fixed(((quiet, None), (loud, (0.0,))), drop_carry=True)
    assert carried.increments == pytest.approx((-1.6,))
    assert carried.max_abs_carry_over_sigma == pytest.approx(0.6)
    assert carried.mean_carry == pytest.approx(-0.3)
    assert dropped.increments == pytest.approx((-1.0,))
    assert all_lose_z(loud) == pytest.approx(-1.0)


def test_refused_template_is_reported_not_dropped() -> None:
    bad = make_station_day("K", tuple(make_leg(f"T{i}", "no", 0.2) for i in range(3)))
    good = make_station_day("K", (make_leg("T70", "yes", 0.4),))
    admitted, refused = partition_station_days((bad, good))
    assert [day.station for day in admitted] == ["K"]
    assert admitted[0].legs[0].rung == "T70"
    assert len(refused) == 1
    assert refused[0].station == "K"
    assert refused[0].reason == ReasonCode.SIGMA_NO_EXCEEDS_ONE.value
    assert "T0" in refused[0].rungs


def test_overround_variance_is_the_production_shrink() -> None:
    day = make_station_day("K", (make_leg("A", "yes", 0.8), make_leg("B", "yes", 0.8)))
    rows = stratum_rows(day)
    joint = shrunk_joint(rows)
    assert production_variance(day) == pytest.approx(joint.variance)
    share, mean_kappa = template_overround((day,))
    assert share == pytest.approx(1.0)
    assert mean_kappa == pytest.approx(joint.kappa)


def test_mixes_drop_the_other_side_and_the_pair() -> None:
    paired = make_station_day(
        "K",
        (make_leg("T70", "yes", 0.4), make_leg("T70", "no", 0.4), make_leg("T80", "yes", 0.3)),
    )
    assert paired.netting == pytest.approx(1.0 - 0.4 - 0.4)
    assert [leg.rung for leg in paired.legs] == ["T80"]
    yes_only = apply_mix(paired, "M-yes")
    no_only = apply_mix(paired, "M-no")
    assert [leg.side for leg in yes_only.legs] == ["yes"]
    assert yes_only.netting == 0.0
    assert no_only.legs == ()
    assert apply_mix(paired, "M-pool").legs == paired.legs


def test_run_floor_reports_a_refused_template_and_does_not_freeze() -> None:
    bad = make_station_day("K", tuple(make_leg(f"T{i}", "no", 0.2) for i in range(3)))
    good = make_station_day("K", (make_leg("T70", "yes", 0.4),))
    config = FloorConfig(
        take_rate_lower=0.25,
        theta=0.0695,
        lambda_pool=0.25,
        r_sd=1.0,
        lambda_sd=1.0,
        half_spread=None,
        pool_exit_fraction=0.0,
        rho_hat=None,
        freeze=date(2026, 10, 8),
        horizon=date(2026, 10, 12),
    )
    document = _obj_dict(run_floor(((bad, good),), replicates=4, seed=2, config=config))
    assert document["refused_count"] == 1
    assert document["refused_templates"][0]["reason"] == "sigma_no_exceeds_one"
    assert document["outcome"]["floor_mode"] == "refused_templates"
    assert document["outcome"]["c"] is None


def test_run_floor_outcome_has_the_pinned_fields() -> None:
    day = make_station_day("K", (make_leg("T70", "yes", 0.45),))
    config = FloorConfig(
        take_rate_lower=0.25,
        theta=0.0,
        lambda_pool=0.25,
        r_sd=1.0,
        lambda_sd=1.0,
        half_spread=0.03,
        pool_exit_fraction=0.0,
        rho_hat=0.1,
        freeze=date(2026, 10, 8),
        horizon=date(2026, 10, 11),
    )
    document = _obj_dict(run_floor(((day,),), replicates=6, seed=5, config=config, alphas=(0.10,)))
    outcome = document["outcome"]
    for key in (
        "floor_mode",
        "power_class",
        "alpha_star",
        "c",
        "c_mc_se",
        "t_min",
        "measured_power",
        "s6_feasible_rate",
        "reach_cutoff_epoch_start",
    ):
        assert key in outcome
    assert outcome["escalated_on_g3"] is False
    assert outcome["floor_mode"] in {"sqrt_boundary", "unreachable_veto", "s6_stop"}
    if outcome["floor_mode"] == "sqrt_boundary":
        assert outcome["c"] is not None and outcome["c"] > 0.0
        assert math.isfinite(outcome["c_mc_se"])
    else:
        assert outcome["c"] is None
    assert document["rows"]
    assert {row["row"] for row in document["rows"]} >= {"H0", "S1", "S2", "S3", "S4", "S5", "S6"}
    assert document["max_abs_carry_over_sigma_next"] >= 0.0


def test_parser_requires_a_seed_and_defaults_the_ladder() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
    args = build_parser().parse_args(["--seed", "11"])
    assert args.replicates == 10000
    assert args.subset_benchmark is False
    assert args.alpha is None
    assert args.max_memory_gib == pytest.approx(8.0)
    assert default_out(11).name == "fq_loss_floor_mc_seed11.json"
