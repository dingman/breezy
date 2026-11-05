"""The FQ KILL test and the diagnostic BSS-on-takes interval (E-25 rule 3; F7b-core). Pure, stdlib.

KILL validity (F7B-R10, restated by F7B-R22). The m = 0 capital ``prod(1 - lam_d * (Y_d - 0))``
with a predictable ``lam_d >= 0`` is a supermartingale whenever ``E[Y | F] >= 0`` -- the no-loss
null. By Ville's inequality the chance it ever reaches ``2/alpha_kill`` is at most ``alpha_kill/2``,
so a false KILL has probability at most ``alpha_kill / 2`` whenever the true edge is non-negative.
Under the PASS null (``E[Y] <= 0``) that capital grows and KILL is the intended outcome.

The bound is on the CLIPPED variable: it holds when ``E[Y_clipped] >= 0``. Upside clipping lowers
``Y`` (``X`` is cut at ``x_max``), so ``E[Y_clipped] <= E[Y_unclipped]``: a book whose unclipped
edge is exactly zero has a slightly negative clipped edge, and KILL is therefore slightly
anti-conservative for the unclipped edge (the false-KILL bound is not guaranteed at an unclipped
edge of exactly zero). The stated bound is exact only for the clipped edge.

The module also requires the capital at EVERY other grid point (``KILL_GRID_POINTS`` values of m
over ``[0, X_max]``) to be at the bar. Those extra points only add conservatism; they carry no
validity claim. The per-m cap on ``lam`` keeps ``1 - lam (Y - m) > 0`` for every ``Y`` in
``[-1, X_max]``. The grid, the cap, ``theta = 1/2`` and the bar ``log(2/alpha_kill)`` are the F5
Monte-Carlo constants, copied unchanged and filed as an F5 pin request.

The input is the CLIPPED, haircut-BE ``Y_d`` produced by ``eprocess``. ``alpha_kill`` is a separate
pinned parameter and is never charged into ``alpha_spent``.

``bss_on_takes`` is a DIAGNOSTIC: it never feeds an outcome. Its comparator is the RAW executable
ask (F7B-R21) and its interval is the day-clustered bootstrap of ``analysis/stats/scoring_core``.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from breezy.analysis.stats.scoring_core import (
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    CLUSTER_DATE,
    bootstrap_cluster_draws,
    percentile_interval,
)

__all__ = [
    "KILL_GRID_POINTS",
    "BssResult",
    "TakeScore",
    "bss_on_takes",
    "kill_bar",
    "kill_crossed",
    "kill_first_n",
    "kill_grid",
    "kill_log_capitals",
]

KILL_GRID_POINTS: Final = 5
KILL_MAX_LAMBDA: Final = 0.5
PRIOR_PSEUDO_DAYS: Final = 1
PRIOR_SECOND_MOMENT: Final = 0.25
_VAR_FLOOR: Final = 1e-6
_MIN_RANGE: Final = 0.5


def kill_bar(alpha_kill: float | Decimal) -> float:
    """``log(2/alpha_kill)``, converted from the stored level once."""
    value = float(alpha_kill)
    if not 0.0 < value < 1.0:
        raise ValueError(f"alpha_kill must be in (0, 1), got {alpha_kill!r}")
    return math.log(2.0 / value)


def kill_grid(x_max: float) -> tuple[float, ...]:
    """``KILL_GRID_POINTS`` evenly spaced values of m over ``[0, x_max]`` (numpy ``linspace``)."""
    if not (math.isfinite(x_max) and x_max > 0):
        raise ValueError("x_max must be a positive finite number")
    last = KILL_GRID_POINTS - 1
    return tuple(x_max * i / last for i in range(KILL_GRID_POINTS))


def _lambda_cap(m: float, x_max: float) -> float:
    return min(KILL_MAX_LAMBDA, 0.5 / max(x_max - m, _MIN_RANGE))


def _bet_fraction(sy: float, sy2: float, d: int, m: float, x_max: float) -> float:
    """The PREDICTABLE minus-side bet at day ``d`` for grid point ``m``: it is a function of the
    sums ``sy``/``sy2`` of the days strictly before ``d`` only (shrunk toward ``(0, 0.25)``)."""
    n = d + PRIOR_PSEUDO_DAYS
    mu = sy / n
    m2 = (sy2 + PRIOR_PSEUDO_DAYS * PRIOR_SECOND_MOMENT) / n
    var = max(m2 - mu * mu, _VAR_FLOOR)
    gap = m - mu
    return min(max(gap / (var + gap * gap), 0.0), _lambda_cap(m, x_max))


def kill_log_capitals(ys: Sequence[float], *, x_max: float) -> tuple[tuple[float, ...], ...]:
    """Per day, the log of the minus-side capital betting ``E[Y] < m`` at every grid m.

    The bet at day ``d`` uses days strictly before ``d`` only (predictable).
    """
    grid = kill_grid(x_max)
    log_k = [0.0] * len(grid)
    sy = sy2 = 0.0
    rows: list[tuple[float, ...]] = []
    for d, y in enumerate(ys):
        for j, m in enumerate(grid):
            lam = _bet_fraction(sy, sy2, d, m, x_max)
            log_k[j] += math.log1p(-lam * (y - m))
        sy, sy2 = sy + y, sy2 + y * y
        rows.append(tuple(log_k))
    return tuple(rows)


def kill_crossed(log_capitals: Sequence[float], bar: float) -> bool:
    """KILL needs every grid capital at the bar (a log-space ``>=``)."""
    return len(log_capitals) > 0 and all(value >= bar for value in log_capitals)


def kill_first_n(
    ys: Sequence[float],
    n_cum: Sequence[int],
    *,
    x_max: float,
    alpha_kill: float | Decimal,
    earliest_look_n: int,
) -> int | None:
    """The first ``n_cum`` at a look (``n_cum >= earliest_look_n``) where KILL fires, else None."""
    if len(ys) != len(n_cum):
        raise ValueError("ys and n_cum must have the same length")
    bar = kill_bar(alpha_kill)
    for n, row in zip(n_cum, kill_log_capitals(ys, x_max=x_max), strict=True):
        if n >= earliest_look_n and kill_crossed(row, bar):
            return n
    return None


@dataclass(frozen=True, slots=True)
class TakeScore:
    """One settled take for BSS-on-takes: the RAW executable ask, never the haircut BE."""

    climate_day: dt.date
    raw_ask: float
    p_model: float
    h: int

    def cluster_key(self, cluster: str) -> object:
        if cluster != CLUSTER_DATE:
            raise ValueError(f"BSS-on-takes clusters by calendar day only, got {cluster!r}")
        return self.climate_day


@dataclass(frozen=True, slots=True)
class BssResult:
    """The diagnostic BSS-on-takes. ``None`` fields mean the comparator was undefined."""

    point: float | None
    low: float | None
    high: float | None
    n_clusters: int
    cluster: str = CLUSTER_DATE


def _bss(scores: Sequence[TakeScore]) -> float | None:
    den = sum((s.raw_ask - s.h) ** 2 for s in scores)
    if den <= 0.0:
        return None
    return 1.0 - sum((s.p_model - s.h) ** 2 for s in scores) / den


def bss_on_takes(
    scores: Sequence[TakeScore],
    *,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> BssResult:
    """``1 - sum (p - y)^2 / sum (ask - y)^2`` over takes, with a day-clustered interval."""
    point = _bss(scores)
    n_clusters = len({s.climate_day for s in scores})
    if point is None:
        return BssResult(None, None, None, n_clusters)

    def statistic(sample: Sequence[TakeScore]) -> float:
        value = _bss(sample)
        return 0.0 if value is None else value

    draws = bootstrap_cluster_draws(
        scores, statistic=statistic, cluster=CLUSTER_DATE, iterations=iterations, seed=seed
    )
    low, high = percentile_interval(draws, alpha=BOOTSTRAP_ALPHA)
    return BssResult(point, low, high, n_clusters)
