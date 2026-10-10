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
from breezy.adapters.polymarket_us.account_activity import PORTFOLIO_ACTIVITIES_PATH
from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError, PolymarketUSError
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import (
    BUDGET_EXHAUSTED_KEY_PREFIX,
    FILL_BY_FINGERPRINT_KEY_PREFIX,
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
    OPEN_ORDERS_PATH,
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
from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    parse_binary_option,
    parse_binary_option_pair,
)
from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermissionError,
    issue_live_trading_permit,
    live_trading_budget_remaining,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.persistence.exit_tags import (
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)
from breezy.persistence.family_manifest import FamilyManifest
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntentState,
    open_submit_intent_latch,
)
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import (
    RAW,
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

_ZERO_SHA256: Final[str] = "0" * 64


def _family_manifest(
    *, family_id: str, exit_rule: str | None, no_leg_exit: bool = False,
) -> FamilyManifest:
    """INC-E2c: a manifest built directly (never `load_family_manifest`,
    which reads a real file) -- only `family_id`/`exit_rule`/`no_leg_exit`
    vary across the tests below; every other field is a well-formed
    placeholder."""
    return FamilyManifest(
        family_id=family_id,
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="current_rung_hold/trial/",
        d0_climate_day="2026-09-01",
        boundary_artefact_path=Path("deploy/families/placeholder.json"),
        boundary_inputs_sha256=_ZERO_SHA256,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("KSFO",),
        status="REGISTERED",
        manifest_sha256=_ZERO_SHA256,
        exit_rule=exit_rule,
        no_leg_exit=no_leg_exit,
    )


#: The LIVE configuration (module docstring of `persistence/exit_gate.py`):
#: `pm_us_crh_cont` is not `_EXIT_RULE_REGISTERED_FAMILIES`-registered AND
#: declares no `exit_rule` -- the gate is closed either way.
LIVE_UNARMED_MANIFEST: Final[FamilyManifest] = _family_manifest(
    family_id="pm_us_crh_cont", exit_rule=None,
)

#: The TEST-ONLY armed configuration: the one family
#: `persistence/exit_gate.py._EXIT_RULE_REGISTERED_FAMILIES` names, with a
#: manifest that also declares `exit_rule` -- `family_declares_exit_rule`
#: gates `True`. Deliberately does NOT declare `no_leg_exit` (FU-1d S2): the
#: NO-exit tests below that use THIS manifest exercise the new refusal.
ARMED_EXIT_MANIFEST: Final[FamilyManifest] = _family_manifest(
    family_id="pm_us_crh_exit_v4", exit_rule="R_THREAT",
)

#: FU-1d S2: the SAME armed family, additionally declaring `no_leg_exit` --
#: the fixture every NO-exit test that must actually MAP (not refuse) uses.
ARMED_NO_LEG_EXIT_MANIFEST: Final[FamilyManifest] = _family_manifest(
    family_id="pm_us_crh_exit_v4", exit_rule="R_THREAT", no_leg_exit=True,
)

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

    async def __call__(
        self, path: str, query: Mapping[str, object] | None = None
    ) -> Mapping[str, Any]:
        # EDGE-2 slice D (AC10): `query` is accepted but not recorded here --
        # the resolver's own cursor-forwarding tests
        # (`test_current_rung_hold_ambiguous_resolver.py`) replace
        # `_private_read` with a purpose-built local fake instead, so this
        # stub stays a byte-identical drop-in for the widened `PrivateRead`
        # protocol without dead instrumentation.
        del query
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
            # §4.3 (RESTING_BID_HUNT Rev 2): the boot's open-order enumeration
            # -- EMPTY by default, the "nothing rests" book every existing
            # `_connect` test assumes.
            OPEN_ORDERS_PATH: {"orders": []},
            # EDGE-2 slice D (AC4(c)): the resolver's activities trade-join
            # read -- EOF-complete with no trade rows by default, the
            # "nothing has traded" book every existing zero-fill/fill test
            # assumes unless it overrides this key.
            PORTFOLIO_ACTIVITIES_PATH: {"activities": [], "eof": True},
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


def test_private_read_call_takes_a_path_and_an_optional_query() -> None:
    """PIN, updated by EDGE-2 slice D (AC10, ruling b): the GET-only
    guarantee stays -- no verb but GET is ever expressible on this protocol
    -- but `query` is now an explicit, OPTIONAL second parameter, defaulted
    to `None` so every existing single-argument call site is unaffected.
    D1/D2/D3 touch the refusal store and the closure's body, never this
    signature; slice D is the one deliberate, reviewed exception (plan
    docs/plans/backlog/EDGE_2026-09-27/
    EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md, AC10)."""
    signature = inspect.signature(PrivateRead.__call__)
    params = list(signature.parameters)
    assert params == ["self", "path", "query"]
    assert signature.parameters["query"].default is None


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
    `_resolve_accept_fill` and `_resolve_terminal_zero`). Widened AGAIN
    old(33) -> new(34) by the position-shape ruling
    (`docs/evidence/RULING_no_side_position_shape_2026-09-16.md`):
    `_map_position` gained one new fail-closed refusal for a NO-leg
    holding whose NO instrument is not loaded. Widened AGAIN old(34) ->
    new(35) by EDGE-2 plan r3 (AC6b): `_resolve_accept_fill` gained a
    third `self._refuse(_RESOLVER_FILL_UNBUDGETED)` site, the cross-process
    unbudgeted-fill latch. Never relaxed, only widened (L-12).

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
    assert count == 35


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


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"positions": None},
        {"positions": ["not", "a", "dict"]},
        {"positions": {}, "eof": True},
        {"positions": {}, "eof": False},
        {"positions": {}},
        {"positions": {"some-slug": {"netPosition": "1"}}, "eof": True},
    ],
    ids=[
        "absent-key",
        "explicit-none",
        "non-dict-list",
        "empty-eof-true",
        "empty-eof-false",
        "empty-no-eof",
        "one-slug",
    ],
)
def test_declared_positions_public_alias_agrees_with_the_private_staticmethod(
    payload: dict[str, Any],
) -> None:
    """AUD-02b P3(i): `declared_positions` (public) is a pure delegation to
    `_declared_positions` (private) -- same return, or the SAME exception
    type, on every one of the existing foreign/empty/non-eof/terminal
    payload shapes above. The six in-class call sites and the existing
    private-name tests stay untouched; only a build-side caller outside this
    class (`breezy.strategy.current_rung_hold.set_family_halt_cli`) is meant
    to reach the public name."""
    try:
        private_result: Any = PolymarketUSExecutionClient._declared_positions(payload)
    except ExecutionReportMappingError as private_exc:
        with pytest.raises(ExecutionReportMappingError) as public_exc_info:
            PolymarketUSExecutionClient.declared_positions(payload)
        assert str(public_exc_info.value) == str(private_exc)
        return
    assert PolymarketUSExecutionClient.declared_positions(payload) == private_result


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
# NO-leg position mapping -- position-shape ruling
# (`docs/evidence/RULING_no_side_position_shape_2026-09-16.md`,
# `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` Appendix A.1). A NO
# holding is a LONG on the NO-leg instrument, never a SHORT on the YES one.
# ---------------------------------------------------------------------------


def _no_side_position(slug: str, *, qty: str = "1", cost: str = "0.09") -> dict[str, Any]:
    """A ``UserPosition`` shaped like the measured NO holding (Appendix A.1):
    ``outcome='No'``, negative ``netPosition``, ``qtyBought=0``/``qtySold=1``
    -- the venue represents a NO buy as a sell of the YES side."""
    return {
        **build_position(slug),
        "netPosition": f"-{qty}",
        "qtyBought": "0",
        "qtySold": qty,
        "cost": {"value": cost, "currency": "USD"},
        "qtyAvailable": f"-{qty}",
        "marketMetadata": {"slug": slug, "outcome": "No"},
    }


