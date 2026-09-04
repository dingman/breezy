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

Interval-valued `R(t)` (amendment A13)
---------------------------------------
Not every source reports at METAR tenths resolution: the NWS 5-minute API
reports a whole degree Celsius, meaning the true value lies somewhere in
``[x - 0.5, x + 0.5)`` degrees C -- an INTERVAL, not a point. `push` now
takes each row's own ``precision_c_tenths`` (in tenths of a degree C, the
FULL width of the interval the true value is known to lie within -- e.g.
``10`` for an integer-degree-C row, matching ``[x - 0.5, x + 0.5)``) and
``is_metar`` flag.

A METAR (``is_metar=True``) row is treated as an EXACT point regardless of
its own ``precision_c_tenths`` -- METAR's own ``T``-group already reports
tenths resolution, so its reading is the settlement-grade datum and is never
widened into an interval here; ``precision_c_tenths`` is still recorded on
it (see ``StationObservation``) as descriptive provenance, but this
accumulator does not use it to build a METAR row's bounds.

`value_at` returns a frozen :class:`RunningMax` describing the running max
as ``[lower_f, upper_f]`` -- CLOSED at BOTH ends, matching
``WeatherBucketFacts.contains`` (``breezy/domain/weather_bucket_facts.py``,
verified against 114/114 real venue ladders):

* ``lower_f`` = the max, over every eligible row, of ``round_half_up_f`` of
  that row's Celsius-tenths LOWER bound (its own ``temp_c_tenths`` for a
  METAR row, or ``temp_c_tenths - precision_c_tenths // 2`` otherwise). The
  lower end of a non-METAR row's real interval is CLOSED (``x - 0.5`` is
  itself achievable), and `round_half_up_f` is monotone non-decreasing, so
  the rounded value AT that closed lower endpoint is exactly the maximum
  achievable there -- no special derivation needed.
* ``upper_f`` = the max, over every eligible row, of that row's CLOSED upper
  Fahrenheit bound: its own ``round_half_up_f(temp_c_tenths)`` for a METAR
  row (an exact point), or ``breezy.domain.temperature.max_rounded_f_below``
  applied to ``temp_c_tenths + precision_c_tenths // 2`` otherwise. A
  non-METAR row's real interval is HALF-OPEN on the upper end
  (``[x - 0.5, x + 0.5)``) and the real temperature is continuous, not
  confined to the tenths grid -- so the largest ACHIEVABLE rounded
  Fahrenheit value is the supremum of `round_half_up_f` over reals
  approaching that exclusive bound from below, not `round_half_up_f` of the
  bound itself (worked example: a 29 C row's real interval is
  ``[28.5, 29.5)`` C; 29.4 C is inside it and rounds to 85 F, so ``upper_f``
  is 85, not `round_half_up_f(295) == 85` by coincidence but
  `round_half_up_f(294) == 84` would UNDER-count if the exclusive tenths
  boundary itself were rounded naively -- see `max_rounded_f_below`'s
  docstring for the exact derivation).
* ``exact_f`` is set (non-``None``) only when the row that determines
  ``upper_f`` (ties broken toward a METAR row, then toward the latest
  ``observed_at_ns``) is itself a METAR row -- in that case the interval
  collapses to that row's own rounded value.

Use :meth:`RunningMax.spans` against the ACTUAL venue ladder (closed-closed
rungs, exactly the shape ``WeatherBucketFacts.lower_f``/``upper_f`` expose)
to decide whether ``[lower_f, upper_f]`` can be resolved to one rung; a rung
decision on a spanning interval must be REFUSED by the caller, never rounded
or guessed (L-17).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from breezy.domain.temperature import max_rounded_f_below, round_half_up_f
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
    received_at_ns: int
    temp_c_tenths: int
    precision_c_tenths: int
    is_metar: bool

    def _half_width_c_tenths(self) -> int:
        return self.precision_c_tenths // 2

    def lower_c_tenths(self) -> int:
        if self.is_metar:
            return self.temp_c_tenths
        return self.temp_c_tenths - self._half_width_c_tenths()

    def upper_f_closed(self) -> int:
        """The row's CLOSED upper Fahrenheit bound.

        A METAR row is an exact point: its own rounded value. A non-METAR
        row's real interval is half-open on the upper end
        (``[x - half_width, x + half_width)``), so the achievable maximum is
        the supremum of `round_half_up_f` over reals approaching that
        exclusive Celsius-tenths bound from below -- see
        `breezy.domain.temperature.max_rounded_f_below`.
        """
        if self.is_metar:
            return round_half_up_f(self.temp_c_tenths)
        upper_c_tenths_exclusive = self.temp_c_tenths + self._half_width_c_tenths()
        return max_rounded_f_below(upper_c_tenths_exclusive)


