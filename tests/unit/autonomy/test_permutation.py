"""AUT-4 WP2: the studentised date-cluster sign-flip test and its draw cap (r11 §3.2)."""

from __future__ import annotations

import datetime as dt
import itertools
import math

import numpy as np
import pytest

from breezy.analysis.autonomy import permutation
from breezy.persistence.autonomy import pins, sample_size

_ALPHA_1 = 0.025 / 2.0


def _days(n: int) -> list[dt.date]:
    return [dt.date(2026, 10, 2) + dt.timedelta(days=i) for i in range(n)]


def _effect(n_dates: int, shift: float, seed: int = 7) -> dict[dt.date, list[float]]:
    rng = np.random.default_rng(seed)
    return {d: [float(x) for x in rng.normal(shift, 1.0, size=3)] for d in _days(n_dates)}


def test_b_capped_and_tail_beyond_cap() -> None:
    assert permutation.draw_count(0.025) == 10_000
    assert permutation.draw_count(0.0125) == 16_000
    assert permutation.draw_count(1e-9) == pins.BOOTSTRAP_B_MAX  # capped, never above the pin
    # Beyond the cap the Monte-Carlo p cannot resolve alpha: the Hoeffding tail is used and flagged.
    result = permutation.date_cluster_signflip(_effect(30, 2.0), alpha=1e-4, seed=1)
    assert result.p_method == permutation.METHOD_HOEFFDING_TAIL
    assert result.defect_alert is True
    assert result.draws == 0
    assert 0.0 < result.p_value < 1.0


def test_hoeffding_tail_is_an_upper_bound_on_the_exact_p() -> None:
    effect = _effect(18, 1.0, seed=3)
    exact = permutation.date_cluster_signflip(effect, alpha=0.025, seed=1)
    sums = np.array([sum(v) for v in effect.values()])
    bound = math.exp(-(sums.sum() ** 2) / (2.0 * float(np.dot(sums, sums))))
    assert exact.p_method == permutation.METHOD_EXACT
    assert exact.p_value <= bound + 1e-12


def test_b_max_covers_k_lifetime_over_three() -> None:
    for k in range(1, pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME + 1):
        level = 0.025 * 2.0**-k / 3.0
        assert permutation.required_draws(level) <= pins.BOOTSTRAP_B_MAX
        assert permutation.draw_count(level) == permutation.required_draws(level)
    deepest = 0.025 * 2.0**-pins.MAX_NOMINATIONS_PER_LINEAGE_LIFETIME / 3.0
    assert permutation.required_draws(deepest) == 384_000


def test_exact_enumeration_matches_brute_force() -> None:
    effect = _effect(11, 0.8, seed=5)
    sums = np.array([sum(v) for _, v in sorted(effect.items())])
    observed = sums.sum()
    brute = sum(
        1
        for signs in itertools.product((1.0, -1.0), repeat=len(sums))
        if float(np.dot(signs, sums)) >= observed - 1e-9
    ) / 2 ** len(sums)
    result = permutation.date_cluster_signflip(effect, alpha=0.025, seed=1)
    assert result.p_method == permutation.METHOD_EXACT
    assert result.p_value == pytest.approx(brute, abs=1e-12)
    assert result.draws == 2**11


def test_monte_carlo_is_seed_reproducible_and_seed_sensitive() -> None:
    effect = _effect(40, 0.3)
    a = permutation.date_cluster_signflip(effect, alpha=0.025, seed=11, b=20_000)
    b = permutation.date_cluster_signflip(effect, alpha=0.025, seed=11, b=20_000)
    c = permutation.date_cluster_signflip(effect, alpha=0.025, seed=12, b=20_000)
    assert a == b
    assert a.p_method == permutation.METHOD_MONTE_CARLO
    assert a.p_value != c.p_value


def test_p_value_separates_signal_from_null() -> None:
    strong = permutation.date_cluster_signflip(_effect(40, 1.5), alpha=0.025, seed=2, b=20_000)
    null = permutation.date_cluster_signflip(
        _effect(40, 0.0, seed=99), alpha=0.025, seed=2, b=20_000
    )
    assert strong.p_value < 0.001
    assert null.p_value > 0.05


def test_one_sided_a_negative_effect_is_never_significant() -> None:
    result = permutation.date_cluster_signflip(_effect(40, -1.5), alpha=0.025, seed=2, b=20_000)
    assert result.p_value > 0.99


def test_chunking_does_not_change_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    effect = _effect(30, 0.5)
    whole = permutation.date_cluster_signflip(effect, alpha=0.025, seed=4, b=5_000)
    monkeypatch.setattr(permutation, "CHUNK_FLIPS", 777)
    chunked = permutation.date_cluster_signflip(effect, alpha=0.025, seed=4, b=5_000)
    # Different chunking consumes the generator differently, so exact equality is not promised;
    # both must be valid Monte-Carlo estimates of the same p.
    assert abs(whole.p_value - chunked.p_value) < 0.03


def test_dates_below_the_cluster_floor_raise() -> None:
    few = _effect(sample_size.c_min(0.025) - 1, 1.0)
    with pytest.raises(permutation.InsufficientClustersError) as caught:
        permutation.date_cluster_signflip(few, alpha=0.025, seed=1)
    assert caught.value.required == sample_size.c_min(0.025)


def test_all_zero_differences_are_degenerate_p_one() -> None:
    zeros = {d: [0.0, 0.0] for d in _days(25)}
    result = permutation.date_cluster_signflip(zeros, alpha=0.025, seed=1)
    assert (result.p_value, result.p_method) == (1.0, permutation.METHOD_DEGENERATE)


@pytest.mark.parametrize(
    "bad",
    [{dt.date(2026, 10, 2): []}, {dt.date(2026, 10, 2): [float("nan")]}],
)
def test_empty_or_non_finite_dates_are_refused(bad: dict[dt.date, list[float]]) -> None:
    padded = {**_effect(25, 0.0), **bad}
    with pytest.raises(ValueError):
        permutation.date_cluster_signflip(padded, alpha=0.025, seed=1)


def test_rows_within_a_date_are_summed_not_resampled() -> None:
    """Moving a difference between dates changes the result; reordering inside a date does not."""
    effect = _effect(30, 0.4)
    reordered = {d: list(reversed(v)) for d, v in effect.items()}
    a = permutation.date_cluster_signflip(effect, alpha=0.025, seed=3, b=4_000)
    b = permutation.date_cluster_signflip(reordered, alpha=0.025, seed=3, b=4_000)
    assert a.p_value == pytest.approx(b.p_value, abs=1e-12)
