"""``market_data`` is screened too, not only ``weather_data``.

``assert_weather_is_wrapped`` was scoped to ``config.weather_data``, so the
single most natural mistake -- putting the weather records in ``market_data``,
where every other record already lives -- went entirely unchecked.

What happens to a bare ``NwsClimateDay`` in ``market_data``
----------------------------------------------------------

``BacktestEngine.add_data`` validates only ``data[0]`` (``engine.pyx:863``).
If the first element is a depth record the bare weather record sails past
validation, is sorted into the stream, and is then handed to
``DataEngine._handle_data``, whose terminal ``else`` LOGS AND DROPS. The run
completes. The strategy's ``on_data`` is never called. The bot has never seen
weather, and nothing says so.

A *wrapped* ``CustomData`` record in ``market_data`` is no better: the wrapped
weather stream must be added with ``client_id=NWS_BACKTEST_CLIENT_ID``, which
is what ``weather_data`` is for. Placed in ``market_data`` it either raises an
opaque ``client_id`` condition failure inside Nautilus or is routed to a client
no strategy subscribes to.

So the screen is an ALLOWLIST of venue market-data types rather than a
blocklist of known-bad ones: the failure mode is "something unforeseen was
dropped", and a blocklist cannot catch the unforeseen.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import (
    BreezyBacktestConfig,
    NotVenueMarketDataError,
    assert_market_data_is_venue_data,
    build_backtest_engine,
)
from tests.support.synthetic_binary_tape import synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day


def _config(**overrides: object) -> BreezyBacktestConfig:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    kwargs: dict[str, object] = {
        "instruments": (tape.instrument,),
        "market_data": tape.all_data(),
        "settlement_prices": {tape.instrument.id: tape.settlement_price},
        "starting_balances": (Money(1_000, USD),),
    }
    kwargs.update(overrides)
    return BreezyBacktestConfig(**kwargs)  # type: ignore[arg-type]


def test_a_bare_weather_record_in_market_data_is_refused() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    with pytest.raises(NotVenueMarketDataError) as excinfo:
        assert_market_data_is_venue_data([*tape.all_data(), make_climate_day()])

    assert "NwsClimateDay" in str(excinfo.value)


def test_the_refusal_names_the_field_the_record_belongs_in() -> None:
    """An error that does not say where to put it teaches nothing."""
    with pytest.raises(NotVenueMarketDataError) as excinfo:
        assert_market_data_is_venue_data([make_climate_day()])

    assert "weather_data" in str(excinfo.value)


def test_a_WRAPPED_weather_record_in_market_data_is_also_refused() -> None:
    """Wrapping fixes the dispatch, not the routing.

    `weather_data` is added with `client_id=NWS_BACKTEST_CLIENT_ID`; the same
    envelope in `market_data` reaches a client nothing subscribes to.
    """
    wrapped = as_backtest_data([make_climate_day()])

    with pytest.raises(NotVenueMarketDataError) as excinfo:
        assert_market_data_is_venue_data(list(wrapped))

    assert "weather_data" in str(excinfo.value)


def test_the_screen_runs_from_the_builder() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    with pytest.raises(NotVenueMarketDataError):
        build_backtest_engine(_config(market_data=[*tape.all_data(), make_climate_day()]))


def test_a_clean_venue_tape_passes_the_screen() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    assert_market_data_is_venue_data(tape.all_data())


def test_the_screen_is_type_exact_so_a_subclass_does_not_slip_through() -> None:
    """`DataEngine._handle_data` dispatches on exact types, so a subclass of a
    market-data type is not what it recognises either.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    depth = tape.market_data[0]

    class _DepthSubclass(type(depth)):  # type: ignore[misc]
        pass

    impostor = _DepthSubclass(
        instrument_id=depth.instrument_id,
        bids=list(depth.bids),
        asks=list(depth.asks),
        bid_counts=list(depth.bid_counts),
        ask_counts=list(depth.ask_counts),
        flags=depth.flags,
        sequence=depth.sequence,
        ts_event=depth.ts_event,
        ts_init=depth.ts_init,
    )

    with pytest.raises(NotVenueMarketDataError):
        assert_market_data_is_venue_data([impostor])
