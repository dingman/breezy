"""MAKER-S2 WP6: the simulation loop plumbing and the report-only run modes.

``--bench N`` (N in {4, 8}; timing and RSS only; the heaviest REPLAYED station-days by catalog
bytes, every variant run; NO episode, fill, rate or label output), the loop's context builder and
its RSS-watched ``simulate``. ``--tail-only`` lives in ``maker_stage0_report`` (the one module that
may load truth), ``--verify-first`` and the pin sources in ``maker_stage0_finish``; nothing here
can reach the truth loader or the pins module, so the simulation loop's import closure stays
truth-free. The driver injects the patchable collaborators (calibration, RSS
readers, verify-first reader) so this module owns no global state; plan r4 delta (c)(i)7-9 and
amendment s1 items 2, 3 and 5.
"""

from __future__ import annotations

import datetime as dt
import platform
import shutil
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import nautilus_trader

from breezy.analysis.stats.scoring_core import BOOTSTRAP_ITERATIONS, BOOTSTRAP_SEED
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from scripts.analysis.maker_stage0_bench_screen import project_bench
from scripts.analysis.maker_stage0_catalog_read import CatalogSession
from scripts.analysis.maker_stage0_inputs import load_trade_unit
from scripts.analysis.maker_stage0_run_types import (
    BENCH_COUNTS,
    RSS_ABORT_BYTES,
    MemoryAbort,
    Pre,
    RunConfig,
    RunSummary,
    SubsetRefused,
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
from scripts.analysis.maker_stage0_station_loop import (
    VARIANTS,
    LoopContext,
    LoopOutput,
    replays,
    run_station_day,
)

__all__ = [
    "build_context",
    "free_bytes",
    "peak_watch",
    "run_bench",
    "simulate",
    "write_manifest",
]

Key = tuple[str, dt.date]


def free_bytes(path: Path) -> int:
    existing = path
    while not existing.exists():
        existing = existing.parent
    return shutil.disk_usage(existing).free


def write_manifest(
    cfg: RunConfig,
    pre: Pre,
    mode: str,
    phases: Sequence[str],
    parity: dict[str, int],
    verdict: str | None = None,
) -> None:
    extra = {} if verdict is None else {"verdict": verdict}
    write_json(
        cfg.out_dir / "run_manifest.json",
        {
            **extra,
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


def peak_watch(peak_fn: Callable[[], int]) -> Callable[[], None]:
    """S-5 inside the day: ``ru_maxrss`` is checked after every (hypothesis, variant) pass."""

    def watch() -> None:
        peak = peak_fn()
        if peak > RSS_ABORT_BYTES:
            raise MemoryAbort(f"S-5: peak resident memory {peak} exceeds {RSS_ABORT_BYTES}")

    return watch


def build_context(
    cfg: RunConfig,
    pre: Pre,
    session: CatalogSession,
    deltas: dict[Key, int],
    *,
    sink: EpisodeSink | None,
    variants: tuple[str, ...],
    calibration: LiveCalibration,
    peak_fn: Callable[[], int] = peak_rss_bytes,
    abstained: frozenset[Key] = frozenset(),
) -> tuple[LoopContext, dict[dt.date, DaySchedule]]:
    days = sorted({d for _, d in pre.census})
    stations = sorted({s for s, _ in pre.census})
    overlay = overlay_schedule(days, pre.scans)
    ctx = LoopContext(
        units=load_trade_unit(cfg.need("trade_unit")).hypotheses(),
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
        abstained=abstained,
        watch=peak_watch(peak_fn),
    )
    return ctx, overlay


def simulate(
    ctx: LoopContext,
    keys: Sequence[Key],
    progress: ProgressLog,
    out: LoopOutput,
    rss_fn: Callable[[], int],
    peak_fn: Callable[[], int] = peak_rss_bytes,
) -> list[dict[str, Any]]:
    """Every station-day in order: one progress line each (no fill/rate/label), RSS watched.

    Per station-day the ``ru_maxrss`` delta is recorded; the in-day peak check runs inside
    ``run_station_day`` (``ctx.watch``) and again here when the line is written.
    """
    timings: list[dict[str, Any]] = []
    for index, key in enumerate(keys, 1):
        started, peak_before = time.monotonic(), peak_fn()
        n_events = run_station_day(ctx, key, out)
        elapsed, rss, peak = time.monotonic() - started, rss_fn(), peak_fn()
        measured = {
            "elapsed_s": round(elapsed, 3),
            "rss_bytes": rss,
            "n_events": n_events,
            "rss_peak_delta_bytes": max(0, peak - peak_before),
            "peak_rss_bytes": peak,
        }
        iso = key[1].isoformat()
        where = {"station": key[0], "climate_day": iso}
        progress.write({"index": index, "of": len(keys), **where, "status": "done", **measured})
        timings.append({**where, **measured})
        worst = max(rss, peak)
        if worst > RSS_ABORT_BYTES:
            raise MemoryAbort(f"S-5: resident memory {worst} exceeds {RSS_ABORT_BYTES} at {key}")
    return timings


# --- bench ------------------------------------------------------------------------------------


def run_bench(
    cfg: RunConfig,
    pre: Pre,
    calibration: LiveCalibration,
    rss_fn: Callable[[], int],
    peak_fn: Callable[[], int] = peak_rss_bytes,
) -> RunSummary:
    """Time and weigh the heaviest REPLAYED station-days over every variant (a screen, S-5)."""
    count = cfg.bench
    if count not in BENCH_COUNTS:
        raise SubsetRefused(f"--bench N must be one of {BENCH_COUNTS}, got {count}")
    cfg.out_dir.mkdir(parents=True)
    session = CatalogSession(cfg.catalog_root, cfg.work_root)
    progress = ProgressLog(cfg.out_dir / "progress.jsonl")
    try:
        variants = tuple(VARIANTS)
        ctx, _ = build_context(
            cfg, pre, session, {}, sink=None, variants=variants, calibration=calibration,
            peak_fn=peak_fn,
        )  # fmt: skip
        weights = {
            k: plan.catalog_bytes
            for k, plan in ctx.plans.items()
            if k in pre.census and replays(pre.census[k], ctx.statuses.get(k[1]))
        }
        chosen = sorted(heaviest(weights, count or 0), key=lambda k: (k[1], k[0]))
        timings = simulate(ctx, chosen, progress, LoopOutput(), rss_fn, peak_fn)
    finally:
        progress.close()
        session.close()
        shutil.rmtree(cfg.work_root, ignore_errors=True)
    _write_bench(cfg, pre, timings, weights, variants)
    write_manifest(cfg, pre, "bench", ["preflight", "simulate"], {})
    return RunSummary(cfg.out_dir, None, pre.code_sha, "bench")


def _write_bench(
    cfg: RunConfig,
    pre: Pre,
    timings: Sequence[dict[str, Any]],
    weights: dict[Key, int],
    variants: tuple[str, ...],
) -> None:
    by_iso = {(s, d.isoformat()): n for (s, d), n in weights.items()}
    rows = [{**t, "catalog_bytes": by_iso[(t["station"], t["climate_day"])]} for t in timings]
    proj = project_bench(rows, len(weights), sum(weights.values()))
    write_json(
        cfg.out_dir / "bench.json",
        {
            "station_days": rows,
            "variants": list(variants),
            "n_replayable_station_days": len(weights),
            "projected_total_s": proj.projected_total_s,
            "projected_total_s_by_count": proj.projected_total_s_by_count,
            "projected_peak_rss_bytes": proj.projected_peak_rss_bytes,
            "rss_slope_bytes_per_row": proj.rss_slope_bytes_per_row,
            "s5_exceeded": proj.s5_exceeded,
            "code_sha": pre.code_sha,
        },
    )
