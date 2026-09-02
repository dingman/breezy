"""Venue payload -> NATIVE Nautilus execution reports. Mapping only.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-3. **Read/map
only** -- every function here is pure, takes an already-decoded payload, and
performs no I/O.

NULL HYPOTHESIS: CONFIRMED, so Breezy defines no report class of its own.
``OrderStatusReport`` (``nautilus_trader/execution/reports.py:95``),
``FillReport`` (``:619``), ``PositionStatusReport`` (``:859``) and
``ExecutionMassStatus`` (``:1038``) are all native and are constructed
directly. ``AccountBalance`` (``model/objects.pyx:1897``) is likewise native.

WHAT THE MAPPING IS KEYED OFF, AND WHAT THAT COSTS
---------------------------------------------------

No live shape capture exists: all four authenticated smoke runs recorded
``Connectivity verdict: FAIL``
(``docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_*.md``). So the key
allowlists and enum tables below are transcribed from the SDK snapshot
TypedDicts (``docs/evidence/venue/polymarket_us/sdk_snapshot/
polymarket_us_0.1.2/types/``) and from nothing else. Nothing here is
live-verified, and the mappers behave accordingly:

* **Total over the declared shapes.** Every ``OrderState``, ``ExecutionType``,
  ``OrderSide``, ``OrderType`` and ``TimeInForce`` member the snapshot spells
  out has a mapping. ``ORDER_STATE_TO_ORDER_STATUS`` is asserted complete by
  the test suite against the snapshot's own ``Literal``.
* **Refusal outside them.** An unrecognised member, an undeclared key, a
  missing required field, or a money value the native constructor would
  silently round all raise :class:`ExecutionReportMappingError`. There is no
  coercion path and no default value anywhere in this module.

Two mappings are judgement calls and are named as such rather than buried.
``ORDER_STATE_PENDING_RISK`` has no Nautilus counterpart and is read as
``SUBMITTED`` (acknowledged by the venue, not yet working). It is REACHABLE:
a venue-side risk check can fire on any order Breezy submits, amendment or
not, so this mapping is on the live path and is not a formality.
``ORDER_STATE_REPLACED`` is read as ``ACCEPTED``, which is the status Nautilus
itself leaves an order in after an accepted update; THAT one is unreachable
through an order Breezy placed, because Breezy never amends.

THREE THINGS THIS MODULE DELIBERATELY DOES NOT DO
--------------------------------------------------

1. **It does not derive a position's average open price** *in the mapper*.
   ``UserPosition`` has no average-entry field. ``cost``/``qtyBought``
   (``types/portfolio.py:25-27``) look like a derivation, but whether ``cost``
   is net of sells is undefined by the snapshot and unobserved live, and the
   plan assigns the entry price to R-4's durable fill record (OQ-1).
   :func:`parse_position_status_report` therefore leaves ``avg_px_open``
   ``None`` rather than filling it with a guess.
   :func:`derive_position_cost_basis` is the separately-called FALLBACK for
   the case where no fill record exists, and it is sound only under
   ``qtySold == 0`` -- the one condition that removes the ambiguity. It is a
   distinct function precisely so the mapper's output cannot silently acquire
   a derived number.
2. **It does not resolve a ``ClientOrderId``.** The venue payload carries no
   field for one, so every report leaves it ``None``. R-4 owns the
   venue-id -> client-id map and attaches it.
3. **It does not read an order's ``intent``.** ``side`` already determines the
   Nautilus ``OrderSide`` unambiguously, so ``intent`` is a declared but
   unconsumed key. Barrier X3 backs that up, but it is narrower than "no
   directional vocabulary at all": it bans two specific TOKENS -- the venue's
   sell-short intent suffix and its NO-outcome constant, both spelled out in
   ``BANNED_EXEC_DIRECTION_TOKENS`` rather than here, because X3 reads this
   file as raw text and naming them would trip it -- plus complement
   arithmetic on a price. ``PositionSide.SHORT`` is NOT among them and is used
   below: :func:`parse_position_status_report` must be able to REPORT a short
   Breezy did not open. What X3 forbids is the vocabulary by which a direction
   MODEL would enter, which is the right constraint for a long-only adapter.

MONEY
-----

``_parse_amount`` (``parsing.py:525-539``) is REUSED verbatim for every
``Amount``-shaped field: it already refuses a non-``USD`` currency and already
returns ``Decimal``. It is not reimplemented here. Bare-``float`` balance
fields have no ``Amount`` wrapper, so they go through ``_to_decimal``, which
never performs binary float arithmetic.

Native ``Money`` rounds to the currency precision in silence -- measured:
``Money(Decimal("0.3125"), USD)`` is ``Money(0.31, USD)`` and
``Money(Decimal("0.005"), USD)`` is ``Money(0.01, USD)``. Every money value is
therefore checked against ``USD.precision`` with ``_assert_representable``
BEFORE the constructor sees it, and refused if it would change. A sub-cent
commission is a refusal, not a rounding: if the venue really does bill below
the cent, that is a modelling decision for the increment that observes it, not
something this module should absorb by quietly dropping the remainder.

Prices go through the SAME guard whether the native field wants a ``Price`` or
a ``Decimal``. ``OrderStatusReport.avg_px`` is typed ``Decimal | None``, which
made it look like a plain amount; it is not. Nautilus reconciliation feeds it
to ``instrument.make_price()`` (``live/reconciliation.py:408``, ``:487``,
``:502``) and books the result as a fill price, so it is range-checked and
precision-checked exactly as ``price`` is.

OBLIGATION FOR R-4 -- ``calculate_commission`` is NOT optional
---------------------------------------------------------------

``create_inferred_order_filled_event`` calls
``client.calculate_commission(...)`` and, when it returns ``None``, books
``Money(0, instrument.quote_currency)`` (``live/reconciliation.py:507-508``).
That is an IMPLIED-ZERO FEE -- precisely the "the venue said nothing" ->
"the venue is free" conflation that
:func:`~breezy.adapters.polymarket_us.parsing.assert_fee_schedule_known` exists
to prevent, arriving through a path that guard never sees. The fallback is
Nautilus's own and is IMMUTABLE; it cannot be patched, only pre-empted. So the
execution client R-4 builds MUST implement ``calculate_commission`` on top of
``PolymarketUSFeeModel`` rather than inherit the default, and must fail closed
while the schedule is UNKNOWN. R-3 does not build it -- this module maps
reports and constructs no client -- but the obligation is recorded here
because this is the module whose output reaches that code path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final, NamedTuple

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.reports import (
    ExecutionMassStatus,
    FillReport,
    OrderStatusReport,
    PositionStatusReport,
)
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import (
    LiquiditySide,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import AccountId, ClientId, TradeId, VenueOrderId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import AccountBalance, Money, Price, Quantity

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.parsing import (
    QUOTE_CURRENCY_CODE,
    _assert_price_representable,
    _assert_representable,
    _build_price,
    _build_quantity,
    _parse_amount,
    _to_decimal,
    parse_rfc3339_nanos,
)
from breezy.adapters.polymarket_us.parsing import (
    _require as _require_field,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE

__all__ = [
    "ORDER_STATE_TO_ORDER_STATUS",
    "MappedPosition",
    "build_execution_mass_status",
    "derive_position_cost_basis",
    "parse_account_balances",
    "parse_fill_report",
    "parse_order_status_report",
    "parse_position_status_report",
]

# ---------------------------------------------------------------------------
# Declared shapes -- transcribed from the SDK snapshot TypedDicts
# ---------------------------------------------------------------------------

#: ``GetAccountBalancesResponse`` (``types/account.py:36-39``).
_BALANCES_RESPONSE_KEYS: Final[frozenset[str]] = frozenset({"balances"})

#: ``UserBalance`` (``types/account.py:19-33``).
_USER_BALANCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "assetAvailable",
        "assetNotional",
        "balanceReservation",
        "buyingPower",
        "currency",
        "currentBalance",
        "lastUpdated",
        "marginRequirement",
        "openOrders",
        "pendingCredit",
        "pendingWithdrawals",
        "unsettledFunds",
    }
)

#: ``Order`` (``types/orders.py:70-92``).
_ORDER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "avgPx",
        "cashOrderQty",
        "commissionNotionalTotalCollected",
        "commissionsBasisPoints",
        "createTime",
        "cumQuantity",
        "goodTillTime",
        "id",
        "insertTime",
        "intent",
        "leavesQuantity",
        "makerCommissionsBasisPoints",
        "marketMetadata",
        "marketSlug",
        "price",
        "quantity",
        "side",
        "state",
        "tif",
        "type",
    }
)

#: ``Execution`` (``types/orders.py:95-108``).
_EXECUTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "aggressor",
        "commissionNotionalCollected",
        "id",
        "lastPx",
        "lastShares",
        "order",
        "orderRejectReason",
        "text",
        "tradeId",
        "transactTime",
        "type",
    }
)

#: ``UserPosition`` (``types/portfolio.py:21-34``).
_USER_POSITION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "bodPosition",
        "cashValue",
        "cost",
        "expired",
        "marketMetadata",
        "netPosition",
        "qtyAvailable",
        "qtyBought",
        "qtySold",
        "realized",
        "updateTime",
    }
)

#: ``MarketMetadata`` (``types/orders.py:58-67``).
_MARKET_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {"eventSlug", "icon", "outcome", "slug", "team", "teamId", "title"}
)

_ORDER_SIDES: Final[Mapping[str, OrderSide]] = {
    "ORDER_SIDE_BUY": OrderSide.BUY,
    "ORDER_SIDE_SELL": OrderSide.SELL,
}

_ORDER_TYPES: Final[Mapping[str, OrderType]] = {
    "ORDER_TYPE_LIMIT": OrderType.LIMIT,
    "ORDER_TYPE_MARKET": OrderType.MARKET,
}

_TIME_IN_FORCE: Final[Mapping[str, TimeInForce]] = {
    "TIME_IN_FORCE_FILL_OR_KILL": TimeInForce.FOK,
    "TIME_IN_FORCE_GOOD_TILL_CANCEL": TimeInForce.GTC,
    "TIME_IN_FORCE_GOOD_TILL_DATE": TimeInForce.GTD,
    "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL": TimeInForce.IOC,
}

#: Every ``OrderState`` the snapshot declares (``types/orders.py:21-33``),
#: mapped to the Nautilus ``OrderStatus`` a reconciler should read it as.
#: PUBLIC so the test suite can assert this table against the snapshot itself
#: rather than against a second copy of the same list.
ORDER_STATE_TO_ORDER_STATUS: Final[Mapping[str, OrderStatus]] = {
    "ORDER_STATE_NEW": OrderStatus.ACCEPTED,
    "ORDER_STATE_PENDING_NEW": OrderStatus.SUBMITTED,
    "ORDER_STATE_PENDING_REPLACE": OrderStatus.PENDING_UPDATE,
    "ORDER_STATE_PENDING_CANCEL": OrderStatus.PENDING_CANCEL,
    # No Nautilus counterpart. A venue-side risk check is an acknowledged but
    # not-yet-working order, which is what SUBMITTED means.
    "ORDER_STATE_PENDING_RISK": OrderStatus.SUBMITTED,
    "ORDER_STATE_PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "ORDER_STATE_FILLED": OrderStatus.FILLED,
    "ORDER_STATE_CANCELED": OrderStatus.CANCELED,
    # Nautilus has no REPLACED status; an order that completed an amendment is
    # ACCEPTED again. Unreachable for Breezy, which never amends.
    "ORDER_STATE_REPLACED": OrderStatus.ACCEPTED,
    "ORDER_STATE_REJECTED": OrderStatus.REJECTED,
    "ORDER_STATE_EXPIRED": OrderStatus.EXPIRED,
}

#: The two ``ExecutionType`` members that describe a trade
#: (``types/orders.py:34-43``). Every other declared member is a lifecycle
#: acknowledgement, and turning one into a ``FillReport`` would invent a trade.
_FILL_EXECUTION_TYPES: Final[frozenset[str]] = frozenset(
    {"EXECUTION_TYPE_FILL", "EXECUTION_TYPE_PARTIAL_FILL"}
)


# ---------------------------------------------------------------------------
# Primitive readers -- every one of them refuses rather than coerces
# ---------------------------------------------------------------------------


def _assert_known_keys(
    payload: object, *, known: frozenset[str], context: str
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ExecutionReportMappingError(
            f"{context} must be a JSON object, got {type(payload).__name__}"
        )
    unknown = sorted(repr(key) for key in payload if key not in known)
    if unknown:
        raise ExecutionReportMappingError(
            f"{context} carries field(s) {', '.join(unknown)} that the SDK snapshot "
            "does not declare; the venue shape moved under a surface reconciliation "
            "reads money from, so it is refused rather than ignored"
        )
    mapping: Mapping[str, Any] = payload
    return mapping


def _require(payload: Mapping[str, Any], key: str, *, context: str) -> Any:
    """The adapter's own required-field reader, bound to this module's error.

    Delegation, not a second implementation: ``parsing._require`` already IS
    the refusal, and a private copy here would be a second place for the
    "absent is never a default" rule to drift out of.
    """
    return _require_field(payload, key, error=ExecutionReportMappingError, context=context)


def _name_value(value: object, *, limit: int = 64) -> str:
    """Describe a venue-supplied value for diagnosis, without echoing it whole.

    An unrecognised enum member has to be NAMED or the refusal is undebuggable,
    but the string is venue-controlled and unbounded, and a non-string could be
    an entire nested payload. So: a short string is quoted verbatim, a long one
    is truncated with its true length stated, and a non-string is named by TYPE
    only.
    """
    if not isinstance(value, str):
        return type(value).__name__
    if len(value) <= limit:
        return repr(value)
    return f"{value[:limit]!r} (truncated from {len(value)} characters)"


def _require_text(payload: Mapping[str, Any], key: str, *, context: str) -> str:
    value = _require(payload, key, context=context)
    if not isinstance(value, str) or not value:
        raise ExecutionReportMappingError(
            f"{context} field {key!r} must be a non-empty string, got "
            f"{type(value).__name__}"
        )
    return value


def _require_bool(payload: Mapping[str, Any], key: str, *, context: str) -> bool:
    value = _require(payload, key, context=context)
    if not isinstance(value, bool):
        raise ExecutionReportMappingError(
            f"{context} field {key!r} must be a boolean, got {type(value).__name__}"
        )
    return value


def _lookup[T](
    table: Mapping[str, T], payload: Mapping[str, Any], key: str, *, context: str
) -> T:
    value = _require(payload, key, context=context)
    if not isinstance(value, str) or value not in table:
        raise ExecutionReportMappingError(
            f"{context} field {key!r} carries {_name_value(value)}, which is outside "
            f"the members the SDK snapshot declares ({', '.join(sorted(table))})"
        )
    return table[value]


def _usd_money(value: Decimal, *, field: str) -> Money:
    """Build ``Money`` only when the native constructor will not alter the value."""
    representable = _assert_representable(
        value, precision=USD.precision, field=field, error=ExecutionReportMappingError
    )
    return Money(representable, USD)


def _report_quantity(
    value: Decimal, *, instrument: Instrument, field: str, allow_zero: bool
) -> Quantity:
    """Bind ``parsing._build_quantity`` to this module's instrument and error.

    Delegation, not a second implementation -- the refusal, the representable
    check and the format string all live in one place.
    """
    return _build_quantity(
        value,
        precision=instrument.size_precision,
        field=field,
        error=ExecutionReportMappingError,
        allow_zero=allow_zero,
    )


def _quantity_field(
    payload: Mapping[str, Any],
    key: str,
    *,
    instrument: Instrument,
    context: str,
    allow_zero: bool = False,
) -> Quantity:
    field = f"{context}.{key}"
    value = _to_decimal(
        _require(payload, key, context=context),
        field=field,
        error=ExecutionReportMappingError,
    )
    return _report_quantity(
        value, instrument=instrument, field=field, allow_zero=allow_zero
    )


def _amount_field(payload: Mapping[str, Any], key: str, *, context: str) -> Decimal:
    """Read an ``Amount``-shaped field through the adapter's existing reader."""
    return _parse_amount(
        _require(payload, key, context=context),
        field=f"{context}.{key}",
        error=ExecutionReportMappingError,
    )


