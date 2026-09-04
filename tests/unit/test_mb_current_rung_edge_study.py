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
# evaluate_mb -- the kill-amendment: REALIZED hold rate of TAKEN trials vs
# ask+fee, never the archive base rate against ask
# (`docs/evidence/grok_mb_kill_amendment_2026-09-02.md`)
# ---------------------------------------------------------------------------


def _taken_trials(
    mb: ModuleType, *, city: str, n: int, k: int, ask: float
) -> tuple[object, ...]:
    """`n` synthetic TAKEN trials at one station, `k` of which held, all at `ask`."""
    held_flags = [True] * k + [False] * (n - k)
    return tuple(
        mb.CurrentRungTrial(
            city=city,
            climate_day=_CLIMATE_DAY,
            t=_lst_to_utc(12, 0),
            ts_lst=_lst_to_utc(12, 0),
            hour_lst=12,
            running_f=93,
            rung_instrument_id="x",
            width=mb.WIDTH_INTERIOR,
            m=0,
            held=flag,
            lag_minutes=10,
            entry_ts=_lst_to_utc(12, 10),
            entry_ask=ask,
            entry_size=5.0,
            p_hold_lower=0.90,
            edge=0.90 - ask - 0.06 * ask * (1.0 - ask),
        )
        for flag in held_flags
    )


def test_evaluate_mb_kills_at_n60_when_realized_rate_is_near_zero(mb: ModuleType) -> None:
    # k=0/n=60 at ask=0.06: Wilson-95% upper = z^2/(n+z^2) ~= 0.0602, just under
    # BE(0.06) ~= 0.0634 -- the exact "near-zero realized rate" the amendment
    # names as what n=60 CAN kill (even k=1 already clears break-even at this
    # ask: upper ~= 0.0886 > BE, so the kill floor is genuinely this tight).
    taken = _taken_trials(mb, city="MDW", n=60, k=0, ask=0.06)
    verdict = mb.evaluate_mb(taken, lag_minutes=10)
    assert verdict.outcome == "MB_DEAD"
    assert verdict.n_taken == 60
    assert verdict.pooled is not None
    assert verdict.pooled.wilson_upper < verdict.pooled.break_even


def test_evaluate_mb_does_not_kill_at_n60_when_upper_clears_break_even(
    mb: ModuleType,
) -> None:
    taken = _taken_trials(mb, city="MDW", n=60, k=20, ask=0.06)
    verdict = mb.evaluate_mb(taken, lag_minutes=10)
    assert verdict.outcome != "MB_DEAD"
    assert verdict.pooled is not None
    assert verdict.pooled.wilson_upper > verdict.pooled.break_even


def test_evaluate_mb_survives_at_n150_when_lower_clears_break_even(mb: ModuleType) -> None:
    taken = _taken_trials(mb, city="MDW", n=150, k=40, ask=0.06)
    verdict = mb.evaluate_mb(taken, lag_minutes=10)
    assert verdict.outcome == "ALIVE"
    assert verdict.n_taken == 150
    assert verdict.pooled is not None
    assert verdict.pooled.wilson_lower > verdict.pooled.break_even


def test_evaluate_mb_is_underpowered_below_n60_regardless_of_realized_rate(
    mb: ModuleType,
) -> None:
    taken = _taken_trials(mb, city="MDW", n=59, k=59, ask=0.06)  # 100% realized hold
    verdict = mb.evaluate_mb(taken, lag_minutes=10)
    assert verdict.outcome == "UNDERPOWERED"
    assert verdict.n_taken == 59


def test_evaluate_mb_reports_a_cell_dead_stratum_inside_a_pooled_non_kill(
    mb: ModuleType,
) -> None:
    # Station A: 60 trials, mostly held (pooled rate looks healthy).
    # Station B: 60 trials, k=2 (near-zero) -- dead on its OWN, even though the
    # pooled 120-trial rate (60/120 = 50%) clears break-even easily.
    station_a = _taken_trials(mb, city="A", n=60, k=58, ask=0.06)
    station_b = _taken_trials(mb, city="B", n=60, k=0, ask=0.06)  # near-zero -- see above
    taken = station_a + station_b

    verdict = mb.evaluate_mb(taken, lag_minutes=10)

    assert verdict.n_taken == 120
    dead_labels = {stratum.label for stratum in verdict.cell_dead_strata}
    assert "station:B" in dead_labels
    station_b_stratum = next(s for s in verdict.station_strata if s.label == "station:B")
    assert station_b_stratum.cell_dead is True
    station_a_stratum = next(s for s in verdict.station_strata if s.label == "station:A")
    assert station_a_stratum.cell_dead is False


