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
    BUDGET_EXHAUSTED_KEY_PREFIX,
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    DurableFillRecord,
)
from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id
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
    LATCH_GATE_REFUSAL_REASONS,
    NO_SIDE_FIRST_ORDER_PENDING_REASON,
    SIBLING_LEG_TRADED_REASON,
    STARTUP_EVIDENCE_KEY,
    STATION_DAY_ADMISSION_REASON,
    Refusal,
    TrialDayAlreadyConsumed,
    TrialDayInvalidReason,
    TrialDayLatch,
    TrialDayLatchError,
    TrialDayRecord,
    TrialDayRecordCorrupt,
    open_trial_day_latch,
    refuse_if_sibling_leg_traded,
    startup_evidence_confirms_absent_flat,
    startup_evidence_lists_slug,
    startup_evidence_permits_arm,
    startup_evidence_position_for,
    station_day_admission,
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

    def test_a_foreign_thread_calling_consume_if_absent_is_refused(self, store_path: Path) -> None:
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
        self,
        store_path: Path,
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
                    second_station,
                    CLIMATE_DAY,
                    re_arm_record,
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
    def test_inflight_get_set_clear_is_keyed_instrument_day(self, store_path: Path) -> None:
        """Re-pinned (operator ruling 2026-09-14 / plan S1): "I never wanted
        a limit of 1 contract per station" -- v3's IN_FLIGHT primitive is
        keyed by ``(station, climate_day, instrument_id)``, not station-day
        alone. Was ``test_inflight_get_set_clear_is_keyed_station_day``."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(
                intent_latch,
                key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            )
            assert latch.is_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID) is False
            latch.set_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID)
            assert latch.is_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID) is True
            assert (
                latch.is_inflight(STATION, OTHER_CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID)
                is False
            )
            assert latch.is_consumed(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID) is False
            latch.clear_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID)
            assert latch.is_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID) is False
        keys = _committed_keys(store_path)
        inflight_key = f"continuous_rung_hold/inflight/{STATION}/{CLIMATE_DAY}/{INSTRUMENT_ID}"
        assert inflight_key in keys
        assert f"continuous_rung_hold/trial/{STATION}/{CLIMATE_DAY}/{INSTRUMENT_ID}" not in keys

    def test_the_inflight_key_is_per_instrument_day(self, store_path: Path) -> None:
        """RED (plan S1): two DIFFERENT instruments on the SAME station-day
        each get their own independent IN_FLIGHT marker -- setting one must
        never affect the other."""
        other_instrument = "POLY-LAX-TMAX-94-96.US"
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(
                intent_latch,
                key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
            )
            latch.set_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID)
            assert latch.is_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID) is True
            assert (
                latch.is_inflight(STATION, CLIMATE_DAY, key_instrument_id=other_instrument) is False
            )
            latch.set_inflight(STATION, CLIMATE_DAY, key_instrument_id=other_instrument)
            latch.clear_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID)
            assert latch.is_inflight(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID) is False
            assert (
                latch.is_inflight(STATION, CLIMATE_DAY, key_instrument_id=other_instrument) is True
            )

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
                intent.intent_id,
                RetirementReason.DEFINITIVE_REJECT,
                now_ns=2,
            )
            assert latch.is_intent_open() is False

    def test_a_stale_crash_left_open_singleton_is_visible_to_a_fresh_process(
        self,
        store_path: Path,
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
        self,
        store_path: Path,
    ) -> None:
        """A ``TrialDayLatch`` constructed directly (existing test doubles,
        never through ``open_trial_day_latch``) has no ``intent_latch`` to
        delegate to and must fail closed, not silently report ``False``."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            store, lock = intent_latch.shared_state_binding()
            bare = TrialDayLatch(store, lock)
            with pytest.raises(TrialDayLatchError):
                bare.is_intent_open()


