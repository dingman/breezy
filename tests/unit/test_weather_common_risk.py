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
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.weather_common import risk as risk_module
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import MarketQuote
from breezy.strategy.weather_common.refusals import SHORTS_DISABLED, RefusalCounter
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
        quote_age_minutes=0.0,
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
        quote_age_minutes=0.0,
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
        quote_age_minutes=0.0,
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
        quote_age_minutes=0.0,
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
        quote_age_minutes=0.0,
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
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "shorts_disabled"


# ---------------------------------------------------------------------------
# Close-only: the ONLY naked-short control there is
# ---------------------------------------------------------------------------
#
# `nautilus_trader==1.231.0` denies no naked short of its own:
# `risk/engine.pyx:974-985` exempts a position-REDUCING sell outright, and a
# position-OPENING sell is denied only by `CUM_NOTIONAL_EXCEEDS_FREE_BALANCE`,
# itself gated on `not allow_borrowing` -- and on a CASH account
# `CashAccount.balance_impact` returns +notional for a SELL, so that gate
# cannot fire either. These tests therefore pin a control with nothing behind
# it, not a defence-in-depth layer.


def test_shorting_from_flat_is_refused_under_the_bare_default_limits() -> None:
    """The DEFAULT limits must refuse it -- no argument, no override, no config."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-10.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "shorts_disabled"


def test_a_pending_buy_cannot_unlock_a_sell_that_opens_a_short() -> None:
    """Close-only is evaluated against SETTLED position, never against `net_qty`.

    `net_qty` is `position_qty + pending_qty` and `pending_qty` is SIGNED, so a
    pending BUY inflates it. Reading the guard off `net_qty` let a sell that
    takes the settled position below zero pass: 10 held + 50 pending buy = 60,
    against which a 40-lot sell "reduces". It does not -- it opens a 30-lot
    naked short the instant it fills, and the pending buy may never fill at
    all. A pending buy is not inventory.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(allow_short=False), {"A": contract})
    portfolio = PortfolioSnapshot(
        position_qty={"A": 10.0},
        pending_qty={"A": 50.0},  # a WORKING BUY, not inventory
    )

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-40.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "shorts_disabled"


def test_a_sell_that_exactly_closes_a_long_is_allowed_at_the_boundary() -> None:
    """Close-only must not become refuse-all: that strands every open position."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-10.0,  # exactly flat afterwards
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == -10.0


def test_a_partial_close_is_allowed() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-4.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == -4.0


def test_a_sell_one_contract_past_flat_is_refused_at_the_boundary() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-11.0,  # one contract past flat
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "shorts_disabled"


def test_a_shorts_disabled_refusal_is_recorded_on_the_counter() -> None:
    """A refusal nobody can count is a strategy that silently does nothing."""
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": contract}, refusals=counter)

    risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-10.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert counter.count(SHORTS_DISABLED) == 1


def test_an_allowed_order_records_no_refusal() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": contract}, refusals=counter)

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert counter.count(SHORTS_DISABLED) == 0


# ---------------------------------------------------------------------------
# `allow_short=True` is unreachable from any DEFAULT construction path
# ---------------------------------------------------------------------------


def test_bare_risk_limits_forbid_shorting() -> None:
    assert RiskLimits().allow_short is False


def test_no_strategy_config_default_permits_shorting() -> None:
    """All three strategy configs, at their defaults, off the same rule.

    Asserted on the config OBJECTS rather than on source text: a default that
    flips back to `True` fails here regardless of how it is spelled.
    """
    assert CalibrationMeanReversionConfig(instrument_ids=()).allow_short is False
    assert ForecastMispricingConfig(instrument_ids=()).allow_short is False
    assert ForecastRevisionConfig(instrument_ids=()).allow_short is False


# ---------------------------------------------------------------------------
# `exclusive_conflict` is UNTOUCHED by the close-only fix -- characterization
# ---------------------------------------------------------------------------


def test_exclusive_conflict_still_counts_a_pending_long_on_a_sibling_bucket() -> None:
    """Deliberately still `net_qty`, pending included, and this is correct.

    The close-only fix narrows the SHORT guard to settled position only. It
    must not narrow this one: a working BUY on a sibling bucket is exactly the
    second long-YES on one climate day that this rule exists to prevent, and
    waiting for it to fill before noticing would be too late.
    """
    bucket_a = _contract("A", lower_f=80, upper_f=None)
    bucket_b = _contract("B", lower_f=85, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": bucket_a, "B": bucket_b})
    portfolio = PortfolioSnapshot(pending_qty={"A": 10.0})  # working BUY, unfilled

    decision = risk.evaluate_order(
        contract=bucket_b,
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "exclusive_bucket_conflict"


def test_exclusive_conflict_ignores_a_reducing_or_short_delta() -> None:
    bucket_a = _contract("A", lower_f=80, upper_f=None)
    bucket_b = _contract("B", lower_f=85, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": bucket_a, "B": bucket_b})
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0, "B": 8.0})

    assert risk.exclusive_conflict(bucket_b, -5.0, portfolio) is False
    assert risk.exclusive_conflict(bucket_b, 5.0, portfolio) is True


# ---------------------------------------------------------------------------
# Shared cross-strategy max-payout exposure
# ---------------------------------------------------------------------------


def test_three_strategy_managers_share_the_same_event_notional_cap() -> None:
    """Regression for BL-3: three isolated managers admit 3x the event cap."""
    contracts = [
        _contract("A", lower_f=80, upper_f=81),
        _contract("B", lower_f=82, upper_f=83),
        _contract("C", lower_f=84, upper_f=85),
    ]
    limits = RiskLimits(
        max_event_notional=2.0,
        max_location_notional=100.0,
        max_position_contracts=100.0,
        max_equity_fraction=1.0,
        allow_overlapping_exclusive_yes=True,
    )
    shared_exposure_cls = getattr(risk_module, "SharedExposureView", None)
    shared_exposure = shared_exposure_cls() if shared_exposure_cls is not None else None

    managers = []
    for contract in contracts:
        kwargs = {}
        if shared_exposure is not None:
            kwargs["exposure_view"] = shared_exposure
        managers.append(RiskManager(limits, {contract.instrument_id: contract}, **kwargs))

    portfolio = PortfolioSnapshot(equity=10_000.0)
    decisions = []
    for contract, manager in zip(contracts, managers, strict=True):
        decision = manager.evaluate_order(
            contract=contract,
            signed_qty_delta=1.0,
            hours_to_settlement=24.0,
            forecast_age_hours=0.0,
            edge=0.50,
            portfolio=portfolio,
            quote=_quote(),
            quote_age_minutes=0.0,
        )
        decisions.append(decision)
        if decision.allowed:
            portfolio.pending_qty[contract.instrument_id] = decision.clipped_quantity

    assert [decision.reason for decision in decisions] == [
        "ok",
        "ok",
        "max_event_notional",
    ]


def test_single_strategy_event_notional_boundary_is_unchanged() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(
        RiskLimits(
            max_event_notional=2.0,
            max_location_notional=100.0,
            max_position_contracts=100.0,
            max_equity_fraction=1.0,
        ),
        {"A": contract},
    )

    boundary = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=1.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(pending_qty={"A": 1.0}, equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )
    over = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=1.0,
        hours_to_settlement=24.0,
        forecast_age_hours=0.0,
        edge=0.50,
        portfolio=PortfolioSnapshot(pending_qty={"A": 2.0}, equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert boundary.allowed is True
    assert boundary.clipped_quantity == 1.0
    assert over.allowed is False
    assert over.reason == "max_event_notional"
