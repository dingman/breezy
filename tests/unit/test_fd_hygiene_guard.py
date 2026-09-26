"""FU-16 regression guard: strategies a test starts and never stops must not
leak file descriptors past cleanup.

Root cause (measured, two independent parts -- see `stop_if_still_open`'s
docstring in `conftest.py` for the full mechanism):

1. ``ContinuousRungHoldStrategy.on_start`` (and ``CurrentRungHoldStrategy
   .on_start``) enters the trial-day latch into an ``ExitStack`` -- a
   ``SqliteStateStore`` db fd plus ``-wal``/``-shm``, and an ``os.open``
   flock fd from ``submit_intent.py`` whose holder has no ``__del__`` --
   released only by ``on_stop`` (``continuous_strategy.py``
   :793-804,1210-1223). ~228 strategy instances across the unit suite are
   started via ``.start()`` and never stopped, leaking these fds.
2. Nautilus's own message-bus subscriber bookkeeping keeps a bound method
   (e.g. ``self.on_data``) alive after ``on_stop``, forming a reference
   cycle back to the strategy -- and everything it holds, including the
   just-closed latch's ``SqliteStateStore`` -- that plain refcounting
   cannot free. Only ``.dispose()`` breaks it; a bare ``.stop()``/
   ``on_stop()`` (part 1 alone) still leaks the sqlite fds.

Each strategy is built inside its own helper-function call below (one
instance, one local scope) -- the same shape every real test in this suite
uses (one or a few strategies, function-scoped), never a single test holding
dozens of them alive in one list. That distinction matters empirically: with
every instance's only reference confined to the helper call that built it,
`stop_if_still_open` converges to exactly zero growth; a synthetic scenario
that keeps all N instances referenced in one list until the end measures
"still legitimately alive," not a leak, and does not match how the suite
actually uses these classes.

RED (before the fix): ``tests.unit.conftest.stop_if_still_open`` does not
exist -- this import fails. A version implementing only part 1 (stopping and
nothing else) leaves fd count growing by ~3 fds/cycle (sqlite db + ``-wal``
+ ``-shm``) even though every instance was "stopped" -- past
``_MAX_FD_GROWTH``.

GREEN: ``stop_if_still_open`` stops (or, for an instance started outside the
FSM, force-runs ``on_stop`` directly), disposes, then ``gc.collect()``s --
breaking the cycle so the sqlite fds are actually freed once the instance's
only reference (this helper call's local) goes out of scope.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit.conftest import stop_if_still_open
from tests.unit.test_continuous_rung_hold_strategy import _register_and_start

#: A handful of repeated start-without-stop cycles is enough to expose a
#: per-instance fd leak (sqlite db + `-wal` + `-shm`, plus the submit_intent
#: flock) without making the test slow.
_ITERATIONS = 20

#: Generous headroom over the true expected growth of 0 fds -- guards
#: against a regression, not a hard promise of exactly zero (e.g. an
#: unrelated one-time allocation).
_MAX_FD_GROWTH = 5


def _fd_count() -> int:
    return len(os.listdir(f"/proc/{os.getpid()}/fd"))


def _start_without_stopping_then_clean_up(store_path: Path) -> None:
    """One representative leaking cycle: build, start, never call `.stop()`
    -- exactly the pattern this suite's ~228 unstopped instances follow --
    then run the fix under test. The instance's only reference is this
    function's own local, so it is gone once this call returns.
    """
    strategy = _register_and_start(store_path=store_path, instruments=())
    stop_if_still_open([strategy])


def test_stop_if_still_open_bounds_fd_growth_across_start_without_stop_cycles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This suite's own `_stop_leaked_strategies` autouse fixture (the thing
    # under test) also wraps `on_start` and tracks every instance THIS test
    # creates in its own list, which would keep them referenced until this
    # test's teardown -- after this test's own assertion already ran,
    # defeating the fd measurement below. `undo()` strips that wrapping
    # (restoring the pristine `on_start`) so this test exercises
    # `stop_if_still_open` directly, standing in for what the fixture does.
    monkeypatch.undo()

    # Warm-up: absorb one-time Rust runtime fd allocation on first use, so it
    # is never mistaken for a per-cycle leak below.
    _start_without_stopping_then_clean_up(tmp_path / "warmup.db")

    baseline = _fd_count()
    for i in range(_ITERATIONS):
        _start_without_stopping_then_clean_up(tmp_path / f"state-{i}.db")
    grown = _fd_count() - baseline

    assert grown <= _MAX_FD_GROWTH, (
        f"fd count grew by {grown} across {_ITERATIONS} start-without-stop "
        "cycles even after stop_if_still_open ran -- a leak survived cleanup"
    )


def test_stop_if_still_open_is_idempotent_for_an_already_stopped_strategy(
    tmp_path: Path,
) -> None:
    strategy = _register_and_start(store_path=tmp_path / "state.db", instruments=())
    strategy.stop()
    assert strategy._exit_stack is None
    assert strategy.is_disposed is False

    # Must not raise, must not double-close anything the test's own
    # `.stop()` already released, and must still dispose (never called yet).
    stop_if_still_open([strategy])
    assert strategy.is_disposed is True

    # A second pass over an already-disposed instance must also be a no-op.
    stop_if_still_open([strategy])
