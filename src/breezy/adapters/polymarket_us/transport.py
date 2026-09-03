"""Read-only HTTP transport for Polymarket.us (plan revision 2, section 6).

Null hypothesis first. Nautilus already ships the transport this adapter
needs: ``nautilus_pyo3.HttpClient`` provides connection pooling, per-key
token-bucket rate limiting (``keyed_quotas`` / ``default_quota``), whole-second
timeouts and a response-header allow-list, all in Rust
(``nautilus_trader/core/nautilus_pyo3.pyi:5416-5448``). Nothing here
re-implements any of that. This module contributes exactly three things
Nautilus does not and should not know about:

1. a Breezy-owned ``Protocol`` (:class:`PolymarketUSReadTransport`) so the HTTP
   client can be driven by a recording double in tests without monkeypatching
   a third-party object's private attributes (plan D4, evidence 1);
2. the venue rate-limit budget (section 8.2) expressed as ``Quota`` objects;
3. **order-submission barrier B3**: the pyo3 client is captured inside a
   module-private GET-only callable whose instance has no client attribute and
   no bound method whose ``__self__`` is the client. There is no
   ``transport._client`` to walk to a write verb, and ``__slots__`` closes the
   companion hole -- a write-capable client cannot be attached later either.

The pyo3 client is looked up as ``nautilus_pyo3.HttpClient`` at construction
time rather than imported by name, so ``tests/conftest.py``'s autouse
kill-switch (which replaces the constructor on the module object) is effective
against this module.

TLS is never disabled: ``HttpClient`` exposes no verification switch and none
is wanted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from nautilus_trader.core import nautilus_pyo3

from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.redaction import redact_url
from breezy.ingest.http import assert_clean_proxy_env

__all__ = [
    "DEFAULT_BOOK_REQUESTS_PER_MINUTE",
    "DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE",
    "DEFAULT_GLOBAL_REQUESTS_PER_SECOND",
    "DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE",
    "DEFAULT_PORTFOLIO_REQUESTS_PER_MINUTE",
    "OBSERVED_RESPONSE_HEADERS",
    "PERMITTED_QUOTA_KEYS",
    "QUOTA_KEY_BOOK",
    "QUOTA_KEY_DEFAULT",
    "QUOTA_KEY_DISCOVERY",
    "QUOTA_KEY_INSTRUMENTS",
    "QUOTA_KEY_PORTFOLIO",
    "REDIRECT_STATUS_LOWER",
    "REDIRECT_STATUS_UPPER",
    "RETAIL_GLOBAL_REQUESTS_PER_SECOND",
    "NautilusHttpTransport",
    "PolymarketUSReadTransport",
    "VenueResponse",
    "assert_permitted_quota_key",
    "build_default_quota",
    "build_keyed_quotas",
    "build_shared_http_client",
]

#: Response headers we ask the Rust client to surface. ``HttpClient`` hides
#: ALL response headers unless they are named here
#: (nautilus-trader-patterns trap 11), and the venue's back-pressure signal
#: lives entirely in these.
OBSERVED_RESPONSE_HEADERS: tuple[str, ...] = (
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "date",
    # Named so a redirect is at least VISIBLE. Without it the allow-list hides
    # `Location`, and a 3xx is invisible in logs as well as in the code path.
    "location",
)

#: Statuses refused outright by :meth:`NautilusHttpTransport.get`.
#:
#: See the class docstring for what this does and does not achieve: it stops a
#: redirect the Rust client hands BACK to us, and it cannot stop one the Rust
#: client already followed.
REDIRECT_STATUS_LOWER: int = 300
REDIRECT_STATUS_UPPER: int = 400

QUOTA_KEY_INSTRUMENTS: str = "instruments"
QUOTA_KEY_DISCOVERY: str = "discovery"
QUOTA_KEY_BOOK: str = "book"
QUOTA_KEY_PORTFOLIO: str = "portfolio"
QUOTA_KEY_DEFAULT: str = "default"

#: Every key a read may be budgeted under. A call carrying anything else is a
#: programming error, not a silently-unthrottled request: adding an endpoint
#: without giving it a budget fails loudly at the first call.
PERMITTED_QUOTA_KEYS: frozenset[str] = frozenset(
    {
        QUOTA_KEY_INSTRUMENTS,
        QUOTA_KEY_DISCOVERY,
        QUOTA_KEY_BOOK,
        QUOTA_KEY_PORTFOLIO,
        QUOTA_KEY_DEFAULT,
    }
)

#: The documented RETAIL ceiling, recorded so the headroom below is auditable:
#: "The Retail API enforces a global rate limit of 20 requests per second per
#: API key across all endpoints", and 20 req/s per IP for public/unauthenticated
#: reads -- ``docs/evidence/venue/polymarket_us/docs_snapshots/
#: api-reference_rate-limits_2026-08-25.md:15,19-20``.
#:
#: The per-endpoint 6/min and 12/min figures in ``trader-guide_rate-limits_*``
#: describe the INSTITUTIONAL DMA surface, measured per participant firm, which
#: Breezy never reaches. They are adopted below only *prudentially* -- as the
#: venue's own statement that instrument and book reads are expensive and
#: should be cached and streamed -- never as our governing limit.
RETAIL_GLOBAL_REQUESTS_PER_SECOND: int = 20

#: Breezy's global budget: 25% headroom under the retail cap.
DEFAULT_GLOBAL_REQUESTS_PER_SECOND: int = 15
DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE: int = 6
DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE: int = 6
DEFAULT_BOOK_REQUESTS_PER_MINUTE: int = 12
DEFAULT_PORTFOLIO_REQUESTS_PER_MINUTE: int = 12


def _build_get_only_callable(client: Any) -> Callable[..., Awaitable[Any]]:
    """Return a callable GET proxy without storing ``client`` on an object.

    The returned object exposes only ``__call__``. Its ``__self__`` is the proxy
    object, not the pyo3 client, and the proxy has no attributes. The client is
    still reachable through deliberate Python function-closure introspection;
    B3's purpose is to remove the ordinary attribute and bound-method receiver
    paths that a caller or refactor would naturally take.
    """

    class _GetOnlyCallable:
        __slots__ = ()

        async def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return await client.get(*args, **kwargs)

        def __repr__(self) -> str:
            return "NautilusHttpTransportGetOnlyCallable()"

    return _GetOnlyCallable()


@dataclass(frozen=True, slots=True)
class VenueResponse:
    """One venue HTTP response, reduced to what the read path may observe.

    ``headers`` contains only the :data:`OBSERVED_RESPONSE_HEADERS` the Rust
    client was told to surface, so a response header cannot smuggle anything
    unexpected into a log line.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


