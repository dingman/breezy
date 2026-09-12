"""Reconnect gaps in the quote tape must be OBSERVABLE, never implied away.

The recorder writes whatever quotes arrive. It cannot write quotes that never
arrived, and quotes that occur while the socket is down are lost permanently --
Polymarket.us weather markets cannot be backfilled. The socket's supervisor
reconnects and replays subscriptions, so the tape RESUMES; nothing in the
resulting parquet says it ever stopped.

That is the dishonest failure mode this file exists to prevent: a continuous
looking archive with silent holes in it, analysed later as if it were
continuous. The client therefore counts observed disconnect->reconnect
transitions and the wall-clock seconds spent disconnected, and logs each one
at ERROR.

The counters are DELIBERATELY a lower bound and the code says so: a gap shorter
than the watchdog's sample interval can pass unobserved, and a gap in progress
when the process dies is never counted at all. A lower bound that is loudly a
lower bound beats a number that pretends to be exact.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus, TestClock
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import PolymarketUSDataClient, build_data_client
from breezy.adapters.polymarket_us.symbology import slug_to_instrument_id
from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap
from breezy.adapters.polymarket_us.websocket import SilentSubscriptionWarning
from tests.unit.test_polymarket_us_data import OTHER_SLUG, SLUG, make_instrument

CLIENT_NAME = "POLYMARKET_US"


class ControllableFeed:
    """A markets feed whose connected/degraded state the test drives directly.

    Models the REAL split the socket exposes: ``is_degraded`` is the union
    ("not fully healthy"), ``is_fatally_degraded`` the narrow subset the
    process may be stopped over. A double that collapsed the two would
    validate exactly the confusion this suite now pins.
    """

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self._connected = False
        self._fatally_degraded = False
        self._silent: list[SilentSubscriptionWarning] = []
        self._subscriptions: dict[str, str] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_degraded(self) -> bool:
        return self._fatally_degraded or bool(self._silent)

    @property
    def is_fatally_degraded(self) -> bool:
        return self._fatally_degraded

    @property
    def silent_subscriptions(self) -> tuple[SilentSubscriptionWarning, ...]:
        return tuple(self._silent)

    @property
    def subscriptions(self) -> Mapping[str, str]:
        return dict(self._subscriptions)

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        for slug in market_slugs:
            self._subscriptions[slug] = "req-1"

    async def unsubscribe(self, request_id: str) -> None:
        return

    # -- test controls ----------------------------------------------------

    def drop(self) -> None:
        """The socket lost its connection; the supervisor is retrying."""
        self._connected = False

    def restore(self) -> None:
        """The supervisor reconnected and replayed subscriptions."""
        self._connected = True

    def give_up(self) -> None:
        """Alias for the original fatal producer: reconnection abandoned."""
        self.exhaust_reconnects()

    def exhaust_reconnects(self) -> None:
        """FATAL producer 1: the supervisor spent its retry budget and gave up."""
        self._connected = False
        self._fatally_degraded = True

    def supervisor_died(self) -> None:
        """FATAL producer 2: the supervisor raised, so nothing reconnects now.

        The socket can still LOOK connected here -- that is precisely why this
        producer was invisible before it set a flag of its own.
        """
        self._fatally_degraded = True

    def go_silent(self, slug: str, after_secs: float = 60.0) -> None:
        """NON-FATAL producer 3: one subscribed slug produced no inbound frame.

        The socket is alive and every other slug keeps flowing. At 05:00Z
        roughly 60 thin overnight weather markets are subscribed, so this is
        an EXPECTED, recurring observation -- never a reason to end the run.
        """
        self._silent.append(SilentSubscriptionWarning(slug=slug, subscribed_after_secs=after_secs))


class _ShardStatus:
    """Mirrors ``websocket.ShardStatus`` structurally -- data.py duck-types this."""

    def __init__(self, label: str, connected: bool, subscribed_slugs: Sequence[str]) -> None:
        self.label = label
        self.connected = connected
        self.subscribed_slugs = tuple(subscribed_slugs)


class ShardedControllableFeed:
    """A markets feed exposing PER-SHARD connectivity, driven directly by the test.

    Models the real gap: :attr:`is_connected` rolls the shards up with
    ``all()`` (matching ``PolymarketUSMarketsWebSocketPool``), while
    :attr:`shard_status` is the optional, duck-typed capability the data
    client's watchdog must use to scope gap accounting to the shard that
    actually dropped.
    """

    def __init__(self, handler: Any, shard_slugs: Mapping[str, Sequence[str]]) -> None:
        self.handler = handler
        self._slugs: dict[str, tuple[str, ...]] = {
            label: tuple(slugs) for label, slugs in shard_slugs.items()
        }
        self._connected: dict[str, bool] = dict.fromkeys(self._slugs, False)
        self._fatally_degraded = False
        self._silent: list[SilentSubscriptionWarning] = []

    @property
    def is_connected(self) -> bool:
        return all(self._connected.values())

    @property
    def is_degraded(self) -> bool:
        return self._fatally_degraded or bool(self._silent)

    @property
    def is_fatally_degraded(self) -> bool:
        return self._fatally_degraded

    @property
    def silent_subscriptions(self) -> tuple[SilentSubscriptionWarning, ...]:
        return tuple(self._silent)

    @property
    def subscriptions(self) -> Mapping[str, str]:
        merged: dict[str, str] = {}
        for label, slugs in self._slugs.items():
            for slug in slugs:
                merged[slug] = f"req-{label}"
        return merged

    @property
    def shard_status(self) -> tuple[_ShardStatus, ...]:
        return tuple(
            _ShardStatus(label=label, connected=self._connected[label], subscribed_slugs=slugs)
            for label, slugs in self._slugs.items()
        )

    async def connect(self) -> None:
        for label in self._connected:
            self._connected[label] = True

    async def close(self) -> None:
        for label in self._connected:
            self._connected[label] = False

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        return

    async def unsubscribe(self, request_id: str) -> None:
        return

    # -- test controls ------------------------------------------------------

    def drop_shard(self, label: str) -> None:
        self._connected[label] = False

    def restore_shard(self, label: str) -> None:
        self._connected[label] = True

    def shard_status_labels(self) -> tuple[str, ...]:
        return tuple(self._slugs)


class FakeProvider(InstrumentProvider):
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


def build_client(
    loop: asyncio.AbstractEventLoop,
) -> tuple[PolymarketUSDataClient, ControllableFeed]:
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    feeds: list[ControllableFeed] = []

    def feed_factory(handler: Any) -> ControllableFeed:
        feed = ControllableFeed(handler)
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
        instrument_provider=FakeProvider([make_instrument(SLUG)]),
        feed_factory=feed_factory,
        quote_parser=lambda payload, *, instrument, ts_init: None,  # never called here
    )
    engine.register_client(client)
    return client, feeds[0]


def build_sharded_client(
    loop: asyncio.AbstractEventLoop,
) -> tuple[PolymarketUSDataClient, ShardedControllableFeed]:
    """A client backed by a two-shard feed: ``shard-0``/SLUG, ``shard-1``/OTHER_SLUG."""
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    feeds: list[ShardedControllableFeed] = []

    def feed_factory(handler: Any) -> ShardedControllableFeed:
        feed = ShardedControllableFeed(
            handler, shard_slugs={"shard-0": (SLUG,), "shard-1": (OTHER_SLUG,)}
        )
        feeds.append(feed)
        return feed

    client = build_data_client(
        loop=loop,
        name=CLIENT_NAME,
        config=PolymarketUSDataClientConfig(
            allow_foreign_origin=True,
            api_base_url="https://api.example.invalid",
            gateway_base_url="https://gateway.example.invalid",
            ws_url="wss://api.example.invalid",
            market_slugs=(SLUG, OTHER_SLUG),
            instrument_reload_interval_mins=5,
            user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
            instrument_provider=InstrumentProviderConfig(load_all=True),
        ),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=FakeProvider([make_instrument(SLUG), make_instrument(OTHER_SLUG)]),
        feed_factory=feed_factory,
        quote_parser=lambda payload, *, instrument, ts_init: None,  # never called here
    )
    engine.register_client(client)
    return client, feeds[0]


def build_sharded_client_with_recorded_gaps(
    loop: asyncio.AbstractEventLoop, clock: TestClock
) -> tuple[PolymarketUSDataClient, ShardedControllableFeed, list[QuoteTapeGap]]:
    """As :func:`build_sharded_client`, plus an INJECTED clock and every
    published ``QuoteTapeGap`` captured in arrival order.

    Mirrors the capture pattern already pinned in
    ``test_polymarket_us_tape_routing.py::Harness``: ``_publish_custom``
    republishes the UNWRAPPED record on ``data.*``
    (``PolymarketUSDataClient._publish_custom`` docstring), so subscribing
    there is the same seam production code is observed through, not a
    monkeypatch of a private method.
    """
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    feeds: list[ShardedControllableFeed] = []

    def feed_factory(handler: Any) -> ShardedControllableFeed:
        feed = ShardedControllableFeed(
            handler, shard_slugs={"shard-0": (SLUG,), "shard-1": (OTHER_SLUG,)}
        )
        feeds.append(feed)
        return feed

    client = build_data_client(
        loop=loop,
        name=CLIENT_NAME,
        config=PolymarketUSDataClientConfig(
            allow_foreign_origin=True,
            api_base_url="https://api.example.invalid",
            gateway_base_url="https://gateway.example.invalid",
            ws_url="wss://api.example.invalid",
            market_slugs=(SLUG, OTHER_SLUG),
            instrument_reload_interval_mins=5,
            user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
            instrument_provider=InstrumentProviderConfig(load_all=True),
        ),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=FakeProvider([make_instrument(SLUG), make_instrument(OTHER_SLUG)]),
        feed_factory=feed_factory,
        quote_parser=lambda payload, *, instrument, ts_init: None,  # never called here
    )
    engine.register_client(client)
    gap_records: list[QuoteTapeGap] = []
    msgbus.subscribe(
        topic="data.*",
        handler=lambda record: gap_records.append(record)
        if isinstance(record, QuoteTapeGap)
        else None,
    )
    return client, feeds[0], gap_records


@pytest.fixture(name="loop")
def _loop() -> Iterator[asyncio.AbstractEventLoop]:
    """A fresh loop per test.

    ``asyncio.get_event_loop()`` raises once any earlier test has set and
    closed a loop policy state, so the client's loop is created and disposed
    explicitly here. Nothing is ever run on it: these tests drive
    ``sample_feed_health`` synchronously.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


