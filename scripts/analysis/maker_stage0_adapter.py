"""MAKER-S2 WP6: the WP3 -> WP4 adapter (plan r4 delta (e)); pure apart from the p_NO store lookups.

Builds the ``RungSelector`` WP4 injects: at a decision instant it asks WP2 for the forecast
(``classify_p_no``; an abstention becomes an invalid ``Decision`` that drops every live rung), gates
it with WP3's ``forecast_gate``, prices each rung with ``decide_bid`` against the displayed book,
ranks with ``select_rungs`` (modal rung and neighbours excluded, held rungs ineligible but still
part of the ladder), and maps WP3's ``REASON_*`` vocabulary onto WP4's ``DROP_REASONS``.

A live rung that is outranked but still individually eligible stays desired: the spec cancels on
the p_min / b_floor / stale / day conditions only, and a re-price is a ``REPLACED`` in WP4. The
K1 rung (``k1_rung`` of the ranked selection) leads ``desired``. A rung with no displayed book is
NOT priced or ranked (it cannot become K1, displace a bookable rung or get an attempt); the rungs
the rule WOULD have wanted without one are recorded in the tracker (WP5 ``n_no_book_wants``) and
nowhere else. The tracker also counts abstentions per reason at decision instants.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_fill_events import (
    CANCEL_BFLOOR,
    CANCEL_DAYMISMATCH,
    CANCEL_PMIN,
    CANCEL_STALE,
    CENTS,
    NOT_YET_AVAILABLE,
    Decision,
    DecisionContext,
    DepthFrame,
    Desired,
    RungSelector,
)
from scripts.analysis.maker_stage0_pno import (
    FORECAST_DAY_MISMATCH,
    FORECAST_STALE,
    NO_VECTOR,
    AbstainReason,
    PNoAtInstant,
    classify_p_no,
)
from scripts.analysis.maker_stage0_pno_store import (
    NONFINITE_P_YES,
    UNKNOWN_ERA,
    PNoStore,
    Stress,
)
from scripts.analysis.maker_stage0_pricing import RungPricer

__all__ = [
    "DROP_REASON_FOR",
    "MAX_RUNGS_PASSED",
    "SelectorConfig",
    "WantTracker",
    "best_no_bid",
    "build_selector",
    "drop_reason_for",
    "no_ask",
]

#: What the driver hands WP4 as ``max_rungs`` (WP3 owns the constant; never copied).
MAX_RUNGS_PASSED: Final[int] = rule.MAX_RUNGS

DROP_REASON_FOR: Final[Mapping[str, str]] = {
    rule.REASON_P_NO_BELOW_P_MIN: CANCEL_PMIN,
    rule.REASON_B_MAX_BELOW_FLOOR: CANCEL_BFLOOR,
    rule.REASON_BID_BELOW_FLOOR: CANCEL_BFLOOR,
    rule.REASON_FORECAST_DAY_MISMATCH: CANCEL_DAYMISMATCH,
    rule.REASON_FORECAST_STALE: CANCEL_STALE,
    rule.REASON_FORECAST_NOT_YET_AVAILABLE: NOT_YET_AVAILABLE,
    # WP2 abstentions that have no WP3 twin: no usable vector at this instant.
    NO_VECTOR: NOT_YET_AVAILABLE,
    UNKNOWN_ERA: NOT_YET_AVAILABLE,
    NONFINITE_P_YES: NOT_YET_AVAILABLE,
    FORECAST_DAY_MISMATCH: CANCEL_DAYMISMATCH,
    FORECAST_STALE: CANCEL_STALE,
}


def drop_reason_for(reason: str) -> str:
    """The WP4 drop reason for a WP2/WP3 reason string; unknown strings are a bug, not a default."""
    try:
        return DROP_REASON_FOR[reason]
    except KeyError:
        raise ValueError(f"no drop reason maps from {reason!r}") from None


@dataclass
class WantTracker:
    """Records (never decides) rungs the rule wanted while no book existed for them."""

    wanted_without_book: set[str] = field(default_factory=set)
    abstentions: Counter[str] = field(default_factory=Counter)  # decision instants, by reason


@dataclass(frozen=True, kw_only=True)
class SelectorConfig:
    store: PNoStore
    station: str
    day: dt.date
    stress: Stress
    delta_ns: int
    theta: float
    lower_edges_f: Mapping[str, float]


def best_no_bid(frame: DepthFrame) -> float | None:
    """The best NO bid = 1 - the lowest displayed YES ask (size-0 pads are never levels)."""
    asks = [price for price, size in frame.yes_asks if size > 0]
    return (CENTS - min(asks)) / CENTS if asks else None


def no_ask(frame: DepthFrame) -> float | None:
    """The NO ask = 1 - the highest displayed YES bid."""
    bids = [price for price, size in frame.yes_bids if size > 0]
    return (CENTS - max(bids)) / CENTS if bids else None


def _quote(frame: DepthFrame | None) -> tuple[float | None, float | None]:
    return (None, None) if frame is None else (best_no_bid(frame), no_ask(frame))


def _price_rungs(
    p_yes: Mapping[str, float], ctx: DecisionContext, pricer: RungPricer
) -> tuple[dict[str, float | None], dict[str, str | None]]:
    bids: dict[str, float | None] = {}
    reasons: dict[str, str | None] = {}
    for rung, p in p_yes.items():
        if rung in ctx.held:
            bids[rung], reasons[rung] = None, None  # filled: ineligible, still on the ladder
            continue
        decided = pricer.price(rung, ctx.books.get(rung), 1.0 - p)
        bids[rung], reasons[rung] = decided.bid, decided.reason
    return bids, reasons


def _dropped(
    ctx: DecisionContext, desired: tuple[Desired, ...], reasons: Mapping[str, str | None]
) -> dict[str, str]:
    kept = {d.rung_id for d in desired}
    return {
        rung: drop_reason_for(reasons.get(rung) or rule.REASON_P_NO_BELOW_P_MIN)
        for rung in ctx.live_bids
        if rung not in kept
    }


def _desired(
    chosen: tuple[str, ...], bids: Mapping[str, float | None], ctx: DecisionContext
) -> tuple[Desired, ...]:
    ranked = list(chosen)
    lead = rule.k1_rung(chosen)
    if lead is not None:
        ranked.remove(lead)
        ranked.insert(0, lead)
    for rung in ctx.live_bids:  # outranked but still eligible: kept, never silently cancelled
        if rung not in ranked and bids.get(rung) is not None:
            ranked.append(rung)
    priced = [(r, bids[r]) for r in ranked]
    return tuple(Desired(r, round(b * CENTS)) for r, b in priced if b is not None)


def _abstain(served: AbstainReason, tracker: WantTracker | None) -> Decision:
    if tracker is not None:
        tracker.abstentions[served.reason] += 1
    return Decision(drop_reason=drop_reason_for(served.reason), forecast_valid=False)


@dataclass
class _Memo:
    """What one selector may reuse between decisions: rung prices and per-vector ladder plans."""

    pricer: RungPricer
    plans: dict[int, tuple[Mapping[str, float], rule.LadderPlan]] = field(default_factory=dict)

    def plan_for(self, p_yes: Mapping[str, float], edges: Mapping[str, float]) -> rule.LadderPlan:
        """One plan per p_yes view (the store keeps one view per cycle; the ref pins its id)."""
        hit = self.plans.get(id(p_yes))
        if hit is not None and hit[0] is p_yes:
            return hit[1]
        plan = rule.ladder_plan(p_yes, edges)
        self.plans[id(p_yes)] = (p_yes, plan)
        return plan


def _decide(
    cfg: SelectorConfig, tracker: WantTracker | None, memo: _Memo, ctx: DecisionContext
) -> Decision:
    shift = abs(cfg.delta_ns)
    served = classify_p_no(cfg.store, cfg.station, cfg.day, ctx.now_ns - shift, stress=cfg.stress)
    if isinstance(served, AbstainReason):
        return _abstain(served, tracker)
    age = ctx.now_ns - (served.available_at_ns + shift)
    gate = rule.forecast_gate(served.vector.climate_day, cfg.day, age)
    if gate is not None:
        return Decision(drop_reason=drop_reason_for(gate), forecast_valid=False)
    return _priced(cfg, tracker, memo, ctx, served)


def _priced(
    cfg: SelectorConfig,
    tracker: WantTracker | None,
    memo: _Memo,
    ctx: DecisionContext,
    served: PNoAtInstant,
) -> Decision:
    p_yes = served.p_yes_point_live
    plan = memo.plan_for(p_yes, cfg.lower_edges_f)
    bids, reasons = _price_rungs(p_yes, ctx, memo.pricer)
    unbooked = [r for r in bids if r not in ctx.books]
    bookable = {r: (b if r in ctx.books else None) for r, b in bids.items()} if unbooked else bids
    chosen = plan.select(bookable)
    if tracker is not None and unbooked:  # hindsight, write-only: what the rule would want unbooked
        wanted = plan.select(bids)
        tracker.wanted_without_book.update(r for r in wanted if r not in ctx.books)
    desired = _desired(chosen, bookable, ctx)
    return Decision(
        desired=desired,
        forecast_valid=True,
        dropped=_dropped(ctx, desired, reasons),
    )


def build_selector(cfg: SelectorConfig, tracker: WantTracker | None = None) -> RungSelector:
    """The pure-in-effect selector WP4 calls at each decision instant (tracker is write-only)."""
    memo = _Memo(RungPricer(cfg.theta, _quote))

    def selector(ctx: DecisionContext, /) -> Decision:
        return _decide(cfg, tracker, memo, ctx)

    return selector
