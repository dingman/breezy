"""One floor-MC family: resampled calendar days, keep probability, core clock.

S5 draws a Gaussian copula uniform. Every other row draws an independent uniform,
unless ``persist=(L, rho_p)``: then each station carries one factor, held for ``L``
simulated days and redrawn at the next block, and ``u = Φ(√ρp·F + √(1−ρp)·ε)``.
The carry is whatever ``step_clock`` returns. This module does not solve ``c``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay, TickDraw, advance_prepared

__all__ = ["Simulation", "simulate_family"]

_PERSIST_STREAM = 0x9E15  # child stream for station factors; the main stream is untouched


@dataclass(frozen=True, slots=True)
class Simulation:
    paths: tuple[tuple[float, ...], ...]
    cuts: tuple[tuple[int, ...], ...]
    max_abs_carry_over_sigma: float
    mean_carry: float
    multi_tick_share: float
    h1_fallback_uses: int = 0
    h1_draws: int = 0
    draws: tuple[tuple[TickDraw, ...], ...] = ()


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
    record_draws: bool = False,
    persist: tuple[int, float] | None = None,
) -> Simulation:
    """``n_days`` resampled calendar days. A station-day is kept with ``p_keep``.

    ``persist=(L, rho_p)`` shares a per-station factor within L-day blocks. It cannot
    be combined with ``rho``. ``persist=None`` leaves the RNG stream unchanged.
    """
    if replicates < 1:
        raise ValueError(f"replicates must be positive, got {replicates}")
    if n_days < 0:
        raise ValueError(f"n_days must be non-negative, got {n_days}")
    if not groups:
        raise ValueError("simulate_family needs at least one calendar-day group")
    if not 0.0 <= p_keep <= 1.0:
        raise ValueError(f"p_keep must be in [0, 1], got {p_keep}")
    if persist is not None:
        if rho is not None:
            raise ValueError("persist and rho are mutually exclusive")
        if persist[0] < 1 or not 0.0 <= persist[1] <= 1.0:
            raise ValueError(f"persist needs L >= 1 and 0 <= rho_p <= 1, got {persist!r}")
    rng = np.random.default_rng(seed)
    factor_rng = np.random.default_rng([seed, _PERSIST_STREAM]) if persist else None
    paths: list[tuple[float, ...]] = []
    cuts: list[tuple[int, ...]] = []
    draw_paths: list[tuple[TickDraw, ...]] = []
    ratios: list[float] = []
    absorbed: list[float] = []
    multi = 0
    h1_uses = 0
    h1_draws = 0
    slots = replicates * n_days
    for _rep in range(replicates):
        increments: list[float] = []
        draw_increments: list[TickDraw] = []
        day_cuts: list[int] = []
        carry = 0.0
        station_factors: dict[str, float] = {}
        for day_index in range(n_days):
            if persist is not None and day_index % persist[0] == 0:
                station_factors.clear()
            group = groups[int(rng.integers(0, len(groups)))]
            factor = float(rng.standard_normal()) if rho is not None else 0.0
            ticks_today = 0
            for prep in group:
                if p_keep < 1.0 and float(rng.random()) >= p_keep:
                    continue
                if persist is not None and factor_rng is not None:
                    shared = station_factors.get(prep.day.station)
                    if shared is None:
                        shared = float(factor_rng.standard_normal())
                        station_factors[prep.day.station] = shared
                    u = _copula_u(rng, persist[1], shared)
                else:
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
                    draw_sink=draw_increments if record_draws else None,
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
        if record_draws and len(draw_increments) != len(increments):
            raise RuntimeError("tick draws and z increments diverged")
        paths.append(tuple(increments))
        cuts.append(tuple(day_cuts))
        if record_draws:
            draw_paths.append(tuple(draw_increments))
    mean = float(sum(absorbed) / len(absorbed)) if absorbed else 0.0
    worst = max(ratios) if ratios else 0.0
    share = multi / slots if slots else 0.0
    recorded = tuple(draw_paths) if record_draws else ()
    return Simulation(tuple(paths), tuple(cuts), worst, mean, share, h1_uses, h1_draws, recorded)
