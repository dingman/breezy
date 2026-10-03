"""``demand/v1``: the restrictive-demand record, its one writer and its venue-veto reader (AC 24).

A demand file can only stop entries (ARCH C5 Z11), so it needs no authentication, and this module
exposes no way to lift one: there is no archive, rename or delete here (the engine's archive is
AUT-5 WP4). Files live at ``registry/demand/<venue>/``, mode 0444, written once through
``single_read.write_once``:

* engine files ``<family_id>_<ts_ns>_engine.json``;
* producer files ``<family_id>_<reason>_<verdict_id>_<producer>.json``, only for ids in
  ``DEMAND_WRITER_PRODUCER_IDS``.

Writer rules: exact-set ``demand/v1``; at most ``DEMAND_FILE_MAX_BYTES``; ``family_id`` in the
venue fold and ``reason`` in ``DEMAND_REASONS`` (a file failing either would veto every family on
the venue, so none is written); one unarchived file per ``(family, reason)`` for every writer; a
producer re-run of the same ``verdict_id`` writes nothing; a producer file whose reason is not
``integrity_floor`` is written only while fewer than
``DEMAND_FILES_MAX - DEMAND_INTEGRITY_RESERVED`` files stand, so the reserved slots stay free for
engine and ``integrity_floor`` files; and no write takes the venue past ``DEMAND_FILES_MAX``.

Reader: a bad file, an unreadable directory or more than ``DEMAND_FILES_MAX`` files is a venue-wide
veto. A missing directory is no demand. Names and details are closed codes, never paths. The writer
check-then-write is not atomic across processes; the writers (one engine, one producer unit) are
serialised by their callers.
"""

from __future__ import annotations

import os
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.paths import (
    AutonomyPaths,
    ShadowPaths,
    family_component,
    venue_component,
)
from breezy.persistence.autonomy.pins import (
    DEMAND_FILE_MAX_BYTES,
    DEMAND_FILES_MAX,
    DEMAND_INTEGRITY_RESERVED,
    DEMAND_REASONS,
    DEMAND_WRITER_PRODUCER_IDS,
)
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    WriteOutcome,
    open_root,
    read_once_at,
    walk_dirs,
    write_once,
)
from breezy.persistence.autonomy.wire import (
    WireRefusalReason,
    WireRefused,
    check_int,
    check_match,
    check_sha256,
    optional_sha256,
    parse_json_exact,
    require_enum,
    require_exact_keys,
    require_ns,
    require_str,
)

__all__ = [
    "DemandOutcome",
    "DemandRecord",
    "DemandRefusalReason",
    "DemandRefused",
    "DemandScan",
    "DemandVetoReason",
    "DemandWrite",
    "scan_demands",
    "write_engine_demand",
    "write_producer_demand",
]

DEMAND_SCHEMA: Final = "demand/v1"
DEMAND_FILE_MODE: Final = 0o444
ENGINE_WRITER: Final = "engine"
INTEGRITY_REASON: Final = "integrity_floor"
_DEMAND_PARTS: Final = ("registry", "demand")
_WRITER_RE: Final = re.compile(r"\A[a-z0-9_]{1,32}(?:\.[a-z0-9_]{1,32}){0,3}\Z", re.ASCII)
_REASON_RE: Final = re.compile(r"\A[a-z0-9_]{1,48}\Z", re.ASCII)
_TEMP_NAME_RE: Final = re.compile(r"\A\.tmp\.[0-9a-f]{16}\Z", re.ASCII)
_KEYS: Final = ("schema", "venue", "family_id", "reason", "writer", "verdict_id", "ts_ns")


@dataclass(frozen=True, kw_only=True)
class DemandRecord:
    """``demand/v1``. ``verdict_id`` is required of a producer and optional for the engine."""

    venue: str
    family_id: str
    reason: str
    writer: str
    ts_ns: int
    verdict_id: str | None = None

    def __post_init__(self) -> None:
        venue_component(self.venue)
        family_component(self.family_id)
        check_match(self.reason, _REASON_RE, "reason")
        check_match(self.writer, _WRITER_RE, "writer")
        check_int(self.ts_ns, "ts_ns")
        if self.verdict_id is not None:
            check_sha256(self.verdict_id, "verdict_id")
        elif self.writer != ENGINE_WRITER:
            raise WireRefused(WireRefusalReason.BAD_VALUE, "verdict_id")  # names the file

    def filename(self) -> str:
        if self.writer == ENGINE_WRITER:
            return f"{self.family_id}_{self.ts_ns}_{ENGINE_WRITER}.json"
        return f"{self.family_id}_{self.reason}_{self.verdict_id}_{self.writer}.json"

    def to_wire(self) -> dict[str, object]:
        return {
            "schema": DEMAND_SCHEMA,
            "venue": self.venue,
            "family_id": self.family_id,
            "reason": self.reason,
            "writer": self.writer,
            "verdict_id": self.verdict_id,
            "ts_ns": self.ts_ns,
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=_KEYS)
        require_enum(obj, "schema", allowed=(DEMAND_SCHEMA,))
        return cls(
            venue=require_str(obj, "venue"),
            family_id=require_str(obj, "family_id"),
            reason=require_str(obj, "reason"),
            writer=require_str(obj, "writer"),
            verdict_id=optional_sha256(obj, "verdict_id"),
            ts_ns=require_ns(obj, "ts_ns"),
        )


