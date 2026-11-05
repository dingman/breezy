"""√t clock for one normalised station-day (F5 pin r3 §4.1 step 8).

No I/O and no boundary constant ``c``. The pure core re-exports these names.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

__all__ = [
    "VARIANCE_EPS",
    "ClockStep",
    "FqLossStopRefusal",
    "ReasonCode",
    "first_crossing",
    "sigma_from_variance",
    "step_clock",
]


class ReasonCode(StrEnum):
    """Closed set of pure-core refusal reasons."""

    BE_OUT_OF_RANGE = "be_out_of_range"
    FEE_UNRECONCILED = "fee_unreconciled"
    MISSING_FEE = "missing_fee"
    UNKNOWN_NETTING = "unknown_netting"
    SIGMA_NO_EXCEEDS_ONE = "sigma_no_exceeds_one"
    NEGATIVE_VARIANCE = "negative_variance"
    INVALID_EXIT_FILL = "invalid_exit_fill"
    MISSING_SETTLEMENT = "missing_settlement"
    ADMISSION_REFUSED = "admission_refused"
    ZERO_VARIANCE_REALISED = "zero_variance_realised"


class FqLossStopRefusal(Exception):
    """A pure-core input the floor will not score. ``reason`` is closed."""

    reason: ReasonCode

    def __init__(self, reason: ReasonCode, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


#: n9. VARIANCE_EPS is a variance threshold, not a σ threshold. A tick
#: requires variance > VARIANCE_EPS. σ = sqrt(variance) is computed only
#: for those days. A variance at or below −VARIANCE_EPS is a numerical
#: defect, not a zero-σ day.
VARIANCE_EPS: Final[float] = 1e-12


class _ClockDay(Protocol):
    """The fields ``step_clock`` reads. ``NormalisedDay`` satisfies this."""

    @property
    def variance(self) -> float: ...

    @property
    def x_rand(self) -> float: ...

    @property
    def shift(self) -> float: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ClockStep:
    """One station-day on the √t clock. ``carry_out`` is 0 exactly on a tick."""

    is_tick: bool
    z: float | None
    x: float
    sigma: float
    carry_out: float


def sigma_from_variance(variance: float) -> float:
    """σ for a ticking day. Refuse a variance at or below ``−VARIANCE_EPS``.

    ``−VARIANCE_EPS < variance <= VARIANCE_EPS`` is a zero-σ day and returns
    0 without a square root. σ = sqrt(variance) is computed only when
    variance > VARIANCE_EPS (n9).
    """
    if not math.isfinite(variance) or variance <= -VARIANCE_EPS:
        raise FqLossStopRefusal(
            ReasonCode.NEGATIVE_VARIANCE,
            f"variance {variance!r} is at or below -VARIANCE_EPS",
        )
    if variance <= VARIANCE_EPS:
        return 0.0
    return math.sqrt(variance)


def first_crossing(increments: Sequence[float], *, c: float, t_min: int) -> int | None:
    """First 1-based t ≥ ``t_min`` with ``S_t < −c√t``, or None.

    t counts ticks. Equality with the boundary is not a crossing.
    """
    if t_min < 1:
        raise ValueError("t_min must be >= 1")
    total = 0.0
    for t, increment in enumerate(increments, start=1):
        total += increment
        if t >= t_min and total < -c * math.sqrt(t):
            return t
    return None


def step_clock(day: _ClockDay, carry: float) -> ClockStep:
    """Advance one station-day. A tick is ``variance > VARIANCE_EPS``; the carry then resets.

    A zero-σ day is not a tick. Its deterministic shift (Σ δ_net, plus any
    same-rung exit that is not itself a bundle leg) is added to the carry
    and enters the next tick (r3 §4.1 step 8). ``x_rand`` is not carried.
    A zero-variance day with a nonzero ``x_rand`` is an invariant break:
    dropping it would hide realised P&L, so the clock refuses instead.
    """
    sigma = sigma_from_variance(day.variance)
    if day.variance > VARIANCE_EPS:
        x = day.x_rand + day.shift + carry
        return ClockStep(is_tick=True, z=x / sigma, x=x, sigma=sigma, carry_out=0.0)
    if day.x_rand != 0.0:
        raise FqLossStopRefusal(
            ReasonCode.ZERO_VARIANCE_REALISED,
            f"zero-variance day would drop realised P&L x_rand={day.x_rand!r}",
        )
    return ClockStep(is_tick=False, z=None, x=day.shift, sigma=sigma, carry_out=carry + day.shift)
