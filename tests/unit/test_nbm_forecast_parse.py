"""WP-12 Seam B: the NBS collective-bulletin parser raises on drift (RED first).

The fixture block in :data:`REAL_BLOCK` is BYTE-REAL: it is the head of the
live body captured on 2026-09-19 by ``scripts/venue/nbm_nomads_discovery_probe.py``
(``docs/evidence/nbm_nomads_discovery_probe_20260919T134718Z/p2_collective_nbstx.probe.json``),
with only the station id changed from the numeric ``086092`` that happened to
sort first in that 28 MB file to the ICAO ``KMIA`` this repo trades. Column
geometry, header tokens, row labels and values are untouched.

Every other bulletin in this module is BUILT from :func:`utc_row`/:func:`fhr_row`/
:func:`txn_row`, which place a value in a named column rather than counting
spaces by hand -- so a test that means "TXN at the 03Z column" says so.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

import pytest

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS, ForecastPoint
from breezy.ingest.nbm_forecast_parse import (
    NBM_NBS_MODEL,
    TXN_PERIOD_END_UTC_HOURS,
    TXN_VARIABLE,
    NbsBulletinDriftError,
    parse_nbs_bulletin,
)

NS = 1_000_000_000
LAG_NS = MINIMUM_PUBLICATION_LAG_NS["NBM_NBS"] + 600 * NS  # 30 min, above the floor
CYCLE_NS = int(dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC).timestamp()) * NS
INGESTED_NS = CYCLE_NS + 2 * LAG_NS

REAL_BLOCK = (
    " KMIA    NBM V5.0 NBS GUIDANCE    9/19/2026  1200 UTC\n"
    " DT /SEP  19/SEP  20                /SEP  21                /SEP  22      \n"
    " UTC  18 21 00 03 06 09 12 15 18 21 00 03 06 09 12 15 18 21 00 03 06 09 12 \n"
    " FHR  06 09 12 15 18 21 24 27 30 33 36 39 42 45 48 51 54 57 60 63 66 69 72 \n"
    " TXN        84          76          84          75          84          75\n"
    " XND         1           1           1           1           1           1\n"
    " TMP  83 81 80 80 79 78 78 82 82 79 78 78 77 77 77 82 82 79 78 78 77 77 77\n"
)

#: The 23 projection hours of the real 12Z block, in column order.
REAL_UTC_HOURS = [(18 + 3 * k) % 24 for k in range(23)]
REAL_FHRS = [6 + 3 * k for k in range(23)]


def _row(label: str, cells: list[str]) -> str:
    return f" {label} " + "".join(cell.rjust(3) for cell in cells)


def utc_row(hours: list[int]) -> str:
    return _row("UTC", [f"{hour:02d}" for hour in hours])


def fhr_row(fhrs: list[int]) -> str:
    return _row("FHR", [f"{fhr:02d}" for fhr in fhrs])


def txn_row(values: dict[int, str], *, columns: int = 23) -> str:
    cells = ["" for _ in range(columns)]
    for index, token in values.items():
        cells[index] = token
    return _row("TXN", cells)


def block(
    *,
    header: str = " KMIA    NBM V5.0 NBS GUIDANCE    9/19/2026  1200 UTC",
    hours: list[int] | None = None,
    fhrs: list[int] | None = None,
    txn: dict[int, str] | None = None,
    drop: frozenset[str] = frozenset(),
) -> str:
    rows = [header]
    if "UTC" not in drop:
        rows.append(utc_row(REAL_UTC_HOURS if hours is None else hours))
    if "FHR" not in drop:
        rows.append(fhr_row(REAL_FHRS if fhrs is None else fhrs))
    if "TXN" not in drop:
        rows.append(txn_row({} if txn is None else txn))
    return "\n".join(rows) + "\n"


def parse(
    text: str, *, stations: frozenset[str] = frozenset({"KMIA"})
) -> tuple[tuple[ForecastPoint, ...], Counter[str]]:
    return parse_nbs_bulletin(
        text,
        stations=stations,
        measured_publication_lag_ns=LAG_NS,
        ingested_at_ns=INGESTED_NS,
    )


# ---------------------------------------------------------------------------
# The real capture parses, exactly
# ---------------------------------------------------------------------------


def test_the_real_captured_block_yields_one_txn_point_per_period_end() -> None:
    points, drops = parse(REAL_BLOCK)

    assert drops == {}
    # 00Z and 12Z only: columns 2, 6, 10, 14, 18, 22 of the real 12Z block.
    assert [point.value_f for point in points] == [84.0, 76.0, 84.0, 75.0, 84.0, 75.0]
    assert {point.station for point in points} == {"KMIA"}
    assert {point.model for point in points} == {NBM_NBS_MODEL}
    assert {point.model_version for point in points} == {"5.0"}
    assert {point.variable for point in points} == {TXN_VARIABLE}
    assert {point.absence_reason for point in points} == {None}


def test_the_cycle_instant_and_the_vintage_come_from_the_header_and_the_measured_lag() -> None:
    points, _ = parse(REAL_BLOCK)

    assert {point.cycle_runtime_ns for point in points} == {CYCLE_NS}
    assert {point.measured_publication_lag_ns for point in points} == {LAG_NS}
    assert {point.available_at_ns for point in points} == {CYCLE_NS + LAG_NS}
    assert {point.ingested_at_ns for point in points} == {INGESTED_NS}


def test_the_validity_window_is_the_measured_period_end_instant() -> None:
    """Period LENGTH is still UNVERIFIED (FC-0a), so the window is the end instant."""
    points, _ = parse(REAL_BLOCK)

    first = points[0]
    assert first.valid_start_ns == first.valid_end_ns
    assert first.valid_end_ns == CYCLE_NS + 12 * 3600 * NS  # FHR 12 -> 00Z next day
    for point in points:
        end = dt.datetime.fromtimestamp(point.valid_end_ns / NS, tz=dt.UTC)
        assert end.hour in TXN_PERIOD_END_UTC_HOURS


def test_a_station_not_asked_for_is_not_parsed() -> None:
    points, drops = parse(REAL_BLOCK, stations=frozenset({"KSFO"}))

    assert points == ()
    assert drops["station_block_missing"] == 1


# ---------------------------------------------------------------------------
# Absences: named, never invented
# ---------------------------------------------------------------------------


def test_a_blank_period_end_column_is_recorded_as_not_published() -> None:
    points, _ = parse(block(txn={6: "76"}))

    by_hour = {point.valid_end_ns: point for point in points}
    assert len(by_hour) == 6
    absent = [p for p in points if p.value_f is None]
    assert {p.absence_reason for p in absent} == {"not_published"}
    assert [p.value_f for p in points if p.value_f is not None] == [76.0]


@pytest.mark.parametrize("sentinel", ["-99", "999"])
def test_a_sentinel_maps_through_forecast_value_or_none_as_sentinel(sentinel: str) -> None:
    points, _ = parse(block(txn={2: sentinel}))

    first = points[0]
    assert first.value_f is None
    assert first.absence_reason == "sentinel"


def test_an_unreadable_token_is_a_parse_failure_and_never_a_value() -> None:
    points, _ = parse(block(txn={2: "**"}))

    first = points[0]
    assert first.value_f is None
    assert first.absence_reason == "parse_failure"


# ---------------------------------------------------------------------------
# Drift raises. It never coerces.
# ---------------------------------------------------------------------------


def test_a_body_with_no_station_header_at_all_raises() -> None:
    with pytest.raises(NbsBulletinDriftError, match="no NBS station block"):
        parse("1\n\n SOMETHING ELSE ENTIRELY\n")


def test_a_header_whose_model_tokens_changed_raises() -> None:
    with pytest.raises(NbsBulletinDriftError):
        parse(block(header=" KMIA    NBM NBS GUIDANCE    9/19/2026  1200 UTC"))


@pytest.mark.parametrize("label", ["UTC", "FHR", "TXN"])
def test_a_missing_required_row_raises(label: str) -> None:
    with pytest.raises(NbsBulletinDriftError, match=label):
        parse(block(drop=frozenset({label})))


def test_a_utc_row_that_disagrees_with_the_projection_hours_raises() -> None:
    """The cross-check that catches a silently reshaped column grid."""
    hours = list(REAL_UTC_HOURS)
    hours[2] = 1  # the 00Z period end relabelled 01Z
    with pytest.raises(NbsBulletinDriftError, match="disagrees"):
        parse(block(hours=hours))


def test_unequal_utc_and_fhr_column_counts_raise() -> None:
    with pytest.raises(NbsBulletinDriftError, match="column"):
        parse(block(hours=REAL_UTC_HOURS[:20]))


def test_a_txn_value_outside_the_measured_period_end_hours_raises() -> None:
    """FC-0a census: txn is published at 00Z and 12Z only, 0/14,720 elsewhere."""
    with pytest.raises(NbsBulletinDriftError, match="03"):
        parse(block(txn={3: "84"}))


def test_a_non_numeric_projection_hour_raises() -> None:
    rows = block().splitlines()
    rows[1] = rows[1].replace(" 00", " XX", 1)
    with pytest.raises(NbsBulletinDriftError):
        parse("\n".join(rows) + "\n")


# ---------------------------------------------------------------------------
# Memory bound: work is proportional to the REQUESTED stations, not the body
# ---------------------------------------------------------------------------
#
# The live collective bulletin measured 29,720,949 bytes (~28.35 MiB) on
# 2026-09-19 and holds every NBM station. Materialising a line list for every
# block before selecting the four this bot trades makes peak RSS a multiple of
# the body -- inside the LIVE TRADE NODE, against a unit `MemoryMax`. These
# tests pin the structural property that bounds it.
#
# Allocation is not measured directly (a `tracemalloc` threshold would be a
# flaky change-detector); what is asserted instead is the property that
# CAUSES the allocation: exactly one block is ever split per requested station
# that is present, regardless of how many stations the body carries.


def many_station_bulletin(count: int, *, wanted: tuple[str, ...] = ("KMIA", "KSFO")) -> str:
    """A bulletin with `count` filler blocks plus the `wanted` ones, interleaved."""
    stations = [f"{index:06d}" for index in range(count)]
    for offset, station in enumerate(wanted):
        stations.insert(min(offset * 3 + 1, len(stations)), station)
    return "".join(
        block(header=f" {station}    NBM V5.0 NBS GUIDANCE    9/19/2026  1200 UTC",
              txn={2: "84", 6: "76"})
        for station in stations
    )


@pytest.mark.parametrize("filler", [8, 400])
def test_only_the_requested_station_blocks_are_ever_split(
    filler: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Splits stay at 2 whether the body carries 10 blocks or 402."""
    from breezy.ingest import nbm_forecast_parse

    split: list[tuple[int, int]] = []
    original = nbm_forecast_parse._block_lines

    def counting(text: str, start: int, end: int) -> list[str]:
        split.append((start, end))
        return original(text, start, end)

    monkeypatch.setattr(nbm_forecast_parse, "_block_lines", counting)

    points, drops = parse(
        many_station_bulletin(filler), stations=frozenset({"KMIA", "KSFO"})
    )

    assert len(split) == 2, "one split per REQUESTED station, never per block in the body"
    assert drops == {}
    # Six period-end columns per station; the two populated ones carry values
    # and the other four are explicit `not_published` absences.
    assert len(points) == 12
    assert {point.station for point in points} == {"KMIA", "KSFO"}
    assert sorted(p.value_f for p in points if p.value_f is not None) == [76.0, 76.0, 84.0, 84.0]