def _price_field(
    payload: Mapping[str, Any], key: str, *, instrument: Instrument, context: str
) -> Price:
    return _build_price(
        _amount_field(payload, key, context=context),
        precision=instrument.price_precision,
        field=f"{context}.{key}",
        error=ExecutionReportMappingError,
    )


def _price_decimal_field(
    payload: Mapping[str, Any], key: str, *, instrument: Instrument, context: str
) -> Decimal:
    """A price field that the native report wants as a ``Decimal``, not a ``Price``.

    Same guard, same refusals, same taxonomy as :func:`_price_field` -- only
    the return type differs, because ``OrderStatusReport.avg_px`` is typed
    ``Decimal | None`` (``execution/reports.py:209``). Routing it through
    ``_amount_field`` alone -- which is what this module used to do -- left the
    venue's raw ``Decimal`` unranged and unquantised, and Nautilus then books
    it as a FILL PRICE via ``instrument.make_price(report.avg_px)``
    (``live/reconciliation.py:487``). Measured at precision 2: ``0.5249``
    became ``0.52`` in silence, and ``1.35`` -- an impossible cost basis on a
    contract that pays at most 1.00 -- was accepted outright.
    """
    return _assert_price_representable(
        _amount_field(payload, key, context=context),
        precision=instrument.price_precision,
        field=f"{context}.{key}",
        error=ExecutionReportMappingError,
    )


