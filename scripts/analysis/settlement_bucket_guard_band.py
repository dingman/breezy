"""Post-hoc exploratory guard-band sweep for the settlement bucket gate.

This script is cache-only. It reuses the original bucket-gate loading, parsing,
validation and bucket helpers, and never calls Polymarket or writes Breezy
runtime state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from settlement_bucket_gate import (
    BUCKET_WIDTH_F,
    END_DATE,
    MIN_CITY_DAYS,
    MIN_TOTAL_DAYS,
    PASS_WILSON_LOWER,
    PHASES,
    START_DATE,
    VENUE_RAW_DIR,
    AgreementStats,
    DailyComparison,
    PhaseCase,
    bucket_id,
    derive_venue_grammar,
    format_rate,
    grammar_markdown,
    load_daily_comparisons,
    load_sites,
    load_validation_labels,
    summarize,
    verdict,
)

DEFAULT_CACHE_DIR: Final[Path] = Path("/tmp/breezy-settlement-alignment-cache")
DEFAULT_OUTPUT: Final[Path] = Path(
    "docs/evidence/settlement_bucket_guard_band_2026-08-26.md"
)
PREREGISTRATION_PATH: Final[Path] = Path(
    "docs/evidence/settlement_bucket_guard_band_prereg_2026-08-26.md"
)
SOURCE_BUCKET_GATE_PATH: Final[Path] = Path(
    "docs/evidence/settlement_bucket_gate_2026-08-25.md"
)
SOURCE_DIAGNOSIS_PATH: Final[Path] = Path(
    "docs/evidence/settlement_alignment_diagnosis_2026-08-25.md"
)
GUARD_BANDS: Final[tuple[float, ...]] = (0.0, 0.25, 0.5, 0.75, 1.0)
THRESHOLD_CASES_PER_CITY_DAY: Final[int] = 4


@dataclass(frozen=True, slots=True)
class GuardedBucketCase:
    city: str
    climate_day: dt.date
    phase: float
    guard_band_f: float
    cli_tmax_f: int
    metar_rounded_max_f: int
    metar_unrounded_max_f: float
    cli_bucket: int
    metar_bucket: int
    metar_edge_distance_f: float

    @property
    def agreed(self) -> bool:
        return self.cli_bucket == self.metar_bucket

    @property
    def miss_direction(self) -> str:
        if self.agreed:
            return "agreement"
        if self.metar_bucket < self.cli_bucket:
            return "METAR below CLI"
        return "METAR above CLI"


@dataclass(frozen=True, slots=True)
class RetentionStats:
    retained_cases: int
    original_cases: int
    retained_fraction: float
    retained_city_days: int
    original_city_days: int
    retained_city_day_fraction: float
    retained_threshold_cases: int
    original_threshold_cases: int
    retained_threshold_case_fraction: float


def metar_edge_distance(value_f: float, phase: float) -> float:
    residual = (value_f - phase) % BUCKET_WIDTH_F
    return round(min(residual, BUCKET_WIDTH_F - residual), 10)


def retained_by_guard(*, edge_distance_f: float, guard_band_f: float) -> bool:
    if guard_band_f == 0.0:
        return True
    return edge_distance_f > guard_band_f


def guarded_cases(comparisons: Iterable[DailyComparison]) -> tuple[GuardedBucketCase, ...]:
    cases: list[GuardedBucketCase] = []
    for comparison in comparisons:
        for phase in PHASES:
            distance = metar_edge_distance(comparison.metar_unrounded_max_f, phase)
            for guard_band in GUARD_BANDS:
                if not retained_by_guard(
                    edge_distance_f=distance,
                    guard_band_f=guard_band,
                ):
                    continue
                cases.append(
                    GuardedBucketCase(
                        city=comparison.city,
                        climate_day=comparison.climate_day,
                        phase=phase,
                        guard_band_f=guard_band,
                        cli_tmax_f=comparison.cli_tmax_f,
                        metar_rounded_max_f=comparison.metar_rounded_max_f,
                        metar_unrounded_max_f=comparison.metar_unrounded_max_f,
                        cli_bucket=bucket_id(comparison.cli_tmax_f, phase),
                        metar_bucket=bucket_id(comparison.metar_rounded_max_f, phase),
                        metar_edge_distance_f=distance,
                    )
                )
    return tuple(cases)


def original_phase_cases(comparisons: Iterable[DailyComparison]) -> tuple[PhaseCase, ...]:
    cases: list[PhaseCase] = []
    for comparison in comparisons:
        for phase in PHASES:
            cases.append(
                PhaseCase(
                    city=comparison.city,
                    climate_day=comparison.climate_day,
                    phase=phase,
                    cli_tmax_f=comparison.cli_tmax_f,
                    metar_rounded_max_f=comparison.metar_rounded_max_f,
                    cli_bucket=bucket_id(comparison.cli_tmax_f, phase),
                    metar_bucket=bucket_id(comparison.metar_rounded_max_f, phase),
                    edge_distance_f=metar_edge_distance(
                        comparison.metar_unrounded_max_f,
                        phase,
                    ),
                )
            )
    return tuple(cases)


def stats_for_guarded(cases: Sequence[GuardedBucketCase]) -> AgreementStats:
    return summarize(cases)


def retention_stats(
    *,
    retained: Sequence[GuardedBucketCase],
    original: Sequence[PhaseCase],
) -> RetentionStats:
    retained_days = {(case.city, case.climate_day) for case in retained}
    original_days = {(case.city, case.climate_day) for case in original}
    retained_count = len(retained)
    original_count = len(original)
    retained_city_days = len(retained_days)
    original_city_days = len(original_days)
    retained_threshold_cases = retained_city_days * THRESHOLD_CASES_PER_CITY_DAY
    original_threshold_cases = original_city_days * THRESHOLD_CASES_PER_CITY_DAY
    return RetentionStats(
        retained_cases=retained_count,
        original_cases=original_count,
        retained_fraction=retained_count / original_count if original_count else 0.0,
        retained_city_days=retained_city_days,
        original_city_days=original_city_days,
        retained_city_day_fraction=(
            retained_city_days / original_city_days if original_city_days else 0.0
        ),
        retained_threshold_cases=retained_threshold_cases,
        original_threshold_cases=original_threshold_cases,
        retained_threshold_case_fraction=(
            retained_threshold_cases / original_threshold_cases
            if original_threshold_cases
            else 0.0
        ),
    )


def percent(value: float) -> str:
    return f"{value * 100.0:.2f}%"


def guard_label(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def group_original_by_phase_city(
    cases: Sequence[PhaseCase],
) -> dict[tuple[float, str | None], list[PhaseCase]]:
    grouped: dict[tuple[float, str | None], list[PhaseCase]] = defaultdict(list)
    for case in cases:
        grouped[(case.phase, case.city)].append(case)
        grouped[(case.phase, None)].append(case)
    return grouped


def group_retained(
    cases: Sequence[GuardedBucketCase],
) -> dict[tuple[float, float, str | None], list[GuardedBucketCase]]:
    grouped: dict[tuple[float, float, str | None], list[GuardedBucketCase]] = defaultdict(list)
    for case in cases:
        grouped[(case.guard_band_f, case.phase, case.city)].append(case)
        grouped[(case.guard_band_f, case.phase, None)].append(case)
    return grouped


def cell_verdict(*, city: str | None, stats: AgreementStats) -> str:
    min_cases = MIN_TOTAL_DAYS if city is None else MIN_CITY_DAYS
    return verdict(stats, min_cases=min_cases)


def guard_passes(
    *,
    guard_band: float,
    cities: Sequence[str],
    retained_by_cell: dict[tuple[float, float, str | None], list[GuardedBucketCase]],
) -> bool:
    for phase in PHASES:
        total_stats = stats_for_guarded(retained_by_cell[(guard_band, phase, None)])
        if cell_verdict(city=None, stats=total_stats) != "PASS":
            return False
        for city in cities:
            city_stats = stats_for_guarded(retained_by_cell[(guard_band, phase, city)])
            if cell_verdict(city=city, stats=city_stats) != "PASS":
                return False
    return True


def worst_phase_retention(
    *,
    guard_band: float,
    original_by_cell: dict[tuple[float, str | None], list[PhaseCase]],
    retained_by_cell: dict[tuple[float, float, str | None], list[GuardedBucketCase]],
) -> RetentionStats:
    phase_stats = [
        retention_stats(
            retained=retained_by_cell[(guard_band, phase, None)],
            original=original_by_cell[(phase, None)],
        )
        for phase in PHASES
    ]
    return min(
        phase_stats,
        key=lambda item: (
            item.retained_city_day_fraction,
            item.retained_threshold_case_fraction,
        ),
    )


def worst_phase_agreement(
    *,
    guard_band: float,
    retained_by_cell: dict[tuple[float, float, str | None], list[GuardedBucketCase]],
) -> tuple[float, AgreementStats]:
    phase_stats = [
        (phase, stats_for_guarded(retained_by_cell[(guard_band, phase, None)]))
        for phase in PHASES
    ]
    return min(phase_stats, key=lambda item: (item[1].wilson_lower, item[1].rate))


def headline_rows(
    *,
    cities: Sequence[str],
    original_by_cell: dict[tuple[float, str | None], list[PhaseCase]],
    retained_by_cell: dict[tuple[float, float, str | None], list[GuardedBucketCase]],
) -> list[str]:
    rows = [
        (
            "| Guard band F | Verdict | Worst phase by Wilson F | Worst-phase "
            "retained city-days | City-day retention | Retained threshold cases | "
            "Threshold-case retention | Worst-phase agreement | Worst-phase Wilson "
            "95% lower | Misses below | Misses above |"
        ),
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for guard_band in GUARD_BANDS:
        passes = guard_passes(
            guard_band=guard_band,
            cities=cities,
            retained_by_cell=retained_by_cell,
        )
        retention = worst_phase_retention(
            guard_band=guard_band,
            original_by_cell=original_by_cell,
            retained_by_cell=retained_by_cell,
        )
        worst_phase, stats = worst_phase_agreement(
            guard_band=guard_band,
            retained_by_cell=retained_by_cell,
        )
        rows.append(
            f"| {guard_label(guard_band)} | {'PASS' if passes else 'FAIL'} | "
            f"{worst_phase:.1f} | "
            f"{retention.retained_city_days}/{retention.original_city_days} | "
            f"{percent(retention.retained_city_day_fraction)} | "
            f"{retention.retained_threshold_cases}/{retention.original_threshold_cases} | "
            f"{percent(retention.retained_threshold_case_fraction)} | "
            f"{format_rate(stats.rate)} | {format_rate(stats.wilson_lower)} | "
            f"{stats.metar_below_cli} | {stats.metar_above_cli} |"
        )
    return rows


def detailed_rows(
    *,
    cities: Sequence[str],
    original_by_cell: dict[tuple[float, str | None], list[PhaseCase]],
    retained_by_cell: dict[tuple[float, float, str | None], list[GuardedBucketCase]],
) -> list[str]:
    rows = [
        (
            "| Guard band F | Phase F | City | Retained cases | Retained fraction | "
            "Retained city-days | City-day fraction | Agreement rate | Wilson 95% "
            "lower | METAR bucket below CLI | METAR bucket above CLI | Verdict |"
        ),
        "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    city_order: tuple[str | None, ...] = (*cities, None)
    for guard_band in GUARD_BANDS:
        for phase in PHASES:
            for city in city_order:
                retained = retained_by_cell[(guard_band, phase, city)]
                original = original_by_cell[(phase, city)]
                stats = stats_for_guarded(retained)
                retention = retention_stats(retained=retained, original=original)
                label = "TOTAL" if city is None else city
                rows.append(
                    f"| {guard_label(guard_band)} | {phase:.1f} | {label} | "
                    f"{retention.retained_cases}/{retention.original_cases} | "
                    f"{format_rate(retention.retained_fraction)} | "
                    f"{retention.retained_city_days}/{retention.original_city_days} | "
                    f"{format_rate(retention.retained_city_day_fraction)} | "
                    f"{format_rate(stats.rate)} | {format_rate(stats.wilson_lower)} | "
                    f"{stats.metar_below_cli} | {stats.metar_above_cli} | "
                    f"{cell_verdict(city=city, stats=stats)} |"
                )
    return rows


def residual_direction_rows(
    *,
    cities: Sequence[str],
    retained_by_cell: dict[tuple[float, float, str | None], list[GuardedBucketCase]],
) -> list[str]:
    rows = [
        (
            "| Guard band F | City | Misses | METAR bucket below CLI | "
            "Below share | METAR bucket above CLI | Above share |"
        ),
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    city_order: tuple[str | None, ...] = (*cities, None)
    for guard_band in GUARD_BANDS:
        for city in city_order:
            combined: list[GuardedBucketCase] = []
            for phase in PHASES:
                combined.extend(retained_by_cell[(guard_band, phase, city)])
            stats = stats_for_guarded(combined)
            misses = stats.cases - stats.agreements
            label = "TOTAL" if city is None else city
            rows.append(
                f"| {guard_label(guard_band)} | {label} | {misses} | "
                f"{stats.metar_below_cli} | "
                f"{format_rate(stats.metar_below_cli / misses if misses else 0.0)} | "
                f"{stats.metar_above_cli} | "
                f"{format_rate(stats.metar_above_cli / misses if misses else 0.0)} |"
            )
    return rows


def markdown_report(
    *,
    command: str,
    catalog_base: Path | None,
    cache_dir: Path,
    validation_status: str,
    validation_checked: int,
    validation_mismatches: int,
    validation_details: Sequence[str],
    comparisons: Sequence[DailyComparison],
    original_cases: Sequence[PhaseCase],
    retained_cases: Sequence[GuardedBucketCase],
    drops: Counter[str],
    parse_errors: Sequence[str],
) -> str:
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    window_days = (END_DATE - START_DATE).days + 1
    cities = tuple(sorted({row.city for row in comparisons}))
    original_by_cell = group_original_by_phase_city(original_cases)
    retained_by_cell = group_retained(retained_cases)
    passing_guards = [
        guard_band
        for guard_band in GUARD_BANDS
        if guard_passes(
            guard_band=guard_band,
            cities=cities,
            retained_by_cell=retained_by_cell,
        )
    ]
    grammar = derive_venue_grammar(VENUE_RAW_DIR)

    lines = [
        "# Settlement Bucket Guard-Band Evidence",
        "",
        f"Generated at: {generated_at.isoformat()}",
        f"Command: `{command}`",
        f"Catalog base: `{catalog_base}`",
        f"Cache dir: `{cache_dir}`",
        f"Pre-registration: `{PREREGISTRATION_PATH}`",
        f"Original failed bucket gate: `{SOURCE_BUCKET_GATE_PATH}`",
        f"Post-hoc diagnosis source: `{SOURCE_DIAGNOSIS_PATH}`",
        "",
        "## Status",
        "",
        (
            "This is an explicitly **post-hoc, exploratory follow-up**. The "
            "0.5 F boundary-distance idea was chosen after seeing the failed "
            "settlement-alignment data. Do not treat any passing guard band in "
            "this report as pre-registered evidence or as a trading license."
        ),
        "",
        "## Methodological Limitation",
        "",
        (
            "The venue's real 2021-2025 historical bucket ladders are not "
            "observed. The captured venue markets are from 2026 only, so this "
            "report reconstructs an infinite two-degree ladder and sweeps phase "
            "offsets. A green result here would still not identify the real "
            "venue ladder anchors, boundary operator, or settlement behavior."
        ),
        "",
        "## Gate Definition",
        "",
        (
            f"- Historical window: {START_DATE.isoformat()} through "
            f"{END_DATE.isoformat()} ({window_days} days)."
        ),
        (
            f"- Guard bands: {', '.join(guard_label(value) for value in GUARD_BANDS)} F."
        ),
        (
            f"- Phase offsets: {PHASES[0]:.1f} F through {PHASES[-1]:.1f} F "
            "in 0.1 F steps."
        ),
        (
            "- Guard distance is measured from the unrounded METAR daily maximum "
            "to the nearest reconstructed 2 F bucket edge for that phase."
        ),
        (
            "- Guard 0.0 F is the no-guard baseline. Positive guards retain only "
            "city-days with distance strictly greater than the guard."
        ),
        (
            f"- Pass threshold: Wilson 95% lower bound strictly greater than "
            f"{PASS_WILSON_LOWER:.4f}."
        ),
        (
            f"- Minimum sample: {MIN_CITY_DAYS} retained city-day cases per city "
            f"and {MIN_TOTAL_DAYS} retained city-day cases total at every phase."
        ),
        "- A guard band passes only if every city and the total pass at every phase.",
        "",
        "## Headline Verdict And Retention Cost",
        "",
    ]

    if validation_status != "passed":
        lines.extend(
            [
                (
                    "The archive-validation bridge did not pass, so no "
                    "guard-band alignment statistics are licensed by this run."
                ),
                "",
            ]
        )
    else:
        if passing_guards:
            passing_text = ", ".join(f"{guard_label(value)} F" for value in passing_guards)
            lines.append(f"Guard bands passing every city at every phase: **{passing_text}**.")
        else:
            lines.append("Guard bands passing every city at every phase: **none**.")
        lines.append("")
        lines.extend(headline_rows(
            cities=cities,
            original_by_cell=original_by_cell,
            retained_by_cell=retained_by_cell,
        ))
        lines.extend(
            [
                "",
                (
                    "Retention is worst-phase total retention. Threshold-case "
                    "retention uses four diagnostic threshold cases per retained "
                    "city-day; because this guard excludes whole city-days, it "
                    "tracks city-day retention one-for-one."
                ),
                "",
                "## Detailed Guard x Phase x City Cells",
                "",
            ]
        )
        lines.extend(detailed_rows(
            cities=cities,
            original_by_cell=original_by_cell,
            retained_by_cell=retained_by_cell,
        ))
        lines.extend(
            [
                "",
                "## Directional Structure Of Residual Misses",
                "",
            ]
        )
        lines.extend(residual_direction_rows(
            cities=cities,
            retained_by_cell=retained_by_cell,
        ))
        lines.extend(
            [
                "",
                "## Eligible City-Days",
                "",
                f"Eligible city-days before phase expansion: {len(comparisons)}",
                "",
                "| City | Eligible city-days |",
                "|---|---:|",
            ]
        )
        city_counts = Counter(row.city for row in comparisons)
        for city in sorted(city_counts):
            lines.append(f"| {city} | {city_counts[city]} |")
        lines.extend(["", *grammar_markdown(grammar)])

    lines.extend(
        [
            "## Archive Validation Bridge",
            "",
            (
                "Note: this study never fetches new archive data over the "
                "network. If the live Breezy catalog has grown past the "
                "already-cached IEM AFOS validation window since the archive "
                "cache was populated, `--catalog-base` is pointed at a "
                "fixed-timestamp snapshot of the live catalog containing only "
                "the records present as of the original bucket-gate cache "
                "capture, so the validation bridge can complete from cache "
                "alone. The snapshot is a strict subset of the live catalog; "
                "it removes no record inconsistently and adds none."
            ),
            "",
            f"Status: **{validation_status}**",
            f"Checked overlapping final records: {validation_checked}",
            f"Mismatches: {validation_mismatches}",
            "",
        ]
    )
    lines.extend(f"- {detail}" for detail in validation_details)
    lines.extend(["", "## Drop Counts", ""])
    if drops:
        lines.extend(f"- {reason}: {count}" for reason, count in sorted(drops.items()))
    else:
        lines.append("- none")
    lines.extend(["", "## Parse Issues", ""])
    if parse_errors:
        lines.extend(f"- {error}" for error in parse_errors[:200])
        if len(parse_errors) > 200:
            lines.append(f"- ... {len(parse_errors) - 200} additional parse issues omitted")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## What This Licenses",
            "",
            (
                "This report licenses only a post-hoc hypothesis about reconstructed "
                "2 F bucket lattices. It does not determine real historical venue "
                "bucket ladders, does not resolve REQ-SETTLE-03, does not remove "
                "the need for `BOUNDARY_UNRESOLVED` observability in "
                "REQ-SETTLE-03a, and does not authorize trading."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_sidecars(
    *, output: Path, command: str, catalog_base: Path | None, cache_dir: Path
) -> None:
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n",
        encoding="utf-8",
    )
    meta = {
        "captured_by": "breezy settlement bucket guard-band analysis script",
        "note": "Digest sidecar for post-hoc exploratory guard-band evidence report.",
        "retrieved_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "sha256": digest,
        "url": "local offline study",
        "command": command,
        "catalog_base": str(catalog_base),
        "cache_dir": str(cache_dir),
        "pre_registration": str(PREREGISTRATION_PATH),
    }
    output.with_suffix(output.suffix + ".meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-base", type=Path, default=os.environ.get("BREEZY_CATALOG_BASE"))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-date", type=dt.date.fromisoformat, default=START_DATE)
    parser.add_argument("--end-date", type=dt.date.fromisoformat, default=END_DATE)
    parser.add_argument(
        "--report-command",
        default=None,
        help="Exact command line to print in the evidence document.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.start_date != START_DATE or args.end_date != END_DATE:
        raise SystemExit("start/end date overrides would violate the follow-up registration")

    sites = load_sites()
    validation_status, checked, mismatches, validation_details = load_validation_labels(
        cache_dir=args.cache_dir,
        sites=sites,
        catalog_base=args.catalog_base,
    )

    drops: Counter[str] = Counter()
    parse_errors: tuple[str, ...] = ()
    comparisons: tuple[DailyComparison, ...] = ()
    baseline_cases: tuple[PhaseCase, ...] = ()
    retained_cases: tuple[GuardedBucketCase, ...] = ()
    if validation_status == "passed":
        comparisons, drops, parse_errors = load_daily_comparisons(
            cache_dir=args.cache_dir,
            sites=sites,
            start=START_DATE,
            end=END_DATE,
        )
        baseline_cases = original_phase_cases(comparisons)
        retained_cases = guarded_cases(comparisons)
    else:
        drop_reason = (
            "validation_unavailable"
            if "unavailable" in validation_status
            else "validation_mismatch"
        )
        drops[drop_reason] = 1

    command = args.report_command or " ".join([sys.executable, *sys.argv])
    report = markdown_report(
        command=command,
        catalog_base=args.catalog_base,
        cache_dir=args.cache_dir,
        validation_status=validation_status,
        validation_checked=checked,
        validation_mismatches=mismatches,
        validation_details=validation_details,
        comparisons=comparisons,
        original_cases=baseline_cases,
        retained_cases=retained_cases,
        drops=drops,
        parse_errors=parse_errors,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    write_sidecars(
        output=args.output,
        command=command,
        catalog_base=args.catalog_base,
        cache_dir=args.cache_dir,
    )
    return 0 if validation_status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
