"""S2 bid ladder + the NO-side price identity ``NO_ask == 1 - YES_bid``.

Plan `NO_SIDE_EDGE_2026-09-14.md` section 4 S2 / section 2 (`NO_ask = 1 - YES_bid`,
size available at that price is the YES bid size). ``MarketQuote.bid_ladder``
and ``market_quote_from_depth``'s ``include_bid_ladder`` are additive: this
file proves the existing ``ask_ladder``-only behaviour is unedited (default
``False``, ``None``) and adds the NO-side derivation off the SAME recorded
Depth10 frame -- no re-recording, no NO-side subscription needed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from breezy.strategy.depth10 import market_quote_from_depth
from breezy.strategy.weather_common.models import MarketQuote

TS_INIT = 1_787_617_213_000_000_000
DEPTH10_LEVELS = 10


def _pad(
    side: OrderSide, levels: tuple[tuple[str, int], ...], *, precision: int = 2
) -> list[BookOrder]:
    filler = BookOrder(side, Price(0, precision), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    while len(orders) < DEPTH10_LEVELS:
        orders.append(filler)
    return orders


def _depth(
    *,
    bids: tuple[tuple[str, int], ...],
    asks: tuple[tuple[str, int], ...],
    instrument_id: str = "TEST-GE80.POLYMARKET_US",
) -> OrderBookDepth10:
    bid_orders = _pad(OrderSide.BUY, bids)
    ask_orders = _pad(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=InstrumentId.from_str(instrument_id),
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1 if o.size.as_double() > 0 else 0 for o in bid_orders],
        ask_counts=[1 if o.size.as_double() > 0 else 0 for o in ask_orders],
        flags=0,
        sequence=0,
        ts_event=TS_INIT,
        ts_init=TS_INIT,
    )


def test_include_bid_ladder_defaults_false_and_is_none() -> None:
    depth = _depth(bids=(("0.40", 1), ("0.39", 2)), asks=(("0.42", 1),))
    quote = market_quote_from_depth(depth)
    assert quote is not None
    assert quote.bid_ladder is None
    # Existing ask_ladder-only behaviour is byte-identical: still None by default.
    assert quote.ask_ladder is None


def test_include_bid_ladder_populates_best_price_first() -> None:
    depth = _depth(bids=(("0.40", 1), ("0.39", 2)), asks=(("0.42", 1),))
    quote = market_quote_from_depth(depth, include_bid_ladder=True)
    assert quote is not None
    assert quote.bid_ladder == ((0.40, 1.0), (0.39, 2.0))


def test_a_fully_padded_bid_side_yields_no_bid_ladder() -> None:
    depth = _depth(bids=(), asks=(("0.42", 1),))
    quote = market_quote_from_depth(depth, include_bid_ladder=True)
    assert quote is not None
    assert quote.bid_ladder is None


def test_marketquote_bid_ladder_field_is_additive_and_defaults_none() -> None:
    quote = MarketQuote(
        instrument_id="X.POLYMARKET_US",
        bid=0.40,
        ask=0.42,
        bid_size=1.0,
        ask_size=1.0,
        ts_event=__import__("datetime").datetime.now(tz=__import__("datetime").UTC),
    )
    assert quote.bid_ladder is None


def test_no_ask_equals_one_minus_yes_bid_off_the_same_depth10_frame() -> None:
    """NO_ask = 1 - YES_bid, size at that price = the YES bid size (Decimal)."""
    depth = _depth(bids=(("0.35", 4),), asks=(("0.42", 1),))
    yes_quote = market_quote_from_depth(depth, include_bid_ladder=True)
    assert yes_quote is not None
    assert yes_quote.bid is not None and yes_quote.bid_size is not None

    no_ask = Decimal(1) - Decimal(str(yes_quote.bid))
    no_ask_size = yes_quote.bid_size

    assert no_ask == Decimal("0.65")
    assert no_ask_size == pytest.approx(4.0)
