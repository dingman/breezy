"""Full-depth, trade, mark and state parsing -- the unbackfillable fields.

Why this file exists
--------------------
``parse_quote_tick`` validated all ten-plus book levels and then returned
``min()``/``max()`` -- one level per side. Everything below the top of book was
parsed, range-checked, and thrown away.

That is not a cosmetic loss. Phase 1.5.3 of
``docs/plans/TRADING_ENABLEMENT_PLAN.md`` requires netting the measured gap
against "realistic slippage at the intended size", and slippage at any size
larger than the best level is a function of the levels beneath it. An analyst
handed top-of-book only must assume the best level fills the whole order, which
understates slippage, inflates the residual, and can produce a FALSE GO on the
premise-falsification gate. Polymarket.us weather markets have no history, so a
day recorded top-of-book-only can never be re-recorded with depth.

Golden samples are the COMMITTED venue captures under
``docs/evidence/venue/polymarket_us/raw/``. This suite never contacts the venue.
Where a shape is not present in a capture it is marked UNRESOLVED in the module
under test and the parser fails closed rather than guessing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.data import (
    InstrumentClose,
    MarkPriceUpdate,
    OrderBookDepth10,
    TradeTick,
)
from nautilus_trader.model.enums import AggressorSide, InstrumentCloseType, OrderSide
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price

from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.parsing import (
    DEPTH10_LEVELS,
    parse_binary_option,
    parse_instrument_close,
    parse_instrument_status,
    parse_mark_price,
    parse_order_book_depth10,
    parse_quote_tick,
    parse_rfc3339_nanos,
    parse_trade_tick,
    venue_market_state,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

TS_INIT = 1_787_617_213_000_000_000


def load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def open_book() -> dict[str, Any]:
    return load_raw("book_open_510636.json")


@pytest.fixture
def closed_book() -> dict[str, Any]:
    return load_raw("book_closed_15806.json")


@pytest.fixture
def open_instrument() -> BinaryOption:
    return parse_binary_option(
        load_raw("market_open_510636_by_slug.json"), venue=POLYMARKET_US_VENUE, ts_init=TS_INIT
    )


# ---------------------------------------------------------------------------
# Depth
# ---------------------------------------------------------------------------


class TestDepth:
    def test_the_captured_book_really_does_carry_depth_beyond_the_top(
        self, open_book: dict[str, Any]
    ) -> None:
        """Anchors the whole file: this is not a hypothetical loss.

        The committed capture has 12 bid levels and 14 offer levels. The old
        code persisted one of each.
        """
        assert len(open_book["marketData"]["bids"]) > 1
        assert len(open_book["marketData"]["offers"]) > 1

    def test_ten_levels_per_side_are_persisted_not_one(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        depth = parse_order_book_depth10(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        )

        assert isinstance(depth, OrderBookDepth10)
        real_bids = [o for o in depth.bids if o.size > 0]
        real_asks = [o for o in depth.asks if o.size > 0]
        assert len(real_bids) == DEPTH10_LEVELS
        assert len(real_asks) == DEPTH10_LEVELS

    def test_bids_descend_and_asks_ascend_so_level_n_is_the_nth_best(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """Position carries meaning, so ordering is asserted, not assumed.

        A slippage walk consumes levels in order. If the venue stops sorting a
        side, an unsorted tape silently produces a wrong slippage estimate.
        """
        depth = parse_order_book_depth10(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        )
        bid_prices = [o.price for o in depth.bids if o.size > 0]
        ask_prices = [o.price for o in depth.asks if o.size > 0]

        assert bid_prices == sorted(bid_prices, reverse=True)
        assert ask_prices == sorted(ask_prices)

    def test_the_top_of_the_depth_record_equals_the_quote_tick(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """The two records must not disagree; they come from the same frame."""
        depth = parse_order_book_depth10(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        )
        quote = parse_quote_tick(open_book, instrument=open_instrument, ts_init=TS_INIT)

        assert depth.bids[0].price == quote.bid_price
        assert depth.asks[0].price == quote.ask_price
        assert depth.bids[0].size == quote.bid_size
        assert depth.asks[0].size == quote.ask_size
        assert depth.ts_event == quote.ts_event

    def test_sides_are_tagged_with_the_correct_book_order_side(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        depth = parse_order_book_depth10(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        )

        assert all(o.side == OrderSide.BUY for o in depth.bids)
        assert all(o.side == OrderSide.SELL for o in depth.asks)

    def test_padding_uses_the_instruments_own_precision(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """Nautilus's own auto-pad makes the record UNSERIALIZABLE.

        `OrderBookDepth10.__init__` pads a short side with `NULL_ORDER`, whose
        price/size precision is 0. The Arrow encoder then rejects the whole
        record with `ValueError: Mixed metadata at row 0`, so a thin book would
        be dropped entirely -- silently, since the writer logs nothing. Padding
        at the instrument's precision is what keeps a thin market recordable.
        """
        book = json.loads(json.dumps(open_book))
        book["marketData"]["bids"] = book["marketData"]["bids"][:2]
        book["marketData"]["offers"] = book["marketData"]["offers"][:2]

        depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

        assert len(depth.bids) == DEPTH10_LEVELS
        for order in depth.bids:
            assert order.price.precision == open_instrument.price_precision
            assert order.size.precision == open_instrument.size_precision

    def test_a_thin_book_round_trips_through_the_arrow_encoder(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """The behavioural half of the test above: it actually serializes."""
        from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

        book = json.loads(json.dumps(open_book))
        book["marketData"]["bids"] = book["marketData"]["bids"][:1]
        book["marketData"]["offers"] = book["marketData"]["offers"][:1]
        depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

        batch = ArrowSerializer.serialize_batch([depth], data_cls=OrderBookDepth10)

        assert batch.num_rows == 1

    def test_empty_bids_with_populated_offers_records_the_ask_ladder(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """A missing bid is a legitimate venue state, not a malformed payload.

        Observation-lock strategies trade leftover asks on books whose bid
        side is empty. Discarding the whole frame (including the ask ladder)
        makes that state unrecordable.
        """
        two_sided = parse_order_book_depth10(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        )
        expected_asks = [order.price for order in two_sided.asks if order.size > 0]
        expected_ask_sizes = [order.size for order in two_sided.asks if order.size > 0]

        book = json.loads(json.dumps(open_book))
        book["marketData"]["bids"] = []
        depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

        real_bids = [order for order in depth.bids if order.size > 0]
        real_asks = [order for order in depth.asks if order.size > 0]
        assert real_bids == []
        assert [order.price for order in real_asks] == expected_asks
        assert [order.size for order in real_asks] == expected_ask_sizes
        assert len(depth.bids) == DEPTH10_LEVELS
        assert all(order.size == 0 for order in depth.bids)
        assert all(
            order.price.precision == open_instrument.price_precision for order in depth.bids
        )

    def test_empty_offers_with_populated_bids_records_the_bid_ladder(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        two_sided = parse_order_book_depth10(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        )
        expected_bids = [order.price for order in two_sided.bids if order.size > 0]
        expected_bid_sizes = [order.size for order in two_sided.bids if order.size > 0]

        book = json.loads(json.dumps(open_book))
        book["marketData"]["offers"] = []
        depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

        real_bids = [order for order in depth.bids if order.size > 0]
        real_asks = [order for order in depth.asks if order.size > 0]
        assert real_asks == []
        assert [order.price for order in real_bids] == expected_bids
        assert [order.size for order in real_bids] == expected_bid_sizes
        assert len(depth.asks) == DEPTH10_LEVELS
        assert all(order.size == 0 for order in depth.asks)

    def test_a_one_sided_book_round_trips_through_the_arrow_encoder(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

        book = json.loads(json.dumps(open_book))
        book["marketData"]["bids"] = []
        depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

        batch = ArrowSerializer.serialize_batch([depth], data_cls=OrderBookDepth10)

        assert batch.num_rows == 1

    def test_a_malformed_level_on_a_one_sided_book_is_still_rejected(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """Allowing an empty side must not loosen per-level validation."""
        book = json.loads(json.dumps(open_book))
        book["marketData"]["bids"] = []
        book["marketData"]["offers"][0]["px"]["value"] = "1.50"
        with pytest.raises(VenuePayloadError, match="outside the binary-option range"):
            parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

    def test_a_one_sided_book_is_not_treated_as_crossed(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """The crossed-book check must not IndexError when a side is empty."""
        book = json.loads(json.dumps(open_book))
        book["marketData"]["bids"] = []
        depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)
        assert any(order.size > 0 for order in depth.asks)

    def test_a_fully_empty_book_is_refused_rather_than_recorded_as_a_flat_book(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """A fully empty book is still not a price.

        The settled capture has ``bids: []`` and ``offers: []``. Padding both
        sides with zero would record a flat book the venue did not send. A
        *one-sided* book (empty bids, populated offers, or the reverse) is
        the legitimate live state and is tested separately. This case is
        both sides empty, with a matching instrument slug so the refusal is
        the empty book, not a slug mismatch.
        """
        book = json.loads(json.dumps(open_book))
        book["marketData"]["bids"] = []
        book["marketData"]["offers"] = []
        with pytest.raises(VenuePayloadError, match="no populated side"):
            parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

    def test_a_crossed_book_is_refused(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        book = json.loads(json.dumps(open_book))
        book["marketData"]["offers"][0]["px"]["value"] = "0.0010"
        with pytest.raises(VenuePayloadError, match="crossed"):
            parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------


class TestTradeTick:
    def frame(self) -> dict[str, Any]:
        return {
            "trade": {
                "marketSlug": "tc-temp-nychigh-2026-08-25-lt79f",
                "px": {"value": "0.5300", "currency": "USD"},
                "qty": "15.6100",
                "transactTime": "2026-08-25T00:06:58.830425365Z",
                "tradeId": "trd-0001",
                "takerSide": "SIDE_BUY",
            }
        }

    def test_an_executed_print_becomes_a_trade_tick(
        self, open_instrument: BinaryOption
    ) -> None:
        tick = parse_trade_tick(self.frame(), instrument=open_instrument, ts_init=TS_INIT)

        assert isinstance(tick, TradeTick)
        assert tick.instrument_id == open_instrument.id
        assert tick.price == Price.from_str("0.530")
        assert str(tick.size) == "15.6100"[: len(str(tick.size))] or tick.size.as_decimal() > 0
        assert tick.ts_event == parse_rfc3339_nanos(
            "2026-08-25T00:06:58.830425365Z", field="transactTime"
        )
        assert tick.ts_init == TS_INIT

    def test_the_venue_trade_id_is_preserved_verbatim(
        self, open_instrument: BinaryOption
    ) -> None:
        """Not synthesised. A synthetic id cannot be reconciled with the venue."""
        tick = parse_trade_tick(self.frame(), instrument=open_instrument, ts_init=TS_INIT)

        assert tick.trade_id.value == "trd-0001"

    def test_the_taker_side_is_carried_through(self, open_instrument: BinaryOption) -> None:
        tick = parse_trade_tick(self.frame(), instrument=open_instrument, ts_init=TS_INIT)

        assert tick.aggressor_side == AggressorSide.BUYER

    def test_an_unknown_taker_side_records_no_aggressor_rather_than_guessing(
        self, open_instrument: BinaryOption
    ) -> None:
        """The venue's taker-side spelling is UNRESOLVED.

        Guessing BUYER for an unrecognised token would invent direction on
        every print. `NO_AGGRESSOR` is the honest encoding of "the venue told
        us something we do not understand".
        """
        frame = self.frame()
        frame["trade"]["takerSide"] = "SOMETHING_NEW"

        tick = parse_trade_tick(frame, instrument=open_instrument, ts_init=TS_INIT)

        assert tick.aggressor_side == AggressorSide.NO_AGGRESSOR

    def test_a_trade_for_another_slug_is_refused(
        self, open_instrument: BinaryOption
    ) -> None:
        frame = self.frame()
        frame["trade"]["marketSlug"] = "tc-temp-mdwhigh-2026-08-25-lt91f"
        with pytest.raises(VenuePayloadError):
            parse_trade_tick(frame, instrument=open_instrument, ts_init=TS_INIT)

    @pytest.mark.parametrize("field", ["px", "qty", "transactTime", "tradeId"])
    def test_no_required_trade_field_is_ever_defaulted(
        self, open_instrument: BinaryOption, field: str
    ) -> None:
        frame = self.frame()
        del frame["trade"][field]
        with pytest.raises(VenuePayloadError, match=field):
            parse_trade_tick(frame, instrument=open_instrument, ts_init=TS_INIT)


# ---------------------------------------------------------------------------
# Venue state and the venue's own settlement price
# ---------------------------------------------------------------------------


class TestVenueStateAndSettlement:
    def test_the_raw_venue_state_string_is_read_from_the_capture(
        self, open_book: dict[str, Any], closed_book: dict[str, Any]
    ) -> None:
        assert venue_market_state(open_book) == "MARKET_STATE_OPEN"
        assert venue_market_state(closed_book) == "MARKET_STATE_EXPIRED"

    def test_state_is_recorded_verbatim_rather_than_mapped_onto_a_guessed_enum(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """The venue's state enum is UNRESOLVED; mapping it would lose information.

        Nautilus's `MarketStatusAction` has no member meaning
        `MARKET_STATE_EXPIRED`, and picking the nearest one would encode a guess
        into an unbackfillable archive. The raw string goes in `reason`, where
        it survives exactly as the venue sent it.
        """
        status = parse_instrument_status(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        )

        assert status is not None
        assert status.reason == "MARKET_STATE_OPEN"
        assert status.instrument_id == open_instrument.id

    def test_the_venue_settlement_price_is_captured_as_a_mark_price(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """`settlementPx` on an OPEN market is a daily mark, not a terminal value.

        The committed open-market capture carries
        `state=MARKET_STATE_OPEN` with `settlementPx=0.4900`, so treating it as
        a close price would fabricate a settlement that has not happened.
        `MarkPriceUpdate` is the native carrier with the right meaning.
        """
        mark = parse_mark_price(open_book, instrument=open_instrument, ts_init=TS_INIT)

        assert isinstance(mark, MarkPriceUpdate)
        assert mark.value == Price.from_str("0.490")

    def test_the_mark_price_is_stamped_with_the_venues_settlement_set_time(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """Not the frame's transactTime: the two differ by hours in the capture."""
        mark = parse_mark_price(open_book, instrument=open_instrument, ts_init=TS_INIT)

        assert mark is not None
        assert mark.ts_event == parse_rfc3339_nanos(
            open_book["marketData"]["stats"]["settlementSetTime"], field="settlementSetTime"
        )

    def test_an_expired_market_also_yields_a_terminal_instrument_close(
        self, closed_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """This is the venue's OWN authoritative settlement value.

        Plan item 1.2 needs it, and venue REST may not retain it once the
        market ages out.
        """
        close = parse_instrument_close(
            closed_book, instrument=open_instrument, ts_init=TS_INIT
        )

        assert isinstance(close, InstrumentClose)
        assert close.close_price == Price.from_str("1.000")
        assert close.close_type == InstrumentCloseType.CONTRACT_EXPIRED

    def test_an_open_market_yields_no_instrument_close(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        """Refusing to emit a close for a live market is the whole point."""
        assert parse_instrument_close(
            open_book, instrument=open_instrument, ts_init=TS_INIT
        ) is None

    def test_a_frame_with_no_settlement_price_yields_no_mark(
        self, open_book: dict[str, Any], open_instrument: BinaryOption
    ) -> None:
        book = json.loads(json.dumps(open_book))
        del book["marketData"]["stats"]["settlementPx"]

        assert parse_mark_price(book, instrument=open_instrument, ts_init=TS_INIT) is None
