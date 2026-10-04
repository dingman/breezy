"""AUT-1 WP3 step 1: the recorder watchdog pinger and its place in ``_connect`` (EH1, EM2, X-5).

The client tests drive the REAL ``PolymarketUSDataClient._connect`` against a real datagram
socket standing in for systemd's ``$NOTIFY_SOCKET``, so what systemd would receive is what is
asserted.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us import feed_fault
from breezy.adapters.polymarket_us.recorder_watchdog import (
    PHASE_DISCOVERING,
    RecorderSample,
    RecorderWatchdogPinger,
)
from tests.support.recorder_watchdog import (
    NS,
    ListLogger,
    build_watchdog_client,
    drain,
    notify_socket,
    sample,
    utc_ns,
)
from tests.unit.test_polymarket_us_connect_fail_fast import (
    ConnectFailsFeed,
    _InitializeStubProvider,
)
from tests.unit.test_polymarket_us_data import SLUG, make_instrument
from tests.unit.test_polymarket_us_quote_tape_gap import FakeProvider

MORNING = utc_ns(8, 0, 0)


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


@pytest.fixture(name="notify")
def _notify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    path = tmp_path / "notify.sock"
    with notify_socket(path) as server:
        monkeypatch.setenv("NOTIFY_SOCKET", str(path))
        yield server


def _pump(loop: asyncio.AbstractEventLoop, seconds: float = 0.1) -> None:
    loop.run_until_complete(asyncio.sleep(seconds))


def _disconnect(loop: asyncio.AbstractEventLoop, client: Any) -> None:
    loop.run_until_complete(client._disconnect())


# ------------------------------------------------------------------ the pinger in _connect


def test_pinger_task_created_first_in_connect(loop: asyncio.AbstractEventLoop) -> None:
    seen: dict[str, Any] = {}
    provider = FakeProvider([make_instrument(SLUG)])
    client = build_watchdog_client(loop, provider)
    original = client._initialize_instruments_for_connect

    async def spy() -> None:
        seen["task_at_initialize"] = client._watchdog_pinger_task
        await original()

    client._initialize_instruments_for_connect = spy  # type: ignore[method-assign]
    loop.run_until_complete(client._connect())
    try:
        task = seen["task_at_initialize"]
        assert task is not None and not task.done()
        assert task is client._watchdog_pinger_task
    finally:
        _disconnect(loop, client)


def test_pinger_runs_while_initialize_retries_empty_listing(
    loop: asyncio.AbstractEventLoop,
    notify: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _InitializeStubProvider([make_instrument(SLUG)], empty_times=3)
    client = build_watchdog_client(loop, provider, empty_discovery_retry_secs=600.0)
    real_sleep = asyncio.sleep

    async def fast_sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        await real_sleep(0.05 if delay == 60.0 else delay)

    monkeypatch.setattr("breezy.adapters.polymarket_us.data.asyncio.sleep", fast_sleep)
    loop.run_until_complete(client._connect())
    try:
        messages = drain(notify)
        extends = [m for m in messages if m.startswith("EXTEND_TIMEOUT_USEC=")]
        assert provider.initialize_calls == 4
        assert len(extends) >= 2, messages  # extended during the retries, before READY
        assert messages.index("READY=1") > messages.index(extends[0])
    finally:
        _disconnect(loop, client)


def test_quiet_feed_start_sends_ready_without_any_counter_advance(
    loop: asyncio.AbstractEventLoop, notify: Any
) -> None:
    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    loop.run_until_complete(client._connect())
    try:
        _pump(loop)
        assert client.quotes_published == 0 and client.depths_published == 0
        assert drain(notify).count("READY=1") == 1
    finally:
        _disconnect(loop, client)


def test_ready_not_sent_before_subscribe_and_sent_once(
    loop: asyncio.AbstractEventLoop, notify: Any
) -> None:
    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    order: list[str] = []
    original = client._feed.subscribe_market_data

    async def spy(slugs: Any) -> None:
        order.extend(drain(notify))
        order.append("subscribed")
        await original(slugs)

    client._feed.subscribe_market_data = spy  # type: ignore[assignment,method-assign]
    loop.run_until_complete(client._connect())
    try:
        _pump(loop)
        order.extend(drain(notify))
        assert "READY=1" not in order[: order.index("subscribed")]
        assert order.count("READY=1") == 1
        assert order.index("READY=1") > order.index("subscribed")
    finally:
        _disconnect(loop, client)


def test_connect_failure_never_sends_ready(loop: asyncio.AbstractEventLoop, notify: Any) -> None:
    client = build_watchdog_client(
        loop, FakeProvider([make_instrument(SLUG)]), feed_factory=ConnectFailsFeed
    )
    loop.run_until_complete(client._connect())
    try:
        _pump(loop)
        assert "READY=1" not in drain(notify)
        assert client.is_safe_mode is True
        assert client._watchdog_pinger is not None and not client._watchdog_pinger.is_ready
    finally:
        _disconnect(loop, client)


def test_watchdog_sent_only_after_ready(loop: asyncio.AbstractEventLoop, notify: Any) -> None:
    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    loop.run_until_complete(client._connect())
    try:
        _pump(loop, 0.2)
        messages = drain(notify)
        assert "WATCHDOG=1" in messages
        assert messages.index("READY=1") < messages.index("WATCHDOG=1")
        assert not [m for m in messages[messages.index("READY=1") :] if m.startswith("EXTEND")]
    finally:
        _disconnect(loop, client)


def test_second_connect_does_not_start_a_second_pinger(loop: asyncio.AbstractEventLoop) -> None:
    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    loop.run_until_complete(client._connect())
    try:
        first = client._watchdog_pinger_task
        loop.run_until_complete(client._connect())
        assert client._watchdog_pinger_task is first
        pingers = [
            t for t in asyncio.all_tasks(loop) if t.get_name() == "polymarket-us-watchdog-pinger"
        ]
        assert len(pingers) == 1
        assert client.watchdog_phase == "STREAMING"
    finally:
        _disconnect(loop, client)


def test_pinger_task_strongly_referenced_and_cleared_on_disconnect(
    loop: asyncio.AbstractEventLoop,
) -> None:
    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    loop.run_until_complete(client._connect())
    task = client._watchdog_pinger_task
    assert task is not None
    _pump(loop)
    assert not task.done()
    _disconnect(loop, client)
    assert client._watchdog_pinger_task is None
    assert task.cancelled()


def test_ready_sent_once_across_reconnects(loop: asyncio.AbstractEventLoop, notify: Any) -> None:
    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    loop.run_until_complete(client._connect())
    _disconnect(loop, client)
    loop.run_until_complete(client._connect())
    try:
        _pump(loop)
        assert drain(notify).count("READY=1") == 1
    finally:
        _disconnect(loop, client)


def test_pinger_stops_extending_once_stop_begins(
    loop: asyncio.AbstractEventLoop, notify: Any
) -> None:
    """WP0 part (c): the default WatchdogSignal is SIGABRT and a unit that keeps extending
    while its process ignores SIGTERM sat in ``stop-sigterm`` for minutes."""
    provider = _InitializeStubProvider([make_instrument(SLUG)], empty_times=10_000)
    client = build_watchdog_client(loop, provider, empty_discovery_retry_secs=600.0)
    state = {"extending": True}

    async def hold_discovery() -> None:
        while state["extending"]:
            await asyncio.sleep(0.01)

    client._initialize_instruments_for_connect = hold_discovery  # type: ignore[method-assign]
    connect = loop.create_task(client._connect())
    try:
        _pump(loop, 0.15)
        before = [m for m in drain(notify) if m.startswith("EXTEND_TIMEOUT_USEC=")]
        assert before, "the pinger extends the start while discovery is legitimately waiting"
        client._disconnecting = True  # `_disconnect` has begun (or the component is STOPPING)
        drain(notify)
        _pump(loop, 0.15)
        assert [m for m in drain(notify) if m.startswith("EXTEND")] == []
    finally:
        state["extending"] = False
        loop.run_until_complete(asyncio.wait({connect}, timeout=2))
        _disconnect(loop, client)


def test_stop_begun_also_follows_the_component_state(loop: asyncio.AbstractEventLoop) -> None:
    from nautilus_trader.common.enums import ComponentState

    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    assert client._watchdog_stop_begun() is False
    assert client.state != ComponentState.STOPPING
    stopping = {ComponentState.STOPPING, ComponentState.STOPPED, ComponentState.DISPOSED}
    from breezy.adapters.polymarket_us import data

    assert stopping <= data._STOPPING_STATES
    assert ComponentState.RUNNING not in data._STOPPING_STATES
    assert ComponentState.STARTING not in data._STOPPING_STATES


def test_no_notify_without_the_opt_in_flag(loop: asyncio.AbstractEventLoop, notify: Any) -> None:
    client = build_watchdog_client(
        loop, FakeProvider([make_instrument(SLUG)]), watchdog_notify=False
    )
    loop.run_until_complete(client._connect())
    try:
        _pump(loop, 0.1)
        assert client._watchdog_pinger is None and client._watchdog_pinger_task is None
        assert drain(notify) == []
    finally:
        _disconnect(loop, client)


def test_type_simple_every_notify_is_a_noop_and_never_raises(
    loop: asyncio.AbstractEventLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Today's unit: no NOTIFY_SOCKET. The pinger runs, sends nothing and the client is intact."""
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    client = build_watchdog_client(loop, FakeProvider([make_instrument(SLUG)]))
    loop.run_until_complete(client._connect())
    try:
        _pump(loop, 0.1)
        pinger = client._watchdog_pinger
        assert pinger is not None and pinger.is_ready
        assert pinger.sample_failures == 0
        assert client.is_safe_mode is False
    finally:
        _disconnect(loop, client)


