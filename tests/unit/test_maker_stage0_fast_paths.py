"""MAKER-S2 S-5 time round: every hot-path shortcut is checked against the original algorithm.

Each shortcut (ladder plan, vector chain, rung pricer, level-validation fast path) must return what
the pre-optimisation code returned, including the errors and the store/tracker side effects.
"""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from scripts.analysis import maker_stage0_adapter as adapter
from scripts.analysis import maker_stage0_fill_events as ev
from scripts.analysis import maker_stage0_pno as pno
from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_pricing import RungPricer
from tests.unit import test_maker_stage0_pno as fx

SEC = 10**9
EDGE_POOL = [float("-inf"), 70.0, 76.0, 80.0, 82.0, 84.0, 86.0, 90.0, 95.0]


def _reference_select(
    p_yes_by_rung: dict[str, float], bids: Mapping[str, float | None], edges: dict[str, float]
) -> tuple[str, ...]:
    """The pre-optimisation ``rule.select_rungs`` body, verbatim."""
    for rung, p_yes in p_yes_by_rung.items():
        rule._validate_probability(p_yes, f"p_yes[{rung!r}]")
    rungs = rule._ladder_order(p_yes_by_rung, edges)
    if not rungs:
        return ()
    modal = max(range(len(rungs)), key=lambda i: p_yes_by_rung[rungs[i]])
    eligible: list[tuple[float, int]] = []
    for idx, rung in enumerate(rungs):
        bid = bids.get(rung)
        if abs(idx - modal) <= 1 or bid is None or rule._cents(bid) < rule._cents(rule.B_FLOOR):
            continue
        if rule._p_no_below_p_min(1.0 - p_yes_by_rung[rung]):
            continue
        eligible.append((p_yes_by_rung[rung], idx))
    eligible.sort()
    return tuple(rungs[idx] for _, idx in eligible[: rule.MAX_RUNGS])


def _random_case(rnd: random.Random) -> tuple[dict[str, float], dict[str, float | None], Any]:
    n = rnd.randint(1, 9)
    names = [f"R{i}" for i in range(n)]
    edges = dict(zip(names, rnd.sample(EDGE_POOL, n), strict=True))
    levels = [0.0, 0.02, 0.1, 0.5, 0.97, 1.0]
    p_yes = {r: rnd.choice(levels) if rnd.random() < 0.4 else rnd.random() for r in names}
    bids: dict[str, float | None] = {}
    for r in names:
        roll = rnd.random()
        if roll < 0.2:
            bids[r] = None
        elif roll > 0.9:
            continue  # missing key
        else:
            bids[r] = rnd.randint(0, 99) / 100
    return p_yes, bids, edges


def test_ladder_plan_select_matches_the_reference_select_rungs() -> None:
    rnd = random.Random(11)
    picked = 0
    for _ in range(4_000):
        p_yes, bids, edges = _random_case(rnd)
        want = _reference_select(p_yes, bids, edges)
        assert rule.select_rungs(p_yes, bids, lower_edges_f=edges) == want
        assert rule.ladder_plan(p_yes, edges).select(bids) == want
        picked += bool(want)
    assert picked > 300  # the random cases are not all empty selections


@pytest.mark.parametrize(
    "p_yes, edges",
    [
        ({"a": float("nan"), "b": 0.1}, {"a": 1.0, "b": 2.0}),
        ({"a": 0.2, "b": 1.5}, {"a": 1.0, "b": 2.0}),
        ({"a": 0.2, "b": 0.1}, {"a": 1.0}),
        ({"a": 0.2, "b": 0.1}, {"a": 1.0, "b": 1.0}),
        ({"a": 0.2, "b": 0.1}, {"a": float("nan"), "b": 1.0}),
    ],
)
def test_ladder_plan_raises_the_reference_error(
    p_yes: dict[str, float], edges: dict[str, float]
) -> None:
    with pytest.raises(ValueError) as ref:
        _reference_select(p_yes, {}, edges)
    with pytest.raises(ValueError) as new:
        rule.ladder_plan(p_yes, edges)
    with pytest.raises(ValueError) as public:
        rule.select_rungs(p_yes, {}, lower_edges_f=edges)
    assert str(new.value) == str(ref.value) == str(public.value)


