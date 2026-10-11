"""Single-writer EXEC-PAR rows for the in-node stage evaluator (BG-5b) on ``SubmitIntentLatch``.

The same discipline as :mod:`breezy.runtime.exec_par_latch_records`: ``_require_held()`` first,
``_mutex`` taken once per public method (never nested), a garbled or mis-keyed row raises the
latch's ``CorruptError`` (never a default), store errors propagate.

Rows (key layout in :mod:`breezy.runtime.exec_par_records`):

* ``stage_eval/stamp``, ``stage_eval/liveness``, ``stage_eval/reconcile_phase``,
  ``stage_eval/report``: single overwritten rows (the stamp and the phases are monotone
  by construction: one loop-thread writer).
* ``look/<day>``: EXCLUSIVE per day; the evaluator never writes it (it never promotes, r4.5
  O5): the BG-4 / BG-10(f) side does. The evaluator only reads it.
* ``counts_delta/<day>``, ``rebuild/<day>``, ``rebuild_log/<day>/<ts_ns>``: the BG-1d rebuild
  overlay, the pending note and its audit trail.
* ``delete_gappy_mark``: integration note 1: a cleared gappy mark is DELETED, not tombstoned,
  so a later fault on the same day re-creates it (``write_gappy_mark`` is first-write-wins).
"""

from __future__ import annotations

from typing import Final

from breezy.runtime.exec_par_latch_counters import ExecParCounterRowsMixin, _part
from breezy.runtime.exec_par_records import (
    DAY_CONVENTION_KEY,
    EPOCH_KEY_PREFIX,
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
    decode_day_convention,
    encode_day_convention,
)

LOOK_OUTCOMES: Final[frozenset[str]] = frozenset({"passed", "failed", "not_taken"})

_STAMP = EXEC_PAR_PREFIX + "stage_eval/stamp"
_LIVENESS = EXEC_PAR_PREFIX + "stage_eval/liveness"
_RECONCILE_PHASE = EXEC_PAR_PREFIX + "stage_eval/reconcile_phase"
_REPORT = EXEC_PAR_PREFIX + "stage_eval/report"
_LOOK = EXEC_PAR_PREFIX + "look/"
_COUNTS = EXEC_PAR_PREFIX + "counts_delta/"
_REBUILD = EXEC_PAR_PREFIX + "rebuild/"
_REBUILD_LOG = EXEC_PAR_PREFIX + "rebuild_log/"
_GAPPY = EXEC_PAR_PREFIX + "gappy/"
_GAPPY_LOG = EXEC_PAR_PREFIX + "gappy_log/"


