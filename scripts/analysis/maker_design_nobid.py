"""MAKER design driver (cards 1 and 2): the Stage 0 maker simulator under three rule variants.

Arms (all replay the same fenced capture slice, read once per station-day, through the shipped
``replay_station_day`` / ``simulate_station_day``; nothing under ``maker_stage0_*`` is edited):

* ``control``        shipped rule (B_CAP 0.80, MAX_RUNGS 2) WITH the listing abstention: the
                     positive control, which must reproduce the Stage 0 verdict's per-station-day
                     table (``compare_with_reference``) or the driver is wrong;
* ``control_noabst`` the same rule without the abstention: the like-for-like comparator;
* ``nbp_deep``       B_CAP 0.84, MAX_RUNGS 3, no abstention (card 1);
* ``spike_bid``      the forecast-free selector of ``maker_design_spike_selector`` (card 2).

Departures from the Stage 0 verdict run, all disclosed in ``summary.json``: only the PRIMARY
variant is replayed; the recorder clock offset Delta is taken as 0 (the Stage 0 ``delta0`` variant
is the reference); node-log outage status is not consulted; the S1 census supplies the covered /
bid-live gate and the listing instant (``first_seen_ns``, equal to the probe's on all 96 block
station-days); the maker fee is the taker theta.

The fence is enforced here, not trusted: climate days are limited to ``LAST_ALLOWED_DAY`` and never
the sealed day, only the four maker stations, and the census and truth reads are scoped to that.
Truth is read only after every station-day has been simulated.

The rule constants ``B_CAP`` / ``MAX_RUNGS`` are bound at import time by ``maker_stage0_adapter``
(``MAX_RUNGS_PASSED``) and ``maker_stage0_events_build``, so setting ``rule`` before importing the
adapter works only for the first importer. ``rule_override`` instead rebinds all four module
attributes in place for the duration of one replay and restores them, which also works after the
modules are imported (tests, several arms in one process).

Each station-day runs in its own spawned child (memory is bounded by construction, as in
``maker_stage0_isolate``); the parent keeps the plan, the sinks and the scoring.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import multiprocessing as mp
import resource
import shutil
import subprocess
import sys
import time
from collections.abc import Collection, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Final

from breezy.analysis.maker_tape_census import CensusedDay
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration
from scripts.analysis import maker_design_score as score
from scripts.analysis import maker_stage0_adapter as adapter
from scripts.analysis import maker_stage0_events_build as events_build
from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_design_config import (
    ARMS,
    Arm,
    DesignConfig,
    DesignRefused,
    Key,
    check_out_dir,
    load_config,
    read_plan_cache,
    write_plan_cache,
)
from scripts.analysis.maker_design_spike_selector import ask_trails, build_spike_selector
from scripts.analysis.maker_stage0_adapter import WantTracker
from scripts.analysis.maker_stage0_catalog_read import (
    CatalogSession,
    StationDayPlan,
    query_window_ns,
)
from scripts.analysis.maker_stage0_events_build import (
    DataEvents,
    assert_before_local_midnight,
    clock_events,
    replay_station_day,
)
from scripts.analysis.maker_stage0_fill_events import (
    Episode,
    ForecastVector,
    RungSelector,
    StationDaySummary,
)
from scripts.analysis.maker_stage0_frozen import SEALED_DAY
from scripts.analysis.maker_stage0_inputs import load_census_days, load_trade_unit
from scripts.analysis.maker_stage0_runio import (
    EpisodeSink,
    PositionFold,
    PositionSeed,
    ProgressLog,
    peak_rss_bytes,
    read_rss_bytes,
)
from scripts.analysis.maker_stage0_schedule import primary_schedule
from scripts.analysis.maker_stage0_station_loop import (
    LoopContext,
    LoopOutput,
    _cut_specs,
    _data,
    _no_selector,
    _prepare,
    _Prepared,
    _selector_for,
    replays,
)

__all__ = [
    "abstains",
    "compare_with_reference",
    "flat_vector",
    "main",
    "plan_only",
    "rule_override",
    "run",
    "run_day",
    "select_station_days",
    "station_day_row",
]

COMPARED: Final[tuple[str, ...]] = (
    "bid_bearing", "n_attempts", "n_episodes", "n_refused", "rung_trials_posted",
    "rung_trials_filled_base", "rung_trials_filled_stress",
)  # fmt: skip
SD_COLUMNS: Final[tuple[str, ...]] = ("arm", "station", "climate_day", "late_listed", *COMPARED)

# --- arms ------------------------------------------------------------------------------------


@contextmanager
def rule_override(
    b_cap: float,
    max_rungs: int,
    *,
    p_min: float | None = None,
    e_min: float | None = None,
    b_floor: float | None = None,
) -> Iterator[None]:
    """Rebind the rule constants everywhere they are held, for one replay; always restored.

    P_MIN / E_MIN / B_FLOOR are read at call time inside ``maker_stage0_rule``; None leaves them.
    """
    extra = (("P_MIN", p_min), ("E_MIN", e_min), ("B_FLOOR", b_floor))
    patches = (
        (rule, "B_CAP", b_cap),
        (rule, "MAX_RUNGS", max_rungs),
        (adapter, "MAX_RUNGS_PASSED", max_rungs),
        (events_build, "MAX_RUNGS_PASSED", max_rungs),
        *((rule, name, value) for name, value in extra if value is not None),
    )
    saved = [(module, name, vars(module)[name]) for module, name, _ in patches]
    for module, name, value in patches:
        vars(module)[name] = value
    try:
        yield
    finally:
        for module, name, value in saved:
            vars(module)[name] = value


def flat_vector(at_ns: int) -> ForecastVector:
    """An empty vector in force: the simulator refuses any bid without one (forecast-free arms)."""
    return ForecastVector(at_ns, {}, {}, 0, "", "none")


def select_station_days(cfg: DesignConfig, census: Mapping[Key, CensusedDay]) -> list[Key]:
    """Covered, bid-live station-days in range (day-major), the sealed day never included."""
    span = (cfg.day_to - cfg.day_from).days + 1
    days = [cfg.day_from + dt.timedelta(days=n) for n in range(span)]
    return [
        (station, day)
        for day in days
        if day != SEALED_DAY
        for station in sorted(cfg.stations)
        if (station, day) in census and replays(census[(station, day)], None)
    ]


def abstains(row: CensusedDay) -> bool:
    """Spec section 3: a ladder first seen after D-1 12:00Z is replayed but never bid."""
    return not rule.listed_in_time(row.first_seen_ns, row.climate_day)


def _plans(
    cfg: DesignConfig, selected: Sequence[Key]
) -> tuple[dict[Key, StationDayPlan], dict[str, str]]:
    if cfg.plan_cache is not None and cfg.plan_cache.exists():
        return read_plan_cache(cfg.plan_cache)
    session = CatalogSession(cfg.catalog_root, cfg.work_root)
    try:
        plans = session.plan(sorted({d for _, d in selected}), sorted({s for s, _ in selected}))
    finally:
        session.close()
        shutil.rmtree(cfg.work_root, ignore_errors=True)
    if cfg.plan_cache is not None:
        write_plan_cache(cfg.plan_cache, plans, session.skipped)
    return plans, dict(session.skipped)


# --- one station-day (runs in a spawned child) -----------------------------------------------


@dataclass(frozen=True)
class DayJob:
    cfg: DesignConfig
    key: Key
    plan: StationDayPlan
    late_listed: bool


@dataclass(frozen=True)
class ArmDay:
    arm: str
    summary: StationDaySummary
    episodes: tuple[Episode, ...]
    seeds: tuple[PositionSeed, ...]


@dataclass(frozen=True)
class DayResult:
    key: Key
    arms: tuple[ArmDay, ...]
    n_events: int
    rss_bytes: int
    peak_bytes: int
    elapsed_s: float


def run_day(job: DayJob) -> DayResult:
    """Read the slice once, then replay every configured arm over the same events."""
    started = time.monotonic()
    cfg, (station, day) = job.cfg, job.key
    units = load_trade_unit(cfg.trade_unit).hypotheses()
    if len(units) != 1:
        raise DesignRefused(f"one trade-unit hypothesis expected, got {[u.name for u in units]}")
    sched = primary_schedule(day)
    session = CatalogSession(cfg.catalog_root, cfg.work_root / f"day_{station}_{day.isoformat()}")
    calibration = load_live_calibration(
        str(cfg.calibration), expected_sha256=cfg.calibration_sha256
    )
    ctx = LoopContext(
        units=units, primary={day: sched}, overlay={}, statuses={}, census={}, deltas={},
        plans={job.key: job.plan}, session=session, nbp_root=cfg.nbp_root,
        calibration=calibration, sink=None, variants=("primary",),
    )  # fmt: skip
    try:
        prep = _prepare(ctx, job.key, LoopOutput())
        data = _data(prep, units[0], job.key)
        arms = tuple(
            _replay_arm(ARMS[name], prep, data, units[0].name, job, sched.window_start_ns)
            for name in cfg.arms
        )
    finally:
        session.close()
        shutil.rmtree(session.work_root, ignore_errors=True)
    return DayResult(
        job.key, arms, data.n_events, read_rss_bytes(), peak_rss_bytes(), time.monotonic() - started
    )


def _replay_arm(
    arm: Arm, prep: _Prepared, data: DataEvents, unit: str, job: DayJob, live_from_ns: int
) -> ArmDay:
    station, day = job.key
    tracker = WantTracker()
    selector: RungSelector
    vectors: Sequence[ForecastVector]
    if arm.abstain and job.late_listed:
        selector, vectors = _no_selector, ()
    elif arm.spike:
        selector = build_spike_selector(prep.edges, ask_trails(data.events))
        vectors = (flat_vector(query_window_ns(station, day)[0]),)
    else:
        selector = _selector_for(prep, job.key, "none", arm.delta_ns, tracker)
        vectors = prep.vectors["none"]
    clock = clock_events(_cut_specs(primary_schedule(day), station, day), vectors)
    with rule_override(
        arm.b_cap, arm.max_rungs, p_min=arm.p_min, e_min=arm.e_min, b_floor=arm.b_floor
    ):
        replay = replay_station_day(
            data, clock, selector=selector, tracker=tracker, station=station, day=day,
            unit_hypothesis=unit, live_from_ns=live_from_ns, delta_ns=arm.delta_ns,
        )  # fmt: skip
    fold = PositionFold(station, day, unit)
    for episode in replay.result.episodes:
        assert_before_local_midnight(episode, station, day)
        fold.add(episode)
    return ArmDay(arm.name, replay.result.summary, replay.result.episodes, tuple(fold.seeds()))


# --- Stage 0 positive control ----------------------------------------------------------------


def station_day_row(
    summary: StationDaySummary, *, arm: str, late_listed: bool
) -> dict[str, object]:
    data = summary.to_dict()
    head = {"arm": arm, "station": data["station"], "climate_day": data["climate_day"]}
    return {**head, "late_listed": late_listed, **{c: data[c] for c in COMPARED}}


def _norm(value: object) -> str:
    return str(value).strip().lower()


def compare_with_reference(
    rows: Sequence[Mapping[str, object]], reference: Path, scope: Collection[tuple[str, str]]
) -> list[str]:
    """Every difference between this run's station-day rows and a Stage 0 station-day CSV.

    Only keys in ``scope`` that the reference knows are compared; a key the reference holds but
    this run lacks is reported as missing (never silently skipped).
    """
    with reference.open(encoding="utf-8", newline="") as handle:
        want = {(r["station"], r["climate_day"]): r for r in csv.DictReader(handle)}
    have = {(str(r["station"]), str(r["climate_day"])): r for r in rows}
    diffs: list[str] = []
    for key in sorted(scope):
        expected, got = want.get(key), have.get(key)
        where = f"{key[0]} {key[1]}"
        if expected is None:
            continue
        if got is None:
            diffs.append(f"{where}: missing from this run")
            continue
        diffs += [
            f"{where}: {col} {_norm(got[col])!r} != Stage 0 {_norm(expected[col])!r}"
            for col in COMPARED
            if _norm(got[col]) != _norm(expected[col])
        ]
    return diffs


# --- the run ---------------------------------------------------------------------------------


def _code_sha() -> str:
    root = Path(__file__).resolve().parents[2]
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


def _arm_dir(out: Path, arm: str) -> Path:
    path = out / arm
    path.mkdir(parents=True, exist_ok=True)
    return path


def _simulate(
    cfg: DesignConfig, keys: Sequence[Key], plans: Mapping[Key, StationDayPlan],
    census: Mapping[Key, CensusedDay], out: Path,
) -> list[DayResult]:  # fmt: skip
    progress = ProgressLog(out / "progress.jsonl")
    sinks = {arm: EpisodeSink(_arm_dir(out, arm) / "episodes.jsonl") for arm in cfg.arms}
    results: list[DayResult] = []
    pool = ProcessPoolExecutor(
        max_workers=cfg.workers, mp_context=mp.get_context("spawn"), max_tasks_per_child=1
    )
    try:
        jobs = [DayJob(cfg, key, plans[key], abstains(census[key])) for key in keys]
        futures = [pool.submit(run_day, job) for job in jobs]  # results are consumed in order
        for index, (key, future) in enumerate(zip(keys, futures, strict=True), 1):
            result = future.result()
            for arm_day in result.arms:
                for episode in arm_day.episodes:
                    sinks[arm_day.arm].write(episode)
            lean = tuple(replace(a, episodes=()) for a in result.arms)
            results.append(replace(result, arms=lean))
            progress.write(
                {
                    "index": index, "of": len(keys), "station": key[0],
                    "climate_day": key[1].isoformat(), "status": "done",
                    "elapsed_s": round(result.elapsed_s, 3), "rss_bytes": result.rss_bytes,
                    "n_events": result.n_events, "peak_rss_bytes": result.peak_bytes,
                }
            )  # fmt: skip
    finally:
        pool.shutdown(wait=True, cancel_futures=True)  # a failed day must not start the rest
        progress.close()
        for sink in sinks.values():
            sink.close()
    return results


def _score_arm(
    cfg: DesignConfig, arm: str, results: Sequence[DayResult], truth: Mapping[Key, int],
    out: Path, late: Mapping[Key, bool],
) -> tuple[list[dict[str, object]], dict[str, Any]]:  # fmt: skip
    grid = cfg.grid
    days = [(r.key, next(a for a in r.arms if a.arm == arm)) for r in results]
    sd_rows = [station_day_row(a.summary, arm=arm, late_listed=late[key]) for key, a in days]
    rows = score.position_rows([s for _, a in days for s in a.seeds], truth, grid, arm=arm)
    where = _arm_dir(out, arm)
    score.write_rows(where / "positions.csv", score.position_columns(grid), rows)
    score.write_rows(where / "station_days.csv", SD_COLUMNS, sd_rows)
    bid_days = [key[1] for key, a in days if a.summary.bid_bearing]
    stats = score.arm_stats(rows, grid, days=bid_days)
    stats["bid_bearing_station_days"] = len(bid_days)
    stats["late_listed_station_days"] = sum(late[key] for key, _ in days)
    stats["n_no_final"] = sum(r["win"] is None for r in rows if r["stress_pass"])
    return sd_rows, stats


def run(cfg: DesignConfig, out_dir: Path) -> dict[str, Any]:
    out = check_out_dir(out_dir)
    if cfg.work_root.exists() and any(cfg.work_root.iterdir()):
        raise DesignRefused(f"work_root {cfg.work_root} is not empty")
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    census_rows = load_census_days(cfg.census_days).rows
    census = {(r.station, r.climate_day): r for r in census_rows if r.climate_day <= cfg.day_to}
    selected = select_station_days(cfg, census)
    try:
        plans, skipped = _plans(cfg, selected)
        keys = [k for k in selected if k in plans]
        results = _simulate(cfg, keys, plans, census, out)
    finally:
        shutil.rmtree(cfg.work_root, ignore_errors=True)
    truth = score.load_truth(cfg.truth, cfg.stations, days=(cfg.day_from, cfg.day_to))
    late = {k: abstains(census[k]) for k in keys}
    arms: dict[str, Any] = {}
    sd_by_arm: dict[str, list[dict[str, object]]] = {}
    for arm in cfg.arms:
        sd_by_arm[arm], arms[arm] = _score_arm(cfg, arm, results, truth, out, late)
    diffs: list[str] | None = None
    if "control" in cfg.arms and cfg.reference is not None:
        scope = [(s, d.isoformat()) for s, d in selected]
        diffs = compare_with_reference(sd_by_arm["control"], cfg.reference, scope)
    for stats in arms.values():
        stats["label"] = score.label(stats, cfg.grid, valid=not diffs)
    summary = {
        "arms": arms,
        "positive_control": {"reference": str(cfg.reference), "differences": diffs},
        "selected_station_days": len(selected),
        "unplanned": [f"{s} {d.isoformat()}" for s, d in selected if (s, d) not in plans],
        "skipped_instances": dict(sorted(skipped.items())),
        "wall_s": time.monotonic() - started,
        "peak_rss_bytes": peak_rss_bytes(),
        "children_peak_rss_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
        "code_sha": _code_sha(),
        "config": {f.name: str(getattr(cfg, f.name)) for f in fields(cfg)},
        "departures": [
            "primary variant only", "Delta = 0", "no node-log outage status",
            "census supplies covered/bid-live and the listing instant", "maker fee = taker theta",
        ],
    }  # fmt: skip
    text = json.dumps(summary, indent=2, sort_keys=True, default=str)
    (out / "summary.json").write_text(text + "\n", encoding="utf-8")
    return summary


def plan_only(cfg: DesignConfig) -> Path:
    """Walk the catalog for the configured range and write ``cfg.plan_cache``; replay nothing."""
    if cfg.plan_cache is None:
        raise DesignRefused("--plan-only needs a plan_cache in the config")
    if cfg.plan_cache.exists():
        raise DesignRefused(f"plan cache {cfg.plan_cache} already exists")
    census_rows = load_census_days(cfg.census_days).rows
    census = {(r.station, r.climate_day): r for r in census_rows if r.climate_day <= cfg.day_to}
    _plans(cfg, select_station_days(cfg, census))
    return cfg.plan_cache


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MAKER design driver (cards 1 and 2)")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    if args.plan_only:
        sys.stdout.write(f"plan cache written: {plan_only(cfg)}\n")
        return 0
    if args.out_dir is None:
        parser.error("--out-dir is required unless --plan-only")
    summary = run(cfg, args.out_dir)
    for arm, stats in summary["arms"].items():
        line = f"{arm}: fills={stats['fills']} n_eff={stats['n_eff']:.2f} {stats['label']}"
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