def test_ladder_plan_of_an_empty_ladder_selects_nothing() -> None:
    assert rule.ladder_plan({}, {}).select({}) == ()


def test_a_nan_bid_still_raises_where_the_reference_raised() -> None:
    p_yes, edges = {"a": 0.1, "b": 0.2, "c": 0.9}, {"a": 1.0, "b": 2.0, "c": 3.0}
    bids = {"a": float("nan"), "b": 0.5, "c": 0.5}
    with pytest.raises(ValueError):
        _reference_select(p_yes, bids, edges)
    with pytest.raises(ValueError):
        rule.ladder_plan(p_yes, edges).select(bids)


# ---- the vector chain -----------------------------------------------------------------------


def _reference_value_at(store: pno.PNoStore, stress: pno.Stress, now_ns: int) -> Any:
    return store.state("LAX", fx.DAY, stress).value_at(now_ns)


@pytest.mark.parametrize("stress", ["none", "plus60", "poll_lag"])
def test_vector_chain_at_equals_state_value_at_everywhere(tmp_path: Path, stress: Any) -> None:
    store = fx._store(fx._build_root(tmp_path))
    chain = store.vector_chain("LAX", fx.DAY, stress)
    start = fx._ns(fx.DAY - dt.timedelta(days=1), 10)
    probes = list(range(start, start + 36 * 3600 * SEC, 97 * SEC))
    for vector in chain.vectors:
        probes += [vector.available_at_ns - 1, vector.available_at_ns, vector.available_at_ns + 1]
    for now in probes:
        assert chain.at(now) == _reference_value_at(store, stress, now)
    assert chain.at(0) is None
    assert chain.at(2**62) == _reference_value_at(store, stress, 2**62)


def test_release_instants_equal_the_reference_walk(tmp_path: Path) -> None:
    store = fx._store(fx._build_root(tmp_path))
    for stress in ("none", "plus60", "poll_lag"):
        state = store.state("LAX", fx.DAY, stress)
        instants: set[int] = set()
        vector = state.value_at(2**62)
        while vector is not None:
            if vector.climate_day == fx.DAY:
                instants.add(vector.available_at_ns)
            vector = state.value_at(vector.available_at_ns - 1)
        got = pno.release_instants(store, "LAX", fx.DAY, stress=stress)
        assert got == tuple(sorted(instants))


def test_the_point_view_is_shared_per_cycle_and_still_immutable(tmp_path: Path) -> None:
    store = fx._store(fx._build_root(tmp_path))
    first = pno.classify_p_no(store, "LAX", fx.DAY, fx.AT_1650, stress="none")
    again = pno.classify_p_no(store, "LAX", fx.DAY, fx.AT_1650 + SEC, stress="none")
    assert isinstance(first, pno.PNoAtInstant) and isinstance(again, pno.PNoAtInstant)
    assert first.p_yes_point_live is again.p_yes_point_live
    assert first.p_yes_point_live == {k: v.point for k, v in first.bounds.items()}
    with pytest.raises(TypeError):
        first.p_yes_point_live["r82"] = 0.0  # type: ignore[index]


# ---- the rung pricer ------------------------------------------------------------------------


def _frame(rnd: random.Random, rung: str, ts: int) -> ev.DepthFrame:
    asks = tuple(
        sorted({(rnd.randint(5, 95), rnd.randint(0, 9)) for _ in range(rnd.randint(0, 4))})
    )
    bids = tuple(
        sorted({(rnd.randint(1, 60), rnd.randint(0, 9)) for _ in range(rnd.randint(0, 3))})
    )
    return ev.DepthFrame(rung_id=rung, ts_ns=ts, yes_bids=bids, yes_asks=asks, instance_id="i")