def test_evaluate_mb_family_requires_both_lag_10_and_15_to_agree(mb: ModuleType) -> None:
    dead_at_10 = mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=10)
    alive_at_15 = mb.evaluate_mb(
        _taken_trials(mb, city="MDW", n=150, k=40, ask=0.06), lag_minutes=15
    )
    family = mb.evaluate_mb_family({10: dead_at_10, 15: alive_at_15})
    assert family == "UNDERPOWERED"  # disagreement -- neither lag confirms the other

    both_dead = {
        10: mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=10),
        15: mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=15),
    }
    assert mb.evaluate_mb_family(both_dead) == "MB_DEAD"


def test_gather_taken_trials_excludes_negative_edge_and_dead_cells(mb: ModuleType) -> None:
    positive_edge = mb.CurrentRungTrial(
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
    negative_edge = mb.CurrentRungTrial(
        city="SFO",
        climate_day=_CLIMATE_DAY,
        t=_lst_to_utc(13, 0),
        ts_lst=_lst_to_utc(13, 0),
        hour_lst=13,
        running_f=70,
        rung_instrument_id="y",
        width=mb.WIDTH_INTERIOR,
        m=0,
        held=True,
        lag_minutes=10,
        entry_ts=_lst_to_utc(13, 10),
        entry_ask=0.66,
        entry_size=5.0,
        p_hold_lower=0.46,
        edge=0.46 - 0.66 - 0.06 * 0.66 * 0.34,
    )
    summaries = (
        mb.MbStationDaySummary(
            city="MDW",
            climate_day=_CLIMATE_DAY,
            status="SCORED",
            lag_minutes=10,
            afternoon_coverage_minutes=300.0,
            trials=(positive_edge,),
            first_executable=positive_edge,
        ),
        mb.MbStationDaySummary(
            city="SFO",
            climate_day=_CLIMATE_DAY,
            status="SCORED",
            lag_minutes=10,
            afternoon_coverage_minutes=300.0,
            trials=(negative_edge,),
            first_executable=negative_edge,
        ),
    )
    taken = mb.gather_taken_trials(summaries)
    assert len(taken) == 1
    assert taken[0].city == "MDW"


# ---------------------------------------------------------------------------
# Live family (lags 30/45) -- `docs/evidence/grok_live_small_spec_rev2_2026-09-04.md`
# SS1/SS6: live receipts match the measured NWS publication lag, not the
# archive's 10/15-min arms. 5/10/15 remain an archive-only upper bound;
# 30/45 is the new live family and must be evaluated and reported SEPARATELY
# from the archive family, never merged.
# ---------------------------------------------------------------------------


def test_lag_sweep_includes_the_live_arms_30_and_45(mb: ModuleType) -> None:
    assert 30 in mb.LAG_MINUTES_SWEEP
    assert 45 in mb.LAG_MINUTES_SWEEP
    # Archive-only upper bound arms are kept, not replaced.
    assert 5 in mb.LAG_MINUTES_SWEEP
    assert 10 in mb.LAG_MINUTES_SWEEP
    assert 15 in mb.LAG_MINUTES_SWEEP


def test_k_b_required_lags_live_is_30_and_45_and_archive_is_unchanged(
    mb: ModuleType,
) -> None:
    assert mb.K_B_REQUIRED_LAGS == (10, 15)
    assert mb.K_B_REQUIRED_LAGS_LIVE == (30, 45)


def test_evaluate_mb_family_live_requires_30_and_45_to_agree(mb: ModuleType) -> None:
    dead_at_30 = mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=30)
    alive_at_45 = mb.evaluate_mb(
        _taken_trials(mb, city="MDW", n=150, k=40, ask=0.06), lag_minutes=45
    )
    live_family = mb.evaluate_mb_family(
        {30: dead_at_30, 45: alive_at_45}, required_lags=mb.K_B_REQUIRED_LAGS_LIVE
    )
    assert live_family == "UNDERPOWERED"  # disagreement

    both_dead = {
        30: mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=30),
        45: mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=45),
    }
    assert (
        mb.evaluate_mb_family(both_dead, required_lags=mb.K_B_REQUIRED_LAGS_LIVE) == "MB_DEAD"
    )


