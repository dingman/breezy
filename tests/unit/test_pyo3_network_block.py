"""Regression tests for native pyo3 network blocking in ordinary pytest runs.

MEASURED CORRECTION (2026-08-27). The module-level
``from nautilus_trader.core.nautilus_pyo3 import HttpClient`` below does NOT
capture the real Rust class. ``conftest.pytest_configure`` installs the
constructor block, and pytest runs ``pytest_configure`` BEFORE it imports test
modules at collection -- so ``CapturedPyo3HttpClient`` is already
``conftest._BlockedPyo3NetworkClient``.

``test_pyo3_http_client_captured_before_fixture_cannot_reach_os`` therefore
asserts that the sentinel raises, which it does by construction. It passed
vacuously, and its name overstated what it covered. It is KEPT (it is a valid,
if weak, pin on the sentinel's behaviour) and
``test_the_captured_symbol_is_the_sentinel_not_the_real_class`` below pins the
vacuity explicitly so nobody mistakes it for proof of egress blocking again.

The real coverage is the two tests after it, plus barrier N1 in
``test_execution_egress_firewall_guard.py``. Both exist because the block was
measured to be escapable at the time: the ``nautilus_pyo3.network`` submodule
holds an independent attribute slot that the original block never touched, and
``SocketClient`` was not in the blocked-name list at all.
"""

from __future__ import annotations

import asyncio
import importlib
import socket
from typing import Any

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


def _pyo3_network_submodule() -> Any:
    """Import the ``network`` submodule dynamically.

    The shipped ``nautilus_pyo3.pyi`` is a single flat stub and does not
    declare the submodule, so a static ``from ... import network`` is an
    ``attr-defined`` error under ``mypy --strict`` even though the attribute
    exists at runtime. That stub/runtime divergence is itself part of why the
    submodule slot went unnoticed.
    """
    return importlib.import_module("nautilus_trader.core.nautilus_pyo3.network")


def test_the_captured_symbol_is_the_sentinel_not_the_real_class() -> None:
    """Pins WHY the test above cannot prove anything about real egress."""
    from tests.conftest import _BlockedPyo3NetworkClient

    captured: object = CapturedPyo3HttpClient
    assert captured is _BlockedPyo3NetworkClient


@pytest.mark.asyncio
async def test_the_network_submodule_import_path_is_also_blocked() -> None:
    """The escape that WAS open: a one-line supported import of the real class.

    Before 2026-08-27 this import yielded the genuine Rust client, and a GET
    against a closed loopback port returned ``Connection refused (os error
    111)`` -- proof of a real ``connect(2)`` -- while every gate read green.
    """
    network = _pyo3_network_submodule()

    port = _closed_loopback_port()
    with pytest.raises(RuntimeError, match="Network access is disabled") as exc_info:
        client = network.HttpClient(timeout_secs=1)
        await asyncio.wait_for(
            client.get(f"http://127.0.0.1:{port}/", timeout_secs=1),
            timeout=3,
        )
    assert not _looks_like_loopback_econnrefused(exc_info.value, port=port)


def test_the_raw_socket_client_is_blocked_at_every_import_path() -> None:
    """``SocketClient`` is raw TCP and was absent from the blocked-name list."""
    from nautilus_trader.core import nautilus_pyo3

    owners: tuple[Any, ...] = (nautilus_pyo3, _pyo3_network_submodule())
    for owner in owners:
        with pytest.raises(RuntimeError, match="Network access is disabled"):
            owner.SocketClient()
