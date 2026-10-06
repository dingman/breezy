"""F13 Phase A: the offline multi-source blend against the NBP champion.

Plan: ``docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r3.md`` section
"Phase A1 / A" (r3.1, r3.2 and ruling F13-R35 binding). PURE: no network, no clock, no file access,
no Nautilus import. It holds the feature assembly with its leakage assertions, the Student-t blend,
the nested ladder M0' / M1 / M2 / M3, the fold construction, and the paired-delta statistics. The
champion M0 is :func:`breezy.analysis.nbp_calibration.fit_calibration`, left untouched; every CRPS
here goes through :func:`breezy.analysis.nbp_calibration.crps_numerical` with ``center`` = the mu
being scored.

Sealed days. A row whose climate day is on or after ``DEFAULT_SPLITS.holdout_start`` is REFUSED by
every fitting, folding and scoring entry point (:class:`HoldoutLeakError`); this module never calls
``open_holdout``.

Ladder and nesting. The regressors of a cell are the NBP q50, ``obs_so_far`` when defined, then
``L = max(obs_so_far, lamp_rem_max_f)`` (level 1), the PFM mu (level 2) and the GFS MOS mu
(level 3). A row scores with the LONGEST PRESENT PREFIX of [LAMP, PFM, MOS], capped at the model's
level, so a row whose LAMP feature is missing scores exactly as M0' (R35: nothing is imputed). The
level-0 cell is fitted on every row, so M0' is the same fit inside every ladder step.

The distribution is Student-t with ``log sigma = c + d*log(NBP sd)`` (plus ``e*log(source
disagreement)`` only in the separate step ``use_disagreement_sigma``), floored at
``sigma_floor_f``. Weights shrink toward a sum of 1 with ``weight_sum_lambda * n * (sum(w)-1)^2``,
not a hard box. Fitting minimises the Student-t negative log-likelihood; scoring is CRPS.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln, stdtr, stdtrit

from breezy.analysis.nbp_calibration import (
    DEFAULT_BOOTSTRAP_DRAWS,
    DEFAULT_SPLITS,
    VersionRow,
    crps_numerical,
    fit_calibration,
)
from breezy.domain.climate_day import climate_day_for_instant, standard_time_zone
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    apply_emos,
    build_cdf,
)

__all__ = [
    "ALPHA_ONE_SIDED",
    "HOLDOUT_START",
    "LAG_SHIFT_NS",
    "MISSING_LAMP",
    "STRICT_24H_LABEL",
    "AcceptanceDecision",
    "AcceptanceInputs",
    "ArmPrediction",
    "BlendFit",
    "BlendSettings",
    "C1LagEvidenceError",
    "CellParams",
    "ChampionSpec",
    "DeltaSummary",
    "FeatureRow",
    "Fold",
    "FoldPlan",
    "HoldoutLeakError",
    "InsufficientFoldsError",
    "InsufficientRowsError",
    "LampFeature",
    "LampHour",
    "LampRun",
    "LeakageError",
    "M0PrimeStatus",
    "Missingness",
    "NonFiniteInputError",
    "ObsReading",
    "PreregIncompleteError",
    "ScoredRow",
    "SourceVintage",
    "Verdict",
    "assemble_feature_row",
    "assert_lamp_run_before_anchor",
    "assert_pre_holdout",
    "assert_row_leakage_free",
    "blend_cdf",
    "build_folds",
    "champion_cdf",
    "combined_lamp_input",
    "days_by_version",
    "decide_acceptance",
    "delta_by_day",
    "delta_summary",
    "diagnostics",
    "feature_row_from_json",
    "feature_row_to_json",
    "fit_blend",
    "fold_mean_crps",
    "fold_sd",
    "fold_sign_threshold",
    "lag_rows_lost",
    "lamp_missingness_by_horizon",
    "lamp_remaining_feature",
    "lower_bound_one_sided",
    "m0_prime_status",
    "mean_arm_crps",
    "mean_arm_difference",
    "merge_scored",
    "minimum_effect_floor",
    "obs_so_far",
    "out_of_fold_scores",
    "per_fold_delta",
    "per_station_delta",
    "predict_row",
    "require_c1_measured_lags",
    "row_crps",
    "score_rows",
    "scored_row_from_json",
    "scored_row_to_json",
    "shuffle_labels",
    "source_disagreement_f",
    "stationary_bootstrap_means",
    "strict_24h_max_diagnostic",
    "student_t_cdf",
]

_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3_600 * _NS
HOLDOUT_START: Final[dt.date] = DEFAULT_SPLITS.holdout_start
#: Plan R15 acceptance 8: every source lag is shifted by this much in the sensitivity rerun.
LAG_SHIFT_NS: Final[int] = 3_600 * _NS
#: Plan acceptance 1: the lower bound is one-sided 97.5 %.
ALPHA_ONE_SIDED: Final[float] = 0.025
STRICT_24H_LABEL: Final[str] = "diagnostic_only"
PEAK_LST_HOURS: Final[tuple[int, ...]] = tuple(range(12, 19))
HORIZONS: Final[tuple[str, ...]] = ("D0", "D-1")
LEVEL_SOURCES: Final[tuple[str, ...]] = ("lamp", "pfm", "mos")
ARM_NAMES: Final[tuple[str, ...]] = ("M0prime", "M1", "M2", "M3")
#: Floor on the sd of the sources' mu in the disagreement-sigma step (avoids log 0).
DISAGREEMENT_SD_FLOOR_F: Final[float] = 0.1
_RIDGE: Final[float] = 1e-6
_MAX_FIT_ITER: Final[int] = 400
_LOG_FLOOR: Final[float] = 1e-12


class NonFiniteInputError(ValueError):
    """A NaN or infinite input; refused, never imputed."""


class LeakageError(RuntimeError):
    """A feature whose availability is not strictly before the anchor."""


class HoldoutLeakError(RuntimeError):
    """A row on or after the sealed holdout start reached a fit, a fold or a score."""


class InsufficientRowsError(ValueError):
    """Not enough rows to fit or to predict a cell."""


class InsufficientFoldsError(ValueError):
    """Fewer folds than a spread needs."""


class PreregIncompleteError(ValueError):
    """A prereg value the computation needs is still null."""


class C1LagEvidenceError(RuntimeError):
    """C1 has not yet measured enough lag days to freeze the source lags."""


# ------------------------------------------------------------------ feature inputs


@dataclass(frozen=True, slots=True)
class ObsReading:
    ts_ns: int
    available_at_ns: int
    temp_f: float
    source: str = "obs"


@dataclass(frozen=True, slots=True)
class LampHour:
    valid_ts_ns: int
    tmp_f: float | None


@dataclass(frozen=True, slots=True)
class LampRun:
    """One LAMP run: ``lavtxt`` and ``lavtxt_ext`` hours merged by the caller."""

    issued_ns: int
    available_at_ns: int
    hours: tuple[LampHour, ...]


@dataclass(frozen=True, slots=True)
class SourceVintage:
    available_at_ns: int
    mu_f: float


def _finite(name: str, value: float | None) -> None:
    if value is not None and not math.isfinite(value):
        raise NonFiniteInputError(f"{name} is not finite ({value!r}); refused, never imputed")


@dataclass(frozen=True, slots=True)
class LampFeature:
    """F13-R35: the remaining-hours LAMP feature and its persisted coverage fields."""

    rem_max_f: float | None
    hours_covered: int
    peak_covered: bool
    missing: bool
    run_available_at_ns: int | None
    min_valid_ts_ns: int | None
    strict_24h_max_f_diagnostic: float | None

    def __post_init__(self) -> None:
        _finite("lamp.rem_max_f", self.rem_max_f)
        _finite("lamp.strict_24h_max_f_diagnostic", self.strict_24h_max_f_diagnostic)
        if self.missing and self.rem_max_f is not None:
            raise ValueError("a missing LAMP feature carries no value (nothing is imputed)")
        if not self.missing and self.rem_max_f is None:
            raise ValueError("a present LAMP feature needs rem_max_f")


MISSING_LAMP: Final[LampFeature] = LampFeature(None, 0, False, True, None, None, None)


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """One station-day at one horizon, with every input available before ``anchor_ns``."""

    station: str
    climate_day: dt.date
    version: str
    horizon: str
    anchor_ns: int
    percentiles: Percentiles
    cli_tmax_f: float
    obs_so_far_f: float | None = None
    obs_available_at_ns: int | None = None
    lamp: LampFeature = MISSING_LAMP
    pfm_mu_f: float | None = None
    pfm_available_at_ns: int | None = None
    mos_mu_f: float | None = None
    mos_available_at_ns: int | None = None

    def __post_init__(self) -> None:
        if self.horizon not in HORIZONS:
            raise ValueError(f"horizon must be one of {HORIZONS}, was {self.horizon!r}")
        p = self.percentiles
        for name in ("q10", "q25", "q50", "q75", "q90", "mean", "sd"):
            _finite(f"percentiles.{name}", getattr(p, name))
        if not p.sd > 0.0:
            raise NonFiniteInputError(f"NBP sd must be positive, was {p.sd!r}")
        _finite("cli_tmax_f", self.cli_tmax_f)
        _finite("obs_so_far_f", self.obs_so_far_f)
        _finite("pfm_mu_f", self.pfm_mu_f)
        _finite("mos_mu_f", self.mos_mu_f)

    @property
    def lamp_input_f(self) -> float | None:
        """``L = max(obs_so_far, lamp_rem_max_f)``; ``None`` when LAMP is missing (R35)."""
        if self.lamp.missing:
            return None
        return combined_lamp_input(self.obs_so_far_f, self.lamp.rem_max_f)

    @property
    def prefix_level(self) -> int:
        """Length of the present prefix of [LAMP, PFM, MOS]."""
        level = 0
        for present in (
            not self.lamp.missing,
            self.pfm_mu_f is not None,
            self.mos_mu_f is not None,
        ):
            if not present:
                break
            level += 1
        return level


def combined_lamp_input(obs_so_far_f: float | None, lamp_rem_max_f: float | None) -> float | None:
    if lamp_rem_max_f is None:
        return None
    if obs_so_far_f is None:
        return lamp_rem_max_f
    return max(obs_so_far_f, lamp_rem_max_f)


def _lst_date(ts_ns: int, offset_hours: float) -> dt.date:
    return climate_day_for_instant(dt.datetime.fromtimestamp(ts_ns // _NS, tz=dt.UTC), offset_hours)


def _lst_midnight_ns(day: dt.date, offset_hours: float) -> int:
    utc = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC) - dt.timedelta(
        hours=offset_hours
    )
    return int(utc.timestamp()) * _NS


def assert_lamp_run_before_anchor(run: LampRun, anchor_ns: int, *, extra_lag_ns: int = 0) -> None:
    if run.available_at_ns + extra_lag_ns >= anchor_ns:
        raise LeakageError(
            f"LAMP run available_at {run.available_at_ns} (+{extra_lag_ns}) is not before the "
            f"anchor {anchor_ns}"
        )


def lamp_remaining_feature(
    runs: Sequence[LampRun],
    *,
    anchor_ns: int,
    climate_day: dt.date,
    std_utc_offset_hours: float,
    extra_lag_ns: int = 0,
) -> LampFeature:
    """F13-R35 ``lamp_rem_max_f`` from the latest run available before the anchor."""
    eligible = [r for r in runs if r.available_at_ns + extra_lag_ns < anchor_ns]
    if not eligible:
        return MISSING_LAMP
    run = max(eligible, key=lambda r: (r.issued_ns, r.available_at_ns))
    assert_lamp_run_before_anchor(run, anchor_ns, extra_lag_ns=extra_lag_ns)
    zone = standard_time_zone(std_utc_offset_hours)
    used: list[tuple[int, float]] = []
    present_hours: set[int] = set()
    for hour in run.hours:
        if hour.valid_ts_ns <= anchor_ns or hour.tmp_f is None:
            continue
        if _lst_date(hour.valid_ts_ns, std_utc_offset_hours) != climate_day:
            continue
        _finite("lamp hour tmp_f", hour.tmp_f)
        used.append((hour.valid_ts_ns, hour.tmp_f))
        present_hours.add(dt.datetime.fromtimestamp(hour.valid_ts_ns // _NS, tz=zone).hour)
    midnight = _lst_midnight_ns(climate_day, std_utc_offset_hours)
    expected = {h for h in PEAK_LST_HOURS if midnight + h * _HOUR_NS > anchor_ns}
    peak_covered = expected <= present_hours
    strict = strict_24h_max_diagnostic(run, climate_day, std_utc_offset_hours)
    if not used or not peak_covered:
        return LampFeature(None, len(used), peak_covered, True, run.available_at_ns, None, strict)
    return LampFeature(
        rem_max_f=max(temp for _ts, temp in used),
        hours_covered=len(used),
        peak_covered=True,
        missing=False,
        run_available_at_ns=run.available_at_ns,
        min_valid_ts_ns=min(ts for ts, _temp in used),
        strict_24h_max_f_diagnostic=strict,
    )


def strict_24h_max_diagnostic(
    run: LampRun, climate_day: dt.date, std_utc_offset_hours: float
) -> float | None:
    """The S3 strict all-24-hours max (``STRICT_24H_LABEL``): never a blend input."""
    window = [h for h in run.hours if _lst_date(h.valid_ts_ns, std_utc_offset_hours) == climate_day]
    if len(window) != 24 or any(h.tmp_f is None for h in window):
        return None
    return max(h.tmp_f for h in window if h.tmp_f is not None)


def _eligible_obs(
    readings: Sequence[ObsReading], anchor_ns: int, climate_day: dt.date, offset: float
) -> list[ObsReading]:
    chosen: list[ObsReading] = []
    for reading in readings:
        if "lamp" in reading.source.lower():
            raise LeakageError("obs_so_far is never sourced from LAMP")
        if reading.available_at_ns >= anchor_ns or reading.ts_ns > anchor_ns:
            continue
        if _lst_date(reading.ts_ns, offset) != climate_day:
            continue
        _finite("obs temp_f", reading.temp_f)
        chosen.append(reading)
    return chosen


def obs_so_far(
    readings: Sequence[ObsReading],
    *,
    anchor_ns: int,
    climate_day: dt.date,
    std_utc_offset_hours: float,
) -> float | None:
    """Max observed temperature so far in the climate day; ``None`` when none exists (D-1)."""
    chosen = _eligible_obs(readings, anchor_ns, climate_day, std_utc_offset_hours)
    return max(r.temp_f for r in chosen) if chosen else None


def _latest_vintage(
    vintages: Sequence[SourceVintage], anchor_ns: int, extra_lag_ns: int
) -> SourceVintage | None:
    eligible = [v for v in vintages if v.available_at_ns + extra_lag_ns < anchor_ns]
    return max(eligible, key=lambda v: v.available_at_ns) if eligible else None


def assemble_feature_row(
    *,
    station: str,
    climate_day: dt.date,
    version: str,
    horizon: str,
    anchor_ns: int,
    std_utc_offset_hours: float,
    percentiles: Percentiles,
    cli_tmax_f: float,
    obs_readings: Sequence[ObsReading] = (),
    lamp_runs: Sequence[LampRun] = (),
    pfm_vintages: Sequence[SourceVintage] = (),
    mos_vintages: Sequence[SourceVintage] = (),
    extra_lag_ns: int = 0,
) -> FeatureRow:
    """Build one row from raw inputs, taking only vintages available before the anchor."""
    chosen_obs = _eligible_obs(obs_readings, anchor_ns, climate_day, std_utc_offset_hours)
    pfm = _latest_vintage(pfm_vintages, anchor_ns, extra_lag_ns)
    mos = _latest_vintage(mos_vintages, anchor_ns, extra_lag_ns)
    row = FeatureRow(
        station=station,
        climate_day=climate_day,
        version=version,
        horizon=horizon,
        anchor_ns=anchor_ns,
        percentiles=percentiles,
        cli_tmax_f=cli_tmax_f,
        obs_so_far_f=max(r.temp_f for r in chosen_obs) if chosen_obs else None,
        obs_available_at_ns=max(r.available_at_ns for r in chosen_obs) if chosen_obs else None,
        lamp=lamp_remaining_feature(
            lamp_runs,
            anchor_ns=anchor_ns,
            climate_day=climate_day,
            std_utc_offset_hours=std_utc_offset_hours,
            extra_lag_ns=extra_lag_ns,
        ),
        pfm_mu_f=None if pfm is None else pfm.mu_f,
        pfm_available_at_ns=None if pfm is None else pfm.available_at_ns,
        mos_mu_f=None if mos is None else mos.mu_f,
        mos_available_at_ns=None if mos is None else mos.available_at_ns,
    )
    assert_row_leakage_free(row)
    return row


def assert_row_leakage_free(row: FeatureRow) -> None:
    """The scored-row assertion: ``max(available_at) < anchor`` and ``min(valid_ts) > anchor``."""
    pairs = (
        ("obs", row.obs_so_far_f, row.obs_available_at_ns),
        ("pfm", row.pfm_mu_f, row.pfm_available_at_ns),
        ("mos", row.mos_mu_f, row.mos_available_at_ns),
    )
    for name, value, available in pairs:
        if value is None:
            continue
        if available is None or available >= row.anchor_ns:
            raise LeakageError(
                f"{name} available_at {available} is not before the anchor {row.anchor_ns} "
                f"({row.station} {row.climate_day} {row.horizon})"
            )
    lamp = row.lamp
    if lamp.run_available_at_ns is not None and lamp.run_available_at_ns >= row.anchor_ns:
        raise LeakageError(
            f"LAMP run available_at {lamp.run_available_at_ns} is not before the anchor"
        )
    if lamp.min_valid_ts_ns is not None and lamp.min_valid_ts_ns <= row.anchor_ns:
        raise LeakageError(f"LAMP hour valid_ts {lamp.min_valid_ts_ns} is not after the anchor")
    if not lamp.missing and (lamp.run_available_at_ns is None or lamp.min_valid_ts_ns is None):
        raise LeakageError("a present LAMP feature must carry its run availability and first hour")


def assert_pre_holdout(rows: Sequence[FeatureRow]) -> None:
    for row in rows:
        if row.climate_day >= HOLDOUT_START:
            raise HoldoutLeakError(
                f"climate day {row.climate_day} is on or after the sealed start {HOLDOUT_START}"
            )


def _assert_admissible(rows: Sequence[FeatureRow]) -> None:
    assert_pre_holdout(rows)
    for row in rows:
        assert_row_leakage_free(row)


# ------------------------------------------------------------------ the blend


@dataclass(frozen=True, slots=True)
class BlendSettings:
    nu: float
    sigma_floor_f: float
    weight_sum_lambda: float
    min_cell_rows: int
    use_disagreement_sigma: bool = False

    def __post_init__(self) -> None:
        if not (math.isfinite(self.nu) and self.nu > 0.0):
            raise ValueError(f"nu must be positive, was {self.nu!r}")
        if not (math.isfinite(self.sigma_floor_f) and self.sigma_floor_f > 0.0):
            raise ValueError(f"sigma_floor_f must be positive, was {self.sigma_floor_f!r}")
        if not (math.isfinite(self.weight_sum_lambda) and self.weight_sum_lambda >= 0.0):
            raise ValueError("weight_sum_lambda must be non-negative")
        if self.min_cell_rows < 5:
            raise ValueError("min_cell_rows must be at least 5")


@dataclass(frozen=True, slots=True)
class CellParams:
    level: int
    obs: bool
    b: float
    w: tuple[float, ...]
    c: float
    d: float
    e: float | None
    n: int


@dataclass(frozen=True, slots=True)
class BlendFit:
    level: int
    settings: BlendSettings
    cells: Mapping[tuple[int, bool], CellParams]


def source_disagreement_f(row: FeatureRow, *, level: int) -> float:
    """Population sd of the sources' mu (NBP q50, L, PFM, MOS up to ``level``), floored."""
    if level < 1:
        raise ValueError("source disagreement needs at least one source beyond NBP")
    values = [row.percentiles.q50]
    lamp_input = row.lamp_input_f
    if lamp_input is None:
        raise ValueError("source disagreement needs the LAMP term at level >= 1")
    values.append(lamp_input)
    if level >= 2 and row.pfm_mu_f is not None:
        values.append(row.pfm_mu_f)
    if level >= 3 and row.mos_mu_f is not None:
        values.append(row.mos_mu_f)
    return max(statistics.pstdev(values), DISAGREEMENT_SD_FLOOR_F)


