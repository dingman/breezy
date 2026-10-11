"""Single-writer EXEC-PAR D-PREREG record methods for ``SubmitIntentLatch`` (BG-1a).

A mixin so ``submit_intent.py`` stays small. Every public method:

* runs ``self._require_held()`` first (a not-held latch raises
  ``SubmitIntentLockNotHeld`` before touching the store);
* takes ``self._mutex`` exactly once and never calls another method that takes
  it (the mutex is a non-reentrant ``threading.Lock``);
* raises the latch's own ``CorruptError`` for any unreadable stored record,
  never a default. An absent record reads as ``None``; store errors propagate.

Nothing in the node calls these yet (BG-1a is inert); the key layout and the
record shapes are documented in :mod:`breezy.runtime.exec_par_records`.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from typing import Protocol, TypeVar

from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    Amendment,
    CleanupDemotion,
    EpochRow,
    ExcludedDay,
    ExecParRecordError,
    ForceK1Cleared,
    ForceK1Flag,
    StageEvalDry,
    StageReset,
    StopVerdict,
    decode_excluded_days,
    decode_force_k1_flag,
    decode_pointer,
    decode_record,
    encode_excluded_days,
    encode_force_k1_tombstone,
    encode_pointer,
    encode_record,
)

T = TypeVar("T")

_STAGE_RESET = EXEC_PAR_PREFIX + "stage_reset"
_EXCLUDED_DAYS = EXEC_PAR_PREFIX + "excluded_days"
_STAGE_EVAL_DRY = EXEC_PAR_PREFIX + "stage_eval_dry"
_FORCE_K1_CLEARED = EXEC_PAR_PREFIX + "force_k1_cleared"
_FORCE_K1_FLAG = EXEC_PAR_PREFIX + "force_k1"
_EPOCH = EXEC_PAR_PREFIX + "epoch/"
_AMENDMENT = EXEC_PAR_PREFIX + "amendment/"
_STOP_VERDICT = EXEC_PAR_PREFIX + "stop_verdict/"
_CLEANUP_DEMOTION = EXEC_PAR_PREFIX + "cleanup_demotion/"
_LATEST = "latest"


class _Store(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes) -> None: ...


class ExecParRecordsMixin:
    """The durable-record writers/readers; the host supplies the four attributes."""

    _store: _Store
    _mutex: AbstractContextManager[object]
    CorruptError: type[Exception]

    def _require_held(self) -> None:
        raise NotImplementedError

    # -- private helpers (callers hold ``_mutex``) -----------------------

    def _er_get(self, key: str, cls: type[T]) -> T | None:
        raw = self._store.get(key)
        if raw is None:
            return None
        try:
            return decode_record(cls, raw)
        except ExecParRecordError:
            raise self.CorruptError() from None

    def _er_put(self, key: str, record: object) -> None:
        try:
            raw = encode_record(record)
        except ExecParRecordError:
            raise ValueError("invalid EXEC-PAR record") from None
        self._store.set(key, raw)

    def _er_put_family(self, prefix: str, ts_ns: int, record: object) -> None:
        """Row first, then the ``latest`` pointer, so a crash never points at nothing."""
        self._er_put(f"{prefix}{ts_ns}", record)
        self._store.set(prefix + _LATEST, encode_pointer(ts_ns))

    def _er_get_by_ts(self, prefix: str, ts_ns: int, cls: type[T]) -> T | None:
        return self._er_get(f"{prefix}{ts_ns}", cls)

    def _er_get_latest(self, prefix: str, cls: type[T]) -> T | None:
        raw = self._store.get(prefix + _LATEST)
        if raw is None:
            return None
        try:
            ts_ns = decode_pointer(raw)
        except ExecParRecordError:
            raise self.CorruptError() from None
        row = self._er_get_by_ts(prefix, ts_ns, cls)
        if row is None:
            raise self.CorruptError()
        return row

    # -- stage_reset (the floor) -----------------------------------------

    def write_stage_reset(self, record: StageReset) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_STAGE_RESET, record)

    def read_stage_reset(self) -> StageReset | None:
        self._require_held()
        with self._mutex:
            return self._er_get(_STAGE_RESET, StageReset)

    # -- excluded days ---------------------------------------------------

    def add_excluded_day(self, record: ExcludedDay) -> bool:
        """Append; ``False`` (nothing written) if the day is already excluded."""
        self._require_held()
        with self._mutex:
            existing = self._read_excluded_days_locked()
            if any(d.day == record.day for d in existing):
                return False
            self._store.set(_EXCLUDED_DAYS, encode_excluded_days((*existing, record)))
            return True

    def read_excluded_days(self) -> tuple[ExcludedDay, ...]:
        self._require_held()
        with self._mutex:
            return self._read_excluded_days_locked()

    def _read_excluded_days_locked(self) -> tuple[ExcludedDay, ...]:
        raw = self._store.get(_EXCLUDED_DAYS)
        if raw is None:
            return ()
        try:
            return decode_excluded_days(raw)
        except ExecParRecordError:
            raise self.CorruptError() from None

    # -- epoch rows ------------------------------------------------------

    def write_epoch_row(self, record: EpochRow) -> None:
        self._require_held()
        with self._mutex:
            self._er_put_family(_EPOCH, record.boot_ts, record)

    def read_epoch_row(self, boot_ts: int) -> EpochRow | None:
        self._require_held()
        with self._mutex:
            return self._er_get_by_ts(_EPOCH, boot_ts, EpochRow)

    def read_latest_epoch_row(self) -> EpochRow | None:
        self._require_held()
        with self._mutex:
            return self._er_get_latest(_EPOCH, EpochRow)

    def write_epoch_stop_ts(self, boot_ts: int, stop_ts: int) -> bool:
        """Set ``stop_ts`` once; ``False`` if the row is absent or already stopped."""
        self._require_held()
        with self._mutex:
            row = self._er_get_by_ts(_EPOCH, boot_ts, EpochRow)
            if row is None or row.stop_ts is not None:
                return False
            self._er_put(f"{_EPOCH}{boot_ts}", replace(row, stop_ts=stop_ts))
            return True

    # -- amendments ------------------------------------------------------

    def write_amendment(self, record: Amendment) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(f"{_AMENDMENT}{record.ts_ns}", record)

    def read_amendment(self, ts_ns: int) -> Amendment | None:
        self._require_held()
        with self._mutex:
            return self._er_get_by_ts(_AMENDMENT, ts_ns, Amendment)

    # -- dry evaluation and force-K1 clearance ---------------------------

    def write_stage_eval_dry(self, record: StageEvalDry) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_STAGE_EVAL_DRY, record)

    def read_stage_eval_dry(self) -> StageEvalDry | None:
        self._require_held()
        with self._mutex:
            return self._er_get(_STAGE_EVAL_DRY, StageEvalDry)

    def write_force_k1_cleared(self, record: ForceK1Cleared) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_FORCE_K1_CLEARED, record)

    def read_force_k1_cleared(self) -> ForceK1Cleared | None:
        self._require_held()
        with self._mutex:
            return self._er_get(_FORCE_K1_CLEARED, ForceK1Cleared)

    # -- stop-verdict markers (M3) and cleanup demotions (N4) ------------

    def write_stop_verdict(self, record: StopVerdict) -> None:
        self._require_held()
        with self._mutex:
            self._er_put_family(_STOP_VERDICT, record.ts_ns, record)

    def read_stop_verdict(self, ts_ns: int) -> StopVerdict | None:
        self._require_held()
        with self._mutex:
            return self._er_get_by_ts(_STOP_VERDICT, ts_ns, StopVerdict)

    def read_latest_stop_verdict(self) -> StopVerdict | None:
        self._require_held()
        with self._mutex:
            return self._er_get_latest(_STOP_VERDICT, StopVerdict)

    def write_cleanup_demotion(self, record: CleanupDemotion) -> None:
        self._require_held()
        with self._mutex:
            self._er_put_family(_CLEANUP_DEMOTION, record.ts_ns, record)

    def read_cleanup_demotion(self, ts_ns: int) -> CleanupDemotion | None:
        self._require_held()
        with self._mutex:
            return self._er_get_by_ts(_CLEANUP_DEMOTION, ts_ns, CleanupDemotion)

    def read_latest_cleanup_demotion(self) -> CleanupDemotion | None:
        self._require_held()
        with self._mutex:
            return self._er_get_latest(_CLEANUP_DEMOTION, CleanupDemotion)

    # -- durable force-K1 flag (1b) --------------------------------------

    def write_force_k1_flag(self, record: ForceK1Flag) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_FORCE_K1_FLAG, record)

    def clear_force_k1_flag(self, cleared_ts_ns: int) -> None:
        """Overwrite the flag with a tombstone (the store has no delete)."""
        self._require_held()
        with self._mutex:
            self._store.set(_FORCE_K1_FLAG, encode_force_k1_tombstone(cleared_ts_ns))

    def read_force_k1_flag(self) -> ForceK1Flag | None:
        """The flag, ``None`` if never set or cleared; unreadable raises (caller: set)."""
        self._require_held()
        with self._mutex:
            raw = self._store.get(_FORCE_K1_FLAG)
            if raw is None:
                return None
            try:
                return decode_force_k1_flag(raw)
            except ExecParRecordError:
                raise self.CorruptError() from None
