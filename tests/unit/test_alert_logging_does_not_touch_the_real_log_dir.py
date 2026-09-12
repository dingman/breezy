"""RED/GREEN coverage for the L-27 session-wide guard (SP-6 B3) added to
``tests/conftest.py``.

The guard is offset-based rather than size/mtime-based: a naive
byte-identical check is guaranteed RED on this host because the LIVE trade
node and supervisor append to files under the real
``~/.local/share/breezy/logs/`` throughout any multi-minute gate run. These
tests exercise the guard's pure, injectable primitives (and the
context-manager that wires them together) against a ``tmp_path`` stand-in
directory -- never the real one -- so a genuine test-write leak is caught
while a concurrent real writer's appended bytes stay green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    _TEST_SENTINEL_SUBSTRINGS,
    _log_dir_snapshot,
    _log_dir_untouched_guard,
    find_test_sentinel_leaks,
    find_unexpected_new_files,
)

_SENTINEL = _TEST_SENTINEL_SUBSTRINGS[0]


def test_a_planted_write_is_caught(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    target = log_dir / "breezy-trade-supervisor.log"
    target.write_text("2026-09-12T00:00:00Z self_check result=PASS\n")
    before = _log_dir_snapshot(log_dir)

    with target.open("a") as fh:
        fh.write(f"leaked test content referencing {_SENTINEL}\n")

    leaks = find_test_sentinel_leaks(log_dir, before)
    assert leaks == {"breezy-trade-supervisor.log": _SENTINEL}


def test_a_concurrent_append_by_a_real_writer_is_green(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    target = log_dir / "breezy-trade-supervisor.log"
    target.write_text("2026-09-12T00:00:00Z self_check result=PASS\n")
    before = _log_dir_snapshot(log_dir)

    with target.open("a") as fh:
        fh.write("2026-09-12T00:05:00Z self_check result=PASS pid=895135\n")

    assert find_test_sentinel_leaks(log_dir, before) == {}
    assert find_unexpected_new_files(log_dir, before) == []


def test_a_truncated_file_is_rebaselined_not_failed(tmp_path: Path) -> None:
    """AM-17: a pre-existing file whose size at teardown is SMALLER than
    its recorded offset (rotation/truncation) is re-baselined -- the whole
    current file is scanned for sentinels, and a shrink alone is never
    itself a leak."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    target = log_dir / "breezy-trade-supervisor.log"
    target.write_text("real production content\n" * 20)
    before = _log_dir_snapshot(log_dir)

    # Rotation: truncate to a short, clean, brand-new-looking file.
    target.write_text("2026-09-12T00:10:00Z self_check result=PASS\n")

    assert find_test_sentinel_leaks(log_dir, before) == {}


def test_a_truncated_file_still_catches_a_sentinel_in_the_rebaselined_scan(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    target = log_dir / "breezy-trade-supervisor.log"
    target.write_text("real production content\n" * 20)
    before = _log_dir_snapshot(log_dir)

    target.write_text(f"short file mentioning {_SENTINEL}\n")

    leaks = find_test_sentinel_leaks(log_dir, before)
    assert leaks == {"breezy-trade-supervisor.log": _SENTINEL}


def test_a_new_file_matching_the_node_log_convention_is_not_flagged(
    tmp_path: Path,
) -> None:
    """The live node mints a brand-new ``breezy-trade-<stamp>.log`` on
    every relaunch -- that exact shape is legitimate production behaviour
    and must never be flagged as a leak."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    before = _log_dir_snapshot(log_dir)

    (log_dir / "breezy-trade-20260912T165000Z.log").write_text("boot\n")

    assert find_unexpected_new_files(log_dir, before) == []


def test_a_new_file_is_caught(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    before = _log_dir_snapshot(log_dir)

    (log_dir / "unexpected-test-artifact.log").write_text("leaked\n")

    assert find_unexpected_new_files(log_dir, before) == [
        "unexpected-test-artifact.log"
    ]


def test_the_guard_context_raises_when_a_leak_is_planted_inside_it(
    tmp_path: Path,
) -> None:
    """End-to-end exercise of the exact primitive the session fixture
    wraps (``_real_log_dir_untouched`` in ``tests/conftest.py``), against a
    ``tmp_path`` stand-in -- never the real directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "breezy-trade-supervisor.log").write_text("clean\n")

    with (
        pytest.raises(AssertionError),
        _log_dir_untouched_guard(log_dir),
        (log_dir / "breezy-trade-supervisor.log").open("a") as fh,
    ):
        fh.write(f"leak {_SENTINEL}\n")


def test_the_guard_context_is_green_for_a_plain_concurrent_append(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "breezy-trade-supervisor.log").write_text("clean\n")

    with (
        _log_dir_untouched_guard(log_dir),
        (log_dir / "breezy-trade-supervisor.log").open("a") as fh,
    ):
        fh.write("2026-09-12T00:05:00Z self_check result=PASS pid=895135\n")


def test_a_sentinel_in_a_new_node_shaped_file_is_still_caught(tmp_path: Path) -> None:
    """Coordinator review NB1: a NEW file exempted by NAME from
    ``find_unexpected_new_files`` (the node-log timestamp shape) must
    still have its CONTENT sentinel-scanned -- exempting the shape must
    never also exempt a leak written into it."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    before = _log_dir_snapshot(log_dir)

    node_shaped = log_dir / "breezy-trade-20260912T165000Z.log"
    node_shaped.write_text(f"boot line referencing {_SENTINEL}\n")

    # The name-based check still correctly treats this as legitimate.
    assert find_unexpected_new_files(log_dir, before) == []

    # But the content-based check must NOT be blind to it.
    leaks = find_test_sentinel_leaks(log_dir, before)
    assert leaks == {"breezy-trade-20260912T165000Z.log": _SENTINEL}
