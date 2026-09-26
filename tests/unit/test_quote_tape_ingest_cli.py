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

import dataclasses
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
from nautilus_trader.model.data import InstrumentClose, MarkPriceUpdate, QuoteTick, TradeTick
from nautilus_trader.model.enums import AggressorSide, AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TradeId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import class_to_filename
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer
from nautilus_trader.test_kit.providers import TestInstrumentProvider

import breezy.runtime.quote_tape_ingest_cli as ingest_cli_module
from breezy.persistence.feather_preflight import inspect_feather_file, salvage_feather_file
from breezy.runtime.quote_tape_ingest_cli import (
    CONVERTED,
    CONVERTED_NOTHING_NEW,
    DEFAULT_DATA_TYPES,
    DEFAULT_LIVE_GRACE_MINUTES,
    EXIT_CONVERSION_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    FILE_MARKER_PREFIX,
    MARKER_PREFIX,
    default_convert,
    ingest_instance,
    run,
    run_ingest,
)
from breezy.runtime.quote_tape_preflight_cli import CATALOG_ENV_VAR
from breezy.runtime.quote_tape_salvage import salvage_truncated_instance
from tests.contract.test_quote_tape_unclean_shutdown import (
    INSTANCE_ID as _SIGKILL_INSTANCE_ID,
)
from tests.contract.test_quote_tape_unclean_shutdown import (
    RECORD_COUNT as _SIGKILL_RECORD_COUNT,
)
from tests.contract.test_quote_tape_unclean_shutdown import (
    _sigkill_a_real_writer,
)


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

    def test_run_ingest_does_not_open_feathers_when_every_type_is_already_converted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fully-converted instance's frozen bytes must not be re-streamed.

        ``scan_instance`` still walks every record batch even with
        ``collect=False``. Periodic ingest therefore re-read gigabytes of
        already-converted feather until this skip landed.
        """
        instance_dir = tmp_path / "live" / INSTANCE
        for data_cls in DEFAULT_DATA_TYPES:
            name = class_to_filename(data_cls)
            _touch(
                tmp_path,
                INSTANCE,
                f"{name}_0.feather",
                age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
            )
            (instance_dir / f"{MARKER_PREFIX}{name}").touch()

        opened: list[Path] = []
        real_inspect = inspect_feather_file

        def spy_inspect(path: Path) -> Any:
            opened.append(path)
            return real_inspect(path)

        monkeypatch.setattr(
            "breezy.persistence.feather_preflight.inspect_feather_file", spy_inspect
        )
        calls: list[tuple[str, type]] = []

        results = run_ingest(
            tmp_path,
            data_types=DEFAULT_DATA_TYPES,
            service_active_probe=_never_active,
            convert_fn=_recording_convert(calls),
        )

        assert opened == []
        assert len(results) == 1
        assert {result.outcome for result in results[0].type_results} == {
            "skipped-already-converted"
        }
        assert calls == []

    def test_run_ingest_still_scans_when_one_converted_marker_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing a single marker must not inherit the fully-converted skip."""
        instance_dir = tmp_path / "live" / INSTANCE
        skipped = DEFAULT_DATA_TYPES[-1]
        for data_cls in DEFAULT_DATA_TYPES:
            name = class_to_filename(data_cls)
            _touch(
                tmp_path,
                INSTANCE,
                f"{name}_0.feather",
                age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
            )
            if data_cls is not skipped:
                (instance_dir / f"{MARKER_PREFIX}{name}").touch()

        opened: list[Path] = []
        real_inspect = inspect_feather_file

        def spy_inspect(path: Path) -> Any:
            opened.append(path)
            return real_inspect(path)

        monkeypatch.setattr(
            "breezy.persistence.feather_preflight.inspect_feather_file", spy_inspect
        )
        calls: list[tuple[str, type]] = []

        results = run_ingest(
            tmp_path,
            data_types=DEFAULT_DATA_TYPES,
            service_active_probe=_never_active,
            convert_fn=_recording_convert(calls),
        )

        assert opened, "an instance missing a marker must still be scanned"
        assert len(results) == 1
        outcomes = {result.data_cls: result.outcome for result in results[0].type_results}
        assert outcomes[skipped] == "converted"
        assert calls == [(INSTANCE, skipped)]

    def test_run_ingest_still_scans_when_an_unrequested_type_is_unconverted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A narrow data_types skip must not hide an unmarked sibling feather.

        ``run_ingest(..., data_types=(QuoteTick,))`` used to treat
        ``.converted-quote_tick`` as "fully converted" and skip
        ``scan_instance``. An unrequested ``instrument_close_0.feather``
        in the same instance was then never inspected, so truncation of
        that file was neither reported nor salvaged.
        """
        instance_dir = tmp_path / "live" / INSTANCE
        _touch(
            tmp_path,
            INSTANCE,
            "quote_tick_0.feather",
            age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
        )
        (instance_dir / f"{MARKER_PREFIX}{class_to_filename(QuoteTick)}").touch()

        close_path = instance_dir / "instrument_close_0.feather"
        _write_typed_ipc_stream(
            close_path, [_quote_tick(i) for i in range(20)], QuoteTick, close=False
        )
        _truncate_tail(close_path)
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(close_path, (stamp, stamp))

        opened: list[Path] = []
        real_inspect = inspect_feather_file

        def spy_inspect(path: Path) -> Any:
            opened.append(path)
            return real_inspect(path)

        monkeypatch.setattr(
            "breezy.persistence.feather_preflight.inspect_feather_file", spy_inspect
        )
        calls: list[tuple[str, type]] = []

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=_recording_convert(calls),
        )

        assert opened, "an unmarked unrequested type must still be scanned"
        assert any(path.name == "instrument_close_0.feather" for path in opened)
        assert len(results) == 1
        assert results[0].outcome == "skipped-truncated"
        assert calls == []

    def test_run_ingest_skips_scan_only_when_every_present_feather_type_is_marked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Skip the BL-23 walk only when every on-disk type is marked, even
        if the caller requested a narrower ``data_types`` than is present.
        """
        instance_dir = tmp_path / "live" / INSTANCE
        for name in ("quote_tick", "instrument_close"):
            _touch(
                tmp_path,
                INSTANCE,
                f"{name}_0.feather",
                age_minutes=DEFAULT_LIVE_GRACE_MINUTES + 5,
            )
            (instance_dir / f"{MARKER_PREFIX}{name}").touch()

        opened: list[Path] = []
        real_inspect = inspect_feather_file

        def spy_inspect(path: Path) -> Any:
            opened.append(path)
            return real_inspect(path)

        monkeypatch.setattr(
            "breezy.persistence.feather_preflight.inspect_feather_file", spy_inspect
        )
        calls: list[tuple[str, type]] = []

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=_recording_convert(calls),
        )

        assert opened == []
        assert len(results) == 1
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
    def test_a_quote_tick_still_goes_through_the_native_bulk_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The row-wise path is for instrument definitions ONLY.

        Quote/depth/trade rows are capture-timed and monotonic, so they never
        hit the overlap; re-routing them through a deserialise-and-rewrite
        path would trade a working native bulk copy for a slower one.

        ING-2 S3a: the fast path now calls a Breezy mirror,
        ``_convert_stream_natively``, instead of the native
        ``ParquetDataCatalog.convert_stream_to_data`` directly (it still
        calls native ``_convert_feather_table_to_parquet`` per file inside
        that mirror) -- so the spy is retargeted to the seam this module
        actually calls. Mutation M1 (``default_convert`` bypasses the seam
        and calls ``catalog.convert_stream_to_data`` directly) must turn this
        RED: the spy would then stay empty.
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
            catalog: ParquetDataCatalog,
            instance_id: str,
            data_cls: type,
            subdirectory: str,
            *,
            target: ParquetDataCatalog | None = None,
        ) -> None:
            native_calls.append(data_cls)

        monkeypatch.setattr(ingest_cli_module, "_convert_stream_natively", spy)

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
            catalog: ParquetDataCatalog,
            instance_id: str,
            data_cls: type,
            subdirectory: str,
            *,
            target: ParquetDataCatalog | None = None,
        ) -> None:
            raise ValueError("would create non-disjoint intervals")

        monkeypatch.setattr(ingest_cli_module, "_convert_stream_natively", boom)

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


