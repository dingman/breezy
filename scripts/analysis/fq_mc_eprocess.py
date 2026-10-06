"""E-25 e-process pieces and the vectorised scan for the FQ F5 N Monte-Carlo (pure, no I/O).

Split out of `fq_resume_n_mc.py`. X_i, Y_d (pinned denominator m_cap), the predictable betting
rule, e_a / e_b, the hedged KILL CS and the joint-power N, exactly as E-25
(docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md) defines them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

ALPHA_TOTAL: Final[float] = 0.025


ALPHA_KILL: Final[float] = 0.05


T_NOMINATIONS: Final[int] = 4


MAX_LAMBDA: Final[float] = 0.5


M_CAP_CHOICES: Final[tuple[int, ...]] = (2, 3)


K_SLOTS: Final[int] = max(M_CAP_CHOICES)


POWER_TARGET: Final[float] = 0.8


KILL_GRID_POINTS: Final[int] = 5


PRIOR_PSEUDO_DAYS: Final[int] = 1


PRIOR_SECOND_MOMENT: Final[float] = 0.25


BETTING_RULE: Final[str] = "agrapa_v1:prior_pseudo_days=1,prior_second_moment=0.25"


def wilson_upper(successes: int, trials: int, *, z: float = 1.959963984540054) -> float:
    """Upper end of the Wilson score interval for a rate of ``successes`` in ``trials``."""
    if trials <= 0:
        return 1.0
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = p + z * z / (2.0 * trials)
    half = z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))
    return min(1.0, (centre + half) / denom)


def gamma_schedule(horizon: int = T_NOMINATIONS) -> tuple[float, ...]:
    """gamma_t = g(t)/sum_{s<=T} g(s), g(t) = 1/(t ln^2(t+1))."""
    g = [1.0 / (t * math.log(t + 1.0) ** 2) for t in range(1, horizon + 1)]
    total = sum(g)
    return tuple(x / total for x in g)


def alpha_k(k: int, *, promotions: int = 0, horizon: int = T_NOMINATIONS) -> float:
    """alpha_k = alpha_total * gamma_k * (R + 1) -- E-25 rule 4; R = 0 for the first nomination."""
    return ALPHA_TOTAL * gamma_schedule(horizon)[k - 1] * (promotions + 1)


def take_x(h: float, be: float, x_max: float) -> float:
    """X_i = min(h/BE - 1, X_max). The upside is clipped; the downside (-1) never is."""
    return min(h / be - 1.0, x_max)


def daily_y(xs: Sequence[float], *, m_cap: int) -> float:
    """Y_d = (1/m_cap) sum_{i <= min(N_d, m_cap)} X_i. Empty slots count 0; takes past the cap are
    excluded (and disclosed upstream). ``xs`` is already in decision order; a void is a 0 entry."""
    if m_cap not in M_CAP_CHOICES:
        raise ValueError(f"m_cap must be one of {M_CAP_CHOICES}, got {m_cap!r}")
    return sum(xs[:m_cap]) / m_cap


def _take_key(take: Any) -> tuple[str, str, str]:
    if isinstance(take, tuple):
        return (str(take[0]), str(take[1]), str(take[2]) if len(take) > 2 else "")
    return (take.station, take.rung_id, take.side)


def order_takes[T](takes: Sequence[T]) -> list[T]:
    """Ties at one decision instant are ordered by G-measurable keys only: (station, rung id)
    lexicographic (side is a last, still G-measurable, tie-break). Never outcome or arrival
    order."""
    return sorted(takes, key=_take_key)


def agrapa_lambda(sum_x: Any, sum_x2: Any, n_prev: int, *, cap: float) -> Any:
    """Predictable betting fraction from SETTLED days only (the pinned `agrapa_v1` rule).

    mu-hat and the second moment shrink toward (0, PRIOR_SECOND_MOMENT) with PRIOR_PSEUDO_DAYS
    pseudo-days; lam = clip(mu / (var + mu^2), 0, cap). Never negative, never above ``cap``.
    """
    n = n_prev + PRIOR_PSEUDO_DAYS
    mu = np.asarray(sum_x, dtype=float) / n
    m2 = (np.asarray(sum_x2, dtype=float) + PRIOR_PSEUDO_DAYS * PRIOR_SECOND_MOMENT) / n
    var = np.maximum(m2 - mu * mu, 1e-6)
    return np.clip(mu / (var + mu * mu), 0.0, cap)


def outcome_probability(be: float, *, delta_h: float, null: bool) -> float:
    """H0: Bernoulli exactly at BE. H1: Bernoulli(BE + delta_h) at the sampled ask, capped at 1."""
    return be if null else min(1.0, be + delta_h)


@dataclass(slots=True)
class ItemBatch:
    """Per (rep, day) the first K_SLOTS takes in decision order, plus the full take count."""

    be: np.ndarray
    ask: np.ndarray
    p: np.ndarray
    h: np.ndarray
    valid: np.ndarray
    n_d: np.ndarray
    st: np.ndarray | None = None  # station index per slot (pooled runs)
    mixed: np.ndarray | None = None  # (rep, day): the day's template is mixed-side


def items_to_yz(batch: ItemBatch, *, m_cap: int, x_max: float) -> tuple[np.ndarray, np.ndarray]:
    """Y_d and Z_d on the pinned denominator m_cap.

    Empty slots count 0, takes past the cap are excluded, voids are 0 slots.
    """
    valid = batch.valid[..., :m_cap]
    h, be = batch.h[..., :m_cap], batch.be[..., :m_cap]
    x = np.minimum(h / be - 1.0, x_max) * valid
    s = ((batch.ask[..., :m_cap] - h) ** 2 - (batch.p[..., :m_cap] - h) ** 2) * valid
    return x.sum(axis=-1) / m_cap, s.sum(axis=-1) / m_cap


@dataclass(slots=True)
class ScanResult:
    cross_joint: np.ndarray  # (K, R): n_cum at the first PASS look, -1 if never
    cross_a: np.ndarray
    cross_b: np.ndarray
    kill_n: np.ndarray  # (R,)
    mean_final_e_a: float
    peak_log_min: np.ndarray | None = None  # (R,) max over looks of log min(e_a, e_b)


def _kill_grid(x_max: float) -> np.ndarray:
    return np.linspace(0.0, x_max, KILL_GRID_POINTS)


def _kill_increment(
    y_d: np.ndarray, sy: np.ndarray, sy2: np.ndarray, n_prev: int, grid: np.ndarray, x_max: float
) -> np.ndarray:
    """log(1 - lam_m (Y - m)) for the minus-side capital betting that E[Y] < m, per grid m."""
    n = n_prev + PRIOR_PSEUDO_DAYS
    mu = (sy / n)[:, None]
    m2 = ((sy2 + PRIOR_PSEUDO_DAYS * PRIOR_SECOND_MOMENT) / n)[:, None]
    var = np.maximum(m2 - mu * mu, 1e-6)
    gap = grid[None, :] - mu
    cap = np.minimum(MAX_LAMBDA, 0.5 / np.maximum(x_max - grid, 0.5))[None, :]
    lam = np.clip(gap / (var + gap * gap), 0.0, cap)
    out: np.ndarray = np.log1p(-lam * (y_d[:, None] - grid[None, :]))
    return out


def eprocess_scan(
    y: np.ndarray,
    z: np.ndarray,
    n_cum: np.ndarray,
    *,
    alphas: Sequence[float],
    earliest_look_n: int,
    lam_max: float,
    mu_max: float,
    alpha_kill: float,
    x_max: float,
) -> ScanResult:
    """Walk the days.

    PASS at alpha_k is min(e_a, e_b) >= 1/alpha_k at a look with n >= earliest_look_n.

    KILL is the hedged CS (theta = 1/2) at 1 - alpha_kill having UB < 0: every grid m >= 0
    excluded by the minus-side capital. Both statistics use the same predictable,
    settled-days-only betting rule.
    """
    reps, days = y.shape
    log_a, log_b = np.zeros(reps), np.zeros(reps)
    sy, sy2, sz, sz2 = (np.zeros(reps) for _ in range(4))
    grid = _kill_grid(x_max)
    log_k = np.zeros((reps, grid.size))
    shape = (len(alphas), reps)
    cross_j, cross_a, cross_b = (np.full(shape, -1, dtype=np.int64) for _ in range(3))
    kill_n = np.full(reps, -1, dtype=np.int64)
    peak = np.full(reps, -np.inf)
    kill_bar = math.log(2.0 / alpha_kill)
    for d in range(days):
        yd, zd = y[:, d], z[:, d]
        lam = agrapa_lambda(sy, sy2, d, cap=lam_max)
        mu = agrapa_lambda(sz, sz2, d, cap=mu_max)
        log_k += _kill_increment(yd, sy, sy2, d, grid, x_max)
        log_a += np.log1p(lam * yd)
        log_b += np.log1p(mu * zd)
        sy += yd
        sy2 += yd * yd
        sz += zd
        sz2 += zd * zd
        look = n_cum[:, d] >= earliest_look_n
        lmin = np.minimum(log_a, log_b)
        peak = np.where(look, np.maximum(peak, lmin), peak)
        for k, alpha in enumerate(alphas):
            bar = -math.log(alpha)
            for target, stat in ((cross_j, lmin), (cross_a, log_a), (cross_b, log_b)):
                hit = look & (stat >= bar) & (target[k] < 0)
                target[k][hit] = n_cum[hit, d]
        dead = look & (kill_n < 0) & (log_k >= kill_bar).all(axis=1)
        kill_n[dead] = n_cum[dead, d]
    return ScanResult(cross_j, cross_a, cross_b, kill_n, float(np.exp(log_a).mean()), peak)


def kill_first_n(
    y: np.ndarray, n_cum: np.ndarray, *, x_max: float, alpha_kill: float, earliest_look_n: int
) -> np.ndarray:
    """First n_cum at which the hedged CS on Y has UB < 0 (-1 if never)."""
    scan = eprocess_scan(
        y,
        np.zeros_like(y),
        n_cum,
        alphas=(0.5,),
        earliest_look_n=earliest_look_n,
        lam_max=MAX_LAMBDA,
        mu_max=MAX_LAMBDA,
        alpha_kill=alpha_kill,
        x_max=x_max,
    )
    return scan.kill_n


def n_for_power(cross: np.ndarray, *, target: float = POWER_TARGET) -> int | None:
    """Smallest n with P(first PASS look has n_cum <= n) >= target.

    None if the target is unreachable inside the horizon.
    """
    finite = np.sort(cross[cross >= 0])
    need = max(1, math.ceil(target * len(cross) - 1e-9))
    return int(finite[need - 1]) if len(finite) >= need else None


def residual_rho_var(resid_by_day: Sequence[Sequence[float]]) -> tuple[float, float]:
    """rho-hat (mean within-station-day cross product / variance) and the residual variance."""
    cross = pairs = total = count = 0.0
    for day in resid_by_day:
        k = len(day)
        s, s2 = sum(day), sum(r * r for r in day)
        cross += s * s - s2
        pairs += k * (k - 1)
        total += s2
        count += k
    var = total / count if count else 0.0
    rho = (cross / pairs) / var if pairs and var > 0 else 0.0
    return max(-1.0, min(1.0, rho)), var


def _alphas() -> tuple[float, ...]:
    return tuple(alpha_k(k) for k in range(1, T_NOMINATIONS + 1))
