"""Probe cached IEM AFOS CLI archives for final corrections and yield drift.

This is Increment I-0 from ``docs/plans/CLI_BACKFILL_PLAN.md``. It is a
zero-network probe over the existing settlement-alignment AFOS ZIP cache. It
does not write to Breezy's catalog, state store, or archive cache.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import math
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Final, Literal
from zipfile import ZipFile

from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (
    VENUE,
    afos_url,
    cache_path_for_url,
    issue_utc_from_iem_filename,
    load_sites,
    parse_issued_at,
    split_iem_afos_products,
)

from breezy.normalize.classify import (
    ClassificationError,
    Issuance,
    classify_issuance,
    has_correction_evidence,
)
from breezy.normalize.cli_parse import (
    CliContentError,
    CliNotOurProductError,
    CliStructuralError,
    parse_cli_product,
)
from breezy.normalize.sanity import CliSanityError
from breezy.registry.sites import SettlementSite

START_YEAR: Final[int] = 2021
END_YEAR: Final[int] = 2025
DEFAULT_OUTPUT_PATH: Final[Path] = Path(
    "docs/evidence/ingestion/ARCHIVE_CORRECTION_PROBE_2026-08-29.md"
)
REJECTION_CATEGORIES: Final[tuple[str, ...]] = (
    "CliStructuralError",
    "CliContentError",
    "CliSanityError",
    "ClassificationError",
    "CliNotOurProductError",
)
Z_95: Final[float] = 1.959963984540054
ValueTriple = tuple[int | None, int | None, int | None]


class CacheCoverageError(RuntimeError):
    """The required zero-network cache coverage is unavailable."""


@dataclass(frozen=True, slots=True)
class ProductRecord:
    city: str
    cli_location: str
    year: int
    climate_day: dt.date
    issuance: Issuance
    issuance_ns: int | None
    raw_sha256: str
    value_triple: ValueTriple
    is_correction_bbb: bool
    has_correction_evidence: bool
    source_member: str
    product_index: int


@dataclass(frozen=True, slots=True)
class CandidatePair:
    city: str
    cli_location: str
    year: int
    climate_day: dt.date
    earlier: ProductRecord
    later: ProductRecord

    @property
    def delta_seconds(self) -> int | None:
        if self.earlier.issuance_ns is None or self.later.issuance_ns is None:
            return None
        return (self.later.issuance_ns - self.earlier.issuance_ns) // 1_000_000_000

    @property
    def values_differ(self) -> bool:
        return self.earlier.value_triple != self.later.value_triple

    @property
    def byte_different_value_identical(self) -> bool:
        return self.earlier.raw_sha256 != self.later.raw_sha256 and not self.values_differ


@dataclass(slots=True)
class StationYearStats:
    city: str
    cli_location: str
    year: int
    cache_file: Path
    total_products: int = 0
    parseable: int = 0
    out_of_year_parseable: int = 0
    unresolved_issuance: int = 0
    zip_members: int = 0
    zip_members_without_products: int = 0
    rejections: Counter[str] = field(default_factory=Counter)
    records: list[ProductRecord] = field(default_factory=list)

    @property
    def calendar_days(self) -> int:
        return 366 if calendar.isleap(self.year) else 365

    @property
    def days_with_parseable_final(self) -> int:
        return len(
            {
                record.climate_day
                for record in self.records
                if record.issuance == "FINAL" and record.climate_day.year == self.year
            }
        )

    @property
    def yield_rate(self) -> float:
        return self.days_with_parseable_final / self.calendar_days

    def monthly_final_counts(self) -> dict[int, int]:
        days_by_month: dict[int, set[dt.date]] = {month: set() for month in range(1, 13)}
        for record in self.records:
            if record.issuance == "FINAL" and record.climate_day.year == self.year:
                days_by_month[record.climate_day.month].add(record.climate_day)
        return {month: len(days) for month, days in days_by_month.items()}


@dataclass(frozen=True, slots=True)
class ProbeResult:
    station_years: tuple[StationYearStats, ...]
    candidates: tuple[CandidatePair, ...]
    product_group_counts: Mapping[tuple[str, int, dt.date, Issuance], int]
    extra_zip_files: tuple[Path, ...]


def _issue_ns(filename_issue: dt.datetime | None, product_text: str) -> int | None:
    issued_at = filename_issue or parse_issued_at(product_text)
    if issued_at is None:
        return None
    return int(issued_at.timestamp() * 1_000_000_000)


def _rejection_name(exc: Exception) -> Literal[
    "CliStructuralError",
    "CliContentError",
    "CliSanityError",
    "ClassificationError",
    "CliNotOurProductError",
]:
    if isinstance(exc, CliNotOurProductError):
        return "CliNotOurProductError"
    if isinstance(exc, CliStructuralError):
        return "CliStructuralError"
    if isinstance(exc, CliContentError):
        return "CliContentError"
    if isinstance(exc, CliSanityError):
        return "CliSanityError"
    if isinstance(exc, ClassificationError):
        return "ClassificationError"
    raise AssertionError(f"unexpected rejection type: {type(exc).__name__}")


def _expected_cache_paths(cache_dir: Path) -> dict[tuple[str, int], Path]:
    expected: dict[tuple[str, int], Path] = {}
    for spec in load_sites():
        for year in range(START_YEAR, END_YEAR + 1):
            start = dt.date(year, 1, 1)
            end = dt.date(year, 12, 31)
            url = afos_url(spec.site.cli_location, start, end, limit=3_000)
            expected[(spec.city, year)] = cache_path_for_url(cache_dir, url, suffix=".zip")
    return expected


def _iter_expected_site_years(
    cache_dir: Path,
) -> Iterable[tuple[str, SettlementSite, int, Path]]:
    expected_paths = _expected_cache_paths(cache_dir)
    missing = [path for path in expected_paths.values() if not path.is_file()]
    if missing:
        missing_list = "\n".join(str(path) for path in missing)
        raise CacheCoverageError(
            "required station-year AFOS ZIP cache entries are missing; "
            "zero-network I-0 cannot proceed:\n"
            f"{missing_list}"
        )
    for spec in sorted(load_sites(), key=lambda item: item.city):
        for year in range(START_YEAR, END_YEAR + 1):
            yield spec.city, spec.site, year, expected_paths[(spec.city, year)]


def _parse_station_year(
    city: str,
    site: SettlementSite,
    year: int,
    cache_file: Path,
) -> StationYearStats:
    stats = StationYearStats(
        city=city,
        cli_location=site.cli_location,
        year=year,
        cache_file=cache_file,
    )
    with ZipFile(cache_file) as archive:
        for member in sorted(archive.namelist()):
            stats.zip_members += 1
            raw_text = archive.read(member).decode("utf-8", errors="replace")
            products = split_iem_afos_products(raw_text)
            if not products:
                stats.zip_members_without_products += 1
                continue
            filename_issue = issue_utc_from_iem_filename(member)
            for product_index, product_text in enumerate(products, start=1):
                stats.total_products += 1
                issuance_ns = _issue_ns(filename_issue, product_text)
                if issuance_ns is None:
                    stats.unresolved_issuance += 1
                try:
                    parsed = parse_cli_product(
                        product_text,
                        cli_location=site.cli_location,
                        body_header_regex=site.body_header_regex,
                    )
                    issuance = classify_issuance(product_text)
                except (
                    CliNotOurProductError,
                    CliStructuralError,
                    CliContentError,
                    CliSanityError,
                    ClassificationError,
                ) as exc:
                    stats.rejections[_rejection_name(exc)] += 1
                    continue

                stats.parseable += 1
                if parsed.summary_date.year != year:
                    stats.out_of_year_parseable += 1
                stats.records.append(
                    ProductRecord(
                        city=city,
                        cli_location=site.cli_location,
                        year=year,
                        climate_day=parsed.summary_date,
                        issuance=issuance,
                        issuance_ns=issuance_ns,
                        raw_sha256=hashlib.sha256(product_text.encode("utf-8")).hexdigest(),
                        value_triple=(
                            parsed.tmax.value_f,
                            parsed.tmin.value_f,
                            parsed.tavg.value_f,
                        ),
                        is_correction_bbb=parsed.is_correction_bbb,
                        has_correction_evidence=has_correction_evidence(product_text),
                        source_member=member,
                        product_index=product_index,
                    )
                )
    return stats


def _record_sort_key(record: ProductRecord) -> tuple[int, int, str]:
    return (
        record.issuance_ns if record.issuance_ns is not None else sys.maxsize,
        record.product_index,
        record.raw_sha256,
    )


def _product_group_counts(
    station_years: Sequence[StationYearStats],
) -> dict[tuple[str, int, dt.date, Issuance], int]:
    counts: dict[tuple[str, int, dt.date, Issuance], int] = defaultdict(int)
    for station_year in station_years:
        for record in station_year.records:
            if record.climate_day.year == station_year.year:
                counts[(record.city, record.year, record.climate_day, record.issuance)] += 1
    return dict(counts)


def _candidate_pairs(station_years: Sequence[StationYearStats]) -> tuple[CandidatePair, ...]:
    grouped: dict[tuple[str, int, dt.date], list[ProductRecord]] = defaultdict(list)
    for station_year in station_years:
        for record in station_year.records:
            if record.climate_day.year == station_year.year and record.issuance == "FINAL":
                grouped[(record.city, record.year, record.climate_day)].append(record)

    pairs: list[CandidatePair] = []
    for (_city, _year, _day), records in sorted(grouped.items()):
        ordered = sorted(records, key=_record_sort_key)
        for earlier, later in pairwise(ordered):
            pairs.append(
                CandidatePair(
                    city=later.city,
                    cli_location=later.cli_location,
                    year=later.year,
                    climate_day=later.climate_day,
                    earlier=earlier,
                    later=later,
                )
            )
    return tuple(pairs)


def run_probe(cache_dir: Path) -> ProbeResult:
    cache_dir = require_settlement_alignment_cache_dir(cache_dir)
    station_years = tuple(
        _parse_station_year(city, site, year, cache_file)
        for city, site, year, cache_file in _iter_expected_site_years(cache_dir)
    )
    expected_zip_names = {path.name for path in _expected_cache_paths(cache_dir).values()}
    extra_zip_files = tuple(
        sorted(
            path
            for path in cache_dir.glob("*.zip")
            if path.name not in expected_zip_names
        )
    )
    return ProbeResult(
        station_years=station_years,
        candidates=_candidate_pairs(station_years),
        product_group_counts=_product_group_counts(station_years),
        extra_zip_files=extra_zip_files,
    )


def wilson_interval(successes: int, total: int, *, z: float = Z_95) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = (
        z
        * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
        / denom
    )
    return (max(0.0, center - half), min(1.0, center + half))


def _fmt_rate(value: float) -> str:
    return f"{value:.4f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fmt_int_or_na(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


def _summarize_deltas(candidates: Sequence[CandidatePair]) -> tuple[int, int, int, float] | None:
    deltas = [
        candidate.delta_seconds for candidate in candidates if candidate.delta_seconds is not None
    ]
    if not deltas:
        return None
    return (
        min(deltas),
        int(statistics.median(deltas)),
        max(deltas),
        statistics.mean(deltas),
    )


def _monthly_flag_rows(
    station_years: Sequence[StationYearStats],
) -> list[tuple[str, int, int, int, float]]:
    by_city: dict[str, list[StationYearStats]] = defaultdict(list)
    for station_year in station_years:
        by_city[station_year.city].append(station_year)

    flagged: list[tuple[str, int, int, int, float]] = []
    for city, rows in sorted(by_city.items()):
        month_counts = [
            count
            for station_year in rows
            for count in station_year.monthly_final_counts().values()
        ]
        mean = statistics.mean(month_counts)
        pstdev = statistics.pstdev(month_counts)
        threshold = mean - 2 * pstdev
        for station_year in sorted(rows, key=lambda item: item.year):
            for month, count in station_year.monthly_final_counts().items():
                if count < threshold:
                    flagged.append((city, station_year.year, month, count, threshold))
    return flagged


def _monthly_gap_rows(
    station_years: Sequence[StationYearStats],
) -> list[tuple[str, int, int, int, int]]:
    gaps: list[tuple[str, int, int, int, int]] = []
    for station_year in station_years:
        for month, count in station_year.monthly_final_counts().items():
            expected_days = calendar.monthrange(station_year.year, month)[1]
            missing_days = expected_days - count
            if missing_days > 0:
                gaps.append((station_year.city, station_year.year, month, count, missing_days))
    return gaps


def _render_station_year_table(station_years: Sequence[StationYearStats]) -> list[str]:
    lines = [
        (
            "| Station | Year | Products | Parseable | Finals days | Yield | "
            "Unresolved issue | Out-of-year parseable | Structural | Content | Sanity | "
            "Classification | Not our product | Empty members |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in station_years:
        lines.append(
            f"| {row.city} | {row.year} | {row.total_products} | {row.parseable} | "
            f"{row.days_with_parseable_final} | {_fmt_rate(row.yield_rate)} | "
            f"{row.unresolved_issuance} | {row.out_of_year_parseable} | "
            f"{row.rejections['CliStructuralError']} | {row.rejections['CliContentError']} | "
            f"{row.rejections['CliSanityError']} | {row.rejections['ClassificationError']} | "
            f"{row.rejections['CliNotOurProductError']} | {row.zip_members_without_products} |"
        )
    return lines


def _render_monthly_table(station_years: Sequence[StationYearStats]) -> list[str]:
    header = (
        "| Station | Year | "
        + " | ".join(calendar.month_abbr[month] for month in range(1, 13))
        + " |"
    )
    separator = "|---|---:|" + "---:|" * 12
    lines = [header, separator]
    for row in station_years:
        monthly = row.monthly_final_counts()
        counts = " | ".join(str(monthly[month]) for month in range(1, 13))
        lines.append(f"| {row.city} | {row.year} | {counts} |")
    return lines


def _render_candidate_table(candidates: Sequence[CandidatePair]) -> list[str]:
    if not candidates:
        return ["No FINAL correction-candidate pairs were found."]
    lines = [
        (
            "| Station | Year | Climate day | Later BBB CCx | Later text evidence | "
            "Values differ | Byte-different value-identical | Delta seconds | Earlier SHA | "
            "Later SHA |"
        ),
        "|---|---:|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for candidate in candidates:
        lines.append(
            f"| {candidate.city} | {candidate.year} | {candidate.climate_day.isoformat()} | "
            f"{int(candidate.later.is_correction_bbb)} | "
            f"{int(candidate.later.has_correction_evidence)} | "
            f"{int(candidate.values_differ)} | "
            f"{int(candidate.byte_different_value_identical)} | "
            f"{_fmt_int_or_na(candidate.delta_seconds)} | "
            f"`{candidate.earlier.raw_sha256[:12]}` | "
            f"`{candidate.later.raw_sha256[:12]}` |"
        )
    return lines


def _render_group_count_table(
    product_group_counts: Mapping[tuple[str, int, dt.date, Issuance], int],
) -> list[str]:
    by_day: dict[tuple[str, int, dt.date], dict[Issuance, int]] = defaultdict(
        lambda: {"PRELIMINARY": 0, "FINAL": 0}
    )
    for (city, year, climate_day, issuance), count in product_group_counts.items():
        by_day[(city, year, climate_day)][issuance] = count

    lines = [
        "| Station | Year | Climate day | PRELIMINARY products | FINAL products |",
        "|---|---:|---|---:|---:|",
    ]
    for (city, year, climate_day), counts in sorted(by_day.items()):
        lines.append(
            f"| {city} | {year} | {climate_day.isoformat()} | "
            f"{counts['PRELIMINARY']} | {counts['FINAL']} |"
        )
    return lines


def render_markdown(result: ProbeResult, *, cache_dir: Path) -> str:
    station_years = result.station_years
    candidates = result.candidates
    final_days = sum(row.days_with_parseable_final for row in station_years)
    candidate_groups = {
        (candidate.city, candidate.year, candidate.climate_day)
        for candidate in candidates
    }
    bbb_candidate_groups = {
        (candidate.city, candidate.year, candidate.climate_day)
        for candidate in candidates
        if candidate.later.is_correction_bbb
    }
    evidence_candidate_groups = {
        (candidate.city, candidate.year, candidate.climate_day)
        for candidate in candidates
        if candidate.later.has_correction_evidence
    }
    bbb_candidates = sum(1 for candidate in candidates if candidate.later.is_correction_bbb)
    evidence_only_candidates = sum(
        1
        for candidate in candidates
        if candidate.later.has_correction_evidence and not candidate.later.is_correction_bbb
    )
    neither_candidates = sum(
        1
        for candidate in candidates
        if not candidate.later.has_correction_evidence and not candidate.later.is_correction_bbb
    )
    values_differ = sum(1 for candidate in candidates if candidate.values_differ)
    byte_different_value_identical = sum(
        1 for candidate in candidates if candidate.byte_different_value_identical
    )
    unresolved_candidate_deltas = sum(
        1 for candidate in candidates if candidate.delta_seconds is None
    )
    yields = [row.yield_rate for row in station_years]
    yield_min = min(yields)
    yield_median = statistics.median(yields)
    yield_max = max(yields)
    duplicate_lower, duplicate_upper = wilson_interval(len(candidate_groups), final_days)
    archive_bbb_lower, archive_bbb_upper = wilson_interval(len(bbb_candidate_groups), final_days)
    archive_evidence_lower, archive_evidence_upper = wilson_interval(
        len(evidence_candidate_groups), final_days
    )
    live_lower, live_upper = wilson_interval(1, 8)
    delta_summary = _summarize_deltas(candidates)
    monthly_flags = _monthly_flag_rows(station_years)
    monthly_gaps = _monthly_gap_rows(station_years)
    yield_verdict = "supported"
    if yield_min < 0.95:
        yield_verdict = "too tight for this cache"
    elif yield_min > 0.99:
        yield_verdict = "too loose for this cache"

    lines = [
        "# Archive Correction Probe - 2026-08-29",
        "",
        (
            "Read-only I-0 probe over cached IEM AFOS ZIP responses. No network fetches were "
            "made by this script, and it writes only this evidence document."
        ),
        "",
        "## Inputs",
        "",
        f"- Cache directory: `{cache_dir}`",
        f"- Expected scope: `{VENUE}` CLI station-years {START_YEAR}-{END_YEAR}",
        f"- Expected AFOS ZIPs found: {len(station_years)}/25",
        f"- Extra ZIPs present but excluded from the scoped probe: {len(result.extra_zip_files)}",
        (
            "- Product splitter and issuance recovery reused from "
            "`scripts/analysis/settlement_alignment_study.py`."
        ),
        (
            "- Parser/classifier reused from `breezy.normalize.cli_parse.parse_cli_product` "
            "and `breezy.normalize.classify.classify_issuance`."
        ),
        "",
        "## Headline Results",
        "",
        f"- FINAL correction-candidate groups: {len(candidate_groups)}",
        f"- FINAL correction-candidate later-product pairs: {len(candidates)}",
        (
            f"- Candidate evidence split: BBB CCx={bbb_candidates}, "
            f"free-text-only={evidence_only_candidates}, neither={neither_candidates}"
        ),
        (
            f"- Candidate groups with any later-product correction evidence: "
            f"BBB CCx={len(bbb_candidate_groups)}, any evidence={len(evidence_candidate_groups)}"
        ),
        (
            f"- Candidate value comparison: values differ={values_differ}, "
            f"byte-different but value-identical={byte_different_value_identical}"
        ),
        f"- Candidate unresolved issuance deltas: {unresolved_candidate_deltas}",
        (
            f"- Products with issuance instant from neither filename nor ISSUED line: "
            f"{sum(row.unresolved_issuance for row in station_years)}"
        ),
        (
            f"- Per-station-year yield min/median/max: "
            f"{_fmt_rate(yield_min)} / {_fmt_rate(yield_median)} / {_fmt_rate(yield_max)}"
        ),
        f"- 0.95 yield floor verdict: {yield_verdict}",
        "",
        "## Correction Base-Rate Honesty",
        "",
        (
            f"Archive duplicate-FINAL candidate-group rate: {len(candidate_groups)}/"
            f"{final_days} parseable final station-days = "
            f"{_fmt_pct(len(candidate_groups) / final_days)} (Wilson 95% CI "
            f"{_fmt_pct(duplicate_lower)}-{_fmt_pct(duplicate_upper)}). This is a broad "
            "supersession-candidate rate, not the same denominator as the live "
            "corrected-final count."
        ),
        "",
        (
            f"Archive positional `CCx` correction-candidate group rate: "
            f"{len(bbb_candidate_groups)}/{final_days} = "
            f"{_fmt_pct(len(bbb_candidate_groups) / final_days)} "
            f"(Wilson 95% CI {_fmt_pct(archive_bbb_lower)}-"
            f"{_fmt_pct(archive_bbb_upper)})."
        ),
        "",
        (
            f"Archive any-evidence correction-candidate group rate: "
            f"{len(evidence_candidate_groups)}/{final_days} = "
            f"{_fmt_pct(len(evidence_candidate_groups) / final_days)} "
            f"(Wilson 95% CI {_fmt_pct(archive_evidence_lower)}-"
            f"{_fmt_pct(archive_evidence_upper)})."
        ),
        "",
        (
            "Live-side reference from `docs/evidence/settlement_alignment_2026-08-25.md:32`: "
            f"1 corrected final out of 8 MDW finals = {_fmt_pct(1 / 8)} "
            f"(Wilson 95% CI {_fmt_pct(live_lower)}-{_fmt_pct(live_upper)})."
        ),
        "",
        (
            "The archive-vs-live contrast is a hypothesis with very wide uncertainty, not "
            "a settled finding. The archive `CCx` point estimate is much lower than the "
            "live MDW point estimate, but this probe does not by itself prove the archive "
            "is lossy for corrections."
        ),
        "",
        "## Candidate Delta Distribution",
        "",
    ]
    if delta_summary is None:
        lines.append("No candidate pairs had a measurable later-minus-earlier issuance delta.")
    else:
        min_delta, median_delta, max_delta, mean_delta = delta_summary
        lines.append(
            f"Delta seconds min/median/max/mean: {min_delta} / {median_delta} / "
            f"{max_delta} / {mean_delta:.1f}."
        )
    lines.extend(
        [
            "",
            "## Per Station-Year Yield And Rejections",
            "",
            *_render_station_year_table(station_years),
            "",
            "## Per Station-Year Monthly Parseable FINAL Counts",
            "",
            *_render_monthly_table(station_years),
            "",
            "## Month Completeness Gaps",
            "",
        ]
    )
    if not monthly_gaps:
        lines.append("No station-year-month is missing a parseable FINAL climate day.")
    else:
        lines.extend(
            [
                "| Station | Year | Month | Parseable FINAL days | Missing days |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for city, year, month, count, missing_days in monthly_gaps:
            lines.append(f"| {city} | {year} | {month} | {count} | {missing_days} |")
    lines.extend(
        [
            "",
            "## Monthly Low-Count Flags",
            "",
        ]
    )
    if not monthly_flags:
        lines.append("No station-year-month count fell more than 2 population standard deviations "
                     "below that station's 2021-2025 monthly mean.")
    else:
        lines.extend(
            [
                "| Station | Year | Month | Count | Station threshold |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for city, year, month, count, threshold in monthly_flags:
            lines.append(f"| {city} | {year} | {month} | {count} | {threshold:.2f} |")
    lines.extend(
        [
            "",
            "## Correction Candidates",
            "",
            *_render_candidate_table(candidates),
            "",
            "## Products Per Station Climate Day And Issuance Class",
            "",
            *_render_group_count_table(result.product_group_counts),
            "",
            "## What This Means For The Plan",
            "",
            (
                f"- Item 7: The single-year yield distribution is {_fmt_rate(yield_min)} "
                f"min, {_fmt_rate(yield_median)} median, {_fmt_rate(yield_max)} max. "
                f"A 0.95 floor is {yield_verdict} by this 2021-2025 cache; the "
                "observed minimum also leaves room to evaluate a stricter floor "
                "separately."
            ),
            (
                "- Item 8: Monthly counts are reported above. The low-count flag uses "
                "the raw station-month counts requested here; it is a gap detector, "
                "not a month-length normalization. The month completeness table "
                "separately lists every month with fewer parseable FINAL days than "
                "calendar days."
            ),
            (
                "- Item 9: Correction candidates are reported with Wilson uncertainty "
                "and compared to the live MDW 1/8 rate only as an uncertain hypothesis."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
        help="Read-only settlement-alignment AFOS cache directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Evidence markdown path to write.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = run_probe(args.cache_dir)
    content = render_markdown(
        result,
        cache_dir=require_settlement_alignment_cache_dir(args.cache_dir),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"station_years={len(result.station_years)}")
    print(f"correction_candidate_pairs={len(result.candidates)}")
    print(
        "yield_min_median_max="
        f"{min(row.yield_rate for row in result.station_years):.4f}/"
        f"{statistics.median(row.yield_rate for row in result.station_years):.4f}/"
        f"{max(row.yield_rate for row in result.station_years):.4f}"
    )
    flags = _monthly_flag_rows(result.station_years)
    print(f"monthly_low_count_flags={len(flags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
