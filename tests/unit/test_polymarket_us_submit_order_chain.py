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
from nautilus_trader.model.identifiers import ClientId, StrategyId, TradeId, TraderId
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us import write_transport
from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.exec.submit_chain import (
    KIND_ACCEPT_FILL,
    KIND_AMBIGUOUS,
    KIND_REJECT,
    KIND_ZERO_FILL,
    ORDER_BODY_KEYS,
    classify_create_order_outcome,
    encode_order_body,
    fill_generation,
)
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
    ACCOUNT_ID,
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


@pytest.fixture
def write_canonical_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    """The companion monkeypatch that pins WRITE_CANONICAL_STRING_VERIFIED
    False for refusal tests, now that the module default is True (C5, the
    OP-4 positive-control flip). This module remains the ONE place allowed
    to set the attribute -- see ``setattr_hits`` below.
    """
    monkeypatch.setattr(write_transport, "WRITE_CANONICAL_STRING_VERIFIED", False)


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
    def __init__(self, payloads: dict[str, Mapping[str, Any]]) -> None:
        self._payloads: dict[str, Mapping[str, Any]] = payloads
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
        latch_cm: Any = None,
    ) -> None:
        self.client = client
        self.sender = sender
        self.order_events = order_events
        self.instrument = instrument
        self.clock = clock
        self.tmp_path = tmp_path
        # Keeps the `open_submit_intent_latch` generator-CM ALIVE for the
        # rig's lifetime. Discarding the CM object (keeping only its
        # `__enter__()` return value) drops its last reference, and CPython
        # then finalises the generator via `GeneratorExit` -- which runs the
        # `finally: lock.release()` inside `hold_submit_intent_process_lock`
        # and silently drops the flock mid-test. Never exited on purpose
        # (see `_build_chain_rig`): this rig's flock lives for the test,
        # exactly as a real composition root's lives for the process.
        self._latch_cm = latch_cm

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

    latch_cm: Any = None
    if latch is ...:
        # The composition root's shape: a SEPARATE `SqliteStateStore` handle
        # from the one `state_store_opener` below builds for the client's
        # own `_open_state_store` -- the same duplication
        # `breezy.app.trade.run` has, and for the same reason (see its
        # module docstring). Opened, never exited: this rig's flock lives
        # for the test process, exactly as a real composition root's does
        # for the trading process. `latch_cm` is retained on `_ChainRig`
        # (below) so the generator-CM is not garbage-collected mid-test --
        # see `_ChainRig.__init__`'s docstring comment for why that matters.
        latch_cm = open_submit_intent_latch(SqliteStateStore(store_path), store_path)
        submit_intent_latch = latch_cm.__enter__()
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
        latch_cm=latch_cm,
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


def _find_write_transport_canonical_setattr_sites() -> list[str]:
    """Files with an AST ``setattr(<any target>, "WRITE_CANONICAL_STRING_VERIFIED", ...)``.

    Any-target, restored exactly to the original scan shape (L-12: a
    barrier's scan scope is never narrowed, even when the narrower form
    "feels" equivalent -- only the allowed-file SET may widen, and only with
    evidence for each addition). Per-FILE, not per-call, so that this
    module's two fixtures (``write_canonical_verified`` /
    ``write_canonical_unverified``) collapse to one entry rather than two.
    """
    hits: list[str] = []
    for path, source in iter_python_sources(("tests",)):
        if "WRITE_CANONICAL_STRING_VERIFIED" not in source:
            continue
        tree = ast.parse(source, filename=path)
        file_hit = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "setattr":
                continue
            dumped = ast.dump(node)
            if "WRITE_CANONICAL_STRING_VERIFIED" in dumped:
                file_hit = True
        if file_hit:
            hits.append(path)
    return hits


@pytest.mark.asyncio
async def test_no_post_is_reachable_while_the_write_canonical_string_is_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_unverified: None,
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

    # Widened (never loosened): the factories test patches
    # `factories_module`'s own from-imported binding to prove `order_sender`
    # wiring in both directions; the `write_transport` attribute itself is
    # still moved only by this module's two fixtures.
    assert _find_write_transport_canonical_setattr_sites() == [
        "tests/unit/test_polymarket_us_factories.py",
        "tests/unit/test_polymarket_us_submit_order_chain.py",
    ]


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
        current = rig.client._latch.current()
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
        current = rig.client._latch.current()
        await rig.client._disconnect()
    assert spent > Decimal(0)
    assert current is not None and current.state is SubmitIntentState.OPEN
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "X-PM-Signature" not in joined
    assert "X-PM-Access-Key" not in joined
    assert "nonce" not in joined.lower()


