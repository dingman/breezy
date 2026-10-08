"""RED-first tests for the EDGE-6 6f deferral-stall streak state machine.

Plan: `docs/plans/backlog/EDGE_2026-09-27/EDGE-6_ops_reliability_plan_r2_2026-09-27.md`,
r2 final amendment (AM-1/AM-2), §1 6f, §4 6f, §6 6f.

`step()` is pure and independent of a run's exit code (AC-6f-4/C-5) --
these tests drive it directly with a hand-advanced clock. Wiring it into
`quote_tape_ingest_cli.run()` (exit 4, the printed line, the marker-aware
`_instance_has_pending_work` predicate) is covered separately in
`test_quote_tape_ingest_deferral_stall.py`.
"""

from __future__ import annotations

import errno
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import breezy.runtime.ingest_deferral_streak as streak_module
from breezy.runtime.ingest_deferral_streak import (
    INITIAL_STATE,
    REALERT_EVERY_RUNS,
    STALL_MIN_AGE,
    STALL_MIN_CONSECUTIVE_RUNS,
    STATE_FILENAME,
    STATE_VERSION,
    DeferralStreakState,
    load_state,
    save_state,
    step,
)

_T0 = datetime(2026, 9, 27, 0, 0, 0, tzinfo=UTC)
#: 20 minutes, not the unit's real 15-minute `*:0/15` cadence: chosen so
#: that exactly the 4th consecutive run (index 3) lands at age=60 minutes,
#: making both AC-6f-1 thresholds (4 runs, 60 minutes) cross on the SAME
#: run without any fractional-run rounding in the test math.
_RUN_INTERVAL = timedelta(minutes=20)


def _advance(n: int) -> datetime:
    return _T0 + _RUN_INTERVAL * n


class TestBelowThreshold:
    def test_streak_below_threshold_exits_zero(self) -> None:
        state = INITIAL_STATE
        for i in range(STALL_MIN_CONSECUTIVE_RUNS - 1):
            state, alert_due = step(state, pending=True, now=_advance(i))
            assert alert_due is False

    def test_three_runs_or_under_60min_do_not_alert(self) -> None:
        # 3 consecutive runs at a 15-minute cadence: 45 minutes old, under
        # BOTH thresholds (run count AND age).
        state = INITIAL_STATE
        for i in range(3):
            state, alert_due = step(state, pending=True, now=_advance(i))
            assert alert_due is False
        assert state.consecutive_runs == 3

    def test_many_runs_below_60_minutes_do_not_alert(self) -> None:
        # Run count alone crosses 4, but a 1-minute cadence never crosses
        # the 60-minute age bound -- AC-6f-1 requires BOTH.
        fast = timedelta(minutes=1)
        state = INITIAL_STATE
        for i in range(10):
            state, alert_due = step(state, pending=True, now=_T0 + fast * i)
            assert alert_due is False


class TestCrossing:
    def test_fourth_consecutive_pending_deferral_after_60min_exits_4(self) -> None:
        state = INITIAL_STATE
        alert_due = False
        for i in range(STALL_MIN_CONSECUTIVE_RUNS):
            state, alert_due = step(state, pending=True, now=_advance(i))
        assert state.consecutive_runs == STALL_MIN_CONSECUTIVE_RUNS
        assert alert_due is True

    def test_crossing_requires_the_age_bound_even_past_the_run_count(self) -> None:
        # 4 runs at a 1-minute cadence: run count met, age (3 minutes) not.
        fast = timedelta(minutes=1)
        state = INITIAL_STATE
        alert_due = False
        for i in range(STALL_MIN_CONSECUTIVE_RUNS):
            state, alert_due = step(state, pending=True, now=_T0 + fast * i)
        assert alert_due is False
        # Once age (not count) finally crosses 60 minutes, it fires exactly
        # once, on that crossing run.
        state, alert_due = step(state, pending=True, now=_T0 + STALL_MIN_AGE)
        assert alert_due is True


