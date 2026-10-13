"""Frozen cell, per-cell re-check, verdict, early stop and horizon sensitivity (r4 delta).

Rules pinned before the binding run. The frozen stop ``(c, t_min, α*)`` is solved at the
``f_kill`` tick count; every binding cell is then re-checked at it (G1, G3, H0 rates).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from scripts.analysis.fq_loss_floor_mc_engine import (
    _criticals,
    _partition,
    _rho,
    _run,
    _seed,
    prepare_mix_groups,
)
from scripts.analysis.fq_loss_floor_mc_gate import (
    DEFAULT_FREEZE,
    DELTAS,
    HORIZON,
    delta_key,
    fully_lost_fraction,
    g1_holds,
    g3_floor,
    inclusive_days,
    keep_probability,
    rate_cal,
    rate_gate,
    repeated_crossing,
    t_low_count,
)
from scripts.analysis.fq_loss_floor_mc_maker_inputs import check_bid_range
from scripts.analysis.fq_loss_floor_mc_maker_templates import (
    BINDING_REPLICATES,
    DEFF_CEILING,
    GRID_BIDS,
    MAKER_SPEC,
    MakerMix,
    MakerRefusal,
    build_maker_groups,
    confirm_mixes,
    maker_floor_config,
    sweep_mixes,
)
from scripts.analysis.fq_loss_floor_mc_report import _median_z, ticking_share
from scripts.analysis.fq_loss_floor_mc_solve import binomial_se, crossing_rate

__all__ = [
    "evaluate_binding",
    "horizon_sensitivity",
    "needs_borderline_rerun",
    "recheck_cell",
    "select_frozen_cell",
    "sweep_early_stop",
    "verdict",
]

HORIZON_NOTE: Final = (
    "capital-conservative; costs power; a tail STOP is terminal STOP, not FAIL, not refutation"
)
_TOL: Final = 1e-9
_NO_RECHECK: Final[dict[str, Any]] = {
    "frozen_c_g1_holds": None,
    "frozen_c_g1": None,
    "frozen_c_g3_by_delta": None,
    "frozen_c_g3_holds": None,
    "frozen_c_h0_rate_by_row": None,
    "frozen_c_h0_ok": None,
}


def verdict(cells_pass: Sequence[bool], cells_kill: Sequence[bool]) -> str:
    """KILL reads the stressed point (``f_kill``); PASS reads the stressed lower bound."""
    if not cells_pass or len(cells_pass) != len(cells_kill):
        raise ValueError("verdict needs equal, non-empty per-cell pass flags")
    if not all(cells_kill):
        return "UNREACHABLE"
    return "REACHABLE" if all(cells_pass) else "UNDERDETERMINED"


def _bracket(b: float) -> tuple[float, ...]:
    for grid in GRID_BIDS:
        if abs(b - grid) < _TOL:
            return (grid,)
    below = max(g for g in GRID_BIDS if g < b)
    above = min(g for g in GRID_BIDS if g > b)
    return (below, above)


def select_frozen_cell(
    cells_kill: Sequence[Mapping[str, Any]], *, b_median: float, k_admitted: int | None
) -> Mapping[str, Any] | None:
    """Binding cell at ``f_kill`` nearest S2's realised (k, b); on a bracket the larger c.

    The larger c is the LESS protective choice; the per-cell re-check is the protection.
    Returns None when no bracketing cell has a solved ``c`` (that cell is a failure).
    """
    check_bid_range(b_median)
    bids, ks = _bracket(b_median), ((k_admitted,) if k_admitted else (1, 2))
    near = [
        cell
        for cell in cells_kill
        if cell["k"] in ks and any(abs(cell["b"] - b) < _TOL for b in bids)
    ]
    if not near:
        raise MakerRefusal(f"no binding cell brackets k={ks}, b={b_median}")
    solved = [cell for cell in near if cell.get("c") is not None]
    return max(solved, key=lambda cell: cell["c"]) if solved else None


def _context(cell: Mapping[str, Any]) -> tuple[Any, Any, Any, Any, Any, Any]:
    mix = MakerMix(**cell["mix"])
    groups = build_maker_groups(mix, n_dates=cell["n_dates"], seed=cell["seed"])
    config = maker_floor_config(groups, mix)
    cleaned = _partition(groups)[0]
    p_cal = keep_probability(
        rate_cal(config.lambda_pool, config.take_rate_lower),
        r_sd=config.r_sd,
        lambda_sd=config.lambda_sd,
    )
    p_gate = keep_probability(
        rate_gate(config.lambda_pool, config.take_rate_lower),
        r_sd=config.r_sd,
        lambda_sd=config.lambda_sd,
    )
    return config, cleaned, prepare_mix_groups(cleaned, "M-pool", s6=False), p_cal, p_gate, mix


def _row_key(row: str, mode: str) -> str:
    return row if mode == "none" else f"{row}-{mode}"


def _binding_rates(
    cell: Mapping[str, Any],
    pooled: Any,
    config: Any,
    p_cal: float,
    c: float,
    t_min: int,
    n_days: int,
) -> tuple[dict[str, float], int]:
    rates: dict[str, float] = {}
    shortest = n_days
    for row, mode in MAKER_SPEC.binding:
        sim = _run(
            pooled,
            replicates=cell["replicates"],
            n_days=n_days,
            p_keep=p_cal,
            seed=_seed(cell["seed"], f"cal|{row}|{mode}|M-pool"),
            row=row,
            config=config,
            rho=_rho(mode, config),
            netting=True,
            persist=MAKER_SPEC.persist_for(mode),
        )
        shortest = min(shortest, *(len(cuts) for cuts in sim.cuts))
        rates[_row_key(row, mode)] = crossing_rate(_criticals(sim, n_days, t_min), c)
    return rates, shortest


def recheck_cell(cell: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
    """G1, G3 and the cell's own H0 crossing rate per binding row, at the frozen (c, t_min, α*)."""
    c, t_min, alpha = frozen["c"], frozen["t_min"], frozen["alpha_star"]
    config, cleaned, pooled, p_cal, p_gate, _mix = _context(cell)
    n_cal = inclusive_days(config.freeze, config.horizon)
    reps = cell["replicates"]
    rates, _ = _binding_rates(cell, pooled, config, p_cal, c, t_min, n_cal)
    se = binomial_se(alpha, reps)
    t_low = t_low_count(n_cal, config.lambda_sd, p_gate, tick_share=ticking_share(cleaned))
    z = _median_z(cleaned, "M-pool", MAKER_SPEC.g1_path)
    t_cross = None if z is None else repeated_crossing(z, c=c, t_min=t_min, t_low=t_low)
    g1 = g1_holds(t_cross, t_low, margin=alpha > 0.10 + 1e-9)
    g3: dict[str, float] = {}
    for delta in DELTAS:
        sim = _run(
            pooled,
            replicates=reps,
            n_days=n_cal,
            p_keep=p_gate,
            seed=_seed(cell["seed"], f"g3|{delta}|M-pool"),
            row="H1",
            config=config,
            delta=delta,
        )
        g3[delta_key(delta)] = crossing_rate(_criticals(sim, n_cal, t_min), c)
    return {
        "frozen_c_g1_holds": g1,
        "frozen_c_g1": {
            "t_cross": t_cross,
            "t_low": t_low,
            "z_worst_feasible": z,
            "fully_lost_fraction": None if z is None else fully_lost_fraction(z, c=c, t_low=t_low),
        },
        "frozen_c_g3_by_delta": g3,
        "frozen_c_g3_holds": g3["-0.16"] + 1e-15 >= g3_floor(alpha),
        "frozen_c_h0_rate_by_row": rates,
        "frozen_c_h0_ok": all(rate <= alpha + 3.0 * se for rate in rates.values()),
    }


