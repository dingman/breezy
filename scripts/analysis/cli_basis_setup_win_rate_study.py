"""CLI-basis candidate #2 -- archive-side `P(win | setup)` (Item 3).

Pre-registered in `pre_registration_2026-09-02T055741Z.md` -- read that file
first; this module implements exactly the statistic, bar, and power rule
fixed there, in that order, before any outcome was computed.

WHY THIS EXISTS, SEPARATELY FROM THE OFFER-GATE SCAN
--------------------------------------------------------
`cli_basis_offer_gate_scan.py`'s pre-registered `n >= 50` admissible
dense-station-day rule needs ~625 dense station-days at the measured
qualifying-setup rate (~1 in 12) -- about five months at four stations, not
compatible with this programme's timeline. Rather than lower that bar (never
acceptable here), the edge is decomposed into two INDEPENDENTLY estimable
factors:

    EV = P(win | setup) * $1 - ask - fee

This module answers the first factor -- given ASOS headroom sits at 1-or-2,
how often does the CLI final actually reach the strike -- using NO prices and
NO forward tape, so it can run against the full 2021-2025 archive TODAY, at n
in the thousands. It says NOTHING about whether the venue actually OFFERS
that tail cheaply and in size; that is the offer-gate scan's own, unchanged,
still-binding `n >= 50` gate. See the pre-registration's "crucial asymmetry"
section: a PASS here is necessary, never sufficient, for a GO on candidate #2.

NULL HYPOTHESIS, checked before this module was written (L-1, L-11)
---------------------------------------------------------------------
* `pmr_climatology_study.build_running_max_days` / `load_cli_records` /
  `RunningMaxDay` / `CliRecord` -- the running-max fold and CLI-final archive
  loader, reused verbatim via import. NATIVE-EXISTS-AND-REUSED.
* `settlement_alignment_study.load_sites` / `metar_temperatures` /
  `parse_asos_rows` / `asos_url` / `SiteSpec` / `START_DATE` / `END_DATE` --
  registry and ASOS archive access, reused verbatim via import.
  NATIVE-EXISTS-AND-REUSED.
* `settlement_bucket_gate.read_cached` -- the zero-network, cache-miss-
  refuses-loudly reader, reused verbatim via import. NATIVE-EXISTS-AND-
  REUSED.
* `cli_basis_boundary_study.hour_coverage` / `is_non_sentinel_final` -- this
  study's own per-hour true-coverage helper and non-sentinel-final predicate,
  reused verbatim via IMPORT ONLY. `cli_basis_boundary_study.py` ITSELF is
  never modified by this effort -- it already carries its own PASSED,
  pre-registered gate (L-12: widen an exact-set barrier with a new, narrower
  variant, never by relaxing the original in place).
* `k1_cheap_open_settlement.wilson_interval` -- the two-sided Wilson bound,
  reused verbatim via import, matching the offer-gate scan's own choice, so
  this repo does not grow a third disagreeing Wilson implementation.
* `cli_basis_offer_gate_scan.QUALIFYING_HEADROOM` / `CONTAMINATED_STATIONS` --
  the exact `{1, 2}` margin set and the exact NYC-contamination exclusion the
  offer-gate scan already uses, reused verbatim via import so this archive
  statistic can never silently drift from what "setup" means downstream.

* A join generalizing `cli_basis_boundary_study.BoundaryCase` from a FIXED
  `margin=1` restricted to local-standard hours 17-23, to a PARAMETERIZED
  `margin in {1, 2}` with NO hour restriction, pooled across the four dense
  stations -- does NOT exist upstream. GENUINE GAP, built here as a narrow,
  new join re-deriving nothing the pieces above already provide.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_boundary_study import hour_coverage, is_non_sentinel_final
from cli_basis_offer_gate_scan import CONTAMINATED_STATIONS, QUALIFYING_HEADROOM
from k1_cheap_open_settlement import wilson_interval
from pmr_climatology_study import (
    CliRecord,
    RunningMaxDay,
    build_running_max_days,
)
from pmr_climatology_study import load_cli_records as _load_cli_records
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
    "DENSE_STATIONS",
    "MIN_ADMISSIBLE_N",
    "PRIMARY_BAR",
    "QUALIFYING_MARGINS",
    "PooledResult",
    "SetupCase",
    "StationSetupResult",
    "analyse_station",
    "build_setup_cases",
    "main",
    "pool_stations",
    "pooled_verdict",
    "summarize_station",
]

#: Identical derivation to `cli_basis_boundary_study.PRIMARY_BAR` (see the
#: pre-registration): `ask + theta*ask*(1-ask) + tick` at ask=0.05, theta=0.06.
PRIMARY_BAR: Final[float] = 0.06285

#: Mirrors `cli_basis_boundary_study.MIN_ADMISSIBLE_N` -- same floor, same
#: reasoning (an underpowered verdict describes the sample, not the world).
MIN_ADMISSIBLE_N: Final[int] = 100

#: The exact margin set the offer-gate scan treats as one qualifying "setup",
#: reused verbatim so this archive statistic cannot silently mean something
#: different from what the forward-tape half of the gate means.
QUALIFYING_MARGINS: Final[tuple[int, ...]] = tuple(sorted(QUALIFYING_HEADROOM))

#: The four dense stations the offer-gate scan's own kill rule counts --
#: everything in the registry except the contaminated station(s).
DENSE_STATIONS: Final[tuple[str, ...]] = tuple(
    spec.city for spec in load_sites() if spec.city not in CONTAMINATED_STATIONS
)


@dataclass(frozen=True, slots=True)
class SetupCase:
    """One `(station, climate-day, hour, margin)` evaluation.

    `hit` is `True` when the CLI final print landed AT OR ABOVE
    `running_f + margin` -- the archive-side half of the same event the
    offer-gate scan looks for on the forward tape.
    """

    station: str
    climate_day: dt.date
    hour: int
    margin: int
    running_f: int
    threshold_f: int
    cli_final_f: int
    hit: bool


def build_setup_cases(
    *,
    station: str,
    running_max_days: Sequence[RunningMaxDay],
    covered_hours_by_day: Mapping[dt.date, frozenset[int]],
    cli_finals: Mapping[dt.date, CliRecord],
    margins: Sequence[int] = QUALIFYING_MARGINS,
) -> tuple[SetupCase, ...]:
    """Join running-max days against CLI finals, at EVERY covered hour.

    No hour restriction (the offer-gate scan already established that the
    running max has converged well before local-standard hour 17, so a
    restriction would only shrink `n` for no discrimination). A day
    contributes cases only when its CLI final is a real, non-sentinel FINAL
    -- `is_non_sentinel_final`, reused verbatim, so a preliminary or sentinel
    final can never silently count as ground truth.
    """
    cases: list[SetupCase] = []
    for day in running_max_days:
        final = cli_finals.get(day.climate_day)
        if not is_non_sentinel_final(final):
            continue
        assert final is not None and final.tmax_f is not None  # narrowed above
        covered = covered_hours_by_day.get(day.climate_day, frozenset())
        for hour in range(24):
            if hour not in covered:
                continue
            running_f = day.running_max_f[hour]
            if running_f is None:
                continue
            for margin in margins:
                threshold_f = running_f + margin
                cases.append(
                    SetupCase(
                        station=station,
                        climate_day=day.climate_day,
                        hour=hour,
                        margin=margin,
                        running_f=running_f,
                        threshold_f=threshold_f,
                        cli_final_f=final.tmax_f,
                        hit=final.tmax_f >= threshold_f,
                    )
                )
    return tuple(cases)


@dataclass(frozen=True, slots=True)
class StationSetupResult:
    station: str
    n: int
    k: int
    wilson_lower: float
    wilson_upper: float


def summarize_station(cases: Sequence[SetupCase]) -> StationSetupResult:
    """One station's pooled `(n, k, Wilson bounds)` across every margin."""
    n = len(cases)
    k = sum(1 for case in cases if case.hit)
    interval = wilson_interval(k, n)
    lower, upper = interval if interval is not None else (0.0, 1.0)
    station = cases[0].station if cases else ""
    return StationSetupResult(station=station, n=n, k=k, wilson_lower=lower, wilson_upper=upper)


