"""Pure FQ loss-stop core (F5 pin r3 §4.1 steps 2–8, §4.2, §4.3).

No I/O, no clock read, and no boundary constant ``c``. The producer and the
floor Monte Carlo import these functions and replay them verbatim.

Feasible station-days (Σ q ≤ 1) take their variance from
``combine_station_day``. Overround days use the YES-first shrink and the
exact variance of that categorical, enumerated over the k+1 outcomes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal

from breezy.analysis.fq_loss_stop_shrink import ShrunkJoint, bundle_variance, shrunk_joint
from breezy.settlement.current_rung_hold_v2 import StratumRow

__all__ = ["ShrunkJoint", "bundle_variance", "shrunk_joint"]

Side = Literal["yes", "no"]

#: r3 §4.6 α ladder. Imported by the A1 checker; never retyped there.
ALPHA_FLOOR_GRID: Final[tuple[float, ...]] = (0.10, 0.20, 0.30)
#: r3 §4.6. G3(−0.16) must clear this multiple of α_floor.
G3_FLOOR_MULTIPLIER: Final[float] = 2.5
#: r3 §4.5. t_min is chosen from this grid; ties go to the smallest.
T_MIN_GRID: Final[tuple[int, ...]] = (1, 2, 3, 5)
#: n9. A tick requires σ > SIGMA_EPS. A variance at or below −SIGMA_EPS
#: is a numerical defect, not a zero-σ day.
SIGMA_EPS: Final[float] = 1e-12

_ZERO = Decimal(0)
_ONE = Decimal(1)


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


class FqLossStopRefusal(Exception):
    """A pure-core input the floor will not score. ``reason`` is closed."""

    reason: ReasonCode

    def __init__(self, reason: ReasonCode, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuyFill:
    """One BUY order's cumulative ledger totals on a single leg instrument.

    ``cost`` and ``fee`` are order totals, not per-contract prices. A NO
    leg's cost is the NO instrument's own premium, never ``1 −`` a YES wire.
    """

    rung: str
    side: Side
    qty: Decimal
    cost: Decimal
    fee: Decimal | None
    fee_reconciled: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitFill:
    """One SELL. ``cost`` is the order's gross proceeds (cumulative cost)."""

    rung: str
    side: Side
    qty: Decimal
    cost: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class LegSettlement:
    """Venue outcome for one (rung, side). ``held`` is that side's own truth."""

    rung: str
    side: Side
    held: bool
    voided: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class NettingShift:
    """One paired rung's deterministic ``1 − BE̅_y − BE̅_n`` (D1)."""

    rung: str
    delta_net: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class BundleLeg:
    """One unpaired (rung, side) at qty ≡ 1. ``h_eff`` is the realised outcome."""

    rung: str
    side: Side
    be: Decimal
    h_eff: Decimal
    row: StratumRow


@dataclass(frozen=True, slots=True, kw_only=True)
class NormalisedDay:
    """A station-day after netting, exits and voids. ``shift`` enters x, not σ."""

    station: str
    legs: tuple[BundleLeg, ...]
    shifts: tuple[NettingShift, ...]
    rows: tuple[StratumRow, ...]
    x_rand: float
    shift: float
    variance: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ClockStep:
    """One station-day on the √t clock. ``carry_out`` is 0 exactly on a tick."""

    is_tick: bool
    z: float | None
    x: float
    sigma: float
    carry_out: float


@dataclass(slots=True)
class _Side:
    be: Decimal
    held: bool
    bought: Decimal
    sold: Decimal
    proceeds: Decimal

    @property
    def open_qty(self) -> Decimal:
        if self.sold >= self.bought:
            return _ZERO
        return self.bought - self.sold


def per_contract_exit_v(*, cost: Decimal, fee: Decimal, sold_qty: Decimal) -> Decimal:
    """Per-contract v. ``_exit_record`` returns total proceeds; divide by qty (n1).

    ``fee > cost`` is ``InvalidExitFill`` and becomes a core refusal.
    """
    if sold_qty <= 0:
        raise FqLossStopRefusal(ReasonCode.INVALID_EXIT_FILL, "sold quantity must be positive")
    if fee > cost:
        raise FqLossStopRefusal(ReasonCode.INVALID_EXIT_FILL, "a SELL's fee exceeds its proceeds")
    return (cost - fee) / sold_qty


