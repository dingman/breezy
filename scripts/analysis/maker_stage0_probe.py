"""MAKER S2 WP0 -- the read-only Stage-0 probe (I/O layer).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP0 (L108-117) and
S2_stage0_replay_plan_r4_delta.md (b), (e), (g), (i)3. Pure rules: ``maker_stage0_probe_core``.

Read-only on the capture: per CLEAN recorder instance the needed streams are converted natively
(``default_convert``) into a scratch catalog OUTSIDE the capture root, read, and deleted. The
scratch ``work_root/<instance_id>`` must not pre-exist (never adopted, never deleted if foreign).
The caller (the driver) enforces the licence: ``probe`` and ``first_print_instant`` read only the
``days`` x maker ``stations`` they are handed (NYC and undeclared days vanish through
``station_day_key``). Depth and trade queries are bounded to [D-1 12:00Z, end of the D+1 window].
Delta and live/gap hours use S1's bid-live window (``bidlive_window_ns``). The listing instant is
the earliest ``BinaryOption.ts_init`` -- the field S1 uses for ``first_seen_ns``.
``ProbeReport`` and ``CLOCKS`` live in ``maker_stage0_probe_report`` and are re-exported here.
``ProbeReport.require_clean`` raises the S-2 STOP after ``wp0_agreement.json`` is written.
"""

from __future__ import annotations

import datetime as dt
import shutil
import time
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from nautilus_trader.model.data import OrderBookDepth10, TradeTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.symbology import REGISTRY_VENUE_KEY
from breezy.adapters.polymarket_us.tape_records import (
    DepthTruncation,
    QuoteTapeGap,
    VenueClockOffset,
)
from breezy.analysis import maker_tape_census as core
from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    PreflightError,
    list_instance_ids,
)
from breezy.registry import default_registry
from breezy.runtime.quote_tape_gaps import load_partitioned_quote_tape_gaps
from breezy.runtime.quote_tape_ingest_core import default_convert
from scripts.analysis import maker_stage0_scoped_convert as sc
from scripts.analysis.cli_basis_offer_gate_scan import classify_instance
from scripts.analysis.maker_stage0_prefilter import _prefilter_reason, log_prefilter
from scripts.analysis.maker_stage0_probe_frames import (
    FrameSpill,
    count_truncations,
    fold_directions,
    read_depth_frames,
)
from scripts.analysis.maker_stage0_probe_report import CLOCKS, ProbeReport
from scripts.analysis.maker_stage0_release import release_free_heap

from scripts.analysis.maker_stage0_clock_offset import (  # isort: skip
    InstanceDayDelta, delta_summary, instance_day_deltas, station_day_delta,
)  # fmt: skip
from scripts.analysis.maker_stage0_probe_core import (  # isort: skip
    CensusCounts, CensusViolation, DirectionResult, Frame, Gap, SideTally, StationDay,
    StationDayCoverage, StopS2, classify_direction, count_census, direction_result, distribution,
    enforce_direction, first_replayable_day, gap_free_frames, ladder_parity,
    listing_abstain, live_and_gap_hours, mid_of, reassert_census, station_day_key, unique_prints,
)  # fmt: skip

__all__ = [
    "CLOCKS", "CensusCounts", "CensusViolation", "DirectionResult", "Frame", "Gap",
    "InstanceDayDelta", "ProbeReport", "SideTally", "StationDayCoverage", "StopS2",
    "classify_direction",
    "count_census", "direction_result", "distribution", "enforce_direction",
    "first_print_instant", "first_replayable_day", "gap_free_frames", "instance_day_deltas",
    "ladder_parity", "listing_abstain", "live_and_gap_hours", "mid_of", "prefilter_cutoff_ns",
    "probe", "reassert_census",
    "station_day_delta", "station_day_key", "unique_prints",
]  # fmt: skip

_DIRECTION_STREAMS: Final[tuple[type, ...]] = (
    BinaryOption,
    QuoteTapeGap,
    VenueClockOffset,
    TradeTick,
    OrderBookDepth10,
    DepthTruncation,
)
_Samples = Sequence[tuple[int, int]]  # (ts_init, signed offset_ns)
_ONE_DAY: Final = dt.timedelta(days=1)
_ONE_DAY_NS: Final = 86_400 * 1_000_000_000


