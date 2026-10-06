"""AUT-4 WP2: relative calibration non-inferiority to the champion (r11 §3.10 R-C)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from breezy.analysis.autonomy import calibration_ni as ni
from breezy.analysis.stats import scoring_core
from breezy.persistence.autonomy import sample_size

_ALPHA = 0.0125
_MARGIN = 0.01


def _dates(n_rows: int, per_day: int = 4) -> list[dt.date]:
    return [dt.date(2026, 10, 2) + dt.timedelta(days=i // per_day) for i in range(n_rows)]


def _rows(
    n: int, *, bias: float, seed: int = 0
) -> tuple[list[tuple[float, bool]], list[tuple[float, bool]]]:
    """Champion is calibrated; the candidate's probabilities are shifted by `bias`."""
    rng = np.random.default_rng(seed)
    true_p = rng.uniform(0.02, 0.98, size=n)
    outcome = rng.uniform(size=n) < true_p
    champ = [(float(p), bool(y)) for p, y in zip(true_p, outcome, strict=True)]
    cand = [
        (float(min(1.0, max(0.0, p + bias))), bool(y)) for p, y in zip(true_p, outcome, strict=True)
    ]
    return cand, champ


def test_relative_calibration_one_sided_with_margin() -> None:
    _, champ = _rows(1500, bias=0.0)
    dates = _dates(1500)
    same = ni.relative_calibration_ni(champ, champ, dates, _ALPHA, _MARGIN, seed=1, b=2000)
    assert same.n_buckets_paired == 10
    assert same.ece_diff_ub == pytest.approx(0.0, abs=1e-12)  # identical models: dECE is 0
    assert (
        ni.evaluate_calibration_ni(champ, champ, dates, _ALPHA, _MARGIN, 3, 1, 2000).outcome
        == ni.OUTCOME_HOLDS
    )

    bad_cand, bad_champ = _rows(1500, bias=0.15, seed=4)
    worse = ni.evaluate_calibration_ni(bad_cand, bad_champ, dates, _ALPHA, _MARGIN, 3, 1, 2000)
    assert worse.outcome == ni.OUTCOME_FAILS
    assert worse.ece_diff_ub is not None and worse.ece_diff_ub >= _MARGIN

    better = ni.evaluate_calibration_ni(bad_champ, bad_cand, dates, _ALPHA, _MARGIN, 3, 1, 2000)
    assert better.outcome == ni.OUTCOME_HOLDS  # a better-calibrated candidate is non-inferior
    assert better.ece_diff_ub is not None and better.ece_diff_ub < 0.0


def test_upper_bound_is_one_sided_one_minus_alpha() -> None:
    cand, champ = _rows(1500, bias=0.05, seed=2)
    dates = _dates(1500)
    tight = ni.relative_calibration_ni(cand, champ, dates, 0.4, _MARGIN, seed=3, b=3000).ece_diff_ub
    loose = ni.relative_calibration_ni(
        cand, champ, dates, 0.001, _MARGIN, seed=3, b=3000
    ).ece_diff_ub
    assert loose > tight  # a smaller alpha is a higher upper quantile


def test_bootstrap_is_seed_reproducible() -> None:
    cand, champ = _rows(900, bias=0.03, seed=8)
    dates = _dates(900)
    a = ni.relative_calibration_ni(cand, champ, dates, _ALPHA, _MARGIN, seed=5, b=1500)
    b = ni.relative_calibration_ni(cand, champ, dates, _ALPHA, _MARGIN, seed=5, b=1500)
    assert a == b


def test_fewer_than_min_calibration_buckets_inconclusive() -> None:
    cand, champ = _rows(120, bias=0.0, seed=6)  # ~12 per bucket: no bucket reaches 30 events
    verdict = ni.evaluate_calibration_ni(cand, champ, _dates(120), _ALPHA, _MARGIN, 3, 1, 500)
    assert verdict.outcome == ni.OUTCOME_INCONCLUSIVE
    assert verdict.reason == "calibration_buckets_below_min"
    assert verdict.ece_diff_ub is None
    # Enough buckets overall, but fewer than the floor requires.
    cand2, champ2 = _rows(1500, bias=0.0, seed=7)
    verdict2 = ni.evaluate_calibration_ni(cand2, champ2, _dates(1500), _ALPHA, _MARGIN, 11, 1, 500)
    assert (verdict2.outcome, verdict2.reason) == (
        ni.OUTCOME_INCONCLUSIVE,
        ni.REASON_BUCKETS_BELOW_MIN,
    )


