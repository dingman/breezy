"""Hardened outbound HTTP transport for untrusted third-party data sources.

This module fetches NWS product text that determines real-money settlement.
It is deliberately isolated from ``nautilus_trader`` (no import of it here)
so it stays unit-testable with ``respx`` in complete isolation, and is used
only for weather-data ingestion — venue traffic keeps
``nautilus_pyo3.HttpClient``. See docs/plans/WEATHER_INGESTION_PROPOSAL.md
section 6 for the full rationale and the evaluation of why
``nautilus_pyo3.HttpClient`` cannot express these controls.

Every control below is individually load-bearing:

- HTTPS-only + host allowlist, checked before any socket opens, on the URL
  the transport itself constructed.
- Callers pass **typed identifiers, never URLs**: the two public fetch
  methods take a bare CLI location code and a product id respectively, and
  build their own paths. The origin is configurable; the paths are not.
  Both identifiers are untrusted (one comes from the registry, one is
  parsed out of remote JSON), so each is shape-checked before it can become
  a path segment -- traversal, injection and absolute-URL forms are refused
  rather than sanitised. Construction is defence in depth, not a substitute
  for the allowlist, which still guards the finished URL.
- Redirects are never followed: a 3xx on a settlement endpoint is an
  integrity alarm, not a fetch step. The one deliberate exception is 304
  Not Modified, the expected success response to a conditional GET
  (``If-None-Match``) against the discovery-list endpoint; 305 and 306
  remain alarms (see ``RedirectError`` and ``FetchResult``). That carve-out
  is scoped to the endpoint that can legitimately produce it -- see the
  conditional-GET control below.
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
- Conditional GET is restricted to the endpoint where it is safe, **in the
  type system rather than in this prose**. There are two public fetch
  methods over one private implementation:
  :meth:`HttpTransport.fetch_discovery_list` takes validators;
  :meth:`HttpTransport.fetch_product` takes none at all. A discovery list is
  a mutable index of what exists, so revalidating it is correct. A
  ``/products/{id}`` body is immutable by id, so there is nothing to
  revalidate: a conditional GET there buys nothing and costs correctness,
  because a 304 routes as a *successful poll* that satisfies the freshness
  watchdog while writing no record and recording no digest. "Conditionally
  GET a product body" is therefore not a call that can be written, rather
  than one that is discouraged. Because the two methods take *identifiers*
  of mutually exclusive shape rather than URLs, the converse mistake --
  aiming the conditional-GET method at a product body -- is equally
  inexpressible.
"""

from __future__ import annotations

import hashlib
import os
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

DEFAULT_BASE_URL = "https://api.weather.gov"

DEFAULT_MAX_BODY_BYTES = 128 * 1024  # 128 KiB; real CLI products are <64 KiB.
DEFAULT_CHUNK_SIZE = 8 * 1024
DEFAULT_CONTACT = "breezy-data@gmail.com"
USER_AGENT_ENV_VAR = "BREEZY_USER_AGENT"

# Generous for a real validator (NWS ETags run ~40 chars, an HTTP-date 29)
# and far below anything that could be used to smuggle a payload.
MAX_VALIDATOR_LENGTH = 256

# The BARE CLI location code -- the `{loc}` segment of
# /products/types/CLI/locations/{loc}, e.g. `NYC`, `SFO`, `MIA`, `MDW`, `LAX`.
#
# This is NOT the AWIPS PIL. The PIL (`CLINYC`) appears on line 3 of the
# product TEXT and is a different identifier in a different position;
# conflating the two has already been a live defect in this project, so
# `CLINYC` is refused here rather than fetched as a location that does not
# exist.
#
# The shape is all this module enforces. `src/breezy/registry/sites.toml` is
# the single source of truth for WHICH codes are legitimate -- station
# identifiers are never hardcoded in settlement logic. Loosening this pattern
# is a deliberate decision that needs a registry cross-check, not a
# convenience edit.
_CLI_LOCATION_PATTERN = re.compile(r"\A[A-Z]{3}\Z")

# A product id as api.weather.gov assigns it: a canonical UUID. Every id
# observed in this project's fixtures and every id described by the
# `nws-cli-settlement` skill has this shape.
#
# Matched WITHOUT normalising, so the id placed in the path is byte-identical
# to the id `ingest/product_index.py` records as `product_uuid` -- parsing and
# re-serialising through `uuid.UUID` would accept `urn:uuid:` and braced forms
# and then silently rewrite a settlement lookup key.
_PRODUCT_ID_PATTERN = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)

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

    304 Not Modified is excluded **on the discovery-list endpoint only**,
    where it is the expected success response to a conditional GET and is
    returned to the caller as a normal ``FetchResult`` instead (see
    :meth:`HttpTransport.fetch_discovery_list`).

    On :meth:`HttpTransport.fetch_product` a 304 IS raised through this
    class, with ``status_code == 304``. That path never sends a validator,
    so a 304 there is unsolicited and cannot be a truthful "your copy is
    current" -- it is a stale-copy integrity alarm on the body that
    determines settlement.

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


