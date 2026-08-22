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
    MAX_VALIDATOR_LENGTH,
    ContentEncodingError,
    DecodeError,
    DisallowedHostError,
    ForbiddenError,
    HttpTransport,
    InvalidCacheValidatorError,
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

# An arbitrary fixed instant (2025-08-24T04:26:40Z). Any test asserting an
# exact stamped value compares against this, never against a wall clock.
FIXED_NS = 1_756_009_600_000_000_000


class _FakeClock:
    """Injected nanosecond clock: fixed by default, and it counts its reads.

    The read count is the seam that proves ``fetch`` stamps the receipt
    instant *itself*, exactly once per fetch, rather than leaving it to a
    caller who might stamp it late.
    """

    def __init__(self, *, start_ns: int = FIXED_NS, step_ns: int = 0) -> None:
        self._now = start_ns
        self._step = step_ns
        self.reads = 0

    def __call__(self) -> int:
        self.reads += 1
        now = self._now
        self._now += self._step
        return now


def make_transport(**overrides: object) -> HttpTransport:
    kwargs: dict[str, object] = {
        "allowed_hosts": frozenset({ALLOWED_HOST}),
        "check_proxy_env": False,
        "clock": _FakeClock(),
    }
    kwargs.update(overrides)
    return HttpTransport(**kwargs)  # type: ignore[arg-type]


def make_fetch_result(**overrides: object) -> object:
    """Construct a `FetchResult` directly, for the defensive-invariant tests."""
    from breezy.ingest.http import FetchResult

    kwargs: dict[str, object] = {
        "text": "CLIMATE REPORT",
        "sha256": hashlib.sha256(b"CLIMATE REPORT").hexdigest(),
        "status_code": 200,
        "headers": httpx.Headers({}),
        "url": URL,
        "retrieved_at_ns": FIXED_NS,
    }
    kwargs.update(overrides)
    return FetchResult(**kwargs)  # type: ignore[arg-type]


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
    assert "breezy-data@gmail.com" in sent_request.headers["User-Agent"]


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
        HttpTransport(allowed_hosts=frozenset({ALLOWED_HOST}), clock=_FakeClock())


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


# --------------------------------------------------------------------------
# 304 Not Modified — the healthy response to a conditional GET on the
# discovery-list endpoint. Must never be treated as a redirect-integrity
# alarm (that would hard-block trading the moment conditional GET is wired
# in, since 304 is the *expected* steady-state response).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_304_not_modified_is_not_a_redirect_alarm() -> None:
    respx.get(URL).mock(return_value=httpx.Response(304, headers={"ETag": '"abc123"'}))
    transport = make_transport()
    result = await transport.fetch(URL)
    assert result.status_code == 304


@pytest.mark.asyncio
@respx.mock
async def test_304_result_cannot_be_mistaken_for_a_fetched_document() -> None:
    """A 304 has no body: text/sha256 must be None, never an empty-body digest.

    A 304 whose sha256 silently equalled hashlib.sha256(b"").hexdigest()
    would be indistinguishable from a genuinely empty document flowing into
    a provenance record. Leaving both fields None forces any caller (and
    mypy, under strict mode) to branch on status_code before touching them.
    """
    respx.get(URL).mock(return_value=httpx.Response(304, headers={"ETag": '"abc123"'}))
    transport = make_transport()
    result = await transport.fetch(URL)
    assert result.text is None
    assert result.sha256 is None
    assert result.sha256 != hashlib.sha256(b"").hexdigest()


@pytest.mark.asyncio
@respx.mock
async def test_etag_is_readable_on_200_and_304() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(200, headers={"ETag": '"abc123"'}, content=b"CLIMATE REPORT")
    )
    transport = make_transport()
    fetched = await transport.fetch(URL)
    assert fetched.headers.get("etag") == '"abc123"'

    respx.get(URL).mock(return_value=httpx.Response(304, headers={"ETag": '"abc123"'}))
    not_modified = await transport.fetch(URL)
    assert not_modified.headers.get("etag") == '"abc123"'