class TestReAlertCadence:
    def _drive_to_crossing(self) -> DeferralStreakState:
        state = INITIAL_STATE
        for i in range(STALL_MIN_CONSECUTIVE_RUNS):
            state, _ = step(state, pending=True, now=_advance(i))
        return state

    def test_runs_between_realerts_exit_zero(self) -> None:
        state = self._drive_to_crossing()
        for offset in range(1, REALERT_EVERY_RUNS):
            state, alert_due = step(
                state, pending=True, now=_advance(STALL_MIN_CONSECUTIVE_RUNS - 1 + offset)
            )
            assert alert_due is False, f"run {offset} after crossing must not re-alert"

    def test_realert_every_16_runs_while_stalled(self) -> None:
        state = self._drive_to_crossing()
        due_flags: list[bool] = []
        for offset in range(1, REALERT_EVERY_RUNS + 1):
            state, alert_due = step(
                state, pending=True, now=_advance(STALL_MIN_CONSECUTIVE_RUNS - 1 + offset)
            )
            due_flags.append(alert_due)
        # Exactly the 16th run after the crossing re-alerts.
        assert due_flags == [False] * (REALERT_EVERY_RUNS - 1) + [True]

        # And the cadence repeats: another 16 runs, another single alert.
        due_flags = []
        base = STALL_MIN_CONSECUTIVE_RUNS - 1 + REALERT_EVERY_RUNS
        for offset in range(1, REALERT_EVERY_RUNS + 1):
            state, alert_due = step(state, pending=True, now=_advance(base + offset))
            due_flags.append(alert_due)
        assert due_flags == [False] * (REALERT_EVERY_RUNS - 1) + [True]


class TestReset:
    def test_streak_resets_on_a_run_with_no_pending_deferral(self) -> None:
        state = INITIAL_STATE
        for i in range(STALL_MIN_CONSECUTIVE_RUNS):
            state, _ = step(state, pending=True, now=_advance(i))
        assert state.consecutive_runs == STALL_MIN_CONSECUTIVE_RUNS

        state, alert_due = step(state, pending=False, now=_advance(99))
        assert alert_due is False
        assert state == INITIAL_STATE

    def test_a_fresh_streak_after_reset_needs_the_full_threshold_again(self) -> None:
        state = INITIAL_STATE
        for i in range(STALL_MIN_CONSECUTIVE_RUNS):
            state, _ = step(state, pending=True, now=_advance(i))
        state, _ = step(state, pending=False, now=_advance(99))

        # A brand-new streak starting now must NOT inherit the old
        # first_deferred_utc/consecutive_runs -- it needs 4 fresh runs.
        state, alert_due = step(state, pending=True, now=_advance(100))
        assert alert_due is False
        assert state.consecutive_runs == 1


