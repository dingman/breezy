"""R-4: the reconciling, order-refusing Polymarket.us execution client.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-4.

Every test here drives the REAL client against a REAL Nautilus ``MessageBus``,
``Cache``, ``LiveClock`` and ``InstrumentProvider``, with a real
``SqliteStateStore`` on a temporary path. Only the venue read is a stub, and it
is a stub because R-4 must not open a socket: the client takes the private read
as an injected coroutine, so this suite substitutes a payload table rather than
patching a transport.

WHAT THIS INCREMENT IS FOR, AND WHY THE ASSERTIONS ARE SHAPED THIS WAY

R-4 publishes Breezy's first ``AccountState``, and the Nautilus risk engine is
INERT until one exists (``risk/engine.pyx:684-689`` returns ``True`` when
``account_for_venue`` is ``None``, pinned by
``tests/contract/test_risk_engine_ordering_enforcement.py``). So the account
state is not bookkeeping -- it is the event that turns every notional cap on.
It is asserted for issuer, currency and amount rather than merely for
existence.

The second shape is refusal. This increment can reconcile, and it can do
nothing else: ``_submit_order`` and ``_cancel_order`` carry denial bodies and
the other four lifecycle coroutines raise. There is no configuration, no
environment variable and no argument that makes an order sendable here, and
several tests exist only to keep that true.

No test in this module assigns a value to either operator-reserved control
(max daily budget, max per position). Their absence fails closed, and R-4 does
not read them at all -- it refuses every order unconditionally, which is
strictly stronger.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import inspect
import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final

import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.common.messages import ShutdownSystem
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import (
    BatchCancelOrders,
    CancelAllOrders,
    CancelOrder,
    GenerateFillReports,
    GenerateOrderStatusReports,
    GeneratePositionStatusReports,
    ModifyOrder,
    QueryAccount,
    QueryOrder,
    SubmitOrder,
    SubmitOrderList,
)
from nautilus_trader.execution.reports import ExecutionMassStatus, OrderStatusReport
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import (
    LiquiditySide,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    TimeInForce,
)
from nautilus_trader.model.events import AccountState, OrderDenied, OrderFilled, OrderSubmitted
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientId,
    ClientOrderId,
    StrategyId,
    TraderId,
    VenueOrderId,
)
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.orders.list import OrderList

import breezy.adapters.polymarket_us.exec.client as client_module
from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError, PolymarketUSError
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    RESOLVER_CONTEXT_KEY_PREFIX,
    VENUE_ORDER_ID_KEY_PREFIX,
    AmbiguousResolverContext,
    DurableFillRecord,
    PolymarketUSExecutionClient,
    PrivateRead,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.exec.refusals import (
    ClassifiedRefusal,
    PrivateReadRefused,
    RefusalClass,
)
from breezy.adapters.polymarket_us.exec.reports import build_execution_mass_status
from breezy.adapters.polymarket_us.exec_fault import (
    clear_fatal_exec_fault,
    fatal_exec_fault,
)
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
    utc_day_for_ns,
)
from breezy.adapters.polymarket_us.parsing import FEE_COEFFICIENT_KEY, parse_binary_option
from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermissionError,
    issue_live_trading_permit,
    live_trading_budget_remaining,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntentState,
    open_submit_intent_latch,
)
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import (
    TS_EVENT_TEXT,
    build_execution,
    build_instrument,
    build_order,
    build_position,
    build_second_instrument,
)
from tests.unit.test_polymarket_us_permit_issuance import credentials, enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    # Reused, never redefined: `_find_write_transport_canonical_setattr_sites`
    # (`test_polymarket_us_submit_order_chain.py`) pins an EXACT set of files
    # that may `setattr` `write_transport.WRITE_CANONICAL_STRING_VERIFIED`; a
    # second monkeypatch site here would widen it. This module never calls
    # `setattr` on that attribute itself -- it imports the one fixture that
    # already does, the same reuse pattern
    # `test_order_submission_permit_issuance.py` and
    # `test_current_rung_hold_order_submission_wiring.py` already use.
    write_canonical_verified,  # noqa: F401
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

    from nautilus_trader.model.instruments import BinaryOption

TRADER_ID: Final[TraderId] = TraderId("BREEZY-R4-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("WEATHER-001")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
ACCOUNT_NUMBER: Final[str] = "001"

#: A ``GetAccountBalancesResponse`` with a spendable USD balance. The literals
#: are bare JSON numbers because the venue types the private money fields as
#: ``float`` -- which is the whole reason R-3 ships a Decimal-preserving decode.
BALANCE_TOTAL: Final[Decimal] = Decimal("125.50")
BALANCE_FREE: Final[Decimal] = Decimal("120.25")

#: The price a durable fill record says Breezy opened at. Deliberately not a
#: round number and never 0.00: a test that accepted the synthetic zero would
#: be indistinguishable from one that passed.
RECORDED_OPEN_PRICE: Final[Decimal] = Decimal("0.37")
RECORDED_QUANTITY: Final[Decimal] = Decimal(4)
#: The cumulative cost that price implies. The record stores COST, not a price:
#: see `DurableFillRecord`, which is cumulative PER VENUE ORDER.
RECORDED_COST: Final[Decimal] = RECORDED_OPEN_PRICE * RECORDED_QUANTITY

TS_INIT: Final[int] = 1_787_617_213_000_000_000


@pytest.fixture(autouse=True)
def _clean_exec_fault_latch() -> Iterator[None]:
    """The exec-fault latch is process-global (`exec_fault.py`); a test that
    forces `_connect` to fail must not poison a later, unrelated test."""
    clear_fatal_exec_fault()
    yield
    clear_fatal_exec_fault()


# ---------------------------------------------------------------------------
# Rig
# ---------------------------------------------------------------------------


def _balances_payload() -> dict[str, Any]:
    return {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": BALANCE_TOTAL,
                "buyingPower": BALANCE_FREE,
                "lastUpdated": TS_EVENT_TEXT,
            },
        ],
    }


class _PrivateReadStub:
    """The injected venue read. Records every path, opens no socket."""

    def __init__(self, payloads: dict[str, Any]) -> None:
        self._payloads = payloads
        self.paths: list[str] = []
        self.raises: dict[str, Exception] = {}

    async def __call__(self, path: str) -> Mapping[str, Any]:
        self.paths.append(path)
        error = self.raises.get(path)
        if error is not None:
            raise error
        payload: Mapping[str, Any] = self._payloads[path]
        return payload


class _Rig:
    """The client under test, plus every message it emitted."""

    def __init__(
        self,
        *,
        client: PolymarketUSExecutionClient,
        cache: Cache,
        msgbus: MessageBus,
        instrument: BinaryOption,
        read: _PrivateReadStub,
        account_states: list[AccountState],
        order_events: list[Any],
        clock: LiveClock,
        store_path: Path,
    ) -> None:
        self.client = client
        self.cache = cache
        self.msgbus = msgbus
        self.instrument = instrument
        self.read = read
        self.account_states = account_states
        self.order_events = order_events
        self.clock = clock
        self.store_path = store_path

    def submit_command(self) -> SubmitOrder:
        factory = OrderFactory(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            clock=LiveClock(),
        )
        order = factory.market(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,  # long only; `allow_short=False`
            quantity=Quantity(1, self.instrument.size_precision),
            time_in_force=TimeInForce.IOC,
        )
        return SubmitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            order=order,
            command_id=UUID4(),
            ts_init=TS_INIT,
        )


def _build_rig(
    tmp_path: Path,
    *,
    positions: dict[str, Any] | None = None,
    instrument_loaded: bool = True,
    store_opener: Any = None,
    instrument_wait_timeout_s: Any = 1.0,
    spend_ledger: Any = None,
    live_trading_permit: Any = None,
    store_path: Path | None = None,
) -> _Rig:
    loop = asyncio.get_running_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))

    instrument = build_instrument()
    cache.add_instrument(instrument)

    provider = InstrumentProvider()
    if instrument_loaded:
        provider.add(instrument)

    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: {"positions": dict(positions or {}), "eof": True},
        },
    )

    account_states: list[AccountState] = []
    order_events: list[Any] = []

    def _on_account_state(state: AccountState) -> None:
        account_states.append(state)
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)
    msgbus.register(endpoint="ExecEngine.process", handler=order_events.append)

    resolved_store_path = store_path or (tmp_path / "exec_state.db")
    opener = store_opener or (lambda: SqliteStateStore(resolved_store_path))
    client = PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=read,
        state_store_opener=opener,
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=instrument_wait_timeout_s,
        account_registration_timeout_s=1.0,
        spend_ledger=spend_ledger,
        live_trading_permit=live_trading_permit,
    )
    return _Rig(
        client=client,
        cache=cache,
        msgbus=msgbus,
        instrument=instrument,
        read=read,
        account_states=account_states,
        order_events=order_events,
        clock=clock,
        store_path=resolved_store_path,
    )


def _slug(instrument: BinaryOption) -> str:
    return str(instrument.symbol.value)


def _record(
    rig: _Rig,
    *,
    order: str = "V-OPEN-1",
    qty: Decimal = RECORDED_QUANTITY,
    cost: Decimal = RECORDED_COST,
    side: str = "BUY",
    fee: Decimal = Decimal("0.00"),
    fee_reconciled: bool = True,
) -> DurableFillRecord:
    """One cumulative record for one venue order."""
    return DurableFillRecord(
        venue_order_id=order,
        client_order_id="O-19700101-000000-001-001-1",
        instrument_id=str(rig.instrument.id),
        order_side=side,
        cumulative_qty=qty,
        cumulative_cost=cost,
        cumulative_fee=fee,
        fee_reconciled=fee_reconciled,
        ts_event=TS_INIT,
    )


# ---------------------------------------------------------------------------
# The account state -- the event that de-inerts every Nautilus cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_publishes_an_account_state_with_the_issued_id_and_a_usd_balance(
    tmp_path: Path,
) -> None:
    """The first `AccountState` Breezy has ever published.

    Until this event lands, `risk/engine.pyx:684-689` returns `True` for every
    order regardless of notional. The issuer is asserted because
    `_set_account_id` (`execution/client.pyx:148-152`) requires
    `account_id.get_issuer() == client_id`, and a mismatch is the failure that
    leaves the account unfindable by venue.
    """
    rig = _build_rig(tmp_path)
    await rig.client._connect()

    assert len(rig.account_states) == 1
    state = rig.account_states[0]
    assert state.account_id == AccountId(f"{CLIENT_ID.value}-{ACCOUNT_NUMBER}")
    assert state.account_id.get_issuer() == CLIENT_ID.value
    assert state.is_reported is True

    balance = state.balances[0]
    assert balance.total == Money(BALANCE_TOTAL, balance.currency)
    assert balance.free == Money(BALANCE_FREE, balance.currency)
    assert balance.currency.code == "USD"

    assert rig.cache.account_for_venue(POLYMARKET_US_VENUE) is not None

    # EXEC SPINE W done-predicate clauses 1 & 2: a healthy connect must be
    # distinguishable from one that latched a refusal purely by coincidence
    # (e.g. an instrument-load timeout also denies every order). Both must
    # hold on the SAME successful connect this test already exercises.
    assert rig.client.trading_refusals == ()
    assert rig.client._instrument_provider.count > 0

    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_query_account_republishes_the_account_state(tmp_path: Path) -> None:
    """`_query_account` is absent from `LiveExecutionClient` and is CALLED at
    `live/execution_client.py:332`; without it that path raises."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    await rig.client._query_account(
        QueryAccount(
            trader_id=TRADER_ID,
            account_id=AccountId(f"{CLIENT_ID.value}-{ACCOUNT_NUMBER}"),
            command_id=UUID4(),
            ts_init=TS_INIT,
        ),
    )
    assert len(rig.account_states) == 2
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# `_query_order` -- NOT absent from the base, a report-injection seam CLOSED
# by this client's own `generate_order_status_report` always returning `None`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_native_query_order_never_reaches_the_send_seam(tmp_path: Path) -> None:
    """`_query_order` (`live/execution_client.py:516-532`) is genuinely
    inherited, not absent: it calls `generate_order_status_report` and, if the
    result is non-`None`, `_send_order_status_report` -- a report-injection
    seam that bypasses `_submit_order`'s refusal latch entirely. This client's
    override always returns `None` (see its own docstring), so the seam is
    closed BEHAVIOURALLY -- but that closure was never pinned. If a future
    change to `generate_order_status_report` ever returned a real report, this
    is the test that would catch the seam opening.
    """
    rig = _build_rig(tmp_path)
    await rig.client._connect()

    def _fail_if_reached(report: Any) -> None:
        pytest.fail(f"_send_order_status_report was reached with {report!r}")

    rig.client._send_order_status_report = _fail_if_reached

    await rig.client._query_order(
        QueryOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=rig.instrument.id,
            client_order_id=ClientOrderId("O-19700101-000000-001-001-1"),
            venue_order_id=None,
            command_id=UUID4(),
            ts_init=TS_INIT,
        ),
    )
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_native_query_order_DOES_reach_the_send_seam_given_a_real_report(
    tmp_path: Path,
) -> None:
    """Non-vacuity of the test above: the seam is real and reachable, it is
    only this client's own `None` return that keeps it closed. Without this,
    the previous test would pass just as happily against a base method that
    never calls `_send_order_status_report` at all."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()

    report = OrderStatusReport(
        account_id=rig.client._issued_account_id,
        instrument_id=rig.instrument.id,
        venue_order_id=VenueOrderId("V-1"),
        order_side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.IOC,
        order_status=OrderStatus.FILLED,
        quantity=Quantity(1, rig.instrument.size_precision),
        filled_qty=Quantity(1, rig.instrument.size_precision),
        report_id=UUID4(),
        ts_accepted=TS_INIT,
        ts_last=TS_INIT,
        ts_init=TS_INIT,
    )

    async def _fake_generate(command: Any) -> OrderStatusReport:
        return report

    received: list[Any] = []
    rig.client.generate_order_status_report = _fake_generate  # type: ignore[method-assign]
    rig.client._send_order_status_report = received.append

    await rig.client._query_order(
        QueryOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=rig.instrument.id,
            client_order_id=ClientOrderId("O-19700101-000000-001-001-1"),
            venue_order_id=VenueOrderId("V-1"),
            command_id=UUID4(),
            ts_init=TS_INIT,
        ),
    )
    assert received == [report]
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# Mass status -- the trap: `None` means the trader never starts, silently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mass_status_on_an_empty_account_is_empty_but_not_none(
    tmp_path: Path,
) -> None:
    """A flat, orderless account reconciles. `None` would abort the start-up."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()

    mass_status = await rig.client.generate_mass_status()

    assert isinstance(mass_status, ExecutionMassStatus)
    assert mass_status.venue == POLYMARKET_US_VENUE
    assert mass_status.order_reports == {}
    assert mass_status.fill_reports == {}
    assert mass_status.position_reports == {}
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_mass_status_is_never_none_when_the_venue_read_fails(
    tmp_path: Path,
) -> None:
    """`live/execution_client.py:512-514` swallows ANY exception and returns
    `None`, which fails reconciliation and stops the trader with no order and
    no explanation. The failure is caught and reported INSIDE instead, and it
    latches a trading refusal so the node is inert rather than confident."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.read.raises[PORTFOLIO_POSITIONS_PATH] = RuntimeError("venue read failed")

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert mass_status.position_reports == {}
    assert rig.client.trading_refusals != ()
    assert any("position" in reason.lower() for reason in rig.client.trading_refusals)
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# R-6.5a -- a status-carrying refusal is classified on its real status,
# never decoded as if it were a payload
# ---------------------------------------------------------------------------


def _grpc_body(code: int) -> bytes:
    return json.dumps({"code": code, "message": "x", "details": []}).encode("utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        pytest.param(503, _grpc_body(14), RefusalClass.TRANSIENT, id="503-unavailable-transient"),
        pytest.param(404, _grpc_body(5), RefusalClass.DURABLE, id="404-not-found-durable"),
    ],
)
async def test_a_failed_positions_read_latches_the_status_derived_classification(
    tmp_path: Path,
    status: int,
    body: bytes,
    expected: RefusalClass,
) -> None:
    """A `PrivateReadRefused` reaching `generate_position_status_reports` is
    classified from its OWN status and body, not defaulted blind.

    Today `_trading_refusals` is `list[str]` and no classification exists at
    all, so this fails before it can even reach the assertion below.
    """
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.read.raises[PORTFOLIO_POSITIONS_PATH] = PrivateReadRefused(
        status=status, path=PORTFOLIO_POSITIONS_PATH, body=body
    )

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert rig.client.trading_refusals != ()
    assert rig.client._trading_refusals[-1].classification is expected
    await rig.client._disconnect()


def test_classify_venue_refusal_has_a_production_caller() -> None:
    """The inverse of R-6e's zero-callers pin.

    `classify_venue_refusal` shipped in R-6d with no caller anywhere in
    `src/`; R-6.5a gives it its first one, in the except branch that catches
    `PrivateReadRefused`. Today this fails: no such call exists yet.
    """
    source = Path(client_module.__file__).read_text(encoding="utf-8")
    assert "classify_venue_refusal(" in source


def test_private_read_call_still_takes_only_a_path() -> None:
    """PIN: the GET-only, no-query guarantee. D1/D2/D3 touch the refusal
    store and the closure's body, never `PrivateRead.__call__`'s signature."""
    params = list(inspect.signature(PrivateRead.__call__).parameters)
    assert params == ["self", "path"]


def test_refuse_producer_count_stays_pinned_at_twenty_seven() -> None:
    """PIN: widened old(27) -> new(29) for I1b's exactly TWO new producers,
    `self._refuse(_FILL_WRITE_FAILED)` and `self._refuse(_FEE_UNRECONCILED)`
    in `_submit_order`'s `KIND_ACCEPT_FILL` branch
    (LIVE_FILL_SCORING_CHAIN_2026-09-05). Widened AGAIN old(29) -> new(30) by
    slice 3 (plan rev 6.1): `_resolve_accept_fill`'s own
    `self._refuse(_FILL_WRITE_FAILED)`, mirroring `_submit_order`'s identical
    fail-closed guard around its own `record_fill` call. Widened AGAIN
    old(30) -> new(33) by A1 (SP-3): three new fail-closed venue-id
    map-write refusals (`_submit_order`'s new site plus one each in
    `_resolve_accept_fill` and `_resolve_terminal_zero`). Never relaxed,
    only widened (L-12).

    The authoritative, triaged inventory is
    `tests/unit/test_exec_refusal_health_surface.py::REFUSAL_PRODUCERS`,
    updated in the SAME commit as this pin; this is the cheap local pin
    that catches a moved count without importing that module's internals.
    """
    source = Path(client_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    count = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_refuse"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    )
    assert count == 33


@pytest.mark.asyncio
async def test_mass_status_is_never_none_when_the_ASSEMBLY_itself_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The assembly ran OUTSIDE the `try`.

    `build_execution_mass_status` constructs a real `ExecutionMassStatus` and
    calls three native `add_*_reports`; anything it raised escaped to the
    native `return None` path -- the silent non-start this module exists to
    prevent, arriving through the one statement not covered.
    """
    real = build_execution_mass_status

    def _fails_on_any_report(**kwargs: Any) -> Any:
        if kwargs["order_reports"] or kwargs["fill_reports"] or kwargs["position_reports"]:
            raise RuntimeError("native assembly rejected a report")
        return real(**kwargs)

    slug = _slug(build_instrument())
    rig = _build_rig(tmp_path, positions={slug: _position(slug)})
    await rig.client._connect()
    monkeypatch.setattr(client_module, "build_execution_mass_status", _fails_on_any_report)

    mass_status = await rig.client.generate_mass_status()

    assert isinstance(mass_status, ExecutionMassStatus)
    assert mass_status.position_reports == {}
    assert any("assembl" in reason.lower() for reason in rig.client.trading_refusals), (
        rig.client.trading_refusals
    )
    assert rig.client.reconciliation_active is False
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_the_report_generators_never_raise_into_the_native_handler(
    tmp_path: Path,
) -> None:
    """Belt and braces for the same trap: even called directly by the native
    `generate_mass_status`, none of the three may raise."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    for path in (ACCOUNT_BALANCES_PATH, PORTFOLIO_POSITIONS_PATH):
        rig.read.raises[path] = RuntimeError("venue read failed")

    assert (
        await rig.client.generate_order_status_reports(
            GenerateOrderStatusReports(
                instrument_id=None,
                start=None,
                end=None,
                open_only=False,
                command_id=UUID4(),
                ts_init=TS_INIT,
            ),
        )
        == []
    )
    assert (
        await rig.client.generate_fill_reports(
            GenerateFillReports(
                instrument_id=None,
                venue_order_id=None,
                start=None,
                end=None,
                command_id=UUID4(),
                ts_init=TS_INIT,
            ),
        )
        == []
    )
    assert (
        await rig.client.generate_position_status_reports(
            GeneratePositionStatusReports(
                instrument_id=None,
                start=None,
                end=None,
                command_id=UUID4(),
                ts_init=TS_INIT,
            ),
        )
        == []
    )
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# `_declared_positions` -- an absent map is not an empty map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"positions": None},
        {"positions": ["not", "a", "dict"]},
    ],
    ids=["absent-key", "explicit-none", "non-dict-list"],
)
def test_declared_positions_refuses_a_foreign_shape(payload: dict[str, Any]) -> None:
    """An absent, `None`, or non-dict `positions` value is a REFUSAL, never
    treated as an empty map -- a foreign response shape must not be silently
    read as "the venue holds nothing"."""
    with pytest.raises(ExecutionReportMappingError):
        PolymarketUSExecutionClient._declared_positions(payload)


def test_declared_positions_accepts_a_genuinely_empty_map() -> None:
    """`{"positions": {}, "eof": True}` IS the true "nothing held" shape, and
    must NOT be refused -- the empty-dict case is what the three refusals
    above exist to keep distinct. `eof: True` is required here too (R-4P-1):
    an empty page that is NOT the last page is still a truncation."""
    assert (
        PolymarketUSExecutionClient._declared_positions({"positions": {}, "eof": True}) == {}
    )


# ---------------------------------------------------------------------------
# R-4P-1 -- a non-terminal page is a REFUSAL, never a silently-accepted
# partial book. `GetUserPositionsResponse` is cursor-paginated (`eof`,
# `nextCursor` alongside `positions`); R-4 as originally landed read only
# `payload["positions"]` and stopped, so a real multi-page account would
# reconcile page 1 and call it the whole book -- an under-reported book
# that every risk cap sizes off. This is the INTERIM fix only
# (R-4P-1): refuse the truncation. Cursor-following pagination (R-4P-2) is
# deliberately deferred.
# ---------------------------------------------------------------------------


def test_a_non_terminal_positions_page_latches_a_refusal() -> None:
    """`eof: False` is an explicit, unambiguous "there is more"."""
    with pytest.raises(ExecutionReportMappingError, match="eof"):
        PolymarketUSExecutionClient._declared_positions({"positions": {}, "eof": False})


def test_an_absent_eof_is_treated_as_non_terminal() -> None:
    """`GetUserPositionsResponse` is `total=False`: an absent `eof` is
    UNKNOWN, not `True`. Treating "absent" as "complete" is exactly the R-4
    defect, so absence must refuse exactly like an explicit `False`."""
    with pytest.raises(ExecutionReportMappingError, match="eof"):
        PolymarketUSExecutionClient._declared_positions({"positions": {}})


def test_a_terminal_page_reconciles_normally() -> None:
    """Non-vacuity: the increment must not refuse EVERY page -- only
    non-terminal ones. `eof: True` with real positions passes through."""
    positions = {"some-slug": {"netPosition": "1"}}
    assert (
        PolymarketUSExecutionClient._declared_positions({"positions": positions, "eof": True})
        == positions
    )


# ---------------------------------------------------------------------------
# Positions -- the synthetic zero, and the durable fill record
# ---------------------------------------------------------------------------


def _position(
    slug: str,
    *,
    net: str = "4",
    bought: str = "4",
    sold: str = "0",
    cost: str = "2.08",
) -> dict[str, Any]:
    """A ``UserPosition`` with the three cost-basis fields under our control."""
    payload = build_position(slug)
    payload["netPosition"] = net
    payload["qtyBought"] = bought
    payload["qtySold"] = sold
    payload["cost"] = {"value": cost, "currency": "USD"}
    return payload


@pytest.mark.asyncio
async def test_a_transient_refusal_for_one_instrument_is_dropped_after_it_reconciles(
    tmp_path: Path,
) -> None:
    """`refusals_after_successful_reconcile` wired at `_map_position`'s
    success point -- the narrowest one that covers every outcome under it
    (expired, FLAT, or a live LONG), right after the payload is mapped and
    before any of those three are distinguished.

    This client has no per-instrument HTTP status to classify from today
    (only the whole-account positions/balances reads carry one, and neither
    is scoped to a single instrument), so the TRANSIENT/DURABLE pair here is
    PLANTED directly rather than produced by a live failure -- what is under
    test is the WIRING, that a successful reconcile of `slug` re-derives the
    refusal set exactly as `refusals_after_successful_reconcile` does. The
    classifier itself is covered in isolation by
    `test_polymarket_us_exec_refusals.py`.

    Today `refusals_after_successful_reconcile` has zero callers, so nothing
    clears the seeded transient entry and this fails.
    """
    slug = _slug(build_instrument())
    other_slug = "highest-temperature-in-chicago-on-september-2"
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.client._trading_refusals = [
        ClassifiedRefusal(
            instrument=slug, reason="transient here", classification=RefusalClass.TRANSIENT
        ),
        ClassifiedRefusal(
            instrument=slug, reason="durable here", classification=RefusalClass.DURABLE
        ),
        ClassifiedRefusal(
            instrument=other_slug,
            reason="transient elsewhere",
            classification=RefusalClass.TRANSIENT,
        ),
    ]

    report = rig.client._map_position(slug, _position(slug))

    assert report is not None
    reasons = {refusal.reason for refusal in rig.client._trading_refusals}
    assert "transient here" not in reasons, reasons
    assert "durable here" in reasons, reasons
    assert "transient elsewhere" in reasons, reasons
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_second_degrade_is_never_triggered_once_the_refusal_list_empties(
    tmp_path: Path,
) -> None:
    """The double-degrade trap: `_map_position`'s reconciliation-clearing
    call can empty `_trading_refusals` entirely while the component is
    STILL degraded from an earlier refusal. Keying the next `degrade()` call
    on "the list was empty a moment ago" recomputes `True` and fires a
    SECOND, invalid FSM transition -- caught and logged as an ERROR by
    Nautilus's own `_trigger_fsm`, not raised, so nothing but a spy or the
    log itself would ever show it.

    Reproduced today (RED) against the unfixed gate: a durable-fill-matched
    reconcile of `slug` empties the seeded TRANSIENT entry with no NEW
    refusal appended in the same call, then a second, unrelated `_refuse`
    finds an empty list and re-degrades. The fix keys on `self.is_degraded`
    (the native FSM state), never on the list's momentary emptiness.
    """
    rig = _build_rig(tmp_path)
    rig.client.start()
    assert rig.client.is_running
    await rig.client._connect()
    slug = _slug(rig.instrument)
    rig.client.record_fill(_record(rig, qty=RECORDED_QUANTITY, cost=RECORDED_COST))

    rig.client._trading_refusals = [
        ClassifiedRefusal(
            instrument=slug, reason="transient here", classification=RefusalClass.TRANSIENT
        ),
    ]
    rig.client.degrade()
    assert rig.client.is_degraded

    degrade_calls: list[None] = []
    original_degrade = rig.client.degrade

    def _spy() -> None:
        degrade_calls.append(None)
        original_degrade()

    rig.client.degrade = _spy

    report = rig.client._map_position(slug, _position(slug))
    assert report is not None
    assert rig.client._trading_refusals == [], rig.client._trading_refusals

    rig.client._refuse("a second, unrelated reason")

    assert degrade_calls == [], "degrade() must not fire again once already DEGRADED"
    assert rig.client.is_degraded
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_foreign_long_position_is_forwarded_priced_from_the_venue_cost_basis(
    tmp_path: Path,
) -> None:
    """Every LONG is forwarded. Excluding one HIDES it from every cap.

    Breezy's caps read `Strategy.portfolio.net_position`, which is derived
    from the reconciled position; a position dropped here reads ZERO there, so
    `max_position_contracts`, `max_event_notional` and `exclusive_conflict`
    would all size against a bucket the account already holds. The exposure is
    real whether or not we can attribute it, so it is REPORTED and the
    inability to attribute it is latched as a refusal instead.

    With no fill record, the price comes from the venue's own `cost`/
    `qtyBought`, which is a sound derivation exactly while `qtySold == 0`.
    """
    slug = _slug(build_instrument())
    rig = _build_rig(tmp_path, positions={slug: _position(slug)})
    await rig.client._connect()

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    reports = mass_status.position_reports[rig.instrument.id]
    assert len(reports) == 1
    assert reports[0].avg_px_open == Decimal("0.52")  # 2.08 / 4
    assert reports[0].quantity == Quantity(4, rig.instrument.size_precision)
    assert any("no durable fill record" in reason for reason in rig.client.trading_refusals), (
        rig.client.trading_refusals
    )
    assert any(str(rig.instrument.id) in reason for reason in rig.client.trading_refusals)
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_long_position_the_venue_cannot_price_is_forwarded_unpriced(
    tmp_path: Path,
) -> None:
    """`cost` is undefined as to whether it nets sells, so a position with a
    SELL in its history cannot be priced from it. It is still forwarded --
    unpriced and refused -- because a hidden position is worse than an
    imprecise one, and the refusal guarantees Breezy never trades against it.
    """
    slug = _slug(build_instrument())
    rig = _build_rig(
        tmp_path,
        positions={slug: _position(slug, net="4", bought="5", sold="1")},
    )
    await rig.client._connect()

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    reports = mass_status.position_reports[rig.instrument.id]
    assert len(reports) == 1
    assert reports[0].avg_px_open is None
    assert any("UNPRICED" in reason for reason in rig.client.trading_refusals), (
        rig.client.trading_refusals
    )
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_position_matching_a_durable_fill_record_is_priced_from_it(
    tmp_path: Path,
) -> None:
    """The goal-state clause: `avg_px_open` comes from what Breezy actually
    paid, so no reconciliation fallback price is ever reached."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()

    rig.client.record_fill(_record(rig, qty=RECORDED_QUANTITY, cost=RECORDED_COST))
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {_slug(rig.instrument): _position(_slug(rig.instrument))},
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    reports = mass_status.position_reports
    assert list(reports) == [rig.instrument.id]
    assert len(reports[rig.instrument.id]) == 1
    report = reports[rig.instrument.id][0]
    assert report.position_side == PositionSide.LONG
    assert report.quantity == Quantity(RECORDED_QUANTITY, rig.instrument.size_precision)
    # Our own record (0.37), NOT the venue's cost basis (2.08 / 4 = 0.52).
    assert report.avg_px_open == RECORDED_OPEN_PRICE
    assert report.avg_px_open != Decimal(0)
    assert rig.client.trading_refusals == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_two_venue_orders_average_by_TOTAL_cost_not_by_the_first_record(
    tmp_path: Path,
) -> None:
    """One clip per venue order, weighted by size -- `1 @ 0.30` plus
    `3 @ 0.40` is `0.375`, not `0.30` and not `0.35`."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.client.record_fill(_record(rig, order="V-OPEN-1", qty=Decimal(1), cost=Decimal("0.30")))
    rig.client.record_fill(_record(rig, order="V-OPEN-2", qty=Decimal(3), cost=Decimal("1.20")))
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {_slug(rig.instrument): _position(_slug(rig.instrument))},
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    report = mass_status.position_reports[rig.instrument.id][0]
    assert report.avg_px_open == Decimal("0.375")
    assert rig.client.trading_refusals == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_rewritten_record_is_a_cumulative_update_not_a_second_fill(
    tmp_path: Path,
) -> None:
    """The record is keyed by venue ORDER and is CUMULATIVE.

    One order sweeping several ask levels produces several fills at one
    ``venue_order_id``. Were the record per-fill, the rewrite would drop every
    earlier clip and the recorded size would stop matching the venue's, making
    Breezy's OWN position unattributable on the routine path.
    """
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.client.record_fill(_record(rig, qty=Decimal(1), cost=Decimal("0.30")))
    rig.client.record_fill(_record(rig, qty=Decimal(4), cost=Decimal("1.50")))
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {_slug(rig.instrument): _position(_slug(rig.instrument))},
        "eof": True,
    }

    assert len(rig.client.fill_records_for(rig.instrument.id)) == 1

    mass_status = await rig.client.generate_mass_status()

    report = mass_status.position_reports[rig.instrument.id][0]
    assert report.avg_px_open == Decimal("0.375")  # 1.50 / 4, the LATEST total
    assert rig.client.trading_refusals == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_sell_record_nets_against_the_long_records(tmp_path: Path) -> None:
    """After a partial exit (R-8/R-9) Breezy's OWN remaining position must stay
    attributable: a SELL record is netted, not treated as poison."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.client.record_fill(_record(rig, order="V-OPEN-1", qty=Decimal(4), cost=Decimal("2.00")))
    rig.client.record_fill(
        _record(rig, order="V-EXIT-1", qty=Decimal(1), cost=Decimal("0.60"), side="SELL"),
    )
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {_slug(rig.instrument): _position(_slug(rig.instrument), net="3")},
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    report = mass_status.position_reports[rig.instrument.id][0]
    assert report.quantity == Quantity(3, rig.instrument.size_precision)
    # (2.00 - 0.60) / (4 - 1)
    assert report.avg_px_open == Decimal("1.40") / Decimal(3)
    assert rig.client.trading_refusals == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_position_whose_size_exceeds_the_durable_record_is_still_forwarded(
    tmp_path: Path,
) -> None:
    """A partial match is not a match, so our own records cannot price the
    whole position -- but the excess is REAL exposure, so the position is
    forwarded on the venue's cost basis with the mismatch latched."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.client.record_fill(_record(rig, qty=Decimal(1), cost=RECORDED_OPEN_PRICE))
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {_slug(rig.instrument): _position(_slug(rig.instrument))},
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    reports = mass_status.position_reports[rig.instrument.id]
    assert len(reports) == 1
    assert reports[0].avg_px_open == Decimal("0.52")
    assert any("does not match" in reason for reason in rig.client.trading_refusals), (
        rig.client.trading_refusals
    )
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_an_expired_position_is_not_reported_as_live_risk(
    tmp_path: Path,
) -> None:
    """R-3 returns `MappedPosition(report, expired)`. A settled binary holding
    a nonzero net position is NOT capacity: reported, it would count as live
    exposure every cap downstream could still trade against."""
    settled = build_position(_slug(build_instrument()))
    settled["expired"] = True
    rig = _build_rig(tmp_path, positions={_slug(build_instrument()): settled})
    await rig.client._connect()
    rig.client.record_fill(_record(rig))

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert mass_status.position_reports == {}
    assert rig.client.settled_positions == (rig.instrument.id,)
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_position_in_an_unknown_market_is_refused_not_mapped(
    tmp_path: Path,
) -> None:
    """No instrument, no mapping. The position is real risk we cannot describe,
    so the node starts, alerts and denies."""
    rig = _build_rig(
        tmp_path,
        positions={"a-market-we-never-loaded": build_position("a-market-we-never-loaded")},
        instrument_loaded=False,
    )
    await rig.client._connect()

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert mass_status.position_reports == {}
    assert any("a-market-we-never-loaded" in reason for reason in rig.client.trading_refusals), (
        rig.client.trading_refusals
    )
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_position_under_an_unusable_slug_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """A slug that fails `assert_valid_slug` (symbology.py) never reaches
    instrument resolution at all -- it is refused as an unusable slug, a
    DIFFERENT reason from "no instrument is loaded"."""
    bad_slug = "bad.slug"  # "." collides with the InstrumentId delimiter
    rig = _build_rig(
        tmp_path,
        positions={bad_slug: build_position(bad_slug)},
    )
    await rig.client._connect()

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert mass_status.position_reports == {}
    assert any(
        "unusable slug" in reason and bad_slug in reason for reason in rig.client.trading_refusals
    ), rig.client.trading_refusals
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# Refusal -- no order may become sendable in this increment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_order_is_refused_and_denies_the_order(tmp_path: Path) -> None:
    """With a live account, a live store and a clean reconcile, the answer is
    still no. R-4 can reconcile and nothing else."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    command = rig.submit_command()

    await rig.client._submit_order(command)

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].client_order_id == command.order.client_order_id
    assert "R-4" in denials[0].reason or "refuses" in denials[0].reason.lower()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_submit_order_is_refused_before_any_account_exists(
    tmp_path: Path,
) -> None:
    """The §Ordering belt-and-braces fallback, measured.

    Every Nautilus cap is inert while `cache.account_for_venue(...)` is `None`,
    so the FIRST thing the submit path checks is that the account exists -- and
    it refuses by naming that, not by naming the venue.
    """
    rig = _build_rig(tmp_path)
    assert rig.cache.account_for_venue(POLYMARKET_US_VENUE) is None
    command = rig.submit_command()

    await rig.client._submit_order(command)

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert "account" in denials[0].reason.lower()


