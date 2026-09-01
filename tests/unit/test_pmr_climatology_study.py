"""Unit tests for the late-rise-hazard climatology study.

These tests cover the pure logic in
``scripts/analysis/pmr_climatology_study.py``: the local-standard-time
climate-day/hour assignment, the running-maximum accumulation, the 2F rung
floor/ceiling/headroom arithmetic, the bucket-crossing predicate, the CLI
time-of-maximum extraction and the Wilson bounds.

They never touch the network or the IEM archive cache -- every fixture is
synthetic. The study itself is an OFFLINE PHYSICAL MEASUREMENT over historical
NWS observations: it produces a table of conditional probabilities as a MODEL
INPUT. It never simulates a trade, a fill, or a P&L, and nothing here asserts
on one.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

# LAX/NYC standard offsets, read from `src/breezy/registry/sites.toml`. The
# study itself never hardcodes these -- it reads the registry via
# `settlement_alignment_study.load_sites()`. They are literals HERE so the
# boundary test states the offset it is asserting about.
_LAX_STD_OFFSET_HOURS = -8.0
_NYC_STD_OFFSET_HOURS = -5.0


def _load_study_module() -> ModuleType:
    # The study does bare `from settlement_alignment_study import ...` (the
    # same passthrough convention settlement_bucket_gate.py uses), so
    # scripts/analysis must be importable as a top-level module directory
    # before we exec the study module itself.
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "pmr_climatology_study.py"
    spec = importlib.util.spec_from_file_location("pmr_climatology_study", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return _load_study_module()


def _metar_row(*, station: str, valid: str, t_group: str) -> dict[str, str]:
    """A single IEM ASOS CSV row in the cached archive's exact column shape."""
    return {
        "station": station,
        "valid": valid,
        "metar": f"K{station} 010000Z AUTO 25009KT 10SM CLR 15/07 A3015 RMK AO2 {t_group}",
    }


def _f_to_t_group(temp_c_tenths: int) -> str:
    sign = "1" if temp_c_tenths < 0 else "0"
    return f"T{sign}{abs(temp_c_tenths):03d}{sign}{abs(temp_c_tenths):03d}"


def _days(
    study: ModuleType,
    *,
    city: str,
    std_utc_offset_hours: float,
    rows: list[dict[str, str]],
) -> tuple[Any, ...]:
    temperatures, drops = study.metar_temperatures(
        city=city,
        rows=rows,
        std_utc_offset_hours=std_utc_offset_hours,
    )
    assert not drops, f"fixture rows failed to parse: {drops}"
    days: tuple[Any, ...] = study.build_running_max_days(
        city=city,
        temperatures=temperatures,
        std_utc_offset_hours=std_utc_offset_hours,
    )
    return days



def _one_complete_day(
    study: ModuleType,
    *,
    tenths: int,
    city: str = "LAX",
    std_utc_offset_hours: float = _LAX_STD_OFFSET_HOURS,
    climate_day: dt.date = dt.date(2025, 1, 15),
) -> Any:
    """A flat 24-hour climate day, complete in every local-standard hour."""
    midnight_utc = dt.datetime.combine(
        climate_day, dt.time(0, 0), tzinfo=dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    ).astimezone(dt.UTC)
    rows = [
        _metar_row(
            station=city,
            valid=(midnight_utc + dt.timedelta(hours=hour)).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(tenths),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city=city, std_utc_offset_hours=std_utc_offset_hours, rows=rows)
    return day

# ---------------------------------------------------------------------------
# METAR T-group parsing -- shared with settlement_alignment_study, never forked
# ---------------------------------------------------------------------------


def test_metar_t_group_parser_is_the_shared_settlement_alignment_parser(
    study: ModuleType,
) -> None:
    """The study must REUSE the existing METAR parser, not fork a second one."""
    import settlement_alignment_study

    assert study.parse_metar_t_group is settlement_alignment_study.parse_metar_t_group
    assert study.METAR_T_RE is settlement_alignment_study.METAR_T_RE


def test_parse_metar_t_group_reads_a_known_positive_reading(study: ModuleType) -> None:
    raw = "KNYC 310051Z AUTO 22010G23KT 180V250 10SM SCT090 06/M03 A3015 RMK AO2 SLP201 T00561033 $"

    assert study.parse_metar_t_group(raw) == 56
    assert study.round_half_up_f(56) == 42


def test_parse_metar_t_group_reads_a_known_sub_zero_reading(study: ModuleType) -> None:
    raw = "KMDW 310000Z AUTO 28013KT 10SM BKN018 M03/M07 A3002 RMK T10301070 MADISHF"

    assert study.parse_metar_t_group(raw) == -30
    assert study.round_half_up_f(-30) == 27


def test_parse_metar_t_group_returns_none_when_no_t_group_is_present(
    study: ModuleType,
) -> None:
    assert study.parse_metar_t_group("KLAX 310000Z AUTO 25009KT 10SM CLR 15/07 A3015") is None


# ---------------------------------------------------------------------------
# Climate-day boundary -- local STANDARD time, never DST, never UTC
# ---------------------------------------------------------------------------


def test_climate_day_boundary_matches_climate_day_end_ns_at_lax_under_dst(
    study: ModuleType,
) -> None:
    """LAX in July is on PDT, but the climate day runs on PST year-round.

    `_climate_day_end_ns` is the repo's settlement-path definition. The study
    must land on the SAME instant. A `ZoneInfo("America/Los_Angeles")`
    implementation would roll the day over an hour early (07:00Z, not 08:00Z)
    and silently shift every hour bucket in the table.
    """
    from breezy.ingest.records import _climate_day_end_ns

    climate_day = dt.date(2025, 7, 4)
    end_ns = _climate_day_end_ns(climate_day, _LAX_STD_OFFSET_HOURS)
    boundary_utc = dt.datetime.fromtimestamp(end_ns / 1_000_000_000, tz=dt.UTC)

    assert boundary_utc == dt.datetime(2025, 7, 5, 8, 0, tzinfo=dt.UTC)

    last_instant = boundary_utc - dt.timedelta(minutes=5)
    rows = [
        _metar_row(
            station="LAX",
            valid=last_instant.strftime("%Y-%m-%d %H:%M"),
            t_group="T02000200",
        ),
        _metar_row(
            station="LAX",
            valid=boundary_utc.strftime("%Y-%m-%d %H:%M"),
            t_group="T03000300",
        ),
    ]
    days = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    by_day = {day.climate_day: day for day in days}
    assert set(by_day) == {climate_day, dt.date(2025, 7, 5)}
    # The 07:55Z observation is the LAST hour (23) of the 2025-07-04 climate day.
    assert by_day[climate_day].hour_of_max == 23
    # The 08:00Z observation opens hour 0 of the NEXT climate day.
    assert by_day[dt.date(2025, 7, 5)].hour_of_max == 0


def test_climate_day_boundary_matches_climate_day_end_ns_at_nyc_under_dst(
    study: ModuleType,
) -> None:
    from breezy.ingest.records import _climate_day_end_ns

    climate_day = dt.date(2025, 7, 4)
    end_ns = _climate_day_end_ns(climate_day, _NYC_STD_OFFSET_HOURS)
    boundary_utc = dt.datetime.fromtimestamp(end_ns / 1_000_000_000, tz=dt.UTC)

    assert boundary_utc == dt.datetime(2025, 7, 5, 5, 0, tzinfo=dt.UTC)

    rows = [
        _metar_row(station="NYC", valid="2025-07-05 04:51", t_group="T02000200"),
        _metar_row(station="NYC", valid="2025-07-05 05:51", t_group="T03000300"),
    ]
    days = _days(study, city="NYC", std_utc_offset_hours=_NYC_STD_OFFSET_HOURS, rows=rows)
    by_day = {day.climate_day: day for day in days}

    assert by_day[climate_day].hour_of_max == 23
    assert by_day[dt.date(2025, 7, 5)].hour_of_max == 0


@pytest.mark.parametrize(
    ("utc_valid", "expected_hour"),
    [
        ("2025-01-15 08:00", 0),
        ("2025-01-15 20:30", 12),
        ("2025-01-16 07:59", 23),
        # Same wall-clock local-DAYLIGHT hour in July: the STANDARD hour is one
        # lower, which is exactly the aliasing this study must not commit.
        ("2025-07-15 20:30", 12),
    ],
)
def test_local_standard_hour_never_follows_daylight_saving(
    study: ModuleType, utc_valid: str, expected_hour: int
) -> None:
    instant = dt.datetime.strptime(utc_valid, "%Y-%m-%d %H:%M").replace(tzinfo=dt.UTC)

    assert study.local_standard_hour(instant, _LAX_STD_OFFSET_HOURS) == expected_hour


# ---------------------------------------------------------------------------
# Running maximum R(t) -- monotone, day-scoped, look-ahead free
# ---------------------------------------------------------------------------


def test_running_max_is_monotone_non_decreasing_within_a_climate_day(
    study: ModuleType,
) -> None:
    # A realistic diurnal shape at LAX: cool overnight, peak mid-afternoon,
    # cooling into the evening. R(t) must never fall even though T(t) does.
    tenths_by_hour = {
        0: 100, 3: 90, 6: 95, 9: 150, 12: 200, 15: 230, 18: 190, 21: 140, 23: 120
    }
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(tenths),
        )
        for hour, tenths in sorted(tenths_by_hour.items())
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    series = day.running_max_f
    assert len(series) == 24
    observed = [value for value in series if value is not None]
    assert observed == sorted(observed), f"running max fell: {series}"
    assert series[23] == day.observed_max_f == study.round_half_up_f(230)
    assert day.hour_of_max == 15


