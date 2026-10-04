"""The per-venue hash chain (ARCH-0 AC 11; ARCH C5 "Hash chain", Y20).

Each venue has its own chain. The genesis is ``sha256(b"registry/v1|" + venue)`` and
``transition_hash = sha256(canonical_row || prev_transition_hash)``. ``canonical_row`` hashes every
column except ``seq`` (a global order only) and the two hash columns, so ``venue`` and
``venue_seq`` are covered.

``verify_venue_chain`` raises ``ChainBroken`` (reason ``chain_broken``) unless ``venue_seq`` runs
contiguously from 1, every row is the one venue, ``ts_ns`` never decreases and every link hashes.
A verified chain is immutable; ``verify_extension`` returns a longer one. Pure: no I/O, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from breezy.persistence.autonomy.canonical import canonical_json, sha256_hex
from breezy.persistence.autonomy.schemas import (
    ExportTrailer,
    RefusalReason,
    TransitionRow,
    check_venue,
)

__all__ = [
    "GENESIS_PREFIX",
    "ChainBroken",
    "VerifiedVenueChain",
    "canonical_row",
    "genesis",
    "seq_is_verified_prefix",
    "transition_hash",
    "verify_against_export",
    "verify_extension",
    "verify_venue_chain",
]

GENESIS_PREFIX: Final = b"registry/v1|"
#: Columns the row hash never covers: the global order and the two hash columns themselves.
_UNHASHED: Final = frozenset({"seq", "prev_transition_hash", "transition_hash"})


class ChainBroken(Exception):
    """A chain failed verification; ``venue_seq`` is the first row at fault (``0``: none)."""

    def __init__(self, venue_seq: int = 0, detail: str = "") -> None:
        super().__init__(
            f"{RefusalReason.CHAIN_BROKEN.value}: venue_seq={venue_seq} {detail}".strip()
        )
        self.reason = RefusalReason.CHAIN_BROKEN
        self.venue_seq = venue_seq
        self.detail = detail


@dataclass(frozen=True, slots=True)
class VerifiedVenueChain:
    """Rows proven contiguous, single-venue, monotone and linked from the venue genesis."""

    venue: str
    rows: tuple[TransitionRow, ...]
    #: Hash the next row must name as ``prev_transition_hash`` (the genesis when empty).
    head_hash: str

    @property
    def head_venue_seq(self) -> int:
        return len(self.rows)


def genesis(venue: str) -> str:
    """The hex genesis hash of ``venue``'s chain."""
    return sha256_hex(GENESIS_PREFIX + check_venue(venue).encode("ascii"))


def canonical_row(row: TransitionRow) -> bytes:
    """Canonical bytes of every column except ``seq`` and the two hash columns."""
    wire = row.to_wire()
    return canonical_json({k: v for k, v in wire.items() if k not in _UNHASHED})


def transition_hash(row: TransitionRow, prev_transition_hash: str) -> str:
    """``sha256(canonical_row(row) || prev_transition_hash)`` as lowercase hex."""
    return sha256_hex(canonical_row(row) + prev_transition_hash.encode("ascii"))


def _walk(
    rows: Iterable[TransitionRow], venue: str, *, start_seq: int, prev_hash: str, prev_ts: int
) -> tuple[tuple[TransitionRow, ...], str]:
    out: list[TransitionRow] = []
    expected = start_seq
    for row in rows:
        if not isinstance(row, TransitionRow):
            raise ChainBroken(expected, "not a TransitionRow")
        if row.venue != venue:
            raise ChainBroken(expected, "foreign venue")
        if row.venue_seq != expected:
            raise ChainBroken(expected, "venue_seq not contiguous")
        if row.ts_ns < prev_ts:
            raise ChainBroken(expected, "ts_ns decreases")
        if row.prev_transition_hash != prev_hash:
            raise ChainBroken(expected, "prev link broken")
        if row.transition_hash is None or row.transition_hash != transition_hash(row, prev_hash):
            raise ChainBroken(expected, "row hash mismatch")
        out.append(row)
        prev_hash, prev_ts, expected = row.transition_hash, row.ts_ns, expected + 1
    return tuple(out), prev_hash


def verify_venue_chain(rows: Sequence[TransitionRow], venue: str) -> VerifiedVenueChain:
    """Verify ``rows`` as ``venue``'s whole chain from genesis; raise ``ChainBroken`` otherwise."""
    verified, head = _walk(rows, venue, start_seq=1, prev_hash=genesis(venue), prev_ts=0)
    return VerifiedVenueChain(venue=venue, rows=verified, head_hash=head)


def verify_extension(
    chain: VerifiedVenueChain, new_rows: Sequence[TransitionRow]
) -> VerifiedVenueChain:
    """``chain`` followed by ``new_rows``, each verified against the current head."""
    prev_ts = chain.rows[-1].ts_ns if chain.rows else 0
    added, head = _walk(
        new_rows,
        chain.venue,
        start_seq=chain.head_venue_seq + 1,
        prev_hash=chain.head_hash,
        prev_ts=prev_ts,
    )
    return VerifiedVenueChain(venue=chain.venue, rows=chain.rows + added, head_hash=head)


def seq_is_verified_prefix(chain: VerifiedVenueChain, venue_seq: int, chain_head: str) -> bool:
    """True when ``chain_head`` is the hash after exactly ``venue_seq`` rows (0 is the genesis)."""
    if venue_seq < 0 or venue_seq > chain.head_venue_seq:
        return False
    expected = genesis(chain.venue) if venue_seq == 0 else chain.rows[venue_seq - 1].transition_hash
    return expected == chain_head


def verify_against_export(
    chain: VerifiedVenueChain, trailer: ExportTrailer
) -> RefusalReason | None:
    """``export_prefix_mismatch`` unless the export's head is a prefix of the verified chain."""
    if trailer.venue != chain.venue:
        return RefusalReason.EXPORT_PREFIX_MISMATCH
    if not seq_is_verified_prefix(chain, trailer.venue_seq, trailer.chain_head):
        return RefusalReason.EXPORT_PREFIX_MISMATCH
    return None
