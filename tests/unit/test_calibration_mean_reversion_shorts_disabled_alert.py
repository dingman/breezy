"""The disabled strategy must SAY it is disabled -- end to end, no seams stubbed.

`calibration_mean_reversion` was SHORT_YES-only in the tested window, so with
shorting off (the default, and the only naked-short control there is) it can
execute no signal at all. It reports that by doing nothing, which is
byte-identical to what it does when the market is fairly priced.

Driven through a REAL registered `Strategy`, a REAL `MessageBus` and the REAL
default alert sink -- `resolve_alert_sink()` with no webhook configured, i.e.
`LoggingAlertSink`, asserted through `caplog`. Nothing here injects a test
double into the strategy: the point is that the wiring an operator actually
runs carries the signal, not that a hand-placed alerter can be called.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.calibration_mean_reversion import (
    CalibrationMeanReversionConfig,
    CalibrationMeanReversionStrategy,
)
from breezy.strategy.weather_common.models import ForecastSnapshot
from breezy.strategy.weather_common.refusals import SHORTS_DISABLED, SHORTS_DISABLED_EVENT

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

STATION = "NYC"
CLIMATE_DAY = dt.date(1970, 1, 1)
SYMBOL = Symbol("nyc-ge80f")
VENUE = Venue("POLYMARKET_US")
INSTRUMENT_ID = InstrumentId(symbol=SYMBOL, venue=VENUE)

#: A forecast far BELOW the bucket's 80F strike against a book bid at 0.90:
#: the model says "almost certainly not", the market says "almost certainly
#: yes". That is a SHORT_YES, and it is the only kind of signal this fixture
#: produces.
RICH_MARKET_BID = "0.90"
RICH_MARKET_ASK = "0.92"
COLD_FORECAST_HIGH_F = 70.0


class _ConstantForecastSource:
    """Returns one snapshot, always -- no settlement-derived value anywhere."""

    def snapshot(
        self, *, station: str, climate_day: dt.date, now: dt.datetime,
    ) -> ForecastSnapshot | None:
        return ForecastSnapshot(
            location_id=station,
            target_date=climate_day,
            published_at=now - dt.timedelta(hours=1),
            expected_high_f=COLD_FORECAST_HIGH_F,
            horizon_hours=24.0,
        )


def _instrument() -> BinaryOption:
    price_increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=INSTRUMENT_ID,
        raw_symbol=SYMBOL,
        outcome="Yes",
        description="NYC daily high at least 80F",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=price_increment.precision,
        price_increment=price_increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=1_000_000_000_000,
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
            STRIKE_LOWER_F_KEY: 80,
            STRIKE_UPPER_F_KEY: None,
        },
    )


class _Rig(NamedTuple):
    """A registered strategy, the clock the caller advances, and every command
    the two engine endpoints received."""

    strategy: CalibrationMeanReversionStrategy
    clock: TestClock
    commands: list[Any]


def _registered_strategy(config: CalibrationMeanReversionConfig) -> _Rig:
    """A really-registered strategy, plus the clock the caller must advance.

    The data endpoint is given a capture handler: without one a
    `SubscribeQuoteTicks` reaches no endpoint, which Nautilus reports as an
    error rather than raising -- and an error the test cannot see is exactly
    the silence these tests exist to eliminate. Whether an order was submitted
    is asserted off `cache.orders()` rather than off a captured command,
    because which engine endpoint a `SubmitOrder` is routed to is Nautilus's
    business and not a fact this test should pin.
    """
    strategy = CalibrationMeanReversionStrategy(config, _ConstantForecastSource())
    clock = TestClock()
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(_instrument())
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    commands: list[Any] = []
    msgbus.register(endpoint="DataEngine.execute", handler=commands.append)
    strategy.register(
        trader_id=TraderId("TESTER-000"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    strategy.start()  # -> RUNNING, then `on_start`; orders need the real state
    return _Rig(strategy, clock, commands)


def _rich_quote() -> QuoteTick:
    return QuoteTick(
        instrument_id=INSTRUMENT_ID,
        bid_price=Price.from_str(RICH_MARKET_BID),
        ask_price=Price.from_str(RICH_MARKET_ASK),
        bid_size=Quantity.from_int(100),
        ask_size=Quantity.from_int(100),
        ts_event=0,
        ts_init=0,
    )


@pytest.fixture
def alert_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Captures what the DEFAULT sink emits -- `LoggingAlertSink`, not a double.

    The FIXTURE is yielded rather than `caplog.records`: that property builds a
    new list on each access, so a list captured here would stay empty forever
    and every assertion below would pass vacuously.
    """
    with caplog.at_level(logging.WARNING, logger="breezy.runtime.health"):
        yield caplog


def test_a_default_configured_strategy_alerts_that_shorting_disabled_it(
    alert_log: pytest.LogCaptureFixture,
) -> None:
    strategy = _registered_strategy(
        CalibrationMeanReversionConfig(instrument_ids=(INSTRUMENT_ID,)),
    ).strategy

    strategy.on_quote_tick(_rich_quote())

    messages = [record.getMessage() for record in alert_log.records]
    assert any(SHORTS_DISABLED_EVENT in message for message in messages), messages
    assert any(str(strategy.id) in message for message in messages), messages
    assert strategy.cache.orders() == []  # and nothing was traded


def test_the_same_strategy_with_shorting_enabled_raises_no_such_alert(
    alert_log: pytest.LogCaptureFixture,
) -> None:
    """The control: the alert tracks the DISABLEMENT, not the market.

    Same instrument, same book, same forecast -- only the permission differs.
    Without this, an alert that fired unconditionally would look identical.
    """
    rig = _registered_strategy(
        CalibrationMeanReversionConfig(instrument_ids=(INSTRUMENT_ID,), allow_short=True),
    )

    rig.strategy.on_quote_tick(_rich_quote())

    messages = [record.getMessage() for record in alert_log.records]
    assert not any(SHORTS_DISABLED_EVENT in message for message in messages), messages
    assert rig.strategy.refusals.total() == 0
    # NOT vacuous: this same input really does produce a tradable signal, so
    # the silence above is the permission changing and nothing else.
    orders = rig.strategy.cache.orders()
    assert len(orders) == 1
    assert orders[0].side == OrderSide.SELL


def test_the_refusal_is_counted_once_per_refused_signal(
    alert_log: pytest.LogCaptureFixture,
) -> None:
    """The COUNT keeps rising even though the alert is deduped to one payload.

    Re-notify (24h) reports the accumulated total, so an operator who reads the
    second alert learns the scale, not just the fact.
    """
    strategy, clock, _commands = _registered_strategy(
        CalibrationMeanReversionConfig(instrument_ids=(INSTRUMENT_ID,), recheck_minutes=20.0),
    )

    strategy.on_quote_tick(_rich_quote())
    # Past `recheck_minutes`, or the second evaluation is throttled and this
    # test would pass for the wrong reason.
    clock.set_time(30 * 60 * 1_000_000_000)
    strategy.on_quote_tick(_rich_quote())

    assert strategy.refusals.count(SHORTS_DISABLED) == 2
    fired = [r for r in alert_log.records if SHORTS_DISABLED_EVENT in r.getMessage()]
    assert len(fired) == 1
