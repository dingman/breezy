"""CT-1: AMBIGUOUS through the exec client's public command port.

One public ``submit_order`` receives a with-id empty-executions body. A
second public submit, scheduled before that POST returns, is refused by
the submit-intent latch check. The POST count stays 1, the intent stays
OPEN, and no retirement reason is written.

The entry is ``PolymarketUSExecutionClient.submit_order`` (the command
path the fq caps test builds orders for). This file never calls
``_submit_order``. The in-memory spend held for an AMBIGUOUS booking is
not asserted across a restart: that loss is C9 and is not fixed here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from nautilus_trader.model.events import OrderDenied

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.runtime.submit_intent import SubmitIntentState
from tests.unit.operator_control_env import operator_control_env
from tests.unit.test_fq_caps_and_ambiguous_2026_10_01 import _fq_submit_order
from tests.unit.test_polymarket_us_exec_client import (
    _build_accept_fill_rig,
    _FakeOrderSender,
)
from tests.unit.test_polymarket_us_submit_order_chain import write_canonical_verified  # noqa: F401

# The create-order residual. Pinned as a literal so a rename of the
# constant, or a new retirement of this outcome, cannot pass unnoticed.
_AMBIGUOUS_REASON_LITERAL = (
    "create-order outcome is AMBIGUOUS; latch stays open and the booking is held"
)


class _YieldOnceOrderSender(_FakeOrderSender):
    """Yields once inside the POST so a second already-scheduled public
    submit runs its latch check while this one is suspended.

    The body is inlined: a named ``post_order`` call would widen the
    readonly guard's single call-site pin. Recording happens after the
    yield, so a latch refusal never counts as a POST.
    """

    async def post_order(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> VenueResponse:
        await asyncio.sleep(0)
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        return self.response


async def _drain_scheduled_submits() -> None:
    """Let ready submit tasks finish. The resolver task sleeps for its
    poll interval and must not be gathered -- it never completes."""
    current = asyncio.current_task()
    for _ in range(20):
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        if not pending:
            return
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_ct01_with_id_empty_executions_refuses_the_second_public_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _YieldOnceOrderSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=json.dumps({"id": "ord-ct1-ambiguous", "executions": []}).encode(),
    )
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    first = _fq_submit_order(rig)
    second = _fq_submit_order(rig, price="0.64")

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await rig.client._connect()
        # Both commands are scheduled before either POST runs. The first
        # arms the latch, then yields inside the sender; the second must
        # observe that OPEN intent and refuse without a second POST.
        rig.client.submit_order(first)
        rig.client.submit_order(second)
        await _drain_scheduled_submits()
        await rig.client._disconnect()

    assert len(sender.calls) == 1
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].client_order_id == second.order.client_order_id
    assert denials[0].reason == submit_chain.OPEN_INTENT_WAIT_REASON

    current = rig.submit_intent_latch.current()
    assert current is not None
    assert current.state is SubmitIntentState.OPEN
    assert current.retirement_reason is None
    assert _AMBIGUOUS_REASON_LITERAL in rig.client.trading_refusals
    assert submit_chain.AMBIGUOUS_REASON == _AMBIGUOUS_REASON_LITERAL