@pytest.mark.asyncio
@respx.mock
async def test_305_and_306_remain_redirect_alarms() -> None:
    """305 (Use Proxy) and 306 (reserved/unused) stay integrity alarms.

    Only 304 is excluded from the redirect check. 305 is deprecated and
    instructs the client to route through a proxy — on a settlement path
    that is arguably *more* alarming than an ordinary redirect, not less,
    so it is not carved out alongside 304. 306 has been reserved/unused
    since HTTP/1.1 and a live server emitting it is itself anomalous.
    Neither is a response the discovery-list conditional GET is ever
    expected to produce, unlike 304.
    """
    transport = make_transport()

    respx.get(URL).mock(return_value=httpx.Response(305, headers={"Location": "https://proxy.example/"}))
    with pytest.raises(RedirectError):
        await transport.fetch(URL)

    respx.get(URL).mock(return_value=httpx.Response(306))
    with pytest.raises(RedirectError):
        await transport.fetch(URL)


def test_fetch_result_rejects_body_on_304() -> None:
    """Defensive invariant: a 304 FetchResult must never carry text/sha256."""
    with pytest.raises(ValueError):
        make_fetch_result(
            text="unexpected body",
            sha256=hashlib.sha256(b"unexpected body").hexdigest(),
            status_code=304,
        )


def test_fetch_result_requires_body_when_not_304() -> None:
    """Defensive invariant: a non-304 FetchResult must carry text/sha256."""
    with pytest.raises(ValueError):
        make_fetch_result(text=None, sha256=None, status_code=200)


# --------------------------------------------------------------------------
# Receipt timestamp — stamped INSIDE fetch, adjacent to the digest.
#
# `ts_init` on every catalog record propagates the instant the bytes arrived.
# Stamping it later (at record construction, after a parse, after an await)
# silently degrades backtest/live replay fidelity and makes the backtest
# return a plausible, wrong answer — risk #1 in
# docs/plans/WEATHER_INGESTION_PROPOSAL.md. The transport is the only layer
# that knows the instant, so it is the only layer allowed to stamp it.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_fetch_stamps_the_receipt_instant_from_the_injected_clock() -> None:
    """The exact stamped value is the injected clock's reading — assertable."""
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"CLIMATE REPORT"))
    clock = _FakeClock(start_ns=FIXED_NS)
    transport = make_transport(clock=clock)

    result = await transport.fetch(URL)

    assert result.retrieved_at_ns == FIXED_NS


@pytest.mark.asyncio
@respx.mock
async def test_the_receipt_instant_is_stamped_by_fetch_exactly_once() -> None:
    """`fetch` reads the clock itself, once — the caller never stamps.

    A second read would mean the timestamp and the digest could describe two
    different instants; zero reads would mean the caller is stamping it, which
    is the defect this change removes.
    """
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"CLIMATE REPORT"))
    clock = _FakeClock(start_ns=FIXED_NS, step_ns=1_000_000_000)
    transport = make_transport(clock=clock)

    result = await transport.fetch(URL)

    assert clock.reads == 1
    assert result.retrieved_at_ns == FIXED_NS


@pytest.mark.asyncio
@respx.mock
async def test_the_receipt_instant_and_the_digest_describe_the_same_fetch() -> None:
    """Two fetches of the same bytes get the same digest and different stamps."""
    body = b"CLIMATE REPORT\nNEW YORK CITY NY\n"
    respx.get(URL).mock(return_value=httpx.Response(200, content=body))
    clock = _FakeClock(start_ns=FIXED_NS, step_ns=5_000_000_000)
    transport = make_transport(clock=clock)

    first = await transport.fetch(URL)
    second = await transport.fetch(URL)

    assert first.sha256 == second.sha256 == hashlib.sha256(body).hexdigest()
    assert first.retrieved_at_ns == FIXED_NS
    assert second.retrieved_at_ns == FIXED_NS + 5_000_000_000


