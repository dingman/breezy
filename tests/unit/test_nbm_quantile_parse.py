"""SL-2: the NBM NBP probabilistic percentile bulletin parser raises on drift (RED first).

Two fixture sources:

* :data:`REAL_FIXTURE_FILES` -- four BYTE-REAL captures under
  `tests/fixtures/nbm/nbptx_*_excerpt.txt`, each with a provenance header
  (source URL, fetch time, raw-file sha256) and unmodified station blocks
  (L-17/L-36): the 13Z/19Z/01Z v5.0 cycles (2026-09-28/29) and one v4.2-era
  cycle (2024-06-01 13Z).
* :func:`block` and friends -- SYNTHETIC bulletins built from named columns,
  for drift/absence cases a real capture cannot exercise on demand (a
  reshaped grid, a missing row, a sentinel cell). Mirrors
  `test_nbm_forecast_parse.py`'s own real-vs-synthetic split.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

import pytest

from breezy.ingest.gaps import local_standard_date
from breezy.ingest.nbm_quantile_parse import (
    NBM_NBP_MODEL,
    NBP_MAX_COLUMN_UTC_HOUR,
    TXN_VARIABLE_BY_ROW_LABEL,
    NbpBulletinDriftError,
    NbpQuantilePoint,
    bbb_correction_token,
    max_column_lst_climate_day,
    parse_nbp_bulletin,
)

NS = 1_000_000_000
STATIONS = frozenset({"KLAX", "KMDW", "KMIA", "KSFO"})

#: Registered standard-time offsets (`src/breezy/registry/sites.toml`), for
#: LST assertions only -- this test module carries no registry dependency,
#: matching `tests/support/forecast_climate_day_fixtures.py`'s own stance.
STD_UTC_OFFSET_HOURS = {"KLAX": -8.0, "KMDW": -6.0, "KMIA": -5.0, "KSFO": -8.0}

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nbm"

REAL_FIXTURE_FILES = {
    "13Z": "nbptx_t13z_excerpt.txt",
    "19Z": "nbptx_t19z_excerpt.txt",
    "01Z": "nbptx_t01z_excerpt.txt",
    "v4era_13Z": "nbptx_v4era_t13z_excerpt.txt",
}


def real_fixture_text(name: str) -> str:
    return (FIXTURE_DIR / REAL_FIXTURE_FILES[name]).read_text(encoding="utf-8")


def parse_real(name: str) -> tuple[tuple[NbpQuantilePoint, ...], Counter[str]]:
    return parse_nbp_bulletin(real_fixture_text(name), stations=STATIONS)


# ---------------------------------------------------------------------------
# Real captures parse: all 4 stations, matching the fixture, every cycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["13Z", "19Z", "01Z", "v4era_13Z"])
def test_all_four_stations_parse_with_no_drops(name: str) -> None:
    points, drops = parse_real(name)

    assert drops == {}
    assert {point.station for point in points} == STATIONS
    # 7 TXN variables x 9 available MAX columns per station in this excerpt.
    for station in STATIONS:
        assert sum(1 for p in points if p.station == station) == 63


@pytest.mark.parametrize("name", ["13Z", "19Z", "01Z"])
def test_real_v5_0_captures_report_that_version(name: str) -> None:
    points, _ = parse_real(name)

    assert {point.model_version for point in points} == {"5.0"}


def test_a_v4_x_era_capture_reports_that_version() -> None:
    points, _ = parse_real("v4era_13Z")

    assert {point.model_version for point in points} == {"4.2"}


def test_every_variable_row_maps_to_the_plan_target_names() -> None:
    points, _ = parse_real("13Z")

    assert {point.variable for point in points} == set(TXN_VARIABLE_BY_ROW_LABEL.values())
    assert set(TXN_VARIABLE_BY_ROW_LABEL.values()) == {
        "TXN_MEAN", "TXN_SD", "TXN_Q10", "TXN_Q25", "TXN_Q50", "TXN_Q75", "TXN_Q90",
    }


def test_klax_txn_mean_values_match_the_real_13z_fixture_grid() -> None:
    """Cross-checked by hand against the raw capture's TXNMN row for KLAX."""
    points, _ = parse_real("13Z")

    klax_mean = sorted(
        (p for p in points if p.station == "KLAX" and p.variable == "TXN_MEAN"),
        key=lambda p: p.valid_end_ns,
    )
    assert [p.value_f for p in klax_mean] == [
        82.0, 81.0, 81.0, 85.0, 88.0, 90.0, 91.0, 90.0, 90.0,
    ]


