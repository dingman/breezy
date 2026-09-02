"""Unit tests for `breezy.strategy.weather_common.risk`.

Covers `edge_after_costs` (the executable-vs-midpoint edge calculation) and
the `RiskManager.evaluate_order` screening sequence, including the
event-grouping exclusivity check that replaced the bundle's
`WeatherContractRegistry` (see the module docstring for why the grouping
rule was simplified, and what that simplification does and does not change).
"""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.weather_common import risk as risk_module
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.freshness import SignalFreshness, SignalKind
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

#: The unit-of-work under test in almost every case below is the screening
#: sequence AFTER the staleness step, not staleness itself -- so a single
#: always-fresh `SignalFreshness` constant keeps those call sites a one-line
#: mechanical edit (R2 in the plan) instead of constructing a fresh value 30+
#: times over. Tests that exercise staleness itself build their own.
FRESH = SignalFreshness.forecast(0.0)


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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
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
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert counter.count(SHORTS_DISABLED) == 0


# ---------------------------------------------------------------------------
# BL-8 -- every `evaluate_order` refusal is counted, not just `shorts_disabled`
# ---------------------------------------------------------------------------
#
# `evaluate_order` is only ever invoked once a strategy's decision layer has
# already formed a non-`FLAT`, non-`None` `SignalDecision` and is attempting
# to submit it (see `RiskManager._refuse`'s docstring for the call-site
# proof). Every refusal below therefore blocks an order the strategy
# actually tried to place -- a gag, not "no opportunity" -- and must count.


def test_stale_quote_refusal_is_recorded_on_the_counter() -> None:
    """A gagged run must be distinguishable from an efficient market.

    Regression for BL-8: `quote_tradable`'s `stale_quote` reason reaches
    `evaluate_order` but was never recorded, so a run refused on every tick
    for a stale quote reported a clean, unqualified `COMPLETED`.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": contract}, refusals=counter)

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=999.0,  # far past the default 15-minute limit
    )

    assert decision.allowed is False
    assert decision.reason == "stale_quote"
    assert counter.count("stale_quote") == 1


def test_max_event_notional_refusal_is_recorded_on_the_counter() -> None:
    """Regression for BL-8: notional-cap refusals were silently uncounted."""
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(
        RiskLimits(max_event_notional=1.0, max_location_notional=100.0),
        {"A": contract},
        refusals=counter,
    )

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "max_event_notional"
    assert counter.count("max_event_notional") == 1


def test_max_location_notional_refusal_is_recorded_on_the_counter() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(
        RiskLimits(max_event_notional=100.0, max_location_notional=1.0),
        {"A": contract},
        refusals=counter,
    )

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "max_location_notional"
    assert counter.count("max_location_notional") == 1


def test_max_position_refusal_is_recorded_on_the_counter() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(
        RiskLimits(max_position_contracts=5.0),
        {"A": contract},
        refusals=counter,
    )
    portfolio = PortfolioSnapshot(position_qty={"A": 5.0})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=1.0,  # already at the cap; no room left
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "max_position"
    assert counter.count("max_position") == 1


def test_exclusive_bucket_conflict_refusal_is_recorded_on_the_counter() -> None:
    bucket_a = _contract("A", lower_f=80, upper_f=None)
    bucket_b = _contract("B", lower_f=85, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": bucket_a, "B": bucket_b}, refusals=counter)
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0})

    decision = risk.evaluate_order(
        contract=bucket_b,
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert counter.count("exclusive_bucket_conflict") == 1


def test_settlement_halt_refusal_is_recorded_on_the_counter() -> None:
    """One of the "earlier gates" BL-8 calls out by name."""
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": contract}, refusals=counter)

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=0.1,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert counter.count("settlement_halt") == 1


def test_edge_below_minimum_refusal_is_recorded_on_the_counter() -> None:
    """The other "earlier gate" BL-8 calls out by name."""
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": contract}, refusals=counter)

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.01,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert counter.count("edge_below_minimum") == 1


def test_wide_spread_refusals_collapse_to_one_bounded_counter_key() -> None:
    """`quote_tradable` composes `f"spread_{spread:.3f}"` -- a raw record of
    that string would grow one counter key per distinct spread value ever
    observed, an unbounded key space keyed by market noise. Every wide-spread
    refusal, regardless of the measured spread, must land on ONE key.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(max_bid_ask_spread=0.01), {"A": contract}, refusals=counter)

    first = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(bid=0.40, ask=0.42),  # spread 0.02
        quote_age_minutes=0.0,
    )
    second = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(bid=0.30, ask=0.40),  # spread 0.10, a DIFFERENT value
        quote_age_minutes=0.0,
    )

    assert first.allowed is False
    assert first.reason == "spread_0.020"  # outward reason keeps the value
    assert second.allowed is False
    assert second.reason == "spread_0.100"
    assert counter.count("wide_spread") == 2  # both land on the one bounded key
    assert "spread_0.020" not in counter.counts
    assert "spread_0.100" not in counter.counts


