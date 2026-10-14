"""MAKER-S2 WP6: the simulation loop plumbing and the report-only run modes.

``--bench`` (timing and RSS only; heaviest station-days by catalog bytes; NO episode, fill, rate or
label output), ``--tail-only`` (writes only ``tail_reliability.csv`` plus a manifest that
records the code sha) and ``--verify-first`` (WP2 S-6 reader, climate day 2026-06-30 only). The
driver injects the patchable collaborators (calibration, RSS reader, verify-first reader) so
this module owns no global state; plan r4 delta (c)(i)7-9 and amendment s1 items 2, 3 and 5.
"""

from __future__ import annotations

import datetime as dt
import platform
import shutil
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

import nautilus_trader

from breezy.analysis.stats.scoring_core import BOOTSTRAP_ITERATIONS, BOOTSTRAP_SEED
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.quantile_density import Rung
from scripts.analysis import maker_stage0_report as report
from scripts.analysis.maker_stage0_catalog_read import CatalogSession
from scripts.analysis.maker_stage0_inputs import load_trade_unit
from scripts.analysis.maker_stage0_pins import git_commit
from scripts.analysis.maker_stage0_pno_store import PNoStore
from scripts.analysis.maker_stage0_run_types import (
    RSS_ABORT_BYTES,
    S5_MAX_SECONDS,
    MemoryAbort,
    Pre,
    RunConfig,
    RunSummary,
)
from scripts.analysis.maker_stage0_runio import (
    EpisodeSink,
    ProgressLog,
    heaviest,
    peak_rss_bytes,
    write_json,
)
from scripts.analysis.maker_stage0_schedule import (
    DaySchedule,
    day_log_status,
    overlay_schedule,
    process_schedule,
)
from scripts.analysis.maker_stage0_station_loop import LoopContext, LoopOutput, run_station_day
from scripts.analysis.maker_stage0_tables import tail_rows_to_csv

__all__ = [
    "build_context",
    "free_bytes",
    "run_bench",
    "run_tail",
    "run_verify_first",
    "simulate",
    "write_manifest",
]

TAIL_BAND_FLOOR_F: Final[int] = 10
TAIL_BAND_CEIL_F: Final[int] = 125
Key = tuple[str, dt.date]


def free_bytes(path: Path) -> int:
    existing = path
    while not existing.exists():
        existing = existing.parent
    return shutil.disk_usage(existing).free


def write_manifest(
    cfg: RunConfig, pre: Pre, mode: str, phases: Sequence[str], parity: dict[str, int]
) -> None:
    write_json(
        cfg.out_dir / "run_manifest.json",
        {
            "mode": mode,
            "run_id": cfg.out_dir.name,
            "argv": list(cfg.argv),
            "git_commit": pre.code_sha,
            "code_sha": pre.code_sha,
            "phases": list(phases),
            "python": platform.python_version(),
            "nautilus_version": nautilus_trader.__version__,
            "seed": BOOTSTRAP_SEED,
            "iterations": BOOTSTRAP_ITERATIONS,
            "peak_rss_bytes": peak_rss_bytes(),
            "wall_time_s": time.monotonic() - pre.started,
            "free_disk_start_bytes": pre.free_start,
            "free_disk_end_bytes": free_bytes(cfg.out_dir),
            "ladder_lower_parity": parity,
        },
    )


def build_context(
    cfg: RunConfig,
    pre: Pre,
    session: CatalogSession,
    deltas: dict[Key, int],
    *,
    sink: EpisodeSink | None,
    variants: tuple[str, ...],
    calibration: LiveCalibration,
) -> tuple[LoopContext, dict[dt.date, DaySchedule]]:
    days = sorted({d for _, d in pre.census})
    stations = sorted({s for s, _ in pre.census})
    overlay = overlay_schedule(days, pre.scans)
    ctx = LoopContext(
        units=load_trade_unit(cfg.trade_unit).hypotheses(),
        primary=process_schedule(days),
        overlay=overlay,
        statuses=day_log_status(days, pre.scans),
        census=pre.census,
        deltas=deltas,
        plans=session.plan(days, stations),
        session=session,
        nbp_root=cfg.nbp_root,
        calibration=calibration,
        sink=sink,
        variants=variants,
    )
    return ctx, overlay


def simulate(
    ctx: LoopContext,
    keys: Sequence[Key],
    progress: ProgressLog,
    out: LoopOutput,
    rss_fn: Callable[[], int],
) -> list[dict[str, Any]]:
    """Every station-day in order: one progress line each (no fill/rate/label), RSS watched."""
    timings: list[dict[str, Any]] = []
    for index, key in enumerate(keys, 1):
        started = time.monotonic()
        n_events = run_station_day(ctx, key, out)
        elapsed, rss = time.monotonic() - started, rss_fn()
        iso = key[1].isoformat()
        progress.write(
            {
                "index": index,
                "of": len(keys),
                "station": key[0],
                "climate_day": iso,
                "status": "done",
                "elapsed_s": round(elapsed, 3),
                "rss_bytes": rss,
                "n_events": n_events,
            }
        )
        timings.append(
            {"station": key[0], "climate_day": iso, "elapsed_s": elapsed, "rss_bytes": rss}
        )
        if rss > RSS_ABORT_BYTES:
            raise MemoryAbort(f"S-5: resident memory {rss} exceeds {RSS_ABORT_BYTES} at {key}")
    return timings


