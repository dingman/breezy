"""Unit tests for `breezy.ingest.iem_observations` -- BL-24 Seam A.

`parse_metar_t_group` is a PORT of
`scripts/analysis/settlement_alignment_study.py:234-239`, not an import from
`scripts/` into `src/` -- the differential test below pins the two against
each other so they cannot silently drift.
"""

from __future__ import annotations

from collections import Counter
from types import ModuleType

import pytest

from breezy.domain.station_observation import StationObservation
from breezy.ingest.iem_observations import (
    iem_asos_rows_to_station_observations,
    parse_metar_t_group,
    station_observation_data_type,
)
from tests.unit.test_pmr_climatology_study import _load_study_module, _metar_row

_RECEIVED_AT_NS = 2_000_000_000_000_000_000  # far future: always > any test row


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return _load_study_module()


# ---------------------------------------------------------------------------
# Differential: the port agrees with the original on every input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_metar",
    [
        "KNYC 010000Z AUTO 25009KT 10SM CLR 15/07 A3015 RMK AO2 T01500070",
        "KNYC 010000Z AUTO 25009KT 10SM CLR M05/M10 A3015 RMK AO2 T10501100",
        "KNYC 010000Z AUTO 25009KT 10SM CLR A3015 RMK AO2",  # no T group
        "",
        "T99999999",  # malformed digit run, still matches the pattern shape
    ],
)
def test_the_port_agrees_with_the_original_parser(study: ModuleType, raw_metar: str) -> None:
    assert parse_metar_t_group(raw_metar) == study.parse_metar_t_group(raw_metar)


# ---------------------------------------------------------------------------
# Drop-and-count, never interpolate (L-17)
# ---------------------------------------------------------------------------


def test_unparseable_metar_row_is_dropped_and_counted() -> None:
    rows = [{"station": "KNYC", "valid": "2026-07-15 04:00", "metar": "GARBAGE NO T GROUP"}]

    observations, drops = iem_asos_rows_to_station_observations(
        station="KNYC",
        rows=rows,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=30_000_000_000,
        received_at_ns=_RECEIVED_AT_NS,
    )

    assert observations == ()
    assert drops == Counter({"missing_metar_t_group_row": 1})


def test_a_row_with_no_t_group_does_not_become_a_zero() -> None:
    """A missing reading must never silently arrive as `temp_c_tenths=0`."""
    rows = [_metar_row(station="NYC", valid="2026-07-15 04:00", t_group="")]

    observations, drops = iem_asos_rows_to_station_observations(
        station="KNYC",
        rows=rows,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=30_000_000_000,
        received_at_ns=_RECEIVED_AT_NS,
    )

    assert observations == ()
    assert drops["missing_metar_t_group_row"] == 1
    assert 0 not in [obs.temp_c_tenths for obs in observations]


def test_an_unparseable_valid_column_is_dropped_and_counted() -> None:
    rows = [{"station": "KNYC", "valid": "not-a-timestamp", "metar": "T01500070"}]

    observations, drops = iem_asos_rows_to_station_observations(
        station="KNYC",
        rows=rows,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=30_000_000_000,
        received_at_ns=_RECEIVED_AT_NS,
    )

    assert observations == ()
    assert drops == Counter({"archive_parse_error": 1})


def test_a_well_formed_row_becomes_one_station_observation() -> None:
    rows = [_metar_row(station="NYC", valid="2026-07-15 04:00", t_group="T01500070")]

    observations, drops = iem_asos_rows_to_station_observations(
        station="KNYC",
        rows=rows,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=30_000_000_000,
        received_at_ns=_RECEIVED_AT_NS,
    )

    assert not drops
    (observation,) = observations
    assert isinstance(observation, StationObservation)
    assert observation.station == "KNYC"
    assert observation.temp_c_tenths == 150
    assert observation.source_channel == "iem_asos_metar"


def test_multiple_rows_mix_kept_and_dropped_independently() -> None:
    rows = [
        _metar_row(station="NYC", valid="2026-07-15 04:00", t_group="T01500070"),
        {"station": "NYC", "valid": "2026-07-15 04:05", "metar": "NO T GROUP HERE"},
        _metar_row(station="NYC", valid="2026-07-15 04:10", t_group="T01600080"),
    ]

    observations, drops = iem_asos_rows_to_station_observations(
        station="KNYC",
        rows=rows,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=30_000_000_000,
        received_at_ns=_RECEIVED_AT_NS,
    )

    assert len(observations) == 2
    assert drops == Counter({"missing_metar_t_group_row": 1})


# ---------------------------------------------------------------------------
# The shared `DataType` factory
# ---------------------------------------------------------------------------


def test_station_observation_data_type_is_a_single_cached_object() -> None:
    assert station_observation_data_type() is station_observation_data_type()
    assert station_observation_data_type().metadata == {}


# ---------------------------------------------------------------------------
# `observed_at_ns` is built by integer construction, never float time math
# ---------------------------------------------------------------------------


def test_observed_at_ns_round_trips_a_minute_precision_timestamp_exactly() -> None:
    """`observed_at_ns` must equal the calendar-exact nanosecond instant.

    Computed independently via `datetime` field arithmetic (never
    `.timestamp() * 1e9`) so this test cannot share the bug it is pinning.
    """
    import datetime as dt

    valid_utc = dt.datetime(2026, 7, 15, 4, 7, tzinfo=dt.UTC)
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    expected_ns = int((valid_utc - epoch).total_seconds()) * 1_000_000_000

    rows = [_metar_row(station="NYC", valid="2026-07-15 04:07", t_group="T01500070")]
    observations, drops = iem_asos_rows_to_station_observations(
        station="KNYC",
        rows=rows,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=30_000_000_000,
        received_at_ns=_RECEIVED_AT_NS,
    )

    assert not drops
    (observation,) = observations
    assert observation.observed_at_ns == expected_ns
