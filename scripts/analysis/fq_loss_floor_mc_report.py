"""JSON rows and the per-α solve for the floor MC."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence

import numpy as np

from breezy.analysis.fq_loss_stop_core import T_MIN_GRID, VARIANCE_EPS
from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay
from scripts.analysis.fq_loss_floor_mc_gate import (
    DELTAS,
    AlphaEval,
    FloorConfig,
    FloorOutcome,
    choose_t_min,
    delta_key,
    epoch_holds,
    fully_lost_fraction,
    g1_holds,
    repeated_crossing,
    t_low_count,
)
from scripts.analysis.fq_loss_floor_mc_rows import (
    StationDay,
    all_lose_z,
    apply_mix,
    clamped_leg_share,
    production_variance,
    rho_bind,
    template_overround,
)
from scripts.analysis.fq_loss_floor_mc_sim import Simulation
from scripts.analysis.fq_loss_floor_mc_solve import (
    binding_max,
    binomial_se,
    bootstrap_c_se,
    crossing_rate,
    single_day_share,
    smallest_grid_c,
)

__all__ = ["append_rows", "evaluate_alpha", "finish_document"]

Power = Callable[[float, str, int, int, float], float]
MIXES: tuple[str, ...] = ("M-pool", "M-yes", "M-no")
_CAL: tuple[tuple[str, str], ...] = (
    ("H0", "none"),
    ("S1", "none"),
    ("S2", "none"),
    ("S4", "none"),
    ("S5", "bind"),
    ("S5", "half"),
    ("S6", "none"),
)
_BINDING: frozenset[tuple[str, str]] = frozenset({("H0", "none"), ("S4", "none"), ("S5", "bind")})


def _seed(master: int, label: str) -> int:
    digest = hashlib.sha256(f"{master}|{label}".encode()).digest()
    return int.from_bytes(digest[:4], "little")


def _median_z(groups: Sequence[Sequence[StationDay]], mix: str) -> float | None:
    scores = [
        z for group in groups for day in group if (z := all_lose_z(apply_mix(day, mix))) is not None
    ]
    if not scores:
        return None
    scores.sort()
    return scores[len(scores) // 2]


def _rho(mode: str, config: FloorConfig) -> float | None:
    if mode == "bind":
        return rho_bind(config.rho_hat)
    if mode == "half":
        return 0.5
    return None


def append_rows(
    rows: list[dict[str, object]],
    cal_sims: Mapping[tuple[str, str, str], Simulation],
    crit: Callable[[Simulation, int, int], np.ndarray],
    alpha: float,
    t_min: int,
    solved: float,
    n_cal: int,
    replicates: int,
    config: FloorConfig,
) -> None:
    """Per-cell crossing rate at the solved ``c``, plus the S3 single-day share."""
    for row, mode in _CAL:
        rho = _rho(mode, config)
        for mix in MIXES:
            sim = cal_sims[(row, mode, mix)]
            drawn = crit(sim, n_cal, t_min)
            rate = crossing_rate(drawn, solved)
            rows.append(
                {
                    "row": row,
                    "mix": mix,
                    "role": "binding" if (row, mode) in _BINDING else "report",
                    "alpha": alpha,
                    "t_min": t_min,
                    "rho": rho,
                    "rate": rate,
                    "se": binomial_se(rate, replicates),
                    "c_cell": smallest_grid_c(drawn, alpha),
                    "multi_tick_share": sim.multi_tick_share if row == "S5" else None,
                }
            )
            if row == "H0":
                rows.append(
                    {
                        "row": "S3",
                        "mix": mix,
                        "role": "report",
                        "alpha": alpha,
                        "t_min": t_min,
                        "single_day_share": single_day_share(sim.paths, c=solved, t_min=t_min),
                    }
                )


def evaluate_alpha(
    *,
    alpha: float,
    cal_sims: Mapping[tuple[str, str, str], Simulation],
    crit: Callable[[Simulation, int, int], np.ndarray],
    power: Power,
    n_cal: int,
    replicates: int,
    config: FloorConfig,
    lengths: Mapping[str, int],
    p_gate: float,
    cleaned: Sequence[Sequence[StationDay]],
    feasible: Mapping[str, Sequence[Sequence[PreparedDay]]],
    seed: int,
    rows: list[dict[str, object]],
    gates: list[dict[str, object]],
) -> tuple[AlphaEval, tuple[str, str]]:
    """Solve ``c`` and the epoch gates for one α. Appends to ``rows`` and ``gates``."""
    by_t: dict[int, tuple[float, tuple[str, str]]] = {}
    scores: dict[int, float] = {}
    for t_min in T_MIN_GRID:
        cells: dict[tuple[str, str], float] = {}
        for row, mode in _CAL:
            if (row, mode) not in _BINDING:
                continue
            for mix in MIXES:
                drawn = crit(cal_sims[(row, mode, mix)], n_cal, t_min)
                cells[(row, mix)] = smallest_grid_c(drawn, alpha)
        solved, cell = binding_max(cells)
        by_t[t_min] = (solved, cell)
        scores[t_min] = min(power(-0.16, mix, n_cal, t_min, solved) for mix in MIXES)
    t_star = choose_t_min(scores, set(by_t))
    solved, cell = by_t[t_star]
    binding_draws = {
        (row, mix): crit(cal_sims[(row, mode, mix)], n_cal, t_star)
        for row, mode in _CAL
        if (row, mode) in _BINDING
        for mix in MIXES
    }
    c_se = bootstrap_c_se(binding_draws, alpha=alpha, seed=_seed(seed, f"boot|{alpha}"))
    s6_rates = [
        crossing_rate(crit(cal_sims[("S6", "none", mix)], n_cal, t_star), solved)
        for mix in MIXES
        if any(prep.day.legs for group in feasible[mix] for prep in group)
    ]
    s6_rate = max(s6_rates) if s6_rates else 1.0
    s6_se = binomial_se(s6_rate, replicates) if s6_rates else 0.0
    freeze_key = config.freeze.isoformat()
    measured = {
        delta_key(delta): min(
            power(delta, mix, lengths[freeze_key], t_star, solved) for mix in MIXES
        )
        for delta in DELTAS
    }
    epoch_ok: dict[str, bool] = {}
    g1_pass = False
    g1_margin = False
    for epoch, n_days in lengths.items():
        t_low = t_low_count(n_days, config.lambda_sd, p_gate)
        passes: list[bool] = []
        margins: list[bool] = []
        g3_epoch: list[float] = []
        for mix in MIXES:
            z = _median_z(cleaned, mix)
            t_cross = (
                None if z is None else repeated_crossing(z, c=solved, t_min=t_star, t_low=t_low)
            )
            passed = g1_holds(t_cross, t_low, margin=False)
            margin = g1_holds(t_cross, t_low, margin=True)
            passes.append(passed)
            margins.append(margin)
            g3_values = {
                delta_key(delta): power(delta, mix, n_days, t_star, solved) for delta in DELTAS
            }
            g3_epoch.append(g3_values["-0.16"])
            f_star = None if z is None else fully_lost_fraction(z, c=solved, t_low=t_low)
            gates.append(
                {
                    "alpha": alpha,
                    "epoch": epoch,
                    "mix": mix,
                    "t_min": t_star,
                    "c": solved,
                    "t_low": t_low,
                    "t_cross": t_cross,
                    "g1": passed,
                    "g1_margin": margin,
                    "f_star": f_star,
                    "g3": g3_values,
                }
            )
        epoch_ok[epoch] = epoch_holds(
            g1_pass=all(passes),
            g1_margin=all(margins),
            g3=min(g3_epoch),
            alpha=alpha,
        )
        if epoch == freeze_key:
            g1_pass = all(passes)
            g1_margin = all(margins)
    evaluation = AlphaEval(
        alpha=alpha,
        g1_pass=g1_pass,
        g1_margin=g1_margin,
        g3_at_m016=measured["-0.16"],
        s6_rate=s6_rate,
        s6_se=s6_se,
        c=solved,
        c_se=c_se,
        t_min=t_star,
        measured_power=measured,
        epoch_ok=epoch_ok,
    )
    append_rows(rows, cal_sims, crit, alpha, t_star, solved, n_cal, replicates, config)
    return evaluation, cell


def finish_document(
    *,
    seed: int,
    replicates: int,
    outcome: FloorOutcome,
    rows: Sequence[Mapping[str, object]],
    gates: Sequence[Mapping[str, object]],
    refused_count: int,
    refused_templates: Sequence[Mapping[str, object]],
    binding_cell: list[str] | None,
    carry_ratio: float,
    mean_carry: float,
    admitted: Sequence[StationDay],
    script_git_sha: str | None,
    parent_sha: str | None,
    a0_sha: str | None,
    git_head: str | None,
) -> dict[str, object]:
    over_share, mean_kappa = template_overround(admitted)
    paired = [day.netting for day in admitted if day.netting != 0.0]
    legs = [leg for day in admitted for leg in day.legs]
    return {
        "seed": seed,
        "replicates": replicates,
        "outcome": outcome.as_dict(),
        "rows": list(rows),
        "gates": list(gates),
        "refused_count": refused_count,
        "refused_templates": list(refused_templates),
        "binding_cell": binding_cell,
        "max_abs_carry_over_sigma_next": carry_ratio,
        "mean_carry": mean_carry,
        "zero_sigma_days": sum(1 for day in admitted if production_variance(day) <= VARIANCE_EPS),
        "overround_share": over_share,
        "mean_kappa": mean_kappa,
        "netting_pair_share": (len(paired) / len(admitted)) if admitted else 0.0,
        "mean_delta_net": (sum(paired) / len(paired)) if paired else None,
        "clamped_leg_share": {
            delta_key(delta): clamped_leg_share(legs, delta=delta) for delta in DELTAS
        },
        "script_git_sha": script_git_sha,
        "parent_sha": parent_sha,
        "a0_sha": a0_sha,
        "git_head": git_head,
    }
