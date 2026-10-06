"""F13 Phase B0 release census (read-only, memory-capped).

Builds, for the B0 power pre-registration and the B1 release-timing design:

* the PFM WMO issuance times per WFO, read from the ``us-pfm-afos`` archive the live
  collector (and the backfill) write -- the anchor of each issuance is its WMO header time,
  which is the archive key's ``window_start``;
* the NBP measured vintages from the node catalog's ``ForecastPoint`` ``NBM_NBP`` rows
  (R29, the B0 vintage check). Absent rows are reported as absent, never invented;
* the LAMP nominal HH30 run times with the conservative 60-minute lag, until C1 has data.

READ-ONLY. It opens no network connection, reads no settlement, climate-summary or model
value, and writes exactly one JSON file (``--out``), which may not sit inside the archive.
It never creates a catalog directory: an absent catalog is a finding, not a prompt to make one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from itertools import pairwise
from pathlib import Path
from statistics import median, median_low
from typing import Any, Final

from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.analysis.memory_cap import apply_address_space_cap
from breezy.ingest.nbm_quantile_parse import NBM_NBP_MODEL
from breezy.persistence.archive_cache import ArchiveCache, ArchiveRequest
from breezy.persistence.us_source_request import (
    US_LAMP_LIVE_SOURCE,
    US_PFM_AFOS_SOURCE,
    US_SOURCE_PRODUCTS,
    US_SOURCE_STATIONS,
    revision_product_pattern,
)
from breezy.strategy.ladder_ev.forecast_catalog import (
    forecast_catalog_root,
    read_forecast_points,
)

__all__ = [
    "lamp_nominal_times",
    "lamp_summary",
    "main",
    "nbp_vintage_report",
    "pfm_issuance_times",
    "summarise_issuances",
]

_NS: Final[int] = 1_000_000_000
_MINUTE_S: Final[int] = 60
_HOUR_S: Final[int] = 3600
#: Prereg A0 table: LAMP is available at run + 60 min until C1 measures it (plan section 2).
LAMP_CONSERVATIVE_LAG_S: Final[int] = 3600
LAMP_RUN_MINUTE: Final[int] = 30
LAMP_BASIS: Final[str] = "nominal_plus_conservative_lag"
DEFAULT_TAPE_START: Final[dt.date] = dt.date(2026, 8, 30)
DEFAULT_MAX_MEMORY_GIB: Final[float] = 8.0
_TOP_MINUTES: Final[int] = 3
_EXIT_REFUSED: Final[int] = 2


class _NoFetchClock:
    def timestamp_ns(self) -> int:
        return 0


def _no_fetch(request: ArchiveRequest) -> bytes:
    raise RuntimeError(f"the census is read-only and never fetches ({request.cache_key()})")


def _entries(archive_root: Path, source: str) -> tuple[Any, ...]:
    cache = ArchiveCache(Path(archive_root), fetch=_no_fetch, clock=_NoFetchClock())
    return cache.entries(source)


def _utc(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / _NS, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------ PFM


def pfm_issuance_times(archive_root: Path) -> dict[str, tuple[int, ...]]:
    """``{wfo: sorted distinct WMO issuance ns}`` from raw ``pfm-r<N>`` archive entries."""
    pattern = revision_product_pattern(US_SOURCE_PRODUCTS[US_PFM_AFOS_SOURCE])
    found: dict[str, set[int]] = {}
    for entry in _entries(archive_root, US_PFM_AFOS_SOURCE):
        if entry.model is None or pattern.fullmatch(entry.product) is None:
            continue
        found.setdefault(entry.model, set()).add(entry.window_start)
    return {wfo: tuple(sorted(times)) for wfo, times in sorted(found.items())}


def summarise_issuances(ts_ns_sorted: Sequence[int]) -> dict[str, Any]:
    """Schedule regularity of one WFO's issuances (UTC)."""
    if not ts_ns_sorted:
        return {
            "n_issuances": 0,
            "n_days": 0,
            "per_day": None,
            "median_gap_s": None,
            "first_utc": None,
            "last_utc": None,
            "top_minute_of_hour": [],
            "fixed_schedule_share": None,
        }
    moments = [dt.datetime.fromtimestamp(t / _NS, tz=dt.UTC) for t in ts_ns_sorted]
    per_day = Counter(m.date() for m in moments)
    counts = sorted(per_day.values())
    minutes = Counter(m.minute for m in moments)
    gaps = [(b - a) / _NS for a, b in pairwise(ts_ns_sorted)]
    ranked = sorted(minutes.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "n_issuances": len(ts_ns_sorted),
        "n_days": len(per_day),
        "per_day": {"min": counts[0], "median": median_low(counts), "max": counts[-1]},
        "median_gap_s": float(median(gaps)) if gaps else None,
        "first_utc": _utc(ts_ns_sorted[0]),
        "last_utc": _utc(ts_ns_sorted[-1]),
        "top_minute_of_hour": [{"minute": m, "count": c} for m, c in ranked[:_TOP_MINUTES]],
        "fixed_schedule_share": ranked[0][1] / len(ts_ns_sorted),
    }


# ------------------------------------------------------------------------ NBP


