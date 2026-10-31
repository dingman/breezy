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
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scipy.stats import beta, binom

from breezy.ingest.http import TransportError
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
# One series or city must not abort the others. These are the errors the
# public clients raise (HTTP/URL/timeout, JSON, our own parsers, IEM transport).
_PULL_ERRORS: Final[tuple[type[BaseException], ...]] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    TransportError,
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
    """Latest product per climate date. Later text wins; an amendment stays out."""

    days: Mapping[dt.date, CliLabelParse]
    undated_exclusions: Mapping[str, int]


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
    killed: bool
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


def cli_days_from_text(text: str, side: str) -> CliTextIndex:
    """Index one station's raw text. The later product for a date replaces it."""
    chosen: dict[dt.date, CliLabelParse] = {}
    undated: Counter[str] = Counter()
    products = split_iem_products(text)
    if not products and text.strip():
        products = (text,)
    for product in products:
        label = parse_cli_label(product, side)
        if label.climate_date is None:
            undated[label.exclusion or "unparsed"] += 1
            continue
        chosen[label.climate_date] = label
    return CliTextIndex(days=chosen, undated_exclusions=dict(undated))


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
    exclusion = _reason_for_day(series, block, slot, kalshi_day, day)
    cli_value = _cli_value(slot, day)
    kalshi_value = None if kalshi_day is None else kalshi_day.expiration_f
    if exclusion is not None:
        return _excluded_row(station.city, side, day, half, kalshi_value, cli_value, exclusion)
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
    )


def _cli_value(slot: CliTextIndex | str | None, day: dt.date) -> int | None:
    if not isinstance(slot, CliTextIndex):
        return None
    label = slot.days.get(day)
    if label is None or label.exclusion is not None:
        return None
    return label.value_f


def _reason_for_day(
    series: str | None,
    block: str | None,
    slot: CliTextIndex | str | None,
    kalshi_day: KalshiDay | None,
    day: dt.date,
) -> str | None:
    """Why this day is out of the denominator. None means both labels are usable."""
    if series is None:
        return "missing_series"
    if block is not None:
        return block
    if isinstance(slot, str):
        return slot
    if not isinstance(slot, CliTextIndex):
        return "cli_not_loaded"
    return _label_reason(slot.days.get(day), kalshi_day)


def _label_reason(label: CliLabelParse | None, kalshi_day: KalshiDay | None) -> str | None:
    if kalshi_day is not None and kalshi_day.exclusion is not None:
        return kalshi_day.exclusion
    if label is not None and label.exclusion is not None:
        return label.exclusion
    if kalshi_day is None and (label is None or label.value_f is None):
        return "missing_both"
    if kalshi_day is None:
        return "missing_kalshi"
    if label is None or label.value_f is None:
        return "missing_cli"
    return None


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


def _side_outcome(flagged: bool, sign_ok: bool, killed: bool) -> VerdictWord:
    """PASS only for a Holm flag that also meets the sign rule. Not via pooled T1."""
    if flagged and sign_ok:
        return "PASS"
    if killed:
        return "KILL"
    return "INCONCLUSIVE"


def _one_side(
    station: str,
    side: str,
    rows: Sequence[DayRow],
    flagged: frozenset[str],
    p0: float,
    share: float,
    kill_ucb: float,
) -> SideStat:
    k, n = _mismatch_counts(rows)
    deltas = _deltas(rows)
    positive = sum(1 for delta in deltas if delta > 0)
    negative = sum(1 for delta in deltas if delta < 0)
    sign_ok = same_sign_rule(deltas, share)
    killed = kill_rule(k, n, UCB_LEVEL, kill_ucb)
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
        killed=killed,
        outcome=_side_outcome(is_flagged, sign_ok, killed),
        day_exclusions=_day_exclusion_counts(rows),
    )


