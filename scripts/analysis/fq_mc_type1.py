"""Exact-null Type-I cases for the FQ F5 N Monte-Carlo (E-25 mandatory cases, L-40 i / L-41).

Split out of `fq_resume_n_mc.py`. (i) Intraday-informed take count: the model takes on an intraday
signal, outcomes are correlated with it, the true conditional edge is exactly 0. (ii) Mixed-side
same-station-day takes with positive covariance. Both run through the shipped take rule.
"""

from __future__ import annotations

import datetime as dt
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from statistics import NormalDist
from typing import Any, Final

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.strategy.forecast_quantile_ladder.decision import SidedAsk, Take
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.quantile_density import Rung
from scripts.analysis.fq_mc_eprocess import (
    ALPHA_KILL,
    K_SLOTS,
    MAX_LAMBDA,
    ItemBatch,
    _alphas,
    eprocess_scan,
    items_to_yz,
    wilson_upper,
)
from scripts.analysis.fq_mc_livedata import (
    Design,
    LoopConfig,
    PoolDay,
    Side,
    _break_even,
    _call_evaluate,
    build_templates,
    simulate_pooled,
)


def _type1_rows(
    batch: ItemBatch, designs: Sequence[tuple[int, float]], earliest_look_n: int
) -> list[dict[str, Any]]:
    alphas = _alphas()
    n_cum = np.cumsum(batch.n_d, axis=1)
    rows = []
    for m_cap, x_max in designs:
        y, z = items_to_yz(batch, m_cap=m_cap, x_max=x_max)
        scan = eprocess_scan(
            y,
            z,
            n_cum,
            alphas=alphas,
            earliest_look_n=earliest_look_n,
            lam_max=MAX_LAMBDA,
            mu_max=MAX_LAMBDA,
            alpha_kill=ALPHA_KILL,
            x_max=x_max,
        )

        reps = int(y.shape[0])
        valid = batch.valid[..., :m_cap]
        be_taken = batch.be[..., :m_cap][valid]
        bite = float(np.mean(1.0 / be_taken - 1.0 > x_max)) if be_taken.size else 0.0
        stats: dict[str, Any] = {}
        for name, crossed in (
            ("type1_joint", scan.cross_joint),
            ("type1_a", scan.cross_a),
            ("type1_b", scan.cross_b),
        ):
            hits = [int((crossed[k] >= 0).sum()) for k in range(len(alphas))]
            rates = [x / reps for x in hits]
            stats[name] = {str(k + 1): r for k, r in enumerate(rates)}
            stats[f"{name}_se"] = {
                str(k + 1): math.sqrt(r * (1.0 - r) / reps) for k, r in enumerate(rates)
            }
            stats[f"{name}_wilson_ub"] = {
                str(k + 1): wilson_upper(x, reps) for k, x in enumerate(hits)
            }
        rows.append(
            {
                "m_cap": m_cap,
                "x_max": x_max,
                "reps": reps,
                **stats,
                "alpha_k": {str(k + 1): a for k, a in enumerate(alphas)},
                # KILL's null is E[Y] >= 0 AFTER the clip; a clipped null stream has E[Y] < 0, so
                # this is the rate at which a zero-edge stream is capital-protection killed.
                "p_kill_under_null_stream": float((scan.kill_n >= 0).mean()),
                "clipped_mean_y": float(y.mean()),
                "clip_bite_fraction": bite,
                "peak_joint_e_p99": float(np.exp(np.quantile(scan.peak_log_min, 0.99)))
                if scan.peak_log_min is not None
                else None,
            }
        )
    return rows


