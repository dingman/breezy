"""RED-first tests for 6e -- `settlement/roi_bound.py`.

`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md`, Converged peer review
item 10, is the binding spec. This module's input is a plain sequence of
`(pnl, cost, excluded_reason)` rows -- it deliberately does NOT import the
6c scorer (`settlement/trial_scorer.py`), which a sibling agent is building
in parallel.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import numpy as np
from scipy.stats import norm

from breezy.settlement import roi_bound
from breezy.settlement.exit_guard import EXCLUSION_FRACTION_CEILING
from breezy.settlement.roi_bound import (
    ROIBound,
    ROIBoundRefused,
    ROIBoundUnderpowered,
    ROIInputRow,
    compute_roi_bound,
    format_roi_bound,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _rows(n: int, *, excluded: int = 0) -> list[ROIInputRow]:
    """`n` non-excluded rows (alternating +1/-1 pnl, unit cost) followed by
    `excluded` rows carrying a reason -- deterministic, no randomness."""
    rows: list[ROIInputRow] = []
    for i in range(n):
        pnl = Decimal(1) if i % 3 else Decimal(-1)
        rows.append(ROIInputRow(pnl=pnl, cost=Decimal(1), excluded_reason=None))
    for _ in range(excluded):
        rows.append(
            ROIInputRow(pnl=Decimal(0), cost=Decimal(1), excluded_reason="divergence")
        )
    return rows


# ---------------------------------------------------------------------------
# Seed reproducibility
# ---------------------------------------------------------------------------


def test_seed_reproducibility_gives_exact_bound_on_a_fixture() -> None:
    rows = _rows(40)

    result = compute_roi_bound(rows)

    assert isinstance(result, ROIBound)
    assert result == ROIBound(
        lower_bound=Decimal("0.05"),
        n=40,
        theta_hat=Decimal("0.3"),
    )


def test_the_same_fixture_produces_the_same_bound_across_repeated_calls() -> None:
    rows = _rows(40)

    first = compute_roi_bound(rows)
    second = compute_roi_bound(rows)

    assert first == second


# ---------------------------------------------------------------------------
# Refusal above the exclusion-fraction ceiling
# ---------------------------------------------------------------------------


def test_refusal_above_exclusion_ceiling_computes_no_bound() -> None:
    # 21 excluded of 100 rows = 0.21 > EXCLUSION_FRACTION_CEILING (0.20).
    rows = _rows(79, excluded=21)

    result = compute_roi_bound(rows)

    assert result == ROIBoundRefused(
        exclusion_fraction=Decimal(21) / Decimal(100),
        ceiling=EXCLUSION_FRACTION_CEILING,
    )
    # No bound was computed on the priced remainder -- the refusal is a
    # distinct type from ROIBound, not a bound with a flag set.
    assert not isinstance(result, ROIBound)


def test_exactly_at_the_ceiling_is_not_refused() -> None:
    # 20 excluded of 100 = exactly 0.20 -- the ceiling itself is inclusive.
    rows = _rows(80, excluded=20)

    result = compute_roi_bound(rows)

    assert not isinstance(result, ROIBoundRefused)


# ---------------------------------------------------------------------------
# Power floor: n=29 underpowered, n=30 bound
# ---------------------------------------------------------------------------


def test_underpowered_at_twenty_nine_non_excluded_rows() -> None:
    result = compute_roi_bound(_rows(29))

    assert result == ROIBoundUnderpowered(n=29)


def test_a_bound_is_computed_at_thirty_non_excluded_rows() -> None:
    result = compute_roi_bound(_rows(30))

    assert isinstance(result, ROIBound)
    assert result.n == 30


# ---------------------------------------------------------------------------
# Ratio-of-sums vs mean-of-returns
# ---------------------------------------------------------------------------


def test_ratio_of_sums_differs_from_mean_of_returns_on_a_fixture_where_they_disagree() -> None:
    # 29 rows at pnl=cost=1 (per-row ratio 1.0 each); one huge-cost row that
    # dominates the DENOMINATOR of a ratio-of-sums but is just one more
    # term in a mean-of-per-row-ratios.
    rows = [ROIInputRow(pnl=Decimal(1), cost=Decimal(1), excluded_reason=None) for _ in range(29)]
    rows.append(
        ROIInputRow(pnl=Decimal(-1), cost=Decimal(1000000000), excluded_reason=None)
    )

    result = compute_roi_bound(rows)

    assert isinstance(result, ROIBound)
    mean_of_per_row_ratios = sum(
        (row.pnl / row.cost for row in rows), start=Decimal(0)
    ) / len(rows)
    # theta_hat (ratio of sums) is near zero; mean-of-returns is near 1.
    # They must not be conflated.
    assert abs(result.theta_hat - mean_of_per_row_ratios) > Decimal("0.5")
    assert result.theta_hat < Decimal("0.01")
    assert mean_of_per_row_ratios > Decimal("0.9")


# ---------------------------------------------------------------------------
# Differential test against a small, independent reference BCa
# implementation (dev-only -- pins the library call against hand-rolled
# math on a small fixture; NOT a substitute for scipy in production code).
# Tolerance: 0.15 absolute on the lower bound, justified by the small
# resample count (2,000 vs the module's 10,000) used here to keep the test
# fast -- BCa endpoints are noisy at 2,000 resamples.
# ---------------------------------------------------------------------------


def _reference_bca_lower(
    pnl: np.ndarray, cost: np.ndarray, alpha: float = 0.10, seed: int = 7
) -> float:
    rng = np.random.default_rng(seed)
    n = len(pnl)
    theta_hat = pnl.sum() / cost.sum()
    boot = np.array(
        [
            (pnl[idx].sum() / cost[idx].sum())
            for idx in (rng.integers(0, n, n) for _ in range(2000))
        ]
    )
    z0 = norm.ppf((boot < theta_hat).mean())
    jack = np.array(
        [np.delete(pnl, i).sum() / np.delete(cost, i).sum() for i in range(n)]
    )
    jack_mean = jack.mean()
    num = ((jack_mean - jack) ** 3).sum()
    den = 6.0 * (((jack_mean - jack) ** 2).sum() ** 1.5)
    accel = num / den if den != 0 else 0.0
    z_lo = norm.ppf(alpha / 2)
    p_lo = norm.cdf(z0 + (z0 + z_lo) / (1 - accel * (z0 + z_lo)))
    return float(np.percentile(boot, 100 * p_lo))


def test_differential_against_a_reference_bca_implementation_within_tolerance() -> None:
    rows = _rows(30)
    pnl = np.array([float(row.pnl) for row in rows])
    cost = np.array([float(row.cost) for row in rows])

    result = compute_roi_bound(rows)
    assert isinstance(result, ROIBound)

    reference_lower = _reference_bca_lower(pnl, cost)

    assert abs(float(result.lower_bound) - reference_lower) < 0.15


# ---------------------------------------------------------------------------
# format_roi_bound
# ---------------------------------------------------------------------------


def test_format_refused_matches_the_spec_string_exactly() -> None:
    result = ROIBoundRefused(
        exclusion_fraction=Decimal("0.21"), ceiling=EXCLUSION_FRACTION_CEILING
    )

    assert (
        format_roi_bound(result)
        == "BCa: REFUSED — exclusion fraction 0.210 exceeds ceiling 0.20"
    )


def test_format_underpowered_matches_the_spec_string_exactly() -> None:
    assert format_roi_bound(ROIBoundUnderpowered(n=29)) == "BCa: UNDERPOWERED (n<30)"


def test_format_bound_matches_the_spec_string_exactly() -> None:
    result = ROIBound(
        lower_bound=Decimal("0.05"), n=40, theta_hat=Decimal("0.3")
    )

    assert (
        format_roi_bound(result)
        == "BCa 95% lower bound on ROI: 0.05 (n=40, B=10000, seed=20260904)"
    )


def test_format_roi_bound_never_prints_wald_for_any_result_variant() -> None:
    variants: list[roi_bound.ROIBoundResult] = [
        ROIBoundRefused(exclusion_fraction=Decimal("0.5"), ceiling=EXCLUSION_FRACTION_CEILING),
        ROIBoundUnderpowered(n=0),
        ROIBound(lower_bound=Decimal(0), n=30, theta_hat=Decimal(0)),
    ]
    for variant in variants:
        assert "Wald" not in format_roi_bound(variant)


# ---------------------------------------------------------------------------
# The module source itself never mentions Wald
# ---------------------------------------------------------------------------


def test_the_module_source_never_mentions_wald() -> None:
    source_path = Path(inspect.getfile(roi_bound))
    source = source_path.read_text(encoding="utf-8")

    assert "Wald" not in source
