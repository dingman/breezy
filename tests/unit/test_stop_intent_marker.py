"""AUD-13d HIGH-1: the Breezy-owned stop-intent marker.

Pure file-I/O unit tests -- no Nautilus, no process, no signal. Every test
below injects a fake ``process_start_ticks``/``now`` so nothing depends on
real ``/proc`` state for an arbitrary test pid.
"""

from __future__ import annotations

import inspect
import logging
import time
from pathlib import Path

import pytest

from breezy.runtime.stop_intent_marker import (
    _process_start_ticks,
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
# [2026-09-24 review, nit (a)] `time.monotonic()` is `CLOCK_MONOTONIC`-backed
# on Linux -- a single system-wide clock, so two DIFFERENT processes reading
# it on the SAME boot get comparable values (Python docs for
# `time.monotonic`; `clock_gettime(2)`). That does NOT make it safe here: it
# resets to (near) 0 at every boot, and so does `/proc/<pid>/stat`'s
# starttime field (`_process_start_ticks`) -- a genuine host reboot landing
# in the write-to-consume window is exactly the case where BOTH clocks reset
# together, so a monotonic age check could read a stale marker as fresh
# (small/negative `now() - written_at`) instead of failing closed. Wall-clock
# `time.time()` keeps advancing across a reboot, so it is kept. This test
# pins that decision in code so a future refactor can't silently swap it.
# ---------------------------------------------------------------------------


def test_the_default_clock_is_wall_clock_time_not_monotonic() -> None:
    write_sig = inspect.signature(write_stop_intent_marker)
    consume_sig = inspect.signature(consume_stop_intent_marker)

    assert write_sig.parameters["now"].default is time.time
    assert consume_sig.parameters["now"].default is time.time


# ---------------------------------------------------------------------------
# [2026-09-24 review, nit (c)] `_process_start_ticks` splits `/proc/<pid>/stat`
# after the LAST `)` because `comm` (field 2) is parenthesized and may itself
# contain spaces or parentheses.
# ---------------------------------------------------------------------------


def test_process_start_ticks_parses_a_comm_containing_spaces_and_parens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = 987654
    stat_path = Path(f"/proc/{pid}/stat")
    # Fields 3 (state) .. 22 (starttime) verbatim, matching the real kernel
    # layout -- only `comm` (field 2) is synthetic/adversarial.
    trailing_fields = [
        "S", "1", "12345", "12345", "0", "-1", "4194304", "100", "0", "0",
        "0", "10", "5", "0", "0", "20", "0", "4", "0", "987654321",
    ]
    synthetic_line = f"{pid} (my (weird) proc name) " + " ".join(trailing_fields)
    real_read_text = Path.read_text

    def _fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == stat_path:
            return synthetic_line
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _fake_read_text)

    assert _process_start_ticks(pid) == 987654321


def test_process_start_ticks_returns_none_when_proc_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = 987655
    stat_path = Path(f"/proc/{pid}/stat")
    real_read_text = Path.read_text

    def _fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == stat_path:
            raise OSError("synthetic: no such process")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _fake_read_text)

    assert _process_start_ticks(pid) is None


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
