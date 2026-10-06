"""F7b-core: the pure e-process core (`analysis/autonomy/eprocess.py`), E-25 rule 3.

Rulings tested here: F7B-R12 (terminal precedence lives in the evaluator, not here), R13 (day set,
duplicates, ASCII keys), R14 (log-space comparisons), R15 (void independence), R16 (exact
enumeration with `fractions.Fraction`, a least-favourable-null Monte-Carlo, mutation tests), R21
(BE/X use the haircut `be`; the Z comparator uses the RAW ask), R23 (voids are explicit; an unknown
outcome on a settled day is refused), R24 (a day needs a coverage marker; a covered empty day is
Y = 0).
"""

from __future__ import annotations

import ast
import inspect
import itertools
import json
import math
import random
from collections.abc import Callable, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any, Final, Literal

import pytest

from breezy.analysis.autonomy import eprocess
from breezy.analysis.autonomy.eprocess import (
    BETTING_RULE_AGRAPA_V1,
    DayStat,
    EProcessDesign,
    EProcessRefused,
    GuardThresholds,
    TakeInput,
    agrapa_fraction,
    build_day_stats,
    crossed,
    daily_statistic,
    first_pass_n,
    order_takes,
    pass_bar,
    run_eprocess,
    take_x,
)
from tests.support.fq_eprocess_fixtures import (
    FIXTURE_A,
    FIXTURE_A_DAYS,
    FIXTURE_C_DAYS,
    FIXTURE_D_DAYS,
    Row,
    climate_day,
    fixture_b,
    fixture_c,
    fixture_d,
    ts_ns,
)
from tests.support.fq_mc_reference_vectors import REFERENCE

REPO: Final = Path(__file__).resolve().parents[3]
DESIGN_JSON: Final = (
    REPO / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json"
)
SRC_EPROCESS: Final = REPO / "src/breezy/analysis/autonomy/eprocess.py"
REL: Final = 1e-12


def design(**kw: object) -> EProcessDesign:
    base: dict[str, object] = {
        "m_cap": 2,
        "x_max": 4.0,
        "lambda_max": 0.5,
        "mu_max": 0.5,
        "earliest_look_n": 3,
    }
    return EProcessDesign(**{**base, **kw})  # type: ignore[arg-type]


def take(
    day: int = 0,
    ts: int = 100,
    station: str = "KNYC",
    rung: str = "r1",
    side: str = "yes",
    ask: float = 0.35,
    be: float = 0.3760128,
    p: float = 0.5,
    h: int | None = 1,
    void: bool = False,
) -> TakeInput:
    return TakeInput(
        climate_day=climate_day(day),
        decision_ts_ns=ts_ns(day, ts),
        station=station,
        rung_id=rung,
        side=side,
        be=be,
        raw_ask=ask,
        p_model=p,
        h=h,
        void=void,
    )


def takes_of(rows: Sequence[Row]) -> list[TakeInput]:
    return [
        take(d, ts, st, rg, sd, ask, be, p, h, void)
        for d, ts, st, rg, sd, ask, be, p, h, void in rows
    ]


def stats_of(rows: Sequence[Row], days: int, d: EProcessDesign) -> tuple[DayStat, ...]:
    return build_day_stats(
        takes_of(rows),
        covered_days=frozenset(climate_day(i) for i in range(days)),
        first_day=climate_day(0),
        last_settled_day=climate_day(days - 1),
        design=d,
    )


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL, abs_tol=1e-15)


# ---------------------------------------------------------------- X, Y, Z, ordering


def test_take_x_clips_upside_only() -> None:
    assert take_x(1, 0.1, 4.0) == 4.0  # 1/0.1 - 1 = 9 -> clipped
    assert take_x(1, 0.5, 4.0) == 1.0
    assert take_x(0, 0.01, 4.0) == -1.0  # the downside is never clipped