@pytest.mark.asyncio
async def test_a_yes_holding_with_an_explicit_outcome_is_long_on_the_yes_instrument(
    tmp_path: Path,
) -> None:
    """L-44: an explicit ``outcome='Yes'`` maps the same way an absent one
    already did -- LONG 1 on the YES instrument, priced from Breezy's own
    durable fill record (0.12, per the measured YES holding)."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    slug = _slug(rig.instrument)
    rig.client.record_fill(_record(rig, qty=Decimal(1), cost=Decimal("0.12")))
    yes_position = {
        **build_position(slug),
        "netPosition": "1",
        "qtyBought": "1",
        "qtySold": "0",
        "marketMetadata": {"slug": slug, "outcome": "Yes"},
    }
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {slug: yes_position},
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    reports = mass_status.position_reports[rig.instrument.id]
    assert len(reports) == 1
    assert reports[0].position_side == PositionSide.LONG
    assert reports[0].quantity == Quantity(1, rig.instrument.size_precision)
    assert reports[0].avg_px_open == Decimal("0.12")
    assert rig.client.trading_refusals == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_no_holding_is_long_on_the_no_leg_instrument_in_a_mixed_payload(
    tmp_path: Path,
) -> None:
    """L-44: the NO holding measured 2026-09-16 -- ``outcome='No'``,
    ``netPosition='-1'``, ``qtyBought=0``, ``qtySold=1`` -- maps to LONG 1 on
    the ``^no`` instrument, priced 0.09 from Breezy's own durable fill
    record (never complemented: the venue's ``avgPx``/``cost`` are already
    NO-denominated). ``qtySold=1`` is accepted, not refused as an unknown or
    contradictory shape.

    Mixed with an ordinary YES holding in a SECOND, unrelated market in the
    SAME boot payload (Appendix A.1's "mixed YES+NO payload" case), and
    asserts the NO leg is never attributed to its own market's YES
    instrument -- the sibling-leg false positive this ruling exists to
    close.
    """
    rig = _build_rig(tmp_path)
    no_instrument = _no_leg_instrument()
    second_instrument = build_second_instrument()
    rig.client._instrument_provider.add(no_instrument)
    rig.cache.add_instrument(no_instrument)
    rig.client._instrument_provider.add(second_instrument)
    rig.cache.add_instrument(second_instrument)
    await rig.client._connect()

    no_slug = _slug(rig.instrument)
    second_slug = _slug(second_instrument)
    no_record = DurableFillRecord(
        venue_order_id="V-NO-1",
        client_order_id="O-19700101-000000-001-001-1",
        instrument_id=str(no_instrument.id),
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.09"),
        cumulative_fee=Decimal("0.00"),
        fee_reconciled=True,
        ts_event=TS_INIT,
    )
    rig.client.record_fill(no_record)
    second_record = DurableFillRecord(
        venue_order_id="V-SECOND-1",
        client_order_id="O-19700101-000000-001-001-1",
        instrument_id=str(second_instrument.id),
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.60"),
        cumulative_fee=Decimal("0.00"),
        fee_reconciled=True,
        ts_event=TS_INIT,
    )
    rig.client.record_fill(second_record)
    second_position = {
        **build_position(second_slug),
        "netPosition": "1",
        "qtyBought": "1",
        "qtySold": "0",
    }
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {
            no_slug: _no_side_position(no_slug),
            second_slug: second_position,
        },
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    assert rig.instrument.id not in mass_status.position_reports, (
        "a NO holding must never be attributed to its market's YES instrument"
    )
    no_reports = mass_status.position_reports[no_instrument.id]
    assert len(no_reports) == 1
    assert no_reports[0].position_side == PositionSide.LONG
    assert no_reports[0].quantity == Quantity(1, no_instrument.size_precision)
    assert no_reports[0].avg_px_open == Decimal("0.09")

    yes_reports = mass_status.position_reports[second_instrument.id]
    assert len(yes_reports) == 1
    assert yes_reports[0].position_side == PositionSide.LONG

    assert rig.client.trading_refusals == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_no_holding_with_no_no_leg_instrument_loaded_is_refused(
    tmp_path: Path,
) -> None:
    """The YES instrument alone is not enough to map a NO holding: without
    the NO-leg instrument loaded the exposure is real but unattributable,
    so it is refused rather than silently dropped or mis-mapped onto YES."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    slug = _slug(rig.instrument)
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {slug: _no_side_position(slug)},
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert mass_status.position_reports == {}
    assert any(
        "NO-leg instrument" in reason and "no NO-leg instrument is loaded" in reason
        for reason in rig.client.trading_refusals
    ), rig.client.trading_refusals
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_contradictory_outcome_and_sign_is_refused_end_to_end(
    tmp_path: Path,
) -> None:
    """``outcome='No'`` with a positive ``netPosition`` is a venue
    contradiction, refused all the way through ``_map_position`` -- never
    guessed toward either leg."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    slug = _slug(rig.instrument)
    contradictory = {
        **build_position(slug),
        "netPosition": "1",
        "marketMetadata": {"slug": slug, "outcome": "No"},
    }
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {slug: contradictory},
        "eof": True,
    }

    mass_status = await rig.client.generate_mass_status()

    assert mass_status is not None
    assert mass_status.position_reports == {}
    assert any(
        "could not be mapped" in reason and "contradiction" in reason
        for reason in rig.client.trading_refusals
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

    def limit_sell(self, *, price: str = "0.37") -> SubmitOrder:
        """An UNTAGGED SELL-side order -- a naked short, never an exit
        (INC-E2c: an exit order carries the ``exit_rule=`` tag,
        :meth:`limit_exit_sell`). `submit_chain.unmappable_order_reason`
        refuses every non-BUY, untagged order, byte-unchanged. Callers that
        need this to reach `_submit_order`'s ACCEPT_FILL branch must
        monkeypatch that ONE gate off for the duration of the test, to
        isolate the (in-scope) fill-accounting fix from the (out-of-scope,
        unmodified) mappability gate."""
        factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=self.clock)
        order = factory.limit(
            instrument_id=self.instrument.id,
            order_side=OrderSide.SELL,
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

    def limit_exit_sell(
        self,
        *,
        price: str = "0.37",
        rule: str = "R_THREAT",
        family_id: str = "pm_us_crh_exit_v4",
        position_id: str = "pos-exit-1",
        client_order_id_value: str = "O-EXIT-1",
        instrument: Any | None = None,
    ) -> SubmitOrder:
        """INC-E2c: a properly exit-tagged SELL, the exact shape
        `exit_wiring.submit_exit` constructs (four ``exit_*=`` tags, plus
        ``client_order_id`` pinned to the SAME value the tag carries).
        ``instrument`` defaults to the rig's own (YES-leg) instrument; a
        caller proving the NO leg passes the NO-leg instrument explicitly
        (and must register it on the rig's cache itself first)."""
        target_instrument = self.instrument if instrument is None else instrument
        factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=self.clock)
        order = factory.limit(
            instrument_id=target_instrument.id,
            order_side=OrderSide.SELL,
            quantity=Quantity(1, target_instrument.size_precision),
            price=Price.from_str(price),
            time_in_force=TimeInForce.IOC,
            tags=[
                f"{EXIT_RULE_TAG_PREFIX}{rule}",
                f"{EXIT_POSITION_TAG_PREFIX}{position_id}",
                f"{EXIT_FAMILY_TAG_PREFIX}{family_id}",
                f"{EXIT_CLIENT_ORDER_ID_TAG_PREFIX}{client_order_id_value}",
            ],
            client_order_id=ClientOrderId(client_order_id_value),
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
    exit_manifest: FamilyManifest | None = None,
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
            OPEN_ORDERS_PATH: {"orders": []},
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
        exit_manifest=exit_manifest,
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


def _budget_marker(store_path: Path, day: str) -> bytes | None:
    with SqliteStateStore(store_path) as reopened:
        return reopened.get(f"{BUDGET_EXHAUSTED_KEY_PREFIX}{day}")


# ---------------------------------------------------------------------------
# Operator ruling 2026-09-14: the daily-budget day stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_daily_budget_denial_writes_the_utc_day_marker_and_still_denies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "0.10"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert sender.calls == []
    day = utc_day_for_ns(rig.clock.timestamp_ns()).isoformat()
    assert _budget_marker(rig.store_path, day) == b"1"


@pytest.mark.asyncio
async def test_a_session_notional_exhaustion_writes_the_same_day_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Operator ruling 2026-09-14: session notional derives from the daily
    budget, so its exhaustion is the SAME day's dollar ceiling."""
    sender = _FakeOrderSender()
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
            OPEN_ORDERS_PATH: {"orders": []},
        },
    )
    order_events: list[Any] = []

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)
    msgbus.register(endpoint="ExecEngine.process", handler=order_events.append)

    store_path = tmp_path / "exec_state.db"
    enable_operator_gate(monkeypatch, session_notional="0.10")
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
        order_sender=sender,
        write_signer=_FakeWriteSigner(),
        live_trading_permit=issued_permit,
        spend_ledger=DailySpendLedger(),
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
    )
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=clock)
    order = factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=Price.from_str("0.37"),
        time_in_force=TimeInForce.IOC,
    )
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
        await client._connect()
        await client._submit_order(command)
        await client._disconnect()

    denials = [event for event in order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert sender.calls == []
    day = utc_day_for_ns(clock.timestamp_ns()).isoformat()
    assert _budget_marker(store_path, day) == b"1"


def _build_manual_client(
    tmp_path: Path,
    *,
    name: str,
    permit: Any,
    sender: _FakeOrderSender,
) -> tuple[PolymarketUSExecutionClient, list[Any], Path, LiveClock]:
    """A second, independently-stored client stack sharing ONE already-issued
    permit -- so its in-process ``_PERMIT_BUDGETS`` entry (keyed by
    ``permit.permit_id``, not by client) is genuinely shared, the way a
    process restart against the same permit id would be."""
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
            OPEN_ORDERS_PATH: {"orders": []},
        },
    )
    order_events: list[Any] = []

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)
    msgbus.register(endpoint="ExecEngine.process", handler=order_events.append)

    store_path = tmp_path / f"exec_state_{name}.db"
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
        order_sender=sender,
        write_signer=_FakeWriteSigner(),
        live_trading_permit=permit,
        spend_ledger=DailySpendLedger(),
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
    )
    client._instrument_for_test = instrument
    # Kept alive on the client for the rig's lifetime -- see
    # `_AcceptFillRig`'s identical note: dropping this reference finalises
    # the generator-CM via `GeneratorExit` and silently releases the flock
    # mid-test.
    client._latch_cm_for_test = latch_cm
    return client, order_events, store_path, clock


