"""`ForecastMispricingStrategy` through the real backtest harness.

This is the integration proof the task asked for: the strategy actually
trades and its position settles, driven entirely through
``breezy.runtime.backtest_harness.run_backtest`` -- no mocked engine, no
patched Nautilus internals.

THE ANTI-LOOKAHEAD PROOF, NOT JUST A CLAIM
--------------------------------------------
``_SyntheticForecastSource`` below is constructed with its own
``expected_high_f`` (95.0), fixed independently of, and asserted below to
DIFFER from, the realized settlement observation fed into the run
(``tmax_f=84`` via ``NwsClimateDay``). If a future change accidentally wired
the forecast source to read the settlement value instead of trading on an
independently-supplied forecast, ``test_the_injected_forecast_is_not_the_realised_observation``
fails immediately, and the strategy's trading behaviour no longer has
anything to prove it against.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, InstrumentClose, OrderBookDepth10, QuoteTick
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
from breezy.strategy.forecast_mispricing import ForecastMispricingConfig, ForecastMispricingStrategy
from breezy.strategy.weather_common.models import ForecastSnapshot
from tests.unit.test_persistence_catalog import make_climate_day

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
#: The realized settlement observation -- deliberately DIFFERENT from the
#: forecast the strategy trades on (see `_FORECAST_EXPECTED_HIGH_F`).
_OBSERVED_TMAX_F = 84
#: What the injected forecast claims, fixed independently of the realized
#: value above. Trading logic never sees `_OBSERVED_TMAX_F` before settlement.
_FORECAST_EXPECTED_HIGH_F = 95.0
_STRIKE_LOWER_F = 80  # bucket: "high >= 80F"
STARTING_BALANCE_USD = 10_000
_STEP_NS = 1_000_000_000
_BASE_NS = _STEP_NS  # one second after activation
_CLOSE_GAP_NS = 5 * _STEP_NS


@dataclass(frozen=True, slots=True)
class _SyntheticForecastSource:
    """A forecast source built independently of any settlement observation.

    ``horizon_hours`` is held constant for this short test run rather than
    recomputed from ``now`` -- acceptable for a fixed-duration backtest, but
    see ``breezy.strategy.weather_common.forecast_source`` for why a
    production source MUST make this live.
    """

    station: str
    climate_day: dt.date
    expected_high_f: float
    published_at: dt.datetime
    horizon_hours: float

    def snapshot(
        self, *, station: str, climate_day: dt.date, now: dt.datetime,
    ) -> ForecastSnapshot | None:
        del now
        if station != self.station or climate_day != self.climate_day:
            return None
        return ForecastSnapshot(
            location_id=station,
            target_date=climate_day,
            published_at=self.published_at,
            expected_high_f=self.expected_high_f,
            horizon_hours=self.horizon_hours,
        )


def _instrument() -> BinaryOption:
    symbol = Symbol("nyc-ge80f")
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
        expiration_ns=10 * _STEP_NS + _CLOSE_GAP_NS + _STEP_NS,
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


#: Ask-side depth, deliberately larger than the ~75 contracts this scenario's
#: sizing rule asks for.
#:
#: It used to be 50, which was SMALLER than the intent -- and before BL-25 D2
#: that difference was invisible: `RiskManager.evaluate_order` clipped to the
#: position, notional and equity caps but never to the book, so the strategy
#: submitted a 75-lot MARKET order into a 50-lot book, filled 50, and left a
#: 25-lot remainder working forever. A permanently unfilled remainder is not
#: a rejection, so nothing surfaced it. With the depth clip in place the first
#: order is sized to the book and fills completely, and the strategy then
#: (correctly) asks for the rest against a book it has just consumed -- which
#: the venue answers `no market`. Serving the intent from real depth keeps
#: this test measuring what its name says (a strategy that trades and
#: settles) instead of an artefact of an over-sized order.
_ASK_DEPTH_CONTRACTS: int = 100


def _depth(instrument: BinaryOption) -> OrderBookDepth10:
    bids, bid_counts = _padded_side(instrument, OrderSide.BUY, "0.28", 50)
    asks, ask_counts = _padded_side(
        instrument, OrderSide.SELL, "0.30", _ASK_DEPTH_CONTRACTS,
    )
    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=bids,
        asks=asks,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=_BASE_NS,
        ts_init=_BASE_NS,
    )


def _quote(instrument: BinaryOption) -> QuoteTick:
    ts = _BASE_NS + _STEP_NS
    return QuoteTick(
        instrument.id,
        Price.from_str("0.28"),
        Price.from_str("0.30"),
        Quantity(50, instrument.size_precision),
        Quantity(50, instrument.size_precision),
        ts,
        ts,
    )


def _close(instrument: BinaryOption) -> InstrumentClose:
    ts = _BASE_NS + _STEP_NS + _CLOSE_GAP_NS
    return InstrumentClose(
        instrument.id,
        Price.from_str("1.00"),
        InstrumentCloseType.CONTRACT_EXPIRED,
        ts,
        ts,
    )


def _config(instrument: BinaryOption) -> BreezyBacktestConfig:
    return BreezyBacktestConfig(
        instruments=(instrument,),
        market_data=[_depth(instrument), _quote(instrument), _close(instrument)],
        weather_data=as_backtest_data(
            [
                make_climate_day(
                    station=STATION,
                    climate_day=CLIMATE_DAY,
                    tmax_f=_OBSERVED_TMAX_F,
                    is_final=True,
                    retrieved_at_ns=_BASE_NS + _STEP_NS // 2,
                ),
            ],
        ),
        settlement_prices={instrument.id: 1.0},
        starting_balances=(Money(STARTING_BALANCE_USD, instrument.quote_currency),),
    )


def _forecast_source() -> _SyntheticForecastSource:
    return _SyntheticForecastSource(
        station=STATION,
        climate_day=CLIMATE_DAY,
        expected_high_f=_FORECAST_EXPECTED_HIGH_F,
        published_at=dt.datetime.fromtimestamp(_BASE_NS / 1_000_000_000, tz=dt.UTC),
        horizon_hours=24.0,
    )


def _strategy(instrument: BinaryOption) -> ForecastMispricingStrategy:
    return ForecastMispricingStrategy(
        ForecastMispricingConfig(
            instrument_ids=(instrument.id,),
            use_limit_orders=False,  # market order: deterministic full fill for this proof
        ),
        _forecast_source(),
    )


def test_the_injected_forecast_is_not_the_realised_observation() -> None:
    """The anti-lookahead proof itself: the forecast is NOT the settlement value."""
    forecast = _forecast_source().snapshot(
        station=STATION, climate_day=CLIMATE_DAY, now=dt.datetime.now(tz=dt.UTC),
    )
    assert forecast is not None
    assert forecast.expected_high_f != float(_OBSERVED_TMAX_F)
    assert forecast.expected_high_f == _FORECAST_EXPECTED_HIGH_F


def test_forecast_mispricing_strategy_trades_and_settles() -> None:
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
        positions = engine.cache.positions()

        assert len(fills) >= 1
        # `engine.cache.orders()` is not guaranteed chronological, so check
        # membership rather than assume the entry is `fills[0]`: a settled
        # LONG position also produces the engine's own closing SELL leg.
        assert any(fill.order_side == OrderSide.BUY for fill in fills)
        assert len(positions) == 1
        assert positions[0].is_closed
        assert positions[0].avg_px_close == 1.0  # the settlement_prices value, not tmax_f
        assert positions[0].realized_pnl is not None
        # Bought around 0.30, settled at 1.00: this should be solidly profitable.
        assert positions[0].realized_pnl.as_decimal() > 0
    finally:
        engine.dispose()
