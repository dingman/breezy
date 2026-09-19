"""Per-station CLI-truth alignment for the frozen TXN climate-day map (FC-0a-4 Phase B).

Aligns the daily-max TXN window (``TXN_MAX_PERIOD_HOURS`` ending at
``TXN_MAX_PERIOD_END_UTC_HOUR``, both from ``forecast_climate_day_map.py``)
against real NWS CLI climate-day truth already archived on this host --
``settlement_alignment_cache.py`` / ``pmr_climatology_study.load_cli_records``
-- the SAME cache ``cli_basis_boundary_study.py`` and its siblings already
read. This module NEVER reads the IEM MOS probe captures under
``docs/evidence/iem_mos_reachability_probe_*``: those are reachability
evidence only (see that directory's ``README.md``, "EVIDENCE ONLY - NEVER
INGEST") and are read directly by the evidence document this script's
output feeds, never by this module.

Two independent checks, per station:

1. DAY-LABEL CROSS-CHECK (P2). For every real archived CLI final day ``D``,
   build the canonical ``(runtime, ftime)`` pair for the daily-max TXN
   period targeting ``D`` (``ftime = 06Z(D+1)``, ``runtime = 12Z(D)``) and
   assert ``climate_day_for_txn`` returns exactly ``D``. This is exhaustive
   over the real archive, not a sample. A station that fails this needs a
   PER-STATION map (plan WP-4 GATE) and drops out of the shared formula --
   it must never be papered over with a fudged global map.

2. WINDOW-COVERAGE CHECK (P1, corollary). Whether the CLI-published
   ``MAXIMUM ... (LST)`` time-of-day for each real archived day falls
   inside the TXN window's local-standard hour range for that station. A
   miss means the 18h window would not have captured that day's true
   published maximum -- a forecast-ACCURACY signal for Stage 0b's fit, not
   itself a day-labeling defect: day-labeling depends only on
   ``valid_start_ns``'s local date, never on window length.

Pure functions take a caller-supplied ``finals_by_day`` mapping (the exact
shape ``load_cli_records`` returns), so unit tests exercise them with small
synthetic ``CliRecord`` rows -- no real cache read, no network, matching
``test_cli_basis_boundary_study.py``'s convention ("every fixture is
synthetic or built from small in-memory rows"). ``main()`` is the only
real-I/O path, invoked by a human to regenerate the evidence document; the
pytest suite never calls it.

No network. No ingest: this module only READS the pre-existing local
settlement-alignment cache and writes nothing to any catalog.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from forecast_climate_day_map import (  # noqa: E402
    TXN_MAX_PERIOD_END_UTC_HOUR,
    TXN_MAX_PERIOD_HOURS,
    climate_day_for_txn,
)
from pmr_climatology_study import CliRecord  # noqa: E402
from settlement_alignment_cache import require_settlement_alignment_cache_dir  # noqa: E402
from settlement_alignment_study import SiteSpec, load_sites  # noqa: E402

__all__ = [
    "DEFAULT_OUTPUT",
    "FORECAST_STATIONS",
    "StationAlignmentResult",
    "WindowBounds",
    "align_station",
    "build_report",
    "climate_day_for_real_final",
    "is_hour_in_window",
    "load_and_align",
    "main",
    "window_bounds",
]

_NS: Final[int] = 10**9
_SECONDS_PER_HOUR: Final[int] = 3600

DEFAULT_OUTPUT: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evidence"
    / "forecast_txn_climate_day_cli_alignment_2026-09-19.md"
)

#: ICAO -> registry city token. Mirrors
#: ``tests/support/forecast_climate_day_fixtures.FORECAST_STATIONS``
#: deliberately: that module is test support and this is a production-
#: adjacent analysis script, so the two are not permitted to import each
#: other, but both name the same four stations for the same reason (parent
#: plan §3.4; KNYC excluded).
FORECAST_STATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("KMIA", "MIA"),
    ("KMDW", "MDW"),
    ("KSFO", "SFO"),
    ("KLAX", "LAX"),
)

DEFAULT_ARCHIVE_START: Final[dt.date] = dt.date(2021, 1, 1)
DEFAULT_ARCHIVE_END: Final[dt.date] = dt.date(2025, 12, 31)


@dataclass(frozen=True, slots=True)
class WindowBounds:
    """The TXN daily-max window expressed as local-standard hours-of-day.

    ``start_local_hour`` is ``valid_start_ns``'s local-standard hour;
    ``end_local_hour`` is ``ftime_ns``'s. When ``wraps`` is ``True`` the
    window's END lands after local midnight on ``D + 1`` (MIA/MDW at the
    frozen constants); the ``D``-day portion of the window is then
    ``[start_local_hour, 24)`` -- the ``D + 1`` sliver is checked against a
    *different* day's CLI record and is out of scope for this function.
    """

    start_local_hour: int
    end_local_hour: int
    wraps: bool


def window_bounds(std_utc_offset_hours: float) -> WindowBounds:
    """Compute the TXN daily-max window's local-standard hour bounds.

    Pure arithmetic on the frozen constants in ``forecast_climate_day_map``;
    no clock, no ``zoneinfo``. ``std_utc_offset_hours`` must be an integer
    number of hours for the result to line up with a whole local hour --
    true of every site in ``sites.toml`` today.
    """
    start = int((TXN_MAX_PERIOD_END_UTC_HOUR - TXN_MAX_PERIOD_HOURS + std_utc_offset_hours) % 24)
    end = int((TXN_MAX_PERIOD_END_UTC_HOUR + std_utc_offset_hours) % 24)
    return WindowBounds(start_local_hour=start, end_local_hour=end, wraps=end <= start)


def is_hour_in_window(hour: int, bounds: WindowBounds) -> bool:
    """Return whether local-standard ``hour`` (0..23) falls in the window's own-day portion."""
    if bounds.wraps:
        return hour >= bounds.start_local_hour or hour < bounds.end_local_hour
    return bounds.start_local_hour <= hour < bounds.end_local_hour


