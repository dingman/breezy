"""Contract: the streaming-persistence facts that fail SILENTLY on a version bump.

Every assertion here was executed against the **installed
`nautilus-trader 1.231.0`** before it was written. This file exists because
the quote tape is unbackfillable: Polymarket.us weather markets did not exist
before 2026, so a silent capture failure is permanent data loss, and each of
the behaviours pinned below fails with **no exception and no error log**.

Verified `file:line` in the installed 1.231.0 (re-check on a version bump)
-------------------------------------------------------------------------
* `system/kernel.py:508-509` -- the writer is built iff `config.streaming` is set.
* `system/kernel.py:588` -- the stream path is
  `f"{config.catalog_path}/{self._environment.value}/{self.instance_id}"`.
* `system/kernel.py:604` -- `self._trader.subscribe("*", self._writer.write)`;
  the writer sees the WHOLE bus, so `include_types` is the only filter.
* `persistence/writer.py:137-147` -- `quote_tick` is a PER-INSTRUMENT table.
* `persistence/writer.py:228-238` -- per-instrument branch: if the instrument
  is absent from the `Cache`, the method **returns**. No raise, no log.
* `persistence/writer.py:193-195` -- `include_types` is an exclusive filter.
* `persistence/catalog/parquet.py:2604-2635` -- `convert_stream_to_data`,
  whose `subdirectory` argument is documented as "Either 'backtest' or 'live'".
"""

from __future__ import annotations

from datetime import time as datetime_time
from decimal import Decimal
from pathlib import Path

import nautilus_trader
import pandas as pd
import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common import Environment
from nautilus_trader.common.component import TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.writer import RotationMode, StreamingFeatherWriter

pytestmark = pytest.mark.contract

VENUE = Venue("POLYMARKET_US")
SLUG = "tc-temp-nychigh-2026-08-25-lt79f"


def test_pinned_nautilus_version() -> None:
    assert nautilus_trader.__version__.startswith("1.231.")


def make_instrument() -> BinaryOption:
    symbol = Symbol(SLUG)
    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=VENUE),
        raw_symbol=symbol,
        outcome="Yes",
        description="contract fixture",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=3,
        price_increment=Price.from_str("0.001"),
        size_precision=0,
        size_increment=Quantity.from_str("1"),
        activation_ns=0,
        expiration_ns=1_800_000_000_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
    )


def make_quote(instrument: BinaryOption, ts: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price.from_str("0.400"),
        ask_price=Price.from_str("0.410"),
        bid_size=Quantity.from_str("10"),
        ask_size=Quantity.from_str("11"),
        ts_event=ts,
        ts_init=ts,
    )


def make_writer(path: Path, cache: Cache) -> StreamingFeatherWriter:
    return StreamingFeatherWriter(
        path=str(path),
        cache=cache,
        clock=TestClock(),
        include_types=[QuoteTick, BinaryOption],
    )


def test_a_quote_is_silently_discarded_when_its_instrument_is_not_in_the_cache(
    tmp_path: Path,
) -> None:
    """THE trap. No exception, no error log, no file -- just no data, forever.

    `writer.py:228-238`: `quote_tick` is a per-instrument table, the writer
    looks the instrument up in the `Cache` to create the per-instrument writer,
    and when the lookup returns `None` it falls through to a bare `return`.

    The operational consequence, and the reason this is a contract test rather
    than a comment: the recorder's correctness depends on the data client
    publishing instrument definitions BEFORE the first quote. It does --
    `PolymarketUSDataClient._connect` calls
    `_send_all_instruments_to_data_engine()` before subscribing, and
    `DataEngine._handle_instrument` (`data/engine.pyx:2589-2590`) puts them in
    the `Cache`. If a future refactor reorders those two steps, the tape goes
    silently empty and nothing else in the suite notices.
    """
    instrument = make_instrument()
    cache = Cache(database=None, config=CacheConfig())  # deliberately EMPTY
    writer = make_writer(tmp_path / "live" / "instance-1", cache)

    writer.write(make_quote(instrument, 1_000_000_000))  # must not raise
    writer.close()

    catalog = ParquetDataCatalog(tmp_path)
    catalog.convert_stream_to_data("instance-1", QuoteTick, subdirectory="live")

    assert catalog.query(data_cls=QuoteTick) == []


