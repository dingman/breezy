"""Unit tests for `breezy.ingest.nws_observations` -- BL-24 Seam B, section 1.

The parser converts one ``GET /stations/{icao}/observations`` GeoJSON payload
into `StationObservation` records under the precision rule of
``docs/plans/BL24_SEAM_B_BRIEF_2026-09-04.md`` section 1: a METAR ``T`` group
is exact (tenths, ``precision_c_tenths=5``); an integer-valued Celsius value
is an interval (``precision_c_tenths=10``); anything else is DROPPED AND
COUNTED, never rounded (L-17).

Rows below are shaped exactly like the recorded fixture
``tests/fixtures/nws/kmdw_observations_2026-09-04.json`` (fetched
2026-09-04T02:34:57Z); only the fields the parser reads are carried.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from breezy.ingest import iem_observations, nws_observations
from breezy.ingest.nws_observations import (
    NWS_OBSERVATION_SOURCE_CHANNEL,
    largest_gap_ns,
    nws_observation_rows_to_station_observations,
    station_observation_data_type,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nws"
FIXTURE_FILE = FIXTURE / "kmdw_observations_2026-09-04.json"

_RECEIVED_AT_NS = 2_000_000_000_000_000_000  # far future: always > any test row
_LAG_NS = 1_260_000_000_000  # 21 min, provenance only (A6)
_NS = 1_000_000_000


def _row(
    *,
    timestamp: str = "2026-09-04T02:20:00+00:00",
    value: Any = 22,
    unit_code: str = "wmoUnit:degC",
    raw_message: str = "",
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "timestamp": timestamp,
            "rawMessage": raw_message,
            "temperature": {"unitCode": unit_code, "value": value, "qualityControl": "V"},
        },
    }


def _payload(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(rows)}


def _parse(payload: dict[str, Any]) -> tuple[tuple[Any, ...], Counter[str]]:
    return nws_observation_rows_to_station_observations(
        station="KMDW",
        payload=payload,
        source_channel=NWS_OBSERVATION_SOURCE_CHANNEL,
        assumed_publication_lag_ns=_LAG_NS,
        received_at_ns=_RECEIVED_AT_NS,
    )


def test_an_integer_celsius_row_carries_ten_tenths_of_precision() -> None:
    observations, drops = _parse(_payload(_row(value=22.0)))

    assert drops == Counter()
    (record,) = observations
    assert record.temp_c_tenths == 220
    assert record.precision_c_tenths == 10
    assert record.is_metar is False
    assert record.source_channel == NWS_OBSERVATION_SOURCE_CHANNEL
    assert record.station == "KMDW"
    assert record.received_at_ns == _RECEIVED_AT_NS
    assert record.assumed_publication_lag_ns == _LAG_NS


def test_a_row_with_a_metar_t_group_is_exact_and_flagged_is_metar() -> None:
    raw = "KMDW 040153Z 09008KT 10SM CLR 22/13 A3020 RMK AO2 SLP224 T02170128"
    observations, drops = _parse(_payload(_row(value=21.7, raw_message=raw)))

    assert drops == Counter()
    (record,) = observations
    assert record.temp_c_tenths == 217
    assert record.precision_c_tenths == 5
    assert record.is_metar is True


def test_a_non_integer_celsius_row_with_no_t_group_is_dropped_and_counted() -> None:
    observations, drops = _parse(_payload(_row(value=21.7, raw_message="")))

    assert observations == ()
    assert drops == Counter({"unparseable_row": 1})


def test_a_null_temperature_row_is_dropped_and_counted() -> None:
    observations, drops = _parse(_payload(_row(value=None)))

    assert observations == ()
    assert drops == Counter({"null_temperature_row": 1})


def test_an_unexpected_unit_code_is_dropped_and_counted() -> None:
    observations, drops = _parse(_payload(_row(value=72, unit_code="wmoUnit:degF")))

    assert observations == ()
    assert drops == Counter({"unexpected_unit_code": 1})


def test_the_observed_instant_is_built_with_integer_nanoseconds() -> None:
    observations, _ = _parse(_payload(_row(timestamp="2026-09-04T02:20:00+00:00")))

    (record,) = observations
    expected = int(dt.datetime(2026, 9, 4, 2, 20, tzinfo=dt.UTC).timestamp()) * _NS
    assert record.observed_at_ns == expected
    assert record.ts_event == expected
    assert isinstance(record.observed_at_ns, int)
    # No float time math: the seconds are an exact multiple of 1e9 ns.
    assert record.observed_at_ns % _NS == 0


def test_an_unparsable_timestamp_is_dropped_and_counted() -> None:
    observations, drops = _parse(_payload(_row(timestamp="not-a-time")))

    assert observations == ()
    assert drops == Counter({"observation_parse_error": 1})


def test_a_boolean_temperature_is_not_an_integer_celsius_value() -> None:
    observations, drops = _parse(_payload(_row(value=True)))

    assert observations == ()
    assert drops == Counter({"unparseable_row": 1})


def test_the_parser_reuses_the_one_shared_data_type_factory() -> None:
    """W1: no second `DataType(StationObservation)` -- the name is a re-export."""
    assert station_observation_data_type is iem_observations.station_observation_data_type
    assert nws_observations.station_observation_data_type() is (
        iem_observations.station_observation_data_type()
    )


def test_a_payload_without_a_features_list_is_refused() -> None:
    with pytest.raises(ValueError, match="features"):
        _parse({"type": "FeatureCollection"})


#: Independent re-implementation of the parser's own `METAR_T_RE` (module
#: docstring precision rule) -- a SEPARATE regex object, not an import of the
#: parser's, so a parser regression cannot silently agree with itself here.
_INDEPENDENT_METAR_T_RE = re.compile(
    r"(?:^|\s)T(?P<air_sign>[01])(?P<air_tenths>\d{3})[01]\d{3}(?:\s|$)"
)


def _derive_expected_counts(payload: dict[str, Any]) -> tuple[int, int, int]:
    """Walk the raw fixture JSON and independently classify every row.

    Mirrors the parser's documented precedence exactly (module docstring):
    a `temperature.unitCode` other than `wmoUnit:degC` is dropped first
    (`unexpected_unit_code`, checked ahead of the T-group per the parser's
    own row loop); else a non-empty `rawMessage` carrying a METAR T group is
    exact (METAR); else an integer-valued `temperature.value` is an interval
    row; else the row is dropped (`null_temperature_row` /
    `unparseable_row`). Returns `(metar_count, interval_count,
    dropped_count)`, computed from the raw JSON -- never by calling the
    parser under test.
    """
    metar_count = 0
    interval_count = 0
    dropped_count = 0
    for feature in payload["features"]:
        properties = feature.get("properties", {})
        temperature = properties.get("temperature", {})
        raw_message = properties.get("rawMessage", "")
        value = temperature.get("value")
        unit_code = temperature.get("unitCode")

        if unit_code != "wmoUnit:degC":
            dropped_count += 1
            continue
        if isinstance(raw_message, str) and _INDEPENDENT_METAR_T_RE.search(raw_message):
            metar_count += 1
            continue
        if value is None or isinstance(value, bool):
            dropped_count += 1
            continue
        if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
            interval_count += 1
            continue
        dropped_count += 1
    return metar_count, interval_count, dropped_count


def test_the_recorded_fixture_parses_with_only_the_documented_drop_reasons() -> None:
    payload = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))

    observations, drops = _parse(payload)

    assert len(payload["features"]) == 500
    assert set(drops) <= {"unparseable_row", "null_temperature_row", "unexpected_unit_code"}
    assert len(observations) + sum(drops.values()) == 500
    assert all(o.received_at_ns > o.observed_at_ns for o in observations)
    assert {o.precision_c_tenths for o in observations} <= {5, 10}
    assert any(o.is_metar for o in observations)
    assert any(not o.is_metar for o in observations)

    expected_metar, expected_interval, expected_dropped = _derive_expected_counts(payload)
    metar_count = sum(1 for o in observations if o.is_metar)
    interval_count = sum(1 for o in observations if not o.is_metar)

    assert expected_metar + expected_interval + expected_dropped == 500
    assert metar_count == expected_metar
    assert interval_count == expected_interval
    assert sum(drops.values()) == expected_dropped


# ---------------------------------------------------------------------------
# largest_gap_ns -- pure, ingest-local, no strategy import
# ---------------------------------------------------------------------------


def test_largest_gap_is_none_for_fewer_than_two_rows() -> None:
    assert largest_gap_ns(()) is None
    assert largest_gap_ns((5,)) is None


def test_largest_gap_is_the_largest_consecutive_difference() -> None:
    assert largest_gap_ns((0, 300 * _NS, 600 * _NS, 1_800 * _NS, 2_100 * _NS)) == 1_200 * _NS


def test_largest_gap_refuses_an_unsorted_sequence() -> None:
    with pytest.raises(ValueError, match="sorted"):
        largest_gap_ns((10, 5))
