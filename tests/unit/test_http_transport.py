"""Unit tests for breezy.ingest.http — the hardened outbound HTTP transport.

RED-first: written before src/breezy/ingest/http.py exists / is complete.
All network traffic is mocked with respx; tests/conftest.py additionally
blocks any real socket from opening in this suite.
"""

from __future__ import annotations

import gzip
import hashlib

import httpx
import pytest
import respx

from breezy.ingest.http import (
    ContentEncodingError,
    DecodeError,
    DisallowedHostError,
    ForbiddenError,
    HttpTransport,
    OversizeBodyError,
    ProxyEnvironmentError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportError,
    TransportTimeoutError,
    assert_clean_proxy_env,
    redact_url,
)

ALLOWED_HOST = "api.weather.gov"
URL = f"https://{ALLOWED_HOST}/products/types/CLI/locations/OKX"


def make_transport(**overrides: object) -> HttpTransport:
    kwargs: dict[str, object] = {
        "allowed_hosts": frozenset({ALLOWED_HOST}),
        "check_proxy_env": False,
    }
    kwargs.update(overrides)
    return HttpTransport(**kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_non_https_scheme_rejected() -> None:
    transport = make_transport()
    with pytest.raises(DisallowedHostError):
        await transport.fetch(f"http://{ALLOWED_HOST}/products")


@pytest.mark.asyncio
async def test_disallowed_host_rejected_before_request() -> None:
    transport = make_transport()
    # No respx route is registered for evil.example — if the transport tried
    # to open a real connection, respx (or the socket-blocking fixture)
    # would raise a different error than DisallowedHostError.
    with pytest.raises(DisallowedHostError):
        await transport.fetch("https://evil.example/products")


@pytest.mark.asyncio
@respx.mock
async def test_redirect_is_an_error_not_followed() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(301, headers={"Location": "https://evil.example/"})
    )
    transport = make_transport()
    with pytest.raises(RedirectError):
        await transport.fetch(URL)


@pytest.mark.asyncio
@respx.mock
async def test_oversize_body_raises_end_to_end() -> None:
    oversize_body = b"x" * (200 * 1024)  # 200 KiB > 128 KiB default cap
    respx.get(URL).mock(return_value=httpx.Response(200, content=oversize_body))
    transport = make_transport()
    with pytest.raises(OversizeBodyError):
        await transport.fetch(URL)


class _CountingByteStream:
    """A lazy async chunk source that records how many chunks were pulled.

    Standing in for ``httpx.Response.aiter_bytes`` without going through
    respx, which pre-materialises its mocked response body internally
    (unrelated to our client-side consumption) and so cannot itself prove
    that OUR code stops pulling chunks once the cap is exceeded.
    """

    def __init__(self, chunk: bytes, total_chunks: int) -> None:
        self._chunk = chunk
        self._total_chunks = total_chunks
        self.yielded = 0

    async def __call__(self, chunk_size: int):
        for _ in range(self._total_chunks):
            self.yielded += 1
            yield self._chunk


class _FakeStreamingResponse:
    def __init__(self, stream: _CountingByteStream) -> None:
        self.aiter_bytes = stream
        self.url = URL
        self.status_code = 200
        self.headers = httpx.Headers({})


@pytest.mark.asyncio
async def test_oversize_body_aborted_during_stream_not_after() -> None:
    """The cap check happens per-chunk mid-stream, not after full read.

    With a 1 KiB chunk and a 128 KiB default cap, aborting mid-stream means
    far fewer than the 300 available chunks are ever pulled from the
    iterator.
    """
    chunk = b"x" * 1024
    total_available_chunks = 300  # 300 KiB if fully consumed
    stream = _CountingByteStream(chunk, total_available_chunks)
    fake_response = _FakeStreamingResponse(stream)
    transport = make_transport()

    with pytest.raises(OversizeBodyError):
        await transport._read_capped_body(fake_response)  # type: ignore[arg-type]

    assert stream.yielded < total_available_chunks
    assert stream.yielded * len(chunk) <= transport._max_body_bytes + len(chunk)