def _checked(
    cells: Sequence[Mapping[str, Any]],
    frozen: Mapping[str, Any] | None,
    recheck: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]],
    role: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cell in cells:
        result = dict(_NO_RECHECK)
        own = cell.get("floor_mode") == "sqrt_boundary"
        if own and frozen is not None:
            result.update(recheck(cell, frozen))
        passed = (
            own
            and frozen is not None
            and bool(result["frozen_c_g1_holds"])
            and bool(result["frozen_c_g3_holds"])
            and bool(result["frozen_c_h0_ok"])
        )
        out.append({**cell, **result, "f_role": role, "frozen_c_pass": passed})
    return out


def evaluate_binding(
    cells_kill: Sequence[Mapping[str, Any]],
    cells_pass: Sequence[Mapping[str, Any]],
    *,
    b_median: float,
    k_admitted: int | None,
    recheck: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]] = recheck_cell,
) -> dict[str, Any]:
    """Freeze at the f_kill cell nearest S2, re-check every cell at both f, then the verdict."""
    chosen = select_frozen_cell(cells_kill, b_median=b_median, k_admitted=k_admitted)
    frozen = (
        None
        if chosen is None
        else {"c": chosen["c"], "t_min": chosen["t_min"], "alpha_star": chosen["alpha_star"]}
    )
    kill = _checked(cells_kill, frozen, recheck, "f_kill")
    passing = _checked(cells_pass, frozen, recheck, "f_pass")
    return {
        "verdict": verdict(
            [cell["frozen_c_pass"] for cell in passing], [cell["frozen_c_pass"] for cell in kill]
        ),
        "frozen_cell": None
        if chosen is None
        else {"k": chosen["k"], "b": chosen["b"], "f_kill": chosen["f"]},
        "frozen_c": None if frozen is None else frozen["c"],
        "frozen_c_deff": None if frozen is None else frozen["c"] / math.sqrt(DEFF_CEILING),
        "frozen_t_min": None if frozen is None else frozen["t_min"],
        "frozen_alpha_star": None if frozen is None else frozen["alpha_star"],
        "frozen_certified_ticks": None if chosen is None else chosen["certified_ticks"],
        "cells": [*kill, *passing],
    }


