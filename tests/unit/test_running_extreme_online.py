"""Unit tests for `RunningExtremeAccumulator` -- BL-24 Seam A / A-2.

The differential oracle is `build_running_max_days`
(`scripts/analysis/pmr_climatology_study.py:351`), reused rather than
reimplemented -- see `docs/plans/BL24_LIVE_RT_2026-09-04.md` §3 and
amendment A3 (hour-resolution comparison), extended by amendment A13
(interval-valued `R(t)`).
"""

from __future__ import annotations

import datetime as dt
from types import ModuleType

import pytest

from breezy.strategy.weather_common.running_extreme import (
    CoverageReport,
    RunningExtremeAccumulator,
    RunningMax,
)
from tests.unit.test_pmr_climatology_study import (
    _LAX_STD_OFFSET_HOURS,
    _f_to_t_group,
    _load_study_module,
    _metar_row,
)

_NS_PER_SECOND = 1_000_000_000

#: A METAR row's own `precision_c_tenths` -- see `iem_observations.py`. The
#: accumulator ignores it for interval math (a METAR row is exact), so its
#: exact value here is not load-bearing beyond being a valid positive int.
_METAR_PRECISION_C_TENTHS = 5

#: An integer-Celsius row's `precision_c_tenths`: full width 10 tenths (1.0
#: C), matching the NWS 5-minute API's `[x - 0.5, x + 0.5)` C interval.
_INTEGER_PRECISION_C_TENTHS = 10


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return _load_study_module()


def _local_midnight_utc(climate_day: dt.date, std_utc_offset_hours: float) -> dt.datetime:
    tz = dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    return dt.datetime.combine(climate_day, dt.time(0, 0), tzinfo=tz).astimezone(dt.UTC)


def _ns(instant: dt.datetime) -> int:
    return int(instant.timestamp() * _NS_PER_SECOND)


def _push_metar_row(
    accumulator: RunningExtremeAccumulator,
    *,
    instant_utc: dt.datetime,
    temp_c_tenths: int,
    received_at_ns: int | None = None,
) -> None:
    observed_at_ns = _ns(instant_utc)
    accumulator.push(
        observed_at_ns,
        temp_c_tenths,
        _METAR_PRECISION_C_TENTHS,
        True,
        received_at_ns if received_at_ns is not None else observed_at_ns,
    )


def _push_integer_row(
    accumulator: RunningExtremeAccumulator,
    *,
    instant_utc: dt.datetime,
    temp_c_tenths: int,
    received_at_ns: int | None = None,
) -> None:
    observed_at_ns = _ns(instant_utc)
    accumulator.push(
        observed_at_ns,
        temp_c_tenths,
        _INTEGER_PRECISION_C_TENTHS,
        False,
        received_at_ns if received_at_ns is not None else observed_at_ns,
    )


# ---------------------------------------------------------------------------
# Differential: agrees with the offline oracle at every local-standard hour
# end, when every pushed row is METAR (tenths, exact) -- the interval
# collapses and `RunningMax` behaves exactly like the old scalar `rounded_f`.
# ---------------------------------------------------------------------------


def test_agrees_with_the_offline_oracle_at_each_local_standard_hour_end(
    study: ModuleType,
) -> None:
    climate_day = dt.date(2025, 1, 15)
    tenths_by_hour = {0: 50, 3: 200, 3 + 1: 60, 10: 300, 20: 150}
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
        city="LAX",
        rows=rows,
        std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
    )
    assert not drops
    (oracle_day,) = study.build_running_max_days(
        city="LAX",
        temperatures=temperatures,
        std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
    )

    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    for hour, tenths in sorted(tenths_by_hour.items()):
        _push_metar_row(
            accumulator,
            instant_utc=(midnight_local + dt.timedelta(hours=hour)).astimezone(dt.UTC),
            temp_c_tenths=tenths,
        )

    for hour in range(24):
        hour_end_local = midnight_local + dt.timedelta(hours=hour + 1)
        hour_end_ns = _ns(hour_end_local.astimezone(dt.UTC)) - 1  # still within `hour`
        running_max = accumulator.value_at(hour_end_ns)
        assert running_max is not None, hour
        expected = oracle_day.running_max_f[hour]
        # A pure-METAR feed collapses the interval: lower == upper == exact.
        assert running_max.lower_f == expected, hour
        assert running_max.upper_f == expected, hour
        assert running_max.exact_f == expected, hour
        assert running_max.is_ambiguous() is False, hour


