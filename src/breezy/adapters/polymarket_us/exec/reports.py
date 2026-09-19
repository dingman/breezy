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
``Money(Decimal("0.005"), USD)`` is ``Money(0.01, USD)``, and that second
mode is NOT banker's. Fill ``commissionNotionalCollected`` is therefore
banker's-rounded to ``USD.precision`` (the venue rule) BEFORE the constructor
sees it, then checked with ``_assert_representable``. The original venue
string is logged when rounding changes the value (and, on the submit path,
stored as ``commission_raw``). A non-zero raw fee that books as ``0.00`` is
a warning, not a silent zero. Prices, quantities, and every other USD amount
still refuse extra precision -- a sub-tick price is a refusal, not a
rounding. ``_assert_representable`` itself is unchanged.

L-2 unit: unit before = venue Amount.value USD notional (unbounded decimal
string); unit after (FillReport/OrderFilled.commission) = Money(USD) at
precision 2, bankers-rounded; equal because both are USD notional -- the
only change is the native Money quantum, which cannot carry sub-cents.
unit after (DurableFillRecord.cumulative_fee) = same Decimal notional as
before, unrounded.

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

import logging
from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation
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
from breezy.adapters.polymarket_us.leg_prices import (
    Leg,
    assert_echo_matches_leg,
    assert_exit_echo_matches_leg,
    instrument_price_for_leg,
)
from breezy.adapters.polymarket_us.parsing import (
    QUOTE_CURRENCY_CODE,
    _assert_price_representable,
    _assert_representable,
    _build_price,
    _build_quantity,
    _name_value,
    _parse_amount,
    _to_decimal,
    parse_rfc3339_nanos,
)
from breezy.adapters.polymarket_us.parsing import (
    _require as _require_field,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, leg_of

logger = logging.getLogger(__name__)

__all__ = [
    "OPEN_ORDER_UNKNOWN_KEYS_MAX",
    "ORDER_STATE_TO_ORDER_STATUS",
    "MappedPosition",
    "OpenOrderRecord",
    "build_execution_mass_status",
    "derive_position_cost_basis",
    "parse_account_balances",
    "parse_fill_report",
    "parse_open_orders",
    "parse_order_status_report",
    "parse_position_status_report",
]

# ---------------------------------------------------------------------------
# Declared shapes -- transcribed from the SDK snapshot TypedDicts
# ---------------------------------------------------------------------------

#: ``GetAccountBalancesResponse`` (``types/account.py:36-39``).
_BALANCES_RESPONSE_KEYS: Final[frozenset[str]] = frozenset({"balances"})

#: ``UserBalance`` (``types/account.py:19-33``). Kept in EXACT lockstep with
#: the snapshot -- ``test_polymarket_us_exec_snapshot_drift.py`` asserts SET
#: EQUALITY against ``typed_dict_keys("account.py", "UserBalance")`` -- so this
#: set is NOT where a live-observed-but-unpinned field is added; see
#: :data:`_USER_BALANCE_DRIFT_ALLOWED_KEYS` below for that.
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

#: Six fields observed live on ``GET /v1/account/balances`` on 2026-09-04, plus
#: a seventh (``bonusHold``) observed live on 2026-09-19, that the pinned SDK
#: snapshot (``polymarket_us_0.1.2``, frozen at package release) does not
#: declare -- see
#: ``docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-04.md`` and
#: ``docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-19.md``.
#: Declared here, repo-side, as DECLARED-BUT-UNREAD: accepted so the
#: reconciliation does not refuse an otherwise-healthy connect over a name it
#: has never needed, but not merged into :data:`_USER_BALANCE_KEYS` itself --
#: that set must stay exactly what the snapshot declares, or the drift check
#: above goes vacuous. None of these seven is read for money by
#: :func:`_parse_account_balance`; a field the venue adds beyond THESE seven is
#: still an unknown key and is still refused.
_USER_BALANCE_DRIFT_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availableToWithdraw",
        "bonusHold",
        "bonusReservation",
        "depositReservation",
        "displayedAvailableSoon",
        "displayedBonus",
        "displayedCash",
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

#: Four fields observed live on ``GET /v1/order/{id}`` at 2026-09-11T20:20:31Z
#: while resolving the AMBIGUOUS IOC ``CEBPX0EVTTMX``
#: (``tc-temp-sfohigh-2026-09-11-gte70lt71f``) that the pinned SDK snapshot
#: (``polymarket_us_0.1.2``, frozen at package release) does not declare.
#: Declared here, repo-side, as DECLARED-BUT-UNREAD -- same treatment as
#: :data:`_USER_BALANCE_DRIFT_ALLOWED_KEYS` -- so the resolver's GET-status
#: read does not refuse an otherwise-healthy terminal/PARTIALLY_FILLED body
#: over a name it has never needed (NOTE: ``_known_order`` is also reached
#: from :func:`parse_fill_report`'s nested order, so the create-order /
#: fill classification is widened by the same four unread names), but not
#: merged into :data:`_ORDER_KEYS`
#: itself -- that set must stay exactly what the snapshot declares, or the
#: drift check in ``test_polymarket_us_exec_snapshot_drift.py`` goes vacuous.
#: None of these four is read for money or state by :func:`_known_order`,
#: :func:`parse_order_status_report` or :func:`parse_fill_report`:
#: ``outcomeSide`` is a known venue concept (BL-6: NO is a side of the same
#: book) already unread by every mapper here; ``action``,
#: ``lastTransactTime`` and ``manualOrderIndicator`` are FIX-style order
#: fields the mapper has never consumed. A field the venue adds beyond
#: THESE four is still an unknown key and is still refused.
_ORDER_DRIFT_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    {"action", "lastTransactTime", "manualOrderIndicator", "outcomeSide"}
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

#: Five fields observed live on a create-order 200 response at
#: 2026-09-13T17:03:46Z (node log ``breezy-trade-20260913T165011Z.log``
#: line 533, resolver store key
#: ``exec/polymarket_us/resolver/428709da14e14a8ba2602332753d8534``) for a
#: real MIA BUY 1 @0.70 IOC fill: ``commissionSpreadPx``, ``legPrices``,
#: ``traceId``, ``transactTradeDate``, ``unsolicitedCancelReason`` -- none
#: of which the pinned SDK snapshot (``types/orders.py:95-108``) declares.
#: Declared here, repo-side, as DECLARED-BUT-UNREAD -- same treatment as
#: :data:`_ORDER_DRIFT_ALLOWED_KEYS` -- so a real fill no longer falls to
#: KIND_AMBIGUOUS over names :func:`parse_fill_report` has never needed, but
#: not merged into :data:`_EXECUTION_KEYS` itself, or the drift check in
#: ``test_polymarket_us_exec_snapshot_drift.py`` goes vacuous. None of these
#: five is read for money or state by :func:`parse_fill_report`:
#: ``commissionSpreadPx`` is a maker-side spread fee Breezy is taker-only and
#: never prices, ``legPrices``/``traceId``/``transactTradeDate`` are venue
#: bookkeeping the mapper has never consumed, and
#: ``unsolicitedCancelReason`` is a cancel-path field that appears (empty)
#: even on a FILL row. A field the venue adds beyond THESE five is still an
#: unknown key and is still refused. Evidence:
#: ``docs/evidence/venue/polymarket_us/CREATE_ORDER_EXECUTION_DRIFT_2026-09-
#: 13_MIA.md``. Closes ruling R-6.
_EXECUTION_DRIFT_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "commissionSpreadPx",
        "legPrices",
        "traceId",
        "transactTradeDate",
        "unsolicitedCancelReason",
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

#: Eleven fields observed live on the startup position surface at
#: 2026-09-12T02:04:03Z, for the real position the account now carries (net
#: 1, from the 09-11 fill): ``avgPx``, ``baseCost``, ``bodPositionDecimal``,
#: ``comboLegDetails``, ``costPerShare``, ``fees``, ``netPositionDecimal``,
#: ``positionId``, ``qtyAvailableDecimal``, ``qtyBoughtDecimal`` and
#: ``qtySoldDecimal`` -- all beyond the pinned SDK snapshot. Declared here,
#: repo-side, as DECLARED-BUT-UNREAD -- same treatment as
#: :data:`_ORDER_DRIFT_ALLOWED_KEYS` -- so a healthy position no longer
#: refuses the whole surface over names the mapper has never needed, but not
#: merged into :data:`_USER_POSITION_KEYS` itself, or the drift check in
#: ``test_polymarket_us_exec_snapshot_drift.py`` goes vacuous.
#: :func:`parse_position_status_report` reads ``netPosition`` (a string, not
#: ``netPositionDecimal``) for quantity and side -- unchanged by this
#: declaration; none of these eleven ``*Decimal``/derived names is read
#: anywhere in this module. A field the venue adds beyond THESE eleven is
#: still an unknown key and is still refused.
_USER_POSITION_DRIFT_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "avgPx",
        "baseCost",
        "bodPositionDecimal",
        "comboLegDetails",
        "costPerShare",
        "fees",
        "netPositionDecimal",
        "positionId",
        "qtyAvailableDecimal",
        "qtyBoughtDecimal",
        "qtySoldDecimal",
    }
)

