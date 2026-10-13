"""Maker path model for the S3 loss-floor reachability run (plan r3 §4.1, r4 delta).

Pure and seeded. One leg is one filled resting NO bid, qty 1, held to settlement:
win ``1 - BE``, loss ``-BE``, ``BE = b + θ·b·(1 − b)``. A station-day carries at most
``MAX_RUNGS`` legs on distinct rungs; the FQ engine draws them from one categorical
outcome, so two legs can never both lose. Split from ``fq_loss_floor_mc_maker`` to keep
that CLI module under 300 lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

import numpy as np

from scripts.analysis.fq_loss_floor_mc_gate import (
    DEFAULT_FREEZE,
    FQ_CAL,
    FloorConfig,
    FloorSpec,
)
from scripts.analysis.fq_loss_floor_mc_rows import Leg, StationDay, make_leg

__all__ = [
    "BINDING_REPLICATES",
    "BORDERLINE_REPLICATES",
    "BORDERLINE_SEED",
    "B_CAP",
    "B_FLOOR",
    "DEFF_CEILING",
    "FILL_ICC",
    "FILL_ICC_SD",
    "GRID_BIDS",
    "LISTING",
    "MAKER_SPEC",
    "MAX_RUNGS",
    "N_TEMPLATE_DATES",
    "OUTER_REPLICATES",
    "OUTER_RESAMPLES",
    "RUNG_TRIALS_PER_DATE",
    "SEED",
    "STATIONS",
    "STATIONS_PER_DATE",
    "STRESS_THETA",
    "SWEEP_REPLICATES",
    "THETA_TAKER",
    "MakerMix",
    "MakerRefusal",
    "build_maker_groups",
    "confirm_mixes",
    "design_effects",
    "maker_be",
    "maker_floor_config",
    "station_day_icc",
    "sweep_mixes",
]

SEED: Final = 20261012
N_TEMPLATE_DATES: Final = 1000
SWEEP_REPLICATES: Final = 2000
BINDING_REPLICATES: Final = 10_000
OUTER_RESAMPLES: Final = 20
OUTER_REPLICATES: Final = 2000
BORDERLINE_REPLICATES: Final = 50_000
BORDERLINE_SEED: Final = 20261013
THETA_TAKER: Final = 0.0695
STRESS_THETA: Final = 0.08
B_FLOOR: Final = 0.70
B_CAP: Final = 0.80
MAX_RUNGS: Final = 2
DEFF_CEILING: Final = 1.5
LISTING: Final = 0.91
STATIONS: Final = ("LAX", "MDW", "MIA", "SFO")
# Spec §6.4 defines deff 1.5 = 1 + (m − 1)·ICC at m = 8 rung-trials per date (4 stations x 2 rungs).
# The template draws ONE fill trial per station-day, so m = 4 trials per date: the same ICC applied
# per station-day would realise only 1 + 3·(0.5/7) = 1.21. Hence two units:
#   FILL_ICC     per rung-trial (S2's unit, the floor of the refusal): (1.5 − 1)/(8 − 1) = 0.5/7
#   FILL_ICC_SD  per station-day (the Beta draw's unit): (1.5 − 1)/(4 − 1) = 0.5/3
# so the REALISED design effect of the fill trials equals the pinned 1.5.
RUNG_TRIALS_PER_DATE: Final = 8
STATIONS_PER_DATE: Final = len(STATIONS)
FILL_ICC: Final = (DEFF_CEILING - 1.0) / (RUNG_TRIALS_PER_DATE - 1)
FILL_ICC_SD: Final = (DEFF_CEILING - 1.0) / (STATIONS_PER_DATE - 1)
GRID_BIDS: Final = (0.70, 0.75, 0.80)
_FILLS: Final = (0.1, 0.2, 0.3, 0.4, 0.5)
_RUNG_IDS: Final = tuple(f"T{t}" for t in range(66, 78, 2))  # numeric, so rung_temperature orders
_TOL: Final = 1e-12

MAKER_SPEC: Final = FloorSpec(
    mixes=("M-pool",),
    cal=(*FQ_CAL, ("S8", "persist3"), ("S9", "persist5")),
    binding=(("H0", "none"), ("S4", "none"), ("S5", "bind"), ("S8", "persist3")),
    persist=(("persist3", 3, 0.5), ("persist5", 5, 0.9)),
    g1_path="worst_feasible",
)


class MakerRefusal(ValueError):
    """An input or parameter the run refuses rather than extrapolates."""


def station_day_icc(icc_rung_trial: float) -> float:
    """Map a per-rung-trial fill ICC (S2's unit) to the per-station-day ICC the template draws.

    Both give the same design effect on their own trial count: ``1 + 7·ICC_rt`` at 8 rung-trials
    per date equals ``1 + 3·ICC_sd`` at 4 station-day trials per date.
    """
    return icc_rung_trial * (RUNG_TRIALS_PER_DATE - 1) / (STATIONS_PER_DATE - 1)


def design_effects(icc_rung_trial: float) -> dict[str, float]:
    """Both ICC units, the pinned design effect, and the one the templates realise."""
    icc_sd = station_day_icc(icc_rung_trial)
    return {
        "fill_icc_rung_trial": icc_rung_trial,
        "fill_icc_station_day": icc_sd,
        "design_effect_pinned": 1.0 + (RUNG_TRIALS_PER_DATE - 1) * icc_rung_trial,
        "design_effect_realised": 1.0 + (STATIONS_PER_DATE - 1) * icc_sd,
    }


def maker_be(bid: float, theta: float) -> float:
    """``b + θ·b·(1 − b)``: the taker-θ break-even (conservative; the maker rebate is refused)."""
    return bid + theta * bid * (1.0 - bid)


@dataclass(frozen=True, slots=True)
class MakerMix:
    fill_rate: float
    bid: float
    rungs: Literal[1, 2]
    bid_bearing: float
    two_fill_share: float
    fill_icc: float
    theta: float = THETA_TAKER

    def __post_init__(self) -> None:
        if not B_FLOOR - _TOL <= self.bid <= B_CAP + _TOL:
            raise MakerRefusal(f"bid {self.bid!r} is outside [B_FLOOR {B_FLOOR}, B_CAP {B_CAP}]")
        if self.rungs not in (1, MAX_RUNGS):
            raise MakerRefusal(f"rungs must be 1 or {MAX_RUNGS}, got {self.rungs!r}")
        if self.fill_icc < FILL_ICC - _TOL or station_day_icc(self.fill_icc) >= 1.0:
            raise MakerRefusal(
                f"fill_icc {self.fill_icc!r} (per rung-trial) is below the 0.5/7 floor, or maps "
                "to a per-station-day ICC >= 1"
            )
        if self.two_fill_share > 0.0 and self.rungs == 1:
            raise MakerRefusal("two_fill_share > 0 with rungs == 1")
        for name in ("fill_rate", "bid_bearing", "two_fill_share", "theta"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise MakerRefusal(f"{name} must be in [0, 1]")


def _fill_probability(rng: np.random.Generator, mix: MakerMix) -> float:
    """Per-date fill probability ``Beta(mean f, ICC_sd)``: ``a + b = (1 − ICC_sd)/ICC_sd``.

    ``mix.fill_icc`` is per rung-trial; the draw uses its per-station-day image (see top).
    """
    if mix.fill_rate in (0.0, 1.0):
        return mix.fill_rate
    icc_sd = station_day_icc(mix.fill_icc)
    total = (1.0 - icc_sd) / icc_sd
    return float(rng.beta(mix.fill_rate * total, (1.0 - mix.fill_rate) * total))


def build_maker_groups(
    mix: MakerMix, *, n_dates: int, seed: int
) -> tuple[tuple[StationDay, ...], ...]:
    """One group per climate date; unfilled station-days are absent, fill-less dates stay empty."""
    if n_dates < 1:
        raise MakerRefusal(f"n_dates must be positive, got {n_dates}")
    be = maker_be(mix.bid, mix.theta)
    rng = np.random.default_rng(seed)
    groups: list[tuple[StationDay, ...]] = []
    for _date in range(n_dates):
        f_date = _fill_probability(rng, mix)
        day: list[StationDay] = []
        for station in STATIONS:
            listed = rng.random() < LISTING
            bidding = rng.random() < mix.bid_bearing
            filled = rng.random() < f_date
            if not (listed and bidding and filled):
                continue
            two = mix.rungs == MAX_RUNGS and rng.random() < mix.two_fill_share
            picked = sorted(rng.choice(len(_RUNG_IDS), size=2 if two else 1, replace=False))
            legs: tuple[Leg, ...] = tuple(
                make_leg(_RUNG_IDS[int(i)], "no", be, price=mix.bid) for i in picked
            )
            day.append(StationDay(station, legs, 0.0))
        groups.append(tuple(day))
    return tuple(groups)


def maker_floor_config(
    groups: tuple[tuple[StationDay, ...], ...],
    mix: MakerMix,
    *,
    freeze: date = DEFAULT_FREEZE,
) -> FloorConfig:
    """§4.1 rates read off the templates; ρ̂ pinned 0.5; FQ's 110-date window as a label."""
    if freeze != DEFAULT_FREEZE:
        raise MakerRefusal(f"freeze {freeze} refused: only {DEFAULT_FREEZE} is certified")
    days = [day for group in groups for day in group if day.legs]
    if not days:
        raise MakerRefusal("templates carry no filled station-day")
    legs = sum(len(day.legs) for day in days)
    rate = legs / len(groups)
    return FloorConfig(
        take_rate_lower=rate,
        theta=mix.theta,
        lambda_pool=rate,
        r_sd=legs / len(days),
        lambda_sd=len(days) / len(groups),
        half_spread=None,
        pool_exit_fraction=0.0,
        rho_hat=0.5,
    )


def _mix(k: int, b: float, f: float) -> MakerMix:
    two = 0.5 if k == MAX_RUNGS else 0.0
    return MakerMix(f, b, k, 1.0, two, FILL_ICC)  # type: ignore[arg-type]


def sweep_mixes() -> tuple[MakerMix, ...]:
    """f {0.1..0.5} x b {0.70, 0.75, 0.80} x k {1, 2} at β = 1, p₂ = 0.5."""
    return tuple(_mix(k, b, f) for f in _FILLS for b in GRID_BIDS for k in (1, 2))


def confirm_mixes() -> tuple[MakerMix, ...]:
    """The six f = 0.5 cells of the early-stop confirm."""
    return tuple(_mix(k, b, _FILLS[-1]) for b in GRID_BIDS for k in (1, 2))