@pytest.mark.contract
class TestATruncatedInstanceIsSalvagedNotDropped:
    """A SIGKILL-truncated instance must not lose the whole day.

    ``tests/contract/test_quote_tape_unclean_shutdown.py`` measured that the
    native path returns zero rows for a truncated tape, and the ingest CLI
    (before this test) quarantined the instance -- correctly refusing full
    conversion -- but never landed the recoverable prefix either. This pins
    the fix: the readable prefix must land in the catalog, the truncated
    source file must survive untouched, and the loss must be reported.
    """

    def _truncate(self, tape: Path) -> None:
        """Truncate the quote tape and backdate EVERY feather file the
        writer staged for this instance -- not just the tape -- past the
        live-grace window. A real ``StreamingFeatherWriter`` touches an
        empty flat file for every registered data type on construction, and
        ``classify_liveness`` looks at the WHOLE instance's write window, so
        leaving those at "now" would classify the instance live regardless
        of the tape's own mtime.
        """
        with tape.open("r+b") as handle:
            handle.truncate(tape.stat().st_size - 64)
        stamp = time.time() - 60 * 60  # outside the live-grace window
        instance_dir = tape
        while instance_dir.name != _SIGKILL_INSTANCE_ID:
            instance_dir = instance_dir.parent
        for path in instance_dir.rglob("*.feather"):
            os.utime(path, (stamp, stamp))

    def test_recoverable_rows_land_in_the_catalog(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        tape = _sigkill_a_real_writer(tmp_path, mode="flush")
        original_bytes = tape.read_bytes()
        self._truncate(tape)

        with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_salvage"):
            results = run_ingest(
                tmp_path,
                data_types=(QuoteTick,),
                service_active_probe=_never_active,
            )

        catalog = ParquetDataCatalog(str(tmp_path))
        recovered_rows = len(catalog.query(data_cls=QuoteTick))
        assert 0 < recovered_rows < _SIGKILL_RECORD_COUNT, (
            "the salvageable prefix must be ingested, and the truncated tail "
            "must genuinely still be lost"
        )

        # (b) the truncated source file is preserved untouched for forensics --
        # byte for byte, not merely "still exists".
        assert tape.exists()
        assert tape.read_bytes() != original_bytes  # it was truncated by the test fixture
        assert tape.stat().st_size == len(original_bytes) - 64
        assert tape.read_bytes() == original_bytes[: len(original_bytes) - 64]

        # The instance is still reported as quarantined, not fully converted.
        assert results[0].instance_id == _SIGKILL_INSTANCE_ID
        assert results[0].outcome == "skipped-truncated"

        # (c) the loss is reported, with counts.
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "salvaged" in messages.lower()
        assert str(recovered_rows) in messages

    def test_a_second_run_does_not_duplicate_the_salvaged_rows(
        self, tmp_path: Path
    ) -> None:
        tape = _sigkill_a_real_writer(tmp_path, mode="flush")
        self._truncate(tape)

        run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)
        catalog = ParquetDataCatalog(str(tmp_path))
        first_count = len(catalog.query(data_cls=QuoteTick))

        run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)
        second_count = len(catalog.query(data_cls=QuoteTick))

        assert first_count > 0
        assert second_count == first_count

    def test_a_truncated_file_with_no_recoverable_rows_is_not_ingested(
        self, tmp_path: Path
    ) -> None:
        """The header-only truncation case: nothing readable, nothing to land."""
        instance_dir = tmp_path / "live" / INSTANCE / "quote_tick"
        instance_dir.mkdir(parents=True, exist_ok=True)
        tape = instance_dir / "quote_tick_0.feather"
        # Not even a readable schema message.
        tape.write_bytes(b"ARROW1\x00\x00garbage-not-a-real-stream")
        stamp = time.time() - 60 * 60  # outside the live-grace window
        os.utime(tape, (stamp, stamp))

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert results[0].outcome == "skipped-truncated"
        assert tape.exists()

    def test_a_salvage_failure_on_one_instance_does_not_abort_a_later_instance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Salvage must be isolated PER TRUNCATED FILE, exactly like
        ``ingest_instance``'s own ``except ValueError`` isolates one data
        type's conversion failure from the rest -- never a whole-run abort.
        """
        tape = _sigkill_a_real_writer(tmp_path, mode="flush")
        self._truncate(tape)

        # A second, ordinary instance the ingest CLI must still convert even
        # though the first instance's salvage blows up.
        _write_instrument_feather(
            tmp_path, OTHER_INSTANCE, "binary_option_0.feather", [_binary_option("MKT-A", T0)]
        )

        import breezy.runtime.quote_tape_salvage as salvage_module

        def _raise(path: Path) -> None:
            raise ValueError("synthetic salvage failure")

        monkeypatch.setattr(salvage_module, "salvage_feather_file", _raise)

        with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_salvage"):
            results = run_ingest(
                tmp_path,
                data_types=(QuoteTick, BinaryOption),
                service_active_probe=_never_active,
            )

        by_instance = {result.instance_id: result for result in results}
        assert by_instance[INSTANCE].outcome == "skipped-truncated"
        assert by_instance[OTHER_INSTANCE].outcome == "converted"
        binary_outcomes = {
            r.outcome
            for r in by_instance[OTHER_INSTANCE].type_results
            if r.data_cls is BinaryOption
        }
        assert binary_outcomes == {CONVERTED}

        # And zero rows landed for the instance whose salvage raised -- no
        # partial/corrupt write slipped through the failure.
        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "synthetic salvage failure" in messages

    def test_a_salvaged_row_that_already_landed_is_not_duplicated(
        self, tmp_path: Path
    ) -> None:
        """The de-duplication precedent ``convert_instrument_definitions``
        sets for re-emitted definitions, generalised: writing salvaged rows
        with ``skip_disjoint_check=True`` bypasses the ONLY native guard
        against a duplicate, so salvage must not rely on running once.
        """
        tape = _sigkill_a_real_writer(tmp_path, mode="flush")
        self._truncate(tape)

        preview = salvage_feather_file(tape)
        recovered_count = preview.rows_recovered
        assert recovered_count > 1, "need at least one non-overlapping row too"

        instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
        overlapping_tick = QuoteTick(
            instrument_id=instrument.id,
            bid_price=Price.from_str("1.00000"),
            ask_price=Price.from_str("1.00010"),
            bid_size=Quantity.from_int(1),
            ask_size=Quantity.from_int(1),
            ts_event=1_000_000_000,
            ts_init=1_000_000_000,
        )
        catalog = ParquetDataCatalog(str(tmp_path))
        catalog.write_data([overlapping_tick])

        run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)

        landed = catalog.query(data_cls=QuoteTick)
        matching = [tick for tick in landed if tick.ts_init == 1_000_000_000]
        assert len(matching) == 1, "the pre-landed row must not be duplicated"
        assert len(landed) == 1 + (recovered_count - 1)


def _quote_tick(index: int) -> QuoteTick:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price.from_str("1.00000"),
        ask_price=Price.from_str("1.00010"),
        bid_size=Quantity.from_int(1),
        ask_size=Quantity.from_int(1),
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _mark_price(index: int) -> MarkPriceUpdate:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    return MarkPriceUpdate(
        instrument_id=instrument.id,
        value=Price.from_str("1.00000"),
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _write_typed_ipc_stream(
    path: Path, objects: Sequence[Any], data_cls: type, *, close: bool
) -> None:
    """Write ``objects`` as one Arrow IPC stream the salvage path can read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    first = ArrowSerializer.serialize_batch([objects[0]], data_cls=data_cls)
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, first.schema)
        for obj in objects:
            piece = ArrowSerializer.serialize_batch([obj], data_cls=data_cls)
            if isinstance(piece, pa.RecordBatch):
                writer.write_batch(piece)
            else:
                writer.write_table(piece)
        if close:
            writer.close()


