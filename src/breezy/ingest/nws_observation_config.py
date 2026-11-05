"""Config, constants and the transport seam for the NWS observation Actor (BL-24 Seam B).

Split from :mod:`breezy.ingest.nws_observation_actor` so that module stays
within the seam's file-size budget; everything here is declarative. Imported
from ``nautilus_trader.common.config`` (typed ``.py``), not from the compiled
``actor`` module, for the reason ``ingest/config.py`` gives.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final, Protocol

from nautilus_trader.common.config import ActorConfig

from breezy.ingest.http import FetchResult
from breezy.ingest.nws_observation_transport import NwsObservationTransport
from breezy.ingest.nws_observations import NWS_OBSERVATION_SOURCE_CHANNEL

__all__ = [
    "DEFAULT_OBSERVATION_POLL_INTERVAL_SECONDS",
    "DEFAULT_STALENESS_BOUND_SECONDS",
    "EXCLUDED_ICAOS",
    "MIN_REQUEST_SPACING_NS",
    "NwsObservationActorConfig",
    "ObservationFetcher",
    "TransportFactory",
    "build_observation_transport",
]

#: Stations the live rule excludes: KNYC has no sub-hourly observations in
#: any public source (`docs/evidence/observation_source_latency_2026-09-04.md`,
#: amendment A14, converged review item 8).
EXCLUDED_ICAOS: Final[frozenset[str]] = frozenset({"KNYC"})

#: S2: never two requests for one station within a second.
MIN_REQUEST_SPACING_NS: Final[int] = 1_000_000_000

#: Amendment A12: cadence >= 92 s per NWS `max-age`; 300 s chosen.
DEFAULT_OBSERVATION_POLL_INTERVAL_SECONDS: Final[int] = 300

#: Spec rev 3 delta (2026-09-04), replacing rev 2 section 5's
#: `stale_observation_hours = 0.75` (2_700 s / 45 min exactly) for
#: LAX/MDW/MIA/SFO. New bound: `max(K_B_REQUIRED_LAGS_LIVE) + 5 min ASOS
#: cadence` = 45 + 5 = 50 min, so the ingest rebuild trust window stays in
#: lockstep with `current_rung_hold.config.STALE_OBSERVATION_MINUTES`.
DEFAULT_STALENESS_BOUND_SECONDS: Final[int] = 3_000

_ICAO_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")


class ObservationFetcher(Protocol):
    """The one transport method the Actor calls."""

    async def fetch_station_observations(self, icao: str, *, limit: int) -> FetchResult: ...


#: Builds the transport ON THE ACTOR'S CLOCK -- called from `on_start` with
#: `self.clock.timestamp_ns`, so a transport on any other clock cannot be
#: wired in by construction (amendment A7, one clock).
TransportFactory = Callable[[Callable[[], int]], ObservationFetcher]


def build_observation_transport(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> NwsObservationTransport:
    """The production `TransportFactory`."""
    return NwsObservationTransport(clock=clock, check_proxy_env=check_proxy_env)


class NwsObservationActorConfig(ActorConfig, frozen=True):
    """Configuration for one observation Actor serving one station.

    Scalar, msgspec-serialisable fields only -- see `NwsIngestActorConfig`.
    `assumed_publication_lag_ns` is provenance stamped on every record and
    never used in any computation (amendment A6); it has no default because
    a measured value must be supplied by the composition root.
    """

    station_icao: str
    assumed_publication_lag_ns: int
    poll_interval_seconds: int = DEFAULT_OBSERVATION_POLL_INTERVAL_SECONDS
    stagger_offset_seconds: int = 0
    staleness_bound_seconds: int = DEFAULT_STALENESS_BOUND_SECONDS
    source_channel: str = NWS_OBSERVATION_SOURCE_CHANNEL

    def __post_init__(self) -> None:
        if _ICAO_PATTERN.match(self.station_icao) is None:
            raise ValueError(
                f"`station_icao` must be a four-letter upper-case ICAO id, was "
                f"{self.station_icao!r}"
            )
        if self.station_icao in EXCLUDED_ICAOS:
            raise ValueError(
                f"`station_icao` {self.station_icao!r} is excluded from the live "
                "observation rule: it is hourly-only in every public source (A14)"
            )
        if self.assumed_publication_lag_ns <= 0:
            raise ValueError("`assumed_publication_lag_ns` must be positive")
        if self.poll_interval_seconds <= 0:
            raise ValueError("`poll_interval_seconds` must be positive")
        if self.staleness_bound_seconds <= 0:
            raise ValueError("`staleness_bound_seconds` must be positive")
        if self.stagger_offset_seconds < 0:
            raise ValueError("`stagger_offset_seconds` must be non-negative")
