"""Rung facts from a Polymarket.us instrument id (AUT-2 r7 WP2; a pure move, L-46).

Moved byte-for-byte out of ``scripts/analysis/score_live_trials.py`` (names made public) so the
AUT-2 labelling package can resolve a fill's rung without importing a script. The script re-imports
both functions under their old private names, so its behaviour is unchanged.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from breezy.adapters.polymarket_us.symbology import (
    REGISTRY_VENUE_KEY,
    parse_weather_slug,
    slug_closed_interval,
)
from breezy.domain.instrument_leg import base_symbol_of, symbol_of_instrument_id
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherBucketFacts,
    read_weather_bucket_facts,
)
from breezy.persistence.catalog import open_station_catalog
from breezy.registry.sites import SiteNotFoundError, default_registry

__all__ = ["bucket_facts_from_instrument_id", "read_bucket_facts_by_instrument_id"]


def read_bucket_facts_by_instrument_id(
    catalog_base: Path, *, venue: str, city: str
) -> dict[str, WeatherBucketFacts]:
    """Resolve every persisted instrument definition's rung facts, keyed by id.

    Absence for a given `instrument_id` is the caller's `instrument_unavailable`
    refusal signal (item 7) -- this function returns only what it found.

    Duplicate `instrument_id` (review item 4, mirroring `252918a`'s ingest
    idiom): the FIRST-landed definition stands. A later definition under the
    same id that diverges in content is counted, never silently taken as the
    winner, and the count is logged once as a single warning.
    """
    catalog = open_station_catalog(catalog_base, venue, city)
    facts: dict[str, WeatherBucketFacts] = {}
    divergent = 0
    for instrument in catalog.instruments():
        try:
            resolved = read_weather_bucket_facts(instrument.info)
        except Exception as exc:  # noqa: BLE001 -- a non-weather instrument is skipped, not fatal
            logging.getLogger(__name__).debug(
                "skipping non-weather instrument %s: %s", instrument.id, exc
            )
            continue
        instrument_id = str(instrument.id)
        existing = facts.get(instrument_id)
        if existing is not None:
            if existing != resolved:
                divergent += 1
            continue
        facts[instrument_id] = resolved
    if divergent:
        logging.getLogger(__name__).warning(
            "%d instrument definition(s) share an already-landed instrument_id "
            "but differ in weather-bucket facts; skipped, the first-landed "
            "definition stands",
            divergent,
        )
    return facts


def bucket_facts_from_instrument_id(instrument_id: str) -> WeatherBucketFacts | None:
    """Derive `WeatherBucketFacts` straight from `instrument_id`'s own slug
    grammar, for when no persisted instrument definition exists (measured
    2026-09-16: the per-station NWS catalog holds ZERO instrument
    definitions in this environment -- ING-1 ingest strand).

    Reuses the SAME parser `breezy.adapters.polymarket_us.parsing
    ._weather_info` reads at ingestion time --
    `symbology.parse_weather_slug` for the city/measure/climate-day/bounds,
    then `symbology.slug_closed_interval` for the closed-interval reading --
    never a new regex. `slug_closed_interval`'s three-family mapping is the
    exact rule `docs/evidence/venue/polymarket_us
    /THRESHOLD_SEMANTICS_2026-08-25.md` section 4.2 pins as settlement-grade
    (`gte{A}lt{B}f` -> `[A, B]` inclusive, the same rule
    `settlement_truth_dataset.bucket_facts` already applies standalone with
    no venue payload) -- this driver never has the venue's own
    description/title to cross-check against (`assert_bounds_cross_checked`
    needs a live market payload this scorer does not hold), so it uses that
    corroborated cross-check reading directly rather than re-deriving a new
    one.

    `None` for anything the parser does not recognise (an unobserved bound
    family, a slug outside the weather grammar, or a city with no
    registered settlement site) -- the caller's `instrument_unavailable`
    refusal, unchanged.
    """
    slug = base_symbol_of(symbol_of_instrument_id(instrument_id))
    parsed = parse_weather_slug(slug)
    if parsed is None:
        return None
    interval = slug_closed_interval(parsed.bounds)
    if interval is None:
        return None
    try:
        site = default_registry().site_for_venue_city_token(REGISTRY_VENUE_KEY, parsed.city)
    except SiteNotFoundError:
        return None
    return WeatherBucketFacts(
        settlement_station=site.cli_location,
        climate_day=dt.date.fromisoformat(parsed.climate_date),
        measure=Measure(parsed.measure),
        lower_f=interval[0],
        upper_f=interval[1],
    )
