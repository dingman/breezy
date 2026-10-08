"""Natural λ_pool, then a separate strict calibration for each target rate."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from scripts.analysis import fq_mc_livedata as livedata
from scripts.analysis.fq_loss_floor_mc_gate import POOL_EXIT_FRACTION_SOURCE, rate_cal, rate_gate
from scripts.analysis.fq_mc_livedata import DayTemplate, PoolDay

__all__ = [
    "LAMBDA_POOL_DEFINITION",
    "POOL_EXIT_FRACTION_SOURCE",
    "PlannedRates",
    "plan_floor_rates",
]

LAMBDA_POOL_DEFINITION = (
    "mean takes per climate day of build_templates at the model view's default "
    "pi_fav (DEFAULT_PI_FAV) on the sampled pre-holdout pool, measured before "
    "any take-rate bisection"
)


def _mean_takes(templates: Sequence[DayTemplate]) -> float:
    if not templates:
        return 0.0
    return float(np.mean([template.n for template in templates]))


def _ratios(templates: Sequence[DayTemplate]) -> tuple[float, float]:
    takes = sum(template.n for template in templates)
    stations = sum(len({take.station for take in template.takes}) for template in templates)
    days = len(templates)
    r_sd = (takes / stations) if stations else 1.0
    lambda_sd = (stations / days) if days and stations else 1.0
    return r_sd, lambda_sd


def _keep_raw(rate: float, r_sd: float, lambda_sd: float) -> float:
    return (rate / r_sd) / lambda_sd


@dataclass(frozen=True, slots=True)
class PlannedRates:
    lambda_pool: float
    rate_cal: float
    rate_gate: float
    achieved_rate_cal: float
    achieved_rate_gate: float
    pi_cal: float
    pi_gate: float
    p_keep_cal: float
    p_keep_gate: float
    p_keep_cal_raw: float
    p_keep_gate_raw: float
    r_sd_cal: float
    lambda_sd_cal: float
    r_sd_gate: float
    lambda_sd_gate: float
    cal_templates: tuple[DayTemplate, ...]
    gate_templates: tuple[DayTemplate, ...]
    definition: str = LAMBDA_POOL_DEFINITION


def plan_floor_rates(
    days: Sequence[PoolDay],
    *,
    take_rate_lower: float,
    seed: int,
) -> PlannedRates:
    """Measure λ_pool at the default π, then bisect π separately for each target."""
    natural = livedata.build_templates(days, seed=seed)
    lambda_pool = _mean_takes(natural)
    target_cal = rate_cal(lambda_pool, take_rate_lower)
    target_gate = rate_gate(lambda_pool, take_rate_lower)
    pi_cal, calibrated = livedata.calibrate_take_rate(
        days, target_rate=target_cal, seed=seed, require_reachable=True
    )
    if target_gate == target_cal:
        pi_gate, gated = pi_cal, calibrated
    else:
        pi_gate, gated = livedata.calibrate_take_rate(
            days, target_rate=target_gate, seed=seed, require_reachable=True
        )
    raw_cal_r, raw_cal_l = _ratios(calibrated)
    raw_gate_r, raw_gate_l = _ratios(gated)
    raw_cal = _keep_raw(target_cal, raw_cal_r, raw_cal_l)
    raw_gate = _keep_raw(target_gate, raw_gate_r, raw_gate_l)
    return PlannedRates(
        lambda_pool=lambda_pool,
        rate_cal=target_cal,
        rate_gate=target_gate,
        achieved_rate_cal=_mean_takes(calibrated),
        achieved_rate_gate=_mean_takes(gated),
        pi_cal=pi_cal,
        pi_gate=pi_gate,
        p_keep_cal=min(1.0, raw_cal),
        p_keep_gate=min(1.0, raw_gate),
        p_keep_cal_raw=raw_cal,
        p_keep_gate_raw=raw_gate,
        r_sd_cal=raw_cal_r,
        lambda_sd_cal=raw_cal_l,
        r_sd_gate=raw_gate_r,
        lambda_sd_gate=raw_gate_l,
        cal_templates=tuple(calibrated),
        gate_templates=tuple(gated),
    )
