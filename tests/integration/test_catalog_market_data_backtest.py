"""Catalog-to-backtest proofs for captured venue market data.

Everything here fabricates data first, writes it through Nautilus' native
catalog or streaming writer, and then treats the disk catalog as the source of
truth. No venue endpoint is touched.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.model.data import InstrumentClose, OrderBookDepth10, QuoteTick
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.writer import StreamingFeatherWriter

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import BreezyBacktestConfig, run_backtest
from breezy.strategy.harness_probe import BreezyHarnessProbe, BreezyHarnessProbeConfig
from tests.support.synthetic_binary_tape import SyntheticBinaryTape, synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

STARTING_BALANCE_USD = 1_000
TRADE_QUANTITY = Decimal(10)
INSTANCE_ID = "instance-1"


def _catalog_records(
    catalog: ParquetDataCatalog,
    tape: SyntheticBinaryTape,
    *,
    expected_depths: int,
    expected_quotes: int,
    expected_closes: int,
) -> tuple[BinaryOption, list[OrderBookDepth10], list[QuoteTick], list[InstrumentClose]]:
    instrument_id = tape.instrument.id.value
    instruments = [
        instrument for instrument in catalog.instruments() if instrument.id == tape.instrument.id
    ]
    definitions = catalog.query(data_cls=BinaryOption)
    depths = catalog.order_book_depth10(instrument_ids=[instrument_id])
    quotes = catalog.quote_ticks(instrument_ids=[instrument_id])
    closes = [
        close for close in catalog.instrument_closes() if close.instrument_id == tape.instrument.id
    ]

    assert [instrument.id for instrument in instruments] == [tape.instrument.id]
    assert [definition.id for definition in definitions] == [tape.instrument.id]
    assert all(isinstance(instrument, BinaryOption) for instrument in instruments)
    assert [depth.instrument_id for depth in depths] == [tape.instrument.id] * len(depths)
    assert [quote.instrument_id for quote in quotes] == [tape.instrument.id] * len(quotes)
    assert [close.instrument_id for close in closes] == [tape.instrument.id]
    assert len(instruments) == 1
    assert len(definitions) == 1
    assert len(depths) == expected_depths
    assert len(quotes) == expected_quotes
    assert len(closes) == expected_closes

    return instruments[0], depths, quotes, closes


def _run_probe_backtest(
    *,
    tape: SyntheticBinaryTape,
    instrument: BinaryOption,
    depths: list[OrderBookDepth10],
    quotes: list[QuoteTick],
    closes: list[InstrumentClose],
) -> BreezyHarnessProbe:
    strategy = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=instrument.id,
            station="NYC",
            trade_quantity=TRADE_QUANTITY,
        ),
    )
    engine = run_backtest(
        BreezyBacktestConfig(
            instruments=(instrument,),
            market_data=[*depths, *quotes, *closes],
            weather_data=as_backtest_data(
                [
                    make_climate_day(
                        station="NYC",
                        tmax_f=84,
                        is_final=True,
                        retrieved_at_ns=tape.weather_ts_ns,
                    ),
                ],
            ),
            settlement_prices={instrument.id: tape.settlement_price},
            starting_balances=(Money(STARTING_BALANCE_USD, instrument.quote_currency),),
        ),
        strategies=(strategy,),
    )
    try:
        fills = [
            event
            for order in engine.cache.orders()
            for event in order.events
            if isinstance(event, OrderFilled)
        ]

        assert len(fills) >= 1
        assert len(engine.cache.positions()) == 1
        assert engine.cache.positions()[0].is_closed
    finally:
        engine.dispose()

    assert strategy.depths == len(depths)
    assert strategy.quotes == len(quotes)
    assert strategy.closes == len(closes)
    assert strategy.weather == 1
    assert strategy.orders_submitted == 1
    assert strategy.own_fills == 1
    assert strategy.traded_station == "NYC"
    return strategy


def _decision_index(strategy: BreezyHarnessProbe, needle: str) -> int:
    for index, entry in enumerate(strategy.decisions):
        if needle in entry:
            return index
    raise AssertionError(f"missing decision entry containing {needle!r}: {strategy.decisions}")


def _first_two_depth_quote_pairs(tape: SyntheticBinaryTape) -> list[object]:
    # The first depth is before weather, so the probe can still trade; omitting
    # the third pair makes `tape.all_data()` detectably too large.
    return [*tape.market_data[:4], tape.instrument_close]


def test_native_catalog_market_data_reads_back_and_runs_a_trading_backtest(
    tmp_path: Path,
) -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    catalog = ParquetDataCatalog(tmp_path)
    catalog_data = _first_two_depth_quote_pairs(tape)

    catalog.write_data([tape.instrument, *catalog_data])

    instrument, depths, quotes, closes = _catalog_records(
        catalog,
        tape,
        expected_depths=2,
        expected_quotes=2,
        expected_closes=1,
    )
    strategy = _run_probe_backtest(
        tape=tape,
        instrument=instrument,
        depths=depths,
        quotes=quotes,
        closes=closes,
    )

    assert strategy.decisions[0] == f"0|started|{tape.instrument.id}"
    assert _decision_index(strategy, "|depth|seq=0") < _decision_index(
        strategy, "|weather|NYC:2026-08-22"
    )
    assert _decision_index(strategy, "|weather|NYC:2026-08-22") < _decision_index(
        strategy, f"|submit|BUY:{TRADE_QUANTITY}"
    )
    assert any("|quote|" in entry for entry in strategy.decisions)
    assert any("|close|" in entry for entry in strategy.decisions)


def test_live_feather_stream_converts_to_readable_catalog_data_and_backtests(
    tmp_path: Path,
) -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    cache = Cache(database=None, config=CacheConfig())
    cache.add_instrument(tape.instrument)
    writer = StreamingFeatherWriter(
        path=str(tmp_path / "live" / INSTANCE_ID),
        cache=cache,
        clock=TestClock(),
        include_types=[BinaryOption, OrderBookDepth10, QuoteTick, InstrumentClose],
    )
    writer.write(tape.instrument)
    for record in tape.all_data():
        writer.write(record)
    writer.close()

    catalog = ParquetDataCatalog(tmp_path)
    assert catalog.quote_ticks(instrument_ids=[tape.instrument.id.value]) == []
    assert catalog.instruments(instrument_ids=[tape.instrument.id.value]) == []

    catalog.convert_stream_to_data(INSTANCE_ID, BinaryOption, subdirectory="live")
    catalog.convert_stream_to_data(INSTANCE_ID, OrderBookDepth10, subdirectory="live")
    catalog.convert_stream_to_data(INSTANCE_ID, QuoteTick, subdirectory="live")
    catalog.convert_stream_to_data(INSTANCE_ID, InstrumentClose, subdirectory="live")

    instrument, depths, quotes, closes = _catalog_records(
        catalog,
        tape,
        expected_depths=3,
        expected_quotes=3,
        expected_closes=1,
    )
    strategy = _run_probe_backtest(
        tape=tape,
        instrument=instrument,
        depths=depths,
        quotes=quotes,
        closes=closes,
    )

    assert strategy.orders_submitted == 1


def test_strategy_quickstart_documents_captured_catalog_backtests() -> None:
    text = Path("docs/specs/STRATEGY_QUICKSTART.md").read_text(encoding="utf-8")

    assert "## 8. Backtest Against Captured Catalog Data" in text
    assert "convert_stream_to_data" in text
    assert "catalog.quote_ticks" in text
    assert "catalog.instruments" in text
