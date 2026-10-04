"""AUT-1 WP0 premises, V-12, V-13: ForecastPoint stream and feed-watch cadence.

Shared helpers live in ``aut1_premises_support`` (WP0-R10).
"""

import asyncio
import threading
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.common.actor import Actor
from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.forecast_point import ForecastPoint
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from tests.unit.aut1_premises_support import (
    _TRADER,
    _clock_at,
    _open_writer,
    _read_rows,
    _table_files,
)

# ---------------------------------------------------------------------------
# V-12  ForecastPoint stream
# ---------------------------------------------------------------------------

_FORECAST_TOPIC: Final[str] = "data.ForecastPoint*"


class _CaptureStandIn(Actor):  # type: ignore[misc]
    """Stand-in for ``CaptureActor``: subscribes in ``on_start`` and records what arrives."""

    def __init__(self, topic: str = _FORECAST_TOPIC) -> None:
        super().__init__()
        self.topic = topic
        self.received: list[Any] = []

    def on_start(self) -> None:
        self.msgbus.subscribe(topic=self.topic, handler=self.received.append)


def _nbm_harness() -> Any:
    from tests.unit.test_nbm_quantile_actor import build

    return build()


def _register_capture(harness: Any, topic: str = _FORECAST_TOPIC) -> _CaptureStandIn:
    capture = _CaptureStandIn(topic)
    capture.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=harness.actor.msgbus,
        cache=TestComponentStubs.cache(),
        clock=harness.clock,
    )
    return capture


@pytest.mark.asyncio
async def test_forecast_point_topic_pinned_by_publish_probe() -> None:
    """V-12. The topic ``NbmQuantileActor._publish`` publishes on is exactly ``data.ForecastPoint*``
    (``DataType.topic`` is ``ForecastPoint*``): a subscriber on that literal receives every point
    from the real actor fed the recorded bulletin.

    MUTATION (red): subscribing to ``data.ForecastPoint`` (no ``*``) receives nothing.
    """
    assert nbm_forecast_point_data_type().topic == "ForecastPoint*"
    harness = _nbm_harness()
    capture = _register_capture(harness)
    capture.start()
    harness.actor.start()
    await harness.drain()
    assert len(capture.received) == 28
    assert {type(p) for p in capture.received} == {ForecastPoint}
    assert capture.received == harness.published


@pytest.mark.asyncio
async def test_capture_actor_subscribed_before_first_forecast_publish() -> None:
    """V-12 (``trader.py:251-271``, ``nbm_quantile_actor.py:286-300``). Even if the producing
    actor starts FIRST, its first poll is an asynchronous task: nothing is published before
    ``start()`` returns, so a subscriber made in a later actor's ``on_start`` still gets all 28
    points. And a real ``Trader`` (from a ``BacktestEngine``) starts actors before strategies even
    when the strategy was registered first.

    MUTATION (red): starting the capture stand-in only after ``drain()`` receives zero points;
    making the ordering probe a ``Strategy`` instead of an ``Actor`` starts it after the strategy.
    """
    harness = _nbm_harness()
    capture = _register_capture(harness)
    harness.actor.start()
    assert harness.published == []
    capture.start()
    await harness.drain()
    assert len(capture.received) == 28

    started: list[str] = []

    class StartOrderActor(Actor):  # type: ignore[misc]
        def on_start(self) -> None:
            started.append("actor")

    class StartOrderStrategy(Strategy):  # type: ignore[misc]
        def on_start(self) -> None:
            started.append("strategy")

    engine = BacktestEngine(BacktestEngineConfig(trader_id=_TRADER))
    try:
        engine.add_strategy(StartOrderStrategy())  # registered FIRST on purpose
        engine.add_actor(StartOrderActor())
        engine.trader.start()
        assert started == ["actor", "strategy"]
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_forecast_point_streams_to_regular_custom_file(tmp_path: Path) -> None:
    """V-12. Real ``ForecastPoint``s written through the real writer land in one regular
    ``custom_forecast_point_*.feather`` (no ``instrument_id``), one row each, values intact.

    MUTATION (red): an ``include_types`` without ``ForecastPoint`` writes no file.
    """
    harness = _nbm_harness()
    capture = _register_capture(harness)
    capture.start()
    harness.actor.start()
    await harness.drain()
    writer = _open_writer(tmp_path, _clock_at("2026-10-04T10:00:00.000000000Z"))
    for point in capture.received:
        writer.write(point)
    writer.close()
    stream_dir = tmp_path / "live" / "premise"
    assert len(_table_files(stream_dir, "custom_forecast_point")) == 1
    rows = _read_rows(stream_dir, "custom_forecast_point")
    assert len(rows) == len(capture.received) == 28
    assert sorted((r["station"], r["variable"]) for r in rows) == sorted(
        (p.station, p.variable) for p in capture.received
    )
    assert all("instrument_id" not in r for r in rows)


# ---------------------------------------------------------------------------
# V-13  feed-watch cadence; sample_feed_health runs on the event loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_feed_health_runs_on_loop_thread() -> None:
    """V-13 (``data.py:1947-1960``): the cadence is ``DEFAULT_FEED_WATCH_INTERVAL_SECS`` = 5.0 s,
    and ``_watch_feed`` calls ``sample_feed_health`` from the event-loop thread, not a worker.

    MUTATION (red): calling ``sample_feed_health`` through ``run_in_executor`` records a worker
    thread id different from the loop's.
    """
    from breezy.adapters.polymarket_us.data import DEFAULT_FEED_WATCH_INTERVAL_SECS
    from tests.unit.test_polymarket_us_data import build_harness

    assert DEFAULT_FEED_WATCH_INTERVAL_SECS == 5.0
    harness = build_harness()
    assert harness.client._feed_watch_interval_secs == DEFAULT_FEED_WATCH_INTERVAL_SECS
    harness.client._feed_watch_interval_secs = 0.01
    seen: list[int] = []

    def recording() -> bool:
        seen.append(threading.get_ident())
        return False

    harness.client.sample_feed_health = recording  # type: ignore[method-assign]
    await harness.client._connect()
    watchdog = harness.client._feed_watchdog
    assert watchdog is not None
    await asyncio.wait_for(watchdog, timeout=5)
    await harness.client._disconnect()
    assert seen == [threading.get_ident()]
