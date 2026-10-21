"""WP-C1: the live `no_ladder_maker` decision core equals the Stage 0 scripts, line for line.

Every ported function is driven over a grid next to its `scripts.analysis` original. The
originals read module globals, so each side runs under the design driver's own `rule_override`
for the arm under test (`sharp`: `ARMS["sharp"]`; `control`: the shipped constants).
"""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.nbp_derived_store import (
    PUBLICATION_LAG_FLOOR_NS,
    DerivedNbpRow,
    partition_path,
    read_partition,
)
from breezy.strategy.no_ladder_maker import params as p
from breezy.strategy.no_ladder_maker import pno, pno_store, rule, selector
from breezy.strategy.no_ladder_maker import records as t
from scripts.analysis import maker_stage0_adapter as s_adapter
from scripts.analysis import maker_stage0_fill_events as s_events
from scripts.analysis import maker_stage0_pno as s_pno
from scripts.analysis import maker_stage0_pno_store as s_store
from scripts.analysis import maker_stage0_rule as s_rule
from scripts.analysis.maker_design_config import ARMS
from scripts.analysis.maker_design_nobid import rule_override
from tests.unit import test_maker_stage0_pno as pno_fx

NS_H = 3_600 * 10**9
THETAS = (0.0, 0.06, 0.0695)
P_NOS = (0.0, 0.5, 0.93, 0.94, 0.95, 0.96, 0.969, 0.97, 0.975, 0.98, 0.99, 1.0)
BEST_BIDS = (None, 0.5, 0.7, 0.74, 0.75, 0.8, 0.85, 0.88, 0.89, 0.9)
NO_ASKS = (None, 0.7, 0.75, 0.8, 0.9, 0.95, 1.0)
DAY = dt.date(2026, 9, 29)
GRID_SIZE: list[int] = []


def _override(name: str) -> AbstractContextManager[None]:
    if name == "control":
        return nullcontext()
    arm = ARMS[name]
    return rule_override(
        arm.b_cap, arm.max_rungs, p_min=arm.p_min, e_min=arm.e_min, b_floor=arm.b_floor
    )


PARAMS: Mapping[str, p.MakerRuleParams] = {"sharp": p.SHARP_V1, "control": p.CONTROL_V1}


@pytest.fixture(params=sorted(PARAMS))
def arm(request: pytest.FixtureRequest) -> Iterator[tuple[str, p.MakerRuleParams]]:
    with _override(request.param):
        yield request.param, PARAMS[request.param]


def _same(
    ported: Callable[..., Any],
    original: Callable[..., Any],
    *args: Any,
    extra: tuple[Any, ...] = (),
) -> Any:
    """Both succeed with equal values or both raise ValueError with the same message.

    The ported function gets ``*args, *extra`` (its injected params); the original ``*args``.
    """
    outcomes = []
    for fn, call_args in ((ported, (*args, *extra)), (original, args)):
        try:
            value = fn(*call_args)
            if isinstance(value, rule.BidDecision | s_rule.BidDecision):
                value = (value.bid, value.reason)
            outcomes.append(("ok", value))
        except ValueError as exc:
            outcomes.append(("err", str(exc)))
    assert outcomes[0] == outcomes[1]
    GRID_SIZE.append(1)
    return outcomes[0]


def test_sharp_params_match_the_design_arm() -> None:
    arm_ = ARMS["sharp"]
    sharp = p.SHARP_V1
    assert (sharp.p_min, sharp.e_min, sharp.b_floor, sharp.b_cap, sharp.max_rungs) == (
        0.97, 0.04, 0.75, 0.89, 2,
    )  # fmt: skip
    assert (sharp.b_cap, sharp.max_rungs, sharp.p_min, sharp.e_min, sharp.b_floor) == (
        arm_.b_cap, arm_.max_rungs, arm_.p_min, arm_.e_min, arm_.b_floor,
    )  # fmt: skip
    assert sharp.stale_h == s_pno.STALE_H == 8
    assert sharp.abstain_unlisted is False and arm_.abstain is False
    assert sharp.max_simultaneous == 8


def test_control_params_match_the_shipped_rule() -> None:
    c = p.CONTROL_V1
    assert (c.p_min, c.e_min, c.b_floor, c.b_cap, c.max_rungs, c.cancel_lst) == (
        s_rule.P_MIN, s_rule.E_MIN, s_rule.B_FLOOR, s_rule.B_CAP, s_rule.MAX_RUNGS,
        s_rule.CANCEL_LST,
    )  # fmt: skip
    assert c.abstain_unlisted is ARMS["control"].abstain


