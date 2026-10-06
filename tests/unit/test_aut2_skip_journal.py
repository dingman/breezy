"""AUT-2 r7 WP5 / sections 3.2.2, 3.7.3: the write-once lock-skip journal and its streak."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from breezy.analysis.labeling.skip_journal import (
    SkipJournalWriteFailed,
    consecutive_skips,
    record_skip,
    run_record_skip,
    skip_is_critical,
)

_H = 3_600_000_000_000
T0 = 1_790_000_000_000_000_000
UNIT = "breezy-label-outcomes"


def test_lock_skip_writes_write_once_journal(tmp_path: Path) -> None:
    record = record_skip(tmp_path, UNIT, "lock", T0, slot_ns=T0 - 5, since_ns=0)

    body = json.loads(record.path.read_text())
    assert body == {
        "schema": "aut2_skip/v1",
        "unit": UNIT,
        "slot_ns": T0 - 5,
        "reason": "lock",
        "consecutive": 1,
    }
    assert stat.S_IMODE(record.path.stat().st_mode) == 0o600
    assert record.path.name == f"{T0}_{UNIT}.json"
    assert "evidence/aut2/skips/" in record.path.as_posix()


def test_second_consecutive_skip_from_journal_is_critical(tmp_path: Path) -> None:
    first = record_skip(tmp_path, UNIT, "lock", T0, slot_ns=T0, since_ns=0)
    second = record_skip(tmp_path, UNIT, "lock", T0 + 6 * _H, slot_ns=T0 + 6 * _H, since_ns=0)

    assert (first.consecutive, second.consecutive) == (1, 2)
    assert skip_is_critical(first.consecutive) is False
    assert skip_is_critical(second.consecutive) is True
    # the count is read from the durable journal, never process memory
    assert consecutive_skips(tmp_path, UNIT, since_ns=0) == 2


def test_marker_after_skip_resets_consecutive(tmp_path: Path) -> None:
    record_skip(tmp_path, UNIT, "lock", T0, slot_ns=T0, since_ns=0)

    after_marker = record_skip(tmp_path, UNIT, "lock", T0 + 2 * _H, slot_ns=T0, since_ns=T0 + _H)

    assert after_marker.consecutive == 1


def test_skip_counts_are_per_unit(tmp_path: Path) -> None:
    record_skip(tmp_path, UNIT, "lock", T0, slot_ns=T0, since_ns=0)

    assert consecutive_skips(tmp_path, "breezy-aut2-reconciliation", since_ns=0) == 0


def test_record_skip_write_failure_exits_nonzero(tmp_path: Path) -> None:
    locked = tmp_path / "ro"
    locked.mkdir(mode=0o700)
    (locked / "evidence").mkdir(mode=0o500)  # a read-only skip directory
    try:
        with pytest.raises(SkipJournalWriteFailed):
            record_skip(locked, UNIT, "lock", T0, slot_ns=T0, since_ns=0)
        code, line = run_record_skip(locked, UNIT, T0, slot_ns=T0, since_ns=0)
    finally:
        os.chmod(locked / "evidence", 0o700)

    assert code == 1 and line == f"AUT2 SKIP_JOURNAL_WRITE_FAILED unit={UNIT}"
    ok_code, ok_line = run_record_skip(tmp_path, UNIT, T0, slot_ns=T0, since_ns=0)
    assert ok_code == 0 and ok_line.startswith("SKIPPED reason=lock")


def test_a_bad_unit_or_reason_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        record_skip(tmp_path, "../x", "lock", T0, slot_ns=T0, since_ns=0)
    with pytest.raises(ValueError):
        record_skip(tmp_path, UNIT, "other", T0, slot_ns=T0, since_ns=0)


def test_write_json_once_refuses_empty_parts(tmp_path: Path) -> None:
    from breezy.analysis.labeling.skip_journal import write_json_once

    with pytest.raises(ValueError, match="parts"):
        write_json_once(tmp_path, (), {"a": 1})
