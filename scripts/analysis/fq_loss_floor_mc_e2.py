"""E-2 pieces: veto completion, the max-rate sensitivity c, the blank document."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date

import numpy as np

from breezy.analysis.fq_loss_stop_core import ALPHA_FLOOR_GRID
from scripts.analysis.fq_loss_floor_mc_gate import AlphaEval, FloorOutcome, epoch_grid
from scripts.analysis.fq_loss_floor_mc_rows import RefusedTemplate
from scripts.analysis.fq_loss_floor_mc_solve import binding_max, smallest_grid_c

__all__ = ["blank_document", "complete_veto", "finish_e2", "refused_names", "sensitivity_c"]

_MIX_ORDER: tuple[str, ...] = ("M-pool", "M-yes", "M-no")
_G3_KEYS: tuple[str, ...] = ("-0.16", "-0.08", "-0.04")


def refused_names(refused: Sequence[RefusedTemplate]) -> list[dict[str, object]]:
    return [
        {
            "station": item.station,
            "rungs": list(item.rungs),
            "reason": item.reason,
            "detail": item.detail,
        }
        for item in refused
    ]


def blank_document(
    refused: Sequence[RefusedTemplate], *, seed: int, replicates: int
) -> dict[str, object]:
    detail = f"{len(refused)} station-day template(s) refused"
    if not refused:
        detail = "no admitted station-day remains after the template partition"
    outcome = FloorOutcome(
        None,
        "none",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        freeze_blocked={"reason": "refused_templates", "detail": detail},
    )
    return {
        "seed": seed,
        "replicates": replicates,
        "outcome": outcome.as_dict(),
        "rows": [],
        "gates": [],
        "refused_count": len(refused),
        "refused_templates": refused_names(refused),
        "max_abs_carry_over_sigma_next": 0.0,
        "binding_cell": None,
    }


def sensitivity_c(
    *,
    same_rate: bool,
    bound_c: float,
    alpha: float,
    binding: Sequence[tuple[str, str]],
    mixes: Sequence[str],
    run_cell: Callable[[str, str, str], np.ndarray],
) -> float:
    """c at ``max(λ_pool, take_rate_lower)``. Re-solves only when that rate differs."""
    if same_rate:
        return bound_c
    cells: dict[tuple[str, str], float] = {}
    for row, mode in binding:
        for mix in mixes:
            cells[(row, mix)] = smallest_grid_c(run_cell(row, mode, mix), alpha)
    solved, _winner = binding_max(cells)
    return solved


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a number, got {value!r}")
    return float(value)


def _g3(row: Mapping[str, object]) -> dict[str, float]:
    raw = row.get("g3")
    if not isinstance(raw, dict):
        raise TypeError("g3 must be a mapping")
    return {key: _number(raw.get(key), key) for key in _G3_KEYS}


def _rows_at(
    gates: Sequence[Mapping[str, object]], *, alpha: float, epoch: str
) -> dict[str, Mapping[str, object]]:
    found: dict[str, Mapping[str, object]] = {}
    for row in gates:
        if row.get("epoch") != epoch:
            continue
        if not math.isclose(_number(row.get("alpha"), "alpha"), alpha, abs_tol=1e-9):
            continue
        mix = row.get("mix")
        if not isinstance(mix, str):
            raise TypeError(f"gate mix must be a string, got {mix!r}")
        found[mix] = row
    missing = [mix for mix in _MIX_ORDER if mix not in found]
    if missing:
        raise ValueError(f"gate rows missing {missing} at alpha {alpha} epoch {epoch}")
    return found


def _flag(rows: Mapping[str, Mapping[str, object]], mix: str, flag: str) -> bool:
    value = rows[mix].get(flag)
    if not isinstance(value, bool):
        raise TypeError(f"{flag} for {mix} must be bool, got {value!r}")
    return value


def _measured(
    gates: Sequence[Mapping[str, object]], *, alpha: float, epoch: str
) -> dict[str, float]:
    rows = _rows_at(gates, alpha=alpha, epoch=epoch)
    return {key: min(_g3(rows[mix])[key] for mix in _MIX_ORDER) for key in _G3_KEYS}


def _failing_mix(
    outcome: FloorOutcome,
    gates: Sequence[Mapping[str, object]],
    epoch: str,
) -> str:
    if outcome.veto_cause == "g3_floor":
        alpha = outcome.alpha_star
        if alpha is None:
            raise ValueError("g3_floor veto is missing alpha_star")
        rows = _rows_at(gates, alpha=alpha, epoch=epoch)
        scores = {mix: _g3(rows[mix])["-0.16"] for mix in _MIX_ORDER}
        return min(_MIX_ORDER, key=lambda mix: (scores[mix], _MIX_ORDER.index(mix)))
    for alpha in ALPHA_FLOOR_GRID:
        rows = _rows_at(gates, alpha=alpha, epoch=epoch)
        flag = "g1" if math.isclose(alpha, ALPHA_FLOOR_GRID[0], abs_tol=1e-9) else "g1_margin"
        failed = [mix for mix in _MIX_ORDER if not _flag(rows, mix, flag)]
        if failed:
            return failed[0]
    raise ValueError("g1_unreachable veto has no failing mix on the ladder")


def _ladder_start(evals: Sequence[AlphaEval]) -> AlphaEval:
    alpha0 = ALPHA_FLOOR_GRID[0]
    for item in evals:
        if math.isclose(item.alpha, alpha0, abs_tol=1e-9):
            return item
    raise ValueError("veto diagnostics need an evaluation at the ladder start")


def finish_e2(
    outcome: FloorOutcome,
    *,
    rows: list[dict[str, object]],
    adjusted: Sequence[AlphaEval],
    gates: Sequence[Mapping[str, object]],
    freeze: date,
    grid_last: float,
    max_rate: float,
    cal_rate: float,
    refused: bool,
    refused_detail: str,
    mixes: Sequence[str],
    run_at: Callable[[str, str, str, int], np.ndarray],
) -> FloorOutcome:
    """Append the max-rate sensitivity c, fill a veto, then apply a refusal block."""
    final_alpha = outcome.alpha_star if outcome.alpha_star is not None else grid_last
    final_eval = next(
        item for item in adjusted if math.isclose(item.alpha, final_alpha, abs_tol=1e-9)
    )
    t_min = final_eval.t_min

    def _cell(row: str, mode: str, mix: str) -> np.ndarray:
        return run_at(row, mode, mix, t_min)

    rows.append(
        {
            "row": "cal_at_max_rate",
            "role": "sensitivity",
            "alpha": final_alpha,
            "c": sensitivity_c(
                same_rate=math.isclose(max_rate, cal_rate),
                bound_c=final_eval.c,
                alpha=final_alpha,
                binding=(("H0", "none"), ("S4", "none"), ("S5", "bind")),
                mixes=mixes,
                run_cell=_cell,
            ),
        }
    )
    if outcome.floor_mode == "unreachable_veto":
        outcome = complete_veto(outcome, gates=gates, evals=adjusted, freeze=freeze)
    if not refused:
        return outcome
    return replace(
        outcome,
        floor_mode=None,
        power_class="none",
        c=None,
        c_mc_se=None,
        t_min=None,
        veto_cause=None,
        failing_mix=None,
        diagnostics=None,
        reach_cutoff_epoch_start=None,
        freeze_blocked={"reason": "refused_templates", "detail": refused_detail},
    )


def complete_veto(
    outcome: FloorOutcome,
    *,
    gates: Sequence[Mapping[str, object]],
    evals: Sequence[AlphaEval],
    freeze: date,
) -> FloorOutcome:
    """Fill power, the failing mix, and α=0.10 diagnostics. Those are not pins."""
    if outcome.floor_mode != "unreachable_veto":
        return outcome
    alpha0 = ALPHA_FLOOR_GRID[0]
    epoch = epoch_grid(freeze)[0].isoformat()
    start = _ladder_start(evals)
    diagnostics: dict[str, float | int] = {
        "alpha": alpha0,
        "c": start.c,
        "t_min": start.t_min,
        "c_mc_se_total": start.c_se,
        "s6": start.s6_rate,
    }
    return replace(
        outcome,
        c=None,
        c_mc_se=None,
        t_min=None,
        measured_power=_measured(gates, alpha=alpha0, epoch=epoch),
        failing_mix=_failing_mix(outcome, gates, epoch),
        diagnostics=diagnostics,
    )