def test_params_are_frozen() -> None:
    with pytest.raises(AttributeError):
        p.SHARP_V1.p_min = 0.5  # type: ignore[misc]


def test_b_max_and_decide_bid_grid(arm: tuple[str, p.MakerRuleParams]) -> None:
    _, params = arm
    for theta, p_no in itertools.product(THETAS, P_NOS):
        _same(rule.b_max, s_rule.b_max, p_no, theta, extra=(params,))
        for bid, ask in itertools.product(BEST_BIDS, NO_ASKS):
            got = rule.decide_bid(p_no, bid, ask, theta, params)
            want = s_rule.decide_bid(p_no, bid, ask, theta)
            assert (got.bid, got.reason) == (want.bid, want.reason)
            GRID_SIZE.append(1)
    assert len(GRID_SIZE) >= len(THETAS) * len(P_NOS) * len(BEST_BIDS) * len(NO_ASKS)


@pytest.mark.parametrize("bad", [float("nan"), -0.1, 1.1])
def test_invalid_probability_and_theta_raise_like_the_original(
    arm: tuple[str, p.MakerRuleParams], bad: float
) -> None:
    _, params = arm
    _same(rule.decide_bid, s_rule.decide_bid, bad, None, None, 0.0695, extra=(params,))
    _same(rule.decide_bid, s_rule.decide_bid, 0.99, None, None, bad, extra=(params,))


def test_forecast_gate_grid(arm: tuple[str, p.MakerRuleParams]) -> None:
    _, params = arm
    ages = (-1, 0, 1, 8 * NS_H - 1, 8 * NS_H, 8 * NS_H + 1, 40 * NS_H)
    days = (None, DAY, DAY - dt.timedelta(days=1))
    for vday, age in itertools.product(days, ages):
        _same(rule.forecast_gate, s_rule.forecast_gate, vday, DAY, age, extra=(params,))


EDGES = {"a": float("-inf"), "b": 80.0, "c": 82.0, "d": 84.0, "e": 86.0, "f": 88.0}
P_YES_SETS = (
    {"a": 0.9, "b": 0.05, "c": 0.02, "d": 0.01, "e": 0.01, "f": 0.01},
    {"a": 0.01, "b": 0.01, "c": 0.01, "d": 0.01, "e": 0.01, "f": 0.01},  # ties
    {"a": 0.0, "b": 0.0, "c": 0.97, "d": 0.02, "e": 0.0, "f": 0.01},
    {"a": 0.02, "b": 0.5, "c": 0.4, "d": 0.03, "e": 0.02, "f": 0.03},
    {"a": 0.1, "b": 0.1, "c": 0.1, "d": 0.1, "e": 0.1, "f": 0.5},
)
BID_SETS: tuple[dict[str, float | None], ...] = (
    dict.fromkeys(EDGES, 0.8),
    {"a": None, "b": 0.74, "c": 0.75, "d": 0.76, "e": None, "f": 0.89},
    {"a": 0.9, "b": 0.7, "c": 0.8, "d": 0.8},  # missing keys
    {},
)


def test_ladder_plan_select_and_k1_grid(arm: tuple[str, p.MakerRuleParams]) -> None:
    _, params = arm
    for p_yes, bids in itertools.product(P_YES_SETS, BID_SETS):
        got = rule.ladder_plan(p_yes, EDGES, params).select(bids)
        want = s_rule.ladder_plan(p_yes, EDGES).select(bids)
        assert got == want
        assert rule.select_rungs(p_yes, bids, lower_edges_f=EDGES, params=params) == want
        assert rule.k1_rung(got) == s_rule.k1_rung(want)
        GRID_SIZE.append(1)
    assert rule.k1_rung(()) is None


def test_ladder_plan_errors_match(arm: tuple[str, p.MakerRuleParams]) -> None:
    _, params = arm
    bad: tuple[tuple[dict[str, float], dict[str, float]], ...] = (
        ({"a": 1.5}, {"a": 1.0}),
        ({"a": float("nan")}, {"a": 1.0}),
        ({"a": 0.1, "b": 0.2}, {"a": 1.0, "b": 1.0}),
        ({"a": 0.1, "b": 0.2}, {"a": 1.0}),
        ({"a": 0.1, "b": 0.2}, {"a": 1.0, "b": float("nan")}),
        ({}, {}),
    )
    for p_yes, edges in bad:
        _same(
            lambda *a: rule.ladder_plan(*a).rungs,
            lambda *a: s_rule.ladder_plan(*a).rungs,
            p_yes,
            edges,
            extra=(params,),
        )


