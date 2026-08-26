"""Cache-only symmetric settlement bucket gate for Breezy Phase 2.

This script reuses the historical CLI and METAR loading/parsing paths from
``settlement_alignment_study.py``. It never calls Polymarket, never uses
credentials, and refuses archive cache misses instead of fetching network data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from settlement_alignment_study import (
    END_DATE,
    START_DATE,
    CliLabel,
    DailyMetarMax,
    SiteSpec,
    afos_url,
    asos_url,
    daily_metar_maxima,
    load_sites,
    metar_temperatures,
    parse_asos_rows,
    parse_cli_labels_zip,
    read_catalog_finals,
    wilson_lower_bound,
    year_chunks,
)

DEFAULT_CACHE_DIR: Final[Path] = Path("/tmp/breezy-settlement-alignment-cache")
DEFAULT_OUTPUT: Final[Path] = Path("docs/evidence/settlement_bucket_gate_2026-08-25.md")
PREREGISTRATION_PATH: Final[Path] = Path(
    "docs/evidence/settlement_bucket_gate_prereg_2026-08-25.md"
)
VENUE_RAW_DIR: Final[Path] = Path("docs/evidence/venue/polymarket_us/raw")
PASS_WILSON_LOWER: Final[float] = 0.9900
MIN_CITY_DAYS: Final[int] = 1_000
MIN_TOTAL_DAYS: Final[int] = 5_000
BUCKET_WIDTH_F: Final[float] = 2.0
PHASES: Final[tuple[float, ...]] = tuple(round(step / 10.0, 1) for step in range(20))

MARKET_SLUG_RE: Final[re.Pattern[str]] = re.compile(
    r"^tc-temp-(?P<city>[a-z]+)high-(?P<date>\d{4}-\d{2}-\d{2})-"
    r"(?P<strike>(?:lt(?P<lt>\d+)f)|(?:gte(?P<gte>\d+)lt(?P<inner_lt>\d+)f)|"
    r"(?:gte(?P<upper_gte>\d+)f))$"
)
TITLE_RANGE_RE: Final[re.Pattern[str]] = re.compile(r"(?P<lo>-?\d+)\s*(?:°)?\s+to\s+(?P<hi>-?\d+)")


@dataclass(frozen=True, slots=True)
class VenueMarket:
    slug: str
    city: str
    event_date: dt.date
    strike_kind: str
    strike_low: int | None
    strike_high: int | None
    title: str
    description: str
    source_file: str


@dataclass(frozen=True, slots=True)
class VenueGrammar:
    markets: tuple[VenueMarket, ...]
    strike_counts: Counter[str]
    interior_display_widths: Counter[int]
    slug_inner_span_counts: Counter[int]
    complete_event_count: int
    lower_anchors: Counter[int]
    anchor_phases: Counter[int]


@dataclass(frozen=True, slots=True)
class DailyComparison:
    city: str
    climate_day: dt.date
    cli_tmax_f: int
    metar_rounded_max_f: int
    metar_unrounded_max_f: float
    cli_source: str
    metar_source: str


@dataclass(frozen=True, slots=True)
class PhaseCase:
    city: str
    climate_day: dt.date
    phase: float
    cli_tmax_f: int
    metar_rounded_max_f: int
    cli_bucket: int
    metar_bucket: int
    edge_distance_f: float

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
class AgreementStats:
    cases: int
    agreements: int
    rate: float
    wilson_lower: float
    metar_below_cli: int
    metar_above_cli: int


def cache_path_for_url(cache_dir: Path, url: str, suffix: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}{suffix}"


def read_cached(cache_dir: Path, url: str, suffix: str) -> bytes:
    path = cache_path_for_url(cache_dir, url, suffix)
    if not path.exists():
        raise SystemExit(
            "cache miss would require network access; refusing:\n"
            f"url: {url}\n"
            f"expected cache file: {path}"
        )
    return path.read_bytes()


def iter_json_objects(value: object) -> Iterable[Mapping[str, object]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from iter_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_objects(child)


def parse_venue_market(obj: Mapping[str, object], source_file: Path) -> VenueMarket | None:
    slug_value = obj.get("slug")
    if not isinstance(slug_value, str):
        return None
    match = MARKET_SLUG_RE.match(slug_value)
    if match is None:
        return None

    if match.group("lt") is not None:
        strike_kind = "lt"
        strike_low = None
        strike_high = int(match.group("lt"))
    elif match.group("upper_gte") is not None:
        strike_kind = "gte"
        strike_low = int(match.group("upper_gte"))
        strike_high = None
    else:
        strike_kind = "between"
        strike_low = int(match.group("gte"))
        strike_high = int(match.group("inner_lt"))

    title = obj.get("title")
    if not isinstance(title, str):
        title = obj.get("groupItemTitle") if isinstance(obj.get("groupItemTitle"), str) else ""
    description = obj.get("description")
    return VenueMarket(
        slug=slug_value,
        city=match.group("city"),
        event_date=dt.date.fromisoformat(match.group("date")),
        strike_kind=strike_kind,
        strike_low=strike_low,
        strike_high=strike_high,
        title=title,
        description=description if isinstance(description, str) else "",
        source_file=str(source_file),
    )


def derive_venue_grammar(raw_dir: Path) -> VenueGrammar:
    by_slug: dict[str, VenueMarket] = {}
    for path in sorted(raw_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for obj in iter_json_objects(data):
            market = parse_venue_market(obj, path)
            if market is not None:
                by_slug.setdefault(market.slug, market)

    markets = tuple(sorted(by_slug.values(), key=lambda row: row.slug))
    strike_counts: Counter[str] = Counter(market.strike_kind for market in markets)
    interior_display_widths: Counter[int] = Counter()
    slug_inner_span_counts: Counter[int] = Counter()
    by_event: dict[tuple[str, dt.date], list[VenueMarket]] = defaultdict(list)
    for market in markets:
        by_event[(market.city, market.event_date)].append(market)
        if market.strike_kind != "between":
            continue
        if market.strike_low is not None and market.strike_high is not None:
            slug_inner_span_counts[market.strike_high - market.strike_low] += 1
        title_match = TITLE_RANGE_RE.search(market.title)
        if title_match is not None:
            display_low = int(title_match.group("lo"))
            display_high = int(title_match.group("hi"))
            interior_display_widths[display_high - display_low + 1] += 1

    lower_anchors: Counter[int] = Counter()
    anchor_phases: Counter[int] = Counter()
    complete_event_count = 0
    for event_markets in by_event.values():
        kinds = {market.strike_kind for market in event_markets}
        if not {"lt", "between", "gte"}.issubset(kinds):
            continue
        interior_lows = sorted(
            market.strike_low
            for market in event_markets
            if market.strike_kind == "between" and market.strike_low is not None
        )
        if not interior_lows:
            continue
        lower_anchor = interior_lows[0]
        lower_anchors[lower_anchor] += 1
        anchor_phases[lower_anchor % 2] += 1
        complete_event_count += 1

    return VenueGrammar(
        markets=markets,
        strike_counts=strike_counts,
        interior_display_widths=interior_display_widths,
        slug_inner_span_counts=slug_inner_span_counts,
        complete_event_count=complete_event_count,
        lower_anchors=lower_anchors,
        anchor_phases=anchor_phases,
    )


def load_validation_labels(
    *,
    cache_dir: Path,
    sites: Sequence[SiteSpec],
    catalog_base: Path | None,
) -> tuple[str, int, int, tuple[str, ...]]:
    catalog_finals, catalog_details = read_catalog_finals(catalog_base=catalog_base, sites=sites)
    if not catalog_finals:
        return "blocked: validation_unavailable", 0, 0, catalog_details

    dates_by_city: dict[str, list[dt.date]] = defaultdict(list)
    for city, climate_day in catalog_finals:
        dates_by_city[city].append(climate_day)

    mismatches: list[str] = []
    checked = 0
    for spec in sites:
        dates = dates_by_city.get(spec.city)
        if not dates:
            continue
        url = afos_url(spec.site.cli_location, min(dates), max(dates), limit=500)
        zip_bytes = read_cached(cache_dir, url, ".zip")
        labels, _drops, parse_errors = parse_cli_labels_zip(
            city=spec.city,
            site=spec.site,
            zip_bytes=zip_bytes,
            source_url=url,
            start=min(dates),
            end=max(dates),
        )
        for error in parse_errors[:10]:
            mismatches.append(f"validation parse issue: {error}")
        for climate_day in dates:
            key = (spec.city, climate_day)
            archive = labels.get(climate_day)
            if archive is None:
                mismatches.append(f"{spec.city} {climate_day}: missing IEM final label")
                continue
            checked += 1
            catalog_record = catalog_finals[key]
            if archive.tmax_f != catalog_record.tmax_f:
                mismatches.append(
                    f"{spec.city} {climate_day}: catalog tmax={catalog_record.tmax_f}, "
                    f"IEM tmax={archive.tmax_f}, source={archive.source}"
                )

    if mismatches:
        return "blocked: validation_mismatch", checked, len(mismatches), (
            *catalog_details,
            *mismatches,
        )
    return "passed", checked, 0, (
        f"checked {checked} overlapping final Breezy catalog records",
        *catalog_details,
    )


def load_cli_labels_for_site(
    *,
    cache_dir: Path,
    spec: SiteSpec,
    start: dt.date,
    end: dt.date,
) -> tuple[dict[dt.date, CliLabel], Counter[str], tuple[str, ...]]:
    labels: dict[dt.date, CliLabel] = {}
    drops: Counter[str] = Counter()
    errors: list[str] = []
    for chunk_start, chunk_end in year_chunks(start, end):
        url = afos_url(spec.site.cli_location, chunk_start, chunk_end, limit=3_000)
        zip_bytes = read_cached(cache_dir, url, ".zip")
        chunk_labels, chunk_drops, chunk_errors = parse_cli_labels_zip(
            city=spec.city,
            site=spec.site,
            zip_bytes=zip_bytes,
            source_url=url,
            start=chunk_start,
            end=chunk_end,
        )
        labels.update(chunk_labels)
        drops.update(chunk_drops)
        errors.extend(chunk_errors)
    return labels, drops, tuple(errors)


def load_metar_maxima_for_site(
    *,
    cache_dir: Path,
    spec: SiteSpec,
    start: dt.date,
    end: dt.date,
) -> tuple[dict[dt.date, DailyMetarMax], Counter[str]]:
    url = asos_url(spec.iem_asos_id, start, end)
    raw = read_cached(cache_dir, url, ".txt").decode("utf-8", errors="replace")
    rows = parse_asos_rows(raw)
    temperatures, drops = metar_temperatures(
        city=spec.city,
        rows=rows,
        std_utc_offset_hours=spec.std_utc_offset_hours,
    )
    filtered = tuple(row for row in temperatures if start <= row.climate_day <= end)
    return daily_metar_maxima(filtered, source=url), drops


def load_daily_comparisons(
    *,
    cache_dir: Path,
    sites: Sequence[SiteSpec],
    start: dt.date,
    end: dt.date,
) -> tuple[tuple[DailyComparison, ...], Counter[str], tuple[str, ...]]:
    comparisons: list[DailyComparison] = []
    drops: Counter[str] = Counter()
    parse_errors: list[str] = []
    for spec in sites:
        labels, cli_drops, cli_errors = load_cli_labels_for_site(
            cache_dir=cache_dir,
            spec=spec,
            start=start,
            end=end,
        )
        maxima, metar_drops = load_metar_maxima_for_site(
            cache_dir=cache_dir,
            spec=spec,
            start=start,
            end=end,
        )
        drops.update({f"{spec.city}:{key}": value for key, value in cli_drops.items()})
        drops.update({f"{spec.city}:{key}": value for key, value in metar_drops.items()})
        parse_errors.extend(cli_errors)
        for climate_day, label in labels.items():
            if label.tmax_f is None:
                drops[f"{spec.city}:cli_sentinel"] += 1
                continue
            maximum = maxima.get(climate_day)
            if maximum is None:
                drops[f"{spec.city}:missing_metar_t_group"] += 1
                continue
            comparisons.append(
                DailyComparison(
                    city=spec.city,
                    climate_day=climate_day,
                    cli_tmax_f=label.tmax_f,
                    metar_rounded_max_f=maximum.rounded_max_f,
                    metar_unrounded_max_f=maximum.unrounded_max_f,
                    cli_source=label.source,
                    metar_source=maximum.source,
                )
            )
        for climate_day in maxima:
            if climate_day not in labels:
                drops[f"{spec.city}:missing_cli_final"] += 1
    return (
        tuple(sorted(comparisons, key=lambda row: (row.city, row.climate_day))),
        drops,
        tuple(parse_errors),
    )


def bucket_id(value_f: int, phase: float) -> int:
    return math.floor((value_f - phase) / BUCKET_WIDTH_F)


def edge_distance(value_f: int, phase: float) -> float:
    residual = (value_f - phase) % BUCKET_WIDTH_F
    return round(min(residual, BUCKET_WIDTH_F - residual), 10)


def phase_cases(comparisons: Iterable[DailyComparison]) -> tuple[PhaseCase, ...]:
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
                    edge_distance_f=edge_distance(comparison.cli_tmax_f, phase),
                )
            )
    return tuple(cases)


def summarize(cases: Iterable[PhaseCase]) -> AgreementStats:
    materialized = tuple(cases)
    agreements = sum(1 for case in materialized if case.agreed)
    count = len(materialized)
    return AgreementStats(
        cases=count,
        agreements=agreements,
        rate=agreements / count if count else 0.0,
        wilson_lower=wilson_lower_bound(agreements, count),
        metar_below_cli=sum(1 for case in materialized if case.miss_direction == "METAR below CLI"),
        metar_above_cli=sum(1 for case in materialized if case.miss_direction == "METAR above CLI"),
    )


def verdict(stats: AgreementStats, *, min_cases: int) -> str:
    if stats.cases < min_cases:
        return "FAIL: insufficient sample"
    if stats.wilson_lower > PASS_WILSON_LOWER:
        return "PASS"
    return "FAIL"


def format_rate(value: float) -> str:
    return f"{value:.6f}"


def counter_text(counter: Counter[int] | Counter[str]) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{key}: {counter[key]}" for key in sorted(counter))


def grammar_markdown(grammar: VenueGrammar) -> list[str]:
    sample_slugs = [market.slug for market in grammar.markets[:10]]
    return [
        "## Venue Bucket Grammar",
        "",
        f"Parsed captured temperature market slugs: {len(grammar.markets)}",
        f"Strike forms: {counter_text(grammar.strike_counts)}",
        f"Interior slug upper-minus-lower spans: {counter_text(grammar.slug_inner_span_counts)}",
        (
            "Interior displayed integer bucket widths: "
            f"{counter_text(grammar.interior_display_widths)}"
        ),
        f"Complete captured event ladders: {grammar.complete_event_count}",
        f"Observed lower interior anchors: {counter_text(grammar.lower_anchors)}",
        f"Observed anchor parity modulo 2F: {counter_text(grammar.anchor_phases)}",
        "",
        "Interpretation used for this gate:",
        "",
        "- Lower tail `ltNf`: integer CLI values below `N`.",
        (
            "- Interior `gteNltN+1f`: displayed as `N to N+1`, treated as "
            "integer values `N` and `N+1`."
        ),
        "- Upper tail `gteNf`: integer CLI values greater than or equal to `N`.",
        "- Captured complete ladders have two-degree interior buckets and two-degree spacing.",
        (
            "- Captured lower anchors vary, including both modulo-2 parities, so "
            "the ladder appears forecast-anchored rather than a fixed absolute "
            "integer lattice."
        ),
        "",
        "First parsed sample slugs:",
        "",
        *(f"- `{slug}`" for slug in sample_slugs),
        "",
    ]


def phase_summary_rows(cases: Sequence[PhaseCase]) -> list[str]:
    by_phase: dict[float, list[PhaseCase]] = defaultdict(list)
    for case in cases:
        by_phase[case.phase].append(case)
    rows = [
        (
            "| Phase offset F | Cases | Agreements | Misses | Agreement rate | "
            "Wilson 95% lower | METAR bucket below CLI | METAR bucket above CLI | "
            "Verdict |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for phase in PHASES:
        stats = summarize(by_phase[phase])
        rows.append(
            f"| {phase:.1f} | {stats.cases} | {stats.agreements} | "
            f"{stats.cases - stats.agreements} | {format_rate(stats.rate)} | "
            f"{format_rate(stats.wilson_lower)} | {stats.metar_below_cli} | "
            f"{stats.metar_above_cli} | {verdict(stats, min_cases=MIN_TOTAL_DAYS)} |"
        )
    return rows


def city_worst_phase_rows(cases: Sequence[PhaseCase]) -> list[str]:
    by_city_phase: dict[tuple[str, float], list[PhaseCase]] = defaultdict(list)
    for case in cases:
        by_city_phase[(case.city, case.phase)].append(case)
    rows = [
        (
            "| City | Worst phase F | Cases | Agreements | Misses | Agreement rate | "
            "Wilson 95% lower | METAR bucket below CLI | METAR bucket above CLI | "
            "Verdict |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for city in sorted({case.city for case in cases}):
        phase_stats = [
            (phase, summarize(by_city_phase[(city, phase)]))
            for phase in PHASES
        ]
        phase, stats = min(phase_stats, key=lambda item: (item[1].wilson_lower, item[1].rate))
        city_verdict = "PASS" if all(
            verdict(item_stats, min_cases=MIN_CITY_DAYS) == "PASS"
            for _item_phase, item_stats in phase_stats
        ) else "FAIL"
        rows.append(
            f"| {city} | {phase:.1f} | {stats.cases} | {stats.agreements} | "
            f"{stats.cases - stats.agreements} | {format_rate(stats.rate)} | "
            f"{format_rate(stats.wilson_lower)} | {stats.metar_below_cli} | "
            f"{stats.metar_above_cli} | {city_verdict} |"
        )
    return rows


def city_phase_rows(cases: Sequence[PhaseCase]) -> list[str]:
    by_city_phase: dict[tuple[str, float], list[PhaseCase]] = defaultdict(list)
    for case in cases:
        by_city_phase[(case.city, case.phase)].append(case)
    rows = [
        (
            "| City | Phase offset F | Cases | Agreements | Misses | Agreement rate | "
            "Wilson 95% lower | METAR bucket below CLI | METAR bucket above CLI | "
            "Verdict |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for city in sorted({case.city for case in cases}):
        for phase in PHASES:
            stats = summarize(by_city_phase[(city, phase)])
            rows.append(
                f"| {city} | {phase:.1f} | {stats.cases} | {stats.agreements} | "
                f"{stats.cases - stats.agreements} | {format_rate(stats.rate)} | "
                f"{format_rate(stats.wilson_lower)} | {stats.metar_below_cli} | "
                f"{stats.metar_above_cli} | {verdict(stats, min_cases=MIN_CITY_DAYS)} |"
            )
    return rows


def edge_distance_rows(cases: Sequence[PhaseCase]) -> list[str]:
    by_distance: dict[float, list[PhaseCase]] = defaultdict(list)
    for case in cases:
        by_distance[case.edge_distance_f].append(case)
    rows = [
        (
            "| CLI distance to nearest bucket edge F | Cases | Agreements | Misses | "
            "Agreement rate | Wilson 95% lower | METAR bucket below CLI | "
            "METAR bucket above CLI |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for distance in sorted(by_distance):
        stats = summarize(by_distance[distance])
        rows.append(
            f"| {distance:.1f} | {stats.cases} | {stats.agreements} | "
            f"{stats.cases - stats.agreements} | {format_rate(stats.rate)} | "
            f"{format_rate(stats.wilson_lower)} | {stats.metar_below_cli} | "
            f"{stats.metar_above_cli} |"
        )
    return rows


def total_verdict(cases: Sequence[PhaseCase]) -> str:
    if not cases:
        return "FAIL"
    by_phase: dict[float, list[PhaseCase]] = defaultdict(list)
    by_city_phase: dict[tuple[str, float], list[PhaseCase]] = defaultdict(list)
    for case in cases:
        by_phase[case.phase].append(case)
        by_city_phase[(case.city, case.phase)].append(case)
    total_pass = all(
        verdict(summarize(by_phase[phase]), min_cases=MIN_TOTAL_DAYS) == "PASS"
        for phase in PHASES
    )
    city_pass = all(
        verdict(summarize(by_city_phase[(city, phase)]), min_cases=MIN_CITY_DAYS) == "PASS"
        for city in {case.city for case in cases}
        for phase in PHASES
    )
    return "PASS" if total_pass and city_pass else "FAIL"


def markdown_report(
    *,
    command: str,
    cache_dir: Path,
    catalog_base: Path | None,
    validation_status: str,
    validation_checked: int,
    validation_mismatches: int,
    validation_details: Sequence[str],
    grammar: VenueGrammar,
    comparisons: Sequence[DailyComparison],
    cases: Sequence[PhaseCase],
    drops: Counter[str],
    parse_errors: Sequence[str],
) -> str:
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    window_days = (END_DATE - START_DATE).days + 1
    phase2_verdict = "FAIL" if validation_status != "passed" else total_verdict(cases)
    lines = [
        "# Settlement Bucket Gate Evidence",
        "",
        f"Generated at: {generated_at.isoformat()}",
        f"Phase 2 bucket-alignment gate: **{phase2_verdict}**",
        f"Pre-registration: `{PREREGISTRATION_PATH}`",
        f"Command: `{command}`",
        f"Catalog base: `{catalog_base}`",
        f"Cache dir: `{cache_dir}`",
        "",
        "## Registered Gate",
        "",
        (
            f"- Historical window: {START_DATE.isoformat()} through "
            f"{END_DATE.isoformat()} ({window_days} days)"
        ),
        (
            "- Bucket agreement: symmetric same-bucket comparison of final CLI "
            "`tmax_f` and METAR rounded daily maximum."
        ),
        (
            f"- Reconstructed lattice: two-degree buckets, phase offsets "
            f"{PHASES[0]:.1f}F through {PHASES[-1]:.1f}F in 0.1F steps."
        ),
        f"- Pass threshold: Wilson 95% lower bound strictly greater than {PASS_WILSON_LOWER:.4f}.",
        (
            f"- Minimum sample: {MIN_CITY_DAYS} eligible city-days per city and "
            f"{MIN_TOTAL_DAYS} eligible city-days total at every phase."
        ),
        "- Phase 2 passes only if every city and the total pass at every preregistered phase.",
        "",
        "## Methodological Limitation",
        "",
        (
            "The captured venue markets are from 2026 only; no 2021-2025 "
            "historical venue bucket ladders are present in the captured data. "
            "This report therefore reconstructs an infinite two-degree ladder "
            "and treats the preregistered phase sweep as the evidence."
        ),
        "",
        *grammar_markdown(grammar),
        "## Archive Validation Bridge",
        "",
        f"Status: **{validation_status}**",
        f"Checked overlapping final records: {validation_checked}",
        f"Mismatches: {validation_mismatches}",
        "",
    ]
    lines.extend(f"- {detail}" for detail in validation_details)
    lines.append("")

    if validation_status != "passed":
        lines.extend(
            [
                "## Evaluation",
                "",
                "Not computed because the validation bridge did not pass.",
                "",
            ]
        )
    else:
        lines.extend(
            [
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
        lines.extend(
            [
                "",
                "## Per-City Verdicts",
                "",
                (
                    "Worst phase is the preregistered phase with the lowest "
                    "Wilson lower bound for that city."
                ),
                "",
                *city_worst_phase_rows(cases),
                "",
                "## Lattice Offset Sensitivity",
                "",
                *phase_summary_rows(cases),
                "",
                "## Per-City By Phase",
                "",
                *city_phase_rows(cases),
                "",
                "## Agreement By CLI Distance To Bucket Edge",
                "",
                *edge_distance_rows(cases),
                "",
            ]
        )

    lines.extend(["## Drop Counts", ""])
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
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-base", type=Path, default=os.environ.get("BREEZY_CATALOG_BASE"))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--venue-raw-dir", type=Path, default=VENUE_RAW_DIR)
    parser.add_argument("--start-date", type=dt.date.fromisoformat, default=START_DATE)
    parser.add_argument("--end-date", type=dt.date.fromisoformat, default=END_DATE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.start_date != START_DATE or args.end_date != END_DATE:
        raise SystemExit("start/end date overrides would violate the pre-registration")

    sites = load_sites()
    grammar = derive_venue_grammar(args.venue_raw_dir)
    validation_status, checked, mismatches, validation_details = load_validation_labels(
        cache_dir=args.cache_dir,
        sites=sites,
        catalog_base=args.catalog_base,
    )

    drops: Counter[str] = Counter()
    parse_errors: tuple[str, ...] = ()
    comparisons: tuple[DailyComparison, ...] = ()
    cases: tuple[PhaseCase, ...] = ()
    if validation_status == "passed":
        comparisons, drops, parse_errors = load_daily_comparisons(
            cache_dir=args.cache_dir,
            sites=sites,
            start=START_DATE,
            end=END_DATE,
        )
        cases = phase_cases(comparisons)
    else:
        drop_reason = (
            "validation_unavailable"
            if "unavailable" in validation_status
            else "validation_mismatch"
        )
        drops[drop_reason] = 1

    command = " ".join([sys.executable, *sys.argv])
    report = markdown_report(
        command=command,
        cache_dir=args.cache_dir,
        catalog_base=args.catalog_base,
        validation_status=validation_status,
        validation_checked=checked,
        validation_mismatches=mismatches,
        validation_details=validation_details,
        grammar=grammar,
        comparisons=comparisons,
        cases=cases,
        drops=drops,
        parse_errors=parse_errors,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0 if validation_status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