def test_the_same_quote_is_recorded_once_its_instrument_is_in_the_cache(
    tmp_path: Path,
) -> None:
    """The positive half of the pin above: identical inputs, cache populated."""
    instrument = make_instrument()
    cache = Cache(database=None, config=CacheConfig())
    cache.add_instrument(instrument)
    writer = make_writer(tmp_path / "live" / "instance-1", cache)

    writer.write(make_quote(instrument, 1_000_000_000))
    writer.close()

    catalog = ParquetDataCatalog(tmp_path)
    catalog.convert_stream_to_data("instance-1", QuoteTick, subdirectory="live")

    assert len(catalog.query(data_cls=QuoteTick)) == 1


def test_the_live_environment_value_is_the_stream_subdirectory_name() -> None:
    """`kernel.py:588` interpolates `Environment.LIVE.value` into the path.

    Any reader -- including ours -- must pass `subdirectory="live"`, and this
    is the fact that makes that literal correct rather than a guess. A rename
    upstream would otherwise leave the tape on disk and unreadable.
    """
    assert Environment.LIVE.value == "live"


def test_convert_stream_to_data_accepts_the_live_subdirectory(tmp_path: Path) -> None:
    """Not merely documented: exercised. Feather under `live/` becomes parquet."""
    instrument = make_instrument()
    cache = Cache(database=None, config=CacheConfig())
    cache.add_instrument(instrument)
    writer = make_writer(tmp_path / Environment.LIVE.value / "instance-1", cache)
    writer.write(instrument)
    writer.write(make_quote(instrument, 1_000_000_000))
    writer.close()

    assert list(tmp_path.rglob("*.parquet")) == []

    catalog = ParquetDataCatalog(tmp_path)
    catalog.convert_stream_to_data("instance-1", QuoteTick, subdirectory="live")

    assert list(tmp_path.rglob("*.parquet")) != []


def test_quote_ticks_partition_by_instrument_id_in_a_single_catalog_root(
    tmp_path: Path,
) -> None:
    """Why one catalog root serves the whole venue.

    The "one root per station" rule exists for custom types that carry no
    `instrument_id` and therefore write flat, becoming indistinguishable on
    read. `QuoteTick` carries one, so the catalog partitions natively. Pinned
    because the layout decision for an unbackfillable archive rests on it.
    """
    instrument = make_instrument()
    cache = Cache(database=None, config=CacheConfig())
    cache.add_instrument(instrument)
    writer = make_writer(tmp_path / "live" / "instance-1", cache)
    writer.write(make_quote(instrument, 1_000_000_000))
    writer.close()

    catalog = ParquetDataCatalog(tmp_path)
    catalog.convert_stream_to_data("instance-1", QuoteTick, subdirectory="live")

    parquet_paths = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet")]
    assert any(f"data/quote_tick/{instrument.id.value}/" in p for p in parquet_paths), (
        parquet_paths
    )


def test_include_types_is_exclusive_not_additive(tmp_path: Path) -> None:
    """`writer.py:193-195` returns early for any class not in `include_types`.

    Load-bearing because the kernel subscribes the writer to `"*"`
    (`kernel.py:604`): without the filter, every account/order/position event
    and every unrelated data type lands in the tape directory.
    """
    from nautilus_trader.model.data import TradeTick
    from nautilus_trader.model.enums import AggressorSide
    from nautilus_trader.model.identifiers import TradeId

    instrument = make_instrument()
    cache = Cache(database=None, config=CacheConfig())
    cache.add_instrument(instrument)
    writer = make_writer(tmp_path / "live" / "instance-1", cache)

    writer.write(
        TradeTick(
            instrument_id=instrument.id,
            price=Price.from_str("0.400"),
            size=Quantity.from_str("5"),
            aggressor_side=AggressorSide.BUYER,
            trade_id=TradeId("T-1"),
            ts_event=1_000_000_000,
            ts_init=1_000_000_000,
        )
    )
    writer.close()

    # The writer pre-creates an (empty) file for each *included* type at setup,
    # so the assertion is about the EXCLUDED type: no trade_tick stream exists
    # and no trade_tick data can therefore be converted or read back.
    written = [p.name for p in tmp_path.rglob("*.feather")]
    assert not any("trade_tick" in name for name in written), written

    catalog = ParquetDataCatalog(tmp_path)
    catalog.convert_stream_to_data("instance-1", TradeTick, subdirectory="live")
    assert catalog.query(data_cls=TradeTick) == []


