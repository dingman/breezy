"""FB-R3 (L-13): ``obs_so_far`` emulates the LIVE observation path from the 1-min ASOS archive.

Live path (cited, not copied): ``breezy.ingest.nws_observations`` / ``iem_observations`` build
``StationObservation`` rows (tenths of a degree C, 5-minute cadence) and
``breezy.strategy.weather_common.running_extreme`` quantises them with
``breezy.domain.temperature.round_half_up_f``. The builder downsamples the whole-degF 1-min archive
to the live cadence and quantises through the SAME function; anything it cannot reproduce is
refused (never guessed). Synthetic payloads through the production ``ArchiveCache`` writer.
"""

from __future__ import annotations

import datetime as dt
import tracemalloc
from pathlib import Path

import pytest

from breezy.domain.temperature import round_half_up_f
from scripts.analysis import multisource_blend_inputs_obs as obs
from scripts.analysis.forecast_conditional_corpus import OBS_CADENCE_SECONDS
from tests.unit.featbuild_fixtures import (
    NS,
    asos_1min_payload,
    ns,
    utc,
    write_asos_year,
)

_NYC_OFFSET = -5.0
_LAG = 15 * 60 * NS


def _read(
    tmp_path: Path,
    rows: list[tuple[dt.datetime, int | str]],
    *,
    days: dict[dt.date, int] | None = None,
    year: int = 2021,
    routine_minute: int = 0,
) -> obs.ObsYear:
    root = tmp_path / "asos"
    write_asos_year(root, "KMIA", year, asos_1min_payload(rows))
    from scripts.analysis.multisource_blend_features_build import read_only_cache

    cutoffs = days if days is not None else {rows[0][0].date(): ns(utc(year, 12, 31, 23))}
    return obs.read_obs_year(
        read_only_cache(root),
        "KMIA",
        year,
        std_utc_offset_hours=_NYC_OFFSET,
        routine_minute=routine_minute,
        lag_ns=_LAG,
        cutoff_ns_by_day=cutoffs,
    )


# ------------------------------------------------------------------ the quantisation (STOP rule)


def test_the_live_path_is_cited_and_the_obs_cadence_is_the_routine_hourly_cadence() -> None:
    assert "running_extreme" in obs.LIVE_PATH_CITATION
    assert "round_half_up_f" in obs.LIVE_PATH_CITATION
    assert "iem_observations" in obs.LIVE_PATH_CITATION
    assert obs.ROUTINE_OBS_CADENCE_SECONDS == 3600  # FB-R13: routine METAR, not the 5-min grid
    assert obs.DESCRIPTIVE_FIVE_MIN_SECONDS == OBS_CADENCE_SECONDS == 300


def test_every_whole_degf_reproduces_through_the_live_quantisation() -> None:
    for tmpf in range(-80, 141):
        c_tenths = obs.whole_f_to_c_tenths(tmpf)
        assert round_half_up_f(c_tenths) == tmpf, tmpf
        assert obs.live_quantised_f(float(tmpf)) == tmpf


@pytest.mark.parametrize("bad", [72.4, 71.5, float("nan"), float("inf")])
def test_a_reading_the_live_function_cannot_reproduce_is_refused(bad: float) -> None:
    with pytest.raises(obs.ObsQuantisationError):
        obs.live_quantised_f(bad)


def test_an_archive_that_is_not_whole_degf_stops_the_read(tmp_path: Path) -> None:
    rows: list[tuple[dt.datetime, int | str]] = [(utc(2021, 6, 15, 12, 0), "72.4")]

    with pytest.raises(obs.ObsQuantisationError):
        _read(tmp_path, rows)


# ------------------------------------------------------------------ L-13 cadence downsample


def _hourly_minutes(
    hours: range, spikes: dict[tuple[int, int], int] | None = None
) -> list[tuple[dt.datetime, int | str]]:
    """1-min rows for ``hours``: 60 + hour, with ``{(hour, minute): tmpf}`` overrides."""
    spikes = spikes or {}
    return [
        (utc(2021, 6, 15, hour, minute), spikes.get((hour, minute), 60 + hour))
        for hour in hours
        for minute in range(60)
    ]


