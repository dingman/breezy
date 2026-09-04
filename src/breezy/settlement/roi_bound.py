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

One-sided. `scipy.stats.bootstrap` supports a direct one-sided BCa interval
via `alternative="greater"` together with `method="BCa"` in the scipy
version this repo pins (1.18.1) -- `alternative=` is NOT percentile-only.
Requesting the one-sided 95% lower bound is `confidence_level=0.95`,
`alternative="greater"`, `method="BCa"`; the returned `.low` is the bound and
`.high` is `inf` by construction and is discarded. This was previously
computed via a two-sided-90% equivalence trick, which produced the same
`.low` on the pinned fixture (0.05 either way) but relied on an incorrect
docstring claim that `alternative=` was percentile-only for this scipy
version -- corrected here.

Degeneracy. A sample with zero variance in the bootstrap statistic (e.g. all
wins, all losses, identical pnl rows) makes the BCa acceleration/bias
correction undefined; scipy raises `DegenerateDataWarning` and returns a NaN
lower bound. That warning is escalated to an error and caught, and the
returned bound is independently checked with `math.isfinite` before any
`Decimal` conversion, so degeneracy is caught even if scipy ever returns
finite garbage without warning. Either path returns `ROIBoundDegenerate`,
never a `ROIBound` wrapping `Decimal("NaN")`.

The naive normal-approximation interval EXEC_SPINE refuses by name is
never printed or referenced anywhere in this module (pinned by
the source-text pin in `tests/unit/test_settlement_roi_bound.py`).
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, assert_never

import numpy as np
from numpy.typing import NDArray
from scipy.stats import DegenerateDataWarning, bootstrap

from breezy.settlement.exit_guard import EXCLUSION_FRACTION_CEILING

__all__ = [
    "B_RESAMPLES",
    "MIN_NON_EXCLUDED_N",
    "SEED",
    "ROIBound",
    "ROIBoundDegenerate",
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

#: The one-sided confidence level for the lower bound (see module docstring,
#: "One-sided").
_CONFIDENCE_LEVEL: Final[float] = 0.95


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


@dataclass(frozen=True, slots=True, kw_only=True)
class ROIBoundDegenerate:
    """The BCa bootstrap could not produce a finite bound on this sample.

    Covers zero-variance samples (all wins, all losses, identical pnl rows
    -- scipy's `DegenerateDataWarning`), zero total cost over the
    non-excluded rows (division by zero), and non-finite or negative
    Decimal inputs. `reason` names which condition triggered it.
    """

    n: int
    reason: str


ROIBoundResult = ROIBoundRefused | ROIBoundUnderpowered | ROIBoundDegenerate | ROIBound


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

    for row in included:
        if not row.pnl.is_finite():
            return ROIBoundDegenerate(n=n, reason="non-finite pnl input")
        if not row.cost.is_finite():
            return ROIBoundDegenerate(n=n, reason="non-finite cost input")
        if row.cost < 0:
            return ROIBoundDegenerate(n=n, reason="negative cost input")

    total_pnl = sum((row.pnl for row in included), start=Decimal(0))
    total_cost = sum((row.cost for row in included), start=Decimal(0))
    if total_cost == 0:
        return ROIBoundDegenerate(n=n, reason="zero total cost")

    theta_hat = total_pnl / total_cost

    pnl_arr = np.array([float(row.pnl) for row in included], dtype=np.float64)
    cost_arr = np.array([float(row.cost) for row in included], dtype=np.float64)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DegenerateDataWarning)
            result = bootstrap(
                (pnl_arr, cost_arr),
                _ratio_of_sums,
                paired=True,
                vectorized=True,
                n_resamples=B_RESAMPLES,
                random_state=np.random.default_rng(SEED),
                confidence_level=_CONFIDENCE_LEVEL,
                alternative="greater",
                method="BCa",
            )
    except DegenerateDataWarning:
        return ROIBoundDegenerate(
            n=n, reason="degenerate bootstrap distribution (scipy DegenerateDataWarning)"
        )

    lower_bound_float = result.confidence_interval.low
    if not math.isfinite(lower_bound_float):
        return ROIBoundDegenerate(n=n, reason="non-finite BCa lower bound")

    lower_bound = Decimal(str(lower_bound_float))

    return ROIBound(lower_bound=lower_bound, n=n, theta_hat=theta_hat)


def format_roi_bound(result: ROIBoundResult) -> str:
    """Render `result` exactly per the spec (item 10) -- the ONLY place
    these four strings are produced, so a caller (6d) never hand-formats
    them differently."""
    match result:
        case ROIBoundRefused():
            return (
                f"BCa: REFUSED — exclusion fraction {result.exclusion_fraction:.3f} "
                f"exceeds ceiling {result.ceiling}"
            )
        case ROIBoundUnderpowered():
            return "BCa: UNDERPOWERED (n<30)"
        case ROIBoundDegenerate():
            return f"BCa: DEGENERATE — {result.reason} (n={result.n})"
        case ROIBound():
            return (
                f"BCa 95% lower bound on ROI: {result.lower_bound} "
                f"(n={result.n}, B={result.b_resamples}, seed={result.seed})"
            )
        case _:
            assert_never(result)
