"""NBP weather-only calibration + S2 gate machinery (SL-8; plan
`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` S2, S2.2, S4.1;
ruling `docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` S12 A-3/A-4).

Pure. No `nautilus_trader` import -- `breezy.analysis` is contract-barred
from importing it directly (`pyproject.toml`, "The offline analysis layer
never DIRECTLY imports Nautilus"). File I/O is limited to the holdout
marker and the artefact writer, both plain JSON on a caller-supplied
``Path`` -- no venue or Nautilus catalog access anywhere in this module.

**What this module is, and is not.** It is the S2 statistics layer: splits,
the holdout single-look marker, hierarchical EMOS shrinkage (ruling S12
A-4), and the four pre-declared gates G2.0-G2.3 plus contingency C-1. It is
NOT the raw NBP/CLI join (that is `scripts/analysis/nbp_skill_study.py`,
which reads real data and calls into this module), and it is NOT the
percentile-to-CDF machinery (that is
`breezy.strategy.ladder_ev.quantile_density`, which this module calls to
build the artefact's per-rung probability bounds).

**The holdout-leakage invariant, restated in code.** Every function whose
NAME contains "lovo" or "kappa" refuses outright if handed a row tagged
``split == "holdout"`` (:class:`PrimaryHoldoutLeakError`).
:func:`fit_hierarchical_emos` accepts a caller's full, unfiltered row set
(every split, holdout included) and FILTERS holdout rows out before calling
into that machinery -- so mutating a holdout-tagged row's values can never
change the kappa choice or the fitted (a_v, gamma_v) (the "poisoned
holdout" regression test pins this).

**CRPS is shape-agnostic (review item 2).** Every CRPS this module computes
against the ACTUAL chosen :class:`CdfMethod` (NORMAL, PCHIP_NORMAL_TAILS, or
SKEW_NORMAL, plus the EMOS location-scale transform) goes through
:func:`crps_numerical` -- deterministic numerical integration on a fixed
0.1 degF grid over ``[Q50-40, Q50+40]`` (midpoint rule). :func:`crps_normal`
(the closed-form Gneiting & Raftery formula) is kept ONLY as a test oracle
for the NORMAL case -- no fitting or gate-scoring code path calls it.

**Train-era versions (review item 4).** ``VersionRow.split == "train"`` rows
are fitted unshrunk on their OWN version's train rows (plan S3.2 item 5's
NBM version eras that predate the label gap -- v3.2/v4.0/v4.1/v4.2). They
participate in the LEAVE-ONE-OUT POOLED MEAN used to shrink the
validation/v5_fit_slice-era versions (v4.2's post-cutover tail, v4.3, v5.0),
but the LOVO kappa-selection CURVE itself -- the first-half-fit/
second-half-score CRPS loop that CHOOSES kappa -- still iterates only over
the versions present in validation + the v5.0 fit slice (ruling S12 A-4):
train rows are never a scored half.

**The degenerate-SE convention (review item 5).** G2.0/G2.0a/G2.1's
one-sample z-tests take their SE from a cluster bootstrap. When every
drawn resample produces an IDENTICAL statistic (SE == 0) -- e.g. a
one-cluster group, or every outcome in a bucket agreeing exactly -- a naive
``z = diff / 0`` is undefined. This module's convention: a zero-variance
bootstrap that still DISAGREES with the null (``observed != predicted``, or
``mean != 0``) is treated as p=0 (reject) -- the STRONGEST possible
evidence, not the weakest -- while a zero-variance bootstrap that agrees
exactly is p=1 (never reject a perfect match). Every gate result that can
hit this path carries a ``bootstrap_degenerate: bool`` field (``None`` on an
``UNTESTED`` group) so the S2 evidence note can tell a bootstrap-degeneracy
rejection apart from a substantive one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise
from pathlib import Path
from typing import Final, TypeVar

from scipy.optimize import minimize, minimize_scalar

from breezy.analysis.brier_decomposition import bin_by_value, resolution_difference
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
    rung_probability_interval,
)

__all__ = [
    "ARTEFACT_SCHEMA_VERSION",
    "BOOTSTRAP_ITERATIONS",
    "BOOTSTRAP_SEED",
    "CRPS_GRID_HALF_WIDTH_F",
    "CRPS_GRID_STEP_F",
    "DEFAULT_BOOTSTRAP_DRAWS",
    "DEFAULT_DELTA_BRACKET",
    "DEFAULT_DELTA_XATOL",
    "DEFAULT_SPLITS",
    "G20_MONTH_MIN_DATES",
    "G20_MONTH_N",
    "G21_MIN_BUCKET_N",
    "G22_TARGET_DIFFERENCE_X",
    "KAPPA_GRID",
    "N_MIN_CEILING",
    "NBM_VERSION_ERAS",
    "NEAR_MIDNIGHT_STRATA",
    "PMUS_INFEASIBLE_ROUTE_NODE4",
    "RELIABILITY_BUCKET_EDGES",
    "TAU_GRID",
    "C1Deviation",
    "C1Reevaluation",
    "CalibrationFit",
    "CorrectionForm",
    "DeltaFitDiagnostics",
    "G20GroupResult",
    "G20Result",
    "G20aResult",
    "G21BucketResult",
    "G21Result",
    "G23Result",
    "HierarchicalEmosResult",
    "HoldoutInsufficientNError",
    "HoldoutSingleLookError",
    "InvalidCorrectionFormError",
    "KappaScore",
    "KappaSelection",
    "MatchedEvent",
    "NMinResult",
    "NbpCalibrationArtefact",
    "PrimaryHoldoutLeakError",
    "RungEvent",
    "SkillGateResult",
    "SplitBounds",
    "SplitOrderError",
    "Splits",
    "StationDayResidual",
    "VersionEmosDraws",
    "VersionEstimate",
    "VersionRow",
    "apply_correction_form",
    "artefact_json",
    "artefact_sha256",
    "bootstrap_emos_draws",
    "cluster_bootstrap_draws",
    "compute_n_min",
    "crps_normal",
    "crps_numerical",
    "emos_params_from_draw_entry",
    "evaluate_g20",
    "evaluate_g20a",
    "evaluate_g21",
    "evaluate_g22",
    "evaluate_g23",
    "fit_calibration",
    "fit_hierarchical_emos",
    "fit_shared_delta",
    "fit_shared_delta_with_diagnostics",
    "fit_version_unshrunk",
    "holm_correction",
    "open_holdout",
    "parse_correction_form",
    "percentile_interval",
    "reevaluate_c1",
    "rung_bounds_from_calibration",
    "select_kappa_by_lovo_crps",
    "shrink_toward_lovo_pooled_mean",
    "tau_fraction_sensitivity",
    "write_artefact",
]

_logger = logging.getLogger(__name__)

_SQRT2: Final[float] = math.sqrt(2.0)
_SQRT_2PI: Final[float] = math.sqrt(2.0 * math.pi)
_INV_SQRT_PI: Final[float] = 1.0 / math.sqrt(math.pi)


def _std_normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


# ---------------------------------------------------------------------------
# Splits (plan S3.2 item 6; ruling S12 A-3/A-4)
# ---------------------------------------------------------------------------


class SplitOrderError(ValueError):
    """A split's bounds overlap the next split's, or a date falls in none."""


@dataclass(frozen=True, slots=True)
class SplitBounds:
    name: str
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise SplitOrderError(
                f"split {self.name!r} start {self.start} is after its own end {self.end}"
            )

    def contains(self, day: dt.date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True, slots=True)
class Splits:
    """Four time-ordered splits. ``holdout_start`` is open-ended -- the
    holdout "grows forward as labels accrue" (plan S3.2 item 6), so it
    carries no end date."""

    train: SplitBounds
    validate: SplitBounds
    v5_fit_slice: SplitBounds
    holdout_start: dt.date

    def __post_init__(self) -> None:
        ordered = (self.train, self.validate, self.v5_fit_slice)
        for earlier, later in pairwise(ordered):
            if earlier.end >= later.start:
                raise SplitOrderError(
                    f"split {earlier.name!r} ends {earlier.end} on or after "
                    f"split {later.name!r} starts {later.start}"
                )
        if self.v5_fit_slice.end >= self.holdout_start:
            raise SplitOrderError(
                f"v5_fit_slice ends {self.v5_fit_slice.end} on or after "
                f"the holdout starts {self.holdout_start}"
            )

    def split_for_date(self, day: dt.date) -> str:
        if self.train.contains(day):
            return "train"
        if self.validate.contains(day):
            return "validate"
        if self.v5_fit_slice.contains(day):
            return "v5_fit_slice"
        if day >= self.holdout_start:
            return "holdout"
        raise SplitOrderError(f"{day} falls in no declared split")


DEFAULT_SPLITS: Final[Splits] = Splits(
    train=SplitBounds("train", dt.date(2021, 1, 1), dt.date(2024, 12, 31)),
    validate=SplitBounds("validate", dt.date(2025, 1, 1), dt.date(2026, 5, 3)),
    v5_fit_slice=SplitBounds("v5_fit_slice", dt.date(2026, 5, 4), dt.date(2026, 6, 30)),
    holdout_start=dt.date(2026, 7, 1),
)


# ---------------------------------------------------------------------------
# n_min (ruling S12 A-3: a formula, not a number; ceiling 520)
# ---------------------------------------------------------------------------

#: norm.ppf(0.975) and norm.ppf(0.80) -- pinned literals. This module has no
#: other need of scipy.stats.norm, so these two constants are pinned rather
#: than adding that dependency for two lookups.
Z_ALPHA_TWO_SIDED_095: Final[float] = 1.9599639845400545
Z_POWER_080: Final[float] = 0.8416212335729143

#: The 09-20 resolution gap (plan S4.1; ruling ":45"), the pinned materiality
#: anchor for both the G2.2 power target and the G2.3 floor.
G22_TARGET_DIFFERENCE_X: Final[float] = 0.0152

#: Ruling S12 A-3: the final v5.0-holdout count reachable by ~2026-11-15.
N_MIN_CEILING: Final[int] = 520
PMUS_INFEASIBLE_ROUTE_NODE4: Final[str] = "PMUS_INFEASIBLE_ROUTE_NODE4"


@dataclass(frozen=True, slots=True)
class NMinResult:
    n_min: int
    sigma_d: float
    x: float
    feasible: bool
    status: str


def compute_n_min(sigma_d: float, *, x: float = G22_TARGET_DIFFERENCE_X) -> NMinResult:
    """``n_min = ceil(((z_0.975 + z_0.80) * sigma_d / x) ** 2)`` (ruling S12 A-3).

    ``sigma_d`` MUST be the validation-split estimate of the per-station-day
    mean paired Brier difference SD (ruling S12 A-3) -- this function takes
    it as given; measuring it from real rows is the caller's job.
    """
    if sigma_d <= 0.0:
        raise ValueError(f"sigma_d must be positive, was {sigma_d!r}")
    if x <= 0.0:
        raise ValueError(f"x must be positive, was {x!r}")
    raw = ((Z_ALPHA_TWO_SIDED_095 + Z_POWER_080) * sigma_d / x) ** 2
    n_min = math.ceil(raw)
    if n_min > N_MIN_CEILING:
        return NMinResult(
            n_min=n_min, sigma_d=sigma_d, x=x, feasible=False, status=PMUS_INFEASIBLE_ROUTE_NODE4
        )
    return NMinResult(n_min=n_min, sigma_d=sigma_d, x=x, feasible=True, status="OK")


# ---------------------------------------------------------------------------
# The holdout single-look marker (plan S3.2 item 6; S4.1 contingency C-1)
# ---------------------------------------------------------------------------


class HoldoutSingleLookError(RuntimeError):
    """The holdout marker already exists; only a C-1 deviation may reopen it."""


class HoldoutInsufficientNError(RuntimeError):
    """``final_station_day_count < n_min``; the holdout stays closed and no
    marker is written."""


@dataclass(frozen=True, slots=True)
class C1Deviation:
    """The documented protocol deviation contingency C-1 requires, co-signed
    by mle-reviewer (plan S4.1)."""

    declared_at: dt.date
    reason: str
    co_signed_by: str


def open_holdout(
    marker_path: Path,
    *,
    today: dt.date,
    final_station_day_count: int,
    n_min: int,
    c1_deviation: C1Deviation | None = None,
) -> Mapping[str, object]:
    """Open the v5.0 holdout exactly once, mirroring SINGLE_LOOK.

    First open: refuses (writing no marker) while
    ``final_station_day_count < n_min``. Otherwise writes the marker and
    returns its record.

    A second open (``marker_path`` already exists): refuses with
    :class:`HoldoutSingleLookError` unless ``c1_deviation`` is given, in
    which case it reopens -- the ONLY sanctioned exception (plan S3.2 item 6).
    """
    if marker_path.exists():
        if c1_deviation is None:
            raise HoldoutSingleLookError(
                f"{marker_path} already marks the holdout opened -- a second "
                "open needs a C-1 deviation record (plan S4.1 contingency C-1)"
            )
        record: dict[str, object] = {
            "reopened_at": today.isoformat(),
            "c1_deviation": {
                "declared_at": c1_deviation.declared_at.isoformat(),
                "reason": c1_deviation.reason,
                "co_signed_by": c1_deviation.co_signed_by,
            },
        }
        marker_path.write_text(json.dumps(record, sort_keys=True))
        return record
    if final_station_day_count < n_min:
        raise HoldoutInsufficientNError(
            f"final holdout count {final_station_day_count} < n_min {n_min} -- "
            "S2 waits; the wait is weather-only and costs no alpha (plan S3.2 "
            "item 6); no marker is written"
        )
    record = {
        "opened_at": today.isoformat(),
        "final_station_day_count": final_station_day_count,
        "n_min": n_min,
    }
    marker_path.write_text(json.dumps(record, sort_keys=True))
    return record


# ---------------------------------------------------------------------------
# Hierarchical EMOS: fit, CRPS, precision-weighted shrinkage, LOVO kappa
# (plan S2.2; ruling S12 A-4)
# ---------------------------------------------------------------------------


class PrimaryHoldoutLeakError(RuntimeError):
    """A holdout-tagged row reached kappa selection, parameter fitting, or a
    C-1 reevaluation input that must never see it."""


BOOTSTRAP_ITERATIONS: Final[int] = 2000
BOOTSTRAP_SEED: Final[int] = 20260929

_ClusterItemT = TypeVar("_ClusterItemT")


def _clusters(
    items: Sequence[_ClusterItemT], key_fn: Callable[[_ClusterItemT], object]
) -> list[list[_ClusterItemT]]:
    grouped: dict[object, list[_ClusterItemT]] = {}
    for item in items:
        grouped.setdefault(key_fn(item), []).append(item)
    return [grouped[key] for key in sorted(grouped, key=repr)]


#: NBM version eras (plan S3.2 item 5), for documentation/reference only --
#: this module never hardcodes which era a caller's ``VersionRow.version``
#: belongs to, only whether its ``split`` is ``"train"`` (review item 4).
NBM_VERSION_ERAS: Final[tuple[str, ...]] = ("v3.2", "v4.0", "v4.1", "v4.2", "v4.3", "v5.0")


@dataclass(frozen=True, slots=True)
class VersionRow:
    """One station-day's NBP percentile bulletin versus CLI truth, tagged to
    the NBM version whose bulletin produced it and to the split it falls in.
    ``split`` is one of ``"train"``, ``"validate"``, ``"v5_fit_slice"``, or
    ``"holdout"`` (see :meth:`Splits.split_for_date`).

    Carries the FULL ``Percentiles`` (not just ``q50``/``sd``) -- review item
    2 requires CRPS to be scored against the actual chosen
    :class:`CdfMethod` CDF (normal, PCHIP, or skew-normal), which needs every
    percentile, not a two-parameter summary.
    """

    version: str
    split: str
    station: str
    climate_day: dt.date
    percentiles: Percentiles
    cli_tmax_f: float


@dataclass(frozen=True, slots=True)
class VersionEstimate:
    version: str
    a: float
    gamma: float
    n: int
    #: SL-8b review item 2: ``scipy.optimize.OptimizeResult.success`` from the
    #: minimum-CRPS descent that produced ``(a, gamma)``. ``True`` for every
    #: caller that constructs a ``VersionEstimate`` by hand (tests, the
    #: shrinkage math) -- only :func:`fit_version_unshrunk` itself, and
    #: :func:`shrink_toward_lovo_pooled_mean` carrying its ``target``'s own
    #: value through, ever set this to ``False``.
    converged: bool = True
    #: ``OptimizeResult.nfev`` from that same descent -- 0 for a hand-built
    #: estimate.
    nfev: int = 0


def crps_normal(mu: float, sigma: float, observed: float) -> float:
    """Closed-form CRPS of ``N(mu, sigma)`` against one observation
    (Gneiting & Raftery 2007, eq. 5). Kept ONLY as a test oracle for the
    NORMAL method -- no fitting or gate-scoring code in this module calls
    it; use :func:`crps_numerical` for anything shape-agnostic (review item
    2)."""
    if sigma <= 0.0:
        raise ValueError(f"sigma must be positive, was {sigma!r}")
    z = (observed - mu) / sigma
    phi = math.exp(-0.5 * z * z) / _SQRT_2PI
    cdf = _std_normal_cdf(z)
    return sigma * (z * (2.0 * cdf - 1.0) + 2.0 * phi - _INV_SQRT_PI)


#: Review item 2: a fixed 0.1 degF grid, +/-40 degF around each row's own Q50.
CRPS_GRID_HALF_WIDTH_F: Final[float] = 40.0
CRPS_GRID_STEP_F: Final[float] = 0.1


def crps_numerical(
    cdf: Callable[[float], float],
    observed: float,
    *,
    center: float,
    half_width: float = CRPS_GRID_HALF_WIDTH_F,
    step: float = CRPS_GRID_STEP_F,
) -> float:
    """CRPS by deterministic numerical integration (review item 2):
    ``integral (F(x) - 1{x >= observed})^2 dx`` via the midpoint rule on a
    FIXED grid over ``[center-half_width, center+half_width]`` at ``step``
    increments. Works for ANY monotone CDF callable -- normal, PCHIP, or
    skew-normal (plus EMOS) -- unlike :func:`crps_normal`, which only
    applies to a normal distribution.
    """
    if half_width <= 0.0:
        raise ValueError(f"half_width must be positive, was {half_width!r}")
    if step <= 0.0:
        raise ValueError(f"step must be positive, was {step!r}")
    lo = center - half_width
    n_steps = max(1, round((2.0 * half_width) / step))
    total = 0.0
    for i in range(n_steps):
        x_mid = lo + (i + 0.5) * step
        indicator = 1.0 if x_mid >= observed else 0.0
        total += (cdf(x_mid) - indicator) ** 2 * step
    return total


#: Default Nelder-Mead iteration ceiling for :func:`fit_version_unshrunk`
#: (SL-8b review item 2). Callers force non-convergence for tests by
#: passing a small ``max_iterations`` (e.g. ``1``); production callers use
#: the default.
DEFAULT_VERSION_FIT_MAX_ITERATIONS: Final[int] = 200


def fit_version_unshrunk(
    rows: Sequence[VersionRow],
    *,
    method: CdfMethod,
    delta: float,
    max_iterations: int | None = None,
) -> VersionEstimate:
    """Minimum-CRPS point estimate of one version's ``(a_v, gamma_v)`` (plan
    S2.2; review item 1).

    Starts at the closed-form moment-matching solution -- ``a0 = mean(cli -
    q50)``; ``gamma0`` chosen so the mean squared STANDARDIZED residual
    (``residual / exp(gamma + delta * log(sd))``) equals 1 -- then REFINES
    it by minimising the TOTAL :func:`crps_numerical` of the calibrated
    ``method`` CDF (:func:`~breezy.strategy.ladder_ev.quantile_density
    .build_cdf` + :func:`~breezy.strategy.ladder_ev.quantile_density
    .apply_emos`) against every row's CLI outcome, via a deterministic
    Nelder-Mead descent (fixed start, fixed method, fixed tolerances -- no
    randomness) from that moment-matching start.

    **Convergence (SL-8b review item 2).** ``scipy.optimize.OptimizeResult
    .success`` and ``.nfev`` are inspected, never assumed: a non-converged
    descent is logged at WARNING and surfaced on the returned
    :class:`VersionEstimate` as ``converged=False`` -- the caller decides
    what to do with a non-converged fit, but it is never accepted silently.
    ``max_iterations`` overrides the Nelder-Mead ``maxiter`` option (default
    :data:`DEFAULT_VERSION_FIT_MAX_ITERATIONS`); pass a small value (e.g.
    ``1``) to force non-convergence deterministically in a test.
    """
    if not rows:
        raise ValueError("fit_version_unshrunk needs at least one row")
    versions = {row.version for row in rows}
    if len(versions) != 1:
        raise ValueError(f"rows must all share one version, got {sorted(versions)!r}")

    a0 = statistics.fmean(row.cli_tmax_f - row.percentiles.q50 for row in rows)
    ratios = [
        ((row.cli_tmax_f - (row.percentiles.q50 + a0)) ** 2) / (row.percentiles.sd ** (2.0 * delta))
        for row in rows
    ]
    gamma0 = 0.5 * math.log(max(statistics.fmean(ratios), 1e-12))

    # Each row's BASE cdf depends only on (method, percentiles) -- neither
    # changes during the (a, gamma) search -- so it is built ONCE per row,
    # not re-fit on every objective evaluation. For SKEW_NORMAL this avoids
    # re-running its internal least-squares fit hundreds of times per call.
    base_cdfs = [build_cdf(method, row.percentiles) for row in rows]

    def total_crps(params: Sequence[float]) -> float:
        a, gamma = params
        total = 0.0
        for row, base_cdf in zip(rows, base_cdfs, strict=True):
            calibrated_cdf = apply_emos(base_cdf, row.percentiles, EmosParams(a=a, gamma=gamma, delta=delta))
            total += crps_numerical(calibrated_cdf, row.cli_tmax_f, center=row.percentiles.q50)
        return total

    result = minimize(
        total_crps,
        x0=[a0, gamma0],
        method="Nelder-Mead",
        options={
            "xatol": 1e-4,
            "fatol": 1e-6,
            "maxiter": DEFAULT_VERSION_FIT_MAX_ITERATIONS if max_iterations is None else max_iterations,
        },
    )
    converged = bool(result.success)
    nfev = int(result.nfev)
    if not converged:
        _logger.warning(
            "fit_version_unshrunk did not converge for version %r (n=%d, nfev=%d): %s",
            rows[0].version,
            len(rows),
            nfev,
            getattr(result, "message", ""),
        )
    a_v, gamma_v = float(result.x[0]), float(result.x[1])
    return VersionEstimate(
        version=rows[0].version, a=a_v, gamma=gamma_v, n=len(rows), converged=converged, nfev=nfev
    )


#: Defaults shared by :func:`fit_shared_delta`/:func:`fit_shared_delta_with_diagnostics`
#: and :func:`fit_calibration` (SL-8b pipeline glue).
DEFAULT_DELTA_BRACKET: Final[tuple[float, float]] = (0.1, 3.0)
DEFAULT_DELTA_XATOL: Final[float] = 1e-3


@dataclass(frozen=True, slots=True)
class DeltaFitDiagnostics:
    """:func:`fit_shared_delta_with_diagnostics`'s full result (SL-8b review
    item 2) -- the bare delta plus the bounded scalar minimiser's own
    ``OptimizeResult.success``/``.nfev``."""

    delta: float
    converged: bool
    nfev: int


def fit_shared_delta_with_diagnostics(
    rows_by_version: Mapping[str, Sequence[VersionRow]],
    *,
    method: CdfMethod,
    bracket: tuple[float, float] = DEFAULT_DELTA_BRACKET,
    xatol: float = DEFAULT_DELTA_XATOL,
    max_iterations: int | None = None,
) -> DeltaFitDiagnostics:
    """:func:`fit_shared_delta`'s full result: the delta plus
    ``scipy.optimize.OptimizeResult.success``/``.nfev`` from the bounded
    scalar minimiser (SL-8b review item 2) -- inspected and logged, never
    silently accepted. ``max_iterations`` overrides the minimiser's own
    ``maxiter`` option; pass a small value (e.g. ``1``) to force
    non-convergence deterministically in a test.
    """
    if not rows_by_version:
        raise ValueError("fit_shared_delta needs at least one version's rows")

    def total_crps_at(delta: float) -> float:
        total = 0.0
        for rows in rows_by_version.values():
            estimate = fit_version_unshrunk(rows, method=method, delta=delta)
            for row in rows:
                calibrated_cdf = apply_emos(
                    build_cdf(method, row.percentiles),
                    row.percentiles,
                    EmosParams(a=estimate.a, gamma=estimate.gamma, delta=delta),
                )
                total += crps_numerical(calibrated_cdf, row.cli_tmax_f, center=row.percentiles.q50)
        return total

    options: dict[str, float | int] = {"xatol": xatol}
    if max_iterations is not None:
        options["maxiter"] = max_iterations
    result = minimize_scalar(total_crps_at, bounds=bracket, method="bounded", options=options)
    converged = bool(result.success)
    nfev = int(result.nfev)
    if not converged:
        _logger.warning(
            "fit_shared_delta did not converge (bracket=%r, nfev=%d): %s",
            bracket,
            nfev,
            getattr(result, "message", ""),
        )
    return DeltaFitDiagnostics(delta=float(result.x), converged=converged, nfev=nfev)


def fit_shared_delta(
    rows_by_version: Mapping[str, Sequence[VersionRow]],
    *,
    method: CdfMethod,
    bracket: tuple[float, float] = DEFAULT_DELTA_BRACKET,
    xatol: float = DEFAULT_DELTA_XATOL,
) -> float:
    """The shared delta, fitted by MINIMUM total CRPS across every version's
    own rows (plan S2.2: "fitted by minimum CRPS on train"; review item 1).

    For each candidate delta, every version in ``rows_by_version`` is refit
    unshrunk via :func:`fit_version_unshrunk`, and the CRPS is summed across
    ALL of every version's own rows; delta is chosen to minimise that total,
    via a deterministic bounded scalar minimiser (fixed bracket, fixed
    tolerance -- no randomness). Typically called with TRAIN rows (plan
    S2.2), but takes whatever ``rows_by_version`` the caller supplies.

    Thin wrapper over :func:`fit_shared_delta_with_diagnostics` that returns
    only the delta, preserving this function's original ``float`` return
    contract; convergence is still inspected and logged inside that call.
    """
    return fit_shared_delta_with_diagnostics(rows_by_version, method=method, bracket=bracket, xatol=xatol).delta


def shrink_toward_lovo_pooled_mean(
    target: VersionEstimate, others: Sequence[VersionEstimate], *, kappa: float
) -> VersionEstimate:
    """``theta_shrunk = w*theta_hat_v + (1-w)*theta_bar_{-v}``,
    ``w = n_v / (n_v + kappa)`` (ruling S12 A-4). ``theta_bar_{-v}`` is the
    n-weighted mean of every OTHER version's own unshrunk estimate.
    ``kappa == math.inf`` is full pooling (``w = 0``); ``kappa == 0`` is
    unshrunk (``w = 1``).
    """
    if not others:
        raise ValueError("shrink_toward_lovo_pooled_mean needs at least one other version")
    total_n = sum(other.n for other in others)
    if total_n <= 0:
        raise ValueError("the leave-one-out pool has zero total station-days")
    pooled_a = sum(other.a * other.n for other in others) / total_n
    pooled_gamma = sum(other.gamma * other.n for other in others) / total_n
    if kappa == math.inf:
        w = 0.0
    else:
        if kappa < 0.0:
            raise ValueError(f"kappa must be >= 0, was {kappa!r}")
        w = target.n / (target.n + kappa)
    return VersionEstimate(
        version=target.version,
        a=w * target.a + (1.0 - w) * pooled_a,
        gamma=w * target.gamma + (1.0 - w) * pooled_gamma,
        n=target.n,
        # Shrinkage does not refit -- it reweights `target`'s own already-fit
        # (a, gamma) against a pooled mean -- so the shrunk estimate's
        # convergence provenance is `target`'s own (SL-8b review item 2).
        converged=target.converged,
        nfev=target.nfev,
    )


#: Pinned grid (ruling S12 A-4).
KAPPA_GRID: Final[tuple[float, ...]] = (0.0, 30.0, 60.0, 120.0, 240.0, 480.0, 960.0, math.inf)
#: The old unweighted-fraction grid, reported as sensitivity only (ruling S12 A-4).
TAU_GRID: Final[tuple[float, ...]] = tuple(round(i * 0.1, 1) for i in range(11))


@dataclass(frozen=True, slots=True)
class KappaScore:
    kappa: float
    mean_crps: float


@dataclass(frozen=True, slots=True)
class KappaSelection:
    chosen_kappa: float
    #: The FULL curve, not just the argmin (ruling S12 recorded residual (ii)).
    curve: tuple[KappaScore, ...]


def _assert_no_holdout_rows(rows_by_version: Mapping[str, Sequence[VersionRow]]) -> None:
    for version, rows in rows_by_version.items():
        for row in rows:
            if row.split == "holdout":
                raise PrimaryHoldoutLeakError(
                    f"a holdout-tagged row for version {version!r} reached kappa/"
                    "parameter selection -- that machinery reads only validation "
                    "+ v5_fit_slice rows (plan S2.2)"
                )


def _select_by_lovo_crps(
    rows_by_version: Mapping[str, Sequence[VersionRow]],
    *,
    method: CdfMethod,
    delta: float,
    grid: Sequence[float],
    weight_fn: Callable[[int, float], float],
) -> KappaSelection:
    _assert_no_holdout_rows(rows_by_version)
    if len(rows_by_version) < 2:
        raise ValueError("LOVO selection needs at least two versions")
    unshrunk = {
        version: fit_version_unshrunk(rows, method=method, delta=delta)
        for version, rows in rows_by_version.items()
    }
    curve: list[KappaScore] = []
    for param in grid:
        per_version_crps: list[float] = []
        for version, rows in rows_by_version.items():
            ordered_rows = sorted(rows, key=lambda r: (r.climate_day, r.station))
            half = len(ordered_rows) // 2
            first_half, second_half = ordered_rows[:half], ordered_rows[half:]
            if not first_half or not second_half:
                continue
            others = [estimate for v, estimate in unshrunk.items() if v != version]
            total_n = sum(other.n for other in others)
            if total_n <= 0:
                continue
            pooled_a = sum(other.a * other.n for other in others) / total_n
            pooled_gamma = sum(other.gamma * other.n for other in others) / total_n
            first_half_estimate = fit_version_unshrunk(first_half, method=method, delta=delta)
            w = weight_fn(first_half_estimate.n, param)
            shrunk_a = w * first_half_estimate.a + (1.0 - w) * pooled_a
            shrunk_gamma = w * first_half_estimate.gamma + (1.0 - w) * pooled_gamma
            scores = [
                crps_numerical(
                    apply_emos(
                        build_cdf(method, row.percentiles),
                        row.percentiles,
                        EmosParams(a=shrunk_a, gamma=shrunk_gamma, delta=delta),
                    ),
                    row.cli_tmax_f,
                    center=row.percentiles.q50,
                )
                for row in second_half
            ]
            per_version_crps.append(statistics.fmean(scores))
        if per_version_crps:
            curve.append(KappaScore(kappa=param, mean_crps=statistics.fmean(per_version_crps)))
    if not curve:
        raise ValueError("no grid point produced a scoreable curve -- every version has < 2 rows")
    chosen = min(curve, key=lambda score: (score.mean_crps, score.kappa))
    return KappaSelection(chosen_kappa=chosen.kappa, curve=tuple(curve))


def select_kappa_by_lovo_crps(
    rows_by_version: Mapping[str, Sequence[VersionRow]],
    *,
    method: CdfMethod,
    delta: float,
    grid: Sequence[float] = KAPPA_GRID,
) -> KappaSelection:
    """LOVO first-half-fit / second-half-score CRPS kappa selection (plan
    S2.2; ruling S12 A-4). Scores CRPS against the ACTUAL ``method`` CDF
    (review item 2) via :func:`crps_numerical`. Refuses any holdout-tagged
    input row. ``rows_by_version`` must hold only the versions present in
    validation + the v5.0 fit slice (ruling S12 A-4) -- train-era versions
    never enter this scoring loop (review item 4); they still shape the
    pooled mean used here only insofar as :func:`fit_hierarchical_emos`
    seeds ``pooled_a``/``pooled_gamma`` -- see that function's docstring."""

    def weight_fn(n: int, kappa: float) -> float:
        if kappa == math.inf:
            return 0.0
        return n / (n + kappa)

    return _select_by_lovo_crps(rows_by_version, method=method, delta=delta, grid=grid, weight_fn=weight_fn)


