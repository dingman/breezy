"""Data-client contract for the Polymarket.us read-only slice (plan Step 11).

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` section 6
(``data.py`` blueprint, ``:830-881``), section 8.3 quote flow (``:1059-1073``)
and section 9 Step 11 (``:1241-1251``).

What is deliberately proven here rather than asserted by inspection:

* **client_id / venue derivation.** ``LiveMarketDataClient.__init__``
  (``live/data_client.py:349-361``) takes both POSITIONALLY and type-checks
  the instrument provider immediately after, while ``LiveDataClientFactory``
  (``live/factories.py:33``) has no venue in scope. The derivation
  (``ClientId(name)``, module-constant venue) is therefore code, and code
  needs a test.
* **Delivery into the real ``DataEngine``.** ``_handle_data`` sends to the
  ``DataEngine.process`` endpoint (``data/client.pyx:1262-1263``); a test
  that only spies on ``_handle_data`` would pass even if the tick never
  reached the engine. These tests run a real ``DataEngine`` and a real
  ``MessageBus`` and assert on the published topic.
* **No orphaned task after disconnect.** Nautilus calls ``connect()`` once
  and provides no supervision; every task the adapter starts is the
  adapter's to cancel.
"""

from __future__ import annotations

import ast
import asyncio
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.data.messages import (
    SubscribeOrderBook,
    SubscribeQuoteTicks,
    UnsubscribeOrderBook,
    UnsubscribeQuoteTicks,
)
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.model.enums import AssetClass, BookType
from nautilus_trader.model.identifiers import ClientId, InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import (
    DISCOVERY_RELOAD_FLOOR_SECS,
    FRAME_DIAGNOSTICS_CAPACITY,
    MARKET_SLUG_KEY,
    MISSING_ROUTING_KEY_WARN_EVERY,
    POLYMARKET_US_VENUE,
    PolymarketUSDataClient,
    build_data_client,
    frame_class_counts,
    should_warn_at_count,
)
from breezy.adapters.polymarket_us.websocket import (
    SilentSubscriptionWarning,
    VenueTransportError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

SLUG = "tc-temp-nychigh-2026-08-25-lt79f"
OTHER_SLUG = "tc-temp-mdwhigh-2026-08-25-lt91f"
CLIENT_NAME = "POLYMARKET_US"


# ---------------------------------------------------------------------------
# Fixtures and doubles
# ---------------------------------------------------------------------------


def make_instrument(
    slug: str,
    *,
    activation_ns: int = 0,
    expiration_ns: int = 1_800_000_000_000_000_000,
) -> BinaryOption:
    symbol = Symbol(slug)
    price_increment = Price.from_str("0.001")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=POLYMARKET_US_VENUE),
        raw_symbol=symbol,
        outcome="Yes",
        description="Test weather market",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=price_increment.precision,
        price_increment=price_increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=activation_ns,
        expiration_ns=expiration_ns,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
    )


class FakeInstrumentProvider(InstrumentProvider):
    """Minimal provider double: records loads, serves preloaded instruments."""

    def __init__(self, instruments: Sequence[Instrument]) -> None:
        super().__init__(config=InstrumentProviderConfig(load_all=True))
        self._preloaded = list(instruments)
        self.load_all_calls = 0
        self._resolved_market_reasons: dict[str, str] = {}

    async def load_all_async(self, filters: dict[str, Any] | None = None) -> None:
        self.load_all_calls += 1
        for instrument in self._preloaded:
            self.add(instrument)

    @property
    def market_slugs(self) -> tuple[str, ...]:
        return tuple(str(instrument.id.symbol.value) for instrument in self._preloaded)

    @property
    def active_market_slugs(self) -> tuple[str, ...]:
        return tuple(str(instrument.id.symbol.value) for instrument in self._preloaded)

    @property
    def resolved_market_reasons(self) -> Mapping[str, str]:
        return dict(self._resolved_market_reasons)


class FakeMarketsFeed:
    """Structural stand-in for ``PolymarketUSMarketsWebSocket``.

    The real socket cannot be built under the test suite at all: the autouse
    fixture in ``tests/conftest.py`` replaces the ``nautilus_pyo3``
    ``WebSocketClient`` constructor with a raising sentinel.
    """

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.events: list[str] = []
        self._subscriptions: dict[str, str] = {}
        self._connected = False
        self._fatally_degraded = False
        self._silent: list[SilentSubscriptionWarning] = []
        self._next_id = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_degraded(self) -> bool:
        return self._fatally_degraded or bool(self._silent)

    @property
    def is_fatally_degraded(self) -> bool:
        """Only the UNRECOVERABLE class -- what the client may stop the run over."""
        return self._fatally_degraded

    @property
    def silent_subscriptions(self) -> tuple[SilentSubscriptionWarning, ...]:
        """Subscribed slugs with no inbound frame yet. Reported, never fatal."""
        return tuple(self._silent)

    @property
    def subscriptions(self) -> Mapping[str, str]:
        return dict(self._subscriptions)

    async def connect(self) -> None:
        self.events.append("connect")
        self._connected = True

    async def close(self) -> None:
        self.events.append("close")
        self._connected = False

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        self._next_id += 1
        request_id = f"req-{self._next_id}"
        for slug in market_slugs:
            self.events.append(f"subscribe:{slug}")
            self._subscriptions[slug] = request_id

    async def unsubscribe(self, request_id: str) -> None:
        self.events.append(f"unsubscribe:{request_id}")
        for slug, held in list(self._subscriptions.items()):
            if held == request_id:
                del self._subscriptions[slug]

    def degrade_fatally(self) -> None:
        """The FATAL class: reconnection abandoned, or the supervisor died.

        Named for the class it belongs to, because the non-fatal class (a
        silent, unconfirmed subscription) also raises `is_degraded` and must
        NOT reach safe mode -- a double with one undifferentiated `degrade()`
        is what let those two be conflated in the first place.
        """
        self._fatally_degraded = True
        self._connected = False

    def go_silent(self, slug: str, after_secs: float = 60.0) -> None:
        """The NON-FATAL class: one subscribed slug produced no inbound frame."""
        self._silent.append(SilentSubscriptionWarning(slug=slug, subscribed_after_secs=after_secs))

    def deliver(self, payload: Mapping[str, Any]) -> None:
        self.handler(json.dumps(payload).encode())

    def deliver_raw(self, raw: bytes) -> None:
        self.handler(raw)


