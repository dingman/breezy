"""Unit tests for `RunningExtremeAccumulator` -- BL-24 Seam A.

The differential oracle is `build_running_max_days`
(`scripts/analysis/pmr_climatology_study.py:351`), reused rather than
reimplemented -- see `docs/plans/BL24_LIVE_RT_2026-09-04.md` §3 and
amendment A3 (hour-resolution comparison).
"""

from __future__ import annotations

import datetime as dt
from types import ModuleType

import pytest

from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator
from tests.unit.test_pmr_climatology_study import (
    _LAX_STD_OFFSET_HOURS,
    _f_to_t_group,
    _load_study_module,
    _metar_row,
)

_NS_PER_SECOND = 1_000_000_000


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return _load_study_module()


def _local_midnight_utc(climate_day: dt.date, std_utc_offset_hours: float) -> dt.datetime:
    tz = dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    return dt.datetime.combine(climate_day, dt.time(0, 0), tzinfo=tz).astimezone(dt.UTC)


def _ns(instant: dt.datetime) -> int:
    return int(instant.timestamp() * _NS_PER_SECOND)


def _push_row(
    accumulator: RunningExtremeAccumulator,
    study: ModuleType,
    *,
    instant_utc: dt.datetime,
    temp_c_tenths: int,
) -> None:
    temp_f = study.c_tenths_to_f(temp_c_tenths)
    rounded_f = study.round_half_up_f(temp_c_tenths)
    accumulator.push(_ns(instant_utc), rounded_f, temp_f)


# ---------------------------------------------------------------------------
# Differential: agrees with the offline oracle at every local-standard hour end
# ---------------------------------------------------------------------------


def test_agrees_with_the_offline_oracle_at_each_local_standard_hour_end(
    study: ModuleType,
) -> None:
    climate_day = dt.date(2025, 1, 15)
    tenths_by_hour = {0: 50, 3: 200, 3 + 1: 80, 10: 300, 20: 150}
    rows = []
    tz = dt.timezone(dt.timedelta(hours=_LAX_STD_OFFSET_HOURS))
    midnight_local = dt.datetime.combine(climate_day, dt.time(0, 0), tzinfo=tz)
    for hour, tenths in sorted(tenths_by_hour.items()):
        instant = midnight_local + dt.timedelta(hours=hour)
        rows.append(
            _metar_row(
                station="LAX",
                valid=instant.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M"),
                t_group=_f_to_t_group(tenths),
            ),
        )

    temperatures, drops = study.metar_temperatures(
        city="LAX", rows=rows, std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
    )
    assert not drops
    (oracle_day,) = study.build_running_max_days(
        city="LAX", temperatures=temperatures, std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
    )

    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    for hour, tenths in sorted(tenths_by_hour.items()):
        _push_row(
            accumulator, study,
            instant_utc=(midnight_local + dt.timedelta(hours=hour)).astimezone(dt.UTC),
            temp_c_tenths=tenths,
        )

    for hour in range(24):
        hour_end_local = midnight_local + dt.timedelta(hours=hour + 1)
        hour_end_ns = _ns(hour_end_local.astimezone(dt.UTC)) - 1  # still within `hour`
        assert accumulator.value_at(hour_end_ns) == oracle_day.running_max_f[hour], hour


# ---------------------------------------------------------------------------
# A same-instant re-push may LOWER R (amendment A2)
# ---------------------------------------------------------------------------


def test_a_same_instant_repush_may_lower_r(study: ModuleType) -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    instant = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=6)

    _push_row(accumulator, study, instant_utc=instant, temp_c_tenths=200)
    assert accumulator.value_at(_ns(instant)) == study.round_half_up_f(200)

    # A correction at the SAME instant, lower than before -- accepted, not
    # rejected or clamped.
    _push_row(accumulator, study, instant_utc=instant, temp_c_tenths=100)
    assert accumulator.value_at(_ns(instant)) == study.round_half_up_f(100)