def test_rung_pricer_equals_decide_bid_on_the_displayed_book() -> None:
    rnd = random.Random(5)
    pricer = RungPricer(0.0695, adapter._quote)
    frames = [None, *(_frame(rnd, "R", i) for i in range(30))]
    for _ in range(3_000):
        frame, p_no = rnd.choice(frames), rnd.choice([0.5, 0.81, 0.93, 0.99, 1.0, 0.1])
        nb, na = adapter._quote(frame)
        want = rule.decide_bid(p_no, nb, na, 0.0695)
        assert pricer.price("R", frame, p_no) == want
        assert pricer.price("R", frame, p_no) == want  # the cached answer is the same answer


def test_rung_pricer_reprices_when_the_book_or_the_probability_changes() -> None:
    pricer = RungPricer(0.0695, adapter._quote)
    thin = ev.DepthFrame(rung_id="R", ts_ns=1, yes_bids=((10, 5),), yes_asks=((30, 5),))
    thick = ev.DepthFrame(rung_id="R", ts_ns=2, yes_bids=((10, 5),), yes_asks=((20, 5),))
    a = pricer.price("R", thin, 0.9)
    b = pricer.price("R", thick, 0.9)
    c = pricer.price("R", thick, 0.7)
    assert (a, b, c) == (
        rule.decide_bid(0.9, 0.7, 0.9, 0.0695),
        rule.decide_bid(0.9, 0.8, 0.9, 0.0695),
        rule.decide_bid(0.7, 0.8, 0.9, 0.0695),
    )


def test_rung_pricer_never_caches_an_error() -> None:
    pricer = RungPricer(0.0695, adapter._quote)
    for _ in range(2):
        with pytest.raises(ValueError):
            pricer.price("R", None, float("nan"))


# ---- the adapter selector against the original algorithm ----------------------------------------


def _reference_decide(
    cfg: adapter.SelectorConfig, tracker: adapter.WantTracker | None, ctx: ev.DecisionContext
) -> ev.Decision:
    """The pre-optimisation ``adapter._decide`` / ``_priced`` / ``_price_rungs``, verbatim."""
    shift = abs(cfg.delta_ns)
    state = cfg.store.state(cfg.station, cfg.day, cfg.stress)
    decision_ts = ctx.now_ns - shift
    vector = state.value_at(decision_ts - 1)
    reason = pno._abstain_reason(vector, cfg.day, decision_ts)
    if reason == pno.NO_VECTOR and any(
        t >= decision_ts for t in _reference_releases(cfg.store, cfg.station, cfg.day, cfg.stress)
    ):
        reason = pno.FORECAST_NOT_YET_AVAILABLE
    p_yes: Any = ""
    if reason is None and vector is not None:
        p_yes = cfg.store.p_yes(cfg.station, cfg.day, vector)
        reason = p_yes if isinstance(p_yes, str) else None
    if reason is not None or vector is None or isinstance(p_yes, str):
        reason = reason or pno.NO_VECTOR
        cfg.store.abstentions.add((cfg.station, cfg.day, cfg.stress, reason))
        cfg.store.abstention_counts[(cfg.stress, reason)] += 1
        if tracker is not None:
            tracker.abstentions[reason] += 1
        return ev.Decision(drop_reason=adapter.drop_reason_for(reason), forecast_valid=False)
    cfg.store.served.add((cfg.station, cfg.day, cfg.stress))
    age = ctx.now_ns - (vector.available_at_ns + shift)
    gate = rule.forecast_gate(vector.climate_day, cfg.day, age)
    if gate is not None:
        return ev.Decision(drop_reason=adapter.drop_reason_for(gate), forecast_valid=False)
    points = {k: p.point for k, p in p_yes.items()}
    bids: dict[str, float | None] = {}
    reasons: dict[str, str | None] = {}
    for rung, p in points.items():
        if rung in ctx.held:
            bids[rung], reasons[rung] = None, None
            continue
        nb, na = adapter._quote(ctx.books.get(rung))
        decided = rule.decide_bid(1.0 - p, nb, na, cfg.theta)
        bids[rung], reasons[rung] = decided.bid, decided.reason
    if tracker is not None:
        wanted = _reference_select(points, bids, dict(cfg.lower_edges_f))
        tracker.wanted_without_book.update(r for r in wanted if r not in ctx.books)
    bookable = {r: (b if r in ctx.books else None) for r, b in bids.items()}
    chosen = _reference_select(points, bookable, dict(cfg.lower_edges_f))
    desired = adapter._desired(chosen, bookable, ctx)
    return ev.Decision(
        desired=desired, forecast_valid=True, dropped=adapter._dropped(ctx, desired, reasons)
    )