# ------------------------------------------------------------------- pinger body (EM2)


def _recorder(sent: list[str]) -> Any:
    def notify(message: str) -> bool:
        sent.append(message)
        return True

    return notify


def _bare(
    samples: Any,
    *,
    sent: list[str] | None = None,
    logger: ListLogger | None = None,
    clock: dict[str, int] | None = None,
) -> RecorderWatchdogPinger:
    clock = clock if clock is not None else {"now": MORNING}
    sent = sent if sent is not None else []
    return RecorderWatchdogPinger(
        read_sample=samples,
        clock_ns=lambda: clock["now"],
        logger=logger or ListLogger(),
        interval_s=0.001,
        notify=_recorder(sent),
        socket_present=True,
    )


def test_sample_exception_logs_recorder_sample_failed_counts_and_withholds() -> None:
    sent: list[str] = []
    log = ListLogger()
    clock = {"now": MORNING}

    def boom() -> RecorderSample:
        raise OSError("lstat failed")

    pinger = _bare(boom, sent=sent, logger=log, clock=clock)
    pinger.mark_ready()
    sent.clear()
    for _ in range(61):
        pinger.tick()
        clock["now"] += 5 * NS
    assert pinger.sample_failures == 61
    assert pinger.last_verdict == "sample_error"
    assert sent == []
    failed = log.messages("RECORDER_SAMPLE_FAILED")
    assert failed[0] == "RECORDER_SAMPLE_FAILED cause=OSError failures=1"
    assert failed[1] == "RECORDER_SAMPLE_FAILED cause=OSError failures=60"
    assert len(failed) == 2  # the first, then every 60th
    assert [level for level, m in log.lines if m.startswith("RECORDER_SAMPLE_FAILED")] == [
        "error"
    ] * 2


