"""F13 Phase A blend, part 5: JSON serialisation of feature rows and scored rows.

Split out of ``breezy.analysis.multisource_blend``; re-exported by that facade.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from breezy.analysis.multisource_blend_features import FeatureRow, LampFeature
from breezy.analysis.multisource_blend_folds import ArmPrediction, ChampionSpec, ScoredRow
from breezy.strategy.ladder_ev.quantile_density import Percentiles


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
        "levels": dict(row.levels),
        "fell_back": list(row.fell_back),
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
        levels={k: int(v) for k, v in data.get("levels", {}).items()},
        fell_back=tuple(data.get("fell_back", ())),
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
