"""R-7 submit-order chain: wired, denying, structurally unreachable POST.

RED tests named in ``docs/plans/R7_BUILD_BRIEF_2026-09-04.md`` §6 as amended
by the converged peer review. The only route any test reaches a POST is the
single ``write_canonical_verified`` monkeypatch fixture below.
"""

from __future__ import annotations

import ast
import json
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderDenied, OrderFilled, OrderRejected, OrderSubmitted
from nautilus_trader.model.identifiers import ClientId, StrategyId, TraderId
from nautilus_trader.model.objects import Quantity

from breezy.adapters.polymarket_us import write_transport
from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.exec.submit_chain import ORDER_BODY_KEYS, encode_order_body
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
)
from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntentState,
    open_submit_intent_latch,
)
from tests.unit.operator_control_env import operator_control_env, operator_control_unset
from tests.unit.polymarket_us_exec_shapes import (
    TS_EVENT_TEXT,
    build_execution,
    build_instrument,
    build_order,
)
from tests.unit.test_polymarket_us_permit_issuance import credentials, enable_operator_gate
from tests.unit.test_polymarket_us_readonly_guard import iter_python_sources

TRADER_ID: Final[TraderId] = TraderId("BREEZY-R7-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("WEATHER-001")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
ACCOUNT_NUMBER: Final[str] = "001"
TS_INIT: Final[int] = 1_787_617_213_000_000_000
BALANCE_TOTAL: Final[Decimal] = Decimal("125.50")
BALANCE_FREE: Final[Decimal] = Decimal("120.25")


@pytest.fixture
def write_canonical_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ONE monkeypatch that makes WRITE_CANONICAL_STRING_VERIFIED True."""
    monkeypatch.setattr(write_transport, "WRITE_CANONICAL_STRING_VERIFIED", True)


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
    def __init__(self, payloads: dict[str, Any]) -> None:
        self._payloads = payloads
        self.paths: list[str] = []

    async def __call__(self, path: str) -> Mapping[str, Any]:
        self.paths.append(path)
        return self._payloads[path]


class _FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = VenueResponse(status=200, headers={}, body=b"{}")
        self.error: BaseException | None = None

    async def post_order(
        self, base_url: str, *, headers: Mapping[str, str], body: bytes
    ) -> VenueResponse:
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        if self.error is not None:
            raise self.error
        return self.response


class _FakeSigner:
    def sign_headers(self, method: str, path: str, **_kwargs: object) -> list[tuple[str, str]]:
        return [("X-Test-Method", method), ("X-Test-Path", path)]


class _BoomStore:
    def __init__(self, inner: SqliteStateStore) -> None:
        self._inner = inner

    def get(self, key: str) -> bytes | None:
        return self._inner.get(key)

    def set(self, key: str, value: bytes) -> None:
        if "intent" in key:
            raise RuntimeError("state store raised before the post")
        self._inner.set(key, value)

    def close(self) -> None:
        self._inner.close()


def _durable_accept_body(
    slug: str, *, commission: str = "0.03", last_px: str = "0.37"
) -> bytes:
    order = build_order(slug)
    order["id"] = "ord-r7-1"
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
    return json.dumps({"id": "ord-r7-1", "executions": [execution]}).encode("utf-8")


def _status_reject_body() -> bytes:
    return json.dumps({"code": 3, "message": "invalid", "details": []}).encode("utf-8")


class _ChainRig:
    def __init__(
        self,
        *,
        client: PolymarketUSExecutionClient,
        sender: _FakeSender,
        order_events: list[Any],
        instrument: Any,
        clock: LiveClock,
        tmp_path: Path,
    ) -> None:
        self.client = client
        self.sender = sender
        self.order_events = order_events
        self.instrument = instrument
        self.clock = clock
        self.tmp_path = tmp_path

    def limit_buy(
        self,
        *,
        quantity: int = 1,
        price: str = "0.37",
        tif: TimeInForce = TimeInForce.IOC,
        side: OrderSide = OrderSide.BUY,
        order_type: str = "limit",
    ) -> SubmitOrder:
        factory = OrderFactory(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            clock=self.clock,
        )
        qty = Quantity(quantity, self.instrument.size_precision)
        from nautilus_trader.model.objects import Price

        if order_type == "market":
            order = factory.market(
                instrument_id=self.instrument.id,
                order_side=side,
                quantity=qty,
                time_in_force=tif,
            )
        else:
            order = factory.limit(
                instrument_id=self.instrument.id,
                order_side=side,
                quantity=qty,
                price=Price.from_str(price),
                time_in_force=tif,
            )
        return SubmitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            order=order,
            command_id=UUID4(),
            ts_init=TS_INIT,
        )


def _build_chain_rig(
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
    sender: _FakeSender | None = None,
    permit: object | None = ...,
    ledger: DailySpendLedger | None = None,
    latch: Any = ...,
    caps: tuple[str, str] | None = ("1000.00", "10.00"),
    enable_gate: bool = True,
) -> _ChainRig:
    loop = __import__("asyncio").get_running_loop()
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

    def _on_account_state(state: Any) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)
    msgbus.register(endpoint="ExecEngine.process", handler=order_events.append)

    store_path = tmp_path / "exec_state.db"
    fake_sender = sender if sender is not None else _FakeSender()
    if enable_gate:
        enable_operator_gate(monkeypatch)
    issued_permit: object | None
    if permit is ...:
        issued_permit = issue_live_trading_permit(clock=clock) if enable_gate else None
    else:
        issued_permit = permit

    if latch is ...:
        # The composition root's shape: a SEPARATE `SqliteStateStore` handle
        # from the one `state_store_opener` below builds for the client's
        # own `_open_state_store` -- the same duplication
        # `breezy.app.trade.run` has, and for the same reason (see its
        # module docstring). Opened, never exited: this rig's flock lives
        # for the test process, exactly as a real composition root's does
        # for the trading process.
        submit_intent_latch = open_submit_intent_latch(
            SqliteStateStore(store_path), store_path
        ).__enter__()
    else:
        submit_intent_latch = latch
    spend = ledger if ledger is not None else DailySpendLedger()
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
        write_signer=_FakeSigner(),
        live_trading_permit=issued_permit,
        spend_ledger=spend,
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
    )
    return _ChainRig(
        client=client,
        sender=fake_sender,
        order_events=order_events,
        instrument=instrument,
        clock=clock,
        tmp_path=tmp_path,
    )


@contextmanager
def _caps(daily: str, position: str) -> Iterator[None]:
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, daily),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, position),
    ):
        yield


# ---------------------------------------------------------------------------
# §6 named tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_submit_with_a_granted_authorization_dispatches_and_generates_order_submitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_durable_accept_body(str(build_instrument().raw_symbol)),
    )
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert len(sender.calls) == 1
    submitted = [e for e in rig.order_events if isinstance(e, OrderSubmitted)]
    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(submitted) == 1
    assert len(filled) == 1


@pytest.mark.asyncio
async def test_the_chain_denies_when_the_enablement_control_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(
            tmp_path,
            monkeypatch=monkeypatch,
            sender=sender,
            permit=None,
            enable_gate=False,
        )
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert sender.calls == []
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert len(denials) == 1
    assert "permit" in denials[0].reason.lower()


@pytest.mark.parametrize("which", ["daily", "position"])
@pytest.mark.asyncio
async def test_the_chain_denies_when_either_operator_cap_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
    which: str,
) -> None:
    sender = _FakeSender()
    daily_cm = (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR)
        if which == "daily"
        else operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00")
    )
    position_cm = (
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR)
        if which == "position"
        else operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00")
    )
    with daily_cm, position_cm:
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert sender.calls == []
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert len(denials) == 1


@pytest.mark.asyncio
async def test_the_chain_denies_when_the_daily_ledger_is_exhausted_and_issues_no_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    ledger = DailySpendLedger()
    with _caps("0.10", "10.00"):
        rig = _build_chain_rig(
            tmp_path, monkeypatch=monkeypatch, sender=sender, ledger=ledger
        )
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy(price="0.37"))
        await rig.client._disconnect()
    assert sender.calls == []
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert len(denials) == 1


@pytest.mark.asyncio
async def test_a_latch_left_open_by_a_prior_crash_refuses_every_submit_until_cleared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    store_path = tmp_path / "exec_state.db"
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as latch:
        latch.arm("a" * 64, now_ns=TS_INIT)
    store.close()
    sender = _FakeSender()
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert sender.calls == []
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert len(denials) == 1
    assert "latch" in denials[0].reason.lower()


@pytest.mark.asyncio
async def test_no_post_is_reachable_while_the_write_canonical_string_is_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert write_transport.WRITE_CANONICAL_STRING_VERIFIED is False
    sender = _FakeSender()
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert sender.calls == []
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert len(denials) == 1
    assert "canonical" in denials[0].reason.lower()

    setattr_hits: list[str] = []
    for path, source in iter_python_sources(("tests",)):
        if "WRITE_CANONICAL_STRING_VERIFIED" not in source:
            continue
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "setattr":
                continue
            dumped = ast.dump(node)
            if "WRITE_CANONICAL_STRING_VERIFIED" in dumped:
                setattr_hits.append(path)
    assert setattr_hits == ["tests/unit/test_polymarket_us_submit_order_chain.py"]


@pytest.mark.asyncio
async def test_a_second_arm_within_one_process_is_refused_and_issues_no_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    sender.response = VenueResponse(status=503, headers={}, body=b"{}")
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        first_posts = len(sender.calls)
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert len(sender.calls) == first_posts == 1
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert denials


@pytest.mark.asyncio
async def test_a_4xx_with_a_status_body_and_no_order_id_retires_and_releases_the_booking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    sender.response = VenueResponse(status=400, headers={}, body=_status_reject_body())
    ledger = DailySpendLedger()
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(
            tmp_path, monkeypatch=monkeypatch, sender=sender, ledger=ledger
        )
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        spent = ledger.spent_today_usd(now_ns=rig.clock.timestamp_ns())
        current = rig.client._latch.current()  # type: ignore[union-attr]
        await rig.client._disconnect()
    assert sender.calls
    rejected = [e for e in rig.order_events if isinstance(e, OrderRejected)]
    assert rejected
    assert spent == Decimal(0)
    assert current is None or current.state is SubmitIntentState.RETIRED


@pytest.mark.parametrize(
    "response",
    [
        ("status", VenueResponse(status=503, headers={}, body=b"{}")),
        ("transport", None),
        ("cancelled", None),
        (
            "200-id-no-exec",
            VenueResponse(
                status=200,
                headers={},
                body=json.dumps({"id": "ord-amb", "executions": []}).encode(),
            ),
        ),
        (
            "4xx-with-id",
            VenueResponse(
                status=400,
                headers={},
                body=json.dumps(
                    {"code": 3, "message": "x", "details": [], "id": "ord-amb"}
                ).encode(),
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
    response: tuple[str, VenueResponse | None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    kind, payload = response
    sender = _FakeSender()
    if kind == "transport":
        from breezy.adapters.polymarket_us.errors import VenueTransportError

        sender.error = VenueTransportError("POST failed at the transport layer")
    elif kind == "cancelled":
        sender.error = __import__("asyncio").CancelledError()
    elif payload is not None:
        sender.response = payload
    ledger = DailySpendLedger()
    caplog.set_level("ERROR")
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(
            tmp_path, monkeypatch=monkeypatch, sender=sender, ledger=ledger
        )
        await rig.client._connect()
        if kind == "cancelled":
            with pytest.raises(__import__("asyncio").CancelledError):
                await rig.client._submit_order(rig.limit_buy())
        else:
            await rig.client._submit_order(rig.limit_buy())
        spent = ledger.spent_today_usd(now_ns=rig.clock.timestamp_ns())
        current = rig.client._latch.current()  # type: ignore[union-attr]
        await rig.client._disconnect()
    assert spent > Decimal(0)
    assert current is not None and current.state is SubmitIntentState.OPEN
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "X-PM-Signature" not in joined
    assert "X-PM-Access-Key" not in joined
    assert "nonce" not in joined.lower()


@pytest.mark.asyncio
async def test_a_raising_state_store_before_the_post_means_no_post_occurs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()

    class _BoomLatch:
        #: Bound at class-definition time, inside this test function, so it
        #: is this test's own thread -- the same shape
        #: `SubmitIntentLatch.opening_thread_ident` records for a real one.
        opening_thread_ident = threading.get_ident()

        def arm(self, fingerprint: str, *, now_ns: int) -> object:
            raise RuntimeError("state store raised before the post")

        def retire(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("retire must not run")

        def current(self) -> None:
            return None

        def reconcile_at_startup(self, **_kwargs: object) -> None:
            return None

    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(
            tmp_path,
            monkeypatch=monkeypatch,
            sender=sender,
            latch=_BoomLatch(),
        )
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert sender.calls == []


@pytest.mark.asyncio
async def test_reconcile_at_startup_runs_before_the_first_arm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        rig.client._intent_reconciled = False  # type: ignore[attr-defined]
        # Skip connect; plant an account so the account-gate is not the denial.
        await rig.client._connect()
        rig.client._intent_reconciled = False  # type: ignore[attr-defined]
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    assert sender.calls == []
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert denials
    assert "reconcile" in denials[0].reason.lower()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tif": TimeInForce.GTC},
        {"side": OrderSide.SELL},
        {"quantity": 2},
        {"order_type": "market"},
        {"price": "0.00"},
        {"price": "1.00"},
    ],
)
@pytest.mark.asyncio
async def test_a_non_ioc_or_non_buy_or_multi_contract_order_is_refused_before_any_body_is_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
    kwargs: dict[str, Any],
) -> None:
    sender = _FakeSender()
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy(**kwargs))
        await rig.client._disconnect()
    assert sender.calls == []
    denials = [e for e in rig.order_events if isinstance(e, OrderDenied)]
    assert denials


@pytest.mark.asyncio
async def test_the_order_body_matches_the_venue_schema_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    sender.response = VenueResponse(status=503, headers={}, body=b"{}")
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy(price="0.37"))
        await rig.client._disconnect()
    assert sender.calls
    body = json.loads(sender.calls[0]["body"].decode("utf-8"))
    assert set(body) == ORDER_BODY_KEYS
    assert isinstance(body["price"]["value"], str)
    assert body["price"]["value"] == "0.37"
    assert body["price"]["currency"] == "USD"
    assert isinstance(body["quantity"], (int, float))
    assert body["quantity"] == 1
    assert body["type"] == "ORDER_TYPE_LIMIT"
    assert body["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
    assert body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert body["action"] == "ORDER_ACTION_BUY"
    encode_order_body(body)


@pytest.mark.asyncio
async def test_a_fill_report_is_never_built_without_a_venue_order_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    slug = str(build_instrument().raw_symbol)
    order = build_order(slug)
    order.pop("id", None)
    execution = build_execution(order)
    execution["tradeId"] = "trd-1"
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=json.dumps({"id": "ord-top", "executions": [execution]}).encode(),
    )
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert filled == []


@pytest.mark.asyncio
async def test_the_commission_booked_is_the_measured_venue_number_not_the_modelled_fee(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_durable_accept_body(str(build_instrument().raw_symbol), commission="0.11"),
    )
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()
    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(filled) == 1
    assert filled[0].commission == __import__(
        "nautilus_trader.model.objects", fromlist=["Money"]
    ).Money(Decimal("0.11"), USD)


def test_no_post_is_reachable_scan_finds_exactly_one_monkeypatch_fixture() -> None:
    """Structural half of test 6: one setattr fixture, no second construction path."""
    hits = []
    for path, source in iter_python_sources(("tests",)):
        if "setattr" in source and "WRITE_CANONICAL_STRING_VERIFIED" in source:
            hits.append(path)
    assert hits == ["tests/unit/test_polymarket_us_submit_order_chain.py"]
