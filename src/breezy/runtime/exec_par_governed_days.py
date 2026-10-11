"""EXEC-PAR BG-5c WP-C (R1): the one climate-day convention for every K>1 attribution path.

An entry belongs to the climate day of its ARM time under its OWN station's local STANDARD
time (``domain.climate_day``; never the DST wall clock, never a UTC date). Stations roll over
at different instants (standard-time midnight is 05:00Z for UTC-5 and 08:00Z for UTC-8), so
there is no single "the day":

* :meth:`GovernedDays.entry_day` ``(station, arm_ns)``: the day an entry is attributed to.
* :meth:`GovernedDays.open_days_at` ``(ts_ns)``: every governed station's open day at ``ts``.
  Instant-only callers (boot, stage floor, gap spans) use this, because an instant has no
  station.
* :meth:`GovernedDays.today` ``(ts_ns)`` = ``min(open_days_at(ts_ns))``: a label is CLOSED only
  when every governed station is past it.

The governed station set and each station's standard-time offset are INJECTED
(``governed_days_for``); nothing here names a station or a number. The wiring (BG-5c WP-E) builds
the set from the same source as ``app/trade.py`` ``_composable_stations`` / ``_today_by_station``.

Pure: no I/O, no clock, no logging, no Nautilus. Days are ISO ``YYYY-MM-DD`` strings, which sort
chronologically, so ``min`` / ``max`` over labels are date order.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from breezy.domain.climate_day import climate_day_for_instant
from breezy.runtime.exec_par_days_port import DayConvention

__all__ = [
    "DayConvention",
    "GovernedDays",
    "GovernedDaysError",
    "UnknownStationError",
    "governed_days_for",
]

_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_NS_PER_US: Final[int] = 1_000
#: Real UTC offsets span -12h..+14h; anything else is a registry or wiring fault.
_MIN_OFFSET_HOURS: Final[float] = -12.0
_MAX_OFFSET_HOURS: Final[float] = 14.0


class GovernedDaysError(ValueError):
    """The convention was built or called with an invalid input (fail closed)."""


class UnknownStationError(GovernedDaysError):
    """A station outside the injected governed set."""


def _instant(ns: object) -> dt.datetime:
    if isinstance(ns, bool) or not isinstance(ns, int) or ns <= 0:
        raise GovernedDaysError("timestamp must be a positive int of nanoseconds")
    return _EPOCH + dt.timedelta(microseconds=ns // _NS_PER_US)


@dataclass(frozen=True, slots=True)
class GovernedDays:
    """Per-station standard-time climate days over an injected station set.

    ``std_offsets`` maps each governed station to its STANDARD (winter) UTC offset in hours.
    Build it with :func:`governed_days_for`.
    """

    std_offsets: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.std_offsets:
            raise GovernedDaysError("the governed station set is empty")
        for station, offset in self.std_offsets.items():
            if not isinstance(station, str) or not station:
                raise GovernedDaysError("station must be a non-empty string")
            if (
                isinstance(offset, bool)
                or not isinstance(offset, int | float)
                or not math.isfinite(offset)
                or not _MIN_OFFSET_HOURS <= offset <= _MAX_OFFSET_HOURS
            ):
                raise GovernedDaysError("standard-time offset is not a plausible UTC offset")
        object.__setattr__(self, "std_offsets", MappingProxyType(dict(self.std_offsets)))

    @property
    def stations(self) -> tuple[str, ...]:
        return tuple(self.std_offsets)

    def entry_day(self, station: str, arm_ns: int) -> str:
        """The climate day of ``arm_ns`` under ``station``'s standard time."""
        offset = self.std_offsets.get(station)
        if offset is None:
            raise UnknownStationError("station is not in the governed set")
        return climate_day_for_instant(_instant(arm_ns), offset).isoformat()

    def open_days_at(self, ts_ns: int) -> frozenset[str]:
        """Every governed station's open climate day at ``ts_ns``."""
        instant = _instant(ts_ns)
        return frozenset(
            climate_day_for_instant(instant, offset).isoformat()
            for offset in self.std_offsets.values()
        )

    def today(self, ts_ns: int) -> str:
        """The earliest still-open day: later labels may be open for ahead stations."""
        return min(self.open_days_at(ts_ns))


def governed_days_for(
    stations: Sequence[str], std_offset_of: Callable[[str], float]
) -> GovernedDays:
    """Build the convention for ``stations`` (a duplicate is a wiring fault, not deduplicated)."""
    ordered = tuple(stations)
    if len(set(ordered)) != len(ordered):
        raise GovernedDaysError("duplicate station in the governed set")
    return GovernedDays({station: std_offset_of(station) for station in ordered})