# ---------------------------------------------------------------------------
# A same-instant re-push may LOWER R (amendment A2)
# ---------------------------------------------------------------------------


def test_a_same_instant_repush_may_lower_r(study: ModuleType) -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    instant = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=6)

    _push_metar_row(accumulator, instant_utc=instant, temp_c_tenths=200)
    first = accumulator.value_at(_ns(instant))
    assert first is not None
    assert first.exact_f == study.round_half_up_f(200)

    # A correction at the SAME instant, lower than before -- accepted, not
    # rejected or clamped.
    _push_metar_row(accumulator, instant_utc=instant, temp_c_tenths=100)
    second = accumulator.value_at(_ns(instant))
    assert second is not None
    assert second.exact_f == study.round_half_up_f(100)


# ---------------------------------------------------------------------------
# Resets at local-standard midnight, not UTC
# ---------------------------------------------------------------------------


def test_resets_at_local_standard_midnight_not_utc(study: ModuleType) -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    day_one = dt.date(2025, 1, 15)
    day_two = dt.date(2025, 1, 16)

    late_day_one = _local_midnight_utc(day_one, _LAX_STD_OFFSET_HOURS) + dt.timedelta(
        hours=23,
        minutes=59,
    )
    _push_metar_row(accumulator, instant_utc=late_day_one, temp_c_tenths=300)
    assert accumulator.earliest_observed_ns == _ns(late_day_one)

    early_day_two = _local_midnight_utc(day_two, _LAX_STD_OFFSET_HOURS) + dt.timedelta(
        minutes=1,
    )
    _push_metar_row(accumulator, instant_utc=early_day_two, temp_c_tenths=50)

    # The prior day's row is gone -- the day-two low, not the day-one high.
    day_two_value = accumulator.value_at(_ns(early_day_two))
    assert day_two_value is not None
    assert day_two_value.exact_f == study.round_half_up_f(50)
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
    _push_metar_row(accumulator, instant_utc=first, temp_c_tenths=100)

    five_minutes_later = _ns(first) + 5 * 60 * _NS_PER_SECOND
    assert accumulator.staleness_ns(five_minutes_later) == 5 * 60 * _NS_PER_SECOND
    # `R` still holds the last pushed value -- it does not vanish while
    # stale, it is the caller's job to consult staleness and refuse.
    stale_value = accumulator.value_at(five_minutes_later)
    assert stale_value is not None
    assert stale_value.exact_f == study.round_half_up_f(100)

    # A much longer gap -- staleness keeps growing; still no interpolation
    # invents an intermediate value.
    three_hours_later = _ns(first) + 3 * 3600 * _NS_PER_SECOND
    assert accumulator.staleness_ns(three_hours_later) == 3 * 3600 * _NS_PER_SECOND
    much_stale_value = accumulator.value_at(three_hours_later)
    assert much_stale_value is not None
    assert much_stale_value.exact_f == study.round_half_up_f(100)


def test_staleness_and_value_at_are_none_before_any_push() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    assert accumulator.staleness_ns(0) is None
    assert accumulator.value_at(0) is None
    assert accumulator.earliest_observed_ns is None
    empty_coverage = accumulator.coverage(0, expected_cadence_ns=300 * _NS_PER_SECOND)
    assert empty_coverage == CoverageReport(
        first_observed_ns=None,
        last_observed_ns=None,
        largest_gap_ns=None,
    )


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
    _push_metar_row(accumulator, instant_utc=late, temp_c_tenths=90)
    _push_metar_row(accumulator, instant_utc=early, temp_c_tenths=200)

    # `R` at a `now` between the two instants sees only the early (higher)
    # reading -- the late one is correctly excluded by its OWN instant, not
    # by arrival order.
    between = midnight_local_utc + dt.timedelta(hours=6)
    between_value = accumulator.value_at(_ns(between))
    assert between_value is not None
    assert between_value.exact_f == study.round_half_up_f(200)
    # `R` at `now` on/after the late instant sees both, and the max wins.
    late_value = accumulator.value_at(_ns(late))
    assert late_value is not None
    assert late_value.exact_f == study.round_half_up_f(200)
    assert accumulator.earliest_observed_ns == _ns(early)