class _RaisingSubscribeFeed(FakeMarketsFeed):
    """A `FakeMarketsFeed` whose `subscribe_market_data` raises exactly once,
    on demand (`raise_on_next_subscribe`), then behaves normally."""

    def __init__(self, handler: Any) -> None:
        super().__init__(handler)
        self.raise_on_next_subscribe = False

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        if self.raise_on_next_subscribe:
            self.raise_on_next_subscribe = False
            raise VenueTransportError("simulated subscribe failure")
        await super().subscribe_market_data(market_slugs)


def fake_quote_parser(
    payload: Mapping[str, Any],
    *,
    instrument: Instrument,
    ts_init: int,
) -> Any:
    """Stand-in for ``parsing.parse_quote_tick`` (a sibling seam, Step 7)."""
    from nautilus_trader.model.data import QuoteTick

    if "marketData" in payload and isinstance(payload["marketData"], Mapping):
        book = payload["marketData"]
        bid_price = book["bids"][0]["px"]["value"]
        ask_price = book["offers"][0]["px"]["value"]
    else:
        bid_price = payload["bid"]
        ask_price = payload["ask"]

    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price.from_str(str(bid_price)),
        ask_price=Price.from_str(str(ask_price)),
        bid_size=Quantity.from_str("10"),
        ask_size=Quantity.from_str("10"),
        ts_event=int(payload.get("tsEvent", ts_init)),
        ts_init=ts_init,
    )


def raising_quote_parser(
    payload: Mapping[str, Any],
    *,
    instrument: Instrument,
    ts_init: int,
) -> Any:
    raise ValueError("unparseable frame")


def make_config(**overrides: object) -> PolymarketUSDataClientConfig:
    kwargs: dict[str, object] = {
        # Deliberate test-double origin off the venue domain.
        "allow_foreign_origin": True,
        "api_base_url": "https://api.example.invalid",
        "gateway_base_url": "https://gateway.example.invalid",
        "ws_url": "wss://api.example.invalid",
        "instrument_reload_interval_mins": 5,
        "user_agent": "breezy-test/1.0 (+mailto:ops@example.invalid)",
        "instrument_provider": InstrumentProviderConfig(load_all=True),
    }
    kwargs.update(overrides)
    return PolymarketUSDataClientConfig(**kwargs)  # type: ignore[arg-type]


class Harness:
    """A real msgbus, cache, clock and ``DataEngine`` around the client."""

    def __init__(self, client: PolymarketUSDataClient, feed: FakeMarketsFeed) -> None:
        self.client = client
        self.feed = feed
        self.published: list[Any] = []


def build_harness(
    *,
    instruments: Sequence[Instrument] | None = None,
    quote_parser: Any = fake_quote_parser,
    config: PolymarketUSDataClientConfig | None = None,
    name: str = CLIENT_NAME,
    feed_cls: type[FakeMarketsFeed] = FakeMarketsFeed,
) -> Harness:
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    provider = FakeInstrumentProvider(
        [make_instrument(SLUG)] if instruments is None else instruments
    )
    feeds: list[FakeMarketsFeed] = []

    def feed_factory(handler: Any) -> FakeMarketsFeed:
        feed = feed_cls(handler)
        feeds.append(feed)
        return feed

    client = build_data_client(
        loop=asyncio.get_event_loop(),
        name=name,
        config=make_config() if config is None else config,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=provider,
        feed_factory=feed_factory,
        quote_parser=quote_parser,
    )
    engine.register_client(client)

    harness = Harness(client, feeds[0])
    msgbus.subscribe(topic="data.quotes.*", handler=harness.published.append)
    return harness


def subscribe_command(instrument_id: InstrumentId) -> SubscribeQuoteTicks:
    return SubscribeQuoteTicks(
        instrument_id=instrument_id,
        client_id=ClientId(CLIENT_NAME),
        venue=POLYMARKET_US_VENUE,
        command_id=UUID4(),
        ts_init=0,
        params=None,
    )


def unsubscribe_command(instrument_id: InstrumentId) -> UnsubscribeQuoteTicks:
    return UnsubscribeQuoteTicks(
        instrument_id=instrument_id,
        client_id=ClientId(CLIENT_NAME),
        venue=POLYMARKET_US_VENUE,
        command_id=UUID4(),
        ts_init=0,
        params=None,
    )


def depth_subscribe_command(instrument_id: InstrumentId) -> SubscribeOrderBook:
    return SubscribeOrderBook(
        instrument_id,
        OrderBookDepth10,
        BookType.L2_MBP,
        ClientId(CLIENT_NAME),
        POLYMARKET_US_VENUE,
        UUID4(),
        0,
    )


