"""YES-first shrunk variance for an overround station-day (r2 §4.2, r3 §4.2).

Feasible days (Σ q ≤ 1) do not use this arithmetic: ``bundle_variance``
calls ``combine_station_day`` and returns that variance unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, NoReturn

from breezy.settlement.current_rung_hold_v2 import (
    StationDayAdmissionRefusal,
    StratumRow,
    break_even_row,
    combine_station_day,
)

Side = Literal["yes", "no"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ShrunkJoint:
    """YES-first shrink of an overround day (r2 §4.2)."""

    kappa: float
    masses: tuple[float, ...]
    variance: float
    drifts: tuple[float, ...]


def shrunk_joint(rows: Sequence[StratumRow]) -> ShrunkJoint:
    """YES-first shrink. Refuses when Σ_NO q > 1 (κ would be negative)."""
    material = tuple(rows)
    if not material:
        raise ValueError("shrunk joint is undefined for an empty station-day")
    parts = _parts(material)
    _refuse_same_rung(material)
    sum_no, sum_yes = _side_totals(parts)
    if sum_no > 1.0:
        _refuse("SIGMA_NO_EXCEEDS_ONE", f"sum of NO cell probabilities is {sum_no!r}")
    if sum(parts.qs) <= 1.0:
        raise ValueError("shrunk joint is only defined when sum q > 1")
    # ΣNO ≤ 1 (refused above) and Σq > 1 imply ΣYES = Σq − ΣNO > 0, so a
    # "no YES mass" refusal is unreachable and is not a branch here.
    kappa = (1.0 - sum_no) / sum_yes
    masses = tuple(
        kappa * q if side == "yes" else q for q, side in zip(parts.qs, parts.sides, strict=True)
    )
    variance, drifts = _enumerate(parts.bes, parts.sides, masses)
    return ShrunkJoint(kappa=kappa, masses=masses, variance=variance, drifts=drifts)


def bundle_variance(rows: Sequence[StratumRow]) -> float:
    """Feasible days reuse ``combine_station_day``. Overround days use the shrink.

    The feasible variance is not re-implemented here. A same-rung YES+NO
    pair that reached this function was not netted first; that is a refusal.
    """
    material = tuple(rows)
    if not material:
        return 0.0
    _refuse_same_rung(material)
    parts = _parts(material)
    sum_no, _sum_yes = _side_totals(parts)
    if sum_no > 1.0:
        _refuse("SIGMA_NO_EXCEEDS_ONE", f"sum of NO cell probabilities is {sum_no!r}")
    if sum(parts.qs) > 1.0:
        return shrunk_joint(material).variance
    try:
        return combine_station_day(material).variance
    except StationDayAdmissionRefusal as exc:
        _refuse("ADMISSION_REFUSED", str(exc))


def _refuse(code: str, detail: str) -> NoReturn:
    # Lazy: this module must not import the core at load time (the core
    # imports us). The refusal type stays owned by the core.
    from breezy.analysis.fq_loss_stop_core import FqLossStopRefusal, ReasonCode

    raise FqLossStopRefusal(ReasonCode[code], detail)


@dataclass(frozen=True, slots=True)
class _Parts:
    bes: tuple[float, ...]
    qs: tuple[float, ...]
    sides: tuple[Side, ...]


def _parts(rows: Sequence[StratumRow]) -> _Parts:
    bes: list[float] = []
    qs: list[float] = []
    sides: list[Side] = []
    for row in rows:
        side: Side = row.side
        be = float(break_even_row(row.entry_ask, row.fee))
        bes.append(be)
        qs.append(be if side == "yes" else 1.0 - be)
        sides.append(side)
    return _Parts(tuple(bes), tuple(qs), tuple(sides))


def _side_totals(parts: _Parts) -> tuple[float, float]:
    paired = zip(parts.qs, parts.sides, strict=True)
    sum_no = sum(q for q, side in paired if side == "no")
    paired = zip(parts.qs, parts.sides, strict=True)
    sum_yes = sum(q for q, side in paired if side == "yes")
    return sum_no, sum_yes


def _refuse_same_rung(rows: Sequence[StratumRow]) -> None:
    seen: dict[str, Side] = {}
    for row in rows:
        if row.rung is None:
            continue
        previous = seen.get(row.rung)
        if previous is not None and previous != row.side:
            _refuse("ADMISSION_REFUSED", f"rung {row.rung!r} carries both a YES and a NO leg")
        seen[row.rung] = row.side


def _enumerate(
    bes: tuple[float, ...],
    sides: tuple[Side, ...],
    masses: tuple[float, ...],
) -> tuple[float, tuple[float, ...]]:
    """Exact mean and second moment of Σ (H_i − BE_i) over k rung wins plus other."""
    k = len(bes)
    probs = [*masses, 1.0 - sum(masses)]
    expect_h = [0.0] * k
    mean = 0.0
    second = 0.0
    for outcome, prob in enumerate(probs):
        x = 0.0
        for i in range(k):
            on_rung = outcome == i
            h = (1.0 if on_rung else 0.0) if sides[i] == "yes" else (0.0 if on_rung else 1.0)
            expect_h[i] += prob * h
            x += h - bes[i]
        mean += prob * x
        second += prob * x * x
    drifts = tuple(eh - be for eh, be in zip(expect_h, bes, strict=True))
    return second - mean * mean, drifts
