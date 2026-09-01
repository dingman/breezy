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
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import PolymarketUSDataClient, build_data_client
from breezy.adapters.polymarket_us.websocket import SilentSubscriptionWarning
from tests.unit.test_polymarket_us_data import SLUG, make_instrument

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
