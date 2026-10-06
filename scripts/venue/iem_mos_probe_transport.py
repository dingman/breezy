"""Paced IEM transport and MOS CSV probe fetch (FC-0a-1).

Shared names (sibling FC-0a-2 will import later for the 1-min ASOS product):
``IEM_HOST``, ``IEM_BASE_URL``, ``IEM_ALLOWED_HOSTS``, ``IEM_MIN_INTERVAL_NS``,
``IemPacer``, ``PacedIemTransport``. MOS-only names stay in this module too.

The budget is charged inside ``_fetch`` before the pacer and before
``super()._fetch``, so the (N+1)th attempt raises without opening a socket.
"""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import re
from collections.abc import Awaitable, Callable
from typing import Final
from urllib.parse import urlencode, urlsplit

from breezy.ingest.http import (
    FetchResult,
    HttpTransport,
    RateLimitedError,
    RedirectError,
    _validated_path_identifier,  # internal path-segment validator; not a public HTTP API
    redact_url,
)
from breezy.ingest.probe_transport import (
    SETTLEMENT_HOSTS,
    ProbeExchange,
    RequestBudget,
    SettlementHostForbiddenError,
)

__all__ = [
    "IEM_AFOS_LAV_MIN_INTERVAL_NS",
    "IEM_AFOS_LIST_MAX_BODY_BYTES",
    "IEM_AFOS_LIST_PATH",
    "IEM_AFOS_PFM_MAX_BODY_BYTES",
    "IEM_AFOS_RETRIEVE_PATH",
    "IEM_AFOS_WFOS",
    "IEM_ALLOWED_HOSTS",
    "IEM_BASE_URL",
    "IEM_HOST",
    "IEM_LAV_MAX_BODY_BYTES",
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
#: The closed MOS/LAV station SET. KNYC is widened in here only (F13-R33);
#: `IEM_MOS_STATION_ORDER` stays the four-station default so the nightly
#: backfill is unchanged, and KNYC runs only when named explicitly.
IEM_MOS_STATIONS: Final[frozenset[str]] = frozenset({*IEM_MOS_STATION_ORDER, "KNYC"})
IEM_MOS_MODEL_ORDER: Final[tuple[str, ...]] = ("NBS", "GFS")
IEM_MOS_MODELS: Final[frozenset[str]] = frozenset(IEM_MOS_MODEL_ORDER)
IEM_MOS_PATH: Final[str] = "/cgi-bin/request/mos.py"
IEM_AFOS_RETRIEVE_PATH: Final[str] = "/cgi-bin/afos/retrieve.py"
IEM_AFOS_LIST_PATH: Final[str] = "/api/1/nws/afos/list.json"
IEM_LAV_MODEL: Final[str] = "LAV"

#: PFM issuing offices for the five stations (A0-R2): OKX, LOX, LOT, MTR, MFL.
IEM_AFOS_WFOS: Final[frozenset[str]] = frozenset({"OKX", "LOX", "LOT", "MTR", "MFL"})
IEM_AFOS_PILS: Final[frozenset[str]] = frozenset(f"PFM{wfo}" for wfo in IEM_AFOS_WFOS)
IEM_AFOS_MAX_LIMIT: Final[int] = 50

#: A0-R1: IEM throttled at ~1.2 s between requests; 3-4 s was clean. Applies to
#: the AFOS and LAV methods only -- `IEM_MIN_INTERVAL_NS` is unchanged.
IEM_AFOS_LAV_MIN_INTERVAL_NS: Final[int] = 4_000_000_000

#: Per-method body caps (F13 R21), each well under the MOS probe cap.
IEM_AFOS_PFM_MAX_BODY_BYTES: Final[int] = 2 * 1024 * 1024
IEM_AFOS_LIST_MAX_BODY_BYTES: Final[int] = 1024 * 1024
IEM_LAV_MAX_BODY_BYTES: Final[int] = 16 * 1024 * 1024

#: IEM's throttle answer (A0 probe). It is NOT data, whatever the status code.
IEM_THROTTLE_BODY_MARKER: Final[str] = "Too many requests from your IP address"
_THROTTLE_SCAN_CHARS: Final[int] = 512

_NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000
_STATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")
_STS_ETS_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z\Z")


def _closed_station(station: str) -> str:
    encoded = _validated_path_identifier(
        station,
        name="station",
        shape="a four-letter upper-case ICAO station id (e.g. `KMDW`), not a URL",
        pattern=_STATION_PATTERN,
    )
    if station not in IEM_MOS_STATIONS:
        raise ValueError(
            "`station` is not in the closed MOS station set; refused rather than sanitised."
        )
    return encoded


def _closed_window(sts: str, ets: str) -> None:
    for name, value in (("sts", sts), ("ets", ets)):
        if _STS_ETS_PATTERN.match(value) is None:
            raise ValueError(f"`{name}` must be YYYY-MM-DDTHH:MMZ; the supplied value is refused.")


def _closed_date(name: str, value: dt.date) -> str:
    if not isinstance(value, dt.date) or isinstance(value, dt.datetime):
        raise TypeError(f"`{name}` must be a `datetime.date`, was {type(value).__name__}")
    return value.isoformat()


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
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def _slot_lock(self) -> asyncio.Lock:
        # Created lazily, and rebuilt if the pacer is reused from another event
        # loop (the backfill drives it from one runner, tests from several).
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def wait(self, min_interval_ns: int | None = None) -> None:
        """Reserve the next request slot atomically, then sleep until it.

        Under the lock the slot is ``max(now, last + interval)`` and is
        recorded as ``last`` BEFORE any sleep, so concurrent callers each get a
        distinct slot at least one interval apart -- including at first use.
        The interval is the larger of the pacer's own and ``min_interval_ns``
        (a per-method floor).
        """
        async with self._slot_lock():
            now = self._clock()
            interval_ns = max(self._min_interval_ns, min_interval_ns or 0)
            slot = now if self._last_ns is None else max(now, self._last_ns + interval_ns)
            self._last_ns = slot
        delay_ns = slot - now
        if delay_ns > 0:
            await self._sleeper(delay_ns / _NANOSECONDS_PER_SECOND)


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
        min_interval_ns: int | None = None,
    ) -> FetchResult:
        self._budget.consume()
        if min_interval_ns is None:
            await self._pacer.wait()
        else:
            await self._pacer.wait(min_interval_ns)
        return await super()._fetch(
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )

    # -- AFOS (PFM) and LAV: closed sets, per-method caps, A0-R1 pacing -------

    async def fetch_afos_pfm(
        self, wfo: str, *, sdate: dt.date | None = None, limit: int = 1
    ) -> FetchResult:
        """The latest PFM (``sdate=None``) or ascending history from ``sdate``."""
        if wfo not in IEM_AFOS_WFOS:
            raise ValueError("`wfo` is not in the closed PFM office set; refused.")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("`limit` must be an int")
        if not 1 <= limit <= IEM_AFOS_MAX_LIMIT:
            raise ValueError(f"`limit` must be in 1..{IEM_AFOS_MAX_LIMIT}")
        params = {"pil": f"PFM{wfo}", "limit": str(limit)}
        if sdate is not None:
            params["sdate"] = _closed_date("sdate", sdate)
            params["order"] = "asc"
        params["fmt"] = "text"
        return await self._fetch_closed(
            f"{self._base_url}{IEM_AFOS_RETRIEVE_PATH}?{urlencode(params)}",
            cap=IEM_AFOS_PFM_MAX_BODY_BYTES,
            accept="text/plain",
        )

    async def fetch_afos_list(self, pil: str, date: dt.date) -> FetchResult:
        """The day's issuance list for one closed-set PFM product."""
        if pil not in IEM_AFOS_PILS:
            raise ValueError("`pil` is not in the closed PFM product set; refused.")
        query = urlencode({"pil": pil, "date": _closed_date("date", date)})
        return await self._fetch_closed(
            f"{self._base_url}{IEM_AFOS_LIST_PATH}?{query}",
            cap=IEM_AFOS_LIST_MAX_BODY_BYTES,
            accept="application/json",
        )

    async def fetch_lav(self, station: str, sts: str, ets: str) -> FetchResult:
        """GFS LAMP (LAV) CSV. Never goes through the MOS model set."""
        encoded = _closed_station(station)
        _closed_window(sts, ets)
        query = urlencode(
            {"station": encoded, "model": IEM_LAV_MODEL, "format": "csv", "sts": sts, "ets": ets}
        )
        return await self._fetch_closed(
            f"{self._base_url}{IEM_MOS_PATH}?{query}",
            cap=IEM_LAV_MAX_BODY_BYTES,
            accept="text/csv",
        )

    async def _fetch_closed(self, url: str, *, cap: int, accept: str) -> FetchResult:
        # A shallow per-call view: it carries this method's cap and Accept
        # without mutating the shared transport, while the budget and pacer
        # (shared by reference) still count and space every request.
        view = copy.copy(self)
        view._max_body_bytes = min(cap, self._max_body_bytes)
        view._accept = accept
        result = await view._fetch(
            url,
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
            min_interval_ns=IEM_AFOS_LAV_MIN_INTERVAL_NS,
        )
        if IEM_THROTTLE_BODY_MARKER in (result.text or "")[:_THROTTLE_SCAN_CHARS]:
            raise RateLimitedError(
                f"{IEM_THROTTLE_BODY_MARKER} (IEM throttle body from "
                f"{redact_url(result.url)}): the response is not data; back off and alert.",
                retry_after=None,
            )
        return result


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
        encoded_station = _closed_station(station)
        if model not in IEM_MOS_MODELS:
            raise ValueError(
                "`model` is not in the closed MOS model set; refused rather than sanitised."
            )
        _closed_window(sts, ets)
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
