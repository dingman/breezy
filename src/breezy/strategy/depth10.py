"""Read native ``OrderBookDepth10`` without treating the size-0 pad as a price.

``OrderBookDepth10`` always carries ten levels per side. An empty (or short)
side is padded with ``Price(0)`` / ``Quantity(0)`` at the instrument's own
precision so the Arrow encoder will accept a thin or one-sided book -- see
``parse_order_book_depth10``. That pad sits at index 0 on a missing side, so
``depth.bids[0]`` is a fabricated 0.00 and ``mid = ask / 2``.

Native ``OrderBookDepth10.to_quote_tick()`` has the same flaw; do not quote
from it. Two-sided quotes stay on ``parse_quote_tick`` / ``parse_book_top``.
Depth consumers share this module so the skip-if-zero loop is not pasted
into every strategy.

``MarketQuote`` already expresses a missing side as ``None`` (``bid`` / ``ask``
are ``float | None``; ``mid`` is only derived when both are present). This
module is the one construction seam that honours that.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from nautilus_trader.model.data import BookOrder, OrderBookDepth10

from breezy.strategy.weather_common.models import MarketQuote

__all__ = ["best_order", "market_quote_from_depth"]


def best_order(side: Sequence[BookOrder]) -> BookOrder | None:
    """Best populated level of a Depth10 ladder, skipping the size-0 pad.

    Matches ``RestingLadderStrategy._best``: a zero-size level is the Arrow
    filler, not a quote. A genuinely thin but real level (``size > 0``) is
    returned even when that size is 1.
    """
    for level in side:
        if level.size > 0:
            return level
    return None


def market_quote_from_depth(
    depth: OrderBookDepth10,
    *,
    include_ask_ladder: bool = False,
) -> MarketQuote | None:
    """Build a ``MarketQuote`` from a Depth10 snapshot, pad-safe.

    A missing side is ``None``, never 0.0. A fully empty (both-sides-padded)
    book is not a quote. ``mid`` stays ``None`` unless both sides are
    populated -- ``MarketQuote.__post_init__`` will not average a real ask
    against a synthetic zero bid.
    """
    bid = best_order(depth.bids)
    ask = best_order(depth.asks)
    if bid is None and ask is None:
        return None
    ask_ladder: tuple[tuple[float, float], ...] | None = None
    if include_ask_ladder:
        populated = tuple(
            (float(level.price), float(level.size)) for level in depth.asks if level.size > 0
        )
        ask_ladder = populated or None
    return MarketQuote(
        instrument_id=str(depth.instrument_id),
        bid=float(bid.price) if bid is not None else None,
        ask=float(ask.price) if ask is not None else None,
        bid_size=float(bid.size) if bid is not None else None,
        ask_size=float(ask.size) if ask is not None else None,
        ts_event=datetime.fromtimestamp(depth.ts_event / 1_000_000_000, tz=UTC),
        ask_ladder=ask_ladder,
    )
