"""CLI-basis candidate #2 -- per-hour setup-win-rate profile (Item 3, resolved).

Resolves the challenge banner on top of
``docs/evidence/cli_basis_setup_win_rate_2026-09-02T060103Z.md``: that study
pools ``P(win | setup)`` across EVERY local-standard hour 0..23
(``cli_basis_setup_win_rate_study.py:174``'s ``for hour in range(24)``), so a
09:00 instant with ASOS headroom 1-or-2 counts identically to a 23:00 one.
At 09:00 the running max is typically nowhere near the day's eventual max, so
the strike is reached by ordinary diurnal warming, not by the CLI-vs-ASOS
basis this family actually trades. Pooling that in inflates the headline.

This module answers two questions BEFORE fixing anything, per the
pre-registration this module implements
(``pre_registration_2026-09-02T061500Z.md``):

1. What does ``P(win | setup)`` actually look like AT EACH local-standard
   hour, per dense station? (``setup_hour_cell`` /
   ``aggregate_setup_cases_by_hour``.)
2. At each hour, how often has the running max ALREADY reached its
   end-of-day value -- ``P(R_h == R_23)``? (``convergence_counts_by_hour``.)
   Where this is low, a "setup" at that hour is really "the day is not over
   yet", not a CLI-vs-ASOS basis event.

Only THEN does this module fix an admissibility rule
(``is_admissible_hour`` / ``ADMISSIBLE_HOUR_FLOOR``) and recompute the
corrected headline (``filter_cases_by_admissible_hours``, then the existing,
UNCHANGED ``summarize_station`` / ``pool_stations`` / ``pooled_verdict``).

NULL HYPOTHESIS, checked before this module was written (L-1, L-11)
---------------------------------------------------------------------
* ``cli_basis_setup_win_rate_study.build_setup_cases`` -- already produces
  one ``SetupCase`` per ``(station, day, hour, margin)`` for EVERY hour
  0..23, tagged with ``.hour``. NATIVE-EXISTS-AND-REUSED verbatim via
  import -- nothing about the per-hour breakdown required touching or
  widening that function; the breakdown was already latent in its output,
  merely pooled away by ``summarize_station``. Reused, not reimplemented.
* ``cli_basis_setup_win_rate_study.summarize_station`` / ``pool_stations`` /
  ``pooled_verdict`` / ``SetupCase`` / ``DENSE_STATIONS`` /
  ``QUALIFYING_MARGINS`` / ``PRIMARY_BAR`` / ``MIN_ADMISSIBLE_N`` --
  NATIVE-EXISTS-AND-REUSED verbatim via import. The corrected headline is
  produced by handing this module's FILTERED cases to the SAME, unmodified
  pooling/verdict pipeline, so the corrected number is comparable to the
  original one call-for-call.
* ``cli_basis_boundary_study.hour_coverage`` / ``is_non_sentinel_final`` /
  ``STUDY_HOURS`` -- NATIVE-EXISTS-AND-REUSED verbatim via import.
  ``STUDY_HOURS[0] == 17`` is reused as ``ADMISSIBLE_HOUR_FLOOR`` rather than
  re-derived, so this module's registered rule cannot silently diverge from
  the window the already-PASSED boundary study measured.
  ``cli_basis_boundary_study.py`` ITSELF is never modified (L-12: widen an
  exact-set barrier with a new, narrower variant, never by relaxing the
  original in place; it already carries its own PASSED, pre-registered gate).
* ``pmr_climatology_study.build_running_max_days`` / ``load_cli_records`` /
  ``RunningMaxDay`` / ``CliRecord`` -- the running-max fold and CLI-final
  archive loader, reused verbatim via import.
* ``settlement_alignment_study.load_sites`` / ``metar_temperatures`` /
  ``parse_asos_rows`` / ``asos_url`` / ``SiteSpec`` / ``START_DATE`` /
  ``END_DATE`` -- registry and ASOS archive access, reused verbatim via
  import. (The fetch/parse helpers live here, NOT in
  ``settlement_alignment_cache.py``, which only supplies the cache-dir
  constant/validator, reused separately below.)
* ``settlement_bucket_gate.read_cached`` -- the zero-network, cache-miss-
  refuses-loudly reader, reused verbatim via import.
* ``k1_cheap_open_settlement.wilson_interval`` -- the two-sided Wilson
  bound, reused verbatim via import, matching every other study in this
  family so the repo never grows a third disagreeing Wilson implementation.

GENUINE GAPS built here, narrow and additive only:

* ``aggregate_setup_cases_by_hour`` -- pools ``SetupCase``s by
  ``(station, hour)`` (margins 1-and-2 together), as opposed to
  ``summarize_station``'s all-hours-and-margins pool. Does not exist
  upstream: ``cli_basis_boundary_study.aggregate_cells`` is typed for
  ``BoundaryCase``, a different dataclass (no ``margin`` field), and is not
  reused here to avoid a type-incorrect duck-typed call.
* ``setup_hour_cell`` -- applies the shared Wilson bound to one per-hour
  count, mirroring ``cli_basis_boundary_study.cell_verdict``'s shape without
  its PASS/FAIL verdict machinery (this diagnostic reports rates, it does
  not gate on them).
* ``convergence_counts_by_hour`` -- ``P(R_h == R_23)`` per hour. No existing
  function compares two different hours of the SAME ``running_max_f`` series
  against each other; every existing study reads a single hour's value.
* ``is_admissible_hour`` / ``ADMISSIBLE_HOUR_FLOOR`` -- the registered
  admissibility predicate, deliberately a pure function of the clock hour
  alone (the lookahead guard: its signature has no parameter through which a
  realized running-max value or a day's own peak could reach it).
* ``filter_cases_by_admissible_hours`` -- applies that predicate to a tuple
  of ``SetupCase``, so the corrected headline reuses the existing pooling
  pipeline on a restricted input rather than re-deriving pooling logic.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_boundary_study import STUDY_HOURS, hour_coverage, is_non_sentinel_final
from cli_basis_setup_win_rate_study import (
    DENSE_STATIONS,
    MIN_ADMISSIBLE_N,
    PRIMARY_BAR,
    QUALIFYING_MARGINS,
    SetupCase,
    build_setup_cases,
    pool_stations,
    summarize_station,
)
from k1_cheap_open_settlement import wilson_interval
from pmr_climatology_study import CliRecord, RunningMaxDay, build_running_max_days
from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (
    END_DATE,
    START_DATE,
    SiteSpec,
    asos_url,
    load_sites,
    metar_temperatures,
    parse_asos_rows,
)
from settlement_bucket_gate import read_cached

__all__ = [
    "ADMISSIBLE_HOUR_FLOOR",
    "DENSE_STATIONS",
    "MIN_ADMISSIBLE_N",
    "PRIMARY_BAR",
    "QUALIFYING_MARGINS",
    "ConvergenceCell",
    "HourCell",
    "StationHourlyResult",
    "aggregate_setup_cases_by_hour",
    "analyse_station_hourly",
    "build_hour_cells",
    "convergence_counts_by_hour",
    "filter_cases_by_admissible_hours",
    "is_admissible_hour",
    "main",
    "setup_hour_cell",
]

#: The registered admissibility rule (see the module docstring and
#: `pre_registration_2026-09-02T061500Z.md`): a local-standard hour is
#: admissible only from `cli_basis_boundary_study.STUDY_HOURS[0]` onward --
#: reused, not re-chosen, so this study's window cannot silently drift from
#: the window the already-PASSED boundary study measured.
ADMISSIBLE_HOUR_FLOOR: Final[int] = STUDY_HOURS[0]


def is_admissible_hour(hour: int) -> bool:
    """Is `hour` (local-standard, 0..23) admissible under the registered rule?

    Deliberately a PURE function of the clock hour alone -- no running-max
    value, no realized peak, no day identity can reach this function, because
    its signature carries nothing but `hour`. That is the lookahead guard:
    admissibility is therefore computable AT THE INSTANT the clock reads
    `hour`, with no dependency on how the rest of that day turns out.
    """
    return hour >= ADMISSIBLE_HOUR_FLOOR


def filter_cases_by_admissible_hours(cases: Sequence[SetupCase]) -> tuple[SetupCase, ...]:
    """Keep only the `SetupCase`s at an admissible hour, in original order.

    The remaining pooling machinery is intentionally untouched:
    `summarize_station` / `pool_stations` / `pooled_verdict`, reused verbatim
    from `cli_basis_setup_win_rate_study`, only ever have to know how to pool
    a tuple of `SetupCase` -- what changed here is which cases they see.
    """
    return tuple(case for case in cases if is_admissible_hour(case.hour))


def aggregate_setup_cases_by_hour(
    cases: Iterable[SetupCase],
) -> dict[tuple[str, int], tuple[int, int]]:
    """Reduce `SetupCase`s to `{(station, hour): (n, k)}`, margins pooled."""
    counts: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for case in cases:
        bucket = counts[(case.station, case.hour)]
        bucket[0] += 1
        bucket[1] += int(case.hit)
    return {key: (values[0], values[1]) for key, values in counts.items()}


@dataclass(frozen=True, slots=True)
class HourCell:
    """One `(station, hour)` cell of the `P(win | setup)` diagnostic."""

    station: str
    hour: int
    n: int
    k: int
    rate: float
    wilson_lower: float
    wilson_upper: float


def setup_hour_cell(*, station: str, hour: int, n: int, k: int) -> HourCell:
    """Apply the shared Wilson bound to one per-hour `(n, k)` count."""
    interval = wilson_interval(k, n)
    lower, upper = interval if interval is not None else (0.0, 1.0)
    rate = k / n if n else 0.0
    return HourCell(
        station=station, hour=hour, n=n, k=k, rate=rate, wilson_lower=lower, wilson_upper=upper
    )


def build_hour_cells(
    *, station: str, counts: Mapping[tuple[str, int], tuple[int, int]]
) -> tuple[HourCell, ...]:
    """One station's full 0..23 `HourCell` row, keyed correctly by `(station, hour)`.

    Pulled out as its own function (rather than inlined in
    `analyse_station_hourly`) specifically so the `(station, hour)` lookup key
    has direct unit coverage -- `aggregate_setup_cases_by_hour` keys its
    counts by the PAIR, and a lookup that forgets the station half silently
    reads every hour as `(0, 0)` without raising anything.
    """
    return tuple(
        setup_hour_cell(station=station, hour=hour, n=n, k=k)
        for hour in range(24)
        for n, k in [counts.get((station, hour), (0, 0))]
    )


@dataclass(frozen=True, slots=True)
class ConvergenceCell:
    """One `(station, hour)` cell of the `P(R_h == R_23)` diagnostic."""

    station: str
    hour: int
    n: int
    k: int
    rate: float


def convergence_counts_by_hour(
    *,
    running_max_days: Sequence[RunningMaxDay],
    covered_hours_by_day: Mapping[dt.date, frozenset[int]],
    cli_finals: Mapping[dt.date, CliRecord],
) -> dict[int, tuple[int, int]]:
    """Per hour, `(n, k)` for `P(R_h == R_23)`.

    A day contributes to hour `h`'s count only when: `h` had a real ASOS
    observation (`covered_hours_by_day`, never a carried-forward gap, same
    guard `build_boundary_cases` uses); `running_max_f[h]` is defined; the
    day's end-of-day running value `running_max_f[23]` is defined (guards a
    day with no observations at all); and a non-sentinel CLI final exists,
    matching the exact admissible population the win-rate cells use, so the
    two diagnostics are read over the same denominator.  Hour 23 itself is
    NOT required to be independently covered -- `running_max_f[23]` already
    reads correctly off a carried-forward value if the day's last
    observation was earlier, which is the definition of "day's end-of-day
    value", not an observation-at-23:00 requirement.
    """
    counts: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for day in running_max_days:
        final = cli_finals.get(day.climate_day)
        if not is_non_sentinel_final(final):
            continue
        eod = day.running_max_f[23]
        if eod is None:
            continue
        covered = covered_hours_by_day.get(day.climate_day, frozenset())
        for hour in range(24):
            if hour not in covered:
                continue
            running_f = day.running_max_f[hour]
            if running_f is None:
                continue
            bucket = counts[hour]
            bucket[0] += 1
            bucket[1] += int(running_f == eod)
    return {hour: (values[0], values[1]) for hour, values in counts.items()}


@dataclass(frozen=True, slots=True)
class StationHourlyResult:
    """One station's full per-hour diagnostic: win-rate cells + convergence."""

    station: str
    hour_cells: tuple[HourCell, ...]
    convergence_cells: tuple[ConvergenceCell, ...]
    admissible_cases: tuple[SetupCase, ...]


