"""The registry reader and the evidence exports (ARCH-0 seam A 6f; AC 12 and AC 17 step 3).

``RegistryReader`` is the read-only view of ``registry/registry.sqlite``. ``write_export`` publishes
``evidence/registry/registry_<venue>_<date>[_hwm<k>].jsonl`` write-once, and ``newest_export``
classifies the directory and returns the export with the highest ``export_seq``. The module is a
sibling of ``registry_store`` (ruling A6e-R3): the store is the one writer of the database, and this
module never writes it.

An export file is canonical JSON lines: the rows it carries (each a sealed C5 row), then the
``registry_export/v1`` trailer, each line ending in ``\\n``. ``newest_export`` re-renders what it
parsed and refuses a file whose bytes differ, so a hand edit cannot pass as an export.

Choices ARCH leaves open, fixed here:

* The caller chooses which rows an export carries (all rows or the rows since the last export). The
  file is only required to be self-consistent: one venue, contiguous ``venue_seq``, and a trailer
  whose ``venue_seq`` and ``chain_head`` are the last row's. An export with no rows is legal.
* A ``_hwm<k>`` name must carry a trailer with ``export_seq == k``; a daily name carries any.
* Two candidate files with one ``export_seq`` are ambiguous and refuse; so does any candidate that
  does not read, parse or agree with its name. One bad candidate is never skipped in favour of an
  older good one.
* A stored row that does not decode is ``schema_mismatch``: the data no longer fits the schema.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from typing import ClassVar, Final, NamedTuple

from breezy.persistence.autonomy import single_read
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.registry_store import (
    _SELECT_MASTER,
    APPLICATION_ID,
    COLUMNS,
    DDL_OBJECTS,
    SCHEMA_ID,
    USER_VERSION,
    StoreDrifted,
    _from_db,
)
from breezy.persistence.autonomy.schemas import (
    ExportTrailer,
    RefusalReason,
    TransitionRow,
    UnreadableReason,
    check_venue,
)
from breezy.persistence.autonomy.wire import check_int, parse_json_exact

__all__ = [
    "EXPORT_FILE_MODE",
    "MAX_EXPORT_BYTES",
    "ExportAbsent",
    "ExportRead",
    "ExportRefused",
    "ExportUnreadable",
    "RegistryReader",
    "RegistryUnreadable",
    "newest_export",
    "unreadable_reason",
    "write_export",
]

EXPORT_FILE_MODE: Final = 0o444
MAX_EXPORT_BYTES: Final = 64 * 1024 * 1024
_EXPORT_PARTS: Final = ("evidence", "registry")
_MS_PER_S: Final = 1000
_PRIMARY_CODE_MASK: Final = 0xFF

_NAME_FLAGS: Final = re.ASCII
_DATE: Final = r"\d{4}-\d{2}-\d{2}"
#: ``paths.VENUE_RE`` without its anchors (a test pins the two together).
_VENUE_CLASS: Final = r"[a-z0-9_]{1,32}"
_OTHER_VENUE_EXPORT: Final = re.compile(
    rf"\Aregistry_{_VENUE_CLASS}_{_DATE}(?:_hwm\d+)?\.jsonl\Z", _NAME_FLAGS
)
_RESET_RECORD: Final = re.compile(r"\Ahwm_reset_.+\.json\Z", _NAME_FLAGS)
#: The ``write_once`` temp name; it is never an export, since ``write_once`` publishes by ``link``.
_WRITE_ONCE_TEMP: Final = re.compile(r"\A\.tmp\.[0-9a-f]{16}\Z", _NAME_FLAGS)

_SELECT_AFTER: Final = (
    f"SELECT {', '.join(COLUMNS)} FROM transitions WHERE venue = ? AND venue_seq > ? "
    "ORDER BY venue_seq"
)
_BEGIN: Final = "BEGIN"
_ROLLBACK: Final = "ROLLBACK"
_PRAGMA_APPLICATION_ID: Final = "PRAGMA application_id"
_PRAGMA_USER_VERSION: Final = "PRAGMA user_version"
_SELECT_META: Final = "SELECT schema FROM meta"

# --- the reader -----------------------------------------------------------------------------------


class RegistryUnreadable(Exception):
    """The registry could not be read; ``reason`` is a member of ``UnreadableReason``."""

    def __init__(self, reason: UnreadableReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


_BUSY_CODES: Final = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
_IO_CODES: Final = frozenset({sqlite3.SQLITE_IOERR, sqlite3.SQLITE_CANTOPEN})


def unreadable_reason(exc: BaseException) -> UnreadableReason:
    """Map one failure to its reason (AC 12): extended result codes fold onto their primary code."""
    if isinstance(exc, OSError):
        return UnreadableReason.IO
    code = getattr(exc, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return UnreadableReason.SQLITE_ERROR
    if code == sqlite3.SQLITE_READONLY_ROLLBACK:
        return UnreadableReason.HOT_JOURNAL
    primary = code & _PRIMARY_CODE_MASK
    if primary in _BUSY_CODES:
        return UnreadableReason.BUSY
    if primary in _IO_CODES:
        return UnreadableReason.IO
    return UnreadableReason.SQLITE_ERROR


class RegistryReader:
    """Read-only access to one registry root's ``registry.sqlite``; one connection per call.

    The connection is opened ``mode=ro`` with ``query_only=ON`` and ``trusted_schema=OFF``. It never
    writes, so it sets no ``synchronous`` level (that belongs to the writer, A6e-R6).
    """

    def __init__(self, paths: AutonomyPaths | ShadowPaths, *, busy_timeout_ms: int) -> None:
        if not isinstance(paths, AutonomyPaths | ShadowPaths):
            raise TypeError("paths must be AutonomyPaths or ShadowPaths")
        if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int):
            raise TypeError("busy_timeout_ms must be an int")
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must not be negative")
        self._db = paths.registry_db()
        self._busy_timeout_s = busy_timeout_ms / _MS_PER_S

    def read_venue_rows(self, venue: str, after_seq: int = 0) -> tuple[TransitionRow, ...]:
        """The venue's rows with ``venue_seq > after_seq``, in order; chain checks are the caller's.

        Raises ``RegistryUnreadable``. A chain that does not verify is not unreadable: the rows come
        back and ``chain.verify_venue_chain`` refuses them.
        """
        venue = check_venue(venue)
        check_int(after_seq, "after_seq")
        try:
            conn = self._connect()
        except (sqlite3.Error, OSError) as exc:
            raise RegistryUnreadable(unreadable_reason(exc), type(exc).__name__) from exc
        try:
            conn.execute(_BEGIN)
            _check_identity(conn)
            return tuple(
                _from_db(record) for record in conn.execute(_SELECT_AFTER, (venue, after_seq))
            )
        except RegistryUnreadable:
            raise
        except StoreDrifted as exc:
            raise RegistryUnreadable(UnreadableReason.SCHEMA_MISMATCH, str(exc)) from exc
        except (sqlite3.Error, OSError) as exc:
            raise RegistryUnreadable(unreadable_reason(exc), type(exc).__name__) from exc
        finally:
            _close(conn)

    def _connect(self) -> sqlite3.Connection:
        info = os.lstat(self._db)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("the registry database is not a regular file")
        conn = sqlite3.connect(
            f"{self._db.as_uri()}?mode=ro",
            uri=True,
            timeout=self._busy_timeout_s,
            isolation_level=None,
        )
        try:
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA trusted_schema = OFF")
        except BaseException:
            conn.close()
            raise
        return conn


def _check_identity(conn: sqlite3.Connection) -> None:
    """Refuse a database whose identity or any owned object differs from the DDL constants."""
    app_id = conn.execute(_PRAGMA_APPLICATION_ID).fetchone()[0]
    version = conn.execute(_PRAGMA_USER_VERSION).fetchone()[0]
    objects = {tuple(row) for row in conn.execute(_SELECT_MASTER)}
    if app_id != APPLICATION_ID or version != USER_VERSION or objects != set(DDL_OBJECTS):
        raise RegistryUnreadable(UnreadableReason.SCHEMA_MISMATCH, "identity or objects differ")
    if [row[0] for row in conn.execute(_SELECT_META)] != [SCHEMA_ID]:
        raise RegistryUnreadable(UnreadableReason.SCHEMA_MISMATCH, "meta differs")


def _close(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.execute(_ROLLBACK)
    except sqlite3.Error:
        pass  # the connection is about to close; a failed ROLLBACK must not mask the real error
    finally:
        conn.close()


# --- the export file ------------------------------------------------------------------------------


class ExportRefused(Exception):
    """``write_export`` was handed rows or a trailer that do not describe one consistent export."""


def _inconsistency(trailer: ExportTrailer, rows: tuple[TransitionRow, ...]) -> str | None:
    """Why ``rows`` and ``trailer`` are not one export, or ``None``."""
    previous: int | None = None
    for row in rows:
        if row.venue != trailer.venue:
            return "a row belongs to another venue"
        if row.venue_seq is None or row.transition_hash is None or row.seq is None:
            return "a row is not sealed"
        if previous is not None and row.venue_seq != previous + 1:
            return "venue_seq is not contiguous"
        previous = row.venue_seq
    if rows and (rows[-1].venue_seq, rows[-1].transition_hash) != (
        trailer.venue_seq,
        trailer.chain_head,
    ):
        return "the trailer is not the last row"
    return None


def _render(trailer: ExportTrailer, rows: tuple[TransitionRow, ...]) -> bytes:
    lines = [canonical_json(row.to_wire()) for row in rows]
    lines.append(canonical_json(trailer.to_wire()))
    return b"\n".join(lines) + b"\n"


def write_export(
    paths: AutonomyPaths | ShadowPaths,
    *,
    day: str,
    trailer: ExportTrailer,
    rows: tuple[TransitionRow, ...],
    hwm_export_seq: int | None = None,
) -> single_read.WriteOutcome:
    """Publish one export write-once (0444) and return ``WRITTEN`` or ``EXISTS_EQUAL``.

    ``hwm_export_seq`` makes it the reset variant ``_hwm<k>``; ``k`` must be the trailer's
    ``export_seq``. Raises ``ExportRefused`` for inconsistent input and ``SingleReadRefused`` (never
    a silent overwrite) for a missing directory, other bytes at the name, or a failed write.
    """
    if not isinstance(paths, AutonomyPaths | ShadowPaths):
        raise TypeError("paths must be AutonomyPaths or ShadowPaths")
    rows = tuple(rows)
    problem = _inconsistency(trailer, rows)
    if problem is not None:
        raise ExportRefused(problem)
    if hwm_export_seq is not None and hwm_export_seq != trailer.export_seq:
        raise ExportRefused("the _hwm name must carry the trailer's export_seq")
    path = paths.export_file(trailer.venue, day, hwm_export_seq=hwm_export_seq)
    data = _render(trailer, rows)
    if len(data) > MAX_EXPORT_BYTES:
        raise ExportRefused("the export exceeds MAX_EXPORT_BYTES")
    return single_read.write_once_tmpfile(path, data, root=paths.root, mode=EXPORT_FILE_MODE)


# --- newest_export --------------------------------------------------------------------------------


class ExportRead(NamedTuple):
    """The export with the highest ``export_seq``: its trailer and the rows it carries."""

    trailer: ExportTrailer
    rows: tuple[TransitionRow, ...]


@dataclass(frozen=True, slots=True)
class ExportUnreadable:
    """The directory or a candidate cannot be trusted: ``export_unreadable``, fail closed."""

    detail: str
    reason: ClassVar[RefusalReason] = RefusalReason.EXPORT_UNREADABLE


@dataclass(frozen=True, slots=True)
class ExportAbsent:
    """The directory lists no export of this venue (the resolver applies the 26 h rule)."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    name: str
    hwm_export_seq: int | None


