"""RED-first guards for EXEC_SPINE R-9-PRE (`docs/plans/EXEC_SPINE_2026-09-01.md`
Sec R-9, "R-4 review amendments").

Two guards, landed ahead of the `SettlementExitActor` itself because both are
independently load-bearing and testable today without the machinery R-9
proper is still blocked on (`exec/` write path, a live fill, a real
settlement actor):

1. `compute_trade_returns` -- `r_i = pnl / (avg_px_open * qty * multiplier)`
   must never divide by zero or an absent open price (an unpriced forward,
   L-17). Such a trade is excluded from the BCa sample with an explicit,
   counted reason -- never silently dropped, never substituted with a price.
2. `assert_settlement_close_permitted` -- the settlement-as-exit path must
   consult the SAME `trading_refusals` latch `_submit_order` consults, and
   must never close a position it cannot attribute to a Breezy order
   (`external_order_claims`). Per L-22 this is written as the sole gate a
   future actor calls, not an optional helper.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from breezy.settlement.exit_guard import (
    SettlementCloseRefused,
    TradeReturnInput,
    assert_settlement_close_permitted,
    compute_trade_returns,
)

# ---------------------------------------------------------------------------
# Guard (a): the per-trade return never divides by zero or a substituted price
# ---------------------------------------------------------------------------


def test_a_priced_trade_computes_the_net_return() -> None:
    sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="T1",
                realized_pnl=Decimal("0.40"),
                avg_px_open=Decimal("0.20"),
                qty=Decimal(10),
            ),
        ],
    )
    assert sample.included == (("T1", Decimal("0.40") / (Decimal("0.20") * Decimal(10))),)
    assert sample.excluded == ()


def test_a_zero_open_price_is_excluded_not_divided() -> None:
    """`avg_px_open=0` is an unpriced forward (L-17), not a real zero-cost
    entry -- it must never reach a division."""
    sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="T2",
                realized_pnl=Decimal("1.00"),
                avg_px_open=Decimal(0),
                qty=Decimal(10),
            ),
        ],
    )
    assert sample.included == ()
    assert len(sample.excluded) == 1
    trade_id, reason = sample.excluded[0]
    assert trade_id == "T2"
    assert "unpriced forward" in reason
    assert "T2" not in [tid for tid, _ in sample.included]


def test_an_absent_open_price_is_excluded_not_substituted() -> None:
    """`avg_px_open=None` must never be defaulted to 0, 1, or anything else --
    it is refused, exactly like the zero case, and for the same reason."""
    sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="T3",
                realized_pnl=Decimal("1.00"),
                avg_px_open=None,
                qty=Decimal(10),
            ),
        ],
    )
    assert sample.included == ()
    assert len(sample.excluded) == 1
    assert sample.excluded[0][0] == "T3"
    assert "unpriced forward" in sample.excluded[0][1]


def test_a_zero_quantity_denominator_is_also_excluded_never_divided() -> None:
    sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="T4",
                realized_pnl=Decimal("1.00"),
                avg_px_open=Decimal("0.20"),
                qty=Decimal(0),
            ),
        ],
    )
    assert sample.included == ()
    assert len(sample.excluded) == 1
    assert sample.excluded[0][0] == "T4"
    assert "zero return denominator" in sample.excluded[0][1]


def test_an_unpriced_open_and_a_zero_denominator_get_distinct_reasons() -> None:
    """An unpriced open (`avg_px_open` None/zero) and a priced-but-zero-qty
    record reach the same refuse-to-divide outcome through different
    upstream defects -- the reason string must say which."""
    sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="UNPRICED",
                realized_pnl=Decimal("1.00"),
                avg_px_open=None,
                qty=Decimal(10),
            ),
            TradeReturnInput(
                trade_id="ZERO_QTY",
                realized_pnl=Decimal("1.00"),
                avg_px_open=Decimal("0.20"),
                qty=Decimal(0),
            ),
        ],
    )
    reasons = dict(sample.excluded)
    assert "unpriced forward" in reasons["UNPRICED"]
    assert "zero return denominator" in reasons["ZERO_QTY"]
    assert reasons["UNPRICED"] != reasons["ZERO_QTY"]
    assert len(sample.included) + len(sample.excluded) == len(
        ["UNPRICED", "ZERO_QTY"]
    )


def test_realized_pnl_must_be_fee_inclusive_like_nautilus_position() -> None:
    """`realized_pnl` MUST be sourced from Nautilus `Position.realized_pnl`
    (`nautilus_trader/model/position.pyx`), which nets commission into the
    figure on every fill (`position.pyx:901-902`,
    `realized_pnl = -fill.commission.as_f64_c()` before the price-only PnL
    is added). This pins that convention: a 1-contract BUY at 0.12 that
    settles to 0 with a $0.01 commission has `realized_pnl = -0.12 - 0.01`,
    NOT a price-only `-0.12` -- so `r_i` is worse than -1.0 exactly because
    the fee is already netted in, not because this module adds it."""
    fee_inclusive_pnl = Decimal("-0.12") - Decimal("0.01")
    sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="FEE1",
                realized_pnl=fee_inclusive_pnl,
                avg_px_open=Decimal("0.12"),
                qty=Decimal(1),
            ),
        ],
    )
    assert sample.excluded == ()
    trade_id, r = sample.included[0]
    assert trade_id == "FEE1"
    expected = (Decimal("-0.12") - Decimal("0.01")) / Decimal("0.12")
    assert r == expected
    assert r < Decimal("-1.0")


def test_exclusion_count_is_explicit_across_a_mixed_sample() -> None:
    """The count must be exact and attributable -- never a silent drop."""
    sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="OK1",
                realized_pnl=Decimal("0.10"),
                avg_px_open=Decimal("0.5"),
                qty=Decimal(1),
            ),
            TradeReturnInput(
                trade_id="BAD1",
                realized_pnl=Decimal("1.00"),
                avg_px_open=Decimal(0),
                qty=Decimal(1),
            ),
            TradeReturnInput(
                trade_id="OK2",
                realized_pnl=Decimal("-0.20"),
                avg_px_open=Decimal("0.4"),
                qty=Decimal(2),
            ),
            TradeReturnInput(
                trade_id="BAD2",
                realized_pnl=Decimal("1.00"),
                avg_px_open=None,
                qty=Decimal(1),
            ),
        ],
    )
    assert [tid for tid, _ in sample.included] == ["OK1", "OK2"]
    assert [tid for tid, _ in sample.excluded] == ["BAD1", "BAD2"]
    assert len(sample.excluded) == 2


def test_empty_sample_is_not_an_error() -> None:
    sample = compute_trade_returns([])
    assert sample.included == ()
    assert sample.excluded == ()


# ---------------------------------------------------------------------------
# Guard (b): settlement-as-exit must consult the trading_refusals latch and
# must never close an unattributable position
# ---------------------------------------------------------------------------


def test_a_latched_trading_refusal_blocks_the_settlement_close() -> None:
    """`_submit_order`'s refusal latch must gate settlement-as-exit too --
    this is the exact bypass named in the plan's R-4 review amendments."""
    with pytest.raises(SettlementCloseRefused, match="unresolved trading refusal"):
        assert_settlement_close_permitted(
            trading_refusals=("the instrument load did not finish within 5.0s",),
            instrument_id="BINARY-1.WEATHER",
            attributed_order_id="SETTLE-BINARY-1.WEATHER-2026-09-04",
        )


