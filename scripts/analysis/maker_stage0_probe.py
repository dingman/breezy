"""MAKER S2 WP0 -- the read-only Stage-0 probe (I/O layer and report).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP0 (L108-117) and
S2_stage0_replay_plan_r4_delta.md (e), (g), (i)3. Pure rules: ``maker_stage0_probe_core``.

Read-only on the capture: per CLEAN recorder instance the needed streams are converted natively
(``default_convert``) into a scratch catalog OUTSIDE the capture root, read, and deleted. The
caller (the driver) enforces the licence: ``probe`` reads only the ``days`` it is handed and
never enumerates the catalog beyond them; ``first_print_instant`` reads print timestamps only.
``ProbeReport.require_clean`` raises the S-2 STOP after ``wp0_agreement.json`` is written.
"""

from __future__ import annotations

import datetime as dt
import shutil
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from nautilus_trader.model.data import OrderBookDepth10, TradeTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.symbology import REGISTRY_VENUE_KEY, leg_of
from breezy.adapters.polymarket_us.tape_records import (
    DepthTruncation,
    QuoteTapeGap,
    VenueClockOffset,
)
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
from scripts.analysis.cli_basis_offer_gate_scan import classify_instance
from scripts.analysis.maker_stage0_probe_core import (
    CensusCounts,
    CensusViolation,
    DirectionResult,
    Frame,
    Gap,
    InstanceDayDelta,
    SideTally,
    StopS2,
    classify_direction,
    count_census,
    direction_result,
    enforce_direction,
    first_replayable_day,
    gap_free_frames,
    instance_day_deltas,
    reassert_census,
    station_day_delta,
)

__all__ = [
    "CensusCounts", "CensusViolation", "DirectionResult", "Frame", "Gap", "InstanceDayDelta",
    "ProbeReport", "SideTally", "StationDayCoverage", "StopS2", "classify_direction",
    "count_census", "direction_result", "enforce_direction", "first_print_instant",
    "first_replayable_day", "gap_free_frames", "instance_day_deltas", "probe",
    "reassert_census", "station_day_delta",
]  # fmt: skip

_HOUR_NS: Final[int] = 3_600 * 1_000_000_000
_DIRECTION_STREAMS: Final[tuple[type, ...]] = (
    BinaryOption,
    QuoteTapeGap,
    VenueClockOffset,
    TradeTick,
    OrderBookDepth10,
    DepthTruncation,
)
CLOCKS: Final[Mapping[str, str]] = {
    "depth_ts_event": "venue transactTime (parsing.py:777-779)",
    "print_ts_event": "venue tradeTime (parsing.py:971)",
    "forecast_available_at_ns": "UTC-anchored",
}
_StationDay = tuple[str, dt.date]
_Samples = Sequence[tuple[int, int]]  # (ts_init, signed offset_ns)


# --- Report ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StationDayCoverage:
    station: str
    climate_day: str
    live_hours: float
    gap_overlap_hours: float
    listing_ns: int | None
    listing_abstain: bool  # no listing, or listed after D-1 12:00Z
    delta_ns: int | None


@dataclass(frozen=True, slots=True)
class ProbeReport:
    days: tuple[str, ...]
    stations: tuple[str, ...]
    first_print_ns: int | None
    first_replayable_day: str | None
    direction: DirectionResult
    control: DirectionResult | None
    census: CensusCounts
    depth_frames: int
    truncated_frames: int
    coverage: tuple[StationDayCoverage, ...]
    delta_instance_days: tuple[InstanceDayDelta, ...]
    delta_distribution: Mapping[str, int | None]
    ladder_parity: Mapping[str, Mapping[str, object]]

    def require_clean(self) -> None:
        """Raise ``CensusViolation`` / ``StopS2``; the sidecar is written BEFORE this is called."""
        reassert_census(self.census)
        enforce_direction(self.direction)

    def to_dict(self) -> dict[str, Any]:
        share = self.truncated_frames / self.depth_frames if self.depth_frames else None
        return {
            "days": list(self.days),
            "stations": list(self.stations),
            "first_print_ns": self.first_print_ns,
            "first_replayable_day": self.first_replayable_day,
            "direction": self.direction.to_dict(),
            "positive_control": None if self.control is None else self.control.to_dict(),
            "census": asdict(self.census),
            "depth_frames": self.depth_frames,
            "truncated_frames": self.truncated_frames,
            "truncated_frame_share": share,
            "coverage": [asdict(c) for c in self.coverage],
            "delta_instance_days": [asdict(d) for d in self.delta_instance_days],
            "delta_distribution": dict(self.delta_distribution),
            "ladder_parity": {k: dict(v) for k, v in self.ladder_parity.items()},
            "clocks": dict(CLOCKS),
        }