def tau_fraction_sensitivity(
    rows_by_version: Mapping[str, Sequence[VersionRow]],
    *,
    method: CdfMethod,
    delta: float,
    grid: Sequence[float] = TAU_GRID,
) -> KappaSelection:
    """The old unweighted tau-fraction shrinkage, report-only (ruling S12 A-4)."""

    def weight_fn(_n: int, tau: float) -> float:
        return tau

    return _select_by_lovo_crps(rows_by_version, method=method, delta=delta, grid=grid, weight_fn=weight_fn)


#: Review item 3: B seeded station-day cluster-bootstrap draws per version.
DEFAULT_BOOTSTRAP_DRAWS: Final[int] = 200


@dataclass(frozen=True, slots=True)
class VersionEmosDraws:
    """One version's :class:`EmosParams` point estimate plus its bootstrap
    draws (review item 3)."""

    version: str
    point: EmosParams
    draws: tuple[EmosParams, ...]


def _bootstrap_version_emos_draws(
    rows: Sequence[VersionRow],
    *,
    method: CdfMethod,
    delta: float,
    seed: int,
    draws: int,
    resample_delta: bool = True,
    delta_bracket: tuple[float, float] = DEFAULT_DELTA_BRACKET,
    delta_xatol: float = DEFAULT_DELTA_XATOL,
) -> tuple[EmosParams, ...]:
    """``draws`` seeded station-day cluster-bootstrap refits of ``(a_v,
    gamma_v)`` for ONE version.

    **Delta resampling (SL-8b review item 3, supersedes the prior
    fixed-delta convention).** When ``resample_delta`` is ``True`` (the
    default), EACH draw's own delta is refit on that SAME resample via
    :func:`fit_shared_delta` restricted to this one version's drawn rows --
    so the returned :class:`EmosParams` carries a genuinely per-draw
    ``delta``, and the interval :func:`~breezy.strategy.ladder_ev
    .quantile_density.rung_probability_interval` derives from these draws
    reflects delta's own sampling uncertainty, not just ``(a_v,
    gamma_v)``'s. ``resample_delta=False`` reproduces the ORIGINAL SL-8
    behaviour -- every draw pinned to the single caller-supplied ``delta``
    -- kept for the direct fixed-vs-resampled interval-width comparison
    (``tests/unit/test_nbp_calibration.py``).
    """
    blocks = _clusters(rows, lambda row: (row.station, row.climate_day))
    if not blocks:
        raise ValueError("cannot bootstrap zero rows")
    rng = random.Random(seed)
    out: list[EmosParams] = []
    for _ in range(draws):
        drawn: list[VersionRow] = []
        for _ in range(len(blocks)):
            drawn.extend(blocks[rng.randrange(len(blocks))])
        draw_delta = delta
        if resample_delta:
            draw_delta = fit_shared_delta(
                {drawn[0].version: drawn}, method=method, bracket=delta_bracket, xatol=delta_xatol
            )
        estimate = fit_version_unshrunk(drawn, method=method, delta=draw_delta)
        out.append(EmosParams(a=estimate.a, gamma=estimate.gamma, delta=draw_delta))
    return tuple(out)


