"""Single-writer EXEC-PAR D-PREREG record methods for ``SubmitIntentLatch`` (BG-1a).

A mixin so ``submit_intent.py`` stays small. Every public method:

* runs ``self._require_held()`` first (a not-held latch raises
  ``SubmitIntentLockNotHeld`` before touching the store);
* takes ``self._mutex`` exactly once and never calls another method that takes
  it (the mutex is a non-reentrant ``threading.Lock``);
* raises the latch's own ``CorruptError`` for any unreadable stored record,
  never a default (the one exception is :meth:`read_force_k1_flag`, which
  returns the fail-closed ``UNREADABLE`` state). An absent record reads as
  ``None``; store errors propagate.

Keyed families (``epoch``, ``stop_verdict``, ``amendment``, ``cleanup_demotion``)
have NO ``latest`` pointer: readers scan the ``<prefix>`` rows through the
store's ``keys_with_prefix`` and take the max ``ts``, so a crash after a row
write can never leave a reader looking at a stale or missing pointer. Rows are
exclusive per key: an identical rewrite is a no-op, a different row raises.

Nothing in the node calls these yet (BG-1a is inert); the key layout and the
record shapes are documented in :mod:`breezy.runtime.exec_par_records`.
"""

from __future__ import annotations

from collections.abc import Callable
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
    ForceK1Kind,
    ForceK1State,
    SettledPnlDay,
    StageEvalDry,
    StageReset,
    StopVerdict,
    decode_excluded_days,
    decode_force_k1_flag,
    decode_record,
    encode_excluded_days,
    encode_force_k1_tombstone,
    encode_record,
)
from breezy.runtime.exec_par_settled_pnl import (
    PreBootLedger,
    Timed,
    check_monotonic,
    pre_boot_fill_ledger,
)

T = TypeVar("T")
F = TypeVar("F", bound=Timed)

_STAGE_RESET = EXEC_PAR_PREFIX + "stage_reset"
_EXCLUDED_DAYS = EXEC_PAR_PREFIX + "excluded_days"
_STAGE_EVAL_DRY = EXEC_PAR_PREFIX + "stage_eval_dry"
_FORCE_K1_CLEARED = EXEC_PAR_PREFIX + "force_k1_cleared"
_FORCE_K1_FLAG = EXEC_PAR_PREFIX + "force_k1"
_EPOCH = EXEC_PAR_PREFIX + "epoch/"
_AMENDMENT = EXEC_PAR_PREFIX + "amendment/"
_STOP_VERDICT = EXEC_PAR_PREFIX + "stop_verdict/"
_CLEANUP_DEMOTION = EXEC_PAR_PREFIX + "cleanup_demotion/"
_SETTLED_PNL = EXEC_PAR_PREFIX + "settled_pnl/"


class _Store(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes) -> None: ...