def test_each_run_writes_its_own_instance_directory(tmp_path: Path) -> None:
    """Restarts do not overwrite or merge -- they add a sibling directory.

    `kernel.py:588` puts `instance_id` in the path, and `instance_id` is fresh
    per kernel. Two consequences worth pinning: an earlier run's tape is never
    clobbered by a later one, and the set of directories under `live/` is the
    honest record of how many separate capture sessions there were -- i.e. of
    where the gaps are.
    """
    instrument = make_instrument()
    cache = Cache(database=None, config=CacheConfig())
    cache.add_instrument(instrument)

    for instance_id in ("instance-1", "instance-2"):
        writer = make_writer(tmp_path / "live" / instance_id, cache)
        writer.write(make_quote(instrument, 1_000_000_000))
        writer.close()

    assert sorted(p.name for p in (tmp_path / "live").iterdir()) == [
        "instance-1",
        "instance-2",
    ]


# ---------------------------------------------------------------------------
# Depth: the padding trap
# ---------------------------------------------------------------------------


def _book_order(side: OrderSide, price: str, size: str) -> BookOrder:
    return BookOrder(side, Price.from_str(price), Quantity.from_str(size), 0)


def test_nautilus_auto_padding_makes_a_thin_depth_record_unserializable() -> None:
    """`OrderBookDepth10` pads a short side with `NULL_ORDER` -- precision ZERO.

    `model/data.pyx:3497-3502` extends a side shorter than ten with
    `NULL_ORDER`, whose price and size precision are 0. The Arrow encoder then
    rejects the WHOLE record with `ValueError: Mixed metadata at row 0`, and
    `StreamingFeatherWriter.write` catches every exception into a log line
    (`persistence/writer.py:284-287`) -- so a thin book would vanish from the
    tape with no raise and no gap marker.

    A thin book is not exotic: it is what a quiet weather market looks like
    most of the day. `parse_order_book_depth10` therefore pads at the
    instrument's own precision instead. This test pins the upstream behaviour
    that makes that necessary, so a future version that fixes it fails RED here
    rather than leaving Breezy with unexplained padding code.
    """
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    instrument = make_instrument()
    depth = OrderBookDepth10(
        instrument_id=instrument.id,
        bids=[_book_order(OrderSide.BUY, "0.400", "10")],
        asks=[_book_order(OrderSide.SELL, "0.410", "11")],
        bid_counts=[1],
        ask_counts=[1],
        flags=0,
        sequence=0,
        ts_event=1_000_000_000,
        ts_init=1_000_000_000,
    )

    # The padding really is precision-0, which is the root cause.
    assert depth.bids[1].price.precision == 0
    assert instrument.price_precision != 0

    with pytest.raises(ValueError, match="Mixed metadata"):
        ArrowSerializer.serialize_batch([depth], data_cls=OrderBookDepth10)


def test_precision_matched_padding_serializes_and_reads_back(tmp_path: Path) -> None:
    """The workaround, asserted as behaviour: a one-level book reaches disk."""
    instrument = make_instrument()
    cache = Cache(database=None, config=CacheConfig())
    cache.add_instrument(instrument)
    filler_bid = BookOrder(
        OrderSide.BUY,
        Price(0, instrument.price_precision),
        Quantity(0, instrument.size_precision),
        0,
    )
    filler_ask = BookOrder(
        OrderSide.SELL,
        Price(0, instrument.price_precision),
        Quantity(0, instrument.size_precision),
        0,
    )
    depth = OrderBookDepth10(
        instrument_id=instrument.id,
        bids=[_book_order(OrderSide.BUY, "0.400", "10"), *([filler_bid] * 9)],
        asks=[_book_order(OrderSide.SELL, "0.410", "11"), *([filler_ask] * 9)],
        bid_counts=[1, *([0] * 9)],
        ask_counts=[1, *([0] * 9)],
        flags=0,
        sequence=0,
        ts_event=1_000_000_000,
        ts_init=1_000_000_000,
    )

    writer = StreamingFeatherWriter(
        path=str(tmp_path / "live" / "instance-1"),
        cache=cache,
        clock=TestClock(),
        include_types=[OrderBookDepth10, BinaryOption],
    )
    writer.write(instrument)
    writer.write(depth)
    writer.close()

    catalog = ParquetDataCatalog(tmp_path)
    catalog.convert_stream_to_data("instance-1", OrderBookDepth10, subdirectory="live")

    recorded = catalog.query(data_cls=OrderBookDepth10)
    assert len(recorded) == 1
    assert recorded[0].bids[0].price == Price.from_str("0.400")


