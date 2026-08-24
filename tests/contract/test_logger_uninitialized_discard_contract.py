"""Contract test pinning `Logger`'s silent discard when logging is uninitialized.

Every assertion here was observed by execution against the pinned install
(nautilus-trader 1.231.0), not inferred from documentation. Run this FIRST on
any version bump: a failure means the platform moved, not that Breezy is
wrong.

This is why `breezy`'s pure modules (`normalize`, `settlement`, `domain`, ...)
use stdlib `logging` rather than `nautilus_trader.common.component.Logger`:
a Cython `Logger("X").error(...)` called before the process has initialized
the framework's logging subsystem produces NO output and raises NO exception
-- the record is silently dropped on the floor
(`common/component.pyx:1450-1451`, guarded by `is_logging_initialized()` at
`:1373-1376`). A module that only ever logs through the framework `Logger`,
and is exercised in a context where nothing has called `init_logging` yet
(e.g. a standalone script, an early-boot import, or a unit test), would look
like it is running cleanly while every `.error()` call vanishes.

Process isolation, deliberately
--------------------------------
`is_logging_initialized()` is backed by a global Rust flag with no reset: once
any code path in a process calls `init_logging` (`NautilusKernel.__init__`
does so unconditionally, see `system/kernel.py:194-231` -- and this very test
suite's `test_live_timer_thread_affinity.py` constructs a live kernel), the
flag stays `True` for the rest of that process, `LogGuard.__del__` included
(verified by execution: dropping the guard does not un-initialize it). Under
`pytest-randomly` a same-process test asserting "uninitialized" behaviour
would therefore be order-dependent -- true in isolation, silently wrong
whenever it happens to run after a kernel-constructing test. This test runs
its probe in a FRESH subprocess for exactly that reason: it must observe a
process that has never called `init_logging`, not "whatever this pytest
session's logging state happens to be right now."

Scope: `common/component.pyx` `Logger.error` (`:1529-1560`) and
`is_logging_initialized` (`:1373`). No network access.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.contract

_PROBE_SCRIPT = """
import sys
from nautilus_trader.common.component import Logger, is_logging_initialized

assert not is_logging_initialized(), "logging was already initialized -- probe process is contaminated"

logger = Logger("CONTRACT-PROBE")
logger.error("THIS-MUST-NOT-APPEAR-error")
logger.warning("THIS-MUST-NOT-APPEAR-warning")
logger.info("THIS-MUST-NOT-APPEAR-info")

# Still uninitialized: nothing about calling the logger flips the flag.
assert not is_logging_initialized()

print("PROBE-COMPLETED-NO-EXCEPTION")
"""


def _run_probe() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _PROBE_SCRIPT],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_error_call_before_logging_init_produces_no_output_and_raises_nothing() -> None:
    """`common/component.pyx:1529-1560` -- `Logger.error` checks
    `logging_is_initialized()` (`:1450` is the twin check inside `debug`; the
    `error` method's own check is at the same guard pattern a few lines down)
    and returns immediately, WITHOUT raising, when the subsystem is not yet
    initialized. The three log calls' message text must not appear anywhere
    in stdout or stderr, and the process must exit 0 -- proving no exception
    propagated.
    """
    result = _run_probe()

    assert result.returncode == 0, f"probe process failed: {result.stderr}"
    assert "PROBE-COMPLETED-NO-EXCEPTION" in result.stdout
    combined = result.stdout + result.stderr
    assert "THIS-MUST-NOT-APPEAR" not in combined


def test_a_freshly_initialized_logger_in_the_same_probe_does_emit_output() -> None:
    """Companion/control test: proves the probe harness itself is capable of
    observing Logger output, so the previous test's silence is meaningful
    evidence of the discard rather than an artifact of a broken probe (e.g.
    output capture not working, or the subprocess crashing before it reaches
    the log calls).
    """
    script = """
from nautilus_trader.common.component import Logger, init_logging
from nautilus_trader.model.identifiers import TraderId

init_logging(trader_id=TraderId("CONTRACT-PROBE-001"))
logger = Logger("CONTRACT-PROBE")
logger.error("THIS-MUST-APPEAR-once-initialized")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"probe process failed: {result.stderr}"
    combined = result.stdout + result.stderr
    assert "THIS-MUST-APPEAR-once-initialized" in combined
