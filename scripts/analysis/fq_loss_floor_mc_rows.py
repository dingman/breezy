"""Station-day templates for the floor MC. Variance and the clock stay in the core."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import numpy as np

from breezy.analysis.fq_loss_stop_core import (
    FqLossStopRefusal,
    NormalisedDay,
    sigma_from_variance,
    step_clock,
)
from breezy.analysis.fq_loss_stop_shrink import bundle_variance, shrunk_joint
from breezy.settlement.current_rung_hold_v2 import StratumRow, break_even_row
from breezy.strategy.weather_common.costs import venue_fee_prob

__all__ = [
    "KAPPA_FLOOR",
    "Leg",
    "RefusedTemplate",
    "StationDay",
    "WalkReport",
    "all_lose_z",
    "apply_mix",
    "clamped_leg_share",
    "critical_values",
    "estimate_rho",
    "exit_coefficient",
    "exit_probability",
    "h1_win_probability",
    "kappa_exit",
    "make_leg",
    "make_station_day",
    "partition_station_days",
    "production_variance",
    "rho_bind",
    "s6_station_days",
    "stratum_rows",
    "sum_cell_q",
    "template_overround",
    "walk_fixed",
]

Side = Literal["yes", "no"]
KAPPA_FLOOR: float = 0.02  # review ruling 1: max(median half-spread, 0.02)
_P_EXIT_FLOOR: float = 0.10  # r3 §4.5, accepted by review ruling 1
_RHO_FLOOR: float = 0.25  # ρ_bind = max(0.25, ρ̂_pool)
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
_ZERO = Decimal(0)
_ONE = Decimal(1)


def rung_temperature(rung: str) -> tuple[float, str]:
    match = _NUM.search(rung)
    if match is None:
        return (math.inf, rung)
    return (float(match.group()), rung)


@dataclass(frozen=True, slots=True)
class Leg:
    rung: str
    side: Side
    be: float
    price: float
    half_spread: float | None = None


def make_leg(
    rung: str,
    side: Side,
    be: float,
    *,
    price: float | None = None,
    half_spread: float | None = None,
) -> Leg:
    if side not in ("yes", "no"):
        raise ValueError(f"side must be yes or no, got {side!r}")
    if not math.isfinite(be) or not 0.0 < be < 1.0:
        raise ValueError(f"BE {be!r} is not in (0, 1)")
    quoted = be if price is None else price
    if not math.isfinite(quoted) or not 0.0 <= quoted <= 1.0:
        raise ValueError(f"price {quoted!r} is not in [0, 1]")
    return Leg(rung, side, be, quoted, half_spread)


@dataclass(frozen=True, slots=True)
class StationDay:
    station: str
    legs: tuple[Leg, ...]
    netting: float = 0.0

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.legs, key=lambda leg: rung_temperature(leg.rung)))
        if ordered != self.legs:
            object.__setattr__(self, "legs", ordered)


def _mean(values: Sequence[float]) -> float:
    return float(sum(values) / len(values))


def _collapse(rung: str, side: Side, legs: Sequence[Leg]) -> Leg:
    spreads = [leg.half_spread for leg in legs]
    finite = [item for item in spreads if item is not None and math.isfinite(item)]
    spread = _mean(finite) if len(finite) == len(spreads) else None
    be, price = _mean([leg.be for leg in legs]), _mean([leg.price for leg in legs])
    return make_leg(rung, side, be, price=price, half_spread=spread)


def make_station_day(
    station: str, legs: Sequence[Leg], *, extra_netting: float = 0.0
) -> StationDay:
    grouped: dict[str, dict[str, list[Leg]]] = {}
    order: list[str] = []
    for leg in legs:
        if leg.rung not in grouped:
            grouped[leg.rung] = {}
            order.append(leg.rung)
        grouped[leg.rung].setdefault(leg.side, []).append(leg)
    netting = extra_netting
    unpaired: list[Leg] = []
    for rung in order:
        yes = grouped[rung].get("yes", [])
        no = grouped[rung].get("no", [])
        if yes and no:
            be_y = Decimal(str(_mean([leg.be for leg in yes])))
            be_n = Decimal(str(_mean([leg.be for leg in no])))
            netting += float(_ONE - be_y - be_n)
        elif yes:
            unpaired.append(_collapse(rung, "yes", yes))
        elif no:
            unpaired.append(_collapse(rung, "no", no))
    return StationDay(station, tuple(unpaired), netting)


def cell_q(leg: Leg) -> float:
    be = float(break_even_row(Decimal(str(leg.be)), _ZERO))
    return be if leg.side == "yes" else 1.0 - be


def sum_cell_q(day: StationDay) -> float:
    return float(sum(cell_q(leg) for leg in day.legs))


def stratum_rows(day: StationDay) -> tuple[StratumRow, ...]:
    return tuple(
        StratumRow(
            entry_ask=Decimal(str(leg.be)),
            fee=_ZERO,
            held=False,
            station=day.station,
            qty=_ONE,
            side=leg.side,
            rung=leg.rung,
        )
        for leg in day.legs
    )


def production_variance(day: StationDay) -> float:
    if not day.legs:
        return 0.0
    return bundle_variance(stratum_rows(day))


def _clock_block(day: StationDay) -> str | None:
    from scripts.analysis.fq_loss_floor_mc_draw import clock_block

    return clock_block(day)


def x_piece(h: float, be: Decimal) -> float:
    if h == 0.0 or h == 1.0:
        return float(Decimal(int(h))) - float(be)
    return float(Decimal(str(h)) - be)


def _normalised(station: str, x_rand: float, shift: float, variance: float) -> NormalisedDay:
    return NormalisedDay(
        station=station, legs=(), shifts=(), rows=(), x_rand=x_rand, shift=shift, variance=variance
    )


@dataclass(frozen=True, slots=True)
class RefusedTemplate:
    station: str
    rungs: tuple[str, ...]
    reason: str
    detail: str


def partition_station_days(
    days: Sequence[StationDay],
) -> tuple[tuple[StationDay, ...], tuple[RefusedTemplate, ...]]:
    admitted: list[StationDay] = []
    refused: list[RefusedTemplate] = []
    for day in days:
        if not day.legs:
            admitted.append(day)
            continue
        try:
            bundle_variance(stratum_rows(day))
        except FqLossStopRefusal as exc:
            refused.append(
                RefusedTemplate(
                    day.station, tuple(leg.rung for leg in day.legs), exc.reason.value, exc.detail
                )
            )
            continue
        blocked = _clock_block(day)
        if blocked is not None:
            refused.append(
                RefusedTemplate(
                    day.station,
                    tuple(leg.rung for leg in day.legs),
                    blocked,
                    "zero-variance day realises nonzero x",
                )
            )
            continue
        admitted.append(day)
    return tuple(admitted), tuple(refused)


def template_overround(days: Sequence[StationDay]) -> tuple[float, float | None]:
    kappas: list[float] = []
    over = 0
    for day in days:
        if sum_cell_q(day) <= 1.0:
            continue
        over += 1
        try:
            kappas.append(shrunk_joint(stratum_rows(day)).kappa)
        except FqLossStopRefusal:
            continue
    share = over / len(days) if days else 0.0
    mean = float(sum(kappas) / len(kappas)) if kappas else None
    return share, mean


def apply_mix(day: StationDay, mix: str) -> StationDay:
    if mix == "M-pool":
        return day
    if mix not in {"M-yes", "M-no"}:
        raise ValueError(f"unknown mix {mix!r}")
    side: Side = "yes" if mix == "M-yes" else "no"
    kept = tuple(leg for leg in day.legs if leg.side == side)
    return StationDay(day.station, kept, 0.0)


def s6_station_days(days: Sequence[StationDay]) -> tuple[StationDay, ...]:
    kept: list[StationDay] = []
    for day in days:
        if not day.legs or sum_cell_q(day) > 1.0:
            continue
        kept.append(StationDay(day.station, day.legs, 0.0))
    return tuple(kept)


def kappa_exit(half_spread: float | None) -> float:
    spread = 0.0
    if half_spread is not None and math.isfinite(half_spread):
        spread = max(0.0, half_spread)
    return max(spread, KAPPA_FLOOR)


def exit_coefficient(half_spread: float | None, *, price: float, theta: float) -> float:
    fee = venue_fee_prob(executable_price=price, fee_coefficient=theta)
    return kappa_exit(half_spread) + fee


def exit_probability(pool_exit_fraction: float) -> float:
    if pool_exit_fraction < 0.0:
        raise ValueError(f"exit fraction must be non-negative, got {pool_exit_fraction!r}")
    return max(_P_EXIT_FLOOR, pool_exit_fraction)


def rho_bind(rho_hat: float | None) -> float:
    if rho_hat is None or not math.isfinite(rho_hat):
        return _RHO_FLOOR
    return max(_RHO_FLOOR, rho_hat)


def estimate_rho(days: Sequence[Sequence[float]]) -> float | None:
    xs: list[float] = []
    ys: list[float] = []
    for pits in days:
        for i in range(len(pits)):
            for j in range(i + 1, len(pits)):
                xs.append(float(pits[i]))
                ys.append(float(pits[j]))
    if len(xs) < 3:
        return None
    left = np.asarray(xs, dtype=float)
    right = np.asarray(ys, dtype=float)
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return 1.0 if bool(np.allclose(left, right)) else None
    corr = float(np.corrcoef(left, right)[0, 1])
    return corr if math.isfinite(corr) else None


def h1_win_probability(be: float, *, delta: float) -> float:
    return max(0.0, be - abs(delta))


def clamped_leg_share(legs: Sequence[Leg], *, delta: float) -> float:
    if not legs:
        return 0.0
    clamped = sum(1 for leg in legs if leg.be < abs(delta))
    return clamped / len(legs)


def _pnl(day: StationDay, hs: Sequence[float], pnl_scale: float) -> float:
    total = sum(x_piece(h, Decimal(str(leg.be))) for leg, h in zip(day.legs, hs, strict=True))
    return total * pnl_scale


def all_lose_z(day: StationDay) -> float | None:
    if not day.legs:
        return None
    variance = production_variance(day)
    if sigma_from_variance(variance) == 0.0:
        return None
    x_rand = sum(x_piece(0.0, Decimal(str(leg.be))) for leg in day.legs)
    step = step_clock(_normalised(day.station, x_rand, day.netting, variance), 0.0)
    return step.z


@dataclass(frozen=True, slots=True)
class WalkReport:
    increments: tuple[float, ...]
    max_abs_carry_over_sigma: float
    mean_carry: float


def walk_fixed(
    steps: Sequence[tuple[StationDay, tuple[float, ...] | None]],
    *,
    drop_carry: bool = False,
) -> WalkReport:
    carry = 0.0
    increments: list[float] = []
    ratios: list[float] = []
    absorbed: list[float] = []
    for day, hs in steps:
        if hs is None:
            x_rand, variance = 0.0, 0.0
        else:
            x_rand = _pnl(day, hs, 1.0)
            variance = production_variance(day)
        incoming = 0.0 if drop_carry else carry
        step = step_clock(_normalised(day.station, x_rand, day.netting, variance), incoming)
        carry = 0.0 if drop_carry else step.carry_out
        if not step.is_tick or step.z is None:
            continue
        increments.append(step.z)
        if incoming != 0.0 and step.sigma > 0.0:
            ratios.append(abs(incoming) / step.sigma)
            absorbed.append(incoming)
    mean = float(sum(absorbed) / len(absorbed)) if absorbed else 0.0
    worst = max(ratios) if ratios else 0.0
    return WalkReport(tuple(increments), worst, mean)


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
    from scripts.analysis.fq_loss_floor_mc_draw import critical_values as _draw

    return _draw(
        days,
        row=row,
        replicates=replicates,
        n_ticks=n_ticks,
        seed=seed,
        t_min=t_min,
        netting=netting,
        drop_overround=drop_overround,
        pnl_scale=pnl_scale,
        return_paths=return_paths,
    )