def _reference_releases(
    store: pno.PNoStore, station: str, day: dt.date, stress: pno.Stress
) -> tuple[int, ...]:
    state = store.state(station, day, stress)
    instants: set[int] = set()
    vector = state.value_at(2**62)
    while vector is not None:
        if vector.climate_day == day:
            instants.add(vector.available_at_ns)
        vector = state.value_at(vector.available_at_ns - 1)
    return tuple(sorted(instants))


def _context(rnd: random.Random, now: int, rungs: list[str], frames: dict[str, Any]) -> Any:
    books = {r: frames[r][rnd.randrange(len(frames[r]))] for r in rungs if rnd.random() < 0.8}
    live = {r: rnd.randint(40, 90) for r in rungs if rnd.random() < 0.3}
    held = frozenset(r for r in rungs if rnd.random() < 0.15)
    return ev.DecisionContext(now, None, MappingProxyType(books), live, held)


@pytest.mark.parametrize("stress", ["none", "plus60", "poll_lag"])
@pytest.mark.parametrize("delta_ns", [0, 7 * SEC])
def test_adapter_selector_equals_the_original_algorithm_with_identical_side_effects(
    tmp_path: Path, stress: Any, delta_ns: int
) -> None:
    root = fx._build_root(tmp_path)
    fast, slow = fx._store(root), fx._store(root)
    rungs = [r.rung_id for r in fx.LADDER]
    edges = {r.rung_id: float("-inf") if r.lo is None else float(r.lo) for r in fx.LADDER}

    def mk(s: pno.PNoStore) -> adapter.SelectorConfig:
        return adapter.SelectorConfig(
            store=s,
            station="LAX",
            day=fx.DAY,
            stress=stress,
            delta_ns=delta_ns,
            theta=0.0695,
            lower_edges_f=edges,
        )

    cfg_fast, cfg_slow = mk(fast), mk(slow)
    t_fast, t_slow = adapter.WantTracker(), adapter.WantTracker()
    select = adapter.build_selector(cfg_fast, t_fast)
    rnd = random.Random(99)
    frames = {r: [_frame(rnd, r, i) for i in range(12)] for r in rungs}
    start = fx._ns(fx.DAY - dt.timedelta(days=1), 12)
    nows = sorted(rnd.randrange(start, start + 28 * 3600 * SEC) for _ in range(700))
    got_valid = 0
    for now in nows + nows:  # the second sweep exercises every cache hit
        ctx = _context(rnd, now, rungs, frames)
        want = _reference_decide(cfg_slow, t_slow, ctx)
        got = select(ctx)
        assert got == want
        got_valid += got.forecast_valid
    assert got_valid > 100
    assert t_fast.wanted_without_book == t_slow.wanted_without_book
    assert t_fast.abstentions == t_slow.abstentions
    assert fast.abstentions == slow.abstentions
    assert fast.abstention_counts == slow.abstention_counts
    assert fast.served == slow.served


# ---- level validation fast path -------------------------------------------------------------


@pytest.mark.parametrize(
    "levels",
    [((0, 1),), ((100, 1),), ((5, -1),), ((True, 1),), ((5, True),), ((5.0, 1),), ((5, 1.0),)],
)
def test_check_levels_fast_path_still_rejects_every_bad_level(levels: Any) -> None:
    with pytest.raises(ev.EventError):
        ev._check_levels(levels, "lv")


def test_check_levels_accepts_the_boundaries_and_int_subclasses_like_before() -> None:
    ev._check_levels(((1, 0), (99, 7)), "lv")
    ev._check_levels(((ev.Kind.DEPTH, 2),), "lv")  # an IntEnum member: an int by isinstance
