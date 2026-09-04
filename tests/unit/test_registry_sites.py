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
    ClimateDayWindow,
    EnrichmentCoordinates,
    SettlementDeadline,
    SettlementSite,
    SiteNotFoundError,
    SiteRegistry,
    VenueSymbology,
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

# The station's own (DST-following) IANA zone, per sites.toml -- used ONLY as
# a test-side expectation to prove the venue settlement clock is NOT
# site-local. The loader deliberately does not expose this value (see
# `test_iana_tz_is_not_exposed_by_any_accessor`).
_SITE_LOCAL_TZ_FOR_TEST = {
    "MDW": "America/Chicago",
    "LAX": "America/Los_Angeles",
    "SFO": "America/Los_Angeles",
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


def test_venue_city_token_is_read_not_derived_from_city_key(registry: SiteRegistry) -> None:
    symbology = registry.venue_symbology("polymarket_us", "NYC")
    assert isinstance(symbology, VenueSymbology)
    assert symbology.venue == "polymarket_us"
    assert symbology.city == "NYC"
    assert symbology.venue_city_token == "nyc"

    non_derivable = load_registry(FIXTURES_DIR / "nonderivable_valid.toml")
    hypothetical = non_derivable.venue_symbology("polymarket_us", "TST")
    assert hypothetical.venue_city_token == "not-tst"
    assert hypothetical.venue_city_token != hypothetical.city.lower()


def test_site_can_be_resolved_by_venue_city_token(registry: SiteRegistry) -> None:
    assert registry.site_for_venue_city_token("polymarket_us", "nyc") == (
        registry.settlement_site("polymarket_us", "NYC")
    )

    with pytest.raises(SiteNotFoundError, match="venue_city_token"):
        registry.site_for_venue_city_token("polymarket_us", "nope")

    with pytest.raises(SiteNotFoundError, match="venue_city_token"):
        registry.site_for_venue_city_token("kalshi", "nyc")


def test_settlement_accessor_requires_venue_and_city(registry: SiteRegistry) -> None:
    site = registry.settlement_site("polymarket_us", "NYC")
    assert isinstance(site, SettlementSite)

    with pytest.raises(SiteNotFoundError):
        registry.settlement_site("kalshi", "NYC")

    with pytest.raises(SiteNotFoundError):
        registry.settlement_site("polymarket_us", "NOPE")

    with pytest.raises(TypeError):
        registry.settlement_site("NYC")  # type: ignore[call-arg]


def test_climate_day_window_and_settlement_deadline_require_venue_and_city(
    registry: SiteRegistry,
) -> None:
    window = registry.climate_day_window("polymarket_us", "NYC")
    assert isinstance(window, ClimateDayWindow)
    with pytest.raises(SiteNotFoundError):
        registry.climate_day_window("kalshi", "NYC")
    with pytest.raises(SiteNotFoundError):
        registry.climate_day_window("polymarket_us", "NOPE")
    with pytest.raises(TypeError):
        registry.climate_day_window("NYC")  # type: ignore[call-arg]

    deadline = registry.settlement_deadline("polymarket_us", "NYC")
    assert isinstance(deadline, SettlementDeadline)
    with pytest.raises(SiteNotFoundError):
        registry.settlement_deadline("kalshi", "NYC")
    with pytest.raises(SiteNotFoundError):
        registry.settlement_deadline("polymarket_us", "NOPE")
    with pytest.raises(TypeError):
        registry.settlement_deadline("NYC")  # type: ignore[call-arg]


@pytest.mark.parametrize("city", ["MDW", "LAX", "SFO"])
def test_settlement_clock_is_venue_not_site_local(registry: SiteRegistry, city: str) -> None:
    deadline = registry.settlement_deadline("polymarket_us", city)
    assert deadline.settlement_timezone == "America/New_York"
    assert deadline.settlement_time_local == "08:00"
    # For these three sites the venue clock and the station's own zone
    # differ -- 08:00 ET is emphatically not 08:00 at the station.
    assert deadline.settlement_timezone != _SITE_LOCAL_TZ_FOR_TEST[city]


def test_settlement_clock_matches_venue_for_all_sites(registry: SiteRegistry) -> None:
    for venue, city in registry.pairs():
        deadline = registry.settlement_deadline(venue, city)
        assert deadline.settlement_timezone == "America/New_York"
        assert deadline.settlement_delay_timezone == "America/New_York"


def test_conditional_delay_time_is_exposed(registry: SiteRegistry) -> None:
    deadline = registry.settlement_deadline("polymarket_us", "NYC")
    assert deadline.settlement_delay_time_local == "11:00"
    assert deadline.settlement_delay_timezone == "America/New_York"
    assert deadline.settlement_delay_time_local != deadline.settlement_time_local


def test_climate_day_offset_is_fixed_standard_time_for_all_sites(registry: SiteRegistry) -> None:
    expected = {
        "NYC": -5.0,
        "SFO": -8.0,
        "MIA": -5.0,
        "MDW": -6.0,
        "LAX": -8.0,
    }
    for city, offset in expected.items():
        window = registry.climate_day_window("polymarket_us", city)
        assert window.std_utc_offset_hours == pytest.approx(offset)


def test_climate_day_offset_and_venue_clock_are_structurally_separate(
    registry: SiteRegistry,
) -> None:
    """The two clocks must be unreachable through each other's accessor.

    `ClimateDayWindow` (fixed standard-time offset, never DST-aware) and
    `SettlementDeadline` (DST-following venue wall-clock deadline) are
    different types returned by different accessors -- a caller cannot reach
    for the wrong one by autocomplete. Mirrors
    `test_open_meteo_coordinates_not_reachable_through_settlement_accessor`.
    """
    window = registry.climate_day_window("polymarket_us", "NYC")
    assert not hasattr(window, "settlement_timezone")
    assert not hasattr(window, "settlement_time_local")
    assert not hasattr(window, "settlement_delay_time_local")
    assert not hasattr(window, "settlement_delay_timezone")
    assert not hasattr(window, "no_data_fallback_days")

    deadline = registry.settlement_deadline("polymarket_us", "NYC")
    assert not hasattr(deadline, "std_utc_offset_hours")

    site = registry.settlement_site("polymarket_us", "NYC")
    assert not hasattr(site, "std_utc_offset_hours")
    assert not hasattr(site, "settlement_timezone")
    assert not hasattr(site, "settlement_time_local")


def test_iana_tz_is_not_exposed_by_any_accessor(registry: SiteRegistry) -> None:
    """iana_tz is real, verified data in sites.toml but has no consumer.

    Its only plausible future use is confusing the DST-following venue
    settlement clock with the non-DST-aware climate-day offset, so the
    loader validates its presence (see test_registry_validation.py) but
    never surfaces it through any returned type.
    """
    site = registry.settlement_site("polymarket_us", "NYC")
    window = registry.climate_day_window("polymarket_us", "NYC")
    deadline = registry.settlement_deadline("polymarket_us", "NYC")
    coords = registry.enrichment_coordinates("polymarket_us", "NYC")

    assert not hasattr(site, "iana_tz")
    assert not hasattr(window, "iana_tz")
    assert not hasattr(deadline, "iana_tz")
    assert not hasattr(coords, "iana_tz")


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


def test_iem_asos_id_is_read_for_every_site(registry: SiteRegistry) -> None:
    # BL-24 amendment A5: values from settlement_alignment_study.py:65-71.
    expected = {
        "NYC": "KNYC",
        "SFO": "KSFO",
        "MIA": "KMIA",
        "MDW": "KMDW",
        "LAX": "KLAX",
    }
    for city, iem_asos_id in expected.items():
        site = registry.settlement_site("polymarket_us", city)
        assert site.iem_asos_id == iem_asos_id


def test_known_iem_asos_ids_is_the_closed_set_across_every_site(
    registry: SiteRegistry,
) -> None:
    assert registry.known_iem_asos_ids() == frozenset(
        {"KNYC", "KSFO", "KMIA", "KMDW", "KLAX"},
    )


def test_registry_version_is_exposed(registry: SiteRegistry) -> None:
    assert registry.registry_version == "1.0.0"


def test_default_registry_loads_and_is_cached() -> None:
    first = default_registry()
    second = default_registry()
    assert first is second
    assert first.registry_version == "1.0.0"
