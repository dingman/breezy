"""Property tests for ``build_running_max_days`` -- the fold under the evidence.

``scripts/analysis/pmr_climatology_study.py:351`` produced every conditional
cell in ``docs/evidence/pmr_climatology_2026-09-01.md``, and a planned ingest
increment intends to PORT its logic into the bot. This module pins the
properties that table's meaning depends on, in the places
``tests/unit/test_pmr_climatology_study.py`` does not reach:

* the gap fill (interior, leading, trailing) at ``:386-387`` / ``:397-398``
  -- a carried value is "no rise yet", never "not looking";
* strict completeness (``:341``) -- a carried hour must NOT count as covered;
* end-of-hour semantics when an hour holds several observations;
* the deliberate rounded/unrounded split at ``:326-336``, including the
  direction of the bias (``hour_of_rounded_max <= hour_of_max``, always);
* the fixed standard offset under daylight saving, at the DAY level rather
  than only inside ``local_standard_hour``;
* single-observation days, exact local-midnight instants, and a fractional
  standard offset (no registry site has one today -- ``sites.toml`` carries
  only -5.0, -6.0 and -8.0 -- but the signature accepts a float).

Helpers are imported from the existing study test module rather than forked,
so the fixture shape stays single-sourced. Nothing here touches the network
or the on-disk ASOS archive.
"""

from __future__ import annotations

import datetime as dt
from types import ModuleType
from typing import Any

import pytest

from tests.unit.test_pmr_climatology_study import (
    _LAX_STD_OFFSET_HOURS,
    _days,
    _f_to_t_group,
    _load_study_module,
    _metar_row,
)

#: A synthetic half-hour offset. No Breezy site uses one (see module docstring);
#: it is here because `std_utc_offset_hours` is typed `float` and a ported
#: implementation must not quietly assume integral offsets.
_HALF_HOUR_OFFSET_HOURS = -5.5


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return _load_study_module()


def _rows_at_local_hours(
    *,
    tenths_by_hour: dict[int, int],
    climate_day: dt.date,
    std_utc_offset_hours: float = _LAX_STD_OFFSET_HOURS,
    city: str = "LAX",
    minute: int = 0,
) -> list[dict[str, str]]:
    """Archive rows placed at chosen LOCAL-STANDARD hours of one climate day."""
    tz = dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    midnight_local = dt.datetime.combine(climate_day, dt.time(0, 0), tzinfo=tz)
    rows: list[dict[str, str]] = []
    for hour, tenths in sorted(tenths_by_hour.items()):
        instant = midnight_local + dt.timedelta(hours=hour, minutes=minute)
        rows.append(
            _metar_row(
                station=city,
                valid=instant.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M"),
                t_group=_f_to_t_group(tenths),
            )
        )
    return rows


def _one_day(
    study: ModuleType,
    rows: list[dict[str, str]],
    *,
    std_utc_offset_hours: float = _LAX_STD_OFFSET_HOURS,
    city: str = "LAX",
) -> Any:
    (day,) = _days(study, city=city, std_utc_offset_hours=std_utc_offset_hours, rows=rows)
    return day


def _assert_non_decreasing(series: tuple[int | None, ...]) -> None:
    observed = [value for value in series if value is not None]
    assert observed == sorted(observed), f"running max fell: {series}"


# ---------------------------------------------------------------------------
# Gap handling: interior carry-forward, leading None, trailing fill
# ---------------------------------------------------------------------------


