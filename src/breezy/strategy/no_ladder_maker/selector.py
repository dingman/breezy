"""The live rung selector, ported from `maker_stage0_adapter` + `maker_stage0_pricing`.

At a decision instant it asks ``classify_p_no`` for the forecast (an abstention becomes an invalid
``Decision`` that drops every live rung), gates it with ``forecast_gate``, prices each rung with
``decide_bid`` against the displayed book, ranks with ``ladder_plan(...).select`` (modal rung and
neighbours excluded, held rungs ineligible but still on the ladder), and maps the rule's
``REASON_*`` vocabulary onto the ``DROP_REASONS``. Logic is the Stage 0 adapter's, line for line;
the rule constants arrive via ``SelectorConfig.params``.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final

from breezy.strategy.no_ladder_maker import rule
from breezy.strategy.no_ladder_maker.params import MakerRuleParams
from breezy.strategy.no_ladder_maker.pno import (
    FORECAST_DAY_MISMATCH,
    FORECAST_STALE,
    NO_VECTOR,
    AbstainReason,
    PNoAtInstant,
    classify_p_no,
)
from breezy.strategy.no_ladder_maker.pno_store import (
    NONFINITE_P_YES,
    UNKNOWN_ERA,
    PNoStore,
    Stress,
)
from breezy.strategy.no_ladder_maker.records import (
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
)

__all__ = [
    "DROP_REASON_FOR",
    "RungPricer",
    "RungSelector",
    "SelectorConfig",
    "WantTracker",
    "best_no_bid",
    "build_selector",
    "drop_reason_for",
    "no_ask",
]

RungSelector = Callable[[DecisionContext], Decision]
Quote = Callable[[DepthFrame | None], tuple[float | None, float | None]]

DROP_REASON_FOR: Final[Mapping[str, str]] = {
    rule.REASON_P_NO_BELOW_P_MIN: CANCEL_PMIN,
    rule.REASON_B_MAX_BELOW_FLOOR: CANCEL_BFLOOR,
    rule.REASON_BID_BELOW_FLOOR: CANCEL_BFLOOR,
    rule.REASON_FORECAST_DAY_MISMATCH: CANCEL_DAYMISMATCH,
    rule.REASON_FORECAST_STALE: CANCEL_STALE,
    rule.REASON_FORECAST_NOT_YET_AVAILABLE: NOT_YET_AVAILABLE,
    # p_NO abstentions that have no rule twin: no usable vector at this instant.
    NO_VECTOR: NOT_YET_AVAILABLE,
    UNKNOWN_ERA: NOT_YET_AVAILABLE,
    NONFINITE_P_YES: NOT_YET_AVAILABLE,
    FORECAST_DAY_MISMATCH: CANCEL_DAYMISMATCH,
    FORECAST_STALE: CANCEL_STALE,
}


def drop_reason_for(reason: str) -> str:
    """The drop reason for a p_NO/rule reason string; unknown strings are a bug, not a default."""
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
    params: MakerRuleParams


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


class RungPricer:
    """``decide_bid`` on the displayed book, memoised per rung on (frame identity, p_no)."""

    def __init__(self, theta: float, quote: Quote, params: MakerRuleParams) -> None:
        self._theta = theta
        self._quote = quote
        self._params = params
        self._last: dict[str, tuple[DepthFrame | None, float, rule.BidDecision]] = {}

    def price(self, rung: str, frame: DepthFrame | None, p_no: float) -> rule.BidDecision:
        seen = self._last.get(rung)
        if seen is not None and seen[0] is frame and seen[1] == p_no:
            return seen[2]
        best_bid, ask = self._quote(frame)
        decided = rule.decide_bid(p_no, best_bid, ask, self._theta, self._params)
        self._last[rung] = (frame, p_no, decided)
        return decided


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

    def plan_for(
        self, p_yes: Mapping[str, float], edges: Mapping[str, float], params: MakerRuleParams
    ) -> rule.LadderPlan:
        """One plan per p_yes view (the store keeps one view per cycle; the ref pins its id)."""
        hit = self.plans.get(id(p_yes))
        if hit is not None and hit[0] is p_yes:
            return hit[1]
        plan = rule.ladder_plan(p_yes, edges, params)
        self.plans[id(p_yes)] = (p_yes, plan)
        return plan


def _decide(
    cfg: SelectorConfig, tracker: WantTracker | None, memo: _Memo, ctx: DecisionContext
) -> Decision:
    shift = abs(cfg.delta_ns)
    served = classify_p_no(
        cfg.store,
        cfg.station,
        cfg.day,
        ctx.now_ns - shift,
        stress=cfg.stress,
        stale_h=cfg.params.stale_h,
    )
    if isinstance(served, AbstainReason):
        return _abstain(served, tracker)
    age = ctx.now_ns - (served.available_at_ns + shift)
    gate = rule.forecast_gate(served.vector.climate_day, cfg.day, age, cfg.params)
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
    plan = memo.plan_for(p_yes, cfg.lower_edges_f, cfg.params)
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
    """The pure-in-effect selector called at each decision instant (tracker is write-only)."""
    memo = _Memo(RungPricer(cfg.theta, _quote, cfg.params))

    def selector(ctx: DecisionContext, /) -> Decision:
        return _decide(cfg, tracker, memo, ctx)

    return selector
