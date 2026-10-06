"""Relative calibration non-inferiority to the champion (AUT-4 r11 §3.10 R-C).

On the verdict's own station-days a reliability bucket is PAIRED when the candidate and the
champion each hold at least ``MIN_EVENTS_PER_BUCKET`` events in it. The statistic is
``dECE = ECE_cand - ECE_champ`` over paired buckets, each ECE the n-weighted mean
``|observed - predicted|`` with the model's own bucket counts as weights. The conjunct holds when
the one-sided ``(1 - alpha)`` upper bound of ``dECE``, from a paired date-cluster bootstrap
(dates resampled jointly for both models), is below the margin.

Bucket edges are ``scoring_core.RELIABILITY_BUCKET_EDGES`` and the bucket index is
``brier_decomposition.bin_by_edges``, so the binning is the one the moved reliability code uses.
The paired set is fixed on the full sample and held fixed across bootstrap draws.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple

import numpy as np

from breezy.analysis.brier_decomposition import bin_by_edges
from breezy.analysis.stats.scoring_core import RELIABILITY_BUCKET_EDGES

MIN_EVENTS_PER_BUCKET: Final[int] = 30
CHUNK_DRAWS: Final[int] = 4_096
DEFAULT_PERTURBATION_SD: Final[float] = 0.02
_EDGES: Final[tuple[float, ...]] = (0.0, *RELIABILITY_BUCKET_EDGES, 1.0)
_N_BUCKETS: Final[int] = len(_EDGES) - 1

OUTCOME_HOLDS: Final[str] = "HOLDS"
OUTCOME_FAILS: Final[str] = "FAILS"
OUTCOME_INCONCLUSIVE: Final[str] = "INCONCLUSIVE"
REASON_BUCKETS_BELOW_MIN: Final[str] = "calibration_buckets_below_min"


class NIStatistic(NamedTuple):
    ece_diff_ub: float
    n_buckets_paired: int


@dataclass(frozen=True, slots=True)
class NIVerdict:
    outcome: str
    reason: str | None
    ece_diff_ub: float | None
    n_buckets_paired: int


@dataclass(frozen=True, slots=True)
class FalseFailReport:
    rate: float
    n_trials: int
    n_failed: int
    n_below_min_buckets: int


class _Stats(NamedTuple):
    """Per (date, bucket) sufficient statistics: counts, probability sums, outcome sums."""

    n: np.ndarray
    p: np.ndarray
    y: np.ndarray


def _validate(
    cand: Sequence[tuple[float, bool]],
    champ: Sequence[tuple[float, bool]],
    dates: Sequence[dt.date],
) -> None:
    if not (len(cand) == len(champ) == len(dates)):
        raise ValueError("cand, champ and dates must be paired (equal length)")
    if not cand:
        raise ValueError("an empty station-day set has no calibration statistic")
    for (p_cand, y_cand), (p_champ, y_champ) in zip(cand, champ, strict=True):
        if not (0.0 <= p_cand <= 1.0 and 0.0 <= p_champ <= 1.0):
            raise ValueError("probabilities must lie in [0, 1]")
        if bool(y_cand) != bool(y_champ):
            raise ValueError("candidate and champion must score the same outcome per station-day")


def _stats(rows: Sequence[tuple[float, bool]], date_index: Sequence[int], n_dates: int) -> _Stats:
    key = bin_by_edges(_EDGES)
    n = np.zeros((n_dates, _N_BUCKETS))
    p = np.zeros((n_dates, _N_BUCKETS))
    y = np.zeros((n_dates, _N_BUCKETS))
    for (prob, outcome), d in zip(rows, date_index, strict=True):
        b = key(prob)
        assert isinstance(b, int)
        n[d, b] += 1.0
        p[d, b] += prob
        y[d, b] += float(bool(outcome))
    return _Stats(n, p, y)


def _ece(n: np.ndarray, p: np.ndarray, y: np.ndarray, paired: np.ndarray) -> np.ndarray:
    """ECE over the paired buckets for each row of weights; NaN where no event is left."""
    n_p = n[:, paired]
    total = n_p.sum(axis=1)
    safe = np.where(n_p > 0.0, n_p, 1.0)
    deviation = np.abs(y[:, paired] / safe - p[:, paired] / safe)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(
            total > 0.0, (n_p * deviation).sum(axis=1) / np.where(total > 0, total, 1.0), np.nan
        )


def relative_calibration_ni(
    cand: Sequence[tuple[float, bool]],
    champ: Sequence[tuple[float, bool]],
    dates: Sequence[dt.date],
    alpha: float,
    margin: float,
    seed: int,
    b: int,
) -> NIStatistic:
    """``(ece_diff_ub, n_buckets_paired)``: the one-sided ``(1 - alpha)`` upper bound of dECE.

    ``cand`` and ``champ`` are paired ``(probability, outcome)`` rows, one per station-day, and
    ``dates`` carries each row's climate date (the bootstrap cluster). ``margin`` is validated
    here and applied by :func:`evaluate_calibration_ni`. With no paired bucket the bound is NaN.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie in (0, 1), was {alpha!r}")
    if margin <= 0.0:
        raise ValueError(f"margin must be positive, was {margin!r}")
    if b <= 0:
        raise ValueError(f"b must be positive, was {b!r}")
    _validate(cand, champ, dates)
    unique = sorted(set(dates))
    index = {day: i for i, day in enumerate(unique)}
    date_index = [index[day] for day in dates]
    cs = _stats(cand, date_index, len(unique))
    hs = _stats(champ, date_index, len(unique))
    paired = (cs.n.sum(axis=0) >= MIN_EVENTS_PER_BUCKET) & (
        hs.n.sum(axis=0) >= MIN_EVENTS_PER_BUCKET
    )
    n_paired = int(paired.sum())
    if n_paired == 0:
        return NIStatistic(float("nan"), 0)

    rng = np.random.default_rng(seed)
    n_dates = len(unique)
    uniform = np.full(n_dates, 1.0 / n_dates)
    diffs: list[np.ndarray] = []
    remaining = b
    while remaining > 0:
        chunk = min(CHUNK_DRAWS, remaining)
        counts = rng.multinomial(n_dates, uniform, size=chunk).astype(np.float64)
        ece_c = _ece(counts @ cs.n, counts @ cs.p, counts @ cs.y, paired)
        ece_h = _ece(counts @ hs.n, counts @ hs.p, counts @ hs.y, paired)
        diffs.append(ece_c - ece_h)
        remaining -= chunk
    draws = np.concatenate(diffs)
    draws = draws[~np.isnan(draws)]
    if draws.size == 0:
        return NIStatistic(float("nan"), n_paired)
    upper = float(np.quantile(draws, 1.0 - alpha, method="higher"))
    return NIStatistic(upper, n_paired)