class DemandOutcome(StrEnum):
    WRITTEN = "written"
    #: A producer file for this ``verdict_id`` already stands; nothing was written.
    ALREADY_PRESENT = "already_present"
    #: Another unarchived file already stops this (family, reason); nothing was written.
    SLOT_OCCUPIED = "slot_occupied"


class DemandRefusalReason(StrEnum):
    UNLISTED_PRODUCER = "unlisted_producer"
    NOT_ENGINE_WRITER = "not_engine_writer"
    UNKNOWN_REASON = "unknown_reason"
    UNKNOWN_FAMILY = "unknown_family"
    OVERSIZE = "oversize"
    #: A producer file past the cap that keeps the reserved INTEGRITY slots free.
    PRODUCER_CAP = "producer_cap"
    #: The venue holds ``DEMAND_FILES_MAX`` files; a further one would veto the venue.
    SLOTS_FULL = "slots_full"
    DIRECTORY_UNREADABLE = "directory_unreadable"
    WRITE_FAILED = "write_failed"


class DemandRefused(Exception):
    """The writer refused; ``reason`` is a closed code and ``detail`` never a path."""

    def __init__(self, reason: DemandRefusalReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class DemandWrite:
    outcome: DemandOutcome
    name: str


class DemandVetoReason(StrEnum):
    DIR_UNREADABLE = "dir_unreadable"
    TOO_MANY_FILES = "too_many_files"
    BAD_FILE = "bad_file"


@dataclass(frozen=True)
class DemandScan:
    """The demands standing for one venue, or the venue-wide veto (``demands`` is then empty)."""

    demands: tuple[DemandRecord, ...]
    venue_veto: bool
    veto_reason: DemandVetoReason | None


def _veto(reason: DemandVetoReason) -> DemandScan:
    return DemandScan(demands=(), venue_veto=True, veto_reason=reason)


def _read_one(dirfd: int, name: str, venue: str) -> DemandRecord | None:
    """The record in ``name``, or ``None`` unless it is exactly one valid, self-named demand."""
    try:
        raw = read_once_at(dirfd, name, max_bytes=DEMAND_FILE_MAX_BYTES, policy=ReadPolicy.STRICT)
        record = DemandRecord.from_wire(parse_json_exact(raw))
    except (SingleReadRefused, WireRefused, OSError):
        return None
    if record.venue != venue or record.filename() != name or raw != _bytes_of(record):
        return None
    return record


def _read_all(dirfd: int, names: list[str], venue: str) -> list[DemandRecord] | None:
    """Every record, or ``None`` for the first file that is not a valid demand."""
    records: list[DemandRecord] = []
    for name in names:
        record = _read_one(dirfd, name, venue)
        if record is None:
            return None
        records.append(record)
    return records


def _bytes_of(record: DemandRecord) -> bytes:
    return canonical_json(record.to_wire())


def _listing(dirfd: int) -> list[str]:
    """Every name that counts: the pinned ``write_once`` temp pattern is not a demand."""
    return sorted(n for n in os.listdir(dirfd) if not _TEMP_NAME_RE.fullmatch(n))


def scan_demands(
    paths: AutonomyPaths | ShadowPaths, venue: str, *, fold_family_ids: Collection[str]
) -> DemandScan:
    """Read ``registry/demand/<venue>/``: every valid demand, or a venue-wide veto.

    Vetoed: an unreadable or unsafe directory, more than ``DEMAND_FILES_MAX`` files, and any file
    that is oversize, a symlink, group- or other-writable, unparseable, not exactly ``demand/v1``,
    for another venue, named differently from its record, for a family outside ``fold_family_ids``
    or with a reason outside ``DEMAND_REASONS``. A missing directory means no demands.
    """
    venue_component(venue)
    try:
        rootfd = open_root(paths.root)
    except SingleReadRefused as exc:
        return _scan_refused(exc)
    try:
        try:
            dirfd = walk_dirs(rootfd, (*_DEMAND_PARTS, venue), create=False)
        except SingleReadRefused as exc:
            return _scan_refused(exc)
        try:
            names = _listing(dirfd)
            if len(names) > DEMAND_FILES_MAX:
                return _veto(DemandVetoReason.TOO_MANY_FILES)
            records = _read_all(dirfd, names, venue)
        except OSError:
            return _veto(DemandVetoReason.DIR_UNREADABLE)
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)
    if records is None or not _all_admissible(records, fold_family_ids):
        return _veto(DemandVetoReason.BAD_FILE)
    return DemandScan(demands=tuple(records), venue_veto=False, veto_reason=None)


