"""Proves BL-13 wiring: the analysis runner's `_build_strategy` can construct
`CliSettlementPrintLockStrategy` (no `ForecastSource` -- an observation-kind
strategy) and, driven entirely through the REAL
`breezy.runtime.backtest_harness.run_backtest`, that strategy's `on_data`
reaches its decision path and submits an order against an INTERIOR bucket.

WIRING ONLY -- NOT ECONOMICS
-----------------------------
This proves the runner->strategy->harness plumbing is connected: a FINAL
`NwsClimateDay` delivered via `as_backtest_data` reaches `on_data`, an
`OrderBookDepth10` reaches `on_order_book_depth`, and together they clear the
strategy's own decision and risk gates enough to submit a real order through
the real engine. It measures NO PnL, ROI, or economic performance -- the book
(bid/ask, sizes) and the printed value below are constructed to be
unambiguously tradable, not drawn from any real tape or any real CLI product.
Do not cite any number from this test as measured strategy performance.

The bucket under test is deliberately an INTERIOR one ([80, 84] with an 82F
print), because that is what this strategy is FOR -- see the decision module
docstring for why an interior bucket after the FINAL print is sound while the
same bucket after a PRELIMINARY is dead (G-01).

Loaded the same way as `test_running_extreme_lock_backtest_wiring.py`
(`scripts/` carries no package `__init__.py`).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, InstrumentClose, OrderBookDepth10
from nautilus_trader.model.enums import (
    AssetClass,
    InstrumentCloseType,
    OrderSide,
    OrderType,
    TimeInForce,
)
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_KNOWN,
)
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import BreezyBacktestConfig, run_backtest
from breezy.strategy.cli_settlement_print_lock.config import MIN_EDGE_AFTER_COSTS_BL19
from breezy.strategy.cli_settlement_print_lock.decision import (
    cost_basis_anchor,
    worst_admissible_ask,
)
from breezy.strategy.cli_settlement_print_lock.strategy import (
    MEASURED_P_STABLE_WILSON_LOWER,
)
from tests.unit.test_persistence_catalog import make_climate_day


def _load_runner_module() -> ModuleType:
    path = Path("scripts/analysis/run_weather_strategy_backtests.py")
    sys.path.insert(0, path.parent.as_posix())
    spec = importlib.util.spec_from_file_location("run_weather_strategy_backtests", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner_module()

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
#: An INTERIOR rung of the ladder -- the bucket this strategy exists to buy.
_STRIKE_LOWER_F = 80
_STRIKE_UPPER_F = 84
#: The FINAL CLI print, comfortably inside [80, 84].
_PRINTED_TMAX_F = 82
STARTING_BALANCE_USD = 10_000
_HOUR_NS = 3_600_000_000_000
#: The print arrives before the depth tick, so both signals are present the
#: moment `on_order_book_depth` fires. The depth tick sits far enough before
#: `_CLOSE_NS` (expiration) that `hours_to_settlement` clears both
#: `halt_hours_before_settlement` (1.0h) and `min_hours_to_settlement` (2.0h),
#: and the print's age at the depth tick (1h) is well inside
#: `STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK`.
_PRINT_NS = _HOUR_NS
_DEPTH_NS = 2 * _HOUR_NS
_CLOSE_NS = 8 * _HOUR_NS


def _instrument() -> BinaryOption:
    symbol = Symbol("nyc-80-84f-rel")
    venue = Venue("POLYMARKET_US")
    price_increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=venue),
        raw_symbol=symbol,
        outcome="Yes",
        description="NYC daily high 80-84F",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=price_increment.precision,
        price_increment=price_increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=_CLOSE_NS,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: STATION,
            CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: _STRIKE_LOWER_F,
            STRIKE_UPPER_F_KEY: _STRIKE_UPPER_F,
            FEE_SCHEDULE_STATUS_KEY: FEE_SCHEDULE_STATUS_KNOWN,
            # The MEASURED venue coefficient: 20/20 captured weather markets
            # carry `feeCoefficient: 0.06`. Not "0" -- a free venue is the one
            # cost assumption this strategy's design exists to make
            # unwritable, and a wiring test that silently trades free would
            # not exercise the fee path at all.
            FEE_COEFFICIENT_KEY: "0.06",
        },
    )


def _padded_side(
    instrument: BinaryOption, side: OrderSide, price: str, size: int,
) -> tuple[list[BookOrder], list[int]]:
    real = BookOrder(side, Price.from_str(price), Quantity(size, instrument.size_precision), 0)
    filler = BookOrder(
        side, Price(0, instrument.price_precision), Quantity(0, instrument.size_precision), 0,
    )
    orders = [real] + [filler] * 9
    counts = [1] + [0] * 9
    return orders, counts


def _depth(instrument: BinaryOption) -> OrderBookDepth10:
    # Deep and tight: unambiguously tradable, not a realistic near-certain quote.
    bids, bid_counts = _padded_side(instrument, OrderSide.BUY, "0.88", 500)
    asks, ask_counts = _padded_side(instrument, OrderSide.SELL, "0.90", 500)
    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=_DEPTH_NS,
        ts_init=_DEPTH_NS,
    )


def _close(instrument: BinaryOption) -> InstrumentClose:
    return InstrumentClose(
        instrument.id,
        Price.from_str("1.00"),
        InstrumentCloseType.CONTRACT_EXPIRED,
        _CLOSE_NS,
        _CLOSE_NS,
    )


def _depth_at(
    instrument: BinaryOption, *, ask: str, size: int, ts_ns: int, sequence: int,
) -> OrderBookDepth10:
    """One tradable snapshot at `ask`, with a bid one 0.02 spread below.

    Two-sided deliberately: the backtest matching engine returns NO FILLS from
    a book whose bid side is entirely padding, so a one-sided snapshot tests
    the engine rather than the strategy. The spread is held at 0.02, inside
    `max_bid_ask_spread` (0.06), so `quote_tradable` never refuses for a
    reason this test is not about.
    """
    bid_value = round(float(ask) - 0.02, instrument.price_precision)
    bids, bid_counts = _padded_side(
        instrument, OrderSide.BUY, f"{bid_value:.{instrument.price_precision}f}", size,
    )
    asks, ask_counts = _padded_side(instrument, OrderSide.SELL, ask, size)
    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=sequence,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def _config(instrument: BinaryOption) -> BreezyBacktestConfig:
    return BreezyBacktestConfig(
        instruments=(instrument,),
        market_data=[_depth(instrument), _close(instrument)],
        weather_data=as_backtest_data(
            [
                make_climate_day(
                    station=STATION,
                    climate_day=CLIMATE_DAY,
                    tmax_f=_PRINTED_TMAX_F,
                    is_final=True,
                    correction_flag=False,
                    is_superseded=False,
                    issuance_time_ns=_PRINT_NS,
                    retrieved_at_ns=_PRINT_NS,
                    ts_event=_PRINT_NS,
                ),
            ],
        ),
        # 82F settles the [80, 84] bucket YES.
        settlement_prices={instrument.id: 1.0},
        starting_balances=(Money(STARTING_BALANCE_USD, instrument.quote_currency),),
    )


def _fees(instrument: BinaryOption) -> Any:
    return runner.PolymarketUSFeeCoefficients({str(instrument.id): instrument})


def _strategy(instrument: BinaryOption) -> Any:
    return runner._build_strategy(
        "cli_settlement_print_lock", (instrument.id,), None, _fees(instrument),
    )


def test_runner_builds_cli_settlement_print_lock_without_a_forecast_source() -> None:
    instrument = _instrument()
    strategy = _strategy(instrument)

    assert isinstance(strategy, runner.CliSettlementPrintLockStrategy)
    assert strategy.config.stale_observation_hours == (
        runner.STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK
    )


def test_the_runner_supplies_the_slippage_term_explicitly_at_the_one_call_site() -> None:
    """No default exists in the config, so the runner must name it -- and the
    named value must be at least one tick on this venue's 0.01 grid."""
    instrument = _instrument()
    strategy = _strategy(instrument)

    assert strategy.config.slippage_prob == (
        runner.SLIPPAGE_PROB_CLI_SETTLEMENT_PRINT_LOCK
    )
    assert strategy.config.slippage_prob >= float(instrument.price_increment)


