"""RED-first suite for `strategy/current_rung_hold/exit_authorization.py`
(INC-E1, `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` §3).

Every construction-time refusal is tested per leg (L-44): a YES instance and
a NO instance, each varying exactly one field away from an otherwise-valid
baseline so the refusal is attributable to that single field.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from breezy.strategy.current_rung_hold.exit_authorization import (
    ExitAuthorization,
    ExitAuthorizationRefusalError,
    ExitRule,
)

_FEE_COEFFICIENT = Decimal("0.06")
_DECIDED_AT_NS = 1_700_000_000_000_000_000
_BOOK_STALENESS_NS = 5_000_000_000


def _base_kwargs(*, leg: str) -> dict[str, object]:
    """A valid R_THREAT authorization baseline for the given leg.

    `limit_price=0.80`, `fee_coefficient=0.06` -> fee = 0.06*0.80*0.20 =
    0.0096, banker's-rounded to 0.01 -> net proceeds = 0.79.
    `expected_settlement_value=0.60` is comfortably below that, so R_THREAT's
    own threshold (net proceeds > expected_settlement_value) passes.
    """
    return {
        "family_id": "pm_us_crh_exit_v4",
        "position_id": f"position-{leg}-1",
        "client_order_id": f"client-order-{leg}-1",
        "leg": leg,
        "attributed_net_long": 2,
        "working_sell_qty": 0,
        "quantity": 1,
        "limit_price": Decimal("0.80"),
        "rule": ExitRule.R_THREAT,
        "expected_settlement_value": Decimal("0.60"),
        "fee_coefficient": _FEE_COEFFICIENT,
        "decided_at_ns": _DECIDED_AT_NS,
        "book_staleness_ns": _BOOK_STALENESS_NS,
    }


def _dead_kwargs(*, leg: str) -> dict[str, object]:
    """A valid R_DEAD authorization baseline for the given leg.

    `limit_price=0.05`, `fee_coefficient=0.06` -> fee = 0.06*0.05*0.95 =
    0.00285, banker's-rounded to 0.00 -> net proceeds = 0.05, strictly
    positive, clearing R_DEAD's `> 0` bar. `expected_settlement_value` is
    unused by R_DEAD's own threshold but still required by the dataclass.
    """
    kwargs = _base_kwargs(leg=leg)
    kwargs.update(
        rule=ExitRule.R_DEAD,
        limit_price=Decimal("0.05"),
        expected_settlement_value=Decimal("0.0"),
    )
    return kwargs


@pytest.mark.parametrize("leg", ["yes", "no"])
class TestValidConstructionPerLeg:
    def test_a_valid_r_threat_authorization_constructs(self, leg: str) -> None:
        auth = ExitAuthorization(**_base_kwargs(leg=leg))
        assert auth.leg == leg
        assert auth.rule is ExitRule.R_THREAT

    def test_a_valid_r_dead_authorization_constructs(self, leg: str) -> None:
        auth = ExitAuthorization(**_dead_kwargs(leg=leg))
        assert auth.leg == leg
        assert auth.rule is ExitRule.R_DEAD


@pytest.mark.parametrize("leg", ["yes", "no"])
class TestRefusalsPerLeg:
    def test_a_missing_position_id_refuses(self, leg: str) -> None:
        kwargs = _base_kwargs(leg=leg)
        kwargs["position_id"] = ""
        with pytest.raises(ExitAuthorizationRefusalError, match="position_id"):
            ExitAuthorization(**kwargs)

    def test_a_quantity_other_than_one_refuses(self, leg: str) -> None:
        kwargs = _base_kwargs(leg=leg)
        kwargs["quantity"] = 2
        with pytest.raises(ExitAuthorizationRefusalError, match="pinned to exactly"):
            ExitAuthorization(**kwargs)

    def test_a_zero_quantity_refuses(self, leg: str) -> None:
        kwargs = _base_kwargs(leg=leg)
        kwargs["quantity"] = 0
        with pytest.raises(ExitAuthorizationRefusalError, match="pinned to exactly"):
            ExitAuthorization(**kwargs)

    def test_quantity_exceeding_the_remaining_attributable_long_refuses(
        self, leg: str
    ) -> None:
        kwargs = _base_kwargs(leg=leg)
        kwargs["attributed_net_long"] = 1
        kwargs["working_sell_qty"] = 1
        with pytest.raises(ExitAuthorizationRefusalError, match="remains attributable"):
            ExitAuthorization(**kwargs)

    @pytest.mark.parametrize(
        "bad_price", [Decimal(0), Decimal(1), Decimal("-0.1"), Decimal("1.5")]
    )
    def test_a_unit_boundary_or_out_of_range_price_refuses(
        self, leg: str, bad_price: Decimal
    ) -> None:
        kwargs = _base_kwargs(leg=leg)
        kwargs["limit_price"] = bad_price
        with pytest.raises(ExitAuthorizationRefusalError, match="strictly inside"):
            ExitAuthorization(**kwargs)

    def test_an_r_threat_authorization_whose_net_proceeds_do_not_clear_hold_expectation_refuses(
        self, leg: str
    ) -> None:
        kwargs = _base_kwargs(leg=leg)
        # net proceeds at limit_price=0.80 is 0.79 (see `_base_kwargs`); an
        # expected_settlement_value at or above that must refuse.
        kwargs["expected_settlement_value"] = Decimal("0.85")
        with pytest.raises(ExitAuthorizationRefusalError, match="hold expectation"):
            ExitAuthorization(**kwargs)

    def test_an_r_dead_authorization_whose_net_proceeds_are_not_positive_refuses(
        self, leg: str
    ) -> None:
        kwargs = _dead_kwargs(leg=leg)
        # An artificially large fee coefficient forces the fee above the
        # price itself, driving net proceeds negative -- this exercises the
        # refusal branch, not a realistic venue fee schedule.
        kwargs["fee_coefficient"] = Decimal(5)
        with pytest.raises(ExitAuthorizationRefusalError, match="strictly positive"):
            ExitAuthorization(**kwargs)


def test_the_rule_field_accepts_exactly_the_two_registered_rules() -> None:
    assert {member.value for member in ExitRule} == {"R_THREAT", "R_DEAD"}