def _validated_path_identifier(value: str, *, name: str, shape: str, pattern: re.Pattern[str]) -> str:
    """Return `value` percent-encoded for use as ONE path segment, else raise.

    Both identifiers this module accepts are untrusted. `cli_location` comes
    from a registry value; `product_id` is **network-derived**, parsed out of
    the discovery-list JSON an origin served us. A leading `/`, a `..`, a
    query `?`, a fragment `#` or an encoded `%2e%2e%2f` in either one is a
    path-manipulation primitive, and refusing those is the entire reason this
    module exists.

    The shape check is exact-match anchored, so nothing outside the permitted
    charset survives -- traversal, injection and absolute-URL forms are all
    rejected by construction rather than stripped. `quote(safe="")` on the way
    out is a no-op for every value that passes, and is applied anyway so the
    encoding guarantee does not silently depend on the pattern staying tight.

    Raises `ValueError`, deliberately NOT a `TransportError`: nothing was
    transported. The request could not even be FORMED, so there is no poll
    outcome to route it to, and letting it be caught by an
    `except TransportError` handler would let a path-manipulation attempt be
    logged as a network condition.

    The message names the *parameter*, never the value -- the same rule the
    cache validators follow, for the same reason: an untrusted string must not
    be laundered into a log line.
    """
    if pattern.match(value) is None:
        raise ValueError(
            f"`{name}` must be {shape}; the supplied value does not match and is "
            "refused rather than sanitised. The value is withheld from this "
            "message because it is untrusted input."
        )
    return quote(value, safe="")


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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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
        base_url: str = DEFAULT_BASE_URL,
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
        # The ORIGIN is configurable so tests can retarget it; the PATHS are
        # not -- they are built from validated identifiers by the two
        # `_*_url` helpers below. A caller supplies what to fetch, never
        # where on the origin to fetch it from.
        self._base_url = base_url.rstrip("/")
        self._max_body_bytes = max_body_bytes
        self._chunk_size = chunk_size
        self._timeouts = _Timeouts(
            connect=connect_timeout, read=read_timeout, write=write_timeout, pool=pool_timeout
        )
        self._user_agent = user_agent or _default_user_agent()
        self._ssl_context = _build_ssl_context()

    def _discovery_list_url(self, cli_location: str) -> str:
        """Build the discovery-list URL for a BARE CLI location code.

        `cli_location` is the `{loc}` path segment (`NYC`), never the AWIPS
        PIL (`CLINYC`) and never the issuing WFO (`OKX`) -- three different
        identifier spaces for the same site.
        """
        segment = _validated_path_identifier(
            cli_location,
            name="cli_location",
            shape=(
                "the bare three-letter CLI location code (e.g. `NYC`), not the "
                "AWIPS PIL (`CLINYC`), not the issuing office, and not a URL"
            ),
            pattern=_CLI_LOCATION_PATTERN,
        )
        return f"{self._base_url}/products/types/CLI/locations/{segment}"

    def _product_url(self, product_id: str) -> str:
        """Build the product-body URL for a product id (a canonical UUID)."""
        segment = _validated_path_identifier(
            product_id,
            name="product_id",
            shape=(
                "a canonical UUID as assigned by api.weather.gov (8-4-4-4-12 "
                "hex digits), not a URL and not a path fragment"
            ),
            pattern=_PRODUCT_ID_PATTERN,
        )
        return f"{self._base_url}/products/{segment}"

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

    async def fetch_discovery_list(
        self,
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        """Fetch a station's **discovery list**, optionally as a conditional GET.

        This is the endpoint where conditional GET is correct: the list of
        products for a location is a *mutable index of what exists*, it is
        polled far more often than it changes, and a 304 there is a true
        statement that nothing new has been published. Revalidating it is
        the whole point.

        Parameters
        ----------
        cli_location : str
            The **bare** CLI location code -- the ``{loc}`` path segment of
            ``/products/types/CLI/locations/{loc}``, e.g. ``NYC``. The
            transport builds the path; the caller never supplies a URL.

            This is **not** the AWIPS PIL: the PIL for that site is
            ``CLINYC`` and lives on line 3 of the product text. It is also
            not the issuing office (``OKX``). Three identifier spaces, one
            site -- see ``src/breezy/registry/sites.toml``, which is the
            single source of truth for which codes are legitimate.
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

        A 304 comes back as a normal :class:`FetchResult` with
        ``status_code == 304`` and no document. On this endpoint that is the
        healthy steady state.

        Raises `ValueError` if `cli_location` is not a well-formed bare
        location code (before any socket opens), or one of the
        :class:`TransportError` subclasses on any transport failure mode;
        never returns a partially-materialised or lossily-decoded body.
        """
        return await self._fetch(
            self._discovery_list_url(cli_location),
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=True,
        )

    async def fetch_product(self, product_id: str) -> FetchResult:
        """Fetch a **product body** by id. Unconditionally, always, by construction.

        This method takes no cache-validator parameters, and that absence is
        the point: it makes "conditionally GET a product body" something a
        caller cannot express, rather than something a docstring discourages.

        It also takes an **id, not a URL**, which is what makes the converse
        mistake -- pointing :meth:`fetch_discovery_list` at a product body to
        get its validators back -- equally inexpressible. A CLI location is
        three uppercase letters and a product id is a canonical UUID, so no
        string satisfies both and neither method can be aimed at the other's
        endpoint.

        A ``/products/{id}`` body is **immutable by id**. There is nothing
        there to revalidate, so a conditional GET buys nothing and costs
        correctness. A 304 routes as a *successful poll*
        (``routing.route_fetch_result`` -> ``PollOutcome.NOT_MODIFIED``,
        "freshness satisfied, no record written"), so a stale or buggy 304 on
        a product fetch -- a known class of server-side ETag defect, or simply
        a reissue racing the validator capture -- would leave the site reading
        OPEN and fresh while a corrected final sat unfetched.
        ``FINAL_CLI_OVERDUE`` would not catch it either: that watchdog fires
        off a *deadline*, not off "is my copy current". The failure would be
        invisible to every gate signal until the next discovery poll.

        Because this path never sends a validator, a 304 *received* here is
        unsolicited (RFC 9110 SS15.4.5: 304 answers a conditional request) and
        is raised as a :class:`RedirectError` integrity alarm rather than
        returned. Closing the signature stops us asking for one; that check
        stops a buggy or hostile origin volunteering one.

        Parameters
        ----------
        product_id : str
            The product id assigned by api.weather.gov -- a canonical UUID,
            the same value ``ingest/product_index.py`` records as
            ``product_uuid``. The transport builds ``/products/{id}`` itself.

            This value is **network-derived** (parsed out of the discovery
            JSON), so it is treated as untrusted: its shape is checked before
            it is placed in a path, and it is never normalised, so the id
            fetched is byte-identical to the id recorded as provenance.

        Raises `ValueError` if `product_id` is not a well-formed product id
        (before any socket opens), or one of the :class:`TransportError`
        subclasses on any transport failure mode; never returns a
        partially-materialised or lossily-decoded body.
        """
        return await self._fetch(
            self._product_url(product_id),
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
        )

    async def _fetch(
        self,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        """Shared hardened implementation behind both public fetch methods.

        Private so that the endpoint distinction cannot be bypassed by
        reaching past the two public methods, and so the hardening cannot
        fork between them: every control (allowlist, TLS floor, redirect
        alarm, size cap, strict decode, digest-before-decode, receipt stamp)
        is applied here, once, for both.

        ``allow_not_modified`` is a property of the *endpoint*, fixed by
        which public method was called -- deliberately not derived from
        whether this particular call happened to carry a validator. Deriving
        it per call would put a correctness-critical branch back onto
        per-call state, which is exactly the fragility the split removes.
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
                self._raise_for_status(response, allow_not_modified=allow_not_modified)
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

    def _raise_for_status(self, response: httpx.Response, *, allow_not_modified: bool) -> None:
        status = response.status_code
        if status == 304 and not allow_not_modified:
            # Unsolicited: this endpoint never sends a validator, and RFC 9110
            # SS15.4.5 says 304 answers a conditional request. Returned as a
            # `FetchResult` it would route to `PollOutcome.NOT_MODIFIED` and
            # satisfy the freshness watchdog while writing no record, which on
            # a settlement body is the exact silent-staleness failure the
            # endpoint split exists to prevent. Raised as the EXISTING
            # `RedirectError` -- no new subclass, since `routing.py` enumerates
            # them and a contract test fails if one lacks a route.
            raise RedirectError(
                f"Server returned 304 Not Modified for {redact_url(str(response.url))}, "
                "which sent no conditional-GET validator. An unsolicited 304 on an "
                "immutable-by-id body is an integrity alarm, not a fresh poll.",
                status_code=status,
                location=response.headers.get("location"),
            )
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
