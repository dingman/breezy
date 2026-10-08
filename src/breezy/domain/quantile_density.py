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
  plus the mean/SD by **interval-censored** least squares (plan §9 Q1(c),
  §3.2 item 7): each integer percentile Q_i contributes a ZERO residual
  whenever the model's own CDF band ``[F(Q_i-0.5), F(Q_i+0.5)]`` already
  contains the target probability p_i -- equivalently, whenever the model's
  p_i-quantile falls inside ``[Q_i-0.5, Q_i+0.5]`` -- and only the shortfall
  outside that band otherwise. Mean and SD are soft anchors (weighted
  residuals, never hard constraints). The fit is deterministic
  (Levenberg-Marquardt from a fixed initial guess, no randomness). If the
  solver does not converge (``OptimizeResult.success`` is False), the fit
  falls back to :attr:`CdfMethod.NORMAL`\\(mean, sd) and logs a warning;
  either way the returned callable exposes an inspectable
  ``fit_fell_back: bool`` attribute (never reads S2's holdout; the method
  choice itself is made once, on validation data, by the caller -- plan
  §2.2).

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

import logging
import math
import statistics
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
    "rung_probability_interval",
]

#: Logging only (never file/network I/O, never read back): observability for
#: the SKEW_NORMAL non-convergence fallback (review item 2). Does not affect
#: the module's determinism or purity -- the same inputs always produce the
#: same CDF regardless of whether a handler is configured.
# Hard-coded on purpose: the pre-move logger name is pinned by test_ladder_ev_domain_move.
_logger = logging.getLogger("breezy.strategy.ladder_ev.quantile_density")

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


@dataclass(frozen=True, slots=True)
class _FitFallbackAwareCdf:
    """Wraps a CDF callable with an inspectable convergence flag.

    ``fit_fell_back`` (review item 2) is False when the wrapped CDF is a
    converged least-squares fit, and True when the fit failed to converge
    and ``_inner`` is the :attr:`CdfMethod.NORMAL` fallback instead. Callers
    that care can check ``getattr(cdf, "fit_fell_back", False)``.
    """

    _inner: Callable[[float], float]
    fit_fell_back: bool

    def __call__(self, x: float) -> float:
        return self._inner(x)


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


def _skew_normal_cdf(percentiles: Percentiles, *, max_nfev: int = 2000) -> Callable[[float], float]:
    """Skew-normal fitted to the 5 percentiles plus mean/SD, by
    interval-censored least squares (plan §9 Q1(c), §3.2 item 7).

    Each integer percentile Q_i is latent in ``[Q_i-0.5, Q_i+0.5)`` (the
    same integer-rounding treatment as §3.2 item 7), so a fit landing
    ANYWHERE in that band is exactly as good as landing precisely on Q_i.
    The per-knot residual is therefore zero whenever the trial CDF already
    satisfies ``F(Q_i-0.5) <= p_i <= F(Q_i+0.5)`` -- equivalently, whenever
    the trial distribution's own p_i-quantile falls inside
    ``[Q_i-0.5, Q_i+0.5]`` (evaluating in CDF space avoids an extra
    ``ppf`` inversion per residual) -- and otherwise the shortfall to the
    nearer band edge. Mean and SD stay soft anchors (weighted residuals,
    never hard constraints). ``max_nfev`` is exposed for tests that need to
    force non-convergence; production callers use the default.

    Deterministic: Levenberg-Marquardt (``method="lm"``) from a fixed
    initial guess, no randomness. If the solver's own convergence check
    (``OptimizeResult.success``) is False, this logs a warning and falls
    back to :attr:`CdfMethod.NORMAL`\\(mean, sd) instead of returning a
    poorly-fit distribution silently (review item 2); either branch returns
    a :class:`_FitFallbackAwareCdf` so callers can inspect ``fit_fell_back``.
    """
    xs = (percentiles.q10, percentiles.q25, percentiles.q50, percentiles.q75, percentiles.q90)
    sd = percentiles.sd
    scale_guard = max(sd, _MIN_SD)

    def residuals(params: Sequence[float]) -> list[float]:
        shape, loc, log_scale = params
        scale = math.exp(log_scale)
        band_resid: list[float] = []
        for x, p in zip(xs, _PERCENTILE_PROBS):
            low = float(skewnorm.cdf(x - 0.5, shape, loc=loc, scale=scale))
            high = float(skewnorm.cdf(x + 0.5, shape, loc=loc, scale=scale))
            if p < low:
                band_resid.append(low - p)
            elif p > high:
                band_resid.append(p - high)
            else:
                band_resid.append(0.0)
        model_mean, model_var = skewnorm.stats(shape, loc=loc, scale=scale, moments="mv")
        mean_resid = (float(model_mean) - percentiles.mean) / scale_guard
        sd_resid = (math.sqrt(max(float(model_var), 0.0)) - sd) / scale_guard
        return [*band_resid, mean_resid, sd_resid]

    x0 = [0.0, percentiles.q50, math.log(scale_guard)]
    result = least_squares(residuals, x0=x0, method="lm", max_nfev=max_nfev)
    if not bool(result.success):
        _logger.warning(
            "SKEW_NORMAL interval-censored fit did not converge "
            "(max_nfev=%d, percentiles=%r) -- falling back to "
            "CdfMethod.NORMAL(mean=%r, sd=%r)",
            max_nfev,
            percentiles,
            percentiles.mean,
            percentiles.sd,
        )
        return _FitFallbackAwareCdf(
            _inner=_normal_cdf_fn(percentiles.mean, percentiles.sd),
            fit_fell_back=True,
        )

    shape_fit = float(result.x[0])
    loc_fit = float(result.x[1])
    scale_fit = math.exp(float(result.x[2]))

    def f(x: float) -> float:
        return float(skewnorm.cdf(x, shape_fit, loc=loc_fit, scale=scale_fit))

    return _FitFallbackAwareCdf(_inner=f, fit_fell_back=False)


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
    percentiles: Percentiles,
    params: EmosParams,
) -> Callable[[float], float]:
    """Apply the EMOS location-scale transform (plan §2.2) around Q50.

    ``percentiles`` MUST be the same :class:`Percentiles` used to build
    ``base_cdf`` via :func:`build_cdf` -- ``q50`` and ``sd`` are read
    directly off it rather than accepted as separate caller-supplied
    scalars (review item 3), so the EMOS transform can never be applied
    with a different SD than the one ``base_cdf`` was itself built from.

    ``mu = percentiles.q50 + params.a``; ``s = exp(params.gamma +
    params.delta * log(percentiles.sd))``. The identity ``EmosParams(a=0,
    gamma=0, delta=1)`` (``s == percentiles.sd``) leaves ``base_cdf``
    unchanged: ``mu == q50`` and the location-scale ratio collapses to 1,
    regardless of what ``base_cdf`` itself is.
    """
    txn_sd = percentiles.sd
    if txn_sd <= 0.0:
        raise ValueError(f"percentiles.sd must be positive, was {txn_sd!r}")
    q50 = percentiles.q50
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


