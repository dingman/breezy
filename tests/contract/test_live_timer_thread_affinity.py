"""Contract tests pinning WHERE a ``LiveClock`` timer callback actually runs.

Measured against nautilus-trader 1.231.0 on 2026-08-22 by executing every
assertion below (raw ``LiveClock`` and a real live-environment
``NautilusKernel`` + ``Actor``; both paths agree).

The finding, in one line:

    A ``LiveClock`` timer callback runs on a Rust/tokio-owned thread that
    Python sees as a ``_DummyThread``.  It is NOT the asyncio event-loop
    thread, there is NO running loop on it, and ``asyncio.create_task``
    therefore raises ``RuntimeError: no running event loop``.

Why this file exists.  Breezy's NWS ingest Actor polls on a ``LiveClock``
timer.  The timer callback is unconditionally synchronous, and
``Actor.run_in_executor`` cannot host the poll because it discards its
callable's return value and hands back a ``TaskId`` -- a frozen dataclass
around a UUID with no ``add_done_callback``, hence no supervision seam.  The
obvious bridge, ``asyncio.create_task`` inside the callback, does not work:
it raises, polling never starts, and the task-supervision path that drives
the settlement gate to BLOCKED silently does not exist.

The primitive that DOES work is ``asyncio.run_coroutine_threadsafe(coro,
loop)``.  It needs an explicit loop reference, and base ``Actor`` exposes
none -- so this file also pins the public, non-private-attribute place a loop
reference can be obtained: ``asyncio.get_running_loop()`` called inside
``on_start``, which in a live kernel runs on the loop thread.

``TestClock`` proves nothing here: it fires inline on the caller's thread, so
a backtest-mode measurement reports a comfortable and misleading answer.  The
final test pins that divergence so nobody "verifies" this with a backtest.

A failure in this module means the platform moved.  Re-measure before
changing ``breezy.ingest``; do not relax an assertion to go green.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import threading
from datetime import timedelta
from typing import Any

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import LiveClock, TestClock
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.common.executor import TaskId
from nautilus_trader.config import LoggingConfig
from nautilus_trader.live.config import TradingNodeConfig
from nautilus_trader.system.kernel import NautilusKernel

pytestmark = pytest.mark.contract

_INTERVAL = timedelta(milliseconds=50)
_WAIT_TIMEOUT_S = 15.0
_POLL_S = 0.01


async def _await_flag(flag: threading.Event, timeout: float = _WAIT_TIMEOUT_S) -> None:
    """Wait for a threading.Event without blocking the event loop.

    The flag is set from the Rust timer thread, so the loop must keep
    running for the callback's cross-thread submissions to be serviced.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not flag.is_set():
        if loop.time() >= deadline:
            pytest.fail(f"timer callback did not fire within {timeout}s")
        await asyncio.sleep(_POLL_S)


async def _noop() -> str:
    return "coroutine-ran"


async def _boom() -> str:
    raise ValueError("poll failed")


# ---------------------------------------------------------------------------
# 1. Thread identity and loop availability (raw LiveClock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_liveclock_timer_callback_runs_off_the_event_loop_thread() -> None:
    """The callback lands on a foreign (Rust/tokio) thread, not the loop thread."""
    loop_thread_ident = threading.get_ident()
    captured: dict[str, Any] = {}
    fired = threading.Event()

    def _callback(event: Any) -> None:
        captured["ident"] = threading.get_ident()
        captured["is_main_thread"] = threading.current_thread() is threading.main_thread()
        # Python has no Thread object for a thread it did not create, so it
        # fabricates a `_DummyThread`. That class name IS the evidence that
        # the thread came from Rust.
        captured["thread_class"] = type(threading.current_thread()).__name__
        try:
            asyncio.get_running_loop()
            captured["running_loop"] = "present"
        except RuntimeError as exc:
            captured["running_loop"] = f"RuntimeError: {exc}"
        fired.set()

    clock = LiveClock()
    try:
        clock.set_timer(name="probe", interval=_INTERVAL, callback=_callback)
        await _await_flag(fired)
    finally:
        clock.cancel_timers()

    assert captured["ident"] != loop_thread_ident
    assert captured["is_main_thread"] is False
    assert captured["thread_class"] == "_DummyThread"
    assert captured["running_loop"] == "RuntimeError: no running event loop"


