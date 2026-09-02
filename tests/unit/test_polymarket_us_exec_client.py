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
import inspect
import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.factories import OrderFactory
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
from nautilus_trader.model.events import AccountState, OrderDenied
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
from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    VENUE_ORDER_ID_KEY_PREFIX,
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
from breezy.adapters.polymarket_us.parsing import FEE_COEFFICIENT_KEY, parse_binary_option
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.unit.polymarket_us_exec_shapes import (
    TS_EVENT_TEXT,
    build_instrument,
    build_position,
    build_second_instrument,
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
    ) -> None:
        self.client = client
        self.cache = cache
        self.msgbus = msgbus
        self.instrument = instrument
        self.read = read
        self.account_states = account_states
        self.order_events = order_events

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

    opener = store_opener or (lambda: SqliteStateStore(tmp_path / "exec_state.db"))
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
    )
    return _Rig(
        client=client,
        cache=cache,
        msgbus=msgbus,
        instrument=instrument,
        read=read,
        account_states=account_states,
        order_events=order_events,
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
) -> DurableFillRecord:
    """One cumulative record for one venue order."""
    return DurableFillRecord(
        venue_order_id=order,
        client_order_id="O-19700101-000000-001-001-1",
        instrument_id=str(rig.instrument.id),
        order_side=side,
        cumulative_qty=qty,
        cumulative_cost=cost,
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


def test_refuse_producer_count_stays_pinned_at_twenty_five() -> None:
    """PIN: R-6.5a adds no new `self._refuse(...)` call site.

    D3 changes the STORE's element type and one caller's keyword arguments;
    it neither adds nor removes a producer. The authoritative, triaged
    inventory is `tests/unit/test_exec_refusal_health_surface.py::
    REFUSAL_PRODUCERS`; this is the cheap local pin that catches a moved
    count without importing that module's internals.
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
    assert count == 25


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


def _raw_record(*, cumulative_qty: str = "4", cumulative_cost: str = "0.37") -> bytes:
    return json.dumps(
        {
            "venueOrderId": "V-1",
            "clientOrderId": "O-19700101-000000-001-001-1",
            "instrumentId": "some-instrument",
            "orderSide": "BUY",
            "cumulativeQty": cumulative_qty,
            "cumulativeCost": cumulative_cost,
            "tsEvent": TS_INIT,
        },
    ).encode("utf-8")


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
