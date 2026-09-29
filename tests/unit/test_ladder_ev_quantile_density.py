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

from breezy.strategy.ladder_ev.density_table import RUNG_IDS
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
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

    emos_cdf = apply_emos(base_cdf, q50=percentiles.q50, txn_sd=percentiles.sd, params=identity)

    for x in (30.0, 45.0, 60.0, 75.0, 90.0):
        assert emos_cdf(x) == pytest.approx(base_cdf(x), abs=1e-9)


def test_emos_shift_moves_the_median() -> None:
    percentiles = _TYPICAL_PERCENTILES
    base_cdf = build_cdf(CdfMethod.NORMAL, percentiles)
    shifted = EmosParams(a=5.0, gamma=0.0, delta=1.0)

    emos_cdf = apply_emos(base_cdf, q50=percentiles.q50, txn_sd=percentiles.sd, params=shifted)

    # New median (F=0.5) sits at old median + a.
    assert emos_cdf(percentiles.q50 + 5.0) == pytest.approx(0.5, abs=1e-9)


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
# Closed enum
# ---------------------------------------------------------------------------


def test_cdf_method_is_a_closed_enum_of_three() -> None:
    assert {member.name for member in CdfMethod} == {
        "NORMAL",
        "PCHIP_NORMAL_TAILS",
        "SKEW_NORMAL",
    }
