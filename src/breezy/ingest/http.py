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
  integrity alarm, not a fetch step. The one deliberate exception is 304
  Not Modified, the expected success response to a conditional GET
  (``If-None-Match``) against the discovery-list endpoint; 305 and 306
  remain alarms (see ``RedirectError`` and ``FetchResult``).
- TLS verification is always on (no code path disables it), minimum TLS 1.2.
- Response bodies are capped (128 KiB default) and the cap is enforced
  *during* streaming, before the full body is materialised.
- Decoding is strict UTF-8: a decode failure raises rather than silently
  mutating the settlement datum (and its digest) via ``errors="replace"``.
- The SHA-256 digest is computed over the exact raw bytes received, before
  anything (decoding, normalization) can transform them.
- The instant of receipt is stamped **here**, adjacent to that digest, from
  an injected clock. This layer is the only one that knows when the bytes
  arrived; every later layer can only guess, and a late guess silently
  degrades replay fidelity (see :class:`FetchResult`).
- Conditional-GET validators are accepted as typed *values*, never as a
  caller-supplied header mapping, so the hardened headers above cannot be
  displaced per call. An ``ETag`` is remote data being echoed back into an
  outbound request, so it is validated for length and charset before it is
  ever placed in a header (see :func:`_validated_cache_validator`).
"""

from __future__ import annotations

import hashlib
import os
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

DEFAULT_MAX_BODY_BYTES = 128 * 1024  # 128 KiB; real CLI products are <64 KiB.
DEFAULT_CHUNK_SIZE = 8 * 1024
DEFAULT_CONTACT = "breezy-data@gmail.com"
USER_AGENT_ENV_VAR = "BREEZY_USER_AGENT"

# Generous for a real validator (NWS ETags run ~40 chars, an HTTP-date 29)
# and far below anything that could be used to smuggle a payload.
MAX_VALIDATOR_LENGTH = 256

# RFC 9110 field-value characters, minus the obsolete forms: printable US-ASCII
# only. This excludes CR, LF and NUL (header injection), HTAB and DEL (obs-fold
# and control smuggling), and every non-ASCII byte.
_VALIDATOR_CHARSET = re.compile(r"\A[\x20-\x7e]+\Z")

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
    """Raised when the server responds with a 3xx status other than 304.

    Redirects are never followed. On a settlement endpoint this is treated
    as an integrity alarm, not a normal fetch outcome.

    304 Not Modified is deliberately excluded: it is the expected success
    response to a conditional GET on the discovery-list endpoint and is
    returned to the caller as a normal ``FetchResult`` instead (see
    :meth:`HttpTransport.fetch`).

    305 (Use Proxy) and 306 (reserved, unused since HTTP/1.1) remain
    alarms. 305 instructs the client to route through a proxy, which on a
    settlement path is arguably *more* alarming than an ordinary redirect,
    not less; 306 has no legitimate use, so a live server emitting it is
    itself anomalous. Neither is a response the conditional GET is ever
    expected to produce.
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


