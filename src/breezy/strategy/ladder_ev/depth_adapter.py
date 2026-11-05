"""Fail-closed ask-level tuples from native Nautilus books (spec §4).

Does **not** call ``weather_common.ladder.ask_levels`` (that helper falls
back to top-of-book). Pad-skipping matches ``depth10.best_order`` plus the
spec's ``price > 0`` conjunct.
"""

from __future__ import annotations

from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import OrderBookDepth10

from breezy.strategy.weather_common.costs import NoExecutableDepthError

__all__ = ["bid_levels_from_book", "depth_levels_from_book"]


def depth_levels_from_book(book: OrderBook | OrderBookDepth10) -> list[tuple[float, float]]:
    """Real ask levels ``(price, size)``, ascending; no top-of-book fallback.

    Accepts native ``OrderBook`` (``.asks()`` → ``BookLevel``) or
    ``OrderBookDepth10`` (``.asks`` → ``list[BookOrder]``). Skips
    ``price <= 0`` / ``size <= 0`` padding. Raises
    :class:`NoExecutableDepthError` when nothing remains.
    """
    raw = book.asks if isinstance(book, OrderBookDepth10) else book.asks()
    levels: list[tuple[float, float]] = []
    for item in raw:
        price = float(item.price)
        raw_size = item.size() if callable(item.size) else item.size
        size = float(raw_size)
        if price > 0.0 and size > 0.0:
            levels.append((price, size))
    levels.sort(key=lambda pair: pair[0])
    if not levels:
        raise NoExecutableDepthError(
            "No executable ask depth; refusing to price a fill against a book "
            "that cannot supply one. An empty or padded book is a no-trade, "
            "never a top-of-book fallback"
        )
    return levels


def bid_levels_from_book(book: OrderBook | OrderBookDepth10) -> list[tuple[float, float]]:
    """Invert YES bids to NO asks ``(1 - bid, size)``, then sort ascending.

    Fail-closed: an empty or padded bid side raises
    :class:`NoExecutableDepthError` with reason ``no_bid_side``. Never
    assume a bid (E2).
    """
    raw = book.bids if isinstance(book, OrderBookDepth10) else book.bids()
    levels: list[tuple[float, float]] = []
    for item in raw:
        price = float(item.price)
        raw_size = item.size() if callable(item.size) else item.size
        size = float(raw_size)
        if price > 0.0 and size > 0.0:
            levels.append((1.0 - price, size))
    levels.sort(key=lambda pair: pair[0])
    if not levels:
        raise NoExecutableDepthError(
            "no_bid_side: No executable bid depth; refusing to price a NO fill "
            "against a book that cannot supply a bid. An empty or padded bid "
            "side is a no-trade, never an assumed bid"
        )
    return levels
