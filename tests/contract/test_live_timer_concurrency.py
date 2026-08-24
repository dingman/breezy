"""Contract tests pinning whether TWO ``LiveClock`` timers share a thread.

Measured against nautilus-trader 1.231.0 by executing every assertion below.

The finding, in one line:

    There is NO "one tokio timer thread".  Two ``LiveClock`` timers scheduled
    to fire at the same instant are observed running CONCURRENTLY -- overlapping
    in wall-clock time, on DISTINCT threads.

Why this file exists.  ``breezy.ingest.nws_actor`` reasons in several comments
from an assumption about "one tokio timer thread", and its ``_submit`` bound is
a check-then-act pair on a shared ``set``.  Whether that pair can actually be
interleaved depends entirely on the question above -- and nothing in the suite
measured it.  ``tests/contract/test_live_timer_thread_affinity.py`` pins that a
*single* timer callback runs off the loop thread, which is a different question
and says nothing about two of them.  The Actor arms TWO timers (the poll
cadence and the final-overdue alert), so this is not hypothetical.

**Why the assumption was believable, and what was NOT provable.**  A SINGLE
timer usually reuses one worker: 30 consecutive firings of a fast callback
landed on one ident in 12 of 12 standalone runs, and so did 40 firings of a
callback blocking its worker for 50 ms, in 6 of 6.  So a one-timer experiment
measures confinement and invites the conclusion that ``_submit`` cannot be
re-entered concurrently.

That confinement is REUSE BY AN IDLE POOL, not a guarantee, and an attempt to
pin it as one was withdrawn for flakiness: asserting a single timer's firings
all share an ident failed 3 times in 12 runs under pytest (two idents observed,
e.g. ``[131594167740096, 131594178246336]``), even though it never failed
standalone.  A warmer runtime migrates it.  No assertion about single-timer
thread identity appears below, because none is true.  The finding stands as
prose: single-timer confinement is common, unreliable, and must not be
depended on.

**How the concurrency is measured, and why not with a barrier.**  The first
attempt rendezvoused the two callbacks at a single-use ``threading.Barrier(2)``.
That was rejected as flaky (3 failures in 15 runs): the FIRST pair of firings is
not reliably co-scheduled, and one missed rendezvous breaks a barrier
permanently, so the test reported "serialised" on what was really a slow start.
The measurement used instead is a direct temporal one -- each callback records
``perf_counter_ns`` on entry and exit while occupying its worker, and the test
asserts that some cross-timer pair of intervals genuinely overlaps.  Over a
bounded window of 40 firings this was observed in 20 of 20 runs with a minimum
of 11 overlapping pairs, so the ``>= 1`` threshold below carries an order-of-
magnitude margin rather than resting on timing luck.

**This file does not license any behaviour in ``breezy.ingest``.**  The
in-flight cap is held under a single lock across check-and-insert regardless of
what this file measures, because correctness must not rest on an undocumented
runtime scheduling detail that a version bump is free to change.  The job here
is to make that detail VISIBLE and to fail loudly if it ever moves.

A failure in this module means the platform moved.  Re-measure before changing
``breezy.ingest``; do not relax an assertion to go green.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock

pytestmark = pytest.mark.contract

_INTERVAL = timedelta(milliseconds=50)
_START_DELAY = timedelta(milliseconds=200)
#: Long enough that a genuinely concurrent pair overlaps observably, short
#: enough that 40 firings at a 50 ms cadence stay inside a second or two.
_OCCUPY_S = 0.03
_SAMPLES = 40
_WAIT_TIMEOUT_S = 30.0
_POLL_S = 0.01


@dataclass(frozen=True)
class _Firing:
    """One timer callback's thread identity and its wall-clock extent."""

    timer: str
    ident: int
    entered_ns: int
    exited_ns: int

    def overlaps(self, other: _Firing) -> bool:
        return self.entered_ns < other.exited_ns and other.entered_ns < self.exited_ns


async def _await_flag(flag: threading.Event, timeout: float = _WAIT_TIMEOUT_S) -> None:
    """Wait for a threading.Event without blocking the event loop.

    The flag is set from a Rust timer thread, so the loop must keep turning.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not flag.is_set():
        if loop.time() >= deadline:
            pytest.fail(f"timer callbacks did not produce enough samples within {timeout}s")
        await asyncio.sleep(_POLL_S)


@pytest.mark.asyncio
async def test_two_concurrent_liveclock_timers_run_at_the_same_time_on_distinct_threads() -> None:
    """Two timers armed for the same instant execute CONCURRENTLY.

    This is the measurement that decides whether the ``_submit`` in-flight cap's
    check-then-act pair is reachable at all. If the two timers were serialised
    onto one thread, two callbacks could never be inside ``_submit`` at once. They
    are not serialised, so it is reachable -- and the lock must span both halves.

    Overlapping wall-clock intervals are the evidence, not merely unequal thread
    idents: two firings that never coexist could reuse a thread id sequentially
    and prove nothing. An overlap means both callbacks were genuinely in flight
    together, which is precisely the precondition for the interleaving.
    """
    firings: list[_Firing] = []
    lock = threading.Lock()
    enough = threading.Event()

    def _make(name: str) -> Any:
        def _callback(event: Any) -> None:
            entered = time.perf_counter_ns()
            # Occupy the worker so a genuine overlap is observable. `_submit` is
            # not instantaneous either: it takes a lock and calls
            # `run_coroutine_threadsafe`.
            time.sleep(_OCCUPY_S)
            exited = time.perf_counter_ns()
            with lock:
                firings.append(_Firing(name, threading.get_ident(), entered, exited))
                if len(firings) >= _SAMPLES:
                    enough.set()

        return _callback

    clock = LiveClock()
    start = clock.utc_now() + _START_DELAY
    try:
        clock.set_timer(name="alpha", interval=_INTERVAL, start_time=start, callback=_make("alpha"))
        clock.set_timer(name="beta", interval=_INTERVAL, start_time=start, callback=_make("beta"))
        await _await_flag(enough)
    finally:
        clock.cancel_timers()

    with lock:
        observed = list(firings)

    assert {firing.timer for firing in observed} == {"alpha", "beta"}, (
        f"both timers must have fired: {sorted({f.timer for f in observed})}"
    )
    assert threading.get_ident() not in {firing.ident for firing in observed}, (
        "no timer callback may run on the event-loop thread"
    )

    concurrent_pairs = [
        (first, second)
        for index, first in enumerate(observed)
        for second in observed[index + 1 :]
        if first.timer != second.timer and first.overlaps(second)
    ]
    assert concurrent_pairs, (
        "two LiveClock timers scheduled for the same instant never overlapped in "
        f"{len(observed)} firings, so this runtime SERIALISES them. That is not a "
        "correctness regression for `breezy.ingest` -- the in-flight cap holds one lock "
        "across check-and-insert regardless -- but `nws_actor`'s threading comments and "
        "this file's finding must both be re-measured"
    )
    assert all(first.ident != second.ident for first, second in concurrent_pairs), (
        "two callbacks overlapped in time yet reported the same thread identity, which "
        "is impossible; the measurement itself is wrong"
    )
