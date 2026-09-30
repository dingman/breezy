"""RED-first tests for `breezy.analysis.brier_decomposition` (SL-7).

Plan: `docs/plans/FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`,
S2 statistics (:419-421) and build-slice row SL-7 (:473): "rel - res + unc
reconstructs Brier to 1e-12; six-rung unc = 5/36". Governing ruling:
`docs/evidence/RULING_forecast_edge_programme_closes_2026-09-20.md:36-38`,
which states `uncertainty = o(1-o) = (1/6)(5/6) = 5/36 = 0.138889` exactly,
identically for both systems. `unc = 5/36` holds ONLY because each of the
six rungs wins with EMPIRICAL frequency 1/6 in the scored corpus -- an
empirical property of that event set, not a consequence of "exactly one
rung wins per station-day" on its own. `murphy_decomposition` always
computes `obar` (and so `UNC`) from the supplied `outcomes`, never from an
assumed 1/6.

No Murphy implementation existed in the repo before this slice [VER: `grep
-rn "murphy" --include="*.py"` = 0 hits before this commit].
"""

from __future__ import annotations

import math
import random

import pytest

from breezy.analysis.brier_decomposition import (
    MurphyDecomposition,
    bin_by_edges,
    bin_by_value,
    murphy_decomposition,
    resolution_difference,
)

# ---------------------------------------------------------------------------
# 1. Exact reconstruction on random data, fixed seed.
# ---------------------------------------------------------------------------


def test_exact_reconstruction_holds_to_1e12_on_random_data() -> None:
    # Arrange: 500 events, each with a distinct random forecast probability
    # (bin_by_value puts every distinct value in its own bin, so within-bin
    # forecast variance and covariance are algebraically zero) and an
    # outcome drawn independently, so the ladder is not artificially tidy.
    rng = random.Random(20260929)
    probs = [rng.random() for _ in range(500)]
    outcomes = [rng.random() < 0.4 for _ in range(500)]

    # Act
    decomposition = murphy_decomposition(probs, outcomes, bin_by_value)

    # Assert: rel - res + unc reconstructs the directly-computed Brier.
    assert math.isclose(
        decomposition.reconstructed_brier, decomposition.brier, rel_tol=0.0, abs_tol=1e-12
    )
    # And the two correction terms are themselves ~0 in exact mode -- every
    # bin holds one distinct forecast value, so there is no within-bin
    # spread for either term to measure.
    assert math.isclose(decomposition.within_bin_forecast_variance, 0.0, abs_tol=1e-12)
    assert math.isclose(decomposition.within_bin_covariance, 0.0, abs_tol=1e-12)


def test_extended_identity_holds_to_1e12_with_coarse_bins() -> None:
    # Arrange: the SAME random corpus, but grouped into 5 coarse edge bins,
    # so individual forecasts differ from their bin mean and the two
    # correction terms are generally nonzero.
    rng = random.Random(20260929)
    probs = [rng.random() for _ in range(500)]
    outcomes = [rng.random() < 0.4 for _ in range(500)]
    coarse = bin_by_edges((0.0, 0.2, 0.4, 0.6, 0.8, 1.0))

    # Act
    decomposition = murphy_decomposition(probs, outcomes, coarse)

    # Assert: the EXTENDED identity (rel - res + unc + W - C) still
    # reconstructs Brier exactly, even though bins are coarse.
    assert math.isclose(
        decomposition.reconstructed_brier, decomposition.brier, rel_tol=0.0, abs_tol=1e-12
    )


# ---------------------------------------------------------------------------
# 2. Six-rung uniform climatology: unc = 5/36.
# ---------------------------------------------------------------------------


