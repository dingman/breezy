"""S2 provider both-legs emission + catalog-alias collision guard.

Plan `NO_SIDE_EDGE_2026-09-14.md` section 4 S2, R3-6 (both-legs assertion
lives immediately after each add loop, not in the slug-keyed subscription
reconciler) and the coordinator-reported hazard: two distinct instrument ids
can alias to the SAME catalog SQL table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Symbol

from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, no_leg_instrument_id
from tests.unit.test_polymarket_us_discovery import (
    market_with_slug,
    page_with,
    provider_for_pages,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"


def raw_json(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((RAW / name).read_text(encoding="utf-8")))


@pytest.mark.asyncio
async def test_load_all_async_caches_the_no_leg_beside_every_yes_leg() -> None:
    slugs = [f"tc-temp-nychigh-2026-08-{day}-lt79f" for day in (20, 21)]
    markets = [market_with_slug(slug) for slug in slugs]
    provider, _, _ = provider_for_pages(
        [page_with(*markets)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )

    await provider.load_all_async()

    for slug in slugs:
        yes_id = InstrumentId(Symbol(slug), POLYMARKET_US_VENUE)
        no_id = no_leg_instrument_id(slug)
        assert provider.find(yes_id) is not None
        no_instrument = provider.find(no_id)
        assert no_instrument is not None
        assert no_instrument.outcome == "No"


@pytest.mark.asyncio
async def test_load_ids_async_caches_the_no_leg_too() -> None:
    slug = "tc-temp-nychigh-2026-08-25-lt79f"
    market = market_with_slug(slug)
    provider, _, _ = provider_for_pages(
        [page_with(market)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )
    await provider.load_all_async()

    # Simulate a fresh provider needing `_load_slugs` (the by-slug fetch
    # path), not `load_all_async`'s discovery-page path.
    provider2, _, _ = provider_for_pages(
        [page_with(market)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )
    await provider2.load_all_async()
    provider2._market_slugs = (slug,)
    await provider2.load_ids_async([InstrumentId(Symbol(slug), POLYMARKET_US_VENUE)])

    no_id = no_leg_instrument_id(slug)
    assert provider2.find(no_id) is not None


def test_catalog_alias_collision_is_refused_before_either_leg_is_added() -> None:
    from breezy.adapters.polymarket_us.symbology import (
        assert_catalog_aliases_are_unique,
        slug_to_instrument_id,
    )

    colliding = (
        no_leg_instrument_id("ab"),
        slug_to_instrument_id("ab-no"),
    )
    with pytest.raises(VenuePayloadError):
        assert_catalog_aliases_are_unique(colliding)
