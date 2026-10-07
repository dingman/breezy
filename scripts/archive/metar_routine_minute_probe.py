#!/usr/bin/env python
"""Routine-METAR report-minute probe and 1-min archive equivalence measurement (F13 FB-R13).

WHAT THIS IS
------------
Phase A ruling FB-R13 defines ``obs_so_far`` as the running max of ROUTINE hourly METAR
temperatures, read from the IEM 1-min ASOS archive at one pinned minute per station
(``obs_routine_minute_by_station``). The 1-min archive carries no report-type field, so the
pin must come from METAR itself. This tool:

1. fetches IEM ASOS METAR (``report_type=3`` = routine only; ``tmpf`` + raw ``metar``; UTC) for
   one month per station per year and computes, per station-year, the modal ``valid`` minute,
   its share, the report count and the missing-``tmpf`` rate at the modal minute;
2. classifies each station (``PIN_STATION`` / ``PIN_STATION_YEAR`` / ``UNPINNABLE``, or
   ``INCOMPLETE`` when a station-year could not be fetched) and PROPOSES the pin maps. Nothing
   is ever written to the prereg;
3. measures equivalence: the METAR T-group (0.1 degC) through the live quantiser
   ``round_half_up_f`` against the whole-degF 1-min archive value at the same timestamp, read
   from the local archive cache only (a missing month is recorded as missing, never invented),
   and the METAR ``tmpf`` column against the T-group conversion.

EGRESS
------
A public HTTPS GET to the IEM host on the single path ``/cgi-bin/request/asos.py`` and nothing
else, through the ``PacedIemTransport`` (allowlist, redirect alarm, body cap, hard request
budget) with a 4 s pacing floor. No credential and no ``operator.env`` is read.

HOLDOUT
-------
Any requested window reaching 2026-07-01 or later is refused (exit 2); parsed rows at or after
the holdout are dropped as well. The holdout is sealed.

EXIT CODES
----------
0 complete
1 one or more station-years failed
2 refusal or error (the report is still written)
3 aborted: request budget exhausted
6 refused: started inside, or close enough to meet, the 16:30-17:10 UTC launch window
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode, urlsplit

_SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
for _sibling in ("analysis", "venue", "archive"):  # pragma: no cover - bootstrap
    _sibling_path = str(_SCRIPTS_ROOT / _sibling)
    if _sibling_path not in sys.path:
        sys.path.insert(0, _sibling_path)

# Imported after the sys.path bootstrap above (L-46: IEM retrieval stays under scripts/).
from iem_mos_probe_transport import (  # type: ignore[import-not-found]
    IEM_ALLOWED_HOSTS,
    IEM_BASE_URL,
    IemPacer,
    PacedIemTransport,
)
from multisource_blend_features_build import DEFAULT_STATIONS  # type: ignore[import-not-found]
from multisource_blend_inputs_obs import (  # type: ignore[import-not-found]
    modal_routine_minute_by_station,
)

from breezy.domain.temperature import round_half_up_f
from breezy.ingest.http import (
    RateLimitedError,
    ServerError,
    TransportError,
    TransportTimeoutError,
)
from breezy.ingest.probe_transport import RequestBudget, RequestBudgetExceededError
from breezy.persistence.archive_cache import (
    ArchiveCache,
    ArchiveCacheError,
    iem_asos_1min_request,
)
from breezy.persistence.autonomy.capture_schedule import launch_window_guard

__all__ = [
    "HOLDOUT_START",
    "FetchedText",
    "MetarRow",
    "MetarTransport",
    "build_plan",
    "classify_station",
    "main",
    "parse_metar_csv",
    "parse_tgroup_tenths",
]

SCHEMA: Final[str] = "metar_routine_minute_probe/v1"
LIVE_ENV_VAR: Final[str] = "BREEZY_LIVE"
USER_AGENT: Final[str] = (
    "breezy-metar-minute-probe/1.0 (read-only IEM METAR probe; contact: operator)"
)
ASOS_PATH: Final[str] = "/cgi-bin/request/asos.py"
REPORT_TYPE_ROUTINE: Final[str] = "3"
MAX_BODY_BYTES: Final[int] = 8 * 1024 * 1024
PACING_NS: Final[int] = 4_000_000_000
PER_REQUEST_WORST_CASE_S: Final[int] = 24  # 4 s pacing + 20 s read timeout
MAX_ATTEMPTS: Final[int] = 3
RETRY_BACKOFF_S: Final[float] = 30.0
_NS_PER_S: Final[int] = 1_000_000_000

#: The sealed holdout: no requested window may reach this date.
HOLDOUT_START: Final[dt.date] = dt.date(2026, 7, 1)
YEARS: Final[tuple[int, ...]] = (2021, 2022, 2023, 2024, 2025, 2026)
#: One sampled month per year, spread across seasons; 2026 stays before the holdout.
DEFAULT_MONTH_BY_YEAR: Final[Mapping[int, int]] = {
    2021: 3,
    2022: 6,
    2023: 9,
    2024: 12,
    2025: 4,
    2026: 5,
}
#: Pin rule: modal share must reach this in every sampled year.
PIN_SHARE_THRESHOLD: Final[float] = 0.95

#: IEM ``asos.py`` keys on the 3-letter identifier. Closed map: an unlisted station is refused.
IEM_METAR_STATION_IDS: Final[Mapping[str, str]] = {
    "KLAX": "LAX",
    "KMDW": "MDW",
    "KMIA": "MIA",
    "KNYC": "NYC",
    "KSFO": "SFO",
}

VERDICT_PIN_STATION: Final[str] = "PIN_STATION"
VERDICT_PIN_STATION_YEAR: Final[str] = "PIN_STATION_YEAR"
VERDICT_UNPINNABLE: Final[str] = "UNPINNABLE"
VERDICT_INCOMPLETE: Final[str] = "INCOMPLETE"

EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_REFUSED: Final[int] = 2
EXIT_ABORTED: Final[int] = 3
EXIT_LAUNCH_WINDOW: Final[int] = 6

_RETRYABLE: Final[tuple[type[TransportError], ...]] = (
    RateLimitedError,
    ServerError,
    TransportTimeoutError,
)
_TGROUP: Final[re.Pattern[str]] = re.compile(r"(?<!\S)T([01])(\d{3})(?:[01]\d{3})?(?!\S)")
_DEFAULT_ASOS_ROOT: Final[Path] = (
    Path.home() / ".local" / "share" / "breezy" / "archive" / "iem-asos-1min"
)


class RefusalError(RuntimeError):
    """The run is refused before any request is made."""


# ---------------------------------------------------------------------------
# Pure parsing and statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetarRow:
    valid: dt.datetime
    tmpf: float | None
    raw: str


def parse_tgroup_tenths(raw: str) -> int | None:
    """The temperature of the remarks ``T`` group in integer tenths of a degree C, or ``None``.

    ``T1xxx...`` is negative. Only the remarks section is searched, so a body token can never
    be mistaken for the group.
    """
    _body, sep, remarks = raw.partition(" RMK ")
    if not sep:
        return None
    match = _TGROUP.search(remarks)
    if match is None:
        return None
    tenths = int(match.group(2))
    return -tenths if match.group(1) == "1" else tenths


def tgroup_to_f(tenths: int) -> int:
    """T-group tenths C through the live quantiser."""
    return round_half_up_f(tenths)


def parse_metar_csv(text: str) -> list[MetarRow]:
    """IEM ``format=onlycomma`` body to rows. A body with no ``valid`` header is an error."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or "valid" not in header or "metar" not in header or "tmpf" not in header:
        raise ValueError("response has no valid/tmpf/metar header")
    i_valid, i_tmpf, i_metar = header.index("valid"), header.index("tmpf"), header.index("metar")
    rows: list[MetarRow] = []
    for record in reader:
        if len(record) <= max(i_valid, i_tmpf, i_metar):
            continue
        valid = dt.datetime.fromisoformat(record[i_valid].strip()).replace(tzinfo=dt.UTC)
        cell = record[i_tmpf].strip()
        tmpf = None if cell in ("", "M") else float(cell)
        rows.append(MetarRow(valid, tmpf, record[i_metar].strip()))
    return rows