def test_running_max_resets_at_the_climate_day_boundary(study: ModuleType) -> None:
    """Day 2's running max must start from day 2's own observations only."""
    hot_day = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(300),
        )
        for hour in range(24)
    ]
    cold_day = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 16, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(50),
        )
        for hour in range(24)
    ]
    days = _days(
        study,
        city="LAX",
        std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
        rows=hot_day + cold_day,
    )
    by_day = {day.climate_day: day for day in days}

    hot = by_day[dt.date(2025, 1, 15)]
    cold = by_day[dt.date(2025, 1, 16)]

    assert hot.running_max_f[0] == study.round_half_up_f(300)
    # The reset: the cold day's hour-0 running max is its OWN reading, not the
    # previous day's 30.0C carried across the boundary.
    assert cold.running_max_f[0] == study.round_half_up_f(50)
    assert cold.running_max_f[23] == study.round_half_up_f(50)
    assert cold.observed_max_f < hot.observed_max_f


def test_no_observation_after_t_influences_the_running_max_at_t(
    study: ModuleType,
) -> None:
    """Truncating the day at hour h must not change R(0..h). No look-ahead."""
    all_rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(100 + 10 * hour),
        )
        for hour in range(24)
    ]
    (full_day,) = _days(
        study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=all_rows
    )

    for cutoff in range(24):
        (truncated,) = _days(
            study,
            city="LAX",
            std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
            rows=all_rows[: cutoff + 1],
        )
        assert truncated.running_max_f[: cutoff + 1] == full_day.running_max_f[: cutoff + 1], (
            f"observations after hour {cutoff} leaked into R(t<={cutoff})"
        )


def test_running_max_is_none_for_hours_before_the_first_observation(
    study: ModuleType,
) -> None:
    rows = [
        _metar_row(station="LAX", valid="2025-01-15 20:00", t_group=_f_to_t_group(150)),
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    assert day.running_max_f[:12] == (None,) * 12
    assert day.running_max_f[12] == study.round_half_up_f(150)
    assert day.covered_hours == 1
    assert not study.is_complete_day(day)


def test_a_day_with_an_observation_in_every_local_hour_is_complete(
    study: ModuleType,
) -> None:
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(100),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    assert day.covered_hours == 24
    assert day.observation_count == 24
    assert study.is_complete_day(day)


def test_hour_of_max_is_the_first_hour_attaining_the_daily_maximum(
    study: ModuleType,
) -> None:
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(250 if hour in (14, 18) else 100),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    assert day.hour_of_max == 14


# ---------------------------------------------------------------------------
# 2F bucket arithmetic and the crossing predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value_f", "expected_floor", "expected_margin"),
    [
        (84, 84, 0),
        (85, 84, 1),
        (86, 86, 0),
        (0, 0, 0),
        (-1, -2, 1),
        (-2, -2, 0),
        (-3, -4, 1),
    ],
)
def test_bucket_floor_and_margin_use_the_repo_two_degree_bucket_width(
    study: ModuleType, value_f: int, expected_floor: int, expected_margin: int
) -> None:
    assert study.BUCKET_WIDTH_F == 2.0
    assert study.bucket_floor_f(value_f) == expected_floor
    assert study.margin_f(value_f) == expected_margin


