"""AMBIG-LATCH-RESUME Phase B: pure attribution of venue activity to a no-id submit.

A create-order POST whose outcome is AMBIGUOUS and whose response carried no
venue order id leaves nothing to join on: the venue issues no client order id.
The faithful equivalent is an attribution join on the venue's ECHO of our own
wire body (market slug, side, action, price, quantity 1, IOC, AUTOMATIC) inside
a time window around the take. This module classifies the account's TRADE rows
and open orders against that echo and returns one verdict. Authority:
``docs/plans/backlog/BACKLOG_PLANS_2026-10-03/AMBIG-LATCH-RESUME_plan_r6.md``
section 2.8.5.

PURE. This module does no I/O, has no ``await`` and imports only
``dataclasses``, ``decimal``, ``enum``, ``typing``, ``collections.abc`` and the
one RFC3339 parser alias from ``account_activity``. It lives OUTSIDE ``exec/``,
so the NO-SEND scanners never read its body; the purity is enforced by
``tests/unit/test_no_id_attribution_purity.py`` (AST) instead. It must stay free
of ``from __future__ import annotations`` for the same reason: the pin is the
exact import set.

Verdicts are a closed vocabulary: ``ADOPT(order_id)``, ``NO_FILL``,
``CONTRADICTION(token)`` and ``INCOMPLETE(token)``. Precedence is
CONTRADICTION, then INCOMPLETE, then the rest.
"""

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final, Literal

from breezy.adapters.polymarket_us.account_activity import parse_rfc3339_ns

TRADE_TYPE: Final[str] = "ACTIVITY_TYPE_TRADE"
IOC_TIF: Final[str] = "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
MANUAL_INDICATOR: Final[str] = "MANUAL_ORDER_INDICATOR_MANUAL"


class VerdictKind(StrEnum):
    """Verdict kinds (a ``str`` enum, so ``kind == "ADOPT"`` holds)."""

    ADOPT = "ADOPT"
    NO_FILL = "NO_FILL"
    CONTRADICTION = "CONTRADICTION"
    INCOMPLETE = "INCOMPLETE"


ADOPT: Final = VerdictKind.ADOPT
NO_FILL: Final = VerdictKind.NO_FILL
CONTRADICTION: Final = VerdictKind.CONTRADICTION
INCOMPLETE: Final = VerdictKind.INCOMPLETE

#: Closed token sets.
TOKEN_MULTIPLE_CANDIDATES: Final[str] = "multiple_candidates"
TOKEN_UNATTRIBUTED: Final[str] = "unattributed_automated_trade_in_window"
TOKEN_IN_WINDOW_OPEN_ORDER: Final[str] = "in_window_open_order"
TOKEN_LEG_AFTER_WINDOW: Final[str] = "leg_after_attribution_window"
TOKEN_ACTIVITIES_INCOMPLETE: Final[str] = "activities_incomplete"
TOKEN_ACTIVITIES_OUT_OF_ORDER: Final[str] = "activities_out_of_order"
TOKEN_OPEN_ORDERS_READ: Final[str] = "open_orders_read"

#: The signed venue-net effect of a MANUAL aggressor fill, keyed by
#: ``(outcomeSide, action, intent)``. Only observed shapes are declared (L-37):
#: the venue nets a NO holding as short YES, so a NO buy LOWERS the slug's net.
MANUAL_SIGN_TABLE: Final[tuple[tuple[tuple[str, str, str], int], ...]] = (
    (("OUTCOME_SIDE_YES", "ORDER_ACTION_BUY", "ORDER_INTENT_BUY_LONG"), 1),
    (("OUTCOME_SIDE_YES", "ORDER_ACTION_SELL", "ORDER_INTENT_SELL_LONG"), -1),
    (("OUTCOME_SIDE_NO", "ORDER_ACTION_BUY", "ORDER_INTENT_BUY_SHORT"), -1),
)

_ONE: Final[Decimal] = Decimal(1)


@dataclass(frozen=True, slots=True)
class NoIdEcho:
    """The wire fields the venue echoes on its own order objects."""

    slug: str
    outcome_side: str
    action: str
    price: str


