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
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
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
    utc_day_for_ns,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermissionError,
    issue_live_trading_permit,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, base_slug_of
from breezy.adapters.polymarket_us.transport import VenueResponse
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
from tests.unit.test_current_rung_hold_ambiguous_resolver import (
    _backdate_resolver_context,
    _run_exactly_one_pass,
    _run_n_passes_recording_sleeps,
    _run_resolver_passes,
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
    _exit_shaped_body_with_echo,
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

backdate = _backdate_resolver_context
run_passes = _run_resolver_passes
run_one_pass = _run_exactly_one_pass
run_passes_recording_sleeps = _run_n_passes_recording_sleeps
accept_fill_body = _accept_fill_body
exit_fill_body = _exit_shaped_body_with_echo
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
    "GatedSender",
    "NoRegisterLedger",
    "ParClient",
    "ParRig",
    "PolymarketUSExecutionClient",
    "RetirementReason",
    "ScriptedSender",
    "SpyLedger",
    "YieldingOrderSender",
    "accept_fill_body",
    "ambiguous_body",
    "arm_open_intent",
    "as_if_booted",
    "backdate",
    "build_par_rig",
    "build_third_instrument",
    "caps",
    "client_module",
    "decimal_spent",
    "durable_record",
    "exit_fill_body",
    "ok",
    "par_rig",
    "reboot",
    "reject_body",
    "run_one_pass",
    "run_passes",
    "run_passes_recording_sleeps",
    "spy_retire",
    "submit_chain",
    "wire_order",
    "wire_positions",
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
#: A clock jump past this (the permit lives 10 h from BASE_NS) re-mints the permit.
_PERMIT_REMINT_AFTER_NS: Final[int] = 9 * 3600 * SEC_NS
#: 2026-10-11T00:00:00Z, the next UTC midnight after :data:`BASE_NS`.
NEXT_MIDNIGHT_NS: Final[int] = BASE_NS + 12 * 3600 * SEC_NS


class SettableClock:
    """An absolute, test-controlled ``timestamp_ns`` (other attributes delegate)."""

    def __init__(self, inner: Any, now_ns: int) -> None:
        self._inner = inner
        self.now_ns = now_ns
        #: Added to ``now_ns`` AFTER every read (0 = a frozen clock); a test sets
        #: it to prove that two values came from ONE read.
        self.tick_ns = 0
        self.reads = 0

    def timestamp_ns(self) -> int:
        value = self.now_ns
        self.now_ns += self.tick_ns
        self.reads += 1
        return value

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
        return [m for lv, m in self.log_records if lv.upper() == level.upper() and contains in m]

    @property
    def settable_clock(self) -> SettableClock:
        clock = self._clock
        assert isinstance(clock, SettableClock)
        return clock

    def set_now(self, ns: int) -> None:
        """Jump the shared clock. The permit has a 10 h TTL from BASE_NS, so a
        jump to the next UTC midnight (12 h on) re-mints it against the new
        clock; a test that counts permit slots must not call this."""
        self.settable_clock.now_ns = ns
        if self._permit is not None and ns - BASE_NS > _PERMIT_REMINT_AFTER_NS:
            self._permit = issue_live_trading_permit(clock=self.settable_clock)

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
def caps(daily: str = "1000.00", position: str = "10.00") -> Iterator[None]:
    """The placeholder caps every sibling exec suite wraps its body in.

    A test that needs a tight placeholder (to reach an open-exposure bound with a
    handful of orders) passes its own through this same whitelisted seam.
    """
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, daily),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, position),
    ):
        yield


def ok(body: bytes, status: int = 200) -> VenueResponse:
    """A venue response carrying ``body``."""
    return VenueResponse(status=status, headers={}, body=body)


class ScriptedSender:
    """``post_order`` hands back the queued responses in order; an exception
    instance in the queue is raised. Every call is recorded."""

    def __init__(self, *responses: VenueResponse | Exception, yield_once: bool = False) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.yield_once = yield_once

    async def post_order(self, base_url: str, *, headers: Any, body: bytes) -> Any:
        if self.yield_once:
            await asyncio.sleep(0)
        index = len(self.calls)
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        response = self.responses[index if index < len(self.responses) else -1]
        if isinstance(response, Exception):
            raise response
        return response


