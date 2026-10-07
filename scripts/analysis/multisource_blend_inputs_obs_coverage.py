"""F13 Phase A feature build: routine-METAR coverage, drift and staleness diagnostics.

Pure helpers (no store reads) for the ``obs_so_far`` source. The build REFUSES a station-year whose
coverage (routine rows used / expected hourly reports in the requested window) is below the
prereg pin ``obs_min_coverage_per_station_year``; everything else here is descriptive.

* ``expected`` counts, per requested climate day, the hourly report instants at the pinned routine
  minute from local-standard-time midnight up to the day's last anchor (the same window the
  reader keeps); ``used`` is the rows that became readings (T group present, at the pinned
  minute). A day absent from the store therefore lowers coverage instead of being skipped.
* The minute histogram and the pin-minute-excluded share cover EVERY stored row in that window,
  so an era change in the report minute (a new ASOS vintage) shows even if the pin still holds.
* ``d0_mean_truth_minus_obs_so_far`` is the mean of (final truth Tmax - D0 ``obs_so_far``): a
  drift of it across years flags a downward obs bias by era. Truth is the builder's own
  pre-holdout truth input.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "COVERAGE_PIN",
    "ObsDiagnostics",
    "YearCoverage",
    "check_coverage_pin",
    "coverage_report",
    "expected_report_count",
    "staleness_report",
]

COVERAGE_PIN: Final[str] = "obs_min_coverage_per_station_year"
_NS: Final[int] = 1_000_000_000
_HOURS_PER_DAY: Final[int] = 24
_SECONDS_PER_HOUR: Final[int] = 3600
_NS_PER_MINUTE: Final[int] = 60 * _NS
_P90: Final[float] = 0.9


def expected_report_count(
    day: dt.date, std_utc_offset_hours: float, routine_minute: int, cutoff_ns: int
) -> int:
    """Hourly report instants at ``routine_minute`` in the local-standard day up to the cutoff."""
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC) - dt.timedelta(
        hours=std_utc_offset_hours
    )
    first_ns = int(start.timestamp()) * _NS + routine_minute * _NS_PER_MINUTE
    step_ns = _SECONDS_PER_HOUR * _NS
    return sum(1 for hour in range(_HOURS_PER_DAY) if first_ns + hour * step_ns <= cutoff_ns)


@dataclass(slots=True)
class YearCoverage:
    """One station-year's routine-METAR coverage counters (see the module docstring)."""

    expected: int = 0
    used: int = 0
    rows_in_window: int = 0
    pin_minute_excluded: int = 0
    minute_histogram: Counter[int] = field(default_factory=Counter)
    _months: dict[int, list[int]] = field(default_factory=dict)  # month -> [expected, used]

    def add_expected(self, month: int, count: int) -> None:
        self.expected += count
        self._months.setdefault(month, [0, 0])[0] += count

    def add_row(self, minute: int, pinned_minute: int) -> None:
        self.rows_in_window += 1
        self.minute_histogram[minute] += 1
        self.pin_minute_excluded += int(minute != pinned_minute)

    def add_used(self, month: int) -> None:
        self.used += 1
        self._months.setdefault(month, [0, 0])[1] += 1

    @property
    def coverage(self) -> float | None:
        return self.used / self.expected if self.expected else None

    @property
    def pin_minute_excluded_share(self) -> float | None:
        return self.pin_minute_excluded / self.rows_in_window if self.rows_in_window else None

    @property
    def by_month(self) -> dict[int, tuple[int, int]]:
        return {month: (cell[0], cell[1]) for month, cell in sorted(self._months.items())}