@dataclass(frozen=True, slots=True)
class NoIdLeg:
    """One TRADE row's aggressor leg, as read from the venue."""

    order_id: str
    market_slug: str
    outcome_side: str
    action: str
    price: Decimal | None
    quantity: Decimal | None
    tif: str
    manual: bool
    trade_create_ns: int
    intent: str | None
    fill_qty: Decimal | None


@dataclass(frozen=True, slots=True)
class NoIdLegScan:
    legs: tuple[NoIdLeg, ...]
    passive_manual: tuple[bool, ...]
    uninterpretable_rows: int
    out_of_order: bool
    passed_window_start: bool
    last_row_ts_ns: int | None


@dataclass(frozen=True, slots=True)
class NoIdVerdict:
    kind: VerdictKind
    token: str | None = None
    order_id: str | None = None


@dataclass(frozen=True, slots=True)
class ManualNet:
    value: Decimal | None
    status: Literal["ok", "unsettled", "unreconcilable"]
    reason: str | None = None
    count: int = 0


def _decimal_or_none(raw: object) -> Decimal | None:
    if isinstance(raw, bool) or not isinstance(raw, str | int | float):
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _strict_fill_qty(raw: object) -> Decimal | None:
    if isinstance(raw, bool) or not isinstance(raw, str | int):
        return None
    return _decimal_or_none(raw)


def _order_object(
    trade: Mapping[str, Any], key: str, execution_key: str
) -> Mapping[str, Any] | None:
    direct = trade.get(key)
    if isinstance(direct, Mapping):
        return direct
    execution = trade.get(execution_key)
    if isinstance(execution, Mapping):
        nested = execution.get("order")
        if isinstance(nested, Mapping):
            return nested
    return None


def _text(obj: Mapping[str, Any], key: str) -> str | None:
    value = obj.get(key)
    return value if isinstance(value, str) and value else None


def _price_value(obj: Mapping[str, Any]) -> Decimal | None:
    price = obj.get("price")
    if not isinstance(price, Mapping):
        return None
    return _decimal_or_none(price.get("value"))


def _leg_from_trade(trade: Mapping[str, Any], ts_ns: int) -> tuple[NoIdLeg, bool] | None:
    """The aggressor leg and the passive leg's MANUAL flag, or ``None`` when a
    required field is missing or not a string (the row is uninterpretable)."""
    aggressor = _order_object(trade, "aggressor", "aggressorExecution")
    passive = _order_object(trade, "passive", "passiveExecution")
    if aggressor is None or passive is None:
        return None
    order_id = _text(aggressor, "id")
    slug = _text(aggressor, "marketSlug")
    outcome_side = _text(aggressor, "outcomeSide")
    action = _text(aggressor, "action")
    tif = _text(aggressor, "tif")
    indicator = _text(aggressor, "manualOrderIndicator")
    passive_indicator = _text(passive, "manualOrderIndicator")
    if None in (order_id, slug, outcome_side, action, tif, indicator, passive_indicator):
        return None
    quantity = aggressor.get("quantity")
    intent = aggressor.get("intent")
    leg = NoIdLeg(
        order_id=str(order_id),
        market_slug=str(slug),
        outcome_side=str(outcome_side),
        action=str(action),
        price=_price_value(aggressor),
        quantity=_decimal_or_none(quantity),
        tif=str(tif),
        manual=indicator == MANUAL_INDICATOR,
        trade_create_ns=ts_ns,
        intent=intent if isinstance(intent, str) and intent else None,
        fill_qty=_strict_fill_qty(trade.get("qtyDecimal")),
    )
    return leg, passive_indicator == MANUAL_INDICATOR