@runtime_checkable
class PolymarketUSReadTransport(Protocol):
    """The Breezy-owned read seam: a GET, a quota key, and nothing else.

    There is deliberately no ``method`` parameter. A protocol that cannot
    express a write verb cannot be asked to perform one.
    """

    async def get(
        self, url: str, *, headers: Mapping[str, str], quota_key: str
    ) -> VenueResponse: ...


def assert_permitted_quota_key(quota_key: str) -> None:
    """Raise ``ValueError`` unless ``quota_key`` has a budget (section 8.2)."""
    if quota_key not in PERMITTED_QUOTA_KEYS:
        raise ValueError(
            f"Unknown quota_key {quota_key!r}; every Polymarket.us read must be "
            f"budgeted under one of {sorted(PERMITTED_QUOTA_KEYS)}"
        )


def build_default_quota(
    requests_per_second: int = DEFAULT_GLOBAL_REQUESTS_PER_SECOND,
) -> Any:
    """Build the fallback quota applied to any key without its own budget."""
    if not 0 < requests_per_second < RETAIL_GLOBAL_REQUESTS_PER_SECOND:
        raise ValueError(
            "The global read budget must sit strictly under the documented retail "
            f"cap of {RETAIL_GLOBAL_REQUESTS_PER_SECOND} requests/second; "
            f"got {requests_per_second}"
        )
    return _record_quota_spec(
        nautilus_pyo3.Quota.rate_per_second(requests_per_second),
        kind="rate_per_second",
        burst=requests_per_second,
    )


