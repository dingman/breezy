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
from breezy.adapters.polymarket_us.errors import (
    BoundsSemanticsError,
    InstrumentDefinitionError,
    SiteRegistryMismatchError,
    VenuePayloadError,
)
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

    def set_pages(self, pages: Sequence[Mapping[str, Any]]) -> None:
        """Swap the pages returned by a subsequent discovery cycle.

        Additive test helper only -- existing tests construct pages once via
        the constructor and never call this.
        """
        self._pages = [json.dumps(page).encode("utf-8") for page in pages]

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


def market_with_slug(slug: str, *, base: str = "market_open_510636_by_slug.json") -> dict[str, Any]:
    """A structurally-valid market payload re-keyed onto a distinct ``slug``.

    Only the slug (and the ``marketSides`` identifiers that must agree with
    it) changes; the bounds tokens are left untouched so the venue prose in
    the captured fixture keeps corroborating them.
    """
    market = wrapped_market(base)
    market["slug"] = slug
    for side in market["marketSides"]:
        side["identifier"] = slug
    return market


def broken_market(slug: str, *, delete_field: str) -> dict[str, Any]:
    """A ``market_with_slug`` payload missing one required field."""
    market = market_with_slug(slug)
    del market[delete_field]
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


def test_discovery_refuses_weather_city_without_registry_truth() -> None:
    market = dict(wrapped_market("market_open_510636_by_slug.json"))
    market["slug"] = "tc-temp-boshigh-2026-08-25-lt79f"
    market["question"] = "Highest temperature in Boston on August 25?"
    market["description"] = (
        "Will the highest temperature recorded at Logan Airport (KBOS) in Boston "
        "for 2026-08-25 as reported by the National Weather Service's "
        "Climatological Report (Daily) be less than or equal to 78F? "
        "Outcome verified from NWS Climatological Report."
    )

    with pytest.raises(
        VenuePayloadError,
        match=(
            "Boston.*tc-temp-boshigh-2026-08-25-lt79f.*no polymarket_us "
            "entry in the settlement registry"
        ),
    ):
        discovery_candidate_slugs(page_with(market), city_codes=("nyc",))


def test_non_weather_climate_payload_without_city_is_skipped() -> None:
    market = {
        "slug": "climate-policy-index-2026",
        "question": "Will the climate policy index close above 50 in 2026?",
        "description": "A non-temperature climate market with no settlement-city claim.",
    }

    assert discovery_candidate_slugs(page_with(market), city_codes=("nyc",)) == ()


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


# ---------------------------------------------------------------------------
# CF-14a -- evaluate-all-then-decide, a complete failure tally, abort
# semantics UNCHANGED (docs/plans/CF14_DISCOVERY_ISOLATION_2026-09-02.md)
# ---------------------------------------------------------------------------


def _error_messages(logger: NullLogger) -> list[str]:
    return [msg for level, msg in logger.messages if level == "error"]


