"""Evidence-pinned tests for venue-series -> city-universe derivation (G-19 B3).

Every assertion here is anchored to a **captured venue payload** under
``docs/evidence/venue/polymarket_us/raw/``. Nothing in this suite asserts a
city binding that a human recited; if the capture does not establish it, the
test asserts that the module refuses rather than guesses.

The load-bearing test is
:func:`test_the_derived_site_pairs_equal_the_settlement_registry_pairs`: it
turns "the registry happens to hold the venue's five cities" from an
assumption into a checked equality against the venue's own series list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.errors import PolymarketUSError
from breezy.adapters.polymarket_us.series import (
    SeriesDerivationError,
    SeriesUniverse,
    derive_series_universe,
    derive_site_pairs,
    index_series_stations,
    parse_weather_series,
)
from breezy.registry.sites import default_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

#: The venue's own series list, captured 2026-08 from the series endpoint.
SERIES_CAPTURE = RAW / "series_limit100.json"
#: Event captures that carry ``seriesSlug`` AND nested markets.
EVENT_CAPTURES = (
    RAW / "search_weather.json",
    RAW / "events_seriesId_35_active.json",
)


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)
    return payload


@pytest.fixture(scope="module")
def series_payload() -> dict[str, Any]:
    return _load(SERIES_CAPTURE)


@pytest.fixture(scope="module")
def event_payloads() -> tuple[dict[str, Any], ...]:
    return tuple(_load(path) for path in EVENT_CAPTURES)


@pytest.fixture(scope="module")
def universe(
    series_payload: dict[str, Any],
    event_payloads: tuple[dict[str, Any], ...],
) -> SeriesUniverse:
    return derive_series_universe(series_payload, *event_payloads)


# ---------------------------------------------------------------------------
# Series-list parsing
# ---------------------------------------------------------------------------


def test_the_capture_yields_exactly_the_ten_weather_daily_series(
    series_payload: dict[str, Any],
) -> None:
    """Ten: five cities x {high, low}. Evidence: ``series_limit100.json``."""
    parsed = parse_weather_series(series_payload)

    assert len(parsed) == 10
    assert {entry.series_id for entry in parsed} == {str(n) for n in range(35, 45)}


def test_the_umbrella_weather_series_is_not_a_daily_series(
    series_payload: dict[str, Any],
) -> None:
    """Series 31 is ``slug="weather"`` -- an umbrella with no city token.

    It must be excluded structurally (it is not ``weather-daily-*``), never
    by a special case that could also swallow a drifted daily slug.
    """
    parsed = parse_weather_series(series_payload)

    assert "31" not in {entry.series_id for entry in parsed}
    assert "weather" not in {entry.slug for entry in parsed}


def test_the_five_city_tokens_come_from_the_capture(
    series_payload: dict[str, Any],
) -> None:
    parsed = parse_weather_series(series_payload)

    assert {entry.city_token for entry in parsed} == {
        "nyc",
        "miami",
        "chicago",
        "los-angeles",
        "san-francisco",
    }


def test_both_measures_are_recognised(series_payload: dict[str, Any]) -> None:
    parsed = parse_weather_series(series_payload)

    assert {entry.measure for entry in parsed} == {"high", "low"}
    assert sum(1 for entry in parsed if entry.measure == "high") == 5
    assert sum(1 for entry in parsed if entry.measure == "low") == 5


def test_a_drifted_weather_daily_slug_raises_rather_than_being_dropped() -> None:
    """Silent dropping is the defect: a new measure must fail loudly."""
    payload = {"series": [{"id": "99", "slug": "weather-daily-mean-nyc", "title": "Mean"}]}

    with pytest.raises(SeriesDerivationError, match="weather-daily-mean-nyc"):
        parse_weather_series(payload)


def test_a_series_entry_missing_a_slug_raises() -> None:
    payload = {"series": [{"id": "99", "title": "No slug"}]}

    with pytest.raises(SeriesDerivationError, match="slug"):
        parse_weather_series(payload)


def test_a_payload_without_a_series_key_raises() -> None:
    with pytest.raises(SeriesDerivationError, match="series"):
        parse_weather_series({"events": []})


def test_a_duplicate_series_slug_raises() -> None:
    payload = {
        "series": [
            {"id": "35", "slug": "weather-daily-high-nyc", "title": "A"},
            {"id": "36", "slug": "weather-daily-high-nyc", "title": "B"},
        ]
    }

    with pytest.raises(SeriesDerivationError, match="weather-daily-high-nyc"):
        parse_weather_series(payload)


def test_the_derivation_error_is_inside_the_adapter_taxonomy() -> None:
    assert issubclass(SeriesDerivationError, PolymarketUSError)
    assert issubclass(SeriesDerivationError, ValueError)


# ---------------------------------------------------------------------------
# The series -> station join
# ---------------------------------------------------------------------------


def test_the_join_recovers_five_stations_from_the_event_captures(
    event_payloads: tuple[dict[str, Any], ...],
) -> None:
    """``seriesSlug`` (event) + ``(ICAO)`` (market description) is the join.

    Both fields are in the captured payloads; neither is recited by a human.
    """
    index = index_series_stations(*event_payloads)

    assert {slug: icao for slug, (icao, _) in index.items()} == {
        "weather-daily-high-nyc": "KNYC",
        "weather-daily-high-miami": "KMIA",
        "weather-daily-high-chicago": "KMDW",
        "weather-daily-high-los-angeles": "KLAX",
        "weather-daily-high-san-francisco": "KSFO",
    }


def test_chicago_resolves_to_midway_not_ohare(
    event_payloads: tuple[dict[str, Any], ...],
) -> None:
    """The single most expensive station mistake in this system."""
    index = index_series_stations(*event_payloads)

    icao, market_slug = index["weather-daily-high-chicago"]
    assert icao == "KMDW"
    assert icao != "KORD"
    assert market_slug.startswith("tc-temp-mdwhigh-")


def test_the_join_records_the_market_slug_that_established_it(
    event_payloads: tuple[dict[str, Any], ...],
) -> None:
    index = index_series_stations(*event_payloads)

    for _icao, market_slug in index.values():
        assert market_slug


def test_two_different_stations_under_one_series_raises() -> None:
    """An ambiguous join must never be resolved by picking one."""
    payload = {
        "events": [
            {
                "seriesSlug": "weather-daily-high-chicago",
                "markets": [
                    {"slug": "a", "description": "recorded at Chicago Midway (KMDW) ..."},
                    {"slug": "b", "description": "recorded at Chicago O'Hare (KORD) ..."},
                ],
            }
        ]
    }

    with pytest.raises(SeriesDerivationError, match="KMDW|KORD"):
        index_series_stations(payload)


def test_an_event_without_a_series_slug_raises() -> None:
    payload = {"events": [{"slug": "temp-nychigh-2026-08-25", "markets": []}]}

    with pytest.raises(SeriesDerivationError, match="seriesSlug"):
        index_series_stations(payload)


def test_an_events_payload_without_an_events_key_raises() -> None:
    with pytest.raises(SeriesDerivationError, match="events"):
        index_series_stations({"series": []})


def test_a_description_without_a_station_contributes_no_join() -> None:
    """April-2026 descriptions carry no ``(ICAO)``; that is absence, not drift.

    Evidence: ``markets_categories_climate.json`` -- every description reads
    "recorded in New York City", with no parenthesised station. Those events
    must simply fail to establish a join rather than raise.
    """
    payload = {
        "events": [
            {
                "seriesSlug": "weather-daily-high-nyc",
                "markets": [
                    {
                        "slug": "tc-temp-nychigh-2026-04-22-lt56f",
                        "description": (
                            "Will the highest temperature recorded in New York City "
                            "for 2026-04-22 ... be less than or equal to 55F?"
                        ),
                    }
                ],
            }
        ]
    }

    assert index_series_stations(payload) == {}


# ---------------------------------------------------------------------------
# The universe: what is resolved, and the NAMED GAP
# ---------------------------------------------------------------------------


def test_the_five_high_series_resolve_to_stations(universe: SeriesUniverse) -> None:
    assert {(entry.series.slug, entry.icao) for entry in universe.resolved} == {
        ("weather-daily-high-nyc", "KNYC"),
        ("weather-daily-high-miami", "KMIA"),
        ("weather-daily-high-chicago", "KMDW"),
        ("weather-daily-high-los-angeles", "KLAX"),
        ("weather-daily-high-san-francisco", "KSFO"),
    }


def test_the_five_low_series_are_reported_unresolved_not_assumed(
    universe: SeriesUniverse,
) -> None:
    """THE NAMED GAP, asserted so it cannot be quietly closed by a guess.

    No captured payload joins any ``weather-daily-low-*`` series to a market:
    ``events_seriesId_36_active.json`` is ``{"events": []}`` and no other
    capture carries a low seriesSlug. The module must therefore report these
    five as UNRESOLVED. If a later capture supplies the join, this test fails
    RED -- which is the correct signal to update it with the new evidence.
    """
    assert {entry.slug for entry in universe.unresolved} == {
        "weather-daily-low-nyc",
        "weather-daily-low-miami",
        "weather-daily-low-chicago",
        "weather-daily-low-los-angeles",
        "weather-daily-low-san-francisco",
    }
    assert all(entry.measure == "low" for entry in universe.unresolved)


def test_the_module_docstring_names_the_unresolved_join() -> None:
    """The gap must be visible to a reader of the module, not only of a test."""
    from breezy.adapters.polymarket_us import series as series_module

    doc = series_module.__doc__ or ""
    assert "weather-daily-low" in doc
    assert "UNRESOLVED" in doc


def test_no_city_is_dropped_by_the_unresolved_low_series(
    universe: SeriesUniverse,
) -> None:
    """Every unresolved token is independently established by a resolved series.

    This is a coverage check, NOT a claim that the low series settles on the
    same station -- that binding remains unobserved.
    """
    resolved_tokens = {entry.series.city_token for entry in universe.resolved}
    assert {entry.city_token for entry in universe.unresolved} <= resolved_tokens


# ---------------------------------------------------------------------------
# Registry binding -- the loud refusal
# ---------------------------------------------------------------------------


def test_the_derived_site_pairs_equal_the_settlement_registry_pairs(
    universe: SeriesUniverse,
) -> None:
    """The equality that lets an unset ``BREEZY_SITES`` default to the registry.

    Derived purely from the venue's own series/event captures, then bound to
    the registry by ICAO. If the venue adds a sixth city, this fails RED.
    """
    registry = default_registry()
    pairs = derive_site_pairs(universe, registry)

    assert set(pairs) == set(registry.pairs())
    assert pairs == tuple(sorted(pairs))


def test_a_station_with_no_registry_entry_is_refused_loudly() -> None:
    """A venue city we hold no settlement truth for must NEVER be skipped."""
    series_payload = {
        "series": [{"id": "50", "slug": "weather-daily-high-boston", "title": "Boston"}]
    }
    event_payload = {
        "events": [
            {
                "seriesSlug": "weather-daily-high-boston",
                "markets": [
                    {"slug": "tc-temp-boshigh-x", "description": "recorded at Logan (KBOS) ..."}
                ],
            }
        ]
    }
    derived = derive_series_universe(series_payload, event_payload)

    with pytest.raises(SeriesDerivationError, match="KBOS"):
        derive_site_pairs(derived, default_registry())


def test_an_unresolved_series_for_an_otherwise_unknown_city_is_refused_loudly() -> None:
    """A city that appears ONLY in an unresolved series must not vanish."""
    series_payload = {
        "series": [
            {"id": "35", "slug": "weather-daily-high-nyc", "title": "NYC high"},
            {"id": "60", "slug": "weather-daily-low-boston", "title": "Boston low"},
        ]
    }
    event_payload = {
        "events": [
            {
                "seriesSlug": "weather-daily-high-nyc",
                "markets": [
                    {"slug": "tc-temp-nychigh-x", "description": "recorded at Central Park (KNYC)"}
                ],
            }
        ]
    }
    derived = derive_series_universe(series_payload, event_payload)

    with pytest.raises(SeriesDerivationError, match="boston"):
        derive_site_pairs(derived, default_registry())


def test_a_universe_with_no_resolved_series_is_refused_loudly() -> None:
    """Zero resolved series means the captures established nothing at all."""
    derived = derive_series_universe(
        {"series": [{"id": "36", "slug": "weather-daily-low-nyc", "title": "NYC low"}]},
        {"events": []},
    )

    with pytest.raises(SeriesDerivationError, match="no station"):
        derive_site_pairs(derived, default_registry())


def test_site_pairs_are_keyed_by_venue_and_city(universe: SeriesUniverse) -> None:
    pairs = derive_site_pairs(universe, default_registry())

    assert all(venue == "polymarket_us" for venue, _ in pairs)
    assert {city for _, city in pairs} == {"NYC", "SFO", "MIA", "MDW", "LAX"}
