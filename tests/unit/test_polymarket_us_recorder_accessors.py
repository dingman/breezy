"""AUT-1 WP3 step 1 (EM6): the read-only accessors the recorder gate samples.

Every accessor reads state the client already keeps; none changes behaviour. The client is the
real ``PolymarketUSDataClient`` over the same doubles the other recorder tests use.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us import feed_fault
from breezy.adapters.polymarket_us.recorder_watchdog import (
    PHASE_CONNECTING,
    PHASE_DISCOVERING,
    PHASE_SAFE_MODE,
    PHASE_STREAMING,
    stream_bytes_total,
)
from tests.support.recorder_watchdog import build_watchdog_client
from tests.unit.test_polymarket_us_connect_fail_fast import (
    ConnectFailsFeed,
    _InitializeStubProvider,
)
from tests.unit.test_polymarket_us_data import SLUG, make_instrument
from tests.unit.test_polymarket_us_quote_tape_gap import FakeProvider


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


def test_phase_transitions_discovering_connecting_streaming_safe_mode(
    loop: asyncio.AbstractEventLoop,
) -> None:
    provider = FakeProvider([make_instrument(SLUG)])
    client = build_watchdog_client(loop, provider, watchdog_notify=False)
    seen: list[tuple[str, int]] = []

    original_init = provider.initialize
    original_push = client._send_all_instruments_to_data_engine
    original_reconcile = client._reconcile_discovered_subscriptions

    async def init(*args: Any, **kwargs: Any) -> None:
        seen.append((client.watchdog_phase, client.watchdog_phase_started_ns))
        await original_init(*args, **kwargs)

    def push() -> None:
        seen.append((client.watchdog_phase, client.watchdog_phase_started_ns))
        original_push()

    async def reconcile(**kwargs: Any) -> None:
        seen.append((client.watchdog_phase, client.watchdog_phase_started_ns))
        await original_reconcile(**kwargs)

    provider.initialize = init  # type: ignore[method-assign]
    client._send_all_instruments_to_data_engine = push  # type: ignore[method-assign]
    client._reconcile_discovered_subscriptions = reconcile  # type: ignore[method-assign]
    assert client.watchdog_phase == PHASE_DISCOVERING

    loop.run_until_complete(client._connect())
    try:
        assert [phase for phase, _ in seen] == [
            PHASE_DISCOVERING,
            PHASE_CONNECTING,
            PHASE_CONNECTING,
        ]
        assert client.watchdog_phase == PHASE_STREAMING
        started = [ns for _, ns in seen]
        assert started == sorted(started) and client.watchdog_phase_started_ns >= started[-1]
        # Safe mode overrides the phase and carries its own start.
        before = client.watchdog_phase_started_ns
        client._enter_safe_mode()
        assert client.watchdog_phase == PHASE_SAFE_MODE
        assert client.watchdog_phase_started_ns >= before
        entered = client.watchdog_phase_started_ns
        client._enter_safe_mode()
        assert client.watchdog_phase_started_ns == entered  # first entry only
    finally:
        loop.run_until_complete(client._disconnect())


def test_connect_failure_enters_safe_mode_phase(loop: asyncio.AbstractEventLoop) -> None:
    client = build_watchdog_client(
        loop,
        FakeProvider([make_instrument(SLUG)]),
        watchdog_notify=False,
        feed_factory=ConnectFailsFeed,
    )
    loop.run_until_complete(client._connect())
    assert client.is_safe_mode is True
    assert client.watchdog_phase == PHASE_SAFE_MODE
    assert client.watchdog_phase_started_ns > 0


def test_depths_published_counts_handed_depths(loop: asyncio.AbstractEventLoop) -> None:
    from breezy.adapters.polymarket_us.parsing import parse_binary_option
    from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
    from tests.unit.test_polymarket_us_depth_parsing import TS_INIT, load_raw

    client = build_watchdog_client(
        loop, FakeProvider([make_instrument(SLUG)]), watchdog_notify=False
    )
    instrument = parse_binary_option(
        load_raw("market_open_510636_by_slug.json"), venue=POLYMARKET_US_VENUE, ts_init=TS_INIT
    )
    handed: list[Any] = []
    client._handle_data = handed.append
    assert client.depths_published == 0

    client._publish_market_data(load_raw("book_open_510636.json"), instrument, TS_INIT)

    depths = [item for item in handed if type(item).__name__ == "OrderBookDepth10"]
    assert len(depths) == 1 and client.depths_published == 1
    client._publish_market_data(load_raw("book_open_510636.json"), instrument, TS_INIT)
    assert client.depths_published == 2
    assert client.quotes_published == 0  # the double quote parser yields none: twins stay apart


def test_discovered_slugs_and_subscribed_count_read_only(loop: asyncio.AbstractEventLoop) -> None:
    client = build_watchdog_client(
        loop, FakeProvider([make_instrument(SLUG)]), watchdog_notify=False
    )
    assert client.discovered_slug_count == 1
    assert client.subscribed_slug_count == 0
    loop.run_until_complete(client._connect())
    try:
        assert client.subscribed_slug_count == 1
        assert client.feed_watch_alive is True
        with pytest.raises(AttributeError):
            client.subscribed_slug_count = 5  # type: ignore[misc]
        with pytest.raises(AttributeError):
            client.depths_published = 5  # type: ignore[misc]
    finally:
        loop.run_until_complete(client._disconnect())
    assert client.feed_watch_alive is False


def test_reload_accessors_set_by_update_instruments(loop: asyncio.AbstractEventLoop) -> None:
    client = build_watchdog_client(
        loop, FakeProvider([make_instrument(SLUG)]), watchdog_notify=False
    )
    assert client.last_discovery_reload_ns == 0 and client.last_scheduled_reload_delay_secs == 0.0
    loop.run_until_complete(client._connect())
    try:
        loop.run_until_complete(asyncio.sleep(0.05))
        # `instrument_reload_interval_mins=5` is the override the helper builds the client with.
        assert client.last_scheduled_reload_delay_secs == 300.0
        baseline = client.last_discovery_reload_ns
        assert baseline > 0
        loop.run_until_complete(client._run_one_reload_cycle())
        assert client.last_discovery_reload_ns == baseline  # only the loop stamps a reload
    finally:
        loop.run_until_complete(client._disconnect())


def test_reload_cycle_stamps_last_discovery_reload(
    loop: asyncio.AbstractEventLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = build_watchdog_client(
        loop, FakeProvider([make_instrument(SLUG)]), watchdog_notify=False
    )
    real_sleep = asyncio.sleep

    async def fast(delay: float, *args: Any, **kwargs: Any) -> None:
        await real_sleep(0.01 if delay == 300.0 else delay)

    monkeypatch.setattr("breezy.adapters.polymarket_us.data.asyncio.sleep", fast)
    loop.run_until_complete(client._connect())
    try:
        loop.run_until_complete(real_sleep(0.01))
        first = client.last_discovery_reload_ns
        loop.run_until_complete(real_sleep(0.15))
        assert client.last_discovery_reload_ns > first
    finally:
        loop.run_until_complete(client._disconnect())


def test_discovery_attempt_inflight_since_set_around_initialize_and_cleared_in_finally(
    loop: asyncio.AbstractEventLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _InitializeStubProvider([make_instrument(SLUG)], empty_times=1)
    client = build_watchdog_client(
        loop, provider, watchdog_notify=False, empty_discovery_retry_secs=600.0
    )
    during: list[int] = []
    sleeping: list[int] = []
    original = provider.initialize

    async def spy(*args: Any, **kwargs: Any) -> None:
        during.append(client.discovery_attempt_inflight_since_ns)
        await original(*args, **kwargs)

    provider.initialize = spy  # type: ignore[method-assign]
    real_sleep = asyncio.sleep

    async def fast(delay: float, *args: Any, **kwargs: Any) -> None:
        if delay == 60.0:
            sleeping.append(client.discovery_attempt_inflight_since_ns)
            delay = 0.01
        await real_sleep(delay)

    monkeypatch.setattr("breezy.adapters.polymarket_us.data.asyncio.sleep", fast)
    loop.run_until_complete(client._connect())
    try:
        assert len(during) == 2 and all(ns > 0 for ns in during)
        assert sleeping == [0]  # the retry sleep between attempts is not an attempt in flight
        assert client.discovery_attempt_inflight_since_ns == 0
    finally:
        loop.run_until_complete(client._disconnect())


def test_inflight_is_cleared_when_initialize_raises(loop: asyncio.AbstractEventLoop) -> None:
    from breezy.adapters.polymarket_us.errors import VenuePayloadError

    provider = _InitializeStubProvider([make_instrument(SLUG)], error=VenuePayloadError("dup"))
    client = build_watchdog_client(loop, provider, watchdog_notify=False)
    loop.run_until_complete(client._connect())
    assert client.discovery_attempt_inflight_since_ns == 0
    assert client.is_safe_mode is True


def test_stream_bytes_total_counts_only_regular_visible_feather_files(tmp_path: Path) -> None:
    (tmp_path / "quote_tick_1.feather").write_bytes(b"a" * 100)
    (tmp_path / "trade_tick_2.feather").write_bytes(b"b" * 50)
    (tmp_path / ".salvaged-x.feather").write_bytes(b"c" * 999)
    (tmp_path / ".preflight-memo-v1.json").write_bytes(b"d" * 999)
    (tmp_path / "note.txt").write_bytes(b"e" * 999)
    (tmp_path / "link.feather").symlink_to(tmp_path / "quote_tick_1.feather")
    assert stream_bytes_total(tmp_path) == 150
    assert stream_bytes_total(tmp_path / "not-created-yet") == 0


def test_recorder_sample_reads_every_field_through_the_accessors(
    loop: asyncio.AbstractEventLoop, tmp_path: Path
) -> None:
    (tmp_path / "quote_tick_1.feather").write_bytes(b"x" * 64)
    client = build_watchdog_client(
        loop, FakeProvider([make_instrument(SLUG)]), watchdog_notify=False, stream_dir=str(tmp_path)
    )
    snapshot = client._recorder_sample()
    assert snapshot.phase == PHASE_DISCOVERING
    assert snapshot.stream_bytes == 64
    assert snapshot.discovered_slugs == 1 and snapshot.subscribed_count == 0
    assert snapshot.events == 0 and snapshot.safe_mode is False
    assert snapshot.feed_watch_alive is False
    assert snapshot.is_tape_gap_open is False


def test_stream_bytes_total_skips_an_entry_whose_stat_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP3-R3 (py L2): one file removed between scandir and stat skips that entry only."""
    import os

    (tmp_path / "a.feather").write_bytes(b"a" * 10)
    (tmp_path / "gone.feather").write_bytes(b"b" * 20)
    (tmp_path / "c.feather").write_bytes(b"c" * 30)
    real_scandir = os.scandir

    class _Entry:
        def __init__(self, entry: os.DirEntry[str]) -> None:
            self._entry = entry
            self.name = entry.name

        def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            if self.name == "gone.feather":
                raise FileNotFoundError(self.name)
            return self._entry.stat(follow_symlinks=follow_symlinks)

    class _Scan:
        def __init__(self, path: Path) -> None:
            self._inner = real_scandir(path)

        def __enter__(self) -> list[_Entry]:
            return [_Entry(e) for e in self._inner.__enter__()]

        def __exit__(self, *exc: object) -> None:
            self._inner.__exit__(*exc)

    monkeypatch.setattr("breezy.adapters.polymarket_us.recorder_watchdog.os.scandir", _Scan)
    assert stream_bytes_total(tmp_path) == 40


def test_config_rejects_watchdog_notify_without_a_stream_dir() -> None:
    from msgspec.structs import replace

    from breezy.runtime.settings import SettingsError
    from tests.unit.test_quote_tape_recorder import make_data_client_config

    base = make_data_client_config()
    assert base.watchdog_notify is False
    for bad in (None, "", 5):
        with pytest.raises(SettingsError, match="watchdog_stream_dir"):
            replace(base, watchdog_notify=True, watchdog_stream_dir=bad)
    ok = replace(base, watchdog_notify=True, watchdog_stream_dir="/tmp/x/live/abc")
    assert ok.watchdog_notify is True
