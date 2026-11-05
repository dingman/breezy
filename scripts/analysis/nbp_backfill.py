#!/usr/bin/env python3
"""SL-4: the NBM NBP historical backfill (FORECAST_NBP_PROBABILISTIC_FAMILY
Rev3, plan §7 row 4).

WHAT THIS COVERS. For each date in ``[--start, --end]`` and each of the
three D+1 cycles ``{13Z, 19Z, 01Z}`` (plan §2.3), fetch the collective
``blend_nbptx`` bulletin through :class:`breezy.ingest.nbm_quantile_transport.
NbmQuantileTransport` (AWS S3 primary, NOMADS fallback -- both tried inside
the transport's own ``fetch_nbp_bulletin``) and parse it with
:func:`breezy.ingest.nbm_quantile_parse.parse_nbp_bulletin` for the four
traded stations (KLAX, KMDW, KMIA, KSFO). One row is emitted per (station,
cycle_runtime, variable, valid window) -- ``TXN_Q10``, ``TXN_Q25``,
``TXN_Q50``, ``TXN_Q75``, ``TXN_Q90``, ``TXN_MEAN``, ``TXN_SD`` -- tagged
with:

* the NBM version, cross-checked against ``NBM_VERSION_BREAKS`` (reused from
  ``scripts.analysis.nbp_lag_census.VERSION_BREAKS``, the ONE copy of that
  table): a mismatch between the header's own version and the era expected
  for the cycle's UTC calendar date is LOGGED and the header wins;
* ``available_at_ns = max(LastModified, cycle + floor)`` (plan §3.2 item 1,
  the SL-1b floor);
* the source host and the raw bulletin's sha256.

OUTPUT. Parquet under ``--output-dir`` (default
``~/.local/share/breezy/derived/nbp/``), one file per (date, cycle) --
``<output-dir>/<YYYY>/<MM>/nbp_<YYYYMMDD>_<HH>z.parquet`` -- partitioned by
the cycle's own UTC year/month. A durable JSON manifest
(``_manifest.json``) records every completed (date, cycle) checkpoint, so a
re-run RESUMES: an already-manifested pair is skipped without a request. A
separate failure ledger (``_failures.json``) names every (date, cycle) that
failed on BOTH hosts (or failed to parse) -- no row is ever written for a
failed pair; it is reported, never filled in, and simply stays absent from
the manifest so the next run retries it.

DEDUPE (R2-13 / R3-08, branch (b) -- BBB absent, `docs/evidence/
NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md` part (b)). Every partition write
deduplicates its own rows via
:func:`breezy.persistence.nbp_derived_store.dedupe_rows`:
``max(LastModified, raw_sha256)`` per (station, cycle_runtime, variable,
valid window), deterministic. This run logs, once, that dedupe is operating
in no-BBB mode (see the module import and the log line in :func:`main`).

SAFETY DEFAULTS. ``--dry-run`` is the default: with neither ``--dry-run``
nor ``--apply``, the run lists the planned (date, cycle) items and makes no
request. ``--apply`` additionally requires ``BREEZY_LIVE=1`` in the
environment and a monitored ``BREEZY_USER_AGENT`` -- mirrors
``scripts/archive/iem_mos_backfill.py``.

MEMORY. Process-then-discard, one (date, cycle) at a time: the transport
itself streams and filters to the four wanted stations
(``NbmQuantileTransport``, L-53), so the largest live object ever held is one
filtered bulletin's text (kilobytes), never the ~30+ MB raw body. The
recommended way to run a real historical backfill is under a hard memory
cap::

    systemd-run --user --pty -p MemoryMax=2G -p LimitNOFILE=524288 \\
        --setenv=BREEZY_LIVE=1 \\
        --setenv=BREEZY_USER_AGENT='breezy-research (jon@gopoint.com)' \\
        /home/jon/breezy/.venv/bin/python scripts/analysis/nbp_backfill.py \\
        --apply --start 2021-01-01 --end 2026-09-29

Exit codes: 0 complete (including a run with recorded failures -- they are
reported, not fatal), 2 refusal (bad arguments / missing unlock).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from breezy.ingest.nbm_quantile_parse import (
    NbpBulletinDriftError,
    parse_nbp_bulletin,
)
from breezy.ingest.nbm_quantile_transport import (
    DEFAULT_NBM_QUANTILE_STATIONS,
    BothHostsFailedError,
    NbmQuantileFetchError,
    NbmQuantileTransport,
)
from breezy.persistence.autonomy.capture_schedule import launch_window_guard
from breezy.persistence.nbp_derived_store import (
    DerivedNbpRow,
    FailureEntry,
    ManifestEntry,
    available_at_ns,
    load_manifest,
    manifest_key,
    parse_http_last_modified,
    partition_path,
    record_failure,
    record_success,
    write_partition,
)

# `scripts.analysis` is not part of the `breezy` import-linter graph, so
# reusing `VERSION_BREAKS`/`version_for` here is a plain, DRY import -- the
# ONE copy of the version-era table (also reused by SL-3's lag census).
from scripts.analysis.nbp_lag_census import VERSION_BREAKS, version_for

__all__ = [
    "CYCLES",
    "DEFAULT_OUTPUT_DIR_TAIL",
    "LIVE_ENV_VAR",
    "USER_AGENT_ENV_VAR",
    "BackfillPlanItem",
    "BackfillRunReport",
    "build_plan",
    "default_output_dir",
    "derive_rows_for_bulletin",
    "item_key",
    "main",
    "run_backfill",
]

#: The D+1 cycles (plan §2.3): 13Z and 19Z of date D, and 01Z of date D+1's
#: own calendar date -- `NbmQuantileTransport.fetch_nbp_bulletin` takes the
#: cycle's OWN UTC calendar date directly, so no D+1 arithmetic happens here.
CYCLES: Final[tuple[int, ...]] = (13, 19, 1)

LIVE_ENV_VAR: Final[str] = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: Final[str] = "BREEZY_USER_AGENT"

DEFAULT_OUTPUT_DIR_TAIL: Final[tuple[str, ...]] = (
    ".local",
    "share",
    "breezy",
    "derived",
    "nbp",
)

#: Each item may issue two requests (S3, then the NOMADS fallback); the
#: budget is charged the worst case up front so it is a hard ceiling.
REQUESTS_PER_ITEM_WORST_CASE: Final[int] = 2
#: Worst-case seconds one item can run (two hosts x the transport's 65 s
#: connect+read ceiling, rounded up) -- the launch-window guard span.
ITEM_WORST_CASE_S: Final[int] = 150
DEFAULT_PACE_S: Final[float] = 1.0
STATIONS_MARKER_NAME: Final[str] = "_stations.json"
STOP_BUDGET: Final[str] = "budget_exhausted"
STOP_WINDOW: Final[str] = "paused_launch_window"

STATUS_WRITTEN: Final[str] = "WRITTEN"
STATUS_SKIPPED: Final[str] = "SKIPPED"
STATUS_WOULD_FETCH: Final[str] = "WOULD_FETCH"
STATUS_FAILED: Final[str] = "FAILED"


def default_output_dir() -> Path:
    return Path.home().joinpath(*DEFAULT_OUTPUT_DIR_TAIL)


def item_key(item: BackfillPlanItem, stations: frozenset[str]) -> str:
    """Manifest key. The default (4-station) set keeps the legacy key so the
    existing store resumes unchanged; any other set is suffixed with its
    sorted members, so a 4-station item can never satisfy a 5-station one."""
    if stations == DEFAULT_NBM_QUANTILE_STATIONS:
        return item.key
    return f"{item.key}@{'+'.join(sorted(stations))}"


def _parse_stations(raw: str) -> frozenset[str]:
    stations = frozenset(part.strip().upper() for part in raw.split(",") if part.strip())
    if not stations:
        raise ValueError("--stations must name at least one station")
    return stations


def _root_stations(output_dir: Path) -> frozenset[str] | None:
    """The station set a root was stamped with; `None` for an unstamped root."""
    marker = output_dir / STATIONS_MARKER_NAME
    if not marker.exists():
        return None
    return frozenset(json.loads(marker.read_text(encoding="utf-8")))


def _stamp_root(output_dir: Path, stations: frozenset[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / STATIONS_MARKER_NAME).write_text(
        json.dumps(sorted(stations)) + "\n", encoding="utf-8"
    )


class BackfillPlanItem:
    """One unit of work: one NBP cycle, one date. Station-agnostic -- the
    transport always fetches every station in one request."""

    __slots__ = ("cycle_date", "cycle_hour")

    def __init__(self, cycle_date: dt.date, cycle_hour: int) -> None:
        self.cycle_date = cycle_date
        self.cycle_hour = cycle_hour

    @property
    def key(self) -> str:
        return manifest_key(self.cycle_date, self.cycle_hour)

    @property
    def label(self) -> str:
        return f"{self.cycle_date.isoformat()} {self.cycle_hour:02d}Z"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BackfillPlanItem):
            return NotImplemented
        return (self.cycle_date, self.cycle_hour) == (other.cycle_date, other.cycle_hour)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"BackfillPlanItem({self.cycle_date!r}, {self.cycle_hour!r})"


def build_plan(
    *, start: dt.date, end: dt.date, cycles: Sequence[int] = CYCLES
) -> tuple[BackfillPlanItem, ...]:
    """Date-major, cycle-ascending work plan. `end` is INCLUSIVE."""
    if end < start:
        raise ValueError(f"--end {end} precedes --start {start}")
    unknown = [hour for hour in cycles if not (0 <= hour <= 23)]
    if unknown:
        raise ValueError(f"cycle hour(s) {unknown} are not valid UTC hours (0..23)")
    items: list[BackfillPlanItem] = []
    day = start
    while day <= end:
        for hour in cycles:
            items.append(BackfillPlanItem(day, hour))
        day += dt.timedelta(days=1)
    return tuple(items)


def era_for_cycle(cycle_runtime_ns: int) -> str:
    """The NBM version era `NBM_VERSION_BREAKS` expects for a cycle instant,
    read off the cycle's own UTC calendar date (matches how the SL-3 census
    itself classifies a date -- see `VERSION_BREAKS`)."""
    cycle_date = dt.datetime.fromtimestamp(cycle_runtime_ns / 1_000_000_000, tz=dt.UTC).date()
    return version_for(cycle_date)


def derive_rows_for_bulletin(
    *,
    text: str,
    source_host: str,
    last_modified: str | None,
    fetched_at_ns: int,
    raw_sha256: str,
    stations: frozenset[str] = DEFAULT_NBM_QUANTILE_STATIONS,
    log: Callable[[str], None] = lambda _message: None,
) -> tuple[tuple[DerivedNbpRow, ...], int]:
    """Parse one fetched bulletin into `DerivedNbpRow`s. Returns
    `(rows, station_block_missing_count)`. Raises `NbpBulletinDriftError`
    unchanged -- the caller decides how a drifted bulletin is reported."""
    points, drops = parse_nbp_bulletin(text, stations=stations)
    last_modified_dt = parse_http_last_modified(last_modified)
    last_modified_ns = (
        None if last_modified_dt is None else int(last_modified_dt.timestamp() * 1_000_000_000)
    )

    rows: list[DerivedNbpRow] = []
    for point in points:
        expected_era = era_for_cycle(point.cycle_runtime_ns)
        header_era = f"v{point.model_version}"
        mismatch = header_era != expected_era
        if mismatch:
            log(
                f"NBM version mismatch: header reports {header_era!r} for "
                f"{point.station} cycle {point.cycle_runtime_ns}ns, but "
                f"NBM_VERSION_BREAKS expects {expected_era!r} for that cycle's "
                "UTC date; the header wins."
            )
        rows.append(
            DerivedNbpRow(
                station=point.station,
                variable=point.variable,
                cycle_runtime_ns=point.cycle_runtime_ns,
                valid_start_ns=point.valid_start_ns,
                valid_end_ns=point.valid_end_ns,
                value_f=point.value_f,
                absence_reason=point.absence_reason,
                header_model_version=point.model_version,
                nbm_version_era=header_era,
                version_break_mismatch=mismatch,
                available_at_ns=available_at_ns(
                    cycle_runtime_ns=point.cycle_runtime_ns,
                    last_modified_ns=last_modified_ns,
                ),
                last_modified=last_modified,
                source_host=source_host,
                raw_sha256=raw_sha256,
                fetched_at_ns=fetched_at_ns,
            )
        )
    return tuple(rows), drops.get("station_block_missing", 0)


class BackfillRunReport:
    """The whole run, in the shape the operator has to act on."""

    __slots__ = (
        "dry_run",
        "failed",
        "output_dir",
        "requests",
        "skipped",
        "stations",
        "stop_reason",
        "would_fetch",
        "written",
    )

    def __init__(
        self,
        *,
        written: int,
        skipped: int,
        would_fetch: int,
        failed: tuple[str, ...],
        dry_run: bool,
        output_dir: Path,
        stations: frozenset[str] = DEFAULT_NBM_QUANTILE_STATIONS,
        requests: int = 0,
        stop_reason: str | None = None,
    ) -> None:
        self.stations = stations
        self.requests = requests
        self.stop_reason = stop_reason
        self.written = written
        self.skipped = skipped
        self.would_fetch = would_fetch
        self.failed = failed
        self.dry_run = dry_run
        self.output_dir = output_dir

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "output_dir": str(self.output_dir),
            "stations": sorted(self.stations),
            "written": self.written,
            "skipped": self.skipped,
            "would_fetch": self.would_fetch,
            "failed": list(self.failed),
            "requests_charged": self.requests,
            "stop_reason": self.stop_reason,
        }


def run_backfill(
    *,
    plan: Sequence[BackfillPlanItem],
    output_dir: Path,
    transport: NbmQuantileTransport | None,
    runner: asyncio.Runner | None,
    progress: Callable[[str], None],
    clock: Callable[[], int],
    dry_run: bool,
    stations: frozenset[str] = DEFAULT_NBM_QUANTILE_STATIONS,
    request_budget: int | None = None,
    pace_s: float = 0.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> BackfillRunReport:
    """Walk the plan date-major, one (date, cycle) at a time, process-then-
    discard: exactly one fetched bulletin's text is alive at a time.

    A failure (both hosts, or a bulletin the parser refuses) is recorded to
    the failure ledger and NEVER written as a partial or guessed row; the
    run continues to the next item.

    Disciplines: `request_budget` is a hard ceiling charged at the worst case
    (two requests) per item; `pace_s` sleeps between fetches; an item never
    starts when its worst-case span would meet the 16:30-17:10Z launch window
    (the run stops and reports `paused_launch_window`).
    """
    manifest = load_manifest(output_dir)
    written = 0
    skipped = 0
    would_fetch = 0
    failed: list[str] = []
    total = len(plan)
    charged = 0
    stop_reason: str | None = None
    fetched_any = False

    for index, item in enumerate(plan, start=1):
        prefix = f"[{index}/{total}] {item.label}"
        key = item_key(item, stations)
        if key in manifest:
            skipped += 1
            progress(f"{prefix} {STATUS_SKIPPED} (already in manifest)")
            continue

        if dry_run:
            would_fetch += 1
            progress(f"{prefix} {STATUS_WOULD_FETCH}")
            continue

        assert transport is not None and runner is not None  # dry_run False => both required

        if request_budget is not None and (charged + REQUESTS_PER_ITEM_WORST_CASE > request_budget):
            stop_reason = STOP_BUDGET
            progress(f"{prefix} STOPPED request budget {request_budget} exhausted")
            break
        if not launch_window_guard(clock(), 0, ITEM_WORST_CASE_S):
            stop_reason = STOP_WINDOW
            progress(f"{prefix} STOPPED launch window 16:30-17:10Z; resume from this item")
            break
        if fetched_any and pace_s > 0:
            sleeper(pace_s)
        fetched_any = True
        charged += REQUESTS_PER_ITEM_WORST_CASE

        def _log_with_prefix(message: str, *, _prefix: str = prefix) -> None:
            progress(f"{_prefix} {message}")

        try:
            result = runner.run(
                transport.fetch_nbp_bulletin(cycle_date=item.cycle_date, cycle_hour=item.cycle_hour)
            )
        except BothHostsFailedError as exc:
            record_failure(
                output_dir,
                key,
                FailureEntry(
                    cycle_date=item.cycle_date.isoformat(),
                    cycle_hour=item.cycle_hour,
                    primary_error=repr(exc.primary_error),
                    fallback_error=repr(exc.fallback_error),
                    failed_at_ns=clock(),
                ),
            )
            failed.append(item.label)
            progress(f"{prefix} {STATUS_FAILED} both hosts failed: {exc}")
            continue
        except NbmQuantileFetchError as exc:
            record_failure(
                output_dir,
                key,
                FailureEntry(
                    cycle_date=item.cycle_date.isoformat(),
                    cycle_hour=item.cycle_hour,
                    primary_error=repr(exc),
                    fallback_error="",
                    failed_at_ns=clock(),
                ),
            )
            failed.append(item.label)
            progress(f"{prefix} {STATUS_FAILED} {exc}")
            continue

        try:
            rows, missing = derive_rows_for_bulletin(
                text=result.text,
                source_host=result.source_host,
                last_modified=result.last_modified,
                fetched_at_ns=result.fetched_at_ns,
                raw_sha256=result.raw_sha256,
                stations=stations,
                log=_log_with_prefix,
            )
        except NbpBulletinDriftError as exc:
            record_failure(
                output_dir,
                key,
                FailureEntry(
                    cycle_date=item.cycle_date.isoformat(),
                    cycle_hour=item.cycle_hour,
                    primary_error=f"NbpBulletinDriftError: {exc}",
                    fallback_error="",
                    failed_at_ns=clock(),
                ),
            )
            failed.append(item.label)
            progress(f"{prefix} {STATUS_FAILED} bulletin drift: {exc}")
            continue
        del result  # process-then-discard: one bulletin alive at a time

        path = partition_path(output_dir, item.cycle_date, item.cycle_hour)
        write_partition(rows, path)
        record_success(
            output_dir,
            key,
            ManifestEntry(
                cycle_date=item.cycle_date.isoformat(),
                cycle_hour=item.cycle_hour,
                source_host=rows[0].source_host if rows else "",
                raw_sha256=rows[0].raw_sha256 if rows else "",
                rows=len(rows),
                parquet_path=str(path),
                completed_at_ns=clock(),
            ),
        )
        written += 1
        progress(
            f"{prefix} {STATUS_WRITTEN} rows={len(rows)} station_block_missing={missing} "
            f"path={path}"
        )

    return BackfillRunReport(
        written=written,
        skipped=skipped,
        would_fetch=would_fetch,
        failed=tuple(failed),
        dry_run=dry_run,
        output_dir=output_dir,
        stations=stations,
        requests=charged,
        stop_reason=stop_reason,
    )


def render_summary(report: BackfillRunReport) -> str:
    mode = "DRY RUN" if report.dry_run else "RUN"
    lines = [
        f"{mode} nbp_backfill output_dir={report.output_dir}",
        (
            f"  items: {report.written} written, {report.would_fetch} to fetch, "
            f"{report.skipped} already covered, {len(report.failed)} failed"
        ),
    ]
    lines.append(
        f"  stations={','.join(sorted(report.stations))} requests_charged={report.requests}"
    )
    if report.stop_reason:
        lines.append(f"  STOPPED EARLY: {report.stop_reason} (re-run resumes from the manifest)")
    if report.failed:
        lines.append("  FAILED (see _failures.json; never fetched a partial row):")
        lines.extend(f"    {label}" for label in report.failed)
    else:
        lines.append("  no failed items")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--start", required=True, help="First date, inclusive, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Last date, inclusive, YYYY-MM-DD.")
    parser.add_argument("--output-dir", "--out-root", dest="output_dir", default=None, type=Path)
    parser.add_argument(
        "--stations",
        default=",".join(sorted(DEFAULT_NBM_QUANTILE_STATIONS)),
        help="Comma-separated station ids. A non-default set REQUIRES a fresh --out-root.",
    )
    parser.add_argument("--request-budget", type=int, default=None)
    parser.add_argument("--pace-s", type=float, default=DEFAULT_PACE_S)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-json", default=None, type=Path)
    return parser.parse_args(list(argv))


def _write_report(report: BackfillRunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")


def _stderr(line: str) -> None:
    sys.stderr.write(f"{line}\n")


def _refuse(message: str) -> int:
    _stderr(f"REFUSED: {message}")
    return 2


def main(argv: Sequence[str] | None = None, *, clock: Callable[[], int] | None = None) -> int:
    """CLI entry point. `clock` is a keyword-only test seam; production
    resolves it to `time.time_ns`."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    resolved_clock = clock if clock is not None else time.time_ns

    try:
        start = dt.date.fromisoformat(args.start)
        end = dt.date.fromisoformat(args.end)
    except ValueError as exc:
        return _refuse(f"--start/--end must be YYYY-MM-DD: {exc}")

    try:
        plan = build_plan(start=start, end=end)
    except ValueError as exc:
        return _refuse(str(exc))

    try:
        stations = _parse_stations(args.stations)
    except ValueError as exc:
        return _refuse(str(exc))
    default_root = default_output_dir()
    output_dir = args.output_dir if args.output_dir is not None else default_root
    dry_run = args.dry_run or not args.apply

    stamped = _root_stations(output_dir)
    if stations != DEFAULT_NBM_QUANTILE_STATIONS and output_dir.resolve() == default_root.resolve():
        return _refuse(
            "a non-default --stations set may not be written into the default NBP root "
            f"{default_root} (it is evidence for prior studies); pass a fresh --out-root."
        )
    if stamped is not None and stamped != stations:
        return _refuse(
            f"{output_dir} is stamped with stations {sorted(stamped)}; refusing {sorted(stations)}."
        )
    if stamped is None and stations != DEFAULT_NBM_QUANTILE_STATIONS and load_manifest(output_dir):
        return _refuse(f"{output_dir} holds an unstamped (default-station) manifest.")

    if not dry_run:
        if os.environ.get(LIVE_ENV_VAR) != "1":
            return _refuse(
                f"{LIVE_ENV_VAR}=1 is required before this job may dispatch any request. "
                f"Planned items: {len(plan)}. Run with --dry-run first."
            )
        if not os.environ.get(USER_AGENT_ENV_VAR):
            return _refuse(f"{USER_AGENT_ENV_VAR} must name a monitored contact.")
        if not args.request_budget or args.request_budget < 1:
            return _refuse(
                "--request-budget is required for --apply "
                f"(worst case {REQUESTS_PER_ITEM_WORST_CASE} per item x {len(plan)} items)."
            )

    _stderr(
        f"NBP backfill: {len(plan)} item(s) planned ({start}..{end}, cycles={CYCLES}) "
        f"into {output_dir} stations={sorted(stations)}"
    )
    _stderr(
        "dedupe: no-BBB mode (R2-13/R3-08 branch (b) -- BBB correction indicator "
        "verified ABSENT on every real NBP capture examined; ordering degrades to "
        "max(LastModified, raw_sha256))."
    )
    _stderr(f"NBM_VERSION_BREAKS: {VERSION_BREAKS}")

    if dry_run:
        report = run_backfill(
            plan=plan,
            output_dir=output_dir,
            transport=None,
            runner=None,
            progress=_stderr,
            clock=resolved_clock,
            dry_run=True,
            stations=stations,
        )
        sys.stderr.write(render_summary(report))
        if args.report_json is not None:
            _write_report(report, args.report_json)
        return 0

    if stations != DEFAULT_NBM_QUANTILE_STATIONS:
        _stamp_root(output_dir, stations)
    report_path = (
        args.report_json if args.report_json is not None else output_dir / "_run_report.json"
    )
    with asyncio.Runner() as runner:
        transport = NbmQuantileTransport(
            clock=resolved_clock,
            stations=stations,
            user_agent=os.environ[USER_AGENT_ENV_VAR],
        )
        report = run_backfill(
            plan=plan,
            output_dir=output_dir,
            transport=transport,
            runner=runner,
            progress=_stderr,
            clock=resolved_clock,
            dry_run=False,
            stations=stations,
            request_budget=args.request_budget,
            pace_s=args.pace_s,
        )
    sys.stderr.write(render_summary(report))
    _write_report(report, report_path)
    return 1 if report.failed or report.stop_reason else 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