# ---------------------------------------------------------------------------
# BL-9 -- a future-dated quote (negative age) must not fail open as fresh
# ---------------------------------------------------------------------------


def test_asks_only_quote_is_tradable_when_ask_liquidity_clears_the_floor() -> None:
    """A long-only taker does not need a bid. Spread is undefined, not ask-0."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})
    quote = MarketQuote(
        instrument_id="ANY",
        bid=None,
        ask=0.50,
        bid_size=None,
        ask_size=100.0,
        ts_event=NOW,
    )

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=quote,
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True


def test_asks_only_quote_is_not_a_wide_spread_against_a_synthetic_zero_bid() -> None:
    """Reading the size-0 pad as bid=0 makes spread=ask, which always fails
    ``max_bid_ask_spread``. That is the fabricated-price sibling, not a real
    wide book.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(max_bid_ask_spread=0.06), {"A": contract})
    ok, why = risk.quote_tradable(
        MarketQuote(
            instrument_id="ANY",
            bid=None,
            ask=0.50,
            bid_size=None,
            ask_size=100.0,
            ts_event=NOW,
        ),
        1.0,
        0.0,
    )

    assert ok is True
    assert why == "ok"


def test_a_buy_on_a_bids_only_book_is_refused_as_missing_the_executable_side() -> None:
    """quote_tradable may skip spread on a one-sided book; a BUY still needs an ask."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})
    quote = MarketQuote(
        instrument_id="ANY",
        bid=0.40,
        ask=None,
        bid_size=100.0,
        ask_size=None,
        ts_event=NOW,
    )

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=quote,
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "missing_bid_ask"


def test_a_reducing_sell_on_an_asks_only_book_is_refused_as_missing_the_executable_side() -> None:
    """A close-only sell executes at the bid. An absent bid is not a 0.00 price."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})
    quote = MarketQuote(
        instrument_id="ANY",
        bid=None,
        ask=0.50,
        bid_size=None,
        ask_size=100.0,
        ts_event=NOW,
    )

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(position_qty={"A": 10.0}),
        quote=quote,
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "missing_bid_ask"


def test_bids_only_quote_uses_bid_liquidity_and_does_not_invent_an_ask() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})
    ok, why = risk.quote_tradable(
        MarketQuote(
            instrument_id="ANY",
            bid=0.40,
            ask=None,
            bid_size=100.0,
            ask_size=None,
            ts_event=NOW,
        ),
        1.0,
        0.0,
    )

    assert ok is True
    assert why == "ok"


def test_a_thin_real_two_sided_book_is_still_tradable() -> None:
    """Size 30 is small, but it is a real level, not a pad. Do not over-correct."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(min_liquidity_contracts=25.0), {"A": contract})
    ok, why = risk.quote_tradable(
        MarketQuote(
            instrument_id="ANY",
            bid=0.40,
            ask=0.42,
            bid_size=30.0,
            ask_size=30.0,
            ts_event=NOW,
        ),
        1.0,
        0.0,
    )

    assert ok is True
    assert why == "ok"


def test_a_future_dated_quote_is_refused_as_future_quote() -> None:
    """`now_ts_age_minutes` negative means `quote.ts_event` is AHEAD of
    `now` -- clock skew or a bad feed timestamp, not freshness. Before the
    fix, `now_ts_age_minutes > stale_quote_minutes` was the only staleness
    check, and a negative age never exceeds a positive threshold, so the
    quote was silently accepted as fresh.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": contract}, refusals=counter)

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=-1440.0,  # quote.ts_event is a full day in the future
    )

    assert decision.allowed is False
    assert decision.reason == "future_quote"
    assert counter.count("future_quote") == 1


