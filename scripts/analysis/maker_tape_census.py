"""MAKER S1 WP1 -- maker-window print census (I/O layer).

Plan: docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md, WP1.
The pure counting rules live in ``breezy.analysis.maker_tape_census``.

Per CLEAN recorder instance this natively converts four small streams
(``BinaryOption``, ``QuoteTapeGap``, ``VenueClockOffset``, ``TradeTick``) into
a scratch catalog OUTSIDE the capture root, admits only maker-station x
requested-day prints, counts them in the maker window, and deletes the
scratch. LIVE / CORRUPT / EMPTY instances are counted and never read. No
Depth10, no network, no forecast store; the capture root is read-only.

Usage: maker_tape_census.py --from 2026-08-30 --to 2026-10-13 --stations LAX,MDW,MIA,SFO
       --search-declaration docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md
       --output ~/.local/share/breezy/derived/maker/s1/censused_days.jsonl
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_offer_gate_scan import classify_instance  # type: ignore[import-not-found]
from nautilus_trader.model.data import TradeTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from replay_sufficiency_census import _cleanup_work_catalog  # type: ignore[import-not-found]

from breezy.adapters.polymarket_us.symbology import REGISTRY_VENUE_KEY
from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap, VenueClockOffset
from breezy.analysis import maker_tape_census as core
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    PreflightError,
    list_instance_ids,
    scan_instance,
)
from breezy.registry import default_registry
from breezy.runtime.quote_tape_gaps import load_partitioned_quote_tape_gaps
from breezy.runtime.quote_tape_ingest_core import default_convert

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_ROOT: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_WORK_ROOT: Final[Path] = Path.home() / ".cache/breezy/maker-s1-work"
_DEFAULT_STATIONS: Final[str] = ",".join(sorted(core.MAKER_STATIONS))
_EXIT_REFUSED: Final[int] = 2
_EXIT_FAILED: Final[int] = 3
_EXIT_UNSCREENED: Final[int] = 4

_StationDay = tuple[str, dt.date]


@dataclass(frozen=True, slots=True)
class CensusRun:
    rows: tuple[core.CensusedDay, ...]
    summary: core.CensusSummary
    instance_counts: Counter[str]
    instances_read: tuple[str, ...]
    rows_discarded_out_of_scope: int = 0


@dataclass
class _Accumulator:
    """Everything the instances told us about one station-day."""

    clean: int = 0
    parse_failed: bool = False
    first_seen_ns: int | None = None
    corrupt_unread: int = 0
    live_unread: int = 0
    spans: list[core.AliveSpan] = field(default_factory=list)
    prints: list[core.PrintRecord] = field(default_factory=list)


def convert_instance(
    source: ParquetDataCatalog, instance_id: str, work: ParquetDataCatalog
) -> bool:
    """Natively convert the four small streams of one instance into ``work``.

    Returns True when the ``TradeTick`` stream could not be converted (the
    caller refuses every station-day that instance touches). A failure of any
    other stream propagates: without the instrument list or the liveness
    markers the instance cannot be interpreted at all.
    """
    for data_cls in (BinaryOption, QuoteTapeGap, VenueClockOffset):
        default_convert(source, instance_id, data_cls, DEFAULT_SUBDIRECTORY, target=work)
    try:
        default_convert(source, instance_id, TradeTick, DEFAULT_SUBDIRECTORY, target=work)
    except Exception as exc:  # noqa: BLE001 -- the refusal IS the finding, never a lower count
        print(
            f"maker-s1-census: TradeTick conversion failed for {instance_id}: {type(exc).__name__}",
            file=sys.stderr,
        )
        return True
    return False


def _station_day(instrument_id: object) -> _StationDay | None:
    facts = bucket_facts_from_instrument_id(str(instrument_id))
    return None if facts is None else (facts.settlement_station, facts.climate_day)


def _unwrap(item: Any) -> Any:
    return getattr(item, "data", item)


@dataclass
class _Scope:
    """In-scope stations and days. Every stream is filtered through ``admits`` BEFORE any
    gap / first-seen / coverage / count computation, so an out-of-scope row never enters a
    computation (SEARCH declaration section 2). ``discarded`` counts them; no value is kept."""

    days: frozenset[dt.date]
    stations: frozenset[str]
    discarded: int = 0

    def admits(self, key: _StationDay | None) -> bool:
        ok = key is not None and core.admit_print(key[0], key[1], self.days, self.stations)
        if not ok:
            self.discarded += 1
        return ok


def _first_seen_by_station_day(work: ParquetDataCatalog, scope: _Scope) -> dict[_StationDay, int]:
    first: dict[_StationDay, int] = {}
    for instrument in work.query(data_cls=BinaryOption):
        key = _station_day(instrument.id)
        if key is not None and scope.admits(key):
            first[key] = min(first.get(key, instrument.ts_init), instrument.ts_init)
    return first


def _alive_span(work: ParquetDataCatalog) -> tuple[int, int] | None:
    stamps = [_unwrap(item).ts_init for item in work.query(data_cls=VenueClockOffset)]
    return (min(stamps), max(stamps)) if stamps else None


def _gaps_by_station_day(
    work: ParquetDataCatalog, scope: _Scope
) -> dict[_StationDay, list[core.GapInterval]]:
    gaps: dict[_StationDay, list[core.GapInterval]] = defaultdict(list)
    for partition, records in load_partitioned_quote_tape_gaps(work).items():
        key = _station_day(partition.instrument_id)
        if not scope.admits(key) or key is None:
            continue
        gaps[key].extend(
            core.GapInterval(g.started_ns, g.ended_ns if g.resolved else None) for g in records
        )
    return gaps


def _admitted_prints(
    work: ParquetDataCatalog, scope: _Scope
) -> dict[_StationDay, list[core.PrintRecord]]:
    out: dict[_StationDay, list[core.PrintRecord]] = defaultdict(list)
    for tick in work.query(data_cls=TradeTick):
        key = _station_day(tick.instrument_id)
        # Before any bucketing, count or log: NYC, D+1 and out-of-range slugs vanish here.
        if not scope.admits(key) or key is None:
            continue
        out[key].append(
            core.PrintRecord(
                trade_id=tick.trade_id.value,
                ts_event_ns=tick.ts_event,
                price_yes=Decimal(str(tick.price)),
                aggressor=tick.aggressor_side.name,
                rung=str(tick.instrument_id),
            )
        )
    return out


def _read_instance(
    work: ParquetDataCatalog,
    parse_failed: bool,
    scope: _Scope,
    ledger: dict[_StationDay, _Accumulator],
) -> None:
    first_seen = _first_seen_by_station_day(work, scope)
    alive = _alive_span(work)
    gaps = _gaps_by_station_day(work, scope)
    prints = _admitted_prints(work, scope)
    for key, seen_ns in first_seen.items():
        entry = ledger[key]
        entry.clean += 1
        entry.parse_failed = entry.parse_failed or parse_failed
        entry.first_seen_ns = (
            seen_ns if entry.first_seen_ns is None else min(entry.first_seen_ns, seen_ns)
        )
        if alive is not None:
            entry.spans.append(core.AliveSpan(alive[0], alive[1], tuple(gaps.get(key, ()))))
        entry.prints.extend(prints.get(key, ()))


def _listed_station_days(instance_dir: Path, scope: _Scope) -> set[_StationDay]:
    """Station-days an UNREAD (LIVE/CORRUPT) instance lists, from directory NAMES only.

    Per-instrument streams live at ``<class>/<instrument_id>/``; the instrument id is in
    the directory name, so no feather byte is opened. A lower bound: an instance that
    wrote only the flat ``binary_option`` file lists nothing here.
    """
    listed: set[_StationDay] = set()
    for class_dir in (d for d in instance_dir.iterdir() if d.is_dir()):
        for instrument_dir in (d for d in class_dir.iterdir() if d.is_dir()):
            key = _station_day(instrument_dir.name)
            if key is not None and scope.admits(key):
                listed.add(key)
    return listed


def _check_work_root(work_root: Path, catalog_root: Path) -> None:
    resolved = work_root.resolve()
    if resolved == catalog_root.resolve() or catalog_root.resolve() in resolved.parents:
        raise ValueError(
            f"--work-root {work_root} is inside the capture root {catalog_root}. "
            "The capture is read-only evidence; converted rows must go somewhere else."
        )


def _std_offset_hours(station: str) -> float:
    return default_registry().climate_day_window(REGISTRY_VENUE_KEY, station).std_utc_offset_hours


def _plan_rows(
    stations: Sequence[str], day_from: dt.date, day_to: dt.date, declaration_sha256: str | None
) -> dict[_StationDay, tuple[str, core.MakerWindow]]:
    """Clear every requested station-day BEFORE any tape is touched (FirewallRefused aborts)."""
    plan: dict[_StationDay, tuple[str, core.MakerWindow]] = {}
    day = day_from
    while day <= day_to:
        for station in stations:
            firewall = core.require_firewall_clearance(station, day, declaration_sha256)
            window = core.maker_window_ns(
                climate_day=day, std_utc_offset_hours=_std_offset_hours(station)
            )
            plan[(station, day)] = (firewall, window)
        day += dt.timedelta(days=1)
    return plan


def run_census(
    *,
    catalog_root: Path,
    work_root: Path,
    stations: Sequence[str],
    day_from: dt.date,
    day_to: dt.date,
    declaration_sha256: str | None,
) -> CensusRun:
    plan = _plan_rows(stations, day_from, day_to, declaration_sha256)
    _check_work_root(work_root, catalog_root)
    read_days = frozenset(
        day
        for (_, day), (_, window) in plan.items()
        if window.start_ns >= core.TRADE_CAPTURE_START_NS
    )
    scope = _Scope(read_days, frozenset(stations))
    ledger: dict[_StationDay, _Accumulator] = defaultdict(_Accumulator)
    counts: Counter[str] = Counter()
    read: list[str] = []
    source = ParquetDataCatalog(str(catalog_root))
    instance_ids = list_instance_ids(catalog_root, DEFAULT_SUBDIRECTORY) if read_days else ()
    created_root = not work_root.exists()
    now_ns = time.time_ns()

    for position, instance_id in enumerate(instance_ids, start=1):
        try:
            verdict = classify_instance(
                scan_instance(catalog_root, instance_id, DEFAULT_SUBDIRECTORY), now_ns=now_ns
            )
        except PreflightError:
            verdict = "EMPTY"
        counts[verdict] += 1
        print(
            f"maker-s1-census: {position}/{len(instance_ids)} {instance_id} {verdict}",
            file=sys.stderr,
        )
        if verdict in ("LIVE", "CORRUPT"):  # classifier verdict only; no byte is read
            for key in _listed_station_days(
                catalog_root / DEFAULT_SUBDIRECTORY / instance_id, scope
            ):
                if verdict == "LIVE":
                    ledger[key].live_unread += 1
                else:
                    ledger[key].corrupt_unread += 1
        if verdict != "CLEAN":
            continue
        work_dir = work_root / instance_id
        if work_dir.exists() and any(work_dir.iterdir()):
            raise ValueError(f"work catalog {work_dir} is not empty; refusing a partial conversion")
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            work = ParquetDataCatalog(str(work_dir))
            parse_failed = convert_instance(source, instance_id, work)
            _read_instance(work, parse_failed, scope, ledger)
            read.append(instance_id)
        finally:
            _cleanup_work_catalog(work_dir)
    if created_root:
        with contextlib.suppress(OSError):
            work_root.rmdir()

    rows = tuple(
        _row(key, plan[key], ledger.get(key)) for key in sorted(plan, key=lambda k: (k[0], k[1]))
    )
    return CensusRun(rows, core.summarise(rows), counts, tuple(read), scope.discarded)


def _row(
    key: _StationDay, planned: tuple[str, core.MakerWindow], seen: _Accumulator | None
) -> core.CensusedDay:
    firewall, window = planned
    entry = seen if seen is not None else _Accumulator()
    return core.classify(
        station=key[0],
        climate_day=key[1],
        firewall_class=firewall,
        window=window,
        clean_instances=entry.clean,
        corrupt_unread=entry.corrupt_unread,
        live_unread=entry.live_unread,
        trade_parse_failed=entry.parse_failed,
        spans=tuple(entry.spans),
        prints=tuple(entry.prints),
        first_seen_ns=entry.first_seen_ns,
    )


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=10,
        )  # fmt: skip
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _provenance(
    args: argparse.Namespace, declaration: str | None, run: CensusRun
) -> dict[str, object]:
    return {
        "git_sha": _git_sha(),
        "stations": args.stations,
        "range": [args.day_from, args.day_to],
        "declaration_sha256": declaration,
        "instances": dict(run.instance_counts),
        "instances_read": list(run.instances_read),
        "constants": {
            "STALE_H": core.STALE_H,
            "NBP_LAG_UB_H": core.NBP_LAG_UB_H,
            "CANCEL_LST_HOUR": core.CANCEL_LST_HOUR,
            "COVERAGE_MIN": core.COVERAGE_MIN,
            "LONGEST_HOLE_MAX_MIN": core.LONGEST_HOLE_MAX_MIN,
            "RHO_ASSUMED": core.RHO_ASSUMED,
            "TRADE_CAPTURE_START_NS": core.TRADE_CAPTURE_START_NS,
        },
    }


def _report(summary: core.CensusSummary, run: CensusRun) -> list[str]:
    lines = [
        "census_summary: "
        + json.dumps(
            {
                "N_cov": summary.n_cov,
                "D_cov": summary.d_cov,
                "n_eff_ub": round(summary.n_eff_ub, 4),
                "rho": f"{core.RHO_ASSUMED} (assumed, not measured)",
                "C": summary.c,
                "C_030": summary.c_030,
                "tail_span_only_days": summary.tail_span_only,
                "rows_discarded_out_of_scope": run.rows_discarded_out_of_scope,
                "reasons": dict(Counter(r.reason for r in run.rows)),
            },
            sort_keys=True,
        )
    ]
    if "S-1" in summary.stops:
        lines.append(f"STOP S-1 UNDERPOWERED n_eff_ub={summary.n_eff_ub:.2f} < {core.N_EFF_FLOOR}")
    if summary.s5_unscreened:
        lines.append(f"STOP S-5 UNSCREENED (covered_days={summary.n_cov} < {core.S5_MIN_COVERED})")
    if "S-5" in summary.stops:
        lines.append(f"STOP S-5 NO-GO pre-screen C={summary.c} < {core.C_STOP}")
    if summary.flag is not None:
        lines.append(f"FLAG {summary.flag} C={summary.c} in [{core.C_STOP}, {core.C_FLAG})")
    lines.append(
        "INFO bidlive: "
        + json.dumps(
            {
                "window": "[D-1 16:50Z, D 02:50Z) within the plan window (spec section 3)",
                "N_cov_bidlive": summary.n_cov_bidlive,
                "D_cov_bidlive": summary.d_cov_bidlive,
                "C_bidlive": summary.c_bidlive,
                "n_eff_ub_bidlive": round(summary.n_eff_ub_bidlive, 4),
                "gates_no_stop": True,
            },
            sort_keys=True,
        )
    )
    return lines


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--from", dest="day_from", required=True)
    parser.add_argument("--to", dest="day_to", required=True)
    parser.add_argument("--stations", default=_DEFAULT_STATIONS)
    parser.add_argument("--search-declaration", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    declaration: str | None = None
    try:
        if args.search_declaration is not None:
            declaration = hashlib.sha256(
                args.search_declaration.expanduser().read_bytes()
            ).hexdigest()
        run = run_census(
            catalog_root=args.catalog_root.expanduser(),
            work_root=args.work_root.expanduser(),
            stations=tuple(s.strip().upper() for s in args.stations.split(",") if s.strip()),
            day_from=dt.date.fromisoformat(args.day_from),
            day_to=dt.date.fromisoformat(args.day_to),
            declaration_sha256=declaration,
        )
    except (core.FirewallRefused, ValueError) as exc:
        print(f"maker-s1-census: REFUSED {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_REFUSED
    except OSError as exc:
        print(f"maker-s1-census: IO_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_FAILED
    except Exception as exc:  # noqa: BLE001 -- loud, never a partial output file
        print(f"maker-s1-census: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_FAILED
    try:
        core.write_censused_days(args.output.expanduser(), run.rows)
    except OSError as exc:
        print(f"maker-s1-census: IO_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return _EXIT_FAILED
    print("census_provenance: " + json.dumps(_provenance(args, declaration, run), sort_keys=True))
    print("\n".join(_report(run.summary, run)))
    return _EXIT_UNSCREENED if run.summary.s5_unscreened else 0


if __name__ == "__main__":
    raise SystemExit(main())
