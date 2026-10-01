"""D+1 ids come from the catalog UNION the native cache, not the catalog alone.

The quote-tape catalog only holds the current climate day. The instrument
provider has already loaded tomorrow's markets into ``self.cache`` at boot.
An empty catalog must still subscribe this station's D+1 YES rungs (and each
rung's NO leg); catalog ids must still subscribe when the cache scan is
empty; an id present in both sources is subscribed once.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, MutableMapping
from decimal import Decimal

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.strategy.current_rung_hold.composition import InstrumentStationMismatchError
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from tests.strategy.forecast_quantile_ladder.test_sl13_s6_wiring import (
    _artefact,
    _bounds_provider,
    _config,
)
from tests.support.nautilus_log_capture import capture_nautilus_logs

_VENUE = Venue("POLYMARKET_US")
_STATION = "LAX"
_OTHER = "MIA"
# 2026-10-01T20:00:00Z. LAX LST (UTC-8) is 12:00 on 2026-10-01, so D+1 is 2026-10-02.
_NOW_NS = 1_790_884_800_000_000_000
_TODAY = dt.date(2026, 10, 1)
_D1 = dt.date(2026, 10, 2)
_QUOTE_PREFIX = "data.quotes.POLYMARKET_US."


class _HideScanCache(Cache):  # type: ignore[misc]  # Cython Cache is Any to mypy
    """Lookup by id still works; ``instruments()`` (the cache scan) is empty."""

    def instruments(
        self, venue: Venue | None = None, underlying: str | None = None,
    ) -> list[BinaryOption]:
        del venue, underlying
        return []


def _yes(
    symbol: str, *, station: str, climate_day: dt.date, lower_f: int, upper_f: int,
) -> BinaryOption:
    instrument_id = InstrumentId(Symbol(symbol), _VENUE)
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description=f"{station} daily high",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: station,
            CLIMATE_DAY_KEY: climate_day.isoformat(),
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: lower_f,
            STRIKE_UPPER_F_KEY: upper_f,
        },
    )


def _no(yes: BinaryOption) -> BinaryOption:
    no_id = sibling_instrument_id(yes.id)
    return BinaryOption(
        instrument_id=no_id,
        raw_symbol=no_id.symbol,
        outcome="No",
        description="no leg",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=yes.price_precision,
        price_increment=yes.price_increment,
        size_precision=yes.size_precision,
        size_increment=yes.size_increment,
        activation_ns=0,
        expiration_ns=yes.expiration_ns,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info=dict(yes.info),
    )


def _build(
    *,
    instruments: tuple[BinaryOption, ...],
    initial_ids: tuple[str, ...],
    hide_scan: bool,
    d1_resolver: Callable[[], tuple[str, ...]] | None,
) -> tuple[ForecastQuantileLadderStrategy, MessageBus, MutableMapping[str, bool | None]]:
    clock = TestClock()
    clock.set_time(_NOW_NS)
    msgbus = TestComponentStubs.msgbus()
    cache: Cache = _HideScanCache(database=None) if hide_scan else TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    actor = ForecastQuantileStateActor(stations=(_STATION,), std_utc_offset_hours={_STATION: -8.0})
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(), msgbus=msgbus, cache=cache, clock=clock,
    )
    actor.start()
    state: MutableMapping[str, bool | None] = {}
    strategy = ForecastQuantileLadderStrategy(
        _config(_STATION),
        quantile_actor=actor,
        calibration=_artefact(),
        ladder_cfg=LadderEvConfig(),
        bounds_provider=_bounds_provider,
        instrument_ids=initial_ids,
        d1_resolver=d1_resolver,
        d1_readiness_state=state,
    )
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    return strategy, msgbus, state


def _quote_symbols(msgbus: MessageBus) -> set[str]:
    topics = msgbus.topics()
    return {topic[len(_QUOTE_PREFIX):] for topic in topics if topic.startswith(_QUOTE_PREFIX)}


def _assert_subscribed(
    strategy: ForecastQuantileLadderStrategy,
    msgbus: MessageBus,
    *,
    yes_ids: tuple[InstrumentId, ...],
    lines: list[str],
) -> None:
    expected_yes = {str(instrument_id) for instrument_id in yes_ids}
    got_yes = {yes for yes, _no in strategy.rung_instruments.values()}
    assert got_yes == expected_yes
    assert {key[0] for key in strategy.rung_instruments} == {_STATION}
    assert {key[1] for key in strategy.rung_instruments} == {_D1.isoformat()}
    expected_symbols: set[str] = set()
    for instrument_id in yes_ids:
        no_id = sibling_instrument_id(instrument_id)
        expected_symbols.add(instrument_id.symbol.value)
        expected_symbols.add(no_id.symbol.value)
        yes_str, no_str = strategy.rung_instruments[
            (_STATION, _D1.isoformat(), _rung_id(instrument_id, strategy))
        ]
        assert yes_str == str(instrument_id)
        assert no_str == str(no_id)
    assert _quote_symbols(msgbus) == expected_symbols
    blob = "\n".join(lines)
    assert len(re.findall(rf"subscribed n={len(yes_ids)}(?!\d)", blob)) == 1
    for instrument_id in yes_ids:
        assert len(re.findall(rf"subscribed {re.escape(str(instrument_id))}(?!\S)", blob)) == 1


def _rung_id(instrument_id: InstrumentId, strategy: ForecastQuantileLadderStrategy) -> str:
    for (_station, _day, rung_id), (yes_id, _no_id) in strategy.rung_instruments.items():
        if yes_id == str(instrument_id):
            return rung_id
    raise AssertionError(f"{instrument_id} was not subscribed")


def test_empty_catalog_subscribes_d1_yes_rungs_from_the_cache() -> None:
    """Cache holds D+1 YES, the NO leg, today's market, and another station.

    The catalog list and the readiness resolver are both empty. on_start
    subscribes exactly this station's D+1 YES rungs plus each NO leg.
    """
    yes_a = _yes("lax-d1-80-81", station=_STATION, climate_day=_D1, lower_f=80, upper_f=81)
    yes_b = _yes("lax-d1-82-83", station=_STATION, climate_day=_D1, lower_f=82, upper_f=83)
    today = _yes("lax-d0-80-81", station=_STATION, climate_day=_TODAY, lower_f=80, upper_f=81)
    other = _yes("mia-d1-80-81", station=_OTHER, climate_day=_D1, lower_f=80, upper_f=81)
    read = capture_nautilus_logs()
    strategy, msgbus, state = _build(
        instruments=(today, other, _no(yes_a), _no(yes_b), yes_b, yes_a),
        initial_ids=(),
        hide_scan=False,
        d1_resolver=lambda: (),
    )

    strategy.start()

    assert state[_STATION] is True
    _assert_subscribed(
        strategy, msgbus, yes_ids=(yes_a.id, yes_b.id), lines=read(),
    )


def test_catalog_ids_still_subscribe_when_the_cache_scan_is_empty() -> None:
    yes_a = _yes("lax-d1-80-81", station=_STATION, climate_day=_D1, lower_f=80, upper_f=81)
    yes_b = _yes("lax-d1-82-83", station=_STATION, climate_day=_D1, lower_f=82, upper_f=83)
    today = _yes("lax-d0-80-81", station=_STATION, climate_day=_TODAY, lower_f=80, upper_f=81)
    other = _yes("mia-d1-80-81", station=_OTHER, climate_day=_D1, lower_f=80, upper_f=81)
    read = capture_nautilus_logs()
    strategy, msgbus, state = _build(
        instruments=(today, other, _no(yes_a), _no(yes_b), yes_b, yes_a),
        initial_ids=(str(yes_a.id),),
        hide_scan=True,
        d1_resolver=lambda: (),
    )

    strategy.start()

    assert state[_STATION] is True
    _assert_subscribed(strategy, msgbus, yes_ids=(yes_a.id,), lines=read())


def test_an_id_in_the_catalog_and_the_cache_is_subscribed_once() -> None:
    yes_a = _yes("lax-d1-80-81", station=_STATION, climate_day=_D1, lower_f=80, upper_f=81)
    yes_b = _yes("lax-d1-82-83", station=_STATION, climate_day=_D1, lower_f=82, upper_f=83)
    today = _yes("lax-d0-80-81", station=_STATION, climate_day=_TODAY, lower_f=80, upper_f=81)
    other = _yes("mia-d1-80-81", station=_OTHER, climate_day=_D1, lower_f=80, upper_f=81)
    read = capture_nautilus_logs()
    strategy, msgbus, state = _build(
        instruments=(today, other, _no(yes_a), _no(yes_b), yes_b, yes_a),
        initial_ids=(str(yes_a.id),),
        hide_scan=False,
        d1_resolver=lambda: (str(yes_a.id),),
    )

    strategy.start()
    # A second pass (the readiness poll's own call) must not subscribe again.
    assert strategy._subscribe_ids(strategy._instrument_ids) == 0

    assert state[_STATION] is True
    _assert_subscribed(
        strategy, msgbus, yes_ids=(yes_a.id, yes_b.id), lines=read(),
    )


_MISMATCH = "lax id re-parses to MIA"


def _raise_station_mismatch(*_args: object, **_kwargs: object) -> None:
    raise InstrumentStationMismatchError(_MISMATCH)


def test_on_start_bucket_mismatch_fails_closed_and_arms_the_timer(monkeypatch: object) -> None:
    """A symbology mismatch in the cache scan must not escape on_start.

    L-16: the handler logs the station and the exception, subscribes nothing,
    and still arms the readiness poll.
    """
    yes_a = _yes("lax-d1-80-81", station=_STATION, climate_day=_D1, lower_f=80, upper_f=81)
    read = capture_nautilus_logs()
    strategy, msgbus, state = _build(
        instruments=(_no(yes_a), yes_a),
        initial_ids=(),
        hide_scan=False,
        d1_resolver=lambda: (),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "breezy.strategy.forecast_quantile_ladder.strategy.bucket_station_instrument_ids",
        _raise_station_mismatch,
    )

    strategy.start()

    blob = "\n".join(read())
    assert strategy.rung_instruments == {}
    assert strategy._instrument_context == {}
    assert _quote_symbols(msgbus) == set()
    assert "subscribed n=" not in blob
    assert state.get(_STATION) is None
    assert strategy._d1_timer_name == f"fq-d1-readiness-{_STATION}"
    assert strategy._d1_timer_name in strategy.clock.timer_names
    assert f"station={_STATION}" in blob
    assert "InstrumentStationMismatchError" in blob
    assert _MISMATCH in blob


def test_readiness_timer_bucket_mismatch_counts_the_attempt(monkeypatch: object) -> None:
    """The same mismatch inside the timer callback is counted, not fatal."""
    yes_a = _yes("lax-d1-80-81", station=_STATION, climate_day=_D1, lower_f=80, upper_f=81)
    read = capture_nautilus_logs()
    strategy, msgbus, state = _build(
        instruments=(_no(yes_a), yes_a),
        initial_ids=(),
        hide_scan=False,
        d1_resolver=lambda: (),
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "breezy.strategy.forecast_quantile_ladder.strategy.bucket_station_instrument_ids",
        _raise_station_mismatch,
    )
    strategy.start()
    assert strategy._d1_attempts == 0

    strategy._on_d1_readiness_timer(object())

    blob = "\n".join(read())
    assert strategy._d1_attempts == 1
    assert strategy.rung_instruments == {}
    assert strategy._instrument_context == {}
    assert _quote_symbols(msgbus) == set()
    assert state.get(_STATION) is None
    assert strategy._d1_timer_name in strategy.clock.timer_names
    assert f"station={_STATION}" in blob
    assert "InstrumentStationMismatchError" in blob
    assert _MISMATCH in blob
