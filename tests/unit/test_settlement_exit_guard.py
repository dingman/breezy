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
    settlement_price_for_leg,
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


# ---------------------------------------------------------------------------
# S2b (R3-5(ii)) -- the NO leg settles at the complement, keyed on leg,
# never on the raw venue number and never on an outcome string.
# ---------------------------------------------------------------------------


def test_a_yes_leg_settles_at_the_raw_venue_price_unchanged() -> None:
    """Pin: the YES path is byte-identical to before this function existed --
    the raw venue number, untouched."""
    assert settlement_price_for_leg(leg="yes", settlement_price=Decimal("0.7300")) == Decimal(
        "0.7300"
    )


def test_a_no_leg_settles_at_the_complement() -> None:
    assert settlement_price_for_leg(leg="no", settlement_price=Decimal("0.7300")) == Decimal(
        "0.2700"
    )


@pytest.mark.parametrize(
    ("settlement_price", "expected_yes", "expected_no"),
    [
        (Decimal(0), Decimal(0), Decimal(1)),
        (Decimal("0.5"), Decimal("0.5"), Decimal("0.5")),
        (Decimal(1), Decimal(1), Decimal(0)),
    ],
)
def test_a_yes_no_pair_always_sums_to_exactly_one(
    settlement_price: Decimal, expected_yes: Decimal, expected_no: Decimal
) -> None:
    yes = settlement_price_for_leg(leg="yes", settlement_price=settlement_price)
    no = settlement_price_for_leg(leg="no", settlement_price=settlement_price)

    assert yes == expected_yes
    assert no == expected_no
    assert yes + no == Decimal(1)


def test_an_unknown_leg_marker_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown settlement leg"):
        settlement_price_for_leg(leg="maybe", settlement_price=Decimal("0.5"))  # type: ignore[arg-type]


def test_a_no_position_that_won_yields_positive_and_a_lost_no_yields_negative_premium() -> None:
    """`compute_trade_returns` doesn't know about legs -- it only sees a
    priced entry and a realized PnL. This test proves the leg-correct
    settlement price feeds it a realistic won/lost NO trade: a NO bought at
    0.30 that settles at 1 (HIGH landed outside the rung, so NO won) returns
    positive; the same NO settling at 0 (HIGH landed inside the rung, NO
    lost) returns exactly -1 (loses the whole premium)."""
    open_price = Decimal("0.30")
    qty = Decimal(10)

    won_settlement = settlement_price_for_leg(leg="no", settlement_price=Decimal(0))
    won_pnl = (won_settlement - open_price) * qty
    won_sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="no-won",
                realized_pnl=won_pnl,
                avg_px_open=open_price,
                qty=qty,
            )
        ]
    )
    assert won_sample.included[0][1] > 0

    lost_settlement = settlement_price_for_leg(leg="no", settlement_price=Decimal(1))
    lost_pnl = (lost_settlement - open_price) * qty
    lost_sample = compute_trade_returns(
        [
            TradeReturnInput(
                trade_id="no-lost",
                realized_pnl=lost_pnl,
                avg_px_open=open_price,
                qty=qty,
            )
        ]
    )
    assert lost_sample.included[0][1] == Decimal(-1)


# ---------------------------------------------------------------------------
# Follow-up review fix: `settlement_price` must be bounds-checked BEFORE the
# leg dispatch. A binary settlement is a probability in [0, 1]; anything
# outside that (or non-finite: NaN/Infinity) must be refused, never clamped
# -- an out-of-range Decimal flowing into the leg arithmetic would produce an
# impossible synthetic close price for the actor this function is written
# for.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("settlement_price", [Decimal(0), Decimal(1)])
def test_the_boundary_values_zero_and_one_are_accepted(settlement_price: Decimal) -> None:
    # Must not raise.
    settlement_price_for_leg(leg="yes", settlement_price=settlement_price)
    settlement_price_for_leg(leg="no", settlement_price=settlement_price)


@pytest.mark.parametrize("settlement_price", [Decimal("-0.0001"), Decimal("1.0001")])
def test_just_outside_the_boundary_is_refused(settlement_price: Decimal) -> None:
    with pytest.raises(ValueError, match="settlement_price"):
        settlement_price_for_leg(leg="yes", settlement_price=settlement_price)
    with pytest.raises(ValueError, match="settlement_price"):
        settlement_price_for_leg(leg="no", settlement_price=settlement_price)


@pytest.mark.parametrize("settlement_price", [Decimal("1.2"), Decimal("-0.2")])
def test_grossly_out_of_range_values_are_refused_not_clamped(settlement_price: Decimal) -> None:
    with pytest.raises(ValueError, match="settlement_price"):
        settlement_price_for_leg(leg="no", settlement_price=settlement_price)


def test_a_nan_settlement_price_is_refused() -> None:
    with pytest.raises(ValueError, match="settlement_price"):
        settlement_price_for_leg(leg="yes", settlement_price=Decimal("NaN"))


def test_an_infinite_settlement_price_is_refused() -> None:
    with pytest.raises(ValueError, match="settlement_price"):
        settlement_price_for_leg(leg="no", settlement_price=Decimal("Infinity"))
    with pytest.raises(ValueError, match="settlement_price"):
        settlement_price_for_leg(leg="no", settlement_price=Decimal("-Infinity"))