def test_obs_so_far_uses_routine_metar_minute_only(tmp_path: Path) -> None:
    # distinct value at every minute of 12Z..14Z: only the :53 values may become readings
    rows: list[tuple[dt.datetime, int | str]] = [
        (utc(2021, 6, 15, hour, minute), 50 + (hour - 12) * 10 + minute % 10)
        for hour in (12, 13, 14)
        for minute in range(60)
    ]

    year = _read(tmp_path, rows, routine_minute=53)

    readings = year.readings_by_day[dt.date(2021, 6, 15)]
    assert [r.ts_ns for r in readings] == [ns(utc(2021, 6, 15, h, 53)) for h in (12, 13, 14)]
    assert [r.temp_f for r in readings] == [53.0, 63.0, 73.0]
    assert all(r.available_at_ns == r.ts_ns + _LAG for r in readings)
    assert year.counts["non_routine_minute"] == 3 * 59


def test_obs_specials_and_interval_rows_excluded(tmp_path: Path) -> None:
    rows = _hourly_minutes(range(12, 15), spikes={(12, 20): 99, (13, 7): 98, (13, 53): 71})

    year = _read(tmp_path, rows, routine_minute=53)

    day = dt.date(2021, 6, 15)
    # a special at :20 and an off-minute interval-style reading at :07 never enter the feature ...
    assert [r.temp_f for r in year.readings_by_day[day]] == [72.0, 71.0, 74.0]
    assert max(r.temp_f for r in year.readings_by_day[day]) == 74.0
    # ... they live only in the descriptive 1-min arm
    assert obs.raw_running_max_at(year.raw_max_by_day[day], ns(utc(2021, 6, 15, 14, 59))) == 99.0


def test_descriptive_obs_arms_reported_not_in_features(tmp_path: Path) -> None:
    rows = _hourly_minutes(range(12, 14), spikes={(12, 3): 99, (12, 5): 85, (12, 53): 70})

    year = _read(tmp_path, rows, routine_minute=53)

    day = dt.date(2021, 6, 15)
    anchor = ns(utc(2021, 6, 15, 13, 59))
    assert obs.raw_running_max_at(year.raw_max_by_day[day], anchor) == 99.0
    assert obs.raw_running_max_at(year.five_min_max_by_day[day], anchor) == 85.0
    assert max(r.temp_f for r in year.readings_by_day[day]) == 73.0  # neither arm feeds a feature
    assert 85.0 not in {r.temp_f for r in year.readings_by_day[day]}


def test_routine_minute_helper_reports_modal_minute_per_station() -> None:
    def report(minute: int, count: int) -> list[dt.datetime]:
        return [utc(2021, 6, 1) + dt.timedelta(days=i, minutes=minute) for i in range(count)]

    modal = obs.modal_routine_minute_by_station(
        {"KMIA": [*report(53, 8), *report(54, 3), *report(20, 1)], "KNYC": report(51, 4)}
    )

    assert modal["KMIA"].minute == 53 and modal["KMIA"].n == 12
    assert modal["KMIA"].share == pytest.approx(8 / 12)
    assert modal["KMIA"].histogram == {20: 1, 53: 8, 54: 3}
    assert modal["KNYC"].minute == 51 and modal["KNYC"].share == 1.0
    assert obs.routine_minute_pin_suggestion(modal) == {"KMIA": 53, "KNYC": 51}


def test_routine_minute_helper_breaks_ties_to_the_lower_minute_and_skips_empty() -> None:
    tie = [utc(2021, 6, 1, 0, 52), utc(2021, 6, 2, 0, 53)]

    modal = obs.modal_routine_minute_by_station({"KAAA": tie, "KBBB": []})

    assert modal["KAAA"].minute == 52
    assert "KBBB" not in modal


def test_readings_carry_the_obs_lag_and_never_a_lamp_source(tmp_path: Path) -> None:
    year = _read(tmp_path, [(utc(2021, 6, 15, 12, 0), 70)])

    reading = year.readings_by_day[dt.date(2021, 6, 15)][0]
    assert reading.available_at_ns == reading.ts_ns + _LAG
    assert "lamp" not in reading.source.lower()
    assert reading.source == obs.OBS_SOURCE_LABEL


