"""BL-20: depth consumers must not read a size-0 pad as a price.

``OrderBookDepth10`` always carries ten levels per side. An empty side is
padded with ``Price(0)`` / ``Quantity(0)`` at the instrument's own precision
so the Arrow encoder will accept a thin or one-sided book (BL-18). That pad
sits at index 0, so ``depth.bids[0].price`` is a fabricated 0.00 and
``mid = ask/2``. Native ``to_quote_tick()`` has the same flaw.

The shared conversion (``market_quote_from_depth``) is the one seam: a missing
side arrives on ``MarketQuote`` as ``None``, which the type already expresses.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.parsing import (
    DEPTH10_LEVELS,
    parse_binary_option,
    parse_order_book_depth10,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.strategy.depth10 import best_order, market_quote_from_depth

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT = 1_787_617_213_000_000_000

DEPTH_QUOTE_CONSUMERS = (
    "src/breezy/strategy/forecast_mispricing/strategy.py",
    "src/breezy/strategy/calibration_mean_reversion/strategy.py",
    "src/breezy/strategy/forecast_revision/strategy.py",
    "src/breezy/strategy/running_extreme_lock/strategy.py",
)


def _load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def open_book() -> dict[str, Any]:
    return _load_raw("book_open_510636.json")


@pytest.fixture
def open_instrument() -> BinaryOption:
    return parse_binary_option(
        _load_raw("market_open_510636_by_slug.json"),
        venue=POLYMARKET_US_VENUE,
        ts_init=TS_INIT,
    )


def _pad(
    side: OrderSide, levels: tuple[tuple[str, int], ...], *, precision: int = 2
) -> tuple[list[BookOrder], list[int]]:
    filler = BookOrder(side, Price(0, precision), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    counts = [1] * len(orders)
    while len(orders) < DEPTH10_LEVELS:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _depth(
    *,
    bids: tuple[tuple[str, int], ...],
    asks: tuple[tuple[str, int], ...],
    instrument_id: str = "TEST-GE80.POLYMARKET_US",
) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, bids)
    ask_orders, ask_counts = _pad(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=InstrumentId.from_str(instrument_id),
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=TS_INIT,
        ts_init=TS_INIT,
    )


# ---------------------------------------------------------------------------
# The defect: a one-sided Depth10 pad is a 0.00 at index 0
# ---------------------------------------------------------------------------


def test_the_native_pad_really_does_sit_at_index_zero_on_an_asks_only_book(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    """Non-vacuity: the pad is not hypothetical, and naive [0] reads 0.00."""
    book = json.loads(json.dumps(open_book))
    book["marketData"]["bids"] = []
    depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)

    assert float(depth.bids[0].price) == 0.0
    assert float(depth.bids[0].size) == 0.0
    assert float(depth.asks[0].size) > 0.0


def test_asks_only_depth_does_not_quote_a_zero_bid_or_a_half_ask_mid(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    book = json.loads(json.dumps(open_book))
    book["marketData"]["bids"] = []
    depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)
    naive_ask = float(depth.asks[0].price)

    quote = market_quote_from_depth(depth)

    assert quote is not None
    assert quote.bid is None
    assert quote.bid_size is None
    assert quote.ask == pytest.approx(naive_ask)
    assert quote.ask is not None and quote.ask > 0.0
    assert quote.mid is None
    assert quote.mid != naive_ask / 2.0


def test_bids_only_depth_does_not_quote_a_zero_ask(
    open_book: dict[str, Any], open_instrument: BinaryOption
) -> None:
    book = json.loads(json.dumps(open_book))
    book["marketData"]["offers"] = []
    depth = parse_order_book_depth10(book, instrument=open_instrument, ts_init=TS_INIT)
    naive_bid = float(depth.bids[0].price)

    quote = market_quote_from_depth(depth)

    assert quote is not None
    assert quote.ask is None
    assert quote.ask_size is None
    assert quote.bid == pytest.approx(naive_bid)
    assert quote.bid is not None and quote.bid > 0.0
    assert quote.mid is None


def test_a_genuinely_thin_but_real_level_is_still_quoted() -> None:
    """Do not over-correct: size > 0 at a real price is a book, not a pad."""
    depth = _depth(bids=(("0.40", 1),), asks=(("0.42", 1),))

    quote = market_quote_from_depth(depth)

    assert quote is not None
    assert quote.bid == pytest.approx(0.40)
    assert quote.ask == pytest.approx(0.42)
    assert quote.bid_size == pytest.approx(1.0)
    assert quote.ask_size == pytest.approx(1.0)
    assert quote.mid == pytest.approx(0.41)


def test_a_thin_real_ask_on_an_asks_only_book_is_still_the_ask() -> None:
    depth = _depth(bids=(), asks=(("0.55", 2),))

    quote = market_quote_from_depth(depth)

    assert quote is not None
    assert quote.bid is None
    assert quote.ask == pytest.approx(0.55)
    assert quote.ask_size == pytest.approx(2.0)
    assert quote.mid is None


def test_ask_ladder_skips_the_size_zero_pad() -> None:
    depth = _depth(bids=(), asks=(("0.50", 10), ("0.51", 20)))

    quote = market_quote_from_depth(depth, include_ask_ladder=True)

    assert quote is not None
    assert quote.ask_ladder == ((0.50, 10.0), (0.51, 20.0))
    assert all(size > 0.0 for _, size in quote.ask_ladder)


def test_a_fully_empty_padded_book_is_not_a_quote() -> None:
    depth = _depth(bids=(), asks=())

    assert market_quote_from_depth(depth) is None


def test_best_order_skips_the_size_zero_pad() -> None:
    asks, _ = _pad(OrderSide.SELL, (("0.61", 7),))
    # The pad occupies every slot after the real level; a naive [0] is fine
    # here, so also pin a pad-first side (what a fully empty side looks like).
    empty, _ = _pad(OrderSide.SELL, ())

    best = best_order(asks)
    missing = best_order(empty)

    assert best is not None
    assert float(best.price) == pytest.approx(0.61)
    assert float(best.size) == pytest.approx(7.0)
    assert missing is None


def test_best_order_keeps_a_real_thin_level() -> None:
    bids, _ = _pad(OrderSide.BUY, (("0.33", 1),))

    best = best_order(bids)

    assert best is not None
    assert float(best.price) == pytest.approx(0.33)
    assert float(best.size) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Seam: every MarketQuote-from-depth consumer uses the shared factory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", DEPTH_QUOTE_CONSUMERS)
def test_depth_consumers_build_market_quote_through_the_shared_factory(path: str) -> None:
    """Do not re-paste the skip-if-zero loop; one conversion, four call sites."""
    source = Path(REPO_ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "market_quote_from_depth"
    ]
    assert calls, f"{path} never calls market_quote_from_depth"

    indexed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr in {"bids", "asks"}
    ]
    assert indexed == [], f"{path} still indexes depth.bids/asks directly: {indexed}"
