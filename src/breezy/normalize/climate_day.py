"""Map an instant to its climate day.

Re-exports `breezy.domain.climate_day` unchanged, and is the pure home of
`local_standard_date` (`breezy.ingest.gaps` re-exports it; that package's eager import is not
pure). The implementation lives
in `domain` (the bottom layer) because `breezy.domain.station_observation`
needs it and the layer contract in `pyproject.toml` forbids
`domain -> normalize`; `normalize` sits above `domain` in that stack, so the
re-export here keeps every pre-existing `breezy.normalize.climate_day`
caller working with no import-path change.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

from breezy.domain.climate_day import (
    ClimateDayError,
    climate_day_for_instant,
    standard_time_zone,
)

__all__ = [
    "ClimateDayError",
    "climate_day_for_instant",
    "local_standard_date",
    "standard_time_zone",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000


def local_standard_date(now_ns: int, std_utc_offset_hours: float) -> dt.date:
    """The calendar date `now_ns` falls on in fixed local-standard time.

    Never DST-aware -- see the module docstring's two-clocks note. Matches
    ``NwsIngestActor._most_recent_completed_climate_day``'s own conversion
    byte-for-byte (floor division on whole seconds, not float division), so
    this and that function agree on every instant, including ones exactly on
    a second boundary.
    """
    local = dt.datetime.fromtimestamp(
        now_ns // _NS_PER_SECOND,
        tz=standard_time_zone(std_utc_offset_hours),
    )
    return local.date()
