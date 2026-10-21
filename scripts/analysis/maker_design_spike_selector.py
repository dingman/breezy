"""MAKER design card 2 (SPIKE-BID): a forecast-free rung selector for the Stage 0 simulator.

Rests a NO bid on a far-tail rung that has been quiet for an hour, so that only a YES-price jump
to 20c or more (a buyer print at NO price <= the bid) can fill it. No NBP, no truth.

Eligibility of a rung (every clause must hold at the decision instant ``now``):

* it is at least ``MODE_STEPS`` ladder steps from the book's mode (the rung with the highest YES
  mid; a missing bid counts as 0c and a missing ask as 100c; ties go to the lowest ladder index);
* the best YES ask over the trailing ``TRAIL_NS`` was at most ``TRAIL_ASK_MAX_C`` (a venue seed
  ask of 0.60 or 0.99 inside the hour disqualifies; an empty ask side counts as 100c);
* the displayed best YES ask is at most ``NOW_ASK_MAX_C`` and the best YES bid at most
  ``NOW_BID_MAX_C`` (an empty bid side passes, an empty ask side fails);
* it is not held, and its bid ``min(B_CAP_C, best NO bid + 1, NO ask - 1)`` is at least
  ``B_FLOOR_C`` (the same clamp as ``maker_stage0_rule.decide_bid``, without the p_NO terms).

The trailing window is inclusive of the book in force at ``now``, so the ``NOW_ASK_MAX_C`` clause
is implied by the ``TRAIL_ASK_MAX_C`` clause on consistent inputs; both are kept as the card
states them. At most ``MAX_RUNGS`` rungs are desired, rungs already resting first (a live rung
that is still eligible is never silently re-ranked away), then the lowest ask, then the farthest
from the mode. A live rung that is no longer desired is dropped with ``CANCEL_BFLOOR``.

The simulator calls the selector once per pass and requires it to be pure, so the trailing-ask
tables are built once from the day's depth events and read here by bisect; a query at ``now``
never sees a frame after ``now``.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from scripts.analysis.maker_stage0_fill_events import (
    CANCEL_BFLOOR,
    CENTS,
    NS_PER_MIN,
    Decision,
    DecisionContext,
    DepthFrame,
    Desired,
    Event,
    Kind,
    RungSelector,
)

__all__ = [
    "MAX_RUNGS",
    "AskTrail",
    "ask_trails",
    "build_spike_selector",
    "spike_bid_cents",
    "trailing_max_ask",
]

MODE_STEPS: Final[int] = 2
TRAIL_NS: Final[int] = 60 * NS_PER_MIN
TRAIL_ASK_MAX_C: Final[int] = 8
NOW_ASK_MAX_C: Final[int] = 12
NOW_BID_MAX_C: Final[int] = 4
B_CAP_C: Final[int] = 80
B_FLOOR_C: Final[int] = 70
MAX_RUNGS: Final[int] = 2


@dataclass(frozen=True, slots=True)
class AskTrail:
    """One rung's best YES ask (cents; 100 for an empty ask side) at each of its depth frames."""

    ts: tuple[int, ...]
    ask_c: tuple[int, ...]


def _best_ask_c(frame: DepthFrame) -> int | None:
    asks = [price for price, size in frame.yes_asks if size > 0]
    return min(asks) if asks else None


def _best_bid_c(frame: DepthFrame) -> int | None:
    bids = [price for price, size in frame.yes_bids if size > 0]
    return max(bids) if bids else None


def _mid2(frame: DepthFrame) -> int:
    """Twice the YES mid in whole cents, with the unquoted side at its extreme."""
    ask = _best_ask_c(frame)
    return (_best_bid_c(frame) or 0) + (CENTS if ask is None else ask)


def ask_trails(events: Iterable[Event]) -> dict[str, AskTrail]:
    """The per-rung ask series of a canonically ordered event stream (depth frames only)."""
    series: dict[str, tuple[list[int], list[int]]] = {}
    for event in events:
        frame = event.payload
        if event.kind is not Kind.DEPTH or not isinstance(frame, DepthFrame):
            continue
        ts, asks = series.setdefault(frame.rung_id, ([], []))
        ask = _best_ask_c(frame)
        ts.append(event.ts_ns)
        asks.append(CENTS if ask is None else ask)
    return {rung: AskTrail(tuple(ts), tuple(asks)) for rung, (ts, asks) in series.items()}


def trailing_max_ask(trail: AskTrail | None, now_ns: int) -> int | None:
    """Max best ask over the book states in force during ``[now - TRAIL_NS, now]``, else None."""
    if trail is None:
        return None
    hi = bisect_right(trail.ts, now_ns)
    if hi == 0:
        return None
    lo = max(bisect_right(trail.ts, now_ns - TRAIL_NS) - 1, 0)  # the state in force at the start
    return max(trail.ask_c[lo:hi])


def spike_bid_cents(ask_c: int | None, bid_c: int | None) -> int | None:
    """``min(80c, best NO bid + 1, NO ask - 1)`` when it is at least 70c, else None."""
    limits = [B_CAP_C]
    if ask_c is not None:
        limits.append(CENTS - ask_c + 1)
    if bid_c is not None:
        limits.append(CENTS - bid_c - 1)
    bid = min(limits)
    return bid if bid >= B_FLOOR_C else None


def _bid_if_eligible(frame: DepthFrame, trail: AskTrail | None, now_ns: int) -> int | None:
    ask, bid = _best_ask_c(frame), _best_bid_c(frame)
    if ask is None or ask > NOW_ASK_MAX_C or (bid is not None and bid > NOW_BID_MAX_C):
        return None
    trailing = trailing_max_ask(trail, now_ns)
    if trailing is None or trailing > TRAIL_ASK_MAX_C:
        return None
    return spike_bid_cents(ask, bid)


def build_spike_selector(
    lower_edges_f: Mapping[str, float], trails: Mapping[str, AskTrail]
) -> RungSelector:
    """The pure selector; ``lower_edges_f`` orders the ladder, ``trails`` is read-only."""
    order = tuple(sorted(lower_edges_f, key=lower_edges_f.__getitem__))
    index = {rung: i for i, rung in enumerate(order)}

    def selector(ctx: DecisionContext, /) -> Decision:
        booked = [r for r in order if r in ctx.books]
        ranked: list[tuple[tuple[bool, int, int, int], Desired]] = []
        if booked:
            mode = index[max(booked, key=lambda r: _mid2(ctx.books[r]))]
            for rung in booked:
                gap = abs(index[rung] - mode)
                if gap < MODE_STEPS or rung in ctx.held:
                    continue
                frame = ctx.books[rung]
                bid = _bid_if_eligible(frame, trails.get(rung), ctx.now_ns)
                if bid is not None:
                    key = (rung not in ctx.live_bids, _best_ask_c(frame) or 0, -gap, index[rung])
                    ranked.append((key, Desired(rung, bid)))
        desired = tuple(d for _, d in sorted(ranked, key=lambda item: item[0]))[:MAX_RUNGS]
        kept = {d.rung_id for d in desired}
        dropped = {rung: CANCEL_BFLOOR for rung in ctx.live_bids if rung not in kept}
        return Decision(desired=desired, forecast_valid=True, dropped=dropped)

    return selector
