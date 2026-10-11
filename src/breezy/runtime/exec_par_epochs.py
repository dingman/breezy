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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import quote

from breezy.persistence.epoch_strata import STRATUM_PARALLEL, STRATUM_SINGLE
from breezy.runtime.exec_par_records import (
    AMENDMENT_KEY_PREFIX,
    EPOCH_KEY_PREFIX,
    Amendment,
    EpochRow,
    ExecParRecordError,
    StageReset,
    decode_record,
)

__all__ = [
    "K_CHANGE_CAUSE",
    "K_FORCED_NOTE_PREFIX",
    "STRATUM_PARALLEL",
    "STRATUM_SINGLE",
    "EpochFloorWriteError",
    "EpochLedger",
    "EpochLedgerCorrupt",
    "EpochLedgerWriteError",
    "EpochRowWriteError",
    "EpochWritePort",
    "k_forced_amendment",
    "read_epoch_ledger",
    "record_boot_epoch",
    "record_clean_stop",
]

K_CHANGE_CAUSE: Final[str] = "k_change"
K_FORCED_NOTE_PREFIX: Final[str] = "k_forced_to_1:"

_BUSY_TIMEOUT_S: Final[float] = 5.0


class EpochLedgerWriteError(Exception):
    """A boot-time ledger write failed; ``__cause__`` is the underlying error."""


class EpochRowWriteError(EpochLedgerWriteError):
    """The epoch row itself could not be written (the floor, if any, already was)."""


class EpochFloorWriteError(EpochLedgerWriteError):
    """The ``k_change`` ``stage_reset`` could not be written. Never to be swallowed."""


class EpochLedgerCorrupt(ValueError):
    """An epoch or amendment row did not decode; M1-v3 separation cannot be trusted."""


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
    no prior row and so writes no ``stage_reset``. A failed floor write raises
    :class:`EpochFloorWriteError`, a failed row write :class:`EpochRowWriteError`;
    the caller decides which one it may contain.
    """
    row = EpochRow(
        commit_sha=commit_sha,
        effective_k=latch.max_slots(),
        force_reason=latch.k_forced_reason,
        boot_ts=boot_ts,
    )
    prior = latch.read_latest_epoch_row()
    if prior is not None and prior.effective_k != row.effective_k:
        try:
            latch.write_stage_reset(StageReset(ts=boot_ts, cause=K_CHANGE_CAUSE, halt_ts=None))
        except Exception as exc:
            raise EpochFloorWriteError("k_change stage_reset write failed") from exc
    try:
        latch.write_epoch_row(row)
    except Exception as exc:
        raise EpochRowWriteError("epoch row write failed") from exc
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
    _boots: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_boots", tuple(row.boot_ts for row in self.epochs))

    def stratum_of(self, ts_event_ns: int) -> str:
        """``parallel`` or ``single`` for a fill at ``ts_event_ns`` (before any epoch: single).

        A missing or late K-force amendment leaves a K=1 epoch classed ``parallel``. That is
        the safe direction: it only removes fills from M1-v3 separation and can never place a
        parallel fill in the single stratum. An amendment likewise never retracts the
        classification of an epoch that ended before it was written (``exec/client.py`` is
        byte-pinned, so the marker cannot be made more reliable from here).
        """
        boots = self._boots
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
    """Read the epoch and K-forced amendment rows through a ``mode=ro`` open (never writes).

    A row that does not decode raises :class:`EpochLedgerCorrupt` naming its key. It is never
    skipped: a skipped parallel epoch would let parallel fills into M1-v3.
    """
    uri = f"file:{quote(db_path.resolve().as_posix())}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=_BUSY_TIMEOUT_S)
    try:
        conn.execute("PRAGMA query_only=ON")
        epoch_items = _rows_under(conn, EPOCH_KEY_PREFIX)
        amendment_items = _rows_under(conn, AMENDMENT_KEY_PREFIX)
    finally:
        conn.close()
    epochs = sorted((_decode(EpochRow, k, raw) for k, raw in epoch_items), key=_boot_ts)
    forced = sorted(
        amendment.ts_ns
        for amendment in (_decode(Amendment, k, raw) for k, raw in amendment_items)
        if amendment.note.startswith(K_FORCED_NOTE_PREFIX)
    )
    return EpochLedger(epochs=tuple(epochs), forced_amendment_ts=tuple(forced))


def _decode[R](factory: type[R], key: str, raw: bytes) -> R:
    try:
        return decode_record(factory, raw)
    except ExecParRecordError as exc:
        raise EpochLedgerCorrupt(
            f"epoch ledger corrupt; M1-v3 separation cannot be guaranteed (key {key})"
        ) from exc


def _boot_ts(row: EpochRow) -> int:
    return row.boot_ts


def _rows_under(conn: sqlite3.Connection, prefix: str) -> list[tuple[str, bytes]]:
    rows = conn.execute(
        "SELECT key, value FROM state WHERE substr(key, 1, ?) = ? ORDER BY key",
        (len(prefix), prefix),
    ).fetchall()
    return [(str(key), bytes(value)) for key, value in rows]