def _regressors(row: FeatureRow, level: int) -> list[float]:
    x = [row.percentiles.q50]
    if row.obs_so_far_f is not None:
        x.append(row.obs_so_far_f)
    if level >= 1:
        x.append(_required(row.lamp_input_f))
    if level >= 2:
        x.append(_required(row.pfm_mu_f))
    if level >= 3:
        x.append(_required(row.mos_mu_f))
    return x


def _required(value: float | None) -> float:
    if value is None:
        raise InsufficientRowsError("a regressor the cell needs is missing on this row")
    return value


def _t_constant(nu: float) -> float:
    return float(gammaln((nu + 1.0) / 2.0) - gammaln(nu / 2.0) - 0.5 * math.log(nu * math.pi))


def _fit_cell(
    rows: Sequence[FeatureRow], level: int, obs: bool, settings: BlendSettings
) -> CellParams:
    x = np.asarray([_regressors(r, level) for r in rows], dtype=np.float64)
    y = np.asarray([r.cli_tmax_f for r in rows], dtype=np.float64)
    log_sd = np.log(np.asarray([r.percentiles.sd for r in rows], dtype=np.float64))
    use_e = settings.use_disagreement_sigma and level >= 1
    log_dis = (
        np.log(np.asarray([source_disagreement_f(r, level=level) for r in rows], dtype=np.float64))
        if use_e
        else None
    )
    n, m = x.shape
    centre = x.mean(axis=0)
    xc = x - centre
    design = np.column_stack([np.ones(n), xc])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    resid_sd = float(np.std(y - design @ beta))
    nu, floor, lam = settings.nu, settings.sigma_floor_f, settings.weight_sum_lambda
    const = _t_constant(nu)

    def objective(theta: np.ndarray) -> float:
        mu = theta[0] + xc @ theta[1 : 1 + m]
        eta = theta[1 + m] + theta[2 + m] * log_sd
        if log_dis is not None:
            eta = eta + theta[3 + m] * log_dis
        sigma = np.maximum(np.exp(np.clip(eta, -20.0, 20.0)), floor)
        z = (y - mu) / sigma
        nll = float(np.sum(np.log(sigma) - const + 0.5 * (nu + 1.0) * np.log1p(z * z / nu)))
        penalty = lam * n * float(np.sum(theta[1 : 1 + m]) - 1.0) ** 2
        ridge = _RIDGE * float(np.sum(theta[2 + m :] ** 2))
        return nll + penalty + ridge

    start = np.concatenate(
        [beta, [math.log(max(resid_sd, floor)), 0.0], [0.0] if log_dis is not None else []]
    )
    result = minimize(objective, start, method="L-BFGS-B", options={"maxiter": _MAX_FIT_ITER})
    theta = np.asarray(result.x, dtype=np.float64)
    w = theta[1 : 1 + m]
    return CellParams(
        level=level,
        obs=obs,
        b=float(theta[0] - centre @ w),
        w=tuple(float(v) for v in w),
        c=float(theta[1 + m]),
        d=float(theta[2 + m]),
        e=float(theta[3 + m]) if log_dis is not None else None,
        n=n,
    )


