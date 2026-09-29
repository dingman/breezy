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

STATUS_WRITTEN: Final[str] = "WRITTEN"
STATUS_SKIPPED: Final[str] = "SKIPPED"
STATUS_WOULD_FETCH: Final[str] = "WOULD_FETCH"
STATUS_FAILED: Final[str] = "FAILED"


def default_output_dir() -> Path:
    return Path.home().joinpath(*DEFAULT_OUTPUT_DIR_TAIL)


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
    cycle_date = dt.datetime.fromtimestamp(
        cycle_runtime_ns / 1_000_000_000, tz=dt.UTC
    ).date()
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

    __slots__ = ("dry_run", "failed", "output_dir", "skipped", "would_fetch", "written")

    def __init__(
        self,
        *,
        written: int,
        skipped: int,
        would_fetch: int,
        failed: tuple[str, ...],
        dry_run: bool,
        output_dir: Path,
    ) -> None:
        self.written = written
        self.skipped = skipped
        self.would_fetch = would_fetch
        self.failed = failed
        self.dry_run = dry_run
        self.output_dir = output_dir


def run_backfill(
    *,
    plan: Sequence[BackfillPlanItem],
    output_dir: Path,
    transport: NbmQuantileTransport | None,
    runner: asyncio.Runner | None,
    progress: Callable[[str], None],
    clock: Callable[[], int],
    dry_run: bool,
) -> BackfillRunReport:
    """Walk the plan date-major, one (date, cycle) at a time, process-then-
    discard: exactly one fetched bulletin's text is alive at a time.

    A failure (both hosts, or a bulletin the parser refuses) is recorded to
    the failure ledger and NEVER written as a partial or guessed row; the
    run continues to the next item.
    """
    manifest = load_manifest(output_dir)
    written = 0
    skipped = 0
    would_fetch = 0
    failed: list[str] = []
    total = len(plan)

    for index, item in enumerate(plan, start=1):
        prefix = f"[{index}/{total}] {item.label}"
        if item.key in manifest:
            skipped += 1
            progress(f"{prefix} {STATUS_SKIPPED} (already in manifest)")
            continue

        if dry_run:
            would_fetch += 1
            progress(f"{prefix} {STATUS_WOULD_FETCH}")
            continue

        assert transport is not None and runner is not None  # dry_run False => both required

        def _log_with_prefix(message: str, *, _prefix: str = prefix) -> None:
            progress(f"{_prefix} {message}")

        try:
            result = runner.run(
                transport.fetch_nbp_bulletin(cycle_date=item.cycle_date, cycle_hour=item.cycle_hour)
            )
        except BothHostsFailedError as exc:
            record_failure(
                output_dir,
                item.key,
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
                item.key,
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
                log=_log_with_prefix,
            )
        except NbpBulletinDriftError as exc:
            record_failure(
                output_dir,
                item.key,
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
            item.key,
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
    parser.add_argument("--output-dir", default=None, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report-json", default=None, type=Path)
    return parser.parse_args(list(argv))


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

    output_dir = args.output_dir if args.output_dir is not None else default_output_dir()
    dry_run = args.dry_run or not args.apply

    if not dry_run:
        if os.environ.get(LIVE_ENV_VAR) != "1":
            return _refuse(
                f"{LIVE_ENV_VAR}=1 is required before this job may dispatch any request. "
                f"Planned items: {len(plan)}. Run with --dry-run first."
            )
        if not os.environ.get(USER_AGENT_ENV_VAR):
            return _refuse(f"{USER_AGENT_ENV_VAR} must name a monitored contact.")

    _stderr(
        f"NBP backfill: {len(plan)} item(s) planned ({start}..{end}, cycles={CYCLES}) "
        f"into {output_dir}"
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
        )
        sys.stderr.write(render_summary(report))
        return 0

    exit_code = 0
    with asyncio.Runner() as runner:
        transport = NbmQuantileTransport(
            clock=resolved_clock,
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
        )
    sys.stderr.write(render_summary(report))
    if report.failed:
        exit_code = 1
    return exit_code


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
