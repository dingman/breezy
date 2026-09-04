"""Pure helpers for the observation Actor's restart rebuild (BL-24 amendment A8).

No I/O, no clock access, no `nautilus_trader` import: the Actor supplies
every instant and this module answers with integers. Split out of
:mod:`breezy.ingest.nws_observation_actor` so the trust decision -- the part
that decides whether a station publishes at all after a restart -- is
testable without a message bus.

Integer arithmetic only (amendment A7): nanoseconds are never divided into a
float, and a local-standard midnight is a modulus over the day length.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from breezy.ingest.nws_observations import largest_gap_ns

__all__ = [
    "MAX_OBSERVATION_LIMIT",
    "NOMINAL_CADENCE_SECONDS",
    "REBUILD_ROW_MARGIN",
    "local_standard_midnight_ns",
    "observation_fetch_limit",
    "rebuild_is_trusted",
]

#: The API's documented ceiling for `?limit=`; also the cap on a rebuild.
#: Measured 2026-09-04 (`tests/fixtures/nws/kmdw_observations_2026-09-04.json`):
#: 500 KMDW rows reach back ~38 h, so one call covers a climate day.
MAX_OBSERVATION_LIMIT: Final[int] = 500

#: The 5-minute ASOS cadence the limit formula is sized on.
NOMINAL_CADENCE_SECONDS: Final[int] = 300

#: Rows requested beyond the nominal count, absorbing hourly METARs and
#: specials (brief section 3: `ceil(elapsed / 300) + 24`).
REBUILD_ROW_MARGIN: Final[int] = 24

_NS_PER_SECOND: Final[int] = 1_000_000_000
_DAY_NS: Final[int] = 86_400 * _NS_PER_SECOND


def observation_fetch_limit(elapsed_seconds: int) -> int:
    """`min(500, ceil(elapsed / 300) + 24)` -- the brief's bounded fetch size."""
    if elapsed_seconds < 0:
        raise ValueError(f"`elapsed_seconds` must be non-negative, was {elapsed_seconds}")
    nominal_rows = -(-elapsed_seconds // NOMINAL_CADENCE_SECONDS)  # ceil, integers only
    return min(MAX_OBSERVATION_LIMIT, nominal_rows + REBUILD_ROW_MARGIN)


def local_standard_midnight_ns(now_ns: int, std_utc_offset_hours: float) -> int:
    """UNIX ns of the local-STANDARD-time midnight starting the climate day of `now_ns`.

    Never DST-aware: the offset is the site's fixed standard offset from the
    registry (`ClimateDayWindow.std_utc_offset_hours`), exactly as
    `breezy.domain.climate_day.climate_day_for_instant` uses it.
    """
    offset_ns = round(std_utc_offset_hours * 3_600) * _NS_PER_SECOND
    local_ns = now_ns + offset_ns
    local_midnight_ns = local_ns - (local_ns % _DAY_NS)
    return local_midnight_ns - offset_ns


def rebuild_is_trusted(
    *,
    sorted_observed_ns: Sequence[int],
    midnight_ns: int,
    staleness_bound_ns: int,
) -> bool:
    """A8's trust test: covers from midnight, and no gap over the staleness bound.

    Trusted iff the oldest row is no later than `midnight + bound` AND the
    largest gap between consecutive rows from `midnight - bound` onward is
    at most `bound`. An empty response is never trusted. Rows older than
    the lead-in are ignored for the gap test: they belong to a climate day
    the accumulator will never hold.
    """
    if not sorted_observed_ns:
        return False
    if sorted_observed_ns[0] > midnight_ns + staleness_bound_ns:
        return False
    lead_in_ns = midnight_ns - staleness_bound_ns
    relevant = [instant for instant in sorted_observed_ns if instant >= lead_in_ns]
    gap = largest_gap_ns(relevant)
    return gap is None or gap <= staleness_bound_ns