def sigma_from_variance(variance: float) -> float:
    """σ for a day. Refuse a variance at or below ``−SIGMA_EPS`` (n9)."""
    if not math.isfinite(variance) or variance <= -SIGMA_EPS:
        raise FqLossStopRefusal(
            ReasonCode.NEGATIVE_VARIANCE,
            f"variance {variance!r} is at or below -SIGMA_EPS",
        )
    if variance <= 0.0:
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


def step_clock(day: NormalisedDay, carry: float) -> ClockStep:
    """Advance one station-day. A tick is ``σ > SIGMA_EPS``; the carry then resets.

    A zero-σ day is not a tick. Its deterministic shift (Σ δ_net, plus any
    same-rung exit that is not itself a bundle leg) is added to the carry
    and enters the next tick (r3 §4.1 step 8). ``x_rand`` is not carried:
    on the days the pin names it is zero.
    """
    sigma = sigma_from_variance(day.variance)
    if sigma > SIGMA_EPS:
        x = day.x_rand + day.shift + carry
        return ClockStep(is_tick=True, z=x / sigma, x=x, sigma=sigma, carry_out=0.0)
    return ClockStep(is_tick=False, z=None, x=day.shift, sigma=sigma, carry_out=carry + day.shift)


def normalise_station_day(
    *,
    station: str,
    buys: Sequence[BuyFill],
    settlements: Sequence[LegSettlement],
    exits: Sequence[ExitFill] = (),
    unknown_netting_slugs: Sequence[str] = (),
) -> NormalisedDay:
    """Leg-normalise one station-day: qty ≡ 1, ledger BE̅, fee 0, netting split.

    Voids contribute nothing. A paired rung contributes one zero-variance
    shift and only its unpaired remainder stays in the random bundle.
    """
    if unknown_netting_slugs:
        raise FqLossStopRefusal(ReasonCode.UNKNOWN_NETTING, "unknown netting slugs")
    grouped, voided = _group_buys(buys, _settlement_index(settlements))
    _apply_exits(grouped, voided, exits)
    legs, shifts, exit_shift = _bundle(station, grouped)
    rows = tuple(leg.row for leg in legs)
    netting = float(sum((shift.delta_net for shift in shifts), start=_ZERO))
    return NormalisedDay(
        station=station,
        legs=tuple(legs),
        shifts=tuple(shifts),
        rows=rows,
        x_rand=math.fsum(_x_piece(leg) for leg in legs),
        shift=netting + float(exit_shift),
        variance=bundle_variance(rows),
    )


def _x_piece(leg: BundleLeg) -> float:
    # Match combine_station_day's float split when the outcome is still 0/1.
    if leg.h_eff == _ZERO or leg.h_eff == _ONE:
        return float(leg.h_eff) - float(leg.be)
    return float(leg.h_eff - leg.be)


def _settlement_index(
    settlements: Sequence[LegSettlement],
) -> dict[tuple[str, Side], LegSettlement]:
    index: dict[tuple[str, Side], LegSettlement] = {}
    for item in settlements:
        key = (item.rung, item.side)
        if key in index:
            raise ValueError(f"duplicate settlement for {key!r}")
        index[key] = item
    return index


