"""AUD-13d HIGH-1: the Breezy-owned stop-intent marker.

Pure file-I/O unit tests -- no Nautilus, no process, no signal.
"""

from __future__ import annotations

from pathlib import Path

from breezy.runtime.stop_intent_marker import (
    consume_stop_intent_marker,
    stop_intent_marker_path,
    write_stop_intent_marker,
)


def test_marker_path_sits_beside_the_store_with_a_distinct_suffix(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    marker_path = stop_intent_marker_path(store_path)

    assert marker_path.parent == store_path.parent
    assert marker_path.name == "exec-state.db.stop_intent"
    assert marker_path != store_path


def test_a_written_marker_naming_this_pid_is_consumed_as_true(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"

    write_stop_intent_marker(store_path, 4242)

    assert consume_stop_intent_marker(store_path, 4242) is True


def test_consuming_the_marker_deletes_it(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242)

    consume_stop_intent_marker(store_path, 4242)

    assert not stop_intent_marker_path(store_path).exists()


def test_a_second_consume_after_the_first_reports_false(tmp_path: Path) -> None:
    """Single-use: a stale marker must never suppress a LATER, unrelated halt."""
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242)

    first = consume_stop_intent_marker(store_path, 4242)
    second = consume_stop_intent_marker(store_path, 4242)

    assert first is True
    assert second is False


def test_a_marker_naming_a_different_pid_is_not_a_match(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 111)

    assert consume_stop_intent_marker(store_path, 222) is False


def test_a_mismatched_marker_is_still_consumed_deleted(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 111)

    consume_stop_intent_marker(store_path, 222)

    assert not stop_intent_marker_path(store_path).exists()


def test_no_marker_at_all_fails_closed_to_false(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"

    assert consume_stop_intent_marker(store_path, 4242) is False


def test_a_corrupt_marker_fails_closed_to_false_and_is_still_removed(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    marker_path = stop_intent_marker_path(store_path)
    marker_path.write_text("not json{{{")

    result = consume_stop_intent_marker(store_path, 4242)

    assert result is False
    assert not marker_path.exists()


def test_write_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"

    write_stop_intent_marker(store_path, 4242)

    leftovers = [p for p in tmp_path.iterdir() if ".tmp." in p.name]
    assert leftovers == []


def test_write_to_an_unwritable_directory_does_not_raise(tmp_path: Path) -> None:
    store_path = tmp_path / "does" / "not" / "exist" / "exec-state.db"

    write_stop_intent_marker(store_path, 4242)  # must not raise

    assert consume_stop_intent_marker(store_path, 4242) is False
