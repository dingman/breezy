"""Typed, validated loader for the settlement-site registry.

`sites.toml` (in this package) is the single source of settlement truth for
Breezy. This module is a read-only, eagerly-validated view over that file. It
imports no `nautilus_trader` and derives nothing: every settlement-critical
identifier is read from the file verbatim.

Two structural guarantees this module exists to enforce:

- `(venue, city)` keying everywhere -- there is no city-only accessor, so a
  second venue (Kalshi) needs no restructuring later.
- Enrichment isolation -- `SettlementSite` carries no `open_meteo` fields at
  all. Forecast coordinates are reachable only via `enrichment_coordinates`,
  a differently-named accessor returning a differently-typed object. That is
  a property of the API shape, not a convention callers must remember.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from re import Pattern
from typing import Any, Final

DEFAULT_REGISTRY_PATH: Final[Path] = Path(__file__).resolve().parent / "sites.toml"

_REQUIRED_SITE_FIELDS: Final[tuple[str, ...]] = (
    "icao",
    "cli_location",
    "issuing_office",
    "iana_tz",
    "std_utc_offset_hours",
    "body_header_regex",
    "never_substitute",
    "never_substitute_cli_locations",
    "settlement_time_local",
    "settlement_timezone",
    "settlement_delay_time_local",
    "settlement_delay_timezone",
    "no_data_fallback_days",
)

_REQUIRED_OPEN_METEO_FIELDS: Final[tuple[str, ...]] = (
    "settlement_eligible",
    "lat",
    "lon",
    "elevation_m",
)


class RegistryError(Exception):
    """Raised when the settlement-site registry fails to load or validate.

    A registry that loads with a hole in it is worse than one that refuses
    to load, so every structural or content problem raises this eagerly
    during `load_registry`, never lazily on first use of the affected site.
    """


class SiteNotFoundError(RegistryError, KeyError):
    """Raised when an unknown `(venue, city)` pair is requested.

    Looking up an unregistered venue or city must fail loudly with a clear
    message rather than returning `None` or a bare `KeyError`.
    """


@dataclass(frozen=True, slots=True)
class SettlementSite:
    """A single settlement-critical `(venue, city)` binding.

    Every field is a stored value read verbatim from `sites.toml` -- nothing
    here is computed from another field. In particular `cli_location` is
    never derived from `icao`.

    Deliberately excludes any enrichment (`open_meteo`) fields. See
    `EnrichmentCoordinates` and `SiteRegistry.enrichment_coordinates` for
    forecast-only coordinate data, which lives on a separate type reachable
    only through a separately-named accessor.
    """

    venue: str
    city: str
    icao: str
    cli_location: str
    issuing_office: str
    iana_tz: str
    std_utc_offset_hours: float
    body_header_regex: Pattern[str]
    never_substitute: tuple[str, ...]
    never_substitute_cli_locations: tuple[str, ...]
    # VENUE clock, paired with settlement_timezone -- NOT this site's local
    # clock. For MDW, LAX and SFO the settlement instant is deliberately not
    # 08:00 at the station.
    settlement_time_local: str
    settlement_timezone: str
    # Conditional delay clock (applies when the CLI reading disagrees with
    # the 24-hour METAR observation). Also the venue's clock, not site-local.
    settlement_delay_time_local: str
    settlement_delay_timezone: str
    no_data_fallback_days: int


@dataclass(frozen=True, slots=True)
class EnrichmentCoordinates:
    """Forecast-enrichment coordinates for a `(venue, city)` site.

    NEVER a settlement input -- `settlement_eligible` is validated to be
    exactly `False` at load time, and this type is unreachable from
    `SettlementSite` or `SiteRegistry.settlement_site`.
    """

    venue: str
    city: str
    lat: float
    lon: float
    elevation_m: float
    settlement_eligible: bool


def _require_field(table: dict[str, Any], field: str, site_key: str) -> None:
    if field not in table:
        raise RegistryError(f"site '{site_key}': missing required field '{field}'")


def _compile_header_regex(pattern: str, site_key: str) -> Pattern[str]:
    try:
        return re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        raise RegistryError(
            f"site '{site_key}': body_header_regex does not compile: {exc}"
        ) from exc


def _build_settlement_site(venue: str, city: str, table: dict[str, Any]) -> SettlementSite:
    site_key = f"{venue}.{city}"
    for field in _REQUIRED_SITE_FIELDS:
        _require_field(table, field, site_key)

    never_substitute = tuple(str(x) for x in table["never_substitute"])
    if len(never_substitute) == 0:
        raise RegistryError(f"site '{site_key}': never_substitute must not be empty")

    return SettlementSite(
        venue=venue,
        city=city,
        icao=str(table["icao"]),
        cli_location=str(table["cli_location"]),
        issuing_office=str(table["issuing_office"]),
        iana_tz=str(table["iana_tz"]),
        std_utc_offset_hours=float(table["std_utc_offset_hours"]),
        body_header_regex=_compile_header_regex(str(table["body_header_regex"]), site_key),
        never_substitute=never_substitute,
        never_substitute_cli_locations=tuple(
            str(x) for x in table["never_substitute_cli_locations"]
        ),
        settlement_time_local=str(table["settlement_time_local"]),
        settlement_timezone=str(table["settlement_timezone"]),
        settlement_delay_time_local=str(table["settlement_delay_time_local"]),
        settlement_delay_timezone=str(table["settlement_delay_timezone"]),
        no_data_fallback_days=int(table["no_data_fallback_days"]),
    )


def _build_enrichment_coordinates(
    venue: str, city: str, table: dict[str, Any]
) -> EnrichmentCoordinates:
    site_key = f"{venue}.{city}"
    open_meteo_raw = table.get("open_meteo")
    if not isinstance(open_meteo_raw, dict):
        raise RegistryError(f"site '{site_key}': missing required table 'open_meteo'")

    for field in _REQUIRED_OPEN_METEO_FIELDS:
        _require_field(open_meteo_raw, field, f"{site_key}.open_meteo")

    settlement_eligible = open_meteo_raw["settlement_eligible"]
    if settlement_eligible is not False:
        raise RegistryError(
            f"site '{site_key}': open_meteo.settlement_eligible must be exactly false"
        )

    return EnrichmentCoordinates(
        venue=venue,
        city=city,
        lat=float(open_meteo_raw["lat"]),
        lon=float(open_meteo_raw["lon"]),
        elevation_m=float(open_meteo_raw["elevation_m"]),
        settlement_eligible=False,
    )


class SiteRegistry:
    """Typed, validated view over a settlement-site registry TOML file.

    Construct via `load_registry` (or the cached `default_registry`), never
    directly -- the constructor takes fully-validated data so that all
    validation happens in one place, at load time.
    """

    def __init__(
        self,
        registry_version: str,
        settlement_sites: dict[tuple[str, str], SettlementSite],
        enrichment_sites: dict[tuple[str, str], EnrichmentCoordinates],
    ) -> None:
        self._registry_version = registry_version
        self._settlement_sites = settlement_sites
        self._enrichment_sites = enrichment_sites

    @property
    def registry_version(self) -> str:
        """Stamped into every persisted settlement record for auditability."""
        return self._registry_version

    def pairs(self) -> tuple[tuple[str, str], ...]:
        """All `(venue, city)` pairs known to this registry."""
        return tuple(self._settlement_sites.keys())

    def settlement_site(self, venue: str, city: str) -> SettlementSite:
        """Return the settlement-critical binding for `(venue, city)`.

        Raises `SiteNotFoundError` for an unregistered venue or city --
        never returns `None` and never silently substitutes a neighbour.
        """
        try:
            return self._settlement_sites[(venue, city)]
        except KeyError as exc:
            raise SiteNotFoundError(
                f"no settlement site registered for venue={venue!r} city={city!r}"
            ) from exc

    def enrichment_coordinates(self, venue: str, city: str) -> EnrichmentCoordinates:
        """Return forecast-enrichment coordinates for `(venue, city)`.

        Structurally separate from `settlement_site`: this is the only path
        by which coordinate data is reachable at all.
        """
        try:
            return self._enrichment_sites[(venue, city)]
        except KeyError as exc:
            raise SiteNotFoundError(
                f"no enrichment coordinates registered for venue={venue!r} city={city!r}"
            ) from exc


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> SiteRegistry:
    """Load, parse and eagerly validate the site registry TOML at `path`.

    Raises `RegistryError` for any structural or content problem: a missing
    required field, an uncompilable `body_header_regex`, an
    `open_meteo.settlement_eligible` that is not exactly `False`, or a
    `never_substitute` list that is empty. Raises `FileNotFoundError` if
    `path` does not exist.
    """
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    if "registry_version" not in raw:
        raise RegistryError("registry: missing required top-level field 'registry_version'")
    registry_version = str(raw["registry_version"])

    sites_raw = raw.get("sites")
    if not isinstance(sites_raw, dict) or not sites_raw:
        raise RegistryError("registry: missing or empty top-level table 'sites'")

    settlement_sites: dict[tuple[str, str], SettlementSite] = {}
    enrichment_sites: dict[tuple[str, str], EnrichmentCoordinates] = {}

    for venue, cities_raw in sites_raw.items():
        if not isinstance(cities_raw, dict) or not cities_raw:
            raise RegistryError(f"registry: venue '{venue}' has no sites")
        for city, table_raw in cities_raw.items():
            if not isinstance(table_raw, dict):
                raise RegistryError(f"registry: site '{venue}.{city}' is not a table")
            settlement_sites[(venue, city)] = _build_settlement_site(venue, city, table_raw)
            enrichment_sites[(venue, city)] = _build_enrichment_coordinates(
                venue, city, table_raw
            )

    return SiteRegistry(
        registry_version=registry_version,
        settlement_sites=settlement_sites,
        enrichment_sites=enrichment_sites,
    )


@lru_cache(maxsize=1)
def default_registry() -> SiteRegistry:
    """Load and cache the production registry at the package-default path."""
    return load_registry(DEFAULT_REGISTRY_PATH)
