"""Review-round fixes for the floor MC. Each case was written against the blocked behaviour."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from breezy.analysis.fq_loss_stop_core import (
    VARIANCE_EPS,
    BuyFill,
    ExitFill,
    LegSettlement,
    normalise_station_day,
)
from scripts.analysis.fq_loss_floor_mc import build_parser, exit_code
from scripts.analysis.fq_loss_floor_mc_draw import prepare_day, resolved_half_spread
from scripts.analysis.fq_loss_floor_mc_engine import run_floor
from scripts.analysis.fq_loss_floor_mc_gate import AlphaEval, FloorConfig, select_alpha, t_low_count
from scripts.analysis.fq_loss_floor_mc_outer import c_mc_se_total
from scripts.analysis.fq_loss_floor_mc_rates import (
    LAMBDA_POOL_DEFINITION,
    POOL_EXIT_FRACTION_SOURCE,
    plan_floor_rates,
)
from scripts.analysis.fq_loss_floor_mc_report import h1_warning_lines, ticking_share
from scripts.analysis.fq_loss_floor_mc_rows import (
    kappa_exit,
    make_leg,
    make_station_day,
    production_variance,
    x_piece,
)
from scripts.analysis.fq_loss_floor_mc_sim import simulate_family
from scripts.analysis.fq_mc_livedata import (
    DEFAULT_PI_FAV,
    DayTemplate,
    PoolDay,
    TakeRecord,
    UnreachableTakeRate,
    calibrate_take_rate,
)


def _obj(value: object) -> dict[Any, Any]:
    assert isinstance(value, dict)
    return value


def _config(**overrides: object) -> FloorConfig:
    base: dict[str, object] = {
        "take_rate_lower": 0.25,
        "theta": 0.0,
        "lambda_pool": 0.40,
        "r_sd": 1.0,
        "lambda_sd": 1.0,
        "half_spread": 0.03,
        "pool_exit_fraction": 0.0,
        "rho_hat": None,
        "freeze": date(2026, 10, 8),
        "horizon": date(2026, 10, 10),
    }
    base.update(overrides)
    return FloorConfig(**base)  # type: ignore[arg-type]


def _alpha(**overrides: object) -> AlphaEval:
    base: dict[str, object] = {
        "alpha": 0.10,
        "g1_pass": True,
        "g1_margin": True,
        "g3_at_m016": 0.90,
        "s6_rate": 0.05,
        "s6_se": 0.01,
        "c": 1.5,
        "c_se": 0.04,
        "t_min": 1,
        "measured_power": {"-0.16": 0.90, "-0.08": 0.45, "-0.04": 0.20},
        "epoch_ok": {"2026-10-08": True},
    }
    base.update(overrides)
    return AlphaEval(**base)  # type: ignore[arg-type]


def test_unreachable_target_at_pi_one_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _empty(days: object, *, pi_fav: float, seed: int, cfg: object = None) -> list[DayTemplate]:
        del days, pi_fav, seed, cfg
        return [DayTemplate(date(2024, 1, 2), ())]

    monkeypatch.setattr("scripts.analysis.fq_mc_livedata.build_templates", _empty)
    day = PoolDay(climate_day=date(2024, 1, 2), stations=())
    with pytest.raises(UnreachableTakeRate, match="unreachable"):
        calibrate_take_rate((day,), target_rate=0.25, seed=1, require_reachable=True)


def test_lambda_pool_is_measured_before_either_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    def _build(
        days: object, *, pi_fav: float = DEFAULT_PI_FAV, seed: int, cfg: object = None
    ) -> list[DayTemplate]:
        del days, seed, cfg
        seen.append(pi_fav)
        take = TakeRecord("S", "R", "yes", 0.4, 0.45, 0.5, 0.1)
        kept = round(pi_fav * 20)
        return [
            DayTemplate(date(2024, 1, 2), (take,) if index < kept else ()) for index in range(20)
        ]

    monkeypatch.setattr("scripts.analysis.fq_mc_livedata.build_templates", _build)
    planned = plan_floor_rates(
        (PoolDay(climate_day=date(2024, 1, 2), stations=()),), take_rate_lower=0.25, seed=3
    )
    assert seen[0] == pytest.approx(DEFAULT_PI_FAV)
    assert planned.lambda_pool == pytest.approx(0.5)
    assert planned.rate_cal == pytest.approx(0.25)
    assert planned.rate_gate == pytest.approx(0.25)
    assert planned.achieved_rate_cal == pytest.approx(0.25)
    assert planned.achieved_rate_gate == pytest.approx(0.25)
    assert planned.definition == LAMBDA_POOL_DEFINITION
    assert 1.0 in seen  # the bisection starts at π = 1 only after the natural rate


def test_run_floor_emits_the_rate_fields_and_the_exit_source() -> None:
    day = make_station_day(
        "K",
        (make_leg("T70", "yes", 0.4, half_spread=0.04), make_leg("T71", "yes", 0.4)),
    )
    document = _obj(
        run_floor(
            ((day,),), replicates=4, seed=1, config=_config(), alphas=(0.10,), outer_resamples=0
        )
    )
    for key in (
        "lambda_pool",
        "lambda_pool_definition",
        "rate_cal",
        "rate_gate",
        "p_keep_cal",
        "p_keep_gate",
        "achieved_rate_cal",
        "achieved_rate_gate",
    ):
        assert key in document
    assert document["lambda_pool"] == pytest.approx(0.40)
    assert document["rate_cal"] == pytest.approx(0.25)
    assert document["rate_cal_rule"] == "E2"
    assert document["rate_gate"] == pytest.approx(0.25)
    assert document["lambda_pool_definition"] == LAMBDA_POOL_DEFINITION
    assert document["pool_exit_fraction_source"] == POOL_EXIT_FRACTION_SOURCE
    assert document["kappa_exit_fallback_share"] == pytest.approx(0.5)
    outcome = _obj(document["outcome"])
    assert "c_replicate_se" in outcome
    assert "c_template_sd" in outcome
    if outcome["c"] is not None:
        assert outcome["c_mc_se"] == pytest.approx(
            c_mc_se_total(float(outcome["c_replicate_se"]), float(outcome["c_template_sd"]))
        )


def test_outer_template_resample_enters_c_mc_se() -> None:
    day = make_station_day("K", (make_leg("T70", "yes", 0.45),))
    document = _obj(
        run_floor(
            ((day,), (day,)),
            replicates=4,
            seed=2,
            config=_config(),
            alphas=(0.10,),
            outer_resamples=3,
            outer_replicates=3,
        )
    )
    outcome = _obj(document["outcome"])
    assert document["outer_resamples"] == 3
    assert document["outer_replicates"] == 3
    quantiles = outcome["c_template_quantiles"]
    assert isinstance(quantiles, dict)
    assert set(quantiles) == {"p025", "p50", "p975"}
    assert outcome["c_template_sd"] >= 0.0
    if outcome["c"] is not None:
        assert outcome["c_mc_se"] == pytest.approx(
            math.sqrt(float(outcome["c_replicate_se"]) ** 2 + float(outcome["c_template_sd"]) ** 2)
        )


def test_s6_failure_nulls_floor_mode_and_blocks_the_freeze() -> None:
    outcome = select_alpha((_alpha(s6_rate=0.50, s6_se=0.01, c_se=0.04),))
    assert outcome.floor_mode is None
    assert outcome.power_class == "none"
    blocked = outcome.freeze_blocked
    assert blocked is not None
    assert blocked["reason"] == "s6_failed"
    body = outcome.as_dict()
    assert body["floor_mode"] is None
    assert _obj(body["freeze_blocked"])["reason"] == "s6_failed"
    assert exit_code({"outcome": body}) == 1


def test_s6_tolerance_uses_c_mc_se_not_the_binomial_se() -> None:
    # Binomial SE would accept 0.20 ≤ 0.10 + 3·0.05. c_se = 0.02 does not.
    outcome = select_alpha((_alpha(s6_rate=0.20, s6_se=0.05, c_se=0.02),))
    assert outcome.floor_mode is None
    assert outcome.freeze_blocked is not None
    assert outcome.freeze_blocked["reason"] == "s6_failed"


def test_a_passing_freeze_stays_in_the_spec_vocabulary() -> None:
    outcome = select_alpha((_alpha(),))
    assert outcome.floor_mode == "sqrt_boundary"
    assert outcome.power_class == "edge_capable"
    assert outcome.freeze_blocked is None
    assert exit_code({"outcome": outcome.as_dict()}) == 0


def test_t_low_counts_ticking_station_days_only() -> None:
    loud = make_station_day("K", (make_leg("T70", "yes", 0.5),))
    quiet = make_station_day("K", (), extra_netting=-0.2)
    assert production_variance(loud) > VARIANCE_EPS
    assert production_variance(quiet) <= VARIANCE_EPS
    share = ticking_share(((loud, quiet),))
    assert share == pytest.approx(0.5)
    assert t_low_count(10, 1.0, 1.0, tick_share=share) == 5
    assert t_low_count(10, 1.0, 1.0) == 10
    document = _obj(
        run_floor(
            ((loud, quiet),),
            replicates=4,
            seed=4,
            config=_config(lambda_pool=0.25, r_sd=1.0, lambda_sd=1.0),
            alphas=(0.10,),
            outer_resamples=0,
        )
    )
    expected = t_low_count(3, 1.0, 0.25, tick_share=0.5)
    assert document["gates"][0]["t_low"] == expected


def test_h1_bernoulli_fallback_is_counted_per_delta_and_warns() -> None:
    forced = make_station_day("K", (make_leg("A", "no", 0.55), make_leg("B", "no", 0.55)))
    prepared = prepare_day(forced, deltas=(-0.16,))
    assert prepared.h1[-0.16] is None
    forced_sim = simulate_family(
        ((prepared,),),
        replicates=3,
        n_days=2,
        p_keep=1.0,
        seed=1,
        row="H1",
        delta=-0.16,
    )
    assert forced_sim.h1_draws == 6
    assert forced_sim.h1_fallback_uses == 6
    yes = prepare_day(make_station_day("K", (make_leg("T70", "yes", 0.4),)), deltas=(-0.16,))
    assert yes.h1[-0.16] is not None
    quiet = simulate_family(
        ((yes,),), replicates=3, n_days=2, p_keep=1.0, seed=1, row="H1", delta=-0.16
    )
    assert quiet.h1_draws == 6
    assert quiet.h1_fallback_uses == 0
    assert h1_warning_lines({"-0.16": {"share": 0.0}}) == []
    warned = h1_warning_lines({"-0.16": {"share": 1.0}})
    assert len(warned) == 1
    assert "-0.16" in warned[0]


def test_kappa_exit_prefers_the_leg_spread_and_floors_at_two_cents() -> None:
    own, fell_back = resolved_half_spread(0.05, 0.01)
    assert fell_back is False
    assert kappa_exit(own) == pytest.approx(0.05)
    pooled, fell_back = resolved_half_spread(None, 0.08)
    assert fell_back is True
    assert kappa_exit(pooled) == pytest.approx(0.08)
    tiny, fell_back = resolved_half_spread(None, 0.01)
    assert fell_back is True
    assert kappa_exit(tiny) == pytest.approx(0.02)
    present, fell_back = resolved_half_spread(0.01, 0.08)
    assert fell_back is False
    assert kappa_exit(present) == pytest.approx(0.02)


def test_x_piece_matches_normalise_station_day_on_three_fixtures() -> None:
    def _buy(cost: str, qty: str = "1") -> BuyFill:
        return BuyFill(
            rung="T70",
            side="yes",
            qty=Decimal(qty),
            cost=Decimal(cost),
            fee=Decimal(0),
            fee_reconciled=True,
        )

    held = normalise_station_day(
        station="K",
        buys=(_buy("0.40"),),
        settlements=(LegSettlement(rung="T70", side="yes", held=True),),
    )
    lost = normalise_station_day(
        station="K",
        buys=(_buy("0.40"),),
        settlements=(LegSettlement(rung="T70", side="yes", held=False),),
    )
    partial = normalise_station_day(
        station="K",
        buys=(_buy("0.80", "2"),),
        settlements=(LegSettlement(rung="T70", side="yes", held=True),),
        exits=(
            ExitFill(
                rung="T70",
                side="yes",
                qty=Decimal(1),
                cost=Decimal("0.50"),
                fee=Decimal(0),
            ),
        ),
    )
    for day in (held, lost, partial):
        pieces = [x_piece(float(leg.h_eff), leg.be) for leg in day.legs]
        assert math.fsum(pieces) == pytest.approx(day.x_rand)
        assert day.legs


def test_outer_cli_defaults() -> None:
    args = build_parser().parse_args(["--seed", "1"])
    assert args.outer_resamples == 20
    assert args.outer_replicates == 2000