@pytest.mark.asyncio
async def test_asyncio_create_task_inside_a_timer_callback_raises() -> None:
    """`asyncio.create_task` is NOT usable inside a LiveClock timer callback.

    This is the whole design ruling. If this ever passes, the simpler
    ``create_task`` + ``add_done_callback`` bridge becomes available and
    ``breezy.ingest`` should be simplified -- but only after re-measuring.
    """
    captured: dict[str, Any] = {}
    fired = threading.Event()

    def _callback(event: Any) -> None:
        coro = _noop()
        try:
            asyncio.create_task(coro)
            captured["outcome"] = "created"
        except RuntimeError as exc:
            captured["outcome"] = f"RuntimeError: {exc}"
            coro.close()  # avoid an un-awaited-coroutine warning
        finally:
            fired.set()

    clock = LiveClock()
    try:
        clock.set_timer(name="probe", interval=_INTERVAL, callback=_callback)
        await _await_flag(fired)
    finally:
        clock.cancel_timers()

    assert captured["outcome"] == "RuntimeError: no running event loop"


# ---------------------------------------------------------------------------
# 2. The primitive that works, and the supervision seam it provides
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_coroutine_threadsafe_is_the_working_bridge() -> None:
    """`run_coroutine_threadsafe` crosses the thread boundary and returns a handle."""
    loop = asyncio.get_running_loop()
    captured: dict[str, Any] = {}
    fired = threading.Event()

    def _callback(event: Any) -> None:
        future = asyncio.run_coroutine_threadsafe(_noop(), loop)
        captured["future_type"] = type(future)
        captured["has_add_done_callback"] = hasattr(future, "add_done_callback")
        captured["result"] = future.result(timeout=_WAIT_TIMEOUT_S)
        fired.set()

    clock = LiveClock()
    try:
        clock.set_timer(name="probe", interval=_INTERVAL, callback=_callback)
        await _await_flag(fired)
    finally:
        clock.cancel_timers()

    # Note: a `concurrent.futures.Future`, NOT an `asyncio.Task`.
    assert captured["future_type"] is concurrent.futures.Future
    assert captured["has_add_done_callback"] is True
    assert captured["result"] == "coroutine-ran"


@pytest.mark.asyncio
async def test_failed_poll_reaches_a_done_callback_so_the_gate_can_fail_closed() -> None:
    """An exception inside the coroutine IS observable via the future's done callback.

    This is the seam that lets a dead poll transition the settlement gate to
    BLOCKED. Without it, a poll can die and nothing notices.
    """
    loop = asyncio.get_running_loop()
    observed: dict[str, Any] = {}
    handled = threading.Event()

    def _on_done(future: concurrent.futures.Future[str]) -> None:
        observed["exception"] = future.exception()
        handled.set()

    def _callback(event: Any) -> None:
        future = asyncio.run_coroutine_threadsafe(_boom(), loop)
        future.add_done_callback(_on_done)

    clock = LiveClock()
    try:
        clock.set_timer(name="probe", interval=_INTERVAL, callback=_callback)
        await _await_flag(handled)
    finally:
        clock.cancel_timers()

    assert isinstance(observed["exception"], ValueError)
    assert str(observed["exception"]) == "poll failed"


@pytest.mark.asyncio
async def test_exception_in_a_timer_callback_is_swallowed_and_the_timer_keeps_firing() -> None:
    """Rust catches and logs the exception; it never reaches Python callers.

    Consequence: supervision cannot rely on an exception escaping the
    callback. It must be explicit, via the future returned by
    ``run_coroutine_threadsafe``.
    """
    fires: list[int] = []
    enough = threading.Event()

    def _callback(event: Any) -> None:
        fires.append(len(fires) + 1)
        if len(fires) >= 3:
            enough.set()
        raise ValueError("deliberate failure inside a LiveClock timer callback")

    clock = LiveClock()
    try:
        clock.set_timer(name="probe", interval=_INTERVAL, callback=_callback)
        await _await_flag(enough)
    finally:
        clock.cancel_timers()

    # Fired repeatedly despite raising every time.
    assert len(fires) >= 3


# ---------------------------------------------------------------------------
# 3. Why `Actor.run_in_executor` cannot host the poll
# ---------------------------------------------------------------------------


def test_actor_run_in_executor_gives_no_supervision_seam() -> None:
    """`run_in_executor` returns a `TaskId` (a UUID), discarding the return value."""
    actor = Actor(ActorConfig(component_id="CONTRACT-PROBE"))
    returned: list[str] = []

    task_id = actor.run_in_executor(lambda: returned.append("ran") or "discarded")

    assert isinstance(task_id, TaskId)
    assert dataclasses.is_dataclass(task_id)
    assert [f.name for f in dataclasses.fields(task_id)] == ["value"]
    assert not hasattr(task_id, "add_done_callback")
    assert not hasattr(task_id, "result")
    assert returned == ["ran"]  # ran inline (no executor registered), result dropped