def fit_blend(rows: Sequence[FeatureRow], *, level: int, settings: BlendSettings) -> BlendFit:
    """Fit every cell of one ladder step. ``level`` 0 is M0', 1..3 are M1..M3."""
    if level not in range(4):
        raise ValueError(f"level must be 0..3, was {level!r}")
    _assert_admissible(rows)
    if not rows:
        raise InsufficientRowsError("no rows to fit")
    groups: dict[tuple[int, bool], list[FeatureRow]] = {}
    for row in rows:
        eff = 0 if level == 0 else min(row.prefix_level, level)
        groups.setdefault((eff, row.obs_so_far_f is not None), []).append(row)
        if eff > 0:
            # level-0 cell: M0' is fitted on every row, identically inside every ladder step
            groups.setdefault((0, row.obs_so_far_f is not None), []).append(row)
    cells = {
        key: _fit_cell(members, key[0], key[1], settings)
        for key, members in sorted(groups.items())
        if len(members) >= settings.min_cell_rows
    }
    if not cells:
        raise InsufficientRowsError("no cell reached min_cell_rows")
    return BlendFit(level=level, settings=settings, cells=cells)


def _cell_for(fit: BlendFit, row: FeatureRow) -> tuple[CellParams, int]:
    eff = min(row.prefix_level, fit.level)
    obs = row.obs_so_far_f is not None
    for level in range(eff, -1, -1):
        cell = fit.cells.get((level, obs))
        if cell is not None:
            return cell, level
    raise InsufficientRowsError(
        f"no fitted cell for obs_present={obs} at or below level {eff} "
        f"({row.station} {row.climate_day})"
    )


