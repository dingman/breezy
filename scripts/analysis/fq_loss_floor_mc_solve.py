"""Grid solver for the F6 loss-stop floor (r3 §4.5). Pure; no pool I/O.

``c`` is the smallest 0.01-grid value whose crossing rate is at most α.
A replicate crosses ``c`` exactly when :func:`first_crossing` would fire.
``critical_value`` is the sup of such ``c``, so ``critical > c`` matches that
strict boundary (equality is not a crossing).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from breezy.analysis.fq_loss_stop_core import first_crossing

__all__ = [
    "GRID_STEP",
    "binding_max",
    "binomial_se",
    "bootstrap_c_se",
    "critical_value",
    "crossing_rate",
    "path_rate",
    "rate_within_alpha",
    "single_day_share",
    "smallest_grid_c",
]

GRID_STEP: float = 0.01


def critical_value(increments: Sequence[float], *, t_min: int) -> float:
    """Supremum of ``c`` that :func:`first_crossing` still accepts, or ``-inf``."""
    if t_min < 1:
        raise ValueError("t_min must be >= 1")
    total = 0.0
    worst = -math.inf
    for t, increment in enumerate(increments, start=1):
        total += increment
        if t >= t_min:
            score = -total / math.sqrt(t)
            worst = max(worst, score)
    return worst


def crossing_rate(critical: np.ndarray, c: float) -> float:
    """Share of replicates with ``critical > c`` (strict, matching the core)."""
    if critical.size == 0:
        raise ValueError("crossing rate needs at least one replicate")
    return float(np.mean(critical > c))


def path_rate(paths: Sequence[Sequence[float]], c: float, *, t_min: int) -> float:
    """Crossing rate via :func:`first_crossing` itself, not the critical-value form."""
    if not paths:
        raise ValueError("path rate needs at least one replicate")
    hits = sum(first_crossing(path, c=c, t_min=t_min) is not None for path in paths)
    return hits / len(paths)


def smallest_grid_c(critical: np.ndarray, alpha: float, *, step: float = GRID_STEP) -> float:
    """Smallest grid ``c`` whose crossing rate is ≤ ``alpha``.

    The scan starts at ``step`` and stops at the first success. A larger grid
    point that also passes is not a solution.
    """
    if critical.size == 0:
        raise ValueError("c solver needs at least one replicate")
    if step <= 0.0 or not 0.0 <= alpha <= 1.0:
        raise ValueError(f"bad grid step {step!r} or alpha {alpha!r}")
    finite = critical[np.isfinite(critical)]
    if finite.size == 0:
        return step
    # One step past the largest finite critical. The rate is monotone, so the
    # smallest passing grid point is a binary search, not a linear scan.
    steps = max(1, math.floor(float(np.max(finite)) / step + 1e-9) + 1)
    ordered = np.sort(np.asarray(critical, dtype=float))
    count = int(ordered.size)
    lo, hi = 1, steps
    best = steps
    while lo <= hi:
        mid = (lo + hi) // 2
        c = round(mid * step, 10)
        greater = count - int(np.searchsorted(ordered, c, side="right"))
        if greater / count <= alpha + 1e-12:
            best = mid
            hi = mid - 1
        else:
            lo = mid + 1
    return round(best * step, 2)


def binding_max(
    cells: Mapping[tuple[str, str], float],
) -> tuple[float, tuple[str, str]]:
    """Maximum cell ``c``. Ties break by sorted ``(row, mix)``."""
    if not cells:
        raise ValueError("binding max needs at least one cell")
    best = max(cells.values())
    winners = sorted(key for key, value in cells.items() if value == best)
    return best, winners[0]


def binomial_se(rate: float, n: int) -> float:
    if n <= 0 or not 0.0 <= rate <= 1.0:
        raise ValueError(f"bad rate {rate!r} or n {n!r}")
    return math.sqrt(rate * (1.0 - rate) / n)


def rate_within_alpha(rate: float, *, alpha: float, se: float) -> bool:
    """Acceptance: rate ≤ α + 3·SE (r3 §4.5)."""
    if se < 0.0 or not math.isfinite(se):
        return False
    return rate <= alpha + 3.0 * se


def bootstrap_c_se(
    cells: Mapping[tuple[str, str], np.ndarray],
    *,
    alpha: float,
    seed: int,
    draws: int = 200,
) -> float:
    """Bootstrap standard error of the binding-max ``c`` over replicates."""
    if draws < 2 or not cells:
        raise ValueError("bootstrap needs two draws and at least one cell")
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=float)
    keys = list(cells)
    for index in range(draws):
        solved: list[float] = []
        for key in keys:
            sample = cells[key]
            if sample.size == 0:
                raise ValueError(f"empty replicates for {key!r}")
            drawn = sample[rng.integers(0, sample.size, size=sample.size)]
            solved.append(smallest_grid_c(drawn, alpha))
        estimates[index] = max(solved)
    return float(np.std(estimates, ddof=1))


def single_day_share(paths: Sequence[Sequence[float]], *, c: float, t_min: int) -> float | None:
    """Share of false stops whose first crossing is the first tick (S3)."""
    hits = 0
    single = 0
    for path in paths:
        crossed = first_crossing(path, c=c, t_min=t_min)
        if crossed is None:
            continue
        hits += 1
        if crossed == 1:
            single += 1
    if hits == 0:
        return None
    return single / hits