def test_base_actor_exposes_no_public_event_loop_reference() -> None:
    """There is no `Actor.loop`; the loop must be captured in `on_start`.

    If a future version adds one, this fails RED and Breezy should switch to
    the native accessor instead of capturing the loop itself.
    """
    actor = Actor(ActorConfig(component_id="CONTRACT-PROBE"))

    assert [name for name in dir(actor) if "loop" in name.lower()] == []


# ---------------------------------------------------------------------------
# 4. The same measurement through a real live kernel + Actor
# ---------------------------------------------------------------------------


class _ProbeActor(Actor):
    """Smallest Actor that measures its own timer callback's thread context."""

    def __init__(self, config: ActorConfig) -> None:
        super().__init__(config)
        self.loop_ref: asyncio.AbstractEventLoop | None = None
        self.on_start_thread_ident: int | None = None
        self.observations: list[dict[str, Any]] = []
        self.fired = threading.Event()

    def on_start(self) -> None:
        self.on_start_thread_ident = threading.get_ident()
        # PUBLIC loop capture: in a live kernel `on_start` is awaited ON the
        # event loop thread, so `get_running_loop()` yields the kernel's loop.
        # No private attribute, no monkeypatching. In a backtest this raises,
        # which is the correct signal that the bridge is not needed there.
        self.loop_ref = asyncio.get_running_loop()
        self.clock.set_timer(name="probe", interval=_INTERVAL, callback=self._on_timer)

    def _on_timer(self, event: Any) -> None:
        record: dict[str, Any] = {
            "ident": threading.get_ident(),
            "thread_class": type(threading.current_thread()).__name__,
        }
        try:
            asyncio.get_running_loop()
            record["running_loop"] = "present"
        except RuntimeError as exc:
            record["running_loop"] = f"RuntimeError: {exc}"

        coro = _noop()
        try:
            asyncio.create_task(coro)
            record["create_task"] = "created"
        except RuntimeError as exc:
            record["create_task"] = f"RuntimeError: {exc}"
            coro.close()

        assert self.loop_ref is not None
        future = asyncio.run_coroutine_threadsafe(_noop(), self.loop_ref)
        record["bridge_result"] = future.result(timeout=_WAIT_TIMEOUT_S)

        self.observations.append(record)
        self.fired.set()


@pytest.mark.asyncio
async def test_live_kernel_actor_timer_callback_thread_context() -> None:
    """End-to-end: a live-environment kernel reproduces the raw-clock finding.

    No network, no venue: the node config declares zero data and exec clients,
    so nothing connects. The clock, engines and executor wiring are the real
    live ones.
    """
    loop = asyncio.get_running_loop()
    config = TradingNodeConfig(
        trader_id="CONTRACT-001",
        logging=LoggingConfig(log_level="ERROR"),
        timeout_connection=5.0,
        timeout_disconnection=5.0,
        timeout_post_stop=2.0,
    )
    kernel = NautilusKernel(name="ContractProbe", config=config, loop=loop)
    actor = _ProbeActor(ActorConfig(component_id="CONTRACT-PROBE"))
    kernel.trader.add_actor(actor)

    try:
        await kernel.start_async()
        assert type(actor.clock).__name__ == "LiveClock"
        await _await_flag(actor.fired)
    finally:
        actor.clock.cancel_timers()
        await kernel.stop_async()
        kernel.dispose()

    # `on_start` ran on the loop thread and yielded the kernel's own loop.
    assert actor.on_start_thread_ident == threading.get_ident()
    assert actor.loop_ref is loop

    record = actor.observations[0]
    assert record["ident"] != threading.get_ident()
    assert record["thread_class"] == "_DummyThread"
    assert record["running_loop"] == "RuntimeError: no running event loop"
    assert record["create_task"] == "RuntimeError: no running event loop"
    assert record["bridge_result"] == "coroutine-ran"


# ---------------------------------------------------------------------------
# 5. Why a backtest measurement would have lied
# ---------------------------------------------------------------------------


def test_testclock_fires_inline_on_the_caller_thread() -> None:
    """`TestClock` handlers run on whichever thread drains them.

    So a backtest-mode measurement of this question reports "same thread,
    loop available" and is worthless as evidence about live behaviour.
    """
    seen: list[int] = []

    def _callback(event: Any) -> None:
        seen.append(threading.get_ident())

    clock = TestClock()
    clock.set_time_alert_ns(name="probe", alert_time_ns=1_000_000, callback=_callback)
    for handler in clock.advance_time(to_time_ns=2_000_000):
        handler.handle()

    assert seen == [threading.get_ident()]