@pytest.mark.asyncio
@respx.mock
async def test_a_304_carries_a_receipt_instant() -> None:
    """A 304 has no body but it still *happened at a time*.

    The body carve-out is about the document, not the exchange: a 304 is the
    healthy steady-state answer to a conditional GET and is a successful poll
    for the freshness watchdog, which measures liveness in nanoseconds. If the
    304 arrived without a stamp the caller would have to re-stamp from its own
    clock — reintroducing exactly the second source of truth being removed.
    """
    respx.get(URL).mock(return_value=httpx.Response(304, headers={"ETag": '"abc123"'}))
    clock = _FakeClock(start_ns=FIXED_NS)
    transport = make_transport(clock=clock)

    result = await transport.fetch(URL, if_none_match='"abc123"')

    assert result.status_code == 304
    assert result.text is None
    assert result.sha256 is None
    assert result.retrieved_at_ns == FIXED_NS
    assert clock.reads == 1


def test_fetch_result_requires_a_receipt_instant() -> None:
    """Omission is a TypeError: the field has no default to fall through."""
    from breezy.ingest.http import FetchResult

    with pytest.raises(TypeError):
        FetchResult(  # type: ignore[call-arg]
            text="CLIMATE REPORT",
            sha256=hashlib.sha256(b"CLIMATE REPORT").hexdigest(),
            status_code=200,
            headers=httpx.Headers({}),
            url=URL,
        )


@pytest.mark.parametrize("stamp", [0, -1, -FIXED_NS])
def test_fetch_result_rejects_a_non_positive_receipt_instant(stamp: int) -> None:
    """A zero stamp is the silently-omitted case wearing an int's clothes."""
    with pytest.raises(ValueError, match="retrieved_at_ns"):
        make_fetch_result(retrieved_at_ns=stamp)


def test_fetch_result_rejects_a_bool_receipt_instant() -> None:
    """`bool` is an `int` subclass; a stray `True` would encode as 1 nanosecond."""
    with pytest.raises(TypeError, match="retrieved_at_ns"):
        make_fetch_result(retrieved_at_ns=True)


def test_a_304_fetch_result_carries_the_instant_and_no_document() -> None:
    """The invariant's two clauses, stated together on the status they differ on."""
    result = make_fetch_result(text=None, sha256=None, status_code=304)

    assert result.status_code == 304  # type: ignore[attr-defined]
    assert result.retrieved_at_ns == FIXED_NS  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Conditional GET — the request half. Without it nothing can ever *cause* a
# 304, so the entire 304 response path above was unreachable in production.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_if_none_match_is_sent_when_supplied() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport()

    await transport.fetch(URL, if_none_match='W/"abc123"')

    assert respx.calls.last.request.headers["If-None-Match"] == 'W/"abc123"'


@pytest.mark.asyncio
@respx.mock
async def test_if_modified_since_is_sent_when_supplied() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport()

    await transport.fetch(URL, if_modified_since="Sat, 22 Aug 2026 06:26:00 GMT")

    sent = respx.calls.last.request
    assert sent.headers["If-Modified-Since"] == "Sat, 22 Aug 2026 06:26:00 GMT"


@pytest.mark.asyncio
@respx.mock
async def test_both_validators_can_be_sent_together() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport()

    await transport.fetch(
        URL,
        if_none_match='"abc123"',
        if_modified_since="Sat, 22 Aug 2026 06:26:00 GMT",
    )

    sent = respx.calls.last.request
    assert sent.headers["If-None-Match"] == '"abc123"'
    assert sent.headers["If-Modified-Since"] == "Sat, 22 Aug 2026 06:26:00 GMT"


@pytest.mark.asyncio
@respx.mock
async def test_an_unconditional_fetch_sends_no_validator_headers() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport()

    await transport.fetch(URL)

    sent = respx.calls.last.request
    assert "If-None-Match" not in sent.headers
    assert "If-Modified-Since" not in sent.headers