def test_six_rung_climatology_uncertainty_is_5_over_36() -> None:
    # Arrange: 6 station-days, each a 6-rung ladder with a uniform
    # climatology forecast (p = 1/6 for every rung) and exactly one rung
    # settling YES per day, exactly like a real partition ladder -- base
    # rate = 6 YES / 36 rungs = 1/6. This is an EMPIRICAL property of THIS
    # event set (each rung happens to win with frequency 1/6 across the 6
    # station-days), not a consequence of "exactly one rung wins per
    # station-day" alone -- a corpus where the rungs win with unequal
    # frequencies would measure a different obar and a different unc, even
    # though exactly one rung still settles per station-day.
    probs = [1.0 / 6.0] * 36
    outcomes = ([True, False, False, False, False, False]) * 6

    # Act
    decomposition = murphy_decomposition(probs, outcomes, bin_by_value)

    # Assert: unc = obar*(1-obar), and obar is MEASURED from `outcomes`
    # above (6/36 = 1/6 in this corpus), never assumed -- it equals
    # (1/6)(5/6) = 5/36 here exactly because this event set's measured
    # obar is 1/6, matching the 09-20 ruling
    # (`RULING_forecast_edge_programme_closes_2026-09-20.md:36-38`).
    assert math.isclose(decomposition.uncertainty, 5.0 / 36.0, rel_tol=0.0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# 3. Perfect forecast: REL = 0, RES = UNC.
# ---------------------------------------------------------------------------


def test_perfect_forecast_has_zero_reliability_and_resolution_equals_uncertainty() -> None:
    # Arrange: p_i == o_i exactly for every event -- the forecast IS the
    # outcome, so every bin (grouped by exact value) is either all-YES or
    # all-NO and predicts its own observed frequency exactly.
    outcomes = [False, False, True, True, False, True, True, False]
    probs = [1.0 if outcome else 0.0 for outcome in outcomes]

    # Act
    decomposition = murphy_decomposition(probs, outcomes, bin_by_value)

    # Assert
    assert math.isclose(decomposition.reliability, 0.0, abs_tol=1e-12)
    assert math.isclose(decomposition.resolution, decomposition.uncertainty, abs_tol=1e-12)
    # And the Brier of a perfect forecast is 0.
    assert math.isclose(decomposition.brier, 0.0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# 4. Climatological forecast: RES = 0.
# ---------------------------------------------------------------------------


def test_climatological_forecast_has_zero_resolution() -> None:
    # Arrange: every forecast equals the SAME constant (the overall base
    # rate), so bin_by_value puts every event in one single bin -- the bin
    # mean observed frequency trivially equals the overall base rate.
    outcomes = [True, False, False, True, True, False]
    base_rate = sum(outcomes) / len(outcomes)
    probs = [base_rate] * len(outcomes)

    # Act
    decomposition = murphy_decomposition(probs, outcomes, bin_by_value)

    # Assert
    assert math.isclose(decomposition.resolution, 0.0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# 5. resolution_difference is antisymmetric.
# ---------------------------------------------------------------------------


def test_resolution_difference_is_antisymmetric() -> None:
    # Arrange
    rng = random.Random(7)
    outcomes = [rng.random() < 0.35 for _ in range(200)]
    probs_a = [rng.random() for _ in range(200)]
    probs_b = [rng.random() for _ in range(200)]

    # Act
    bins = bin_by_edges(tuple(i / 10.0 for i in range(11)))
    d_ab = resolution_difference(probs_a, probs_b, outcomes, bins)
    d_ba = resolution_difference(probs_b, probs_a, outcomes, bins)

    # Assert
    assert math.isclose(d_ab, -d_ba, rel_tol=0.0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# 6. Mismatched input lengths raise.
# ---------------------------------------------------------------------------


def test_murphy_decomposition_raises_on_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="probs has"):
        murphy_decomposition([0.1, 0.2], [True], bin_by_value)


def test_murphy_decomposition_raises_on_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        murphy_decomposition([], [], bin_by_value)


def test_resolution_difference_raises_on_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="matched lengths"):
        resolution_difference([0.1, 0.2], [0.1], [True, False], bin_by_value)


def test_resolution_difference_refuses_exact_value_bins_for_cross_model_comparison() -> None:
    with pytest.raises(ValueError, match="refuses bin_by_value"):
        resolution_difference([0.1, 0.2], [0.2, 0.1], [True, False], bin_by_value)


# ---------------------------------------------------------------------------
# 7. Small hand-computed example (6 events), arithmetic in comments.
# ---------------------------------------------------------------------------


def test_hand_computed_six_event_example() -> None:
    # Arrange: 3 distinct forecast values, 2 events each (bin_by_value ->
    # exactly 3 bins, each with a CONSTANT forecast, so this stays exact
    # mode: within-bin forecast variance and covariance are both 0).
    #
    #   bin 0.2: p=[0.2, 0.2], o=[0, 1]  -> f=0.2, obar=0.5, n=2
    #   bin 0.6: p=[0.6, 0.6], o=[0, 1]  -> f=0.6, obar=0.5, n=2
    #   bin 0.8: p=[0.8, 0.8], o=[1, 1]  -> f=0.8, obar=1.0, n=2
    #
    #   overall obar = (0+1+0+1+1+1)/6 = 4/6 = 2/3
    #   UNC = (2/3)(1/3) = 2/9 = 0.222222...
    #
    #   REL = (1/6)[2*(0.2-0.5)^2 + 2*(0.6-0.5)^2 + 2*(0.8-1.0)^2]
    #       = (1/6)[2*0.09 + 2*0.01 + 2*0.04]
    #       = (1/6)(0.28) = 0.046666...
    #
    #   RES = (1/6)[2*(0.5-2/3)^2 + 2*(0.5-2/3)^2 + 2*(1.0-2/3)^2]
    #       = (1/6)[2*(1/36) + 2*(1/36) + 2*(1/9)]
    #       = (1/6)(12/36) = 1/18 = 0.055555...
    #
    #   Brier directly = (1/6)*[(0.2-0)^2 + (0.2-1)^2 + (0.6-0)^2 + (0.6-1)^2
    #                            + (0.8-1)^2 + (0.8-1)^2]
    #                  = (1/6)*[0.04 + 0.64 + 0.36 + 0.16 + 0.04 + 0.04]
    #                  = 1.28/6 = 0.213333...
    #
    #   Check: REL - RES + UNC = 0.046667 - 0.055556 + 0.222222 = 0.213333 (matches).
    probs = [0.2, 0.2, 0.6, 0.6, 0.8, 0.8]
    outcomes = [False, True, False, True, True, True]

    # Act
    decomposition = murphy_decomposition(probs, outcomes, bin_by_value)

    # Assert
    assert math.isclose(decomposition.uncertainty, 2.0 / 9.0, abs_tol=1e-9)
    assert math.isclose(decomposition.reliability, 0.28 / 6.0, abs_tol=1e-9)
    assert math.isclose(decomposition.resolution, 1.0 / 18.0, abs_tol=1e-9)
    assert math.isclose(decomposition.brier, 1.28 / 6.0, abs_tol=1e-9)
    assert math.isclose(decomposition.reconstructed_brier, decomposition.brier, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# bin_by_edges: coarse binning helper contract.
# ---------------------------------------------------------------------------


def test_bin_by_edges_groups_values_into_the_expected_bin() -> None:
    key = bin_by_edges((0.0, 0.5, 1.0))
    assert key(0.0) == key(0.25) == key(0.49)
    assert key(0.5) != key(0.25)
    assert key(0.5) == key(0.99) == key(1.0)


def test_bin_by_edges_rejects_fewer_than_two_edges() -> None:
    with pytest.raises(ValueError, match="at least two edges"):
        bin_by_edges((0.5,))


def test_bin_by_edges_rejects_nonascending_edges() -> None:
    with pytest.raises(ValueError, match="ascending"):
        bin_by_edges((0.5, 0.2, 1.0))


def test_bin_by_edges_raises_for_a_value_outside_the_edges() -> None:
    key = bin_by_edges((0.0, 0.5))
    with pytest.raises(ValueError, match="outside"):
        key(1.5)


def test_murphy_decomposition_returns_dataclass_instance() -> None:
    decomposition = murphy_decomposition([0.5, 0.5], [True, False], bin_by_value)
    assert isinstance(decomposition, MurphyDecomposition)