def predict_row(fit: BlendFit, row: FeatureRow) -> tuple[float, float, int]:
    """``(mu, sigma, effective_level)`` for one row."""
    cell, level = _cell_for(fit, row)
    x = _regressors(row, level)
    mu = cell.b + sum(w * v for w, v in zip(cell.w, x, strict=True))
    eta = cell.c + cell.d * math.log(row.percentiles.sd)
    if cell.e is not None:
        eta += cell.e * math.log(source_disagreement_f(row, level=level))
    sigma = max(math.exp(max(-20.0, min(20.0, eta))), fit.settings.sigma_floor_f)
    return mu, sigma, level


def student_t_cdf(mu: float, sigma: float, nu: float) -> Callable[[float], float]:
    def cdf(x: float) -> float:
        return float(stdtr(nu, (x - mu) / sigma))

    return cdf


def row_crps(fit: BlendFit, row: FeatureRow) -> float:
    mu, sigma, _level = predict_row(fit, row)
    return crps_numerical(student_t_cdf(mu, sigma, fit.settings.nu), row.cli_tmax_f, center=mu)


def score_rows(fit: BlendFit, rows: Sequence[FeatureRow]) -> list[float]:
    _assert_admissible(rows)
    return [row_crps(fit, row) for row in rows]


# ------------------------------------------------------------------ folds


@dataclass(frozen=True, slots=True)
class Fold:
    fold_id: int
    version: str
    segment: int
    held_days: tuple[dt.date, ...]
    train_days: tuple[dt.date, ...]


