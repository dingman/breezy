"""Phase-B observed-provenance fixtures for the frozen TXN climate-day map (FC-0a-4).

RED-FIRST, per the WP-4 GATE: three fixtures are named in the plan because
they are the known ways `(icao, runtime, ftime) -> climate_day` goes wrong --
MIA bleed, SFO/LAX PST miss, DST transition. This module pins them with
REAL, archive-verified dates (never the 2026 placeholder dates Phase A used)
and proves each one actually DISCRIMINATES: a naive "UTC calendar date of
ftime" map gets it WRONG, and the frozen `climate_day_for_txn` gets it
RIGHT. A fixture that both maps agree on would prove nothing -- see
`test_discriminating_fixtures_actually_discriminate` in
`test_forecast_txn_climate_day.py` for the Phase-A precedent of this same
check.

Real-date verification (offline, once, against the on-disk
settlement-alignment cache -- NOT re-run by this suite; see
`docs/evidence/forecast_txn_climate_day_cli_alignment_2026-09-19.md`):
2024-12-02/2024-12-03 (MIA/MDW/SFO/LAX), 2022-03-13 (DST spring-forward),
2022-11-06 (DST fall-back) are all present as real NWS CLI FINAL records in
the on-disk settlement-alignment cache (`settlement_alignment_cache.
DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR`).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.support.forecast_climate_day_fixtures import FROZEN_FIXTURES, ForecastDayFixture

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_module(name: str) -> ModuleType:
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


def _naive_utc_day(ftime_ns: int) -> dt.date:
    """The map a careless implementer would write: the UTC calendar date of ftime.

    This is deliberately NOT imported from the frozen mapper -- it exists
    only to demonstrate what the wrong answer looks like.
    """
    return dt.datetime.fromtimestamp(ftime_ns // 10**9, tz=dt.UTC).date()


def _observed_row(phenomenon: str) -> ForecastDayFixture:
    matches = [row for row in FROZEN_FIXTURES if row.phenomenon == phenomenon and row.provenance == "observed"]
    assert len(matches) >= 1, f"no observed-provenance row for phenomenon={phenomenon!r}"
    return matches[0]


def _call(mapper: ModuleType, row: ForecastDayFixture) -> dt.date:
    return mapper.climate_day_for_txn(  # type: ignore[no-any-return]
        icao=row.icao,
        runtime_ns=row.runtime_ns,
        ftime_ns=row.ftime_ns,
        std_utc_offset_hours=row.std_utc_offset_hours,
        model=row.model,
    )


# ---------------------------------------------------------------------------
# Fixture 1: MIA bleed (real 2024-12-02/03)
# ---------------------------------------------------------------------------


def test_mia_bleed_observed_row_is_grounded_in_a_real_archived_day() -> None:
    row = _observed_row("mia_period_end_bleed")
    assert row.icao == "KMIA"
    assert row.expected_climate_day == dt.date(2024, 12, 2)
    assert row.expected_utc_naive_day == dt.date(2024, 12, 3)


def test_mia_bleed_naive_utc_map_disagrees_with_the_frozen_map() -> None:
    row = _observed_row("mia_period_end_bleed")
    naive = _naive_utc_day(row.ftime_ns)
    assert naive == row.expected_utc_naive_day
    assert naive != row.expected_climate_day


def test_mia_bleed_frozen_map_matches_the_real_climate_day(mapper: ModuleType) -> None:
    row = _observed_row("mia_period_end_bleed")
    assert _call(mapper, row) == row.expected_climate_day


# ---------------------------------------------------------------------------
# Fixture 2: SFO/LAX PST miss (real 2024-12-02)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phenomenon", ["sfo_utc_cut_miss", "lax_utc_cut_miss"])
def test_pacific_pst_miss_observed_row_is_grounded_in_a_real_archived_day(
    phenomenon: str,
) -> None:
    row = _observed_row(phenomenon)
    assert row.icao in ("KSFO", "KLAX")
    assert row.expected_climate_day == dt.date(2024, 12, 2)
    assert row.expected_utc_naive_day == dt.date(2024, 12, 3)


@pytest.mark.parametrize("phenomenon", ["sfo_utc_cut_miss", "lax_utc_cut_miss"])
def test_pacific_pst_miss_naive_utc_map_disagrees_with_the_frozen_map(phenomenon: str) -> None:
    row = _observed_row(phenomenon)
    naive = _naive_utc_day(row.ftime_ns)
    assert naive == row.expected_utc_naive_day
    assert naive != row.expected_climate_day


@pytest.mark.parametrize("phenomenon", ["sfo_utc_cut_miss", "lax_utc_cut_miss"])
def test_pacific_pst_miss_frozen_map_matches_the_real_climate_day(
    mapper: ModuleType, phenomenon: str
) -> None:
    row = _observed_row(phenomenon)
    assert _call(mapper, row) == row.expected_climate_day


# ---------------------------------------------------------------------------
# Fixture 3: DST transition (real 2022-03-13 spring-forward, 2022-11-06 fall-back)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phenomenon", "expected_day"),
    [
        ("dst_spring_forward", dt.date(2022, 3, 13)),
        ("dst_fall_back", dt.date(2022, 11, 6)),
    ],
)
def test_dst_transition_observed_row_is_grounded_in_a_real_transition_date(
    phenomenon: str, expected_day: dt.date
) -> None:
    row = _observed_row(phenomenon)
    assert row.expected_climate_day == expected_day


@pytest.mark.parametrize("phenomenon", ["dst_spring_forward", "dst_fall_back"])
def test_dst_transition_frozen_map_matches_the_real_climate_day(
    mapper: ModuleType, phenomenon: str
) -> None:
    row = _observed_row(phenomenon)
    assert _call(mapper, row) == row.expected_climate_day


def test_dst_transition_mapping_is_identical_to_a_non_transition_day(mapper: ModuleType) -> None:
    """The frozen map takes no DST branch at all -- spring and fall must behave alike."""
    spring = _observed_row("dst_spring_forward")
    fall = _observed_row("dst_fall_back")
    assert spring.std_utc_offset_hours == fall.std_utc_offset_hours
    spring_result = _call(mapper, spring)
    fall_result = _call(mapper, fall)
    assert spring_result == spring.expected_climate_day
    assert fall_result == fall.expected_climate_day


# ---------------------------------------------------------------------------
# Every phenomenon (all 9, per the Phase-A xfail contract) has a REAL observed row
# ---------------------------------------------------------------------------


def test_every_phenomenon_has_a_real_archive_grounded_observed_row() -> None:
    all_phenomena = {row.phenomenon for row in FROZEN_FIXTURES}
    missing = [
        phenomenon
        for phenomenon in all_phenomena
        if not any(
            row.provenance == "observed" and row.phenomenon == phenomenon
            for row in FROZEN_FIXTURES
        )
    ]
    assert missing == []


def test_observed_rows_never_reuse_a_2026_placeholder_date() -> None:
    """The 2021-2025 settlement-alignment cache does not cover 2026; an
    'observed' row dated 2026 would be an unverifiable claim, not a
    measurement."""
    for row in FROZEN_FIXTURES:
        if row.provenance == "observed":
            assert row.expected_climate_day.year <= 2025, row.phenomenon
