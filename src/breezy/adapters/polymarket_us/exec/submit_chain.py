"""Pure helpers for the Polymarket.us submit path (R-7).

No I/O, no awaits, no network client. ``_submit_order`` is the one chokepoint;
this module classifies order shape, encodes the venue body, and classifies the
create-order response. X3 bans the NO-outcome constant under ``exec/``: a
NO instrument is unmappable rather than encoded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final, cast

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import AccountId, TradeId, VenueOrderId
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError, VenueTransportError
from breezy.adapters.polymarket_us.exec.reports import parse_fill_report
from breezy.adapters.polymarket_us.transport import VenueResponse

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
_YES_OUTCOME: Final[str] = "yes"
_OUTCOME_SIDE_YES: Final[str] = "OUTCOME_SIDE_YES"
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
    ts_event: int
    filled_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class CreateOrderOutcome:
    """One classified create-order response. Absence of a field is absence."""

    kind: str
    reason: str
    retirement_name: str | None
    venue_order_id: str | None
    fill: FillGeneration | None
    filled_cost_usd: Decimal | None
    generate_submitted: bool


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
    outcome = getattr(instrument, "outcome", None)
    if not isinstance(outcome, str) or not outcome.strip():
        info = getattr(instrument, "info", None)
        if isinstance(info, Mapping):
            outcome = info.get("outcome")
    if not isinstance(outcome, str):
        return None
    if outcome.strip().casefold() == _YES_OUTCOME:
        return _OUTCOME_SIDE_YES
    return None


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
    if _outcome_token(instrument) is None:
        return "no YES outcome leg is derivable from the instrument; refusing"
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
        raise ValueError("no YES outcome leg is derivable from the instrument; refusing")
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
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
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
    executions = payload.get("executions")
    if not isinstance(executions, list):
        return None
    for item in executions:
        if not isinstance(item, Mapping):
            continue
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


def fill_generation(
    execution: Mapping[str, Any],
    *,
    instrument: object,
    account_id: object,
    ts_init: int,
) -> FillGeneration | None:
    try:
        report = parse_fill_report(
            dict(execution),
            instrument=cast(Instrument, instrument),
            account_id=cast(AccountId, account_id),
            report_id=UUID4(),
            ts_init=ts_init,
        )
    except (ExecutionReportMappingError, TypeError, ValueError):
        return None
    filled_cost = _filled_cost_from_execution(execution)
    if filled_cost is None:
        return None
    return FillGeneration(
        venue_order_id=report.venue_order_id,
        trade_id=report.trade_id,
        last_qty=report.last_qty,
        last_px=report.last_px,
        commission=report.commission,
        ts_event=int(report.ts_event),
        filled_cost_usd=filled_cost,
    )


def venue_order_id(order_id: str) -> VenueOrderId:
    return VenueOrderId(order_id)


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
            generate_submitted=False,
        )
    status = int(response.status)
    payload = _parse_json_object(response.body)
    order_id = _response_order_id(payload) if payload is not None else None

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
            generate_submitted=False,
        )

    if status == 200 and payload is not None and order_id is not None:
        execution = _durable_execution(payload)
        if execution is not None:
            fill = fill_generation(
                execution, instrument=instrument, account_id=account_id, ts_init=ts_init
            )
            if fill is not None:
                return CreateOrderOutcome(
                    kind=KIND_ACCEPT_FILL,
                    reason="200 with durable fill record",
                    retirement_name=RETIRE_ACCEPT_FILL,
                    venue_order_id=order_id,
                    fill=fill,
                    filled_cost_usd=fill.filled_cost_usd,
                    generate_submitted=True,
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
                generate_submitted=True,
            )

    return CreateOrderOutcome(
        kind=KIND_AMBIGUOUS,
        reason=AMBIGUOUS_REASON,
        retirement_name=None,
        venue_order_id=order_id,
        fill=None,
        filled_cost_usd=None,
        generate_submitted=order_id is not None,
    )


def retirement_member(reasons: object, name: str) -> object:
    return getattr(reasons, name)