def test_an_unattributable_position_is_never_closed() -> None:
    with pytest.raises(SettlementCloseRefused, match="no Breezy order"):
        assert_settlement_close_permitted(
            trading_refusals=(),
            instrument_id="BINARY-1.WEATHER",
            attributed_order_id=None,
        )


def test_an_empty_attributed_order_id_is_also_refused() -> None:
    """An empty string is not an id -- the same defect as `None`, not a
    different one; a falsy check must not be narrowed to `is None`."""
    with pytest.raises(SettlementCloseRefused, match="no Breezy order"):
        assert_settlement_close_permitted(
            trading_refusals=(),
            instrument_id="BINARY-1.WEATHER",
            attributed_order_id="",
        )


def test_a_clean_latch_and_an_attributed_order_permit_the_close() -> None:
    assert_settlement_close_permitted(
        trading_refusals=(),
        instrument_id="BINARY-1.WEATHER",
        attributed_order_id="SETTLE-BINARY-1.WEATHER-2026-09-04",
    )


def test_refusals_are_checked_before_attribution_and_both_named_in_the_message() -> None:
    """Order of checks does not matter to the caller, but the failure reason
    must name what actually blocked the close -- never a generic refusal."""
    with pytest.raises(SettlementCloseRefused, match="unresolved trading refusal"):
        assert_settlement_close_permitted(
            trading_refusals=("durable refusal: mass status assembly rejected a report",),
            instrument_id="BINARY-2.WEATHER",
            attributed_order_id=None,
        )
