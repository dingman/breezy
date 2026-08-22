"""Repo-wide pytest fixtures.

This module is intentionally minimal: it exists to guarantee that no test in
this suite can reach the real network. Weather-settlement data is fetched
over HTTP from untrusted third parties (NWS), and a test suite that can
silently fall through to a live socket is a supply-chain risk in its own
right (flaky CI, accidental data exfiltration, accidental real requests to
a rate-limited government API).

``respx`` (used to mock ``httpx`` traffic) does NOT need real sockets — it
intercepts requests at the transport layer — so this fixture does not
conflict with respx-based tests.

Opt-out: mark an individual test with ``@pytest.mark.allow_socket`` if it
genuinely needs a real socket (e.g. a loopback-only integration test).
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_BLOCKED_MESSAGE = (
    "Network access is disabled in this test suite. "
    "If this test genuinely needs a real socket, mark it with "
    "@pytest.mark.allow_socket."
)


def pytest_configure(config: pytest.Config) -> None:
    """Register the opt-out marker so --strict-markers accepts it."""
    config.addinivalue_line(
        "markers",
        "allow_socket: permit this test to open real network sockets "
        "(bypasses the autouse network-blocking fixture)",
    )


def _blocked_connect(self: socket.socket, *args: Any, **kwargs: Any) -> None:
    raise RuntimeError(_BLOCKED_MESSAGE)


def _blocked_connect_ex(self: socket.socket, *args: Any, **kwargs: Any) -> int:
    raise RuntimeError(_BLOCKED_MESSAGE)


@pytest.fixture(autouse=True)
def _block_network_sockets(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Block real socket connections for every test unless opted out.

    Patches ``socket.socket.connect``/``connect_ex`` rather than the socket
    constructor, so socket *objects* can still be created (some libraries
    construct sockets for introspection without connecting), but any attempt
    to actually reach a peer raises immediately.
    """
    if request.node.get_closest_marker("allow_socket") is not None:
        yield
        return

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect_ex)
    yield
