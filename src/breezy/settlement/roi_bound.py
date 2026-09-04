"""6e -- the BCa bootstrap lower bound on realized ROI.

`docs/plans/EXEC_SPINE_2026-09-01.md` Sec R-9 ("test 10") names this the
STOP-GATE quantity: the naive normal-approximation interval EXEC_SPINE
names is REFUSED because it is anticonservative exactly where the decision
is made. `docs/plans/SCORER_TALLY_BCA_BRIEF_
2026-09-04.md`, Converged peer review item 10, is the binding specification
this module implements.

Pure module -- no I/O, no Nautilus, and deliberately no import of the 6c
scorer (`settlement/trial_scorer.py`, built in parallel by a sibling): the
input here is a plain sequence of `(pnl, cost, excluded_reason)` rows, not a
`ScoredTrial`. A caller adapts its own record type into `ROIInputRow`.

Statistic. theta = (sum of pnl) / (sum of cost) across the NON-EXCLUDED
rows -- the ratio of sums, i.e. a single portfolio-level ROI, NOT the mean of
each row's own pnl/cost ratio. The two differ whenever `cost` varies across
rows (see `test_ratio_of_sums_differs_from_mean_of_returns` for a fixture
where they disagree). `exit_guard.compute_trade_returns` computes the
mean-of-returns diagnostic ledger; that is a different, complementary
number and is never substituted here.

Exclusion-fraction ceiling. `exit_guard.EXCLUSION_FRACTION_CEILING`
(`Decimal("0.20")`) is the ONE named constant for this check -- it is
imported, never restated. A sample whose excluded fraction exceeds the
ceiling is REFUSED outright: no bound is computed on the priced remainder,
because a mostly-excluded sample is not a sample the bootstrap should run on
silently (`exit_guard.py` module docstring).

Power floor. Fewer than 30 non-excluded rows is UNDERPOWERED: no bound is
computed.

Method. `scipy.stats.bootstrap` with `method="BCa"`, `paired=True` (pnl and
cost for a row are always resampled together -- they are not independent
samples), `n_resamples=10000`, and a seeded generator
(`numpy.random.default_rng(20260904)`) for exact reproducibility.

One-sided vs two-sided. `scipy.stats.bootstrap` does not directly expose a
one-sided BCa interval, and its own `alternative="less"/"greater"` support is
`percentile`-only, not `BCa`, in the scipy version this repo pins (1.18.1).
The standard equivalence used here instead: for a two-sided BCa interval at
confidence level `1 - alpha`, the LOWER endpoint is exactly the one-sided
lower bound at confidence level `1 - alpha/2`. Requesting a one-sided 95%
lower bound is therefore requesting a TWO-SIDED 90% interval
(`confidence_level=0.90`) and keeping only its low end -- the high end is
computed by scipy as a side effect and discarded. This is a standard
BCa-interval identity (Efron & Tibshirani, *An Introduction to the
Bootstrap*, ch. 14), not an approximation specific to this module.

The naive normal-approximation interval EXEC_SPINE refuses by name is
never printed or referenced anywhere in this module (pinned by
the source-text pin in `tests/unit/test_settlement_roi_bound.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import numpy as np
from numpy.typing import NDArray
from scipy.stats import bootstrap

from breezy.settlement.exit_guard import EXCLUSION_FRACTION_CEILING

__all__ = [
    "B_RESAMPLES",
    "MIN_NON_EXCLUDED_N",
    "SEED",
    "ROIBound",
    "ROIBoundRefused",
    "ROIBoundResult",
    "ROIBoundUnderpowered",
    "ROIInputRow",
    "compute_roi_bound",
    "format_roi_bound",
]

#: Number of bootstrap resamples, pinned by the spec (item 10).
B_RESAMPLES: Final[int] = 10_000

#: Seed for `numpy.random.default_rng`, pinned by the spec (item 10) for
#: exact reproducibility of the bound across runs.
SEED: Final[int] = 20260904

#: Below this many non-excluded rows the bootstrap is not run at all.
MIN_NON_EXCLUDED_N: Final[int] = 30

#: The two-sided confidence level whose LOWER endpoint is the one-sided 95%
#: lower bound (see module docstring, "One-sided vs two-sided").
_TWO_SIDED_CONFIDENCE_LEVEL: Final[float] = 0.90


@dataclass(frozen=True, slots=True, kw_only=True)
class ROIInputRow:
    """One trial's contribution to the ROI bootstrap sample.

    `excluded_reason` is `None` for a row counted toward the statistic;
    any non-`None` string marks it excluded (the reason itself is not
    interpreted here -- only its presence or absence).
    """

    pnl: Decimal
    cost: Decimal
    excluded_reason: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ROIBoundRefused:
    """The exclusion fraction exceeded the ceiling; no bound was computed."""

    exclusion_fraction: Decimal
    ceiling: Decimal = EXCLUSION_FRACTION_CEILING


@dataclass(frozen=True, slots=True, kw_only=True)
class ROIBoundUnderpowered:
    """Fewer than `MIN_NON_EXCLUDED_N` non-excluded rows; no bound computed."""

    n: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ROIBound:
    """The BCa 95% one-sided lower bound on realized ROI."""

    lower_bound: Decimal
    n: int
    b_resamples: int = B_RESAMPLES
    seed: int = SEED
    theta_hat: Decimal


ROIBoundResult = ROIBoundRefused | ROIBoundUnderpowered | ROIBound


def _ratio_of_sums(
    pnl: NDArray[np.float64], cost: NDArray[np.float64], axis: int = -1
) -> NDArray[np.float64]:
    """theta = sum(pnl) / sum(cost) along `axis` -- the ratio of sums, NOT
    the mean of each row's own pnl/cost ratio. Vectorized for
    `scipy.stats.bootstrap(vectorized=True)`."""
    return np.sum(pnl, axis=axis) / np.sum(cost, axis=axis)


def compute_roi_bound(rows: Sequence[ROIInputRow]) -> ROIBoundResult:
    """Compute the BCa 95% one-sided lower bound on realized ROI over `rows`.

    Returns `ROIBoundRefused` if the exclusion fraction exceeds
    `exit_guard.EXCLUSION_FRACTION_CEILING`, `ROIBoundUnderpowered` if fewer
    than `MIN_NON_EXCLUDED_N` non-excluded rows remain, else `ROIBound`.
    """
    total = len(rows)
    excluded_count = sum(1 for row in rows if row.excluded_reason is not None)
    exclusion_fraction = (
        Decimal(excluded_count) / Decimal(total) if total > 0 else Decimal(0)
    )
    if exclusion_fraction > EXCLUSION_FRACTION_CEILING:
        return ROIBoundRefused(exclusion_fraction=exclusion_fraction)

    included = [row for row in rows if row.excluded_reason is None]
    n = len(included)
    if n < MIN_NON_EXCLUDED_N:
        return ROIBoundUnderpowered(n=n)

    pnl_arr = np.array([float(row.pnl) for row in included], dtype=np.float64)
    cost_arr = np.array([float(row.cost) for row in included], dtype=np.float64)

    theta_hat = sum((row.pnl for row in included), start=Decimal(0)) / sum(
        (row.cost for row in included), start=Decimal(0)
    )

    result = bootstrap(
        (pnl_arr, cost_arr),
        _ratio_of_sums,
        paired=True,
        vectorized=True,
        n_resamples=B_RESAMPLES,
        random_state=np.random.default_rng(SEED),
        confidence_level=_TWO_SIDED_CONFIDENCE_LEVEL,
        method="BCa",
    )
    lower_bound = Decimal(str(result.confidence_interval.low))

    return ROIBound(lower_bound=lower_bound, n=n, theta_hat=theta_hat)


def format_roi_bound(result: ROIBoundResult) -> str:
    """Render `result` exactly per the spec (item 10) -- the ONLY place
    these three strings are produced, so a caller (6d) never hand-formats
    them differently."""
    if isinstance(result, ROIBoundRefused):
        return (
            f"BCa: REFUSED — exclusion fraction {result.exclusion_fraction:.3f} "
            f"exceeds ceiling {result.ceiling}"
        )
    if isinstance(result, ROIBoundUnderpowered):
        return "BCa: UNDERPOWERED (n<30)"
    return (
        f"BCa 95% lower bound on ROI: {result.lower_bound} "
        f"(n={result.n}, B={result.b_resamples}, seed={result.seed})"
    )
