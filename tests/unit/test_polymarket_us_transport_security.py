"""Security remediation for the read-only Polymarket.us adapter.

Findings H1 (redirect credential exposure), M2 (origin host allowlist),
M3 (proxy-environment hygiene), M4 (reload cadence must never fail shut),
L5 (bare ``?``/``#`` origins), L6 (non-normalized origins), L8 (unbounded
discovery pagination).

**No real credential appears anywhere in this module.** Every ``X-PM-*`` value
below is a literal test token, and no test reaches a non-loopback host. TLS is
never disabled: the loopback probes speak plain ``http`` to ``127.0.0.1`` and
never construct an unverified context.

The H1 contract test is deliberately an *observation* of ``nautilus_pyo3``
behaviour rather than an assertion that Breezy has prevented it. See its
docstring: the installed client follows cross-host redirects and forwards
custom headers, and exposes no switch to stop it (nautilus-trader-patterns
trap 11 -- the constructor is exactly ``(default_headers, header_keys,
keyed_quotas, default_quota, timeout_secs, proxy_url)``). Pinning the observed
behaviour is what makes a version bump fail RED instead of drifting silently.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest
from nautilus_trader.core import nautilus_pyo3

from breezy.adapters.polymarket_us.config import (
    POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR,
    PolymarketUSDataClientConfig,
    assert_well_formed_origin,
)
from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.transport import (
    OBSERVED_RESPONSE_HEADERS,
    QUOTA_KEY_DEFAULT,
    NautilusHttpTransport,
    build_default_quota,
    build_keyed_quotas,
)
from breezy.ingest.http import ProxyEnvironmentError
from breezy.runtime.settings import SettingsError

_USER_AGENT = "breezy-transport-security-test/1.0 (+mailto:ops@example.com)"

#: Literal test tokens. Not credentials, not derived from any credential.
_FAKE_CREDENTIAL_HEADERS = {
    "X-PM-Access-Key": "TEST-KEY-ID-NOT-A-CREDENTIAL",
    "X-PM-Timestamp": "1700000000000",
    "X-PM-Signature": "TEST-SIGNATURE-NOT-A-CREDENTIAL",
}


# --------------------------------------------------------------------------
# Offline double
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.status = status
        self.body = body
        self.headers = headers


class _RecordingHttpClient:
    instances: ClassVar[list[_RecordingHttpClient]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.construction_kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        self.response = _FakeResponse(200, b'{"ok": true}', {})
        _RecordingHttpClient.instances.append(self)

    async def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        keys: list[str] | None = None,
        timeout_secs: int | None = None,
    ) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers, "keys": keys})
        return self.response


@pytest.fixture()
def recording_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_RecordingHttpClient]]:
    _RecordingHttpClient.instances = []
    monkeypatch.setattr(nautilus_pyo3, "HttpClient", _RecordingHttpClient)
    yield _RecordingHttpClient
    _RecordingHttpClient.instances = []


def _transport(**overrides: Any) -> NautilusHttpTransport:
    kwargs: dict[str, Any] = {
        "timeout_secs": 5,
        "default_quota": build_default_quota(),
        "keyed_quotas": build_keyed_quotas(),
        "default_headers": {"User-Agent": _USER_AGENT},
    }
    kwargs.update(overrides)
    return NautilusHttpTransport(**kwargs)


# --------------------------------------------------------------------------
# H1 -- redirect handling
# --------------------------------------------------------------------------


def test_location_is_an_observed_response_header() -> None:
    """``header_keys`` is an allow-list; without ``location`` a hop is invisible.

    ``HttpClient`` surfaces NO response header that is not named at
    construction (nautilus-trader-patterns trap 11), so today a redirect is
    absent from logs as well as from the code path.
    """
    assert "location" in OBSERVED_RESPONSE_HEADERS


@pytest.mark.parametrize("status", [300, 301, 302, 303, 304, 305, 307, 308])
@pytest.mark.asyncio
async def test_transport_refuses_any_redirect_status(
    recording_client: type[_RecordingHttpClient], status: int
) -> None:
    """A 3xx that reaches us is refused, never decoded and never trusted.

    This covers the redirects ``reqwest`` declines to follow itself and hands
    back (measured: a 302 with no ``Location``, a 305, and a 304). It does NOT
    cover a *followed* redirect -- see
    ``test_pyo3_client_follows_cross_host_redirects_and_forwards_custom_headers``.
    """
    transport = _transport()
    client = recording_client.instances[-1]
    client.response = _FakeResponse(status, b"", {"location": "https://evil.example.com/"})

    with pytest.raises(VenueTransportError) as excinfo:
        await transport.get(
            "https://api.polymarket.us/v1/markets",
            headers=_FAKE_CREDENTIAL_HEADERS,
            quota_key=QUOTA_KEY_DEFAULT,
        )
    assert str(status) in str(excinfo.value)


@pytest.mark.asyncio
async def test_transport_refusal_message_does_not_echo_credential_headers(
    recording_client: type[_RecordingHttpClient],
) -> None:
    transport = _transport()
    client = recording_client.instances[-1]
    client.response = _FakeResponse(302, b"", {"location": "https://evil.example.com/"})

    with pytest.raises(VenueTransportError) as excinfo:
        await transport.get(
            "https://api.polymarket.us/v1/markets",
            headers=_FAKE_CREDENTIAL_HEADERS,
            quota_key=QUOTA_KEY_DEFAULT,
        )
    message = str(excinfo.value)
    for value in _FAKE_CREDENTIAL_HEADERS.values():
        assert value not in message


# --------------------------------------------------------------------------
# H1 -- loopback proofs against the REAL pyo3 client
# --------------------------------------------------------------------------


class _RedirectState:
    """Cross-thread state for the loopback handlers."""

    target_hits: ClassVar[list[dict[str, str]]] = []
    origin_hits: ClassVar[list[dict[str, str]]] = []
    target_port: ClassVar[int] = 0
    send_location: ClassVar[bool] = True


class _TargetHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        _RedirectState.target_hits.append({k.lower(): v for k, v in self.headers.items()})
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, fmt: str, *args: Any) -> None:
        return


class _RedirectingOriginHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        _RedirectState.origin_hits.append({k.lower(): v for k, v in self.headers.items()})
        self.send_response(302)
        if _RedirectState.send_location:
            # `localhost`, not `127.0.0.1`: reqwest's sensitive-header
            # stripping keys on a host CHANGE, so the two listeners must
            # differ by host string, not only by port.
            self.send_header("Location", f"http://localhost:{_RedirectState.target_port}/landed")
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        return


@pytest.fixture()
def redirect_pair() -> Iterator[str]:
    _RedirectState.target_hits = []
    _RedirectState.origin_hits = []
    _RedirectState.send_location = True
    target = ThreadingHTTPServer(("127.0.0.1", 0), _TargetHandler)
    _RedirectState.target_port = target.server_address[1]
    origin = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectingOriginHandler)
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (target, origin)
    ]
    for thread in threads:
        thread.start()
    try:
        yield f"http://127.0.0.1:{origin.server_address[1]}"
    finally:
        for server in (target, origin):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_pyo3_client_follows_cross_host_redirects_and_forwards_custom_headers(
    redirect_pair: str,
) -> None:
    """CONTRACT TEST -- pins the residual risk H1 names, and does not claim a fix.

    ``nautilus_pyo3.HttpClient`` exposes no redirect policy, so ``reqwest``'s
    default ``Policy::limited(10)`` applies and strips only its hardcoded
    sensitive set. Custom ``X-PM-*`` headers are not in that set, so they
    survive a cross-host hop; ``Authorization`` is the control and is stripped.

    Breezy CANNOT prevent this at this layer: the client returns the FINAL
    response (status 200) and exposes no final-URL attribute, so the hop is
    neither preventable nor detectable from the response.

    If a future ``nautilus-trader`` stops following redirects, or gains a
    redirect switch, this test fails RED -- which is the signal to remove the
    residual-risk note in ``transport.py`` and tighten the guard.
    """
    transport = _transport()
    response = await transport.get(
        redirect_pair + "/v1/markets",
        headers={**_FAKE_CREDENTIAL_HEADERS, "Authorization": "Bearer TEST-CONTROL"},
        quota_key=QUOTA_KEY_DEFAULT,
    )

    assert response.status == 200, "the redirect was followed, so the caller sees the final 200"
    assert len(_RedirectState.target_hits) == 1
    landed = _RedirectState.target_hits[0]
    assert landed["x-pm-access-key"] == _FAKE_CREDENTIAL_HEADERS["X-PM-Access-Key"]
    assert landed["x-pm-signature"] == _FAKE_CREDENTIAL_HEADERS["X-PM-Signature"]
    assert "authorization" not in landed, "reqwest strips its own sensitive set"


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_unfollowable_redirect_is_refused_and_never_reaches_the_second_host(
    redirect_pair: str,
) -> None:
    """A 3xx the client hands back is refused before its body is trusted."""
    _RedirectState.send_location = False  # reqwest cannot follow this one
    transport = _transport()

    with pytest.raises(VenueTransportError):
        await transport.get(
            redirect_pair + "/v1/markets",
            headers=_FAKE_CREDENTIAL_HEADERS,
            quota_key=QUOTA_KEY_DEFAULT,
        )
    assert _RedirectState.target_hits == [], "no credentialed request reached the second host"


# --------------------------------------------------------------------------
# M3 -- proxy environment hygiene
# --------------------------------------------------------------------------


@pytest.mark.parametrize("var", ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"])
def test_transport_construction_refuses_an_unapproved_proxy_environment(
    recording_client: type[_RecordingHttpClient],
    monkeypatch: pytest.MonkeyPatch,
    var: str,
) -> None:
    """``reqwest`` honours proxy env vars by default; the adapter must not.

    ``breezy.ingest.http`` has enforced this since it was written
    (``ingest/http.py:557,783``); the path carrying SIGNING CREDENTIALS was
    outside that control.
    """
    monkeypatch.setenv(var, "http://127.0.0.1:9")
    with pytest.raises(ProxyEnvironmentError):
        _transport()


def test_all_proxy_is_a_known_uncovered_variable(
    recording_client: type[_RecordingHttpClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Documents a REAL residual gap rather than hiding it.

    ``reqwest`` honours ``ALL_PROXY``/``all_proxy`` too, but
    ``breezy.ingest.http._SENSITIVE_PROXY_ENV_VARS`` does not list them, so
    neither transport refuses it today. Widening that shared tuple changes the
    NWS ingest client's behaviour as well and belongs in its own change; this
    test makes the gap visible and will fail RED once it is closed, prompting
    the fix here.
    """
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    transport = _transport()
    assert isinstance(transport, NautilusHttpTransport)


