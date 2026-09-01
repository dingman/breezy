"""BL-22: the missing-instrument alert must OBSERVE the engine, not race it.

``_alert_on_missing_cache_after_push`` fires immediately after
``_send_all_instruments_to_data_engine()``, with no ``await`` in between. In a
LIVE node that is a race the alert always loses: ``DataClient._handle_data``
sends to the ``DataEngine.process`` endpoint (``data/client.pyx:1262-1263``),
and ``LiveDataEngine.process`` (``live/data_engine.py:324-343``) does not
process anything -- it ENQUEUES onto an ``asyncio.Queue`` drained by the
``_run_data_queue`` task (``:477-497``). Until the loop yields, that queue is
still full and the cache is still empty, so every instrument looks missing.

The data is sound. The authoritative gate is
``_reconcile_discovered_subscriptions``, which runs after an ``await`` and
reported ``blocked_missing_cache=()`` on the very cycle where the alert
claimed all 60 were absent (venue discovery log, 2026-08-30); inbound frames
resolve through ``_instrument_provider.find()`` first regardless. So this is
cosmetic -- and cosmetic is exactly the problem. Sixty ERROR lines per
discovery cycle, for an eight-hour unattended run, is the noise a real error
hides in, and it would trip any error-rate alarm built on this log.

The fix is NOT to delete the alert or lower its level. The condition it
watches is real: an instrument that never reaches the cache means the
streaming writer cannot resolve it, and
``StreamingFeatherWriter.write`` silently ``return``s for a per-instrument
type whose instrument is absent (``persistence/writer.py:212-232``) -- quotes
would be dropped from the tape with no error at all. The alert must keep
firing for that. It must simply stop firing for instruments the engine has
merely not gotten to yet.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.config import InstrumentProviderConfig, LiveDataEngineConfig
from nautilus_trader.live.data_engine import LiveDataEngine
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import PolymarketUSDataClient, build_data_client
from breezy.adapters.polymarket_us.symbology import slug_to_instrument_id
from tests.unit.test_polymarket_us_data import SLUG, make_instrument
from tests.unit.test_polymarket_us_quote_tape_gap import ControllableFeed, FakeProvider

CLIENT_NAME = "POLYMARKET_US"
SLUGS = (SLUG, "tc-temp-miahigh-2026-08-31-gte91lt92f", "tc-temp-mdwhigh-2026-08-31-gte92lt93f")


def build_live_client(
    loop: asyncio.AbstractEventLoop,
    slugs: tuple[str, ...] = SLUGS,
) -> tuple[PolymarketUSDataClient, LiveDataEngine, ControllableFeed]:
    """A client wired to a REAL ``LiveDataEngine``.

    The plain ``DataEngine`` used by the sibling unit tests processes
    synchronously and therefore cannot reproduce this defect at all: its cache
    is populated before ``_send_all_instruments_to_data_engine`` returns. Only
    the live engine has the queue that creates the race, so only the live
    engine can prove it is gone.
    """
    clock = LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = LiveDataEngine(
        loop=loop,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        config=LiveDataEngineConfig(),
    )
    feeds: list[ControllableFeed] = []

    def feed_factory(handler: Any) -> ControllableFeed:
        feed = ControllableFeed(handler)
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
            market_slugs=slugs,
            instrument_reload_interval_mins=5,
            user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
            instrument_provider=InstrumentProviderConfig(load_all=True),
        ),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=FakeProvider([make_instrument(slug) for slug in slugs]),
        feed_factory=feed_factory,
        quote_parser=lambda payload, *, instrument, ts_init: None,
    )
    engine.register_client(client)
    return client, engine, feeds[0]


@pytest.fixture(name="engine_loop")
def _engine_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


def _run(loop: asyncio.AbstractEventLoop, coro: Any) -> Any:
    return loop.run_until_complete(coro)


@pytest.mark.parametrize("slug_count", [1, 3])
def test_connecting_raises_no_missing_cache_alert_for_instruments_the_engine_has(
    engine_loop: asyncio.AbstractEventLoop,
    slug_count: int,
) -> None:
    """The storm itself: every pushed instrument must be seen as present.

    Parameterised over one and several slugs because the live capture pushes
    sixty at a time; a fix that only works for a single instrument would leave
    the storm intact.
    """
    slugs = SLUGS[:slug_count]
    client, engine, _feed = build_live_client(engine_loop, slugs)

    async def scenario() -> None:
        engine.start()
        await asyncio.sleep(0)
        try:
            await client._connect()
            await client._disconnect()
        finally:
            engine.stop()
            await asyncio.sleep(0)

    _run(engine_loop, scenario())

    assert client.missing_cache_alerts == 0, (
        "the alert fired for instruments the engine had simply not drained yet"
    )


def test_the_instruments_really_are_in_the_cache_after_connect(
    engine_loop: asyncio.AbstractEventLoop,
) -> None:
    """Guard against a 'fix' that just stops looking.

    A zero alert count is only meaningful if the cache genuinely holds the
    instruments by then. This is the assertion that makes deleting the alert,
    or short-circuiting the check, fail.
    """
    client, engine, _feed = build_live_client(engine_loop)

    async def scenario() -> None:
        engine.start()
        await asyncio.sleep(0)
        try:
            await client._connect()
            await client._disconnect()
        finally:
            engine.stop()
            await asyncio.sleep(0)

    _run(engine_loop, scenario())

    for slug in SLUGS:
        instrument_id = slug_to_instrument_id(slug, client.venue)
        assert client._cache.instrument(instrument_id) is not None


def test_an_instrument_that_never_reaches_the_cache_still_alerts(
    engine_loop: asyncio.AbstractEventLoop,
) -> None:
    """The alert must keep its teeth. This is the condition it exists for.

    A slug the provider advertises but never actually loads never reaches the
    engine and never reaches the cache, so waiting for the engine to drain can
    never make it appear. The alert must fire -- otherwise the streaming
    writer silently drops that instrument's quotes
    (``persistence/writer.py:212-232``) and the tape is short with no error.
    """
    client, engine, _feed = build_live_client(engine_loop, SLUGS)
    ghost = "tc-temp-laxhigh-2026-08-31-gte80lt81f"

    async def scenario() -> None:
        engine.start()
        await asyncio.sleep(0)
        try:
            await client._connect()
            # Advertised by discovery, never loaded into the provider.
            await client._alert_on_missing_cache_after_push((*SLUGS, ghost))
            await client._disconnect()
        finally:
            engine.stop()
            await asyncio.sleep(0)

    _run(engine_loop, scenario())

    assert client.missing_cache_alerts == 1, "the genuinely absent instrument must alert"


def test_waiting_for_the_engine_is_bounded_and_does_not_hang(
    engine_loop: asyncio.AbstractEventLoop,
) -> None:
    """A stalled engine must not stall the recorder's connect path.

    With the engine never started, nothing drains the queue and the
    instruments never arrive. The check must give up on a deadline and report,
    not block the client's ``_connect`` forever.
    """
    client, engine, _feed = build_live_client(engine_loop, SLUGS)

    async def scenario() -> None:
        # Engine deliberately NOT started: `_run_data_queue` never runs.
        await asyncio.wait_for(
            client._alert_on_missing_cache_after_push(SLUGS),
            timeout=30.0,
        )

    _run(engine_loop, scenario())

    assert client.missing_cache_alerts == len(SLUGS)
    assert engine.is_running is False
