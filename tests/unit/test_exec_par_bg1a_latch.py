"""EXEC-PAR BG-1a: single-writer latch methods for the durable D-PREREG records."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    Amendment,
    CleanupDemotion,
    EpochRow,
    ExcludedDay,
    ForceK1Cleared,
    ForceK1Flag,
    StageEvalDry,
    StageReset,
    StopVerdict,
)
from breezy.runtime.submit_intent import (
    SubmitIntentCorrupt,
    SubmitIntentLatch,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_set = False

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        if self.fail_set:
            raise OSError("simulated set failure")
        self.data[key] = value


class _DepthMutex:
    """A non-reentrant lock that raises if the same code path nests it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.depth = 0
        self.max_depth = 0

    def __enter__(self) -> None:
        self.max_depth = max(self.max_depth, self.depth + 1)
        if self.depth:
            raise AssertionError("mutex nested")
        self.depth += 1
        self._lock.acquire()

    def __exit__(self, *exc: object) -> None:
        self.depth -= 1
        self._lock.release()


@contextmanager
def _open(store: _Store, tmp_path: Path) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(store, tmp_path / "state.db", clock_ns=lambda: 777) as latch:
        yield latch


P = EXEC_PAR_PREFIX
RESET = StageReset(ts=5, cause="stop_clear", halt_ts=4)
EPOCH = EpochRow(commit_sha="abc", effective_k=2, force_reason=None, boot_ts=100)
DRY = StageEvalDry(verdict="PASS", input_complete=True, ts=7)
CLEARED = ForceK1Cleared(ts=8, halt_ts=4, incident_report="docs/r.md")
STOP = StopVerdict(reason="s5_cp", ts_ns=11)
DEMO = CleanupDemotion(from_k=4, to_k=2, ts_ns=12, reason="low_volume")
FLAG = ForceK1Flag(reason="s5_cp", ts_ns=13, set_by="watcher")
AMEND = Amendment(ts_ns=3, commit_sha="abc", note="A1")

Op = Callable[[Any], Any]
# (id, writer, reader, expected record, key the READER depends on)
CASES: list[tuple[str, Op, Op, object, str]] = [
    (
        "stage_reset",
        lambda x: x.write_stage_reset(RESET),
        lambda x: x.read_stage_reset(),
        RESET,
        P + "stage_reset",
    ),
    (
        "epoch",
        lambda x: x.write_epoch_row(EPOCH),
        lambda x: x.read_latest_epoch_row(),
        EPOCH,
        P + "epoch/100",
    ),
    (
        "epoch_by_ts",
        lambda x: x.write_epoch_row(EPOCH),
        lambda x: x.read_epoch_row(100),
        EPOCH,
        P + "epoch/100",
    ),
    (
        "amendment",
        lambda x: x.write_amendment(AMEND),
        lambda x: x.read_amendment(3),
        AMEND,
        P + "amendment/3",
    ),
    (
        "dry",
        lambda x: x.write_stage_eval_dry(DRY),
        lambda x: x.read_stage_eval_dry(),
        DRY,
        P + "stage_eval_dry",
    ),
    (
        "cleared",
        lambda x: x.write_force_k1_cleared(CLEARED),
        lambda x: x.read_force_k1_cleared(),
        CLEARED,
        P + "force_k1_cleared",
    ),
    (
        "stop",
        lambda x: x.write_stop_verdict(STOP),
        lambda x: x.read_latest_stop_verdict(),
        STOP,
        P + "stop_verdict/11",
    ),
    (
        "stop_by_ts",
        lambda x: x.write_stop_verdict(STOP),
        lambda x: x.read_stop_verdict(11),
        STOP,
        P + "stop_verdict/11",
    ),
    (
        "demotion",
        lambda x: x.write_cleanup_demotion(DEMO),
        lambda x: x.read_latest_cleanup_demotion(),
        DEMO,
        P + "cleanup_demotion/12",
    ),
    (
        "demotion_by_ts",
        lambda x: x.write_cleanup_demotion(DEMO),
        lambda x: x.read_cleanup_demotion(12),
        DEMO,
        P + "cleanup_demotion/12",
    ),
    (
        "flag",
        lambda x: x.write_force_k1_flag(FLAG),
        lambda x: x.read_force_k1_flag(),
        FLAG,
        P + "force_k1",
    ),
]
IDS = [c[0] for c in CASES]
ARGS = "name,write,read,expected,key"