def test_ambiguous_exception_path_source_logs_the_exception_type_never_its_str() -> None:
    """The DEFECT: the exception path logged only the constant reason, with no
    way to tell which exception fired or what it said. Nautilus's own Cython
    ``self._log`` is not stdlib ``logging``, so ``caplog`` cannot observe it
    dynamically -- see ``test_shadow_log_line_names_the_permit_gate`` in
    ``test_current_rung_hold_strategy.py`` for the same, already-established
    limitation in this codebase. The source text is the reliable check that
    the exception's TYPE is now logged, and that its ``str`` -- which may
    embed a secret-shaped URL or header -- never is."""
    import inspect

    source = inspect.getsource(PolymarketUSExecutionClient._submit_order)
    start = source.index("response = await self._order_sender.post_order(")
    end = source.index("outcome = submit_chain.classify_create_order_outcome(")
    exception_block = source[start:end]
    assert "path=exception" in exception_block
    assert "exc_type={exc.__class__.__name__}" in exception_block
    assert "client_order_id=" in exception_block
    assert "{exc}" not in exception_block
    assert "str(exc)" not in exception_block


def test_ambiguous_classified_path_source_logs_the_venues_shape_not_its_body() -> None:
    """The DEFECT: the classifier's AMBIGUOUS path logged only the constant
    reason -- never the response status, the ``google.rpc.Status`` code, or
    the body length. Source-text check for the same reason as above: the
    residual AMBIGUOUS branch (the LAST ``self._refuse(AMBIGUOUS_REASON)`` in
    the method -- the first is the exception path above) now logs
    ``outcome.detail``, which ``classify_create_order_outcome`` computes as a
    redacted status/shape/rpc-code/length summary
    (``test_classify_ambiguous_status_body_off_the_4xx_range_reports_rpc_code_and_length``
    pins its exact value for a 503 with a Status body)."""
    import inspect

    source = inspect.getsource(PolymarketUSExecutionClient._submit_order)
    classified_block = source[source.rindex("self._refuse(submit_chain.AMBIGUOUS_REASON)") :]
    assert "path=classified" in classified_block
    assert "outcome.detail" in classified_block
    assert "client_order_id=" in classified_block


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
        rig.client._intent_reconciled = False
        # Skip connect; plant an account so the account-gate is not the denial.
        await rig.client._connect()
        rig.client._intent_reconciled = False
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
    assert filled[0].commission == Money(Decimal("0.11"), USD)


def test_fill_generation_books_sub_cent_commission() -> None:
    instrument = build_instrument()
    execution = build_execution(build_order(str(instrument.raw_symbol)))
    execution["commissionNotionalCollected"] = {"value": "0.004", "currency": "USD"}
    result = fill_generation(
        execution, instrument=instrument, account_id=ACCOUNT_ID, ts_init=TS_INIT
    )
    assert result is not None
    assert result.commission == Money(0, USD)
    assert result.commission_raw == "0.004"


def test_fill_generation_returns_none_for_pathological_commission() -> None:
    instrument = build_instrument()
    execution = build_execution(build_order(str(instrument.raw_symbol)))
    execution["commissionNotionalCollected"] = {
        "value": "1E+999999",
        "currency": "USD",
    }
    assert (
        fill_generation(
            execution, instrument=instrument, account_id=ACCOUNT_ID, ts_init=TS_INIT
        )
        is None
    )


def test_fill_generation_books_numeric_sub_cent_commission() -> None:
    instrument = build_instrument()
    execution = build_execution(build_order(str(instrument.raw_symbol)))
    execution["commissionNotionalCollected"] = {"value": 0.004, "currency": "USD"}
    result = fill_generation(
        execution, instrument=instrument, account_id=ACCOUNT_ID, ts_init=TS_INIT
    )
    assert result is not None
    assert result.commission == Money(0, USD)
    assert result.commission_raw == str(0.004)


