#!/usr/bin/env python
"""Card E run 1: Kalshi expiration_value versus IEM CLI, one read-only look.

Ordinary analysis tooling (argparse only). Not an evaluator, harness, runner,
or unit. Nautilus is not imported. No order path, no auth, no operator caps.

The mismatch is ``int(expiration_value) - CLI_final`` at whole degrees.
Null or non-numeric expiration values, non-finalized markets, voids,
cancellations, and CLI amendments are excluded. They are not mismatches.
The bucket check is reported and is not a gate. The chronological half-split
is a stability table and is not a gate.

Kalshi reads go through ``KalshiHttp`` in ``scripts/analysis/k1_kalshi_prior.py``
(public GETs only). IEM reads use ``afos_cli_text_url`` and ``IemCliTransport``
from ``scripts/archive/iem_cli_fetch.py`` and never that module's ``fetch``
(the single writer of the production CLI cache). Raw text is written only
under ``--scratch-dir``. The only evidence files are
``card_e_cli_vs_twc.md`` and ``card_e_cli_vs_twc.parquet`` in ``--out-dir``.
An existing pair is a finished look and is not overwritten unless
``--force-new-look`` carries a reason, which is recorded (L-34).
``--prereg`` and ``--prereg-sha`` are required. Thresholds, sides, and the
climate window are frozen. A dry-run cannot write the evidence directory.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scipy.stats import beta, binom

from breezy.ingest.http import (
    RateLimitedError,
    ServerError,
    TransportError,
    TransportTimeoutError,
)
from breezy.normalize.classify import (
    ClassificationError,
    classify_issuance,
    has_correction_evidence,
)
from breezy.normalize.cli_parse import (
    CliContentError,
    CliParseError,
    ParsedCliProduct,
    parse_cli_product,
)
from breezy.normalize.sanity import CliSanityError

_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _ANALYSIS_DIR.parents[1]
if str(_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MARKDOWN_NAME: Final[str] = "card_e_cli_vs_twc.md"
PARQUET_NAME: Final[str] = "card_e_cli_vs_twc.parquet"
DEFAULT_OUT_DIR: Final[str] = "docs/evidence/STRAT_DESIGN_2026-10-31"
PLANNING_N: Final[int] = 4080
REFERENCE_FAMILY: Final[int] = 48
REFERENCE_NS: Final[tuple[int, ...]] = (90, 71, 65, 63)
UCB_LEVEL: Final[float] = 0.95
KALSHI_MIN_INTERVAL_S: Final[float] = 0.25  # at most 4 requests/second
IEM_MIN_INTERVAL_NS: Final[int] = 1_000_000_000  # at most 1 request/second
KALSHI_USER_AGENT: Final[str] = "breezy-research/1.0 (Card E CLI vs TWC; public GET; no auth)"
IEM_USER_AGENT: Final[str] = "breezy-research/1.0 (Card E CLI vs TWC; read-only AFOS)"
# Frozen in prereg_r2_1.md §3 and §5. Not flags.
P0: Final[float] = 0.01
ALPHA_T1: Final[float] = 0.025
ALPHA_T2: Final[float] = 0.025
SAME_SIGN_SHARE: Final[float] = 0.80
KILL_UCB: Final[float] = 0.02
SIDES: Final[tuple[str, ...]] = ("high", "low")
FROZEN_START: Final[dt.date] = dt.date(2026, 7, 5)
FROZEN_END: Final[dt.date] = dt.date(2026, 10, 30)
FROZEN_PREREG: Final[str] = "docs/plans/backlog/STRAT_DESIGN_2026-10-31/prereg_r2_1.md"
FROZEN_PREREG_SHA: Final[str] = "4f490f4b255ab34b214251f19500f66ed487bb68a4e780a7e8c3108c09d34070"
# Kalshi historical client serves days before this date (k1_kalshi_prior).
HISTORICAL_CUTOFF: Final[dt.date] = dt.date(2026, 7, 4)
IEM_MAX_ATTEMPTS: Final[int] = 5
IEM_BACKOFF_S: Final[float] = 1.0
MIN_PRODUCTS_PER_SIDE: Final[int] = 1
PAIRED_CAP_FRACTION: Final[float] = 0.50
# Prereg §3: 18 stations share n ≤ 91. The six named cities differ.
_CAP_91_CITIES: Final[frozenset[str]] = frozenset(
    {
        "ATL",
        "AUS",
        "BOS",
        "MDW",
        "DFW",
        "DEN",
        "HOU",
        "LAS",
        "LAX",
        "MIA",
        "MSY",
        "NYC",
        "OKC",
        "PHL",
        "SAT",
        "SFO",
        "SEA",
        "DCA",
    }
)
_NAMED_CAPS: Final[Mapping[str, int]] = {
    "PHX": 89,
    "MSP": 90,
    "SAN": 71,
    "EWR": 65,
    "TTN": 65,
    "SDF": 63,
}
# Retryable transport failures only. Programming errors propagate (B7).
_PULL_ERRORS: Final[tuple[type[BaseException], ...]] = (OSError, TransportError)
_IEM_RETRY: Final[tuple[type[BaseException], ...]] = (
    OSError,
    RateLimitedError,
    ServerError,
    TransportTimeoutError,
)

_MONTHS: Final[Mapping[str, int]] = {
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
_MONTH_NAMES: Final[Mapping[str, int]] = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}
# Event ticker only. close_time is not the climate date.
_EVENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<series>[A-Z0-9]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})$"
)
# Same headline shape as ``src/breezy/normalize/cli_parse.py`` ``_HEADLINE_RE``.
_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^\.\.\.THE\s+.+?\s+CLIMATE\s+SUMMARY\s+FOR\s+[A-Z]+\s+\d{1,2}\s+\d{4}\.\.\.\s*$"
)
_HEADLINE_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"CLIMATE\s+SUMMARY\s+FOR\s+(?P<month>[A-Z]+)\s+(?P<day>\d{1,2})\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
_PIL_RE: Final[re.Pattern[str]] = re.compile(r"^CLI(?P<loc>[A-Z][A-Z0-9]{2})\s*$", re.MULTILINE)
_DAY_EXCLUSION_ORDER: Final[tuple[str, ...]] = (
    "void",
    "cancelled",
    "not_finalized",
    "null_expiration_value",
    "non_numeric_expiration_value",
    "non_integer_expiration_value",
)
_MISSING_SENTINELS: Final[frozenset[str]] = frozenset({"M", "MM", "T", "MS", "MB"})

Outcome = Literal["match", "mismatch", "excluded"]
BucketWord = Literal["agree", "disagree"]
VerdictWord = Literal["PASS", "KILL", "INCONCLUSIVE"]


@dataclass(frozen=True, slots=True)
class Station:
    """One row of the stations file. ``city`` is the join key, not the ICAO.

    ``cli_id`` is the AFOS location (``cli_afos_id`` when the file has one).
    """

    city: str
    icao: str
    timezone: str
    high_series: str | None
    low_series: str | None
    cli_id: str


@dataclass(frozen=True, slots=True)
class KalshiDay:
    """One station-side-day: an integer expiration value, or why it is out."""

    expiration_f: int | None
    exclusion: str | None

    def __post_init__(self) -> None:
        if (self.expiration_f is None) == (self.exclusion is None):
            raise ValueError("Kalshi day needs exactly one of expiration_f or exclusion")


@dataclass(frozen=True, slots=True)
class KalshiSettled:
    """``days`` is the join key. ``exclusion_counts`` counts market rows, not days."""

    days: Mapping[tuple[str, str, dt.date], KalshiDay]
    exclusion_counts: Mapping[tuple[str, str], Mapping[str, int]]


@dataclass(frozen=True, slots=True)
class CliLabelParse:
    """One product's tmax or tmin, or the reason that product cannot be used."""

    value_f: int | None
    exclusion: str | None
    climate_date: dt.date | None

    def __post_init__(self) -> None:
        if (self.value_f is None) == (self.exclusion is None):
            raise ValueError("CLI label needs exactly one of value_f or exclusion")


@dataclass(frozen=True, slots=True)
class CliTextIndex:
    """Latest product per climate date. Later text wins; an amendment stays out.

    ``overwrites`` counts dates replaced by a later product. A later non-final
    product does not replace a final integer (S10).
    """

    days: Mapping[dt.date, CliLabelParse]
    undated_exclusions: Mapping[str, int]
    overwrites: int = 0


@dataclass(frozen=True, slots=True)
class Mismatch:
    """``delta`` is Kalshi minus CLI. Zero is a match."""

    kind: Literal["match", "mismatch"]
    delta: int


@dataclass(frozen=True, slots=True)
class T1Result:
    """Exact one-sided binomial. ``threshold`` is the smallest rejecting k."""

    k: int
    n: int
    p0: float
    alpha: float
    threshold: int | None
    p_value: float
    reject: bool


@dataclass(frozen=True, slots=True)
class DayRow:
    """One parquet row. ``outcome`` is excluded when either label is unusable."""

    station: str
    side: str
    climate_date: dt.date
    kalshi_f: int | None
    cli_f: int | None
    delta: int | None
    outcome: Outcome
    exclusion: str | None
    half: int
    kalshi_reason: str | None = None
    cli_reason: str | None = None


@dataclass(frozen=True, slots=True)
class BucketTally:
    """Reported only. Never read by the verdict."""

    agree: int
    disagree: int
    skipped: int


@dataclass(frozen=True, slots=True)
class SideStat:
    side_id: str
    station: str
    side: str
    n: int
    k: int
    p_value: float
    flagged: bool
    positive: int
    negative: int
    sign_ok: bool
    upper: float | None
    outcome: VerdictWord
    day_exclusions: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CardResult:
    t1: T1Result
    t2_flags: tuple[str, ...]
    sign_ok: bool
    kill: bool
    upper: float | None
    name: VerdictWord
    reason: str
    planning_threshold: int | None
    reference_thresholds: Mapping[int, int | None]


@dataclass(frozen=True, slots=True)
class RequestCounts:
    mode: str
    kalshi_get_json: int
    iem_fetches: int
    kalshi_errors: int
    iem_errors: int


class _MarketClient(Protocol):
    calls: int

    def list_series_markets(self, series: str) -> list[Mapping[str, Any]]: ...