def test_a_requested_station_that_is_absent_costs_no_split(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.ingest import nbm_forecast_parse

    split: list[tuple[int, int]] = []
    original = nbm_forecast_parse._block_lines

    def counting(text: str, start: int, end: int) -> list[str]:
        split.append((start, end))
        return original(text, start, end)

    monkeypatch.setattr(nbm_forecast_parse, "_block_lines", counting)

    points, drops = parse(many_station_bulletin(20), stations=frozenset({"KLAX"}))

    assert split == []
    assert points == ()
    assert drops["station_block_missing"] == 1


def test_the_body_cap_is_pinned_to_the_measured_bulletin_size() -> None:
    """The cap has headroom over the measured maximum -- and a ceiling on that headroom.

    Bounded BOTH ways on purpose: too low truncates a legitimately larger
    future bulletin via `OversizeBodyError`, too high stops being a control.
    """
    from breezy.ingest.nbm_forecast_transport import (
        DEFAULT_NBM_MAX_BODY_BYTES,
        MEASURED_MAX_BULLETIN_BYTES,
    )

    assert MEASURED_MAX_BULLETIN_BYTES == 29_720_949
    assert DEFAULT_NBM_MAX_BODY_BYTES >= int(MEASURED_MAX_BULLETIN_BYTES * 1.5)
    assert DEFAULT_NBM_MAX_BODY_BYTES <= int(MEASURED_MAX_BULLETIN_BYTES * 2)