def test_transport_construction_allows_an_approved_proxy_environment(
    recording_client: type[_RecordingHttpClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BREEZY_ALLOW_PROXY_ENV=1`` is threaded through as ``check_proxy_env=False``."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    transport = _transport(check_proxy_env=False)
    assert isinstance(transport, NautilusHttpTransport)


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_no_credentialed_request_reaches_a_proxy_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empirical proof of the M3 fix, matching how M3 was proven.

    A real listener stands in for the proxy. Construction must fail before any
    request is dispatched, so the listener records nothing.
    """
    seen: list[str] = []

    class _ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_address[1]}")
        with pytest.raises(ProxyEnvironmentError):
            transport = _transport()
            await transport.get(
                "http://127.0.0.1:1/v1/portfolio/positions",
                headers=_FAKE_CREDENTIAL_HEADERS,
                quota_key=QUOTA_KEY_DEFAULT,
            )
        await asyncio.sleep(0.1)
        assert seen == [], "a credentialed request reached the proxy listener"
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# M2 -- origin host allowlist
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "https://api.polymarket.us",
        "https://gateway.polymarket.us",
        "https://polymarket.us",
        "https://api.polymarket.us.",  # trailing dot normalizes to the same host
        "https://xn--pi-fmc.polymarket.us",  # a punycode label UNDER the venue domain
    ],
)
def test_venue_domain_origins_are_accepted(origin: str) -> None:
    assert assert_well_formed_origin("api_base_url", origin, scheme="https")


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1",
        "https://localhost",
        "https://[::1]",
        "https://evil.example.com",
        "https://api.polymarket.us.evil.com",  # suffix match must be dot-bounded
        "https://notpolymarket.us",  # substring match must not be enough
        "https://polymarket.us.evil.com",
    ],
)
def test_foreign_origins_are_refused_without_the_named_escape(origin: str) -> None:
    with pytest.raises(SettingsError):
        assert_well_formed_origin("api_base_url", origin, scheme="https")


def test_a_non_ascii_host_is_refused_outright() -> None:
    """The Cyrillic homograph of ``api`` is a typo or an attack, never intent."""
    with pytest.raises(SettingsError):
        assert_well_formed_origin(
            "api_base_url", "https://аpi.polymarket.us", scheme="https"
        )


def test_the_named_escape_permits_a_foreign_origin() -> None:
    """A staging or test-double run is deliberate, and a typo is a startup failure."""
    assert (
        assert_well_formed_origin(
            "api_base_url", "https://localhost", scheme="https", allow_foreign=True
        )
        == "https://localhost"
    )


def test_the_escape_is_carried_as_an_auditable_config_field() -> None:
    """It is hashed into the run identifier, so a relocated run says so."""
    config = PolymarketUSDataClientConfig(
        user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
        api_base_url="https://api.example.invalid",
        gateway_base_url="https://gateway.example.invalid",
        ws_url="wss://api.example.invalid",
        allow_foreign_origin=True,
    )
    assert config.allow_foreign_origin is True
    assert "allow_foreign_origin" in config.json().decode("utf-8")


def test_a_foreign_origin_without_the_field_fails_at_config_construction() -> None:
    with pytest.raises(SettingsError):
        PolymarketUSDataClientConfig(
            user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
            api_base_url="https://api.example.invalid",
            gateway_base_url="https://gateway.polymarket.us",
            ws_url="wss://api.polymarket.us",
        )


@pytest.mark.parametrize("raw", ["true", "yes", "on", "0", "", " 1 x"])
def test_the_env_escape_is_not_triggered_by_a_truthy_looking_value(raw: str) -> None:
    """A half-remembered spelling must fail closed, loudly, at startup."""
    from breezy.adapters.polymarket_us.factories import _allow_foreign_origin

    assert _allow_foreign_origin({POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR: raw}) is False


def test_the_env_escape_is_triggered_by_exactly_one() -> None:
    from breezy.adapters.polymarket_us.factories import _allow_foreign_origin

    assert _allow_foreign_origin({POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR: "1"}) is True


def test_the_wss_origin_is_allowlisted_on_the_same_rule() -> None:
    assert assert_well_formed_origin("ws_url", "wss://api.polymarket.us", scheme="wss")
    with pytest.raises(SettingsError):
        assert_well_formed_origin("ws_url", "wss://evil.example.com", scheme="wss")


# --------------------------------------------------------------------------
# L5 -- bare `?` / `#` desync the signed path from the requested path
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "https://api.polymarket.us?",
        "https://api.polymarket.us#",
        "https://api.polymarket.us?#",
    ],
)
def test_bare_query_or_fragment_delimiters_are_refused(origin: str) -> None:
    """``urlsplit`` reports an EMPTY query/fragment, so the parsed guard passes.

    The composed URL then lands on ``/`` while the signature covers
    ``/v1/markets``. The guard must key on the RAW delimiter.
    """
    with pytest.raises(SettingsError):
        assert_well_formed_origin("api_base_url", origin, scheme="https")


# --------------------------------------------------------------------------
# L6 -- the validator must inspect the same string the transport uses
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        " https://api.polymarket.us ",
        "https://api.polymarket.us\n",
        "\thttps://api.polymarket.us",
    ],
)
def test_a_non_normalized_origin_is_refused_rather_than_silently_stripped(
    origin: str,
) -> None:
    """A frozen ``__post_init__`` cannot normalize, so it must refuse.

    Accepting-and-returning a stripped value while the frozen struct keeps the
    raw one means the validator inspects one string and the transport composes
    another.
    """
    with pytest.raises(SettingsError):
        assert_well_formed_origin("api_base_url", origin, scheme="https")
