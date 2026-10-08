"""Pure Neyman–Pearson pieces for the Stage 0 G3 bound.

``c`` is the smallest H0 replicate with ``P0(L > c) ≤ α``. The test is
randomized on that atom: ``γ = (α·n0 − #{L0 > c}) / #{L0 == c}``, clipped to
``[0, 1]``, and ``power = P1(L > c) + γ·P1(L == c)``. A positive infinite
ratio always rejects. The standard error is the multinomial delta-method SE
of that estimator, conditional on ``(c, γ)``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple, NotRequired, TypedDict

import numpy as np

from breezy.analysis.fq_loss_stop_core import VARIANCE_EPS, step_clock
from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay, TickDraw, _outcome_h
from scripts.analysis.fq_loss_floor_mc_rows import _normalised, h1_win_probability
from scripts.analysis.fq_loss_floor_mc_solve import critical_value, crossing_rate

__all__ = [
    "ALPHA_NOMINAL",
    "DELTA_H1",
    "E_PROJ",
    "IDENTITY_FIGURES",
    "POWER_SE_FORMULA",
    "REACH",
    "TIES_EXACT",
    "InformationReport",
    "NpPower",
    "bound_min_with_se",
    "conditional_variance_table",
    "count_summary",
    "d1_decision",
    "d1_point_decision",
    "discrete_critical_value",
    "identity_at_recorded_carries",
    "identity_evidence",
    "information_identity",
    "information_prefix",
    "json_float",
    "linear_s_threshold_power",
    "log_lr_totals",
    "mean_conditional_information",
    "np_bound_power",
    "np_power_report",
    "np_rejects",
    "outcome_log_lr",
    "realised_tick_counts",
    "sqrt_boundary_rate",
]

#: The phrase the evidence uses for the tie rule. Exact on the atom, not conservative.
TIES_EXACT: str = "randomized NP test; exact at the atom"

#: Conditional on the H0 pair (c, gamma). W = 1 on {L = +inf or L > c} and
#: gamma on a finite atom. Documented here so the JSON and the tests share one string.
POWER_SE_FORMULA: str = (
    "Conditional on the H0 pair (c, gamma), each H1 replicate has weight "
    "W = 1{L = +inf or L > c} + gamma·1{L finite and L = c}. "
    "power = mean(W). "
    "SE = sqrt((mean(W^2) - power^2) / n1). "
    "This is the multinomial delta-method SE of the randomized estimator. "
    "W is only 0, gamma, or 1, so the moments are the three class counts, "
    "not a running sum: a constant weight then has SE 0. "
    "When gamma is 0 or 1, W is Bernoulli and SE equals the binomial SE "
    "sqrt(p(1-p)/n1)."
)

#: C-6 moments are taken over every prepared day of M-pool, M-yes, and M-no.
IDENTITY_FIGURES: str = "The figures pool the preps of all three mixes."

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
    #: ``|Σ m z² − 1|``. Same quantity as ``max_abs_second_moment_gap``.
    max_abs_var_minus_1: float
    days_checked: int
    I_t: NotRequired[IVariance]


class NpPower(NamedTuple):
    """Randomized NP power at one α, with the H0 threshold it was calibrated on."""

    c: float
    gamma: float
    power: float
    se: float
    h0_tail: int


class _Threshold(NamedTuple):
    c: float
    gamma: float
    n_above: int
    n_equal: int


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


def _np_threshold(stats: Sequence[float], alpha: float) -> _Threshold:
    """Smallest H0 value ``c`` with ``#{L > c} / n ≤ α``, and the atom weight ``γ``.

    ``γ = clip((α·n − #{L > c}) / #{L == c}, 0, 1)``. At ``α = 1`` every outcome
    rejects, so ``c = −∞`` and ``γ = 1``. The integer tail uses the same
    ``floor(α·n + 1e-12)`` dust guard as the old order-statistic index, which
    keeps ``c`` on the same atom.
    """
    if not stats:
        raise ValueError("critical value needs replicates")
    if not 0.0 <= alpha <= 1.0 or not math.isfinite(alpha):
        raise ValueError(f"alpha must be in [0, 1], got {alpha!r}")
    if any(math.isnan(value) for value in stats):
        raise ValueError("critical value cannot be computed from NaN")
    n = len(stats)
    if alpha >= 1.0:
        n_equal = sum(1 for value in stats if math.isinf(value) and value < 0.0)
        return _Threshold(-math.inf, 1.0, n - n_equal, n_equal)
    ordered = sorted(stats)
    limit = math.floor(alpha * n + 1e-12)
    index = 0
    while index < n:
        value = ordered[index]
        end = index + 1
        while end < n and ordered[end] == value:
            end += 1
        n_above = n - end
        if n_above <= limit:
            n_equal = end - index
            raw = (alpha * n - n_above) / n_equal
            gamma = min(1.0, max(0.0, raw))
            return _Threshold(value, gamma, n_above, n_equal)
        index = end
    raise RuntimeError("H0 tail never falls to alpha")


def discrete_critical_value(stats: Sequence[float], alpha: float) -> float:
    """``c`` of the randomized NP test. +inf still rejects when this is +inf."""
    return _np_threshold(stats, alpha).c


def rejection_rate(stats: Sequence[float], crit: float) -> float:
    """Strict exceedance rate. The randomized power does not use this."""
    if not stats:
        raise ValueError("rejection rate needs replicates")
    hits = sum(np_rejects(stat, crit) for stat in stats)
    return hits / len(stats)


def _reject_weight(stat: float, threshold: _Threshold) -> float:
    """1 above ``c`` and on +inf, ``γ`` on the finite atom, 0 below ``c``."""
    if (math.isinf(stat) and stat > 0.0) or stat > threshold.c:
        return 1.0
    if stat == threshold.c:
        return threshold.gamma
    return 0.0


def np_power_report(h0_stats: Sequence[float], h1_stats: Sequence[float], alpha: float) -> NpPower:
    """Randomized NP power and its delta-method SE. See ``POWER_SE_FORMULA``.

    ``h0_tail`` is ``#{L0 > c}``. ``γ`` is estimated from the H0 replicates only,
    so the SE is conditional on ``(c, γ)`` and does not add a threshold term.
    """
    if not h1_stats:
        raise ValueError("power needs replicates")
    threshold = _np_threshold(h0_stats, alpha)
    # W is in {0, gamma, 1}. Class counts keep mean(W^2) - power^2 from
    # going negative: a naive sum of a constant weight does, past n1 ≈ 5e4.
    n_hi = 0
    n_atom = 0
    for stat in h1_stats:
        weight = _reject_weight(stat, threshold)
        if weight == 1.0:
            n_hi += 1
        elif weight != 0.0:
            n_atom += 1
    n1 = len(h1_stats)
    n_lo = n1 - n_hi - n_atom
    gamma = threshold.gamma
    if n_hi == n1:
        power, variance = 1.0, 0.0
    elif n_atom == n1:
        power, variance = gamma, 0.0
    elif n_lo == n1:
        power, variance = 0.0, 0.0
    else:
        power = (n_hi + gamma * n_atom) / n1
        second = (n_hi + gamma * gamma * n_atom) / n1
        variance = second - power * power
        if variance < 0.0 and variance > -1e-12:
            variance = 0.0
    return NpPower(
        c=threshold.c,
        gamma=threshold.gamma,
        power=power,
        se=math.sqrt(variance / n1),
        h0_tail=threshold.n_above,
    )


def np_bound_power(h0_stats: Sequence[float], h1_stats: Sequence[float], alpha: float) -> float:
    """H1 power of the randomized LR test calibrated on ``h0_stats``."""
    return np_power_report(h0_stats, h1_stats, alpha).power


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


def _moments_report(pairs: Sequence[tuple[PreparedDay, float]]) -> InformationReport:
    """Max ``|Σ m z|`` and ``|Σ m z² − 1|`` over ``(prep, incoming carry)`` pairs."""
    max_mean = 0.0
    max_second = 0.0
    max_gap = 0.0
    lowest = math.inf
    highest = -math.inf
    total = 0.0
    checked = 0
    for prep, carry in pairs:
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
        "max_abs_var_minus_1": max_second,
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


def information_identity(days: Sequence[PreparedDay], *, carry: float = 0.0) -> InformationReport:
    """C-6 at one incoming carry. Does not abort. ``I_t`` only when the identity fails."""
    return _moments_report(tuple((prep, carry) for prep in days))


def identity_at_recorded_carries(
    draws: Sequence[Sequence[TickDraw]],
) -> InformationReport:
    """C-6 at the incoming carry of each recorded tick.

    A repeated ``(prep, carry)`` pair is evaluated once. The moments are the
    H0 masses on that prep, not the drawn outcome.
    """
    seen: set[tuple[int, float]] = set()
    pairs: list[tuple[PreparedDay, float]] = []
    for path in draws:
        for item in path:
            key = (id(item.prep), item.carry)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((item.prep, item.carry))
    return _moments_report(pairs)


def identity_evidence(carry0: InformationReport, carried: InformationReport) -> dict[str, Any]:
    """Carried moments, plus the carry-0 figures. Either failure keeps ``I_t``.

    ``information_identity_holds`` is false when either check fails. The carried
    moments are what the simulation actually produced; carry 0 is the same
    preps with the carry stripped off.
    """
    holds = carry0["information_identity_holds"] and carried["information_identity_holds"]
    payload: dict[str, Any] = {
        "identity_figures": IDENTITY_FIGURES,
        "identity_carry_source": (
            "Incoming carries of the H0 and H1 ticks, pooled across the preps of all three mixes."
        ),
        "information_identity_holds": holds,
        "max_abs_mean_z": carried["max_abs_mean_z"],
        "max_abs_var_minus_1": carried["max_abs_var_minus_1"],
        "max_abs_mean_z_carry0": carry0["max_abs_mean_z"],
        "max_abs_var_minus_1_carry0": carry0["max_abs_var_minus_1"],
        "max_abs_second_moment_gap": carry0["max_abs_second_moment_gap"],
    }
    variance = carried.get("I_t")
    if variance is None:
        variance = carry0.get("I_t")
    if not holds and variance is not None:
        payload["I_t"] = variance
    return payload


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


def _cutoff(passing: Sequence[str], *, e_proj: str) -> tuple[str | None, str]:
    cutoff = max(passing) if passing else None
    status = "PASS" if cutoff is not None and cutoff >= e_proj else "FAIL"
    return cutoff, status


def d1_point_decision(bound_min: Mapping[str, float], *, e_proj: str) -> tuple[str | None, str]:
    """Decision without the SE term: latest epoch with ``bound_min ≥ 0.30``."""
    passing = [epoch for epoch, bound in bound_min.items() if bound >= REACH]
    return _cutoff(passing, e_proj=e_proj)


def d1_decision(
    bound_min: Mapping[str, float],
    *,
    e_proj: str,
    se: Mapping[str, float] | None = None,
) -> tuple[str | None, str]:
    """PASS iff ``np_reach_cutoff_e`` is not null and ≥ ``e_proj``.

    Reach at epoch ``e`` means ``bound_min(e) + 2·SE(e) ≥ 0.30``. ``SE`` is the
    standard error of the minimising cell. Omitted SE is zero, which is the
    point rule. The screen is a necessary condition, so a near-miss proceeds
    to A1b's own gate rather than being killed by replicate noise.
    """
    errors = {} if se is None else se
    passing: list[str] = []
    for epoch, bound in bound_min.items():
        error = float(errors.get(epoch, 0.0))
        if error < 0.0 or not math.isfinite(error):
            raise ValueError(f"SE for {epoch} must be finite and non-negative, got {error!r}")
        if bound + 2.0 * error >= REACH:
            passing.append(epoch)
    return _cutoff(passing, e_proj=e_proj)


def bound_min_with_se(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, float], dict[str, float]]:
    """Raw ``min np_bound_alpha_eff`` and the SE of the minimising cell.

    Ties take the larger SE. A quieter tied cell must not hide a near-miss.
    """
    bounds: dict[str, float] = {}
    errors: dict[str, float] = {}
    for row in rows:
        epoch = row["epoch"]
        if not isinstance(epoch, str):
            raise TypeError(f"epoch must be a string, got {epoch!r}")
        bound = _real(row["np_bound_alpha_eff"], "np_bound_alpha_eff")
        error = _real(row["np_bound_alpha_eff_se"], "np_bound_alpha_eff_se")
        if error < 0.0:
            raise ValueError(f"SE for {epoch} must be non-negative, got {error!r}")
        current = bounds.get(epoch)
        if current is None or bound < current:
            bounds[epoch] = bound
            errors[epoch] = error
        elif bound == current:
            errors[epoch] = max(errors[epoch], error)
    return bounds, errors


def _real(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a real number, got {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{label} must be finite, got {value!r}")
    return out


def json_float(value: float) -> float | str:
    if math.isnan(value):
        raise ValueError("NaN is not evidence")
    if math.isinf(value):
        return "+inf" if value > 0.0 else "-inf"
    return value