def depth_unsubscribe_command(instrument_id: InstrumentId) -> UnsubscribeOrderBook:
    return UnsubscribeOrderBook(
        instrument_id,
        OrderBookDepth10,
        ClientId(CLIENT_NAME),
        POLYMARKET_US_VENUE,
        UUID4(),
        0,
    )


# ---------------------------------------------------------------------------
# Derivation of client_id and venue -- pinned, because the factory has no venue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_id_equals_the_registered_factory_name() -> None:
    harness = build_harness(name="PM_US_ALT")
    assert harness.client.id == ClientId("PM_US_ALT")


@pytest.mark.asyncio
async def test_venue_equals_the_polymarket_us_venue_constant() -> None:
    harness = build_harness()
    assert harness.client.venue == POLYMARKET_US_VENUE
    assert POLYMARKET_US_VENUE == Venue("POLYMARKET_US")


@pytest.mark.asyncio
async def test_base_class_accepts_the_instrument_provider() -> None:
    """``PyCondition.type`` at ``live/data_client.py:361`` must pass."""
    harness = build_harness()
    assert isinstance(harness.client, PolymarketUSDataClient)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_loads_instruments_then_connects_then_subscribes() -> None:
    harness = build_harness()
    await harness.client._connect()

    provider = harness.client._instrument_provider
    assert isinstance(provider, FakeInstrumentProvider)
    assert provider.load_all_calls == 1
    assert harness.feed.events == ["connect", f"subscribe:{SLUG}"]

    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_connect_publishes_loaded_instruments_to_the_data_engine() -> None:
    harness = build_harness()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    assert harness.client._cache.instrument(instrument_id) is None

    await harness.client._connect()

    assert harness.client._cache.instrument(instrument_id) is not None
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_disconnect_closes_the_feed_and_leaves_no_orphaned_task() -> None:
    before = {task for task in asyncio.all_tasks() if not task.done()}
    harness = build_harness()
    await harness.client._connect()
    await harness.client._disconnect()
    await asyncio.sleep(0)

    assert "close" in harness.feed.events
    leaked = {task for task in asyncio.all_tasks() if not task.done()} - before
    assert leaked == set()


@pytest.mark.asyncio
async def test_discovery_reload_subscribes_new_and_unsubscribes_resolved_markets() -> None:
    first = make_instrument(SLUG)
    second = make_instrument(OTHER_SLUG)
    harness = build_harness(instruments=[first])
    await harness.client._connect()
    provider = harness.client._instrument_provider
    assert isinstance(provider, FakeInstrumentProvider)

    provider._preloaded = [second]
    provider._resolved_market_reasons = {SLUG: "closed=true status='MARKET_STATUS_RESOLVED'"}
    await provider.initialize(reload=True)
    harness.client._send_all_instruments_to_data_engine()
    await harness.client._reconcile_discovered_subscriptions(cycle="test")

    assert SLUG not in harness.feed.subscriptions
    assert OTHER_SLUG in harness.feed.subscriptions
    assert any(event.startswith("unsubscribe:") for event in harness.feed.events)
    assert f"subscribe:{OTHER_SLUG}" in harness.feed.events

    await harness.client._disconnect()


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_quote_ticks_subscribes_the_slug_once() -> None:
    harness = build_harness()
    await harness.client._connect()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)

    await harness.client._subscribe_quote_ticks(subscribe_command(instrument_id))
    await harness.client._subscribe_quote_ticks(subscribe_command(instrument_id))

    assert harness.feed.events.count(f"subscribe:{SLUG}") == 1
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_unsubscribe_quote_ticks_releases_the_request_id() -> None:
    harness = build_harness()
    await harness.client._connect()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    request_id = harness.feed.subscriptions[SLUG]

    await harness.client._unsubscribe_quote_ticks(unsubscribe_command(instrument_id))

    assert f"unsubscribe:{request_id}" in harness.feed.events
    assert SLUG not in harness.feed.subscriptions
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_subscribe_refuses_an_instrument_id_from_another_venue() -> None:
    harness = build_harness()
    await harness.client._connect()
    foreign = InstrumentId(Symbol(SLUG), Venue("KALSHI"))

    await harness.client._subscribe_quote_ticks(subscribe_command(foreign))

    assert harness.feed.events == ["connect", f"subscribe:{SLUG}"]
    await harness.client._disconnect()