def test_every_returned_point_is_a_max_column_never_a_min_column() -> None:
    points, _ = parse_real("13Z")

    for point in points:
        end = dt.datetime.fromtimestamp(point.valid_end_ns / NS, tz=dt.UTC)
        assert end.hour == NBP_MAX_COLUMN_UTC_HOUR
        assert point.valid_start_ns == point.valid_end_ns


# ---------------------------------------------------------------------------
# 13Z / 19Z / 01Z cycles: the first available MAX column targets D+1 (LST)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["13Z", "19Z", "01Z"])
def test_first_max_column_targets_dplus1_in_lst_every_cycle(name: str) -> None:
    points, _ = parse_real(name)

    for station in STATIONS:
        offset = STD_UTC_OFFSET_HOURS[station]
        station_points = [p for p in points if p.station == station]
        cycle_ns = station_points[0].cycle_runtime_ns
        assert {p.cycle_runtime_ns for p in station_points} == {cycle_ns}

        cycle_lst_day = local_standard_date(cycle_ns, offset)
        lst_days = {
            max_column_lst_climate_day(p, std_utc_offset_hours=offset)
            for p in station_points
        }
        assert min(lst_days) == cycle_lst_day + dt.timedelta(days=1), (
            name, station, cycle_lst_day, sorted(lst_days)[:3]
        )


def test_01z_cycles_own_lst_day_is_the_utc_date_minus_one() -> None:
    """01:00 UTC on 9/29 is still 9/28 evening in every CONUS station's LST."""
    points, _ = parse_real("01Z")
    klax_cycle_ns = next(p.cycle_runtime_ns for p in points if p.station == "KLAX")

    cycle_utc_date = dt.datetime.fromtimestamp(klax_cycle_ns / NS, tz=dt.UTC).date()
    assert cycle_utc_date == dt.date(2026, 9, 29)

    cycle_lst_day = local_standard_date(klax_cycle_ns, STD_UTC_OFFSET_HOURS["KLAX"])
    assert cycle_lst_day == dt.date(2026, 9, 28)


# ---------------------------------------------------------------------------
# HAND-COMPUTED D+1 target LST day (SL-2 review, MEDIUM): every expectation
# below is a hard-coded literal, worked out by hand from the raw fixture's
# FHR row -- NEVER via `local_standard_date`/`max_column_lst_climate_day` or
# any other library call. Only the ACTUAL side of each assertion calls the
# parser and the production helper.
#
# The FHR row is byte-identical across all four stations within one cycle
# file (verified: `grep " FHR " tests/fixtures/nbm/nbptx_t*_excerpt.txt`), so
# the first available MAX (00Z) column's own UTC valid instant is the SAME
# for every station, per cycle:
#
#   13Z cycle (2026-09-28 13:00 UTC): first MAX column is FHR 35 (the
#     grid's FIRST group, FHR 23, carries only the 12Z/MIN sub-value).
#     13:00 UTC + 35h = 13:00 + 1d11h = (next day) 00:00 UTC, +1 more day
#     = 2026-09-30 00:00:00 UTC.
#
#   19Z cycle (2026-09-28 19:00 UTC): first MAX column is FHR 29 (group 0,
#     FHR 17, is MIN-only, same shape as the 13Z case).
#     19:00 UTC + 29h = 19:00 + 1d5h = (next day) 00:00 UTC, +1 more day
#     = 2026-09-30 00:00:00 UTC.
#
#   01Z cycle (2026-09-29 01:00 UTC): first MAX column is FHR 23 (this
#     grid's very first group already carries BOTH 00Z and 12Z, since 01Z
#     is early enough that the day-D MAX is already >= NBP's ~24h floor).
#     01:00 UTC + 23h = 24:00 UTC = 2026-09-30 00:00:00 UTC.
#
# All three cycles converge on the SAME instant, 2026-09-30 00:00:00 UTC.
# Converting it to each station's FIXED standard-time offset by hand
# (UTC hour + offset; a negative result rolls the calendar date back one):
#
#   KLAX (offset -8): 00:00 - 8h = -08:00 -> 2026-09-29 16:00 LST -> day 2026-09-29
#   KSFO (offset -8): 00:00 - 8h = -08:00 -> 2026-09-29 16:00 LST -> day 2026-09-29
#   KMDW (offset -6): 00:00 - 6h = -06:00 -> 2026-09-29 18:00 LST -> day 2026-09-29
#   KMIA (offset -5): 00:00 - 5h = -05:00 -> 2026-09-29 19:00 LST -> day 2026-09-29
#
# Every station lands on 2026-09-29, which is D+1: each cycle's own LST day
# D is 2026-09-28 (13Z/19Z keep the UTC calendar date; 01Z's 2026-09-29 UTC
# rolls back to 2026-09-28 LST at every one of these offsets -- worked
# example 3, docs/evidence/NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md).