class InvalidCacheValidatorError(TransportError):
    """Raised when a conditional-GET validator is not well formed.

    Raised before any socket is opened. A validator is remote data (an
    ``ETag``/``Last-Modified`` the origin sent us) being echoed back into an
    outbound request, so it is the one caller-supplied value in this module
    that reaches the wire. Anything carrying CR/LF, a control character, a
    non-ASCII byte, surrounding whitespace, or an absurd length is refused
    rather than sanitised: a header-injection vector through a stored ETag is
    precisely what the rest of this module's hardening exists to prevent.
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


def _validated_cache_validator(value: str, header: str) -> str:
    """Return `value` if it is safe to place in `header`, else raise.

    Static typing already pins the parameter to `str` at every call site, so
    this guards the runtime threat rather than the type: a validator that
    round-tripped through a remote server and our own storage before being
    echoed back out. The error message names the *header*, never the value —
    an untrusted string must not be laundered into a log line.
    """
    if len(value) > MAX_VALIDATOR_LENGTH:
        raise InvalidCacheValidatorError(
            f"{header} validator exceeds the maximum length of "
            f"{MAX_VALIDATOR_LENGTH} characters."
        )
    if value != value.strip():
        raise InvalidCacheValidatorError(
            f"{header} validator must not carry leading or trailing whitespace."
        )
    if _VALIDATOR_CHARSET.match(value) is None:
        raise InvalidCacheValidatorError(
            f"{header} validator is empty or contains characters that are not "
            "printable US-ASCII; it is refused rather than sanitised."
        )
    return value


def _conditional_headers(
    *,
    if_none_match: str | None,
    if_modified_since: str | None,
) -> dict[str, str]:
    """Build the conditional-GET request headers from validated values.

    The header *names* are supplied here and only here. A caller passes
    values, never keys, so no per-call input can displace the hardened
    ``User-Agent``/``Accept-Encoding`` set on the client.
    """
    headers: dict[str, str] = {}
    if if_none_match is not None:
        headers["If-None-Match"] = _validated_cache_validator(if_none_match, "If-None-Match")
    if if_modified_since is not None:
        headers["If-Modified-Since"] = _validated_cache_validator(
            if_modified_since, "If-Modified-Since"
        )
    return headers


# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """Result of a successful fetch, including 304 Not Modified.

    **A `FetchResult` describes an exchange.** One rule governs its fields, in
    two clauses that share that subject:

    1. The exchange *always happened at an instant*, so ``retrieved_at_ns`` is
       unconditional — present on every status, 304 included.
    2. The exchange *carried a document* exactly when the status says a body
       was sent, so ``text`` and ``sha256`` are present iff
       ``status_code != 304``.

    ``sha256`` is computed over the exact raw bytes received, before UTF-8
    decoding, so provenance is captured ahead of any transformation.
    ``retrieved_at_ns`` is stamped adjacent to it, from the transport's
    injected clock, so the two describe the same event.

    A 304 has no body (RFC 9110 SS15.4.5): ``text`` and ``sha256`` are
    ``None`` in that case, never the digest of an empty body. That keeps a
    "nothing changed" response from being mistaken for a zero-length
    fetched document, and forces a ``status_code`` check (enforced by
    mypy under strict mode, since both fields are ``str | None``) before
    either field can flow into a provenance record.

    A 304 *does* carry ``retrieved_at_ns``. The body carve-out is about the
    document, not the exchange: a 304 is the healthy steady-state answer to a
    conditional GET, it is a successful poll for the freshness watchdog (which
    measures liveness in nanoseconds), and a stampless 304 would force the
    caller to re-stamp from its own clock — reintroducing the second source of
    truth this field exists to remove.

    ``retrieved_at_ns`` has no default. Omission is a ``TypeError`` from the
    generated ``__init__``; a zero or negative value is rejected below,
    because "silently omitted" and "stamped as 0" are the same defect wearing
    different clothes.
    """

    text: str | None
    sha256: str | None
    status_code: int
    headers: httpx.Headers
    url: str
    retrieved_at_ns: int
    retry_after: str | None = None

    def __post_init__(self) -> None:
        # Clause 1 — the exchange always happened at an instant.
        # `bool` is an `int` subclass and is rejected explicitly: a stray
        # `True` would sail through the range check as 1 nanosecond.
        if isinstance(self.retrieved_at_ns, bool) or not isinstance(self.retrieved_at_ns, int):
            raise TypeError(
                "`retrieved_at_ns` must be an `int` of UNIX nanoseconds, was "
                f"{type(self.retrieved_at_ns).__name__}"
            )
        if self.retrieved_at_ns <= 0:
            raise ValueError(
                f"`retrieved_at_ns` must be a positive UNIX-nanosecond instant, was "
                f"{self.retrieved_at_ns}"
            )

        # Clause 2 — it carried a document iff the status says a body was sent.
        has_body = self.text is not None or self.sha256 is not None
        if self.status_code == 304 and has_body:
            raise ValueError("304 Not Modified FetchResult must not carry text/sha256")
        if self.status_code != 304 and not has_body:
            raise ValueError(f"status {self.status_code} FetchResult must carry text and sha256")


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
        clock: Callable[[], int],
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
        # `clock` is required and injected, exactly as `SettlementGate` takes
        # it: a `Callable[[], int]` of UNIX nanoseconds. The ingest Actor
        # passes `Actor.clock.timestamp_ns` (Nautilus' own native clock) so the
        # receipt stamps that become `ts_init` and the gate's freshness
        # watchdog read ONE clock. A module-level default would be a second
        # clock that can silently diverge from it, and would make the exact
        # stamped value unassertable under test -- which is how a late stamp
        # gets in unnoticed.
        self._clock = clock
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

    async def fetch(
        self,
        url: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        """Fetch ``url`` and return its raw-bytes digest, decoded text and receipt instant.

        Parameters
        ----------
        url : str
            The absolute HTTPS URL to fetch. Validated against the scheme,
            userinfo, port and host-allowlist rules before any socket opens.
        if_none_match : str or None
            An ``ETag`` from a previous response for this URL, sent as
            ``If-None-Match``. Supply it to make the origin answer 304 when
            nothing changed.
        if_modified_since : str or None
            A ``Last-Modified`` value from a previous response for this URL,
            sent as ``If-Modified-Since``.

        Both validators are accepted as *values*, never as a header mapping:
        the transport builds the header names itself, so a caller cannot
        displace ``User-Agent``, ``Accept-Encoding`` or any other hardened
        header on a per-call basis. Each is checked by
        :func:`_validated_cache_validator` before it reaches the wire.

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

        # Host allowlisting stays the outermost gate; validator checks follow,
        # and both complete before a socket is opened.
        self._validate_url(url)
        conditional_headers = _conditional_headers(
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
        )

        try:
            async with (
                self._build_client() as client,
                client.stream("GET", url, headers=conditional_headers) as response,
            ):
                self._raise_for_status(response)
                if response.status_code == 304:
                    return self._not_modified_result(response, url)
                self._reject_unexpected_content_encoding(response)
                body = await self._read_capped_body(response)
                # Stamp and digest, adjacent and in that order, on the bytes
                # that just finished arriving: one clock read, describing the
                # same event as the digest beside it. Nothing (a decode, an
                # await, a parse, a record construction) is allowed to come
                # between the arrival and the instant recorded for it.
                retrieved_at_ns = self._clock()
                digest = hashlib.sha256(body).hexdigest()
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

        return FetchResult(
            text=text,
            sha256=digest,
            status_code=response.status_code,
            headers=response.headers,
            url=url,
            retrieved_at_ns=retrieved_at_ns,
            retry_after=response.headers.get("retry-after"),
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if 300 <= status < 400 and status != 304:
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

    def _not_modified_result(self, response: httpx.Response, url: str) -> FetchResult:
        """Build the ``FetchResult`` for a 304 Not Modified response.

        304 carries no body per RFC 9110 SS15.4.5, so there is nothing to
        decode or digest. ``ETag``/``Last-Modified`` still arrive on
        ``response.headers`` for the caller to persist for the next
        conditional GET.

        The receipt instant IS stamped here — one clock read, at the point the
        response was received. A 304 has no document but it is still an
        exchange that happened at a time, and it is a successful poll for the
        freshness watchdog.
        """
        return FetchResult(
            text=None,
            sha256=None,
            status_code=response.status_code,
            headers=response.headers,
            url=url,
            retrieved_at_ns=self._clock(),
            retry_after=response.headers.get("retry-after"),
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