#: ``MarketMetadata`` (``types/orders.py:58-67``).
_MARKET_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {"eventSlug", "icon", "outcome", "slug", "team", "teamId", "title"}
)

#: Two fields observed live on ``GET /v1/order/{id}`` at 2026-09-12T02:04:06Z
#: while resolving venue order ``CEBPX0EVTTMX`` -- one layer deeper than the
#: 2026-09-11 order-level drift (:data:`_ORDER_DRIFT_ALLOWED_KEYS`):
#: ``marketMetadata`` itself now carries ``eventId`` and ``subject`` beyond
#: the pinned SDK snapshot. Declared here, repo-side, as DECLARED-BUT-UNREAD,
#: same treatment as the order-level drift set, but not merged into
#: :data:`_MARKET_METADATA_KEYS` itself, or the drift check in
#: ``test_polymarket_us_exec_snapshot_drift.py`` goes vacuous.
#:
#: ``MarketMetadata`` (``types/orders.py:58-67``) is ONE shared TypedDict the
#: snapshot embeds in both ``Order`` and ``UserPosition`` -- the same object,
#: not a lookalike -- so this allowlist is applied everywhere the snapshot
#: nests it: the order (``_known_order``, reached from both
#: :func:`parse_order_status_report` and :func:`parse_fill_report`'s nested
#: order) AND the position (:func:`parse_position_status_report`). Only the
#: order-GET evidence above has actually been observed; applying it to the
#: position surface too is a same-schema inference, not a second
#: observation -- a field the venue adds beyond THESE two, on EITHER
#: surface, is still an unknown key and is still refused. Neither field is
#: read anywhere in this module -- the only ``marketMetadata`` field ever
#: read is ``slug`` (the market-identity cross-check in both mappers).
_MARKET_METADATA_DRIFT_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({"eventId", "subject"})

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


