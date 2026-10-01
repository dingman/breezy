"""Independent pin of ``rung_probability_interval`` (gate-5 blind spot).

Both parity-harness legs call this one function, so a bug inside it cannot
show up as a live-vs-analysis diff. Expected ``(p_hat, p_lower, p_upper)``
are computed in this file from ``math.erf`` and the order-statistic index
in the function's own docstring (``level=0.95`` -> ``floor(0.025 n)`` /
``ceil(0.975 n) - 1``). No ``quantile_density`` helper is imported for
those expected values.

The function is ``breezy.strategy.ladder_ev.quantile_density.
rung_probability_interval`` (percentile index at lines 437-439). Plan §2
does not put an additive haircut on this interval: D2's location
correction is applied by the caller before the draws arrive, and
``p_hat`` / ``p_lower`` / ``p_upper`` are the mean and the percentile
order statistics of the per-draw rung probabilities.
"""

from __future__ import annotations

import math
import statistics

import pytest

from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    rung_probability_interval,
)

# n = 30: floor(0.025 * 30) = floor(0.75) = 0, while round(0.75) = 1.
# A nearest-index reading of "2.5%" would pick a different draw.
_N_DRAWS = 30
_LEVEL = 0.95

_PERCENTILES = Percentiles(
    q10=72.0, q25=76.0, q50=80.0, q75=84.0, q90=88.0, mean=80.2, sd=4.0,
)
_LADDER: tuple[Rung, ...] = (
    Rung(rung_id="open_low", lo=None, hi=74),
    Rung(rung_id="interior", lo=75, hi=84),
    Rung(rung_id="open_high", lo=85, hi=None),
)
_DRAWS: tuple[EmosParams, ...] = tuple(
    EmosParams(a=-1.5 + 0.1 * i, gamma=-0.04 + 0.002 * i, delta=0.85 + 0.01 * i)
    for i in range(_N_DRAWS)
)


def _phi(z: float) -> float:
    """Standard normal CDF via ``math.erf``, not a ``quantile_density`` helper."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _rung_probability(draw: EmosParams, rung: Rung) -> float:
    """``P(rung) = F(hi + 0.5) - F(lo - 0.5)`` under one EMOS draw.

    ``mu = q50 + a``, ``s = exp(gamma + delta * log(sd))``, and the base
    CDF is ``NORMAL(mean, sd)`` evaluated at the EMOS-warped boundary
    ``q50 + (x - mu) * sd / s``. Open tails use 0 and 1, not a sentinel.
    """
    sd = _PERCENTILES.sd
    mu = _PERCENTILES.q50 + draw.a
    scale = math.exp(draw.gamma + draw.delta * math.log(sd))
    ratio = sd / scale

    def cdf_at(x: float) -> float:
        warped = _PERCENTILES.q50 + (x - mu) * ratio
        return _phi((warped - _PERCENTILES.mean) / sd)

    upper = 1.0 if rung.hi is None else cdf_at(float(rung.hi) + 0.5)
    lower = 0.0 if rung.lo is None else cdf_at(float(rung.lo) - 0.5)
    return upper - lower


def _expected_interval(rung: Rung) -> tuple[float, float, float]:
    values = [_rung_probability(draw, rung) for draw in _DRAWS]
    ordered = sorted(values)
    alpha = 1.0 - _LEVEL
    n = len(ordered)
    lower_index = max(0, math.floor((alpha / 2.0) * n))
    upper_index = min(n - 1, math.ceil((1.0 - alpha / 2.0) * n) - 1)
    return statistics.fmean(values), ordered[lower_index], ordered[upper_index]


def test_percentile_index_rounding_is_observable_at_this_draw_count() -> None:
    """Pins that n=30 is a count where floor, not round, chooses p_lower."""
    alpha = 1.0 - _LEVEL
    fractional = (alpha / 2.0) * _N_DRAWS
    floor_index = math.floor(fractional)
    assert floor_index != round(fractional)

    ordered = sorted(_rung_probability(draw, _LADDER[2]) for draw in _DRAWS)
    assert ordered[floor_index] != ordered[round(fractional)]


@pytest.mark.parametrize("rung", _LADDER, ids=lambda rung: rung.rung_id)
def test_rung_probability_interval_matches_an_independent_erf_oracle(rung: Rung) -> None:
    actual = rung_probability_interval(
        _PERCENTILES, CdfMethod.NORMAL, _DRAWS, _LADDER, level=_LEVEL,
    )
    p_hat, p_lower, p_upper = _expected_interval(rung)

    assert actual[rung.rung_id][0] == pytest.approx(p_hat, abs=1e-12)
    assert actual[rung.rung_id][1] == pytest.approx(p_lower, abs=1e-12)
    assert actual[rung.rung_id][2] == pytest.approx(p_upper, abs=1e-12)