def type1_mixed_side(
    pool_days: Sequence[PoolDay],
    *,
    designs: Sequence[tuple[int, float]],
    reps: int,
    days: int,
    seed: int,
    pi_fav: float,
    earliest_look_n: int,
    delta_h: float = 0.0,
) -> dict[str, Any]:
    """(ii) Mixed-side same-station-day takes: comonotone outcomes, exact null.

    ``delta_h`` > 0 injects a true edge: a POSITIVE CONTROL that must trip PASS.
    """
    templates = build_templates(pool_days, pi_fav=pi_fav, seed=seed)
    batch = simulate_pooled(
        templates,
        Design(delta_h=delta_h),
        reps=reps,
        days=days,
        seed=seed,
        null=delta_h == 0.0,
        mixed_only=True,
    )
    assert batch.st is not None and batch.mixed is not None
    pair = batch.valid[..., 0] & batch.valid[..., 1] & (batch.st[..., 0] == batch.st[..., 1])
    cov = (batch.h[..., 0] - batch.be[..., 0]) * (batch.h[..., 1] - batch.be[..., 1])
    return {
        "case": "ii_mixed_side_same_station_day",
        "true_conditional_edge": delta_h,
        "mean_takes_per_day": float(batch.n_d.mean()),
        "looks_reached_fraction": float((batch.n_d.sum(axis=1) >= earliest_look_n).mean()),
        "mixed_side_fraction": float(batch.mixed.mean()),
        "pair_covariance": float(cov[pair].mean()) if pair.any() else 0.0,
        "positive_covariance": bool(pair.any() and cov[pair].mean() > 0.0),
        "rows": _type1_rows(batch, designs, earliest_look_n),
    }


def _ask_for_be(be: float, theta: float, haircut: float) -> float:
    """Invert BE = a_e + theta a_e (1 - a_e) for the quote (a_e = quote + haircut)."""
    a_e = ((1.0 + theta) - math.sqrt((1.0 + theta) ** 2 - 4.0 * theta * be)) / (2.0 * theta)
    return a_e - haircut


DEFAULT_PI0: Final[tuple[float, ...]] = (0.10, 0.18, 0.25, 0.32, 0.40, 0.50, 0.62)


def _pool_pi0(pool_days: Sequence[PoolDay] | None, cfg: LoopConfig) -> np.ndarray:
    if not pool_days:
        return np.array(DEFAULT_PI0)
    asks = [
        r.yes_ask
        for d in pool_days
        for _s, rungs in d.stations
        for r in rungs
        if cfg.ask_floor <= r.yes_ask <= 0.8
    ]
    return np.array([_break_even(a, cfg) for a in asks] or DEFAULT_PI0)


def _intraday_rep_day(
    rng: np.random.Generator,
    pi0_pool: np.ndarray,
    cfg: LoopConfig,
    *,
    stations: int,
    rungs: int,
    checkpoints: int,
    momentum: float,
    model_sd: float,
    leak: float,
) -> tuple[list[tuple[float, float, float, float]], float]:
    """One day. M ~ N(0,1); rung events are {M > t_r}; pi_k(r) = P(M > t_r | info_k) is a
    martingale and the quote is set so BE = pi_k exactly, so E[h | G_tau] = BE for every take.
    The model reads the intraday signal (its jump) and takes on it, so the take count depends
    on the path."""
    day = dt.date(2026, 6, 1)
    signal_abs = 0.0
    latch = QuantileLadderLatch()
    state = []
    for s in range(stations):
        pi0 = np.sort(rng.choice(pi0_pool, size=rungs, replace=False))[::-1]
        thr = np.array([_NORMAL.inv_cdf(1.0 - float(x)) for x in np.clip(pi0, 1e-6, 1 - 1e-6)])
        m_latent, noise_var = float(rng.standard_normal()), 3.0
        obs = m_latent + math.sqrt(noise_var) * rng.standard_normal(checkpoints)
        state.append((f"S{s}", thr, m_latent, obs, pi0.copy()))
    out: list[tuple[float, float, float, float]] = []
    for k in range(1, checkpoints + 1):
        for name, thr, m_latent, obs, prev in state:
            prec = 1.0 + k / 3.0
            post_mean, post_sd = (obs[:k].sum() / 3.0) / prec, math.sqrt(1.0 / prec)
            pi_k = np.array([1.0 - _NORMAL.cdf((float(t) - post_mean) / post_sd) for t in thr])
            ladder = tuple(Rung(f"R{r}", None, None) for r in range(rungs))
            for r in range(rungs):
                jump = float(pi_k[r] - prev[r])
                signal_abs += abs(jump)
                y_event = 1.0 if m_latent > thr[r] else 0.0
                p_hat = float(
                    np.clip(
                        pi_k[r] + momentum * jump + model_sd * rng.standard_normal(), 0.001, 0.999
                    )
                )
                # leak > 0 is a LOOK-AHEAD positive control: the model sees part of the outcome.
                p_hat = float(np.clip((1.0 - leak) * p_hat + leak * y_event, 0.001, 0.999))
                sides: tuple[tuple[Side, float], ...] = (
                    ("yes", float(pi_k[r])),
                    ("no", 1.0 - float(pi_k[r])),
                )
                for side, be in sides:
                    if not 0.02 < be < 0.97:
                        continue
                    ask = _ask_for_be(be, cfg.theta, cfg.haircut)
                    if not cfg.ask_floor <= ask <= cfg.ask_ceiling:
                        continue
                    decision = _call_evaluate(
                        climate_day=day,
                        station=name,
                        ladder=ladder,
                        rung_id=f"R{r}",
                        side=side,
                        ask=SidedAsk(side=side, instrument_id=f"{name}-R{r}-{side}", price=ask),
                        p_hat=p_hat,
                        cfg=cfg,
                        h_hours=cfg.h_hours + (checkpoints - k),
                        latch=latch,
                    )
                    if isinstance(decision, Take):
                        h = y_event if side == "yes" else 1.0 - y_event
                        p_side = p_hat if side == "yes" else 1.0 - p_hat
                        out.append((ask, be, p_side, h))
            prev[:] = pi_k
    # Decision order: checkpoint, then (station, rung, side); the loops above run in that order.
    return out, signal_abs