class GatedSender:
    """Like :class:`ScriptedSender`, but call ``n`` parks until ``release(n)``.

    ``started(n)`` is set as soon as call ``n`` is in flight, so a test can
    interleave other work at exactly the POST ``await``.
    """

    def __init__(self, *responses: VenueResponse | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self._gates = [asyncio.Event() for _ in responses]
        self._started = [asyncio.Event() for _ in responses]

    def release(self, index: int) -> None:
        self._gates[index].set()

    async def wait_started(self, index: int, timeout_s: float = 5.0) -> None:
        """Wait for call ``index`` to be in flight; a call that never starts (the
        order was denied before the POST) fails the test instead of hanging it."""
        try:
            await asyncio.wait_for(self._started[index].wait(), timeout_s)
        except TimeoutError:
            raise AssertionError(f"POST call {index} never started") from None

    async def post_order(self, base_url: str, *, headers: Any, body: bytes) -> Any:
        index = len(self.calls)
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        self._started[index].set()
        await self._gates[index].wait()
        response = self.responses[index]
        if isinstance(response, Exception):
            raise response
        return response


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

    def slug(self, index: int = 0) -> str:
        return str(base_slug_of(self.instruments[index].id))

    def day_stop_marker(self) -> bytes | None:
        """The durable UTC day-stop marker for the client's current day, if any."""
        day = utc_day_for_ns(self.clock.timestamp_ns()).isoformat()
        marker: bytes | None = self.client._store_get(
            f"{client_module.BUDGET_EXHAUSTED_KEY_PREFIX}{day}"
        )
        return marker

    async def close(self) -> None:
        await self.client._disconnect()
        self.latch_cm.__exit__(None, None, None)

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
        **{**extra, **(client_kwargs or {})},
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


class SpyLedger(DailySpendLedger):
    """The real ledger plus a call log and a scripted ``settle`` failure.

    ``calls`` holds ``("settle", key, booking_given, realized, fill_ts_ns, now_ns,
    booking_still_reachable)`` and ``("abandon", key)`` tuples in call order.
    ``settle_raises`` is how many of the next ``settle`` calls raise the
    ledger's own integrity error type before delegating normally.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[Any, ...]] = []
        self.settle_raises = 0
        self.client: Any = None

    def settle(
        self,
        key: str,
        *,
        booking: Any,
        realized_usd: Any,
        fill_ts_ns: Any,
        now_ns: int,
    ) -> bool:
        reachable = self.client is not None and key in self.client._ambiguous_bookings
        self.calls.append(
            ("settle", key, booking is not None, realized_usd, fill_ts_ns, now_ns, reachable)
        )
        if self.settle_raises > 0:
            self.settle_raises -= 1
            raise LiveTradingPermissionError("settle integrity error (scripted)")
        return super().settle(
            key,
            booking=booking,
            realized_usd=realized_usd,
            fill_ts_ns=fill_ts_ns,
            now_ns=now_ns,
        )

    def abandon_open_exposure(self, key: str) -> bool:
        self.calls.append(("abandon", key))
        return super().abandon_open_exposure(key)


class NoRegisterLedger(SpyLedger):
    """The "registry double" of r5 3.7: ``register_open_exposure`` does nothing,
    so every intent is unregistered -- the only way production reaches the
    UNBUDGETED latch (a registry bug)."""

    def register_open_exposure(self, *args: Any, **kwargs: Any) -> None:
        return None


def spy_retire(rig: ParRig, ledger: SpyLedger) -> None:
    """Interleave every ``client._retire`` into ``ledger.calls`` as ``("retire", id)``."""
    original = rig.client._retire

    def recording(intent_id: str, retire_name: str, now_ns: int) -> None:
        ledger.calls.append(("retire", intent_id))
        original(intent_id, retire_name, now_ns)

    rig.client._retire = recording
    ledger.client = rig.client


def as_if_booted(
    client: Any, intent_id: str, *, notional: str = "0.40", register: bool = True
) -> None:
    """Model the state a RESTARTED process holds for an inherited OPEN intent.

    The old ledger died with the process, so a FRESH ledger replaces it; no
    booking survives (``_ambiguous_bookings`` is process-local); and -- iff
    ``register`` -- the boot hunk registers the intent as uncharged, AMBIGUOUS
    open exposure (the notional, no seeded partial). ``register=False`` is the
    registry-failure shape the retained UNBUDGETED variants exercise.
    """
    client._ledger = DailySpendLedger()
    client._ambiguous_bookings.pop(intent_id, None)
    if register:
        client._ledger.register_open_exposure(
            intent_id,
            Decimal(notional),
            booking=None,
            seeded_partial_usd=Decimal(0),
            side="BUY",
            now_ns=client._clock.timestamp_ns(),
        )
        client._ledger.mark_ambiguous(intent_id)


async def reboot(rig: ParRig, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> ParRig:
    """Model a process restart: release the first process's flock and build a
    fresh stack over the SAME durable store (connected unless told otherwise)."""
    await rig.close()
    return await build_par_rig(
        rig.store_path.parent, monkeypatch, store_path=rig.store_path, **kwargs
    )


@asynccontextmanager
async def par_rig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs: Any
) -> AsyncIterator[ParRig]:
    """:func:`build_par_rig` that always disconnects and releases the flock."""
    rig = await build_par_rig(tmp_path, monkeypatch, **kwargs)
    try:
        yield rig
    finally:
        await rig.close()


_FP_COUNTER = [0]


def arm_open_intent(
    rig: ParRig,
    index: int = 0,
    *,
    venue_order_id: str = "ord-hand",
    age_s: float = 200.0,
    notional: str = "0.40",
    order_side: str = "BUY",
    with_context: bool = True,
    registered: bool = False,
    wire_price: str | None = "0.40",
    wire_quantity: str | None = "1",
    baseline: tuple[str, str, int] | None = None,
    instrument: Any | None = None,
) -> str:
    """Hand-arm an OPEN slot ``age_s`` seconds old plus its resolver context.

    ``registered`` also registers it (uncharged, AMBIGUOUS) in the ledger the
    way the boot hunk does. ``baseline`` is ``(venue_net, durable_net, ts_ns)``.
    Returns the intent id.
    """
    import hashlib

    target = instrument if instrument is not None else rig.instruments[index]
    slug = str(base_slug_of(target.id))
    now_ns = rig.clock.timestamp_ns()
    created_ns = now_ns - int(age_s * SEC_NS)
    _FP_COUNTER[0] += 1
    fingerprint = hashlib.sha256(f"hand-{_FP_COUNTER[0]}".encode()).hexdigest()
    if rig.latch.max_slots() > 1:
        armed = rig.latch.arm_slot(fingerprint, slug=slug, is_exit=False, now_ns=created_ns)
    else:
        armed = rig.latch.arm(fingerprint, now_ns=created_ns)
    if with_context:
        base_net, durable_net, base_ts = baseline if baseline else (None, None, None)
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=venue_order_id,
            instrument_id=str(target.id),
            client_order_id=f"O-HAND-{_FP_COUNTER[0]}",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal(notional),
            booking_id=1,
            created_ns=created_ns,
            order_side=order_side,
            wire_market_slug=slug,
            wire_price=wire_price,
            wire_outcome_side="OUTCOME_SIDE_YES",
            wire_action="ORDER_ACTION_BUY",
            baseline_venue_net=base_net,
            baseline_durable_net=durable_net,
            baseline_ts_ns=base_ts,
            wire_quantity=wire_quantity,
        )
        # Through the latch's own store handle: it is open before ``_connect`` too,
        # and it is the same database file the client reads.
        rig.latch._store.set(
            f"{client_module.RESOLVER_CONTEXT_KEY_PREFIX}{armed.intent_id}", context.to_bytes()
        )
    if registered:
        rig.ledger.register_open_exposure(
            armed.intent_id,
            Decimal(notional),
            booking=None,
            seeded_partial_usd=Decimal(0),
            side=order_side,
            now_ns=now_ns,
        )
        rig.ledger.mark_ambiguous(armed.intent_id)
    return str(armed.intent_id)


def wire_order(rig: ParRig, order_id: str, index: int = 0, **body: Any) -> None:
    """Serve ``GET /v1/order/<id>`` with the resolver suite's order body."""
    from tests.unit.test_current_rung_hold_ambiguous_resolver import _order_get_body

    payloads = rig.client._private_read._payloads
    payloads[f"/v1/order/{order_id}"] = _order_get_body(order_id, slug=rig.slug(index), **body)


def wire_positions(rig: ParRig, positions: dict[str, Any]) -> None:
    rig.client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": positions,
        "eof": True,
    }


def durable_record(
    rig: ParRig,
    *,
    venue_order_id: str,
    ts_event: int,
    cost: str,
    index: int = 0,
    side: str = "BUY",
) -> Any:
    """A ``DurableFillRecord`` for one unit on instrument ``index``."""
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"O-REC-{venue_order_id}",
        instrument_id=str(rig.instruments[index].id),
        order_side=side,
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal(cost),
        cumulative_fee=Decimal(0),
        fee_reconciled=True,
        ts_event=ts_event,
        venue_fee_raw=None,
        trade_id=f"T-{venue_order_id}",
        order_qty=Decimal(1),
    )


def decimal_spent(rig: ParRig) -> Decimal:
    """Today's recorded spend in the rig's ledger (a read; never mutates)."""
    spent: Decimal = rig.ledger.spent_today_usd(now_ns=rig.clock.timestamp_ns())
    return spent