# ---------------------------------------------------------------------------
# `value_at` gates on RECEIPT as well as measurement (module docstring
# amendment A1: "measurement <= t AND receipt <= t") -- otherwise a live
# strategy trades on a faster information set than the archive measured.
# ---------------------------------------------------------------------------


def test_a_row_received_after_now_is_invisible_until_its_own_receipt_instant() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    t0 = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)
    received_at_ns = _ns(t0) + 30 * 60 * _NS_PER_SECOND  # received 30 min after measurement

    _push_metar_row(
        accumulator, instant_utc=t0, temp_c_tenths=200, received_at_ns=received_at_ns,
    )

    # `now` is 10 min after MEASUREMENT but 20 min BEFORE Breezy actually
    # received the row -- invisible, even though `observed_at_ns <= now_ns`.
    ten_minutes_after_observation = _ns(t0) + 10 * 60 * _NS_PER_SECOND
    assert accumulator.value_at(ten_minutes_after_observation) is None

    # `now` at the receipt instant itself -- now visible.
    at_receipt = accumulator.value_at(received_at_ns)
    assert at_receipt is not None
    assert at_receipt.exact_f == 68  # round_half_up_f(200)
    assert at_receipt.source_observed_at_ns == _ns(t0)
    assert at_receipt.source_received_at_ns == received_at_ns


# ---------------------------------------------------------------------------
# Amendment A13: interval-valued `R(t)`
# ---------------------------------------------------------------------------


def test_an_integer_row_that_straddles_two_f_rungs_is_ambiguous() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    instant = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)

    # 10.0 C, full width 1.0 C (`[9.5, 10.5)` C) -> `[49, 51)` F: a 2 F-wide
    # interval that spans two 1 F rungs (49-50 and 50-51).
    _push_integer_row(accumulator, instant_utc=instant, temp_c_tenths=100)

    running_max = accumulator.value_at(_ns(instant))
    assert running_max is not None
    assert running_max.exact_f is None
    assert running_max.lower_f == 49
    assert running_max.upper_f == 51
    assert running_max.is_ambiguous() is True


def test_a_later_metar_row_that_exceeds_an_ambiguous_integer_row_collapses() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    first = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)
    second = first + dt.timedelta(minutes=5)

    _push_integer_row(accumulator, instant_utc=first, temp_c_tenths=100)
    ambiguous = accumulator.value_at(_ns(first))
    assert ambiguous is not None
    assert ambiguous.is_ambiguous() is True

    # A METAR reading clearly above the integer row's interval -- the
    # running max collapses to an exact value.
    _push_metar_row(accumulator, instant_utc=second, temp_c_tenths=300)
    collapsed = accumulator.value_at(_ns(second))
    assert collapsed is not None
    assert collapsed.exact_f is not None
    assert collapsed.lower_f == collapsed.upper_f == collapsed.exact_f
    assert collapsed.is_ambiguous() is False
    assert collapsed.source_observed_at_ns == _ns(second)


