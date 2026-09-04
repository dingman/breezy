"""`_convert_live_capture` must survive a re-emitted instrument definition.

The real capture for instance ``5a111bca-c349-49d7-94bc-948649485ac8`` holds
MORE THAN ONE ``binary_option_*.feather`` file for the same instrument,
because the recorder re-emits instrument definitions on every discovery
cycle carrying their ORIGINAL ``ts_init`` (see
``breezy.runtime.quote_tape_ingest_cli``'s module docstring). Converting such
an instance with the native ``ParquetDataCatalog.convert_stream_to_data``
call fails permanently once the second file's interval lands inside the
first file's already-written interval
(``ValueError: ... would create non-disjoint intervals``,
``parquet.py:2690``).

These tests build that exact shape -- two feather files, same instrument,
nested intervals -- against a REAL ``ParquetDataCatalog`` (native Arrow IPC
streams, no mocked catalog), reproduce the failure through
``_convert_live_capture`` (RED), and then pin the fix: instrument
definitions route through ``breezy.runtime.quote_tape_ingest_cli``'s
row-wise, de-duplicated conversion instead, while quote ticks keep the
single native ``convert_stream_to_data`` call, unchanged.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pyarrow as pa
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.writer import StreamingFeatherWriter
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer


def _load_runner_module() -> ModuleType:
    path = Path("scripts/analysis/run_weather_strategy_backtests.py")
    sys.path.insert(0, path.parent.as_posix())
    spec = importlib.util.spec_from_file_location(
        "run_weather_strategy_backtests_convert_live_capture", path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner_module()

INSTANCE = "instance-1"
_VENUE = Venue("POLYUS")

#: T0 < T1 < T2. T1 (the re-emitted definition's point interval) lands
#: strictly inside the [T0, T2] interval of the file written first.
T0 = 1_788_272_911_000_000_000
T1 = 1_788_280_000_000_000_000
T2 = 1_788_294_512_000_000_000


def _binary_option(symbol: str, ts_init: int) -> BinaryOption:
    raw_symbol = Symbol(symbol)
    return BinaryOption(
        instrument_id=InstrumentId(symbol=raw_symbol, venue=_VENUE),
        raw_symbol=raw_symbol,
        outcome="Yes",
        description="convert-live-capture fixture",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        size_precision=0,
        size_increment=Quantity.from_int(1),
        activation_ns=0,
        expiration_ns=1_800_000_000_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=ts_init,
        ts_init=ts_init,
    )


def _quote_tick(instrument_id: InstrumentId, ts_init: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str("0.40"),
        ask_price=Price.from_str("0.45"),
        bid_size=Quantity.from_int(10),
        ask_size=Quantity.from_int(10),
        ts_event=ts_init,
        ts_init=ts_init,
    )


def _write_stream_feather(
    catalog_root: Path,
    instance_id: str,
    name: str,
    records: list,
    *,
    data_cls: type,
) -> Path:
    """Write ``records`` as one closed Arrow IPC stream, the shape the
    recorder's ``StreamingFeatherWriter`` produces for one discovery cycle.
    """
    batch = ArrowSerializer.serialize_batch(records, data_cls=data_cls)
    table = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
    table = table.replace_schema_metadata({"class": data_cls.__name__})

    path = catalog_root / "live" / instance_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, table.schema)
        writer.write_table(table)
        writer.close()
    return path


def _write_quote_tick_stream(
    quote_catalog: Path, instrument: BinaryOption, quotes: list[QuoteTick]
) -> None:
    """Write ``quotes`` through the REAL ``StreamingFeatherWriter``.

    Quote ticks use Nautilus' per-instrument writer, which embeds
    ``instrument_id`` (and precision) schema metadata that
    ``ParquetDataCatalog.convert_stream_to_data`` requires to file the
    converted parquet under ``data/quote_tick/<instrument_id>/`` and answer
    an identifier-filtered query. Hand-crafting that metadata is exactly the
    kind of native-behaviour duplication this repo avoids -- the real writer
    is used instead, matching ``test_catalog_market_data_backtest.py``.
    """
    cache = Cache(database=None)
    cache.add_instrument(instrument)
    writer = StreamingFeatherWriter(
        path=str(quote_catalog / "live" / INSTANCE),
        cache=cache,
        clock=TestClock(),
        include_types=[QuoteTick],
    )
    for quote in quotes:
        writer.write(quote)
    writer.close()


def _seed_two_nested_definition_files(quote_catalog: Path, instrument: BinaryOption) -> None:
    """Two feather files for the SAME instrument, nested intervals.

    Mirrors the real capture exactly: one file spans ``[T0, T2]`` (an
    earlier multi-row discovery cycle), the second is a single re-emitted
    row at ``T1``, strictly inside the first file's interval. Both files
    exist BEFORE any conversion is attempted -- unlike the ingest-cli
    fixtures, there is no separate "seed" conversion step here, because the
    real defect fires the first time `_convert_live_capture` ever touches
    this instance.
    """
    _write_stream_feather(
        quote_catalog,
        INSTANCE,
        "binary_option_0.feather",
        [
            _binary_option(instrument.raw_symbol.value, T0),
            _binary_option(instrument.raw_symbol.value, T2),
        ],
        data_cls=BinaryOption,
    )
    _write_stream_feather(
        quote_catalog,
        INSTANCE,
        "binary_option_1.feather",
        [_binary_option(instrument.raw_symbol.value, T1)],
        data_cls=BinaryOption,
    )


class TestConvertLiveCaptureSurvivesReEmittedDefinitions:
    def test_two_nested_definition_intervals_convert_without_error(
        self, tmp_path: Path
    ) -> None:
        quote_catalog = tmp_path / "capture"
        work_catalog = tmp_path / "work"
        instrument = _binary_option("MKT-A", T0)
        _seed_two_nested_definition_files(quote_catalog, instrument)
        _write_quote_tick_stream(
            quote_catalog,
            instrument,
            [_quote_tick(instrument.id, T0), _quote_tick(instrument.id, T2)],
        )

        work = runner._convert_live_capture(
            quote_catalog=quote_catalog,
            instance_id=INSTANCE,
            subdirectory="live",
            work_catalog=work_catalog,
        )

        landed_ids = {i.id.value for i in work.instruments()}
        assert instrument.id.value in landed_ids

        quotes = work.quote_ticks(instrument_ids=[instrument.id.value])
        assert sorted(q.ts_init for q in quotes) == [T0, T2]

        # The read-only capture is never written to: no `data/` partition
        # appears under the source root, only the pre-existing `live/`
        # feather staging directory.
        assert not (quote_catalog / "data").exists()

    def test_definitions_land_deduplicated_and_content_matches(self, tmp_path: Path) -> None:
        quote_catalog = tmp_path / "capture"
        work_catalog = tmp_path / "work"
        instrument = _binary_option("MKT-A", T0)
        _seed_two_nested_definition_files(quote_catalog, instrument)
        _write_quote_tick_stream(quote_catalog, instrument, [_quote_tick(instrument.id, T0)])

        work = runner._convert_live_capture(
            quote_catalog=quote_catalog,
            instance_id=INSTANCE,
            subdirectory="live",
            work_catalog=work_catalog,
        )

        definitions = work.query(data_cls=BinaryOption)
        assert sorted(d.ts_init for d in definitions) == [T0, T1, T2]