def test_classify_create_order_outcome_books_a_sub_cent_fill() -> None:
    slug = str(build_instrument().raw_symbol)
    response = VenueResponse(
        status=200,
        headers={},
        body=_durable_accept_body(slug, commission="0.004"),
    )
    outcome = classify_create_order_outcome(
        response,
        instrument=build_instrument(),
        account_id=ACCOUNT_ID,
        ts_init=TS_INIT,
    )
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fill is not None
    assert outcome.fill.commission == Money(0, USD)
    assert outcome.fill.commission_raw == "0.004"
    assert outcome.cumulative_fee == Decimal("0.004")


@pytest.mark.asyncio
async def test_a_sub_cent_venue_fee_is_booked_as_bankers_zero_with_raw_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> None:
    sender = _FakeSender()
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_durable_accept_body(str(build_instrument().raw_symbol), commission="0.004"),
    )
    with _caps("1000.00", "10.00"):
        rig = _build_chain_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        records = rig.client.fill_records_for(rig.instrument.id)
        await rig.client._disconnect()
    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(filled) == 1
    assert filled[0].commission == Money(0, USD)
    assert len(records) == 1
    assert records[0].venue_fee_raw == "0.004"
    assert records[0].cumulative_fee == Decimal("0.004")


def test_no_post_is_reachable_scan_finds_exactly_one_monkeypatch_fixture() -> None:
    """Structural half of test 6: one module may setattr the flag the exec
    chain actually reads; a second construction path is refused.
    """
    # Widened (never loosened): the factories test patches
    # `factories_module`'s own from-imported binding to prove `order_sender`
    # wiring in both directions; the `write_transport` attribute itself is
    # still moved only by this module's two fixtures.
    assert _find_write_transport_canonical_setattr_sites() == [
        "tests/unit/test_polymarket_us_factories.py",
        "tests/unit/test_polymarket_us_submit_order_chain.py",
    ]


# ---------------------------------------------------------------------------
# I1a -- order-level totals on the classified outcome
# (docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md, section "I1a")
#
# These fixtures are stated schema-shaped from the SDK/OpenAPI snapshots
# (``types/orders.py:70-108``; ``docs_snapshots/api-reference_orders_create-
# order_2026-08-25.md``) -- NO recorded 200 body exists for a multi-leg fill,
# so nothing here is a captured response. Every execution's embedded "order"
# is the SAME final snapshot: the synchronous-execution create-order call
# resolves the whole order lifecycle in one round trip, so by the time the
# response is serialized every leg carries the terminal order state, never a
# stale intermediate one.
# ---------------------------------------------------------------------------


def _i1a_order(
    slug: str,
    *,
    cum_quantity: str | None,
    avg_px: str | None,
    commission_total: str | None,
) -> dict[str, Any]:
    order = build_order(slug)
    order["id"] = "ord-i1a"
    order["quantity"] = 1
    order["leavesQuantity"] = 0
    order["state"] = "ORDER_STATE_FILLED"
    if cum_quantity is None:
        order.pop("cumQuantity", None)
    else:
        order["cumQuantity"] = cum_quantity
    if avg_px is None:
        order.pop("avgPx", None)
    else:
        order["avgPx"] = {"value": avg_px, "currency": "USD"}
    if commission_total is not None:
        order["commissionNotionalTotalCollected"] = {
            "value": commission_total,
            "currency": "USD",
        }
    return order


def _i1a_leg(
    order: dict[str, Any],
    *,
    exec_id: str,
    trade_id: str,
    last_shares: str,
    last_px: str,
    commission: str | None,
    exec_type: str | None = "EXECUTION_TYPE_FILL",
) -> dict[str, Any]:
    execution = build_execution(order)
    execution["id"] = exec_id
    execution["tradeId"] = trade_id
    execution["lastShares"] = last_shares
    execution["lastPx"] = {"value": last_px, "currency": "USD"}
    if commission is None:
        execution.pop("commissionNotionalCollected", None)
    else:
        execution["commissionNotionalCollected"] = {"value": commission, "currency": "USD"}
    if exec_type is None:
        execution.pop("type", None)
    else:
        execution["type"] = exec_type
    return execution