HAND_COMPUTED_FIRST_MAX_VALID_UTC = dt.datetime(2026, 9, 30, 0, 0, tzinfo=dt.UTC)

HAND_COMPUTED_DPLUS1_LST_DAY: dict[str, dt.date] = {
    "KLAX": dt.date(2026, 9, 29),
    "KSFO": dt.date(2026, 9, 29),
    "KMDW": dt.date(2026, 9, 29),
    "KMIA": dt.date(2026, 9, 29),
}


@pytest.mark.parametrize("station", ["KLAX", "KSFO", "KMDW", "KMIA"])
@pytest.mark.parametrize("name", ["13Z", "19Z", "01Z"])
def test_hand_computed_dplus1_lst_day_per_station_per_cycle(name: str, station: str) -> None:
    points, _ = parse_real(name)
    station_points = [p for p in points if p.station == station]
    first = min(station_points, key=lambda p: p.valid_end_ns)

    first_instant = dt.datetime.fromtimestamp(first.valid_end_ns / NS, tz=dt.UTC)
    assert first_instant == HAND_COMPUTED_FIRST_MAX_VALID_UTC

    actual_lst_day = max_column_lst_climate_day(
        first, std_utc_offset_hours=STD_UTC_OFFSET_HOURS[station]
    )
    assert actual_lst_day == HAND_COMPUTED_DPLUS1_LST_DAY[station]


# ---------------------------------------------------------------------------
# BBB correction indicator: parsed if present; PINNED absent on every fixture
# (R3-08). Real NBP captures carry no WMO abbreviated-header line.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["13Z", "19Z", "01Z", "v4era_13Z"])
def test_bbb_correction_token_is_absent_on_every_real_fixture(name: str) -> None:
    text = real_fixture_text(name)
    header_lines = [
        line for line in text.splitlines()
        if "NBM V" in line and "NBP GUIDANCE" in line
    ]
    assert len(header_lines) == 4  # KLAX, KMDW, KMIA, KSFO

    for header_line in header_lines:
        assert bbb_correction_token(header_line) is None


def test_bbb_correction_token_is_parsed_when_present() -> None:
    """The parse-if-present half of R3-08: proves the function is not a stub."""
    header = " KLAX    NBM V5.0 NBP GUIDANCE    9/28/2026  1300 UTC CCA"

    assert bbb_correction_token(header) == "CCA"


def test_bbb_correction_token_raises_on_an_unrecognised_header() -> None:
    with pytest.raises(NbpBulletinDriftError):
        bbb_correction_token("not a header line at all")


# ---------------------------------------------------------------------------
# Synthetic bulletins: absences, drift, and grid-geometry edge cases a real
# capture does not conveniently exercise on demand.
# ---------------------------------------------------------------------------

_HEADER = " KMIA    NBM V5.0 NBP GUIDANCE    9/28/2026  1300 UTC"

#: Three day-groups: group0 = 1 slot (12Z/MIN only, FHR23 -> derived 12Z off
#: the 13Z cycle), group1/group2 = 2 slots each (00Z/MAX then 12Z/MIN).
#: Values chosen so `(cycle_hour + FHR) % 24` matches every labelled hour.
_DAY_ROW = "    TUE 29| WED 30| THU 01|"


def _group(*values: str) -> str:
    return " ".join(value.rjust(3) for value in values)


def _build_row(label: str, groups: list[list[str]]) -> str:
    rendered = [_group(*vals) for vals in groups]
    return f" {label} {rendered[0]}" + "".join(f"|{g}" for g in rendered[1:])


_UTC_ROW = _build_row("UTC", [["12"], ["00", "12"], ["00", "12"]])
_FHR_ROW = _build_row("FHR", [["23"], ["35", "47"], ["59", "71"]])


def _minimal_txn_row(label: str, *, max_values: list[str]) -> str:
    """group0 blank (MIN, unused by this parser); group1/group2 = (MAX, MIN)."""
    return _build_row(label, [[""], [max_values[0], "99"], [max_values[1], "99"]])


