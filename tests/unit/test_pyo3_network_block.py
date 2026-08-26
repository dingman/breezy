"""Regression tests for native pyo3 network blocking in ordinary pytest runs."""

from __future__ import annotations

import asyncio
import socket

import pytest
from nautilus_trader.core.nautilus_pyo3 import HttpClient as CapturedPyo3HttpClient


def _closed_loopback_port() -> int:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
    finally:
        listener.close()


def _looks_like_loopback_econnrefused(exc: BaseException, *, port: int) -> bool:
    text = str(exc)
    return (
        "127.0.0.1" in text
        and str(port) in text
        and ("Connection refused" in text or "os error 111" in text or "ECONNREFUSED" in text)
    )


@pytest.mark.asyncio
async def test_pyo3_http_client_captured_before_fixture_cannot_reach_os() -> None:
    port = _closed_loopback_port()

    python_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Network access is disabled"):
            python_socket.connect(("127.0.0.1", port))
    finally:
        python_socket.close()

    with pytest.raises(RuntimeError, match="Network access is disabled") as exc_info:
        client = CapturedPyo3HttpClient(timeout_secs=1)
        await asyncio.wait_for(
            client.get(f"http://127.0.0.1:{port}/", timeout_secs=1),
            timeout=3,
        )

    assert not _looks_like_loopback_econnrefused(exc_info.value, port=port), (
        "captured nautilus_pyo3.HttpClient reached the OS and got ECONNREFUSED "
        "while Python socket.connect was blocked"
    )
