"""Template-resample component of the floor's c standard error."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import numpy as np

from scripts.analysis.fq_loss_floor_mc_gate import AlphaEval, FloorConfig
from scripts.analysis.fq_loss_floor_mc_rows import StationDay

__all__ = [
    "TemplateComponent",
    "apply_outer_se",
    "c_mc_se_total",
    "resample_template_c",
    "solve_resampled",
    "summarise_template_c",
]

_MC_SE_LABEL = "sqrt(c_replicate_se^2 + c_template_sd^2); this is the spec c_mc_se"


@dataclass(frozen=True, slots=True)
class TemplateComponent:
    c_replicate_se: float
    c_template_sd: float
    c_template_quantiles: dict[str, float] | None
    c_mc_se_total: float

    def as_dict(self) -> dict[str, object]:
        return {
            "c_replicate_se": self.c_replicate_se,
            "c_replicate_se_label": "bootstrap SE of binding-max c across MC replicates",
            "c_template_sd": self.c_template_sd,
            "c_template_sd_label": "sample sd (ddof=1) of c across calendar-day template resamples",
            "c_template_quantiles": self.c_template_quantiles,
            "c_mc_se_total": self.c_mc_se_total,
            "c_mc_se_total_label": _MC_SE_LABEL,
        }


_BINDING: tuple[tuple[str, str], ...] = (("H0", "none"), ("S4", "none"), ("S5", "bind"))


def c_mc_se_total(replicate_se: float, template_sd: float) -> float:
    """``sqrt(replicate_se² + template_sd²)``. This value is the spec's ``c_mc_se``."""
    if replicate_se < 0.0 or template_sd < 0.0:
        raise ValueError(f"negative SE component {replicate_se!r}, {template_sd!r}")
    if not math.isfinite(replicate_se) or not math.isfinite(template_sd):
        raise ValueError("SE components must be finite")
    return math.sqrt(replicate_se * replicate_se + template_sd * template_sd)


def summarise_template_c(samples: Sequence[float]) -> tuple[float, dict[str, float]]:
    if len(samples) < 2:
        raise ValueError("template sd needs at least two resamples")
    array = np.asarray(samples, dtype=float)
    deviation = float(np.std(array, ddof=1))
    low, mid, high = (float(value) for value in np.quantile(array, [0.025, 0.5, 0.975]))
    return deviation, {"p025": low, "p50": mid, "p975": high}


def resample_template_c[T](
    groups: Sequence[T],
    *,
    resamples: int,
    seed: int,
    solve: Callable[[Sequence[T], int], float],
) -> list[float]:
    """Resample calendar-day templates with replacement and re-solve ``c`` on each."""
    if resamples < 2:
        raise ValueError(f"resamples must be at least 2, got {resamples}")
    if not groups:
        raise ValueError("template resample needs at least one calendar day")
    rng = np.random.default_rng(seed)
    width = len(groups)
    solved: list[float] = []
    for draw in range(resamples):
        picked = tuple(groups[int(index)] for index in rng.integers(0, width, size=width))
        solved.append(float(solve(picked, draw)))
    return solved


def binding_c(
    groups: Sequence[Sequence[StationDay]],
    *,
    alpha: float,
    t_min: int,
    replicates: int,
    n_days: int,
    p_keep: float,
    seed: int,
    config: FloorConfig,
) -> float:
    """Binding-max grid ``c`` at a fixed ``t_min``. Imports the engine lazily."""
    from scripts.analysis.fq_loss_floor_mc_engine import (
        MIXES,
        _criticals,
        _rho,
        _run,
        _seed,
        prepare_mix_groups,
    )
    from scripts.analysis.fq_loss_floor_mc_solve import binding_max, smallest_grid_c

    pooled = {mix: prepare_mix_groups(groups, mix, s6=False) for mix in MIXES}
    cells: dict[tuple[str, str], float] = {}
    for row, mode in _BINDING:
        for mix in MIXES:
            simulation = _run(
                pooled[mix],
                replicates=replicates,
                n_days=n_days,
                p_keep=p_keep,
                seed=_seed(seed, f"outer|{alpha}|{row}|{mode}|{mix}"),
                row=row,
                config=config,
                rho=_rho(mode, config),
                netting=True,
            )
            drawn = _criticals(simulation, n_days, t_min)
            cells[(row, mix)] = smallest_grid_c(drawn, alpha)
    solved, _cell = binding_max(cells)
    return solved


def solve_resampled(
    groups: Sequence[Sequence[StationDay]],
    *,
    alpha: float,
    t_min: int,
    resamples: int,
    replicates: int,
    n_days: int,
    p_keep: float,
    seed: int,
    config: FloorConfig,
) -> tuple[float, dict[str, float]]:
    """``c`` sample sd and quantiles across ``resamples`` of the template set."""

    def solve(picked: Sequence[Sequence[StationDay]], draw: int) -> float:
        return binding_c(
            picked,
            alpha=alpha,
            t_min=t_min,
            replicates=replicates,
            n_days=n_days,
            p_keep=p_keep,
            seed=seed + draw * 1_000_003,
            config=config,
        )

    samples = resample_template_c(groups, resamples=resamples, seed=seed, solve=solve)
    return summarise_template_c(samples)


def apply_outer_se(
    evals: Sequence[AlphaEval],
    *,
    groups: Sequence[Sequence[StationDay]],
    resamples: int,
    replicates: int,
    n_days: int,
    p_keep: float,
    seed_for: Callable[[str], int],
    config: FloorConfig,
) -> tuple[tuple[AlphaEval, ...], dict[str, TemplateComponent]]:
    """Replace each ``c_se`` with ``c_mc_se_total`` before the ladder reads it."""
    adjusted: list[AlphaEval] = []
    components: dict[str, TemplateComponent] = {}
    for evaluation in evals:
        replicate_se = evaluation.c_se
        template_sd = 0.0
        quantiles: dict[str, float] | None = None
        if resamples >= 2:
            template_sd, quantiles = solve_resampled(
                groups,
                alpha=evaluation.alpha,
                t_min=evaluation.t_min,
                resamples=resamples,
                replicates=replicates,
                n_days=n_days,
                p_keep=p_keep,
                seed=seed_for(f"outer|{evaluation.alpha:.2f}"),
                config=config,
            )
        total = c_mc_se_total(replicate_se, template_sd)
        components[f"{evaluation.alpha:.2f}"] = TemplateComponent(
            replicate_se, template_sd, quantiles, total
        )
        adjusted.append(replace(evaluation, c_se=total))
    return tuple(adjusted), components
