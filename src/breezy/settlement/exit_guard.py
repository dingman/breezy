"""Guards for EXEC_SPINE R-9 settlement-as-exit, landed ahead of the actor.

Pure module -- no I/O, clock, or Nautilus objects. `docs/plans/EXEC_SPINE_
2026-09-01.md` Sec R-9, "R-4 review amendments" (2026-09-02), names two
defects R-9's own guard must close before any settlement close is ever
booked:

1. The per-trade return `r_i = realized_pnl / (avg_px_open * qty *
   multiplier)` divides by zero for an unpriced forward
   (`avg_px_open` zero or absent). An unpriced forward is not a real
   zero-cost entry ([[L-17]]): it is refused and excluded from the BCa
   bootstrap sample with an explicit, counted reason, never substituted
   with a price and never silently dropped.
2. Settlement-as-exit reaches Nautilus through
   `ExecutionClient._send_order_status_report`, which bypasses
   `_submit_order`'s refusal latch entirely. The settlement exit path must
   consult the SAME latch (`PolymarketUSExecutionClient.trading_refusals`,
   `exec/client.py`) BEFORE closing any position, and must never close a
   position it cannot attribute to a Breezy order
   (`external_order_claims`, `trading/config.py:91`).

Per [[L-22]], `assert_settlement_close_permitted` is written as the ONE gate
a future `SettlementExitActor` calls immediately before it builds the
synthetic `OrderStatusReport` -- not a sibling helper the call site is
trusted to remember. It raises rather than returning a boolean specifically
so a call site cannot silently discard a refused verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "SettlementCloseRefused",
    "TradeReturnInput",
    "TradeReturnSample",
    "assert_settlement_close_permitted",
    "compute_trade_returns",
]

#: The single reason string used whenever a trade cannot be priced. Kept as
#: one constant so both the zero-price and absent-price branches -- and the
#: zero-denominator branch, which is the same hazard reached a different way
#: -- produce an identical, greppable, matchable reason.
_UNPRICED_FORWARD_REASON: str = (
    "unpriced forward: avg_px_open is zero, absent, or produces a zero "
    "return denominator (avg_px_open * qty * multiplier); refused rather "
    "than divided or substituted with a price (see LESSONS.md L-17)"
)


@dataclass(frozen=True, kw_only=True)
class TradeReturnInput:
    """One closed trade's inputs to the per-trade net return.

    `avg_px_open` is `Decimal | None` on purpose: `None` is how an unpriced
    forward is represented upstream, and a `Decimal(0)` sentinel would be
    indistinguishable from a real zero price. Both are refused identically.
    """

    trade_id: str
    realized_pnl: Decimal
    avg_px_open: Decimal | None
    qty: Decimal
    multiplier: Decimal = Decimal(1)


@dataclass(frozen=True, kw_only=True)
class TradeReturnSample:
    """The BCa bootstrap's raw material: included returns plus an explicit,
    counted, attributable exclusion list. Never fewer entries than trades
    passed in across both tuples combined."""

    included: tuple[tuple[str, Decimal], ...]
    excluded: tuple[tuple[str, str], ...]


def compute_trade_returns(trades: Sequence[TradeReturnInput]) -> TradeReturnSample:
    """Compute `r_i` for every priced trade; exclude, never divide, the rest.

    A trade is excluded -- with `_UNPRICED_FORWARD_REASON` -- whenever
    `avg_px_open` is `None`, `avg_px_open` is zero, or the full denominator
    `avg_px_open * qty * multiplier` is zero (a zero quantity or multiplier
    reaches the same hazard through a different field). No branch here ever
    computes a division whose denominator could be zero.
    """
    included: list[tuple[str, Decimal]] = []
    excluded: list[tuple[str, str]] = []
    for trade in trades:
        if trade.avg_px_open is None or trade.avg_px_open == 0:
            excluded.append((trade.trade_id, _UNPRICED_FORWARD_REASON))
            continue
        denominator = trade.avg_px_open * trade.qty * trade.multiplier
        if denominator == 0:
            excluded.append((trade.trade_id, _UNPRICED_FORWARD_REASON))
            continue
        included.append((trade.trade_id, trade.realized_pnl / denominator))
    return TradeReturnSample(included=tuple(included), excluded=tuple(excluded))


class SettlementCloseRefused(Exception):
    """Raised when settlement-as-exit must not close a position.

    A subclass is deliberately not raised for the two distinct causes
    (a latched refusal vs. no attribution): the plan treats both as the
    same hard stop -- a close that must not happen -- and a caller
    distinguishing them by `except` type would be one step from treating
    one of them as recoverable.
    """


def assert_settlement_close_permitted(
    *,
    trading_refusals: Sequence[str],
    instrument_id: str,
    attributed_order_id: str | None,
) -> None:
    """Refuse a settlement close the same way `_submit_order` would refuse it.

    Two independent checks, both mandatory, checked in this order so the
    message always names the more foundational defect first:

    1. `trading_refusals` -- the exec client's own latch
       (`PolymarketUSExecutionClient.trading_refusals`). Non-empty means
       reconciliation could not attribute venue state with confidence;
       `_submit_order` already refuses on this, and settlement-as-exit must
       refuse identically rather than reach Nautilus through the
       `_send_order_status_report` seam, which `_submit_order`'s
       precondition does not gate.
    2. `attributed_order_id` -- the Breezy order id this close is claimed
       against (`external_order_claims`). `None` and `""` are refused
       identically: an empty string is not an id, not a lesser id.

    Raises :class:`SettlementCloseRefused` on either failure; returns
    `None` (permits the close) only when both checks pass.
    """
    if trading_refusals:
        raise SettlementCloseRefused(
            f"refusing to close {instrument_id} via settlement-as-exit: "
            f"the exec client latch carries {len(trading_refusals)} "
            f"unresolved trading refusal(s) ({'; '.join(trading_refusals)}); "
            "_submit_order's refusal latch must gate this path too"
        )
    if not attributed_order_id:
        raise SettlementCloseRefused(
            f"refusing to close {instrument_id} via settlement-as-exit: "
            "no Breezy order could be attributed to this position "
            "(external_order_claims produced no id); closing an "
            "unattributable position risks booking a foreign fill"
        )