def test_the_runner_refuses_to_build_this_strategy_with_no_fee_source() -> None:
    """There is no default coefficient anywhere. A `None` is a caller bug."""
    instrument = _instrument()

    with pytest.raises(ValueError, match="fee_coefficients"):
        runner._build_strategy(
            "cli_settlement_print_lock", (instrument.id,), None, None,
        )


def test_on_start_resolves_the_venue_fee_onto_every_traded_contract() -> None:
    """Proves the injection reaches the DECISION layer, not just the ctor."""
    instrument = _instrument()
    strategy = _strategy(instrument)

    engine = run_backtest(_config(instrument), strategies=(strategy,))
    try:
        contract = strategy._contracts[str(instrument.id)]
        assert contract.fee_coefficient == pytest.approx(0.06)
    finally:
        engine.dispose()


def test_the_derived_stale_observation_bound_is_not_the_preliminary_window_bound() -> None:
    """The 12.665h bound was derived for the prelim->final ISSUANCE gap; this
    strategy's bound comes from the FINAL-print-to-settlement window and is
    strictly tighter. Copying the sibling's number would be a derivation bug."""
    assert (
        runner.STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK
        < runner.STALE_OBSERVATION_HOURS_RUNNING_EXTREME_LOCK
    )


def test_cli_settlement_print_lock_reaches_on_data_and_submits_an_order() -> None:
    """WIRING PROOF ONLY -- see the module docstring. Not an economics claim."""
    instrument = _instrument()
    strategy = _strategy(instrument)

    engine = run_backtest(_config(instrument), strategies=(strategy,))
    try:
        fills = [
            event
            for order in engine.cache.orders()
            for event in order.events
            if isinstance(event, OrderFilled)
        ]
        assert len(fills) >= 1
        assert any(fill.order_side == OrderSide.BUY for fill in fills)
        assert strategy.refusals.counts == {} or all(
            count == 0 for count in strategy.refusals.counts.values()
        )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The execution mechanism actually enforces the modelled slippage