# ---------------------------------------------------------------------------
# Phase 0b: depth subscription shares the quote feed subscription, reference
# counted -- one socket, no NotImplementedError.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depth_sub_on_a_quote_subscribed_instrument_issues_no_new_subscribe() -> None:
    harness = build_harness()
    await harness.client._connect()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    await harness.client._subscribe_quote_ticks(subscribe_command(instrument_id))

    await harness.client._subscribe_order_book_depth(depth_subscribe_command(instrument_id))

    assert harness.feed.events.count(f"subscribe:{SLUG}") == 1
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_unsubscribing_quotes_while_depth_remains_keeps_the_feed_sub() -> None:
    harness = build_harness()
    await harness.client._connect()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    await harness.client._subscribe_quote_ticks(subscribe_command(instrument_id))
    await harness.client._subscribe_order_book_depth(depth_subscribe_command(instrument_id))

    await harness.client._unsubscribe_quote_ticks(unsubscribe_command(instrument_id))

    assert SLUG in harness.feed.subscriptions
    assert not any(event.startswith("unsubscribe:") for event in harness.feed.events)
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_unsubscribing_depth_while_quotes_remain_keeps_the_feed_sub() -> None:
    harness = build_harness()
    await harness.client._connect()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    await harness.client._subscribe_quote_ticks(subscribe_command(instrument_id))
    await harness.client._subscribe_order_book_depth(depth_subscribe_command(instrument_id))

    await harness.client._unsubscribe_order_book_depth(depth_unsubscribe_command(instrument_id))

    assert SLUG in harness.feed.subscriptions
    assert not any(event.startswith("unsubscribe:") for event in harness.feed.events)
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_unsubscribing_both_types_releases_the_feed_subscription() -> None:
    harness = build_harness()
    await harness.client._connect()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    await harness.client._subscribe_quote_ticks(subscribe_command(instrument_id))
    await harness.client._subscribe_order_book_depth(depth_subscribe_command(instrument_id))

    await harness.client._unsubscribe_quote_ticks(unsubscribe_command(instrument_id))
    await harness.client._unsubscribe_order_book_depth(depth_unsubscribe_command(instrument_id))

    assert SLUG not in harness.feed.subscriptions
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_depth_subscribe_task_completes_without_the_base_not_implemented_error() -> None:
    """The base ``_subscribe_order_book_depth`` raises `NotImplementedError`,
    which `_on_task_completed` would only log (never re-raise) -- so this
    proves the override is live by inspecting the SCHEDULED task itself,
    not just that the direct coroutine call doesn't raise."""
    harness = build_harness()
    await harness.client._connect()
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)

    harness.client.subscribe_order_book_depth(depth_subscribe_command(instrument_id))
    (task,) = tuple(
        task
        for task in harness.client._tasks
        if task.get_name() == f"subscribe: order_book_depth {instrument_id}"
    )
    await task

    assert task.exception() is None
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_discovery_interest_survives_a_depth_only_subscribe_unsubscribe_pair() -> None:
    """A discovery-driven quote slug (the recorder's whole coverage) must not
    be torn down by an UNRELATED depth subscribe/unsubscribe pair -- discovery
    interest counts as quote interest for the shared feed refcount."""
    harness = build_harness()
    await harness.client._connect()
    assert SLUG in harness.feed.subscriptions
    instrument_id = InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)

    await harness.client._subscribe_order_book_depth(depth_subscribe_command(instrument_id))
    await harness.client._unsubscribe_order_book_depth(depth_unsubscribe_command(instrument_id))

    assert SLUG in harness.feed.subscriptions

    # Discovery itself now decides SLUG is out of scope -> a REAL teardown.
    harness.client._instrument_provider._preloaded.clear()  # type: ignore[attr-defined]
    await harness.client._reconcile_discovered_subscriptions(cycle="reload")

    assert SLUG not in harness.feed.subscriptions
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_failed_quote_subscribe_leaves_no_phantom_interest() -> None:
    harness = build_harness(feed_cls=_RaisingSubscribeFeed)
    other_instrument = make_instrument(OTHER_SLUG)
    harness.client._cache.add_instrument(other_instrument)
    instrument_id = other_instrument.id
    assert isinstance(harness.feed, _RaisingSubscribeFeed)
    harness.feed.raise_on_next_subscribe = True

    with pytest.raises(VenueTransportError):
        await harness.client._subscribe_quote_ticks(subscribe_command(instrument_id))

    assert OTHER_SLUG not in harness.client._quote_subscribed_slugs
    assert OTHER_SLUG not in harness.feed.subscriptions

    # A later depth subscribe + unsubscribe must tear the feed sub down
    # cleanly -- no phantom quote interest must survive the failed subscribe.
    await harness.client._subscribe_order_book_depth(depth_subscribe_command(instrument_id))
    await harness.client._unsubscribe_order_book_depth(depth_unsubscribe_command(instrument_id))

    assert OTHER_SLUG not in harness.feed.subscriptions