def _assert_market_matches(slug: object, *, instrument: Instrument, context: str) -> None:
    """Refuse a payload whose market is not the instrument it is mapped onto.

    Attaching a report to the wrong instrument moves the wrong position, so a
    mismatch is refused rather than resolved by preferring one side. Callers
    invoke this UNCONDITIONALLY: a payload that carries no market identifier of
    its own is not a payload that matches every market, and the caller supplies
    the authoritative one instead.
    """
    expected = str(instrument.raw_symbol)
    if slug != expected:
        raise ExecutionReportMappingError(
            f"{context} names market {_name_value(slug)} but is being mapped onto "
            f"instrument {instrument.id}; refusing to attach a report to a "
            "different market"
        )


def _assert_fill_progress_consistent(
    payload: Mapping[str, Any],
    *,
    quantity: Quantity,
    filled_qty: Quantity,
    instrument: Instrument,
    context: str,
) -> None:
    """Refuse an order whose own fill progress contradicts itself.

    ``OrderStatusReport`` does not validate this; it CLAMPS. Leaves is derived
    with a saturating subtraction, so ``quantity=10`` with ``cumQuantity=14``
    is accepted whole and reconciliation goes on to infer a 14-lot fill on a
    10-lot order. A contradiction is refused here instead of clamped there.

    ``leavesQuantity`` was allowlisted and then discarded. It is the venue's
    own cross-check on the other two, and checking it costs nothing. It is
    ``total=False`` in the snapshot, so an ABSENT leaves is not a
    contradiction and is not treated as one; a PRESENT leaves that disagrees
    is.
    """
    if filled_qty > quantity:
        raise ExecutionReportMappingError(
            f"{context} reports a 'cumQuantity' greater than its 'quantity'; a "
            "filled size larger than the order is a contradiction, and the native "
            "report would silently clamp it rather than refuse it"
        )
    if payload.get("leavesQuantity") is None:
        return
    leaves = _quantity_field(
        payload, "leavesQuantity", instrument=instrument, context=context, allow_zero=True
    )
    if leaves.as_decimal() != quantity.as_decimal() - filled_qty.as_decimal():
        raise ExecutionReportMappingError(
            f"{context} field 'leavesQuantity' does not equal 'quantity' minus "
            "'cumQuantity'; refusing a self-contradictory order payload rather "
            "than choosing which two of the three fields to believe"
        )


