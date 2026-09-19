"""The IEM MOS FALLBACK forecast transport -- backfill only, never the live primary.

IEM's MOS archive lags roughly 40 hours and publishes whole degrees
Fahrenheit. That makes it a sound BACKFILL and FALLBACK source for building a
calibration sample, and an unsound live one. NBM direct
(:mod:`breezy.ingest.nbm_forecast_transport`) is the live PRIMARY; the live
forecast Actor does not import this module, and a test asserts that.

Containment, on the template ``nws_observation_transport.py`` established:

* it **subclasses** :class:`breezy.ingest.http.HttpTransport` and inherits
  ``_fetch`` UNFORKED -- allowlist, TLS floor, ``follow_redirects=False``,
  streaming body cap, digest-before-decode, receipt stamp;
* :class:`IemMosPacer` enforces a >= 1 s minimum interval between requests,
  charged INSIDE ``_fetch`` rather than by the caller, so no call site can
  bypass the politeness contract (the shape
  ``scripts/venue/iem_mos_probe_transport.py`` proved out live);
* its ``allowed_hosts`` is its OWN named constant, distinct from the
  settlement allowlist. The host is a plain literal -- never assembled, never
  hidden behind a ``noqa`` -- so an audit that greps for it finds it;
* the three inherited settlement/observation endpoints are CLOSED, so the
  settlement path is unreachable from a forecast backfill (L-22).

This module is NOT a probe: probes write evidence under an
EVIDENCE-ONLY-NEVER-INGEST boundary, whereas this is a production ingest
transport whose output is parsed into records.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Final
from urllib.parse import urlencode

from breezy.ingest.http import FetchResult, HttpTransport

__all__ = [
    "DEFAULT_IEM_MOS_MAX_BODY_BYTES",
    "IEM_MOS_ALLOWED_HOSTS",
    "IEM_MOS_BASE_URL",
    "IEM_MOS_HOST",
    "IEM_MOS_IS_LIVE_PRIMARY",
    "IEM_MOS_MIN_INTERVAL_NS",
    "IEM_MOS_MODELS",
    "IEM_MOS_STATIONS",
    "IemMosFallbackTransport",
    "IemMosPacer",
]

IEM_MOS_HOST: Final[str] = "mesonet.agron.iastate.edu"
IEM_MOS_BASE_URL: Final[str] = "https://mesonet.agron.iastate.edu"
IEM_MOS_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"mesonet.agron.iastate.edu"})

#: Stated as a constant so the role is assertable, not merely documented.
IEM_MOS_IS_LIVE_PRIMARY: Final[bool] = False

#: One second, minimum, between requests to this origin.
IEM_MOS_MIN_INTERVAL_NS: Final[int] = 1_000_000_000

#: A MOS CSV year-cell measured well under 8 MiB in the 2026-09-19 census.
DEFAULT_IEM_MOS_MAX_BODY_BYTES: Final[int] = 16 * 1024 * 1024

IEM_MOS_ACCEPT: Final[str] = "text/csv"
IEM_MOS_PATH: Final[str] = "/cgi-bin/request/mos.py"

#: Closed alphabets: an out-of-set argument is REFUSED, never sanitised.
IEM_MOS_STATIONS: Final[frozenset[str]] = frozenset({"KLAX", "KMDW", "KMIA", "KSFO"})
IEM_MOS_MODELS: Final[frozenset[str]] = frozenset({"NBS", "GFS"})

_NS_PER_SECOND: Final[int] = 1_000_000_000
_STAMP_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z\Z")


class IemMosPacer:
    """A NAMED >= 1 s minimum interval between IEM requests.

    The clock is injected -- the Actor's own Nautilus clock in production --
    so there is no second clock and the spacing is assertable under test.

    **The wiring seam MUST pass ONE shared instance to every transport that
    talks to this origin.** The interval is tracked per PACER, not per host,
    so two transports each holding their own pacer would politely emit 2
    req/s at the origin while each believed it was emitting 1. Nothing
    references this module today, which is what contains the hazard now; the
    slice that first constructs a second transport is the one that must
    thread the existing pacer through rather than build another.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        min_interval_ns: int = IEM_MOS_MIN_INTERVAL_NS,
    ) -> None:
        if min_interval_ns < IEM_MOS_MIN_INTERVAL_NS:
            raise ValueError(
                f"`min_interval_ns` must be at least {IEM_MOS_MIN_INTERVAL_NS} ns; "
                f"{min_interval_ns} would be a relaxation of the politeness contract"
            )
        self._clock = clock
        self._sleeper = asyncio.sleep if sleeper is None else sleeper
        self._min_interval_ns = min_interval_ns
        self._last_ns: int | None = None

    async def wait(self) -> None:
        """Sleep the residual, if any, then record this request's instant."""
        now = self._clock()
        if self._last_ns is not None:
            residual_ns = self._min_interval_ns - (now - self._last_ns)
            if residual_ns > 0:
                await self._sleeper(residual_ns / _NS_PER_SECOND)
        self._last_ns = self._clock()