def type1_intraday(
    *,
    designs: Sequence[tuple[int, float]],
    reps: int,
    days: int,
    seed: int,
    earliest_look_n: int,
    pool_days: Sequence[PoolDay] | None = None,
    stations: int = 3,
    rungs: int = 4,
    checkpoints: int = 4,
    momentum: float = 0.25,
    model_sd: float = 0.03,
    leak: float = 0.0,
) -> dict[str, Any]:
    """(i) Intraday-informed take count.

    The model takes on an intraday signal, outcomes are correlated with that signal, and the true
    conditional edge is exactly 0 (BE = the true conditional probability).
    """
    cfg = LoopConfig()
    pi0_pool = _pool_pi0(pool_days, cfg)
    rng = np.random.default_rng(seed)
    shape = (reps, days, K_SLOTS)
    be, ask, p, h = (np.full(shape, 0.5) for _ in range(4))
    valid = np.zeros(shape, dtype=bool)
    n_d = np.zeros((reps, days), dtype=np.int64)
    signal = np.zeros((reps, days))
    for r in range(reps):
        for d in range(days):
            takes, signal[r, d] = _intraday_rep_day(
                rng,
                pi0_pool,
                cfg,
                stations=stations,
                rungs=rungs,
                checkpoints=checkpoints,
                momentum=momentum,
                model_sd=model_sd,
                leak=leak,
            )
            n_d[r, d] = len(takes)
            for j, (a, b, ps, hh) in enumerate(takes[:K_SLOTS]):
                ask[r, d, j], be[r, d, j], p[r, d, j], h[r, d, j], valid[r, d, j] = (
                    a,
                    b,
                    ps,
                    hh,
                    True,
                )
    batch = ItemBatch(be=be, ask=ask, p=p, h=h, valid=valid, n_d=n_d)
    taken = valid
    corr_sig = float(np.corrcoef(signal.ravel(), n_d.ravel())[0, 1]) if n_d.std() > 0 else 0.0
    corr_out = (
        float(np.corrcoef(be[taken], h[taken])[0, 1])
        if taken.sum() > 2 and h[taken].std() > 0
        else 0.0
    )
    return {
        "case": "i_intraday_informed_take_count",
        "true_conditional_edge": 0.0 if leak == 0.0 else None,
        "look_ahead_leak": leak,
        "looks_reached_fraction": float((n_d.sum(axis=1) >= earliest_look_n).mean()),
        "realised_mean_edge_first_slots": float((h - be)[taken].mean()) if taken.any() else 0.0,
        "mean_takes_per_day": float(n_d.mean()),
        "take_count_varies_with_signal": bool(n_d.std() > 0 and corr_sig > 0.0),
        "take_count_signal_correlation": corr_sig,
        "signal_outcome_correlation": corr_out,
        "rows": _type1_rows(batch, designs, earliest_look_n),
    }


_NORMAL: Final = NormalDist()
