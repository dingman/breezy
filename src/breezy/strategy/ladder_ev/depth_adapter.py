"""Fail-closed ask-level tuples from native Nautilus books (spec §4).

Does **not** call ``weather_common.ladder.ask_levels`` (that helper falls
back to top-of-book). Pad-skipping matches ``depth10.best_order`` plus the
spec's ``price > 0`` conjunct.
"""

from __future__ import annotations

from nautilus_trader.model.book import OrderBook
from nautilus_trader.model.data import OrderBookDepth10

from breezy.strategy.weather_common.costs import NoExecutableDepthError

__all__ = ["depth_levels_from_book"]


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
