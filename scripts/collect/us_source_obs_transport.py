"""F13 C1-R1: the C1-owned mirror of the live observation request (GET only).

The live observation ingest (``breezy.ingest.nws_observation_transport.NwsObservationTransport``)
sits in the M6 baseline, which by design never overlaps the C1 import closure, so the collector
cannot import it. This class issues the SAME request on the same hardened ``HttpTransport``:
``GET https://api.weather.gov/stations/{ICAO}/observations?limit=N`` with
``Accept: application/geo+json``, a 4 MiB body cap, and the settlement endpoints closed. A test
(``tests/unit/test_us_source_lag_legs.py``) pins URL, Accept and cap parity against the live class.
The station set is the closed C1 set; a registry import would pull baseline modules in.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from breezy.ingest.http import (
    DEFAULT_BASE_URL,
    FetchResult,
    HttpTransport,
    _validated_path_identifier,
)
from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS

__all__ = ["OBS_ACCEPT", "OBS_MAX_BODY_BYTES", "OBS_STATIONS", "ObsTransport"]

OBS_ACCEPT: Final[str] = "application/geo+json"
OBS_MAX_BODY_BYTES: Final[int] = 4 * 1024 * 1024
OBS_MAX_LIMIT: Final[int] = 500
OBS_STATIONS: Final[frozenset[str]] = frozenset({"KLAX", "KMDW", "KMIA", "KNYC", "KSFO"})
_ICAO_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")


class ObsTransport(HttpTransport):
    """Closed, GET-only client for ``/stations/{icao}/observations`` on the five C1 stations."""

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        user_agent: str,
        check_proxy_env: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
    ) -> None:
        super().__init__(
            allowed_hosts=DEFAULT_ALLOWED_HOSTS,
            clock=clock,
            base_url=DEFAULT_BASE_URL,
            max_body_bytes=OBS_MAX_BODY_BYTES,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            user_agent=user_agent,
            accept=OBS_ACCEPT,
            check_proxy_env=check_proxy_env,
        )

    async def fetch_discovery_list(self, *_args: object, **_kwargs: object) -> FetchResult:
        raise NotImplementedError("closed: the observation poller has no settlement endpoint")

    async def fetch_product(self, *_args: object, **_kwargs: object) -> FetchResult:
        raise NotImplementedError("closed: the observation poller has no settlement endpoint")

    def station_observations_url(self, icao: str, limit: int) -> str:
        segment = _validated_path_identifier(
            icao,
            name="icao",
            shape="a four-letter upper-case ICAO station id",
            pattern=_ICAO_PATTERN,
        )
        if icao not in OBS_STATIONS:
            raise ValueError(f"ICAO {icao!r} is not a C1 station")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= OBS_MAX_LIMIT:
            raise ValueError(f"`limit` must be an int in 1..{OBS_MAX_LIMIT}, was {limit!r}")
        return f"{self._base_url}/stations/{segment}/observations?limit={int(limit)}"

    async def fetch_station_observations(self, icao: str, *, limit: int) -> FetchResult:
        return await self._fetch(
            self.station_observations_url(icao, limit),
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
        )
