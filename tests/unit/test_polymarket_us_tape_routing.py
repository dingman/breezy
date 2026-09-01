"""One venue frame in, every unbackfillable record out.

The client used to turn a market-data frame into exactly one ``QuoteTick`` and
throw the rest of the frame away: ten-plus book levels below the top, the
venue's ``state``, and the venue's own ``settlementPx``. Polymarket.us weather
markets have no history, so each of those was a permanent loss per frame.

These tests assert the BEHAVIOUR an analyst depends on -- "the records exist
and carry the venue's values" -- rather than "the client has a method".
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.model.data import (
    InstrumentClose,
    MarkPriceUpdate,
    OrderBookDepth10,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Price
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import (
    CLOCK_OFFSET_SAMPLE_EVERY,
    PolymarketUSDataClient,
    build_data_client,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.tape_records import (
    DepthTruncation,
    QuoteTapeGap,
    VenueClockOffset,
    VenueSettlementSnapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
SLUG = "tc-temp-nychigh-2026-08-25-lt79f"
CLIENT_NAME = "POLYMARKET_US"


def load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


def make_instrument() -> BinaryOption:
    return parse_binary_option(
        load_raw("market_open_510636_by_slug.json"), venue=POLYMARKET_US_VENUE, ts_init=0
    )


class Feed:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self._connected = False
        self._degraded = False
        self._subs: dict[str, str] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    @property
    def subscriptions(self) -> Mapping[str, str]:
        return dict(self._subs)

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        for slug in market_slugs:
            self._subs[slug] = "req-1"

    async def unsubscribe(self, request_id: str) -> None:
        return

    def drop(self) -> None:
        self._connected = False

    def restore(self) -> None:
        self._connected = True

    def deliver(self, payload: Mapping[str, Any]) -> None:
        self.handler(json.dumps(payload).encode())


class Provider(InstrumentProvider):
    def __init__(self, instruments: Sequence[Instrument]) -> None:
        super().__init__(config=InstrumentProviderConfig(load_all=True))
        self._preloaded = list(instruments)

    async def load_all_async(self, filters: dict[str, Any] | None = None) -> None:
        for instrument in self._preloaded:
            self.add(instrument)

    @property
    def market_slugs(self) -> tuple[str, ...]:
        return tuple(str(instrument.id.symbol.value) for instrument in self._preloaded)

    @property
    def active_market_slugs(self) -> tuple[str, ...]:
        return self.market_slugs

    @property
    def resolved_market_reasons(self) -> Mapping[str, str]:
        return {}


class Harness:
    def __init__(self, client: PolymarketUSDataClient, feed: Feed) -> None:
        self.client = client
        self.feed = feed
        self.seen: list[Any] = []

    def of(self, cls: type) -> list[Any]:
        return [item for item in self.seen if isinstance(item, cls)]


@pytest.fixture(name="loop")
def _loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture(name="harness")
def _harness(loop: asyncio.AbstractEventLoop) -> Harness:
    instrument = make_instrument()
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(instrument)
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    feeds: list[Feed] = []

    def feed_factory(handler: Any) -> Feed:
        feed = Feed(handler)
        feeds.append(feed)
        return feed

    client = build_data_client(
        loop=loop,
        name=CLIENT_NAME,
        config=PolymarketUSDataClientConfig(
            # A deliberate test-double origin off the venue domain, declared
            # as such. The allowlist is the point of the field.
            allow_foreign_origin=True,
            api_base_url="https://api.example.invalid",
            gateway_base_url="https://gateway.example.invalid",
            ws_url="wss://api.example.invalid",
            market_slugs=(SLUG,),
            instrument_reload_interval_mins=5,
            user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
            instrument_provider=InstrumentProviderConfig(load_all=True),
        ),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=Provider([instrument]),
        feed_factory=feed_factory,
    )
    engine.register_client(client)
    harness = Harness(client, feeds[0])
    msgbus.subscribe(topic="data.*", handler=harness.seen.append)
    return harness


def market_frame() -> dict[str, Any]:
    return load_raw("book_open_510636.json")


def expired_frame() -> dict[str, Any]:
    frame = load_raw("book_closed_15806.json")
    frame["marketData"]["marketSlug"] = SLUG
    return frame


# ---------------------------------------------------------------------------
# Depth, quote, state and mark from ONE frame
# ---------------------------------------------------------------------------


class TestMarketDataFrameFanOut:
    def test_one_frame_yields_both_a_quote_and_a_ten_level_depth_record(
        self, harness: Harness
    ) -> None:
        harness.feed.deliver(market_frame())

        assert len(harness.of(QuoteTick)) == 1
        depths = harness.of(OrderBookDepth10)
        assert len(depths) == 1
        assert len([o for o in depths[0].bids if o.size > 0]) == 10

    def test_the_depth_record_carries_liquidity_the_quote_cannot(
        self, harness: Harness
    ) -> None:
        """The whole point: level 2+ is what slippage-at-size is computed from."""
        harness.feed.deliver(market_frame())
        depth = harness.of(OrderBookDepth10)[0]

        second_bid = depth.bids[1]
        assert second_bid.size > 0
        assert second_bid.price < depth.bids[0].price

    def test_the_venue_state_is_recorded_verbatim(self, harness: Harness) -> None:
        from nautilus_trader.model.data import InstrumentStatus

        harness.feed.deliver(market_frame())

        statuses = harness.of(InstrumentStatus)
        assert [s.reason for s in statuses] == ["MARKET_STATE_OPEN"]

    def test_the_venue_settlement_price_is_recorded_as_a_mark(
        self, harness: Harness
    ) -> None:
        harness.feed.deliver(market_frame())

        marks = harness.of(MarkPriceUpdate)
        assert [m.value for m in marks] == [Price.from_str("0.490")]

    def test_an_open_market_produces_no_instrument_close(self, harness: Harness) -> None:
        harness.feed.deliver(market_frame())

        assert harness.of(InstrumentClose) == []

    def test_truncation_beyond_ten_levels_is_counted_not_hidden(
        self, harness: Harness
    ) -> None:
        """The capture has 12 bids and 14 offers; 6 levels do not fit.

        An analyst who assumes the tape is the whole book overstates how deep
        the recorded liquidity goes. The counter is what makes that knowable.
        """
        harness.feed.deliver(market_frame())

        assert harness.client.depth_levels_truncated == (12 - 10) + (14 - 10)

    def test_an_unquotable_book_is_counted_without_discarding_the_rest(
        self, harness: Harness
    ) -> None:
        """A book that stops being quotable must be visible, not silent.

        ``QuoteTick`` is two-sided, so an empty bid cannot form a quote and
        the failure is counted. It is deliberately NOT a "dropped frame":
        the frame still carried the ask ladder, the venue's state, and the
        mark price, and those are kept. The distinct counter is what lets
        an operator see a tape that has quietly stopped carrying two-sided
        quotes while still looking busy.
        """
        from nautilus_trader.model.data import InstrumentStatus

        frame = market_frame()
        frame["marketData"]["bids"] = []

        harness.feed.deliver(frame)

        assert harness.of(QuoteTick) == []
        depths = harness.of(OrderBookDepth10)
        assert len(depths) == 1
        assert [order for order in depths[0].bids if order.size > 0] == []
        assert [order for order in depths[0].asks if order.size > 0]
        assert harness.client.quote_parse_failures == 1
        assert harness.client.dropped_frames == 0
        assert len(harness.of(InstrumentStatus)) == 1
        assert len(harness.of(MarkPriceUpdate)) == 1


class TestExpiredMarketFrame:
    def test_an_expired_market_publishes_the_venues_terminal_settlement(
        self, harness: Harness
    ) -> None:
        """Venue REST may not retain this once the market ages out."""
        harness.feed.deliver(expired_frame())

        closes = harness.of(InstrumentClose)
        assert [c.close_price for c in closes] == [Price.from_str("1.000")]

    def test_an_expired_market_with_an_empty_book_still_yields_its_settlement(
        self, harness: Harness
    ) -> None:
        """The book is `[]` at expiry, so a quote is impossible -- the close is not.

        Dropping the whole frame because it has no quotable book would discard
        the single most valuable record the venue ever sends.
        """
        harness.feed.deliver(expired_frame())

        assert harness.of(QuoteTick) == []
        assert len(harness.of(InstrumentClose)) == 1


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------


class TestTradeFrame:
    def frame(self) -> dict[str, Any]:
        return {
            "trade": {
                "marketSlug": SLUG,
                "px": {"value": "0.5300", "currency": "USD"},
                "qty": "15.6100",
                "transactTime": "2026-08-25T00:06:58.830425365Z",
                "tradeId": "trd-0001",
                "takerSide": "SIDE_BUY",
            }
        }

    def test_an_executed_print_is_published_as_a_trade_tick(
        self, harness: Harness
    ) -> None:
        harness.feed.deliver(self.frame())

        trades = harness.of(TradeTick)
        assert len(trades) == 1
        assert trades[0].price == Price.from_str("0.530")
        assert trades[0].trade_id.value == "trd-0001"

    def test_an_unparseable_trade_is_dropped_and_counted_never_fabricated(
        self, harness: Harness
    ) -> None:
        frame = self.frame()
        del frame["trade"]["px"]

        harness.feed.deliver(frame)

        assert harness.of(TradeTick) == []
        assert harness.client.dropped_frames == 1


# ---------------------------------------------------------------------------
# Gap and clock-offset series reach the bus
# ---------------------------------------------------------------------------


class TestOperationalSeries:
    def test_a_gap_is_published_as_a_record_for_every_subscribed_instrument(
        self, harness: Harness
    ) -> None:
        harness.feed.restore()
        harness.client.sample_feed_health()
        harness.feed.drop()
        harness.client.sample_feed_health()

        opened = harness.of(QuoteTapeGap)
        assert len(opened) == 1
        assert opened[0].resolved is False
        assert opened[0].instrument_id == make_instrument().id

    def test_the_closing_record_states_the_resolved_interval(
        self, harness: Harness
    ) -> None:
        harness.feed.restore()
        harness.client.sample_feed_health()
        harness.feed.drop()
        harness.client.sample_feed_health()
        harness.feed.restore()
        harness.client.sample_feed_health()

        closed = [gap for gap in harness.of(QuoteTapeGap) if gap.resolved]
        assert len(closed) == 1
        assert closed[0].ended_ns >= closed[0].started_ns
        assert closed[0].duration_ns is not None

    def test_the_clock_offset_series_is_published_from_frames_already_on_the_wire(
        self, harness: Harness
    ) -> None:
        """No new egress: the offset is ts_init minus the venue's transactTime."""
        for _ in range(CLOCK_OFFSET_SAMPLE_EVERY):
            harness.feed.deliver(market_frame())

        offsets = harness.of(VenueClockOffset)
        assert len(offsets) == 1
        assert offsets[0].source == "ws-transact-time"
        assert offsets[0].samples == CLOCK_OFFSET_SAMPLE_EVERY

    def test_the_offset_is_signed_and_reflects_the_measured_difference(
        self, harness: Harness
    ) -> None:
        for _ in range(CLOCK_OFFSET_SAMPLE_EVERY):
            harness.feed.deliver(market_frame())

        offset = harness.of(VenueClockOffset)[0]
        # The capture's transactTime is 2026-08-25; the test host clock is
        # later, so the host reads AHEAD of that frame. The sign is what is
        # being pinned, not the magnitude.
        assert offset.offset_ns > 0