@pytest.mark.asyncio
@respx.mock
async def test_the_304_path_is_reachable_end_to_end() -> None:
    """Send a validator, get a 304 back — the round trip, not a hand-built result.

    Previously the only way to reach `_not_modified_result` was to construct
    the response directly, which is how the missing request half survived two
    reviews.
    """
    etag = '"cli-nyc-2026-08-21"'
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"ETag": etag}, content=b"CLI"))
    clock = _FakeClock(start_ns=FIXED_NS, step_ns=60_000_000_000)
    transport = make_transport(clock=clock)

    first = await transport.fetch(URL)
    assert first.status_code == 200
    assert first.headers.get("etag") == etag
    assert first.retrieved_at_ns == FIXED_NS

    respx.get(URL).mock(return_value=httpx.Response(304, headers={"ETag": etag}))
    second = await transport.fetch(URL, if_none_match=first.headers.get("etag"))

    assert respx.calls.last.request.headers["If-None-Match"] == etag
    assert second.status_code == 304
    assert second.text is None
    assert second.sha256 is None
    assert second.retrieved_at_ns == FIXED_NS + 60_000_000_000


@pytest.mark.asyncio
@respx.mock
async def test_conditional_headers_cannot_displace_the_hardened_headers() -> None:
    """The transport builds the header names; a caller supplies only values.

    There is no caller-supplied header *dict*, so User-Agent, Accept-Encoding
    and the rest are not overridable per call.
    """
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport(user_agent="breezy-test/1.0 (+mailto:ops@example.com)")

    await transport.fetch(URL, if_none_match='"abc123"')

    sent = respx.calls.last.request
    assert sent.headers["User-Agent"] == "breezy-test/1.0 (+mailto:ops@example.com)"
    assert sent.headers["Accept-Encoding"] == "identity"


@pytest.mark.parametrize(
    ("bad", "label"),
    [
        ('"abc"\r\nX-Injected: 1', "crlf"),
        ('"abc"\nX-Injected: 1', "lf"),
        ('"abc"\rX-Injected: 1', "cr"),
        ('"abc"\x00', "nul"),
        ('"abc"\x7f', "del"),
        ('"abc"\tmore', "tab"),
        ('"caf\xe9"', "non-ascii"),
        ("", "empty"),
        ("   ", "whitespace-only"),
        (' "abc"', "leading-space"),
        ('"abc" ', "trailing-space"),
        ('"abc"\n', "trailing-newline"),
    ],
)
@pytest.mark.asyncio
async def test_a_malformed_validator_is_rejected_before_any_socket_opens(
    bad: str,
    label: str,
) -> None:
    """An ETag is remote data being echoed back into a request we sign off on.

    No respx route is registered here: if the transport reached the network at
    all, the socket-blocking fixture would raise something other than
    InvalidCacheValidatorError.
    """
    transport = make_transport()

    with pytest.raises(InvalidCacheValidatorError):
        await transport.fetch(URL, if_none_match=bad)

    with pytest.raises(InvalidCacheValidatorError):
        await transport.fetch(URL, if_modified_since=bad)


@pytest.mark.asyncio
async def test_an_absurdly_long_validator_is_rejected() -> None:
    transport = make_transport()
    oversize = '"' + "a" * MAX_VALIDATOR_LENGTH + '"'

    with pytest.raises(InvalidCacheValidatorError, match="length"):
        await transport.fetch(URL, if_none_match=oversize)


@pytest.mark.asyncio
@respx.mock
async def test_a_validator_at_the_length_limit_is_accepted() -> None:
    """The cap must not false-positive-reject a legitimate long ETag."""
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"ok"))
    transport = make_transport()
    at_limit = "a" * MAX_VALIDATOR_LENGTH

    await transport.fetch(URL, if_none_match=at_limit)

    assert respx.calls.last.request.headers["If-None-Match"] == at_limit


@pytest.mark.asyncio
async def test_the_validator_rejection_names_the_header_not_the_value() -> None:
    """The message must not echo the untrusted value back into a log line."""
    transport = make_transport()

    with pytest.raises(InvalidCacheValidatorError) as excinfo:
        await transport.fetch(URL, if_none_match='"secret-etag"\r\nX-Injected: 1')

    assert "If-None-Match" in str(excinfo.value)
    assert "secret-etag" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_disallowed_host_is_rejected_before_the_validators() -> None:
    """Host allowlisting stays the outermost gate."""
    transport = make_transport()

    with pytest.raises(DisallowedHostError):
        await transport.fetch("https://evil.example/products", if_none_match="\r\n")
