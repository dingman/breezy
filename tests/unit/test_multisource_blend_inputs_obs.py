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
        cadence_seconds=300,
        lag_ns=_LAG,
        cutoff_ns_by_day=cutoffs,
    )


# ------------------------------------------------------------------ the quantisation (STOP rule)


def test_the_live_path_is_cited_and_the_cadence_is_the_live_cadence() -> None:
    assert "running_extreme" in obs.LIVE_PATH_CITATION
    assert "round_half_up_f" in obs.LIVE_PATH_CITATION
    assert "iem_observations" in obs.LIVE_PATH_CITATION
    assert obs.LIVE_OBS_CADENCE_SECONDS == OBS_CADENCE_SECONDS == 300


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


def test_the_one_minute_series_is_downsampled_to_the_live_cadence_grid(tmp_path: Path) -> None:
    rows: list[tuple[dt.datetime, int | str]] = [
        (utc(2021, 6, 15, 12, minute), 70 + (99 - 70 if minute == 3 else 0)) for minute in range(15)
    ]

    year = _read(tmp_path, rows)

    day = dt.date(2021, 6, 15)
    stamps = [r.ts_ns for r in year.readings_by_day[day]]
    assert stamps == [ns(utc(2021, 6, 15, 12, m)) for m in (0, 5, 10)]
    assert all(r.temp_f == 70.0 for r in year.readings_by_day[day])
    # the 1-min spike never enters the cadence series (L-13: a sparser grid is its own datum) ...
    assert max(r.temp_f for r in year.readings_by_day[day]) == 70.0
    # ... and survives only in the DESCRIPTIVE raw running max
    assert obs.raw_running_max_at(year.raw_max_by_day[day], ns(utc(2021, 6, 15, 13))) == 99.0
    assert obs.raw_running_max_at(year.raw_max_by_day[day], ns(utc(2021, 6, 15, 12, 2))) == 70.0


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
        (utc(2021, 6, 15, 12, 10), 71),
    ]

    year = _read(tmp_path, rows)

    assert [r.temp_f for r in year.readings_by_day[dt.date(2021, 6, 15)]] == [70.0, 71.0]
    assert year.counts["missing_tmpf"] == 1


# ------------------------------------------------------------------ day scoping


def test_the_climate_day_boundary_is_local_standard_time_never_dst(tmp_path: Path) -> None:
    # 04:55Z in July is 23:55 LST of the PREVIOUS day at UTC-5 (EDT would call it 00:55 same day)
    rows: list[tuple[dt.datetime, int | str]] = [
        (utc(2021, 7, 2, 4, 55), 80),
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
        cadence_seconds=300,
        lag_ns=_LAG,
        cutoff_ns_by_day={dt.date(2021, 6, 15): ns(utc(2021, 6, 15, 15))},
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(year.readings_by_day[dt.date(2021, 6, 15)]) > 0
    # the payload itself is resident once (the cache returns bytes); parsed rows must not be
    assert peak < 1.6 * len(payload), f"peak {peak} bytes vs payload {len(payload)}: not streamed"
