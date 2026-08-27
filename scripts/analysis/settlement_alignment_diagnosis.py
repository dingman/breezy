"""Cache-only diagnosis for the Phase 2 settlement-alignment failure.

This script reuses ``settlement_alignment_study.py`` case construction and
does not write Breezy runtime state. It intentionally has no network fallback:
if the preregistered study cache is incomplete, the run fails instead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
    resolve_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (
    END_DATE,
    PRIMARY_BREAK_EVEN,
    START_DATE,
    ThresholdCase,
    afos_url,
    asos_url,
    fetch_historical_cases,
    format_stats,
    load_sites,
    parse_asos_rows,
    parse_metar_t_group,
    summarize_cases,
    validate_archive_against_catalog,
    verdict,
    wilson_lower_bound,
)

DEFAULT_CACHE_DIR = DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
DEFAULT_OUTPUT = Path("docs/evidence/settlement_alignment_diagnosis_2026-08-25.md")


class NoNetworkClient:
    def get(self, url: str, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError(f"cache miss would require network access: {url}")


@dataclass(frozen=True, slots=True)
class DailyComparison:
    city: str
    climate_day: dt.date
    cli_tmax_f: int
    rounded_metar_max_f: int
    unrounded_metar_max_f: float

    @property
    def signed_diff_f(self) -> int:
        return self.rounded_metar_max_f - self.cli_tmax_f


@dataclass(frozen=True, slots=True)
class SignedStats:
    city: str
    day_count: int
    mean: float
    median: float
    pstdev: float
    distribution: Counter[int]
    nonzero_count: int
    metar_lt_cli_count: int
    metar_gt_cli_count: int


def cache_path_for_url(cache_dir: Path, url: str, suffix: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}{suffix}"


def assert_cache_complete(cache_dir: Path) -> None:
    missing: list[Path] = []
    for spec in load_sites():
        site_asos_url = asos_url(spec.iem_asos_id, START_DATE, END_DATE)
        path = cache_path_for_url(cache_dir, site_asos_url, ".txt")
        if not path.exists():
            missing.append(path)
        for year in range(START_DATE.year, END_DATE.year + 1):
            chunk_start = dt.date(year, 1, 1)
            chunk_end = dt.date(year, 12, 31)
            cli_url = afos_url(spec.site.cli_location, chunk_start, chunk_end, limit=3_000)
            path = cache_path_for_url(cache_dir, cli_url, ".zip")
            if not path.exists():
                missing.append(path)
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"cache incomplete; refusing network fetch:\n{formatted}")


def unique_daily_comparisons(cases: Sequence[ThresholdCase]) -> tuple[DailyComparison, ...]:
    by_key: dict[tuple[str, dt.date], ThresholdCase] = {}
    for case in cases:
        by_key.setdefault((case.city, case.climate_day), case)
    return tuple(
        DailyComparison(
            city=case.city,
            climate_day=case.climate_day,
            cli_tmax_f=case.cli_tmax_f,
            rounded_metar_max_f=case.rounded_metar_max_f,
            unrounded_metar_max_f=case.unrounded_metar_max_f,
        )
        for case in sorted(by_key.values(), key=lambda row: (row.city, row.climate_day))
    )


def signed_stats(comparisons: Iterable[DailyComparison]) -> dict[str, SignedStats]:
    by_city: dict[str, list[int]] = defaultdict(list)
    for comparison in comparisons:
        by_city[comparison.city].append(comparison.signed_diff_f)
    stats: dict[str, SignedStats] = {}
    for city, diffs in sorted(by_city.items()):
        dist = Counter(diffs)
        nonzero = [diff for diff in diffs if diff != 0]
        stats[city] = SignedStats(
            city=city,
            day_count=len(diffs),
            mean=statistics.mean(diffs),
            median=statistics.median(diffs),
            pstdev=statistics.pstdev(diffs),
            distribution=dist,
            nonzero_count=len(nonzero),
            metar_lt_cli_count=sum(1 for diff in nonzero if diff < 0),
            metar_gt_cli_count=sum(1 for diff in nonzero if diff > 0),
        )
    return stats


def distribution_text(distribution: Counter[int]) -> str:
    return ", ".join(f"{diff}: {distribution[diff]}" for diff in sorted(distribution))


def fraction(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def boundary_distance(case: ThresholdCase) -> float:
    return abs(case.unrounded_metar_max_f - case.threshold_f)


def by_city_cases(cases: Iterable[ThresholdCase]) -> dict[str, list[ThresholdCase]]:
    grouped: dict[str, list[ThresholdCase]] = defaultdict(list)
    for case in cases:
        grouped[case.city].append(case)
    return grouped


def corrected_cases(
    comparisons: Sequence[DailyComparison],
    *,
    corrections: dict[str, int],
) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[bool]] = defaultdict(list)
    for comparison in comparisons:
        correction = corrections.get(comparison.city, 0)
        corrected_projection = comparison.rounded_metar_max_f - correction
        for margin in (0, 1, 2, 3):
            threshold = corrected_projection - margin
            counts[comparison.city].append(comparison.cli_tmax_f >= threshold)
    return {
        city: (sum(city_hits), len(city_hits))
        for city, city_hits in sorted(counts.items())
    }


def station_observation_summary(cache_dir: Path) -> dict[str, dict[str, float | int | str]]:
    rows_by_city: dict[str, dict[str, float | int | str]] = {}
    for spec in load_sites():
        site_asos_url = asos_url(spec.iem_asos_id, START_DATE, END_DATE)
        path = cache_path_for_url(cache_dir, site_asos_url, ".txt")
        rows = parse_asos_rows(path.read_text(encoding="utf-8", errors="replace"))
        day_counts: Counter[str] = Counter()
        t_group_rows = 0
        for row in rows:
            raw = row.get("metar", "")
            if parse_metar_t_group(raw) is None:
                continue
            t_group_rows += 1
            valid = row.get("valid", "")[:10]
            if valid:
                day_counts[valid] += 1
        counts = tuple(day_counts.values())
        rows_by_city[spec.city] = {
            "icao": spec.site.icao,
            "cli_location": spec.site.cli_location,
            "iem_asos_id": spec.iem_asos_id,
            "raw_rows": len(rows),
            "t_group_rows": t_group_rows,
            "utc_days_with_t_group": len(day_counts),
            "mean_t_group_rows_per_utc_day": statistics.mean(counts) if counts else 0.0,
            "median_t_group_rows_per_utc_day": statistics.median(counts) if counts else 0.0,
        }
    return rows_by_city


def markdown_report(
    *,
    command: str,
    catalog_base: Path | None,
    cache_dir: Path,
    validation_status: str,
    validation_checked: int,
    validation_mismatches: int,
    validation_details: Sequence[str],
    cases: Sequence[ThresholdCase],
    drops: Counter[str],
    parse_errors: Sequence[str],
    comparisons: Sequence[DailyComparison],
) -> str:
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    city_cases = by_city_cases(cases)
    city_days: dict[str, set[dt.date]] = defaultdict(set)
    for comparison in comparisons:
        city_days[comparison.city].add(comparison.climate_day)
    total_window_days = (END_DATE - START_DATE).days + 1
    stats_by_city = signed_stats(comparisons)
    observation_summary = station_observation_summary(cache_dir)

    failing_airport_cities = ("LAX", "MDW", "MIA", "SFO")
    airport_positive = [
        fraction(stats_by_city[city].metar_gt_cli_count, stats_by_city[city].nonzero_count)
        for city in failing_airport_cities
    ]
    systematic_airport_bias = all(
        stats_by_city[city].median >= 1.0
        and stats_by_city[city].mean >= 0.45
        and share >= 0.95
        for city, share in zip(failing_airport_cities, airport_positive, strict=True)
    )
    history_line = (
        f"Historical window: {START_DATE.isoformat()} through "
        f"{END_DATE.isoformat()} ({total_window_days} days)"
    )
    signed_error_note = (
        "Signed error is `rounded_metar_max_f - cli_tmax_f`, one row per unique "
        "city-day. The threshold-case count is exactly four times the city-day "
        "count; repeating by threshold does not change the mean, median, or stddev."
    )
    signed_header = (
        "| City | City-days | Mean signed F | Median | Stddev | Nonzero days | "
        "METAR < CLI | METAR > CLI |"
    )
    station_header = (
        "| City | ICAO | CLI location | IEM ASOS id | Evaluated days | "
        "Window coverage | Raw METAR rows | T-group rows | UTC days with T-group | "
        "Mean T-group rows/UTC day |"
    )
    nyc_interpretation = (
        "NYC does not pass because it retained far more days: its evaluated-day "
        "coverage is comparable to the airport sites. The validation bridge also "
        "found no wrong-station catalog records for any city and no checked "
        "catalog/archive mismatches, so the local data does not show a KNYC-specific "
        "CLI join artifact. What the local data does show is a strong station-class "
        "correlation in sign: KNYC's nonzero signed errors are almost entirely "
        "METAR < CLI, while the airport ASOS cities have hundreds of METAR > CLI "
        "days that can create false-positive threshold hits near the boundary."
    )
    unresolved_station_question = (
        "This local evidence cannot distinguish a genuine instrumentation/settlement-"
        "source difference from an IEM METAR archive artifact for airport ASOS "
        "stations. Distinguishing those would require an independent official daily "
        "max/continuous ASOS or LCD-style source for the same station-days, or raw "
        "station products showing the exact observation stream used to populate each "
        "CLI maximum."
    )
    boundary_note = (
        "Distance is `abs(unrounded_metar_max_f - threshold_f)` for each threshold "
        "case. Retained fraction is reported against all evaluated city-threshold "
        "cases; city-days with at least one retained threshold are also shown because "
        "every evaluated day can still have a far-from-boundary threshold."
    )
    boundary_header = (
        "| Cut | City | Retained cases | Case fraction | City-days retained | "
        "City-day fraction | Agreement | Wilson 95% lower | Verdict |"
    )
    posthoc_note = (
        "POST-HOC, NOT A PASSING OF THE PREREGISTERED GATE. The correction below "
        "subtracts each city's observed median signed error from its rounded METAR "
        "projection before rebuilding the four threshold cases. This uses the answer "
        "variable and is included only to size the apparent bias."
    )
    posthoc_header = (
        "| City | Median correction F | Cases | Matches | Agreement | "
        "Wilson 95% lower | Verdict |"
    )
    bias_conclusion = (
        "The four failed airport ASOS cities show a systematic positive METAR-vs-CLI "
        "bias: nonzero errors are almost entirely METAR > CLI, with median signed "
        "error +1 F. NYC does not show that pattern."
        if systematic_airport_bias
        else "The failed airport sites do not show a well-supported scalar bias correction: "
        "their means are close to zero, medians are 0 F, and nonzero signs are mixed. "
        "The gate failures come from positive METAR-over-CLI days near the boundary, "
        "while negative METAR-under-CLI days are conservative for these threshold cases."
    )

    lines = [
        "# Settlement-Alignment Failure Diagnosis",
        "",
        f"Generated at: {generated_at.isoformat()}",
        f"Command: `{command}`",
        f"Catalog base: `{catalog_base}`",
        f"Cache dir: `{cache_dir}`",
        history_line,
        f"Primary gate: Wilson 95% lower bound > {PRIMARY_BREAK_EVEN:.4f}",
        "",
        "## Data Integrity Checks",
        "",
        f"- Archive-validation bridge status: **{validation_status}**",
        f"- Checked overlapping final Breezy catalog records: {validation_checked}",
        f"- Validation mismatches: {validation_mismatches}",
        f"- Parsed threshold cases: {len(cases)}",
        f"- Parsed unique city-days: {len(comparisons)}",
        f"- Parse issues: {len(parse_errors)}",
        "",
    ]
    for detail in validation_details:
        lines.append(f"- {detail}")

    lines.extend(
        [
            "",
            "## 1. Signed Error Structure",
            "",
            signed_error_note,
            "",
            signed_header,
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for city in sorted(stats_by_city):
        stat = stats_by_city[city]
        lines.append(
            f"| {city} | {stat.day_count} | {stat.mean:.6f} | {stat.median:.1f} | "
            f"{stat.pstdev:.6f} | {stat.nonzero_count} | "
            f"{stat.metar_lt_cli_count} "
            f"({fraction(stat.metar_lt_cli_count, stat.nonzero_count):.6f}) | "
            f"{stat.metar_gt_cli_count} "
            f"({fraction(stat.metar_gt_cli_count, stat.nonzero_count):.6f}) |"
        )

    lines.extend(
        [
            "",
            "Full signed-difference distributions, in whole Fahrenheit degrees:",
            "",
        ]
    )
    for city in sorted(stats_by_city):
        lines.append(f"- {city}: {distribution_text(stats_by_city[city].distribution)}")
    lines.extend(["", f"Conclusion: {bias_conclusion}", ""])

    lines.extend(
        [
            "## 2. NYC Versus Airport ASOS Cities",
            "",
            station_header,
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for city in sorted(city_days):
        obs = observation_summary[city]
        lines.append(
            f"| {city} | {obs['icao']} | {obs['cli_location']} | {obs['iem_asos_id']} | "
            f"{len(city_days[city])} | {fraction(len(city_days[city]), total_window_days):.6f} | "
            f"{obs['raw_rows']} | {obs['t_group_rows']} | {obs['utc_days_with_t_group']} | "
            f"{obs['mean_t_group_rows_per_utc_day']:.2f} |"
        )
    lines.extend(["", "Study drop counts:", ""])
    for reason, count in sorted(drops.items()):
        lines.append(f"- {reason}: {count}")
    lines.extend(
        [
            "",
            nyc_interpretation,
            "",
            unresolved_station_question,
            "",
        ]
    )

    lines.extend(
        [
            "## 3. Boundary-Distance Restricted Gates",
            "",
            boundary_note,
            "",
            boundary_header,
            "|---:|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for cut in (0.5, 1.0, 2.0):
        for city in sorted(city_cases):
            all_city_cases = city_cases[city]
            kept = [case for case in all_city_cases if boundary_distance(case) > cut]
            kept_days = {case.climate_day for case in kept}
            stats = summarize_cases(kept)
            pass_fail = "PASSED" if stats.wilson_95_lower > PRIMARY_BREAK_EVEN else "FAILED"
            lines.append(
                f"| >{cut:.1f} F | {city} | {stats.sample_count}/{len(all_city_cases)} | "
                f"{fraction(stats.sample_count, len(all_city_cases)):.6f} | "
                f"{len(kept_days)}/{len(city_days[city])} | "
                f"{fraction(len(kept_days), len(city_days[city])):.6f} | "
                f"{stats.hit_rate:.6f} | {stats.wilson_95_lower:.6f} | {pass_fail} |"
            )
    lines.append("")

    if systematic_airport_bias:
        corrections = {
            city: int(stats_by_city[city].median)
            for city in stats_by_city
        }
        posthoc = corrected_cases(comparisons, corrections=corrections)
        lines.extend(
            [
                "## Post-Hoc Bias Correction",
                "",
                posthoc_note,
                "",
                posthoc_header,
                "|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for city in sorted(posthoc):
            hits, total = posthoc[city]
            lb = wilson_lower_bound(hits, total)
            pass_fail = "PASSED" if lb > PRIMARY_BREAK_EVEN else "FAILED"
            lines.append(
                f"| {city} | {corrections[city]} | {total} | {hits} | "
                f"{fraction(hits, total):.6f} | {lb:.6f} | {pass_fail} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Original Unrestricted Gate",
            "",
            "| City | Cases | Matches | Mismatches | Agreement rate | Wilson 95% lower | Verdict |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for city in sorted(city_cases):
        stats = summarize_cases(city_cases[city])
        lines.append(
            f"| {city} | {format_stats(stats)} | "
            f"{verdict(stats, generated_at=generated_at)} |"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-base", type=Path, default=os.environ.get("BREEZY_CATALOG_BASE"))
    parser.add_argument(
        "--cache-dir",
        type=resolve_settlement_alignment_cache_dir,
        default=DEFAULT_CACHE_DIR,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    assert_cache_complete(cache_dir)
    sites = load_sites()
    client = NoNetworkClient()
    validation, _overlap_labels = validate_archive_against_catalog(
        client=client,
        cache_dir=cache_dir,
        delay_s=0.0,
        catalog_base=args.catalog_base,
        sites=sites,
    )
    if validation.status != "passed":
        raise SystemExit(f"archive-validation bridge did not pass: {validation.status}")
    cases, drops, parse_errors = fetch_historical_cases(
        client=client,
        cache_dir=cache_dir,
        delay_s=0.0,
        sites=sites,
        start=START_DATE,
        end=END_DATE,
    )
    comparisons = unique_daily_comparisons(cases)
    command = " ".join(["python", *sys.argv])
    report = markdown_report(
        command=command,
        catalog_base=args.catalog_base,
        cache_dir=cache_dir,
        validation_status=validation.status,
        validation_checked=validation.checked_count,
        validation_mismatches=validation.mismatch_count,
        validation_details=validation.details,
        cases=cases,
        drops=drops,
        parse_errors=parse_errors,
        comparisons=comparisons,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
