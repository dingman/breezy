"""AC-11: forecast-station set and registry offsets (FC-0a-4 Phase A)."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from breezy.registry.sites import default_registry
from tests.support.forecast_climate_day_fixtures import FORECAST_STATIONS, FORECAST_VENUE

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_MAPPER_PATH = _SCRIPTS_ANALYSIS_DIR / "forecast_climate_day_map.py"

_EXPECTED_OFFSETS = {
    "KMIA": -5.0,
    "KSFO": -8.0,
    "KMDW": -6.0,
    "KLAX": -8.0,
}


def _load_module(name: str) -> ModuleType:
    """Load a ``scripts/analysis/<name>.py`` module by file path.

    Mirrors the existing repo convention (see
    ``tests/unit/test_cli_basis_boundary_study.py``) for loading a
    bare-import-style analysis script without installing
    ``scripts/analysis`` as a package.
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
def mapper() -> ModuleType:
    return _load_module("forecast_climate_day_map")


def test_four_forecast_stations_resolve_expected_std_offsets(mapper: ModuleType) -> None:
    del mapper
    registry = default_registry()
    resolved = {
        icao: registry.climate_day_window(FORECAST_VENUE, city).std_utc_offset_hours
        for icao, city in FORECAST_STATIONS
    }
    assert resolved == _EXPECTED_OFFSETS
    assert set(resolved) == {"KMIA", "KSFO", "KMDW", "KLAX"}


def test_knyc_is_excluded_from_forecast_station_set(mapper: ModuleType) -> None:
    del mapper
    icaos = {icao for icao, _city in FORECAST_STATIONS}
    assert "KNYC" not in icaos
    assert icaos == {"KMIA", "KSFO", "KMDW", "KLAX"}


def test_offsets_come_from_registry_not_literals(mapper: ModuleType) -> None:
    source = _MAPPER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_MAPPER_PATH))
    numeric_literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
        and node.value in {-5.0, -6.0, -8.0, -5, -6, -8}
    ]
    assert numeric_literals == [], f"per-city offset literals in mapper: {numeric_literals}"
    for icao, city in FORECAST_STATIONS:
        window = default_registry().climate_day_window(FORECAST_VENUE, city)
        assert window.std_utc_offset_hours == _EXPECTED_OFFSETS[icao]
    # Mapper source must not mention a city offset by ICAO pairing.
    assert "KMIA" not in source or "std_utc_offset_hours=-5" not in source.replace(" ", "")
    del mapper