def _known_order(payload: object, *, context: str) -> Mapping[str, Any]:
    order = _assert_known_keys(payload, known=_ORDER_KEYS, context=context)
    metadata = order.get("marketMetadata")
    if metadata is not None:
        _assert_known_keys(
            metadata, known=_MARKET_METADATA_KEYS, context=f"{context}.marketMetadata"
        )
    return order


# ---------------------------------------------------------------------------
# Account balances -> native AccountBalance
# ---------------------------------------------------------------------------


def parse_account_balances(payload: Mapping[str, Any]) -> tuple[AccountBalance, ...]:
    """Map a ``GetAccountBalancesResponse`` to native ``AccountBalance`` values.

    ``total`` is ``currentBalance`` and ``free`` is ``buyingPower``; ``locked``
    is DERIVED as their difference rather than assembled from a guess about
    which of ``openOrders``, ``balanceReservation`` and ``marginRequirement``
    the venue counts as encumbrance. ``AccountBalance`` requires
    ``total - locked == free`` exactly, so the derivation is the only reading
    that is internally consistent without an observation we do not have. A
    ``free`` above ``total`` would imply borrowing; it is refused, not clamped.

    Non-``USD`` is a hard refusal. ``BinaryOption`` is built with
    ``currency=USD`` (``parsing.py:1297``) and an account denominated in
    anything else cannot be netted against it.
    """
    context = "account balances response"
    _assert_known_keys(payload, known=_BALANCES_RESPONSE_KEYS, context=context)
    entries = _require(payload, "balances", context=context)
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
        raise ExecutionReportMappingError(
            f"{context} field 'balances' must be a JSON array, got "
            f"{type(entries).__name__}"
        )
    if not entries:
        raise ExecutionReportMappingError(
            f"{context} carried no balance entry; an absent balance is not a zero "
            "balance, and defaulting one would publish spending power we cannot see"
        )
    return tuple(
        _parse_account_balance(entry, context=f"{context} balances[{index}]")
        for index, entry in enumerate(entries)
    )