@dataclass(frozen=True, slots=True)
class FoldPlan:
    folds: tuple[Fold, ...]
    excluded: tuple[tuple[str, int, str], ...]


def days_by_version(rows: Sequence[FeatureRow]) -> dict[str, tuple[dt.date, ...]]:
    grouped: dict[str, set[dt.date]] = {}
    for row in rows:
        grouped.setdefault(row.version, set()).add(row.climate_day)
    return {version: tuple(sorted(days)) for version, days in grouped.items()}


def build_folds(
    days: Mapping[str, Sequence[dt.date]],
    *,
    source_breaks: Sequence[dt.date],
    block_days: int = 28,
    min_train_days: int = 28,
    min_blocks: int = 2,
) -> FoldPlan:
    """Blocked folds within each NBM version AND each source-break segment.

    A segment enters only with at least ``min_blocks`` blocks of at least ``block_days`` held days
    and at least ``min_train_days`` train days. The remainder joins the last block. No fold's held
    or train days cross a break, so a fold never straddles a source break.
    """
    for version_days in days.values():
        for day in version_days:
            if day >= HOLDOUT_START:
                raise HoldoutLeakError(f"climate day {day} is on or after {HOLDOUT_START}")
    breaks = sorted(source_breaks)
    folds: list[Fold] = []
    excluded: list[tuple[str, int, str]] = []
    for version in sorted(days):
        segments: dict[int, list[dt.date]] = {}
        for day in sorted(set(days[version])):
            segments.setdefault(sum(1 for b in breaks if day >= b), []).append(day)
        for segment, ordered in sorted(segments.items()):
            n_blocks = len(ordered) // block_days
            if n_blocks < min_blocks:
                excluded.append(
                    (version, segment, f"{len(ordered)} days: fewer than {min_blocks} blocks")
                )
                continue
            blocks = [ordered[i * block_days : (i + 1) * block_days] for i in range(n_blocks)]
            blocks[-1] = ordered[(n_blocks - 1) * block_days :]
            if len(ordered) - max(len(b) for b in blocks) < min_train_days:
                excluded.append(
                    (
                        version,
                        segment,
                        f"{len(ordered)} days: fewer than {min_train_days} train days",
                    )
                )
                continue
            for block in blocks:
                held = set(block)
                folds.append(
                    Fold(
                        fold_id=len(folds),
                        version=version,
                        segment=segment,
                        held_days=tuple(block),
                        train_days=tuple(d for d in ordered if d not in held),
                    )
                )
    return FoldPlan(folds=tuple(folds), excluded=tuple(excluded))


# ------------------------------------------------------------------ out-of-fold scoring


@dataclass(frozen=True, slots=True)
class ArmPrediction:
    mu: float
    sigma: float
    nu: float


@dataclass(frozen=True, slots=True)
class ChampionSpec:
    """The champion's out-of-fold calibrated CDF: bulletin + fitted EMOS params."""

    method: str
    percentiles: Percentiles
    a: float
    gamma: float
    delta: float


@dataclass(frozen=True, slots=True)
class ScoredRow:
    station: str
    climate_day: dt.date
    horizon: str
    version: str
    fold_id: int | None
    observed_f: float
    crps: Mapping[str, float]
    arm_predictions: Mapping[str, ArmPrediction]
    champion: ChampionSpec | None


def champion_cdf(spec: ChampionSpec) -> Callable[[float], float]:
    return apply_emos(
        build_cdf(CdfMethod[spec.method], spec.percentiles),
        spec.percentiles,
        EmosParams(a=spec.a, gamma=spec.gamma, delta=spec.delta),
    )


def blend_cdf(prediction: ArmPrediction) -> Callable[[float], float]:
    return student_t_cdf(prediction.mu, prediction.sigma, prediction.nu)


def _version_row(row: FeatureRow) -> VersionRow:
    return VersionRow(
        version=row.version,
        split=DEFAULT_SPLITS.split_for_date(row.climate_day),
        station=row.station,
        climate_day=row.climate_day,
        percentiles=row.percentiles,
        cli_tmax_f=row.cli_tmax_f,
    )


def _champion_rows(
    pool: Sequence[FeatureRow], held: Sequence[FeatureRow], method: CdfMethod, draws: int
) -> list[tuple[float, ChampionSpec]]:
    """M0 scored out of fold: ``fit_calibration`` on ``pool`` (every pre-holdout row outside the
    held block, all versions, as the committed champion is fitted), then the held rows only."""
    fit = fit_calibration([_version_row(r) for r in pool], method=method, bootstrap_draws=draws)
    out: list[tuple[float, ChampionSpec]] = []
    for row in held:
        estimate = fit.hierarchical.shrunk_by_version[row.version]
        spec = ChampionSpec(method.name, row.percentiles, estimate.a, estimate.gamma, fit.delta)
        out.append(
            (
                crps_numerical(champion_cdf(spec), row.cli_tmax_f, center=row.percentiles.q50),
                spec,
            )
        )
    return out


def out_of_fold_scores(
    rows: Sequence[FeatureRow],
    plan: FoldPlan,
    settings: BlendSettings,
    *,
    levels: Sequence[int],
    champion: bool = True,
    m0_bootstrap_draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    champion_method: CdfMethod = CdfMethod.NORMAL,
) -> list[ScoredRow]:
    """Score every held row of every fold with models fitted without that fold's held days.

    The blend arms train on the fold's own train days (same version, same source segment). The
    champion M0 is the shared multi-version ``fit_calibration`` over every pre-holdout row outside
    the held block, because the champion's hierarchical shrinkage needs several versions; it is the
    same procedure the committed champion uses, never fitted on the rows it scores.
    """
    _assert_admissible(rows)
    scored: list[ScoredRow] = []
    for fold in plan.folds:
        held_days, train_days = set(fold.held_days), set(fold.train_days)
        held = [r for r in rows if r.version == fold.version and r.climate_day in held_days]
        train = [r for r in rows if r.version == fold.version and r.climate_day in train_days]
        if not held:
            continue
        crps: list[dict[str, float]] = [{} for _ in held]
        predictions: list[dict[str, ArmPrediction]] = [{} for _ in held]
        for level in levels:
            fit = fit_blend(train, level=level, settings=settings)
            arm = ARM_NAMES[level]
            for i, row in enumerate(held):
                mu, sigma, _eff = predict_row(fit, row)
                predictions[i][arm] = ArmPrediction(mu, sigma, settings.nu)
                crps[i][arm] = row_crps(fit, row)
        specs: list[ChampionSpec | None] = [None] * len(held)
        if champion:
            pool = [
                r for r in rows if not (r.version == fold.version and r.climate_day in held_days)
            ]
            for i, (value, spec) in enumerate(
                _champion_rows(pool, held, champion_method, m0_bootstrap_draws)
            ):
                crps[i]["M0"] = value
                specs[i] = spec
        for i, row in enumerate(held):
            scored.append(
                ScoredRow(
                    station=row.station,
                    climate_day=row.climate_day,
                    horizon=row.horizon,
                    version=row.version,
                    fold_id=fold.fold_id,
                    observed_f=row.cli_tmax_f,
                    crps=crps[i],
                    arm_predictions=predictions[i],
                    champion=specs[i],
                )
            )
    return scored