class TestCurrentOpenSubmitIntent:
    """Review finding B (POSITION_EXIT_EXECUTION_2026-09-16.md): the
    read-only pass-through ``exit_wiring.check_exit_intent_for_ambiguous_
    send`` needs to see whether ITS OWN exit is the account-wide singleton
    still stuck OPEN."""

    def test_none_on_a_fresh_never_armed_latch(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            assert latch.current_open_submit_intent() is None

    def test_returns_the_armed_intent_with_its_fingerprint_and_created_ns(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            armed = intent_latch.arm("a" * 64, now_ns=123)
            current = latch.current_open_submit_intent()
            assert current is not None
            assert current.intent_id == armed.intent_id
            assert current.fingerprint == "a" * 64
            assert current.created_ns == 123

    def test_none_again_once_retired(self, store_path: Path) -> None:
        from breezy.runtime.submit_intent import RetirementReason

        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            intent = intent_latch.arm("a" * 64, now_ns=1)
            assert latch.current_open_submit_intent() is not None
            intent_latch.retire(
                intent.intent_id,
                RetirementReason.DEFINITIVE_REJECT,
                now_ns=2,
            )
            assert latch.current_open_submit_intent() is None

    def test_a_trial_day_latch_built_without_an_intent_latch_refuses_to_answer(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            store, lock = intent_latch.shared_state_binding()
            bare = TrialDayLatch(store, lock)
            with pytest.raises(TrialDayLatchError):
                bare.current_open_submit_intent()


class TestDuplicateFillAndFamilyHalt:
    """Slice 4 item B1 (plan rev 6.1)."""

    def test_a_duplicate_fill_writes_a_bucket_and_sets_the_family_halt(
        self,
        store_path: Path,
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
        self,
        store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.record_duplicate_fill(
                STATION,
                CLIMATE_DAY,
                venue_order_id="ord-dup-1",
                qty=Decimal(1),
                fill_px=Decimal("0.40"),
                fee=Decimal("0.01"),
                ts_ns=NOW_NS,
            )
            # Second call, different numbers -- must not overwrite the first.
            latch.record_duplicate_fill(
                STATION,
                CLIMATE_DAY,
                venue_order_id="ord-dup-1",
                qty=Decimal(9),
                fill_px=Decimal("0.99"),
                fee=Decimal("0.99"),
                ts_ns=NOW_NS + 1,
            )
        conn_keys = _committed_keys(store_path)
        dup_keys = [k for k in conn_keys if k.startswith("continuous_rung_hold/duplicate_fill/")]
        assert len(dup_keys) == 1

    def test_family_halt_is_false_on_a_fresh_latch(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert latch.is_family_halted() is False


class TestExitProvenanceAndAmbiguousHalt:
    """INC-E3 (plan §3, PREREG v4 §5b/§10): ``record_exit`` and
    ``record_ambiguous_exit``."""

    def test_record_exit_attaches_provenance_to_an_existing_trial(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.40"),
                reason="taken",
                key_instrument_id=INSTRUMENT_ID,
            )
            latch.record_exit(
                STATION,
                CLIMATE_DAY,
                key_instrument_id=INSTRUMENT_ID,
                exit_reason="R_DEAD",
                exit_px=Decimal("0.05"),
                exit_fee=Decimal("0.00"),
                exit_at_ns=NOW_NS + 1,
            )
            record = latch.record(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID)
        assert record is not None
        # Entry fields carried forward byte-identical.
        assert record.ask == Decimal("0.40")
        assert record.reason == "taken"
        # New exit provenance.
        assert record.exit_reason == "R_DEAD"
        assert record.exit_px == Decimal("0.05")
        assert record.exit_fee == Decimal("0.00")
        assert record.exit_at_ns == NOW_NS + 1

    def test_record_exit_round_trips_through_to_bytes_and_from_bytes(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.40"),
                reason="taken",
                key_instrument_id=INSTRUMENT_ID,
            )
            latch.record_exit(
                STATION,
                CLIMATE_DAY,
                key_instrument_id=INSTRUMENT_ID,
                exit_reason="R_THREAT",
                exit_px=Decimal("0.55"),
                exit_fee=Decimal("0.01"),
                exit_at_ns=NOW_NS + 2,
            )
        # Fresh reopen over the SAME store file -- a genuine restart, not an
        # in-process re-read.
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            record = latch.record(STATION, CLIMATE_DAY, key_instrument_id=INSTRUMENT_ID)
        assert record is not None
        assert record.exit_reason == "R_THREAT"
        assert record.exit_px == Decimal("0.55")
        assert record.exit_fee == Decimal("0.01")
        assert record.exit_at_ns == NOW_NS + 2

    def test_record_exit_refuses_a_station_day_with_no_existing_trial(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            with pytest.raises(TrialDayLatchError):
                latch.record_exit(
                    STATION,
                    CLIMATE_DAY,
                    key_instrument_id=INSTRUMENT_ID,
                    exit_reason="R_DEAD",
                    exit_px=Decimal("0.05"),
                    exit_fee=Decimal("0.00"),
                    exit_at_ns=NOW_NS,
                )

    def test_record_exit_refuses_an_exit_reason_outside_the_closed_set(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.40"),
                reason="taken",
                key_instrument_id=INSTRUMENT_ID,
            )
            with pytest.raises(TrialDayInvalidReason):
                latch.record_exit(
                    STATION,
                    CLIMATE_DAY,
                    key_instrument_id=INSTRUMENT_ID,
                    exit_reason="not_a_real_rule",
                    exit_px=Decimal("0.05"),
                    exit_fee=Decimal("0.00"),
                    exit_at_ns=NOW_NS,
                )

    def test_record_ambiguous_exit_sets_the_same_family_halt_as_duplicate_fill(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert latch.is_family_halted() is False
            latch.record_ambiguous_exit(
                position_id="P-1", reason="order_rejected:test", ts_ns=NOW_NS,
            )
            assert latch.is_family_halted() is True
        keys = _committed_keys(store_path)
        assert FAMILY_HALT_KEY in keys

    def test_record_ambiguous_exit_is_idempotent_once_already_halted(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.record_duplicate_fill(
                STATION,
                CLIMATE_DAY,
                venue_order_id="ord-dup-x",
                qty=Decimal(1),
                fill_px=Decimal("0.40"),
                fee=Decimal("0.01"),
                ts_ns=NOW_NS,
            )
            # A SECOND, different cause must never overwrite the FIRST halt
            # payload (mirrors `record_duplicate_fill`'s own idempotency).
            latch.record_ambiguous_exit(
                position_id="P-1", reason="order_rejected:test", ts_ns=NOW_NS + 1,
            )
            assert latch.is_family_halted() is True
        with sqlite3.connect(store_path) as conn:
            row = conn.execute(
                "SELECT value FROM state WHERE key = ?", (FAMILY_HALT_KEY,),
            ).fetchone()
        assert row is not None
        assert b"duplicate_fill" in row[0]
        assert b"ambiguous_exit" not in row[0]

    def test_the_ambiguous_exit_halt_survives_a_process_restart(
        self, store_path: Path,
    ) -> None:
        """The exact scenario `midday-relaunch` makes routine (memory:
        `trade-node-dies-with-the-session`): the halt written by ONE process
        must be observed as-is by a FRESH `TrialDayLatch`/`SqliteStateStore`
        opened over the SAME on-disk store file, never re-derived from
        in-memory state."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.record_ambiguous_exit(
                position_id="P-restart", reason="order_denied:test", ts_ns=NOW_NS,
            )

        # Simulates a process restart: a BRAND NEW SqliteStateStore instance
        # and a brand new intent latch, over the same file on disk.
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            restarted = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert restarted.is_family_halted() is True


class TestDayBudgetExhausted:
    """Operator ruling 2026-09-14: the day-budget marker the exec client
    writes at ``BUDGET_EXHAUSTED_KEY_PREFIX + <UTC day>``."""

    def test_is_day_budget_exhausted_is_false_for_a_different_utc_day(
        self, store_path: Path
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            store, _ = intent_latch.shared_state_binding()
            store.set(f"{BUDGET_EXHAUSTED_KEY_PREFIX}2026-09-14", b"1")
            assert latch.is_day_budget_exhausted("2026-09-14") is True
            assert latch.is_day_budget_exhausted("2026-09-15") is False

    def test_is_day_budget_exhausted_raises_without_the_flock(
        self, store_path: Path
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        with pytest.raises(SubmitIntentLockNotHeld):
            latch.is_day_budget_exhausted("2026-09-14")

    def test_any_value_at_the_budget_key_reads_as_exhausted(self, store_path: Path) -> None:
        """Fail-closed: the store has no delete, so ANY value -- not only
        ``b"1"`` -- must read as exhausted, mirroring ``is_family_halted``'s
        own presence check (except this key is never "cleared")."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            store, _ = intent_latch.shared_state_binding()
            store.set(f"{BUDGET_EXHAUSTED_KEY_PREFIX}2026-09-14", b"anything-nonempty")
            assert latch.is_day_budget_exhausted("2026-09-14") is True


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
                "v": 1,
                "position_read_refused": True,
                "eof_complete": True,
                "fill_walk_complete": True,
            },
            {
                "v": 1,
                "position_read_refused": False,
                "eof_complete": False,
                "fill_walk_complete": True,
            },
            {
                "v": 1,
                "position_read_refused": False,
                "eof_complete": True,
                "fill_walk_complete": False,
            },
            {
                "v": 2,
                "position_read_refused": False,
                "eof_complete": True,
                "fill_walk_complete": True,
            },
        ],
    )
    def test_permits_arm_is_false_for_every_failure_mode(self, evidence: object) -> None:
        assert startup_evidence_permits_arm(evidence) is False  # type: ignore[arg-type]

    def test_permits_arm_is_true_for_a_complete_record(self) -> None:
        assert (
            startup_evidence_permits_arm(
                {
                    "v": 1,
                    "position_read_refused": False,
                    "eof_complete": True,
                    "fill_walk_complete": True,
                    # RESTING_BID_HUNT Rev 2 §4.3: a COMPLETE record now also
                    # carries a successful, EMPTY open-order enumeration.
                    # Widened additively; every prior key is unchanged.
                    "open_orders_read_refused": False,
                    "open_orders": [],
                },
            )
            is True
        )

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
            # RESTING_BID_HUNT Rev 2 §4.3: complete = open orders read, empty.
            "open_orders_read_refused": False,
            "open_orders": [],
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
        self,
        positions: list[object],
        expected: bool,
    ) -> None:  # H13
        evidence: dict[str, object] = {"positions": positions}
        assert startup_evidence_lists_slug(evidence, "mine") is expected

    # -- H1-H5: confirms_absent_flat gates on startup_evidence_permits_arm --

    _MAX_AGE_NS = 600_000_000_000

    def test_confirms_absent_flat_true_when_absent_and_complete(self) -> None:  # H1
        evidence = self._complete_evidence()
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is True
        )

    def test_confirms_absent_flat_false_when_not_eof_complete(self) -> None:  # H2
        evidence = self._complete_evidence(eof_complete=False)
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    def test_confirms_absent_flat_false_when_position_read_refused(self) -> None:  # H3
        evidence = self._complete_evidence(position_read_refused=True)
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    def test_confirms_absent_flat_false_when_schema_version_is_not_one(self) -> None:  # H4
        evidence = self._complete_evidence(v=2)
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    def test_confirms_absent_flat_false_when_fill_walk_incomplete(self) -> None:  # H5
        evidence = self._complete_evidence(fill_walk_complete=False)
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    # -- H9-H12: absent-branch exhaustiveness (HB4/E13) --

    def test_confirms_absent_flat_false_when_positions_key_is_missing(self) -> None:  # H9
        evidence = self._complete_evidence()
        del evidence["positions"]
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    def test_confirms_absent_flat_false_when_positions_is_not_a_list(self) -> None:  # H10
        evidence = self._complete_evidence(positions="garbage")
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    def test_confirms_absent_flat_false_on_any_non_mapping_row(self) -> None:  # H11
        evidence = self._complete_evidence(positions=["garbage"])
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    def test_confirms_absent_flat_false_when_slug_is_listed(self) -> None:  # H12
        evidence = self._complete_evidence(positions=[{"slug": "mine", "net_position": "0"}])
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    # -- H14 (HB3): round-trips the REAL producer object, not a hand-built dict --

    def test_startup_position_evidence_round_trip_confirms_absent_flat(self) -> None:  # H14
        from breezy.adapters.polymarket_us.exec.client import StartupPositionEvidence

        evidence = json.loads(
            StartupPositionEvidence(
                ts_ns=NOW_NS,
                eof_complete=True,
                position_read_refused=False,
                fill_walk_complete=True,
                positions=(),
                # §4.3: the producer's default is REFUSED (fail closed); a
                # complete boot record states the successful empty read.
                open_orders_read_refused=False,
                open_orders=(),
            ).to_bytes(),
        )
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "never-traded-slug",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is True
        )

    # -- H6-H8 (C2, R2-B1/L-2): freshness clause, wall-clock units --

    def test_confirms_absent_flat_false_when_evidence_is_stale(self) -> None:  # H6
        evidence = self._complete_evidence(ts_ns=NOW_NS)
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS + self._MAX_AGE_NS + 1,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    def test_confirms_absent_flat_false_when_ts_ns_is_in_the_future(self) -> None:  # H7
        evidence = self._complete_evidence(ts_ns=NOW_NS + 1)
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )

    @pytest.mark.parametrize("bad_ts", [None, True, "1700000000000000000"])
    def test_confirms_absent_flat_false_when_ts_ns_is_malformed(
        self,
        bad_ts: object,
    ) -> None:  # H8
        evidence = self._complete_evidence(ts_ns=bad_ts)
        assert (
            startup_evidence_confirms_absent_flat(
                evidence,
                "mine",
                now_ns=NOW_NS,
                max_age_ns=self._MAX_AGE_NS,
            )
            is False
        )


def _fill_record(
    *,
    venue_order_id: str,
    instrument_id: str,
    qty: str,
    cost: str,
    fee: str = "0",
    ts_event: int = NOW_NS,
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"C-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(qty),
        cumulative_cost=Decimal(cost),
        cumulative_fee=Decimal(fee),
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
                venue_order_id="ord-1",
                instrument_id=INSTRUMENT_ID,
                qty="1",
                cost="0.40",
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

    def test_the_attempt_counter_is_per_instrument_day(self, store_path: Path) -> None:
        """RED (plan S1): two DIFFERENT instruments on the SAME station-day
        each get their own independent re-arm attempt counter."""
        other_instrument = "POLY-LAX-TMAX-94-96.US"
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            assert (
                latch.record_attempt(
                    STATION,
                    CLIMATE_DAY,
                    ts_ns=NOW_NS,
                    key_instrument_id=INSTRUMENT_ID,
                )
                == 1
            )
            assert (
                latch.record_attempt(
                    STATION,
                    CLIMATE_DAY,
                    ts_ns=NOW_NS + 1,
                    key_instrument_id=INSTRUMENT_ID,
                )
                == 2
            )
            # A second instrument's counter starts fresh, unaffected by the first.
            assert latch.attempt_state(
                STATION,
                CLIMATE_DAY,
                key_instrument_id=other_instrument,
            ) == (0, None)
            assert (
                latch.record_attempt(
                    STATION,
                    CLIMATE_DAY,
                    ts_ns=NOW_NS + 2,
                    key_instrument_id=other_instrument,
                )
                == 1
            )
            assert latch.attempt_state(
                STATION,
                CLIMATE_DAY,
                key_instrument_id=INSTRUMENT_ID,
            ) == (2, NOW_NS + 1)
            assert latch.attempt_state(
                STATION,
                CLIMATE_DAY,
                key_instrument_id=other_instrument,
            ) == (1, NOW_NS + 2)


class TestInstrumentDayReadCompatShim:
    """RED (plan S1, operator ruling 2026-09-14): "I never wanted a limit
    of 1 contract per station." A durable row from before this slice lives
    under the OLD station-day key with no instrument suffix; the shim below
    is the only bridge a restart needs.
    """

    def test_a_legacy_station_day_row_blocks_only_its_own_instrument(
        self,
        store_path: Path,
    ) -> None:
        other_instrument = "POLY-LAX-TMAX-94-96.US"
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            # The legacy row's OWN instrument is blocked...
            assert (
                latch.is_consumed(
                    STATION,
                    CLIMATE_DAY,
                    key_instrument_id=INSTRUMENT_ID,
                )
                is True
            )
            # ...but a DIFFERENT instrument on the SAME station-day is not.
            assert (
                latch.is_consumed(
                    STATION,
                    CLIMATE_DAY,
                    key_instrument_id=other_instrument,
                )
                is False
            )
            # The different instrument may still be consumed under its own key.
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS + 1,
                instrument_id=other_instrument,
                ask=Decimal("0.22"),
                reason="taken",
                key_instrument_id=other_instrument,
            )
            assert (
                latch.is_consumed(
                    STATION,
                    CLIMATE_DAY,
                    key_instrument_id=other_instrument,
                )
                is True
            )


class TestV2LatchKeysAreByteIdentical:
    """RED (plan S1): v2's PREREG is closed and never re-keyed -- every v2
    call shape (no ``key_instrument_id``) must write and read the SAME
    byte-identical station-day key as before this slice.
    """

    def test_v2_latch_keys_are_byte_identical(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            assert latch.is_consumed(STATION, CLIMATE_DAY) is True
        keys = _committed_keys(store_path)
        assert f"current_rung_hold/trial/{STATION}/{CLIMATE_DAY}" in keys
        assert not any(k.count("/") > 3 for k in keys if k.startswith("current_rung_hold/trial/"))


class TestKeyInstrumentIdRejectsSlash:
    """S1 follow-up (operator ruling 2026-09-14): a ``key_instrument_id``
    containing ``/`` would corrupt the ``station/climate_day/instrument_id``
    key boundary -- refused loudly at every keyed accessor, never silently
    building a malformed key."""

    def test_an_instrument_id_containing_a_slash_is_refused_at_the_key_boundary(
        self, store_path: Path,
    ) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            with pytest.raises(TrialDayLatchError):
                latch.is_consumed(STATION, CLIMATE_DAY, key_instrument_id="POLY/LAX")
            with pytest.raises(TrialDayLatchError):
                latch.consume(
                    STATION,
                    CLIMATE_DAY,
                    latched_at_ns=NOW_NS,
                    instrument_id=INSTRUMENT_ID,
                    ask=Decimal("0.37"),
                    reason="taken",
                    key_instrument_id="POLY/LAX",
                )


# ---------------------------------------------------------------------------
# S4: closed-set reason enumeration for the two latch-level gates below.
# ---------------------------------------------------------------------------


def test_latch_gate_refusal_reasons_is_the_closed_set() -> None:
    """Pin (plan NO_SIDE_EDGE_2026-09-14 S4, N2-10/R3-7): these reasons
    are DISTINCT from ``decision.REFUSAL_REASONS`` (hard invariant --
    ``decision.py`` stays untouched) because these gates run before a quote
    ever reaches ``evaluate_decision`` and have no analogue there.

    WIDENED (NO-SIDE S5, E3-6/E4-6), never relaxed (L-12):
    ``NO_SIDE_FIRST_ORDER_PENDING_REASON`` -- the bounded first-order
    containment window's refusal reason (PREREG amendment §8).
    """
    assert LATCH_GATE_REFUSAL_REASONS == frozenset(
        {
            SIBLING_LEG_TRADED_REASON,
            STATION_DAY_ADMISSION_REASON,
            NO_SIDE_FIRST_ORDER_PENDING_REASON,
        }
    )
    assert SIBLING_LEG_TRADED_REASON == "sibling_leg_traded"
    assert STATION_DAY_ADMISSION_REASON == "station_day_admission"
    assert NO_SIDE_FIRST_ORDER_PENDING_REASON == "no_side_first_order_pending"


def test_refusal_rejects_a_reason_outside_the_closed_set() -> None:
    with pytest.raises(ValueError):
        Refusal("bogus")


# ---------------------------------------------------------------------------
# S4: TrialDayRecord gains an OPTIONAL, trailing ``fee`` field (R3-7) --
# mirrors ``venue_order_id`` exactly: no ``_SCHEMA_VERSION`` bump (that gate
# would corrupt every existing v1 row), read via ``payload.get`` so a
# pre-slice-4 record missing the key decodes as ``None`` ("q unknown").
# ---------------------------------------------------------------------------


class TestTrialDayRecordFee:
    def test_fee_round_trips_through_to_bytes_and_from_bytes(self) -> None:
        record = TrialDayRecord(
            latched_at_ns=NOW_NS,
            instrument_id=INSTRUMENT_ID,
            ask=Decimal("0.40"),
            reason="taken",
            fee=Decimal("0.01"),
        )
        assert TrialDayRecord.from_bytes(record.to_bytes()) == record

    def test_a_record_with_no_fee_key_decodes_fee_as_none(self) -> None:
        """A pre-slice-4 record byte-for-byte (no ``fee`` key at all)."""
        payload = json.dumps(
            {
                "v": 1,
                "latched_at_ns": NOW_NS,
                "instrument_id": INSTRUMENT_ID,
                "ask": "0.37",
                "reason": "taken",
                "venueOrderId": None,
            },
            sort_keys=True,
        ).encode("utf-8")
        record = TrialDayRecord.from_bytes(payload)
        assert record.fee is None

    def test_consume_accepts_an_optional_fee_and_persists_it(self, store_path: Path) -> None:
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.40"),
                reason="taken",
                fee=Decimal("0.0144"),
            )
            record = latch.record(STATION, CLIMATE_DAY)
            assert record is not None
            assert record.fee == Decimal("0.0144")

    def test_consume_without_fee_still_defaults_to_none_byte_identically(
        self, store_path: Path
    ) -> None:
        """v2's only call shape never passes ``fee`` -- stays byte-identical."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=INSTRUMENT_ID,
                ask=Decimal("0.37"),
                reason="taken",
            )
            record = latch.record(STATION, CLIMATE_DAY)
            assert record is not None
            assert record.fee is None


# ---------------------------------------------------------------------------
# S4 item 1 (N2-10): sibling-leg exclusion.
# ---------------------------------------------------------------------------


NO_INSTRUMENT_ID = str(no_leg_instrument_id("poly-lax-tmax-92-94").symbol)


class TestRefuseIfSiblingLegTraded:
    def test_no_sibling_record_is_not_refused(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path):
            got = refuse_if_sibling_leg_traded(
                store, DEFAULT_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY, "poly-lax-tmax-92-94",
            )
        assert got is None

    def test_a_filled_sibling_record_refuses(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=NO_INSTRUMENT_ID,
                ask=Decimal("0.30"),
                reason="taken",
                key_instrument_id=NO_INSTRUMENT_ID,
            )
            got = refuse_if_sibling_leg_traded(
                store, DEFAULT_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY, "poly-lax-tmax-92-94",
            )
        assert got == Refusal(SIBLING_LEG_TRADED_REASON)

    def test_a_fill_walk_sibling_record_also_refuses(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=NO_INSTRUMENT_ID,
                ask=Decimal("0.30"),
                reason="taken_from_fill_walk",
                key_instrument_id=NO_INSTRUMENT_ID,
            )
            got = refuse_if_sibling_leg_traded(
                store, DEFAULT_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY, "poly-lax-tmax-92-94",
            )
        assert got == Refusal(SIBLING_LEG_TRADED_REASON)

    def test_a_merely_refused_sibling_record_does_not_refuse(self, store_path: Path) -> None:
        """A sibling that was EVALUATED and refused (never filled) is not a
        TRIAL in the sense this gate cares about -- only ``taken`` and
        ``taken_from_fill_walk`` count as the sibling having traded."""
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=NO_INSTRUMENT_ID,
                ask=Decimal("0.30"),
                reason="not_executable",
                key_instrument_id=NO_INSTRUMENT_ID,
            )
            got = refuse_if_sibling_leg_traded(
                store, DEFAULT_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY, "poly-lax-tmax-92-94",
            )
        assert got is None

    def test_the_no_leg_composite_id_round_trips_through_the_key_and_the_legacy_shim(
        self, store_path: Path,
    ) -> None:
        """The composite ``^no`` id must survive ``_key``'s slash guard and
        ``record_with_legacy_fallback`` exactly like any other
        ``key_instrument_id`` string."""
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=NO_INSTRUMENT_ID,
                ask=Decimal("0.30"),
                reason="taken",
                key_instrument_id=NO_INSTRUMENT_ID,
            )
            record = latch.record_with_legacy_fallback(
                STATION, CLIMATE_DAY, key_instrument_id=NO_INSTRUMENT_ID,
            )
        assert record is not None
        assert record.instrument_id == NO_INSTRUMENT_ID
        keys = _committed_keys(store_path)
        # Safety review finding 1 (2026-09-14, commit f2d33f4): `_key` now
        # normalises every `key_instrument_id` to the DOTTED canonical form
        # (`_dotted_key_id`) so a record written under the bare symbol and
        # one written under the dotted `str(InstrumentId)` resolve to the
        # SAME durable key -- the committed key is dotted, not bare.
        assert (
            f"current_rung_hold/trial/{STATION}/{CLIMATE_DAY}/{NO_INSTRUMENT_ID}.POLYMARKET_US"
            in keys
        )

    def test_mid_day_relaunch_a_fresh_process_still_sees_a_yes_trial_from_the_sibling(
        self, store_path: Path,
    ) -> None:
        """N2-10 relaunch ordering: a YES fill is persisted, the process
        exits (both latches close), a FRESH process opens a new
        ``TrialDayLatch`` over the SAME store and the NO leg's sibling
        check still sees it -- pure store reads, no in-memory state."""
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id="poly-lax-tmax-92-94",
                ask=Decimal("0.55"),
                reason="taken",
                key_instrument_id="poly-lax-tmax-92-94",
            )
        # Fresh process: a brand-new store handle and a brand-new latch.
        fresh_store = SqliteStateStore(store_path)
        with open_submit_intent_latch(fresh_store, store_path):
            got = refuse_if_sibling_leg_traded(
                fresh_store, DEFAULT_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY, NO_INSTRUMENT_ID,
            )
        assert got == Refusal(SIBLING_LEG_TRADED_REASON)


# ---------------------------------------------------------------------------
# S4 item 2 (R3-7): arm-time station-day admission.
# ---------------------------------------------------------------------------


class TestStationDayAdmission:
    def test_an_empty_day_admits_any_candidate_up_to_one(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path):
            got = station_day_admission(
                store, DEFAULT_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY, "yes", Decimal("0.90"),
            )
        assert got is None

    def test_a_yes_candidate_that_alone_exceeds_one_is_refused(self, store_path: Path) -> None:
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path):
            got = station_day_admission(
                store, DEFAULT_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY, "yes", Decimal("1.01"),
            )
        assert got == Refusal(STATION_DAY_ADMISSION_REASON)

    def test_an_existing_yes_trial_plus_a_candidate_summing_above_one_is_refused(
        self, store_path: Path,
    ) -> None:
        other_instrument = "POLY-LAX-TMAX-70-71"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=other_instrument,
                ask=Decimal("0.50"),
                reason="taken",
                fee=Decimal("0.01"),
                key_instrument_id=other_instrument,
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.55"),
                existing_instrument_ids=(other_instrument,),
            )
        # 0.51 + 0.55 == 1.06 > 1
        assert got == Refusal(STATION_DAY_ADMISSION_REASON)

    def test_an_existing_yes_trial_plus_a_candidate_summing_to_exactly_one_is_admitted(
        self, store_path: Path,
    ) -> None:
        other_instrument = "POLY-LAX-TMAX-70-71"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=other_instrument,
                ask=Decimal("0.40"),
                reason="taken",
                fee=Decimal("0.00"),
                key_instrument_id=other_instrument,
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.60"),
                existing_instrument_ids=(other_instrument,),
            )
        assert got is None

    def test_a_no_leg_candidate_uses_one_minus_be_as_its_cell_probability(
        self, store_path: Path,
    ) -> None:
        """``q = 1 - BE`` for NO -- a cheap NO (``BE=0.10`` -> ``q=0.90``)
        plus an existing YES leg on another rung (``q=0.15``) sums to
        ``1.05 > 1`` and is refused."""
        other_instrument = "POLY-LAX-TMAX-70-71"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=other_instrument,
                ask=Decimal("0.14"),
                reason="taken",
                fee=Decimal("0.01"),
                key_instrument_id=other_instrument,
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "no",
                Decimal("0.10"),
                existing_instrument_ids=(other_instrument,),
            )
        assert got == Refusal(STATION_DAY_ADMISSION_REASON)

    def test_an_existing_record_missing_fee_refuses_the_candidate_rather_than_guessing(
        self, store_path: Path,
    ) -> None:
        """A legacy TRIAL record with no ``fee`` (pre-slice-4 write) makes
        its ``q`` unknown -- R3-7: never guess, refuse."""
        other_instrument = "POLY-LAX-TMAX-70-71"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=other_instrument,
                ask=Decimal("0.10"),
                reason="taken",
                key_instrument_id=other_instrument,
                # no fee -- legacy shape
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.10"),
                existing_instrument_ids=(other_instrument,),
            )
        assert got == Refusal(STATION_DAY_ADMISSION_REASON)

    def test_the_2026_09_15_mdw_yes_pair_admits_at_the_arm_time_gate(
        self, store_path: Path,
    ) -> None:
        """ADM-1 regression pin (docs/core/PROGRESS.md row ADM-1): MDW took
        YES [80,81] @0.11 then YES [82,83] @0.24 with NO arm-time admission
        check at all (the defect). Their break-evens (q for a YES leg is
        `BE` itself, `_cell_probability`) sum to 0.3581 + 0.5944 = 0.9525 <=
        1 -- the arm-time gate this fix wires onto the YES path must ADMIT
        this exact historical pair, not merely some synthetic one, once a
        FILLED prior leg's `fee` is genuinely known (the strategy-level
        regression, `test_two_yes_rungs_on_one_station_day_both_arm_before_
        either_fills`, covers the currently-reachable no-prior-fill shape;
        this pins the arithmetic itself against the real incident numbers).
        """
        first_leg = "POLY-MDW-TMAX-80-81"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=first_leg,
                ask=Decimal("0.11"),
                reason="taken",
                fee=Decimal("0.3581") - Decimal("0.11"),
                key_instrument_id=first_leg,
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.5944"),
                existing_instrument_ids=(first_leg,),
            )
        assert got is None

    def test_a_merely_refused_existing_record_does_not_count_toward_the_sum(
        self, store_path: Path,
    ) -> None:
        other_instrument = "POLY-LAX-TMAX-70-71"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=other_instrument,
                ask=Decimal("0.10"),
                reason="not_executable",
                key_instrument_id=other_instrument,
                # no fee, but reason is not a fill -- must be skipped, not refused
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.90"),
                existing_instrument_ids=(other_instrument,),
            )
        assert got is None

    # -----------------------------------------------------------------
    # ADM-1: Sigma-q must count a committed-but-unrecorded leg (the
    # create-path window between the durable fill write and the TRIAL/
    # TAKEN record landing on a later engine turn).
    # -----------------------------------------------------------------

    def test_a_committed_fill_without_a_taken_record_counts_toward_sigma_q(
        self, store_path: Path,
    ) -> None:
        """RED (pre-fix): leg A's fill is committed but its TRIAL record
        has not landed -- the sibling candidate must still see A's spent
        capital via ``pending_fills``."""
        other_instrument = "POLY-LAX-TMAX-70-71.POLYMARKET_US"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path):
            fill = _fill_record(
                venue_order_id="V-1",
                instrument_id=other_instrument,
                qty="1",
                cost="0.50",
                fee="0.01",
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.55"),
                existing_instrument_ids=(other_instrument,),
                pending_fills={other_instrument: fill},
            )
        # be = (0.50 + 0.01) / 1 = 0.51; 0.51 + 0.55 == 1.06 > 1.
        assert got == Refusal(STATION_DAY_ADMISSION_REASON)

    def test_a_leg_with_both_a_taken_record_and_a_pending_fill_counts_once_from_taken(
        self, store_path: Path,
    ) -> None:
        """AC2 / r1.1 guard 2: once a leg has a genuine TRIAL record,
        ``pending_fills`` for that SAME leg is never consulted -- otherwise
        the leg would be double-counted."""
        other_instrument = "POLY-LAX-TMAX-70-71.POLYMARKET_US"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path) as intent_latch:
            latch = open_trial_day_latch(intent_latch)
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=other_instrument,
                ask=Decimal("0.10"),
                reason="taken",
                fee=Decimal("0.01"),
                key_instrument_id=other_instrument,
            )
            # If this were consulted instead of (or alongside) the TAKEN
            # record, its own be (0.90) would push the sum above 1.
            inflated_fill = _fill_record(
                venue_order_id="V-2",
                instrument_id=other_instrument,
                qty="1",
                cost="0.89",
                fee="0.01",
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.55"),
                existing_instrument_ids=(other_instrument,),
                pending_fills={other_instrument: inflated_fill},
            )
        # TAKEN be = 0.10 + 0.01 = 0.11; 0.11 + 0.55 = 0.66 <= 1 -- admitted
        # only if the inflated pending fill was correctly ignored.
        assert got is None

    def test_a_pending_fill_with_zero_fee_computes_a_known_q(
        self, store_path: Path,
    ) -> None:
        """A zero fee on a ``DurableFillRecord`` is a KNOWN value (the
        field is required, unlike the optional ``TrialDayRecord.fee``) --
        it must not be treated as the legacy 'unknown fee' refusal."""
        other_instrument = "POLY-LAX-TMAX-70-71.POLYMARKET_US"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path):
            fill = _fill_record(
                venue_order_id="V-3",
                instrument_id=other_instrument,
                qty="1",
                cost="0.30",
                fee="0",
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.55"),
                existing_instrument_ids=(other_instrument,),
                pending_fills={other_instrument: fill},
            )
        # be = 0.30 / 1 = 0.30; 0.30 + 0.55 = 0.85 <= 1 -- admitted.
        assert got is None

    def test_a_pending_fill_with_zero_cumulative_qty_is_refused_rather_than_divide(
        self, store_path: Path,
    ) -> None:
        """r1.1 guard 1: ``cumulative_qty <= 0`` means the average cost is
        unknown -- never divide, refuse the whole candidate."""
        other_instrument = "POLY-LAX-TMAX-70-71.POLYMARKET_US"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path):
            fill = _fill_record(
                venue_order_id="V-4",
                instrument_id=other_instrument,
                qty="0",
                cost="0",
                fee="0",
            )
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.10"),
                existing_instrument_ids=(other_instrument,),
                pending_fills={other_instrument: fill},
            )
        assert got == Refusal(STATION_DAY_ADMISSION_REASON)

    def test_an_in_flight_leg_with_no_trial_record_and_no_pending_fill_contributes_zero(
        self, store_path: Path,
    ) -> None:
        """A leg that is merely IN_FLIGHT -- no TRIAL record and no
        committed fill yet -- contributes 0, exactly as before ADM-1."""
        other_instrument = "POLY-LAX-TMAX-70-71.POLYMARKET_US"
        store = SqliteStateStore(store_path)
        with open_submit_intent_latch(store, store_path):
            got = station_day_admission(
                store,
                DEFAULT_TRIAL_KEY_PREFIX,
                STATION,
                CLIMATE_DAY,
                "yes",
                Decimal("0.90"),
                existing_instrument_ids=(other_instrument,),
                pending_fills={},
            )
        assert got is None


try:
    from hypothesis import given
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover - hypothesis is a declared dev dependency
    given = None  # type: ignore[assignment]
    st = None  # type: ignore[assignment]


@pytest.mark.skipif(given is None, reason="hypothesis not installed")
@given(
    bes=st.lists(
        st.decimals(min_value="0.01", max_value="0.99", places=2), min_size=1, max_size=4,
    )
)
def test_yes_only_rungs_summing_at_or_below_one_are_never_refused(
    bes: list[Decimal], tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """R3-7: YES-only days cannot breach under the edge rule -- a property
    test over random per-rung BEs that themselves sum to at most 1 must
    never see this gate fire, for every prefix count."""
    total = sum(bes)
    if total > Decimal(1):
        return  # a filtered draw; equivalent to hypothesis's `assume`
    store_path = tmp_path_factory.mktemp("station_day_admission") / "state.db"
    prefix = DEFAULT_TRIAL_KEY_PREFIX
    existing: list[str] = []
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        latch = open_trial_day_latch(intent_latch)
        for index, be in enumerate(bes[:-1]):
            instrument_id = f"POLY-LAX-RUNG-{index}"
            latch.consume(
                STATION,
                CLIMATE_DAY,
                latched_at_ns=NOW_NS,
                instrument_id=instrument_id,
                ask=be,
                reason="taken",
                fee=Decimal(0),
                key_instrument_id=instrument_id,
            )
            existing.append(instrument_id)
        got = station_day_admission(
            store,
            prefix,
            STATION,
            CLIMATE_DAY,
            "yes",
            bes[-1],
            existing_instrument_ids=existing,
        )
    assert got is None


class TestStartupEvidenceOpenOrders:
    """RESTING_BID_HUNT Rev 2 §4.3: the never-arm gate fails closed on the
    open-order enumeration -- absent, refused, malformed or NON-EMPTY all
    refuse. ``startup_evidence_permits_arm`` is the single predicate both
    the boot walk (``continuous_strategy.py:582``) and the re-arm gate
    (``:1765``) consult, so the refusal lands on both without either
    caller changing."""

    @staticmethod
    def _complete(**overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "v": 1,
            "ts_ns": NOW_NS,
            "position_read_refused": False,
            "eof_complete": True,
            "fill_walk_complete": True,
            "positions": [],
            "open_orders_read_refused": False,
            "open_orders": [],
        }
        base.update(overrides)
        return base

    def test_a_complete_record_with_an_empty_open_order_set_arms(self) -> None:
        assert startup_evidence_permits_arm(self._complete()) is True

    def test_a_record_predating_the_open_order_fields_refuses(self) -> None:
        """Fail closed: a v1 record written by an older client carries no
        open-order evidence, which is UNKNOWN, never 'none open'."""
        evidence = self._complete()
        del evidence["open_orders_read_refused"]
        del evidence["open_orders"]
        assert startup_evidence_permits_arm(evidence) is False

    @pytest.mark.parametrize(
        "overrides",
        [
            {"open_orders_read_refused": True},
            {"open_orders_read_refused": None},
            {"open_orders_read_refused": "false"},
            {"open_orders": None},
            {"open_orders": {}},
            {"open_orders": "[]"},
            {"open_orders": [{"venue_order_id": "RESTING0001A", "market_slug": "x"}]},
        ],
    )
    def test_refused_malformed_or_non_empty_open_orders_refuse(
        self, overrides: dict[str, object],
    ) -> None:
        assert startup_evidence_permits_arm(self._complete(**overrides)) is False

    def test_refusal_reason_names_the_open_order_presence(self) -> None:
        from breezy.strategy.current_rung_hold.trial_day_latch import (
            STARTUP_OPEN_ORDERS_PRESENT_REASON,
            startup_evidence_refusal_reason,
        )

        present = self._complete(open_orders=[{"venue_order_id": "R1", "market_slug": "x"}])
        assert startup_evidence_refusal_reason(present) == STARTUP_OPEN_ORDERS_PRESENT_REASON
        assert STARTUP_OPEN_ORDERS_PRESENT_REASON == "startup_open_orders_present"
        assert startup_evidence_refusal_reason(self._complete()) is None
        assert (
            startup_evidence_refusal_reason(self._complete(open_orders_read_refused=True))
            == "open_orders_read_refused"
        )
        assert startup_evidence_refusal_reason(None) == "evidence_absent"

    def test_permits_arm_is_exactly_reason_is_none(self) -> None:
        from breezy.strategy.current_rung_hold.trial_day_latch import (
            startup_evidence_refusal_reason,
        )

        for evidence in (
            None,
            self._complete(),
            self._complete(open_orders_read_refused=True),
            self._complete(position_read_refused=True),
            self._complete(v=2),
        ):
            assert startup_evidence_permits_arm(evidence) is (
                startup_evidence_refusal_reason(evidence) is None
            )

    def test_confirms_absent_flat_also_refuses_on_an_open_order(self) -> None:
        present = self._complete(open_orders=[{"venue_order_id": "R1", "market_slug": "x"}])
        assert (
            startup_evidence_confirms_absent_flat(
                present, "never-listed", now_ns=NOW_NS, max_age_ns=10**12,
            )
            is False
        )
