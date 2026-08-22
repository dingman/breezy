"""Unit tests for the settlement-site registry loader.

Covers `src/breezy/registry/sites.py`, the typed/validated accessor over the
single source of settlement truth at `src/breezy/registry/sites.toml`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from breezy.registry.sites import (
    DEFAULT_REGISTRY_PATH,
    EnrichmentCoordinates,
    SettlementSite,
    SiteNotFoundError,
    SiteRegistry,
    default_registry,
    load_registry,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "registry"

EXPECTED_HEADERS = {
    "NYC": "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...",
    "SFO": "...THE SAN FRANCISCO AIRPORT CLIMATE SUMMARY FOR AUGUST 21 2026...",
    "MIA": "...THE MIAMI CLIMATE SUMMARY FOR AUGUST 21 2026...",
    "MDW": "...THE CHICAGO-MIDWAY CLIMATE SUMMARY FOR AUGUST 21 2026...",
    "LAX": "...THE LOS ANGELES INTL AIRPORT CA CLIMATE SUMMARY FOR AUGUST 21 2026...",
}


@pytest.fixture(scope="module")
def registry() -> SiteRegistry:
    return load_registry(DEFAULT_REGISTRY_PATH)


def test_cli_location_is_read_not_derived_from_icao(registry: SiteRegistry) -> None:
    site = registry.settlement_site("polymarket_us", "NYC")
    assert site.icao == "KNYC"
    assert site.cli_location == "NYC"

    # KNYC -> "NYC" would ALSO be produced by naively stripping the leading
    # "K", so the real file alone can't prove non-derivation. Prove it with a
    # hypothetical registry where stripping the ICAO's leading "K" would NOT
    # match cli_location -- it must still load correctly and read verbatim.
    non_derivable = load_registry(FIXTURES_DIR / "nonderivable_valid.toml")
    hypothetical = non_derivable.settlement_site("polymarket_us", "TST")
    assert hypothetical.icao == "KABC"
    assert hypothetical.cli_location == "ZZZ"
    assert hypothetical.cli_location != hypothetical.icao[1:]


def test_settlement_accessor_requires_venue_and_city(registry: SiteRegistry) -> None:
    site = registry.settlement_site("polymarket_us", "NYC")
    assert isinstance(site, SettlementSite)

    with pytest.raises(SiteNotFoundError):
        registry.settlement_site("kalshi", "NYC")

    with pytest.raises(SiteNotFoundError):
        registry.settlement_site("polymarket_us", "NOPE")

    with pytest.raises(TypeError):
        registry.settlement_site("NYC")  # type: ignore[call-arg]


@pytest.mark.parametrize("city", ["MDW", "LAX", "SFO"])
def test_settlement_clock_is_venue_not_site_local(registry: SiteRegistry, city: str) -> None:
    site = registry.settlement_site("polymarket_us", city)
    assert site.settlement_timezone == "America/New_York"
    assert site.settlement_time_local == "08:00"
    # For these three sites the venue clock and the station's own IANA zone
    # differ -- 08:00 ET is emphatically not 08:00 at the station.
    assert site.iana_tz != site.settlement_timezone


def test_settlement_clock_matches_venue_for_all_sites(registry: SiteRegistry) -> None:
    for venue, city in registry.pairs():
        site = registry.settlement_site(venue, city)
        assert site.settlement_timezone == "America/New_York"
        assert site.settlement_delay_timezone == "America/New_York"


def test_conditional_delay_time_is_exposed(registry: SiteRegistry) -> None:
    site = registry.settlement_site("polymarket_us", "NYC")
    assert site.settlement_delay_time_local == "11:00"
    assert site.settlement_delay_timezone == "America/New_York"
    assert site.settlement_delay_time_local != site.settlement_time_local


def test_open_meteo_coordinates_not_reachable_through_settlement_accessor(
    registry: SiteRegistry,
) -> None:
    site = registry.settlement_site("polymarket_us", "NYC")
    # Structural barrier: SettlementSite carries no enrichment attributes at
    # all, not merely "unset" ones.
    assert not hasattr(site, "open_meteo")
    assert not hasattr(site, "lat")
    assert not hasattr(site, "lon")
    assert not hasattr(site, "elevation_m")
    assert not hasattr(site, "settlement_eligible")

    coords = registry.enrichment_coordinates("polymarket_us", "NYC")
    assert isinstance(coords, EnrichmentCoordinates)
    assert coords.settlement_eligible is False
    assert coords.lat == pytest.approx(40.78333)
    assert coords.lon == pytest.approx(-73.96667)


def test_all_five_body_header_regexes_compile(registry: SiteRegistry) -> None:
    cities = {city for _, city in registry.pairs()}
    assert cities == set(EXPECTED_HEADERS)

    for city, header in EXPECTED_HEADERS.items():
        site = registry.settlement_site("polymarket_us", city)
        assert isinstance(site.body_header_regex, re.Pattern)
        assert site.body_header_regex.search(header) is not None


def test_never_substitute_is_populated_for_every_site(registry: SiteRegistry) -> None:
    for venue, city in registry.pairs():
        site = registry.settlement_site(venue, city)
        assert len(site.never_substitute) > 0


def test_registry_version_is_exposed(registry: SiteRegistry) -> None:
    assert registry.registry_version == "1.0.0"


def test_default_registry_loads_and_is_cached() -> None:
    first = default_registry()
    second = default_registry()
    assert first is second
    assert first.registry_version == "1.0.0"
