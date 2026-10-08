"""M2 gate for the F6 loss-stop floor (r3 §4.6). Pure; no pool I/O.

Escalation looks only at G1. A G3-floor miss at the selected α is a veto,
never a reason to try a larger α.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from breezy.analysis.fq_loss_stop_core import (
    ALPHA_FLOOR_GRID,
    G3_FLOOR_MULTIPLIER,
    T_MIN_GRID,
    first_crossing,
)
from scripts.analysis.fq_loss_floor_mc_solve import rate_within_alpha
from scripts.analysis.fq_mc_eprocess import POWER_TARGET

__all__ = [
    "DEFAULT_FREEZE",
    "DELTAS",
    "HORIZON",
    "POOL_EXIT_FRACTION_SOURCE",
    "AlphaEval",
    "FloorConfig",
    "FloorOutcome",
    "choose_t_min",
    "epoch_grid",
    "epoch_holds",
    "fully_lost_fraction",
    "g1_holds",
    "g3_floor",
    "inclusive_days",
    "keep_probability",
    "margin_limit",
    "rate_cal",
    "rate_gate",
    "reach_cutoff",
    "repeated_crossing",
    "select_alpha",
    "t_low_count",
]

POOL_EXIT_FRACTION_SOURCE: Final = "unavailable; floor 0.10 binds"
_FLOOR_MODES: Final = frozenset({"sqrt_boundary", "unreachable_veto"})
_POWER_CLASSES: Final = frozenset({"edge_capable", "gross_loss_tripwire", "none"})

DEFAULT_FREEZE: Final = date(2026, 10, 8)
HORIZON: Final = date(2027, 1, 25)
DELTAS: Final[tuple[float, ...]] = (-0.16, -0.08, -0.04)
_EPOCH_FIXED: Final[tuple[date, ...]] = (
    date(2026, 11, 1),
    date(2026, 11, 15),
    date(2026, 12, 1),
)
_DELTA_KEY: Final[dict[float, str]] = {-0.16: "-0.16", -0.08: "-0.08", -0.04: "-0.04"}


def delta_key(delta: float) -> str:
    key = _DELTA_KEY.get(delta)
    if key is None:
        raise ValueError(f"delta {delta!r} is not on the G3 grid")
    return key


def g3_floor(alpha: float) -> float:
    """``G3(−0.16) ≥ 2.5 × α`` (the multiplier is the core constant)."""
    return G3_FLOOR_MULTIPLIER * alpha


def margin_limit(t_low: int) -> int:
    """``⌊0.8 · T_low⌋`` (review ruling 2)."""
    if t_low < 0:
        raise ValueError(f"T_low must be non-negative, got {t_low}")
    return math.floor(0.8 * t_low)


def g1_holds(t_cross: int | None, t_low: int, *, margin: bool) -> bool:
    """G1: ``t_cross`` lands in ``[1, T_low]``. Margin tightens the cap."""
    if t_cross is None or t_low < 1:
        return False
    limit = margin_limit(t_low) if margin else t_low
    return 1 <= t_cross <= limit


def repeated_crossing(z: float, *, c: float, t_min: int, t_low: int) -> int | None:
    """All-lose path of ``t_low`` identical ticks, judged by :func:`first_crossing`."""
    if t_low < 1:
        return None
    return first_crossing([z] * t_low, c=c, t_min=t_min)


def fully_lost_fraction(z: float, *, c: float, t_low: int) -> float:
    """Minimum fully-lost fraction whose expected path crosses by ``T_low``."""
    if t_low < 1 or not z < 0.0:
        return 1.0
    return min(1.0, c / (abs(z) * math.sqrt(t_low)))


def rate_cal(lambda_pool: float, take_rate_lower: float) -> float:
    """``max(λ_pool, take_rate_lower)`` — more ticks, larger c (D5)."""
    return max(lambda_pool, take_rate_lower)


def rate_gate(lambda_pool: float, take_rate_lower: float) -> float:
    """``min(λ_pool, take_rate_lower)`` — fewer ticks, pessimistic reach and power."""
    return min(lambda_pool, take_rate_lower)


def keep_probability(rate: float, *, r_sd: float, lambda_sd: float) -> float:
    """Thin a pool station-day: ``min(1, (rate / r_sd) / λ_sd,pool)``."""
    if r_sd <= 0.0 or lambda_sd <= 0.0:
        raise ValueError(f"bad r_sd {r_sd!r} or lambda_sd {lambda_sd!r}")
    return min(1.0, (rate / r_sd) / lambda_sd)


def t_low_count(n_days: int, lambda_sd: float, p_keep: float, *, tick_share: float = 1.0) -> int:
    """Expected ticking station-days by the horizon at ``rate_gate``, rounded down."""
    if n_days < 0:
        raise ValueError(f"n_days must be non-negative, got {n_days}")
    if not 0.0 <= tick_share <= 1.0 or not math.isfinite(tick_share):
        raise ValueError(f"tick_share must be in [0, 1], got {tick_share!r}")
    return math.floor(n_days * lambda_sd * p_keep * tick_share)


def inclusive_days(start: date, end: date) -> int:
    if end < start:
        return 0
    return (end - start).days + 1


def epoch_grid(freeze: date) -> tuple[date, ...]:
    """``{freeze date, 2026-11-01, 2026-11-15, 2026-12-01}``, chronological."""
    return tuple(sorted({freeze, *_EPOCH_FIXED}))


def choose_t_min(scores: Mapping[int, float], feasible: set[int]) -> int:
    """Maximise G3 on the core ``t_min`` grid. Ties go to the smallest."""
    options = [t_min for t_min in T_MIN_GRID if t_min in feasible]
    if not options:
        raise ValueError("no t_min meets the alpha constraint")
    best = max(scores[t_min] for t_min in options)
    return min(t_min for t_min in options if scores[t_min] == best)


def epoch_holds(*, g1_pass: bool, g1_margin: bool, g3: float, alpha: float) -> bool:
    """Reach (with margin only when α > 0.10) and the G3 floor, both required."""
    reach = g1_margin if alpha > 0.10 + 1e-9 else g1_pass
    return reach and g3 + 1e-15 >= g3_floor(alpha)


def reach_cutoff(epoch_ok: Mapping[str, bool]) -> str | None:
    """Latest epoch date at which reach and the G3 floor both hold."""
    good = [day for day, ok in epoch_ok.items() if ok]
    if not good:
        return None
    return max(good)


@dataclass(frozen=True, slots=True)
class AlphaEval:
    """One α on the ladder, already scored. The ladder does not resimulate."""

    alpha: float
    g1_pass: bool
    g1_margin: bool
    g3_at_m016: float
    s6_rate: float
    s6_se: float
    c: float
    c_se: float
    t_min: int
    measured_power: Mapping[str, float]
    epoch_ok: Mapping[str, bool]


@dataclass(frozen=True, slots=True)
class FloorOutcome:
    floor_mode: str | None
    power_class: str
    alpha_star: float | None
    c: float | None
    c_mc_se: float | None
    t_min: int | None
    measured_power: dict[str, float] | None
    s6_feasible_rate: float | None
    reach_cutoff_epoch_start: str | None
    escalated_on_g3: bool = False
    freeze_blocked: dict[str, str] | None = None
    c_replicate_se: float | None = None
    c_template_sd: float | None = None
    c_template_quantiles: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if self.power_class not in _POWER_CLASSES:
            raise ValueError(f"power_class {self.power_class!r} is not a spec class")
        if self.floor_mode is None:
            if self.freeze_blocked is None:
                raise ValueError("floor_mode null requires freeze_blocked")
        elif self.floor_mode not in _FLOOR_MODES:
            raise ValueError(f"floor_mode {self.floor_mode!r} is not a spec mode")
        elif self.freeze_blocked is not None:
            raise ValueError("freeze_blocked requires floor_mode null")
        if self.freeze_blocked is not None:
            reason, detail = self.freeze_blocked.get("reason"), self.freeze_blocked.get("detail")
            if not reason or not detail:
                raise ValueError("freeze_blocked needs reason and detail")

    def as_dict(self) -> dict[str, object]:
        return {
            "floor_mode": self.floor_mode,
            "power_class": self.power_class,
            "alpha_star": self.alpha_star,
            "c": self.c,
            "c_mc_se": self.c_mc_se,
            "t_min": self.t_min,
            "measured_power": self.measured_power,
            "s6_feasible_rate": self.s6_feasible_rate,
            "reach_cutoff_epoch_start": self.reach_cutoff_epoch_start,
            "escalated_on_g3": self.escalated_on_g3,
            "freeze_blocked": self.freeze_blocked,
            "c_replicate_se": self.c_replicate_se,
            "c_template_sd": self.c_template_sd,
            "c_template_quantiles": self.c_template_quantiles,
        }


def _match(alpha: float, evals: Sequence[AlphaEval]) -> AlphaEval | None:
    for item in evals:
        if math.isclose(item.alpha, alpha, abs_tol=1e-9):
            return item
    return None


def select_alpha(evals: Sequence[AlphaEval]) -> FloorOutcome:
    """r3 §4.6 ladder, then the freeze table. Never escalates on G3."""
    chosen: AlphaEval | None = None
    for alpha in ALPHA_FLOOR_GRID:
        item = _match(alpha, evals)
        if item is None:
            continue
        if math.isclose(alpha, ALPHA_FLOOR_GRID[0], abs_tol=1e-9):
            if item.g1_pass:
                chosen = item
                break
        elif item.g1_margin:
            chosen = item
            break
    if chosen is None:
        return FloorOutcome(
            floor_mode="unreachable_veto",
            power_class="none",
            alpha_star=None,
            c=None,
            c_mc_se=None,
            t_min=None,
            measured_power=None,
            s6_feasible_rate=None,
            reach_cutoff_epoch_start=None,
        )
    powers = dict(chosen.measured_power)
    if not rate_within_alpha(chosen.s6_rate, alpha=chosen.alpha, se=chosen.c_se):
        return FloorOutcome(
            floor_mode=None,
            power_class="none",
            alpha_star=chosen.alpha,
            c=None,
            c_mc_se=None,
            t_min=chosen.t_min,
            measured_power=powers,
            s6_feasible_rate=chosen.s6_rate,
            reach_cutoff_epoch_start=None,
            freeze_blocked={
                "reason": "s6_failed",
                "detail": (
                    f"s6_feasible_rate {chosen.s6_rate} exceeds alpha {chosen.alpha}"
                    f" + 3*c_mc_se {chosen.c_se}"
                ),
            },
        )
    g3 = chosen.g3_at_m016
    if g3 >= POWER_TARGET:
        mode, power_class, solved = "sqrt_boundary", "edge_capable", chosen.c
    elif g3 + 1e-15 >= g3_floor(chosen.alpha):
        mode, power_class, solved = "sqrt_boundary", "gross_loss_tripwire", chosen.c
    else:
        mode, power_class, solved = "unreachable_veto", "none", None
    cutoff = reach_cutoff(chosen.epoch_ok) if mode == "sqrt_boundary" else None
    return FloorOutcome(
        floor_mode=mode,
        power_class=power_class,
        alpha_star=chosen.alpha,
        c=solved,
        c_mc_se=chosen.c_se if solved is not None else None,
        t_min=chosen.t_min,
        measured_power=powers,
        s6_feasible_rate=chosen.s6_rate,
        reach_cutoff_epoch_start=cutoff,
    )


@dataclass(frozen=True, slots=True)
class FloorConfig:
    """Rates and costs read from the parent, plus the epoch window."""

    take_rate_lower: float
    theta: float
    lambda_pool: float
    r_sd: float
    lambda_sd: float
    half_spread: float | None
    pool_exit_fraction: float
    rho_hat: float | None
    freeze: date = DEFAULT_FREEZE
    horizon: date = HORIZON
    achieved_rate_cal: float | None = None
    achieved_rate_gate: float | None = None
    pool_exit_fraction_source: str = POOL_EXIT_FRACTION_SOURCE
    r_sd_cal: float | None = None
    lambda_sd_cal: float | None = None