_IGNORED: Final = "ignored"


def _classify_name(name: str, venue: str) -> _Candidate | str | None:
    """A candidate for this venue's export, ``"ignored"`` for a known foreign name, else ``None``.

    ``None`` is any other name: the caller refuses it (A5-R6, A6-R1).
    """
    own = re.compile(
        rf"\Aregistry_{re.escape(venue)}_{_DATE}(?:_hwm(?P<hwm>\d+))?\.jsonl\Z", _NAME_FLAGS
    )
    matched = own.fullmatch(name)
    if matched is not None:
        hwm = matched.group("hwm")
        return _Candidate(name, None if hwm is None else int(hwm))
    if (
        _OTHER_VENUE_EXPORT.fullmatch(name)
        or _RESET_RECORD.fullmatch(name)
        or _WRITE_ONCE_TEMP.fullmatch(name)
    ):
        return _IGNORED
    return None


def _classify_all(names: list[str], venue: str) -> list[_Candidate] | ExportUnreadable:
    candidates: list[_Candidate] = []
    for name in sorted(names):
        kind = _classify_name(name, venue)
        if kind is None:
            return ExportUnreadable(f"unknown name in the export directory: {name!r}")
        if isinstance(kind, _Candidate):
            candidates.append(kind)
    return candidates


