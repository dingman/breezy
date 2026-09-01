"""Unit tests for `breezy.strategy.weather_common.ladder`.

BL-25 D2. The visible-ask-ladder walk was PRIVATE to
`running_extreme_lock.decision` (`_vwap_ask_for_quantity`) while
`cli_settlement_print_lock`, `RiskManager.evaluate_order` and the offline
gate classifier each needed the same arithmetic. This module is that one
walk, and these tests pin the padding/exhaustion semantics every caller now
depends on -- see `test_weather_common_costs.py` for the cost built on top of
it and `test_weather_common_risk.py` for the size clip.
"""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.strategy.weather_common.ladder import (
    LadderWalk,
    ask_levels,
    available_ask_depth,
    levels_within_price,
    walk_ask_ladder,
)
from breezy.strategy.weather_common.models import MarketQuote

NOW = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC)

#: Level 0 is CHEAP and THIN, the levels behind it are expensive. This is the
#: measured shape of the captured tape (BL-25): a $24.53 order exceeds level-0
#: ask size in 57.4% of snapshots.
THIN_TOP_LADDER: tuple[tuple[float, float], ...] = ((0.90, 5.0), (0.95, 20.0), (0.99, 50.0))


def _quote(
    *,
    ask: float | None = 0.90,
    ask_size: float | None = 5.0,
    ask_ladder: tuple[tuple[float, float], ...] | None = None,
) -> MarketQuote:
    return MarketQuote(
        instrument_id="ANY",
        bid=None,
        ask=ask,
        bid_size=None,
        ask_size=ask_size,
        ts_event=NOW,
        ask_ladder=ask_ladder,
    )


# ---------------------------------------------------------------------------
# walk_ask_ladder
# ---------------------------------------------------------------------------


def test_a_walk_inside_level_zero_pays_level_zero() -> None:
    walk = walk_ask_ladder(THIN_TOP_LADDER, 4.0)

    assert walk is not None
    assert walk.vwap_price == pytest.approx(0.90)
    assert walk.filled_quantity == pytest.approx(4.0)
    assert walk.exhausted is False
    assert walk.price_concession == pytest.approx(0.0)


def test_a_walk_past_level_zero_pays_the_volume_weighted_average() -> None:
    walk = walk_ask_ladder(THIN_TOP_LADDER, 25.0)

    assert walk is not None
    # (5 * 0.90 + 20 * 0.95) / 25
    assert walk.vwap_price == pytest.approx(0.94)
    assert walk.filled_quantity == pytest.approx(25.0)
    assert walk.top_of_book_price == pytest.approx(0.90)
    assert walk.price_concession == pytest.approx(0.04)


def test_a_walk_that_exhausts_the_ladder_reports_only_what_it_could_fill() -> None:
    walk = walk_ask_ladder(THIN_TOP_LADDER, 500.0)

    assert walk is not None
    assert walk.filled_quantity == pytest.approx(75.0)
    assert walk.total_depth == pytest.approx(75.0)
    assert walk.requested_quantity == pytest.approx(500.0)
    assert walk.exhausted is True


def test_the_size_zero_arrow_pad_is_never_free_liquidity() -> None:
    """`OrderBookDepth10` pads a short side with `Price(0)`/`Quantity(0)`."""
    walk = walk_ask_ladder(((0.90, 5.0), (0.0, 0.0), (0.0, 0.0)), 50.0)

    assert walk is not None
    assert walk.vwap_price == pytest.approx(0.90)
    assert walk.filled_quantity == pytest.approx(5.0)
    assert walk.exhausted is True


def test_a_ladder_with_no_real_depth_is_not_a_walk() -> None:
    assert walk_ask_ladder((), 10.0) is None
    assert walk_ask_ladder(((0.0, 0.0),), 10.0) is None
    assert walk_ask_ladder(((0.90, 0.0),), 10.0) is None


