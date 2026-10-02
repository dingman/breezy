"""RED-first equivalence + unit tests for REPLAY-BIGINST (object-free,
column-projected census spans).

`_oracle_spans` below is a FROZEN, byte-for-byte copy of the PRE-REPLAY-BIGINST
`_discover_clean_spans` per-instance body (object-based: `_select_capture_
instruments` + `best_order` + `window_extent`), used ONLY as the equivalence
oracle. It is duplicated here deliberately rather than imported, because the
production function it mirrors is being REPLACED by the column-scan path
under test in this module.

Most fixtures use `ParquetDataCatalog.write_data` directly (E-B1's own
wording) and monkeypatch `replay_sufficiency_census._convert_live_capture` to
hand back that already-built catalog -- conversion itself
(`_convert_live_capture`/`default_convert`) is UNCHANGED by this plan and is
exercised separately, end-to-end from real feather, by E-B2 only.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Self

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from nautilus_trader.model.currencies import EUR, USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption, CurrencyPair
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import urisafe_identifier

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import replay_sufficiency_census as census_module
from tape_instruments import _select_capture_instruments

from breezy.analysis.instance_span_cache import (
    SPAN_ALGO_VERSION,
    CachedInstanceSpans,
    read_instance_span_cache,
    write_instance_span_cache,
)
from breezy.analysis.replay_sufficiency import (
    InstanceSpan,
    WindowExtentFold,
    decision_window_ns,
    window_extent,
)
from breezy.domain.weather_bucket_facts import (
    WeatherFactsUnavailableError,
    read_weather_bucket_facts,
)
from breezy.persistence.catalog_column_scan import (
    CatalogColumnScanError,
    count_depth_rows,
    group_files_by_identifier,
    scan_depth_window,
    scan_quote_window,
)
from breezy.persistence.feather_preflight import PREFLIGHT_CLASSIFIER_VERSION
from breezy.strategy.depth10 import best_order

_VENUE = Venue("BREEZY_TEST")
_SEC: int = 1_000_000_000


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


class _FakeWindow:
    def __init__(self, offset: float) -> None:
        self.std_utc_offset_hours = offset


class _FakeRegistry:
    def __init__(self, offsets: dict[str, float] | None = None) -> None:
        self.offsets = offsets or {"SFO": -8.0, "LAX": -8.0}

    def climate_day_window(self, _venue: str, station: str) -> _FakeWindow:
        return _FakeWindow(self.offsets[station])


def _weather_binary_option(
    *, symbol: str, station: str, climate_day: str, ts_init: int = 0
) -> BinaryOption:
    info = {
        "weather_facts_status": "KNOWN",
        "settlement_station": station,
        "climate_date": climate_day,
        "measure": "high",
        "strike_lower_f": 70,
        "strike_upper_f": None,
    }
    sym = Symbol(symbol)
    return BinaryOption(
        instrument_id=InstrumentId(symbol=sym, venue=_VENUE),
        raw_symbol=sym,
        outcome="Yes",
        description="REPLAY-BIGINST fixture",
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
        info=info,
    )


def _non_weather_currency_pair(*, symbol: str, ts_init: int = 0) -> CurrencyPair:
    sym = Symbol(symbol)
    return CurrencyPair(
        instrument_id=InstrumentId(symbol=sym, venue=_VENUE),
        raw_symbol=sym,
        base_currency=EUR,
        quote_currency=USD,
        price_precision=5,
        size_precision=0,
        price_increment=Price.from_str("0.00001"),
        size_increment=Quantity.from_int(1),
        ts_event=ts_init,
        ts_init=ts_init,
        info=None,
    )


def _weather_currency_pair(
    *, symbol: str, station: str, climate_day: str, ts_init: int = 0
) -> CurrencyPair:
    """A non-`BinaryOption` instrument that STILL carries valid weather facts
    (E-B7): the TypeError fires on TYPE alone, never on facts availability."""
    info = {
        "weather_facts_status": "KNOWN",
        "settlement_station": station,
        "climate_date": climate_day,
        "measure": "high",
        "strike_lower_f": 70,
        "strike_upper_f": None,
    }
    sym = Symbol(symbol)
    return CurrencyPair(
        instrument_id=InstrumentId(symbol=sym, venue=_VENUE),
        raw_symbol=sym,
        base_currency=EUR,
        quote_currency=USD,
        price_precision=5,
        size_precision=0,
        price_increment=Price.from_str("0.00001"),
        size_increment=Quantity.from_int(1),
        ts_event=ts_init,
        ts_init=ts_init,
        info=info,
    )


def _pad(
    side: OrderSide, real_level: int | None, ask_price: str
) -> tuple[list[BookOrder], list[int]]:
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders: list[BookOrder] = []
    counts: list[int] = []
    for level in range(10):
        if level == real_level:
            orders.append(BookOrder(side, Price.from_str(ask_price), Quantity.from_int(5), 0))
            counts.append(1)
        else:
            orders.append(filler)
            counts.append(0)
    return orders, counts


def _depth(
    instrument_id: InstrumentId,
    *,
    ts_event: int,
    ts_init: int,
    real_ask_level: int | None = 0,
    ask_price: str = "0.51",
) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, None, "0.01")
    ask_orders, ask_counts = _pad(OrderSide.SELL, real_ask_level, ask_price)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_init,
    )


def _quote(instrument_id: InstrumentId, *, ts_event: int, ts_init: int | None = None) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str("0.49"),
        ask_price=Price.from_str("0.51"),
        bid_size=Quantity.from_int(5),
        ask_size=Quantity.from_int(5),
        ts_event=ts_event,
        ts_init=ts_init if ts_init is not None else ts_event,
    )


def _oracle_spans(
    catalog: ParquetDataCatalog, *, instance_id: str
) -> dict[tuple[str, str], InstanceSpan]:
    """Frozen copy of the pre-REPLAY-BIGINST `_discover_clean_spans` body
    (`replay_sufficiency_census.py`, before this change) -- see module
    docstring."""
    registry = census_module.default_registry()
    window_bounds: dict[tuple[str, str], tuple[int, int]] = {}
    climate_days: dict[dt.date, None] = {}
    for instrument in catalog.instruments():
        try:
            facts = read_weather_bucket_facts(instrument.info)
        except WeatherFactsUnavailableError:
            continue
        climate_days.setdefault(facts.climate_day, None)

    by_station_day: dict[tuple[str, str], list] = defaultdict(list)
    for climate_day in climate_days:
        for tape_instrument in _select_capture_instruments(catalog, climate_day=climate_day):
            key = (tape_instrument.facts.settlement_station, climate_day.isoformat())
            by_station_day[key].append(tape_instrument)

    result: dict[tuple[str, str], InstanceSpan] = {}
    for (station, day), tape_instruments in by_station_day.items():
        start_ns, end_ns = census_module._window_bounds_for(
            station, day, registry=registry, window_bounds=window_bounds
        )
        depth_ts = [
            depth.ts_event
            for ti in tape_instruments
            for depth in ti.depths
            if best_order(depth.asks) is not None
        ]
        quote_ts = [quote.ts_event for ti in tape_instruments for quote in ti.quotes]
        depth_extent = window_extent(depth_ts, start_ns=start_ns, end_ns=end_ns)
        quote_extent = window_extent(quote_ts, start_ns=start_ns, end_ns=end_ns)
        result[(station, day)] = InstanceSpan(
            instance_id=instance_id,
            verdict="CLEAN",
            depth_window_minutes=depth_extent.span_ns / 1_000_000_000 / 60,
            quote_window_minutes=quote_extent.span_ns / 1_000_000_000 / 60,
            distinct_instruments=len(tape_instruments),
            first_in_window_ns=depth_extent.first_ns,
            last_in_window_ns=depth_extent.last_ns,
        )
    return result


def _new_spans(
    monkeypatch: pytest.MonkeyPatch,
    catalog: ParquetDataCatalog,
    *,
    instance_id: str = "instance-1",
    should_stop=None,
    work_root: Path | None = None,
) -> dict[tuple[str, str], InstanceSpan]:
    """Run the NEW `_discover_clean_spans` against an already-built `catalog`,
    stubbing `_convert_live_capture` (unchanged, out of scope) to hand it back
    directly."""
    monkeypatch.setattr(census_module, "_convert_live_capture", lambda **_kwargs: catalog)
    kwargs = {}
    if should_stop is not None:
        kwargs["should_stop"] = should_stop
    spans, _clean_days, _bounds = census_module._discover_clean_spans(
        catalog_root=Path("/unused-catalog-root"),
        subdirectory="live",
        clean_ids=[instance_id],
        work_root=work_root or Path("/unused-work-root"),
        **kwargs,
    )
    flattened: dict[tuple[str, str], InstanceSpan] = {}
    for key, values in spans.items():
        assert len(values) == 1, f"expected exactly one span per key for a single instance: {key}"
        flattened[key] = values[0]
    return flattened


# ---------------------------------------------------------------------------
# WindowExtentFold (pure) -- the streaming primitive both scan functions fold
# through.
# ---------------------------------------------------------------------------


class TestWindowExtentFold:
    def test_empty_fold_matches_window_extent_of_an_empty_iterable(self) -> None:
        fold = WindowExtentFold()
        assert fold.extent() == window_extent([], start_ns=0, end_ns=100)

    def test_a_single_in_window_instant_gives_a_zero_span_like_window_extent(self) -> None:
        fold = WindowExtentFold().combine([50], start_ns=0, end_ns=100)
        assert fold.extent() == window_extent([50], start_ns=0, end_ns=100)

    def test_folding_in_chunks_matches_one_shot_window_extent(self) -> None:
        values = [50, 10, 90, 30, 70, 5, 95]
        one_shot = window_extent(values, start_ns=0, end_ns=100)
        folded = WindowExtentFold()
        for chunk in ([50, 10], [90], [30, 70, 5], [95]):
            folded = folded.combine(chunk, start_ns=0, end_ns=100)
        assert folded.extent() == one_shot

    def test_out_of_window_instants_never_affect_the_fold(self) -> None:
        folded = WindowExtentFold().combine([-5, 150, 50], start_ns=0, end_ns=100)
        assert folded.extent() == window_extent([50], start_ns=0, end_ns=100)

    def test_combine_never_mutates_the_original_fold(self) -> None:
        original = WindowExtentFold()
        combined = original.combine([50], start_ns=0, end_ns=100)
        assert original.extent() == WindowExtentFold().extent()
        assert combined.extent() != original.extent()


# ---------------------------------------------------------------------------
# catalog_column_scan unit tests: schema, nulls, grouping, should_stop
# ---------------------------------------------------------------------------


def _build_depth_catalog(tmp_path: Path, rows: list[OrderBookDepth10]) -> ParquetDataCatalog:
    catalog = ParquetDataCatalog(tmp_path)
    catalog.write_data(rows)
    return catalog


def _depth_files_for(catalog: ParquetDataCatalog, instrument_id: InstrumentId) -> list[str]:
    grouped = group_files_by_identifier(catalog, OrderBookDepth10)
    return grouped.get(urisafe_identifier(instrument_id), [])


def _quote_files_for(catalog: ParquetDataCatalog, instrument_id: InstrumentId) -> list[str]:
    grouped = group_files_by_identifier(catalog, QuoteTick)
    return grouped.get(urisafe_identifier(instrument_id), [])


class TestCountDepthRows:
    def test_e_b9_zero_files_counts_zero(self) -> None:
        assert count_depth_rows([]) == 0

    def test_counts_every_row_all_time_no_window_no_ask_mask(self, tmp_path: Path) -> None:
        iid = InstrumentId(symbol=Symbol("A"), venue=_VENUE)
        rows = [
            _depth(iid, ts_event=0, ts_init=0, real_ask_level=None),  # pad-only still counts
            _depth(iid, ts_event=1, ts_init=1, real_ask_level=0),
        ]
        catalog = _build_depth_catalog(tmp_path, rows)
        files = _depth_files_for(catalog, iid)
        assert count_depth_rows(files) == 2


class TestGroupFilesByIdentifier_EB11:
    def test_e_b11_groups_by_urisafe_identifier_not_the_raw_id(self, tmp_path: Path) -> None:
        plain = InstrumentId(symbol=Symbol("PLAIN-A"), venue=_VENUE)
        slashed = InstrumentId(symbol=Symbol("TC-TEMP-SFO/HIGH-2026-09-01-70"), venue=_VENUE)
        assert "/" in slashed.value

        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data(
            [
                _depth(plain, ts_event=0, ts_init=0),
                _depth(slashed, ts_event=0, ts_init=0),
            ]
        )

        grouped = group_files_by_identifier(catalog, OrderBookDepth10)

        assert grouped[urisafe_identifier(plain)] != grouped[urisafe_identifier(slashed)]
        assert count_depth_rows(grouped[urisafe_identifier(slashed)]) == 1
        # The raw (un-stripped) id is NEVER a key -- grouping by the raw id
        # would silently miss this instrument (R3-1).
        assert slashed.value not in grouped

    def test_two_instruments_files_co_located_under_one_type_directory_stay_separated(
        self, tmp_path: Path
    ) -> None:
        a = InstrumentId(symbol=Symbol("CO-A"), venue=_VENUE)
        b = InstrumentId(symbol=Symbol("CO-B"), venue=_VENUE)
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data(
            [
                _depth(a, ts_event=0, ts_init=0),
                _depth(a, ts_event=1, ts_init=1),
                _depth(b, ts_event=0, ts_init=0),
            ]
        )

        grouped = group_files_by_identifier(catalog, OrderBookDepth10)

        assert count_depth_rows(grouped[urisafe_identifier(a)]) == 2
        assert count_depth_rows(grouped[urisafe_identifier(b)]) == 1


class TestScanDepthWindowSchemaErrors:
    """E-B3, E-B3b, E-B3c, E-B10: the schema/null asserts."""

    def _write_one_row(self, tmp_path: Path) -> tuple[ParquetDataCatalog, InstrumentId]:
        iid = InstrumentId(symbol=Symbol("SCHEMA-A"), venue=_VENUE)
        catalog = _build_depth_catalog(
            tmp_path, [_depth(iid, ts_event=10, ts_init=10, real_ask_level=0)]
        )
        return catalog, iid

    def _rewrite_column(self, file_path: str, name: str, new_array: pa.Array) -> None:
        table = pq.read_table(file_path)
        index = table.schema.get_field_index(name)
        table = table.set_column(index, name, new_array)
        pq.write_table(table, file_path)

    def test_e_b3_a_missing_ask_size_column_raises(self, tmp_path: Path) -> None:
        catalog, iid = self._write_one_row(tmp_path)
        files = _depth_files_for(catalog, iid)
        table = pq.read_table(files[0])
        table = table.drop(["ask_size_3"])
        pq.write_table(table, files[0])

        with pytest.raises(CatalogColumnScanError, match="ask_size_3"):
            scan_depth_window(files, start_ns=0, end_ns=1_000, should_stop=lambda: None)

    def test_e_b3b_a_wrong_type_column_raises(self, tmp_path: Path) -> None:
        catalog, iid = self._write_one_row(tmp_path)
        files = _depth_files_for(catalog, iid)
        replacement = pa.array([7], type=pa.int64())
        self._rewrite_column(files[0], "ask_size_3", replacement)
        with pytest.raises(CatalogColumnScanError, match="ask_size_3"):
            scan_depth_window(files, start_ns=0, end_ns=1_000, should_stop=lambda: None)

    def test_e_b3c_a_mismatched_width_raises_and_names_the_width(self, tmp_path: Path) -> None:
        catalog, iid = self._write_one_row(tmp_path)
        files = _depth_files_for(catalog, iid)
        table = pq.read_table(files[0])
        for name in [f"ask_size_{i}" for i in range(10)]:
            index = table.schema.get_field_index(name)
            original = table.column(name)
            truncated = pa.array(
                [v.as_py()[:8] for v in original.combine_chunks()], type=pa.binary(8)
            )
            table = table.set_column(index, name, truncated)
        pq.write_table(table, files[0])

        with pytest.raises(CatalogColumnScanError, match="width"):
            scan_depth_window(files, start_ns=0, end_ns=1_000, should_stop=lambda: None)

    def test_e_b10_a_null_ask_size_raises(self, tmp_path: Path) -> None:
        catalog, iid = self._write_one_row(tmp_path)
        files = _depth_files_for(catalog, iid)
        table = pq.read_table(files[0])
        index = table.schema.get_field_index("ask_size_3")
        width = table.schema.field("ask_size_3").type.byte_width
        null_column = pa.array([None], type=pa.binary(width))
        table = table.set_column(index, "ask_size_3", null_column)
        pq.write_table(table, files[0])

        with pytest.raises(CatalogColumnScanError, match="null"):
            scan_depth_window(files, start_ns=0, end_ns=1_000, should_stop=lambda: None)


class TestScanDepthWindowAskMaskAndRowCount:
    def test_only_ask_positive_in_window_rows_count_pad_only_and_out_of_window_excluded(
        self, tmp_path: Path
    ) -> None:
        iid = InstrumentId(symbol=Symbol("MASK-A"), venue=_VENUE)
        rows = [
            _depth(iid, ts_event=1, ts_init=1, real_ask_level=0),  # real, OUTSIDE window (before)
            _depth(iid, ts_event=10, ts_init=2, real_ask_level=0),  # real, at window start
            _depth(iid, ts_event=50, ts_init=3, real_ask_level=None),  # pad-only, INSIDE window
            _depth(iid, ts_event=20, ts_init=4, real_ask_level=2),  # real at level 2 only
            _depth(iid, ts_event=100, ts_init=5, real_ask_level=0),  # real, at window end (excl)
        ]
        catalog = _build_depth_catalog(tmp_path, rows)
        files = _depth_files_for(catalog, iid)

        row_count, lo, hi = scan_depth_window(
            files, start_ns=10, end_ns=100, should_stop=lambda: None
        )

        # Only ts=10 and ts=20 are BOTH in-window AND ask-positive: ts=1 is
        # window-excluded regardless of its ask; ts=50 is window-INCLUDED but
        # pad-only (ask mask must exclude it, not the window filter); ts=100
        # is exactly the (excluded) end.
        assert row_count == 2
        assert (lo, hi) == (10, 20)

    def test_e_sig_should_stop_raising_mid_scan_propagates_and_never_returns(
        self, tmp_path: Path
    ) -> None:
        iid = InstrumentId(symbol=Symbol("STOP-A"), venue=_VENUE)
        rows = [
            _depth(iid, ts_event=i, ts_init=i, real_ask_level=0) for i in range(5)
        ]
        catalog = _build_depth_catalog(tmp_path, rows)
        files = _depth_files_for(catalog, iid)

        calls = {"n": 0}

        def should_stop() -> None:
            calls["n"] += 1
            if calls["n"] >= 2:
                raise SystemExit(143)

        with pytest.raises(SystemExit) as excinfo:
            scan_depth_window(
                files, start_ns=0, end_ns=1_000, should_stop=should_stop, batch_size=1
            )
        assert excinfo.value.code == 143
        assert calls["n"] >= 2


class TestScanQuoteWindow:
    def test_counts_only_in_window_quotes(self, tmp_path: Path) -> None:
        iid = InstrumentId(symbol=Symbol("QUOTE-A"), venue=_VENUE)
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data(
            [
                _quote(iid, ts_event=5),
                _quote(iid, ts_event=10),
                _quote(iid, ts_event=99),
            ]
        )
        files = _quote_files_for(catalog, iid)

        row_count, lo, hi = scan_quote_window(
            files, start_ns=10, end_ns=99, should_stop=lambda: None
        )

        assert row_count == 1
        assert (lo, hi) == (10, 10)


# ---------------------------------------------------------------------------
# E-B1: multi-day/multi-station equivalence against the frozen oracle.
# ---------------------------------------------------------------------------


@pytest.fixture
def _fake_registry(monkeypatch: pytest.MonkeyPatch) -> _FakeRegistry:
    registry = _FakeRegistry()
    monkeypatch.setattr(census_module, "default_registry", lambda: registry)
    return registry


class TestEB1MultiDayMultiStationEquivalence:
    def _sfo_day1_window(self) -> tuple[int, int]:
        return decision_window_ns(climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0)

    def _lax_day1_window(self) -> tuple[int, int]:
        return decision_window_ns(climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0)

    def _sfo_day2_window(self) -> tuple[int, int]:
        return decision_window_ns(climate_day=dt.date(2026, 9, 2), std_utc_offset_hours=-8.0)

    def _build_catalog(self, tmp_path: Path) -> ParquetDataCatalog:
        w_start, w_end = self._sfo_day1_window()
        lax_start, _lax_end = self._lax_day1_window()
        day2_start, _day2_end = self._sfo_day2_window()

        instruments: list[BinaryOption] = [
            _weather_binary_option(symbol="SFO-A", station="SFO", climate_day="2026-09-01"),
            _weather_binary_option(symbol="SFO-B", station="SFO", climate_day="2026-09-01"),
            _weather_binary_option(symbol="SFO-C", station="SFO", climate_day="2026-09-01"),
            _weather_binary_option(symbol="SFO-D", station="SFO", climate_day="2026-09-01"),
            _weather_binary_option(symbol="SFO-E", station="SFO", climate_day="2026-09-01"),
            _weather_binary_option(symbol="LAX-A", station="LAX", climate_day="2026-09-01"),
            _weather_binary_option(symbol="SFO2-A", station="SFO", climate_day="2026-09-02"),
        ]

        def iid(symbol: str) -> InstrumentId:
            return InstrumentId(symbol=Symbol(symbol), venue=_VENUE)

        depth_rows: list[OrderBookDepth10] = [
            # sfo-a: pad-only (in-window, excluded), start-inclusive, level-2
            # real ask, ts_event-inside/ts_init-outside, end-exclusive.
            _depth(iid("SFO-A"), ts_event=w_start + 100 * _SEC, ts_init=100, real_ask_level=None),
            _depth(iid("SFO-A"), ts_event=w_start, ts_init=200, real_ask_level=0),
            _depth(iid("SFO-A"), ts_event=w_start + 1_000 * _SEC, ts_init=300, real_ask_level=2),
            _depth(
                iid("SFO-A"),
                ts_event=w_start + 2_000 * _SEC,
                ts_init=w_end + 100_000 * _SEC,
                real_ask_level=0,
            ),
            _depth(
                iid("SFO-A"),
                ts_event=w_end,
                ts_init=w_end + 200_000 * _SEC,
                real_ask_level=0,
            ),
            # sfo-b: duplicate ts_event (span 0), 2 rows.
            _depth(iid("SFO-B"), ts_event=w_start + 5_000 * _SEC, ts_init=10, real_ask_level=0),
            _depth(iid("SFO-B"), ts_event=w_start + 5_000 * _SEC, ts_init=20, real_ask_level=0),
            # sfo-c: D-5 non-monotonic ts_event, min/max neither first nor last.
            _depth(iid("SFO-C"), ts_event=w_start + 9_000 * _SEC, ts_init=10, real_ask_level=0),
            _depth(iid("SFO-C"), ts_event=w_start + 1_000 * _SEC, ts_init=20, real_ask_level=0),
            _depth(iid("SFO-C"), ts_event=w_start + 17_000 * _SEC, ts_init=30, real_ask_level=0),
            _depth(iid("SFO-C"), ts_event=w_start + 3_000 * _SEC, ts_init=40, real_ask_level=0),
            _depth(iid("SFO-C"), ts_event=w_start + 15_000 * _SEC, ts_init=50, real_ask_level=0),
            # sfo-e: book-backed (all-time count > 0), but every depth row is
            # OUTSIDE the window (E-B8).
            _depth(iid("SFO-E"), ts_event=w_start - 5_000 * _SEC, ts_init=10, real_ask_level=0),
            # lax-a: simple, in-window.
            _depth(iid("LAX-A"), ts_event=lax_start + 50 * _SEC, ts_init=10, real_ask_level=0),
            # sfo2-a: a SEPARATE climate day; must never leak into day 1.
            _depth(iid("SFO2-A"), ts_event=day2_start + 50 * _SEC, ts_init=10, real_ask_level=0),
        ]
        # sfo-d is intentionally NOT in depth_rows: zero depth files (E-B9).

        quote_rows: list[QuoteTick] = [
            _quote(iid("SFO-A"), ts_event=w_start + 500 * _SEC, ts_init=10),
            _quote(iid("SFO-A"), ts_event=w_start + 1_500 * _SEC, ts_init=20),
            _quote(iid("SFO-B"), ts_event=w_start + 5_000 * _SEC, ts_init=10),
            # sfo-d: quote-only, NOT book-backed -- its quotes must NOT count.
            # An extreme (very early) value that WOULD shift the aggregate
            # minimum if wrongly folded in.
            _quote(iid("SFO-D"), ts_event=w_start, ts_init=10),
            # sfo-e: book-backed via all-time depth count alone; its
            # in-window quotes DO count (E-B8) -- a value between start and
            # sfo-d's, so a correct run's minimum is THIS value, not sfo-d's.
            _quote(iid("SFO-E"), ts_event=w_start + 1 * _SEC, ts_init=10),
            _quote(iid("LAX-A"), ts_event=lax_start + 50 * _SEC, ts_init=10),
            _quote(iid("SFO2-A"), ts_event=day2_start + 50 * _SEC, ts_init=10),
        ]

        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([*instruments])
        catalog.write_data(depth_rows)
        catalog.write_data(quote_rows)
        return catalog

    def test_oracle_and_new_path_agree_on_every_station_day(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        catalog = self._build_catalog(tmp_path)

        oracle = _oracle_spans(catalog, instance_id="instance-1")
        new = _new_spans(monkeypatch, catalog, instance_id="instance-1")

        assert set(oracle) == {("SFO", "2026-09-01"), ("LAX", "2026-09-01"), ("SFO", "2026-09-02")}
        assert oracle == new

    def test_sfo_day1_excludes_the_end_instant_and_includes_the_start_instant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        catalog = self._build_catalog(tmp_path)
        w_start, _w_end = self._sfo_day1_window()

        new = _new_spans(monkeypatch, catalog, instance_id="instance-1")
        span = new[("SFO", "2026-09-01")]

        # sfo-a alone would give [w_start, w_start+2000s]; sfo-b/-c extend the
        # upper bound further (sfo-c's max is w_start+17000s).
        assert span.first_in_window_ns == w_start
        assert span.last_in_window_ns == w_start + 17_000 * _SEC
        # book-backed: sfo-a, sfo-b, sfo-c, sfo-e (NOT sfo-d, zero depth files).
        assert span.distinct_instruments == 4

    def test_sfo_day1_quote_minimum_comes_from_the_book_backed_all_outside_window_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        catalog = self._build_catalog(tmp_path)
        w_start, _w_end = self._sfo_day1_window()

        new = _new_spans(monkeypatch, catalog, instance_id="instance-1")
        span = new[("SFO", "2026-09-01")]

        quote_span_ns = round(span.quote_window_minutes * 60 * 1_000_000_000)
        # sfo-e's quote at w_start+1s is the true minimum; sfo-d's earlier
        # quote at w_start must NOT have counted (E-B9).
        assert quote_span_ns == (w_start + 5_000 * _SEC) - (w_start + 1 * _SEC)


# ---------------------------------------------------------------------------
# E-B4: WeatherFactsUnavailableError -- same helper, same exception, both paths.
# ---------------------------------------------------------------------------


class TestEB4NoWeatherFacts:
    def test_an_instrument_with_no_weather_facts_raises_the_same_exception_on_both_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        good = _weather_binary_option(symbol="OK-A", station="SFO", climate_day="2026-09-01")
        # A BinaryOption whose `info` claims KNOWN status but omits a
        # required key -- passes the outer climate_days pre-filter's
        # try/except (it is skipped there), but `_capture_instruments_by_id`
        # calls `read_weather_bucket_facts` unguarded for every instrument in
        # the catalog once ANY climate day is processed.
        bad_symbol = Symbol("BAD-A")
        bad = BinaryOption(
            instrument_id=InstrumentId(symbol=bad_symbol, venue=_VENUE),
            raw_symbol=bad_symbol,
            outcome="Yes",
            description="bad facts",
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
            ts_event=0,
            ts_init=0,
            info={"weather_facts_status": "KNOWN"},  # missing required keys
        )
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([good, bad])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        catalog.write_data(
            [
                _depth(
                    InstrumentId(symbol=Symbol("OK-A"), venue=_VENUE),
                    ts_event=w_start,
                    ts_init=0,
                )
            ]
        )

        with pytest.raises(WeatherFactsUnavailableError):
            _oracle_spans(catalog, instance_id="instance-1")

        with pytest.raises(WeatherFactsUnavailableError):
            _new_spans(monkeypatch, catalog, instance_id="instance-1")


# ---------------------------------------------------------------------------
# E-B7 / E-B7b: TypeError re-homed after the book-backed filter.
# ---------------------------------------------------------------------------


class TestEB7TypeErrorAfterBookBackedFilter:
    def test_a_book_backed_non_binary_option_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        bad = _weather_currency_pair(symbol="ZZZ-BAD", station="SFO", climate_day="2026-09-01")
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([bad])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        bad_iid = InstrumentId(symbol=Symbol("ZZZ-BAD"), venue=_VENUE)
        catalog.write_data([_depth(bad_iid, ts_event=w_start, ts_init=0)])

        with pytest.raises(TypeError, match="ZZZ-BAD"):
            _new_spans(monkeypatch, catalog, instance_id="instance-1")

    def test_a_non_binary_option_with_zero_depth_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        harmless = _weather_currency_pair(
            symbol="HARMLESS-A", station="SFO", climate_day="2026-09-01"
        )
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([harmless])
        # No depth rows written for HARMLESS-A at all: zero files, not
        # book-backed, TypeError check never applies to it.

        new = _new_spans(monkeypatch, catalog, instance_id="instance-1")
        assert new == {}

    def test_e_b7b_typeerror_discards_any_partial_result_for_the_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        """`good-a` sorts before `zzz-bad` -- the book-backed loop processes
        it FIRST, partially populating an in-memory accumulator -- but the
        raise still means `_discover_clean_spans` returns NOTHING, ever, for
        this instance (E-B7b / R3-2)."""
        good = _weather_binary_option(symbol="good-a", station="SFO", climate_day="2026-09-01")
        bad = _weather_currency_pair(symbol="zzz-bad", station="SFO", climate_day="2026-09-01")
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([good, bad])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        catalog.write_data(
            [
                _depth(
                    InstrumentId(symbol=Symbol("good-a"), venue=_VENUE),
                    ts_event=w_start,
                    ts_init=0,
                ),
                _depth(
                    InstrumentId(symbol=Symbol("zzz-bad"), venue=_VENUE),
                    ts_event=w_start,
                    ts_init=1,
                ),
            ]
        )

        monkeypatch.setattr(census_module, "_convert_live_capture", lambda **_kwargs: catalog)
        with pytest.raises(TypeError):
            census_module._discover_clean_spans(
                catalog_root=Path("/unused"),
                subdirectory="live",
                clean_ids=["instance-1"],
                work_root=Path("/unused-work"),
            )
        # No return value exists to inspect -- the raise IS the proof: a
        # caller (run_census) can never observe a partial InstanceSpan, cache
        # entry, or checkpoint line for this instance.


# ---------------------------------------------------------------------------
# E-SIG (integration level): should_stop raising leaves no return value.
# ---------------------------------------------------------------------------


class TestESigIntegration:
    def test_should_stop_raising_propagates_out_of_discover_clean_spans(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        instrument = _weather_binary_option(
            symbol="STOP-INT-A", station="SFO", climate_day="2026-09-01"
        )
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([instrument])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        catalog.write_data(
            [
                _depth(
                    InstrumentId(symbol=Symbol("STOP-INT-A"), venue=_VENUE),
                    ts_event=w_start,
                    ts_init=0,
                )
            ]
        )

        def should_stop() -> None:
            raise SystemExit(143)

        monkeypatch.setattr(census_module, "_convert_live_capture", lambda **_kwargs: catalog)
        with pytest.raises(SystemExit) as excinfo:
            census_module._discover_clean_spans(
                catalog_root=Path("/unused"),
                subdirectory="live",
                clean_ids=["instance-1"],
                work_root=Path("/unused-work"),
                should_stop=should_stop,
            )
        assert excinfo.value.code == 143


# ---------------------------------------------------------------------------
# E-B6: a cache entry written by the oracle equals a recompute by the new path.
# ---------------------------------------------------------------------------


class TestEB5PlainIntsAndByteIdenticalJsonl:
    def test_first_and_last_in_window_ns_are_plain_ints_and_cache_json_bytes_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        from breezy.analysis.instance_span_cache import _payload_for_entry

        instrument = _weather_binary_option(
            symbol="JSON-A", station="SFO", climate_day="2026-09-01"
        )
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([instrument])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        json_iid = InstrumentId(symbol=Symbol("JSON-A"), venue=_VENUE)
        catalog.write_data([_depth(json_iid, ts_event=w_start, ts_init=0)])

        oracle = _oracle_spans(catalog, instance_id="instance-1")
        new = _new_spans(monkeypatch, catalog, instance_id="instance-1")

        span = new[("SFO", "2026-09-01")]
        assert type(span.first_in_window_ns) is int
        assert type(span.last_in_window_ns) is int

        key = ("instance-1", "fp", SPAN_ALGO_VERSION, PREFLIGHT_CLASSIFIER_VERSION)
        oracle_entry = CachedInstanceSpans(
            spans=dict(oracle), station_offsets={"SFO": -8.0}, last_full_scan="2026-09-27"
        )
        new_entry = CachedInstanceSpans(
            spans=dict(new), station_offsets={"SFO": -8.0}, last_full_scan="2026-09-27"
        )
        oracle_json = json.dumps(_payload_for_entry(key, oracle_entry), sort_keys=True)
        new_json = json.dumps(_payload_for_entry(key, new_entry), sort_keys=True)
        assert oracle_json == new_json


class TestEB6CacheRoundTrip:
    def test_a_cache_entry_written_from_oracle_spans_equals_a_new_path_recompute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        instrument = _weather_binary_option(
            symbol="CACHE-A", station="SFO", climate_day="2026-09-01"
        )
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([instrument])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        catalog.write_data(
            [
                _depth(
                    InstrumentId(symbol=Symbol("CACHE-A"), venue=_VENUE),
                    ts_event=w_start,
                    ts_init=0,
                )
            ]
        )
        catalog.write_data(
            [_quote(InstrumentId(symbol=Symbol("CACHE-A"), venue=_VENUE), ts_event=w_start)]
        )

        oracle = _oracle_spans(catalog, instance_id="instance-1")
        entry = CachedInstanceSpans(
            spans=dict(oracle), station_offsets={"SFO": -8.0}, last_full_scan="2026-09-27"
        )
        cache_path = tmp_path / "instance_spans.v2.jsonl"
        key = ("instance-1", "deadbeef", SPAN_ALGO_VERSION, PREFLIGHT_CLASSIFIER_VERSION)
        write_instance_span_cache(cache_path, {key: entry})
        read_back = read_instance_span_cache(cache_path)[key].spans

        new = _new_spans(monkeypatch, catalog, instance_id="instance-1")

        assert read_back == new


# ---------------------------------------------------------------------------
# E-B2: end-to-end from real live feather, via the REAL `_convert_live_capture`.
# ---------------------------------------------------------------------------


class TestEB2EndToEndFromLiveFeather:
    def test_a_real_feather_capture_converts_and_matches_the_oracle(
        self, tmp_path: Path, _fake_registry: _FakeRegistry
    ) -> None:
        from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        iid = InstrumentId(symbol=Symbol("FEATHER-A"), venue=_VENUE)
        instrument = _weather_binary_option(
            symbol="FEATHER-A", station="SFO", climate_day="2026-09-01"
        )
        depth_rows = [
            _depth(iid, ts_event=w_start, ts_init=0, real_ask_level=0),
            _depth(iid, ts_event=w_start + 100 * _SEC, ts_init=1, real_ask_level=0),
        ]
        quote_rows = [_quote(iid, ts_event=w_start + 50 * _SEC, ts_init=0)]

        capture_root = tmp_path / "capture"
        instance_dir = capture_root / "live" / "instance-feather-1"
        instance_dir.mkdir(parents=True)

        def _write_stream(path: Path, objects: list, data_cls: type) -> None:
            batch = ArrowSerializer.serialize_batch(objects, data_cls=data_cls)
            table = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
            with path.open("wb") as handle:
                writer = pa.ipc.new_stream(handle, table.schema)
                writer.write_table(table)
                writer.close()

        _write_stream(instance_dir / "binary_option_0.feather", [instrument], BinaryOption)
        _write_stream(instance_dir / "order_book_depths_0.feather", depth_rows, OrderBookDepth10)
        _write_stream(instance_dir / "quote_tick_0.feather", quote_rows, QuoteTick)

        work_root = tmp_path / "work"
        oracle_catalog = census_module._convert_live_capture(
            quote_catalog=capture_root,
            instance_id="instance-feather-1",
            subdirectory="live",
            work_catalog=work_root / "oracle",
        )
        oracle = _oracle_spans(oracle_catalog, instance_id="instance-feather-1")

        new_spans, _clean_days, _bounds = census_module._discover_clean_spans(
            catalog_root=capture_root,
            subdirectory="live",
            clean_ids=["instance-feather-1"],
            work_root=work_root / "new",
        )
        new_flat = {key: values[0] for key, values in new_spans.items()}

        assert oracle == new_flat
        assert oracle[("SFO", "2026-09-01")].distinct_instruments == 1


# ---------------------------------------------------------------------------
# REPLAY-BIGINST review finding 1 (HIGH): parquet handles must close
# deterministically, including when `should_stop` raises mid-scan.
# ---------------------------------------------------------------------------


def _spying_parquet_file_class(real_parquet_file: type) -> type:
    """A `pq.ParquetFile` stand-in that counts opens/closes, delegating
    everything else to the real class -- used to prove a raising scan still
    closes every file it opened (finding 1)."""

    class _SpyParquetFile:
        open_count = 0
        close_count = 0

        def __init__(self, path: str, *args: object, **kwargs: object) -> None:
            type(self).open_count += 1
            self._inner = real_parquet_file(path, *args, **kwargs)

        def close(self) -> None:
            type(self).close_count += 1
            self._inner.close()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            self.close()
            return False

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    return _SpyParquetFile


class TestFinding1ParquetHandlesCloseDeterministically:
    def test_scan_depth_window_closes_the_file_even_when_should_stop_raises_mid_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        iid = InstrumentId(symbol=Symbol("CLOSE-DEPTH-A"), venue=_VENUE)
        rows = [_depth(iid, ts_event=i, ts_init=i, real_ask_level=0) for i in range(5)]
        catalog = _build_depth_catalog(tmp_path, rows)
        files = _depth_files_for(catalog, iid)

        spy_cls = _spying_parquet_file_class(pq.ParquetFile)
        monkeypatch.setattr(pq, "ParquetFile", spy_cls)

        def should_stop() -> None:
            raise SystemExit(143)

        with pytest.raises(SystemExit):
            scan_depth_window(
                files, start_ns=0, end_ns=1_000, should_stop=should_stop, batch_size=1
            )

        assert spy_cls.open_count >= 1
        assert spy_cls.close_count == spy_cls.open_count

    def test_scan_quote_window_closes_the_file_even_when_should_stop_raises_mid_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        iid = InstrumentId(symbol=Symbol("CLOSE-QUOTE-A"), venue=_VENUE)
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([_quote(iid, ts_event=i) for i in range(5)])
        files = _quote_files_for(catalog, iid)

        spy_cls = _spying_parquet_file_class(pq.ParquetFile)
        monkeypatch.setattr(pq, "ParquetFile", spy_cls)

        def should_stop() -> None:
            raise SystemExit(143)

        with pytest.raises(SystemExit):
            scan_quote_window(
                files, start_ns=0, end_ns=1_000, should_stop=should_stop, batch_size=1
            )

        assert spy_cls.open_count >= 1
        assert spy_cls.close_count == spy_cls.open_count

    def test_count_depth_rows_closes_every_file_it_opens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        iid = InstrumentId(symbol=Symbol("CLOSE-COUNT-A"), venue=_VENUE)
        rows = [_depth(iid, ts_event=0, ts_init=0), _depth(iid, ts_event=1, ts_init=1)]
        catalog = _build_depth_catalog(tmp_path, rows)
        files = _depth_files_for(catalog, iid)

        spy_cls = _spying_parquet_file_class(pq.ParquetFile)
        monkeypatch.setattr(pq, "ParquetFile", spy_cls)

        assert count_depth_rows(files) == 2
        assert spy_cls.open_count >= 1
        assert spy_cls.close_count == spy_cls.open_count


# ---------------------------------------------------------------------------
# REPLAY-BIGINST review finding 3 (MEDIUM, R3-3): the BinaryOption type check
# runs over ALL book-backed ids, sorted, BEFORE any scan touches a file.
# ---------------------------------------------------------------------------


class TestFinding3TypeCheckRunsBeforeAnyScan:
    def test_a_corrupt_depth_file_on_an_earlier_id_never_masks_a_later_type_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        """`aaa-corrupt` sorts before `zzz-bad-type`: if the type check ran
        interleaved with the scan (the pre-fix order), `aaa-corrupt`'s scan
        would run FIRST and raise `CatalogColumnScanError` from its corrupt
        depth file, and `zzz-bad-type`'s `TypeError` would never surface. R3-3
        requires every book-backed id's type to be checked, in sorted order,
        before any scan starts."""
        good = _weather_binary_option(
            symbol="aaa-corrupt", station="SFO", climate_day="2026-09-01"
        )
        bad = _weather_currency_pair(
            symbol="zzz-bad-type", station="SFO", climate_day="2026-09-01"
        )
        catalog = ParquetDataCatalog(tmp_path)
        catalog.write_data([good, bad])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        good_iid = InstrumentId(symbol=Symbol("aaa-corrupt"), venue=_VENUE)
        bad_iid = InstrumentId(symbol=Symbol("zzz-bad-type"), venue=_VENUE)
        catalog.write_data([_depth(good_iid, ts_event=w_start, ts_init=0)])
        catalog.write_data([_depth(bad_iid, ts_event=w_start, ts_init=1)])

        good_files = _depth_files_for(catalog, good_iid)
        table = pq.read_table(good_files[0])
        table = table.drop(["ask_size_3"])
        pq.write_table(table, good_files[0])

        with pytest.raises(TypeError, match="zzz-bad-type"):
            _new_spans(monkeypatch, catalog, instance_id="instance-1")


# ---------------------------------------------------------------------------
# REPLAY-BIGINST review finding 2 (MEDIUM): a stop or a TypeError writes
# NOTHING -- checked at the `run_census` level (cache file + checkpoint).
# ---------------------------------------------------------------------------


def _stub_run_census_collaborators(
    monkeypatch: pytest.MonkeyPatch, *, instance_id: str, catalog: ParquetDataCatalog
) -> None:
    monkeypatch.setattr(
        census_module, "list_instance_ids", lambda _root, _subdir: (instance_id,)
    )
    monkeypatch.setattr(
        census_module, "scan_instance", lambda _root, iid, _subdir: iid
    )
    monkeypatch.setattr(
        census_module, "classify_instance", lambda _report, *, now_ns: "CLEAN"
    )
    monkeypatch.setattr(census_module, "_convert_live_capture", lambda **_kwargs: catalog)
    monkeypatch.setattr(
        census_module,
        "_corrupt_instance_station_days",
        lambda quote_catalog, subdirectory, corrupt_ids: set(),
    )
    monkeypatch.setattr(
        census_module,
        "_live_instance_registrations",
        lambda quote_catalog, subdirectory, live_ids: {},
    )
    monkeypatch.setattr(census_module, "_read_station_candidates", lambda path: ())


class TestESigIntegrationRunCensus:
    """E-SIG-int: `should_stop` flips mid-scan, after batch 1, with a
    `batch_size` smaller than the row count (R3-4) -- `run_census` must leave
    NOTHING in the cache file/checkpoint for this instance."""

    def test_should_stop_raising_leaves_no_cache_entry_or_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        instance_id = "sig-int-a"
        instance_dir = tmp_path / "live" / instance_id
        instance_dir.mkdir(parents=True)
        (instance_dir / "binary_option_0.feather").write_bytes(b"sig-int-fixture")

        instrument = _weather_binary_option(
            symbol="SIG-INT-A", station="SFO", climate_day="2026-09-01"
        )
        catalog = ParquetDataCatalog(tmp_path / "catalog")
        catalog.write_data([instrument])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        iid = InstrumentId(symbol=Symbol("SIG-INT-A"), venue=_VENUE)
        # 5 rows against batch_size=2 (below): 3 batches, so `should_stop` is
        # called more than once -- the flag flips AFTER batch 1, mid-scan,
        # never at the natural end of the file (R3-4).
        catalog.write_data(
            [_depth(iid, ts_event=w_start + i * _SEC, ts_init=i) for i in range(5)]
        )

        _stub_run_census_collaborators(monkeypatch, instance_id=instance_id, catalog=catalog)
        monkeypatch.setattr(
            census_module,
            "scan_depth_window",
            functools.partial(scan_depth_window, batch_size=2),
        )

        calls = {"n": 0}

        def _flip_after_batch_one() -> None:
            calls["n"] += 1
            if calls["n"] >= 2:
                raise SystemExit(143)

        monkeypatch.setitem(
            census_module._discover_clean_spans.__kwdefaults__,
            "should_stop",
            _flip_after_batch_one,
        )

        cache_path = tmp_path / "instance_spans.v2.jsonl"
        with pytest.raises(SystemExit) as excinfo:
            census_module.run_census(
                catalog_root=tmp_path,
                subdirectory="live",
                work_root=tmp_path / "work",
                station_candidates_path=tmp_path / "station_candidates.jsonl",
                computed_day="2026-09-27",
                now_ns=1,
                instance_spans_cache_path=cache_path,
            )

        assert excinfo.value.code == 143
        assert calls["n"] >= 2
        assert read_instance_span_cache(cache_path) == {}


class TestEB7bIntegrationRunCensus:
    """E-B7b-int: a book-backed id that is not a `BinaryOption` -- `run_census`
    must leave NOTHING in the cache file/checkpoint for this instance."""

    def test_typeerror_leaves_no_cache_entry_or_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _fake_registry: _FakeRegistry
    ) -> None:
        instance_id = "b7b-int-a"
        instance_dir = tmp_path / "live" / instance_id
        instance_dir.mkdir(parents=True)
        (instance_dir / "binary_option_0.feather").write_bytes(b"b7b-int-fixture")

        good = _weather_binary_option(
            symbol="good-b7b", station="SFO", climate_day="2026-09-01"
        )
        bad = _weather_currency_pair(
            symbol="zzz-bad-b7b", station="SFO", climate_day="2026-09-01"
        )
        catalog = ParquetDataCatalog(tmp_path / "catalog")
        catalog.write_data([good, bad])
        w_start, _w_end = decision_window_ns(
            climate_day=dt.date(2026, 9, 1), std_utc_offset_hours=-8.0
        )
        catalog.write_data(
            [
                _depth(
                    InstrumentId(symbol=Symbol("good-b7b"), venue=_VENUE),
                    ts_event=w_start,
                    ts_init=0,
                ),
                _depth(
                    InstrumentId(symbol=Symbol("zzz-bad-b7b"), venue=_VENUE),
                    ts_event=w_start,
                    ts_init=1,
                ),
            ]
        )

        _stub_run_census_collaborators(monkeypatch, instance_id=instance_id, catalog=catalog)

        cache_path = tmp_path / "instance_spans.v2.jsonl"
        with pytest.raises(TypeError, match="zzz-bad-b7b"):
            census_module.run_census(
                catalog_root=tmp_path,
                subdirectory="live",
                work_root=tmp_path / "work",
                station_candidates_path=tmp_path / "station_candidates.jsonl",
                computed_day="2026-09-27",
                now_ns=1,
                instance_spans_cache_path=cache_path,
            )

        assert read_instance_span_cache(cache_path) == {}
