"""KILL power at non-positive edges. Reporting only: this changes no constant.

Spec: docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5-pin-request_r2.md §3.4.
The r2-verification corrections add a δ = 0 harness row (p_kill ≈ 0), the realised
clipped mean of Y, and the BE/ask source and take rate.

The Monte Carlo alternative ``min(1, BE + δ)`` (``fq_mc_eprocess.outcome_probability``)
has no lower clamp. A negative δ below BE would be a negative probability. This
script clamps ``clamp(BE + δ, 0, 1)`` itself and does not edit the MC module: that
module's as-run state backs the frozen power table. KILL is the MC's ``kill_first_n``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import json
import math
import resource
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.autonomy import confidence_sequence as cs
from breezy.analysis.memory_cap import apply_address_space_cap
from scripts.analysis import fq_mc_eprocess as mc
from scripts.analysis.fq_mc_eprocess import ItemBatch, items_to_yz, kill_first_n
from scripts.analysis.fq_mc_livedata import (
    DayTemplate,
    Design,
    LoadStats,
    _arrays,
    calibrate_take_rate,
    group_days,
    load_pool,
)
from scripts.analysis.fq_resume_n_mc import KILL_DATE
from scripts.analysis.fq_resume_n_mc import build_parser as mc_build_parser
from scripts.analysis.fq_resume_n_mc import run_grid as mc_run_grid
from scripts.analysis.multisource_blend_refusal import Refusal
from scripts.analysis.prereg_amendment_check import _resolve_parent, load_verified_amendment
from scripts.analysis.prereg_precommit_check import load_design

__all__ = [
    "AMENDMENT_ID",
    "BE_ASK_SOURCE",
    "DEFAULT_AMENDMENT_PATH",
    "DEFAULT_OUTPUT_PATH",
    "DELTAS",
    "KILL_DATE",
    "ROW_KEYS",
    "SEED",
    "TAKE_RATE_SOURCE",
    "build_document",
    "build_parser",
    "clamped_outcome_probability",
    "load_verified_pins",
    "main",
    "mc_d0",
    "mc_n_max",
    "mc_pool_days",
    "mc_replicates",
    "n_by_kill_date",
    "run_delta",
    "simulate_clamped",
]

AMENDMENT_ID: Final[str] = "F5_prereg_v2_A0_kill"
SEED: Final[int] = 20261008
DELTAS: Final[tuple[float, ...]] = (0.0, -0.04, -0.08, -0.16)
DEFAULT_AMENDMENT_PATH: Path = (
    _REPO_ROOT / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_amendment_A0.json"
)
DEFAULT_OUTPUT_PATH: Path = (
    _REPO_ROOT / "docs/evidence/f5/fq_kill_power_negative_edge_seed20261008.json"
)
DEFAULT_MAX_MEMORY_GIB: Final[float] = 8.0  # same cap the other heavy analysis scripts use
_DATA_ROOT: Final[Path] = Path.home() / ".local/share/breezy/kalshi"
_K_SLOTS: Final[int] = 3
_BOOTSTRAP_DRAWS: Final[int] = 200
# Raw-array budget for one chunk. Temporaries sit on top; 1.5 GiB of arrays stays
# inside the 4 GiB RSS gate with room to spare.
_CHUNK_ARRAY_BUDGET: Final[int] = int(1.5 * 1024**3)

BE_ASK_SOURCE: Final[str] = (
    "Kalshi pre-holdout quote tape (fq_mc_livedata.load_pool, climate_day < holdout start). "
    "TakeRecord.ask is the quote the shipped take rule saw; TakeRecord.be is the haircut ask "
    "plus the fee, using the frozen parent haircut (1 tick of 0.01) and theta 0.0695: "
    "BE = haircut_ask + theta*p*(1-p). This is the Monte Carlo break-even, not a ledger fill BE."
)
TAKE_RATE_SOURCE: Final[str] = (
    "Frozen parent take_rate_lower, realised by fq_mc_livedata.calibrate_take_rate "
    "(pi_fav bisection on the shipped take rule). n_by_kill_date uses the target rate, "
    "the MC --d0 default, the parent uptime_floor and fq_resume_n_mc.KILL_DATE. "
    "take_rate on each row is the realised mean takes per resampled day; "
    "take_rate_target is the parent rate the kill-date censor uses."
)

ROW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "delta",
        "p_kill_by_kill_date",
        "se_p_kill_by_kill_date",
        "p_kill_by_n_max",
        "se_p_kill_by_n_max",
        "median_n_at_kill",
        "se_median_n_at_kill",
        "clipped_mean_y",
        "take_rate",
        "take_rate_target",
        "take_rate_realised",
        "be_ask_source",
    }
)


def _signature_int(name: str) -> int:
    value = inspect.signature(mc_run_grid).parameters[name].default
    if not isinstance(value, int):
        raise TypeError(f"fq_resume_n_mc.run_grid {name} default must be int, got {value!r}")
    return value


_CHUNK: Final[int] = _signature_int("chunk")
_MAX_DAYS: Final[int] = _signature_int("max_days")


def _parser_default(name: str) -> Any:
    return mc_build_parser().get_default(name)


def mc_replicates() -> int:
    """The resume-n MC ``--reps`` default. This report does not retype it."""
    value = _parser_default("reps")
    if not isinstance(value, int):
        raise TypeError(f"MC replicates default must be int, got {value!r}")
    return value


def mc_n_max() -> int:
    value = _parser_default("n_max")
    if not isinstance(value, int):
        raise TypeError(f"MC n_max default must be int, got {value!r}")
    return value


def mc_pool_days() -> int:
    value = _parser_default("pool_days")
    if not isinstance(value, int):
        raise TypeError(f"MC pool_days default must be int, got {value!r}")
    return value


def mc_d0() -> dt.date:
    value = _parser_default("d0")
    if not isinstance(value, dt.date):
        raise TypeError(f"MC d0 default must be a date, got {value!r}")
    return value


def clamped_outcome_probability(be: float, *, delta: float) -> float:
    """Bernoulli probability ``clamp(BE + δ, 0, 1)``.

    ``fq_mc_eprocess.outcome_probability`` caps only at 1. This is the lower clamp
    the negative-edge report needs, and it is not a change to that function.
    """
    if not math.isfinite(be) or not math.isfinite(delta):
        raise ValueError(f"BE and delta must be finite, got {be!r}, {delta!r}")
    return float(min(1.0, max(0.0, be + delta)))


def n_by_kill_date(
    take_rate: float, *, d0: dt.date, kill_date: dt.date, uptime_floor: float
) -> int:
    """Takes available before KILL_DATE. Same product the MC starvation table uses."""
    if take_rate < 0.0 or not 0.0 <= uptime_floor <= 1.0:
        raise ValueError(f"bad take rate {take_rate!r} or uptime {uptime_floor!r}")
    days = (kill_date - d0).days + 1
    if days <= 0:
        raise ValueError(f"kill date {kill_date} is not after d0 {d0}")
    return int(take_rate * days * uptime_floor)


def _require_number(mapping: Mapping[str, Any], key: str) -> float:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refusal(f"{key} must be a number, got {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise Refusal(f"{key} must be finite, got {value!r}")
    return out


def _require_int(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refusal(f"{key} must be an integer, got {value!r}")
    return value


def _assert_kill_constants(amendment: Mapping[str, Any]) -> None:
    """A0's KILL numbers are the imported production and MC constants. Nothing is retyped."""
    kill = amendment.get("kill")
    if not isinstance(kill, Mapping):
        raise Refusal("the A0 kill payload must be an object")
    pairs: tuple[tuple[str, object, object | None], ...] = (
        ("kill_grid_points", cs.KILL_GRID_POINTS, mc.KILL_GRID_POINTS),
        ("kill_lambda_max", cs.KILL_MAX_LAMBDA, mc.MAX_LAMBDA),
        ("kill_min_range", cs._MIN_RANGE, None),
        ("kill_var_floor", cs._VAR_FLOOR, None),
        ("kill_prior_pseudo_days", cs.PRIOR_PSEUDO_DAYS, mc.PRIOR_PSEUDO_DAYS),
        ("kill_prior_second_moment", cs.PRIOR_SECOND_MOMENT, mc.PRIOR_SECOND_MOMENT),
    )
    for name, production, monte_carlo in pairs:
        got = kill[name]
        if got != production or (monte_carlo is not None and got != monte_carlo):
            raise AssertionError(
                f"A0 {name}={got!r} != imported production {production!r} / MC {monte_carlo!r}"
            )