def _classify_i1a(executions: list[dict[str, Any]]) -> Any:
    body = json.dumps({"id": "ord-i1a", "executions": executions}).encode("utf-8")
    response = VenueResponse(status=200, headers={}, body=body)
    return classify_create_order_outcome(
        response,
        instrument=build_instrument(),
        account_id=ACCOUNT_ID,
        ts_init=TS_INIT,
    )


def test_i1a_multi_leg_fill_totals_are_order_level() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.414", commission_total="0.05")
    leg_a = _i1a_leg(
        order,
        exec_id="exe-a",
        trade_id="trd-a",
        last_shares="0.6",
        last_px="0.41",
        commission="0.03",
    )
    leg_b = _i1a_leg(
        order,
        exec_id="exe-b",
        trade_id="trd-b",
        last_shares="0.4",
        last_px="0.42",
        commission="0.02",
    )
    outcome = _classify_i1a([leg_a, leg_b])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.cumulative_qty == Decimal(1)
    assert outcome.cumulative_cost == Decimal("0.414")
    assert outcome.cumulative_fee == Decimal("0.05")
    assert outcome.fee_reconciled is True


def test_i1a_a_canceled_row_with_a_stale_commission_is_ignored() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.41", commission_total=None)
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.41",
        commission="0.03",
    )
    stale_cancel = _i1a_leg(
        order,
        exec_id="exe-2",
        trade_id="trd-2",
        last_shares="0",
        last_px="0.41",
        commission="0.99",
        exec_type="EXECUTION_TYPE_CANCELED",
    )
    outcome = _classify_i1a([fill_leg, stale_cancel])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.cumulative_fee == Decimal("0.03")
    assert outcome.fee_reconciled is True


def test_a_stale_canceled_row_before_the_real_fill_is_never_durably_selected() -> None:
    """Guards the I1b durable-execution selection, not just the I1a fee sum.

    A CANCELED row that happens to carry ``lastPx``/``lastShares``/``tradeId``
    and is LISTED BEFORE the real FILL row must never be the execution
    ``_durable_execution`` hands to ``fill_generation``/``_cumulative_*`` --
    only ``EXECUTION_TYPE_FILL``/``EXECUTION_TYPE_PARTIAL_FILL`` rows qualify.
    """
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.41", commission_total=None)
    stale_cancel = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-stale",
        last_shares="1",
        last_px="0.99",
        commission="0.99",
        exec_type="EXECUTION_TYPE_CANCELED",
    )
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-2",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.41",
        commission="0.03",
    )
    outcome = _classify_i1a([stale_cancel, fill_leg])
    baseline = _classify_i1a([fill_leg])

    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fill is not None
    assert outcome.fill.trade_id == TradeId("trd-1")
    assert outcome.fill.last_px == Price.from_str("0.41")
    assert outcome.cumulative_qty == baseline.cumulative_qty == Decimal(1)
    assert outcome.cumulative_cost == baseline.cumulative_cost == Decimal("0.41")
    assert outcome.cumulative_fee == baseline.cumulative_fee == Decimal("0.03")
    assert outcome.fee_reconciled is baseline.fee_reconciled is True


def test_an_untyped_row_before_the_real_fill_is_never_durably_selected() -> None:
    """Same guard as above for a row carrying NO ``type`` at all (I1a's other
    excluded case), listed before the real FILL row."""
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.41", commission_total=None)
    stale_untyped = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-stale",
        last_shares="1",
        last_px="0.99",
        commission="0.99",
        exec_type=None,
    )
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-2",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.41",
        commission="0.03",
    )
    outcome = _classify_i1a([stale_untyped, fill_leg])
    baseline = _classify_i1a([fill_leg])

    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fill is not None
    assert outcome.fill.trade_id == TradeId("trd-1")
    assert outcome.cumulative_qty == baseline.cumulative_qty == Decimal(1)
    assert outcome.cumulative_cost == baseline.cumulative_cost == Decimal("0.41")
    assert outcome.cumulative_fee == baseline.cumulative_fee == Decimal("0.03")
    assert outcome.fee_reconciled is baseline.fee_reconciled is True