def side_statistics(
    rows: Sequence[DayRow],
    p0: float,
    alpha: float,
    share: float,
    kill_ucb: float,
) -> tuple[tuple[SideStat, ...], tuple[str, ...]]:
    """Every station-side in ``rows``, including n = 0. Holm family is that set."""
    order: list[tuple[str, str]] = []
    grouped: dict[tuple[str, str], list[DayRow]] = defaultdict(list)
    for row in rows:
        key = (row.station, row.side)
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)
    counts = {
        side_id(station, side): _mismatch_counts(grouped[(station, side)])
        for station, side in order
    }
    flags = t2_holm(counts, p0, alpha)
    flagged = frozenset(flags)
    stats = tuple(
        _one_side(station, side, grouped[(station, side)], flagged, p0, share, kill_ucb)
        for station, side in order
    )
    return stats, flags


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
    """One calendar half. ``sign`` is the sign of the summed paired deltas."""

    half: int
    start: dt.date
    end: dt.date
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


def _one_half(rows: Sequence[DayRow], half: int, bounds: tuple[dt.date, dt.date]) -> HalfStat:
    paired = [row for row in rows if row.half == half and row.delta is not None]
    deltas = [row.delta for row in paired if row.delta is not None]
    total = sum(deltas)
    n = len(deltas)
    mismatches = sum(1 for row in paired if row.outcome == "mismatch")
    mean = None if n == 0 else total / n
    return HalfStat(half, bounds[0], bounds[1], n, mismatches, mean, _half_sign(total, n))


def half_statistics(
    rows: Sequence[DayRow], start: dt.date, end: dt.date
) -> tuple[HalfStat, HalfStat, bool]:
    """Stability when both halves are non-zero and the same sign. Not a gate."""
    bounds = half_bounds(start, end)
    first = _one_half(rows, 1, bounds[0])
    second = _one_half(rows, 2, bounds[1])
    stable = first.sign == second.sign and first.sign in {"positive", "negative"}
    return first, second, stable


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
    start: dt.date
    end: dt.date
    sides: tuple[str, ...]
    cli_pull_ts: str
    scratch_dir: Path
    out_dir: Path
    dry_run: bool
    p0: float
    alpha_t1: float
    alpha_t2: float
    same_sign_share: float
    kill_ucb: float
    force_reason: str | None


