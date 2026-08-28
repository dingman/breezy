"""Offline settlement-alignment study for Breezy weather contracts.

This script is deliberately outside ``src/breezy``. It reads Breezy registry,
climate-day and catalog primitives, but never writes to Breezy's catalog or
state DB. Network responses from IEM are cached under ``scripts/analysis`` by
default so repeated runs do not re-hammer the archives.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlencode
from zipfile import ZipFile

import httpx
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
    resolve_settlement_alignment_cache_dir,
)

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.selection import latest_by_climate_day
from breezy.normalize.classify import ClassificationError, classify_issuance
from breezy.normalize.cli_parse import CliParseError, parse_cli_product
from breezy.normalize.climate_day import climate_day_for_instant
from breezy.persistence.catalog import read_climate_days, read_raw_products, station_catalog_path
from breezy.registry.sites import SettlementSite, default_registry

PREREGISTRATION_PATH: Final[Path] = Path(
    "scripts/analysis/pre_registration_2026-08-24T192643Z.md"
)
DEFAULT_CACHE_DIR: Final[Path] = DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
DEFAULT_EVIDENCE_PATH: Final[Path] = Path(
    "docs/evidence/settlement_alignment_2026-08-24.md"
)
IEM_BASE: Final[str] = "https://mesonet.agron.iastate.edu"
USER_AGENT: Final[str] = (
    "Breezy settlement-alignment offline study/0.1 "
    "(contact: local operator; polite cached research)"
)
VENUE: Final[str] = "polymarket_us"
START_DATE: Final[dt.date] = dt.date(2021, 1, 1)
END_DATE: Final[dt.date] = dt.date(2025, 12, 31)
PRIMARY_BREAK_EVEN: Final[float] = 0.9906
SECONDARY_BREAK_EVEN: Final[float] = 0.9760
MIN_SAMPLE_COUNT: Final[int] = 1_000
IEM_ASOS_IDS: Final[dict[str, str]] = {
    "KNYC": "NYC",
    "KSFO": "SFO",
    "KMIA": "MIA",
    "KMDW": "MDW",
    "KLAX": "LAX",
}
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
METAR_T_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)T(?P<air_sign>[01])(?P<air_tenths>\d{3})[01]\d{3}(?:\s|$)"
)


@dataclass(frozen=True, slots=True)
class SiteSpec:
    city: str
    site: SettlementSite
    std_utc_offset_hours: float
    iem_asos_id: str


@dataclass(frozen=True, slots=True)
class CliLabel:
    city: str
    climate_day: dt.date
    tmax_f: int | None
    tmax_flag: str | None
    is_final: bool
    correction_flag: bool
    issued_at_utc: dt.datetime | None
    source: str
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class MetarTemperature:
    city: str
    valid_utc: dt.datetime
    climate_day: dt.date
    temp_c_tenths: int
    temp_f: float
    rounded_f: int
    raw_metar: str


@dataclass(frozen=True, slots=True)
class DailyMetarMax:
    city: str
    climate_day: dt.date
    rounded_max_f: int
    unrounded_max_f: float
    observation_count: int
    source: str


@dataclass(frozen=True, slots=True)
class ThresholdCase:
    city: str
    climate_day: dt.date
    threshold_f: int
    cli_tmax_f: int
    rounded_metar_max_f: int
    unrounded_metar_max_f: float
    margin_f: int
    bucket: str
    hit: bool
    rounding_sensitive: bool
    cli_source: str
    metar_source: str


@dataclass(frozen=True, slots=True)
class BucketStats:
    sample_count: int
    hit_count: int
    hit_rate: float
    wilson_95_lower: float


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: str
    checked_count: int
    mismatch_count: int
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogSiteSummary:
    city: str
    expected_cli_location: str
    climate_records: int
    raw_product_records: int
    final_records: int
    preliminary_records: int
    wrong_station_records: int
    corrected_final_records: int
    first_climate_day: dt.date | None
    last_climate_day: dt.date | None


def round_half_up_f(c_tenths: int) -> int:
    fahrenheit = (c_tenths / 10.0) * 9.0 / 5.0 + 32.0
    return math.floor(fahrenheit + 0.5)


def c_tenths_to_f(c_tenths: int) -> float:
    return (c_tenths / 10.0) * 9.0 / 5.0 + 32.0


def bucket_for_margin(margin_f: int) -> str:
    if margin_f == 0:
        return "0-1F"
    if margin_f == 1:
        return "1-2F"
    if margin_f == 2:
        return "2-3F"
    return "3F+"


def wilson_lower_bound(hit_count: int, sample_count: int, z: float = 1.959963984540054) -> float:
    if sample_count == 0:
        return 0.0
    phat = hit_count / sample_count
    denom = 1.0 + z * z / sample_count
    centre = phat + z * z / (2.0 * sample_count)
    radius = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * sample_count)) / sample_count)
    return (centre - radius) / denom


def summarize_cases(cases: Iterable[ThresholdCase]) -> BucketStats:
    materialized = tuple(cases)
    sample_count = len(materialized)
    hit_count = sum(1 for case in materialized if case.hit)
    hit_rate = hit_count / sample_count if sample_count else 0.0
    return BucketStats(
        sample_count=sample_count,
        hit_count=hit_count,
        hit_rate=hit_rate,
        wilson_95_lower=wilson_lower_bound(hit_count, sample_count),
    )


def parse_metar_t_group(raw_metar: str) -> int | None:
    match = METAR_T_RE.search(raw_metar)
    if match is None:
        return None
    magnitude = int(match.group("air_tenths"))
    return -magnitude if match.group("air_sign") == "1" else magnitude


def metar_temperatures(
    *,
    city: str,
    rows: Iterable[Mapping[str, str]],
    std_utc_offset_hours: float,
) -> tuple[tuple[MetarTemperature, ...], Counter[str]]:
    temperatures: list[MetarTemperature] = []
    drops: Counter[str] = Counter()
    for row in rows:
        raw_metar = row.get("metar", "")
        c_tenths = parse_metar_t_group(raw_metar)
        if c_tenths is None:
            drops["missing_metar_t_group_row"] += 1
            continue
        raw_valid = row.get("valid", "")
        try:
            valid_utc = dt.datetime.strptime(raw_valid, "%Y-%m-%d %H:%M").replace(
                tzinfo=dt.UTC
            )
        except ValueError:
            drops["archive_parse_error"] += 1
            continue
        climate_day = climate_day_for_instant(valid_utc, std_utc_offset_hours)
        temp_f = c_tenths_to_f(c_tenths)
        temperatures.append(
            MetarTemperature(
                city=city,
                valid_utc=valid_utc,
                climate_day=climate_day,
                temp_c_tenths=c_tenths,
                temp_f=temp_f,
                rounded_f=round_half_up_f(c_tenths),
                raw_metar=raw_metar,
            )
        )
    return tuple(temperatures), drops


def daily_metar_maxima(
    temperatures: Iterable[MetarTemperature], *, source: str
) -> dict[dt.date, DailyMetarMax]:
    grouped: dict[dt.date, list[MetarTemperature]] = defaultdict(list)
    for temperature in temperatures:
        grouped[temperature.climate_day].append(temperature)

    maxima: dict[dt.date, DailyMetarMax] = {}
    for climate_day, rows in grouped.items():
        rounded_max = max(row.rounded_f for row in rows)
        unrounded_max = max(row.temp_f for row in rows)
        maxima[climate_day] = DailyMetarMax(
            city=rows[0].city,
            climate_day=climate_day,
            rounded_max_f=rounded_max,
            unrounded_max_f=unrounded_max,
            observation_count=len(rows),
            source=source,
        )
    return maxima


def build_threshold_cases(
    *,
    city: str,
    labels: Mapping[dt.date, CliLabel],
    daily_maxima: Mapping[dt.date, DailyMetarMax],
) -> tuple[tuple[ThresholdCase, ...], Counter[str]]:
    cases: list[ThresholdCase] = []
    drops: Counter[str] = Counter()
    for climate_day, label in labels.items():
        if label.tmax_f is None:
            drops["cli_sentinel"] += 1
            continue
        metar_max = daily_maxima.get(climate_day)
        if metar_max is None:
            drops["missing_metar_t_group"] += 1
            continue
        for margin in (0, 1, 2, 3):
            threshold = metar_max.rounded_max_f - margin
            hit = label.tmax_f >= threshold
            cases.append(
                ThresholdCase(
                    city=city,
                    climate_day=climate_day,
                    threshold_f=threshold,
                    cli_tmax_f=label.tmax_f,
                    rounded_metar_max_f=metar_max.rounded_max_f,
                    unrounded_metar_max_f=metar_max.unrounded_max_f,
                    margin_f=margin,
                    bucket=bucket_for_margin(margin),
                    hit=hit,
                    rounding_sensitive=metar_max.unrounded_max_f < threshold,
                    cli_source=label.source,
                    metar_source=metar_max.source,
                )
            )
    for climate_day in daily_maxima:
        if climate_day not in labels:
            drops["missing_cli_final"] += 1
    return tuple(cases), drops


def cache_path_for_url(cache_dir: Path, url: str, suffix: str = ".txt") -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}{suffix}"


class HistoricalDataClient(Protocol):
    """The subset of ``httpx.Client`` these fetch helpers actually call.

    Narrower than ``httpx.Client`` so a cache-only stub (e.g. a client that
    always raises instead of performing network I/O) can honestly satisfy the
    interface without claiming to implement the full HTTP client surface.
    """

    def get(self, url: str, *, timeout: float) -> httpx.Response: ...


def fetch_text_cached(
    client: HistoricalDataClient, cache_dir: Path, url: str, delay_s: float
) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path_for_url(cache_dir, url)
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    response = client.get(url, timeout=60.0)
    response.raise_for_status()
    text = response.text
    path.write_text(text, encoding="utf-8")
    time.sleep(delay_s)
    return text


def fetch_bytes_cached(
    client: HistoricalDataClient,
    cache_dir: Path,
    url: str,
    delay_s: float,
    *,
    suffix: str,
) -> bytes:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path_for_url(cache_dir, url, suffix=suffix)
    if path.exists():
        return path.read_bytes()
    response = client.get(url, timeout=90.0)
    response.raise_for_status()
    data = response.content
    path.write_bytes(data)
    time.sleep(delay_s)
    return data


def afos_url(cli_location: str, start: dt.date, end: dt.date, *, limit: int = 10_000) -> str:
    params = urlencode(
        {
            "pil": f"CLI{cli_location}",
            "fmt": "zip",
            "order": "asc",
            "sdate": f"{start.isoformat()}T00:00Z",
            "edate": f"{(end + dt.timedelta(days=2)).isoformat()}T00:00Z",
            "limit": str(limit),
        }
    )
    return f"{IEM_BASE}/cgi-bin/afos/retrieve.py?{params}"


def asos_url(iem_asos_id: str, start: dt.date, end: dt.date) -> str:
    # Fetch a UTC pad on both sides; climate-day assignment is done by Breezy's
    # fixed-standard-time helper after parsing.
    padded_start = start - dt.timedelta(days=1)
    padded_end = end + dt.timedelta(days=2)
    params = urlencode(
        {
            "station": iem_asos_id,
            "data": "metar",
            "year1": str(padded_start.year),
            "month1": str(padded_start.month),
            "day1": str(padded_start.day),
            "year2": str(padded_end.year),
            "month2": str(padded_end.month),
            "day2": str(padded_end.day),
            "tz": "Etc/UTC",
            "format": "onlycomma",
            "latlon": "no",
            "direct": "no",
            "report_type": "1",
            "report_type_2": "2",
        }
    )
    # IEM expects repeated report_type keys. urlencode cannot express that from
    # the dict above without making the rest noisier, so patch the second key.
    return f"{IEM_BASE}/cgi-bin/request/asos.py?{params.replace('report_type_2=', 'report_type=')}"


def split_iem_afos_products(raw_text: str) -> tuple[str, ...]:
    products: list[str] = []
    for chunk in raw_text.split("\x03"):
        stripped = chunk.strip("\n\r\x01 ")
        if not stripped:
            continue
        lines = stripped.splitlines()
        if lines and re.fullmatch(r"\d+\s*", lines[0]):
            lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
        if not lines:
            continue
        products.append("\n000\n" + "\n".join(lines).rstrip() + "\n")
    return tuple(products)


def issue_utc_from_iem_filename(filename: str) -> dt.datetime | None:
    match = re.search(r"_(\d{12})\.txt$", filename)
    if match is None:
        return None
    return dt.datetime.strptime(match.group(1), "%Y%m%d%H%M").replace(tzinfo=dt.UTC)


def parse_issued_at(product_text: str) -> dt.datetime | None:
    match = ISSUED_RE.search(product_text)
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
    return local.astimezone(dt.UTC)


def parse_cli_labels(
    *,
    city: str,
    site: SettlementSite,
    raw_text: str,
    source_url: str,
    start: dt.date,
    end: dt.date,
) -> tuple[dict[dt.date, CliLabel], Counter[str], tuple[str, ...]]:
    labels: dict[dt.date, CliLabel] = {}
    drops: Counter[str] = Counter()
    parse_errors: list[str] = []
    for index, product_text in enumerate(split_iem_afos_products(raw_text), start=1):
        try:
            parsed = parse_cli_product(
                product_text,
                cli_location=site.cli_location,
                body_header_regex=site.body_header_regex,
            )
            issuance = classify_issuance(product_text)
        except (CliParseError, ClassificationError, ValueError) as exc:
            drops["archive_parse_error"] += 1
            parse_errors.append(f"{city} product {index}: {type(exc).__name__}: {exc}")
            continue

        if parsed.summary_date < start or parsed.summary_date > end:
            continue
        if issuance != "FINAL":
            continue
        issued_at = parse_issued_at(product_text)
        label = CliLabel(
            city=city,
            climate_day=parsed.summary_date,
            tmax_f=parsed.tmax.value_f,
            tmax_flag=None if parsed.tmax.sentinel == "NONE" else parsed.tmax.sentinel,
            is_final=True,
            correction_flag=parsed.is_correction_bbb,
            issued_at_utc=issued_at,
            source=f"{source_url}#product-{index}",
            raw_sha256=hashlib.sha256(product_text.encode("utf-8")).hexdigest(),
        )
        current = labels.get(parsed.summary_date)
        if current is None:
            labels[parsed.summary_date] = label
            continue
        if (label.issued_at_utc or dt.datetime.min.replace(tzinfo=dt.UTC)) >= (
            current.issued_at_utc or dt.datetime.min.replace(tzinfo=dt.UTC)
        ):
            labels[parsed.summary_date] = label
    return labels, drops, tuple(parse_errors)


def parse_cli_labels_zip(
    *,
    city: str,
    site: SettlementSite,
    zip_bytes: bytes,
    source_url: str,
    start: dt.date,
    end: dt.date,
) -> tuple[dict[dt.date, CliLabel], Counter[str], tuple[str, ...]]:
    labels: dict[dt.date, CliLabel] = {}
    drops: Counter[str] = Counter()
    parse_errors: list[str] = []
    with ZipFile(BytesIO(zip_bytes)) as archive:
        for filename in sorted(archive.namelist()):
            raw_text = archive.read(filename).decode("utf-8", errors="replace")
            products = split_iem_afos_products(raw_text)
            if not products:
                drops["archive_parse_error"] += 1
                parse_errors.append(f"{city} {filename}: no CLI product text found")
                continue
            for product_text in products:
                try:
                    parsed = parse_cli_product(
                        product_text,
                        cli_location=site.cli_location,
                        body_header_regex=site.body_header_regex,
                    )
                    issuance = classify_issuance(product_text)
                except (CliParseError, ClassificationError, ValueError) as exc:
                    drops["archive_parse_error"] += 1
                    parse_errors.append(f"{city} {filename}: {type(exc).__name__}: {exc}")
                    continue

                if parsed.summary_date < start or parsed.summary_date > end:
                    continue
                if issuance != "FINAL":
                    continue
                issued_at = issue_utc_from_iem_filename(filename) or parse_issued_at(product_text)
                label = CliLabel(
                    city=city,
                    climate_day=parsed.summary_date,
                    tmax_f=parsed.tmax.value_f,
                    tmax_flag=None if parsed.tmax.sentinel == "NONE" else parsed.tmax.sentinel,
                    is_final=True,
                    correction_flag=parsed.is_correction_bbb,
                    issued_at_utc=issued_at,
                    source=f"{source_url}#{filename}",
                    raw_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                )
                current = labels.get(parsed.summary_date)
                if current is None:
                    labels[parsed.summary_date] = label
                    continue
                if (label.issued_at_utc or dt.datetime.min.replace(tzinfo=dt.UTC)) >= (
                    current.issued_at_utc or dt.datetime.min.replace(tzinfo=dt.UTC)
                ):
                    labels[parsed.summary_date] = label
    return labels, drops, tuple(parse_errors)


def year_chunks(start: dt.date, end: dt.date) -> Iterable[tuple[dt.date, dt.date]]:
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(dt.date(chunk_start.year, 12, 31), end)
        yield chunk_start, chunk_end
        chunk_start = chunk_end + dt.timedelta(days=1)


def fetch_cli_labels_chunked(
    *,
    client: HistoricalDataClient,
    cache_dir: Path,
    delay_s: float,
    city: str,
    site: SettlementSite,
    start: dt.date,
    end: dt.date,
) -> tuple[dict[dt.date, CliLabel], Counter[str], tuple[str, ...]]:
    labels: dict[dt.date, CliLabel] = {}
    drops: Counter[str] = Counter()
    parse_errors: list[str] = []
    for chunk_start, chunk_end in year_chunks(start, end):
        cli_url = afos_url(site.cli_location, chunk_start, chunk_end, limit=3_000)
        cli_raw = fetch_bytes_cached(client, cache_dir, cli_url, delay_s, suffix=".zip")
        chunk_labels, chunk_drops, chunk_errors = parse_cli_labels_zip(
            city=city,
            site=site,
            zip_bytes=cli_raw,
            source_url=cli_url,
            start=chunk_start,
            end=chunk_end,
        )
        labels.update(chunk_labels)
        drops.update(chunk_drops)
        parse_errors.extend(chunk_errors)
    return labels, drops, tuple(parse_errors)


def parse_asos_rows(raw_csv: str) -> tuple[dict[str, str], ...]:
    return tuple(csv.DictReader(raw_csv.splitlines()))


def load_sites() -> tuple[SiteSpec, ...]:
    registry = default_registry()
    sites: list[SiteSpec] = []
    for venue, city in registry.pairs():
        if venue != VENUE:
            continue
        site = registry.settlement_site(venue, city)
        climate_window = registry.climate_day_window(venue, city)
        try:
            iem_asos_id = IEM_ASOS_IDS[site.icao]
        except KeyError as exc:
            raise RuntimeError(f"no explicit IEM ASOS mapping for {site.icao}") from exc
        sites.append(
            SiteSpec(
                city=city,
                site=site,
                std_utc_offset_hours=climate_window.std_utc_offset_hours,
                iem_asos_id=iem_asos_id,
            )
        )
    return tuple(sites)


def select_catalog_finals_for_site(
    *,
    city: str,
    expected_cli_location: str,
    records: Sequence[NwsClimateDay],
    raw_product_records: int = 0,
) -> tuple[dict[tuple[str, dt.date], NwsClimateDay], CatalogSiteSummary]:
    expected_records = tuple(
        record for record in records if record.station == expected_cli_location
    )
    wrong_station_records = len(records) - len(expected_records)
    selected = latest_by_climate_day(expected_records)
    finals = {
        (city, climate_day): record
        for (_station, climate_day), record in selected.items()
        if record.is_final and record.tmax_f is not None
    }
    summary = CatalogSiteSummary(
        city=city,
        expected_cli_location=expected_cli_location,
        climate_records=len(records),
        raw_product_records=raw_product_records,
        final_records=sum(1 for record in expected_records if record.is_final),
        preliminary_records=sum(1 for record in expected_records if not record.is_final),
        wrong_station_records=wrong_station_records,
        corrected_final_records=sum(
            1 for record in expected_records if record.is_final and record.correction_flag
        ),
        first_climate_day=min((record.climate_day for record in records), default=None),
        last_climate_day=max((record.climate_day for record in records), default=None),
    )
    return finals, summary


def _catalog_summary_detail(summary: CatalogSiteSummary) -> str:
    date_range = (
        "none"
        if summary.first_climate_day is None or summary.last_climate_day is None
        else f"{summary.first_climate_day}..{summary.last_climate_day}"
    )
    return (
        f"{summary.city}: expected_cli_location={summary.expected_cli_location} "
        f"climate_records={summary.climate_records} raw_products={summary.raw_product_records} "
        f"final={summary.final_records} preliminary={summary.preliminary_records} "
        f"wrong_station={summary.wrong_station_records} "
        f"corrected_finals={summary.corrected_final_records} date_range={date_range}"
    )


def read_catalog_finals(
    *, catalog_base: Path | None, sites: Sequence[SiteSpec]
) -> tuple[dict[tuple[str, dt.date], NwsClimateDay], tuple[str, ...]]:
    if catalog_base is None:
        return {}, ("BREEZY_CATALOG_BASE/--catalog-base was not supplied",)
    if not catalog_base.exists():
        return {}, (f"catalog base does not exist: {catalog_base}",)

    selected: dict[tuple[str, dt.date], NwsClimateDay] = {}
    details: list[str] = []
    for spec in sites:
        root = station_catalog_path(catalog_base, VENUE, spec.city)
        if not root.exists():
            details.append(f"missing station catalog root: {root}")
            continue
        catalog = ParquetDataCatalog(path=root)
        records = read_climate_days(catalog)
        raw_products = read_raw_products(catalog)
        site_finals, summary = select_catalog_finals_for_site(
            city=spec.city,
            expected_cli_location=spec.site.cli_location,
            records=records,
            raw_product_records=len(raw_products),
        )
        selected.update(site_finals)
        details.append(_catalog_summary_detail(summary))
    if not selected:
        details.append("no final Breezy catalog records found for the expected CLI locations")
    return selected, tuple(details)


def validate_archive_against_catalog(
    *,
    client: HistoricalDataClient,
    cache_dir: Path,
    delay_s: float,
    catalog_base: Path | None,
    sites: Sequence[SiteSpec],
) -> tuple[ValidationResult, dict[str, dict[dt.date, CliLabel]]]:
    catalog_finals, catalog_details = read_catalog_finals(catalog_base=catalog_base, sites=sites)
    if not catalog_finals:
        status = (
            "blocked: catalog_base_not_configured"
            if catalog_base is None
            else "blocked: validation_unavailable"
        )
        return (
            ValidationResult(
                status=status,
                checked_count=0,
                mismatch_count=0,
                details=catalog_details,
            ),
            {},
        )

    dates_by_city: dict[str, list[dt.date]] = defaultdict(list)
    for city, climate_day in catalog_finals:
        dates_by_city[city].append(climate_day)

    labels_by_city: dict[str, dict[dt.date, CliLabel]] = {}
    mismatches: list[str] = []
    checked = 0
    for spec in sites:
        dates = dates_by_city.get(spec.city)
        if not dates:
            continue
        url = afos_url(spec.site.cli_location, min(dates), max(dates), limit=500)
        zip_bytes = fetch_bytes_cached(client, cache_dir, url, delay_s, suffix=".zip")
        labels, _drops, parse_errors = parse_cli_labels_zip(
            city=spec.city,
            site=spec.site,
            zip_bytes=zip_bytes,
            source_url=url,
            start=min(dates),
            end=max(dates),
        )
        labels_by_city[spec.city] = labels
        for parse_error in parse_errors[:10]:
            mismatches.append(f"validation parse issue: {parse_error}")
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
        return (
            ValidationResult(
                status="blocked: validation_mismatch",
                checked_count=checked,
                mismatch_count=len(mismatches),
                details=(*catalog_details, *mismatches),
            ),
            labels_by_city,
        )
    return (
        ValidationResult(
            status="passed",
            checked_count=checked,
            mismatch_count=0,
            details=(
                f"checked {checked} overlapping final Breezy catalog records",
                *catalog_details,
            ),
        ),
        labels_by_city,
    )


def fetch_historical_cases(
    *,
    client: HistoricalDataClient,
    cache_dir: Path,
    delay_s: float,
    sites: Sequence[SiteSpec],
    start: dt.date,
    end: dt.date,
) -> tuple[tuple[ThresholdCase, ...], Counter[str], tuple[str, ...]]:
    all_cases: list[ThresholdCase] = []
    drops: Counter[str] = Counter()
    parse_errors: list[str] = []
    for spec in sites:
        labels, cli_drops, cli_errors = fetch_cli_labels_chunked(
            client=client,
            cache_dir=cache_dir,
            delay_s=delay_s,
            city=spec.city,
            site=spec.site,
            start=start,
            end=end,
        )
        drops.update({f"{spec.city}:{key}": value for key, value in cli_drops.items()})
        parse_errors.extend(cli_errors)

        site_asos_url = asos_url(spec.iem_asos_id, start, end)
        asos_raw = fetch_text_cached(client, cache_dir, site_asos_url, delay_s)
        rows = parse_asos_rows(asos_raw)
        temperatures, metar_drops = metar_temperatures(
            city=spec.city,
            rows=rows,
            std_utc_offset_hours=spec.std_utc_offset_hours,
        )
        filtered_temperatures = tuple(
            row for row in temperatures if start <= row.climate_day <= end
        )
        drops.update({f"{spec.city}:{key}": value for key, value in metar_drops.items()})
        maxima = daily_metar_maxima(filtered_temperatures, source=site_asos_url)
        cases, case_drops = build_threshold_cases(
            city=spec.city,
            labels=labels,
            daily_maxima=maxima,
        )
        drops.update({f"{spec.city}:{key}": value for key, value in case_drops.items()})
        all_cases.extend(cases)
    return tuple(all_cases), drops, tuple(parse_errors)


def disagreement_rows(cases: Iterable[ThresholdCase]) -> tuple[ThresholdCase, ...]:
    return tuple(case for case in cases if not case.hit)


def classify_disagreement(case: ThresholdCase) -> str:
    if case.rounding_sensitive:
        return "C->F rounding"
    return "unexplained"


def format_stats(stats: BucketStats) -> str:
    return (
        f"{stats.sample_count} | {stats.hit_count} | {stats.sample_count - stats.hit_count} | "
        f"{stats.hit_rate:.6f} | {stats.wilson_95_lower:.6f}"
    )


def insufficient_sample_message(
    stats: BucketStats,
    *,
    min_sample_count: int,
    cases_per_climate_day: int,
    generated_at: dt.datetime,
) -> str:
    if stats.sample_count >= min_sample_count:
        return "sample threshold satisfied"
    needed_cases = min_sample_count - stats.sample_count
    needed_days = math.ceil(needed_cases / cases_per_climate_day)
    unblock_date = generated_at.date() + dt.timedelta(days=needed_days)
    return (
        "NOT YET ANSWERABLE: insufficient sample; "
        f"{stats.sample_count}/{min_sample_count} cases evaluated, "
        f"{needed_cases} more cases needed = {needed_days} more climate days at "
        f"{cases_per_climate_day} cases/day; earliest live-only unblock date {unblock_date}"
    )


def verdict(stats: BucketStats, *, generated_at: dt.datetime) -> str:
    if stats.sample_count < MIN_SAMPLE_COUNT:
        return insufficient_sample_message(
            stats,
            min_sample_count=MIN_SAMPLE_COUNT,
            cases_per_climate_day=4,
            generated_at=generated_at,
        )
    if stats.wilson_95_lower > PRIMARY_BREAK_EVEN:
        return "PASSED"
    return "FAILED"


def overall_gate(cases: Sequence[ThresholdCase], *, generated_at: dt.datetime) -> str:
    by_city: dict[str, list[ThresholdCase]] = defaultdict(list)
    for case in cases:
        by_city[case.city].append(case)
    if not by_city:
        return "NOT YET ANSWERABLE"
    verdicts = {
        city: verdict(summarize_cases(city_cases), generated_at=generated_at)
        for city, city_cases in by_city.items()
    }
    if any(value.startswith("NOT YET ANSWERABLE") for value in verdicts.values()):
        return "NOT YET ANSWERABLE"
    if all(value == "PASSED" for value in verdicts.values()):
        return "PASSED"
    return "FAILED"


def markdown_report(
    *,
    validation: ValidationResult,
    cases: Sequence[ThresholdCase],
    drops: Counter[str],
    parse_errors: Sequence[str],
    blocked: bool,
    catalog_base: Path | None,
    cache_dir: Path,
    command: str,
) -> str:
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    gate_status = (
        "NOT YET ANSWERABLE" if blocked else overall_gate(cases, generated_at=generated_at)
    )
    lines = [
        "# Settlement-Alignment Study Evidence",
        "",
        f"Generated at: {generated_at.isoformat()}",
        f"Settlement-alignment gate: **{gate_status}**",
        f"Pre-registration: `{PREREGISTRATION_PATH}`",
        f"Command: `{command}`",
        f"Catalog base: `{catalog_base}`",
        f"Cache dir: `{cache_dir}`",
        "",
        "## Registered Rules",
        "",
        f"- Historical window: {START_DATE.isoformat()} through {END_DATE.isoformat()}",
        f"- Primary GO threshold: Wilson 95% lower bound > {PRIMARY_BREAK_EVEN:.4f}",
        f"- Secondary 97c reference break-even: {SECONDARY_BREAK_EVEN:.4f}",
        f"- Minimum per-city sample count: {MIN_SAMPLE_COUNT}",
        "- C->F rounding: half-up whole Fahrenheit from raw METAR T-group Celsius tenths",
        "- Margin buckets: 0-1F, 1-2F, 2-3F, 3F+",
        (
            "- Climate-day boundary: Breezy fixed local-standard midnight-to-midnight "
            "window from `sites.toml` (`std_utc_offset_hours`), not UTC and not "
            "DST-adjusted civil time."
        ),
        "- Settlement oracle: official NWS CLI final product for the venue-mapped station.",
        (
            "- Revised CLI handling: final corrections are separate records; selection "
            "uses the latest final for a station/day and reports corrected-final inventory."
        ),
        "",
        "## Archive Validation Bridge",
        "",
        f"Status: **{validation.status}**",
        f"Checked overlapping final records: {validation.checked_count}",
        f"Mismatches: {validation.mismatch_count}",
        "",
    ]
    for detail in validation.details:
        lines.append(f"- {detail}")
    lines.append("")

    if blocked:
        lines.extend(
            [
                "## Study Status",
                "",
                (
                    "BLOCKED. Historical hit-rate analysis was not run because the "
                    "archive-validation bridge did not pass."
                ),
                "",
                "## Per-City Statistics",
                "",
                "Not computed because the validation bridge did not pass.",
                "",
                "## Per-Margin Bucket Statistics",
                "",
                "Not computed.",
                "",
                "## GO / NO-GO Verdicts",
                "",
                "No city receives a GO verdict because the validation bridge did not pass.",
                "",
            ]
        )
    else:
        by_city: dict[str, list[ThresholdCase]] = defaultdict(list)
        by_bucket: dict[str, list[ThresholdCase]] = defaultdict(list)
        for case in cases:
            by_city[case.city].append(case)
            by_bucket[case.bucket].append(case)

        lines.extend(
            [
                "## Per-City Statistics",
                "",
                (
                    "| City | Cases | Matches | Mismatches | Agreement rate | "
                    "Wilson 95% lower | Verdict |"
                ),
                "|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for city in sorted(by_city):
            stats = summarize_cases(by_city[city])
            lines.append(
                f"| {city} | {format_stats(stats)} | "
                f"{verdict(stats, generated_at=generated_at)} |"
            )
        lines.extend(
            [
                "",
                "## Per-Margin Bucket Statistics",
                "",
                "| Bucket | Cases | Matches | Mismatches | Agreement rate | Wilson 95% lower |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for bucket in ("0-1F", "1-2F", "2-3F", "3F+"):
            stats = summarize_cases(by_bucket.get(bucket, ()))
            lines.append(f"| {bucket} | {format_stats(stats)} |")
        rounding_sensitive = sum(1 for case in cases if case.rounding_sensitive)
        lines.extend(["", f"Rounding-sensitive evaluated cases: {rounding_sensitive}", ""])

    lines.extend(["## Drop Counts", ""])
    if drops:
        for reason, count in sorted(drops.items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")
    lines.append("")

    lines.extend(
        [
            "## Backfill Assessment",
            "",
            (
                "Historical CLI/METAR archive data can answer the alignment question now; "
                "waiting for live collection is not required for this study."
            ),
            "",
            "Command used:",
            "",
            "```console",
            f"$ {command}",
            "```",
            "",
            (
                "Fetch plan and observed cost: five venue-mapped stations, one IEM ASOS "
                "METAR CSV per station, and one IEM AFOS CLI ZIP per station-year for "
                "2021-01-01 through 2025-12-31. The completed run cached 40 files, totaling "
                "about 298 MiB. That cache was written to "
                "`/tmp/breezy-settlement-alignment-cache` and has since been relocated, "
                "SHA-256 verified, to "
                "`~/.local/share/breezy/archive/settlement-alignment-cache`, which is "
                "the path these scripts now default to."
            ),
            "",
            (
                "This is read-only archive backfill for the study. It does not write "
                "historical rows into Breezy's Parquet catalog or SQLite state DB."
            ),
            "",
        ]
    )

    lines.extend(["## Disagreement Case Files", ""])
    misses = disagreement_rows(cases)
    if misses:
        lines.append(
            "| City | Climate day | X | CLI tmax | METAR max | Bucket | Cause | "
            "CLI source | METAR source |"
        )
        lines.append("|---|---|---:|---:|---:|---|---|---|---|")
        for case in misses:
            lines.append(
                f"| {case.city} | {case.climate_day} | {case.threshold_f} | "
                f"{case.cli_tmax_f} | {case.rounded_metar_max_f} | {case.bucket} | "
                f"{classify_disagreement(case)} | {case.cli_source} | {case.metar_source} |"
            )
    else:
        lines.append("No disagreement cases were computed." if blocked else "No misses.")
    lines.append("")

    lines.extend(["## Parse Issues", ""])
    if parse_errors:
        for error in parse_errors[:200]:
            lines.append(f"- {error}")
        if len(parse_errors) > 200:
            lines.append(f"- ... {len(parse_errors) - 200} additional parse issues omitted")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_evidence(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {
        "url": "local offline study",
        "retrieved_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "sha256": digest,
        "captured_by": "breezy settlement-alignment study script",
        "note": "Digest sidecar for reproducible settlement-alignment evidence report.",
    }
    path.with_suffix(path.suffix + ".meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-base", type=Path, default=os.environ.get("BREEZY_CATALOG_BASE"))
    parser.add_argument(
        "--cache-dir",
        type=resolve_settlement_alignment_cache_dir,
        default=DEFAULT_CACHE_DIR,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE_PATH)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--start-date", type=dt.date.fromisoformat, default=START_DATE)
    parser.add_argument("--end-date", type=dt.date.fromisoformat, default=END_DATE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.start_date != START_DATE or args.end_date != END_DATE:
        raise SystemExit("start/end date overrides would violate the pre-registration")

    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    try:
        pyiem_version = importlib.metadata.version("pyiem")
    except importlib.metadata.PackageNotFoundError:
        pyiem_version = "not installed"

    sites = load_sites()
    command = " ".join(["python", *sys.argv])
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        validation, _overlap_labels = validate_archive_against_catalog(
            client=client,
            cache_dir=cache_dir,
            delay_s=args.delay_seconds,
            catalog_base=args.catalog_base,
            sites=sites,
        )
        if validation.status != "passed":
            report = markdown_report(
                validation=validation,
                cases=(),
                drops=Counter({"validation_unavailable": 1}),
                parse_errors=(f"pyiem version available to backfill extra: {pyiem_version}",),
                blocked=True,
                catalog_base=args.catalog_base,
                cache_dir=cache_dir,
                command=command,
            )
            write_evidence(args.output, report)
            return 2

        cases, drops, parse_errors = fetch_historical_cases(
            client=client,
            cache_dir=cache_dir,
            delay_s=args.delay_seconds,
            sites=sites,
            start=START_DATE,
            end=END_DATE,
        )
        report = markdown_report(
            validation=validation,
            cases=cases,
            drops=drops,
            parse_errors=(
                f"pyiem version available to backfill extra: {pyiem_version}",
                *parse_errors,
            ),
            blocked=False,
            catalog_base=args.catalog_base,
            cache_dir=cache_dir,
            command=command,
        )
        write_evidence(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