def test_clock_helpers_grid(arm: tuple[str, p.MakerRuleParams]) -> None:
    _, params = arm
    for day, off in itertools.product((DAY, dt.date(2026, 3, 8)), (-8, -7, -6, -5, 0)):
        assert rule.hard_cancel_ns(day, off, params) == s_rule.hard_cancel_ns(day, off)
    noon = int(dt.datetime(2026, 9, 29, 12, tzinfo=dt.UTC).timestamp()) * 10**9
    for now, cancel, permit in itertools.product(
        (noon, noon + 11 * NS_H + 1), (noon - 1, noon + 5 * NS_H), (noon + NS_H, noon + 30 * NS_H)
    ):
        assert rule.gtd_expire_ns(now, cancel, permit) == s_rule.gtd_expire_ns(now, cancel, permit)
    for upper, edge, intc in itertools.product(
        (76.0, 77.9, 78.0, 80.0), (80.0, 82.0), (False, True)
    ):
        assert rule.obs_cancel(upper, edge, intc) == s_rule.obs_cancel(upper, edge, intc)
    deadline = int(dt.datetime(2026, 9, 28, 12, tzinfo=dt.UTC).timestamp()) * 10**9
    for listed in (None, deadline - 1, deadline, deadline + 1):
        assert rule.listed_in_time(listed, DAY) == s_rule.listed_in_time(listed, DAY)


def test_reason_vocabulary_matches() -> None:
    names = {n for n in vars(s_rule) if n.startswith("REASON_")}
    assert names == {n for n in vars(rule) if n.startswith("REASON_")}
    for n in names:
        assert getattr(rule, n) == getattr(s_rule, n)


# --- pno store and selector on synthetic NBP rows -------------------------------------------

EDGES5 = {"lt80": float("-inf"), "r80": 80.0, "r82": 82.0, "r84": 84.0, "ge86": 86.0}
AFTER_19Z = pno_fx._ns(DAY, 0, 0) - 3 * NS_H


