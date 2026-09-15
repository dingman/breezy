"""RED-first tests for `MarkBuffer` and the monitor summary store (INC-4).

Per `docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md` Sec 6 INC-4 and Rev
2.1 addendum A2 (per-climate-day catalog partitioning).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.persistence.catalog import CatalogWriteError
from breezy.strategy.current_rung_hold import monitor_store
from breezy.strategy.current_rung_hold.monitor_records import (
    PositionMarkRecord,
    PositionMonitorSummary,
)
from breezy.strategy.current_rung_hold.monitor_store import (
    MarkBuffer,
    open_monitor_catalog,
    read_monitor_summaries,
    write_monitor_summaries,
)

_INSTRUMENT_ID = InstrumentId.from_str("sfo-86-87.POLYMARKET_US")


def _mark_record(**overrides: object) -> PositionMarkRecord:
    base: dict[str, object] = {
        "instrument_id": _INSTRUMENT_ID,
        "station": "SFO",
        "climate_day": "2026-09-01",
        "leg": "YES",
        "entry_context": "live",
        "thesis_state": "ALIVE",
        "verdict": "HOLD",
        "mark_vwap": Decimal("0.62"),
        "mark_source": "depth_walk",
        "unrealized_pnl": Decimal("1.50"),
        "recoverable_value": Decimal("0.60"),
        "running_max_lower": Decimal(80),
        "running_max_upper": Decimal(84),
        "staleness_ns": 5_000_000_000,
        "book_staleness_ns": 2_000_000_000,
        "held_qty": Decimal(1),
        "reason_codes": (),
        "ts_event": 1_700_000_000_000_000_000,
        "ts_init": 1_700_000_000_500_000_000,
    }
    base.update(overrides)
    return PositionMarkRecord(**base)  # type: ignore[arg-type]


def _summary(**overrides: object) -> PositionMonitorSummary:
    base: dict[str, object] = {
        "trial_id": "continuous_rung_hold/trial/SFO/2026-09-01/sfo-86-87.POLYMARKET_US",
        "instrument_id": "sfo-86-87.POLYMARKET_US",
        "station": "SFO",
        "climate_day": "2026-09-01",
        "leg": "YES",
        "entry_context": "live",
        "monitor_seq": 1,
        "fill_px": Decimal("0.55"),
        "held_qty": Decimal(1),
        "mae": Decimal("0.10"),
        "mfe": Decimal("0.25"),
        "first_signal_ts_ns": None,
        "first_signal_hour_lst": None,
        "first_signal_state": None,
        "verdict_at_signal": None,
        "recoverable_value_at_signal": None,
        "held_duration_ns": 3_600_000_000_000,
        "total_frames": 42,
        "mark_missing_frames": 3,
        "settled_pnl": None,
        "settled_held": None,
    }
    base.update(overrides)
    return PositionMonitorSummary(**base)  # type: ignore[arg-type]


class TestMarkBufferBounding:
    def test_the_bounded_deque_drops_the_oldest_record_and_counts_it(self) -> None:
        buf = MarkBuffer(maxlen=3)
        for i in range(5):
            buf.append(_mark_record(reason_codes=(f"r{i}",)))

        assert len(buf) == 3
        assert buf.dropped == 2
        assert [record.reason_codes for record in buf.records()] == [
            ("r2",),
            ("r3",),
            ("r4",),
        ]

    def test_a_buffer_within_capacity_drops_nothing(self) -> None:
        buf = MarkBuffer(maxlen=10)
        buf.append(_mark_record())

        assert len(buf) == 1
        assert buf.dropped == 0

    def test_should_flush_is_true_once_the_threshold_is_reached(self) -> None:
        buf = MarkBuffer(maxlen=monitor_store.MARK_BUFFER_FLUSH_THRESHOLD + 1)
        for _ in range(monitor_store.MARK_BUFFER_FLUSH_THRESHOLD - 1):
            buf.append(_mark_record())
        assert buf.should_flush() is False

        buf.append(_mark_record())
        assert buf.should_flush() is True


class TestMarkBufferSidecar:
    def test_a_sidecar_write_error_is_swallowed_and_counted(self, tmp_path: Path) -> None:
        """`tmp_path` itself is a directory: opening it for append raises
        `IsADirectoryError`, an `OSError` subclass, exactly like an
        unwritable disk path would in production."""
        buf = MarkBuffer(sidecar_path=tmp_path)

        buf.append(_mark_record())

        assert len(buf) == 1
        assert buf.sidecar_errors == 1

    def test_a_working_sidecar_never_increments_the_error_counter(self, tmp_path: Path) -> None:
        buf = MarkBuffer(sidecar_path=tmp_path / "marks.jsonl")

        buf.append(_mark_record())

        assert buf.sidecar_errors == 0
        assert (tmp_path / "marks.jsonl").exists()


class TestMarkBufferFlush:
    def test_flush_writes_all_pending_records_in_one_batched_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = MarkBuffer()
        for i in range(5):
            buf.append(_mark_record(reason_codes=(f"r{i}",)))

        real_write_records = monitor_store.write_records
        calls: list[int] = []

        def spy(catalog: object, records: object) -> object:
            calls.append(len(records))  # type: ignore[arg-type]
            return real_write_records(catalog, records)  # type: ignore[arg-type]

        monkeypatch.setattr(monitor_store, "write_records", spy)

        written = buf.flush(tmp_path, "2026-09-01")

        assert calls == [5]
        assert written == 5
        assert len(buf) == 0

    def test_flush_with_nothing_pending_is_a_no_op(self, tmp_path: Path) -> None:
        buf = MarkBuffer()

        assert buf.flush(tmp_path, "2026-09-01") == 0

    def test_flush_failure_keeps_records_buffered_and_counts_the_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = MarkBuffer()
        buf.append(_mark_record())

        def boom(catalog: object, records: object) -> object:
            raise CatalogWriteError("simulated read-back mismatch")

        monkeypatch.setattr(monitor_store, "write_records", boom)

        written = buf.flush(tmp_path, "2026-09-01")

        assert written == 0
        assert len(buf) == 1
        assert buf.flush_errors == 1

    def test_a_second_flush_after_success_has_nothing_left_to_write(
        self, tmp_path: Path
    ) -> None:
        buf = MarkBuffer()
        buf.append(_mark_record())
        buf.flush(tmp_path, "2026-09-01")

        assert buf.flush(tmp_path, "2026-09-01") == 0


class TestOpenMonitorCatalogPartitioning:
    def test_two_climate_days_get_two_distinct_catalog_roots(self, tmp_path: Path) -> None:
        catalog_a = open_monitor_catalog(tmp_path, "2026-09-01")
        catalog_b = open_monitor_catalog(tmp_path, "2026-09-02")

        assert catalog_a.path != catalog_b.path
        assert Path(catalog_a.path).exists()
        assert Path(catalog_b.path).exists()
        assert Path(catalog_a.path).parent == Path(catalog_b.path).parent

    def test_the_monitor_root_is_never_the_bare_catalog_root(self, tmp_path: Path) -> None:
        catalog = open_monitor_catalog(tmp_path, "2026-09-01")

        assert Path(catalog.path) != tmp_path
        assert "monitor" in Path(catalog.path).parts


class TestMonitorSummaryStore:
    def test_summaries_are_deduped_by_trial_id_keeping_the_max_monitor_seq(
        self, tmp_path: Path
    ) -> None:
        write_monitor_summaries(tmp_path, [_summary(monitor_seq=1)], now_ns=1_000_000_000)
        write_monitor_summaries(tmp_path, [_summary(monitor_seq=2)], now_ns=2_000_000_000)

        rows = read_monitor_summaries(tmp_path)

        assert len(rows) == 1
        assert rows[0].monitor_seq == 2

    def test_distinct_trial_ids_both_survive_the_dedup(self, tmp_path: Path) -> None:
        write_monitor_summaries(
            tmp_path,
            [
                _summary(trial_id="A", monitor_seq=1),
                _summary(trial_id="B", monitor_seq=1),
            ],
            now_ns=1_000_000_000,
        )

        rows = read_monitor_summaries(tmp_path)

        assert {row.trial_id for row in rows} == {"A", "B"}

    def test_an_absent_directory_reads_as_empty_not_an_error(self, tmp_path: Path) -> None:
        assert read_monitor_summaries(tmp_path / "never-written") == ()

    def test_a_write_never_rewrites_an_existing_file(self, tmp_path: Path) -> None:
        first = write_monitor_summaries(tmp_path, [_summary()], now_ns=1_000_000_000)
        second = write_monitor_summaries(tmp_path, [_summary()], now_ns=2_000_000_000)

        assert first != second
        assert first.exists()
        assert second.exists()
