"""T5: ``depth_levels_from_book`` is fail-closed (spec §4 / §13)."""

from __future__ import annotations

import pytest
from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import BookType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from breezy.strategy.ladder_ev.depth_adapter import depth_levels_from_book
from breezy.strategy.weather_common.costs import NoExecutableDepthError

_INSTRUMENT_ID = InstrumentId.from_str("TEST.POLYMARKET_US")


def _filler(side: OrderSide) -> BookOrder:
    return BookOrder(side, Price(0, 2), Quantity(0, 0), 0)


def _pad(side: OrderSide, levels: tuple[tuple[str, int], ...]) -> tuple[list[BookOrder], list[int]]:
    orders = [
        BookOrder(side, Price.from_str(price), Quantity(size, 0), 0) for price, size in levels
    ]
    counts = [1] * len(orders)
    while len(orders) < 10:
        orders.append(_filler(side))
        counts.append(0)
    return orders, counts


def _depth(asks: tuple[tuple[str, int], ...]) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, (("0.01", 10),))
    ask_orders, ask_counts = _pad(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=_INSTRUMENT_ID,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=0,
        ts_init=0,
    )


def test_empty_order_book_raises() -> None:
    book = OrderBook(_INSTRUMENT_ID, BookType.L2_MBP)
    with pytest.raises(NoExecutableDepthError):
        depth_levels_from_book(book)


def test_padded_depth10_raises() -> None:
    with pytest.raises(NoExecutableDepthError):
        depth_levels_from_book(_depth(()))


def test_never_returns_a_size_zero_level() -> None:
    levels = depth_levels_from_book(_depth((("0.40", 3), ("0.41", 7))))
    assert levels
    assert all(price > 0.0 and size > 0.0 for price, size in levels)
    assert levels == [(0.40, 3.0), (0.41, 7.0)]


def test_order_book_levels_are_ascending_real_asks() -> None:
    book = OrderBook(_INSTRUMENT_ID, BookType.L2_MBP)
    book.add(BookOrder(OrderSide.SELL, Price.from_str("0.52"), Quantity.from_int(2), 1), 1)
    book.add(BookOrder(OrderSide.SELL, Price.from_str("0.50"), Quantity.from_int(4), 2), 2)
    levels = depth_levels_from_book(book)
    assert levels == [(0.50, 4.0), (0.52, 2.0)]
    assert all(size > 0.0 for _, size in levels)