def analyse_station_hourly(*, cache_dir: Path, spec: SiteSpec) -> StationHourlyResult:
    """Read one station's cached ASOS + CLI archives and build its diagnostic.

    Mirrors `cli_basis_setup_win_rate_study.analyse_station`'s shape; zero
    network (`read_cached` / `load_cli_records` both refuse a cache miss).
    """
    raw = read_cached(cache_dir, asos_url(spec.iem_asos_id, START_DATE, END_DATE), ".txt")
    rows = parse_asos_rows(raw.decode("utf-8", errors="replace"))
    temperatures, _drops = metar_temperatures(
        city=spec.city, rows=rows, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    in_window = tuple(t for t in temperatures if START_DATE <= t.climate_day <= END_DATE)

    running_days = build_running_max_days(
        city=spec.city, temperatures=in_window, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    coverage = hour_coverage(in_window, std_utc_offset_hours=spec.std_utc_offset_hours)
    finals, _every, _drops2 = load_cli_records_for(cache_dir=cache_dir, spec=spec)

    all_cases = build_setup_cases(
        station=spec.city,
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    hour_counts = aggregate_setup_cases_by_hour(all_cases)
    hour_cells = build_hour_cells(station=spec.city, counts=hour_counts)
    convergence_counts = convergence_counts_by_hour(
        running_max_days=running_days, covered_hours_by_day=coverage, cli_finals=finals
    )
    convergence_cells = tuple(
        ConvergenceCell(
            station=spec.city, hour=hour, n=n, k=k, rate=(k / n if n else 0.0)
        )
        for hour in range(24)
        for n, k in [convergence_counts.get(hour, (0, 0))]
    )
    admissible = filter_cases_by_admissible_hours(all_cases)
    return StationHourlyResult(
        station=spec.city,
        hour_cells=hour_cells,
        convergence_cells=convergence_cells,
        admissible_cases=admissible,
    )


def load_cli_records_for(
    *, cache_dir: Path, spec: SiteSpec
) -> tuple[dict[dt.date, CliRecord], tuple[CliRecord, ...], object]:
    """Thin, verbatim pass-through to `pmr_climatology_study.load_cli_records`.

    Kept as a tiny named wrapper only so `analyse_station_hourly` above reads
    identically to the sibling studies' own `analyse_station` shape; it adds
    no logic of its own.
    """
    from pmr_climatology_study import load_cli_records as _load_cli_records

    return _load_cli_records(cache_dir=cache_dir, spec=spec, start=START_DATE, end=END_DATE)


def _hour_table(results: Sequence[StationHourlyResult]) -> str:
    lines = [
        (
            "| station | hour | n (win-rate) | rate | Wilson lower | Wilson upper | "
            "n (convergence) | P(R_h == R_23) |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        by_hour_conv = {cell.hour: cell for cell in result.convergence_cells}
        for cell in result.hour_cells:
            conv = by_hour_conv.get(cell.hour)
            conv_n = conv.n if conv else 0
            conv_rate = conv.rate if conv else 0.0
            lines.append(
                f"| {cell.station} | {cell.hour} | {cell.n} | {cell.rate:.4%} "
                f"| {cell.wilson_lower:.4%} | {cell.wilson_upper:.4%} "
                f"| {conv_n} | {conv_rate:.4%} |"
            )
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR.as_posix())
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    sites_by_city = {spec.city: spec for spec in load_sites()}

    results: list[StationHourlyResult] = []
    for city in DENSE_STATIONS:
        spec = sites_by_city[city]
        result = analyse_station_hourly(cache_dir=cache_dir, spec=spec)
        results.append(result)

    print(_hour_table(results))

    per_station = [summarize_station(result.admissible_cases) for result in results]
    for station_result in per_station:
        print(
            f"[hourly-profile] {station_result.station} (admissible hours only): "
            f"n={station_result.n} k={station_result.k} "
            f"wilson_lower={station_result.wilson_lower:.4f} "
            f"wilson_upper={station_result.wilson_upper:.4f}"
        )
    pooled = pool_stations(per_station)
    print(
        f"[hourly-profile] POOLED (admissible hours only): n={pooled.n} k={pooled.k} "
        f"wilson_lower={pooled.wilson_lower:.4f} wilson_upper={pooled.wilson_upper:.4f} "
        f"verdict={pooled.verdict}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
