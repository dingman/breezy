"""Step 5 (client half): ``PolymarketUSHttpClient`` read-only GET surface.

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 6 ``http.py``, section 8.2/8.3, section 9 Step 5.

Every test here is offline: the transport is a recording double implementing
``PolymarketUSReadTransport``, and every credential is an ephemeral Ed25519
key generated in-process. Nothing in this module can reach a venue host.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import pytest
from nacl.signing import SigningKey
from nautilus_trader.common.component import TestClock

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import (
    GatewayForbiddenError,
    MethodNotPermittedError,
    VenueAuthError,
    VenueRateLimitError,
    VenueStatusError,
    VenueTransportError,
)
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import (
    ACCESS_KEY_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    CanonicalRequest,
    Ed25519RequestSigner,
    build_canonical_path_without_query,
)
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_BOOK,
    QUOTA_KEY_DEFAULT,
    QUOTA_KEY_INSTRUMENTS,
    QUOTA_KEY_PORTFOLIO,
    VenueResponse,
)

_API_BASE = "https://api.example.invalid"
_GATEWAY_BASE = "https://gateway.example.invalid"
_KEY_ID = "11111111-2222-3333-4444-555555555555"
_TS_MS = 1_700_000_000_000


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class _RecordingTransport:
    def __init__(self, response: VenueResponse | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = response or VenueResponse(
            status=200, headers={}, body=b'{"slug": "tc-temp-nychigh-2026-08-25-lt79f"}'
        )
        self.raises: BaseException | None = None

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        self.calls.append({"url": url, "headers": dict(headers), "quota_key": quota_key})
        if self.raises is not None:
            raise self.raises
        return self.response


class _RecordingLogger:
    def __init__(self) -> None:
        self.records: list[str] = []

    def debug(self, message: str) -> None:
        self.records.append(message)

    def info(self, message: str) -> None:
        self.records.append(message)

    def warning(self, message: str) -> None:
        self.records.append(message)

    def error(self, message: str) -> None:
        self.records.append(message)


def _secret_b64() -> str:
    return base64.b64encode(bytes(SigningKey.generate())).decode("ascii")


def _clock() -> TestClock:
    clock = TestClock()
    clock.set_time(_TS_MS * 1_000_000)
    return clock


def _signer(
    secret: str, *, canonicalize: Any = build_canonical_path_without_query
) -> Ed25519RequestSigner:
    return Ed25519RequestSigner(
        PolymarketUSCredentials(
            key_id=RedactedSecureString(_KEY_ID),
            secret_key=RedactedSecureString(secret),
        ),
        clock=_clock(),
        canonicalize=canonicalize,
    )


def _client(
    transport: _RecordingTransport,
    *,
    logger: _RecordingLogger | None = None,
    signer: Ed25519RequestSigner | None = None,
) -> PolymarketUSHttpClient:
    return PolymarketUSHttpClient(
        transport=transport,
        signer=signer or _signer(_secret_b64()),
        api_base_url=_API_BASE,
        gateway_base_url=_GATEWAY_BASE,
        logger=logger or _RecordingLogger(),
    )


# --------------------------------------------------------------------------
# Authenticated reads
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_authenticated_emits_the_three_x_pm_headers() -> None:
    transport = _RecordingTransport()
    client = _client(transport)
    payload = await client.get_authenticated(
        "/v1/portfolio/positions", quota_key=QUOTA_KEY_PORTFOLIO
    )
    assert payload == {"slug": "tc-temp-nychigh-2026-08-25-lt79f"}
    headers = transport.calls[0]["headers"]
    assert set(headers) >= {ACCESS_KEY_HEADER, TIMESTAMP_HEADER, SIGNATURE_HEADER}
    signature = headers[SIGNATURE_HEADER]
    assert base64.b64decode(signature, validate=True)
    assert transport.calls[0]["url"] == f"{_API_BASE}/v1/portfolio/positions"
    assert transport.calls[0]["quota_key"] == QUOTA_KEY_PORTFOLIO


@pytest.mark.asyncio
async def test_signed_canonical_and_dispatched_url_share_one_query_string() -> None:
    seen: list[CanonicalRequest] = []

    def recording_builder(request: CanonicalRequest) -> bytes:
        seen.append(request)
        return build_canonical_path_without_query(request)

    transport = _RecordingTransport()
    client = _client(transport, signer=_signer(_secret_b64(), canonicalize=recording_builder))
    await client.get_authenticated(
        "/v1/markets",
        query={"limit": "5", "cursor": "a b"},
        quota_key=QUOTA_KEY_INSTRUMENTS,
    )
    dispatched_url = transport.calls[0]["url"]
    signed_query = seen[0].query_string
    assert dispatched_url == f"{_API_BASE}/v1/markets?{signed_query}"
    assert seen[0].path == "/v1/markets"


@pytest.mark.asyncio
async def test_query_params_are_sorted_and_percent_encoded_deterministically() -> None:
    transport = _RecordingTransport()
    client = _client(transport)
    await client.get_authenticated(
        "/v1/markets",
        query={"zeta": "1", "alpha": "a b", "mid": "x/y"},
        quota_key=QUOTA_KEY_INSTRUMENTS,
    )
    url = transport.calls[0]["url"]
    assert url == f"{_API_BASE}/v1/markets?alpha=a%20b&mid=x%2Fy&zeta=1"


@pytest.mark.asyncio
async def test_no_query_string_yields_a_bare_path() -> None:
    transport = _RecordingTransport()
    client = _client(transport)
    await client.get_authenticated("/v1/markets", query={}, quota_key=QUOTA_KEY_INSTRUMENTS)
    assert transport.calls[0]["url"] == f"{_API_BASE}/v1/markets"


# --------------------------------------------------------------------------
# Barrier B1 -- only GET leaves this module
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_get_reaches_the_transport() -> None:
    transport = _RecordingTransport()
    client = _client(transport)
    with pytest.raises(MethodNotPermittedError):
        await client._dispatch(
            "P" + "OST",
            _API_BASE,
            "/v1/markets",
            "",
            authenticated=True,
            quota_key=QUOTA_KEY_DEFAULT,
        )
    assert transport.calls == []


def test_client_exposes_no_write_capable_public_method() -> None:
    public = {name for name in dir(PolymarketUSHttpClient) if not name.startswith("_")}
    assert public == {"get_authenticated", "get_public"}


# --------------------------------------------------------------------------
# Public gateway reads
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_get_sends_no_auth_headers() -> None:
    transport = _RecordingTransport()
    client = _client(transport)
    await client.get_public("/v1/market/slug/x", quota_key=QUOTA_KEY_INSTRUMENTS)
    headers = transport.calls[0]["headers"]
    assert ACCESS_KEY_HEADER not in headers
    assert SIGNATURE_HEADER not in headers
    assert TIMESTAMP_HEADER not in headers
    assert transport.calls[0]["url"] == f"{_GATEWAY_BASE}/v1/market/slug/x"


@pytest.mark.asyncio
async def test_gateway_403_raises_gateway_forbidden_and_does_not_fall_back() -> None:
    transport = _RecordingTransport(VenueResponse(status=403, headers={}, body=b"forbidden"))
    client = _client(transport)
    with pytest.raises(GatewayForbiddenError):
        await client.get_public("/v1/market/slug/x", quota_key=QUOTA_KEY_INSTRUMENTS)
    # No fallback: exactly one dispatch, never a retry onto the authenticated API.
    assert len(transport.calls) == 1


# --------------------------------------------------------------------------
# Status mapping
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_maps_to_venue_auth_error_without_leaking_headers() -> None:
    transport = _RecordingTransport(VenueResponse(status=401, headers={}, body=b"nope"))
    client = _client(transport)
    with pytest.raises(VenueAuthError) as excinfo:
        await client.get_authenticated("/v1/portfolio/positions", quota_key=QUOTA_KEY_PORTFOLIO)
    rendered = str(excinfo.value)
    signature = transport.calls[0]["headers"][SIGNATURE_HEADER]
    leaked = signature in rendered or _KEY_ID in rendered
    assert not leaked
    assert "nope" not in rendered


@pytest.mark.asyncio
async def test_api_403_maps_to_venue_auth_error_not_gateway_forbidden() -> None:
    transport = _RecordingTransport(VenueResponse(status=403, headers={}, body=b""))
    client = _client(transport)
    with pytest.raises(VenueAuthError):
        await client.get_authenticated("/v1/portfolio/positions", quota_key=QUOTA_KEY_PORTFOLIO)


@pytest.mark.asyncio
async def test_429_maps_to_rate_limit_error_carrying_retry_after() -> None:
    transport = _RecordingTransport(
        VenueResponse(status=429, headers={"retry-after": "13"}, body=b"")
    )
    client = _client(transport)
    with pytest.raises(VenueRateLimitError) as excinfo:
        await client.get_public("/v1/markets", quota_key=QUOTA_KEY_INSTRUMENTS)
    assert excinfo.value.retry_after == "13"


@pytest.mark.asyncio
async def test_5xx_maps_to_venue_status_error_carrying_the_code() -> None:
    transport = _RecordingTransport(VenueResponse(status=503, headers={}, body=b""))
    client = _client(transport)
    with pytest.raises(VenueStatusError) as excinfo:
        await client.get_public("/v1/markets", quota_key=QUOTA_KEY_BOOK)
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_malformed_json_body_raises_venue_transport_error() -> None:
    transport = _RecordingTransport(VenueResponse(status=200, headers={}, body=b"<html>nope"))
    client = _client(transport)
    with pytest.raises(VenueTransportError):
        await client.get_public("/v1/markets", quota_key=QUOTA_KEY_INSTRUMENTS)


@pytest.mark.asyncio
async def test_non_object_json_body_raises_venue_transport_error() -> None:
    transport = _RecordingTransport(VenueResponse(status=200, headers={}, body=b"[1, 2, 3]"))
    client = _client(transport)
    with pytest.raises(VenueTransportError):
        await client.get_public("/v1/markets", quota_key=QUOTA_KEY_INSTRUMENTS)


# --------------------------------------------------------------------------
# Quota budget (section 8.2)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_public_method_passes_a_known_quota_key() -> None:
    transport = _RecordingTransport()
    client = _client(transport)
    await client.get_authenticated("/v1/portfolio/positions", quota_key=QUOTA_KEY_PORTFOLIO)
    await client.get_public("/v1/market/slug/x", quota_key=QUOTA_KEY_INSTRUMENTS)
    from breezy.adapters.polymarket_us.transport import PERMITTED_QUOTA_KEYS

    used = {call["quota_key"] for call in transport.calls}
    assert used <= PERMITTED_QUOTA_KEYS


@pytest.mark.asyncio
async def test_unbudgeted_quota_key_is_refused_before_anything_is_signed() -> None:
    transport = _RecordingTransport()
    client = _client(transport)
    with pytest.raises(ValueError, match="quota_key"):
        await client.get_authenticated("/v1/markets", quota_key="unbudgeted")
    assert transport.calls == []


# --------------------------------------------------------------------------
# SEC-3 -- logging carries no secret material
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_log_contains_no_secret_material() -> None:
    transport = _RecordingTransport()
    logger = _RecordingLogger()
    client = _client(transport, logger=logger)
    await client.get_authenticated(
        "/v1/portfolio/positions",
        query={"token": "sensitive-query-value"},
        quota_key=QUOTA_KEY_PORTFOLIO,
    )
    assert logger.records, "the client must log each dispatched read"
    joined = "\n".join(logger.records)
    signature = transport.calls[0]["headers"][SIGNATURE_HEADER]
    leaked = signature in joined or _KEY_ID in joined or "sensitive-query-value" in joined
    assert not leaked


@pytest.mark.asyncio
async def test_error_log_on_failure_status_is_redacted() -> None:
    transport = _RecordingTransport(VenueResponse(status=401, headers={}, body=b"secret-body"))
    logger = _RecordingLogger()
    client = _client(transport, logger=logger)
    with pytest.raises(VenueAuthError):
        await client.get_authenticated("/v1/portfolio/positions", quota_key=QUOTA_KEY_PORTFOLIO)
    joined = "\n".join(logger.records)
    assert "secret-body" not in joined
    assert "401" in joined


def test_client_repr_is_redacted() -> None:
    client = _client(_RecordingTransport())
    rendered = repr(client)
    assert _KEY_ID not in rendered
    assert "PolymarketUSHttpClient" in rendered
