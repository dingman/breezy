"""Proves BL-12 wiring: the analysis runner's `_build_strategy` can construct
`RunningExtremeLockStrategy` (no `ForecastSource`, an observation-kind
strategy) and, driven entirely through the REAL
`breezy.runtime.backtest_harness.run_backtest`, that strategy's `on_data`
reaches its decision path (`evaluate_instrument` via `_evaluate_and_act`) and
submits an order.

WIRING ONLY -- NOT ECONOMICS
-----------------------------
This test proves the runner->strategy->harness plumbing is connected: a
`NwsClimateDay` observation delivered via `as_backtest_data` reaches
`on_data`, and an `OrderBookDepth10` reaches `on_order_book_depth`, and
together they clear the strategy's own decision and risk gates enough to
submit a real order through the real engine. It does NOT measure PnL, ROI,
or any economic performance -- the market data (bid/ask, sizes) and the
observation margin below are constructed to be unambiguously tradable, not
drawn from any real tape or any real weather event. Do not cite any number
from this test as measured strategy performance.

Loaded the same way as `test_run_weather_strategy_backtests.py`
(`scripts/` carries no package `__init__.py`).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

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
_STRIKE_LOWER_F = 80  # bucket: "high >= 80F" -- open-ended upper tail
#: Well past the tail floor (margin 5+), so `MEASURED_MARGIN_MODEL_P`
#: resolves to its highest, table-capped bound regardless of exact margin.
_RUNNING_TMAX_F = 90
STARTING_BALANCE_USD = 10_000
_HOUR_NS = 3_600_000_000_000
#: Observation arrives first, well before the depth tick, so both signals
#: are present the moment `on_order_book_depth` fires and
#: `_evaluate_and_act` is not short-circuited waiting on the other input.
#: The depth tick sits far enough before `_CLOSE_NS` (expiration) that
#: `hours_to_settlement` clears both `halt_hours_before_settlement` (1.0h)
#: and `min_hours_to_settlement` (2.0h) defaults -- `RunningExtremeLockStrategy`
#: derives `hours_to_settlement` from the real instrument expiration
#: (unlike the forecast strategies, which use `forecast.horizon_hours`).
_OBSERVATION_NS = _HOUR_NS
_DEPTH_NS = 2 * _HOUR_NS
_CLOSE_NS = 8 * _HOUR_NS


def _instrument() -> BinaryOption:
    symbol = Symbol("nyc-ge80f-rel")
    venue = Venue("POLYMARKET_US")
    price_increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=venue),
        raw_symbol=symbol,
        outcome="Yes",
        description="NYC daily high at least 80F",
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
            STRIKE_UPPER_F_KEY: None,
            FEE_SCHEDULE_STATUS_KEY: FEE_SCHEDULE_STATUS_KNOWN,
            FEE_COEFFICIENT_KEY: "0",
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
    # Deep, tight, cheap ask: unambiguously tradable, not a realistic quote.
    bids, bid_counts = _padded_side(instrument, OrderSide.BUY, "0.10", 500)
    asks, ask_counts = _padded_side(instrument, OrderSide.SELL, "0.12", 500)
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
                    tmax_f=_RUNNING_TMAX_F,
                    is_final=False,
                    correction_flag=False,
                    is_superseded=False,
                    issuance_time_ns=_OBSERVATION_NS,
                    retrieved_at_ns=_OBSERVATION_NS,
                    ts_event=_OBSERVATION_NS,
                ),
            ],
        ),
        settlement_prices={instrument.id: 1.0},
        starting_balances=(Money(STARTING_BALANCE_USD, instrument.quote_currency),),
    )


def test_runner_builds_running_extreme_lock_without_a_forecast_source() -> None:
    """BL-12: `_build_strategy` no longer hard-requires `forecast_source`."""
    instrument = _instrument()
    strategy = runner._build_strategy(
        "running_extreme_lock", (instrument.id,), None,
    )

    assert isinstance(strategy, runner.RunningExtremeLockStrategy)
    assert strategy.config.stale_observation_hours == (
        runner.STALE_OBSERVATION_HOURS_RUNNING_EXTREME_LOCK
    )


def test_running_extreme_lock_reaches_on_data_and_submits_an_order_through_run_backtest() -> None:
    """WIRING PROOF ONLY -- see the module docstring. Not an economics claim."""
    instrument = _instrument()
    strategy = runner._build_strategy(
        "running_extreme_lock", (instrument.id,), None,
    )

    engine = run_backtest(_config(instrument), strategies=(strategy,))
    try:
        fills = [
            event
            for order in engine.cache.orders()
            for event in order.events
            if isinstance(event, OrderFilled)
        ]
        # The observation reached `on_data` and populated
        # `strategy._observations` (private, but this is the wiring proof --
        # the public-surface evidence is the order below): a BUY fill exists
        # only if `_evaluate_and_act` ran the full decision + risk path after
        # both the observation and the depth tick arrived.
        assert len(fills) >= 1
        assert any(fill.order_side == OrderSide.BUY for fill in fills)
        assert strategy.refusals.counts == {} or all(
            count == 0 for count in strategy.refusals.counts.values()
        )
    finally:
        engine.dispose()
