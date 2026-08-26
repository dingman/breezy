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

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from nautilus_trader.core import nautilus_pyo3

from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.redaction import redact_url

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
    "RETAIL_GLOBAL_REQUESTS_PER_SECOND",
    "NautilusHttpTransport",
    "PolymarketUSReadTransport",
    "VenueResponse",
    "assert_permitted_quota_key",
    "build_default_quota",
    "build_keyed_quotas",
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
)

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
    return nautilus_pyo3.Quota.rate_per_second(requests_per_second)


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
            nautilus_pyo3.Quota.rate_per_minute(discovery_requests_per_minute),
        ),
        (
            QUOTA_KEY_INSTRUMENTS,
            nautilus_pyo3.Quota.rate_per_minute(instrument_requests_per_minute),
        ),
        (QUOTA_KEY_BOOK, nautilus_pyo3.Quota.rate_per_minute(book_requests_per_minute)),
        (QUOTA_KEY_PORTFOLIO, nautilus_pyo3.Quota.rate_per_minute(portfolio_requests_per_minute)),
    ]


class NautilusHttpTransport:
    """GET-only wrapper over ``nautilus_pyo3.HttpClient`` (barrier B3).

    The constructor builds the client as a LOCAL and keeps only a GET-only
    callable object closed over that local. Storing the client itself would put
    ``transport._client.post(...)`` one attribute hop away from any caller.
    Storing ``client.get`` is also insufficient because bound methods expose
    their receiver as ``__self__``. ``__slots__`` prevents a client being
    attached afterwards.

    The Python object graph can still reach the client through deliberate
    closure-cell introspection on the callable's class method. That is a
    language residual, not an ordinary attribute path or a bound-method
    receiver path.
    """

    __slots__ = ("_get", "_permitted_quota_keys")

    def __init__(
        self,
        *,
        timeout_secs: int,
        default_quota: Any,
        keyed_quotas: list[tuple[str, Any]],
        default_headers: dict[str, str],
        permitted_quota_keys: frozenset[str] = PERMITTED_QUOTA_KEYS,
    ) -> None:
        if timeout_secs <= 0:
            raise ValueError(f"timeout_secs must be positive; got {timeout_secs}")
        if not default_headers.get("User-Agent"):
            raise ValueError(
                "A non-empty User-Agent is required: gap G15 makes the effective "
                "User-Agent the attributable signal if the gateway ever refuses a "
                "non-browser fetch"
            )
        client = nautilus_pyo3.HttpClient(
            default_headers=default_headers,
            header_keys=list(OBSERVED_RESPONSE_HEADERS),
            keyed_quotas=keyed_quotas,
            default_quota=default_quota,
            timeout_secs=timeout_secs,
        )
        # Barrier B3. `client` is a local and is never stored.
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
        return VenueResponse(
            status=int(response.status),
            headers=dict(response.headers),
            body=bytes(response.body),
        )

    def __repr__(self) -> str:
        return "NautilusHttpTransport(GET-only)"
