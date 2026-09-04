"""Unit tests for `RunningExtremeAccumulator` -- BL-24 Seam A / A-2.

The differential oracle is `build_running_max_days`
(`scripts/analysis/pmr_climatology_study.py:351`), reused rather than
reimplemented -- see `docs/plans/BL24_LIVE_RT_2026-09-04.md` §3 and
amendment A3 (hour-resolution comparison), extended by amendment A13
(interval-valued `R(t)`).
"""

from __future__ import annotations

import datetime as dt
import math
from fractions import Fraction
from types import ModuleType

import pytest

from breezy.domain.temperature import (
    max_rounded_f_below,
    round_half_up_f,
)
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


def test_a_29c_row_has_closed_upper_bound_85_not_the_naive_exclusive_85() -> None:
    """Worked example from the Seam A-2 defect report.

    A 29 C row's real interval is `[28.5, 29.5)` C. 29.4 C is inside that
    interval and rounds to 85 F, so the achievable maximum is 85 -- CLOSED,
    i.e. `upper_f == 85`, not an exclusive bound that would (wrongly)
    exclude 85 from the reachable set.
    """
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    instant = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)

    _push_integer_row(accumulator, instant_utc=instant, temp_c_tenths=290)

    running_max = accumulator.value_at(_ns(instant))
    assert running_max is not None
    assert running_max.exact_f is None
    assert running_max.lower_f == 83
    assert running_max.upper_f == 85
    # 29.4 C is a real, achievable value strictly inside `[28.5, 29.5)` C.
    assert round_half_up_f(294) == 85


def test_an_integer_row_that_straddles_two_f_rungs_has_a_two_wide_closed_interval() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    instant = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)

    # 10.0 C, full width 1.0 C (`[9.5, 10.5)` C). 10.4 C is achievable and
    # rounds to 51 F, so the closed interval is `[49, 51]`.
    _push_integer_row(accumulator, instant_utc=instant, temp_c_tenths=100)

    running_max = accumulator.value_at(_ns(instant))
    assert running_max is not None
    assert running_max.exact_f is None
    assert running_max.lower_f == 49
    assert running_max.upper_f == 51
    assert round_half_up_f(104) == 51
    ladder = [(None, 49), (49, 50), (50, 51), (51, None)]
    assert running_max.spans(ladder) is True


def test_a_later_metar_row_that_exceeds_a_wide_integer_row_collapses() -> None:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    climate_day = dt.date(2025, 1, 15)
    first = _local_midnight_utc(climate_day, _LAX_STD_OFFSET_HOURS) + dt.timedelta(hours=1)
    second = first + dt.timedelta(minutes=5)

    _push_integer_row(accumulator, instant_utc=first, temp_c_tenths=100)
    wide = accumulator.value_at(_ns(first))
    assert wide is not None
    assert wide.lower_f == 49
    assert wide.upper_f == 51

    # A METAR reading clearly above the integer row's interval -- the
    # running max collapses to an exact value.
    _push_metar_row(accumulator, instant_utc=second, temp_c_tenths=300)
    collapsed = accumulator.value_at(_ns(second))
    assert collapsed is not None
    assert collapsed.exact_f is not None
    assert collapsed.lower_f == collapsed.upper_f == collapsed.exact_f
    assert collapsed.source_observed_at_ns == _ns(second)


