"""Step 5 (transport half): ``NautilusHttpTransport`` and ``VenueResponse``.

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 6 ``transport.py``, section 8 (rate-limit budget), section 9 Step 5.

Two classes of test live here and both are load-bearing:

* **Offline tests** replace ``nautilus_pyo3.HttpClient`` with a recorder so the
  wiring (quota key, header conversion, error mapping, barrier B3) is asserted
  deterministically.
* **One loopback test** drives the REAL pyo3 client against a
  ``127.0.0.1`` ``http.server`` under ``@pytest.mark.allow_socket``. Without
  it, ``keyed_quotas`` / ``default_quota`` / ``header_keys`` -- the three
  constructor arguments the whole D4 transport decision rests on -- would be
  exercised only against the live venue and never in CI. The autouse
  kill-switch in ``tests/conftest.py`` replaces the pyo3 constructors for
  every other test, so this marker is the only way to reach them.

No credential is used anywhere in this module: the transport does not sign.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest
from nautilus_trader.core import nautilus_pyo3

from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.transport import (
    OBSERVED_RESPONSE_HEADERS,
    PERMITTED_QUOTA_KEYS,
    QUOTA_KEY_BOOK,
    QUOTA_KEY_DEFAULT,
    QUOTA_KEY_DISCOVERY,
    QUOTA_KEY_INSTRUMENTS,
    QUOTA_KEY_PORTFOLIO,
    NautilusHttpTransport,
    PolymarketUSReadTransport,
    VenueResponse,
    build_default_quota,
    build_keyed_quotas,
)

_USER_AGENT = "breezy-transport-test/1.0 (+mailto:ops@example.com)"


# --------------------------------------------------------------------------
# Offline doubles
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status = status
        self.body = body
        self.headers = headers


class _RecordingHttpClient:
    """Stands in for ``nautilus_pyo3.HttpClient`` in the offline tests."""

    instances: ClassVar[list[_RecordingHttpClient]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.construction_kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        self.raises: BaseException | None = None
        self.response = _FakeResponse(200, b'{"ok": true}', {"retry-after": "3"})
        _RecordingHttpClient.instances.append(self)

    async def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        keys: list[str] | None = None,
        timeout_secs: int | None = None,
    ) -> _FakeResponse:
        self.calls.append({"url": url, "params": params, "headers": headers, "keys": keys})
        if self.raises is not None:
            raise self.raises
        return self.response


@pytest.fixture()
def recording_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_RecordingHttpClient]]:
    _RecordingHttpClient.instances = []
    monkeypatch.setattr(nautilus_pyo3, "HttpClient", _RecordingHttpClient)
    yield _RecordingHttpClient
    _RecordingHttpClient.instances = []


def _transport() -> NautilusHttpTransport:
    return NautilusHttpTransport(
        timeout_secs=5,
        default_quota=build_default_quota(),
        keyed_quotas=build_keyed_quotas(),
        default_headers={"User-Agent": _USER_AGENT},
    )


# --------------------------------------------------------------------------
# Barrier B3 -- the pyo3 client is not reachable as an attribute
# --------------------------------------------------------------------------


def test_transport_does_not_expose_the_http_client_as_an_attribute(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    exposed = [
        name
        for name in dir(transport)
        if not name.startswith("__")
        and isinstance(getattr(transport, name, None), recording_client)
    ]
    assert exposed == [], f"barrier B3: HttpClient reachable via attribute(s) {exposed}"


@pytest.mark.allow_socket
def test_transport_does_not_expose_real_pyo3_client_through_bound_method_self() -> None:
    """B3 must not leave ``transport._get.__self__`` pointing at HttpClient."""
    transport = _transport()

    exposed = []
    for name in dir(transport):
        if name.startswith("__"):
            continue
        value = getattr(transport, name, None)
        receiver = getattr(value, "__self__", None)
        if receiver is not None and callable(getattr(receiver, "post", None)):
            exposed.append(f"{name}.__self__ -> {type(receiver).__name__}.post")

    assert exposed == [], "barrier B3 receiver escape(s): " + ", ".join(exposed)


def test_transport_defines_slots_so_no_client_can_be_attached_later(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    assert not hasattr(transport, "__dict__")
    with pytest.raises(AttributeError):
        transport._client = recording_client.instances[0]  # type: ignore[attr-defined]


def test_transport_satisfies_the_read_transport_protocol(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport: PolymarketUSReadTransport = _transport()
    assert callable(transport.get)


# --------------------------------------------------------------------------
# Construction arguments (plan section 6 / section 8.2)
# --------------------------------------------------------------------------


def test_transport_registers_the_observed_response_header_allow_list(
    recording_client: type[_RecordingHttpClient],
) -> None:
    _transport()
    kwargs = recording_client.instances[0].construction_kwargs
    assert kwargs["header_keys"] == list(OBSERVED_RESPONSE_HEADERS)


def test_observed_response_headers_cover_retry_after_and_rate_limit_headers() -> None:
    assert "retry-after" in OBSERVED_RESPONSE_HEADERS
    assert "x-ratelimit-remaining" in OBSERVED_RESPONSE_HEADERS
    assert all(name == name.lower() for name in OBSERVED_RESPONSE_HEADERS)


def test_keyed_quota_table_covers_exactly_the_permitted_quota_keys() -> None:
    keyed = dict(build_keyed_quotas())
    assert set(keyed) | {QUOTA_KEY_DEFAULT} == set(PERMITTED_QUOTA_KEYS)
    assert {
        QUOTA_KEY_DISCOVERY,
        QUOTA_KEY_INSTRUMENTS,
        QUOTA_KEY_BOOK,
        QUOTA_KEY_PORTFOLIO,
    } <= set(keyed)


def test_default_quota_stays_below_the_retail_twenty_per_second_cap() -> None:
    """Retail cap is 20 req/s per API key; Breezy budgets under it.

    Evidence: ``docs_snapshots/api-reference_rate-limits_2026-08-25.md:15,19-20``.
    The institutional per-firm figures in ``trader-guide_rate-limits_*`` are a
    different API surface and are NOT installed as our global limit.
    """
    from breezy.adapters.polymarket_us.transport import (
        DEFAULT_GLOBAL_REQUESTS_PER_SECOND,
        RETAIL_GLOBAL_REQUESTS_PER_SECOND,
    )

    assert RETAIL_GLOBAL_REQUESTS_PER_SECOND == 20
    assert 0 < DEFAULT_GLOBAL_REQUESTS_PER_SECOND < RETAIL_GLOBAL_REQUESTS_PER_SECOND


def test_transport_passes_the_default_headers_through_to_the_client(
    recording_client: type[_RecordingHttpClient],
) -> None:
    _transport()
    kwargs = recording_client.instances[0].construction_kwargs
    assert kwargs["default_headers"] == {"User-Agent": _USER_AGENT}
    assert kwargs["timeout_secs"] == 5


# --------------------------------------------------------------------------
# Dispatch behaviour
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_forwards_headers_and_the_quota_key(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    response = await transport.get(
        "https://example.invalid/v1/market/slug/x",
        headers={"X-PM-Access-Key": "not-a-real-key"},
        quota_key=QUOTA_KEY_INSTRUMENTS,
    )
    call = recording_client.instances[0].calls[0]
    assert call["keys"] == [QUOTA_KEY_INSTRUMENTS]
    assert call["headers"] == {"X-PM-Access-Key": "not-a-real-key"}
    assert isinstance(response, VenueResponse)
    assert response.status == 200
    assert response.body == b'{"ok": true}'
    assert dict(response.headers) == {"retry-after": "3"}


@pytest.mark.asyncio
async def test_get_rejects_a_quota_key_outside_the_budget_table(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    with pytest.raises(ValueError, match="quota_key"):
        await transport.get("https://example.invalid/x", headers={}, quota_key="unbudgeted")


@pytest.mark.asyncio
async def test_transport_error_is_typed_and_carries_no_header_values(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    recording_client.instances[0].raises = nautilus_pyo3.HttpError("connection refused")
    with pytest.raises(VenueTransportError) as excinfo:
        await transport.get(
            "https://example.invalid/v1/x?token=sekrit",
            headers={"X-PM-Signature": "s3cr3t-signature"},
            quota_key=QUOTA_KEY_DEFAULT,
        )
    rendered = str(excinfo.value)
    assert "s3cr3t-signature" not in rendered
    assert "sekrit" not in rendered


@pytest.mark.asyncio
async def test_timeout_is_mapped_to_venue_transport_error(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    recording_client.instances[0].raises = nautilus_pyo3.HttpTimeoutError("timed out")
    with pytest.raises(VenueTransportError):
        await transport.get("https://example.invalid/v1/x", headers={}, quota_key=QUOTA_KEY_DEFAULT)


@pytest.mark.asyncio
async def test_venue_response_is_immutable(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    response = await transport.get(
        "https://example.invalid/v1/x", headers={}, quota_key=QUOTA_KEY_DEFAULT
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.status = 500  # type: ignore[misc]


# --------------------------------------------------------------------------
# Loopback: the REAL pyo3 client
# --------------------------------------------------------------------------


class _LoopbackHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Retry-After", "7")
        self.send_header("X-RateLimit-Remaining", "19")
        self.send_header("X-Not-Allow-Listed", "should-not-surface")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


@pytest.fixture()
def loopback_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LoopbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_transport_round_trips_against_a_loopback_server(loopback_server: str) -> None:
    """The real pyo3 client, exercising ``header_keys`` end to end."""
    transport = NautilusHttpTransport(
        timeout_secs=5,
        default_quota=build_default_quota(),
        keyed_quotas=build_keyed_quotas(),
        default_headers={"User-Agent": _USER_AGENT},
    )
    response = await transport.get(
        f"{loopback_server}/v1/market/slug/tc-temp-nychigh-2026-08-25-lt79f",
        headers={"X-Probe": "1"},
        quota_key=QUOTA_KEY_DEFAULT,
    )
    assert response.status == 200
    assert response.body == b'{"ok": true}'
    # `header_keys` is an allow-list: named headers surface, others do not.
    assert response.headers["retry-after"] == "7"
    assert response.headers["x-ratelimit-remaining"] == "19"
    assert "x-not-allow-listed" not in {k.lower() for k in response.headers}


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_keyed_quota_throttles_the_real_client_at_the_loopback_server(
    loopback_server: str,
) -> None:
    """A keyed quota genuinely delays calls beyond its burst; the default does not."""
    throttled_key = "throttled-probe"
    transport = NautilusHttpTransport(
        timeout_secs=5,
        default_quota=build_default_quota(),
        keyed_quotas=[(throttled_key, nautilus_pyo3.Quota.rate_per_second(2))],
        default_headers={"User-Agent": _USER_AGENT},
        permitted_quota_keys=frozenset({throttled_key, QUOTA_KEY_DEFAULT}),
    )
    url = f"{loopback_server}/v1/probe"

    started = time.monotonic()
    for _ in range(4):
        await transport.get(url, headers={}, quota_key=throttled_key)
    throttled_elapsed = time.monotonic() - started

    started = time.monotonic()
    for _ in range(4):
        await transport.get(url, headers={}, quota_key=QUOTA_KEY_DEFAULT)
    default_elapsed = time.monotonic() - started

    # 4 calls against a 2/second burst must wait for two replenishments.
    assert throttled_elapsed > 0.8, f"keyed quota did not throttle ({throttled_elapsed:.3f}s)"
    assert default_elapsed < throttled_elapsed


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_connection_refused_on_loopback_raises_venue_transport_error() -> None:
    transport = NautilusHttpTransport(
        timeout_secs=2,
        default_quota=build_default_quota(),
        keyed_quotas=build_keyed_quotas(),
        default_headers={"User-Agent": _USER_AGENT},
    )
    # Port 1 on loopback: reserved, never bound by this suite.
    with pytest.raises(VenueTransportError):
        await asyncio.wait_for(
            transport.get("http://127.0.0.1:1/v1/x", headers={}, quota_key=QUOTA_KEY_DEFAULT),
            timeout=10,
        )


def test_response_headers_mapping_type_is_a_mapping() -> None:
    response = VenueResponse(status=200, headers={"retry-after": "1"}, body=b"")
    mapping: Mapping[str, str] = response.headers
    assert mapping["retry-after"] == "1"
