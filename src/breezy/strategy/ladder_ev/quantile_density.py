"""Percentile forecast -> rung probability (plan §2.2, §3.2 item 7, §9 Q1).

PURE: no Nautilus import, no I/O. Stdlib ``math`` plus ``scipy`` (an existing
repo dependency -- ``pyproject.toml``) for the PCHIP interpolant and the
skew-normal fit. Fitting the EMOS coefficients themselves is out of scope
(plan §2.2: "There is no fitting here; fitting belongs to a later analysis
slice") -- this module only *applies* an already-fitted :class:`EmosParams`.

Three pre-declared ways to turn 5 percentiles (Q10/Q25/Q50/Q75/Q90) plus a
mean and an SD into a monotone CDF over degrees Fahrenheit (§9 Q1):

* :attr:`CdfMethod.NORMAL` -- ``normal(mean, sd)``, ignoring the percentiles.
* :attr:`CdfMethod.PCHIP_NORMAL_TAILS` -- a monotone PCHIP interpolant
  through the 5 percentile knots, with normal tails below Q10 and above Q90
  anchored so the CDF is continuous at both junctions.
* :attr:`CdfMethod.SKEW_NORMAL` -- a skew-normal fitted to the 5 percentiles
  plus the mean/SD by least squares (never reads S2's holdout; that choice
  is made once, on validation data, by the caller -- see plan §2.2).

``rung_probabilities`` turns any such CDF into per-rung probabilities over a
*complete* integer-°F partition (open-lower / interior / open-upper, §3.2
item 7), treating each integer label as latent in ``[x-0.5, x+0.5)``. This
module intentionally does NOT import
``breezy.strategy.ladder_ev.density_table`` -- its ``partition_check``
targets a ``Mapping[key, Mapping[rung_id, cell]]`` table at 1e-9, and its
fixed ``RUNG_IDS`` alphabet is the closed 6-rung venue identity, whereas this
module partitions ONE caller-supplied ladder (any width, any rung count) at
the tighter 1e-12 the plan requires. Callers that DO use the venue's 6-rung
ladder pass ``RUNG_IDS`` values for the rung ids; see
``tests/unit/test_ladder_ev_quantile_density.py``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

from scipy.interpolate import PchipInterpolator
from scipy.optimize import least_squares
from scipy.stats import skewnorm

__all__ = [
    "CdfMethod",
    "EmosParams",
    "Percentiles",
    "Rung",
    "apply_emos",
    "build_cdf",
    "rung_probabilities",
]

_SQRT2: float = math.sqrt(2.0)

#: Guard floor so ``log(sd)`` / division-by-sd never sees a literal 0.
_MIN_SD: float = 1e-6

#: The 5 pre-declared percentile probabilities (plan §9 Q1), in order.
_PERCENTILE_PROBS: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75, 0.90)


class CdfMethod(Enum):
    """Closed set of percentile -> CDF constructions (plan §9 Q1)."""

    NORMAL = "normal"
    PCHIP_NORMAL_TAILS = "pchip_normal_tails"
    SKEW_NORMAL = "skew_normal"


@dataclass(frozen=True, slots=True)
class Percentiles:
    """One day's NBP percentile bulletin row, plus its mean/SD (°F)."""

    q10: float
    q25: float
    q50: float
    q75: float
    q90: float
    mean: float
    sd: float


@dataclass(frozen=True, slots=True)
class EmosParams:
    """Already-fitted EMOS location-scale coefficients (plan §2.2).

    ``mu = q50 + a``; ``log(s) = gamma + delta * log(txn_sd)``. Fitting
    ``(a, gamma, delta)`` happens elsewhere (a later analysis slice); this
    module only applies them.
    """

    a: float
    gamma: float
    delta: float


@dataclass(frozen=True, slots=True)
class Rung:
    """One rung of an integer-°F ladder.

    ``lo``/``hi`` are inclusive integer bounds; ``None`` marks an open tail
    (at most one rung may have ``lo is None``, and at most one ``hi is
    None`` -- see :func:`rung_probabilities`).
    """

    rung_id: str
    lo: int | None
    hi: int | None


def _normal_cdf_fn(mean: float, sd: float) -> Callable[[float], float]:
    def f(x: float) -> float:
        return 0.5 * (1.0 + math.erf((x - mean) / (sd * _SQRT2)))

    return f


