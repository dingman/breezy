"""CLI-basis candidate #2 -- archive-side adverse-selection proxy (Item 3, Task 2).

Pre-registered in ``pre_registration_2026-09-02T062000Z.md`` -- read that
file first; this module implements exactly the statistic and reporting rule
fixed there, in that order, before any per-season outcome was computed.

WHAT THIS ANSWERS, AND WHAT IT DOES NOT
----------------------------------------
The corrected headline
(``docs/evidence/cli_basis_setup_win_rate_corrected_2026-09-02T061722Z.md``)
reports ONE pooled `P(win | setup)` per station, over every admissible-hour
setup in five years of archive. That number is an UNCONDITIONAL average over
whatever setups happen to occur. Breezy would only ever TRADE the subset the
venue actually offers cheaply -- and if the venue offers cheaply exactly on
the days its true basis-crossing probability is already low (for reasons a
counterparty can infer without special access), the traded population's true
win rate could sit well below the archive's unconditional figure, even
though no single archived fact is wrong.

No order-book history exists before 2026-09-01 (verified, hard constraint),
so the DIRECT test -- `P(win | setup, offered <= $0.05)` -- cannot be run
from the archive at all; see the module's `main()` docstring section and the
task's write-up for what a live measurement of that would require.

What CAN be checked from the archive alone is whether the admissible-hour
setup population is HOMOGENEOUS or whether it decomposes into
sub-populations with materially different rates along an axis a
counterparty could plausibly use WITHOUT price history -- season is the
cheapest such axis (a counterparty always knows the calendar). This module
answers exactly that, and only that: a homogeneous finding here narrows one
plausible channel; it is not proof adverse selection is absent, and a
heterogeneous finding is not proof the venue actually exploits it (no price
data exists to confirm mechanism, only to make the risk plausible or not).

NULL HYPOTHESIS, checked before this module was written (L-1, L-11)
---------------------------------------------------------------------
* ``pmr_climatology_study.season_for`` -- the repo's only per-day season
  classifier (``_SEASON_BY_MONTH``: DJF/MAM/JJA/SON), reused verbatim via
  import. NATIVE-EXISTS-AND-REUSED.
* ``cli_basis_setup_win_rate_study.SetupCase`` / ``build_setup_cases`` /
  ``DENSE_STATIONS`` -- reused verbatim via import. NATIVE-EXISTS-AND-REUSED.
* ``cli_basis_hourly_profile_study.filter_cases_by_admissible_hours`` /
  ``is_admissible_hour`` -- reused verbatim via import, so this test measures
  heterogeneity WITHIN the exact population the corrected headline already
  treats as one pool (local-standard hour >= 17), never a different one.
  NATIVE-EXISTS-AND-REUSED.
* ``k1_cheap_open_settlement.wilson_interval`` -- reused verbatim via import,
  matching every other study in this family. NATIVE-EXISTS-AND-REUSED.

GENUINE GAP built here: ``season_setup_counts`` -- a per-``(station,
season)`` aggregation of ``SetupCase``. No existing aggregator in this
family groups by season; every one of them groups by ``(station, hour)``.
``season_cell_verdict`` applies the shared Wilson bound and reports whether
a season's interval EXCLUDES the pooled point estimate, mirroring
``cli_basis_boundary_study.cell_verdict``'s shape without its PASS/FAIL
break-even machinery (this is a heterogeneity check, not a tradeability
gate -- see the pre-registration's "Bar" section for why no PASS/FAIL is
registered here).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_hourly_profile_study import analyse_station_hourly
from cli_basis_setup_win_rate_study import (
    DENSE_STATIONS,
    SetupCase,
    pool_stations,
    summarize_station,
)
from k1_cheap_open_settlement import wilson_interval
from pmr_climatology_study import season_for
from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import load_sites

__all__ = [
    "DENSE_STATIONS",
    "MIN_ADMISSIBLE_N",
    "SeasonCell",
    "main",
    "season_cell_verdict",
    "season_setup_counts",
]

#: Same floor as every other cell in this study family -- an underpowered
#: verdict describes the sample, not the world.
MIN_ADMISSIBLE_N: Final[int] = 100


def season_setup_counts(cases: Iterable[SetupCase]) -> dict[tuple[str, str], tuple[int, int]]:
    """Reduce admissible `SetupCase`s to `{(station, season): (n, k)}`.

    `season_for` (reused verbatim) is applied to `case.climate_day` -- the
    same date every other cell in this family already carries, so this adds
    no new join, only a new grouping key.
    """
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for case in cases:
        key = (case.station, season_for(case.climate_day))
        bucket = counts[key]
        bucket[0] += 1
        bucket[1] += int(case.hit)
    return {key: (values[0], values[1]) for key, values in counts.items()}


@dataclass(frozen=True, slots=True)
class SeasonCell:
    """One `(station, season)` cell's rate against the pooled point estimate."""

    station: str
    season: str
    n: int
    k: int
    rate: float
    wilson_lower: float
    wilson_upper: float
    pooled_rate: float
    admissible: bool

    @property
    def verdict(self) -> str:
        if not self.admissible:
            return "UNDERPOWERED"
        if self.wilson_lower <= self.pooled_rate <= self.wilson_upper:
            return "MATERIALLY HOMOGENEOUS"
        return "MATERIALLY HETEROGENEOUS"


