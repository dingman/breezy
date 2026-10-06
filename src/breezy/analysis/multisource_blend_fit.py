"""F13 Phase A blend, part 2: the Student-t blend, its nested ladder cells and its CRPS scoring.

Split out of ``breezy.analysis.multisource_blend``; re-exported by that facade.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln, stdtr

from breezy.analysis.multisource_blend_features import (
    DISAGREEMENT_SD_FLOOR_F,
    FeatureRow,
    FitNotConvergedError,
    InsufficientRowsError,
    _assert_admissible,
)
from breezy.analysis.nbp_calibration import crps_numerical

_RIDGE: Final[float] = 1e-6
_MAX_FIT_ITER: Final[int] = 400
#: Sharpness k of the smooth sigma floor: the floor is exact to within ``ln 2 / k`` degF at the
#: crossing and to ``exp(-k * floor) / k`` far below it.
SIGMA_FLOOR_SHARPNESS: Final[float] = 20.0
_ETA_CLIP: Final[float] = 20.0

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
    #: cells whose optimiser did not converge: dropped, so their rows fall back to a lower cell
    nonconverged: tuple[tuple[int, bool], ...] = ()


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


def floored_sigma(eta: Any, floor: float) -> Any:
    """``sigma`` from ``eta = log sigma`` with a SMOOTH floor (a softplus, never a hard maximum).

    ``floor + softplus_k(exp(eta) - floor)``: always >= ``floor``, strictly increasing in ``eta``
    (so L-BFGS-B always sees a gradient, which a ``max(., floor)`` kink removes) and equal to
    ``exp(eta)`` far above the floor. The fit and :func:`predict_row` both use it.
    """
    raw = np.exp(np.clip(eta, -_ETA_CLIP, _ETA_CLIP))
    return floor + np.logaddexp(0.0, SIGMA_FLOOR_SHARPNESS * (raw - floor)) / SIGMA_FLOOR_SHARPNESS


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
        sigma = floored_sigma(eta, floor)
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
    if not (bool(result.success) and bool(np.all(np.isfinite(theta)))):
        raise FitNotConvergedError(
            f"cell (level={level}, obs={obs}, n={n}) did not converge: {result.message}"
        )
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
    cells: dict[tuple[int, bool], CellParams] = {}
    nonconverged: list[tuple[int, bool]] = []
    for key, members in sorted(groups.items()):
        if len(members) < settings.min_cell_rows:
            continue
        try:
            cells[key] = _fit_cell(members, key[0], key[1], settings)
        except FitNotConvergedError:
            if key[0] == 0:
                raise  # M0' has no cell below it: a silent fallback would score a failed fit
            nonconverged.append(key)
    if not cells:
        raise InsufficientRowsError("no cell reached min_cell_rows")
    return BlendFit(level=level, settings=settings, cells=cells, nonconverged=tuple(nonconverged))


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
    return mu, float(floored_sigma(eta, fit.settings.sigma_floor_f)), level


def intended_level(fit: BlendFit, row: FeatureRow) -> int:
    """The ladder level the row should score at: its present prefix, capped at the fit's level."""
    return min(row.prefix_level, fit.level)


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
