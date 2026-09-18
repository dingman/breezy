"""Paced IEM transport and MOS CSV probe fetch (FC-0a-1).

Shared names (sibling FC-0a-2 will import later for the 1-min ASOS product):
``IEM_HOST``, ``IEM_BASE_URL``, ``IEM_ALLOWED_HOSTS``, ``IEM_MIN_INTERVAL_NS``,
``IemPacer``, ``PacedIemTransport``. MOS-only names stay in this module too.

The budget is charged inside ``_fetch`` before the pacer and before
``super()._fetch``, so the (N+1)th attempt raises without opening a socket.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from collections.abc import Awaitable, Callable
from typing import Final
from urllib.parse import urlencode, urlsplit

from breezy.ingest.http import (
    FetchResult,
    HttpTransport,
    RedirectError,
    _validated_path_identifier,  # internal path-segment validator; not a public HTTP API
)
from breezy.ingest.probe_transport import (
    SETTLEMENT_HOSTS,
    ProbeExchange,
    RequestBudget,
    SettlementHostForbiddenError,
)

__all__ = [
    "IEM_ALLOWED_HOSTS",
    "IEM_BASE_URL",
    "IEM_HOST",
    "IEM_MIN_INTERVAL_NS",
    "IEM_MOS_ACCEPT",
    "IEM_MOS_MODELS",
    "IEM_MOS_PATH",
    "IEM_MOS_PROBE_MAX_BODY_BYTES",
    "IEM_MOS_STATIONS",
    "IemMosProbeTransport",
    "IemPacer",
    "PacedIemTransport",
    "exchange_from_alarm",
    "exchange_from_result",
    "utc_stamp",
]

IEM_HOST: Final[str] = "mesonet.agron.iastate.edu"
IEM_BASE_URL: Final[str] = f"https://{IEM_HOST}"
IEM_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({IEM_HOST})
IEM_MIN_INTERVAL_NS: Final[int] = 1_000_000_000

IEM_MOS_ACCEPT: Final[str] = "text/csv"
IEM_MOS_PROBE_MAX_BODY_BYTES: Final[int] = 32 * 1024 * 1024
IEM_MOS_STATION_ORDER: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KSFO")
IEM_MOS_STATIONS: Final[frozenset[str]] = frozenset(IEM_MOS_STATION_ORDER)
IEM_MOS_MODEL_ORDER: Final[tuple[str, ...]] = ("NBS", "GFS")
IEM_MOS_MODELS: Final[frozenset[str]] = frozenset(IEM_MOS_MODEL_ORDER)
IEM_MOS_PATH: Final[str] = "/cgi-bin/request/mos.py"

_NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000
_STATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")
_STS_ETS_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z\Z")


def utc_stamp(clock: Callable[[], int]) -> str:
    """Reproduce probe_transport._utc_stamp from an injected nanosecond clock."""
    seconds = clock() / _NANOSECONDS_PER_SECOND
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat(timespec="seconds")


def exchange_from_result(
    *,
    label: str,
    url: str,
    result: FetchResult,
    ordinal: int,
    requested_at_utc: str,
) -> ProbeExchange:
    """Classify a fetch. A non-2xx is never ``ok``. ``text`` is always None."""
    body = result.text or ""
    succeeded = 200 <= result.status_code < 300
    outcome = "ok" if succeeded else f"http_{result.status_code}"
    finding = (
        None
        if succeeded
        else (
            f"Server answered HTTP {result.status_code} (non-2xx). The body is "
            "captured as evidence, but it carried no requested datum: this is a "
            "FINDING, and no question may be marked answered from it."
        )
    )
    return ProbeExchange(
        ordinal=ordinal,
        requested_at_utc=requested_at_utc,
        label=label,
        url=url,
        status_code=result.status_code,
        body_bytes=len(body.encode("utf-8")),
        content_type=result.headers.get("content-type", ""),
        outcome=outcome,
        sha256=result.sha256,
        text=None,
        finding=finding,
    )


def exchange_from_alarm(
    *,
    label: str,
    url: str,
    error: BaseException,
    ordinal: int,
    requested_at_utc: str,
) -> ProbeExchange:
    """Record a redirect, oversize, or other transport alarm. ``text`` is None."""
    if isinstance(error, RedirectError):
        outcome = "redirect_not_followed"
        status_code = error.status_code
        finding = (
            f"Server answered {error.status_code} with Location="
            f"{error.location!r}. Redirects are NOT followed: recorded as an "
            "integrity finding, not a fetch step."
        )
    else:
        outcome = f"error:{type(error).__name__}"
        status_code = 0
        finding = f"{type(error).__name__}: {error}"
    return ProbeExchange(
        ordinal=ordinal,
        requested_at_utc=requested_at_utc,
        label=label,
        url=url,
        status_code=status_code,
        body_bytes=0,
        content_type="",
        outcome=outcome,
        sha256=None,
        text=None,
        finding=finding,
    )


class IemPacer:
    """One-second minimum interval between IEM requests, charged inside ``_fetch``."""

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        min_interval_ns: int = IEM_MIN_INTERVAL_NS,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper if sleeper is not None else asyncio.sleep
        self._min_interval_ns = min_interval_ns
        self._last_ns: int | None = None

    async def wait(self) -> None:
        now = self._clock()
        if self._last_ns is not None:
            residual_ns = self._min_interval_ns - (now - self._last_ns)
            if residual_ns > 0:
                await self._sleeper(residual_ns / _NANOSECONDS_PER_SECOND)
        self._last_ns = self._clock()


class PacedIemTransport(HttpTransport):
    """Budgeted, paced, IEM-only view of the hardened transport. No public fetch."""

    def __init__(
        self,
        *,
        budget: RequestBudget,
        pacer: IemPacer,
        user_agent: str,
        clock: Callable[[], int],
        max_body_bytes: int,
        accept: str,
        allowed_hosts: frozenset[str] = IEM_ALLOWED_HOSTS,
        base_url: str = IEM_BASE_URL,
        check_proxy_env: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
    ) -> None:
        forbidden = {host.lower() for host in allowed_hosts} & SETTLEMENT_HOSTS
        base_host = (urlsplit(base_url).hostname or "").lower()
        if base_host in SETTLEMENT_HOSTS:
            forbidden.add(base_host)
        if forbidden:
            raise SettlementHostForbiddenError(
                f"A paced IEM transport may not be aimed at the settlement origin(s) "
                f"{sorted(forbidden)}."
            )
        normalized_hosts = frozenset(host.lower() for host in allowed_hosts)
        origin_ok = base_url.rstrip("/") == IEM_BASE_URL.rstrip("/")
        if normalized_hosts != IEM_ALLOWED_HOSTS or not origin_ok:
            raise ValueError(
                "PacedIemTransport constructs only with IEM_ALLOWED_HOSTS and IEM_BASE_URL."
            )
        super().__init__(
            allowed_hosts=IEM_ALLOWED_HOSTS,
            clock=clock,
            base_url=IEM_BASE_URL,
            max_body_bytes=max_body_bytes,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            user_agent=user_agent,
            accept=accept,
            check_proxy_env=check_proxy_env,
        )
        self._budget = budget
        self._pacer = pacer

    @property
    def budget(self) -> RequestBudget:
        return self._budget

    async def fetch_discovery_list(
        self,
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        raise NotImplementedError(
            "A paced IEM transport has no NWS discovery-list endpoint. This method "
            "is closed so the settlement path cannot be reached from an IEM probe."
        )

    async def fetch_product(self, product_id: str) -> FetchResult:
        raise NotImplementedError(
            "A paced IEM transport has no NWS product endpoint. This method is "
            "closed so the settlement path cannot be reached from an IEM probe."
        )

    async def fetch_station_observations(self, icao: str, *, limit: int) -> FetchResult:
        raise NotImplementedError(
            "A paced IEM transport has no NWS observation endpoint. This method is "
            "closed so the settlement path cannot be reached from an IEM probe."
        )

    async def _fetch(
        self,
        url: str,
        *,
        if_none_match: str | None,
        if_modified_since: str | None,
        allow_not_modified: bool,
    ) -> FetchResult:
        self._budget.consume()
        await self._pacer.wait()
        return await super()._fetch(
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )


class IemMosProbeTransport(PacedIemTransport):
    """IEM MOS CSV fetch on the paced IEM transport. Caller never supplies a URL."""

    def __init__(
        self,
        *,
        budget: RequestBudget,
        pacer: IemPacer,
        user_agent: str,
        clock: Callable[[], int],
        allowed_hosts: frozenset[str] = IEM_ALLOWED_HOSTS,
        base_url: str = IEM_BASE_URL,
        max_body_bytes: int = IEM_MOS_PROBE_MAX_BODY_BYTES,
        accept: str = IEM_MOS_ACCEPT,
        check_proxy_env: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
    ) -> None:
        super().__init__(
            budget=budget,
            pacer=pacer,
            user_agent=user_agent,
            clock=clock,
            max_body_bytes=max_body_bytes,
            accept=accept,
            allowed_hosts=allowed_hosts,
            base_url=base_url,
            check_proxy_env=check_proxy_env,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )

    async def fetch_mos_csv(self, station: str, model: str, sts: str, ets: str) -> FetchResult:
        return await self._fetch(
            self._mos_url(station, model, sts, ets),
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
        )

    def _mos_url(self, station: str, model: str, sts: str, ets: str) -> str:
        encoded_station = _validated_path_identifier(
            station,
            name="station",
            shape="a four-letter upper-case ICAO station id (e.g. `KMDW`), not a URL",
            pattern=_STATION_PATTERN,
        )
        if station not in IEM_MOS_STATIONS:
            raise ValueError(
                "`station` is not in the closed MOS station set; refused rather than sanitised."
            )
        if model not in IEM_MOS_MODELS:
            raise ValueError(
                "`model` is not in the closed MOS model set; refused rather than sanitised."
            )
        for name, value in (("sts", sts), ("ets", ets)):
            if _STS_ETS_PATTERN.match(value) is None:
                raise ValueError(
                    f"`{name}` must be YYYY-MM-DDTHH:MMZ; the supplied value is refused."
                )
        query = urlencode(
            {
                "station": encoded_station,
                "model": model,
                "format": "csv",
                "sts": sts,
                "ets": ets,
            }
        )
        return f"{self._base_url}{IEM_MOS_PATH}?{query}"