def _manual_limit_buy(client: Any, clock: LiveClock) -> SubmitOrder:
    instrument = client._instrument_for_test
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=clock)
    order = factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=Price.from_str("0.37"),
        time_in_force=TimeInForce.IOC,
    )
    return SubmitOrder(
        trader_id=TRADER_ID, strategy_id=STRATEGY_ID, order=order, command_id=UUID4(),
        ts_init=TS_INIT,
    )


@pytest.mark.asyncio
async def test_a_session_order_count_exhaustion_writes_no_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """D3 (Rev 2 dispositions): the session ORDER-COUNT ceiling is a
    distinct, non-dollar limit under the 09-14 per-order ruling; it must
    never mark the day.

    Two client stacks (fresh store + latch each) share ONE issued permit:
    the first cleanly retires its slot with an accepted fill, so the second
    reaches the permit check with a fresh (unlatched) submit intent and an
    exhausted order-count budget -- unambiguously the count ceiling, not the
    per-order intent-wait path.
    """
    enable_operator_gate(monkeypatch, session_notional="1000.00", order_count="1")
    clock0 = LiveClock()
    permit = issue_live_trading_permit(clock=clock0)

    sender1 = _FakeOrderSender()
    client1, events1, _store_path1, clock1 = _build_manual_client(
        tmp_path, name="a", permit=permit, sender=sender1,
    )
    slug = _slug(client1._instrument_for_test)
    sender1.response = VenueResponse(status=200, headers={}, body=_accept_fill_body(slug))
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await client1._connect()
        await client1._submit_order(_manual_limit_buy(client1, clock1))
        await client1._disconnect()
    assert any(isinstance(event, OrderFilled) for event in events1)

    sender2 = _FakeOrderSender()
    client2, events2, store_path2, clock2 = _build_manual_client(
        tmp_path, name="b", permit=permit, sender=sender2,
    )
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await client2._connect()
        await client2._submit_order(_manual_limit_buy(client2, clock2))
        await client2._disconnect()

    denials2 = [event for event in events2 if isinstance(event, OrderDenied)]
    assert len(denials2) == 1
    assert sender2.calls == []
    day = utc_day_for_ns(clock2.timestamp_ns()).isoformat()
    assert _budget_marker(store_path2, day) is None


@pytest.mark.asyncio
async def test_a_per_position_ceiling_denial_writes_no_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "0.10"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert sender.calls == []
    day = utc_day_for_ns(rig.clock.timestamp_ns()).isoformat()
    assert _budget_marker(rig.store_path, day) is None


@pytest.mark.asyncio
async def test_a_clock_rewind_denial_writes_no_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The clock-rewind branch shares the daily env-var name in its message
    but is a plain ``LiveTradingPermissionError``, never
    ``DailyBudgetExhausted`` -- pinned directly on the ledger by
    ``test_operator_reserved_controls.py``. Here it must not reach the
    exec client's marker-writing except arm either."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    def _raise_clock_rewind(*args: Any, **kwargs: Any) -> Any:
        # A plain LiveTradingPermissionError -- deliberately NOT the typed
        # DailyBudgetExhausted subclass, mirroring the real clock-rewind
        # branch (operator_controls.py). The message text is irrelevant to
        # this test and intentionally omits the control's name so the
        # assignment scan's A6 rule (no control name outside the whitelisted
        # seam) does not fire on this test double.
        raise LiveTradingPermissionError(
            "refuses this order: the injected clock moved backwards, and "
            "spent budget is never resurrected"
        )

    monkeypatch.setattr(DailySpendLedger, "authorize_order_cost", _raise_clock_rewind)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    day = utc_day_for_ns(rig.clock.timestamp_ns()).isoformat()
    assert _budget_marker(rig.store_path, day) is None


@pytest.mark.asyncio
async def test_a_marker_store_write_failure_still_denies_the_order_and_does_not_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """D1 (Rev 2 dispositions): the marker write is exception-shielded, so
    ``self._deny(...)`` always runs."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    original_store_set = rig.client._store_set

    def _raise_only_for_the_budget_marker(key: str, value: bytes) -> None:
        if key.startswith(BUDGET_EXHAUSTED_KEY_PREFIX):
            raise RuntimeError("simulated store failure")
        original_store_set(key, value)

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "0.10"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await rig.client._connect()
        monkeypatch.setattr(rig.client, "_store_set", _raise_only_for_the_budget_marker)
        await rig.client._submit_order(rig.limit_buy())  # must not raise
        await rig.client._disconnect()

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert sender.calls == []


def test_the_typed_budget_excepts_precede_the_parent_clause() -> None:
    """D2 (Rev 2 dispositions): ``except SessionNotionalExhausted`` /
    ``except DailyBudgetExhausted`` must each precede the parent
    ``except LiveTradingPermissionError`` in ``_submit_order``'s source --
    an ``except`` clause ordering that a Python interpreter itself enforces
    at compile time only for identical types, never for a subclass listed
    after its own parent (which would silently make the subclass arm dead
    code)."""
    import textwrap

    source = inspect.getsource(client_module.PolymarketUSExecutionClient._submit_order)
    tree = ast.parse(textwrap.dedent(source))
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef))
    try_nodes = [node for node in ast.walk(call) if isinstance(node, ast.Try)]
    found_pairs = 0
    for try_node in try_nodes:
        names = [
            handler.type.id
            for handler in try_node.handlers
            if isinstance(handler.type, ast.Name)
        ]
        if "LiveTradingPermissionError" in names:
            parent_index = names.index("LiveTradingPermissionError")
            for typed_name in ("SessionNotionalExhausted", "DailyBudgetExhausted"):
                if typed_name in names:
                    assert names.index(typed_name) < parent_index, (
                        f"{typed_name} must precede LiveTradingPermissionError, got {names}"
                    )
                    found_pairs += 1
    assert found_pairs == 2, f"expected both typed excepts pinned, found {found_pairs}"


def test_the_budget_stop_log_line_names_no_dollar_figure_and_no_control_name() -> None:
    """A live log capture is unreliable here (`self._log` is Nautilus's
    Rust-backed logger, not interceptable through `caplog`/`capsys`/
    `capfd`), so this parses `_mark_budget_exhausted`'s own source instead --
    the same AST-based technique `test_the_seed_log_line_names_only_the_
    count_and_the_day` already uses."""
    import re
    import textwrap

    source = inspect.getsource(PolymarketUSExecutionClient._mark_budget_exhausted)
    tree = ast.parse(textwrap.dedent(source))
    log_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "warning"
    ]
    assert log_calls, "expected at least one `self._log.warning(...)` call"
    for call in log_calls:
        for arg in call.args:
            formatted = ast.unparse(arg)
            assert "$" not in formatted
            assert MAX_DAILY_BUDGET_USD_ENV_VAR not in formatted
            assert MAX_POSITION_COST_USD_ENV_VAR not in formatted
            assert re.search(r"\d+\.\d\d", formatted) is None


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

    def _spy_record_fill(record: DurableFillRecord, **kwargs: Any) -> None:
        # AUD-13b: the write sites now pass `fill_time_instrument=` through.
        rig.trace.append("record_fill")
        original_record_fill(record, **kwargs)

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


# ---------------------------------------------------------------------------
# INC-E2 (POSITION_EXIT_EXECUTION_2026-09-16.md §3): fill accounting takes
# the order's REAL side, and an exit-side order never touches the daily
# budget. No exit order can reach `_submit_order` yet --
# `submit_chain.unmappable_order_reason` refuses every non-BUY order,
# byte-unchanged (INC-E2b/E3 build the exit seam that reaches this
# mappable) -- so every test below monkeypatches that ONE gate off, for
# this test only, to isolate the fill-accounting/budget fix under test.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sell_side_accept_fill_books_sell_not_buy_and_never_debits_the_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RED (pre-INC-E2): the durable record and the native `OrderFilled`
    both hardcoded BUY (`LONG_ONLY_SIDE` / `OrderSide.BUY`) regardless of
    the order's real side, and `authorize_order_cost` ran unconditionally.
    GREEN: a SELL-side fill books SELL both places, nets to a negative
    signed quantity via the existing `_RECORD_SIGNS` table, and the daily
    ledger is untouched -- `authorize_order_cost` is never even called."""
    monkeypatch.setattr(submit_chain, "unmappable_order_reason", lambda order, instrument: None)
    ledger = DailySpendLedger()
    authorize_calls: list[Any] = []
    original_authorize = DailySpendLedger.authorize_order_cost

    def _spy_authorize(self_: DailySpendLedger, **kwargs: Any) -> Any:
        authorize_calls.append(kwargs)
        return original_authorize(self_, **kwargs)

    monkeypatch.setattr(DailySpendLedger, "authorize_order_cost", _spy_authorize)

    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    rig.client._ledger = ledger
    slug = _slug(rig.instrument)
    order_id = "ord-e2-sell"
    sender.response = VenueResponse(
        status=200, headers={}, body=_accept_fill_body(slug, order_id=order_id),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_sell())
        now_ns = rig.clock.timestamp_ns()
        await rig.client._disconnect()

    assert authorize_calls == [], "a SELL-side order must never call authorize_order_cost"
    assert ledger.spent_today_usd(now_ns=now_ns) == Decimal(0), (
        "an exit fill must never debit the daily (gross entry spend) counter"
    )

    record = _reopened_fill_record(rig.store_path, order_id)
    assert record is not None
    assert record.order_side == "SELL"
    assert client_module._RECORD_SIGNS[record.order_side] * record.cumulative_qty == Decimal(-1)

    fills = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    assert len(fills) == 1
    assert fills[0].order_side == OrderSide.SELL


