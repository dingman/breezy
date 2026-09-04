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


def test_known_icaos_is_the_closed_set_across_every_site(registry: SiteRegistry) -> None:
    """BL-24 Seam B section 2: the observation transport validates ICAOs against this set."""
    assert registry.known_icaos() == frozenset({"KNYC", "KSFO", "KMIA", "KMDW", "KLAX"})


def test_registry_version_is_exposed(registry: SiteRegistry) -> None:
    assert registry.registry_version == "1.0.0"


def test_default_registry_loads_and_is_cached() -> None:
    first = default_registry()
    second = default_registry()
    assert first is second
    assert first.registry_version == "1.0.0"


# -----------------------------------------------------------------------------
# Kalshi sibling-venue entries (KALSHI_CRH_EXPANSION_PLAN_2026-09-04 S4)
# -----------------------------------------------------------------------------

_PM_GOLDEN_SETTLEMENT_SITES = {
    "NYC": SettlementSite(
        venue="polymarket_us",
        city="NYC",
        icao="KNYC",
        iem_asos_id="KNYC",
        cli_location="NYC",
        issuing_office="KOKX",
        body_header_regex=re.compile(
            r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
        ),
        never_substitute=("KJFK", "KLGA", "KEWR"),
        never_substitute_cli_locations=("JFK", "LGA", "EWR"),
    ),
    "SFO": SettlementSite(
        venue="polymarket_us",
        city="SFO",
        icao="KSFO",
        iem_asos_id="KSFO",
        cli_location="SFO",
        issuing_office="KMTR",
        body_header_regex=re.compile(
            r"^\.\.\.THE\s+SAN\s+FRANCISCO\s+AIRPORT\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
        ),
        never_substitute=("KOAK", "KSJC"),
        never_substitute_cli_locations=("OAK", "SJC"),
    ),
    "MIA": SettlementSite(
        venue="polymarket_us",
        city="MIA",
        icao="KMIA",
        iem_asos_id="KMIA",
        cli_location="MIA",
        issuing_office="KMFL",
        body_header_regex=re.compile(
            r"^\.\.\.THE\s+MIAMI\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
        ),
        never_substitute=("KFLL", "KAPF", "KMTH"),
        never_substitute_cli_locations=("FLL", "APF", "MTH"),
    ),
    "MDW": SettlementSite(
        venue="polymarket_us",
        city="MDW",
        icao="KMDW",
        iem_asos_id="KMDW",
        cli_location="MDW",
        issuing_office="KLOT",
        body_header_regex=re.compile(
            r"^\.\.\.THE\s+CHICAGO\s*-\s*MIDWAY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
        ),
        never_substitute=("KORD",),
        never_substitute_cli_locations=("ORD",),
    ),
    "LAX": SettlementSite(
        venue="polymarket_us",
        city="LAX",
        icao="KLAX",
        iem_asos_id="KLAX",
        cli_location="LAX",
        issuing_office="KLOX",
        body_header_regex=re.compile(
            r"^\.\.\.THE\s+LOS\s+ANGELES\s+INTL\s+AIRPORT\s+CA\s+CLIMATE\s+SUMMARY\s+FOR\b",
            re.MULTILINE,
        ),
        never_substitute=("KBUR", "KLGB", "KSNA"),
        never_substitute_cli_locations=("BUR", "LGB", "SNA"),
    ),
}

_PM_GOLDEN_SETTLEMENT_DEADLINES = {
    city: SettlementDeadline(
        venue="polymarket_us",
        city=city,
        settlement_time_local="08:00",
        settlement_timezone="America/New_York",
        settlement_delay_time_local="11:00",
        settlement_delay_timezone="America/New_York",
        no_data_fallback_days=7,
    )
    for city in ("NYC", "SFO", "MIA", "MDW", "LAX")
}