# ---------------------------------------------------------------------------
# Quote flow: WS frame -> QuoteTick -> DataEngine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_market_data_frame_reaches_the_data_engine_as_a_quote_tick() -> None:
    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver({MARKET_SLUG_KEY: SLUG, "bid": "0.470", "ask": "0.520"})

    assert len(harness.published) == 1
    tick = harness.published[0]
    assert tick.instrument_id == InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    assert tick.bid_price == Price.from_str("0.470")
    assert tick.ask_price == Price.from_str("0.520")

    cached = harness.client._cache.quote_tick(tick.instrument_id)
    assert cached is not None
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_documented_market_data_frame_routes_by_nested_market_slug() -> None:
    """The committed docs put the slug under marketData.marketSlug, not top-level."""
    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver(
        {
            "requestId": "req-1",
            "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
            "marketData": {
                "marketSlug": SLUG,
                "bids": [{"px": {"value": "0.470", "currency": "USD"}, "qty": "10"}],
                "offers": [{"px": {"value": "0.520", "currency": "USD"}, "qty": "10"}],
                "transactTime": "2026-08-25T19:16:06Z",
            },
        }
    )

    assert len(harness.published) == 1
    assert harness.client.frames_missing_routing_key == 0
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_frame_for_an_unknown_slug_is_dropped_without_raising() -> None:
    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver({MARKET_SLUG_KEY: "not-a-loaded-slug", "bid": "0.1", "ask": "0.2"})

    assert harness.published == []
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_inbound_frame_diagnostics_capture_every_frame_class_and_structure() -> None:
    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver({"subscribed": {"requestId": "req-1"}})
    harness.feed.deliver({"heartbeat": {"serverTime": "2026-08-25T19:16:07Z"}})
    harness.feed.deliver(
        {
            "requestId": "req-1",
            "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
            "marketData": {
                "marketSlug": SLUG,
                "bids": [{"px": {"value": "0.470", "currency": "USD"}, "qty": "10"}],
                "offers": [{"px": {"value": "0.520", "currency": "USD"}, "qty": "10"}],
            },
        }
    )

    diagnostics = harness.client.frame_diagnostics
    assert [diagnostic.frame_class for diagnostic in diagnostics] == [
        "acknowledgement",
        "heartbeat",
        "market_data",
    ]
    assert diagnostics[2].keys == ("marketData", "requestId", "subscriptionType")
    assert "marketData.marketSlug" in diagnostics[2].structure_paths
    assert diagnostics[2].safe_values["subscriptionType"] == "SUBSCRIPTION_TYPE_MARKET_DATA"
    assert diagnostics[2].safe_values["marketData.marketSlug"] == SLUG
    assert frame_class_counts(diagnostics) == {
        "acknowledgement": 1,
        "heartbeat": 1,
        "market_data": 1,
    }
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_frame_diagnostics_ring_buffer_retains_only_the_latest_frames() -> None:
    """An unbounded list here leaked ~1 GB/h on the live node (2026-09-05).

    Feeding far more frames than the cap must retain exactly
    ``FRAME_DIAGNOSTICS_CAPACITY`` entries, and they must be the LAST frames
    seen (oldest evicted first), not an arbitrary subset.
    """
    harness = build_harness()
    await harness.client._connect()

    frame_count = 10_000
    for seq in range(frame_count):
        harness.feed.deliver({"heartbeat": {"seq": seq}})

    diagnostics = harness.client.frame_diagnostics
    assert len(diagnostics) == FRAME_DIAGNOSTICS_CAPACITY
    kept_seqs = [int(diagnostic.safe_values["heartbeat.seq"]) for diagnostic in diagnostics]
    expected_first_seq = frame_count - FRAME_DIAGNOSTICS_CAPACITY
    assert kept_seqs == list(range(expected_first_seq, frame_count))
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_frame_diagnostics_buffer_is_a_bounded_ring_not_an_unbounded_list() -> None:
    """Memory pin, no tracemalloc: assert the maxlen directly rather than
    inferring boundedness from behaviour alone."""
    harness = build_harness()
    await harness.client._connect()

    assert harness.client._frame_diagnostics.maxlen == FRAME_DIAGNOSTICS_CAPACITY

    for seq in range(10_000):
        harness.feed.deliver({"heartbeat": {"seq": seq}})

    assert len(harness.client._frame_diagnostics) == FRAME_DIAGNOSTICS_CAPACITY
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_frame_without_a_market_slug_is_counted_not_silently_ignored() -> None:
    """Subscription acknowledgements share the socket with quotes -- but they
    are still counted, because a wrong :data:`MARKET_SLUG_KEY` guess is
    indistinguishable from an idle market unless something moves.

    The previous version of this test asserted only ``published == []``, which
    passed while the handler returned at ``debug`` level without touching any
    counter. That is exactly the state the docstring claimed was impossible.
    """
    harness = build_harness()
    await harness.client._connect()
    before = harness.client.frames_missing_routing_key

    harness.feed.deliver({"subscribed": {"requestId": "req-1"}})

    assert harness.published == []
    assert harness.client.frames_missing_routing_key == before + 1
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_quote_shaped_frame_missing_the_routing_key_increments_the_counter() -> None:
    """The wrong-key-guess scenario, end to end.

    ``MARKET_SLUG_KEY`` is an UNRESOLVED venue fact. If the guess is wrong,
    EVERY quote frame lands here. The counter is the only thing that
    distinguishes "wrong key" from "quiet market".
    """
    harness = build_harness()
    await harness.client._connect()

    for _ in range(3):
        harness.feed.deliver({"market_slug": SLUG, "bid": "0.470", "ask": "0.520"})

    assert harness.published == []
    assert harness.client.frames_missing_routing_key == 3
    assert harness.client.quotes_published == 0
    # Not conflated with the unroutable/unparseable counter.
    assert harness.client.dropped_frames == 0
    await harness.client._disconnect()


def test_the_missing_routing_key_warning_fires_first_then_rate_limits() -> None:
    """Visible within ONE frame, then bounded.

    ``Component._log`` is ``cdef readonly`` (``common/component.pxd:226``) so
    the logger cannot be substituted; the rate-limit policy is therefore a
    pure function and is tested as one.
    """
    n = MISSING_ROUTING_KEY_WARN_EVERY
    assert should_warn_at_count(1) is True
    assert should_warn_at_count(2) is False
    assert should_warn_at_count(n - 1) is False
    assert should_warn_at_count(n) is True
    assert should_warn_at_count(n + 1) is False
    assert should_warn_at_count(2 * n) is True
    assert should_warn_at_count(0) is False


def test_the_missing_routing_key_notice_is_logged_at_warning_not_debug() -> None:
    """The finding was that this path logged at ``debug``. Pin the level.

    Asserted on the AST of the shipped method because the logger itself is not
    interceptable. A regression to ``debug`` -- the exact defect -- fails here.
    """
    source = (REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "data.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_note_missing_routing_key"
    )
    levels = {
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_log"
    }
    assert levels == {"warning"}