class _Source:
    """`PartitionSource` over the persistence layer (tests and offline tools may import it)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def partition_path(self, cycle_date: dt.date, hour: int) -> Path:
        return partition_path(self._root, cycle_date, hour)

    def read_partition(self, path: Path) -> Sequence[DerivedNbpRow]:
        return read_partition(path)


def _stores(tmp_path: Path) -> tuple[pno.PNoStore, s_pno.PNoStore]:
    root = pno_fx._build_root(tmp_path)
    cal = pno_fx._calibration()
    ladders = {("SFO", DAY): pno_fx.LADDER}
    ported = pno.PNoStore.from_source(
        _Source(root), stations=("SFO",), days=[DAY], calibration=cal, ladders=ladders
    )
    original = s_pno.PNoStore.from_root(
        root, stations=("SFO",), days=[DAY], calibration=cal, ladders=ladders
    )
    return ported, original


def test_pno_module_surface_is_the_store_surface() -> None:
    assert pno.PNoStore is pno_store.PNoStore
    assert pno_store.STATIONS == s_store.STATIONS and pno_store.VENUE == s_store.VENUE


def test_pinned_first_max_column_and_delay_match(tmp_path: Path) -> None:
    for day in (DAY, dt.date(2026, 1, 1), dt.date(2026, 3, 1)):
        assert pno_store._pinned(day) == s_store._pinned(day)
    root = pno_fx._build_root(tmp_path)
    got: Any = pno_store.read_pinned(_Source(root), "KSFO", DAY)
    want: Any = s_store.read_pinned(root, "KSFO", DAY)
    assert got == want  # rows, consumed, missing
    assert pno_store._first_max_column(got.rows) == s_store._first_max_column(want.rows)
    for row, stress in itertools.product(want.rows, ("none", "plus60", "poll_lag")):
        assert pno_store._delay_ns(row, stress) == s_store._delay_ns(row, stress)  # type: ignore[arg-type]
    assert pno_store.build_chain(pno_store.build_state(got.rows, -8.0, "plus60"), DAY).releases == (
        s_store.build_chain(s_store.build_state(want.rows, -8.0, "plus60"), DAY).releases
    )


def test_publication_lag_floor_is_the_derived_stores_floor() -> None:
    assert pno_store.PUBLICATION_LAG_FLOOR_NS == PUBLICATION_LAG_FLOOR_NS


def test_missing_and_corrupt_partitions_behave_like_the_original(tmp_path: Path) -> None:
    root = pno_fx._build_root(tmp_path / "gap", hours=(13, 1))
    got: Any = pno_store.read_pinned(_Source(root), "KSFO", DAY)
    want: Any = s_store.read_pinned(root, "KSFO", DAY)
    assert got == want and want.missing  # the 19Z partition is absent
    full = pno_fx._build_root(tmp_path / "bad")
    victim = partition_path(full, DAY - dt.timedelta(days=1), 19)
    victim.write_bytes(b"not a parquet file")
    outcomes = []
    reads: tuple[tuple[Callable[..., Any], Any], ...] = (
        (pno_store.read_pinned, _Source(full)),
        (s_store.read_pinned, full),
    )
    for fn, src in reads:
        with pytest.raises(Exception) as info:
            fn(src, "KSFO", DAY)
        outcomes.append((info.type.__name__, str(info.value)))
    assert outcomes[0][0] == "PNoStoreReadError" and outcomes[0] == outcomes[1]


def _instants() -> list[int]:
    base = [pno_fx._ns(DAY, 0, 0) + h * NS_H for h in range(-36, 14, 1)]
    return sorted({*base, *(b + d for b in base[::7] for d in (-1, 1, 60 * 10**9))})


@pytest.mark.parametrize("stress", ["none", "plus60", "poll_lag"])
def test_classify_p_no_and_releases_match(
    arm: tuple[str, p.MakerRuleParams], tmp_path: Path, stress: Any
) -> None:
    _, params = arm
    ported, original = _stores(tmp_path)
    assert pno.release_instants(ported, "SFO", DAY, stress=stress) == s_pno.release_instants(
        original, "SFO", DAY, stress=stress
    )
    for now in _instants():
        got = pno.classify_p_no(ported, "SFO", DAY, now, stress=stress, stale_h=params.stale_h)
        want = s_pno.classify_p_no(original, "SFO", DAY, now, stress=stress)
        if isinstance(want, s_pno.AbstainReason):
            assert isinstance(got, pno.AbstainReason)
            assert (got.reason, got.station, got.climate_day, got.stress) == (
                want.reason, want.station, want.climate_day, want.stress,
            )  # fmt: skip
        else:
            assert isinstance(got, pno.PNoAtInstant)
            assert dict(got.p_yes_point_live) == dict(want.p_yes_point_live)
            assert dict[str, Any](got.bounds) == dict[str, Any](want.bounds)
            assert (got.cycle, got.available_at_ns, got.vintage_age_s, got.vector) == (
                want.cycle, want.available_at_ns, want.vintage_age_s, want.vector,
            )  # fmt: skip
        GRID_SIZE.append(1)
    assert ported.abstention_counts == original.abstention_counts
    assert ported.served == original.served


def test_classify_refuses_nyc_and_unloaded_like_the_original(tmp_path: Path) -> None:
    ported, original = _stores(tmp_path)
    for station, day in (("NYC", DAY), ("SFO", DAY + dt.timedelta(days=3))):
        outcomes = []
        calls: tuple[tuple[Callable[..., Any], Any, dict[str, int]], ...] = (
            (pno.classify_p_no, ported, {"stale_h": 8}),
            (s_pno.classify_p_no, original, {}),
        )
        for fn, store, extra in calls:
            with pytest.raises(Exception) as info:
                fn(store, station, day, 1, stress="none", **extra)
            outcomes.append((info.type.__name__, str(info.value)))
        assert outcomes[0] == outcomes[1]


def _frames(ask: int, bid: int, rung: str) -> tuple[t.DepthFrame, s_events.DepthFrame]:
    ours = t.DepthFrame(rung_id=rung, ts_ns=AFTER_19Z - 1, yes_bids=((bid, 10),),
                        yes_asks=((ask, 10),))  # fmt: skip
    theirs = s_events.DepthFrame(rung_id=rung, ts_ns=AFTER_19Z - 1, yes_bids=((bid, 10),),
                                 yes_asks=((ask, 10),))  # fmt: skip
    return ours, theirs


BOOK_SHAPES: tuple[dict[str, tuple[int, int]], ...] = (
    {r: (25, 15) for r in EDGES5},
    {r: (12, 8) for r in EDGES5},
    {r: (30, 40) for r in EDGES5},  # crossed-ish: no_ask low
    {"lt80": (25, 15), "r84": (22, 10), "ge86": (18, 5)},  # missing books
    {},
)
LIVE_HELD: tuple[tuple[dict[str, int], frozenset[str]], ...] = (
    ({}, frozenset[str]()),
    ({"ge86": 76, "r84": 70}, frozenset[str]()),
    ({"r82": 70, "lt80": 70}, frozenset({"ge86"})),
    ({}, frozenset({"ge86", "r84"})),
)


def _contexts() -> Iterator[tuple[t.DecisionContext, s_events.DecisionContext]]:
    nows = [AFTER_19Z, AFTER_19Z - 30 * NS_H, pno_fx._ns(DAY, 0) + 11 * NS_H, *_instants()[::5]]
    for now, shape, (live, held) in itertools.product(nows, BOOK_SHAPES, LIVE_HELD):
        ours: dict[str, t.DepthFrame] = {}
        theirs: dict[str, s_events.DepthFrame] = {}
        for rung, (ask, bid) in shape.items():
            ours[rung], theirs[rung] = _frames(ask, bid, rung)
        yield (
            t.DecisionContext(now_ns=now, books=ours, live_bids=live, held=held),
            s_events.DecisionContext(
                now_ns=now, vector=None, books=theirs, live_bids=live, held=held
            ),
        )


def _flat(d: t.Decision | s_events.Decision) -> tuple[Any, ...]:
    desired = tuple((x.rung_id, x.bid_cents) for x in d.desired)
    return (desired, d.drop_reason, d.forecast_valid, dict(d.dropped))


def test_book_quotes_match() -> None:
    for ask, bid in itertools.product((1, 12, 25, 99), (1, 15, 40, 98)):
        ours, theirs = _frames(ask, bid, "x")
        assert selector.best_no_bid(ours) == s_adapter.best_no_bid(theirs)
        assert selector.no_ask(ours) == s_adapter.no_ask(theirs)
    ours = t.DepthFrame(rung_id="x", ts_ns=0, yes_bids=((50, 0),), yes_asks=((60, 0),))
    theirs = s_events.DepthFrame(rung_id="x", ts_ns=0, yes_bids=((50, 0),), yes_asks=((60, 0),))
    assert selector.best_no_bid(ours) is None is s_adapter.best_no_bid(theirs)
    assert selector.no_ask(ours) is None is s_adapter.no_ask(theirs)
    assert (
        selector.best_no_bid(t.DepthFrame(rung_id="x", ts_ns=0, yes_bids=(), yes_asks=())) is None
    )


def test_drop_reason_map_matches() -> None:
    assert dict(selector.DROP_REASON_FOR) == dict(s_adapter.DROP_REASON_FOR)
    for reason in s_adapter.DROP_REASON_FOR:
        assert selector.drop_reason_for(reason) == s_adapter.drop_reason_for(reason)
    with pytest.raises(ValueError, match="no drop reason"):
        selector.drop_reason_for("made_up_reason")


@pytest.mark.parametrize("stress", ["none", "plus60"])
@pytest.mark.parametrize("delta_ns", [0, 600 * 10**9, -600 * 10**9])
def test_selector_decisions_match_over_contexts(
    arm: tuple[str, p.MakerRuleParams], tmp_path: Path, stress: Any, delta_ns: int
) -> None:
    _, params = arm
    ported_store, original_store = _stores(tmp_path)
    t_ours, t_theirs = selector.WantTracker(), s_adapter.WantTracker()
    ours = selector.build_selector(
        selector.SelectorConfig(
            store=ported_store, station="SFO", day=DAY, stress=stress, delta_ns=delta_ns,
            theta=0.0695, lower_edges_f=EDGES5, params=params,
        ),
        t_ours,
    )  # fmt: skip
    theirs = s_adapter.build_selector(
        s_adapter.SelectorConfig(
            store=original_store, station="SFO", day=DAY, stress=stress, delta_ns=delta_ns,
            theta=0.0695, lower_edges_f=EDGES5,
        ),
        t_theirs,
    )  # fmt: skip
    valid = 0
    for ctx_ours, ctx_theirs in _contexts():
        got, want = ours(ctx_ours), theirs(ctx_theirs)
        assert _flat(got) == _flat(want)
        valid += bool(want.desired)
        GRID_SIZE.append(1)
    assert valid > 0  # the grid really reaches priced decisions
    assert t_ours.wanted_without_book == t_theirs.wanted_without_book
    assert t_ours.abstentions == t_theirs.abstentions


def test_rung_pricer_memoises_like_the_original(arm: tuple[str, p.MakerRuleParams]) -> None:
    _, params = arm
    calls: list[int] = []

    def quote(frame: t.DepthFrame | None) -> tuple[float | None, float | None]:
        calls.append(1)
        return (0.75, 0.9)

    pricer = selector.RungPricer(0.0695, quote, params)
    frame, _ = _frames(25, 15, "r")
    first = pricer.price("r", frame, 0.99)
    assert pricer.price("r", frame, 0.99) is first and len(calls) == 1
    pricer.price("r", frame, 0.98)
    assert len(calls) == 2
    want = s_rule.decide_bid(0.99, 0.75, 0.9, 0.0695)
    assert (first.bid, first.reason) == (want.bid, want.reason)
