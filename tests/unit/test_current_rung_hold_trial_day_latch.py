"""Tests for the ``current_rung_hold`` trial-day latch
(src/breezy/strategy/current_rung_hold/trial_day_latch.py).

This latch shares ONE ``SqliteStateStore`` file and ONE flock with R-7's
submit-intent latch (``breezy.runtime.submit_intent``) -- see the blueprint's
"Contradiction resolved -- latch store: FOLD" and this module's docstring.
Every test below constructs a ``TrialDayLatch`` only through
``open_trial_day_latch`` bound to a real, opened ``SubmitIntentLatch``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayAlreadyConsumed,
    TrialDayInvalidReason,
    TrialDayLatch,
    TrialDayRecord,
    open_trial_day_latch,
)

NOW_NS = 1_700_000_000_000_000_000
STATION = "LAX"
CLIMATE_DAY = "2026-09-04"
OTHER_CLIMATE_DAY = "2026-09-05"
INSTRUMENT_ID = "POLY-LAX-TMAX-92-94.US"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


class TestConstruction:
    def test_cannot_be_constructed_without_a_currently_held_intent_latch(
        self, store_path: Path
    ) -> None:
        """A latch whose own flock has already been released cannot be used
        to bind a `TrialDayLatch` -- the accessor it goes through asserts the
        SAME flock `open_trial_day_latch` would otherwise silently inherit.
        """
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as latch:
            pass
        with pytest.raises(SubmitIntentLockNotHeld):
            open_trial_day_latch(latch)

    def test_open_trial_day_latch_returns_a_working_latch(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            assert isinstance(trial_latch, TrialDayLatch)
            assert trial_latch.is_consumed(STATION, CLIMATE_DAY) is False


class TestSecondOpenerFailsClosed:
    def test_a_second_opener_of_the_shared_store_path_raises_lock_held(
        self, store_path: Path
    ) -> None:
        """There is no side door through this module: the only way to get a
        second `TrialDayLatch` bound to the same file is a second
        `open_submit_intent_latch`, which is refused exactly as it already
        is for the submit-intent latch itself.
        """
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            open_trial_day_latch(intent_latch)
            with (
                pytest.raises(SubmitIntentLockHeld),
                open_submit_intent_latch(SqliteStateStore(store_path), store_path),
            ):
                raise AssertionError("second factory must not yield")


class TestConsumeAndRecord:
    def test_consume_then_record_round_trips_every_field(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            trial_latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            record = trial_latch.record(STATION, CLIMATE_DAY)
            assert record == TrialDayRecord(
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            assert isinstance(record.ask, Decimal)
            assert trial_latch.is_consumed(STATION, CLIMATE_DAY) is True

    def test_a_second_consume_for_the_same_station_day_raises_already_consumed(
        self, store_path: Path
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            trial_latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            with pytest.raises(TrialDayAlreadyConsumed):
                trial_latch.consume(
                    STATION,
                    CLIMATE_DAY,
                    latched_at_ns=NOW_NS + 1,
                    instrument_id=INSTRUMENT_ID,
                    ask=Decimal("0.40"),
                    reason="taken",
                )
            # The first record is untouched by the refused second write.
            record = trial_latch.record(STATION, CLIMATE_DAY)
            assert record is not None
            assert record.ask == Decimal("0.37")

    def test_consume_with_a_reason_outside_the_closed_set_is_refused(
        self, store_path: Path
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            with pytest.raises(TrialDayInvalidReason):
                trial_latch.consume(
                    STATION,
                    CLIMATE_DAY,
                    latched_at_ns=NOW_NS,
                    instrument_id=INSTRUMENT_ID,
                    ask=Decimal("0.37"),
                    reason="bogus",
                )
            assert trial_latch.record(STATION, CLIMATE_DAY) is None

    @pytest.mark.parametrize(
        "reason", ["observation_unavailable", "observation_ambiguous", "not_taken", "taken"]
    )
    def test_every_closed_set_reason_is_accepted(self, store_path: Path, reason: str) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            trial_latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.10"),
                reason=reason,
            )
            record = trial_latch.record(STATION, CLIMATE_DAY)
            assert record is not None
            assert record.reason == reason

    def test_resets_on_the_next_local_standard_climate_day(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            trial_latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            assert trial_latch.is_consumed(STATION, CLIMATE_DAY) is True
            assert trial_latch.is_consumed(STATION, OTHER_CLIMATE_DAY) is False
            # A different key entirely -- the next day's trial still runs.
            trial_latch.consume(
                STATION,
                OTHER_CLIMATE_DAY,
                latched_at_ns=NOW_NS + 1,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.22"),
                reason="not_taken",
            )
            assert trial_latch.is_consumed(STATION, OTHER_CLIMATE_DAY) is True


class TestSurvivesRestart:
    def test_consume_close_reopen_still_consumed(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            trial_latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
        store.close()

        reopened = SqliteStateStore(store_path)
        with open_submit_intent_latch(reopened, store_path) as restarted_intent_latch:
            restarted_trial_latch = open_trial_day_latch(restarted_intent_latch)
            assert restarted_trial_latch.is_consumed(STATION, CLIMATE_DAY) is True
            record = restarted_trial_latch.record(STATION, CLIMATE_DAY)
            assert record is not None
            assert record.ask == Decimal("0.37")
        reopened.close()

    def test_consume_then_crash_before_arm_leaves_day_consumed_no_intent_open(
        self, store_path: Path
    ) -> None:
        """The ordering rule: `consume` durably commits before `arm()` ever
        runs. A crash in that gap (simulated here by never calling `arm`
        before the process 'restarts') leaves the trial day consumed with NO
        OPEN intent -- a lost trial, never a double-send.
        """
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            trial_latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            # No `intent_latch.arm(...)` call -- simulating a crash here.
        store.close()

        reopened = SqliteStateStore(store_path)
        with open_submit_intent_latch(reopened, store_path) as restarted_intent_latch:
            restarted_trial_latch = open_trial_day_latch(restarted_intent_latch)
            assert restarted_trial_latch.is_consumed(STATION, CLIMATE_DAY) is True
            assert restarted_intent_latch.current() is None
        reopened.close()


class TestLockReleaseMakesEveryMethodRaise:
    def test_every_method_raises_lock_not_held_once_the_intent_latch_releases(
        self, store_path: Path
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            trial_latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )

        with pytest.raises(SubmitIntentLockNotHeld):
            trial_latch.is_consumed(STATION, CLIMATE_DAY)
        with pytest.raises(SubmitIntentLockNotHeld):
            trial_latch.record(STATION, CLIMATE_DAY)
        with pytest.raises(SubmitIntentLockNotHeld):
            trial_latch.consume(
                STATION,
                OTHER_CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.10"),
                reason="taken",
            )
