"""Map an instant to its climate day.

Re-exports `breezy.domain.climate_day` unchanged. The implementation lives
in `domain` (the bottom layer) because `breezy.domain.station_observation`
needs it and the layer contract in `pyproject.toml` forbids
`domain -> normalize`; `normalize` sits above `domain` in that stack, so the
re-export here keeps every pre-existing `breezy.normalize.climate_day`
caller working with no import-path change.
"""

from __future__ import annotations

from breezy.domain.climate_day import (
    ClimateDayError,
    climate_day_for_instant,
    standard_time_zone,
)

__all__ = [
    "ClimateDayError",
    "climate_day_for_instant",
    "standard_time_zone",
]
