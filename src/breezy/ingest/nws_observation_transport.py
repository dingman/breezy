"""The NWS observation transport: ONE path builder on the hardened settlement transport.

BL-24 Seam B, section 2, on the :class:`breezy.ingest.probe_transport.ProbeTransport`
template. :class:`NwsObservationTransport` **subclasses**
:class:`breezy.ingest.http.HttpTransport` and inherits ``_fetch`` UNFORKED:
the HTTPS-only host allowlist checked before a socket opens, the TLS floor,
``follow_redirects=False`` with 3xx as an integrity alarm, the body cap
enforced during streaming, digest-before-decode, and the receipt stamp from
the injected clock. It shadows none of them -- a test asserts each by
IDENTITY (converged review item 5).

It adds exactly one endpoint, ``GET /stations/{icao}/observations?limit=N``,
whose ``{icao}`` segment must BOTH match ``\\A[A-Z]{4}\\Z`` and be a member
of the registry's closed ICAO set, and whose ``limit`` is an ``int`` in
``1..500`` formatted here -- never a caller string. Conditional-GET
validators are never sent (``allow_not_modified=False``): a 304 on this
endpoint would be an unsolicited one and the inherited ``_raise_for_status``
already treats it as an alarm.

It **closes** both inherited settlement methods (``fetch_discovery_list``,
``fetch_product``) with ``NotImplementedError``, and the settlement transport
never gains ``fetch_station_observations`` -- exclusion is unforgeable, not
offered (L-22). The host is unchanged: ``api.weather.gov`` is already the
only member of ``DEFAULT_ALLOWED_HOSTS``.

The body cap is larger than the settlement default: a 500-row KMDW response
measured 1.93 MB on 2026-09-04 against the settlement transport's 128 KiB.
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
from breezy.registry.sites import default_registry

__all__ = [
    "DEFAULT_OBSERVATION_MAX_BODY_BYTES",
    "MAX_OBSERVATION_LIMIT",
    "OBSERVATION_ACCEPT",
    "InvalidObservationLimitError",
    "NwsObservationTransport",
    "UnregisteredStationError",
]

#: The observations endpoint serves GeoJSON; passed through the inherited,
#: validated `accept=` constructor seam. The header NAME stays transport-owned.
OBSERVATION_ACCEPT: Final[str] = "application/geo+json"

#: The API's documented ceiling for `?limit=`.
MAX_OBSERVATION_LIMIT: Final[int] = 500

#: 4 MiB: ~2x the measured 500-row response, still a hard cap.
DEFAULT_OBSERVATION_MAX_BODY_BYTES: Final[int] = 4 * 1024 * 1024

_ICAO_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")


class UnregisteredStationError(ValueError):
    """The ICAO has the right shape but is not in the registry's closed set."""


class InvalidObservationLimitError(ValueError):
    """`limit` is not an `int` in `1..MAX_OBSERVATION_LIMIT`."""


class NwsObservationTransport(HttpTransport):
    """A hardened, GET-only client for ``/stations/{icao}/observations``.

    Overrides nothing that hardens a request. Closes the two settlement
    endpoints. Adds one.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
        known_icaos: frozenset[str] | None = None,
        base_url: str = DEFAULT_BASE_URL,
        max_body_bytes: int = DEFAULT_OBSERVATION_MAX_BODY_BYTES,
        user_agent: str | None = None,
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
    ) -> None:
        super().__init__(
            allowed_hosts=allowed_hosts,
            clock=clock,
            base_url=base_url,
            max_body_bytes=max_body_bytes,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            user_agent=user_agent,
            accept=OBSERVATION_ACCEPT,
            check_proxy_env=check_proxy_env,
            approved_proxy_env_vars=approved_proxy_env_vars,
        )
        # The registry is the single source of truth for which stations
        # exist (`sites.toml`); a shape regex alone cannot tell KMDW from
        # KORD, and O'Hare is exactly the substitution L-17's neighbour
        # rule forbids.
        self._known_icaos: frozenset[str] = (
            default_registry().known_icaos() if known_icaos is None else frozenset(known_icaos)
        )

    # -- the closed inherited surface --------------------------------------

    async def fetch_discovery_list(
        self,
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        """Closed. The observation transport has no settlement discovery endpoint."""
        raise NotImplementedError(
            "NwsObservationTransport has no NWS discovery-list endpoint. This method "
            "is closed so the settlement path cannot be reached from the observation "
            "poller."
        )

    async def fetch_product(self, product_id: str) -> FetchResult:
        """Closed, for the same reason as :meth:`fetch_discovery_list`."""
        raise NotImplementedError(
            "NwsObservationTransport has no NWS product endpoint. This method is "
            "closed so the settlement path cannot be reached from the observation "
            "poller."
        )

    # -- the observation surface -------------------------------------------

    async def fetch_station_observations(self, icao: str, *, limit: int) -> FetchResult:
        """Fetch the newest `limit` observations for a REGISTERED station.

        Both arguments are validated before a socket opens; the URL is built
        here from validated parts, never supplied by the caller.
        """
        return await self._fetch(
            self._station_observations_url(icao, limit),
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
        )

    def _station_observations_url(self, icao: str, limit: int) -> str:
        segment = _validated_path_identifier(
            icao,
            name="icao",
            shape="a four-letter upper-case ICAO station id (e.g. `KMDW`), not a URL",
            pattern=_ICAO_PATTERN,
        )
        if icao not in self._known_icaos:
            raise UnregisteredStationError(
                f"ICAO {icao!r} is not a registered settlement station; refusing to "
                "fetch observations for a station the registry does not know"
            )
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise InvalidObservationLimitError(
                f"`limit` must be an int, was {type(limit).__name__}"
            )
        if not 1 <= limit <= MAX_OBSERVATION_LIMIT:
            raise InvalidObservationLimitError(
                f"`limit` must be in 1..{MAX_OBSERVATION_LIMIT}, was {limit}"
            )
        return f"{self._base_url}/stations/{segment}/observations?limit={int(limit)}"
