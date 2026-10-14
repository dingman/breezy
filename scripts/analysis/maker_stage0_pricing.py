"""MAKER-S2 WP6: per-rung bid pricing that skips recomputation when nothing it reads changed.

``rule.decide_bid`` is a pure function of ``(p_no, best NO bid, NO ask, theta)`` and the two book
quotes are a pure function of the displayed frame. A rung's frame object and p_NO are both
unchanged across most decisions (a decision fires on EVERY depth frame, of any rung), and across
the base and stress passes of a variant, so the last answer per rung is reused when the frame is
the same object and ``p_no`` is equal. Answers are never cached when ``decide_bid`` raises.
"""

from __future__ import annotations

from collections.abc import Callable

from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_fill_events import DepthFrame

__all__ = ["RungPricer"]

Quote = Callable[[DepthFrame | None], tuple[float | None, float | None]]


class RungPricer:
    """``decide_bid`` on the displayed book, memoised per rung on (frame identity, p_no)."""

    def __init__(self, theta: float, quote: Quote) -> None:
        self._theta = theta
        self._quote = quote
        self._last: dict[str, tuple[DepthFrame | None, float, rule.BidDecision]] = {}

    def price(self, rung: str, frame: DepthFrame | None, p_no: float) -> rule.BidDecision:
        seen = self._last.get(rung)
        if seen is not None and seen[0] is frame and seen[1] == p_no:
            return seen[2]
        best_no_bid, no_ask = self._quote(frame)
        decided = rule.decide_bid(p_no, best_no_bid, no_ask, self._theta)
        self._last[rung] = (frame, p_no, decided)
        return decided
