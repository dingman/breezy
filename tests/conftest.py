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

``@pytest.mark.live`` (``tests/live/``) is the OTHER opt-out. Those tests
perform real network I/O against ``api.weather.gov`` by design, so a
``live``-marked test is exempted from the socket block exactly like an
``allow_socket``-marked one -- see :func:`_block_network_sockets`. They are
additionally gated by :func:`pytest_collection_modifyitems` below: deselected
by default (``pyproject.toml``'s ``addopts`` runs ``-m 'not live'``), and
even under an explicit ``-m live`` override they SKIP with a clear reason
unless ``BREEZY_LIVE=1`` is set, so a live test can never silently attempt
real network I/O from a job that merely overrode ``-m``.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest

_BLOCKED_MESSAGE = (
    "Network access is disabled in this test suite. "
    "If this test genuinely needs a real socket, mark it with "
    "@pytest.mark.allow_socket."
)

_LIVE_ENV_VAR = "BREEZY_LIVE"
_TEST_USER_AGENT = "breezy-test/1.0 (+mailto:ops@example.com)"


def pytest_configure(config: pytest.Config) -> None:
    """Register the opt-out markers so --strict-markers accepts them.

    ``live`` is already declared in ``pyproject.toml``'s ``markers`` list --
    declared again here is harmless (pytest merges the two) and keeps this
    file self-describing for anyone who reads it without the toml alongside.
    """
    config.addinivalue_line(
        "markers",
        "allow_socket: permit this test to open real network sockets "
        "(bypasses the autouse network-blocking fixture)",
    )
    config.addinivalue_line(
        "markers",
        "live: performs REAL network I/O against api.weather.gov and needs "
        f"{_LIVE_ENV_VAR}=1; deselected by default",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every ``live``-marked test unless ``BREEZY_LIVE=1`` is set.

    The default ``addopts`` (``-m 'not live'``) already keeps these OUT of an
    ordinary run via deselection, which is silent by design (deselected tests
    do not appear as skipped). This hook covers the other path: an explicit
    ``-m live`` invocation bypasses that default marker expression entirely,
    and without this hook a bare ``pytest -m live`` would attempt real network
    I/O unconditionally. Gating on the env var here, in the SAME place the
    marker itself is enforced, means there is exactly one place a live test's
    run/skip decision is made.
    """
    if os.environ.get(_LIVE_ENV_VAR) == "1":
        return
    skip_live = pytest.mark.skip(
        reason=(
            f"live test requires real network I/O against api.weather.gov; "
            f"set {_LIVE_ENV_VAR}=1 to run it"
        )
    )
    for item in items:
        if item.get_closest_marker("live") is not None:
            item.add_marker(skip_live)


def _blocked_connect(self: socket.socket, *args: Any, **kwargs: Any) -> None:
    raise RuntimeError(_BLOCKED_MESSAGE)


def _blocked_connect_ex(self: socket.socket, *args: Any, **kwargs: Any) -> int:
    raise RuntimeError(_BLOCKED_MESSAGE)


@pytest.fixture(autouse=True)
def _default_breezy_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREEZY_USER_AGENT", _TEST_USER_AGENT)


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
    if request.node.get_closest_marker("live") is not None:
        # `live` tests are real-network-by-design (`tests/live/`); gating
        # whether they RUN AT ALL is `pytest_collection_modifyitems`'s job,
        # not this fixture's -- by the time a `live` test reaches here it has
        # already been selected and (if unskipped) is meant to reach the
        # real host.
        yield
        return

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect_ex)
    yield