def test_depth10_carries_exactly_ten_levels_per_side(tmp_path: Path) -> None:
    """The cap is Nautilus's, not Breezy's, and it is a real cut.

    The committed capture `book_open_510636.json` has 12 bid levels and 14
    offer levels, so six levels do not fit. `Condition.is_true(bids_len <= 10)`
    (`model/data.pyx:3491`) is the hard limit. Pinned because the recorder's
    truncation counter and the "slippage is valid to level ten" caveat both
    depend on it.
    """
    instrument = make_instrument()
    eleven = [_book_order(OrderSide.BUY, "0.400", "10")] * 11

    with pytest.raises(ValueError, match="greater than maximum 10"):
        OrderBookDepth10(
            instrument_id=instrument.id,
            bids=eleven,
            asks=eleven,
            bid_counts=[1] * 11,
            ask_counts=[1] * 11,
            flags=0,
            sequence=0,
            ts_event=1,
            ts_init=1,
        )


# ---------------------------------------------------------------------------
# Rotation: the modes are MUTUALLY EXCLUSIVE, not layered
# ---------------------------------------------------------------------------


def test_a_scheduled_rotation_ignores_max_file_size_entirely(tmp_path: Path) -> None:
    """``max_file_size`` is DEAD under ``SCHEDULED_DATES``. There is no backstop.

    ``_check_file_rotation`` (``persistence/writer.py:290-320``) is a single
    ``if/elif`` chain on ``rotation_mode``: the ``SIZE`` branch is the only one
    that reads ``max_file_size``, and it is unreachable once the mode is
    ``SCHEDULED_DATES``. A daily-rotating tape is therefore UNBOUNDED within
    one day -- a venue frame storm produces one arbitrarily large file and no
    error.

    Pinned so that a future Nautilus that gains a dual-trigger mode fails RED
    here instead of quietly changing the on-disk layout of an unbackfillable
    tape.
    """
    instrument = make_instrument()
    cache = Cache(config=CacheConfig())
    cache.add_instrument(instrument)

    writer = StreamingFeatherWriter(
        path=str(tmp_path),
        cache=cache,
        clock=TestClock(),
        include_types=[QuoteTick, BinaryOption],
        rotation_mode=RotationMode.SCHEDULED_DATES,
        rotation_interval=pd.Timedelta(days=1),
        rotation_time=datetime_time(0, 0, 0, 0),
        rotation_timezone="UTC",
        max_file_size=1,  # one byte -- would rotate on EVERY write under SIZE
    )

    for i in range(200):
        writer.write(make_quote(instrument, 1_000 + i))
    writer.close()

    # ``quote_tick`` is a per-instrument table, so the file is named for the
    # instrument id (``writer.py:137-147``), not for the type.
    written = sorted(tmp_path.rglob(f"{instrument.id}*.feather"))
    assert [p.name for p in written] == [f"{instrument.id}_0.feather"]
    assert written[0].stat().st_size > 1


def test_size_rotation_is_the_only_mode_that_honours_max_file_size(
    tmp_path: Path,
) -> None:
    """The control for the test above: under ``SIZE`` the same bound DOES fire."""
    instrument = make_instrument()
    cache = Cache(config=CacheConfig())
    cache.add_instrument(instrument)
    # The rotated filename is stamped with ``clock.timestamp_ns()``
    # (``writer.py:427``), so a FROZEN clock makes every rotation overwrite the
    # same path and rotation becomes unobservable. The clock must advance.
    clock = TestClock()

    writer = StreamingFeatherWriter(
        path=str(tmp_path),
        cache=cache,
        clock=clock,
        include_types=[QuoteTick, BinaryOption],
        rotation_mode=RotationMode.SIZE,
        max_file_size=1,
    )

    for i in range(5):
        clock.set_time(1_000_000_000 * (i + 1))
        writer.write(make_quote(instrument, 1_000 + i))
    writer.close()

    assert len(list(tmp_path.rglob(f"{instrument.id}*.feather"))) > 1
