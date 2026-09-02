"""CLI-vs-ASOS basis boundary upper-tail climatology.

Pre-registered in
``scripts/analysis/pre_registration_2026-09-02T044737Z.md`` — read that file
first; this module implements exactly the statistic, bar, power rule and
multiplicity handling fixed there, in that order, before any outcome was
computed.

NULL HYPOTHESIS, checked before this module was written. The running-maximum
fold (``R_h(S, d)``), the ASOS/CLI archive loaders, and the Wilson score
interval all already exist in this repo:

* ``pmr_climatology_study.build_running_max_days`` — the running-max fold,
  reused verbatim via import, not reimplemented.
* ``pmr_climatology_study.load_cli_records`` / ``CliRecord`` — CLI-final
  loading from the AFOS zip cache, reused verbatim via import.
* ``settlement_alignment_study.metar_temperatures`` / ``load_sites`` /
  ``asos_url`` — ASOS archive loading and registry site resolution, reused
  verbatim via import.
* ``settlement_alignment_study.wilson_lower_bound`` — the Wilson score lower
  bound, reused verbatim via import (parameterized by ``z``, so both the
  primary 95% bound and the secondary Bonferroni-adjusted bound below reuse
  the same one function).

What is GENUINELY NEW here (and is what this module's tests exercise) is:

1. Per-hour ASOS *coverage* (as opposed to the running-max VALUE, which
   carries forward through empty hours) — needed because the pre-registered
   statistic only evaluates an hour when it is not a carried-forward gap.
2. The boundary/threshold construction (``running_f + 1``) and the join
   between a station's running-max days and its CLI finals, restricted to
   local-standard hours 17..23.
3. The pre-registered bar, power/admissibility rule, and the two Wilson
   bounds (primary one-sided-labeled 95%, secondary Bonferroni-adjusted)
   applied to each aggregated cell.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Final

from pmr_climatology_study import (
    CliRecord,
    RunningMaxDay,
    build_running_max_days,
    local_standard_hour,
)
from pmr_climatology_study import load_cli_records as _load_cli_records
from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (
    END_DATE,
    START_DATE,
    MetarTemperature,
    SiteSpec,
    asos_url,
    load_sites,
    metar_temperatures,
    wilson_lower_bound,
)
from settlement_bucket_gate import read_cached

__all__ = [
    "BONFERRONI_Z",
    "MIN_ADMISSIBLE_N",
    "PRIMARY_BAR",
    "STUDY_HOURS",
    "BoundaryCase",
    "CellResult",
    "StationResult",
    "aggregate_cells",
    "analyse_station",
    "build_boundary_cases",
    "build_report",
    "cell_verdict",
    "hour_coverage",
    "is_non_sentinel_final",
    "main",
]

DEFAULT_OUTPUT: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evidence"
    / "cli_basis_boundary_study_2026-09-02T044737Z.md"
)

#: Local-standard hours evaluated, per the pre-registration: "17..23".
STUDY_HOURS: Final[tuple[int, ...]] = (17, 18, 19, 20, 21, 22, 23)

#: `ask 0.05 + theta * p * (1-p) at p=0.05 with theta=0.06 + one 0.01 tick`,
#: reproduced in `pre_registration_2026-09-02T044737Z.md`.
PRIMARY_BAR: Final[float] = 0.06285

#: A cell needs at least this many station-days to be ADMISSIBLE. Below this
#: the cell is UNDERPOWERED, never FAIL.
MIN_ADMISSIBLE_N: Final[int] = 100

#: 5 stations x 7 hours = 35 cells. Two-sided Bonferroni-adjusted z for a
#: per-cell alpha of 0.05 / 35, i.e. a (1 - 0.05/35) = 99.857...% two-sided
#: bound. Computed, not hand-typed, so the value is exactly reproducible from
#: the stated correction.
BONFERRONI_Z: Final[float] = NormalDist().inv_cdf(1.0 - (0.05 / 35) / 2.0)


def hour_coverage(
    rows: Iterable[MetarTemperature], *, std_utc_offset_hours: float
) -> dict[dt.date, frozenset[int]]:
    """Per climate day, the set of local-standard hours with >= 1 observation.

    Deliberately independent of `build_running_max_days`'s `running_max_f`:
    that series carries the running value FORWARD through empty hours (by
    design, for the running-maximum statistic), so it cannot answer "did hour
    `h` itself have an observation" -- an hour with no observation would
    silently read as "covered" if this were derived from `running_max_f` by
    checking for a non-`None` value. This function re-derives coverage from
    the raw rows instead, so a carried-forward gap is never mistaken for a
    real observation.
    """
    covered: dict[dt.date, set[int]] = defaultdict(set)
    for row in rows:
        hour = local_standard_hour(row.valid_utc, std_utc_offset_hours)
        covered[row.climate_day].add(hour)
    return {day: frozenset(hours) for day, hours in covered.items()}


def is_non_sentinel_final(record: CliRecord | None) -> bool:
    """Is `record` a FINAL CLI product with a real (non-sentinel) `tmax_f`?"""
    if record is None:
        return False
    return (
        record.issuance == "FINAL"
        and record.tmax_sentinel == "NONE"
        and record.tmax_f is not None
    )


@dataclass(frozen=True, slots=True)
class BoundaryCase:
    """One (station, climate-day, hour) evaluation of the boundary statistic.

    `hit` is `True` when the CLI final print landed AT OR ABOVE the next
    whole degree the ASOS running maximum had not yet reached at hour `h`
    (`threshold_f = running_f + 1`) -- the event this whole study measures.
    """

    station: str
    climate_day: dt.date
    hour: int
    running_f: int
    threshold_f: int
    cli_final_f: int
    hit: bool


def build_boundary_cases(
    *,
    station: str,
    running_max_days: Sequence[RunningMaxDay],
    covered_hours_by_day: Mapping[dt.date, frozenset[int]],
    cli_finals: Mapping[dt.date, CliRecord],
    hours: Sequence[int] = STUDY_HOURS,
) -> tuple[BoundaryCase, ...]:
    """Join a station's running-max days against its CLI finals.

    A case is produced for `(station, day, hour)` only when ALL of:

    1. `hour` is one of the evaluated hours (`hours`, default 17..23).
    2. `hour` actually had an ASOS observation that day (`covered_hours_by_day`
       -- never a carried-forward gap; see `hour_coverage`).
    3. The day's CLI final exists and is non-sentinel (`is_non_sentinel_final`).
    4. `running_max_f[hour]` is not `None` (guards the same gap from the
       running-max side, for a day whose FIRST observation is after `hour`).

    A day/hour missing any of the above is silently excluded from the cell,
    not counted as a miss -- this study measures the conditional rate among
    admissible cases, not among all calendar days.
    """
    cases: list[BoundaryCase] = []
    for day in running_max_days:
        final = cli_finals.get(day.climate_day)
        if not is_non_sentinel_final(final):
            continue
        assert final is not None  # narrowed by is_non_sentinel_final
        covered = covered_hours_by_day.get(day.climate_day, frozenset())
        for hour in hours:
            if hour not in covered:
                continue
            running_f = day.running_max_f[hour]
            if running_f is None:
                continue
            threshold_f = running_f + 1
            cli_final_f = final.tmax_f
            assert cli_final_f is not None  # narrowed by is_non_sentinel_final
            cases.append(
                BoundaryCase(
                    station=station,
                    climate_day=day.climate_day,
                    hour=hour,
                    running_f=running_f,
                    threshold_f=threshold_f,
                    cli_final_f=cli_final_f,
                    hit=cli_final_f >= threshold_f,
                )
            )
    return tuple(cases)


def aggregate_cells(
    cases: Iterable[BoundaryCase],
) -> dict[tuple[str, int], tuple[int, int]]:
    """Reduce cases to `{(station, hour): (n, successes)}`."""
    counts: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for case in cases:
        key = (case.station, case.hour)
        bucket = counts[key]
        bucket[0] += 1
        bucket[1] += int(case.hit)
    return {key: (values[0], values[1]) for key, values in counts.items()}


@dataclass(frozen=True, slots=True)
class CellResult:
    """The pre-registered verdict for one `(station, hour)` cell."""

    station: str
    hour: int
    n: int
    successes: int
    rate: float
    wilson_lower: float
    wilson_lower_bonferroni: float
    admissible: bool
    passes_primary: bool
    passes_bonferroni: bool

    @property
    def verdict(self) -> str:
        if not self.admissible:
            return "UNDERPOWERED"
        return "PASS" if self.passes_primary else "FAIL"


@dataclass(frozen=True, slots=True)
class StationResult:
    """One station's contribution: its cases and the CLI-load drop counter."""

    station: str
    cases: tuple[BoundaryCase, ...]
    asos_row_count: int
    complete_day_count: int
    cli_final_count: int
    cli_drops: Mapping[str, int]


