"""Tests for breezy.normalize.climate_day.

The climate day is always local STANDARD time, year-round, using a fixed
UTC offset supplied by the caller -- never zoneinfo/DST-aware conversion.
An instant near a DST transition must map to the same calendar date it
would on any other day of the year, because the offset used is fixed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from breezy.normalize.climate_day import (
    ClimateDayError,
    climate_day_for_instant,
    standard_time_zone,
)


def test_standard_time_zone_uses_fixed_offset_not_zoneinfo() -> None:
    tz = standard_time_zone(-5.0)
    assert tz.utcoffset(None) == timedelta(hours=-5)


@pytest.mark.parametrize(
    ("instant_utc", "std_utc_offset_hours", "expected_day"),
    [
        # NYC (-5): 05:00Z is local-standard midnight; just before/after
        # the boundary must fall on different climate days.
        (datetime(2026, 7, 4, 4, 59, 59, tzinfo=UTC), -5.0, date(2026, 7, 3)),
        (datetime(2026, 7, 4, 5, 0, 0, tzinfo=UTC), -5.0, date(2026, 7, 4)),
        # MDW (-6): boundary at 06:00Z.
        (datetime(2026, 7, 4, 5, 59, 59, tzinfo=UTC), -6.0, date(2026, 7, 3)),
        (datetime(2026, 7, 4, 6, 0, 0, tzinfo=UTC), -6.0, date(2026, 7, 4)),
        # LAX/SFO (-8): boundary at 08:00Z.
        (datetime(2026, 7, 4, 7, 59, 59, tzinfo=UTC), -8.0, date(2026, 7, 3)),
        (datetime(2026, 7, 4, 8, 0, 0, tzinfo=UTC), -8.0, date(2026, 7, 4)),
    ],
)
def test_climate_day_boundary_is_exact_for_each_offset(
    instant_utc: datetime, std_utc_offset_hours: float, expected_day: date
) -> None:
    assert climate_day_for_instant(instant_utc, std_utc_offset_hours) == expected_day


@pytest.mark.parametrize("std_utc_offset_hours", [-5.0, -6.0, -8.0])
def test_climate_day_uses_local_standard_time_year_round(std_utc_offset_hours: float) -> None:
    """Across both 2026 DST transitions, the SAME fixed offset must be used.

    If DST-aware conversion leaked in, the boundary instant (which is fixed
    relative to standard time) would shift by an hour around the transition
    dates. We assert the boundary stays put on both sides of each
    transition: spring-forward (2026-03-08) and fall-back (2026-11-01).
    """
    boundary_utc = timedelta(hours=-std_utc_offset_hours)  # e.g. 05:00Z for -5

    for transition_date in (date(2026, 3, 8), date(2026, 11, 1)):
        for probe_date in (
            transition_date - timedelta(days=3),
            transition_date,
            transition_date + timedelta(days=3),
        ):
            just_before = datetime.combine(probe_date, datetime.min.time(), tzinfo=UTC) + (
                boundary_utc - timedelta(seconds=1)
            )
            just_after = datetime.combine(probe_date, datetime.min.time(), tzinfo=UTC) + boundary_utc

            assert climate_day_for_instant(just_before, std_utc_offset_hours) == probe_date - timedelta(days=1)
            assert climate_day_for_instant(just_after, std_utc_offset_hours) == probe_date


def test_climate_day_rejects_naive_datetime() -> None:
    naive = datetime(2026, 8, 21, 12, 0, 0)  # noqa: DTZ001 -- deliberately naive
    with pytest.raises(ClimateDayError):
        climate_day_for_instant(naive, -5.0)
