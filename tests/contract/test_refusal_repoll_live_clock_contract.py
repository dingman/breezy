"""FU-8b contract tests: ``install_refusal_repoll_timer`` under a REAL
``LiveClock`` and a REAL asyncio loop -- not the inline fakes
``tests/unit/test_component_health_watch_repoll_timer.py`` and
``tests/unit/test_trade_cli.py`` use.

Mirrors ``tests/contract/test_live_timer_thread_affinity.py``'s measured
facts: a ``LiveClock`` timer callback runs on a Rust/tokio thread, not the
asyncio loop thread, so the join under test here -- the
``loop.call_soon_threadsafe`` hop -- is the one thing that makes the handler
poll run where the msgbus trigger's dedupe sets expect it: the loop thread.

A failure in this module means the platform moved, or the hop regressed. Do
not relax an assertion to go green; re-measure instead.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock

from breezy.runtime.component_health_watch import install_refusal_repoll_timer

pytestmark = pytest.mark.contract

_INTERVAL = timedelta(milliseconds=50)
_WAIT_TIMEOUT_S = 15.0
_POLL_S = 0.01


async def _await_flag(flag: threading.Event, timeout: float = _WAIT_TIMEOUT_S) -> None:
    """Wait for a threading.Event without blocking the event loop.

    Idiom copied from ``test_live_timer_thread_affinity.py::_await_flag``:
    the flag is set from the Rust timer thread, so the loop must keep
    running for the callback's cross-thread submission to be serviced.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not flag.is_set():
        if loop.time() >= deadline:
            pytest.fail(f"repoll timer did not fire within {timeout}s")
        await asyncio.sleep(_POLL_S)


@pytest.mark.asyncio
async def test_live_clock_repoll_runs_handlers_on_the_event_loop_thread() -> None:
    """A mutant that drops the ``call_soon_threadsafe`` hop (calling the
    handler directly from ``_on_timer``) fails this: the handler would then
    observe the Rust/tokio thread, never the loop thread (L-33)."""
    loop_thread_ident = threading.get_ident()
    captured: dict[str, Any] = {}
    fired = threading.Event()

    def _handler(event: object) -> None:
        captured["ident"] = threading.get_ident()
        try:
            asyncio.get_running_loop()
            captured["running_loop"] = "present"
        except RuntimeError as exc:
            captured["running_loop"] = f"RuntimeError: {exc}"
        fired.set()

    clock = LiveClock()
    loop = asyncio.get_running_loop()
    cancel = install_refusal_repoll_timer(
        clock, loop=loop, handlers=(_handler,), interval=_INTERVAL
    )
    try:
        await _await_flag(fired)
    finally:
        cancel()

    assert captured["ident"] == loop_thread_ident
    assert captured["running_loop"] == "present"


@pytest.mark.asyncio
async def test_a_raising_handler_under_live_clock_is_logged_and_the_timer_keeps_firing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fires: list[int] = []
    enough = threading.Event()

    def _raiser(event: object) -> None:
        fires.append(len(fires) + 1)
        if len(fires) >= 3:
            enough.set()
        raise ValueError("deliberate failure inside a repoll handler")

    clock = LiveClock()
    loop = asyncio.get_running_loop()
    with caplog.at_level("ERROR"):
        cancel = install_refusal_repoll_timer(
            clock, loop=loop, handlers=(_raiser,), interval=_INTERVAL
        )
        try:
            await _await_flag(enough)
        finally:
            cancel()

    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) >= 3


def test_a_timer_armed_before_the_loop_runs_polls_once_the_loop_starts() -> None:
    """Arms the timer on a freshly-created, NOT-yet-running loop, then starts
    it. ``call_soon_threadsafe`` on a not-yet-running loop queues the
    callback until ``run_until_complete`` (measured, not assumed)."""
    loop = asyncio.new_event_loop()
    fired = threading.Event()
    captured: dict[str, Any] = {}

    def _handler(event: object) -> None:
        captured["ident"] = threading.get_ident()
        fired.set()

    clock = LiveClock()
    cancel = install_refusal_repoll_timer(
        clock, loop=loop, handlers=(_handler,), interval=_INTERVAL
    )

    async def _run_until_fired() -> None:
        deadline = loop.time() + _WAIT_TIMEOUT_S
        while not fired.is_set():
            if loop.time() >= deadline:
                raise AssertionError("repoll timer did not fire once the loop started")
            await asyncio.sleep(_POLL_S)

    try:
        loop.run_until_complete(_run_until_fired())
    finally:
        cancel()
        loop.close()

    assert fired.is_set()
    assert captured["ident"] == threading.get_ident()
