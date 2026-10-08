"""One-tick draws for the floor MC. Variance and the clock stay in the core.

H0 uses the shrink joint. S2 uses proportional masses. S1 and a refused H1
clamp draw independent Bernoullis. S4 adds the exit-cost shift on top of H0.
P&L is scaled here; σ is not.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from breezy.analysis.fq_loss_stop_core import (
    VARIANCE_EPS,
    ClockStep,
    FqLossStopRefusal,
    step_clock,
)
from breezy.analysis.fq_loss_stop_shrink import shrunk_joint
from breezy.settlement.current_rung_hold_v2 import StratumRow
from scripts.analysis.fq_loss_floor_mc_rows import (
    Leg,
    StationDay,
    _normalised,
    _pnl,
    cell_q,
    exit_coefficient,
    h1_win_probability,
    production_variance,
    stratum_rows,
    sum_cell_q,
    x_piece,
)
from scripts.analysis.fq_loss_floor_mc_solve import critical_value

__all__ = [
    "PreparedDay",
    "advance_prepared",
    "critical_values",
    "prepare_day",
    "resolved_half_spread",
]

_ZERO = Decimal(0)
_ONE = Decimal(1)


def _outcome_h(leg: Leg, index: int, slot: int) -> float:
    rung_wins = index == slot
    if leg.side == "yes":
        return 1.0 if rung_wins else 0.0
    return 0.0 if rung_wins else 1.0


def _h1_masses(day: StationDay, delta: float) -> tuple[float, ...] | None:
    """Categorical H1 masses. ``None`` means the clamp made Σ_NO q > 1."""
    if not day.legs:
        return ()
    masses: list[float] = []
    rows: list[StratumRow] = []
    for leg in day.legs:
        p_win = h1_win_probability(leg.be, delta=delta)
        mass = p_win if leg.side == "yes" else 1.0 - p_win
        masses.append(mass)
        be = Decimal(str(p_win)) if p_win > 0.0 else _ZERO
        rows.append(
            StratumRow(
                entry_ask=be,
                fee=_ZERO,
                held=False,
                station=day.station,
                qty=_ONE,
                side=leg.side,
                rung=leg.rung,
            )
        )
    sum_no = sum(mass for mass, leg in zip(masses, day.legs, strict=True) if leg.side == "no")
    if sum_no > 1.0:
        return None
    if sum(masses) > 1.0:
        try:
            return shrunk_joint(tuple(rows)).masses
        except FqLossStopRefusal:
            return None
    return tuple(masses)


@dataclass(frozen=True, slots=True)
class PreparedDay:
    day: StationDay
    variance: float
    masses: tuple[float, ...]
    proportional: tuple[float, ...]
    xs: tuple[float, ...]
    h1: Mapping[float, tuple[float, ...] | None]


def prepare_day(day: StationDay, *, deltas: Sequence[float] = ()) -> PreparedDay:
    if not day.legs:
        return PreparedDay(day, 0.0, (), (), (0.0,), {})
    qs = tuple(cell_q(leg) for leg in day.legs)
    if sum(qs) > 1.0:
        masses: tuple[float, ...] = shrunk_joint(stratum_rows(day)).masses
        total = sum(qs)
        proportional = tuple(q / total for q in qs)
    else:
        masses = qs
        proportional = qs
    xs = tuple(
        sum(
            x_piece(_outcome_h(leg, index, slot), Decimal(str(leg.be)))
            for slot, leg in enumerate(day.legs)
        )
        for index in range(len(day.legs) + 1)
    )
    h1 = {delta: _h1_masses(day, delta) for delta in deltas}
    return PreparedDay(day, production_variance(day), masses, proportional, xs, h1)


def clock_block(day: StationDay) -> str | None:
    """Reason the clock would refuse this day, or None when every positive-mass x is legal."""
    if not day.legs:
        return None
    try:
        prep = prepare_day(day)
    except FqLossStopRefusal as exc:
        return exc.reason.value
    if prep.variance > VARIANCE_EPS:
        return None
    weights = list(prep.masses)
    if len(prep.xs) == len(weights) + 1:
        weights.append(max(0.0, 1.0 - float(sum(prep.masses))))
    for outcome, weight in zip(prep.xs, weights, strict=False):
        if weight > 0.0 and outcome != 0.0:
            return "zero_variance_realised"
    return None


def resolved_half_spread(
    leg_spread: float | None, pool_median: float | None
) -> tuple[float | None, bool]:
    """Leg tape first. The pool median is only the fallback, and it is reported."""
    if leg_spread is not None and math.isfinite(leg_spread):
        return leg_spread, False
    return pool_median, True


def invert_cdf(masses: Sequence[float], u: float) -> int:
    cum = 0.0
    for index, mass in enumerate(masses):
        cum += mass
        if u < cum:
            return index
    return len(masses)


def advance_prepared(
    prep: PreparedDay,
    *,
    u: float,
    rng: np.random.Generator,
    carry: float,
    row: str,
    delta: float | None,
    netting: bool,
    pnl_scale: float,
    p_exit: float,
    half_spread: float | None,
    theta: float,
) -> tuple[ClockStep, float, bool]:
    """One station-day through ``step_clock``. Carry in, then the H1 Bernoulli fallback flag."""
    day = prep.day
    h1_fallback = bool(delta is not None and prep.h1.get(delta) is None and day.legs)
    independent = row == "S1" or h1_fallback
    if independent:
        ps = [
            leg.be if delta is None else h1_win_probability(leg.be, delta=delta) for leg in day.legs
        ]
        hs = [1.0 if float(rng.random()) < p else 0.0 for p in ps]
        x_rand = _pnl(day, hs, pnl_scale)
    else:
        if delta is not None:
            masses = prep.h1.get(delta, ())
        elif row == "S2":
            masses = prep.proportional
        else:
            masses = prep.masses
        if masses is None:
            masses = ()
        x_rand = prep.xs[invert_cdf(masses, u)] * pnl_scale
    shift = (day.netting if netting else 0.0) * pnl_scale
    if row == "S4":
        for leg in day.legs:
            if float(rng.random()) < p_exit:
                fraction = float(rng.random())
                spread, _fell_back = resolved_half_spread(leg.half_spread, half_spread)
                cost = exit_coefficient(spread, price=leg.price, theta=theta)
                shift -= pnl_scale * fraction * cost
    step = step_clock(_normalised(day.station, x_rand, shift, prep.variance), carry)
    return step, carry, h1_fallback


def critical_values(
    days: Sequence[StationDay],
    *,
    row: str,
    replicates: int,
    n_ticks: int,
    seed: int,
    t_min: int = 1,
    netting: bool = True,
    drop_overround: bool = False,
    pnl_scale: float = 1.0,
    return_paths: bool = False,
) -> np.ndarray | list[list[float]]:
    """Iid ticks from ``days``. ``pnl_scale`` multiplies P&L only, never σ."""
    if replicates < 1 or n_ticks < 1 or not days:
        raise ValueError("critical_values needs replicates, ticks and a day")
    preps = [prepare_day(day) for day in days]
    children = np.random.SeedSequence(seed).spawn(replicates)
    crits = np.empty(replicates, dtype=float)
    paths: list[list[float]] = []
    for index, child in enumerate(children):
        rng = np.random.default_rng(child)
        increments: list[float] = []
        carry = 0.0
        for _tick in range(n_ticks):
            prep = preps[int(rng.integers(0, len(preps)))]
            if drop_overround and sum_cell_q(prep.day) > 1.0:
                continue
            step, _incoming, _h1_fallback = advance_prepared(
                prep,
                u=float(rng.random()),
                rng=rng,
                carry=carry,
                row=row,
                delta=None,
                netting=netting,
                pnl_scale=pnl_scale,
                p_exit=0.0,
                half_spread=None,
                theta=0.0,
            )
            carry = step.carry_out
            if step.is_tick and step.z is not None:
                increments.append(step.z)
        crits[index] = critical_value(increments, t_min=t_min)
        if return_paths:
            paths.append(increments)
    if return_paths:
        return paths
    return crits