@pytest.mark.asyncio
async def test_the_missing_routing_key_handler_returns_without_publishing() -> None:
    """Counting must not turn an acknowledgement into a quote or a drop."""
    harness = build_harness()
    await harness.client._connect()

    for _ in range(MISSING_ROUTING_KEY_WARN_EVERY + 1):
        harness.feed.deliver({"subscribed": {"requestId": "req-1"}})

    assert harness.published == []
    assert harness.client.dropped_frames == 0
    assert harness.client.frames_missing_routing_key == MISSING_ROUTING_KEY_WARN_EVERY + 1
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_delivered_quote_increments_the_published_counter() -> None:
    """The denominator of the alert: missing-key frames matter when quotes are 0."""
    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver({MARKET_SLUG_KEY: SLUG, "bid": "0.470", "ask": "0.520"})

    assert harness.client.quotes_published == 1
    assert harness.client.frames_missing_routing_key == 0
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_malformed_json_frame_is_dropped_without_raising() -> None:
    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver_raw(b"{not json")

    assert harness.published == []
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_parser_failure_drops_the_frame_and_keeps_the_feed_alive() -> None:
    harness = build_harness(quote_parser=raising_quote_parser)
    await harness.client._connect()

    harness.feed.deliver({MARKET_SLUG_KEY: SLUG, "bid": "0.470", "ask": "0.520"})

    assert harness.published == []
    # The frame is dropped; the socket is untouched and stays subscribed.
    assert harness.feed.is_connected is True
    assert SLUG in harness.feed.subscriptions
    await harness.client._disconnect()


# ---------------------------------------------------------------------------
# Operability: fail-closed safe mode on feed loss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fatal_feed_degradation_enters_safe_mode_and_marks_the_client_disconnected() -> None:
    harness = build_harness()
    harness.client._feed_watch_interval_secs = 0.01
    await harness.client._connect()
    harness.client._set_connected(True)
    assert harness.client.is_safe_mode is False

    harness.feed.degrade_fatally()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if harness.client.is_safe_mode:
            break

    assert harness.client.is_safe_mode is True
    assert harness.client.is_connected is False
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_silent_subscription_never_enters_safe_mode() -> None:
    """The other half of the same watchdog, running against a LIVE socket.

    Exercised through the real `_watch_feed` task rather than a direct
    `sample_feed_health` call, because the task is what runs at 05:00Z: an
    unconfirmed slug must be reported and the loop must keep going.
    """
    harness = build_harness()
    harness.client._feed_watch_interval_secs = 0.01
    await harness.client._connect()
    harness.client._set_connected(True)

    harness.feed.go_silent("kxhighny-26aug31-b70")
    for _ in range(100):
        await asyncio.sleep(0.01)
        if harness.client.silent_subscription_alerts:
            break

    assert harness.client.silent_subscription_alerts == 1, "reported"
    assert harness.client.is_safe_mode is False, "and never fatal"
    assert harness.client.is_connected is True
    watchdog = harness.client._feed_watchdog
    assert watchdog is not None and not watchdog.done(), "the watchdog keeps sampling"
    await harness.client._disconnect()


# ---------------------------------------------------------------------------
# Static contracts
# ---------------------------------------------------------------------------