def _dedup_knots(xs: Sequence[float], ps: Sequence[float]) -> tuple[list[float], list[float]]:
    """Collapse consecutive tied x-knots, averaging their target probabilities.

    PCHIP requires strictly increasing x-knots. Integer NBP percentiles
    commonly tie when TXNSD < 2 F (plan §9 Q1). Ties are merged in
    encounter order: each new tie at an already-seen x averages its
    probability into the running value for that x. The merged sequence
    stays non-decreasing because the 5 source probabilities (0.10 .. 0.90)
    are themselves strictly increasing before any merge -- averaging a
    running value with the next (larger) probability can only move it up,
    never past the following distinct knot's own (larger still) value.
    """
    dedup_x: list[float] = []
    dedup_p: list[float] = []
    for x, p in zip(xs, ps):
        if dedup_x and x == dedup_x[-1]:
            dedup_p[-1] = (dedup_p[-1] + p) / 2.0
        else:
            dedup_x.append(x)
            dedup_p.append(p)
    return dedup_x, dedup_p


def _pchip_normal_tails_cdf(percentiles: Percentiles) -> Callable[[float], float]:
    xs = [percentiles.q10, percentiles.q25, percentiles.q50, percentiles.q75, percentiles.q90]
    normal_cdf = _normal_cdf_fn(percentiles.mean, percentiles.sd)
    dedup_x, dedup_p = _dedup_knots(xs, list(_PERCENTILE_PROBS))

    if len(dedup_x) < 2:
        # Fallback (documented, plan §9 Q1): every percentile collapsed to
        # one x-knot -- no monotone interpolant passes through a single
        # point, so PCHIP_NORMAL_TAILS degrades to the plain NORMAL(mean,
        # sd) CDF entirely.
        return normal_cdf

    interpolator = PchipInterpolator(dedup_x, dedup_p, extrapolate=False)
    lo_x, hi_x = dedup_x[0], dedup_x[-1]
    lo_p, hi_p = dedup_p[0], dedup_p[-1]
    norm_lo = normal_cdf(lo_x)
    norm_hi = normal_cdf(hi_x)

    def f(x: float) -> float:
        if x <= lo_x:
            if norm_lo <= 0.0:
                return 0.0
            return lo_p * (normal_cdf(x) / norm_lo)
        if x >= hi_x:
            denom = 1.0 - norm_hi
            if denom <= 0.0:
                return 1.0
            return 1.0 - (1.0 - hi_p) * ((1.0 - normal_cdf(x)) / denom)
        return float(interpolator(x))

    return f


def _skew_normal_cdf(percentiles: Percentiles) -> Callable[[float], float]:
    """Skew-normal fitted to the 5 percentiles plus mean/SD, by least squares.

    "Interval-censored" (plan §9 Q1): each integer percentile Q_i is treated
    as the (mean/SD-scaled) target ``F(Q_i) = p_i`` rather than as an exact
    point sample, matching the same ±0.5 latent-interval treatment used
    elsewhere for integer °F labels (plan §3.2 item 7) -- the residual for
    each knot is the CDF-probability gap, not a raw temperature gap.
    """
    xs = (percentiles.q10, percentiles.q25, percentiles.q50, percentiles.q75, percentiles.q90)
    sd = percentiles.sd
    scale_guard = max(sd, _MIN_SD)

    def residuals(params: Sequence[float]) -> list[float]:
        shape, loc, log_scale = params
        scale = math.exp(log_scale)
        cdf_resid = [
            float(skewnorm.cdf(x, shape, loc=loc, scale=scale)) - p
            for x, p in zip(xs, _PERCENTILE_PROBS)
        ]
        model_mean, model_var = skewnorm.stats(shape, loc=loc, scale=scale, moments="mv")
        mean_resid = (float(model_mean) - percentiles.mean) / scale_guard
        sd_resid = (math.sqrt(max(float(model_var), 0.0)) - sd) / scale_guard
        return [*cdf_resid, mean_resid, sd_resid]

    x0 = [0.0, percentiles.q50, math.log(scale_guard)]
    result = least_squares(residuals, x0=x0, method="lm", max_nfev=2000)
    shape_fit = float(result.x[0])
    loc_fit = float(result.x[1])
    scale_fit = math.exp(float(result.x[2]))

    def f(x: float) -> float:
        return float(skewnorm.cdf(x, shape_fit, loc=loc_fit, scale=scale_fit))

    return f


