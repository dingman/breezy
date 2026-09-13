"""Tests for the ``current_rung_hold`` trial-day latch
(src/breezy/strategy/current_rung_hold/trial_day_latch.py).

This latch shares ONE ``SqliteStateStore`` file and ONE flock with R-7's
submit-intent latch (``breezy.runtime.submit_intent``) -- see the blueprint's
"Contradiction resolved -- latch store: FOLD" and this module's docstring.
Every test below constructs a ``TrialDayLatch`` only through
``open_trial_day_latch`` bound to a real, opened ``SubmitIntentLatch``.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    DurableFillRecord,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)
from breezy.strategy.current_rung_hold.decision import REFUSAL_REASONS
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    DEFAULT_TRIAL_KEY_PREFIX,
    FAMILY_HALT_KEY,
    STARTUP_EVIDENCE_KEY,
    TrialDayAlreadyConsumed,
    TrialDayInvalidReason,
    TrialDayLatch,
    TrialDayLatchError,
    TrialDayRecord,
    TrialDayRecordCorrupt,
    open_trial_day_latch,
    startup_evidence_confirms_absent_flat,
    startup_evidence_lists_slug,
    startup_evidence_permits_arm,
    startup_evidence_position_for,
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
        "reason",
        sorted(REFUSAL_REASONS | {"taken"}),
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
                reason="observation_unavailable",
            )
            assert trial_latch.is_consumed(STATION, OTHER_CLIMATE_DAY) is True


class TestConsumeIfAbsent:
    """Slice 4 item A: TRIAL-on-fill's idempotent, never-raising writer."""

    def test_writes_and_returns_true_when_absent(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            record = TrialDayRecord(
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
                venue_order_id="ord-1",
            )
            wrote = trial_latch.consume_if_absent(STATION, CLIMATE_DAY, record)
            assert wrote is True
            assert trial_latch.record(STATION, CLIMATE_DAY) == record

    def test_a_recon_replayed_duplicate_fill_never_raises_and_returns_false(
        self, store_path: Path
    ) -> None:
        """RED: a duplicate ``OrderFilled`` for an already-consumed
        station-day (reconciliation replay, the venue's own retry, etc.)
        must be a silent no-op -- never `TrialDayAlreadyConsumed`."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            first = TrialDayRecord(
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
                venue_order_id="ord-1",
            )
            assert trial_latch.consume_if_absent(STATION, CLIMATE_DAY, first) is True

            replayed = TrialDayRecord(
                latched_at_ns=NOW_NS + 1,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.40"),
                reason="taken",
                venue_order_id="ord-1",
            )
            wrote_again = trial_latch.consume_if_absent(STATION, CLIMATE_DAY, replayed)
            assert wrote_again is False
            # The FIRST record survives untouched -- the replay never overwrote it.
            assert trial_latch.record(STATION, CLIMATE_DAY) == first

    def test_two_writers_racing_the_same_station_day_leave_exactly_one_record(
        self, store_path: Path
    ) -> None:
        """RED: two DISTINCT writers (e.g. ``on_order_filled`` and the
        on_start durable-fill walk) racing the SAME station-day -- modeled
        here as two sequential calls on the one thread that owns the latch,
        since the flock is process-wide and this latch is single-thread-
        affine by design (see the thread-affinity assert below)."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            writer_a = TrialDayRecord(
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
                venue_order_id="ord-a",
            )
            writer_b = TrialDayRecord(
                latched_at_ns=NOW_NS + 5,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.41"),
                reason="taken",
                venue_order_id="ord-b",
            )
            results = (
                trial_latch.consume_if_absent(STATION, CLIMATE_DAY, writer_a),
                trial_latch.consume_if_absent(STATION, CLIMATE_DAY, writer_b),
            )
            assert sorted(results) == [False, True], "exactly one writer wrote"
            survivor = trial_latch.record(STATION, CLIMATE_DAY)
            assert survivor in (writer_a, writer_b)

    def test_an_invalid_reason_still_raises(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            record = TrialDayRecord(
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="bogus",
            )
            with pytest.raises(TrialDayInvalidReason):
                trial_latch.consume_if_absent(STATION, CLIMATE_DAY, record)
            assert trial_latch.record(STATION, CLIMATE_DAY) is None

    def test_requires_the_held_flock(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
        record = TrialDayRecord(
            latched_at_ns=NOW_NS,
            instrument_id=INSTRUMENT_ID,
            ask=Decimal("0.37"),
            reason="taken",
        )
        with pytest.raises(SubmitIntentLockNotHeld):
            trial_latch.consume_if_absent(STATION, CLIMATE_DAY, record)

    def test_a_foreign_thread_calling_consume_if_absent_is_refused(
        self, store_path: Path
    ) -> None:
        """The thread-affinity assert is load-bearing: a second thread
        racing this same call is NOT made safe by the process-wide flock
        alone."""
        import threading

        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            trial_latch = open_trial_day_latch(intent_latch)
            record = TrialDayRecord(
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            errors: list[BaseException] = []

            def _call_from_another_thread() -> None:
                try:
                    trial_latch.consume_if_absent(STATION, CLIMATE_DAY, record)
                except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
                    errors.append(exc)

            thread = threading.Thread(target=_call_from_another_thread)
            thread.start()
            thread.join()
            assert len(errors) == 1
            assert isinstance(errors[0], AssertionError)
            assert trial_latch.record(STATION, CLIMATE_DAY) is None


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

    def test_a_restart_mid_day_cannot_re_arm_an_already_consumed_station_day(
        self, store_path: Path,
    ) -> None:
        """(C2) The MULTI-station aggregate bound (Rev 2 REVISE-4 / §7 R5).

        `test_consume_close_reopen_still_consumed` above already covers the
        SINGLE-station half; this narrows to what it does not: with TWO
        distinct station-days consumed for the same climate day, a restart
        must leave BOTH consumed and refuse to re-arm EITHER. Aggregate
        daily exposure is bounded by this DURABLE latch, not by
        `DailySpendLedger` (`operator_controls.py:259-263`: "a restart
        forgets the day's spending") -- `_MAX_STATION_DAY_ATTEMPTS`
        (`continuous_strategy.py:125`) has no time dimension of its own
        either.
        """
        second_station = "SFO"
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
            trial_latch.consume(
                second_station,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.42"),
                reason="taken",
            )
        store.close()

        reopened = SqliteStateStore(store_path)
        with open_submit_intent_latch(reopened, store_path) as restarted_intent_latch:
            restarted_trial_latch = open_trial_day_latch(restarted_intent_latch)
            assert restarted_trial_latch.is_consumed(STATION, CLIMATE_DAY) is True
            assert restarted_trial_latch.is_consumed(second_station, CLIMATE_DAY) is True

            re_arm_record = TrialDayRecord(
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.99"),
                reason="taken",
            )
            assert (
                restarted_trial_latch.consume_if_absent(STATION, CLIMATE_DAY, re_arm_record)
                is False
            )
            assert (
                restarted_trial_latch.consume_if_absent(
                    second_station, CLIMATE_DAY, re_arm_record,
                )
                is False
            )
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
        with pytest.raises(SubmitIntentLockNotHeld):
            trial_latch.is_inflight(STATION, CLIMATE_DAY)
        with pytest.raises(SubmitIntentLockNotHeld):
            trial_latch.set_inflight(STATION, CLIMATE_DAY)
        with pytest.raises(SubmitIntentLockNotHeld):
            trial_latch.clear_inflight(STATION, CLIMATE_DAY)


def _committed_keys(store_path: Path) -> set[str]:
    conn = sqlite3.connect(store_path)
    try:
        return {row[0] for row in conn.execute("SELECT key FROM state")}
    finally:
        conn.close()


class TestKeyPrefix:
    def test_v2_prefix_default_unchanged(self, store_path: Path) -> None:
        """Default constructor prefix is byte-identical to today's v2 key."""
        assert DEFAULT_TRIAL_KEY_PREFIX == "current_rung_hold/trial/"
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
        keys = _committed_keys(store_path)
        assert f"current_rung_hold/trial/{STATION}/{CLIMATE_DAY}" in keys
        assert not any(k.startswith("continuous_rung_hold/") for k in keys)

    def test_cont_prefix_does_not_collide(self, store_path: Path) -> None:
        """v3 prefix is a sibling namespace on the same store/flock."""
        assert CONTINUOUS_TRIAL_KEY_PREFIX == "continuous_rung_hold/trial/"
        assert CONTINUOUS_TRIAL_KEY_PREFIX != DEFAULT_TRIAL_KEY_PREFIX
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            v2 = open_trial_day_latch(intent_latch)
            v3 = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            v2.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            assert v3.is_consumed(STATION, CLIMATE_DAY) is False
            v3.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.41"),
                reason="taken",
            )
            assert v2.is_consumed(STATION, CLIMATE_DAY) is True
            assert v3.is_consumed(STATION, CLIMATE_DAY) is True
            assert v2.record(STATION, CLIMATE_DAY) is not None
            assert v2.record(STATION, CLIMATE_DAY).ask == Decimal("0.37")
            assert v3.record(STATION, CLIMATE_DAY) is not None
            assert v3.record(STATION, CLIMATE_DAY).ask == Decimal("0.41")
        keys = _committed_keys(store_path)
        assert f"current_rung_hold/trial/{STATION}/{CLIMATE_DAY}" in keys
        assert f"continuous_rung_hold/trial/{STATION}/{CLIMATE_DAY}" in keys


class TestInFlightPrimitive:
    def test_inflight_get_set_clear_is_keyed_station_day(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(
                intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            )
            assert latch.is_inflight(STATION, CLIMATE_DAY) is False
            latch.set_inflight(STATION, CLIMATE_DAY)
            assert latch.is_inflight(STATION, CLIMATE_DAY) is True
            assert latch.is_inflight(STATION, OTHER_CLIMATE_DAY) is False
            assert latch.is_consumed(STATION, CLIMATE_DAY) is False
            latch.clear_inflight(STATION, CLIMATE_DAY)
            assert latch.is_inflight(STATION, CLIMATE_DAY) is False
        keys = _committed_keys(store_path)
        inflight_key = f"continuous_rung_hold/inflight/{STATION}/{CLIMATE_DAY}"
        assert inflight_key in keys
        assert f"continuous_rung_hold/trial/{STATION}/{CLIMATE_DAY}" not in keys

    def test_v2_default_prefix_never_writes_cont_inflight(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.set_inflight(STATION, CLIMATE_DAY)
        keys = _committed_keys(store_path)
        assert f"current_rung_hold/inflight/{STATION}/{CLIMATE_DAY}" in keys
        assert not any(k.startswith("continuous_rung_hold/") for k in keys)


class TestIsIntentOpen:
    """Resolution B (plan rev 6.1): the cheap, read-only pre-filter
    ``_hunt_tick`` checks before ``set_inflight``/``_maybe_submit``."""

    def test_false_on_a_fresh_never_armed_latch(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            assert latch.is_intent_open() is False

    def test_true_once_the_bound_intent_latch_is_armed(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            intent_latch.arm("a" * 64, now_ns=1)
            assert latch.is_intent_open() is True

    def test_false_again_once_retired(self, store_path: Path) -> None:
        from breezy.runtime.submit_intent import RetirementReason

        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            intent = intent_latch.arm("a" * 64, now_ns=1)
            assert latch.is_intent_open() is True
            intent_latch.retire(
                intent.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=2,
            )
            assert latch.is_intent_open() is False

    def test_a_stale_crash_left_open_singleton_is_visible_to_a_fresh_process(
        self, store_path: Path,
    ) -> None:
        """A latch armed and left OPEN (the flock released without a
        retire -- exactly a crash) is still OPEN to the NEXT process that
        opens the same store, which is the whole point: the pre-filter must
        see a stale OPEN singleton, not only a same-process sibling."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            intent_latch.arm("a" * 64, now_ns=1)
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            assert latch.is_intent_open() is True

    def test_a_trial_day_latch_built_without_an_intent_latch_refuses_to_answer(
        self, store_path: Path,
    ) -> None:
        """A ``TrialDayLatch`` constructed directly (existing test doubles,
        never through ``open_trial_day_latch``) has no ``intent_latch`` to
        delegate to and must fail closed, not silently report ``False``."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            store, lock = intent_latch.shared_state_binding()
            bare = TrialDayLatch(store, lock)
            with pytest.raises(TrialDayLatchError):
                bare.is_intent_open()


class TestDuplicateFillAndFamilyHalt:
    """Slice 4 item B1 (plan rev 6.1)."""

    def test_a_duplicate_fill_writes_a_bucket_and_sets_the_family_halt(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert latch.is_family_halted() is False
            latch.record_duplicate_fill(
                STATION,
                CLIMATE_DAY,
                venue_order_id="ord-dup-1",
                qty=Decimal(1),
                fill_px=Decimal("0.40"),
                fee=Decimal("0.01"),
                ts_ns=NOW_NS,
            )
            assert latch.is_family_halted() is True
        keys = _committed_keys(store_path)
        assert "continuous_rung_hold/duplicate_fill/ord-dup-1" in keys
        assert FAMILY_HALT_KEY in keys

    def test_recording_the_same_duplicate_id_twice_writes_neither_bucket_twice(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.record_duplicate_fill(
                STATION, CLIMATE_DAY, venue_order_id="ord-dup-1",
                qty=Decimal(1), fill_px=Decimal("0.40"), fee=Decimal("0.01"), ts_ns=NOW_NS,
            )
            # Second call, different numbers -- must not overwrite the first.
            latch.record_duplicate_fill(
                STATION, CLIMATE_DAY, venue_order_id="ord-dup-1",
                qty=Decimal(9), fill_px=Decimal("0.99"), fee=Decimal("0.99"), ts_ns=NOW_NS + 1,
            )
        conn_keys = _committed_keys(store_path)
        dup_keys = [k for k in conn_keys if k.startswith("continuous_rung_hold/duplicate_fill/")]
        assert len(dup_keys) == 1

    def test_family_halt_is_false_on_a_fresh_latch(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert latch.is_family_halted() is False


def test_startup_evidence_key_matches_the_exec_clients_own_constant() -> None:
    """Three-seam Slice 4 review item 6 [LOW]: this module's own literal
    must never drift from the exec client's -- two independent literals by
    design (strategy may import adapters; adapters must never import
    runtime/strategy), pinned equal here rather than imported."""
    from breezy.adapters.polymarket_us.exec.client import (
        STARTUP_EVIDENCE_KEY as CLIENT_STARTUP_EVIDENCE_KEY,
    )

    assert STARTUP_EVIDENCE_KEY == CLIENT_STARTUP_EVIDENCE_KEY


class TestStartupEvidence:
    """Slice 4 item A2 (plan rev 6.1)."""

    def test_absent_key_reads_as_none(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            assert latch.read_startup_evidence() is None

    def test_a_complete_record_round_trips(self, store_path: Path) -> None:
        payload = {
            "v": 1,
            "ts_ns": NOW_NS,
            "eof_complete": True,
            "position_read_refused": False,
            "fill_walk_complete": True,
            "positions": [{"slug": "tc-temp-laxhigh-2026-09-04-gte86lt87f", "net_position": "0"}],
        }
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            store, _ = intent_latch.shared_state_binding()
            store.set(STARTUP_EVIDENCE_KEY, json.dumps(payload).encode("utf-8"))
            latch = open_trial_day_latch(intent_latch)
            assert latch.read_startup_evidence() == payload

    def test_malformed_json_reads_as_none_not_a_raise(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            store, _ = intent_latch.shared_state_binding()
            store.set(STARTUP_EVIDENCE_KEY, b"not json")
            latch = open_trial_day_latch(intent_latch)
            assert latch.read_startup_evidence() is None

    @pytest.mark.parametrize(
        "evidence",
        [
            None,
            {
                "v": 1, "position_read_refused": True,
                "eof_complete": True, "fill_walk_complete": True,
            },
            {
                "v": 1, "position_read_refused": False,
                "eof_complete": False, "fill_walk_complete": True,
            },
            {
                "v": 1, "position_read_refused": False,
                "eof_complete": True, "fill_walk_complete": False,
            },
            {
                "v": 2, "position_read_refused": False,
                "eof_complete": True, "fill_walk_complete": True,
            },
        ],
    )
    def test_permits_arm_is_false_for_every_failure_mode(self, evidence: object) -> None:
        assert startup_evidence_permits_arm(evidence) is False  # type: ignore[arg-type]

    def test_permits_arm_is_true_for_a_complete_record(self) -> None:
        assert startup_evidence_permits_arm(
            {
                "v": 1, "position_read_refused": False,
                "eof_complete": True, "fill_walk_complete": True,
            },
        ) is True

    def test_position_for_an_absent_slug_is_unknown_not_flat(self) -> None:
        """Slice 4 review item 5: the client seam now emits every slug from
        the page, so a slug simply absent from the list is a READ GAP, never
        evidence of "no position" -- `None` (UNKNOWN), not `Decimal(0)`."""
        evidence: dict[str, object] = {"positions": [{"slug": "other", "net_position": "1"}]}
        assert startup_evidence_position_for(evidence, "mine") is None

    def test_position_for_a_null_net_position_is_unknown_not_flat(self) -> None:
        """Slice 4 review item 5: the client emits `"net_position": null`
        for a row it could not itself read -- `None` (UNKNOWN), never
        coerced to flat."""
        evidence: dict[str, object] = {"positions": [{"slug": "mine", "net_position": None}]}
        assert startup_evidence_position_for(evidence, "mine") is None

    def test_position_for_known_slug_is_its_net_position(self) -> None:
        evidence: dict[str, object] = {"positions": [{"slug": "mine", "net_position": "3.5"}]}
        assert startup_evidence_position_for(evidence, "mine") == Decimal("3.5")

    def test_position_for_none_evidence_is_none(self) -> None:
        assert startup_evidence_position_for(None, "mine") is None


class TestStartupEvidenceAbsentIsFlat:
    """R-8 (2026-09-12): ``startup_evidence_lists_slug`` and
    ``startup_evidence_confirms_absent_flat`` -- supersedes three-seam
    Slice 4 review item 5 for candidate instruments (HF-1.rev4.md).
    """

    @staticmethod
    def _complete_evidence(**overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "v": 1,
            "ts_ns": NOW_NS,
            "position_read_refused": False,
            "eof_complete": True,
            "fill_walk_complete": True,
            "positions": [],
        }
        base.update(overrides)
        return base

    # -- H15: lists_slug siblings' None-evidence convention --

    def test_lists_slug_is_false_when_evidence_is_none(self) -> None:
        assert startup_evidence_lists_slug(None, "mine") is False  # H15

    # -- H13: lists_slug scans for a match, skipping non-mapping rows --

    @pytest.mark.parametrize(
        ("positions", "expected"),
        [
            ([{"slug": "mine", "net_position": "0"}], True),
            ([{"slug": "other", "net_position": "0"}], False),
            (["garbage", {"slug": "mine", "net_position": "0"}], True),
        ],
    )
    def test_lists_slug_present_absent_and_garbage_row_ignored(
        self, positions: list[object], expected: bool,
    ) -> None:  # H13
        evidence: dict[str, object] = {"positions": positions}
        assert startup_evidence_lists_slug(evidence, "mine") is expected

    # -- H1-H5: confirms_absent_flat gates on startup_evidence_permits_arm --

    _MAX_AGE_NS = 600_000_000_000

    def test_confirms_absent_flat_true_when_absent_and_complete(self) -> None:  # H1
        evidence = self._complete_evidence()
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is True

    def test_confirms_absent_flat_false_when_not_eof_complete(self) -> None:  # H2
        evidence = self._complete_evidence(eof_complete=False)
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    def test_confirms_absent_flat_false_when_position_read_refused(self) -> None:  # H3
        evidence = self._complete_evidence(position_read_refused=True)
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    def test_confirms_absent_flat_false_when_schema_version_is_not_one(self) -> None:  # H4
        evidence = self._complete_evidence(v=2)
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    def test_confirms_absent_flat_false_when_fill_walk_incomplete(self) -> None:  # H5
        evidence = self._complete_evidence(fill_walk_complete=False)
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    # -- H9-H12: absent-branch exhaustiveness (HB4/E13) --

    def test_confirms_absent_flat_false_when_positions_key_is_missing(self) -> None:  # H9
        evidence = self._complete_evidence()
        del evidence["positions"]
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    def test_confirms_absent_flat_false_when_positions_is_not_a_list(self) -> None:  # H10
        evidence = self._complete_evidence(positions="garbage")
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    def test_confirms_absent_flat_false_on_any_non_mapping_row(self) -> None:  # H11
        evidence = self._complete_evidence(positions=["garbage"])
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    def test_confirms_absent_flat_false_when_slug_is_listed(self) -> None:  # H12
        evidence = self._complete_evidence(positions=[{"slug": "mine", "net_position": "0"}])
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    # -- H14 (HB3): round-trips the REAL producer object, not a hand-built dict --

    def test_startup_position_evidence_round_trip_confirms_absent_flat(self) -> None:  # H14
        from breezy.adapters.polymarket_us.exec.client import StartupPositionEvidence

        evidence = json.loads(
            StartupPositionEvidence(
                ts_ns=NOW_NS, eof_complete=True, position_read_refused=False,
                fill_walk_complete=True, positions=(),
            ).to_bytes(),
        )
        assert startup_evidence_confirms_absent_flat(
            evidence, "never-traded-slug", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is True

    # -- H6-H8 (C2, R2-B1/L-2): freshness clause, wall-clock units --

    def test_confirms_absent_flat_false_when_evidence_is_stale(self) -> None:  # H6
        evidence = self._complete_evidence(ts_ns=NOW_NS)
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS + self._MAX_AGE_NS + 1, max_age_ns=self._MAX_AGE_NS,
        ) is False

    def test_confirms_absent_flat_false_when_ts_ns_is_in_the_future(self) -> None:  # H7
        evidence = self._complete_evidence(ts_ns=NOW_NS + 1)
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False

    @pytest.mark.parametrize("bad_ts", [None, True, "1700000000000000000"])
    def test_confirms_absent_flat_false_when_ts_ns_is_malformed(
        self, bad_ts: object,
    ) -> None:  # H8
        evidence = self._complete_evidence(ts_ns=bad_ts)
        assert startup_evidence_confirms_absent_flat(
            evidence, "mine", now_ns=NOW_NS, max_age_ns=self._MAX_AGE_NS,
        ) is False


def _fill_record(
    *, venue_order_id: str, instrument_id: str, qty: str, cost: str, ts_event: int = NOW_NS,
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"C-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(qty),
        cumulative_cost=Decimal(cost),
        cumulative_fee=Decimal(0),
        fee_reconciled=True,
        ts_event=ts_event,
    )


def _write_fill(store: SqliteStateStore, record: DurableFillRecord) -> None:
    index_key = f"{FILL_INDEX_KEY_PREFIX}{record.instrument_id}"
    existing = store.get(index_key)
    ids: list[str] = json.loads(existing.decode("utf-8")) if existing is not None else []
    ids.append(record.venue_order_id)
    store.set(index_key, json.dumps(ids).encode("utf-8"))
    store.set(f"{FILL_KEY_PREFIX}{record.venue_order_id}", record.to_bytes())


class TestIterFillRecords:
    """Slice 4 item A2 (plan rev 6.1): the never-arm fill-primary walk's reader."""

    def test_no_index_for_an_instrument_yields_no_records(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            assert latch.iter_fill_records([INSTRUMENT_ID]) == ()

    def test_one_indexed_fill_is_returned(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            record = _fill_record(
                venue_order_id="ord-1", instrument_id=INSTRUMENT_ID, qty="1", cost="0.40",
            )
            _write_fill(store, record)
            latch = open_trial_day_latch(intent_latch)
            got = latch.iter_fill_records([INSTRUMENT_ID])
            assert got == (record,)

    def test_a_malformed_index_raises_corrupt(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            store.set(f"{FILL_INDEX_KEY_PREFIX}{INSTRUMENT_ID}", b"not json")
            latch = open_trial_day_latch(intent_latch)
            with pytest.raises(TrialDayRecordCorrupt):
                latch.iter_fill_records([INSTRUMENT_ID])

    def test_an_indexed_but_missing_record_raises_corrupt(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            store.set(
                f"{FILL_INDEX_KEY_PREFIX}{INSTRUMENT_ID}",
                json.dumps(["ord-ghost"]).encode("utf-8"),
            )
            latch = open_trial_day_latch(intent_latch)
            with pytest.raises(TrialDayRecordCorrupt):
                latch.iter_fill_records([INSTRUMENT_ID])

    def test_a_malformed_record_body_raises_mapping_error(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            store.set(
                f"{FILL_INDEX_KEY_PREFIX}{INSTRUMENT_ID}",
                json.dumps(["ord-bad"]).encode("utf-8"),
            )
            store.set(f"{FILL_KEY_PREFIX}ord-bad", b"not json")
            latch = open_trial_day_latch(intent_latch)
            with pytest.raises(ExecutionReportMappingError):
                latch.iter_fill_records([INSTRUMENT_ID])


class TestAttemptCounter:
    """Slice 4 item E1 (plan rev 6.1, Resolution F)."""

    def test_fresh_station_day_is_zero_none(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert latch.attempt_state(STATION, CLIMATE_DAY) == (0, None)

    def test_record_attempt_increments_and_persists(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert latch.record_attempt(STATION, CLIMATE_DAY, ts_ns=NOW_NS) == 1
            assert latch.attempt_state(STATION, CLIMATE_DAY) == (1, NOW_NS)
            assert latch.record_attempt(STATION, CLIMATE_DAY, ts_ns=NOW_NS + 1) == 2
            assert latch.attempt_state(STATION, CLIMATE_DAY) == (2, NOW_NS + 1)

    def test_a_malformed_attempt_record_raises_corrupt(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            store.set(f"continuous_rung_hold/attempts/{STATION}/{CLIMATE_DAY}", b"not json")
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            with pytest.raises(TrialDayRecordCorrupt):
                latch.attempt_state(STATION, CLIMATE_DAY)
