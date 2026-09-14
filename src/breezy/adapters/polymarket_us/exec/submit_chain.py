"""Pure helpers for the Polymarket.us submit path (R-7).

No I/O, no awaits, no network client. ``_submit_order`` is the one chokepoint;
this module classifies order shape, encodes the venue body, and classifies the
create-order response. X3 (see the firewall guard's banned-token set) admits
the outcome-side-NO constant per the ruling at
``docs/evidence/RULING_x3_no_outcome_token_2026-09-14.md``, while still
banning the naked-short vocabulary it replaced; ``_outcome_token`` maps a
NO order via ``leg_of(instrument.id)``, never by reading the free-text
outcome string.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Final, cast

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import AccountId, TradeId, VenueOrderId
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError, VenueTransportError
from breezy.adapters.polymarket_us.exec.reports import _key_tree, parse_fill_report
from breezy.adapters.polymarket_us.parsing import LEG_KEY, LEG_NO
from breezy.adapters.polymarket_us.symbology import leg_of
from breezy.adapters.polymarket_us.transport import VenueResponse

logger = logging.getLogger(__name__)

KIND_ACCEPT_FILL: Final[str] = "accept_fill"
KIND_ZERO_FILL: Final[str] = "zero_fill"
KIND_REJECT: Final[str] = "reject"
KIND_AMBIGUOUS: Final[str] = "ambiguous"

RETIRE_ACCEPT_FILL: Final[str] = "ACCEPTED_WITH_DURABLE_FILL"
RETIRE_ZERO_FILL: Final[str] = "ACCEPTED_ZERO_FILL_TERMINAL"
RETIRE_REJECT: Final[str] = "DEFINITIVE_REJECT"

SENDER_ABSENT_REASON: Final[str] = (
    "order sender is not injected; this client refuses to submit"
)
CANONICAL_UNVERIFIED_REASON: Final[str] = (
    "write canonical string is unverified; this client refuses to submit"
)
PERMIT_ABSENT_REASON: Final[str] = (
    "live-trading permit is absent or not a LiveTradingPermit; "
    "this client refuses to submit"
)
RECONCILE_NOT_RUN_REASON: Final[str] = (
    "submit-intent reconcile_at_startup has not run; this client refuses to submit"
)
LATCH_ARM_REFUSED_REASON: Final[str] = (
    "submit-intent latch refused to arm; this client refuses to submit"
)
#: SAFETY C1 (plan rev 6.1): the authoritative pre-spend re-check inside
#: ``_submit_order``, evaluated on the same event-loop thread as ``arm()``
#: with no ``await`` between them. A WAIT is not a refusal: it spends no
#: permit, releases no booking (none was authorized yet), and does not latch
#: ``_trading_refusals``. The strategy clears IN_FLIGHT for this station on
#: seeing this exact reason (see ``ContinuousRungHoldStrategy.on_order_denied``).
OPEN_INTENT_WAIT_REASON: Final[str] = (
    "submit intent is already OPEN for this account; wait for it to resolve"
)
STORE_RAISED_REASON: Final[str] = (
    "the durable store raised before the post; this client refuses to submit"
)
AMBIGUOUS_REASON: Final[str] = (
    "create-order outcome is AMBIGUOUS; latch stays open and the booking is held"
)

ZERO: Final[Decimal] = Decimal(0)
ONE: Final[Decimal] = Decimal(1)
OPEN_PRICE_EXCLUSIVE_LOW: Final[Decimal] = Decimal("0.00")
OPEN_PRICE_EXCLUSIVE_HIGH: Final[Decimal] = Decimal("1.00")

ORDER_BODY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "marketSlug",
        "type",
        "price",
        "quantity",
        "tif",
        "outcomeSide",
        "action",
        "manualOrderIndicator",
        "synchronousExecution",
        "maxBlockTime",
    }
)

_IOC_ZERO_FILL_TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {
        "ORDER_STATE_CANCELED",
        "ORDER_STATE_REJECTED",
        "ORDER_STATE_EXPIRED",
    }
)
_LATCH_ARM_REFUSAL_TYPES: Final[frozenset[str]] = frozenset(
    {
        "SubmitIntentLatched",
        "SubmitIntentInvalidFingerprint",
        "SubmitIntentLockNotHeld",
    }
)
_OUTCOME_SIDE_YES: Final[str] = "OUTCOME_SIDE_YES"
_OUTCOME_SIDE_NO: Final[str] = "OUTCOME_SIDE_NO"
_ORDER_ACTION_BUY: Final[str] = "ORDER_ACTION_BUY"
_ORDER_TYPE_LIMIT: Final[str] = "ORDER_TYPE_LIMIT"
_TIF_IOC: Final[str] = "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
_MANUAL_AUTOMATIC: Final[str] = "MANUAL_ORDER_INDICATOR_AUTOMATIC"
_MAX_BLOCK_TIME: Final[str] = "5"
_PRIVATE_API_VERSION: Final[str] = "v1"
_ORDER_RESOURCE: Final[str] = "order"


@dataclass(frozen=True, slots=True)
class FillGeneration:
    """Native arguments for ``generate_order_filled``, never a synthesised fill."""

    venue_order_id: VenueOrderId
    trade_id: TradeId
    last_qty: Quantity
    last_px: Price
    commission: Money
    commission_raw: str
    ts_event: int
    filled_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class CreateOrderOutcome:
    """One classified create-order response. Absence of a field is absence.

    ``cumulative_qty``/``cumulative_cost``/``cumulative_fee``/
    ``fee_reconciled`` are the I1a order-level totals (LIVE_FILL_SCORING_CHAIN
    plan, section "I1a"): populated on ``KIND_ACCEPT_FILL`` only, ``None``/
    ``False`` on every other kind.
    """

    kind: str
    reason: str
    retirement_name: str | None
    venue_order_id: str | None
    fill: FillGeneration | None
    filled_cost_usd: Decimal | None
    cumulative_qty: Decimal | None
    cumulative_cost: Decimal | None
    cumulative_fee: Decimal | None
    fee_reconciled: bool
    generate_submitted: bool
    #: Redacted, log-only summary of every classified outcome (never ``None``).
    #: Carries only shape and length -- status code, a coarse ``body_kind``,
    #: the ``google.rpc.Status`` code when present, and the raw body's byte
    #: length -- never the body content itself, so it is always safe to log
    #: even though the body may be adversarial or carry venue-side account
    #: details.
    detail: str | None = None
    #: The ``ExecutionReportMappingError`` message :func:`fill_generation`
    #: caught and swallowed to ``None``, when an ``executions``-present,
    #: 200-with-order-id body still ended up ``KIND_AMBIGUOUS`` because the
    #: nested order/execution shape did not map. ``None`` on every kind
    #: except that fallthrough. Names-only (the mapper's own message,
    #: including its full key tree per ``reports.py``'s ``_key_tree`` --
    #: never a value), so it is safe to log verbatim: it is what turns a
    #: fee-unreconciled, excluded-from-``n`` AMBIGUOUS into a diagnosable one
    #: instead of a silent ``return None``.
    fill_parse_error: str | None = None


def latched_refusal_reason(first_reason: str) -> str:
    return (
        "this client has latched a trading refusal and will not act on "
        f"venue state it could not attribute: {first_reason}"
    )


def missing_account_reason(venue: object) -> str:
    return (
        f"no AccountState is cached for {venue}, so every Nautilus "
        "risk cap is inert; refusing"
    )


def permit_is_missing(permit: object) -> bool:
    return type(permit).__name__ != "LiveTradingPermit"


def is_latch_arm_refusal(exc: BaseException) -> bool:
    return type(exc).__name__ in _LATCH_ARM_REFUSAL_TYPES


def is_cancelled(exc: BaseException) -> bool:
    return type(exc).__name__ == "CancelledError"


def is_transport_error(exc: BaseException) -> bool:
    return isinstance(exc, VenueTransportError)


def order_price_decimal(order: object) -> Decimal:
    price = getattr(order, "price", None)
    if price is None:
        raise ValueError("limit order carries no price")
    as_decimal = getattr(price, "as_decimal", None)
    if callable(as_decimal):
        return Decimal(str(as_decimal()))
    return Decimal(str(price))


def order_quantity_decimal(order: object) -> Decimal:
    quantity = getattr(order, "quantity", None)
    if quantity is None:
        raise ValueError("order carries no quantity")
    as_decimal = getattr(quantity, "as_decimal", None)
    if callable(as_decimal):
        return Decimal(str(as_decimal()))
    return Decimal(str(quantity))


def order_notional_usd(order: object) -> Decimal:
    return order_price_decimal(order) * order_quantity_decimal(order)


def intent_fingerprint(order: object) -> str:
    payload = "\n".join(
        (
            str(getattr(order, "instrument_id", "")),
            str(getattr(order, "side", "")),
            str(getattr(order, "quantity", "")),
            str(getattr(order, "price", "")),
            str(getattr(order, "time_in_force", "")),
            str(getattr(order, "client_order_id", "")),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def order_fingerprint_bytes(order: object) -> bytes:
    return bytes.fromhex(intent_fingerprint(order))


def _outcome_token(instrument: object) -> str | None:
    """Map ``instrument`` to its order-body ``outcomeSide`` value.

    Keyed on :func:`leg_of` (the composite ``InstrumentId``), NEVER on the
    free-text ``outcome`` string -- the parse the parent plan forbids
    (``parsing.py:1211-1221``). ``info[LEG_KEY]`` is a cross-check that must
    agree; disagreement is a refusal (``ValueError``), never a fallback.
    Returns ``None`` only when the instrument carries no resolvable id.
    """
    instrument_id = getattr(instrument, "id", None)
    if instrument_id is None:
        return None
    id_leg = leg_of(instrument_id)
    info = getattr(instrument, "info", None)
    info_leg = info.get(LEG_KEY) if isinstance(info, Mapping) else None
    if info_leg is not None and info_leg != id_leg:
        raise ValueError(
            f"instrument id leg {id_leg!r} contradicts info[{LEG_KEY!r}]={info_leg!r}; refusing"
        )
    return _OUTCOME_SIDE_NO if id_leg == LEG_NO else _OUTCOME_SIDE_YES


def unmappable_order_reason(order: object, instrument: object) -> str | None:
    """Return a denial reason when the order cannot be mapped, else None."""
    if instrument is None or not isinstance(instrument, BinaryOption):
        return "instrument is not a BinaryOption; refusing"
    slug = str(getattr(instrument, "raw_symbol", "") or "")
    if not slug.strip():
        return "instrument has no resolvable market slug; refusing"
    if getattr(order, "order_type", None) is not OrderType.LIMIT:
        return "only a LIMIT order is mappable; refusing"
    if getattr(order, "time_in_force", None) is not TimeInForce.IOC:
        return "only an IOC order is mappable; refusing"
    if getattr(order, "side", None) is not OrderSide.BUY:
        return "only a BUY is mappable (a SELL is a naked short); refusing"
    try:
        quantity = order_quantity_decimal(order)
        price = order_price_decimal(order)
    except (TypeError, ValueError, InvalidOperation):
        return "order price or quantity is unreadable; refusing"
    if quantity != ONE:
        return "only a 1-contract order is mappable; refusing"
    if price <= OPEN_PRICE_EXCLUSIVE_LOW or price >= OPEN_PRICE_EXCLUSIVE_HIGH:
        return "price must be strictly inside (0.00, 1.00); refusing"
    if getattr(order, "is_post_only", False):
        return "post-only is not mappable; refusing"
    if getattr(order, "is_reduce_only", False):
        return "reduce-only is not mappable; refusing"
    display_qty = getattr(order, "display_qty", None)
    if display_qty is not None:
        return "display_qty is not mappable; refusing"
    expire_time = getattr(order, "expire_time", None)
    if expire_time is not None:
        return "expire_time is not mappable; refusing"
    has_trigger = getattr(order, "has_trigger_price", False)
    if has_trigger is True or (callable(has_trigger) and has_trigger()):
        return "trigger_price is not mappable; refusing"
    try:
        outcome_side = _outcome_token(instrument)
    except ValueError as exc:
        return str(exc)
    if outcome_side is None:
        return "no order-body outcome side is derivable from the instrument; refusing"
    return None


def build_order_body(order: object, instrument: object) -> dict[str, Any]:
    """Return the exact CreateOrderRequest key set. Caller has already mapped."""
    reason = unmappable_order_reason(order, instrument)
    if reason is not None:
        raise ValueError(reason)
    price = order_price_decimal(order)
    slug = str(getattr(instrument, "raw_symbol", "") or "")
    outcome_side = _outcome_token(instrument)
    if outcome_side is None:
        raise ValueError("no order-body outcome side is derivable from the instrument; refusing")
    return {
        "marketSlug": slug,
        "type": _ORDER_TYPE_LIMIT,
        "price": {"value": f"{price:.2f}", "currency": "USD"},
        "quantity": 1,
        "tif": _TIF_IOC,
        "outcomeSide": outcome_side,
        "action": _ORDER_ACTION_BUY,
        "manualOrderIndicator": _MANUAL_AUTOMATIC,
        "synchronousExecution": True,
        "maxBlockTime": _MAX_BLOCK_TIME,
    }


def encode_order_body(body: Mapping[str, Any]) -> bytes:
    if set(body) != ORDER_BODY_KEYS:
        raise ValueError("order body key set does not match the venue schema")
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def order_by_id_path(order_id: str) -> str:
    """Templated by-id path so V2 does not see the order resource as one literal."""
    return f"/{_PRIVATE_API_VERSION}/{_ORDER_RESOURCE}/{order_id}"


def _parse_json_object(body: bytes) -> dict[str, Any] | None:
    """Decode ``body`` as a JSON object, or ``None`` if it cannot be read.

    SP-2 I2b (AR-N1): a body whose nesting exhausts the parser is
    ``unparseable`` like any other unreadable body -- refused, never
    accepted, and never allowed to escape ``_submit_order``
    (``client.py:2748`` is not inside a ``try``).
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _is_google_rpc_status(payload: Mapping[str, Any]) -> bool:
    code = payload.get("code")
    message = payload.get("message")
    details = payload.get("details")
    return isinstance(code, int) and isinstance(message, str) and isinstance(details, list)


