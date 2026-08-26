"""Measure NWS CLI preliminary-to-final tmax revision rates.

This script is deliberately outside ``src/breezy``. It reads Breezy registry and
catalog primitives, but never writes to Breezy's live Parquet catalog or state
DB. It opens existing station catalog roots directly instead of using
``open_station_catalog`` because that helper creates missing directories.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shlex
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyarrow as pa
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from settlement_alignment_study import wilson_lower_bound

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.catalog import read_climate_days, station_catalog_path
from breezy.registry.sites import default_registry

VENUE: Final[str] = "polymarket_us"
DEFAULT_CATALOG_BASE: Final[Path] = Path("/home/jon/.local/share/breezy/catalog")
DEFAULT_OUTPUT_PATH: Final[Path] = Path(
    "docs/evidence/preliminary_final_revision_2026-08-26.md",
)
PREREGISTRATION_PATH: Final[Path] = Path(
    "docs/evidence/preliminary_final_revision_prereg_2026-08-26.md",
)
SAMPLE_FLOOR_PER_SITE: Final[int] = 90
WILSON_UPPER_PASS_THRESHOLD: Final[float] = 0.05
Z_95: Final[float] = 1.959963984540054


@dataclass(frozen=True, slots=True)
class SiteSpec:
    city: str
    cli_location: str


@dataclass(frozen=True, slots=True)
class RevisionPair:
    city: str
    climate_day: dt.date
    preliminary_tmax_f: int
    final_tmax_f: int
    revised: bool
    preliminary_ts_init: int
    first_final_ts_init: int
    final_ts_init: int
    preliminary_issuance_time_ns: int
    first_final_issuance_time_ns: int
    final_issuance_time_ns: int
    preliminary_revision_seq: int
    final_revision_seq: int
    preliminary_raw_sha256: str
    final_raw_sha256: str


@dataclass(frozen=True, slots=True)
class SiteResult:
    city: str
    cli_location: str
    catalog_root: Path
    catalog_root_exists: bool
    climate_records: int
    expected_station_records: int
    wrong_station_records: int
    preliminary_records: int
    final_records: int
    first_climate_day: dt.date | None
    last_climate_day: dt.date | None
    pairs: tuple[RevisionPair, ...]
    drops: Counter[str]
    read_error: str | None = None


@dataclass(frozen=True, slots=True)
class RateStats:
    sample_count: int
    revision_count: int
    revision_rate: float | None
    wilson_95_lower: float | None
    wilson_95_upper: float | None
    verdict: str


def load_sites() -> tuple[SiteSpec, ...]:
    registry = default_registry()
    sites: list[SiteSpec] = []
    for venue, city in registry.pairs():
        if venue != VENUE:
            continue
        settlement_site = registry.settlement_site(venue, city)
        sites.append(SiteSpec(city=city, cli_location=settlement_site.cli_location))
    return tuple(sites)


def _record_order(record: NwsClimateDay) -> tuple[int, int]:
    return (record.ts_init, record.revision_seq)


def _ns_to_utc(ns: int) -> str:
    seconds, nanos = divmod(ns, 1_000_000_000)
    stamp = dt.datetime.fromtimestamp(seconds, tz=dt.UTC).replace(microsecond=nanos // 1000)
    return stamp.isoformat()


def _date_range(records: Sequence[NwsClimateDay]) -> tuple[dt.date | None, dt.date | None]:
    if not records:
        return None, None
    days = [record.climate_day for record in records]
    return min(days), max(days)


def select_revision_pair(
    *,
    city: str,
    climate_day: dt.date,
    records: Sequence[NwsClimateDay],
    drops: Counter[str],
) -> RevisionPair | None:
    preliminaries = sorted(
        (record for record in records if not record.is_final),
        key=_record_order,
    )
    finals = sorted((record for record in records if record.is_final), key=_record_order)

    if not preliminaries:
        drops["no_preliminary"] += 1
        return None
    if not finals:
        drops["no_final"] += 1
        return None

    first_final = finals[0]
    preliminaries_before_final = [
        record for record in preliminaries if record.ts_init < first_final.ts_init
    ]
    if not preliminaries_before_final:
        drops["no_preliminary_before_first_final"] += 1
        return None

    preliminary = max(preliminaries_before_final, key=_record_order)
    final = finals[-1]

    if preliminary.tmax_f is None:
        drops["preliminary_tmax_sentinel"] += 1
        return None
    if final.tmax_f is None:
        drops["final_tmax_sentinel"] += 1
        return None

    return RevisionPair(
        city=city,
        climate_day=climate_day,
        preliminary_tmax_f=preliminary.tmax_f,
        final_tmax_f=final.tmax_f,
        revised=preliminary.tmax_f != final.tmax_f,
        preliminary_ts_init=preliminary.ts_init,
        first_final_ts_init=first_final.ts_init,
        final_ts_init=final.ts_init,
        preliminary_issuance_time_ns=preliminary.issuance_time_ns,
        first_final_issuance_time_ns=first_final.issuance_time_ns,
        final_issuance_time_ns=final.issuance_time_ns,
        preliminary_revision_seq=preliminary.revision_seq,
        final_revision_seq=final.revision_seq,
        preliminary_raw_sha256=preliminary.raw_sha256,
        final_raw_sha256=final.raw_sha256,
    )


def analyze_site(catalog_base: Path, spec: SiteSpec) -> SiteResult:
    root = station_catalog_path(catalog_base, VENUE, spec.city)
    if not root.exists():
        return SiteResult(
            city=spec.city,
            cli_location=spec.cli_location,
            catalog_root=root,
            catalog_root_exists=False,
            climate_records=0,
            expected_station_records=0,
            wrong_station_records=0,
            preliminary_records=0,
            final_records=0,
            first_climate_day=None,
            last_climate_day=None,
            pairs=(),
            drops=Counter({"missing_catalog_root": 1}),
        )

    try:
        records = tuple(read_climate_days(ParquetDataCatalog(path=root)))
    except (OSError, RuntimeError, ValueError, pa.ArrowException) as exc:
        return SiteResult(
            city=spec.city,
            cli_location=spec.cli_location,
            catalog_root=root,
            catalog_root_exists=True,
            climate_records=0,
            expected_station_records=0,
            wrong_station_records=0,
            preliminary_records=0,
            final_records=0,
            first_climate_day=None,
            last_climate_day=None,
            pairs=(),
            drops=Counter({"catalog_read_error": 1}),
            read_error=f"{type(exc).__name__}: {exc}",
        )

    expected_records = tuple(record for record in records if record.station == spec.cli_location)
    grouped: dict[dt.date, list[NwsClimateDay]] = defaultdict(list)
    for record in expected_records:
        grouped[record.climate_day].append(record)

    drops: Counter[str] = Counter()
    pairs: list[RevisionPair] = []
    for climate_day in sorted(grouped):
        pair = select_revision_pair(
            city=spec.city,
            climate_day=climate_day,
            records=grouped[climate_day],
            drops=drops,
        )
        if pair is not None:
            pairs.append(pair)

    first_day, last_day = _date_range(records)
    return SiteResult(
        city=spec.city,
        cli_location=spec.cli_location,
        catalog_root=root,
        catalog_root_exists=True,
        climate_records=len(records),
        expected_station_records=len(expected_records),
        wrong_station_records=len(records) - len(expected_records),
        preliminary_records=sum(1 for record in expected_records if not record.is_final),
        final_records=sum(1 for record in expected_records if record.is_final),
        first_climate_day=first_day,
        last_climate_day=last_day,
        pairs=tuple(pairs),
        drops=drops,
    )


def rate_stats(pairs: Sequence[RevisionPair]) -> RateStats:
    sample_count = len(pairs)
    revision_count = sum(1 for pair in pairs if pair.revised)
    if sample_count == 0:
        return RateStats(
            sample_count=0,
            revision_count=0,
            revision_rate=None,
            wilson_95_lower=None,
            wilson_95_upper=None,
            verdict="UNDERPOWERED",
        )

    lower = wilson_lower_bound(revision_count, sample_count, z=Z_95)
    non_revisions = sample_count - revision_count
    upper = 1.0 - wilson_lower_bound(non_revisions, sample_count, z=Z_95)
    verdict = "UNDERPOWERED"
    if sample_count >= SAMPLE_FLOOR_PER_SITE:
        verdict = "PASS" if upper <= WILSON_UPPER_PASS_THRESHOLD else "FAIL"
    return RateStats(
        sample_count=sample_count,
        revision_count=revision_count,
        revision_rate=revision_count / sample_count,
        wilson_95_lower=lower,
        wilson_95_upper=upper,
        verdict=verdict,
    )


def overall_verdict(results: Sequence[SiteResult]) -> str:
    site_verdicts = [rate_stats(result.pairs).verdict for result in results]
    if any(result.read_error for result in results):
        return "BLOCKED"
    if any(verdict == "UNDERPOWERED" for verdict in site_verdicts):
        return "UNDERPOWERED"
    if any(verdict == "FAIL" for verdict in site_verdicts):
        return "FAIL"
    return "PASS"


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def _format_date(value: dt.date | None) -> str:
    if value is None:
        return "none"
    return value.isoformat()


def markdown_report(
    *,
    catalog_base: Path,
    output_path: Path,
    command: str,
    results: Sequence[SiteResult],
) -> str:
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    gate = overall_verdict(results)
    total_n = sum(len(result.pairs) for result in results)
    total_revisions = sum(1 for result in results for pair in result.pairs if pair.revised)
    total_rate_line = (
        f"- Total observed revision rate: {(total_revisions / total_n):.6f}"
        if total_n
        else "- Total observed revision rate: n/a"
    )

    lines = [
        "# Preliminary/Final Tmax Revision-Rate Study Evidence",
        "",
        f"Generated at: {generated_at.isoformat()}",
        f"Primary verdict: **{gate}**",
        f"Pre-registration: `{PREREGISTRATION_PATH}`",
        f"Command: `{command}`",
        f"Catalog base: `{catalog_base}`",
        f"Output path: `{output_path}`",
        "Archive data used: **no**",
        "",
        "## Pre-Registered Decision Rule",
        "",
        f"- Minimum powered sample size: N >= {SAMPLE_FLOOR_PER_SITE} paired site-days per site.",
        (
            "- Per-site PASS: Wilson 95% upper bound for tmax revision rate "
            f"<= {WILSON_UPPER_PASS_THRESHOLD:.6f}."
        ),
        "- Primary PASS: every site passes.",
        "- Primary FAIL: every site is powered and at least one site fails.",
        "- Primary UNDERPOWERED: at least one site is underpowered.",
        "",
        "## Headline Result",
        "",
        f"- Total paired live-catalog sample size: {total_n}",
        f"- Total observed tmax revisions: {total_revisions}",
        total_rate_line,
        f"- Primary verdict against pre-registration: **{gate}**",
        "",
        "## Per-Site Statistics",
        "",
        (
            "| Site | N | Revisions | Revision rate | Wilson 95% lower | "
            "Wilson 95% upper | Verdict |"
        ),
        "|---|---:|---:|---:|---:|---:|---|",
    ]

    for result in sorted(results, key=lambda item: item.city):
        stats = rate_stats(result.pairs)
        lines.append(
            f"| {result.city} | {stats.sample_count} | {stats.revision_count} | "
            f"{_format_rate(stats.revision_rate)} | {_format_rate(stats.wilson_95_lower)} | "
            f"{_format_rate(stats.wilson_95_upper)} | {stats.verdict} |"
        )

    lines.extend(
        [
            "",
            "## Catalog Inventory",
            "",
            (
                "| Site | CLI location | Root exists | Climate records | "
                "Expected-station records | "
                "Wrong-station records | Preliminary records | Final records | Date range |"
            ),
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for result in sorted(results, key=lambda item: item.city):
        date_range = (
            f"{_format_date(result.first_climate_day)}.."
            f"{_format_date(result.last_climate_day)}"
        )
        lines.append(
            f"| {result.city} | {result.cli_location} | {result.catalog_root_exists} | "
            f"{result.climate_records} | {result.expected_station_records} | "
            f"{result.wrong_station_records} | {result.preliminary_records} | "
            f"{result.final_records} | {date_range} |"
        )

    lines.extend(["", "## Drop Counts", ""])
    for result in sorted(results, key=lambda item: item.city):
        if result.drops:
            drop_text = ", ".join(
                f"{reason}={count}" for reason, count in sorted(result.drops.items())
            )
        else:
            drop_text = "none"
        lines.append(f"- {result.city}: {drop_text}")
        if result.read_error:
            lines.append(f"- {result.city} read error: {result.read_error}")

    lines.extend(["", "## Included Pairs", ""])
    if total_n:
        lines.extend(
            [
                (
                    "| Site | Climate day | Preliminary tmax | Final tmax | Revised | "
                    "Prelim issued UTC | First final issued UTC | Selected final issued UTC | "
                    "Prelim retrieved UTC | First final retrieved UTC | "
                    "Selected final retrieved UTC |"
                ),
                "|---|---|---:|---:|---|---|---|---|---|---|---|",
            ]
        )
        for result in sorted(results, key=lambda item: item.city):
            for pair in result.pairs:
                lines.append(
                    f"| {pair.city} | {pair.climate_day.isoformat()} | "
                    f"{pair.preliminary_tmax_f} | {pair.final_tmax_f} | {pair.revised} | "
                    f"{_ns_to_utc(pair.preliminary_issuance_time_ns)} | "
                    f"{_ns_to_utc(pair.first_final_issuance_time_ns)} | "
                    f"{_ns_to_utc(pair.final_issuance_time_ns)} | "
                    f"{_ns_to_utc(pair.preliminary_ts_init)} | "
                    f"{_ns_to_utc(pair.first_final_ts_init)} | {_ns_to_utc(pair.final_ts_init)} |"
                )
    else:
        lines.append("No paired preliminary/final site-days were included.")

    lines.extend(
        [
            "",
            "## Limitations",
            "",
            (
                "- Continuous live collection was re-established on 2026-08-24 after total "
                "catalog loss, so the live-catalog sample is expected to be small."
            ),
            (
                "- The primary result is live-catalog only; no IEM archive-derived records "
                "are mixed into the verdict."
            ),
            (
                "- Several included records were recovered during the 2026-08-24 collector "
                "restart. For those rows, retrieval timestamps show Breezy backfill order; "
                "issuance timestamps show the product publication order."
            ),
            (
                "- The statistic measures `tmax` changes from selected preliminary to selected "
                "final. It does not estimate market-specific error probability conditional on "
                "a contract threshold or order book."
            ),
            (
                "- A latest final correction currently present in the catalog is treated as "
                "the final `tmax` truth for this study."
            ),
            (
                "- If a station root was being modified concurrently and could not be read, "
                "the study reports BLOCKED rather than retrying with any catalog mutation."
            ),
            "",
            "## Output Integrity",
            "",
        ]
    )
    content_without_digest = "\n".join(lines)
    digest = hashlib.sha256(content_without_digest.encode("utf-8")).hexdigest()
    lines.append(f"- SHA256 of report content before this line: `{digest}`")
    lines.append("")
    return "\n".join(lines)


def write_evidence(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {
        "captured_by": "breezy preliminary-final revision-rate study script",
        "retrieved_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "sha256": digest,
        "url": "local live catalog read-only study",
    }
    path.with_suffix(path.suffix + ".meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-base", type=Path, default=DEFAULT_CATALOG_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    sites = load_sites()
    results = tuple(analyze_site(args.catalog_base, spec) for spec in sites)
    command = " ".join(shlex.quote(part) for part in [sys.executable, *sys.argv])
    report = markdown_report(
        catalog_base=args.catalog_base,
        output_path=args.output,
        command=command,
        results=results,
    )
    write_evidence(args.output, report)
    print(f"wrote {args.output}")
    print(f"primary_verdict={overall_verdict(results)}")
    for result in sorted(results, key=lambda item: item.city):
        stats = rate_stats(result.pairs)
        print(
            f"{result.city}: n={stats.sample_count} revisions={stats.revision_count} "
            f"rate={_format_rate(stats.revision_rate)} "
            f"wilson95=[{_format_rate(stats.wilson_95_lower)}, "
            f"{_format_rate(stats.wilson_95_upper)}] verdict={stats.verdict}"
        )
    return 2 if any(result.read_error for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
