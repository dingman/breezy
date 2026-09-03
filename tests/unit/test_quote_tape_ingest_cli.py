"""RED-first tests for the missing catalog-conversion step (`breezy-quote-tape-ingest`).

199,079 depth rows for the 2026-09-01 afternoon sat invisible under
``<catalog>/live/<instance>/`` because nothing but a manual, twice-ever
``convert_stream_to_data`` call ever turned them into the parquet layout
every analysis script queries. These tests pin the four safety properties
that make automating that call safe:

1. a recently-written instance is never converted (it may be mid-write, and
   a stream with no end-of-stream marker read as complete is exactly the
   BL-23 defect wearing a new hat);
2. an instance already marked converted for a data type is skipped, not
   re-scanned;
3. a ``ValueError`` from one data type (the native non-disjoint-interval
   refusal) never stops the remaining types or aborts the instance; and
4. a second run over an unchanged tape converts nothing further.

A fifth property was added after the timer failed on EVERY run for three
days: instrument definitions are RE-EMITTED carrying their ORIGINAL
``ts_init``, so a one-row feather file's point interval lands strictly INSIDE
the interval of the already-written multi-row file, and the native
``convert_stream_to_data`` refuses it forever. Those types must be converted
row-wise and de-duplicated, while every other type keeps the single native
call.
"""

from __future__ import annotations

import io
import logging
import os
import time
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import MarkPriceUpdate, QuoteTick
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

from breezy.runtime.quote_tape_ingest_cli import (
    CONVERTED,
    CONVERTED_NOTHING_NEW,
    DEFAULT_LIVE_GRACE_MINUTES,
    EXIT_OK,
    EXIT_USAGE,
    default_convert,
    ingest_instance,
    run,
    run_ingest,
)
from breezy.runtime.quote_tape_preflight_cli import CATALOG_ENV_VAR


def _recording_convert(
    calls: list[tuple[str, type]],
) -> Callable[[ParquetDataCatalog, str, type, str], None]:
    def convert(
        catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
    ) -> None:
        calls.append((instance_id, data_cls))

    return convert

INSTANCE = "instance-1"
OTHER_INSTANCE = "instance-2"


def _touch(
    catalog_root: Path, instance_id: str, name: str, *, age_minutes: float = 0.0
) -> Path:
    """Create an empty ``.feather`` file. Zero bytes is `EMPTY_FILE` to the
    preflight scanner -- never truncated -- so these fixtures exercise
    liveness and idempotency without needing a real Arrow stream.
    """
    path = catalog_root / "live" / instance_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    if age_minutes:
        stamp = time.time() - age_minutes * 60
        os.utime(path, (stamp, stamp))
    return path


def _never_active() -> bool:
    return False


# --- instrument-definition fixtures ------------------------------------------
#
# These build a REAL Arrow IPC stream the same way `StreamingFeatherWriter`
# does (flat `<instance>/binary_option_<n>.feather`, schema metadata carrying
# the class name), because the defect under test lives in how the interval of
# one such file relates to what is already in `data/binary_option/` -- a
# zero-byte placeholder cannot express it.

_FIXTURE_VENUE = Venue("POLYUS")

#: T0 < T1 < T2. T1 is the re-emitted definition whose point interval lands
#: strictly inside the [T0, T2] file already in the catalog.
T0 = 1_788_272_911_000_000_000
T1 = 1_788_280_000_000_000_000
T2 = 1_788_294_512_000_000_000


def _binary_option(
    symbol: str, ts_init: int, *, description: str = "ingest fixture"
) -> BinaryOption:
    raw_symbol = Symbol(symbol)
    return BinaryOption(
        instrument_id=InstrumentId(symbol=raw_symbol, venue=_FIXTURE_VENUE),
        raw_symbol=raw_symbol,
        outcome="Yes",
        description=description,
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


def _write_instrument_feather(
    catalog_root: Path,
    instance_id: str,
    name: str,
    instruments: Sequence[BinaryOption],
    *,
    age_minutes: float = DEFAULT_LIVE_GRACE_MINUTES + 5,
) -> Path:
    """Write ``instruments`` as one closed Arrow IPC stream under the instance."""
    batch = ArrowSerializer.serialize_batch(list(instruments), data_cls=BinaryOption)
    table = (
        pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
    )
    table = table.replace_schema_metadata({"class": BinaryOption.__name__})

    path = catalog_root / "live" / instance_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, table.schema)
        writer.write_table(table)
        writer.close()

    stamp = time.time() - age_minutes * 60
    os.utime(path, (stamp, stamp))
    return path


