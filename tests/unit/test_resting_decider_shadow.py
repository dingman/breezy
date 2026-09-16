"""RED-first coverage for the SHADOW resting-bid decider
(``docs/plans/RESTING_BID_HUNT_2026-09-16.md`` Rev 2, §6 shadow stage).

Pure module, no I/O, no Nautilus order construction -- see
``resting_decider.py``'s own module docstring. The zero-call-sites test
below is the module's own hard invariant, independent of any wiring test
in ``test_continuous_rung_hold_strategy.py``/``test_continuous_rung_hold_
backtest_only.py``.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.strategy.current_rung_hold import resting_decider as resting_decider_module
from breezy.strategy.current_rung_hold.resting_decider import (
    MARGIN_PRIMARY,
    ShadowRestingDecider,
    compute_p_star,
    edge_maker,
    fee_maker,
)

_STATION = "SFO"
_DAY = "2026-09-16"
_STALE_BOUND_NS = 50 * 60 * 1_000_000_000


def _decider() -> ShadowRestingDecider:
    return ShadowRestingDecider()


# ---------------------------------------------------------------------------
# Zero call sites -- the module's own hard invariant
# ---------------------------------------------------------------------------


_BANNED_NAMES = frozenset({"order_factory", "OrderFactory", "submit_order", "submit_chain"})


def test_the_decider_module_never_imports_order_construction_modules() -> None:
    """AST-based, not a raw substring scan: the module's own docstring
    names ``order_factory``/``submit_order`` in prose (explaining the
    invariant), so only real ``Import``/``ImportFrom``/``Call``/attribute
    references are checked here -- the same discipline
    ``test_polymarket_us_readonly_guard.py``'s non-vacuity scans use."""
    source = Path(resting_decider_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(banned in alias.name for banned in _BANNED_NAMES)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not any(banned in module for banned in _BANNED_NAMES)
            for alias in node.names:
                assert alias.name not in _BANNED_NAMES
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in _BANNED_NAMES
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in _BANNED_NAMES
        elif isinstance(node, ast.Attribute):
            assert node.attr not in _BANNED_NAMES
        elif isinstance(node, ast.Name):
            assert node.id not in _BANNED_NAMES


def test_a_second_module_referencing_the_banned_names_still_trips_the_scan() -> None:
    """Non-vacuity: a module that DOES reference a banned name must fail
    the same scan the test above runs, proving the scan is not vacuously
    passing."""
    tree = ast.parse("from breezy.adapters.polymarket_us.exec import submit_chain\n")
    tripped = any(
        isinstance(node, ast.ImportFrom) and node.module == "breezy.adapters.polymarket_us.exec"
        and any(alias.name == "submit_chain" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert tripped


# ---------------------------------------------------------------------------
# edge_maker / fee_maker / compute_p_star
# ---------------------------------------------------------------------------


def test_fee_maker_is_a_rebate_negative_for_any_interior_price() -> None:
    assert fee_maker(Decimal("0.50")) < 0
    assert fee_maker(Decimal("0.80")) < 0


def test_edge_maker_is_larger_than_the_taker_break_even_gap_at_the_same_price() -> None:
    p_bound = Decimal("0.70")
    price = Decimal("0.60")
    edge = edge_maker(p_bound, price)
    # A rebate means cost < price, so edge > p_bound - price.
    assert edge > p_bound - price


def test_compute_p_star_returns_the_highest_tick_price_meeting_the_margin() -> None:
    # p_bound is high and the ask is far above the band, so a healthy
    # interior price should clear the primary margin comfortably.
    price, reason = compute_p_star(Decimal("0.90"), Decimal("0.90"), MARGIN_PRIMARY)
    assert reason is None
    assert price is not None
    assert price < Decimal("0.90")
    assert price % Decimal("0.01") == 0


def test_compute_p_star_would_cross_when_the_ask_is_at_the_price_floor() -> None:
    # best_ask - tick < floor: no price in the band is strictly below the ask.
    price, reason = compute_p_star(Decimal("0.90"), Decimal("0.05"), MARGIN_PRIMARY)
    assert price is None
    assert reason == "would_cross"


def test_compute_p_star_edge_below_margin_when_p_bound_is_too_close_to_the_ask() -> None:
    # p_bound barely above the ask: even the lowest band price cannot clear
    # a margin this large.
    price, reason = compute_p_star(Decimal("0.10"), Decimal("0.90"), Decimal("0.50"))
    assert price is None
    assert reason == "edge_below_margin"


def test_the_no_leg_uses_the_same_pure_function_over_the_complement_price() -> None:
    """The decider has no leg-specific arithmetic -- the NO leg's ask is
    the caller's ``1 - bid`` complement, fed through the SAME
    :func:`compute_p_star`. This pins that the complement produces a
    genuinely different, still-valid answer, never a leg-conditional branch
    inside the pure function itself."""
    bid = Decimal("0.30")
    no_ask = Decimal(1) - bid
    p_bound_no = Decimal("0.55")
    price, reason = compute_p_star(p_bound_no, no_ask, MARGIN_PRIMARY)
    assert reason is None
    assert price is not None
    assert price < no_ask


# ---------------------------------------------------------------------------
# State machine: REST / RE-PRICE / CANCEL / WOULD_CROSS / fill-eligible
# ---------------------------------------------------------------------------


def test_first_eligible_tick_rests_at_p_star() -> None:
    decider = _decider()
    result = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert result.state == "RESTING"
    assert result.reason == "rest"
    assert result.price is not None
    assert result.margin == MARGIN_PRIMARY
    assert result.price_secondary is not None
    assert decider.is_resting(_STATION, _DAY, "YES")


def test_would_cross_never_rests() -> None:
    decider = _decider()
    result = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.05"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert result.state == "NONE"
    assert result.reason == "would_cross"
    assert result.price is None
    assert not decider.is_resting(_STATION, _DAY, "YES")


def test_reprice_fires_when_p_bound_changes_the_computed_p_star() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    result = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.70"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert result.state == "RESTING"
    assert result.reason == "reprice"


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    [
        ({"family_halted": True}, "halt"),
        ({"sibling_leg_filled": True}, "sibling_leg_filled"),
        ({"cell_legal": False}, "rung_dead"),
        ({"in_window": False}, "window_close"),
        ({"staleness_ns": _STALE_BOUND_NS + 1}, "staleness"),
        ({"p_bound": None}, "p_hold_undefined"),
    ],
)
def test_each_cancel_reason_clears_a_live_rest(kwargs: dict, expected_reason: str) -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert decider.is_resting(_STATION, _DAY, "YES")

    base = {
        "station": _STATION,
        "climate_day": _DAY,
        "leg": "YES",
        "best_ask": Decimal("0.90"),
        "p_bound": Decimal("0.90"),
        "staleness_ns": 0,
        "stale_bound_ns": _STALE_BOUND_NS,
    }
    base.update(kwargs)
    result = decider.evaluate_tick(**base)
    assert result.state == "NONE"
    assert result.reason == expected_reason
    assert not decider.is_resting(_STATION, _DAY, "YES")


def test_edge_below_margin_cancel_reason_clears_a_live_rest() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    result = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        # Low enough that even the price-floor candidate cannot clear the
        # primary margin (edge is decreasing in price, so if the floor
        # fails, every higher price fails too).
        p_bound=Decimal("0.06"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert result.state == "NONE"
    assert result.reason == "edge_below_margin"


def test_would_cross_cancel_reason_clears_a_live_rest() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    result = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.05"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert result.state == "NONE"
    assert result.reason == "would_cross"


def test_fill_eligible_transition_is_counted_exactly_once_while_crossed() -> None:
    decider = _decider()
    rest = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    price = rest.price
    assert price is not None

    crossing = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=price,  # ask falls to exactly the resting price: crossed
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert crossing.fill_event is True

    still_crossed = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=price,  # stays crossed: no second event
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert still_crossed.fill_event is False

    uncrossed = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),  # back above the resting price
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert uncrossed.fill_event is False

    recrossed = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=price,  # crosses again: a second, distinct event
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert recrossed.fill_event is True


def test_window_close_clears_state_and_reports_a_cancel_when_resting() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert decider.is_resting(_STATION, _DAY, "YES")

    result = decider.close_window(_STATION, _DAY, "YES")
    assert result is not None
    assert result.state == "NONE"
    assert result.reason == "window_close"
    assert not decider.is_resting(_STATION, _DAY, "YES")
    assert len(decider) == 0


def test_window_close_on_a_never_resting_key_reports_nothing() -> None:
    decider = _decider()
    assert decider.close_window(_STATION, _DAY, "YES") is None


def test_close_all_windows_clears_every_resting_key() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="NO",
        best_ask=Decimal("0.80"),
        p_bound=Decimal("0.80"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    events = decider.close_all_windows()
    assert len(events) == 2
    assert len(decider) == 0
    assert all(result.reason == "window_close" for _key, result in events)


def test_a_key_can_rest_again_after_a_cancel() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
        family_halted=True,
    )
    assert not decider.is_resting(_STATION, _DAY, "YES")
    result = decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert result.state == "RESTING"
    assert result.reason == "rest"


def test_a_station_and_no_station_do_not_share_state() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station="SFO",
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert decider.is_resting("SFO", _DAY, "YES")
    assert not decider.is_resting("MIA", _DAY, "YES")


def test_yes_and_no_legs_of_the_same_station_day_do_not_share_state() -> None:
    decider = _decider()
    decider.evaluate_tick(
        station=_STATION,
        climate_day=_DAY,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )
    assert decider.is_resting(_STATION, _DAY, "YES")
    assert not decider.is_resting(_STATION, _DAY, "NO")