@dataclass(frozen=True, slots=True)
class Report:
    """Everything the markdown and parquet are allowed to say."""

    config: RunConfig
    stations_sha256: str
    stations: tuple[Station, ...]
    kalshi_pull_ts: str
    rows: tuple[DayRow, ...]
    side_stats: tuple[SideStat, ...]
    card: CardResult
    halves: tuple[HalfStat, HalfStat]
    stable: bool
    buckets: BucketTally
    market_exclusions: Mapping[tuple[str, str], Mapping[str, int]]
    undated: Mapping[str, Mapping[str, int]]
    requests: RequestCounts


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
        f"- stations file: `{cfg.stations_file}`",
        f"- stations sha256: `{report.stations_sha256}`",
        f"- cli_pull_ts: `{cfg.cli_pull_ts}`",
        f"- kalshi_pull_ts: `{report.kalshi_pull_ts}`",
        f"- climate dates: {cfg.start.isoformat()} .. {cfg.end.isoformat()}",
        f"- sides: {', '.join(cfg.sides)}",
        f"- p0: {cfg.p0}",
        f"- alpha_t1: {cfg.alpha_t1}",
        f"- alpha_t2: {cfg.alpha_t2}",
        f"- same_sign_share: {cfg.same_sign_share}",
        f"- kill_ucb: {cfg.kill_ucb}",
        f"- ucb_level: {UCB_LEVEL} (fixed, not a flag)",
        f"- force-new-look: {force}",
        (
            f"- planning N={PLANNING_N} pooled threshold k={card.planning_threshold} "
            f"at p0={cfg.p0}, alpha={cfg.alpha_t1}"
        ),
        (
            f"- Bonferroni first step over {REFERENCE_FAMILY} sides "
            f"at alpha {cfg.alpha_t2}: {reference}"
        ),
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
        (half.half, half.start, half.end, half.n, half.k, _fmt(half.mean_delta), half.sign)
        for half in report.halves
    ]
    headers = ("half", "start", "end", "n", "k", "mean_delta", "sign")
    stable = "yes" if report.stable else "no"
    return [
        "## Half-split stability",
        "",
        "Calendar halves, not a sample median. Not a gate.",
        "",
        *_md_table(headers, body),
        f"Stable (both halves non-zero and the same sign): {stable}.",
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


def _section_exclusions(report: Report) -> list[str]:
    day_counts: Counter[str] = Counter(row.exclusion for row in report.rows if row.exclusion)
    day_body = sorted(day_counts.items()) or [("none", 0)]
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
    return [
        "## Day-row exclusions",
        "",
        *_md_table(("reason", "n"), day_body),
        "## Kalshi market-row exclusions",
        "",
        *_md_table(("side", "reason", "n"), market_body),
        "## CLI undated products",
        "",
        "Counted once per city, not once per side.",
        "",
        *_md_table(("city", "reason", "n"), undated_body),
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


def write_parquet(rows: Sequence[DayRow], path: Path) -> None:
    """Direct write of the per (station, side, date) rows. No temporary sibling."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "station": [row.station for row in rows],
            "side": [row.side for row in rows],
            "climate_date": pa.array([row.climate_date for row in rows], type=pa.date32()),
            "kalshi_f": pa.array([row.kalshi_f for row in rows], type=pa.int32()),
            "cli_f": pa.array([row.cli_f for row in rows], type=pa.int32()),
            "delta": pa.array([row.delta for row in rows], type=pa.int32()),
            "outcome": [row.outcome for row in rows],
            "exclusion": [row.exclusion for row in rows],
            "half": pa.array([row.half for row in rows], type=pa.int8()),
        }
    )
    pq.write_table(table, path)


def emit_outputs(out_dir: Path, rows: Sequence[DayRow], markdown: str) -> None:
    """Write the parquet and the markdown. Nowhere else."""
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown_path, parquet_path = output_paths(out_dir)
    write_parquet(rows, parquet_path)
    markdown_path.write_text(markdown, encoding="utf-8")


def _note_fetch_error(kind: str, label: str, exc: BaseException) -> None:
    """Type name only. Exception text can carry a URL; credentials are never printed."""
    print(f"{kind} {label} {type(exc).__name__}", file=sys.stderr)


def _write_markets(path: Path, markets: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"markets": [dict(market) for market in markets]}
    path.write_text(json.dumps(payload), encoding="utf-8")


class _CountedKalshi:
    """Counts ``get_json``. ``list_series_markets`` stays the unmodified method."""

    def __init__(self, inner: Any) -> None:
        self.calls = 0
        self._inner = inner
        self._original = inner.get_json
        inner.get_json = self._counted

    def _counted(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        self.calls += 1
        return self._original(path, params)

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


def _pull_kalshi(
    scratch: Path, owners: Mapping[str, tuple[str, str]]
) -> tuple[dict[tuple[str, str], str], int, int]:
    """Public GETs only, via ``list_series_markets``. Failures stay per series."""
    client = _counting_kalshi()
    blocked: dict[tuple[str, str], str] = {}
    errors = 0
    for series, owner in owners.items():
        try:
            markets = client.list_series_markets(series)
        except _PULL_ERRORS as exc:
            errors += 1
            _note_fetch_error("kalshi", series, exc)
            blocked[owner] = "kalshi_fetch_error"
            continue
        _write_markets(scratch / "kalshi" / f"{series}.json", markets)
    return blocked, client.calls, errors


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
        budget=RequestBudget(limit=max(1, city_count * 5)),
        pacer=pacer_cls(clock=time.time_ns, min_interval_ns=IEM_MIN_INTERVAL_NS),
        user_agent=IEM_USER_AGENT,
        clock=time.time_ns,
    )
    return transport, url_for


async def _fetch_one_city(
    transport: Any,
    url_for: Any,
    scratch: Path,
    station: Station,
    start: dt.date,
    end: dt.date,
) -> str | None:
    """Write the raw body on any HTTP answer. Return an exclusion, or None."""
    try:
        fetched = await transport.fetch_cli_text(url_for(station.cli_id, start, end))
    except _PULL_ERRORS as exc:
        _note_fetch_error("iem", station.city, exc)
        return "iem_fetch_error"
    path = scratch / "iem" / f"{station.city}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fetched.text, encoding="utf-8")
    if fetched.status_code != 200:
        print(f"iem {station.city} http_{fetched.status_code}", file=sys.stderr)
        return f"iem_http_{fetched.status_code}"
    return None


async def _pull_iem_async(
    scratch: Path, stations: Sequence[Station], sides: Sequence[str], start: dt.date, end: dt.date
) -> tuple[dict[tuple[str, str], str], int, int]:
    blocked: dict[tuple[str, str], str] = {}
    try:
        transport, url_for = _iem_runtime(len(stations))
    except _PULL_ERRORS as exc:
        _note_fetch_error("iem", "transport", exc)
        for station in stations:
            for side in sides:
                blocked[(station.city, side)] = "iem_fetch_error"
        return blocked, 0, len(stations)
    errors = 0
    fetches = 0
    for station in stations:
        fetches += 1
        reason = await _fetch_one_city(transport, url_for, scratch, station, start, end)
        if reason is None:
            continue
        errors += 1
        for side in sides:
            blocked[(station.city, side)] = reason
    return blocked, fetches, errors


def _pull_iem(
    scratch: Path, stations: Sequence[Station], sides: Sequence[str], start: dt.date, end: dt.date
) -> tuple[dict[tuple[str, str], str], int, int]:
    """At most one IEM request per second, inside ``IemPacer``."""
    return asyncio.run(_pull_iem_async(scratch, stations, sides, start, end))


_Loaded = tuple[
    list[dict[str, Any]],
    dict[tuple[str, str], str],
    dict[tuple[str, str], CliTextIndex | str],
    RequestCounts,
    str,
]


def _pull_live(
    config: RunConfig, stations: Sequence[Station], owners: Mapping[str, tuple[str, str]]
) -> _Loaded:
    """Read-only pulls. Raw bodies land only under ``config.scratch_dir``."""
    kalshi_pull_ts = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    kalshi_blocked, kalshi_calls, kalshi_errors = _pull_kalshi(config.scratch_dir, owners)
    cli_blocked, iem_fetches, iem_errors = _pull_iem(
        config.scratch_dir, stations, config.sides, config.start, config.end
    )
    markets, blocked = _load_dry_markets(config.scratch_dir, owners, kalshi_blocked)
    cli = _load_dry_cli(config.scratch_dir, stations, config.sides, cli_blocked)
    counts = RequestCounts("live", kalshi_calls, iem_fetches, kalshi_errors, iem_errors)
    return markets, blocked, cli, counts, kalshi_pull_ts


def _load_inputs(
    config: RunConfig, stations: Sequence[Station], owners: Mapping[str, tuple[str, str]]
) -> _Loaded:
    if config.dry_run:
        markets, blocked = _load_dry_markets(config.scratch_dir, owners)
        cli = _load_dry_cli(config.scratch_dir, stations, config.sides)
        return markets, blocked, cli, RequestCounts("dry-run", 0, 0, 0, 0), "dry-run"
    return _pull_live(config, stations, owners)


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


def execute(config: RunConfig) -> None:
    """One look. The overwrite check happens before any read of the venues."""
    assert_one_look(config.out_dir, config.force_reason)
    stations = load_stations(config.stations_file)
    digest = file_sha256(config.stations_file)
    owners = _owners(stations, config.sides)
    markets, blocked, cli, counts, kalshi_pull_ts = _load_inputs(config, stations, owners)
    settled = parse_kalshi_settled(markets)
    rows = build_rows(stations, config.sides, config.start, config.end, settled, cli, blocked)
    stats, flags = side_statistics(
        rows, config.p0, config.alpha_t2, config.same_sign_share, config.kill_ucb
    )
    card = evaluate_card(stats, flags, config.p0, config.alpha_t1, config.alpha_t2, config.kill_ucb)
    first, second, stable = half_statistics(rows, config.start, config.end)
    report = Report(
        config=config,
        stations_sha256=digest,
        stations=stations,
        kalshi_pull_ts=kalshi_pull_ts,
        rows=rows,
        side_stats=stats,
        card=card,
        halves=(first, second),
        stable=stable,
        buckets=tally_buckets(markets, cli, config.start, config.end),
        market_exclusions=settled.exclusion_counts,
        undated=_undated_by_city(cli, stations, config.sides),
        requests=counts,
    )
    emit_outputs(config.out_dir, rows, render_report(report))


def parse_sides(raw: str) -> tuple[str, ...]:
    """``high``, ``low``, or ``high,low``. Duplicates are rejected."""
    parts = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    if not parts or any(part not in {"high", "low"} for part in parts):
        raise ValueError("sides must be high, low, or high,low")
    if len(parts) != len(set(parts)):
        raise ValueError("duplicate side")
    return parts


def _parse_timestamp(raw: str) -> str:
    text = raw.strip()
    if not text or "\n" in raw or "\r" in raw:
        raise ValueError("cli-pull-ts must be one ISO timestamp")
    dt.datetime.fromisoformat(text)
    return text


def _force_reason(raw: str) -> str:
    text = raw.strip()
    if not text or "\n" in raw or "\r" in raw:
        raise ValueError("--force-new-look needs one non-empty line")
    return text


def _open_unit(name: str, raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(raw)
    if not math.isfinite(number) or not 0 < number < 1:
        raise ValueError(f"{name} must be in (0, 1)")
    return number


def _closed_unit(name: str, raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(raw)
    if not math.isfinite(number) or not 0 < number <= 1:
        raise ValueError(f"{name} must be in (0, 1]")
    return number


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    start = dt.date.fromisoformat(str(args.start))
    end = dt.date.fromisoformat(str(args.end))
    if end < start:
        raise ValueError("end before start")
    force = None if args.force_new_look is None else _force_reason(str(args.force_new_look))
    return RunConfig(
        stations_file=Path(str(args.stations_file)),
        start=start,
        end=end,
        sides=parse_sides(str(args.sides)),
        cli_pull_ts=_parse_timestamp(str(args.cli_pull_ts)),
        scratch_dir=Path(str(args.scratch_dir)),
        out_dir=Path(str(args.out_dir)),
        dry_run=bool(args.dry_run),
        p0=_open_unit("p0", args.p0),
        alpha_t1=_open_unit("alpha-t1", args.alpha_t1),
        alpha_t2=_open_unit("alpha-t2", args.alpha_t2),
        same_sign_share=_closed_unit("same-sign-share", args.same_sign_share),
        kill_ucb=_open_unit("kill-ucb", args.kill_ucb),
        force_reason=force,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Card E: CLI versus Kalshi expiration value")
    parser.add_argument("--stations-file", type=Path, required=True)
    parser.add_argument("--start", required=True, help="climate date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="climate date YYYY-MM-DD")
    parser.add_argument("--sides", required=True, help="high, low, or high,low")
    parser.add_argument("--cli-pull-ts", required=True, help="frozen ISO timestamp")
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path(DEFAULT_OUT_DIR))
    parser.add_argument("--dry-run", action="store_true", help="fixtures only; no network")
    parser.add_argument("--p0", type=float, default=0.01)
    parser.add_argument("--alpha-t1", type=float, default=0.025)
    parser.add_argument("--alpha-t2", type=float, default=0.025)
    parser.add_argument("--same-sign-share", type=float, default=0.80)
    parser.add_argument("--kill-ucb", type=float, default=0.02)
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