def _parse_account_balance(payload: object, *, context: str) -> AccountBalance:
    balance = _assert_known_keys(payload, known=_USER_BALANCE_KEYS, context=context)

    currency = balance.get("currency")
    if currency != QUOTE_CURRENCY_CODE:
        raise ExecutionReportMappingError(
            f"{context} is denominated in {currency!r}, not {QUOTE_CURRENCY_CODE!r}; "
            "refusing to treat it as a USD balance"
        )

    total = _assert_representable(
        _to_decimal(
            _require(balance, "currentBalance", context=context),
            field=f"{context}.currentBalance",
            error=ExecutionReportMappingError,
        ),
        precision=USD.precision,
        field=f"{context}.currentBalance",
        error=ExecutionReportMappingError,
    )
    free = _assert_representable(
        _to_decimal(
            _require(balance, "buyingPower", context=context),
            field=f"{context}.buyingPower",
            error=ExecutionReportMappingError,
        ),
        precision=USD.precision,
        field=f"{context}.buyingPower",
        error=ExecutionReportMappingError,
    )
    locked = total - free
    if locked < 0:
        raise ExecutionReportMappingError(
            f"{context} reports 'buyingPower' above 'currentBalance', which would "
            "imply a negative encumbrance; the shape has never been observed and is "
            "refused rather than clamped. The two amounts are deliberately NOT "
            "named: a private balance is the operator's buying power, and this "
            "message is what R-4 attaches a logger to"
        )

    return AccountBalance(
        total=_usd_money(total, field=f"{context}.currentBalance"),
        locked=_usd_money(locked, field=f"{context}.locked"),
        free=_usd_money(free, field=f"{context}.buyingPower"),
    )