def test_sample_exception_never_ends_the_pinger(loop: asyncio.AbstractEventLoop) -> None:
    calls = {"n": 0}

    def flaky() -> RecorderSample:
        calls["n"] += 1
        if calls["n"] <= 3:
            raise ValueError("boom")
        return sample(MORNING)

    pinger = _bare(flaky)
    task = loop.create_task(pinger.run())
    loop.run_until_complete(asyncio.sleep(0.1))
    assert not task.done()
    assert calls["n"] > 5 and pinger.sample_failures == 3
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        loop.run_until_complete(task)


def test_pinger_death_logs_recorder_pinger_died(loop: asyncio.AbstractEventLoop) -> None:
    log = ListLogger()
    pinger = _bare(lambda: sample(MORNING), logger=log)

    async def dies() -> None:
        raise RuntimeError("the loop broke")

    task = loop.create_task(dies())
    task.add_done_callback(pinger.on_task_done)
    loop.run_until_complete(asyncio.sleep(0.01))
    assert log.messages("RECORDER_PINGER_DIED") == ["RECORDER_PINGER_DIED cause=RuntimeError"]
    # Cancellation is the only normal ending and is silent.
    quiet = ListLogger()
    other = _bare(lambda: sample(MORNING), logger=quiet)
    sleeper = loop.create_task(asyncio.sleep(10))
    sleeper.add_done_callback(other.on_task_done)
    sleeper.cancel()
    loop.run_until_complete(asyncio.sleep(0.01))
    assert quiet.messages("RECORDER_PINGER_DIED") == []