def merge_scored(first: Sequence[ScoredRow], second: Sequence[ScoredRow]) -> list[ScoredRow]:
    """Union of two scorings of the SAME rows in the SAME order (stage A then stage B)."""
    if len(first) != len(second):
        raise ValueError("scorings cover different row sets")
    merged: list[ScoredRow] = []
    for a, b in zip(first, second, strict=True):
        if (a.station, a.climate_day, a.horizon, a.fold_id) != (
            b.station,
            b.climate_day,
            b.horizon,
            b.fold_id,
        ):
            raise ValueError("scorings are not row-aligned")
        merged.append(
            replace(
                a,
                crps={**a.crps, **b.crps},
                arm_predictions={**a.arm_predictions, **b.arm_predictions},
                champion=a.champion if a.champion is not None else b.champion,
            )
        )
    return merged


def shuffle_labels(rows: Sequence[FeatureRow], *, seed: int) -> list[FeatureRow]:
    """Negative control: permute station-day labels within each NBM version."""
    rng = random.Random(seed)
    keys_by_version: dict[str, list[tuple[str, dt.date]]] = {}
    label: dict[tuple[str, str, dt.date], float] = {}
    for row in rows:
        key = (row.station, row.climate_day)
        if (row.version, *key) not in label:
            label[(row.version, *key)] = row.cli_tmax_f
            keys_by_version.setdefault(row.version, []).append(key)
    permuted: dict[tuple[str, str, dt.date], float] = {}
    for version, keys in keys_by_version.items():
        values = [label[(version, *k)] for k in keys]
        rng.shuffle(values)
        permuted.update({(version, *k): v for k, v in zip(keys, values, strict=True)})
    return [
        replace(row, cli_tmax_f=permuted[(row.version, row.station, row.climate_day)])
        for row in rows
    ]


# ------------------------------------------------------------------ statistics


def mean_arm_crps(scored: Sequence[ScoredRow], arm: str) -> float:
    values = [s.crps[arm] for s in scored if arm in s.crps]
    if not values:
        raise InsufficientRowsError(f"no scored rows carry arm {arm!r}")
    return math.fsum(values) / len(values)


def mean_arm_difference(scored: Sequence[ScoredRow], first: str, second: str) -> float:
    """Mean of ``CRPS(first) - CRPS(second)``; positive means ``second`` is better."""
    values = [
        s.crps[first] - s.crps[second] for s in scored if first in s.crps and second in s.crps
    ]
    if not values:
        raise InsufficientRowsError(f"no scored rows carry both {first!r} and {second!r}")
    return math.fsum(values) / len(values)


def _grouped_difference(
    scored: Sequence[ScoredRow], first: str, second: str, key: Callable[[ScoredRow], Any]
) -> dict[Any, float]:
    groups: dict[Any, list[float]] = {}
    for s in scored:
        if first in s.crps and second in s.crps:
            groups.setdefault(key(s), []).append(s.crps[first] - s.crps[second])
    return {k: math.fsum(v) / len(v) for k, v in groups.items()}


def delta_by_day(
    scored: Sequence[ScoredRow], first: str, second: str
) -> list[tuple[dt.date, float]]:
    """One value per climate day: the mean difference across stations and horizons."""
    return sorted(_grouped_difference(scored, first, second, lambda s: s.climate_day).items())


def per_fold_delta(scored: Sequence[ScoredRow], first: str, second: str) -> dict[int, float]:
    return _grouped_difference(scored, first, second, lambda s: s.fold_id)


def per_station_delta(scored: Sequence[ScoredRow], first: str, second: str) -> dict[str, float]:
    return _grouped_difference(scored, first, second, lambda s: s.station)


def fold_mean_crps(scored: Sequence[ScoredRow], arm: str) -> dict[int, float]:
    groups: dict[int, list[float]] = {}
    for s in scored:
        if arm in s.crps and s.fold_id is not None:
            groups.setdefault(s.fold_id, []).append(s.crps[arm])
    return {k: math.fsum(v) / len(v) for k, v in sorted(groups.items())}


def stationary_bootstrap_means(
    values: Sequence[float], *, mean_block: float, n_boot: int, seed: int
) -> list[float]:
    """Politis-Romano stationary bootstrap of the mean (geometric blocks, circular), ascending.

    No stationary bootstrap exists elsewhere in the repo (``scoring_core`` and ``release_timing``
    resample i.i.d. clusters), so this is the one implementation of it.
    """
    n = len(values)
    if n < 2:
        raise ValueError("a stationary bootstrap needs at least 2 observations")
    if mean_block < 1.0 or n_boot < 1:
        raise ValueError("mean_block must be >= 1 and n_boot >= 1")
    data = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    positions = np.arange(n)
    means = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        fresh = rng.random(n) < 1.0 / mean_block
        fresh[0] = True
        last = np.maximum.accumulate(np.where(fresh, positions, 0))
        starts = rng.integers(0, n, size=n)
        means[i] = data[(starts[last] + positions - last) % n].mean()
    return sorted(float(v) for v in means)


def lower_bound_one_sided(draws: Sequence[float], alpha: float = ALPHA_ONE_SIDED) -> float:
    if not draws:
        raise ValueError("a bound over zero draws is undefined")
    ordered = sorted(draws)
    return ordered[min(len(ordered) - 1, int(alpha * len(ordered)))]


@dataclass(frozen=True, slots=True)
class DeltaSummary:
    mean: float
    lb: float
    n_days: int


def delta_summary(
    day_values: Sequence[tuple[dt.date, float]], *, n_boot: int, seed: int, mean_block: float = 7.0
) -> DeltaSummary:
    ordered = [v for _day, v in sorted(day_values)]
    draws = stationary_bootstrap_means(ordered, mean_block=mean_block, n_boot=n_boot, seed=seed)
    return DeltaSummary(
        mean=math.fsum(ordered) / len(ordered),
        lb=lower_bound_one_sided(draws),
        n_days=len(ordered),
    )


def fold_sd(values: Sequence[float]) -> float:
    if len(values) < 2:
        raise InsufficientFoldsError("a fold-to-fold SD needs at least 2 folds")
    return statistics.stdev(values)


