"""F13 B0 backfill: PFM history (IEM AFOS) and GFS MOS history (incl. KNYC). Coordinator-run.

Read-only network use against ``mesonet.agron.iastate.edu`` only; the one local write path is
the ``us-pfm-afos`` revision store (PFM) and the existing MOS archive writer (GFS).

* PFM: ``PacedIemTransport.fetch_afos_pfm`` pages ascending history (``sdate``, ``order=asc``,
  at most 50 products per request) at the A0-R1 pace (>= 4 s between AFOS requests). Each
  product is split out, its WMO issuance time resolved, parsed (a refused product is counted
  and never written) and appended RAW through ``UsSourceRevisionStore`` under the collector's
  key shape, so a re-run appends nothing and a live-collected issuance is not duplicated by
  key. Normalised CSVs and the poll ledger are not written: a backfilled row's availability is
  its exact WMO header time and the live collector owns first-seen stamps.
* GFS: delegated to the existing ``iem_mos_backfill`` CLI (model ``GFS``, KNYC included via
  the R33 ``IEM_MOS_STATIONS`` widening), so the MOS archive keeps ONE writer.

Safety: ``--dry-run`` plans only (no network, no write); ``--apply`` needs ``BREEZY_LIVE=1`` and
a request budget. A request never starts inside, or close enough to meet, the 16:30-17:10Z
launch window (``launch_window_guard``): the PFM leg pauses and names the resume date. A throttle
body ("Too many requests ...") is never data: the leg backs off, then stops and alerts.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

_ARCHIVE_DIR = Path(__file__).resolve().parent
for _directory in (_ARCHIVE_DIR, _ARCHIVE_DIR.parent / "venue"):  # pragma: no cover - bootstrap
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

from iem_mos_probe_transport import (  # type: ignore[import-not-found]
    IEM_AFOS_LAV_MIN_INTERVAL_NS,
    IEM_AFOS_MAX_LIMIT,
    IEM_AFOS_PFM_MAX_BODY_BYTES,
    IemPacer,
    PacedIemTransport,
)

from breezy.ingest.http import RateLimitedError
from breezy.ingest.pfm_parse import PfmParseError, parse_pfm_product
from breezy.ingest.probe_transport import (
    RequestBudget,
    RequestBudgetExceededError,
)
from breezy.persistence.autonomy.capture_schedule import launch_window_guard
from breezy.persistence.us_source_request import (
    PFM_POINTS,
    US_PFM_AFOS_SOURCE,
    US_SOURCE_STATIONS,
)
from breezy.persistence.us_source_revision_store import (
    AppendOutcome,
    RevisionStoreBusyError,
    RevisionStoreError,
    UsSourceRevisionStore,
)

__all__ = [
    "LegReport",
    "main",
    "make_pfm_fetch",
    "make_window_guard",
    "resolve_issuance_sequence",
    "run_pfm_leg",
    "split_products",
    "wmo_header_fields",
]

_NS: Final[int] = 1_000_000_000
LIVE_ENV_VAR: Final[str] = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: Final[str] = "BREEZY_USER_AGENT"
DEFAULT_USER_AGENT: Final[str] = "breezy-us-source-backfill (contact: jon@gopoint.com; F13 B0)"
FIRST_YEAR: Final[int] = 2021
#: A request is paced (>= 4 s), may read for up to 20 s, plus slack.
REQUEST_WORST_CASE_S: Final[int] = 30
THROTTLE_BACKOFF_S: Final[tuple[float, ...]] = (30.0, 120.0, 300.0)
BUSY_WAIT_S: Final[float] = 10.0
BUSY_RETRIES: Final[int] = 3
#: Planning constant for the dry run only (LOT issues ~28/day, the others fewer).
PLANNING_ISSUANCES_PER_DAY: Final[int] = 24
MAX_GAP_DAYS: Final[int] = 45
_MAX_MONTH_BUMPS: Final[int] = 3
DEFAULT_MAX_RUNTIME_S: Final[int] = 3 * 3600
_REFUSE_REASON_FALLBACK: Final[str] = "unparsed"
_EXIT_REFUSED: Final[int] = 2
_EXIT_INCOMPLETE: Final[int] = 1
_SOH: Final[str] = "\x01"
_ETX: Final[str] = "\x03"
_HEADER_SCAN_LINES: Final[int] = 10
_WMO_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{4}\d{2} ([A-Z]{4}) (\d{2})(\d{2})(\d{2})$")

PfmFetch = Callable[[str, dt.date, int], str]


# ------------------------------------------------------------------ pure helpers


def split_products(text: str) -> tuple[str, ...]:
    """Split one AFOS text response into its products (each keeps its leading SOH)."""
    if not text.strip():
        return ()
    parts = text.split(_SOH)
    if len(parts) == 1:
        body = text.replace(_ETX, "").rstrip()
        return (body,) if body else ()
    out: list[str] = []
    for part in parts[1:]:
        body = part.replace(_ETX, "").rstrip()
        if body.strip():
            out.append(_SOH + body)
    return tuple(out)


def wmo_header_fields(product: str) -> tuple[str, int, int, int] | None:
    """``(CCCC, day, hour, minute)`` of the WMO abbreviated heading, or None."""
    for line in product.splitlines()[:_HEADER_SCAN_LINES]:
        match = _WMO_RE.match(line.strip())
        if match is not None:
            cccc, day, hour, minute = match.groups()
            return cccc, int(day), int(hour), int(minute)
    return None


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def resolve_issuance_sequence(
    headers: Sequence[tuple[int, int, int]], start: dt.date
) -> list[dt.datetime]:
    """Resolve ``(day, hour, minute)`` headers, ascending from ``start``, to UTC instants.

    A WMO header carries no month or year. Ascending order lets the month advance whenever the
    day-of-month steps backwards (or the day does not exist in the current month).
    """
    year, month = start.year, start.month
    previous = dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC)
    resolved: list[dt.datetime] = []
    for day, hour, minute in headers:
        found: dt.datetime | None = None
        for _ in range(_MAX_MONTH_BUMPS):
            try:
                candidate: dt.datetime | None = dt.datetime(
                    year, month, day, hour, minute, tzinfo=dt.UTC
                )
            except ValueError:
                candidate = None
            if candidate is not None and candidate >= previous:
                found = candidate
                break
            year, month = _next_month(year, month)
        if found is None:
            raise ValueError(
                f"cannot place header {day:02d}{hour:02d}{minute:02d} after {previous}"
            )
        if found - previous > dt.timedelta(days=MAX_GAP_DAYS):
            raise ValueError(f"issuance gap over {MAX_GAP_DAYS} days before {found.isoformat()}")
        resolved.append(found)
        previous = found
    return resolved


def make_window_guard(worst_case_s: int = REQUEST_WORST_CASE_S) -> Callable[[int], bool]:
    """``window_ok(now_ns)``: True when a request starting now cannot meet 16:30-17:10Z."""

    def window_ok(now_ns: int) -> bool:
        return launch_window_guard(now_ns, 0, worst_case_s)

    return window_ok


# ---------------------------------------------------------------------- PFM leg


@dataclass(slots=True)
class LegReport:
    station: str
    wfo: str
    status: str = "complete"
    requests: int = 0
    products_seen: int = 0
    appended: int = 0
    unchanged: int = 0
    quarantined: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    truncated_days: tuple[dt.date, ...] = ()
    resume_sdate: dt.date | None = None

    @property
    def refused_total(self) -> int:
        return sum(self.refused.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "station": self.station,
            "wfo": self.wfo,
            "status": self.status,
            "requests": self.requests,
            "products_seen": self.products_seen,
            "appended": self.appended,
            "unchanged": self.unchanged,
            "quarantined": self.quarantined,
            "refused": dict(sorted(self.refused.items())),
            "truncated_days": [d.isoformat() for d in self.truncated_days],
            "resume_sdate": self.resume_sdate.isoformat() if self.resume_sdate else None,
        }


class _StoreClock:
    def __init__(self, clock_ns: Callable[[], int]) -> None:
        self._clock_ns = clock_ns

    def timestamp_ns(self) -> int:
        return self._clock_ns()


def _alert(message: str) -> None:
    sys.stderr.write(f"ALERT us-source-backfill: {message}\n")


def _fetch_page(
    fetch: PfmFetch,
    wfo: str,
    cursor: dt.date,
    limit: int,
    report: LegReport,
    sleep: Callable[[float], None],
    window_ok: Callable[[int], bool],
    clock_ns: Callable[[], int],
) -> str | None:
    """One page, retrying a throttle with backoff; None means the leg must stop (status set)."""
    for attempt in range(len(THROTTLE_BACKOFF_S) + 1):
        if not window_ok(clock_ns()):
            report.status = "paused_launch_window"
            return None
        try:
            text = fetch(wfo, cursor, limit)
        except RequestBudgetExceededError:
            report.status = "budget_exhausted"
            return None
        except RateLimitedError:
            report.requests += 1
            if attempt == len(THROTTLE_BACKOFF_S):
                report.status = "throttled"
                _alert(f"IEM throttle persisted for PFM{wfo} at sdate={cursor}; stopping the leg")
                return None
            sleep(THROTTLE_BACKOFF_S[attempt])
            continue
        report.requests += 1
        return text
    return None  # pragma: no cover - the loop always returns


def _append(
    store: UsSourceRevisionStore,
    report: LegReport,
    sleep: Callable[[float], None],
    *,
    station: str,
    run_ts_ns: int,
    wfo: str,
    payload: bytes,
) -> bool:
    """Append one raw revision; False when the unit lock stayed busy past the retries."""
    for attempt in range(BUSY_RETRIES + 1):
        try:
            result = store.append_if_new(
                source=US_PFM_AFOS_SOURCE,
                station=station,
                run_ts_ns=run_ts_ns,
                model=wfo,
                payload=payload,
            )
        except RevisionStoreBusyError:
            if attempt == BUSY_RETRIES:
                return False
            sleep(BUSY_WAIT_S)
            continue
        except RevisionStoreError as exc:
            _count(report, type(exc).__name__)
            return True
        if result.outcome is AppendOutcome.APPENDED:
            report.appended += 1
        elif result.outcome is AppendOutcome.UNCHANGED:
            report.unchanged += 1
        else:
            report.quarantined += 1
        return True
    return False  # pragma: no cover


def _count(report: LegReport, reason: str) -> None:
    report.refused[reason] = report.refused.get(reason, 0) + 1


def _place(
    products: Sequence[str], cursor: dt.date, report: LegReport
) -> list[tuple[str, dt.datetime | None]]:
    """Pair each product with its resolved issuance time; headerless ones are refused."""
    headers = [wmo_header_fields(p) for p in products]
    parseable = [(h[1], h[2], h[3]) for h in headers if h is not None]
    resolved = iter(resolve_issuance_sequence(parseable, cursor))
    paired: list[tuple[str, dt.datetime | None]] = []
    for product, header in zip(products, headers, strict=True):
        if header is None:
            _count(report, "no_wmo_header")
            paired.append((product, None))
        else:
            paired.append((product, next(resolved)))
    return paired


def _ingest_page(
    paired: Sequence[tuple[str, dt.datetime | None]],
    *,
    station: str,
    wfo: str,
    end: dt.date,
    store: UsSourceRevisionStore,
    report: LegReport,
    sleep: Callable[[float], None],
) -> tuple[dt.datetime | None, bool, bool]:
    """Store a page; returns ``(last issuance seen, past_end, busy)``."""
    last: dt.datetime | None = None
    for product, issued in paired:
        if issued is None:
            continue
        if issued.date() > end:
            return last, True, False
        last = issued
        report.products_seen += 1
        raw = product.encode("utf-8")
        try:
            parse_pfm_product(raw, station=station, reference_time=issued + dt.timedelta(seconds=1))
        except PfmParseError as exc:
            _count(report, exc.reason or _REFUSE_REASON_FALLBACK)
            continue
        run_ts_ns = int(issued.timestamp()) * _NS
        if not _append(
            store, report, sleep, station=station, run_ts_ns=run_ts_ns, wfo=wfo, payload=raw
        ):
            return last, False, True
    return last, False, False


def run_pfm_leg(
    *,
    station: str,
    start: dt.date,
    end: dt.date,
    fetch: PfmFetch,
    store: UsSourceRevisionStore,
    clock_ns: Callable[[], int],
    window_ok: Callable[[int], bool],
    sleep: Callable[[float], None],
    page_limit: int = IEM_AFOS_MAX_LIMIT,
) -> LegReport:
    """Backfill one station's WFO from ``start`` to ``end`` inclusive, ascending by issuance."""
    wfo = PFM_POINTS[station].wfo
    report = LegReport(station=station, wfo=wfo)
    truncated: list[dt.date] = []
    cursor = start
    while cursor <= end:
        text = _fetch_page(fetch, wfo, cursor, page_limit, report, sleep, window_ok, clock_ns)
        if text is None:
            report.resume_sdate = cursor
            break
        products = split_products(text)
        if not products:
            break
        paired = _place(products, cursor, report)
        last, past_end, busy = _ingest_page(
            paired, station=station, wfo=wfo, end=end, store=store, report=report, sleep=sleep
        )
        if busy:
            report.status, report.resume_sdate = "store_busy", cursor
            break
        if past_end or len(products) < page_limit or last is None:
            break
        following = last.date()
        if following <= cursor:  # a full page inside one date: the rest of that date is unseen
            truncated.append(cursor)
            following = cursor + dt.timedelta(days=1)
        cursor = following
    report.truncated_days = tuple(truncated)
    return report


