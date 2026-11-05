"""The registry high-water mark (ARCH-0 AC 16; A5-R2 monotone write decision).

The HWM is one exec-store value per venue, ``autonomy/registry_hwm/<venue>``. It records the chain
position and export counter the node last verified, so a chain rewound to a shorter or rewritten
history is refused. Reading is tri-state: ``HwmAbsent`` (the key does not exist), ``HwmPresent`` or
``HwmUnreadable``. Absent on a non-empty chain refuses (``hwm_absent``); it is never a pass.

This module is pure: no I/O, no clock, no store. ``write_monotone_decision`` is the decision part of
the sole writer API ``hwm.write_monotone`` that AUT-5a adds on a ``HwmKeyStore`` Protocol. The
write path never lowers either sequence; the reset CLI is the only bypass.

Wire form (``Hwm.to_wire``): the four keys ``venue``, ``venue_seq``, ``chain_head`` and
``export_seq``, as canonical JSON, with no ``schema`` key (so no ``ACCEPTED_SCHEMAS`` entry).
``hwm_reading_from_bytes`` is the only decoder, and ``HwmAbsent`` is built only in this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.chain import VerifiedVenueChain
from breezy.persistence.autonomy.schemas import VENUE_RE, RefusalReason
from breezy.persistence.autonomy.wire import (
    WireRefusalReason,
    WireRefused,
    check_int,
    check_match,
    check_sha256,
    parse_json_exact,
    require_exact_keys,
    require_int,
    require_str,
)

__all__ = [
    "REGISTRY_HWM_KEY_PREFIX",
    "Hwm",
    "HwmAbsent",
    "HwmPresent",
    "HwmReading",
    "HwmUnreadable",
    "HwmWriteDecision",
    "hwm_check",
    "hwm_key",
    "hwm_reading_from_bytes",
    "next_hwm",
    "write_monotone_decision",
]

REGISTRY_HWM_KEY_PREFIX: Final = "autonomy/registry_hwm/"


@dataclass(frozen=True, slots=True, kw_only=True)
class Hwm:
    """The last verified position: ``venue_seq`` rows, their head hash, and the export counter."""

    venue: str
    venue_seq: int
    chain_head: str
    export_seq: int

    def __post_init__(self) -> None:
        check_match(self.venue, VENUE_RE, "venue")
        check_int(self.venue_seq, "venue_seq", minimum=1)
        check_sha256(self.chain_head, "chain_head")
        check_int(self.export_seq, "export_seq")

    def to_wire(self) -> dict[str, object]:
        return {
            "venue": self.venue,
            "venue_seq": self.venue_seq,
            "chain_head": self.chain_head,
            "export_seq": self.export_seq,
        }

    def to_bytes(self) -> bytes:
        return canonical_json(self.to_wire())

    @classmethod
    def from_wire(cls, obj: Mapping[str, object]) -> Self:
        require_exact_keys(obj, required=("venue", "venue_seq", "chain_head", "export_seq"))
        return cls(
            venue=require_str(obj, "venue"),
            venue_seq=require_int(obj, "venue_seq"),
            chain_head=require_str(obj, "chain_head"),
            export_seq=require_int(obj, "export_seq"),
        )


@dataclass(frozen=True, slots=True)
class HwmAbsent:
    """The key does not exist. Built only in this module (AST-banned elsewhere)."""


@dataclass(frozen=True, slots=True)
class HwmPresent:
    hwm: Hwm


@dataclass(frozen=True, slots=True)
class HwmUnreadable:
    #: A closed code (a ``WireRefusalReason`` value); never the payload.
    detail: str


HwmReading = HwmAbsent | HwmPresent | HwmUnreadable


def hwm_key(venue: str) -> str:
    """The exec-store key of ``venue``'s HWM."""
    return f"{REGISTRY_HWM_KEY_PREFIX}{check_match(venue, VENUE_RE, 'venue')}"


def hwm_reading_from_bytes(raw: bytes | None) -> HwmReading:
    """The only decoder: ``None`` is Absent, anything that does not parse exactly is Unreadable."""
    if raw is None:
        return HwmAbsent()
    if not isinstance(raw, bytes):
        return HwmUnreadable(WireRefusalReason.WRONG_TYPE.value)
    try:
        return HwmPresent(Hwm.from_wire(parse_json_exact(raw)))
    except WireRefused as exc:
        return HwmUnreadable(exc.reason.value)


def hwm_check(
    chain: VerifiedVenueChain, reading: HwmReading, *, newest_export_seq: int
) -> RefusalReason | None:
    """The refusal ``reading`` earns against the verified ``chain``, or ``None`` (AC 16 rules 1-6).

    ``newest_export_seq`` is ``0`` when there is no export file.
    """
    if isinstance(reading, HwmAbsent):
        return RefusalReason.HWM_ABSENT if chain.rows else None
    if not isinstance(reading, HwmPresent):  # HwmUnreadable and any unknown type
        return RefusalReason.HWM_UNREADABLE
    hwm = reading.hwm
    if hwm.venue != chain.venue or hwm.venue_seq < 1:
        return RefusalReason.HWM_UNREADABLE
    if hwm.venue_seq > chain.head_venue_seq:
        return RefusalReason.HWM_REGRESSED
    if chain.rows[hwm.venue_seq - 1].transition_hash != hwm.chain_head:
        return RefusalReason.HWM_REGRESSED
    if hwm.export_seq > newest_export_seq:
        return RefusalReason.HWM_REGRESSED
    return None


def next_hwm(chain: VerifiedVenueChain, *, export_seq: int) -> Hwm:
    """The HWM that marks ``chain``'s head and the verified ``export_seq`` (refused when empty)."""
    return Hwm(
        venue=chain.venue,
        venue_seq=chain.head_venue_seq,
        chain_head=chain.head_hash,
        export_seq=export_seq,
    )


class HwmWriteDecision(StrEnum):
    """What a monotone writer does with a candidate HWM (not a refusal reason)."""

    WRITE = "WRITE"
    SKIP = "SKIP"
    REFUSE = "REFUSE"


def write_monotone_decision(current: HwmReading, new: Hwm) -> HwmWriteDecision:
    """The pure decision behind ``hwm.write_monotone`` (A5-R2); a writer never lowers a sequence.

    In order: Absent writes; Unreadable or an unknown reading refuses; a foreign venue refuses; the
    same ``venue_seq`` with another head refuses; both sequences at least the stored ones write
    (or skip when identical); both at most the stored ones skip (a stale writer); a mix refuses.
    """
    if not isinstance(new, Hwm):
        return HwmWriteDecision.REFUSE
    if isinstance(current, HwmAbsent):
        return HwmWriteDecision.WRITE
    if not isinstance(current, HwmPresent):
        return HwmWriteDecision.REFUSE
    stored = current.hwm
    if new.venue != stored.venue:
        return HwmWriteDecision.REFUSE
    if new.venue_seq == stored.venue_seq and new.chain_head != stored.chain_head:
        return HwmWriteDecision.REFUSE
    if new.venue_seq >= stored.venue_seq and new.export_seq >= stored.export_seq:
        return HwmWriteDecision.SKIP if new == stored else HwmWriteDecision.WRITE
    if new.venue_seq <= stored.venue_seq and new.export_seq <= stored.export_seq:
        return HwmWriteDecision.SKIP
    return HwmWriteDecision.REFUSE