def test_executions_with_only_non_fill_rows_are_ambiguous_not_accept_fill() -> None:
    """A non-empty ``executions`` list holding only CANCELED/untyped rows has
    no durable fill execution. It also fails the KIND_ZERO_FILL predicate
    (that requires ``executions == []``), so the residual is KIND_AMBIGUOUS --
    never KIND_ACCEPT_FILL on a stale row's data."""
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="0", avg_px=None, commission_total=None)
    stale_cancel = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-stale",
        last_shares="1",
        last_px="0.99",
        commission="0.99",
        exec_type="EXECUTION_TYPE_CANCELED",
    )
    outcome = _classify_i1a([stale_cancel])
    assert outcome.kind == KIND_AMBIGUOUS
    assert outcome.fill is None
    assert outcome.cumulative_qty is None
    assert outcome.cumulative_cost is None
    assert outcome.cumulative_fee is None
    assert outcome.fee_reconciled is False


def test_classify_ambiguous_with_no_response_reports_a_none_shaped_detail() -> None:
    """No response at all (the transport never returned one) -- every detail
    field is the ``none`` sentinel, never a guess."""
    outcome = classify_create_order_outcome(
        None, instrument=build_instrument(), account_id=ACCOUNT_ID, ts_init=1
    )
    assert outcome.kind == KIND_AMBIGUOUS
    assert outcome.detail == "status=none body_kind=none rpc_code=none body_len=0"


def test_classify_ambiguous_status_body_off_the_4xx_range_reports_rpc_code_and_length() -> None:
    """A ``google.rpc.Status`` body at a status the classifier's REJECT branch
    does not cover (503, not 4xx) falls through to AMBIGUOUS. The detail
    reports the venue's actual answer -- status, shape, its rpc code, and the
    body length -- never the body content itself."""
    body = _status_reject_body()
    response = VenueResponse(status=503, headers={}, body=body)
    outcome = classify_create_order_outcome(
        response, instrument=build_instrument(), account_id=ACCOUNT_ID, ts_init=1
    )
    assert outcome.kind == KIND_AMBIGUOUS
    assert outcome.detail == (
        f"status=503 body_kind=status-no-order-id rpc_code=3 body_len={len(body)}"
    )


def test_classify_ambiguous_unparseable_body_reports_that_shape() -> None:
    response = VenueResponse(status=200, headers={}, body=b"not json")
    outcome = classify_create_order_outcome(
        response, instrument=build_instrument(), account_id=ACCOUNT_ID, ts_init=1
    )
    assert outcome.kind == KIND_AMBIGUOUS
    assert outcome.detail == (
        f"status=200 body_kind=unparseable rpc_code=none body_len={len(response.body)}"
    )