def _truncate_tail(path: Path, *, drop_bytes: int = 64) -> None:
    with path.open("r+b") as handle:
        handle.truncate(path.stat().st_size - drop_bytes)


class TestSalvageIsolatesATypeWithNoArrowWrangler:
    def test_salvage_isolates_a_type_with_no_arrow_wrangler_and_continues(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A wrangler-None type must not abort salvage of a sibling file.

        ``ArrowSerializer._deserialize_rust`` raises ``NotImplementedError``
        for ``MarkPriceUpdate`` (Rust wrangler is ``None``). That used to
        escape ``_ISOLATED_ERRORS`` and take down the whole ingest unit.
        """
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        mark_path = instance_dir / "mark_price_update_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(20)], QuoteTick, close=False
        )
        _write_typed_ipc_stream(
            mark_path, [_mark_price(i) for i in range(20)], MarkPriceUpdate, close=False
        )
        _truncate_tail(quote_path)
        _truncate_tail(mark_path)

        quote_report = inspect_feather_file(quote_path)
        mark_report = inspect_feather_file(mark_path)
        assert quote_report.is_truncated
        assert mark_report.is_truncated
        assert quote_report.rows > 0

        catalog = ParquetDataCatalog(str(tmp_path))
        with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_salvage"):
            salvage_truncated_instance(
                catalog,
                instance_dir,
                INSTANCE,
                (MarkPriceUpdate, QuoteTick),
                (mark_report, quote_report),
            )

        landed = catalog.query(data_cls=QuoteTick)
        assert len(landed) > 0
        assert (instance_dir / f".salvaged-{quote_path.name}").is_file()
        assert not (instance_dir / f".salvaged-{mark_path.name}").is_file()

        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "NotImplementedError" in messages
        assert "skipped" in messages


def _trade_tick(index: int) -> TradeTick:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    return TradeTick(
        instrument_id=instrument.id,
        price=Price.from_str("1.00000"),
        size=Quantity.from_int(1),
        aggressor_side=AggressorSide.BUYER,
        trade_id=TradeId(f"T-{index}"),
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


class TestPerFileConversionSurvivesOpenAndTruncatedSiblings:
    """GL-14/BL-24: neither a truncated nor an open sibling may block a
    genuinely complete file, regardless of type or rotation order.
    """

    def test_an_intact_sibling_is_converted_despite_a_truncated_file(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        trade_path = instance_dir / "trade_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(20)], QuoteTick, close=False
        )
        _truncate_tail(quote_path)
        _write_typed_ipc_stream(
            trade_path, [_trade_tick(i) for i in range(20)], TradeTick, close=True
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        for path in (quote_path, trade_path):
            os.utime(path, (stamp, stamp))

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick, TradeTick),
            service_active_probe=_never_active,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        # the intact sibling, a DIFFERENT type, landed despite the truncation
        assert len(catalog.query(data_cls=TradeTick)) == 20
        # the truncated file's readable prefix was salvaged, not dropped
        recovered = catalog.query(data_cls=QuoteTick)
        assert 0 < len(recovered) < 20

        # per-FILE marker, not the blanket per-type marker: the type could
        # still receive a new file while the instance is not fully clean.
        assert (instance_dir / f"{FILE_MARKER_PREFIX}{trade_path.name}").is_file()
        assert not (instance_dir / ".converted-trade_tick").exists()

        # the instance is still reported quarantined -- QuoteTick remains
        # truncated -- even though real progress happened underneath.
        assert results[0].outcome == "skipped-truncated"

    def test_the_currently_open_file_is_skipped_not_converted(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        closed_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "quote_tick_1.feather"
        _write_typed_ipc_stream(
            closed_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_quote_tick(100 + i) for i in range(5)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(closed_path, (stamp, stamp))
        # `open_path` is left at "now" -- inside the live-grace window.

        results = run_ingest(
            tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        landed = {tick.ts_init for tick in catalog.query(data_cls=QuoteTick)}
        assert landed == {1_000_000_000 + i for i in range(10)}
        assert 1_000_000_100 not in landed  # the open file was never read

        assert (instance_dir / f"{FILE_MARKER_PREFIX}{closed_path.name}").is_file()
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{open_path.name}").is_file()
        assert results[0].outcome == "converted"

    def test_a_second_run_converts_nothing_new(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        closed_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "quote_tick_1.feather"
        _write_typed_ipc_stream(
            closed_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_quote_tick(100 + i) for i in range(5)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(closed_path, (stamp, stamp))

        run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)
        catalog = ParquetDataCatalog(str(tmp_path))
        first_count = len(catalog.query(data_cls=QuoteTick))

        run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)
        second_count = len(catalog.query(data_cls=QuoteTick))

        assert first_count == 10
        assert second_count == first_count

    def test_dry_run_writes_nothing_for_a_mixed_open_and_closed_instance(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        closed_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "quote_tick_1.feather"
        _write_typed_ipc_stream(
            closed_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_quote_tick(100 + i) for i in range(5)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(closed_path, (stamp, stamp))

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            dry_run=True,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{closed_path.name}").exists()
        assert results[0].outcome == "dry-run"


class TestANoneOrEmptyPostTransformTableIsAHardFailure:
    """Review item 1: the per-file path must never mark a file whose read
    silently produced nothing, unlike ``convert_stream_to_data``'s own
    caller (parquet.py:2644-2646), which treats that ``None`` as "done".
    """

    def _mixed_instance(self, tmp_path: Path) -> tuple[Path, Path]:
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "quote_tick_1.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_quote_tick(100 + i) for i in range(5)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(quote_path, (stamp, stamp))
        return instance_dir, quote_path

    def test_a_none_table_is_never_marked_and_is_counted_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance_dir, quote_path = self._mixed_instance(tmp_path)
        monkeypatch.setattr(
            ingest_cli_module, "read_feather_coalesced", lambda fs, path, **kw: None
        )

        results = run_ingest(
            tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{quote_path.name}").exists()
        assert "failed=1" in results[0].type_results[0].outcome
        assert results[0].outcome == "failed"

    def test_a_post_transform_empty_table_with_nonzero_rows_is_never_marked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance_dir, quote_path = self._mixed_instance(tmp_path)

        def _empty_transform(table: pa.Table, **kwargs: Any) -> pa.Table:
            return table.slice(0, 0)

        monkeypatch.setattr(
            ParquetDataCatalog,
            "_apply_stream_conversion_transforms",
            staticmethod(_empty_transform),
        )

        results = run_ingest(
            tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{quote_path.name}").exists()
        assert "failed=1" in results[0].type_results[0].outcome
        assert results[0].outcome == "failed"


class TestAnUnclosedIntactFileWhileLiveIsNeverConvertedPerFile:
    """Review item 2 (round 2 semantics pin): a message-boundary-clean read
    with no end-of-stream marker is byte-identical to a live writer paused
    mid-stream -- untrustworthy ONLY while a writer for it could still
    exist, i.e. while its instance is not yet confirmed ``instance_is_dead``
    (see the module docstring's "Per-file conversion" section). This class
    pins the LIVE half; :class:`TestANoEosFileInADeadInstanceIsConverted`
    pins the DEAD half that GL-14/BL-24's original per-file path got wrong.
    """

    def test_without_eos_the_file_is_left_unmarked_while_the_instance_is_live(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        unclosed_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "quote_tick_1.feather"
        _write_typed_ipc_stream(
            unclosed_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=False
        )
        _write_typed_ipc_stream(
            open_path, [_quote_tick(100 + i) for i in range(3)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(unclosed_path, (stamp, stamp))
        # `open_path` stays at "now", AND the recorder is reported active for
        # this, the only (hence newest-started) instance -- genuinely LIVE,
        # not merely "this one file looks fresh".

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=lambda: True,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{unclosed_path.name}").exists()
        assert "skipped-unclosed=1" in results[0].type_results[0].outcome

    def test_with_eos_the_file_is_converted(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        closed_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "trade_tick_0.feather"
        _write_typed_ipc_stream(
            closed_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_trade_tick(i) for i in range(3)], TradeTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(closed_path, (stamp, stamp))

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick, TradeTick),
            service_active_probe=_never_active,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 10
        assert (instance_dir / f"{FILE_MARKER_PREFIX}{closed_path.name}").is_file()
        assert "converted=1" in results[0].type_results[0].outcome


class TestUnreadableIsNeverReportedAsSalvaged:
    """Review item 4: only TRUNCATED files are handed to
    ``salvage_truncated_instance``; an UNREADABLE file must never claim
    salvage activity that did not run.
    """

    def test_an_unreadable_sibling_is_counted_separately_from_salvage(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        unreadable_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "trade_tick_0.feather"
        _write_typed_ipc_stream(
            unreadable_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_trade_tick(i) for i in range(3)], TradeTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(unreadable_path, (stamp, stamp))
        unreadable_path.chmod(0o000)
        try:
            results = run_ingest(
                tmp_path,
                data_types=(QuoteTick, TradeTick),
                service_active_probe=_never_active,
            )
        finally:
            unreadable_path.chmod(0o600)

        outcomes = {r.data_cls: r.outcome for r in results[0].type_results}
        assert "unreadable=1" in outcomes[QuoteTick]
        assert "salvaged" not in outcomes[QuoteTick]
        assert "would-salvage" not in outcomes[QuoteTick]
        # unreadable is never truncated, so `salvage_truncated_instance` sees
        # nothing for this instance and the run is not reported quarantined.
        assert not (instance_dir / f".salvaged-{unreadable_path.name}").exists()


class TestDefinitionsAlwaysConvertBeforeTicks:
    """Review item 5: a tick row must never land before the instrument
    definition it references.
    """

    def test_an_open_definition_defers_every_tick_type_this_run(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        binary_path = _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_0.feather", [_binary_option("MKT-A", T0)],
            age_minutes=0.0,
        )
        quote_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(quote_path, (stamp, stamp))

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick, BinaryOption),
            service_active_probe=_never_active,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{quote_path.name}").exists()
        outcomes = {r.data_cls: r.outcome for r in results[0].type_results}
        assert outcomes[QuoteTick] == "skipped-definitions-pending"
        assert binary_path.exists()  # untouched, still open, retried next run

    def test_once_the_definition_closes_both_convert_and_definition_lands_first(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_0.feather", [_binary_option("MKT-A", T0)]
        )
        quote_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(quote_path, (stamp, stamp))

        # A sibling open file keeps this a per-file-path instance so the
        # ordering guarantee under test is the one actually exercised.
        _write_typed_ipc_stream(
            instance_dir / "trade_tick_0.feather", [_trade_tick(0)], TradeTick, close=False
        )

        run_ingest(
            tmp_path,
            data_types=(QuoteTick, BinaryOption, TradeTick),
            service_active_probe=_never_active,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 10
        assert len(_catalog_definitions(tmp_path)) == 1

        definition_files = _parquet_files(tmp_path)
        quote_files = sorted((tmp_path / "data" / "quote_tick").rglob("*.parquet"))
        assert definition_files and quote_files
        assert max(p.stat().st_mtime for p in definition_files) <= min(
            p.stat().st_mtime for p in quote_files
        )


class TestWholeInstanceDeadPathAndNoEosSemantics:
    """Review item 1 (round 2): pin exactly when a no-EOS, message-boundary
    -clean file is safe for the whole-instance dead path to convert via the
    native ``convert_stream_to_data`` call, which has no EOS concept at all.
    Safe if and only if the file's OWN instance is dead: not the
    most-recently-started instance while the recorder is active, or the
    recorder unit is confirmed inactive.
    """

    def test_the_newest_active_instances_no_eos_file_is_never_converted(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        lone_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            lone_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(lone_path, (stamp, stamp))  # stale mtime, no other open sibling

        results = run_ingest(
            tmp_path, data_types=(QuoteTick,), service_active_probe=lambda: True
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{lone_path.name}").exists()
        assert not (instance_dir / ".converted-quote_tick").exists()
        # the "dead" predicate must be False for the newest active instance --
        # it is still treated live overall, exactly like a fresh file would be.
        assert results[0].outcome == "skipped-live"

    def test_a_non_newest_instances_no_eos_file_is_converted_by_the_dead_path(
        self, tmp_path: Path
    ) -> None:
        old_dir = tmp_path / "live" / INSTANCE
        old_path = old_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            old_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=False
        )
        old_stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 20) * 60
        os.utime(old_path, (old_stamp, old_stamp))

        # OTHER_INSTANCE is newer and fresh -- makes `INSTANCE` provably
        # non-newest regardless of the recorder's own active/inactive state.
        _touch(tmp_path, OTHER_INSTANCE, "quote_tick_0.feather")

        results = run_ingest(
            tmp_path, data_types=(QuoteTick,), service_active_probe=lambda: True
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 10
        assert (old_dir / ".converted-quote_tick").is_file()
        by_instance = {r.instance_id: r for r in results}
        assert by_instance[INSTANCE].outcome == "converted"

    def test_an_inactive_recorder_no_eos_file_is_converted_by_the_dead_path(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        lone_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            lone_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(lone_path, (stamp, stamp))

        results = run_ingest(
            tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 10
        assert (instance_dir / ".converted-quote_tick").is_file()
        assert results[0].outcome == "converted"


class TestExitCodeReflectsAHardConversionFailure:
    """Review item 2: EXIT_OK must not be returned when any instance's
    outcome is "failed" -- skips still exit 0, only a real failure exits
    EXIT_CONVERSION_FAILED.
    """

    def test_a_failed_outcome_exits_conversion_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "quote_tick_1.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_quote_tick(100 + i) for i in range(5)], QuoteTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(quote_path, (stamp, stamp))
        monkeypatch.setattr(
            ingest_cli_module, "read_feather_coalesced", lambda fs, path, **kw: None
        )

        out, err = io.StringIO(), io.StringIO()
        code = run(
            [], env={CATALOG_ENV_VAR: str(tmp_path)}, stdout=out, stderr=err
        )

        assert code == EXIT_CONVERSION_FAILED
        assert "failed=1" in out.getvalue()

    def test_a_skipped_live_outcome_still_exits_ok(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_1.feather", age_minutes=0.0)

        out, err = io.StringIO(), io.StringIO()
        code = run([], env={CATALOG_ENV_VAR: str(tmp_path)}, stdout=out, stderr=err)

        assert code == EXIT_OK

    def test_a_skipped_truncated_outcome_still_exits_ok(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        tape = instance_dir / "quote_tick_0.feather"
        instance_dir.mkdir(parents=True, exist_ok=True)
        tape.write_bytes(b"ARROW1\x00\x00garbage-not-a-real-stream")
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(tape, (stamp, stamp))

        out, err = io.StringIO(), io.StringIO()
        code = run([], env={CATALOG_ENV_VAR: str(tmp_path)}, stdout=out, stderr=err)

        assert code == EXIT_OK


class TestAMissingPreflightReportIsNeverSilent:
    """Review item 3: a file present on disk but absent from the preflight
    snapshot (a scan/enumeration race) must never be silently skipped.
    """

    def test_a_file_omitted_from_the_preflight_snapshot_is_warned_and_uncounted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        open_path = instance_dir / "trade_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            open_path, [_trade_tick(i) for i in range(3)], TradeTick, close=False
        )
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        os.utime(quote_path, (stamp, stamp))

        real_scan_instance = ingest_cli_module.scan_instance

        def _drop_quote_report(catalog_root: Path, instance_id: str, subdirectory: str) -> Any:
            report = real_scan_instance(catalog_root, instance_id, subdirectory)
            return dataclasses.replace(
                report, files=tuple(f for f in report.files if f.path != quote_path)
            )

        monkeypatch.setattr(ingest_cli_module, "scan_instance", _drop_quote_report)

        with caplog.at_level(logging.WARNING, logger="breezy.runtime.quote_tape_ingest_cli"):
            results = run_ingest(
                tmp_path,
                data_types=(QuoteTick, TradeTick),
                service_active_probe=_never_active,
            )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert not (instance_dir / f"{FILE_MARKER_PREFIX}{quote_path.name}").exists()
        outcomes = {r.data_cls: r.outcome for r in results[0].type_results}
        assert "unreported=1" in outcomes[QuoteTick]
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "no preflight report" in messages


class TestANoEosFileInADeadInstanceIsConverted:
    """Round-3 stranded-instance fix: a reboot-killed instance can have MOST
    of its rotated files lacking an EOS marker while ALSO carrying an
    unrelated truncated file for a different type -- neither the missing
    EOS marker nor the truncated sibling may strand a file that is
    genuinely safe to trust once the instance itself is confirmed dead.
    """

    def test_dead_instance_converts_no_eos_quotes_despite_a_truncated_sibling(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        trade_path = instance_dir / "trade_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=False
        )
        _write_typed_ipc_stream(
            trade_path, [_trade_tick(i) for i in range(20)], TradeTick, close=False
        )
        _truncate_tail(trade_path)
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        for path in (quote_path, trade_path):
            os.utime(path, (stamp, stamp))

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick, TradeTick),
            service_active_probe=_never_active,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        # the no-EOS QuoteTick file converted despite lacking EOS -- the
        # instance itself is confirmed dead (recorder inactive).
        assert len(catalog.query(data_cls=QuoteTick)) == 10
        assert (instance_dir / f"{FILE_MARKER_PREFIX}{quote_path.name}").is_file()

        # the truncated TradeTick sibling was salvaged, not silently dropped
        # and not left blocking QuoteTick.
        recovered = catalog.query(data_cls=TradeTick)
        assert 0 < len(recovered) < 20
        assert (instance_dir / f".salvaged-{trade_path.name}").is_file()

        # the instance is still reported quarantined -- TradeTick remains
        # truncated -- even though the QuoteTick rows landed underneath.
        assert results[0].outcome == "skipped-truncated"

    def test_dead_instance_empty_sibling_files_never_block_and_are_marked(
        self, tmp_path: Path
    ) -> None:
        """Confirms item 4 of the round-3 review: 0-byte EMPTY_FILE entries
        (the writer's placeholder for a type that never captured anything
        this run) never block tick conversion, and land in their own
        ``converted-nothing-new`` bucket, per file, regardless of the
        instance being dead or the truncated sibling elsewhere.
        """
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        trade_path = instance_dir / "trade_tick_0.feather"
        empty_path = instance_dir / "instrument_close_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=False
        )
        _write_typed_ipc_stream(
            trade_path, [_trade_tick(i) for i in range(20)], TradeTick, close=False
        )
        _truncate_tail(trade_path)
        empty_path.parent.mkdir(parents=True, exist_ok=True)
        empty_path.touch()
        stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
        for path in (quote_path, trade_path, empty_path):
            os.utime(path, (stamp, stamp))

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick, TradeTick, InstrumentClose),
            service_active_probe=_never_active,
        )

        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 10
        outcomes = {r.data_cls: r.outcome for r in results[0].type_results}
        assert "converted-nothing-new=1" in outcomes[InstrumentClose]
        assert (instance_dir / f"{FILE_MARKER_PREFIX}{empty_path.name}").is_file()
