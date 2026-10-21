"""MAKER design card 2 (SPIKE-BID): the pure selector, its eligibility gates and ask tables.

Synthetic ``DataEvents`` frames only: no capture, no NBP, no truth. The selector must be pure
(``maker_stage0_fill.simulate_station_day`` runs it once per pass), so the trailing-ask tables are
built from the events up front and read by bisect at the decision instant.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import pytest

from scripts.analysis import maker_design_spike_selector as sp
from scripts.analysis.maker_stage0_events_build import DataEvents
from scripts.analysis.maker_stage0_fill import simulate_station_day
from scripts.analysis.maker_stage0_fill_events import (
    BUYER,
    CANCEL_BFLOOR,
    DROP_REASONS,
    Decision,
    DecisionContext,
    DepthFrame,
    Desired,
    Event,
    ForecastVector,
    Kind,
    Print,
)

NS_MIN = 60_000_000_000
NOW = 600 * NS_MIN
EDGES = {"r0": float("-inf"), "r1": 80.0, "r2": 82.0, "r3": 84.0, "r4": 86.0}
Series = Mapping[str, Sequence[tuple[int, int | None]]]


def _frame(
    rung: str, *, ask: int | None = 5, bid: int | None = None, ts: int = NOW - 1
) -> DepthFrame:
    return DepthFrame(
        rung_id=rung,
        ts_ns=ts,
        yes_bids=() if bid is None else ((bid, 10),),
        yes_asks=() if ask is None else ((ask, 10),),
    )


def _data(series: Series) -> DataEvents:
    """Depth events only: one frame per ``(ts, best ask)`` point, canonical order."""
    events: list[Event] = []
    for rung, points in series.items():
        for seq, (ts, ask) in enumerate(points):
            frame = _frame(rung, ask=ask, ts=ts)
            events.append(Event(ts, Kind.DEPTH, seq * 100 + len(events), frame))
    return DataEvents(tuple(sorted(events)), len(events), frozenset(series))


def _quiet(rungs: Iterable[str] = tuple(EDGES)) -> Series:
    return {r: [(NOW - 180 * NS_MIN, 5)] for r in rungs}


def _books(**over: DepthFrame) -> dict[str, DepthFrame]:
    base = {
        "r0": _frame("r0", ask=5, bid=None),
        "r1": _frame("r1", ask=30, bid=20),
        "r2": _frame("r2", ask=55, bid=45),
        "r3": _frame("r3", ask=30, bid=20),
        "r4": _frame("r4", ask=5, bid=2),
    }
    base.update(over)
    return base


def _ctx(
    books: Mapping[str, DepthFrame],
    *,
    live: Mapping[str, int] | None = None,
    held: frozenset[str] = frozenset(),
    now: int = NOW,
) -> DecisionContext:
    return DecisionContext(
        now_ns=now, vector=None, books=books, live_bids=dict(live or {}), held=held
    )


def _select(
    ctx: DecisionContext,
    series: Series | None = None,
    edges: Mapping[str, float] = EDGES,
) -> Decision:
    trails = sp.ask_trails(_data(series if series is not None else _quiet(edges)).events)
    return sp.build_spike_selector(edges, trails)(ctx)


# --- the bid price -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ask_c", "bid_c", "expected"),
    [
        (5, 2, 80),  # the cap binds: best NO bid + 1 = 96, NO ask - 1 = 97
        (12, 4, 80),
        (30, 20, 71),  # best NO bid 70 + 1
        (31, 20, 70),  # exactly the floor
        (32, 20, None),  # 69 < 70: no bid
        (5, 25, 74),  # NO ask 75 - 1 clamps below the cap
        (5, 31, None),  # NO ask - 1 = 68 < 70
        (None, None, 80),  # empty book sides apply no clamp (rule.decide_bid)
        (None, 25, 74),
        (30, None, 71),
    ],
)
def test_bid_is_min_of_cap_best_no_bid_plus_one_and_no_ask_minus_one_floored_at_70c(
    ask_c: int | None, bid_c: int | None, expected: int | None
) -> None:
    assert sp.spike_bid_cents(ask_c, bid_c) == expected


# --- ask tables ----------------------------------------------------------------------------


def test_ask_trails_hold_one_ascending_series_per_rung_with_empty_ask_as_100c() -> None:
    data = _data({"r0": [(30, 7), (10, 60), (20, None)], "r1": [(5, 9)]})
    trails = sp.ask_trails(data.events)
    assert set(trails) == {"r0", "r1"}
    assert trails["r0"].ts == (10, 20, 30)
    assert trails["r0"].ask_c == (60, 100, 7)
    assert trails["r1"].ask_c == (9,)


def test_ask_trails_ignore_prints_and_clock_events() -> None:
    depth = _data({"r0": [(10, 5)]}).events
    other = (
        Event(11, Kind.PRINT, 1, Print("r0", 90, 5, BUYER)),
        Event(12, Kind.FORECAST_RELEASE, 2, ForecastVector(12, {}, {}, 0, "", "none")),
    )
    assert sp.ask_trails((*depth, *other))["r0"].ts == (10,)


@pytest.mark.parametrize(
    ("points", "eligible"),
    [
        ([(NOW - 180 * NS_MIN, 5)], True),  # quiet for three hours
        ([(NOW - 30 * NS_MIN, 60), (NOW - 1, 5)], False),  # a 0.60 seed ask inside the hour
        ([(NOW - 30 * NS_MIN, 99), (NOW - 1, 5)], False),  # a 0.99 seed ask inside the hour
        ([(NOW - 180 * NS_MIN, 60), (NOW - 59 * NS_MIN, 5)], False),  # 60 still in force at -60 min
        ([(NOW - 180 * NS_MIN, 60), (NOW - 61 * NS_MIN, 5)], True),  # replaced before the window
        ([(NOW - 180 * NS_MIN, 60), (NOW - 60 * NS_MIN, 5)], True),  # boundary frame is in force
        ([(NOW - 30 * NS_MIN, 9), (NOW - 1, 5)], False),  # 9 > 8 inside the hour
        ([(NOW - 30 * NS_MIN, 8), (NOW - 1, 5)], True),  # 8 is allowed
        ([(NOW - 30 * NS_MIN, None), (NOW - 1, 5)], False),  # an empty ask side counts as 100c
    ],
)
def test_trailing_sixty_minute_max_ask_must_stay_at_or_below_eight_cents(
    points: list[tuple[int, int | None]], eligible: bool
) -> None:
    series = {**_quiet(), "r4": points}
    decision = _select(_ctx(_books()), series)
    assert ("r4" in {d.rung_id for d in decision.desired}) is eligible
    assert "r0" in {d.rung_id for d in decision.desired}


def test_trailing_window_never_looks_past_the_decision_instant() -> None:
    early = {**_quiet(), "r4": [(NOW - 180 * NS_MIN, 5)]}
    later = {**_quiet(), "r4": [(NOW - 180 * NS_MIN, 5), (NOW + 1, 99)]}
    assert _select(_ctx(_books()), early) == _select(_ctx(_books()), later)


def test_trailing_max_is_none_before_a_rungs_first_frame_or_without_a_trail() -> None:
    trail = sp.ask_trails(_data({"r0": [(NOW, 5)]}).events)["r0"]
    assert sp.trailing_max_ask(trail, NOW - 1) is None
    assert sp.trailing_max_ask(trail, NOW) == 5
    assert sp.trailing_max_ask(None, NOW) is None


# --- eligibility ---------------------------------------------------------------------------


def test_posts_far_rungs_at_the_cap_with_decision_shape_per_the_simulator_contract() -> None:
    decision = _select(_ctx(_books()))
    assert decision.desired == (Desired("r0", 80), Desired("r4", 80))
    assert decision.forecast_valid is True
    assert dict(decision.dropped) == {}
    assert decision.drop_reason is None
    assert set(decision.dropped.values()) <= DROP_REASONS


def test_mode_and_both_neighbours_are_excluded_even_when_their_prices_qualify() -> None:
    cheap = _books(
        r1=_frame("r1", ask=5, bid=2),
        r3=_frame("r3", ask=5, bid=2),
        r2=_frame("r2", ask=55, bid=45),
    )
    chosen = {d.rung_id for d in _select(_ctx(cheap)).desired}
    assert chosen == {"r0", "r4"}


def test_a_neighbour_of_the_mode_alone_never_qualifies() -> None:
    books = _books(
        r0=_frame("r0", ask=30, bid=20),  # the far rungs are expensive: nothing else qualifies
        r4=_frame("r4", ask=30, bid=20),
        r1=_frame("r1", ask=5, bid=2),
        r3=_frame("r3", ask=5, bid=2),
    )
    assert _select(_ctx(books)).desired == ()


def test_mode_is_the_highest_yes_mid_and_ties_go_to_the_lowest_ladder_index() -> None:
    books = _books(
        r0=_frame("r0", ask=5, bid=None),
        r1=_frame("r1", ask=30, bid=20),
        r2=_frame("r2", ask=30, bid=20),  # same mid as r1: the tie
        r3=_frame("r3", ask=5, bid=None),
        r4=_frame("r4", ask=5, bid=2),
    )
    # mode r1 (lowest index of the tie): r3 and r4 are two or more steps away; r0 is a neighbour
    chosen = {d.rung_id for d in _select(_ctx(books)).desired}
    assert chosen == {"r3", "r4"}


def test_no_book_at_all_posts_nothing() -> None:
    decision = _select(_ctx({}))
    assert decision.desired == ()
    assert decision.forecast_valid is True


@pytest.mark.parametrize(
    ("ask", "bid", "ok"),
    [
        (12, 4, True),
        (13, 4, False),
        (12, 5, False),
        (8, None, True),  # an empty YES bid side passes the bid gate
        (None, 2, False),  # an empty YES ask side fails the ask gate
    ],
)
def test_current_ask_at_most_12c_and_bid_at_most_4c(
    ask: int | None, bid: int | None, ok: bool
) -> None:
    # trails say the hour was quiet, so only the live-frame gates are under test
    books = _books(r4=_frame("r4", ask=ask, bid=bid))
    chosen = {d.rung_id for d in _select(_ctx(books)).desired}
    assert ("r4" in chosen) is ok
    assert "r0" in chosen


def test_at_most_two_rungs_live_rungs_first_then_cheapest_then_farthest() -> None:
    edges = {f"r{i}": float(70 + 2 * i) for i in range(7)}
    books = {
        "r0": _frame("r0", ask=7),
        "r1": _frame("r1", ask=3),
        "r2": _frame("r2", ask=30, bid=20),
        "r3": _frame("r3", ask=55, bid=45),
        "r4": _frame("r4", ask=30, bid=20),
        "r5": _frame("r5", ask=3),
        "r6": _frame("r6", ask=7),
    }
    fresh = _select(_ctx(books), edges=edges)
    assert fresh.desired == (Desired("r1", 80), Desired("r5", 80))
    kept = _select(_ctx(books, live={"r6": 80}), edges=edges)
    assert kept.desired == (Desired("r6", 80), Desired("r1", 80))
    assert len(kept.desired) <= sp.MAX_RUNGS


def test_a_held_rung_is_never_desired_again() -> None:
    decision = _select(_ctx(_books(), held=frozenset({"r0"})))
    assert [d.rung_id for d in decision.desired] == ["r4"]


def test_a_live_rung_whose_conditions_fail_is_dropped_with_a_known_reason() -> None:
    spiking = _books(r0=_frame("r0", ask=20, bid=10))
    decision = _select(_ctx(spiking, live={"r0": 80, "r4": 80}))
    assert decision.desired == (Desired("r4", 80),)
    assert dict(decision.dropped) == {"r0": CANCEL_BFLOOR}
    assert CANCEL_BFLOOR in DROP_REASONS


def test_a_live_rung_with_no_book_left_is_dropped_not_forgotten() -> None:
    decision = _select(_ctx({"r2": _frame("r2", ask=55, bid=45)}, live={"r0": 80}))
    assert dict(decision.dropped) == {"r0": CANCEL_BFLOOR}


# --- purity --------------------------------------------------------------------------------


def test_selector_is_pure_same_context_same_decision_and_tables_untouched() -> None:
    trails = sp.ask_trails(_data(_quiet()).events)
    before = {r: (t.ts, t.ask_c) for r, t in trails.items()}
    selector = sp.build_spike_selector(EDGES, trails)
    ctx = _ctx(_books(), live={"r0": 80})
    assert selector(ctx) == selector(ctx) == selector(ctx)
    assert {r: (t.ts, t.ask_c) for r, t in trails.items()} == before


# --- end to end through the shipped simulator ------------------------------------------------


def test_spike_selector_fills_a_far_rung_through_the_stage0_simulator() -> None:
    hour = 60 * NS_MIN
    ladder = {"r0": float("-inf"), "r1": 80.0, "r2": 82.0, "r3": 84.0, "r4": 86.0}
    start = 3 * hour
    series: dict[str, list[tuple[int, int | None]]] = {
        "r0": [(0, 5), (2 * hour, 5), (4 * hour, 5)],
        "r1": [(0, 30), (4 * hour, 30)],
        "r2": [(0, 55), (4 * hour, 55)],
        "r3": [(0, 30), (4 * hour, 30)],
        "r4": [(0, 5), (3 * hour + 30 * NS_MIN, 60), (4 * hour, 5)],  # a seed-like 0.60 ask
    }
    events: list[Event] = []
    for rung, points in series.items():
        for ts, ask in points:
            bid = {"r1": 20, "r2": 45, "r3": 20}.get(rung)
            frame = DepthFrame(
                rung_id=rung,
                ts_ns=ts,
                yes_bids=() if bid is None else ((bid, 10),),
                yes_asks=() if ask is None else ((ask, 10),),
            )
            events.append(Event(ts, Kind.DEPTH, len(events), frame))
    events.append(
        Event(0, Kind.FORECAST_RELEASE, 1 << 40, ForecastVector(0, {}, {}, 0, "", "none"))
    )
    events.append(Event(4 * hour + 1, Kind.PRINT, 1 << 41, Print("r0", 20, 30, BUYER)))
    selector = sp.build_spike_selector(ladder, sp.ask_trails(sorted(events)))
    result = simulate_station_day(
        sorted(events), selector, station="LAX", climate_day="2026-10-02",
        unit_hypothesis="CONTRACTS", live_from_ns=start, max_rungs=sp.MAX_RUNGS,
    )  # fmt: skip
    r0 = [e for e in result.episodes if e.rung_id == "r0" and e.refused_reason is None]
    assert [e.bid_cents for e in r0] == [80]
    assert r0[0].filled_ns_stress is not None  # 30 contracts exhaust 2 * (10 + 0 + 1)
    assert result.summary.rung_trials_filled_stress == 1