def _month_end(year: int, month: int) -> dt.date:
    return dt.date(year + (month == 12), month % 12 + 1, 1)


def year_stats(rows: Sequence[MetarRow]) -> dict[str, Any]:
    """Modal-minute statistics of one station-year sample (reuses the pinned modal helper)."""
    modal = modal_routine_minute_by_station({"X": [row.valid for row in rows]}).get("X")
    if modal is None:
        return {
            "n_reports": 0,
            "modal_minute": None,
            "modal_share": None,
            "missing_tmpf_rate": None,
        }
    at_modal = [row for row in rows if row.valid.minute == modal.minute]
    missing = sum(1 for row in at_modal if row.tmpf is None)
    return {
        "n_reports": modal.n,
        "modal_minute": modal.minute,
        "modal_share": modal.share,
        "missing_tmpf_rate": missing / len(at_modal),
        "minute_histogram": {str(k): v for k, v in modal.histogram.items()},
    }


def classify_station(
    by_year: Mapping[int, Mapping[str, Any]], *, expected_years: int
) -> dict[str, Any]:
    """Verdict and proposed pin from per-year stats (years with no reports count as missing)."""
    usable = {y: s for y, s in by_year.items() if s.get("modal_minute") is not None}
    if len(usable) < expected_years or not usable:
        return {"verdict": VERDICT_INCOMPLETE}
    if any(s["modal_share"] < PIN_SHARE_THRESHOLD for s in usable.values()):
        return {"verdict": VERDICT_UNPINNABLE}
    minutes = {y: s["modal_minute"] for y, s in sorted(usable.items())}
    if len(set(minutes.values())) == 1:
        return {"verdict": VERDICT_PIN_STATION, "pin_minute": next(iter(minutes.values()))}
    return {"verdict": VERDICT_PIN_STATION_YEAR, "pin_minute_by_year": minutes}


