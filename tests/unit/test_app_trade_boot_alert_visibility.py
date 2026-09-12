"""A-B1 lifecycle coverage (SP-6 row 5c): the boot window is real.

Before ``trade_cli.py``'s ``install_logging_bridge()`` ever runs, the
``breezy`` namespace has no handler at all, and stdlib's own fallback
(``logging.lastResort``) is a WARNING-only ``_StderrHandler`` -- an INFO
record logged in that window is silently dropped. ``_ensure_boot_logging_visible``
(``breezy.app.trade``) closes that gap for the dedicated boot-audit logger
AND, via ``logging_bridge.ensure_stderr_visible``, for ``breezy.runtime.health``
(A1's sink-selection line, A2's delivery receipt).

These tests drive ``sys.stderr`` redirected to a real ``io.StringIO``
BEFORE calling ``_ensure_boot_logging_visible``, exactly matching a real
process's stderr -- never ``caplog``, which attaches its own handler and
would make the very gap under test invisible.
"""

from __future__ import annotations

import io
import logging

import pytest

from breezy.app import trade as trade_module
from breezy.runtime import logging_bridge
from breezy.runtime.health import (
    HEALTH_LOGGER_NAME,
    AlertPayload,
    emit_alert,
    resolve_alert_sink,
)


class _FakeNautilusLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def debug(self, message: str) -> None:
        self.calls.append(("debug", message))

    def info(self, message: str) -> None:
        self.calls.append(("info", message))

    def warning(self, message: str) -> None:
        self.calls.append(("warning", message))

    def error(self, message: str) -> None:
        self.calls.append(("error", message))


@pytest.fixture(autouse=True)
def _clean_boot_and_bridge_state() -> object:
    """Both loggers this module touches carry process-global handler
    state (``_boot_logger`` in ``app/trade.py``, ``breezy.runtime.health``
    via ``ensure_stderr_visible``, and the ``breezy`` bridge namespace
    itself) -- reset all three before AND after every test here."""

    def _reset() -> None:
        logging_bridge.uninstall()
        for name in (trade_module._BOOT_LOGGER_NAME, HEALTH_LOGGER_NAME):
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
            logger.setLevel(logging.NOTSET)

    _reset()
    yield
    _reset()


def test_the_boot_window_selection_line_reaches_a_real_stderr_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stderr", buffer)

    trade_module._ensure_boot_logging_visible()
    resolve_alert_sink({})  # unconfigured branch -> LoggingAlertSink

    assert "LoggingAlertSink" in buffer.getvalue()
    assert "unconfigured" in buffer.getvalue()


def test_the_boot_window_receipt_reaches_a_real_stderr_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stderr", buffer)

    trade_module._ensure_boot_logging_visible()
    sink = resolve_alert_sink({})
    emit_alert(
        sink,
        AlertPayload(severity="WARN", event="E", site="global", detail="d"),
    )

    assert "breezy alert delivered" in buffer.getvalue()
    assert "sink=LoggingAlertSink" in buffer.getvalue()


def test_after_the_bridge_is_installed_the_record_goes_to_the_bridge_and_not_twice_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stderr", buffer)
    trade_module._ensure_boot_logging_visible()

    fake_nautilus = _FakeNautilusLogger()
    logging_bridge.install(fake_nautilus)

    sink = resolve_alert_sink({})
    emit_alert(
        sink,
        AlertPayload(severity="WARN", event="E", site="global", detail="d"),
    )

    # The record reached the bridge (forwarded to the fake Nautilus logger)...
    assert any("breezy alert delivered" in message for _level, message in fake_nautilus.calls)
    # ...and did NOT also reach the boot-window stderr handler a second time.
    assert "breezy alert delivered" not in buffer.getvalue()
