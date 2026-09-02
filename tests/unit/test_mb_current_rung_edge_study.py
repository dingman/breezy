"""Unit tests for M_B -- the current-rung p_hold x ask edge measurement.

Spec: `docs/evidence/grok_mb_design_2026-09-02.md` SS1 (archive table, tape
join, per-station-day statistic, kill sentence) and SS2 (survivorship and
latency traps). Pure-logic fixtures only -- no catalog, no network, no
Nautilus data types, matching the sibling `test_ma_prelock_winner_ask_study`
suite's shape.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_MDW_STD_OFFSET_HOURS = -6.0  # UTC-6, no DST -- local standard time all year.
_CLIMATE_DAY = dt.date(2026, 8, 31)


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "mb_current_rung_edge_study.py"
    spec = importlib.util.spec_from_file_location("mb_current_rung_edge_study", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mb() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    return _load_module()


def _lst_to_utc(hour: int, minute: int, *, day: dt.date = _CLIMATE_DAY) -> dt.datetime:
    tz = dt.timezone(dt.timedelta(hours=_MDW_STD_OFFSET_HOURS))
    local = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
    return local.astimezone(dt.UTC)


def _depth_row(
    mb: ModuleType,
    *,
    instrument_id: str,
    hour: int,
    minute: int,
    ask: tuple[float, float] | None,
) -> object:
    return mb.DepthObservation(
        instrument_id=instrument_id,
        ts_event=_lst_to_utc(hour, minute),
        best_ask=None if ask is None else ask[0],
        ask_ladder=None if ask is None else (ask,),
        best_bid=None,
    )


# ---------------------------------------------------------------------------
# Part A -- archive p_hold table: Wilson bound + n_min "n/a" floor
# ---------------------------------------------------------------------------


def test_a_rung_holding_95_of_100_reports_wilson_lower_near_point_nine(
    mb: ModuleType,
) -> None:
    cases = tuple(
        mb.HoldCase(
            city="MDW",
            climate_day=dt.date(2021, 1, 1),
            season="DJF",
            hour=13,
            running_f=50,
            settled_f=50,
            width=mb.WIDTH_INTERIOR,
            m=0,
            held=index < 95,
        )
        for index in range(100)
    )
    table = mb.aggregate_hold_cases(cases)
    cell = table[("MDW", "DJF", 13, mb.WIDTH_INTERIOR, 0)]

    assert cell.n == 100
    assert cell.hold_count == 95
    assert cell.p_hold_lower is not None
    assert cell.p_hold_lower == pytest.approx(0.90, abs=0.03)


def test_a_cell_below_n_min_reports_n_slash_a_never_zero(mb: ModuleType) -> None:
    cases = tuple(
        mb.HoldCase(
            city="SFO",
            climate_day=dt.date(2021, 1, 1),
            season="MAM",
            hour=14,
            running_f=60,
            settled_f=60,
            width=mb.WIDTH_OPEN_UPPER,
            m=None,
            held=True,
        )
        for _index in range(50)
    )
    table = mb.aggregate_hold_cases(cases)
    cell = table[("SFO", "MAM", 14, mb.WIDTH_OPEN_UPPER, None)]

    assert cell.n == 50
    assert cell.p_hold_lower is None  # n < N_MIN=90 -- undefined, not 0.0
    assert mb.N_MIN == 90


def test_a_missing_cell_lookup_is_also_n_slash_a(mb: ModuleType) -> None:
    table: dict[object, object] = {}
    assert table.get(("LAX", "JJA", 12, mb.WIDTH_INTERIOR, 0)) is None


def test_a_proxy_rung_m0_and_m1_and_open_upper_geometry(mb: ModuleType) -> None:
    m0 = mb.proxy_rung(running_f=78, width=mb.WIDTH_INTERIOR, m=0)
    assert m0.lower_f == 78 and m0.upper_f == 79
    assert m0.contains(78) and m0.contains(79) and not m0.contains(77) and not m0.contains(80)

    m1 = mb.proxy_rung(running_f=78, width=mb.WIDTH_INTERIOR, m=1)
    assert m1.lower_f == 77 and m1.upper_f == 78
    assert m1.contains(77) and m1.contains(78) and not m1.contains(79)

    upper = mb.proxy_rung(running_f=78, width=mb.WIDTH_OPEN_UPPER, m=None)
    assert upper.lower_f == 78 and upper.upper_f is None
    assert upper.contains(78) and upper.contains(200) and not upper.contains(77)


def test_a_build_hold_cases_covers_every_archive_hour_and_width(mb: ModuleType) -> None:
    running_by_hour = {hour: 50 for hour in range(24)}
    day = mb.RunningMaxDay(
        city="MDW",
        climate_day=dt.date(2021, 6, 15),
        running_max_f=tuple(running_by_hour[h] for h in range(24)),
        observed_max_f=50,
        observed_max_unrounded_f=50.0,
        hour_of_max=13,
        instant_of_max=_lst_to_utc(13, 0),
        hour_of_rounded_max=13,
        observation_count=24,
        covered_hours=24,
    )
    cases = mb.build_hold_cases(day=day, settled_f=51)
    # 5 hours x 3 proxy cells (interior m=0, interior m=1, open_upper).
    assert len(cases) == 5 * 3
    assert {case.hour for case in cases} == set(mb.ARCHIVE_HOURS)
    assert {(case.width, case.m) for case in cases} == {
        (mb.WIDTH_INTERIOR, 0),
        (mb.WIDTH_INTERIOR, 1),
        (mb.WIDTH_OPEN_UPPER, None),
    }
    # settled_f=51, running=50: m=0 rung [50,51] holds; m=1 rung [49,50] does not.
    m0_case = next(c for c in cases if c.hour == 13 and c.width == mb.WIDTH_INTERIOR and c.m == 0)
    m1_case = next(c for c in cases if c.hour == 13 and c.width == mb.WIDTH_INTERIOR and c.m == 1)
    assert m0_case.held is True
    assert m1_case.held is False


# ---------------------------------------------------------------------------
# Part B -- survivorship: a mid-afternoon rung jump yields two trials, the
# first labelled not-held (SS2)
# ---------------------------------------------------------------------------


def test_b_running_max_jump_mid_afternoon_yields_two_trials_first_not_held(
    mb: ModuleType,
) -> None:
    ladder = mb.parse_ladder(
        [
            "tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte95lt96f.POLYMARKET_US",
        ]
    )
    # R(t) sits at 93 through 13:00, jumps to 95 at 14:00 and stays there.
    series = ((_lst_to_utc(6, 0), 93), (_lst_to_utc(14, 0), 95))
    window_instants = (_lst_to_utc(13, 0), _lst_to_utc(15, 0))
    depth: dict[str, tuple[object, ...]] = {}

    trials = mb.build_current_rung_trials(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        ladder=ladder,
        depth=depth,
        series=series,
        window_instants=window_instants,
        settled_f=95,  # CLI settles inside the SECOND (post-jump) rung.
        lag_minutes=10,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
        archive={},
    )

    assert len(trials) == 2
    first, second = trials
    assert first.t < second.t
    assert first.rung_instrument_id.endswith("gte93lt94f.POLYMARKET_US")
    assert first.held is False  # settled_f=95 not in [93, 94] -- NOT the winner
    assert second.rung_instrument_id.endswith("gte95lt96f.POLYMARKET_US")
    assert second.held is True


# ---------------------------------------------------------------------------
# Part B -- latency: entry ask is read at t+lag, never at t
# ---------------------------------------------------------------------------


def test_b_lagged_entry_selects_a_later_snapshot_not_the_one_at_t(mb: ModuleType) -> None:
    ladder = mb.parse_ladder(["tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US"])
    series = ((_lst_to_utc(6, 0), 93),)
    t = _lst_to_utc(13, 0)
    instrument_id = ladder[0].instrument_id
    depth = {
        instrument_id: (
            _depth_row(mb, instrument_id=instrument_id, hour=13, minute=0, ask=(0.10, 5.0)),
            _depth_row(mb, instrument_id=instrument_id, hour=13, minute=1, ask=(0.15, 5.0)),
            _depth_row(mb, instrument_id=instrument_id, hour=13, minute=11, ask=(0.40, 5.0)),
        )
    }

    trials = mb.build_current_rung_trials(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        ladder=ladder,
        depth=depth,
        series=series,
        window_instants=(t,),
        settled_f=93,
        lag_minutes=10,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
        archive={},
    )

    assert len(trials) == 1
    # lag=10min after 13:00 -> 13:10; the first row at/after that is 13:11, ask=0.40.
    assert trials[0].entry_ask == pytest.approx(0.40)
    assert trials[0].entry_ts == _lst_to_utc(13, 11)


def test_b_find_lagged_entry_returns_none_when_nothing_qualifies(mb: ModuleType) -> None:
    rows = (_depth_row(mb, instrument_id="x", hour=13, minute=0, ask=(0.5, 1.0)),)
    assert mb.find_lagged_entry(rows, not_before=_lst_to_utc(14, 0)) is None


# ---------------------------------------------------------------------------
# Part B -- per-station-day statistic: FIRST executable snapshot, not min ask
# ---------------------------------------------------------------------------


def test_b_first_executable_trial_is_not_the_cheapest_ask(mb: ModuleType) -> None:
    def _trial(*, t: dt.datetime, ask: float | None, size: float | None) -> object:
        return mb.CurrentRungTrial(
            city="MDW",
            climate_day=_CLIMATE_DAY,
            t=t,
            ts_lst=t,
            hour_lst=13,
            running_f=93,
            rung_instrument_id="tc-temp-mdwhigh-2026-08-31-gte93lt94f.POLYMARKET_US",
            width=mb.WIDTH_INTERIOR,
            m=0,
            held=True,
            lag_minutes=10,
            entry_ts=t,
            entry_ask=ask,
            entry_size=size,
            p_hold_lower=0.95,
            edge=None if ask is None else 0.95 - ask,
        )

    # First trial (t=13:00) is executable at ask=0.50; a LATER trial (t=14:00)
    # has a cheaper ask=0.10 -- the statistic must pick the FIRST, not the min.
    trials = (
        _trial(t=_lst_to_utc(13, 0), ask=0.50, size=5.0),
        _trial(t=_lst_to_utc(14, 0), ask=0.10, size=5.0),
    )
    winner = mb.first_executable_trial(trials)
    assert winner is not None
    assert winner.entry_ask == pytest.approx(0.50)


def test_b_first_executable_trial_skips_unpriced_and_undersized_snapshots(
    mb: ModuleType,
) -> None:
    def _trial(*, t: dt.datetime, ask: float | None, size: float | None) -> object:
        return mb.CurrentRungTrial(
            city="MDW",
            climate_day=_CLIMATE_DAY,
            t=t,
            ts_lst=t,
            hour_lst=13,
            running_f=93,
            rung_instrument_id="x",
            width=mb.WIDTH_INTERIOR,
            m=0,
            held=True,
            lag_minutes=10,
            entry_ts=t,
            entry_ask=ask,
            entry_size=size,
            p_hold_lower=None,
            edge=None,
        )

    trials = (
        _trial(t=_lst_to_utc(13, 0), ask=None, size=None),  # no ask at all
        _trial(t=_lst_to_utc(13, 5), ask=0.99, size=5.0),  # outside (0.05, 0.95)
        _trial(t=_lst_to_utc(13, 10), ask=0.50, size=0.5),  # K-depth: size < 1.0
        _trial(t=_lst_to_utc(13, 15), ask=0.50, size=1.0),  # first genuinely executable
    )
    winner = mb.first_executable_trial(trials)
    assert winner is not None
    assert winner.t == _lst_to_utc(13, 15)


# ---------------------------------------------------------------------------
# classify_width -- interior margin and open-tail classification
# ---------------------------------------------------------------------------


def test_classify_width_interior_margins_and_open_tails(mb: ModuleType) -> None:
    ladder = mb.parse_ladder(
        [
            "tc-temp-mdwhigh-2026-08-31-lt89f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte89lt90f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte97f.POLYMARKET_US",
        ]
    )
    interior = mb.rung_containing(ladder, 90)
    width, m = mb.classify_width(interior, 90)
    assert (width, m) == (mb.WIDTH_INTERIOR, 1)  # 90 - 89 = 1

    interior_low = mb.rung_containing(ladder, 89)
    width_low, m_low = mb.classify_width(interior_low, 89)
    assert (width_low, m_low) == (mb.WIDTH_INTERIOR, 0)

    upper = mb.rung_containing(ladder, 100)
    assert mb.classify_width(upper, 100) == (mb.WIDTH_OPEN_UPPER, None)

    lower = mb.rung_containing(ladder, 50)
    assert mb.classify_width(lower, 50) == (mb.WIDTH_OPEN_LOWER, None)


# ---------------------------------------------------------------------------
# evaluate_mb -- the SS1 kill sentence
# ---------------------------------------------------------------------------


def _summary(
    mb: ModuleType,
    *,
    city: str,
    coverage: float,
    trial: object | None,
) -> object:
    return mb.MbStationDaySummary(
        city=city,
        climate_day=_CLIMATE_DAY,
        status="SCORED",
        lag_minutes=10,
        afternoon_coverage_minutes=coverage,
        trials=() if trial is None else (trial,),
        first_executable=trial,
    )


def _positive_edge_trial(mb: ModuleType) -> object:
    return mb.CurrentRungTrial(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        t=_lst_to_utc(13, 0),
        ts_lst=_lst_to_utc(13, 0),
        hour_lst=13,
        running_f=93,
        rung_instrument_id="x",
        width=mb.WIDTH_INTERIOR,
        m=0,
        held=True,
        lag_minutes=10,
        entry_ts=_lst_to_utc(13, 10),
        entry_ask=0.30,
        entry_size=5.0,
        p_hold_lower=0.90,
        edge=0.90 - 0.30 - 0.06 * 0.30 * 0.70,
    )


def test_evaluate_mb_is_underpowered_below_15_afternoon_covered_days(mb: ModuleType) -> None:
    summaries = [
        _summary(mb, city="MDW", coverage=300.0, trial=_positive_edge_trial(mb))
        for _index in range(4)
    ]
    verdict = mb.evaluate_mb(summaries, lag_minutes=10)
    assert verdict.outcome == "UNDERPOWERED"
    assert verdict.n_afternoon == 4


def test_evaluate_mb_is_dead_at_15_plus_days_with_no_positive_edge(mb: ModuleType) -> None:
    dead_trial = mb.CurrentRungTrial(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        t=_lst_to_utc(13, 0),
        ts_lst=_lst_to_utc(13, 0),
        hour_lst=13,
        running_f=93,
        rung_instrument_id="x",
        width=mb.WIDTH_INTERIOR,
        m=0,
        held=True,
        lag_minutes=10,
        entry_ts=_lst_to_utc(13, 10),
        entry_ask=0.90,
        entry_size=5.0,
        p_hold_lower=0.90,
        edge=0.90 - 0.90 - 0.06 * 0.90 * 0.10,  # negative edge
    )
    summaries = [
        _summary(mb, city=f"S{i}", coverage=300.0, trial=dead_trial) for i in range(16)
    ]
    verdict = mb.evaluate_mb(summaries, lag_minutes=10)
    assert verdict.outcome == "MB_DEAD"
    assert verdict.n_afternoon == 16


def test_evaluate_mb_is_alive_at_15_plus_days_with_one_positive_edge(mb: ModuleType) -> None:
    summaries = [
        _summary(mb, city=f"S{i}", coverage=300.0, trial=_positive_edge_trial(mb))
        for i in range(15)
    ]
    verdict = mb.evaluate_mb(summaries, lag_minutes=10)
    assert verdict.outcome == "ALIVE"
    assert verdict.any_edge_positive is True