@pytest.mark.parametrize(ARGS, CASES, ids=IDS)
def test_record_round_trips_through_the_store(
    tmp_path: Path, name: str, write: Op, read: Op, expected: object, key: str
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert read(latch) is None
        write(latch)
        assert read(latch) == expected
    assert key in store.data


@pytest.mark.parametrize(ARGS, CASES, ids=IDS)
def test_garbled_stored_bytes_raise_typed_error_never_a_default(
    tmp_path: Path, name: str, write: Op, read: Op, expected: object, key: str
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        write(latch)
        store.data[key] = b"\x00garbled"
        with pytest.raises(SubmitIntentCorrupt):
            read(latch)


@pytest.mark.parametrize(ARGS, CASES, ids=IDS)
def test_not_held_calls_raise(
    tmp_path: Path, name: str, write: Op, read: Op, expected: object, key: str
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        pass
    with pytest.raises(SubmitIntentLockNotHeld):
        write(latch)
    with pytest.raises(SubmitIntentLockNotHeld):
        read(latch)
    assert store.data == {}


@pytest.mark.parametrize(ARGS, CASES, ids=IDS)
def test_no_mutex_nesting_and_store_errors_propagate(
    tmp_path: Path, name: str, write: Op, read: Op, expected: object, key: str
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        mutex = _DepthMutex()
        setattr(latch, "_mutex", mutex)  # noqa: B010 - swap the lock for the depth probe
        write(latch)
        read(latch)
        assert mutex.max_depth <= 1
        store.fail_set = True
        with pytest.raises(OSError, match="simulated"):
            write(latch)


def test_pointer_to_missing_row_is_corrupt_not_none(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_stop_verdict(STOP)
        del store.data[P + "stop_verdict/11"]
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_latest_stop_verdict()


def test_latest_pointer_follows_the_newest_write(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        latch.write_stop_verdict(StopVerdict("a", 1))
        latch.write_stop_verdict(StopVerdict("b", 2))
        assert latch.read_latest_stop_verdict() == StopVerdict("b", 2)
        assert latch.read_stop_verdict(1) == StopVerdict("a", 1)


def test_excluded_days_append_dedupes_by_day_first_wins(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert latch.read_excluded_days() == ()
        assert latch.add_excluded_day(ExcludedDay("2026-12-02", "gappy", 2)) is True
        assert latch.add_excluded_day(ExcludedDay("2026-12-01", "gappy", 1)) is True
        assert latch.add_excluded_day(ExcludedDay("2026-12-02", "other", 9)) is False
        assert [d.day for d in latch.read_excluded_days()] == ["2026-12-01", "2026-12-02"]
        assert latch.read_excluded_days()[1].cause == "gappy"
        store.data[P + "excluded_days"] = b"{"
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_excluded_days()
        with pytest.raises(SubmitIntentCorrupt):
            latch.add_excluded_day(ExcludedDay("2026-12-03", "x", 3))


def test_epoch_stop_ts_set_once_and_requires_the_row(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        assert latch.write_epoch_stop_ts(100, 150) is False
        latch.write_epoch_row(EPOCH)
        assert latch.write_epoch_stop_ts(100, 150) is True
        assert latch.write_epoch_stop_ts(100, 999) is False
        row = latch.read_epoch_row(100)
        assert row is not None
        assert row.stop_ts == 150


def test_force_k1_flag_clear_leaves_a_tombstone_and_unreadable_never_defaults(
    tmp_path: Path,
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_force_k1_flag(FLAG)
        latch.clear_force_k1_flag(99)
        assert latch.read_force_k1_flag() is None
        assert P + "force_k1" in store.data
        store.data[P + "force_k1"] = b"junk"
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_force_k1_flag()


def test_boot_ns_is_a_read_only_view_of_the_construction_time_clock(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        assert latch.boot_ns == 777
        with pytest.raises(AttributeError):
            setattr(latch, "boot_ns", 1)  # noqa: B010 - the property must have no setter


def test_k1_behaviour_untouched_no_exec_par_keys_unless_written(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert latch.current() is None
        latch.arm("f" * 64, now_ns=1)
    assert not [k for k in store.data if k.startswith(P)]