def test_zero_age_quote_is_still_accepted() -> None:
    """Boundary proof: the fix must not over-tighten `now_ts_age_minutes == 0`."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True


def test_small_positive_age_within_the_stale_bound_is_still_accepted() -> None:
    """Boundary proof: an ordinary fresh quote must not be caught by BL-9."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})  # stale_quote_minutes default 15.0

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=5.0,
    )

    assert decision.allowed is True


def test_age_exactly_at_the_stale_quote_boundary_is_still_accepted() -> None:
    """The pre-existing `>` (not `>=`) boundary at `stale_quote_minutes` is
    unchanged by BL-9 -- this pins that BL-9 touched only the negative side.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(stale_quote_minutes=15.0), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=15.0,
    )

    assert decision.allowed is True


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
        signal_age=FRESH,
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
            signal_age=FRESH,
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
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(pending_qty={"A": 1.0}, equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )
    over = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=1.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(pending_qty={"A": 2.0}, equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert boundary.allowed is True
    assert boundary.clipped_quantity == 1.0
    assert over.allowed is False
    assert over.reason == "max_event_notional"


# ---------------------------------------------------------------------------
# Observation-freshness plan, C3: pins that `age_hours == stale_forecast_hours`
# is ACCEPTED under the `>` (not `>=`) boundary -- unchanged by the
# `forecast_age_hours` -> `signal_age: SignalFreshness` rewrite. Confirmed
# green against the OLD `forecast_age_hours=8.0` signature BEFORE the rewrite
# landed (see the task's RED/GREEN verification report); this is that same
# test ported to the new signature, proving the rewrite is algebraically a
# no-op for the FORECAST kind.
# ---------------------------------------------------------------------------


def test_forecast_age_exactly_at_the_stale_forecast_boundary_is_accepted() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(stale_forecast_hours=8.0), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=SignalFreshness.forecast(8.0),  # exactly at the boundary
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True


# ---------------------------------------------------------------------------
# C2 -- `stale_observation_hours` fail-closed default, and no shipped config
# declares one (the missing half of the `allow_short` discipline, applied to
# the new field: see `test_bare_risk_limits_forbid_shorting` /
# `test_no_strategy_config_default_permits_shorting` above).
# ---------------------------------------------------------------------------


def test_bare_risk_limits_defaults_stale_observation_hours_to_none() -> None:
    assert RiskLimits().stale_observation_hours is None


def test_no_strategy_config_declares_a_stale_observation_hours_default() -> None:
    """No shipped strategy is observation-driven yet (see the plan's blast
    radius): none of the three configs should carry this field at all, so a
    future strategy that silently starts is impossible to miss here.
    """
    assert not hasattr(CalibrationMeanReversionConfig(instrument_ids=()), "stale_observation_hours")
    assert not hasattr(ForecastMispricingConfig(instrument_ids=()), "stale_observation_hours")
    assert not hasattr(ForecastRevisionConfig(instrument_ids=()), "stale_observation_hours")


# ---------------------------------------------------------------------------
# `RiskLimits.max_signal_age_hours` -- the FORECAST/OBSERVATION selector
# ---------------------------------------------------------------------------


def test_max_signal_age_hours_selects_stale_forecast_hours_for_forecast_kind() -> None:
    limits = RiskLimits(stale_forecast_hours=6.0, stale_observation_hours=3.0)
    assert limits.max_signal_age_hours(SignalKind.FORECAST) == 6.0


def test_max_signal_age_hours_selects_stale_observation_hours_for_observation_kind() -> None:
    limits = RiskLimits(stale_forecast_hours=6.0, stale_observation_hours=3.0)
    assert limits.max_signal_age_hours(SignalKind.OBSERVATION) == 3.0


def test_max_signal_age_hours_is_none_for_observation_kind_on_bare_limits() -> None:
    assert RiskLimits().max_signal_age_hours(SignalKind.OBSERVATION) is None


# ---------------------------------------------------------------------------
# Observation-driven freshness screening (plan P3, corrections C1/C2/C3/C7)
# ---------------------------------------------------------------------------


def test_observation_signal_older_than_the_bound_is_refused_as_stale_observation() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(
        RiskLimits(stale_observation_hours=2.0), {"A": contract}, refusals=counter,
    )

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=SignalFreshness.observation(2.5),  # past the 2.0h bound
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "stale_observation"
    assert counter.count("stale_observation") == 1


def test_observation_age_exactly_at_the_stale_observation_boundary_is_accepted() -> None:
    """Same `>` (not `>=`) boundary idiom as `stale_quote_minutes`
    (`test_age_exactly_at_the_stale_quote_boundary_is_still_accepted`) and as
    `stale_forecast_hours`
    (`test_forecast_age_exactly_at_the_stale_forecast_boundary_is_accepted`).
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(stale_observation_hours=2.0), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=SignalFreshness.observation(2.0),  # exactly at the boundary
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True


