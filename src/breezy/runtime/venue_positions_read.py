"""The GET-only venue positions read (AUT-2 r7 WP0; ARCH §4.4; the reviewed egress dependency).

One cursor-paginated read of ``/v1/portfolio/positions`` and nothing else. The module builds on the
existing read-only client: ``PolymarketUSHttpClient`` dispatches ``GET`` only
(``PERMITTED_METHODS``) over a transport with no method parameter, and this module calls exactly
one of its methods, ``get_authenticated``. It never imports the order path (``exec/``, the write
transport, strategy or app code), and the only credential source is the process environment that
the unit's ``polymarket.env`` populates.

Bounds (P8). Every page request is bounded by ``VENUE_READ_REQUEST_TIMEOUT_S``; the whole read is
bounded by an overall deadline the caller passes in. Expiry of either cancels the in-flight request
and returns ``READ_FAILED`` with no rows. No failure raises past this module, so the caller can
always write its INCONCLUSIVE verdict. A failed read is never retried here.

The output carries base slugs, net quantities and the ``expired`` flag, and no account, position or
order identifier: every other key of a venue row is dropped at the parse.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final, NamedTuple, Protocol

from nautilus_trader.common.component import LiveClock

from breezy.adapters.polymarket_us.credentials import PolymarketUSSecretsRefConfig
from breezy.adapters.polymarket_us.env import load_polymarket_us_credentials
from breezy.adapters.polymarket_us.errors import VenueRateLimitError
from breezy.adapters.polymarket_us.factories import config_from_env
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_PORTFOLIO,
    NautilusHttpTransport,
    PolymarketUSReadTransport,
    VenueResponse,
    build_default_quota,
    build_keyed_quotas,
    build_shared_http_client,
)
from breezy.persistence.autonomy import pins
from breezy.runtime.settings import proxy_env_check_enabled

__all__ = [
    "MAX_PAGES",
    "POSITIONS_LITERAL",
    "POSITIONS_PAGE_MAX_BYTES",
    "VENUE_READ_REQUEST_TIMEOUT_S",
    "CappedReadTransport",
    "PositionRow",
    "ReadStatus",
    "VenuePositionsRead",
    "build_positions_client",
    "read_venue_positions",
    "validate_endpoint",
]

#: The single endpoint this module reads. A test pins it equal to the exec package's
#: ``PORTFOLIO_POSITIONS_PATH`` without this module importing that package.
POSITIONS_LITERAL: Final[str] = "/v1/portfolio/positions"

#: Per-request bound (the pyo3 client ``timeout_secs`` and an ``asyncio.wait_for`` per page).
VENUE_READ_REQUEST_TIMEOUT_S: Final[int] = 10

#: The page cap is the Wave 0 pin, never a local number.
MAX_PAGES: Final[int] = pins.POSTSTOP_POSITIONS_MAX_PAGES

#: Per-page response body cap, checked on the raw bytes before the client parses them (S2). A
#: positions page of a few hundred rows is tens of KiB; a body past this is refused, not parsed.
POSITIONS_PAGE_MAX_BYTES: Final[int] = 4 * 1024 * 1024

#: Endpoint labels are constants chosen by the caller, never payload data. Anything outside this
#: charset is refused rather than sanitised, so a path carrying a market slug or a query string
#: cannot become a filename.
_ENDPOINT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A/[A-Za-z0-9/_-]*\Z")

_CURSOR_QUERY_KEY: Final[str] = "cursor"


def validate_endpoint(endpoint: str) -> str:
    """Return ``endpoint`` if it is a plain path of ``[A-Za-z0-9/_-]``, else raise ``ValueError``.

    Moved verbatim from ``scripts/venue/polymarket_us_shape_capture.py`` (WP0), which re-imports it.
    """
    if not _ENDPOINT_PATTERN.fullmatch(endpoint):
        raise ValueError(
            "endpoint label must be a plain path of [A-Za-z0-9/_-]; refusing "
            "a label that could carry payload-derived text"
        )
    return endpoint


class ReadStatus(StrEnum):
    OK = "OK"
    QUOTA_REFUSED = "QUOTA_REFUSED"
    READ_FAILED = "READ_FAILED"


class PositionRow(NamedTuple):
    """One venue position: the base slug, the signed net quantity, and the ``expired`` flag."""

    base_slug: str
    net_qty: Decimal
    expired: bool


@dataclass(frozen=True)
class VenuePositionsRead:
    """The outcome of one read. ``rows`` is empty unless the read finished its pages cleanly."""

    snapshot_ns: int
    complete: bool
    pages: int
    read_status: ReadStatus
    rows: tuple[PositionRow, ...]


class _PageTooLarge(Exception):
    """A page body over the byte cap; mapped to ``READ_FAILED``."""


class CappedReadTransport:
    """A read transport that refuses an oversized body before the client's ``json.loads``.

    The body is already in memory when the transport returns it; the cap bounds the parse and
    everything after it, and the shipped transport is the only caller.
    """

    def __init__(self, inner: PolymarketUSReadTransport, *, max_bytes: int) -> None:
        self._inner = inner
        self._max_bytes = max_bytes

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        response = await self._inner.get(url, headers=headers, quota_key=quota_key)
        if len(response.body) > self._max_bytes:
            raise _PageTooLarge("a positions page body exceeds the byte cap")
        return response


class _GetAuthenticated(Protocol):
    async def get_authenticated(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        quota_key: str,
    ) -> Mapping[str, Any]: ...


class _MalformedPage(Exception):
    """A page that is not a well-shaped positions page; mapped to ``READ_FAILED``."""


def _parse_page(page: Mapping[str, Any]) -> list[PositionRow]:
    positions = page.get("positions")
    if not isinstance(positions, dict):
        raise _MalformedPage("positions is absent or not an object")
    rows: list[PositionRow] = []
    for slug, entry in positions.items():
        if not isinstance(slug, str) or not isinstance(entry, Mapping):
            raise _MalformedPage("a position entry is malformed")
        raw_net = entry.get("netPosition")
        expired = entry.get("expired")
        if raw_net is None or not isinstance(expired, bool):
            raise _MalformedPage("a position entry lacks netPosition or expired")
        try:
            net = Decimal(str(raw_net))
        except InvalidOperation as exc:
            raise _MalformedPage("netPosition is not a decimal") from exc
        if not net.is_finite():
            raise _MalformedPage("netPosition is not finite")
        rows.append(PositionRow(slug, net, expired))
    return rows


async def _pull_pages(
    client: _GetAuthenticated,
    *,
    request_timeout_s: float,
    deadline_at: float,
    max_pages: int,
) -> tuple[list[PositionRow], int, bool]:
    """Page to ``eof`` or to the cap. Returns ``(rows, pages, complete)``; raises on any failure."""
    loop = asyncio.get_running_loop()
    rows: list[PositionRow] = []
    cursor: str | None = None
    pages = 0
    for _ in range(max_pages):
        remaining = deadline_at - loop.time()
        if remaining <= 0:
            raise TimeoutError("read deadline expired")
        query: dict[str, object] | None = {_CURSOR_QUERY_KEY: cursor} if cursor else None
        page = await asyncio.wait_for(
            client.get_authenticated(
                validate_endpoint(POSITIONS_LITERAL), query=query, quota_key=QUOTA_KEY_PORTFOLIO
            ),
            timeout=min(request_timeout_s, remaining),
        )
        pages += 1
        rows.extend(_parse_page(page))
        next_cursor = page.get("nextCursor")
        if page.get("eof") is True:
            return rows, pages, True
        if not isinstance(next_cursor, str) or not next_cursor:
            return rows, pages, False
        cursor = next_cursor
    return rows, pages, False


async def read_venue_positions(
    client: _GetAuthenticated,
    *,
    deadline_s: float,
    request_timeout_s: float = VENUE_READ_REQUEST_TIMEOUT_S,
    max_pages: int = MAX_PAGES,
    now_ns: Callable[[], int] = time.time_ns,
) -> VenuePositionsRead:
    """Read every positions page under the overall ``deadline_s``; never raises on a read failure.

    ``snapshot_ns`` is stamped once the read has ended, so a fill that lands while the pages are
    being read falls inside the caller's grace window rather than before it.
    """
    deadline_at = asyncio.get_running_loop().time() + deadline_s
    try:
        rows, pages, complete = await _pull_pages(
            client,
            request_timeout_s=request_timeout_s,
            deadline_at=deadline_at,
            max_pages=max_pages,
        )
    except VenueRateLimitError:
        return _failed(ReadStatus.QUOTA_REFUSED, now_ns)
    except Exception:  # noqa: BLE001 - every failure is a recorded READ_FAILED, never raised
        return _failed(ReadStatus.READ_FAILED, now_ns)
    return VenuePositionsRead(
        snapshot_ns=now_ns(),
        complete=complete,
        pages=pages,
        read_status=ReadStatus.OK,
        rows=tuple(rows),
    )


def _failed(status: ReadStatus, now_ns: Callable[[], int]) -> VenuePositionsRead:
    return VenuePositionsRead(
        snapshot_ns=now_ns(), complete=False, pages=0, read_status=status, rows=()
    )


def _default_transport(config: Any) -> PolymarketUSReadTransport:
    """The shipped GET-only transport, with the pyo3 client bounded by the request timeout."""
    client = build_shared_http_client(
        timeout_secs=VENUE_READ_REQUEST_TIMEOUT_S,
        default_quota=build_default_quota(config.global_requests_per_second),
        keyed_quotas=build_keyed_quotas(),
        default_headers={"User-Agent": str(config.user_agent)},
        check_proxy_env=proxy_env_check_enabled(),
    )
    return NautilusHttpTransport(client=client)


def build_positions_client(
    env: Mapping[str, str] | None = None,
    *,
    transport: PolymarketUSReadTransport | None = None,
) -> PolymarketUSHttpClient:
    """The credentialed read-only client, built from ``env`` (default: the process environment).

    ``transport`` is a test seam only; production passes none and gets the shipped GET-only
    transport. A missing or unsafe credential raises ``CredentialSourceError``; there is no
    fallback source.
    """
    source = os.environ if env is None else env
    config = config_from_env(source)
    credentials = load_polymarket_us_credentials(PolymarketUSSecretsRefConfig(), env=source)
    signer = Ed25519RequestSigner.for_variant(
        credentials, clock=LiveClock(), variant=config.signing_variant
    )
    return PolymarketUSHttpClient(
        transport=CappedReadTransport(
            transport if transport is not None else _default_transport(config),
            max_bytes=POSITIONS_PAGE_MAX_BYTES,
        ),
        signer=signer,
        api_base_url=str(config.api_base_url),
        gateway_base_url=str(config.gateway_base_url),
        logger=_NullVenueLog(),
    )


class _NullVenueLog:
    """The client's request log goes nowhere: a positions read must leave no venue text behind."""

    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...