def bootstrap_emos_draws(
    rows_by_version: Mapping[str, Sequence[VersionRow]],
    shrunk_by_version: Mapping[str, VersionEstimate],
    *,
    method: CdfMethod,
    delta: float,
    seed: int = BOOTSTRAP_SEED,
    draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    resample_delta: bool = True,
    delta_bracket: tuple[float, float] = DEFAULT_DELTA_BRACKET,
    delta_xatol: float = DEFAULT_DELTA_XATOL,
) -> dict[str, VersionEmosDraws]:
    """``draws`` seeded station-day cluster-bootstrap draws of ``(a_v,
    gamma_v, delta)`` per version (review item 3), replacing the previous
    degenerate ``(p, p)`` artefact bound.

    A version with no rows of its own in ``rows_by_version`` (e.g. it has
    only train rows, already unshrunk and used purely as pooled-mean input)
    gets ``draws`` copies of its own point estimate -- there is no
    resampling population for it, so its interval collapses to the point,
    which is honest rather than fabricated spread. The POINT estimate
    always carries the caller-supplied shared ``delta`` regardless of
    ``resample_delta`` -- only the draws' own delta is resampled (SL-8b
    review item 3).
    """
    result: dict[str, VersionEmosDraws] = {}
    for index, (version, estimate) in enumerate(sorted(shrunk_by_version.items())):
        point = EmosParams(a=estimate.a, gamma=estimate.gamma, delta=delta)
        rows = rows_by_version.get(version)
        if not rows:
            result[version] = VersionEmosDraws(version=version, point=point, draws=(point,) * draws)
            continue
        version_draws = _bootstrap_version_emos_draws(
            rows,
            method=method,
            delta=delta,
            seed=seed + index,
            draws=draws,
            resample_delta=resample_delta,
            delta_bracket=delta_bracket,
            delta_xatol=delta_xatol,
        )
        result[version] = VersionEmosDraws(version=version, point=point, draws=version_draws)
    return result


