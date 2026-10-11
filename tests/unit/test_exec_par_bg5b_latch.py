"""EXEC-PAR BG-5b: single-writer latch rows for the stage evaluator (stamp, looks, ...)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    DayCountsDelta,
    EpochRow,
    ExecParRecordError,
    GappyMark,
    LookRow,
    RebuildRow,
    ReconcilePhase,
    StageEvalLiveness,
    StageEvalStamp,
    StageReportDoc,
    decode_record,
    encode_record,
)
from breezy.runtime.submit_intent import (
    SubmitIntentCorrupt,
    SubmitIntentLatch,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)

P = EXEC_PAR_PREFIX


class _Store:
    def __init__(self, *, with_delete: bool = True) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_set = False
        if not with_delete:
            self.delete = None  # type: ignore[assignment]

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def set(self, key: str, value: bytes) -> None:
        if self.fail_set:
            raise OSError("simulated set failure")
        self.data[key] = value

    def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


class _DepthMutex:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.depth = 0

    def __enter__(self) -> None:
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


DAY = "2026-11-30"
STAMP = StageEvalStamp(ts_ns=100, boot_ns=777)
LIVE = StageEvalLiveness(stage_eval_last_start_ns=5, stage_eval_last_ok_ns=None)
PHASE = ReconcilePhase(reconcile_start_ns=7, reconcile_ok_ns=9)
LOOK = LookRow(day=DAY, outcome="failed", ts_ns=3)
REPORT = StageReportDoc(ts_ns=4, verdict="pass", reason=None, report_json='{"a":1}')
COUNTS = DayCountsDelta(day=DAY, posted_entries=3, ambiguous=1, fills=2, spend="1.5")
REBUILD = RebuildRow(
    day=DAY,
    ts_ns=8,
    mismatch_kinds="fills,spend",
    posted_entries=3,
    ambiguous=1,
    fills=2,
    spend="1.5",
)

Op = Callable[[SubmitIntentLatch], object]
CASES: list[tuple[str, Op, Op, object, str]] = [
    (
        "stamp",
        lambda latch: latch.write_stage_eval_stamp(STAMP),
        lambda latch: latch.read_stage_eval_stamp(),
        STAMP,
        P + "stage_eval/stamp",
    ),
    (
        "liveness",
        lambda latch: latch.write_stage_eval_liveness(LIVE),
        lambda latch: latch.read_stage_eval_liveness(),
        LIVE,
        P + "stage_eval/liveness",
    ),
    (
        "reconcile_phase",
        lambda latch: latch.write_reconcile_phase(start_ns=7, ok_ns=9),
        lambda latch: latch.read_reconcile_phase(),
        PHASE,
        P + "stage_eval/reconcile_phase",
    ),
    (
        "report",
        lambda latch: latch.write_stage_report(REPORT),
        lambda latch: latch.read_stage_report(),
        REPORT,
        P + "stage_eval/report",
    ),
    (
        "counts_delta",
        lambda latch: latch.write_counts_delta(COUNTS),
        lambda latch: latch.read_counts_delta(DAY),
        COUNTS,
        P + f"counts_delta/{DAY}",
    ),
    (
        "rebuild",
        lambda latch: latch.write_rebuild_row(REBUILD),
        lambda latch: latch.read_rebuild_row(DAY),
        REBUILD,
        P + f"rebuild/{DAY}",
    ),
]
IDS = [c[0] for c in CASES]
ARGS = "name,write,read,expected,key"


@pytest.mark.parametrize(ARGS, CASES, ids=IDS)
def test_round_trip_and_absent_reads_none(
    tmp_path: Path, name: str, write: Op, read: Op, expected: object, key: str
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert read(latch) is None
        write(latch)
        assert read(latch) == expected
    assert key in store.data


@pytest.mark.parametrize(ARGS, CASES, ids=IDS)
def test_garbled_stored_bytes_raise_corrupt_never_a_default(
    tmp_path: Path, name: str, write: Op, read: Op, expected: object, key: str
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
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


@pytest.mark.parametrize(ARGS, CASES, ids=IDS)
def test_no_mutex_nesting_and_store_errors_propagate(
    tmp_path: Path, name: str, write: Op, read: Op, expected: object, key: str
) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        setattr(latch, "_mutex", _DepthMutex())  # noqa: B010 - swap in the depth probe
        write(latch)
        assert read(latch) == expected
        store.fail_set = True
        with pytest.raises(OSError):
            write(latch)


def test_look_rows_are_exclusive_per_day_and_read_back_in_day_order(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert latch.read_looks() == ()
        assert latch.write_look(LOOK) is True
        assert latch.write_look(LOOK) is False  # identical replay: no-op
        with pytest.raises(ValueError):
            latch.write_look(LookRow(day=DAY, outcome="passed", ts_ns=3))
        earlier = LookRow(day="2026-11-29", outcome="not_taken", ts_ns=2)
        latch.write_look(earlier)
        assert latch.read_looks() == (earlier, LOOK)
    assert P + f"look/{DAY}" in store.data


def test_look_scan_fails_closed_on_a_stray_or_mis_keyed_row(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        store.data[P + "look/not-a-day"] = encode_record(LOOK)
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_looks()
    store2 = _Store()
    with _open(store2, tmp_path) as latch2:
        store2.data[P + "look/2026-11-01"] = encode_record(LOOK)  # row says 2026-11-30
        with pytest.raises(SubmitIntentCorrupt):
            latch2.read_looks()


def test_look_outcome_must_be_a_known_value(tmp_path: Path) -> None:
    with _open(_Store(), tmp_path) as latch, pytest.raises(ValueError):
        latch.write_look(LookRow(day=DAY, outcome="maybe", ts_ns=1))


def test_read_epoch_rows_is_ascending_and_garbage_raises(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        assert latch.read_epoch_rows() == ()
        late = EpochRow(commit_sha="b", effective_k=2, force_reason=None, boot_ts=20)
        early = EpochRow(commit_sha="a", effective_k=1, force_reason=None, boot_ts=10)
        latch.write_epoch_row(late)
        latch.write_epoch_row(early)
        assert latch.read_epoch_rows() == (early, late)
        store.data[P + "epoch/zzz"] = b"x"
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_epoch_rows()


def test_delete_gappy_mark_deletes_the_row_and_a_later_mark_recreates_it(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        mark = GappyMark(day=DAY, cause="first", ts_ns=1, cleared_ts=None)
        assert latch.write_gappy_mark(mark) is True
        assert latch.delete_gappy_mark(DAY) is True
        assert P + f"gappy/{DAY}" not in store.data  # deleted, not tombstoned
        assert latch.delete_gappy_mark(DAY) is False  # already absent
        again = GappyMark(day=DAY, cause="second", ts_ns=2, cleared_ts=None)
        assert latch.write_gappy_mark(again) is True  # first-write-wins applies afresh
        assert latch.read_gappy_marks() == (again,)


def test_delete_gappy_mark_without_a_store_delete_fails_closed(tmp_path: Path) -> None:
    store = _Store(with_delete=False)
    with _open(store, tmp_path) as latch:
        latch.write_gappy_mark(GappyMark(day=DAY, cause="c", ts_ns=1, cleared_ts=None))
        with pytest.raises(RuntimeError):
            latch.delete_gappy_mark(DAY)
        assert P + f"gappy/{DAY}" in store.data


def test_retire_rebuild_audits_first_then_deletes_and_is_idempotent(tmp_path: Path) -> None:
    store = _Store()
    with _open(store, tmp_path) as latch:
        latch.write_rebuild_row(REBUILD)
        assert latch.retire_rebuild_row(DAY) is True
        assert latch.read_rebuild_row(DAY) is None
        assert P + f"rebuild_log/{DAY}/{REBUILD.ts_ns}" in store.data
        assert latch.retire_rebuild_row(DAY) is False  # nothing pending: no-op
        latch.write_rebuild_row(REBUILD)  # crash-replay of the same note
        assert latch.retire_rebuild_row(DAY) is True  # identical audit row: no conflict


@pytest.mark.parametrize(
    "record",
    [STAMP, LIVE, PHASE, LOOK, REPORT, COUNTS, REBUILD],
    ids=lambda r: type(r).__name__,
)
def test_codec_round_trips_and_is_strict(record: object) -> None:
    raw = encode_record(record)
    assert decode_record(type(record), raw) == record
    with pytest.raises(ExecParRecordError):
        decode_record(type(record), raw.replace(b'"v": 1', b'"v": 2'))


def test_codec_rejects_bad_types() -> None:
    with pytest.raises(ExecParRecordError):
        encode_record(StageEvalStamp(ts_ns=True, boot_ns=1))
    with pytest.raises(ExecParRecordError):
        encode_record(LookRow(day="2026-1-1", outcome="failed", ts_ns=1))
    with pytest.raises(ExecParRecordError):
        encode_record(DayCountsDelta(day=DAY, posted_entries=True, ambiguous=0, fills=0, spend="0"))
    with pytest.raises(ExecParRecordError):
        encode_record(DayCountsDelta(day=DAY, posted_entries=1, ambiguous=0, fills=0, spend="1.50"))