# -------------------------------------------------------------------- transport


def make_pfm_fetch(
    *,
    request_budget: int,
    user_agent: str,
    clock_ns: Callable[[], int],
    sleeper: Callable[[float], Any] | None = None,
    check_proxy_env: bool = True,
) -> PfmFetch:
    """The AFOS fetch: paced IEM transport, A0-R1 spacing, a hard shared request budget."""
    transport = PacedIemTransport(
        budget=RequestBudget(limit=request_budget),
        pacer=IemPacer(
            clock=clock_ns, sleeper=sleeper, min_interval_ns=IEM_AFOS_LAV_MIN_INTERVAL_NS
        ),
        user_agent=user_agent,
        clock=clock_ns,
        max_body_bytes=IEM_AFOS_PFM_MAX_BODY_BYTES,
        accept="text/plain",
        check_proxy_env=check_proxy_env,
    )

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        result = asyncio.run(transport.fetch_afos_pfm(wfo, sdate=sdate, limit=limit))
        return result.text or ""

    return fetch


# ------------------------------------------------------------------------ plans


def _last_complete_year(end: dt.date) -> int:
    return end.year if (end.month, end.day) == (12, 31) else end.year - 1


def _gfs_years(start: dt.date, end: dt.date) -> list[int]:
    return list(range(max(FIRST_YEAR, start.year), _last_complete_year(end) + 1))


