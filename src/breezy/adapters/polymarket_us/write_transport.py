"""Shipped write-only HTTP transport for Polymarket.us (R-6.5b).

File-exact B4 exemption. Extends Nautilus only through ``nautilus_pyo3.HttpClient``
(injected, never constructed here). ``signing.py`` and ``PERMITTED_METHODS`` are
untouched: the write signer is a sibling type gated by
:data:`PERMITTED_WRITE_METHODS`. Zero send call sites in this increment;
``factories.py`` constructs the wrapper and R-7 injects the dispatch.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from nautilus_trader.common.component import Clock
from nautilus_trader.core import nautilus_pyo3

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import (
    MethodNotPermittedError,
    SignatureClockSkewError,
    VenueTransportError,
)
from breezy.adapters.polymarket_us.redaction import REDACTED, redact_url
from breezy.adapters.polymarket_us.signing import (
    ACCESS_KEY_HEADER,
    DEFAULT_SKEW_TOLERANCE_MS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    CanonicalRequest,
    _load_signing_key,
    build_canonical_path_without_query,
)
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO, VenueResponse

__all__ = [
    "CANCEL_ALL_PATH",
    "ORDERS_PATH",
    "PERMITTED_WRITE_METHODS",
    "WRITE_CANONICAL_STRING_VERIFIED",
    "Ed25519WriteRequestSigner",
    "PolymarketUSWriteTransport",
]

#: Flips only along the OP-4 probe artefact path. R-7 must refuse to wire a
#: call site while this is False.
WRITE_CANONICAL_STRING_VERIFIED: Final[bool] = False

PERMITTED_WRITE_METHODS: frozenset[str] = frozenset({"POST"})
_WRITE_METHOD: str = next(iter(PERMITTED_WRITE_METHODS))

CANCEL_ALL_PATH: Final[str] = "/v1/orders/open/cancel"
ORDERS_PATH: Final[str] = "/v1/orders"


def _build_post_only_callable(client: Any) -> Callable[..., Awaitable[Any]]:
    """Return a callable POST proxy without storing ``client`` on an object.

    Twin of ``transport._build_get_only_callable``. The returned object exposes
    only ``__call__``. Its ``__self__`` is the proxy, not the pyo3 client.
    """

    class _PostOnlyCallable:
        __slots__ = ()

        async def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return await client.post(*args, **kwargs)

        def __repr__(self) -> str:
            return "NautilusHttpTransportPostOnlyCallable()"

    return _PostOnlyCallable()


class Ed25519WriteRequestSigner:
    """Sibling of :class:`Ed25519RequestSigner` that signs write verbs only.

    Mirrors the probe's ``_sign_write_headers``: same canonical builder, same
    key loader, same three header names, over ``PERMITTED_WRITE_METHODS``.
    """

    __slots__ = ("_clock", "_credentials", "_skew_tolerance_ms")

    def __init__(
        self,
        credentials: PolymarketUSCredentials,
        *,
        clock: Clock,
        skew_tolerance_ms: int = DEFAULT_SKEW_TOLERANCE_MS,
    ) -> None:
        if skew_tolerance_ms <= 0:
            raise ValueError("skew_tolerance_ms must be positive")
        self._credentials = credentials
        self._clock = clock
        self._skew_tolerance_ms = skew_tolerance_ms

    def assert_within_window(self, timestamp_ms: int) -> None:
        drift_ms = timestamp_ms - self._clock.timestamp_ms()
        if abs(drift_ms) > self._skew_tolerance_ms:
            raise SignatureClockSkewError(
                f"Request timestamp drifts {drift_ms} ms from the local clock, outside "
                f"the +/-{self._skew_tolerance_ms} ms Ed25519 signing window; venue "
                "signature verification will fail until the host clock is corrected"
            )

    def sign_headers(
        self,
        method: str,
        path: str,
        *,
        query_string: str = "",
        timestamp_ms: int | None = None,
    ) -> list[tuple[str, str]]:
        if method not in PERMITTED_WRITE_METHODS:
            raise MethodNotPermittedError(
                "Polymarket.us write-request signing is restricted to "
                f"{sorted(PERMITTED_WRITE_METHODS)}; "
                f"refused to sign method {method!r}"
            )
        effective_ts = self._clock.timestamp_ms() if timestamp_ms is None else timestamp_ms
        self.assert_within_window(effective_ts)
        canonical = build_canonical_path_without_query(
            CanonicalRequest(
                timestamp_ms=effective_ts,
                method=method,
                path=path,
                query_string=query_string,
            )
        )
        signing_key = _load_signing_key(self._credentials.secret_key.get_value())
        signature = base64.b64encode(signing_key.sign(canonical).signature).decode("ascii")
        return [
            (ACCESS_KEY_HEADER, self._credentials.key_id.get_value()),
            (TIMESTAMP_HEADER, str(effective_ts)),
            (SIGNATURE_HEADER, signature),
        ]

    def __repr__(self) -> str:
        return f"Ed25519WriteRequestSigner({REDACTED})"


class PolymarketUSWriteTransport:
    """POST-only wrapper over an injected ``nautilus_pyo3.HttpClient`` (B3).

    The constructor takes a prebuilt client as a keyword-only argument and
    keeps only a POST-only callable closed over that argument. Storing the
    client would put ``transport._client.post(...)`` one attribute hop away.
    """

    __slots__ = ("_post",)

    def __init__(self, *, client: Any) -> None:
        self._post: Callable[..., Awaitable[Any]] = _build_post_only_callable(client)

    async def post_cancel_all(
        self, api_base_url: str, *, headers: Mapping[str, str]
    ) -> VenueResponse:
        """Dispatch the one pinned cancel-all write. No method, query, or body."""
        url = f"{api_base_url.rstrip('/')}{CANCEL_ALL_PATH}"
        try:
            response = await self._post(
                url, headers=dict(headers), keys=[QUOTA_KEY_PORTFOLIO]
            )
        except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError):
            raise VenueTransportError(
                f"{_WRITE_METHOD} {redact_url(url)} failed at the transport layer"
            ) from None
        return VenueResponse(
            status=int(response.status),
            headers=dict(response.headers),
            body=bytes(response.body),
        )

    async def post_order(
        self, base_url: str, *, headers: Mapping[str, str], body: bytes
    ) -> VenueResponse:
        """Dispatch the one pinned create-order write. Reuses ``self._post``."""
        url = f"{base_url.rstrip('/')}{ORDERS_PATH}"
        try:
            response = await self._post(
                url, headers=dict(headers), body=body, keys=[QUOTA_KEY_PORTFOLIO]
            )
        except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError):
            raise VenueTransportError(
                f"{_WRITE_METHOD} {redact_url(url)} failed at the transport layer"
            ) from None
        return VenueResponse(
            status=int(response.status),
            headers=dict(response.headers),
            body=bytes(response.body),
        )

    def __repr__(self) -> str:
        return "PolymarketUSWriteTransport(POST-only)"