def evaluate_calibration_ni(
    cand: Sequence[tuple[float, bool]],
    champ: Sequence[tuple[float, bool]],
    dates: Sequence[dt.date],
    alpha: float,
    margin: float,
    min_buckets: int,
    seed: int,
    b: int,
) -> NIVerdict:
    """The (c) predicate: HOLDS iff the upper bound is below ``margin``.

    Fewer than ``min_buckets`` paired buckets is ``INCONCLUSIVE(calibration_buckets_below_min)``.
    """
    if min_buckets < 1:
        raise ValueError(f"min_buckets is a floor of 1, was {min_buckets!r}")
    stat = relative_calibration_ni(cand, champ, dates, alpha, margin, seed, b)
    if stat.n_buckets_paired < min_buckets or np.isnan(stat.ece_diff_ub):
        return NIVerdict(
            OUTCOME_INCONCLUSIVE, REASON_BUCKETS_BELOW_MIN, None, stat.n_buckets_paired
        )
    holds = stat.ece_diff_ub < margin
    return NIVerdict(
        OUTCOME_HOLDS if holds else OUTCOME_FAILS, None, stat.ece_diff_ub, stat.n_buckets_paired
    )


def false_fail_rate(
    champ: Sequence[tuple[float, bool]],
    dates: Sequence[dt.date],
    alpha: float,
    margin: float,
    min_buckets: int,
    seed: int,
    b: int,
    n_trials: int,
    perturbation_sd: float = DEFAULT_PERTURBATION_SD,
) -> FalseFailReport:
    """WP0 false-fail rate: how often a champion-equivalent candidate is rejected.

    Each trial perturbs the champion's own predictions with seeded Gaussian noise (clipped to
    [0, 1], outcomes unchanged), runs :func:`evaluate_calibration_ni` and counts a FAIL. Trials
    with too few paired buckets are INCONCLUSIVE and reported separately; they are not FAILs.
    """
    if n_trials <= 0:
        raise ValueError(f"n_trials must be positive, was {n_trials!r}")
    rng = np.random.default_rng(seed)
    failed = below = 0
    for trial in range(n_trials):
        noise = rng.normal(0.0, perturbation_sd, size=len(champ))
        cand = [
            (float(min(1.0, max(0.0, p + e))), bool(y))
            for (p, y), e in zip(champ, noise, strict=True)
        ]
        verdict = evaluate_calibration_ni(
            cand, champ, dates, alpha, margin, min_buckets, seed + 1 + trial, b
        )
        failed += verdict.outcome == OUTCOME_FAILS
        below += verdict.outcome == OUTCOME_INCONCLUSIVE
    return FalseFailReport(failed / n_trials, n_trials, failed, below)
