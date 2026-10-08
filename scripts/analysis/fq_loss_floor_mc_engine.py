"""Solve the F6 loss-stop floor on station-day templates (r3 §4.5–§4.6).

The α ladder is ``select_alpha``. A G3 miss never moves α. Any refused
template (Σ_NO q > 1) is reported and blocks a frozen c.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

import numpy as np

from breezy.analysis.fq_loss_stop_core import ALPHA_FLOOR_GRID
from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay, clock_block, prepare_day
from scripts.analysis.fq_loss_floor_mc_gate import (
    DELTAS,
    FloorConfig,
    FloorOutcome,
    epoch_grid,
    inclusive_days,
    keep_probability,
    rate_cal,
    rate_gate,
    select_alpha,
)
from scripts.analysis.fq_loss_floor_mc_outer import apply_outer_se
from scripts.analysis.fq_loss_floor_mc_report import (
    evaluate_alpha,
    finish_document,
    h1_fallback_table,
    h1_warning_lines,
    kappa_fallback_share,
    stamp_run,
    ticking_share,
)
from scripts.analysis.fq_loss_floor_mc_rows import (
    RefusedTemplate,
    StationDay,
    apply_mix,
    exit_probability,
    partition_station_days,
    rho_bind,
    sum_cell_q,
)
from scripts.analysis.fq_loss_floor_mc_sim import Simulation, simulate_family
from scripts.analysis.fq_loss_floor_mc_solve import critical_value, crossing_rate

__all__ = ["PATH_FAMILIES", "prepare_mix_groups", "run_floor"]

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
# Calibration rows × mixes, plus G3 deltas × mixes × the four epoch lengths.
PATH_FAMILIES: int = len(_CAL) * len(MIXES) + len(DELTAS) * len(MIXES) * 4


def _seed(master: int, label: str) -> int:
    digest = hashlib.sha256(f"{master}|{label}".encode()).digest()
    return int.from_bytes(digest[:4], "little")


def _partition(
    groups: Sequence[Sequence[StationDay]],
) -> tuple[tuple[tuple[StationDay, ...], ...], tuple[RefusedTemplate, ...]]:
    cleaned: list[tuple[StationDay, ...]] = []
    refused: list[RefusedTemplate] = []
    for group in groups:
        kept: list[StationDay] = []
        for day in group:
            admitted, rejected = partition_station_days((day,))
            kept.extend(admitted)
            refused.extend(rejected)
        cleaned.append(tuple(kept))
    return tuple(cleaned), tuple(refused)


def prepare_mix_groups(
    groups: Sequence[Sequence[StationDay]], mix: str, *, s6: bool
) -> list[list[PreparedDay]]:
    prepared: list[list[PreparedDay]] = []
    for group in groups:
        preps: list[PreparedDay] = []
        for day in group:
            mixed = apply_mix(day, mix)
            if s6:
                if not mixed.legs or sum_cell_q(mixed) > 1.0:
                    continue
                mixed = StationDay(mixed.station, mixed.legs, 0.0)
            elif not mixed.legs and mixed.netting == 0.0:
                continue
            if clock_block(mixed) is None:
                preps.append(prepare_day(mixed, deltas=DELTAS))
        prepared.append(preps)
    return prepared


def _criticals(sim: Simulation, n_days: int, t_min: int) -> np.ndarray:
    out = np.empty(len(sim.paths), dtype=float)
    for index, (path, cuts) in enumerate(zip(sim.paths, sim.cuts, strict=True)):
        if n_days <= 0 or not cuts:
            out[index] = critical_value((), t_min=t_min)
            continue
        end = cuts[min(n_days, len(cuts)) - 1]
        out[index] = critical_value(path[:end], t_min=t_min)
    return out


def _rho(mode: str, config: FloorConfig) -> float | None:
    if mode == "bind":
        return rho_bind(config.rho_hat)
    if mode == "half":
        return 0.5
    return None


def _run(
    groups: Sequence[Sequence[PreparedDay]],
    *,
    replicates: int,
    n_days: int,
    p_keep: float,
    seed: int,
    row: str,
    config: FloorConfig,
    delta: float | None = None,
    rho: float | None = None,
    netting: bool = True,
) -> Simulation:
    return simulate_family(
        groups,
        replicates=replicates,
        n_days=n_days,
        p_keep=p_keep,
        seed=seed,
        row=row,
        delta=delta,
        rho=rho,
        netting=netting,
        p_exit=exit_probability(config.pool_exit_fraction),
        half_spread=config.half_spread,
        theta=config.theta,
    )


def _refused_names(refused: Sequence[RefusedTemplate]) -> list[dict[str, object]]:
    return [
        {
            "station": item.station,
            "rungs": list(item.rungs),
            "reason": item.reason,
            "detail": item.detail,
        }
        for item in refused
    ]


def _blank(refused: Sequence[RefusedTemplate], *, seed: int, replicates: int) -> dict[str, object]:
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
        "refused_templates": _refused_names(refused),
        "max_abs_carry_over_sigma_next": 0.0,
        "binding_cell": None,
    }


def run_floor(
    groups: Sequence[Sequence[StationDay]],
    *,
    replicates: int,
    seed: int,
    config: FloorConfig,
    alphas: Sequence[float] | None = None,
    script_git_sha: str | None = None,
    parent_sha: str | None = None,
    a0_sha: str | None = None,
    git_head: str | None = None,
    gate_groups: Sequence[Sequence[StationDay]] | None = None,
    outer_resamples: int = 0,
    outer_replicates: int = 2000,
) -> dict[str, object]:
    if replicates < 1:
        raise ValueError(f"replicates must be positive, got {replicates}")
    grid = tuple(alphas) if alphas is not None else ALPHA_FLOOR_GRID
    for alpha in grid:
        if not any(math.isclose(alpha, item, abs_tol=1e-9) for item in ALPHA_FLOOR_GRID):
            raise ValueError(f"alpha {alpha} is not on {ALPHA_FLOOR_GRID}")
    cleaned, refused = _partition(groups)
    if gate_groups is None:
        gate_cleaned: tuple[tuple[StationDay, ...], ...] = cleaned
    else:
        gate_cleaned, gate_refused = _partition(gate_groups)
        refused = (*refused, *gate_refused)
    admitted = [day for group in cleaned for day in group]
    gate_admitted = [day for group in gate_cleaned for day in group]
    r_cal = config.r_sd if config.r_sd_cal is None else config.r_sd_cal
    l_cal = config.lambda_sd if config.lambda_sd_cal is None else config.lambda_sd_cal
    cal_rate = rate_cal(config.lambda_pool, config.take_rate_lower)
    gate_rate = rate_gate(config.lambda_pool, config.take_rate_lower)
    p_cal = keep_probability(cal_rate, r_sd=r_cal, lambda_sd=l_cal)
    p_gate = keep_probability(gate_rate, r_sd=config.r_sd, lambda_sd=config.lambda_sd)
    raw_cal = (cal_rate / r_cal) / l_cal
    raw_gate = (gate_rate / config.r_sd) / config.lambda_sd
    tick_share = ticking_share(gate_cleaned)
    kappa_share = kappa_fallback_share(admitted)

    def _emit(
        document: dict[str, object],
        h1: Mapping[str, Mapping[str, float]],
        components: Mapping[str, Mapping[str, object]],
    ) -> dict[str, object]:
        warnings = h1_warning_lines(h1)
        if raw_cal > 1.0 or raw_gate > 1.0:
            warnings.append(
                f"p_keep capped at 1; raw keep probability cal={raw_cal:.6f} gate={raw_gate:.6f}"
            )
        document["script_git_sha"] = script_git_sha
        document["parent_sha"] = parent_sha
        document["a0_sha"] = a0_sha
        document["git_head"] = git_head
        return stamp_run(
            document,
            config=config,
            p_keep_cal=p_cal,
            p_keep_gate=p_gate,
            p_keep_cal_raw=raw_cal,
            p_keep_gate_raw=raw_gate,
            kappa_share=kappa_share,
            tick_share=tick_share,
            h1_by_delta=h1,
            warnings=warnings,
            outer_resamples=outer_resamples,
            outer_replicates=outer_replicates,
            c_components=components,
        )

    if not admitted or not gate_admitted:
        return _emit(_blank(refused, seed=seed, replicates=replicates), {}, {})
    n_cal = inclusive_days(config.freeze, config.horizon)
    lengths = {
        day.isoformat(): inclusive_days(day, config.horizon) for day in epoch_grid(config.freeze)
    }
    n_gate = max(lengths.values(), default=0)
    pooled = {mix: prepare_mix_groups(cleaned, mix, s6=False) for mix in MIXES}
    feasible = {mix: prepare_mix_groups(cleaned, mix, s6=True) for mix in MIXES}
    gate_pooled = {mix: prepare_mix_groups(gate_cleaned, mix, s6=False) for mix in MIXES}
    cal_sims: dict[tuple[str, str, str], Simulation] = {}
    for row, mode in _CAL:
        for mix in MIXES:
            source = feasible[mix] if row == "S6" else pooled[mix]
            cal_sims[(row, mode, mix)] = _run(
                source,
                replicates=replicates,
                n_days=n_cal,
                p_keep=p_cal,
                seed=_seed(seed, f"cal|{row}|{mode}|{mix}"),
                row=row,
                config=config,
                rho=_rho(mode, config),
                netting=row != "S6",
            )
    gate_sims = {
        (delta, mix): _run(
            gate_pooled[mix],
            replicates=replicates,
            n_days=n_gate,
            p_keep=p_gate,
            seed=_seed(seed, f"g3|{delta}|{mix}"),
            row="H1",
            config=config,
            delta=delta,
        )
        for delta in DELTAS
        for mix in MIXES
    }
    cache: dict[tuple[int, int, int], np.ndarray] = {}

    def crit(sim: Simulation, n_days: int, t_min: int) -> np.ndarray:
        key = (id(sim), n_days, t_min)
        hit = cache.get(key)
        if hit is None:
            hit = _criticals(sim, n_days, t_min)
            cache[key] = hit
        return hit

    def power(delta: float, mix: str, n_days: int, t_min: int, solved: float) -> float:
        return crossing_rate(crit(gate_sims[(delta, mix)], n_days, t_min), solved)

    evals = []
    rows: list[dict[str, object]] = []
    gates: list[dict[str, object]] = []
    solved_cell: dict[float, tuple[str, str]] = {}
    for alpha in grid:
        evaluation, cell = evaluate_alpha(
            alpha=alpha,
            cal_sims=cal_sims,
            crit=crit,
            power=power,
            n_cal=n_cal,
            replicates=replicates,
            config=config,
            lengths=lengths,
            p_gate=p_gate,
            cleaned=gate_cleaned,
            feasible=feasible,
            seed=seed,
            rows=rows,
            gates=gates,
            tick_share=tick_share,
        )
        evals.append(evaluation)
        solved_cell[alpha] = cell
    adjusted, components = apply_outer_se(
        evals,
        groups=cleaned,
        resamples=outer_resamples,
        replicates=outer_replicates,
        n_days=n_cal,
        p_keep=p_cal,
        seed_for=lambda label: _seed(seed, label),
        config=config,
    )
    outcome = select_alpha(adjusted)
    chosen_alpha = outcome.alpha_star if outcome.alpha_star is not None else adjusted[0].alpha
    component = components[f"{chosen_alpha:.2f}"]
    outcome = replace(
        outcome,
        c_replicate_se=component.c_replicate_se,
        c_template_sd=component.c_template_sd,
        c_template_quantiles=component.c_template_quantiles,
    )
    if refused:
        outcome = replace(
            outcome,
            floor_mode=None,
            power_class="none",
            c=None,
            c_mc_se=None,
            reach_cutoff_epoch_start=None,
            freeze_blocked={
                "reason": "refused_templates",
                "detail": f"{len(refused)} station-day template(s) refused",
            },
        )
    carry = cal_sims[("H0", "none", "M-pool")]
    binding_cell: list[str] | None = None
    if outcome.c is not None and outcome.alpha_star is not None:
        binding_cell = list(solved_cell[outcome.alpha_star])
    h1 = h1_fallback_table(gate_sims)
    return _emit(
        finish_document(
            seed=seed,
            replicates=replicates,
            outcome=outcome,
            rows=rows,
            gates=gates,
            refused_count=len(refused),
            refused_templates=_refused_names(refused),
            binding_cell=binding_cell,
            carry_ratio=carry.max_abs_carry_over_sigma,
            mean_carry=carry.mean_carry,
            admitted=admitted,
            script_git_sha=None,
            parent_sha=None,
            a0_sha=None,
            git_head=None,
        ),
        h1,
        {key: item.as_dict() for key, item in components.items()},
    )