@pytest.mark.asyncio
async def test_a_buy_side_accept_fill_still_books_buy_and_still_debits_the_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The BUY path must stay byte-identical after INC-E2: this is the same
    assertion shape as the SELL test above, mirrored for a BUY, so a future
    change to the shared code path is caught on both sides at once."""
    ledger = DailySpendLedger()
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    rig.client._ledger = ledger
    slug = _slug(rig.instrument)
    order_id = "ord-e2-buy"
    sender.response = VenueResponse(
        status=200, headers={}, body=_accept_fill_body(slug, order_id=order_id, last_px="0.37"),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        now_ns = rig.clock.timestamp_ns()
        await rig.client._disconnect()

    assert ledger.spent_today_usd(now_ns=now_ns) == Decimal("0.37")

    record = _reopened_fill_record(rig.store_path, order_id)
    assert record is not None
    assert record.order_side == "BUY"
    assert client_module._RECORD_SIGNS[record.order_side] * record.cumulative_qty == Decimal(1)

    fills = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    assert len(fills) == 1
    assert fills[0].order_side == OrderSide.BUY


# ---------------------------------------------------------------------------
# INC-E2c: wiring the exec client to the exit seam
# (`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` §3 INC-E2, live-tree
# path). `limit_exit_sell` builds the exact tag shape
# `exit_wiring.submit_exit` constructs; these tests drive `_submit_order`
# end to end, never calling `submit_chain` directly (that seam is pinned by
# `test_polymarket_us_exit_submit_chain_2026_09_16.py`).
# ---------------------------------------------------------------------------


def _no_leg_instrument() -> BinaryOption:
    """The NO-leg sibling of `polymarket_us_exec_shapes.build_instrument`,
    from the SAME captured market file, via the pair parser."""
    payload = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    )
    _yes, no = parse_binary_option_pair(payload, ts_init=TS_INIT)
    assert no is not None
    return no


@pytest.mark.asyncio
async def test_an_authorised_yes_exit_maps_and_sends_through_the_same_seam_as_a_buy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )
    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_exit_sell(price="0.55"))
        await rig.client._disconnect()

    assert len(sender.calls) == 1, "an authorised exit must reach the ONE sanctioned egress call"
    sent_body = json.loads(sender.calls[0]["body"])
    assert sent_body["action"] == "ORDER_ACTION_SELL"
    assert sent_body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert sent_body["price"] == {"value": "0.55", "currency": "USD"}
    assert sent_body["quantity"] == 1

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert denials == []


@pytest.mark.asyncio
async def test_an_authorised_no_exit_maps_with_the_complemented_price(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """NO at instrument price 0.09 -> wire price 0.91 (matches
    `test_polymarket_us_exit_submit_chain_2026_09_16.py`'s pin at the
    `submit_chain` layer -- this proves the SAME translation survives the
    exec-client wiring)."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_NO_LEG_EXIT_MANIFEST,
    )
    no_instrument = _no_leg_instrument()
    rig.client._cache.add_instrument(no_instrument)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(
            rig.limit_exit_sell(price="0.09", instrument=no_instrument)
        )
        await rig.client._disconnect()

    assert len(sender.calls) == 1
    sent_body = json.loads(sender.calls[0]["body"])
    assert sent_body["action"] == "ORDER_ACTION_SELL"
    assert sent_body["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert sent_body["price"] == {"value": "0.91", "currency": "USD"}

    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert denials == []


@pytest.mark.asyncio
async def test_a_tagged_no_exit_is_denied_when_the_armed_manifest_does_not_declare_no_leg_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """FU-1d S2 (defense in depth, `RULING_FU-1b_no_leg_marks_2026-09-26.md`
    re-open item 2). RED against today's code: `ARMED_EXIT_MANIFEST` is
    registered and armed for an exit, but does NOT declare `no_leg_exit` --
    a tagged NO exit must be denied at the exec-client boundary with the
    new reason, exactly one `OrderDenied`, and `sender.calls == []` (never
    reaching transport)."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )
    no_instrument = _no_leg_instrument()
    rig.client._cache.add_instrument(no_instrument)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(
            rig.limit_exit_sell(price="0.09", instrument=no_instrument)
        )
        await rig.client._disconnect()

    assert sender.calls == [], "a NO exit refused for an undeclared no_leg_exit must never send"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].reason == "family does not declare a NO-leg exit; refusing"


@pytest.mark.asyncio
async def test_an_untagged_sell_is_still_refused_as_a_naked_short_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """No exit tags -> the plain (BUY-only) path, unchanged: the exact same
    reason `test_no_side_submit_chain_2026_09_14.py` pins at the
    `submit_chain` layer, now proven at the exec-client boundary too."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )
    command = rig.limit_sell()
    expected_reason = submit_chain.unmappable_order_reason(command.order, rig.instrument)
    assert expected_reason == "only a BUY is mappable (a SELL is a naked short); refusing"

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(command)
        await rig.client._disconnect()

    assert sender.calls == []
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].reason == expected_reason


@pytest.mark.asyncio
async def test_a_tagged_exit_is_denied_when_the_live_manifest_declares_no_exit_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The LIVE configuration (`persistence/exit_gate.py` module docstring):
    `pm_us_crh_cont` declares no `exit_rule`, so the gate stays closed and
    `_submit_order` never reaches `self._order_sender.post_order` at all --
    the seam ships unarmed."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=LIVE_UNARMED_MANIFEST,
    )
    command = rig.limit_exit_sell(family_id="pm_us_crh_cont")

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(command)
        await rig.client._disconnect()

    assert sender.calls == [], "the LIVE (unarmed) manifest must never let an exit reach transport"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].reason == "family does not declare a registered exit rule; refusing"


@pytest.mark.asyncio
async def test_a_tagged_exit_with_a_vanished_instrument_denies_before_fabricating_a_leg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Item C (POSITION_EXIT_EXECUTION_2026-09-16.md review, LOW): an
    exit-tagged order for an instrument absent from the cache must deny
    immediately, never construct an `_AdapterExitAuthorization` with a
    fabricated `exit_leg="yes"` placeholder. The instrument below is never
    registered on `rig.client._cache`, standing in for the (already-logged
    elsewhere) "instrument vanished from cache" race."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )
    vanished_instrument = _no_leg_instrument()  # deliberately NOT added to rig.client._cache
    command = rig.limit_exit_sell(instrument=vanished_instrument)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(command)
        await rig.client._disconnect()

    assert sender.calls == [], "a vanished instrument must never reach transport"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].reason == "instrument is not a BinaryOption; refusing"


