"""EXEC-PAR BG-2: the K-epoch ledger (D-PREREG spec 10, ``BG-2``).

Pure functions over the BG-1a epoch writers on ``SubmitIntentLatch``:

* :func:`record_boot_epoch` appends the boot row and, when the effective K
  differs from the previous row's, writes the ``k_change`` ``stage_reset``;
* :func:`record_clean_stop` closes the row at disposal;
* :func:`k_forced_amendment` builds the row the breaker watcher writes when the
  exec client's bucket guard forces K=1 after the boot row was written;
* :class:`EpochLedger` / :func:`read_epoch_ledger` classify a fill's
  ``ts_event`` into a ``single`` or ``parallel`` stratum (J1).

An epoch is ``parallel`` iff its effective K is above 1, it carries no forced
reason, and no K-forced amendment falls inside it. A crash leaves ``stop_ts``
unset; the next ``boot_ts`` closes the epoch.
"""

from __future__ import annotations

import bisect
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from breezy.persistence.epoch_strata import STRATUM_PARALLEL, STRATUM_SINGLE
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    Amendment,
    EpochRow,
    StageReset,
    decode_record,
)

__all__ = [
    "K_CHANGE_CAUSE",
    "K_FORCED_NOTE_PREFIX",
    "STRATUM_PARALLEL",
    "STRATUM_SINGLE",
    "EpochLedger",
    "EpochWritePort",
    "k_forced_amendment",
    "read_epoch_ledger",
    "record_boot_epoch",
    "record_clean_stop",
]

K_CHANGE_CAUSE: Final[str] = "k_change"
K_FORCED_NOTE_PREFIX: Final[str] = "k_forced_to_1:"

_EPOCH_PREFIX: Final[str] = EXEC_PAR_PREFIX + "epoch/"
_AMENDMENT_PREFIX: Final[str] = EXEC_PAR_PREFIX + "amendment/"
_BUSY_TIMEOUT_S: Final[float] = 5.0


class EpochWritePort(Protocol):
    """The slice of ``SubmitIntentLatch`` the boot / stop paths use."""

    def max_slots(self) -> int: ...
    @property
    def k_forced_reason(self) -> str | None: ...
    def read_latest_epoch_row(self) -> EpochRow | None: ...
    def write_stage_reset(self, record: StageReset) -> None: ...
    def write_epoch_row(self, record: EpochRow) -> None: ...
    def write_epoch_stop_ts(self, boot_ts: int, stop_ts: int) -> bool: ...


def record_boot_epoch(latch: EpochWritePort, *, commit_sha: str, boot_ts: int) -> EpochRow:
    """Append this boot's epoch row; write the ``k_change`` floor first if K changed.

    The floor goes first so a crash between the two writes cannot lose it: the
    next boot still sees the old K and writes it again. The very first boot has
    no prior row and so writes no ``stage_reset``. A write failure propagates.
    """
    row = EpochRow(
        commit_sha=commit_sha,
        effective_k=latch.max_slots(),
        force_reason=latch.k_forced_reason,
        boot_ts=boot_ts,
    )
    prior = latch.read_latest_epoch_row()
    if prior is not None and prior.effective_k != row.effective_k:
        latch.write_stage_reset(StageReset(ts=boot_ts, cause=K_CHANGE_CAUSE, halt_ts=None))
    latch.write_epoch_row(row)
    return row


def record_clean_stop(latch: EpochWritePort, *, boot_ts: int, stop_ts: int) -> bool:
    """Set ``stop_ts`` on this boot's row once; ``False`` if it was already set."""
    return latch.write_epoch_stop_ts(boot_ts, stop_ts)


def k_forced_amendment(*, ts_ns: int, commit_sha: str, reason: str) -> Amendment:
    """The amendment row for a K=1 force that happened after the boot row (names no value)."""
    return Amendment(ts_ns=ts_ns, commit_sha=commit_sha, note=K_FORCED_NOTE_PREFIX + reason)


@dataclass(frozen=True, slots=True)
class EpochLedger:
    """Epoch rows (ascending ``boot_ts``) plus the timestamps of K-forced amendments."""

    epochs: tuple[EpochRow, ...]
    forced_amendment_ts: tuple[int, ...]

    def stratum_of(self, ts_event_ns: int) -> str:
        """``parallel`` or ``single`` for a fill at ``ts_event_ns`` (before any epoch: single)."""
        boots = [row.boot_ts for row in self.epochs]
        index = bisect.bisect_right(boots, ts_event_ns) - 1
        if index < 0:
            return STRATUM_SINGLE
        row = self.epochs[index]
        if row.effective_k <= 1 or row.force_reason is not None:
            return STRATUM_SINGLE
        end = boots[index + 1] if index + 1 < len(boots) else None
        for ts in self.forced_amendment_ts:
            if ts >= row.boot_ts and (end is None or ts < end):
                return STRATUM_SINGLE
        return STRATUM_PARALLEL


def read_epoch_ledger(db_path: Path) -> EpochLedger:
    """Read the epoch and K-forced amendment rows through a ``mode=ro`` open (never writes)."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_S)
    try:
        conn.execute("PRAGMA query_only=ON")
        epoch_values = _values_under(conn, _EPOCH_PREFIX)
        amendment_values = _values_under(conn, _AMENDMENT_PREFIX)
    finally:
        conn.close()
    epochs = sorted((decode_record(EpochRow, raw) for raw in epoch_values), key=_boot_ts)
    forced = sorted(
        amendment.ts_ns
        for amendment in (decode_record(Amendment, raw) for raw in amendment_values)
        if amendment.note.startswith(K_FORCED_NOTE_PREFIX)
    )
    return EpochLedger(epochs=tuple(epochs), forced_amendment_ts=tuple(forced))


def _boot_ts(row: EpochRow) -> int:
    return row.boot_ts


def _values_under(conn: sqlite3.Connection, prefix: str) -> list[bytes]:
    rows = conn.execute(
        "SELECT value FROM state WHERE substr(key, 1, ?) = ? ORDER BY key",
        (len(prefix), prefix),
    ).fetchall()
    return [bytes(value) for (value,) in rows]
