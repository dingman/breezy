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

from typing import Any

from nautilus_trader.common.component import Clock
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.model.identifiers import InstrumentId, Venue

from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    assert_valid_slug,
    instrument_id_to_slug,
    slug_to_instrument_id,
)
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_INSTRUMENTS

__all__ = ["MARKET_BY_SLUG_PATH", "PolymarketUSInstrumentProvider"]

#: ``gateway.polymarket.us`` reference-data read, per the committed docs
#: snapshot ``api-reference_markets_get-market-by-slug_2026-08-25.md``.
MARKET_BY_SLUG_PATH: str = "/v1/market/slug/{slug}"


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
    market_slugs : tuple[str, ...]
        The configured universe. Validated eagerly so a malformed slug fails at
        wiring time rather than mid-session inside a URL path segment.
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
        market_slugs: tuple[str, ...],
        clock: Clock,
    ) -> None:
        super().__init__(config=config)
        if not market_slugs:
            raise VenuePayloadError(
                "PolymarketUSInstrumentProvider requires at least one configured "
                "market slug; an empty universe would load silently and quote nothing"
            )
        for slug in market_slugs:
            assert_valid_slug(slug)
        if len(set(market_slugs)) != len(market_slugs):
            raise VenuePayloadError(
                "PolymarketUSInstrumentProvider was given duplicate market slugs"
            )
        self._client: PolymarketUSHttpClient = client
        self._venue: Venue = venue
        self._market_slugs: tuple[str, ...] = tuple(market_slugs)
        self._clock: Clock = clock

    @property
    def venue(self) -> Venue:
        """Return the venue this provider loads instruments for."""
        return self._venue

    @property
    def market_slugs(self) -> tuple[str, ...]:
        """Return the configured market slug universe."""
        return self._market_slugs

    async def load_all_async(self, filters: dict[Any, Any] | None = None) -> None:
        """Load every configured slug. Any failure aborts the whole load."""
        await self._load_slugs(self._market_slugs)

    async def load_ids_async(
        self,
        instrument_ids: list[InstrumentId],
        filters: dict[Any, Any] | None = None,
    ) -> None:
        """Load exactly the requested IDs, refusing anything outside the universe."""
        if not instrument_ids:
            return
        slugs: list[str] = []
        for instrument_id in instrument_ids:
            slug = instrument_id_to_slug(instrument_id, self._venue)
            if slug not in self._market_slugs:
                raise VenuePayloadError(
                    f"InstrumentId {instrument_id} is outside the configured "
                    "Polymarket.us market slug universe; refusing to fetch an "
                    "unbudgeted market"
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

    def __repr__(self) -> str:
        return (
            f"PolymarketUSInstrumentProvider(venue={self._venue}, "
            f"slugs={len(self._market_slugs)}, loaded={self.count})"
        )
