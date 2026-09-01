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
from nautilus_trader.model.enums import AssetClass, InstrumentCloseType, OrderSide
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