def file_sha256(path: Path) -> str:
    """SHA-256 of the stations file bytes, not of a re-serialization."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_stations(path: Path) -> tuple[Station, ...]:
    """JSON list of station rows.

    Accepts ``high_series`` / ``low_series`` / ``timezone`` and the frozen
    Card E names ``kalshi_high_series`` / ``kalshi_low_series`` / ``tz``.
    """
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("stations file must be a JSON list")
    if not payload:
        raise ValueError("stations file must be a non-empty JSON list")
    stations = tuple(_one_station(item) for item in payload)
    cities = [station.city for station in stations]
    if len(cities) != len(set(cities)):
        raise ValueError("duplicate city in stations file")
    return stations


def _one_station(item: object) -> Station:
    if not isinstance(item, dict):
        raise TypeError("station row must be a JSON object")
    timezone = _required_alias(item, ("timezone", "tz"))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone {timezone}") from exc
    city = _required_text(item, "city")
    return Station(
        city=city,
        icao=_required_text(item, "icao"),
        timezone=timezone,
        high_series=_aliased(item, ("high_series", "kalshi_high_series"), required=False),
        low_series=_aliased(item, ("low_series", "kalshi_low_series"), required=False),
        cli_id=_aliased(item, ("cli_afos_id",), required=False) or city,
    )


def _required_alias(row: Mapping[str, Any], names: tuple[str, ...]) -> str:
    value = _aliased(row, names, required=True)
    if value is None:
        raise ValueError(f"station needs one of {', '.join(names)}")
    return value


def _aliased(row: Mapping[str, Any], names: tuple[str, ...], *, required: bool) -> str | None:
    """First present alias. Two present aliases that disagree are an error."""
    found: list[str] = []
    for name in names:
        if name not in row or row[name] is None:
            continue
        value = row[name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"station field {name} must be a non-empty string")
        found.append(value.strip())
    if len(set(found)) > 1:
        raise ValueError(f"station fields {', '.join(names)} disagree")
    if found:
        return found[0]
    if required:
        raise ValueError(f"station needs one of {', '.join(names)}")
    return None


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"station field {key} must be a non-empty string")
    return value.strip()


def _series_for(station: Station, side: str) -> str | None:
    return station.high_series if side == "high" else station.low_series


def _event_climate_date(raw: object) -> dt.date | None:
    """Climate date from ``event_ticker`` only. ``close_time`` is not read."""
    if not isinstance(raw, str):
        return None
    match = _EVENT_RE.match(raw.strip().upper())
    if match is None:
        return None
    month = _MONTHS.get(match.group("mon"))
    if month is None:
        return None
    try:
        return dt.date(2000 + int(match.group("yy")), month, int(match.group("dd")))
    except ValueError:
        return None


def _whole_degrees(raw: object) -> int | str:
    """Whole-degree expiration value, or an exclusion reason. No truncation."""
    if raw is None:
        return "null_expiration_value"
    if isinstance(raw, str) and raw.strip().lower() in {"", "null", "none", "na"}:
        return "null_expiration_value"
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return "non_numeric_expiration_value"
    from decimal import Decimal, InvalidOperation

    try:
        number = Decimal(str(raw).strip()) if not isinstance(raw, int) else Decimal(raw)
    except InvalidOperation:
        return "non_numeric_expiration_value"
    if not number.is_finite() or number != number.to_integral_value():
        return "non_integer_expiration_value"
    return int(number)


def _row_exclusion(row: Mapping[str, Any]) -> str | None:
    """Void, cancelled, or not finalized. A usable row returns None."""
    status = str(row.get("status") or "").strip().lower()
    result = str(row.get("result") or "").strip().lower()
    if status in {"cancelled", "canceled"} or result in {"cancelled", "canceled"}:
        return "cancelled"
    if result in {"void", "voided"}:
        return "void"
    if status != "finalized":
        return "not_finalized"
    return None


def _row_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    station = row.get("station")
    side = row.get("side")
    if not isinstance(station, str) or not isinstance(side, str):
        raise TypeError("Kalshi row is missing station or side")
    return station, side


def parse_kalshi_settled(rows: Sequence[Mapping[str, Any]]) -> KalshiSettled:
    """Per (station, side, climate_date): an integer, or an exclusion reason.

    Market-row exclusions are counted even when another market on that day
    still supplies the integer. Disagreeing integers exclude the day.
    """
    grouped: dict[tuple[str, str, dt.date], list[Mapping[str, Any]]] = defaultdict(list)
    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        station, side = _row_identity(row)
        climate_date = _event_climate_date(row.get("event_ticker"))
        if climate_date is None:
            counts[(station, side)]["unparsed_event_ticker"] += 1
            continue
        grouped[(station, side, climate_date)].append(row)
    days = {key: _collapse_group(group, counts) for key, group in grouped.items()}
    frozen = {key: dict(counter) for key, counter in counts.items() if counter}
    return KalshiSettled(days=days, exclusion_counts=frozen)


def _collapse_group(
    group: Sequence[Mapping[str, Any]],
    counts: dict[tuple[str, str], Counter[str]],
) -> KalshiDay:
    station, side = _row_identity(group[0])
    values: set[int] = set()
    local: Counter[str] = Counter()
    for row in group:
        reason = _row_exclusion(row)
        parsed: int | str
        if reason is not None:
            parsed = reason
        else:
            parsed = _whole_degrees(row.get("expiration_value"))
        if isinstance(parsed, str):
            local[parsed] += 1
            continue
        values.add(parsed)
    counts[(station, side)].update(local)
    if len(values) == 1:
        return KalshiDay(expiration_f=next(iter(values)), exclusion=None)
    if len(values) > 1:
        counts[(station, side)]["conflicting_expiration_value"] += 1
        return KalshiDay(expiration_f=None, exclusion="conflicting_expiration_value")
    return KalshiDay(expiration_f=None, exclusion=_day_exclusion(local))


def _day_exclusion(counts: Counter[str]) -> str:
    for name in _DAY_EXCLUSION_ORDER:
        if counts[name]:
            return name
    return "no_usable_expiration"


def _headline_date(text: str) -> dt.date | None:
    match = _HEADLINE_DATE_RE.search(text)
    if match is None:
        return None
    month = _MONTH_NAMES.get(match.group("month").upper())
    if month is None:
        return None
    try:
        return dt.date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def _pil_location(text: str) -> str | None:
    match = _PIL_RE.search(text)
    return None if match is None else match.group("loc")


def _issuance(text: str) -> str:
    try:
        kind = classify_issuance(text)
    except ClassificationError:
        return "unparsed"
    return "final" if kind == "FINAL" else "not_final"


def _parse_product(text: str) -> ParsedCliProduct | str:
    location = _pil_location(text)
    if location is None:
        return "unparsed"
    try:
        return parse_cli_product(text, cli_location=location, body_header_regex=_HEADER_RE)
    except CliContentError:
        # tmax is fail-closed in ``parse_cli_product``: a bad token raises
        # instead of returning the UNREADABLE sentinel tmin uses.
        return "unreadable_temperature"
    except (CliParseError, CliSanityError):
        return "unparsed"


def _side_reading(parsed: ParsedCliProduct, side: str) -> CliLabelParse:
    reading = parsed.tmax if side == "high" else parsed.tmin
    if reading.value_f is None:
        if reading.sentinel in _MISSING_SENTINELS:
            reason = "missing_temperature"
        else:
            reason = "unreadable_temperature"
        return CliLabelParse(None, reason, parsed.summary_date)
    return CliLabelParse(reading.value_f, None, parsed.summary_date)


def parse_cli_label(text: str, side: str) -> CliLabelParse:
    """Integer tmax (``high``) or tmin (``low``), or an exclusion reason.

    Modeled on ``parse_cli_product`` in ``src/breezy/normalize/cli_parse.py``,
    which ``src/breezy/ingest/records.py`` uses to map a product onto
    ``NwsClimateDay`` (both extremes). ``CliLabel`` in
    ``scripts/analysis/settlement_alignment_study.py`` stores ``tmax_f`` only,
    so LOW cannot be read from it. Amendment evidence is
    ``has_correction_evidence`` (``src/breezy/normalize/classify.py``) or the
    product's WMO BBB correction flag. A record-``R`` token keeps its integer.
    """
    normalized = _normalize_side(side)
    if not text or not text.strip():
        return CliLabelParse(None, "empty_product", None)
    climate_date = _headline_date(text)
    if has_correction_evidence(text):
        return CliLabelParse(None, "amendment", climate_date)
    if _issuance(text) == "not_final":
        return CliLabelParse(None, "not_final", climate_date)
    if _issuance(text) == "unparsed":
        return CliLabelParse(None, "unparsed", climate_date)
    parsed = _parse_product(text)
    if isinstance(parsed, str):
        return CliLabelParse(None, parsed, climate_date)
    if parsed.is_correction_bbb:
        return CliLabelParse(None, "amendment", parsed.summary_date)
    return _side_reading(parsed, normalized)


def _normalize_side(side: str) -> Literal["high", "low"]:
    lowered = side.strip().lower()
    if lowered not in {"high", "low"}:
        raise ValueError("side must be high or low")
    return cast(Literal["high", "low"], lowered)


def split_iem_products(raw_text: str) -> tuple[str, ...]:
    """Split an IEM AFOS text blob on ETX.

    Same framing as ``split_iem_afos_products`` in
    ``scripts/analysis/settlement_alignment_study.py`` (the leading count line
    dropped, a ``000`` transmission line restored). Inlined so this script does
    not import that module's Nautilus catalog reader.
    """
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


def _keeps_final(previous: CliLabelParse, incoming: CliLabelParse) -> bool:
    """A later non-final product must not replace the last final integer."""
    return previous.value_f is not None and incoming.exclusion == "not_final"


def cli_days_from_text(text: str, side: str) -> CliTextIndex:
    """Index one station's raw text. The last final integer is kept (S10)."""
    chosen: dict[dt.date, CliLabelParse] = {}
    undated: Counter[str] = Counter()
    overwrites = 0
    products = split_iem_products(text)
    if not products and text.strip():
        products = (text,)
    for product in products:
        label = parse_cli_label(product, side)
        if label.climate_date is None:
            undated[label.exclusion or "unparsed"] += 1
            continue
        previous = chosen.get(label.climate_date)
        if previous is not None and _keeps_final(previous, label):
            continue
        if previous is not None:
            overwrites += 1
        chosen[label.climate_date] = label
    return CliTextIndex(days=chosen, undated_exclusions=dict(undated), overwrites=overwrites)


def classify_mismatch(kalshi_int: int, cli_int: int) -> Mismatch:
    """Match when the degree-level difference is zero. ``delta`` keeps its sign."""
    delta = kalshi_int - cli_int
    kind: Literal["match", "mismatch"] = "match" if delta == 0 else "mismatch"
    return Mismatch(kind=kind, delta=delta)