# ---------------------------------------------------------------------------


def test_the_submitted_order_is_a_marketable_limit_capped_at_ask_plus_slippage() -> None:
    """An UNPRICED market order defeats `slippage_prob` at execution time.

    `slippage_prob` is the load-bearing safety input -- the whole "ask 0.99 is
    unwritable" guarantee rests on it -- but a `MARKET` order carries no price
    at all, so nothing downstream holds the fill to the number the edge model
    charged. The final print is PUBLIC: every participant sees it at once, the
    quoted level is swept, and the taker walks the book at whatever is left.

    A marketable LIMIT at `ask + slippage_prob`, IOC, makes the modelled cost
    STRUCTURAL: no fill can occur above the price the edge was computed at
    plus the slippage that edge already paid for, and anything worse simply
    does not trade.
    """
    instrument = _instrument()
    strategy = _strategy(instrument)

    engine = run_backtest(_config(instrument), strategies=(strategy,))
    try:
        submitted = [
            order
            for order in engine.cache.orders()
            if not str(order.client_order_id).startswith("EXPIRATION-LEG")
        ]
        assert len(submitted) == 1
        order = submitted[0]
        assert order.order_type == OrderType.LIMIT
        assert order.time_in_force == TimeInForce.IOC
        # ask 0.90 + one 0.01 tick of modelled slippage, ON THE GRID.
        assert order.price == Price.from_str("0.91")
        assert order.price.precision == instrument.price_precision
    finally:
        engine.dispose()