# ---------------------------------------------------------------------------
# Per-snapshot provenance: truncation and settlement method
# ---------------------------------------------------------------------------


class TestPerSnapshotProvenance:
    def test_a_truncated_depth_snapshot_carries_its_own_truncation_record(
        self, harness: Harness
    ) -> None:
        """A running counter cannot answer "was THIS snapshot truncated?".

        An analyst joining a depth snapshot to a crossing event has only the
        archive; runtime logs may never reach the study. The capture has 12
        bids and 14 offers, so six levels do not fit.
        """
        harness.feed.deliver(market_frame())

        records = harness.of(DepthTruncation)
        assert len(records) == 1
        assert records[0].bid_levels_seen == 12
        assert records[0].ask_levels_seen == 14
        assert records[0].levels_dropped == 6

    def test_the_truncation_record_joins_the_depth_record_exactly(
        self, harness: Harness
    ) -> None:
        """Same instrument and same ts_event: an exact join, not nearest-neighbour."""
        harness.feed.deliver(market_frame())

        depth = harness.of(OrderBookDepth10)[0]
        truncation = harness.of(DepthTruncation)[0]

        assert truncation.instrument_id == depth.instrument_id
        assert truncation.ts_event == depth.ts_event

    def test_an_untruncated_snapshot_emits_no_truncation_record(
        self, harness: Harness
    ) -> None:
        """Absence of a record is the (much more common) "nothing was dropped"."""
        frame = market_frame()
        frame["marketData"]["bids"] = frame["marketData"]["bids"][:4]
        frame["marketData"]["offers"] = frame["marketData"]["offers"][:4]

        harness.feed.deliver(frame)

        assert harness.of(OrderBookDepth10) != []
        assert harness.of(DepthTruncation) == []

    def test_the_venue_settlement_method_reaches_the_tape_verbatim(
        self, harness: Harness
    ) -> None:
        harness.feed.deliver(market_frame())

        snapshots = harness.of(VenueSettlementSnapshot)
        assert len(snapshots) == 1
        assert snapshots[0].method == "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        assert snapshots[0].state == "MARKET_STATE_OPEN"
        assert snapshots[0].is_terminal is False

    def test_an_expired_but_not_yet_terminal_frame_records_without_settling(
        self, harness: Harness
    ) -> None:
        """The refusal is visible on disk instead of being a silence."""
        frame = expired_frame()
        frame["marketData"]["stats"]["settlementPriceCalculationMethod"] = (
            "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        )

        harness.feed.deliver(frame)

        assert harness.of(InstrumentClose) == []
        snapshots = harness.of(VenueSettlementSnapshot)
        assert len(snapshots) == 1
        assert snapshots[0].state == "MARKET_STATE_EXPIRED"
        assert snapshots[0].is_terminal is False


class TestExpiredButNotTerminalIsCounted:
    """Surface the "expired, but the venue never marked it TIER_1" case.

    The record already lands on disk (``VenueSettlementSnapshot`` with
    ``is_terminal=False``), but finding it requires an analyst to know to scan
    for it. A counter makes it visible from the running process. Deliberately a
    counter and nothing more -- no alerting infrastructure.
    """

    def test_an_expired_frame_without_a_terminal_method_is_counted(
        self, harness: Harness
    ) -> None:
        frame = expired_frame()
        frame["marketData"]["stats"]["settlementPriceCalculationMethod"] = (
            "SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_2"
        )

        harness.feed.deliver(frame)

        assert harness.client.expired_without_terminal_settlement == 1
        assert harness.of(InstrumentClose) == []

    def test_a_terminal_expired_frame_is_not_counted(self, harness: Harness) -> None:
        harness.feed.deliver(expired_frame())

        assert harness.client.expired_without_terminal_settlement == 0
        assert len(harness.of(InstrumentClose)) == 1

    def test_an_open_market_is_never_counted(self, harness: Harness) -> None:
        harness.feed.deliver(market_frame())

        assert harness.client.expired_without_terminal_settlement == 0