def test_an_interior_gap_carries_the_previous_running_max_forward(
    study: ModuleType,
) -> None:
    """Hours 7-9 have no observation: R there is R(6), never R(10).

    Filling an empty hour from the FOLLOWING observation would be look-ahead
    dressed as interpolation -- every conditional probability in the evidence
    table would then be conditioned on a future the trader cannot see.
    """
    rows = _rows_at_local_hours(
        tenths_by_hour={6: 100, 10: 200, 11: 200},
        climate_day=dt.date(2025, 1, 15),
    )
    day = _one_day(study, rows)

    cool = study.round_half_up_f(100)
    warm = study.round_half_up_f(200)
    assert cool < warm, "fixture must actually rise across the gap"
    assert day.running_max_f[6] == cool
    assert day.running_max_f[7:10] == (cool, cool, cool)
    assert day.running_max_f[10] == warm
    _assert_non_decreasing(day.running_max_f)


def test_a_leading_gap_stays_none_and_is_never_backfilled(study: ModuleType) -> None:
    """Before the first observation R(t) is UNDEFINED, not zero and not the max."""
    rows = _rows_at_local_hours(
        tenths_by_hour={5: 150, 6: 300},
        climate_day=dt.date(2025, 1, 15),
    )
    day = _one_day(study, rows)

    assert day.running_max_f[:5] == (None,) * 5
    assert day.running_max_f[5] == study.round_half_up_f(150)
    assert day.covered_hours == 2
    assert not study.is_complete_day(day)


def test_the_trailing_hours_carry_the_final_running_max(study: ModuleType) -> None:
    """After the last observation R(t) holds; it is neither None nor reset."""
    rows = _rows_at_local_hours(
        tenths_by_hour={hour: 100 + 5 * hour for hour in range(13)},
        climate_day=dt.date(2025, 1, 15),
    )
    day = _one_day(study, rows)

    final = study.round_half_up_f(100 + 5 * 12)
    assert day.observed_max_f == final
    assert day.running_max_f[12] == final
    assert day.running_max_f[13:] == (final,) * 11
    assert day.covered_hours == 13
    assert not study.is_complete_day(day)


def test_a_carried_hour_is_not_a_covered_hour(study: ModuleType) -> None:
    """A hole must make the day INCOMPLETE even though R(t) is stated there.

    This is the distinction `is_complete_day` (:341) exists to protect: hour 14
    carries a value, so the series is not ragged, but nothing was OBSERVED
    there. Counting the carry as coverage would silently mix "no rise yet"
    with "nobody was looking" in every cell of the table.
    """
    tenths_by_hour = {hour: 100 for hour in range(24) if hour != 14}
    day = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour=tenths_by_hour, climate_day=dt.date(2025, 1, 15)),
    )

    assert day.running_max_f[14] == study.round_half_up_f(100)
    assert day.observation_count == 23
    assert day.covered_hours == 23
    assert not study.is_complete_day(day)


# ---------------------------------------------------------------------------
# No look-ahead: a late spike cannot reach backwards
# ---------------------------------------------------------------------------


def test_a_late_spike_never_raises_an_earlier_hour(study: ModuleType) -> None:
    """Same day, one reading changed at hour 20: hours 0-19 must be identical.

    Complements the truncation test in `test_pmr_climatology_study.py` -- that
    one removes the future, this one keeps the day's length fixed and only
    makes the future hotter, which is the shape a leak in the fold (e.g. a
    `max()` over the whole day written into every cell) would show up as.
    """
    flat = {hour: 100 for hour in range(24)}
    spiked = dict(flat)
    spiked[20] = 400

    baseline = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour=flat, climate_day=dt.date(2025, 1, 15)),
    )
    with_spike = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour=spiked, climate_day=dt.date(2025, 1, 15)),
    )

    assert with_spike.running_max_f[:20] == baseline.running_max_f[:20]
    assert with_spike.running_max_f[20] > baseline.running_max_f[20]
    assert with_spike.running_max_f[23] == with_spike.observed_max_f
    assert with_spike.hour_of_max == 20


