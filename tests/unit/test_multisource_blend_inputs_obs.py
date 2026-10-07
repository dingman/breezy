"""FB-R13/FB-R15 (L-13): ``obs_so_far`` comes from the routine-METAR store, never the 1-min archive.

Live path (cited, not copied): ``breezy.ingest.nws_observations`` / ``iem_observations`` build
``StationObservation`` rows (tenths of a degree C) and
``breezy.strategy.weather_common.running_extreme`` quantises them with
``breezy.domain.temperature.round_half_up_f``. The builder reads the routine hourly METAR rows of
``scripts/archive/metar_routine_store.py`` (T-group through the same function). Rows whose minute
differs from the pinned routine minute are a validation exclusion; ``tmpf_source="missing"`` rows
are skipped, never imputed. The 1-min archive only feeds two DESCRIPTIVE, non-METAR arms.
Synthetic payloads through the production writers.
"""

from __future__ import annotations

import datetime as dt
import tracemalloc
from collections.abc import Sequence
from pathlib import Path

import pytest

from breezy.domain.temperature import round_half_up_f
from scripts.analysis import multisource_blend_inputs_obs as obs
from scripts.analysis.forecast_conditional_corpus import OBS_CADENCE_SECONDS
from tests.unit.featbuild_fixtures import (
    NS,
    RoutineRow,
    asos_1min_payload,
    ns,
    utc,
    write_asos_year,
    write_routine_store,
)

_NYC_OFFSET = -5.0
_LAG = 15 * 60 * NS
_DAY = dt.date(2021, 6, 15)


def _read_routine(
    tmp_path: Path,
    rows: Sequence[RoutineRow],
    *,
    days: dict[dt.date, int] | None = None,
    year: int = 2021,
    routine_minute: int = 53,
) -> obs.RoutineObsYear:
    root = tmp_path / "metar"
    write_routine_store(root, "KMIA", year, rows)
    cutoffs = days if days is not None else {_DAY: ns(utc(year, 12, 31, 23))}
    return obs.read_routine_obs_year(
        root,
        "KMIA",
        year,
        std_utc_offset_hours=_NYC_OFFSET,
        routine_minute=routine_minute,
        lag_ns=_LAG,
        cutoff_ns_by_day=cutoffs,
    )


