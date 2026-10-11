"""EXEC-PAR BG-6: the ``SubmitIntentLatch._breaker_denial`` stamp gate (pending, stale, unreadable).

Real latch over an in-memory store that records every ``get``. The gate is K>1 only: at K=1 the
store sees no new read, and entries-only holds for every BG-6 reason (exits are never denied).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from breezy.runtime.exec_par_records import EXEC_PAR_PREFIX, StageEvalStamp
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    RetirementReason,
    SubmitIntentLatch,
    open_submit_intent_latch,
)

NS = 1_000_000_000
HOUR = 3600 * NS
BOOT = 5_000 * HOUR
STAMP_KEY = EXEC_PAR_PREFIX + "stage_eval/stamp"


def _fp(n: int) -> str:
    return f"{n:08x}" + "a1b2c3d4" * 7


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.gets: list[str] = []
        self.fail_get: set[str] = set()

    def get(self, key: str) -> bytes | None:
        self.gets.append(key)
        if key in self.fail_get:
            raise OSError("injected get failure")
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


class _Clock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


@contextmanager
def _open(store: _Store, tmp_path: Path, clock: _Clock, *, k: int) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(
        store, tmp_path / "s.db", max_slots=k, v2_predicate=lambda: True, clock_ns=clock
    ) as latch:
        yield latch


def _healthy_heartbeat(latch: SubmitIntentLatch, clock: _Clock) -> None:
    latch.write_breaker_heartbeat(hb_ns=clock.now, resolver_pass_ns=clock.now)


def test_k2_no_stamp_denies_entries_with_boot_pending_and_never_exits(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 10 * NS
        _healthy_heartbeat(latch, clock)
        assert latch.admission_refusal("S-A", False) == "stage_eval_boot_pending"
        assert latch.admission_refusal("S-A", True) is None  # exits are never denied


def test_boot_pending_also_holds_inside_the_absent_record_grace_window(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 5 * NS  # no breaker record yet, within the 60 s grace
        assert latch.admission_refusal("S-A", False) == "stage_eval_boot_pending"


def test_boot_pending_lifecycle_previous_boot_stamp_then_this_boot_stamp(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 10 * NS
        _healthy_heartbeat(latch, clock)
        assert latch.boot_ns == BOOT
        # a stamp from a previous boot never counts
        latch.write_stage_eval_stamp(StageEvalStamp(BOOT + 5 * NS, BOOT - 1))
        assert latch.admission_refusal("S-A", False) == "stage_eval_boot_pending"
        # right boot_ns but written before this boot: still pending
        latch.write_stage_eval_stamp(StageEvalStamp(BOOT - 1, BOOT))
        assert latch.admission_refusal("S-A", False) == "stage_eval_boot_pending"
        # this boot's stamp clears the gate
        latch.write_stage_eval_stamp(StageEvalStamp(BOOT + 6 * NS, latch.boot_ns))
        assert latch.admission_refusal("S-A", False) is None


def test_stale_stamp_denies_at_26_hours_plus_one_ns_and_a_new_stamp_clears_it(
    tmp_path: Path,
) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        stamp_ts = BOOT + 5 * NS
        latch.write_stage_eval_stamp(StageEvalStamp(stamp_ts, BOOT))
        clock.now = stamp_ts + 26 * HOUR
        _healthy_heartbeat(latch, clock)
        assert latch.admission_refusal("S-A", False) is None  # exactly 26 h
        clock.now += 1
        _healthy_heartbeat(latch, clock)
        assert latch.admission_refusal("S-A", False) == "stage_eval_stamp_stale"
        assert latch.admission_refusal("S-A", True) is None
        latch.write_stage_eval_stamp(StageEvalStamp(clock.now, BOOT))
        assert latch.admission_refusal("S-A", False) is None


def test_never_written_stamp_is_stale_once_the_boot_is_26_hours_old(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 26 * HOUR
        _healthy_heartbeat(latch, clock)
        assert latch.admission_refusal("S-A", False) == "stage_eval_boot_pending"
        clock.now += 1
        _healthy_heartbeat(latch, clock)
        assert latch.admission_refusal("S-A", False) == "stage_eval_stamp_stale"


def test_garbled_or_unreadable_stamp_row_denies_fail_closed(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 10 * NS
        _healthy_heartbeat(latch, clock)
        store.data[STAMP_KEY] = b"{garbled"
        assert latch.admission_refusal("S-A", False) == "stage_eval_stamp_unreadable"
        assert latch.admission_refusal("S-A", True) is None
        del store.data[STAMP_KEY]
        store.fail_get.add(STAMP_KEY)
        assert latch.admission_refusal("S-A", False) == "stage_eval_stamp_unreadable"


def test_existing_denials_keep_priority_and_cost_no_stamp_read(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 10 * NS
        _healthy_heartbeat(latch, clock)
        latch.write_breaker_halt("stuck_slots", ts_ns=clock.now)
        store.gets.clear()
        assert latch.admission_refusal("S-A", False) == "breaker_halted"
        assert STAMP_KEY not in store.gets
        clock.now += 61 * NS
        latch.reset_breaker_halt()
        store.gets.clear()
        assert latch.admission_refusal("S-A", False) == "breaker_heartbeat_stale"
        assert STAMP_KEY not in store.gets
        clock.now = BOOT + 3 * HOUR  # absent-record case is unchanged too
        store.data.pop(BREAKER_KEY)
        store.gets.clear()
        assert latch.admission_refusal("S-A", False) == "breaker_absent"
        assert STAMP_KEY not in store.gets


def test_one_stamp_get_per_entry_admission_and_none_for_exits(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 10 * NS
        _healthy_heartbeat(latch, clock)
        latch.write_stage_eval_stamp(StageEvalStamp(BOOT + 5 * NS, BOOT))
        store.gets.clear()
        assert latch.admission_refusal("S-A", False) is None
        assert store.gets.count(STAMP_KEY) == 1
        store.gets.clear()
        assert latch.admission_refusal("S-A", True) is None
        assert STAMP_KEY not in store.gets and BREAKER_KEY not in store.gets


def test_entries_only_pin_exits_are_armed_under_every_bg6_denial(tmp_path: Path) -> None:
    """Exits and the resolver are never blocked by a BG-6 reason (r3.2 E6, r4 1a)."""
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 10 * NS
        _healthy_heartbeat(latch, clock)
        # boot pending: an entry is refused, an exit admits and arms
        assert latch.admission_refusal("S-A", False) == "stage_eval_boot_pending"
        assert latch.admission_refusal("S-A", True) is None
        first = latch.arm_slot(_fp(1), slug="S-A", is_exit=True, now_ns=clock.now)
        assert first.is_exit is True
        # stale stamp: same
        latch.write_stage_eval_stamp(StageEvalStamp(BOOT + 1, BOOT))
        clock.now = BOOT + 40 * HOUR
        _healthy_heartbeat(latch, clock)
        assert latch.admission_refusal("S-B", False) == "stage_eval_stamp_stale"
        second = latch.arm_slot(_fp(2), slug="S-B", is_exit=True, now_ns=clock.now)
        assert second.is_exit is True
        # unreadable stamp: same
        store.data[STAMP_KEY] = b"{garbled"
        assert latch.admission_refusal("S-C", False) == "stage_eval_stamp_unreadable"
        third = latch.arm_slot(_fp(3), slug="S-C", is_exit=True, now_ns=clock.now)
        assert third.is_exit is True
        # the resolver's retire path is untouched by every one of the three reasons
        assert latch.retire(first.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=clock.now)


def test_k1_identical_denial_behaviour_and_zero_new_reads(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT + 10_000 * HOUR)
    with _open(store, tmp_path, clock, k=1) as latch:
        clock.now += 120 * NS  # past the absent-record grace
        store.gets.clear()
        assert latch.admission_refusal("S-A", False) is None
        assert latch.admission_refusal("S-A", True) is None
        assert STAMP_KEY not in store.gets and BREAKER_KEY not in store.gets
        # even a direct call of the denial keeps the configured-K gate (no stamp read, no record)
        store.gets.clear()
        assert latch._breaker_denial(clock.now) == "breaker_absent"
        assert store.gets == [BREAKER_KEY]


def test_forced_k1_skips_the_breaker_and_the_stamp_entirely(tmp_path: Path) -> None:
    store, clock = _Store(), _Clock(BOOT)
    with _open(store, tmp_path, clock, k=2) as latch:
        clock.now = BOOT + 10 * NS
        latch.force_k1("test")
        store.gets.clear()
        assert latch.admission_refusal("S-A", False) is None
        assert STAMP_KEY not in store.gets and BREAKER_KEY not in store.gets


@pytest.mark.parametrize("reason", ["stage_eval_boot_pending", "stage_eval_stamp_stale"])
def test_denial_labels_are_the_spec_names(reason: str) -> None:
    from breezy.runtime import exec_par_stamp_gate as gate

    assert reason in {gate.REASON_BOOT_PENDING, gate.REASON_STAMP_STALE}