@dataclass(frozen=True, slots=True)
class HierarchicalEmosResult:
    method: CdfMethod
    delta: float
    kappa_selection: KappaSelection
    tau_sensitivity: KappaSelection
    shrunk_by_version: Mapping[str, VersionEstimate]
    draws_by_version: Mapping[str, VersionEmosDraws]


def fit_hierarchical_emos(
    all_rows: Sequence[VersionRow],
    *,
    method: CdfMethod,
    delta: float,
    bootstrap_draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    resample_delta: bool = True,
    delta_bracket: tuple[float, float] = DEFAULT_DELTA_BRACKET,
    delta_xatol: float = DEFAULT_DELTA_XATOL,
) -> HierarchicalEmosResult:
    """Fit + precision-weight-shrink ``(a_v, gamma_v)`` for every version,
    train-era versions included (review item 4), plus their bootstrap draws
    (review item 3).

    ``all_rows`` may carry rows from EVERY split, holdout included -- rows
    tagged ``split == "holdout"`` are filtered out before anything
    downstream (kappa selection, every unshrunk fit, the pooled mean) ever
    sees them, so mutating a holdout-tagged row's values in ``all_rows``
    can never change this function's output.

    **Train-era versions (review item 4).** Rows tagged ``split ==
    "train"`` are grouped by version and fitted UNSHRUNK on their own train
    rows -- they have abundant data and need no shrinkage. Their fitted
    estimates are folded into the ``unshrunk`` pool alongside the
    validation/v5_fit_slice-era versions, so they PARTICIPATE in the
    leave-one-out pooled mean used to shrink those other versions. But
    :func:`select_kappa_by_lovo_crps`'s scoring loop -- which CHOOSES kappa
    -- receives only the validation/v5_fit_slice ``rows_by_version`` (ruling
    S12 A-4): train rows are never a scored half.
    """
    train_rows = [row for row in all_rows if row.split == "train"]
    fit_rows = [row for row in all_rows if row.split in ("validate", "v5_fit_slice")]
    if not fit_rows:
        raise ValueError("fit_hierarchical_emos needs at least one validate/v5_fit_slice row")

    train_by_version: dict[str, list[VersionRow]] = {}
    for row in train_rows:
        train_by_version.setdefault(row.version, []).append(row)

    rows_by_version: dict[str, list[VersionRow]] = {}
    for row in fit_rows:
        rows_by_version.setdefault(row.version, []).append(row)

    kappa_selection = select_kappa_by_lovo_crps(rows_by_version, method=method, delta=delta)
    tau_selection = tau_fraction_sensitivity(rows_by_version, method=method, delta=delta)

    unshrunk: dict[str, VersionEstimate] = {
        version: fit_version_unshrunk(rows, method=method, delta=delta)
        for version, rows in train_by_version.items()
    }
    unshrunk.update(
        {
            version: fit_version_unshrunk(rows, method=method, delta=delta)
            for version, rows in rows_by_version.items()
        }
    )

    shrunk: dict[str, VersionEstimate] = {}
    for version in train_by_version:
        # Train-era: abundant data, reported unshrunk (review item 4).
        shrunk[version] = unshrunk[version]
    for version in rows_by_version:
        others = [other for v, other in unshrunk.items() if v != version]
        shrunk[version] = shrink_toward_lovo_pooled_mean(
            unshrunk[version], others, kappa=kappa_selection.chosen_kappa
        )

    draws_by_version = bootstrap_emos_draws(
        rows_by_version,
        shrunk,
        method=method,
        delta=delta,
        seed=bootstrap_seed,
        draws=bootstrap_draws,
        resample_delta=resample_delta,
        delta_bracket=delta_bracket,
        delta_xatol=delta_xatol,
    )

    return HierarchicalEmosResult(
        method=method,
        delta=delta,
        kappa_selection=kappa_selection,
        tau_sensitivity=tau_selection,
        shrunk_by_version=shrunk,
        draws_by_version=draws_by_version,
    )