def season_cell_verdict(
    *, station: str, season: str, n: int, k: int, pooled_rate: float
) -> SeasonCell:
    """Apply the shared Wilson bound; flag whether it excludes `pooled_rate`."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid cell counts: n={n} k={k}")
    interval = wilson_interval(k, n)
    lower, upper = interval if interval is not None else (0.0, 1.0)
    rate = k / n if n else 0.0
    admissible = n >= MIN_ADMISSIBLE_N
    return SeasonCell(
        station=station,
        season=season,
        n=n,
        k=k,
        rate=rate,
        wilson_lower=lower,
        wilson_upper=upper,
        pooled_rate=pooled_rate,
        admissible=admissible,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR.as_posix())
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Compute the corrected pooled rate, then decompose it by season.

    Reuses `analyse_station_hourly`'s `admissible_cases` output verbatim --
    the exact same admissible-hour-filtered `SetupCase`s the corrected
    headline (`cli_basis_hourly_profile_study.main`) pools -- so the pooled
    point estimate this module compares seasons against is the SAME number,
    not a re-derived one that could silently drift from it.
    """
    args = _parse_args(argv)
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    sites_by_city = {spec.city: spec for spec in load_sites()}

    per_station_admissible: dict[str, tuple[SetupCase, ...]] = {}
    for city in DENSE_STATIONS:
        spec = sites_by_city[city]
        result = analyse_station_hourly(cache_dir=cache_dir, spec=spec)
        per_station_admissible[city] = result.admissible_cases

    all_admissible = tuple(
        case for cases in per_station_admissible.values() for case in cases
    )
    pooled = pool_stations([summarize_station(cases) for cases in per_station_admissible.values()])
    pooled_rate = pooled.k / pooled.n if pooled.n else 0.0
    print(
        f"[adverse-selection] pooled admissible-hour rate: {pooled_rate:.4f} "
        f"(n={pooled.n}, k={pooled.k})"
    )

    season_counts = season_setup_counts(all_admissible)
    print("| station | season | n | share | rate | Wilson lower | Wilson upper | verdict |")
    print("|---|---|---:|---:|---:|---:|---:|---|")
    for city in DENSE_STATIONS:
        station_total = sum(1 for _ in per_station_admissible[city]) or 1
        for season in ("DJF", "MAM", "JJA", "SON"):
            n, k = season_counts.get((city, season), (0, 0))
            cell = season_cell_verdict(
                station=city, season=season, n=n, k=k, pooled_rate=pooled_rate
            )
            share = n / station_total
            print(
                f"| {city} | {season} | {n} | {share:.2%} | {cell.rate:.4%} "
                f"| {cell.wilson_lower:.4%} | {cell.wilson_upper:.4%} | {cell.verdict} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