@dataclass(frozen=True, slots=True)
class RunningMax:
    """The running maximum as a Fahrenheit INTERVAL `[lower_f, upper_f]`.

    Both ends are CLOSED, matching `WeatherBucketFacts.contains`
    (`breezy/domain/weather_bucket_facts.py`, verified against 114/114 real
    venue ladders) -- NOT the venue's own half-open rung-label convention
    (`gteXXltYYf`), which is a display convention, not this interval's
    shape. `exact_f` is set only when the interval collapses to a single
    Fahrenheit integer because the maximizing row was a METAR (exact,
    tenths) reading -- see the module docstring's "Interval-valued `R(t)`"
    section for the exact definition of `lower_f`/`upper_f`/`exact_f`.
    """

    lower_f: int
    upper_f: int
    exact_f: int | None
    source_observed_at_ns: int
    source_received_at_ns: int

    def spans(self, bounds: Sequence[tuple[int | None, int | None]]) -> bool:
        """`True` iff `[lower_f, upper_f]` (closed both ends) cannot be resolved to ONE rung.

        `bounds` uses the SAME closed-closed convention as
        `WeatherBucketFacts.lower_f`/`upper_f` -- pass those fields straight
        through. Each element is `(rung_lower_f, rung_upper_f)`; either
        bound may be `None` for an open (unbounded) tail rung. `bounds`
        order and coverage are the caller's responsibility -- this method
        does not validate that `bounds` tiles the real number line without
        gaps or overlaps.

        Ambiguous (returns `True`) both when `lower_f` and `upper_f` fall in
        DIFFERENT listed rungs, and when either endpoint falls in NO listed
        rung at all -- this method fails closed rather than assume
        containment it cannot prove.
        """

        def _rung_index(value: int) -> int | None:
            for index, (rung_lower, rung_upper) in enumerate(bounds):
                if rung_lower is not None and value < rung_lower:
                    continue
                if rung_upper is not None and value > rung_upper:
                    continue
                return index
            return None

        lower_rung = _rung_index(self.lower_f)
        upper_rung = _rung_index(self.upper_f)
        if lower_rung is None or upper_rung is None:
            return True
        return lower_rung != upper_rung


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Facts about the rows currently held, at or before some `now_ns` (amendment A8).

    No policy is baked in here -- see :meth:`RunningExtremeAccumulator.coverage`.
    """

    first_observed_ns: int | None
    last_observed_ns: int | None
    largest_gap_ns: int | None


class RunningExtremeAccumulator:
    """Online `R(t)` for one station, one climate day at a time."""

    def __init__(self, *, std_utc_offset_hours: float) -> None:
        self._std_utc_offset_hours = std_utc_offset_hours
        self._rows: dict[int, _Row] = {}
        self._current_climate_day: dt.date | None = None

    def push(
        self,
        observed_at_ns: int,
        temp_c_tenths: int,
        precision_c_tenths: int,
        is_metar: bool,
        received_at_ns: int,
    ) -> None:
        """Record one observation, resetting the accumulator on a day change.

        A same-instant re-push REPLACES the stored row (see module
        docstring) -- the new `temp_c_tenths` may be lower than the one it
        replaces, and that is accepted, not corrected upward.

        `precision_c_tenths` is the full width, in tenths of a degree C, of
        the interval the true value is known to lie within (amendment A13,
        ignored for a METAR row -- see the module docstring); `is_metar`
        marks a tenths-resolution (METAR) reading. `received_at_ns` is the
        instant Breezy received this row -- `value_at` gates on it exactly
        as it gates on `observed_at_ns` (module docstring amendment A1:
        "measurement <= t AND receipt <= t"), so a row cannot be visible to
        a live `now_ns` before Breezy actually had it, mirroring the
        archive oracle's `running_max_at` gate (`valid <= t`,
        `scripts/analysis/h4_preliminary_economic_read.py:336-347`). Feed
        `received_at_ns == observed_at_ns` to reproduce the archive, which
        has no separate receipt instant.
        """
        day = climate_day_for_instant(
            _instant_from_ns(observed_at_ns), self._std_utc_offset_hours,
        )
        if self._current_climate_day is not None and day != self._current_climate_day:
            self._rows = {}
        self._current_climate_day = day
        self._rows[observed_at_ns] = _Row(
            received_at_ns=received_at_ns,
            temp_c_tenths=temp_c_tenths,
            precision_c_tenths=precision_c_tenths,
            is_metar=is_metar,
        )

    def value_at(self, now_ns: int) -> RunningMax | None:
        """`R(now_ns)`: the running max, as an interval, of rows measured at or before `now_ns`.

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
            (observed_at_ns, row)
            for observed_at_ns, row in self._rows.items()
            if observed_at_ns <= now_ns and row.received_at_ns <= now_ns
        ]
        if not eligible:
            return None

        lower_f = max(round_half_up_f(row.lower_c_tenths()) for _, row in eligible)

        # The row that determines `upper_f`: ties broken toward a METAR row,
        # then toward the latest `observed_at_ns`, so `exact_f` and
        # `source_observed_at_ns` are picked deterministically.
        def _sort_key(item: tuple[int, _Row]) -> tuple[int, bool, int]:
            observed_at_ns, row = item
            return (row.upper_f_closed(), row.is_metar, observed_at_ns)

        max_observed_at_ns, max_row = max(eligible, key=_sort_key)
        upper_f = max_row.upper_f_closed()
        exact_f = round_half_up_f(max_row.temp_c_tenths) if max_row.is_metar else None

        return RunningMax(
            lower_f=lower_f,
            upper_f=upper_f,
            exact_f=exact_f,
            source_observed_at_ns=max_observed_at_ns,
            source_received_at_ns=max_row.received_at_ns,
        )

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

    def coverage(self, now_ns: int, expected_cadence_ns: int) -> CoverageReport:
        """Report facts about the currently-held rows, at or before `now_ns`.

        `expected_cadence_ns` must be positive (a nonsensical cadence is
        rejected fail-fast) but is NOT used to compute any field below --
        amendment A8 states this deliberately: this method reports facts
        only, never a policy verdict. Comparing `largest_gap_ns` against
        `expected_cadence_ns` (e.g. "no gap over the staleness bound") is
        Seam B's decision, made from these facts.

        `largest_gap_ns` is the largest gap between two CONSECUTIVE stored
        rows at or before `now_ns` -- `None` when fewer than two such rows
        are held. It does not include the trailing gap from
        `last_observed_ns` to `now_ns`; that fact is already available from
        `staleness_ns`.
        """
        if expected_cadence_ns <= 0:
            raise ValueError(
                f"`expected_cadence_ns` must be positive, was {expected_cadence_ns}",
            )

        eligible_ns = sorted(
            observed_at_ns for observed_at_ns in self._rows if observed_at_ns <= now_ns
        )
        if not eligible_ns:
            return CoverageReport(
                first_observed_ns=None, last_observed_ns=None, largest_gap_ns=None,
            )

        largest_gap_ns: int | None = None
        if len(eligible_ns) >= 2:
            largest_gap_ns = max(
                later - earlier for earlier, later in pairwise(eligible_ns)
            )

        return CoverageReport(
            first_observed_ns=eligible_ns[0],
            last_observed_ns=eligible_ns[-1],
            largest_gap_ns=largest_gap_ns,
        )
