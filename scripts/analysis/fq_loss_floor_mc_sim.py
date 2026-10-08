"""One floor-MC family: resampled calendar days, keep probability, core clock.

S5 draws a Gaussian copula uniform. Every other row draws an independent uniform.
The carry is whatever ``step_clock`` returns. This module does not solve ``c``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay, advance_prepared

__all__ = ["Simulation", "simulate_family"]


@dataclass(frozen=True, slots=True)
class Simulation:
    paths: tuple[tuple[float, ...], ...]
    cuts: tuple[tuple[int, ...], ...]
    max_abs_carry_over_sigma: float
    mean_carry: float
    multi_tick_share: float
    h1_fallback_uses: int = 0
    h1_draws: int = 0


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _copula_u(rng: np.random.Generator, rho: float, factor: float) -> float:
    """``U = Φ(√ρ·F + √(1−ρ)·ε)``. ``ρ = 1`` shares one shock."""
    bounded = min(1.0, max(0.0, rho))
    if bounded >= 1.0:
        shock = factor
    elif bounded <= 0.0:
        shock = float(rng.standard_normal())
    else:
        shock = math.sqrt(bounded) * factor + math.sqrt(1.0 - bounded) * float(
            rng.standard_normal()
        )
    return _phi(shock)


def simulate_family(
    groups: Sequence[Sequence[PreparedDay]],
    *,
    replicates: int,
    n_days: int,
    p_keep: float,
    seed: int,
    row: str,
    delta: float | None = None,
    rho: float | None = None,
    netting: bool = True,
    p_exit: float = 0.0,
    half_spread: float | None = None,
    theta: float = 0.0,
) -> Simulation:
    """``n_days`` resampled calendar days. A station-day is kept with ``p_keep``."""
    if replicates < 1:
        raise ValueError(f"replicates must be positive, got {replicates}")
    if n_days < 0:
        raise ValueError(f"n_days must be non-negative, got {n_days}")
    if not groups:
        raise ValueError("simulate_family needs at least one calendar-day group")
    if not 0.0 <= p_keep <= 1.0:
        raise ValueError(f"p_keep must be in [0, 1], got {p_keep}")
    rng = np.random.default_rng(seed)
    paths: list[tuple[float, ...]] = []
    cuts: list[tuple[int, ...]] = []
    ratios: list[float] = []
    absorbed: list[float] = []
    multi = 0
    h1_uses = 0
    h1_draws = 0
    slots = replicates * n_days
    for _rep in range(replicates):
        increments: list[float] = []
        day_cuts: list[int] = []
        carry = 0.0
        for _day in range(n_days):
            group = groups[int(rng.integers(0, len(groups)))]
            factor = float(rng.standard_normal()) if rho is not None else 0.0
            ticks_today = 0
            for prep in group:
                if p_keep < 1.0 and float(rng.random()) >= p_keep:
                    continue
                u = float(rng.random()) if rho is None else _copula_u(rng, rho, factor)
                step, incoming, h1_fallback = advance_prepared(
                    prep,
                    u=u,
                    rng=rng,
                    carry=carry,
                    row=row,
                    delta=delta,
                    netting=netting,
                    pnl_scale=1.0,
                    p_exit=p_exit,
                    half_spread=half_spread,
                    theta=theta,
                )
                carry = step.carry_out
                if delta is not None:
                    h1_draws += 1
                    h1_uses += int(h1_fallback)
                if not step.is_tick or step.z is None:
                    continue
                increments.append(step.z)
                ticks_today += 1
                if incoming != 0.0 and step.sigma > 0.0:
                    ratios.append(abs(incoming) / step.sigma)
                    absorbed.append(incoming)
            if ticks_today >= 2:
                multi += 1
            day_cuts.append(len(increments))
        paths.append(tuple(increments))
        cuts.append(tuple(day_cuts))
    mean = float(sum(absorbed) / len(absorbed)) if absorbed else 0.0
    worst = max(ratios) if ratios else 0.0
    share = multi / slots if slots else 0.0
    return Simulation(tuple(paths), tuple(cuts), worst, mean, share, h1_uses, h1_draws)
