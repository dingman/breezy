"""SL-6: pure quantile percentile -> rung probability (plan §2.2, §3.2 item 7,
§9 Q1; ruling A-4).

Pins the closed-enum ``CdfMethod`` (normal / PCHIP-with-normal-tails /
skew-normal), the EMOS location-scale transform, and
``rung_probabilities``'s interval-censored rung partition (§3.2 item 7).

Hand-computed values (NORMAL method, mean=50.0, sd=1.0) are derived here from
``math.erf`` directly, independent of
``breezy.strategy.ladder_ev.quantile_density``, per the standard normal CDF
identity Phi(z) = 0.5*(1+erf(z/sqrt(2))):

    Phi(-0.5)  = 0.30853753872598690
    Phi(1.5)   = 0.93319279873114191

Ladder: lt = (None, 49), i0 = (50, 51), gte = (52, None).

    P(lt)  = Phi((49.5-50)/1) - 0                = Phi(-0.5)          = 0.3085375387
    P(i0)  = Phi((51.5-50)/1) - Phi((49.5-50)/1)  = Phi(1.5)-Phi(-0.5) = 0.6246552600
    P(gte) = 1 - Phi((51.5-50)/1)                 = 1 - Phi(1.5)       = 0.0668072013

    Sum = 0.3085375387 + 0.6246552600 + 0.0668072013 = 1.0000000000
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from itertools import pairwise

import pytest
from scipy.optimize import least_squares as _legacy_least_squares
from scipy.stats import skewnorm as _legacy_skewnorm

from breezy.strategy.ladder_ev.density_table import RUNG_IDS
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    _skew_normal_cdf,
    apply_emos,
    build_cdf,
    rung_probabilities,
)

assert RUNG_IDS == ("lt", "i0", "i1", "i2", "i3", "gte")  # reused below (§9 Q1 reuse note)

_ALL_METHODS: tuple[CdfMethod, ...] = (
    CdfMethod.NORMAL,
    CdfMethod.PCHIP_NORMAL_TAILS,
    CdfMethod.SKEW_NORMAL,
)

#: A 6-rung complete partition using the venue's own rung-id alphabet
#: (RUNG_IDS): open-lower, four 2 F interiors, open-upper.
_SIX_RUNG_LADDER: tuple[Rung, ...] = (
    Rung(RUNG_IDS[0], None, 39),
    Rung(RUNG_IDS[1], 40, 41),
    Rung(RUNG_IDS[2], 42, 43),
    Rung(RUNG_IDS[3], 44, 45),
    Rung(RUNG_IDS[4], 46, 47),
    Rung(RUNG_IDS[5], 48, None),
)

_HAND_LADDER: tuple[Rung, ...] = (
    Rung("lt", None, 49),
    Rung("i0", 50, 51),
    Rung("gte", 52, None),
)

_TYPICAL_PERCENTILES = Percentiles(
    q10=50.0, q25=55.0, q50=60.0, q75=65.0, q90=70.0, mean=60.0, sd=8.0
)

_TIED_PERCENTILES = Percentiles(q10=50.0, q25=50.0, q50=50.0, q75=50.0, q90=50.0, mean=50.0, sd=0.3)

_HAND_PERCENTILES = Percentiles(q10=48.7, q25=49.3, q50=50.0, q75=50.7, q90=51.3, mean=50.0, sd=1.0)


def _phi(z: float) -> float:
    """Independent standard-normal CDF, never calling the module under test."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _assert_monotone(cdf: Callable[[float], float], xs: Sequence[float]) -> None:
    values = [cdf(x) for x in xs]
    for previous, current in pairwise(values):
        assert current >= previous - 1e-12, (previous, current)


# ---------------------------------------------------------------------------
# Partition sums to 1 (+/- 1e-12) for every method
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", _ALL_METHODS)
def test_partition_sums_to_one_within_1e_minus_12(method: CdfMethod) -> None:
    cdf = build_cdf(method, _TYPICAL_PERCENTILES)

    probabilities = rung_probabilities(cdf, _SIX_RUNG_LADDER)

    assert sum(probabilities.values()) == pytest.approx(1.0, abs=1e-12)
    assert set(probabilities) == set(RUNG_IDS)


