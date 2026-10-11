"""EXEC-PAR BG-10(c): pure statistics for the D-PREREG section 5 simulation outputs.

No I/O, no clock, no randomness. Scalar reference implementations and vectorised batch
twins (a test pins that they agree). Everything here is a function of its arguments.

  * Wilson upper bound on n_eff = n / DEFF (DEFF = 1 + (m_bar - 1) * ICC);
  * one-way ANOVA ICC with n0 weighting, a negative estimate floored to 0.1;
  * exact Clopper-Pearson lower bound, and the critical-count table for "LB > p0";
  * burst detection on arm times (>= k events inside any window);
  * the two-look promotion schedule of section 1 / section 5 (first look at >= 8 days and
    >= 30 orders, one cumulative re-look 5 days later, stage cap 15 days).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Final

import numpy as np
import numpy.typing as npt

ICC_FLOOR: Final[float] = 0.1
MIN_LOOK_DAYS: Final[int] = 8
MIN_LOOK_ORDERS: Final[int] = 30
RELOOK_EXTENSION_DAYS: Final[int] = 5
STAGE_CAP_DAYS: Final[int] = 15
BURST_BASE_THRESHOLD: Final[int] = 5
BURST_RAISED_THRESHOLD: Final[int] = 6
BURST_RHO0_FALSE_ALARM_LIMIT: Final[float] = 0.10

IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


# ---- Wilson with a design effect --------------------------------------------------------------
def z_one_sided(level: float) -> float:
    """The standard-normal quantile of a one-sided ``level`` (0.90 -> 1.2816)."""
    if not 0.5 < level < 1.0:
        raise ValueError("a one-sided level must lie in (0.5, 1)")
    return NormalDist().inv_cdf(level)


def deff(m_bar: float, icc: float) -> float:
    """Design effect 1 + (m_bar - 1) * ICC, never below 1."""
    return max(1.0, 1.0 + (m_bar - 1.0) * icc)


def wilson_upper_deff(x: int, n: int, design_effect: float, z: float) -> float:
    """One-sided Wilson upper bound of x/n on the effective size n / design_effect.

    No data (n = 0) is no evidence: the bound is 1.0.
    """
    if n < 0 or x < 0 or x > n:
        raise ValueError("need 0 <= x <= n")
    if design_effect < 1.0:
        raise ValueError("a design effect below 1 is not admissible")
    if n == 0:
        return 1.0
    n_eff = n / design_effect
    p = x / n
    z2 = z * z
    centre = p + z2 / (2 * n_eff)
    half = z * math.sqrt(p * (1 - p) / n_eff + z2 / (4 * n_eff * n_eff))
    return min(1.0, (centre + half) / (1 + z2 / n_eff))


def wilson_upper_deff_batch(
    x: IntArray, n: IntArray, design_effect: FloatArray, z: float
) -> FloatArray:
    """Vectorised :func:`wilson_upper_deff` (n == 0 gives 1.0)."""
    xf = np.asarray(x, dtype=np.float64)
    nf = np.asarray(n, dtype=np.float64)
    safe_n = np.where(nf > 0, nf, 1.0)
    n_eff = safe_n / np.asarray(design_effect, dtype=np.float64)
    p = xf / safe_n
    z2 = z * z
    centre = p + z2 / (2 * n_eff)
    half = z * np.sqrt(p * (1 - p) / n_eff + z2 / (4 * n_eff * n_eff))
    out = np.minimum(1.0, (centre + half) / (1 + z2 / n_eff))
    return np.asarray(np.where(nf > 0, out, 1.0), dtype=np.float64)


# ---- one-way ANOVA ICC with n0 weighting -------------------------------------------------------
def floor_icc(raw: float) -> float:
    """The ICC used: max(0.1, raw); a negative or undefined estimate becomes 0.1."""
    if math.isnan(raw):
        return ICC_FLOOR
    return max(ICC_FLOOR, raw)


@dataclass(frozen=True)
class IccEstimate:
    raw: float
    n0: float
    used: float
    groups: int
    total: int


def anova_icc(groups: Sequence[tuple[int, int]]) -> IccEstimate:
    """Binary one-way ANOVA ICC from ``(m_i, y_i)`` day groups (m_i orders, y_i AMBIGUOUS).

    ICC = (MSB - MSW) / (MSB + (n0 - 1) MSW), n0 = (N - sum(m_i^2) / N) / (k - 1). Empty groups
    are dropped. An undefined estimate (k < 2, N = k, or a zero denominator) is NaN and the
    floored ``used`` value is 0.1.
    """
    for m, y in groups:
        if m < 0 or y < 0 or y > m:
            raise ValueError("a group needs 0 <= y <= m")
    kept = [(m, y) for m, y in groups if m > 0]
    k = len(kept)
    total = sum(m for m, _ in kept)
    if k < 2 or total - k <= 0:
        return IccEstimate(math.nan, math.nan, ICC_FLOOR, k, total)
    p_bar = sum(y for _, y in kept) / total
    msb = sum(m * (y / m - p_bar) ** 2 for m, y in kept) / (k - 1)
    msw = sum(y * (m - y) / m for m, y in kept) / (total - k)
    n0 = (total - sum(m * m for m, _ in kept) / total) / (k - 1)
    denom = msb + (n0 - 1.0) * msw
    raw = (msb - msw) / denom if denom > 0 else math.nan
    return IccEstimate(raw, n0, floor_icc(raw), k, total)


# ---- Clopper-Pearson ---------------------------------------------------------------------------
def binom_sf_ge(x: int, n: int, p: float) -> float:
    """P(Bin(n, p) >= x), exact, summed in log space."""
    if x <= 0:
        return 1.0
    if x > n:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    total = 0.0
    for j in range(x, n + 1):
        log_term = (
            math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1) + j * lp + (n - j) * lq
        )
        total += math.exp(log_term)
    return min(1.0, total)


def clopper_pearson_lower(x: int, n: int, alpha: float) -> float:
    """Exact one-sided lower confidence bound at level 1 - alpha: P(Bin(n, LB) >= x) = alpha."""
    if n < 1 or x < 0 or x > n:
        raise ValueError("need n >= 1 and 0 <= x <= n")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie in (0, 1)")
    if x == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if binom_sf_ge(x, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cp_critical_counts(n_max: int, p0: float, alpha: float, min_n: int) -> IntArray:
    """For each n in 0..n_max the smallest x whose Clopper-Pearson lower bound exceeds ``p0``.

    LB > p0 holds exactly when P(Bin(n, p0) >= x) < alpha. Below ``min_n`` (or when no x
    qualifies) the entry is n + 1: the rule can never fire there.
    """
    out = np.empty(n_max + 1, dtype=np.int64)
    start = 0  # the critical count never decreases with n: P(Bin(n, p0) >= x) grows with n
    for n in range(n_max + 1):
        crit = n + 1
        if n >= min_n and n >= 1:
            for x in range(start, n + 1):
                if binom_sf_ge(x, n, p0) < alpha:
                    crit = x
                    start = x
                    break
        out[n] = crit
    return out


# ---- burst -------------------------------------------------------------------------------------
def max_in_window(times_ns: Sequence[int], window_ns: int) -> int:
    """The largest number of events inside any window of ``window_ns`` (span <= window)."""
    ordered = sorted(times_ns)
    best = lo = 0
    for hi, t in enumerate(ordered):
        while t - ordered[lo] > window_ns:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def burst_tripped(times_ns: Sequence[int], threshold: int, window_ns: int) -> bool:
    """True iff at least ``threshold`` events (arm times) fall inside one ``window_ns``."""
    if threshold < 1:
        raise ValueError("the burst threshold must be at least 1")
    return max_in_window(times_ns, window_ns) >= threshold


def burst_threshold_applied(rho0_false_alarm_ge5: float) -> int:
    """5, unless the 15-day false alarm of >= 5 at p = 0.18, rho = 0 exceeds 10%: then 6."""
    if rho0_false_alarm_ge5 > BURST_RHO0_FALSE_ALARM_LIMIT:
        return BURST_RAISED_THRESHOLD
    return BURST_BASE_THRESHOLD


# ---- the two-look promotion schedule -----------------------------------------------------------
def first_look_day(
    entries: Sequence[int],
    min_days: int = MIN_LOOK_DAYS,
    min_orders: int = MIN_LOOK_ORDERS,
    cap: int = STAGE_CAP_DAYS,
) -> int | None:
    """The first climate day (1-based) on which both look minima hold, within the stage cap."""
    cum = 0
    for day, count in enumerate(entries[:cap], start=1):
        cum += count
        if day >= min_days and cum >= min_orders:
            return day
    return None


def relook_day(
    first: int, extension: int = RELOOK_EXTENSION_DAYS, cap: int = STAGE_CAP_DAYS
) -> int:
    """The single cumulative re-look: five days on, or day 15 if that is later."""
    return min(first + extension, cap)


@dataclass(frozen=True)
class TwoLook:
    first_look: int | None
    first_bound: float
    first_pass: bool
    second_look: int | None
    second_bound: float
    promoted: bool
    demoted: bool
    held: bool


def _bound_at(entries: Sequence[int], amb: Sequence[int], day: int, icc: float, z: float) -> float:
    n = sum(entries[:day])
    x = sum(amb[:day])
    return wilson_upper_deff(x, n, deff(n / day, icc), z)


def two_look_promotion(
    entries: Sequence[int], amb: Sequence[int], *, level: float, z: float, icc: float
) -> TwoLook:
    """Scalar reference of the section 5 promotion schedule on per-day counts (no exclusions).

    A look passes when the Wilson-DEFF bound on the pooled rate is <= ``level``. A first FAIL
    opens exactly one cumulative re-look; a second FAIL is a demotion verdict. A stage whose
    look minima are unmet by the 15-day cap holds (no look, no promotion, no demotion).
    """
    if len(entries) != len(amb):
        raise ValueError("entries and amb must have equal length")
    if any(e < 0 or a < 0 or a > e for e, a in zip(entries, amb, strict=True)):
        raise ValueError("need 0 <= amb <= entries on every day")
    first = first_look_day(entries)
    if first is None:
        return TwoLook(None, math.nan, False, None, math.nan, False, False, True)
    b1 = _bound_at(entries, amb, first, icc, z)
    if b1 <= level:
        return TwoLook(first, b1, True, None, math.nan, True, False, False)
    second = relook_day(first)
    b2 = _bound_at(entries, amb, second, icc, z)
    passed = b2 <= level
    return TwoLook(first, b1, False, second, b2, passed, not passed, False)


@dataclass(frozen=True)
class TwoLookBatch:
    first_look: IntArray  # 1-based day, 0 when the look minima were never met
    first_pass: BoolArray
    promoted: BoolArray
    demoted: BoolArray
    held: BoolArray


def two_look_promotion_batch(
    entries: IntArray, amb: IntArray, *, level: float, z: float, icc: float
) -> TwoLookBatch:
    """Vectorised :func:`two_look_promotion` over runs (rows) of per-day counts (columns)."""
    ent = np.asarray(entries, dtype=np.int64)[:, :STAGE_CAP_DAYS]
    bad = np.asarray(amb, dtype=np.int64)[:, :STAGE_CAP_DAYS]
    runs, days = ent.shape
    day_no = np.arange(1, days + 1, dtype=np.int64)
    cum_n = np.cumsum(ent, axis=1)
    cum_x = np.cumsum(bad, axis=1)
    m_bar = cum_n / day_no
    design = np.maximum(1.0, 1.0 + (m_bar - 1.0) * icc)
    bound = wilson_upper_deff_batch(cum_x, cum_n, design, z)
    eligible = (day_no >= MIN_LOOK_DAYS) & (cum_n >= MIN_LOOK_ORDERS)
    has_look = eligible.any(axis=1)
    first = np.where(has_look, eligible.argmax(axis=1) + 1, 0).astype(np.int64)
    rows = np.arange(runs)
    first_idx = np.maximum(first - 1, 0)
    first_pass = has_look & (bound[rows, first_idx] <= level)
    second = np.minimum(first + RELOOK_EXTENSION_DAYS, days)
    second_pass = has_look & ~first_pass & (bound[rows, np.maximum(second - 1, 0)] <= level)
    promoted = first_pass | second_pass
    return TwoLookBatch(first, first_pass, promoted, has_look & ~promoted, ~has_look)
