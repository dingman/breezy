"""NO-side S5 section 4: fill/GET leg attribution and spend seeding.

No new durable field -- `AmbiguousResolverContext.instrument_id` (written at
`client.py` `_note_ambiguous_open`, read at the resolver's `_cache.instrument`
lookup) already carries whichever leg's `InstrumentId` the order was built
on, and `_seed_spend_from_durable_fills` already walks every instrument the
provider has loaded. These tests prove the mechanism actually carries a NO
leg correctly, rather than asserting it by reading the source.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
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
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import AccountState
from nautilus_trader.model.identifiers import StrategyId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec.client import (
    FILL_KEY_PREFIX,
    RESOLVER_CONTEXT_KEY_PREFIX,
    AmbiguousResolverContext,
    DurableFillRecord,
    PolymarketUSExecutionClient,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, leg_of
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from tests.unit.operator_control_env import operator_control_env
from tests.unit.test_polymarket_us_exec_client import (
    _balances_payload,
    _PrivateReadStub,
)
from tests.unit.test_polymarket_us_permit_issuance import credentials, enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    _FakeSender,
    _FakeSigner,
    build_execution,
    build_order,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT: Final[int] = 1_787_617_213_000_000_000
TRADER_ID: Final[TraderId] = TraderId("BREEZY-R7-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("WEATHER-001")
CLIENT_ID_VALUE: Final[str] = "POLYMARKET_US"
ACCOUNT_NUMBER: Final[str] = "001"


def _load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def legs() -> tuple[BinaryOption, BinaryOption]:
    payload = _load_raw("market_open_510636_by_slug.json")
    yes, no = parse_binary_option_pair(payload, ts_init=TS_INIT)
    assert no is not None
    assert leg_of(yes.id) == "yes"
    assert leg_of(no.id) == "no"
    return yes, no


class _Fixture:
    def __init__(
        self, *, client: PolymarketUSExecutionClient, store_path: Path, latch_cm: Any
    ) -> None:
        self.client = client
        self.store_path = store_path
        # Kept alive for the fixture's lifetime -- see `_ChainRig`'s identical
        # note in `test_polymarket_us_submit_order_chain.py`: dropping this
        # reference finalises the generator-CM via `GeneratorExit` and
        # silently releases the flock mid-test.
        self._latch_cm = latch_cm


def _build_client(
    tmp_path: Path,
    *,
    legs: tuple[BinaryOption, BinaryOption],
    monkeypatch: pytest.MonkeyPatch,
    sender: _FakeSender | None = None,
) -> _Fixture:
    from nautilus_trader.model.identifiers import ClientId

    enable_operator_gate(monkeypatch)
    loop = asyncio.get_event_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    yes, no = legs
    cache.add_instrument(yes)
    cache.add_instrument(no)
    provider = InstrumentProvider()
    provider.add(yes)
    provider.add(no)
    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: {"positions": {}, "eof": True},
        },
    )

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)
    msgbus.register(endpoint="ExecEngine.process", handler=lambda _e: None)

    store_path = tmp_path / "exec_state.db"
    issued_permit = issue_live_trading_permit(clock=clock)
    latch_cm = open_submit_intent_latch(SqliteStateStore(store_path), store_path)
    submit_intent_latch = latch_cm.__enter__()
    client = PolymarketUSExecutionClient(
        loop=loop,
        client_id=ClientId(CLIENT_ID_VALUE),
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
        spend_ledger=DailySpendLedger(),
        order_sender=sender,
        write_signer=_FakeSigner() if sender is not None else None,
        live_trading_permit=issued_permit,
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
    )
    return _Fixture(client=client, store_path=store_path, latch_cm=latch_cm)


def _limit_buy(instrument: BinaryOption, *, price: str = "0.37") -> Any:
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    order = factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
    )
    return order


def _accept_fill_body(
    slug: str, *, order_id: str = "ord-no-1", wire_last_px: str = "0.37"
) -> bytes:
    """A 200 create-order body classifying as `KIND_ACCEPT_FILL` for the NO
    leg: `wire_last_px` is the value the VENUE echoes on the wire (always
    YES-denominated, Rev 5); `side`/`intent` are the venue's NO-leg echo."""
    order = build_order(slug)
    order["id"] = order_id
    order["quantity"] = 1
    order["cumQuantity"] = 1
    order["leavesQuantity"] = 0
    order["state"] = "ORDER_STATE_FILLED"
    order["side"] = "ORDER_SIDE_SELL"
    order["intent"] = "ORDER_INTENT_BUY_SHORT"
    order["price"] = {"value": wire_last_px, "currency": "USD"}
    order["avgPx"] = {"value": wire_last_px, "currency": "USD"}
    execution = build_execution(order)
    execution["lastShares"] = "1"
    execution["lastPx"] = {"value": wire_last_px, "currency": "USD"}
    execution["commissionNotionalCollected"] = {"value": "0.03", "currency": "USD"}
    return json.dumps({"id": order_id, "executions": [execution]}).encode("utf-8")


def _reopened_fill_record(store_path: Path, venue_order_id: str) -> DurableFillRecord | None:
    with SqliteStateStore(store_path) as reopened:
        raw = reopened.get(f"{FILL_KEY_PREFIX}{venue_order_id}")
    if raw is None:
        return None
    return DurableFillRecord.from_bytes(raw)