@pytest.mark.asyncio
async def test_a_latched_refusal_alone_denies_a_submitted_order(
    tmp_path: Path,
) -> None:
    """The refusal SET is the mechanism, not the R-4 standing denial.

    R-4 denies unconditionally, so this cannot be observed through the outcome
    -- only through the REASON. R-6 inherits this gate when the standing
    denial goes away, so it is proven here, while there is still a suite that
    can prove it.
    """
    slug = _slug(build_instrument())
    rig = _build_rig(tmp_path, positions={slug: _position(slug, bought="5", sold="1")})
    await rig.client._connect()
    await rig.client.generate_mass_status()
    assert rig.client.trading_refusals != ()
    assert rig.cache.account_for_venue(POLYMARKET_US_VENUE) is not None

    await rig.client._submit_order(rig.submit_command())

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert "refus" in denials[0].reason.lower()
    assert rig.client.trading_refusals[0] in denials[0].reason
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_cancel_order_is_refused(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path)
    await rig.client._connect()

    await rig.client._cancel_order(
        CancelOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=rig.instrument.id,
            client_order_id=ClientOrderId("O-19700101-000000-001-001-1"),
            venue_order_id=VenueOrderId("V-1"),
            command_id=UUID4(),
            ts_init=TS_INIT,
        ),
    )

    rejections = [
        event for event in rig.order_events if type(event).__name__ == "OrderCancelRejected"
    ]
    assert len(rejections) == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_the_other_four_lifecycle_coroutines_raise_unsupported(
    tmp_path: Path,
) -> None:
    """Only `_submit_order` and `_cancel_order` get denial bodies. The rest are
    not silently no-ops: a no-op would look like acceptance."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    order = rig.submit_command().order

    with pytest.raises(NotImplementedError):
        await rig.client._submit_order_list(
            SubmitOrderList(
                trader_id=TRADER_ID,
                strategy_id=STRATEGY_ID,
                order_list=OrderList(order_list_id_from(order), [order]),
                command_id=UUID4(),
                ts_init=TS_INIT,
            ),
        )
    with pytest.raises(NotImplementedError):
        await rig.client._modify_order(
            ModifyOrder(
                trader_id=TRADER_ID,
                strategy_id=STRATEGY_ID,
                instrument_id=rig.instrument.id,
                client_order_id=order.client_order_id,
                venue_order_id=None,
                quantity=None,
                price=None,
                trigger_price=None,
                command_id=UUID4(),
                ts_init=TS_INIT,
            ),
        )
    with pytest.raises(NotImplementedError):
        await rig.client._cancel_all_orders(
            CancelAllOrders(
                trader_id=TRADER_ID,
                strategy_id=STRATEGY_ID,
                instrument_id=rig.instrument.id,
                order_side=OrderSide.NO_ORDER_SIDE,
                command_id=UUID4(),
                ts_init=TS_INIT,
            ),
        )
    with pytest.raises(NotImplementedError):
        await rig.client._batch_cancel_orders(
            BatchCancelOrders(
                trader_id=TRADER_ID,
                strategy_id=STRATEGY_ID,
                instrument_id=rig.instrument.id,
                cancels=[
                    CancelOrder(
                        trader_id=TRADER_ID,
                        strategy_id=STRATEGY_ID,
                        instrument_id=rig.instrument.id,
                        client_order_id=order.client_order_id,
                        venue_order_id=VenueOrderId("V-1"),
                        command_id=UUID4(),
                        ts_init=TS_INIT,
                    ),
                ],
                command_id=UUID4(),
                ts_init=TS_INIT,
            ),
        )
    await rig.client._disconnect()


def order_list_id_from(order: Any) -> Any:
    from nautilus_trader.model.identifiers import OrderListId

    return OrderListId(f"OL-{order.client_order_id.value}")


# ---------------------------------------------------------------------------
# The durable store -- thread affinity is a hard precondition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_store_is_constructed_on_the_thread_that_writes_it(
    tmp_path: Path,
) -> None:
    """`SqliteStateStore` confines itself to its constructing thread
    (`sqlite_store.py:120`, `:128-135`). A store built in a config builder
    passes every other test in this file and fails only here."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()

    loop_thread = threading.get_ident()
    rig.client.record_venue_order_id(
        VenueOrderId("V-1"),
        ClientOrderId("O-19700101-000000-001-001-1"),
    )
    assert rig.client.state_store_owner_thread == loop_thread
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_store_built_on_a_foreign_thread_fails_the_connect(
    tmp_path: Path,
) -> None:
    """Non-vacuity of the affinity pin: the wrong construction site is caught
    at start-up, not at the first write months later."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        foreign = pool.submit(lambda: SqliteStateStore(tmp_path / "foreign.db")).result()
        rig = _build_rig(tmp_path, store_opener=lambda: foreign)
        with pytest.raises(Exception, match="durab|thread"):
            await rig.client._connect()
        assert rig.account_states == []
        pool.submit(foreign.close).result()


@pytest.mark.asyncio
async def test_the_durable_keys_carry_the_venue_namespace(tmp_path: Path) -> None:
    """`exec/<venue>/` IS the portability seam: a second venue gets its own
    prefix, never a shared one."""
    assert VENUE_ORDER_ID_KEY_PREFIX == "exec/polymarket_us/venue_id/"
    assert FILL_KEY_PREFIX == "exec/polymarket_us/fill/"
    assert FILL_INDEX_KEY_PREFIX.startswith("exec/polymarket_us/")

    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.client.record_venue_order_id(
        VenueOrderId("V-42"),
        ClientOrderId("O-19700101-000000-001-001-1"),
    )
    assert rig.client.client_order_id_for(VenueOrderId("V-42")) == ClientOrderId(
        "O-19700101-000000-001-001-1",
    )
    assert rig.client.client_order_id_for(VenueOrderId("V-99")) is None
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_fill_record_survives_reopening_the_store(tmp_path: Path) -> None:
    """The record is on disk, not in a dict: that is the whole point of it."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    record = _record(rig)
    rig.client.record_fill(record)
    await rig.client._disconnect()

    with SqliteStateStore(tmp_path / "exec_state.db") as reopened:
        raw = reopened.get(f"{FILL_KEY_PREFIX}V-OPEN-1")
    assert raw is not None
    assert DurableFillRecord.from_bytes(raw) == record
    assert json.loads(raw)["cumulativeCost"] == str(RECORDED_COST)


