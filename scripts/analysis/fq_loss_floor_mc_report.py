"""JSON rows and the per-α solve for the floor MC."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence

import numpy as np

from breezy.analysis.fq_loss_stop_core import T_MIN_GRID, VARIANCE_EPS, FqLossStopRefusal
from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay, prepare_day, with_s7_skips
from scripts.analysis.fq_loss_floor_mc_gate import (
    DELTAS,
    FQ_CAL,
    FQ_SPEC,
    AlphaEval,
    FloorConfig,
    FloorOutcome,
    FloorSpec,
    choose_t_min,
    delta_key,
    epoch_holds,
    fully_lost_fraction,
    g1_holds,
    rate_cal,
    rate_gate,
    repeated_crossing,
    t_low_count,
)
from scripts.analysis.fq_loss_floor_mc_rates import LAMBDA_POOL_DEFINITION
from scripts.analysis.fq_loss_floor_mc_rows import (
    StationDay,
    all_lose_z,
    apply_mix,
    clamped_leg_share,
    production_variance,
    rho_bind,
    template_overround,
    worst_feasible_z,
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

__all__ = [
    "all_lose_by_mix",
    "append_rows",
    "evaluate_alpha",
    "finish_document",
    "h1_fallback_table",
    "h1_warning_lines",
    "kappa_fallback_share",
    "stamp_run",
    "ticking_share",
]

T_LOW_DEFINITION = (
    "expected station-days whose production variance exceeds VARIANCE_EPS, "
    "at rate_gate (not every station-day)"
)
C_TEMPLATE_RESAMPLE = (
    "bootstrap resamples of calendar-day templates with replacement; "
    "station-days stay inside their sampled template"
)

Power = Callable[[float, str, int, int, float], float]
# FQ defaults, pinned by WP0. A run reads its own FloorSpec; these stay the FQ values.
MIXES: tuple[str, ...] = FQ_SPEC.mixes
_CAL: tuple[tuple[str, str], ...] = FQ_CAL
_BINDING: frozenset[tuple[str, str]] = frozenset(FQ_SPEC.binding)


def _seed(master: int, label: str) -> int:
    digest = hashlib.sha256(f"{master}|{label}".encode()).digest()
    return int.from_bytes(digest[:4], "little")


def _day_z(day: StationDay, path: str) -> float | None:
    if path == "all_lose":
        return all_lose_z(day)
    try:
        return worst_feasible_z(day, prepare_day(day).xs)
    except FqLossStopRefusal:
        return None  # the sim drops the same day (clock_block)


def _median_z(
    groups: Sequence[Sequence[StationDay]], mix: str, path: str = "all_lose"
) -> float | None:
    scores = [
        z
        for group in groups
        for day in group
        if (z := _day_z(apply_mix(day, mix), path)) is not None
    ]
    if not scores:
        return None
    scores.sort()
    return scores[len(scores) // 2]


def all_lose_by_mix(
    groups: Sequence[Sequence[StationDay]], mixes: Sequence[str]
) -> dict[str, float | None]:
    """Median all-lose ``z`` per mix: the FQ G1 path, printed as context on other specs."""
    return {mix: _median_z(groups, mix, "all_lose") for mix in mixes}


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
    spec: FloorSpec = FQ_SPEC,
) -> None:
    """Per-cell crossing rate at the solved ``c``, plus the S3 single-day share."""
    binding = frozenset(spec.binding)
    for row, mode in spec.cal:
        rho = _rho(mode, config)
        for mix in spec.mixes:
            sim = cal_sims[(row, mode, mix)]
            drawn = crit(sim, n_cal, t_min)
            rate = crossing_rate(drawn, solved)
            rows.append(
                {
                    "row": row,
                    "mix": mix,
                    "role": "binding" if (row, mode) in binding else "report",
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
    tick_share: float = 1.0,
    spec: FloorSpec = FQ_SPEC,
) -> tuple[AlphaEval, tuple[str, str]]:
    """Solve ``c`` and the epoch gates for one α. Appends to ``rows`` and ``gates``."""
    binding = frozenset(spec.binding)
    mixes = spec.mixes
    by_t: dict[int, tuple[float, tuple[str, str]]] = {}
    scores: dict[int, float] = {}
    for t_min in T_MIN_GRID:
        cells: dict[tuple[str, str], float] = {}
        for row, mode in spec.cal:
            if (row, mode) not in binding:
                continue
            for mix in mixes:
                drawn = crit(cal_sims[(row, mode, mix)], n_cal, t_min)
                cells[(row, mix)] = smallest_grid_c(drawn, alpha)
        solved, cell = binding_max(cells)
        by_t[t_min] = (solved, cell)
        scores[t_min] = min(power(-0.16, mix, n_cal, t_min, solved) for mix in mixes)
    t_star = choose_t_min(scores, set(by_t))
    solved, cell = by_t[t_star]
    binding_draws = {
        (row, mix): crit(cal_sims[(row, mode, mix)], n_cal, t_star)
        for row, mode in spec.cal
        if (row, mode) in binding
        for mix in mixes
    }
    c_se = bootstrap_c_se(binding_draws, alpha=alpha, seed=_seed(seed, f"boot|{alpha}"))
    s6_rates = [
        crossing_rate(crit(cal_sims[("S6", "none", mix)], n_cal, t_star), solved)
        for mix in mixes
        if any(prep.day.legs for group in feasible[mix] for prep in group)
    ]
    s6_rate = max(s6_rates) if s6_rates else 1.0
    s6_se = binomial_se(s6_rate, replicates) if s6_rates else 0.0
    freeze_key = config.freeze.isoformat()
    measured = {
        delta_key(delta): min(
            power(delta, mix, lengths[freeze_key], t_star, solved) for mix in mixes
        )
        for delta in DELTAS
    }
    epoch_ok: dict[str, bool] = {}
    g1_pass = False
    g1_margin = False
    for epoch, n_days in lengths.items():
        t_low = t_low_count(n_days, config.lambda_sd, p_gate, tick_share=tick_share)
        passes: list[bool] = []
        margins: list[bool] = []
        g3_epoch: list[float] = []
        for mix in mixes:
            z = _median_z(cleaned, mix, spec.g1_path)
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
            gate_row: dict[str, object] = {
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
            if spec.g1_path != "all_lose":
                gate_row["z_g1"] = z
                gate_row["z_all_lose"] = _median_z(cleaned, mix, "all_lose")
            gates.append(gate_row)
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
    append_rows(rows, cal_sims, crit, alpha, t_star, solved, n_cal, replicates, config, spec)
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
        "rows": with_s7_skips(rows, admitted),
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


def ticking_share(groups: Sequence[Sequence[StationDay]]) -> float:
    days = [day for group in groups for day in group]
    if not days:
        return 0.0
    ticking = sum(1 for day in days if production_variance(day) > VARIANCE_EPS)
    return ticking / len(days)


def kappa_fallback_share(days: Sequence[StationDay]) -> float:
    legs = [leg for day in days for leg in day.legs]
    if not legs:
        return 0.0
    missing = 0
    for leg in legs:
        spread = leg.half_spread
        if spread is None or not math.isfinite(spread):
            missing += 1
    return missing / len(legs)


def h1_fallback_table(
    sims: Mapping[tuple[float, str], Simulation],
    spec: FloorSpec = FQ_SPEC,
) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for delta in DELTAS:
        uses = sum(sims[(delta, mix)].h1_fallback_uses for mix in spec.mixes)
        draws = sum(sims[(delta, mix)].h1_draws for mix in spec.mixes)
        table[delta_key(delta)] = {
            "uses": float(uses),
            "draws": float(draws),
            "share": (uses / draws) if draws else 0.0,
        }
    return table


def h1_warning_lines(by_delta: Mapping[str, Mapping[str, float]]) -> list[str]:
    lines: list[str] = []
    for delta, stats in by_delta.items():
        share = float(stats.get("share", 0.0))
        if share > 0.0:
            lines.append(
                f"H1 independent-Bernoulli fallback used at delta {delta}: share={share:.6f}"
            )
    return lines


def stamp_run(
    document: dict[str, object],
    *,
    config: FloorConfig,
    p_keep_cal: float,
    p_keep_gate: float,
    p_keep_cal_raw: float,
    p_keep_gate_raw: float,
    kappa_share: float,
    tick_share: float,
    h1_by_delta: Mapping[str, Mapping[str, float]],
    warnings: Sequence[str],
    outer_resamples: int,
    outer_replicates: int,
    c_components: Mapping[str, Mapping[str, object]],
    spec: FloorSpec = FQ_SPEC,
    g1_all_lose_z: Mapping[str, float | None] | None = None,
) -> dict[str, object]:
    document["lambda_pool"] = config.lambda_pool
    document["lambda_pool_definition"] = LAMBDA_POOL_DEFINITION
    document["rate_cal"] = rate_cal(config.lambda_pool, config.take_rate_lower)
    document["rate_gate"] = rate_gate(config.lambda_pool, config.take_rate_lower)
    document["p_keep_cal"] = p_keep_cal
    document["p_keep_gate"] = p_keep_gate
    document["p_keep_cal_raw"] = p_keep_cal_raw
    document["p_keep_gate_raw"] = p_keep_gate_raw
    document["achieved_rate_cal"] = config.achieved_rate_cal
    document["achieved_rate_gate"] = config.achieved_rate_gate
    document["pool_exit_fraction"] = config.pool_exit_fraction
    document["pool_exit_fraction_source"] = config.pool_exit_fraction_source
    document["kappa_exit_fallback_share"] = kappa_share
    document["tick_share"] = tick_share
    document["t_low_definition"] = T_LOW_DEFINITION
    document["h1_bernoulli_fallback"] = {key: dict(value) for key, value in h1_by_delta.items()}
    document["warnings"] = list(warnings)
    document["outer_resamples"] = outer_resamples
    document["outer_replicates"] = outer_replicates
    document["c_template_resample"] = C_TEMPLATE_RESAMPLE
    document["c_components"] = {key: dict(value) for key, value in c_components.items()}
    if spec != FQ_SPEC:
        document["floor_spec"] = spec.as_dict()
        if g1_all_lose_z is not None:
            document["g1_all_lose_z"] = dict(g1_all_lose_z)
    return document