def needs_borderline_rerun(cell: Mapping[str, Any]) -> bool:
    """``|G3(-0.16) - 2.5 α*| < 2 binomial SE`` at the cell's replicate count."""
    alpha, g3 = cell.get("alpha_star"), (cell.get("g3_by_delta") or {}).get("-0.16")
    if alpha is None or g3 is None:
        return False
    se = binomial_se(min(1.0, max(0.0, g3)), cell["replicates"])
    return bool(abs(g3 - g3_floor(alpha)) < 2.0 * se)


def sweep_early_stop(
    sweep_cells: Sequence[Mapping[str, Any]], confirm: Callable[[MakerMix], Mapping[str, Any]]
) -> dict[str, Any] | None:
    """All 30 cells veto, then six f = 0.5 cells confirm at 10k. freeze_blocked never counts."""
    if len(sweep_cells) != len(sweep_mixes()):
        raise ValueError(f"expected {len(sweep_mixes())} sweep cells, got {len(sweep_cells)}")

    def vetoed(cells: Sequence[Mapping[str, Any]]) -> bool:
        return all(
            c.get("freeze_blocked") is None and c["floor_mode"] == "unreachable_veto" for c in cells
        )

    if not vetoed(sweep_cells):
        return None
    if not vetoed([confirm(mix) for mix in confirm_mixes()]):
        return None
    return {
        "early_stop": "sweep_all_veto",
        "early_stop_basis": {"f_max": 0.5, "beta": 1.0, "replicates": BINDING_REPLICATES},
    }


def horizon_sensitivity(
    cell: Mapping[str, Any],
    frozen: Mapping[str, Any],
    *,
    l_cap: int,
    holdout_start: str | None = None,
    cap_date: str | None = None,
) -> dict[str, Any]:
    """Re-simulate the frozen cell to ``L_cap`` dates; crossing rates only, no gates, no solve."""
    config, cleaned, pooled, p_cal, p_gate, _mix = _context(cell)
    rates, shortest = _binding_rates(
        cell, pooled, config, p_cal, frozen["c"], frozen["t_min"], l_cap
    )
    if shortest < l_cap:
        raise RuntimeError(f"simulated {shortest} dates, fewer than L_cap {l_cap}")
    ticks = t_low_count(l_cap, config.lambda_sd, p_gate, tick_share=ticking_share(cleaned))
    return {
        "report_only": True,
        "freeze": DEFAULT_FREEZE.isoformat(),
        "L_cap": l_cap,
        "holdout_start_date": holdout_start,
        "calendar_cap_date": cap_date,
        "seed": cell["seed"],
        "replicates": cell["replicates"],
        "frozen_c": frozen["c"],
        "frozen_t_min": frozen["t_min"],
        "false_stop_rate_by_row": rates,
        "worst_binding_row_rate": max(rates.values()),
        "certified_ticks_at_cap": ticks,
        "min_simulated_days": shortest,
        "note": HORIZON_NOTE,
        "certified_window_end": HORIZON.isoformat(),
    }