def minimum_effect_floor(m0_fold_crps: Sequence[float], multiple: float | None) -> float:
    """R15: the floor is a pre-registered multiple of the M0 fold-to-fold CRPS SD."""
    if multiple is None or not (math.isfinite(multiple) and multiple > 0.0):
        raise PreregIncompleteError("floor_multiple is not pinned in the prereg")
    return multiple * fold_sd(m0_fold_crps)


def fold_sign_threshold(n_folds: int) -> int:
    """``ceil(0.75 * n_folds)`` in integer arithmetic."""
    return (3 * n_folds + 3) // 4


@dataclass(frozen=True, slots=True)
class M0PrimeStatus:
    within_tolerance: bool
    worse_than_champion: bool
    difference: float


def m0_prime_status(*, m0_crps: float, m0_prime_crps: float, tolerance: float) -> M0PrimeStatus:
    """M0' must not be worse than M0 by more than ``tolerance`` (absolute CRPS, degF)."""
    difference = m0_prime_crps - m0_crps
    return M0PrimeStatus(difference <= tolerance, difference > 0.0, difference)


class Verdict(StrEnum):
    ACCEPT = "ACCEPT"
    NO_SKILL = "NO_SKILL"
    HELD_LEAK_AUDIT = "HELD_LEAK_AUDIT"
    REFUSED_M0PRIME_WORSE = "REFUSED_M0PRIME_WORSE"


@dataclass(frozen=True, slots=True)
class AcceptanceInputs:
    m0p_vs_m3: DeltaSummary
    m0_vs_m3: DeltaSummary
    fold_means_m0p_vs_m3: Sequence[float]
    m0_fold_crps: Sequence[float]
    floor_multiple: float | None
    leak_audit_multiple: float | None
    m0p_minus_m0: float
    m0p_tolerance: float | None
    station_deltas: Mapping[str, float]
    station_tolerance: float | None
    lag_rerun: DeltaSummary | None
    lag_rows_lost: Any


@dataclass(frozen=True, slots=True)
class AcceptanceDecision:
    verdict: Verdict
    reasons: tuple[str, ...]
    report: dict[str, Any]


def _lb_failures(label: str, summary: DeltaSummary, floor: float) -> list[str]:
    failures: list[str] = []
    if not summary.lb > 0.0:
        failures.append(f"{label} one-sided 97.5% lower bound {summary.lb:.4f} is not > 0")
    if summary.lb < floor:
        failures.append(f"{label} lower bound {summary.lb:.4f} is below the floor {floor:.4f}")
    return failures


def decide_acceptance(inputs: AcceptanceInputs) -> AcceptanceDecision:
    """Acceptance 1-8 (R15, R25). Acceptance 9 is the diagnostics report."""
    for name in ("m0p_tolerance", "station_tolerance", "leak_audit_multiple"):
        if getattr(inputs, name) is None:
            raise PreregIncompleteError(f"{name} is not pinned in the prereg")
    assert inputs.m0p_tolerance is not None and inputs.station_tolerance is not None
    assert inputs.leak_audit_multiple is not None
    floor = minimum_effect_floor(inputs.m0_fold_crps, inputs.floor_multiple)
    spread = fold_sd(inputs.m0_fold_crps)
    report: dict[str, Any] = {
        "floor": floor,
        "floor_multiple": inputs.floor_multiple,
        "m0_fold_sd": spread,
        "fold_sign_needed": fold_sign_threshold(len(inputs.fold_means_m0p_vs_m3)),
        "lag_rerun": {
            "mean": None if inputs.lag_rerun is None else inputs.lag_rerun.mean,
            "lb": None if inputs.lag_rerun is None else inputs.lag_rerun.lb,
            "rows_lost": inputs.lag_rows_lost,
        },
    }
    if inputs.m0p_vs_m3.mean > inputs.leak_audit_multiple * spread:
        reason = (
            f"delta {inputs.m0p_vs_m3.mean:.4f} exceeds {inputs.leak_audit_multiple} x the fold "
            f"spread {spread:.4f}: audit for leakage before believing it"
        )
        return AcceptanceDecision(Verdict.HELD_LEAK_AUDIT, (reason,), report)
    if inputs.m0p_minus_m0 > inputs.m0p_tolerance:
        reason = (
            f"M0' is worse than M0 by {inputs.m0p_minus_m0:.4f}, beyond the tolerance "
            f"{inputs.m0p_tolerance}"
        )
        return AcceptanceDecision(Verdict.REFUSED_M0PRIME_WORSE, (reason,), report)
    reasons = _lb_failures("CRPS(M0prime) - CRPS(M3)", inputs.m0p_vs_m3, floor)
    reasons += _lb_failures("CRPS(M0) - CRPS(M3)", inputs.m0_vs_m3, floor)
    positive = sum(1 for v in inputs.fold_means_m0p_vs_m3 if v > 0.0)
    needed = report["fold_sign_needed"]
    if positive < needed:
        reasons.append(
            f"only {positive} of {len(inputs.fold_means_m0p_vs_m3)} folds improve (need {needed})"
        )
    reasons += [
        f"station {station} degraded: mean delta {value:.4f} is below -{inputs.station_tolerance}"
        for station, value in sorted(inputs.station_deltas.items())
        if value < -inputs.station_tolerance
    ]
    if inputs.lag_rerun is None:
        reasons.append("the +60 min lag-sensitivity rerun is absent")
    elif inputs.lag_rerun.lb < 0.0:
        reasons.append(f"lag +60 min rerun lower bound {inputs.lag_rerun.lb:.4f} is below 0")
    verdict = Verdict.NO_SKILL if reasons else Verdict.ACCEPT
    return AcceptanceDecision(verdict, tuple(reasons), report)


# ------------------------------------------------------------------ reporting + gates


@dataclass(frozen=True, slots=True)
class Missingness:
    n: int
    missing: int

    @property
    def share(self) -> float:
        return self.missing / self.n if self.n else 0.0


def lamp_missingness_by_horizon(rows: Sequence[FeatureRow]) -> dict[str, Missingness]:
    out: dict[str, Missingness] = {}
    for horizon in HORIZONS:
        subset = [r for r in rows if r.horizon == horizon]
        if subset:
            out[horizon] = Missingness(len(subset), sum(1 for r in subset if r.lamp.missing))
    return out


def lag_rows_lost(base: Sequence[FeatureRow], shifted: Sequence[FeatureRow]) -> dict[str, int]:
    """Rows whose source is present in ``base`` and absent after the +60 min lag shift."""
    after = {(r.station, r.climate_day, r.horizon): r for r in shifted}
    lost = {"lamp": 0, "pfm": 0, "mos": 0}
    for row in base:
        other = after.get((row.station, row.climate_day, row.horizon))
        if other is None:
            continue
        lost["lamp"] += int(not row.lamp.missing and other.lamp.missing)
        lost["pfm"] += int(row.pfm_mu_f is not None and other.pfm_mu_f is None)
        lost["mos"] += int(row.mos_mu_f is not None and other.mos_mu_f is None)
    return lost


