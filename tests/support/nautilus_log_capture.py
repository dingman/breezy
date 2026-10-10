"""Capture Nautilus ``Component._log`` lines without pytest ``capfd``.

Nautilus's Rust logger is process-global and is initialized exactly once
(``init_logging`` at ``$NT/common/component.pyx:1253-1367`` raises
``RuntimeError`` on a second call). ``LogGuard.__del__`` calls ``logger_drop``
(``:1248-1250``) but does **not** clear the initialized flag: after dropping
the guard, ``is_logging_initialized()`` stays True and re-init still raises.
``NautilusKernel.dispose`` also leaves the guard in place on purpose
(``$NT/system/kernel.py:1118-1119``).

Two consequences for tests:

1. The first ``BacktestEngine`` in a session freezes the stdout level (Breezy's
   harness defaults to ``WARNING`` at ``src/breezy/runtime/backtest_harness.py:700-703``).
   Later INFO lines such as ``empty-discovery retry`` are filtered.
2. The logger clones its stdout handle at init. A later ``capfd`` ``dup2`` of
   fd 1 does not intercept those writes -- they keep going to the original
   handle, so ``capfd.readouterr()`` returns ``[]`` even when ERROR lines are
   visibly leaking to the terminal.

This module therefore initializes logging **first**, with a file at INFO, and
tests read that file. Empty capture is an error, not a vacuous ``any([])``.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from nautilus_trader.common.component import (
    Logger,
    flush_logger,
    init_logging,
    is_logging_initialized,
    sync_logger_to_disk,
)
from nautilus_trader.common.enums import LogLevel

#: Distinctive phrase in every capture-failure ``AssertionError``. Tests match
#: on this rather than on incidental prose so a missing log line cannot be
#: confused with "the capture subsystem returned nothing".
VACUOUS_CAPTURE_MARKER = "vacuous capture"

_LOG_GUARD: object | None = None
_LOG_PATH: Path | None = None


def install_session_logging() -> None:
    """Initialize Nautilus logging once, with an INFO file, before any test.

    Must run from ``pytest_configure`` so it precedes the first
    ``BacktestEngine``. If logging is already initialized, this is a no-op and
    :func:`capture_nautilus_logs` will fail loudly rather than return ``[]``.
    """
    global _LOG_GUARD, _LOG_PATH
    if is_logging_initialized():
        return
    log_dir = Path(tempfile.mkdtemp(prefix="breezy-nautilus-logs-"))
    _LOG_PATH = log_dir / "nautilus.log"
    _LOG_GUARD = init_logging(
        level_stdout=LogLevel.WARNING,
        level_file=LogLevel.INFO,
        directory=str(log_dir),
        file_name="nautilus",
    )


def _flush() -> None:
    flush_logger()
    sync_logger_to_disk()


def _fail_vacuous(detail: str) -> NoReturn:
    raise AssertionError(
        f"Nautilus log capture failed ({VACUOUS_CAPTURE_MARKER}): {detail} "
        f"is_logging_initialized={is_logging_initialized()!r} log_path={_LOG_PATH!r}"
    )


def capture_nautilus_logs() -> Callable[[], list[str]]:
    """Return a reader of Nautilus log lines written after this call.

    Fails immediately if INFO file-capture is not working, and the reader fails
    if it would otherwise return no lines. An empty list is never a success.
    """
    log_path = _LOG_PATH
    if log_path is None:
        _fail_vacuous(
            "session file logging was not installed; the process-global logger "
            "was already initialized without a file (typically a BacktestEngine "
            "constructed before pytest_configure), so INFO lines cannot be read"
        )

    _flush()
    canary = f"breezy-log-capture-canary-{uuid.uuid4().hex}"
    Logger("BREEZY-TEST-CAPTURE").info(canary)
    _flush()
    if not log_path.exists():
        _fail_vacuous(f"expected log file was not created after canary write: {log_path}")
    logged = log_path.read_text(encoding="utf-8")
    if canary not in logged:
        _fail_vacuous(
            f"wrote INFO canary {canary!r} but it did not appear in {log_path}; "
            "the process-global logger is dropping INFO or is not writing the file"
        )
    start = log_path.stat().st_size

    def _read() -> list[str]:
        _flush()
        data = log_path.read_bytes()[start:]
        lines = data.decode("utf-8").splitlines()
        if not lines:
            _fail_vacuous(
                f"reader returned no lines; start_offset={start} size={log_path.stat().st_size}"
            )
        return lines

    return _read


#: Upper bound on how long Nautilus's asynchronous Rust logger may take to
#: deliver a line to the capture file under CPU load.
LOG_DELIVERY_TIMEOUT_S = 2.0
_LOG_POLL_INTERVAL_S = 0.02


def wait_for_logged(
    read: Callable[[], list[str]],
    *needles: str,
    timeout_s: float = LOG_DELIVERY_TIMEOUT_S,
) -> str:
    """Poll ``read`` until every needle appears; return the text read so far.

    The Rust logger writes on its own thread, so a line emitted just before the
    call may land after a single read. The wait is bounded and polls the
    *delivery* of the same line; it never relaxes what is asserted -- callers
    still assert each needle on the returned text. A reader that has nothing
    yet raises (see :func:`capture_nautilus_logs`); that is treated as "not
    delivered yet" until the deadline, when the last error is re-raised.
    """
    deadline = time.monotonic() + timeout_s
    text = ""
    while True:
        try:
            text = "\n".join(read())
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
        else:
            if all(needle in text for needle in needles) or time.monotonic() >= deadline:
                return text
        time.sleep(_LOG_POLL_INTERVAL_S)