@pytest.mark.parametrize(
    ("running_f", "settled_f", "expected"),
    [
        # margin 0, +1F: still inside the same 2F bucket -- harmless.
        (84, 85, False),
        # margin 0, +2F: crosses out of [84,86).
        (84, 86, True),
        # margin 1, +1F: crosses immediately.
        (85, 86, True),
        # no rise at all.
        (85, 85, False),
        # a big late rise.
        (84, 97, True),
    ],
)
def test_bucket_crossing_predicate(
    study: ModuleType, running_f: int, settled_f: int, expected: bool
) -> None:
    assert study.crosses_bucket(running_f=running_f, settled_f=settled_f) is expected


def test_settled_below_running_is_a_negative_basis_never_a_crossing(
    study: ModuleType,
) -> None:
    """M < R(t) is impossible on the observation basis and REAL on the CLI one.

    Settlement is the CLI integer while R(t) is ASOS-derived, so the settled
    value legitimately lands below the running max. That is a negative basis,
    not a crossing, and it must never inflate the crossing count.
    """
    assert study.crosses_bucket(running_f=85, settled_f=80) is False

    day = _one_complete_day(study, tenths=289)
    cases = study.build_exceedance_cases(day=day, settled_f=day.observed_max_f - 4)

    assert not any(case.crosses_bucket for case in cases)
    assert not any(case.exceeds for case in cases)
    assert all(case.gain_f == -4 for case in cases)

    table = study.aggregate(cases)
    assert sum(cell.negative_basis_count for cell in table.values()) == len(cases)
    assert sum(cell.cross_count for cell in table.values()) == 0


# ---------------------------------------------------------------------------
# Exceedance cases -- the statistic itself
# ---------------------------------------------------------------------------


def test_exceedance_cases_cover_every_hour_with_an_observation(
    study: ModuleType,
) -> None:
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            # Peaks at hour 14 (85F-ish), so hours >= 14 have no exceedance.
            t_group=_f_to_t_group(100 + 10 * min(hour, 14)),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)
    cases = study.build_exceedance_cases(day=day, settled_f=day.observed_max_f)

    assert len(cases) == 24
    assert [case.hour for case in cases] == list(range(24))
    assert all(case.city == "LAX" for case in cases)
    assert all(case.season == "DJF" for case in cases)
    # Strictly rising through hour 14, so every earlier hour is exceeded.
    assert all(case.exceeds for case in cases if case.hour < 14)
    assert not any(case.exceeds for case in cases if case.hour >= 14)
    assert cases[13].gain_f == day.observed_max_f - day.running_max_f[13]
    assert cases[23].gain_f == 0


def test_exceedance_case_margin_is_measured_off_the_running_max_not_the_settled_max(
    study: ModuleType,
) -> None:
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(289 if hour >= 12 else 283),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)
    cases = {case.hour: case for case in study.build_exceedance_cases(
        day=day, settled_f=day.observed_max_f
    )}

    # 28.3C -> 82.94F -> 83 (margin 1); 28.9C -> 84.02F -> 84 (margin 0).
    assert day.running_max_f[0] == 83
    assert day.observed_max_f == 84
    assert cases[0].margin_f == study.margin_f(83) == 1
    assert cases[12].margin_f == study.margin_f(84) == 0
    assert cases[0].crosses_bucket is True
    assert cases[12].crosses_bucket is False


@pytest.mark.parametrize(
    ("month", "expected"),
    [(1, "DJF"), (2, "DJF"), (3, "MAM"), (5, "MAM"), (6, "JJA"), (8, "JJA"),
     (9, "SON"), (11, "SON"), (12, "DJF")],
)
def test_season_for_partitions_the_year_into_four_meteorological_seasons(
    study: ModuleType, month: int, expected: str
) -> None:
    assert study.season_for(dt.date(2025, month, 15)) == expected


def test_exceedance_cases_are_not_built_for_an_incomplete_day(
    study: ModuleType,
) -> None:
    rows = [_metar_row(station="LAX", valid="2025-01-15 20:00", t_group=_f_to_t_group(150))]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    with pytest.raises(ValueError, match="complete"):
        study.build_exceedance_cases(day=day, settled_f=day.observed_max_f)


# ---------------------------------------------------------------------------
# Wilson bounds -- upper is the conservative direction for this decision
# ---------------------------------------------------------------------------


def test_wilson_bounds_are_the_shared_archive_probe_implementation(
    study: ModuleType,
) -> None:
    import archive_correction_probe

    assert study.wilson_interval is archive_correction_probe.wilson_interval


def test_wilson_upper_bound_exceeds_the_point_estimate_and_shrinks_with_n(
    study: ModuleType,
) -> None:
    small = study.wilson_upper(0, 12)
    large = study.wilson_upper(0, 12_000)

    assert 0.0 < large < small < 1.0
    # For phat == 0 the Wilson upper root is exactly z**2 / (n + z**2).
    z_squared = 1.959963984540054 ** 2
    assert small == pytest.approx(z_squared / (12 + z_squared), abs=1e-12)
    assert small == pytest.approx(0.242494, abs=1e-6)
    assert study.wilson_upper(1, 100) > 1 / 100


def test_wilson_upper_bound_of_a_zero_denominator_cell_is_undefined(
    study: ModuleType,
) -> None:
    assert study.wilson_upper(0, 0) is None


# ---------------------------------------------------------------------------
# Aggregation -- every denominator is carried, never dropped
# ---------------------------------------------------------------------------


