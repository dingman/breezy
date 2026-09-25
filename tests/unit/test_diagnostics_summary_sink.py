"""F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): `DiagnosticsSummarySink` and
`delta`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from breezy.strategy.current_rung_hold.diagnostics_summary import (
    DiagnosticsSummarySink,
    delta,
)


class TestDelta:
    def test_empty_previous_returns_the_current_values(self) -> None:
        assert delta({}, {"a": 3, "b": 1}) == {"a": 3, "b": 1}

    def test_computes_the_increase_since_the_last_emission(self) -> None:
        assert delta({"a": 3, "b": 1}, {"a": 5, "b": 1}) == {"a": 2, "b": 0}

    def test_a_key_absent_from_previous_is_its_full_current_value(self) -> None:
        assert delta({"a": 3}, {"a": 3, "c": 2}) == {"a": 0, "c": 2}

    def test_never_returns_negative(self) -> None:
        """A decreasing counter would be a coding bug upstream, not a valid
        delta -- clamp rather than propagate a negative row field."""
        assert delta({"a": 9}, {"a": 3}) == {"a": 0}


class TestDiagnosticsSummarySinkAppend:
    def test_two_sink_instances_one_file_rows_intact_and_attributable(
        self, tmp_path: Path
    ) -> None:
        """A5: two 'processes' (two sink instances over the same path, the
        shape a restart mid-hour leaves) both append cleanly -- rows stay
        intact and attributable by their own pid/boot_ns fields (written by
        the caller, not this sink)."""
        path = tmp_path / "diagnostics_summary_2026-09-25.jsonl"
        sink_a = DiagnosticsSummarySink(path)
        sink_a.append({"pid": 111, "boot_ns": 1, "hour_utc_start_ns": 0})
        sink_b = DiagnosticsSummarySink(path)
        sink_b.append({"pid": 222, "boot_ns": 2, "hour_utc_start_ns": 3600})

        lines = path.read_text().splitlines()
        rows = [json.loads(line) for line in lines]
        assert [row["pid"] for row in rows] == [111, 222]

    def test_cap_and_resume(self, tmp_path: Path) -> None:
        path = tmp_path / "diagnostics_summary_2026-09-25.jsonl"
        row = {"pid": 1, "hour_utc_start_ns": 0, "diagnostics": {"x": 1}}
        row_bytes = len(json.dumps(row, sort_keys=True).encode("utf-8")) + 1
        sink = DiagnosticsSummarySink(path, max_bytes=row_bytes)

        sink.append(row)
        sink.append(row)  # over the cap -- dropped from disk only

        assert len(path.read_text().splitlines()) == 1
        assert sink.capped == 1

        # A fresh instance over the same path resumes the cap from the REAL
        # on-disk size rather than re-zeroing it.
        resumed = DiagnosticsSummarySink(path, max_bytes=row_bytes)
        resumed.append(row)
        assert resumed.capped == 1
        assert len(path.read_text().splitlines()) == 1

    def test_unwritable_dir_in_memory_only(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory")
        path = blocker / "diagnostics_summary_2026-09-25.jsonl"

        sink = DiagnosticsSummarySink(path)
        sink.append({"pid": 1})  # never raises

        assert sink.errors >= 1
        assert not blocker.is_dir()

    def test_append_with_no_path_configured_never_raises(self) -> None:
        sink = DiagnosticsSummarySink(None)
        sink.append({"pid": 1})
        assert sink.errors == 0
        assert sink.capped == 0

    def test_negative_max_bytes_rejected(self) -> None:
        with pytest.raises(ValueError):
            DiagnosticsSummarySink(None, max_bytes=0)
