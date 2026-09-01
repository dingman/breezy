"""Venue JSON -> Nautilus domain objects, with validation at the trust boundary.

Plan revision 2 section 6 ``parsing.py``; build order Step 7.

Three rules govern every function here.

**1. Decimal only.** No ``float(`` call appears in this module (asserted by an
AST test, per ``BUILD_PLAN:66``). ``Price`` and ``Quantity`` are built through
``from_str`` on an exactly-formatted ``Decimal``, never from a binary float.
JSON numbers that arrive as Python floats -- the venue sends
``orderPriceMinTickSize`` and ``minimumTradeQty`` as bare JSON numbers -- are
converted via ``Decimal(str(value))``, which uses the shortest round-tripping
repr and is exact for the tick sizes the venue publishes.

**2. Validate before constructing.** ``Price``/``Quantity`` are Rust-backed and
``TRADING_ENABLEMENT_FINDINGS.md`` section E records that the layer can abort
the process rather than raise on out-of-domain input. Every value is therefore
range-checked and precision-checked in Python first. A value that would need
rounding to fit the instrument's precision is REFUSED, not rounded: silent
rounding of a venue price is a wrong number that survives into settlement.

**3. Never default a missing field.** A missing or malformed field raises
:class:`~breezy.adapters.polymarket_us.errors.VenuePayloadError` (or
:class:`~breezy.adapters.polymarket_us.errors.InstrumentDefinitionError` for
instrument definitions). There is no code path that substitutes a constant for
a value the venue did not send.

**Fees fail closed through a native fee-model extension.**
The market payload's ``feeCoefficient`` is the ``theta`` of
``fee = theta * C * p * (1 - p)`` -- a coefficient on a concave function of
price, not a flat rate on notional, which is what Nautilus's
``maker_fee``/``taker_fee`` mean. A valid per-market coefficient is recorded
verbatim in ``info`` under :data:`FEE_COEFFICIENT_KEY` and marks the fee
schedule :data:`FEE_SCHEDULE_STATUS_KNOWN`; absence keeps the schedule
:data:`FEE_SCHEDULE_STATUS_UNKNOWN`, and an unusable value aborts the load.

**DECISION (a): the flat fee fields carry ``theta``, and are made UNREACHABLE
rather than argued safe.**
The exact fee is carried by
:class:`~breezy.adapters.polymarket_us.fees.PolymarketUSFeeModel`. The
question this docstring answers is what the two FLAT fields should hold, given
that generic Nautilus machinery reads them and nothing in Nautilus can stop a
future caller from doing so.

Writing ``theta`` there is not a guess about the VALUE. It is the meaning
Nautilus itself assigns to an instrument fee rate on a probability-priced
binary: ``nautilus_pyo3.ProbabilityPriceFeeModel`` computes
``qty * rate * p * (1 - p)`` "using the instrument's maker or taker fee rate".
So the field follows the framework's own convention for this instrument class.

**What the flat read actually costs, stated accurately.** A generic
``MakerTakerFeeModel`` computes ``notional * taker_fee``, i.e.
``theta * C * p``. The venue charges ``theta * C * p * (1 - p)``. The absolute
difference is ``theta * C * p^2``, which is ``>= 0`` everywhere on ``[0, 1]``.

That non-negativity is true and it defends the WRONG property. The venue fee
is **symmetric about ``p = 0.50``**; the flat read is **monotone in ``p``**.
The RELATIVE overstatement is ``1 / (1 - p)``, which is **unbounded as
``p -> 1``**. At ``theta = 0.06``, ``C = 100``:

===================  ===============  ==============  =====
trade                true venue fee   flat-field fee  ratio
===================  ===============  ==============  =====
YES @ ``p = 0.90``   $0.54            $5.40           10x
NO  @ ``p = 0.10``   $0.54            $0.60           1.11x
===================  ===============  ==============  =====

The venue charges those two IDENTICALLY. The flat read charges one 9x more
than the other, so it does not haircut an edge gate -- it TILTS it toward the
cheap side of every book. For a weather bot, confident forecasts land exactly
in the ``p -> 1`` region where the distortion is worst. Calling this
"conservative" was a real defect in an earlier revision of this docstring.

**Zero is not the alternative.** ``BinaryOption`` defaults these fields to
``Decimal(0)`` (``model/instruments/binary_option.pyx:148-149``): a real,
typed, usable zero that reads as a FREE venue. Now that a parsed coefficient
marks the schedule ``KNOWN``, :func:`assert_fee_schedule_known` OPENS, so a
zero here would be charged as nothing at all -- understating, which is
strictly worse than overstating. **Neither flat value is safe on its own.**

``theta`` is therefore kept only so that a circumvention errs in the
overstating direction. The actual defence is barrier F2 in
``tests/unit/test_polymarket_us_fee_guard.py``, which fails the suite for any
module under ``src/`` or ``scripts/`` that constructs a backtest venue without
passing ``fee_model=PolymarketUSFeeModel()`` -- because
``BacktestEngine.add_venue`` otherwise defaults to ``MakerTakerFeeModel``
(``backtest/engine.pyx:643-644``). Barrier F1 independently forbids reading
either field as truth.

**The ``info`` marker alone is NOT enough, and saying otherwise was a real
defect.** Whenever the venue omits ``feeCoefficient`` the schedule stays
``UNKNOWN`` and ``BinaryOption`` defaults both fee fields via
``maker_fee or Decimal(0)`` (``model/instruments/binary_option.pyx:148-149``),
putting a genuine, typed ``Decimal(0)`` in exactly the fields generic Nautilus
machinery reads -- ``MakerTakerFeeModel.get_commission`` multiplies notional
by ``instrument.taker_fee`` and by nothing else
(``backtest/models/fee.pyx:96-99``). A zero there is indistinguishable from a
free venue, while the real taker fee is $1.50 per 100 contracts at p=0.50.

Instruments must stay loadable (the read-only slice needs them to receive
quotes), so the enforcement is a guard plus
:class:`breezy.adapters.polymarket_us.fees.PolymarketUSFeeModel`, rather than a
flat fee. :func:`assert_fee_schedule_known` raises unless ``info`` says the
schedule is ``KNOWN``, and ``tests/unit/test_polymarket_us_fee_guard.py``
(barrier F1) fails the suite if any venue-touching module reads a fee field
without calling it.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import (
    BookOrder,
    InstrumentClose,
    InstrumentStatus,
    MarkPriceUpdate,
    OrderBookDepth10,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.enums import (
    AggressorSide,
    AssetClass,
    InstrumentCloseType,
    MarketStatusAction,
    OrderSide,
)
from nautilus_trader.model.identifiers import Symbol, TradeId, Venue
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.errors import (
    FeeScheduleUnknownError,
    InstrumentDefinitionError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    REGISTRY_VENUE_KEY,
    assert_bounds_cross_checked,
    assert_valid_slug,
    parse_weather_slug,
    slug_to_instrument_id,
)
from breezy.adapters.polymarket_us.tape_records import VenueSettlementSnapshot
from breezy.domain.weather_bucket_facts import (
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
    WEATHER_FACTS_STATUS_UNKNOWN,
)
from breezy.registry.sites import SiteNotFoundError, SiteRegistry, default_registry

__all__ = [
    "CLIMATE_CATEGORY",
    "DEPTH10_LEVELS",
    "EXPIRED_MARKET_STATES",
    "FEE_COEFFICIENT_KEY",
    "FEE_SCHEDULE_STATUS_KEY",
    "FEE_SCHEDULE_STATUS_KNOWN",
    "FEE_SCHEDULE_STATUS_UNKNOWN",
    "OBSERVED_SETTLEMENT_METHODS",
    "QUOTE_CURRENCY_CODE",
    "TERMINAL_SETTLEMENT_METHOD",
    "TRADE_CONTAINER_KEY",
    "assert_fee_schedule_known",
    "depth_levels_dropped",
    "parse_binary_option",
    "parse_book_levels",
    "parse_book_top",
    "parse_instrument_close",
    "parse_instrument_status",
    "parse_mark_price",
    "parse_order_book_depth10",
    "parse_quote_tick",
    "parse_rfc3339_nanos",
    "parse_settlement_snapshot",
    "parse_trade_tick",
    "venue_market_state",
    "venue_settlement_method",
]

#: Levels per side carried by ``OrderBookDepth10``. Fixed by Nautilus
#: (``model/data.pyx:3491-3495``), not a Breezy choice.
DEPTH10_LEVELS: int = 10

#: The frame container holding an executed print.
#:
#: UNRESOLVED venue fact: no trade frame has been captured. The key is the one
#: ``data._classify_frame`` already recognises, and every field inside is
#: REQUIRED -- a frame that does not match raises and is dropped and counted by
#: the caller, so a wrong guess degrades to "no trades recorded", never to a
#: fabricated print. Confirmation is a live-probe question for
#: ``polymarket-us-discovery``.
TRADE_CONTAINER_KEY: str = "trade"

#: Venue ``state`` values that mean the contract has reached a terminal
#: settlement, so ``settlementPx`` is the final value rather than a daily mark.
#: ``MARKET_STATE_EXPIRED`` is observed in the committed capture
#: ``book_closed_15806.json``; the others are defensive and, if they never
#: occur, cost nothing. A state NOT listed here never produces an
#: ``InstrumentClose``.
EXPIRED_MARKET_STATES: frozenset[str] = frozenset(
    {"MARKET_STATE_EXPIRED", "MARKET_STATE_SETTLED", "MARKET_STATE_CLOSED"}
)

#: The ONLY ``settlementPriceCalculationMethod`` value that may create a
#: TERMINAL settlement record.
#:
#: Observed in ``book_closed_15806.json`` on an expired market whose
#: ``settlementPx`` is ``1.0000`` and whose ``closePx`` is absent. The live
#: capture carries ``..._EVENT_TIER_2`` with ``settlementPx == closePx``, i.e.
#: a daily mark.
#:
#: Gating on ``state`` alone would be one frame away from permanent corruption:
#: if the venue flips ``state`` to EXPIRED before republishing a
#: terminally-computed price, a mark-derived number becomes the settlement
#: truth that REQ-SETTLE-04/08 and everything trained on it treat as ground
#: truth -- in an archive that can never be re-recorded.
TERMINAL_SETTLEMENT_METHOD: str = "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1"

#: Every method value ever observed. The enum is otherwise UNRESOLVED, and a
#: value outside this set is NEVER treated as terminal -- a third value might
#: be a new terminal method or a new intraday one, and guessing which is
#: guessing about settlement truth. Recorded verbatim either way, so the
#: judgement can be re-derived later rather than lost.
OBSERVED_SETTLEMENT_METHODS: frozenset[str] = frozenset(
    {
        TERMINAL_SETTLEMENT_METHOD,
        "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2",
    }
)

#: Venue taker-side spellings mapped onto Nautilus's aggressor side. UNRESOLVED:
#: no trade frame has been captured, so an unrecognised token maps to
#: ``NO_AGGRESSOR`` rather than to a guessed direction.
_TAKER_SIDES: dict[str, AggressorSide] = {
    "SIDE_BUY": AggressorSide.BUYER,
    "SIDE_SELL": AggressorSide.SELLER,
    "BUY": AggressorSide.BUYER,
    "SELL": AggressorSide.SELLER,
}

#: The only settlement currency Polymarket.us (a fiat DCM) is documented to use.
#: A payload naming anything else is refused rather than coerced.
QUOTE_CURRENCY_CODE: str = "USD"

#: ``info`` key holding the market's own verbatim ``theta``, as a string.
#: Read by :class:`~breezy.adapters.polymarket_us.fees.PolymarketUSFeeModel`,
#: which re-validates it rather than trusting the status marker alone.
FEE_COEFFICIENT_KEY: str = "fee_coefficient"

#: ``info`` key carrying the fee-schedule resolution state. Barrier F1 hangs
#: on this constant: :func:`assert_fee_schedule_known` reads it and every
#: fee-consuming path must call that guard first.
FEE_SCHEDULE_STATUS_KEY: str = "fee_schedule_status"

#: Recorded in ``BinaryOption.info`` so no downstream consumer can mistake the
#: absence of a fee rate for a zero fee rate. Enforced by
#: :func:`assert_fee_schedule_known`, not by convention.
FEE_SCHEDULE_STATUS_UNKNOWN: str = "UNKNOWN"

#: The ONLY value that unlocks a fee-consuming path. It is written only after a
#: finite per-market ``feeCoefficient`` in ``[0, 1]`` is parsed from the venue
#: payload.
FEE_SCHEDULE_STATUS_KNOWN: str = "KNOWN"

#: The venue's own label for a weather market. Used to decide when an
#: unparseable slug is fatal rather than merely unrecognised.
CLIMATE_CATEGORY: str = "climate"

_PRICE_MIN: Decimal = Decimal(0)
_PRICE_MAX: Decimal = Decimal(1)
_NANOS_PER_SECOND: int = 1_000_000_000
_FRACTION_DIGITS: int = 9

_RFC3339_RE: re.Pattern[str] = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?Z$"
)


# ---------------------------------------------------------------------------
# Fee fail-closed guard
# ---------------------------------------------------------------------------


def assert_fee_schedule_known(instrument: Instrument) -> None:
    """Refuse to proceed while ``instrument``'s fee schedule is unresolved.

    Every path that reads ``maker_fee``/``taker_fee`` -- a fee model, a PnL
    calculation, any future sizing or edge computation -- must call this
    first. Barrier F1 in ``tests/unit/test_polymarket_us_fee_guard.py`` fails
    the suite for any venue-touching module under ``src/`` or ``scripts/``
    that reads either field without calling it.

    Fails closed on ABSENCE as well as on ``UNKNOWN``: an instrument with no
    ``info``, or with the marker stripped, is treated as unresolved. The
    opposite default would make the guard useless against exactly the refactor
    it exists to catch.

    Raises
    ------
    FeeScheduleUnknownError
        Unless ``instrument.info[FEE_SCHEDULE_STATUS_KEY]`` is
        :data:`FEE_SCHEDULE_STATUS_KNOWN`.
    """
    info = getattr(instrument, "info", None)
    status = info.get(FEE_SCHEDULE_STATUS_KEY) if isinstance(info, Mapping) else None
    if status == FEE_SCHEDULE_STATUS_KNOWN:
        return
    identifier = getattr(instrument, "id", None)
    raise FeeScheduleUnknownError(
        f"Refusing a fee-dependent computation for {identifier}: the Polymarket.us "
        f"fee schedule is {status or FEE_SCHEDULE_STATUS_UNKNOWN!s}. Its "
        "'maker_fee' and 'taker_fee' fields hold a placeholder Decimal(0) supplied "
        "by BinaryOption's own default, NOT a verified zero-fee schedule; the venue "
        "charges theta * C * p * (1 - p), with theta read from the market payload. "
        "Resolve the schedule and mark it "
        f"{FEE_SCHEDULE_STATUS_KNOWN!r} before charging or netting fees."
    )


# ---------------------------------------------------------------------------
# Primitive readers
# ---------------------------------------------------------------------------


def _require_mapping(payload: object, key: str, *, context: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise VenuePayloadError(f"{context}: expected a JSON object, got {type(payload).__name__}")
    if key not in payload:
        raise VenuePayloadError(f"{context}: required key {key!r} is absent")
    value = payload[key]
    if not isinstance(value, Mapping):
        raise VenuePayloadError(
            f"{context}: key {key!r} must hold a JSON object, got {type(value).__name__}"
        )
    return value


def _require(payload: Mapping[str, Any], key: str, *, error: type[VenuePayloadError]) -> Any:
    if key not in payload or payload[key] is None:
        raise error(f"Polymarket.us payload is missing required field {key!r}")
    return payload[key]


def _to_decimal(value: object, *, field: str, error: type[VenuePayloadError]) -> Decimal:
    """Convert a venue scalar to ``Decimal`` without ever touching binary float math."""
    if isinstance(value, bool):
        raise error(f"Field {field!r} must be a number or numeric string, got a bool")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, (str, float)):
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise error(
                f"Field {field!r} is not a valid decimal number "
                f"({len(str(value))} characters; content withheld)"
            ) from None
    else:
        raise error(
            f"Field {field!r} must be a number or numeric string, got {type(value).__name__}"
        )
    if not decimal_value.is_finite():
        raise error(f"Field {field!r} is not a finite decimal number")
    return decimal_value


def _precision_of(value: Decimal, *, field: str, error: type[VenuePayloadError]) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):  # pragma: no cover - guarded by is_finite above
        raise error(f"Field {field!r} has no finite decimal exponent")
    return max(0, -exponent)


def _assert_representable(
    value: Decimal, *, precision: int, field: str, error: type[VenuePayloadError]
) -> Decimal:
    """Return ``value`` quantised to ``precision``, or raise if that loses information.

    Trailing zeros are fine (``0.5300`` at precision 2 is exactly ``0.53``);
    a significant digit below the instrument's increment is not.
    """
    quantum = Decimal(1).scaleb(-precision)
    try:
        quantised = value.quantize(quantum)
    except InvalidOperation:
        raise error(f"Field {field!r} cannot be represented at precision {precision}") from None
    if quantised != value:
        raise error(
            f"Field {field!r} carries more precision than the instrument allows "
            f"(precision {precision}); refusing to round a venue value"
        )
    return quantised


def _build_price(value: Decimal, *, precision: int, field: str) -> Price:
    if value < _PRICE_MIN or value > _PRICE_MAX:
        raise VenuePayloadError(
            f"Field {field!r} value {value} is outside the binary-option range "
            f"[{_PRICE_MIN}, {_PRICE_MAX}]"
        )
    quantised = _assert_representable(
        value, precision=precision, field=field, error=VenuePayloadError
    )
    return Price.from_str(format(quantised, f".{precision}f"))


def _build_quantity(value: Decimal, *, precision: int, field: str) -> Quantity:
    if value <= 0:
        raise VenuePayloadError(f"Field {field!r} value {value} is not a positive size")
    quantised = _assert_representable(
        value, precision=precision, field=field, error=VenuePayloadError
    )
    return Quantity.from_str(format(quantised, f".{precision}f"))


def parse_rfc3339_nanos(value: object, *, field: str) -> int:
    """Parse a venue RFC 3339 UTC timestamp to UNIX nanoseconds, losslessly.

    The venue emits nine fractional digits (``...T00:19:48.120237895Z``).
    ``datetime`` tops out at microseconds, so the fraction is carried as an
    integer instead: dropping the last three digits would silently reorder
    same-microsecond book updates.

    Only the ``Z`` form is accepted. A numeric offset is not something the
    venue has been observed to send, and guessing at one is how a timestamp
    ends up hours wrong.
    """
    if not isinstance(value, str):
        raise VenuePayloadError(
            f"Field {field!r} must be an RFC 3339 UTC string, got {type(value).__name__}"
        )
    match = _RFC3339_RE.match(value)
    if match is None:
        raise VenuePayloadError(f"Field {field!r} is not an RFC 3339 UTC timestamp ending in 'Z'")
    try:
        moment = datetime.strptime(  # noqa: DTZ007 - tz is fixed UTC by the regex
            f"{match.group('date')}T{match.group('time')}", "%Y-%m-%dT%H:%M:%S"
        )
    except ValueError:
        raise VenuePayloadError(f"Field {field!r} is not a valid calendar date/time") from None
    seconds = calendar.timegm(moment.timetuple())
    fraction = match.group("fraction") or ""
    nanos = int(fraction.ljust(_FRACTION_DIGITS, "0")) if fraction else 0
    return seconds * _NANOS_PER_SECOND + nanos


def _parse_amount(
    value: object, *, field: str, error: type[VenuePayloadError] = VenuePayloadError
) -> Decimal:
    """Read a venue ``{"value": ..., "currency": ...}`` amount object."""
    if not isinstance(value, Mapping):
        raise error(f"Field {field!r} must be an amount object, got {type(value).__name__}")
    currency = value.get("currency")
    if currency != QUOTE_CURRENCY_CODE:
        raise error(
            f"Field {field!r} is denominated in {currency!r}, not "
            f"{QUOTE_CURRENCY_CODE!r}; refusing to treat it as a USD amount"
        )
    return _to_decimal(_require(value, "value", error=error), field=f"{field}.value", error=error)


def _parse_fee_coefficient(market: Mapping[str, Any]) -> tuple[Decimal | None, str]:
    """Read the market's own ``theta``, or report the schedule UNKNOWN.

    Three outcomes, deliberately distinct:

    * **Absent or JSON ``null``** -> ``(None, UNKNOWN)``. The venue said
      nothing, so we know nothing, and every fee-consuming path fails closed
      via :func:`assert_fee_schedule_known`.
    * **Present and usable** (finite, ``0 <= theta <= 1``) ->
      ``(theta, KNOWN)``. The status is DERIVED from an actual parse; it is
      never assumed and never written on any other path.
    * **Present and unusable** -> raises
      :class:`~breezy.adapters.polymarket_us.errors.InstrumentDefinitionError`.
      A coefficient we cannot read is a venue schema change, and aborting the
      instrument surfaces it immediately instead of degrading to UNKNOWN and
      letting a fee-free instrument look merely unresolved.

    Note that a parsed ``0`` is KNOWN, not UNKNOWN: "the venue told us this
    market is free" and "the venue told us nothing" are different facts, and
    conflating them is exactly the defect barrier F1 exists to prevent.
    """
    raw = market.get("feeCoefficient")
    if raw is None:
        return None, FEE_SCHEDULE_STATUS_UNKNOWN
    theta = _to_decimal(raw, field="feeCoefficient", error=InstrumentDefinitionError)
    if theta < Decimal(0) or theta > Decimal(1):
        raise InstrumentDefinitionError(
            f"Field 'feeCoefficient' value {theta} is outside the supported range [0, 1]"
        )
    return theta, FEE_SCHEDULE_STATUS_KNOWN


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------


def _parse_levels(levels: object, *, side: str) -> list[tuple[Decimal, Decimal]]:
    """Validate and return EVERY level of one book side, in venue order.

    An empty JSON array is a valid parsed side: a missing bid or offer is a
    legitimate venue state on thin weather markets, not a malformed payload.
    Per-level checks (type, binary price range, positive size) are unchanged.
    Callers that need a two-sided quote must require a populated side
    themselves -- see ``_require_best_level``.
    """
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes)):
        raise VenuePayloadError(
            f"Book side {side!r} must be a JSON array, got {type(levels).__name__}"
        )
    parsed: list[tuple[Decimal, Decimal]] = []
    for index, level in enumerate(levels):
        if not isinstance(level, Mapping):
            raise VenuePayloadError(
                f"Book level {side}[{index}] must be a JSON object, got {type(level).__name__}"
            )
        price = _parse_amount(_require(level, "px", error=VenuePayloadError), field=f"{side}.px")
        if price < _PRICE_MIN or price > _PRICE_MAX:
            raise VenuePayloadError(
                f"Book level {side}[{index}] price {price} is outside the "
                f"binary-option range [{_PRICE_MIN}, {_PRICE_MAX}]"
            )
        size = _to_decimal(
            _require(level, "qty", error=VenuePayloadError),
            field=f"{side}.qty",
            error=VenuePayloadError,
        )
        if size <= 0:
            raise VenuePayloadError(
                f"Book level {side}[{index}] size {size} is not a positive size"
            )
        parsed.append((price, size))
    return parsed


def _require_best_level(levels: object, *, side: str, want_lowest: bool) -> tuple[Decimal, Decimal]:
    """Return the best ``(price, size)`` of one side, or refuse an empty side.

    ``QuoteTick`` is a two-sided quote. Inventing a bid (or ask) of 0 -- or
    any other price -- would fabricate a top of book the venue did not send.
    Empty is therefore an error here, not a default. Depth capture uses
    ``parse_book_levels``, which records the populated side instead.
    """
    parsed = _parse_levels(levels, side=side)
    if not parsed:
        raise VenuePayloadError(f"Book side {side!r} is empty; there is no top of book to quote")
    return min(parsed) if want_lowest else max(parsed)


def parse_book_levels(
    payload: Mapping[str, Any],
) -> tuple[list[tuple[Decimal, Decimal]], list[tuple[Decimal, Decimal]]]:
    """Return ``(bids, asks)`` as fully validated, best-first ``Decimal`` levels.

    Sorted here rather than trusted from the venue: position carries meaning to
    a slippage walk (level ``n`` is the ``n``-th best), and a venue that stops
    sorting a side would otherwise produce a silently wrong slippage estimate
    from a tape that looks perfectly well formed.

    A one-sided book (empty bids or empty offers, but not both) is returned
    as-is: the populated side is the recordable market state. A fully empty
    book is still refused -- padding both sides with zero is not a price.
    The crossed-book check runs only when both sides are populated.
    """
    market_data = _require_mapping(payload, "marketData", context="order book payload")
    bids = _parse_levels(_require(market_data, "bids", error=VenuePayloadError), side="bids")
    asks = _parse_levels(_require(market_data, "offers", error=VenuePayloadError), side="offers")
    bids.sort(key=lambda level: level[0], reverse=True)
    asks.sort(key=lambda level: level[0])
    if not bids and not asks:
        raise VenuePayloadError("Order book has no populated side; there is nothing to record")
    if bids and asks and bids[0][0] > asks[0][0]:
        raise VenuePayloadError(
            f"Order book is crossed: best bid {bids[0][0]} exceeds best offer {asks[0][0]}"
        )
    return bids, asks


def parse_book_top(payload: Mapping[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return ``(bid_price, bid_size, ask_price, ask_size)`` as exact ``Decimal``s.

    Accepts the shape shared by the REST order-book response and the markets
    WebSocket ``SUBSCRIPTION_TYPE_MARKET_DATA`` frame: an envelope carrying
    ``marketData`` with ``bids`` and ``offers``. The ask side is spelled
    ``offers`` in both, and is not aliased to ``asks`` here -- an unexpected key
    means the schema moved and should fail loudly.

    The best level is selected by price rather than by array position, so a
    venue that stops sorting a side cannot silently produce a wrong top of book.

    A one-sided book cannot form this return value: there is no bid (or no
    ask) to quote. This function refuses rather than inventing a price. Depth
    capture uses ``parse_book_levels``, which records the populated side.
    """
    market_data = _require_mapping(payload, "marketData", context="order book payload")
    bid_price, bid_size = _require_best_level(
        _require(market_data, "bids", error=VenuePayloadError), side="bids", want_lowest=False
    )
    ask_price, ask_size = _require_best_level(
        _require(market_data, "offers", error=VenuePayloadError), side="offers", want_lowest=True
    )
    if bid_price > ask_price:
        raise VenuePayloadError(
            f"Order book is crossed: best bid {bid_price} exceeds best offer {ask_price}"
        )
    return bid_price, bid_size, ask_price, ask_size


