"""SL-3 TASK B: the pure core of the NBP publication-lag census script.

No network here -- `_fetch_listing`/`main --live` are exercised only by a
live, human-run collection (see the module docstring); these tests cover
everything network-free: version-era classification, the fixed sample-date
set, and parsing a `LastModified` out of a raw `ListObjectsV2` XML listing.
"""

from __future__ import annotations

import datetime as dt

from scripts.analysis.nbp_lag_census import (
    CYCLES,
    CensusRecord,
    _record_for,
    parse_last_modified,
    sample_dates,
    version_for,
)

_LISTING_ONE_KEY = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>noaa-nbm-grib2-pds</Name>
  <Contents>
    <Key>blend.20260928/13/text/blend_nbptx.t13z</Key>
    <LastModified>2026-09-28T14:03:18.000Z</LastModified>
    <Size>34714882</Size>
  </Contents>
</ListBucketResult>"""

_LISTING_WITH_SIDECAR = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>noaa-nbm-grib2-pds</Name>
  <Contents>
    <Key>blend.20260928/13/text/blend_nbptx.t13z.idx</Key>
    <LastModified>2026-09-28T14:02:00.000Z</LastModified>
    <Size>512</Size>
  </Contents>
  <Contents>
    <Key>blend.20260928/13/text/blend_nbptx.t13z</Key>
    <LastModified>2026-09-28T14:03:18.000Z</LastModified>
    <Size>34714882</Size>
  </Contents>
</ListBucketResult>"""

_LISTING_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>noaa-nbm-grib2-pds</Name>
  <KeyCount>0</KeyCount>
</ListBucketResult>"""


# ---------------------------------------------------------------------------
# Version-era classification
# ---------------------------------------------------------------------------


def test_version_boundaries_are_exact() -> None:
    assert version_for(dt.date(2020, 9, 29)) == "v4.0"
    assert version_for(dt.date(2023, 1, 16)) == "v4.0"
    assert version_for(dt.date(2023, 1, 17)) == "v4.1"
    assert version_for(dt.date(2024, 5, 14)) == "v4.1"
    assert version_for(dt.date(2024, 5, 15)) == "v4.2"
    assert version_for(dt.date(2025, 5, 26)) == "v4.2"
    assert version_for(dt.date(2025, 5, 27)) == "v4.3"
    assert version_for(dt.date(2026, 5, 3)) == "v4.3"
    assert version_for(dt.date(2026, 5, 4)) == "v5.0"
    assert version_for(dt.date(2026, 9, 29)) == "v5.0"


def test_a_date_before_the_earliest_era_still_returns_the_earliest_era() -> None:
    assert version_for(dt.date(2019, 1, 1)) == "v4.0"


# ---------------------------------------------------------------------------
# Sample-date construction
# ---------------------------------------------------------------------------


def test_sample_dates_covers_at_least_sixty_dates_and_spans_every_era() -> None:
    dates = sample_dates(dt.date(2026, 9, 29))

    assert len(dates) >= 60
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)

    versions = {version_for(d) for d in dates}
    assert versions == {"v4.0", "v4.1", "v4.2", "v4.3", "v5.0"}


def test_sample_dates_includes_the_last_thirty_days_ending_today() -> None:
    today = dt.date(2026, 9, 29)
    dates = sample_dates(today)

    for offset in range(30):
        assert today - dt.timedelta(days=offset) in dates


def test_sample_dates_is_deterministic_for_the_same_today() -> None:
    today = dt.date(2026, 9, 29)
    assert sample_dates(today) == sample_dates(today)


# ---------------------------------------------------------------------------
# Six cycles, exactly as the plan names
# ---------------------------------------------------------------------------


def test_the_cycles_are_exactly_those_named_in_the_plan() -> None:
    assert CYCLES == (0, 1, 7, 12, 13, 19)


# ---------------------------------------------------------------------------
# Parsing a raw ListObjectsV2 listing
# ---------------------------------------------------------------------------


def test_parse_last_modified_reads_the_one_key() -> None:
    assert parse_last_modified(_LISTING_ONE_KEY, hour=13) == "2026-09-28T14:03:18.000Z"


def test_parse_last_modified_prefers_the_exact_key_over_a_sidecar() -> None:
    assert parse_last_modified(_LISTING_WITH_SIDECAR, hour=13) == "2026-09-28T14:03:18.000Z"


def test_parse_last_modified_returns_none_for_an_empty_listing() -> None:
    assert parse_last_modified(_LISTING_EMPTY, hour=13) is None


def test_parse_last_modified_returns_none_for_malformed_xml() -> None:
    assert parse_last_modified("not xml", hour=13) is None


# ---------------------------------------------------------------------------
# Record construction: OK and MISSING
# ---------------------------------------------------------------------------


def test_record_for_a_present_listing_computes_the_lag() -> None:
    record = _record_for(_LISTING_ONE_KEY, date=dt.date(2026, 9, 28), hour=13)

    assert record.status == "OK"
    assert record.version == "v5.0"
    assert record.last_modified == "2026-09-28T14:03:18.000Z"
    assert record.lag_seconds == 3798.0
    assert record.lag_minutes is not None
    assert round(record.lag_minutes, 2) == 63.3


def test_record_for_a_missing_listing_is_missing_status() -> None:
    record = _record_for(_LISTING_EMPTY, date=dt.date(2026, 9, 28), hour=13)

    assert record.status == "MISSING"
    assert record.last_modified is None
    assert record.lag_seconds is None


def test_record_for_no_response_at_all_is_missing_status() -> None:
    record = _record_for(None, date=dt.date(2026, 9, 28), hour=13)

    assert record.status == "MISSING"


def test_a_census_record_serialises_to_the_committed_schema() -> None:
    record = CensusRecord(
        date="2026-09-28",
        cycle_hour=13,
        version="v5.0",
        cycle_iso="2026-09-28T13:00:00+00:00",
        status="OK",
        last_modified="2026-09-28T14:03:18.000Z",
        lag_seconds=3798.0,
        lag_minutes=63.3,
    )

    payload = record.to_json()

    assert payload == {
        "date": "2026-09-28",
        "cycle_hour": 13,
        "version": "v5.0",
        "cycle_iso": "2026-09-28T13:00:00+00:00",
        "status": "OK",
        "last_modified": "2026-09-28T14:03:18.000Z",
        "lag_seconds": 3798.0,
        "lag_minutes": 63.3,
    }


# ---------------------------------------------------------------------------
# The script never imports nautilus_trader or breezy -- it is a standalone
# stdlib script (module docstring).
# ---------------------------------------------------------------------------


def test_the_script_imports_no_nautilus_trader_or_breezy() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "nbp_lag_census.py"
    ).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import nautilus_trader", "from nautilus_trader")):
            raise AssertionError("nbp_lag_census.py must never import nautilus_trader")
        if stripped.startswith(("import breezy", "from breezy")):
            raise AssertionError("nbp_lag_census.py must never import breezy")
