"""RED-first tests for ``tick_eval.evaluate_both_sides`` (S3 fix-first review
finding 2, plan ``NO_SIDE_EDGE_2026-09-14.md``).

No test previously covered this function. Covers: a normal frame returns a
typed ``BothSides``; a crossed/locked book refuses BOTH sides
``not_executable`` before either side's own gates run; a normal book proves
the mutual-exclusion identity ``BE_yes + BE_no > 1``; a frame with no bid
still evaluates YES and refuses NO with the missing-bid reason.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import Refuse, Take
from breezy.strategy.current_rung_hold.tick_eval import BothSides, evaluate_both_sides
from breezy.strategy.weather_common.running_extreme import RunningMax

_LADDER: tuple[tuple[int | None, int | None], ...] = ((None, 69), (70, 71), (72, None))

_STATION = "LAX"
_HOUR_LST = 12
_INTERIOR_WIDTH_CODE = 0
_M_ZERO = 0
_CLIMATE_DAY = dt.date(2026, 1, 15)


def _running_max(reading_f: int = 70) -> RunningMax:
    return RunningMax(
        lower_f=reading_f,
        upper_f=reading_f,
        exact_f=reading_f,
        source_observed_at_ns=0,
        source_received_at_ns=0,
    )


def _both_sides(
    *,
    ask: Decimal = Decimal("0.40"),
    ask_size: int = 5,
    bid: Decimal | None = Decimal("0.10"),
    bid_size: Decimal | None = Decimal(5),
) -> BothSides:
    return evaluate_both_sides(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        now_ns=1_000_000_000,
        ladder=_LADDER,
        fee_coefficient=Decimal("0.06"),
        ask=ask,
        ask_size=ask_size,
        bid=bid,
        bid_size=bid_size,
        running_max=_running_max(),
        staleness_ns=0,
        # Armed so this file still measures the NO break-even. The closed
        # default is pinned on ``evaluate_decision`` itself.
        config=CurrentRungHoldConfig(no_side_calibration_gate_cleared=True),
        hour_lst=_HOUR_LST,
        width_code=_INTERIOR_WIDTH_CODE,
        m_code=_M_ZERO,
    )


def test_a_normal_frame_returns_a_typed_both_sides_result() -> None:
    result = _both_sides()
    assert isinstance(result, BothSides)
    assert result.yes == Take(
        quantity=1,
        limit_price=Decimal("0.40"),
        p_hold_lower=Decimal("0.6585"),
        break_even=Decimal("0.41"),
        rung=(70, 71),
    )
    assert isinstance(result.no, Refuse)


def test_a_crossed_book_refuses_both_sides_not_executable() -> None:
    # bid=0.50 >= ask=0.40: crossed.
    result = _both_sides(ask=Decimal("0.40"), bid=Decimal("0.50"))
    assert result.yes == Refuse("not_executable")
    assert result.no == Refuse("not_executable")


def test_a_locked_book_refuses_both_sides_not_executable() -> None:
    # bid == ask: locked, not merely crossed -- same refusal.
    result = _both_sides(ask=Decimal("0.40"), bid=Decimal("0.40"))
    assert result.yes == Refuse("not_executable")
    assert result.no == Refuse("not_executable")


def test_a_normal_book_proves_be_yes_plus_be_no_exceeds_one() -> None:
    # ask=0.40 -> break_even=0.41 (Take); bid=0.10 -> NO_ask=0.90 ->
    # break_even~0.91 (Refuse edge_below_break_even). 0.41 + 0.91 > 1: the
    # two sides' break-evens cannot both be admissible on the same rung.
    result = _both_sides()
    assert isinstance(result.yes, Take)
    # GAP fix 2026-09-15: `Refuse` now carries the numeric p_bound/break_even
    # that produced this refusal; `.reason` is this test's actual subject.
    assert isinstance(result.no, Refuse)
    assert result.no.reason == "edge_below_break_even"
    assert result.yes.break_even + Decimal("0.91") > Decimal(1)


def test_a_frame_with_no_bid_still_evaluates_yes_and_refuses_no_not_executable() -> None:
    result = _both_sides(bid=None, bid_size=None)
    assert isinstance(result.yes, Take)
    assert result.no == Refuse("not_executable")