def build_cdf(method: CdfMethod, percentiles: Percentiles) -> Callable[[float], float]:
    """Build the monotone CDF for ``method`` (plan §9 Q1)."""
    if percentiles.sd <= 0.0:
        raise ValueError(f"sd must be positive, was {percentiles.sd!r}")
    if method is CdfMethod.NORMAL:
        return _normal_cdf_fn(percentiles.mean, percentiles.sd)
    if method is CdfMethod.PCHIP_NORMAL_TAILS:
        return _pchip_normal_tails_cdf(percentiles)
    if method is CdfMethod.SKEW_NORMAL:
        return _skew_normal_cdf(percentiles)
    raise AssertionError(f"unreachable: unhandled CdfMethod {method!r}")  # pragma: no cover


def apply_emos(
    base_cdf: Callable[[float], float],
    *,
    q50: float,
    txn_sd: float,
    params: EmosParams,
) -> Callable[[float], float]:
    """Apply the EMOS location-scale transform (plan §2.2) around ``q50``.

    ``mu = q50 + params.a``; ``s = exp(params.gamma + params.delta *
    log(txn_sd))``. The identity ``EmosParams(a=0, gamma=0, delta=1)``
    (with ``s == txn_sd``) leaves ``base_cdf`` unchanged: ``mu == q50`` and
    the location-scale ratio collapses to 1, regardless of what ``base_cdf``
    itself is.
    """
    if txn_sd <= 0.0:
        raise ValueError(f"txn_sd must be positive, was {txn_sd!r}")
    mu = q50 + params.a
    s = math.exp(params.gamma + params.delta * math.log(txn_sd))
    if s <= 0.0:
        raise ValueError(f"EMOS scale s must be positive, was {s!r}")
    ratio = txn_sd / s

    def emos_cdf(x: float) -> float:
        return base_cdf(q50 + (x - mu) * ratio)

    return emos_cdf


def _tail_sort_key(rung: Rung) -> float:
    return float("-inf") if rung.lo is None else float(rung.lo)


def _assert_complete_partition(rungs: Sequence[Rung]) -> None:
    """Assert ``rungs`` is a complete, contiguous, open-tailed partition.

    Restates, at rung-ladder granularity, the same "complete partition"
    property ``density_table.partition_check`` asserts at the probability
    level (see module docstring) -- exactly one open-lower rung, exactly
    one open-upper rung, and every interior boundary abuts its neighbour
    with no gap and no overlap.
    """
    if not rungs:
        raise ValueError("rungs must be non-empty")
    ordered = sorted(rungs, key=_tail_sort_key)
    if ordered[0].lo is not None:
        raise ValueError(
            f"incomplete partition: first rung {ordered[0].rung_id!r} "
            "is not open-lower (lo must be None)"
        )
    if ordered[-1].hi is not None:
        raise ValueError(
            f"incomplete partition: last rung {ordered[-1].rung_id!r} "
            "is not open-upper (hi must be None)"
        )
    for left, right in pairwise(ordered):
        if left.hi is None or right.lo is None or right.lo != left.hi + 1:
            raise ValueError(
                "incomplete partition: "
                f"{left.rung_id!r} (hi={left.hi!r}) does not abut "
                f"{right.rung_id!r} (lo={right.lo!r})"
            )


def rung_probabilities(cdf: Callable[[float], float], rungs: Sequence[Rung]) -> dict[str, float]:
    """``P(rung) = F(hi + 0.5) - F(lo - 0.5)`` over a complete partition.

    Integer °F labels are treated as latent in ``[x-0.5, x+0.5)`` (plan
    §3.2 item 7). Open tails use the literal ``0.0`` / ``1.0`` endpoints
    rather than evaluating ``cdf`` at a large sentinel, so the partition sum
    telescopes to 1 up to ordinary floating-point addition error (each
    shared interior boundary is the identical float, from the identical
    ``cdf`` call, on both sides) instead of accumulating far-tail
    floating-point noise. Asserts the sum is 1 within 1e-12.
    """
    _assert_complete_partition(rungs)
    probabilities: dict[str, float] = {}
    for rung in rungs:
        upper = 1.0 if rung.hi is None else cdf(float(rung.hi) + 0.5)
        lower = 0.0 if rung.lo is None else cdf(float(rung.lo) - 0.5)
        probabilities[rung.rung_id] = upper - lower
    total = sum(probabilities.values())
    if abs(total - 1.0) > 1e-12:
        raise ValueError(f"rung probabilities sum to {total!r}, not 1 within 1e-12")
    return probabilities