def test_running_max_is_frozen_and_upper_bound_is_exclusive() -> None:
    running_max = RunningMax(
        lower_f=46, upper_f=48, exact_f=None, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.is_ambiguous(rung_width_f=1) is True
    assert running_max.is_ambiguous(rung_width_f=2) is False
    with pytest.raises(AttributeError):
        running_max.lower_f = 0  # type: ignore[misc]


def test_is_ambiguous_rejects_a_non_positive_rung_width() -> None:
    running_max = RunningMax(
        lower_f=46, upper_f=47, exact_f=46, source_observed_at_ns=0, source_received_at_ns=0
    )
    with pytest.raises(ValueError, match="rung_width_f"):
        running_max.is_ambiguous(rung_width_f=0)


# ---------------------------------------------------------------------------
# `spans` -- containment against the ACTUAL (non-width-aligned) venue ladder
# ---------------------------------------------------------------------------

#: A Polymarket.us-style phased ladder: open-ended tails, oddly-sized rungs.
_PHASED_LADDER: list[tuple[int | None, int | None]] = [
    (None, 79),  # "lt79f"
    (79, 91),
    (91, 92),  # a genuinely 1 F-wide rung, phased oddly against its neighbours
    (92, 94),
    (94, None),  # "gte94f"
]


def test_spans_is_false_when_the_interval_fits_one_ladder_rung() -> None:
    running_max = RunningMax(
        lower_f=80, upper_f=81, exact_f=80, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is False


def test_spans_is_true_when_the_interval_crosses_two_ladder_rungs() -> None:
    # [90, 93) crosses the 79-91, 91-92, and 92-94 rungs.
    running_max = RunningMax(
        lower_f=90, upper_f=93, exact_f=None, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is True


def test_spans_fits_the_narrow_odd_rung_that_a_uniform_width_would_miss() -> None:
    """`[91, 92)` is a genuine single rung on the real ladder.

    A UNIFORM 1 F-width `is_ambiguous` would call this unambiguous too, but
    a 2 F-width `is_ambiguous` would wrongly call it ambiguous -- `spans`
    answers correctly against the real ladder regardless of any assumed
    width.
    """
    running_max = RunningMax(
        lower_f=91, upper_f=92, exact_f=91, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is False


def test_spans_is_true_when_an_endpoint_falls_in_no_listed_rung() -> None:
    """Fails closed: a gap in the caller's ladder is never assumed safe."""
    sparse_ladder: list[tuple[int | None, int | None]] = [(None, 50), (60, None)]
    running_max = RunningMax(
        lower_f=55, upper_f=56, exact_f=55, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(sparse_ladder) is True


def test_spans_handles_open_ended_tail_rungs() -> None:
    running_max = RunningMax(
        lower_f=95, upper_f=96, exact_f=95, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is False

    below_all = RunningMax(
        lower_f=10, upper_f=11, exact_f=10, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert below_all.spans(_PHASED_LADDER) is False


# ---------------------------------------------------------------------------
# `coverage` (amendment A8) -- facts only, no policy
# ---------------------------------------------------------------------------


def test_coverage_rejects_a_non_positive_expected_cadence() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    with pytest.raises(ValueError, match="expected_cadence_ns"):
        accumulator.coverage(0, expected_cadence_ns=0)


def test_coverage_reports_first_last_and_largest_gap() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    midnight_local_utc = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS)
    first = midnight_local_utc + dt.timedelta(hours=1)
    second = first + dt.timedelta(minutes=5)
    third = second + dt.timedelta(minutes=20)  # the largest gap: 20 minutes

    for instant, tenths in ((first, 100), (second, 110), (third, 120)):
        _push_metar_row(accumulator, instant_utc=instant, temp_c_tenths=tenths)

    report = accumulator.coverage(_ns(third), expected_cadence_ns=300 * _NS_PER_SECOND)
    assert report.first_observed_ns == _ns(first)
    assert report.last_observed_ns == _ns(third)
    assert report.largest_gap_ns == 20 * 60 * _NS_PER_SECOND


def test_coverage_excludes_rows_after_now_ns() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    midnight_local_utc = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS)
    first = midnight_local_utc + dt.timedelta(hours=1)
    later = first + dt.timedelta(hours=5)

    _push_metar_row(accumulator, instant_utc=first, temp_c_tenths=100)
    _push_metar_row(accumulator, instant_utc=later, temp_c_tenths=200)

    report = accumulator.coverage(_ns(first), expected_cadence_ns=300 * _NS_PER_SECOND)
    assert report.first_observed_ns == _ns(first)
    assert report.last_observed_ns == _ns(first)
    assert report.largest_gap_ns is None


def test_coverage_largest_gap_is_none_with_fewer_than_two_rows() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    only = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)
    _push_metar_row(accumulator, instant_utc=only, temp_c_tenths=100)

    report = accumulator.coverage(_ns(only), expected_cadence_ns=300 * _NS_PER_SECOND)
    assert report.first_observed_ns == report.last_observed_ns == _ns(only)
    assert report.largest_gap_ns is None