def _rows_by_version_for_splits(
    rows: Sequence[VersionRow], *, splits: tuple[str, ...]
) -> dict[str, list[VersionRow]]:
    grouped: dict[str, list[VersionRow]] = {}
    for row in rows:
        if row.split in splits:
            grouped.setdefault(row.version, []).append(row)
    return grouped


@dataclass(frozen=True, slots=True)
class CalibrationFit:
    """SL-8b pipeline glue: :func:`fit_shared_delta`'s output, wired straight
    into :func:`fit_hierarchical_emos` in ONE entry point (SL-8b review item
    1) -- the delta the per-version fits use (``hierarchical.delta``) always
    equals ``delta`` on THIS object.
    """

    delta: float
    delta_converged: bool
    delta_nfev: int
    hierarchical: HierarchicalEmosResult


def fit_calibration(
    all_rows: Sequence[VersionRow],
    *,
    method: CdfMethod,
    delta_bracket: tuple[float, float] = DEFAULT_DELTA_BRACKET,
    delta_xatol: float = DEFAULT_DELTA_XATOL,
    delta_max_iterations: int | None = None,
    bootstrap_draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    resample_delta: bool = True,
) -> CalibrationFit:
    """The single entry point: fit the shared delta, then fit + shrink every
    version's ``(a_v, gamma_v)`` against THAT delta (SL-8b review item 1).

    Delta is fitted on ``all_rows``' TRAIN rows when any are present (plan
    S2.2: "fitted by minimum CRPS on train"), grouped by version. When
    ``all_rows`` carries no train-split rows (e.g. a validate-only fixture),
    it falls back to the validate/v5_fit_slice rows -- the same fit-eligible
    rows :func:`fit_hierarchical_emos` itself uses -- so delta fitting never
    needs a caller to pre-split its input. Either way, holdout rows are
    NEVER used to fit delta, mirroring :func:`fit_hierarchical_emos`'s own
    holdout filter (module docstring).
    """
    delta_rows_by_version = _rows_by_version_for_splits(all_rows, splits=("train",))
    if not delta_rows_by_version:
        delta_rows_by_version = _rows_by_version_for_splits(
            all_rows, splits=("validate", "v5_fit_slice")
        )
    if not delta_rows_by_version:
        raise ValueError(
            "fit_calibration needs at least one train, validate, or v5_fit_slice row to fit delta"
        )
    delta_diagnostics = fit_shared_delta_with_diagnostics(
        delta_rows_by_version,
        method=method,
        bracket=delta_bracket,
        xatol=delta_xatol,
        max_iterations=delta_max_iterations,
    )
    hierarchical = fit_hierarchical_emos(
        all_rows,
        method=method,
        delta=delta_diagnostics.delta,
        bootstrap_draws=bootstrap_draws,
        bootstrap_seed=bootstrap_seed,
        resample_delta=resample_delta,
    )
    return CalibrationFit(
        delta=delta_diagnostics.delta,
        delta_converged=delta_diagnostics.converged,
        delta_nfev=delta_diagnostics.nfev,
        hierarchical=hierarchical,
    )