def _seed_catalog(
    catalog_root: Path, instance_id: str, instruments: Sequence[BinaryOption]
) -> None:
    """Put ``instruments`` in the catalog the way an EARLIER timer run did.

    Deliberately the native ``convert_stream_to_data``, not ``write_data``:
    the streamed feather carries no ``instrument_id`` schema metadata, so the
    native converter derives no identifier and writes FLAT to
    ``data/binary_option/``. Seeding with ``write_data`` instead would file
    the rows under ``data/binary_option/<instrument_id>/`` -- a different
    directory, no interval overlap, and a fixture that cannot reproduce the
    defect at all.
    """
    _write_instrument_feather(
        catalog_root, instance_id, "binary_option_0.feather", instruments
    )
    ParquetDataCatalog(str(catalog_root)).convert_stream_to_data(
        instance_id, BinaryOption, subdirectory="live"
    )


def _catalog_definitions(catalog_root: Path) -> list[tuple[str, int]]:
    definitions = ParquetDataCatalog(str(catalog_root)).query(data_cls=BinaryOption)
    return sorted((str(d.id), d.ts_init) for d in definitions)


def _parquet_files(catalog_root: Path) -> list[Path]:
    return sorted((catalog_root / "data" / "binary_option").rglob("*.parquet"))


class TestLiveInstancesAreNeverConverted:
    def test_a_recently_written_instance_is_skipped_as_live(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_1.feather", age_minutes=0.0)
        calls: list[tuple[str, type]] = []

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=_recording_convert(calls),
        )

        assert len(results) == 1
        assert results[0].outcome == "skipped-live"
        assert calls == []

    def test_an_old_but_currently_active_instance_is_still_skipped_as_live(
        self, tmp_path: Path
    ) -> None:
        """Rule (b): the newest instance while the service is active -- a
        quiet market can leave the CURRENT instance with no recent write at
        all, and that must not be misread as abandoned.
        """
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_1.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )
        calls: list[tuple[str, type]] = []

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=lambda: True,
            convert_fn=_recording_convert(calls),
        )

        assert results[0].outcome == "skipped-live"
        assert calls == []


class TestAlreadyConvertedTypesAreSkipped:
    def test_an_instance_with_a_converted_marker_is_skipped(self, tmp_path: Path) -> None:
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_1.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )
        marker = tmp_path / "live" / INSTANCE / ".converted-quote_tick"
        marker.touch()
        calls: list[tuple[str, type]] = []

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=_recording_convert(calls),
        )

        assert results[0].outcome == "converted"
        assert results[0].type_results[0].outcome == "skipped-already-converted"
        assert calls == []


class TestOneTypesValueErrorNeverStopsTheOthers:
    def test_a_value_error_from_one_type_does_not_stop_the_next_type(
        self, tmp_path: Path
    ) -> None:
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_1.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )
        calls: list[type] = []

        def flaky_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append(data_cls)
            if data_cls is QuoteTick:
                raise ValueError("non-disjoint interval on republished definitions")

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick, MarkPriceUpdate),
            service_active_probe=_never_active,
            convert_fn=flaky_convert,
        )

        # Both types were attempted -- the failure of the first never
        # short-circuited the second.
        assert calls == [QuoteTick, MarkPriceUpdate]

        outcomes = {r.data_cls: r.outcome for r in results[0].type_results}
        assert outcomes[QuoteTick] == "failed"
        assert outcomes[MarkPriceUpdate] == "converted"

        instance_dir = tmp_path / "live" / INSTANCE
        assert not (instance_dir / ".converted-quote_tick").exists()
        assert (instance_dir / ".converted-mark_price_update").exists()


class TestRunningTwiceAddsNothing:
    def test_second_run_adds_zero_rows(self, tmp_path: Path) -> None:
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_1.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )
        calls: list[type] = []

        def recording_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append(data_cls)

        first = run_ingest(
            tmp_path,
            data_types=(QuoteTick, BinaryOption),
            service_active_probe=_never_active,
            convert_fn=recording_convert,
        )
        assert len(calls) == 2
        assert {r.outcome for r in first[0].type_results} == {"converted"}

        second = run_ingest(
            tmp_path,
            data_types=(QuoteTick, BinaryOption),
            service_active_probe=_never_active,
            convert_fn=recording_convert,
        )

        # No further native conversion calls -- the second run adds nothing.
        assert len(calls) == 2
        assert {r.outcome for r in second[0].type_results} == {"skipped-already-converted"}