def test_aggregate_carries_every_denominator(study: ModuleType) -> None:
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(100 + 10 * hour),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)
    cases = study.build_exceedance_cases(day=day, settled_f=day.observed_max_f)

    table = study.aggregate(cases)

    assert sum(cell.n for cell in table.values()) == len(cases)
    for key, cell in table.items():
        city, season, hour, margin = key
        assert city == "LAX"
        assert season == "DJF"
        assert 0 <= hour <= 23
        assert margin in (0, 1)
        assert cell.n >= 1
        assert 0 <= cell.exceed_count <= cell.n
        assert cell.cross_count <= cell.exceed_count


# ---------------------------------------------------------------------------
# Headroom -- the PRIMARY conditioning variable, and the loss event it defines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value_f", "expected_floor", "expected_upper", "expected_margin", "expected_headroom"),
    [
        (78, 78, 79, 0, 1),
        (79, 78, 79, 1, 0),
        (80, 80, 81, 0, 1),
        (0, 0, 1, 0, 1),
        (-1, -2, -1, 1, 0),
        (-2, -2, -1, 0, 1),
    ],
)
def test_rung_is_a_closed_two_degree_interval_and_headroom_is_its_complement(
    study: ModuleType,
    value_f: int,
    expected_floor: int,
    expected_upper: int,
    expected_margin: int,
    expected_headroom: int,
) -> None:
    """Interiors settle a CLOSED `[A, A+1]`, so `upper_f = A + 1` is the last
    value that still settles YES -- and `headroom = upper_f - R` is `1 - margin`."""
    assert study.bucket_floor_f(value_f) == expected_floor
    assert study.bucket_upper_f(value_f) == expected_upper
    assert study.margin_f(value_f) == expected_margin
    assert study.headroom_f(value_f) == expected_headroom
    assert study.headroom_f(value_f) + study.margin_f(value_f) == 1


def test_the_loss_event_is_m_above_the_rung_ceiling_not_m_above_the_running_max(
    study: ModuleType,
) -> None:
    """R=78 inside [78,79]: a 1F late rise still pays. R=79: it does not."""
    assert study.headroom_f(78) == 1
    assert study.crosses_bucket(running_f=78, settled_f=79) is False
    assert study.crosses_bucket(running_f=78, settled_f=80) is True

    assert study.headroom_f(79) == 0
    assert study.crosses_bucket(running_f=79, settled_f=80) is True


def test_aggregate_keys_on_headroom_and_never_pools_the_two(study: ModuleType) -> None:
    """A pooled pass that fires at the ceiling is a fail -- the table must keep
    headroom 0 and headroom 1 in separate cells."""
    # 25.0C -> 77.0F -> 77 (headroom 0); 26.1C -> 78.98F -> 79 (headroom 0);
    # 25.6C -> 78.08F -> 78 (headroom 1).
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(256 if hour < 12 else 261),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)
    assert day.running_max_f[0] == 78
    assert day.observed_max_f == 79

    table = study.aggregate(study.build_exceedance_cases(day=day, settled_f=79))
    headrooms = {key[3] for key in table}

    assert headrooms == {0, 1}
    morning = table[("LAX", "DJF", 0, 1)]
    afternoon = table[("LAX", "DJF", 12, 0)]
    # R=78, M=79: exceeds, but stays inside [78,79] -- NOT a loss.
    assert morning.exceed_count == morning.n == 1
    assert morning.cross_count == 0
    # R=79 already on the ceiling: no exceedance at all here.
    assert afternoon.cross_count == 0


# ---------------------------------------------------------------------------
# CLI time-of-maximum -- the field Breezy's production parser discards
# ---------------------------------------------------------------------------


_CLI_FINAL_FIXTURE = """
506
CDUS43 KLOT 242145
CLIMDW

CLIMATE REPORT
NATIONAL WEATHER SERVICE CHICAGO IL
445 PM CDT MON AUG 24 2026

...................................

...THE CHICAGO-MIDWAY CLIMATE SUMMARY FOR AUGUST 24 2026...

WEATHER ITEM   OBSERVED TIME   RECORD YEAR NORMAL DEPARTURE LAST
                VALUE   (LST)  VALUE       VALUE  FROM      YEAR
...................................................................
TEMPERATURE (F)
 YESTERDAY
  MAXIMUM         79   1:44 PM 100    1947  82     -3       75
                                      2023
  MINIMUM         58   5:40 AM  48    1942  66     -8       60
  AVERAGE         69                        74     -5       68

PRECIPITATION (IN)
  TODAY            0.00          1.20 2006   0.13  -0.13     0.00
"""


def test_parse_cli_max_time_reads_the_observed_maximums_stated_time(
    study: ModuleType,
) -> None:
    parsed = study.parse_cli_max_time(_CLI_FINAL_FIXTURE)

    assert parsed is not None
    assert (parsed.hour, parsed.minute) == (13, 44)


def test_parse_cli_max_time_anchors_on_the_observed_subsection_not_a_record_block(
    study: ModuleType,
) -> None:
    """The TEMPERATURE (F) block also carries RECORD/NORMAL sub-blocks with
    their own MAXIMUM rows. Reading one of those is a silent mis-parse."""
    hostile = _CLI_FINAL_FIXTURE.replace(
        "TEMPERATURE (F)\n YESTERDAY",
        "TEMPERATURE (F)\n RECORD\n  MAXIMUM        100   3:30 AM\n\n YESTERDAY",
    )

    parsed = study.parse_cli_max_time(hostile)

    assert parsed is not None
    assert (parsed.hour, parsed.minute) == (13, 44)


def test_parse_cli_max_time_returns_none_when_the_product_prints_no_time(
    study: ModuleType,
) -> None:
    timeless = _CLI_FINAL_FIXTURE.replace("  MAXIMUM         79   1:44 PM", "  MAXIMUM         MM")

    assert study.parse_cli_max_time(timeless) is None


def test_parse_cli_max_time_never_reads_the_minimum_rows_time(study: ModuleType) -> None:
    """`[ \\t]` not `\\s`: a newline-spanning gap would let 5:40 AM be read as
    the maximum's time on any product whose MAXIMUM row omits one."""
    timeless = _CLI_FINAL_FIXTURE.replace("  MAXIMUM         79   1:44 PM", "  MAXIMUM         79")

    assert study.parse_cli_max_time(timeless) is None