_PM_GOLDEN_CLIMATE_DAY_WINDOWS = {
    "NYC": ClimateDayWindow(venue="polymarket_us", city="NYC", std_utc_offset_hours=-5.0),
    "SFO": ClimateDayWindow(venue="polymarket_us", city="SFO", std_utc_offset_hours=-8.0),
    "MIA": ClimateDayWindow(venue="polymarket_us", city="MIA", std_utc_offset_hours=-5.0),
    "MDW": ClimateDayWindow(venue="polymarket_us", city="MDW", std_utc_offset_hours=-6.0),
    "LAX": ClimateDayWindow(venue="polymarket_us", city="LAX", std_utc_offset_hours=-8.0),
}

_PM_GOLDEN_ENRICHMENT = {
    "NYC": EnrichmentCoordinates(
        venue="polymarket_us", city="NYC", lat=40.78333, lon=-73.96667,
        elevation_m=46.9392, settlement_eligible=False,
    ),
    "SFO": EnrichmentCoordinates(
        venue="polymarket_us", city="SFO", lat=37.61961, lon=-122.36558,
        elevation_m=3.048, settlement_eligible=False,
    ),
    "MIA": EnrichmentCoordinates(
        venue="polymarket_us", city="MIA", lat=25.79056, lon=-80.31639,
        elevation_m=3.048, settlement_eligible=False,
    ),
    "MDW": EnrichmentCoordinates(
        venue="polymarket_us", city="MDW", lat=41.78417, lon=-87.75528,
        elevation_m=188.0616, settlement_eligible=False,
    ),
    "LAX": EnrichmentCoordinates(
        venue="polymarket_us", city="LAX", lat=33.93806, lon=-118.38889,
        elevation_m=38.1, settlement_eligible=False,
    ),
}

_PM_GOLDEN_SYMBOLOGY = {
    city: VenueSymbology(venue="polymarket_us", city=city, venue_city_token=token)
    for city, token in {"NYC": "nyc", "SFO": "sfo", "MIA": "mia", "MDW": "mdw", "LAX": "lax"}.items()
}

_KALSHI_CITIES = ("LAX", "MDW", "MIA", "SFO")

_KALSHI_EXPECTED_DEADLINE = {
    "settlement_time_local": "08:00",
    "settlement_timezone": "America/New_York",
    # NWS-product-derived, shared with polymarket_us -- drives only the CLI
    # review-extension window, not a venue-specific instant.
    "settlement_delay_time_local": "11:00",
    "settlement_delay_timezone": "America/New_York",
    "no_data_fallback_days": 7,
}

# Same-office collisions requiring the sibling-decoy rejection, mirrored from
# the PM entries for the same physical stations (plan §Registry hazards).
_KALSHI_SIBLING_DECOY_HEADER = {
    "MDW": "...THE CHICAGO-OHARE CLIMATE SUMMARY FOR SEPTEMBER 3 2026...",
    "LAX": "...THE HOLLYWOOD/BURBANK  AIRPORT CA CLIMATE SUMMARY FOR SEPTEMBER 3 2026...",
    "MIA": "...THE FORT LAUDERDALE CLIMATE SUMMARY FOR SEPTEMBER 3 2026...",
}


def test_pm_settlement_sites_are_byte_identical_after_kalshi_addition(
    registry: SiteRegistry,
) -> None:
    """Golden pin: adding [sites.kalshi.*] must not alter a single PM value."""
    for city, expected in _PM_GOLDEN_SETTLEMENT_SITES.items():
        actual = registry.settlement_site("polymarket_us", city)
        assert actual.venue == expected.venue
        assert actual.city == expected.city
        assert actual.icao == expected.icao
        assert actual.iem_asos_id == expected.iem_asos_id
        assert actual.cli_location == expected.cli_location
        assert actual.issuing_office == expected.issuing_office
        assert actual.body_header_regex.pattern == expected.body_header_regex.pattern
        assert actual.never_substitute == expected.never_substitute
        assert (
            actual.never_substitute_cli_locations == expected.never_substitute_cli_locations
        )

    for city, expected_deadline in _PM_GOLDEN_SETTLEMENT_DEADLINES.items():
        assert registry.settlement_deadline("polymarket_us", city) == expected_deadline

    for city, expected_window in _PM_GOLDEN_CLIMATE_DAY_WINDOWS.items():
        assert registry.climate_day_window("polymarket_us", city) == expected_window

    for city, expected_coords in _PM_GOLDEN_ENRICHMENT.items():
        assert registry.enrichment_coordinates("polymarket_us", city) == expected_coords

    for city, expected_symbology in _PM_GOLDEN_SYMBOLOGY.items():
        assert registry.venue_symbology("polymarket_us", city) == expected_symbology


