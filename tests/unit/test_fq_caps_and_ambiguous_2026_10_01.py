"""FQ-S6 (plan §3 S6 test 5, test 6): the operator caps and the AMBIGUOUS-
intent resolver apply to an fq-labelled order exactly as they do to CRH's.

Both guards (`DailySpendLedger.authorize_order_cost`, the submit-intent
latch's WAIT refusal) live entirely in the shared, family-agnostic exec
client (D8) -- there is no fq-specific code path to wire. These tests prove
that reuse by actually driving an fq-``StrategyId``-tagged order through it,
never by inspection alone, reusing the established `_build_accept_fill_rig`
R-7 harness (`test_polymarket_us_exec_client.py`) rather than a second,
drifting one.

Per plan §8/invariants: no test here reads, assigns, or logs a real
operator-reserved cap VALUE outside the whitelisted
`operator_control_env`/`operator_control_unset` test seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderDenied
from nautilus_trader.model.identifiers import StrategyId
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.transport import VenueResponse
from tests.unit.operator_control_env import operator_control_env, operator_control_unset
from tests.unit.test_polymarket_us_exec_client import (
    TRADER_ID,
    _AcceptFillRig,
    _build_accept_fill_rig,
    _FakeOrderSender,
)
from tests.unit.test_polymarket_us_submit_order_chain import write_canonical_verified  # noqa: F401

FQ_STRATEGY_ID = StrategyId("FORECAST-QUANTILE-LADDER-LAX")
FQ_ORDER_PRICE = "0.63"


class _RaisingOrderSender(_FakeOrderSender):
    """A `_FakeOrderSender` whose `post_order` raises once armed -- the
    SAME AMBIGUOUS-triggering shape `test_polymarket_us_submit_order_chain
    .py`'s own `_FakeSender.error` already provides, redeclared as a real
    `_FakeOrderSender` subclass so it satisfies `_build_accept_fill_rig`'s
    concrete parameter type.
    """

    def __init__(self) -> None:
        super().__init__()
        self.error: BaseException | None = None

    async def post_order(
        self, base_url: str, *, headers: Mapping[str, str], body: bytes,
    ) -> VenueResponse:
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        if self.error is not None:
            raise self.error
        return self.response


def _fq_submit_order(rig: _AcceptFillRig, *, price: str = FQ_ORDER_PRICE) -> SubmitOrder:
    """The exact order shape ``ForecastQuantileLadderStrategy._maybe_submit``
    builds (LIMIT/IOC/BUY/qty 1), tagged with an fq ``StrategyId`` -- never
    the CRH one the shared rig's own ``limit_buy()`` hardcodes.
    """
    from nautilus_trader.common.factories import OrderFactory

    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=FQ_STRATEGY_ID, clock=rig.clock)
    order = factory.limit(
        instrument_id=rig.instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, rig.instrument.size_precision),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
    )
    return SubmitOrder(
        trader_id=TRADER_ID,
        strategy_id=FQ_STRATEGY_ID,
        order=order,
        command_id=UUID4(),
        ts_init=0,
    )


@pytest.mark.asyncio
async def test_fq_order_denied_when_per_position_cap_is_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        # Cost (0.63) exceeds this ceiling -- the per-position deny path.
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "0.10"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        await rig.client._disconnect()

    assert sender.calls == [], "a per-position cap deny must never reach the venue"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert MAX_POSITION_COST_USD_ENV_VAR in denials[0].reason
    assert "0.63" not in denials[0].reason and "0.10" not in denials[0].reason
    assert rig.client._ledger is not None
    assert rig.client._ledger.spent_today_usd(now_ns=rig.clock.timestamp_ns()) == Decimal(0)


@pytest.mark.asyncio
async def test_fq_order_denied_when_daily_budget_is_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        # Cost (0.63) exceeds this ceiling -- the daily-budget deny path.
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "0.10"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        await rig.client._disconnect()

    assert sender.calls == []
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert MAX_DAILY_BUDGET_USD_ENV_VAR in denials[0].reason


@pytest.mark.asyncio
async def test_fq_order_denied_when_neither_control_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR),
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        await rig.client._disconnect()

    assert sender.calls == [], "absence of either control must refuse, never default-permit"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1


@pytest.mark.asyncio
async def test_fq_order_resolved_ambiguous_then_the_next_take_is_latch_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    """An fq-tagged order whose `post_order` raises classifies AMBIGUOUS
    (the shared resolver, D8): the client latches a trading refusal
    (``submit_chain.latched_refusal_reason``) and will not act on venue
    state it could not attribute -- so a SECOND fq take is refused on that
    SAME shared, family-agnostic latch, never special-cased for fq (plan §3
    S6 test 6). The first order itself gets no `OrderDenied` (it reaches the
    venue and only its RESPONSE is unattributable); only the second,
    latch-refused one does.
    """
    sender = _RaisingOrderSender()
    sender.error = ConnectionError("simulated transport failure")
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        # The first intent is now AMBIGUOUS/latched -- a second fq take must
        # be refused on that SAME latch, never submit a second order.
        await rig.client._submit_order(_fq_submit_order(rig, price="0.64"))
        await rig.client._disconnect()

    assert len(sender.calls) == 1, "the second take must never reach the venue once latched"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert "AMBIGUOUS" in denials[0].reason
    assert denials[0].reason == submit_chain.latched_refusal_reason(
        "create-order outcome is AMBIGUOUS; latch stays open and the booking is held",
    )
