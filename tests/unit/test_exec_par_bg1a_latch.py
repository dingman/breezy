"""EXEC-PAR BG-1a: single-writer latch methods for the durable D-PREREG records."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.exec_par_records import (
    encode_force_k1_tombstone,
    ForceK1Kind,
    ForceK1State,
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

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

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
LATE_CLEARED = ForceK1Cleared(ts=20, halt_ts=4, incident_report="docs/r.md")
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
        lambda x: x.read_force_k1_flag().record,
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


NON_FLAG = [c for c in CASES if c[0] != "flag"]


@pytest.mark.parametrize(ARGS, NON_FLAG, ids=[c[0] for c in NON_FLAG])
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
        store.data.clear()  # keyed rows are idempotent; force a real set
        store.fail_set = True
        with pytest.raises(OSError, match="simulated"):
            write(latch)


def test_reader_sees_a_row_written_before_a_crash_no_pointer_to_trust(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_stop_verdict(STOP)
        latch.write_cleanup_demotion(DEMO)
        latch.write_epoch_row(EPOCH)
    # nothing else was ever written (crash): a fresh latch must still see the rows
    assert not [k for k in store.data if k.endswith("/latest")]
    with _open(store, tmp_path) as latch:
        assert latch.read_latest_stop_verdict() == STOP
        assert latch.read_latest_cleanup_demotion() == DEMO
        assert latch.read_latest_epoch_row() == EPOCH


def test_latest_is_the_max_ts_regardless_of_write_order(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        latch.write_stop_verdict(StopVerdict("b", 2))
        latch.write_stop_verdict(StopVerdict("a", 1))
        assert latch.read_latest_stop_verdict() == StopVerdict("b", 2)
        assert latch.read_stop_verdict(1) == StopVerdict("a", 1)


def test_stop_verdicts_since_returns_every_marker_at_or_after_ts(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        assert latch.read_stop_verdicts_since(0) == ()
        for ts in (30, 10, 20):
            latch.write_stop_verdict(StopVerdict(f"r{ts}", ts))
        assert [m.ts_ns for m in latch.read_stop_verdicts_since(20)] == [20, 30]
        assert latch.read_stop_verdicts_since(31) == ()


def test_scan_fails_closed_on_stray_or_mismatched_rows(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_stop_verdict(StopVerdict("a", 1))
        store.data[P + "stop_verdict/notanint"] = b"{}"
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_latest_stop_verdict()
        del store.data[P + "stop_verdict/notanint"]
        store.data[P + "stop_verdict/5"] = store.data[P + "stop_verdict/1"]  # ts_ns 1 under key 5
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_stop_verdicts_since(0)


@pytest.mark.parametrize(
    ("write", "first", "other"),
    [
        (lambda x, r: x.write_stop_verdict(r), STOP, StopVerdict("different", 11)),
        (lambda x, r: x.write_epoch_row(r), EPOCH, EpochRow("zzz", 4, None, 100)),
        (lambda x, r: x.write_amendment(r), AMEND, Amendment(3, "abc", "other note")),
        (lambda x, r: x.write_cleanup_demotion(r), DEMO, CleanupDemotion(4, 1, 12, "low_volume")),
    ],
    ids=["stop", "epoch", "amendment", "demotion"],
)
def test_keyed_rows_are_exclusive_identical_rewrite_idempotent(
    tmp_path: Path, write: Any, first: Any, other: Any
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        write(latch, first)
        before = dict(store.data)
        write(latch, first)
        assert store.data == before
        with pytest.raises(ValueError, match="conflict"):
            write(latch, other)
        assert store.data == before


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


def test_epoch_stop_ts_set_once_and_raises_on_an_absent_row(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch:
        with pytest.raises(ValueError, match="absent"):
            latch.write_epoch_stop_ts(100, 150)
        latch.write_epoch_row(EPOCH)
        assert latch.write_epoch_stop_ts(100, 150) is True
        assert latch.write_epoch_stop_ts(100, 999) is False
        row = latch.read_epoch_row(100)
        assert row is not None
        assert row.stop_ts == 150


def test_stage_reset_rejects_a_lower_ts_and_allows_equal_or_higher(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_stage_reset(RESET)
        before = dict(store.data)
        with pytest.raises(ValueError, match="monotonic"):
            latch.write_stage_reset(StageReset(ts=4, cause="k_change", halt_ts=None))
        assert store.data == before
        latch.write_stage_reset(RESET)  # identical rewrite at an equal ts is idempotent
        latch.write_stage_reset(StageReset(ts=6, cause="k_change", halt_ts=None))
        assert latch.read_stage_reset() == StageReset(ts=6, cause="k_change", halt_ts=None)
        store.data[P + "stage_reset"] = b"junk"
        with pytest.raises(SubmitIntentCorrupt):
            latch.write_stage_reset(StageReset(ts=9, cause="k_change", halt_ts=None))


def test_add_excluded_day_invalid_row_raises_value_error(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        with pytest.raises(ValueError):
            latch.add_excluded_day(ExcludedDay("", "x", 1))
        assert store.data == {}


def test_force_k1_flag_is_tri_state_and_never_raises_for_corruption(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert latch.read_force_k1_flag() == ForceK1State(ForceK1Kind.CLEARED, None)
        latch.write_force_k1_flag(FLAG)
        assert latch.read_force_k1_flag() == ForceK1State(ForceK1Kind.SET, FLAG)
        for junk in (b"junk", b'{"v":1}', b""):
            store.data[P + "force_k1"] = junk
            assert latch.read_force_k1_flag() == ForceK1State(ForceK1Kind.UNREADABLE, None)


def test_clear_force_k1_flag_requires_matching_cleared_record_and_positive_ts(
    tmp_path: Path,
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_force_k1_flag(FLAG)
        flag_bytes = store.data[P + "force_k1"]
        for bad_ts in (0, -1):
            with pytest.raises(ValueError, match="positive"):
                latch.clear_force_k1_flag(bad_ts)
        with pytest.raises(ValueError, match="force_k1_cleared"):
            latch.clear_force_k1_flag(20)  # no cleared record at all
        latch.write_force_k1_cleared(LATE_CLEARED)
        with pytest.raises(ValueError, match="force_k1_cleared"):
            latch.clear_force_k1_flag(21)  # ts mismatch
        assert store.data[P + "force_k1"] == flag_bytes
        latch.clear_force_k1_flag(20)
        assert latch.read_force_k1_flag().kind is ForceK1Kind.CLEARED
        assert P + "force_k1" in store.data


def test_clear_force_k1_flag_raises_on_garbled_flag_or_cleared_record(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_force_k1_cleared(LATE_CLEARED)
        store.data[P + "force_k1"] = b"junk"
        with pytest.raises(SubmitIntentCorrupt):
            latch.clear_force_k1_flag(20)
        assert store.data[P + "force_k1"] == b"junk"
        latch.write_force_k1_flag(FLAG)
        store.data[P + "force_k1_cleared"] = b"junk"
        with pytest.raises(SubmitIntentCorrupt):
            latch.clear_force_k1_flag(20)


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


def test_stale_clear_record_from_an_earlier_incident_cannot_clear_a_newer_flag(
    tmp_path: Path,
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_force_k1_cleared(CLEARED)  # ts 8: the earlier incident
        latch.write_force_k1_flag(FLAG)  # ts_ns 13: the newer flag
        before = store.data[P + "force_k1"]
        with pytest.raises(ValueError, match="newer"):
            latch.clear_force_k1_flag(8)
        assert store.data[P + "force_k1"] == before
        latch.write_force_k1_cleared(LATE_CLEARED)
        latch.clear_force_k1_flag(20)
        assert latch.read_force_k1_flag().kind is ForceK1Kind.CLEARED


@pytest.mark.parametrize("suffix", ["007", "+7", "-7", " 7", "7 ", "0x7", "\u0667"])
def test_scan_rejects_non_canonical_decimal_suffixes(tmp_path: Path, suffix: str) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_stop_verdict(StopVerdict("a", 7))
        store.data[P + "stop_verdict/" + suffix] = store.data[P + "stop_verdict/7"]
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_latest_stop_verdict()


def test_stage_reset_equal_ts_different_content_raises_identical_is_idempotent(
    tmp_path: Path,
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_stage_reset(RESET)
        before = dict(store.data)
        latch.write_stage_reset(RESET)
        assert store.data == before
        with pytest.raises(ValueError, match="conflict"):
            latch.write_stage_reset(StageReset(ts=5, cause="k_change", halt_ts=None))
        assert store.data == before


@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_tombstone_reads_back_unreadable(tmp_path: Path, bad: int) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        store.data[P + "force_k1"] = encode_force_k1_tombstone(bad)
        assert latch.read_force_k1_flag() == ForceK1State(ForceK1Kind.UNREADABLE, None)