@pytest.mark.asyncio
async def test_an_ambiguous_exit_send_leaves_the_durable_intent_open_across_a_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Review finding B (POSITION_EXIT_EXECUTION_2026-09-16.md, first layer
    of the AMBIGUOUS-exit cover): an exit order whose create-order response
    classifies `KIND_AMBIGUOUS` (with-id, L-36 shape) leaves the
    account-wide `SubmitIntentLatch` OPEN on disk -- `_submit_order`'s own
    `arm()` -> POST -> classify prefix is IDENTICAL for an entry and an
    exit, so this needs no new production code, only proof. A brand-new
    client instance over the SAME store (standing in for a process restart)
    still sees the OPEN singleton and refuses BOTH the next entry AND the
    next exit with the SAME open-intent reason, until an operator retires
    it -- this is the durable cover the exec client's silent, in-memory
    `_refuse` on a POST exception/AMBIGUOUS classification cannot itself
    provide via an order event."""
    order_id = "ord-exit-ambiguous-1"
    sender = _FakeOrderSender()
    sender.response = VenueResponse(status=200, headers={}, body=_ambiguous_with_id_body(order_id))
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_exit_sell())

        assert rig.client._latch is not None
        assert rig.client._latch.is_latched() is True, (
            "an AMBIGUOUS exit send must leave the account-wide intent OPEN"
        )
        denials_first = [event for event in rig.order_events if isinstance(event, OrderDenied)]
        assert denials_first == [], (
            "AMBIGUOUS raises no order event at all -- this is exactly the "
            "gap the durable latch, not an OrderDenied/OrderRejected, covers"
        )

        await rig.client._disconnect()
    # Release the flock this rig's `open_submit_intent_latch` call holds --
    # standing in for the process exiting -- so a SECOND client can open the
    # SAME store, exactly like a restarted process would.
    rig._latch_cm.__exit__(None, None, None)

    second_sender = _FakeOrderSender()
    restarted_rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=second_sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )

    with _accept_fill_caps():
        await restarted_rig.client._connect()
        await restarted_rig.client._submit_order(restarted_rig.limit_buy())
        await restarted_rig.client._submit_order(restarted_rig.limit_exit_sell())
        await restarted_rig.client._disconnect()

    assert second_sender.calls == [], (
        "a restarted client over the SAME store must never let ANY order -- "
        "entry or exit -- reach transport while the intent is still OPEN"
    )
    restart_denials = [
        event for event in restarted_rig.order_events if isinstance(event, OrderDenied)
    ]
    assert len(restart_denials) == 2
    assert all(denial.reason == submit_chain.OPEN_INTENT_WAIT_REASON for denial in restart_denials)


def _exit_shaped_body_with_echo(
    slug: str, *, order_id: str, side: str, intent: str, last_px: str = "0.37"
) -> bytes:
    """The SAME accept-fill shape `_accept_fill_body` builds, with the
    nested order's `side`/`intent` overridden -- so the venue's ECHO can be
    driven independently of the order Breezy actually sent. `last_px`
    (INC-E2, additive default -- every existing caller stays at "0.37")
    drives the wire price independently too, so a NO-leg close's pinned
    0.99 wire (0.01 instrument price) can be built the same way."""
    order = build_order(slug)
    order["id"] = order_id
    order["quantity"] = 1
    order["cumQuantity"] = 1
    order["leavesQuantity"] = 0
    order["state"] = "ORDER_STATE_FILLED"
    order["price"] = {"value": last_px, "currency": "USD"}
    order["avgPx"] = {"value": last_px, "currency": "USD"}
    order["side"] = side
    order["intent"] = intent
    execution = build_execution(order)
    execution["lastShares"] = "1"
    execution["lastPx"] = {"value": last_px, "currency": "USD"}
    execution["commissionNotionalCollected"] = {"value": "0.03", "currency": "USD"}
    return json.dumps({"id": order_id, "executions": [execution]}).encode("utf-8")


@pytest.mark.asyncio
async def test_an_exit_fill_with_a_mismatched_venue_echo_never_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """`reports.py._order_side_for_leg` is byte-unchanged (plan's pinned
    test #1) and still unconditionally applies the BUY-table echo
    (`VENUE_SIDE_FOR_LEG`/`VENUE_INTENT_FOR_LEG`) to every fill it parses,
    entry or exit. A venue echo that matches NEITHER table -- here, the
    NO-leg CLOSE pair (`ORDER_SIDE_SELL`, `ORDER_INTENT_SELL_SHORT`) echoed
    for a YES-leg exit -- fails the mapper's cross-check and the outcome
    stays `KIND_AMBIGUOUS`: never an `OrderFilled`, and the AMBIGUOUS
    refusal is latched. (Making a CORRECTLY-echoed exit fill classify as
    `KIND_ACCEPT_FILL` needs `reports.py` to become exit-aware -- out of
    this increment's file list; see the return's open question.)"""
    slug = _slug(build_instrument())
    order_id = "ord-exit-echo-1"
    sender = _FakeOrderSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_exit_shaped_body_with_echo(
            slug, order_id=order_id, side="ORDER_SIDE_SELL", intent="ORDER_INTENT_SELL_SHORT",
        ),
    )
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_exit_sell(price="0.37"))
        await rig.client._disconnect()

    assert len(sender.calls) == 1, "the well-formed, authorised exit still reaches the venue"
    fills = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    assert fills == [], "a mismatched exit echo must never accept a fill"
    assert submit_chain.AMBIGUOUS_REASON in rig.client.trading_refusals


# ---------------------------------------------------------------------------
# INC-E2 gap close: `reports.py`/`classify_create_order_outcome` are now
# exit-aware (`closing=is_exit_order`, threaded from `_submit_order`'s own
# tag-derived flag). A CORRECTLY-echoed exit fill now accepts instead of
# staying the AMBIGUOUS residual the docstring above describes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_authorised_yes_exit_with_the_pinned_echo_now_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    slug = _slug(build_instrument())
    order_id = "ord-exit-yes-accept-1"
    sender = _FakeOrderSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_exit_shaped_body_with_echo(
            slug, order_id=order_id, side="ORDER_SIDE_SELL", intent="ORDER_INTENT_SELL_LONG",
        ),
    )
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_exit_sell(price="0.37"))
        await rig.client._disconnect()

    assert len(sender.calls) == 1
    fills = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    assert len(fills) == 1, "a correctly-echoed YES close must accept the fill"
    assert fills[0].order_side == OrderSide.SELL
    assert submit_chain.AMBIGUOUS_REASON not in rig.client.trading_refusals

    record = _reopened_fill_record(rig.store_path, order_id)
    assert record is not None
    assert record.order_side == "SELL"
    assert client_module._RECORD_SIGNS[record.order_side] * record.cumulative_qty == Decimal(-1)


@pytest.mark.asyncio
async def test_an_authorised_no_exit_with_the_pinned_mirrored_echo_now_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """NO close: request instrument price 0.01 -> wire 0.99 (the SAME
    complement `test_an_authorised_no_exit_maps_with_the_complemented_price`
    proves on the request side); the response echoes the pinned
    ``(ORDER_SIDE_BUY, ORDER_INTENT_SELL_SHORT)`` mirror pair at that same
    wire price, and now accepts at the decoded instrument price 0.01."""
    no_instrument = _no_leg_instrument()
    slug = str(no_instrument.raw_symbol)
    order_id = "ord-exit-no-accept-1"
    sender = _FakeOrderSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_exit_shaped_body_with_echo(
            slug,
            order_id=order_id,
            side="ORDER_SIDE_BUY",
            intent="ORDER_INTENT_SELL_SHORT",
            last_px="0.99",
        ),
    )
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_NO_LEG_EXIT_MANIFEST,
    )
    rig.client._cache.add_instrument(no_instrument)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(
            rig.limit_exit_sell(price="0.01", instrument=no_instrument)
        )
        await rig.client._disconnect()

    assert len(sender.calls) == 1
    sent_body = json.loads(sender.calls[0]["body"])
    assert sent_body["price"] == {"value": "0.99", "currency": "USD"}

    fills = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    assert len(fills) == 1, "a correctly-echoed NO close must accept the fill"
    assert fills[0].order_side == OrderSide.SELL
    assert fills[0].last_px == Price.from_str("0.01")
    assert submit_chain.AMBIGUOUS_REASON not in rig.client.trading_refusals

    record = _reopened_fill_record(rig.store_path, order_id)
    assert record is not None
    assert record.order_side == "SELL"
    assert client_module._RECORD_SIGNS[record.order_side] * record.cumulative_qty == Decimal(-1)


@pytest.mark.asyncio
async def test_a_no_exit_echoed_with_the_wrong_side_stays_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The NO-close echo's ``side`` is ``BUY``; a ``SELL`` on the same
    ``SELL_SHORT`` intent matches neither table and must never accept."""
    no_instrument = _no_leg_instrument()
    slug = str(no_instrument.raw_symbol)
    order_id = "ord-exit-no-wrong-side-1"
    sender = _FakeOrderSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_exit_shaped_body_with_echo(
            slug,
            order_id=order_id,
            side="ORDER_SIDE_SELL",
            intent="ORDER_INTENT_SELL_SHORT",
            last_px="0.99",
        ),
    )
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_NO_LEG_EXIT_MANIFEST,
    )
    rig.client._cache.add_instrument(no_instrument)

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(
            rig.limit_exit_sell(price="0.01", instrument=no_instrument)
        )
        await rig.client._disconnect()

    assert len(sender.calls) == 1
    fills = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    assert fills == [], "a wrong-side NO-close echo must never accept a fill"
    assert submit_chain.AMBIGUOUS_REASON in rig.client.trading_refusals


class _YieldingOrderSender(_FakeOrderSender):
    """Like `_FakeOrderSender`, but yields to the event loop once before
    resolving -- so a SECOND `_submit_order` task, created before this one
    finishes, gets a chance to run its own prefix (through the SAME-tick
    `arm()`/`is_latched()` re-check SAFETY C1 describes) while THIS one is
    suspended, rather than running the two to completion back to back."""

    async def post_order(
        self, base_url: str, *, headers: Mapping[str, str], body: bytes,
    ) -> VenueResponse:
        # Inlined rather than `await super().post_order(...)`: B9
        # (`test_polymarket_us_readonly_guard.py`) pins `post_order` to
        # EXACTLY one repo-wide call site
        # (`exec/client.py::_submit_order`) by scanning for the CALL, not
        # the definition -- a second named call site here, even to this
        # fake's own base class, would widen that pin.
        await asyncio.sleep(0)
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        return self.response


@pytest.mark.asyncio
async def test_an_open_entry_intent_refuses_a_concurrent_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """SAFETY C1's account-wide `SubmitIntentLatch` singleton is NOT
    re-checked per side (`exit_wiring.submit_exit`'s own docstring): a
    concurrently-submitted exit, created before the entry's own `arm()` ->
    `post_order` round trip resolves, observes `is_latched() is True` and
    is denied as a WAIT -- exactly like a second entry would be -- rather
    than reaching the venue itself."""
    sender = _YieldingOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )

    with _accept_fill_caps():
        await rig.client._connect()
        entry_task = asyncio.create_task(rig.client._submit_order(rig.limit_buy()))
        exit_task = asyncio.create_task(rig.client._submit_order(rig.limit_exit_sell()))
        await asyncio.gather(entry_task, exit_task)
        await rig.client._disconnect()

    assert len(sender.calls) == 1, "only the entry reaches transport; the exit is a WAIT, not sent"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].client_order_id == rig.limit_exit_sell().order.client_order_id
    assert denials[0].reason == submit_chain.OPEN_INTENT_WAIT_REASON


