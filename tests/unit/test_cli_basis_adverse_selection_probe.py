"""Unit tests for `scripts/analysis/cli_basis_adverse_selection_probe.py`.

Pre-registered in `pre_registration_2026-09-02T062000Z.md` -- the archive-side
proxy for Task 2's adverse-selection concern: does the admissible-hour setup
population decompose into seasons with materially different basis-crossing
rates? Covers only the GENUINE GAP, `season_setup_counts` and
`season_cell_verdict`; `season_for`, `SetupCase`, `build_setup_cases`,
`filter_cases_by_admissible_hours`, and `wilson_interval` are all reused
verbatim from modules with their own existing coverage.
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
def probe() -> ModuleType:
    return _load_module("cli_basis_adverse_selection_probe")


@pytest.fixture(scope="module")
def setup_study(probe: ModuleType) -> ModuleType:
    import cli_basis_setup_win_rate_study as setup_mod

    return setup_mod


# ---------------------------------------------------------------------------
# season_setup_counts
# ---------------------------------------------------------------------------


def test_season_setup_counts_buckets_by_station_and_season(
    probe: ModuleType, setup_study: ModuleType
) -> None:
    winter_day = dt.date(2021, 1, 15)  # DJF
    summer_day = dt.date(2021, 7, 15)  # JJA
    cases = (
        setup_study.SetupCase("LAX", winter_day, 20, 1, 70, 71, 71, True),
        setup_study.SetupCase("LAX", winter_day, 20, 2, 70, 72, 71, False),
        setup_study.SetupCase("LAX", summer_day, 20, 1, 90, 91, 91, True),
    )
    counts = probe.season_setup_counts(cases)
    assert counts[("LAX", "DJF")] == (2, 1)
    assert counts[("LAX", "JJA")] == (1, 1)


def test_season_setup_counts_separates_stations(
    probe: ModuleType, setup_study: ModuleType
) -> None:
    winter_day = dt.date(2021, 1, 15)
    cases = (
        setup_study.SetupCase("LAX", winter_day, 20, 1, 70, 71, 71, True),
        setup_study.SetupCase("SFO", winter_day, 20, 1, 60, 61, 61, False),
    )
    counts = probe.season_setup_counts(cases)
    assert counts[("LAX", "DJF")] == (1, 1)
    assert counts[("SFO", "DJF")] == (1, 0)


def test_season_setup_counts_maps_every_month_to_one_of_four_seasons(
    probe: ModuleType, setup_study: ModuleType
) -> None:
    cases = tuple(
        setup_study.SetupCase("LAX", dt.date(2021, month, 15), 20, 1, 70, 71, 71, True)
        for month in range(1, 13)
    )
    counts = probe.season_setup_counts(cases)
    seasons = {season for (_station, season) in counts}
    assert seasons == {"DJF", "MAM", "JJA", "SON"}


def test_season_setup_counts_empty_for_no_cases(probe: ModuleType) -> None:
    assert probe.season_setup_counts(()) == {}


# ---------------------------------------------------------------------------
# season_cell_verdict
# ---------------------------------------------------------------------------


def test_season_cell_verdict_underpowered_below_min_n(probe: ModuleType) -> None:
    cell = probe.season_cell_verdict(
        station="LAX", season="DJF", n=50, k=10, pooled_rate=0.1213
    )
    assert cell.verdict == "UNDERPOWERED"


def test_season_cell_verdict_heterogeneous_when_interval_excludes_pooled_rate(
    probe: ModuleType,
) -> None:
    # A season whose observed rate is far above the pooled point estimate,
    # at large n, so the Wilson interval excludes it cleanly.
    cell = probe.season_cell_verdict(
        station="LAX", season="DJF", n=2000, k=1200, pooled_rate=0.1213
    )
    assert cell.admissible is True
    assert cell.verdict == "MATERIALLY HETEROGENEOUS"


def test_season_cell_verdict_homogeneous_when_interval_contains_pooled_rate(
    probe: ModuleType,
) -> None:
    # A season whose rate is close to the pooled point estimate, at large n,
    # so the Wilson interval contains it.
    cell = probe.season_cell_verdict(
        station="LAX", season="DJF", n=2000, k=243, pooled_rate=0.1213
    )
    assert cell.admissible is True
    assert cell.verdict == "MATERIALLY HOMOGENEOUS"


def test_season_cell_verdict_rejects_impossible_counts(probe: ModuleType) -> None:
    with pytest.raises(ValueError):
        probe.season_cell_verdict(station="LAX", season="DJF", n=10, k=11, pooled_rate=0.1213)