@pytest.mark.asyncio
async def test_every_failing_market_is_evaluated_before_the_cycle_raises() -> None:
    """3 failures produce 3 tally entries, not 1 (A1)."""
    slugs = [
        "tc-temp-nychigh-2026-08-25-lt79f",
        "tc-temp-nychigh-2026-08-26-lt79f",
        "tc-temp-nychigh-2026-08-27-lt79f",
    ]
    markets = [broken_market(slug, delete_field="minimumTradeQty") for slug in slugs]
    provider, _, logger = provider_for_pages(
        [page_with(*markets)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )

    with pytest.raises(InstrumentDefinitionError):
        await provider.load_all_async()

    tallies = _error_messages(logger)
    assert len(tallies) == 1, "the tally must be one ERROR log, not one per failure"
    assert tallies[0].count("slug=") == 3
    for slug in slugs:
        assert slug in tallies[0]


@pytest.mark.asyncio
async def test_tally_content_is_order_independent() -> None:
    """Failing-first and failing-last give identical tally content."""
    bad_a = broken_market("tc-temp-nychigh-2026-08-25-lt79f", delete_field="minimumTradeQty")
    bad_b = broken_market("tc-temp-nychigh-2026-08-26-lt79f", delete_field="orderPriceMinTickSize")

    provider_first, _, logger_first = provider_for_pages(
        [page_with(bad_a, bad_b)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )
    with pytest.raises(InstrumentDefinitionError):
        await provider_first.load_all_async()

    provider_last, _, logger_last = provider_for_pages(
        [page_with(bad_b, bad_a)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )
    with pytest.raises(InstrumentDefinitionError):
        await provider_last.load_all_async()

    assert _error_messages(logger_first) == _error_messages(logger_last)


@pytest.mark.asyncio
async def test_tally_is_emitted_before_the_raise_and_survives_the_abort_path() -> None:
    """Pins C1: the tally must fire even though a caller of ``load_all_async``
    (mirroring ``_run_one_reload_cycle``, ``data.py:1058``) never reaches any
    code after the raise."""
    bad = broken_market("tc-temp-nychigh-2026-08-25-lt79f", delete_field="minimumTradeQty")
    provider, _, logger = provider_for_pages([page_with(bad)])

    downstream_reached = False
    try:
        await provider.load_all_async()
        downstream_reached = True  # pragma: no cover - must never execute
    except InstrumentDefinitionError:
        pass

    assert downstream_reached is False
    assert any("tc-temp-nychigh-2026-08-25-lt79f" in msg for msg in _error_messages(logger))


@pytest.mark.asyncio
async def test_raised_exception_is_the_first_collected_failure_unchanged() -> None:
    """Pins C2: type, message and ordering identity are preserved."""
    bad_first = broken_market("tc-temp-nychigh-2026-08-25-lt79f", delete_field="minimumTradeQty")
    bad_second = broken_market(
        "tc-temp-nychigh-2026-08-26-lt79f", delete_field="orderPriceMinTickSize"
    )
    provider, _, _ = provider_for_pages(
        [page_with(bad_first, bad_second)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )

    with pytest.raises(InstrumentDefinitionError, match="minimumTradeQty") as exc_info:
        await provider.load_all_async()

    assert "orderPriceMinTickSize" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_a_cohort_total_failure_still_aborts_with_instrument_definition_error() -> None:
    """Regression-pins today's incident: every market failing still hard-aborts."""
    bad_a = broken_market("tc-temp-nychigh-2026-08-25-lt79f", delete_field="minimumTradeQty")
    bad_b = broken_market("tc-temp-nychigh-2026-08-26-lt79f", delete_field="minimumTradeQty")
    provider, _, _ = provider_for_pages(
        [page_with(bad_a, bad_b)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )

    with pytest.raises(InstrumentDefinitionError):
        await provider.load_all_async()


@pytest.mark.asyncio
async def test_mixed_cohort_aborts_and_tally_names_every_bad_market() -> None:
    """3 good + 3 bad still aborts, and the tally names all 3 bad ones."""
    good_slugs = [f"tc-temp-nychigh-2026-08-{day}-lt79f" for day in (20, 21, 22)]
    bad_slugs = [f"tc-temp-nychigh-2026-08-{day}-lt79f" for day in (23, 24, 25)]
    goods = [market_with_slug(slug) for slug in good_slugs]
    bads = [broken_market(slug, delete_field="minimumTradeQty") for slug in bad_slugs]
    provider, _, logger = provider_for_pages(
        [page_with(*goods, *bads)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )

    with pytest.raises(InstrumentDefinitionError):
        await provider.load_all_async()

    tally = _error_messages(logger)[0]
    for slug in bad_slugs:
        assert f"slug={slug!r}" in tally
    for slug in good_slugs:
        assert f"slug={slug!r}" not in tally
    assert provider.count == 0


@pytest.mark.asyncio
async def test_state_is_unchanged_from_pre_cycle_values_on_abort() -> None:
    """On abort, ``count``/``market_slugs``/``active_market_slugs``/
    ``resolved_market_reasons`` are all unchanged from pre-cycle (pins A4)."""
    good = market_with_slug("tc-temp-nychigh-2026-08-25-lt79f")
    provider, transport, _ = provider_for_pages([page_with(good)])
    await provider.load_all_async()

    pre_count = provider.count
    pre_market_slugs = provider.market_slugs
    pre_active_slugs = provider.active_market_slugs
    pre_resolved = dict(provider.resolved_market_reasons)

    bad = broken_market("tc-temp-nychigh-2026-08-26-lt79f", delete_field="minimumTradeQty")
    transport.set_pages([page_with(bad)])

    with pytest.raises(InstrumentDefinitionError):
        await provider.load_all_async()

    assert provider.count == pre_count
    assert provider.market_slugs == pre_market_slugs
    assert provider.active_market_slugs == pre_active_slugs
    assert dict(provider.resolved_market_reasons) == pre_resolved


@pytest.mark.asyncio
async def test_all_markets_are_added_on_a_fully_successful_cycle() -> None:
    """On success, ``self.add()`` still fires for every loaded market."""
    slugs = [f"tc-temp-nychigh-2026-08-{day}-lt79f" for day in (20, 21, 22)]
    markets = [market_with_slug(slug) for slug in slugs]
    provider, _, _ = provider_for_pages(
        [page_with(*markets)], discovery=PolymarketUSMarketDiscoveryConfig(limit=10)
    )

    await provider.load_all_async()

    assert provider.count == 3
    assert set(provider.active_market_slugs) == set(slugs)
    for slug in slugs:
        assert provider.find(InstrumentId(Symbol(slug), POLYMARKET_US_VENUE)) is not None


@pytest.mark.asyncio
async def test_a_site_registry_mismatch_is_distinguishable_from_a_venue_payload_error() -> None:
    """Pins A3: a ``discovery.city_codes`` <-> ``SiteRegistry`` mismatch is a
    Breezy config bug, not a venue payload error, and must not masquerade as
    ``InstrumentDefinitionError`` -- see CF-14b's future per-market gate."""
    market = market_with_slug("tc-temp-zzzhigh-2026-08-25-lt79f")
    market["question"] = "Highest temperature in Nowhereland on August 25?"
    discovery = PolymarketUSMarketDiscoveryConfig(limit=2, city_codes=("zzz",))
    provider, _, _ = provider_for_pages([page_with(market)], discovery=discovery)

    with pytest.raises(SiteRegistryMismatchError) as exc_info:
        await provider.load_all_async()

    assert not isinstance(exc_info.value, VenuePayloadError)
