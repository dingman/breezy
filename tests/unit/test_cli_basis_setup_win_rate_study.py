"""Unit tests for `scripts/analysis/cli_basis_setup_win_rate_study.py` (Item 3).

Covers the GENUINELY NEW join (`build_setup_cases`, generalizing margin to
{1, 2} with no hour restriction) and the pooling/verdict rule
(`summarize_station`, `pool_stations`, `pooled_verdict`). The running-max
fold, CLI loader, hour coverage, and Wilson bound are all reused verbatim
from modules with their own existing coverage -- not re-tested here. No
network access; every fixture is synthetic, mirroring
`test_cli_basis_boundary_study.py`'s own fixture shapes.
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
    return _load_module("cli_basis_setup_win_rate_study")


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
# QUALIFYING_MARGINS / DENSE_STATIONS -- reused verbatim, never re-derived
# ---------------------------------------------------------------------------


def test_qualifying_margins_matches_the_offer_gate_scans_headroom_set(
    study: ModuleType,
) -> None:
    import cli_basis_offer_gate_scan as scan

    assert set(study.QUALIFYING_MARGINS) == scan.QUALIFYING_HEADROOM


def test_dense_stations_excludes_the_contaminated_station(study: ModuleType) -> None:
    import cli_basis_offer_gate_scan as scan

    assert set(study.DENSE_STATIONS).isdisjoint(scan.CONTAMINATED_STATIONS)
    assert "NYC" not in study.DENSE_STATIONS


def test_primary_bar_matches_the_boundary_studys_bar(study: ModuleType) -> None:
    assert study.PRIMARY_BAR == pytest.approx(0.06285)


# ---------------------------------------------------------------------------
# build_setup_cases -- the ASOS<->CLI join, margins {1, 2}, no hour restriction
# ---------------------------------------------------------------------------


def test_build_setup_cases_hits_for_margin_one_and_two_when_final_clears_both(
    study: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(
            pmr, city="LAX", climate_day=day, running_max_f=_series_with({3: 78})
        )
    ]
    coverage = {day: frozenset({3})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=80)}

    cases = study.build_setup_cases(
        station="LAX", running_max_days=running_days, covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    assert len(cases) == 2
    by_margin = {c.margin: c for c in cases}
    assert by_margin[1].threshold_f == 79
    assert by_margin[1].hit is True  # 80 >= 79
    assert by_margin[2].threshold_f == 80
    assert by_margin[2].hit is True  # 80 >= 80


def test_build_setup_cases_miss_when_final_falls_short(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="LAX", climate_day=day, running_max_f=_series_with({3: 78}))
    ]
    coverage = {day: frozenset({3})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=79)}

    cases = study.build_setup_cases(
        station="LAX", running_max_days=running_days, covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    by_margin = {c.margin: c for c in cases}
    assert by_margin[1].hit is True  # 79 >= 79
    assert by_margin[2].hit is False  # 79 >= 80 is False


def test_build_setup_cases_excludes_an_uncovered_hour(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="LAX", climate_day=day, running_max_f=_series_with({3: 78}))
    ]
    coverage: dict[dt.date, frozenset[int]] = {day: frozenset()}  # hour 3 not covered
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=90)}

    cases = study.build_setup_cases(
        station="LAX", running_max_days=running_days, covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    assert cases == ()


def test_build_setup_cases_excludes_a_missing_final(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="LAX", climate_day=day, running_max_f=_series_with({3: 78}))
    ]
    coverage = {day: frozenset({3})}
    cases = study.build_setup_cases(
        station="LAX", running_max_days=running_days, covered_hours_by_day=coverage, cli_finals={}
    )
    assert cases == ()


def test_build_setup_cases_excludes_a_sentinel_final(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="LAX", climate_day=day, running_max_f=_series_with({3: 78}))
    ]
    coverage = {day: frozenset({3})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=None)}
    cases = study.build_setup_cases(
        station="LAX", running_max_days=running_days, covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    assert cases == ()


def test_build_setup_cases_evaluates_every_hour_not_just_17_to_23(
    study: ModuleType, pmr: ModuleType
) -> None:
    """The offer-gate scan's own correction: no hour restriction, since the
    running max has already converged well before local-standard hour 17.
    """
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="LAX", climate_day=day, running_max_f=_series_with({5: 70}))
    ]
    coverage = {day: frozenset({5})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=72)}
    cases = study.build_setup_cases(
        station="LAX", running_max_days=running_days, covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    assert len(cases) == 2
    assert all(c.hour == 5 for c in cases)


# ---------------------------------------------------------------------------
# summarize_station / pool_stations / pooled_verdict
# ---------------------------------------------------------------------------


def test_summarize_station_counts_n_and_k(study: ModuleType, pmr: ModuleType) -> None:
    day = dt.date(2021, 8, 1)
    running_days = [
        _running_max_day(pmr, city="LAX", climate_day=day, running_max_f=_series_with({3: 78}))
    ]
    coverage = {day: frozenset({3})}
    finals = {day: _cli_final(pmr, city="LAX", climate_day=day, tmax_f=80)}
    cases = study.build_setup_cases(
        station="LAX", running_max_days=running_days, covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    result = study.summarize_station(cases)
    assert result.station == "LAX"
    assert result.n == 2
    assert result.k == 2  # both margins hit


def test_summarize_station_empty_for_no_cases(study: ModuleType) -> None:
    result = study.summarize_station(())
    assert result.n == 0
    assert result.k == 0
    assert result.wilson_lower == 0.0
    assert result.wilson_upper == 1.0


def test_pooled_verdict_underpowered_below_min_n(study: ModuleType) -> None:
    result = study.pooled_verdict(n=1, k=1)
    assert result.verdict == "UNDERPOWERED"


def test_pooled_verdict_passes_when_lower_bound_clears_the_bar(study: ModuleType) -> None:
    # A generous, unambiguous rate at adequate n.
    result = study.pooled_verdict(n=1000, k=200)
    assert result.verdict == "PASS"
    assert result.wilson_lower >= study.PRIMARY_BAR


def test_pooled_verdict_fails_when_upper_bound_stays_below_the_bar(study: ModuleType) -> None:
    result = study.pooled_verdict(n=1000, k=1)
    assert result.verdict == "FAIL"
    assert result.wilson_upper < study.PRIMARY_BAR


def test_pooled_verdict_underpowered_between_fail_and_pass_at_adequate_n(
    study: ModuleType,
) -> None:
    result = study.pooled_verdict(n=study.MIN_ADMISSIBLE_N, k=7)
    assert result.verdict == "UNDERPOWERED"


def test_pool_stations_sums_n_and_k_across_stations(study: ModuleType) -> None:
    a = study.StationSetupResult(station="LAX", n=10, k=1, wilson_lower=0.0, wilson_upper=1.0)
    b = study.StationSetupResult(station="SFO", n=20, k=2, wilson_lower=0.0, wilson_upper=1.0)
    pooled = study.pool_stations((a, b))
    assert pooled.n == 30
    assert pooled.k == 3


def test_min_admissible_n_is_pinned_at_one_hundred(study: ModuleType) -> None:
    assert study.MIN_ADMISSIBLE_N == 100