class EquivalenceAccumulator:
    """METAR T-group vs 1-min whole-degF, and METAR tmpf column vs T-group, for one station."""

    def __init__(self) -> None:
        self.n_metar_rows = 0
        self.n_no_tgroup = 0
        self.n_no_onemin = 0
        self.diffs: Counter[int] = Counter()  # onemin - metar_tgroup, whole degF
        self.tmpf_n = 0
        self.tmpf_diffs: Counter[int] = Counter()  # tmpf_quantised - tgroup, whole degF
        self.missing_months: list[str] = []

    def add_month(
        self, rows: Sequence[MetarRow], onemin: Mapping[dt.datetime, float] | None, label: str
    ) -> None:
        if onemin is None:
            self.missing_months.append(label)
        for row in rows:
            self.n_metar_rows += 1
            tenths = parse_tgroup_tenths(row.raw)
            if tenths is None:
                self.n_no_tgroup += 1
                continue
            metar_f = tgroup_to_f(tenths)
            if row.tmpf is not None:
                self.tmpf_n += 1
                self.tmpf_diffs[math.floor(row.tmpf + 0.5) - metar_f] += 1
            if onemin is None:
                continue
            value = onemin.get(row.valid)
            if value is None:
                self.n_no_onemin += 1
                continue
            self.diffs[math.floor(value + 0.5) - metar_f] += 1

    @staticmethod
    def _summ(diffs: Counter[int]) -> dict[str, Any]:
        n = sum(diffs.values())
        if n == 0:
            return {
                "n_compared": 0,
                "mismatch_rate": None,
                "mean_signed_bias": None,
                "max_abs_diff": None,
            }
        return {
            "n_compared": n,
            "mismatch_rate": sum(c for d, c in diffs.items() if d != 0) / n,
            "mean_signed_bias": sum(d * c for d, c in diffs.items()) / n,
            "max_abs_diff": max(abs(d) for d in diffs),
            "diff_histogram": {str(d): c for d, c in sorted(diffs.items())},
        }

    def report(self) -> dict[str, Any]:
        return {
            "onemin_vs_metar_tgroup": self._summ(self.diffs),
            "tmpf_column_vs_tgroup": self._summ(self.tmpf_diffs),
            "n_metar_rows": self.n_metar_rows,
            "n_no_tgroup": self.n_no_tgroup,
            "n_tgroup_without_onemin_row": self.n_no_onemin,
            "months_missing_in_onemin_archive": sorted(self.missing_months),
        }


