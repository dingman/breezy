"""EXEC-PAR BG-10(c): the pre-registered D-PREREG section 5 simulation outputs.

Pure simulation functions plus one run that writes a JSON artefact. Offline, seeded, no network.

DATA RULE (absolute). Every input is dated before 2026-10-07; the dhat v2 guards refuse anything
later BEFORE any work. The M1-v3 window, the F13 sealed holdout and PREREG.json are never read.

Method
  * V1 (BG-10 level): the p_amb at which the section 3 stop rule (K=6, one stuck slot, bucket 0.05,
    worse free-balance arm, p90 CI upper bound, EVERY seed) reaches 0.30. Scan then bisection.
  * Stage model (K=2, stage S1): for every empirical pre-window day (candidate counts and intraday
    arm times from the candidate file, zero-candidate days included) simulate ``draws`` days through
    the production admit engine; a stage is 15 days sampled with replacement from those pools. So
    entries/day is the empirical candidate count times the SIMULATED K=2 admission rate, with its
    sampling variation; AMBIGUOUS outcomes are day-overdispersed (beta-binomial by day, rho).
  * Halts: Clopper-Pearson (alpha 0.01, n >= 20, LB > 0.18, stage-cumulative, checked after every
    entry) and the 60-minute burst on ARM times (empirical intraday times).
  * Promotion: two-look Wilson-DEFF schedule (see exec_par_bg10_stats).
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import hashlib
import json
import math
import multiprocessing
import random
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

HERE: Final[Path] = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import exec_par_bg10_stats as stats
import exec_parallel_dhat_v2 as dhat

IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

DEFAULT_OUT: Final[Path] = HERE / "exec_par_bg10_results.json"
STAGE_DAYS: Final[int] = stats.STAGE_CAP_DAYS
NEVER: Final[int] = STAGE_DAYS + 1  # "no halt inside the stage"
STAGE_K: Final[int] = 2  # S1
STAGE_BUCKET: Final[float] = 0.05
STAGE_FREE0: Final[float] = dhat.FREE0_DEFAULT
LEVEL_K: Final[int] = 6
LEVEL_BUCKET: Final[float] = 0.05
LEVEL_STUCK: Final[int] = 1
BURST_WINDOW_NS: Final[int] = 3600 * dhat.NS
CP_ALPHA: Final[float] = 0.01
CP_P0: Final[float] = 0.18
CP_MIN_N: Final[int] = 20
P_TRUE: Final[float] = 0.18
POWER_PS: Final[tuple[float, ...]] = (0.33, 0.45)
POWER_DAYS: Final[int] = 5
RHOS: Final[tuple[float, ...]] = (0.0, 0.1)
V1_MIN: Final[float] = 0.33
V2_MIN: Final[float] = 0.80
V3_MAX: Final[float] = 0.20
LEVEL_BAR: Final[float] = dhat.STOP_BAR
LEVEL_TOL: Final[float] = 0.002
LEVEL_GRID: Final[tuple[float, ...]] = (0.20, 0.25, 0.30, 0.33, 0.36, 0.40, 0.45, 0.50, 0.60, 0.70)
MIN_AMB_FOR_ICC: Final[int] = 20  # fewer AMBIGUOUS orders cannot resolve a between-day variance
ORDER_DAY_SHIFT_HOURS: Final[int] = 6  # order -> climate day; insensitive for shifts of 3..12 h
MAX_GEN_RHO: Final[float] = 0.95  # beta_params needs rho < 1
DEFAULT_DRAWS: Final[int] = 2000
DEFAULT_RUNS: Final[int] = 100_000
DEFAULT_BOOT_RUNS: Final[int] = 2000


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


# ---- ICC from the pre-window order table -----------------------------------------------------
def icc_groups_from_orders(path: Path) -> list[tuple[int, int]]:
    """``(posted orders, AMBIGUOUS orders)`` per climate day from the pre-window order table."""
    dhat.refuse_window_path(path)
    with path.open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    by_day: dict[dt.date, list[int]] = {}
    for row in rows:
        stamp = dt.datetime.fromisoformat(row["submit_ts"][:19]).replace(tzinfo=dt.UTC)
        dhat.refuse_window_day(stamp.date())
        if row["posted"] != "Y":
            continue
        day = (stamp - dt.timedelta(hours=ORDER_DAY_SHIFT_HOURS)).date()
        counts = by_day.setdefault(day, [0, 0])
        counts[0] += 1
        counts[1] += 1 if row["outcome"] == "AMBIGUOUS" else 0
    return [(m, y) for _, (m, y) in sorted(by_day.items())]


def icc_report(groups: Sequence[tuple[int, int]], *, boot_runs: int, seed: int) -> dict[str, Any]:
    """The pre-window ANOVA ICC, its day-bootstrap instability, and the ICC used."""
    est = stats.anova_icc(groups)
    n_amb = sum(y for _, y in groups)
    too_few = n_amb < MIN_AMB_FOR_ICC
    rng = np.random.default_rng(seed)
    used: list[float] = []
    raws: list[float] = []
    k = len(groups)
    for _ in range(boot_runs):
        pick = rng.integers(0, k, size=k) if k else []
        boot = stats.anova_icc([groups[i] for i in pick])
        raws.append(boot.raw)
        used.append(boot.used)
    defined = [r for r in raws if not math.isnan(r)]
    pct = np.percentile(np.asarray(used), [5, 50, 95]) if used else [math.nan] * 3
    return {
        "estimate_raw": est.raw,
        "n0": est.n0,
        "estimate_floored": est.used,
        "n_days": est.groups,
        "n_posted": est.total,
        "n_ambiguous": n_amb,
        "min_ambiguous_for_meaningful_icc": MIN_AMB_FOR_ICC,
        "too_few_ambiguous": too_few,
        "icc_used": stats.ICC_FLOOR if too_few else est.used,
        "rule": "one-way ANOVA ICC, n0 weighting, floored at 0.1; ICC = 0.1 when too few AMBIGUOUS",
        "day_groups": [list(g) for g in groups],
        "instability": {
            "bootstrap_runs": boot_runs,
            "undefined_share": 1.0 - len(defined) / boot_runs if boot_runs else math.nan,
            "raw_p05": float(np.percentile(defined, 5)) if defined else math.nan,
            "raw_p50": float(np.percentile(defined, 50)) if defined else math.nan,
            "raw_p95": float(np.percentile(defined, 95)) if defined else math.nan,
            "used_p05": float(pct[0]),
            "used_p50": float(pct[1]),
            "used_p95": float(pct[2]),
            "share_raw_at_or_below_floor": (
                sum(1 for r in defined if r <= stats.ICC_FLOOR) / len(defined) if defined else None
            ),
        },
    }


# ---- pools of simulated days ------------------------------------------------------------------
@dataclass(frozen=True)
class DayPool:
    """``draws`` simulated draws of one empirical day at the stage K."""

    m: IntArray  # admitted (posted) entries
    a: IntArray  # AMBIGUOUS entries
    mask: IntArray  # bit j set: the j-th admitted entry (arm-time order) is AMBIGUOUS
    burst: IntArray  # most AMBIGUOUS arm times inside any 60 minutes


@dataclass(frozen=True)
class PoolSet:
    """Day pools stacked: arrays of shape (empirical days, draws)."""

    m: IntArray
    a: IntArray
    mask: IntArray
    burst: IntArray


def build_day_pool(
    cands: Sequence[dhat.Candidate], arm: dhat.Arm, day: dt.date, draws: int
) -> DayPool:
    rng = random.Random(dhat.draw_seed_string(arm, day))
    m = np.zeros(draws, dtype=np.int64)
    a = np.zeros(draws, dtype=np.int64)
    mask = np.zeros(draws, dtype=np.int64)
    burst = np.zeros(draws, dtype=np.int64)
    if not cands:
        return DayPool(m, a, mask, burst)
    for i in range(draws):
        draw_arm = (
            arm if arm.rho <= 0.0 else dataclasses.replace(arm, p_amb=dhat.day_p_amb(arm, rng))
        )
        out = dhat.simulate_day(cands, draw_arm, rng)
        m[i] = out.admitted
        amb_times = [t for t, is_amb in zip(out.arm_ns, out.ambiguous, strict=True) if is_amb]
        a[i] = len(amb_times)
        mask[i] = sum(1 << j for j, is_amb in enumerate(out.ambiguous) if is_amb)
        burst[i] = stats.max_in_window(amb_times, BURST_WINDOW_NS)
    return DayPool(m, a, mask, burst)


def stack_pools(pools: Sequence[DayPool]) -> PoolSet:
    return PoolSet(
        np.stack([p.m for p in pools]),
        np.stack([p.a for p in pools]),
        np.stack([p.mask for p in pools]),
        np.stack([p.burst for p in pools]),
    )


# ---- stage trajectories -----------------------------------------------------------------------
@dataclass(frozen=True)
class StageSample:
    entries: IntArray  # (runs, days)
    amb: IntArray
    masks: IntArray
    bursts: IntArray
    cp_day: IntArray  # first day (1-based) the Clopper-Pearson rule fires, NEVER if not


def sample_stage(
    pools: PoolSet, rng: np.random.Generator, *, runs: int, days: int, crit: IntArray
) -> StageSample:
    """``runs`` stages of ``days`` days, each day a random empirical day and a random draw."""
    n_types, draws = pools.m.shape
    day_idx = rng.integers(0, n_types, size=(runs, days))
    draw_idx = rng.integers(0, draws, size=(runs, days))
    entries = pools.m[day_idx, draw_idx]
    amb = pools.a[day_idx, draw_idx]
    masks = pools.mask[day_idx, draw_idx]
    bursts = pools.burst[day_idx, draw_idx]
    if len(crit) <= int(entries.sum(axis=1).max(initial=0)):
        raise ValueError("the Clopper-Pearson table is too short for this stage")
    n_cum = np.zeros(runs, dtype=np.int64)
    x_cum = np.zeros(runs, dtype=np.int64)
    cp_day = np.full(runs, NEVER, dtype=np.int64)
    for d in range(days):
        day_entries, day_mask = entries[:, d], masks[:, d]
        for j in range(int(day_entries.max(initial=0))):
            active = day_entries > j
            n_cum += active
            x_cum += active & (((day_mask >> j) & 1) == 1)
            trip = active & (x_cum >= crit[n_cum]) & (cp_day == NEVER)
            cp_day[trip] = d + 1
    return StageSample(entries, amb, masks, bursts, cp_day)


def burst_day(bursts: IntArray, threshold: int) -> IntArray:
    """First day (1-based) whose most-AMBIGUOUS-in-60-minutes reaches ``threshold``."""
    hit = bursts >= threshold
    first = np.where(hit.any(axis=1), hit.argmax(axis=1) + 1, bursts.shape[1] + 1)
    return np.asarray(first, dtype=np.int64)


def halt_day(cp_day: IntArray, burst: IntArray) -> IntArray:
    return np.asarray(np.minimum(cp_day, burst), dtype=np.int64)


def rate_within(days: IntArray, horizon: int, *, never: int) -> float:
    """Share of runs whose event day is within ``horizon`` days."""
    return float(np.mean((days <= horizon) & (days < never)))


def promoted_without_halt(batch: Any, halt: IntArray, *, never: int) -> BoolArray:
    """Promoted AND no section 5 halt on or before the day the promotion was decided."""
    first = np.asarray(batch.first_look, dtype=np.int64)
    decision = np.where(
        np.asarray(batch.first_pass, dtype=bool),
        first,
        np.minimum(first + stats.RELOOK_EXTENSION_DAYS, STAGE_DAYS),
    )
    ok = np.asarray(batch.promoted, dtype=bool) & ((halt >= never) | (halt > decision))
    return np.asarray(ok, dtype=bool)


# ---- the BG-10 level search -------------------------------------------------------------------
@dataclass(frozen=True)
class LevelResult:
    root: float | None
    bracket: tuple[float, float] | None
    status: str  # ok | below_grid | above_grid
    table: tuple[tuple[float, float], ...]


def find_level(
    evaluate: Callable[[float], float],
    *,
    bar: float,
    grid: Sequence[float],
    tol: float,
    prefetch: Callable[[Sequence[float]], None] | None = None,
) -> LevelResult:
    """The p at which ``evaluate`` crosses ``bar`` (passes iff <= bar; NaN fails)."""

    def passes(value: float) -> bool:
        return not math.isnan(value) and value <= bar

    if prefetch is not None:
        prefetch(grid)
    table = [(p, evaluate(p)) for p in grid]
    if not passes(table[0][1]):
        return LevelResult(None, None, "below_grid", tuple(table))
    fail_at = next((i for i, (_, u) in enumerate(table) if not passes(u)), None)
    if fail_at is None:
        return LevelResult(None, None, "above_grid", tuple(table))
    lo, hi = table[fail_at - 1][0], table[fail_at][0]
    while hi - lo > tol:
        mid = (lo + hi) / 2
        value = evaluate(mid)
        table.append((mid, value))
        if passes(value):
            lo = mid
        else:
            hi = mid
    return LevelResult((lo + hi) / 2, (lo, hi), "ok", tuple(table))


def decide_viability(
    *,
    level: float | None,
    v2_90: float,
    v3_90: float,
    v2_95: float | None,
    v3_95: float | None,
) -> dict[str, Any]:
    """Section 5 / K10: V1 level >= 0.33; V2 >= 80%; V3 <= 20%. The 95% bound is switched on ONLY
    by a V3 failure at 90%; a V2 failure at 90% is NOT-VIABLE (nothing may be tuned after)."""
    v1_ok = level is not None and level >= V1_MIN
    failed: list[str] = []
    if not v1_ok:
        failed.append(f"V1 level {level} < {V1_MIN}")
    if v3_90 <= V3_MAX:
        bound, v2_used, v3_used = 0.90, v2_90, v3_90
    else:
        bound = 0.95
        if v2_95 is None or v3_95 is None:
            failed.append("V3 > 20% at 90% and the 95% recompute is missing")
            v2_used, v3_used = math.nan, math.nan
        else:
            v2_used, v3_used = v2_95, v3_95
    if not math.isnan(v2_used) and v2_used < V2_MIN:
        failed.append(f"V2 {v2_used:.4f} < {V2_MIN} at the {bound:.0%} bound")
    if not math.isnan(v3_used) and v3_used > V3_MAX:
        failed.append(f"V3 {v3_used:.4f} > {V3_MAX} at the {bound:.0%} bound")
    return {
        "verdict": "NOT-VIABLE" if failed else "VIABLE",
        "bound_in_force": bound,
        "v1_ok": v1_ok,
        "v2_used": v2_used,
        "v3_used": v3_used,
        "failed": failed,
        "rule": "V1 level >= 0.33; V2 >= 80%; V3 <= 20%; 95% only if V3 > 20% at 90% (K10)",
    }


# ---- running ----------------------------------------------------------------------------------
_CTX: dict[str, Any] = {}


def _pool_task(task: tuple[float, float, int, int]) -> tuple[float, float, int, int, DayPool]:
    p, rho, seed, day_i = task
    day, cands = _CTX["days"][day_i]
    arm = dhat.Arm(STAGE_K, p, STAGE_BUCKET, "A", 0, False, True, True, STAGE_FREE0, rho, seed)
    return p, rho, seed, day_i, build_day_pool(cands, arm, day, _CTX["draws"])


def build_pools(
    scenarios: Sequence[tuple[float, float]],
    days: Sequence[tuple[dt.date, tuple[dhat.Candidate, ...]]],
    draws: int,
    workers: int,
) -> dict[tuple[float, float, int], PoolSet]:
    _CTX["days"], _CTX["draws"] = list(days), draws
    tasks = [
        (p, rho, seed, i) for (p, rho) in scenarios for seed in dhat.SEEDS for i in range(len(days))
    ]
    got: dict[tuple[float, float, int], dict[int, DayPool]] = {}
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(workers) as pool:
        for n, (p, rho, seed, i, day_pool) in enumerate(
            pool.imap_unordered(_pool_task, tasks, chunksize=1), start=1
        ):
            got.setdefault((p, rho, seed), {})[i] = day_pool
            if n % max(1, len(tasks) // 20) == 0 or n == len(tasks):
                log(f"pools: {n}/{len(tasks)} day-pools")
    return {key: stack_pools([v[i] for i in sorted(v)]) for key, v in got.items()}


def _nan_safe(value: Any) -> Any:
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, Mapping):
        return {str(k): _nan_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_nan_safe(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return _nan_safe(value.item())
    return value


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _agg(per_seed: Sequence[float]) -> dict[str, Any]:
    return {
        "mean": float(np.mean(per_seed)),
        "min": float(np.min(per_seed)),
        "max": float(np.max(per_seed)),
        "per_seed": [float(x) for x in per_seed],
    }


def key_name(p: float, rho: float) -> str:
    return f"p{p}_rho{rho}"


@dataclass(frozen=True)
class StageResult:
    cp_day: IntArray
    b5_day: IntArray
    b6_day: IntArray
    tl90: Any
    tl95: Any
    entries_per_day: float
    amb_share: float


def stage_results(
    pools: PoolSet, *, seed: int, index: int, runs: int, level: float, icc: float
) -> StageResult:
    max_entries = int(pools.m.max(initial=0))
    crit = stats.cp_critical_counts(STAGE_DAYS * max(max_entries, 1), CP_P0, CP_ALPHA, CP_MIN_N)
    rng = np.random.default_rng([dhat.boot_seed(seed), index])
    s = sample_stage(pools, rng, runs=runs, days=STAGE_DAYS, crit=crit)
    z90, z95 = stats.z_one_sided(0.90), stats.z_one_sided(0.95)
    total = float(s.entries.sum())
    return StageResult(
        s.cp_day,
        burst_day(s.bursts, 5),
        burst_day(s.bursts, 6),
        stats.two_look_promotion_batch(s.entries, s.amb, level=level, z=z90, icc=icc),
        stats.two_look_promotion_batch(s.entries, s.amb, level=level, z=z95, icc=icc),
        total / (runs * STAGE_DAYS),
        float(s.amb.sum()) / total if total else math.nan,
    )


def _promotion_block(
    results: Mapping[int, StageResult], tl: str, halts: Mapping[int, IntArray]
) -> dict[str, Any]:
    first, overall, joint, hold, first_day8 = [], [], [], [], []
    for seed, r in results.items():
        batch = getattr(r, tl)
        first.append(float(np.mean(batch.first_pass)))
        overall.append(float(np.mean(batch.promoted)))
        hold.append(float(np.mean(batch.held)))
        first_day8.append(float(np.mean(batch.first_look == stats.MIN_LOOK_DAYS)))
        joint.append(float(np.mean(promoted_without_halt(batch, halts[seed], never=NEVER))))
    return {
        "first_look_pass": _agg(first),
        "overall_pass": _agg(overall),
        "overall_pass_with_no_halt": _agg(joint),
        "held_share": _agg(hold),
        "first_look_on_day_8_share": _agg(first_day8),
    }


# ---- the level evaluator over the dhat gate cells ---------------------------------------------
def make_level_evaluator(
    workers: int, bucket: float = LEVEL_BUCKET, rho: float = 0.0
) -> tuple[Callable[[float], float], Callable[[Sequence[float]], None], dict[float, list[float]]]:
    cells: dict[dhat.CellKey, dhat.CellStat] = {}
    per_seed: dict[float, list[float]] = {}

    def prefetch(ps: Sequence[float]) -> None:
        todo = [p for p in ps if p not in per_seed]
        arms = [
            dhat.Arm(LEVEL_K, p, bucket, fa, LEVEL_STUCK, False, True, True, STAGE_FREE0, rho, s)
            for p in todo
            for s in dhat.SEEDS
            for fa in ("A", "B")
        ]
        if not arms:
            return
        cells.update(dhat._run_arms(arms, workers))
        for p in todo:
            per_seed[p] = list(dhat.seed_uppers(cells, bucket, LEVEL_K, p, LEVEL_STUCK, False, rho))

    def evaluate(p: float) -> float:
        prefetch([p])
        return max(per_seed[p]) if all(not math.isnan(u) for u in per_seed[p]) else math.nan

    return evaluate, prefetch, per_seed


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    dhat.refuse_window_path(args.cands)
    dhat.refuse_window_path(args.orders)
    dhat.refuse_window_path(args.out)
    by_day = dhat.load_candidates(args.cands)
    stations = dhat.MAIN4_NYC
    days = [(d, tuple(c for c in v if c.station in stations)) for d, v in sorted(by_day.items())]
    dhat.assert_hold_constants_current()
    groups = icc_groups_from_orders(args.orders)  # refuses window rows
    icc = icc_report(groups, boot_runs=args.boot_runs, seed=dhat.boot_seed(0))
    icc_used = float(icc["icc_used"])
    log(f"icc: raw={icc['estimate_raw']} n_amb={icc['n_ambiguous']} used={icc_used}")

    # ---- V1 level (dhat gate cells)
    dhat._DAYS = {d: c for d, c in days}
    dhat._DRAWS, dhat._RESAMPLES = args.level_draws, args.level_resamples
    evaluate, prefetch, per_seed = make_level_evaluator(args.workers)
    log(f"level search: grid={list(args.level_grid)}")
    level_res = find_level(
        evaluate, bar=LEVEL_BAR, grid=args.level_grid, tol=LEVEL_TOL, prefetch=prefetch
    )
    log(f"level: status={level_res.status} root={level_res.root}")
    v1_level: float | None = level_res.root
    if level_res.status == "above_grid":
        v1_level = float(max(args.level_grid))  # at least the grid maximum
    if level_res.root is not None:
        level = level_res.root
    elif level_res.status == "above_grid":
        level = float(max(args.level_grid))
    else:
        level = float(min(args.level_grid))
    v1_block: dict[str, Any] = {
        "bar": LEVEL_BAR,
        "k": LEVEL_K,
        "bucket": dhat.bucket_name(LEVEL_BUCKET),
        "stuck_slots": LEVEL_STUCK,
        "worse_free_balance_arm": True,
        "status": level_res.status,
        "root": level_res.root,
        "bracket": level_res.bracket,
        "level_used_downstream": level,
        "ge_0_33": v1_level is not None and v1_level >= V1_MIN,
        "passing_grid_points_above_root": [
            p
            for p, u in level_res.table
            if level_res.bracket is not None
            and p > level_res.bracket[1]
            and not math.isnan(u)
            and u <= LEVEL_BAR
        ],
        "table": [
            {"p_amb": p, "max_seed_p90_ci_upper": u, "per_seed": per_seed.get(p)}
            for p, u in sorted(level_res.table)
        ],
    }
    # report-only rho = 0.1 arm: the gate cell at the registered p and at the level
    rho_eval, rho_prefetch, rho_seed = make_level_evaluator(args.workers, rho=dhat.RHO_ARM)
    rho_ps = sorted({dhat.STRESS_P_AMB, round(level, 6)})
    rho_prefetch(rho_ps)
    v1_block["rho_0_1_arm_report_only"] = {
        str(p): {"max_seed_p90_ci_upper": rho_eval(p), "per_seed": rho_seed[p]} for p in rho_ps
    }

    # ---- stage pools
    lvl = round(level, 6)
    sens_icc = _sensitivity_icc(icc)
    gen = min(icc_used, MAX_GEN_RHO)  # generative day-overdispersion; DEFF keeps the exact ICC
    gen_sens = None if sens_icc is None else min(sens_icc, MAX_GEN_RHO)
    extra = {(P_TRUE, gen), (V1_MIN, gen), (lvl, gen), (lvl, 0.0)}
    if gen_sens is not None:
        extra |= {(P_TRUE, gen_sens), (lvl, gen_sens)}
    scenarios = sorted(
        {(P_TRUE, r) for r in RHOS} | {(p, r) for p in POWER_PS for r in RHOS} | extra
    )
    index = {key: i for i, key in enumerate(scenarios)}
    log(f"stage pools: {len(scenarios)} scenarios x {len(dhat.SEEDS)} seeds, draws={args.draws}")
    pools = build_pools(scenarios, days, args.draws, args.workers)
    res: dict[tuple[float, float], dict[int, StageResult]] = {}

    def restage(p: float, rho: float, *, level_: float, icc_: float) -> dict[int, StageResult]:
        return {
            seed: stage_results(
                pools[(p, rho, seed)],
                seed=seed,
                index=index[(p, rho)],
                runs=args.runs,
                level=level_,
                icc=icc_,
            )
            for seed in dhat.SEEDS
        }

    for p, rho in scenarios:
        res[(p, rho)] = restage(p, rho, level_=level, icc_=icc_used)
        log(f"stage: {key_name(p, rho)} done")

    # ---- burst guard
    def burst_rate(p: float, rho: float, thr: int) -> dict[str, Any]:
        r = res[(p, rho)]
        return _agg(
            [
                rate_within(r[s].b5_day if thr == 5 else r[s].b6_day, STAGE_DAYS, never=NEVER)
                for s in dhat.SEEDS
            ]
        )

    burst_fa = {
        f"rho{rho}": {f"ge{thr}": burst_rate(P_TRUE, rho, thr) for thr in (5, 6)} for rho in RHOS
    }
    rho0_ge5_worst = burst_fa["rho0.0"]["ge5"]["max"]
    threshold = stats.burst_threshold_applied(rho0_ge5_worst)
    burst_block = {
        "window_minutes": 60,
        "horizon_days": STAGE_DAYS,
        "p_true": P_TRUE,
        "false_alarm_15d": burst_fa,
        "rho0_ge5_worst_seed": rho0_ge5_worst,
        "threshold_applied": threshold,
        "rule": "5, unless rho=0 at >=5 exceeds 10% (worst seed), then 6",
    }

    def halts_for(p: float, rho: float) -> dict[int, IntArray]:
        return _halts(res[(p, rho)], threshold)

    def halt_rates(p: float, rho: float, horizon: int) -> dict[str, Any]:
        h = halts_for(p, rho)
        r = res[(p, rho)]
        return {
            "cp_only": _agg([rate_within(r[s].cp_day, horizon, never=NEVER) for s in dhat.SEEDS]),
            "burst_only": _agg(
                [
                    rate_within(
                        r[s].b5_day if threshold == 5 else r[s].b6_day, horizon, never=NEVER
                    )
                    for s in dhat.SEEDS
                ]
            ),
            "cp_or_burst": _agg([rate_within(h[s], horizon, never=NEVER) for s in dhat.SEEDS]),
        }

    cp_block = {
        "rule": f"CP lower bound alpha {CP_ALPHA} > {CP_P0}, n >= {CP_MIN_N}, stage-cumulative, "
        f"checked after every entry; OR burst >= {threshold} AMBIGUOUS in 60 min of arm time",
        "false_alarm_15d_p0.18": {f"rho{r}": halt_rates(P_TRUE, r, STAGE_DAYS) for r in RHOS},
        "power_5d": {
            f"p{p}": {f"rho{r}": halt_rates(p, r, POWER_DAYS) for r in RHOS} for p in POWER_PS
        },
        "power_15d": {
            f"p{p}": {f"rho{r}": halt_rates(p, r, STAGE_DAYS) for r in RHOS} for p in POWER_PS
        },
    }

    # ---- V2 / V3
    def promo(p: float, rho: float, tl: str) -> dict[str, Any]:
        return _promotion_block(res[(p, rho)], tl, halts_for(p, rho))

    v2_90 = promo(P_TRUE, gen, "tl90")
    v3_90 = promo(lvl, gen, "tl90")
    v3_over = _agg_v3(v3_90) > V3_MAX
    v2_95 = promo(P_TRUE, gen, "tl95") if v3_over else None
    v3_95 = promo(lvl, gen, "tl95") if v3_over else None
    v2_block: dict[str, Any] = {
        "p_true": P_TRUE,
        "level": level,
        "icc_used": icc_used,
        "generative_rho": gen,
        "bound_90": v2_90,
        "sensitivity_iid_rho0": promo(P_TRUE, 0.0, "tl90"),
    }
    v3_block: dict[str, Any] = {
        "p_true": level,
        "level": level,
        "icc_used": icc_used,
        "generative_rho": gen,
        "bound_90": v3_90,
        "switch_to_95_triggered": v3_over,
        "sensitivity_iid_rho0": promo(lvl, 0.0, "tl90"),
    }
    if v3_over and v2_95 is not None and v3_95 is not None:
        v2_block["bound_95"] = v2_95
        v3_block["bound_95"] = v3_95
    ref_v2 = restage(P_TRUE, gen, level_=V1_MIN, icc_=icc_used)
    ref_v3 = restage(V1_MIN, gen, level_=V1_MIN, icc_=icc_used)
    for block, ref in ((v2_block, ref_v2), (v3_block, ref_v3)):
        block["reference_at_level_0.33"] = {
            "note": "same model with the level fixed at 0.33 (the reviewers' reference figures)",
            "bound_90": _promotion_block(ref, "tl90", _halts(ref, threshold)),
            "bound_95": _promotion_block(ref, "tl95", _halts(ref, threshold)),
        }
    sensitivity_icc: dict[str, Any] | None = None
    if sens_icc is not None and gen_sens is not None:
        s2 = restage(P_TRUE, gen_sens, level_=level, icc_=sens_icc)
        s3 = restage(lvl, gen_sens, level_=level, icc_=sens_icc)
        sensitivity_icc = {
            "note": "ICC = the (unreliable) pre-window estimate instead of the floor, for DEFF "
            "and the generative rho; NOT used for the verdict",
            "icc": sens_icc,
            "v2_bound_90": _promotion_block(s2, "tl90", _halts(s2, threshold)),
            "v3_bound_90": _promotion_block(s3, "tl90", _halts(s3, threshold)),
            "v2_bound_95": _promotion_block(s2, "tl95", _halts(s2, threshold)),
            "v3_bound_95": _promotion_block(s3, "tl95", _halts(s3, threshold)),
        }
    viability = decide_viability(
        level=v1_level,
        v2_90=v2_90["overall_pass_with_no_halt"]["min"],
        v3_90=v3_90["overall_pass"]["max"],
        v2_95=None if v2_95 is None else v2_95["overall_pass_with_no_halt"]["min"],
        v3_95=None if v3_95 is None else v3_95["overall_pass"]["max"],
    )
    viability["basis"] = (
        "V2 = promotion pass with no section 5 halt (worst seed); V3 = bound-only false pass "
        "(worst seed); the bound-only V2 is reported beside it"
    )

    pins = _pins(args, days, res, scenarios, icc_used, level, threshold)
    return {
        "meta": {
            "task": "EXEC-PAR D-PREREG BG-10 (a)(c)(d)(e)",
            "data_rule": f"every input dated before {dhat.CUTOFF_DAY}; window inputs refused",
            "inputs_sha256": {
                args.cands.name: sha256_of(args.cands),
                args.orders.name: sha256_of(args.orders),
            },
            "scripts_sha256": {
                "exec_parallel_dhat_v2.py": sha256_of(Path(dhat.__file__)),
                "exec_par_bg10_stats.py": sha256_of(Path(stats.__file__)),
                "exec_par_bg10_sim.py": sha256_of(Path(__file__)),
            },
            "elapsed_s": round(time.time() - started, 1),
        },
        "v1_level": v1_block,
        "icc": icc,
        "v2": v2_block,
        "v3": v3_block,
        "burst": burst_block,
        "cp_burst": cp_block,
        "viability": viability,
        "sensitivity_icc_estimate": sensitivity_icc,
        "pins": pins,
    }


def _halts(results: Mapping[int, StageResult], threshold: int) -> dict[int, IntArray]:
    return {
        s: halt_day(r.cp_day, r.b5_day if threshold == 5 else r.b6_day) for s, r in results.items()
    }


def _sensitivity_icc(icc: Mapping[str, Any]) -> float | None:
    """The raw pre-window estimate, when it was set aside as too noisy and exceeds the floor."""
    est = float(icc["estimate_floored"])
    if icc["too_few_ambiguous"] and not math.isnan(est) and est > float(icc["icc_used"]):
        return est
    return None


def _agg_v3(block: Mapping[str, Any]) -> float:
    return float(block["overall_pass"]["max"])


def _pins(
    args: argparse.Namespace,
    days: Sequence[tuple[dt.date, tuple[dhat.Candidate, ...]]],
    res: Mapping[tuple[float, float], Mapping[int, StageResult]],
    scenarios: Sequence[tuple[float, float]],
    icc_used: float,
    level: float,
    threshold: int,
) -> dict[str, Any]:
    counts = {d.isoformat(): len(c) for d, c in days}
    secs = [(t % dhat.DAY_NS) / dhat.NS for _, c in days for t in (x.ts_ns for x in c)]
    spans = [
        (max(x.ts_ns for x in c) - min(x.ts_ns for x in c)) / dhat.NS / 60 for _, c in days if c
    ]
    return {
        "entries_per_day": {
            "rule": "empirical pre-2026-10-07 per-day candidate count x simulated K=2 admission "
            "rate (the simulated admitted count of each empirical day, drawn with replacement)",
            "candidate_counts_by_day": counts,
            "days": len(days),
            "zero_candidate_days": sum(1 for v in counts.values() if v == 0),
            "mean_candidates_per_day": float(np.mean(list(counts.values()))),
            "stations": sorted(dhat.MAIN4_NYC),
            "mean_posted_entries_per_stage_day": {
                key_name(p, rho): _agg([r.entries_per_day for r in res[(p, rho)].values()])
                for p, rho in scenarios
            },
            "ambiguous_share_of_posted": {
                key_name(p, rho): _agg([r.amb_share for r in res[(p, rho)].values()])
                for p, rho in scenarios
            },
            "m_bar_definition": "posted entries / non-excluded climate days in the stage window",
        },
        "intraday_entry_times": {
            "source": "pre-2026-10-07 candidate file: first 12:00-13:00Z depth row per rung",
            "arm_time": "the candidate timestamp (admission is immediate)",
            "seconds_of_day_min": float(min(secs)),
            "seconds_of_day_p50": float(np.percentile(secs, 50)),
            "seconds_of_day_max": float(max(secs)),
            "per_day_span_minutes_p50": float(np.percentile(spans, 50)),
            "per_day_span_minutes_max": float(max(spans)),
            "burst_window_minutes": 60,
            "note": "all arm times of a day fall inside one 60-minute window and windows never "
            "span days, so the burst guard reduces to the day's AMBIGUOUS count",
        },
        "icc_model": {
            "estimator": "one-way ANOVA ICC, n0 weighting, floored at 0.1",
            "icc_used": icc_used,
            "bound": "Wilson on n_eff = n / DEFF, DEFF = 1 + (m_bar - 1) * ICC",
            "generative": "AMBIGUOUS by day beta-binomial, rho = ICC used; rho = 0 as sensitivity",
            "order_day_shift_hours": ORDER_DAY_SHIFT_HOURS,
        },
        "seeds": list(dhat.SEEDS),
        "bootstrap_seeds": [dhat.boot_seed(s) for s in dhat.SEEDS],
        "runs": args.runs,
        "draws_per_day": args.draws,
        "level_draws_per_day": args.level_draws,
        "level_resamples": args.level_resamples,
        "icc_bootstrap_runs": args.boot_runs,
        "k": STAGE_K,
        "bucket": dhat.bucket_name(STAGE_BUCKET),
        "bounds": {"primary": 0.90, "switch": 0.95, "level_used": level},
        "stage_rules": {
            "first_look": f">= {stats.MIN_LOOK_DAYS} days and >= {stats.MIN_LOOK_ORDERS} orders",
            "relook": f"+{stats.RELOOK_EXTENSION_DAYS} days, cumulative, cap day {STAGE_DAYS}",
            "cp": f"alpha {CP_ALPHA}, LB > {CP_P0}, n >= {CP_MIN_N}",
            "burst_threshold": threshold,
            "burst_window_minutes": 60,
        },
        "level_grid": list(args.level_grid),
        "level_tolerance": LEVEL_TOL,
    }


def _grid(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.split(","))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EXEC-PAR BG-10(c) pre-registered simulation outputs")
    p.add_argument("--cands", type=Path, default=dhat.DEFAULT_CANDS)
    p.add_argument("--orders", type=Path, default=dhat.DEFAULT_ORDERS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--draws", type=int, default=DEFAULT_DRAWS, help="stage draws per empirical day")
    p.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="stage trajectories per seed")
    p.add_argument("--workers", type=int, default=dhat.DEFAULT_WORKERS)
    p.add_argument("--level-draws", type=int, default=dhat.DRAWS)
    p.add_argument("--level-resamples", type=int, default=dhat.RESAMPLES)
    p.add_argument("--boot-runs", type=int, default=DEFAULT_BOOT_RUNS)
    p.add_argument("--level-grid", type=_grid, default=LEVEL_GRID)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args)
    except dhat.WindowDataRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    args.out.write_text(json.dumps(_nan_safe(result), indent=1) + "\n")
    log(f"wrote {args.out.name}: viability {result['viability']['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