@pytest.mark.asyncio
async def test_an_open_exit_intent_refuses_a_concurrent_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The reverse of the test above: a concurrently-submitted entry,
    created before the exit's own round trip resolves, is refused as a
    WAIT instead of reaching the venue."""
    sender = _YieldingOrderSender()
    rig = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=sender, exit_manifest=ARMED_EXIT_MANIFEST,
    )

    with _accept_fill_caps():
        await rig.client._connect()
        exit_task = asyncio.create_task(rig.client._submit_order(rig.limit_exit_sell()))
        entry_task = asyncio.create_task(rig.client._submit_order(rig.limit_buy()))
        await asyncio.gather(exit_task, entry_task)
        await rig.client._disconnect()

    assert len(sender.calls) == 1, "only the exit reaches transport; the entry is a WAIT, not sent"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert denials[0].reason == submit_chain.OPEN_INTENT_WAIT_REASON


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

    def _boom(record: DurableFillRecord, **kwargs: Any) -> None:
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
        # AUD-13b (ruling R-1 = O4): two more optional-on-read keys, same
        # pattern as `tradeId`/`orderQty`. WIDENED, not relaxed: still `==`.
        "feeCoefficientAtFill",
        "feeSource",
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


# (f4) AUD-13b / ruling R-1 = O4: `fee_coefficient_at_fill` and `fee_source`
# round-trip, and are optional-on-read for every record written before them.
def test_a_durable_record_round_trips_the_fee_coefficient_at_fill_and_fee_source() -> None:
    record = DurableFillRecord(
        venue_order_id="V-ROUNDTRIP-3",
        client_order_id="O-19700101-000000-001-001-3",
        instrument_id="some-instrument",
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.44"),
        cumulative_fee=Decimal(0),
        fee_reconciled=False,
        ts_event=TS_INIT,
        fee_coefficient_at_fill=Decimal("0.0695"),
        fee_source="MODELLED_AT_FILL_TIME",
    )
    raw = record.to_bytes()
    decoded = json.loads(raw)
    assert decoded["feeCoefficientAtFill"] == "0.0695"
    assert decoded["feeSource"] == "MODELLED_AT_FILL_TIME"
    assert DurableFillRecord.from_bytes(raw) == record


def test_a_legacy_record_decodes_with_no_fee_coefficient_at_fill_and_no_fee_source() -> None:
    legacy = DurableFillRecord.from_bytes(_raw_record())
    assert legacy.fee_coefficient_at_fill is None
    assert legacy.fee_source is None


@pytest.mark.parametrize("bad", ["NaN", "-0.01", "1.5"])
def test_an_unusable_fee_coefficient_at_fill_is_refused(bad: str) -> None:
    with pytest.raises(ExecutionReportMappingError, match="feeCoefficientAtFill"):
        DurableFillRecord.from_bytes(_raw_record(feeCoefficientAtFill=bad))


@pytest.mark.parametrize("bad", ["recorded", "MODELLED", 1])
def test_a_fee_source_outside_the_two_ruled_values_is_refused(bad: Any) -> None:
    with pytest.raises(ExecutionReportMappingError, match="feeSource"):
        DurableFillRecord.from_bytes(_raw_record(feeSource=bad))


@pytest.mark.asyncio
async def test_an_accept_fill_stamps_the_fill_time_coefficient_and_fee_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """B0 (ruling R-1 mechanism (a)): the CREATE-path write site records the
    theta of the `Instrument` in hand AT FILL TIME, and the `feeSource` the O4
    rule derives from the record itself."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200, headers={}, body=_accept_fill_body(slug, order_id="ord-b0-theta"),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        (record,) = rig.client.fill_records_for(rig.instrument.id)
        await rig.client._disconnect()

    assert record.fee_coefficient_at_fill == Decimal(
        str(rig.instrument.info[FEE_COEFFICIENT_KEY])
    )
    expected = (
        "RECORDED"
        if record.fee_reconciled and record.venue_fee_raw is not None
        else "MODELLED_AT_FILL_TIME"
    )
    assert record.fee_source == expected


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


def test_a_resolver_context_written_before_order_side_still_decodes_as_buy() -> None:
    """INC-E2: same AR-N6 shape as the test above, for the new `order_side`
    field. An old blob (no `orderSide` key -- every order this client had
    ever built was a BUY) decodes to `LONG_ONLY_SIDE`; a new row round-trips
    whatever real side it was given, including `SELL`."""
    old_blob = json.dumps(
        {
            "intentId": "intent-old-side",
            "venueOrderId": "venue-old-side",
            "instrumentId": "instrument-old-side",
            "clientOrderId": "client-old-side",
            "strategyId": "strategy-old-side",
            "notionalUsd": "1.00",
            "bookingId": 9,
            "createdNs": TS_INIT,
        },
        sort_keys=True,
    ).encode("utf-8")

    old_context = AmbiguousResolverContext.from_bytes(old_blob)
    assert old_context.order_side == client_module.LONG_ONLY_SIDE

    sell_context = AmbiguousResolverContext(
        intent_id="intent-new-sell",
        venue_order_id="venue-new-sell",
        instrument_id="instrument-new-sell",
        client_order_id="client-new-sell",
        strategy_id="strategy-new-sell",
        notional_usd=Decimal("1.00"),
        booking_id=10,
        created_ns=TS_INIT,
        order_side="SELL",
    )
    round_tripped = AmbiguousResolverContext.from_bytes(sell_context.to_bytes())
    assert round_tripped.order_side == "SELL"


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
            OPEN_ORDERS_PATH: {"orders": []},
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


# ---------------------------------------------------------------------------
# INC-E2: the resolver path (`_resolve_accept_fill`) takes the durable
# context's own `order_side`, never the entry-only `LONG_ONLY_SIDE` /
# `OrderSide.BUY` hardcodes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_resolver_accept_fill_books_the_contexts_real_order_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RED (pre-INC-E2): the resolver always recorded `LONG_ONLY_SIDE` /
    `OrderSide.BUY`, regardless of what a durable `AmbiguousResolverContext`
    named. GREEN: a context carrying `order_side="SELL"` books SELL in both
    the durable record and the native `OrderFilled`."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-e2-resolver-sell"
    sender.response = VenueResponse(status=200, headers={}, body=_ambiguous_with_id_body(order_id))

    with _accept_fill_caps():
        await rig.client._connect()
        # Only the latch needs to be armed and OPEN; the initiating order's
        # own side is irrelevant to this test -- `_resolve_accept_fill`
        # reads the durable context's `order_side`, never the order that
        # armed the intent. FU-8: the real `ExecutionEngine` adds a submitted
        # order to the cache before it ever reaches the client
        # (`execution/engine.pyx:1122`); this rig calls `_submit_order`
        # directly, so it is replicated here -- otherwise
        # `_resolver_fill_order_unknown` (FU-8) sees no cached order for
        # this SAME-session fill and (correctly, for a genuinely unknown
        # order) defers it instead of booking it.
        command = rig.limit_buy()
        rig.client._cache.add_order(command.order, position_id=None)
        await rig.client._submit_order(command)

        assert rig.client._latch is not None
        current = rig.client._latch.current_open()
        assert current is not None, "the with-id AMBIGUOUS outcome must leave OPEN"

        instrument = rig.instrument
        now_ns = rig.clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=current.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id=command.order.client_order_id.value,
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=now_ns,
            order_side="SELL",
        )
        rig.client._resolved_by_get_ts_ns[current.intent_id] = now_ns
        rig.client._ambiguous_bookings.pop(current.intent_id, None)

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        await rig.client._disconnect()

    record = _reopened_fill_record(rig.store_path, order_id)
    assert record is not None
    assert record.order_side == "SELL"

    fills = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    # The initiating `rig.limit_buy()` submit classified with-id AMBIGUOUS
    # (`_ambiguous_with_id_body`), which never emits an `OrderFilled` --
    # every fill event here comes from `_resolve_accept_fill` above.
    assert len(fills) == 1
    assert fills[0].order_side == OrderSide.SELL


# ===========================================================================
# RESTING_BID_HUNT Rev 2 §4.3 -- `_read_open_orders` on the private read seam
# ===========================================================================


def _open_orders_payload(*slugs: str) -> dict[str, Any]:
    return {
        "orders": [
            {
                "id": f"RESTING{i:04d}",
                "marketSlug": slug,
                "side": "ORDER_SIDE_BUY",
                "type": "ORDER_TYPE_LIMIT",
                "price": {"value": "0.01", "currency": "USD"},
                "quantity": 1,
                "cumQuantity": 0,
                "leavesQuantity": 1,
                "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
                "state": "ORDER_STATE_NEW",
                "createTime": TS_EVENT_TEXT,
            }
            for i, slug in enumerate(slugs)
        ]
    }