def parse_quote_tick(
    payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int
) -> QuoteTick:
    """Build a ``QuoteTick`` for ``instrument`` from a book or market-data frame.

    ``ts_event`` is the venue's ``transactTime``; ``ts_init`` is supplied by the
    caller from the adapter clock at the moment of receipt. They are distinct on
    purpose -- ``ts_init`` drives backtest ordering while ``ts_event`` carries
    venue semantics -- so ``transactTime`` is required rather than defaulted.
    """
    market_data = _require_mapping(payload, "marketData", context="market data payload")
    expected_slug = instrument.id.symbol.value
    observed_slug = _require(market_data, "marketSlug", error=VenuePayloadError)
    if observed_slug != expected_slug:
        raise VenuePayloadError(
            f"Market data frame is for slug {observed_slug!r} but was parsed against "
            f"instrument {expected_slug!r}"
        )
    ts_event = parse_rfc3339_nanos(
        _require(market_data, "transactTime", error=VenuePayloadError), field="transactTime"
    )
    bid_price, bid_size, ask_price, ask_size = parse_book_top(payload)
    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=_build_price(bid_price, precision=instrument.price_precision, field="bids.px"),
        ask_price=_build_price(ask_price, precision=instrument.price_precision, field="offers.px"),
        bid_size=_build_quantity(bid_size, precision=instrument.size_precision, field="bids.qty"),
        ask_size=_build_quantity(ask_size, precision=instrument.size_precision, field="offers.qty"),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def _market_data(payload: Mapping[str, Any], *, instrument: BinaryOption) -> Mapping[str, Any]:
    """Return the ``marketData`` envelope, refusing a frame for another slug."""
    market_data = _require_mapping(payload, "marketData", context="market data payload")
    expected_slug = instrument.id.symbol.value
    observed_slug = _require(market_data, "marketSlug", error=VenuePayloadError)
    if observed_slug != expected_slug:
        raise VenuePayloadError(
            f"Market data frame is for slug {observed_slug!r} but was parsed against "
            f"instrument {expected_slug!r}"
        )
    return market_data


