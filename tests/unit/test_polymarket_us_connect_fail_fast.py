"""A ``_connect()`` failure must fail the recorder, not vanish into a log line.

Measured incident (2026-09-03 22:31:10 UTC): the recorder was OOM-killed,
restarted by systemd, and its data client's ``_connect`` raised
``VenueTransportError`` from ``self._feed.connect()``. The process did NOT
exit. It could not have: Nautilus's own ``LiveDataClient.connect()``
(``live/data_client.py:222-234``) wraps ``_connect()`` in ``create_task`` with
``actions=lambda: self._set_connected(True)`` -- called ONLY when the task
raises no exception. On failure, ``_on_task_completed``
(``live/data_client.py:190-210``) does nothing but
``self._log.exception(...)``: it never marks the client connected, never
re-raises, and never asks the node to stop. ``self._log`` is Nautilus's own
async logger; nothing outside the process reads that line.

``NautilusKernel._await_engines_connected`` (``system/kernel.py:1298-1313``)
then times out after ``timeout_connection`` (60s) waiting for
``DataEngine.check_connected()`` and logs a WARNING -- but
``NautilusKernel.start_async`` (``system/kernel.py:1021-1023``) responds to
that timeout with a bare ``return``: it never raises, never calls
``stop_async``. ``TradingNode.run_async`` (``live/node.py:349-352``) logs
"RUNNING" unconditionally right after ``start_async()`` returns, then
``await``s the engine queue tasks forever. The process sits there,
disconnected, capturing nothing, until something external kills it.

No native Nautilus config flag rescues this (confirmed: `grep -rn
"timeout_connection"` across the installed package matches only the
`PositiveFloat` field declaration and its two log lines in
``system/kernel.py`` -- no raise-on-timeout behaviour exists).

The fix therefore has to live in the one place this recorder already proved
out for the SAME class of problem: ``PolymarketUSDataClient`` already
requests a native shutdown and latches a fatal fault when its watchdog
observes a feed it cannot recover
(``tests/unit/test_polymarket_us_unattended_exit.py``). That machinery never
ran here because the watchdog task
(``PolymarketUSDataClient._watch_feed``) is created AFTER
``await self._feed.connect()`` succeeds -- a `_connect()` that fails before
reaching that line starts no watchdog at all. This file proves the missing
half: a `_connect()` failure must reuse the SAME fatal-fault latch and the
SAME native ``shutdown_system`` request, from `_connect()` itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.messages import ShutdownSystem
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us import feed_fault
from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import build_data_client
from breezy.adapters.polymarket_us.errors import VenueTransportError
from tests.unit.test_polymarket_us_data import SLUG, make_instrument
from tests.unit.test_polymarket_us_quote_tape_gap import FakeProvider

SHUTDOWN_TOPIC = "commands.system.shutdown"


class ConnectFailsFeed:
    """A markets feed whose ``connect()`` raises, exactly as the incident did."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.close_called = False

    @property
    def is_connected(self) -> bool:
        return False

    @property
    def is_degraded(self) -> bool:
        return True

    @property
    def is_fatally_degraded(self) -> bool:
        return True

    @property
    def silent_subscriptions(self) -> tuple[Any, ...]:
        return ()

    @property
    def subscriptions(self) -> Mapping[str, str]:
        return {}

    async def connect(self) -> None:
        raise VenueTransportError(
            "GET /v1/ws/markets failed: WebSocketClientError"
        )

    async def close(self) -> None:
        self.close_called = True

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        raise AssertionError("never reached: connect() failed first")

    async def unsubscribe(self, request_id: str) -> None:
        return


@pytest.fixture(autouse=True)
def _clear_latch() -> Iterator[None]:
    feed_fault.clear_fatal_feed_fault()
    yield
    feed_fault.clear_fatal_feed_fault()


@pytest.fixture(name="loop")
def _loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


def build_client_with_failing_feed(loop: asyncio.AbstractEventLoop) -> tuple[Any, ConnectFailsFeed]:
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
    feeds: list[ConnectFailsFeed] = []

    def feed_factory(handler: Any) -> ConnectFailsFeed:
        feed = ConnectFailsFeed(handler)
        feeds.append(feed)
        return feed

    client = build_data_client(
        loop=loop,
        name="POLYMARKET_US",
        config=PolymarketUSDataClientConfig(
            allow_foreign_origin=True,
            api_base_url="https://api.example.invalid",
            gateway_base_url="https://gateway.example.invalid",
            ws_url="wss://api.example.invalid",
            market_slugs=(SLUG,),
            instrument_reload_interval_mins=5,
            user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
        ),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=FakeProvider([make_instrument(SLUG)]),
        feed_factory=feed_factory,
        quote_parser=lambda payload, *, instrument, ts_init: None,
    )
    engine.register_client(client)
    return client, feeds[0]


def test_a_connect_failure_latches_a_fatal_fault_for_the_exit_status(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """The bug: today ``_connect`` just raises into Nautilus's own logger.

    Nautilus's ``LiveDataClient.connect()`` wrapper swallows that exception
    (logs it, never marks connected, never re-raises) so nothing downstream
    of the client sees it. The client must therefore latch the SAME fatal
    fault its feed-loss watchdog already latches, from inside ``_connect``
    itself.
    """
    client, _feed = build_client_with_failing_feed(loop)

    assert feed_fault.fatal_feed_fault() is None

    # Must not raise: a `_connect` failure is handled here, not left to
    # propagate into Nautilus's own silent task-completion handler.
    loop.run_until_complete(client._connect())

    fault = feed_fault.fatal_feed_fault()
    assert fault is not None, (
        "a _connect failure must latch a fatal fault, exactly like a "
        "post-connect feed loss does"
    )
    assert fault.component == str(client.id)
    assert "connect" in fault.reason.lower() or "feed" in fault.reason.lower()


def test_a_connect_failure_requests_a_native_system_shutdown(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """The node must be told to stop through Nautilus's own command."""
    client, _feed = build_client_with_failing_feed(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    loop.run_until_complete(client._connect())

    assert len(published) == 1, "exactly one ShutdownSystem command"
    command = published[0]
    assert isinstance(command, ShutdownSystem)
    assert command.component_id == client.id
