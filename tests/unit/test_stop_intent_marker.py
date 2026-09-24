"""AUD-13d HIGH-1: the Breezy-owned stop-intent marker.

Pure file-I/O unit tests -- no Nautilus, no process, no signal. Every test
below injects a fake ``process_start_ticks``/``now`` so nothing depends on
real ``/proc`` state for an arbitrary test pid.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from breezy.runtime.stop_intent_marker import (
    consume_stop_intent_marker,
    discard_stop_intent_marker,
    stop_intent_marker_path,
    write_stop_intent_marker,
)

_FIXED_START_TICKS = 123456


def _fixed_ticks(_pid: int) -> int:
    return _FIXED_START_TICKS


def test_marker_path_sits_beside_the_store_with_a_distinct_suffix(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    marker_path = stop_intent_marker_path(store_path)

    assert marker_path.parent == store_path.parent
    assert marker_path.name == "exec-state.db.stop_intent"
    assert marker_path != store_path


def test_a_written_marker_naming_this_pid_and_incarnation_is_consumed_as_true(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "exec-state.db"

    write_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    assert (
        consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks) is True
    )


def test_consuming_the_marker_deletes_it(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    assert not stop_intent_marker_path(store_path).exists()


def test_a_second_consume_after_the_first_reports_false(tmp_path: Path) -> None:
    """Single-use: a stale marker must never suppress a LATER, unrelated halt."""
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    first = consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)
    second = consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    assert first is True
    assert second is False


def test_a_marker_naming_a_different_pid_is_not_a_match(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 111, process_start_ticks=_fixed_ticks)

    assert consume_stop_intent_marker(store_path, 222, process_start_ticks=_fixed_ticks) is False


def test_a_mismatched_marker_is_still_consumed_deleted(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 111, process_start_ticks=_fixed_ticks)

    consume_stop_intent_marker(store_path, 222, process_start_ticks=_fixed_ticks)

    assert not stop_intent_marker_path(store_path).exists()


def test_no_marker_at_all_fails_closed_to_false(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"

    assert consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks) is False


def test_a_corrupt_marker_fails_closed_to_false_and_is_still_removed(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    marker_path = stop_intent_marker_path(store_path)
    marker_path.write_text("not json{{{")

    result = consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    assert result is False
    assert not marker_path.exists()


def test_write_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"

    write_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    leftovers = [p for p in tmp_path.iterdir() if ".tmp." in p.name]
    assert leftovers == []


def test_write_to_an_unwritable_directory_does_not_raise(tmp_path: Path) -> None:
    store_path = tmp_path / "does" / "not" / "exist" / "exec-state.db"

    write_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)  # must not raise

    assert consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks) is False


# ---------------------------------------------------------------------------
# [2026-09-24 review, HIGH] pid-reuse hardening: a bare pid match is not
# enough. A marker binds the target's `/proc` start time; a later, unrelated
# process assigned the SAME pid must never match.
# ---------------------------------------------------------------------------


def test_write_skips_entirely_when_the_target_start_time_is_unreadable(tmp_path: Path) -> None:
    """The target died between the caller's TOCTOU recheck and this call --
    nothing is written, rather than a marker with no bound identity."""
    store_path = tmp_path / "exec-state.db"

    write_stop_intent_marker(store_path, 4242, process_start_ticks=lambda _pid: None)

    assert not stop_intent_marker_path(store_path).exists()


def test_a_marker_for_a_pid_reused_by_a_different_incarnation_is_not_a_match(
    tmp_path: Path,
) -> None:
    """Same pid, DIFFERENT start ticks -- the kernel reused the pid for an
    unrelated later process. That process's own genuine boot halt must not
    be silenced by a marker meant for its predecessor."""
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242, process_start_ticks=lambda _pid: 111)

    result = consume_stop_intent_marker(store_path, 4242, process_start_ticks=lambda _pid: 999)

    assert result is False


def test_a_reused_pid_mismatch_is_still_consumed_deleted(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242, process_start_ticks=lambda _pid: 111)

    consume_stop_intent_marker(store_path, 4242, process_start_ticks=lambda _pid: 999)

    assert not stop_intent_marker_path(store_path).exists()


def test_a_marker_older_than_the_max_age_is_not_a_match(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    clock = {"t": 1_000_000.0}
    write_stop_intent_marker(
        store_path, 4242, now=lambda: clock["t"], process_start_ticks=_fixed_ticks
    )

    clock["t"] += 301.0  # one second past the 300s max age

    result = consume_stop_intent_marker(
        store_path,
        4242,
        now=lambda: clock["t"],
        process_start_ticks=_fixed_ticks,
        max_age_seconds=300.0,
    )

    assert result is False


def test_a_marker_within_the_max_age_is_still_a_match(tmp_path: Path) -> None:
    """Positive control for the max-age test above: a fresh marker, same
    pid and incarnation, matches -- the age check alone is not what fails
    the stale case."""
    store_path = tmp_path / "exec-state.db"
    clock = {"t": 1_000_000.0}
    write_stop_intent_marker(
        store_path, 4242, now=lambda: clock["t"], process_start_ticks=_fixed_ticks
    )

    clock["t"] += 1.0

    result = consume_stop_intent_marker(
        store_path,
        4242,
        now=lambda: clock["t"],
        process_start_ticks=_fixed_ticks,
        max_age_seconds=300.0,
    )

    assert result is True


# ---------------------------------------------------------------------------
# discard_stop_intent_marker -- used when the signal a marker corroborates
# never actually landed.
# ---------------------------------------------------------------------------


def test_discard_removes_an_existing_marker(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    discard_stop_intent_marker(store_path)

    assert not stop_intent_marker_path(store_path).exists()


def test_discard_is_a_noop_when_no_marker_exists(tmp_path: Path) -> None:
    store_path = tmp_path / "exec-state.db"

    discard_stop_intent_marker(store_path)  # must not raise

    assert not stop_intent_marker_path(store_path).exists()


# ---------------------------------------------------------------------------
# [2026-09-24 review, LOW] consume must LOG an unlink failure, matching the
# write side's own convention -- not swallow it silently.
# ---------------------------------------------------------------------------


def test_consume_logs_when_the_marker_cannot_be_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store_path = tmp_path / "exec-state.db"
    write_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)
    marker_path = stop_intent_marker_path(store_path)
    real_unlink = Path.unlink

    def _boom(self: Path, *args: object, **kwargs: object) -> None:
        if self == marker_path:
            raise OSError("synthetic unlink failure")
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _boom)
    caplog.set_level(logging.ERROR, logger="breezy.runtime.stop_intent_marker")

    result = consume_stop_intent_marker(store_path, 4242, process_start_ticks=_fixed_ticks)

    # The removal failure is logged, but never changes the match outcome --
    # this mirrors the write side's own "log and swallow" convention.
    assert result is True
    assert "stop-intent marker could not be removed" in caplog.text