def parse_order_book_depth10(
    payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int
) -> OrderBookDepth10:
    """Build a native ``OrderBookDepth10`` from a book or market-data frame.

    **Why the native type and not a custom one.** ``OrderBookDepth10`` is
    Arrow-registered (``serialization/arrow/serializer.py``), is a
    per-instrument table in ``StreamingFeatherWriter``
    (``persistence/writer.py:137-147``), and partitions natively into
    ``data/order_book_depths/<instrument_id>/``. Measured end to end before
    this function was written. A custom depth type would have reimplemented
    all of that. Do not quote from ``to_quote_tick()``: on a one-sided book
    that native helper reads the size-0 pad as a 0 price. Two-sided quotes
    stay on ``parse_quote_tick`` / ``parse_book_top``; depth consumers must
    skip ``size == 0``.

    **Truncation is real and is the price of the native carrier.** The
    committed capture ``book_open_510636.json`` has **12 bid levels and 14 offer
    levels**, so ten-per-side is a genuine cut, not a theoretical one. The
    caller counts truncations (``PolymarketUSDataClient.depth_levels_truncated``)
    and warns, because an analyst who assumes the tape is the whole book will
    understate available liquidity beyond level ten. Ten levels is nonetheless
    what slippage-at-intended-size needs, and it is ten times what the previous
    top-of-book-only tape carried.

    **Padding is authored, and must be.** ``OrderBookDepth10.__init__`` pads a
    short side with ``NULL_ORDER``, whose price and size precision are 0. The
    Arrow encoder then rejects the record outright --
    ``ValueError: Mixed metadata at row 0`` -- and the writer swallows that into
    a log line, so a thin book would vanish from the tape silently. Executed and
    reproduced. Padding at the instrument's own precision is what makes a thin
    market recordable at all.
    """
    market_data = _market_data(payload, instrument=instrument)
    ts_event = parse_rfc3339_nanos(
        _require(market_data, "transactTime", error=VenuePayloadError), field="transactTime"
    )
    bids, asks = parse_book_levels(payload)

    price_precision = instrument.price_precision
    size_precision = instrument.size_precision

    def side_orders(
        levels: list[tuple[Decimal, Decimal]], side: OrderSide, field: str
    ) -> tuple[list[BookOrder], list[int]]:
        kept = levels[:DEPTH10_LEVELS]
        orders = [
            BookOrder(
                side,
                _build_price(price, precision=price_precision, field=f"{field}.px"),
                _build_quantity(size, precision=size_precision, field=f"{field}.qty"),
                0,
            )
            for price, size in kept
        ]
        counts = [1] * len(orders)
        # Precision-matched filler, NOT Nautilus's NULL_ORDER. See the docstring.
        filler = BookOrder(side, Price(0, price_precision), Quantity(0, size_precision), 0)
        while len(orders) < DEPTH10_LEVELS:
            orders.append(filler)
            counts.append(0)
        return orders, counts

    bid_orders, bid_counts = side_orders(bids, OrderSide.BUY, "bids")
    ask_orders, ask_counts = side_orders(asks, OrderSide.SELL, "offers")

    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        # No venue sequence number is present in any capture. Zero is what
        # Nautilus documents for that case (``model/data.pyx:3460-3462``);
        # inventing a counter here would look like venue ordering and is not.
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_init,
    )


