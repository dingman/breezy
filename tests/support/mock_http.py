"""Install an ``httpx.MockTransport`` under every client a transport builds.

Transports construct their own ``httpx.AsyncClient`` / ``httpx.Client`` with
hardened kwargs. Patching the two constructors keeps production code free of
a test-injection knob while still letting a test (a) answer every request from
a handler and (b) read back the exact kwargs the hardened client was built
with. No socket is ever opened.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

Handler = Callable[[httpx.Request], httpx.Response]

# Captured once at import so repeated installs never wrap an earlier factory.
_REAL_ASYNC_CLIENT = httpx.AsyncClient
_REAL_SYNC_CLIENT = httpx.Client


class MockHttp:
    """Recorded requests and client kwargs for one installed handler."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.client_kwargs: list[dict[str, Any]] = []


def install_mock_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> MockHttp:
    state = MockHttp()

    def recording(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        return handler(request)

    def async_factory(**kwargs: Any) -> httpx.AsyncClient:
        state.client_kwargs.append(dict(kwargs))
        return _REAL_ASYNC_CLIENT(**kwargs, transport=httpx.MockTransport(recording))

    def sync_factory(**kwargs: Any) -> httpx.Client:
        state.client_kwargs.append(dict(kwargs))
        return _REAL_SYNC_CLIENT(**kwargs, transport=httpx.MockTransport(recording))

    monkeypatch.setattr(httpx, "AsyncClient", async_factory)
    monkeypatch.setattr(httpx, "Client", sync_factory)
    return state
