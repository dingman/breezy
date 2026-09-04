"""Online running-maximum accumulator for one station's climate-day `R(t)`.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no global
state -- callers own the clock (see
``docs/plans/BL24_LIVE_RT_2026-09-04.md`` amendment A7, "one clock").

The goal predicate (amendment A1): `R(t) = max{rounded_f of the station's
climate-day observations with measurement <= t and receipt <= t}`. The lag
`L` belongs on the quote a strategy prices against, never on `R` itself --
:meth:`RunningExtremeAccumulator.value_at` therefore takes no `lag`
parameter.

The accumulator (amendment A2) stores every pushed row in a bounded
``dict[int, Row]`` keyed by `observed_at_ns` (~288 rows/day at 5-minute
cadence) and recomputes the day's running max on every read rather than
maintaining an incremental running value. Two consequences follow directly
from that shape, both deliberate:

* Pushing to an `observed_at_ns` that already has a row REPLACES it. A
  corrected reading at the same instant may lower `R` -- this is a genuine
  correction, not an error, and is never rejected or clamped upward.
* A push whose `observed_at_ns` is earlier than the latest already stored is
  simply another dict entry, not a reordering -- out-of-order arrival by
  wall-clock receipt is accepted at its own instant and never smeared into
  the wrong slot.

The day boundary comes from `breezy.normalize.climate_day.climate_day_for_instant`
-- local STANDARD time, never UTC, never DST-aware. When a push's climate day
differs from the day currently held, every prior row is discarded: `R`
starts over at local-standard midnight, matching the offline oracle
`build_running_max_days` (`scripts/analysis/pmr_climatology_study.py:351`).
A missing interval is never interpolated -- an empty accumulator, or an
instant that predates the earliest pushed row, answers `None`
(`value_at`) and an unbounded `staleness_ns`, and callers are expected to
refuse rather than invent a temperature (L-17).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Final

from breezy.normalize.climate_day import climate_day_for_instant

_NS_PER_SECOND: Final[int] = 1_000_000_000


def _instant_from_ns(instant_ns: int) -> dt.datetime:
    """Convert UNIX nanoseconds to a UTC `datetime`, exactly.

    Integer `divmod`, never float division: `instant_ns / 1e9` loses
    sub-microsecond precision at real epoch magnitudes (~1e18 ns), which is
    enough to round an instant across a day boundary -- exactly the failure
    a climate-day computation cannot tolerate.
    """
    seconds, nanoseconds = divmod(instant_ns, _NS_PER_SECOND)
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(
        microseconds=nanoseconds // 1_000,
    )


@dataclass(frozen=True, slots=True)
class _Row:
    rounded_f: int
    temp_f: float


class RunningExtremeAccumulator:
    """Online `R(t)` for one station, one climate day at a time."""

    def __init__(self, *, std_utc_offset_hours: float) -> None:
        self._std_utc_offset_hours = std_utc_offset_hours
        self._rows: dict[int, _Row] = {}
        self._current_climate_day: dt.date | None = None

    def push(self, observed_at_ns: int, rounded_f: int, temp_f: float) -> None:
        """Record one observation, resetting the accumulator on a day change.

        A same-instant re-push REPLACES the stored row (see module
        docstring) -- the new `rounded_f` may be lower than the one it
        replaces, and that is accepted, not corrected upward.
        """
        day = climate_day_for_instant(
            _instant_from_ns(observed_at_ns), self._std_utc_offset_hours,
        )
        if self._current_climate_day is not None and day != self._current_climate_day:
            self._rows = {}
        self._current_climate_day = day
        self._rows[observed_at_ns] = _Row(rounded_f=rounded_f, temp_f=temp_f)

    def value_at(self, now_ns: int) -> int | None:
        """`R(now_ns)`: the max `rounded_f` of rows measured at or before `now_ns`.

        No `lag` parameter -- see the module docstring's amendment A1 note.
        Returns `None` when `now_ns` falls outside the currently-held
        climate day, or when no row measured at or before `now_ns` has been
        pushed -- never a carried-over or interpolated value.
        """
        if self._current_climate_day is None:
            return None
        day = climate_day_for_instant(_instant_from_ns(now_ns), self._std_utc_offset_hours)
        if day != self._current_climate_day:
            return None
        eligible = [
            row.rounded_f for observed_at_ns, row in self._rows.items() if observed_at_ns <= now_ns
        ]
        if not eligible:
            return None
        return max(eligible)

    def staleness_ns(self, now_ns: int) -> int | None:
        """`now_ns` minus the newest observed instant, or `None` if empty."""
        if not self._rows:
            return None
        newest_observed_ns = max(self._rows)
        return now_ns - newest_observed_ns

    @property
    def earliest_observed_ns(self) -> int | None:
        """The earliest `observed_at_ns` currently held, or `None` if empty."""
        if not self._rows:
            return None
        return min(self._rows)

    @property
    def covered(self) -> bool:
        """`True` iff at least one observation is currently held."""
        return bool(self._rows)