def analyse_station(*, cache_dir: Path, spec: SiteSpec) -> StationResult:
    """Read one station's cached ASOS + CLI archives and build its cases.

    Zero network: `read_cached` / `_load_cli_records` (via
    `pmr_climatology_study.iter_cached_cli_products`) both refuse a cache
    miss rather than fetching (`settlement_bucket_gate.read_cached`).
    """
    raw = read_cached(cache_dir, asos_url(spec.iem_asos_id, START_DATE, END_DATE), ".txt")
    from settlement_alignment_study import parse_asos_rows

    rows = parse_asos_rows(raw.decode("utf-8", errors="replace"))
    temperatures, _drops = metar_temperatures(
        city=spec.city, rows=rows, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    in_window = tuple(t for t in temperatures if START_DATE <= t.climate_day <= END_DATE)

    running_days = build_running_max_days(
        city=spec.city,
        temperatures=in_window,
        std_utc_offset_hours=spec.std_utc_offset_hours,
    )
    coverage = hour_coverage(in_window, std_utc_offset_hours=spec.std_utc_offset_hours)

    finals, _every, cli_drops = _load_cli_records(
        cache_dir=cache_dir, spec=spec, start=START_DATE, end=END_DATE
    )

    cases = build_boundary_cases(
        station=spec.city,
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
    )

    return StationResult(
        station=spec.city,
        cases=cases,
        asos_row_count=len(in_window),
        complete_day_count=len(running_days),
        cli_final_count=len(finals),
        cli_drops=dict(cli_drops),
    )


def build_report(
    results: Sequence[StationResult], *, generated_at: dt.datetime, cache_dir: Path
) -> str:
    """Render the pre-registered per-cell table and verdict as markdown."""
    all_cases = tuple(case for result in results for case in result.cases)
    counts = aggregate_cells(all_cases)

    cells: list[CellResult] = []
    for result in results:
        for hour in STUDY_HOURS:
            n, successes = counts.get((result.station, hour), (0, 0))
            cells.append(
                cell_verdict(station=result.station, hour=hour, n=n, successes=successes)
            )

    admissible_passes = [c for c in cells if c.admissible and c.passes_primary]
    bonferroni_survivors = [c for c in admissible_passes if c.passes_bonferroni]
    all_underpowered = all(not c.admissible for c in cells)

    if bonferroni_survivors:
        verdict = "GO"
    elif all_underpowered or admissible_passes and not bonferroni_survivors:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "NO-GO"

    lines: list[str] = []
    add = lines.append
    add("# CLI-basis boundary upper-tail — measured (2026-09-02T04:47:37Z)")
    add("")
    add(
        f"Generated {generated_at.isoformat()} from "
        "`scripts/analysis/cli_basis_boundary_study.py`, pre-registered in "
        "`scripts/analysis/pre_registration_2026-09-02T044737Z.md`."
    )
    add(f"Archive cache: `{cache_dir}` (zero network; cache misses are refused).")
    add(f"Corpus window: {START_DATE.isoformat()} .. {END_DATE.isoformat()}.")
    add("")
    add("## Pre-registered bar")
    add("")
    add(
        "PASS bar: Wilson 95% lower bound >= **0.06285** "
        "(ask 0.05 + theta*p*(1-p) at p=0.05, theta=0.06 -> 0.00285, "
        "+ one 0.01 tick buffer)."
    )
    add(f"Admissibility: n >= {MIN_ADMISSIBLE_N} station-days, else UNDERPOWERED.")
    add(
        f"Bonferroni corroboration z = {BONFERRONI_Z:.4f} "
        "(two-sided 95%/35 cells)."
    )
    add("")
    add("## Per-cell results")
    add("")
    add(
        "| station | hour | n | rate | Wilson lower | Wilson lower (Bonferroni) "
        "| verdict |"
    )
    add("|---|---:|---:|---:|---:|---:|---|")
    for cell in cells:
        add(
            f"| {cell.station} | {cell.hour} | {cell.n} | {cell.rate:.4%} "
            f"| {cell.wilson_lower:.4%} | {cell.wilson_lower_bonferroni:.4%} "
            f"| {cell.verdict} |"
        )
    add("")
    add("## Verdict")
    add("")
    add(f"**{verdict}**")
    add("")
    add(
        f"Admissible-and-PASS cells: {len(admissible_passes)}. "
        f"Of those, Bonferroni-corroborated: {len(bonferroni_survivors)}."
    )
    return "\n".join(lines) + "\n"


def cell_verdict(*, station: str, hour: int, n: int, successes: int) -> CellResult:
    """Apply the pre-registered bar, power rule and Bonferroni check to one cell."""
    if n < 0 or successes < 0 or successes > n:
        raise ValueError(f"invalid cell counts: n={n} successes={successes}")
    rate = successes / n if n else 0.0
    wilson_lower = wilson_lower_bound(successes, n)
    wilson_lower_bonferroni = wilson_lower_bound(successes, n, z=BONFERRONI_Z)
    admissible = n >= MIN_ADMISSIBLE_N
    passes_primary = admissible and wilson_lower >= PRIMARY_BAR
    passes_bonferroni = admissible and wilson_lower_bonferroni >= PRIMARY_BAR
    return CellResult(
        station=station,
        hour=hour,
        n=n,
        successes=successes,
        rate=rate,
        wilson_lower=wilson_lower,
        wilson_lower_bonferroni=wilson_lower_bonferroni,
        admissible=admissible,
        passes_primary=passes_primary,
        passes_bonferroni=passes_bonferroni,
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=str(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    sites = load_sites()

    results: list[StationResult] = []
    for spec in sorted(sites, key=lambda site: site.city):
        print(f"[cli-basis] {spec.city}: reading archive ...", file=sys.stderr, flush=True)
        results.append(analyse_station(cache_dir=cache_dir, spec=spec))
        print(
            f"[cli-basis] {spec.city}: {results[-1].asos_row_count} ASOS rows, "
            f"{results[-1].cli_final_count} CLI finals, "
            f"{len(results[-1].cases)} boundary cases",
            file=sys.stderr,
            flush=True,
        )

    report = build_report(
        results, generated_at=dt.datetime.now(tz=dt.UTC).replace(microsecond=0), cache_dir=cache_dir
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[cli-basis] wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