def read_onemin_window(
    body: bytes, start: dt.datetime, end: dt.datetime, wanted: set[dt.datetime]
) -> dict[dt.datetime, float]:
    """The ``wanted`` instants of a 1-min year payload inside ``[start, end)``."""
    reader = csv.reader(io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline=""))
    header = next(reader, None)
    if header is None or "valid(UTC)" not in header or "tmpf" not in header:
        raise ValueError("1-min payload has no valid(UTC)/tmpf header")
    i_valid, i_tmpf = header.index("valid(UTC)"), header.index("tmpf")
    out: dict[dt.datetime, float] = {}
    for record in reader:
        cell = record[i_tmpf].strip()
        if not cell or cell == "M":
            continue
        when = dt.datetime.fromisoformat(record[i_valid]).replace(tzinfo=dt.UTC)
        if start <= when < end and when in wanted:
            out[when] = float(cell)
    return out


# ---------------------------------------------------------------------------
# Plan, URL, transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedRequest:
    station: str
    year: int
    month: int
    start: dt.date
    end: dt.date
    url: str


def metar_url(station: str, start: dt.date, end: dt.date) -> str:
    pairs: list[tuple[str, str]] = [
        ("station", IEM_METAR_STATION_IDS[station]),
        ("data", "tmpf"),
        ("data", "metar"),
        ("year1", str(start.year)),
        ("month1", str(start.month)),
        ("day1", str(start.day)),
        ("year2", str(end.year)),
        ("month2", str(end.month)),
        ("day2", str(end.day)),
        ("tz", "Etc/UTC"),
        ("format", "onlycomma"),
        ("latlon", "no"),
        ("missing", "M"),
        ("trace", "T"),
        ("direct", "no"),
        ("report_type", REPORT_TYPE_ROUTINE),
    ]
    return f"{IEM_BASE_URL}{ASOS_PATH}?{urlencode(pairs)}"


def build_plan(
    stations: Sequence[str], months: Mapping[int, int] | None = None
) -> list[PlannedRequest]:
    """One request per station-year. Refuses unknown stations and any holdout-reaching window."""
    months = DEFAULT_MONTH_BY_YEAR if months is None else months
    plan: list[PlannedRequest] = []
    for station in stations:
        if station not in IEM_METAR_STATION_IDS:
            raise RefusalError(f"station {station!r} has no verified IEM METAR identifier")
        for year in sorted(months):
            month = months[year]
            if not 1 <= month <= 12:
                raise RefusalError(f"month {month} for year {year} is not 1..12")
            start, end = dt.date(year, month, 1), _month_end(year, month)
            if end > HOLDOUT_START:
                raise RefusalError(
                    f"window {start}..{end} reaches the sealed holdout (>= {HOLDOUT_START})"
                )
            plan.append(
                PlannedRequest(station, year, month, start, end, metar_url(station, start, end))
            )
    return plan


def require_metar_url(url: str) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in IEM_ALLOWED_HOSTS or parts.port not in (None, 443):
        raise ValueError("refused: not an https URL on an IEM-allowed host")
    if parts.path != ASOS_PATH:
        raise ValueError("refused: not an IEM asos.py retrieval")


@dataclass(frozen=True, slots=True)
class FetchedText:
    status_code: int
    text: str


class MetarFetcher(Protocol):
    async def fetch_metar_text(self, url: str) -> FetchedText: ...


class MetarTransport(PacedIemTransport):  # type: ignore[misc]
    """Budgeted, paced, IEM-only GET of the ASOS METAR CSV. Caller names a URL, never a host."""

    def __init__(self, *, budget: RequestBudget, pacer: IemPacer, clock: Callable[[], int]) -> None:
        super().__init__(
            budget=budget,
            pacer=pacer,
            user_agent=USER_AGENT,
            clock=clock,
            max_body_bytes=MAX_BODY_BYTES,
            accept="text/csv",
        )

    async def fetch_metar_text(self, url: str) -> FetchedText:
        require_metar_url(url)
        result = await self._fetch(
            url, if_none_match=None, if_modified_since=None, allow_not_modified=False
        )
        return FetchedText(status_code=result.status_code, text=result.text or "")