#: Sanitiser knobs for :func:`_key_tree` / :func:`_safe_key_name` (SP-2 I0).
#: ``_KEY_NAME_MAX_CHARS`` mirrors :func:`_name_value`'s own ``limit: int =
#: 64``. ``_KEY_TREE_MAX_DEPTH`` is schema-derived: the deepest declared
#: create-order key path is body -> ``executions[]`` -> ``order`` ->
#: ``marketMetadata`` -> ``team`` (4 levels; ``team`` is ``<opaque>`` anyway).
#: ``_KEY_TREE_MAX_LIST_ROWS`` bounds how many list rows are rendered before
#: ``, +N more`` (N counts list ELEMENTS beyond the cap, not unrendered
#: mappings -- AR-N4). ``_KEY_TREE_OPAQUE_KEYS`` is matched at ANY depth
#: (AR-N3, chosen globally): ``MarketMetadata.team: dict[str, object]`` is
#: the one reachable free-form map in the declared shapes, and narrowing the
#: match to a specific parent context would add a parameter to this
#: recursive helper for no measured gain -- global matching can only make
#: MORE content opaque, never less.
_KEY_NAME_MAX_CHARS: Final[int] = 64
_KEY_TREE_MAX_DEPTH: Final[int] = 6
_KEY_TREE_MAX_LIST_ROWS: Final[int] = 8
_KEY_TREE_OPAQUE_KEYS: Final[frozenset[str]] = frozenset({"team"})
_DEPTH_CAPPED: Final[str] = "<depth-capped>"
_OPAQUE: Final[str] = "<opaque>"


def _safe_key_name(key: object) -> str:
    """Render one venue-supplied mapping KEY for a diagnostic, safely.

    ``ascii()`` output always opens and closes with the SAME quote character.
    The truncated branch slices at ``_KEY_NAME_MAX_CHARS``, which is strictly
    less than the index of that closing quote, so a GENUINE truncation always
    leaves the quoted span UNTERMINATED and puts the marker outside it. A key
    whose own content spells the marker therefore renders inside a CLOSED
    quote and is distinguishable -- see the marker placement rule on
    :func:`_key_tree`.

    The marker reports the RAW key length -- what the venue actually sent --
    not the length of the escaped rendering, so a 512-character key reads
    "truncated from 512 characters" and not 514 (CX-N1). Where escaping
    EXPANDS a short key past the cap the reported raw length is smaller than
    the emitted prefix; that is intended, and the escapes are the tell. The
    CAP itself is still measured on the rendered ``name``, because the cap
    bounds what is EMITTED.
    """
    raw = str(key)
    name = ascii(raw)
    if len(name) <= _KEY_NAME_MAX_CHARS:
        return name
    return f"{name[:_KEY_NAME_MAX_CHARS]} (truncated from {len(raw)} characters)"


def _key_tree(payload: Mapping[str, Any], *, depth: int = 0) -> str:
    """Names-only structural summary of ``payload``, for a diagnostic message.

    Sanitised and bounded (SP-2 I0, narrowing the names-only invariant): a
    venue-controlled mapping KEY is treated as a SCHEMA NAME, not as content.
    Every key name is rendered through :func:`_safe_key_name` (``ascii()``
    -escaped, quoted, capped at ``_KEY_NAME_MAX_CHARS``); nesting is bounded
    at ``_KEY_TREE_MAX_DEPTH`` (``<depth-capped>`` beyond it); a list renders
    up to ``_KEY_TREE_MAX_LIST_ROWS`` mapping rows -- including a row that is
    not the list's first element (AR-N4; a list with no mapping element at
    all keeps the plain ``key[n]`` shape) -- then ``, +N more`` counting list
    ELEMENTS beyond the cap; and any key in ``_KEY_TREE_OPAQUE_KEYS`` renders
    ``<opaque>`` at ANY depth (see the module constant's docstring).

    No VALUE is ever rendered, at any depth: a diagnostic meant to reveal a
    whole drifted shape at once must not become a second, log-line leak of
    the money or PII this module exists to protect. Member KEYS are rendered
    deliberately -- they are the evidence the tree exists to carry.

    **Marker placement rule (RV3-A13), one of three renderers sharing it:**
    every AUTHENTIC truncation marker this function's output carries (via
    :func:`_safe_key_name`) is emitted OUTSIDE the structure it truncates --
    after a key's closing quote, leaving that quoted span UNTERMINATED. A
    marker appearing INSIDE a closed quote is venue CONTENT, never a
    truncation; the discriminator is structural, not a substring match.

    Depth is keyword-only with a default so the sole call site
    (:func:`_known_keys_with_full_tree`) needs no edit; the depth bound also
    protects that caller from unbounded recursion on venue-controlled depth
    (AR-N2) -- ``_safe_key_tree`` in ``submit_chain`` is additional
    containment for SP-2's own two call sites there, not the sole one.
    """
    parts: list[str] = []
    for key in sorted(payload, key=str):
        name = _safe_key_name(key)
        value = payload[key]
        if isinstance(value, (Mapping, list)) and key in _KEY_TREE_OPAQUE_KEYS:
            parts.append(f"{name}: {{{_OPAQUE}}}")
        elif isinstance(value, Mapping):
            if depth >= _KEY_TREE_MAX_DEPTH:
                parts.append(f"{name}: {{{_DEPTH_CAPPED}}}")
            else:
                parts.append(f"{name}: {{{_key_tree(value, depth=depth + 1)}}}")
        elif isinstance(value, list):
            rows = [
                element
                for element in value[:_KEY_TREE_MAX_LIST_ROWS]
                if isinstance(element, Mapping)
            ]
            if not rows:
                parts.append(f"{name}[{len(value)}]")
            elif depth >= _KEY_TREE_MAX_DEPTH:
                parts.append(f"{name}[{len(value)}]: {{{_DEPTH_CAPPED}}}")
            else:
                rendered = ", ".join(
                    f"{{{_key_tree(row, depth=depth + 1)}}}" for row in rows
                )
                more = (
                    f", +{len(value) - _KEY_TREE_MAX_LIST_ROWS} more"
                    if len(value) > _KEY_TREE_MAX_LIST_ROWS
                    else ""
                )
                parts.append(f"{name}[{len(value)}]: {rendered}{more}")
        else:
            parts.append(name)
    return ", ".join(parts)