@pytest.mark.asyncio
async def test_read_open_orders_issues_one_bare_path_get_and_maps_the_rows(
    tmp_path: Path,
) -> None:
    """One GET on the declared path -- no query string, so the proven
    path-only signing contract (`PrivateRead.__call__(path)`) is untouched."""
    rig = _build_rig(tmp_path)
    rig.read._payloads[OPEN_ORDERS_PATH] = _open_orders_payload("slug-a", "slug-b")

    records = await rig.client._read_open_orders()

    assert rig.read.paths == [OPEN_ORDERS_PATH]
    assert [r.venue_order_id for r in records] == ["RESTING0000", "RESTING0001"]
    assert [r.market_slug for r in records] == ["slug-a", "slug-b"]


@pytest.mark.asyncio
async def test_read_open_orders_filters_by_slug_client_side(tmp_path: Path) -> None:
    """`slugs` narrows the RESULT, never the request: the venue's `slugs[]`
    query is not sent (bare path only), so an unfiltered enumeration is what
    the boot gate sees and a caller's filter cannot hide a foreign order."""
    rig = _build_rig(tmp_path)
    rig.read._payloads[OPEN_ORDERS_PATH] = _open_orders_payload("slug-a", "slug-b")

    records = await rig.client._read_open_orders(slugs=("slug-b",))

    assert rig.read.paths == [OPEN_ORDERS_PATH]
    assert [r.market_slug for r in records] == ["slug-b"]


@pytest.mark.asyncio
async def test_read_open_orders_propagates_a_read_refusal(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path)
    rig.read.raises[OPEN_ORDERS_PATH] = PrivateReadRefused(
        status=503, path=OPEN_ORDERS_PATH, body=b'{"code": 14}',
    )
    with pytest.raises(PrivateReadRefused):
        await rig.client._read_open_orders()


@pytest.mark.asyncio
async def test_read_open_orders_refuses_a_malformed_body(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path)
    rig.read._payloads[OPEN_ORDERS_PATH] = {"orders": [{"id": "x"}]}
    with pytest.raises(ExecutionReportMappingError):
        await rig.client._read_open_orders()


@pytest.mark.asyncio
async def test_generate_order_status_reports_still_returns_empty_when_an_order_rests(
    tmp_path: Path,
) -> None:
    """DECIDED: stays ``[]``. The venue ``Order`` carries no client-order-id
    field (reports.py module docstring item 2; skill row 2026-09-05), so no
    open order is Breezy-ATTRIBUTABLE from the read alone; attribution
    arrives with the §4.4 store. Until then a report with
    ``client_order_id=None`` would make native reconciliation adopt the
    order as EXTERNAL -- the opposite of fail-closed."""
    rig = _build_rig(tmp_path)
    rig.read._payloads[OPEN_ORDERS_PATH] = _open_orders_payload("slug-a")
    await rig.client._connect()
    reports = await rig.client.generate_order_status_reports(
        GenerateOrderStatusReports(
            instrument_id=None,
            start=None,
            end=None,
            open_only=True,
            command_id=UUID4(),
            ts_init=TS_INIT,
        ),
    )
    await rig.client._disconnect()
    assert reports == []


@pytest.mark.asyncio
async def test_a_terminal_zero_rewrite_carries_the_last_open_order_read_forward(
    tmp_path: Path,
) -> None:
    """`_resolve_terminal_zero` is synchronous and cannot GET; its evidence
    rewrite must reuse the LAST enumeration rather than fabricate an empty
    one. Before any read the carried state is REFUSED (fail closed)."""
    rig = _build_rig(tmp_path)
    assert rig.client._open_orders_read_refused is True
    assert rig.client._open_orders == ()
    rig.read._payloads[OPEN_ORDERS_PATH] = _open_orders_payload("slug-a")
    await rig.client._connect()
    assert rig.client._open_orders_read_refused is False
    rig.client._write_startup_position_evidence(
        now_ns=rig.clock.timestamp_ns(),
        eof_complete=True,
        position_read_refused=False,
        raw_positions={},
    )
    evidence = rig.client.read_startup_position_evidence()
    await rig.client._disconnect()
    assert evidence is not None
    assert [o.venue_order_id for o in evidence.open_orders] == ["RESTING0000"]


def test_open_order_ids_are_redacted_to_a_prefix_in_the_error_line() -> None:
    from breezy.adapters.polymarket_us.exec.client import _redact_order_id

    assert _redact_order_id("CEBPX0EVTTMX") == "CEBP…"
    assert _redact_order_id("AB") == "AB…"


def test_resolver_terminal_statuses_is_derived_not_hand_copied() -> None:
    """Two independently hand-maintained copies of the same three statuses
    can drift silently. `_RESOLVER_TERMINAL_STATUSES` must be the SAME
    object (or at minimum equal) as `reports.NON_FILL_TERMINAL_STATUSES`,
    not a second frozenset that happens to match today."""
    from breezy.adapters.polymarket_us.exec.client import _RESOLVER_TERMINAL_STATUSES
    from breezy.adapters.polymarket_us.exec.reports import NON_FILL_TERMINAL_STATUSES

    assert _RESOLVER_TERMINAL_STATUSES is NON_FILL_TERMINAL_STATUSES
    assert _RESOLVER_TERMINAL_STATUSES == {
        OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED,
    }
    assert OrderStatus.FILLED not in _RESOLVER_TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# SP-3r: the real `_has_durable_fill_record` boot probe (plan r1 + r1.1)
# ---------------------------------------------------------------------------


def _sp3r_fill_record(
    *, venue_order_id: str, instrument_id: str, ts_event: int,
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"O-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.37"),
        cumulative_fee=Decimal("0.02"),
        fee_reconciled=True,
        ts_event=ts_event,
    )


@pytest.mark.asyncio
async def test_a_committed_fill_with_an_open_intent_is_retired_at_boot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """SP-3r AC1. Crash injection: `_retire` is monkeypatched to raise
    exactly where the real create-path accept-fill branch calls it -- AFTER
    `record_fill` (and, inside it, the day-scoped fingerprint index write)
    has already committed. The OPEN singleton and the real fill/fingerprint
    evidence both survive on disk; a brand-new client instance over the SAME
    store (standing in for a process restart, the same idiom
    `test_an_ambiguous_exit_send_leaves_the_durable_intent_open_across_a_restart`
    uses) must retire it at `_connect` via the REAL probe -- not the old
    always-``False`` stub -- with `STARTUP_FILL_RECORD_MATCH`."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    sender.response = VenueResponse(
        status=200, headers={}, body=_accept_fill_body(slug, order_id="ord-sp3r-crash"),
    )

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated crash between record_fill and _retire")

    monkeypatch.setattr(rig.client, "_retire", _boom)

    with _accept_fill_caps():
        await rig.client._connect()
        with pytest.raises(RuntimeError, match="simulated crash"):
            await rig.client._submit_order(rig.limit_buy())
        crashed = rig.submit_intent_latch.current()
        assert crashed is not None
        assert crashed.state is SubmitIntentState.OPEN, (
            "the crash must leave the singleton OPEN, exactly like a real "
            "process death between record_fill and _retire"
        )
        await rig.client._disconnect()
    # Standing in for the process exiting: release the flock this rig's
    # `open_submit_intent_latch` call holds, so a second client can open the
    # SAME store, exactly like a restarted process would.
    rig._latch_cm.__exit__(None, None, None)

    fill_record = _reopened_fill_record(rig.store_path, "ord-sp3r-crash")
    assert fill_record is not None, "record_fill's own write must have survived the crash"
    with SqliteStateStore(rig.store_path) as reopened:
        day = utc_day_for_ns(crashed.created_ns).isoformat()
        index_raw = reopened.get(f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{crashed.fingerprint}")
    assert index_raw == b"ord-sp3r-crash"

    restarted = _build_accept_fill_rig(
        tmp_path, monkeypatch=monkeypatch, sender=_FakeOrderSender(),
    )
    await restarted.client._connect()
    await restarted.client._disconnect()

    result = restarted.submit_intent_latch.current()
    assert result is not None
    assert result.intent_id == crashed.intent_id
    assert result.state is SubmitIntentState.RETIRED
    assert result.retirement_reason is RetirementReason.STARTUP_FILL_RECORD_MATCH


@pytest.mark.asyncio
async def test_probe_returns_false_with_no_fingerprint_index_entry(tmp_path: Path) -> None:
    """SP-3r AC2. Nothing was ever written for this fingerprint -- absence,
    never a synthesised match."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    assert rig.client._has_durable_fill_record("a" * 64, TS_INIT) is False
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_probe_returns_false_on_a_fingerprint_mismatch(tmp_path: Path) -> None:
    """SP-3r AC2. An index entry exists for a DIFFERENT fingerprint on the
    SAME day -- the probe must not match on the day alone. The genuine
    fingerprint, probed identically, DOES match: proves the negative case
    above is a real mismatch check, not a probe that always refuses."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    record = _sp3r_fill_record(
        venue_order_id="V-SP3R-MISMATCH", instrument_id=str(rig.instrument.id), ts_event=TS_INIT,
    )
    rig.client.record_fill(record, intent_fingerprint="b" * 64, intent_created_ns=TS_INIT)

    assert rig.client._has_durable_fill_record("c" * 64, TS_INIT) is False
    assert rig.client._has_durable_fill_record("b" * 64, TS_INIT) is True
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_probe_returns_false_on_a_store_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SP-3r AC2. A store read failure must refuse, never raise out of the
    probe and never be treated as a match."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    record = _sp3r_fill_record(
        venue_order_id="V-SP3R-STOREERR", instrument_id=str(rig.instrument.id), ts_event=TS_INIT,
    )
    rig.client.record_fill(record, intent_fingerprint="d" * 64, intent_created_ns=TS_INIT)

    def _boom(key: str) -> bytes | None:
        raise OSError("simulated store read failure")

    monkeypatch.setattr(rig.client, "_store_get", _boom)
    assert rig.client._has_durable_fill_record("d" * 64, TS_INIT) is False
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_stale_prior_day_fingerprint_index_does_not_match_a_new_days_probe(
    tmp_path: Path,
) -> None:
    """Security review r1.1: day-scoping is defence in depth against
    `client_order_id`/fingerprint reuse across UTC days. A fingerprint index
    entry written under one UTC day must never satisfy a probe for the SAME
    fingerprint carrying a NEW open intent's later `created_ns`."""
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    fingerprint = "e" * 64
    stale_day_ns = TS_INIT
    a_month_of_ns = 86_400 * 1_000_000_000 * 30
    new_day_ns = TS_INIT + a_month_of_ns
    record = _sp3r_fill_record(
        venue_order_id="V-SP3R-STALEDAY",
        instrument_id=str(rig.instrument.id),
        ts_event=stale_day_ns,
    )
    rig.client.record_fill(record, intent_fingerprint=fingerprint, intent_created_ns=stale_day_ns)

    assert rig.client._has_durable_fill_record(fingerprint, new_day_ns) is False
    # Sanity: the stale day's own probe still matches its own entry -- the
    # negative above is the day scope, not a fingerprint typo.
    assert rig.client._has_durable_fill_record(fingerprint, stale_day_ns) is True
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# WP-DR: the resolver's ledger true-up must not raise on a PRIOR-day booking.
# The "next day" is modelled as the real submit time + 24 h passed as the
# resolver's `now_ns` (the booking day is then provably != today's UTC day).
# ---------------------------------------------------------------------------