def _scan_refused(exc: SingleReadRefused) -> DemandScan:
    if exc.reason is SingleReadReason.NOT_FOUND:
        return DemandScan(demands=(), venue_veto=False, veto_reason=None)
    return _veto(DemandVetoReason.DIR_UNREADABLE)


def _all_admissible(records: list[DemandRecord], fold_family_ids: Collection[str]) -> bool:
    return all(r.family_id in fold_family_ids and r.reason in DEMAND_REASONS for r in records)


def _check_writable(record: DemandRecord, fold_family_ids: Collection[str], data: bytes) -> None:
    if record.reason not in DEMAND_REASONS:
        raise DemandRefused(DemandRefusalReason.UNKNOWN_REASON)
    if record.family_id not in fold_family_ids:
        raise DemandRefused(DemandRefusalReason.UNKNOWN_FAMILY)
    if len(data) > DEMAND_FILE_MAX_BYTES:
        raise DemandRefused(DemandRefusalReason.OVERSIZE)


def _standing(
    paths: AutonomyPaths | ShadowPaths, venue: str
) -> tuple[list[str], list[DemandRecord]]:
    """Make the venue directory; the names standing in it and the valid records among them.

    A file that is not a valid demand counts as a name but yields no record.
    """
    try:
        rootfd = open_root(paths.root)
        try:
            dirfd = walk_dirs(rootfd, (*_DEMAND_PARTS, venue), create=True)
        finally:
            os.close(rootfd)
    except SingleReadRefused as exc:
        raise DemandRefused(DemandRefusalReason.WRITE_FAILED, exc.reason.value) from exc
    try:
        names = _listing(dirfd)
        parsed = (_read_one(dirfd, name, venue) for name in names)
        return names, [record for record in parsed if record is not None]
    except OSError as exc:
        raise DemandRefused(DemandRefusalReason.DIRECTORY_UNREADABLE) from exc
    finally:
        os.close(dirfd)


def _write(
    paths: AutonomyPaths | ShadowPaths,
    record: DemandRecord,
    fold_family_ids: Collection[str],
    *,
    producer: bool,
) -> DemandWrite:
    data = _bytes_of(record)
    _check_writable(record, fold_family_ids, data)
    names, records = _standing(paths, record.venue)
    name = record.filename()
    if producer and name in names:
        return DemandWrite(DemandOutcome.ALREADY_PRESENT, name)
    if any(r.family_id == record.family_id and r.reason == record.reason for r in records):
        return DemandWrite(DemandOutcome.SLOT_OCCUPIED, name)
    if producer and record.reason != INTEGRITY_REASON:
        if len(names) >= DEMAND_FILES_MAX - DEMAND_INTEGRITY_RESERVED:
            raise DemandRefused(DemandRefusalReason.PRODUCER_CAP)
    elif len(names) >= DEMAND_FILES_MAX:
        raise DemandRefused(DemandRefusalReason.SLOTS_FULL)
    try:
        outcome = write_once(
            paths.demand_dir(record.venue) / name, data, root=paths.root, mode=DEMAND_FILE_MODE
        )
    except SingleReadRefused as exc:
        raise DemandRefused(DemandRefusalReason.WRITE_FAILED, exc.reason.value) from exc
    if outcome is WriteOutcome.EXISTS_EQUAL:
        return DemandWrite(DemandOutcome.ALREADY_PRESENT, name)
    return DemandWrite(DemandOutcome.WRITTEN, name)


def write_engine_demand(
    paths: AutonomyPaths | ShadowPaths,
    record: DemandRecord,
    *,
    fold_family_ids: Collection[str],
) -> DemandWrite:
    """Write the engine's demand for ``record`` (``writer == "engine"``); see the module rules."""
    if record.writer != ENGINE_WRITER:
        raise DemandRefused(DemandRefusalReason.NOT_ENGINE_WRITER)
    return _write(paths, record, fold_family_ids, producer=False)


def write_producer_demand(
    paths: AutonomyPaths | ShadowPaths,
    record: DemandRecord,
    *,
    fold_family_ids: Collection[str],
) -> DemandWrite:
    """Write a producer's demand; ``record.writer`` must be in ``DEMAND_WRITER_PRODUCER_IDS``."""
    if record.writer not in DEMAND_WRITER_PRODUCER_IDS:
        raise DemandRefused(DemandRefusalReason.UNLISTED_PRODUCER)
    return _write(paths, record, fold_family_ids, producer=True)
