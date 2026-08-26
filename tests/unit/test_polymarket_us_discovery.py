"""Autonomous Polymarket.us market discovery (G-18).

Every venue payload here is a committed capture under ``docs/evidence``. The
tests deliberately exercise the list endpoint shape, not by-slug fixtures, so a
static ``POLYMARKET_US_MARKET_SLUGS`` implementation cannot pass.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from nautilus_trader.common.component import TestClock
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId, Symbol

from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
from breezy.adapters.polymarket_us.errors import BoundsSemanticsError, VenuePayloadError
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.provider import (
    MARKET_LIST_PATH,
    PolymarketUSInstrumentProvider,
    discovery_candidate_slugs,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_DISCOVERY, VenueResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

OPEN_SLUG = "tc-temp-nychigh-2026-08-25-lt79f"
EXPIRED_SLUG = "tc-temp-nychigh-2026-04-23-gte72lt73f"
TS_INIT = 1_787_617_213_000_000_000


def raw_json(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((RAW / name).read_text(encoding="utf-8")))


def raw_bytes(name: str) -> bytes:
    return (RAW / name).read_bytes()


class RecordingListTransport:
    """GET-only list transport keyed by requested ``offset``."""

    def __init__(self, pages: Sequence[Mapping[str, Any]]) -> None:
        self._pages = [json.dumps(page).encode("utf-8") for page in pages]
        self.calls: list[tuple[str, str]] = []

    async def get(self, url: str, *, headers: dict[str, str], quota_key: str) -> VenueResponse:
        self.calls.append((url, quota_key))
        offset = 0
        if "offset=" in url:
            offset = int(url.split("offset=", 1)[1].split("&", 1)[0])
        index = min(offset, len(self._pages) - 1)
        return VenueResponse(status=200, headers={}, body=self._pages[index])


class UnusableSigner:
    def sign_headers(self, *args: object, **kwargs: object) -> list[tuple[str, str]]:
        raise AssertionError("market discovery must use public GET reads")


class NullLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def debug(self, message: str) -> None:
        self.messages.append(("debug", message))

    def info(self, message: str) -> None:
        self.messages.append(("info", message))

    def warning(self, message: str) -> None:
        self.messages.append(("warning", message))

    def error(self, message: str) -> None:
        self.messages.append(("error", message))


def page_with(*markets: Mapping[str, Any]) -> dict[str, Any]:
    return {"markets": list(markets)}


def wrapped_market(name: str) -> dict[str, Any]:
    payload = raw_json(name)
    market = payload["market"]
    assert isinstance(market, dict)
    return market


def provider_for_pages(
    pages: Sequence[Mapping[str, Any]],
    *,
    discovery: PolymarketUSMarketDiscoveryConfig | None = None,
) -> tuple[PolymarketUSInstrumentProvider, RecordingListTransport, NullLogger]:
    transport = RecordingListTransport(pages)
    logger = NullLogger()
    client = PolymarketUSHttpClient(
        transport=transport,  # type: ignore[arg-type]
        signer=UnusableSigner(),  # type: ignore[arg-type]
        api_base_url="https://api.polymarket.us",
        gateway_base_url="https://gateway.polymarket.us",
        logger=logger,
    )
    clock = TestClock()
    clock.set_time(TS_INIT)
    provider = PolymarketUSInstrumentProvider(
        client=client,
        config=InstrumentProviderConfig(load_all=True),
        venue=POLYMARKET_US_VENUE,
        discovery=discovery or PolymarketUSMarketDiscoveryConfig(limit=2),
        clock=clock,
        logger=logger,
    )
    return provider, transport, logger


def test_captured_climate_list_payload_exposes_the_expected_weather_slug_set() -> None:
    payload = raw_json("markets_categories_climate.json")

    assert set(discovery_candidate_slugs(payload, city_codes=("nyc", "mia", "mdw", "lax"))) == {
        "tc-temp-nychigh-2026-04-22-gte56lt57f",
        "tc-temp-nychigh-2026-04-22-gte62lt63f",
        "tc-temp-miahigh-2026-04-22-gte76lt77f",
        "tc-temp-nychigh-2026-04-22-lt56f",
        "tc-temp-miahigh-2026-04-22-gte78lt79f",
        "tc-temp-nychigh-2026-04-22-gte64f",
        "tc-temp-miahigh-2026-04-22-gte80lt81f",
        "tc-temp-nychigh-2026-04-22-gte58lt59f",
        "tc-temp-miahigh-2026-04-22-lt76f",
        "tc-temp-nychigh-2026-04-22-gte60lt61f",
        "tc-temp-miahigh-2026-04-22-gte82lt83f",
        "tc-temp-miahigh-2026-04-22-gte84f",
        "tc-temp-mdwhigh-2026-04-22-lt68f",
        "tc-temp-mdwhigh-2026-04-22-gte70lt71f",
        "tc-temp-mdwhigh-2026-04-22-gte74lt75f",
        "tc-temp-laxhigh-2026-04-22-gte64lt65f",
        "tc-temp-mdwhigh-2026-04-22-gte68lt69f",
        "tc-temp-laxhigh-2026-04-22-gte66lt67f",
        "tc-temp-mdwhigh-2026-04-22-gte72lt73f",
        "tc-temp-laxhigh-2026-04-22-gte68lt69f",
    }


@pytest.mark.asyncio
async def test_provider_discovers_open_markets_from_the_list_endpoint() -> None:
    provider, transport, _ = provider_for_pages(
        [page_with(wrapped_market("market_open_510636_by_slug.json"))]
    )

    await provider.load_all_async()

    assert provider.market_slugs == (OPEN_SLUG,)
    assert provider.active_market_slugs == (OPEN_SLUG,)
    assert provider.find(InstrumentId(Symbol(OPEN_SLUG), POLYMARKET_US_VENUE)) is not None
    assert len(transport.calls) == 1
    url, quota_key = transport.calls[0]
    assert url.startswith("https://gateway.polymarket.us" + MARKET_LIST_PATH)
    assert "limit=2" in url
    assert "offset=0" in url
    assert quota_key == QUOTA_KEY_DISCOVERY


@pytest.mark.asyncio
async def test_provider_follows_pagination_until_a_short_page() -> None:
    provider, transport, _ = provider_for_pages(
        [
            page_with(wrapped_market("market_open_510636_by_slug.json")),
            page_with(wrapped_market("market_closed_15806_by_slug.json")),
            page_with(),
        ],
        discovery=PolymarketUSMarketDiscoveryConfig(limit=1, include_closed=True),
    )

    await provider.load_all_async()

    assert provider.market_slugs == (OPEN_SLUG, EXPIRED_SLUG)
    assert len(transport.calls) == 3
    assert [url.split("offset=", 1)[1].split("&", 1)[0] for url, _ in transport.calls] == [
        "0",
        "1",
        "2",
    ]


@pytest.mark.asyncio
async def test_zero_discovery_cycle_raises_and_alerts_loudly() -> None:
    provider, _, logger = provider_for_pages([page_with()])

    with pytest.raises(VenuePayloadError, match="discovery returned zero"):
        await provider.load_all_async()

    assert any(
        level == "error" and "discovery returned zero" in msg
        for level, msg in logger.messages
    )


@pytest.mark.asyncio
async def test_bounds_disagreement_fails_closed() -> None:
    market = dict(wrapped_market("market_open_510636_by_slug.json"))
    market["description"] = "Will the highest temperature be less than or equal to 79F?"
    provider, _, _ = provider_for_pages([page_with(market)])

    with pytest.raises(BoundsSemanticsError):
        await provider.load_all_async()


@given(st.lists(st.sampled_from([OPEN_SLUG, EXPIRED_SLUG]), unique=True))
def test_subscription_plan_never_subscribes_before_cache_contains_the_instrument(
    slugs: list[str],
) -> None:
    from breezy.adapters.polymarket_us.data import subscription_changes_after_discovery

    cached: set[str] = set(slugs[:1])
    plan = subscription_changes_after_discovery(
        desired_slugs=tuple(slugs),
        live_slugs=(),
        cached_slugs=frozenset(cached),
        resolved_reasons={},
    )

    assert set(plan.subscribe) <= cached