def rung_probability_interval(
    percentiles: Percentiles,
    method: CdfMethod,
    draws: Sequence[EmosParams],
    rungs: Sequence[Rung],
    *,
    level: float = 0.95,
) -> dict[str, tuple[float, float, float]]:
    """Per-rung ``(p_point, p_lower, p_upper)`` from a set of bootstrap EMOS
    parameter draws (SL-8 review item 3).

    ``draws`` are produced elsewhere -- ``breezy.analysis.nbp_calibration``
    builds them via a seeded station-day cluster bootstrap of ``(a_v,
    gamma_v)`` per NBM version -- this module only EVALUATES rung
    probabilities under each draw and takes the percentile interval, the
    same "fitting happens elsewhere, this module only applies" boundary
    :func:`apply_emos` already keeps (module docstring). This is deliberate:
    ``breezy.analysis`` may reach DOWN into ``breezy.strategy``
    (`pyproject.toml` layers contract), but never the reverse, so the
    live-strategy-importable interval function has to live here, not there.

    ``p_point`` is the MEAN of the per-draw rung probabilities -- not a
    separately-fitted point estimate -- so it is deterministic given
    ``draws`` alone, and (by linearity: every draw's own rung probabilities
    already sum to 1, so their mean across rungs sums to 1 too) the returned
    ``p_point`` values sum to 1 exactly, which a per-rung MEDIAN would not
    guarantee. ``p_lower``/``p_upper`` are the ``level``-percentile interval
    of the same per-draw values (``level=0.95`` -> 2.5/97.5).

    Raises :class:`ValueError` for an empty ``draws`` or a ``level`` outside
    ``(0.0, 1.0)``.
    """
    if not draws:
        raise ValueError("rung_probability_interval needs at least one draw")
    if not (0.0 < level < 1.0):
        raise ValueError(f"level must be in (0.0, 1.0), was {level!r}")
    base_cdf = build_cdf(method, percentiles)
    per_rung_draws: dict[str, list[float]] = {rung.rung_id: [] for rung in rungs}
    for draw in draws:
        calibrated_cdf = apply_emos(base_cdf, percentiles, draw)
        for rung_id, probability in rung_probabilities(calibrated_cdf, rungs).items():
            per_rung_draws[rung_id].append(probability)
    alpha = 1.0 - level
    result: dict[str, tuple[float, float, float]] = {}
    for rung_id, values in per_rung_draws.items():
        ordered = sorted(values)
        lower = ordered[max(0, math.floor((alpha / 2.0) * len(ordered)))]
        upper = ordered[min(len(ordered) - 1, math.ceil((1.0 - alpha / 2.0) * len(ordered)) - 1)]
        point = statistics.fmean(values)
        result[rung_id] = (point, lower, upper)
    return result
