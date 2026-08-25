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

**Fees fail closed -- in substance, not only in this docstring.**
``BUILD_PLAN`` Phase 1 downgraded the Polymarket.us fee schedule to
``[UNKNOWN]``. The market payload's ``feeCoefficient`` is the ``theta`` of
``fee = theta * C * p * (1 - p)`` -- a coefficient on a concave function of
price, not a flat rate on notional, which is what Nautilus's
``maker_fee``/``taker_fee`` mean. It is recorded verbatim in ``info`` next to
:data:`FEE_SCHEDULE_STATUS_UNKNOWN` and is never written to either fee field.

That marker alone is NOT enough, and saying otherwise was a real defect.
``BinaryOption`` defaults the two fee fields via ``maker_fee or Decimal(0)``
(``model/instruments/binary_option.pyx:148-149``), so every instrument loaded
here carries a genuine, typed ``Decimal(0)`` in exactly the fields generic
Nautilus machinery reads -- ``MakerTakerFeeModel.get_commission`` multiplies
notional by ``instrument.taker_fee`` and by nothing else
(``backtest/models/fee.pyx:96-99``). A zero there is indistinguishable from a
free venue, while the real taker fee is $1.50 per 100 contracts at p=0.50.

Instruments must stay loadable (the read-only slice needs them to receive
quotes), so the enforcement is a guard rather than a refusal:
:func:`assert_fee_schedule_known` raises unless ``info`` says the schedule is
``KNOWN``, and ``tests/unit/test_polymarket_us_fee_guard.py`` (barrier F1)
fails the suite if any venue-touching module reads a fee field without calling
it.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.errors import (
    FeeScheduleUnknownError,
    InstrumentDefinitionError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    assert_valid_slug,
    parse_weather_slug,
    slug_to_instrument_id,
)

__all__ = [
    "CLIMATE_CATEGORY",
    "FEE_SCHEDULE_STATUS_KEY",
    "FEE_SCHEDULE_STATUS_KNOWN",
    "FEE_SCHEDULE_STATUS_UNKNOWN",
    "QUOTE_CURRENCY_CODE",
    "assert_fee_schedule_known",
    "parse_binary_option",
    "parse_book_top",
    "parse_quote_tick",
    "parse_rfc3339_nanos",
]

#: The only settlement currency Polymarket.us (a fiat DCM) is documented to use.
#: A payload naming anything else is refused rather than coerced.
QUOTE_CURRENCY_CODE: str = "USD"

#: ``info`` key carrying the fee-schedule resolution state.
FEE_SCHEDULE_STATUS_KEY: str = "fee_schedule_status"

#: Recorded in ``BinaryOption.info`` so no downstream consumer can mistake the
#: absence of a fee rate for a zero fee rate. Enforced by
#: :func:`assert_fee_schedule_known`, not by convention.
FEE_SCHEDULE_STATUS_UNKNOWN: str = "UNKNOWN"

#: The ONLY value that unlocks a fee-consuming path. Nothing writes it today:
#: resolving the schedule means (a) a live-verified per-market fee model for
#: ``theta * C * p * (1 - p)`` and (b) a decision about how that maps onto
#: Nautilus's flat-rate fee fields, neither of which is in this slice.
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
        "charges theta * C * p * (1 - p) (taker theta 0.06, $1.50 per 100 contracts "
        "at p=0.50). Resolve the schedule and mark it "
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


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------


def _best_level(levels: object, *, side: str, want_lowest: bool) -> tuple[Decimal, Decimal]:
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes)):
        raise VenuePayloadError(
            f"Book side {side!r} must be a JSON array, got {type(levels).__name__}"
        )
    if not levels:
        raise VenuePayloadError(f"Book side {side!r} is empty; there is no top of book to quote")
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
    return min(parsed) if want_lowest else max(parsed)


def parse_book_top(payload: Mapping[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return ``(bid_price, bid_size, ask_price, ask_size)`` as exact ``Decimal``s.

    Accepts the shape shared by the REST order-book response and the markets
    WebSocket ``SUBSCRIPTION_TYPE_MARKET_DATA`` frame: an envelope carrying
    ``marketData`` with ``bids`` and ``offers``. The ask side is spelled
    ``offers`` in both, and is not aliased to ``asks`` here -- an unexpected key
    means the schema moved and should fail loudly.

    The best level is selected by price rather than by array position, so a
    venue that stops sorting a side cannot silently produce a wrong top of book.
    """
    market_data = _require_mapping(payload, "marketData", context="order book payload")
    bid_price, bid_size = _best_level(
        _require(market_data, "bids", error=VenuePayloadError), side="bids", want_lowest=False
    )
    ask_price, ask_size = _best_level(
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


def _weather_info(market: Mapping[str, Any], slug: str) -> dict[str, Any]:
    parsed = parse_weather_slug(slug)
    category = market.get("category")
    if parsed is None:
        if category == CLIMATE_CATEGORY:
            raise InstrumentDefinitionError(
                f"Market {slug!r} is categorised {CLIMATE_CATEGORY!r} but its slug does "
                "not match any observed weather grammar; refusing to load a climate "
                "instrument without a city_day_cluster_id"
            )
        return {
            "city": None,
            "measure": None,
            "climate_date": None,
            "strike_bounds": None,
            "strike_bounds_parsed": None,
            "city_day_cluster_id": None,
        }
    return {
        "city": parsed.city,
        "measure": parsed.measure,
        "climate_date": parsed.climate_date,
        "strike_bounds": parsed.raw_bounds,
        "strike_bounds_parsed": parsed.bounds,
        "city_day_cluster_id": parsed.city_day_cluster_id,
    }


def parse_binary_option(
    payload: Mapping[str, Any], *, venue: Venue = POLYMARKET_US_VENUE, ts_init: int
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

    fee_coefficient = market.get("feeCoefficient")
    info: dict[str, Any] = {
        "market_id": str(_require(market, "id", error=InstrumentDefinitionError)),
        "slug": slug,
        "category": market.get("category"),
        "status": market.get("status"),
        "title": market.get("title"),
        "question": market.get("question"),
        "market_side_ids": tuple(str(side.get("id")) for side in sides),
        "size_increment_source": "minimumTradeQty",
        # Fees fail closed: recorded, never promoted to a rate. See module docstring.
        "fee_coefficient": None if fee_coefficient is None else str(fee_coefficient),
        FEE_SCHEDULE_STATUS_KEY: FEE_SCHEDULE_STATUS_UNKNOWN,
    }
    info.update(_weather_info(market, slug))

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
        outcome=outcome,
        description=_description(market),
        info=info,
    )


def _description(market: Mapping[str, Any]) -> str | None:
    description = market.get("description")
    if isinstance(description, str) and description.strip():
        return description
    return None
