"""Shared builders for the AUT-1 WP3 recorder-watchdog tests (samples, clients, a notify socket)."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import PolymarketUSDataClient, build_data_client
from breezy.adapters.polymarket_us.recorder_watchdog import (
    PHASE_STREAMING,
    RecorderSample,
)

NS = 1_000_000_000
#: One fixed phase start for healthy STREAMING samples, so a series is one phase instance.
PHASE_START_NS = 1


def utc_ns(hour: int, minute: int = 0, second: int = 0, *, day: int = 4) -> int:
    """Nanoseconds of 2026-10-<day> hh:mm:ss UTC."""
    return int(datetime(2026, 10, day, hour, minute, second, tzinfo=UTC).timestamp()) * NS


def sample(now_ns: int, **overrides: Any) -> RecorderSample:
    """A healthy STREAMING sample at ``now_ns``; override any field."""
    fields: dict[str, Any] = {
        "now_ns": now_ns,
        "phase": PHASE_STREAMING,
        "phase_started_ns": PHASE_START_NS,
        "discovered_slugs": 30,
        "subscribed_count": 30,
        "quotes_published": 0,
        "depths_published": 0,
        "trades_published": 0,
        "is_tape_gap_open": False,
        "safe_mode": False,
        "feed_watch_alive": True,
        "last_discovery_reload_ns": now_ns - 100 * NS,
        "last_scheduled_reload_delay_secs": 900.0,
        "discovery_attempt_inflight_since_ns": 0,
        "stream_bytes": 1000,
    }
    fields.update(overrides)
    return RecorderSample(**fields)


def series(
    end_ns: int,
    span_s: int,
    *,
    step_s: int = 5,
    events_at: Any = lambda t: 0,
    bytes_at: Any = lambda t: 1000,
    **overrides: Any,
) -> list[RecorderSample]:
    """Samples every ``step_s`` over ``span_s`` seconds ending at ``end_ns`` (oldest first).

    ``events_at(t)`` and ``bytes_at(t)`` take seconds-before-end (``t`` runs span_s .. 0).
    """
    out: list[RecorderSample] = []
    for back in range(span_s, -1, -step_s):
        out.append(
            sample(
                end_ns - back * NS,
                quotes_published=events_at(back),
                stream_bytes=bytes_at(back),
                **overrides,
            )
        )
    return out


class ListLogger:
    """A WatchdogLogger that records ``(level, message)``."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.lines.append(("info", message))

    def warning(self, message: str) -> None:
        self.lines.append(("warning", message))

    def error(self, message: str) -> None:
        self.lines.append(("error", message))

    def messages(self, prefix: str) -> list[str]:
        return [m for _, m in self.lines if m.startswith(prefix)]


class NotifyReceiver:
    """A bound AF_UNIX datagram socket standing in for systemd's ``$NOTIFY_SOCKET``.

    A background thread drains it continuously, as systemd does: an AF_UNIX datagram queue holds
    only ``net.unix.max_dgram_qlen`` (10) messages, and the sender is non-blocking.
    """

    def __init__(self, path: Path) -> None:
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._server.bind(str(path))
        self._server.settimeout(0.01)
        self._messages: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._server.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            with self._lock:
                self._messages.append(data.decode())

    def take(self) -> list[str]:
        time.sleep(0.05)
        with self._lock:
            out, self._messages = self._messages, []
        return out

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        self._server.close()


@contextmanager
def notify_socket(path: Path) -> Iterator[NotifyReceiver]:
    receiver = NotifyReceiver(path)
    try:
        yield receiver
    finally:
        receiver.close()


def drain(receiver: NotifyReceiver) -> list[str]:
    return receiver.take()


def build_watchdog_client(
    loop: asyncio.AbstractEventLoop,
    provider: Any,
    *,
    watchdog_notify: bool = True,
    interval_s: float = 0.01,
    empty_discovery_retry_secs: float = 0.0,
    stream_dir: str | None = None,
    clock: LiveClock | None = None,
    feed_factory: Any | None = None,
) -> PolymarketUSDataClient:
    from tests.unit.test_polymarket_us_data import SLUG
    from tests.unit.test_polymarket_us_quote_tape_gap import ControllableFeed

    clock = clock if clock is not None else LiveClock()
    msgbus: MessageBus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    engine = DataEngine(msgbus=msgbus, cache=cache, clock=clock)
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
            empty_discovery_retry_secs=empty_discovery_retry_secs,
            watchdog_notify=watchdog_notify,
            watchdog_stream_dir=stream_dir,
        ),
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=provider,
        feed_factory=feed_factory or ControllableFeed,
        quote_parser=lambda payload, *, instrument, ts_init: None,
        feed_watch_interval_secs=interval_s,
    )
    engine.register_client(client)
    return client