def bucket_check(
    result: str,
    cli_int: int,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
) -> BucketWord:
    """Does ``result`` match the bucket the CLI integer falls in?

    ``less``: CLI < cap. ``greater``: CLI > floor. ``between``: floor <= CLI <= cap.
    Those are the Kalshi daily-temperature rules (``less than 99`` uses cap 99;
    ``greater than 106`` uses floor 106; ``between 99-100`` is inclusive).
    """
    implied = _implied_yes(cli_int, floor_strike, cap_strike, strike_type)
    if implied is None:
        return "disagree"
    observed = result.strip().lower()
    expected = "yes" if implied else "no"
    return "agree" if observed == expected else "disagree"


def _implied_yes(
    cli_int: int,
    floor_strike: float | None,
    cap_strike: float | None,
    strike_type: str,
) -> bool | None:
    kind = strike_type.strip().lower()
    if kind == "less" and cap_strike is not None:
        return cli_int < float(cap_strike)
    if kind == "greater" and floor_strike is not None:
        return cli_int > float(floor_strike)
    if kind == "between" and floor_strike is not None and cap_strike is not None:
        return float(floor_strike) <= cli_int <= float(cap_strike)
    return None


def _as_probability(raw: object) -> float:
    number = float(cast(Any, raw))
    if isinstance(number, float) and math.isfinite(number):
        return number
    raise ValueError("probability function returned a non-finite value")


def binomial_p_ge(k: int, n: int, p0: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p0). Exact test, float evaluation."""
    if n < 0 or k < 0:
        raise ValueError("k and n must be non-negative")
    if n == 0 or k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return _as_probability(binom.sf(k - 1, n, p0))


def rejection_threshold(n: int, p0: float, alpha: float) -> int | None:
    """Smallest k with P(X >= k) <= alpha, or None if k = n still does not."""
    if n < 0:
        raise ValueError("n must be non-negative")
    if binomial_p_ge(n, n, p0) > alpha:
        return None
    lo = 0
    hi = n
    while lo < hi:
        mid = (lo + hi) // 2
        if binomial_p_ge(mid, n, p0) <= alpha:
            hi = mid
        else:
            lo = mid + 1
    return lo


def bonferroni_threshold(n: int, p0: float, alpha: float, family: int) -> int | None:
    """Holm's first step is Bonferroni: alpha / family."""
    if family < 1:
        raise ValueError("family must be positive")
    return rejection_threshold(n, p0, alpha / family)


def t1_pooled(k: int, n: int, p0: float, alpha: float) -> T1Result:
    """Exact one-sided pooled binomial. Reject when k reaches ``threshold``."""
    if k < 0 or k > n:
        raise ValueError("k must lie in 0..n")
    threshold = rejection_threshold(n, p0, alpha)
    p_value = binomial_p_ge(k, n, p0)
    reject = threshold is not None and k >= threshold
    return T1Result(
        k=k,
        n=n,
        p0=p0,
        alpha=alpha,
        threshold=threshold,
        p_value=p_value,
        reject=reject,
    )


def t2_holm(
    per_side_counts: Mapping[str, tuple[int, int]],
    p0: float,
    alpha: float,
) -> tuple[str, ...]:
    """Exact binomial per side, Holm step-down. Returns flagged side ids.

    ``per_side_counts`` maps a side id to ``(k, n)``. Family size is the number
    of keys. Rank 1 uses alpha/m; the step stops at the first non-rejection.
    """
    scored = sorted(
        ((sid, binomial_p_ge(k, n, p0)) for sid, (k, n) in per_side_counts.items()),
        key=lambda item: (item[1], item[0]),
    )
    family = len(scored)
    flagged: list[str] = []
    for rank, (sid, p_value) in enumerate(scored):
        if p_value <= alpha / (family - rank):
            flagged.append(sid)
            continue
        break
    return tuple(flagged)


def same_sign_rule(deltas: Sequence[int], share: float) -> bool:
    """True when the majority sign among non-zero deltas is at least ``share``.

    Matches (zero) are not mismatches and are not in the denominator. An empty
    mismatch list does not establish a direction.
    """
    if not 0 < share <= 1:
        raise ValueError("share must be in (0, 1]")
    signed = [delta for delta in deltas if delta != 0]
    if not signed:
        return False
    positive = sum(1 for delta in signed if delta > 0)
    majority = max(positive, len(signed) - positive)
    return (majority / len(signed)) >= share


def clopper_pearson_upper(k: int, n: int, ucb_level: float) -> float:
    """One-sided Clopper-Pearson upper bound at confidence ``ucb_level``.

    Beta(ucb_level; k+1, n-k). ``k == n`` is 1. This is the exact bound,
    not a Wald or Wilson interval.
    """
    if n <= 0 or k < 0 or k > n:
        raise ValueError("k must lie in 0..n with n positive")
    if not 0 < ucb_level < 1:
        raise ValueError("ucb_level must be in (0, 1)")
    if k == n:
        return 1.0
    return _as_probability(beta.ppf(ucb_level, k + 1, n - k))


def kill_rule(k: int, n: int, ucb_level: float, kill_ucb: float) -> bool:
    """True when the one-sided upper bound is at or below ``kill_ucb``.

    ``n == 0`` does not kill. A missing sample is not a zero rate.
    """
    if n <= 0:
        return False
    return clopper_pearson_upper(k, n, ucb_level) <= kill_ucb


def verdict(
    t1: bool, t2_flags: Sequence[str], sign_ok: bool, kill: bool
) -> tuple[VerdictWord, str]:
    """PASS if T1 rejects or a Holm flag meets the sign rule. Else KILL or not.

    ``sign_ok`` means at least one flagged side meets ``same_sign_rule``.
    KILL is only reached when T1 did not reject. Otherwise INCONCLUSIVE.
    """
    flags = tuple(t2_flags)
    if t1 and flags and sign_ok:
        return "PASS", f"T1 rejected; T2 flagged {', '.join(flags)} with the sign rule"
    if t1:
        return "PASS", "T1 pooled exact one-sided binomial rejected"
    if flags and sign_ok:
        return "PASS", f"T2 Holm flagged {', '.join(flags)} and the sign rule holds"
    if kill:
        return (
            "KILL",
            (
                "T1 not rejected and the pooled one-sided Clopper-Pearson upper bound "
                "is at or below the kill level"
            ),
        )
    if flags:
        return (
            "INCONCLUSIVE",
            (
                f"T2 flagged {', '.join(flags)} but the sign rule failed, "
                "and the kill bound was not met"
            ),
        )
    return (
        "INCONCLUSIVE",
        "T1 not rejected, no sign-qualified T2 flag, and the kill bound was not met",
    )