class IemMosFallbackTransport(HttpTransport):
    """A hardened, paced, GET-only client for the IEM MOS CSV endpoint."""

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        pacer: IemMosPacer,
        allowed_hosts: frozenset[str] = IEM_MOS_ALLOWED_HOSTS,
        base_url: str = IEM_MOS_BASE_URL,
        max_body_bytes: int = DEFAULT_IEM_MOS_MAX_BODY_BYTES,
        user_agent: str | None = None,
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
    ) -> None:
        if frozenset(host.lower() for host in allowed_hosts) != IEM_MOS_ALLOWED_HOSTS:
            raise ValueError(
                "IemMosFallbackTransport constructs only with IEM_MOS_ALLOWED_HOSTS; a "
                f"fallback transport may not be allowlisted to {sorted(allowed_hosts)}"
            )
        super().__init__(
            allowed_hosts=IEM_MOS_ALLOWED_HOSTS,
            clock=clock,
            base_url=base_url,
            max_body_bytes=max_body_bytes,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            user_agent=user_agent,
            accept=IEM_MOS_ACCEPT,
            check_proxy_env=check_proxy_env,
            approved_proxy_env_vars=approved_proxy_env_vars,
        )
        self._pacer = pacer

    # -- the closed inherited surface ---------------------------------------

    async def fetch_discovery_list(
        self,
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        """Closed. A forecast backfill has no NWS discovery endpoint."""
        raise NotImplementedError(
            "IemMosFallbackTransport has no NWS discovery-list endpoint. This "
            "method is closed so the settlement path cannot be reached from a "
            "forecast backfill."
        )

    async def fetch_product(self, product_id: str) -> FetchResult:
        """Closed, for the same reason as :meth:`fetch_discovery_list`."""
        raise NotImplementedError(
            "IemMosFallbackTransport has no NWS product endpoint. This method is "
            "closed so the settlement path cannot be reached from a forecast "
            "backfill."
        )

    async def fetch_station_observations(self, icao: str, *, limit: int) -> FetchResult:
        """Closed. Observations are the NWS observation transport's endpoint."""
        raise NotImplementedError(
            "IemMosFallbackTransport has no observation endpoint. This method is "
            "closed so the observation path cannot be reached from a forecast "
            "backfill."
        )

    # -- the backfill surface -----------------------------------------------

    async def fetch_mos_csv(self, *, station: str, model: str, sts: str, ets: str) -> FetchResult:
        """Fetch one MOS CSV window. Every argument is validated before dispatch."""
        return await self._fetch(
            self._mos_url(station, model, sts, ets),
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
        """Charge the pacer, then the inherited hardened implementation.

        Overridden ONLY to add pacing; every control the base applies is
        reached by ``super()`` and none is reimplemented here.
        """
        await self._pacer.wait()
        return await super()._fetch(
            url,
            if_none_match=if_none_match,
            if_modified_since=if_modified_since,
            allow_not_modified=allow_not_modified,
        )

    def _mos_url(self, station: str, model: str, sts: str, ets: str) -> str:
        if station not in IEM_MOS_STATIONS:
            raise ValueError(
                f"`station` {station!r} is not in the closed MOS station set; "
                "refused rather than sanitised"
            )
        if model not in IEM_MOS_MODELS:
            raise ValueError(
                f"`model` {model!r} is not in the closed MOS model set; refused "
                "rather than sanitised"
            )
        for name, value in (("sts", sts), ("ets", ets)):
            if not isinstance(value, str) or _STAMP_PATTERN.match(value) is None:
                raise ValueError(
                    f"`{name}` must be YYYY-MM-DDTHH:MMZ; {value!r} is refused"
                )
        query = urlencode(
            {"station": station, "model": model, "format": "csv", "sts": sts, "ets": ets}
        )
        return f"{self._base_url}{IEM_MOS_PATH}?{query}"
