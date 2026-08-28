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
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import (
    VENUE_MARKET_DATA_TYPES,
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

    # H-2: tightened from the bare class name "NwsClimateDay" (which could
    # appear in the message for an unrelated reason, e.g. listing it among
    # accepted types) to the actual CLAIM the message makes about it.
    assert "NwsClimateDay is not venue market data" in str(excinfo.value)


def test_the_refusal_names_the_field_the_record_belongs_in() -> None:
    """An error that does not say where to put it teaches nothing.

    H-2: tightened from the bare field name "weather_data" (which the message
    ALSO uses when explaining what `market_data` accepts INSTEAD, so a
    substring match on the name alone does not pin the "put it there"
    instruction specifically) to the actual routing instruction.
    """
    with pytest.raises(NotVenueMarketDataError) as excinfo:
        assert_market_data_is_venue_data([make_climate_day()])

    assert "it belongs in `weather_data`" in str(excinfo.value)


def test_a_WRAPPED_weather_record_in_market_data_is_also_refused() -> None:
    """Wrapping fixes the dispatch, not the routing.

    `weather_data` is added with `client_id=NWS_BACKTEST_CLIENT_ID`; the same
    envelope in `market_data` reaches a client nothing subscribes to.
    """
    wrapped = as_backtest_data([make_climate_day()])

    with pytest.raises(NotVenueMarketDataError) as excinfo:
        assert_market_data_is_venue_data(list(wrapped))

    assert "it belongs in `weather_data`" in str(excinfo.value)


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


# ---------------------------------------------------------------------------
# H-3: `Bar` is excluded from `VENUE_MARKET_DATA_TYPES`, and that exclusion
# is CORRECT -- pinned with the evidence, not merely asserted.
# ---------------------------------------------------------------------------


def _make_bar(instrument_id: object) -> Bar:
    """A real `Bar`, minimally populated, for the one instrument under test."""
    bar_type = BarType(instrument_id, BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST))
    return Bar(
        bar_type,
        Price(1, 2),
        Price(1, 2),
        Price(1, 2),
        Price(1, 2),
        Quantity(1, 0),
        0,
        0,
    )


def test_bar_is_absent_from_the_venue_market_data_allowlist() -> None:
    """The allowlist itself, not merely the runtime refusal.

    `add_data` accepts `Bar`, so its absence here is a deliberate CHOICE, not
    a gap that happens to also refuse it -- pinning the set membership
    directly is what would catch someone re-adding it to the allowlist
    without addressing why it was never there.
    """
    assert Bar not in VENUE_MARKET_DATA_TYPES


def test_a_bar_in_market_data_is_refused() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    bar = _make_bar(tape.instrument.id)

    with pytest.raises(NotVenueMarketDataError) as excinfo:
        assert_market_data_is_venue_data([*tape.all_data(), bar])

    assert "Bar" in str(excinfo.value)


def test_bar_carries_its_instrument_under_bar_type_not_instrument_id() -> None:
    """THE reason `Bar` cannot share the grouping the other venue types use.

    `_group_market_data` (the function `build_backtest_engine` calls on
    `config.market_data`) keys its groups on `record.instrument_id`. Every
    admitted type in `VENUE_MARKET_DATA_TYPES` -- `OrderBookDelta(s)`,
    `OrderBookDepth10`, `QuoteTick`, `TradeTick`, `InstrumentClose`,
    `InstrumentStatus` -- carries that attribute directly. `Bar` does not: its
    instrument lives at `bar.bar_type.instrument_id`. Admitting `Bar` into the
    allowlist without special-casing the grouping function would not silently
    misgroup it -- it would raise `AttributeError` the first time a `Bar`
    reached `_group_market_data`, proven here directly against the real
    native class rather than asserted from the comment.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    bar = _make_bar(tape.instrument.id)

    assert bar.bar_type.instrument_id == tape.instrument.id
    with pytest.raises(AttributeError):
        bar.instrument_id  # noqa: B018 - the point IS the attribute access


def test_the_harness_refuses_a_bar_from_the_builder_too() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    bar = _make_bar(tape.instrument.id)
    config = BreezyBacktestConfig(
        instruments=(tape.instrument,),
        market_data=[*tape.all_data(), bar],
        settlement_prices={tape.instrument.id: tape.settlement_price},
        starting_balances=(Money(1_000, USD),),
    )

    with pytest.raises(NotVenueMarketDataError):
        build_backtest_engine(config)