def _read_arms(
    tmp_path: Path,
    rows: list[tuple[dt.datetime, int | str]],
    *,
    days: dict[dt.date, int] | None = None,
    year: int = 2021,
) -> obs.OneMinArms:
    root = tmp_path / "asos"
    write_asos_year(root, "KMIA", year, asos_1min_payload(rows))
    from scripts.analysis.multisource_blend_features_build import read_only_cache

    cutoffs = days if days is not None else {rows[0][0].date(): ns(utc(year, 12, 31, 23))}
    return obs.read_onemin_arms_year(
        read_only_cache(root),
        "KMIA",
        year,
        std_utc_offset_hours=_NYC_OFFSET,
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


def test_an_archive_that_is_not_whole_degf_stops_the_arm_read(tmp_path: Path) -> None:
    rows: list[tuple[dt.datetime, int | str]] = [(utc(2021, 6, 15, 12, 0), "72.4")]

    with pytest.raises(obs.ObsQuantisationError):
        _read_arms(tmp_path, rows)


# ------------------------------------------------------------------ FB-R15: routine-METAR source


def _hourly(minute: int, hours: range, source: str = "tgroup") -> list[RoutineRow]:
    return [(utc(2021, 6, 15, h, minute), 60 + h, source) for h in hours]


def test_the_source_label_names_the_routine_store_not_the_1min_archive() -> None:
    assert "1min" not in obs.OBS_SOURCE_LABEL and "routine_metar" in obs.OBS_SOURCE_LABEL


def test_obs_so_far_readings_come_from_the_routine_store_at_the_pinned_minute(
    tmp_path: Path,
) -> None:
    year = _read_routine(tmp_path, _hourly(53, range(12, 15)))

    readings = year.readings_by_day[_DAY]
    assert [r.ts_ns for r in readings] == [ns(utc(2021, 6, 15, h, 53)) for h in (12, 13, 14)]
    assert [r.temp_f for r in readings] == [72.0, 73.0, 74.0]
    assert all(r.available_at_ns == r.ts_ns + _LAG for r in readings)
    assert all(r.source == obs.OBS_SOURCE_LABEL for r in readings)
    assert year.counts["routine_rows_used"] == 3
    assert year.counts["routine_pin_minute_excluded"] == 0


def test_rows_off_the_pinned_minute_are_excluded_and_counted(tmp_path: Path) -> None:
    rows = [*_hourly(53, range(12, 14)), (utc(2021, 6, 15, 12, 20), 99, "tgroup")]

    year = _read_routine(tmp_path, rows)

    assert [r.temp_f for r in year.readings_by_day[_DAY]] == [72.0, 73.0]
    assert year.counts["routine_pin_minute_excluded"] == 1
    assert year.counts["routine_rows_used"] == 2


def test_column_sourced_rows_are_used_and_flagged(tmp_path: Path) -> None:
    rows = [(utc(2021, 6, 15, 12, 53), 72, "tgroup"), (utc(2021, 6, 15, 13, 53), 73, "column")]

    year = _read_routine(tmp_path, rows)

    assert [r.temp_f for r in year.readings_by_day[_DAY]] == [72.0, 73.0]
    assert year.counts["routine_column_sourced"] == 1
    assert year.counts["routine_rows_used"] == 2


def test_missing_rows_are_skipped_counted_and_never_imputed(tmp_path: Path) -> None:
    rows: list[RoutineRow] = [
        (utc(2021, 6, 15, 12, 53), 72, "tgroup"),
        (utc(2021, 6, 15, 13, 53), None, "missing"),
        (utc(2021, 6, 15, 14, 53), 74, "tgroup"),
    ]

    year = _read_routine(tmp_path, rows)

    assert [r.ts_ns for r in year.readings_by_day[_DAY]] == [
        ns(utc(2021, 6, 15, 12, 53)),
        ns(utc(2021, 6, 15, 14, 53)),
    ]
    assert year.counts["routine_missing"] == 1


def test_a_missing_hour_is_never_filled_from_the_1min_archive(tmp_path: Path) -> None:
    rows: list[RoutineRow] = [(utc(2021, 6, 15, 13, 53), None, "missing")]

    year = _read_routine(tmp_path, rows)

    assert _DAY not in year.readings_by_day  # no fallback: there is no 1-min input at all


def test_a_tgroup_that_disagrees_with_the_stored_tmpf_stops_the_read(tmp_path: Path) -> None:
    root = tmp_path / "metar"
    path = write_routine_store(root, "KMIA", 2021, [(utc(2021, 6, 15, 12, 53), 72, "tgroup")])
    text = path.read_text(encoding="utf-8").replace(",72,", ",80,")
    path.write_text(text, encoding="utf-8")
    import hashlib
    import json

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["entries"]["KMIA/2021"]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(obs.ObsQuantisationError):
        obs.read_routine_obs_year(
            root,
            "KMIA",
            2021,
            std_utc_offset_hours=_NYC_OFFSET,
            routine_minute=53,
            lag_ns=_LAG,
            cutoff_ns_by_day={_DAY: ns(utc(2021, 6, 16))},
        )


def test_a_station_year_absent_from_the_store_is_an_error_never_fabricated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "metar"
    write_routine_store(root, "KMIA", 2021, _hourly(53, range(12, 14)))

    with pytest.raises(obs.ObsStoreError):
        obs.read_routine_obs_year(
            root,
            "KMIA",
            2022,
            std_utc_offset_hours=_NYC_OFFSET,
            routine_minute=53,
            lag_ns=_LAG,
            cutoff_ns_by_day={dt.date(2022, 6, 15): ns(utc(2022, 6, 16))},
        )


def test_the_sealed_holdout_is_never_requested_even_with_a_late_cutoff(tmp_path: Path) -> None:
    june = dt.date(2026, 6, 30)
    rows: list[RoutineRow] = [
        (utc(2026, 6, 30, 12, 53), 80, "tgroup"),
        (utc(2026, 7, 2, 12, 53), 99, "tgroup"),  # a sealed row that must never surface
    ]

    year = _read_routine(
        tmp_path, rows, year=2026, days={june: ns(utc(2026, 7, 5))}, routine_minute=53
    )

    assert [r.temp_f for r in year.readings_by_day[june]] == [80.0]
    assert all(r.ts_ns < ns(utc(2026, 7, 1)) for d in year.readings_by_day.values() for r in d)


def test_the_climate_day_boundary_is_local_standard_time_never_dst(tmp_path: Path) -> None:
    # 04:00Z in July is 23:00 LST of the PREVIOUS day at UTC-5 (EDT would call it 00:00 same day)
    rows: list[RoutineRow] = [
        (utc(2021, 7, 2, 4, 53), 80, "tgroup"),
        (utc(2021, 7, 2, 5, 53), 81, "tgroup"),
    ]
    cutoffs = {dt.date(2021, 7, 1): ns(utc(2021, 7, 3)), dt.date(2021, 7, 2): ns(utc(2021, 7, 3))}

    year = _read_routine(tmp_path, rows, days=cutoffs)

    assert [r.temp_f for r in year.readings_by_day[dt.date(2021, 7, 1)]] == [80.0]
    assert [r.temp_f for r in year.readings_by_day[dt.date(2021, 7, 2)]] == [81.0]


def test_only_requested_days_and_only_readings_up_to_the_cutoff_are_retained(
    tmp_path: Path,
) -> None:
    rows: list[RoutineRow] = [
        (utc(2021, 6, 15, 12, 53), 70, "tgroup"),
        (utc(2021, 6, 15, 14, 53), 75, "tgroup"),
        (utc(2021, 6, 16, 12, 53), 60, "tgroup"),
    ]
    # the later requested day widens the read window, so the 14:53 row and the 6/16 row are seen
    cutoffs = {_DAY: ns(utc(2021, 6, 15, 13)), dt.date(2021, 6, 17): ns(utc(2021, 6, 17, 23))}

    year = _read_routine(tmp_path, rows, days=cutoffs)

    assert list(year.readings_by_day) == [_DAY]
    assert [r.temp_f for r in year.readings_by_day[_DAY]] == [70.0]
    assert year.counts["day_not_requested"] >= 1 and year.counts["after_cutoff"] == 1


# ------------------------------------------------------------------ the routine-minute helper


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


# ------------------------------------------------------------------ the non-METAR descriptive arms


def _hourly_minutes(
    hours: range, spikes: dict[tuple[int, int], int] | None = None
) -> list[tuple[dt.datetime, int | str]]:
    spikes = spikes or {}
    return [
        (utc(2021, 6, 15, hour, minute), spikes.get((hour, minute), 60 + hour))
        for hour in hours
        for minute in range(60)
    ]


def test_the_one_minute_arms_are_descriptive_and_carry_no_readings(tmp_path: Path) -> None:
    rows = _hourly_minutes(range(12, 14), spikes={(12, 3): 99, (12, 5): 85, (12, 53): 70})

    arms = _read_arms(tmp_path, rows)

    anchor = ns(utc(2021, 6, 15, 13, 59))
    assert obs.raw_running_max_at(arms.raw_max_by_day[_DAY], anchor) == 99.0
    assert obs.raw_running_max_at(arms.five_min_max_by_day[_DAY], anchor) == 85.0
    assert not hasattr(arms, "readings_by_day")


def test_an_unavailable_one_minute_year_is_counted_not_an_error(tmp_path: Path) -> None:
    from scripts.analysis.multisource_blend_features_build import read_only_cache

    arms = obs.read_onemin_arms_year(
        read_only_cache(tmp_path / "none"),
        "KNYC",
        2021,
        std_utc_offset_hours=_NYC_OFFSET,
        cutoff_ns_by_day={_DAY: ns(utc(2021, 6, 16))},
    )

    assert arms.counts["onemin_year_payload_unavailable"] == 1 and not arms.raw_max_by_day


def test_a_one_minute_arm_year_is_streamed_with_a_bounded_peak(tmp_path: Path) -> None:
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
    arms = obs.read_onemin_arms_year(
        cache,
        "KMIA",
        2021,
        std_utc_offset_hours=_NYC_OFFSET,
        cutoff_ns_by_day={_DAY: ns(utc(2021, 6, 15, 15))},
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(arms.raw_max_by_day[_DAY]) > 0
    assert peak < 1.6 * len(payload), f"peak {peak} bytes vs payload {len(payload)}: not streamed"
