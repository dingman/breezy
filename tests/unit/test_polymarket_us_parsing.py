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

from breezy.adapters.polymarket_us.errors import (
    FeeScheduleUnknownError,
    InstrumentDefinitionError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.parsing import (
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_UNKNOWN,
    assert_fee_schedule_known,
    parse_binary_option,
    parse_book_top,
    parse_quote_tick,
    parse_rfc3339_nanos,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE

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


def test_fee_coefficient_is_never_mapped_to_a_maker_or_taker_fee_rate(
    open_instrument: BinaryOption,
) -> None:
    """``feeCoefficient`` is recorded verbatim and never promoted to a rate.

    ``BUILD_PLAN`` Phase 1 downgraded the .us fee schedule to ``[UNKNOWN]``;
    ``feeCoefficient`` is the ``theta`` of ``fee = theta * C * p * (1 - p)``,
    not a flat rate on notional, and Nautilus's ``maker_fee``/``taker_fee``
    are flat rates. Copying 0.06 across would invent a number.

    REPLACES an earlier version of this test that asserted
    ``open_instrument.maker_fee == Decimal(0)`` and
    ``open_instrument.taker_fee == Decimal(0)`` as the *fail-closed* property.
    Those assertions encoded the defect: the zero is a real, typed value that
    ``MakerTakerFeeModel`` will happily multiply by
    (``backtest/models/fee.pyx:96-99``), so certifying it certified a
    zero-fee illusion. The hazard and its guard are now pinned in
    ``tests/unit/test_polymarket_us_fee_guard.py``; what remains here is the
    only claim this test was ever entitled to make -- that ``theta`` is not
    copied into a fee field.
    """
    info = open_instrument.info
    assert info[FEE_SCHEDULE_STATUS_KEY] == FEE_SCHEDULE_STATUS_UNKNOWN
    assert info["fee_coefficient"] == "0.06"
    assert Decimal(info["fee_coefficient"]) == Decimal("0.06")

    with pytest.raises(FeeScheduleUnknownError):
        assert_fee_schedule_known(open_instrument)


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