def build_keyed_quotas(
    *,
    discovery_requests_per_minute: int = DEFAULT_DISCOVERY_REQUESTS_PER_MINUTE,
    instrument_requests_per_minute: int = DEFAULT_INSTRUMENT_REQUESTS_PER_MINUTE,
    book_requests_per_minute: int = DEFAULT_BOOK_REQUESTS_PER_MINUTE,
    portfolio_requests_per_minute: int = DEFAULT_PORTFOLIO_REQUESTS_PER_MINUTE,
) -> list[tuple[str, Any]]:
    """Build the per-endpoint budget table of plan section 8.2.

    Deliberately tighter than the retail 20/s ceiling for the instrument and
    book classes: loading twenty market slugs at fifteen per second would
    otherwise issue twenty instrument reads inside two seconds. The instrument
    provider caches for the session and book state arrives over the WebSocket,
    so this budget costs nothing in the steady state.
    """
    for name, value in (
        ("discovery_requests_per_minute", discovery_requests_per_minute),
        ("instrument_requests_per_minute", instrument_requests_per_minute),
        ("book_requests_per_minute", book_requests_per_minute),
        ("portfolio_requests_per_minute", portfolio_requests_per_minute),
    ):
        if value <= 0:
            raise ValueError(f"{name} must be positive; got {value}")
    return [
        (
            QUOTA_KEY_DISCOVERY,
            _record_quota_spec(
                nautilus_pyo3.Quota.rate_per_minute(discovery_requests_per_minute),
                kind="rate_per_minute",
                burst=discovery_requests_per_minute,
            ),
        ),
        (
            QUOTA_KEY_INSTRUMENTS,
            _record_quota_spec(
                nautilus_pyo3.Quota.rate_per_minute(instrument_requests_per_minute),
                kind="rate_per_minute",
                burst=instrument_requests_per_minute,
            ),
        ),
        (
            QUOTA_KEY_BOOK,
            _record_quota_spec(
                nautilus_pyo3.Quota.rate_per_minute(book_requests_per_minute),
                kind="rate_per_minute",
                burst=book_requests_per_minute,
            ),
        ),
        (
            QUOTA_KEY_PORTFOLIO,
            _record_quota_spec(
                nautilus_pyo3.Quota.rate_per_minute(portfolio_requests_per_minute),
                kind="rate_per_minute",
                burst=portfolio_requests_per_minute,
            ),
        ),
    ]


#: Specs of ``Quota`` objects this module constructed, keyed by ``id()``.
#: ``Quota`` is opaque (no rate attributes, identity-hashed) so a cache key
#: cannot read the burst off the object; this table is the digest of the
#: spec, not a holder of the Quota.
_QUOTA_SPECS: dict[int, tuple[str, int]] = {}


def _record_quota_spec(quota: Any, *, kind: str, burst: int) -> Any:
    _QUOTA_SPECS[id(quota)] = (kind, burst)
    return quota


def _quota_spec(quota: Any) -> tuple[object, ...]:
    recorded = _QUOTA_SPECS.get(id(quota))
    if recorded is not None:
        return recorded
    return ("opaque", type(quota).__name__, id(quota))


