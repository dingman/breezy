"""F13 METAR obs fixes: T-group train/serve parity, the coverage guard, drift and staleness notes.

Item 1: a routine row without a T group (``tmpf_source="column"``) is never an ``obs_so_far``
value (the live ingest drops it), it is counted ``routine_no_tgroup``. Item 2: per station-year
coverage (used / expected hourly reports), the pin-minute-excluded share, the minute histogram,
and the ``obs_min_coverage_per_station_year`` pin (null refuses). Item 5: the D0 staleness
distribution. Synthetic stores through the production writers; nothing reads live data.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import multisource_blend_features_build as fb
from scripts.analysis import multisource_blend_inputs_obs as obs
from tests.unit.featbuild_fixtures import RoutineRow, ns, utc, write_routine_store
from tests.unit.test_multisource_blend_features_build import (
    _D13,
    _build_world,
    _by_key,
    _no_process_cap,  # noqa: F401  (autouse fixture of the builder tests, needed here too)
    _pins,
    _run,
)

_OFFSET = -5.0
_LAG = 15 * 60 * 10**9
_DAY = dt.date(2021, 6, 15)
_CUTOFF = ns(utc(2021, 6, 15, 15))  # day starts 05:00Z at UTC-5: hourly :53 reports 05:53..14:53


def _read(tmp_path: Path, rows: list[RoutineRow], minute: int = 53) -> obs.RoutineObsYear:
    root = tmp_path / "metar"
    write_routine_store(root, "KMIA", 2021, rows)
    return obs.read_routine_obs_year(
        root,
        "KMIA",
        2021,
        std_utc_offset_hours=_OFFSET,
        routine_minute=minute,
        lag_ns=_LAG,
        cutoff_ns_by_day={_DAY: _CUTOFF},
    )


# ------------------------------------------------------------------ item 1


def test_a_row_without_a_t_group_is_never_used_and_is_counted_no_tgroup(tmp_path: Path) -> None:
    rows: list[RoutineRow] = [
        (utc(2021, 6, 15, 12, 53), 72, "tgroup"),
        (utc(2021, 6, 15, 13, 53), 99, "column"),
    ]

    year = _read(tmp_path, rows)

    assert [r.temp_f for r in year.readings_by_day[_DAY]] == [72.0]
    assert year.counts["routine_no_tgroup"] == 1
    assert year.counts["routine_rows_used"] == 1
    assert year.counts["routine_column_sourced"] == 0


# ------------------------------------------------------------------ item 2: reader coverage


def test_coverage_is_used_over_expected_hourly_reports_in_the_window(tmp_path: Path) -> None:
    rows: list[RoutineRow] = [
        (utc(2021, 6, 15, 12, 53), 72, "tgroup"),
        (utc(2021, 6, 15, 13, 53), 73, "tgroup"),
        (utc(2021, 6, 15, 14, 53), 74, "tgroup"),
        (utc(2021, 6, 15, 12, 20), 99, "tgroup"),  # a special off the pin
        (utc(2021, 6, 15, 11, 53), 70, "column"),  # no T group: not used
    ]

    cov = _read(tmp_path, rows).coverage

    assert cov.expected == 10  # 05:53 .. 14:53 inclusive
    assert cov.used == 3
    assert cov.coverage == pytest.approx(0.3)
    assert cov.rows_in_window == 5
    assert cov.pin_minute_excluded == 1
    assert cov.pin_minute_excluded_share == pytest.approx(0.2)
    assert cov.minute_histogram == {20: 1, 53: 4}
    assert cov.by_month == {6: (10, 3)}


def test_coverage_of_a_window_without_requested_days_is_undefined(tmp_path: Path) -> None:
    root = tmp_path / "metar"
    write_routine_store(root, "KMIA", 2021, [(utc(2021, 6, 15, 12, 53), 72, "tgroup")])

    year = obs.read_routine_obs_year(
        root,
        "KMIA",
        2021,
        std_utc_offset_hours=_OFFSET,
        routine_minute=53,
        lag_ns=_LAG,
        cutoff_ns_by_day={},
    )

    assert year.coverage.expected == 0 and year.coverage.coverage is None


# ------------------------------------------------------------------ item 2: builder guard


def _pins_with(minimum: Any) -> dict[str, Any]:
    return _pins(obs_min_coverage_per_station_year=minimum)


def test_a_null_coverage_pin_refuses_the_build(tmp_path: Path) -> None:
    world = _build_world(tmp_path, pins=_pins_with(None))

    assert _run(world) == fb.EXIT_REFUSED
    assert "obs_min_coverage_per_station_year" in world.report()["reason"]


@pytest.mark.parametrize("bad", [True, -0.1, 1.5, "0.9"])
def test_a_malformed_coverage_pin_is_refused(bad: Any) -> None:
    with pytest.raises(fb.BuildRefusal, match="obs_min_coverage_per_station_year"):
        fb.load_pins({"pins": _pins_with(bad)})


def test_a_station_year_below_the_pin_refuses_and_names_it(tmp_path: Path) -> None:
    gone = {utc(2021, 3, 13, 11, 40): (utc(2021, 3, 13, 11, 40), None, "missing")}
    world = _build_world(tmp_path, pins=_pins_with(0.96), routine_replace=gone)

    assert _run(world) == fb.EXIT_REFUSED

    report = world.report()
    assert "KNYC/2021" in report["reason"]
    assert report["obs_coverage"]["per_station_year"]["KNYC/2021"]["used"] == 19
    assert not (world.out() / "features.jsonl").exists()


def test_a_wrong_pinned_minute_collapses_coverage_and_refuses(tmp_path: Path) -> None:
    world = _build_world(
        tmp_path, pins=_pins(obs_routine_minute_by_station={"KNYC": 41})
    )  # every stored report is at :40

    assert _run(world) == fb.EXIT_REFUSED

    cell = world.report()["obs_coverage"]["per_station_year"]["KNYC/2021"]
    assert cell["used"] == 0 and cell["pin_minute_excluded_share"] == 1.0
    assert cell["minute_histogram"] == {"40": 20}


def test_a_station_year_at_or_above_the_pin_builds_and_reports_coverage(tmp_path: Path) -> None:
    gone = {utc(2021, 3, 13, 11, 40): (utc(2021, 3, 13, 11, 40), None, "missing")}
    world = _build_world(tmp_path, pins=_pins_with(0.9), routine_replace=gone)

    assert _run(world) == fb.EXIT_OK

    cov = world.report()["obs_coverage"]
    cell = cov["per_station_year"]["KNYC/2021"]
    assert cov["min_coverage_pin"] == 0.9 and cov["below_pin"] == []
    assert (cell["expected"], cell["used"]) == (20, 19)
    assert cell["coverage"] == pytest.approx(0.95)
    assert cell["minute_histogram"]["40"] >= 19
    assert cell["pin_minute_excluded_share"] == 0.0
    assert cell["by_month"]["3"] == {"expected": 20, "used": 19, "coverage": pytest.approx(0.95)}


def test_pin_minute_excluded_share_is_reported_per_station_year(tmp_path: Path) -> None:
    extra: list[RoutineRow] = [(utc(2021, 3, 13, 12, 20), 99, "tgroup")]
    world = _build_world(tmp_path, pins=_pins_with(0.5), routine_extra=extra)

    assert _run(world) == fb.EXIT_OK

    cell = world.report()["obs_coverage"]["per_station_year"]["KNYC/2021"]
    assert cell["pin_minute_excluded"] == 1
    assert cell["pin_minute_excluded_share"] == pytest.approx(1 / 21)
    assert cell["minute_histogram"]["20"] == 1


def test_the_d0_truth_minus_obs_so_far_drift_is_reported_per_station_year(tmp_path: Path) -> None:
    world = _build_world(tmp_path, pins=_pins_with(0.5))

    assert _run(world) == fb.EXIT_OK

    cell = world.report()["obs_coverage"]["per_station_year"]["KNYC/2021"]
    # truth 50 / 56 against the D0 obs_so_far 44 on both days
    assert cell["d0_n"] == 2
    assert cell["d0_mean_truth_minus_obs_so_far"] == pytest.approx(9.0)
    assert _by_key(world.rows())[(_D13, "D0")].obs_so_far_f == 44.0


# ------------------------------------------------------------------ item 5: staleness


def test_the_effective_d0_obs_staleness_distribution_is_reported_per_station(
    tmp_path: Path,
) -> None:
    world = _build_world(tmp_path, pins=_pins_with(0.5))

    assert _run(world) == fb.EXIT_OK

    # anchor 15:00Z, newest usable report 14:40Z (available 14:55Z): 20 minutes, both days
    stats = world.report()["obs"]["d0_obs_staleness_minutes_by_station"]["KNYC"]
    assert stats == {"n": 2, "no_usable_report": 0, "min": 20.0, "p50": 20.0, "p90": 20.0,
                     "max": 20.0, "mean": 20.0}  # fmt: skip


def test_a_d0_row_without_a_usable_report_is_counted_not_dropped(tmp_path: Path) -> None:
    # every report of the 3/14 morning is missing: that D0 row has no obs at all
    replace = {
        utc(2021, 3, 14, h, 40): (utc(2021, 3, 14, h, 40), None, "missing") for h in range(5, 15)
    }
    world = _build_world(tmp_path, pins=_pins_with(0.4), routine_replace=replace)

    assert _run(world) == fb.EXIT_OK

    stats = world.report()["obs"]["d0_obs_staleness_minutes_by_station"]["KNYC"]
    assert stats["n"] == 1 and stats["no_usable_report"] == 1
