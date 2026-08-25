"""Typed error taxonomy for the Polymarket.us adapter (plan Step 2, SEC-3).

Every venue error must be renderable into a log line without leaking header
values, secret material, or a response body.
"""

from __future__ import annotations

import pytest

from breezy.adapters.polymarket_us.errors import (
    CredentialSourceError,
    GatewayForbiddenError,
    MethodNotPermittedError,
    PolymarketUSError,
    SignatureClockSkewError,
    VenueAuthError,
    VenueRateLimitError,
    VenueStatusError,
    VenueTransportError,
    format_request_context,
)

_ALL_ERRORS = (
    CredentialSourceError,
    MethodNotPermittedError,
    SignatureClockSkewError,
    VenueAuthError,
    GatewayForbiddenError,
    VenueRateLimitError,
    VenueStatusError,
    VenueTransportError,
)


@pytest.mark.parametrize("error_type", _ALL_ERRORS)
def test_every_error_derives_from_the_package_base(error_type: type[Exception]) -> None:
    assert issubclass(error_type, PolymarketUSError)
    assert issubclass(error_type, Exception)


def test_venue_error_str_never_contains_header_values() -> None:
    headers = {
        "X-PM-Access-Key": "key-id-that-must-not-leak",
        "X-PM-Signature": "signature-that-must-not-leak",
        "X-PM-Timestamp": "1700000000000",
    }

    context = format_request_context(
        method="GET",
        url="https://api.polymarket.us/v1/portfolio/positions?token=leakme",
        headers=headers,
        status_code=401,
    )
    error = VenueAuthError(context)
    rendered = f"{error}{error!r}"

    for secret in (
        "key-id-that-must-not-leak",
        "signature-that-must-not-leak",
        "1700000000000",
        "leakme",
    ):
        assert secret not in rendered
    # The useful, non-sensitive context survives.
    assert "GET" in rendered
    assert "/v1/portfolio/positions" in rendered
    assert "401" in rendered


def test_format_request_context_accepts_no_headers() -> None:
    context = format_request_context(method="GET", url="https://api.polymarket.us/v1/markets")

    assert "GET" in context
    assert "/v1/markets" in context


def test_rate_limit_error_carries_retry_after() -> None:
    error = VenueRateLimitError("rate limited", retry_after="3")

    assert error.retry_after == "3"
    assert isinstance(error, PolymarketUSError)


def test_rate_limit_error_retry_after_may_be_absent() -> None:
    assert VenueRateLimitError("rate limited", retry_after=None).retry_after is None


def test_status_error_carries_status_code() -> None:
    error = VenueStatusError("unexpected status", status_code=503)

    assert error.status_code == 503
    assert "503" in str(error) or "503" in repr(error)


def test_auth_and_gateway_errors_are_distinguishable_types() -> None:
    assert not issubclass(GatewayForbiddenError, VenueAuthError)
    assert not issubclass(VenueAuthError, GatewayForbiddenError)