def _headers_digest(headers: Mapping[str, str]) -> str:
    canonical = tuple(sorted((str(key), str(value)) for key, value in headers.items()))
    return hashlib.sha256(repr(canonical).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _SharedClientConstruction:
    timeout_secs: int
    default_quota_spec: tuple[object, ...]
    keyed_quotas_spec: tuple[tuple[str, tuple[object, ...]], ...]
    headers_digest: str


def _raise_construction_mismatch(
    stored: _SharedClientConstruction, incoming: _SharedClientConstruction
) -> None:
    if stored.timeout_secs != incoming.timeout_secs:
        differing = "timeout_secs"
    elif stored.default_quota_spec != incoming.default_quota_spec:
        differing = "default_quota"
    elif stored.keyed_quotas_spec != incoming.keyed_quotas_spec:
        differing = "keyed_quotas"
    elif stored.headers_digest != incoming.headers_digest:
        differing = "default_headers"
    else:
        differing = "arguments"
    raise ValueError(
        "build_shared_http_client already constructed; "
        f"{differing} differs from the first build and the singleton's "
        "config never updates"
    )


def _make_build_shared_http_client() -> Any:
    holder: list[Any] = []

    def build_shared_http_client(
        *,
        timeout_secs: int,
        default_quota: Any,
        keyed_quotas: list[tuple[str, Any]],
        default_headers: dict[str, str],
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
    ) -> Any:
        """Return the process-wide ``nautilus_pyo3.HttpClient``.

        Why an explicit holder, not ``@lru_cache(maxsize=1)``: ``default_headers``
        is a ``dict`` and ``keyed_quotas`` is a ``list`` (unhashable -- the first
        call would ``TypeError``), and ``Quota`` is hashable by identity -- two
        ``build_default_quota(15)`` objects compare unequal -- so a cache keyed
        on the arguments would mint a second bucket. The Quota is a client-side
        pacing bucket handed to the constructor; a second client halves that
        preventative control (plan §3 D1). Guards run on every call so a dirty
        proxy env or empty User-Agent cannot sneak through on a cache hit: they
        protect a construction ATTEMPT. The singleton's constructor arguments
        (timeout, quotas, headers) never update after the first successful
        build; a later call with a different configuration is a ``ValueError``,
        not a silent reuse.

        The process holds one client, which assumes a single asyncio event loop
        and no worker threads sharing this factory.

        `reqwest` honours HTTP_PROXY/HTTPS_PROXY/ALL_PROXY from the environment
        whenever no explicit proxy is configured, and no proxy is configured
        here. Measured: an `HTTP_PROXY` listener received a request carrying
        `x-pm-access-key` and `x-pm-signature`. `breezy.ingest.http` has guarded
        its own client this way since it was written (`ingest/http.py:557,783`);
        the path carrying SIGNING CREDENTIALS was the one left outside that
        control. Checked before the client is constructed so a dirty environment
        is a startup failure, never a dispatched request. `check_proxy_env` is
        threaded from `BREEZY_ALLOW_PROXY_ENV` so this adapter and the ingest
        client obey one operator switch rather than two.
        """
        if check_proxy_env:
            assert_clean_proxy_env(approved_proxy_env_vars)
        if timeout_secs <= 0:
            raise ValueError(f"timeout_secs must be positive; got {timeout_secs}")
        if not default_headers.get("User-Agent"):
            raise ValueError(
                "A non-empty User-Agent is required: gap G15 makes the effective "
                "User-Agent the attributable signal if the gateway ever refuses a "
                "non-browser fetch"
            )
        incoming = _SharedClientConstruction(
            timeout_secs=timeout_secs,
            default_quota_spec=_quota_spec(default_quota),
            keyed_quotas_spec=tuple((key, _quota_spec(quota)) for key, quota in keyed_quotas),
            headers_digest=_headers_digest(default_headers),
        )
        if holder:
            stored: _SharedClientConstruction = holder[0][0]
            if stored != incoming:
                _raise_construction_mismatch(stored, incoming)
            return holder[0][1]
        client = nautilus_pyo3.HttpClient(
            default_headers=default_headers,
            header_keys=list(OBSERVED_RESPONSE_HEADERS),
            keyed_quotas=keyed_quotas,
            default_quota=default_quota,
            timeout_secs=timeout_secs,
        )
        holder.append((incoming, client))
        return client

    build_shared_http_client._reset_for_tests = holder.clear  # type: ignore[attr-defined]
    return build_shared_http_client


build_shared_http_client = _make_build_shared_http_client()


class NautilusHttpTransport:
    """GET-only wrapper over ``nautilus_pyo3.HttpClient`` (barrier B3).

    The constructor takes a prebuilt client as a keyword-only argument and
    keeps only a GET-only callable object closed over that argument. Storing
    the client itself would put ``transport._client.post(...)`` one attribute
    hop away from any caller. Storing ``client.get`` is also insufficient
    because bound methods expose their receiver as ``__self__``. ``__slots__``
    prevents a client being attached afterwards.

    The Python object graph can still reach the client through deliberate
    closure-cell introspection on the callable's class method. That is a
    language residual, not an ordinary attribute path or a bound-method
    receiver path.

    Redirects -- what this class can and cannot do
    ---------------------------------------------
    ``HttpClient`` exposes no redirect policy (its constructor is exactly
    ``default_headers, header_keys, keyed_quotas, default_quota, timeout_secs,
    proxy_url`` -- ``core/nautilus_pyo3.pyi:5417-5425``), so ``reqwest``'s
    default ``Policy::limited(10)`` applies. ``reqwest`` strips only its own
    hardcoded sensitive header set on a cross-host hop, which does NOT include
    the venue's custom ``X-PM-*`` credential headers.

    Measured against two loopback listeners on different host strings: a 301,
    302, 303 or 307 carrying a ``Location`` is followed transparently, the
    second host receives ``x-pm-access-key`` / ``x-pm-timestamp`` /
    ``x-pm-signature`` intact, a control ``authorization`` header IS stripped,
    and this method observes the FINAL response -- status 200. ``HttpResponse``
    exposes only ``status``, ``headers`` and ``body``, with no final-URL
    attribute, so a followed hop is neither preventable nor detectable here.

    :meth:`get` therefore refuses every ``3xx`` it is handed, which covers the
    redirects ``reqwest`` declines to follow itself (measured: a 302 with no
    ``Location``, a 305, a 304) plus anything a future version stops following.
    It is defence in depth and drift detection, **not** a fix for the followed
    hop. The controls that actually bound that residual are the venue-domain
    origin allowlist in ``config.assert_well_formed_origin`` (only the venue
    itself, or an actor who has already broken TLS to the venue and can read
    the header directly, can emit the 302) and the read-only GET-only cage
    (what leaks is a non-secret key id plus a path-scoped signature valid for
    the venue's 30-second window, never an order capability).
    ``tests/unit/test_polymarket_us_transport_security.py`` pins the measured
    behaviour so a ``nautilus-trader`` bump that changes it fails RED.
    """

    __slots__ = ("_get", "_permitted_quota_keys")

    def __init__(
        self,
        *,
        client: Any,
        permitted_quota_keys: frozenset[str] = PERMITTED_QUOTA_KEYS,
    ) -> None:
        # Barrier B3. `client` is a constructor argument and is never stored.
        self._get: Callable[..., Awaitable[Any]] = _build_get_only_callable(client)
        self._permitted_quota_keys: frozenset[str] = permitted_quota_keys

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        """Perform one rate-limited GET and return a :class:`VenueResponse`.

        Every ``nautilus_pyo3`` transport failure is translated into
        :class:`~breezy.adapters.polymarket_us.errors.VenueTransportError` here,
        at the boundary where the pyo3 exception types are visible, so those
        types never leak through the Breezy-owned protocol into the client, the
        instrument provider, or a strategy.
        """
        if quota_key not in self._permitted_quota_keys:
            raise ValueError(
                f"Unknown quota_key {quota_key!r}; every Polymarket.us read must be "
                f"budgeted under one of {sorted(self._permitted_quota_keys)}"
            )
        try:
            response = await self._get(url, headers=dict(headers), keys=[quota_key])
        except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError) as exc:
            raise VenueTransportError(
                f"GET {redact_url(url)} failed at the transport layer "
                f"(quota_key={quota_key}): {type(exc).__name__}"
            ) from None
        status = int(response.status)
        if REDIRECT_STATUS_LOWER <= status < REDIRECT_STATUS_UPPER:
            # Refused, never decoded and never trusted. Only the status and the
            # redacted URL reach the message: the request headers -- which are
            # the credential -- are never echoed into an exception or a log.
            raise VenueTransportError(
                f"GET {redact_url(url)} returned a redirect status {status} "
                f"(quota_key={quota_key}). Breezy refuses to follow a redirect on "
                "the venue read path: the credential headers are custom "
                "'X-PM-*' names, which reqwest does not strip on a cross-host "
                "hop. Escalate rather than reroute."
            )
        return VenueResponse(
            status=int(response.status),
            headers=dict(response.headers),
            body=bytes(response.body),
        )

    def __repr__(self) -> str:
        return "NautilusHttpTransport(GET-only)"
