"""Parse NWS ``GET /stations/{icao}/observations`` GeoJSON into `StationObservation` records.

BL-24 Seam B, section 1 (``docs/plans/BL24_SEAM_B_BRIEF_2026-09-04.md``).
Mirrors :func:`breezy.ingest.iem_observations.iem_asos_rows_to_station_observations`
and REUSES its METAR ``T``-group decoder and its ONE shared ``DataType``
factory -- this module constructs no second ``DataType`` (barrier W1).

Precision rule (amendment A13), applied in this order to every row:

1. ``rawMessage`` is non-empty and carries a METAR ``T`` group -> the reading
   is EXACT to tenths: ``temp_c_tenths=<tenths>``, ``is_metar=True``,
   ``precision_c_tenths=5``.
2. else ``temperature.value`` is an integer-valued Celsius number -> the
   reading is an INTERVAL: ``temp_c_tenths=int(value)*10``,
   ``is_metar=False``, ``precision_c_tenths=10``.
3. else -- a non-integer value with no ``T`` group, or ``null`` -- the row is
   DROPPED AND COUNTED (``unparseable_row`` / ``null_temperature_row``).
   Never rounded, never interpolated (L-17).

A ``temperature.unitCode`` other than ``wmoUnit:degC`` is dropped and counted
as ``unexpected_unit_code``; an unparsable ``timestamp`` as
``observation_parse_error``.

Timestamps are built on the integer path only: no ``float`` time arithmetic
anywhere (amendment A7, "one clock", and ``iem_observations.py``'s note on
precision loss at epoch magnitudes).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final

from breezy.domain.station_observation import StationObservation
from breezy.ingest.iem_observations import parse_metar_t_group, station_observation_data_type

__all__ = [
    "EXPECTED_TEMPERATURE_UNIT_CODE",
    "INTEGER_CELSIUS_PRECISION_C_TENTHS",
    "METAR_PRECISION_C_TENTHS",
    "NWS_OBSERVATION_SOURCE_CHANNEL",
    "NwsObservationPayloadError",
    "largest_gap_ns",
    "nws_observation_rows_to_station_observations",
    "station_observation_data_type",
]

#: The `StationObservation.source_channel` for rows from the NWS API.
NWS_OBSERVATION_SOURCE_CHANNEL: Final[str] = "nws_api_observations"

#: The only unit the parser accepts. Anything else is dropped and counted.
EXPECTED_TEMPERATURE_UNIT_CODE: Final[str] = "wmoUnit:degC"

#: Full interval width, in tenths of a degree C -- see `StationObservation`.
METAR_PRECISION_C_TENTHS: Final[int] = 5
INTEGER_CELSIUS_PRECISION_C_TENTHS: Final[int] = 10

_NS_PER_SECOND: Final[int] = 1_000_000_000
_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


class NwsObservationPayloadError(ValueError):
    """The response is not a GeoJSON ``FeatureCollection`` with a ``features`` list."""


@dataclass(frozen=True, slots=True)
class _Reading:
    temp_c_tenths: int
    precision_c_tenths: int
    is_metar: bool


def _features(payload: Mapping[str, Any]) -> Sequence[Any]:
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list):
        raise NwsObservationPayloadError(
            "NWS observations payload carries no `features` list; refusing to parse"
        )
    return features


def _observed_at_ns(raw_timestamp: object) -> int | None:
    """UNIX nanoseconds of an ISO-8601 timestamp, or `None` if it does not parse."""
    if not isinstance(raw_timestamp, str):
        return None
    try:
        instant = dt.datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return None
    if instant.tzinfo is None:
        return None
    # Integer construction only: `timedelta` fields are exact integers, so the
    # epoch offset never passes through a float.
    delta = instant.astimezone(dt.UTC) - _EPOCH
    seconds = delta.days * 86_400 + delta.seconds
    return seconds * _NS_PER_SECOND + delta.microseconds * 1_000


def _decode_reading(raw_message: object, value: object) -> _Reading | str:
    """Apply the precision rule; return a reading, or the drop reason."""
    if isinstance(raw_message, str) and raw_message:
        tenths = parse_metar_t_group(raw_message)
        if tenths is not None:
            return _Reading(tenths, METAR_PRECISION_C_TENTHS, True)
    if value is None:
        return "null_temperature_row"
    # `bool` is an `int` subclass and is not a temperature.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "unparseable_row"
    if isinstance(value, float) and not value.is_integer():
        return "unparseable_row"
    return _Reading(int(value) * 10, INTEGER_CELSIUS_PRECISION_C_TENTHS, False)


def nws_observation_rows_to_station_observations(
    *,
    station: str,
    payload: Mapping[str, Any],
    source_channel: str,
    assumed_publication_lag_ns: int,
    received_at_ns: int,
) -> tuple[tuple[StationObservation, ...], Counter[str]]:
    """Convert one observations payload to `StationObservation` records.

    Every dropped row is counted under one of `unexpected_unit_code`,
    `observation_parse_error`, `null_temperature_row` or `unparseable_row`
    -- never silently skipped, never interpolated, never rounded (L-17).

    `received_at_ns` is the transport's receipt stamp for the whole response
    (`FetchResult.retrieved_at_ns`), applied to every row in this call.
    `assumed_publication_lag_ns` is provenance only (amendment A6).
    """
    observations: list[StationObservation] = []
    drops: Counter[str] = Counter()
    for feature in _features(payload):
        properties = feature.get("properties") if isinstance(feature, Mapping) else None
        temperature = properties.get("temperature") if isinstance(properties, Mapping) else None
        if not isinstance(properties, Mapping) or not isinstance(temperature, Mapping):
            drops["observation_parse_error"] += 1
            continue
        if temperature.get("unitCode") != EXPECTED_TEMPERATURE_UNIT_CODE:
            drops["unexpected_unit_code"] += 1
            continue
        observed_at_ns = _observed_at_ns(properties.get("timestamp"))
        if observed_at_ns is None:
            drops["observation_parse_error"] += 1
            continue
        reading = _decode_reading(properties.get("rawMessage"), temperature.get("value"))
        if isinstance(reading, str):
            drops[reading] += 1
            continue
        try:
            record = StationObservation(
                station=station,
                observed_at_ns=observed_at_ns,
                received_at_ns=received_at_ns,
                temp_c_tenths=reading.temp_c_tenths,
                precision_c_tenths=reading.precision_c_tenths,
                is_metar=reading.is_metar,
                source_channel=source_channel,
                assumed_publication_lag_ns=assumed_publication_lag_ns,
            )
        except ValueError:
            # e.g. an observation stamped after our own receipt instant.
            drops["observation_parse_error"] += 1
            continue
        observations.append(record)
    return tuple(observations), drops


def largest_gap_ns(sorted_observed_ns: Sequence[int]) -> int | None:
    """The largest difference between CONSECUTIVE instants, or `None` if fewer than two.

    Ingest-local on purpose: the `lint-imports` layer contract places
    `strategy` above `ingest`, so `RunningExtremeAccumulator.coverage` is not
    reachable from here (brief section 3, least-confident decision 2).
    """
    if len(sorted_observed_ns) < 2:
        return None
    largest = 0
    for earlier, later in pairwise(sorted_observed_ns):
        if later < earlier:
            raise ValueError("`sorted_observed_ns` must be sorted ascending")
        largest = max(largest, later - earlier)
    return largest