def load_verified_pins(
    path: Path | None = None,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Frozen A0 via ``load_verified_amendment``, parent via ``load_design`` on ``amends.path``.

    An UNFROZEN amendment raises :class:`Refusal` before any stream is built.
    """
    amendment_path = DEFAULT_AMENDMENT_PATH if path is None else Path(path)
    amendment = load_verified_amendment(amendment_path, AMENDMENT_ID)
    amends = amendment.get("amends")
    if not isinstance(amends, Mapping):
        raise Refusal("amends is missing")
    parent_path, problem = _resolve_parent(amendment_path, amends.get("path"))
    if problem is not None or parent_path is None:
        raise Refusal(problem or "amends.path is not usable")
    parent = load_design(parent_path)
    _assert_kill_constants(amendment)
    return amendment, parent


def simulate_clamped(
    templates: Sequence[DayTemplate],
    design: Design,
    *,
    reps: int,
    days: int,
    seed: int,
) -> ItemBatch:
    """``simulate_pooled``'s resampling, with outcome probability clamp(BE + δ, 0, 1).

    The uniform draw and the day index use the same RNG order as ``simulate_pooled``
    (mixed_only left off), so δ = 0 reproduces the MC null stream when BE is in [0, 1].
    """
    if reps <= 0 or days <= 0:
        raise ValueError(f"reps and days must be positive, got {reps}, {days}")
    pick = list(range(len(templates)))
    if not pick:
        raise ValueError("no day template")
    arr = _arrays(templates)
    rng = np.random.default_rng(seed)
    idx = np.asarray(pick)[rng.integers(0, len(pick), (reps, days))]
    uniforms = rng.random((reps, days, len(arr.stations)))
    station = arr.st[idx]
    by_station = np.take_along_axis(uniforms, station, axis=2)
    be = arr.be[idx]
    # Not outcome_probability: that helper has no lower clamp.
    probability = np.clip(be + design.delta_h, 0.0, 1.0)
    return ItemBatch(
        be=be,
        ask=arr.ask[idx],
        p=arr.p[idx],
        h=(by_station < probability).astype(float),
        valid=arr.valid[idx],
        n_d=arr.n[idx],
        st=station,
        mixed=arr.mixed[idx],
    )


def _median_n_at_kill(kill_n: np.ndarray) -> float | None:
    """Median n at KILL. A replicate that never kills is censored. Null when that median is."""
    reps = int(kill_n.shape[0])
    if reps == 0:
        return None
    finite = np.sort(kill_n[kill_n >= 0].astype(np.float64))
    if reps % 2 == 1:
        index = reps // 2
        if int(finite.size) <= index:
            return None
        return float(finite[index])
    upper = reps // 2
    lower = upper - 1
    if int(finite.size) <= upper:
        return None
    return float((float(finite[lower]) + float(finite[upper])) / 2.0)


def _se_median(kill_n: np.ndarray, *, seed: int) -> float | None:
    if _median_n_at_kill(kill_n) is None:
        return None
    rng = np.random.default_rng(seed)
    reps = int(kill_n.shape[0])
    draws: list[float] = []
    for _ in range(_BOOTSTRAP_DRAWS):
        sample = kill_n[rng.integers(0, reps, size=reps)]
        med = _median_n_at_kill(sample)
        if med is not None:
            draws.append(med)
    if len(draws) < 2:
        return None
    return float(np.std(np.asarray(draws, dtype=np.float64), ddof=1))


def _rate_se(hits: int, reps: int) -> float:
    if reps <= 0:
        raise ValueError("replicates must be positive")
    proportion = hits / reps
    return math.sqrt(proportion * (1.0 - proportion) / reps)


def run_delta(
    templates: Sequence[DayTemplate],
    *,
    delta: float,
    m_cap: int,
    x_max: float,
    alpha_kill: float,
    earliest_look_n: int,
    replicates: int,
    days: int,
    n_max: int,
    n_by_kill_date_n: int,
    seed: int,
    take_rate_target: float,
    take_rate_realised: float,
    chunk: int | None = None,
) -> dict[str, Any]:
    """One δ. Probabilities are binomial rates; the median is censored at a never-kill."""
    step = _CHUNK if chunk is None else chunk
    if step <= 0:
        raise ValueError(f"chunk must be positive, got {step}")
    design = Design(
        delta_h=delta,
        m_cap=m_cap,
        x_max=x_max,
        earliest_look_n=earliest_look_n,
        alpha_kill=alpha_kill,
    )
    parts: list[np.ndarray] = []
    total_y = 0.0
    count_y = 0
    for chunk_index, start in enumerate(range(0, replicates, step)):
        count = min(step, replicates - start)
        batch = simulate_clamped(
            templates,
            design,
            reps=count,
            days=days,
            seed=seed * 1009 + chunk_index,
        )
        y, _z = items_to_yz(batch, m_cap=m_cap, x_max=x_max)
        n_cum = np.cumsum(batch.n_d, axis=1)
        parts.append(
            kill_first_n(
                y,
                n_cum,
                x_max=x_max,
                alpha_kill=alpha_kill,
                earliest_look_n=earliest_look_n,
            )
        )
        total_y += float(y.sum())
        count_y += int(y.size)
    kill_n = np.concatenate(parts)
    reps = int(kill_n.shape[0])
    by_date = int(np.count_nonzero((kill_n >= 0) & (kill_n <= n_by_kill_date_n)))
    by_max = int(np.count_nonzero((kill_n >= 0) & (kill_n <= n_max)))
    if count_y <= 0:
        raise RuntimeError("the clipped-Y stream was empty")
    row = {
        "delta": delta,
        "p_kill_by_kill_date": by_date / reps,
        "se_p_kill_by_kill_date": _rate_se(by_date, reps),
        "p_kill_by_n_max": by_max / reps,
        "se_p_kill_by_n_max": _rate_se(by_max, reps),
        "median_n_at_kill": _median_n_at_kill(kill_n),
        "se_median_n_at_kill": _se_median(kill_n, seed=seed),
        "clipped_mean_y": total_y / count_y,
        "take_rate": take_rate_realised,
        "take_rate_target": take_rate_target,
        "take_rate_realised": take_rate_realised,
        "be_ask_source": BE_ASK_SOURCE,
    }
    if set(row) != ROW_KEYS:
        raise RuntimeError(f"row keys drifted: {sorted(set(row) ^ ROW_KEYS)}")
    return row


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def build_document(
    *,
    amendment: Mapping[str, Any],
    parent: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    replicates: int,
    n_max: int,
    pool: Mapping[str, Any] | None,
    seed: int,
) -> dict[str, Any]:
    """The evidence document. δ = 0 is first; it is the harness row, not an A0 edge edit."""
    m_cap = _require_int(parent, "m_cap")
    x_max = _require_number(parent, "x_max")
    alpha_kill = _require_number(parent, "alpha_kill")
    earliest = _require_int(parent, "earliest_look_n")
    target = _require_number(parent, "take_rate_lower")
    uptime = _require_number(parent, "uptime_floor")
    d0 = mc_d0()
    amends = amendment["amends"]
    if not isinstance(amends, Mapping):
        raise Refusal("amends is missing")
    parent_rel = amends.get("path")
    realised = rows[0]["take_rate_realised"] if rows else None
    return {
        "seed": seed,
        "replicates": replicates,
        "deltas": list(DELTAS),
        "design": {
            "m_cap": m_cap,
            "x_max": x_max,
            "alpha_kill": alpha_kill,
            "earliest_look_n": earliest,
            "source": "frozen parent via load_design(amends.path)",
        },
        "rows": [dict(row) for row in rows],
        "be_ask_source": BE_ASK_SOURCE,
        "take_rate": target,
        "take_rate_target": target,
        "take_rate_realised": realised,
        "take_rate_source": TAKE_RATE_SOURCE,
        "n_max": n_max,
        "n_by_kill_date": n_by_kill_date(target, d0=d0, kill_date=KILL_DATE, uptime_floor=uptime),
        "kill_date": KILL_DATE.isoformat(),
        "d0": d0.isoformat(),
        "uptime_floor": uptime,
        "amendment_id": AMENDMENT_ID,
        "pool": pool,
        "provenance": {
            "amendment_id": AMENDMENT_ID,
            "amendment_path": _rel(DEFAULT_AMENDMENT_PATH),
            "parent_path": parent_rel,
            "amendment_frozen_sha": amendment.get("frozen_sha"),
            "parent_frozen_sha": parent.get("frozen_sha"),
            "mc_module": "scripts/analysis/fq_mc_eprocess.py",
            "engine": "kill_first_n",
            "outcome": "Bernoulli(clamp(BE + delta, 0, 1))",
            "delta_zero_role": "harness row; same stream as the MC null and p_kill ≈ 0",
            "edges_in_frozen_a0": [-0.04, -0.08, -0.16],
            "seed": seed,
            "role": "reporting_only_changes_no_constant",
            "anchor": (
                "docs/evidence/f5/fq_resume_n_mc_seed20261006.json "
                "clipped_mean_y -0.019 p_kill_under_null_stream 0.0025"
            ),
        },
    }


def _horizon_days(realised_takes_per_day: float, n_max: int) -> int:
    """Same horizon the resume-n grid uses: enough days that n_max is reachable, capped."""
    if realised_takes_per_day <= 0.0:
        raise Refusal("calibrated take rate is 0; there is no stream to score")
    return min(_MAX_DAYS, max(10, math.ceil(1.15 * n_max / realised_takes_per_day)))


def _station_count(templates: Sequence[DayTemplate]) -> int:
    stations = {take.station for day in templates for take in day.takes}
    return max(1, len(stations))


def chunk_size_for(*, days: int, stations: int, replicates: int) -> int:
    """Largest chunk at or under the MC chunk that keeps one batch inside the array budget."""
    per_rep = days * (
        8 * (4 * _K_SLOTS + 1 + _K_SLOTS)  # be, ask, p, h, n_d, station index
        + _K_SLOTS
        + 1
        + 8 * stations  # uniforms, one per station
        + 8 * _K_SLOTS  # the station's uniform
        + 16  # y and n_cum
    )
    if per_rep <= 0:
        return min(_CHUNK, replicates)
    fit = max(1, _CHUNK_ARRAY_BUDGET // per_rep)
    return max(1, min(_CHUNK, replicates, fit))


def _rss_bytes() -> int:
    # Linux: ru_maxrss is kilobytes, and it is the process high-water mark.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def prepare_templates(
    *,
    candles: Path,
    markets_dir: Path,
    take_rate_target: float,
    pool_days: int,
    seed: int,
    n_max: int,
) -> tuple[list[DayTemplate], float, float, dict[str, Any], int]:
    """Load the MC pool, sample days, calibrate the take rate, and size the horizon."""
    if not candles.is_file():
        raise Refusal(f"candles file not found: {candles}")
    stats = LoadStats()
    rows = load_pool(candles, markets_dir=markets_dir, stats=stats)
    days_all = group_days(rows)
    if not days_all:
        raise Refusal("the pre-holdout pool has no climate days")
    rng = np.random.default_rng(seed)
    sample_n = min(pool_days, len(days_all))
    chosen = rng.choice(len(days_all), size=sample_n, replace=False)
    keep = sorted(int(index) for index in np.asarray(chosen).tolist())
    sampled = [days_all[index] for index in keep]
    pi_fav, templates = calibrate_take_rate(sampled, target_rate=take_rate_target, seed=seed)
    realised = float(np.mean([day.n for day in templates])) if templates else 0.0
    horizon = _horizon_days(realised, n_max)
    pool = {
        "rows": len(rows),
        "days": len(days_all),
        "sampled_days": len(sampled),
        "load_stats": stats.as_dict(),
        "pi_fav": pi_fav,
        "stations": _station_count(templates),
        "horizon_days": horizon,
    }
    return list(templates), realised, pi_fav, pool, horizon


def _design_from_parent(parent: Mapping[str, Any]) -> tuple[int, float, float, int, float, float]:
    return (
        _require_int(parent, "m_cap"),
        _require_number(parent, "x_max"),
        _require_number(parent, "alpha_kill"),
        _require_int(parent, "earliest_look_n"),
        _require_number(parent, "take_rate_lower"),
        _require_number(parent, "uptime_floor"),
    )


def run_rows(
    templates: Sequence[DayTemplate],
    *,
    parent: Mapping[str, Any],
    deltas: Sequence[float],
    replicates: int,
    days: int,
    n_max: int,
    seed: int,
    realised: float,
    chunk: int,
) -> list[dict[str, Any]]:
    m_cap, x_max, alpha_kill, earliest, target, uptime = _design_from_parent(parent)
    kill_n = n_by_kill_date(target, d0=mc_d0(), kill_date=KILL_DATE, uptime_floor=uptime)
    rows: list[dict[str, Any]] = []
    for delta in deltas:
        print(
            f"PROGRESS delta={delta} replicates={replicates} days={days} chunk={chunk}",
            flush=True,
        )
        rows.append(
            run_delta(
                templates,
                delta=delta,
                m_cap=m_cap,
                x_max=x_max,
                alpha_kill=alpha_kill,
                earliest_look_n=earliest,
                replicates=replicates,
                days=days,
                n_max=n_max,
                n_by_kill_date_n=kill_n,
                seed=seed,
                take_rate_target=target,
                take_rate_realised=realised,
                chunk=chunk,
            )
        )
    return rows


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _project_seconds(
    t_small: float, n_small: int, t_large: float, n_large: int, n_full: int
) -> float:
    """Fit t = a + b·n on two tiny runs. A negative slope falls back to the larger run's rate."""
    if n_large == n_small:
        return t_large * (n_full / n_large)
    slope = (t_large - t_small) / (n_large - n_small)
    if slope <= 0.0:
        return t_large * (n_full / n_large)
    intercept = t_small - slope * n_small
    return intercept + slope * n_full


def _benchmark(args: argparse.Namespace, full_replicates: int) -> int:
    """Tiny replicate counts. Prints runtime and a full-run projection. Does not write evidence."""
    started = time.monotonic()
    _amendment, parent = load_verified_pins(args.amendment)
    _m_cap, _x_max, _alpha, _earliest, target, _uptime = _design_from_parent(parent)
    load_started = time.monotonic()
    templates, realised, _pi, pool, horizon = prepare_templates(
        candles=args.candles,
        markets_dir=args.markets_dir,
        take_rate_target=target,
        pool_days=mc_pool_days(),
        seed=args.seed,
        n_max=mc_n_max(),
    )
    load_seconds = time.monotonic() - load_started
    stations = int(pool["stations"])
    chunk = chunk_size_for(days=horizon, stations=stations, replicates=full_replicates)
    sizes: tuple[int, ...] = (args.replicates,) if args.replicates is not None else (8, 32)
    timings: list[tuple[int, float, int]] = []
    for size in sizes:
        sim_started = time.monotonic()
        # The second size times one δ. Four δ share the same horizon, so the fit scales by len.
        scored = DELTAS if size == sizes[0] else DELTAS[:1]
        run_rows(
            templates,
            parent=parent,
            deltas=scored,
            replicates=size,
            days=horizon,
            n_max=mc_n_max(),
            seed=args.seed,
            realised=realised,
            chunk=chunk,
        )
        elapsed = time.monotonic() - sim_started
        per_delta = elapsed / len(scored)
        timings.append((size, per_delta, _rss_bytes()))
        print(
            f"benchmark_point replicates={size} per_delta_seconds={per_delta:.3f} "
            f"rss_mib={_rss_bytes() / 1024**2:.1f}",
            flush=True,
        )
    if len(timings) == 1:
        projected_sim = _project_seconds(
            timings[0][1], timings[0][0], timings[0][1], timings[0][0], full_replicates
        )
    else:
        projected_sim = _project_seconds(
            timings[0][1], timings[0][0], timings[-1][1], timings[-1][0], full_replicates
        )
    projected_sim *= len(DELTAS)
    projected_total = load_seconds + projected_sim
    rss_small = timings[0][2]
    rss_large = timings[-1][2]
    n_small, n_large = timings[0][0], timings[-1][0]
    if n_large > n_small and rss_large > rss_small:
        per_rep = (rss_large - rss_small) / (n_large - n_small)
        projected_rss = rss_small + per_rep * (min(chunk, full_replicates) - n_small)
    else:
        projected_rss = rss_large * (min(chunk, full_replicates) / max(n_large, 1))
    print(
        "\n".join(
            [
                "subset_benchmark=1",
                "official_evidence_written=0",
                f"load_seconds={load_seconds:.3f}",
                f"horizon_days={horizon}",
                f"stations={stations}",
                f"chunk={chunk}",
                f"realised_take_rate={realised:.6f}",
                f"full_replicates={full_replicates}",
                f"projected_full_seconds={projected_total:.1f}",
                f"projected_full_minutes={projected_total / 60:.2f}",
                f"projected_peak_rss_mib={projected_rss / 1024**2:.1f}",
                f"measured_peak_rss_mib={_rss_bytes() / 1024**2:.1f}",
                f"wall_seconds={time.monotonic() - started:.3f}",
            ]
        ),
        flush=True,
    )
    return 0


def _full(args: argparse.Namespace, replicates: int) -> int:
    started = time.monotonic()
    amendment, parent = load_verified_pins(args.amendment)
    _m_cap, _x_max, _alpha, _earliest, target, _uptime = _design_from_parent(parent)
    n_max = mc_n_max()
    templates, realised, _pi, pool, horizon = prepare_templates(
        candles=args.candles,
        markets_dir=args.markets_dir,
        take_rate_target=target,
        pool_days=mc_pool_days(),
        seed=args.seed,
        n_max=n_max,
    )
    chunk = chunk_size_for(days=horizon, stations=int(pool["stations"]), replicates=replicates)
    rows = run_rows(
        templates,
        parent=parent,
        deltas=DELTAS,
        replicates=replicates,
        days=horizon,
        n_max=n_max,
        seed=args.seed,
        realised=realised,
        chunk=chunk,
    )
    document = build_document(
        amendment=amendment,
        parent=parent,
        rows=rows,
        replicates=replicates,
        n_max=n_max,
        pool=pool,
        seed=args.seed,
    )
    document["runtime_seconds"] = round(time.monotonic() - started, 3)
    document["peak_rss_mib"] = round(_rss_bytes() / 1024**2, 1)
    document["chunk"] = chunk
    document["horizon_days"] = horizon
    _write(args.out, document)
    print(f"wrote {args.out}", flush=True)
    for row in rows:
        print(
            f"delta={row['delta']} p_kill_by_kill_date={row['p_kill_by_kill_date']:.4f} "
            f"p_kill_by_n_max={row['p_kill_by_n_max']:.4f} "
            f"median_n_at_kill={row['median_n_at_kill']} "
            f"clipped_mean_y={row['clipped_mean_y']:.6f}",
            flush=True,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replicates",
        type=int,
        default=None,
        help="replicate count (default: the MC --reps default; --subset-benchmark uses 8 and 32)",
    )
    parser.add_argument(
        "--subset-benchmark",
        action="store_true",
        help="tiny replicate count; print runtime and a full-run projection; do not write",
    )
    parser.add_argument("--amendment", type=Path, default=DEFAULT_AMENDMENT_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--candles", type=Path, default=_DATA_ROOT / "candles.jsonl")
    parser.add_argument("--markets-dir", type=Path, default=_DATA_ROOT)
    parser.add_argument("--max-memory-gib", type=float, default=DEFAULT_MAX_MEMORY_GIB)
    parser.add_argument("--seed", type=int, default=SEED)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    apply_address_space_cap(args.max_memory_gib)
    if args.replicates is not None and args.replicates <= 0:
        print("replicates must be positive", file=sys.stderr)
        return 2
    try:
        if args.subset_benchmark:
            # --replicates, when set, is the tiny count. The projection target stays the MC default.
            return _benchmark(args, mc_replicates())
        replicates = mc_replicates() if args.replicates is None else args.replicates
        return _full(args, replicates)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