def _group_buys(
    buys: Sequence[BuyFill],
    settlements: Mapping[tuple[str, Side], LegSettlement],
) -> tuple[dict[str, dict[Side, _Side]], set[tuple[str, Side]]]:
    totals: dict[tuple[str, Side], list[Decimal]] = {}
    order: list[tuple[str, Side]] = []
    for buy in buys:
        key = (buy.rung, buy.side)
        fee = buy.fee
        if fee is None:
            raise FqLossStopRefusal(ReasonCode.MISSING_FEE, f"{key!r} has no fee")
        if not buy.fee_reconciled:
            raise FqLossStopRefusal(ReasonCode.FEE_UNRECONCILED, f"{key!r} fee is not reconciled")
        if buy.qty <= 0:
            raise FqLossStopRefusal(ReasonCode.BE_OUT_OF_RANGE, f"{key!r} has a non-positive qty")
        if key not in totals:
            totals[key] = [_ZERO, _ZERO, _ZERO]
            order.append(key)
        slot = totals[key]
        slot[0] += buy.qty
        slot[1] += buy.cost
        slot[2] += fee
    grouped: dict[str, dict[Side, _Side]] = {}
    voided: set[tuple[str, Side]] = set()
    for key in order:
        qty, cost, fee = totals[key]
        be = (cost + fee) / qty
        if not (_ZERO < be < _ONE):
            raise FqLossStopRefusal(
                ReasonCode.BE_OUT_OF_RANGE,
                f"{key!r} ledger BE {be} is not in (0, 1)",
            )
        settlement = settlements.get(key)
        if settlement is None:
            raise FqLossStopRefusal(ReasonCode.MISSING_SETTLEMENT, f"{key!r} has no settlement")
        if settlement.voided:
            voided.add(key)
            continue
        side = _Side(be=be, held=settlement.held, bought=qty, sold=_ZERO, proceeds=_ZERO)
        grouped.setdefault(key[0], {})[key[1]] = side
    return grouped, voided


def _apply_exits(
    grouped: dict[str, dict[Side, _Side]],
    voided: set[tuple[str, Side]],
    exits: Sequence[ExitFill],
) -> None:
    for fill in exits:
        key = (fill.rung, fill.side)
        if key in voided:
            continue
        side = grouped.get(fill.rung, {}).get(fill.side)
        if side is None:
            raise FqLossStopRefusal(ReasonCode.INVALID_EXIT_FILL, f"{key!r} exit has no buy")
        value = per_contract_exit_v(cost=fill.cost, fee=fill.fee, sold_qty=fill.qty)
        side.sold += fill.qty
        side.proceeds += value * fill.qty


def _bundle(
    station: str,
    grouped: Mapping[str, Mapping[Side, _Side]],
) -> tuple[list[BundleLeg], list[NettingShift], Decimal]:
    legs: list[BundleLeg] = []
    shifts: list[NettingShift] = []
    exit_shift = _ZERO
    for rung, sides in grouped.items():
        yes = sides.get("yes")
        no = sides.get("no")
        paired = _ZERO
        if yes is not None and no is not None and yes.open_qty > 0 and no.open_qty > 0:
            paired = min(yes.open_qty, no.open_qty)
            shifts.append(NettingShift(rung=rung, delta_net=_ONE - yes.be - no.be))
        emissions: tuple[tuple[Side, _Side | None, bool], ...] = (
            ("yes", yes, no is not None),
            ("no", no, yes is not None),
        )
        for side_name, state, sibling in emissions:
            if state is None:
                continue
            leg, adjustment = _emit(
                station=station,
                rung=rung,
                side=side_name,
                state=state,
                paired=paired,
                sibling=sibling,
            )
            if leg is not None:
                legs.append(leg)
            exit_shift += adjustment
    return legs, shifts, exit_shift


def _emit(
    *,
    station: str,
    rung: str,
    side: Side,
    state: _Side,
    paired: Decimal,
    sibling: bool,
) -> tuple[BundleLeg | None, Decimal]:
    """One side. A fully exited side beside its sibling is a zero-variance shift.

    That keeps a single bundle row per rung, so ``combine_station_day`` never
    sees the same-rung opposite-side refusal the netting split exists to avoid.
    A lone exited leg stays in the bundle: its variance is the unexited value.
    """
    remainder = state.open_qty - paired
    if remainder < 0:
        remainder = _ZERO
    sold = state.sold
    if remainder == 0 and sold > 0 and sibling:
        return None, state.proceeds / sold - state.be
    non_paired = sold + remainder
    if non_paired <= 0:
        return None, _ZERO
    fraction = sold / non_paired
    held_pay = _ONE if state.held else _ZERO
    exit_v = state.proceeds / sold if sold > 0 else _ZERO
    h_eff = (_ONE - fraction) * held_pay + fraction * exit_v
    row = StratumRow(
        entry_ask=state.be,
        fee=_ZERO,
        held=state.held,
        station=station,
        qty=_ONE,
        side=side,
        rung=rung,
    )
    return BundleLeg(rung=rung, side=side, be=state.be, h_eff=h_eff, row=row), _ZERO