def test_a_gap_before_a_spike_is_filled_from_the_past_not_the_spike(
    study: ModuleType,
) -> None:
    """The gap fill at :386-387 runs BEFORE the current row updates R."""
    rows = _rows_at_local_hours(
        tenths_by_hour={8: 100, 20: 400},
        climate_day=dt.date(2025, 1, 15),
    )
    day = _one_day(study, rows)

    cool = study.round_half_up_f(100)
    assert day.running_max_f[8:20] == (cool,) * 12
    assert day.running_max_f[20] == study.round_half_up_f(400)


# ---------------------------------------------------------------------------
# End-of-hour semantics
# ---------------------------------------------------------------------------


def test_r_at_an_hour_is_its_value_at_the_END_of_that_hour(
    study: ModuleType,
) -> None:
    """Several observations inside one hour: the hour's cell holds them all."""
    tz = dt.timezone(dt.timedelta(hours=_LAX_STD_OFFSET_HOURS))
    midnight_local = dt.datetime.combine(dt.date(2025, 1, 15), dt.time(0, 0), tzinfo=tz)
    rows = [
        _metar_row(
            station="LAX",
            valid=(midnight_local + dt.timedelta(hours=10, minutes=minute))
            .astimezone(dt.UTC)
            .strftime("%Y-%m-%d %H:%M"),
            t_group=_f_to_t_group(tenths),
        )
        for minute, tenths in ((5, 100), (35, 300), (55, 200))
    ]
    day = _one_day(study, rows)

    assert day.running_max_f[10] == study.round_half_up_f(300)
    assert day.observation_count == 3
    assert day.covered_hours == 1, "covered_hours counts HOURS, not observations"
    assert day.hour_of_max == 10
    assert day.instant_of_max == (midnight_local + dt.timedelta(hours=10, minutes=35)).astimezone(
        dt.UTC
    )


def test_the_daily_statistics_agree_with_the_series_and_the_rows(
    study: ModuleType,
) -> None:
    tenths_by_hour = {hour: 100 + (17 * hour) % 130 for hour in range(24)}
    day = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour=tenths_by_hour, climate_day=dt.date(2025, 1, 15)),
    )

    assert study.is_complete_day(day)
    assert day.observed_max_f == max(
        study.round_half_up_f(tenths) for tenths in tenths_by_hour.values()
    )
    assert day.observed_max_unrounded_f == max(
        study.c_tenths_to_f(tenths) for tenths in tenths_by_hour.values()
    )
    assert day.running_max_f[23] == day.observed_max_f
    assert max(value for value in day.running_max_f if value is not None) == (day.observed_max_f)
    _assert_non_decreasing(day.running_max_f)


# ---------------------------------------------------------------------------
# The rounded/unrounded split (:326-336) -- the documented tie bias
# ---------------------------------------------------------------------------


def test_a_rounding_tie_puts_the_rounded_hour_before_the_unrounded_one(
    study: ModuleType,
) -> None:
    """10.0C (50.00F) and 10.2C (50.36F) both round to 50F.

    `hour_of_max` must follow the TENTHS (hour 16, the physical peak);
    `hour_of_rounded_max` follows the rounded series and lands at hour 8.
    Pinning the gap is the point: the study carries both so the tie-driven
    disagreement against the CLI-stated time is visible, not assumed away.
    """
    tenths_by_hour = {hour: 50 for hour in range(24)}
    tenths_by_hour[8] = 100
    tenths_by_hour[16] = 102
    day = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour=tenths_by_hour, climate_day=dt.date(2025, 1, 15)),
    )

    assert study.round_half_up_f(100) == study.round_half_up_f(102) == 50
    assert study.c_tenths_to_f(102) > study.c_tenths_to_f(100)
    assert day.observed_max_f == 50
    assert day.observed_max_unrounded_f == study.c_tenths_to_f(102)
    assert day.hour_of_max == 16, "T* must follow the tenths, not the rounded tie"
    assert day.hour_of_rounded_max == 8, "the rounded rule breaks the tie early"
    # R(t) itself stays in settlement units and is unaffected by the split.
    assert day.running_max_f[8] == 50
    assert day.running_max_f[16] == 50


