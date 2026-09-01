"""Read-back preflight for streamed feather tapes (BL-23).

Why this module exists
----------------------
``StreamingFeatherWriter`` writes the Arrow IPC **stream** format, and
``close()`` is what appends the end-of-stream marker
(``persistence/writer.py:596-611``). A killed process therefore always leaves a
stream with no marker -- harmless on its own, because a clean EOF at a message
boundary reads back in full. The hazard is the other half: whatever sits in the
file object's buffer when the process dies is lost, so the file can end
MID-MESSAGE. Then::

    # nautilus_trader/persistence/catalog/parquet.py:2788-2800
    try:
        with self.fs.open(path) as f:
            reader = pa.ipc.open_stream(f)
            return reader.read_all()
    except (pa.ArrowInvalid, OSError):
        return None

and ``convert_stream_to_data`` turns that ``None`` into ``continue``
(``:2644-2646``). The conversion "succeeds" over an EMPTY catalog. Measured
against a real SIGKILL: **228 KB on disk, 0 rows delivered, no exception, no
log line.**

The danger is interpretive, and it is the whole reason this exists. A
silently-truncated tape reads as "0 rows", reads as "quiet market", reads as
"no edge" -- a false NO-GO on a strategy, produced by a file-handling bug.

L-1 null hypothesis (checked against the installed 1.231.0 source)
------------------------------------------------------------------
**Nautilus offers no validating or batch-wise feather reader.** Every read path
funnels through the single-shot ``_read_feather_file`` above:
``_read_feather`` (``:2577``) and ``convert_stream_to_data`` (``:2644``) are
its only callers, and both treat ``None`` as "skip this file". The
``raise_on_failed_deserialize`` flag on ``_read_feather`` (``:2568``) does not
help: it guards *deserialization* of a table that was already read, and the
``table is None`` check at ``:2578-2580`` ``continue``s before that flag is
ever consulted. ``grep -rn 'read_next_batch\\|RecordBatchStreamReader\\|
iter_batches'`` over the whole installed package returns **zero hits**, and
``open_stream`` appears in exactly five places, all of which immediately
``read_all()``. So the incremental read below is genuinely absent upstream.

Nautilus is not modified, patched, or wrapped. This module reads bytes that
Nautilus wrote, with pyarrow, and never writes.

What the verdicts mean
----------------------
The discriminator between "empty" and "truncated" is NOT the row count -- both
are zero -- it is **where the byte stream stops relative to Arrow's message
framing**:

``EMPTY_FILE``
    Zero bytes. The writer opened the file and never flushed. Nothing was
    captured, nothing was lost. Ordinary: the live tree carries one of these
    for ``instrument_close`` on most runs.
``EMPTY_STREAM``
    A readable schema, zero record batches, ending on a message boundary. The
    capture genuinely recorded nothing for this type.
``INTACT``
    One or more batches, ending on a message boundary. ``end_of_stream_marker``
    separates a cleanly-closed writer from a killed-but-aligned one; both are
    fully readable.
``TRUNCATED``
    The trailing bytes are a partial Arrow message. Data was written and then
    cut. This includes the case where even the schema message is incomplete --
    zero rows, but a LOSS, not an empty capture.
``UNREADABLE``
    The file could not be opened at all. An operational alarm, never a
    zero-row result.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import pyarrow as pa

__all__ = [
    "END_OF_STREAM_MARKER",
    "FeatherFileReport",
    "FeatherStatus",
    "PreflightError",
    "PreflightReport",
    "SalvageResult",
    "TruncatedTapeError",
    "inspect_feather_file",
    "list_instance_ids",
    "salvage_feather_file",
    "scan_instance",
]

#: A 0xFFFFFFFF continuation token followed by a zero-length metadata block.
#: ``StreamingFeatherWriter.close()`` appends it; a killed writer never does.
END_OF_STREAM_MARKER = b"\xff\xff\xff\xff\x00\x00\x00\x00"

#: The subdirectory the live recorder stages feather under. ``backtest`` is the
#: other value Nautilus uses (``parquet.py:2539``, ``:2561``).
DEFAULT_SUBDIRECTORY = "live"

#: Failures pyarrow raises for a stream that ran out of bytes mid-message. This
#: is deliberately the SAME tuple Nautilus catches at ``parquet.py:2799`` -- if
#: the two ever diverge, this module would classify a file the native path
#: silently drops (or the reverse), which is the defect wearing a new hat.
_TRUNCATION_ERRORS: tuple[type[BaseException], ...] = (pa.ArrowInvalid, OSError)


class PreflightError(Exception):
    """The preflight could not be run as asked -- an operator-facing mistake.

    Raised rather than returning an empty report, because an empty report for a
    typo'd instance id is the original defect one level up.
    """


class TruncatedTapeError(Exception):
    """A partial salvage was unwrapped as if it were complete."""


class FeatherStatus(StrEnum):
    """The verdict for a single feather file. See the module docstring."""

    INTACT = "INTACT"
    EMPTY_FILE = "EMPTY_FILE"
    EMPTY_STREAM = "EMPTY_STREAM"
    TRUNCATED = "TRUNCATED"
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class FeatherFileReport:
    """What one feather file actually holds, byte-for-byte."""

    path: Path
    status: FeatherStatus
    size_bytes: int
    #: Bytes consumed by complete Arrow messages. Equals ``size_bytes`` for
    #: every non-truncated file.
    readable_bytes: int
    batches: int
    rows: int
    schema_readable: bool
    ended_mid_message: bool
    end_of_stream_marker: bool
    mtime_ns: int
    #: The pyarrow failure text, verbatim, when there was one.
    failure: str | None

    @property
    def lost_bytes(self) -> int:
        """Bytes on disk that no complete Arrow message covers."""
        return self.size_bytes - self.readable_bytes

    @property
    def is_truncated(self) -> bool:
        return self.status is FeatherStatus.TRUNCATED

    @property
    def is_empty(self) -> bool:
        return self.status in (FeatherStatus.EMPTY_FILE, FeatherStatus.EMPTY_STREAM)


@dataclass(frozen=True)
class PreflightReport:
    """Every feather file staged for one run instance."""

    catalog_root: Path
    subdirectory: str
    instance_id: str
    files: tuple[FeatherFileReport, ...]

    @property
    def total_rows(self) -> int:
        return sum(file.rows for file in self.files)

    @property
    def truncated(self) -> tuple[FeatherFileReport, ...]:
        return tuple(file for file in self.files if file.is_truncated)

    @property
    def unreadable(self) -> tuple[FeatherFileReport, ...]:
        return tuple(file for file in self.files if file.status is FeatherStatus.UNREADABLE)

    @property
    def empty(self) -> tuple[FeatherFileReport, ...]:
        return tuple(file for file in self.files if file.is_empty)

    @property
    def intact(self) -> tuple[FeatherFileReport, ...]:
        return tuple(file for file in self.files if file.status is FeatherStatus.INTACT)

    @property
    def has_truncation(self) -> bool:
        """True if ANY file lost bytes, or could not be read at all."""
        return bool(self.truncated) or bool(self.unreadable)

    @property
    def captured_nothing(self) -> bool:
        """Zero rows across the whole instance. Never a success."""
        return self.total_rows == 0


@dataclass(frozen=True)
class SalvageResult:
    """The readable prefix of a feather file, and what it cost.

    Deliberately NOT a bare :class:`pyarrow.Table`. A salvage that looked like
    a clean read would recreate the very defect this module closes, one level
    up, so unwrapping is either an explicit ``.table`` (having seen
    :attr:`is_partial`) or :meth:`require_complete`, which refuses.

    ``rows_lost`` is absent on purpose. The incomplete trailing message's row
    count is not on disk and cannot be recovered; inventing it would be exactly
    the kind of confident wrong number this ticket exists to eliminate.
    :attr:`bytes_lost` IS knowable and is reported.
    """

    report: FeatherFileReport
    table: pa.Table | None

    @property
    def is_partial(self) -> bool:
        return self.report.status in (FeatherStatus.TRUNCATED, FeatherStatus.UNREADABLE)

    @property
    def rows_recovered(self) -> int:
        return self.report.rows

    @property
    def batches_recovered(self) -> int:
        return self.report.batches

    @property
    def bytes_lost(self) -> int:
        return self.report.lost_bytes

    def describe(self) -> str:
        """One line the caller can log or print without losing the caveat."""
        if not self.is_partial:
            return (
                f"{self.report.status.value} {self.report.path}: "
                f"rows={self.rows_recovered} batches={self.batches_recovered} "
                f"bytes={self.report.size_bytes} (complete)"
            )
        return (
            f"{self.report.status.value} {self.report.path}: PARTIAL -- recovered "
            f"rows={self.rows_recovered} batches={self.batches_recovered} from "
            f"{self.report.readable_bytes} of {self.report.size_bytes} bytes; "
            f"bytes_lost={self.bytes_lost}; rows lost is UNKNOWN (the incomplete "
            f"trailing Arrow message's row count is not on disk)"
        )

    def require_complete(self) -> pa.Table:
        """Return the table only if nothing was lost; otherwise raise."""
        if self.is_partial:
            raise TruncatedTapeError(
                f"refusing to return a partial read of {self.report.path}: "
                f"status={self.report.status.value}, recovered "
                f"rows={self.rows_recovered} batches={self.batches_recovered}, "
                f"bytes_lost={self.bytes_lost} of {self.report.size_bytes}. "
                f"Use `.table` explicitly if a partial tape is acceptable here."
            )
        if self.table is None:
            raise TruncatedTapeError(
                f"{self.report.path} holds no Arrow stream at all "
                f"(status={self.report.status.value}, {self.report.size_bytes} bytes), "
                f"so there is no schema to return an empty table for. Nothing was "
                f"lost -- nothing was ever written."
            )
        return self.table


@dataclass(frozen=True)
class _StreamScan:
    """Raw outcome of walking one Arrow stream."""

    batches: int
    rows: int
    consumed_bytes: int
    schema_readable: bool
    ended_mid_message: bool
    failure: str | None
    table: pa.Table | None


def _scan_stream(path: Path, *, collect: bool) -> _StreamScan:
    """Read an Arrow IPC stream ONE MESSAGE AT A TIME, stopping at the first
    incomplete one.

    This is the whole mitigation. ``read_all()`` -- the only read Nautilus ever
    performs -- is all-or-nothing: one partial trailing message discards every
    complete message before it. Iterating ``read_next_batch()`` instead keeps
    the readable prefix and turns the failure into a located, quantified fact.
    A measured SIGKILL that cost ``read_all()`` all 500 records yields 491 here.

    ``pa.OSFile`` rather than ``pa.memory_map`` or a whole-file ``read_bytes``:
    it is opened read-only so the inspection cannot mutate an irreplaceable
    tape, its ``tell()`` tracks the reader's consumed position exactly (with no
    read-ahead overshoot -- verified against a clean stream, where the final
    ``tell()`` equals the file size), and batches are copied out of it, so the
    salvaged table outlives the handle.
    """
    batches: list[Any] = []
    rows = 0
    count = 0
    failure: str | None = None
    ended_mid_message = False

    with pa.OSFile(str(path), "rb") as source:
        try:
            reader = pa.ipc.open_stream(source)
        except _TRUNCATION_ERRORS as exc:
            # The schema message itself is incomplete. Zero rows, exactly like
            # an empty capture -- and a LOSS, unlike one.
            return _StreamScan(
                batches=0,
                rows=0,
                consumed_bytes=0,
                schema_readable=False,
                ended_mid_message=True,
                failure=f"{type(exc).__name__}: {exc}",
                table=None,
            )

        consumed = source.tell()
        while True:
            try:
                batch = reader.read_next_batch()
            except StopIteration:
                # A clean end: either the end-of-stream marker, or EOF landing
                # exactly on a message boundary. Both read back in full.
                consumed = source.tell()
                break
            except _TRUNCATION_ERRORS as exc:
                failure = f"{type(exc).__name__}: {exc}"
                ended_mid_message = True
                break
            count += 1
            rows += batch.num_rows
            consumed = source.tell()
            if collect:
                batches.append(batch)

        table: pa.Table | None = None
        if collect:
            table = (
                pa.Table.from_batches(batches, reader.schema)
                if batches
                else reader.schema.empty_table()
            )

    return _StreamScan(
        batches=count,
        rows=rows,
        consumed_bytes=consumed,
        schema_readable=True,
        ended_mid_message=ended_mid_message,
        failure=failure,
        table=table,
    )


def _classify(scan: _StreamScan) -> FeatherStatus:
    """Empty versus truncated is decided by FRAMING, never by the row count.

    Both verdicts can carry zero rows. What separates them is whether the
    trailing bytes complete an Arrow message.
    """
    if scan.ended_mid_message:
        return FeatherStatus.TRUNCATED
    if scan.rows == 0:
        return FeatherStatus.EMPTY_STREAM
    return FeatherStatus.INTACT


def _inspect(path: Path, *, collect: bool) -> tuple[FeatherFileReport, pa.Table | None]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise PreflightError(f"cannot stat {path}: {exc}") from exc

    size = stat.st_size
    mtime_ns = stat.st_mtime_ns

    if size == 0:
        # Zero bytes cannot be truncated: nothing was ever flushed. Checked
        # BEFORE opening, because `pa.ipc.open_stream` raises ArrowInvalid on
        # an empty file and would otherwise be misread as a loss.
        return (
            FeatherFileReport(
                path=path,
                status=FeatherStatus.EMPTY_FILE,
                size_bytes=0,
                readable_bytes=0,
                batches=0,
                rows=0,
                schema_readable=False,
                ended_mid_message=False,
                end_of_stream_marker=False,
                mtime_ns=mtime_ns,
                failure=None,
            ),
            None,
        )

    try:
        scan = _scan_stream(path, collect=collect)
    except OSError as exc:
        return (
            FeatherFileReport(
                path=path,
                status=FeatherStatus.UNREADABLE,
                size_bytes=size,
                readable_bytes=0,
                batches=0,
                rows=0,
                schema_readable=False,
                ended_mid_message=False,
                end_of_stream_marker=False,
                mtime_ns=mtime_ns,
                failure=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )

    tail = _read_tail(path, len(END_OF_STREAM_MARKER))
    status = _classify(scan)
    return (
        FeatherFileReport(
            path=path,
            status=status,
            size_bytes=size,
            readable_bytes=scan.consumed_bytes,
            batches=scan.batches,
            rows=scan.rows,
            schema_readable=scan.schema_readable,
            ended_mid_message=scan.ended_mid_message,
            end_of_stream_marker=tail == END_OF_STREAM_MARKER,
            mtime_ns=mtime_ns,
            failure=scan.failure,
        ),
        scan.table,
    )


def _read_tail(path: Path, count: int) -> bytes:
    with path.open("rb") as handle:
        with contextlib.suppress(OSError):
            handle.seek(-count, 2)
        return handle.read(count)


def inspect_feather_file(path: Path) -> FeatherFileReport:
    """Classify one feather file without modifying it."""
    return _inspect(path, collect=False)[0]


def salvage_feather_file(path: Path) -> SalvageResult:
    """Recover the readable prefix of a feather file as an explicit PARTIAL."""
    report, table = _inspect(path, collect=True)
    return SalvageResult(report=report, table=table)


def _instance_dir(catalog_root: Path, instance_id: str, subdirectory: str) -> Path:
    return catalog_root / subdirectory / instance_id


def iter_feather_files(directory: Path) -> Iterator[Path]:
    """Every ``*.feather`` regular file under ``directory``, sorted.

    A byte-level walk on purpose. Nautilus's own enumeration
    (``_list_feather_data_files``) resolves each directory name to a registered
    data class and skips what it cannot map, so a file whose class is not
    imported would vanish from the report -- the silent-omission defect again.
    ``tests/contract/test_quote_tape_truncation_preflight.py`` pins that this
    walk is a superset of the native one.
    """
    for path in sorted(directory.rglob("*.feather")):
        if path.is_file():
            yield path


def list_instance_ids(
    catalog_root: Path, subdirectory: str = DEFAULT_SUBDIRECTORY
) -> tuple[str, ...]:
    """Run-instance directory names under ``<catalog_root>/<subdirectory>/``."""
    base = catalog_root / subdirectory
    if not base.is_dir():
        raise PreflightError(
            f"no {subdirectory!r} subdirectory under catalog root {catalog_root}; "
            f"there is nothing staged to check"
        )
    return tuple(sorted(child.name for child in base.iterdir() if child.is_dir()))


def scan_instance(
    catalog_root: Path,
    instance_id: str,
    subdirectory: str = DEFAULT_SUBDIRECTORY,
) -> PreflightReport:
    """Inspect every feather file staged for one run instance.

    Raises :class:`PreflightError` when the instance directory is absent or
    holds no feather files at all. Both are operator mistakes, and returning an
    empty report for either would be indistinguishable from a clean pass.
    """
    directory = _instance_dir(catalog_root, instance_id, subdirectory)
    if not directory.is_dir():
        raise PreflightError(
            f"no such run instance {instance_id!r} under "
            f"{catalog_root / subdirectory} (known: "
            f"{', '.join(list_instance_ids(catalog_root, subdirectory)) or 'none'})"
        )

    files = tuple(inspect_feather_file(path) for path in iter_feather_files(directory))
    if not files:
        raise PreflightError(
            f"run instance {instance_id!r} holds no .feather files under {directory}; "
            f"refusing to report a clean pass over nothing"
        )
    return PreflightReport(
        catalog_root=catalog_root,
        subdirectory=subdirectory,
        instance_id=instance_id,
        files=files,
    )
