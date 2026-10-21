"""The spec v0.3 section 3 decision rule (NO-leg maker bids), ported from `maker_stage0_rule`.

Logic is the Stage 0 rule line for line; the P_MIN / E_MIN / B_FLOOR / B_CAP / MAX_RUNGS /
STALE_H / CANCEL_LST constants arrive via `MakerRuleParams`, never as module globals.
No I/O, no clock reads, no Nautilus: every input is an argument.

Prices are handled in integer cents internally so the 1 cent grid never suffers
float drift; public results are floats on that grid.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from breezy.strategy.no_ladder_maker.params import MakerRuleParams

# Refusal / abstain reasons: the implicit interface WP4/WP6 compare against.
REASON_P_NO_BELOW_P_MIN: Final[str] = "p_no_below_p_min"
REASON_B_MAX_BELOW_FLOOR: Final[str] = "b_max_below_floor"
REASON_BID_BELOW_FLOOR: Final[str] = "bid_below_floor"
REASON_FORECAST_DAY_MISMATCH: Final[str] = "forecast_day_mismatch"
REASON_FORECAST_STALE: Final[str] = "forecast_stale"
REASON_FORECAST_NOT_YET_AVAILABLE: Final[str] = "forecast_not_yet_available"

CENTS_PER_DOLLAR: Final[int] = 100
_EPS: Final[float] = 1e-9
_NS_PER_S: Final[int] = 1_000_000_000
_NS_PER_H: Final[int] = 3_600 * _NS_PER_S
_NS_PER_DAY: Final[int] = 24 * _NS_PER_H
_OBS_RUNG_F: Final[float] = 2.0  # spec line 98: within 1 rung (2 F)
_INTEGER_C_WIDEN_F: Final[float] = 1.8  # spec line 99
_LISTING_DEADLINE_UTC: Final[dt.time] = dt.time(12, 0)  # spec line 123: D-1 12:00Z


@dataclass(frozen=True)
class BidDecision:
    """Outcome of the bid-price step: a price, or a refusal reason (never both)."""

    bid: float | None
    reason: str | None


def _cents(price: float) -> int:
    return round(price * CENTS_PER_DOLLAR)


def _validate_probability(value: float, name: str) -> None:
    if math.isnan(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")


def _validate_p_no(p_no: float) -> None:
    _validate_probability(p_no, "p_no")


def _validate_theta(theta: float) -> None:
    if not math.isfinite(theta) or theta < 0.0:
        raise ValueError(f"theta must be finite and >= 0, got {theta!r}")


def _p_no_below_p_min(p_no: float, params: MakerRuleParams) -> bool:
    """The one strict P_MIN comparison shared by `decide_bid` and `select_rungs`."""
    return p_no < params.p_min


def b_max(p_no: float, theta: float, params: MakerRuleParams) -> float | None:
    """Largest 1 cent b <= min(B_CAP, p_no - E_MIN - theta*b*(1-b)); spec line 83.

    Returns None when that value is below B_FLOOR (spec line 84).
    """
    _validate_p_no(p_no)
    _validate_theta(theta)
    floor_c = _cents(params.b_floor)
    for cent in range(_cents(params.b_cap), floor_c - 1, -1):
        b = cent / CENTS_PER_DOLLAR
        if b + theta * b * (1.0 - b) <= p_no - params.e_min + _EPS:
            return b
    return None


def decide_bid(
    p_no: float,
    best_no_bid: float | None,
    no_ask: float | None,
    theta: float,
    params: MakerRuleParams,
) -> BidDecision:
    """Spec lines 82-90; `theta` must be finite and >= 0.

    `best_no_bid` excludes our own order (size-0 pad ignored).

    `best_no_bid` None is the empty NO bid side (price = min(b_max, no_ask - 0.01),
    spec line 88); `no_ask` None is the empty YES bid side (no ask clamp).
    """
    _validate_p_no(p_no)
    if _p_no_below_p_min(p_no, params):
        return BidDecision(None, REASON_P_NO_BELOW_P_MIN)
    cap = b_max(p_no, theta, params)
    if cap is None:
        return BidDecision(None, REASON_B_MAX_BELOW_FLOOR)
    limits = [_cents(cap)]
    if best_no_bid is not None:
        limits.append(_cents(best_no_bid) + 1)
    if no_ask is not None:
        limits.append(_cents(no_ask) - 1)
    bid_c = min(limits)
    if bid_c < _cents(params.b_floor):
        return BidDecision(None, REASON_BID_BELOW_FLOOR)
    return BidDecision(bid_c / CENTS_PER_DOLLAR, None)


def bid_price(
    p_no: float,
    best_no_bid: float | None,
    no_ask: float | None,
    theta: float,
    params: MakerRuleParams,
) -> float | None:
    """The bid, or None when the rule cancels / refuses."""
    return decide_bid(p_no, best_no_bid, no_ask, theta, params).bid


def forecast_gate(
    vector_day: dt.date | None, station_day: dt.date, age_ns: int, params: MakerRuleParams
) -> str | None:
    """Spec lines 77-81: None if the forecast may be used, else the abstain reason."""
    if vector_day != station_day:
        return REASON_FORECAST_DAY_MISMATCH
    if age_ns < 0:  # available_at in the future of `now`: lookahead, never fresh
        return REASON_FORECAST_NOT_YET_AVAILABLE
    if age_ns > params.stale_h * _NS_PER_H:
        return REASON_FORECAST_STALE
    return None


def _ladder_order(rungs: Mapping[str, float], lower_edges_f: Mapping[str, float]) -> list[str]:
    """Rung keys in ascending lower-edge order; raises if the edges cannot order them."""
    if set(lower_edges_f) != set(rungs):
        raise ValueError("lower_edges_f keys must equal the p_yes_by_rung keys")
    edges = list(lower_edges_f.values())
    if any(math.isnan(e) for e in edges) or len(set(edges)) != len(edges):
        raise ValueError("lower_edges_f must be non-NaN and distinct to order the ladder")
    return sorted(rungs, key=lambda rung: lower_edges_f[rung])


@dataclass(frozen=True, slots=True)
class LadderPlan:
    """The bid-independent half of `select_rungs`, built once per forecast vector.

    Validation, ladder order, the modal rung, and the P_MIN test depend only on the
    probabilities and the edges; a decision then only filters by its bids.
    """

    rungs: tuple[str, ...]
    modal: int
    p_yes: tuple[float, ...]
    p_min_ok: tuple[bool, ...]
    b_floor: float
    max_rungs: int

    def select(self, bids: Mapping[str, float | None]) -> tuple[str, ...]:
        floor = _cents(self.b_floor)
        eligible: list[tuple[float, int]] = []
        for idx, rung in enumerate(self.rungs):
            bid = bids.get(rung)
            if abs(idx - self.modal) <= 1 or bid is None or _cents(bid) < floor:
                continue
            if self.p_min_ok[idx]:
                eligible.append((self.p_yes[idx], idx))
        eligible.sort()
        return tuple(self.rungs[idx] for _, idx in eligible[: self.max_rungs])


def ladder_plan(
    p_yes_by_rung: Mapping[str, float],
    lower_edges_f: Mapping[str, float],
    params: MakerRuleParams,
) -> LadderPlan:
    """Validate and order the ladder (`select_rungs`' bid-independent half)."""
    for rung, p_yes in p_yes_by_rung.items():
        _validate_probability(p_yes, f"p_yes[{rung!r}]")
    rungs = tuple(_ladder_order(p_yes_by_rung, lower_edges_f))
    ordered = tuple(p_yes_by_rung[rung] for rung in rungs)
    modal = max(range(len(rungs)), key=lambda i: ordered[i]) if rungs else 0
    p_min_ok = tuple(not _p_no_below_p_min(1.0 - p, params) for p in ordered)
    return LadderPlan(rungs, modal, ordered, p_min_ok, params.b_floor, params.max_rungs)


def select_rungs(
    p_yes_by_rung: Mapping[str, float],
    bids: Mapping[str, float | None],
    *,
    lower_edges_f: Mapping[str, float],
    params: MakerRuleParams,
) -> tuple[str, ...]:
    """Spec lines 125-127: up to `params.max_rungs` rungs, lowest p_YES first.

    The ladder is ordered by `lower_edges_f` (ascending), never by mapping insertion
    order, so adjacency is deterministic. Eligible: 1 - p_yes passes the shared
    strict P_MIN test, not the modal rung (argmax p_yes; the lowest ladder index
    wins a tie) nor adjacent to it, and a bid >= B_FLOOR in `bids` (missing =
    ineligible). Equal p_yes ties rank by ascending ladder index. Raises ValueError
    for any p_yes outside [0, 1] / NaN or an unorderable ladder.
    """
    return ladder_plan(p_yes_by_rung, lower_edges_f, params).select(bids)


def k1_rung(selected: tuple[str, ...]) -> str | None:
    """The one-rung (max_rungs=1) subset: the first-ranked selected rung (r4 delta (e))."""
    return selected[0] if selected else None


def _utc_ns(stamp: dt.datetime) -> int:
    return int(stamp.timestamp()) * _NS_PER_S


def hard_cancel_ns(day: dt.date, std_offset_hours: int, params: MakerRuleParams) -> int:
    """`day` `params.cancel_lst` (09:00 local standard time) as integer UTC ns (spec line 96).

    `std_offset_hours` is the station's STANDARD-time UTC offset, east-positive
    (US stations are negative: -8 Pacific, -5 Eastern). Whole hours only.
    """
    local = dt.datetime.combine(day, params.cancel_lst, tzinfo=dt.UTC)
    return _utc_ns(local) - std_offset_hours * _NS_PER_H


def gtd_expire_ns(now_ns: int, hard_cancel: int, permit_expiry_ns: int) -> int:
    """min(cancel_lst, permit expiry, end of the booking UTC day); spec lines 91-92.

    The r4 delta (i)10 caveat applies: a midnight cut re-posts at the same
    instant in replay, live waits for the next event.
    """
    end_of_utc_day = (now_ns // _NS_PER_DAY + 1) * _NS_PER_DAY
    return min(hard_cancel, permit_expiry_ns, end_of_utc_day)


def obs_cancel(upper_f: float, lower_edge_f: float, integer_c: bool = False) -> bool:
    """Observation within 1 rung (2 F) of the rung's lower edge; spec lines 98-99.

    Integer-C observations widen the observed upper bound by 1.8 F.
    """
    upper = upper_f + (_INTEGER_C_WIDEN_F if integer_c else 0.0)
    return upper >= lower_edge_f - _OBS_RUNG_F - _EPS


def listed_in_time(listed_ns: int | None, day: dt.date) -> bool:
    """Spec line 123: S must be listed by D-1 12:00Z, else abstain."""
    if listed_ns is None:
        return False
    deadline = dt.datetime.combine(day - dt.timedelta(days=1), _LISTING_DEADLINE_UTC, tzinfo=dt.UTC)
    return listed_ns <= _utc_ns(deadline)