@pytest.mark.parametrize(
    "tenths_by_hour",
    [
        {hour: 50 for hour in range(24)},  # a completely flat day
        {hour: 100 + hour for hour in range(24)},  # monotone rise
        {hour: 300 - 4 * hour for hour in range(24)},  # monotone fall
        {**{hour: 50 for hour in range(24)}, 3: 200, 19: 201},  # near-tie, late peak
        {**{hour: 50 for hour in range(24)}, 3: 201, 19: 200},  # near-tie, early peak
    ],
)
def test_the_rounded_hour_never_lands_after_the_unrounded_hour(
    study: ModuleType, tenths_by_hour: dict[int, int]
) -> None:
    """`hour_of_rounded_max <= hour_of_max`, for every day shape.

    Rounding is monotone, so the rounded maximum is already attained at the
    unrounded peak; a first-attaining rule over the rounded series can only
    fire at or before it. The bias documented at :326-330 therefore has ONE
    direction -- early -- and a ported implementation that could bias late
    would be a different statistic.
    """
    day = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour=tenths_by_hour, climate_day=dt.date(2025, 1, 15)),
    )

    assert day.hour_of_rounded_max <= day.hour_of_max
    assert day.running_max_f[day.hour_of_rounded_max] == day.observed_max_f


def test_the_first_hour_attaining_the_unrounded_max_wins_the_tie(
    study: ModuleType,
) -> None:
    """Exact unrounded ties resolve to the EARLIER hour (strict `>` at :391)."""
    tenths_by_hour = {hour: 50 for hour in range(24)}
    tenths_by_hour[11] = 250
    tenths_by_hour[17] = 250
    day = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour=tenths_by_hour, climate_day=dt.date(2025, 1, 15)),
    )

    assert day.hour_of_max == 11
    assert day.hour_of_rounded_max == 11


# ---------------------------------------------------------------------------
# Boundaries: single observation, exact local midnight, fixed offset under DST
# ---------------------------------------------------------------------------


def test_a_single_observation_day_states_everything_off_that_one_reading(
    study: ModuleType,
) -> None:
    tz = dt.timezone(dt.timedelta(hours=_LAX_STD_OFFSET_HOURS))
    instant_local = dt.datetime.combine(dt.date(2025, 1, 15), dt.time(13, 0), tzinfo=tz)
    day = _one_day(
        study,
        _rows_at_local_hours(tenths_by_hour={13: 175}, climate_day=dt.date(2025, 1, 15)),
    )

    expected = study.round_half_up_f(175)
    assert day.observation_count == 1
    assert day.covered_hours == 1
    assert not study.is_complete_day(day)
    assert day.running_max_f[:13] == (None,) * 13
    assert day.running_max_f[13:] == (expected,) * 11
    assert day.observed_max_f == expected
    assert day.observed_max_unrounded_f == study.c_tenths_to_f(175)
    assert day.hour_of_max == day.hour_of_rounded_max == 13
    assert day.instant_of_max == instant_local.astimezone(dt.UTC)


def test_local_standard_midnight_opens_the_next_climate_day(
    study: ModuleType,
) -> None:
    """00:00 local standard belongs to the NEW day at hour 0; 23:59 to the old.

    LAX standard offset is -8, so the boundary instant is 08:00Z. This is the
    same boundary `breezy.ingest.records._climate_day_end_ns` computes.
    """
    rows = [
        _metar_row(station="LAX", valid="2025-01-16 07:59", t_group=_f_to_t_group(90)),
        _metar_row(station="LAX", valid="2025-01-16 08:00", t_group=_f_to_t_group(60)),
    ]
    days = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)
    by_day = {day.climate_day: day for day in days}

    assert set(by_day) == {dt.date(2025, 1, 15), dt.date(2025, 1, 16)}
    first = by_day[dt.date(2025, 1, 15)]
    second = by_day[dt.date(2025, 1, 16)]
    assert first.hour_of_max == 23
    assert first.running_max_f[23] == study.round_half_up_f(90)
    assert first.running_max_f[:23] == (None,) * 23
    # The reset at the boundary: the 09:00C reading does not reach hour 0 of
    # the new day even though it is the immediately preceding observation.
    assert second.running_max_f[0] == study.round_half_up_f(60)
    assert second.observed_max_f == study.round_half_up_f(60)