def test_running_max_is_frozen_with_a_closed_closed_interval() -> None:
    running_max = RunningMax(
        lower_f=46, upper_f=48, exact_f=None, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.lower_f == 46
    assert running_max.upper_f == 48
    with pytest.raises(AttributeError):
        running_max.lower_f = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# `max_rounded_f_below` -- exhaustive sweep against direct enumeration
# (BL-24 Seam A-2 fix). Every integer C from -40 to 45; for each, a fine
# real-valued grid (hundredths, plus values approaching `T + 0.5` from
# below) inside `[T - 0.5, T + 0.5)` C is rounded with the SAME formula the
# production code uses (`round_half_up_f`, exact `Fraction` arithmetic --
# never `float`), and the observed min/max must equal the closed-form
# `RunningMax` bounds: `round_half_up_f` at the closed lower end, and
# `max_rounded_f_below` at the exclusive upper end.
# ---------------------------------------------------------------------------


def _round_half_up_f_exact(c_tenths: Fraction) -> int:
    fahrenheit = (c_tenths / 10) * 9 / 5 + 32
    return math.floor(fahrenheit + Fraction(1, 2))


@pytest.mark.parametrize("whole_c", range(-40, 46))
def test_bounds_match_exhaustive_enumeration_for_every_whole_celsius_degree(
    whole_c: int,
) -> None:
    lower_c_tenths = whole_c * 10 - 5
    upper_c_tenths_exclusive = whole_c * 10 + 5

    observed: set[int] = set()
    # A grid at 1/100-of-a-tenth-C resolution across the full half-open
    # interval (1000 points for a 10-tenths-wide interval).
    steps = (upper_c_tenths_exclusive - lower_c_tenths) * 100
    for step in range(steps):
        observed.add(_round_half_up_f_exact(lower_c_tenths + Fraction(step, 100)))
    # Values approaching the exclusive upper bound arbitrarily closely.
    observed.add(
        _round_half_up_f_exact(Fraction(upper_c_tenths_exclusive) - Fraction(1, 10**9))
    )

    expected_lower = round_half_up_f(lower_c_tenths)
    expected_upper = max_rounded_f_below(upper_c_tenths_exclusive)

    assert min(observed) == expected_lower, whole_c
    assert max(observed) == expected_upper, whole_c


# ---------------------------------------------------------------------------
# Differential: `upper_f` for a non-METAR (interval) row matches the offline
# oracle `build_running_max_days` fed the WORST-CASE (highest-rounding) real
# value strictly inside that row's interval -- extends the existing
# all-METAR differential (above) to interval rows, which it did not cover.
# ---------------------------------------------------------------------------


def test_agrees_with_the_offline_oracle_at_the_worst_case_for_interval_rows(
    study: ModuleType,
) -> None:
    climate_day = dt.date(2025, 1, 15)
    tz = dt.timezone(dt.timedelta(hours=_LAX_STD_OFFSET_HOURS))
    midnight_local = dt.datetime.combine(climate_day, dt.time(0, 0), tzinfo=tz)

    metar_tenths_by_hour = {2: 50, 14: 100}
    integer_tenths_by_hour = {0: 290, 6: -50, 10: 449, 20: 0}
    half_width_c_tenths = _INTEGER_PRECISION_C_TENTHS // 2
    epsilon_c_tenths = Fraction(1, 10**6)

    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_LAX_STD_OFFSET_HOURS)
    oracle_rows = []

    for hour, tenths in sorted(metar_tenths_by_hour.items()):
        instant = (midnight_local + dt.timedelta(hours=hour)).astimezone(dt.UTC)
        _push_metar_row(accumulator, instant_utc=instant, temp_c_tenths=tenths)
        oracle_rows.append(
            study.MetarTemperature(
                city="LAX",
                valid_utc=instant,
                climate_day=climate_day,
                temp_c_tenths=tenths,
                temp_f=study.c_tenths_to_f(tenths),
                rounded_f=study.round_half_up_f(tenths),
                raw_metar=_metar_row(
                    station="LAX",
                    valid=instant.strftime("%Y-%m-%d %H:%M"),
                    t_group=_f_to_t_group(tenths),
                )["metar"],
            )
        )

    for hour, tenths in sorted(integer_tenths_by_hour.items()):
        instant = (midnight_local + dt.timedelta(hours=hour)).astimezone(dt.UTC)
        _push_integer_row(accumulator, instant_utc=instant, temp_c_tenths=tenths)
        # The worst-case real value strictly inside `[.., T + half_width)`:
        # approaches the exclusive upper bound arbitrarily closely. A METAR
        # `T`-group cannot encode a non-tenths value, so the oracle row is
        # built directly rather than round-tripped through the ASCII parser.
        worst_case_c_tenths = Fraction(tenths + half_width_c_tenths) - epsilon_c_tenths
        worst_case_f = (worst_case_c_tenths / 10) * 9 / 5 + 32
        oracle_rows.append(
            study.MetarTemperature(
                city="LAX",
                valid_utc=instant,
                climate_day=climate_day,
                temp_c_tenths=tenths,
                temp_f=float(worst_case_f),
                rounded_f=study.round_half_up_f(float(worst_case_c_tenths)),
                raw_metar="<synthetic worst-case oracle row>",
            )
        )

    (oracle_day,) = study.build_running_max_days(
        city="LAX",
        temperatures=tuple(oracle_rows),
        std_utc_offset_hours=_LAX_STD_OFFSET_HOURS,
    )

    checked_hours = sorted({*metar_tenths_by_hour, *integer_tenths_by_hour})
    for hour in checked_hours:
        hour_end_local = midnight_local + dt.timedelta(hours=hour + 1)
        hour_end_ns = _ns(hour_end_local.astimezone(dt.UTC)) - 1
        running_max = accumulator.value_at(hour_end_ns)
        assert running_max is not None, hour
        assert running_max.upper_f == oracle_day.running_max_f[hour], hour


