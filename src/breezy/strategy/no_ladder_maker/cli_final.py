"""ARM D1: the read-only inputs the harm stop and the settlement collector share.

* the CLI final of a station-day, from the NWS station catalog (read-only; never creates one);
* the registry's fixed standard-time UTC offset of a family station token (the climate day's end).

No network, no clock, no write. ``VENUE`` is the only venue these read.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.persistence.catalog import (
    open_station_catalog,
    read_climate_day_including_corrections,
    station_catalog_path,
)
from breezy.registry.sites import SiteNotFoundError, default_registry

__all__ = [
    "VENUE",
    "CliReading",
    "StdOffset",
    "catalog_cli_reader",
    "registry_std_offset_hours",
]

VENUE: Final[str] = "polymarket_us"

CliReading = Callable[[WeatherBucketFacts], int | None]
#: station token -> the climate day's fixed standard-time UTC offset in hours (None: unknown)
StdOffset = Callable[[str], float | None]


def registry_std_offset_hours(station: str) -> float | None:
    """The registry's fixed standard-time UTC offset of a station token; ``None`` if unknown."""
    registry = default_registry()
    try:
        city = registry.site_for_venue_city_token(VENUE, station).city
        return registry.climate_day_window(VENUE, city).std_utc_offset_hours
    except SiteNotFoundError:
        return None


def catalog_cli_reader(catalog_base: Path) -> CliReading:
    """The CLI final from the station catalog; ``None`` when no FINAL with a value is stored.

    Never creates a catalog: a station without an existing catalog directory reads ``None``. Each
    station's catalog is opened once (the Nautilus catalog has no close; it holds no handle)."""
    registry = default_registry()
    city_of = {
        registry.settlement_site(venue, city).cli_location: city
        for venue, city in registry.pairs()
        if venue == VENUE
    }
    opened: dict[str, Any] = {}

    def read(facts: WeatherBucketFacts) -> int | None:
        city = city_of.get(facts.settlement_station)
        if city is None or not station_catalog_path(catalog_base, VENUE, city).is_dir():
            return None
        if city not in opened:
            opened[city] = open_station_catalog(catalog_base, VENUE, city)
        record = read_climate_day_including_corrections(
            opened[city], station=facts.settlement_station, climate_day=facts.climate_day
        )
        if record is None or not record.is_final:
            return None
        return record.tmax_f if facts.measure is Measure.HIGH else record.tmin_f

    return read
