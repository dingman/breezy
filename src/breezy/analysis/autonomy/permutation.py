"""Studentised date-cluster sign-flip permutation test (AUT-4 r11 §3.2).

Per-station-day paired differences are summed per climate date and each date's sign is flipped as
a block, so the dependence inside a date is preserved. One-sided: the alternative is that the
summed differences are POSITIVE, so callers pass differences oriented "positive = candidate
better" (for example the negated Brier difference).

The statistic is ``T = sum_d D_d / sqrt(sum_d D_d^2)``. ``sum_d D_d^2`` is invariant under a sign
flip, so the studentisation is a monotone rescaling and the permutation p-value is exact in
distribution.

Draws are generated in chunks of ``CHUNK_FLIPS`` so memory stays near 16 MB at 120 dates. Exact
enumeration is used up to ``EXACT_MAX_DATES`` dates.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from breezy.persistence.autonomy.pins import BOOTSTRAP_B_MAX
from breezy.persistence.autonomy.sample_size import c_min

#: Exact enumeration of all 2^C sign vectors when the date count allows it.
EXACT_MAX_DATES: Final[int] = 20
CHUNK_FLIPS: Final[int] = 16_384
MIN_DRAWS: Final[int] = 10_000
DRAWS_PER_INVERSE_ALPHA: Final[int] = 200
#: Relative slack for comparing a flipped sum with the observed one (counts ties as >=).
_TIE_RELATIVE_TOLERANCE: Final[float] = 1e-12

METHOD_EXACT: Final[str] = "exact"
METHOD_MONTE_CARLO: Final[str] = "monte_carlo"
METHOD_HOEFFDING_TAIL: Final[str] = "hoeffding_tail"
METHOD_DEGENERATE: Final[str] = "degenerate"


class InsufficientClustersError(ValueError):
    """Fewer dates than ``c_min(alpha)``: the caller reports ``UNDERPOWERED(min_clusters)``."""

    def __init__(self, n_dates: int, required: int, alpha: float) -> None:
        super().__init__(f"{n_dates} date clusters < c_min({alpha}) = {required}")
        self.n_dates = n_dates
        self.required = required
        self.alpha = alpha


@dataclass(frozen=True, slots=True)
class PermutationResult:
    p_value: float
    p_method: str
    statistic: float
    n_dates: int
    draws: int
    #: True when the Hoeffding tail was reached; the caller raises a defect alert.
    defect_alert: bool


def required_draws(alpha: float) -> int:
    """``max(10_000, ceil(200 / alpha))``: the draws the level-``alpha`` test needs."""
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie in (0, 1), was {alpha!r}")
    return max(MIN_DRAWS, math.ceil(DRAWS_PER_INVERSE_ALPHA / alpha))


def draw_count(alpha: float, b_max: int = BOOTSTRAP_B_MAX) -> int:
    """``B = min(BOOTSTRAP_B_MAX, max(10_000, ceil(200 / alpha)))``."""
    return min(b_max, required_draws(alpha))


def _date_sums(diffs_by_date: Mapping[dt.date, Sequence[float]]) -> np.ndarray:
    sums = []
    for day in sorted(diffs_by_date):
        values = diffs_by_date[day]
        if len(values) == 0:
            raise ValueError(f"date {day} carries no differences")
        total = math.fsum(float(v) for v in values)
        if not math.isfinite(total):
            raise ValueError(f"date {day} carries a non-finite difference")
        sums.append(total)
    return np.asarray(sums, dtype=np.float64)


def _count_ge(sums: np.ndarray, observed: float, signs: np.ndarray, slack: float) -> int:
    return int(np.count_nonzero(signs @ sums >= observed - slack))


def _exact_count(sums: np.ndarray, observed: float, slack: float) -> tuple[int, int]:
    n_dates = len(sums)
    total = 1 << n_dates
    shifts = np.arange(n_dates, dtype=np.int64)
    hits = 0
    for start in range(0, total, CHUNK_FLIPS):
        index = np.arange(start, min(start + CHUNK_FLIPS, total), dtype=np.int64)
        signs = 1.0 - 2.0 * ((index[:, None] >> shifts[None, :]) & 1)
        hits += _count_ge(sums, observed, signs, slack)
    return hits, total


def _monte_carlo_count(
    sums: np.ndarray, observed: float, seed: int, draws: int, slack: float
) -> int:
    rng = np.random.default_rng(seed)
    hits = 0
    remaining = draws
    while remaining > 0:
        chunk = min(CHUNK_FLIPS, remaining)
        signs = 1.0 - 2.0 * rng.integers(0, 2, size=(chunk, len(sums)), dtype=np.int8)
        hits += _count_ge(sums, observed, signs, slack)
        remaining -= chunk
    return hits


def date_cluster_signflip(
    diffs_by_date: Mapping[dt.date, Sequence[float]],
    alpha: float,
    seed: int,
    b: int | None = None,
) -> PermutationResult:
    """One-sided date-cluster sign-flip p-value for "the summed differences are positive".

    ``b`` is the requested number of draws (default: ``draw_count(alpha)``). When the draws the
    level needs exceed ``BOOTSTRAP_B_MAX`` (or ``b`` does) the Monte-Carlo p-value cannot resolve
    ``alpha``; the conservative Hoeffding bound ``exp(-T_sum^2 / (2 * sum_d D_d^2))`` is returned
    instead, tagged ``hoeffding_tail`` with ``defect_alert`` set.
    """
    n_dates = len(diffs_by_date)
    floor = c_min(alpha)
    if n_dates < floor:
        raise InsufficientClustersError(n_dates, floor, alpha)
    sums = _date_sums(diffs_by_date)
    observed_sum = float(sums.sum())
    sum_squares = float(np.dot(sums, sums))
    if sum_squares == 0.0:
        return PermutationResult(1.0, METHOD_DEGENERATE, 0.0, n_dates, 0, False)
    statistic = observed_sum / math.sqrt(sum_squares)
    slack = _TIE_RELATIVE_TOLERANCE * float(np.abs(sums).sum())

    if n_dates <= EXACT_MAX_DATES:
        hits, total = _exact_count(sums, observed_sum, slack)
        return PermutationResult(hits / total, METHOD_EXACT, statistic, n_dates, total, False)

    draws = draw_count(alpha) if b is None else b
    if b is not None and b < required_draws(alpha):
        raise ValueError(
            f"b={b} is below required_draws({alpha}) = {required_draws(alpha)}; "
            "pass b=None to resolve it automatically"
        )
    if draws > BOOTSTRAP_B_MAX or (b is None and required_draws(alpha) > BOOTSTRAP_B_MAX):
        bound = math.exp(-(observed_sum**2) / (2.0 * sum_squares)) if observed_sum > 0.0 else 1.0
        return PermutationResult(bound, METHOD_HOEFFDING_TAIL, statistic, n_dates, 0, True)
    hits = _monte_carlo_count(sums, observed_sum, seed, draws, slack)
    return PermutationResult(
        (1 + hits) / (draws + 1), METHOD_MONTE_CARLO, statistic, n_dates, draws, False
    )
