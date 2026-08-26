"""Read-only Polymarket.us HTTP client (plan revision 2, section 6 ``http.py``).

Two read surfaces, and nothing else:

* :meth:`PolymarketUSHttpClient.get_authenticated` -- signed reads against
  ``api.polymarket.us`` (Ed25519, ``X-PM-*`` headers);
* :meth:`PolymarketUSHttpClient.get_public` -- unauthenticated reads against
  ``gateway.polymarket.us``.

**Order-submission barrier B1.** Both funnel through one private dispatch
helper that asserts ``method in PERMITTED_METHODS`` (``frozenset({"GET"})``)
before anything leaves the module. There is no public non-GET entry point, and
the transport protocol this client is given cannot express one either
(barrier B3). Signing refuses non-GET independently (barrier B2), so a write
would have to defeat three unrelated checks.

**One query string, signed and sent.** ``_build_query_string`` is called once
per request and its single result feeds both the canonical request handed to
the signer and the URL handed to the transport. Signing one byte string and
dispatching another is the classic Ed25519 integration failure, and it fails
only against the live venue -- so the shared value is structural here rather
than a convention.

**G15, loudly.** A ``403`` from the gateway raises the dedicated
:class:`~breezy.adapters.polymarket_us.errors.GatewayForbiddenError`. There is
deliberately no fallback that silently re-routes a refused public read onto the
authenticated API: the authenticated equivalents are unverified, and a
speculative reroute would convert a dated, attributable regression into a
mystery.

**SEC-3.** No request or response header map, and no response body, is ever
logged or placed in an exception message. Only the method, the redacted URL,
the status code, the quota key and the allow-listed rate-limit headers are.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from breezy.adapters.polymarket_us.errors import (
    GatewayForbiddenError,
    MethodNotPermittedError,
    VenueAuthError,
    VenueRateLimitError,
    VenueStatusError,
    VenueTransportError,
    format_request_context,
)
from breezy.adapters.polymarket_us.redaction import REDACTED
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
from breezy.adapters.polymarket_us.transport import (
    OBSERVED_RESPONSE_HEADERS,
    PolymarketUSReadTransport,
    VenueResponse,
    assert_permitted_quota_key,
)

__all__ = ["PERMITTED_METHODS", "PolymarketUSHttpClient", "SupportsVenueLog"]

#: Barrier B1. The read-only slice dispatches GET and nothing else.
PERMITTED_METHODS: frozenset[str] = frozenset({"GET"})

_GET: str = "GET"

_RATE_LIMIT_STATUS: int = 429
_UNAUTHORIZED_STATUS: int = 401
_FORBIDDEN_STATUS: int = 403
_OK_LOWER: int = 200
_OK_UPPER: int = 300


class SupportsVenueLog(Protocol):
    """The logging surface this client uses.

    Structurally compatible with ``nautilus_trader.common.component.Logger``
    (``debug``/``info``/``warning``/``error``), matching the subset
    ``breezy.runtime.logging_bridge`` already relies on. Declared as a protocol
    so a test can supply a recorder without constructing Nautilus's logging
    subsystem, and so this module holds no dependency on a concrete logger.
    """

    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


class PolymarketUSHttpClient:
    """Authenticated and public read access to Polymarket.us."""

    __slots__ = ("_api_base_url", "_gateway_base_url", "_logger", "_signer", "_transport")

    def __init__(
        self,
        *,
        transport: PolymarketUSReadTransport,
        signer: Ed25519RequestSigner,
        api_base_url: str,
        gateway_base_url: str,
        logger: SupportsVenueLog,
    ) -> None:
        self._transport: PolymarketUSReadTransport = transport
        self._signer: Ed25519RequestSigner = signer
        self._api_base_url: str = api_base_url.rstrip("/")
        self._gateway_base_url: str = gateway_base_url.rstrip("/")
        self._logger: SupportsVenueLog = logger

    # -- public read surface ------------------------------------------------

    async def get_authenticated(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        quota_key: str,
    ) -> Mapping[str, Any]:
        """Signed GET against the authenticated API.

        ``quota_key`` is a REQUIRED keyword: an unbudgeted read is a type
        error at the call site rather than a silently-unthrottled request.
        """
        return await self._dispatch(
            _GET,
            self._api_base_url,
            path,
            self._build_query_string(query),
            authenticated=True,
            quota_key=quota_key,
        )

    async def get_public(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        quota_key: str,
    ) -> Mapping[str, Any]:
        """Unauthenticated GET against the public gateway."""
        return await self._dispatch(
            _GET,
            self._gateway_base_url,
            path,
            self._build_query_string(query),
            authenticated=False,
            quota_key=quota_key,
        )

    # -- internals ----------------------------------------------------------

    def _build_query_string(self, query: Mapping[str, object] | None) -> str:
        """Render ``query`` deterministically: sorted by key, percent-encoded.

        Determinism is not cosmetic. The same string is signed and sent, so any
        ordering or encoding difference between two renderings of the same
        mapping would be an intermittent signature failure visible only in
        production.
        """
        if not query:
            return ""
        normalised: list[tuple[str, object]] = []
        for key, value in sorted(query.items()):
            if isinstance(value, bool):
                normalised.append((key, str(value).lower()))
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                for item in value:
                    normalised.append(
                        (key, str(item).lower() if isinstance(item, bool) else item)
                    )
            else:
                normalised.append((key, value))
        return urlencode(normalised, quote_via=quote, doseq=True)

    async def _dispatch(
        self,
        method: str,
        base_url: str,
        path: str,
        query_string: str,
        *,
        authenticated: bool,
        quota_key: str,
    ) -> Mapping[str, Any]:
        if method not in PERMITTED_METHODS:
            raise MethodNotPermittedError(
                "The Polymarket.us read client dispatches "
                f"{sorted(PERMITTED_METHODS)} only; refused method {method!r}"
            )
        assert_permitted_quota_key(quota_key)

        url = f"{base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"

        headers: dict[str, str] = {}
        if authenticated:
            headers = dict(self._signer.sign_headers(method, path, query_string=query_string))

        response = await self._transport.get(url, headers=headers, quota_key=quota_key)
        self._log(method, url, response, quota_key=quota_key)
        self._raise_for_status(method, url, response, authenticated=authenticated)
        return self._decode(method, url, response)

    def _log(self, method: str, url: str, response: VenueResponse, *, quota_key: str) -> None:
        observed = {
            name: value
            for name, value in response.headers.items()
            if name.lower() in OBSERVED_RESPONSE_HEADERS
        }
        message = (
            f"{format_request_context(method=method, url=url, status_code=response.status)} "
            f"quota_key={quota_key} rate_limit_headers={observed!r}"
        )
        if _OK_LOWER <= response.status < _OK_UPPER:
            self._logger.info(message)
        else:
            self._logger.error(message)

    def _raise_for_status(
        self, method: str, url: str, response: VenueResponse, *, authenticated: bool
    ) -> None:
        status = response.status
        if _OK_LOWER <= status < _OK_UPPER:
            return
        context = format_request_context(method=method, url=url, status_code=status)
        if status == _RATE_LIMIT_STATUS:
            raise VenueRateLimitError(
                f"Polymarket.us rate limit hit: {context}",
                retry_after=response.headers.get("retry-after"),
            )
        if status == _FORBIDDEN_STATUS and not authenticated:
            raise GatewayForbiddenError(
                "Polymarket.us gateway refused an unauthenticated read (gap G15): "
                f"{context}. No fallback is attempted; escalate rather than reroute"
            )
        if status in (_UNAUTHORIZED_STATUS, _FORBIDDEN_STATUS):
            raise VenueAuthError(
                f"Polymarket.us rejected the request credentials or signature: {context}"
            )
        raise VenueStatusError(
            f"Polymarket.us returned an unexpected status: {context}", status_code=status
        )

    def _decode(self, method: str, url: str, response: VenueResponse) -> Mapping[str, Any]:
        context = format_request_context(method=method, url=url, status_code=response.status)
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, ValueError):
            raise VenueTransportError(
                f"Polymarket.us returned a body that is not valid JSON: {context} "
                f"({len(response.body)} bytes; content withheld)"
            ) from None
        if not isinstance(payload, dict):
            raise VenueTransportError(
                f"Polymarket.us returned a JSON {type(payload).__name__} where an "
                f"object was expected: {context}"
            )
        decoded: Mapping[str, Any] = payload
        return decoded

    def __repr__(self) -> str:
        return (
            f"PolymarketUSHttpClient(api_base_url={self._api_base_url!r}, "
            f"gateway_base_url={self._gateway_base_url!r}, signer={REDACTED})"
        )