@pytest.mark.asyncio
@respx.mock
async def test_invalid_utf8_raises_rather_than_replacing() -> None:
    invalid_utf8 = b"CLIMATE REPORT\xff\xfe INVALID BYTES"
    respx.get(URL).mock(return_value=httpx.Response(200, content=invalid_utf8))
    transport = make_transport()
    with pytest.raises(DecodeError):
        await transport.fetch(URL)


@pytest.mark.asyncio
@respx.mock
async def test_sha256_is_computed_over_raw_bytes() -> None:
    body = b"CLIMATE REPORT\nNEW YORK CITY NY\n"
    expected = hashlib.sha256(body).hexdigest()
    respx.get(URL).mock(return_value=httpx.Response(200, content=body))
    transport = make_transport()
    result = await transport.fetch(URL)
    assert result.sha256 == expected
    assert result.text == body.decode("utf-8")


@pytest.mark.asyncio
@respx.mock
async def test_retry_after_header_is_surfaced() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "120"}, content=b"")
    )
    transport = make_transport()
    with pytest.raises(RateLimitedError) as exc_info:
        await transport.fetch(URL)
    assert exc_info.value.retry_after == "120"


@pytest.mark.asyncio
@respx.mock
async def test_403_and_429_map_to_distinct_error_types() -> None:
    transport = make_transport()

    respx.get(URL).mock(return_value=httpx.Response(403, content=b""))
    with pytest.raises(ForbiddenError):
        await transport.fetch(URL)

    respx.get(URL).mock(return_value=httpx.Response(429, content=b""))
    with pytest.raises(RateLimitedError):
        await transport.fetch(URL)

    assert not issubclass(ForbiddenError, RateLimitedError)
    assert not issubclass(RateLimitedError, ForbiddenError)


@pytest.mark.asyncio
@respx.mock
async def test_5xx_maps_to_server_error() -> None:
    respx.get(URL).mock(return_value=httpx.Response(503, content=b""))
    transport = make_transport()
    with pytest.raises(ServerError):
        await transport.fetch(URL)


@pytest.mark.asyncio
@respx.mock
async def test_timeout_maps_to_transport_timeout_error() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("connect timed out"))
    transport = make_transport()
    with pytest.raises(TransportTimeoutError):
        await transport.fetch(URL)


@pytest.mark.asyncio
@respx.mock
async def test_generic_transport_failure_is_wrapped() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("connection refused"))
    transport = make_transport()
    with pytest.raises(TransportError):
        await transport.fetch(URL)


@pytest.mark.asyncio
@respx.mock
async def test_user_agent_contains_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport()
    await transport.fetch(URL)
    sent_request = respx.calls.last.request
    assert "breezy-data@gopoint.com" in sent_request.headers["User-Agent"]


@pytest.mark.asyncio
@respx.mock
async def test_user_agent_honours_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREEZY_USER_AGENT", "custom-agent/1.0 (+mailto:ops@example.com)")
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport()
    await transport.fetch(URL)
    sent_request = respx.calls.last.request
    assert sent_request.headers["User-Agent"] == "custom-agent/1.0 (+mailto:ops@example.com)"


def test_proxy_env_vars_trigger_startup_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "SSLKEYLOGFILE"):
        monkeypatch.delenv(var, raising=False)

    # Clean environment: no assertion.
    assert_clean_proxy_env()

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:8080")
    with pytest.raises(ProxyEnvironmentError):
        assert_clean_proxy_env()


def test_proxy_env_var_can_be_explicitly_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSLKEYLOGFILE", "/tmp/keys.log")
    assert_clean_proxy_env(approved={"SSLKEYLOGFILE"})


@pytest.mark.asyncio
async def test_constructor_runs_proxy_check_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:8080")
    with pytest.raises(ProxyEnvironmentError):
        HttpTransport(allowed_hosts=frozenset({ALLOWED_HOST}))