_DAY_NS: Final[int] = 24 * 60 * 60 * 1_000_000_000


class _OverCostFillReport:
    """avgPx 0.90 against a 0.37 booking: a same-day over-cost true-up."""

    avg_px = Decimal("0.90")
    filled_qty = Quantity(1, 0)
    quantity = Quantity(1, 0)


async def _arm_booked_ambiguous(
    rig: _AcceptFillRig, order_id: str, sender: _FakeOrderSender
) -> tuple[Any, AmbiguousResolverContext, int]:
    """One real with-id AMBIGUOUS take (a same-process booking exists)."""
    sender.response = VenueResponse(status=200, headers={}, body=_ambiguous_with_id_body(order_id))
    command = rig.limit_buy()
    rig.client._cache.add_order(command.order, position_id=None)
    await rig.client._submit_order(command)
    current = rig.client._latch.current_open()
    assert current is not None
    assert current.intent_id in rig.client._ambiguous_bookings
    now_ns = rig.clock.timestamp_ns()
    context = AmbiguousResolverContext(
        intent_id=current.intent_id,
        venue_order_id=order_id,
        instrument_id=str(rig.instrument.id),
        client_order_id=command.order.client_order_id.value,
        strategy_id=str(STRATEGY_ID.value),
        notional_usd=Decimal("0.37"),
        booking_id=rig.client._ambiguous_bookings[current.intent_id].booking_id,
        created_ns=now_ns,
    )
    return current, context, now_ns


@pytest.mark.asyncio
async def test_zero_fill_retire_after_midnight_cancels_clears_refusal_and_restores_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with _accept_fill_caps():
        await rig.client._connect()
        current, context, now_ns = await _arm_booked_ambiguous(rig, "ord-dr-zero", sender)
        assert submit_chain.AMBIGUOUS_REASON in rig.client.trading_refusals
        _, count_before = live_trading_budget_remaining(rig.client._permit)
        next_day_ns = now_ns + _DAY_NS
        rig.client._resolved_by_get_ts_ns[current.intent_id] = next_day_ns

        rig.client._resolve_terminal_zero(context, next_day_ns)

        after = rig.client._latch.current()
        assert after is not None
        assert after.state is SubmitIntentState.RETIRED
        assert submit_chain.AMBIGUOUS_REASON not in rig.client.trading_refusals
        _, count_after = live_trading_budget_remaining(rig.client._permit)
        assert count_after == count_before + 1
        assert any(type(e).__name__ == "OrderCanceled" for e in rig.order_events)
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_no_id_no_fill_after_midnight_clears_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with _accept_fill_caps():
        await rig.client._connect()
        current, context, now_ns = await _arm_booked_ambiguous(rig, "ord-dr-noid", sender)
        assert submit_chain.AMBIGUOUS_REASON in rig.client.trading_refusals
        next_day_ns = now_ns + _DAY_NS
        rig.client._no_id_retire_admitted = True
        rig.client._resolved_no_id_ts_ns[current.intent_id] = next_day_ns

        rig.client._resolve_no_order(current.intent_id, context, next_day_ns)

        after = rig.client._latch.current()
        assert after is not None
        assert after.state is SubmitIntentState.RETIRED
        assert submit_chain.AMBIGUOUS_REASON not in rig.client.trading_refusals
        assert rig.client._budget_was_restored(f"noid:{current.intent_id}")
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_accept_fill_after_midnight_retires_once_and_latches_fill_unbudgeted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with _accept_fill_caps():
        await rig.client._connect()
        current, context, now_ns = await _arm_booked_ambiguous(rig, "ord-dr-fill", sender)
        next_day_ns = now_ns + _DAY_NS
        rig.client._resolved_by_get_ts_ns[current.intent_id] = next_day_ns

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), rig.instrument, next_day_ns,
        )

        after = rig.client._latch.current()
        assert after is not None
        assert after.state is SubmitIntentState.RETIRED, "must not stay OPEN"
        assert client_module._RESOLVER_FILL_UNBUDGETED in rig.client.trading_refusals
        assert current.intent_id not in rig.client._ambiguous_bookings
        assert len(rig.client.fill_records_for(rig.instrument.id)) == 1
        # Re-entry is a no-op: retired exactly once, one fill record.
        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), rig.instrument, next_day_ns,
        )
        assert len(rig.client.fill_records_for(rig.instrument.id)) == 1
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_same_day_over_cost_true_up_still_escalates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with _accept_fill_caps():
        await rig.client._connect()
        current, context, now_ns = await _arm_booked_ambiguous(rig, "ord-dr-overcost", sender)
        rig.client._resolved_by_get_ts_ns[current.intent_id] = now_ns

        with pytest.raises(LiveTradingPermissionError, match="cannot cost more than authorized"):
            rig.client._resolve_accept_fill(context, _OverCostFillReport(), rig.instrument, now_ns)

        assert client_module._RESOLVER_FILL_UNBUDGETED not in rig.client.trading_refusals
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_same_day_paths_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Golden: a same-day accept-fill trues up the booking and never latches
    UNBUDGETED; a same-day zero-fill releases the spend, restores the permit
    slot and clears the refusal."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with _accept_fill_caps():
        await rig.client._connect()
        current, context, now_ns = await _arm_booked_ambiguous(rig, "ord-dr-gold-fill", sender)
        rig.client._resolved_by_get_ts_ns[current.intent_id] = now_ns
        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), rig.instrument, now_ns,
        )
        assert client_module._RESOLVER_FILL_UNBUDGETED not in rig.client.trading_refusals
        assert rig.client._ledger.spent_today_usd(now_ns=now_ns) == Decimal("0.37")
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_same_day_zero_fill_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with _accept_fill_caps():
        await rig.client._connect()
        current, context, now_ns = await _arm_booked_ambiguous(rig, "ord-dr-gold-zero", sender)
        _, count_before = live_trading_budget_remaining(rig.client._permit)
        rig.client._resolved_by_get_ts_ns[current.intent_id] = now_ns
        rig.client._resolve_terminal_zero(context, now_ns)
        assert rig.client._ledger.spent_today_usd(now_ns=now_ns) == Decimal(0)
        _, count_after = live_trading_budget_remaining(rig.client._permit)
        assert count_after == count_before + 1
        assert submit_chain.AMBIGUOUS_REASON not in rig.client.trading_refusals
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_later_same_day_authorize_after_skip_raises_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    with _accept_fill_caps():
        await rig.client._connect()
        current, context, now_ns = await _arm_booked_ambiguous(rig, "ord-dr-prune", sender)
        next_day_ns = now_ns + _DAY_NS
        rig.client._resolved_by_get_ts_ns[current.intent_id] = next_day_ns
        rig.client._resolve_terminal_zero(context, next_day_ns)

        booking = rig.client._ledger.authorize_order_cost(
            price_usd=Decimal("0.37"), quantity=Decimal(1), now_ns=next_day_ns + 1,
        )

        assert booking.day == utc_day_for_ns(next_day_ns)
        assert rig.client._ledger.spent_today_usd(now_ns=next_day_ns + 1) == Decimal("0.37")
        await rig.client._disconnect()
