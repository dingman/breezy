"""SAFETY C1 (plan rev 6.1) -- the pre-arm race, at the exec-client level.

Two ``_submit_order`` commands created in one synchronous burst (mirroring
``submit_order``'s per-command ``create_task``,
``live/execution_client.py:277-282``) must spend exactly ONE permit slot and
post exactly once. Before the fix, the second task spent a permit slot via
``assert_live_order_submission_permitted`` and only THEN failed ``arm()``
(``SubmitIntentLatched``) -- releasing the booking but never restoring the
permit. The fix inserts an authoritative ``self._latch.is_latched()``
re-check immediately before the spend, so the second task is denied with the
new ``OPEN_INTENT_WAIT_REASON`` WAIT sentinel and never reaches the spend at
all.

Fixtures reused, never redefined (module docstring convention this repo
follows elsewhere): ``_FakeSigner`` / ``_PrivateReadStub`` /
``_balances_payload`` / ``write_canonical_verified``
(``test_polymarket_us_submit_order_chain.py``); ``credentials`` /
``enable_operator_gate`` (``test_polymarket_us_permit_issuance.py``);
``build_instrument`` (``polymarket_us_exec_shapes.py``). ``_SlowSender`` below
is new: ``_FakeSender`` (same module) has no internal ``await`` at all, so it
cannot reproduce the race -- see its docstring.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import AccountState, OrderDenied
from nautilus_trader.model.identifiers import ClientId, StrategyId, TraderId
from nautilus_trader.model.objects import Quantity

from breezy.adapters.polymarket_us.account_activity import PORTFOLIO_ACTIVITIES_PATH
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
)
from breezy.adapters.polymarket_us.safety import (
    issue_live_trading_permit,
    live_trading_budget_remaining,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import build_instrument
from tests.unit.test_polymarket_us_permit_issuance import credentials, enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    _balances_payload,
    _FakeSigner,
    _PrivateReadStub,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

TRADER_ID: Final[TraderId] = TraderId("BREEZY-RACE-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("ContinuousRungHoldStrategy-RACE")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
ACCOUNT_NUMBER: Final[str] = "001"


class _SlowSender:
    """Like ``_FakeSender``, but ``post_order`` genuinely suspends once.

    A real venue POST suspends the task at the socket read, which is exactly
    what gives a second ``_submit_order`` task its window to run BEFORE the
    first one resumes to classify/retire. ``_FakeSender.post_order`` has no
    internal ``await`` at all, so ``await`` on it never yields to the loop --
    the whole first ``_submit_order`` (arm through retire) runs in one
    scheduler turn and the second task only ever starts afterward, which
    cannot reproduce SAFETY C1's race. One ``asyncio.sleep(0)`` reproduces
    the real shape: task 1 arms, THEN suspends at the POST, THEN task 2 runs.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response: Any = None

    async def post_order(
        self, base_url: str, *, headers: Any, body: bytes,
    ) -> Any:
        await asyncio.sleep(0)
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        return self.response


def _zero_fill_body(order_id: str) -> bytes:
    """A 200 with empty executions and a terminal state, ``cumQuantity=0``."""
    return json.dumps(
        {
            "id": order_id,
            "state": "ORDER_STATE_CANCELED",
            "cumQuantity": 0,
            "executions": [],
        }
    ).encode("utf-8")


async def _build_race_client(tmp_path: Path, *, sender: Any) -> tuple[
    PolymarketUSExecutionClient, list[Any], Any, Any,
]:
    loop = asyncio.get_running_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))

    instrument = build_instrument()
    cache.add_instrument(instrument)
    provider = InstrumentProvider()
    provider.add(instrument)

    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: {"positions": {}, "eof": True},
            # EDGE-2 slice D (AC4(c)): EOF-complete, no trade rows, by
            # default -- overridden per-test where a trade join must find
            # (or fail to find) something.
            PORTFOLIO_ACTIVITIES_PATH: {"activities": [], "eof": True},
        },
    )
    order_events: list[Any] = []
    msgbus.register(endpoint="ExecEngine.process", handler=order_events.append)

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)

    store_path = tmp_path / "exec_state.db"
    live_permit = issue_live_trading_permit(clock=clock)
    latch_cm = open_submit_intent_latch(SqliteStateStore(store_path), store_path)
    submit_intent_latch = latch_cm.__enter__()
    ledger = DailySpendLedger()

    client = PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=read,
        state_store_opener=lambda: SqliteStateStore(store_path),
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=1.0,
        account_registration_timeout_s=1.0,
        order_sender=sender,
        write_signer=_FakeSigner(),
        live_trading_permit=live_permit,
        spend_ledger=ledger,
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
    )
    await client._connect()
    # `latch_cm` (the `@contextmanager` generator) MUST stay referenced: if it
    # is dropped, CPython's refcounting immediately GCs it, which throws
    # `GeneratorExit` into the paused generator and releases the flock right
    # away -- `SubmitIntentLockNotHeld` on the very next `is_latched()` call.
    return client, order_events, live_permit, latch_cm


def _submit_command(
    client: PolymarketUSExecutionClient, factory: OrderFactory, tag: str,
) -> SubmitOrder:
    del tag  # kept for call-site readability only; the shared factory de-dupes ids
    instrument = build_instrument()
    order = factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=instrument.make_price("0.40"),
        time_in_force=TimeInForce.IOC,
        post_only=False,
    )
    return SubmitOrder(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        order=order,
        command_id=UUID4(),
        ts_init=client._clock.timestamp_ns(),
    )


@pytest.mark.asyncio
async def test_two_synchronous_submits_in_one_burst_spend_exactly_one_permit_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        sender = _SlowSender()
        sender.response = __import__(
            "breezy.adapters.polymarket_us.transport", fromlist=["VenueResponse"]
        ).VenueResponse(status=200, headers={}, body=_zero_fill_body("ord-race-1"))
        client, order_events, permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )

        factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
        command_a = _submit_command(client, factory, "a")
        command_b = _submit_command(client, factory, "b")

        # The burst: both commands scheduled as independent tasks BEFORE
        # either runs -- mirrors `submit_order`'s per-command `create_task`.
        task_a = asyncio.ensure_future(client._submit_order(command_a))
        task_b = asyncio.ensure_future(client._submit_order(command_b))
        await asyncio.gather(task_a, task_b)

        _, remaining = live_trading_budget_remaining(permit)
        denials = [e for e in order_events if isinstance(e, OrderDenied)]

        # Exactly one order actually reached the venue.
        assert len(sender.calls) == 1
        # Exactly one permit slot spent for the one order that was ever
        # really attempted -- the pre-fix bug spent a slot for BOTH tasks.
        assert remaining == 1, f"expected 1 slot left of 2, found {remaining}"
        # Exactly one denial, carrying the new WAIT sentinel -- not a
        # `_trading_refusals` latch.
        assert len(denials) == 1
        assert denials[0].reason == submit_chain.OPEN_INTENT_WAIT_REASON
        assert client.trading_refusals == ()

        await client._disconnect()
