"""``journal/v1``: the write-once, hash-linked evidence journal (ARCH-0 AC 24).

``append_journal`` writes one ``evidence/journal/<venue>/<kind>/<seq:010d>.json`` envelope per
record, mode 0444 through ``single_read.write_once``. Each envelope names its predecessor by
``prev_sha256``, the sha256 of the predecessor's file bytes (``null`` for seq 1), so an edit,
removal or reordering of any entry other than the last breaks the link recorded after it. Verifying
the last entry against an external head (the export's ``evidence_journal_heads``) is the consumer's
step; this module returns ``JournalHead(seq, sha256)`` for it.

Kinds are bare names. ``JOURNAL_KINDS`` is empty at ARCH-0, so every kind is refused until its
owner registers it in a reviewed change. ``read_journal_chain`` returns the entries or
``JournalUnverified`` and never raises on a damaged chain. A missing journal directory is an empty
chain. Refusals carry closed codes, never paths.

Two contracts for consumers (A5b-R5). An empty chain compared with an external head is a
*mismatch*, never a pass (``head_matches``). Restrictive writes (DEMOTE, HALT, SWAP_CANCEL and their
demand files) are never gated on a journal append: a refused or failed append must not stop one.

This module imports no pyarrow-reaching module (``schemas`` imports it).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from breezy.persistence.autonomy.canonical import CanonicalTypeError, canonical_json, sha256_hex
from breezy.persistence.autonomy.paths import (
    SEQ_DIGITS,
    AutonomyPaths,
    ShadowPaths,
    journal_kind_component,
    seq_component,
    venue_component,
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
    check_sha256,
    optional_sha256,
    parse_json_exact,
    require_enum,
    require_exact_keys,
    require_int,
    require_ns,
    require_object,
    require_str,
)

__all__ = [
    "JOURNAL_KINDS",
    "MAX_JOURNAL_ENTRY_BYTES",
    "JournalEntry",
    "JournalHead",
    "JournalRefusalReason",
    "JournalRefused",
    "JournalUnverified",
    "JournalUnverifiedReason",
    "append_journal",
    "head_matches",
    "read_journal_chain",
]

JOURNAL_SCHEMA: Final = "journal/v1"
JOURNAL_FILE_MODE: Final = 0o444
#: A journal envelope is one small decision record; this bounds a read and a write.
MAX_JOURNAL_ENTRY_BYTES: Final = 65_536
#: Registered journal kinds (bare names). Empty at ARCH-0; an owner adds its own by review.
JOURNAL_KINDS: Final[frozenset[str]] = frozenset()
_JOURNAL_PARTS: Final = ("evidence", "journal")
_ENTRY_NAME_RE: Final = re.compile(rf"\A([0-9]{{{SEQ_DIGITS}}})\.json\Z", re.ASCII)
_TEMP_NAME_RE: Final = re.compile(r"\A\.tmp\.[0-9a-f]{16}\Z", re.ASCII)
_KEYS: Final = ("schema", "kind", "venue", "seq", "ts_ns", "prev_sha256", "record")


class JournalRefusalReason(StrEnum):
    UNKNOWN_KIND = "unknown_kind"
    OVERSIZE = "oversize"
    CHAIN_UNVERIFIED = "chain_unverified"
    SEQ_COLLISION = "seq_collision"
    WRITE_FAILED = "write_failed"


class JournalRefused(Exception):
    """An append was refused; ``reason`` is a closed code and ``detail`` never a path."""

    def __init__(self, reason: JournalRefusalReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


class JournalUnverifiedReason(StrEnum):
    UNKNOWN_KIND = "unknown_kind"
    DIRECTORY_UNREADABLE = "directory_unreadable"
    UNKNOWN_NAME = "unknown_name"
    SEQ_GAP = "seq_gap"
    ENTRY_UNREADABLE = "entry_unreadable"
    ENTRY_INVALID = "entry_invalid"
    ADDRESS_MISMATCH = "address_mismatch"
    LINK_BROKEN = "link_broken"


@dataclass(frozen=True)
class JournalUnverified:
    """The chain could not be verified; ``seq`` is the first entry at fault (``None``: none)."""

    reason: JournalUnverifiedReason
    seq: int | None


@dataclass(frozen=True)
class JournalHead:
    """The newest entry of a chain: its seq and the sha256 of its file bytes."""

    seq: int
    sha256: str


@dataclass(frozen=True, kw_only=True)
class JournalEntry:
    """One ``journal/v1`` envelope. ``record`` is plain JSON and must be treated as read-only."""

    kind: str
    venue: str
    seq: int
    ts_ns: int
    prev_sha256: str | None
    record: Mapping[str, object]

    def __post_init__(self) -> None:
        journal_kind_component(self.kind)
        venue_component(self.venue)
        seq_component(self.seq)
        check_int(self.ts_ns, "ts_ns")
        if self.prev_sha256 is not None:
            check_sha256(self.prev_sha256, "prev_sha256")
        if (self.prev_sha256 is None) is not (self.seq == 1):
            raise WireRefused(WireRefusalReason.BAD_VALUE, "prev_sha256")  # only seq 1 has none
        if not isinstance(self.record, Mapping):
            raise WireRefused(WireRefusalReason.WRONG_TYPE, "record")

    def to_wire(self) -> dict[str, object]:
        return {
            "schema": JOURNAL_SCHEMA,
            "kind": self.kind,
            "venue": self.venue,
            "seq": self.seq,
            "ts_ns": self.ts_ns,
            "prev_sha256": self.prev_sha256,
            "record": dict(self.record),
        }

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=_KEYS)
        require_enum(obj, "schema", allowed=(JOURNAL_SCHEMA,))
        return cls(
            kind=require_str(obj, "kind"),
            venue=require_str(obj, "venue"),
            seq=require_int(obj, "seq"),
            ts_ns=require_ns(obj, "ts_ns"),
            prev_sha256=optional_sha256(obj, "prev_sha256"),
            record=require_object(obj, "record"),
        )

    def file_bytes(self) -> bytes:
        return canonical_json(self.to_wire())

    @property
    def sha256(self) -> str:
        return sha256_hex(self.file_bytes())

    def head(self) -> JournalHead:
        return JournalHead(seq=self.seq, sha256=self.sha256)


def _plain_record(record: Mapping[str, object]) -> dict[str, object]:
    """``record`` as plain JSON values (Decimals become canonical strings); no float survives."""
    try:
        plain = json.loads(canonical_json(record))
    except CanonicalTypeError as exc:
        raise WireRefused(WireRefusalReason.BAD_VALUE, "record") from exc
    if not isinstance(plain, dict):
        raise WireRefused(WireRefusalReason.WRONG_TYPE, "record")
    return plain


def _entry_names(dirfd: int) -> list[tuple[int, str]] | JournalUnverified:
    """Sorted ``(seq, name)`` pairs; the one temp pattern of an interrupted write is ignored."""
    found: list[tuple[int, str]] = []
    for name in os.listdir(dirfd):
        if _TEMP_NAME_RE.fullmatch(name):
            continue
        matched = _ENTRY_NAME_RE.fullmatch(name)
        if matched is None or int(matched.group(1)) < 1:
            return JournalUnverified(JournalUnverifiedReason.UNKNOWN_NAME, None)
        found.append((int(matched.group(1)), name))
    return sorted(found)


def _verify_entries(
    dirfd: int, names: list[tuple[int, str]], kind: str, venue: str
) -> tuple[JournalEntry, ...] | JournalUnverified:
    entries: list[JournalEntry] = []
    prev_sha: str | None = None
    for expected, (seq, name) in enumerate(names, start=1):
        if seq != expected:
            return JournalUnverified(JournalUnverifiedReason.SEQ_GAP, seq)
        try:
            raw = read_once_at(
                dirfd, name, max_bytes=MAX_JOURNAL_ENTRY_BYTES, policy=ReadPolicy.STRICT
            )
        except (SingleReadRefused, OSError):
            return JournalUnverified(JournalUnverifiedReason.ENTRY_UNREADABLE, seq)
        try:
            entry = JournalEntry.from_wire(parse_json_exact(raw))
        except WireRefused:
            return JournalUnverified(JournalUnverifiedReason.ENTRY_INVALID, seq)
        if raw != entry.file_bytes():
            return JournalUnverified(JournalUnverifiedReason.ENTRY_INVALID, seq)
        if (entry.kind, entry.venue, entry.seq) != (kind, venue, seq):
            return JournalUnverified(JournalUnverifiedReason.ADDRESS_MISMATCH, seq)
        if entry.prev_sha256 != prev_sha:
            return JournalUnverified(JournalUnverifiedReason.LINK_BROKEN, seq)
        entries.append(entry)
        prev_sha = sha256_hex(raw)
    return tuple(entries)


def read_journal_chain(
    paths: AutonomyPaths | ShadowPaths, kind: str, venue: str
) -> tuple[JournalEntry, ...] | JournalUnverified:
    """Every entry of ``(venue, kind)`` in seq order, or why the chain cannot be trusted.

    Names are exactly ``<seq:010d>.json`` for seq 1..n without a gap; each entry must be a canonical
    ``journal/v1`` envelope addressed to this venue, kind and seq, and link to its predecessor's
    file bytes. A missing directory is the empty chain.
    """
    journal_kind_component(kind)
    venue_component(venue)
    if kind not in JOURNAL_KINDS:
        return JournalUnverified(JournalUnverifiedReason.UNKNOWN_KIND, None)
    try:
        rootfd = open_root(paths.root)
    except SingleReadRefused:
        return JournalUnverified(JournalUnverifiedReason.DIRECTORY_UNREADABLE, None)
    try:
        try:
            dirfd = walk_dirs(rootfd, (*_JOURNAL_PARTS, venue, kind), create=False)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return ()
            return JournalUnverified(JournalUnverifiedReason.DIRECTORY_UNREADABLE, None)
        try:
            names = _entry_names(dirfd)
            if isinstance(names, JournalUnverified):
                return names
            return _verify_entries(dirfd, names, kind, venue)
        except OSError:
            return JournalUnverified(JournalUnverifiedReason.DIRECTORY_UNREADABLE, None)
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)


def head_matches(chain: tuple[JournalEntry, ...] | JournalUnverified, head: JournalHead) -> bool:
    """True only for a verified, non-empty chain whose newest entry is exactly ``head``.

    An empty chain against an external head is a mismatch (the export names a head the journal
    lacks), and so is an unverified chain.
    """
    if isinstance(chain, JournalUnverified) or not chain:
        return False
    return chain[-1].head() == head


def _publish(paths: AutonomyPaths | ShadowPaths, entry: JournalEntry, data: bytes) -> WriteOutcome:
    path = paths.journal_file(entry.venue, entry.kind, entry.seq)
    try:
        rootfd = open_root(paths.root)
        try:
            os.close(walk_dirs(rootfd, path.parent.relative_to(paths.root).parts, create=True))
        finally:
            os.close(rootfd)
        return write_once(path, data, root=paths.root, mode=JOURNAL_FILE_MODE)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.EXISTS_DIFFERENT:
            raise JournalRefused(JournalRefusalReason.SEQ_COLLISION) from exc
        raise JournalRefused(JournalRefusalReason.WRITE_FAILED, exc.reason.value) from exc


def append_journal(
    paths: AutonomyPaths | ShadowPaths,
    kind: str,
    venue: str,
    record: Mapping[str, object],
    *,
    ts_ns: int,
) -> JournalHead:
    """Append ``record`` to the ``(venue, kind)`` chain and return the new head.

    Refused (``JournalRefused``): an unregistered kind, a chain that does not verify, an entry over
    ``MAX_JOURNAL_ENTRY_BYTES``, a seq another writer already took (``SEQ_COLLISION``; the stored
    entry is untouched), or a failed write. A bad kind, venue, ``ts_ns`` or a record with no
    canonical form raises ``WireRefused``. An identical concurrent append returns the existing head.
    """
    journal_kind_component(kind)
    venue_component(venue)
    check_int(ts_ns, "ts_ns")
    if kind not in JOURNAL_KINDS:
        raise JournalRefused(JournalRefusalReason.UNKNOWN_KIND)
    body = _plain_record(record)
    chain = read_journal_chain(paths, kind, venue)
    if isinstance(chain, JournalUnverified):
        raise JournalRefused(JournalRefusalReason.CHAIN_UNVERIFIED, chain.reason.value)
    entry = JournalEntry(
        kind=kind,
        venue=venue,
        seq=len(chain) + 1,
        ts_ns=ts_ns,
        prev_sha256=chain[-1].sha256 if chain else None,
        record=body,
    )
    data = entry.file_bytes()
    if len(data) > MAX_JOURNAL_ENTRY_BYTES:
        raise JournalRefused(JournalRefusalReason.OVERSIZE)
    _publish(paths, entry, data)
    return entry.head()