# ---------------------------------------------------------------------------
# Monotone CDF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", _ALL_METHODS)
def test_cdf_is_monotone(method: CdfMethod) -> None:
    cdf = build_cdf(method, _TYPICAL_PERCENTILES)

    xs = [float(x) for x in range(121)]

    _assert_monotone(cdf, xs)


# ---------------------------------------------------------------------------
# NORMAL matches a hand-computed normal CDF value
# ---------------------------------------------------------------------------


def test_normal_method_matches_hand_computed_cdf_value() -> None:
    percentiles = Percentiles(q10=48.7, q25=49.3, q50=50.0, q75=50.7, q90=51.3, mean=50.0, sd=1.0)
    cdf = build_cdf(CdfMethod.NORMAL, percentiles)

    assert cdf(49.5) == pytest.approx(_phi(-0.5), abs=1e-12)
    assert cdf(51.5) == pytest.approx(_phi(1.5), abs=1e-12)


# ---------------------------------------------------------------------------
# Tied integer percentiles do not crash and stay monotone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", _ALL_METHODS)
def test_tied_percentiles_do_not_crash_and_stay_monotone(method: CdfMethod) -> None:
    cdf = build_cdf(method, _TIED_PERCENTILES)

    xs = [float(x) for x in range(30, 71)]

    _assert_monotone(cdf, xs)
    assert 0.0 <= cdf(50.0) <= 1.0


def test_pchip_falls_back_to_normal_when_every_knot_ties() -> None:
    """Documents the PCHIP fallback (Q1): when all 5 percentiles collapse to
    one x-knot, no monotone interpolant exists through a single point, so
    PCHIP_NORMAL_TAILS degrades to the plain NORMAL(mean, sd) CDF exactly."""
    normal_cdf = build_cdf(CdfMethod.NORMAL, _TIED_PERCENTILES)
    pchip_cdf = build_cdf(CdfMethod.PCHIP_NORMAL_TAILS, _TIED_PERCENTILES)

    for x in (40.0, 48.0, 50.0, 52.0, 60.0):
        assert pchip_cdf(x) == pytest.approx(normal_cdf(x), abs=1e-12)


def test_pchip_handles_a_partial_tie_and_stays_monotone_with_no_nan() -> None:
    """Q10 = Q25 < Q50 < Q75 = Q90 (review item 4): a tie at each end, but
    not a full collapse, so the interior interpolant still has 3 distinct
    knots and must NOT fall back to NORMAL."""
    percentiles = Percentiles(q10=48.0, q25=48.0, q50=55.0, q75=62.0, q90=62.0, mean=55.0, sd=6.0)
    cdf = build_cdf(CdfMethod.PCHIP_NORMAL_TAILS, percentiles)

    xs = [float(x) for x in range(20, 91)]
    values = [cdf(x) for x in xs]

    assert not any(math.isnan(value) for value in values)
    for previous, current in pairwise(values):
        assert current >= previous - 1e-12, (previous, current)
    assert values[0] == pytest.approx(0.0, abs=1e-6)
    assert values[-1] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Tails: F -> 0 at -inf, F -> 1 at +inf
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", _ALL_METHODS)
def test_tails_approach_zero_and_one(method: CdfMethod) -> None:
    cdf = build_cdf(method, _TYPICAL_PERCENTILES)

    assert cdf(-1_000.0) == pytest.approx(0.0, abs=1e-9)
    assert cdf(1_000.0) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# EMOS identity leaves the NORMAL method unchanged
# ---------------------------------------------------------------------------


