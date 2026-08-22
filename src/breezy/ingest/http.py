"""Hardened outbound HTTP transport for untrusted third-party data sources.

This module fetches NWS product text that determines real-money settlement.
It is deliberately isolated from ``nautilus_trader`` (no import of it here)
so it stays unit-testable with ``respx`` in complete isolation, and is used
only for weather-data ingestion — venue traffic keeps
``nautilus_pyo3.HttpClient``. See docs/plans/WEATHER_INGESTION_PROPOSAL.md
section 6 for the full rationale and the evaluation of why
``nautilus_pyo3.HttpClient`` cannot express these controls.

Every control below is individually load-bearing:

- HTTPS-only + host allowlist, checked before any socket opens.
- Redirects are never followed: a 3xx on a settlement endpoint is an
  integrity alarm, not a fetch step.
- TLS verification is always on (no code path disables it), minimum TLS 1.2.
- Response bodies are capped (128 KiB default) and the cap is enforced
  *during* streaming, before the full body is materialised.
- Decoding is strict UTF-8: a decode failure raises rather than silently
  mutating the settlement datum (and its digest) via ``errors="replace"``.
- The SHA-256 digest is computed over the exact raw bytes received, before
  anything (decoding, normalization) can transform them.
"""

from __future__ import annotations

import hashlib
import os
import ssl
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

DEFAULT_MAX_BODY_BYTES = 128 * 1024  # 128 KiB; real CLI products are <64 KiB.
DEFAULT_CHUNK_SIZE = 8 * 1024
DEFAULT_CONTACT = "breezy-data@gopoint.com"
USER_AGENT_ENV_VAR = "BREEZY_USER_AGENT"

# Environment variables that can silently redirect or weaken outbound TLS
# traffic. Trusting these unexamined defeats the host allowlist and TLS
# verification controls above them.
_SENSITIVE_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "SSLKEYLOGFILE",
)


# --------------------------------------------------------------------------
# Error taxonomy — one distinct, catchable type per failure mode so callers
# (the poller / gate logic in a later seam) can branch without string
# matching on messages.
# --------------------------------------------------------------------------


class TransportError(Exception):
    """Base class for all errors raised by :class:`HttpTransport`."""


class DisallowedHostError(TransportError):
    """Raised for a non-HTTPS scheme or a host outside the allowlist.

    Raised before any socket is opened.
    """


