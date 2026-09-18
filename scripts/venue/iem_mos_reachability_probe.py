#!/usr/bin/env python
"""IEM MOS (NBS/GFS) reachability probe (FC-0a-1).

EVIDENCE ONLY -- NEVER INGEST. Per-step summaries carry a ``.summary.json``
suffix; ``record()`` is called with ``text=None`` so no ``.probe.json``
payload is written.

The mos.py query grammar is UNVERIFIED until the first live GET. A 200 is
not reachability: row counts, distinct runtime days, and the two-tier
60/300/3-year gate decide the verdict.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import io
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from breezy.ingest.http import OversizeBodyError, RedirectError, TransportError
from breezy.ingest.iem_mos_probe_transport import (
    IEM_ALLOWED_HOSTS,
    IEM_HOST,
    IEM_MOS_PROBE_MAX_BODY_BYTES,
    IEM_MOS_STATION_ORDER,
    IemMosProbeTransport,
    IemPacer,
    exchange_from_alarm,
    exchange_from_result,
    utc_stamp,
)
from breezy.ingest.probe_transport import (
    ProbeEvidenceWriter,
    ProbeExchange,
    RequestBudget,
    RequestBudgetExceededError,
)

ALLOWED_HOSTS: frozenset[str] = IEM_ALLOWED_HOSTS

LIVE_ENV_VAR: str = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: str = "BREEZY_USER_AGENT"

STATIONS: tuple[str, ...] = IEM_MOS_STATION_ORDER
MODELS: tuple[str, ...] = ("NBS", "GFS")
FIRST_YEAR: int = 2021

REQUEST_BUDGET: int = 56
OVERSIZE_RESPLIT_RESERVE: int = 8

MIN_NBS_DISTINCT_RUNTIME_DAYS_PER_COMPLETE_YEAR: int = 300
MIN_NBS_DISTINCT_RUNTIME_DAYS_HARD_FLOOR: int = 60
MIN_NBS_COMPLETE_YEARS_AT_FLOOR: int = 3
CURRENT_YEAR_RECENCY_DAYS: int = 14

_NANOSECONDS_PER_SECOND: int = 1_000_000_000

SUMMARY_KEYS: tuple[str, ...] = (
    "label",
    "url",
    "outcome",
    "finding",
    "content_type",
    "status",
    "sha256",
    "body_bytes",
    "row_count",
    "distinct_runtime_days",
    "first_runtime",
    "last_runtime",
    "csv_header_line",
    "sample_row_1",
    "sample_row_2",
)

_RUNTIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%MZ",
    "%Y-%m-%d",
)


@dataclass(frozen=True, slots=True)
class ProbeStep:
    label: str
    station: str
    model: str
    year: int
    sts: str
    ets: str


@dataclass(frozen=True, slots=True)
class MosCensus:
    row_count: int
    distinct_runtime_days: int
    first_runtime: str | None
    last_runtime: str | None
    csv_header_line: str | None
    sample_row_1: str | None
    sample_row_2: str | None
    parse_ok: bool = True


@dataclass(frozen=True, slots=True)
class YearCell:
    station: str
    model: str
    year: int
    label: str
    exchange: ProbeExchange
    census: MosCensus | None
    resplit: bool = False
    body_bytes: int = 0


@dataclass(frozen=True, slots=True)
class Verdict:
    passed: bool
    failures: tuple[str, ...]
    findings: tuple[str, ...]
    optional_failures: tuple[str, ...]
    optional_findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    cells: tuple[YearCell, ...]
    aborted: str | None
    skipped: tuple[str, ...]


def _clock_datetime(clock: Callable[[], int]) -> dt.datetime:
    return dt.datetime.fromtimestamp(clock() / _NANOSECONDS_PER_SECOND, tz=dt.UTC)


def _parse_runtime(value: str) -> dt.datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in _RUNTIME_FORMATS:
        try:
            parsed = dt.datetime.strptime(text, fmt).replace(tzinfo=dt.UTC)
        except ValueError:
            continue
        return parsed
    return None


def build_request_plan(*, clock: Callable[[], int]) -> tuple[ProbeStep, ...]:
    now = _clock_datetime(clock)
    steps: list[ProbeStep] = []
    for model in MODELS:
        for station in STATIONS:
            for year in range(FIRST_YEAR, now.year + 1):
                sts = f"{year}-01-01T00:00Z"
                if year == now.year:
                    ets = now.strftime("%Y-%m-%dT%H:%MZ")
                else:
                    ets = f"{year}-12-31T23:59Z"
                steps.append(
                    ProbeStep(
                        label=f"{model.lower()}_{station.lower()}_{year}",
                        station=station,
                        model=model,
                        year=year,
                        sts=sts,
                        ets=ets,
                    )
                )
    return tuple(steps)


def parse_mos_csv_census(text: str) -> MosCensus:
    """Census distinct runtime calendar days from a MOS CSV body. Process, then discard."""
    empty = MosCensus(0, 0, None, None, None, None, None, True)
    stripped = text.lstrip()
    if not stripped:
        return empty
    if stripped.startswith("<") or stripped.upper().startswith("ERROR"):
        return empty
    lines = text.splitlines()
    if not lines:
        return empty
    header_line = lines[0]
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return empty
    runtime_idx: int | None = None
    for index, name in enumerate(header):
        if name.strip().lower() == "runtime":
            runtime_idx = index
            break
    data_lines = [line for line in lines[1:] if line.strip()]
    sample_1 = data_lines[0] if data_lines else None
    sample_2 = data_lines[1] if len(data_lines) > 1 else None
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return MosCensus(0, 0, None, None, header_line, None, None, True)
    if runtime_idx is None:
        return MosCensus(
            len(rows), 0, None, None, header_line, sample_1, sample_2, False
        )
    parsed: list[tuple[dt.datetime, str]] = []
    for row in rows:
        if runtime_idx >= len(row):
            return MosCensus(
                len(rows), 0, None, None, header_line, sample_1, sample_2, False
            )
        raw = row[runtime_idx]
        instant = _parse_runtime(raw)
        if instant is None:
            return MosCensus(
                len(rows), 0, None, None, header_line, sample_1, sample_2, False
            )
        parsed.append((instant, raw))
    parsed.sort(key=lambda item: item[0])
    days = {item[0].date() for item in parsed}
    return MosCensus(
        row_count=len(rows),
        distinct_runtime_days=len(days),
        first_runtime=parsed[0][1],
        last_runtime=parsed[-1][1],
        csv_header_line=header_line,
        sample_row_1=sample_1,
        sample_row_2=sample_2,
        parse_ok=True,
    )


def _covers_year(census: MosCensus, year: int) -> bool:
    if census.first_runtime is None or census.last_runtime is None:
        return False
    first = _parse_runtime(census.first_runtime)
    last = _parse_runtime(census.last_runtime)
    if first is None or last is None:
        return False
    return first.date() <= dt.date(year, 1, 1) and last.date() >= dt.date(year, 12, 31)


def evaluate_verdict(cells: Sequence[YearCell], *, clock: Callable[[], int]) -> Verdict:
    now = _clock_datetime(clock)
    clock_date = now.date()
    years = tuple(range(FIRST_YEAR, now.year + 1))
    by_key: dict[tuple[str, str, int], YearCell] = {
        (cell.station, cell.model, cell.year): cell for cell in cells
    }
    failures: list[str] = []
    findings: list[str] = []
    optional_failures: list[str] = []
    optional_findings: list[str] = []

    def _record(model: str, message: str, *, fail: bool) -> None:
        if model == "NBS":
            (failures if fail else findings).append(message)
        else:
            (optional_failures if fail else optional_findings).append(message)

    hard_floor = MIN_NBS_DISTINCT_RUNTIME_DAYS_HARD_FLOOR
    day_floor = MIN_NBS_DISTINCT_RUNTIME_DAYS_PER_COMPLETE_YEAR
    recency_days = CURRENT_YEAR_RECENCY_DAYS
    for model in MODELS:
        for station in STATIONS:
            years_at_floor = 0
            for year in years:
                cell = by_key.get((station, model, year))
                complete = year < now.year
                if cell is None or cell.census is None or not cell.census.parse_ok:
                    reason = "has no cell"
                    if cell is not None and cell.census is not None and not cell.census.parse_ok:
                        reason = "is unparseable"
                    elif cell is not None and cell.exchange.outcome not in {"ok"}:
                        reason = f"has no cell ({cell.exchange.outcome})"
                    _record(model, f"absent year: {station} {year} {model} {reason}", fail=True)
                    continue
                census = cell.census
                days = census.distinct_runtime_days
                if cell.resplit:
                    _record(
                        model,
                        f"oversize resplit: {station} {year} {model} re-measured in halves",
                        fail=False,
                    )
                if complete and census.row_count == 0:
                    _record(
                        model,
                        f"absent year: {station} {year} {model} has zero parseable rows",
                        fail=True,
                    )
                    continue
                if complete and days < hard_floor:
                    _record(
                        model,
                        (
                            f"hard floor: {station} {year} {model} "
                            f"distinct_runtime_days={days} < {hard_floor}"
                        ),
                        fail=True,
                    )
                elif complete and days < day_floor:
                    _record(
                        model,
                        (
                            f"partial year: {station} {year} {model} "
                            f"distinct_runtime_days={days} < {day_floor}"
                        ),
                        fail=False,
                    )
                if complete and not _covers_year(census, year):
                    _record(
                        model,
                        f"partial year: {station} {year} {model} first/last do not cover the year",
                        fail=False,
                    )
                if complete and days >= day_floor:
                    years_at_floor += 1
                if year == now.year:
                    last = _parse_runtime(census.last_runtime or "")
                    cutoff = clock_date - dt.timedelta(days=recency_days)
                    if last is None or last.date() < cutoff:
                        _record(
                            model,
                            (
                                f"stale current year: {station} {year} {model} last_runtime "
                                f"{census.last_runtime} is older than {recency_days} days"
                            ),
                            fail=True,
                        )
                    elapsed = (clock_date - dt.date(year, 1, 1)).days + 1
                    if census.distinct_runtime_days < elapsed:
                        _record(
                            model,
                            (
                                f"interior gaps: {station} {year} {model} distinct_runtime_days="
                                f"{census.distinct_runtime_days} < {elapsed} elapsed days"
                            ),
                            fail=False,
                        )
            if years_at_floor < MIN_NBS_COMPLETE_YEARS_AT_FLOOR:
                _record(
                    model,
                    (
                        f"{station} {model} has {years_at_floor} complete years at >= "
                        f"{MIN_NBS_DISTINCT_RUNTIME_DAYS_PER_COMPLETE_YEAR} distinct runtime days; "
                        f"{MIN_NBS_COMPLETE_YEARS_AT_FLOOR} required"
                    ),
                    fail=True,
                )
    return Verdict(
        passed=not failures,
        failures=tuple(failures),
        findings=tuple(findings),
        optional_failures=tuple(optional_failures),
        optional_findings=tuple(optional_findings),
    )


def _summary_payload(exchange: ProbeExchange, census: MosCensus | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": exchange.label,
        "url": exchange.url,
        "outcome": exchange.outcome,
        "finding": exchange.finding,
        "content_type": exchange.content_type,
        "status": exchange.status_code,
        "sha256": exchange.sha256,
        "body_bytes": exchange.body_bytes,
        "row_count": None if census is None else census.row_count,
        "distinct_runtime_days": None if census is None else census.distinct_runtime_days,
        "first_runtime": None if census is None else census.first_runtime,
        "last_runtime": None if census is None else census.last_runtime,
        "csv_header_line": None if census is None else census.csv_header_line,
        "sample_row_1": None if census is None else census.sample_row_1,
        "sample_row_2": None if census is None else census.sample_row_2,
    }
    assert set(payload) == set(SUMMARY_KEYS)
    return payload


def _write_summary(
    writer: ProbeEvidenceWriter, exchange: ProbeExchange, census: MosCensus | None
) -> None:
    writer.write_report(
        f"{exchange.label}.summary.json",
        json.dumps(_summary_payload(exchange, census), indent=2, sort_keys=True),
    )


def _merge_censuses(first: MosCensus, second: MosCensus) -> MosCensus:
    if not first.parse_ok or not second.parse_ok:
        return MosCensus(0, 0, None, None, None, None, None, False)
    firsts = [value for value in (first.first_runtime, second.first_runtime) if value]
    lasts = [value for value in (first.last_runtime, second.last_runtime) if value]
    max_dt = dt.datetime.max.replace(tzinfo=dt.UTC)
    min_dt = dt.datetime.min.replace(tzinfo=dt.UTC)
    first_runtime = min(firsts, key=lambda raw: _parse_runtime(raw) or max_dt) if firsts else None
    last_runtime = max(lasts, key=lambda raw: _parse_runtime(raw) or min_dt) if lasts else None
    return MosCensus(
        row_count=first.row_count + second.row_count,
        distinct_runtime_days=first.distinct_runtime_days + second.distinct_runtime_days,
        first_runtime=first_runtime,
        last_runtime=last_runtime,
        csv_header_line=first.csv_header_line or second.csv_header_line,
        sample_row_1=first.sample_row_1 or second.sample_row_1,
        sample_row_2=first.sample_row_2 or second.sample_row_2,
        parse_ok=True,
    )


async def _dispatch(
    transport: IemMosProbeTransport,
    writer: ProbeEvidenceWriter,
    *,
    label: str,
    station: str,
    model: str,
    year: int,
    sts: str,
    ets: str,
    clock: Callable[[], int],
) -> YearCell:
    url = transport._mos_url(station, model, sts, ets)
    try:
        result = await transport.fetch_mos_csv(station, model, sts, ets)
    except RequestBudgetExceededError:
        raise
    except (RedirectError, OversizeBodyError, TransportError) as exc:
        exchange = exchange_from_alarm(
            label=label,
            url=url,
            error=exc,
            ordinal=transport.budget.spent,
            requested_at_utc=utc_stamp(clock),
        )
        writer.record(label, exchange)
        _write_summary(writer, exchange, None)
        return YearCell(
            station=station,
            model=model,
            year=year,
            label=label,
            exchange=exchange,
            census=None,
            body_bytes=0,
        )
    exchange = exchange_from_result(
        label=label,
        url=url,
        result=result,
        ordinal=transport.budget.spent,
        requested_at_utc=utc_stamp(clock),
    )
    census = parse_mos_csv_census(result.text or "") if exchange.succeeded else None
    writer.record(label, exchange)
    _write_summary(writer, exchange, census)
    return YearCell(
        station=station,
        model=model,
        year=year,
        label=label,
        exchange=exchange,
        census=census,
        body_bytes=exchange.body_bytes,
    )


def _half_windows(year: int, clock: Callable[[], int]) -> tuple[tuple[str, str], tuple[str, str]]:
    now = _clock_datetime(clock)
    first = (f"{year}-01-01T00:00Z", f"{year}-06-30T23:59Z")
    if year == now.year:
        second = (f"{year}-07-01T00:00Z", now.strftime("%Y-%m-%dT%H:%MZ"))
    else:
        second = (f"{year}-07-01T00:00Z", f"{year}-12-31T23:59Z")
    return first, second


async def execute(
    transport: IemMosProbeTransport,
    writer: ProbeEvidenceWriter,
    plan: Sequence[ProbeStep],
    *,
    clock: Callable[[], int],
) -> ExecutionResult:
    cells: list[YearCell] = []
    aborted: str | None = None
    skipped: tuple[str, ...] = ()
    resplit_remaining = OVERSIZE_RESPLIT_RESERVE
    for index, step in enumerate(plan):
        try:
            cell = await _dispatch(
                transport,
                writer,
                label=step.label,
                station=step.station,
                model=step.model,
                year=step.year,
                sts=step.sts,
                ets=step.ets,
                clock=clock,
            )
        except RequestBudgetExceededError as exc:
            aborted = f"Budget exhausted before `{step.label}`: {exc}"
            skipped = tuple(later.label for later in plan[index:])
            break
        if cell.exchange.outcome == "error:OversizeBodyError":
            if resplit_remaining < 2 or transport.budget.remaining < 2:
                cells.append(cell)
                continue
            first_window, second_window = _half_windows(step.year, clock)
            try:
                first_half = await _dispatch(
                    transport,
                    writer,
                    label=f"{step.label}_h1",
                    station=step.station,
                    model=step.model,
                    year=step.year,
                    sts=first_window[0],
                    ets=first_window[1],
                    clock=clock,
                )
                second_half = await _dispatch(
                    transport,
                    writer,
                    label=f"{step.label}_h2",
                    station=step.station,
                    model=step.model,
                    year=step.year,
                    sts=second_window[0],
                    ets=second_window[1],
                    clock=clock,
                )
            except RequestBudgetExceededError as exc:
                aborted = f"Budget exhausted during oversize resplit of `{step.label}`: {exc}"
                skipped = tuple(later.label for later in plan[index + 1 :])
                cells.append(cell)
                break
            resplit_remaining -= 2
            if (
                first_half.census is None
                or second_half.census is None
                or first_half.exchange.outcome == "error:OversizeBodyError"
                or second_half.exchange.outcome == "error:OversizeBodyError"
            ):
                cells.append(cell)
                continue
            cells.append(
                YearCell(
                    station=step.station,
                    model=step.model,
                    year=step.year,
                    label=step.label,
                    exchange=cell.exchange,
                    census=_merge_censuses(first_half.census, second_half.census),
                    resplit=True,
                    body_bytes=first_half.body_bytes + second_half.body_bytes,
                )
            )
            continue
        cells.append(cell)
    return ExecutionResult(cells=tuple(cells), aborted=aborted, skipped=skipped)


def _station_span(
    cells: Sequence[YearCell], station: str, *, model: str = "NBS"
) -> tuple[dt.datetime, dt.datetime] | None:
    instants: list[dt.datetime] = []
    lasts: list[dt.datetime] = []
    for cell in cells:
        if cell.station != station or cell.model != model or cell.census is None:
            continue
        first = _parse_runtime(cell.census.first_runtime or "")
        last = _parse_runtime(cell.census.last_runtime or "")
        if first is not None:
            instants.append(first)
        if last is not None:
            lasts.append(last)
    if not instants or not lasts:
        return None
    return min(instants), max(lasts)


def render_report(
    cells: Sequence[YearCell],
    verdict: Verdict,
    *,
    budget: RequestBudget,
    plan: Sequence[ProbeStep],
    clock: Callable[[], int],
    max_body_bytes_measured: int,
) -> str:
    lines: list[str] = [
        "# IEM MOS (NBS/GFS) reachability probe (FC-0a-1)",
        "",
        "## EVIDENCE ONLY - NEVER INGEST",
        "",
        "These captures must NEVER be ingested into any production catalog.",
        "",
        f"Host: `{IEM_HOST}` (settlement host NOT touched)",
        (
            "Transport: `breezy.ingest.iem_mos_probe_transport.IemMosProbeTransport`, "
            f"max_body_bytes={IEM_MOS_PROBE_MAX_BODY_BYTES}"
        ),
        f"Request budget: {budget.limit} hard; spent {budget.spent}.",
        f"Planned steps: {len(plan)}; year-cells: {len(cells)}.",
        f"max_body_bytes_measured: {max_body_bytes_measured}",
        "",
        "## Per-station NBS spans",
        "",
    ]
    spans: dict[str, tuple[dt.datetime, dt.datetime]] = {}
    for station in STATIONS:
        span = _station_span(cells, station)
        if span is None:
            lines.append(f"- `{station}`: no NBS span")
            continue
        spans[station] = span
        station_cells = [cell for cell in cells if cell.station == station and cell.model == "NBS"]
        total_rows = sum(cell.census.row_count for cell in station_cells if cell.census is not None)
        lines.append(
            f"- `{station}` first={span[0].isoformat()} last={span[1].isoformat()} "
            f"total_rows={total_rows}"
        )
        for cell in station_cells:
            if cell.census is None:
                continue
            lines.append(
                f"  - {cell.year}: rows={cell.census.row_count} "
                f"distinct_runtime_days={cell.census.distinct_runtime_days} "
                f"first={cell.census.first_runtime} last={cell.census.last_runtime}"
            )
    lines.extend(["", "## Four-station INTERSECTION span", ""])
    if len(spans) == len(STATIONS):
        intersection_first = max(span[0] for span in spans.values())
        intersection_last = min(span[1] for span in spans.values())
        if intersection_first <= intersection_last:
            lines.append(
                f"INTERSECTION: {intersection_first.isoformat()} .. {intersection_last.isoformat()}"
            )
        else:
            lines.append("INTERSECTION: none (station spans do not overlap)")
    else:
        lines.append("INTERSECTION: none (a station is missing a span)")
    if verdict.findings:
        lines.extend(["", "## Findings", ""])
        lines.extend(f"- {finding}" for finding in verdict.findings)
    if verdict.optional_failures or verdict.optional_findings:
        lines.extend(["", "## GFS (optional)", ""])
        lines.extend(f"- OPTIONAL-FAIL: {item}" for item in verdict.optional_failures)
        lines.extend(f"- OPTIONAL-FINDING: {item}" for item in verdict.optional_findings)
    if verdict.failures:
        lines.extend(["", "## Failing clauses", ""])
        lines.extend(f"- {failure}" for failure in verdict.failures)
    lines.extend(["", f"VERDICT: {'PASS' if verdict.passed else 'FAIL'}"])
    return "\n".join(lines) + "\n"


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Refuses to dispatch without the explicit live unlock."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    planned = 48
    if os.environ.get(LIVE_ENV_VAR) != "1":
        sys.stderr.write(
            f"REFUSED: {LIVE_ENV_VAR}=1 is required before this probe may dispatch "
            f"any request. Planned steps: at most {planned} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not args.apply:
        sys.stderr.write(
            f"REFUSED: --apply is required. Planned steps: at most {planned} "
            f"(budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not os.environ.get(USER_AGENT_ENV_VAR):
        sys.stderr.write(f"REFUSED: {USER_AGENT_ENV_VAR} must name a monitored contact.\n")
        return 2

    clock = time.time_ns
    plan = build_request_plan(clock=clock)
    budget = RequestBudget(limit=REQUEST_BUDGET)
    transport = IemMosProbeTransport(
        budget=budget,
        pacer=IemPacer(clock=clock, sleeper=asyncio.sleep),
        user_agent=os.environ[USER_AGENT_ENV_VAR],
        clock=clock,
    )
    writer = ProbeEvidenceWriter(Path(args.output_directory))
    execution = asyncio.run(execute(transport, writer, plan, clock=clock))
    verdict = evaluate_verdict(execution.cells, clock=clock)
    max_body = max((cell.body_bytes for cell in execution.cells), default=0)
    writer.write_report(
        "PROBE_REPORT.md",
        render_report(
            execution.cells,
            verdict,
            budget=budget,
            plan=plan,
            clock=clock,
            max_body_bytes_measured=max_body,
        ),
    )
    sys.stderr.write(
        f"IEM MOS probe finished: {budget.spent}/{budget.limit} requests spent, "
        f"{len(execution.cells)} year-cells, VERDICT={'PASS' if verdict.passed else 'FAIL'}.\n"
    )
    if execution.aborted is not None:
        return 1
    return 0 if verdict.passed else 3


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