# ---------------------------------------------------------------------------
# `DurableFillRecord.from_bytes` -- non-finite decimals must REFUSE, not decode
# ---------------------------------------------------------------------------


def _raw_record(
    *,
    cumulative_qty: str = "4",
    cumulative_cost: str = "0.37",
    cumulative_fee: str = "0.00",
    fee_reconciled: bool = True,
    **extra: Any,
) -> bytes:
    """A legacy-shaped record: neither ``tradeId`` nor ``orderQty`` is a key
    here by default (B0, S-M1) -- exactly the shape of every record written
    before this change, ``venueFeeRaw`` included. ``**extra`` lets a caller
    add or override a key (e.g. a malformed ``orderQty``/``tradeId``) without
    a second fixture."""
    payload: dict[str, Any] = {
        "venueOrderId": "V-1",
        "clientOrderId": "O-19700101-000000-001-001-1",
        "instrumentId": "some-instrument",
        "orderSide": "BUY",
        "cumulativeQty": cumulative_qty,
        "cumulativeCost": cumulative_cost,
        "cumulativeFee": cumulative_fee,
        "feeReconciled": fee_reconciled,
        "tsEvent": TS_INIT,
    }
    payload.update(extra)
    return json.dumps(payload).encode("utf-8")


@pytest.mark.parametrize(
    ("cumulative_qty", "cumulative_cost"),
    [
        ("4", "NaN"),
        ("4", "Infinity"),
        ("4", "-Infinity"),
        ("NaN", "1.48"),
        ("Infinity", "1.48"),
    ],
)
def test_from_bytes_refuses_a_non_finite_decimal_field(
    cumulative_qty: str, cumulative_cost: str
) -> None:
    """Bare ``Decimal(str(...))`` decodes "NaN"/"Infinity" cleanly.

    Left unguarded, the later ``net_cost <= 0`` comparison in
    ``_entry_price_from_records`` raises ``decimal.InvalidOperation`` OUTSIDE
    the per-position ``try`` (it is called from ``_map_position``), which
    propagates all the way to ``generate_mass_status``'s OUTER except and
    discards every position report, not just the corrupt one. Refusing here,
    at decode time, is what keeps the corruption scoped to one record.
    """
    raw = _raw_record(cumulative_qty=cumulative_qty, cumulative_cost=cumulative_cost)
    with pytest.raises(ExecutionReportMappingError):
        DurableFillRecord.from_bytes(raw)