async def _fetch_with_retry(
    fetcher: MetarFetcher, url: str, sleep: Callable[[float], Awaitable[None]]
) -> FetchedText:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await fetcher.fetch_metar_text(url)
        except _RETRYABLE:
            if attempt == MAX_ATTEMPTS:
                raise
            await sleep(RETRY_BACKOFF_S * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

OneMinReader = Callable[[str, int], bytes | None]


def cache_onemin_reader(root: Path) -> OneMinReader:
    """Read-only 1-min year payloads from the local archive cache; a miss is ``None``."""

    def _refuse(_request: object) -> bytes:
        raise RuntimeError("the probe never fetches 1-min data")

    class _NoClock:
        def timestamp_ns(self) -> int:
            return 0

    cache = ArchiveCache(root, fetch=_refuse, clock=_NoClock())

    def read(icao: str, year: int) -> bytes | None:
        try:
            return cache.read(iem_asos_1min_request(icao, year))
        except ArchiveCacheError:
            return None

    return read


def _now(clock: Callable[[], int]) -> dt.datetime:
    return dt.datetime.fromtimestamp(clock() / _NS_PER_S, tz=dt.UTC)


def _may_run(clock: Callable[[], int], requests: int) -> bool:
    return launch_window_guard(clock(), 0, requests * PER_REQUEST_WORST_CASE_S)


def _new_report(args: argparse.Namespace, clock: Callable[[], int]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "generated_at": _now(clock).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "status": "started",
        "holdout_start": HOLDOUT_START.isoformat(),
        "report_type": REPORT_TYPE_ROUTINE,
        "pin_share_threshold": PIN_SHARE_THRESHOLD,
        "request_budget": args.request_budget,
        "proposals_only": "nothing is written to the prereg; the coordinator pins",
    }


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _station_result(
    station: str,
    items: Sequence[PlannedRequest],
    fetched: Mapping[tuple[str, int], list[MetarRow]],
    statuses: Mapping[tuple[str, int], str],
    onemin_reader: OneMinReader | None,
) -> dict[str, Any]:
    years: dict[int, dict[str, Any]] = {}
    equivalence = EquivalenceAccumulator()
    for item in items:
        key = (station, item.year)
        stats: dict[str, Any] = {"status": statuses.get(key, "not_fetched"), "month": item.month}
        rows = fetched.get(key)
        if rows is not None:
            stats.update(year_stats(rows))
            body = onemin_reader(station, item.year) if onemin_reader is not None else None
            start = dt.datetime.combine(item.start, dt.time(), dt.UTC)
            end = dt.datetime.combine(item.end, dt.time(), dt.UTC)
            onemin = (
                None
                if body is None
                else read_onemin_window(body, start, end, {row.valid for row in rows})
            )
            equivalence.add_month(rows, onemin, f"{item.year}-{item.month:02d}")
        years[item.year] = stats
    result = {"years": {str(y): s for y, s in sorted(years.items())}}
    result.update(classify_station(years, expected_years=len(items)))
    result["equivalence"] = equivalence.report()
    return result


def _proposals(stations: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    pins = {s: r["pin_minute"] for s, r in sorted(stations.items()) if "pin_minute" in r}
    by_year = {
        s: r["pin_minute_by_year"] for s, r in sorted(stations.items()) if "pin_minute_by_year" in r
    }
    return {
        "obs_routine_minute_by_station": pins,
        "obs_routine_minute_by_station_year": {
            s: {str(y): m for y, m in v.items()} for s, v in by_year.items()
        },
        "unresolved": {
            s: r["verdict"]
            for s, r in sorted(stations.items())
            if r["verdict"] in (VERDICT_UNPINNABLE, VERDICT_INCOMPLETE)
        },
    }


async def _run_requests(
    plan: Sequence[PlannedRequest],
    fetcher: MetarFetcher,
    clock: Callable[[], int],
    sleep: Callable[[float], Awaitable[None]],
    report: dict[str, Any],
) -> tuple[dict[tuple[str, int], list[MetarRow]], dict[tuple[str, int], str], int]:
    fetched: dict[tuple[str, int], list[MetarRow]] = {}
    statuses: dict[tuple[str, int], str] = {}
    code = EXIT_OK
    for item in plan:
        key = (item.station, item.year)
        if not _may_run(clock, 1):
            report["status"] = "paused_launch_window"
            return fetched, statuses, EXIT_LAUNCH_WINDOW
        try:
            response = await _fetch_with_retry(fetcher, item.url, sleep)
        except RequestBudgetExceededError:
            report["status"] = "budget_exhausted"
            return fetched, statuses, EXIT_ABORTED
        except TransportError as exc:
            statuses[key], code = f"fetch_error: {type(exc).__name__}", EXIT_FAILED
            continue
        if response.status_code != 200:
            statuses[key], code = f"http_{response.status_code}", EXIT_FAILED
            continue
        try:
            rows = [
                r for r in parse_metar_csv(response.text) if item.start <= r.valid.date() < item.end
            ]
        except ValueError as exc:
            statuses[key], code = f"bad_body: {exc}", EXIT_FAILED
            continue
        fetched[key] = rows
        statuses[key] = "ok" if rows else "empty"
    return fetched, statuses, code


def _parse_months(values: Sequence[str] | None) -> dict[int, int] | None:
    if not values:
        return None
    out: dict[int, int] = {}
    for value in values:
        year, _, month = value.partition("=")
        out[int(year)] = int(month)
    return out


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="plan only: no network")
    mode.add_argument("--apply", action="store_true", help=f"fetch; needs {LIVE_ENV_VAR}=1")
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--request-budget", type=int, default=None)
    parser.add_argument("--stations", nargs="+", default=list(DEFAULT_STATIONS))
    parser.add_argument("--months", nargs="+", metavar="YEAR=MONTH", default=None)
    parser.add_argument("--asos-root", type=Path, default=_DEFAULT_ASOS_ROOT)
    return parser.parse_args(list(argv))


def _execute(
    args: argparse.Namespace,
    report: dict[str, Any],
    clock: Callable[[], int],
    fetcher: MetarFetcher | None,
    onemin_reader: OneMinReader | None,
    sleep: Callable[[float], Awaitable[None]],
) -> int:
    plan = build_plan(args.stations, _parse_months(args.months))
    report["planned_requests"] = len(plan)
    report["plan"] = [
        {"station": p.station, "year": p.year, "month": p.month, "url": p.url} for p in plan
    ]
    if not args.apply:
        report["status"] = "dry_run"
        return EXIT_OK
    if os.environ.get(LIVE_ENV_VAR) != "1":
        raise RefusalError(f"{LIVE_ENV_VAR}=1 is required before this tool may dispatch a request")
    if not args.request_budget or args.request_budget < len(plan):
        raise RefusalError(
            f"--request-budget must be given and cover the {len(plan)} planned requests"
        )
    if not _may_run(clock, len(plan)):
        report["status"] = "refused_launch_window"
        return EXIT_LAUNCH_WINDOW
    resolved = fetcher or MetarTransport(
        budget=RequestBudget(limit=args.request_budget),
        pacer=IemPacer(clock=clock, min_interval_ns=PACING_NS),
        clock=clock,
    )
    reader = onemin_reader if onemin_reader is not None else cache_onemin_reader(args.asos_root)
    fetched, statuses, code = asyncio.run(_run_requests(plan, resolved, clock, sleep, report))
    by_station: dict[str, list[PlannedRequest]] = {}
    for item in plan:
        by_station.setdefault(item.station, []).append(item)
    stations = {
        s: _station_result(s, items, fetched, statuses, reader) for s, items in by_station.items()
    }
    report["stations"] = stations
    report["proposals"] = _proposals(stations)
    if report["status"] == "started":
        report["status"] = "complete" if code == EXIT_OK else "partial"
    return code


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], int] | None = None,
    fetcher: MetarFetcher | None = None,
    onemin_reader: OneMinReader | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> int:
    """``clock``, ``fetcher``, ``onemin_reader`` and ``sleep`` are test seams, never CLI flags."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    resolved_clock = clock if clock is not None else time.time_ns
    report = _new_report(args, resolved_clock)
    try:
        if not _may_run(resolved_clock, 1):
            report["status"] = "refused_launch_window"
            code = EXIT_LAUNCH_WINDOW
            print("refused: inside the 16:30-17:10 UTC launch window", file=sys.stderr)
        else:
            code = _execute(
                args, report, resolved_clock, fetcher, onemin_reader, sleep or asyncio.sleep
            )
    except Exception as exc:  # noqa: BLE001 - the report is always written (exit 2)
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"refused: {exc}", file=sys.stderr)
        code = EXIT_REFUSED
    report["exit_code"] = code
    try:
        write_report(args.report_json, report)
    except OSError as exc:
        print(f"report not written: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if args.dry_run and code == EXIT_OK:
        print(f"planned_requests={report['planned_requests']} report={args.report_json}")
        for entry in report["plan"]:
            print(f"{entry['station']} {entry['year']}-{entry['month']:02d} {entry['url']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