def test_a_non_positive_request_is_not_a_walk() -> None:
    assert walk_ask_ladder(THIN_TOP_LADDER, 0.0) is None
    assert walk_ask_ladder(THIN_TOP_LADDER, -1.0) is None


def test_the_walk_price_is_monotone_non_decreasing_in_requested_size() -> None:
    previous = 0.0
    for quantity in (1.0, 5.0, 6.0, 25.0, 26.0, 75.0, 100.0):
        walk = walk_ask_ladder(THIN_TOP_LADDER, quantity)
        assert walk is not None
        assert walk.vwap_price >= previous - 1e-12
        previous = walk.vwap_price


def test_a_walk_is_an_immutable_value() -> None:
    walk = walk_ask_ladder(THIN_TOP_LADDER, 25.0)

    assert isinstance(walk, LadderWalk)
    with pytest.raises((AttributeError, TypeError)):
        walk.vwap_price = 0.1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ask_levels / available_ask_depth -- the `MarketQuote` adapters
# ---------------------------------------------------------------------------


def test_ask_levels_prefers_the_ladder_when_the_quote_carries_one() -> None:
    quote = _quote(ask=0.90, ask_size=5.0, ask_ladder=THIN_TOP_LADDER)

    assert ask_levels(quote) == THIN_TOP_LADDER


def test_ask_levels_synthesises_a_one_level_ladder_from_top_of_book() -> None:
    """The pre-existing behaviour of every level-0-only caller, preserved."""
    assert ask_levels(_quote(ask=0.90, ask_size=5.0)) == ((0.90, 5.0),)


def test_ask_levels_of_a_quote_with_no_ask_is_empty() -> None:
    assert ask_levels(_quote(ask=None, ask_size=None)) == ()


def test_available_ask_depth_sums_the_whole_ladder() -> None:
    assert available_ask_depth(
        _quote(ask=0.90, ask_size=5.0, ask_ladder=THIN_TOP_LADDER),
    ) == pytest.approx(75.0)


def test_available_ask_depth_falls_back_to_top_of_book_size() -> None:
    assert available_ask_depth(_quote(ask=0.90, ask_size=5.0)) == pytest.approx(5.0)


def test_available_ask_depth_of_an_empty_book_is_zero_never_unbounded() -> None:
    assert available_ask_depth(_quote(ask=None, ask_size=None)) == 0.0
    assert available_ask_depth(_quote(ask=0.90, ask_size=None)) == 0.0


# ---------------------------------------------------------------------------
# DRY: the strategy that owned this arithmetic first now delegates to it
# ---------------------------------------------------------------------------


def test_running_extreme_lock_delegates_to_the_shared_walk() -> None:
    from breezy.strategy.running_extreme_lock.decision import _vwap_ask_for_quantity

    walked = _vwap_ask_for_quantity(THIN_TOP_LADDER, 25.0)
    shared = walk_ask_ladder(THIN_TOP_LADDER, 25.0)

    assert shared is not None
    assert walked == (shared.vwap_price, shared.filled_quantity)


# ---------------------------------------------------------------------------
# levels_within_price -- for callers whose execution seam bounds what they pay
# ---------------------------------------------------------------------------


def test_levels_within_price_drops_rungs_the_caller_cannot_lift() -> None:
    assert levels_within_price(THIN_TOP_LADDER, 0.95) == ((0.90, 5.0), (0.95, 20.0))


def test_levels_within_price_keeps_a_rung_exactly_on_the_bound() -> None:
    """The bound is arithmetic (`ask + slippage / scale`); a hair of float
    slack must not silently drop a rung that is exactly reachable."""
    assert levels_within_price(((0.90, 5.0), (0.91, 20.0)), 0.90 + 0.01) == (
        (0.90, 5.0),
        (0.91, 20.0),
    )


def test_levels_within_price_can_return_nothing() -> None:
    assert levels_within_price(THIN_TOP_LADDER, 0.5) == ()
    assert walk_ask_ladder(levels_within_price(THIN_TOP_LADDER, 0.5), 10.0) is None