def test_from_bytes_malformed_message_names_the_missing_or_bad_field() -> None:
    """The malformed branch kept only ``type(exc).__name__``; the sibling JSON
    branch a few lines above it includes ``str(exc)``, which is what actually
    names the field. Both branches should say the same kind of thing."""
    with pytest.raises(ExecutionReportMappingError, match="cumulativeCost"):
        DurableFillRecord.from_bytes(_raw_record(cumulative_cost="NaN"))


@pytest.mark.asyncio
async def test_a_corrupted_fill_record_for_one_instrument_does_not_drop_a_healthy_sibling(
    tmp_path: Path,
) -> None:
    """One corrupt record must refuse ONLY its own instrument.

    Before the fix, `NaN` decoded cleanly and blew up `net_cost <= 0` with an
    uncaught `decimal.InvalidOperation` from inside `_map_position`, which
    propagated to `generate_mass_status`'s outer `except Exception` and wiped
    out EVERY position report -- including a completely healthy sibling
    instrument's.
    """
    healthy = build_instrument()
    corrupt = build_second_instrument()
    healthy_slug = _slug(healthy)
    corrupt_slug = str(corrupt.symbol.value)

    rig = _build_rig(
        tmp_path,
        positions={
            healthy_slug: _position(healthy_slug),
            corrupt_slug: _position(corrupt_slug),
        },
    )
    rig.cache.add_instrument(corrupt)
    rig.client._instrument_provider.add(corrupt)

    await rig.client._connect()
    rig.client.record_fill(_record(rig, qty=RECORDED_QUANTITY, cost=RECORDED_COST))
    rig.client.record_fill(
        DurableFillRecord(
            venue_order_id="V-CORRUPT-1",
            client_order_id="O-19700101-000000-001-001-2",
            instrument_id=str(corrupt.id),
            order_side="BUY",
            cumulative_qty=Decimal(4),
            cumulative_cost=Decimal("NaN"),
            cumulative_fee=Decimal("0.00"),
            fee_reconciled=True,
            ts_event=TS_INIT,
        ),
    )

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert rig.instrument.id in mass_status.position_reports, mass_status.position_reports
    healthy_reports = mass_status.position_reports[rig.instrument.id]
    assert len(healthy_reports) == 1
    assert healthy_reports[0].avg_px_open == RECORDED_OPEN_PRICE
    assert any(
        corrupt_slug in reason or str(corrupt.id) in reason
        for reason in rig.client.trading_refusals
    ), rig.client.trading_refusals
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_record_fill_refuses_to_overwrite_an_index_it_could_not_read(
    tmp_path: Path,
) -> None:
    """An index that will not decode holds ids we cannot see. Overwriting it
    with one entry destroys every surviving id, so the write is refused."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    rig.client._store_set(
        f"{FILL_INDEX_KEY_PREFIX}{rig.instrument.id}",
        b"{not json at all",
    )

    with pytest.raises(PolymarketUSError, match="index"):
        rig.client.record_fill(_record(rig))

    surviving = rig.client._store_get(f"{FILL_INDEX_KEY_PREFIX}{rig.instrument.id}")
    assert surviving == b"{not json at all"
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_store_that_cannot_be_proven_durable_is_closed_and_not_retained(
    tmp_path: Path,
) -> None:
    """The durability proof runs on the LOCAL handle, before assignment.

    Assigning first leaves the client holding a store PROVEN non-durable, with
    its sqlite handle never closed -- and `_require_store` only checks for
    `None`, so R-7's `record_fill` would happily write to it.
    """

    class _NonDurable:
        def __init__(self) -> None:
            self.closed = False

        def get(self, key: str) -> bytes | None:
            return None  # never persists anything

        def set(self, key: str, value: bytes) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    store = _NonDurable()
    rig = _build_rig(tmp_path, store_opener=lambda: store)

    with pytest.raises(Exception, match="write-through|durab|persist"):
        await rig.client._connect()

    assert store.closed is True
    assert rig.client._store is None
    assert rig.client.state_store_owner_thread is None


@pytest.mark.asyncio
async def test_a_boolean_timeout_is_refused_by_the_constructor(tmp_path: Path) -> None:
    """`bool` is a subclass of `int`, so `isinstance(x, (int, float))` accepts
    `True` and the client would then wait ONE second for the instrument load.
    A boolean where a duration was declared is a wiring bug, not a duration."""
    with pytest.raises(ValueError, match="instrument_wait_timeout_s"):
        _build_rig(tmp_path, instrument_wait_timeout_s=True)


# ---------------------------------------------------------------------------
# `_disconnect` -- a failing close must not abort the shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_drops_the_store_reference(tmp_path: Path) -> None:
    """The reference is dropped FIRST, so a half-closed handle is never
    reachable for a write afterwards."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    assert rig.client._store is not None

    await rig.client._disconnect()

    assert rig.client._store is None