def check_coverage_pin(pin: object) -> float:
    """The coverage pin as a fraction in [0, 1]; anything else (incl. null) is ``ValueError``."""
    if isinstance(pin, bool) or not isinstance(pin, int | float) or not 0.0 <= pin <= 1.0:
        raise ValueError(f"pins.{COVERAGE_PIN} must be a number in [0, 1], was {pin!r}")
    return float(pin)


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank quantile of a non-empty ascending sequence."""
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def _key(station: str, year: int) -> str:
    return f"{station}/{year}"


@dataclass(slots=True)
class ObsDiagnostics:
    """What the build collects about the ``obs_so_far`` source: coverage, D0 drift and staleness."""

    coverage: dict[tuple[str, int], YearCoverage] = field(default_factory=dict)
    d0_gap: dict[tuple[str, int], list[float]] = field(default_factory=dict)
    d0_staleness_minutes: dict[str, list[float]] = field(default_factory=dict)
    d0_no_report: Counter[str] = field(default_factory=Counter)

    def record_d0(
        self,
        icao: str,
        year: int,
        *,
        truth_tmax_f: float,
        obs_so_far_f: float | None,
        anchor_ns: int,
        readings: Sequence[Any],
    ) -> None:
        """One primary D0 row: the truth gap and the age of the newest usable report."""
        usable = [
            r.ts_ns for r in readings if r.available_at_ns < anchor_ns and r.ts_ns <= anchor_ns
        ]
        if obs_so_far_f is None or not usable:
            self.d0_no_report[icao] += 1
            return
        self.d0_gap.setdefault((icao, year), []).append(truth_tmax_f - obs_so_far_f)
        self.d0_staleness_minutes.setdefault(icao, []).append(
            (anchor_ns - max(usable)) / _NS_PER_MINUTE
        )

    def coverage_report(self, minimum: float | None) -> dict[str, Any]:
        return coverage_report(self.coverage, self.d0_gap, minimum)

    def staleness_report(self) -> dict[str, Any]:
        return staleness_report(self.d0_staleness_minutes, self.d0_no_report)

    def below_pin_message(self, minimum: float) -> str | None:
        """The refusal text naming every station-year below the pin, or ``None``."""
        below = _below_pin(self.coverage, minimum)
        if not below:
            return None
        return f"routine-METAR coverage is below pins.{COVERAGE_PIN} {minimum}: {below}"


def _below_pin(coverage: Mapping[tuple[str, int], YearCoverage], minimum: float) -> list[str]:
    return [
        _key(station, year)
        for (station, year), cov in sorted(coverage.items())
        if cov.coverage is not None and cov.coverage < minimum
    ]


def coverage_report(
    coverage: Mapping[tuple[str, int], YearCoverage],
    d0_gap: Mapping[tuple[str, int], Sequence[float]],
    minimum: float | None,
) -> dict[str, Any]:
    """Per station-year coverage, minute histogram, excluded share, drift, and who is below."""
    cells: dict[str, Any] = {}
    for (station, year), cov in sorted(coverage.items()):
        gaps = d0_gap.get((station, year), ())
        cells[_key(station, year)] = {
            "expected": cov.expected,
            "used": cov.used,
            "coverage": cov.coverage,
            "rows_in_window": cov.rows_in_window,
            "pin_minute_excluded": cov.pin_minute_excluded,
            "pin_minute_excluded_share": cov.pin_minute_excluded_share,
            "minute_histogram": {str(m): n for m, n in sorted(cov.minute_histogram.items())},
            "by_month": {
                str(month): {"expected": e, "used": u, "coverage": u / e if e else None}
                for month, (e, u) in cov.by_month.items()
            },
            "d0_n": len(gaps),
            "d0_mean_truth_minus_obs_so_far": sum(gaps) / len(gaps) if gaps else None,
        }
    return {
        "min_coverage_pin": minimum,
        "below_pin": [] if minimum is None else _below_pin(coverage, minimum),
        "per_station_year": cells,
        "note": (
            "coverage = routine rows used / expected hourly reports at the pinned minute, from "
            "local-standard midnight to each requested day's last anchor; the minute histogram and "
            "pin_minute_excluded_share cover every stored row in that window (an era change in the "
            "report minute shows here); d0_mean_truth_minus_obs_so_far is descriptive (final truth "
            "Tmax minus the D0 obs_so_far) and a drift across years flags a downward obs bias"
        ),
    }


def staleness_report(
    minutes_by_station: Mapping[str, Sequence[float]], no_report_by_station: Mapping[str, int]
) -> dict[str, Any]:
    """D0 ``anchor - newest usable report`` (minutes) per station; rows without one counted."""
    out: dict[str, Any] = {}
    for station in sorted(set(minutes_by_station) | set(no_report_by_station)):
        values = sorted(minutes_by_station.get(station, ()))
        out[station] = {
            "n": len(values),
            "no_usable_report": int(no_report_by_station.get(station, 0)),
            "min": values[0] if values else None,
            "p50": _quantile(values, 0.5) if values else None,
            "p90": _quantile(values, _P90) if values else None,
            "max": values[-1] if values else None,
            "mean": sum(values) / len(values) if values else None,
        }
    return out