# ---------------------------------------------------------------------------
# Resets at local-standard midnight, not UTC
# ---------------------------------------------------------------------------


def test_resets_at_local_standard_midnight_not_utc(study: ModuleType) -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    day_one = dt.date(2025, 1, 15)
    day_two = dt.date(2025, 1, 16)

    late_day_one = _local_midnight_utc(day_one, _LAX_STD_OFFSET_HOURS) + dt.timedelta(
        hours=23, minutes=59,
    )
    _push_row(accumulator, study, instant_utc=late_day_one, temp_c_tenths=300)
    assert accumulator.earliest_observed_ns == _ns(late_day_one)

    early_day_two = _local_midnight_utc(day_two, _LAX_STD_OFFSET_HOURS) + dt.timedelta(
        minutes=1,
    )
    _push_row(accumulator, study, instant_utc=early_day_two, temp_c_tenths=50)

    # The prior day's row is gone -- the day-two low, not the day-one high.
    assert accumulator.value_at(_ns(early_day_two)) == study.round_half_up_f(50)
    assert accumulator.earliest_observed_ns == _ns(early_day_two)
    # A `now` still inside day one no longer resolves -- the accumulator
    # holds only the current day.
    assert accumulator.value_at(_ns(late_day_one)) is None


# ---------------------------------------------------------------------------
# A missing interval raises staleness, never interpolates
# ---------------------------------------------------------------------------


def test_a_missing_interval_raises_staleness_and_never_interpolates(
    study: ModuleType,
) -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    first = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)
    _push_row(accumulator, study, instant_utc=first, temp_c_tenths=100)

    five_minutes_later = _ns(first) + 5 * 60 * _NS_PER_SECOND
    assert accumulator.staleness_ns(five_minutes_later) == 5 * 60 * _NS_PER_SECOND
    # `R` still holds the last pushed value -- it does not vanish while
    # stale, it is the caller's job to consult staleness and refuse.
    assert accumulator.value_at(five_minutes_later) == study.round_half_up_f(100)

    # A much longer gap -- staleness keeps growing; still no interpolation
    # invents an intermediate value.
    three_hours_later = _ns(first) + 3 * 3600 * _NS_PER_SECOND
    assert accumulator.staleness_ns(three_hours_later) == 3 * 3600 * _NS_PER_SECOND
    assert accumulator.value_at(three_hours_later) == study.round_half_up_f(100)


def test_staleness_and_value_at_are_none_before_any_push() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    assert accumulator.staleness_ns(0) is None
    assert accumulator.value_at(0) is None
    assert accumulator.earliest_observed_ns is None
    assert accumulator.covered is False


# ---------------------------------------------------------------------------
# Out-of-order arrival is accepted by instant, never reordered into a wrong day
# ---------------------------------------------------------------------------


def test_out_of_order_arrival_is_accepted_by_instant(study: ModuleType) -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    midnight_local_utc = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS)
    early = midnight_local_utc + dt.timedelta(hours=2)
    late = midnight_local_utc + dt.timedelta(hours=10)

    # Received out of chronological order: the LATE instant's bytes arrive
    # (are pushed) first.
    _push_row(accumulator, study, instant_utc=late, temp_c_tenths=90)
    _push_row(accumulator, study, instant_utc=early, temp_c_tenths=200)

    # `R` at a `now` between the two instants sees only the early (higher)
    # reading -- the late one is correctly excluded by its OWN instant, not
    # by arrival order.
    between = midnight_local_utc + dt.timedelta(hours=6)
    assert accumulator.value_at(_ns(between)) == study.round_half_up_f(200)
    # `R` at `now` on/after the late instant sees both, and the max wins.
    assert accumulator.value_at(_ns(late)) == study.round_half_up_f(200)
    assert accumulator.covered is True
    assert accumulator.earliest_observed_ns == _ns(early)