@pytest.mark.asyncio
async def test_disconnect_swallows_a_failing_close(tmp_path: Path) -> None:
    """At the point `_disconnect` runs, the local handle is the ONLY one --
    an exception escaping `close()` would abort the disconnect over a
    resource that is already unreachable, so it is logged instead."""

    class _FailsToClose:
        def get(self, key: str) -> bytes | None:
            return None

        def set(self, key: str, value: bytes) -> None:
            return None

        def close(self) -> None:
            raise RuntimeError("disk gone")

    rig = _build_rig(tmp_path)
    await rig.client._connect()
    # The durability proof already ran against the REAL store; swap it out
    # afterwards so `_disconnect` is the only thing exercising the fake.
    rig.client._store = _FailsToClose()

    await rig.client._disconnect()  # must not raise

    assert rig.client._store is None


# ---------------------------------------------------------------------------
# Reconnect -- a latched refusal is a FAIL-SAFE and never self-clears
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_latched_refusal_persists_across_a_reconnect_after_the_condition_clears(
    tmp_path: Path,
) -> None:
    """The refusal set is NODE-GLOBAL and never self-clears: a restart
    re-derives it, but within one running client a `_disconnect` /
    `_connect` cycle must not wipe evidence of a fault that already fired --
    even after whatever caused it is fixed. This is the intended fail-safe,
    not a bug: an operator must see and act on the history, not have it
    silently reset by the next successful connect."""
    rig = _build_rig(tmp_path, instrument_loaded=False)
    await rig.client._connect()
    assert rig.client.trading_refusals != ()
    first_refusals = rig.client.trading_refusals

    await rig.client._disconnect()

    # The condition is now resolved -- the instrument is loaded.
    rig.client._instrument_provider.add(rig.instrument)
    await rig.client._connect()

    assert rig.client.trading_refusals[: len(first_refusals)] == first_refusals, (
        "a resolved condition must not erase a refusal that already fired"
    )
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# EXEC SPINE W, risk 2 -- a failed `_connect` must not exit `EXIT_OK` silently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_connect_is_observable_and_does_not_exit_zero(tmp_path: Path) -> None:
    """The exact chain risk 2 names, driven for real through the NATIVE
    `connect()` scheduler -- not by calling `_connect()` directly.

    `LiveExecutionClient.connect()` (`live/execution_client.py:239-249`)
    schedules `_connect()` as a task with `actions=lambda:
    self._set_connected(True)`. Its own `_on_task_completed`
    (`:204-232`) retrieves `task.exception()`, LOGS it, and returns WITHOUT
    calling `actions` when it is not `None` -- so `_set_connected(True)` never
    runs, and the task itself completes normally as far as the event loop is
    concerned. Nothing re-raises. Absent the fault latch this client's
    `_connect` now wraps, that is a completely silent failure: `is_connected`
    stays `False`, but nothing else on this client, and nothing in
    `breezy-trade`, would ever know why -- see
    `test_a_latched_execution_fault_is_reported_as_a_runtime_failure` in
    `tests/unit/test_trade_cli.py` for the other half of this chain.
    """

    def _raising_opener() -> Any:
        raise PermissionError("the state store directory is not writable")

    rig = _build_rig(tmp_path, store_opener=_raising_opener)
    rig.client.start()  # drive the FSM to RUNNING, exactly as the kernel does
    assert fatal_exec_fault() is None

    rig.client.connect()
    tasks = list(rig.client._tasks)
    assert len(tasks) == 1, "connect() must schedule exactly one task"

    done, pending = await asyncio.wait(tasks, timeout=5.0)
    assert pending == set()
    assert done == set(tasks), "the task must complete, not hang"

    # The defect this test pins: the task completing did NOT mean it succeeded.
    assert rig.client.is_connected is False

    fault = fatal_exec_fault()
    assert fault is not None, (
        "a failed _connect must be observable outside the client -- an "
        "operator (or breezy-trade) reading only `is_connected` cannot tell "
        "'never started' from 'refused to connect'"
    )
    assert fault.component == str(rig.client.id)
    assert "PermissionError" in fault.reason


@pytest.mark.asyncio
async def test_a_failed_connect_requests_a_native_system_shutdown(tmp_path: Path) -> None:
    """BALANCES_SHAPE_DRIFT_2026-09-04: the latch alone left the node
    ``RUNNING`` with ``ExecEngine.check_connected() == False`` for 60s until
    killed by hand -- nothing asked the kernel to stop. `_connect` must also
    publish the native `ShutdownSystem` command, exactly like the data
    client's own connect-failure path does
    (`test_polymarket_us_connect_fail_fast.py::
    test_a_connect_failure_requests_a_native_system_shutdown`).
    """
    rig = _build_rig(tmp_path)
    rig.read.raises[ACCOUNT_BALANCES_PATH] = PolymarketUSError(
        "simulated reconcile failure: drifted balances shape refused"
    )
    published: list[Any] = []
    rig.msgbus.subscribe("commands.system.shutdown", published.append)

    rig.client.start()
    rig.client.connect()
    tasks = list(rig.client._tasks)
    done, pending = await asyncio.wait(tasks, timeout=5.0)
    assert pending == set()
    assert done == set(tasks)

    assert fatal_exec_fault() is not None
    assert len(published) == 1, "exactly one ShutdownSystem command"
    command = published[0]
    assert isinstance(command, ShutdownSystem)
    assert command.component_id == rig.client.id


@pytest.mark.asyncio
async def test_a_successful_connect_never_latches_an_exec_fault(tmp_path: Path) -> None:
    """Non-vacuity for the test above: the happy path must not also latch."""
    rig = _build_rig(tmp_path)
    rig.client.start()

    rig.client.connect()
    tasks = list(rig.client._tasks)
    await asyncio.wait(tasks, timeout=5.0)

    assert rig.client.is_connected is True
    assert fatal_exec_fault() is None


# ---------------------------------------------------------------------------
# `calculate_commission` -- a NATIVE extension point, not a gap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculate_commission_prices_a_taker_fill_from_the_venue_model(
    tmp_path: Path,
) -> None:
    """`execution/client.pyx:165` exists to be overridden: "Override this
    method to provide venue-specific commission logic for inferred fills
    generated during reconciliation." Unoverridden it returns `None`, and
    `live/reconciliation.py:507-508` then books `Money(0, USD)` -- an
    implied-zero fee on every reconciled fill.

    Priced at 0.37, NOT at 0.50. The venue formula is `theta*C*p*(1-p)`, and
    at `p = 0.50` that equals `theta*C*p*p` and `theta*C*(1-p)*(1-p)`: three
    distinct formula mutations survive a test written on the symmetry point.
    """
    rig = _build_rig(tmp_path)
    assert Decimal(str(rig.instrument.info[FEE_COEFFICIENT_KEY])) == Decimal("0.06")

    commission = rig.client.calculate_commission(
        rig.instrument,
        Quantity(100, rig.instrument.size_precision),
        Price(Decimal("0.37"), rig.instrument.price_precision),
        LiquiditySide.TAKER,
    )

    # 0.06 * 100 * 0.37 * 0.63 = 1.3986, banker's-rounded to the cent.
    assert commission == Money(Decimal("1.40"), USD)
    assert rig.client.trading_refusals == ()


@pytest.mark.asyncio
async def test_calculate_commission_never_raises_on_an_unknown_fee_schedule(
    tmp_path: Path,
) -> None:
    """It MUST NOT raise: `live/reconciliation.py:506` calls it with no handler
    on the path from `live/execution_engine.py:3499`, so an uncontained raise
    is a node that does not START. `None` is inside the base contract
    (`execution/client.pyx:191`), and the latched refusal is what guarantees
    the mis-booked fill is on a position Breezy will never trade.
    """
    rig = _build_rig(tmp_path)
    payload = _market_payload_without_fee_coefficient()
    feeless = parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)

    commission = rig.client.calculate_commission(
        feeless,
        Quantity(1, feeless.size_precision),
        Price(Decimal("0.50"), feeless.price_precision),
        LiquiditySide.TAKER,
    )

    assert commission is None
    assert any(str(feeless.id) in reason for reason in rig.client.trading_refusals), (
        rig.client.trading_refusals
    )


@pytest.mark.asyncio
async def test_calculate_commission_prices_a_maker_fill_at_taker_and_refuses(
    tmp_path: Path,
) -> None:
    """Breezy is taker-only, so a MAKER fill is an event it did not intend.
    Raising would stop the node; the taker coefficient OVERSTATES the cost
    (the documented maker coefficient is a rebate), so it is the conservative
    figure -- and the instrument is latched as untradeable."""
    rig = _build_rig(tmp_path)

    commission = rig.client.calculate_commission(
        rig.instrument,
        Quantity(100, rig.instrument.size_precision),
        Price(Decimal("0.37"), rig.instrument.price_precision),
        LiquiditySide.MAKER,
    )

    assert commission == Money(Decimal("1.40"), USD)
    assert any("MAKER" in reason for reason in rig.client.trading_refusals), (
        rig.client.trading_refusals
    )


@pytest.mark.asyncio
async def test_calculate_commission_prices_a_sideless_fill_at_taker(
    tmp_path: Path,
) -> None:
    """`NO_LIQUIDITY_SIDE` is IN the base contract's stated domain
    (`execution/client.pyx:186`) and is REACHABLE: a cached marketable LIMIT
    order infers it (`live/reconciliation.py:468-478`), and a marketable limit
    is how a taker crosses a CLOB. Taker is the conservative reading."""
    rig = _build_rig(tmp_path)

    commission = rig.client.calculate_commission(
        rig.instrument,
        Quantity(100, rig.instrument.size_precision),
        Price(Decimal("0.37"), rig.instrument.price_precision),
        LiquiditySide.NO_LIQUIDITY_SIDE,
    )

    assert commission == Money(Decimal("1.40"), USD)


def _market_payload_without_fee_coefficient() -> dict[str, Any]:
    """A real captured market with its fee coefficient removed."""
    import copy
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[2]
    raw = root / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
    payload: dict[str, Any] = json.loads(
        (raw / "market_open_510636_by_slug.json").read_text(encoding="utf-8"),
    )
    payload = copy.deepcopy(payload)
    _strip_fee_coefficient(payload)
    return payload