def test_emos_identity_leaves_normal_method_unchanged() -> None:
    percentiles = _TYPICAL_PERCENTILES
    base_cdf = build_cdf(CdfMethod.NORMAL, percentiles)
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)

    emos_cdf = apply_emos(base_cdf, percentiles, identity)

    for x in (30.0, 45.0, 60.0, 75.0, 90.0):
        assert emos_cdf(x) == pytest.approx(base_cdf(x), abs=1e-9)


def test_emos_shift_moves_the_median() -> None:
    percentiles = _TYPICAL_PERCENTILES
    base_cdf = build_cdf(CdfMethod.NORMAL, percentiles)
    shifted = EmosParams(a=5.0, gamma=0.0, delta=1.0)

    emos_cdf = apply_emos(base_cdf, percentiles, shifted)

    # New median (F=0.5) sits at old median + a.
    assert emos_cdf(percentiles.q50 + 5.0) == pytest.approx(0.5, abs=1e-9)


def test_emos_delta_not_one_matches_hand_computed_cdf_value() -> None:
    """Review item 3: a delta != 1 test with a hand-computed target value,
    which pins the scale formula itself (the median-invariance check above
    holds regardless of delta, so it alone cannot catch a scale-formula
    bug).

    percentiles: mean=60, sd=8, q50=60. params: a=0, gamma=0, delta=0.5:

        log(s) = 0 + 0.5*log(8)         => s = sqrt(8) = 2.8284271247...
        ratio  = txn_sd / s = 8 / sqrt(8) = sqrt(8) = 2.8284271247...
        mu     = q50 + a = 60

    emos_cdf(61) = base_cdf(60 + (61-60)*sqrt(8)) = base_cdf(62.8284271247...)

        z = (62.8284271247 - 60) / 8 = sqrt(8)/8 = 0.3535533906
        Phi(z) = 0.5*(1 + erf(z/sqrt(2))) = 0.5*(1 + erf(0.25))
               = 0.5*(1 + 0.2763263902) = 0.6381631951
    """
    percentiles = Percentiles(q10=50.0, q25=55.0, q50=60.0, q75=65.0, q90=70.0, mean=60.0, sd=8.0)
    base_cdf = build_cdf(CdfMethod.NORMAL, percentiles)
    delta_half = EmosParams(a=0.0, gamma=0.0, delta=0.5)

    emos_cdf = apply_emos(base_cdf, percentiles, delta_half)

    assert emos_cdf(61.0) == pytest.approx(_phi(math.sqrt(8.0) / 8.0), abs=1e-9)
    assert emos_cdf(61.0) == pytest.approx(0.6381631951, abs=1e-9)


# ---------------------------------------------------------------------------
# Incomplete partition raises
# ---------------------------------------------------------------------------


def test_incomplete_partition_with_a_gap_raises() -> None:
    cdf = build_cdf(CdfMethod.NORMAL, _TYPICAL_PERCENTILES)
    gapped = (
        Rung("lt", None, 39),
        Rung("i0", 40, 41),
        # i1 missing: gap between 41 and 44
        Rung("i2", 44, 45),
        Rung("i3", 46, 47),
        Rung("gte", 48, None),
    )

    with pytest.raises(ValueError):
        rung_probabilities(cdf, gapped)


def test_partition_missing_an_open_lower_tail_raises() -> None:
    cdf = build_cdf(CdfMethod.NORMAL, _TYPICAL_PERCENTILES)
    not_open_lower = (
        Rung("i0", 40, 41),
        Rung("gte", 42, None),
    )

    with pytest.raises(ValueError):
        rung_probabilities(cdf, not_open_lower)


def test_partition_missing_an_open_upper_tail_raises() -> None:
    cdf = build_cdf(CdfMethod.NORMAL, _TYPICAL_PERCENTILES)
    not_open_upper = (
        Rung("lt", None, 39),
        Rung("i0", 40, 41),
    )

    with pytest.raises(ValueError):
        rung_probabilities(cdf, not_open_upper)


# ---------------------------------------------------------------------------
# Hand-computed rung-probability values (arithmetic in the module docstring)
# ---------------------------------------------------------------------------