def diagnostics(
    scored: Sequence[ScoredRow], *, arm: str, nu: float, rung_edges: Sequence[int]
) -> dict[str, Any]:
    """Acceptance 9: CRPS by horizon, PIT, 80/95 coverage, rung-ladder log score, RMSE."""
    rows = [s for s in scored if arm in s.arm_predictions]
    if not rows:
        raise InsufficientRowsError(f"no scored rows carry arm {arm!r}")
    edges = [float(e) - 0.5 for e in sorted(rung_edges)]
    pit_bins = [0] * 10
    inside = {0.8: 0, 0.95: 0}
    log_scores: list[float] = []
    squared: list[float] = []
    by_horizon: dict[str, list[float]] = {}
    for s in rows:
        p = s.arm_predictions[arm]
        z = (s.observed_f - p.mu) / p.sigma
        pit_bins[min(9, int(float(stdtr(nu, z)) * 10))] += 1
        for level in inside:
            inside[level] += int(abs(z) <= float(stdtrit(nu, 0.5 + level / 2.0)))
        cdf = blend_cdf(p)
        label = round(s.observed_f) - 0.5
        lower = max((e for e in edges if e <= label), default=None)
        upper = min((e for e in edges if e > label), default=None)
        mass = (1.0 if upper is None else cdf(upper)) - (0.0 if lower is None else cdf(lower))
        log_scores.append(math.log(max(mass, _LOG_FLOOR)))
        squared.append((p.mu - s.observed_f) ** 2)
        by_horizon.setdefault(s.horizon, []).append(s.crps[arm])
    n = len(rows)
    return {
        "arm": arm,
        "n": n,
        "crps_by_horizon": {h: math.fsum(v) / len(v) for h, v in sorted(by_horizon.items())},
        "pit_histogram": pit_bins,
        "coverage_80": inside[0.8] / n,
        "coverage_95": inside[0.95] / n,
        "mean_rung_log_score": math.fsum(log_scores) / n,
        "rmse_descriptive": math.sqrt(math.fsum(squared) / n),
        "rmse_label": "descriptive_only",
    }


def require_c1_measured_lags(
    measured_days: Mapping[str, int],
    *,
    required: Sequence[str],
    min_days: int = 14,
    uncensored: Mapping[str, int] | None = None,
    min_uncensored: int | None = None,
) -> None:
    """Phase A scores only after C1 has measured every source's lag for ``min_days`` days."""
    for source in required:
        days = measured_days.get(source)
        if days is None or days < min_days:
            raise C1LagEvidenceError(
                f"C1 has {days} measured lag days for {source!r}; Phase A needs {min_days}"
            )
        if min_uncensored is not None:
            count = (uncensored or {}).get(source)
            if count is None or count < min_uncensored:
                raise C1LagEvidenceError(
                    f"C1 has {count} uncensored lag samples for {source!r}; needs {min_uncensored}"
                )


# ------------------------------------------------------------------ serialisation


def _percentiles_to_json(p: Percentiles) -> dict[str, float]:
    return {n: getattr(p, n) for n in ("q10", "q25", "q50", "q75", "q90", "mean", "sd")}


def feature_row_to_json(row: FeatureRow) -> dict[str, Any]:
    lamp = row.lamp
    return {
        "station": row.station,
        "climate_day": row.climate_day.isoformat(),
        "version": row.version,
        "horizon": row.horizon,
        "anchor_ns": row.anchor_ns,
        "percentiles": _percentiles_to_json(row.percentiles),
        "cli_tmax_f": row.cli_tmax_f,
        "obs_so_far_f": row.obs_so_far_f,
        "obs_available_at_ns": row.obs_available_at_ns,
        "lamp": {
            "rem_max_f": lamp.rem_max_f,
            "hours_covered": lamp.hours_covered,
            "peak_covered": lamp.peak_covered,
            "missing": lamp.missing,
            "run_available_at_ns": lamp.run_available_at_ns,
            "min_valid_ts_ns": lamp.min_valid_ts_ns,
            "strict_24h_max_f_diagnostic": lamp.strict_24h_max_f_diagnostic,
        },
        "pfm_mu_f": row.pfm_mu_f,
        "pfm_available_at_ns": row.pfm_available_at_ns,
        "mos_mu_f": row.mos_mu_f,
        "mos_available_at_ns": row.mos_available_at_ns,
    }


def feature_row_from_json(data: Mapping[str, Any]) -> FeatureRow:
    return FeatureRow(
        station=data["station"],
        climate_day=dt.date.fromisoformat(data["climate_day"]),
        version=data["version"],
        horizon=data["horizon"],
        anchor_ns=int(data["anchor_ns"]),
        percentiles=Percentiles(**data["percentiles"]),
        cli_tmax_f=data["cli_tmax_f"],
        obs_so_far_f=data["obs_so_far_f"],
        obs_available_at_ns=data["obs_available_at_ns"],
        lamp=LampFeature(**data["lamp"]),
        pfm_mu_f=data["pfm_mu_f"],
        pfm_available_at_ns=data["pfm_available_at_ns"],
        mos_mu_f=data["mos_mu_f"],
        mos_available_at_ns=data["mos_available_at_ns"],
    )


def scored_row_to_json(row: ScoredRow) -> dict[str, Any]:
    champion = row.champion
    return {
        "station": row.station,
        "climate_day": row.climate_day.isoformat(),
        "horizon": row.horizon,
        "version": row.version,
        "fold_id": row.fold_id,
        "observed_f": row.observed_f,
        "crps": dict(row.crps),
        "arm_predictions": {
            k: {"mu": v.mu, "sigma": v.sigma, "nu": v.nu} for k, v in row.arm_predictions.items()
        },
        "champion": None
        if champion is None
        else {
            "method": champion.method,
            "percentiles": _percentiles_to_json(champion.percentiles),
            "a": champion.a,
            "gamma": champion.gamma,
            "delta": champion.delta,
        },
    }


def scored_row_from_json(data: Mapping[str, Any]) -> ScoredRow:
    champion = data["champion"]
    return ScoredRow(
        station=data["station"],
        climate_day=dt.date.fromisoformat(data["climate_day"]),
        horizon=data["horizon"],
        version=data["version"],
        fold_id=data["fold_id"],
        observed_f=data["observed_f"],
        crps=dict(data["crps"]),
        arm_predictions={k: ArmPrediction(**v) for k, v in data["arm_predictions"].items()},
        champion=None
        if champion is None
        else ChampionSpec(
            method=champion["method"],
            percentiles=Percentiles(**champion["percentiles"]),
            a=champion["a"],
            gamma=champion["gamma"],
            delta=champion["delta"],
        ),
    )
