"""Frozen GAP-6 S0 SEARCH screen; unauthenticated Kalshi reads only.

Conservative choices: unrecognized identity/schema is fatal, a transient miss
leaves its whole series unsealed for resume, and inadequate/discordant pre cells
are INCONCLUSIVE (next action CONTINUE). Post cells never decide. Reference
labels denote bucket ENDs except the opening reference, whose end is ceil(open)
+ one hour. Whole-range payloads are indexed by exact end, never carried forward.
The earliest available settlement/close/expiration timestamp bounds references.
F-19 checks the first returned bucket against the actual open, without rounding.
Publication uses a temporary file and an atomic no-replace hard-link, followed
by removal of the temporary name: unlike ordinary rename this cannot clobber
another writer. No partial per-series file or separate digest is published.
An exclusive look-directory reservation precedes outcome access; a failed
calculation retains the reservation, conservatively refusing another look.

P-0 provenance: K1's test module explicitly identifies its historical/live
fixtures as captured venue responses (commit e97f3929). The separate LAX market
fixture is a full response committed at 780a46b2, without an explicit provenance
header; its capture provenance is UNVERIFIED. New s0_cases.json is hand-written
synthetic evidence only. No fixture independently establishes boundary-tick
inclusion. No network probe was made by S2; resolve that provenance before S3a.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from os import link, statvfs
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener, install_opener

from breezy.analysis.stats.scoring_core import bootstrap_cluster_draws, percentile_interval

if TYPE_CHECKING:
    from scripts.analysis.k1_cheap_open_settlement import (
        break_even_probability,
        is_pre_climate_day,
        summarize_stratum,
        wilson_interval,
    )
    from scripts.analysis.k1_kalshi_prior import (
        API_BASE,
        HISTORICAL_CUTOFF,
        KalshiHttp,
        climate_day_from_ticker,
    )
else:
    from k1_cheap_open_settlement import (
        break_even_probability,
        is_pre_climate_day,
        summarize_stratum,
        wilson_interval,
    )
    from k1_kalshi_prior import API_BASE, HISTORICAL_CUTOFF, KalshiHttp, climate_day_from_ticker

__all__ = ["break_even_probability", "summarize_stratum"]

ROOT = Path(__file__).resolve().parents[2]
FROZEN_PREREG = ROOT / "docs/plans/backlog/GAPS_2026-11-01/gap6_sample_and_size/prereg_r1.md"
FROZEN_PREREG_SHA = "2073860f93d78225928bc44deb3f86c2bdeecad8839e8b1da57aa478a0fdd18f"
RAW_ROOT = Path("/mnt/storage/breezy/kalshi_depth/s0_raw/")
EVIDENCE_ROOT = ROOT / "docs/evidence/kalshi_depth"
LST_TABLE = {
    "KXHIGHTATL": ("KATL", -5),
    "KXLOWTATL": ("KATL", -5),
    "KXHIGHAUS": ("KAUS", -6),
    "KXLOWTAUS": ("KAUS", -6),
    "KXHIGHTBOS": ("KBOS", -5),
    "KXLOWTBOS": ("KBOS", -5),
    "KXHIGHTDC": ("KDCA", -5),
    "KXLOWTDC": ("KDCA", -5),
    "KXHIGHDEN": ("KDEN", -7),
    "KXLOWTDEN": ("KDEN", -7),
    "KXHIGHTDAL": ("KDFW", -6),
    "KXLOWTDAL": ("KDFW", -6),
    "KXHIGHTEWR": ("KEWR", -5),
    "KXLOWTEWR": ("KEWR", -5),
    "KXHIGHTHOU": ("KHOU", -6),
    "KXLOWTHOU": ("KHOU", -6),
    "KXHIGHTLV": ("KLAS", -8),
    "KXLOWTLV": ("KLAS", -8),
    "KXHIGHLAX": ("KLAX", -8),
    "KXLOWTLAX": ("KLAX", -8),
    "KXHIGHCHI": ("KMDW", -6),
    "KXLOWTCHI": ("KMDW", -6),
    "KXHIGHMIA": ("KMIA", -5),
    "KXLOWTMIA": ("KMIA", -5),
    "KXHIGHTMIN": ("KMSP", -6),
    "KXLOWTMIN": ("KMSP", -6),
    "KXHIGHTNOLA": ("KMSY", -6),
    "KXLOWTNOLA": ("KMSY", -6),
    "KXHIGHNY": ("KNYC", -5),
    "KXLOWTNYC": ("KNYC", -5),
    "KXHIGHTOKC": ("KOKC", -6),
    "KXLOWTOKC": ("KOKC", -6),
    "KXHIGHPHIL": ("KPHL", -5),
    "KXLOWTPHIL": ("KPHL", -5),
    "KXHIGHTPHX": ("KPHX", -7),
    "KXLOWTPHX": ("KPHX", -7),
    "KXHIGHTSAN": ("KSAN", -8),
    "KXLOWTSAN": ("KSAN", -8),
    "KXHIGHTSATX": ("KSAT", -6),
    "KXLOWTSATX": ("KSAT", -6),
    "KXHIGHTSDF": ("KSDF", -5),
    "KXLOWTSDF": ("KSDF", -5),
    "KXHIGHTSEA": ("KSEA", -8),
    "KXLOWTSEA": ("KSEA", -8),
    "KXHIGHTSFO": ("KSFO", -8),
    "KXLOWTSFO": ("KSFO", -8),
    "KXHIGHTTTN": ("KTTN", -5),
    "KXLOWTTTN": ("KTTN", -5),
}
_TOKEN = r"[A-Z0-9][A-Z0-9._-]{0,63}"
ALLOWED_TEMPLATES = {
    "historical_markets": re.compile(r"historical/markets"),
    "live_markets": re.compile(r"markets"),
    "historical_candles": re.compile(rf"historical/markets/{_TOKEN}/candlesticks"),
    "live_candles": re.compile(rf"series/{_TOKEN}/markets/{_TOKEN}/candlesticks"),
}
_PATHS = {
    "historical_markets": "historical/markets",
    "live_markets": "markets",
    "historical_candles": "historical/markets/{ticker}/candlesticks",
    "live_candles": "series/{series}/markets/{ticker}/candlesticks",
}
CELLS = tuple(f"{side}_{stratum}" for side in ("HIGH", "LOW") for stratum in ("pre", "post"))


class PoisonedInput(ValueError):
    """Input cannot form a permitted resource."""


class KalshiRefused(RuntimeError):
    """Sanitized public-reader refusal."""


class RedirectRefused(KalshiRefused):
    """Redirects cannot leave the pinned endpoint."""


class Absent(KalshiRefused):
    """Deterministic absence; not a transient miss."""


class Miss(KalshiRefused):
    """Exhausted bounded transport retries."""


class Incomplete(RuntimeError):
    """Unsealed run; resumable without spending the look."""


class SealError(ValueError):
    """Frozen inputs failed verification."""


class SemanticsHalt(ValueError):
    """F-19 requires peer review before proceeding."""


class UnknownSeries(KeyError):
    """No default station or offset is permissible."""


class JsonGetter(Protocol):
    _base_url: str

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any: ...


@dataclass
class MissStreak:
    limit: int = 5
    count: int = 0

    def observe(self, outcome: object) -> None:
        self.count = self.count + 1 if isinstance(outcome, Miss) else 0
        if self.count >= self.limit:
            raise Incomplete("INCOMPLETE: consecutive misses")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
    ) -> None:
        return None


class HostPinnedKalshi:
    def __init__(self, getter: JsonGetter) -> None:
        if getter._base_url != API_BASE:
            raise PoisonedInput("base host")
        self._getter = getter
        self.streak = MissStreak()

    @classmethod
    def default(cls) -> HostPinnedKalshi:
        return cls(KalshiHttp(base_url=API_BASE, min_interval_s=0.25, max_retries=3))

    def get(self, template_id: str, *, parts: Mapping[str, str], params: Mapping[str, Any]) -> Any:
        if template_id not in ALLOWED_TEMPLATES:
            raise PoisonedInput("template")
        required = (
            {"ticker", "series"}
            if template_id == "live_candles"
            else ({"ticker"} if template_id == "historical_candles" else set())
        )
        if set(parts) != required or any(
            not isinstance(v, str) or not re.fullmatch(_TOKEN, v) for v in parts.values()
        ):
            raise PoisonedInput("resource identity")
        clean = dict(params)
        for key, value in clean.items():
            if key == "cursor":
                valid = isinstance(value, str) and bool(
                    re.fullmatch(r"[A-Za-z0-9+/=_-]{1,1024}", value)
                )
            elif key == "series_ticker":
                valid = isinstance(value, str) and bool(re.fullmatch(_TOKEN, value))
            elif key in {"limit", "start_ts", "end_ts", "period_interval"}:
                bounds = {
                    "limit": (1, 1000),
                    "start_ts": (0, 4102444800),
                    "end_ts": (0, 4102444800),
                    "period_interval": (60, 60),
                }
                low, high = bounds[key]
                valid = type(value) is int and low <= value <= high
            else:
                valid = False
            if not valid:
                raise PoisonedInput("query parameter")
        if "start_ts" in clean and "end_ts" in clean and clean["start_ts"] > clean["end_ts"]:
            raise PoisonedInput("time range")
        path = _PATHS[template_id].format(**parts)
        if not ALLOWED_TEMPLATES[template_id].fullmatch(path) or self._getter._base_url != API_BASE:
            raise PoisonedInput("resource path")
        code: int | None = None
        kind: type[KalshiRefused] = KalshiRefused
        label = "RuntimeError"
        try:
            result = self._getter.get_json(path, clean)
        except RuntimeError as exc:
            code = exc.__cause__.code if isinstance(exc.__cause__, HTTPError) else None
        except HTTPError as exc:
            code = exc.code
            kind = (
                Absent
                if code == 404
                else Miss
                if code == 429 or 500 <= code < 600
                else (RedirectRefused if 300 <= code < 400 else KalshiRefused)
            )
        except (URLError, TimeoutError):
            kind, label = Miss, "transport"
        except Exception as exc:  # noqa: BLE001 - discard transport exception text and chains
            label = type(exc).__name__
        else:
            self.streak.observe(result)
            return result
        # Leave the handler before raising: __context__ must contain no URL.
        error = kind(f"HTTP {code}" if code is not None else label)
        self.streak.observe(error)
        raise error


def station_offset(series: str) -> tuple[str, int]:
    try:
        return LST_TABLE[series]
    except KeyError:
        raise UnknownSeries(series) from None


def local_time(ts: int, series: str) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, dt.timezone(dt.timedelta(hours=station_offset(series)[1])))


def timestamp(value: str) -> int:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise PoisonedInput("timezone required")
    return int(parsed.timestamp())


def climate_day(row: Mapping[str, Any]) -> dt.date:
    day = row.get("climate_day")
    if day is not None:
        return dt.date.fromisoformat(day)
    parsed = climate_day_from_ticker(str(row["ticker"]))
    if parsed is None:
        raise PoisonedInput("climate identity")
    return parsed


def in_window(row: Mapping[str, Any]) -> bool:
    return dt.date(2025, 7, 1) <= climate_day(row) < dt.date(2026, 7, 1)


def row_exclusion(row: Mapping[str, Any]) -> str | None:
    status = str(row.get("status") or "").strip().lower()
    result = str(row.get("result") or "").strip().lower()
    if status in {"cancelled", "canceled"} or result in {"cancelled", "canceled"}:
        return "cancelled"
    if result in {"void", "voided"}:
        return "void"
    if status != "finalized":
        return "not_finalized"
    return None


def reference_hours(row: Mapping[str, Any]) -> list[tuple[str, int]]:
    series = row["series_ticker"]
    offset = station_offset(series)[1]
    day = climate_day(row)
    midnight = dt.datetime.combine(day, dt.time(), dt.timezone(dt.timedelta(hours=offset)))
    base = int(midnight.timestamp())
    timestamp(row["open_time"])
    opened = dt.datetime.fromisoformat(row["open_time"])
    whole = opened.replace(minute=0, second=0, microsecond=0)
    if opened != whole:
        whole += dt.timedelta(hours=1)
    opening_end = int(whole.timestamp()) + 3600
    refs = []
    if local_time(opening_end - 3600, series).date() == day - dt.timedelta(
        days=1
    ) and is_pre_climate_day(
        opening_end * 1_000_000_000, climate_day=day, std_utc_offset_hours=offset
    ):
        refs.append(("pre", opening_end))
    high = series.startswith("KXHIGH")
    refs.extend(
        [("pre", base + (10 if high else -6) * 3600), ("post", base + (17 if high else 10) * 3600)]
    )
    return list(dict.fromkeys(refs))


def assert_reference(
    ref_end: int, settlement: int, day: dt.date, series: str, side: str, stratum: str
) -> None:
    midnight = dt.datetime.combine(day, dt.time(), local_time(ref_end, series).tzinfo)
    window = int(midnight.timestamp()) + (10 * 3600 if side == "HIGH" else 0)
    assert ref_end < settlement, "reference reaches settlement"
    assert ref_end <= window if stratum == "pre" else ref_end > window, (
        "reference crosses observation window"
    )


def no_ask(candle: Mapping[str, Any]) -> Decimal | None:
    node = candle.get("yes_bid")
    if not isinstance(node, Mapping):
        return None
    for key in ("close", "close_dollars"):
        raw = node.get(key)
        if raw is None:
            continue
        try:
            bid = Decimal(str(raw))
        except InvalidOperation:
            return None
        return Decimal(1) - bid if bid.is_finite() and Decimal(0) < bid < Decimal(1) else None
    return None


def exact_candle(candles: Sequence[Mapping[str, Any]], ref_end: int) -> Mapping[str, Any] | None:
    exact = [c for c in candles if c["end_period_ts"] == ref_end]
    assert len(exact) <= 1, "duplicate candle end"
    if exact:
        return exact[0]
    assert all(c["end_period_ts"] <= ref_end for c in candles), "future candle refused"
    return None


_AUDIT_KEYS = (
    "series_ticker",
    "ticker",
    "climate_day",
    "status",
    "open_time",
    "settlement_ts",
    "candlesticks",
    "candle_status",
)


def audit_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in _AUDIT_KEYS if key in row}


@dataclass(frozen=True)
class Observation:
    side: str
    stratum: str
    station: str
    day: str
    excess: Decimal
    no_win: bool


def selections(row: Mapping[str, Any], counts: Counter[str]) -> list[tuple[str, Decimal]]:
    series = row["series_ticker"]
    side = "HIGH" if series.startswith("KXHIGH") else "LOW"
    candles = row["candlesticks"]
    if candles and min(c["end_period_ts"] for c in candles) != timestamp(row["open_time"]) + 3600:
        raise SemanticsHalt("HALT: F-19 first candle differs from open + 3600")
    selected = []
    for stratum, ref in reference_hours(row):
        cell = f"{side}_{stratum}"
        assert_reference(ref, int(row["settlement_ts"]), climate_day(row), series, side, stratum)
        candle = exact_candle([c for c in candles if c["end_period_ts"] <= ref], ref)
        if candle is None:
            counts[f"{cell}:misses"] += 1
            continue
        counts["yes_bid_present"] += int(isinstance(candle.get("yes_bid"), Mapping))
        ask = no_ask(candle)
        if ask is None:
            counts["no_bid"] += 1
        elif Decimal("0.97") <= ask <= Decimal("0.99"):
            selected.append((stratum, ask))
        else:
            counts["outside_tail"] += 1
    return selected


def observations(row: Mapping[str, Any]) -> list[Observation]:
    if not in_window(row) or row_exclusion(row):
        return []
    result = str(row["result"]).strip().lower()
    if result not in {"yes", "no"}:
        return []
    series = row["series_ticker"]
    station = station_offset(series)[0]
    return [
        Observation(
            "HIGH" if series.startswith("KXHIGH") else "LOW",
            stratum,
            station,
            climate_day(row).isoformat(),
            Decimal(int(result == "no")) - ask,
            result == "no",
        )
        for stratum, ask in selections(audit_projection(row), Counter())
    ]


def audit_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    units: dict[str, set[tuple[str, str]]] = {cell: set() for cell in CELLS}
    for raw in rows:
        if not in_window(raw):
            counts["window"] += 1
            continue
        row = audit_projection(raw)
        series = row["series_ticker"]
        for stratum, _ in selections(row, counts):
            cell = f"{'HIGH' if series.startswith('KXHIGH') else 'LOW'}_{stratum}"
            units[cell].add((station_offset(series)[0], climate_day(row).isoformat()))
    return {
        "cells": {
            cell: {"n": len(units[cell]), "misses": counts[f"{cell}:misses"]} for cell in CELLS
        },
        "stations": {cell: dict(Counter(station for station, _ in units[cell])) for cell in CELLS},
        "exclusions": {key: counts[key] for key in ("window", "no_bid", "outside_tail")},
        "yes_bid_present": counts["yes_bid_present"],
        "F19": "consistent (empty series untested)",
    }


@dataclass(frozen=True)
class StationDay:
    day: str
    mean: Decimal

    def cluster_key(self, cluster: str) -> object:
        assert cluster == "day"
        return self.day


def mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def describe_cell(items: Sequence[Observation]) -> dict[str, Any]:
    if not items:
        return {
            "n": 0,
            "days": 0,
            "adequate": False,
            "weighted_mean": None,
            "pooled_mean": None,
            "bootstrap": None,
            "wilson": None,
            "observations": 0,
        }
    grouped: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for item in items:
        grouped[item.station, item.day].append(item.excess)
    units = [StationDay(day, mean(values)) for (_, day), values in grouped.items()]
    days = len({u.day for u in units})
    draws = bootstrap_cluster_draws(
        units,
        statistic=lambda sample: float(mean([u.mean for u in sample])),
        cluster="day",
        iterations=2000,
        seed=20261102,
    )
    return {
        "n": len(units),
        "days": days,
        "adequate": len(units) >= 30 and days >= 5,
        "weighted_mean": str(mean([u.mean for u in units])),
        "pooled_mean": str(mean([o.excess for o in items])),
        "bootstrap": percentile_interval(draws),
        "wilson": wilson_interval(sum(o.no_win for o in items), len(items)),
        "observations": len(items),
    }


def verdict(items: Sequence[Observation]) -> dict[str, Any]:
    cells = {
        cell: describe_cell([o for o in items if f"{o.side}_{o.stratum}" == cell]) for cell in CELLS
    }
    pre = [cells[f"{side}_pre"] for side in ("HIGH", "LOW")]
    decision = "INCONCLUSIVE"
    if all(c["adequate"] for c in pre):
        signs = [(Decimal(c["weighted_mean"]) <= 0, Decimal(c["pooled_mean"]) <= 0) for c in pre]
        if all(a == b for a, b in signs):
            decision = "KILL" if all(a and b for a, b in signs) else "CONTINUE"
    return {
        "decision": decision,
        "next_action": "STOP" if decision == "KILL" else "CONTINUE",
        "cells": cells,
        "intervals": "descriptive only",
        "classification": "SEARCH; alpha unspent",
    }


def verify_prereg() -> None:
    if hashlib.sha256(FROZEN_PREREG.read_bytes()).hexdigest() != FROZEN_PREREG_SHA:
        raise SealError("prereg sha mismatch")


def write_exclusive(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        link(temporary, path)
    finally:
        temporary.unlink()


def seal_manifest(raw: Path) -> None:
    lines = []
    for series in sorted(LST_TABLE):
        path = raw / f"{series}.json"
        if not path.is_file() or path.is_symlink():
            raise Incomplete("INCOMPLETE: series absent")
        json.loads(path.read_text())
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    write_exclusive(raw / "MANIFEST.sha256", "".join(lines))


def load_sealed(raw: Path) -> list[dict[str, Any]]:
    verify_prereg()
    lines = (raw / "MANIFEST.sha256").read_text().splitlines()
    expected = {f"{series}.json" for series in LST_TABLE}
    names = [line.split("  ")[-1] for line in lines]
    if len(names) != len(expected) or set(names) != expected:
        raise SealError("MANIFEST population mismatch")
    payloads = []
    for line, name in zip(lines, names, strict=True):
        path = raw / name
        if path.is_symlink() or line != f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}":
            raise SealError("MANIFEST sha mismatch")
        payload = json.loads(path.read_text())
        if payload.get("prereg_sha") != FROZEN_PREREG_SHA:
            raise SealError("prereg raw binding mismatch")
        payloads.append(payload)
    return payloads


def market_candles(client: HostPinnedKalshi, row: Mapping[str, Any]) -> Mapping[str, Any]:
    day = climate_day(row)
    series, ticker = row["series_ticker"], row["ticker"]
    end = int(
        dt.datetime.combine(
            day + dt.timedelta(days=1), dt.time(), local_time(0, series).tzinfo
        ).timestamp()
    )
    params = {"start_ts": timestamp(row["open_time"]), "end_ts": end, "period_interval": 60}
    order = ["historical_candles", "live_candles"]
    if day >= HISTORICAL_CUTOFF:
        order.reverse()
    for template in order:
        parts = (
            {"ticker": ticker, "series": series}
            if template == "live_candles"
            else {"ticker": ticker}
        )
        try:
            payload = client.get(template, parts=parts, params=params)
        except Absent:
            continue
        if not isinstance(payload, Mapping) or not isinstance(payload.get("candlesticks"), list):
            raise PoisonedInput("candle schema")
        return payload
    raise Absent("HTTP 404")


def list_markets(client: HostPinnedKalshi, series: str) -> list[Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for template in ("historical_markets", "live_markets"):
        params: dict[str, Any] = {"series_ticker": series, "limit": 1000}
        cursors: set[str] = set()
        while True:
            try:
                page = client.get(template, parts={}, params=params)
            except Absent:
                break
            for row in page["markets"]:
                ticker = row["ticker"]
                if not isinstance(ticker, str) or not re.fullmatch(_TOKEN, ticker):
                    raise PoisonedInput("market identity")
                rows.setdefault(ticker, row)
            cursor = page.get("cursor")
            if not cursor:
                break
            if cursor in cursors:
                raise PoisonedInput("repeated cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
    return list(rows.values())


def fetch(client: HostPinnedKalshi, raw: Path) -> int:
    verify_prereg()
    raw.mkdir(parents=True, exist_ok=True)
    disk = statvfs(raw)
    if disk.f_bavail * disk.f_frsize < 10_000_000_000:
        raise Incomplete("INCOMPLETE: free space below 10 GB")
    incomplete = False
    for series in LST_TABLE:
        target = raw / f"{series}.json"
        if target.exists():
            continue
        exclusions: Counter[str] = Counter()
        kept = []
        failed = False
        try:
            markets = list_markets(client, series)
        except Miss:
            incomplete = True
            continue
        for market in markets:
            if not in_window(market):
                exclusions["window"] += 1
                continue
            reason = row_exclusion(market)
            if reason or str(market.get("result")).strip().lower() not in {"yes", "no"}:
                exclusions[reason or "not_yes_no"] += 1
                continue
            row = {key: market[key] for key in ("ticker", "status", "result", "open_time")}
            if market.get("series_ticker", series) != series:
                raise PoisonedInput("series identity mismatch")
            row.update(series_ticker=series, climate_day=climate_day(market).isoformat())
            times = [
                timestamp(market[k])
                for k in ("settlement_time", "close_time", "expiration_time")
                if market.get(k)
            ]
            if market.get("settlement_ts") is not None:
                times.append(int(market["settlement_ts"]))
            if not times:
                raise PoisonedInput("settlement timestamp")
            row["settlement_ts"] = min(times)
            try:
                row["candlesticks"] = market_candles(client, row)["candlesticks"]
                row["candle_status"] = "success"
            except Absent:
                row.update(candlesticks=[], candle_status="Absent")
            except Miss:
                failed = True
                continue
            kept.append(row)
        if failed:
            incomplete = True
        else:
            write_exclusive(
                target,
                json.dumps(
                    {"rows": kept, "exclusions": dict(exclusions), "prereg_sha": FROZEN_PREREG_SHA},
                    sort_keys=True,
                ),
            )
    if incomplete:
        return 2
    if not (raw / "MANIFEST.sha256").exists():
        seal_manifest(raw)
    load_sealed(raw)
    return 0


def write_audit(raw: Path, evidence: Path, date: str) -> None:
    payloads = load_sealed(raw)
    rows = [audit_projection(row) for p in payloads for row in p["rows"]]
    report = audit_rows(rows)
    exclusions: Counter[str] = Counter(report["exclusions"])
    for p in payloads:
        exclusions.update(p["exclusions"])
    report["exclusions"] = dict(exclusions)
    write_exclusive(
        evidence / f"S0_{date}_audit.md",
        "# S0 outcome-blind audit\n\n" + json.dumps(report, indent=2) + "\n",
    )


def write_verdict(raw: Path, evidence: Path, date: str) -> None:
    target = evidence / f"S0_{date}.json"
    if target.exists() or (evidence / f"S0_{date}.md").exists():
        raise FileExistsError("S0 look already exists")
    payloads = load_sealed(raw)
    rows = [row for p in payloads for row in p["rows"]]
    audit_rows([audit_projection(row) for row in rows])
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f".S0_{date}.look").mkdir()
    result = verdict([o for row in rows for o in observations(row)])
    result["prereg_sha"] = FROZEN_PREREG_SHA
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    write_exclusive(target, content)
    suffix = "\nADAPTER_DECISION: NO-GO\n" if result["decision"] == "KILL" else ""
    write_exclusive(evidence / f"S0_{date}.md", "# S0 SEARCH verdict\n\n" + content + suffix)


def run_command(args: argparse.Namespace) -> int:
    verify_prereg()
    if args.command == "fetch":
        return fetch(HostPinnedKalshi.default(), args.raw_root)
    if args.command == "audit":
        write_audit(args.raw_root, args.evidence_root, args.date)
    else:
        write_verdict(args.raw_root, args.evidence_root, args.date)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    install_opener(build_opener(_NoRedirect(), ProxyHandler({})))
    parser = argparse.ArgumentParser(description=__doc__)
    root = parser.add_subparsers(dest="stage", required=True)
    s0 = root.add_parser("s0")
    commands = s0.add_subparsers(dest="command", required=True)
    for command in ("fetch", "audit", "verdict"):
        child = commands.add_parser(command)
        child.add_argument("--raw-root", type=Path, default=RAW_ROOT)
        child.add_argument("--evidence-root", type=Path, default=EVIDENCE_ROOT)
        child.add_argument("--date", default=dt.datetime.now(dt.UTC).date().isoformat())
    args = parser.parse_args(argv)
    dt.date.fromisoformat(args.date)
    try:
        return run_command(args)
    except (
        KalshiRefused,
        Incomplete,
        SealError,
        SemanticsHalt,
        PoisonedInput,
        FileExistsError,
    ) as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
