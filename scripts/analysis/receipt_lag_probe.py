"""Measure Breezy receipt lag for persisted NWS CLI climate-day records.

This script is deliberately outside ``src/breezy``. It reads existing Breezy
catalog roots directly and never calls ``open_station_catalog`` because that
helper creates missing directories.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import pyarrow as pa
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.persistence.catalog import read_climate_days, read_raw_products, station_catalog_path
from breezy.registry.sites import default_registry

VENUE: Final[str] = "polymarket_us"
DEFAULT_CATALOG_BASE: Final[Path] = Path("/home/jon/.local/share/breezy/catalog")
DEFAULT_OUTPUT_PATH: Final[Path] = Path(
    "docs/evidence/ingestion/RECEIPT_LAG_2026-08-29.md",
)
RECOVERY_WINDOW_START: Final[dt.datetime] = dt.datetime(
    2026,
    8,
    24,
    19,
    50,
    55,
    tzinfo=dt.UTC,
)
RECOVERY_WINDOW_END_EXCLUSIVE: Final[dt.datetime] = dt.datetime(
    2026,
    8,
    24,
    19,
    55,
    9,
    tzinfo=dt.UTC,
)

MONTH_ABBR: Final[dict[str, int]] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
TZ_OFFSETS: Final[dict[str, int]] = {
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "PST": -8,
    "PDT": -7,
}
ISSUED_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<hour>\d{1,2})(?P<minute>\d{2})\s+"
    r"(?P<ampm>AM|PM)\s+(?P<tz>[A-Z]{3})\s+\w+\s+"
    r"(?P<month>[A-Z]{3})\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})"
)
WMO_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<collective>[A-Z]{4}\d{2})\s+"
    r"(?P<office>K[A-Z]{3})\s+"
    r"(?P<day>\d{2})(?P<hour>\d{2})(?P<minute>\d{2})"
    r"(?:\s+(?P<bbb>[A-Z]{3}))?$"
)
NANOS_PER_SECOND: Final[int] = 1_000_000_000

IssuanceSource = Literal["issued_line", "wmo_heading"]
Population = Literal["recovery_ingestion", "steady_state"]


@dataclass(frozen=True, slots=True)
class SiteSpec:
    city: str
    cli_location: str


@dataclass(frozen=True, slots=True)
class DerivedIssuance:
    instant_ns: int
    source: IssuanceSource
    issued_line_minus_wmo_seconds: float | None


@dataclass(frozen=True, slots=True)
class Measurement:
    city: str
    station: str
    climate_day: dt.date
    issuance_class: str
    lag_seconds: float
    ts_init_ns: int
    issuance_ns: int
    raw_sha256: str
    issuance_source: IssuanceSource
    record_issuance_delta_seconds: float
    issued_line_minus_wmo_seconds: float | None
    population: Population


@dataclass(frozen=True, slots=True)
class NonDerivable:
    city: str
    station: str
    climate_day: dt.date
    issuance_class: str
    raw_sha256: str
    reason: str


@dataclass(frozen=True, slots=True)
class SiteReadResult:
    measurements: tuple[Measurement, ...]
    non_derivable: tuple[NonDerivable, ...]
    read_errors: tuple[str, ...]
    climate_records: int
    raw_product_records: int
    expected_station_records: int
    wrong_station_records: int


@dataclass(frozen=True, slots=True)
class Distribution:
    count: int
    min_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None
    p95_seconds: float | None
    p99_seconds: float | None
    max_seconds: float | None


def _ns_to_utc(ns: int) -> str:
    seconds, nanos = divmod(ns, NANOS_PER_SECOND)
    stamp = dt.datetime.fromtimestamp(seconds, tz=dt.UTC).replace(microsecond=nanos // 1000)
    return stamp.isoformat()


def _seconds(delta_ns: int) -> float:
    return delta_ns / NANOS_PER_SECOND


def _datetime_to_ns(value: dt.datetime) -> int:
    return int(value.timestamp() * NANOS_PER_SECOND)


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value == 0:
        return "0.0"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3f}"


def _format_signed_seconds(value: float) -> str:
    return f"{value:+.3f}"


def _format_minutes(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value / 60:.2f}"


def _nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if percentile <= 0:
        return min(values)
    if percentile >= 1:
        return max(values)
    ordered = sorted(values)
    index = math.ceil(percentile * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def distribution(values: Sequence[float]) -> Distribution:
    if not values:
        return Distribution(
            count=0,
            min_seconds=None,
            p50_seconds=None,
            p90_seconds=None,
            p95_seconds=None,
            p99_seconds=None,
            max_seconds=None,
        )
    return Distribution(
        count=len(values),
        min_seconds=min(values),
        p50_seconds=_nearest_rank(values, 0.50),
        p90_seconds=_nearest_rank(values, 0.90),
        p95_seconds=_nearest_rank(values, 0.95),
        p99_seconds=_nearest_rank(values, 0.99),
        max_seconds=max(values),
    )


def parse_issued_line(raw_text: str) -> int | None:
    match = ISSUED_RE.search(raw_text)
    if match is None:
        return None

    hour = int(match.group("hour"))
    if match.group("ampm") == "PM" and hour != 12:
        hour += 12
    if match.group("ampm") == "AM" and hour == 12:
        hour = 0

    offset = TZ_OFFSETS.get(match.group("tz"))
    month = MONTH_ABBR.get(match.group("month"))
    if offset is None or month is None:
        return None

    local = dt.datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        hour,
        int(match.group("minute")),
        tzinfo=dt.timezone(dt.timedelta(hours=offset)),
    )
    return int(local.astimezone(dt.UTC).timestamp() * NANOS_PER_SECOND)


def _candidate_months(anchor: dt.datetime) -> Iterable[tuple[int, int]]:
    previous = (anchor.replace(day=1) - dt.timedelta(days=1)).date()
    current = anchor.date()
    next_month = (anchor.replace(day=28) + dt.timedelta(days=4)).date()
    yield previous.year, previous.month
    yield current.year, current.month
    yield next_month.year, next_month.month


def parse_wmo_heading(raw_text: str, *, retrieved_at_ns: int) -> int | None:
    retrieved_at = dt.datetime.fromtimestamp(retrieved_at_ns / NANOS_PER_SECOND, tz=dt.UTC)
    candidates: list[dt.datetime] = []
    for line in raw_text.splitlines():
        match = WMO_HEADING_RE.fullmatch(line.strip())
        if match is None:
            continue
        day = int(match.group("day"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        for year, month in _candidate_months(retrieved_at):
            try:
                candidate = dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC)
            except ValueError:
                continue
            if candidate <= retrieved_at:
                candidates.append(candidate)
    if not candidates:
        return None
    latest = max(candidates)
    return int(latest.timestamp() * NANOS_PER_SECOND)


def derive_issuance(raw_product: NwsRawProduct) -> DerivedIssuance | None:
    issued_line_ns = parse_issued_line(raw_product.raw_text)
    wmo_ns = parse_wmo_heading(raw_product.raw_text, retrieved_at_ns=raw_product.retrieved_at_ns)
    if wmo_ns is not None:
        return DerivedIssuance(
            instant_ns=wmo_ns,
            source="wmo_heading",
            issued_line_minus_wmo_seconds=(
                _seconds(issued_line_ns - wmo_ns) if issued_line_ns is not None else None
            ),
        )

    if issued_line_ns is not None:
        return DerivedIssuance(
            instant_ns=issued_line_ns,
            source="issued_line",
            issued_line_minus_wmo_seconds=None,
        )

    return None


def classify_population(ts_init_ns: int) -> Population:
    """Split restart recovery from later routine polling using observed restart evidence."""
    if (
        _datetime_to_ns(RECOVERY_WINDOW_START)
        <= ts_init_ns
        < _datetime_to_ns(RECOVERY_WINDOW_END_EXCLUSIVE)
    ):
        return "recovery_ingestion"
    return "steady_state"


def load_sites() -> tuple[SiteSpec, ...]:
    registry = default_registry()
    sites: list[SiteSpec] = []
    for venue, city in registry.pairs():
        if venue != VENUE:
            continue
        settlement_site = registry.settlement_site(venue, city)
        sites.append(SiteSpec(city=city, cli_location=settlement_site.cli_location))
    return tuple(sites)


def _raw_by_sha(raw_products: Sequence[NwsRawProduct]) -> dict[str, NwsRawProduct]:
    by_sha: dict[str, NwsRawProduct] = {}
    for raw_product in raw_products:
        by_sha.setdefault(raw_product.raw_sha256, raw_product)
    return by_sha


def analyze_site(catalog_base: Path, spec: SiteSpec) -> SiteReadResult:
    root = station_catalog_path(catalog_base, VENUE, spec.city)
    if not root.exists():
        missing = NonDerivable(
            city=spec.city,
            station=spec.cli_location,
            climate_day=dt.date.min,
            issuance_class="unknown",
            raw_sha256="",
            reason=f"missing station catalog root: {root}",
        )
        return SiteReadResult(
            measurements=(),
            non_derivable=(missing,),
            read_errors=(),
            climate_records=0,
            raw_product_records=0,
            expected_station_records=0,
            wrong_station_records=0,
        )

    try:
        catalog = ParquetDataCatalog(path=root)
        climate_records = tuple(read_climate_days(catalog))
        raw_products = tuple(read_raw_products(catalog))
    except (OSError, RuntimeError, ValueError, pa.ArrowException) as exc:
        return SiteReadResult(
            measurements=(),
            non_derivable=(),
            read_errors=(f"{spec.city}: {type(exc).__name__}: {exc}",),
            climate_records=0,
            raw_product_records=0,
            expected_station_records=0,
            wrong_station_records=0,
        )

    raw_lookup = _raw_by_sha(raw_products)
    measurements: list[Measurement] = []
    non_derivable: list[NonDerivable] = []
    expected_records = tuple(
        record for record in climate_records if record.station == spec.cli_location
    )

    for record in expected_records:
        issuance_class = "final" if record.is_final else "preliminary"
        raw_product = raw_lookup.get(record.raw_sha256)
        if raw_product is None:
            non_derivable.append(
                NonDerivable(
                    city=spec.city,
                    station=record.station,
                    climate_day=record.climate_day,
                    issuance_class=issuance_class,
                    raw_sha256=record.raw_sha256,
                    reason="no raw product with matching raw_sha256",
                )
            )
            continue

        if not raw_product.verify_digest():
            non_derivable.append(
                NonDerivable(
                    city=spec.city,
                    station=record.station,
                    climate_day=record.climate_day,
                    issuance_class=issuance_class,
                    raw_sha256=record.raw_sha256,
                    reason="raw product digest verification failed",
                )
            )
            continue

        derived = derive_issuance(raw_product)
        if derived is None:
            non_derivable.append(
                NonDerivable(
                    city=spec.city,
                    station=record.station,
                    climate_day=record.climate_day,
                    issuance_class=issuance_class,
                    raw_sha256=record.raw_sha256,
                    reason="neither WMO heading nor ISSUED/local-time line was parseable",
                )
            )
            continue

        measurements.append(
            Measurement(
                city=spec.city,
                station=record.station,
                climate_day=record.climate_day,
                issuance_class=issuance_class,
                lag_seconds=_seconds(record.ts_init - derived.instant_ns),
                ts_init_ns=record.ts_init,
                issuance_ns=derived.instant_ns,
                raw_sha256=record.raw_sha256,
                issuance_source=derived.source,
                record_issuance_delta_seconds=_seconds(
                    record.issuance_time_ns - derived.instant_ns
                ),
                issued_line_minus_wmo_seconds=derived.issued_line_minus_wmo_seconds,
                population=classify_population(record.ts_init),
            )
        )

    return SiteReadResult(
        measurements=tuple(measurements),
        non_derivable=tuple(non_derivable),
        read_errors=(),
        climate_records=len(climate_records),
        raw_product_records=len(raw_products),
        expected_station_records=len(expected_records),
        wrong_station_records=len(climate_records) - len(expected_records),
    )


def _distribution_table(distributions: Mapping[str, Distribution]) -> str:
    rows = [
        "| Group | n | min | p50 | p90 | p95 | max |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group in sorted(distributions):
        dist = distributions[group]
        rows.append(
            "| "
            f"{group} | {dist.count} | {_format_seconds(dist.min_seconds)} | "
            f"{_format_seconds(dist.p50_seconds)} | {_format_seconds(dist.p90_seconds)} | "
            f"{_format_seconds(dist.p95_seconds)} | {_format_seconds(dist.max_seconds)} |"
        )
    return "\n".join(rows)


def _population_distributions(measurements: Sequence[Measurement]) -> dict[str, Distribution]:
    return {
        "steady_state (plan-relevant)": distribution(
            [
                measurement.lag_seconds
                for measurement in measurements
                if measurement.population == "steady_state"
            ]
        ),
        "recovery_ingestion": distribution(
            [
                measurement.lag_seconds
                for measurement in measurements
                if measurement.population == "recovery_ingestion"
            ]
        ),
    }


def _population_class_distributions(
    measurements: Sequence[Measurement],
) -> dict[str, Distribution]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for measurement in measurements:
        grouped[f"{measurement.population} class={measurement.issuance_class}"].append(
            measurement.lag_seconds
        )
    return {group: distribution(values) for group, values in grouped.items()}


def _population_station_distributions(
    measurements: Sequence[Measurement],
) -> dict[str, Distribution]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for measurement in measurements:
        grouped[f"{measurement.population} station={measurement.city}"].append(
            measurement.lag_seconds
        )
    return {group: distribution(values) for group, values in grouped.items()}


def _counter_lines(counter: Counter[str]) -> list[str]:
    if not counter:
        return ["- none"]
    return [f"- {reason}: {count}" for reason, count in sorted(counter.items())]


def _site_table(site_results: Mapping[str, SiteReadResult]) -> str:
    rows = [
        (
            "| City | climate records | expected station records | raw products | measured | "
            "non-derivable | wrong-station |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for city in sorted(site_results):
        result = site_results[city]
        rows.append(
            f"| {city} | {result.climate_records} | {result.expected_station_records} | "
            f"{result.raw_product_records} | {len(result.measurements)} | "
            f"{len(result.non_derivable)} | {result.wrong_station_records} |"
        )
    return "\n".join(rows)


def _retrieval_cluster_table(measurements: Sequence[Measurement]) -> str:
    rows = [
        "| Population | n | first retrieved UTC | last retrieved UTC | min lag | max lag |",
        "|---|---:|---|---|---:|---:|",
    ]
    for population in ("steady_state", "recovery_ingestion"):
        rows_for_population = sorted(
            (measurement for measurement in measurements if measurement.population == population),
            key=lambda item: item.ts_init_ns,
        )
        if not rows_for_population:
            rows.append(f"| {population} | 0 | n/a | n/a | n/a | n/a |")
            continue
        values = [measurement.lag_seconds for measurement in rows_for_population]
        label = (
            "steady_state (plan-relevant)"
            if population == "steady_state"
            else "recovery_ingestion"
        )
        rows.append(
            f"| {label} | {len(rows_for_population)} | "
            f"{_ns_to_utc(rows_for_population[0].ts_init_ns)} | "
            f"{_ns_to_utc(rows_for_population[-1].ts_init_ns)} | "
            f"{_format_seconds(min(values))} | {_format_seconds(max(values))} |"
        )
    return "\n".join(rows)


def _split_boundary_table(measurements: Sequence[Measurement]) -> str:
    steady = [
        measurement for measurement in measurements if measurement.population == "steady_state"
    ]
    recovery = [
        measurement
        for measurement in measurements
        if measurement.population == "recovery_ingestion"
    ]
    if not steady or not recovery:
        return "Split-boundary evidence is unavailable because one population is empty."

    steady_max = max(steady, key=lambda item: item.lag_seconds)
    recovery_min = min(recovery, key=lambda item: item.lag_seconds)
    empty_gap_seconds = recovery_min.lag_seconds - steady_max.lag_seconds
    rows = [
        "| Boundary row | city | climate day | class | retrieved UTC | lag seconds |",
        "|---|---|---|---|---|---:|",
        (
            f"| largest steady-state lag | {steady_max.city} | "
            f"{steady_max.climate_day.isoformat()} | {steady_max.issuance_class} | "
            f"{_ns_to_utc(steady_max.ts_init_ns)} | {_format_seconds(steady_max.lag_seconds)} |"
        ),
        (
            f"| smallest recovery-ingestion lag | {recovery_min.city} | "
            f"{recovery_min.climate_day.isoformat()} | {recovery_min.issuance_class} | "
            f"{_ns_to_utc(recovery_min.ts_init_ns)} | "
            f"{_format_seconds(recovery_min.lag_seconds)} |"
        ),
        (
            "| empty lag interval between them | n/a | n/a | n/a | n/a | "
            f"{_format_seconds(empty_gap_seconds)} |"
        ),
    ]
    return "\n".join(rows)


def _lag_histogram_table(measurements: Sequence[Measurement]) -> str:
    buckets: tuple[tuple[str, float | None], ...] = (
        ("<=5m", 300.0),
        ("5-10m", 600.0),
        ("10-20m", 1_200.0),
        ("20m-1h", 3_600.0),
        ("1-12h", 43_200.0),
        ("12h-2d", 172_800.0),
        ("2-4d", 345_600.0),
        (">4d", None),
    )
    counts: dict[Population, Counter[str]] = {
        "steady_state": Counter(),
        "recovery_ingestion": Counter(),
    }

    for measurement in measurements:
        lower = 0.0
        for label, upper in buckets:
            if upper is None or lower < measurement.lag_seconds <= upper:
                counts[measurement.population][label] += 1
                break
            lower = upper

    rows = [
        "| Lag bucket | steady_state | recovery_ingestion |",
        "|---|---:|---:|",
    ]
    for label, _upper in buckets:
        rows.append(
            f"| {label} | {counts['steady_state'][label]} | "
            f"{counts['recovery_ingestion'][label]} |"
        )
    return "\n".join(rows)


def _steady_state_sample_note(measurements: Sequence[Measurement]) -> str:
    steady_values = sorted(
        measurement.lag_seconds
        for measurement in measurements
        if measurement.population == "steady_state"
    )
    if len(steady_values) < 20:
        return (
            f"The steady-state sample has n={len(steady_values)}, below the n=20 floor. "
            "Do not treat its percentile estimates as plan-grade; collect more routine "
            "polling rows before writing a latency number into the plan."
        )
    p95_rank = math.ceil(0.95 * len(steady_values))
    p95_value = steady_values[p95_rank - 1]
    return (
        f"The steady-state sample has n={len(steady_values)}, above the n=20 stop line "
        "but still small. The nearest-rank p95 is rank "
        f"{p95_rank}/{len(steady_values)} = {_format_seconds(p95_value)} seconds "
        f"({_format_minutes(p95_value)} minutes); the observed max is "
        f"{_format_seconds(max(steady_values))} seconds "
        f"({_format_minutes(max(steady_values))} minutes)."
    )


def _negative_lag_section(measurements: Sequence[Measurement]) -> str:
    negatives = [measurement for measurement in measurements if measurement.lag_seconds < 0]
    if not negatives:
        return "No negative lags were observed."

    rows = [
        (
            "| City | station | climate day | class | lag seconds | ts_init UTC | "
            "issuance UTC | raw_sha256 |"
        ),
        "|---|---|---|---|---:|---|---|---|",
    ]
    for measurement in sorted(negatives, key=lambda item: item.lag_seconds):
        rows.append(
            f"| {measurement.city} | {measurement.station} | "
            f"{measurement.climate_day.isoformat()} | {measurement.issuance_class} | "
            f"{_format_seconds(measurement.lag_seconds)} | {_ns_to_utc(measurement.ts_init_ns)} | "
            f"{_ns_to_utc(measurement.issuance_ns)} | `{measurement.raw_sha256}` |"
        )
    return "\n".join(rows)


def _record_issuance_check(measurements: Sequence[Measurement]) -> str:
    mismatches = [
        measurement
        for measurement in measurements
        if abs(measurement.record_issuance_delta_seconds) > 60.0
    ]
    if not mismatches:
        return (
            "All measured rows had climate-day `issuance_time_ns` within 60 seconds of "
            "the parsed raw-product issuance instant."
        )

    rows = [
        "| City | climate day | class | record minus parsed seconds | raw_sha256 |",
        "|---|---|---|---:|---|",
    ]
    for measurement in sorted(mismatches, key=lambda item: abs(item.record_issuance_delta_seconds)):
        rows.append(
            f"| {measurement.city} | {measurement.climate_day.isoformat()} | "
            f"{measurement.issuance_class} | "
            f"{_format_signed_seconds(measurement.record_issuance_delta_seconds)} | "
            f"`{measurement.raw_sha256}` |"
        )
    return "\n".join(rows)


def _issued_line_disagreement_section(measurements: Sequence[Measurement]) -> str:
    disagreements = [
        measurement
        for measurement in measurements
        if measurement.issued_line_minus_wmo_seconds is not None
        and abs(measurement.issued_line_minus_wmo_seconds) > 60.0
    ]
    if not disagreements:
        return "No WMO-vs-local-issue-line disagreements above 60 seconds were observed."

    rows = [
        "| City | climate day | class | issued line minus WMO seconds | raw_sha256 |",
        "|---|---|---|---:|---|",
    ]
    for measurement in sorted(
        disagreements,
        key=lambda item: abs(item.issued_line_minus_wmo_seconds or 0.0),
        reverse=True,
    ):
        assert measurement.issued_line_minus_wmo_seconds is not None
        rows.append(
            f"| {measurement.city} | {measurement.climate_day.isoformat()} | "
            f"{measurement.issuance_class} | "
            f"{_format_signed_seconds(measurement.issued_line_minus_wmo_seconds)} | "
            f"`{measurement.raw_sha256}` |"
        )
    return "\n".join(rows)


def _non_derivable_section(non_derivable: Sequence[NonDerivable]) -> str:
    if not non_derivable:
        return "No records were non-derivable."

    rows = [
        "| City | station | climate day | class | reason | raw_sha256 |",
        "|---|---|---|---|---|---|",
    ]
    for drop in non_derivable:
        climate_day = "n/a" if drop.climate_day == dt.date.min else drop.climate_day.isoformat()
        raw_sha = "n/a" if not drop.raw_sha256 else f"`{drop.raw_sha256}`"
        rows.append(
            f"| {drop.city} | {drop.station} | {climate_day} | {drop.issuance_class} | "
            f"{drop.reason} | {raw_sha} |"
        )
    return "\n".join(rows)


def render_report(
    *,
    catalog_base: Path,
    site_results: Mapping[str, SiteReadResult],
    measurements: Sequence[Measurement],
    non_derivable: Sequence[NonDerivable],
    read_errors: Sequence[str],
) -> str:
    mixed_distribution = distribution([measurement.lag_seconds for measurement in measurements])
    population_distributions = _population_distributions(measurements)
    steady = population_distributions["steady_state (plan-relevant)"]
    recovery = population_distributions["recovery_ingestion"]
    source_counts = Counter(measurement.issuance_source for measurement in measurements)
    non_derivable_reasons = Counter(drop.reason for drop in non_derivable)
    negatives = [measurement for measurement in measurements if measurement.lag_seconds < 0]
    generated_at = dt.datetime.now(tz=dt.UTC).replace(microsecond=0).isoformat()

    if steady.count >= 20:
        implication = (
            "For the backfill plan, use the steady-state population, not the pooled "
            f"distribution: current observed steady-state p95 is "
            f"{_format_seconds(steady.p95_seconds)} seconds "
            f"({_format_minutes(steady.p95_seconds)} minutes), with an observed steady-state "
            f"max of {_format_seconds(steady.max_seconds)} seconds "
            f"({_format_minutes(steady.max_seconds)} minutes). This is a provisional "
            f"n={steady.count} estimate, not a long-run SLO."
        )
    else:
        implication = (
            "The steady-state sample is too small to write a plan-grade percentile. "
            "The plan should state that more routine polling rows are needed before "
            "quantifying live knowledge delay."
        )

    return "\n".join(
        [
            "# Receipt Lag Probe",
            "",
            f"Generated: {generated_at}",
            "",
            f"Catalog base: `{catalog_base}`",
            "",
            "## Scope",
            "",
            (
                "This is a read-only measurement of the live Breezy NWS catalog. The probe "
                "opened existing station roots directly with `ParquetDataCatalog(path=...)` "
                "and did not call `open_station_catalog()`, because that helper creates "
                "missing catalog directories."
            ),
            "",
            (
                "The sample is small and operationally local: it covers only the records "
                "currently present in this catalog. High percentiles inside station/class "
                "splits are order statistics from a handful of rows and should be treated as "
                "a current sanity measurement, not a settled long-run service-level estimate."
            ),
            "",
            "## Issuance Derivation",
            "",
            (
                "For each `NwsClimateDay`, the probe joined to `NwsRawProduct` by "
                "`raw_sha256`, verified the raw-product digest, and parsed issuance from the "
                "raw product text. The primary parser reads the WMO heading day/hour/minute "
                "and anchors month/year from the product receipt timestamp. That matches the "
                "plan's WMO issuance-clock language and avoids treating a correction product's "
                "stale body issue line as the correction issuance. If the WMO heading is "
                "unavailable, the fallback uses the same local-time issuance-line pattern as "
                "`scripts/analysis/settlement_alignment_study.py`. The climate-day "
                "`issuance_time_ns` field is checked against the derived instant but is not "
                "the primary derivation source."
            ),
            "",
            "## Population Split",
            "",
            (
                "The catalog does not carry a row-level `gap_recovery` vs `routine_poll` fetch "
                "path marker. `source_channel` is the fetched product URL, so it identifies the "
                "NWS product but not the caller path that fetched it."
            ),
            "",
            (
                "The split therefore uses the documented cold-start recovery window from "
                "`docs/evidence/ingestion/COLLECTION_RESTART_2026-08-24.md`: first recovery "
                "poll began at 2026-08-24T19:50:55Z and the final first-poll persistence line "
                "was 2026-08-24T19:55:08Z. Rows with `retrieved_at_ns` in "
                "[2026-08-24T19:50:55Z, 2026-08-24T19:55:09Z) are classified as "
                "`recovery_ingestion`; all later rows are classified as `steady_state`."
            ),
            "",
            _retrieval_cluster_table(measurements),
            "",
            "## Superseded Mixed Figure",
            "",
            (
                "An earlier version of this report pooled steady-state and recovery-ingestion "
                "rows and reported p95 "
                f"{_format_seconds(mixed_distribution.p95_seconds)} seconds. That figure is "
                "superseded because it mixes two populations: routine product polling and "
                "post-restart recovery of products issued days earlier."
            ),
            "",
            "## Plan-Relevant Headline",
            "",
            f"- Records measured: {len(measurements)}",
            f"- Records where issuance was not derivable: {len(non_derivable)}",
            f"- Negative lags: {len(negatives)}",
            f"- Issuance source counts: {dict(sorted(source_counts.items()))}",
            (
                f"- Steady-state p95: {_format_seconds(steady.p95_seconds)} seconds "
                f"({_format_minutes(steady.p95_seconds)} minutes)"
            ),
            f"- Steady-state observed max: {_format_seconds(steady.max_seconds)} seconds",
            f"- Recovery-ingestion p95: {_format_seconds(recovery.p95_seconds)} seconds",
            "",
            _steady_state_sample_note(measurements),
            "",
            "## Lag Distribution By Population",
            "",
            "Percentiles use nearest-rank observed values in seconds.",
            "",
            _distribution_table(population_distributions),
            "",
            "## Lag Distribution By Population And Issuance Class",
            "",
            _distribution_table(_population_class_distributions(measurements)),
            "",
            "## Lag Distribution By Population And Station",
            "",
            _distribution_table(_population_station_distributions(measurements)),
            "",
            "## Split Evidence",
            "",
            "Lag histogram, in fixed human-readable buckets, with the empty middle visible:",
            "",
            _lag_histogram_table(measurements),
            "",
            "Boundary rows around the population separation:",
            "",
            _split_boundary_table(measurements),
            "",
            "## Station Read Summary",
            "",
            _site_table(site_results),
            "",
            "## Non-Derivable Records",
            "",
            "\n".join(_counter_lines(non_derivable_reasons)),
            "",
            _non_derivable_section(non_derivable),
            "",
            "## Negative Lags",
            "",
            _negative_lag_section(measurements),
            "",
            "## Consistency Check",
            "",
            _record_issuance_check(measurements),
            "",
            "## WMO vs Local Issue Line",
            "",
            _issued_line_disagreement_section(measurements),
            "",
            "## Read Errors",
            "",
            "\n".join(f"- {error}" for error in read_errors) if read_errors else "- none",
            "",
            "## Backfill Plan Implication",
            "",
            implication,
            "",
        ]
    )


def run(catalog_base: Path, output_path: Path) -> int:
    if not catalog_base.exists():
        print(f"catalog base does not exist: {catalog_base}", file=sys.stderr)
        return 2

    site_results: dict[str, SiteReadResult] = {}
    all_measurements: list[Measurement] = []
    all_non_derivable: list[NonDerivable] = []
    read_errors: list[str] = []

    for site in load_sites():
        result = analyze_site(catalog_base, site)
        site_results[site.city] = result
        all_measurements.extend(result.measurements)
        all_non_derivable.extend(result.non_derivable)
        read_errors.extend(result.read_errors)

    report = render_report(
        catalog_base=catalog_base,
        site_results=site_results,
        measurements=all_measurements,
        non_derivable=all_non_derivable,
        read_errors=read_errors,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    population_distributions = _population_distributions(all_measurements)
    steady = population_distributions["steady_state (plan-relevant)"]
    recovery = population_distributions["recovery_ingestion"]
    print(
        "measured="
        f"{len(all_measurements)} non_derivable={len(all_non_derivable)} "
        f"negative_lags={sum(1 for item in all_measurements if item.lag_seconds < 0)} "
        f"steady_n={steady.count} steady_p95={_format_seconds(steady.p95_seconds)} "
        f"steady_max={_format_seconds(steady.max_seconds)} "
        f"recovery_n={recovery.count} recovery_p95={_format_seconds(recovery.p95_seconds)} "
        f"output={output_path}"
    )
    if read_errors:
        return 1
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog-base",
        type=Path,
        default=DEFAULT_CATALOG_BASE,
        help=f"live Breezy catalog base to read; default: {DEFAULT_CATALOG_BASE}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"markdown evidence path to write; default: {DEFAULT_OUTPUT_PATH}",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return run(catalog_base=args.catalog_base, output_path=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
