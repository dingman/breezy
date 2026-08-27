"""``PolymarketUSInstrumentProvider`` -- the native Nautilus extension point.

Plan revision 2 section 6 (blueprinted as ``instruments.py``); build order
Step 9.

**Null hypothesis, settled by reading the install.** Nautilus already provides
the instrument-provider machinery: ``InstrumentProvider``
(``nautilus_trader/common/providers.py:29``) owns the ``_instruments``
dictionary, ``add``/``add_bulk``/``add_currency``, ``find``/``get_all``,
``count``, the ``initialize`` lock and its ``load_all`` / ``load_ids``
configuration handling, and the sync ``load_all``/``load_ids``/``load``
wrappers that marshal onto the event loop. ``LiveMarketDataClient`` type-checks
against exactly this base class (``live/data_client.py:361``). Only the two
venue-specific fetch overrides are net-new here; nothing above is
re-implemented, and a contract test asserts that none of those names appear in
this subclass's ``__dict__``.

**Rejection is loud.** A market whose payload fails validation raises
``InstrumentDefinitionError`` out of ``load_*_async`` and adds nothing. It is
never skipped with a warning: a silently short instrument list looks identical
to a venue with fewer markets, and the strategy layer downstream would simply
see no quotes for a market it was configured to trade.

**One request per slug per session.** Instrument metadata is static for the
life of a session (plan section 8.2), and the read budget is small, so a slug
already present in the provider is not re-fetched.

Read-only by construction: the only egress is
``PolymarketUSHttpClient.get_public`` against the unauthenticated gateway,
under the ``instruments`` quota key.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nautilus_trader.common.component import Clock
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId, Venue

from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient, SupportsVenueLog
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    assert_bounds_cross_checked,
    assert_valid_slug,
    instrument_id_to_slug,
    parse_weather_slug,
    slug_to_instrument_id,
)
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_DISCOVERY,
    QUOTA_KEY_INSTRUMENTS,
)

__all__ = [
    "MARKET_BY_SLUG_PATH",
    "MARKET_LIST_PATH",
    "DiscoveredMarket",
    "PolymarketUSInstrumentProvider",
    "discovery_candidate_slugs",
]

#: ``gateway.polymarket.us`` reference-data read, per the committed docs
#: snapshot ``api-reference_markets_get-market-by-slug_2026-08-25.md``.
MARKET_BY_SLUG_PATH: str = "/v1/market/slug/{slug}"
MARKET_LIST_PATH: str = "/v1/markets"

_RESOLVED_STATUS_VALUES: frozenset[str] = frozenset(
    {
        "MARKET_STATUS_RESOLVED",
        "MARKET_STATUS_CLOSED",
        "MARKET_STATUS_EXPIRED",
        "MARKET_STATUS_TERMINATED",
    }
)

_WEATHER_QUESTION_RE: re.Pattern[str] = re.compile(
    r"^(?:Highest|Lowest) temperature in (?P<city>.+?) on "
)


#: Hard cap on discovery pages per cycle.
#:
#: ``_discover_markets`` otherwise terminates only on a SHORT page, which makes
#: a hostile or broken RESPONSE the sole controller of loop termination: a host
#: that always returns a full page loops forever, growing ``discovered``
#: without bound, and ``initialize(reload=True)`` never returns. The venue
#: quota makes that a slow hang and a memory leak rather than a request flood,
#: which is exactly why it would be diagnosed late.
#:
#: 50 pages is roughly two orders of magnitude above the real weather universe
#: (five cities x a handful of daily strike ladders), so it can only be reached
#: by a payload that is already wrong.
MAX_DISCOVERY_PAGES: int = 50


@dataclass(frozen=True, slots=True)
class DiscoveredMarket:
    """One weather market observed during the latest discovery cycle."""

    slug: str
    resolved_reason: str | None
    payload: Mapping[str, Any]


def discovery_candidate_slugs(
    payload: Mapping[str, Any],
    *,
    city_codes: tuple[str, ...],
) -> tuple[str, ...]:
    """Return weather-market slugs in ``payload`` for the configured site cities."""
    return tuple(market["slug"] for market in _weather_market_payloads(payload, city_codes))


def _weather_market_payloads(
    payload: Mapping[str, Any],
    city_codes: tuple[str, ...],
) -> tuple[Mapping[str, Any], ...]:
    markets = _markets_from_payload(payload)
    accepted: list[Mapping[str, Any]] = []
    city_set = set(city_codes)
    for index, market in enumerate(markets):
        if not isinstance(market, Mapping):
            raise VenuePayloadError(
                f"{MARKET_LIST_PATH} response markets[{index}] must be an object, "
                f"got {type(market).__name__}"
            )
        slug = market.get("slug")
        assert_valid_slug(slug)
        assert isinstance(slug, str)
        parsed = parse_weather_slug(slug)
        city_name = _weather_city_name_from_payload(market)
        if parsed is None:
            if city_name is None:
                continue
            raise VenuePayloadError(
                f"{MARKET_LIST_PATH} returned weather market {slug!r} naming "
                f"{city_name!r}, but its slug does not match the observed weather grammar"
            )
        if city_name is None:
            raise VenuePayloadError(
                f"{MARKET_LIST_PATH} returned weather market {slug!r} but the venue "
                "payload does not explicitly name its city in the question field; "
                "refusing to fall back to slug parsing"
            )
        if parsed.city not in city_set:
            raise VenuePayloadError(
                f"{MARKET_LIST_PATH} returned weather market naming {city_name!r} "
                f"({slug!r}, slug city {parsed.city!r}), which has no polymarket_us "
                "entry in the settlement registry; refusing to trade or to skip a "
                "city Breezy holds no settlement truth for"
            )
        accepted.append(market)
    return tuple(accepted)


def _weather_city_name_from_payload(market: Mapping[str, Any]) -> str | None:
    question = market.get("question")
    if not isinstance(question, str):
        return None
    match = _WEATHER_QUESTION_RE.match(question)
    if match is None:
        return None
    return match.group("city")


def _markets_from_payload(payload: Mapping[str, Any]) -> Sequence[Any]:
    markets = payload.get("markets")
    if not isinstance(markets, Sequence) or isinstance(markets, (str, bytes, bytearray)):
        raise VenuePayloadError(
            f"{MARKET_LIST_PATH} response must contain a JSON array at key 'markets'"
        )
    return markets


def _resolved_reason(market: Mapping[str, Any]) -> str | None:
    if market.get("archived") is True:
        return "archived=true"
    if market.get("closed") is True:
        return f"closed=true status={market.get('status')!r} endDate={market.get('endDate')!r}"
    status = market.get("status")
    if isinstance(status, str) and status in _RESOLVED_STATUS_VALUES:
        return f"status={status} endDate={market.get('endDate')!r}"
    return None


class PolymarketUSInstrumentProvider(InstrumentProvider):
    """Load Polymarket.us weather markets as native ``BinaryOption`` instruments.

    Parameters
    ----------
    client : PolymarketUSHttpClient
        The read-only venue client. Only its public-gateway read is used.
    config : InstrumentProviderConfig
        The native Nautilus provider config (``load_all`` / ``load_ids``).
    venue : Venue
        The venue every produced ``InstrumentId`` belongs to.
    discovery : PolymarketUSMarketDiscoveryConfig
        The venue list-query and site-city registry used to discover markets.
    clock : Clock
        Source of ``ts_init``. Injected rather than read from the wall clock so
        the value is deterministic under test and consistent with the rest of
        the node's time source.
    """

    def __init__(
        self,
        *,
        client: PolymarketUSHttpClient,
        config: InstrumentProviderConfig,
        venue: Venue = POLYMARKET_US_VENUE,
        discovery: PolymarketUSMarketDiscoveryConfig,
        clock: Clock,
        logger: SupportsVenueLog | None = None,
    ) -> None:
        super().__init__(config=config)
        self._client: PolymarketUSHttpClient = client
        self._venue: Venue = venue
        self._discovery: PolymarketUSMarketDiscoveryConfig = discovery
        self._clock: Clock = clock
        self._discovery_log: SupportsVenueLog = logger if logger is not None else self._log
        self._market_slugs: tuple[str, ...] = ()
        self._active_market_slugs: tuple[str, ...] = ()
        self._resolved_market_reasons: dict[str, str] = {}
        self._last_successful_non_empty_discovery: tuple[str, ...] = ()

    @property
    def venue(self) -> Venue:
        """Return the venue this provider loads instruments for."""
        return self._venue

    @property
    def market_slugs(self) -> tuple[str, ...]:
        """Return the latest discovered market slug universe."""
        return self._market_slugs

    @property
    def active_market_slugs(self) -> tuple[str, ...]:
        """Return latest discovered markets eligible for live subscription."""
        return self._active_market_slugs

    @property
    def resolved_market_reasons(self) -> Mapping[str, str]:
        """Return latest venue-owned resolution reasons keyed by slug."""
        return dict(self._resolved_market_reasons)

    async def load_all_async(self, filters: dict[Any, Any] | None = None) -> None:
        """Discover weather markets through ``GET /v1/markets`` and load active ones."""
        discovered = await self._discover_markets()
        if not discovered:
            message = (
                "Polymarket.us market discovery returned zero configured-city weather "
                "markets this cycle; refusing to treat this as a quiet market"
            )
            self._discovery_log.error(message)
            raise VenuePayloadError(message)

        slugs = tuple(market.slug for market in discovered)
        if len(set(slugs)) != len(slugs):
            raise VenuePayloadError("Polymarket.us market discovery returned duplicate slugs")

        active_slugs: list[str] = []
        resolved: dict[str, str] = {}
        for market in discovered:
            if market.resolved_reason is not None:
                resolved[market.slug] = market.resolved_reason
                continue
            self._assert_bounds(market.payload, market.slug)
            payload = {"market": market.payload}
            instrument = parse_binary_option(
                payload, venue=self._venue, ts_init=self._clock.timestamp_ns()
            )
            if instrument.id.symbol.value != market.slug:
                raise VenuePayloadError(
                    f"Discovered market slug {market.slug!r} but the parser produced "
                    f"{instrument.id.symbol.value!r}"
                )
            self.add(instrument)
            active_slugs.append(market.slug)

        self._market_slugs = slugs
        self._active_market_slugs = tuple(active_slugs)
        self._resolved_market_reasons = resolved
        self._last_successful_non_empty_discovery = slugs
        self._discovery_log.info(
            "Polymarket.us discovery cycle loaded "
            f"{len(active_slugs)} active market(s), observed {len(resolved)} resolved "
            f"market(s), discovered {len(slugs)} total"
        )

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict[Any, Any] | None = None,
    ) -> None:
        """Load exactly requested IDs, refusing anything outside latest discovery."""
        if not instrument_ids:
            return
        slugs: list[str] = []
        for instrument_id in instrument_ids:
            slug = instrument_id_to_slug(instrument_id, self._venue)
            if slug not in self._market_slugs:
                raise VenuePayloadError(
                    f"InstrumentId {instrument_id} is outside the latest discovered "
                    "Polymarket.us market universe; refusing to fetch an undiscovered market"
                )
            slugs.append(slug)
        await self._load_slugs(tuple(slugs))

    async def load_async(
        self,
        instrument_id: InstrumentId,
        filters: dict[Any, Any] | None = None,
    ) -> None:
        """Load one instrument, reusing the cached definition when present."""
        await self.load_ids_async([instrument_id], filters)

    async def _load_slugs(self, slugs: tuple[str, ...]) -> None:
        for slug in slugs:
            if self.find(slug_to_instrument_id(slug, self._venue)) is not None:
                continue
            payload = await self._client.get_public(
                MARKET_BY_SLUG_PATH.format(slug=slug),
                quota_key=QUOTA_KEY_INSTRUMENTS,
            )
            instrument = parse_binary_option(
                payload, venue=self._venue, ts_init=self._clock.timestamp_ns()
            )
            if instrument.id.symbol.value != slug:
                raise VenuePayloadError(
                    f"Requested market slug {slug!r} but the venue returned "
                    f"{instrument.id.symbol.value!r}"
                )
            self.add(instrument)

    async def _discover_markets(self) -> tuple[DiscoveredMarket, ...]:
        discovered: list[DiscoveredMarket] = []
        offset = 0
        limit = self._discovery.limit
        for page in range(MAX_DISCOVERY_PAGES + 1):
            if page == MAX_DISCOVERY_PAGES:
                raise VenuePayloadError(
                    "Polymarket.us market discovery exceeded the "
                    f"{MAX_DISCOVERY_PAGES}-page cap without returning a short "
                    f"page (offset {offset}, limit {limit}). A response that "
                    "never terminates pagination is malformed or hostile; "
                    "refusing to keep paging."
                )
            payload = await self._client.get_public(
                MARKET_LIST_PATH,
                query=self._query(offset=offset),
                quota_key=QUOTA_KEY_DISCOVERY,
            )
            page_markets = _markets_from_payload(payload)
            for market in _weather_market_payloads(payload, self._discovery.city_codes):
                slug = market["slug"]
                assert isinstance(slug, str)
                discovered.append(
                    DiscoveredMarket(
                        slug=slug,
                        resolved_reason=_resolved_reason(market),
                        payload=market,
                    )
                )
            if len(page_markets) < limit:
                break
            offset += limit
        return tuple(discovered)

    def _query(self, *, offset: int) -> dict[str, object]:
        query: dict[str, object] = {
            "limit": self._discovery.limit,
            "offset": offset,
            "orderBy": self._discovery.order_by,
            "orderDirection": self._discovery.order_direction,
            "categories": self._discovery.categories,
        }
        if self._discovery.archived is not None:
            query["archived"] = self._discovery.archived
        if self._discovery.include_closed:
            return query
        if self._discovery.active is not None:
            query["active"] = self._discovery.active
        if self._discovery.closed is not None:
            query["closed"] = self._discovery.closed
        return query

    def _assert_bounds(self, market: Mapping[str, Any], slug: str) -> None:
        parsed = parse_weather_slug(slug)
        if parsed is None:
            raise VenuePayloadError(f"Discovered weather market {slug!r} no longer parses")
        assert_bounds_cross_checked(
            parsed,
            description=(
                market.get("description") if isinstance(market.get("description"), str) else None
            ),
            title=market.get("title") if isinstance(market.get("title"), str) else None,
            reading_is_whole_degrees=True,
        )

    def __repr__(self) -> str:
        return (
            f"PolymarketUSInstrumentProvider(venue={self._venue}, "
            f"discovered={len(self._market_slugs)}, loaded={self.count})"
        )