def test_a_print_arriving_against_a_stale_cached_book_does_not_trade() -> None:
    """Adverse selection by construction, and the counter must SEE it.

    `_evaluate_and_act` is driven from `on_data` -- CLI print arrival -- against
    the LAST CACHED depth quote, and `stale_quote_minutes` is 15.0. A settled
    source firing against a ten-minute-old book is not a stale-data edge case,
    it is the definition of adverse selection: the print is public, so the
    quoted offer is exactly what everyone else is lifting.

    The refusal is COUNTED (`stale_quote`), never a silent pre-signal `None`
    -- BL-19 s8.5 null class N1 / BL-10.
    """
    instrument = _instrument()
    strategy = _strategy(instrument)
    config = BreezyBacktestConfig(
        instruments=(instrument,),
        # The book lands FIRST and is never refreshed; the print arrives ten
        # minutes later, inside `stale_quote_minutes` and well outside the
        # print-arrival bound.
        market_data=[
            _depth_at(
                instrument, ask="0.90", size=500, ts_ns=_HOUR_NS, sequence=0,
            ),
            _close(instrument),
        ],
        weather_data=as_backtest_data(
            [
                make_climate_day(
                    station=STATION,
                    climate_day=CLIMATE_DAY,
                    tmax_f=_PRINTED_TMAX_F,
                    is_final=True,
                    correction_flag=False,
                    is_superseded=False,
                    issuance_time_ns=_HOUR_NS + 10 * 60 * 1_000_000_000,
                    retrieved_at_ns=_HOUR_NS + 10 * 60 * 1_000_000_000,
                    ts_event=_HOUR_NS + 10 * 60 * 1_000_000_000,
                ),
            ],
        ),
        settlement_prices={instrument.id: 1.0},
        starting_balances=(Money(STARTING_BALANCE_USD, instrument.quote_currency),),
    )

    # Submitting NOTHING is the assertion. The harness otherwise raises
    # `SilentRunError` on an idle strategy, which is the correct default and
    # is exactly what this run exists to observe.
    engine = run_backtest(config, strategies=(strategy,), allow_idle_strategies=True)
    try:
        fills = [
            event
            for order in engine.cache.orders()
            for event in order.events
            if isinstance(event, OrderFilled) and event.order_side == OrderSide.BUY
        ]
        assert fills == []
        assert strategy.refusals.count("stale_quote") >= 1
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The dollar anchor is a POSITION budget, not a per-decision one
# ---------------------------------------------------------------------------

#: A monotone decline from the tightest admissible entry. The OBSERVATION is
#: final and never changes -- only the ask moves -- so every one of these ticks
#: re-forms the SAME signal at a larger `A / premium`.
_DECLINE_ASKS: tuple[str, ...] = (
    "0.98", "0.90", "0.80", "0.70", "0.60", "0.50", "0.40", "0.30", "0.20", "0.16",
)


def _declining_config(instrument: BinaryOption) -> BreezyBacktestConfig:
    half_hour_ns = _HOUR_NS // 2
    depths = [
        _depth_at(
            instrument,
            ask=ask,
            size=500,
            ts_ns=_HOUR_NS + index * half_hour_ns,
            sequence=index,
        )
        for index, ask in enumerate(_DECLINE_ASKS)
    ]
    return BreezyBacktestConfig(
        instruments=(instrument,),
        market_data=[*depths, _close(instrument)],
        weather_data=as_backtest_data(
            [
                make_climate_day(
                    station=STATION,
                    climate_day=CLIMATE_DAY,
                    tmax_f=_PRINTED_TMAX_F,
                    is_final=True,
                    correction_flag=False,
                    is_superseded=False,
                    issuance_time_ns=_PRINT_NS,
                    retrieved_at_ns=_PRINT_NS,
                    ts_event=_PRINT_NS,
                ),
            ],
        ),
        settlement_prices={instrument.id: 1.0},
        starting_balances=(Money(STARTING_BALANCE_USD, instrument.quote_currency),),
    )