def half_bounds(
    start: dt.date, end: dt.date
) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]]:
    """Calendar halves, not a sample median. The first half keeps the middle day.

    2026-07-05..2026-10-30 splits at 2026-09-01 / 2026-09-02 (59 days each).
    """
    if end < start:
        raise ValueError("end before start")
    mid = start + dt.timedelta(days=(end - start).days // 2)
    return (start, mid), (mid + dt.timedelta(days=1), end)


def half_for(day: dt.date, start: dt.date, end: dt.date) -> int:
    """1 or 2. Raises when ``day`` is outside the window."""
    first, second = half_bounds(start, end)
    if first[0] <= day <= first[1]:
        return 1
    if second[0] <= day <= second[1]:
        return 2
    raise ValueError(f"{day.isoformat()} is outside {start.isoformat()}..{end.isoformat()}")


def _owners(stations: Sequence[Station], sides: Sequence[str]) -> dict[str, tuple[str, str]]:
    owners: dict[str, tuple[str, str]] = {}
    for station in stations:
        for side in sides:
            ticker = _series_for(station, side)
            if ticker is None:
                continue
            owner = (station.city, side)
            if ticker in owners and owners[ticker] != owner:
                raise ValueError(f"series {ticker} is claimed by two station-sides")
            owners[ticker] = owner
    return owners


def _annotate(
    markets: Sequence[Mapping[str, Any]], station: str, side: str
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for market in markets:
        row = dict(market)
        row["station"] = station
        row["side"] = side
        annotated.append(row)
    return annotated


def _markets_from_payload(payload: object) -> list[Mapping[str, Any]]:
    rows: object = payload
    if isinstance(payload, dict):
        rows = payload.get("markets")
    if not isinstance(rows, list):
        raise TypeError("Kalshi payload must be a list or an object with markets")
    parsed: list[Mapping[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise TypeError("Kalshi market must be a JSON object")
        parsed.append(item)
    return parsed


def _read_kalshi_file(path: Path) -> list[Mapping[str, Any]]:
    return _markets_from_payload(json.loads(path.read_text(encoding="utf-8")))


def _load_dry_markets(
    scratch: Path,
    owners: Mapping[str, tuple[str, str]],
    blocked: Mapping[tuple[str, str], str] | None = None,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str]]:
    """Read ``scratch/kalshi/{series}.json``. Keys already in ``blocked`` stay out."""
    rows: list[dict[str, Any]] = []
    found = dict(blocked or {})
    for series, (station, side) in owners.items():
        if (station, side) in found:
            continue
        path = scratch / "kalshi" / f"{series}.json"
        if not path.is_file():
            found[(station, side)] = "fixture_missing"
            continue
        rows.extend(_annotate(_read_kalshi_file(path), station, side))
    return rows, found


def _index_cli_by_side(text: str, sides: Sequence[str]) -> dict[str, CliTextIndex]:
    return {side: cli_days_from_text(text, side) for side in sides}


def _load_dry_cli(
    scratch: Path,
    stations: Sequence[Station],
    sides: Sequence[str],
    blocked: Mapping[tuple[str, str], str] | None = None,
) -> dict[tuple[str, str], CliTextIndex | str]:
    """Read ``scratch/iem/{city}.txt``. A blocked side keeps its exclusion string."""
    loaded: dict[tuple[str, str], CliTextIndex | str] = {}
    prior = blocked or {}
    for station in stations:
        path = scratch / "iem" / f"{station.city}.txt"
        if path.is_file():
            indexed = _index_cli_by_side(path.read_text(encoding="utf-8"), sides)
        else:
            indexed = {}
        for side in sides:
            key = (station.city, side)
            if key in prior:
                loaded[key] = prior[key]
            elif side in indexed:
                loaded[key] = indexed[side]
            else:
                loaded[key] = "fixture_missing"
    return loaded


def build_rows(
    stations: Sequence[Station],
    sides: Sequence[str],
    start: dt.date,
    end: dt.date,
    kalshi: KalshiSettled,
    cli_by_side: Mapping[tuple[str, str], CliTextIndex | str],
    blocked: Mapping[tuple[str, str], str],
) -> tuple[DayRow, ...]:
    """One row per station, side, and climate date in the window. Nothing dropped."""
    rows: list[DayRow] = []
    for station in stations:
        for side in sides:
            day = start
            while day <= end:
                rows.append(_day_row(station, side, day, start, end, kalshi, cli_by_side, blocked))
                day += dt.timedelta(days=1)
    return tuple(rows)


def _day_row(
    station: Station,
    side: str,
    day: dt.date,
    start: dt.date,
    end: dt.date,
    kalshi: KalshiSettled,
    cli_by_side: Mapping[tuple[str, str], CliTextIndex | str],
    blocked: Mapping[tuple[str, str], str],
) -> DayRow:
    half = half_for(day, start, end)
    series = _series_for(station, side)
    block = blocked.get((station.city, side))
    slot = cli_by_side.get((station.city, side))
    kalshi_day = _kalshi_day(series, block, kalshi, station.city, side, day)
    kalshi_reason = _kalshi_reason(series, block, kalshi_day)
    cli_reason = _cli_reason(slot, day)
    exclusion = _combined_reason(kalshi_reason, cli_reason)
    cli_value = _cli_value(slot, day)
    kalshi_value = None if kalshi_day is None else kalshi_day.expiration_f
    if exclusion is not None:
        return _excluded_row(
            station.city,
            side,
            day,
            half,
            kalshi_value,
            cli_value,
            exclusion,
            kalshi_reason,
            cli_reason,
        )
    assert kalshi_value is not None and cli_value is not None
    judged = classify_mismatch(kalshi_value, cli_value)
    return DayRow(
        station=station.city,
        side=side,
        climate_date=day,
        kalshi_f=kalshi_value,
        cli_f=cli_value,
        delta=judged.delta,
        outcome=judged.kind,
        exclusion=None,
        half=half,
    )


def _kalshi_day(
    series: str | None,
    block: str | None,
    kalshi: KalshiSettled,
    station: str,
    side: str,
    day: dt.date,
) -> KalshiDay | None:
    if series is None or block is not None:
        return None
    return kalshi.days.get((station, side, day))


def _excluded_row(
    station: str,
    side: str,
    day: dt.date,
    half: int,
    kalshi_value: int | None,
    cli_value: int | None,
    exclusion: str,
    kalshi_reason: str | None,
    cli_reason: str | None,
) -> DayRow:
    return DayRow(
        station=station,
        side=side,
        climate_date=day,
        kalshi_f=kalshi_value,
        cli_f=cli_value,
        delta=None,
        outcome="excluded",
        exclusion=exclusion,
        half=half,
        kalshi_reason=kalshi_reason,
        cli_reason=cli_reason,
    )


def _cli_value(slot: CliTextIndex | str | None, day: dt.date) -> int | None:
    if not isinstance(slot, CliTextIndex):
        return None
    label = slot.days.get(day)
    if label is None or label.exclusion is not None:
        return None
    return label.value_f


def _kalshi_reason(
    series: str | None, block: str | None, kalshi_day: KalshiDay | None
) -> str | None:
    """Why the Kalshi label is unusable. None means the integer is usable."""
    if series is None:
        return "missing_series"
    if block is not None:
        return block
    if kalshi_day is None:
        return "missing_kalshi"
    return kalshi_day.exclusion


def _cli_reason(slot: CliTextIndex | str | None, day: dt.date) -> str | None:
    """Why the CLI label is unusable. None means the integer is usable."""
    if isinstance(slot, str):
        return slot
    if not isinstance(slot, CliTextIndex):
        return "cli_not_loaded"
    label = slot.days.get(day)
    if label is None or label.value_f is None:
        return label.exclusion if label is not None and label.exclusion else "missing_cli"
    return None


def _combined_reason(kalshi_reason: str | None, cli_reason: str | None) -> str | None:
    """Single gate reason. Both labels missing stays ``missing_both``."""
    if kalshi_reason is None and cli_reason is None:
        return None
    if kalshi_reason == "missing_kalshi" and cli_reason == "missing_cli":
        return "missing_both"
    return kalshi_reason or cli_reason


def side_id(station: str, side: str) -> str:
    """Holm key. City, not ICAO, so it matches the stations file."""
    return f"{station}:{side}"


def _paired(rows: Sequence[DayRow]) -> tuple[DayRow, ...]:
    return tuple(row for row in rows if row.outcome != "excluded" and row.delta is not None)


def _mismatch_counts(rows: Sequence[DayRow]) -> tuple[int, int]:
    paired = _paired(rows)
    mismatches = sum(1 for row in paired if row.outcome == "mismatch")
    return mismatches, len(paired)


def _deltas(rows: Sequence[DayRow]) -> tuple[int, ...]:
    return tuple(row.delta for row in _paired(rows) if row.delta is not None)


def _day_exclusion_counts(rows: Sequence[DayRow]) -> dict[str, int]:
    counts: Counter[str] = Counter(row.exclusion for row in rows if row.exclusion is not None)
    return dict(counts)


def _side_outcome(flagged: bool, sign_ok: bool, card_kill: bool) -> VerdictWord:
    """PASS only for a Holm flag that also meets the sign rule.

    KILL iff this side is not a PASS and the card itself is KILL (prereg §6).
    The per-side Clopper-Pearson bound is not a label.
    """
    if flagged and sign_ok:
        return "PASS"
    if card_kill:
        return "KILL"
    return "INCONCLUSIVE"


def _one_side(
    station: str,
    side: str,
    rows: Sequence[DayRow],
    flagged: frozenset[str],
    p0: float,
    share: float,
) -> SideStat:
    """Counts and a provisional outcome. Card KILL is applied afterwards."""
    k, n = _mismatch_counts(rows)
    deltas = _deltas(rows)
    positive = sum(1 for delta in deltas if delta > 0)
    negative = sum(1 for delta in deltas if delta < 0)
    sign_ok = same_sign_rule(deltas, share)
    upper = None if n <= 0 else clopper_pearson_upper(k, n, UCB_LEVEL)
    sid = side_id(station, side)
    is_flagged = sid in flagged
    return SideStat(
        side_id=sid,
        station=station,
        side=side,
        n=n,
        k=k,
        p_value=binomial_p_ge(k, n, p0),
        flagged=is_flagged,
        positive=positive,
        negative=negative,
        sign_ok=sign_ok,
        upper=upper,
        outcome=_side_outcome(is_flagged, sign_ok, False),
        day_exclusions=_day_exclusion_counts(rows),
    )


def side_statistics(
    rows: Sequence[DayRow],
    p0: float,
    alpha: float,
    share: float,
) -> tuple[tuple[SideStat, ...], tuple[str, ...]]:
    """Every station-side in ``rows``, including n = 0. Holm family is 48."""
    order: list[tuple[str, str]] = []
    grouped: dict[tuple[str, str], list[DayRow]] = defaultdict(list)
    for row in rows:
        key = (row.station, row.side)
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)
    if len(order) != REFERENCE_FAMILY:
        raise ValueError(f"Holm family size must be {REFERENCE_FAMILY}, found {len(order)}")
    counts = {
        side_id(station, side): _mismatch_counts(grouped[(station, side)])
        for station, side in order
    }
    flags = t2_holm(counts, p0, alpha)
    flagged = frozenset(flags)
    stats = tuple(
        _one_side(station, side, grouped[(station, side)], flagged, p0, share)
        for station, side in order
    )
    return stats, flags


def apply_side_outcomes(stats: Sequence[SideStat], card_kill: bool) -> tuple[SideStat, ...]:
    """Stamp per-side labels from the card-level kill. Computed after the card."""
    return tuple(
        replace(stat, outcome=_side_outcome(stat.flagged, stat.sign_ok, card_kill))
        for stat in stats
    )


def evaluate_card(
    stats: Sequence[SideStat],
    flags: Sequence[str],
    p0: float,
    alpha_t1: float,
    alpha_t2: float,
    kill_ucb: float,
) -> CardResult:
    """Card PASS is T1 or a sign-qualified T2 flag. Side PASS is not implied by T1."""
    k = sum(stat.k for stat in stats)
    n = sum(stat.n for stat in stats)
    t1 = t1_pooled(k, n, p0, alpha_t1)
    sign_ok = any(stat.sign_ok for stat in stats if stat.side_id in flags)
    kill = kill_rule(k, n, UCB_LEVEL, kill_ucb)
    name, reason = verdict(t1.reject, flags, sign_ok, kill)
    reference = {
        size: bonferroni_threshold(size, p0, alpha_t2, REFERENCE_FAMILY) for size in REFERENCE_NS
    }
    return CardResult(
        t1=t1,
        t2_flags=tuple(flags),
        sign_ok=sign_ok,
        kill=kill,
        upper=None if n <= 0 else clopper_pearson_upper(k, n, UCB_LEVEL),
        name=name,
        reason=reason,
        planning_threshold=rejection_threshold(PLANNING_N, p0, alpha_t1),
        reference_thresholds=reference,
    )


@dataclass(frozen=True, slots=True)
class HalfStat:
    """One matched-day half of one side. ``sign`` is the summed paired deltas."""

    half: int
    side_id: str
    start: dt.date | None
    end: dt.date | None
    n: int
    k: int
    mean_delta: float | None
    sign: str


def _half_sign(total: int, n: int) -> str:
    if n == 0:
        return "empty"
    if total > 0:
        return "positive"
    if total < 0:
        return "negative"
    return "zero"


def assign_matched_halves(rows: Sequence[DayRow]) -> tuple[DayRow, ...]:
    """First floor(n/2) matched days per side are half 1. Excluded days are 0.

    Prereg §5. Not the calendar split ``half_bounds`` still documents.
    """
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.outcome != "excluded" and row.delta is not None:
            groups[(row.station, row.side)].append(index)
    halves = _matched_half_index(rows, groups)
    return tuple(replace(row, half=halves[index]) for index, row in enumerate(rows))


def _matched_half_index(
    rows: Sequence[DayRow], groups: Mapping[tuple[str, str], Sequence[int]]
) -> dict[int, int]:
    halves = dict.fromkeys(range(len(rows)), 0)
    for indexes in groups.values():
        ordered = sorted(indexes, key=lambda index: rows[index].climate_date)
        cut = len(ordered) // 2
        for index in ordered[:cut]:
            halves[index] = 1
        for index in ordered[cut:]:
            halves[index] = 2
    return halves


def _one_half(rows: Sequence[DayRow], half: int, sid: str) -> HalfStat:
    paired = [row for row in rows if row.half == half and row.delta is not None]
    deltas = [row.delta for row in paired if row.delta is not None]
    total = sum(deltas)
    n = len(deltas)
    mismatches = sum(1 for row in paired if row.outcome == "mismatch")
    mean = None if n == 0 else total / n
    start = min((row.climate_date for row in paired), default=None)
    end = max((row.climate_date for row in paired), default=None)
    return HalfStat(half, sid, start, end, n, mismatches, mean, _half_sign(total, n))


def _halves_stable(stats: Sequence[HalfStat]) -> bool:
    """True when every side with two signed halves agrees, and at least one does."""
    by_side: dict[str, dict[int, str]] = defaultdict(dict)
    for stat in stats:
        by_side[stat.side_id][stat.half] = stat.sign
    saw = False
    for signs in by_side.values():
        first, second = signs.get(1, "empty"), signs.get(2, "empty")
        if first not in {"positive", "negative"} or second not in {"positive", "negative"}:
            continue
        if first != second:
            return False
        saw = True
    return saw


def half_statistics(rows: Sequence[DayRow]) -> tuple[tuple[HalfStat, ...], bool]:
    """Per-side matched-day halves. A stability table, never a gate."""
    order: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.station, row.side)
        if key not in seen:
            seen.add(key)
            order.append(key)
    found = [
        _one_half(
            [row for row in rows if row.station == station and row.side == side],
            half,
            side_id(station, side),
        )
        for station, side in order
        for half in (1, 2)
    ]
    return tuple(found), _halves_stable(found)


def _strike(row: Mapping[str, Any], key: str) -> float | None:
    raw = row.get(key)
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def tally_buckets(
    markets: Sequence[Mapping[str, Any]],
    cli_by_side: Mapping[tuple[str, str], CliTextIndex | str],
    start: dt.date,
    end: dt.date,
) -> BucketTally:
    """In-window markets only. Excluded rows and missing CLI are skipped, not gated."""
    agree = disagree = skipped = 0
    for market in markets:
        day = _event_climate_date(market.get("event_ticker"))
        if day is None or day < start or day > end:
            continue
        station, side = _row_identity(market)
        cli_int = _cli_value(cli_by_side.get((station, side)), day)
        if _row_exclusion(market) is not None or cli_int is None:
            skipped += 1
            continue
        word = bucket_check(
            str(market.get("result") or ""),
            cli_int,
            _strike(market, "floor_strike"),
            _strike(market, "cap_strike"),
            str(market.get("strike_type") or ""),
        )
        if word == "agree":
            agree += 1
        else:
            disagree += 1
    return BucketTally(agree=agree, disagree=disagree, skipped=skipped)


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Validated CLI inputs. The live pull is the only network path."""

    stations_file: Path
    prereg: Path
    prereg_sha: str
    start: dt.date
    end: dt.date
    sides: tuple[str, ...]
    scratch_dir: Path
    out_dir: Path
    dry_run: bool
    force_reason: str | None


@dataclass(frozen=True, slots=True)
class KalshiCopyReport:
    """Overlap of the historical and live Kalshi market copies (S6)."""

    overlap: int
    conflicts: int
    historical_rows: int
    historical_not_finalized: int
    cutoff: dt.date


@dataclass(frozen=True, slots=True)
class Report:
    """Everything the markdown and parquet are allowed to say."""

    config: RunConfig
    stations_sha256: str
    prereg_sha256: str
    stations: tuple[Station, ...]
    kalshi_pull_ts: str
    iem_pull_ts: str
    rows: tuple[DayRow, ...]
    side_stats: tuple[SideStat, ...]
    card: CardResult
    halves: tuple[HalfStat, ...]
    stable: bool
    buckets: BucketTally
    market_exclusions: Mapping[tuple[str, str], Mapping[str, int]]
    undated: Mapping[str, Mapping[str, int]]
    requests: RequestCounts
    cli_body_sha256: Mapping[str, str]
    cli_overwrites: Mapping[str, int]
    copies: KalshiCopyReport
    statuses: Mapping[str, int]


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6g}"


def _md_table(headers: Sequence[str], body: Sequence[Sequence[object]]) -> list[str]:
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    lines = ["| " + " | ".join(str(cell) for cell in row) + " |" for row in body]
    return [head, rule, *lines, ""]


def _exclusion_cell(counts: Mapping[str, int]) -> str:
    if not counts:
        return "0"
    return ", ".join(f"{name}={counts[name]}" for name in sorted(counts))


def _sign_share(positive: int, negative: int) -> str:
    total = positive + negative
    if total == 0:
        return "n/a"
    return f"{max(positive, negative) / total:.3f}"


def _section_frozen(report: Report) -> list[str]:
    cfg = report.config
    card = report.card
    force = cfg.force_reason if cfg.force_reason is not None else "none"
    reference = ", ".join(f"n={size} k={card.reference_thresholds[size]}" for size in REFERENCE_NS)
    lines = [
        "## Frozen inputs",
        "",
        f"- prereg: `{cfg.prereg}`",
        f"- prereg sha256: `{report.prereg_sha256}`",
        f"- stations file: `{cfg.stations_file}`",
        f"- stations sha256: `{report.stations_sha256}`",
        f"- iem_pull_ts: `{report.iem_pull_ts}`",
        f"- kalshi_pull_ts: `{report.kalshi_pull_ts}`",
        f"- verdict: {card.name}",
        f"- climate dates: {cfg.start.isoformat()} .. {cfg.end.isoformat()}",
        f"- sides: {', '.join(cfg.sides)}",
        f"- p0: {P0}",
        f"- alpha_t1: {ALPHA_T1}",
        f"- alpha_t2: {ALPHA_T2}",
        f"- same_sign_share: {SAME_SIGN_SHARE}",
        f"- kill_ucb: {KILL_UCB}",
        f"- ucb_level: {UCB_LEVEL} (fixed, not a flag)",
        f"- force-new-look: {force}",
        (
            f"- planning N={PLANNING_N} pooled threshold k={card.planning_threshold} "
            f"at p0={P0}, alpha={ALPHA_T1}"
        ),
        f"- Bonferroni first step over {REFERENCE_FAMILY} sides at alpha {ALPHA_T2}: {reference}",
        "",
    ]
    return lines


def _section_stations(report: Report) -> list[str]:
    body = [
        (s.city, s.icao, s.timezone, s.cli_id, s.high_series or "", s.low_series or "")
        for s in report.stations
    ]
    headers = ("city", "icao", "timezone", "cli_id", "high_series", "low_series")
    return ["## Stations", "", *_md_table(headers, body)]


def _section_sides(report: Report) -> list[str]:
    body = [
        (
            stat.side_id,
            stat.n,
            stat.k,
            _exclusion_cell(stat.day_exclusions),
            _fmt(stat.p_value),
            "yes" if stat.flagged else "no",
            stat.positive,
            stat.negative,
            _sign_share(stat.positive, stat.negative),
            "yes" if stat.sign_ok else "no",
            _fmt(stat.upper),
            stat.outcome,
        )
        for stat in report.side_stats
    ]
    headers = (
        "side",
        "n",
        "k",
        "day_exclusions",
        "p",
        "holm",
        "pos",
        "neg",
        "sign_share",
        "sign_ok",
        "side_ucb",
        "outcome",
    )
    return ["## Per-side sample", "", *_md_table(headers, body)]


def _section_t1(report: Report) -> list[str]:
    t1 = report.card.t1
    body = [(t1.k, t1.n, t1.p0, t1.alpha, t1.threshold, _fmt(t1.p_value), t1.reject)]
    headers = ("k", "n", "p0", "alpha", "threshold", "p_value", "reject")
    return ["## T1 pooled exact one-sided binomial", "", *_md_table(headers, body)]


def _section_t2(report: Report) -> list[str]:
    family = len(report.side_stats)
    flagged = ", ".join(report.card.t2_flags) if report.card.t2_flags else "none"
    body = [
        (stat.side_id, stat.k, stat.n, _fmt(stat.p_value), "yes" if stat.flagged else "no")
        for stat in report.side_stats
    ]
    lines = [
        "## T2 Holm",
        "",
        f"Family m = {family} (requested station-sides, including n = 0). Flagged: {flagged}.",
        "",
        *_md_table(("side", "k", "n", "p", "flagged"), body),
    ]
    return lines


def _section_sign(report: Report) -> list[str]:
    body = [
        (
            stat.side_id,
            stat.positive,
            stat.negative,
            _sign_share(stat.positive, stat.negative),
            "yes" if stat.sign_ok else "no",
            "yes" if stat.flagged else "no",
        )
        for stat in report.side_stats
    ]
    headers = ("side", "positive", "negative", "share", "sign_ok", "flagged")
    note = "Card sign rule applies only to Holm-flagged sides. Not a pooled-T1 input."
    return ["## Sign", "", note, "", *_md_table(headers, body)]


def _section_halves(report: Report) -> list[str]:
    body = [
        (
            half.side_id,
            half.half,
            half.start if half.start is not None else "n/a",
            half.end if half.end is not None else "n/a",
            half.n,
            half.k,
            _fmt(half.mean_delta),
            half.sign,
        )
        for half in report.halves
    ]
    headers = ("side", "half", "start", "end", "n", "k", "mean_delta", "sign")
    stable = "yes" if report.stable else "no"
    return [
        "## Half-split stability",
        "",
        "First floor(n/2) matched days per side, chronological. Not a gate.",
        "",
        *_md_table(headers, body),
        f"Stable (every two-signed side agrees, and at least one does): {stable}.",
        "",
    ]


def _section_buckets(report: Report) -> list[str]:
    buckets = report.buckets
    body = [(buckets.agree, buckets.disagree, buckets.skipped)]
    return [
        "## Bucket check",
        "",
        "Reported only. Agree and disagree do not enter the verdict.",
        "",
        *_md_table(("agree", "disagree", "skipped"), body),
    ]


def _named_counts(values: Sequence[str | None]) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter(value for value in values if value)
    return sorted(counts.items()) or [("none", 0)]


def _section_exclusions(report: Report) -> list[str]:
    day_body = _named_counts([row.exclusion for row in report.rows])
    kalshi_body = _named_counts([row.kalshi_reason for row in report.rows])
    cli_body = _named_counts([row.cli_reason for row in report.rows])
    market_body = [
        (side_id(station, side), reason, count)
        for (station, side), counts in sorted(report.market_exclusions.items())
        for reason, count in sorted(counts.items())
    ] or [("none", "none", 0)]
    undated_body = [
        (city, reason, count)
        for city, counts in sorted(report.undated.items())
        for reason, count in sorted(counts.items())
        if count
    ] or [("none", "none", 0)]
    overwrite_body = sorted(report.cli_overwrites.items()) or [("none", 0)]
    return [
        "## Day-row exclusions",
        "",
        *_md_table(("reason", "n"), day_body),
        "## Day-row kalshi_reason",
        "",
        *_md_table(("reason", "n"), kalshi_body),
        "## Day-row cli_reason",
        "",
        *_md_table(("reason", "n"), cli_body),
        "## Kalshi market-row exclusions",
        "",
        *_md_table(("side", "reason", "n"), market_body),
        "## CLI undated products",
        "",
        "Counted once per city, not once per side.",
        "",
        *_md_table(("city", "reason", "n"), undated_body),
        "## CLI final overwrites",
        "",
        "Times a later product replaced the stored product for a date. Per side.",
        "",
        *_md_table(("side", "overwrites"), overwrite_body),
    ]


def _section_bodies(report: Report) -> list[str]:
    body = sorted(report.cli_body_sha256.items()) or [("none", "n/a")]
    return [
        "## CLI raw body sha256",
        "",
        "SHA-256 of the raw IEM body, one per city.",
        "",
        *_md_table(("city", "sha256"), body),
    ]


def _section_copies(report: Report) -> list[str]:
    copies = report.copies
    statuses = ", ".join(f"{name}={count}" for name, count in sorted(report.statuses.items()))
    status_text = statuses if statuses else "none"
    return [
        "## Kalshi historical and live copies",
        "",
        f"Client cutoff: {copies.cutoff.isoformat()} (days before it are historical).",
        "",
        f"- overlap tickers: {copies.overlap}",
        f"- expiration conflicts: {copies.conflicts}",
        f"- historical rows: {copies.historical_rows}",
        f"- historical rows not status finalized: {copies.historical_not_finalized}",
        f"- status counts: {status_text}",
        "",
    ]


def _section_verdict(report: Report) -> list[str]:
    counts = report.requests
    return [
        "## Verdict",
        "",
        f"**{report.card.name}** — {report.card.reason}",
        "",
        f"Pooled one-sided upper bound: {_fmt(report.card.upper)}.",
        "",
        "## Request counts",
        "",
        f"- mode: {counts.mode}",
        f"- kalshi_get_json: {counts.kalshi_get_json}",
        f"- iem_fetches: {counts.iem_fetches}",
        f"- kalshi_errors: {counts.kalshi_errors}",
        f"- iem_errors: {counts.iem_errors}",
        "",
    ]


def render_report(report: Report) -> str:
    """The one markdown look. No path outside ``--out-dir`` is named as an output."""
    parts = ["# Card E: CLI versus Kalshi expiration value", ""]
    for section in (
        _section_frozen,
        _section_stations,
        _section_sides,
        _section_t1,
        _section_t2,
        _section_sign,
        _section_halves,
        _section_buckets,
        _section_exclusions,
        _section_bodies,
        _section_copies,
        _section_verdict,
    ):
        parts.extend(section(report))
    return "\n".join(parts).rstrip() + "\n"


def output_paths(out_dir: Path) -> tuple[Path, Path]:
    return out_dir / MARKDOWN_NAME, out_dir / PARQUET_NAME


def assert_one_look(out_dir: Path, force_reason: str | None) -> None:
    """Refuse a second look at an existing output unless a reason is recorded (L-34)."""
    existing = [path for path in output_paths(out_dir) if path.exists()]
    if not existing or force_reason:
        return
    names = ", ".join(path.name for path in existing)
    raise SystemExit(f"refusing to overwrite {names}; pass --force-new-look with a reason")


def _column_values(rows: Sequence[DayRow]) -> dict[str, list[Any]]:
    return {
        "station": [row.station for row in rows],
        "side": [row.side for row in rows],
        "outcome": [row.outcome for row in rows],
        "exclusion": [row.exclusion for row in rows],
        "kalshi_reason": [row.kalshi_reason for row in rows],
        "cli_reason": [row.cli_reason for row in rows],
    }


def write_parquet(rows: Sequence[DayRow], path: Path, metadata: Mapping[str, str]) -> None:
    """Write rows plus schema metadata. The caller publishes the file atomically."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    columns: dict[str, Any] = _column_values(rows)
    columns["climate_date"] = pa.array([row.climate_date for row in rows], type=pa.date32())
    columns["kalshi_f"] = pa.array([row.kalshi_f for row in rows], type=pa.int32())
    columns["cli_f"] = pa.array([row.cli_f for row in rows], type=pa.int32())
    columns["delta"] = pa.array([row.delta for row in rows], type=pa.int32())
    columns["half"] = pa.array([row.half for row in rows], type=pa.int8())
    encoded = {key.encode("utf-8"): value.encode("utf-8") for key, value in metadata.items()}
    pq.write_table(pa.table(columns).replace_schema_metadata(encoded), path)


def _write_temps(
    parquet_tmp: Path,
    markdown_tmp: Path,
    rows: Sequence[DayRow],
    markdown: str,
    metadata: Mapping[str, str],
) -> None:
    try:
        write_parquet(rows, parquet_tmp, metadata)
        markdown_tmp.write_text(markdown, encoding="utf-8")
    except Exception:
        parquet_tmp.unlink(missing_ok=True)
        markdown_tmp.unlink(missing_ok=True)
        raise


def _publish_temps(
    parquet_tmp: Path, parquet_path: Path, markdown_tmp: Path, markdown_path: Path
) -> None:
    """Replace both finals only after both temps exist. Roll back a half publish."""
    os.replace(parquet_tmp, parquet_path)
    try:
        os.replace(markdown_tmp, markdown_path)
    except Exception:
        parquet_path.unlink(missing_ok=True)
        markdown_tmp.unlink(missing_ok=True)
        raise


def emit_outputs(
    out_dir: Path, rows: Sequence[DayRow], markdown: str, metadata: Mapping[str, str]
) -> None:
    """Write parquet and markdown to temps in ``out_dir``, then replace both."""
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown_path, parquet_path = output_paths(out_dir)
    markdown_tmp = out_dir / f".{MARKDOWN_NAME}.tmp"
    parquet_tmp = out_dir / f".{PARQUET_NAME}.tmp"
    _write_temps(parquet_tmp, markdown_tmp, rows, markdown, metadata)
    _publish_temps(parquet_tmp, parquet_path, markdown_tmp, markdown_path)


def _http_code(exc: BaseException) -> int | None:
    """HTTP status when the exception carries one. Never the message text."""
    if isinstance(exc, RateLimitedError):
        return 429
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    return None


def _note_fetch_error(kind: str, label: str, exc: BaseException) -> None:
    """Type name and HTTP code only. Exception text can carry a URL."""
    code = _http_code(exc)
    suffix = f" http_{code}" if code is not None else ""
    print(f"{kind} {label} {type(exc).__name__}{suffix}", file=sys.stderr)


def _write_markets(path: Path, markets: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"markets": [dict(market) for market in markets]}
    path.write_text(json.dumps(payload), encoding="utf-8")


class _CountedKalshi:
    """Counts ``get_json`` and keeps each page so the two copies can be compared."""

    def __init__(self, inner: Any) -> None:
        self.calls = 0
        self.pages: list[tuple[str, Any]] = []
        self._inner = inner
        self._original = inner.get_json
        inner.get_json = self._counted

    def _counted(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        self.calls += 1
        payload = self._original(path, params)
        self.pages.append((path, payload))
        return payload

    def list_series_markets(self, series: str) -> list[Mapping[str, Any]]:
        found = self._inner.list_series_markets(series)
        return cast(list[Mapping[str, Any]], found)


def _counting_kalshi() -> _MarketClient:
    """``KalshiHttp`` unchanged, paced at or below 4 requests/second, calls counted."""
    from k1_kalshi_prior import KalshiHttp  # type: ignore[import-not-found]

    inner = KalshiHttp(
        min_interval_s=KALSHI_MIN_INTERVAL_S,
        user_agent=KALSHI_USER_AGENT,
        sleep=time.sleep,
    )
    return _CountedKalshi(inner)


@dataclass(frozen=True, slots=True)
class _SeriesPull:
    raw: tuple[Mapping[str, Any], ...]
    annotated: tuple[dict[str, Any], ...]
    reason: str | None


@dataclass(frozen=True, slots=True)
class _KalshiPull:
    blocked: Mapping[tuple[str, str], str]
    markets: tuple[dict[str, Any], ...]
    calls: int
    errors: int
    copies: KalshiCopyReport
    statuses: Mapping[str, int]
    by_series: Mapping[str, tuple[Mapping[str, Any], ...]]
    pulled_at: str


@dataclass(frozen=True, slots=True)
class _FetchedCity:
    reason: str | None
    text: str | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class _IemPull:
    blocked: Mapping[tuple[str, str], str]
    fetches: int
    errors: int
    texts: Mapping[str, str]
    sha256: Mapping[str, str]
    cli: Mapping[tuple[str, str], CliTextIndex | str]
    overwrites: Mapping[str, int]
    pulled_at: str


@dataclass(frozen=True, slots=True)
class _ScratchPending:
    markets_by_series: Mapping[str, tuple[Mapping[str, Any], ...]]
    texts: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _Inputs:
    """What ``execute`` may score. ``scratch`` is written only after the B6 gate."""

    markets: tuple[Mapping[str, Any], ...]
    blocked: Mapping[tuple[str, str], str]
    cli: Mapping[tuple[str, str], CliTextIndex | str]
    counts: RequestCounts
    kalshi_pull_ts: str
    iem_pull_ts: str
    cli_body_sha256: Mapping[str, str]
    cli_overwrites: Mapping[str, int]
    copies: KalshiCopyReport
    statuses: Mapping[str, int]
    scratch: _ScratchPending | None


def _pull_one_series(client: _MarketClient, series: str, owner: tuple[str, str]) -> _SeriesPull:
    """One series. Programming errors propagate; transport errors become a reason."""
    try:
        markets = client.list_series_markets(series)
    except _PULL_ERRORS as exc:
        _note_fetch_error("kalshi", series, exc)
        return _SeriesPull((), (), "kalshi_fetch_error")
    raw = tuple(market for market in markets if isinstance(market, Mapping))
    return _SeriesPull(raw, tuple(_annotate(raw, owner[0], owner[1])), None)


def _pull_kalshi(owners: Mapping[str, tuple[str, str]]) -> _KalshiPull:
    """Public GETs only. Nothing is written; the caller commits after B6."""
    pulled_at = _stamp()
    client = _counting_kalshi()
    blocked: dict[tuple[str, str], str] = {}
    annotated: list[dict[str, Any]] = []
    by_series: dict[str, tuple[Mapping[str, Any], ...]] = {}
    errors = 0
    for series, owner in owners.items():
        pulled = _pull_one_series(client, series, owner)
        if pulled.reason is not None:
            errors += 1
            blocked[owner] = pulled.reason
            continue
        by_series[series] = pulled.raw
        annotated.extend(pulled.annotated)
    copies = compare_kalshi_copies(*_split_copies(_client_pages(client)))
    return _KalshiPull(
        blocked,
        tuple(annotated),
        client.calls,
        errors,
        copies,
        status_counts(annotated),
        by_series,
        pulled_at,
    )


def _iem_modules() -> tuple[Any, Any, Any]:
    """AFOS URL + transport from the archive module; pacer from the venue module.

    ``iem_cli_fetch.fetch`` is not called. That function is the production CLI
    cache writer. Import is local so fixture tests do not load it.
    """
    for folder in ("archive", "venue"):
        folder_path = str(_REPO_ROOT / "scripts" / folder)
        if folder_path not in sys.path:
            sys.path.insert(0, folder_path)
    from iem_cli_fetch import (  # type: ignore[import-not-found]
        IemCliTransport,
        afos_cli_text_url,
    )
    from iem_mos_probe_transport import IemPacer  # type: ignore[import-not-found]

    return IemCliTransport, afos_cli_text_url, IemPacer


def _iem_runtime(city_count: int) -> tuple[Any, Any]:
    """Transport plus the AFOS URL builder. Pacer enforces one request per second."""
    from breezy.ingest.probe_transport import RequestBudget

    transport_cls, url_for, pacer_cls = _iem_modules()
    transport = transport_cls(
        budget=RequestBudget(limit=max(1, city_count * IEM_MAX_ATTEMPTS)),
        pacer=pacer_cls(clock=time.time_ns, min_interval_ns=IEM_MIN_INTERVAL_NS),
        user_agent=IEM_USER_AGENT,
        clock=time.time_ns,
    )
    return transport, url_for


def _stamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def retry_delay_s(attempt: int) -> float:
    """Backoff before retry ``attempt`` (1-based). At most one request per second."""
    if attempt < 1:
        raise ValueError("attempt must be positive")
    return IEM_BACKOFF_S * float(2 ** (attempt - 1))


def products_in_window(text: str, side: str, start: dt.date, end: dt.date) -> int:
    """Parsed CLI products whose climate date falls inside the frozen window."""
    index = cli_days_from_text(text, side)
    return sum(1 for day in index.days if start <= day <= end)


def _short_sides(text: str, sides: Sequence[str], start: dt.date, end: dt.date) -> tuple[str, ...]:
    return tuple(
        side for side in sides if products_in_window(text, side, start, end) < MIN_PRODUCTS_PER_SIDE
    )


def station_cap(city: str) -> int:
    """Per-side cap from prereg §3. The same cap applies to high and low."""
    named = _NAMED_CAPS.get(city)
    if named is not None:
        return named
    if city in _CAP_91_CITIES:
        return 91
    raise ValueError(f"no frozen per-side cap for {city}")


def paired_cap() -> int:
    """Sum of the per-side caps. 48 sides: each station cap counts twice."""
    cities = (*_CAP_91_CITIES, *_NAMED_CAPS)
    return sum(station_cap(city) for city in cities) * len(SIDES)


def status_counts(markets: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter(
        str(market.get("status") or "").strip().lower() or "missing" for market in markets
    )
    return dict(counter)


def _by_ticker(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    found: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        ticker = row.get("ticker")
        if isinstance(ticker, str) and ticker:
            found[ticker] = row
    return found


def compare_kalshi_copies(
    historical: Sequence[Mapping[str, Any]], live: Sequence[Mapping[str, Any]]
) -> KalshiCopyReport:
    """Overlap and expiration conflicts. Historical rows must be status finalized."""
    hist = _by_ticker(historical)
    live_map = _by_ticker(live)
    shared = set(hist) & set(live_map)
    conflicts = sum(
        1
        for key in shared
        if hist[key].get("expiration_value") != live_map[key].get("expiration_value")
    )
    not_final = sum(
        1 for row in historical if str(row.get("status") or "").strip().lower() != "finalized"
    )
    return KalshiCopyReport(
        overlap=len(shared),
        conflicts=conflicts,
        historical_rows=len(historical),
        historical_not_finalized=not_final,
        cutoff=HISTORICAL_CUTOFF,
    )


def _markets_of(payload: object) -> list[Mapping[str, Any]]:
    markets = payload.get("markets") if isinstance(payload, dict) else None
    if not isinstance(markets, list):
        return []
    return [market for market in markets if isinstance(market, dict)]


def _split_copies(
    pages: Sequence[tuple[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    historical: list[Mapping[str, Any]] = []
    live: list[Mapping[str, Any]] = []
    for path, payload in pages:
        target = historical if path.startswith("historical/") else live
        target.extend(_markets_of(payload))
    return historical, live


def _client_pages(client: _MarketClient) -> tuple[tuple[str, Any], ...]:
    pages = getattr(client, "pages", ())
    if not isinstance(pages, list):
        return ()
    return tuple(pages)


def _empty_copies() -> KalshiCopyReport:
    return KalshiCopyReport(0, 0, 0, 0, HISTORICAL_CUTOFF)


async def _one_attempt(
    transport: Any, url_for: Any, station: Station, start: dt.date, end: dt.date
) -> tuple[Any | None, str | None, bool]:
    """One GET. The bool is whether another attempt is allowed."""
    try:
        fetched = await transport.fetch_cli_text(url_for(station.cli_id, start, end))
    except _IEM_RETRY as exc:
        _note_fetch_error("iem", station.city, exc)
        return None, "iem_fetch_error", True
    except TransportError as exc:
        _note_fetch_error("iem", station.city, exc)
        return None, "iem_fetch_error", False
    if fetched.status_code == 200:
        return fetched, None, False
    print(f"iem {station.city} http_{fetched.status_code}", file=sys.stderr)
    return None, f"iem_http_{fetched.status_code}", True


async def _fetch_with_retry(
    transport: Any, url_for: Any, station: Station, start: dt.date, end: dt.date
) -> tuple[Any | None, str | None]:
    """429, 5xx, other non-200, and transport errors. Cap ``IEM_MAX_ATTEMPTS``."""
    last = "iem_fetch_error"
    for attempt in range(IEM_MAX_ATTEMPTS):
        if attempt:
            await asyncio.sleep(retry_delay_s(attempt))
        fetched, reason, retryable = await _one_attempt(transport, url_for, station, start, end)
        if fetched is not None:
            return fetched, None
        last = reason or last
        if not retryable:
            break
    return None, last


def _classify_body(
    city: str, sides: Sequence[str], start: dt.date, end: dt.date, text: str
) -> _FetchedCity:
    """Require one parsed in-window product per side. A short body is a fetch failure."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    short = _short_sides(text, sides, start, end)
    if not short:
        return _FetchedCity(None, text, digest)
    print(
        f"iem {city} iem_short_body sha256={digest} sides={','.join(short)}",
        file=sys.stderr,
    )
    return _FetchedCity("iem_short_body", None, digest)


async def _fetch_one_city(
    transport: Any,
    url_for: Any,
    station: Station,
    sides: Sequence[str],
    start: dt.date,
    end: dt.date,
) -> _FetchedCity:
    """Fetch one city into memory. No file is written here."""
    fetched, failure = await _fetch_with_retry(transport, url_for, station, start, end)
    if fetched is None:
        return _FetchedCity(failure or "iem_fetch_error", None, None)
    body = fetched.text if isinstance(fetched.text, str) else ""
    return _classify_body(station.city, sides, start, end, body)


def _cli_from_texts(
    texts: Mapping[str, str], stations: Sequence[Station], sides: Sequence[str]
) -> tuple[dict[tuple[str, str], CliTextIndex | str], dict[str, int]]:
    cli: dict[tuple[str, str], CliTextIndex | str] = {}
    overwrites: dict[str, int] = {}
    for station in stations:
        text = texts.get(station.city)
        indexed = _index_cli_by_side(text, sides) if text is not None else {}
        for side in sides:
            slot = indexed.get(side)
            if slot is None:
                cli[(station.city, side)] = "cli_not_loaded"
                continue
            cli[(station.city, side)] = slot
            overwrites[side_id(station.city, side)] = slot.overwrites
    return cli, overwrites


def _iem_transport_failure(
    stations: Sequence[Station], sides: Sequence[str], exc: BaseException, pulled_at: str
) -> _IemPull:
    _note_fetch_error("iem", "transport", exc)
    blocked = {(station.city, side): "iem_fetch_error" for station in stations for side in sides}
    cli = {(station.city, side): "iem_fetch_error" for station in stations for side in sides}
    return _IemPull(blocked, 0, len(stations), {}, {}, cli, {}, pulled_at)


async def _pull_iem_cities(
    transport: Any,
    url_for: Any,
    stations: Sequence[Station],
    sides: Sequence[str],
    start: dt.date,
    end: dt.date,
    pulled_at: str,
) -> _IemPull:
    blocked: dict[tuple[str, str], str] = {}
    texts: dict[str, str] = {}
    shas: dict[str, str] = {}
    errors = 0
    for station in stations:
        city = await _fetch_one_city(transport, url_for, station, sides, start, end)
        if city.sha256 is not None:
            shas[station.city] = city.sha256
        if city.reason is None and city.text is not None:
            texts[station.city] = city.text
            continue
        errors += 1
        for side in sides:
            blocked[(station.city, side)] = city.reason or "iem_fetch_error"
    cli, overwrites = _cli_from_texts(texts, stations, sides)
    for key, reason in blocked.items():
        cli[key] = reason
    return _IemPull(blocked, len(stations), errors, texts, shas, cli, overwrites, pulled_at)


async def _pull_iem_async(
    stations: Sequence[Station], sides: Sequence[str], start: dt.date, end: dt.date
) -> _IemPull:
    pulled_at = _stamp()
    try:
        transport, url_for = _iem_runtime(len(stations))
    except _PULL_ERRORS as exc:
        return _iem_transport_failure(stations, sides, exc, pulled_at)
    return await _pull_iem_cities(transport, url_for, stations, sides, start, end, pulled_at)


def _pull_iem(
    stations: Sequence[Station], sides: Sequence[str], start: dt.date, end: dt.date
) -> _IemPull:
    """At most one IEM request per second, inside ``IemPacer``, plus backoff."""
    return asyncio.run(_pull_iem_async(stations, sides, start, end))


def _undated_by_city(
    cli: Mapping[tuple[str, str], CliTextIndex | str],
    stations: Sequence[Station],
    sides: Sequence[str],
) -> dict[str, Mapping[str, int]]:
    """First loaded side per city. Both sides share one text, so do not double-count."""
    found: dict[str, Mapping[str, int]] = {}
    for station in stations:
        for side in sides:
            slot = cli.get((station.city, side))
            if isinstance(slot, CliTextIndex):
                found[station.city] = slot.undated_exclusions
                break
    return found


def _overwrite_map(cli: Mapping[tuple[str, str], CliTextIndex | str]) -> dict[str, int]:
    return {
        side_id(station, side): slot.overwrites
        for (station, side), slot in cli.items()
        if isinstance(slot, CliTextIndex)
    }


def _dry_body_sha(scratch: Path, stations: Sequence[Station]) -> dict[str, str]:
    found: dict[str, str] = {}
    for station in stations:
        path = scratch / "iem" / f"{station.city}.txt"
        if path.is_file():
            found[station.city] = file_sha256(path)
    return found


def _inputs_from_live(kalshi: _KalshiPull, iem: _IemPull) -> _Inputs:
    counts = RequestCounts("live", kalshi.calls, iem.fetches, kalshi.errors, iem.errors)
    scratch = _ScratchPending(kalshi.by_series, iem.texts)
    return _Inputs(
        kalshi.markets,
        kalshi.blocked,
        iem.cli,
        counts,
        kalshi.pulled_at,
        iem.pulled_at,
        iem.sha256,
        iem.overwrites,
        kalshi.copies,
        kalshi.statuses,
        scratch,
    )


def _inputs_from_dry(
    config: RunConfig, stations: Sequence[Station], owners: Mapping[str, tuple[str, str]]
) -> _Inputs:
    markets, blocked = _load_dry_markets(config.scratch_dir, owners)
    cli = _load_dry_cli(config.scratch_dir, stations, config.sides)
    return _Inputs(
        tuple(markets),
        blocked,
        cli,
        RequestCounts("dry-run", 0, 0, 0, 0),
        "dry-run",
        "dry-run",
        _dry_body_sha(config.scratch_dir, stations),
        _overwrite_map(cli),
        _empty_copies(),
        status_counts(markets),
        None,
    )


def _load_inputs(
    config: RunConfig, stations: Sequence[Station], owners: Mapping[str, tuple[str, str]]
) -> _Inputs:
    if config.dry_run:
        return _inputs_from_dry(config, stations, owners)
    return _inputs_from_live(
        _pull_kalshi(owners),
        _pull_iem(stations, config.sides, config.start, config.end),
    )


def _failure_table(loaded: _Inputs) -> dict[tuple[str, str], str]:
    """Kalshi blocks plus CLI error strings. Fixture gaps are included."""
    found = dict(loaded.blocked)
    for key, slot in loaded.cli.items():
        if not isinstance(slot, str):
            continue
        prior = found.get(key)
        found[key] = slot if prior is None else f"{prior}+{slot}"
    return found


def _abort_if_partial(loaded: _Inputs) -> None:
    """Live fetch failure raises before any scratch or evidence file is written."""
    if loaded.counts.mode == "dry-run":
        return
    failed = loaded.counts.kalshi_errors > 0 or loaded.counts.iem_errors > 0
    table = _failure_table(loaded)
    if not failed and not table:
        return
    print("side\treason", file=sys.stderr)
    for (station, side), reason in sorted(table.items()):
        print(f"{station}:{side}\t{reason}", file=sys.stderr)
    raise SystemExit(2)


def _commit_pending(scratch: Path, pending: _ScratchPending | None) -> None:
    if pending is None:
        return
    for series, markets in pending.markets_by_series.items():
        _write_markets(scratch / "kalshi" / f"{series}.json", markets)
    for city, text in pending.texts.items():
        path = scratch / "iem" / f"{city}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def assert_paired_fraction(paired: int, statuses: Mapping[str, int]) -> None:
    """Abort when paired days fall below half the frozen per-side cap (P7)."""
    cap = paired_cap()
    if paired >= PAIRED_CAP_FRACTION * cap:
        return
    rendered = ", ".join(f"{name}={count}" for name, count in sorted(statuses.items()))
    print(f"card_e: status counts: {rendered}", file=sys.stderr)
    print(
        f"card_e: paired {paired} is below {PAIRED_CAP_FRACTION:.0%} of per-side cap {cap}",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _score_rows(
    stations: Sequence[Station], config: RunConfig, loaded: _Inputs
) -> tuple[
    tuple[DayRow, ...],
    tuple[SideStat, ...],
    CardResult,
    tuple[HalfStat, ...],
    bool,
    KalshiSettled,
]:
    settled = parse_kalshi_settled(loaded.markets)
    rows = assign_matched_halves(
        build_rows(
            stations,
            config.sides,
            config.start,
            config.end,
            settled,
            loaded.cli,
            loaded.blocked,
        )
    )
    stats, flags = side_statistics(rows, P0, ALPHA_T2, SAME_SIGN_SHARE)
    card = evaluate_card(stats, flags, P0, ALPHA_T1, ALPHA_T2, KILL_UCB)
    halves, stable = half_statistics(rows)
    return rows, apply_side_outcomes(stats, card.kill), card, halves, stable, settled


def _assemble_report(
    config: RunConfig,
    stations: tuple[Station, ...],
    stations_sha: str,
    prereg_sha: str,
    loaded: _Inputs,
    scored: tuple[
        tuple[DayRow, ...],
        tuple[SideStat, ...],
        CardResult,
        tuple[HalfStat, ...],
        bool,
        KalshiSettled,
    ],
) -> Report:
    rows, stats, card, halves, stable, settled = scored
    return Report(
        config=config,
        stations_sha256=stations_sha,
        prereg_sha256=prereg_sha,
        stations=stations,
        kalshi_pull_ts=loaded.kalshi_pull_ts,
        iem_pull_ts=loaded.iem_pull_ts,
        rows=rows,
        side_stats=stats,
        card=card,
        halves=halves,
        stable=stable,
        buckets=tally_buckets(loaded.markets, loaded.cli, config.start, config.end),
        market_exclusions=settled.exclusion_counts,
        undated=_undated_by_city(loaded.cli, stations, config.sides),
        requests=loaded.counts,
        cli_body_sha256=loaded.cli_body_sha256,
        cli_overwrites=loaded.cli_overwrites,
        copies=loaded.copies,
        statuses=loaded.statuses,
    )


def _parquet_metadata(report: Report) -> dict[str, str]:
    return {
        "iem_pull_ts": report.iem_pull_ts,
        "kalshi_pull_ts": report.kalshi_pull_ts,
        "stations_sha256": report.stations_sha256,
        "prereg_sha256": report.prereg_sha256,
        "verdict": report.card.name,
    }


def execute(config: RunConfig) -> None:
    """One look. Prereg is checked before the overwrite guard and before any pull."""
    prereg_sha = assert_prereg(config.prereg, config.prereg_sha)
    assert_dry_run_not_evidence(config.out_dir, config.dry_run)
    assert_one_look(config.out_dir, config.force_reason)
    stations = load_stations(config.stations_file)
    loaded = _load_inputs(config, stations, _owners(stations, config.sides))
    _abort_if_partial(loaded)
    _commit_pending(config.scratch_dir, loaded.scratch)
    report = _assemble_report(
        config,
        stations,
        file_sha256(config.stations_file),
        prereg_sha,
        loaded,
        _score_rows(stations, config, loaded),
    )
    if loaded.counts.mode != "dry-run":
        assert_paired_fraction(len(_paired(report.rows)), loaded.statuses)
    emit_outputs(config.out_dir, report.rows, render_report(report), _parquet_metadata(report))


def parse_sides(raw: str) -> tuple[str, ...]:
    """``high``, ``low``, or ``high,low``. Duplicates are rejected."""
    parts = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    if not parts or any(part not in {"high", "low"} for part in parts):
        raise ValueError("sides must be high, low, or high,low")
    if len(parts) != len(set(parts)):
        raise ValueError("duplicate side")
    return parts


def _force_reason(raw: str) -> str:
    text = raw.strip()
    if not text or "\n" in raw or "\r" in raw:
        raise ValueError("--force-new-look needs one non-empty line")
    return text


_PREREG_PENDING_RULE: Final[str] = "while the sha256 line says PENDING"


def _prereg_still_pending(text: str) -> bool:
    """True when PENDING is an unfilled digest, not the sentence that names the rule."""
    return "PENDING" in text.replace(_PREREG_PENDING_RULE, "")


def assert_prereg(path: Path, expected: str) -> str:
    """Refuse a sha mismatch or a prereg whose sha line is still PENDING."""
    digest = file_sha256(path)
    problems: list[str] = []
    if digest != expected.strip().lower():
        problems.append("prereg sha256 mismatch")
    if _prereg_still_pending(path.read_text(encoding="utf-8")):
        problems.append("prereg still contains PENDING")
    if problems:
        print("card_e: " + "; ".join(problems), file=sys.stderr)
        raise SystemExit(2)
    return digest


def evidence_dir() -> Path:
    return (_REPO_ROOT / DEFAULT_OUT_DIR).resolve()


def assert_dry_run_not_evidence(out_dir: Path, dry_run: bool) -> None:
    """A dry-run must not consume the one evidence-directory look."""
    if dry_run and out_dir.resolve() == evidence_dir():
        print(
            "card_e: dry-run refused because --out-dir is the evidence directory",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _frozen_dates(start: object, end: object) -> tuple[dt.date, dt.date]:
    found_start = FROZEN_START if start is None else dt.date.fromisoformat(str(start))
    found_end = FROZEN_END if end is None else dt.date.fromisoformat(str(end))
    if (found_start, found_end) != (FROZEN_START, FROZEN_END):
        raise ValueError(
            f"window is frozen at {FROZEN_START.isoformat()}..{FROZEN_END.isoformat()}"
        )
    return found_start, found_end


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    start, end = _frozen_dates(args.start, args.end)
    force = None if args.force_new_look is None else _force_reason(str(args.force_new_look))
    return RunConfig(
        stations_file=Path(str(args.stations_file)),
        prereg=Path(str(args.prereg)),
        prereg_sha=str(args.prereg_sha).strip().lower(),
        start=start,
        end=end,
        sides=SIDES,
        scratch_dir=Path(str(args.scratch_dir)),
        out_dir=Path(str(args.out_dir)),
        dry_run=bool(args.dry_run),
        force_reason=force,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Card E: CLI versus Kalshi expiration value")
    parser.add_argument("--stations-file", type=Path, required=True)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--prereg-sha", required=True)
    parser.add_argument("--start", default=None, help="optional; must be the frozen start")
    parser.add_argument("--end", default=None, help="optional; must be the frozen end")
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="fixtures only; no network")
    parser.add_argument("--force-new-look", default=None, help="reason required to overwrite")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(None if argv is None else list(argv))
    try:
        execute(_config_from_args(args))
    except (ValueError, TypeError) as exc:
        print(f"card_e: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