def no_id_aggressor_legs(
    page: Mapping[str, Any], window_start_ns: int, prev_row_ts_ns: int | None
) -> NoIdLegScan:
    """Every aggressor leg at or after ``window_start_ns`` on one activities page.

    Ordering is checked on TRADE rows only and is NON-INCREASING (ties are legal:
    the tracked capture has one). ``prev_row_ts_ns`` is the last TRADE row time of
    the previous page, so the check spans page boundaries.
    """
    activities = page.get("activities")
    if not isinstance(activities, list):
        return NoIdLegScan((), (), 1, False, False, prev_row_ts_ns)
    legs: list[NoIdLeg] = []
    passive_flags: list[bool] = []
    uninterpretable = 0
    out_of_order = False
    passed = False
    previous = prev_row_ts_ns
    for activity in activities:
        if not isinstance(activity, Mapping):
            uninterpretable += 1
            continue
        kind = activity.get("type")
        if kind != TRADE_TYPE:
            if "trade" in activity or not isinstance(kind, str):
                uninterpretable += 1
            continue
        trade = activity.get("trade")
        if not isinstance(trade, Mapping):
            uninterpretable += 1
            continue
        try:
            ts_ns = parse_rfc3339_ns(trade.get("createTime"))
        except (ValueError, TypeError):
            uninterpretable += 1
            continue
        if previous is not None and ts_ns > previous:
            out_of_order = True
        previous = ts_ns
        if ts_ns < window_start_ns:
            passed = True
            continue
        parsed = _leg_from_trade(trade, ts_ns)
        if parsed is None:
            uninterpretable += 1
            continue
        legs.append(parsed[0])
        passive_flags.append(parsed[1])
    return NoIdLegScan(
        tuple(legs), tuple(passive_flags), uninterpretable, out_of_order, passed, previous
    )


def _echo_price(echo: NoIdEcho) -> Decimal | None:
    return _decimal_or_none(echo.price)


def _matches_echo(leg: NoIdLeg, echo: NoIdEcho) -> bool:
    price = _echo_price(echo)
    return (
        price is not None
        and leg.market_slug == echo.slug
        and leg.outcome_side == echo.outcome_side
        and leg.action == echo.action
        and leg.price is not None
        and leg.price == price
        and leg.quantity is not None
        and leg.quantity == _ONE
        and leg.tif == IOC_TIF
        and not leg.manual
    )


def _open_order_verdict(
    open_orders: Sequence[Any],
    known_order_ids: AbstractSet[str],
    echo: NoIdEcho | None,
    window_start_ns: int,
    window_end_ns: int,
) -> tuple[bool, bool]:
    """``(contradiction, unreadable)`` over the open orders."""
    contradiction = False
    unreadable = False
    price = _echo_price(echo) if echo is not None else None
    for order in open_orders:
        if order.venue_order_id in known_order_ids:
            continue
        try:
            created = parse_rfc3339_ns(order.create_time)
        except (ValueError, TypeError):
            unreadable = True
            continue
        if not window_start_ns <= created <= window_end_ns:
            continue
        echo_match = (
            echo is not None
            and order.market_slug == echo.slug
            and price is not None
            and order.price is not None
            and order.price == price
        )
        if order.tif == IOC_TIF or echo_match:
            contradiction = True
    return contradiction, unreadable