def _station_vintages(base: Path, station: str) -> dict[str, Any]:
    root = forecast_catalog_root(base, station)
    if not root.is_dir():
        return {"present": False, "n_vintages": 0}
    rows = [
        p for p in read_forecast_points(ParquetDataCatalog(str(root))) if p.model == NBM_NBP_MODEL
    ]
    vintages = sorted({(p.cycle_runtime_ns, p.available_at_ns) for p in rows})
    if not vintages:
        return {"present": False, "n_vintages": 0}
    lags = [(avail - cycle) / _NS / _MINUTE_S for cycle, avail in vintages]
    cycle_hours = sorted({dt.datetime.fromtimestamp(c / _NS, tz=dt.UTC).hour for c, _ in vintages})
    return {
        "present": True,
        "n_vintages": len(vintages),
        "lag_min_minutes": min(lags),
        "lag_median_minutes": float(median(lags)),
        "lag_max_minutes": max(lags),
        "cycle_hours_utc": cycle_hours,
        "first_available_utc": _utc(min(avail for _, avail in vintages)),
        "last_available_utc": _utc(max(avail for _, avail in vintages)),
    }


def nbp_vintage_report(base: Path | None, stations: Sequence[str]) -> dict[str, Any]:
    """Do the node's ``ForecastPoint`` ``NBM_NBP`` vintages exist? Never creates a catalog."""
    if base is None:
        return {
            "vintages_present": False,
            "reason": "no forecast catalog base supplied",
            "stations": {},
        }
    per_station = {station: _station_vintages(Path(base), station) for station in stations}
    return {
        "vintages_present": any(s["present"] for s in per_station.values()),
        "reason": None,
        "stations": per_station,
    }


# ----------------------------------------------------------------------- LAMP


def lamp_nominal_times(start: dt.date, end: dt.date) -> list[dict[str, str]]:
    """Every HH30 run in ``[start, end]`` with its nominal availability (run + 60 min)."""
    if end < start:
        raise ValueError("lamp end precedes start")
    rows: list[dict[str, str]] = []
    day = start
    while day <= end:
        for hour in range(24):
            run = dt.datetime(day.year, day.month, day.day, hour, LAMP_RUN_MINUTE, tzinfo=dt.UTC)
            available = run + dt.timedelta(seconds=LAMP_CONSERVATIVE_LAG_S)
            rows.append(
                {
                    "run_utc": run.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "nominal_available_utc": available.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "basis": LAMP_BASIS,
                }
            )
        day += dt.timedelta(days=1)
    return rows


def lamp_summary(start: dt.date, end: dt.date, archive_root: Path) -> dict[str, Any]:
    rows = lamp_nominal_times(start, end)
    pattern = revision_product_pattern(US_SOURCE_PRODUCTS[US_LAMP_LIVE_SOURCE])
    measured = {
        e.window_start
        for e in _entries(archive_root, US_LAMP_LIVE_SOURCE)
        if pattern.fullmatch(e.product) is not None
    }
    return {
        "n_runs": len(rows),
        "first_run_utc": rows[0]["run_utc"],
        "last_run_utc": rows[-1]["run_utc"],
        "conservative_lag_minutes": LAMP_CONSERVATIVE_LAG_S / _MINUTE_S,
        "basis": LAMP_BASIS,
        "measured_c1_rows": len(measured),
        "status": (
            "nominal_only_until_c1_has_data" if not measured else "c1_data_present_use_measured"
        ),
    }


# ----------------------------------------------------------------------- main


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--forecast-base", type=Path, default=None)
    parser.add_argument("--stations", nargs="+", default=list(US_SOURCE_STATIONS))
    parser.add_argument("--lamp-start", type=dt.date.fromisoformat, default=DEFAULT_TAPE_START)
    parser.add_argument("--lamp-end", type=dt.date.fromisoformat, default=None)
    parser.add_argument(
        "--times-since",
        type=dt.date.fromisoformat,
        default=DEFAULT_TAPE_START,
        help="list each WFO's issuance times (ns) on or after this UTC date (B0 placebo pool)",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-memory-gib", type=float, default=DEFAULT_MAX_MEMORY_GIB)
    return parser.parse_args(list(argv))


def _since(times: Sequence[int], since: dt.date) -> list[int]:
    floor_ns = int(dt.datetime(since.year, since.month, since.day, tzinfo=dt.UTC).timestamp()) * _NS
    return [t for t in times if t >= floor_ns]


def _is_inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _write_atomic(out: Path, payload: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(tmp_name, out)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def main(
    argv: Sequence[str] | None = None, *, cap: Callable[[float], int] = apply_address_space_cap
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if _is_inside(args.out, args.archive_root):
        sys.stderr.write("REFUSED: --out must not sit inside the archive root\n")
        return _EXIT_REFUSED
    cap(args.max_memory_gib)
    lamp_end = args.lamp_end or dt.datetime.now(dt.UTC).date()
    report = {
        "inputs": {
            "archive_root": str(args.archive_root),
            "forecast_base": str(args.forecast_base) if args.forecast_base else None,
            "outcomes_read": False,
            "model_values_read": False,
            "network_used": False,
            "times_since": args.times_since.isoformat(),
        },
        "pfm": {
            wfo: {
                **summarise_issuances(times),
                "issuance_times_ns": _since(times, args.times_since),
            }
            for wfo, times in pfm_issuance_times(args.archive_root).items()
        },
        "nbp": nbp_vintage_report(args.forecast_base, args.stations),
        "lamp": lamp_summary(args.lamp_start, lamp_end, args.archive_root),
    }
    _write_atomic(args.out, report)
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