def _gfs_argv(
    stations: Sequence[str], years: Sequence[int], budget: int, cache_root: Path | None
) -> list[str]:
    argv = [
        "--stations", *stations,
        "--first-year", str(years[0]),
        "--through-year", str(years[-1]),
        "--model", "GFS",
        "--apply",
        "--request-budget", str(budget),
    ]  # fmt: skip
    if cache_root is not None:
        argv += ["--cache-root", str(cache_root)]
    return argv


def _pfm_plan(
    stations: Sequence[str], start: dt.date, end: dt.date, budget: int | None
) -> dict[str, Any]:
    days = (end - start).days + 1
    per_wfo = math.ceil(days * PLANNING_ISSUANCES_PER_DAY / IEM_AFOS_MAX_LIMIT)
    wfos = {
        PFM_POINTS[s].wfo: {
            "station": s,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "estimated_requests": per_wfo,
        }
        for s in stations
    }
    total = per_wfo * len(wfos)
    pacing_s = IEM_AFOS_LAV_MIN_INTERVAL_NS / _NS
    return {
        "wfos": wfos,
        "pacing_s": pacing_s,
        "page_limit": IEM_AFOS_MAX_LIMIT,
        "planning_issuances_per_day": PLANNING_ISSUANCES_PER_DAY,
        "estimated_requests": total,
        "estimated_seconds": total * pacing_s,
        "request_budget": budget,
        "fits_budget": None if budget is None else total <= budget,
    }