def classify_no_id_evidence(
    *,
    legs: Sequence[NoIdLeg],
    passive_manual: Sequence[bool],
    legs_complete: bool,
    out_of_order: bool,
    open_orders: Sequence[Any],
    open_orders_ok: bool,
    known_order_ids: AbstractSet[str],
    echo: NoIdEcho | None,
    window_start_ns: int,
    window_end_ns: int,
) -> NoIdVerdict:
    """One verdict for a no-id submit; see the module docstring for precedence."""
    if out_of_order:
        # An ordering violation makes every leg read untrustworthy: the feed
        # is not the one the early-termination soundness argument assumes.
        return NoIdVerdict(INCOMPLETE, TOKEN_ACTIVITIES_OUT_OF_ORDER)
    candidates: list[str] = []
    unattributed = False
    late = False
    for leg, passive_is_manual in zip(legs, passive_manual, strict=True):
        if leg.order_id in known_order_ids:
            continue
        after_window = leg.trade_create_ns > window_end_ns
        if echo is not None and not after_window and _matches_echo(leg, echo):
            if leg.order_id not in candidates:
                candidates.append(leg.order_id)
            continue
        if leg.manual or passive_is_manual:
            continue
        if after_window:
            late = True
        else:
            unattributed = True
    open_contradiction = False
    open_unreadable = False
    if open_orders_ok:
        open_contradiction, open_unreadable = _open_order_verdict(
            open_orders, known_order_ids, echo, window_start_ns, window_end_ns
        )
    if unattributed:
        return NoIdVerdict(CONTRADICTION, TOKEN_UNATTRIBUTED)
    if late:
        return NoIdVerdict(CONTRADICTION, TOKEN_LEG_AFTER_WINDOW)
    if open_contradiction:
        return NoIdVerdict(CONTRADICTION, TOKEN_IN_WINDOW_OPEN_ORDER)
    if len(candidates) > 1:
        return NoIdVerdict(CONTRADICTION, TOKEN_MULTIPLE_CANDIDATES)
    if not legs_complete:
        return NoIdVerdict(INCOMPLETE, TOKEN_ACTIVITIES_INCOMPLETE)
    if not open_orders_ok or open_unreadable:
        return NoIdVerdict(INCOMPLETE, TOKEN_OPEN_ORDERS_READ)
    if candidates:
        return NoIdVerdict(ADOPT, order_id=candidates[0])
    return NoIdVerdict(NO_FILL)


def holding_delta_consistent(
    *,
    base_venue_net: str,
    now_venue_net: str,
    base_durable_net: str,
    now_durable_net: Decimal,
    leg_sign: int,
    manual_net: Decimal = Decimal(0),
) -> bool | None:
    """Whether the FOREIGN holding moved by exactly the signed manual fills.

    The foreign holding is ``venue_net - leg_sign * durable_net``. ``leg_sign`` is
    +1 for YES and -1 for NO (the venue nets a NO holding as short YES). Returns
    ``None`` if any input is not a finite ``Decimal``.
    """
    base_venue = _decimal_or_none(base_venue_net)
    now_venue = _decimal_or_none(now_venue_net)
    base_durable = _decimal_or_none(base_durable_net)
    if (
        base_venue is None
        or now_venue is None
        or base_durable is None
        or not now_durable_net.is_finite()
        or not manual_net.is_finite()
    ):
        return None
    foreign_base = base_venue - leg_sign * base_durable
    foreign_now = now_venue - leg_sign * now_durable_net
    return foreign_now - foreign_base == manual_net


def manual_leg_net_effect(
    *,
    legs: Sequence[NoIdLeg],
    passive_manual: Sequence[bool],
    slug: str,
    after_ns: int,
    now_ns: int,
    settle_ns: int,
    straddle_ns: int,
) -> ManualNet:
    """Sum the signed venue-net effect of MANUAL aggressor legs on ``slug`` after
    ``after_ns`` (route (d)). Anything it cannot reconcile exactly is
    ``unreconcilable``; a leg too recent for positions to reflect is
    ``unsettled`` and retried at the next re-check."""
    signs = dict(MANUAL_SIGN_TABLE)
    total = Decimal(0)
    count = 0
    reason: str | None = None
    unsettled = False
    for leg, passive_is_manual in zip(legs, passive_manual, strict=True):
        if leg.market_slug != slug:
            continue
        if passive_is_manual and leg.trade_create_ns > after_ns:
            reason = reason or "manual_passive_leg"
        if not leg.manual:
            continue
        if abs(leg.trade_create_ns - after_ns) <= straddle_ns:
            reason = reason or "straddles_snapshot"
            continue
        if leg.trade_create_ns <= after_ns:
            continue
        if leg.intent is None or leg.fill_qty is None:
            reason = reason or "missing_field"
            continue
        sign = signs.get((leg.outcome_side, leg.action, leg.intent))
        if sign is None:
            reason = reason or "unknown_shape"
            continue
        total += sign * leg.fill_qty
        count += 1
        if leg.trade_create_ns > now_ns - settle_ns:
            unsettled = True
    if reason is not None:
        return ManualNet(None, "unreconcilable", reason, count)
    if unsettled:
        return ManualNet(None, "unsettled", None, count)
    return ManualNet(total, "ok", None, count)
