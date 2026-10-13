"""Artifact assembly for the maker S3 floor: verdict, certified object, O-6 window label."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, Final

from scripts.analysis.fq_loss_floor_mc_gate import (
    DEFAULT_FREEZE,
    HORIZON,
    FloorConfig,
    inclusive_days,
)
from scripts.analysis.fq_loss_floor_mc_maker_templates import DEFF_CEILING, MakerMix

__all__ = ["assemble_artifact", "cell_summary", "window_label"]

_RULING: Final = "RULING_MAKER-S3_loss_stop_window_2026-10-13"
_STATEMENTS: Final = (
    (
        "The inflation is a uniform sigma rescale that cancels exactly because c is re-solved on "
        "H0; S5 freezes (sigma*sqrt(1.5), frozen_c_deff). A uniform rescale cannot protect against "
        "clustering: protection is in the H0 calibration rows (S5 copula rho 0.5, S8 persistence, "
        "beta-binomial fills at FILL_ICC >= 0.5/7)."
    ),
    (
        "REACHABLE is conditional on station persistence no worse than (L=3, rho_p=0.5); "
        "S9 (5, 0.9) is a printed stress."
    ),
    (
        "The frozen c is solved at the f_kill tick count; real ticks above it raise the false-stop "
        "rate as the tail does. The verdict deliberately couples to b cells S2 never realised."
    ),
    "theta basis: taker 0.0695 (the maker rebate is refused); theta 0.08 is report-only.",
)


def window_label(frozen_cell: Mapping[str, Any], ticks: object, c_deff: object) -> str:
    """The ruling O-6 string, with the placeholders filled."""
    return (
        "window = FQ v2 window 2026-10-08..2027-01-25 used as a 110-climate-date label; "
        "certified_horizon_climate_days = 110; "
        f"certified_ticks = {ticks}; "
        f"frozen cell = {frozen_cell['k']}, {frozen_cell['b']}, {frozen_cell['f_kill']}; "
        f"frozen_c_deff = {c_deff}; see {_RULING}"
    )


def assemble_artifact(
    evaluation: Mapping[str, Any],
    *,
    report_cells: Sequence[Mapping[str, Any]] = (),
    horizon: Mapping[str, Any] | None = None,
    early_stop: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verdict, certified object and cells. Report cells and the horizon never enter the verdict."""
    frozen = evaluation["frozen_cell"]
    art: dict[str, Any] = {
        "verdict": "UNREACHABLE" if early_stop else evaluation["verdict"],
        "certified_horizon_climate_days": inclusive_days(DEFAULT_FREEZE, HORIZON),
        "certified_ticks": evaluation["frozen_certified_ticks"],
        "frozen_cell": frozen,
        "frozen_c": evaluation["frozen_c"],
        "frozen_c_deff": evaluation["frozen_c_deff"],
        "frozen_t_min": evaluation["frozen_t_min"],
        "frozen_alpha_star": evaluation["frozen_alpha_star"],
        "window_label": None
        if frozen is None
        else window_label(
            frozen, evaluation["frozen_certified_ticks"], evaluation["frozen_c_deff"]
        ),
        "cells": list(evaluation["cells"]),
        "report_cells": list(report_cells),
        "horizon_sensitivity": None if horizon is None else dict(horizon),
        "statements": list(_STATEMENTS),
    }
    if early_stop:
        art.update(early_stop)
    if provenance:
        art["provenance"] = dict(provenance)
    return art


def _by_row(rows: Sequence[Mapping[str, Any]], role: str) -> dict[str, float]:
    return {r["row"]: r["rate"] for r in rows if r["role"] == role}


def cell_summary(
    doc: Mapping[str, Any],
    mix: MakerMix,
    config: FloorConfig,
    *,
    replicates: int,
    seed: int,
    n_dates: int,
) -> dict[str, Any]:
    """Compact cell record from a ``run_floor`` document; adds ``c_deff = c / sqrt(1.5)``."""
    out = doc["outcome"]
    alpha = out["alpha_star"]
    gates = [g for g in doc["gates"] if alpha is None or g["alpha"] == alpha]
    epoch0 = next((g for g in gates if g["epoch"] == config.freeze.isoformat()), {})
    first_alpha = gates[0]["alpha"] if gates else None
    rows = [r for r in doc["rows"] if "rate" in r and (alpha is None or r["alpha"] == alpha)]
    c = out["c"]
    g1_keys = ("t_cross", "g1", "g1_margin", "f_star", "z_g1", "z_all_lose")
    return {
        "k": mix.rungs,
        "b": mix.bid,
        "f": mix.fill_rate,
        "theta": mix.theta,
        "mix": asdict(mix),
        "replicates": replicates,
        "seed": seed,
        "n_dates": n_dates,
        "floor_mode": out["floor_mode"],
        "power_class": out["power_class"],
        "alpha_star": alpha,
        "c": c,
        "c_mc_se": out["c_mc_se"],
        "t_min": out["t_min"],
        "c_deff": None if c is None else c / math.sqrt(DEFF_CEILING),
        "veto_cause": out["veto_cause"],
        "failing_mix": out["failing_mix"],
        "freeze_blocked": out["freeze_blocked"],
        "g3_by_delta": out["measured_power"],
        "certified_ticks": epoch0.get("t_low"),
        "t_low_by_epoch": {g["epoch"]: g["t_low"] for g in gates if g["alpha"] == first_alpha},
        "g1": {key: epoch0.get(key) for key in g1_keys},
        "binding_rates": _by_row(rows, "binding"),
        "report_rates": _by_row(rows, "report"),
        "h1_fallback_share_by_delta": {
            key: value["share"] for key, value in doc["h1_bernoulli_fallback"].items()
        },
        "lambda_sd": config.lambda_sd,
        "p_keep_gate": doc["p_keep_gate"],
        "tick_share": doc["tick_share"],
    }