def test_eprocess_upside_clipped_at_x_max_downside_never_clipped() -> None:
    d = design()
    win = daily_statistic(climate_day(0), [take(be=0.05, h=1)], d)
    loss = daily_statistic(climate_day(0), [take(be=0.05, h=0)], d)
    assert win.y == 4.0 / 2
    assert loss.y == -1.0 / 2


def test_eprocess_daily_denominator_fixed_before_first_decision() -> None:
    d = design(m_cap=3)
    one = daily_statistic(climate_day(0), [take(be=0.5, h=1)], d)
    assert one.y == 1.0 / 3  # one take, three slots: empty slots count 0
    assert daily_statistic(climate_day(0), [], d).y == 0.0
    with pytest.raises(EProcessRefused):
        design(m_cap=4)
    with pytest.raises(EProcessRefused):
        design(m_cap=1)


def test_eprocess_m_d_is_pinned_m_cap_independent_of_listing_count() -> None:
    params = inspect.signature(daily_statistic).parameters
    assert set(params) == {"climate_day", "takes", "design"}  # no listing/slot-count input
    d = design()
    base = daily_statistic(climate_day(0), [take(be=0.5, h=1)], d)
    assert base.y == 0.5  # 1/m_cap, never 1/(takes seen)


def test_eprocess_uncounted_takes_disclosed_never_entered() -> None:
    d = design()
    four = [take(ts=t, rung=f"r{t}", be=0.5, h=h) for t, h in ((1, 1), (2, 0), (3, 1), (4, 1))]
    stat = daily_statistic(climate_day(0), four, d)
    assert (stat.n_takes, stat.uncounted) == (4, 2)
    assert stat.y == (1.0 + -1.0) / 2  # only the first two, in decision order
    states = run_eprocess((stat, stat), d)
    assert states[1].uncounted_cum == 4
    assert states[1].n_cum == 8


def test_eprocess_same_instant_ties_ordered_by_station_then_rung_id() -> None:
    a = take(station="KSFO", rung="r1", side="yes")
    b = take(station="KNYC", rung="r2", side="yes")
    c = take(station="KNYC", rung="r1", side="yes")
    e = take(station="KNYC", rung="r1", side="no")
    for perm in itertools.permutations([a, b, c, e]):
        ordered = order_takes(perm)
        assert [(t.station, t.rung_id, t.side) for t in ordered] == [
            ("KNYC", "r1", "no"),
            ("KNYC", "r1", "yes"),
            ("KNYC", "r2", "yes"),
            ("KSFO", "r1", "yes"),
        ]


def test_ordering_is_ascii_byte_order_and_time_first() -> None:
    upper, lower = take(station="Z"), take(station="a")
    assert order_takes([lower, upper])[0].station == "Z"  # 0x5A < 0x61, never locale order
    early = take(ts=5, station="Z")
    late = take(ts=6, station="A")
    assert order_takes([late, early])[0] is early


def test_non_ascii_key_refused() -> None:
    with pytest.raises(EProcessRefused, match="non_ascii_key"):
        take(station="KNYCé")


