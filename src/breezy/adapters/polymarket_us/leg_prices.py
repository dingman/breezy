"""YES/NO leg price translation and the venue's side/intent echo table.

Lives OUTSIDE ``exec/`` deliberately: X3's AST control
(``tests/unit/test_execution_egress_firewall_guard.py``) bans complement
arithmetic (``1 - x``) anywhere under
``src/breezy/adapters/polymarket_us/exec/``, and this module's whole job is
that one line of arithmetic, applied correctly, exactly once.

Authority: ``docs/plans/NO_SIDE_S5_EXEC_2026-09-14.md`` Rev 5/5a/5b (E5-1,
E5-2, E5-6) and the venue API reference snapshot
(``docs_snapshots/api-reference_orders_create-order_2026-08-25.md:139-158``):
*"The `price.value` field always represents the long side's price, regardless
of which order intent you use... To trade the NO side at any price X, set
`price.value = 1.00 - X`."* Corroborated live 2026-09-14
(``docs/evidence/venue/polymarket_us/NO_SIDE_PREVIEW_20260914T170654Z.json``,
``..._170750Z.json``): a NO-outcome order echoes ``intent:
ORDER_INTENT_BUY_SHORT``, ``side: ORDER_SIDE_SELL`` -- a NO buy is executed as
a SELL of the YES side.

``leg`` here is always :func:`breezy.adapters.polymarket_us.symbology.leg_of`'s
return value (``"yes"`` or ``"no"``), never a free-text outcome string.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Literal

Leg = Literal["yes", "no"]

_ZERO: Final[Decimal] = Decimal(0)
_ONE: Final[Decimal] = Decimal(1)

#: The venue's own values, declared here (L-37: declare, don't hardcode
#: inline at the call site) so a single table backs both the wire-price
#: translation and the echo cross-check. Breezy never shorts (``allow_short
#: =False``): every order Breezy sends is a BUY of one leg or the other, and
#: the venue's OWN classification of that BUY differs by leg.
VENUE_SIDE_FOR_LEG: Final[dict[Leg, str]] = {
    "yes": "ORDER_SIDE_BUY",
    "no": "ORDER_SIDE_SELL",
}
VENUE_INTENT_FOR_LEG: Final[dict[Leg, str]] = {
    "yes": "ORDER_INTENT_BUY_LONG",
    "no": "ORDER_INTENT_BUY_SHORT",
}


def _assert_finite_unit_price(value: Decimal, *, label: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{label} {value!r} is not finite; refusing to translate it")
    if value < _ZERO or value > _ONE:
        raise ValueError(f"{label} {value!r} is outside [0, 1]; refusing to translate it")


def wire_price_for_leg(leg: Leg, instrument_price: Decimal) -> Decimal:
    """The value Breezy must send on the wire for a BUY at ``instrument_price``.

    Identity for the YES leg (the wire has always meant the YES/long price).
    ``1 - instrument_price`` for the NO leg: to buy the NO outcome at price
    X, the wire's ``price.value`` must carry the complement, because the
    venue always prices the long (YES) side (see module docstring).
    """
    if not isinstance(instrument_price, Decimal):
        # ValueError, not TypeError (noqa: TRY004): every refusal in this
        # module is ValueError, deliberately, so a caller catches ONE type.
        raise ValueError(  # noqa: TRY004
            f"instrument_price must be a Decimal, got {type(instrument_price).__name__}"
        )
    _assert_finite_unit_price(instrument_price, label="instrument_price")
    if leg == "yes":
        return instrument_price
    if leg == "no":
        return _ONE - instrument_price
    raise ValueError(f"unknown leg {leg!r}; expected 'yes' or 'no'")


def instrument_price_for_leg(leg: Leg, wire_price: Decimal) -> Decimal:
    """The inverse of :func:`wire_price_for_leg`: recover the NO-instrument
    price Breezy should book from a wire value the venue sent (``price``,
    ``avgPx``, ``lastPx``) on a NO-leg order.

    An exact involution with :func:`wire_price_for_leg` on the NO leg:
    ``instrument_price_for_leg("no", wire_price_for_leg("no", x)) == x``.
    """
    if not isinstance(wire_price, Decimal):
        # ValueError, not TypeError (noqa: TRY004): see wire_price_for_leg.
        raise ValueError(  # noqa: TRY004
            f"wire_price must be a Decimal, got {type(wire_price).__name__}"
        )
    _assert_finite_unit_price(wire_price, label="wire_price")
    if leg == "yes":
        return wire_price
    if leg == "no":
        return _ONE - wire_price
    raise ValueError(f"unknown leg {leg!r}; expected 'yes' or 'no'")


#: The venue's CLOSING-order values (INC-E1 X3 ruling,
#: ``docs/evidence/RULING_x3_sell_long_sell_short_2026-09-16.md``): a YES
#: close is a SELL of the long leg; a NO close is the exact MIRROR of a NO
#: BUY (side ``ORDER_SIDE_BUY``, not ``SELL``), even though the request
#: itself carries ``action: ORDER_ACTION_SELL``. Both intents carry the
#: X3-banned ``SELL_`` substring, which is why this classifier lives here,
#: outside ``exec/``, exactly like :data:`VENUE_SIDE_FOR_LEG` above.
#:
#: PINNED-BY-CAPTURE 2026-09-16T03:19:31Z/T03:19:32Z
#: (``docs/evidence/venue/polymarket_us/CLOSE_PREVIEW_yes_20260916T031931Z.json``,
#: ``..._no_20260916T031932Z.json``): live ``/v1/order/preview`` responses,
#: superseding the Appendix A PINNED-PENDING-CAPTURE documentation guess for
#: the NO leg -- the capture wins per the INC-E2 rule. YES close: request
#: ``outcomeSide YES + ORDER_ACTION_SELL @0.01`` echoes exactly
#: ``(ORDER_SIDE_SELL, ORDER_INTENT_SELL_LONG)`` -- matches the prior
#: documentation guess. NO close: request ``outcomeSide NO + ORDER_ACTION_
#: SELL`` at instrument price 0.01 (wire 0.99) echoes ``(ORDER_SIDE_BUY,
#: ORDER_INTENT_SELL_SHORT)`` -- NOT ``ORDER_SIDE_SELL`` as previously
#: documented. If a future capture disagrees again, THAT capture wins and
#: this table is corrected again, never widened to accept both.
EXIT_VENUE_SIDE_FOR_LEG: Final[dict[Leg, str]] = {
    "yes": "ORDER_SIDE_SELL",
    "no": "ORDER_SIDE_BUY",
}
EXIT_VENUE_INTENT_FOR_LEG: Final[dict[Leg, str]] = {
    "yes": "ORDER_INTENT_SELL_LONG",
    "no": "ORDER_INTENT_SELL_SHORT",
}


def assert_echo_matches_leg(leg: Leg, side: object, intent: object) -> None:
    """Refuse if the venue's ``side``/``intent`` echo disagrees with ``leg``.

    A NO-leg order whose echo is not exactly ``(ORDER_SIDE_SELL,
    ORDER_INTENT_BUY_SHORT)``, or a YES-leg order whose echo is not exactly
    ``(ORDER_SIDE_BUY, ORDER_INTENT_BUY_LONG)``, is refused in BOTH
    directions (E5-2) -- never silently forwarded to Nautilus as a SELL, and
    never silently accepted on a value the venue never declared for this leg.
    """
    if leg not in VENUE_SIDE_FOR_LEG:
        raise ValueError(f"unknown leg {leg!r}; expected 'yes' or 'no'")
    expected_side = VENUE_SIDE_FOR_LEG[leg]
    expected_intent = VENUE_INTENT_FOR_LEG[leg]
    if side != expected_side or intent != expected_intent:
        raise ValueError(
            f"leg {leg!r} expects venue echo (side={expected_side!r}, "
            f"intent={expected_intent!r}) but observed (side={side!r}, "
            f"intent={intent!r}); refusing to attribute this report to a leg "
            "the venue did not declare"
        )


def exit_wire_price_for_leg(leg: Leg, instrument_price: Decimal) -> Decimal:
    """The value Breezy must send on the wire to CLOSE at ``instrument_price``.

    The venue always prices the long (YES) side regardless of BUY/SELL
    intent (Appendix A row 3 of ``POSITION_EXIT_EXECUTION_2026-09-16.md``):
    closing a NO holding at X is sent as ``1 - X``, the IDENTICAL complement
    a NO BUY uses. This is therefore a documented alias of
    :func:`wire_price_for_leg`, not a second implementation -- a closing
    order's call site never has to re-derive whether "the wire price" means
    an open or a close.
    """
    return wire_price_for_leg(leg, instrument_price)


def assert_exit_echo_matches_leg(leg: Leg, side: object, intent: object) -> None:
    """Refuse if the venue's CLOSING-order echo disagrees with ``leg``.

    Sibling of :func:`assert_echo_matches_leg` for a closing order, over the
    disjoint :data:`EXIT_VENUE_SIDE_FOR_LEG`/:data:`EXIT_VENUE_INTENT_FOR_LEG`
    table (PINNED-BY-CAPTURE, module docstring above): a YES close must echo
    exactly ``(ORDER_SIDE_SELL, ORDER_INTENT_SELL_LONG)``; a NO close must
    echo exactly ``(ORDER_SIDE_BUY, ORDER_INTENT_SELL_SHORT)`` -- the exact
    mirror of a NO buy's own echo. Because the NO-close side (``BUY``) is
    the SAME value the YES-buy table uses, this check keys on the full
    (side, intent) PAIR, never side alone: a NO close accidentally
    presented as a YES buy differs by intent (``SELL_SHORT`` vs
    ``BUY_LONG``) and is refused. Refused in BOTH directions (E5-2's rule,
    carried over): a BUY-table echo presented here refuses, and an
    exit-table echo presented to :func:`assert_echo_matches_leg` refuses
    there -- the two tables never accept each other's pair.
    """
    if leg not in EXIT_VENUE_SIDE_FOR_LEG:
        raise ValueError(f"unknown leg {leg!r}; expected 'yes' or 'no'")
    expected_side = EXIT_VENUE_SIDE_FOR_LEG[leg]
    expected_intent = EXIT_VENUE_INTENT_FOR_LEG[leg]
    if side != expected_side or intent != expected_intent:
        raise ValueError(
            f"leg {leg!r} exit expects venue echo (side={expected_side!r}, "
            f"intent={expected_intent!r}) but observed (side={side!r}, "
            f"intent={intent!r}); refusing to attribute this report to a "
            "closing order the venue did not declare"
        )


__all__ = [
    "EXIT_VENUE_INTENT_FOR_LEG",
    "EXIT_VENUE_SIDE_FOR_LEG",
    "VENUE_INTENT_FOR_LEG",
    "VENUE_SIDE_FOR_LEG",
    "Leg",
    "assert_echo_matches_leg",
    "assert_exit_echo_matches_leg",
    "exit_wire_price_for_leg",
    "instrument_price_for_leg",
    "wire_price_for_leg",
]
