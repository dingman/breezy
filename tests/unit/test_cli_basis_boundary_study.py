"""Unit tests for `scripts/analysis/cli_basis_boundary_study.py`.

Covers the logic that is GENUINELY NEW in that module (the running-max fold,
archive loaders, and Wilson formula are reused from
`pmr_climatology_study.py` / `settlement_alignment_study.py`, which already
carry their own test coverage upstream on `feat/data-capture-and-risk`):

* per-hour ASOS coverage, as distinct from the running max's carried-forward
  value across empty hours;
* the boundary/threshold construction and the station-day/hour join against
  CLI finals, including exclusion of sentinel/missing/preliminary finals;
* the Wilson lower bound (primary + Bonferroni-adjusted) and the
  pre-registered PASS/FAIL/UNDERPOWERED verdict rule;
* local-standard-hour bucketing across a fixed UTC offset, including the
  DST trap: the offset must NOT track the wall clock across a DST
  transition.

No network access; every fixture is synthetic or built from small in-memory
rows through the real (reused) parsing/folding functions.
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

_NYC_STD_OFFSET_HOURS = -5.0
_LAX_STD_OFFSET_HOURS = -8.0


def _load_module(name: str) -> ModuleType:
    """Load a `scripts/analysis/<name>.py` module by file path.

    Mirrors the existing repo convention (see
    `tests/unit/test_pmr_climatology_study.py` on `feat/data-capture-and-risk`)
    for loading a bare-import-style analysis script without installing
    `scripts/analysis` as a package.
    """
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
    return _load_module("cli_basis_boundary_study")


@pytest.fixture(scope="module")
def pmr(study: ModuleType) -> ModuleType:
    # `cli_basis_boundary_study` imports `pmr_climatology_study` by its own
    # bare top-level name, so it is already registered in `sys.modules` once
    # `study` has been loaded.
    return sys.modules["pmr_climatology_study"]


def _metar_row(*, station: str, valid: str, t_group: str) -> dict[str, str]:
    return {
        "station": station,
        "valid": valid,
        "metar": f"K{station} 010000Z AUTO 25009KT 10SM CLR 15/07 A3015 RMK AO2 {t_group}",
    }


def _f_to_t_group(temp_c_tenths: int) -> str:
    sign = "1" if temp_c_tenths < 0 else "0"
    return f"T{sign}{abs(temp_c_tenths):03d}{sign}{abs(temp_c_tenths):03d}"


def _cli_final(
    *,
    city: str,
    climate_day: dt.date,
    tmax_f: int | None,
    tmax_sentinel: str = "NONE",
    issuance: str = "FINAL",
) -> object:
    """Build a `pmr_climatology_study.CliRecord` with the fields this study reads."""
    import pmr_climatology_study as pmr_mod

    return pmr_mod.CliRecord(
        city=city,
        climate_day=climate_day,
        issuance=issuance,
        tmax_f=tmax_f,
        tmax_sentinel=tmax_sentinel,
        max_time=None,
        is_correction_bbb=False,
        issued_at_utc=None,
        source="test-fixture",
    )


# ---------------------------------------------------------------------------
# Local-standard-hour bucketing / DST trap
# ---------------------------------------------------------------------------


def test_local_standard_hour_uses_fixed_offset_not_dst_wall_clock(study: ModuleType) -> None:
    """NYC's fixed standard offset is -5h year-round, even in summer.

    A DST-aware ("wall clock") mapping would read a June UTC instant as
    Eastern DAYLIGHT time (UTC-4), one hour later than this. If this ever
    starts matching wall-clock EDT instead of standard EST, the climate-day
    boundary silently shifts by an hour every summer -- exactly the trap the
    brief names.
    """
    winter_instant = dt.datetime(2021, 1, 15, 21, 0, tzinfo=dt.UTC)  # 16:00 EST
    summer_instant = dt.datetime(2021, 6, 15, 21, 0, tzinfo=dt.UTC)  # would be 17:00 EDT

    winter_hour = study.local_standard_hour(winter_instant, _NYC_STD_OFFSET_HOURS)
    summer_hour = study.local_standard_hour(summer_instant, _NYC_STD_OFFSET_HOURS)

    assert winter_hour == 16
    assert summer_hour == 16, "DST must not shift the fixed-standard-time hour bucket"


def test_local_standard_hour_west_coast_negative_wraparound(study: ModuleType) -> None:
    # LAX offset -8h: 03:00Z -> 19:00 the PREVIOUS local-standard day.
    instant = dt.datetime(2021, 3, 2, 3, 0, tzinfo=dt.UTC)
    hour = study.local_standard_hour(instant, _LAX_STD_OFFSET_HOURS)
    assert hour == 19


# ---------------------------------------------------------------------------
# hour_coverage
# ---------------------------------------------------------------------------


def test_hour_coverage_marks_only_hours_with_a_real_observation(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 6, 15)
    rows = [
        _metar_row(
            station="NYC", valid="2021-06-15 22:00", t_group=_f_to_t_group(150)
        ),  # local hour 17
        _metar_row(
            station="NYC", valid="2021-06-16 00:00", t_group=_f_to_t_group(140)
        ),  # local hour 19
    ]
    temperatures, drops = pmr.metar_temperatures(
        city="NYC", rows=rows, std_utc_offset_hours=_NYC_STD_OFFSET_HOURS
    )
    assert not drops

    coverage = study.hour_coverage(temperatures, std_utc_offset_hours=_NYC_STD_OFFSET_HOURS)

    assert coverage[day] == frozenset({17, 19})
    assert 18 not in coverage[day], "hour 18 had no observation and must not read as covered"


def test_hour_coverage_empty_for_no_rows(study: ModuleType) -> None:
    assert study.hour_coverage([], std_utc_offset_hours=_NYC_STD_OFFSET_HOURS) == {}


# ---------------------------------------------------------------------------
# is_non_sentinel_final
# ---------------------------------------------------------------------------


def test_is_non_sentinel_final_true_for_real_final(study: ModuleType) -> None:
    record = _cli_final(city="NYC", climate_day=dt.date(2021, 6, 15), tmax_f=88)
    assert study.is_non_sentinel_final(record) is True


def test_is_non_sentinel_final_false_for_none(study: ModuleType) -> None:
    assert study.is_non_sentinel_final(None) is False


def test_is_non_sentinel_final_false_for_sentinel_tmax(study: ModuleType) -> None:
    record = _cli_final(
        city="NYC", climate_day=dt.date(2021, 6, 15), tmax_f=None, tmax_sentinel="M"
    )
    assert study.is_non_sentinel_final(record) is False


def test_is_non_sentinel_final_false_for_preliminary(study: ModuleType) -> None:
    record = _cli_final(
        city="NYC", climate_day=dt.date(2021, 6, 15), tmax_f=88, issuance="PRELIMINARY"
    )
    assert study.is_non_sentinel_final(record) is False


# ---------------------------------------------------------------------------
# build_boundary_cases -- the ASOS<->CLI join
# ---------------------------------------------------------------------------


def _running_max_day(pmr: ModuleType, *, city: str, climate_day: dt.date, running_max_f: tuple):
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


def _series_with(hour_values: dict) -> tuple:
    series = [None] * 24
    for hour, value in hour_values.items():
        series[hour] = value
    return tuple(series)


def test_build_boundary_cases_hits_when_final_meets_threshold(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr,
            city="NYC",
            climate_day=day,
            running_max_f=_series_with({17: 88, 18: 88}),
        )
    ]
    coverage = {day: frozenset({17, 18})}
    finals = {day: _cli_final(city="NYC", climate_day=day, tmax_f=89)}

    cases = study.build_boundary_cases(
        station="NYC",
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
        hours=(17, 18),
    )

    assert len(cases) == 2
    for case in cases:
        assert case.threshold_f == 89
        assert case.hit is True


def test_build_boundary_cases_miss_when_final_below_threshold(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="NYC", climate_day=day, running_max_f=_series_with({17: 88}))
    ]
    coverage = {day: frozenset({17})}
    finals = {day: _cli_final(city="NYC", climate_day=day, tmax_f=88)}  # did NOT clear 89

    cases = study.build_boundary_cases(
        station="NYC",
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
        hours=(17,),
    )

    assert len(cases) == 1
    assert cases[0].hit is False


def test_build_boundary_cases_excludes_uncovered_hour(study: ModuleType, pmr: ModuleType) -> None:
    """An hour with a carried-forward running value but NO real observation
    must be excluded, even though `running_max_f[hour]` is not `None`."""
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr, city="NYC", climate_day=day, running_max_f=_series_with({17: 88, 18: 88})
        )
    ]
    coverage = {day: frozenset({17})}  # hour 18 carried forward, no real observation
    finals = {day: _cli_final(city="NYC", climate_day=day, tmax_f=90)}

    cases = study.build_boundary_cases(
        station="NYC",
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
        hours=(17, 18),
    )

    assert {case.hour for case in cases} == {17}


def test_build_boundary_cases_excludes_missing_final(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="NYC", climate_day=day, running_max_f=_series_with({17: 88}))
    ]
    coverage = {day: frozenset({17})}

    cases = study.build_boundary_cases(
        station="NYC",
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals={},  # no final at all
        hours=(17,),
    )

    assert cases == ()


def test_build_boundary_cases_excludes_sentinel_final(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="NYC", climate_day=day, running_max_f=_series_with({17: 88}))
    ]
    coverage = {day: frozenset({17})}
    finals = {
        day: _cli_final(city="NYC", climate_day=day, tmax_f=None, tmax_sentinel="M"),
    }

    cases = study.build_boundary_cases(
        station="NYC",
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
        hours=(17,),
    )

    assert cases == ()


def test_build_boundary_cases_ignores_hours_outside_the_evaluated_range(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr, city="NYC", climate_day=day, running_max_f=_series_with({16: 88, 17: 88})
        )
    ]
    coverage = {day: frozenset({16, 17})}
    finals = {day: _cli_final(city="NYC", climate_day=day, tmax_f=90)}

    cases = study.build_boundary_cases(
        station="NYC",
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
        # default hours = STUDY_HOURS = 17..23, so hour 16 must never appear
    )

    assert {case.hour for case in cases} == {17}


# ---------------------------------------------------------------------------
# aggregate_cells
# ---------------------------------------------------------------------------


def test_aggregate_cells_counts_n_and_successes_per_station_hour(study: ModuleType) -> None:
    day = dt.date(2021, 1, 1)
    cases = (
        study.BoundaryCase("NYC", day, 17, 88, 89, 89, True),
        study.BoundaryCase("NYC", day, 17, 88, 89, 88, False),
        study.BoundaryCase("NYC", day, 18, 90, 91, 91, True),
        study.BoundaryCase("LAX", day, 17, 70, 71, 71, True),
    )

    counts = study.aggregate_cells(cases)

    assert counts[("NYC", 17)] == (2, 1)
    assert counts[("NYC", 18)] == (1, 1)
    assert counts[("LAX", 17)] == (1, 1)


def test_aggregate_cells_empty_for_no_cases(study: ModuleType) -> None:
    assert study.aggregate_cells(()) == {}


# ---------------------------------------------------------------------------
# Wilson bounds + verdict rule
# ---------------------------------------------------------------------------


def test_wilson_lower_bound_matches_known_value(study: ModuleType) -> None:
    # Wilson score interval, 8/10 successes, z=1.96 -- textbook value.
    from settlement_alignment_study import wilson_lower_bound

    lower = wilson_lower_bound(8, 10, z=1.959963984540054)
    assert lower == pytest.approx(0.4902, abs=1e-3)


def test_bonferroni_z_is_wider_than_primary_z(study: ModuleType) -> None:
    assert study.BONFERRONI_Z > 1.959963984540054


def test_cell_verdict_underpowered_below_min_n(study: ModuleType) -> None:
    result = study.cell_verdict(station="NYC", hour=17, n=99, successes=90)
    assert result.admissible is False
    assert result.verdict == "UNDERPOWERED"


def test_cell_verdict_pass_when_wilson_lower_clears_bar(study: ModuleType) -> None:
    # A high hit rate at n=100 comfortably clears 0.06285.
    result = study.cell_verdict(station="NYC", hour=17, n=100, successes=40)
    assert result.admissible is True
    assert result.wilson_lower >= study.PRIMARY_BAR
    assert result.verdict == "PASS"


def test_cell_verdict_fail_when_wilson_lower_below_bar(study: ModuleType) -> None:
    result = study.cell_verdict(station="NYC", hour=17, n=100, successes=2)
    assert result.admissible is True
    assert result.wilson_lower < study.PRIMARY_BAR
    assert result.verdict == "FAIL"


def test_cell_verdict_bonferroni_can_fail_when_primary_passes(study: ModuleType) -> None:
    # Choose a rate right at the edge of the primary bar with a small n, so
    # the primary bound can clear 0.06285 while the wider Bonferroni bound
    # does not -- exercising that the two checks are genuinely independent.
    result = study.cell_verdict(station="NYC", hour=17, n=100, successes=12)
    assert result.wilson_lower >= study.PRIMARY_BAR
    assert result.wilson_lower_bonferroni < study.PRIMARY_BAR
    assert result.passes_primary is True
    assert result.passes_bonferroni is False


def test_cell_verdict_rejects_impossible_counts(study: ModuleType) -> None:
    with pytest.raises(ValueError):
        study.cell_verdict(station="NYC", hour=17, n=10, successes=11)