class TestAtomicIO:
    def test_streak_file_lives_at_catalog_root_not_live(self, tmp_path: Path) -> None:
        assert not STATE_FILENAME.startswith("live")
        path = tmp_path / STATE_FILENAME
        save_state(path, DeferralStreakState(consecutive_runs=4, runs_since_alert=0))
        assert path.parent == tmp_path
        assert path.is_file()

    def test_round_trip_preserves_every_field(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        original = DeferralStreakState(
            version=STATE_VERSION,
            consecutive_runs=7,
            first_deferred_utc=_T0.isoformat(),
            runs_since_alert=3,
        )
        save_state(path, original)
        assert load_state(path) == original

    def test_write_is_atomic_no_tmp_file_left_behind(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        save_state(path, DeferralStreakState(consecutive_runs=1))
        leftovers = [p for p in tmp_path.iterdir() if p.name != STATE_FILENAME]
        assert leftovers == []

    def test_missing_file_loads_as_initial_state_with_no_warning(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        import logging as _logging

        path = tmp_path / STATE_FILENAME
        with caplog.at_level(_logging.WARNING, logger="breezy.runtime.ingest_deferral_streak"):
            state = load_state(path)
        assert state == INITIAL_STATE
        assert caplog.records == []

    def test_corrupt_streak_file_resets_and_warns(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        import logging as _logging

        path = tmp_path / STATE_FILENAME
        path.write_text("not json at all {{{")
        with caplog.at_level(_logging.WARNING, logger="breezy.runtime.ingest_deferral_streak"):
            state = load_state(path)
        assert state == INITIAL_STATE
        assert any("corrupt" in record.message.lower() for record in caplog.records)

    def test_unknown_version_resets_and_warns(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        import logging as _logging

        path = tmp_path / STATE_FILENAME
        path.write_text(
            json.dumps(
                {
                    "version": 999,
                    "consecutive_runs": 40,
                    "first_deferred_utc": _T0.isoformat(),
                    "runs_since_alert": 12,
                }
            )
        )
        with caplog.at_level(_logging.WARNING, logger="breezy.runtime.ingest_deferral_streak"):
            state = load_state(path)
        assert state == INITIAL_STATE
        assert caplog.records, "an unknown version must warn, never alert forever silently"

    def test_missing_field_resets_and_warns(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        import logging as _logging

        path = tmp_path / STATE_FILENAME
        path.write_text(json.dumps({"version": STATE_VERSION, "consecutive_runs": 4}))
        with caplog.at_level(_logging.WARNING, logger="breezy.runtime.ingest_deferral_streak"):
            state = load_state(path)
        assert state == INITIAL_STATE


# ---------------------------------------------------------------------------
# DEFER-STREAK-LOAD r2: strict field validation, reason enum, I/O failures.
# The new API is reached through the module object so a missing name fails
# the individual test (RED), not the whole file's collection.
# ---------------------------------------------------------------------------

_LOGGER = "breezy.runtime.ingest_deferral_streak"
_GOOD_FIRST = _T0.isoformat()


def _write_raw(path: Path, **overrides: object) -> None:
    body: dict[str, object] = {
        "version": STATE_VERSION,
        "consecutive_runs": 5,
        "first_deferred_utc": _GOOD_FIRST,
        "runs_since_alert": -1,
    }
    body.update(overrides)
    path.write_text(json.dumps(body))


_BAD_FIRST = [
    12345,
    ["x"],
    {"a": 1},
    True,
    False,
    0,
    "",
    "not-a-date",
    "2026-09-27T00:00:00",
]
_BAD_RUNS = [True, False, 3.5, 1.0, "4", -1, None]
_BAD_SINCE = [-1000, -2, 16, True, -1.0]
_CROSS_FIELD = [
    {"consecutive_runs": 5, "first_deferred_utc": None},
    {"consecutive_runs": 0, "first_deferred_utc": _GOOD_FIRST},
]
_ALL_BAD = (
    [{"first_deferred_utc": v} for v in _BAD_FIRST]
    + [{"consecutive_runs": v} for v in _BAD_RUNS]
    + [{"runs_since_alert": v} for v in _BAD_SINCE]
    + _CROSS_FIELD
)


def _field_of(override: dict[str, object]) -> str:
    if "runs_since_alert" in override:
        return "runs_since_alert"
    if "consecutive_runs" in override and "first_deferred_utc" in override:
        return "first_deferred_utc"  # cross-field violations name this field
    if "consecutive_runs" in override:
        return "consecutive_runs"
    return "first_deferred_utc"


class TestLoadStateRejectsMalformedFields:
    @pytest.mark.parametrize("bad", _BAD_FIRST, ids=repr)
    def test_bad_first_deferred_utc_resets_without_echoing_value(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, bad: object
    ) -> None:
        path = tmp_path / STATE_FILENAME
        _write_raw(path, first_deferred_utc=bad)
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            state, reason = streak_module.load_state_checked(path)
        assert state == INITIAL_STATE
        assert reason == streak_module.StreakResetReason.BAD_FIELD
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "corrupt" in message
        assert "field=first_deferred_utc" in message
        if isinstance(bad, str) and bad:
            assert bad not in message

    @pytest.mark.parametrize("bad", _BAD_RUNS, ids=repr)
    def test_bad_consecutive_runs_resets(self, tmp_path: Path, bad: object) -> None:
        path = tmp_path / STATE_FILENAME
        _write_raw(path, consecutive_runs=bad)
        assert streak_module.load_state_checked(path) == (
            INITIAL_STATE,
            streak_module.StreakResetReason.BAD_FIELD,
        )

    @pytest.mark.parametrize("bad", _BAD_SINCE, ids=repr)
    def test_bad_runs_since_alert_resets(self, tmp_path: Path, bad: object) -> None:
        path = tmp_path / STATE_FILENAME
        _write_raw(path, runs_since_alert=bad)
        assert streak_module.load_state_checked(path) == (
            INITIAL_STATE,
            streak_module.StreakResetReason.BAD_FIELD,
        )

    @pytest.mark.parametrize("override", _CROSS_FIELD, ids=repr)
    def test_cross_field_rule_resets(self, tmp_path: Path, override: dict[str, object]) -> None:
        path = tmp_path / STATE_FILENAME
        _write_raw(path, **override)
        assert streak_module.load_state_checked(path) == (
            INITIAL_STATE,
            streak_module.StreakResetReason.BAD_FIELD,
        )

    @pytest.mark.parametrize("override", _ALL_BAD, ids=repr)
    def test_loaded_state_never_crashes_step(
        self, tmp_path: Path, override: dict[str, object]
    ) -> None:
        path = tmp_path / STATE_FILENAME
        _write_raw(path, **override)
        state = load_state(path)
        _new, alert_due = step(state, pending=True, now=_T0 + timedelta(hours=2))
        assert alert_due is False

    def test_every_writer_producible_state_round_trips_unchanged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / STATE_FILENAME
        state = INITIAL_STATE
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            for i in range(41):
                state, _ = step(state, pending=True, now=_advance(i))
                save_state(path, state)
                assert streak_module.load_state_checked(path) == (state, None)
            state, _ = step(state, pending=False, now=_advance(41))
            save_state(path, state)
            assert streak_module.load_state_checked(path) == (INITIAL_STATE, None)
        assert caplog.records == []


class TestLoadStateReasons:
    def test_unparseable(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text("{not json")
        assert streak_module.load_state_checked(path)[1] == (
            streak_module.StreakResetReason.UNPARSEABLE
        )

    def test_non_utf8_bytes_are_unparseable(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_bytes(b"\xff\xfe\x00{\x80")
        assert streak_module.load_state_checked(path) == (
            INITIAL_STATE,
            streak_module.StreakResetReason.UNPARSEABLE,
        )

    def test_deeply_nested_json_is_unparseable_not_a_crash(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text("[" * 200_000 + "]" * 200_000)
        assert streak_module.load_state_checked(path) == (
            INITIAL_STATE,
            streak_module.StreakResetReason.UNPARSEABLE,
        )

    def test_oversized_integer_literal_is_unparseable_not_a_crash(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text(
            '{"version": 1, "consecutive_runs": ' + "9" * 5000 + ', "first_deferred_utc": null, '
            '"runs_since_alert": -1}'
        )
        assert streak_module.load_state_checked(path) == (
            INITIAL_STATE,
            streak_module.StreakResetReason.UNPARSEABLE,
        )

    @pytest.mark.parametrize("text", ["[]", json.dumps({"version": 2})])
    def test_unsupported_version(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text(text)
        assert streak_module.load_state_checked(path)[1] == (
            streak_module.StreakResetReason.UNSUPPORTED_VERSION
        )

    def test_missing_field(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text(
            json.dumps(
                {"version": STATE_VERSION, "consecutive_runs": 0, "first_deferred_utc": None}
            )
        )
        assert streak_module.load_state_checked(path)[1] == (
            streak_module.StreakResetReason.MISSING_FIELD
        )

    def test_read_oserror_is_io_error_not_a_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / STATE_FILENAME
        _write_raw(path)

        def _boom(self: Path, *a: object, **kw: object) -> str:
            raise OSError(errno.EIO, "boom")

        monkeypatch.setattr(Path, "read_text", _boom)
        assert streak_module.load_state_checked(path) == (
            INITIAL_STATE,
            streak_module.StreakResetReason.IO_ERROR,
        )

    def test_missing_file_is_a_silent_fresh_start(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            result = streak_module.load_state_checked(tmp_path / STATE_FILENAME)
        assert result == (INITIAL_STATE, None)
        assert caplog.records == []

    def test_non_bad_field_reasons_log_field_dash(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text("{not json")
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            streak_module.load_state_checked(path)
        assert "field=-" in caplog.records[0].getMessage()

    def test_loader_never_returns_save_failed(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILENAME
        reasons = set()
        for text in ("{x", "[]", "{}", json.dumps({"version": 1})):
            path.write_text(text)
            reasons.add(streak_module.load_state_checked(path)[1])
        _write_raw(path, consecutive_runs=True)
        reasons.add(streak_module.load_state_checked(path)[1])
        assert streak_module.StreakResetReason.SAVE_FAILED not in reasons


class TestSaveStateFailure:
    def test_failed_replace_reraises_and_leaves_no_tmp_orphan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(src: object, dst: object) -> None:
            raise OSError(errno.ENOSPC, "full")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(OSError) as info:
            save_state(tmp_path / STATE_FILENAME, INITIAL_STATE)
        assert info.value.errno == errno.ENOSPC
        assert [p.name for p in tmp_path.iterdir()] == []