class ExecParStageRowsMixin(ExecParCounterRowsMixin):
    """Stage-evaluator row writers and readers; the host supplies the mixin attributes."""

    def _es_delete(self, key: str) -> bool:
        """Delete ``key`` (caller holds ``_mutex``); the store must offer ``delete``."""
        deleter = getattr(self._store, "delete", None)
        if deleter is None:
            raise RuntimeError("store has no delete; cannot remove an EXEC-PAR row")
        return bool(deleter(key))

    def _es_require_delete(self) -> None:
        if getattr(self._store, "delete", None) is None:
            raise RuntimeError("store has no delete; cannot remove an EXEC-PAR row")

    # -- the climate-day convention (BG-5c R1) ----------------------------

    def read_day_convention(self) -> int | None:
        """The stored ``exec_par/day_convention`` version, or ``None`` when never written."""
        self._require_held()
        with self._mutex:
            raw = self._store.get(DAY_CONVENTION_KEY)
            if raw is None:
                return None
            try:
                return decode_day_convention(raw)
            except ExecParRecordError:
                raise self.CorruptError() from None

    def write_day_convention(self) -> bool:
        """Write ``{"v": 2}`` once: ``True`` if newly written, ``False`` for the identical row;
        any other stored row raises (the boot check refuses K>1 on it before this is reached)."""
        self._require_held()
        raw = encode_day_convention()
        with self._mutex:
            existing = self._store.get(DAY_CONVENTION_KEY)
            if existing is not None:
                if existing == raw:
                    return False
                raise ValueError("conflicting EXEC-PAR day_convention row already stored")
            self._store.set(DAY_CONVENTION_KEY, raw)
            return True

    # -- stamp, liveness, reconcile phase, report -------------------------

    def write_stage_eval_stamp(self, record: StageEvalStamp) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_STAMP, record)

    def read_stage_eval_stamp(self) -> StageEvalStamp | None:
        self._require_held()
        with self._mutex:
            return self._er_get(_STAMP, StageEvalStamp)

    def write_stage_eval_liveness(self, record: StageEvalLiveness) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_LIVENESS, record)

    def read_stage_eval_liveness(self) -> StageEvalLiveness | None:
        self._require_held()
        with self._mutex:
            return self._er_get(_LIVENESS, StageEvalLiveness)

    def write_reconcile_phase(self, *, start_ns: int, ok_ns: int | None) -> None:
        """BG-1d ``CounterStorePort.write_reconcile_phase`` (N3 reconcile timestamps)."""
        self._require_held()
        with self._mutex:
            self._er_put(_RECONCILE_PHASE, ReconcilePhase(start_ns, ok_ns))

    def read_reconcile_phase(self) -> ReconcilePhase | None:
        self._require_held()
        with self._mutex:
            return self._er_get(_RECONCILE_PHASE, ReconcilePhase)

    def write_stage_report(self, record: StageReportDoc) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_REPORT, record)

    def read_stage_report(self) -> StageReportDoc | None:
        self._require_held()
        with self._mutex:
            return self._er_get(_REPORT, StageReportDoc)

    # -- promotion looks (exclusive per day) ------------------------------

    def write_look(self, record: LookRow) -> bool:
        """``True`` if newly written; an identical replay is ``False``; a different row raises."""
        self._require_held()
        if record.outcome not in LOOK_OUTCOMES:
            raise ValueError("unknown look outcome")
        with self._mutex:
            return self._er_put_exclusive(f"{_LOOK}{_part(record.day)}", record)

    def read_looks(self) -> tuple[LookRow, ...]:
        """Every look ascending by day; a mis-keyed row or an unknown outcome is corrupt."""
        self._require_held()
        with self._mutex:
            rows = self._ec_scan(_LOOK, LookRow, lambda r: r.day, None)
        if any(row.outcome not in LOOK_OUTCOMES for row in rows):
            raise self.CorruptError()
        return rows

    # -- every epoch row ----------------------------------------------------

    def read_epoch_rows(self) -> tuple[EpochRow, ...]:
        """Every epoch row ascending by ``boot_ts``; any stray or garbled row is corrupt."""
        self._require_held()
        with self._mutex:
            return tuple(self._er_scan(EPOCH_KEY_PREFIX, EpochRow, lambda r: r.boot_ts))

    # -- BG-1d store halves ---------------------------------------------------

    def delete_gappy_mark(self, day: str) -> bool:
        """Delete the day's mark (note 1); ``False`` if there was none.

        The mark is audited to ``gappy_log/<day>/<mark.ts_ns>`` BEFORE the delete (the same
        order as :meth:`retire_rebuild_row`), so a crash between the two replays cleanly."""
        self._require_held()
        key = f"{_GAPPY}{_part(day)}"
        self._es_require_delete()
        with self._mutex:
            mark = self._er_get(key, GappyMark)
            if mark is None:
                return False
            if mark.day != day:
                raise self.CorruptError()
            self._er_put_exclusive(f"{_GAPPY_LOG}{_part(day)}/{mark.ts_ns}", mark)
            return self._es_delete(key)

    def write_counts_delta(self, record: DayCountsDelta) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(f"{_COUNTS}{_part(record.day)}", record)

    def read_counts_delta(self, day: str) -> DayCountsDelta | None:
        self._require_held()
        key = f"{_COUNTS}{_part(day)}"
        with self._mutex:
            row = self._er_get(key, DayCountsDelta)
        if row is not None and row.day != day:
            raise self.CorruptError()
        return row

    def write_rebuild_row(self, record: RebuildRow) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(f"{_REBUILD}{_part(record.day)}", record)

    def read_rebuild_row(self, day: str) -> RebuildRow | None:
        self._require_held()
        key = f"{_REBUILD}{_part(day)}"
        with self._mutex:
            row = self._er_get(key, RebuildRow)
        if row is not None and row.day != day:
            raise self.CorruptError()
        return row

    def retire_rebuild_row(self, day: str) -> bool:
        """Audit the pending note, then delete it. ``False`` (nothing written) if none is pending.

        The audit row is written first and is exclusive per ``<day>/<ts_ns>``, so a crash
        between the two steps replays to the same result.
        """
        self._require_held()
        key = f"{_REBUILD}{_part(day)}"
        self._es_require_delete()
        with self._mutex:
            row = self._er_get(key, RebuildRow)
            if row is None:
                return False
            if row.day != day:
                raise self.CorruptError()
            self._er_put_exclusive(f"{_REBUILD_LOG}{_part(day)}/{row.ts_ns}", row)
            return self._es_delete(key)