# ---------------------------------------------------------------------------
# G2.0 correction form (closed set; plan S4.1, R3-07)
# ---------------------------------------------------------------------------


class CorrectionForm(Enum):
    """The closed set of G2.0 correction forms (plan S4.1, R3-07). No other
    form may be introduced after S0."""

    NONE = "none"
    MONTH_OFFSET = "month_offset"
    LINEAR_DAYLENGTH = "linear_lst_day_length"


class InvalidCorrectionFormError(ValueError):
    """A correction form outside :class:`CorrectionForm`'s closed set."""


def parse_correction_form(value: str) -> CorrectionForm:
    try:
        return CorrectionForm(value)
    except ValueError as exc:
        raise InvalidCorrectionFormError(
            f"{value!r} is outside the closed correction-form set "
            f"{[form.value for form in CorrectionForm]!r} (plan S4.1, R3-07)"
        ) from exc


def apply_correction_form(
    form: CorrectionForm,
    *,
    residual_f: float,
    month: int,
    day_length_hours: float,
    month_offsets: Mapping[int, float] | None = None,
    linear_coefficients: tuple[float, float] | None = None,
) -> float:
    """Applies ``form`` to one residual, chosen on validation only (plan S4.1)."""
    if form is CorrectionForm.NONE:
        return residual_f
    if form is CorrectionForm.MONTH_OFFSET:
        if month_offsets is None or month not in month_offsets:
            raise ValueError(f"CorrectionForm.MONTH_OFFSET needs an offset for month {month}")
        return residual_f - month_offsets[month]
    if form is CorrectionForm.LINEAR_DAYLENGTH:
        if linear_coefficients is None:
            raise ValueError("CorrectionForm.LINEAR_DAYLENGTH needs (slope, intercept)")
        slope, intercept = linear_coefficients
        return residual_f - (slope * day_length_hours + intercept)
    raise InvalidCorrectionFormError(f"unhandled CorrectionForm {form!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Holm correction + the one cluster bootstrap loop this module uses
# ---------------------------------------------------------------------------


def holm_correction(
    p_values: Mapping[str, float], *, alpha: float = 0.05
) -> dict[str, dict[str, object]]:
    """Step-down Holm at family-wise ``alpha`` over however many hypotheses
    ``p_values`` holds (plan G2.0/G2.0a/G2.1 all Holm-correct over a
    variable-sized tested set, unlike the fixed-``k`` variant in
    `scripts/analysis/forecast_cheap_screen_wp7.py`)."""
    if not p_values:
        raise ValueError("holm_correction over zero hypotheses is undefined")
    k = len(p_values)
    ordered = sorted(p_values.items(), key=lambda kv: (kv[1], kv[0]))
    out: dict[str, dict[str, object]] = {}
    still_rejecting = True
    for rank, (key, p) in enumerate(ordered):
        threshold = alpha / (k - rank)
        rejected = still_rejecting and p <= threshold
        if not rejected:
            still_rejecting = False
        out[key] = {"p_value": p, "rank": rank + 1, "threshold": threshold, "rejected": rejected}
    return out


def cluster_bootstrap_draws(
    items: Sequence[_ClusterItemT],
    *,
    statistic: Callable[[Sequence[_ClusterItemT]], float],
    cluster_key: Callable[[_ClusterItemT], object],
    seed: int = BOOTSTRAP_SEED,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> list[float]:
    """Whole-cluster block bootstrap draws of ``statistic``, ascending. THE
    one resampling loop this module uses -- station-day or date clustered,
    per ``cluster_key``, seeded and deterministic. Generic over the item
    type so every call site's ``statistic``/``cluster_key`` lambdas see a
    properly typed element (e.g. ``RungEvent``, not ``object``) with no
    ``# type: ignore`` needed at the call site.
    """
    blocks = _clusters(items, cluster_key)
    if not blocks:
        raise ValueError("cluster_bootstrap_draws of an empty set is undefined")
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(iterations):
        drawn: list[_ClusterItemT] = []
        for _ in range(len(blocks)):
            drawn.extend(blocks[rng.randrange(len(blocks))])
        draws.append(statistic(drawn))
    draws.sort()
    return draws


def percentile_interval(draws: Sequence[float], *, alpha: float = 0.05) -> tuple[float, float]:
    if not draws:
        raise ValueError("an interval over zero draws is undefined")
    low = draws[max(0, math.floor((alpha / 2.0) * len(draws)))]
    high = draws[min(len(draws) - 1, math.ceil((1.0 - alpha / 2.0) * len(draws)) - 1)]
    return low, high


def _cluster_mean_p_value(
    rows: Sequence[StationDayResidual], *, seed: int, iterations: int
) -> tuple[float, float, bool]:
    """One-sample two-sided test of ``mean(residual) != 0``, with the SE
    taken from the date-clustered bootstrap (plan G2.0: "Clustering is by
    date"). Returns ``(mean, p_value, bootstrap_degenerate)`` -- the
    degenerate-SE convention (module docstring, review item 5): a
    zero-variance bootstrap that still disagrees with the null is p=0
    (reject); one that agrees exactly is p=1."""
    mean = statistics.fmean(row.residual_f for row in rows)
    draws = cluster_bootstrap_draws(
        rows,
        statistic=lambda drawn: statistics.fmean(row.residual_f for row in drawn),
        cluster_key=lambda row: row.climate_day,
        seed=seed,
        iterations=iterations,
    )
    se = statistics.pstdev(draws) if len(draws) > 1 else 0.0
    if se <= 0.0:
        return mean, (0.0 if mean != 0.0 else 1.0), True
    z = mean / se
    p = 2.0 * (1.0 - _std_normal_cdf(abs(z)))
    return mean, p, False


# ---------------------------------------------------------------------------
# G2.0 / G2.0a (plan S4.1, R2-09/R3-05/R3-07)
# ---------------------------------------------------------------------------

#: Month threshold N, fixed at S0 (plan S4.1).
G20_MONTH_N: Final[int] = 60
G20_MONTH_MIN_DATES: Final[int] = 15


@dataclass(frozen=True, slots=True)
class StationDayResidual:
    """One station-day's ``CLI tmax - calibrated M2 median`` residual (plan
    G2.0). Exactly one residual per station-day -- the bootstrap here is
    date-clustered, never station-day-clustered (a one-per-station-day
    series is degenerate under that clustering)."""

    station: str
    climate_day: dt.date
    residual_f: float
    day_length_hours: float

    @property
    def month(self) -> int:
        return self.climate_day.month


@dataclass(frozen=True, slots=True)
class G20GroupResult:
    key: str
    status: str  # "TESTED" | "UNTESTED"
    n: int
    n_dates: int
    mean_residual_f: float | None
    p_value: float | None
    holm_rejected: bool | None
    #: True iff this group's p-value came from a zero-variance (degenerate)
    #: bootstrap -- None for an UNTESTED group (review item 5; module
    #: docstring "The degenerate-SE convention").
    bootstrap_degenerate: bool | None


@dataclass(frozen=True, slots=True)
class G20Result:
    groups: tuple[G20GroupResult, ...]
    flat: bool


def _month_and_tercile_groups(
    rows: Sequence[StationDayResidual], *, tercile_edges: tuple[float, float]
) -> dict[str, list[StationDayResidual]]:
    lo_edge, hi_edge = tercile_edges

    def tercile_of(day_length: float) -> str:
        if day_length < lo_edge:
            return "short"
        if day_length < hi_edge:
            return "mid"
        return "long"

    groups: dict[str, list[StationDayResidual]] = {}
    for row in rows:
        groups.setdefault(f"month_{row.month:02d}", []).append(row)
        groups.setdefault(f"tercile_{tercile_of(row.day_length_hours)}", []).append(row)
    return groups


def _evaluate_residual_groups(
    groups: Mapping[str, Sequence[StationDayResidual]],
    *,
    seed: int,
    iterations: int,
    alpha: float,
) -> tuple[G20GroupResult, ...]:
    results: dict[str, G20GroupResult] = {}
    testable: dict[str, Sequence[StationDayResidual]] = {}
    for key, rows in groups.items():
        n_dates = len({row.climate_day for row in rows})
        if len(rows) < G20_MONTH_N or n_dates < G20_MONTH_MIN_DATES:
            results[key] = G20GroupResult(
                key=key,
                status="UNTESTED",
                n=len(rows),
                n_dates=n_dates,
                mean_residual_f=None,
                p_value=None,
                holm_rejected=None,
                bootstrap_degenerate=None,
            )
        else:
            testable[key] = rows

    p_values: dict[str, float] = {}
    means: dict[str, float] = {}
    degenerate: dict[str, bool] = {}
    for key, rows in testable.items():
        mean, p_value, is_degenerate = _cluster_mean_p_value(rows, seed=seed, iterations=iterations)
        means[key] = mean
        p_values[key] = p_value
        degenerate[key] = is_degenerate

    holm = holm_correction(p_values, alpha=alpha) if p_values else {}
    for key, rows in testable.items():
        n_dates = len({row.climate_day for row in rows})
        entry = holm[key]
        results[key] = G20GroupResult(
            key=key,
            status="TESTED",
            n=len(rows),
            n_dates=n_dates,
            mean_residual_f=means[key],
            p_value=p_values[key],
            holm_rejected=bool(entry["rejected"]),
            bootstrap_degenerate=degenerate[key],
        )
    return tuple(results[key] for key in groups)


def evaluate_g20(
    rows: Sequence[StationDayResidual],
    *,
    tercile_edges: tuple[float, float],
    seed: int = BOOTSTRAP_SEED,
    iterations: int = BOOTSTRAP_ITERATIONS,
    alpha: float = 0.05,
) -> G20Result:
    """G2.0 window-mismatch gate: residual by calendar month and by
    day-length tercile, Holm-corrected, date-clustered (plan S4.1)."""
    groups = _month_and_tercile_groups(rows, tercile_edges=tercile_edges)
    group_results = _evaluate_residual_groups(groups, seed=seed, iterations=iterations, alpha=alpha)
    flat = not any(result.holm_rejected for result in group_results if result.status == "TESTED")
    return G20Result(groups=group_results, flat=flat)


#: G2.0a strata (amendment A-6; plan S4.1).
NEAR_MIDNIGHT_STRATA: Final[Mapping[str, tuple[str, ...]]] = {
    "KMIA": ("KMIA",),
    "KMDW": ("KMDW",),
    "KLAX_KSFO_POOLED": ("KLAX", "KSFO"),
}


@dataclass(frozen=True, slots=True)
class G20aResult:
    groups: tuple[G20GroupResult, ...]
    flat: bool


def evaluate_g20a(
    rows: Sequence[StationDayResidual],
    *,
    stratum_of_station: Mapping[str, str],
    seed: int = BOOTSTRAP_SEED,
    iterations: int = BOOTSTRAP_ITERATIONS,
    alpha: float = 0.05,
) -> G20aResult:
    """G2.0a near-midnight-max stratum gate (amendment A-6). ``rows`` must
    already be filtered to near-midnight station-days (within 2h of LST
    midnight) by the caller -- that filter needs the IEM ASOS 1-min daily-max
    instant, which this module never reads. ``stratum_of_station`` maps each
    row's station to its :data:`NEAR_MIDNIGHT_STRATA` key."""
    groups: dict[str, list[StationDayResidual]] = {}
    for row in rows:
        stratum = stratum_of_station.get(row.station)
        if stratum is None:
            continue
        groups.setdefault(stratum, []).append(row)
    group_results = _evaluate_residual_groups(groups, seed=seed, iterations=iterations, alpha=alpha)
    flat = not any(result.holm_rejected for result in group_results if result.status == "TESTED")
    return G20aResult(groups=group_results, flat=flat)


# ---------------------------------------------------------------------------
# G2.1 Calibration (plan S4.1, R2-05)
# ---------------------------------------------------------------------------

RELIABILITY_BUCKET_EDGES: Final[tuple[float, ...]] = tuple(i / 10.0 for i in range(11))
G21_MIN_BUCKET_N: Final[int] = 30


@dataclass(frozen=True, slots=True)
class RungEvent:
    """One rung event: a model rung probability and its binary outcome,
    tagged to the station-day it belongs to."""

    station: str
    climate_day: dt.date
    rung_id: str
    p_model: float
    outcome: bool


@dataclass(frozen=True, slots=True)
class G21BucketResult:
    lower: float
    upper: float
    n: int
    predicted: float
    observed: float
    z: float
    p_value: float
    holm_rejected: bool
    #: True iff this bucket's p-value came from a zero-variance (degenerate)
    #: bootstrap (review item 5; module docstring "The degenerate-SE
    #: convention"). Every populated bucket is tested, so unlike
    #: :class:`G20GroupResult` this is never None.
    bootstrap_degenerate: bool


@dataclass(frozen=True, slots=True)
class G21Result:
    buckets: tuple[G21BucketResult, ...]
    passed: bool


def evaluate_g21(
    events: Sequence[RungEvent],
    *,
    edges: Sequence[float] = RELIABILITY_BUCKET_EDGES,
    seed: int = BOOTSTRAP_SEED,
    iterations: int = BOOTSTRAP_ITERATIONS,
    alpha: float = 0.05,
) -> G21Result:
    """G2.1 calibration gate: per-bucket ``z = (observed-predicted)/SE``,
    ``SE`` from the station-day cluster bootstrap, Holm-corrected. FAILs
    only if Holm rejects in at least one bucket (plan S4.1)."""
    bucketed: dict[tuple[float, float], list[RungEvent]] = {}
    for lower, upper in pairwise(edges):
        members = [
            event
            for event in events
            if lower <= event.p_model < upper or (upper == 1.0 and event.p_model == 1.0)
        ]
        if len(members) >= G21_MIN_BUCKET_N:
            bucketed[(lower, upper)] = members
    if not bucketed:
        return G21Result(buckets=(), passed=True)

    stats: dict[tuple[float, float], tuple[float, float, float, bool]] = {}
    p_values: dict[str, float] = {}
    for key, members in bucketed.items():
        predicted = statistics.fmean(event.p_model for event in members)
        observed = statistics.fmean(float(event.outcome) for event in members)
        draws = cluster_bootstrap_draws(
            members,
            statistic=lambda drawn: statistics.fmean(
                float(event.outcome) for event in drawn
            ),
            cluster_key=lambda event: (event.station, event.climate_day),
            seed=seed,
            iterations=iterations,
        )
        se = statistics.pstdev(draws) if len(draws) > 1 else 0.0
        if se <= 0.0:
            # A zero-variance bootstrap (e.g. every drawn outcome identical)
            # is the STRONGEST possible evidence when it still disagrees with
            # `predicted` -- treat it as p=0 (reject), not p=1 (mirrors
            # `_cluster_mean_p_value`'s own degenerate-SE convention; module
            # docstring "The degenerate-SE convention", review item 5).
            z = 0.0 if observed == predicted else math.inf
            p_value = 1.0 if observed == predicted else 0.0
            is_degenerate = True
        else:
            z = (observed - predicted) / se
            p_value = 2.0 * (1.0 - _std_normal_cdf(abs(z)))
            is_degenerate = False
        stats[key] = (predicted, observed, z, is_degenerate)
        p_values[f"{key[0]:.1f}_{key[1]:.1f}"] = p_value

    holm = holm_correction(p_values, alpha=alpha)
    buckets = []
    for key in bucketed:
        label = f"{key[0]:.1f}_{key[1]:.1f}"
        predicted, observed, z, is_degenerate = stats[key]
        entry = holm[label]
        buckets.append(
            G21BucketResult(
                lower=key[0],
                upper=key[1],
                n=len(bucketed[key]),
                predicted=predicted,
                observed=observed,
                z=z,
                p_value=p_values[label],
                holm_rejected=bool(entry["rejected"]),
                bootstrap_degenerate=is_degenerate,
            )
        )
    passed = not any(bucket.holm_rejected for bucket in buckets)
    return G21Result(buckets=tuple(buckets), passed=passed)


# ---------------------------------------------------------------------------
# G2.2 / G2.3 (plan S4.1, R2-12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchedEvent:
    """One matched D+1 rung event, scored under all three models on the
    SAME event (plan G2.2/G2.3)."""

    station: str
    climate_day: dt.date
    p_m2: float
    p_m1: float
    p_m0: float
    outcome: bool


def _brier(events: Sequence[MatchedEvent], which: str) -> float:
    return statistics.fmean((getattr(event, which) - float(event.outcome)) ** 2 for event in events)


def _d_res(events: Sequence[MatchedEvent], *, a: str, b: str) -> float:
    probs_a = [getattr(event, a) for event in events]
    probs_b = [getattr(event, b) for event in events]
    outcomes = [event.outcome for event in events]
    return resolution_difference(probs_a, probs_b, outcomes, bin_by_value)


def _matched_event_cluster_key(event: MatchedEvent) -> object:
    return (event.station, event.climate_day)


@dataclass(frozen=True, slots=True)
class SkillGateResult:
    brier_diff_point: float
    brier_diff_ci: tuple[float, float]
    d_res_point: float
    d_res_ci: tuple[float, float]
    passed: bool


def evaluate_g22(
    events: Sequence[MatchedEvent],
    *,
    seed: int = BOOTSTRAP_SEED,
    iterations: int = BOOTSTRAP_ITERATIONS,
    alpha: float = 0.05,
) -> SkillGateResult:
    """G2.2 skill vs M1: paired rung-Brier difference (M2-M1) CI upper < 0,
    OR ``D_res(M2-M1)`` CI lower > 0 (plan S4.1)."""
    brier_point = _brier(events, "p_m2") - _brier(events, "p_m1")
    brier_draws = cluster_bootstrap_draws(
        events,
        statistic=lambda drawn: _brier(drawn, "p_m2") - _brier(drawn, "p_m1"),
        cluster_key=_matched_event_cluster_key,
        seed=seed,
        iterations=iterations,
    )
    brier_ci = percentile_interval(brier_draws, alpha=alpha)
    d_res_point = _d_res(events, a="p_m2", b="p_m1")
    d_res_draws = cluster_bootstrap_draws(
        events,
        statistic=lambda drawn: _d_res(drawn, a="p_m2", b="p_m1"),
        cluster_key=_matched_event_cluster_key,
        seed=seed,
        iterations=iterations,
    )
    d_res_ci = percentile_interval(d_res_draws, alpha=alpha)
    passed = brier_ci[1] < 0.0 or d_res_ci[0] > 0.0
    return SkillGateResult(
        brier_diff_point=brier_point,
        brier_diff_ci=brier_ci,
        d_res_point=d_res_point,
        d_res_ci=d_res_ci,
        passed=passed,
    )


@dataclass(frozen=True, slots=True)
class G23Result:
    d_res_point: float
    d_res_ci: tuple[float, float]
    passed: bool


def evaluate_g23(
    events: Sequence[MatchedEvent],
    *,
    seed: int = BOOTSTRAP_SEED,
    iterations: int = BOOTSTRAP_ITERATIONS,
    alpha: float = 0.05,
    floor: float = G22_TARGET_DIFFERENCE_X,
) -> G23Result:
    """G2.3 materiality vs M0: ``D_res(M2-M0)`` station-day-clustered CI
    lower > 0 AND point estimate >= ``floor`` (plan S4.1, R2-12)."""
    point = _d_res(events, a="p_m2", b="p_m0")
    draws = cluster_bootstrap_draws(
        events,
        statistic=lambda drawn: _d_res(drawn, a="p_m2", b="p_m0"),
        cluster_key=_matched_event_cluster_key,
        seed=seed,
        iterations=iterations,
    )
    ci = percentile_interval(draws, alpha=alpha)
    passed = ci[0] > 0.0 and point >= floor
    return G23Result(d_res_point=point, d_res_ci=ci, passed=passed)


# ---------------------------------------------------------------------------
# Contingency C-1 (plan S4.1, R2-07/R3-05/R3-06)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class C1Reevaluation:
    deviation: C1Deviation
    g20: G20Result
    g20a: G20aResult
    g21: G21Result
    g22: SkillGateResult
    g23: G23Result


def reevaluate_c1(
    *,
    deviation: C1Deviation,
    primary_holdout_window: tuple[dt.date, dt.date],
    g20_rows: Sequence[StationDayResidual],
    g20a_rows: Sequence[StationDayResidual],
    g20a_stratum_of_station: Mapping[str, str],
    g21_events: Sequence[RungEvent],
    g22_events: Sequence[MatchedEvent],
    g23_events: Sequence[MatchedEvent],
    tercile_edges: tuple[float, float],
) -> C1Reevaluation:
    """Re-evaluates G2.0-G2.3 AS A SET on a fresh C-1 holdout (plan S4.1;
    ruling S12 recorded residual note). Raises :class:`PrimaryHoldoutLeakError`
    if ANY input row's ``climate_day`` falls inside the once-peeked primary
    holdout window -- none of the four gates may reference, pool with, or be
    conditioned on it."""
    start, end = primary_holdout_window
    all_dates = (
        [row.climate_day for row in g20_rows]
        + [row.climate_day for row in g20a_rows]
        + [event.climate_day for event in g21_events]
        + [event.climate_day for event in g22_events]
        + [event.climate_day for event in g23_events]
    )
    for day in all_dates:
        if start <= day <= end:
            raise PrimaryHoldoutLeakError(
                f"C-1 input row for {day} falls inside the primary holdout "
                f"window [{start}, {end}] -- refused (plan S4.1)"
            )
    return C1Reevaluation(
        deviation=deviation,
        g20=evaluate_g20(g20_rows, tercile_edges=tercile_edges),
        g20a=evaluate_g20a(g20a_rows, stratum_of_station=g20a_stratum_of_station),
        g21=evaluate_g21(g21_events),
        g22=evaluate_g22(g22_events),
        g23=evaluate_g23(g23_events),
    )


# ---------------------------------------------------------------------------
# The artefact (json + sha256; plan S7 row SL-8)
# ---------------------------------------------------------------------------

ARTEFACT_SCHEMA_VERSION: Final[int] = 1


def rung_bounds_from_calibration(
    percentiles: Percentiles,
    cdf_method: CdfMethod,
    draws: Sequence[EmosParams],
    rungs: Sequence[Rung],
    *,
    level: float = 0.95,
) -> dict[str, tuple[float, float, float]]:
    """The artefact's per-rung ``(p_point, p_lower, p_upper)`` (review item
    3: a degenerate ``(p, p)`` bound is no longer sufficient for any
    ``ev_net`` consumer). A thin wrapper over
    ``breezy.strategy.ladder_ev.quantile_density.rung_probability_interval``
    -- that function lives in the strategy layer (importable from the live
    trading path), not here, per the layers contract (`pyproject.toml`):
    ``breezy.analysis`` may reach DOWN into ``breezy.strategy``, never the
    reverse.
    """
    return rung_probability_interval(percentiles, cdf_method, draws, rungs, level=level)


def emos_params_from_draw_entry(entry: Sequence[float], *, fallback_delta: float) -> EmosParams:
    """Parse one ``emos_draws_by_version`` JSON entry into :class:`EmosParams`
    (SL-8b review item 3).

    Accepts BOTH shapes: a 3-element ``[a, gamma, delta]`` entry (the
    current schema -- each draw carries its OWN resampled delta) and a
    2-element ``[a, gamma]`` entry (the pre-SL-8b schema, whose draws all
    shared the artefact's single top-level ``delta``) -- ``fallback_delta``
    (the artefact's own ``delta`` field) supplies the missing third value
    for the old shape, so an artefact written before this schema change
    still parses. Any other length is refused.
    """
    if len(entry) == 3:
        a, gamma, delta = entry
        return EmosParams(a=float(a), gamma=float(gamma), delta=float(delta))
    if len(entry) == 2:
        a, gamma = entry
        return EmosParams(a=float(a), gamma=float(gamma), delta=float(fallback_delta))
    raise ValueError(f"a draw entry must have 2 or 3 elements, got {len(entry)}: {entry!r}")


@dataclass(frozen=True, slots=True)
class NbpCalibrationArtefact:
    schema_version: int
    cdf_method: str
    recalibration: str
    correction_form: str
    delta: float
    kappa: float
    #: Point estimate ``(a_v, gamma_v)`` per version -- ``delta`` (shared)
    #: is recorded once, at ``delta`` above, not repeated per version.
    emos_params_by_version: Mapping[str, tuple[float, float]]
    #: B seeded bootstrap draws of ``(a_v, gamma_v, delta)`` per version
    #: (SL-8b review item 3) -- EACH draw carries its OWN resampled delta
    #: (:func:`bootstrap_emos_draws`'s ``resample_delta=True`` default),
    #: unlike ``emos_params_by_version``'s point estimate, which stays
    #: pinned to the shared ``delta`` above. Consumed by
    #: ``breezy.strategy.ladder_ev.quantile_density.rung_probability_interval``
    #: after reconstructing each draw's :class:`EmosParams` directly (or via
    #: :func:`emos_params_from_draw_entry` when parsing JSON that may
    #: predate this schema).
    emos_draws_by_version: Mapping[str, tuple[tuple[float, float, float], ...]]
    n_min: int
    sigma_d: float
    #: Per-rung ``(p_point, p_lower, p_upper)`` (review item 3).
    rung_probability_bounds: Mapping[str, tuple[float, float, float]]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "cdf_method": self.cdf_method,
            "recalibration": self.recalibration,
            "correction_form": self.correction_form,
            "delta": self.delta,
            "kappa": "inf" if self.kappa == math.inf else self.kappa,
            "emos_params_by_version": {
                version: [a, gamma]
                for version, (a, gamma) in sorted(self.emos_params_by_version.items())
            },
            "emos_draws_by_version": {
                version: [[a, gamma, delta] for a, gamma, delta in draws]
                for version, draws in sorted(self.emos_draws_by_version.items())
            },
            "n_min": self.n_min,
            "sigma_d": self.sigma_d,
            "rung_probability_bounds": {
                rung_id: [point, lower, upper]
                for rung_id, (point, lower, upper) in sorted(self.rung_probability_bounds.items())
            },
        }


def artefact_json(artefact: NbpCalibrationArtefact) -> str:
    return json.dumps(artefact.to_json_dict(), sort_keys=True, separators=(",", ":"))


def artefact_sha256(artefact: NbpCalibrationArtefact) -> str:
    return hashlib.sha256(artefact_json(artefact).encode("utf-8")).hexdigest()


def write_artefact(path: Path, artefact: NbpCalibrationArtefact) -> str:
    """Writes ``path`` (the json) and a ``.sha256`` sidecar next to it,
    returning the digest (plan S3.2 item 9: live code sees calibration only
    through the sha-pinned manifest artefact)."""
    digest = artefact_sha256(artefact)
    path.write_text(artefact_json(artefact))
    path.with_suffix(path.suffix + ".sha256").write_text(digest + "\n")
    return digest
