"""Venue JSON -> Nautilus domain objects, at the trust boundary.

Plan revision 2 section 6 ``parsing.py`` and build order Step 7. Golden
samples are the COMMITTED venue captures under
``docs/evidence/venue/polymarket_us/raw/`` -- this suite never contacts the
venue and never invents a payload shape. Where a shape is only documented and
not yet captured (the markets WebSocket frame), the fixture is copied verbatim
from the committed docs snapshot and says so.

Two structural claims are asserted rather than trusted:

* **No float arithmetic on money.** An AST scan proves the parsing modules
  contain no ``float(`` call (``BUILD_PLAN:66``).
* **Precision is validated before construction.** ``Price``/``Quantity`` are
  Rust-backed; the plan records (``TRADING_ENABLEMENT_FINDINGS.md`` section E)
  that the layer can SIGABRT rather than raise on bad input, so a malformed
  value must be refused in Python before it reaches the constructor.
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us import parsing
from breezy.adapters.polymarket_us.errors import (
    FeeScheduleUnknownError,
    InstrumentDefinitionError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_KNOWN,
    FEE_SCHEDULE_STATUS_UNKNOWN,
    assert_fee_schedule_known,
    parse_binary_option,
    parse_book_top,
    parse_quote_tick,
    parse_rfc3339_nanos,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from tests.unit.conftest import (
    MIN_CAPTURED_MARKETS,
    iter_captured_market_payloads,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
ADAPTER_DIR = REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us"

PARSING_MODULES = ("parsing.py", "provider.py", "symbology.py")

TS_INIT = 1_787_617_213_000_000_000


def load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def open_market() -> dict[str, Any]:
    return load_raw("market_open_510636_by_slug.json")


@pytest.fixture
def closed_market() -> dict[str, Any]:
    return load_raw("market_closed_15806_by_slug.json")


@pytest.fixture
def open_book() -> dict[str, Any]:
    return load_raw("book_open_510636.json")


@pytest.fixture
def closed_book() -> dict[str, Any]:
    return load_raw("book_closed_15806.json")


@pytest.fixture
def open_instrument(open_market: dict[str, Any]) -> BinaryOption:
    return parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", PARSING_MODULES)
def test_module_contains_no_float_call(module_name: str) -> None:
    tree = ast.parse((ADAPTER_DIR / module_name).read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]
    assert offenders == []


def test_camel_case_keys_are_pinned(open_market: dict[str, Any], open_book: dict[str, Any]) -> None:
    """The committed capture still carries every key the parser depends on."""
    market = open_market["market"]
    for key in (
        "id",
        "slug",
        "startDate",
        "endDate",
        "updatedAt",
        "orderPriceMinTickSize",
        "minimumTradeQty",
        "marketSides",
        "feeCoefficient",
        "category",
        "status",
    ):
        assert key in market, key
    data = open_book["marketData"]
    for key in ("marketSlug", "bids", "offers", "transactTime"):
        assert key in data, key
    assert set(data["bids"][0]) == {"px", "qty"}
    assert set(data["bids"][0]["px"]) == {"value", "currency"}


# ---------------------------------------------------------------------------
# parse_rfc3339_nanos
# ---------------------------------------------------------------------------


def test_transact_time_nanoseconds_are_preserved_exactly() -> None:
    ns = parse_rfc3339_nanos("2026-08-25T00:19:48.120237895Z", field="transactTime")
    assert ns % 1_000_000_000 == 120_237_895
    assert ns == 1_787_617_188_120_237_895


def test_timestamp_without_fraction_parses() -> None:
    assert parse_rfc3339_nanos("2026-08-26T05:00:00Z", field="endDate") % 1_000_000_000 == 0


@pytest.mark.parametrize(
    "bad",
    ["2026-08-25T00:19:48.120237895+00:00", "2026-08-25 00:19:48Z", "not-a-time", ""],
)
def test_malformed_timestamp_is_rejected(bad: str) -> None:
    with pytest.raises(VenuePayloadError):
        parse_rfc3339_nanos(bad, field="transactTime")


# ---------------------------------------------------------------------------
# parse_binary_option
# ---------------------------------------------------------------------------


def test_open_market_golden_sample_parses_to_a_binary_option(
    open_instrument: BinaryOption,
) -> None:
    assert isinstance(open_instrument, BinaryOption)
    assert open_instrument.id.venue == POLYMARKET_US_VENUE
    assert open_instrument.id.symbol.value == "tc-temp-nychigh-2026-08-25-lt79f"
    assert open_instrument.price_precision == 2
    assert open_instrument.price_increment == Price.from_str("0.01")
    assert open_instrument.size_precision == 2
    assert open_instrument.size_increment == Quantity.from_str("0.01")
    assert open_instrument.outcome == "Yes"
    assert open_instrument.ts_init == TS_INIT


def test_activation_and_expiration_come_from_start_and_end_date(
    open_instrument: BinaryOption,
) -> None:
    assert open_instrument.activation_ns == parse_rfc3339_nanos(
        "2026-08-24T09:45:21Z", field="startDate"
    )
    assert open_instrument.expiration_ns == parse_rfc3339_nanos(
        "2026-08-26T05:00:00Z", field="endDate"
    )
    assert open_instrument.ts_event == parse_rfc3339_nanos(
        "2026-08-25T00:17:58Z", field="updatedAt"
    )
    assert open_instrument.ts_event != open_instrument.ts_init


def test_closed_market_with_integer_min_trade_qty_parses_at_precision_zero(
    closed_market: dict[str, Any],
) -> None:
    instrument = parse_binary_option(closed_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert instrument.size_precision == 0
    assert instrument.size_increment == Quantity.from_str("1")


def test_info_carries_the_venue_identifiers_and_the_cluster_id(
    open_instrument: BinaryOption,
) -> None:
    info = open_instrument.info
    assert info["market_id"] == "510636"
    assert info["slug"] == "tc-temp-nychigh-2026-08-25-lt79f"
    assert info["category"] == "climate"
    assert info["city"] == "nyc"
    assert info["measure"] == "high"
    assert info["climate_date"] == "2026-08-25"
    assert info["strike_bounds"] == "lt79f"
    assert info["city_day_cluster_id"] == "nyc:2026-08-25"
    assert info["market_side_ids"] == ("1020784", "1020785")


def test_fee_coefficient_is_validated_and_marks_the_schedule_known(
    open_instrument: BinaryOption,
) -> None:
    """``feeCoefficient`` is the venue's ``theta``, and it is DERIVED, not assumed.

    ``theta`` is the coefficient of ``fee = theta * C * p * (1 - p)``. The
    schedule is marked KNOWN only because a finite per-market coefficient in
    ``[0, 1]`` was actually parsed out of this payload.
    """
    info = open_instrument.info
    assert info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_KNOWN
    assert info[FEE_COEFFICIENT_KEY] == "0.06"
    assert Decimal(info[FEE_COEFFICIENT_KEY]) == Decimal("0.06")
    assert_fee_schedule_known(open_instrument)


def test_the_flat_fee_fields_carry_theta_not_a_zero_and_not_a_notional_rate(
    open_instrument: BinaryOption,
) -> None:
    """DECISION (a): ``maker_fee``/``taker_fee`` hold ``theta`` itself.

    This is the same meaning Nautilus's own prediction-market fee model
    assigns to those fields -- ``nautilus_pyo3.ProbabilityPriceFeeModel``
    computes ``qty * rate * p * (1 - p)`` "using the instrument's maker or
    taker fee rate" -- so the value follows the framework's convention rather
    than inventing one. See ``fees.py`` for the never-understates algebra.

    The previous ``Decimal(0)`` was a real, typed, usable zero that any
    generic fee model would have charged as a FREE venue.
    """
    assert_fee_schedule_known(open_instrument)
    assert open_instrument.maker_fee == Decimal("0.06")
    assert open_instrument.taker_fee == Decimal("0.06")


def test_the_flat_fields_are_theta_itself_and_not_a_notional_rate(
    open_instrument: BinaryOption,
) -> None:
    """What the fields HOLD. What reading them generically COSTS lives elsewhere.

    The test this replaces asserted
    ``theta*C*p - theta*C*p*(1-p) == theta*C*p*p`` with both sides computed
    from the same ``theta`` inside the test body. That is an algebraic
    identity -- it holds for theta = 0, 0.06 and 1 alike -- so it constrained
    nothing about the parser and survived deleting ``maker_fee=``/``taker_fee=``
    from :func:`parse_binary_option` outright.

    The property that actually matters compares the two REAL fee models on the
    REAL instrument, and lives in ``test_polymarket_us_fee_model.py`` so it has
    exactly one home. What belongs HERE is only the parser's own contract:
    the fields carry the market's verbatim coefficient.
    """
    assert_fee_schedule_known(open_instrument)

    theta = Decimal(open_instrument.info[FEE_COEFFICIENT_KEY])

    assert open_instrument.maker_fee == theta
    assert open_instrument.taker_fee == theta
    assert theta != Decimal(0), "a zero here would read as a FREE venue"


def test_missing_fee_coefficient_leaves_the_fee_schedule_unknown(
    open_market: dict[str, Any],
) -> None:
    """Absence is UNKNOWN and fail-closed -- never a defaulted coefficient."""
    del open_market["market"]["feeCoefficient"]
    instrument = parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)

    assert instrument.info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_UNKNOWN
    assert instrument.info[FEE_COEFFICIENT_KEY] is None
    # And the flat fields fall back to BinaryOption's own placeholder zero,
    # which is exactly why barrier F1 forces the guard to be called.
    assert instrument.maker_fee == Decimal(0)
    assert instrument.taker_fee == Decimal(0)
    with pytest.raises(FeeScheduleUnknownError):
        assert_fee_schedule_known(instrument)


def test_a_null_fee_coefficient_is_treated_as_absent_not_as_zero(
    open_market: dict[str, Any],
) -> None:
    """A JSON ``null`` must not become a free venue."""
    open_market["market"]["feeCoefficient"] = None
    instrument = parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)

    assert instrument.info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_UNKNOWN
    with pytest.raises(FeeScheduleUnknownError):
        assert_fee_schedule_known(instrument)


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-number",
        -Decimal("0.01"),
        Decimal("1.01"),
        True,
        [0.06],
        {"value": 0.06},
        "NaN",
        "Infinity",
    ],
)
def test_invalid_fee_coefficient_is_refused_rather_than_marked_known(
    open_market: dict[str, Any], bad: object
) -> None:
    """An unusable coefficient aborts the instrument, it never defaults.

    Refused through the existing ``VenuePayloadError`` path so a venue schema
    change surfaces as a failed load rather than a silently wrong fee.
    """
    open_market["market"]["feeCoefficient"] = bad
    with pytest.raises(InstrumentDefinitionError, match="feeCoefficient"):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def test_a_zero_fee_coefficient_is_a_legitimate_known_free_market(
    open_market: dict[str, Any],
) -> None:
    """Zero is IN range. A venue that says 0 is believed; silence is not.

    This is the distinction the whole barrier exists to draw: a parsed zero
    and an absent field are different facts.
    """
    open_market["market"]["feeCoefficient"] = 0
    instrument = parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)

    assert instrument.info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_KNOWN
    assert_fee_schedule_known(instrument)
    assert instrument.taker_fee == Decimal(0)


def test_every_captured_market_observation_parses_with_the_venue_tick_size() -> None:
    """Parser-side corpus property, asserted over the whole capture.

    The fee-schedule half of this property (status KNOWN, coefficient in
    range) is asserted once, in ``test_polymarket_us_fee_model.py``. What
    stays here is what this module owns: price precision, and the fact that
    both market lifecycle stages are represented so no property below is an
    artefact of a single stage.
    """
    payloads = iter_captured_market_payloads()
    assert len(payloads) >= MIN_CAPTURED_MARKETS, (
        f"corpus shrank to {len(payloads)}; evidence lost?"
    )

    instruments = [
        parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
        for payload in payloads
    ]

    assert {i.price_increment for i in instruments} == {Price.from_str("0.01")}

    statuses = {payload["market"].get("status") for payload in payloads}
    assert "MARKET_STATUS_OPEN" in statuses
    assert "MARKET_STATUS_RESOLVED" in statuses


def test_minimum_trade_qty_is_read_per_market_because_it_varies() -> None:
    """``minimumTradeQty`` is NOT constant across the capture.

    Unlike ``feeCoefficient`` and ``orderPriceMinTickSize``, this field takes
    two distinct values, so a global constant would be wrong for one of them.
    """
    payloads = iter_captured_market_payloads()
    assert {p["market"]["minimumTradeQty"] for p in payloads} == {1, 0.01}

    increments = {
        parse_binary_option(p, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT).size_increment
        for p in payloads
    }
    assert increments == {Quantity.from_str("1"), Quantity.from_str("0.01")}


def test_minimum_trade_qty_absence_aborts_rather_than_defaulting(
    open_market: dict[str, Any],
) -> None:
    del open_market["market"]["minimumTradeQty"]
    with pytest.raises(InstrumentDefinitionError, match="minimumTradeQty"):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def test_market_metadata_missing_tick_size_raises_rather_than_defaulting(
    open_market: dict[str, Any],
) -> None:
    del open_market["market"]["orderPriceMinTickSize"]
    with pytest.raises(InstrumentDefinitionError, match="orderPriceMinTickSize"):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def test_market_metadata_missing_minimum_trade_qty_raises(
    open_market: dict[str, Any],
) -> None:
    del open_market["market"]["minimumTradeQty"]
    with pytest.raises(InstrumentDefinitionError, match="minimumTradeQty"):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


@pytest.mark.parametrize("tick", [0, -0.01, "abc", None, [1]])
def test_non_positive_or_malformed_tick_size_is_rejected(
    open_market: dict[str, Any], tick: object
) -> None:
    open_market["market"]["orderPriceMinTickSize"] = tick
    with pytest.raises(InstrumentDefinitionError):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def test_missing_market_envelope_key_raises(open_market: dict[str, Any]) -> None:
    with pytest.raises(VenuePayloadError, match="market"):
        parse_binary_option(
            {"notMarket": open_market["market"]}, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT
        )


def test_non_usd_currency_is_rejected(open_market: dict[str, Any]) -> None:
    open_market["market"]["marketSides"][0]["quote"]["currency"] = "EUR"
    with pytest.raises(InstrumentDefinitionError, match="EUR"):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def test_a_climate_market_with_unrecognised_slug_grammar_is_rejected_loudly(
    open_market: dict[str, Any],
) -> None:
    """A climate market MUST yield a ``city_day_cluster_id``.

    The Phase 5 correlated-exposure cap keys on it, so an unparseable climate
    slug is an instrument definition failure, not a field to leave blank.
    """
    open_market["market"]["slug"] = "tc-temp-somewhere-else"
    open_market["market"]["marketSides"][0]["identifier"] = "tc-temp-somewhere-else"
    open_market["market"]["marketSides"][1]["identifier"] = "tc-temp-somewhere-else"
    with pytest.raises(InstrumentDefinitionError, match="climate"):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def test_a_market_side_identifier_disagreeing_with_the_slug_is_rejected(
    open_market: dict[str, Any],
) -> None:
    open_market["market"]["marketSides"][1]["identifier"] = "some-other-slug"
    with pytest.raises(InstrumentDefinitionError):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def test_a_market_without_exactly_one_long_side_is_rejected(
    open_market: dict[str, Any],
) -> None:
    open_market["market"]["marketSides"][1]["long"] = True
    with pytest.raises(InstrumentDefinitionError):
        parse_binary_option(open_market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


# ---------------------------------------------------------------------------
# parse_book_top
# ---------------------------------------------------------------------------


def test_book_top_parses_to_decimal_not_float(open_book: dict[str, Any]) -> None:
    top = parse_book_top(open_book)
    assert all(isinstance(value, Decimal) for value in top)
    assert top == (
        Decimal("0.5300"),
        Decimal("123.4800"),
        Decimal("0.5400"),
        Decimal("4.0000"),
    )


def test_an_empty_book_is_rejected_loudly(closed_book: dict[str, Any]) -> None:
    """The closed-market capture has ``bids: []`` and ``offers: []``."""
    with pytest.raises(VenuePayloadError):
        parse_book_top(closed_book)


def test_a_crossed_book_is_rejected(open_book: dict[str, Any]) -> None:
    open_book["marketData"]["offers"][0]["px"]["value"] = "0.4000"
    with pytest.raises(VenuePayloadError, match="crossed"):
        parse_book_top(open_book)


@pytest.mark.parametrize("value", ["-0.01", "1.01", "abc", ""])
def test_a_price_outside_the_binary_range_is_rejected(
    open_book: dict[str, Any], value: str
) -> None:
    open_book["marketData"]["bids"][0]["px"]["value"] = value
    with pytest.raises(VenuePayloadError):
        parse_book_top(open_book)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "Infinity"])
def test_a_non_positive_or_non_finite_size_is_rejected(
    open_book: dict[str, Any], value: str
) -> None:
    open_book["marketData"]["bids"][0]["qty"] = value
    with pytest.raises(VenuePayloadError):
        parse_book_top(open_book)


def test_a_book_level_in_a_foreign_currency_is_rejected(open_book: dict[str, Any]) -> None:
    open_book["marketData"]["bids"][0]["px"]["currency"] = "EUR"
    with pytest.raises(VenuePayloadError, match="EUR"):
        parse_book_top(open_book)


# ---------------------------------------------------------------------------
# parse_quote_tick
# ---------------------------------------------------------------------------


def test_quote_tick_uses_per_market_tick_size_for_precision(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    tick = parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)
    assert tick.instrument_id == open_instrument.id
    assert tick.bid_price == Price.from_str("0.53")
    assert tick.bid_price.precision == open_instrument.price_precision
    assert tick.ask_price == Price.from_str("0.54")
    assert tick.bid_size == Quantity.from_str("123.48")
    assert tick.bid_size.precision == open_instrument.size_precision
    assert tick.ask_size == Quantity.from_str("4.00")


def test_ts_event_comes_from_transact_time_and_ts_init_from_the_caller(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    tick = parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)
    assert tick.ts_event == parse_rfc3339_nanos(
        "2026-08-25T00:19:48.120237895Z", field="transactTime"
    )
    assert tick.ts_init == TS_INIT
    assert tick.ts_event != tick.ts_init


def test_precision_is_validated_before_price_construction(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    """A value carrying more significant decimals than the instrument allows is
    refused in Python -- never rounded, never handed to the Rust constructor.
    """
    open_book["marketData"]["bids"][0]["px"]["value"] = "0.535"
    with pytest.raises(VenuePayloadError, match="precision"):
        parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)


def test_size_precision_is_validated_before_quantity_construction(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    open_book["marketData"]["bids"][0]["qty"] = "123.481"
    with pytest.raises(VenuePayloadError, match="precision"):
        parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)


def test_trailing_zeros_beyond_the_precision_are_not_a_precision_error(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    """``"0.5300"`` at precision 2 is exactly representable; only significant
    digits below the increment are an error.
    """
    tick = parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)
    assert str(tick.bid_price) == "0.53"


def test_a_quote_for_a_different_market_slug_is_rejected(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    open_book["marketData"]["marketSlug"] = "tc-temp-nychigh-2026-08-25-gte79lt80f"
    with pytest.raises(VenuePayloadError):
        parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)


def test_a_missing_transact_time_is_rejected(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    del open_book["marketData"]["transactTime"]
    with pytest.raises(VenuePayloadError, match="transactTime"):
        parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)


def test_the_documented_websocket_market_data_frame_parses(
    open_instrument: BinaryOption,
) -> None:
    """Frame copied verbatim from the committed docs snapshot
    ``api-reference_websocket_markets_2026-08-25.md`` (marketSlug and prices
    adjusted only to match the captured instrument's tick size, which the
    snapshot's illustrative 0.555 does not).
    """
    frame = {
        "requestId": "md-sub-1",
        "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
        "marketData": {
            "marketSlug": "tc-temp-nychigh-2026-08-25-lt79f",
            "bids": [{"px": {"value": "0.55", "currency": "USD"}, "qty": "0.50"}],
            "offers": [{"px": {"value": "0.56", "currency": "USD"}, "qty": "0.80"}],
            "state": "MARKET_STATE_OPEN",
            "transactTime": "2026-08-25T10:30:00Z",
        },
    }
    tick = parse_quote_tick(frame, instrument=open_instrument, ts_init=TS_INIT)
    assert tick.bid_price == Price.from_str("0.55")
    assert tick.ask_size == Quantity.from_str("0.80")
    assert tick.ts_event == parse_rfc3339_nanos("2026-08-25T10:30:00Z", field="transactTime")


# ---------------------------------------------------------------------------
# Constant documentation must stay paired with its constant (F5)
# ---------------------------------------------------------------------------


def _sphinx_doc_comment_for(source: str, constant: str) -> str:
    """Return the ``#:`` comment block immediately preceding ``constant``.

    ``#:`` is Sphinx's "this documents the next assignment" marker, so the
    pairing is positional: a symbol inserted between a ``#:`` block and the
    assignment it described silently steals the documentation.
    """
    lines = source.splitlines()
    index = next(
        i
        for i, line in enumerate(lines)
        if line.startswith((f"{constant}:", f"{constant} ="))
    )
    block: list[str] = []
    cursor = index - 1
    while cursor >= 0 and lines[cursor].startswith("#:"):
        block.append(lines[cursor])
        cursor -= 1
    return "\n".join(reversed(block))


@pytest.mark.parametrize(
    "constant",
    [
        "FEE_COEFFICIENT_KEY",
        "FEE_SCHEDULE_STATUS_KEY",
        "FEE_SCHEDULE_STATUS_KNOWN",
        "FEE_SCHEDULE_STATUS_UNKNOWN",
    ],
)
def test_every_fee_constant_carries_its_own_doc_comment(constant: str) -> None:
    """A ``#:`` block inserted above the wrong symbol documents the wrong thing.

    ``FEE_COEFFICIENT_KEY`` was added BETWEEN the ``#:`` comment describing
    ``FEE_SCHEDULE_STATUS_KEY`` and that constant's own assignment. The result:
    ``FEE_SCHEDULE_STATUS_KEY`` -- the constant the entire F1 barrier hangs on
    -- silently lost its documentation, and ``FEE_COEFFICIENT_KEY`` acquired
    two contradictory description lines.
    """
    source = Path(parsing.__file__).read_text(encoding="utf-8")

    block = _sphinx_doc_comment_for(source, constant)

    assert block, f"{constant} has no `#:` doc comment"


def test_the_status_key_doc_comment_describes_the_status_and_not_the_coefficient() -> None:
    """Non-vacuity: presence is not enough, the text must be about the right symbol."""
    source = Path(parsing.__file__).read_text(encoding="utf-8")

    status = _sphinx_doc_comment_for(source, "FEE_SCHEDULE_STATUS_KEY").lower()
    coefficient = _sphinx_doc_comment_for(source, "FEE_COEFFICIENT_KEY").lower()

    assert "resolution state" in status or "fee-schedule" in status
    assert "theta" in coefficient
    assert "theta" not in status, "the status key's comment must not describe theta"
