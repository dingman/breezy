"""Typed, validated loader for the settlement-site registry.

`sites.toml` (in this package) is the single source of settlement truth for
Breezy. This module is a read-only, eagerly-validated view over that file. It
imports no `nautilus_trader` and derives nothing: every settlement-critical
identifier is read from the file verbatim.

Structural guarantees this module exists to enforce:

- `(venue, city)` keying everywhere -- there is no city-only accessor, so a
  second venue (Kalshi) needs no restructuring later.
- Enrichment isolation -- `SettlementSite` carries no `open_meteo` fields at
  all. Forecast coordinates are reachable only via `enrichment_coordinates`,
  a differently-named accessor returning a differently-typed object.
- Two-clock isolation -- there are two genuinely different clocks in this
  system and they must never be confused:
    1. `ClimateDayWindow.std_utc_offset_hours` -- the FIXED standard-time
       offset that defines the climate day's midnight-to-midnight window,
       year-round, never DST-aware.
    2. `SettlementDeadline` -- the VENUE's settlement deadline, a
       DST-following civil wall-clock time (`settlement_timezone`,
       `America/New_York` for every site regardless of station location),
       plus its conditional review delay.
  These are returned by two distinct accessors as two distinct types so a
  caller cannot reach for the wrong one by autocomplete. `iana_tz` -- the
  one field whose only plausible use is confusing the two -- is validated
  as present (it is real, verified provenance) but is not surfaced by any
  accessor; see the note on `_build_climate_day_window`.
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

_REQUIRED_IDENTIFIER_FIELDS: Final[tuple[str, ...]] = (
    "icao",
    "iem_asos_id",
    "cli_location",
    "issuing_office",
    "body_header_regex",
    "never_substitute",
    "never_substitute_cli_locations",
)

_REQUIRED_SYMBOLOGY_FIELDS: Final[tuple[str, ...]] = ("venue_city_token",)

# `iana_tz` is required and validated (real, verified data) but is NEVER
# stored on any returned type -- see the module docstring and
# `_build_climate_day_window`.
_REQUIRED_UNSURFACED_FIELDS: Final[tuple[str, ...]] = ("iana_tz",)

_REQUIRED_CLIMATE_DAY_FIELDS: Final[tuple[str, ...]] = ("std_utc_offset_hours",)

_REQUIRED_SETTLEMENT_DEADLINE_FIELDS: Final[tuple[str, ...]] = (
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
    """Settlement-critical identity for a `(venue, city)` binding.

    Every field is a stored value read verbatim from `sites.toml` -- nothing
    here is computed from another field. In particular `cli_location` is
    never derived from `icao`.

    Deliberately excludes enrichment (`open_meteo`) fields -- see
    `EnrichmentCoordinates` -- and both clock concerns -- see
    `ClimateDayWindow` and `SettlementDeadline` -- each reachable only
    through its own separately-named accessor.
    """

    venue: str
    city: str
    icao: str
    iem_asos_id: str
    cli_location: str
    issuing_office: str
    body_header_regex: Pattern[str]
    never_substitute: tuple[str, ...]
    never_substitute_cli_locations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VenueSymbology:
    """Venue-facing slug vocabulary for a `(venue, city)` binding.

    A venue city token is not settlement-critical identity, so it is not stored
    on `SettlementSite`. It is still an explicit registry value, never derived
    from the city key.
    """

    venue: str
    city: str
    venue_city_token: str


@dataclass(frozen=True, slots=True)
class ClimateDayWindow:
    """The climate day's fixed standard-time UTC offset for `(venue, city)`.

    `std_utc_offset_hours` is NEVER DST-aware: the climate day runs
    local-standard midnight to midnight all year regardless of whether the
    date falls under daylight saving. Structurally distinct from
    `SettlementDeadline` -- this type carries no timezone-ish string field
    at all, so there is nothing here a caller could mistake for the
    DST-following venue clock.
    """

    venue: str
    city: str
    std_utc_offset_hours: float


@dataclass(frozen=True, slots=True)
class SettlementDeadline:
    """The VENUE's settlement deadline clock for `(venue, city)`.

    `settlement_time_local` / `settlement_timezone` are the venue's clock
    (08:00 America/New_York for every site today), NOT the station's own
    local clock -- for MDW, LAX and SFO the settlement instant is
    deliberately not 08:00 at the station. `settlement_timezone` DOES
    observe DST, unlike `ClimateDayWindow.std_utc_offset_hours`, and that is
    correct: it is a civil wall-clock deadline, not the climate-day window.

    `settlement_delay_time_local` / `settlement_delay_timezone` is the
    conditional review delay (applies when the CLI reading disagrees with
    the 24-hour METAR observation) -- also the venue's clock, not
    site-local.
    """

    venue: str
    city: str
    settlement_time_local: str
    settlement_timezone: str
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
    for field in _REQUIRED_IDENTIFIER_FIELDS:
        _require_field(table, field, site_key)

    never_substitute = tuple(str(x) for x in table["never_substitute"])
    if len(never_substitute) == 0:
        raise RegistryError(f"site '{site_key}': never_substitute must not be empty")

    return SettlementSite(
        venue=venue,
        city=city,
        icao=str(table["icao"]),
        iem_asos_id=str(table["iem_asos_id"]),
        cli_location=str(table["cli_location"]),
        issuing_office=str(table["issuing_office"]),
        body_header_regex=_compile_header_regex(str(table["body_header_regex"]), site_key),
        never_substitute=never_substitute,
        never_substitute_cli_locations=tuple(
            str(x) for x in table["never_substitute_cli_locations"]
        ),
    )


def _build_venue_symbology(venue: str, city: str, table: dict[str, Any]) -> VenueSymbology:
    site_key = f"{venue}.{city}"
    for field in _REQUIRED_SYMBOLOGY_FIELDS:
        _require_field(table, field, site_key)

    venue_city_token = str(table["venue_city_token"])
    if not venue_city_token.strip():
        raise RegistryError(f"site '{site_key}': venue_city_token must be non-empty")

    return VenueSymbology(
        venue=venue,
        city=city,
        venue_city_token=venue_city_token,
    )


def _build_climate_day_window(venue: str, city: str, table: dict[str, Any]) -> ClimateDayWindow:
    site_key = f"{venue}.{city}"
    for field in _REQUIRED_CLIMATE_DAY_FIELDS:
        _require_field(table, field, site_key)

    # `iana_tz` is validated as present -- it is real, verified provenance
    # and must not silently disappear from the registry's contract -- but
    # deliberately discarded here rather than stored on `ClimateDayWindow`.
    # Its only plausible future use is being reached for as if it were the
    # DST-aware venue settlement clock (it is not: see `SettlementDeadline`)
    # or as a shortcut past the fixed `std_utc_offset_hours` (it would be
    # wrong for that too, since it follows DST and the climate day does
    # not). Add a dedicated accessor only when a concrete consumer needs
    # display/parsing context, not before.
    for field in _REQUIRED_UNSURFACED_FIELDS:
        _require_field(table, field, site_key)

    return ClimateDayWindow(
        venue=venue,
        city=city,
        std_utc_offset_hours=float(table["std_utc_offset_hours"]),
    )


def _build_settlement_deadline(
    venue: str, city: str, table: dict[str, Any]
) -> SettlementDeadline:
    site_key = f"{venue}.{city}"
    for field in _REQUIRED_SETTLEMENT_DEADLINE_FIELDS:
        _require_field(table, field, site_key)

    return SettlementDeadline(
        venue=venue,
        city=city,
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
        venue_symbologies: dict[tuple[str, str], VenueSymbology],
        sites_by_venue_city_token: dict[tuple[str, str], SettlementSite],
        climate_day_windows: dict[tuple[str, str], ClimateDayWindow],
        settlement_deadlines: dict[tuple[str, str], SettlementDeadline],
        enrichment_sites: dict[tuple[str, str], EnrichmentCoordinates],
    ) -> None:
        self._registry_version = registry_version
        self._settlement_sites = settlement_sites
        self._venue_symbologies = venue_symbologies
        self._sites_by_venue_city_token = sites_by_venue_city_token
        self._climate_day_windows = climate_day_windows
        self._settlement_deadlines = settlement_deadlines
        self._enrichment_sites = enrichment_sites

    @property
    def registry_version(self) -> str:
        """Stamped into every persisted settlement record for auditability."""
        return self._registry_version

    def pairs(self) -> tuple[tuple[str, str], ...]:
        """All `(venue, city)` pairs known to this registry."""
        return tuple(self._settlement_sites.keys())

    def known_iem_asos_ids(self) -> frozenset[str]:
        """The closed set of registered `iem_asos_id` values, across every site.

        Validation against IEM station ids must use this closed set, never a
        shape regex: IEM ids satisfy `_CLI_LOCATION_PATTERN` too, so a
        pattern cannot separate a legitimate id from an unregistered one.
        """
        return frozenset(site.iem_asos_id for site in self._settlement_sites.values())

    def settlement_site(self, venue: str, city: str) -> SettlementSite:
        """Return the settlement identity for `(venue, city)`.

        Raises `SiteNotFoundError` for an unregistered venue or city --
        never returns `None` and never silently substitutes a neighbour.
        """
        try:
            return self._settlement_sites[(venue, city)]
        except KeyError as exc:
            raise SiteNotFoundError(
                f"no settlement site registered for venue={venue!r} city={city!r}"
            ) from exc

    def venue_symbology(self, venue: str, city: str) -> VenueSymbology:
        """Return venue-facing slug vocabulary for `(venue, city)`."""
        try:
            return self._venue_symbologies[(venue, city)]
        except KeyError as exc:
            raise SiteNotFoundError(
                f"no venue symbology registered for venue={venue!r} city={city!r}"
            ) from exc

    def site_for_venue_city_token(self, venue: str, token: str) -> SettlementSite:
        """Return the settlement site whose stored venue city token is `token`."""
        try:
            return self._sites_by_venue_city_token[(venue, token)]
        except KeyError as exc:
            raise SiteNotFoundError(
                f"no settlement site registered for venue={venue!r} "
                f"venue_city_token={token!r}"
            ) from exc

    def climate_day_window(self, venue: str, city: str) -> ClimateDayWindow:
        """Return the climate day's fixed standard-time offset for `(venue, city)`.

        Structurally separate from `settlement_deadline`: never DST-aware,
        never a wall-clock deadline.
        """
        try:
            return self._climate_day_windows[(venue, city)]
        except KeyError as exc:
            raise SiteNotFoundError(
                f"no climate-day window registered for venue={venue!r} city={city!r}"
            ) from exc

    def settlement_deadline(self, venue: str, city: str) -> SettlementDeadline:
        """Return the venue's settlement deadline clock for `(venue, city)`.

        Structurally separate from `climate_day_window`: this is the venue's
        DST-following civil deadline, never the climate-day offset.
        """
        try:
            return self._settlement_deadlines[(venue, city)]
        except KeyError as exc:
            raise SiteNotFoundError(
                f"no settlement deadline registered for venue={venue!r} city={city!r}"
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
    venue_symbologies: dict[tuple[str, str], VenueSymbology] = {}
    sites_by_venue_city_token: dict[tuple[str, str], SettlementSite] = {}
    climate_day_windows: dict[tuple[str, str], ClimateDayWindow] = {}
    settlement_deadlines: dict[tuple[str, str], SettlementDeadline] = {}
    enrichment_sites: dict[tuple[str, str], EnrichmentCoordinates] = {}

    for venue, cities_raw in sites_raw.items():
        if not isinstance(cities_raw, dict) or not cities_raw:
            raise RegistryError(f"registry: venue '{venue}' has no sites")
        for city, table_raw in cities_raw.items():
            if not isinstance(table_raw, dict):
                raise RegistryError(f"registry: site '{venue}.{city}' is not a table")
            site = _build_settlement_site(venue, city, table_raw)
            symbology = _build_venue_symbology(venue, city, table_raw)
            token_key = (venue, symbology.venue_city_token)
            if token_key in sites_by_venue_city_token:
                raise RegistryError(
                    f"registry: duplicate venue_city_token {symbology.venue_city_token!r} "
                    f"for venue {venue!r}"
                )
            settlement_sites[(venue, city)] = site
            venue_symbologies[(venue, city)] = symbology
            sites_by_venue_city_token[token_key] = site
            climate_day_windows[(venue, city)] = _build_climate_day_window(
                venue, city, table_raw
            )
            settlement_deadlines[(venue, city)] = _build_settlement_deadline(
                venue, city, table_raw
            )
            enrichment_sites[(venue, city)] = _build_enrichment_coordinates(
                venue, city, table_raw
            )

    return SiteRegistry(
        registry_version=registry_version,
        settlement_sites=settlement_sites,
        venue_symbologies=venue_symbologies,
        sites_by_venue_city_token=sites_by_venue_city_token,
        climate_day_windows=climate_day_windows,
        settlement_deadlines=settlement_deadlines,
        enrichment_sites=enrichment_sites,
    )


@lru_cache(maxsize=1)
def default_registry() -> SiteRegistry:
    """Load and cache the production registry at the package-default path."""
    return load_registry(DEFAULT_REGISTRY_PATH)