def _gfs_plan(stations: Sequence[str], years: Sequence[int]) -> dict[str, Any]:
    return {
        "model": "GFS",
        "stations": list(stations),
        "years": list(years),
        "estimated_requests": len(stations) * len(years),
        "delegates_to": "scripts/archive/iem_mos_backfill.py",
    }


# ------------------------------------------------------------------------- main


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=None)
    parser.add_argument("--legs", nargs="+", choices=("pfm", "gfs"), default=["pfm", "gfs"])
    parser.add_argument("--stations", nargs="+", default=list(US_SOURCE_STATIONS))
    parser.add_argument(
        "--start-date", type=dt.date.fromisoformat, default=dt.date(FIRST_YEAR, 1, 1)
    )
    parser.add_argument("--end-date", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--request-budget", type=int, default=None)
    parser.add_argument("--gfs-request-budget", type=int, default=None)
    parser.add_argument("--max-runtime-s", type=int, default=DEFAULT_MAX_RUNTIME_S)
    parser.add_argument("--mos-cache-root", type=Path, default=None)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(list(argv))


def _refuse(message: str) -> int:
    sys.stderr.write(f"REFUSED: {message}\n")
    return _EXIT_REFUSED


def _validate(args: argparse.Namespace) -> str | None:
    """A refusal message, or None when the invocation is coherent."""
    if args.dry_run == args.apply:
        return "exactly one of --dry-run and --apply is required"
    if args.start_date < dt.date(FIRST_YEAR, 1, 1):
        return f"--start-date may not precede {FIRST_YEAR}-01-01 (PFM format break, NBM versions)"
    unknown = [s for s in args.stations if s not in US_SOURCE_STATIONS]
    if unknown:
        return f"station(s) {unknown} are outside the closed set {list(US_SOURCE_STATIONS)}"
    if "pfm" in args.legs and args.archive_root is None:
        return "--archive-root is required for the pfm leg"
    if args.apply and os.environ.get(LIVE_ENV_VAR) != "1":
        return f"{LIVE_ENV_VAR}=1 is required before any request may be dispatched"
    if args.apply and "pfm" in args.legs and not args.request_budget:
        return "--request-budget is required for a real pfm run"
    if args.request_budget is not None and args.request_budget < 1:
        return "--request-budget must be a positive request count"
    return None


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def _default_gfs_runner(argv: Sequence[str]) -> int:  # pragma: no cover - live delegation
    from iem_mos_backfill import main as mos_main  # type: ignore[import-not-found]

    return int(mos_main(list(argv)))


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], None] = time.sleep,
    pfm_fetch_factory: Callable[..., PfmFetch] = make_pfm_fetch,
    gfs_runner: Callable[[Sequence[str]], int] = _default_gfs_runner,
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    problem = _validate(args)
    if problem is not None:
        return _refuse(problem)
    end = args.end_date or dt.datetime.fromtimestamp(clock() / _NS, tz=dt.UTC).date()
    stations: list[str] = list(args.stations)
    years = _gfs_years(args.start_date, end)
    report: dict[str, Any] = {
        "mode": "dry_run" if args.dry_run else "apply",
        "inputs": {
            "start": args.start_date.isoformat(),
            "end": end.isoformat(),
            "stations": stations,
            "legs": list(args.legs),
        },
        "launch_window_utc": "16:30-17:10",
    }
    if "pfm" in args.legs:
        report["pfm"] = _pfm_plan(stations, args.start_date, end, args.request_budget)
    if "gfs" in args.legs:
        report["gfs"] = _gfs_plan(stations, years)
    if args.dry_run:
        _write_report(args.report_json, report)
        return 0
    code = _apply(args, report, stations, years, end, clock, sleep, pfm_fetch_factory, gfs_runner)
    _write_report(args.report_json, report)
    return code