@pytest.mark.asyncio
async def test_a_no_order_persists_the_no_instrument_id_in_its_resolver_context(
    tmp_path: Path, legs: tuple[BinaryOption, BinaryOption], monkeypatch: pytest.MonkeyPatch
) -> None:
    _yes, no = legs
    fixture = _build_client(tmp_path, legs=legs, monkeypatch=monkeypatch)
    await fixture.client._connect()
    order = _limit_buy(no)

    class _Booking:
        booking_id = 1

    fixture.client._note_ambiguous_open(
        intent_id="intent-no-1",
        venue_order_id="venue-no-1",
        order=order,
        notional_usd=Decimal("0.63"),
        booking=_Booking(),
        now_ns=fixture.client._clock.timestamp_ns(),
    )
    raw = fixture.client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}intent-no-1")
    assert raw is not None
    context = AmbiguousResolverContext.from_bytes(raw)
    assert context.instrument_id == str(no.id)
    await fixture.client._disconnect()


@pytest.mark.asyncio
async def test_a_resolved_fill_books_to_the_context_instrument_not_a_slug_lookup(
    tmp_path: Path, legs: tuple[BinaryOption, BinaryOption], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both legs share `raw_symbol` (the venue slug), so `_assert_market_
    matches` passes for EITHER leg -- this is the only thing distinguishing
    a resolved fill's booked instrument from a slug lookup that could have
    silently preferred the YES leg."""
    yes, no = legs
    assert str(yes.raw_symbol) == str(no.raw_symbol)
    fixture = _build_client(tmp_path, legs=legs, monkeypatch=monkeypatch)
    await fixture.client._connect()

    # `_resolve_accept_fill` refuses unless the latch's CURRENT OPEN intent
    # matches `context.intent_id` (SAFETY H2/ARCH M2) -- armed via the real
    # writer path, never a hand-picked intent id.
    armed = fixture.client._latch.arm("f" * 64, now_ns=fixture.client._clock.timestamp_ns())
    context = AmbiguousResolverContext(
        intent_id=armed.intent_id,
        venue_order_id="venue-no-2",
        instrument_id=str(no.id),
        client_order_id="O-19700101-000000-001-001-1",
        strategy_id=str(STRATEGY_ID.value),
        notional_usd=Decimal("0.63"),
        booking_id=2,
        created_ns=fixture.client._clock.timestamp_ns(),
    )
    fixture.client._resolved_by_get_ts_ns[armed.intent_id] = fixture.client._clock.timestamp_ns()

    class _FakeReport:
        avg_px = Decimal("0.63")
        filled_qty = Quantity(1, no.size_precision)
        quantity = Quantity(1, no.size_precision)

    fixture.client._resolve_accept_fill(
        context, _FakeReport(), no, fixture.client._clock.timestamp_ns()
    )
    record = _reopened_fill_record(fixture.store_path, "venue-no-2")
    assert record is not None
    assert record.instrument_id == str(no.id)
    assert record.instrument_id != str(yes.id)
    await fixture.client._disconnect()


@pytest.mark.asyncio
async def test_the_create_path_books_to_the_orders_own_instrument(
    tmp_path: Path, legs: tuple[BinaryOption, BinaryOption], monkeypatch: pytest.MonkeyPatch
) -> None:
    _yes, no = legs
    sender = _FakeSender()
    fixture = _build_client(tmp_path, legs=legs, sender=sender, monkeypatch=monkeypatch)
    slug = str(no.raw_symbol)
    sender.response = VenueResponse(
        status=200, headers={}, body=_accept_fill_body(slug, order_id="ord-no-create-1")
    )
    await fixture.client._connect()
    from nautilus_trader.execution.messages import SubmitOrder

    order = _limit_buy(no, price="0.63")
    command = SubmitOrder(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        order=order,
        command_id=UUID4(),
        ts_init=TS_INIT,
    )
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await fixture.client._submit_order(command)
    record = _reopened_fill_record(fixture.store_path, "ord-no-create-1")
    assert record is not None
    # Rev 5 (E5-1): the venue echoed wire price 0.37 (YES-denominated);
    # booked cost must reflect the NO-instrument price 0.63, not the wire
    # value -- proof the create path's fill parsing inverts it.
    assert record.cumulative_cost == Decimal("0.63")
    assert record.instrument_id == str(no.id)
    await fixture.client._disconnect()


@pytest.mark.asyncio
async def test_a_no_leg_fill_seeds_the_ledger_at_its_premium(
    tmp_path: Path, legs: tuple[BinaryOption, BinaryOption], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_seed_spend_from_durable_fills` walks `list_all()` over every loaded
    instrument, so a NO fill (recorded through the real writer, `record_
    fill` -- L-42) sums into the same ledger the YES leg would."""
    _yes, no = legs
    fixture = _build_client(tmp_path, legs=legs, monkeypatch=monkeypatch)
    await fixture.client._connect()
    now_ns = fixture.client._clock.timestamp_ns()
    record = DurableFillRecord(
        venue_order_id="venue-no-seed-1",
        client_order_id="O-19700101-000000-001-001-1",
        instrument_id=str(no.id),
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.63"),
        cumulative_fee=Decimal("0.00"),
        fee_reconciled=True,
        ts_event=now_ns,
    )
    fixture.client.record_fill(record)
    ledger = fixture.client._ledger
    assert ledger is not None
    before = ledger.spent_today_usd(now_ns=now_ns)
    fixture.client._seed_spend_from_durable_fills()
    after = ledger.spent_today_usd(now_ns=now_ns)
    assert after - before == Decimal("0.63")
    await fixture.client._disconnect()