class TestIngestInstanceDirectly:
    def test_ingest_instance_marks_only_the_types_it_actually_converts(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        instance_dir.mkdir(parents=True)
        catalog = ParquetDataCatalog(str(tmp_path))

        def no_op_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            return None

        result = ingest_instance(
            catalog,
            tmp_path,
            INSTANCE,
            "live",
            (QuoteTick,),
            convert_fn=no_op_convert,
        )

        assert result.outcome == "converted"
        assert result.type_results[0].outcome == "converted"
        assert (instance_dir / ".converted-quote_tick").is_file()


class TestConsoleEntrypoint:
    def test_usage_error_when_no_catalog_is_configured(self, tmp_path: Path) -> None:
        out, err = io.StringIO(), io.StringIO()
        code = run([], env={}, stdout=out, stderr=err)
        assert code == EXIT_USAGE
        assert CATALOG_ENV_VAR in err.getvalue()

    def test_dry_run_reports_without_converting_or_marking(self, tmp_path: Path) -> None:
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_1.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )
        out, err = io.StringIO(), io.StringIO()

        code = run(
            ["--dry-run"],
            env={CATALOG_ENV_VAR: str(tmp_path)},
            stdout=out,
            stderr=err,
        )

        assert code == EXIT_OK
        assert "dry-run" in out.getvalue()
        assert not (tmp_path / "live" / INSTANCE / ".converted-quote_tick").exists()


class TestReEmittedInstrumentDefinitionsStillLand:
    """The three-day defect: `binary_option` failed on EVERY timer run.

    The recorder re-emits an instrument definition with its ORIGINAL
    `ts_init`, so the one-row feather file written at 09-02T02:28 carries the
    point interval of 09-01T14:28 -- strictly inside the interval of the
    multi-row file already in `data/binary_option/`. The native
    `convert_stream_to_data` refuses that overlap permanently, so definitions
    stopped landing and the marker was never written.
    """

    def test_a_new_row_inside_an_existing_interval_is_written(
        self, tmp_path: Path
    ) -> None:
        _seed_catalog(
            tmp_path, INSTANCE, [_binary_option("MKT-A", T0), _binary_option("MKT-A", T2)]
        )
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_1.feather", [_binary_option("MKT-A", T1)]
        )

        results = run_ingest(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=_never_active,
        )

        assert results[0].type_results[0].outcome == CONVERTED
        assert (tmp_path / "live" / INSTANCE / ".converted-binary_option").is_file()
        assert [ts for _id, ts in _catalog_definitions(tmp_path)] == [T0, T1, T2]

    def test_an_exact_duplicate_writes_nothing_and_is_still_marked_converted(
        self, tmp_path: Path
    ) -> None:
        _seed_catalog(
            tmp_path, INSTANCE, [_binary_option("MKT-A", T0), _binary_option("MKT-A", T2)]
        )
        before = _parquet_files(tmp_path)
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_1.feather", [_binary_option("MKT-A", T0)]
        )

        results = run_ingest(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=_never_active,
        )

        assert results[0].type_results[0].outcome == CONVERTED_NOTHING_NEW
        assert (tmp_path / "live" / INSTANCE / ".converted-binary_option").is_file()
        assert _parquet_files(tmp_path) == before
        assert [ts for _id, ts in _catalog_definitions(tmp_path)] == [T0, T2]

    def test_only_the_genuinely_new_row_of_a_mixed_stream_lands(
        self, tmp_path: Path
    ) -> None:
        _seed_catalog(
            tmp_path, INSTANCE, [_binary_option("MKT-A", T0), _binary_option("MKT-A", T2)]
        )
        _write_instrument_feather(
            tmp_path,
            INSTANCE,
            "binary_option_1.feather",
            [_binary_option("MKT-A", T0), _binary_option("MKT-A", T1)],
        )

        results = run_ingest(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=_never_active,
        )

        assert results[0].type_results[0].outcome == CONVERTED
        assert [ts for _id, ts in _catalog_definitions(tmp_path)] == [T0, T1, T2]