def _apply(
    args: argparse.Namespace,
    report: dict[str, Any],
    stations: Sequence[str],
    years: Sequence[int],
    end: dt.date,
    clock: Callable[[], int],
    sleep: Callable[[float], None],
    pfm_fetch_factory: Callable[..., PfmFetch],
    gfs_runner: Callable[[Sequence[str]], int],
) -> int:
    if "gfs" in args.legs and years and not launch_window_guard(clock(), 0, args.max_runtime_s):
        return _refuse(
            f"a {args.max_runtime_s} s run starting now could meet the 16:30-17:10Z launch window"
        )
    incomplete = False
    if "pfm" in args.legs:
        user_agent = os.environ.get(USER_AGENT_ENV_VAR, DEFAULT_USER_AGENT)
        fetch = pfm_fetch_factory(
            request_budget=args.request_budget, user_agent=user_agent, clock_ns=clock
        )
        store = UsSourceRevisionStore(args.archive_root, _StoreClock(clock))
        legs = [
            run_pfm_leg(
                station=s,
                start=args.start_date,
                end=end,
                fetch=fetch,
                store=store,
                clock_ns=clock,
                window_ok=make_window_guard(),
                sleep=sleep,
            )
            for s in stations
        ]
        report["pfm"]["legs"] = [leg.to_dict() for leg in legs]
        incomplete = any(leg.status != "complete" for leg in legs)
    if "gfs" in args.legs:
        if not years:
            report["gfs"]["status"] = "nothing_to_do"
        else:
            budget = args.gfs_request_budget or len(stations) * len(years)
            code = gfs_runner(_gfs_argv(stations, years, budget, args.mos_cache_root))
            report["gfs"].update(status="complete" if code == 0 else "failed", exit_code=code)
            incomplete = incomplete or code != 0
    return _EXIT_INCOMPLETE if incomplete else 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
