"""Unit tests for `scripts/analysis/cli_basis_hourly_profile_study.py`.

Resolves the ⚠ challenge on `cli_basis_setup_win_rate_2026-09-02T060103Z.md`:
that study's pooled ~53% `P(win | setup)` pools every local-standard hour
0..23, including instants long before a day's diurnal peak where the strike
is crossed by ordinary warming, not by CLI-vs-ASOS basis. This module adds
the per-hour breakdown of that same statistic PLUS `P(R_h == R_23)` (how
often the running max at hour `h` already equals its end-of-day value), the
diagnostic the coordinator's banner calls for, and the admissibility-rule
recompute that follows from it.

Covers only what is GENUINELY NEW here:

* `aggregate_setup_cases_by_hour` -- pooling `SetupCase`s (margins 1 and 2
  together) into one `(n, k)` count per `(station, hour)`, as opposed to
  `cli_basis_setup_win_rate_study.summarize_station`'s all-hours pool.
* `setup_hour_cell` -- the Wilson-bounded per-hour cell built from that count.
* `convergence_counts_by_hour` -- `P(R_h == R_23)` per hour, built directly
  from `RunningMaxDay.running_max_f`.
* `is_admissible_hour` -- the registered, PURE, clock-hour-only admissibility
  predicate (the lookahead guard: it is structurally incapable of reading a
  day's own realized peak because its signature carries only an `int` hour).
* `filter_cases_by_admissible_hours` -- applies that predicate to a tuple of
  `SetupCase` before handing off to `summarize_station`/`pool_stations`/
  `pooled_verdict`, which are reused verbatim, not re-implemented.

`build_setup_cases`, `summarize_station`, `pool_stations`, `pooled_verdict`,
`SetupCase`, `DENSE_STATIONS`, `QUALIFYING_MARGINS`, `PRIMARY_BAR` (from
`cli_basis_setup_win_rate_study`), `hour_coverage` / `is_non_sentinel_final`
(from `cli_basis_boundary_study`), and `wilson_interval` (from
`k1_cheap_open_settlement`) are all reused verbatim via import and are not
re-tested here -- each already carries its own coverage upstream.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = REPO_ROOT / "scripts" / "analysis"


def _load_module(name: str) -> ModuleType:
    import importlib.util

    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return _load_module("cli_basis_hourly_profile_study")


@pytest.fixture(scope="module")
def setup_study(study: ModuleType) -> ModuleType:
    import cli_basis_setup_win_rate_study as setup_mod

    return setup_mod


@pytest.fixture(scope="module")
def pmr(study: ModuleType) -> ModuleType:
    import pmr_climatology_study as pmr_mod

    return pmr_mod


def _cli_final(pmr: ModuleType, *, city: str, climate_day: dt.date, tmax_f: int | None) -> object:
    return pmr.CliRecord(
        city=city,
        climate_day=climate_day,
        issuance="FINAL",
        tmax_f=tmax_f,
        tmax_sentinel="NONE",
        max_time=None,
        is_correction_bbb=False,
        issued_at_utc=None,
        source="test-fixture",
    )


def _running_max_day(
    pmr: ModuleType, *, city: str, climate_day: dt.date, running_max_f: tuple[int | None, ...]
) -> object:
    return pmr.RunningMaxDay(
        city=city,
        climate_day=climate_day,
        running_max_f=running_max_f,
        observed_max_f=max(v for v in running_max_f if v is not None),
        observed_max_unrounded_f=0.0,
        hour_of_max=0,
        instant_of_max=dt.datetime(2021, 1, 1, tzinfo=dt.UTC),
        hour_of_rounded_max=0,
        observation_count=1,
        covered_hours=1,
    )


def _series_with(hour_values: dict[int, int]) -> tuple[int | None, ...]:
    series: list[int | None] = [None] * 24
    for hour, value in hour_values.items():
        series[hour] = value
    return tuple(series)


# ---------------------------------------------------------------------------
# aggregate_setup_cases_by_hour
# ---------------------------------------------------------------------------


def test_aggregate_by_hour_pools_both_margins_at_the_same_hour(
    study: ModuleType, setup_study: ModuleType
) -> None:
    day = dt.date(2021, 1, 1)
    cases = (
        setup_study.SetupCase("LAX", day, 9, 1, 70, 71, 71, True),
        setup_study.SetupCase("LAX", day, 9, 2, 70, 72, 71, False),
        setup_study.SetupCase("LAX", day, 20, 1, 78, 79, 79, True),
    )

    counts = study.aggregate_setup_cases_by_hour(cases)

    assert counts[("LAX", 9)] == (2, 1)
    assert counts[("LAX", 20)] == (1, 1)


def test_aggregate_by_hour_separates_stations(study: ModuleType, setup_study: ModuleType) -> None:
    day = dt.date(2021, 1, 1)
    cases = (
        setup_study.SetupCase("LAX", day, 9, 1, 70, 71, 71, True),
        setup_study.SetupCase("SFO", day, 9, 1, 60, 61, 61, False),
    )
    counts = study.aggregate_setup_cases_by_hour(cases)
    assert counts[("LAX", 9)] == (1, 1)
    assert counts[("SFO", 9)] == (1, 0)


def test_aggregate_by_hour_empty_for_no_cases(study: ModuleType) -> None:
    assert study.aggregate_setup_cases_by_hour(()) == {}


# ---------------------------------------------------------------------------
# setup_hour_cell
# ---------------------------------------------------------------------------


def test_setup_hour_cell_reports_wilson_bounds_via_shared_helper(study: ModuleType) -> None:
    cell = study.setup_hour_cell(station="LAX", hour=9, n=1000, k=530)
    assert cell.station == "LAX"
    assert cell.hour == 9
    assert cell.n == 1000
    assert cell.k == 530
    assert 0.0 < cell.wilson_lower < cell.rate < cell.wilson_upper < 1.0


def test_setup_hour_cell_empty_sample_reports_full_width_interval(study: ModuleType) -> None:
    cell = study.setup_hour_cell(station="LAX", hour=9, n=0, k=0)
    assert cell.wilson_lower == 0.0
    assert cell.wilson_upper == 1.0


# ---------------------------------------------------------------------------
# build_hour_cells -- the (station, hour) lookup, regression-tested directly
# ---------------------------------------------------------------------------


def test_build_hour_cells_reads_the_station_and_hour_keyed_count(study: ModuleType) -> None:
    """Regression test for a keying bug caught during development: a lookup
    that forgets the station half of the `(station, hour)` key silently reads
    every hour as `(0, 0)` instead of raising, so this is pinned directly.
    """
    counts = {("LAX", 9): (100, 40), ("SFO", 9): (50, 5)}
    cells = study.build_hour_cells(station="LAX", counts=counts)
    assert len(cells) == 24
    by_hour = {cell.hour: cell for cell in cells}
    assert by_hour[9].n == 100
    assert by_hour[9].k == 40
    assert by_hour[8].n == 0  # untouched hour reads as empty, not cross-contaminated


def test_build_hour_cells_never_reads_another_stations_count(study: ModuleType) -> None:
    counts = {("SFO", 9): (50, 5)}
    cells = study.build_hour_cells(station="LAX", counts=counts)
    assert cells[9].n == 0
    assert cells[9].k == 0


# ---------------------------------------------------------------------------
# convergence_counts_by_hour -- P(R_h == R_23)
# ---------------------------------------------------------------------------


def test_convergence_counts_hit_when_running_max_already_equals_eod_value(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr, city="LAX", climate_day=day, running_max_f=_series_with({9: 80, 23: 80})
        )
    ]
    coverage = {day: frozenset({9, 23})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=81)}

    counts = study.convergence_counts_by_hour(
        running_max_days=running_days, covered_hours_by_day=coverage, cli_finals=finals
    )
    assert counts[9] == (1, 1)


def test_convergence_counts_miss_when_running_max_still_rises_after_hour(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr, city="LAX", climate_day=day, running_max_f=_series_with({9: 75, 23: 80})
        )
    ]
    coverage = {day: frozenset({9, 23})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=81)}

    counts = study.convergence_counts_by_hour(
        running_max_days=running_days, covered_hours_by_day=coverage, cli_finals=finals
    )
    assert counts[9] == (1, 0)


def test_convergence_counts_excludes_uncovered_hour(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr, city="LAX", climate_day=day, running_max_f=_series_with({9: 80, 23: 80})
        )
    ]
    coverage = {day: frozenset({23})}  # hour 9 not covered
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=81)}

    counts = study.convergence_counts_by_hour(
        running_max_days=running_days, covered_hours_by_day=coverage, cli_finals=finals
    )
    assert counts.get(9, (0, 0)) == (0, 0)


def test_convergence_counts_excludes_missing_final(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr, city="LAX", climate_day=day, running_max_f=_series_with({9: 80, 23: 80})
        )
    ]
    coverage = {day: frozenset({9, 23})}

    counts = study.convergence_counts_by_hour(
        running_max_days=running_days, covered_hours_by_day=coverage, cli_finals={}
    )
    assert counts == {}


def test_convergence_counts_excludes_day_with_no_eod_running_value(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="LAX", climate_day=day, running_max_f=_series_with({9: 80}))
    ]
    coverage = {day: frozenset({9})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=81)}

    counts = study.convergence_counts_by_hour(
        running_max_days=running_days, covered_hours_by_day=coverage, cli_finals=finals
    )
    assert counts.get(9, (0, 0)) == (0, 0)


# ---------------------------------------------------------------------------
# is_admissible_hour -- the registered, lookahead-proof admissibility rule
# ---------------------------------------------------------------------------


def test_is_admissible_hour_matches_the_boundary_studys_own_window_start(
    study: ModuleType,
) -> None:
    import cli_basis_boundary_study as boundary

    assert study.ADMISSIBLE_HOUR_FLOOR == boundary.STUDY_HOURS[0]


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(0, False), (9, False), (16, False), (17, True), (20, True), (23, True)],
)
def test_is_admissible_hour_is_a_fixed_clock_hour_cutoff(
    study: ModuleType, hour: int, expected: bool
) -> None:
    assert study.is_admissible_hour(hour) is expected


def test_is_admissible_hour_signature_takes_only_the_clock_hour(study: ModuleType) -> None:
    """Lookahead guard: the predicate is a pure function of the CLOCK HOUR
    alone. It cannot be handed a realized running-max value or a day's own
    peak, because its signature has no parameter to carry one -- the
    admissibility rule is therefore structurally computable AT THE INSTANT,
    never from information that only exists once the day is over.
    """
    import inspect

    parameters = inspect.signature(study.is_admissible_hour).parameters
    assert list(parameters) == ["hour"]
    assert parameters["hour"].annotation in (int, "int")


# ---------------------------------------------------------------------------
# filter_cases_by_admissible_hours -- applies the rule, reuses the rest
# ---------------------------------------------------------------------------


def test_filter_cases_by_admissible_hours_drops_pre_admissible_instants(
    study: ModuleType, setup_study: ModuleType
) -> None:
    day = dt.date(2021, 1, 1)
    cases = (
        setup_study.SetupCase("LAX", day, 9, 1, 70, 71, 71, True),
        setup_study.SetupCase("LAX", day, 20, 1, 78, 79, 79, True),
    )
    filtered = study.filter_cases_by_admissible_hours(cases)
    assert filtered == (cases[1],)


def test_filter_cases_by_admissible_hours_empty_input(study: ModuleType) -> None:
    assert study.filter_cases_by_admissible_hours(()) == ()


def test_filter_then_summarize_matches_hand_pooled_hour20_only_count(
    study: ModuleType, setup_study: ModuleType
) -> None:
    day = dt.date(2021, 1, 1)
    cases = (
        setup_study.SetupCase("LAX", day, 9, 1, 70, 71, 71, True),  # dropped: hour 9
        setup_study.SetupCase("LAX", day, 20, 1, 78, 79, 79, True),  # kept
        setup_study.SetupCase("LAX", day, 20, 2, 78, 80, 79, False),  # kept
    )
    filtered = study.filter_cases_by_admissible_hours(cases)
    result = setup_study.summarize_station(filtered)
    assert result.n == 2
    assert result.k == 1