def test_a_healthy_feed_reports_no_tape_gaps(loop: asyncio.AbstractEventLoop) -> None:
    client, feed = build_client(loop)
    feed.restore()

    for _ in range(5):
        client.sample_feed_health()

    assert client.tape_gaps == 0
    assert client.tape_gap_seconds_total == pytest.approx(0.0)


def test_a_disconnect_then_reconnect_is_counted_as_one_tape_gap(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """The behaviour that matters: the archive knows it has a hole in it."""
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()

    feed.drop()
    client.sample_feed_health()
    client.sample_feed_health()
    # Counted on the FALLING edge, not on recovery: a recorder that has been
    # down for six hours must not report zero gaps. Repeated samples while
    # down must not inflate the count either.
    assert client.tape_gaps == 1
    assert client.is_tape_gap_open is True

    feed.restore()
    client.sample_feed_health()

    assert client.tape_gaps == 1
    assert client.tape_gap_seconds_total > 0.0


def test_repeated_drops_accumulate_rather_than_overwrite(loop: asyncio.AbstractEventLoop) -> None:
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()

    for _ in range(3):
        feed.drop()
        client.sample_feed_health()
        feed.restore()
        client.sample_feed_health()

    assert client.tape_gaps == 3


def test_an_open_gap_is_visible_before_the_feed_returns(loop: asyncio.AbstractEventLoop) -> None:
    """An operator must not have to wait for recovery to see the outage."""
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()

    feed.drop()
    client.sample_feed_health()

    assert client.is_tape_gap_open is True

    feed.restore()
    client.sample_feed_health()

    assert client.is_tape_gap_open is False


def test_entering_safe_mode_marks_the_client_disconnected_at_once(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Fail closed: once the socket gives up, no quotes are coming.

    Safe mode and the disconnect are immediate, on the FIRST fatal sample.
    The watchdog deliberately does NOT stop there -- `shutdown_system` only
    publishes a command the kernel may drop, and this loop is the only thing
    left that could ask again. It stops once the request budget is spent
    (`test_the_watchdog_keeps_re_checking_until_its_request_budget_is_spent`).
    """
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()

    feed.give_up()
    keep_going = client.sample_feed_health()

    assert client.is_safe_mode is True
    assert client.is_connected is False
    assert keep_going is True, (
        "the only re-checker must not end while the shutdown is unconfirmed"
    )


def test_a_gap_that_ends_in_safe_mode_is_still_counted(loop: asyncio.AbstractEventLoop) -> None:
    """The last, permanent hole is the one most likely to be missed."""
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()

    feed.give_up()
    client.sample_feed_health()

    assert client.is_tape_gap_open is True
    assert client.tape_gaps == 1, "an unterminated gap still counts as a gap"


# ---------------------------------------------------------------------------
# Shard-scoped gap accounting (PolymarketUSMarketsWebSocketPool)
# ---------------------------------------------------------------------------
#
# `is_connected` on a sharded feed rolls ALL shards up with `all()`, so one
# shard's idle-timer reconnect must never be counted as the whole feed going
# down -- that over-counts loss for every OTHER shard's instruments. These
# tests pin the fix: gap accounting keyed to the shard that actually dropped,
# with the feed-wide gap reserved for the case every shard is down.


def test_one_shard_down_opens_a_shard_scoped_gap_not_a_feed_wide_one(
    loop: asyncio.AbstractEventLoop,
) -> None:
    client, feed = build_sharded_client(loop)
    for label in feed.shard_status_labels():
        feed.restore_shard(label)
    client.sample_feed_health()

    feed.drop_shard("shard-0")
    client.sample_feed_health()

    assert client.tape_gaps == 1
    assert client.is_tape_gap_open is False, (
        "shard-0 alone must not open the FEED-WIDE gap -- shard-1 is still up"
    )


def test_all_shards_down_opens_a_feed_wide_gap_exactly_as_before(
    loop: asyncio.AbstractEventLoop,
) -> None:
    client, feed = build_sharded_client(loop)
    for label in feed.shard_status_labels():
        feed.restore_shard(label)
    client.sample_feed_health()

    feed.drop_shard("shard-0")
    client.sample_feed_health()
    feed.drop_shard("shard-1")
    client.sample_feed_health()

    assert client.is_tape_gap_open is True, "every shard down must open the feed-wide gap"


def test_a_recovered_shard_closes_its_own_gap_with_duration(
    loop: asyncio.AbstractEventLoop,
) -> None:
    client, feed = build_sharded_client(loop)
    for label in feed.shard_status_labels():
        feed.restore_shard(label)
    client.sample_feed_health()

    feed.drop_shard("shard-0")
    client.sample_feed_health()
    client.sample_feed_health()

    feed.restore_shard("shard-0")
    client.sample_feed_health()

    assert client.is_tape_gap_open is False
    assert client.tape_gap_seconds_total == pytest.approx(0.0), (
        "shard-scoped downtime is not folded into the FEED-WIDE seconds total"
    )


def test_full_outage_then_partial_recovery_never_double_opens_a_slug(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """The full lifecycle, on an INJECTED clock, pinned to exact records.

    shard-0 drops alone (shard gap #1) -> shard-1 also drops, EVERY shard now
    down (shard #1 is subsumed with a CLOSED row, feed-wide gap #2 opens) ->
    ONLY shard-0 recovers (feed-wide #2 closes with a row for every slug,
    shard-1 gets a FRESH gap #3 starting at THIS sample's clock reading) ->
    shard-1 recovers (#3 closes with duration). Across all of it: no slug is
    ever reported OPEN twice without an intervening CLOSE, and no gap_seq is
    ever reused for the same slug.
    """
    clock = TestClock()
    client, feed, gaps = build_sharded_client_with_recorded_gaps(loop, clock)
    slug_instrument = {
        SLUG: slug_to_instrument_id(SLUG),
        OTHER_SLUG: slug_to_instrument_id(OTHER_SLUG),
    }

    def sample_at(now_ns: int) -> None:
        clock.set_time(now_ns)
        client.sample_feed_health()

    for label in feed.shard_status_labels():
        feed.restore_shard(label)
    sample_at(0)

    # -- shard-0 alone drops: shard-scoped gap #1, SLUG only ----------------
    feed.drop_shard("shard-0")
    sample_at(1_000_000_000)

    shard_opens = [g for g in gaps if not g.resolved]
    assert len(shard_opens) == 1
    assert shard_opens[0].instrument_id == slug_instrument[SLUG]
    assert shard_opens[0].gap_seq == 1
    assert shard_opens[0].started_ns == 1_000_000_000
    assert client.tape_gaps == 1

    # -- shard-1 also drops: full outage subsumes gap #1, opens feed-wide #2
    feed.drop_shard("shard-1")
    sample_at(2_000_000_000)

    assert client.tape_gaps == 2
    subsumed_close = [g for g in gaps if g.gap_seq == 1 and g.resolved]
    assert len(subsumed_close) == 1, "shard-0's gap #1 must get a CLOSED row, not vanish"
    assert subsumed_close[0].instrument_id == slug_instrument[SLUG]
    assert subsumed_close[0].started_ns == 1_000_000_000
    assert subsumed_close[0].ended_ns == 2_000_000_000

    feed_wide_opens = [g for g in gaps if g.gap_seq == 2 and not g.resolved]
    assert {g.instrument_id for g in feed_wide_opens} == set(slug_instrument.values()), (
        "the feed-wide gap must cover EVERY slug, exactly as before"
    )
    assert all(g.started_ns == 2_000_000_000 for g in feed_wide_opens)

    # -- ONLY shard-0 recovers: feed-wide #2 closes for every slug, shard-1
    #    gets a FRESH shard-scoped gap #3 starting at THIS sample's clock --
    feed.restore_shard("shard-0")
    sample_at(3_000_000_000)

    assert client.tape_gaps == 3
    feed_wide_closes = [g for g in gaps if g.gap_seq == 2 and g.resolved]
    assert {g.instrument_id for g in feed_wide_closes} == set(slug_instrument.values())
    assert all(
        g.started_ns == 2_000_000_000 and g.ended_ns == 3_000_000_000 for g in feed_wide_closes
    )

    fresh_shard_opens = [g for g in gaps if g.gap_seq == 3 and not g.resolved]
    assert len(fresh_shard_opens) == 1
    assert fresh_shard_opens[0].instrument_id == slug_instrument[OTHER_SLUG], (
        "shard-1's fresh gap must carry ONLY shard-1's slug"
    )
    assert fresh_shard_opens[0].started_ns == 3_000_000_000, (
        "the fresh gap starts at THIS sample's now_ns, per the documented lower bound"
    )
    assert not any(g.gap_seq == 3 and g.instrument_id == slug_instrument[SLUG] for g in gaps), (
        "shard-0 is back up -- it must never appear under shard-1's fresh gap_seq"
    )

    # -- shard-1 recovers: gap #3 closes with duration -----------------------
    feed.restore_shard("shard-1")
    sample_at(4_000_000_000)

    assert client.is_tape_gap_open is False
    fresh_shard_closes = [g for g in gaps if g.gap_seq == 3 and g.resolved]
    assert len(fresh_shard_closes) == 1
    assert fresh_shard_closes[0].instrument_id == slug_instrument[OTHER_SLUG]
    assert fresh_shard_closes[0].started_ns == 3_000_000_000
    assert fresh_shard_closes[0].ended_ns == 4_000_000_000

    # -- invariants over the WHOLE run: never two OPENs, never a repeated
    #    gap_seq, for the same slug -----------------------------------------
    is_open: dict[Any, bool] = {}
    seen_seqs: dict[Any, set[int]] = {}
    for record in gaps:
        instrument_id = record.instrument_id
        seqs = seen_seqs.setdefault(instrument_id, set())
        if not record.resolved:
            assert not is_open.get(instrument_id, False), (
                f"{instrument_id} has two OPEN gaps at once (gap_seq={record.gap_seq})"
            )
            assert record.gap_seq not in seqs, (
                f"gap_seq {record.gap_seq} repeated for {instrument_id}"
            )
            seqs.add(record.gap_seq)
            is_open[instrument_id] = True
        else:
            assert is_open.get(instrument_id, False), (
                f"{instrument_id} CLOSED without a matching OPEN (gap_seq={record.gap_seq})"
            )
            is_open[instrument_id] = False
    assert not any(is_open.values()), "every gap opened in this test must also have closed"
