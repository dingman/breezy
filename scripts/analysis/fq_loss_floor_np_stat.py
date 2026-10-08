"""Pure Neyman–Pearson pieces for the Stage 0 G3 bound.

The critical value is an H0 quantile. The test rejects only when the
log-likelihood ratio is strictly larger, so atoms on the boundary do not
reject and the bound is conservative. A positive infinite ratio always rejects.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict

import numpy as np

from breezy.analysis.fq_loss_stop_core import VARIANCE_EPS, step_clock
from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay, TickDraw, _outcome_h
from scripts.analysis.fq_loss_floor_mc_rows import _normalised, h1_win_probability
from scripts.analysis.fq_loss_floor_mc_solve import critical_value, crossing_rate

__all__ = [
    "ALPHA_NOMINAL",
    "DELTA_H1",
    "E_PROJ",
    "REACH",
    "InformationReport",
    "conditional_variance_table",
    "count_summary",
    "d1_decision",
    "discrete_critical_value",
    "information_identity",
    "information_prefix",
    "json_float",
    "linear_s_threshold_power",
    "log_lr_totals",
    "mean_conditional_information",
    "np_bound_power",
    "np_rejects",
    "outcome_log_lr",
    "realised_tick_counts",
    "sqrt_boundary_rate",
]

#: Coordinator pin, written verbatim. Projected A1b + F6c + F9-B arming is
#: 2026-10-29, so the first epoch-grid date on or after that day.
E_PROJ: str = "2026-11-01"
DELTA_H1: float = -0.16
ALPHA_NOMINAL: float = 0.10
REACH: float = 0.30
_TOL: float = 1e-9


class IVariance(TypedDict):
    definition: str
    conditional_variance_min: float
    conditional_variance_max: float
    conditional_variance_sum: float
    per_tick_equals_one: bool


class InformationReport(TypedDict):
    information_identity_holds: bool
    max_abs_mean_z: float
    max_abs_second_moment_gap: float
    days_checked: int
    I_t: NotRequired[IVariance]


def categorical_mass(masses: Sequence[float], index: int) -> float:
    """Mass of winner ``index``. The last slot is the residual outcome."""
    if index < 0:
        raise ValueError(f"outcome index must be non-negative, got {index}")
    if index < len(masses):
        return float(masses[index])
    return max(0.0, 1.0 - float(math.fsum(float(mass) for mass in masses)))


def mass_log_lr(h0: float, h1: float) -> float:
    """log(h1/h0). H0 mass 0 against a positive H1 mass is +inf."""
    if h0 <= 0.0 < h1:
        return math.inf
    if h1 <= 0.0 < h0:
        return -math.inf
    if h0 <= 0.0 and h1 <= 0.0:
        return 0.0
    return math.log(h1) - math.log(h0)


def _vector(prep: PreparedDay, index: int) -> tuple[float, ...]:
    return tuple(_outcome_h(leg, index, slot) for slot, leg in enumerate(prep.day.legs))


def _h0_of_vector(prep: PreparedDay, hs: Sequence[float]) -> float:
    target = tuple(float(item) for item in hs)
    for index in range(len(prep.day.legs) + 1):
        if _vector(prep, index) == target:
            return categorical_mass(prep.masses, index)
    return 0.0


def _bernoulli(probabilities: Sequence[float], hs: Sequence[float]) -> float:
    prob = 1.0
    for chance, outcome in zip(probabilities, hs, strict=True):
        prob *= chance if outcome == 1.0 else (1.0 - chance)
    return prob


def outcome_log_lr(
    prep: PreparedDay,
    *,
    delta: float,
    index: int | None,
    hs: tuple[float, ...] | None,
) -> float:
    """Log LR of one drawn station-day. Bernoulli only where H1 masses are None."""
    h1_masses = prep.h1.get(delta)
    if h1_masses is None and prep.day.legs:
        vector = hs if hs is not None else None if index is None else _vector(prep, index)
        if vector is None:
            raise ValueError("Bernoulli fallback draw has no outcome")
        chances = tuple(h1_win_probability(leg.be, delta=delta) for leg in prep.day.legs)
        return mass_log_lr(_h0_of_vector(prep, vector), _bernoulli(chances, vector))
    if index is None:
        raise ValueError("categorical draw has no outcome index")
    h1 = () if h1_masses is None else h1_masses
    return mass_log_lr(categorical_mass(prep.masses, index), categorical_mass(h1, index))


def np_rejects(stat: float, crit: float) -> bool:
    """Strict exceedance. +inf rejects even when the critical value is +inf."""
    if math.isinf(stat) and stat > 0.0:
        return True
    return stat > crit


def discrete_critical_value(stats: Sequence[float], alpha: float) -> float:
    """Smallest order statistic whose strict upper tail has mass at most ``alpha``."""
    if not stats:
        raise ValueError("critical value needs replicates")
    if not 0.0 <= alpha <= 1.0 or not math.isfinite(alpha):
        raise ValueError(f"alpha must be in [0, 1], got {alpha!r}")
    ordered = sorted(stats)
    count = len(ordered)
    tail = math.floor(alpha * count + 1e-12)
    if tail >= count:
        return -math.inf
    if tail <= 0:
        return ordered[-1]
    return ordered[count - tail - 1]


def rejection_rate(stats: Sequence[float], crit: float) -> float:
    if not stats:
        raise ValueError("rejection rate needs replicates")
    hits = sum(np_rejects(stat, crit) for stat in stats)
    return hits / len(stats)


def np_bound_power(h0_stats: Sequence[float], h1_stats: Sequence[float], alpha: float) -> float:
    """H1 rejection rate of the conservative LR test calibrated on ``h0_stats``."""
    return rejection_rate(h1_stats, discrete_critical_value(h0_stats, alpha))


def linear_s_threshold_power(h0_s: Sequence[float], h1_s: Sequence[float], alpha: float) -> float:
    """Power of rejecting large −S_t, calibrated on the same H0 replicates."""
    return np_bound_power(tuple(-item for item in h0_s), tuple(-item for item in h1_s), alpha)


def information_prefix[T](
    path: Sequence[T],
    cuts: Sequence[int],
    *,
    n_days: int,
    t_k: int,
) -> tuple[T, ...]:
    """Ticks in the first ``n_days`` calendar days, then cut at ``t_k``."""
    if t_k < 0:
        raise ValueError(f"t_K must be non-negative, got {t_k}")
    if n_days <= 0 or not cuts:
        return ()
    end = cuts[min(n_days, len(cuts)) - 1]
    return tuple(path[: min(t_k, end)])


def realised_tick_counts(cuts: Sequence[Sequence[int]], n_days: int) -> list[int]:
    counts: list[int] = []
    for cut in cuts:
        if n_days <= 0 or not cut:
            counts.append(0)
            continue
        counts.append(int(cut[min(n_days, len(cut)) - 1]))
    return counts


def count_summary(counts: Sequence[int]) -> dict[str, float]:
    if not counts:
        raise ValueError("N_e summary needs replicates")
    ordered = sorted(counts)
    size = len(ordered)
    if size % 2:
        median = float(ordered[size // 2])
    else:
        median = 0.5 * (ordered[size // 2 - 1] + ordered[size // 2])
    return {
        "min": float(ordered[0]),
        "p50": median,
        "mean": float(math.fsum(counts) / size),
        "max": float(ordered[-1]),
    }


def sqrt_boundary_rate(
    paths: Sequence[Sequence[float]],
    cuts: Sequence[Sequence[int]],
    *,
    n_days: int,
    t_k: int,
    c: float,
    t_min: int,
) -> float:
    """H0 crossing rate of the A1 √t boundary on the Stage 0 information set."""
    crits = np.empty(len(paths), dtype=float)
    for index, (path, cut) in enumerate(zip(paths, cuts, strict=True)):
        prefix = information_prefix(path, cut, n_days=n_days, t_k=t_k)
        crits[index] = critical_value(prefix, t_min=t_min)
    return crossing_rate(crits, c)


def day_moments(prep: PreparedDay, *, carry: float = 0.0) -> tuple[float, float, float] | None:
    """(Σ m z, Σ m z², Var(z)) via ``step_clock``, or None when the day does not tick.

    ``carry`` and the day's netting shift both enter z. The check before a
    simulation uses carry 0; the shift is the prepared day's own netting.
    """
    if not prep.day.legs or prep.variance <= VARIANCE_EPS:
        return None
    weights = [float(mass) for mass in prep.masses]
    if len(prep.xs) == len(weights) + 1:
        weights.append(max(0.0, 1.0 - float(math.fsum(weights))))
    shift = float(prep.day.netting)
    scored: list[tuple[float, float]] = []
    for outcome, weight in zip(prep.xs, weights, strict=False):
        if weight <= 0.0:
            continue
        step = step_clock(
            _normalised(prep.day.station, float(outcome), shift, prep.variance), carry
        )
        if not step.is_tick or step.z is None:
            return None
        scored.append((weight, step.z))
    if not scored:
        return None
    mean = math.fsum(weight * zed for weight, zed in scored)
    second = math.fsum(weight * zed * zed for weight, zed in scored)
    conditional = math.fsum(weight * (zed - mean) ** 2 for weight, zed in scored)
    return mean, second, conditional


def information_identity(days: Sequence[PreparedDay], *, carry: float = 0.0) -> InformationReport:
    """C-6. Does not abort. ``I_t`` is present only when the moment identity fails."""
    max_mean = 0.0
    max_second = 0.0
    max_gap = 0.0
    lowest = math.inf
    highest = -math.inf
    total = 0.0
    checked = 0
    for prep in days:
        moments = day_moments(prep, carry=carry)
        if moments is None:
            continue
        mean, second, conditional = moments
        checked += 1
        max_mean = max(max_mean, abs(mean))
        max_second = max(max_second, abs(second - 1.0))
        max_gap = max(max_gap, abs(conditional - 1.0))
        lowest = min(lowest, conditional)
        highest = max(highest, conditional)
        total += conditional
    holds = max_mean <= _TOL and max_second <= _TOL
    report: InformationReport = {
        "information_identity_holds": holds,
        "max_abs_mean_z": max_mean,
        "max_abs_second_moment_gap": max_second,
        "days_checked": checked,
    }
    if not holds:
        report["I_t"] = {
            "definition": (
                "I(t) = sum_k Var_H0(z_k | past). "
                "conditional_variance_sum adds that variance over prepared ticking days."
            ),
            "conditional_variance_min": lowest if checked else 0.0,
            "conditional_variance_max": highest if checked else 0.0,
            "conditional_variance_sum": total,
            "per_tick_equals_one": checked > 0 and max_gap <= _TOL,
        }
    return report


def conditional_variance_table(days: Sequence[PreparedDay]) -> dict[int, float]:
    table: dict[int, float] = {}
    for prep in days:
        moments = day_moments(prep)
        if moments is not None:
            table[id(prep)] = moments[2]
    return table


def _sum_lr(terms: Sequence[float]) -> float:
    total = 0.0
    saw_negative_inf = False
    for term in terms:
        if math.isinf(term) and term > 0.0:
            return math.inf
        if math.isinf(term) and term < 0.0:
            saw_negative_inf = True
            continue
        total += term
    if saw_negative_inf:
        return -math.inf
    return total


def log_lr_totals(
    draws: Sequence[Sequence[TickDraw]],
    cuts: Sequence[Sequence[int]],
    *,
    n_days: int,
    t_k: int,
    delta: float,
) -> list[float]:
    totals: list[float] = []
    for path, cut in zip(draws, cuts, strict=True):
        prefix = information_prefix(path, cut, n_days=n_days, t_k=t_k)
        terms = tuple(
            outcome_log_lr(item.prep, delta=delta, index=item.index, hs=item.hs) for item in prefix
        )
        totals.append(_sum_lr(terms))
    return totals


def mean_conditional_information(
    draws: Sequence[Sequence[TickDraw]],
    cuts: Sequence[Sequence[int]],
    *,
    n_days: int,
    t_k: int,
    variances: Mapping[int, float],
) -> float:
    """Mean over replicates of Σ Var(z_k | past) on the information prefix."""
    if not draws:
        raise ValueError("I(t) needs replicates")
    totals: list[float] = []
    for path, cut in zip(draws, cuts, strict=True):
        prefix = information_prefix(path, cut, n_days=n_days, t_k=t_k)
        totals.append(math.fsum(variances[id(item.prep)] for item in prefix))
    return float(math.fsum(totals) / len(totals))


def d1_decision(bound_min: Mapping[str, float], *, e_proj: str) -> tuple[str | None, str]:
    """PASS iff the latest epoch with bound_min ≥ 0.30 exists and is ≥ ``e_proj``."""
    passing = [epoch for epoch, bound in bound_min.items() if bound >= REACH]
    cutoff = max(passing) if passing else None
    status = "PASS" if cutoff is not None and cutoff >= e_proj else "FAIL"
    return cutoff, status


def json_float(value: float) -> float | str:
    if math.isnan(value):
        raise ValueError("NaN is not evidence")
    if math.isinf(value):
        return "+inf" if value > 0.0 else "-inf"
    return value