def test_rung_probabilities_pin_hand_computed_values() -> None:
    cdf = build_cdf(CdfMethod.NORMAL, _HAND_PERCENTILES)

    probabilities = rung_probabilities(cdf, _HAND_LADDER)

    assert probabilities["lt"] == pytest.approx(_phi(-0.5), abs=1e-9)
    assert probabilities["i0"] == pytest.approx(_phi(1.5) - _phi(-0.5), abs=1e-9)
    assert probabilities["gte"] == pytest.approx(1.0 - _phi(1.5), abs=1e-9)
    assert sum(probabilities.values()) == pytest.approx(1.0, abs=1e-12)


# ---------------------------------------------------------------------------
# SKEW_NORMAL is interval-censored, not point least-squares (review item 1)
# ---------------------------------------------------------------------------


def _legacy_point_least_squares_skew_normal_cdf(
    percentiles: Percentiles,
) -> Callable[[float], float]:
    """The superseded point-least-squares fit (pre-review): each knot's
    residual is ``F(Q_i) - p_i`` exactly, with no ±0.5 slack. Kept ONLY in
    this test, to prove the interval-censored fix (production
    ``_skew_normal_cdf``) changes tail behaviour materially when a tie makes
    an exact point match impossible (Q10 == Q25 here can never satisfy both
    ``F(Q10) == 0.10`` and ``F(Q25) == 0.25`` at once, since they are the
    same input to one function)."""
    xs = (percentiles.q10, percentiles.q25, percentiles.q50, percentiles.q75, percentiles.q90)
    sd = percentiles.sd
    scale_guard = max(sd, 1e-6)

    def residuals(params: Sequence[float]) -> list[float]:
        shape, loc, log_scale = params
        scale = math.exp(log_scale)
        cdf_resid = [
            float(_legacy_skewnorm.cdf(x, shape, loc=loc, scale=scale)) - p
            for x, p in zip(xs, (0.10, 0.25, 0.50, 0.75, 0.90))
        ]
        model_mean, model_var = _legacy_skewnorm.stats(shape, loc=loc, scale=scale, moments="mv")
        mean_resid = (float(model_mean) - percentiles.mean) / scale_guard
        sd_resid = (math.sqrt(max(float(model_var), 0.0)) - sd) / scale_guard
        return [*cdf_resid, mean_resid, sd_resid]

    x0 = [0.0, percentiles.q50, math.log(scale_guard)]
    result = _legacy_least_squares(residuals, x0=x0, method="lm", max_nfev=2000)
    shape_fit, loc_fit = float(result.x[0]), float(result.x[1])
    scale_fit = math.exp(float(result.x[2]))

    def f(x: float) -> float:
        return float(_legacy_skewnorm.cdf(x, shape_fit, loc=loc_fit, scale=scale_fit))

    return f


#: Percentiles generated from a genuine normal(55, 8.6) (z10=-1.2816,
#: z25=-0.6745, z75=0.6745, z90=1.2816, rounded to the nearest integer °F):
#: fully self-consistent, so the fit should comfortably land each knot's
#: target probability inside that knot's ±0.5 CDF band with no tension
#: against the mean/SD anchors.
_WELL_BEHAVED_PERCENTILES = Percentiles(
    q10=44.0, q25=49.0, q50=55.0, q75=61.0, q90=66.0, mean=55.0, sd=8.6
)

#: Q10 == Q25 (tied): no continuous monotone CDF can satisfy both
#: F(48) == 0.10 and F(48) == 0.25 exactly, so a point-LS fit is always
#: forced away from at least one of them; a censored fit is free to trade
#: that knot's residual off against the rest of the shape instead, which
#: measurably moves the upper-tail probability (verified below).
_TIE_FORCING_PERCENTILES = Percentiles(
    q10=48.0, q25=48.0, q50=52.0, q75=56.0, q90=60.0, mean=52.0, sd=4.0
)

