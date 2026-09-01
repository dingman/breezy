"""Walking the VISIBLE ASK LADDER: one pure walk, shared by every consumer.

WHY THIS EXISTS -- NAUTILUS NULL HYPOTHESIS (L-1), CHECKED FIRST
----------------------------------------------------------------
Nautilus DOES walk a ladder --
``nautilus_trader.model.book.OrderBook.get_avg_px_for_quantity``
(``.venv/lib/python3.13/site-packages/nautilus_trader/model/book.pyx:557``) is
exactly this VWAP. It is nonetheless not usable here, for three reasons, and
the third is the load-bearing one:

1. **Wrong input object.** It is a method on ``OrderBook``, a mutable ``Data``
   object maintained by the data/matching engine. Breezy's weather strategies
   consume ``OrderBookDepth10`` SNAPSHOTS and build a ``MarketQuote`` from
   them (``breezy.strategy.depth10``); they never hold an ``OrderBook``.
   ``OrderBookDepth10`` (``model/data.pyx:3441``) exposes ``bids``, ``asks``
   and ``to_quote_tick`` and no aggregation of any kind. Its sibling
   ``OrderBook.simulate_fills`` (``book.pyx:683``) needs both the book AND a
   constructed ``Order``, so it is further away still.
2. **Lossy return.** It returns a bare ``double``. A caller cannot tell a full
   fill from a partial one, cannot recover the filled quantity, and cannot see
   the top-of-book price the concession is measured against -- the three
   things BL-25 needs in order to CLIP an order and to price it.
3. **Fail-open on an empty book.** ``book.pyx:578-580``: "If no average price
   can be calculated then will return 0.0 (zero)." A zero average price
   consumed as a cost reads as a FREE fill -- the same fail-open posture
   ``breezy.adapters.polymarket_us.fees`` refuses and the same one that makes
   Nautilus's own ``PolymarketFeeModel`` unsafe here. This module returns
   ``None`` for "no walk", which every caller must handle as a no-trade.

So the gap is real for the exact input Breezy holds: a ``(price, size)``
sequence lifted off a Depth10 snapshot. This module is the smallest pure
helper that closes it, and it is deliberately NOT a book: it never mutates,
never matches, and never simulates a fill against the venue.

WHY IT LIVES HERE AND NOT IN A STRATEGY
---------------------------------------
It was previously PRIVATE to ``running_extreme_lock.decision`` while three
other places needed the same arithmetic --
``cli_settlement_print_lock.decision`` (which priced and sized off level 0
alone), ``weather_common.risk.RiskManager.evaluate_order`` (which clipped to
every cap EXCEPT the book), and the offline gate classifier in
``scripts/analysis/weather_strategy_backtest_lib``. Four copies of a walk is
four places for the fill price to drift from the price the edge was computed
at, so there is one walk and every caller uses it (BL-25 D2).

WHY THE WALK IS THE RIGHT SHAPE (MEASURED)
------------------------------------------
Over the captured ladder at
``~/.local/share/breezy/catalog/quote_tape/polymarket_us`` (``data/`` AND
``live/``): a $24.53 order exceeds level-0 ask size in **57.4%** of snapshots
and exhausts all ten recorded levels in **6.5%**; realised walk-the-book
slippage (VWAP - level-0 ask) is 0.0026 at the median, **0.137 at p90** and
**0.661 at p99**. Liquidity is inverted -- a median 35,991 contracts offered
at 0.01 on worthless rungs against **0.58** contracts at 0.99 on the one
winning rung ever offered. Level 0 is therefore not the price a real order
pays and not the size a real order can take.

VENUE NEUTRALITY
----------------
Prices are RAW VENUE UNITS throughout, exactly as ``MarketQuote.ask`` stores
them; the caller applies its own ``price_scale`` to the result (VWAP is linear
in price, so scaling the levels first or the result after are equivalent).
Nothing here imports an adapter or names a venue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from breezy.strategy.weather_common.models import MarketQuote

__all__ = [
    "LadderWalk",
    "ask_levels",
    "available_ask_depth",
    "levels_within_price",
    "walk_ask_ladder",
]

#: Contract-quantity slack. Sizes arrive as floats derived from division
#: (`anchor / premium`) and from venue `Quantity` round-trips, so an exact
#: `filled < requested` comparison would report a phantom exhaustion on the
#: last bit of a request the ladder actually covered.
_QTY_EPSILON: float = 1e-9


@dataclass(frozen=True, slots=True)
class LadderWalk:
    """The result of taking ``requested_quantity`` off a visible ask ladder.

    Immutable, and every field is an OBSERVATION about a snapshot -- never an
    instruction. In particular ``filled_quantity`` is what the recorded book
    could supply, which is the largest size a caller may honestly claim; it is
    never the size the caller asked for.

    All prices are RAW VENUE UNITS (see the module docstring).
    """

    #: Volume-weighted average price of ``filled_quantity``.
    vwap_price: float
    #: ``min(requested_quantity, total_depth)`` -- what the book could supply.
    filled_quantity: float
    #: What the caller asked for, kept so an exhausted walk is legible.
    requested_quantity: float
    #: Best REAL level's price -- the "level 0 ask" the old flat cost priced.
    top_of_book_price: float
    #: Price of the LAST level touched -- the worst rung the fill reaches.
    #: Nautilus spells the same quantity `OrderBook.get_worst_px_for_quantity`
    #: (`book.pyx:588`), on the `OrderBook` object Breezy does not hold. An
    #: execution layer needs it to price a marketable limit that actually
    #: FILLS the size the decision was priced at: a limit set at the VWAP
    #: would stop halfway up the ladder it just paid for.
    worst_price: float
    #: Sum of every real level's size on the recorded ladder.
    total_depth: float

    @property
    def exhausted(self) -> bool:
        """The ladder ran out before the request was absorbed."""
        return self.filled_quantity < self.requested_quantity - _QTY_EPSILON

    @property
    def price_concession(self) -> float:
        """``vwap_price - top_of_book_price``, floored at zero.

        The realised walk-the-book slippage the captured tape measures. Zero
        for any walk that stayed inside level 0; never negative -- a ladder
        whose deeper rungs are CHEAPER than its best rung is a crossed/garbled
        book, not a rebate on execution.
        """
        return max(0.0, self.vwap_price - self.top_of_book_price)


def walk_ask_ladder(
    levels: Sequence[tuple[float, float]],
    quantity: float,
) -> LadderWalk | None:
    """Take ``quantity`` off ``levels`` (best price first), or ``None``.

    A degenerate level (``size <= 0`` or ``price <= 0``) is SKIPPED, never
    treated as free liquidity: that is ``OrderBookDepth10``'s ``NULL_ORDER``
    padding, which pads a short side at index 0 (see
    ``breezy.strategy.depth10`` and ``resting_ladder.RestingLadderStrategy.
    _best`` for the same guard).

    Returns ``None`` -- and only ``None`` -- when the request is non-positive
    or the ladder offers strictly zero real depth. Both are "there is no walk
    here", which is a NO-TRADE for every caller; neither is ever reported as a
    zero-cost fill.
    """
    if not (quantity > 0.0):
        return None
    remaining = quantity
    filled = 0.0
    notional = 0.0
    total_depth = 0.0
    top_of_book: float | None = None
    worst: float | None = None
    for price, size in levels:
        if size <= 0.0 or price <= 0.0:
            continue
        if top_of_book is None:
            top_of_book = price
        total_depth += size
        if remaining <= 0.0:
            continue
        take = min(remaining, size)
        notional += take * price
        filled += take
        remaining -= take
        worst = price
    if filled <= 0.0 or top_of_book is None or worst is None:
        return None
    return LadderWalk(
        vwap_price=notional / filled,
        filled_quantity=filled,
        requested_quantity=quantity,
        top_of_book_price=top_of_book,
        worst_price=worst,
        total_depth=total_depth,
    )


def ask_levels(quote: MarketQuote) -> tuple[tuple[float, float], ...]:
    """The quote's ask ladder, or its top-of-book as a one-level ladder.

    The fallback is the pre-existing behaviour of every level-0-only caller,
    preserved exactly: with no ladder the walk returns the level-0 ask at the
    level-0 size, so a depth-aware caller on a ladderless quote computes
    precisely what the old level-0 code computed. ``()`` when there is no
    executable ask side at all.
    """
    if quote.ask_ladder is not None:
        return quote.ask_ladder
    if quote.ask is None:
        return ()
    return ((quote.ask, quote.ask_size or 0.0),)


def available_ask_depth(quote: MarketQuote) -> float:
    """Total REAL contracts offered on the ask side of ``quote``.

    The whole recorded ladder when the quote carries one -- that is the depth
    a VWAP-priced order actually consumes -- and top-of-book size otherwise.
    ``0.0`` when there is no ask side or no size, never an unbounded fallback:
    an unknown depth is no depth (see ``RiskManager.evaluate_order``'s
    ``insufficient_depth`` refusal).
    """
    return sum(size for price, size in ask_levels(quote) if size > 0.0 and price > 0.0)


def levels_within_price(
    levels: Sequence[tuple[float, float]],
    max_price: float,
) -> tuple[tuple[float, float], ...]:
    """The rungs of ``levels`` priced at or below ``max_price`` (RAW units).

    For a caller whose EXECUTION seam bounds the price it can pay -- a
    marketable IOC limit, say -- the rungs above that bound are not liquidity
    it can lift, and sizing or pricing against them models a fill the strategy
    structurally cannot get. Filtering here rather than after the walk keeps
    the VWAP, the fillable quantity and the worst rung all consistent with the
    same bound.

    Tiny float slack, because ``max_price`` is typically derived by arithmetic
    (``ask + slippage / price_scale``) that can land a hair under a level that
    is exactly on the bound.
    """
    return tuple((price, size) for price, size in levels if price <= max_price + 1e-12)
