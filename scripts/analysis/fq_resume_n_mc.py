#!/usr/bin/env python3
"""FQ F5 FQ-PREREG: the N Monte-Carlo for the PREREG v2 shadow e-process (CODE half).

Answers one question: how many takes N does the E-25 PASS rule need? N is the smallest n at which
the JOINT power of min(e_a, e_b) >= 1/alpha_k reaches 0.8, as a function of the true after-haircut
edge delta_h, the take rate, m_cap in {2, 3} and the upside clip X_max. It also runs the two
exact-null Type-I cases E-25 makes mandatory (L-40 / L-41) and reports the n-starvation outcome.

E-25 (docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md) is the authority:
    X_i = min(h_i/BE_i - 1, X_max)          downside never clipped; BE_i = haircut ask + fee
    Y_d = (1/m_cap) * sum_{i <= min(N_d, m_cap)} X_i      voids enter as 0; ties by (station, rung)
    e_a = prod(1 + lam_d Y_d)               lam_d predictable from settled days, <= 0.5
    e_b = prod(1 + mu_d Z_d)                Z_d the same pinned-denominator mean of S_i
    PASS = min(e_a, e_b) >= 1/alpha_k       gamma_t = g(t)/sum g, g(t) = 1/(t ln^2(t+1)), T = 4
    KILL = hedged CS on the clipped Y_d at 1 - alpha_kill (0.05) has UB < 0

THE LIVE LOOP IS IMPORTED, NEVER REIMPLEMENTED. Every take decision is made by the shipped
`forecast_quantile_ladder.decision.evaluate` (with its own latch, `venue_fee_prob`,
`forecast_margin`, `ev_net`/`ev_net_no`). Only its INPUTS are synthetic: a pooled ask and a
model view that is drawn so that the take RATE hits the requested value.

DATA. Asks are the Kalshi D-1 candlestick asks (`k1_kalshi_prior.ask_at_open`, the shipped
reader) dated BEFORE 2026-07-01 -- the day `nbp_calibration.DEFAULT_SPLITS` starts the sealed
holdout. Every row is dropped at or after that day, and nothing here calls the holdout opener.
Outcomes are NEVER read for the decision or the H1 draw: H0 outcomes are Bernoulli exactly at BE,
H1 outcomes are Bernoulli(BE + delta_h) at the sampled asks. Settled residuals are used only for
rho-hat (within-station-day correlation) and the variance, reported beside N.
LIMIT, stated: the model view (which rungs the shadow would take) is synthetic -- the out-of-fold
NBP rung probabilities are not wired here -- so the TAKE RATE is a parameter of the study, not an
estimate. N is therefore reported over the take-rate interval, as FQ-R15 requires.

Within one station-day the outcomes are COMONOTONE (one uniform per station-day). That is the
maximal positive dependence, so it covers the mixed-side positive-covariance case (L-40 i) and
is conservative for every pooled run.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.strategy.forecast_quantile_ladder.decision import evaluate
from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin
from breezy.strategy.weather_common.costs import venue_fee_prob
from scripts.analysis.fq_mc_eprocess import (
    ALPHA_KILL,
    BETTING_RULE,
    M_CAP_CHOICES,
    MAX_LAMBDA,
    ItemBatch,
    ScanResult,
    _alphas,
    agrapa_lambda,
    alpha_k,
    daily_y,
    eprocess_scan,
    gamma_schedule,
    items_to_yz,
    kill_first_n,
    n_for_power,
    order_takes,
    outcome_probability,
    residual_rho_var,
    take_x,
    wilson_upper,
)
from scripts.analysis.fq_mc_livedata import (
    HOLDOUT_START,
    Design,
    LoadStats,
    LoopConfig,
    PoolDay,
    PoolRung,
    _break_even,
    _yes_ask,
    build_templates,
    calibrate_take_rate,
    draw_model_view,
    filter_pre_holdout,
    group_days,
    load_pool,
    replay_live_day,
    simulate_pooled,
)
from scripts.analysis.fq_mc_type1 import type1_intraday, type1_mixed_side

__all__ = [
    "HOLDOUT_START",
    "MAX_LAMBDA",
    "Design",
    "ItemBatch",
    "LoopConfig",
    "PoolDay",
    "PoolRung",
    "agrapa_lambda",
    "alpha_k",
    "build_templates",
    "calibrate_take_rate",
    "daily_y",
    "draw_model_view",
    "eprocess_scan",
    "evaluate",
    "filter_pre_holdout",
    "forecast_margin",
    "gamma_schedule",
    "group_days",
    "items_to_yz",
    "kill_first_n",
    "load_pool",
    "n_for_power",
    "order_takes",
    "outcome_probability",
    "replay_live_day",
    "residual_rho_var",
    "simulate_pooled",
    "take_x",
    "type1_intraday",
    "type1_mixed_side",
    "venue_fee_prob",
    "wilson_upper",
]


KILL_DATE: Final[dt.date] = dt.date(2027, 1, 25)


def _cell(
    *,
    m_cap: int,
    x_max: float,
    delta_h: float,
    rate: float,
    realised: float,
    pi_fav: float,
    crosses: ScanResult,
    n_max: int,
    bite: float,
    reps: int,
) -> dict[str, Any]:
    def censor(a: np.ndarray) -> np.ndarray:
        return np.where(a > n_max, -1, a)

    joint = [censor(c) for c in crosses.cross_joint]
    by_k = {str(k + 1): n_for_power(c) for k, c in enumerate(joint)}
    kill = crosses.kill_n
    return {
        "m_cap": m_cap,
        "x_max": x_max,
        "delta_h": delta_h,
        "take_rate": rate,
        "realised_take_rate": realised,
        "pi_fav": pi_fav,
        "reps": reps,
        "n_max": n_max,
        "n_e_power": by_k["1"],
        "n_e_power_by_k": by_k,
        "n_e_power_a_only_k1": n_for_power(censor(crosses.cross_a[0])),
        "n_e_power_b_only_k1": n_for_power(censor(crosses.cross_b[0])),
        "power_at_n_max_k1": float((joint[0] >= 0).mean()),
        "p_kill_by_n_max": float(((kill >= 0) & (kill <= n_max)).mean()),
        "clip_bite_fraction": bite,
    }


def run_grid(
    pool_days: Sequence[PoolDay],
    *,
    deltas: Sequence[float],
    rates: Sequence[float],
    m_caps: Sequence[int],
    x_maxes: Sequence[float],
    reps: int,
    n_max: int,
    seed: int,
    earliest_look_n: int,
    chunk: int = 250,
    max_days: int = 9000,
    progress: Callable[[str], None] | None = None,
    cfg: LoopConfig | None = None,
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    alphas = _alphas()
    for rate in rates:
        pi_fav, templates = calibrate_take_rate(pool_days, target_rate=rate, seed=seed, cfg=cfg)
        realised = float(np.mean([t.n for t in templates]))
        horizon = min(max_days, max(10, math.ceil(1.15 * n_max / max(realised, 1e-3))))
        be_all = (
            np.array([t.be for tpl in templates for t in tpl.takes])
            if realised
            else np.array([0.5])
        )
        for delta in deltas:
            acc: dict[tuple[int, float], list[ScanResult]] = {
                (m, x): [] for m in m_caps for x in x_maxes
            }
            for ci, start in enumerate(range(0, reps, chunk)):
                n = min(chunk, reps - start)
                batch = simulate_pooled(
                    templates,
                    Design(delta_h=delta),
                    reps=n,
                    days=horizon,
                    seed=seed * 1009 + ci,
                    null=False,
                )
                n_cum = np.cumsum(batch.n_d, axis=1)
                for (m, x), store in acc.items():
                    y, z = items_to_yz(batch, m_cap=m, x_max=x)
                    store.append(
                        eprocess_scan(
                            y,
                            z,
                            n_cum,
                            alphas=alphas,
                            earliest_look_n=earliest_look_n,
                            lam_max=MAX_LAMBDA,
                            mu_max=MAX_LAMBDA,
                            alpha_kill=ALPHA_KILL,
                            x_max=x,
                        )
                    )
            for (m, x), parts in acc.items():
                merged = ScanResult(
                    np.concatenate([p.cross_joint for p in parts], axis=1),
                    np.concatenate([p.cross_a for p in parts], axis=1),
                    np.concatenate([p.cross_b for p in parts], axis=1),
                    np.concatenate([p.kill_n for p in parts]),
                    float(np.mean([p.mean_final_e_a for p in parts])),
                )
                bite = float(np.mean(1.0 / be_all - 1.0 > x))
                cells.append(
                    _cell(
                        m_cap=m,
                        x_max=x,
                        delta_h=delta,
                        rate=rate,
                        realised=realised,
                        pi_fav=pi_fav,
                        crosses=merged,
                        n_max=n_max,
                        bite=bite,
                        reps=reps,
                    )
                )
            if progress:
                progress(f"rate={rate} delta_h={delta} cells={len(cells)} horizon_days={horizon}")
    return cells


def n_starvation(
    *, n_required: Mapping[float, int], d0: dt.date, uptime_floor: float
) -> dict[str, Any]:
    """The n available before the KILL date at each take rate, against the N it needs."""
    days = (KILL_DATE - d0).days + 1
    by_rate: dict[str, Any] = {}
    for rate, need in sorted(n_required.items()):
        avail = int(rate * days * uptime_floor)
        by_rate[str(rate)] = {"n_available": avail, "n_required": need, "starved": avail < need}
    starved = [r for r, v in by_rate.items() if v["starved"]]
    statement = (
        f"n-starvation: {len(starved)} of {len(by_rate)} take rates cannot reach N before "
        f"{KILL_DATE.isoformat()} ({days} forward days from {d0.isoformat()}, "
        f"uptime floor {uptime_floor}). "
        "The M1 fallback is pre-registered: where the e-process on Takes is n-starved, the "
        "n-rich M1 path with forward-frozen confirmation is the primary route (FQ-R14)."
    )
    return {
        "kill_date": KILL_DATE.isoformat(),
        "d0": d0.isoformat(),
        "days_to_kill": days,
        "uptime_floor": uptime_floor,
        "by_rate": by_rate,
        "starved_rates": starved,
        "m1_fallback_preregistered": True,
        "statement": statement,
    }


_DATA_ROOT: Final[Path] = Path.home() / ".local/share/breezy/kalshi"


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.split(","))


def _pool_residuals(rows: Sequence[PoolRung], cfg: LoopConfig) -> list[list[float]]:
    by_day: dict[tuple[str, dt.date], list[float]] = {}
    for r in rows:
        if r.result is None or _yes_ask(r, cfg) is None or _break_even(r.yes_ask, cfg) >= 1.0:
            continue
        by_day.setdefault((r.station, r.climate_day), []).append(
            float(r.result) - _break_even(r.yes_ask, cfg)
        )
    return list(by_day.values())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--candles", type=Path, default=_DATA_ROOT / "candles.jsonl")
    p.add_argument("--markets-dir", type=Path, default=_DATA_ROOT)
    p.add_argument("--outdir", type=Path, required=True)
    p.add_argument("--deltas", type=_floats, default=(0.04, 0.08, 0.12, 0.16, 0.20))
    p.add_argument("--rates", type=_floats, default=(0.25, 0.5, 1.0))
    p.add_argument(
        "--m-caps", type=lambda s: tuple(int(x) for x in s.split(",")), default=M_CAP_CHOICES
    )
    p.add_argument("--x-maxes", type=_floats, default=(1.0, 2.0, 4.0))
    p.add_argument("--reps", type=int, default=2000)
    p.add_argument("--n-max", type=int, default=2000)
    p.add_argument("--pool-days", type=int, default=500)
    p.add_argument("--earliest-look-n", type=int, default=20)
    p.add_argument("--seed", type=int, default=20261006)
    p.add_argument("--d0", type=dt.date.fromisoformat, default=dt.date(2026, 10, 10))
    p.add_argument("--uptime-floor", type=float, default=0.9)
    p.add_argument("--type1-reps", type=int, default=1500)
    p.add_argument("--type1-days", type=int, default=60)
    p.add_argument("--type1-intraday-reps", type=int, default=800)
    p.add_argument("--type1-intraday-days", type=int, default=40)
    p.add_argument("--claim-excess", type=_floats, default=(0.01, 0.04, 0.08))
    p.add_argument("--sens-reps", type=int, default=1000)
    p.add_argument("--pinned-m-cap", type=int, default=2)
    p.add_argument("--pinned-x-max", type=float, default=4.0)
    p.add_argument("--skip-type1", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    def say(msg: str) -> None:
        print(f"PROGRESS +{time.monotonic() - t0:7.1f}s {msg}", flush=True)

    load_stats = LoadStats()
    rows = load_pool(args.candles, markets_dir=args.markets_dir, stats=load_stats)
    days_all = group_days(rows)
    rng = np.random.default_rng(args.seed)
    keep = sorted(rng.choice(len(days_all), size=min(args.pool_days, len(days_all)), replace=False))
    days = [days_all[i] for i in keep]
    say(
        f"pool rows={len(rows)} days={len(days_all)} sampled={len(days)} "
        f"max_day={max(r.climate_day for r in rows)}"
    )
    rho, var = residual_rho_var(_pool_residuals(rows, LoopConfig()))
    cells = run_grid(
        days,
        deltas=args.deltas,
        rates=args.rates,
        m_caps=args.m_caps,
        x_maxes=args.x_maxes,
        reps=args.reps,
        n_max=args.n_max,
        seed=args.seed,
        earliest_look_n=args.earliest_look_n,
        progress=say,
    )
    designs = [(m, x) for m in args.m_caps for x in args.x_maxes]
    type1: dict[str, Any] = {}
    if not args.skip_type1:
        pi_mixed = max((c["pi_fav"] for c in cells), default=0.5)
        type1["ii"] = type1_mixed_side(
            days,
            designs=designs,
            reps=args.type1_reps,
            days=args.type1_days,
            seed=args.seed,
            pi_fav=pi_mixed,
            earliest_look_n=args.earliest_look_n,
        )
        say("type-I (ii) mixed-side done")
        type1["i"] = type1_intraday(
            designs=designs,
            reps=args.type1_intraday_reps,
            days=args.type1_intraday_days,
            seed=args.seed,
            earliest_look_n=args.earliest_look_n,
            pool_days=days,
        )
        say("type-I (i) intraday done")
    sensitivity: list[dict[str, Any]] = []
    for excess in args.claim_excess:
        sens_cfg = dataclasses.replace(LoopConfig(), edge_excess_mean=excess)
        for cell in run_grid(
            days,
            deltas=args.deltas,
            rates=args.rates,
            m_caps=(args.pinned_m_cap,),
            x_maxes=(args.pinned_x_max,),
            reps=args.sens_reps,
            n_max=args.n_max,
            seed=args.seed + 7,
            earliest_look_n=args.earliest_look_n,
            cfg=sens_cfg,
        ):
            sensitivity.append({**cell, "edge_excess_mean": excess})
        say(f"claim sensitivity edge_excess_mean={excess} done")
    default_excess = LoopConfig().edge_excess_mean
    swept = [{**c, "edge_excess_mean": default_excess} for c in cells] + sensitivity
    starvation = starvation_by_delta(
        swept,
        args.rates,
        args.deltas,
        args.n_max,
        args.d0,
        args.uptime_floor,
        m_cap=args.pinned_m_cap,
        x_max=args.pinned_x_max,
    )
    result = {
        "pool": {
            "rows": len(rows),
            "days": len(days_all),
            "sampled_days": len(days),
            "cutoff_exclusive": HOLDOUT_START.isoformat(),
            "max_climate_day": max(r.climate_day for r in rows).isoformat(),
            "load_stats": load_stats.as_dict(),
        },
        "residual_rho_hat": rho,
        "residual_variance": var,
        "alpha_k": {str(k): a for k, a in enumerate(_alphas(), start=1)},
        "betting_rule": BETTING_RULE,
        "earliest_look_n": args.earliest_look_n,
        "cells": cells,
        "claim_sensitivity": sensitivity,
        "type1": type1,
        "n_starvation": starvation,
        "elapsed_s": time.monotonic() - t0,
        "seed": args.seed,
    }
    out = args.outdir / f"fq_resume_n_mc_seed{args.seed}.json"
    out.write_text(json.dumps(result, indent=1, sort_keys=True, default=str), encoding="utf-8")
    say(f"wrote {out}")
    print(format_table(cells))
    print(starvation["statement"])
    return 0


def _worst_case_n(
    cells: Sequence[Mapping[str, Any]], *, rate: float, delta: float, k: str, n_max: int
) -> int:
    """Largest N over the matching cells; a cell that never reached power counts as n_max + 1."""
    ns = [
        c["n_e_power_by_k"][k] if c["n_e_power_by_k"][k] is not None else n_max + 1
        for c in cells
        if c["take_rate"] == rate and c["delta_h"] == delta
    ]
    return max(ns) if ns else n_max + 1


def starvation_by_delta(
    cells: Sequence[Mapping[str, Any]],
    rates: Sequence[float],
    deltas: Sequence[float],
    n_max: int,
    d0: dt.date,
    uptime_floor: float,
    *,
    m_cap: int = 2,
    x_max: float = 4.0,
) -> dict[str, Any]:
    """Per delta_h at the PINNED design: joint N (k=1 and k=4) against n available before the KILL.

    The headline N is the worst case over every cell supplied for that (rate, delta_h), i.e. over
    the model-claim (edge_excess) sensitivity sweep. Cells of any other design are ignored.
    """
    pinned = [c for c in cells if c["m_cap"] == m_cap and c["x_max"] == x_max]
    per_delta: dict[str, Any] = {}
    for delta in deltas:
        row: dict[str, Any] = {}
        for label, k in (("k1", "1"), ("k4", "4")):
            need = {r: _worst_case_n(pinned, rate=r, delta=delta, k=k, n_max=n_max) for r in rates}
            row[label] = n_starvation(n_required=need, d0=d0, uptime_floor=uptime_floor)["by_rate"]
        per_delta[str(delta)] = row
    base = n_starvation(n_required={r: n_max + 1 for r in rates}, d0=d0, uptime_floor=uptime_floor)
    every = all(
        v["starved"]
        for row in per_delta.values()
        for by_rate in row.values()
        for v in by_rate.values()
    )
    verdict = (
        "STARVED at every (delta_h, take rate) grid point"
        if every
        else "not starved at every grid point"
    )
    return {
        "kill_date": base["kill_date"],
        "d0": base["d0"],
        "days_to_kill": base["days_to_kill"],
        "uptime_floor": uptime_floor,
        "n_max_horizon": n_max,
        "pinned_design": {"m_cap": m_cap, "x_max": x_max},
        "headline_basis": "worst_case_over_edge_excess_sweep",
        "by_delta": per_delta,
        "starved_at_every_grid_point": every,
        "m1_fallback_preregistered": True,
        "statement": (
            f"n-starvation outcome at m_cap={m_cap}, X_max={x_max}: {verdict}; "
            f"{base['days_to_kill']} forward days from {base['d0']} to {base['kill_date']} at "
            f"uptime floor {uptime_floor}. "
            "The M1 fallback is pre-registered: where the e-process on Takes is n-starved, the "
            "n-rich M1 path with forward-frozen confirmation is the primary route (FQ-R14)."
        ),
    }


def format_table(cells: Sequence[Mapping[str, Any]]) -> str:
    """N (joint, k=1) by m_cap, x_max, delta_h (rows) and take rate (columns)."""
    rates = sorted({c["take_rate"] for c in cells})
    lines = [
        "| m_cap | x_max | delta_h | " + " | ".join(f"rate {r}" for r in rates) + " |",
        "|---|---|---|" + "---|" * len(rates),
    ]
    keys = sorted({(c["m_cap"], c["x_max"], c["delta_h"]) for c in cells})
    for m, x, d in keys:
        row = []
        for r in rates:
            cell = next(
                c
                for c in cells
                if (c["m_cap"], c["x_max"], c["delta_h"], c["take_rate"]) == (m, x, d, r)
            )
            row.append(
                str(cell["n_e_power"]) if cell["n_e_power"] is not None else f">{cell['n_max']}"
            )
        lines.append(f"| {m} | {x} | {d} | " + " | ".join(row) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