def test_i1a_order_total_mismatch_leaves_fee_unreconciled() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.41", commission_total="0.05")
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.41",
        commission="0.03",
    )
    outcome = _classify_i1a([fill_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fee_reconciled is False
    assert outcome.cumulative_fee == Decimal("0.05")


def test_i1a_exact_total_reconciles_on_the_exact_branch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.41", commission_total="0.03")
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.41",
        commission="0.03",
    )
    caplog.set_level("INFO", logger="breezy.adapters.polymarket_us.exec.submit_chain")
    outcome = _classify_i1a([fill_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fee_reconciled is True
    assert outcome.cumulative_fee == Decimal("0.03")
    assert "branch=exact" in caplog.text


def test_i1a_bankers_rounded_total_against_sub_cent_leg_is_reconciled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.37", commission_total="0.00")
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.37",
        commission="0.004",
    )
    caplog.set_level("INFO", logger="breezy.adapters.polymarket_us.exec.submit_chain")
    outcome = _classify_i1a([fill_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fee_reconciled is True
    assert outcome.cumulative_fee == Decimal("0.004")
    assert "branch=bankers" in caplog.text


def test_i1a_bankers_rounded_total_against_live_threat_leg_is_reconciled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.28", commission_total="0.01")
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.28",
        commission="0.012096",
    )
    caplog.set_level("INFO", logger="breezy.adapters.polymarket_us.exec.submit_chain")
    outcome = _classify_i1a([fill_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fee_reconciled is True
    assert outcome.cumulative_fee == Decimal("0.012096")
    assert "branch=bankers" in caplog.text


def test_i1a_order_total_far_from_leg_is_not_reconciled_via_bankers() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.37", commission_total="0.02")
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-1",
        trade_id="trd-1",
        last_shares="1",
        last_px="0.37",
        commission="0.004",
    )
    outcome = _classify_i1a([fill_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fee_reconciled is False
    assert outcome.cumulative_fee == Decimal("0.02")


def test_i1a_two_fill_legs_with_no_order_total_reconcile_on_the_leg_sum() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.415", commission_total=None)
    leg_a = _i1a_leg(
        order,
        exec_id="exe-a",
        trade_id="trd-a",
        last_shares="0.5",
        last_px="0.41",
        commission="0.02",
    )
    leg_b = _i1a_leg(
        order,
        exec_id="exe-b",
        trade_id="trd-b",
        last_shares="0.5",
        last_px="0.42",
        commission="0.02",
    )
    outcome = _classify_i1a([leg_a, leg_b])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.cumulative_fee == Decimal("0.04")
    assert outcome.fee_reconciled is True


def test_i1a_a_leg_with_no_type_is_never_summed_and_leaves_fee_unreconciled() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.41", commission_total=None)
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-a",
        trade_id="trd-a",
        last_shares="0.5",
        last_px="0.41",
        commission="0.02",
    )
    untyped_leg = _i1a_leg(
        order,
        exec_id="exe-b",
        trade_id="trd-b",
        last_shares="0.5",
        last_px="0.41",
        commission="0.02",
        exec_type=None,
    )
    outcome = _classify_i1a([fill_leg, untyped_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.fee_reconciled is False
    assert outcome.cumulative_fee == Decimal("0.02")


def test_i1a_a_dropped_leg_leaves_fee_unreconciled() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity="1", avg_px="0.41", commission_total=None)
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-a",
        trade_id="trd-a",
        last_shares="0.6",
        last_px="0.41",
        commission="0.03",
    )
    outcome = _classify_i1a([fill_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.cumulative_qty == Decimal(1)
    assert outcome.fee_reconciled is False
    assert outcome.cumulative_fee == Decimal("0.03")


def test_i1a_qty_and_cost_fall_back_together_when_the_order_lacks_avgpx_and_cumquantity() -> None:
    slug = str(build_instrument().raw_symbol)
    order = _i1a_order(slug, cum_quantity=None, avg_px=None, commission_total=None)
    fill_leg = _i1a_leg(
        order,
        exec_id="exe-a",
        trade_id="trd-a",
        last_shares="1",
        last_px="0.41",
        commission="0.03",
    )
    outcome = _classify_i1a([fill_leg])
    assert outcome.kind == KIND_ACCEPT_FILL
    assert outcome.cumulative_qty == Decimal(1)
    assert outcome.cumulative_cost == Decimal("0.41")
    assert outcome.fee_reconciled is True


def test_i1a_reject_and_zero_fill_outcomes_carry_no_cumulative_totals() -> None:
    reject_response = VenueResponse(status=400, headers={}, body=_status_reject_body())
    reject_outcome = classify_create_order_outcome(
        reject_response,
        instrument=build_instrument(),
        account_id=ACCOUNT_ID,
        ts_init=TS_INIT,
    )
    assert reject_outcome.kind == KIND_REJECT
    assert reject_outcome.cumulative_qty is None
    assert reject_outcome.cumulative_cost is None
    assert reject_outcome.cumulative_fee is None
    assert reject_outcome.fee_reconciled is False

    zero_body = json.dumps(
        {
            "id": "ord-i1a-zero",
            "executions": [],
            "state": "ORDER_STATE_CANCELED",
            "cumQuantity": 0,
        }
    ).encode("utf-8")
    zero_response = VenueResponse(status=200, headers={}, body=zero_body)
    zero_outcome = classify_create_order_outcome(
        zero_response,
        instrument=build_instrument(),
        account_id=ACCOUNT_ID,
        ts_init=TS_INIT,
    )
    assert zero_outcome.kind == KIND_ZERO_FILL
    assert zero_outcome.cumulative_qty is None
    assert zero_outcome.cumulative_cost is None
    assert zero_outcome.cumulative_fee is None
    assert zero_outcome.fee_reconciled is False