@pytest.mark.parametrize("city", _KALSHI_CITIES)
def test_kalshi_sites_resolve_with_same_station_identity_as_polymarket_us(
    registry: SiteRegistry, city: str
) -> None:
    kalshi_site = registry.settlement_site("kalshi", city)
    pm_site = registry.settlement_site("polymarket_us", city)
    assert kalshi_site.icao == pm_site.icao
    assert kalshi_site.iem_asos_id == pm_site.iem_asos_id
    assert kalshi_site.cli_location == pm_site.cli_location
    assert kalshi_site.issuing_office == pm_site.issuing_office
    assert kalshi_site.body_header_regex.pattern == pm_site.body_header_regex.pattern
    assert kalshi_site.never_substitute == pm_site.never_substitute
    assert kalshi_site.never_substitute_cli_locations == pm_site.never_substitute_cli_locations


@pytest.mark.parametrize("city", _KALSHI_CITIES)
def test_kalshi_settlement_deadline_matches_stated_venue_values(
    registry: SiteRegistry, city: str
) -> None:
    deadline = registry.settlement_deadline("kalshi", city)
    assert deadline.settlement_time_local == _KALSHI_EXPECTED_DEADLINE["settlement_time_local"]
    assert deadline.settlement_timezone == _KALSHI_EXPECTED_DEADLINE["settlement_timezone"]
    assert (
        deadline.settlement_delay_time_local
        == _KALSHI_EXPECTED_DEADLINE["settlement_delay_time_local"]
    )
    assert (
        deadline.settlement_delay_timezone
        == _KALSHI_EXPECTED_DEADLINE["settlement_delay_timezone"]
    )
    assert deadline.no_data_fallback_days == _KALSHI_EXPECTED_DEADLINE["no_data_fallback_days"]


@pytest.mark.parametrize("city", _KALSHI_CITIES)
def test_kalshi_climate_day_window_matches_polymarket_us(
    registry: SiteRegistry, city: str
) -> None:
    kalshi_window = registry.climate_day_window("kalshi", city)
    pm_window = registry.climate_day_window("polymarket_us", city)
    assert kalshi_window.std_utc_offset_hours == pytest.approx(pm_window.std_utc_offset_hours)


def test_kalshi_venue_city_selector_syntax_validates(registry: SiteRegistry) -> None:
    """`venue:city` selector syntax (BREEZY_SITES) resolves for kalshi:LAX."""
    assert ("kalshi", "LAX") in registry.pairs()
    site = registry.settlement_site("kalshi", "LAX")
    assert site.venue == "kalshi"
    assert site.city == "LAX"


@pytest.mark.parametrize("city", sorted(_KALSHI_SIBLING_DECOY_HEADER))
def test_kalshi_body_header_regex_rejects_sibling_decoy(
    registry: SiteRegistry, city: str
) -> None:
    site = registry.settlement_site("kalshi", city)
    decoy = _KALSHI_SIBLING_DECOY_HEADER[city]
    assert site.body_header_regex.search(decoy) is None


def test_kalshi_never_substitute_is_populated_for_every_city(registry: SiteRegistry) -> None:
    for city in _KALSHI_CITIES:
        site = registry.settlement_site("kalshi", city)
        assert len(site.never_substitute) > 0
