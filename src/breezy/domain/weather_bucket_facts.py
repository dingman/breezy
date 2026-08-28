"""Typed strategy-facing facts for whole-degree Fahrenheit weather buckets.

This module is deliberately narrower than a general market-facts layer. It
describes only temperature bucket intervals and the primitive site/day fields
needed to decide whether a weather record applies to that bucket.
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from breezy.domain.validation import require_int, require_text

__all__ = [
    "CLIMATE_DAY_KEY",
    "MEASURE_KEY",
    "SETTLEMENT_STATION_KEY",
    "STRIKE_LOWER_F_KEY",
    "STRIKE_UPPER_F_KEY",
    "WEATHER_FACTS_STATUS_KEY",
    "WEATHER_FACTS_STATUS_KNOWN",
    "WEATHER_FACTS_STATUS_UNKNOWN",
    "Measure",
    "WeatherBucketFacts",
    "WeatherFactsUnavailableError",
    "is_weather_market",
    "read_weather_bucket_facts",
]

#: Key vocabulary written into ``Instrument.info`` by venue adapters.
#: Values are scalars only: ``str``, ``int`` or ``None``.
WEATHER_FACTS_STATUS_KEY: str = "weather_facts_status"
WEATHER_FACTS_STATUS_KNOWN: str = "KNOWN"
WEATHER_FACTS_STATUS_UNKNOWN: str = "UNKNOWN"
SETTLEMENT_STATION_KEY: str = "settlement_station"
CLIMATE_DAY_KEY: str = "climate_date"
MEASURE_KEY: str = "measure"
STRIKE_LOWER_F_KEY: str = "strike_lower_f"
STRIKE_UPPER_F_KEY: str = "strike_upper_f"


class WeatherFactsUnavailableError(ValueError):
    """Raised when weather-bucket facts are absent or unsafe to consume."""


@enum.unique
class Measure(enum.Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True, slots=True, kw_only=True)
class WeatherBucketFacts:
    settlement_station: str
    climate_day: dt.date
    measure: Measure
    lower_f: int | None
    upper_f: int | None

    def contains(self, reading_f: int) -> bool:
        """Return whether ``reading_f`` is inside this closed interval.

        The interval is closed at both finite ends. This is the venue-prose
        reading that made the captured ladders tile in 114/114 groups.
        """
        reading = require_int(reading_f, "reading_f")
        return (self.lower_f is None or reading >= self.lower_f) and (
            self.upper_f is None or reading <= self.upper_f
        )

    def distance_f(self, reading_f: int) -> int:
        """Unsigned degrees from ``reading_f`` to the closed interval."""
        reading = require_int(reading_f, "reading_f")
        if self.contains(reading):
            return 0
        if self.lower_f is not None and reading < self.lower_f:
            return self.lower_f - reading
        if self.upper_f is not None and reading > self.upper_f:
            return reading - self.upper_f
        return 0

    def applies_to(self, station: str, climate_day: dt.date) -> bool:
        return station == self.settlement_station and climate_day == self.climate_day


def read_weather_bucket_facts(info: object) -> WeatherBucketFacts:
    """Read weather-bucket facts from an ``Instrument.info``-style mapping.

    ``Instrument.info`` erases to ``Any`` at the Nautilus boundary, so call-site
    type checking cannot prove these facts are present or usable. Runtime
    validation is the fail-closed guard.
    """
    mapping = _require_mapping(info)
    status = _require_present(mapping, WEATHER_FACTS_STATUS_KEY)
    if status != WEATHER_FACTS_STATUS_KNOWN:
        raise WeatherFactsUnavailableError(
            f"{WEATHER_FACTS_STATUS_KEY}: expected {WEATHER_FACTS_STATUS_KNOWN!r}, "
            f"got {status!r}"
        )

    settlement_station = _require_text_fact(mapping, SETTLEMENT_STATION_KEY)
    climate_day = _require_climate_day(mapping)
    measure = _require_measure(mapping)
    lower_f = _require_optional_int_fact(mapping, STRIKE_LOWER_F_KEY)
    upper_f = _require_optional_int_fact(mapping, STRIKE_UPPER_F_KEY)
    if lower_f is None and upper_f is None:
        raise WeatherFactsUnavailableError(
            f"{STRIKE_LOWER_F_KEY}/{STRIKE_UPPER_F_KEY}: both bounds cannot be None"
        )
    if lower_f is not None and upper_f is not None and lower_f > upper_f:
        raise WeatherFactsUnavailableError(
            f"{STRIKE_LOWER_F_KEY}: lower bound {lower_f} exceeds upper bound {upper_f}"
        )

    return WeatherBucketFacts(
        settlement_station=settlement_station,
        climate_day=climate_day,
        measure=measure,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def is_weather_market(info: object) -> bool:
    """Return whether ``info`` explicitly identifies a known weather market.

    Only an explicit ``UNKNOWN`` status returns ``False``. Missing or malformed
    status refuses so older instruments cannot silently disappear from a
    strategy pre-filter.
    """
    mapping = _require_mapping(info)
    status = _require_present(mapping, WEATHER_FACTS_STATUS_KEY)
    if status == WEATHER_FACTS_STATUS_UNKNOWN:
        return False
    if status == WEATHER_FACTS_STATUS_KNOWN:
        return True
    raise WeatherFactsUnavailableError(f"{WEATHER_FACTS_STATUS_KEY}: unknown status {status!r}")


def _require_mapping(info: object) -> Mapping[str, Any]:
    if not isinstance(info, Mapping):
        raise WeatherFactsUnavailableError(
            f"{WEATHER_FACTS_STATUS_KEY}: expected Instrument.info Mapping, "
            f"got {type(info).__name__}"
        )
    return info


def _require_present(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise WeatherFactsUnavailableError(f"{key}: missing required weather fact")
    value = mapping[key]
    if value is None:
        raise WeatherFactsUnavailableError(f"{key}: missing required weather fact")
    return value


def _require_text_fact(mapping: Mapping[str, Any], key: str) -> str:
    try:
        return require_text(_require_present(mapping, key), key)
    except (TypeError, ValueError) as exc:
        raise WeatherFactsUnavailableError(f"{key}: {exc}") from exc


def _require_climate_day(mapping: Mapping[str, Any]) -> dt.date:
    value = _require_present(mapping, CLIMATE_DAY_KEY)
    if not isinstance(value, str):
        raise WeatherFactsUnavailableError(
            f"{CLIMATE_DAY_KEY}: expected ISO date string, got {type(value).__name__}"
        )
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise WeatherFactsUnavailableError(
            f"{CLIMATE_DAY_KEY}: expected ISO date string, got {value!r}"
        ) from exc


def _require_measure(mapping: Mapping[str, Any]) -> Measure:
    value = _require_present(mapping, MEASURE_KEY)
    try:
        return Measure(value)
    except ValueError as exc:
        raise WeatherFactsUnavailableError(f"{MEASURE_KEY}: unknown measure {value!r}") from exc


def _require_optional_int_fact(mapping: Mapping[str, Any], key: str) -> int | None:
    if key not in mapping:
        raise WeatherFactsUnavailableError(f"{key}: missing required weather fact")
    value = mapping[key]
    if value is None:
        return None
    try:
        return require_int(value, key)
    except TypeError as exc:
        raise WeatherFactsUnavailableError(f"{key}: {exc}") from exc