def _strip_fee_coefficient(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("feeCoefficient", None)
        for value in node.values():
            _strip_fee_coefficient(value)
    elif isinstance(node, list):
        for value in node:
            _strip_fee_coefficient(value)


def rig_instrument() -> BinaryOption:
    return build_instrument()


# ---------------------------------------------------------------------------
# I1b -- `record_fill` is the FIRST action of the `KIND_ACCEPT_FILL` branch
# (LIVE_FILL_SCORING_CHAIN_2026-09-05). Fixtures below are schema-shaped from
# the SDK/OpenAPI snapshots (see `polymarket_us_exec_shapes.py`'s module
# docstring) -- NOT a recorded response: every authenticated smoke run to
# date recorded ``Connectivity verdict: FAIL``.
# ---------------------------------------------------------------------------


class _FakeOrderSender:
    """Records every POST; returns the queued response."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = VenueResponse(status=200, headers={}, body=b"{}")

    async def post_order(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> VenueResponse:
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        return self.response


class _FakeWriteSigner:
    def sign_headers(self, method: str, path: str, **_kwargs: object) -> list[tuple[str, str]]:
        return [("X-Test-Method", method), ("X-Test-Path", path)]


def _accept_fill_body(
    slug: str,
    *,
    order_id: str = "ord-i1b-1",
    last_px: str = "0.37",
    commission: str = "0.03",
) -> bytes:
    """A 200 create-order body classifying as `KIND_ACCEPT_FILL`, fully
    fee-reconciled: one fill-type execution, order-level `avgPx`/`cumQuantity`
    agreeing with it, no order-level commission total (so `fee_reconciled`
    follows the per-leg sum, I1a `_cumulative_fee_and_reconciliation`)."""
    order = build_order(slug)
    order["id"] = order_id
    order["quantity"] = 1
    order["cumQuantity"] = 1
    order["leavesQuantity"] = 0
    order["state"] = "ORDER_STATE_FILLED"
    order["price"] = {"value": last_px, "currency": "USD"}
    order["avgPx"] = {"value": last_px, "currency": "USD"}
    execution = build_execution(order)
    execution["lastShares"] = "1"
    execution["lastPx"] = {"value": last_px, "currency": "USD"}
    execution["commissionNotionalCollected"] = {"value": commission, "currency": "USD"}
    return json.dumps({"id": order_id, "executions": [execution]}).encode("utf-8")


def _unreconciled_fee_body(slug: str, *, order_id: str = "ord-i1b-2") -> bytes:
    """Same shape, but the order-level commission TOTAL contradicts the
    per-leg sum -- `fee_reconciled=False` (I1a)."""
    order = build_order(slug)
    order["id"] = order_id
    order["quantity"] = 1
    order["cumQuantity"] = 1
    order["leavesQuantity"] = 0
    order["state"] = "ORDER_STATE_FILLED"
    order["price"] = {"value": "0.37", "currency": "USD"}
    order["avgPx"] = {"value": "0.37", "currency": "USD"}
    order["commissionNotionalTotalCollected"] = {"value": "9.99", "currency": "USD"}
    execution = build_execution(order)
    execution["lastShares"] = "1"
    execution["lastPx"] = {"value": "0.37", "currency": "USD"}
    execution["commissionNotionalCollected"] = {"value": "0.03", "currency": "USD"}
    return json.dumps({"id": order_id, "executions": [execution]}).encode("utf-8")


def _zero_fill_body(*, order_id: str = "ord-i1b-zero") -> bytes:
    return json.dumps(
        {
            "id": order_id,
            "executions": [],
            "state": "ORDER_STATE_CANCELED",
            "cumQuantity": 0,
        },
    ).encode("utf-8")


def _reject_body() -> bytes:
    return json.dumps({"code": 3, "message": "invalid", "details": []}).encode("utf-8")


class _AcceptFillRig:
    """The client under test, wired all the way to a fake `post_order`."""

    def __init__(
        self,
        *,
        client: PolymarketUSExecutionClient,
        sender: _FakeOrderSender,
        order_events: list[Any],
        trace: list[str],
        instrument: Any,
        clock: LiveClock,
        submit_intent_latch: Any,
        store_path: Path,
        latch_cm: Any,
    ) -> None:
        self.client = client
        self.sender = sender
        self.order_events = order_events
        self.trace = trace
        self.instrument = instrument
        self.clock = clock
        self.submit_intent_latch = submit_intent_latch
        self.store_path = store_path
        # Kept alive for the rig's lifetime -- see `_ChainRig`'s identical
        # note in `test_polymarket_us_submit_order_chain.py`: dropping this
        # reference finalises the generator-CM via `GeneratorExit` and
        # silently releases the flock mid-test.
        self._latch_cm = latch_cm

    def limit_buy(self, *, price: str = "0.37") -> SubmitOrder:
        factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=self.clock)
        order = factory.limit(
            instrument_id=self.instrument.id,
            order_side=OrderSide.BUY,
            quantity=Quantity(1, self.instrument.size_precision),
            price=Price.from_str(price),
            time_in_force=TimeInForce.IOC,
        )
        return SubmitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            order=order,
            command_id=UUID4(),
            ts_init=TS_INIT,
        )


def _build_accept_fill_rig(
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
    sender: _FakeOrderSender | None = None,
) -> _AcceptFillRig:
    """The R-7 full stack: a real client, a real `SqliteStateStore`, a real
    submit-intent latch, and a fake `post_order` -- the same shape
    `test_polymarket_us_submit_order_chain.py`'s `_build_chain_rig` already
    proves reaches a POST. Rebuilt here (not imported) because that module is
    outside this increment's edit surface.

    Callers must request the `write_canonical_verified` fixture (imported
    above) themselves: this function does not flip
    `WRITE_CANONICAL_STRING_VERIFIED` itself, so this file adds no second
    `setattr` site for `_find_write_transport_canonical_setattr_sites`
    to find.
    """
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
        },
    )
    order_events: list[Any] = []
    trace: list[str] = []

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    def _on_exec_event(event: Any) -> None:
        order_events.append(event)
        trace.append(type(event).__name__)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)
    msgbus.register(endpoint="ExecEngine.process", handler=_on_exec_event)

    store_path = tmp_path / "exec_state.db"
    fake_sender = sender if sender is not None else _FakeOrderSender()
    enable_operator_gate(monkeypatch)
    issued_permit = issue_live_trading_permit(clock=clock)
    latch_cm = open_submit_intent_latch(SqliteStateStore(store_path), store_path)
    submit_intent_latch = latch_cm.__enter__()

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
        order_sender=fake_sender,
        write_signer=_FakeWriteSigner(),
        live_trading_permit=issued_permit,
        spend_ledger=DailySpendLedger(),
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
    )
    return _AcceptFillRig(
        client=client,
        sender=fake_sender,
        order_events=order_events,
        trace=trace,
        instrument=instrument,
        clock=clock,
        submit_intent_latch=submit_intent_latch,
        store_path=store_path,
        latch_cm=latch_cm,
    )


@contextmanager
def _accept_fill_caps() -> Iterator[None]:
    """The operator ceilings `DailySpendLedger.authorize_order_cost` reads,
    bound through the ONE whitelisted test seam (`operator_control_env.py`)
    for the duration of the submit call only."""
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        yield


def _reopened_fill_record(store_path: Path, venue_order_id: str) -> DurableFillRecord | None:
    with SqliteStateStore(store_path) as reopened:
        raw = reopened.get(f"{FILL_KEY_PREFIX}{venue_order_id}")
    if raw is None:
        return None
    return DurableFillRecord.from_bytes(raw)


# (a) ordering probe -- the store write happens BEFORE `true_up_booking`,
# `_retire` and the published `OrderFilled`.
@pytest.mark.asyncio
async def test_record_fill_is_written_before_true_up_booking_retire_and_order_filled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(status=200, headers={}, body=_accept_fill_body(slug))

    original_record_fill = rig.client.record_fill
    original_retire = rig.client._retire
    # `DailySpendLedger` is `__slots__`-only (no instance `__dict__`), so the
    # spy is installed on the CLASS, not the instance -- this rig's ledger is
    # the only live instance for the duration of this test.
    original_true_up = DailySpendLedger.true_up_booking

    def _spy_record_fill(record: DurableFillRecord) -> None:
        rig.trace.append("record_fill")
        original_record_fill(record)

    def _spy_true_up(ledger_self: Any, *args: Any, **kwargs: Any) -> Any:
        rig.trace.append("true_up_booking")
        return original_true_up(ledger_self, *args, **kwargs)

    def _spy_retire(*args: Any, **kwargs: Any) -> Any:
        rig.trace.append("_retire")
        return original_retire(*args, **kwargs)

    monkeypatch.setattr(rig.client, "record_fill", _spy_record_fill)
    monkeypatch.setattr(DailySpendLedger, "true_up_booking", _spy_true_up)
    monkeypatch.setattr(rig.client, "_retire", _spy_retire)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    assert rig.trace == [
        "record_fill",
        "true_up_booking",
        "_retire",
        "OrderSubmitted",
        "OrderFilled",
    ], rig.trace


# (b) the record decodes with the venue fee and the reconciled flag.
@pytest.mark.asyncio
async def test_the_durable_record_decodes_with_the_venue_fee_and_the_reconciled_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_accept_fill_body(slug, order_id="ord-i1b-decode", last_px="0.37", commission="0.03"),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    record = _reopened_fill_record(rig.store_path, "ord-i1b-decode")
    assert record is not None
    assert record.cumulative_qty == Decimal(1)
    assert record.cumulative_cost == Decimal("0.37")
    assert record.cumulative_fee == Decimal("0.03")
    assert record.fee_reconciled is True


# (b2) B0-c: the create-path record carries the venue's own tradeId and the
# ORIGINAL order size -- never the filled size (create-path size is always
# exactly 1, Units correction).
@pytest.mark.asyncio
async def test_an_accept_fill_persists_the_venue_trade_id_and_the_original_order_qty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_accept_fill_body(slug, order_id="ord-i1b-tradeid"),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    record = _reopened_fill_record(rig.store_path, "ord-i1b-tradeid")
    assert record is not None
    assert record.trade_id == "trd-902"  # `build_execution`'s default tradeId
    assert record.order_qty == Decimal(1)


# (c) FAILURE PATH -- `record_fill` raises.
@pytest.mark.asyncio
async def test_a_raising_record_fill_refuses_but_still_publishes_both_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_accept_fill_body(slug, order_id="ord-i1b-boom"),
    )

    def _boom(record: DurableFillRecord) -> None:
        raise RuntimeError("simulated durable write failure")

    monkeypatch.setattr(rig.client, "record_fill", _boom)

    with _accept_fill_caps():
        rig.client.start()  # drive the native FSM to RUNNING, as `_refuse` requires
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())  # must not raise
        # Asserted BEFORE `_disconnect`: the native FSM's own DISCONNECTING/
        # STOPPED transitions supersede DEGRADED, so this is the last point
        # the refusal's own state effect is still directly observable.
        assert rig.client.is_degraded is True
        await rig.client._disconnect()

    assert _reopened_fill_record(rig.store_path, "ord-i1b-boom") is None

    current = rig.submit_intent_latch.current()
    assert current is not None
    assert current.state is SubmitIntentState.OPEN, (
        "a failed evidence write must not retire the intent"
    )

    refusals = rig.client.trading_refusals
    assert refusals.count(client_module._FILL_WRITE_FAILED) == 1, refusals

    submitted = [e for e in rig.order_events if isinstance(e, OrderSubmitted)]
    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(submitted) == 1
    assert len(filled) == 1


# (d) `fee_reconciled=False` -- record still written, refusal latched, retire
# and publish proceed.
@pytest.mark.asyncio
async def test_an_unreconciled_fee_still_writes_and_retires_but_latches_a_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_unreconciled_fee_body(slug, order_id="ord-i1b-unreconciled"),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    record = _reopened_fill_record(rig.store_path, "ord-i1b-unreconciled")
    assert record is not None
    assert record.fee_reconciled is False

    assert rig.client.trading_refusals.count(client_module._FEE_UNRECONCILED) == 1

    current = rig.submit_intent_latch.current()
    assert current is not None
    assert current.state is SubmitIntentState.RETIRED, "the fill is real; retire must still proceed"

    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(filled) == 1


# (e) zero-fill and reject write no record.
@pytest.mark.asyncio
async def test_a_zero_fill_writes_no_durable_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_zero_fill_body(order_id="ord-i1b-zero"),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        assert rig.client.fill_records_for(rig.instrument.id) == ()
        await rig.client._disconnect()

    assert _reopened_fill_record(rig.store_path, "ord-i1b-zero") is None


@pytest.mark.asyncio
async def test_a_reject_writes_no_durable_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    sender.response = VenueResponse(status=400, headers={}, body=_reject_body())

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        assert rig.client.fill_records_for(rig.instrument.id) == ()
        await rig.client._disconnect()


# ---------------------------------------------------------------------------
# A1: the venue order id -> client order id map, written at the one point
# ALL FOUR create-order outcome kinds pass through.
# ---------------------------------------------------------------------------


def _ambiguous_with_id_body(order_id: str) -> bytes:
    """L-36: 200 + id + `executions == []` with no terminal state/cumQuantity
    -- falls through to `KIND_AMBIGUOUS` with `venue_order_id=order_id`."""
    return json.dumps({"id": order_id, "executions": []}).encode("utf-8")


@pytest.mark.asyncio
async def test_an_accept_fill_records_the_venue_id_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200, headers={}, body=_accept_fill_body(slug, order_id="ord-a1-accept"),
    )
    order = rig.limit_buy()

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(order)
        assert (
            rig.client.client_order_id_for(VenueOrderId("ord-a1-accept"))
            == order.order.client_order_id
        )
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_zero_fill_records_the_venue_id_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Rev 2 acceptance #1, load-bearing: `KIND_ZERO_FILL` `return`s BEFORE
    the old AMBIGUOUS-fallthrough anchor, so a written row here proves the
    call site is genuinely pre-dispatch, not a re-citation of a line number."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    sender.response = VenueResponse(
        status=200, headers={}, body=_zero_fill_body(order_id="ord-a1-zero"),
    )
    order = rig.limit_buy()

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(order)
        assert (
            rig.client.client_order_id_for(VenueOrderId("ord-a1-zero"))
            == order.order.client_order_id
        )
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_an_ambiguous_with_id_records_the_venue_id_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    sender.response = VenueResponse(
        status=200, headers={}, body=_ambiguous_with_id_body("ord-a1-ambiguous"),
    )
    order = rig.limit_buy()

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(order)
        assert (
            rig.client.client_order_id_for(VenueOrderId("ord-a1-ambiguous"))
            == order.order.client_order_id
        )
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_reject_records_no_venue_id_map_and_latches_no_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """(AM-4, CX-B1) CHARACTERISATION, not CHANGE: a REJECT carries
    `venue_order_id=None` (`submit_chain.py:800-819`), so it writes no map
    row and latches no refusal -- true at HEAD too, and this is the only
    guard on that shape (Rev 2's inverse acceptance clause was an error).
    MUTATION_RED_EVIDENCE (pair 2): removing the `if outcome.venue_order_id
    is not None:` guard on the A1 block, taken AFTER A1 lands, makes the
    refusal half of this assertion go RED -- see the commit body."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    sender.response = VenueResponse(status=400, headers={}, body=_reject_body())

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        assert len(rig.client.trading_refusals) == 0
        assert rig.client.is_degraded is False
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_venue_id_map_write_failure_refuses_and_still_dispatches_the_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """A-B2: a map-write failure refuses and FALLS THROUGH -- never a
    `return` -- so the ACCEPT_FILL dispatch (`record_fill`/retire/publish)
    still runs to completion."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200, headers={}, body=_accept_fill_body(slug, order_id="ord-a1-boom"),
    )

    def _boom(venue_order_id: VenueOrderId, client_order_id: ClientOrderId) -> None:
        raise RuntimeError("simulated venue-id map write failure")

    monkeypatch.setattr(rig.client, "record_venue_order_id", _boom)

    with _accept_fill_caps():
        rig.client.start()  # drive the native FSM to RUNNING, as `_refuse` requires
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())  # must not raise
        assert rig.client.is_degraded is True
        await rig.client._disconnect()

    refusals = rig.client.trading_refusals
    assert refusals.count(client_module._VENUE_ID_MAP_WRITE_FAILED) == 1, refusals
    assert _reopened_fill_record(rig.store_path, "ord-a1-boom") is not None
    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(filled) == 1


# (f) `to_bytes`/`from_bytes` round-trip with the new fields.
def test_durable_fill_record_round_trips_the_fee_and_reconciled_flag() -> None:
    record = DurableFillRecord(
        venue_order_id="V-ROUNDTRIP-1",
        client_order_id="O-19700101-000000-001-001-1",
        instrument_id="some-instrument",
        order_side="BUY",
        cumulative_qty=Decimal(4),
        cumulative_cost=Decimal("1.48"),
        cumulative_fee=Decimal("0.12"),
        fee_reconciled=False,
        ts_event=TS_INIT,
        venue_fee_raw="0.004",
    )

    raw = record.to_bytes()
    decoded = json.loads(raw)
    assert decoded["cumulativeFee"] == "0.12"
    assert decoded["feeReconciled"] is False
    assert decoded["venueFeeRaw"] == "0.004"
    # B0: two new optional-on-read keys, `None` here since this record does
    # not pass `trade_id`/`order_qty` -- the SET must still carry both.
    assert decoded["tradeId"] is None
    assert decoded["orderQty"] is None
    assert set(decoded) == {
        "venueOrderId",
        "clientOrderId",
        "instrumentId",
        "orderSide",
        "cumulativeQty",
        "cumulativeCost",
        "cumulativeFee",
        "feeReconciled",
        "tsEvent",
        "venueFeeRaw",
        "tradeId",
        "orderQty",
    }

    assert DurableFillRecord.from_bytes(raw) == record

    missing = DurableFillRecord.from_bytes(_raw_record())
    assert missing.venue_fee_raw is None
    assert missing.trade_id is None
    assert missing.order_qty is None


# (f2) B0: `trade_id`/`order_qty` round-trip on their own, non-`None`.
def test_a_durable_record_round_trips_the_trade_id_and_order_qty() -> None:
    record = DurableFillRecord(
        venue_order_id="V-ROUNDTRIP-2",
        client_order_id="O-19700101-000000-001-001-2",
        instrument_id="some-instrument",
        order_side="BUY",
        cumulative_qty=Decimal(4),
        cumulative_cost=Decimal("1.48"),
        cumulative_fee=Decimal("0.12"),
        fee_reconciled=True,
        ts_event=TS_INIT,
        trade_id="trd-902",
        order_qty=Decimal(1),
    )

    raw = record.to_bytes()
    decoded = json.loads(raw)
    assert decoded["tradeId"] == "trd-902"
    assert decoded["orderQty"] == "1"
    assert DurableFillRecord.from_bytes(raw) == record


# (f3) B0/S-M1: a legacy record (no `tradeId`/`orderQty` key at all) decodes
# both fields to `None` -- never inferred from `cumulative_qty`, never
# defaulted to `Decimal(1)`. This is the same shape as every record on disk
# before this change (functionally identical to the live store's
# pre-existing `.../fill/CEBPX0EVTTMX` record -- reading the live state
# store directly is out of scope for this test, so `_raw_record()`'s
# already-legacy shape, the same fixture `venue_fee_raw is None` uses two
# lines above, stands in for it). Reconstructing the `GET-<venue_order_id>`
# fallback from a `None` `trade_id` is a B1 consumer-side rule (Units,
# S-M1) -- BLOCKED-BY-R-1, not implemented by this change.
def test_a_legacy_record_without_a_trade_id_decodes_and_falls_back_to_the_get_form() -> None:
    legacy = DurableFillRecord.from_bytes(_raw_record())
    assert legacy.trade_id is None
    assert legacy.order_qty is None


@pytest.mark.parametrize("bad_order_qty", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_order_qty_is_refused(bad_order_qty: str) -> None:
    with pytest.raises(ExecutionReportMappingError, match="orderQty"):
        DurableFillRecord.from_bytes(_raw_record(orderQty=bad_order_qty))


def test_a_non_string_trade_id_is_refused() -> None:
    with pytest.raises(ExecutionReportMappingError, match="tradeId"):
        DurableFillRecord.from_bytes(_raw_record(tradeId=123))


# (g) `None` totals on an accept-fill outcome -- the same failure path as (c).
@pytest.mark.asyncio
async def test_none_order_level_totals_on_an_accept_fill_take_the_write_failure_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Should be impossible after I1a (`classify_create_order_outcome` always
    populates the totals together with a resolved `fill`), but pinned anyway:
    a `CreateOrderOutcome` that is somehow `KIND_ACCEPT_FILL` with no totals
    must refuse, never guess a zero."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_accept_fill_body(slug, order_id="ord-i1b-none-totals"),
    )

    original_classify = submit_chain.classify_create_order_outcome

    def _classify_with_none_totals(*args: Any, **kwargs: Any) -> Any:
        outcome = original_classify(*args, **kwargs)
        return dataclasses.replace(
            outcome,
            cumulative_qty=None,
            cumulative_cost=None,
            cumulative_fee=None,
        )

    monkeypatch.setattr(submit_chain, "classify_create_order_outcome", _classify_with_none_totals)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())  # must not raise
        await rig.client._disconnect()

    assert _reopened_fill_record(rig.store_path, "ord-i1b-none-totals") is None
    refusals = rig.client.trading_refusals
    assert refusals.count(client_module._FILL_WRITE_FAILED) == 1, refusals

    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(filled) == 1


# ---------------------------------------------------------------------------
# SP-2 I3 -- durable capture: `AmbiguousResolverContext` gains two
# trailing-optional fields, written by `_note_ambiguous_open`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_ambiguous_create_outcome_persists_the_body_key_tree_in_the_resolver_context(
    tmp_path: Path,
) -> None:
    """I3: `outcome.detail` / `outcome.fill_parse_error` -- both already
    capped, names-only, no value -- are persisted onto the durable
    resolver context, so a drifted key survives past the log line and
    feeds R-6."""
    store_path = tmp_path / "exec_state.db"
    rig = _build_rig(tmp_path, store_opener=lambda: SqliteStateStore(store_path))
    await rig.client._connect()

    order = rig.submit_command().order
    booking = SimpleNamespace(booking_id=1)
    create_detail = (
        "status=200 body_kind=executions-present rpc_code=none body_len=1 "
        "state=absent cum=absent tree={'driftedTopLevelKey'}"
    )
    fill_parse_error = (
        "fill report mapped but no filled cost is derivable: "
        "order.avgPx=absent order.cumQuantity=absent lastPx=absent "
        "lastShares=absent; full body key tree: {'driftedLegKey'}"
    )

    rig.client._note_ambiguous_open(
        intent_id="intent-i3",
        venue_order_id="venue-i3",
        order=order,
        notional_usd=Decimal("1.00"),
        booking=booking,
        now_ns=TS_INIT,
        create_detail=create_detail,
        fill_parse_error=fill_parse_error,
    )

    await rig.client._disconnect()

    with SqliteStateStore(store_path) as reopened:
        raw = reopened.get(f"{RESOLVER_CONTEXT_KEY_PREFIX}intent-i3")

    assert raw is not None
    context = AmbiguousResolverContext.from_bytes(raw)
    assert context.create_detail == create_detail
    assert context.fill_parse_error == fill_parse_error
    assert "driftedTopLevelKey" in (context.create_detail or "")
    assert "driftedLegKey" in (context.fill_parse_error or "")


def test_a_resolver_context_written_before_this_change_still_decodes() -> None:
    """AC-13 / AR-N6: a resolver-context blob written before SP-2 (no
    `createDetail`/`fillParseError` keys at all) still decodes, both
    fields `None` -- trailing-optional, no schema version, no migration.
    A NEW row with no detail explicitly serialises `"createDetail": null`
    / `"fillParseError": null` and decodes back to `None`."""
    old_blob = json.dumps(
        {
            "intentId": "intent-old",
            "venueOrderId": "venue-old",
            "instrumentId": "instrument-old",
            "clientOrderId": "client-old",
            "strategyId": "strategy-old",
            "notionalUsd": "1.00",
            "bookingId": 7,
            "createdNs": TS_INIT,
        },
        sort_keys=True,
    ).encode("utf-8")

    old_context = AmbiguousResolverContext.from_bytes(old_blob)
    assert old_context.create_detail is None
    assert old_context.fill_parse_error is None

    new_context = AmbiguousResolverContext(
        intent_id="intent-new",
        venue_order_id="venue-new",
        instrument_id="instrument-new",
        client_order_id="client-new",
        strategy_id="strategy-new",
        notional_usd=Decimal("2.00"),
        booking_id=8,
        created_ns=TS_INIT,
    )
    new_bytes = new_context.to_bytes()
    decoded = json.loads(new_bytes)
    assert decoded["createDetail"] is None
    assert decoded["fillParseError"] is None

    round_tripped = AmbiguousResolverContext.from_bytes(new_bytes)
    assert round_tripped.create_detail is None
    assert round_tripped.fill_parse_error is None


# ---------------------------------------------------------------------------
# S0 (plan rev 3, R3-1) -- boot-seed the ledger and permit budget from
# today's durable fills, between `_reconcile_submit_intent` and
# `_refresh_startup_position_evidence`.
# ---------------------------------------------------------------------------


def _issued_permit(clock: LiveClock) -> Any:
    return issue_live_trading_permit(clock=clock)


def _record_at(rig: _Rig, *, ts_event: int, **kwargs: Any) -> DurableFillRecord:
    """A durable fill record with an EXPLICIT ``ts_event``, since ``_record``
    defaults to the fixed ``TS_INIT`` constant, never the wall clock -- the
    UTC-day seed needs a record whose day is deterministically "today" or
    "not today" relative to the test's own ``now_ns``."""
    return dataclasses.replace(_record(rig, **kwargs), ts_event=ts_event)


@pytest.mark.asyncio
async def test_a_relaunch_mid_day_does_not_re_grant_the_spent_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-day process restart must not forget what today already spent."""
    enable_operator_gate(monkeypatch)
    store_path = tmp_path / "exec_state.db"

    boot1 = _build_rig(tmp_path, store_path=store_path, spend_ledger=DailySpendLedger())
    await boot1.client._connect()
    now_ns = boot1.clock.timestamp_ns()
    boot1.client.record_fill(
        _record_at(boot1, ts_event=now_ns, order="V-SEED-1", qty=Decimal(3), cost=Decimal("3.00")),
    )
    await boot1.client._disconnect()

    ledger2 = DailySpendLedger()
    boot2 = _build_rig(tmp_path, store_path=store_path, spend_ledger=ledger2)
    await boot2.client._connect()
    reauthorize_ns = boot2.clock.timestamp_ns()

    assert ledger2.spent_today_usd(now_ns=reauthorize_ns) == Decimal("3.00")
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "3.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "3.00"),
        pytest.raises(LiveTradingPermissionError, match="daily budget"),
    ):
        ledger2.authorize_order_cost(
            price_usd=Decimal("0.01"), quantity=Decimal(1), now_ns=reauthorize_ns,
        )
    await boot2.client._disconnect()


@pytest.mark.asyncio
async def test_the_seed_sums_only_todays_utc_fills(tmp_path: Path) -> None:
    store_path = tmp_path / "exec_state.db"
    boot1 = _build_rig(tmp_path, store_path=store_path, spend_ledger=DailySpendLedger())
    await boot1.client._connect()
    now_ns = boot1.clock.timestamp_ns()
    yesterday_ns = now_ns - 2 * 24 * 60 * 60 * 1_000_000_000
    boot1.client.record_fill(
        _record_at(boot1, ts_event=now_ns, order="V-TODAY", qty=Decimal(1), cost=Decimal("2.00")),
    )
    boot1.client.record_fill(
        _record_at(
            boot1, ts_event=yesterday_ns, order="V-YESTERDAY", qty=Decimal(1), cost=Decimal("9.00"),
        ),
    )
    await boot1.client._disconnect()

    ledger2 = DailySpendLedger()
    boot2 = _build_rig(tmp_path, store_path=store_path, spend_ledger=ledger2)
    await boot2.client._connect()

    assert ledger2.spent_today_usd(now_ns=now_ns) == Decimal("2.00")
    await boot2.client._disconnect()


@pytest.mark.asyncio
async def test_a_corrupt_fill_index_for_one_instrument_fails_the_seed_closed_and_never_arms(
    tmp_path: Path,
) -> None:
    """A SECOND instrument's corrupt index -- not a wholesale walk failure --
    must still refuse to arm the whole client (R3-1 security note)."""
    second_instrument = build_second_instrument()
    store_path = tmp_path / "exec_state.db"

    with SqliteStateStore(store_path) as store:
        store.set(f"{FILL_INDEX_KEY_PREFIX}{second_instrument.id}", b"{not json at all")

    def _opener() -> SqliteStateStore:
        return SqliteStateStore(store_path)

    loop = asyncio.get_running_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    instrument = build_instrument()
    cache.add_instrument(instrument)
    cache.add_instrument(second_instrument)
    provider = InstrumentProvider()
    provider.add(instrument)
    provider.add(second_instrument)
    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: {"positions": {}, "eof": True},
        },
    )
    msgbus.register(endpoint="Portfolio.update_account", handler=lambda state: None)
    msgbus.register(endpoint="ExecEngine.process", handler=lambda event: None)
    client = PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=read,
        state_store_opener=_opener,
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=1.0,
        account_registration_timeout_s=1.0,
        spend_ledger=DailySpendLedger(),
    )

    client.start()
    client.connect()
    tasks = list(client._tasks)
    done, pending = await asyncio.wait(tasks, timeout=5.0)
    assert pending == set()
    assert done == set(tasks)

    assert client.is_connected is False
    fault = fatal_exec_fault()
    assert fault is not None
    assert "index" in fault.reason


@pytest.mark.asyncio
async def test_the_seed_never_reads_an_operator_control_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither operator-reserved-control reader is ever called by the seed --
    live, not just statically: both are patched to raise, and a normal
    two-boot relaunch (which DOES seed a nonzero figure) must still connect
    cleanly with the raise never firing."""
    import breezy.adapters.polymarket_us.operator_controls as operator_controls_module

    def _boom() -> Decimal:
        raise AssertionError("the boot-time seed must never read an operator control value")

    monkeypatch.setattr(
        operator_controls_module, "operator_max_daily_budget_usd", _boom,
    )
    monkeypatch.setattr(
        operator_controls_module, "operator_max_position_cost_usd", _boom,
    )

    store_path = tmp_path / "exec_state.db"
    boot1 = _build_rig(tmp_path, store_path=store_path, spend_ledger=DailySpendLedger())
    await boot1.client._connect()
    now_ns = boot1.clock.timestamp_ns()
    boot1.client.record_fill(
        _record_at(boot1, ts_event=now_ns, order="V-REDACT", qty=Decimal(1), cost=Decimal("7.00")),
    )
    await boot1.client._disconnect()

    ledger2 = DailySpendLedger()
    boot2 = _build_rig(tmp_path, store_path=store_path, spend_ledger=ledger2)
    await boot2.client._connect()  # would raise via `_boom` if the seed read a control
    await boot2.client._disconnect()

    assert ledger2.spent_today_usd(now_ns=now_ns) == Decimal("7.00")


def test_the_seed_log_line_names_only_the_count_and_the_day() -> None:
    """Static proof the INFO line carries no money-shaped literal: a live
    log capture is unreliable here (`self._log` is Nautilus's Rust-backed
    logger, not interceptable through `caplog`/`capsys`/`capfd`), so this
    parses the method's own source instead -- the same AST-based technique
    `test_operator_control_assignment_scan.py` already uses for its refusal
    messages."""
    import textwrap

    source = inspect.getsource(PolymarketUSExecutionClient._seed_spend_from_durable_fills)
    tree = ast.parse(textwrap.dedent(source))
    log_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "info"
    ]
    assert log_calls, "expected at least one `self._log.info(...)` call"
    for call in log_calls:
        for arg in call.args:
            formatted = ast.unparse(arg)
            assert "cumulative_cost" not in formatted
            assert "total" not in formatted
            assert "spent" not in formatted.lower()


@pytest.mark.asyncio
async def test_the_permit_session_ceiling_is_seeded_from_the_same_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_operator_gate(monkeypatch, session_notional="12.00", order_count="10")
    store_path = tmp_path / "exec_state.db"

    boot1 = _build_rig(tmp_path, store_path=store_path, spend_ledger=DailySpendLedger())
    await boot1.client._connect()
    now_ns = boot1.clock.timestamp_ns()
    boot1.client.record_fill(
        _record_at(
            boot1, ts_event=now_ns, order="V-PERMIT-SEED", qty=Decimal(1), cost=Decimal("4.00"),
        ),
    )
    await boot1.client._disconnect()

    permit = _issued_permit(LiveClock())
    boot2 = _build_rig(
        tmp_path,
        store_path=store_path,
        spend_ledger=DailySpendLedger(),
        live_trading_permit=permit,
    )
    await boot2.client._connect()

    assert live_trading_budget_remaining(permit) == (Decimal("8.00"), 10)
    await boot2.client._disconnect()


@pytest.mark.asyncio
async def test_a_second_connect_in_the_same_process_is_idempotent(tmp_path: Path) -> None:
    ledger = DailySpendLedger()
    rig = _build_rig(tmp_path, spend_ledger=ledger)
    await rig.client._connect()
    now_ns = rig.clock.timestamp_ns()
    rig.client.record_fill(
        _record_at(
            rig, ts_event=now_ns, order="V-IDEMPOTENT", qty=Decimal(1), cost=Decimal("3.00"),
        ),
    )

    await rig.client._connect()
    assert ledger.spent_today_usd(now_ns=now_ns) == Decimal("3.00")

    await rig.client._connect()
    assert ledger.spent_today_usd(now_ns=now_ns) == Decimal("3.00")

    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_the_seed_runs_after_intent_reconciliation_and_before_position_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    trace: list[str] = []

    original_reconcile = rig.client._reconcile_submit_intent
    original_seed = rig.client._seed_spend_from_durable_fills
    original_evidence = rig.client._refresh_startup_position_evidence

    def _spy_reconcile() -> Any:
        trace.append("_reconcile_submit_intent")
        return original_reconcile()

    def _spy_seed() -> Any:
        trace.append("_seed_spend_from_durable_fills")
        return original_seed()

    async def _spy_evidence() -> Any:
        trace.append("_refresh_startup_position_evidence")
        return await original_evidence()

    monkeypatch.setattr(rig.client, "_reconcile_submit_intent", _spy_reconcile)
    monkeypatch.setattr(rig.client, "_seed_spend_from_durable_fills", _spy_seed)
    monkeypatch.setattr(rig.client, "_refresh_startup_position_evidence", _spy_evidence)

    await rig.client._connect()

    assert trace == [
        "_reconcile_submit_intent",
        "_seed_spend_from_durable_fills",
        "_refresh_startup_position_evidence",
    ], trace
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# S3 item 3 (plan 2026-09-14): a resolver-path (`_resolve_accept_fill`) fill
# is stamped with the RESOLVER's own discovery time, never a venue execution
# time -- so a fill discovered after UTC midnight seeds the DISCOVERY day.
# ---------------------------------------------------------------------------


class _FakeResolverAcceptFillReport:
    """Duck-typed stand-in for `_resolve_accept_fill`'s `report` argument.

    `filled_qty`/`quantity` are REAL `Quantity` instances (unlike the
    lighter duck-type in `test_current_rung_hold_ambiguous_resolver.py`):
    this test's intent is genuinely OPEN, so `_resolve_accept_fill` runs all
    the way through to `generate_order_filled`, which requires a real
    `Quantity` for `last_qty`.
    """

    avg_px = Decimal("0.37")
    filled_qty = Quantity(1, 0)
    quantity = Quantity(1, 0)


@pytest.mark.asyncio
async def test_a_resolver_fill_discovered_after_midnight_seeds_the_discovery_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The intent is ARMED (created) at 23:50 UTC on day D -- standing in
    for a fill that happened on the venue before midnight -- but the
    resolver's own GET only discovers and resolves it at 00:10 UTC on day
    D+1. The durable record's `ts_event` must be the DISCOVERY time (D+1),
    never the creation time (D): `_resolve_accept_fill` has no venue
    execution timestamp to fall back on at all."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-s3-midnight"
    sender.response = VenueResponse(status=200, headers={}, body=_ambiguous_with_id_body(order_id))

    day_d_ns = 1_767_657_000_000_000_000  # 2026-01-05T23:50:00Z
    day_d_plus_1_ns = 1_767_658_200_000_000_000  # 2026-01-06T00:10:00Z -- +20 min

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())

        assert rig.client._latch is not None
        current = rig.client._latch.current_open()
        assert current is not None, "the with-id AMBIGUOUS outcome must leave OPEN"

        instrument = rig.instrument
        context = AmbiguousResolverContext(
            intent_id=current.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id="O-does-not-matter",
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=day_d_ns,
        )
        rig.client._resolved_by_get_ts_ns[current.intent_id] = day_d_plus_1_ns
        # Simulate a restart re-entry (`_ambiguous_bookings` is process-local
        # only and empty after a restart, mirroring
        # `test_a_resolver_accept_fill_with_no_same_process_booking_still_
        # records_the_venue_id_map`): this sidesteps `DailySpendLedger.
        # true_up_booking`'s own same-UTC-day guard, which is orthogonal to
        # what this test pins (the durable record's `ts_event`).
        rig.client._ambiguous_bookings.pop(current.intent_id, None)

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, day_d_plus_1_ns,
        )

        await rig.client._disconnect()

    records = _reopened_fill_record(rig.store_path, order_id)
    assert records is not None
    assert records.ts_event == day_d_plus_1_ns
    assert utc_day_for_ns(records.ts_event) == utc_day_for_ns(day_d_plus_1_ns)
    assert utc_day_for_ns(records.ts_event) != utc_day_for_ns(day_d_ns), (
        "a resolver-path fill discovered after midnight must seed the "
        "DISCOVERY day, never the (unknown) day the fill actually happened"
    )