# --- I/O ------------------------------------------------------------------------------
@dataclass
class _Ledger:
    frames: FrameSpill  # S-5: gap-free frames live on disk, never in the ledger
    prints: dict[str, list[core.PrintRecord]] = field(default_factory=dict)
    depth_frames: int = 0
    truncated_frames: int = 0
    spans: dict[StationDay, list[core.AliveSpan]] = field(default_factory=lambda: defaultdict(list))
    listing: dict[StationDay, int] = field(default_factory=dict)
    samples: dict[StationDay, dict[str, _Samples]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    rungs: dict[StationDay, set[str]] = field(default_factory=lambda: defaultdict(set))
    backwards: dict[str, int] = field(default_factory=dict)  # rung -> ts_event-backwards frames


def _unwrap(item: Any) -> Any:
    return getattr(item, "data", item)


def _maker_window(station: str, day: dt.date) -> core.MakerWindow:
    offset = default_registry().climate_day_window(REGISTRY_VENUE_KEY, station).std_utc_offset_hours
    return core.maker_window_ns(climate_day=day, std_utc_offset_hours=offset)


def _focus(key: StationDay) -> tuple[int, int]:
    """The rung's own query range: [D-1 12:00Z, end of the D+1 window]."""
    station, day = key
    return _maker_window(station, day).start_ns, _maker_window(station, day + _ONE_DAY).end_ns


def _query_bounds(days: Collection[dt.date], stations: Collection[str]) -> tuple[int, int]:
    """[D-1 12:00Z of the first day, end of the D+1 window of the last day] in ns."""
    start = min(_maker_window(s, d).start_ns for s in stations for d in days)
    end = max(_maker_window(s, d + _ONE_DAY).end_ns for s in stations for d in days)
    return start, end


def prefilter_cutoff_ns(days: Collection[dt.date], stations: Collection[str]) -> int | None:
    """One day before the block's first query bound (C7 pre-filter); None for an empty block."""
    if not days or not stations:
        return None
    return _query_bounds(days, stations)[0] - _ONE_DAY_NS


def _read_instance(
    work: ParquetDataCatalog,
    instance_id: str,
    days: Collection[dt.date],
    stations: Collection[str],
    ledger: _Ledger,
) -> None:
    bounds = _query_bounds(days, stations)
    rungs: dict[str, StationDay] = {}
    for instrument in work.query(data_cls=BinaryOption):
        key = station_day_key(instrument.id, days, stations)
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
    for rung, key in rungs.items():
        ledger.depth_frames += read_depth_frames(
            work, rung, gaps[rung], bounds, _focus(key), ledger.frames, backwards=ledger.backwards
        )
    ledger.truncated_frames += count_truncations(work, rungs, instance_id)
    ledger.prints[instance_id] = _read_prints(work, rungs, bounds)
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


def _read_prints(
    work: ParquetDataCatalog, rungs: Mapping[str, StationDay], bounds: tuple[int, int]
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
        for t in work.query(data_cls=TradeTick, start=bounds[0], end=bounds[1])
        if str(t.instrument_id) in rungs
    ]


def _for_each_clean_instance(
    catalog_root: Path,
    work_root: Path,
    streams: Sequence[type],
    visit: Callable[[ParquetDataCatalog, str], None],
    skipped: dict[str, str],
    keep_rung: Callable[[str], bool] | None = None,
    *,
    written_since_ns: int | None = None,
    days: Collection[dt.date] = (),
    stations: Collection[str] = (),
) -> None:
    """Convert each CLEAN instance into a fresh scratch dir, visit it, delete it.

    ``work_root/<instance_id>`` must not exist (``FileExistsError``, left untouched). Instances
    that are malformed or not CLEAN are recorded in ``skipped`` with the reason, never dropped.
    ``keep_rung`` (S-5) limits the per-rung streams converted to the ids it accepts (None: all).
    ``written_since_ns`` skips, before classify, an instance whose newest feather is strictly
    older and that holds no licensed rung directory or definition (``maker_stage0_prefilter``).
    """
    sc.check_work_root(work_root, catalog_root)
    source = ParquetDataCatalog(str(catalog_root))
    now_ns = time.time_ns()
    instance_ids = list_instance_ids(catalog_root, DEFAULT_SUBDIRECTORY)
    fail_open: list[str] = []
    for instance_id in instance_ids:
        instance_dir = catalog_root / DEFAULT_SUBDIRECTORY / instance_id
        if written_since_ns is not None and (
            reason := _prefilter_reason(
                instance_dir, written_since_ns, days=days, stations=stations, fail_open=fail_open
            )
        ):
            skipped[instance_id] = reason
            continue
        try:
            verdict = classify_instance(
                sc.scan_instance_memoized(catalog_root, instance_id, DEFAULT_SUBDIRECTORY),
                now_ns=now_ns,
            )
        except PreflightError as error:
            skipped[instance_id] = f"PreflightError: {error}"
            continue
        if verdict != "CLEAN":
            skipped[instance_id] = f"verdict {verdict}"
            continue
        work_dir = work_root / instance_id
        work_dir.mkdir(
            parents=True, exist_ok=False
        )  # before the try: a foreign dir is never rmtree'd
        try:
            work = ParquetDataCatalog(str(work_dir))
            sc.convert_scoped(default_convert, source, work, instance_dir, streams, keep_rung)
            visit(work, instance_id)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            release_free_heap()  # S-5: the instance's freed heap goes back before the next one
    log_prefilter(skipped, len(instance_ids), len(fail_open))


def first_print_instant(
    catalog_root: Path,
    days: Collection[dt.date],
    *,
    work_root: Path,
    stations: Collection[str] = core.MAKER_STATIONS,
) -> int | None:
    """Earliest print ``ts_event`` across CLEAN instances, licensed to maker stations x ``days``.

    "Global" means across instances only: NYC, non-maker stations, NO-leg and undeclared-day
    prints never count. Timestamps only. ``None`` (no licensed print) is a STOP for the driver,
    never a zero or a default day.
    """
    day_set, station_set = frozenset(days), frozenset(stations)
    stamps: list[int] = []
    skipped: dict[str, str] = {}

    def visit(work: ParquetDataCatalog, _instance: str) -> None:
        licensed: dict[str, bool] = {}
        for t in work.query(data_cls=TradeTick):
            rung = str(t.instrument_id)
            if rung not in licensed:
                licensed[rung] = station_day_key(t.instrument_id, day_set, station_set) is not None
            if licensed[rung]:
                stamps.append(t.ts_event)

    _for_each_clean_instance(
        catalog_root,
        work_root,
        (TradeTick,),
        visit,
        skipped,
        sc.licensed_rung_filter(day_set, station_set),
        written_since_ns=prefilter_cutoff_ns(day_set, station_set),
        days=day_set,
        stations=station_set,
    )
    return min(stamps) if stamps else None


def _coverage(
    key: StationDay, ledger: _Ledger
) -> tuple[StationDayCoverage, list[InstanceDayDelta]]:
    station, day = key
    window = _maker_window(station, day)
    live_window = core.bidlive_window_ns(climate_day=day, window=window)  # process-live
    spans = ledger.spans.get(key, [])
    live, gap = live_and_gap_hours(live_window, spans)
    maker_live, maker_gap = live_and_gap_hours((window.start_ns, window.end_ns), spans)
    deltas = instance_day_deltas(ledger.samples.get(key, {}), live_window)
    listing = ledger.listing.get(key)
    row = StationDayCoverage(
        station, day.isoformat(), live, gap, listing,
        listing_abstain(listing, window.start_ns), station_day_delta(deltas),
        maker_live, maker_gap, sum(ledger.backwards.get(r, 0) for r in ledger.rungs.get(key, ())),
    )  # fmt: skip
    return row, [replace(d, station=station, climate_day=day.isoformat()) for d in deltas.values()]


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
    driver can write ``wp0_agreement.json`` before the S-2 STOP raises. The positive control is
    a subset of the pooled sample (not independent) -- read it as a per-station view.
    """
    sc.check_work_root(work_root, catalog_root)
    day_set, station_set = frozenset(days), frozenset(stations)
    cutoff = prefilter_cutoff_ns(day_set, station_set)  # raises on an unknown station: no spill yet
    ledger = _Ledger(FrameSpill(work_root / "_frames"))
    skipped: dict[str, str] = {}

    def visit(work: ParquetDataCatalog, instance_id: str) -> None:
        _read_instance(work, instance_id, day_set, station_set, ledger)

    rung_filter = sc.licensed_rung_filter(day_set, station_set)
    try:
        _for_each_clean_instance(
            catalog_root,
            work_root,
            _DIRECTION_STREAMS,
            visit,
            skipped,
            rung_filter,
            written_since_ns=cutoff,
            days=day_set,
            stations=station_set,
        )
        unique = unique_prints(ledger.prints)
        direction, control = fold_directions(unique, ledger.frames, control_station)
    finally:
        ledger.frames.close()
    rows = [_coverage((s, d), ledger) for s in stations for d in sorted(day_set)]
    deltas = [d for _row, ds in rows for d in ds]
    known = [r.delta_ns for r, _ds in rows if r.delta_ns is not None]
    return ProbeReport(
        days=tuple(sorted(d.isoformat() for d in day_set)),
        stations=tuple(stations),
        first_print_ns=first_print_ns,
        first_replayable_day=(
            None if first_print_ns is None else first_replayable_day(first_print_ns).isoformat()
        ),
        direction=direction,
        control=control,
        census=count_census(ledger.prints),
        depth_frames=ledger.depth_frames,
        truncated_frames=ledger.truncated_frames,
        coverage=tuple(row for row, _ds in rows),
        delta_instance_days=tuple(deltas),
        delta_distribution={
            **distribution(known),
            **delta_summary(deltas),
            "n_unknown": len(rows) - len(known),
        },
        ladder_parity=ladder_parity(ledger.rungs, stations),
        skipped=skipped,
    )