def test_redact_url_removes_query_values() -> None:
    dirty = "https://api.weather.gov/products?api_key=SECRET123&site=OKX"
    clean = redact_url(dirty)
    assert "SECRET123" not in clean
    assert "OKX" not in clean or "site=" not in clean.split("OKX")[0]
    assert "api_key=REDACTED" in clean
    assert "site=REDACTED" in clean
    assert clean.startswith("https://api.weather.gov/products?")


def test_redact_url_leaves_path_and_host_intact() -> None:
    clean = redact_url("https://api.weather.gov/products/types/CLI/locations/OKX")
    assert clean == "https://api.weather.gov/products/types/CLI/locations/OKX"


# --------------------------------------------------------------------------
# Security hardening follow-up (independent review findings)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_content_encoding_header_is_rejected() -> None:
    """A Content-Encoding header must be rejected outright, never decoded.

    We ask for identity via Accept-Encoding, but httpx will still
    auto-decompress on Content-Encoding regardless of what was requested.
    Silently accepting it would let a compromised/malicious allowlisted host
    expand a body past the cap inside one chunk, and would desync the
    sha256 digest (our provenance anchor) from the actual wire bytes.
    """
    # respx pre-reads (decodes) its own mocked response during route
    # resolution regardless of content=/stream=, so the bytes must be valid
    # gzip for the mock itself to construct successfully. The rejection
    # under test must fire purely on the Content-Encoding *header* — it must
    # never depend on whether the payload happens to decode cleanly.
    valid_gzip_body = gzip.compress(b"this would decode fine, and that is the point")
    respx.get(URL).mock(
        return_value=httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=valid_gzip_body)
    )
    transport = make_transport()
    with pytest.raises(ContentEncodingError):
        await transport.fetch(URL)


@pytest.mark.asyncio
@respx.mock
async def test_identity_content_encoding_is_accepted() -> None:
    """An explicit identity Content-Encoding is not a false-positive reject."""
    respx.get(URL).mock(
        return_value=httpx.Response(200, headers={"Content-Encoding": "identity"}, content=b"ok")
    )
    transport = make_transport()
    result = await transport.fetch(URL)
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_client_disables_trust_env() -> None:
    """Defense in depth: trust_env=False regardless of our own assertion."""
    transport = make_transport()
    client = transport._build_client()
    try:
        assert client.trust_env is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_proxy_env_set_after_construction_is_caught_on_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The proxy-env guard must not be TOCTOU: re-checked on every fetch.

    A long-lived transport is constructed once per trading session; an env
    var set afterwards (compromised dependency, subprocess, bad deploy) must
    still be caught on the next fetch, not silently honoured until restart.
    """
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "SSLKEYLOGFILE"):
        monkeypatch.delenv(var, raising=False)

    transport = make_transport(check_proxy_env=True)
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))

    # First fetch succeeds against a clean environment.
    await transport.fetch(URL)

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:8080")
    with pytest.raises(ProxyEnvironmentError):
        await transport.fetch(URL)


def test_redact_url_removes_userinfo() -> None:
    dirty = "https://user:secretpass@api.weather.gov/products?api_key=SECRET"
    clean = redact_url(dirty)
    assert "user" not in clean
    assert "secretpass" not in clean
    assert clean.startswith("https://api.weather.gov/products?")


@pytest.mark.asyncio
async def test_disallowed_port_rejected() -> None:
    transport = make_transport()
    with pytest.raises(DisallowedHostError):
        await transport.fetch(f"https://{ALLOWED_HOST}:8443/products")


def test_default_https_port_is_accepted() -> None:
    """Port pinning must not false-positive-reject the explicit default port."""
    transport = make_transport()
    # Must not raise for the explicit default port.
    transport._validate_url(f"https://{ALLOWED_HOST}:443/products")


@pytest.mark.asyncio
async def test_userinfo_in_url_rejected() -> None:
    transport = make_transport()
    with pytest.raises(DisallowedHostError):
        await transport.fetch(f"https://x@{ALLOWED_HOST}/products")