class RedirectError(TransportError):
    """Raised when the server responds with a 3xx status.

    Redirects are never followed. On a settlement endpoint this is treated
    as an integrity alarm, not a normal fetch outcome.
    """

    def __init__(self, message: str, *, status_code: int, location: str | None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.location = location


class OversizeBodyError(TransportError):
    """Raised when the streamed body exceeds the configured size cap."""


class DecodeError(TransportError):
    """Raised when the raw response body is not valid UTF-8."""


class ForbiddenError(TransportError):
    """Raised on HTTP 403 (UA-trap or abuse block from the origin)."""


class RateLimitedError(TransportError):
    """Raised on HTTP 429, carrying ``Retry-After`` if the server sent one."""

    def __init__(self, message: str, *, retry_after: str | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(TransportError):
    """Raised on HTTP 5xx responses."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class TransportTimeoutError(TransportError):
    """Raised on connect/read/write/pool timeout."""


class ProxyEnvironmentError(TransportError):
    """Raised when an unapproved proxy/TLS-affecting env var is set."""


class ContentEncodingError(TransportError):
    """Raised when a response carries a non-identity Content-Encoding.

    Identity encoding is requested explicitly; anything else is treated as
    an integrity signal from a compromised or malicious allowlisted host,
    never something to transparently decompress.
    """


# --------------------------------------------------------------------------
# Public helpers
# --------------------------------------------------------------------------


def assert_clean_proxy_env(approved: frozenset[str] | set[str] | None = None) -> None:
    """Assert that no proxy/TLS-affecting env var is set unless approved.

    Trusting HTTP(S)_PROXY, SSL_CERT_FILE, REQUESTS_CA_BUNDLE, or
    SSLKEYLOGFILE silently would let an unexamined environment redirect
    traffic or weaken TLS verification for every outbound request, defeating
    the host allowlist and TLS controls above it.
    """
    approved_set = frozenset(approved) if approved else frozenset()
    offending = [
        var
        for var in _SENSITIVE_PROXY_ENV_VARS
        if os.environ.get(var) and var not in approved_set
    ]
    if offending:
        raise ProxyEnvironmentError(
            "Unapproved proxy/TLS environment variable(s) set: "
            f"{', '.join(sorted(offending))}. Either unset them or pass them "
            "explicitly as approved."
        )


def redact_url(url: str) -> str:
    """Return ``url`` with query-parameter values and userinfo removed.

    Intended for logging: query strings on NWS/venue endpoints may carry API
    keys or other sensitive values, and a netloc may carry ``user:pass@``
    credentials; the raw URL is not safe to log as-is.
    """
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    if not parts.query:
        return urlunsplit((parts.scheme, netloc, parts.path, "", parts.fragment))
    redacted_pairs = [(key, "REDACTED") for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    redacted_query = urlencode(redacted_pairs)
    return urlunsplit((parts.scheme, netloc, parts.path, redacted_query, parts.fragment))


def _default_user_agent() -> str:
    override = os.environ.get(USER_AGENT_ENV_VAR)
    if override:
        return override
    return f"breezy-weather-ingest/0.1 (+mailto:{DEFAULT_CONTACT})"


# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """Result of a successful fetch.

    ``sha256`` is computed over the exact raw bytes received, before UTF-8
    decoding, so provenance is captured ahead of any transformation.
    """

    text: str
    sha256: str
    status_code: int
    headers: httpx.Headers
    url: str
    retry_after: str | None = None


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Timeouts:
    connect: float = 5.0
    read: float = 10.0
    write: float = 5.0
    pool: float = 5.0

    def as_httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=self.connect, read=self.read, write=self.write, pool=self.pool)


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class HttpTransport:
    """Injectable async transport over ``httpx`` with settlement-grade controls.

    Not a general-purpose HTTP client: every relaxation (following
    redirects, disabling TLS verification, uncapped bodies, lossy decoding)
    that a general client would offer is deliberately absent.
    """

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        write_timeout: float = 5.0,
        pool_timeout: float = 5.0,
        user_agent: str | None = None,
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
    ) -> None:
        self._check_proxy_env = check_proxy_env
        self._approved_proxy_env_vars = approved_proxy_env_vars
        if check_proxy_env:
            assert_clean_proxy_env(approved_proxy_env_vars)

        self._allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self._max_body_bytes = max_body_bytes
        self._chunk_size = chunk_size
        self._timeouts = _Timeouts(
            connect=connect_timeout, read=read_timeout, write=write_timeout, pool=pool_timeout
        )
        self._user_agent = user_agent or _default_user_agent()
        self._ssl_context = _build_ssl_context()

    def _validate_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise DisallowedHostError(
                f"Scheme {parts.scheme!r} is not allowed; only https:// is permitted "
                f"(url={redact_url(url)})"
            )
        if parts.username is not None:
            raise DisallowedHostError(
                f"URL must not carry userinfo credentials (url={redact_url(url)})"
            )
        if parts.port not in (None, 443):
            raise DisallowedHostError(
                f"Port {parts.port} is not allowed; only the default HTTPS port (443) "
                f"is permitted (url={redact_url(url)})"
            )
        host = (parts.hostname or "").lower()
        if host not in self._allowed_hosts:
            raise DisallowedHostError(
                f"Host {host!r} is not in the allowlist (url={redact_url(url)})"
            )

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=self._ssl_context,
            follow_redirects=False,
            # Defense in depth, independent of our own assert_clean_proxy_env
            # check: never let httpx read HTTP(S)_PROXY / SSL_CERT_FILE /
            # NETRC / etc. from the process environment.
            trust_env=False,
            timeout=self._timeouts.as_httpx_timeout(),
            headers={"User-Agent": self._user_agent, "Accept-Encoding": "identity"},
        )

    async def fetch(self, url: str) -> FetchResult:
        """Fetch ``url`` and return its raw-bytes digest plus decoded text.

        Raises one of the :class:`TransportError` subclasses on any failure
        mode; never returns a partially-materialised or lossily-decoded
        body.
        """
        # Re-checked on every fetch, not only at construction: a long-lived
        # transport is built once per trading session, so an env var set
        # after construction (compromised dependency, subprocess, bad
        # deploy) must still be caught on the next fetch rather than
        # silently honoured until restart.
        if self._check_proxy_env:
            assert_clean_proxy_env(self._approved_proxy_env_vars)

        self._validate_url(url)

        try:
            async with self._build_client() as client, client.stream("GET", url) as response:
                self._raise_for_status(response)
                self._reject_unexpected_content_encoding(response)
                body = await self._read_capped_body(response)
        except httpx.TimeoutException as exc:
            raise TransportTimeoutError(f"Timed out fetching {redact_url(url)}: {exc}") from exc
        except httpx.TransportError as exc:
            # Any other lower-level httpx transport failure (connection
            # refused/reset, DNS failure, etc.) — not a defined settlement
            # failure mode, so it's re-raised as a generic TransportError
            # rather than silently swallowed.
            raise TransportError(f"Transport failure fetching {redact_url(url)}: {exc}") from exc

        try:
            text = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise DecodeError(
                f"Response body from {redact_url(url)} is not valid UTF-8: {exc}"
            ) from exc

        digest = hashlib.sha256(body).hexdigest()
        return FetchResult(
            text=text,
            sha256=digest,
            status_code=response.status_code,
            headers=response.headers,
            url=url,
            retry_after=response.headers.get("retry-after"),
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if 300 <= status < 400:
            raise RedirectError(
                f"Server returned redirect {status} for {redact_url(str(response.url))}; "
                "redirects are disabled and treated as an integrity alarm.",
                status_code=status,
                location=response.headers.get("location"),
            )
        if status == 403:
            raise ForbiddenError(
                f"403 Forbidden from {redact_url(str(response.url))} "
                "(check User-Agent contact / abuse block)."
            )
        if status == 429:
            raise RateLimitedError(
                f"429 Too Many Requests from {redact_url(str(response.url))}.",
                retry_after=response.headers.get("retry-after"),
            )
        if status >= 500:
            raise ServerError(
                f"{status} server error from {redact_url(str(response.url))}.",
                status_code=status,
            )

    def _reject_unexpected_content_encoding(self, response: httpx.Response) -> None:
        """Reject any non-identity Content-Encoding before the body is read.

        Accept-Encoding: identity is requested, but httpx auto-decompresses
        on Content-Encoding regardless of what was requested. Silently
        decompressing would let a compromised/malicious allowlisted host
        expand a body past the size cap inside a single chunk, and would
        desync the sha256 digest (our provenance anchor) from the actual
        wire bytes. We do not attempt to handle or decompress it — anything
        other than identity is treated as an integrity signal.
        """
        encoding = response.headers.get("content-encoding")
        if encoding is not None and encoding.strip().lower() != "identity":
            raise ContentEncodingError(
                f"Unexpected Content-Encoding {encoding!r} from "
                f"{redact_url(str(response.url))}; identity was requested."
            )

    async def _read_capped_body(self, response: httpx.Response) -> bytes:
        """Read the body in chunks, aborting as soon as the cap is exceeded.

        Uses ``aiter_bytes`` exclusively — never ``.aread()``/``.content`` —
        so the size cap is enforced during streaming, before the full body
        is ever materialised in memory.
        """
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes(self._chunk_size):
            total += len(chunk)
            if total > self._max_body_bytes:
                raise OversizeBodyError(
                    f"Response body from {redact_url(str(response.url))} exceeded the "
                    f"{self._max_body_bytes}-byte cap during streaming."
                )
            chunks.append(chunk)
        return b"".join(chunks)