def test_a_bucket_is_paired_only_when_both_models_hold_30_events() -> None:
    n = 600
    champ = [(0.55, i % 2 == 0) for i in range(n)]
    cand = [
        (0.55 if i < 29 else 0.95, i % 2 == 0) for i in range(n)
    ]  # only 29 candidate events at 0.55
    stat = ni.relative_calibration_ni(cand, champ, _dates(n), _ALPHA, _MARGIN, seed=1, b=200)
    assert stat.n_buckets_paired == 0
    assert np.isnan(stat.ece_diff_ub)
    cand30 = [(0.55 if i < 30 else 0.95, i % 2 == 0) for i in range(n)]
    assert (
        ni.relative_calibration_ni(
            cand30, champ, _dates(n), _ALPHA, _MARGIN, seed=1, b=200
        ).n_buckets_paired
        == 1
    )


def test_bins_are_the_scoring_core_reliability_edges() -> None:
    assert ni._EDGES == (0.0, *scoring_core.RELIABILITY_BUCKET_EDGES, 1.0)


def test_n_min_c_enters_n_min_eff() -> None:
    """The (c) predicate's pinned n_min_c is inflated like (a) and (b), and can be binding."""
    deff = 1.5
    a = sample_size.n_min_eff(403, deff, sample_size.c_min(_ALPHA))
    b = sample_size.n_min_eff(120, deff, sample_size.c_min(_ALPHA / 3.0))
    c = sample_size.n_min_eff(900, deff, sample_size.c_min(_ALPHA))
    assert max(a, b, c) == c == 1350
    assert max(a, b, sample_size.n_min_eff(10, deff, sample_size.c_min(_ALPHA))) == a


def test_false_fail_rate_reported() -> None:
    _, champ = _rows(900, bias=0.0, seed=9)
    report = ni.false_fail_rate(champ, _dates(900), _ALPHA, _MARGIN, 3, seed=1, b=300, n_trials=8)
    assert report.n_trials == 8
    assert 0.0 <= report.rate <= 1.0
    assert report.n_failed == round(report.rate * 8)
    assert report.n_failed + report.n_below_min_buckets <= 8
    again = ni.false_fail_rate(champ, _dates(900), _ALPHA, _MARGIN, 3, seed=1, b=300, n_trials=8)
    assert report == again
    # A large perturbation makes the candidate worse than its own champion: the rate rises.
    noisy = ni.false_fail_rate(
        champ, _dates(900), _ALPHA, _MARGIN, 3, seed=1, b=300, n_trials=8, perturbation_sd=0.25
    )
    assert noisy.rate >= report.rate


@pytest.mark.parametrize(
    "kwargs",
    [{"alpha": 0.0}, {"alpha": 1.0}, {"margin": 0.0}, {"b": 0}],
)
def test_invalid_parameters_are_refused(kwargs: dict[str, float]) -> None:
    _, champ = _rows(300, bias=0.0)
    params: dict[str, float] = {"alpha": _ALPHA, "margin": _MARGIN, "b": 100}
    params.update(kwargs)
    with pytest.raises(ValueError):
        ni.relative_calibration_ni(
            champ, champ, _dates(300), params["alpha"], params["margin"], 1, int(params["b"])
        )


def test_unpaired_or_mismatched_inputs_are_refused() -> None:
    _, champ = _rows(100, bias=0.0)
    with pytest.raises(ValueError):
        ni.relative_calibration_ni(champ[:-1], champ, _dates(100), _ALPHA, _MARGIN, 1, 100)
    flipped = [(p, not y) for p, y in champ]
    with pytest.raises(ValueError):
        ni.relative_calibration_ni(flipped, champ, _dates(100), _ALPHA, _MARGIN, 1, 100)
    with pytest.raises(ValueError):
        ni.relative_calibration_ni([], [], [], _ALPHA, _MARGIN, 1, 100)