# --- I/O ------------------------------------------------------------------------------
@dataclass
class _Ledger:
    prints: dict[str, list[core.PrintRecord]] = field(default_factory=dict)
    frames: dict[str, list[Frame]] = field(default_factory=lambda: defaultdict(list))
    depth_frames: int = 0
    truncated_frames: int = 0
    spans: dict[_StationDay, list[core.AliveSpan]] = field(
        default_factory=lambda: defaultdict(list)
    )
    listing: dict[_StationDay, int] = field(default_factory=dict)
    samples: dict[_StationDay, dict[str, _Samples]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    rungs: dict[_StationDay, set[str]] = field(default_factory=lambda: defaultdict(set))


def _key(
    instrument_id: InstrumentId, days: Collection[dt.date], stations: Collection[str]
) -> _StationDay | None:
    """``(station, day)`` for an in-scope YES-leg instrument, else None (out of scope vanishes)."""
    if leg_of(instrument_id) != "yes":
        return None
    facts = bucket_facts_from_instrument_id(str(instrument_id))
    if facts is None or not core.admit_print(
        facts.settlement_station, facts.climate_day, days, stations
    ):
        return None
    return (facts.settlement_station, facts.climate_day)


def _unwrap(item: Any) -> Any:
    return getattr(item, "data", item)


def _mid(depth: OrderBookDepth10) -> Decimal | None:
    bid, ask = depth.bids[0], depth.asks[0]
    if bid.size.as_double() <= 0 or ask.size.as_double() <= 0:
        return None
    return (Decimal(str(bid.price)) + Decimal(str(ask.price))) / 2


def _read_instance(
    work: ParquetDataCatalog,
    instance_id: str,
    days: Collection[dt.date],
    stations: Collection[str],
    ledger: _Ledger,
) -> None:
    rungs: dict[str, _StationDay] = {}
    for instrument in work.query(data_cls=BinaryOption):
        key = _key(instrument.id, days, stations)
        if key is not None:
            rungs[str(instrument.id)] = key
            ledger.rungs[key].add(str(instrument.id))
            ledger.listing[key] = min(
                ledger.listing.get(key, instrument.ts_init), instrument.ts_init
            )
    gaps: dict[str, list[Gap]] = defaultdict(list)
    for partition, records in load_partitioned_quote_tape_gaps(work).items():
        gaps[str(partition.instrument_id)].extend(
            Gap(g.started_ns, g.ended_ns if g.resolved else None) for g in records
        )
    for rung in rungs:
        _read_frames(work, rung, gaps[rung], ledger)
    ledger.truncated_frames += sum(
        str(_unwrap(t).instrument_id) in rungs for t in work.query(data_cls=DepthTruncation)
    )
    ledger.prints[instance_id] = _read_prints(work, rungs)
    samples = [
        (_unwrap(o).ts_init, _unwrap(o).offset_ns) for o in work.query(data_cls=VenueClockOffset)
    ]
    for key in set(rungs.values()):
        if samples:
            station_gaps = tuple(
                core.GapInterval(g.start_ns, g.end_ns)
                for rung, k in rungs.items()
                if k == key
                for g in gaps[rung]
            )
            stamps = [ts for ts, _offset in samples]
            ledger.spans[key].append(core.AliveSpan(min(stamps), max(stamps), station_gaps))
        ledger.samples[key][instance_id] = samples


def _read_frames(work: ParquetDataCatalog, rung: str, gaps: list[Gap], ledger: _Ledger) -> None:
    depths = work.query(data_cls=OrderBookDepth10, identifiers=[rung])
    ledger.depth_frames += len(depths)
    frames = [Frame(d.ts_event, _mid(d)) for d in depths]
    ledger.frames[rung].extend(gap_free_frames(frames, gaps))


def _read_prints(
    work: ParquetDataCatalog, rungs: Mapping[str, _StationDay]
) -> list[core.PrintRecord]:
    return [
        core.PrintRecord(
            trade_id=t.trade_id.value,
            ts_event_ns=t.ts_event,
            price_yes=Decimal(str(t.price)),
            aggressor=t.aggressor_side.name,
            rung=str(t.instrument_id),
            size=Decimal(str(t.size)),
        )
        for t in work.query(data_cls=TradeTick)
        if str(t.instrument_id) in rungs
    ]


def _check_work_root(work_root: Path, catalog_root: Path) -> None:
    resolved, root = work_root.resolve(), catalog_root.resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError(
            f"work root {work_root} is inside the capture root {catalog_root}; "
            "the capture is read-only evidence"
        )


def _for_each_clean_instance(
    catalog_root: Path,
    work_root: Path,
    streams: Sequence[type],
    visit: Callable[[ParquetDataCatalog, str], None],
) -> None:
    _check_work_root(work_root, catalog_root)
    source = ParquetDataCatalog(str(catalog_root))
    now_ns = time.time_ns()
    for instance_id in list_instance_ids(catalog_root, DEFAULT_SUBDIRECTORY):
        try:
            verdict = classify_instance(
                scan_instance(catalog_root, instance_id, DEFAULT_SUBDIRECTORY), now_ns=now_ns
            )
        except PreflightError:
            continue
        if verdict != "CLEAN":
            continue
        work_dir = work_root / instance_id
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            work = ParquetDataCatalog(str(work_dir))
            for data_cls in streams:
                default_convert(source, instance_id, data_cls, DEFAULT_SUBDIRECTORY, target=work)
            visit(work, instance_id)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


def first_print_instant(catalog_root: Path, *, work_root: Path) -> int | None:
    """Global minimum print ``ts_event`` over CLEAN instances (timestamps only)."""
    stamps: list[int] = []

    def visit(work: ParquetDataCatalog, _instance: str) -> None:
        stamps.extend(t.ts_event for t in work.query(data_cls=TradeTick))

    _for_each_clean_instance(catalog_root, work_root, (TradeTick,), visit)
    return min(stamps) if stamps else None


def _hours(intervals: Iterable[tuple[int, int]]) -> float:
    return sum(end - start for start, end in intervals) / _HOUR_NS


def _coverage(
    key: _StationDay, ledger: _Ledger
) -> tuple[StationDayCoverage, list[InstanceDayDelta]]:
    station, day = key
    offset = default_registry().climate_day_window(REGISTRY_VENUE_KEY, station).std_utc_offset_hours
    window = core.maker_window_ns(climate_day=day, std_utc_offset_hours=offset)
    span = (window.start_ns, window.end_ns)
    spans = ledger.spans.get(key, [])
    live = _hours(core.covered_intervals(span, [replace(s, gaps=()) for s in spans]))
    covered = _hours(core.covered_intervals(span, spans))
    deltas = instance_day_deltas(ledger.samples.get(key, {}), span)
    listing = ledger.listing.get(key)
    row = StationDayCoverage(
        station, day.isoformat(), live, live - covered, listing,
        listing is None or listing > window.start_ns, station_day_delta(deltas),
    )  # fmt: skip
    return row, [replace(d, station=station, climate_day=day.isoformat()) for d in deltas.values()]


def _ladder_parity(ledger: _Ledger, stations: Sequence[str]) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for station in stations:
        sizes: dict[str, int] = defaultdict(int)
        for (st, _day), rungs in ledger.rungs.items():
            if st == station and rungs:
                sizes[str(len(rungs))] += 1
        out[station] = {"rungs_per_day": dict(sorted(sizes.items())), "uniform": len(sizes) <= 1}
    return out


def _distribution(deltas: Sequence[int]) -> dict[str, int | None]:
    ordered = sorted(deltas)
    return {
        "n": len(ordered),
        "min": ordered[0] if ordered else None,
        "p50": int(statistics.median_low(ordered)) if ordered else None,
        "max": ordered[-1] if ordered else None,
    }


def _station_of(record: core.PrintRecord) -> str | None:
    facts = bucket_facts_from_instrument_id(record.rung)
    return None if facts is None else facts.settlement_station


def probe(
    catalog_root: Path,
    days: Collection[dt.date],
    stations: Sequence[str],
    *,
    work_root: Path,
    first_print_ns: int | None = None,
    control_station: str = "SFO",
) -> ProbeReport:
    """Read only ``days`` x ``stations``; never write under ``catalog_root``.

    The direction verdict is RECORDED here and enforced by ``ProbeReport.require_clean`` so the
    driver can write ``wp0_agreement.json`` before the S-2 STOP raises.
    """
    ledger, day_set, station_set = _Ledger(), frozenset(days), frozenset(stations)

    def visit(work: ParquetDataCatalog, instance_id: str) -> None:
        _read_instance(work, instance_id, day_set, station_set, ledger)

    _for_each_clean_instance(catalog_root, work_root, _DIRECTION_STREAMS, visit)
    frames = {rung: sorted(fs, key=lambda f: f.ts_ns) for rung, fs in ledger.frames.items()}
    pooled = sorted((r for rs in ledger.prints.values() for r in rs), key=lambda r: r.trade_id)
    unique = list({r.trade_id: r for r in pooled}.values())
    rows = [_coverage((s, d), ledger) for s in stations for d in sorted(day_set)]
    deltas = [d for _row, ds in rows for d in ds]
    control = [r for r in unique if _station_of(r) == control_station]
    return ProbeReport(
        days=tuple(sorted(d.isoformat() for d in day_set)),
        stations=tuple(stations),
        first_print_ns=first_print_ns,
        first_replayable_day=(
            None if first_print_ns is None else first_replayable_day(first_print_ns).isoformat()
        ),
        direction=direction_result(unique, frames),
        control=direction_result(control, frames),
        census=count_census(ledger.prints),
        depth_frames=ledger.depth_frames,
        truncated_frames=ledger.truncated_frames,
        coverage=tuple(row for row, _ds in rows),
        delta_instance_days=tuple(deltas),
        delta_distribution=_distribution([r.delta_ns for r, _ds in rows if r.delta_ns is not None]),
        ladder_parity=_ladder_parity(ledger, stations),
    )