def _amount_decimal(value: object) -> Decimal | None:
    if isinstance(value, Mapping):
        raw = value.get("value")
    else:
        raw = value
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _response_order_id(payload: Mapping[str, Any]) -> str | None:
    top = payload.get("id")
    if isinstance(top, str) and top:
        return top
    order = payload.get("order")
    if isinstance(order, Mapping):
        nested = order.get("id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _terminal_state(payload: Mapping[str, Any]) -> str | None:
    for key in ("state", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    order = payload.get("order")
    if isinstance(order, Mapping):
        for key in ("state", "status"):
            value = order.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _cum_quantity(payload: Mapping[str, Any]) -> Decimal | None:
    raw = payload.get("cumQuantity")
    if raw is None:
        order = payload.get("order")
        if isinstance(order, Mapping):
            raw = order.get("cumQuantity")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _durable_execution(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """First fill-type execution carrying a durable order id, price, size and
    trade id.

    Filtered through :func:`_fill_type_executions` (I1a's own fee filter) so a
    CANCELED/REJECTED/EXPIRED/NEW/REPLACE/DONE_FOR_DAY row -- or one with no
    ``type`` at all -- is never selected even when it happens to carry stale
    ``lastPx``/``lastShares``/``tradeId`` values ahead of the real fill row.
    """
    for item in _fill_type_executions(payload):
        order = item.get("order")
        if not isinstance(order, Mapping):
            continue
        order_id = order.get("id")
        if not isinstance(order_id, str) or not order_id:
            continue
        if item.get("lastPx") is None:
            continue
        if item.get("lastShares") is None:
            continue
        trade_id = item.get("tradeId")
        if not isinstance(trade_id, str) or not trade_id:
            continue
        return item
    return None


def _filled_cost_from_execution(execution: Mapping[str, Any]) -> Decimal | None:
    order = execution.get("order")
    if isinstance(order, Mapping):
        avg = _amount_decimal(order.get("avgPx"))
        cum = order.get("cumQuantity")
        if avg is not None and cum is not None:
            try:
                return avg * Decimal(str(cum))
            except (InvalidOperation, ValueError, TypeError):
                pass
    last_px = _amount_decimal(execution.get("lastPx"))
    last_shares = execution.get("lastShares")
    if last_px is None or last_shares is None:
        return None
    try:
        return last_px * Decimal(str(last_shares))
    except (InvalidOperation, ValueError, TypeError):
        return None


#: I1a fee filter (``types/orders.py:34-43``). ``Execution`` is ``total=False``
#: (``:95-108``), so a row carrying no ``type`` at all is never fill-type.
_FILL_EXECUTION_TYPES: Final[frozenset[str]] = frozenset(
    {"EXECUTION_TYPE_FILL", "EXECUTION_TYPE_PARTIAL_FILL"}
)


def _fill_type_executions(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Every ``executions`` row whose ``type`` is a fill, in payload order.

    A CANCELED/REJECTED/EXPIRED/NEW/REPLACE/DONE_FOR_DAY row -- or one with no
    ``type`` at all -- is excluded here, so its commission is never summed.

    I6 (CRITICAL): ``type`` is a bare venue-controlled JSON value, so it may
    be a dict or list -- ``x in <frozenset>`` raises ``TypeError: unhashable
    type`` on either, uncaught, escaping ``classify_create_order_outcome``
    and ``_submit_order`` with no refusal and no log (the L-37/AR-N1 class
    I2b exists to close). ``isinstance(..., str)`` is checked FIRST, short-
    circuiting the membership test before it ever sees an unhashable value:
    a non-string ``type`` is simply not a fill-type row, exactly like a
    string that is not one of the two fill types.
    """
    executions = payload.get("executions")
    if not isinstance(executions, list):
        return ()
    return tuple(
        item
        for item in executions
        if isinstance(item, Mapping)
        and isinstance((execution_type := item.get("type")), str)
        and execution_type in _FILL_EXECUTION_TYPES
    )


def _sum_last_shares(executions: tuple[Mapping[str, Any], ...]) -> Decimal | None:
    total = ZERO
    for item in executions:
        raw = item.get("lastShares")
        if raw is None:
            return None
        try:
            total += Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None
    return total


def _sum_fill_commission(executions: tuple[Mapping[str, Any], ...]) -> Decimal | None:
    total = ZERO
    for item in executions:
        amount = _amount_decimal(item.get("commissionNotionalCollected"))
        if amount is None:
            return None
        total += amount
    return total


def _cumulative_qty_and_cost(
    execution: Mapping[str, Any],
) -> tuple[Decimal | None, Decimal | None]:
    """Qty and cost sourced TOGETHER, from the order snapshot on ``execution``,
    or together from this one execution's leg -- never mixed (I1a).

    Deliberately NOT a composition of ``_cum_quantity`` and
    ``_filled_cost_from_execution``: those two succeed independently (one
    could resolve order-level while the other falls back to the leg), which
    would pair a whole-order quantity with a one-leg cost or the reverse --
    exactly the defect I1a forbids. This atomically checks both preconditions
    before choosing the order-level source.
    """
    order = execution.get("order")
    if isinstance(order, Mapping):
        avg = _amount_decimal(order.get("avgPx"))
        raw_cum = order.get("cumQuantity")
        if avg is not None and raw_cum is not None:
            try:
                cum = Decimal(str(raw_cum))
            except (InvalidOperation, ValueError):
                cum = None
            if cum is not None:
                return cum, avg * cum
    last_px = _amount_decimal(execution.get("lastPx"))
    last_shares = execution.get("lastShares")
    if last_px is not None and last_shares is not None:
        try:
            qty = Decimal(str(last_shares))
        except (InvalidOperation, ValueError):
            return None, None
        return qty, last_px * qty
    return None, None


def _order_total_commission(execution: Mapping[str, Any]) -> Decimal | None:
    order = execution.get("order")
    if isinstance(order, Mapping):
        return _amount_decimal(order.get("commissionNotionalTotalCollected"))
    return None


def _bankers_cent(value: Decimal) -> Decimal | None:
    """Venue fee quantum: banker's rounding to $0.01. Two exact ``==`` only."""
    try:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        return None


def _amount_raw_string(amount: object) -> str | None:
    """The venue's original Amount.value string, or ``None`` if absent."""
    if isinstance(amount, Mapping):
        raw = amount.get("value")
    else:
        raw = amount
    if raw is None:
        return None
    return raw if isinstance(raw, str) else str(raw)


def _per_leg_commission_raw(item: Mapping[str, Any]) -> str:
    collected = item.get("commissionNotionalCollected")
    if isinstance(collected, Mapping):
        raw_value = collected.get("value")
    else:
        raw_value = collected
    return str(raw_value)


def _commission_raw_audit(
    execution: Mapping[str, Any],
    *,
    payload: Mapping[str, Any] | None = None,
) -> str:
    """Order-level total raw when present, else joined per-leg raws."""
    order = execution.get("order")
    if isinstance(order, Mapping):
        total_raw = _amount_raw_string(order.get("commissionNotionalTotalCollected"))
        if total_raw is not None:
            return total_raw
    if payload is not None:
        fill_type = _fill_type_executions(payload)
        if fill_type:
            return "+".join(_per_leg_commission_raw(item) for item in fill_type)
    return _per_leg_commission_raw(execution)


def _cumulative_fee_and_reconciliation(
    payload: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    cumulative_qty: Decimal | None,
) -> tuple[Decimal | None, bool]:
    """I1a fee + ``fee_reconciled``.

    ``fee_reconciled`` = (sum of fill-type ``lastShares`` == ``cumulative_qty``)
    AND (order total absent, OR order total == the per-leg fill-type sum,
    OR order total == bankers_cent(per-leg sum)). Two exact ``==``
    equalities; the set is widened, never relaxed to a tolerance. The
    quantity identity alone catches a dropped leg (the sum falls short of
    ``cumulative_qty``), so the absent-total branch needs no extra condition.
    ``cumulative_fee`` is the unrounded per-leg sum when reconciled on the
    exact or absent-total branch. On the bankers branch the cash paid IS
    the order-level total (what the venue billed); the exact legs live on
    the raw audit string.
    """
    fill_type = _fill_type_executions(payload)
    leg_qty = _sum_last_shares(fill_type)
    leg_fee = _sum_fill_commission(fill_type)
    qty_reconciled = (
        cumulative_qty is not None and leg_qty is not None and leg_qty == cumulative_qty
    )
    order_total = _order_total_commission(execution)
    if order_total is not None:
        exact_match = leg_fee is not None and order_total == leg_fee
        rounded_leg = _bankers_cent(leg_fee) if leg_fee is not None else None
        bankers_match = (
            not exact_match
            and rounded_leg is not None
            and order_total == rounded_leg
        )
        fee_reconciled = qty_reconciled and (exact_match or bankers_match)
        if fee_reconciled and exact_match:
            branch = "exact"
        elif fee_reconciled and bankers_match:
            branch = "bankers"
        else:
            branch = "none"
        logger.info("i1a fee_reconciled=%s branch=%s", fee_reconciled, branch)
        if fee_reconciled and bankers_match:
            return order_total, True
        if fee_reconciled:
            return leg_fee, True
        return order_total, False
    return leg_fee, qty_reconciled and leg_fee is not None


#: Single cap point (SP-2 I1/I2, Rev 2's value, measured-backed RV2.1-A8):
#: every diagnostic string this module builds for the create path -- the
#: underivable-cost message, a mapping-refusal message, the body key-tree
#: token -- is capped ONCE, at birth, through :func:`_capped_diagnostic` /
#: :func:`_detail_tree_token`. Downstream consumers (the classified log
#: line, the AMBIGUOUS tail, the durable store) all inherit the same bound
#: and never re-truncate (S-L1).
_DETAIL_TREE_MAX_CHARS: Final[int] = 2048

#: Closed-set per-field tokens for :func:`_underivable_cost_message` -- the
#: vocabulary already used by :func:`_state_detail_token` /
#: :func:`_cum_detail_token` in this file. Absent and unparseable are
#: different drift stories and neither ever echoes the value itself.
_TOKEN_ABSENT: Final[str] = "absent"
_TOKEN_PRESENT: Final[str] = "present"
_TOKEN_UNPARSEABLE: Final[str] = "unparseable"

#: `_safe_key_tree`'s fallback when `_key_tree` itself raises -- belt and
#: braces for SP-2's own two call sites in this module; the depth bound in
#: `reports._key_tree` is what actually protects against unbounded
#: recursion (AR-N2), not this fallback.
_TREE_UNAVAILABLE: Final[str] = "<tree unavailable: nesting exceeded>"


def _capped_diagnostic(text: str) -> str:
    """Cap ONE diagnostic string at ``_DETAIL_TREE_MAX_CHARS``, at birth.

    The truncation marker is emitted OUTSIDE the capped span (RV3-A13,
    mirroring ``reports._safe_key_name``'s own placement rule): a string
    within the cap is returned byte-identical, unchanged.
    """
    if len(text) <= _DETAIL_TREE_MAX_CHARS:
        return text
    return f"{text[:_DETAIL_TREE_MAX_CHARS]} (truncated from {len(text)} characters)"


def _safe_key_tree(payload: Mapping[str, Any]) -> str:
    """``reports._key_tree``, contained for this module's two call sites.

    ``reports._key_tree`` already bounds its own recursion depth (SP-2 I0);
    this is belt-and-braces, not the sole containment point (AR-N2) --
    tested by perturbing ``_key_tree`` to raise, never by pretending the
    bound itself fails.
    """
    try:
        return _key_tree(payload)
    except RecursionError:
        return _TREE_UNAVAILABLE


def _amount_token(value: object) -> str:
    """Closed-set token for an ``Amount``-shaped candidate cost field.

    Mirrors :func:`_amount_decimal`'s own parsing exactly, so the token
    always agrees with whatever that function would have derived --
    ``absent`` (no value), ``unparseable`` (present but not a valid
    decimal), or ``present`` (usable). Never the value itself.
    """
    if value is None:
        return _TOKEN_ABSENT
    if _amount_decimal(value) is None:
        return _TOKEN_UNPARSEABLE
    return _TOKEN_PRESENT


def _quantity_token(value: object) -> str:
    """Closed-set token for a bare-quantity candidate cost field.

    Mirrors :func:`_filled_cost_from_execution`'s own ``Decimal(str(value))``
    parsing of ``lastShares`` / ``cumQuantity`` -- these are plain numeric
    strings, not ``Amount``-wrapped, so :func:`_amount_token` does not apply.
    """
    if value is None:
        return _TOKEN_ABSENT
    try:
        Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _TOKEN_UNPARSEABLE
    return _TOKEN_PRESENT


def _underivable_cost_message(execution: Mapping[str, Any]) -> str:
    """Names-only diagnostic for ``_filled_cost_from_execution`` returning
    ``None``: a closed-set token for each of the four candidate fields it
    reads, plus the execution's own sanitised key tree (SP-2 I0) so a
    drifted shape is visible at once -- never a value.

    T1: this branch is UNREACHABLE in life today. ``parse_fill_report``'s
    own amount parsing (``parsing._to_decimal`` / ``_parse_amount``) is
    strictly stronger than this function's, so any leg that fails cost
    derivation fails MAPPING first and never reaches here -- see
    ``test_a_leg_that_maps_cleanly_always_yields_a_derivable_filled_cost``.
    Loud, not deleted, in case that coupling ever breaks (L-37 (2)).
    """
    order = execution.get("order")
    order_avg_px = order.get("avgPx") if isinstance(order, Mapping) else None
    order_cum_quantity = order.get("cumQuantity") if isinstance(order, Mapping) else None
    return (
        "fill report mapped but no filled cost is derivable: "
        f"order.avgPx={_amount_token(order_avg_px)} "
        f"order.cumQuantity={_quantity_token(order_cum_quantity)} "
        f"lastPx={_amount_token(execution.get('lastPx'))} "
        f"lastShares={_quantity_token(execution.get('lastShares'))}; "
        f"full body key tree: {{{_safe_key_tree(execution)}}}"
    )


def fill_generation(
    execution: Mapping[str, Any],
    *,
    instrument: object,
    account_id: object,
    ts_init: int,
    payload: Mapping[str, Any] | None = None,
    errors: list[str] | None = None,
) -> FillGeneration | None:
    """Map ``execution`` to native fill-generation arguments, or ``None``.

    ``errors``, when supplied, receives the caught exception's own ``str()``
    on a parse refusal -- UNCHANGED behaviour otherwise: this still returns
    ``None``, never raises, on a mapping failure. The message is names-only
    (``reports.py``'s ``ExecutionReportMappingError`` -- including the full
    key tree its own diagnostic appends -- never a value), so a caller may
    log it verbatim. Optional, and defaulted to ``None``, so every existing
    caller that does not pass it keeps recording nothing, exactly as before.

    SP-2 I1: the sink also receives a names-only message when the mapped
    execution's filled cost cannot be DERIVED (previously a silent
    ``None`` return, no trace of why -- L-37 (2)). Every message the sink
    receives is capped with an explicit, placement-ruled marker
    (:func:`_capped_diagnostic`), so ``fill_parse_error`` is bounded for
    both the log line and the durable store (SP-2 I3).
    """
    try:
        report = parse_fill_report(
            dict(execution),
            instrument=cast(Instrument, instrument),
            account_id=cast(AccountId, account_id),
            report_id=UUID4(),
            ts_init=ts_init,
        )
    except (ExecutionReportMappingError, TypeError, ValueError) as exc:
        if errors is not None:
            errors.append(_capped_diagnostic(str(exc)))
        return None
    filled_cost = _filled_cost_from_execution(execution)
    if filled_cost is None:
        if errors is not None:
            errors.append(_capped_diagnostic(_underivable_cost_message(execution)))
        return None
    return FillGeneration(
        venue_order_id=report.venue_order_id,
        trade_id=report.trade_id,
        last_qty=report.last_qty,
        last_px=report.last_px,
        commission=report.commission,
        commission_raw=_commission_raw_audit(execution, payload=payload),
        ts_event=int(report.ts_event),
        filled_cost_usd=filled_cost,
    )


def venue_order_id(order_id: str) -> VenueOrderId:
    return VenueOrderId(order_id)


#: Detail for the ``response is None`` AMBIGUOUS case: there is no HTTP
#: response at all, so every field is the "none" sentinel.
_AMBIGUOUS_DETAIL_NO_RESPONSE: Final[str] = (
    "status=none body_kind=none rpc_code=none body_len=0"
)
_ORDER_STATE_TOKEN: Final[re.Pattern[str]] = re.compile(r"^ORDER_STATE_[A-Z_]+$")


def _state_detail_token(payload: Mapping[str, Any] | None) -> str:
    """Closed-set ``state=`` token for the redacted create-order detail.

    Uses the same top-level ``state``/``status`` then nested ``order`` lookup
    as :func:`_terminal_state`. Emits the enum value only when it is a
    ``str`` matching ``ORDER_STATE_[A-Z_]+``; any other present string is
    ``other`` (never echoed); absence is ``absent``.
    """
    if not isinstance(payload, Mapping):
        return "absent"
    raw = _terminal_state(payload)
    if raw is None:
        return "absent"
    if _ORDER_STATE_TOKEN.fullmatch(raw) is not None:
        return raw
    return "other"


def _cum_detail_token(payload: Mapping[str, Any] | None) -> str:
    """Closed-set ``cum=`` token for the redacted create-order detail.

    Looks up ``cumQuantity`` top-level then nested ``order``, matching
    :func:`_cum_quantity`. Emits ``absent``, ``0``, ``nonzero``, or
    ``unparseable`` -- never the raw value.
    """
    if not isinstance(payload, Mapping):
        return "absent"
    raw = payload.get("cumQuantity")
    if raw is None:
        order = payload.get("order")
        if isinstance(order, Mapping):
            raw = order.get("cumQuantity")
    if raw is None:
        return "absent"
    try:
        qty = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return "unparseable"
    if qty == ZERO:
        return "0"
    return "nonzero"


def _detail_tree_token(payload: Mapping[str, Any]) -> str:
    """The ``executions-present``-only `` tree={...}`` suffix for
    :func:`_body_detail`, capped at ``_DETAIL_TREE_MAX_CHARS`` (SP-2 I2).

    Names-only, per :func:`_safe_key_tree` -- the tree is an OPEN set of
    NAMES (sanitised per SP-2 I0), never a value. The truncation marker is
    emitted OUTSIDE the closing brace (RV3-A13): a tree this long already
    contains its own per-key truncation markers (from
    ``reports._safe_key_name``), so the 2048-char slice can land mid-key,
    producing a SECOND, equally authentic truncation immediately before
    this one -- both are outside the structure they truncate, and neither
    is forged (AM-6).
    """
    tree = _safe_key_tree(payload)
    if len(tree) <= _DETAIL_TREE_MAX_CHARS:
        return f" tree={{{tree}}}"
    return f" tree={{{tree[:_DETAIL_TREE_MAX_CHARS]}}} (truncated from {len(tree)} characters)"


def _body_detail(
    response: VenueResponse,
    payload: Mapping[str, Any] | None,
    order_id: str | None,
) -> str:
    """Redacted, log-only summary of one classified create-order response.

    Reports shape and length only -- never the body content -- so the venue's
    answer is recoverable from the log without risking a leaked secret or
    account detail embedded in an adversarial or malformed body. Closed-set
    tokens only: status, body_kind, rpc_code, body_len, state, cum -- plus
    (SP-2 I2) an OPEN set of sanitised NAMES, never a value, in the ``tree=``
    suffix that appears ONLY on ``executions-present`` (so a SUCCESSFUL fill
    is captured too, not only an ambiguous one -- T3).
    """
    body_len = len(response.body)
    rpc_code: int | None = None
    tree_token = ""
    if payload is None:
        body_kind = "unparseable"
    elif isinstance(payload, Mapping) and _is_google_rpc_status(payload) and order_id is None:
        body_kind = "status-no-order-id"
        code = payload.get("code")
        rpc_code = code if isinstance(code, int) else None
    elif isinstance(payload, Mapping):
        executions = payload.get("executions")
        if isinstance(executions, list) and executions == []:
            body_kind = "empty-executions"
        elif isinstance(executions, list) and executions:
            body_kind = "executions-present"
            tree_token = _detail_tree_token(payload)
        else:
            body_kind = "unexpected-shape"
    else:
        body_kind = "unexpected-shape"
    rpc_code_str = "none" if rpc_code is None else str(rpc_code)
    return (
        f"status={response.status} body_kind={body_kind} "
        f"rpc_code={rpc_code_str} body_len={body_len} "
        f"state={_state_detail_token(payload)} cum={_cum_detail_token(payload)}"
        f"{tree_token}"
    )


def classify_create_order_outcome(
    response: VenueResponse | None,
    *,
    instrument: object,
    account_id: object,
    ts_init: int,
) -> CreateOrderOutcome:
    """Classify one create-order HTTP outcome. AMBIGUOUS is the residual."""
    if response is None:
        return CreateOrderOutcome(
            kind=KIND_AMBIGUOUS,
            reason=AMBIGUOUS_REASON,
            retirement_name=None,
            venue_order_id=None,
            fill=None,
            filled_cost_usd=None,
            cumulative_qty=None,
            cumulative_cost=None,
            cumulative_fee=None,
            fee_reconciled=False,
            generate_submitted=False,
            detail=_AMBIGUOUS_DETAIL_NO_RESPONSE,
        )
    status = int(response.status)
    payload = _parse_json_object(response.body)
    order_id = _response_order_id(payload) if payload is not None else None
    detail = _body_detail(response, payload, order_id)

    if (
        400 <= status < 500
        and payload is not None
        and _is_google_rpc_status(payload)
        and order_id is None
    ):
        return CreateOrderOutcome(
            kind=KIND_REJECT,
            reason="venue 4xx google.rpc.Status with no order id",
            retirement_name=RETIRE_REJECT,
            venue_order_id=None,
            fill=None,
            filled_cost_usd=None,
            cumulative_qty=None,
            cumulative_cost=None,
            cumulative_fee=None,
            fee_reconciled=False,
            generate_submitted=False,
            detail=detail,
        )

    fill_parse_errors: list[str] = []
    if status == 200 and payload is not None and order_id is not None:
        execution = _durable_execution(payload)
        if execution is not None:
            fill = fill_generation(
                execution,
                instrument=instrument,
                account_id=account_id,
                ts_init=ts_init,
                payload=payload,
                errors=fill_parse_errors,
            )
            if fill is not None:
                cumulative_qty, cumulative_cost = _cumulative_qty_and_cost(execution)
                cumulative_fee, fee_reconciled = _cumulative_fee_and_reconciliation(
                    payload, execution, cumulative_qty=cumulative_qty
                )
                return CreateOrderOutcome(
                    kind=KIND_ACCEPT_FILL,
                    reason="200 with durable fill record",
                    retirement_name=RETIRE_ACCEPT_FILL,
                    venue_order_id=order_id,
                    fill=fill,
                    filled_cost_usd=fill.filled_cost_usd,
                    cumulative_qty=cumulative_qty,
                    cumulative_cost=cumulative_cost,
                    cumulative_fee=cumulative_fee,
                    fee_reconciled=fee_reconciled,
                    generate_submitted=True,
                    detail=detail,
                )
        executions = payload.get("executions")
        terminal = _terminal_state(payload)
        cum = _cum_quantity(payload)
        if (
            isinstance(executions, list)
            and executions == []
            and terminal in _IOC_ZERO_FILL_TERMINAL_STATES
            and cum == ZERO
        ):
            return CreateOrderOutcome(
                kind=KIND_ZERO_FILL,
                reason="200 with empty executions, terminal IOC state, cumQuantity 0",
                retirement_name=RETIRE_ZERO_FILL,
                venue_order_id=order_id,
                fill=None,
                filled_cost_usd=ZERO,
                cumulative_qty=None,
                cumulative_cost=None,
                cumulative_fee=None,
                fee_reconciled=False,
                generate_submitted=True,
                detail=detail,
            )

    return CreateOrderOutcome(
        kind=KIND_AMBIGUOUS,
        reason=AMBIGUOUS_REASON,
        retirement_name=None,
        venue_order_id=order_id,
        fill=None,
        filled_cost_usd=None,
        cumulative_qty=None,
        cumulative_cost=None,
        cumulative_fee=None,
        fee_reconciled=False,
        generate_submitted=order_id is not None,
        detail=detail,
        fill_parse_error=fill_parse_errors[0] if fill_parse_errors else None,
    )


def retirement_member(reasons: object, name: str) -> object:
    return getattr(reasons, name)
