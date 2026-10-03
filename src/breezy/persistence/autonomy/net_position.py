"""Leg-signed netting of one rung's fills (ARCH-0 AC 22).

``LegFill`` is netting-only: it carries exactly what a sign needs and nothing about price,
fee or cost basis (AUT-2 owns ``CostedFill``). Each fill is signed in YES-equivalent units:
YES BUY +q, YES SELL -q, NO BUY -q, NO SELL +q. A NO holding is a short YES, so the two legs
net against each other. Any other leg or side is refused, never assigned a sign.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

__all__ = ["LegFill", "UnknownSide", "net_signed_qty"]

_SIGNS: Final[dict[tuple[str, str], Decimal]] = {
    ("yes", "BUY"): Decimal(1),
    ("yes", "SELL"): Decimal(-1),
    ("no", "BUY"): Decimal(-1),
    ("no", "SELL"): Decimal(1),
}


class UnknownSide(ValueError):
    """A fill's leg or side has no sign in the netting table."""


@dataclass(frozen=True)
class LegFill:
    """One fill's leg, side, quantity and event time. Netting-only: no price, fee or cost."""

    leg: Literal["yes", "no"]
    side: Literal["BUY", "SELL"]
    qty: Decimal
    ts_event_ns: int


def net_signed_qty(fills: Iterable[LegFill]) -> Decimal:
    """The YES-equivalent net quantity of ``fills``; ``UnknownSide`` for an unsigned leg or side."""
    net = Decimal(0)
    for fill in fills:
        sign = _SIGNS.get((fill.leg, fill.side))
        if sign is None:
            raise UnknownSide(f"no sign for leg={fill.leg!r} side={fill.side!r}")
        net += sign * fill.qty
    return net