def _anchor() -> float:
    """`A`, re-derived from the shipped constants rather than transcribed."""
    return cost_basis_anchor(
        base_quantity=25.0,
        worst_ask=worst_admissible_ask(
            model_p=MEASURED_P_STABLE_WILSON_LOWER,
            fee_coefficient=0.06,
            slippage_prob=runner.SLIPPAGE_PROB_CLI_SETTLEMENT_PRINT_LOCK,
            min_edge_after_costs=MIN_EDGE_AFTER_COSTS_BL19,
            tick_size=0.01,
        ),
        fee_coefficient=0.06,
    )


def _premium_paid(engine: Any, instrument: BinaryOption) -> float:
    """Dollars actually committed: fill notional PLUS the venue commission."""
    total = 0.0
    for order in engine.cache.orders():
        for event in order.events:
            if not isinstance(event, OrderFilled) or event.order_side != OrderSide.BUY:
                continue
            total += float(event.last_px) * float(event.last_qty)
            total += float(event.commission.as_double())
    return total


def test_a_falling_ask_cannot_ratchet_the_position_past_the_dollar_anchor() -> None:
    """MULTI-TICK, by construction: no single decision can show this.

    `decision.quantity` is a TARGET LEVEL and `_maybe_submit` tops up to it on
    every depth tick. The observation is FINAL and never changes -- only the
    ask moves -- so as the ask falls `A / premium` rises and the strategy buys
    MORE, averaging down through the whole decline. Each decision genuinely is
    a $24.53 basis; the POSITION is not.

    The scenario this refuses: the bucket mapping is wrong, or the print will
    be corrected, and the market marks the bucket down all session. The old
    rule read every step as a bigger edge and deployed multiples of the design
    budget SPECIFICALLY BECAUSE the market disagreed more.
    """
    instrument = _instrument()
    strategy = _strategy(instrument)

    engine = run_backtest(_declining_config(instrument), strategies=(strategy,))
    try:
        fills = [
            event
            for order in engine.cache.orders()
            for event in order.events
            if isinstance(event, OrderFilled) and event.order_side == OrderSide.BUY
        ]
        spent = _premium_paid(engine, instrument)
        assert fills, "the scenario must actually trade, or it proves nothing"
        # `A` is derived with the EXACT fee; the venue rounds each fill's
        # commission to a whole cent (`PolymarketUSFeeModel._round_bankers`),
        # so the realised basis can exceed it by at most one cent PER FILL.
        # That is the venue's rounding, not the ratchet: the same scenario
        # before this change spent $62.60, 2.55x the anchor.
        tolerance = 0.01 * len(fills)
        assert spent <= _anchor() + tolerance, (
            f"position basis {spent:.4f} exceeds the ${_anchor():.4f} anchor "
            f"by more than {tolerance:.2f} of per-fill cent rounding"
        )
        assert spent < 2.0 * _anchor()
    finally:
        engine.dispose()


def test_the_first_entry_of_the_decline_is_unchanged_by_the_position_budget() -> None:
    """The clamp binds only on TOP-UPS -- the first decision is untouched.

    Guards against "fixing" the ratchet by shrinking the strategy: the entry
    at the tightest admissible ask must still be the full `base_quantity`.
    """
    instrument = _instrument()
    strategy = _strategy(instrument)

    engine = run_backtest(_declining_config(instrument), strategies=(strategy,))
    try:
        first = min(
            (
                event
                for order in engine.cache.orders()
                for event in order.events
                if isinstance(event, OrderFilled) and event.order_side == OrderSide.BUY
            ),
            key=lambda event: event.ts_event,
        )
        assert float(first.last_px) == pytest.approx(0.98)
        assert float(first.last_qty) == pytest.approx(25.0)
    finally:
        engine.dispose()
