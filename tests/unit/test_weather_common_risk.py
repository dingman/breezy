"""Unit tests for `breezy.strategy.weather_common.risk`.

Covers `edge_after_costs` (the executable-vs-midpoint edge calculation) and
the `RiskManager.evaluate_order` screening sequence, including the
event-grouping exclusivity check that replaced the bundle's
`WeatherContractRegistry` (see the module docstring for why the grouping
rule was simplified, and what that simplification does and does not change).
"""

from __future__ import annotations

import datetime as dt

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import MarketQuote
from breezy.strategy.weather_common.risk import (
    PortfolioSnapshot,
    RiskLimits,
    RiskManager,
    edge_after_costs,
)

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
NOW = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC)


def _contract(
    instrument_id: str, *, lower_f: int | None, upper_f: int | None,
) -> MispricingContract:
    return MispricingContract(
        instrument_id=instrument_id,
        facts=WeatherBucketFacts(
            settlement_station=STATION,
            climate_day=CLIMATE_DAY,
            measure=Measure.HIGH,
            lower_f=lower_f,
            upper_f=upper_f,
        ),
        tick_size=0.01,
    )


def _quote(*, bid: float = 0.40, ask: float = 0.42) -> MarketQuote:
    return MarketQuote(
        instrument_id="ANY",
        bid=bid,
        ask=ask,
        bid_size=100.0,
        ask_size=100.0,
        ts_event=NOW,
    )


# ---------------------------------------------------------------------------
# edge_after_costs
# ---------------------------------------------------------------------------


def test_long_edge_is_model_minus_ask_minus_cost() -> None:
    edge = edge_after_costs(model_p=0.70, bid_p=0.55, ask_p=0.60, intent_long_yes=True, cost=0.01)
    assert edge == 0.70 - 0.60 - 0.01


def test_short_edge_is_bid_minus_model_minus_cost() -> None:
    edge = edge_after_costs(model_p=0.30, bid_p=0.45, ask_p=0.50, intent_long_yes=False, cost=0.01)
    assert edge == 0.45 - 0.30 - 0.01


def test_long_edge_is_none_without_an_ask() -> None:
    edge = edge_after_costs(model_p=0.70, bid_p=0.55, ask_p=None, intent_long_yes=True, cost=0.01)
    assert edge is None


def test_short_edge_is_none_without_a_bid() -> None:
    edge = edge_after_costs(model_p=0.30, bid_p=None, ask_p=0.50, intent_long_yes=False, cost=0.01)
    assert edge is None


# ---------------------------------------------------------------------------
# RiskManager.evaluate_order -- the screening sequence
# ---------------------------------------------------------------------------


def test_settlement_halt_blocks_regardless_of_edge() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=0.1,  # below default halt_hours_before_settlement=1.0
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
    )

    assert decision.allowed is False
    assert decision.reason == "settlement_halt"


def test_edge_below_minimum_is_blocked() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.01,  # below default min_model_edge=0.04
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
    )

    assert decision.allowed is False
    assert decision.reason == "edge_below_minimum"


def test_a_well_formed_order_within_every_limit_is_allowed() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == 10.0


def test_a_second_long_yes_on_the_same_climate_day_is_an_exclusive_conflict() -> None:
    """Two buckets settling off the SAME station/climate-day are exclusive.

    See the module docstring: this is a deliberate simplification of the
    bundle's `WeatherContractRegistry` grouping, and is strictly more
    conservative than it (it can only block more redundant same-direction
    exposure, never less).
    """
    bucket_a = _contract("A", lower_f=80, upper_f=None)
    bucket_b = _contract("B", lower_f=85, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": bucket_a, "B": bucket_b})
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0})

    decision = risk.evaluate_order(
        contract=bucket_b,
        signed_qty_delta=5.0,  # a NEW long YES on B, while A is already long
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
    )

    assert decision.allowed is False
    assert decision.reason == "exclusive_bucket_conflict"


def test_buckets_on_different_climate_days_are_not_exclusive() -> None:
    bucket_a = _contract("A", lower_f=80, upper_f=None)
    bucket_other_day = MispricingContract(
        instrument_id="C",
        facts=WeatherBucketFacts(
            settlement_station=STATION,
            climate_day=CLIMATE_DAY + dt.timedelta(days=1),
            measure=Measure.HIGH,
            lower_f=80,
            upper_f=None,
        ),
        tick_size=0.01,
    )
    risk = RiskManager(RiskLimits(), {"A": bucket_a, "C": bucket_other_day})
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0})

    decision = risk.evaluate_order(
        contract=bucket_other_day,
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
    )

    assert decision.allowed is True


def test_shorting_a_flat_instrument_is_blocked_when_shorts_are_disabled() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(allow_short=False), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-10.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
    )

    assert decision.allowed is False
    assert decision.reason == "shorts_disabled"