# --- bench ------------------------------------------------------------------------------------


def _rss_growth(rows: Sequence[dict[str, Any]]) -> float:
    if len(rows) < 2:
        return 0.0
    return float(rows[-1]["rss_bytes"] - rows[0]["rss_bytes"]) / (len(rows) - 1)


def run_bench(
    cfg: RunConfig, pre: Pre, calibration: LiveCalibration, rss_fn: Callable[[], int]
) -> RunSummary:
    """Time and weigh the heaviest station-days; the projection is a screen, not a proof (S-5)."""
    assert cfg.bench is not None
    cfg.out_dir.mkdir(parents=True)
    session = CatalogSession(cfg.catalog_root, cfg.work_root)
    progress = ProgressLog(cfg.out_dir / "progress.jsonl")
    try:
        ctx, _ = build_context(
            cfg, pre, session, {}, sink=None, variants=("primary",), calibration=calibration
        )
        weights = {k: ctx.plans[k].catalog_bytes for k in ctx.plans if k in pre.census}
        chosen = sorted(heaviest(weights, cfg.bench), key=lambda k: (k[1], k[0]))
        timings = simulate(ctx, chosen, progress, LoopOutput(), rss_fn)
    finally:
        progress.close()
        session.close()
        shutil.rmtree(cfg.work_root, ignore_errors=True)
    by_iso = {(s, d.isoformat()): n for (s, d), n in weights.items()}
    rows = [
        {
            **t,
            "catalog_bytes": by_iso[(t["station"], t["climate_day"])],
            "peak_rss_bytes": t["rss_bytes"],
        }
        for t in timings
    ]
    total = len(weights)
    mean_s = sum(r["elapsed_s"] for r in rows) / max(1, len(rows))
    peak = max((r["peak_rss_bytes"] for r in rows), default=0)
    projected = peak + int(max(0.0, _rss_growth(rows)) * max(0, total - len(rows)))
    write_json(
        cfg.out_dir / "bench.json",
        {
            "station_days": rows,
            "n_replayable_station_days": total,
            "projected_total_s": mean_s * total,
            "projected_peak_rss_bytes": projected,
            "s5_exceeded": mean_s * total > S5_MAX_SECONDS or projected > RSS_ABORT_BYTES,
            "code_sha": pre.code_sha,
        },
    )
    write_manifest(cfg, pre, "bench", ["preflight", "simulate"], {})
    return RunSummary(cfg.out_dir, None, pre.code_sha, "bench")


# --- tail-only --------------------------------------------------------------------------------


def tail_bands(parity: int) -> dict[str, tuple[int, int]]:
    """Every inclusive 2 F band on the station's parity (no open tails)."""
    first = TAIL_BAND_FLOOR_F + ((parity - TAIL_BAND_FLOOR_F) % 2)
    return {f"{lo}-{lo + 1}": (lo, lo + 1) for lo in range(first, TAIL_BAND_CEIL_F, 2)}


def run_tail(
    cfg: RunConfig, pre: Pre, calibration: LiveCalibration, tail_range: tuple[dt.date, dt.date]
) -> RunSummary:
    """Report-only: the tail-reliability CSV, nothing else (no fill, rate, episode or label)."""
    assert cfg.parity is not None
    cfg.out_dir.mkdir(parents=True)
    first, last = tail_range
    days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    parity = dict(cfg.parity)
    truth = report.load_tail_truth(
        cfg.truth,
        cfg.truth_cross_check,
        cfg.work_root / "tail_truth",
        pre.frozen.truth_csv_sha256,
        {(s, d) for s in parity for d in days},
    )
    rows = []
    for station, p in sorted(parity.items()):
        bands = tail_bands(p)
        rungs = [Rung(rung_id=i, lo=lo, hi=hi) for i, (lo, hi) in bands.items()]
        for day in days:
            store = PNoStore.from_root(
                cfg.nbp_root,
                stations=[station],
                days=[day],
                calibration=calibration,
                ladders={(station, day): rungs},
            )
            tmax = truth.finals.get((station, day))
            rows += report.tail_rows_for(store, station, day, tmax, bands)
    shutil.rmtree(cfg.work_root, ignore_errors=True)
    (cfg.out_dir / "tail_reliability.csv").write_text(tail_rows_to_csv(rows), encoding="utf-8")
    write_manifest(cfg, pre, "tail-only", ["preflight", "tail"], parity)
    return RunSummary(cfg.out_dir, None, pre.code_sha, "tail-only")


# --- verify-first -----------------------------------------------------------------------------


def run_verify_first(
    cfg: RunConfig, reader: Callable[[Path, dt.date], Any], day: dt.date, n_frozen_dates: int
) -> RunSummary:
    """WP2 S-6 on ``day`` only; alignment and vintage-age lines, never a fill, bid or p_NO."""
    cfg.out_dir.mkdir(parents=True)
    write_json(cfg.out_dir / "verify_first.json", reader(cfg.nbp_root, day))
    code_sha = git_commit(cfg.repo_root)
    write_json(
        cfg.out_dir / "run_manifest.json",
        {
            "mode": "verify-first",
            "run_id": cfg.out_dir.name,
            "argv": list(cfg.argv),
            "git_commit": code_sha,
            "day": day,
            "amendment_sha": cfg.amendment_sha,
            "frozen_dates": n_frozen_dates,
        },
    )
    return RunSummary(cfg.out_dir, None, code_sha, "verify-first")