# ---------------------------------------------------------------------------
# `spans` -- containment against the ACTUAL (non-width-aligned) venue ladder.
# `bounds` is CLOSED-CLOSED, the same convention `WeatherBucketFacts.lower_f`
# / `upper_f` expose (verified against 114/114 real ladders) -- so these
# fixtures are expressed exactly as `WeatherBucketFacts` would hand them to
# a caller, not the venue's half-open display convention.
# ---------------------------------------------------------------------------

#: A Polymarket.us-style phased ladder expressed CLOSED-CLOSED: open-ended
#: tails, oddly-sized rungs. Equivalent half-open venue labels in comments.
_PHASED_LADDER: list[tuple[int | None, int | None]] = [
    (None, 78),  # "lt79f"
    (79, 90),
    (91, 91),  # a genuinely 1 F-wide rung, phased oddly against its neighbours
    (92, 93),
    (94, None),  # "gte94f"
]


def test_spans_is_false_when_the_interval_fits_one_ladder_rung() -> None:
    running_max = RunningMax(
        lower_f=80, upper_f=80, exact_f=80, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is False


def test_spans_is_true_when_the_interval_crosses_two_ladder_rungs() -> None:
    # [90, 92] crosses the 79-90, 91-91, and 92-93 rungs.
    running_max = RunningMax(
        lower_f=90, upper_f=92, exact_f=None, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is True


def test_spans_fits_the_narrow_odd_rung_that_a_uniform_width_would_miss() -> None:
    """`[91, 91]` is a genuine single rung on the real ladder."""
    running_max = RunningMax(
        lower_f=91, upper_f=91, exact_f=91, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is False


def test_spans_is_true_when_an_endpoint_falls_in_no_listed_rung() -> None:
    """Fails closed: a gap in the caller's ladder is never assumed safe."""
    sparse_ladder: list[tuple[int | None, int | None]] = [(None, 49), (60, None)]
    running_max = RunningMax(
        lower_f=55, upper_f=55, exact_f=55, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(sparse_ladder) is True


def test_spans_handles_open_ended_tail_rungs() -> None:
    running_max = RunningMax(
        lower_f=95, upper_f=95, exact_f=95, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(_PHASED_LADDER) is False

    below_all = RunningMax(
        lower_f=10, upper_f=10, exact_f=10, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert below_all.spans(_PHASED_LADDER) is False


# ---------------------------------------------------------------------------
# `spans` against `WeatherBucketFacts`-shaped closed rungs directly (item e).
# ---------------------------------------------------------------------------


def test_spans_refuses_an_interval_that_falls_between_two_wbf_style_rungs() -> None:
    # Rungs "(.., 84]" and "[85, ..)" -- an interval [84, 85] straddles both.
    wbf_ladder: list[tuple[int | None, int | None]] = [(None, 84), (85, None)]
    running_max = RunningMax(
        lower_f=84, upper_f=85, exact_f=None, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(wbf_ladder) is True


def test_spans_is_false_when_wholly_inside_one_wbf_style_rung() -> None:
    wbf_ladder: list[tuple[int | None, int | None]] = [(80, 84)]
    running_max = RunningMax(
        lower_f=83, upper_f=84, exact_f=None, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(wbf_ladder) is False


def test_spans_fails_closed_when_an_endpoint_matches_no_wbf_style_rung() -> None:
    wbf_ladder: list[tuple[int | None, int | None]] = [(80, 84), (90, 95)]
    running_max = RunningMax(
        lower_f=86, upper_f=86, exact_f=86, source_observed_at_ns=0, source_received_at_ns=0
    )
    assert running_max.spans(wbf_ladder) is True


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