@dataclass(frozen=True, slots=True)
class PooledResult:
    n: int
    k: int
    wilson_lower: float
    wilson_upper: float
    verdict: str


def pooled_verdict(*, n: int, k: int) -> PooledResult:
    """PASS / FAIL / UNDERPOWERED under the pre-registered rule.

    `n` gates BOTH directional verdicts, not just FAIL -- the same
    small-sample discipline `cli_basis_offer_gate_scan.kill_rule_verdict` and
    `k1_cheap_open_settlement.summarize_stratum` already enforce.
    """
    interval = wilson_interval(k, n)
    if interval is None or n < MIN_ADMISSIBLE_N:
        lower, upper = interval if interval is not None else (0.0, 1.0)
        return PooledResult(
            n=n, k=k, wilson_lower=lower, wilson_upper=upper, verdict="UNDERPOWERED"
        )
    lower, upper = interval
    if lower >= PRIMARY_BAR:
        return PooledResult(n=n, k=k, wilson_lower=lower, wilson_upper=upper, verdict="PASS")
    if upper < PRIMARY_BAR:
        return PooledResult(n=n, k=k, wilson_lower=lower, wilson_upper=upper, verdict="FAIL")
    return PooledResult(n=n, k=k, wilson_lower=lower, wilson_upper=upper, verdict="UNDERPOWERED")


def pool_stations(results: Sequence[StationSetupResult]) -> PooledResult:
    total_n = sum(result.n for result in results)
    total_k = sum(result.k for result in results)
    return pooled_verdict(n=total_n, k=total_k)


# ---------------------------------------------------------------------------
# Archive loading -- mirrors `cli_basis_boundary_study.analyse_station`'s
# shape (read-only precedent; that module is never imported for this part)
# ---------------------------------------------------------------------------


def analyse_station(*, cache_dir: Path, spec: SiteSpec) -> StationSetupResult:
    """Read one station's cached ASOS + CLI archives and summarize it.

    Zero network: `read_cached` / `load_cli_records` both refuse a cache miss
    rather than fetching.
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
    finals, _every, _drops2 = _load_cli_records(
        cache_dir=cache_dir, spec=spec, start=START_DATE, end=END_DATE
    )
    cases = build_setup_cases(
        station=spec.city,
        running_max_days=running_days,
        covered_hours_by_day=coverage,
        cli_finals=finals,
    )
    return summarize_station(cases)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir", default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR.as_posix()
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    sites_by_city = {spec.city: spec for spec in load_sites()}

    per_station: list[StationSetupResult] = []
    for city in DENSE_STATIONS:
        spec = sites_by_city[city]
        result = analyse_station(cache_dir=cache_dir, spec=spec)
        per_station.append(result)
        print(
            f"[setup-win-rate] {city}: n={result.n} k={result.k} "
            f"wilson_lower={result.wilson_lower:.4f} wilson_upper={result.wilson_upper:.4f}"
        )

    pooled = pool_stations(per_station)
    print(
        f"[setup-win-rate] POOLED: n={pooled.n} k={pooled.k} "
        f"wilson_lower={pooled.wilson_lower:.4f} wilson_upper={pooled.wilson_upper:.4f} "
        f"verdict={pooled.verdict}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