def climate_day_for_real_final(
    *,
    icao: str,
    climate_day: dt.date,
    std_utc_offset_hours: float,
    model: str = "NBM_NBS",
) -> dt.date:
    """Map the canonical daily-max TXN row targeting a real archived ``climate_day``.

    Builds ``runtime = 12Z(climate_day)`` and ``ftime = 06Z(climate_day + 1
    day)`` -- the frozen constants' own period -- and delegates to
    ``climate_day_for_txn``. The runtime choice does not affect the result
    (the mapper is runtime-invariant given a fixed ``ftime``; see
    ``test_off_grid_runtime_is_accepted_not_refused``), so any valid runtime
    at or before ``ftime`` would do; 12Z(D) is used because it is the
    period's own documented start.
    """
    runtime = dt.datetime(
        climate_day.year, climate_day.month, climate_day.day, 12, tzinfo=dt.UTC
    )
    ftime_day = climate_day + dt.timedelta(days=1)
    ftime = dt.datetime(ftime_day.year, ftime_day.month, ftime_day.day, 6, tzinfo=dt.UTC)
    return climate_day_for_txn(
        icao=icao,
        runtime_ns=int(runtime.timestamp()) * _NS,
        ftime_ns=int(ftime.timestamp()) * _NS,
        std_utc_offset_hours=std_utc_offset_hours,
        model=model,
    )


@dataclass(frozen=True, slots=True)
class StationAlignmentResult:
    """Per-station alignment outcome against the real CLI archive."""

    icao: str
    city: str
    std_utc_offset_hours: float
    n_days: int
    day_label_mismatches: tuple[dt.date, ...]
    n_with_max_time: int
    window_misses: tuple[tuple[dt.date, int], ...]

    @property
    def day_label_confirmed(self) -> bool:
        """``True`` iff the shared formula never mislabels a real archived day."""
        return len(self.day_label_mismatches) == 0

    @property
    def window_miss_rate(self) -> float:
        if self.n_with_max_time == 0:
            return 0.0
        return len(self.window_misses) / self.n_with_max_time


