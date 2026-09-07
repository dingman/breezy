"""T3, T4, T6, T8: unified cost, margin, ranking, Kelly (spec §4–§7)."""

from __future__ import annotations

from datetime import date

import pytest

from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.scoring import (
    OpportunityRow,
    ev_net,
    kelly_stake_fraction,
    margin,
    rank_rows,
    unified_cost,
)
from breezy.strategy.weather_common.costs import depth_aware_trade_cost_prob

_THREE_LEVEL_LADDER: tuple[tuple[float, float], ...] = (
    (0.50, 1.0),
    (0.51, 2.0),
    (0.52, 5.0),
)


def _row(**overrides: object) -> OpportunityRow:
    values: dict[str, object] = {
        "instrument_id": "MDW-D-80-81",
        "station": "MDW",
        "climate_day": date(2026, 9, 5),
        "ev_net": 0.05,
        "C": 0.50,
        "h_hours": 8.0,
        "fillable_qty": 4.0,
        "p_hat": 0.70,
        "p_lower": 0.65,
    }
    values.update(overrides)
    return OpportunityRow(**values)  # type: ignore[arg-type]


def test_unified_cost_equals_tob_plus_total_prob_on_a_three_level_walk() -> None:
    cost = depth_aware_trade_cost_prob(
        ask_levels=_THREE_LEVEL_LADDER,
        quantity=1.0,
        price_scale=1.0,
        fee_coefficient=0.06,
        slippage_floor_prob=0.01,
    )
    assert unified_cost(cost) == pytest.approx(cost.top_of_book_price + cost.total_prob)
    p_lower = 0.72
    net = ev_net(p_lower, cost)
    assert net is not None
    assert net == pytest.approx(p_lower - unified_cost(cost), abs=1e-12)


def test_margin_interpolates_and_caps_and_is_none_below_n_min() -> None:
    cfg = LadderEvConfig()
    assert margin(6.0, 200, cfg) == pytest.approx(0.02)
    assert margin(12.0, 200, cfg) == pytest.approx(0.02 + 0.04 * (6.0 / 18.0))
    assert margin(24.0, 200, cfg) == pytest.approx(0.06)
    assert margin(48.0, 200, cfg) == pytest.approx(0.06)
    assert margin(12.0, 89, cfg) is None


def test_ranking_prefers_absolute_ev_net_over_roi_and_applies_city_day_cap() -> None:
    cfg = LadderEvConfig()
    lottery = _row(
        instrument_id="MDW-D-lt70",
        ev_net=0.02,
        C=0.03,
        p_hat=0.10,
        p_lower=0.10,
        fillable_qty=10.0,
        h_hours=10.0,
    )
    rung = _row(
        instrument_id="MDW-D-80-81",
        ev_net=0.05,
        C=0.50,
        p_hat=0.70,
        p_lower=0.70,
        fillable_qty=2.0,
        h_hours=10.0,
    )
    ranked = rank_rows((lottery, rung), cfg)
    assert ranked[0].instrument_id == "MDW-D-80-81"
    assert ranked[0].rank == 1
    # Same city-day: the lottery is the second YES and is capped (λ_c = 1).
    assert ranked[1].instrument_id == "MDW-D-lt70"
    assert ranked[1].score == pytest.approx(0.0)

    other_city = _row(
        instrument_id="LAX-D-80-81",
        station="LAX",
        ev_net=0.04,
        C=0.40,
        p_hat=0.60,
        p_lower=0.60,
    )
    ranked_two_cities = rank_rows((lottery, rung, other_city), cfg)
    ids = [row.instrument_id for row in ranked_two_cities if row.score and row.score > 0.0]
    assert "MDW-D-80-81" in ids
    assert "LAX-D-80-81" in ids
    assert "MDW-D-lt70" not in ids


def test_kelly_stake_fraction_returns_kappa_times_f_star() -> None:
    disabled = LadderEvConfig()
    assert kelly_stake_fraction(0.60, 0.40, disabled) == pytest.approx(1.0)
    enabled = LadderEvConfig(kelly_enabled=True)
    # Returns κ · f* with f* = (P − C) / (1 − C) = 0.25 · 0.20 / 0.60
    assert kelly_stake_fraction(0.60, 0.40, enabled) == pytest.approx(0.25 * 0.20 / 0.60)
