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
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise
from pathlib import Path
from typing import Final, TypeVar

from breezy.analysis.brier_decomposition import bin_by_value, resolution_difference
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
    rung_probabilities,
)

__all__ = [
    "ARTEFACT_SCHEMA_VERSION",
    "BOOTSTRAP_ITERATIONS",
    "BOOTSTRAP_SEED",
    "DEFAULT_SPLITS",
    "G20_MONTH_MIN_DATES",
    "G20_MONTH_N",
    "G21_MIN_BUCKET_N",
    "G22_TARGET_DIFFERENCE_X",
    "KAPPA_GRID",
    "N_MIN_CEILING",
    "NEAR_MIDNIGHT_STRATA",
    "PMUS_INFEASIBLE_ROUTE_NODE4",
    "RELIABILITY_BUCKET_EDGES",
    "TAU_GRID",
    "C1Deviation",
    "C1Reevaluation",
    "CorrectionForm",
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
    "VersionEstimate",
    "VersionRow",
    "apply_correction_form",
    "artefact_json",
    "artefact_sha256",
    "cluster_bootstrap_draws",
    "compute_n_min",
    "crps_normal",
    "evaluate_g20",
    "evaluate_g20a",
    "evaluate_g21",
    "evaluate_g22",
    "evaluate_g23",
    "fit_hierarchical_emos",
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


@dataclass(frozen=True, slots=True)
class VersionRow:
    """One station-day's NBP percentile summary versus CLI truth, tagged to
    the NBM version whose bulletin produced it and to the split it falls in.
    ``split`` is one of ``"train"``, ``"validate"``, ``"v5_fit_slice"``, or
    ``"holdout"`` (see :meth:`Splits.split_for_date`)."""

    version: str
    split: str
    station: str
    climate_day: dt.date
    txn50_f: float
    txn_sd_f: float
    cli_tmax_f: float


@dataclass(frozen=True, slots=True)
class VersionEstimate:
    version: str
    a: float
    gamma: float
    n: int


def fit_version_unshrunk(rows: Sequence[VersionRow], *, delta: float) -> VersionEstimate:
    """Closed-form point estimate of one version's ``(a_v, gamma_v)``.

    ``a_v = mean(cli - txn50)`` (the bias). ``gamma_v`` is the
    moment-matching value that makes the mean squared STANDARDIZED
    residual -- ``residual / exp(gamma + delta * log(txn_sd))`` -- equal 1:
    ``gamma_v = 0.5 * log(mean(residual_i^2 / txn_sd_i^(2*delta)))``.
    """
    if not rows:
        raise ValueError("fit_version_unshrunk needs at least one row")
    versions = {row.version for row in rows}
    if len(versions) != 1:
        raise ValueError(f"rows must all share one version, got {sorted(versions)!r}")
    a_v = statistics.fmean(row.cli_tmax_f - row.txn50_f for row in rows)
    ratios = [
        ((row.cli_tmax_f - (row.txn50_f + a_v)) ** 2) / (row.txn_sd_f ** (2.0 * delta))
        for row in rows
    ]
    mean_ratio = max(statistics.fmean(ratios), 1e-12)
    gamma_v = 0.5 * math.log(mean_ratio)
    return VersionEstimate(version=rows[0].version, a=a_v, gamma=gamma_v, n=len(rows))


def crps_normal(mu: float, sigma: float, observed: float) -> float:
    """Closed-form CRPS of ``N(mu, sigma)`` against one observation
    (Gneiting & Raftery 2007, eq. 5)."""
    if sigma <= 0.0:
        raise ValueError(f"sigma must be positive, was {sigma!r}")
    z = (observed - mu) / sigma
    phi = math.exp(-0.5 * z * z) / _SQRT_2PI
    cdf = _std_normal_cdf(z)
    return sigma * (z * (2.0 * cdf - 1.0) + 2.0 * phi - _INV_SQRT_PI)


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
    delta: float,
    grid: Sequence[float],
    weight_fn: Callable[[int, float], float],
) -> KappaSelection:
    _assert_no_holdout_rows(rows_by_version)
    if len(rows_by_version) < 2:
        raise ValueError("LOVO selection needs at least two versions")
    unshrunk = {
        version: fit_version_unshrunk(rows, delta=delta) for version, rows in rows_by_version.items()
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
            first_half_estimate = fit_version_unshrunk(first_half, delta=delta)
            w = weight_fn(first_half_estimate.n, param)
            shrunk_a = w * first_half_estimate.a + (1.0 - w) * pooled_a
            shrunk_gamma = w * first_half_estimate.gamma + (1.0 - w) * pooled_gamma
            scores = [
                crps_normal(
                    row.txn50_f + shrunk_a,
                    math.exp(shrunk_gamma + delta * math.log(row.txn_sd_f)),
                    row.cli_tmax_f,
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
    delta: float,
    grid: Sequence[float] = KAPPA_GRID,
) -> KappaSelection:
    """LOVO first-half-fit / second-half-score CRPS kappa selection (plan
    S2.2; ruling S12 A-4). Refuses any holdout-tagged input row."""

    def weight_fn(n: int, kappa: float) -> float:
        if kappa == math.inf:
            return 0.0
        return n / (n + kappa)

    return _select_by_lovo_crps(rows_by_version, delta=delta, grid=grid, weight_fn=weight_fn)


def tau_fraction_sensitivity(
    rows_by_version: Mapping[str, Sequence[VersionRow]],
    *,
    delta: float,
    grid: Sequence[float] = TAU_GRID,
) -> KappaSelection:
    """The old unweighted tau-fraction shrinkage, report-only (ruling S12 A-4)."""

    def weight_fn(_n: int, tau: float) -> float:
        return tau

    return _select_by_lovo_crps(rows_by_version, delta=delta, grid=grid, weight_fn=weight_fn)


@dataclass(frozen=True, slots=True)
class HierarchicalEmosResult:
    delta: float
    kappa_selection: KappaSelection
    tau_sensitivity: KappaSelection
    shrunk_by_version: Mapping[str, VersionEstimate]


def fit_hierarchical_emos(all_rows: Sequence[VersionRow], *, delta: float) -> HierarchicalEmosResult:
    """Fit + precision-weight-shrink ``(a_v, gamma_v)`` for every version.

    ``all_rows`` may carry rows from EVERY split, holdout included -- rows
    tagged ``split == "holdout"`` are filtered out before anything
    downstream (kappa selection, the unshrunk fit, the pooled mean) ever
    sees them, so mutating a holdout-tagged row's values in ``all_rows``
    can never change this function's output.
    """
    fit_rows = [row for row in all_rows if row.split in ("validate", "v5_fit_slice")]
    if not fit_rows:
        raise ValueError("fit_hierarchical_emos needs at least one validate/v5_fit_slice row")
    rows_by_version: dict[str, list[VersionRow]] = {}
    for row in fit_rows:
        rows_by_version.setdefault(row.version, []).append(row)
    kappa_selection = select_kappa_by_lovo_crps(rows_by_version, delta=delta)
    tau_selection = tau_fraction_sensitivity(rows_by_version, delta=delta)
    unshrunk = {
        version: fit_version_unshrunk(rows, delta=delta) for version, rows in rows_by_version.items()
    }
    shrunk: dict[str, VersionEstimate] = {}
    for version, estimate in unshrunk.items():
        others = [other for v, other in unshrunk.items() if v != version]
        shrunk[version] = shrink_toward_lovo_pooled_mean(
            estimate, others, kappa=kappa_selection.chosen_kappa
        )
    return HierarchicalEmosResult(
        delta=delta,
        kappa_selection=kappa_selection,
        tau_sensitivity=tau_selection,
        shrunk_by_version=shrunk,
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
) -> tuple[float, float]:
    """One-sample two-sided test of ``mean(residual) != 0``, with the SE
    taken from the date-clustered bootstrap (plan G2.0: "Clustering is by
    date")."""
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
        return mean, (0.0 if mean != 0.0 else 1.0)
    z = mean / se
    p = 2.0 * (1.0 - _std_normal_cdf(abs(z)))
    return mean, p


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
            )
        else:
            testable[key] = rows

    p_values: dict[str, float] = {}
    means: dict[str, float] = {}
    for key, rows in testable.items():
        mean, p_value = _cluster_mean_p_value(rows, seed=seed, iterations=iterations)
        means[key] = mean
        p_values[key] = p_value

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

    stats: dict[tuple[float, float], tuple[float, float, float]] = {}
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
            # `_cluster_mean_p_value`'s own degenerate-SE convention).
            z = 0.0 if observed == predicted else math.inf
            p_value = 1.0 if observed == predicted else 0.0
        else:
            z = (observed - predicted) / se
            p_value = 2.0 * (1.0 - _std_normal_cdf(abs(z)))
        stats[key] = (predicted, observed, z)
        p_values[f"{key[0]:.1f}_{key[1]:.1f}"] = p_value

    holm = holm_correction(p_values, alpha=alpha)
    buckets = []
    for key in bucketed:
        label = f"{key[0]:.1f}_{key[1]:.1f}"
        predicted, observed, z = stats[key]
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
    emos: EmosParams,
    rungs: Sequence[Rung],
) -> dict[str, tuple[float, float]]:
    """The artefact's ``p_lower``/``p_upper`` per rung: the calibrated rung
    probability, reported today as a degenerate ``(p, p)`` bound -- a
    bootstrap-widened interval is a later slice's job; this module emits
    the SHAPE the artefact promises (plan S7 row SL-8) via
    ``breezy.strategy.ladder_ev.quantile_density``.
    """
    base_cdf = build_cdf(cdf_method, percentiles)
    calibrated_cdf = apply_emos(base_cdf, percentiles, emos)
    probabilities = rung_probabilities(calibrated_cdf, rungs)
    return {rung_id: (probability, probability) for rung_id, probability in probabilities.items()}


@dataclass(frozen=True, slots=True)
class NbpCalibrationArtefact:
    schema_version: int
    cdf_method: str
    recalibration: str
    correction_form: str
    delta: float
    kappa: float
    emos_params_by_version: Mapping[str, tuple[float, float]]
    n_min: int
    sigma_d: float
    rung_probability_bounds: Mapping[str, tuple[float, float]]

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
            "n_min": self.n_min,
            "sigma_d": self.sigma_d,
            "rung_probability_bounds": {
                rung_id: [lo, hi]
                for rung_id, (lo, hi) in sorted(self.rung_probability_bounds.items())
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