def align_station(
    *,
    icao: str,
    city: str,
    std_utc_offset_hours: float,
    finals_by_day: Mapping[dt.date, CliRecord],
    model: str = "NBM_NBS",
) -> StationAlignmentResult:
    """Run both checks for one station against a caller-supplied final-by-day mapping."""
    bounds = window_bounds(std_utc_offset_hours)
    day_label_mismatches: list[dt.date] = []
    window_misses: list[tuple[dt.date, int]] = []
    n_with_max_time = 0
    for climate_day, record in sorted(finals_by_day.items()):
        mapped = climate_day_for_real_final(
            icao=icao,
            climate_day=climate_day,
            std_utc_offset_hours=std_utc_offset_hours,
            model=model,
        )
        if mapped != climate_day:
            day_label_mismatches.append(climate_day)
        if record.max_time is not None:
            n_with_max_time += 1
            hour = record.max_time.hour_of_day
            if not is_hour_in_window(hour, bounds):
                window_misses.append((climate_day, hour))
    return StationAlignmentResult(
        icao=icao,
        city=city,
        std_utc_offset_hours=std_utc_offset_hours,
        n_days=len(finals_by_day),
        day_label_mismatches=tuple(day_label_mismatches),
        n_with_max_time=n_with_max_time,
        window_misses=tuple(window_misses),
    )


def load_and_align(
    *,
    cache_dir: Path,
    spec: SiteSpec,
    start: dt.date,
    end: dt.date,
) -> StationAlignmentResult:
    """Real-I/O wrapper: load the archive for one site, then ``align_station``."""
    from pmr_climatology_study import load_cli_records

    finals, _every, _drops = load_cli_records(cache_dir=cache_dir, spec=spec, start=start, end=end)
    return align_station(
        icao=spec.site.icao,
        city=spec.city,
        std_utc_offset_hours=spec.std_utc_offset_hours,
        finals_by_day=finals,
    )


def build_report(results: Sequence[StationAlignmentResult]) -> str:
    """Render the per-station alignment results as a markdown evidence document."""
    lines = [
        "# Forecast TXN (icao, runtime, ftime) -> climate_day: CLI-truth alignment",
        "",
        "FC-0a-4 Phase B. Generated by "
        "`scripts/analysis/forecast_txn_climate_day_cli_alignment.py`.",
        "",
        f"TXN_MAX_PERIOD_END_UTC_HOUR={TXN_MAX_PERIOD_END_UTC_HOUR} "
        f"TXN_MAX_PERIOD_HOURS={TXN_MAX_PERIOD_HOURS}",
        "",
        "| station | offset | n_days | day-label mismatches | window-miss rate | n misses / n with time |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.icao} | {result.std_utc_offset_hours} | {result.n_days} | "
            f"{len(result.day_label_mismatches)} | {result.window_miss_rate:.4f} | "
            f"{len(result.window_misses)} / {result.n_with_max_time} |"
        )
    lines.append("")
    for result in results:
        lines.append(f"## {result.icao}")
        lines.append("")
        if result.day_label_mismatches:
            lines.append(
                f"DAY-LABEL MISMATCHES ({len(result.day_label_mismatches)}): "
                f"{', '.join(d.isoformat() for d in result.day_label_mismatches[:10])}"
            )
        else:
            lines.append(
                f"Day-label cross-check: 0 mismatches over {result.n_days} real archived days."
            )
        lines.append("")
        examples = ", ".join(f"{d.isoformat()}@{h:02d}h" for d, h in result.window_misses[:5])
        lines.append(
            f"Window-coverage miss rate: {result.window_miss_rate:.4%} "
            f"({len(result.window_misses)} / {result.n_with_max_time}). "
            f"Examples: {examples or 'none'}"
        )
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--start-date", type=dt.date.fromisoformat, default=DEFAULT_ARCHIVE_START)
    parser.add_argument("--end-date", type=dt.date.fromisoformat, default=DEFAULT_ARCHIVE_END)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR

    args = parse_args(sys.argv[1:] if argv is None else argv)
    cache_dir = require_settlement_alignment_cache_dir(
        args.cache_dir if args.cache_dir is not None else DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
    )
    sites = {spec.city: spec for spec in load_sites()}
    results = []
    for icao, city in FORECAST_STATIONS:
        spec = sites[city]
        if spec.site.icao != icao:
            raise RuntimeError(f"registry ICAO mismatch for {city}: {spec.site.icao} != {icao}")
        results.append(
            load_and_align(cache_dir=cache_dir, spec=spec, start=args.start_date, end=args.end_date)
        )
    report = build_report(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