class _ScanView:
    """Read-only get + prefix listing over the host store (no ``set`` is reachable)."""

    def __init__(self, store: _Store) -> None:
        lister = getattr(store, "keys_with_prefix", None)
        if lister is None:
            raise RuntimeError("store has no keys_with_prefix; cannot scan EXEC-PAR rows")
        self._store = store
        self._lister: Callable[[str], list[str]] = lister

    def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return self._lister(prefix)


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

    @staticmethod
    def _er_encode(record: object) -> bytes:
        try:
            return encode_record(record)
        except ExecParRecordError:
            raise ValueError("invalid EXEC-PAR record") from None

    def _er_put(self, key: str, record: object) -> None:
        self._store.set(key, self._er_encode(record))

    def _er_put_exclusive(self, key: str, record: object) -> bool:
        """Write once. ``True`` if written; identical rewrite is a ``False`` no-op; else raises."""
        raw = self._er_encode(record)
        existing = self._store.get(key)
        if existing is not None:
            if existing == raw:
                return False
            raise ValueError(f"conflicting EXEC-PAR row already stored at {key}")
        self._store.set(key, raw)
        return True

    def _er_scan(self, prefix: str, cls: type[T], ts_of: Callable[[T], int]) -> list[T]:
        """All rows under ``prefix``, ascending by ts; any stray/garbled row is corrupt."""
        lister = getattr(self._store, "keys_with_prefix", None)
        if lister is None:
            raise RuntimeError("store has no keys_with_prefix; cannot scan EXEC-PAR rows")
        rows: list[T] = []
        for key in lister(prefix):
            suffix = key[len(prefix) :]
            if not suffix.isascii() or not suffix.isdigit() or suffix != str(int(suffix)):
                raise self.CorruptError()
            row = self._er_get(key, cls)
            if row is None or ts_of(row) != int(suffix):
                raise self.CorruptError()
            rows.append(row)
        return sorted(rows, key=ts_of)

    def _er_latest(self, prefix: str, cls: type[T], ts_of: Callable[[T], int]) -> T | None:
        rows = self._er_scan(prefix, cls, ts_of)
        return rows[-1] if rows else None

    # -- stage_reset (the floor) -----------------------------------------

    def write_stage_reset(self, record: StageReset) -> None:
        """Write the floor; a ``ts`` lower than the stored one raises (monotonic)."""
        self._require_held()
        with self._mutex:
            existing = self._er_get(_STAGE_RESET, StageReset)
            if existing is not None:
                if record.ts < existing.ts:
                    raise ValueError("stage_reset ts must be monotonic non-decreasing")
                if record.ts == existing.ts and record != existing:
                    raise ValueError("conflicting stage_reset already stored at this ts")
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
            self._er_encode(record)  # validate first: ValueError, consistent with _er_put
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
            self._er_put_exclusive(f"{_EPOCH}{record.boot_ts}", record)

    def read_epoch_row(self, boot_ts: int) -> EpochRow | None:
        self._require_held()
        with self._mutex:
            return self._er_get(f"{_EPOCH}{boot_ts}", EpochRow)

    def read_latest_epoch_row(self) -> EpochRow | None:
        self._require_held()
        with self._mutex:
            return self._er_latest(_EPOCH, EpochRow, lambda r: r.boot_ts)

    def write_epoch_stop_ts(self, boot_ts: int, stop_ts: int) -> bool:
        """Set ``stop_ts`` once. Absent row raises; already stopped is a no-op ``False``."""
        self._require_held()
        with self._mutex:
            row = self._er_get(f"{_EPOCH}{boot_ts}", EpochRow)
            if row is None:
                raise ValueError("epoch row absent; cannot set stop_ts")
            if row.stop_ts is not None:
                return False
            self._er_put(f"{_EPOCH}{boot_ts}", replace(row, stop_ts=stop_ts))
            return True

    # -- amendments ------------------------------------------------------

    def write_amendment(self, record: Amendment) -> None:
        self._require_held()
        with self._mutex:
            self._er_put_exclusive(f"{_AMENDMENT}{record.ts_ns}", record)

    def read_amendment(self, ts_ns: int) -> Amendment | None:
        self._require_held()
        with self._mutex:
            return self._er_get(f"{_AMENDMENT}{ts_ns}", Amendment)

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
            self._er_put_exclusive(f"{_STOP_VERDICT}{record.ts_ns}", record)

    def read_stop_verdict(self, ts_ns: int) -> StopVerdict | None:
        self._require_held()
        with self._mutex:
            return self._er_get(f"{_STOP_VERDICT}{ts_ns}", StopVerdict)

    def read_latest_stop_verdict(self) -> StopVerdict | None:
        self._require_held()
        with self._mutex:
            return self._er_latest(_STOP_VERDICT, StopVerdict, lambda r: r.ts_ns)

    def read_stop_verdicts_since(self, ts_ns: int) -> tuple[StopVerdict, ...]:
        """Every marker with ``ts_ns`` >= the argument, ascending (N1)."""
        self._require_held()
        with self._mutex:
            rows = self._er_scan(_STOP_VERDICT, StopVerdict, lambda r: r.ts_ns)
            return tuple(r for r in rows if r.ts_ns >= ts_ns)

    def write_cleanup_demotion(self, record: CleanupDemotion) -> None:
        self._require_held()
        with self._mutex:
            self._er_put_exclusive(f"{_CLEANUP_DEMOTION}{record.ts_ns}", record)

    def read_cleanup_demotion(self, ts_ns: int) -> CleanupDemotion | None:
        self._require_held()
        with self._mutex:
            return self._er_get(f"{_CLEANUP_DEMOTION}{ts_ns}", CleanupDemotion)

    def read_latest_cleanup_demotion(self) -> CleanupDemotion | None:
        self._require_held()
        with self._mutex:
            return self._er_latest(_CLEANUP_DEMOTION, CleanupDemotion, lambda r: r.ts_ns)

    # -- durable force-K1 flag (1b) --------------------------------------

    def write_force_k1_flag(self, record: ForceK1Flag) -> None:
        self._require_held()
        with self._mutex:
            self._er_put(_FORCE_K1_FLAG, record)

    def clear_force_k1_flag(self, cleared_ts_ns: int) -> None:
        """Tombstone the flag (the store has no delete).

        Requires ``cleared_ts_ns > 0`` and a ``force_k1_cleared`` record whose
        ``ts`` equals it and is newer than a currently SET flag's ``ts_ns``. A garbled flag or garbled cleared record raises.
        """
        self._require_held()
        if cleared_ts_ns <= 0:
            raise ValueError("cleared_ts_ns must be positive")
        with self._mutex:
            raw = self._store.get(_FORCE_K1_FLAG)
            current: ForceK1Flag | None = None
            if raw is not None:
                try:
                    current = decode_force_k1_flag(raw)
                except ExecParRecordError:
                    raise self.CorruptError() from None
            cleared = self._er_get(_FORCE_K1_CLEARED, ForceK1Cleared)
            if cleared is None or cleared.ts != cleared_ts_ns:
                raise ValueError("no matching force_k1_cleared record for this clear")
            if current is not None and cleared.ts <= current.ts_ns:
                raise ValueError("force_k1_cleared must be newer than the flag it clears")
            self._store.set(_FORCE_K1_FLAG, encode_force_k1_tombstone(cleared_ts_ns))

    def read_force_k1_flag(self) -> ForceK1State:
        """SET(record), CLEARED (no active flag) or UNREADABLE. Corruption never raises."""
        self._require_held()
        with self._mutex:
            raw = self._store.get(_FORCE_K1_FLAG)
            if raw is None:
                return ForceK1State(ForceK1Kind.CLEARED)
            try:
                flag = decode_force_k1_flag(raw)
            except ExecParRecordError:
                return ForceK1State(ForceK1Kind.UNREADABLE)
            if flag is None:
                return ForceK1State(ForceK1Kind.CLEARED)
            return ForceK1State(ForceK1Kind.SET, flag)

    # -- BG-1c settled P&L per arm-time day (spec 10a, 15) ----------------

    def write_settled_pnl_day(self, record: SettledPnlDay) -> None:
        """Overwrite the day's row (a full recompute) unless it regresses the prior row (F1)."""
        self._require_held()
        with self._mutex:
            key = f"{_SETTLED_PNL}{record.day}"
            self._er_encode(record)  # validate first
            check_monotonic(self._er_get(key, SettledPnlDay), record)
            self._er_put(key, record)

    def read_settled_pnl_day(self, day: str) -> SettledPnlDay | None:
        """The row, or ``None`` when absent (the consumer treats absent as FAIL, never 0)."""
        self._require_held()
        with self._mutex:
            row = self._er_get(f"{_SETTLED_PNL}{day}", SettledPnlDay)
            if row is not None and row.day != day:
                raise self.CorruptError()
            return row

    def read_settled_pnl_days(self) -> tuple[SettledPnlDay, ...]:
        """Every stored day ascending; a row under the wrong key is corrupt."""
        self._require_held()
        with self._mutex:
            lister = getattr(self._store, "keys_with_prefix", None)
            if lister is None:
                raise RuntimeError("store has no keys_with_prefix; cannot scan EXEC-PAR rows")
            rows: list[SettledPnlDay] = []
            for key in lister(_SETTLED_PNL):
                row = self._er_get(key, SettledPnlDay)
                if row is None or key != f"{_SETTLED_PNL}{row.day}":
                    raise self.CorruptError()
                rows.append(row)
            return tuple(sorted(rows, key=lambda r: r.day))

    # -- BG-1c K=1 pre-boot fill ledger (spec 7 parity; read-only) --------

    def read_first_k_gt1_boot_ts(self) -> int | None:
        """``boot_ts`` of the earliest epoch row with ``effective_k`` > 1, else ``None``."""
        self._require_held()
        with self._mutex:
            return self._first_k_gt1_locked()

    def _first_k_gt1_locked(self) -> int | None:
        return self._epoch_summary_locked()[1]

    def _epoch_summary_locked(self) -> tuple[bool, int | None]:
        epochs = self._er_scan(_EPOCH, EpochRow, lambda r: r.boot_ts)
        return bool(epochs), next((e.boot_ts for e in epochs if e.effective_k > 1), None)

    def read_k1_pre_boot_fills(
        self, decode: Callable[[bytes], F], in_family: Callable[[F], bool]
    ) -> PreBootLedger[F]:
        """Same-family durable fills strictly before the first K>1 epoch (no write)."""
        self._require_held()
        with self._mutex:
            has_epoch_rows, first_k_gt1 = self._epoch_summary_locked()
            return pre_boot_fill_ledger(
                _ScanView(self._store),
                first_k_gt1_boot_ts=first_k_gt1,
                has_epoch_rows=has_epoch_rows,
                decode=decode,
                in_family=in_family,
            )