@pytest.mark.parametrize(
    ("printed", "expected_hour"),
    [("12:05 AM", 0), ("12:05 PM", 12), ("1:44 PM", 13), ("11:59 PM", 23), ("6:00 AM", 6)],
)
def test_parse_cli_max_time_converts_twelve_hour_clock_to_hour_of_day(
    study: ModuleType, printed: str, expected_hour: int
) -> None:
    product = _CLI_FINAL_FIXTURE.replace("1:44 PM", printed)

    parsed = study.parse_cli_max_time(product)

    assert parsed is not None
    assert parsed.hour == expected_hour


# ---------------------------------------------------------------------------
# The known fat tail -- flagged and KEPT, never filtered
# ---------------------------------------------------------------------------


def test_an_unflagged_bad_cli_final_is_reported_and_not_dropped(
    study: ModuleType,
) -> None:
    """MDW 2021-12-30 shape: `MAXIMUM 55  7:11 AM` against an ASOS day topping
    out near 39F, carrying no correction marker at all."""
    climate_day = dt.date(2021, 12, 30)
    day = _one_complete_day(study, tenths=39, city="MDW", std_utc_offset_hours=-6.0,
                            climate_day=climate_day)
    assert day.observed_max_f == 39

    final = study.CliRecord(
        city="MDW",
        climate_day=climate_day,
        issuance="FINAL",
        tmax_f=55,
        tmax_sentinel="NONE",
        max_time=study.CliMaxTime(hour=7, minute=11),
        is_correction_bbb=False,
        issued_at_utc=None,
        source="fixture",
    )
    temperatures, _ = study.metar_temperatures(
        city="MDW",
        rows=[
            _metar_row(
                station="MDW",
                valid=(
                    dt.datetime(2021, 12, 30, 6, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
                ).strftime("%Y-%m-%d %H:%M"),
                t_group=_f_to_t_group(39),
            )
            for hour in range(24)
        ],
        std_utc_offset_hours=-6.0,
    )

    flagged, _ = study.implausible_cli_records(
        days_by_date={climate_day: day},
        records=[final],
        temperatures_by_day={climate_day: temperatures},
        std_utc_offset_hours=-6.0,
    )

    assert len(flagged) == 1
    assert flagged[0].climate_day == climate_day
    assert flagged[0].cli_tmax_f == 55
    assert flagged[0].asos_max_f == 39
    assert "exceeds_asos_daily_max" in flagged[0].reason
    assert not final.is_correction_bbb, "no correction marker -- flags would not catch it"

    # And it is NOT excluded from the statistic: the crossing it implies is counted.
    cases = study.build_exceedance_cases(day=day, settled_f=final.tmax_f)
    assert all(case.crosses_bucket for case in cases)


def test_a_cli_final_agreeing_with_its_asos_series_is_not_flagged(
    study: ModuleType,
) -> None:
    climate_day = dt.date(2021, 12, 30)
    day = _one_complete_day(study, tenths=39, city="MDW", std_utc_offset_hours=-6.0,
                            climate_day=climate_day)
    temperatures, _ = study.metar_temperatures(
        city="MDW",
        rows=[
            _metar_row(
                station="MDW",
                valid=(
                    dt.datetime(2021, 12, 30, 6, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
                ).strftime("%Y-%m-%d %H:%M"),
                t_group=_f_to_t_group(39),
            )
            for hour in range(24)
        ],
        std_utc_offset_hours=-6.0,
    )
    final = study.CliRecord(
        city="MDW",
        climate_day=climate_day,
        issuance="FINAL",
        tmax_f=day.observed_max_f,
        tmax_sentinel="NONE",
        max_time=study.CliMaxTime(hour=12, minute=0),
        is_correction_bbb=False,
        issued_at_utc=None,
        source="fixture",
    )

    flagged, uncorroborated = study.implausible_cli_records(
        days_by_date={climate_day: day},
        records=[final],
        temperatures_by_day={climate_day: temperatures},
        std_utc_offset_hours=-6.0,
    )

    assert flagged == ()
    assert uncorroborated == 0


# ---------------------------------------------------------------------------
# Readout helpers
# ---------------------------------------------------------------------------


def test_first_hour_below_requires_the_bound_to_stay_below_not_merely_touch(
    study: ModuleType,
) -> None:
    def cell(hour: int, cross: int, n: int) -> Any:
        return study.Cell(
            city="LAX",
            season="JJA",
            hour=hour,
            headroom_f=0,
            n=n,
            cross_count=cross,
            physics_cross_count=cross,
            basis_only_cross_count=0,
            exceed_count=cross,
            negative_basis_count=0,
        )

    # Hour 10 dips under the level and hour 11 pops back out; the answer must
    # be 12, not 10.
    # 500/10000 -> Wilson upper ~5.4%, well ABOVE the 1% level; 0/10000 ->
    # Wilson upper ~0.04%, well below it.
    cells = {("LAX", "JJA", hour, 0): cell(hour, 0 if hour in (10, *range(12, 24)) else 500, 10_000)
             for hour in range(24)}

    assert study.first_hour_below(cells, city="LAX", season="JJA", headroom=0, level=0.01) == 12


def test_first_hour_below_returns_none_when_the_risk_never_gets_small(
    study: ModuleType,
) -> None:
    cells = {
        ("LAX", "JJA", hour, 0): study.Cell(
            city="LAX", season="JJA", hour=hour, headroom_f=0, n=1_000,
            cross_count=200, physics_cross_count=200, basis_only_cross_count=0,
            exceed_count=200, negative_basis_count=0,
        )
        for hour in range(24)
    }

    assert study.first_hour_below(cells, city="LAX", season="JJA", headroom=0, level=0.01) is None


def test_hour_distribution_tail_share_and_percentiles(study: ModuleType) -> None:
    distribution = study.hour_distribution("fixture", [10] * 90 + [19] * 10)

    assert distribution.n == 100
    assert distribution.tail_share(17) == pytest.approx(0.10)
    assert distribution.percentile_hour(0.5) == 10
    assert distribution.percentile_hour(0.95) == 19


def test_is_bimodal_applies_the_preregistered_criterion(study: ModuleType) -> None:
    unimodal = study.hour_distribution("unimodal", [13] * 60 + [14] * 40)
    bimodal = study.hour_distribution("bimodal", [10] * 45 + [11] * 5 + [17] * 50)

    assert study.is_bimodal(unimodal)[0] is False
    assert study.is_bimodal(bimodal)[0] is True
    assert study.is_bimodal(study.hour_distribution("empty", []))[0] is False


def test_parse_cli_max_time_reads_the_colonless_kokx_time_format(
    study: ModuleType,
) -> None:
    """Offices do not agree on the time format. KLOT prints `2:52 PM`; KOKX
    prints `602 AM` / `1159 PM` with no colon. Verified against the archived
    products: `CLINYC_202101010622.txt` has `MAXIMUM 48    602 AM`, and
    `CLIMDW_202101010637.txt` has `MAXIMUM 30   2:52 PM`. Reading only the
    colon form silently drops every KOKX time-of-max.
    """
    kokx = _CLI_FINAL_FIXTURE.replace(
        "  MAXIMUM         79   1:44 PM 100    1947  82     -3       75",
        "  MAXIMUM         48    602 AM  63    1965  39      9       45",
    )
    parsed = study.parse_cli_max_time(kokx)
    assert parsed is not None
    assert (parsed.hour, parsed.minute) == (6, 2)

    late = _CLI_FINAL_FIXTURE.replace("1:44 PM", "1159 PM")
    parsed_late = study.parse_cli_max_time(late)
    assert parsed_late is not None
    assert (parsed_late.hour, parsed_late.minute) == (23, 59)


def test_parse_cli_max_time_rejects_a_time_shaped_token_with_an_impossible_clock(
    study: ModuleType,
) -> None:
    for printed in ("1372 PM", "0:30 AM", "13:05 PM"):
        assert study.parse_cli_max_time(_CLI_FINAL_FIXTURE.replace("1:44 PM", printed)) is None


# ---------------------------------------------------------------------------
# T* must be the PHYSICAL time of maximum, not the first rounding tie
# ---------------------------------------------------------------------------


def test_hour_of_max_is_taken_from_the_unrounded_reading_not_the_rounded_one(
    study: ModuleType,
) -> None:
    """Rounding to whole °F creates ties, and a first-attaining-hour rule
    breaks every tie toward the MORNING -- biasing T* early by hours.

    24.2C (75.56F) and 24.5C (76.10F) both round to 76F. A T* read off the
    rounded series lands at 09h; the physical peak is at 15h. The CLI product states the physical
    peak, so a rounded-basis T* would also manufacture a spurious ASOS-vs-CLI
    disagreement in section 3.3.
    """
    tenths_by_hour = {hour: 200 for hour in range(24)}
    tenths_by_hour[9] = 242
    tenths_by_hour[15] = 245
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(tenths),
        )
        for hour, tenths in sorted(tenths_by_hour.items())
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    assert study.round_half_up_f(242) == study.round_half_up_f(245) == 76
    assert day.observed_max_f == 76
    assert day.hour_of_max == 15, "T* must follow the tenths, not the rounded tie"
    assert day.hour_of_rounded_max == 9
    # R(t) itself stays in SETTLEMENT units -- whole °F -- and is unaffected.
    assert day.running_max_f[9] == 76


# ---------------------------------------------------------------------------
# Implausibility: separate "contradicted by ASOS" from "ASOS wasn't looking"
# ---------------------------------------------------------------------------


def _mdw_day(study: ModuleType, *, tenths: int, climate_day: dt.date) -> tuple[Any, Any]:
    rows = [
        _metar_row(
            station="MDW",
            valid=(
                dt.datetime(climate_day.year, climate_day.month, climate_day.day, 6, 0,
                            tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(tenths),
        )
        for hour in range(24)
    ]
    temperatures, _ = study.metar_temperatures(
        city="MDW", rows=rows, std_utc_offset_hours=-6.0
    )
    (day,) = study.build_running_max_days(
        city="MDW", temperatures=temperatures, std_utc_offset_hours=-6.0
    )
    return day, temperatures


def test_a_cadence_gap_at_the_stated_time_is_not_an_implausibility(
    study: ModuleType,
) -> None:
    """NYC is HOURLY, reporting at :51. A CLI max stated at 00:05 has no
    observation within +/-30 min, which says the ASOS was not looking -- it
    does not say the CLI contradicted it. Counting that as implausible turned
    a cadence artifact into a 1.8% "bad print" rate at NYC alone.
    """
    climate_day = dt.date(2022, 1, 15)
    rows = [
        _metar_row(
            station="NYC",
            valid=(
                dt.datetime(2022, 1, 15, 5, 51, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(hour * 5),
        )
        for hour in range(24)
    ]
    temperatures, _ = study.metar_temperatures(
        city="NYC", rows=rows, std_utc_offset_hours=-5.0
    )
    (day,) = study.build_running_max_days(
        city="NYC", temperatures=temperatures, std_utc_offset_hours=-5.0
    )
    record = study.CliRecord(
        city="NYC",
        climate_day=climate_day,
        issuance="FINAL",
        tmax_f=day.observed_max_f,
        tmax_sentinel="NONE",
        max_time=study.CliMaxTime(hour=0, minute=5),
        is_correction_bbb=False,
        issued_at_utc=None,
        source="fixture",
    )

    flagged, uncorroborated = study.implausible_cli_records(
        days_by_date={climate_day: day},
        records=[record],
        temperatures_by_day={climate_day: temperatures},
        std_utc_offset_hours=-5.0,
    )

    assert flagged == ()
    assert uncorroborated == 1


def test_the_known_mdw_fat_tail_is_caught_on_the_preliminary_not_the_final(
    study: ModuleType,
) -> None:
    """MDW 2021-12-30: preliminary `MAXIMUM 55  7:11 AM`, FINAL 39, no
    correction marker anywhere. A "the peak already happened this morning"
    rule reads the PRELIMINARY, so the implausibility scan has to cover
    preliminaries or it misses the archetypal hazard entirely.
    """
    climate_day = dt.date(2021, 12, 30)
    day, temperatures = _mdw_day(study, tenths=39, climate_day=climate_day)
    assert day.observed_max_f == 39

    preliminary = study.CliRecord(
        city="MDW",
        climate_day=climate_day,
        issuance="PRELIMINARY",
        tmax_f=55,
        tmax_sentinel="NONE",
        max_time=study.CliMaxTime(hour=7, minute=11),
        is_correction_bbb=False,
        issued_at_utc=None,
        source="fixture",
    )
    final = study.CliRecord(
        city="MDW",
        climate_day=climate_day,
        issuance="FINAL",
        tmax_f=39,
        tmax_sentinel="NONE",
        max_time=study.CliMaxTime(hour=13, minute=0),
        is_correction_bbb=False,
        issued_at_utc=None,
        source="fixture",
    )

    flagged, _ = study.implausible_cli_records(
        days_by_date={climate_day: day},
        records=[preliminary, final],
        temperatures_by_day={climate_day: temperatures},
        std_utc_offset_hours=-6.0,
    )

    assert len(flagged) == 1
    assert flagged[0].issuance == "PRELIMINARY"
    assert flagged[0].cli_tmax_f == 55
    assert flagged[0].asos_max_f == 39
    assert "exceeds_asos_daily_max" in flagged[0].reason
    assert not preliminary.is_correction_bbb, "unflagged: no correction marker to gate on"


# ---------------------------------------------------------------------------
# Decomposing a CLI-basis crossing: late-day PHYSICS vs instrument BASIS
# ---------------------------------------------------------------------------


def test_a_crossing_is_split_into_physics_and_basis_only(study: ModuleType) -> None:
    """A `cli`-basis crossing has two disjoint causes and they are not the same
    risk. Either the day genuinely got hotter than the rung ceiling (PHYSICS,
    visible in the ASOS series itself), or it did not and the CLI integer still
    landed above the ceiling (BASIS -- a different thermometer, rounded).

    Pooling them reports an instrument mismatch as if it were weather.
    """
    # Flat day: ASOS max == R(t) == 79, so the rung is [78, 79] and headroom 0.
    day = _one_complete_day(study, tenths=261)
    assert day.observed_max_f == 79
    assert study.headroom_f(79) == 0

    basis_only = study.build_exceedance_cases(day=day, settled_f=80)
    assert all(case.crosses_bucket for case in basis_only)
    assert not any(case.physics_crosses_bucket for case in basis_only)

    cell = study.aggregate(basis_only)[("LAX", "DJF", 12, 0)]
    assert cell.cross_count == 1
    assert cell.physics_cross_count == 0
    assert cell.basis_only_cross_count == 1


def test_a_physics_crossing_is_attributed_to_physics_not_to_basis(
    study: ModuleType,
) -> None:
    rows = [
        _metar_row(
            station="LAX",
            valid=(
                dt.datetime(2025, 1, 15, 8, 0, tzinfo=dt.UTC) + dt.timedelta(hours=hour)
            ).strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(261 if hour < 12 else 289),
        )
        for hour in range(24)
    ]
    (day,) = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)
    assert day.running_max_f[0] == 79
    assert day.observed_max_f == 84

    cases = {
        case.hour: case
        for case in study.build_exceedance_cases(day=day, settled_f=day.observed_max_f)
    }
    morning = cases[0]

    assert morning.crosses_bucket is True
    assert morning.physics_crosses_bucket is True

    cell = study.aggregate([morning])[("LAX", "DJF", 0, 0)]
    assert cell.physics_cross_count == 1
    assert cell.basis_only_cross_count == 0


def test_resolution_floor_is_the_smallest_wilson_upper_a_cell_can_report(
    study: ModuleType,
) -> None:
    """With zero events the Wilson upper is exactly `z**2 / (n + z**2)`. That
    is the study's RESOLUTION, and a reference level below it is unreachable
    with the corpus on hand -- a power statement, never a physical one.
    """
    for n in (170, 250, 460, 1_800):
        assert study.resolution_floor(n) == pytest.approx(study.wilson_upper(0, n))

    assert study.resolution_floor(0) is None
    assert study.resolution_floor(250) > study.resolution_floor(1_800)


def test_merge_cells_pools_seasons_but_preserves_headroom(study: ModuleType) -> None:
    cells = [
        study.Cell(city="LAX", season=season, hour=14, headroom_f=0, n=100,
                   cross_count=2, physics_cross_count=1, basis_only_cross_count=1,
                   exceed_count=5, negative_basis_count=3)
        for season in ("DJF", "MAM", "JJA", "SON")
    ]

    merged = study.merge_cells(cells)

    assert merged is not None
    assert merged.season == "ALL"
    assert merged.headroom_f == 0
    assert (merged.n, merged.cross_count, merged.exceed_count) == (400, 8, 20)
    assert merged.physics_cross_count == 4
    assert merged.basis_only_cross_count == 4
    assert merged.negative_basis_count == 12
    assert study.merge_cells([]) is None


# ---------------------------------------------------------------------------
# The headline verdict is COMPUTED from the cells, never asserted in prose
# ---------------------------------------------------------------------------


def _cells(study: ModuleType, *, cross_at: dict[int, int], n: int = 1_000) -> dict[Any, Any]:
    return {
        ("LAX", "JJA", hour, 0): study.Cell(
            city="LAX", season="JJA", hour=hour, headroom_f=0, n=n,
            cross_count=cross_at.get(hour, 0),
            physics_cross_count=0,
            basis_only_cross_count=cross_at.get(hour, 0),
            exceed_count=cross_at.get(hour, 0),
            negative_basis_count=0,
        )
        for hour in range(24)
    }


def test_headline_verdict_is_refuted_when_no_hour_reaches_the_level(
    study: ModuleType,
) -> None:
    cells = _cells(study, cross_at={hour: 200 for hour in range(24)})

    verdict = study.headline_verdict(cells, city="LAX", season="JJA", headroom=0, level=0.05)

    assert verdict.reached is False
    assert verdict.hour is None
    assert "no hour" in verdict.detail.lower()


def test_headline_verdict_names_the_hour_when_one_exists(study: ModuleType) -> None:
    cells = _cells(study, cross_at={hour: 200 for hour in range(15)})

    verdict = study.headline_verdict(cells, city="LAX", season="JJA", headroom=0, level=0.05)

    assert verdict.reached is True
    assert verdict.hour == 15


def test_headline_verdict_refuses_to_claim_an_hour_below_the_resolution_floor(
    study: ModuleType,
) -> None:
    """A zero-event cell of n=100 cannot resolve 0.1%: its Wilson upper floor is
    ~3.7%. Reporting "risk is below 0.1% from hour 0" there would sell a
    sample-size limit as a physical finding."""
    cells = _cells(study, cross_at={}, n=100)

    verdict = study.headline_verdict(cells, city="LAX", season="JJA", headroom=0, level=0.001)

    assert verdict.reached is False
    assert verdict.underpowered is True
    assert "resolution" in verdict.detail.lower()

    powered = study.headline_verdict(cells, city="LAX", season="JJA", headroom=0, level=0.05)
    assert powered.reached is True
    assert powered.underpowered is False


def test_headline_verdict_refuses_an_empty_selection(study: ModuleType) -> None:
    cells = _cells(study, cross_at={})

    with pytest.raises(ValueError, match="not a verdict"):
        study.headline_verdict(cells, city="LAX", season="DJF", headroom=0, level=0.05)


# ---------------------------------------------------------------------------
# Report assembly -- exercised on a synthetic station, no archive, no network
# ---------------------------------------------------------------------------


def _station_result(study: ModuleType, city: str = "LAX") -> Any:
    """A tiny but structurally complete StationResult.

    Two climate days per season so every (season, hour, headroom) axis the
    report indexes actually exists, plus a CLI record carrying a stated time.
    """
    cases_cli: list[Any] = []
    cases_obs: list[Any] = []
    asos_hours: dict[str, list[int]] = {}
    cli_hours: dict[str, list[int]] = {}
    for month, season in ((1, "DJF"), (4, "MAM"), (7, "JJA"), (10, "SON")):
        for offset, tenths in ((0, 261), (1, 256)):
            climate_day = dt.date(2025, month, 10 + offset)
            day = _one_complete_day(study, tenths=tenths, city=city, climate_day=climate_day)
            cases_obs.extend(
                study.build_exceedance_cases(day=day, settled_f=day.observed_max_f)
            )
            cases_cli.extend(
                study.build_exceedance_cases(day=day, settled_f=day.observed_max_f + offset)
            )
            asos_hours.setdefault(season, []).append(day.hour_of_max)
            cli_hours.setdefault(season, []).append(13)

    return study.StationResult(
        city=city,
        std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
        observation_count=8 * 24,
        day_count=8,
        complete_day_count=8,
        drops=Counter({"incomplete_climate_day": 0, "missing_cli_final": 1}),
        cells_cli=study.aggregate(cases_cli),
        cells_obs=study.aggregate(cases_obs),
        cli_day_count=8,
        basis_counts=Counter({0: 4, 1: 4}),
        asos_hour_of_max={
            season: study.hour_distribution(f"{city} {season} ASOS", hours)
            for season, hours in asos_hours.items()
        },
        cli_hour_of_max={
            season: study.hour_distribution(f"{city} {season} CLI", hours)
            for season, hours in cli_hours.items()
        },
        cli_minus_asos_hour=Counter({0: 5, 1: 3}),
        cli_minus_asos_hour_dst=Counter({0: 3, 1: 1}),
        cli_minus_asos_hour_std=Counter({0: 2, 1: 2}),
        gain_counts_cli={0: Counter({1: 4}), 1: Counter({1: 4})},
        gain_counts_obs={0: Counter(), 1: Counter()},
        implausible=(
            study.ImplausibleCliRecord(
                city=city,
                climate_day=dt.date(2025, 1, 10),
                issuance="PRELIMINARY",
                cli_tmax_f=99,
                asos_max_f=79,
                cli_max_hour=7,
                asos_near_stated_time_max_f=None,
                reason="exceeds_asos_daily_max",
                source="fixture",
            ),
        ),
        uncorroborated_stated_times=2,
        cli_missing_max_time=1,
    )


def test_build_report_renders_every_section_without_a_hole(study: ModuleType) -> None:
    report = study.build_report(
        [_station_result(study)],
        generated_at=dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC),
        cache_dir=Path("/nonexistent/fixture-cache"),
    )

    for heading in (
        "## 0.1 Headline",
        "## 1. Corpus and denominators",
        "## 2. METAR↔CLI basis",
        "## 3. Time of the daily maximum",
        "### 3.3 CLI-stated hour minus ASOS hour",
        "## 4. Pre-registered decision rules",
        "### 5.0 Resolution",
        "### 5.2 End-of-day decomposition",
        "### 5.3 Season-pooled",
        "## 6. Conditional on an exceedance",
        "## 7. Full conditional table",
        "## 8. Limitations",
    ):
        assert heading in report, f"missing section: {heading}"

    # No table cell may be a bare Python repr leaking through an f-string.
    assert "None" not in report
    assert "Counter(" not in report
    # The known-hazard record is present, not filtered out.
    assert "exceeds_asos_daily_max" in report
    # It states plainly what it is not. (A keyword ban would be the wrong test:
    # the disclaimer has to be allowed to NAME the things it disclaims.)
    assert "**not** a backtest, **not** a trading simulation" in report
    assert "NautilusTrader is the exclusive owner of" in report
    # And it carries no trading-result column anywhere.
    header_rows = [line for line in report.splitlines() if line.startswith("| station |")]
    assert header_rows
    for header in header_rows:
        lowered_header = header.lower()
        for banned in ("price", "p&l", "pnl", "profit", "fill", "size", "edge"):
            assert banned not in lowered_header, (
                f"a physics table must not carry a {banned!r} column: {header}"
            )


def test_build_report_states_the_denominator_on_every_conditional_row(
    study: ModuleType,
) -> None:
    result = _station_result(study)
    report = study.build_report(
        [result],
        generated_at=dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC),
        cache_dir=Path("/nonexistent/fixture-cache"),
    )
    body = report.split("## 7. Full conditional table", 1)[1]
    rows = [line for line in body.splitlines() if line.startswith("| LAX |")]

    assert rows
    for row in rows:
        columns = [column.strip() for column in row.strip("|").split("|")]
        # station, season, hour, headroom, n, ...
        assert int(columns[4]) > 0, f"row reports a rate with no denominator: {row}"

    assert len(rows) == 2 * sum(
        1 for key in result.cells_cli if key[0] == "LAX"
    ), "the cli and obs tables must both be rendered in full"
