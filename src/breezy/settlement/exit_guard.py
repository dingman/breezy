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

R-9 proper (the future BCa bootstrap consumer of `TradeReturnSample`) is not
built here -- this module only refuses to divide. When that consumer lands,
it MUST additionally assert an exclusion-fraction ceiling
(`len(excluded) / (len(included) + len(excluded))`) against a threshold and
fail closed above it: a sample that is mostly-excluded trades is not a
sample the bootstrap should silently run on with whatever priced remainder
happens to be left.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

__all__ = [
    "EXCLUSION_FRACTION_CEILING",
    "SettlementCloseRefused",
    "TradeReturnInput",
    "TradeReturnSample",
    "assert_settlement_close_permitted",
    "compute_trade_returns",
]

#: The exclusion-fraction ceiling this module's docstring (above) demands of
#: the future BCa bootstrap consumer (`settlement/roi_bound.py`, EXEC_SPINE
#: R-9, "6e" in `SCORER_TALLY_BCA_BRIEF_2026-09-04.md` item 10). Coordinator
#: decision, overridable only downward by a future caller -- never upward.
#: This is the ONE named constant; `roi_bound.py` imports it rather than
#: restating the number.
EXCLUSION_FRACTION_CEILING: Final[Decimal] = Decimal("0.20")

#: Reason string for a trade whose `avg_px_open` is itself the problem --
#: `None` (upstream never recorded an open price) or a real `Decimal(0)`.
#: This is the L-17 unpriced-forward hazard: it is refused, never
#: substituted with a price.
_UNPRICED_OPEN_REASON: str = (
    "unpriced forward: avg_px_open is None or zero; refused rather than "
    "divided or substituted with a price (see LESSONS.md L-17)"
)

#: Reason string for a trade whose `avg_px_open` IS priced but the full
#: denominator (`avg_px_open * qty * multiplier`) is still zero because
#: `qty` or `multiplier` is zero. Distinct from `_UNPRICED_OPEN_REASON`
#: because the cause is a different field -- a caller triaging exclusions
#: needs to know which upstream record is malformed, not just that a
#: division was refused.
_ZERO_DENOMINATOR_REASON: str = (
    "zero return denominator: avg_px_open is priced but avg_px_open * qty "
    "* multiplier is zero (qty or multiplier is zero); refused rather "
    "than divided (see LESSONS.md L-17)"
)


@dataclass(frozen=True, kw_only=True)
class TradeReturnInput:
    """One closed trade's inputs to the per-trade net return.

    `avg_px_open` is `Decimal | None` on purpose: `None` is how an unpriced
    forward is represented upstream, and a `Decimal(0)` sentinel would be
    indistinguishable from a real zero price. Both are refused identically.
    """

    trade_id: str
    #: MUST be sourced from Nautilus `Position.realized_pnl`
    #: (`nautilus_trader/model/position.pyx`) -- NOT a caller-derived
    #: price-only PnL. `Position.realized_pnl` is fee-INCLUSIVE: on every
    #: fill it seeds from `-fill.commission.as_f64_c()` before adding the
    #: price-only PnL (`position.pyx:901-902`,
    #: `_handle_buy_order_fill`/`_handle_sell_order_fill`), then accumulates
    #: across fills (`position.pyx:919-922`). A caller that instead computes
    #: `(close_px - open_px) * qty` and drops commission would understate
    #: the loss (or overstate the gain) on every trade with a nonzero fee,
    #: and the per-trade return `r_i` computed below would be silently
    #: optimistic.
    realized_pnl: Decimal
    avg_px_open: Decimal | None
    qty: Decimal
    multiplier: Decimal = Decimal(1)


@dataclass(frozen=True, kw_only=True)
class TradeReturnSample:
    """The BCa bootstrap's raw material: included returns plus an explicit,
    counted, attributable exclusion list. `len(included) + len(excluded)`
    is always exactly `len(trades)` passed to `compute_trade_returns` --
    never fewer, and never more."""

    included: tuple[tuple[str, Decimal], ...]
    excluded: tuple[tuple[str, str], ...]


def compute_trade_returns(trades: Sequence[TradeReturnInput]) -> TradeReturnSample:
    """Compute `r_i` for every priced trade; exclude, never divide, the rest.

    A trade is excluded for one of two distinct causes, each with its own
    reason string so a caller triaging exclusions knows which upstream
    field is malformed:

    - `_UNPRICED_OPEN_REASON` -- `avg_px_open` is `None` or zero (the L-17
      unpriced-forward hazard).
    - `_ZERO_DENOMINATOR_REASON` -- `avg_px_open` is priced but the full
      denominator `avg_px_open * qty * multiplier` is still zero because
      `qty` or `multiplier` is zero.

    No branch here ever computes a division whose denominator could be
    zero.
    """
    included: list[tuple[str, Decimal]] = []
    excluded: list[tuple[str, str]] = []
    for trade in trades:
        if trade.avg_px_open is None or trade.avg_px_open == 0:
            excluded.append((trade.trade_id, _UNPRICED_OPEN_REASON))
            continue
        denominator = trade.avg_px_open * trade.qty * trade.multiplier
        if denominator == 0:
            excluded.append((trade.trade_id, _ZERO_DENOMINATOR_REASON))
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
