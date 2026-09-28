"""The NBM/NOMADS forecast transport -- the LIVE PRIMARY forecast source.

One path builder on the hardened settlement transport, on the template
``nws_observation_transport.py`` established. :class:`NbmForecastTransport`
**subclasses** :class:`breezy.ingest.http.HttpTransport` and inherits
``_fetch`` UNFORKED: the HTTPS-only host allowlist checked before a socket
opens, the TLS floor, ``follow_redirects=False`` with 3xx as an integrity
alarm, the body cap enforced during streaming, digest-before-decode and the
receipt stamp from the injected clock. It shadows none of them; a test
asserts each by IDENTITY.

It adds exactly one endpoint -- the COLLECTIVE NBS text bulletin::

    /pub/data/nccf/com/blend/prod/blend.{YYYYMMDD}/{HH}/text/blend_nbstx.t{HH}z

verified live on 2026-09-19 as the only NBS text product this origin serves.
Every per-station URL shape was REFUTED the same day (403/404, and absent
from the directory listing NOMADS actually served), so the caller supplies a
CYCLE -- a ``datetime.date`` and an ``int`` hour -- and never a URL.

It **closes** the three inherited settlement/observation methods with
``NotImplementedError``, so the settlement path cannot be reached from the
forecast poller (L-22). The allowlist is a distinct, named constant: this
transport can never be pointed at ``api.weather.gov`` or anywhere else.

Body cap: the largest collective bulletin measured 29,720,949 bytes
(~28.35 MiB) on 2026-09-19 -- the 00Z and 12Z cycles; 06Z measured
29,611,149. 48 MiB is 1.69x that, which leaves room for a bulletin that grows
as NBM gains stations without weakening the cap as a control. The exact
measurement is pinned as `MEASURED_MAX_BULLETIN_BYTES` and the ratio is
asserted in both directions by a test.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Final

from breezy.ingest.http import FetchResult, HttpTransport

__all__ = [
    "DEFAULT_NBM_MAX_BODY_BYTES",
    "MEASURED_MAX_BULLETIN_BYTES",
    "NBM_ALLOWED_HOSTS",
    "NBM_BASE_URL",
    "NBM_FORECAST_ACCEPT",
    "NBM_HOST",
    "NbmForecastTransport",
]

NBM_HOST: Final[str] = "nomads.ncep.noaa.gov"
NBM_BASE_URL: Final[str] = "https://nomads.ncep.noaa.gov"
NBM_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"nomads.ncep.noaa.gov"})

#: The bulletin is a plain text product.
NBM_FORECAST_ACCEPT: Final[str] = "text/plain"

#: The LARGEST collective bulletin actually measured, from the 2026-09-19
#: capture's own request manifest: 29,720,949 bytes for the 00Z and 12Z
#: cycles (06Z measured 29,611,149). Recorded as a constant so the cap below
#: is pinned to evidence rather than to a remembered "20-28 MB".
MEASURED_MAX_BULLETIN_BYTES: Final[int] = 29_720_949

#: 48 MiB = 1.69x the measured maximum. Bounded on BOTH sides by
#: ``test_the_body_cap_is_pinned_to_the_measured_bulletin_size``: too low and
#: a legitimately larger future bulletin (NBM gains stations over time) is
#: truncated into an `OversizeBodyError`; too high and the cap stops being a
#: control. The parser no longer scales its memory with this number -- it
#: splits only the requested station blocks -- but the cap still bounds what
#: one response may bring into the live trade node.
DEFAULT_NBM_MAX_BODY_BYTES: Final[int] = 48 * 1024 * 1024

_BLEND_ROOT: Final[str] = "/pub/data/nccf/com/blend/prod"


class NbmForecastTransport(HttpTransport):
    """A hardened, GET-only client for the collective NBS text bulletin."""

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        allowed_hosts: frozenset[str] = NBM_ALLOWED_HOSTS,
        base_url: str = NBM_BASE_URL,
        max_body_bytes: int = DEFAULT_NBM_MAX_BODY_BYTES,
        user_agent: str | None = None,
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
    ) -> None:
        # The allowlist is NOT a caller knob. A transport that can be aimed
        # anywhere is a transport whose containment lives in review notes
        # rather than in code; `base_url` stays retargetable so tests can
        # exercise the inherited host check, which then refuses.
        if frozenset(host.lower() for host in allowed_hosts) != NBM_ALLOWED_HOSTS:
            raise ValueError(
                "NbmForecastTransport constructs only with NBM_ALLOWED_HOSTS; a "
                f"forecast transport may not be allowlisted to {sorted(allowed_hosts)}"
            )
        super().__init__(
            allowed_hosts=NBM_ALLOWED_HOSTS,
            clock=clock,
            base_url=base_url,
            max_body_bytes=max_body_bytes,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            user_agent=user_agent,
            accept=NBM_FORECAST_ACCEPT,
            check_proxy_env=check_proxy_env,
            approved_proxy_env_vars=approved_proxy_env_vars,
        )

    # -- the closed inherited surface ---------------------------------------

    async def fetch_discovery_list(
        self,
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        """Closed. The forecast transport has no NWS discovery endpoint."""
        raise NotImplementedError(
            "NbmForecastTransport has no NWS discovery-list endpoint. This method "
            "is closed so the settlement path cannot be reached from the forecast "
            "poller."
        )

    async def fetch_product(self, product_id: str) -> FetchResult:
        """Closed, for the same reason as :meth:`fetch_discovery_list`."""
        raise NotImplementedError(
            "NbmForecastTransport has no NWS product endpoint. This method is "
            "closed so the settlement path cannot be reached from the forecast "
            "poller."
        )

    async def fetch_station_observations(self, icao: str, *, limit: int) -> FetchResult:
        """Closed. Observations are the NWS observation transport's endpoint."""
        raise NotImplementedError(
            "NbmForecastTransport has no observation endpoint. This method is "
            "closed so the observation path cannot be reached from the forecast "
            "poller."
        )

    # -- the forecast surface -----------------------------------------------

    async def fetch_nbs_bulletin(self, *, cycle_date: dt.date, cycle_hour: int) -> FetchResult:
        """Fetch the collective NBS text bulletin for ONE model cycle.

        Both arguments are validated before a socket opens and the URL is
        built here from validated parts; a caller never supplies a URL and so
        can never retarget the request.

        No conditional-GET validators are sent: a cycle's bulletin is
        immutable by id, so a 304 here would be unsolicited and the inherited
        ``_raise_for_status`` already treats it as an integrity alarm.
        """
        return await self._fetch(
            self._bulletin_url(cycle_date, cycle_hour),
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
        )

    def _bulletin_url(self, cycle_date: dt.date, cycle_hour: int) -> str:
        if not isinstance(cycle_date, dt.date) or isinstance(cycle_date, dt.datetime):
            raise TypeError(
                f"`cycle_date` must be a `datetime.date`, was {type(cycle_date).__name__}; "
                "a string would let a caller place arbitrary text in the path"
            )
        if isinstance(cycle_hour, bool) or not isinstance(cycle_hour, int):
            raise TypeError(f"`cycle_hour` must be an int, was {type(cycle_hour).__name__}")
        if not 0 <= cycle_hour <= 23:
            raise ValueError(f"`cycle_hour` must be in 0..23, was {cycle_hour}")
        day = f"{cycle_date:%Y%m%d}"
        hour = f"{cycle_hour:02d}"
        return f"{self._base_url}{_BLEND_ROOT}/blend.{day}/{hour}/text/blend_nbstx.t{hour}z"