def _require(payload: Mapping[str, Any], key: str, *, context: str) -> Any:
    """The adapter's own required-field reader, bound to this module's error.

    Delegation, not a second implementation: ``parsing._require`` already IS
    the refusal, and a private copy here would be a second place for the
    "absent is never a default" rule to drift out of.
    """
    return _require_field(payload, key, error=ExecutionReportMappingError, context=context)


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


def _leg_price_field(
    payload: Mapping[str, Any], key: str, *, instrument: Instrument, leg: Leg, context: str
) -> Price:
    """Rev 5 (E5-1): :func:`_price_field`, then translate a NO-leg wire
    value (always YES-denominated) back to the NO instrument's own price.
    Identity on the YES leg."""
    price = _price_field(payload, key, instrument=instrument, context=context)
    if leg != "no":
        return price
    return instrument.make_price(instrument_price_for_leg(leg, price.as_decimal()))


def _leg_price_decimal_field(
    payload: Mapping[str, Any], key: str, *, instrument: Instrument, leg: Leg, context: str
) -> Decimal:
    """The ``Decimal``-returning sibling of :func:`_leg_price_field`."""
    value = _price_decimal_field(payload, key, instrument=instrument, context=context)
    if leg != "no":
        return value
    return instrument_price_for_leg(leg, value)


def _order_side_for_leg(
    order: Mapping[str, Any], *, leg: Leg, context: str, closing: bool = False
) -> OrderSide:
    """Rev 5 (E5-2): a NO-leg order is executed by the venue as a sale of
    the YES side (see ``leg_prices.VENUE_SIDE_FOR_LEG``/``VENUE_INTENT_
    FOR_LEG`` for the exact declared values); Breezy never shorts
    (``allow_short=False``), so an OPENING report's ``order_side`` is
    derived from the order's OWN leg -- always BUY -- never forwarded from
    the venue's ``side`` text. The venue's echo is cross-checked (never
    trusted as the source of truth) and any disagreement in EITHER
    direction is refused.

    INC-E2 (``POSITION_EXIT_EXECUTION_2026-09-16.md`` §3, response-side leg
    check): ``closing=True`` selects the DISJOINT closing-order echo table
    (:func:`leg_prices.assert_exit_echo_matches_leg`) instead, and the
    derived side is ``SELL`` -- every closing order Breezy sends reduces a
    long, never opens one. A closing report echoed against the OPENING
    table (or vice versa) is refused exactly like a wrong-leg echo: the two
    tables never accept each other's ``(side, intent)`` pair, so an entry
    response carrying a close echo -- or a close response carrying an entry
    echo -- raises here rather than being silently mis-attributed.
    """
    side_raw = _require(order, "side", context=context)
    intent_raw = _require(order, "intent", context=context)
    try:
        if closing:
            assert_exit_echo_matches_leg(leg, side_raw, intent_raw)
        else:
            assert_echo_matches_leg(leg, side_raw, intent_raw)
    except ValueError as exc:
        raise ExecutionReportMappingError(str(exc)) from exc
    return OrderSide.SELL if closing else OrderSide.BUY


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


def _known_keys_with_full_tree(
    payload: object,
    *,
    known: frozenset[str],
    context: str,
    full_payload: object,
) -> Mapping[str, Any]:
    """Like :func:`_assert_known_keys`, but an unknown-key refusal is
    re-raised with the FULL names-only key tree of ``full_payload`` appended
    -- see :func:`_key_tree`.

    ``full_payload`` is the WHOLE body being mapped, not necessarily
    ``payload`` itself: a nested check (e.g. ``marketMetadata``) still needs
    the OUTER object's tree, not just its own sub-object's, so a single
    strict-key failure at any nesting depth on a surface reveals every other
    drifted layer of the SAME body in one log line, rather than one nesting
    level per relaunch round.
    """
    try:
        return _assert_known_keys(payload, known=known, context=context)
    except ExecutionReportMappingError as exc:
        if isinstance(full_payload, Mapping):
            raise ExecutionReportMappingError(
                f"{exc}; full body key tree: {{{_key_tree(full_payload)}}}"
            ) from exc
        raise