def test_pinger_runs_on_the_loop_thread(loop: asyncio.AbstractEventLoop) -> None:
    threads: list[int] = []

    def notify(message: str) -> bool:
        threads.append(threading.get_ident())
        return True

    pinger = RecorderWatchdogPinger(
        read_sample=lambda: sample(MORNING),
        clock_ns=lambda: MORNING,
        logger=ListLogger(),
        interval_s=0.005,
        notify=notify,
        socket_present=True,
    )
    pinger.mark_ready()

    async def drive() -> int:
        task = asyncio.get_running_loop().create_task(pinger.run())
        await asyncio.sleep(0.05)
        task.cancel()
        return threading.get_ident()

    loop_thread = loop.run_until_complete(drive())
    assert len(threads) > 3 and set(threads) == {loop_thread}


def test_gate_boot_line_reports_a_boolean_only(loop: asyncio.AbstractEventLoop) -> None:
    log = ListLogger()
    pinger = RecorderWatchdogPinger(
        read_sample=lambda: sample(MORNING),
        clock_ns=lambda: MORNING,
        logger=log,
        interval_s=0.005,
        notify=lambda m: False,
        socket_present=False,
    )

    async def drive() -> None:
        task = asyncio.get_running_loop().create_task(pinger.run())
        await asyncio.sleep(0.02)
        task.cancel()

    loop.run_until_complete(drive())
    assert log.messages("RECORDER_WATCHDOG_GATE") == [
        "RECORDER_WATCHDOG_GATE notify_socket_present=False"
    ]


def test_ready_requested_exactly_once_and_logged() -> None:
    sent: list[str] = []
    log = ListLogger()
    pinger = _bare(lambda: sample(MORNING), sent=sent, logger=log)
    assert pinger.mark_ready() is True
    assert pinger.mark_ready() is False
    assert sent == ["READY=1"]
    assert log.messages("RECORDER_WATCHDOG_READY") == ["RECORDER_WATCHDOG_READY sent=True"]


def test_a_raising_sender_never_ends_a_tick() -> None:
    def raises(message: str) -> bool:
        raise OSError("socket gone")

    pinger = RecorderWatchdogPinger(
        read_sample=lambda: sample(MORNING),
        clock_ns=lambda: MORNING,
        logger=ListLogger(),
        interval_s=5,
        notify=raises,
        socket_present=True,
    )
    pinger.mark_ready()
    assert pinger.tick() == "OK"
    assert pinger.sample_failures == 0


def test_phase_age_pre_ready_extends_then_stops_through_the_pinger() -> None:
    """End to end through the pinger: extension stops at the discovering overrun."""
    sent: list[str] = []
    clock = {"now": MORNING}
    started = {"ns": MORNING}
    pinger = _bare(
        lambda: sample(
            clock["now"],
            phase=PHASE_DISCOVERING,
            phase_started_ns=started["ns"],
            discovered_slugs=0,
            subscribed_count=0,
        ),
        sent=sent,
        clock=clock,
    )
    pinger.tick()
    assert sent == ["EXTEND_TIMEOUT_USEC=120000000"]
    clock["now"] = MORNING + 3901 * NS
    sent.clear()
    assert pinger.tick() == "discovering_overrun"
    assert sent == []
