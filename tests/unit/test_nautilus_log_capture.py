"""The Nautilus log-capture helper must fail closed, never return ``[]``."""

from __future__ import annotations

import pytest
from nautilus_trader.common.component import Logger

from tests.support.nautilus_log_capture import (
    VACUOUS_CAPTURE_MARKER,
    capture_nautilus_logs,
)


def test_capture_fails_loudly_when_nothing_is_logged() -> None:
    read = capture_nautilus_logs()
    with pytest.raises(AssertionError, match=VACUOUS_CAPTURE_MARKER):
        read()


def test_capture_fails_loudly_when_session_file_was_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tests.support.nautilus_log_capture as mod

    monkeypatch.setattr(mod, "_LOG_PATH", None)
    with pytest.raises(AssertionError, match=VACUOUS_CAPTURE_MARKER):
        capture_nautilus_logs()


def test_capture_returns_info_lines_written_after_the_snapshot() -> None:
    read = capture_nautilus_logs()
    Logger("BREEZY-TEST-CAPTURE").info("empty-discovery retry 1 remaining=600s next=30s")
    logged = read()
    assert any(
        "empty-discovery retry" in line and "remaining=" in line and "next=" in line
        for line in logged
    ), logged