def test_a_july_climate_day_still_uses_the_standard_offset(study: ModuleType) -> None:
    """DST is deliberately NOT applied -- the axis is PST in July, not PDT.

    Under PDT (-7) the 23:00Z peak would sit at hour 16 and the 07:30Z reading
    would fall on 16 July. Under the fixed standard offset (-8) they are hour
    15 and hour 23 of 15 July. Pinning the standard reading is what keeps the
    study's hour axis aligned with `_climate_day_end_ns` year-round.
    """
    rows = [
        _metar_row(station="LAX", valid="2025-07-15 16:00", t_group=_f_to_t_group(150)),
        _metar_row(station="LAX", valid="2025-07-15 23:00", t_group=_f_to_t_group(320)),
        _metar_row(station="LAX", valid="2025-07-16 07:30", t_group=_f_to_t_group(200)),
    ]
    days = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    (day,) = days
    assert day.climate_day == dt.date(2025, 7, 15)
    assert day.observation_count == 3
    assert day.covered_hours == 3
    assert day.hour_of_max == 15, "PDT would put the peak at hour 16"
    assert day.running_max_f[8] == study.round_half_up_f(150)
    assert day.running_max_f[15] == study.round_half_up_f(320)
    assert day.running_max_f[23] == study.round_half_up_f(320)


def test_a_fractional_standard_offset_still_yields_a_full_24_hour_axis(
    study: ModuleType,
) -> None:
    """No Breezy site has a half-hour offset today, but the signature allows one."""
    tenths_by_hour = {hour: 100 + hour for hour in range(24)}
    day = _one_day(
        study,
        _rows_at_local_hours(
            tenths_by_hour=tenths_by_hour,
            climate_day=dt.date(2025, 3, 20),
            std_utc_offset_hours=_HALF_HOUR_OFFSET_HOURS,
        ),
        std_utc_offset_hours=_HALF_HOUR_OFFSET_HOURS,
    )

    assert day.climate_day == dt.date(2025, 3, 20)
    assert day.covered_hours == 24
    assert study.is_complete_day(day)
    assert day.hour_of_max == 23
    assert day.observed_max_f == study.round_half_up_f(123)
    _assert_non_decreasing(day.running_max_f)


def test_days_are_returned_in_ascending_climate_day_order(study: ModuleType) -> None:
    """Callers index the result positionally; the sort at :370 is load-bearing."""
    rows: list[dict[str, str]] = []
    for offset_days in (2, 0, 1):
        rows.extend(
            _rows_at_local_hours(
                tenths_by_hour={12: 100 + offset_days},
                climate_day=dt.date(2025, 1, 15) + dt.timedelta(days=offset_days),
            )
        )
    days = _days(study, city="LAX", std_utc_offset_hours=_LAX_STD_OFFSET_HOURS, rows=rows)

    assert [day.climate_day for day in days] == [
        dt.date(2025, 1, 15),
        dt.date(2025, 1, 16),
        dt.date(2025, 1, 17),
    ]


# ---------------------------------------------------------------------------
# Differential: the fold vs an independent brute-force definition of R(t)
# ---------------------------------------------------------------------------


