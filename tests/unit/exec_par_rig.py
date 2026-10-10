"""Shared rig for the EXEC-PAR WP4 (exec-client parallel-slot wiring) suites.

Not a test module: a helper, in the shape of ``ambig_latch_rig.py``.

**It never imports the ``exec`` package itself.** Barrier X1
(``test_execution_egress_firewall_guard.exec_importing_test_modules``) pins, by
set EQUALITY, every test module that does; a new importer would be a widening
that WP4 is not licensed to make. Every ``exec`` symbol the suites need is
reached through the already-pinned ``test_polymarket_us_exec_client`` module
(which re-exports what it imports) or through the client class's own module.
The rig opens no socket: every sender and private read is a local double.

Operator caps: the rig reaches them only through
``tests/unit/operator_control_env`` (the single whitelisted seam); the values are
the same placeholders every sibling exec suite uses.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Self

import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus, TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import AccountState
from nautilus_trader.model.identifiers import ClientOrderId
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.persistence.exit_tags import (
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)
from breezy.persistence.family_manifest import FamilyManifest
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from tests.unit.ambig_latch_rig import _RecordingLog
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import (
    RAW,
    TS_INIT,
    build_instrument,
    build_second_instrument,
)
from tests.unit.test_polymarket_us_exec_client import (
    ACCOUNT_BALANCES_PATH,
    ACCOUNT_NUMBER,
    ARMED_EXIT_MANIFEST,
    CLIENT_ID,
    OPEN_ORDERS_PATH,
    PORTFOLIO_ACTIVITIES_PATH,
    PORTFOLIO_POSITIONS_PATH,
    STRATEGY_ID,
    TRADER_ID,
    AmbiguousResolverContext,
    DurableFillRecord,
    PolymarketUSExecutionClient,
    _accept_fill_body,
    _ambiguous_with_id_body,
    _balances_payload,
    _FakeOrderSender,
    _FakeWriteSigner,
    _PrivateReadStub,
    _reject_body,
    _YieldingOrderSender,
    _zero_fill_body,
    credentials,
    enable_operator_gate,
    submit_chain,
)
from tests.unit.test_polymarket_us_exec_client import client_module as _client_module

accept_fill_body = _accept_fill_body
ambiguous_body = _ambiguous_with_id_body
reject_body = _reject_body
zero_fill_body = _zero_fill_body
FakeOrderSender = _FakeOrderSender
YieldingOrderSender = _YieldingOrderSender

__all__ = [
    "ACCOUNT_BALANCES_PATH",
    "ARMED_EXIT_MANIFEST",
    "BASE_NS",
    "NEXT_MIDNIGHT_NS",
    "OPEN_ORDERS_PATH",
    "PORTFOLIO_ACTIVITIES_PATH",
    "PORTFOLIO_POSITIONS_PATH",
    "SEC_NS",
    "STRATEGY_ID",
    "AmbiguousResolverContext",
    "DurableFillRecord",
    "FakeOrderSender",
    "ParClient",
    "ParRig",
    "PolymarketUSExecutionClient",
    "RetirementReason",
    "YieldingOrderSender",
    "accept_fill_body",
    "ambiguous_body",
    "build_par_rig",
    "build_third_instrument",
    "caps",
    "client_module",
    "reject_body",
    "submit_chain",
    "zero_fill_body",
]

client_module: Final[Any] = _client_module

#: The label D-PREREG would freeze; any label at or above the rig's cap/budget
#: ratio (10 / 1000 = 0.01 -> "<=0.02") lets K > 1 stand.
PERMISSIVE_BUCKET: Final[str] = "0.25"


#: 2026-10-10T12:00:00Z -- the rig's deterministic "now". The permit (10 h TTL)
#: is issued against the same injected clock, so no test depends on wall time.
BASE_NS: Final[int] = 1_791_633_600_000_000_000
SEC_NS: Final[int] = 1_000_000_000
#: 2026-10-11T00:00:00Z, the next UTC midnight after :data:`BASE_NS`.
NEXT_MIDNIGHT_NS: Final[int] = BASE_NS + 12 * 3600 * SEC_NS


class SettableClock:
    """An absolute, test-controlled ``timestamp_ns`` (other attributes delegate)."""

    def __init__(self, inner: Any, now_ns: int) -> None:
        self._inner = inner
        self.now_ns = now_ns

    def timestamp_ns(self) -> int:
        return self.now_ns

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class RecordingStore:
    """A ``SqliteStateStore`` wrapper that appends every ``set`` to ``writes``."""

    def __init__(self, inner: Any, writes: list[tuple[str, bytes]]) -> None:
        self._inner = inner
        self.writes = writes

    def get(self, key: str) -> bytes | None:
        value: bytes | None = self._inner.get(key)
        return value

    def set(self, key: str, value: bytes) -> None:
        self.writes.append((key, value))
        self._inner.set(key, value)

    def close(self) -> None:
        self._inner.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._inner.close()


class ParClient(PolymarketUSExecutionClient):
    """The real client with a Python-visible settable clock and a recording log.

    ``Component._clock`` is a read-only Cython attribute, so (like
    ``ambig_latch_rig.TimedClient``) the property shadows it for every
    Python-level read; native code keeps the real clock.
    """

    @property
    def _clock(self) -> Any:
        wrapped = self.__dict__.get("_par_clock")
        if wrapped is None:
            base = PolymarketUSExecutionClient._clock.__get__(self)
            wrapped = SettableClock(base, BASE_NS)
            self.__dict__["_par_clock"] = wrapped
        return wrapped

    @property
    def _log(self) -> Any:
        wrapped = self.__dict__.get("_par_log")
        if wrapped is None:
            base = PolymarketUSExecutionClient._log.__get__(self)
            wrapped = _RecordingLog(base, self.log_records)
            self.__dict__["_par_log"] = wrapped
        return wrapped

    @property
    def log_records(self) -> list[tuple[str, str]]:
        records: list[tuple[str, str]] = self.__dict__.setdefault("_par_log_records", [])
        return records

    def log_lines(self, level: str, contains: str = "") -> list[str]:
        return [m for lv, m in self.log_records if lv == level and contains in m]

    @property
    def settable_clock(self) -> SettableClock:
        clock = self._clock
        assert isinstance(clock, SettableClock)
        return clock

    def set_now(self, ns: int) -> None:
        self.settable_clock.now_ns = ns

    def advance(self, seconds: float) -> None:
        self.settable_clock.now_ns += int(seconds * SEC_NS)


def build_third_instrument() -> Any:
    """A THIRD distinct slug: the open market with its slug text replaced.

    The captured markets give only two real slugs; K-full needs a third.
    """
    raw = json.loads((RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8"))
    text = (
        json.dumps(raw)
        .replace("lt79f", "lt86f")
        .replace("78F", "85F")
        .replace("78 or below", "85 or below")
        .replace("510636", "510699")
    )
    return parse_binary_option(json.loads(text), venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


@contextmanager
def caps() -> Iterator[None]:
    """The placeholder caps every sibling exec suite wraps its body in."""
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        yield


@dataclass
class ParRig:
    """A real client over a real store and latch, with a fake sender."""

    client: Any
    sender: Any
    order_events: list[Any]
    instruments: tuple[Any, ...]
    clock: Any
    latch: Any
    ledger: Any
    permit: Any
    store_path: Path
    latch_cm: Any
    read: Any
    factory: Any
    writes: list[tuple[str, bytes]]

    @property
    def instrument(self) -> Any:
        return self.instruments[0]

    def buy(self, instrument: Any | None = None, *, price: str = "0.37") -> SubmitOrder:
        target = self.instrument if instrument is None else instrument
        order = self.factory.limit(
            instrument_id=target.id,
            order_side=OrderSide.BUY,
            quantity=Quantity(1, target.size_precision),
            price=Price.from_str(price),
            time_in_force=TimeInForce.IOC,
        )
        self.client._cache.add_order(order, position_id=None)
        return SubmitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            order=order,
            command_id=UUID4(),
            ts_init=TS_INIT,
        )

    def exit_sell(
        self,
        instrument: Any | None = None,
        *,
        price: str = "0.37",
        client_order_id_value: str = "O-EXIT-1",
    ) -> SubmitOrder:
        target = self.instrument if instrument is None else instrument
        order = self.factory.limit(
            instrument_id=target.id,
            order_side=OrderSide.SELL,
            quantity=Quantity(1, target.size_precision),
            price=Price.from_str(price),
            time_in_force=TimeInForce.IOC,
            tags=[
                f"{EXIT_RULE_TAG_PREFIX}R_THREAT",
                f"{EXIT_POSITION_TAG_PREFIX}pos-exit-1",
                f"{EXIT_FAMILY_TAG_PREFIX}pm_us_crh_exit_v4",
                f"{EXIT_CLIENT_ORDER_ID_TAG_PREFIX}{client_order_id_value}",
            ],
            client_order_id=ClientOrderId(client_order_id_value),
        )
        self.client._cache.add_order(order, position_id=None)
        return SubmitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            order=order,
            command_id=UUID4(),
            ts_init=TS_INIT,
        )

    def denied_reasons(self) -> list[str]:
        return [e.reason for e in self.order_events if type(e).__name__ == "OrderDenied"]

    def events_named(self, name: str) -> list[Any]:
        return [e for e in self.order_events if type(e).__name__ == name]

    def open_intent_ids(self) -> tuple[str, ...]:
        return tuple(i.intent_id for i in self.latch.open_submit_intents())

    def remaining_permit(self) -> tuple[Any, int]:
        from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining

        return live_trading_budget_remaining(self.permit)


async def build_par_rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sender: Any,
    max_slots: int = 1,
    v2_predicate: Callable[[], bool] | None = None,
    ledger: Any | None = None,
    ledger_kwargs: dict[str, Any] | None = None,
    instruments: tuple[Any, ...] | None = None,
    frozen_bucket: str | None = None,
    order_count: str = "6",
    exit_manifest: FamilyManifest | None = None,
    store_path: Path | None = None,
    connect: bool = True,
    record_writes: bool = False,
    client_kwargs: dict[str, Any] | None = None,
) -> ParRig:
    """Build (and by default connect) the full stack at slot count ``max_slots``.

    ``max_slots=1`` with no extra arguments is exactly the shipped K=1 wiring.
    For ``max_slots > 1`` the v2 predicate defaults to True and the frozen bucket
    to :data:`PERMISSIVE_BUCKET`, so admission is not blocked by wiring.
    """
    loop = asyncio.get_running_loop()
    native_clock = LiveClock()
    clock = SettableClock(native_clock, BASE_NS)
    msgbus = MessageBus(trader_id=TRADER_ID, clock=native_clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    chosen = instruments or (
        build_instrument(),
        build_second_instrument(),
        build_third_instrument(),
    )
    provider = InstrumentProvider()
    for instrument in chosen:
        cache.add_instrument(instrument)
        provider.add(instrument)
    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: {"positions": {}, "eof": True},
            OPEN_ORDERS_PATH: {"orders": []},
            PORTFOLIO_ACTIVITIES_PATH: {"activities": [], "eof": True},
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

    path = store_path or (tmp_path / "exec_state.db")
    enable_operator_gate(monkeypatch, order_count=order_count)
    permit = issue_live_trading_permit(clock=clock)
    slot_kwargs: dict[str, Any] = {"clock_ns": clock.timestamp_ns}
    if max_slots > 1:
        slot_kwargs = {
            "max_slots": max_slots,
            "v2_predicate": v2_predicate or (lambda: True),
            "clock_ns": clock.timestamp_ns,
        }
    writes: list[tuple[str, bytes]] = []

    def _open_store() -> Any:
        inner = SqliteStateStore(path)
        return RecordingStore(inner, writes) if record_writes else inner

    latch_cm = open_submit_intent_latch(_open_store(), path, **slot_kwargs)
    latch = latch_cm.__enter__()
    the_ledger = ledger if ledger is not None else DailySpendLedger(**(ledger_kwargs or {}))

    extra: dict[str, Any] = {}
    if max_slots > 1:
        extra["frozen_cost_budget_bucket"] = frozen_bucket or PERMISSIVE_BUCKET
    elif frozen_bucket is not None:
        extra["frozen_cost_budget_bucket"] = frozen_bucket

    client = ParClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=native_clock,
        private_read=read,
        state_store_opener=_open_store,
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=1.0,
        account_registration_timeout_s=1.0,
        order_sender=sender,
        write_signer=_FakeWriteSigner(),
        live_trading_permit=permit,
        spend_ledger=the_ledger,
        submit_intent_latch=latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
        exit_manifest=exit_manifest,
        **extra,
        **(client_kwargs or {}),
    )
    client.__dict__["_par_clock"] = clock
    rig = ParRig(
        client=client,
        sender=sender,
        order_events=order_events,
        instruments=chosen,
        clock=clock,
        latch=latch,
        ledger=the_ledger,
        permit=permit,
        store_path=path,
        latch_cm=latch_cm,
        read=read,
        factory=OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=TestClock()),
        writes=writes,
    )
    if connect:
        await client._connect()
    return rig


def decimal_spent(rig: ParRig) -> Decimal:
    """Today's recorded spend in the rig's ledger (a read; never mutates)."""
    return rig.ledger.spent_today_usd(now_ns=rig.clock.timestamp_ns())