#: 2-rung ladder split just below Q90, where the tie-driven shape
#: difference shows up most.
_TIE_TAIL_LADDER: tuple[Rung, ...] = (
    Rung("lt", None, 58),
    Rung("gte", 59, None),
)


def test_skew_normal_censored_residual_is_zero_inside_the_band() -> None:
    """Direct assertion that the censored behaviour holds (review item 1):
    on a self-consistent percentile set, every knot's target probability
    p_i falls inside the fitted model's own CDF band
    [F(Q_i-0.5), F(Q_i+0.5)] -- i.e. a zero band-residual at every knot."""
    cdf = build_cdf(CdfMethod.SKEW_NORMAL, _WELL_BEHAVED_PERCENTILES)
    knots = (
        (_WELL_BEHAVED_PERCENTILES.q10, 0.10),
        (_WELL_BEHAVED_PERCENTILES.q25, 0.25),
        (_WELL_BEHAVED_PERCENTILES.q50, 0.50),
        (_WELL_BEHAVED_PERCENTILES.q75, 0.75),
        (_WELL_BEHAVED_PERCENTILES.q90, 0.90),
    )

    for q, p in knots:
        low = cdf(q - 0.5)
        high = cdf(q + 0.5)
        assert low <= p <= high, (q, p, low, high)


def test_skew_normal_censored_fit_diverges_materially_from_point_ls_on_a_tie() -> None:
    """Review item 1: a case (the Q10==Q25 tie above) where point-LS and
    censored-LS give materially different tail probabilities -- verified
    empirically at ~0.0145 (comfortably clears the 0.01 bar)."""
    censored_cdf = build_cdf(CdfMethod.SKEW_NORMAL, _TIE_FORCING_PERCENTILES)
    point_cdf = _legacy_point_least_squares_skew_normal_cdf(_TIE_FORCING_PERCENTILES)

    censored = rung_probabilities(censored_cdf, _TIE_TAIL_LADDER)
    point = rung_probabilities(point_cdf, _TIE_TAIL_LADDER)

    assert abs(censored["gte"] - point["gte"]) > 0.01, (censored, point)


# ---------------------------------------------------------------------------
# SKEW_NORMAL non-convergence falls back to NORMAL (review item 2)
# ---------------------------------------------------------------------------


def test_skew_normal_fit_exposes_fit_fell_back_false_on_convergence() -> None:
    cdf = build_cdf(CdfMethod.SKEW_NORMAL, _TYPICAL_PERCENTILES)

    assert getattr(cdf, "fit_fell_back", None) is False


#: Deliberately self-contradictory (percentiles wildly inconsistent with
#: mean/sd) so the LM solver cannot satisfy any termination tolerance
#: within 1 function evaluation -- verified empirically to produce
#: ``OptimizeResult.success is False`` at ``max_nfev=1``.
_NON_CONVERGENT_PERCENTILES = Percentiles(
    q10=0.0, q25=100.0, q50=200.0, q75=-50.0, q90=500.0, mean=-1000.0, sd=0.001
)


def test_skew_normal_non_convergence_falls_back_to_normal_and_flags_it() -> None:
    """Forces non-convergence with max_nfev=1 (review item 2) and asserts
    the fallback: the flag is set, and the values match plain NORMAL."""
    normal_cdf = build_cdf(CdfMethod.NORMAL, _NON_CONVERGENT_PERCENTILES)

    fallback_cdf = _skew_normal_cdf(_NON_CONVERGENT_PERCENTILES, max_nfev=1)

    assert getattr(fallback_cdf, "fit_fell_back", None) is True
    for x in (30.0, 45.0, 60.0, 75.0, 90.0):
        assert fallback_cdf(x) == pytest.approx(normal_cdf(x), abs=1e-12)


# ---------------------------------------------------------------------------
# Closed enum
# ---------------------------------------------------------------------------


def test_cdf_method_is_a_closed_enum_of_three() -> None:
    assert {member.name for member in CdfMethod} == {
        "NORMAL",
        "PCHIP_NORMAL_TAILS",
        "SKEW_NORMAL",
    }
