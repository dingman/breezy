"""Rung net-position entry guard (ARCH-0 AC 22; ARCH C5 W6).

The guard reads durable fills through an injected :class:`FillReader` and never imports an
adapter or ``breezy.domain``; the exec client's key and side vocabulary are pinned by
``tests/unit/test_entry_guard.py`` (read by AST). It fails closed: every unreadable state is
``UNREADABLE`` and maps to the same veto as ``HELD``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal, Protocol

from breezy.persistence.autonomy.net_position import LegFill, net_signed_qty
from breezy.persistence.autonomy.veto import VetoReason

__all__ = [
    "NO_LEG_SYMBOL_SUFFIX",
    "FillIndexAbsent",
    "FillReader",
    "FillRow",
    "GuardResult",
    "guard_veto_reason",
    "leg_instrument_ids",
    "rung_has_net_position",
]

#: The composite NO-leg symbol suffix (``<slug>^no``), restated so this module never imports
#: ``breezy.domain``. ``test_leg_suffix_equals_instrument_leg`` pins it to the domain constants.
NO_LEG_SYMBOL_SUFFIX: Final[str] = "^no"
_INSTRUMENT_SEPARATOR: Final[str] = "^"
_VENUE_DELIMITER: Final[str] = "."


class GuardResult(StrEnum):
    HELD = "held"
    FLAT = "flat"
    UNREADABLE = "unreadable"


class FillIndexAbsent(Exception):
    """The instrument has no fill-index key: it has never filled. Not an unreadable index."""


@dataclass(frozen=True)
class FillRow:
    """One durable fill record, reduced to what netting needs."""

    order_side: Literal["BUY", "SELL"]
    cumulative_qty: Decimal
    ts_event_ns: int


class FillReader(Protocol):
    """Exact-key read access to the exec store's durable fills; no scan."""

    def open_intent_blocks(self) -> bool:
        """True while an unresolved order intent makes the fills untrustworthy (venue-global)."""
        ...

    def fill_index(self, instrument_id: str) -> tuple[str, ...]:
        """The venue order ids indexed under ``instrument_id``; raises ``FillIndexAbsent``."""
        ...

    def fill_record(self, venue_order_id: str) -> FillRow:
        """The durable fill record for ``venue_order_id``."""
        ...


def leg_instrument_ids(base_slug: str, *, venue_suffix: str) -> tuple[str, str]:
    """The ``(yes_id, no_id)`` fill-index instrument ids of ``base_slug`` on one venue.

    ``venue_suffix`` includes its leading dot (``".POLYMARKET_US"``). A slug that is empty or
    already carries a venue or leg separator is refused with ``ValueError``.
    """
    if not base_slug or _VENUE_DELIMITER in base_slug or _INSTRUMENT_SEPARATOR in base_slug:
        raise ValueError(f"not a base slug: {base_slug!r}")
    return (
        f"{base_slug}{venue_suffix}",
        f"{base_slug}{NO_LEG_SYMBOL_SUFFIX}{venue_suffix}",
    )


def _leg_fills(reader: FillReader, leg: Literal["yes", "no"], instrument_id: str) -> list[LegFill]:
    try:
        order_ids = reader.fill_index(instrument_id)
    except FillIndexAbsent:
        return []
    if not order_ids:
        raise ValueError(f"fill index for {instrument_id!r} exists but is empty")
    fills: list[LegFill] = []
    for order_id in order_ids:
        row = reader.fill_record(order_id)
        fills.append(LegFill(leg, row.order_side, row.cumulative_qty, row.ts_event_ns))
    return fills


def rung_has_net_position(base_slug: str, *, reader: FillReader, venue_suffix: str) -> GuardResult:
    """Whether ``base_slug`` carries a non-zero net position across its YES and NO legs.

    ``open_intent_blocks()`` is consulted first and its scope is venue-global: an unresolved
    intent anywhere on the venue makes every rung ``UNREADABLE``. An absent index counts as no
    fills; an existing but empty index, a bad slug, an unknown side or any exception is
    ``UNREADABLE``. A non-zero net is ``HELD``.
    """
    try:
        if reader.open_intent_blocks():
            return GuardResult.UNREADABLE
        yes_id, no_id = leg_instrument_ids(base_slug, venue_suffix=venue_suffix)
        fills = _leg_fills(reader, "yes", yes_id) + _leg_fills(reader, "no", no_id)
        return GuardResult.HELD if net_signed_qty(fills) != 0 else GuardResult.FLAT
    except Exception:  # noqa: BLE001 - fail closed: any failure to read is UNREADABLE
        return GuardResult.UNREADABLE


def guard_veto_reason(result: GuardResult) -> VetoReason | None:
    """``rung_net_position_held`` for HELD and UNREADABLE, ``None`` for FLAT."""
    if result is GuardResult.FLAT:
        return None
    return VetoReason.RUNG_NET_POSITION_HELD