# ---------------------------------------------------------------------------
# Order -> native OrderStatusReport
# ---------------------------------------------------------------------------


def parse_order_status_report(
    payload: Mapping[str, Any],
    *,
    instrument: Instrument,
    account_id: AccountId,
    report_id: UUID4,
    ts_init: int,
) -> OrderStatusReport:
    """Map an ``Order`` (``types/orders.py:70-92``) to the native report.

    ``ts_accepted`` and ``ts_last`` are both ``createTime``. ``Order`` also
    carries ``insertTime``, but the snapshot defines neither field's semantics,
    and promoting an undefined timestamp to "the last order status change"
    would put an invented event time into reconciliation. Using the one field
    whose meaning is unambiguous states less, and states nothing false.
    """
    context = "order status report"
    order = _known_order(payload, context=context)
    _assert_market_matches(
        order.get("marketSlug"), instrument=instrument, context=context
    )

    ts_accepted = parse_rfc3339_nanos(
        _require(order, "createTime", context=context),
        field=f"{context}.createTime",
        error=ExecutionReportMappingError,
    )

    quantity = _quantity_field(order, "quantity", instrument=instrument, context=context)
    filled_qty = _quantity_field(
        order, "cumQuantity", instrument=instrument, context=context, allow_zero=True
    )
    _assert_fill_progress_consistent(
        order,
        quantity=quantity,
        filled_qty=filled_qty,
        instrument=instrument,
        context=context,
    )

    return OrderStatusReport(
        account_id=account_id,
        instrument_id=instrument.id,
        venue_order_id=VenueOrderId(_require_text(order, "id", context=context)),
        order_side=_lookup(_ORDER_SIDES, order, "side", context=context),
        order_type=_lookup(_ORDER_TYPES, order, "type", context=context),
        time_in_force=_lookup(_TIME_IN_FORCE, order, "tif", context=context),
        order_status=_lookup(ORDER_STATE_TO_ORDER_STATUS, order, "state", context=context),
        quantity=quantity,
        filled_qty=filled_qty,
        report_id=report_id,
        ts_accepted=ts_accepted,
        ts_last=ts_accepted,
        ts_init=ts_init,
        # A LIMIT price is absent on a MARKET order; both native fields are
        # optional, and an absent optional is left absent, never zeroed.
        price=(
            _price_field(order, "price", instrument=instrument, context=context)
            if order.get("price") is not None
            else None
        ),
        # ``avg_px`` is a PRICE to Nautilus, not a bare amount: reconciliation
        # feeds it to ``instrument.make_price()`` and books the result as a
        # fill price. It therefore runs the identical guard ``price`` does.
        avg_px=(
            _price_decimal_field(order, "avgPx", instrument=instrument, context=context)
            if order.get("avgPx") is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Execution -> native FillReport
# ---------------------------------------------------------------------------


def _assert_taker_fill(execution: Mapping[str, Any], *, context: str) -> None:
    """Refuse a fill the venue reports as MAKER. Its commission sign is unknown.

    The venue's documented maker coefficient is NEGATIVE (-0.0125): a REBATE,
    i.e. income, not a cost. ``commissionNotionalCollected`` is an ``Amount``
    and nothing in the SDK snapshot says whether its sign carries that, so a
    magnitude-only ``{"value": "1.12"}`` on a maker fill books +$1.12 of COST
    against $1.12 of INCOME -- wrong in sign, and wrong by twice the fee.

    Refusing costs nothing today and is the same refusal the adapter already
    makes one layer down: ``MakerRebateUnmodelledError`` rejects a post-only
    order outright, and ``PolymarketUSFeeModel`` has only the taker
    coefficient. Breezy is taker-only, so a venue-reported maker fill is not a
    cheaper fill to record -- it is an event the fee model cannot price and
    that Breezy did not intend to create, which is exactly the shape that must
    surface loudly rather than be mapped.

    Accepting it on a ``commission <= 0`` proof was the alternative and is
    weaker: a zero commission satisfies it while proving nothing, and a
    magnitude-only positive value would make the refusal fire for the wrong
    reason. Exposure is NOT hidden by this refusal -- the position surface
    (``parse_position_status_report``) reports the holding independently of
    any fill record.

    Resolve by observing a real maker fill and recording the venue's actual
    sign convention, not by relaxing this refusal.
    """
    if not _require_bool(execution, "aggressor", context=context):
        raise ExecutionReportMappingError(
            f"{context} field 'aggressor' is False, i.e. a MAKER fill. The venue's "
            "maker coefficient is a REBATE (negative), the payload's commission "
            "sign convention is unobserved, and Breezy is taker-only; refusing to "
            "book a fee whose SIGN is a guess"
        )


def parse_fill_report(
    payload: Mapping[str, Any],
    *,
    instrument: Instrument,
    account_id: AccountId,
    report_id: UUID4,
    ts_init: int,
) -> FillReport:
    """Map an ``Execution`` (``types/orders.py:95-108``) to the native report.

    Only the two fill execution types are accepted. Every other declared
    member -- a new, cancel, replace, reject, expire or done-for-day
    acknowledgement -- is refused, because a ``FillReport`` built from one
    asserts a trade that did not happen. A caller iterating a mixed list
    filters on ``type`` before calling; this refusal is the backstop.

    ``avg_px`` is left ``None``: ``last_px`` is the authoritative price of THIS
    fill, and the order-level average belongs on the order report.

    A MAKER fill is REFUSED -- see :func:`_assert_taker_fill`.
    """
    context = "fill report"
    execution = _assert_known_keys(payload, known=_EXECUTION_KEYS, context=context)

    execution_type = _require(execution, "type", context=context)
    if execution_type not in _FILL_EXECUTION_TYPES:
        raise ExecutionReportMappingError(
            f"{context} carries execution type {execution_type!r}, which is not one of "
            f"({', '.join(sorted(_FILL_EXECUTION_TYPES))}); refusing to report a trade "
            "the venue did not report"
        )

    order_context = f"{context}.order"
    order = _known_order(_require(execution, "order", context=context), context=order_context)
    _assert_market_matches(
        order.get("marketSlug"), instrument=instrument, context=order_context
    )

    _assert_taker_fill(execution, context=context)

    return FillReport(
        account_id=account_id,
        instrument_id=instrument.id,
        venue_order_id=VenueOrderId(_require_text(order, "id", context=order_context)),
        trade_id=TradeId(_require_text(execution, "tradeId", context=context)),
        order_side=_lookup(_ORDER_SIDES, order, "side", context=order_context),
        last_qty=_quantity_field(
            execution, "lastShares", instrument=instrument, context=context
        ),
        last_px=_price_field(execution, "lastPx", instrument=instrument, context=context),
        commission=_usd_money(
            _amount_field(execution, "commissionNotionalCollected", context=context),
            field=f"{context}.commissionNotionalCollected",
        ),
        liquidity_side=LiquiditySide.TAKER,
        report_id=report_id,
        ts_event=parse_rfc3339_nanos(
            _require(execution, "transactTime", context=context),
            field=f"{context}.transactTime",
            error=ExecutionReportMappingError,
        ),
        ts_init=ts_init,
    )


# ---------------------------------------------------------------------------
# UserPosition -> native PositionStatusReport
# ---------------------------------------------------------------------------


class MappedPosition(NamedTuple):
    """A native position report, plus the one fact the native type cannot carry.

    ``PositionStatusReport`` has no slot for ``expired``, and ``expired`` is
    not decoration: a resolved weather binary reporting ``expired: True`` with
    ``netPosition: "4"`` is SETTLED, not tradeable exposure. Dropped, it maps
    to a LONG-4 report indistinguishable from live risk, and every exposure cap
    downstream counts settled contracts as capacity it could still trade.

    Returned ALONGSIDE the native report rather than refused, because a settled
    position lingering on the portfolio endpoint is routine -- every weather
    binary settles -- and refusing one would break reconciliation daily for a
    condition that is not an error. Returned as a TUPLE rather than dropped,
    because a caller cannot ignore an unpacked value the way it can ignore a
    flag it was never handed.

    Breezy still defines no parallel REPORT type: ``report`` is the native
    ``PositionStatusReport``, unwrapped and unmodified.
    """

    report: PositionStatusReport
    expired: bool


def parse_position_status_report(
    payload: Mapping[str, Any],
    *,
    market_slug: str,
    instrument: Instrument,
    account_id: AccountId,
    report_id: UUID4,
    ts_init: int,
) -> MappedPosition:
    """Map a ``UserPosition`` (``types/portfolio.py:21-34``) to the native report.

    ``market_slug`` is REQUIRED and is the authoritative market identifier: in
    ``GetUserPositionsResponse`` (``types/portfolio.py:45-50``) the positions
    arrive as ``dict[str, UserPosition]`` and the slug is the DICT KEY, which
    this function never sees. ``UserPosition`` itself declares no ``marketSlug``
    -- only an OPTIONAL ``marketMetadata`` -- and the TypedDict is
    ``total=False``, so a payload with no metadata carries no market identity at
    all. That is why the check cannot be conditional on the metadata being
    present: it used to be, and an absent block therefore meant NO market check,
    letting market A's position bind to instrument B. With Nautilus's
    ``generate_missing_orders`` defaulting True, reconciliation then SYNTHESISES
    a fill and invents exposure in a market Breezy never traded.

    When ``marketMetadata`` IS present its ``slug`` must agree with
    ``market_slug``. Two venue-supplied identifiers that disagree are a
    contradiction, not a preference, and neither is picked over the other.

    A negative ``netPosition`` is REPORTED, not refused. Breezy is long-only
    and never opens one, but a position it did not open is exactly the risk an
    operator must be told about, and refusing to map it would leave the node
    unable to describe exposure it is actually carrying.

    ``avg_px_open`` is left ``None`` -- see the module docstring, item 1.
    """
    context = "position status report"
    position = _assert_known_keys(payload, known=_USER_POSITION_KEYS, context=context)

    _assert_market_matches(market_slug, instrument=instrument, context=context)

    metadata = position.get("marketMetadata")
    if metadata is not None:
        metadata_context = f"{context}.marketMetadata"
        _assert_known_keys(metadata, known=_MARKET_METADATA_KEYS, context=metadata_context)
        _assert_market_matches(
            metadata.get("slug"), instrument=instrument, context=metadata_context
        )

    # An absent settlement flag is not a "still live" flag. Same rule as every
    # other required field here: absent is refused, never defaulted.
    expired = _require_bool(position, "expired", context=context)

    net = _to_decimal(
        _require(position, "netPosition", context=context),
        field=f"{context}.netPosition",
        error=ExecutionReportMappingError,
    )
    if net > 0:
        side = PositionSide.LONG
    elif net < 0:
        side = PositionSide.SHORT
    else:
        side = PositionSide.FLAT

    return MappedPosition(
        report=PositionStatusReport(
            account_id=account_id,
            instrument_id=instrument.id,
            position_side=side,
            quantity=_report_quantity(
                abs(net),
                instrument=instrument,
                field=f"{context}.netPosition",
                allow_zero=True,
            ),
            report_id=report_id,
            ts_last=parse_rfc3339_nanos(
                _require(position, "updateTime", context=context),
                field=f"{context}.updateTime",
                error=ExecutionReportMappingError,
            ),
            ts_init=ts_init,
        ),
        expired=expired,
    )


def derive_position_cost_basis(payload: Mapping[str, Any]) -> Decimal | None:
    """The venue's own average entry price, or ``None`` when it cannot be one.

    This is the SECOND source of a position's ``avg_px_open``, used only when
    Breezy's durable fill records cannot supply one. It is deliberately narrow.

    ``UserPosition`` (``types/portfolio.py:21-34``) carries no average-entry
    field. ``cost`` and ``qtyBought`` look like a derivation, and item 1 of
    this module's docstring declines to make one -- because whether ``cost`` is
    NET OF SELLS is undefined by the snapshot and unobserved live. Under
    ``qtySold == 0`` that ambiguity does not exist: there are no sells for
    ``cost`` to be net of, so ``cost / qtyBought`` is the entry price under
    either reading. Outside that condition it is refused, which is why this
    returns ``None`` rather than a best effort.

    ``None`` is not "zero" and never becomes one: the caller forwards the
    position UNPRICED and latches a trading refusal instead.
    """
    context = "position cost basis"
    if payload.get("qtySold") is None or payload.get("qtyBought") is None:
        return None
    if payload.get("cost") is None:
        return None

    sold = _to_decimal(
        payload["qtySold"], field=f"{context}.qtySold", error=ExecutionReportMappingError
    )
    if sold != 0:
        return None

    bought = _to_decimal(
        payload["qtyBought"], field=f"{context}.qtyBought", error=ExecutionReportMappingError
    )
    if bought <= 0:
        return None

    cost = _amount_field(payload, "cost", context=context)
    if cost <= 0:
        # A non-positive cost on a long the venue says was BOUGHT is a
        # contradiction, not a free position. Refused, never divided.
        return None

    return cost / bought


# ---------------------------------------------------------------------------
# Native assembly
# ---------------------------------------------------------------------------


def build_execution_mass_status(
    *,
    client_id: ClientId,
    account_id: AccountId,
    report_id: UUID4,
    ts_init: int,
    order_reports: Sequence[OrderStatusReport],
    fill_reports: Sequence[FillReport],
    position_reports: Sequence[PositionStatusReport],
) -> ExecutionMassStatus:
    """Assemble the native mass status. Assembly only -- no mapping happens here.

    An empty mass status is a legitimate result (a flat, orderless account) and
    is returned as such. The venue is pinned to ``POLYMARKET_US_VENUE`` rather
    than accepted as a parameter: this module maps one venue's payloads, and a
    mass status labelled with another venue would route reconciliation at the
    wrong exchange.
    """
    mass_status = ExecutionMassStatus(
        client_id=client_id,
        account_id=account_id,
        venue=POLYMARKET_US_VENUE,
        report_id=report_id,
        ts_init=ts_init,
    )
    mass_status.add_order_reports(list(order_reports))
    mass_status.add_fill_reports(list(fill_reports))
    mass_status.add_position_reports(list(position_reports))
    return mass_status