def _read_candidate(dirfd: int, candidate: _Candidate, venue: str) -> ExportRead | ExportUnreadable:
    name = candidate.name
    try:
        data = single_read.read_once_at(
            dirfd, name, max_bytes=MAX_EXPORT_BYTES, policy=single_read.ReadPolicy.STRICT
        )
    except single_read.SingleReadRefused as exc:
        return ExportUnreadable(f"{name}: {exc.reason.value}")
    try:
        *row_lines, trailer_line = data.split(b"\n")[:-1]
        trailer = ExportTrailer.from_wire(parse_json_exact(trailer_line))
        rows = tuple(TransitionRow.from_wire(parse_json_exact(line)) for line in row_lines)
    except (ValueError, TypeError):
        return ExportUnreadable(f"{name}: does not parse")
    if _render(trailer, rows) != data:
        return ExportUnreadable(f"{name}: not canonical bytes")
    problem = _inconsistency(trailer, rows)
    if problem is None and trailer.venue != venue:
        problem = "the trailer names another venue"
    if problem is None and candidate.hwm_export_seq not in (None, trailer.export_seq):
        problem = "the _hwm name disagrees with export_seq"
    return ExportUnreadable(f"{name}: {problem}") if problem else ExportRead(trailer, rows)


def newest_export(
    paths: AutonomyPaths | ShadowPaths, venue: str
) -> ExportRead | ExportUnreadable | ExportAbsent:
    """The export of ``venue`` with the highest ``export_seq`` (AC 17 step 3).

    Every name in ``evidence/registry/`` is classified first. This venue's exports are candidates;
    another venue's exports, ``hwm_reset_*.json`` records and ``write_once`` temp names are ignored;
    any other name, a missing or unlistable directory, or a candidate that does not read, parse and
    agree with its name gives ``ExportUnreadable``. No candidate gives ``ExportAbsent``.
    """
    venue = check_venue(venue)
    try:
        rootfd = single_read.open_root(paths.root)
    except single_read.SingleReadRefused as exc:
        return ExportUnreadable(f"data root: {exc.reason.value}")
    try:
        try:
            dirfd = single_read.walk_dirs(rootfd, _EXPORT_PARTS)
        except single_read.SingleReadRefused as exc:
            return ExportUnreadable(f"export directory: {exc.reason.value}")
        try:
            return _newest_in(dirfd, venue)
        except OSError as exc:
            return ExportUnreadable(f"export directory listing: {type(exc).__name__}")
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)


def _newest_in(dirfd: int, venue: str) -> ExportRead | ExportUnreadable | ExportAbsent:
    candidates = _classify_all(os.listdir(dirfd), venue)
    if isinstance(candidates, ExportUnreadable):
        return candidates
    newest: ExportRead | None = None
    for candidate in candidates:
        read = _read_candidate(dirfd, candidate, venue)
        if isinstance(read, ExportUnreadable):
            return read
        if newest is not None and read.trailer.export_seq == newest.trailer.export_seq:
            return ExportUnreadable(f"two exports share export_seq {read.trailer.export_seq}")
        if newest is None or read.trailer.export_seq > newest.trailer.export_seq:
            newest = read
    return ExportAbsent() if newest is None else newest