def depth_levels_dropped(payload: Mapping[str, Any]) -> int:
    """Levels the ten-per-side carrier could not keep. Zero when nothing is cut."""
    market_data = payload.get("marketData")
    if not isinstance(market_data, Mapping):
        return 0
    dropped = 0
    for key in ("bids", "offers"):
        side = market_data.get(key)
        if isinstance(side, Sequence) and not isinstance(side, (str, bytes)):
            dropped += max(0, len(side) - DEPTH10_LEVELS)
    return dropped


def parse_trade_tick(
    payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int
) -> TradeTick:
    """Build a ``TradeTick`` from an executed-print frame.

    Executed prints are the only ground truth for what actually traded rather
    than what was merely quoted (REQ-DATA-04), and they cannot be reconstructed
    later from a quote tape.

    **UNRESOLVED venue fact.** No trade frame has been captured; the field names
    here are the singular forms already used by the book payload
    (``px``/``qty``/``transactTime``/``marketSlug``) plus ``tradeId`` and
    ``takerSide``. Every one is REQUIRED except ``takerSide``, so a frame that
    does not match raises :class:`VenuePayloadError` and is dropped and counted
    by the caller. A wrong guess therefore degrades to "no trades recorded",
    which the drop counter makes visible -- never to a fabricated print.
    """
    trade = _require_mapping(payload, TRADE_CONTAINER_KEY, context="trade payload")
    expected_slug = instrument.id.symbol.value
    observed_slug = _require(trade, "marketSlug", error=VenuePayloadError)
    if observed_slug != expected_slug:
        raise VenuePayloadError(
            f"Trade frame is for slug {observed_slug!r} but was parsed against "
            f"instrument {expected_slug!r}"
        )
    price = _parse_amount(_require(trade, "px", error=VenuePayloadError), field="trade.px")
    if price < _PRICE_MIN or price > _PRICE_MAX:
        raise VenuePayloadError(
            f"Trade price {price} is outside the binary-option range "
            f"[{_PRICE_MIN}, {_PRICE_MAX}]"
        )
    size = _to_decimal(
        _require(trade, "qty", error=VenuePayloadError), field="trade.qty", error=VenuePayloadError
    )
    if size <= 0:
        raise VenuePayloadError(f"Trade size {size} is not a positive size")
    ts_event = parse_rfc3339_nanos(
        _require(trade, "transactTime", error=VenuePayloadError), field="transactTime"
    )
    raw_trade_id = _require(trade, "tradeId", error=VenuePayloadError)
    if not isinstance(raw_trade_id, str) or not raw_trade_id.strip():
        raise VenuePayloadError("Field 'tradeId' must be a non-empty string")

    raw_side = trade.get("takerSide")
    aggressor = _TAKER_SIDES.get(raw_side, AggressorSide.NO_AGGRESSOR) if isinstance(
        raw_side, str
    ) else AggressorSide.NO_AGGRESSOR

    return TradeTick(
        instrument_id=instrument.id,
        price=_build_price(price, precision=instrument.price_precision, field="trade.px"),
        size=_build_quantity(size, precision=instrument.size_precision, field="trade.qty"),
        aggressor_side=aggressor,
        trade_id=TradeId(raw_trade_id.strip()),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def venue_market_state(payload: Mapping[str, Any]) -> str | None:
    """Return the raw venue ``state`` string, or ``None`` when absent.

    Observed values in the committed captures: ``MARKET_STATE_OPEN``
    (``book_open_510636.json``) and ``MARKET_STATE_EXPIRED``
    (``book_closed_15806.json``). The full enum is UNRESOLVED, which is exactly
    why the value is returned as a string and never coerced.
    """
    market_data = payload.get("marketData")
    if not isinstance(market_data, Mapping):
        return None
    state = market_data.get("state")
    return state if isinstance(state, str) and state.strip() else None


def parse_instrument_status(
    payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int
) -> InstrumentStatus | None:
    """Carry the venue's market state, VERBATIM, on the native status record.

    ``action`` is deliberately ``MarketStatusAction.NONE``. Nautilus's enum has
    no member meaning ``MARKET_STATE_EXPIRED``, and choosing the nearest one
    would bake a guess about an UNRESOLVED venue enum into an archive that can
    never be re-recorded. ``reason`` is a free-text field, so the venue's own
    string survives byte for byte and can be re-interpreted later once the enum
    is known. Nothing is lost and nothing is invented.
    """
    state = venue_market_state(payload)
    if state is None:
        return None
    market_data = _market_data(payload, instrument=instrument)
    ts_event = parse_rfc3339_nanos(
        _require(market_data, "transactTime", error=VenuePayloadError), field="transactTime"
    )
    return InstrumentStatus(
        instrument_id=instrument.id,
        action=MarketStatusAction.NONE,
        ts_event=ts_event,
        ts_init=ts_init,
        reason=state,
    )


def _stats(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    market_data = payload.get("marketData")
    if not isinstance(market_data, Mapping):
        return None
    stats = market_data.get("stats")
    return stats if isinstance(stats, Mapping) else None


def venue_settlement_method(payload: Mapping[str, Any]) -> str | None:
    """Return the raw ``settlementPriceCalculationMethod``, or ``None`` if absent.

    Returned as a STRING and never coerced onto an enum: only two values have
    ever been observed and the rest of the space is UNRESOLVED. See
    :data:`TERMINAL_SETTLEMENT_METHOD`.
    """
    stats = _stats(payload)
    if stats is None:
        return None
    method = stats.get("settlementPriceCalculationMethod")
    return method if isinstance(method, str) and method.strip() else None


def _venue_settlement_px_text(payload: Mapping[str, Any]) -> str | None:
    """The venue's own spelling of ``settlementPx.value``, unmodified.

    Kept as text so the settlement-truth record never silently acquires our
    formatting: the capture spells it ``"1.0000"`` (four places) while the
    instrument's price precision is three.
    """
    stats = _stats(payload)
    if stats is None:
        return None
    raw = stats.get("settlementPx")
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("value")
    return value if isinstance(value, str) and value.strip() else None


def _is_terminal_settlement(payload: Mapping[str, Any]) -> bool:
    """Both the state AND the venue's own method must say so. Never either."""
    state = venue_market_state(payload)
    if state is None or state not in EXPIRED_MARKET_STATES:
        return False
    return venue_settlement_method(payload) == TERMINAL_SETTLEMENT_METHOD


def _settlement_amount(payload: Mapping[str, Any]) -> tuple[Decimal, int] | None:
    stats = _stats(payload)
    if stats is None:
        return None
    raw = stats.get("settlementPx")
    if raw is None:
        return None
    price = _parse_amount(raw, field="stats.settlementPx")
    if price < _PRICE_MIN or price > _PRICE_MAX:
        raise VenuePayloadError(
            f"Settlement price {price} is outside the binary-option range "
            f"[{_PRICE_MIN}, {_PRICE_MAX}]"
        )
    raw_time = stats.get("settlementSetTime")
    if not isinstance(raw_time, str):
        return None
    return price, parse_rfc3339_nanos(raw_time, field="settlementSetTime")


def parse_settlement_snapshot(
    payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int
) -> VenueSettlementSnapshot | None:
    """Record the venue's settlement fields VERBATIM, on every bearing frame.

    Emitted whether or not the frame is allowed to create a terminal
    settlement, which is the point: an EXPIRED market whose price is not yet
    terminally computed produces no ``InstrumentClose``, and without this
    record that refusal would also be a silence. "Record it and wait" needs
    something recorded.

    ``is_terminal`` is the derived judgement stored ALONGSIDE its raw inputs
    (``state``, ``method``), never instead of them, so a later correction to
    the rule can be applied retrospectively to an archive that cannot be
    re-recorded.

    Both venue clocks are kept: ``ts_event`` is ``settlementSetTime`` (when the
    venue COMPUTED the price) and ``venue_transact_time_ns`` is the frame's own
    ``transactTime`` (when the venue DISCLOSED it). They differ by hours in the
    committed capture, and a settlement dispute turns on the lag between them.
    """
    method = venue_settlement_method(payload)
    settlement_px = _venue_settlement_px_text(payload)
    if method is None or settlement_px is None:
        return None
    state = venue_market_state(payload)
    if state is None:
        return None
    settlement = _settlement_amount(payload)
    if settlement is None:
        return None
    _, ts_event = settlement
    # Read via `_stats`'s unvalidated sibling rather than `_market_data`: this
    # function deliberately does NOT re-assert the slug/instrument match, which
    # is the caller's job and is already done upstream in the routing path.
    # Introducing that check here would change when provenance is recorded, and
    # the whole point of this record is that it is recorded whenever possible.
    market_data = payload.get("marketData")
    if not isinstance(market_data, Mapping):
        return None
    raw_transact = market_data.get("transactTime")
    if not isinstance(raw_transact, str):
        return None
    transact_time = parse_rfc3339_nanos(raw_transact, field="transactTime")
    return VenueSettlementSnapshot(
        instrument_id=instrument.id,
        state=state,
        method=method,
        settlement_px=settlement_px,
        is_terminal=_is_terminal_settlement(payload),
        venue_transact_time_ns=transact_time,
        ts_event=ts_event,
        ts_init=ts_init,
    )


def parse_mark_price(
    payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int
) -> MarkPriceUpdate | None:
    """Capture the venue's own ``settlementPx`` as a native ``MarkPriceUpdate``.

    **Not an ``InstrumentClose``.** The committed OPEN-market capture carries
    ``state=MARKET_STATE_OPEN`` alongside ``settlementPx=0.4900``, so on a live
    market this field is a daily mark, not a terminal value. Recording it as a
    close price would fabricate a settlement that has not happened.
    :func:`parse_instrument_close` handles the terminal case separately.

    ``ts_event`` is the venue's ``settlementSetTime``, not the frame's
    ``transactTime``: in the capture they differ by hours, and the mark's own
    timestamp is the one that matters for any later join.
    """
    settlement = _settlement_amount(payload)
    if settlement is None:
        return None
    price, ts_event = settlement
    return MarkPriceUpdate(
        instrument_id=instrument.id,
        value=_build_price(
            price, precision=instrument.price_precision, field="stats.settlementPx"
        ),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def parse_instrument_close(
    payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int
) -> InstrumentClose | None:
    """Emit the venue's TERMINAL settlement value, and only when it is terminal.

    **TWO conditions, both required.** The state must be in
    :data:`EXPIRED_MARKET_STATES` AND the venue's own
    ``settlementPriceCalculationMethod`` must be
    :data:`TERMINAL_SETTLEMENT_METHOD`. Gating on the state alone is one frame
    away from permanent corruption: if the venue flips ``state`` before it
    republishes a terminally-computed price, a mark-derived number would be
    recorded as settlement truth in an archive with no correction path.

    A refusal here is not a loss -- :func:`parse_settlement_snapshot` records
    the frame verbatim either way, so "expired but not yet terminal" is visible
    on disk rather than silent.

    This is the venue's own authoritative settlement number, which plan item
    1.2's ledger needs and which venue REST may not retain once the market ages
    out -- capture it while it is on the wire or lose it.
    """
    if not _is_terminal_settlement(payload):
        return None
    settlement = _settlement_amount(payload)
    if settlement is None:
        return None
    price, ts_event = settlement
    return InstrumentClose(
        instrument_id=instrument.id,
        close_price=_build_price(
            price, precision=instrument.price_precision, field="stats.settlementPx"
        ),
        close_type=InstrumentCloseType.CONTRACT_EXPIRED,
        ts_event=ts_event,
        ts_init=ts_init,
    )


# ---------------------------------------------------------------------------
# Instrument definition
# ---------------------------------------------------------------------------


def _increment(market: Mapping[str, Any], key: str) -> tuple[Decimal, int]:
    if key not in market or market[key] is None:
        raise InstrumentDefinitionError(
            f"Polymarket.us market is missing required field {key!r}; this adapter "
            "never substitutes a default increment (FINDINGS:225-227)"
        )
    value = _to_decimal(market[key], field=key, error=InstrumentDefinitionError)
    if value <= 0:
        raise InstrumentDefinitionError(f"Field {key!r} value {value} is not positive")
    if value > _PRICE_MAX and key == "orderPriceMinTickSize":
        raise InstrumentDefinitionError(
            f"Field {key!r} value {value} exceeds the binary-option price range"
        )
    return value, _precision_of(value, field=key, error=InstrumentDefinitionError)


def _market_sides(market: Mapping[str, Any], slug: str) -> tuple[list[Mapping[str, Any]], str]:
    raw_sides = _require(market, "marketSides", error=InstrumentDefinitionError)
    if not isinstance(raw_sides, Sequence) or isinstance(raw_sides, (str, bytes)):
        raise InstrumentDefinitionError("Field 'marketSides' must be a JSON array")
    sides: list[Mapping[str, Any]] = []
    for index, side in enumerate(raw_sides):
        if not isinstance(side, Mapping):
            raise InstrumentDefinitionError(
                f"marketSides[{index}] must be a JSON object, got {type(side).__name__}"
            )
        identifier = _require(side, "identifier", error=InstrumentDefinitionError)
        if identifier != slug:
            raise InstrumentDefinitionError(
                f"marketSides[{index}].identifier {identifier!r} disagrees with the "
                f"market slug {slug!r}"
            )
        quote = side.get("quote")
        if quote is not None:
            _parse_amount(
                quote, field=f"marketSides[{index}].quote", error=InstrumentDefinitionError
            )
        sides.append(side)

    long_sides = [side for side in sides if side.get("long") is True]
    if len(long_sides) != 1:
        raise InstrumentDefinitionError(
            f"Expected exactly one long market side for {slug!r}, found {len(long_sides)}"
        )
    outcome = _require(long_sides[0], "description", error=InstrumentDefinitionError)
    if not isinstance(outcome, str) or not outcome.strip():
        raise InstrumentDefinitionError(
            f"Long market side for {slug!r} carries no usable outcome description"
        )
    return sides, outcome


def _weather_info(
    market: Mapping[str, Any],
    slug: str,
    *,
    sites: SiteRegistry,
    venue_key: str,
) -> dict[str, Any]:
    parsed = parse_weather_slug(slug)
    category = market.get("category")
    if parsed is None:
        if category == CLIMATE_CATEGORY:
            raise InstrumentDefinitionError(
                f"Market {slug!r} is categorised {CLIMATE_CATEGORY!r} but its slug does "
                "not match any observed weather grammar; refusing to load a climate "
                "instrument without a city_day_cluster_id"
            )
        return {WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_UNKNOWN}

    interval = assert_bounds_cross_checked(
        parsed,
        description=_description(market),
        title=market.get("title") if isinstance(market.get("title"), str) else None,
        # Settlement data flows through NwsClimateDay.tmax_f/tmin_f, typed int | None.
        reading_is_whole_degrees=True,
    )
    try:
        site = sites.site_for_venue_city_token(venue_key, parsed.city)
    except SiteNotFoundError as exc:
        raise InstrumentDefinitionError(
            f"Market {slug!r} carries venue_city_token {parsed.city!r}, but no "
            f"settlement site is registered for venue {venue_key!r}"
        ) from exc

    return {
        "city": parsed.city,
        "measure": parsed.measure,
        "climate_date": parsed.climate_date,
        "strike_bounds": parsed.raw_bounds,
        "city_day_cluster_id": parsed.city_day_cluster_id,
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: site.cli_location,
        STRIKE_LOWER_F_KEY: interval[0],
        STRIKE_UPPER_F_KEY: interval[1],
    }


def parse_binary_option(
    payload: Mapping[str, Any],
    *,
    venue: Venue = POLYMARKET_US_VENUE,
    ts_init: int,
    sites: SiteRegistry | None = None,
    venue_key: str = REGISTRY_VENUE_KEY,
) -> BinaryOption:
    """Build a native ``BinaryOption`` from a ``GET /v1/market/slug/{slug}`` response.

    ``BinaryOption`` is Nautilus's own instrument type for 0-1 priced binary
    outcomes (notional ``qty * p``, multiplier 1, never inverse), so no parallel
    instrument model is introduced.

    ``asset_class`` follows the in-tree exemplar
    (``adapters/polymarket/common/parsing.py:242``), which uses
    ``AssetClass.ALTERNATIVE`` for prediction-market binaries.
    """
    market = _require_mapping(payload, "market", context="market payload")

    slug = _require(market, "slug", error=InstrumentDefinitionError)
    assert_valid_slug(slug)

    price_increment, price_precision = _increment(market, "orderPriceMinTickSize")
    size_increment, size_precision = _increment(market, "minimumTradeQty")

    sides, outcome = _market_sides(market, slug)

    activation_ns = parse_rfc3339_nanos(
        _require(market, "startDate", error=InstrumentDefinitionError), field="startDate"
    )
    expiration_ns = parse_rfc3339_nanos(
        _require(market, "endDate", error=InstrumentDefinitionError), field="endDate"
    )
    ts_event = parse_rfc3339_nanos(
        _require(market, "updatedAt", error=InstrumentDefinitionError), field="updatedAt"
    )
    if expiration_ns <= activation_ns:
        raise InstrumentDefinitionError(
            f"Market {slug!r} expires at or before it activates "
            f"({expiration_ns} <= {activation_ns})"
        )

    fee_coefficient, fee_schedule_status = _parse_fee_coefficient(market)
    info: dict[str, Any] = {
        "market_id": str(_require(market, "id", error=InstrumentDefinitionError)),
        "slug": slug,
        "category": market.get("category"),
        "status": market.get("status"),
        "title": market.get("title"),
        "question": market.get("question"),
        "market_side_ids": tuple(str(side.get("id")) for side in sides),
        "size_increment_source": "minimumTradeQty",
        # Recorded verbatim, per market. PolymarketUSFeeModel reads it from here.
        FEE_COEFFICIENT_KEY: None if fee_coefficient is None else str(fee_coefficient),
        FEE_SCHEDULE_STATUS_KEY: fee_schedule_status,
    }
    active_sites = default_registry() if sites is None else sites
    info.update(_weather_info(market, slug, sites=active_sites, venue_key=venue_key))

    return BinaryOption(
        instrument_id=slug_to_instrument_id(slug, venue),
        raw_symbol=Symbol(slug),
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=price_precision,
        size_precision=size_precision,
        price_increment=Price.from_str(format(price_increment, f".{price_precision}f")),
        size_increment=Quantity.from_str(format(size_increment, f".{size_precision}f")),
        activation_ns=activation_ns,
        expiration_ns=expiration_ns,
        ts_event=ts_event,
        ts_init=ts_init,
        min_quantity=Quantity.from_str(format(size_increment, f".{size_precision}f")),
        # DECISION (a) -- see the module docstring for the algebra. `theta`
        # itself, not a flat notional rate and not a placeholder zero.
        maker_fee=fee_coefficient,
        taker_fee=fee_coefficient,
        outcome=outcome,
        description=_description(market),
        info=info,
    )


def _description(market: Mapping[str, Any]) -> str | None:
    description = market.get("description")
    if isinstance(description, str) and description.strip():
        return description
    return None