def _known_order(payload: object, *, context: str) -> Mapping[str, Any]:
    """Validate an ``Order`` body, widened by both drift allowlists.

    Both the top-level check and the nested ``marketMetadata`` check route
    through :func:`_known_keys_with_full_tree`, keyed to the WHOLE order
    (``payload``) in both cases -- see that function's docstring.
    """
    order = _known_keys_with_full_tree(
        payload,
        known=_ORDER_KEYS | _ORDER_DRIFT_ALLOWED_KEYS,
        context=context,
        full_payload=payload,
    )
    metadata = order.get("marketMetadata")
    if metadata is not None:
        _known_keys_with_full_tree(
            metadata,
            known=_MARKET_METADATA_KEYS | _MARKET_METADATA_DRIFT_ALLOWED_KEYS,
            context=f"{context}.marketMetadata",
            full_payload=payload,
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

    Each row's key allowlist is ``_USER_BALANCE_KEYS`` widened by
    ``_USER_BALANCE_DRIFT_ALLOWED_KEYS`` -- six fields observed live on
    2026-09-04 plus a seventh (``bonusHold``) observed live on 2026-09-19
    that the pinned SDK snapshot does not declare (see
    ``docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-04.md``
    and
    ``docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-19.md``).
    They are accepted DECLARED-BUT-UNREAD, never merged into the snapshot-
    matched set itself, so the strict refusal below stays strict for any
    field beyond those seven.

    ``currentBalance`` and ``buyingPower`` are QUANTIZED to ``USD.precision``
    with ``ROUND_DOWN`` rather than refused when they carry sub-cent
    precision (peer-reviewed 2026-09-04, second live-launch incident: the
    venue began reporting sub-cent balances). These two fields are Nautilus
    portfolio bookkeeping, not an observation, a price, or a settlement
    number -- Breezy's own sizing gate never reads them -- so A13's "a
    spanning interval is refused, never rounded" does not apply here, and
    ``ROUND_DOWN`` never overstates equity or spending power. See
    ``docs/evidence/grok_live_small_spec_rev2_2026-09-04.md:31,67``. Every
    other money and price field in this module (``avg_px`` included) stays
    strict-refuse via ``_assert_representable``/``_assert_price_representable``
    -- untouched by this carve-out.
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
    non_exact_count = 0
    balances: list[AccountBalance] = []
    for index, entry in enumerate(entries):
        balance, entry_non_exact_count = _parse_account_balance(
            entry, context=f"{context} balances[{index}]"
        )
        balances.append(balance)
        non_exact_count += entry_non_exact_count
    if non_exact_count:
        logger.info(
            "account balances response: %d balance field(s) carried non-exact "
            "precision and were quantized down to the instrument precision",
            non_exact_count,
        )
    return tuple(balances)


def _quantize_balance_field(value: Decimal, *, precision: int) -> tuple[Decimal, bool]:
    """Quantize a balance field toward zero; report whether it was non-exact."""
    quantum = Decimal(1).scaleb(-precision)
    quantised = value.quantize(quantum, rounding=ROUND_DOWN)
    return quantised, quantised != value


def _quantize_commission_field(
    value: Decimal,
    *,
    precision: int = USD.precision,
    field: str = "commissionNotionalCollected",
) -> Decimal:
    """Quantize a fill commission with the venue's banker's rule.

    The input is an untrusted venue decimal: ``InvalidOperation`` (extreme
    exponent, more digits than the context precision) is mapped into
    ``ExecutionReportMappingError`` so it cannot escape the classifier.
    """
    quantum = Decimal(1).scaleb(-precision)
    try:
        return value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        raise ExecutionReportMappingError(
            f"Field {field!r} cannot be represented at precision {precision}"
        ) from None


def _usd_commission(value: Decimal, *, field: str, raw: str) -> Money:
    """Build fill ``Money`` after explicit bankers rounding, never via ``Money``."""
    booked = _quantize_commission_field(value, precision=USD.precision, field=field)
    try:
        raw_decimal = Decimal(raw)
        nonzero_raw = raw_decimal != 0
    except InvalidOperation:
        nonzero_raw = True
    changed = booked != value
    if booked == 0 and nonzero_raw:
        logger.warning(
            "fill commission raw=%s booked=%s; non-zero venue fee rounded to zero",
            raw,
            format(booked, ".2f"),
        )
    elif changed:
        logger.info("fill commission raw=%s booked=%s", raw, format(booked, ".2f"))
    representable = _assert_representable(
        booked, precision=USD.precision, field=field, error=ExecutionReportMappingError
    )
    return Money(representable, USD)


def _parse_account_balance(
    payload: object, *, context: str
) -> tuple[AccountBalance, int]:
    balance = _assert_known_keys(
        payload,
        known=_USER_BALANCE_KEYS | _USER_BALANCE_DRIFT_ALLOWED_KEYS,
        context=context,
    )

    currency = balance.get("currency")
    if currency != QUOTE_CURRENCY_CODE:
        raise ExecutionReportMappingError(
            f"{context} is denominated in {currency!r}, not {QUOTE_CURRENCY_CODE!r}; "
            "refusing to treat it as a USD balance"
        )

    raw_total = _to_decimal(
        _require(balance, "currentBalance", context=context),
        field=f"{context}.currentBalance",
        error=ExecutionReportMappingError,
    )
    raw_free = _to_decimal(
        _require(balance, "buyingPower", context=context),
        field=f"{context}.buyingPower",
        error=ExecutionReportMappingError,
    )
    total, total_non_exact = _quantize_balance_field(raw_total, precision=USD.precision)
    free, free_non_exact = _quantize_balance_field(raw_free, precision=USD.precision)
    non_exact_count = int(total_non_exact) + int(free_non_exact)

    locked = total - free
    if locked < 0:
        raise ExecutionReportMappingError(
            f"{context} reports 'buyingPower' above 'currentBalance', which would "
            "imply a negative encumbrance; the shape has never been observed and is "
            "refused rather than clamped. The two amounts are deliberately NOT "
            "named: a private balance is the operator's buying power, and this "
            "message is what R-4 attaches a logger to"
        )

    return (
        AccountBalance(
            total=_usd_money(total, field=f"{context}.currentBalance"),
            locked=_usd_money(locked, field=f"{context}.locked"),
            free=_usd_money(free, field=f"{context}.buyingPower"),
        ),
        non_exact_count,
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
    closing: bool = False,
) -> OrderStatusReport:
    """Map an ``Order`` (``types/orders.py:70-92``) to the native report.

    ``ts_accepted`` and ``ts_last`` are both ``createTime``. ``Order`` also
    carries ``insertTime``, but the snapshot defines neither field's semantics,
    and promoting an undefined timestamp to "the last order status change"
    would put an invented event time into reconciliation. Using the one field
    whose meaning is unambiguous states less, and states nothing false.

    ``closing`` (INC-E2d, mirrors :func:`parse_fill_report`'s own parameter
    exactly, default ``False`` -- byte-unchanged for every existing entry-path
    caller): forwarded to :func:`_order_side_for_leg` so a closing (exit)
    order's GET-resolved status report is checked against the disjoint exit
    echo table and reports ``order_side=OrderSide.SELL``, instead of the
    entry-only BUY table always refusing it. Without this, the with-id
    AMBIGUOUS resolver (``exec/client.py``'s ``_resolve_ambiguous_intents``)
    has no way to ever resolve an exit order's GET response: it always
    applied the entry echo table, so a genuinely-filled exit stayed
    ``mapping_error``/AMBIGUOUS forever, leaving the account-wide
    ``SubmitIntentLatch`` OPEN indefinitely.
    """
    context = "order status report"
    order = _known_order(payload, context=context)
    _assert_market_matches(
        order.get("marketSlug"), instrument=instrument, context=context
    )
    leg = leg_of(instrument.id)
    order_side = _order_side_for_leg(order, leg=leg, context=context, closing=closing)

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
        order_side=order_side,
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
        # Rev 5 (E5-1): translated via `leg`, identity on the YES leg.
        price=(
            _leg_price_field(order, "price", instrument=instrument, leg=leg, context=context)
            if order.get("price") is not None
            else None
        ),
        # ``avg_px`` is a PRICE to Nautilus, not a bare amount: reconciliation
        # feeds it to ``instrument.make_price()`` and books the result as a
        # fill price. It therefore runs the identical guard ``price`` does.
        avg_px=(
            _leg_price_decimal_field(
                order, "avgPx", instrument=instrument, leg=leg, context=context
            )
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
    closing: bool = False,
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

    The execution-type refusal below names the offending value through this
    module's value-safe renderer (:func:`_name_value`), not raw ``!r``,
    because this message is DURABLE: SP-2's I3 persists it into the resolver
    context store, and ``_require`` permits ``type`` to be any JSON value, so
    an unbounded or nested one must never be echoed whole (SEC-H1).

    ``closing`` (INC-E2, default ``False`` -- byte-unchanged for every
    existing entry-path caller): forwarded to :func:`_order_side_for_leg`
    so a closing order's response is checked against the disjoint exit echo
    table and reports ``order_side=OrderSide.SELL``, instead of the
    entry-only BUY table always refusing it.
    """
    context = "fill report"
    execution = _known_keys_with_full_tree(
        payload,
        known=_EXECUTION_KEYS | _EXECUTION_DRIFT_ALLOWED_KEYS,
        context=context,
        full_payload=payload,
    )

    execution_type = _require(execution, "type", context=context)
    # I6 (CRITICAL, same class as `submit_chain._fill_type_executions`):
    # `execution_type` is a bare venue-controlled JSON value, so a direct
    # caller of this function (not only the create-path pre-filter, which
    # normally screens `type` first) could hand it a dict/list. `isinstance`
    # is checked FIRST so the frozenset membership test never sees an
    # unhashable value.
    if not (isinstance(execution_type, str) and execution_type in _FILL_EXECUTION_TYPES):
        raise ExecutionReportMappingError(
            f"{context} carries execution type {_name_value(execution_type)}, which is not "
            f"one of ({', '.join(sorted(_FILL_EXECUTION_TYPES))}); refusing to report a "
            "trade the venue did not report"
        )

    order_context = f"{context}.order"
    order = _known_order(_require(execution, "order", context=context), context=order_context)
    _assert_market_matches(
        order.get("marketSlug"), instrument=instrument, context=order_context
    )
    leg = leg_of(instrument.id)
    order_side = _order_side_for_leg(order, leg=leg, context=order_context, closing=closing)

    _assert_taker_fill(execution, context=context)

    commission_payload = _require(
        execution, "commissionNotionalCollected", context=context
    )
    commission_dec = _parse_amount(
        commission_payload,
        field=f"{context}.commissionNotionalCollected",
        error=ExecutionReportMappingError,
    )
    raw_value = (
        commission_payload.get("value")
        if isinstance(commission_payload, Mapping)
        else commission_payload
    )
    if isinstance(raw_value, bool) or not isinstance(
        raw_value, (str, int, float, Decimal)
    ):
        raise ExecutionReportMappingError(
            f"{context} field 'commissionNotionalCollected.value' must be a "
            f"number or numeric string, got {type(raw_value).__name__}"
        )

    return FillReport(
        account_id=account_id,
        instrument_id=instrument.id,
        venue_order_id=VenueOrderId(_require_text(order, "id", context=order_context)),
        trade_id=TradeId(_require_text(execution, "tradeId", context=context)),
        order_side=order_side,
        last_qty=_quantity_field(
            execution, "lastShares", instrument=instrument, context=context
        ),
        last_px=_leg_price_field(
            execution, "lastPx", instrument=instrument, leg=leg, context=context
        ),
        commission=_usd_commission(
            commission_dec,
            field=f"{context}.commissionNotionalCollected",
            raw=str(raw_value),
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

    ``leg`` is the OUTCOME the exposure belongs to -- ``"yes"`` or ``"no"`` --
    determined by :func:`_position_leg`. This module performs no I/O
    (module docstring) and therefore never resolves an actual NO-leg
    ``Instrument``: ``report.instrument_id`` is left on the YES id it was
    given (unchanged from before this field existed), and a caller that
    needs the NO-leg exposure attached to the real NO instrument -- R-4's
    :meth:`~breezy.adapters.polymarket_us.exec.client.
    PolymarketUSExecutionClient._map_position` -- reads ``leg`` and performs
    that resolution itself, the same way it already resolves the YES
    instrument from the slug.
    """

    report: PositionStatusReport
    expired: bool
    leg: Leg


def _position_leg(*, net: Decimal, metadata: Mapping[str, Any] | None, context: str) -> Leg:
    """Which leg -- YES or NO -- a position's exposure belongs to.

    Ruling: ``docs/evidence/RULING_no_side_position_shape_2026-09-16.md``. A
    venue position whose ``marketMetadata.outcome`` is ``"No"`` is a holding
    of the NO leg -- Breezy is long-only, and a NO holding is a LONG on the
    NO-leg instrument, never a SHORT on the YES one. An absent ``outcome``
    (or an absent ``marketMetadata`` block entirely -- it is optional, see
    the module docstring) falls back to the sign of ``netPosition``:
    negative is a NO holding, non-negative is a YES holding -- this is the
    pre-existing, still-correct reading for every payload this module has
    ever been tested against, none of which carried ``outcome``.

    A present ``outcome`` that CONTRADICTS the sign -- ``"No"`` with a
    non-negative ``netPosition``, or ``"Yes"`` with a negative one -- is
    refused rather than guessed: two venue-supplied signals that disagree
    are a contradiction, not a preference, and neither is picked over the
    other. An ``outcome`` outside ``{"Yes", "No"}`` is refused the same way
    -- this module refuses outside its declared shapes rather than
    extrapolating (module docstring).
    """
    outcome = metadata.get("outcome") if metadata is not None else None
    if outcome is not None and outcome not in ("Yes", "No"):
        raise ExecutionReportMappingError(
            f"{context}.marketMetadata carries outcome {outcome!r}, neither "
            "'Yes' nor 'No'; refusing to guess which leg the exposure belongs to"
        )
    if outcome == "No":
        if net > 0:
            raise ExecutionReportMappingError(
                f"{context} declares marketMetadata.outcome='No' but a positive "
                f"netPosition ({net}); a NO holding cannot carry a positive "
                "netPosition and the contradiction is refused rather than guessed"
            )
        return "no"
    if outcome == "Yes":
        if net < 0:
            raise ExecutionReportMappingError(
                f"{context} declares marketMetadata.outcome='Yes' but a negative "
                f"netPosition ({net}); a YES holding cannot carry a negative "
                "netPosition and the contradiction is refused rather than guessed"
            )
        return "yes"
    return "no" if net < 0 else "yes"


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
    position = _known_keys_with_full_tree(
        payload,
        known=_USER_POSITION_KEYS | _USER_POSITION_DRIFT_ALLOWED_KEYS,
        context=context,
        full_payload=payload,
    )

    _assert_market_matches(market_slug, instrument=instrument, context=context)

    metadata = position.get("marketMetadata")
    if metadata is not None:
        metadata_context = f"{context}.marketMetadata"
        _known_keys_with_full_tree(
            metadata,
            known=_MARKET_METADATA_KEYS | _MARKET_METADATA_DRIFT_ALLOWED_KEYS,
            context=metadata_context,
            full_payload=payload,
        )
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
    leg = _position_leg(net=net, metadata=metadata, context=context)
    # A NO holding's exposure is LONG on the NO leg, never SHORT on the YES
    # one -- `leg` above already carries that distinction, so the only
    # `position_side` this function ever reports again is LONG (net != 0) or
    # FLAT (net == 0). See `_position_leg` and the ruling it cites.
    side = PositionSide.FLAT if net == 0 else PositionSide.LONG

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
        leg=leg,
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


# ---------------------------------------------------------------------------
# Open orders -> OpenOrderRecord (RESTING_BID_HUNT Rev 2 section 4.3)
# ---------------------------------------------------------------------------

#: Upper bound on the unknown-key names one :class:`OpenOrderRecord` carries.
#: The record is a diagnostic, not a schema: a venue that adds fifty fields
#: must not turn one enumeration row into fifty log tokens.
OPEN_ORDER_UNKNOWN_KEYS_MAX: Final[int] = 16

#: ``GetOpenOrdersResponse`` (``types/orders.py:171-174``): one declared key.
#: ``eof`` is NOT declared for this response; it is tolerated as a known name
#: only so that, should the venue paginate this surface later, a non-terminal
#: page is REFUSED (below) instead of being recorded as an unknown key.
_OPEN_ORDERS_RESPONSE_KEYS: Final[frozenset[str]] = frozenset({"orders", "eof"})

#: The keys :func:`parse_open_orders` READS off an ``Order``. Everything else
#: the snapshot declares (``_ORDER_KEYS``) or has been seen live
#: (``_ORDER_DRIFT_ALLOWED_KEYS``) is accepted silently; anything beyond BOTH
#: is recorded as unknown -- bounded, never fatal.
_OPEN_ORDER_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "id",
    "marketSlug",
    "state",
    "side",
    "quantity",
    "cumQuantity",
    "tif",
    "createTime",
)


class OpenOrderRecord(NamedTuple):
    """One open order as the venue enumerates it -- instrument-FREE.

    NOT a parallel report class: the native ``OrderStatusReport`` needs an
    ``Instrument`` and an account, and the boot never-arm gate must be able
    to enumerate an order on a market this node never configured (a foreign
    slug is exactly the open order it cannot account for). So this is the
    minimal venue-shape record the gate and the durable evidence need, and
    ``parse_order_status_report`` remains the ONLY route to a native report.

    Direction vocabulary is deliberately absent: ``side`` is the venue's
    ``OrderSide`` member; ``intent``/outcome fields are declared but unread,
    exactly as in every other mapper in this module.
    """

    venue_order_id: str
    market_slug: str
    state: str
    side: str
    quantity: Decimal
    cum_quantity: Decimal
    price: Decimal | None
    tif: str
    create_time: str
    #: Sanitised names (``_safe_key_name``) of keys neither the snapshot nor
    #: the live drift allowlist declares -- on the order row AND the response
    #: envelope -- sorted, capped at :data:`OPEN_ORDER_UNKNOWN_KEYS_MAX`.
    unknown_keys: tuple[str, ...]


def _unknown_key_names(payload: Mapping[str, Any], *, known: frozenset[str]) -> list[str]:
    return [_safe_key_name(key) for key in payload if key not in known]


def _open_order_record(
    payload: object, *, context: str, envelope_unknown: list[str]
) -> OpenOrderRecord:
    if not isinstance(payload, Mapping):
        raise ExecutionReportMappingError(
            f"{context} must be a JSON object, got {type(payload).__name__}"
        )
    for key in _OPEN_ORDER_REQUIRED_KEYS:
        if key not in payload or payload[key] is None:
            raise ExecutionReportMappingError(f"{context} is missing required field {key!r}")

    venue_order_id = _require_text(payload, "id", context=context)
    market_slug = _require_text(payload, "marketSlug", context=context)
    create_time = _require_text(payload, "createTime", context=context)
    # Membership only -- the native enums are not needed for an enumeration,
    # but an undeclared member is still refused rather than carried.
    state = _require_text(payload, "state", context=context)
    if state not in ORDER_STATE_TO_ORDER_STATUS:
        raise ExecutionReportMappingError(f"{context}.state {state!r} is not a declared OrderState")
    side = _require_text(payload, "side", context=context)
    if side not in _ORDER_SIDES:
        raise ExecutionReportMappingError(f"{context}.side {side!r} is not a declared OrderSide")
    tif = _require_text(payload, "tif", context=context)
    if tif not in _TIME_IN_FORCE:
        raise ExecutionReportMappingError(f"{context}.tif {tif!r} is not a declared TimeInForce")

    quantity = _to_decimal(
        payload["quantity"], field=f"{context}.quantity", error=ExecutionReportMappingError
    )
    cum_quantity = _to_decimal(
        payload["cumQuantity"], field=f"{context}.cumQuantity", error=ExecutionReportMappingError
    )
    if quantity <= 0:
        raise ExecutionReportMappingError(f"{context}.quantity must be positive, got {quantity}")
    if cum_quantity < 0 or cum_quantity > quantity:
        raise ExecutionReportMappingError(
            f"{context}.cumQuantity {cum_quantity} is outside [0, quantity={quantity}]"
        )

    price: Decimal | None = None
    if payload.get("price") is not None:
        price = _amount_field(payload, "price", context=context)
        if not (Decimal(0) < price < Decimal(1)):
            raise ExecutionReportMappingError(
                f"{context}.price {price} is outside the open interval (0, 1)"
            )

    unknown = sorted(
        set(envelope_unknown)
        | set(_unknown_key_names(payload, known=_ORDER_KEYS | _ORDER_DRIFT_ALLOWED_KEYS))
    )
    return OpenOrderRecord(
        venue_order_id=venue_order_id,
        market_slug=market_slug,
        state=state,
        side=side,
        quantity=quantity,
        cum_quantity=cum_quantity,
        price=price,
        tif=tif,
        create_time=create_time,
        unknown_keys=tuple(unknown[:OPEN_ORDER_UNKNOWN_KEYS_MAX]),
    )


def parse_open_orders(payload: object) -> tuple[OpenOrderRecord, ...]:
    """Map a ``GetOpenOrdersResponse`` to :class:`OpenOrderRecord` rows.

    Drift-TOLERANT on purpose, and the only mapper here that is: the boot
    never-arm gate consumes this to decide whether ANY order is open, so an
    order whose shape moved must still be enumerable (its unknown keys are
    recorded, bounded). Strict everywhere that matters for the decision: a
    missing ``orders`` list, a non-list, a non-object row, an undeclared
    enum member, a negative/inconsistent quantity, a non-USD or out-of-range
    price, or a missing required field REFUSES THE WHOLE READ -- the caller
    records the read as refused and never arms, rather than acting on a
    partial book. An ``eof`` key that is present and not ``True`` is refused
    for the same reason ``_declared_positions`` refuses it: page 1 is not
    the book.
    """
    if not isinstance(payload, Mapping):
        raise ExecutionReportMappingError(
            f"open orders response must be a JSON object, got {type(payload).__name__}"
        )
    orders = payload.get("orders")
    if orders is None:
        raise ExecutionReportMappingError(
            "the venue open-orders response declares no 'orders' key; an absent "
            "list is not an empty list"
        )
    if not isinstance(orders, list):
        raise ExecutionReportMappingError(
            f"the venue open-orders response carries a {type(orders).__name__} under "
            "'orders' where a list was declared"
        )
    if "eof" in payload and payload["eof"] is not True:
        raise ExecutionReportMappingError(
            "the venue open-orders response is marked eof!=true; page 1 is not the book"
        )
    envelope_unknown = _unknown_key_names(payload, known=_OPEN_ORDERS_RESPONSE_KEYS)
    return tuple(
        _open_order_record(row, context=f"open order [{index}]", envelope_unknown=envelope_unknown)
        for index, row in enumerate(orders)
    )