def _reference_day(
    study: ModuleType, rows: list[Any], std_utc_offset_hours: float
) -> dict[str, Any]:
    """R(t) recomputed from the DEFINITION, with no accumulator at all.

    "R at hour h = the maximum rounded reading over every observation whose
    local-standard hour is <= h, undefined when there is none." Written this
    way it cannot share a bug with the single forward pass at :380-398: the
    gap fill, the tail fill and the leading `None` all fall out of the
    definition instead of being separate branches.
    """
    ordered = sorted(rows, key=lambda row: row.valid_utc)
    hours = [study.local_standard_hour(row.valid_utc, std_utc_offset_hours) for row in ordered]
    series: list[int | None] = []
    for hour in range(24):
        so_far = [row.rounded_f for row, row_hour in zip(ordered, hours) if row_hour <= hour]
        series.append(max(so_far) if so_far else None)
    max_unrounded = max(row.temp_f for row in ordered)
    max_rounded = max(row.rounded_f for row in ordered)
    first_unrounded = next(
        index for index, row in enumerate(ordered) if row.temp_f == max_unrounded
    )
    first_rounded = next(index for index, row in enumerate(ordered) if row.rounded_f == max_rounded)
    return {
        "running_max_f": tuple(series),
        "observed_max_f": max_rounded,
        "observed_max_unrounded_f": max_unrounded,
        "hour_of_max": hours[first_unrounded],
        "instant_of_max": ordered[first_unrounded].valid_utc,
        "hour_of_rounded_max": hours[first_rounded],
        "observation_count": len(ordered),
        "covered_hours": len(set(hours)),
    }


def test_the_fold_agrees_with_the_brute_force_definition_of_r(
    study: ModuleType,
) -> None:
    """Randomised (fixed seed) differential over multi-day, ragged fixtures.

    Offsets include a half-hour and a quarter-hour value: no Breezy site has
    one today, but a ported implementation must not assume integral offsets.
    Dates straddle daylight saving, and observation minutes are arbitrary, so
    several observations can share an hour and whole hours can be empty.
    """
    import random

    rng = random.Random(20260901)
    checked_days = 0
    for _ in range(60):
        offset = rng.choice([-5.0, -6.0, -8.0, -5.5, 5.75])
        start = dt.date(2024, 1, 1) + dt.timedelta(days=rng.randrange(700))
        tz = dt.timezone(dt.timedelta(hours=offset))
        midnight_local = dt.datetime.combine(start, dt.time(0, 0), tzinfo=tz)
        rows = [
            _metar_row(
                station="LAX",
                valid=(midnight_local + dt.timedelta(minutes=rng.randrange(3 * 1440)))
                .astimezone(dt.UTC)
                .strftime("%Y-%m-%d %H:%M"),
                t_group=_f_to_t_group(rng.randrange(-400, 450)),
            )
            for _ in range(rng.randrange(1, 40))
        ]
        temperatures, drops = study.metar_temperatures(
            city="LAX", rows=rows, std_utc_offset_hours=offset
        )
        assert not drops, f"fixture rows failed to parse: {drops}"
        days = study.build_running_max_days(
            city="LAX", temperatures=temperatures, std_utc_offset_hours=offset
        )
        by_day: dict[dt.date, list[Any]] = {}
        for temperature in temperatures:
            by_day.setdefault(temperature.climate_day, []).append(temperature)
        assert [day.climate_day for day in days] == sorted(by_day)

        for day in days:
            expected = _reference_day(study, by_day[day.climate_day], offset)
            for field, want in expected.items():
                assert getattr(day, field) == want, (
                    f"{field} disagrees with the definition on {day.climate_day} at offset {offset}"
                )
            assert day.hour_of_rounded_max <= day.hour_of_max
            _assert_non_decreasing(day.running_max_f)
            checked_days += 1

    assert checked_days > 100, "the fixture must exercise many days, not a handful"


def test_no_temperatures_yields_no_days(study: ModuleType) -> None:
    assert (
        study.build_running_max_days(
            city="LAX", temperatures=(), std_utc_offset_hours=_LAX_STD_OFFSET_HOURS
        )
        == ()
    )
