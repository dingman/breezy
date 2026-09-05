"""RED-first suite for `settlement/family_barrier.py` (6f)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from breezy.settlement.family_barrier import FamilyBarrierRefusal, assert_family_only
from breezy.settlement.trial_scorer import ScoredTrial

_PM_PREFIX = "current_rung_hold/trial/"
_KALSHI_PREFIX = "kalshi:current_rung_hold/trial/"
_D0 = "2026-09-10"


@dataclass(frozen=True, slots=True, kw_only=True)
class _FakeManifest:
    trial_id_prefix: str
    d0_climate_day: str
    stations: tuple[str, ...]


_CENSUS = ("LAX", "MDW", "MIA", "SFO")


def _row(**overrides: Any) -> ScoredTrial:
    defaults: dict[str, Any] = {
        "trial_id": "current_rung_hold/trial/LAX/2026-09-11/0",
        "station": "LAX",
        "climate_day": "2026-09-11",
        "instrument_id": "instrument-1",
        "settlement_tmax_f": 80,
        "held": True,
        "pnl": Decimal("0.10"),
        "revision_seq": 0,
        "raw_sha256": "deadbeef",
        "scored_at_ns": 1,
        "score_seq": 0,
        "settlement_basis": "nws_final",
        "excluded_reason": None,
        "slippage": Decimal(0),
        "entry_ask": Decimal("0.5"),
        "fill_px": Decimal("0.5"),
        "fee": Decimal("0.02"),
    }
    defaults.update(overrides)
    return ScoredTrial(**defaults)


def _pm_manifest(**overrides: Any) -> _FakeManifest:
    defaults: dict[str, Any] = {
        "trial_id_prefix": _PM_PREFIX,
        "d0_climate_day": _D0,
        "stations": _CENSUS,
    }
    defaults.update(overrides)
    return _FakeManifest(**defaults)


def test_a_row_on_or_after_d0_with_the_right_prefix_passes() -> None:
    rows = (_row(climate_day=_D0), _row(climate_day="2026-09-11"))
    assert_family_only(rows, _pm_manifest())  # non-vacuity: no raise


def test_a_row_before_d0_is_refused() -> None:
    rows = (_row(climate_day="2026-09-09"),)
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only(rows, _pm_manifest())


def test_a_v1_prefixed_row_before_d0_is_refused_the_v1_through_v2_case() -> None:
    rows = (
        _row(
            trial_id="current_rung_hold/trial/LAX/2026-08-01/0",
            climate_day="2026-08-01",
        ),
    )
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only(rows, _pm_manifest())


def test_a_kalshi_prefixed_row_in_a_pm_manifest_is_refused() -> None:
    rows = (
        _row(
            trial_id="kalshi:current_rung_hold/trial/LAX/2026-09-11/0",
            climate_day="2026-09-11",
        ),
    )
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only(rows, _pm_manifest())


def test_symmetric_a_pm_prefixed_row_in_a_kalshi_manifest_is_refused() -> None:
    rows = (_row(trial_id="current_rung_hold/trial/LAX/2026-09-11/0", climate_day="2026-09-11"),)
    kalshi_manifest = _pm_manifest(trial_id_prefix=_KALSHI_PREFIX)
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only(rows, kalshi_manifest)


def test_the_same_rows_pass_against_a_matching_manifest_non_vacuity() -> None:
    rows = (
        _row(
            trial_id="kalshi:current_rung_hold/trial/LAX/2026-09-11/0",
            climate_day="2026-09-11",
        ),
    )
    kalshi_manifest = _pm_manifest(trial_id_prefix=_KALSHI_PREFIX)
    assert_family_only(rows, kalshi_manifest)  # no raise


def test_one_bad_row_refuses_the_whole_batch_not_a_silent_partial_drop() -> None:
    rows = (
        _row(climate_day="2026-09-11"),
        _row(climate_day="2026-09-01"),  # before D0
        _row(climate_day="2026-09-12"),
    )
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only(rows, _pm_manifest())


def test_a_row_exactly_at_d0_is_not_refused_boundary_inclusive() -> None:
    rows = (_row(climate_day=_D0),)
    assert_family_only(rows, _pm_manifest())  # no raise


# --- B2: station census -----------------------------------------------------


def test_a_row_from_a_station_outside_the_census_is_refused() -> None:
    rows = (_row(station="NYC", climate_day="2026-09-11"),)
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only(rows, _pm_manifest())


def test_an_in_census_row_passes_non_vacuity() -> None:
    rows = (_row(station="LAX", climate_day="2026-09-11"),)
    assert_family_only(rows, _pm_manifest())  # no raise


def test_one_off_census_row_refuses_the_whole_batch_not_a_silent_partial_drop() -> None:
    rows = (
        _row(station="LAX", climate_day="2026-09-11"),
        _row(station="NYC", climate_day="2026-09-11"),
        _row(station="SFO", climate_day="2026-09-12"),
    )
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only(rows, _pm_manifest())