def test_ordering_never_reads_the_outcome() -> None:
    """R15 / R16: the order is a function of G-measurable keys only."""
    tree = ast.parse(SRC_EPROCESS.read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in ("_take_key", "order_takes"):
        attrs = {n.attr for n in ast.walk(fns[name]) if isinstance(n, ast.Attribute)}
        assert attrs.isdisjoint({"h", "void"}), name
    same = [take(h=1, rung="r1"), take(h=0, rung="r2")]
    flipped = [take(h=0, rung="r1"), take(h=1, rung="r2")]
    assert [t.rung_id for t in order_takes(same)] == [t.rung_id for t in order_takes(flipped)]


def test_eprocess_void_take_enters_as_zero_never_dropped() -> None:
    d = design()
    void = take(ts=1, rung="r1", void=True, h=None)
    win = take(ts=2, rung="r2", be=0.5, h=1)
    stat = daily_statistic(climate_day(0), [win, void], d)
    # the void keeps slot 1 as an explicit 0; the win takes slot 2 and is scored at X = 1
    assert stat.y == (0.0 + 1.0) / 2
    assert stat.n_takes == 2
    three = daily_statistic(climate_day(0), [take(ts=3, rung="r3", be=0.5, h=1), win, void], d)
    assert three.y == 0.5  # the third take is past the cap because the void held a slot
    assert three.uncounted == 1


def test_void_path_never_reads_outcome() -> None:
    """R15: a void carries no outcome; the docstring states the independence assumption."""
    with pytest.raises(EProcessRefused, match="void_with_outcome"):
        take(void=True, h=1)
    assert "independent" in (eprocess.__doc__ or "")
    src = SRC_EPROCESS.read_text(encoding="utf-8")
    assert "void must be independent of h" in src


def test_z_comparator_uses_the_raw_ask_not_be_f7b_r21() -> None:
    d = design()
    t = take(ask=0.35, be=0.60, p=0.55, h=1)
    stat = daily_statistic(climate_day(0), [t], d)
    expected_z = ((0.35 - 1) ** 2 - (0.55 - 1) ** 2) / 2
    assert close(stat.z, expected_z)
    # X uses the haircut be: 1/0.60 - 1
    assert close(stat.y, (1 / 0.60 - 1) / 2)
    # a be-based comparator would give a different number
    assert not close(stat.z, ((0.60 - 1) ** 2 - (0.55 - 1) ** 2) / 2)


def test_take_input_validation() -> None:
    for bad in (
        {"be": 0.0},
        {"be": float("nan")},
        {"ask": 1.5},
        {"p": -0.1},
        {"h": 2},
        {"h": True},
        {"station": ""},
    ):
        with pytest.raises(EProcessRefused):
            take(**bad)


# ---------------------------------------------------------------- day set (R13, R23, R24)


def test_uncovered_day_is_gap_refused() -> None:
    d = design()
    with pytest.raises(EProcessRefused, match="coverage_gap"):
        build_day_stats(
            takes_of(FIXTURE_A),
            covered_days=frozenset(climate_day(i) for i in range(FIXTURE_A_DAYS) if i != 3),
            first_day=climate_day(0),
            last_settled_day=climate_day(FIXTURE_A_DAYS - 1),
            design=d,
        )


def test_covered_zero_take_day_is_y0() -> None:
    stats = stats_of(FIXTURE_A, FIXTURE_A_DAYS, design())
    assert len(stats) == FIXTURE_A_DAYS  # contiguous calendar
    assert (stats[3].y, stats[3].z, stats[3].n_takes) == (0.0, 0.0, 0)
    states = run_eprocess(stats, design())
    assert states[3].n_cum == states[2].n_cum  # the day still counts toward n_prev


def test_unsettled_take_refused_not_voided() -> None:
    d = design()
    rows = [take(day=0, h=None, void=False)]
    with pytest.raises(EProcessRefused, match="unsettled_take_in_settled_day"):
        build_day_stats(
            rows,
            covered_days=frozenset({climate_day(0)}),
            first_day=climate_day(0),
            last_settled_day=climate_day(0),
            design=d,
        )
    with pytest.raises(EProcessRefused, match="unsettled_take_in_settled_day"):
        daily_statistic(climate_day(0), rows, d)


def test_takes_after_last_settled_day_are_not_processed() -> None:
    d = design()
    rows = [take(day=0, h=1, be=0.5), take(day=1, h=None, void=False)]
    stats = build_day_stats(
        rows,
        covered_days=frozenset({climate_day(0), climate_day(1)}),
        first_day=climate_day(0),
        last_settled_day=climate_day(0),
        design=d,
    )
    assert len(stats) == 1


def test_duplicate_take_refused_and_take_before_first_day_refused() -> None:
    d = design()
    kw = {
        "covered_days": frozenset({climate_day(0)}),
        "first_day": climate_day(0),
        "last_settled_day": climate_day(0),
        "design": d,
    }
    with pytest.raises(EProcessRefused, match="duplicate_take"):
        build_day_stats([take(), take()], **kw)  # type: ignore[arg-type]
    with pytest.raises(EProcessRefused, match="take_before_first_day"):
        build_day_stats([take(day=-1)], **kw)  # type: ignore[arg-type]


def test_empty_range_is_an_empty_series() -> None:
    assert (
        build_day_stats(
            [],
            covered_days=frozenset(),
            first_day=climate_day(5),
            last_settled_day=climate_day(4),
            design=design(),
        )
        == ()
    )


# ---------------------------------------------------------------- betting rule


def test_lambda_uses_settled_days_only_denominator_fixed_at_decision() -> None:
    d = design()
    base = list(stats_of(FIXTURE_A, FIXTURE_A_DAYS, d))
    s0 = run_eprocess(base, d)
    changed_today = list(base)
    changed_today[5] = DayStat(base[5].climate_day, 9.9, -0.4, base[5].n_takes, base[5].uncounted)
    s1 = run_eprocess(changed_today, d)
    assert s1[5].lambda_d == s0[5].lambda_d and s1[5].mu_d == s0[5].mu_d  # today never feeds today
    assert s1[6].lambda_d != s0[6].lambda_d  # tomorrow does
    # first day: zero settled days, so lambda is the prior only
    assert s0[0].lambda_d == agrapa_fraction(0.0, 0.0, 0, 0.5)


def test_agrapa_fraction_matches_the_pinned_rule() -> None:
    n = 3 + 1
    mu = 1.2 / n
    m2 = (2.0 + 0.25) / n
    var = max(m2 - mu * mu, 1e-6)
    assert close(agrapa_fraction(1.2, 2.0, 3, 0.5), min(max(mu / (var + mu * mu), 0.0), 0.5))
    assert agrapa_fraction(-5.0, 9.0, 3, 0.5) == 0.0  # never negative
    assert agrapa_fraction(1.0, 0.0, 3, 0.25) == 0.25  # never above the cap


def test_capital_nonnegative_bets_predictable() -> None:
    d = design()
    extreme = [DayStat(climate_day(i), -1.0, -1.0, 2, 0) for i in range(30)]
    extreme += [DayStat(climate_day(30 + i), 4.0, 1.0, 2, 0) for i in range(30)]
    states = run_eprocess(extreme, d)
    assert all(s.e_a > 0 and s.e_b > 0 for s in states)
    sy = sy2 = sz = sz2 = 0.0
    for i, s in enumerate(states):
        assert s.lambda_d == agrapa_fraction(sy, sy2, i, d.lambda_max)  # from prior days only
        assert s.mu_d == agrapa_fraction(sz, sz2, i, d.mu_max)
        sy, sy2 = sy + s.y, sy2 + s.y * s.y
        sz, sz2 = sz + s.z, sz2 + s.z * s.z


def test_factor_floor_is_asserted() -> None:
    build = [DayStat(climate_day(i), 4.0, 0.0, 1, 0) for i in range(5)]  # lambda reaches its cap
    bad = DayStat(climate_day(5), -3.0, 0.0, 1, 0)  # Y < -1 is impossible for a real day
    with pytest.raises(EProcessRefused, match="factor_below_floor"):
        run_eprocess([*build, bad], design())


def test_e_b_is_betting_process_not_cs_derived() -> None:
    d = design()
    stats = stats_of(FIXTURE_A, FIXTURE_A_DAYS, d)
    states = run_eprocess(stats, d)
    log_b = 0.0
    sz = sz2 = 0.0
    for i, (stat, st) in enumerate(zip(stats, states, strict=True)):
        mu = agrapa_fraction(sz, sz2, i, d.mu_max)
        log_b += math.log1p(mu * stat.z)
        assert close(st.log_e_b, log_b)
        sz, sz2 = sz + stat.z, sz2 + stat.z * stat.z
    imports = {
        n.module
        for n in ast.walk(ast.parse(SRC_EPROCESS.read_text(encoding="utf-8")))
        if isinstance(n, ast.ImportFrom) and n.module
    }
    assert not any("confidence_sequence" in m for m in imports)


def test_betting_rule_other_than_agrapa_v1_refused() -> None:
    assert BETTING_RULE_AGRAPA_V1 == "agrapa_v1:prior_pseudo_days=1,prior_second_moment=0.25"
    for field in ("betting_rule_e_a", "betting_rule_e_b"):
        with pytest.raises(EProcessRefused, match="betting_rule"):
            design(**{field: "agrapa_v1:prior_pseudo_days=2,prior_second_moment=0.25"})
        with pytest.raises(EProcessRefused, match="betting_rule"):
            design(**{field: "other"})


def test_design_bounds_refused() -> None:
    for bad in (
        {"x_max": 0.0},
        {"lambda_max": 0.0},
        {"lambda_max": 0.6},
        {"mu_max": 0.51},
        {"earliest_look_n": 0},
    ):
        with pytest.raises(EProcessRefused):
            design(**bad)


def test_design_fixture_matches_f5_design_json() -> None:
    raw = json.loads(DESIGN_JSON.read_text(encoding="utf-8"))
    d = EProcessDesign(
        m_cap=raw["m_cap"],
        x_max=raw["x_max"],
        lambda_max=raw["lambda_max"],
        mu_max=raw["mu_max"],
        earliest_look_n=raw["earliest_look_n"],
        betting_rule_e_a=raw["betting_rule_e_a"],
        betting_rule_e_b=raw["betting_rule_e_b"],
    )
    assert (d.m_cap, d.x_max, d.earliest_look_n) == (2, 4.0, 20)
    assert d.betting_rule_e_a == d.betting_rule_e_b == BETTING_RULE_AGRAPA_V1
    # production never reads the docs JSON
    assert "F5_prereg_v2_design" not in SRC_EPROCESS.read_text(encoding="utf-8")


# ---------------------------------------------------------------- log-space comparisons (R14)


def test_pass_bar_boundary_log_space() -> None:
    bar = pass_bar(0.025)
    assert bar == -math.log(0.025)
    assert crossed(bar, bar)  # >= at the boundary
    assert not crossed(math.nextafter(bar, 0.0), bar)
    assert crossed(math.nextafter(bar, math.inf), bar)
    from decimal import Decimal

    assert pass_bar(Decimal("0.025")) == pass_bar(0.025)  # converted once


def test_first_pass_n_respects_earliest_look_and_alpha() -> None:
    d = design()
    states = run_eprocess(stats_of(FIXTURE_A, FIXTURE_A_DAYS, d), d)
    assert first_pass_n(states, 0.9, earliest_look_n=3, which="a") == 3
    assert first_pass_n(states, 0.9, earliest_look_n=99, which="a") is None
    assert first_pass_n(states, 0.05, earliest_look_n=3, which="joint") is None


# ---------------------------------------------------------------- cross-check vs the F5 MC

CASES: Final = (
    ("A_m2", FIXTURE_A, FIXTURE_A_DAYS, 2, 3),
    ("A_m3", FIXTURE_A, FIXTURE_A_DAYS, 3, 3),
    ("B_m2", fixture_b(), 40, 2, 6),
    ("C_m2", fixture_c(), FIXTURE_C_DAYS, 2, 6),  # e_a crosses at alpha .05
    ("D_m2", fixture_d(), FIXTURE_D_DAYS, 2, 6),  # a losing book with clipped days
)


def test_c_fixture_e_a_crosses_at_alpha_005_and_d_has_clipped_days() -> None:
    ref_c, ref_d = REFERENCE["C_m2"], REFERENCE["D_m2"]
    assert ref_c["cross_a"][2] > 0  # alphas[2] == .05: e_a crosses the 1/alpha bar
    # the longshot's unclipped X is 1/0.1693408 - 1 = 4.905 > x_max, so the clipped day is
    # (4.0 - 1.0) / m_cap = 1.5, not (4.905 - 1.0) / 2 = 1.95
    assert 1 / 0.1693408 - 1 > 4.0
    assert max(ref_d["y"]) == pytest.approx(1.5, abs=1e-12)
    assert ref_d["kill_first_n"] > 0


@pytest.mark.parametrize(("key", "rows", "days", "m_cap", "elo"), CASES)
def test_eprocess_matches_f5_mc_reference_on_shared_fixtures(
    key: str, rows: Sequence[Row], days: int, m_cap: int, elo: int
) -> None:
    ref = REFERENCE[key]
    d = design(m_cap=m_cap, earliest_look_n=elo)
    states = run_eprocess(stats_of(rows, days, d), d)
    assert [s.n_cum for s in states] == ref["n_cum"]  # D7: all takes, voids included
    for name, attr in (
        ("y", "y"),
        ("z", "z"),
        ("lam", "lambda_d"),
        ("mu", "mu_d"),
        ("log_e_a", "log_e_a"),
        ("log_e_b", "log_e_b"),
    ):
        got = [getattr(s, attr) for s in states]
        assert all(close(g, r) for g, r in zip(got, ref[name], strict=True)), (key, name)
    for alpha, joint, a, b in zip(
        ref["alphas"], ref["cross_joint"], ref["cross_a"], ref["cross_b"], strict=True
    ):
        wanted: tuple[tuple[Literal["joint", "a", "b"], int], ...] = (
            ("joint", joint),
            ("a", a),
            ("b", b),
        )
        for which, want in wanted:
            got_n = first_pass_n(states, alpha, earliest_look_n=elo, which=which)
            assert got_n == (None if want < 0 else want), (key, alpha, which)


# ---------------------------------------------------------------- null validity (R16)

# Each enumerated day is a list of (probability, outcomes-of-takes); probabilities are Fractions.
Branch = tuple[Fraction, list[tuple[float, int]]]  # (prob, [(be, h)...])


def _bern_day(be: float, q: Fraction, n_takes: int) -> list[Branch]:
    out: list[Branch] = []
    for hs in itertools.product((0, 1), repeat=n_takes):
        w = Fraction(1)
        for h in hs:
            w *= q if h else 1 - q
        out.append((w, [(be, h) for h in hs]))
    return out


def _stopping_day(be: float, q: Fraction, max_takes: int) -> list[Branch]:
    """Intraday-dependent take count: the next take happens only after a LOSS (decided at decision
    time from past outcomes, so G-measurable)."""
    out: list[Branch] = []

    def go(prefix: list[tuple[float, int]], w: Fraction) -> None:
        if len(prefix) == max_takes:
            out.append((w, prefix))
            return
        for h, p in ((1, q), (0, 1 - q)):
            nxt = [*prefix, (be, h)]
            if h == 1:
                out.append((w * p, nxt))
            else:
                go(nxt, w * p)

    go([], Fraction(1))
    return out


def _mixed_side_day() -> list[Branch]:
    """One station-day with a yes take (be .25) and a no take (be .75): perfectly anti-correlated,
    each exactly mean-zero (P(yes wins) = 1/4)."""
    return [(Fraction(1, 4), [(0.25, 1), (0.75, 0)]), (Fraction(3, 4), [(0.25, 0), (0.75, 1)])]


def _day_stat(i: int, branch: list[tuple[float, int]], d: EProcessDesign) -> DayStat:
    ts = [
        take(
            day=i,
            ts=k + 1,
            rung=f"r{k}",
            side="yes" if k == 0 else "no",
            be=be,
            h=h,
            ask=0.4,
            p=0.6,
        )
        for k, (be, h) in enumerate(branch)
    ]
    return daily_statistic(climate_day(i), ts, d)


def _expectation(
    days: Sequence[list[Branch]], d: EProcessDesign, stat: Callable[[Sequence[DayStat]], float]
) -> Fraction:
    total = Fraction(0)
    for path in itertools.product(*days):
        w = Fraction(1)
        stats = []
        for i, (pw, branch) in enumerate(path):
            w *= pw
            stats.append(_day_stat(i, branch, d))
        total += w * Fraction(stat(stats))
    return total


def _e_a(stats: Sequence[DayStat]) -> float:
    return math.exp(run_eprocess(stats, design())[-1].log_e_a)


TOL: Final = Fraction(1, 10**9)


def test_enumeration_e_a_is_exactly_one_at_the_null() -> None:
    days = [_bern_day(0.25, Fraction(1, 4), 2) for _ in range(3)]
    assert abs(_expectation(days, design(), _e_a) - 1) < TOL  # E[e_a] = 1: Bernoulli at BE


def test_enumeration_e_a_le_one_under_clipping() -> None:
    # be = 1/8 -> X = 7 clipped to 4; P(win) = 1/8 so the clipped mean is negative: E[e_a] <= 1
    days = [_bern_day(0.125, Fraction(1, 8), 2) for _ in range(3)]
    assert _expectation(days, design(), _e_a) <= 1 + TOL


def test_eprocess_null_mc_intraday_dependent_take_count() -> None:
    days = [_stopping_day(0.25, Fraction(1, 4), 3) for _ in range(3)]
    assert abs(_expectation(days, design(), _e_a) - 1) < TOL
    d3 = design(m_cap=3)

    def e_a3(stats: Sequence[DayStat]) -> float:
        return math.exp(run_eprocess(stats, d3)[-1].log_e_a)

    assert abs(_expectation(days, d3, e_a3) - 1) < TOL


def test_eprocess_null_mc_mixed_side_same_station_day() -> None:
    days = [_mixed_side_day() for _ in range(4)]
    assert abs(_expectation(days, design(), _e_a) - 1) < TOL


def test_enumeration_e_b_is_at_most_one_at_the_comparator_null() -> None:
    # model p = .6 against comparator ask .4: P(h) = (a + p)/2 = .5 makes E[Z] = 0 exactly
    days = [_bern_day(0.5, Fraction(1, 2), 2) for _ in range(3)]

    def e_b(stats: Sequence[DayStat]) -> float:
        return math.exp(run_eprocess(stats, design())[-1].log_e_b)

    assert abs(_expectation(days, design(), e_b) - 1) < TOL


def _lambda_today_e_a(stats: Sequence[DayStat]) -> float:
    """MUTATION: the bet may see today's Y (not predictable)."""
    sy = sy2 = 0.0
    log_e = 0.0
    for i, s in enumerate(stats):
        lam = agrapa_fraction(sy + s.y, sy2 + s.y * s.y, i, 0.5)
        log_e += math.log1p(lam * s.y)
        sy, sy2 = sy + s.y, sy2 + s.y * s.y
    return math.exp(log_e)


def test_mutation_lambda_uses_the_current_day_fails_the_enumeration() -> None:
    days = [_bern_day(0.25, Fraction(1, 4), 2) for _ in range(3)]
    assert _expectation(days, design(), _lambda_today_e_a) > 1 + Fraction(1, 100)


def test_mutation_outcome_dependent_ordering_fails_the_enumeration() -> None:
    """MUTATION: the takes are ordered best-outcome-first before the cap, so the counted slots are
    the winners. The enumeration over three takes at m_cap 2 sees E[Y] > 0."""
    d = design()
    days = [_bern_day(0.25, Fraction(1, 4), 3) for _ in range(3)]

    total = Fraction(0)
    for path in itertools.product(*days):
        w = Fraction(1)
        stats: list[DayStat] = []
        for i, (pw, branch) in enumerate(path):
            w *= pw
            best_first = sorted(branch, key=lambda bh: -bh[1])
            stats.append(_day_stat(i, best_first, d))
        total += w * Fraction(_e_a(stats))
    assert total > 1 + Fraction(1, 100)
    # the correct, outcome-blind ordering is fine on the same tree
    assert abs(_expectation(days, d, _e_a) - 1) < TOL


def test_mutation_dropping_voids_from_the_count_is_caught() -> None:
    """A void keeps its slot AND counts in n_cum. Dropping it changes both (the E[e] enumeration
    cannot see it: void independence makes either choice unbiased, R15), so it is a direct check."""
    d = design()
    v = take(ts=1, rung="r1", void=True, h=None)
    w = take(ts=2, rung="r2", be=0.5, h=1)
    kept = daily_statistic(climate_day(0), [v, w], d)
    dropped = daily_statistic(climate_day(0), [w], d)
    assert (kept.n_takes, dropped.n_takes) == (2, 1)
    # independent of `kept`: the whole pipeline (takes -> build_day_stats -> run_eprocess)
    pipeline = {
        label: run_eprocess(
            build_day_stats(
                takes,
                covered_days=frozenset({climate_day(0)}),
                first_day=climate_day(0),
                last_settled_day=climate_day(0),
                design=d,
            ),
            d,
        )[0].n_cum
        for label, takes in (("with_void", [v, w]), ("void_dropped", [w]))
    }
    assert pipeline == {"with_void": 2, "void_dropped": 1}


def test_h0_crossing_rate_le_alpha_exact_null() -> None:
    """Least-favourable null: be = .15 (X = 4 clipped), P(win) = .2 gives E[clipped X] = 0
    exactly; the bet is forced to its maximum 0.5 and the clip is active. Ville: P(sup e >= 1/a)
    <= a. Fixed seed, well under 10 s."""
    rng = random.Random(20261006)
    alpha, reps, days = 0.05, 3000, 30
    d = design()
    bar = pass_bar(alpha)
    hits = 0
    for _ in range(reps):
        log_e = 0.0
        for i in range(days):
            ts = [
                take(day=i, ts=k + 1, rung=f"r{k}", be=0.15, h=1 if rng.random() < 0.2 else 0)
                for k in range(2)
            ]
            log_e += math.log1p(0.5 * daily_statistic(climate_day(i), ts, d).y)
            if crossed(log_e, bar):
                hits += 1
                break
    se = math.sqrt(alpha * (1 - alpha) / reps)
    assert hits / reps <= alpha + 3 * se


def test_production_pipeline_crossing_rate_le_alpha_at_the_null() -> None:
    rng = random.Random(7)
    alpha, reps, days = 0.1, 1500, 30
    d = design()
    hits = 0
    for _ in range(reps):
        stats = []
        for i in range(days):
            ts = [
                take(day=i, ts=k + 1, rung=f"r{k}", be=0.25, h=1 if rng.random() < 0.25 else 0)
                for k in range(2)
            ]
            stats.append(daily_statistic(climate_day(i), ts, d))
        if first_pass_n(run_eprocess(stats, d), alpha, earliest_look_n=1, which="a") is not None:
            hits += 1
    assert hits / reps <= alpha + 3 * math.sqrt(alpha * (1 - alpha) / reps)


def test_guard_thresholds_validation_and_optional_design_field() -> None:
    ok = GuardThresholds(4, 3.0, (0.5, 1.5), (0.0, 0.5, 1.0), "pooled")
    assert design().guard is None  # F7B-R11: unpinned by default
    assert design(guard=ok).guard is ok
    for bad in (
        {"n_guard_min": 0},
        {"spiegelhalter_abs_z_max": 0.0},
        {"slope_band": (1.0, 1.0)},
        {"bin_edges": (0.1, 1.0)},  # must start at 0.0
        {"bin_edges": (0.0, 0.9)},  # must end at 1.0
        {"bin_edges": (0.0, 0.5, 0.5, 1.0)},
        {"pooling": "weighted"},
    ):
        kw: dict[str, Any] = {
            "n_guard_min": 4,
            "spiegelhalter_abs_z_max": 3.0,
            "slope_band": (0.5, 1.5),
            "bin_edges": (0.0, 0.5, 1.0),
            "pooling": "per_side",
            **bad,
        }
        with pytest.raises(EProcessRefused):
            GuardThresholds(**kw)
    with pytest.raises(EProcessRefused):
        design(guard="x")
