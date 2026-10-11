"""EXEC-PAR BG-2: the K-epoch ledger (boot row, k_change floor, stop_ts, classification)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from breezy.runtime.exec_par_epochs import (
    K_CHANGE_CAUSE,
    K_FORCED_NOTE_PREFIX,
    STRATUM_PARALLEL,
    STRATUM_SINGLE,
    EpochLedger,
    k_forced_amendment,
    read_epoch_ledger,
    record_boot_epoch,
    record_clean_stop,
)
from breezy.runtime.exec_par_records import Amendment, EpochRow, StageReset
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import SubmitIntentLatch, open_submit_intent_latch

SEC = 1_000_000_000


@contextmanager
def _latch(
    db: Path, *, k: int, boot_ns: int, force: str | None = None
) -> Iterator[SubmitIntentLatch]:
    with (
        SqliteStateStore(db) as store,
        open_submit_intent_latch(
            store,
            db,
            max_slots=k,
            v2_predicate=lambda: True,
            clock_ns=lambda: boot_ns,
        ) as latch,
    ):
        if force is not None:
            latch.force_k1(force)
        yield latch


def test_first_boot_writes_the_row_and_no_stage_reset(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    with _latch(db, k=2, boot_ns=100 * SEC) as latch:
        row = record_boot_epoch(latch, commit_sha="abc123", boot_ts=latch.boot_ns)

        assert row == EpochRow("abc123", 2, None, 100 * SEC)
        assert latch.read_latest_epoch_row() == row
        assert latch.read_stage_reset() is None


def test_boot_row_records_effective_k_after_a_forced_to_1(tmp_path: Path) -> None:
    with _latch(tmp_path / "s.db", k=2, boot_ns=5, force="marker_absent") as latch:
        row = record_boot_epoch(latch, commit_sha="abc", boot_ts=latch.boot_ns)

        assert (row.effective_k, row.force_reason) == (1, "marker_absent")


def test_same_k_reboot_writes_no_stage_reset(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    with _latch(db, k=2, boot_ns=100) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)
    with _latch(db, k=2, boot_ns=200) as latch:
        record_boot_epoch(latch, commit_sha="b", boot_ts=latch.boot_ns)

        assert latch.read_stage_reset() is None
        assert latch.read_epoch_row(100) is not None
        assert latch.read_latest_epoch_row() == EpochRow("b", 2, None, 200)


def test_k_change_writes_the_k_change_stage_reset(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    with _latch(db, k=1, boot_ns=100) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)
    with _latch(db, k=2, boot_ns=200) as latch:
        record_boot_epoch(latch, commit_sha="b", boot_ts=latch.boot_ns)

        reset = latch.read_stage_reset()
        assert reset is not None
        assert (reset.ts, reset.cause, reset.halt_ts) == (200, K_CHANGE_CAUSE, None)
        assert K_CHANGE_CAUSE == "k_change"


def test_forced_down_to_1_is_a_k_change(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    with _latch(db, k=2, boot_ns=100) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)
    with _latch(db, k=2, boot_ns=200, force="marker_absent") as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)

        assert latch.read_stage_reset() is not None


def test_unclean_prior_without_stop_ts_is_closed_by_the_next_boot(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    with _latch(db, k=2, boot_ns=100) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)  # crash: no stop_ts
    with _latch(db, k=2, boot_ns=200) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)

        prior = latch.read_epoch_row(100)
        assert prior is not None and prior.stop_ts is None
        assert latch.read_stage_reset() is None


class _EpochWriteFails:
    """Delegates to a real latch but fails the epoch-row write."""

    def __init__(self, latch: SubmitIntentLatch) -> None:
        self._latch = latch

    def max_slots(self) -> int:
        return self._latch.max_slots()

    @property
    def k_forced_reason(self) -> str | None:
        return self._latch.k_forced_reason

    def read_latest_epoch_row(self) -> EpochRow | None:
        return self._latch.read_latest_epoch_row()

    def write_stage_reset(self, record: StageReset) -> None:
        self._latch.write_stage_reset(record)

    def write_epoch_row(self, record: EpochRow) -> None:
        raise OSError("store down")

    def write_epoch_stop_ts(self, boot_ts: int, stop_ts: int) -> bool:
        return self._latch.write_epoch_stop_ts(boot_ts, stop_ts)


def test_the_floor_is_written_before_the_epoch_row(tmp_path: Path) -> None:
    """A crash between the two writes must not lose the k_change reset."""
    db = tmp_path / "s.db"
    with _latch(db, k=1, boot_ns=100) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)
    with _latch(db, k=2, boot_ns=200) as latch:
        with pytest.raises(OSError):
            record_boot_epoch(_EpochWriteFails(latch), commit_sha="b", boot_ts=latch.boot_ns)

        assert latch.read_stage_reset() is not None
        assert latch.read_latest_epoch_row() == EpochRow("a", 1, None, 100)


def test_clean_stop_sets_stop_ts_once(tmp_path: Path) -> None:
    with _latch(tmp_path / "s.db", k=1, boot_ns=100) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)

        assert record_clean_stop(latch, boot_ts=100, stop_ts=150) is True
        assert record_clean_stop(latch, boot_ts=100, stop_ts=160) is False
        row = latch.read_epoch_row(100)
        assert row is not None and row.stop_ts == 150


def test_k_forced_amendment_names_the_reason_only() -> None:
    amendment = k_forced_amendment(ts_ns=9, commit_sha="abc", reason="bucket_label_above_frozen")

    assert amendment == Amendment(9, "abc", K_FORCED_NOTE_PREFIX + "bucket_label_above_frozen")


# -- classification -------------------------------------------------------------


def _ledger(*epochs: EpochRow, forced: tuple[int, ...] = ()) -> EpochLedger:
    return EpochLedger(epochs=tuple(epochs), forced_amendment_ts=forced)


def test_fill_before_any_epoch_is_single() -> None:
    assert _ledger(EpochRow("a", 2, None, 100)).stratum_of(50) == STRATUM_SINGLE


def test_empty_ledger_is_single() -> None:
    assert _ledger().stratum_of(50) == STRATUM_SINGLE


def test_configured_k_gt_1_without_a_forced_row_is_parallel() -> None:
    ledger = _ledger(EpochRow("a", 2, None, 100), EpochRow("a", 1, None, 300))

    assert ledger.stratum_of(100) == STRATUM_PARALLEL
    assert ledger.stratum_of(299) == STRATUM_PARALLEL
    assert ledger.stratum_of(300) == STRATUM_SINGLE


def test_forced_reason_row_is_single() -> None:
    assert _ledger(EpochRow("a", 1, "marker_absent", 100)).stratum_of(150) == STRATUM_SINGLE


def test_amendment_inside_the_epoch_makes_it_single() -> None:
    ledger = _ledger(EpochRow("a", 2, None, 100), EpochRow("a", 2, None, 300), forced=(120,))

    assert ledger.stratum_of(150) == STRATUM_SINGLE
    assert ledger.stratum_of(350) == STRATUM_PARALLEL


def test_read_epoch_ledger_round_trips_from_a_read_only_open(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    with _latch(db, k=2, boot_ns=100) as latch:
        record_boot_epoch(latch, commit_sha="a", boot_ts=latch.boot_ns)
        latch.write_amendment(k_forced_amendment(ts_ns=120, commit_sha="a", reason="r"))
        latch.write_amendment(Amendment(ts_ns=130, commit_sha="a", note="A1 unrelated"))

        ledger = read_epoch_ledger(db)

    assert ledger.epochs == (EpochRow("a", 2, None, 100),)
    assert ledger.forced_amendment_ts == (120,)


def test_read_epoch_ledger_of_a_store_without_rows_is_empty(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    with SqliteStateStore(db) as store:
        store.set("other", b"x")

    assert read_epoch_ledger(db) == EpochLedger(epochs=(), forced_amendment_ts=())
