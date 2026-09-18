"""Unit tests for ``scripts/analysis/forecast_climate_day_map.py`` (FC-0a-4 Phase A)."""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Final
from unittest.mock import patch

import pytest

from breezy.ingest import gaps
from breezy.registry.sites import default_registry
from tests.support.forecast_climate_day_fixtures import (
    FORECAST_STATIONS,
    FORECAST_VENUE,
    FROZEN_FIXTURES,
    FROZEN_TABLE_SHA256,
    ForecastDayFixture,
    table_digest,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_MAPPER_PATH = _SCRIPTS_ANALYSIS_DIR / "forecast_climate_day_map.py"
_FIXTURES_PATH = (
    _REPO_ROOT / "tests" / "support" / "forecast_climate_day_fixtures.py"
)

_FORBIDDEN_IDENTIFIERS: Final[frozenset[str]] = frozenset({"side", "leg", "yes", "no"})
_NS: Final[int] = 10**9
_PERIOD_HOURS: Final[int] = 18


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


def _utc_ns(year: int, month: int, day: int, hour: int) -> int:
    return int(dt.datetime(year, month, day, hour, tzinfo=dt.UTC).timestamp()) * _NS


def _offset_for(icao: str) -> float:
    city = next(token for code, token in FORECAST_STATIONS if code == icao)
    return default_registry().climate_day_window(FORECAST_VENUE, city).std_utc_offset_hours


def _call(
    mapper: ModuleType,
    *,
    icao: str = "KMIA",
    runtime_ns: int | None = None,
    ftime_ns: int | None = None,
    std_utc_offset_hours: float | None = -5.0,
    model: str = "NBM_NBS",
) -> dt.date:
    if runtime_ns is None:
        runtime_ns = _utc_ns(2026, 7, 15, 12)
    if ftime_ns is None:
        ftime_ns = _utc_ns(2026, 7, 16, 6)
    return mapper.climate_day_for_txn(  # type: ignore[no-any-return]
        icao=icao,
        runtime_ns=runtime_ns,
        ftime_ns=ftime_ns,
        std_utc_offset_hours=std_utc_offset_hours,
        model=model,
    )


def _call_row(mapper: ModuleType, row: ForecastDayFixture, **overrides: object) -> dt.date:
    kwargs = {
        "icao": row.icao,
        "runtime_ns": row.runtime_ns,
        "ftime_ns": row.ftime_ns,
        "std_utc_offset_hours": row.std_utc_offset_hours,
        "model": row.model,
    }
    kwargs.update(overrides)
    return mapper.climate_day_for_txn(**kwargs)  # type: ignore[no-any-return]


def _identifier_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add(node.name.split(".")[-1])
            if node.asname is not None:
                names.add(node.asname)
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            names.add(node.name)
    return names


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    return roots


def test_climate_day_for_txn_delegates_every_conversion_to_local_standard_date(
    mapper: ModuleType,
) -> None:
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    runtime_ns = _utc_ns(2026, 7, 15, 12)
    offset = _offset_for("KMIA")
    expected_valid_start = ftime_ns - _PERIOD_HOURS * 3600 * _NS
    with patch.object(gaps, "local_standard_date", wraps=gaps.local_standard_date) as spy:
        result = _call(
            mapper,
            icao="KMIA",
            runtime_ns=runtime_ns,
            ftime_ns=ftime_ns,
            std_utc_offset_hours=offset,
        )
    spy.assert_called_once_with(expected_valid_start, offset)
    assert result == gaps.local_standard_date(expected_valid_start, offset)


@pytest.mark.parametrize(
    "row",
    FROZEN_FIXTURES,
    ids=lambda row: f"{row.phenomenon}-{row.icao}",
)
def test_frozen_fixtures_map_to_expected_climate_day(
    mapper: ModuleType, row: ForecastDayFixture
) -> None:
    if row.expected_refusal:
        with pytest.raises(mapper.ForecastValidPeriodError, match="not the daily-max TXN period"):
            _call_row(mapper, row)
        return
    assert _call_row(mapper, row) == row.expected_climate_day


@pytest.mark.parametrize(
    ("icao", "std_utc_offset_hours"),
    [
        ("KMIA", -5.0),
        ("KMDW", -6.0),
        ("KSFO", -8.0),
        ("KLAX", -8.0),
    ],
    ids=["-5.0", "-6.0", "-8.0", "-8.0"],
)
def test_06z_ftime_maps_to_the_valid_start_local_day(
    mapper: ModuleType, icao: str, std_utc_offset_hours: float
) -> None:
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    runtime_ns = _utc_ns(2026, 7, 15, 12)
    mapped = _call(
        mapper,
        icao=icao,
        runtime_ns=runtime_ns,
        ftime_ns=ftime_ns,
        std_utc_offset_hours=std_utc_offset_hours,
    )
    valid_start_ns = ftime_ns - mapper.TXN_MAX_PERIOD_HOURS * 3600 * _NS
    assert mapped == gaps.local_standard_date(valid_start_ns, std_utc_offset_hours)
    assert mapped == dt.date(2026, 7, 15)


def test_an_18z_ftime_refuses_as_not_the_daily_max_period(mapper: ModuleType) -> None:
    night_min = next(row for row in FROZEN_FIXTURES if row.phenomenon == "night_min_18z")
    with pytest.raises(mapper.ForecastValidPeriodError, match="not the daily-max TXN period"):
        _call_row(mapper, night_min)


def test_refusal_names_the_max_period_constant(mapper: ModuleType) -> None:
    assert mapper.TXN_MAX_PERIOD_END_UTC_HOUR == 6
    ftime_ns = _utc_ns(2026, 7, 15, 18)
    with pytest.raises(mapper.ForecastValidPeriodError, match="not the daily-max TXN period"):
        _call(mapper, ftime_ns=ftime_ns)
    hour = (ftime_ns // _NS) % 86400 // 3600
    assert hour != mapper.TXN_MAX_PERIOD_END_UTC_HOUR


def test_ftime_own_local_date_disagrees_with_the_pin_at_kmia_and_kmdw(
    mapper: ModuleType,
) -> None:
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    runtime_ns = _utc_ns(2026, 7, 15, 12)
    for icao in ("KMIA", "KMDW"):
        offset = _offset_for(icao)
        pin = _call(
            mapper,
            icao=icao,
            runtime_ns=runtime_ns,
            ftime_ns=ftime_ns,
            std_utc_offset_hours=offset,
        )
        ftime_local = gaps.local_standard_date(ftime_ns, offset)
        assert pin != ftime_local
        assert pin == dt.date(2026, 7, 15)
        assert ftime_local == dt.date(2026, 7, 16)


def test_adjacent_cycles_12z_d_and_12z_d_plus_1_map_to_distinct_consecutive_days(
    mapper: ModuleType,
) -> None:
    offset = _offset_for("KMIA")
    day_d = _call(
        mapper,
        runtime_ns=_utc_ns(2026, 7, 15, 12),
        ftime_ns=_utc_ns(2026, 7, 16, 6),
        std_utc_offset_hours=offset,
    )
    day_d1 = _call(
        mapper,
        runtime_ns=_utc_ns(2026, 7, 16, 12),
        ftime_ns=_utc_ns(2026, 7, 17, 6),
        std_utc_offset_hours=offset,
    )
    assert day_d == dt.date(2026, 7, 15)
    assert day_d1 == dt.date(2026, 7, 16)
    assert day_d1 - day_d == dt.timedelta(days=1)


@pytest.mark.parametrize("std_utc_offset_hours", [-5.0, -6.0, -8.0])
@pytest.mark.parametrize("delta_ns", [-1, 1])
def test_one_nanosecond_either_side_of_local_midnight(
    mapper: ModuleType, std_utc_offset_hours: float, delta_ns: int
) -> None:
    midnight_utc_hour = int(-std_utc_offset_hours)
    midnight_ns = _utc_ns(2026, 7, 15, midnight_utc_hour)
    instant_ns = midnight_ns + delta_ns
    local_day = gaps.local_standard_date(instant_ns, std_utc_offset_hours)
    if delta_ns < 0:
        assert local_day == dt.date(2026, 7, 14)
    else:
        assert local_day == dt.date(2026, 7, 15)
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    mapped = _call(mapper, ftime_ns=ftime_ns, std_utc_offset_hours=std_utc_offset_hours)
    valid_start_ns = ftime_ns - mapper.TXN_MAX_PERIOD_HOURS * 3600 * _NS
    assert mapped == gaps.local_standard_date(valid_start_ns, std_utc_offset_hours)


def test_mapping_is_identical_for_model_nbm_nbs_and_gfs_mos(mapper: ModuleType) -> None:
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    runtime_ns = _utc_ns(2026, 7, 15, 12)
    offset = _offset_for("KMIA")
    nbm = _call(
        mapper,
        runtime_ns=runtime_ns,
        ftime_ns=ftime_ns,
        std_utc_offset_hours=offset,
        model="NBM_NBS",
    )
    gfs = _call(
        mapper,
        runtime_ns=runtime_ns,
        ftime_ns=ftime_ns,
        std_utc_offset_hours=offset,
        model="GFS_MOS",
    )
    assert nbm == gfs == dt.date(2026, 7, 15)


def test_missing_or_none_offset_refuses_instead_of_defaulting_to_utc(
    mapper: ModuleType,
) -> None:
    signature = inspect.signature(mapper.climate_day_for_txn)
    offset_param = signature.parameters["std_utc_offset_hours"]
    assert offset_param.default is inspect.Parameter.empty
    with pytest.raises(mapper.ForecastValidPeriodError):
        _call(mapper, std_utc_offset_hours=None)
    utc_default = gaps.local_standard_date(
        _utc_ns(2026, 7, 16, 6) - _PERIOD_HOURS * 3600 * _NS, 0.0
    )
    with pytest.raises(mapper.ForecastValidPeriodError):
        result = _call(mapper, std_utc_offset_hours=None)
        assert result != utc_default


def test_runtime_after_the_period_end_refuses(mapper: ModuleType) -> None:
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    runtime_ns = ftime_ns + 1
    with pytest.raises(mapper.ForecastValidPeriodError):
        _call(mapper, runtime_ns=runtime_ns, ftime_ns=ftime_ns)


def test_non_integer_ns_refuses(mapper: ModuleType) -> None:
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    runtime_ns = _utc_ns(2026, 7, 15, 12)
    with pytest.raises(mapper.ForecastValidPeriodError):
        mapper.climate_day_for_txn(
            icao="KMIA",
            runtime_ns=float(runtime_ns),
            ftime_ns=ftime_ns,
            std_utc_offset_hours=-5.0,
            model="NBM_NBS",
        )
    with pytest.raises(mapper.ForecastValidPeriodError):
        mapper.climate_day_for_txn(
            icao="KMIA",
            runtime_ns=runtime_ns,
            ftime_ns=float(ftime_ns),
            std_utc_offset_hours=-5.0,
            model="NBM_NBS",
        )


def test_period_end_crossing_local_midnight_does_not_change_the_result(
    mapper: ModuleType,
) -> None:
    """KMIA/KMDW period end is on local D+1; P2 still assigns D."""
    ftime_ns = _utc_ns(2026, 7, 16, 6)
    runtime_ns = _utc_ns(2026, 7, 15, 12)
    for icao in ("KMIA", "KMDW"):
        offset = _offset_for(icao)
        pin = _call(
            mapper,
            icao=icao,
            runtime_ns=runtime_ns,
            ftime_ns=ftime_ns,
            std_utc_offset_hours=offset,
        )
        assert gaps.local_standard_date(ftime_ns, offset) == dt.date(2026, 7, 16)
        assert pin == dt.date(2026, 7, 15)


def test_mia_bleed_disagrees_with_a_utc_day_cut(mapper: ModuleType) -> None:
    row = next(item for item in FROZEN_FIXTURES if item.phenomenon == "mia_period_end_bleed")
    mapped = _call_row(mapper, row)
    utc_cut = dt.datetime.fromtimestamp(row.ftime_ns // _NS, tz=dt.UTC).date()
    assert mapped == row.expected_climate_day
    assert utc_cut == row.expected_utc_naive_day
    assert mapped != utc_cut


@pytest.mark.parametrize("icao", ["KSFO", "KLAX"])
def test_pacific_utc_cut_misses_the_true_local_max(mapper: ModuleType, icao: str) -> None:
    row = next(item for item in FROZEN_FIXTURES if item.icao == icao and not item.expected_refusal)
    mapped = _call_row(mapper, row)
    utc_cut = dt.datetime.fromtimestamp(row.ftime_ns // _NS, tz=dt.UTC).date()
    ftime_local = gaps.local_standard_date(row.ftime_ns, row.std_utc_offset_hours)
    assert mapped == row.expected_climate_day == dt.date(2026, 7, 15)
    assert utc_cut == dt.date(2026, 7, 16)
    assert ftime_local == mapped
    assert utc_cut != mapped


def test_dst_transition_day_assignment_is_identical_to_a_non_dst_day(
    mapper: ModuleType,
) -> None:
    offset = _offset_for("KMIA")
    probes = (
        dt.date(2026, 3, 8),
        dt.date(2026, 3, 5),
        dt.date(2026, 11, 1),
        dt.date(2026, 10, 29),
    )
    for climate in probes:
        ftime = dt.datetime(
            climate.year, climate.month, climate.day, 6, tzinfo=dt.UTC
        ) + dt.timedelta(days=1)
        runtime = dt.datetime(climate.year, climate.month, climate.day, 12, tzinfo=dt.UTC)
        mapped = _call(
            mapper,
            icao="KMIA",
            runtime_ns=int(runtime.timestamp()) * _NS,
            ftime_ns=int(ftime.timestamp()) * _NS,
            std_utc_offset_hours=offset,
        )
        assert mapped == climate


def test_v5_split_cycle_runtime_does_not_change_day_assignment(mapper: ModuleType) -> None:
    pair = [row for row in FROZEN_FIXTURES if row.phenomenon.startswith("v5_split_")]
    assert len(pair) == 2
    days = {_call_row(mapper, row) for row in pair}
    runtimes = {row.runtime_ns for row in pair}
    assert len(days) == 1
    assert len(runtimes) == 2
    assert pair[0].ftime_ns == pair[1].ftime_ns


def test_off_grid_runtime_is_accepted_not_refused(mapper: ModuleType) -> None:
    mapped = _call(
        mapper,
        runtime_ns=_utc_ns(2026, 7, 15, 15),
        ftime_ns=_utc_ns(2026, 7, 16, 6),
        std_utc_offset_hours=_offset_for("KMIA"),
    )
    assert mapped == dt.date(2026, 7, 15)


def test_discriminating_fixtures_actually_discriminate(mapper: ModuleType) -> None:
    bleed = next(row for row in FROZEN_FIXTURES if row.phenomenon == "mia_period_end_bleed")
    pacific = [row for row in FROZEN_FIXTURES if row.phenomenon.endswith("utc_cut_miss")]
    night_min = next(row for row in FROZEN_FIXTURES if row.phenomenon == "night_min_18z")
    assert bleed.expected_climate_day != bleed.expected_utc_naive_day
    assert _call_row(mapper, bleed) != bleed.expected_utc_naive_day
    assert pacific
    for row in pacific:
        assert row.expected_climate_day != row.expected_utc_naive_day
        assert _call_row(mapper, row) != row.expected_utc_naive_day
    assert night_min.expected_refusal is True
    dst_days = {
        row.expected_climate_day
        for row in FROZEN_FIXTURES
        if row.phenomenon.startswith("dst_")
    }
    assert dt.date(2026, 3, 8) in dst_days
    assert dt.date(2026, 11, 1) in dst_days


def test_mapping_signature_has_no_side_or_leg_parameter(mapper: ModuleType) -> None:
    signature = inspect.signature(mapper.climate_day_for_txn)
    assert list(signature.parameters) == [
        "icao",
        "runtime_ns",
        "ftime_ns",
        "std_utc_offset_hours",
        "model",
    ]
    for parameter in signature.parameters.values():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.name not in _FORBIDDEN_IDENTIFIERS


def test_module_ast_has_no_side_leg_yes_or_no_identifier(mapper: ModuleType) -> None:
    tree = ast.parse(_MAPPER_PATH.read_text(encoding="utf-8"), filename=str(_MAPPER_PATH))
    found = _identifier_names(tree) & _FORBIDDEN_IDENTIFIERS
    assert found == set()


def test_docstring_leg_invariance_line_does_not_trip_the_ast_scan(mapper: ModuleType) -> None:
    doc = mapper.climate_day_for_txn.__doc__
    assert doc is not None
    assert "Leg-invariance" in doc
    tree = ast.parse(_MAPPER_PATH.read_text(encoding="utf-8"), filename=str(_MAPPER_PATH))
    found = _identifier_names(tree) & _FORBIDDEN_IDENTIFIERS
    assert found == set()


def test_no_zoneinfo_or_nautilus_import(mapper: ModuleType) -> None:
    del mapper
    for path in (_MAPPER_PATH, _FIXTURES_PATH):
        roots = _imported_roots(path)
        assert "zoneinfo" not in roots
        assert "nautilus_trader" not in roots


def test_no_tilde_literal_in_any_path(mapper: ModuleType) -> None:
    del mapper
    for path in (_MAPPER_PATH, _FIXTURES_PATH):
        assert "~" not in path.read_text(encoding="utf-8")


@pytest.mark.xfail(
    FROZEN_TABLE_SHA256 is None,
    strict=True,
    reason="Phase A: no observed rows yet",
)
def test_fixture_table_digest_is_frozen() -> None:
    assert table_digest(FROZEN_FIXTURES) == FROZEN_TABLE_SHA256


def test_a_consumer_refuses_a_none_digest_table(mapper: ModuleType) -> None:
    del mapper

    def consume(digest: str | None) -> str:
        if digest is None:
            raise ValueError("refusing a None digest table")
        return digest

    with pytest.raises(ValueError, match="None digest"):
        consume(FROZEN_TABLE_SHA256)


@pytest.mark.xfail(
    not any(row.provenance == "observed" for row in FROZEN_FIXTURES),
    strict=True,
    reason="Phase B: observed rows land after the IEM probe artefact",
)
def test_every_phenomenon_has_an_observed_row() -> None:
    missing = [
        phenomenon
        for phenomenon in {row.phenomenon for row in FROZEN_FIXTURES}
        if not any(
            row.provenance == "observed" and row.phenomenon == phenomenon for row in FROZEN_FIXTURES
        )
    ]
    assert missing == []
