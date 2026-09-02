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
"""

from __future__ import annotations

import io
import os
import time
from collections.abc import Callable
from pathlib import Path

from nautilus_trader.model.data import MarkPriceUpdate, QuoteTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.runtime.quote_tape_ingest_cli import (
    DEFAULT_LIVE_GRACE_MINUTES,
    EXIT_OK,
    EXIT_USAGE,
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