def test_missing_rows_are_skipped_and_counted(tmp_path: Path) -> None:
    rows: list[tuple[dt.datetime, int | str]] = [
        (utc(2021, 6, 15, 12, 0), 70),
        (utc(2021, 6, 15, 12, 5), "M"),
        (utc(2021, 6, 15, 13, 0), 71),
    ]

    year = _read(tmp_path, rows)

    assert [r.temp_f for r in year.readings_by_day[dt.date(2021, 6, 15)]] == [70.0, 71.0]
    assert year.counts["missing_tmpf"] == 1


# ------------------------------------------------------------------ day scoping


def test_the_climate_day_boundary_is_local_standard_time_never_dst(tmp_path: Path) -> None:
    # 04:00Z in July is 23:00 LST of the PREVIOUS day at UTC-5 (EDT would call it 00:00 same day)
    rows: list[tuple[dt.datetime, int | str]] = [
        (utc(2021, 7, 2, 4, 0), 80),
        (utc(2021, 7, 2, 5, 0), 81),
    ]
    cutoffs = {dt.date(2021, 7, 1): ns(utc(2021, 7, 3)), dt.date(2021, 7, 2): ns(utc(2021, 7, 3))}

    year = _read(tmp_path, rows, days=cutoffs, year=2021)

    assert [r.temp_f for r in year.readings_by_day[dt.date(2021, 7, 1)]] == [80.0]
    assert [r.temp_f for r in year.readings_by_day[dt.date(2021, 7, 2)]] == [81.0]


def test_only_requested_days_and_only_readings_up_to_the_cutoff_are_retained(
    tmp_path: Path,
) -> None:
    rows: list[tuple[dt.datetime, int | str]] = [
        (utc(2021, 6, 15, 12, 0), 70),
        (utc(2021, 6, 15, 14, 0), 75),
        (utc(2021, 6, 16, 12, 0), 60),
    ]
    cutoffs = {dt.date(2021, 6, 15): ns(utc(2021, 6, 15, 13))}

    year = _read(tmp_path, rows, days=cutoffs)

    assert list(year.readings_by_day) == [dt.date(2021, 6, 15)]
    assert [r.temp_f for r in year.readings_by_day[dt.date(2021, 6, 15)]] == [70.0]
    assert year.counts["day_not_requested"] >= 1


def test_a_station_year_is_streamed_with_a_bounded_peak(tmp_path: Path) -> None:
    # a whole fake year of 1-min rows (~525 k) must never be resident as parsed rows
    start = utc(2021, 1, 1)
    minutes = 365 * 24 * 60
    body = ["station,station_name,valid(UTC),tmpf,dwpf"]
    for i in range(minutes):
        when = start + dt.timedelta(minutes=i)
        body.append(f"MIA,T,{when:%Y-%m-%d %H:%M},{60 + (i // 1440) % 20},50")
    payload = ("\n".join(body) + "\n").encode("utf-8")
    root = tmp_path / "asos"
    from breezy.persistence.archive_cache import iem_asos_1min_request
    from tests.unit.featbuild_fixtures import write_cache_entry

    write_cache_entry(root, iem_asos_1min_request("KMIA", 2021), payload)
    del body
    from scripts.analysis.multisource_blend_features_build import read_only_cache

    cache = read_only_cache(root)
    tracemalloc.start()
    tracemalloc.reset_peak()
    year = obs.read_obs_year(
        cache,
        "KMIA",
        2021,
        std_utc_offset_hours=_NYC_OFFSET,
        routine_minute=0,
        lag_ns=_LAG,
        cutoff_ns_by_day={dt.date(2021, 6, 15): ns(utc(2021, 6, 15, 15))},
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(year.readings_by_day[dt.date(2021, 6, 15)]) > 0
    # the payload itself is resident once (the cache returns bytes); parsed rows must not be
    assert peak < 1.6 * len(payload), f"peak {peak} bytes vs payload {len(payload)}: not streamed"