def block(*, drop: frozenset[str] = frozenset(), txn_overrides: dict[str, str] | None = None) -> str:
    rows = [_HEADER, _DAY_ROW]
    if "UTC" not in drop:
        rows.append(_UTC_ROW)
    if "FHR" not in drop:
        rows.append(_FHR_ROW)
    overrides = txn_overrides or {}
    for label in TXN_VARIABLE_BY_ROW_LABEL:
        if label in drop:
            continue
        if label in overrides:
            rows.append(overrides[label])
        else:
            rows.append(_minimal_txn_row(label, max_values=["80", "81"]))
    return "\n".join(rows) + "\n"


def parse(
    text: str, *, stations: frozenset[str] = frozenset({"KMIA"})
) -> tuple[tuple[NbpQuantilePoint, ...], Counter[str]]:
    return parse_nbp_bulletin(text, stations=stations)


def test_a_body_with_no_station_header_at_all_raises() -> None:
    with pytest.raises(NbpBulletinDriftError, match="no NBP station block"):
        parse("1\n\n SOMETHING ELSE ENTIRELY\n")


def test_a_station_not_asked_for_is_not_parsed() -> None:
    points, drops = parse(block(), stations=frozenset({"KSFO"}))

    assert points == ()
    assert drops["station_block_missing"] == 1


@pytest.mark.parametrize("label", ["UTC", "FHR", "TXNMN", "TXNP9"])
def test_a_missing_required_row_raises_and_names_the_header_key_tree(label: str) -> None:
    with pytest.raises(NbpBulletinDriftError) as excinfo:
        parse(block(drop=frozenset({label})))

    message = str(excinfo.value)
    assert label in message
    assert "Row labels actually present" in message
    # The header key tree names rows that ARE present -- proves it is not a
    # generic "missing row" message but actually enumerates what was found.
    if label != "UTC":
        assert "UTC" in message


def test_an_unknown_layout_raises_when_the_utc_and_fhr_grids_disagree() -> None:
    reshaped_fhr = _build_row("FHR", [["23"], ["35", "47"]])  # one fewer group
    text = block().replace(_FHR_ROW, reshaped_fhr)

    with pytest.raises(NbpBulletinDriftError):
        parse(text)


def test_a_reshaped_utc_fhr_cross_check_raises() -> None:
    """The derived hour `(cycle_hour + FHR) % 24` must match the labelled UTC hour."""
    drifted_utc = _build_row("UTC", [["11"], ["00", "12"], ["00", "12"]])  # was 12
    text = block().replace(_UTC_ROW, drifted_utc)

    with pytest.raises(NbpBulletinDriftError, match="disagrees"):
        parse(text)


# ---------------------------------------------------------------------------
# Missing/absent codes are handled, never invented (mirrors NBS's design)
# ---------------------------------------------------------------------------


def test_a_blank_max_cell_is_recorded_as_not_published() -> None:
    row = _build_row("TXNMN", [[""], ["", "99"], ["", "99"]])  # both MAX fields blank
    text = block(txn_overrides={"TXNMN": row})

    points, _ = parse(text)
    mean_points = [p for p in points if p.variable == "TXN_MEAN"]
    assert len(mean_points) == 2
    assert all(p.value_f is None for p in mean_points)
    assert all(p.absence_reason == "not_published" for p in mean_points)


def test_a_sentinel_maps_to_sentinel_absence_reason() -> None:
    """Primary source: 'a value of -99 indicates missing data' (vlab.noaa.gov NBP card)."""
    row = _build_row("TXNMN", [[""], ["-99", "99"], ["99", "99"]])
    text = block(txn_overrides={"TXNMN": row})

    points, _ = parse(text)
    mean_points = [p for p in points if p.variable == "TXN_MEAN"]
    first = mean_points[0]
    assert first.value_f is None
    assert first.absence_reason == "sentinel"


def test_an_unreadable_token_is_a_parse_failure_and_never_a_value() -> None:
    row = _build_row("TXNMN", [[""], ["**", "99"], ["99", "99"]])
    text = block(txn_overrides={"TXNMN": row})

    points, _ = parse(text)
    mean_points = [p for p in points if p.variable == "TXN_MEAN"]
    first = mean_points[0]
    assert first.value_f is None
    assert first.absence_reason == "parse_failure"


# ---------------------------------------------------------------------------
# NBM_NBP_MODEL is a plain constant, not a ForecastPoint construction --
# this module builds no ForecastPoint and never imports FORECAST_MODELS.
# ---------------------------------------------------------------------------


def test_the_model_constant_is_the_plain_string_nbm_nbp() -> None:
    assert NBM_NBP_MODEL == "NBM_NBP"
