#!/usr/bin/env python
"""IEM MOS NBS TXN occupancy measurement (FC-0a TXN occupancy).

EVIDENCE ONLY -- NEVER INGEST. Answers the question WP-4 could not: how often
is the MOS `txn` (max/min temperature) element actually populated, by
`ftime`/`runtime` UTC hour, and what does `xnd` carry when it is. WP-1's
reachability probe only ever inspected `sample_row_1`/`sample_row_2` per
year-cell -- both always the shortest projection (06Z/09Z) -- so it could
never have observed `txn` regardless of whether the field is populated
elsewhere. This probe fetches full NBS bodies (one request per station, four
total) and censuses every row.

Uses the SAME sanctioned transport as `iem_mos_reachability_probe.py`
(`IemMosProbeTransport` / `IemPacer`, paced >= 1 req/s, IEM_ALLOWED_HOSTS
only). Parsing/aggregation is delegated to the pure, independently-tested
`scripts/analysis/mos_txn_occupancy.py` -- this module owns only the network
dispatch and evidence write-out.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from breezy.ingest.http import OversizeBodyError, RedirectError, TransportError
from breezy.ingest.probe_transport import (
    ProbeEvidenceWriter,
    ProbeExchange,
    RequestBudgetExceededError,
)

_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(_SCRIPT_DIRECTORY) not in sys.path:  # pragma: no cover - bootstrap
    sys.path.insert(0, str(_SCRIPT_DIRECTORY))

_ANALYSIS_DIRECTORY = _SCRIPT_DIRECTORY.parent / "analysis"
if str(_ANALYSIS_DIRECTORY) not in sys.path:  # pragma: no cover - bootstrap
    sys.path.insert(0, str(_ANALYSIS_DIRECTORY))

from iem_mos_probe_transport import (  # noqa: E402
    IEM_MOS_STATION_ORDER,
    IemMosProbeTransport,
    IemPacer,
    exchange_from_alarm,
    exchange_from_result,
    utc_stamp,
)
from mos_txn_occupancy import (  # noqa: E402
    occupancy_by_ftime_hour,
    occupancy_by_runtime_hour,
    parse_mos_txn_rows,
    xnd_value_counts_for_nonempty_txn,
)

LIVE_ENV_VAR: str = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: str = "BREEZY_USER_AGENT"

STATIONS: tuple[str, ...] = IEM_MOS_STATION_ORDER
MODEL: str = "NBS"

#: One request per station -- exactly the request count declared before
#: this probe was run (see docs/evidence/FC_0a_TXN_OCCUPANCY_2026-09-19.md).
REQUEST_BUDGET: int = 4

#: A single station-month is generous for occupancy characterisation
#: (4 cycles/day x ~30 days x up to ~28 projections = several thousand
#: rows/station); this stays well inside that.
LOOKBACK_DAYS: int = 40

_EXAMPLE_ROWS_PER_STATION: int = 3

_NANOSECONDS_PER_SECOND: int = 1_000_000_000


@dataclass(frozen=True, slots=True)
class StationResult:
    station: str
    outcome: str
    row_count: int
    occupancy_by_ftime: dict
    occupancy_by_runtime: dict
    xnd_counts: dict
    example_populated_rows: tuple[str, ...]


def _clock_datetime(clock) -> dt.datetime:
    return dt.datetime.fromtimestamp(clock() / _NANOSECONDS_PER_SECOND, tz=dt.UTC)


def _window(clock) -> tuple[str, str]:
    now = _clock_datetime(clock)
    start = now - dt.timedelta(days=LOOKBACK_DAYS)
    return start.strftime("%Y-%m-%dT%H:%MZ"), now.strftime("%Y-%m-%dT%H:%MZ")


async def _fetch_station(
    transport: IemMosProbeTransport,
    writer: ProbeEvidenceWriter,
    *,
    station: str,
    sts: str,
    ets: str,
    clock,
) -> StationResult:
    label = f"nbs_txn_occupancy_{station.lower()}"
    url = transport._mos_url(station, MODEL, sts, ets)
    try:
        result = await transport.fetch_mos_csv(station, MODEL, sts, ets)
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
        return StationResult(station, exchange.outcome, 0, {}, {}, {}, ())
    base_exchange = exchange_from_result(
        label=label,
        url=url,
        result=result,
        ordinal=transport.budget.spent,
        requested_at_utc=utc_stamp(clock),
    )
    # `exchange_from_result` always sets `text=None` (its docstring: "`text`
    # is always None") -- correct for the reachability probe, which discards
    # payloads by design. This measurement needs the body, so build the
    # exchange this writer records WITH `text` populated on success: the
    # directory this writer targets is the EVIDENCE ONLY / NEVER INGEST
    # capture area (README written at construction), not a production
    # catalog path, and `record()` already trims/marks oversize bodies.
    exchange = (
        ProbeExchange(
            ordinal=base_exchange.ordinal,
            requested_at_utc=base_exchange.requested_at_utc,
            label=base_exchange.label,
            url=base_exchange.url,
            status_code=base_exchange.status_code,
            body_bytes=base_exchange.body_bytes,
            content_type=base_exchange.content_type,
            outcome=base_exchange.outcome,
            sha256=base_exchange.sha256,
            text=result.text,
            finding=base_exchange.finding,
        )
        if base_exchange.succeeded
        else base_exchange
    )
    writer.record(label, exchange)
    if not exchange.succeeded:
        return StationResult(station, exchange.outcome, 0, {}, {}, {}, ())
    rows = parse_mos_txn_rows(result.text or "")
    by_ftime = occupancy_by_ftime_hour(rows)
    by_runtime = occupancy_by_runtime_hour(rows)
    xnd_counts = xnd_value_counts_for_nonempty_txn(rows)
    examples = tuple(
        f"runtime={row.runtime} ftime={row.ftime} txn={row.txn} xnd={row.xnd}"
        for row in rows
        if row.txn_present
    )[:_EXAMPLE_ROWS_PER_STATION]
    return StationResult(
        station=station,
        outcome=exchange.outcome,
        row_count=len(rows),
        occupancy_by_ftime={
            hour: {"total": bucket.total, "non_empty": bucket.non_empty}
            for hour, bucket in sorted(by_ftime.items())
        },
        occupancy_by_runtime={
            hour: {"total": bucket.total, "non_empty": bucket.non_empty}
            for hour, bucket in sorted(by_runtime.items())
        },
        xnd_counts=dict(sorted(xnd_counts.items())),
        example_populated_rows=examples,
    )


async def execute(
    transport: IemMosProbeTransport,
    writer: ProbeEvidenceWriter,
    *,
    sts: str,
    ets: str,
    clock,
) -> tuple[StationResult, ...]:
    results: list[StationResult] = []
    for station in STATIONS:
        results.append(
            await _fetch_station(transport, writer, station=station, sts=sts, ets=ets, clock=clock)
        )
    return tuple(results)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if os.environ.get(LIVE_ENV_VAR) != "1":
        sys.stderr.write(
            f"REFUSED: {LIVE_ENV_VAR}=1 is required before this probe may dispatch "
            f"any request. Planned steps: {len(STATIONS)} (budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not args.apply:
        sys.stderr.write(
            f"REFUSED: --apply is required. Planned steps: {len(STATIONS)} "
            f"(budget {REQUEST_BUDGET}).\n"
        )
        return 2
    if not os.environ.get(USER_AGENT_ENV_VAR):
        sys.stderr.write(f"REFUSED: {USER_AGENT_ENV_VAR} must name a monitored contact.\n")
        return 2

    from breezy.ingest.probe_transport import RequestBudget

    clock = time.time_ns
    sts, ets = _window(clock)
    budget = RequestBudget(limit=REQUEST_BUDGET)
    transport = IemMosProbeTransport(
        budget=budget,
        pacer=IemPacer(clock=clock, sleeper=asyncio.sleep),
        user_agent=os.environ[USER_AGENT_ENV_VAR],
        clock=clock,
    )
    writer = ProbeEvidenceWriter(Path(args.output_directory))
    results = asyncio.run(execute(transport, writer, sts=sts, ets=ets, clock=clock))
    payload = {
        "window": {"sts": sts, "ets": ets},
        "budget": {"limit": budget.limit, "spent": budget.spent},
        "stations": {
            r.station: {
                "outcome": r.outcome,
                "row_count": r.row_count,
                "occupancy_by_ftime_hour": r.occupancy_by_ftime,
                "occupancy_by_runtime_hour": r.occupancy_by_runtime,
                "xnd_value_counts_for_nonempty_txn": r.xnd_counts,
                "example_populated_rows": list(r.example_populated_rows),
            }
            for r in results
        },
    }
    writer.write_report("TXN_OCCUPANCY_SUMMARY.json", json.dumps(payload, indent=2, sort_keys=True))
    sys.stderr.write(
        f"IEM MOS TXN occupancy probe finished: {budget.spent}/{budget.limit} requests spent.\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
