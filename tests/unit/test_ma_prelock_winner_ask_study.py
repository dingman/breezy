"""Unit tests for M_A -- the pre-lock winner-ask afternoon measurement.

Grok's design memo (`docs/evidence/grok_no_edge_verdict_2026-09-02.md` SS2/SS3)
specifies the single remaining read-only measurement before strategy spend on
this book class stops: per dense station-day, at every Depth10 snapshot in
local-standard 12:00-17:00, is the WINNER rung's ask ever inside (0.05, 0.95)
while R(t) sits inside the winner rung? These tests cover the pure logic --
window membership, the qualifying-cell test, coverage-minute gating, and the
PENDING/SCORED split -- with small synthetic fixtures. No catalog, no
network, no Nautilus data types.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_MDW_STD_OFFSET_HOURS = -6.0  # UTC-6, no DST -- local standard time all year.
_CLIMATE_DAY = dt.date(2026, 8, 31)


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "ma_prelock_winner_ask_study.py"
    spec = importlib.util.spec_from_file_location("ma_prelock_winner_ask_study", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ma(ma_h4_dependency: None) -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def ma_h4_dependency() -> None:
    # Ensure the sibling analysis module this one imports from is importable
    # under the same synthetic sys.path shim the h4 test suite uses.
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))


def _lst_to_utc(hour: int, minute: int) -> dt.datetime:
    tz = dt.timezone(dt.timedelta(hours=_MDW_STD_OFFSET_HOURS))
    local = dt.datetime.combine(_CLIMATE_DAY, dt.time(hour, minute), tzinfo=tz)
    return local.astimezone(dt.UTC)


def _winner_rung(ma: ModuleType) -> Any:
    ladder = ma.parse_ladder(
        [
            "tc-temp-mdwhigh-2026-08-31-lt89f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte89lt90f.POLYMARKET_US",
            "tc-temp-mdwhigh-2026-08-31-gte91lt92f.POLYMARKET_US",
        ]
    )
    return ma.rung_containing(ladder, 89)  # the gte89lt90f rung


def _depth_row(
    ma: ModuleType,
    *,
    instrument_id: str,
    hour: int,
    minute: int,
    ask: tuple[float, float] | None,
) -> Any:
    return ma.DepthObservation(
        instrument_id=instrument_id,
        ts_event=_lst_to_utc(hour, minute),
        best_ask=None if ask is None else ask[0],
        ask_ladder=None if ask is None else (ask,),
        best_bid=None,
    )


def _running_series_flat_at_89(ma: ModuleType) -> tuple[tuple[dt.datetime, int], ...]:
    # R(t) already at 89F by 06:00 LST and never rises again this day --
    # so it sits inside the winner rung [89, 90] through the whole afternoon.
    return ((_lst_to_utc(6, 0), 89),)


# ---------------------------------------------------------------------------
# (1) offered at 0.60 mid-afternoon while R(t) is in-rung -- MUST count
# ---------------------------------------------------------------------------


def test_winner_offered_mid_afternoon_in_rung_is_a_qualifying_cell(ma: ModuleType) -> None:
    winner = _winner_rung(ma)
    series = _running_series_flat_at_89(ma)
    depth = [_depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.60, 5.0))]

    snapshots = ma.build_afternoon_snapshots(
        winner_rung=winner,
        winner_depth=depth,
        series=series,
        climate_day=_CLIMATE_DAY,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
    )
    assert len(snapshots) == 1
    assert snapshots[0].in_rung is True
    assert snapshots[0].m == 0

    cells = ma.qualifying_cells(snapshots)
    assert len(cells) == 1
    assert cells[0].ask_px == pytest.approx(0.60)


# ---------------------------------------------------------------------------
# (2) offered only at 0.99 -- MUST NOT count as a qualifying cell
# ---------------------------------------------------------------------------


def test_winner_offered_only_at_099_is_not_a_qualifying_cell(ma: ModuleType) -> None:
    winner = _winner_rung(ma)
    series = _running_series_flat_at_89(ma)
    depth = [
        _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.99, 300.0))
    ]

    snapshots = ma.build_afternoon_snapshots(
        winner_rung=winner,
        winner_depth=depth,
        series=series,
        climate_day=_CLIMATE_DAY,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
    )
    cells = ma.qualifying_cells(snapshots)
    assert cells == ()

    first_high = ma.first_ask_at_or_above(snapshots)
    assert first_high == snapshots[0].ts_lst


def test_first_ask_vanish_reports_the_first_absent_snapshot(ma: ModuleType) -> None:
    winner = _winner_rung(ma)
    series = _running_series_flat_at_89(ma)
    depth = [
        _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.60, 5.0)),
        _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=5, ask=None),
        _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=10, ask=None),
    ]

    snapshots = ma.build_afternoon_snapshots(
        winner_rung=winner,
        winner_depth=depth,
        series=series,
        climate_day=_CLIMATE_DAY,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
    )
    vanish = ma.first_ask_vanish(snapshots)
    assert vanish == snapshots[1].ts_lst


# ---------------------------------------------------------------------------
# (3) 20 minutes of coverage -- MUST NOT count toward n_afternoon
# ---------------------------------------------------------------------------


def test_short_coverage_window_does_not_count_toward_n_afternoon(ma: ModuleType) -> None:
    winner = _winner_rung(ma)
    depth = {
        winner.instrument_id: (
            _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.60, 5.0)),
            _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=20, ask=(0.60, 5.0)),
        )
    }
    instants = ma.collect_window_instants(
        depth, climate_day=_CLIMATE_DAY, std_utc_offset_hours=_MDW_STD_OFFSET_HOURS
    )
    coverage = ma.afternoon_coverage_minutes(instants)
    assert coverage == pytest.approx(20.0)

    summary = ma.StationDaySummary(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        status="SCORED",
        winner_instrument_id=winner.instrument_id,
        settled_tmax_f=89,
        afternoon_coverage_minutes=coverage,
        afternoon_snapshot_count=2,
        qualifying=(),
        min_ask=0.60,
        size_at_min_ask=5.0,
        first_ask_vanish_lst=None,
        first_ask_ge_099_lst=None,
    )
    verdict = ma.evaluate_family_a([summary])
    assert verdict.n_afternoon == 0
    assert summary.afternoon_covered is False


def test_thirty_minute_coverage_window_does_count(ma: ModuleType) -> None:
    winner = _winner_rung(ma)
    depth = {
        winner.instrument_id: (
            _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.60, 5.0)),
            _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=30, ask=(0.60, 5.0)),
        )
    }
    instants = ma.collect_window_instants(
        depth, climate_day=_CLIMATE_DAY, std_utc_offset_hours=_MDW_STD_OFFSET_HOURS
    )
    coverage = ma.afternoon_coverage_minutes(instants)
    assert coverage == pytest.approx(30.0)

    summary = ma.StationDaySummary(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        status="SCORED",
        winner_instrument_id=winner.instrument_id,
        settled_tmax_f=89,
        afternoon_coverage_minutes=coverage,
        afternoon_snapshot_count=2,
        qualifying=(),
        min_ask=0.60,
        size_at_min_ask=5.0,
        first_ask_vanish_lst=None,
        first_ask_ge_099_lst=None,
    )
    assert summary.afternoon_covered is True


# ---------------------------------------------------------------------------
# (4) a PENDING CLI must be PENDING, never scored
# ---------------------------------------------------------------------------


def test_station_day_without_a_final_cli_is_pending_not_scored(ma: ModuleType) -> None:
    winner = _winner_rung(ma)
    ladder = (winner,)
    depth = {
        winner.instrument_id: (
            _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.60, 5.0)),
        )
    }
    series = _running_series_flat_at_89(ma)

    summary = ma.build_station_day_summary(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        ladder=ladder,
        depth=depth,
        series=series,
        settled_tmax_f=None,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
    )
    assert summary.status == "PENDING"
    assert summary.winner_instrument_id is None
    assert summary.qualifying == ()

    verdict = ma.evaluate_family_a([summary])
    assert verdict.n_afternoon == 0
    assert verdict.qualifying_count == 0


def test_station_day_with_a_final_cli_is_scored(ma: ModuleType) -> None:
    winner = _winner_rung(ma)
    ladder = (winner,)
    depth = {
        winner.instrument_id: (
            _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.60, 5.0)),
            _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=30, ask=(0.60, 5.0)),
        )
    }
    series = _running_series_flat_at_89(ma)

    summary = ma.build_station_day_summary(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        ladder=ladder,
        depth=depth,
        series=series,
        settled_tmax_f=89,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
    )
    assert summary.status == "SCORED"
    assert summary.winner_instrument_id == winner.instrument_id
    assert len(summary.qualifying) == 2
    assert summary.min_ask == pytest.approx(0.60)
    assert summary.size_at_min_ask == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# K-depth: level-0 size < 1.0 contract at the recorded ask is unexecutable
# ---------------------------------------------------------------------------


def test_k_depth_flags_a_sub_one_contract_qualifying_ask_as_unexecutable(
    ma: ModuleType,
) -> None:
    winner = _winner_rung(ma)
    series = _running_series_flat_at_89(ma)
    depth = [
        _depth_row(ma, instrument_id=winner.instrument_id, hour=13, minute=0, ask=(0.60, 0.3)),
    ]
    snapshots = ma.build_afternoon_snapshots(
        winner_rung=winner,
        winner_depth=depth,
        series=series,
        climate_day=_CLIMATE_DAY,
        std_utc_offset_hours=_MDW_STD_OFFSET_HOURS,
    )
    summary = ma.StationDaySummary(
        city="MDW",
        climate_day=_CLIMATE_DAY,
        status="SCORED",
        winner_instrument_id=winner.instrument_id,
        settled_tmax_f=89,
        afternoon_coverage_minutes=30.0,
        afternoon_snapshot_count=1,
        qualifying=ma.qualifying_cells(snapshots),
        min_ask=0.60,
        size_at_min_ask=0.3,
        first_ask_vanish_lst=None,
        first_ask_ge_099_lst=None,
    )
    assert len(summary.unexecutable) == 1
    assert summary.unexecutable[0].ask_sz == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# K-A verdict aggregation
# ---------------------------------------------------------------------------


def test_k_a_verdict_is_underpowered_below_fifteen_afternoon_days(ma: ModuleType) -> None:
    summaries = [
        ma.StationDaySummary(
            city="MDW",
            climate_day=_CLIMATE_DAY,
            status="SCORED",
            winner_instrument_id="x",
            settled_tmax_f=89,
            afternoon_coverage_minutes=45.0,
            afternoon_snapshot_count=3,
            qualifying=(),
            min_ask=0.01,
            size_at_min_ask=10.0,
            first_ask_vanish_lst=None,
            first_ask_ge_099_lst=None,
        )
    ]
    verdict = ma.evaluate_family_a(summaries)
    assert verdict.outcome == "UNDERPOWERED"
    assert verdict.n_afternoon == 1


def test_k_a_verdict_is_family_a_dead_at_fifteen_days_with_zero_qualifying_cells(
    ma: ModuleType,
) -> None:
    summaries = [
        ma.StationDaySummary(
            city=f"S{i}",
            climate_day=_CLIMATE_DAY,
            status="SCORED",
            winner_instrument_id="x",
            settled_tmax_f=89,
            afternoon_coverage_minutes=45.0,
            afternoon_snapshot_count=3,
            qualifying=(),
            min_ask=0.01,
            size_at_min_ask=10.0,
            first_ask_vanish_lst=None,
            first_ask_ge_099_lst=None,
        )
        for i in range(15)
    ]
    verdict = ma.evaluate_family_a(summaries)
    assert verdict.outcome == "FAMILY_A_DEAD"
    assert verdict.n_afternoon == 15
    assert verdict.qualifying_count == 0