def _data_module_tree() -> ast.Module:
    import breezy.adapters.polymarket_us.data as data_module

    source = Path(data_module.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def test_data_module_performs_no_blocking_io() -> None:
    """``env.py``'s credential read is blocking; it must never run on the loop."""
    banned_names = {"open", "input"}
    banned_attrs = {"sleep", "read_text", "read_bytes", "stat", "fstat", "urlopen"}
    tree = _data_module_tree()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in banned_names:
            offenders.append(f"{func.id} at line {node.lineno}")
        if isinstance(func, ast.Attribute) and func.attr in banned_attrs:
            # asyncio.sleep is the one non-blocking member of that name.
            value = func.value
            if not (isinstance(value, ast.Name) and value.id == "asyncio"):
                offenders.append(f".{func.attr} at line {node.lineno}")
    assert offenders == []


def test_data_module_does_not_import_the_credential_loader() -> None:
    """Credentials are resolved in the factory, never by the data client."""
    tree = _data_module_tree()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    assert "breezy.adapters.polymarket_us.env" not in modules
    assert "breezy.adapters.polymarket_us.credentials" not in modules


def test_no_optional_base_method_is_overridden_only_to_raise() -> None:
    """The base already raises, and ``_on_task_completed`` swallows it."""
    tree = _data_module_tree()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if not node.name.startswith(("_subscribe", "_unsubscribe", "_request")):
            continue
        body = [stmt for stmt in node.body if not isinstance(stmt, ast.Expr)]
        if len(body) == 1 and isinstance(body[0], ast.Raise):
            offenders.append(node.name)
    assert offenders == []


# ---------------------------------------------------------------------------
# G-19 B2: the reload cadence is derived, not recited by an operator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_uses_the_explicit_reload_override_when_one_is_configured() -> None:
    """The env var survives as an OPTIONAL override (staging, test double)."""
    harness = build_harness(config=make_config(instrument_reload_interval_mins=5))

    assert harness.client._next_reload_delay_secs() == 5 * 60


@pytest.mark.asyncio
async def test_client_derives_the_reload_delay_from_the_discovered_market_set() -> None:
    """With no override, the cadence comes from the venue's own boundaries."""
    now_ns = LiveClock().timestamp_ns()
    boundary_ns = now_ns + 3 * 3600 * 1_000_000_000
    harness = build_harness(
        config=make_config(instrument_reload_interval_mins=None),
        instruments=[make_instrument(SLUG, activation_ns=now_ns, expiration_ns=boundary_ns)],
    )
    await harness.client._instrument_provider.initialize()

    delay = harness.client._next_reload_delay_secs()

    assert DISCOVERY_RELOAD_FLOOR_SECS < delay <= 3 * 3600

    await harness.client._instrument_provider.initialize()


@pytest.mark.asyncio
async def test_connect_schedules_the_reload_task_without_any_configured_interval() -> None:
    """The lifecycle still spawns the native reload task with no operator input."""
    now_ns = LiveClock().timestamp_ns()
    harness = build_harness(
        config=make_config(instrument_reload_interval_mins=None),
        instruments=[
            make_instrument(
                SLUG,
                activation_ns=now_ns,
                expiration_ns=now_ns + 3 * 3600 * 1_000_000_000,
            )
        ],
    )
    await harness.client._connect()
    try:
        task = harness.client._update_instruments_task
        assert task is not None and not task.done()
    finally:
        await harness.client._disconnect()


# ---------------------------------------------------------------------------
# TRADE frames -> native TradeTick, through the DataEngine
# ---------------------------------------------------------------------------
#
# Shape per ``docs/evidence/venue/polymarket_us/docs_snapshots/
# api-reference_websocket_markets_2026-08-25.md:114-138``. The test instrument
# has a 0.001 tick and a size increment of 1, so the values are adjusted to it.


def documented_trade_frame(slug: str = SLUG, **trade_overrides: Any) -> dict[str, Any]:
    trade: dict[str, Any] = {
        "marketSlug": slug,
        "price": {"value": "0.55", "currency": "USD"},
        "quantity": {"value": "3", "currency": "USD"},
        "tradeTime": "2026-08-25T00:06:58.830425365Z",
        "maker": {"side": "ORDER_SIDE_BUY", "intent": "ORDER_INTENT_BUY_LONG"},
        "taker": {"side": "ORDER_SIDE_SELL", "intent": "ORDER_INTENT_SELL_LONG"},
    }
    trade.update(trade_overrides)
    return {
        "requestId": "trade-sub-1",
        "subscriptionType": "SUBSCRIPTION_TYPE_TRADE",
        "trade": trade,
    }


def _capture_trades(harness: Harness) -> list[Any]:
    trades: list[Any] = []
    harness.client._msgbus.subscribe(topic="data.trades.*", handler=trades.append)
    return trades


@pytest.mark.asyncio
async def test_a_documented_trade_frame_reaches_the_data_engine_as_a_trade_tick() -> None:
    from nautilus_trader.model.data import TradeTick
    from nautilus_trader.model.enums import AggressorSide

    harness = build_harness()
    trades = _capture_trades(harness)
    await harness.client._connect()

    harness.feed.deliver(documented_trade_frame())

    assert len(trades) == 1
    tick = trades[0]
    assert isinstance(tick, TradeTick)
    assert tick.instrument_id == InstrumentId(Symbol(SLUG), POLYMARKET_US_VENUE)
    assert tick.price == Price.from_str("0.550")
    assert tick.size == Quantity.from_str("3")
    assert tick.aggressor_side == AggressorSide.SELLER
    from breezy.adapters.polymarket_us.parsing import parse_rfc3339_nanos

    assert tick.ts_event == parse_rfc3339_nanos(
        "2026-08-25T00:06:58.830425365Z", field="tradeTime"
    )
    assert harness.client.trades_published == 1
    assert harness.client.dropped_frames == 0
    # Published on the YES instrument only; nothing is synthesised for a NO leg.
    assert harness.published == []
    # The engine cached it exactly as it caches quotes.
    assert harness.client._cache.trade_tick(tick.instrument_id) is not None
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_malformed_trade_frame_is_counted_and_dropped_never_published() -> None:
    harness = build_harness()
    trades = _capture_trades(harness)
    await harness.client._connect()

    frame = documented_trade_frame()
    del frame["trade"]["price"]
    harness.feed.deliver(frame)
    harness.feed.deliver(documented_trade_frame(quantity={"value": "-1", "currency": "USD"}))

    assert trades == []
    assert harness.client.trades_published == 0
    assert harness.client.trade_parse_failures == 2
    assert harness.client.dropped_frames == 2
    assert harness.feed.is_connected is True
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_unknown_trade_keys_are_recorded_bounded_and_the_print_still_publishes() -> None:
    """Drift discipline, mirroring the depth path: additive schema drift is
    recorded (once per key, bounded) and never fatal."""
    from breezy.adapters.polymarket_us.data import TRADE_UNKNOWN_KEY_CAPACITY

    harness = build_harness()
    trades = _capture_trades(harness)
    await harness.client._connect()

    harness.feed.deliver(documented_trade_frame(venueSeq=1, feeCoefficient="0.06"))
    for i in range(TRADE_UNKNOWN_KEY_CAPACITY + 50):
        # Distinct tradeTime per frame: identical venue fields would (rightly)
        # be suppressed as a replay, which is not what this test measures.
        harness.feed.deliver(
            documented_trade_frame(
                tradeTime=f"2026-08-25T00:00:01.{i:09d}Z", **{f"drift{i}": i}
            )
        )

    assert len(trades) == TRADE_UNKNOWN_KEY_CAPACITY + 51
    recorded = harness.client.trade_unknown_keys
    assert {"venueSeq", "feeCoefficient"} <= set(recorded)
    assert len(recorded) == TRADE_UNKNOWN_KEY_CAPACITY
    assert harness.client.trade_frames_with_unknown_keys == TRADE_UNKNOWN_KEY_CAPACITY + 51
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_taker_side_and_intent_pairs_are_tallied_in_a_bounded_table() -> None:
    """``TradeTick`` has no field for the venue's ``intent`` (the NO-leg
    discriminator), so the client keeps a BOUNDED tally of observed
    ``taker.side / taker.intent`` pairs -- the only evidence about the NO-leg
    print population the tape can carry without a raw sidecar."""
    from breezy.adapters.polymarket_us.data import TRADE_TAKER_TALLY_CAPACITY

    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver(documented_trade_frame())
    harness.feed.deliver(documented_trade_frame(tradeTime="2026-08-25T00:07:00Z"))
    no_leg = {"side": "ORDER_SIDE_SELL", "intent": "ORDER_INTENT_BUY_SHORT"}
    # Own tradeTime: `intent` is not part of the derived id, so an otherwise
    # identical frame would be suppressed as a replay.
    harness.feed.deliver(documented_trade_frame(tradeTime="2026-08-25T00:08:00Z", taker=no_leg))
    for i in range(TRADE_TAKER_TALLY_CAPACITY + 20):
        harness.feed.deliver(
            documented_trade_frame(
                tradeTime=f"2026-08-25T00:00:01.{i:09d}Z",
                taker={"side": f"SIDE_{i}", "intent": f"INTENT_{i}"},
            )
        )

    tally = harness.client.trade_taker_tally
    assert tally["ORDER_SIDE_SELL/ORDER_INTENT_SELL_LONG"] == 2
    assert tally["ORDER_SIDE_SELL/ORDER_INTENT_BUY_SHORT"] == 1
    assert len(tally) <= TRADE_TAKER_TALLY_CAPACITY + 1  # + the overflow bucket
    assert tally[harness.client.TRADE_TAKER_TALLY_OVERFLOW_KEY] > 0
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_trade_frame_for_an_unknown_slug_is_dropped_without_raising() -> None:
    harness = build_harness()
    trades = _capture_trades(harness)
    await harness.client._connect()

    harness.feed.deliver(documented_trade_frame(slug="tc-temp-mdwhigh-2026-08-25-lt91f"))

    assert trades == []
    assert harness.client.trades_published == 0
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_a_replayed_print_is_published_once_and_counted_as_a_replay_duplicate() -> None:
    """After a reconnect the venue may re-send a print. Its derived id is built
    from venue-only fields, so the replay collides and the client suppresses
    it (bounded per-instrument window) instead of double-counting volume."""
    harness = build_harness()
    trades = _capture_trades(harness)
    await harness.client._connect()

    harness.feed.deliver(documented_trade_frame())
    harness.feed.deliver(documented_trade_frame())
    harness.feed.deliver(documented_trade_frame(price={"value": "0.56", "currency": "USD"}))

    assert len(trades) == 2
    assert harness.client.trades_published == 2
    assert harness.client.trade_replay_duplicates == 1
    assert harness.client.dropped_frames == 0
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_the_replay_dedup_window_is_bounded_per_instrument() -> None:
    from breezy.adapters.polymarket_us.data import TRADE_DEDUP_WINDOW

    harness = build_harness()
    trades = _capture_trades(harness)
    await harness.client._connect()

    first = documented_trade_frame(tradeTime="2026-08-25T00:00:00.000000000Z")
    harness.feed.deliver(first)
    for i in range(TRADE_DEDUP_WINDOW):
        harness.feed.deliver(
            documented_trade_frame(tradeTime=f"2026-08-25T00:00:01.{i:09d}Z")
        )
    harness.feed.deliver(first)  # evicted from the window: published again

    assert len(trades) == TRADE_DEDUP_WINDOW + 2
    assert harness.client.trade_replay_duplicates == 0
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_the_raw_quantity_object_is_kept_verbatim_as_bounded_evidence() -> None:
    """The print-size UNIT is unresolved (contracts vs dollars). The raw
    ``quantity`` object and ``price`` are kept verbatim, bounded, so the first
    live print can be cross-checked against the REST fill for the same trade."""
    from breezy.adapters.polymarket_us.data import TRADE_QUANTITY_EVIDENCE_CAPACITY

    harness = build_harness()
    await harness.client._connect()

    harness.feed.deliver(documented_trade_frame())
    for i in range(TRADE_QUANTITY_EVIDENCE_CAPACITY + 5):
        harness.feed.deliver(
            documented_trade_frame(tradeTime=f"2026-08-25T00:00:01.{i:09d}Z", quantity=str(i + 1))
        )

    evidence = harness.client.trade_quantity_evidence
    assert len(evidence) == TRADE_QUANTITY_EVIDENCE_CAPACITY
    last = evidence[-1]
    assert last.market_slug == SLUG
    assert last.trade_time == f"2026-08-25T00:00:01.{TRADE_QUANTITY_EVIDENCE_CAPACITY + 4:09d}Z"
    assert last.quantity == repr(str(TRADE_QUANTITY_EVIDENCE_CAPACITY + 5))
    assert last.price == repr({"value": "0.55", "currency": "USD"})
    await harness.client._disconnect()
