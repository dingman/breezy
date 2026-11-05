"""INC-8 -- the hypothetical-hold corpus for the intra-day position monitor.

Spec: ``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` Rev 2 sec 0/6
(INC-8 row) and the Rev 2.1 addendum (A4, P5, P6). Offline analysis only --
BUILD-TIME, never touches the live node or strategy (D7: "Evaluation via the
v3 backtest subclass / paper replay under TestClock, no look-ahead; plus a
hypothetical-hold corpus over the archived tape" -- this module is that
second leg).

WHAT THIS IS
------------
For every (station, climate_day) in a requested window, this module replays
the ARCHIVED Depth10 + NWS-observation tape in ``ts_init`` order and asks two
questions:

1. Would the live strategy's OWN entry rule (``evaluate_decision``,
   unmodified, imported -- never re-derived) have taken a position that day,
   and at what snapshot? (:func:`select_hypothetical_holds`, reusing the
   study's own "first executable snapshot is the trial" selection rule --
   ``mb_current_rung_edge_study.first_executable_trial`` -- L-34: the
   trigger selects the estimand, so this is the SAME first-snapshot rule the
   live strategy is pinned to, never a re-look.)
2. From that instant forward, what would the SHADOW MONITOR
   (``monitor_evidence.build_monitor_evidence`` +
   ``monitor_decision.evaluate_monitor``, both imported unmodified) have
   said, evaluated against every LATER observation and Depth10 frame with
   ``ts_init > take.ts_ns`` only -- never a look-ahead peek?
   (:func:`replay_monitor`.)

Every take is joined against NWS CLI FINAL settlement truth
(``settlement_truth_dataset.bucket_facts``/``settles_yes`` -- PRELIMINARY
records are never used, matching the live scorer) to produce
``settled_pnl``/``settled_held``, and the whole corpus is written in the
SAME ``PositionMonitorSummary`` schema as the live monitor
(``monitor_store.write_monitor_summaries``) with ``entry_context=
"hypothetical"`` and ``trial_id`` prefixed ``hypo:`` -- so INC-6's nightly
report can join this corpus exactly the way it joins the live one, and can
never confuse a hypothetical row for a real trial (the prefix is a second,
independent barrier alongside ``entry_context``).

L-1 (native vs authored): this module is a pure GAP-FILLER glue layer. Every
piece of real machinery it needs already exists and is imported unmodified:
``evaluate_decision``/``DecisionInputs`` (the live entry rule),
``RunningExtremeAccumulator`` (the live running-max accumulator),
``build_monitor_evidence``/``evaluate_monitor`` (the shadow monitor, built by
a concurrent agent for this same plan), ``bucket_facts``/``settles_yes`` (the
settlement predicate), ``discover_station_days``/``instrument_ids_for``/
``parse_ladder`` (the study's own station-day/ladder discovery), and
``iem_asos_rows_to_station_observations`` (the archive observation parser).
Nothing here reimplements any of those; this module's only original content
is the REPLAY LOOP that drives them together and the descriptive
``CorpusReport`` aggregation.

Streaming and memory (plan CLI note): the CLI processes ONE station-day at a
time, mirroring ``mb_current_rung_edge_study.py``'s per-day loop -- an ASOS
archive fetch is cached once per STATION (a single multi-year text blob) and
sliced per day before feeding a station-day's own, freshly-constructed
``RunningExtremeAccumulator`` (the accumulator resets its held rows on every
climate-day change, so it is NOT reusable bulk-loaded across days -- see
``RunningExtremeAccumulator.push``'s day-boundary reset). Depth10 frames are
read per station-day via ``ParquetDataCatalog.query(OrderBookDepth10,
identifiers=...)``, never the whole catalog at once.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h4_preliminary_economic_read import Rung, parse_ladder
from ma_prelock_winner_ask_study import (
    ASOS_FETCH_END,
    ASOS_FETCH_START,
    DEFAULT_QUOTE_TAPE_CATALOG,
    DEFAULT_SETTLEMENT_CATALOG,
    discover_station_days,
    instrument_ids_for,
    load_settled_tmax_for_day,
)
from monitor_hypothetical_core import (
    ARCHIVE_HOURS,
    TRIAL_ID_PREFIX,
    WINDOW_END_HOUR_LST,
    WINDOW_START_HOUR_LST,
    HypotheticalTake,
    InstrumentTape,
    LookAheadError,
    ObservationRow,
    ReplayDiagnostics,
    replay_monitor,
    select_hypothetical_holds,
)
from monitor_hypothetical_report import (
    CALIBRATION_FLOOR_STATION_DAYS,
    CorpusReport,
    SkippedStationDay,
    build_corpus_report,
)
from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    SiteSpec,
    asos_url,
    cache_path_for_url,
    load_sites,
    parse_asos_rows,
)

from breezy.domain.climate_day import climate_day_for_instant
from breezy.ingest.iem_observations import iem_asos_rows_to_station_observations
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import RungBounds
from breezy.strategy.current_rung_hold.monitor_records import PositionMonitorSummary
from breezy.strategy.current_rung_hold.monitor_store import write_monitor_summaries
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

__all__ = [
    "ARCHIVE_HOURS",
    "CALIBRATION_FLOOR_STATION_DAYS",
    "TRIAL_ID_PREFIX",
    "WINDOW_END_HOUR_LST",
    "WINDOW_START_HOUR_LST",
    "CorpusReport",
    "HypotheticalTake",
    "InstrumentTape",
    "LookAheadError",
    "ObservationRow",
    "ReplayDiagnostics",
    "SkippedStationDay",
    "build_corpus_report",
    "replay_monitor",
    "select_hypothetical_holds",
]

# ---------------------------------------------------------------------------
# I/O -- real catalog and archive reads (never exercised by the unit tests)
# ---------------------------------------------------------------------------


def _load_observations_for_station(
    *, cache_dir: Path, spec: SiteSpec, start: dt.date, end: dt.date,
) -> tuple[ObservationRow, ...]:
    """Every archive observation for one station whose climate day falls in
    ``[start, end]``, parsed ONCE per station (never per day) -- the CLI
    slices this per climate day before pushing into a fresh accumulator
    (module docstring).

    The ASOS cache is keyed by the FIXED ``ASOS_FETCH_START``/``ASOS_FETCH_END``
    window -- the SAME window ``mb_current_rung_edge_study.py`` uses and the
    nightly ``asos_recent_refresh.py --since`` refresh populates -- never by
    this run's own ``--start``/``--end``. Keying by the run's own window (the
    prior bug) produces a cache key the nightly refresh never wrote, so every
    corpus run other than one over the exact refresh window missed. Rows
    outside the requested ``[start, end]`` are dropped here so the
    accumulator this feeds never sees more than the requested day range (no
    look-ahead).
    """
    raw_path = cache_path_for_url(
        cache_dir, asos_url(spec.iem_asos_id, ASOS_FETCH_START, ASOS_FETCH_END), ".txt",
    )
    if not raw_path.exists():
        raise SystemExit(f"ASOS cache miss for {spec.city}; expected: {raw_path}")
    rows = parse_asos_rows(raw_path.read_text(encoding="utf-8", errors="replace"))
    _placeholder_received_at_ns: Final[int] = 2**62
    parsed, _drops = iem_asos_rows_to_station_observations(
        station=spec.iem_asos_id,
        rows=rows,
        source_channel="iem_asos_metar_hypothetical_hold",
        assumed_publication_lag_ns=1,
        received_at_ns=_placeholder_received_at_ns,
    )
    return tuple(
        ObservationRow(
            observed_at_ns=record.observed_at_ns,
            temp_c_tenths=record.temp_c_tenths,
            precision_c_tenths=record.precision_c_tenths,
            is_metar=record.is_metar,
        )
        for record in parsed
        if start
        <= climate_day_for_instant(
            dt.datetime.fromtimestamp(record.observed_at_ns / 1_000_000_000, tz=dt.UTC),
            spec.std_utc_offset_hours,
        )
        <= end
    )


def _accumulator_for_day(
    *,
    observations: Sequence[ObservationRow],
    climate_day: dt.date,
    std_utc_offset_hours: float,
) -> RunningExtremeAccumulator:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=std_utc_offset_hours)
    for row in observations:
        day = climate_day_for_instant(
            dt.datetime.fromtimestamp(row.observed_at_ns / 1_000_000_000, tz=dt.UTC),
            std_utc_offset_hours,
        )
        if day != climate_day:
            continue
        accumulator.push(
            row.observed_at_ns,
            row.temp_c_tenths,
            row.precision_c_tenths,
            row.is_metar,
            row.observed_at_ns,
        )
    return accumulator


def _load_depth_frames(
    *, catalog_root: Path, instrument_ids: Sequence[str],
) -> dict[str, tuple[OrderBookDepth10, ...]]:
    catalog = ParquetDataCatalog(str(catalog_root))
    rows = catalog.query(OrderBookDepth10, identifiers=list(instrument_ids))
    grouped: dict[str, list[OrderBookDepth10]] = {}
    for row in rows:
        grouped.setdefault(str(row.instrument_id), []).append(row)
    return {
        instrument_id: tuple(sorted(frames, key=lambda frame: frame.ts_init))
        for instrument_id, frames in grouped.items()
    }


def _ladder_for(instrument_ids: Sequence[str]) -> tuple[Rung, ...]:
    return parse_ladder(instrument_ids)


def run_hypothetical_hold_corpus(
    *,
    catalog_root: Path,
    nws_root: Path,
    settlement_catalog: Path,
    start: dt.date,
    end: dt.date,
    stations: Sequence[str],
) -> tuple[
    tuple[tuple[HypotheticalTake, PositionMonitorSummary, ReplayDiagnostics], ...],
    tuple[SkippedStationDay, ...],
]:
    """The real, streaming, per-station-day I/O driver (never called by the
    unit tests -- see the module docstring's memory note).
    """
    config = CurrentRungHoldConfig(stations=tuple(stations))
    fee_coefficient = config.required_fee_coefficient
    stale_observation_bound_ns = config.stale_observation_minutes * 60_000_000_000

    specs_by_city = {spec.city: spec for spec in load_sites() if spec.city in stations}
    depth_root = catalog_root / "data" / "order_book_depths"
    if not depth_root.is_dir():
        raise SystemExit(f"no depth catalog at {depth_root}")

    station_days = discover_station_days(
        depth_root=depth_root, cities=stations, fetch_start=start, fetch_end=end,
    )

    observations_by_station: dict[str, tuple[ObservationRow, ...]] = {}
    results: list[tuple[HypotheticalTake, PositionMonitorSummary, ReplayDiagnostics]] = []
    skipped: list[SkippedStationDay] = []

    for city, climate_day in station_days:
        spec = specs_by_city[city]
        if city not in observations_by_station:
            observations_by_station[city] = _load_observations_for_station(
                cache_dir=nws_root, spec=spec, start=start, end=end,
            )
        accumulator = _accumulator_for_day(
            observations=observations_by_station[city],
            climate_day=climate_day,
            std_utc_offset_hours=spec.std_utc_offset_hours,
        )

        instrument_ids = instrument_ids_for(
            depth_root=depth_root, city=city, climate_day=climate_day,
        )
        if not instrument_ids:
            skipped.append(
                SkippedStationDay(station=city, climate_day=climate_day, reason="no_depth10"),
            )
            continue
        ladder_rungs = _ladder_for(instrument_ids)
        ladder_bounds: tuple[RungBounds, ...] = tuple(
            (rung.lower_f, rung.upper_f) for rung in ladder_rungs
        )
        depth_by_id = _load_depth_frames(catalog_root=catalog_root, instrument_ids=instrument_ids)
        instruments = tuple(
            InstrumentTape(
                instrument_id=rung.instrument_id,
                rung=(rung.lower_f, rung.upper_f),
                depth_frames=depth_by_id.get(rung.instrument_id, ()),
            )
            for rung in ladder_rungs
        )
        if not any(tape.depth_frames for tape in instruments):
            skipped.append(
                SkippedStationDay(station=city, climate_day=climate_day, reason="no_depth10"),
            )
            continue

        take = select_hypothetical_holds(
            station=city,
            climate_day=climate_day,
            std_utc_offset_hours=spec.std_utc_offset_hours,
            config=config,
            fee_coefficient=fee_coefficient,
            ladder=ladder_bounds,
            instruments=instruments,
            accumulator=accumulator,
        )
        if take is None:
            skipped.append(
                SkippedStationDay(
                    station=city, climate_day=climate_day, reason="no_executable_snapshot",
                ),
            )
            continue

        tmax_f, _count, _provenance = load_settled_tmax_for_day(
            catalog_base=settlement_catalog, city=city, climate_day=climate_day,
        )
        if tmax_f is None:
            skipped.append(
                SkippedStationDay(
                    station=city, climate_day=climate_day, reason="no_settlement_truth",
                ),
            )
            continue

        taken_tape = next(tape for tape in instruments if tape.instrument_id == take.instrument_id)
        subsequent_depth = tuple(
            frame for frame in taken_tape.depth_frames if frame.ts_init > take.ts_ns
        )
        subsequent_observation_ts_ns = tuple(
            sorted(
                {
                    row.observed_at_ns
                    for row in observations_by_station[city]
                    if row.observed_at_ns > take.ts_ns
                    and climate_day_for_instant(
                        dt.datetime.fromtimestamp(row.observed_at_ns / 1_000_000_000, tz=dt.UTC),
                        spec.std_utc_offset_hours,
                    )
                    == climate_day
                },
            )
        )
        summary, diagnostics = replay_monitor(
            take=take,
            accumulator=accumulator,
            std_utc_offset_hours=spec.std_utc_offset_hours,
            fee_coefficient=fee_coefficient,
            stale_observation_bound_ns=stale_observation_bound_ns,
            subsequent_depth_frames=subsequent_depth,
            subsequent_observation_ts_ns=subsequent_observation_ts_ns,
            tmax_f=tmax_f,
        )
        results.append((take, summary, diagnostics))

    return tuple(results), tuple(skipped)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_QUOTE_TAPE_CATALOG)
    parser.add_argument("--nws-root", type=Path, default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR)
    parser.add_argument("--settlement-catalog", type=Path, default=DEFAULT_SETTLEMENT_CATALOG)
    parser.add_argument("--start", required=True, type=str)
    parser.add_argument("--end", required=True, type=str)
    parser.add_argument(
        "--stations", nargs="+", default=list(CurrentRungHoldConfig().stations),
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    results, skipped = run_hypothetical_hold_corpus(
        catalog_root=args.catalog_root,
        nws_root=args.nws_root,
        settlement_catalog=args.settlement_catalog,
        start=start,
        end=end,
        stations=tuple(args.stations),
    )
    now_ns = int(dt.datetime.now(tz=dt.UTC).timestamp() * 1_000_000_000)
    if results:
        write_monitor_summaries(out_dir, [summary for _, summary, _ in results], now_ns=now_ns)
    report = build_corpus_report(
        results=results,
        skipped_station_days=skipped,
        window_start=start,
        window_end=end,
        stations=tuple(args.stations),
        generated_at_ns=now_ns,
    )
    report_path = out_dir / f"hypothetical_hold_corpus_report_{now_ns}.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    print(f"[hypothetical-hold] {len(results)} trial(s); wrote {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