def test_observation_signal_with_no_configured_bound_is_refused_as_limit_unset() -> None:
    """C1(b): the should-never-happen backstop. No shipped strategy is
    observation-driven yet (C2), so `stale_observation_hours` is `None` on
    every default construction path -- this must REFUSE, not silently admit
    the order or fall back to `stale_forecast_hours`. C1(a)'s wiring-time
    raise, added when the first observation strategy is wired, is the
    structural mitigation that keeps this branch should-never-happen in
    production; this test pins what happens if it is ever reached anyway.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    counter = RefusalCounter()
    risk = RiskManager(RiskLimits(), {"A": contract}, refusals=counter)

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=SignalFreshness.observation(0.0),  # even age=0 must refuse
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "observation_limit_unset"
    assert counter.count("observation_limit_unset") == 1


def test_a_stale_and_low_edge_order_refuses_for_staleness_first_sequence_pin() -> None:
    """Proves the sequence position is preserved: staleness is still checked
    BEFORE `min_model_edge`, exactly as the old `forecast_age_hours` check
    was at risk.py:365-366.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(stale_forecast_hours=8.0), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=SignalFreshness.forecast(9.0),  # stale
        edge=0.01,  # ALSO below min_model_edge=0.04
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "stale_forecast"


def test_omitting_signal_age_raises_type_error() -> None:
    """`signal_age` is required and keyword-only -- there is no sentinel that
    means "no evidence", by design (see the plan's "Default is REFUSAL").
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(RiskLimits(), {"A": contract})

    with pytest.raises(TypeError):
        risk.evaluate_order(  # type: ignore[call-arg]
            contract=contract,
            signed_qty_delta=10.0,
            hours_to_settlement=24.0,
            edge=0.50,
            portfolio=PortfolioSnapshot(equity=10_000.0),
            quote=_quote(),
            quote_age_minutes=0.0,
        )


# ---------------------------------------------------------------------------
# C7/F4 -- `COUNTED_REFUSAL_REASONS` is fixed and finite BY CONSTRUCTION.
# Previously unenforced (zero consumers repo-wide); this test drives every
# refusal branch `evaluate_order` can reach and asserts the counter never
# grows a key outside the frozenset.
# ---------------------------------------------------------------------------


def test_every_recorded_refusal_reason_is_within_the_counted_set() -> None:
    counter = RefusalCounter()
    contract_a = _contract("A", lower_f=80, upper_f=None)
    contract_b = _contract("B", lower_f=85, upper_f=None)

    # settlement_halt
    risk = RiskManager(RiskLimits(), {"A": contract_a}, refusals=counter)
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=0.1,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # too_close_to_settlement
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=1.5,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # stale_forecast
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=SignalFreshness.forecast(999.0), edge=0.50,
        portfolio=PortfolioSnapshot(), quote=_quote(), quote_age_minutes=0.0,
    )
    # stale_observation
    risk_obs = RiskManager(
        RiskLimits(stale_observation_hours=1.0), {"A": contract_a}, refusals=counter,
    )
    risk_obs.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=SignalFreshness.observation(999.0), edge=0.50,
        portfolio=PortfolioSnapshot(), quote=_quote(), quote_age_minutes=0.0,
    )
    # observation_limit_unset
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=SignalFreshness.observation(0.0), edge=0.50,
        portfolio=PortfolioSnapshot(), quote=_quote(), quote_age_minutes=0.0,
    )
    # edge_below_minimum
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.01, portfolio=PortfolioSnapshot(),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # shorts_disabled
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=-10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # missing_bid_ask
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=MarketQuote(
            instrument_id="ANY", bid=None, ask=None, bid_size=None,
            ask_size=None, ts_event=NOW,
        ),
        quote_age_minutes=0.0,
    )
    # crossed_or_locked_ignored
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=_quote(bid=0.50, ask=0.40), quote_age_minutes=0.0,
    )
    # wide_spread
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=_quote(bid=0.10, ask=0.90), quote_age_minutes=0.0,
    )
    # insufficient_liquidity
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=MarketQuote(
            instrument_id="ANY", bid=0.40, ask=0.42, bid_size=1.0, ask_size=1.0,
            ts_event=NOW,
        ),
        quote_age_minutes=0.0,
    )
    # future_quote
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=_quote(), quote_age_minutes=-10.0,
    )
    # stale_quote
    risk.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(),
        quote=_quote(), quote_age_minutes=999.0,
    )
    # exclusive_bucket_conflict
    risk_excl = RiskManager(
        RiskLimits(), {"A": contract_a, "B": contract_b}, refusals=counter,
    )
    risk_excl.evaluate_order(
        contract=contract_b, signed_qty_delta=5.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50,
        portfolio=PortfolioSnapshot(position_qty={"A": 10.0}),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # max_position
    risk_pos = RiskManager(
        RiskLimits(max_position_contracts=5.0), {"A": contract_a}, refusals=counter,
    )
    risk_pos.evaluate_order(
        contract=contract_a, signed_qty_delta=1.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50,
        portfolio=PortfolioSnapshot(position_qty={"A": 5.0}),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # max_event_notional
    risk_event = RiskManager(
        RiskLimits(max_event_notional=1.0, max_location_notional=100.0),
        {"A": contract_a}, refusals=counter,
    )
    risk_event.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # max_location_notional
    risk_loc = RiskManager(
        RiskLimits(max_event_notional=100.0, max_location_notional=1.0),
        {"A": contract_a}, refusals=counter,
    )
    risk_loc.evaluate_order(
        contract=contract_a, signed_qty_delta=10.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # max_simultaneous_positions
    risk_sim = RiskManager(
        RiskLimits(max_simultaneous_positions=1), {"A": contract_a, "B": contract_b},
        refusals=counter,
    )
    risk_sim.evaluate_order(
        contract=contract_b, signed_qty_delta=5.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50,
        portfolio=PortfolioSnapshot(position_qty={"A": 10.0}),
        quote=_quote(), quote_age_minutes=0.0,
    )
    # equity_fraction
    risk_eq = RiskManager(
        RiskLimits(max_equity_fraction=0.001, max_position_contracts=10_000.0),
        {"A": contract_a}, refusals=counter,
    )
    risk_eq.evaluate_order(
        contract=contract_a, signed_qty_delta=10_000.0, hours_to_settlement=24.0,
        signal_age=FRESH, edge=0.50, portfolio=PortfolioSnapshot(equity=1.0),
        quote=_quote(), quote_age_minutes=0.0,
    )

    assert set(counter.counts) <= risk_module.COUNTED_REFUSAL_REASONS
    assert counter.total() > 0


# ---------------------------------------------------------------------------
# BL-25 D2 -- clipping the order to the depth that actually exists
#
# `clipped_quantity` was clipped to `max_position_contracts`, the notional
# caps and the equity cap, but NEVER to the book. Measured over the captured
# ladder (`~/.local/share/breezy/catalog/quote_tape/polymarket_us`, `data/`
# AND `live/`): a $24.53 order exceeds level-0 ask size in 57.4% of snapshots
# and exhausts all ten recorded levels in 6.5%; the winning rung was offered
# 0.58 contracts while worthless rungs carried a median 35,991. So the system
# could "buy" 24.8 contracts where 0.58 exist.
# ---------------------------------------------------------------------------


def _depth_quote(
    *,
    ask: float = 0.42,
    ask_size: float | None = 100.0,
    ask_ladder: tuple[tuple[float, float], ...] | None = None,
) -> MarketQuote:
    """A one-sided ask book, so top-of-book size is the only liquidity term."""
    return MarketQuote(
        instrument_id="ANY",
        bid=None,
        ask=ask,
        bid_size=None,
        ask_size=ask_size,
        ts_event=NOW,
        ask_ladder=ask_ladder,
    )


def _permissive_limits(**overrides: object) -> RiskLimits:
    """Every cap wide open, so a clip observed below is the DEPTH clip."""
    defaults: dict[str, object] = {
        "max_position_contracts": 10_000.0,
        "max_event_notional": 1_000_000.0,
        "max_location_notional": 1_000_000.0,
        "max_equity_fraction": 1.0,
        "min_liquidity_contracts": 0.0,
    }
    defaults.update(overrides)
    return RiskLimits(**defaults)  # type: ignore[arg-type]


def test_a_buy_is_clipped_to_the_visible_top_of_book_depth() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=24.8,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_depth_quote(ask=0.99, ask_size=0.58),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "insufficient_depth"


def test_a_buy_is_clipped_to_depth_when_a_whole_contract_still_fits() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=200.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_depth_quote(ask_size=12.0),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == pytest.approx(12.0)


def test_a_buy_is_clipped_to_the_whole_ladder_when_the_quote_carries_one() -> None:
    """The ladder is the depth the depth-aware COST priced (BL-25 D1)."""
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=200.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_depth_quote(
            ask=0.90,
            ask_size=5.0,
            ask_ladder=((0.90, 5.0), (0.95, 20.0), (0.99, 50.0)),
        ),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == pytest.approx(75.0)


def test_a_ladder_exhausted_before_the_request_never_silently_over_fills() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(), {"A": contract})

    requested = 10_000.0
    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=requested,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=1_000_000.0),
        quote=_depth_quote(
            ask=0.90,
            ask_size=5.0,
            ask_ladder=((0.90, 5.0), (0.95, 20.0), (0.99, 50.0)),
        ),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity < requested
    assert decision.clipped_quantity == pytest.approx(75.0)


def test_a_request_inside_the_visible_depth_is_not_clipped_at_all() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_depth_quote(ask_size=100.0),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == pytest.approx(10.0)


def test_the_position_cap_still_binds_when_it_is_tighter_than_depth() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(max_position_contracts=6.0), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=200.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_depth_quote(ask_size=100.0),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == pytest.approx(6.0)


def test_the_equity_cap_still_binds_when_it_is_tighter_than_depth() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(max_equity_fraction=0.05), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=200.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=100.0),
        quote=_depth_quote(ask_size=100.0),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    # 0.05 * 100 equity / 1.0 contract_size = 5 contracts, tighter than 100.
    assert decision.clipped_quantity == pytest.approx(5.0)


def test_the_notional_cap_still_binds_when_it_is_tighter_than_depth() -> None:
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(max_event_notional=4.0), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=200.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_depth_quote(ask_size=100.0),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "max_event_notional"


def test_an_insufficient_depth_refusal_is_recorded_on_the_counter() -> None:
    counter = RefusalCounter()
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(), {"A": contract}, refusals=counter)

    risk.evaluate_order(
        contract=contract,
        signed_qty_delta=24.8,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(equity=10_000.0),
        quote=_depth_quote(ask=0.99, ask_size=0.58),
        quote_age_minutes=0.0,
    )

    assert counter.count("insufficient_depth") == 1


def test_insufficient_depth_is_a_bounded_counted_refusal_reason() -> None:
    assert "insufficient_depth" in risk_module.COUNTED_REFUSAL_REASONS


def test_a_position_reducing_sell_is_not_clipped_to_ask_depth() -> None:
    """Deliberate asymmetry, recorded rather than assumed.

    The depth clip prices a TAKER against the ASK. A sell takes the BID, and
    `MarketQuote` carries no bid ladder; clipping an exit to a bid side whose
    measured top-of-book median is 0.3 contracts would trap positions the
    close-only guard exists to let out. Revisit only with a bid ladder in
    hand.
    """
    contract = _contract("A", lower_f=80, upper_f=None)
    risk = RiskManager(_permissive_limits(), {"A": contract})

    decision = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=-50.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(position_qty={"A": 50.0}, equity=10_000.0),
        quote=MarketQuote(
            instrument_id="ANY",
            bid=0.40,
            ask=0.42,
            bid_size=0.3,
            ask_size=0.3,
            ts_event=NOW,
        ),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == pytest.approx(-50.0)


# ---------------------------------------------------------------------------
# T-3 -- `open_position_count()` read a SETTLED-ONLY view
#
# `position_qty` is built solely from `portfolio.net_position(...)`, and a
# native `Position` exists only after a FILL. So the one consumer of this
# count -- the `max_simultaneous_positions` refusal -- was blind to every
# order still in flight, while EVERY other cap in `evaluate_order` asks
# `net_qty` (settled + pending, the field T-1 widened to include INITIALIZED
# and SUBMITTED).
#
# Hazard, from `docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md` s T-3: cap
# 12, all instruments flat, a depth/quote burst delivers ticks for 20
# contracts on ONE handler thread so all 20 evaluate before any fill returns.
# The per-instrument in-flight gate is keyed on *that* instrument and cannot
# see the other 19; the count read 0 on every pass, so the cap never bound
# and 20 BUYs went out against a cap of 12.
# ---------------------------------------------------------------------------


def _contract_on_day(instrument_id: str, *, day_offset: int) -> MispricingContract:
    """A bucket on its OWN climate day, so the exclusivity check never fires.

    The position-count cap sits AFTER `exclusive_conflict` in
    `evaluate_order`. Buckets sharing a station/climate-day refuse as
    `exclusive_bucket_conflict` several steps earlier, and a test built from
    them would go green for the wrong reason.
    """
    return MispricingContract(
        instrument_id=instrument_id,
        facts=WeatherBucketFacts(
            settlement_station=STATION,
            climate_day=CLIMATE_DAY + dt.timedelta(days=day_offset),
            measure=Measure.HIGH,
            lower_f=80,
            upper_f=None,
        ),
        tick_size=0.01,
    )


def test_twelve_working_buys_with_nothing_settled_bind_the_simultaneous_cap() -> None:
    """RED-1: the burst, at the refusal. Cap 12, 12 in flight, 0 settled."""
    contracts = {f"I{i}": _contract_on_day(f"I{i}", day_offset=i) for i in range(13)}
    risk = RiskManager(RiskLimits(max_simultaneous_positions=12), contracts)
    portfolio = PortfolioSnapshot(
        pending_qty={f"I{i}": 10.0 for i in range(12)},
        equity=10_000.0,
    )

    decision = risk.evaluate_order(
        contract=contracts["I12"],  # the 13th, itself flat and unordered
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "max_simultaneous_positions"


def test_the_simultaneous_cap_refusal_is_recorded_on_the_counter() -> None:
    """The refusal is a gag on an order the strategy formed -- it must count."""
    counter = RefusalCounter()
    contracts = {f"I{i}": _contract_on_day(f"I{i}", day_offset=i) for i in range(13)}
    risk = RiskManager(
        RiskLimits(max_simultaneous_positions=12), contracts, refusals=counter,
    )

    risk.evaluate_order(
        contract=contracts["I12"],
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=PortfolioSnapshot(
            pending_qty={f"I{i}": 10.0 for i in range(12)}, equity=10_000.0,
        ),
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert counter.counts["max_simultaneous_positions"] == 1
    assert set(counter.counts) <= risk_module.COUNTED_REFUSAL_REASONS


def test_open_position_count_sees_in_flight_orders_with_nothing_settled() -> None:
    """RED-2: the burst, at the count itself. 20 in flight, 0 settled."""
    portfolio = PortfolioSnapshot(pending_qty={f"I{i}": 10.0 for i in range(20)})

    assert portfolio.open_position_count() == 20


def test_an_instrument_both_settled_and_working_occupies_exactly_one_slot() -> None:
    """RED-3: the union must not double-count a key present in both dicts."""
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0}, pending_qty={"A": 5.0})

    assert portfolio.open_position_count() == 1


def test_the_count_is_the_union_of_settled_and_pending_instruments() -> None:
    """RED-3, wider: the two dicts carry DIFFERENT key sets.

    Iterating either one's `.values()` alone under-counts: `position_qty`
    misses the purely in-flight instruments, `pending_qty` misses the purely
    settled ones.
    """
    portfolio = PortfolioSnapshot(
        position_qty={"settled_only": 10.0, "both": 4.0},
        pending_qty={"pending_only": -7.0, "both": 3.0},
    )

    assert portfolio.open_position_count() == 3


def test_a_settled_only_portfolio_counts_exactly_as_it_always_did() -> None:
    """RED-4, a PIN and not a defect test -- green before AND after T-3.

    With no pending quantity at all, `net_qty` degenerates to
    `position_qty.get(...)`, so the widened count must return precisely the
    old number. A zero-quantity key stays uncounted, as before.
    """
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0, "B": -5.0, "C": 0.0})

    assert portfolio.open_position_count() == 2


def test_a_working_sell_that_offsets_a_settled_long_does_not_free_the_slot() -> None:
    """A slot is ANY exposure, settled OR pending -- deliberately NOT a net.

    The netting reading is the one this test used to assert, and it is
    wrong HERE even though it is right for every other cap. Netting frees
    the slot on the strength of a fill that has not happened: the sell may
    be rejected, cancelled, or simply rest unfilled -- and on these weather
    markets resting unfilled is the NORMAL case, not the tail, because the
    measured median top-of-book bid is ~0.3 contracts. Free the slot on that
    assumption and the strategy opens a 13th position against a cap of 12,
    which is precisely the defect class this audit exists to close: a limit
    relaxed on state that has not happened yet.

    A position you are TRYING to exit is still exposure until the fill
    lands.
    """
    portfolio = PortfolioSnapshot(position_qty={"A": 10.0}, pending_qty={"A": -10.0})

    assert portfolio.open_position_count() == 1


def test_adding_to_a_settled_position_is_still_allowed_at_the_cap() -> None:
    """RED-5: the fix must not turn the cap into a blanket freeze.

    The refusal's second clause (`abs(net_qty(candidate)) < 1e-9`) is
    untouched by T-3: a candidate that already occupies one of the N slots
    consumes no NEW slot, so an add-to-existing order goes through with the
    cap at its limit. Here the candidate's slot is settled.
    """
    contracts = {f"I{i}": _contract_on_day(f"I{i}", day_offset=i) for i in range(12)}
    risk = RiskManager(RiskLimits(max_simultaneous_positions=12), contracts)
    portfolio = PortfolioSnapshot(
        position_qty={"I0": 10.0},
        pending_qty={f"I{i}": 10.0 for i in range(1, 12)},
        equity=10_000.0,
    )
    assert portfolio.open_position_count() == 12  # the cap is AT its limit

    decision = risk.evaluate_order(
        contract=contracts["I0"],
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == pytest.approx(5.0)


def test_adding_to_an_in_flight_position_is_allowed_at_the_cap() -> None:
    """RED-5, the newly reachable half.

    Before T-3 a purely in-flight candidate was invisible to the count, so
    this path was never even reached. After it, the candidate occupies one of
    the 12 slots via `pending_qty` -- and the same second clause must still
    let the add through rather than refuse it.
    """
    contracts = {f"I{i}": _contract_on_day(f"I{i}", day_offset=i) for i in range(12)}
    risk = RiskManager(RiskLimits(max_simultaneous_positions=12), contracts)
    portfolio = PortfolioSnapshot(
        pending_qty={f"I{i}": 10.0 for i in range(12)},
        equity=10_000.0,
    )
    assert portfolio.open_position_count() == 12

    decision = risk.evaluate_order(
        contract=contracts["I0"],
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is True
    assert decision.clipped_quantity == pytest.approx(5.0)


def test_a_flat_candidate_is_refused_when_every_slot_is_exiting_but_unfilled() -> None:
    """The concrete 13th-position sequence, end to end at the refusal.

    Twelve settled positions, each with a working sell that would close it,
    cap at 12, a flat 13th candidate arrives. Under a NET reading all twelve
    net to zero, the cap reads empty and the 13th goes out -- and if those
    sells do not fill (see
    `test_a_working_sell_that_offsets_a_settled_long_does_not_free_the_slot`
    for why that is the expected case here) the bot holds 13 positions
    against a cap of 12.
    """
    contracts = {f"I{i}": _contract_on_day(f"I{i}", day_offset=i) for i in range(13)}
    risk = RiskManager(RiskLimits(max_simultaneous_positions=12), contracts)
    portfolio = PortfolioSnapshot(
        position_qty={f"I{i}": 10.0 for i in range(12)},
        pending_qty={f"I{i}": -10.0 for i in range(12)},
        equity=10_000.0,
    )

    decision = risk.evaluate_order(
        contract=contracts["I12"],
        signed_qty_delta=5.0,
        hours_to_settlement=24.0,
        signal_age=FRESH,
        edge=0.50,
        portfolio=portfolio,
        quote=_quote(),
        quote_age_minutes=0.0,
    )

    assert decision.allowed is False
    assert decision.reason == "max_simultaneous_positions"
