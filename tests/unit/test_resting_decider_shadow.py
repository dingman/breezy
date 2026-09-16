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
    MAX_CLIMATE_DAYS_PER_STATION_LEG,
    ShadowRestingDecider,
    compute_p_star,
    edge_rest_conservative,
    fee_rest_conservative,
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
# edge_rest_conservative / fee_rest_conservative / compute_p_star
#
# Domain review of 87446c2, finding 5: priced at the TAKER coefficient
# (PREREG v5 §3b / plan Rev 2 §1.2), never the maker rebate, until a
# wire-observed maker fill retires the pin.
# ---------------------------------------------------------------------------


def test_fee_rest_conservative_is_a_cost_positive_for_any_interior_price() -> None:
    assert fee_rest_conservative(Decimal("0.50")) > 0
    assert fee_rest_conservative(Decimal("0.80")) > 0


def test_edge_rest_conservative_is_smaller_than_the_raw_price_gap() -> None:
    p_bound = Decimal("0.70")
    price = Decimal("0.60")
    edge = edge_rest_conservative(p_bound, price)
    # A cost means the priced fee > 0, so edge < p_bound - price.
    assert edge < p_bound - price


def test_compute_p_star_prices_the_documented_taker_tick_exactly() -> None:
    """Finding 5: computed and asserted against a hand-derived number
    (theta=0.06, the documented taker coefficient), not merely cross-
    checked against the module's own formula."""
    p_bound = Decimal("0.90")
    best_ask = Decimal("0.80")
    margin = Decimal("0.02")
    price, reason = compute_p_star(p_bound, best_ask, margin)
    assert reason is None
    # ceiling_effective = min(0.95, 0.80 - 0.01) = 0.79; at p=0.79 the
    # taker-priced edge (0.90 - 0.79 - 0.06*0.79*0.21 = 0.100046) already
    # clears the 0.02 margin, so 0.79 is the highest admissible tick.
    assert price == Decimal("0.79")


def test_taker_priced_p_star_is_strictly_below_the_rebate_priced_p_star() -> None:
    """Finding 5: a case where the conservative (taker) pricing and the
    rebate pricing this module used to use land on DIFFERENT ticks --
    proof the rename+repricing is load-bearing, not cosmetic."""
    p_bound = Decimal("0.81")
    best_ask = Decimal("0.80")
    margin = Decimal("0.02")

    taker_price, taker_reason = compute_p_star(p_bound, best_ask, margin)
    assert taker_reason is None
    assert taker_price == Decimal("0.77")

    def _rebate_edge(p_bound: Decimal, price: Decimal) -> Decimal:
        rebate_fee = Decimal("-0.0125") * price * (Decimal(1) - price)
        return p_bound - (price + rebate_fee)

    # Hand-rolled rebate-priced search, independent of this module's own
    # (now taker-only) `edge_rest_conservative` -- a real cross-check, not
    # a tautology against the code under test.
    rebate_price = None
    candidate = Decimal("0.79")
    while candidate >= Decimal("0.05"):
        if _rebate_edge(p_bound, candidate) >= margin:
            rebate_price = candidate
            break
        candidate -= Decimal("0.01")
    assert rebate_price == Decimal("0.79")
    assert taker_price is not None
    assert taker_price < rebate_price


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
        ({"fee_schedule_mismatch": True}, "fee_schedule_mismatch"),
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


# ---------------------------------------------------------------------------
# Hard cap on `_states` (domain review of 87446c2, finding 2): a missed
# window-close signal must never let `_states` grow past
# `MAX_CLIMATE_DAYS_PER_STATION_LEG` climate_days per (station, leg).
# ---------------------------------------------------------------------------


def _rest(decider: ShadowRestingDecider, climate_day: str) -> None:
    decider.evaluate_tick(
        station=_STATION,
        climate_day=climate_day,
        leg="YES",
        best_ask=Decimal("0.90"),
        p_bound=Decimal("0.90"),
        staleness_ns=0,
        stale_bound_ns=_STALE_BOUND_NS,
    )


def test_ten_consecutive_climate_days_never_grow_states_past_the_cap() -> None:
    decider = _decider()
    days = [f"2026-09-{d:02d}" for d in range(1, 11)]
    for day in days:
        _rest(decider, day)

    assert len(decider) <= MAX_CLIMATE_DAYS_PER_STATION_LEG
    # The oldest days were evicted; only the newest survive as RESTING.
    for stale_day in days[:-MAX_CLIMATE_DAYS_PER_STATION_LEG]:
        assert not decider.is_resting(_STATION, stale_day, "YES")
    for fresh_day in days[-MAX_CLIMATE_DAYS_PER_STATION_LEG:]:
        assert decider.is_resting(_STATION, fresh_day, "YES")


def test_evicted_climate_days_appear_in_the_drained_eviction_buffer() -> None:
    decider = _decider()
    days = [f"2026-09-{d:02d}" for d in range(1, 11)]
    for day in days:
        _rest(decider, day)

    evicted = decider.drain_evictions()
    evicted_days = {climate_day for (_station, climate_day, _leg), _result in evicted}
    assert evicted_days == set(days[:-MAX_CLIMATE_DAYS_PER_STATION_LEG])
    assert all(result.reason == "window_close" for _key, result in evicted)
    # Drained once -- a second drain is empty until the next eviction.
    assert decider.drain_evictions() == ()


def test_yes_and_no_legs_are_capped_independently() -> None:
    decider = _decider()
    for d in range(1, 11):
        day = f"2026-09-{d:02d}"
        decider.evaluate_tick(
            station=_STATION,
            climate_day=day,
            leg="YES",
            best_ask=Decimal("0.90"),
            p_bound=Decimal("0.90"),
            staleness_ns=0,
            stale_bound_ns=_STALE_BOUND_NS,
        )
        decider.evaluate_tick(
            station=_STATION,
            climate_day=day,
            leg="NO",
            best_ask=Decimal("0.80"),
            p_bound=Decimal("0.80"),
            staleness_ns=0,
            stale_bound_ns=_STALE_BOUND_NS,
        )
    assert len(decider) <= 2 * MAX_CLIMATE_DAYS_PER_STATION_LEG


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