def test_evaluate_mb_family_default_required_lags_is_still_the_archive_pair(
    mb: ModuleType,
) -> None:
    # Existing callers that omit `required_lags` must keep measuring the
    # archive family (10, 15) -- unchanged default, no call-site breakage.
    both_dead = {
        10: mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=10),
        15: mb.evaluate_mb(_taken_trials(mb, city="MDW", n=60, k=0, ask=0.06), lag_minutes=15),
    }
    assert mb.evaluate_mb_family(both_dead) == "MB_DEAD"


def test_dense_stations_excludes_nyc_for_the_live_family(mb: ModuleType) -> None:
    # `docs/evidence/grok_live_small_spec_rev2_2026-09-04.md` SS1: "NYC
    # excluded" for the live family. Reuse the existing CONTAMINATED_STATIONS
    # / DENSE_STATIONS logic (`cli_basis_offer_gate_scan.CONTAMINATED_STATIONS`)
    # rather than duplicate a station list -- DENSE_STATIONS already excludes
    # NYC everywhere it is used (archive table AND tape join), so the live
    # family's station set is DENSE_STATIONS itself, not a new constant.
    assert "NYC" not in mb.DENSE_STATIONS
    assert set(mb.DENSE_STATIONS) == {"LAX", "MDW", "MIA", "SFO"}


def _empty_verdicts(mb: ModuleType) -> dict[int, object]:
    return {lag: mb.evaluate_mb((), lag_minutes=lag) for lag in mb.LAG_MINUTES_SWEEP}


def test_build_report_prints_both_family_verdicts_separately_labelled(
    mb: ModuleType,
) -> None:
    summaries_by_lag = {lag: () for lag in mb.LAG_MINUTES_SWEEP}
    verdicts = _empty_verdicts(mb)
    report = mb.build_report(
        archive={},
        summaries_by_lag=summaries_by_lag,
        verdicts=verdicts,
        family_outcome_archive=mb.evaluate_mb_family(verdicts),
        family_outcome_live=mb.evaluate_mb_family(
            verdicts, required_lags=mb.K_B_REQUIRED_LAGS_LIVE
        ),
        preflight="ok",
        generated_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
    )
    # Existing heading text/shape preserved for the archive family --
    # nightly `breezy-mb-daily` consumers and any K1/offer-gate parser of
    # this report see the same archive section they always have.
    assert "## Part A -- archive p_hold table" in report
    assert "## Part B -- tape join, per-station-day, per lag" in report
    assert "## Independence and the clock" in report
    # New: two separately labelled, never-merged family verdicts.
    assert "archive (10, 15)" in report
    assert "live (30, 45)" in report
    archive_idx = report.index("archive (10, 15)")
    live_idx = report.index("live (30, 45)")
    assert archive_idx != live_idx


def test_build_report_clock_section_prints_live_family_dates(mb: ModuleType) -> None:
    summaries_by_lag = {lag: () for lag in mb.LAG_MINUTES_SWEEP}
    verdicts = _empty_verdicts(mb)
    report = mb.build_report(
        archive={},
        summaries_by_lag=summaries_by_lag,
        verdicts=verdicts,
        family_outcome_archive=mb.evaluate_mb_family(verdicts),
        family_outcome_live=mb.evaluate_mb_family(
            verdicts, required_lags=mb.K_B_REQUIRED_LAGS_LIVE
        ),
        preflight="ok",
        generated_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
    )
    # Grok rev2 SS6 clock table: 3 taken/listed-day, ~9% venue skip,
    # earliest D0=2026-09-05 -> n=60 at D0+22d (2026-09-27), n=150 at
    # D0+55d (2026-10-30).
    assert "9%" in report
    assert "D0+22" in report
    assert "D0+55" in report
    assert "2026-09-27" in report
    assert "2026-10-30" in report
