"""Unit tests for `scripts/analysis/forecast_txn_climate_day_cli_alignment.py` (FC-0a-4 Phase B).

No network, no real cache read: every fixture is a small synthetic
`CliRecord`/`CliMaxTime` row through the real (reused) functions, matching
`test_cli_basis_boundary_study.py`'s convention. `main()` / `load_and_align`
(the real-I/O path against the on-disk settlement-alignment cache) are
exercised manually to regenerate the evidence document, never by this
suite.
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


def _load_module(name: str) -> ModuleType:
    """Load a `scripts/analysis/<name>.py` module by file path (repo convention)."""
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
def align_module() -> ModuleType:
    return _load_module("forecast_txn_climate_day_cli_alignment")


@pytest.fixture(scope="module")
def pmr(align_module: ModuleType) -> ModuleType:
    return sys.modules["pmr_climatology_study"]


def _cli_record(
    pmr: ModuleType,
    *,
    city: str,
    climate_day: dt.date,
    max_hour: int | None,
    max_minute: int = 0,
    tmax_f: int = 70,
) -> object:
    max_time = None if max_hour is None else pmr.CliMaxTime(hour=max_hour, minute=max_minute)
    return pmr.CliRecord(
        city=city,
        climate_day=climate_day,
        issuance="FINAL",
        tmax_f=tmax_f,
        tmax_sentinel="",
        max_time=max_time,
        is_correction_bbb=False,
        issued_at_utc=None,
        source="test",
    )


# ---------------------------------------------------------------------------
# window_bounds / is_hour_in_window
# ---------------------------------------------------------------------------


def test_window_bounds_mia_stays_within_the_same_local_day(align_module: ModuleType) -> None:
    # Phase B2: TXN_MAX_PERIOD_END_UTC_HOUR moved 6 -> 0 (measured); bounds
    # shift accordingly. MIA no longer wraps past local midnight.
    bounds = align_module.window_bounds(-5.0)
    assert bounds.start_local_hour == 1
    assert bounds.end_local_hour == 19
    assert bounds.wraps is False


def test_window_bounds_mdw_starts_exactly_at_local_midnight(align_module: ModuleType) -> None:
    bounds = align_module.window_bounds(-6.0)
    assert bounds.start_local_hour == 0
    assert bounds.end_local_hour == 18
    assert bounds.wraps is False


def test_window_bounds_sfo_lax_wraps_past_local_midnight(align_module: ModuleType) -> None:
    # Phase B2: SFO/LAX now wraps (previously did not, under the 06Z end hour).
    bounds = align_module.window_bounds(-8.0)
    assert bounds.start_local_hour == 22
    assert bounds.end_local_hour == 16
    assert bounds.wraps is True


def test_is_hour_in_window_wrapping_window_accepts_late_and_early_hours(
    align_module: ModuleType,
) -> None:
    bounds = align_module.window_bounds(-8.0)  # SFO/LAX: start=22, end=16, wraps
    assert align_module.is_hour_in_window(22, bounds) is True
    assert align_module.is_hour_in_window(23, bounds) is True
    assert align_module.is_hour_in_window(0, bounds) is True
    assert align_module.is_hour_in_window(15, bounds) is True
    assert align_module.is_hour_in_window(16, bounds) is False
    assert align_module.is_hour_in_window(21, bounds) is False


def test_is_hour_in_window_non_wrapping_window_rejects_late_night(
    align_module: ModuleType,
) -> None:
    bounds = align_module.window_bounds(-5.0)  # MIA: start=1, end=19, no wrap
    assert align_module.is_hour_in_window(1, bounds) is True
    assert align_module.is_hour_in_window(18, bounds) is True
    assert align_module.is_hour_in_window(19, bounds) is False
    assert align_module.is_hour_in_window(0, bounds) is False
    assert align_module.is_hour_in_window(20, bounds) is False


# ---------------------------------------------------------------------------
# climate_day_for_real_final
# ---------------------------------------------------------------------------


def test_climate_day_for_real_final_reproduces_the_target_day_at_every_offset(
    align_module: ModuleType,
) -> None:
    day = dt.date(2024, 12, 2)
    for icao, offset in (("KMIA", -5.0), ("KMDW", -6.0), ("KSFO", -8.0), ("KLAX", -8.0)):
        mapped = align_module.climate_day_for_real_final(
            icao=icao, climate_day=day, std_utc_offset_hours=offset
        )
        assert mapped == day


def test_climate_day_for_real_final_is_runtime_invariant(align_module: ModuleType) -> None:
    """Different valid runtimes for the same target day must not change the result."""
    day = dt.date(2023, 6, 1)
    mapped = align_module.climate_day_for_real_final(
        icao="KMIA", climate_day=day, std_utc_offset_hours=-5.0, model="GFS_MOS"
    )
    assert mapped == day


# ---------------------------------------------------------------------------
# align_station
# ---------------------------------------------------------------------------


def test_align_station_confirms_the_day_label_over_synthetic_real_dated_rows(
    align_module: ModuleType, pmr: ModuleType
) -> None:
    days = [dt.date(2024, 12, 2), dt.date(2024, 12, 3), dt.date(2022, 3, 13)]
    finals = {d: _cli_record(pmr, city="MIA", climate_day=d, max_hour=15) for d in days}
    result = align_module.align_station(
        icao="KMIA", city="MIA", std_utc_offset_hours=-5.0, finals_by_day=finals
    )
    assert result.day_label_confirmed is True
    assert result.n_days == 3
    assert result.window_misses == ()


def test_align_station_flags_a_max_time_outside_the_window_as_a_window_miss(
    align_module: ModuleType, pmr: ModuleType
) -> None:
    # Phase B2 bounds for MDW (-6.0): start=0, end=18 -- hour 20 is outside.
    day = dt.date(2021, 1, 22)
    finals = {day: _cli_record(pmr, city="MDW", climate_day=day, max_hour=20, max_minute=13)}
    result = align_module.align_station(
        icao="KMDW", city="MDW", std_utc_offset_hours=-6.0, finals_by_day=finals
    )
    assert result.day_label_confirmed is True  # window miss != day-label mismatch
    assert result.window_misses == ((day, 20),)
    assert result.window_miss_rate == pytest.approx(1.0)


def test_align_station_a_none_max_time_is_excluded_from_the_window_denominator(
    align_module: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2021, 5, 5)
    finals = {day: _cli_record(pmr, city="LAX", climate_day=day, max_hour=None)}
    result = align_module.align_station(
        icao="KLAX", city="LAX", std_utc_offset_hours=-8.0, finals_by_day=finals
    )
    assert result.n_with_max_time == 0
    assert result.window_misses == ()
    assert result.window_miss_rate == 0.0


def test_align_station_would_flag_a_day_label_mismatch_if_the_mapper_ever_disagreed(
    align_module: ModuleType, monkeypatch: pytest.MonkeyPatch, pmr: ModuleType
) -> None:
    """Injects a deliberately-wrong mapper to prove the cross-check actually discriminates."""
    day = dt.date(2024, 12, 2)
    finals = {day: _cli_record(pmr, city="MIA", climate_day=day, max_hour=15)}
    monkeypatch.setattr(
        align_module,
        "climate_day_for_real_final",
        lambda **kwargs: kwargs["climate_day"] + dt.timedelta(days=1),
    )
    result = align_module.align_station(
        icao="KMIA", city="MIA", std_utc_offset_hours=-5.0, finals_by_day=finals
    )
    assert result.day_label_confirmed is False
    assert result.day_label_mismatches == (day,)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def test_build_report_names_every_station_and_reports_zero_mismatches(
    align_module: ModuleType, pmr: ModuleType
) -> None:
    day = dt.date(2024, 12, 2)
    finals = {day: _cli_record(pmr, city="MIA", climate_day=day, max_hour=15)}
    result = align_module.align_station(
        icao="KMIA", city="MIA", std_utc_offset_hours=-5.0, finals_by_day=finals
    )
    report = align_module.build_report([result])
    assert "KMIA" in report
    assert "0 mismatches" in report


def test_forecast_stations_matches_the_fixture_tables_four_stations(
    align_module: ModuleType,
) -> None:
    from tests.support.forecast_climate_day_fixtures import FORECAST_STATIONS

    assert set(align_module.FORECAST_STATIONS) == set(FORECAST_STATIONS)


def test_no_network_import(align_module: ModuleType) -> None:
    """This module must never import an HTTP client or nautilus_trader."""
    import ast

    path = _SCRIPTS_ANALYSIS_DIR / "forecast_txn_climate_day_cli_alignment.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    assert "httpx" not in roots
    assert "nautilus_trader" not in roots
    assert "requests" not in roots