class TestNonInstrumentTypesKeepTheSingleNativeCall:
    def test_a_quote_tick_still_goes_through_convert_stream_to_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The row-wise path is for instrument definitions ONLY.

        Quote/depth/trade rows are capture-timed and monotonic, so they never
        hit the overlap; re-routing them through a deserialise-and-rewrite
        path would trade a working native bulk copy for a slower one.
        """
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_1.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_0.feather", [_binary_option("MKT-A", T0)]
        )
        native_calls: list[type] = []

        def spy(
            self: ParquetDataCatalog, instance_id: str, data_cls: type, **kwargs: Any
        ) -> None:
            native_calls.append(data_cls)

        monkeypatch.setattr(ParquetDataCatalog, "convert_stream_to_data", spy)

        run_ingest(
            tmp_path,
            data_types=(QuoteTick, BinaryOption),
            service_active_probe=_never_active,
        )

        assert native_calls == [QuoteTick]

    def test_a_native_value_error_still_marks_that_type_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_1.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )

        def boom(
            self: ParquetDataCatalog, instance_id: str, data_cls: type, **kwargs: Any
        ) -> None:
            raise ValueError("would create non-disjoint intervals")

        monkeypatch.setattr(ParquetDataCatalog, "convert_stream_to_data", boom)

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
        )

        assert results[0].type_results[0].outcome == "failed"
        assert not (tmp_path / "live" / INSTANCE / ".converted-quote_tick").exists()


class TestTheMixedCatalogLayoutIsPinned:
    """The flat/per-id split is a live constraint, not a cosmetic detail.

    Native `convert_stream_to_data` wrote definitions FLAT to
    `data/binary_option/` (the streamed feather carries no `instrument_id`
    schema metadata, so no identifier is derived); `write_data` files them
    under `data/binary_option/<instrument_id>/`. An unfiltered query returns
    the union, but `filter_files` derives a file's identifier from
    `file_path.split("/")[-2]` (`parquet.py:2249`), which for a flat file is
    the data-type directory -- so an identifier-FILTERED query silently omits
    every flat row. This pins both halves: the day Nautilus changes either,
    this fires instead of a settlement query quietly losing rows.
    """

    def test_only_the_unfiltered_query_sees_both_layouts(self, tmp_path: Path) -> None:
        _seed_catalog(
            tmp_path, INSTANCE, [_binary_option("MKT-A", T0), _binary_option("MKT-A", T2)]
        )
        catalog = ParquetDataCatalog(str(tmp_path))
        catalog.write_data([_binary_option("MKT-A", T1)], skip_disjoint_check=True)

        flat = sorted((tmp_path / "data" / "binary_option").glob("*.parquet"))
        per_id = sorted((tmp_path / "data" / "binary_option").glob("*/*.parquet"))
        assert len(flat) == 1 and len(per_id) == 1

        unfiltered = catalog.query(data_cls=BinaryOption)
        filtered = catalog.query(data_cls=BinaryOption, identifiers=["MKT-A.POLYUS"])

        assert sorted(d.ts_init for d in unfiltered) == [T0, T1, T2]
        # The flat rows are INVISIBLE to the identifier-filtered query.
        assert sorted(d.ts_init for d in filtered) == [T1]


class TestADivergentReEmissionIsCountedNotSilent:
    def test_same_key_different_content_warns_with_a_count_and_no_ids(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`Instrument.__eq__` compares only `id` (`base.pyx:299-302`), so a
        re-emission that changed a field but kept its `(instrument_id,
        ts_init)` is indistinguishable by equality. The landed row wins --
        rewriting it is not this module's call -- but it is never silent.
        """
        _seed_catalog(tmp_path, INSTANCE, [_binary_option("MKT-A", T0)])
        _write_instrument_feather(
            tmp_path,
            INSTANCE,
            "binary_option_1.feather",
            [_binary_option("MKT-A", T0, description="RE-EMITTED WITH A CHANGED FIELD")],
        )

        with caplog.at_level(logging.WARNING, logger="breezy.runtime.quote_tape_ingest_cli"):
            results = run_ingest(
                tmp_path,
                data_types=(BinaryOption,),
                service_active_probe=_never_active,
            )

        assert results[0].type_results[0].outcome == CONVERTED_NOTHING_NEW
        assert [ts for _id, ts in _catalog_definitions(tmp_path)] == [T0]

        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert "1" in warnings[0]
        # Value-free by contract: a count, never an instrument id.
        assert "MKT-A" not in warnings[0]

    def test_an_identical_re_emission_warns_about_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _seed_catalog(tmp_path, INSTANCE, [_binary_option("MKT-A", T0)])
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_1.feather", [_binary_option("MKT-A", T0)]
        )

        with caplog.at_level(logging.WARNING, logger="breezy.runtime.quote_tape_ingest_cli"):
            run_ingest(
                tmp_path,
                data_types=(BinaryOption,),
                service_active_probe=_never_active,
            )

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


class TestStreamReadFailuresBecomeThisTypesFailure:
    def test_an_unsupported_subdirectory_is_refused_by_name(self, tmp_path: Path) -> None:
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_0.feather", [_binary_option("MKT-A", T0)]
        )
        catalog = ParquetDataCatalog(str(tmp_path))

        with pytest.raises(ValueError, match="subdirectory 'archive'"):
            default_convert(catalog, INSTANCE, BinaryOption, "archive")

    def test_an_undeserialisable_stream_becomes_a_value_error(self, tmp_path: Path) -> None:
        """A readable stream whose rows are not this type must FAIL, never
        deserialise to zero rows and get the success marker -- that is the
        invisible-data defect this module exists to end.
        """
        path = tmp_path / "live" / INSTANCE / "binary_option_0.feather"
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table({"not_a_binary_option": pa.array([1, 2, 3])})
        table = table.replace_schema_metadata({"class": BinaryOption.__name__})
        with path.open("wb") as handle:
            writer = pa.ipc.new_stream(handle, table.schema)
            writer.write_table(table)
            writer.close()
        catalog = ParquetDataCatalog(str(tmp_path))

        with pytest.raises(ValueError, match="could not read streamed binary_option"):
            default_convert(catalog, INSTANCE, BinaryOption, "live")
