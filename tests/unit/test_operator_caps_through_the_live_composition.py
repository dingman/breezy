"""AUD-17: the two operator caps deny an order through the live v4 composition.

Coverage determination (17a). None of the mechanism suites build
``deploy/families/pm_us_crh_v4.json`` and assert a cap denial on its entry
path:

* ``test_operator_reserved_controls.py`` — ledger mechanism only.
* ``test_polymarket_us_exec_client.py`` — ``_submit_order`` with a synthetic
  ledger, not the v4 family.
* ``test_operator_control_assignment_scan.py`` — assignment census.
* ``test_polymarket_us_permit_issuance.py`` — permit mint.
* ``test_trade_supervisor_phase1_unit.py``, ``test_persistence_exit_gate.py``,
  ``test_family_registered_taker_fee_coefficient.py`` — name the family, no
  cap denial.
* ``test_*composition*`` — no cap denial on this entry path.

Gap is real. These tests are the composition proof. They are characterisation
tests: the caps already hold, so they are expected green on arrival.

``test_the_mechanism_has_no_production_call_site_yet`` pins the importer set
of ``operator_controls``, not the absence of a ledger. The name is stale.
``factories.py`` constructs ``DailySpendLedger`` and the live submit path
calls ``authorize_order_cost``. This file does not change that test.

Layer-A ladder rung: (a). A first draft handed the imported identifier to a
local helper and rule A6 fired. The assertion was rewritten into the bare
comparison the scan already pins as clean. Reason-equality is KEPT. The
scan was not amended to allow the helper.

The shipped v4 manifest declares no exit rule, so an exit-tagged sell is
denied at the exit-registration gate, before ``authorize_order_cost``. That
is the composition's behaviour. The order still leaves no booking and does
not debit the daily counter. A hand-written manifest is not used.
"""

from __future__ import annotations

import asyncio
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
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import AccountState, OrderDenied
from nautilus_trader.model.identifiers import ClientId, ClientOrderId, StrategyId, TraderId
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec.client import (
    BUDGET_EXHAUSTED_KEY_PREFIX,
    PolymarketUSExecutionClient,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    OPEN_ORDERS_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.exec_fault import clear_fatal_exec_fault
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
    utc_day_for_ns,
)
from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.persistence.exit_tags import (
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)
from breezy.persistence.family_manifest import load_family_manifest
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    open_trial_day_latch,
)
from tests.unit.operator_control_env import operator_control_env, operator_control_unset
from tests.unit.polymarket_us_exec_shapes import TS_EVENT_TEXT, build_instrument
from tests.unit.test_operator_control_assignment_scan import find_control_assignments
from tests.unit.test_polymarket_us_permit_issuance import (
    credentials,
    enable_operator_gate,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 — pytest fixture, the one setattr site
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_V4_MANIFEST: Final[Path] = REPO_ROOT / "deploy" / "families" / "pm_us_crh_v4.json"
_SUPERVISOR_UNIT: Final[Path] = (
    REPO_ROOT / "deploy" / "systemd" / "breezy-trade-supervisor.service"
)

TRADER_ID: Final[TraderId] = TraderId("BREEZY-AUD17-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("WEATHER-001")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
ACCOUNT_NUMBER: Final[str] = "001"
TS_INIT: Final[int] = 1_787_617_213_000_000_000

# Synthetic figures only. The order price is also the exactly-at ceiling,
# because that boundary is "cost == ceiling". Nothing here is an operator value.
_ORDER_PRICE: Final[str] = "0.37"
_GENEROUS: Final[str] = "8.88"
_BELOW_ORDER_COST: Final[str] = "0.36"
_SESSION_TOO_SMALL: Final[str] = "0.01"
_SEEDED_SPENT: Final[str] = "1.23"
_REFUSAL_SUFFIX: Final[str] = "; this client refuses to submit"
_ABSENT: Final[str] = (
    "is not set; live trading is operator-enabled only and has no default"
)
_POSITION_REFUSAL: Final[str] = (
    "refuses this order: its USD cost (price x quantity) exceeds the "
    "operator's per-position ceiling"
)
_DAILY_REFUSAL: Final[str] = (
    "refuses this order: it would carry today's USD notional past the "
    "operator's daily budget"
)
_SESSION_REFUSAL: Final[str] = (
    "order notional exceeds the permit's remaining notional budget" + _REFUSAL_SUFFIX
)
_EXIT_UNREGISTERED: Final[str] = "family does not declare a registered exit rule; refusing"
_NAKED_SHORT: Final[str] = "only a BUY is mappable (a SELL is a naked short); refusing"

_TOLERANT_SOURCE: Final[str] = (
    "from breezy.adapters.polymarket_us.operator_controls import (\n"
    "    MAX_POSITION_COST_USD_ENV_VAR,\n"
    ")\n"
    "def test_message(denied):\n"
    '    assert denied.reason == f"prefix {MAX_POSITION_COST_USD_ENV_VAR} suffix"\n'
)
_INTOLERANT_SOURCE: Final[str] = (
    "from breezy.adapters.polymarket_us.operator_controls import (\n"
    "    MAX_POSITION_COST_USD_ENV_VAR,\n"
    ")\n"
    "def show():\n"
    "    format(MAX_POSITION_COST_USD_ENV_VAR)\n"
)


@pytest.fixture(autouse=True)
def _isolate_permit_registries_and_exec_fault() -> Iterator[None]:
    from breezy.adapters.polymarket_us import safety

    nonces = dict(safety._UNSPENT_NONCES)
    budgets = dict(safety._PERMIT_BUDGETS)
    seeded = set(safety._SEEDED_PERMIT_BUDGETS)
    safety._UNSPENT_NONCES.clear()
    safety._PERMIT_BUDGETS.clear()
    safety._SEEDED_PERMIT_BUDGETS.clear()
    clear_fatal_exec_fault()
    try:
        yield
    finally:
        safety._UNSPENT_NONCES.clear()
        safety._UNSPENT_NONCES.update(nonces)
        safety._PERMIT_BUDGETS.clear()
        safety._PERMIT_BUDGETS.update(budgets)
        safety._SEEDED_PERMIT_BUDGETS.clear()
        safety._SEEDED_PERMIT_BUDGETS.update(seeded)
        clear_fatal_exec_fault()


def test_layer_a_still_classifies_the_imported_constant_the_way_this_file_depends_on() -> None:
    """Both branches, one run, synthetic sources, the scan's own helper."""
    tolerant = find_control_assignments("tests/unit/planted_compare.py", _TOLERANT_SOURCE)
    assert tolerant == [], (
        "layer A now flags the bare-comparison form — rewrite the per-position "
        "reason-equality assertion or drop it; never amend the scan."
    )
    intolerant = find_control_assignments("tests/unit/planted_call.py", _INTOLERANT_SOURCE)
    assert any(item.rule == "A6" for item in intolerant), (
        "layer A no longer constrains the assertion's shape — re-read §6 before "
        "relying on the old constraint, and if reason-equality was ever dropped, "
        "restore it."
    )


class _RecordingSender:
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


class _RecordingSigner:
    def sign_headers(self, method: str, path: str, **_kwargs: object) -> list[tuple[str, str]]:
        return [("X-Test-Method", method), ("X-Test-Path", path)]


class _ReadStub:
    def __init__(self, payloads: Mapping[str, Mapping[str, Any]]) -> None:
        self._payloads = payloads

    async def __call__(self, path: str) -> Mapping[str, Any]:
        return self._payloads[path]


class _Composition:
    """The v4 dispatch ``app/trade.py`` performs, plus the exec client it wires."""

    def __init__(
        self,
        *,
        client: PolymarketUSExecutionClient,
        sender: _RecordingSender,
        events: list[Any],
        clock: LiveClock,
        instrument: Any,
        latch_cm: Any,
        store_path: Path,
        ledger: DailySpendLedger,
    ) -> None:
        self.client = client
        self.sender = sender
        self.events = events
        self.clock = clock
        self.instrument = instrument
        self._latch_cm = latch_cm
        self.store_path = store_path
        self.ledger = ledger

    def close(self) -> None:
        self._latch_cm.__exit__(None, None, None)

    def _order(
        self,
        side: OrderSide,
        *,
        tags: list[str] | None,
        client_order_id: str,
    ) -> SubmitOrder:
        factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=self.clock)
        order = factory.limit(
            instrument_id=self.instrument.id,
            order_side=side,
            quantity=Quantity(1, self.instrument.size_precision),
            price=Price.from_str(_ORDER_PRICE),
            time_in_force=TimeInForce.IOC,
            tags=tags,
            client_order_id=ClientOrderId(client_order_id) if tags else None,
        )
        return SubmitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            order=order,
            command_id=UUID4(),
            ts_init=TS_INIT,
        )

    def entry(self, client_order_id: str = "O-AUD17-ENTRY") -> SubmitOrder:
        return self._order(OrderSide.BUY, tags=None, client_order_id=client_order_id)

    def naked_sell(self) -> SubmitOrder:
        return self._order(OrderSide.SELL, tags=None, client_order_id="O-AUD17-NAKED")

    def exit_sell(self, family_id: str) -> SubmitOrder:
        client_order_id = "O-AUD17-EXIT"
        return self._order(
            OrderSide.SELL,
            tags=[
                f"{EXIT_RULE_TAG_PREFIX}R_THREAT",
                f"{EXIT_POSITION_TAG_PREFIX}pos-aud17",
                f"{EXIT_FAMILY_TAG_PREFIX}{family_id}",
                f"{EXIT_CLIENT_ORDER_ID_TAG_PREFIX}{client_order_id}",
            ],
            client_order_id=client_order_id,
        )

    def denials(self) -> list[OrderDenied]:
        return [event for event in self.events if isinstance(event, OrderDenied)]

    def spent(self) -> Decimal:
        return self.ledger.spent_today_usd(now_ns=self.clock.timestamp_ns())

    def marker(self) -> bytes | None:
        day = utc_day_for_ns(self.clock.timestamp_ns()).isoformat()
        with SqliteStateStore(self.store_path) as store:
            return store.get(f"{BUDGET_EXHAUSTED_KEY_PREFIX}{day}")


def _compose(tmp_path: Path, *, permit: Any) -> _Composition:
    """Load the shipped v4 manifest and take the continuous-rung-hold branch."""
    unit = _SUPERVISOR_UNIT.read_text(encoding="utf-8")
    assert "BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4" in unit
    manifest = load_family_manifest(_V4_MANIFEST)
    assert manifest.family_id == "pm_us_crh_v4"
    assert manifest.composition_kind == "continuous_rung_hold"
    # The same branch ``app/trade.py`` takes for this composition_kind.
    # ``current_rung_hold`` and ``forecast_ladder`` are the other arms; v4
    # is not either of them. Strategies are not built: the cap binds at the
    # exec client, and sizing is out of scope.
    exit_manifest = manifest

    loop = asyncio.get_running_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    instrument = build_instrument()
    cache.add_instrument(instrument)
    provider = InstrumentProvider()
    provider.add(instrument)
    events: list[Any] = []

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)
    msgbus.register(endpoint="ExecEngine.process", handler=events.append)

    store_path = tmp_path / "exec_state.db"
    latch_cm = open_submit_intent_latch(SqliteStateStore(store_path), store_path)
    latch = latch_cm.__enter__()
    family_halt_latch = open_trial_day_latch(latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
    submit_veto = family_halt_submit_veto(family_halt_latch)
    assert submit_veto() is None
    ledger = DailySpendLedger()
    sender = _RecordingSender()
    client = PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=_ReadStub(
            {
                ACCOUNT_BALANCES_PATH: {
                    "balances": [
                        {
                            "currency": "USD",
                            "currentBalance": Decimal("4.00"),
                            "buyingPower": Decimal("4.00"),
                            "lastUpdated": TS_EVENT_TEXT,
                        },
                    ],
                },
                PORTFOLIO_POSITIONS_PATH: {"positions": {}, "eof": True},
                OPEN_ORDERS_PATH: {"orders": []},
            },
        ),
        state_store_opener=lambda: SqliteStateStore(store_path),
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=1.0,
        account_registration_timeout_s=1.0,
        order_sender=sender,
        write_signer=_RecordingSigner(),
        live_trading_permit=permit,
        spend_ledger=ledger,
        submit_intent_latch=latch,
        credentials=credentials(),
        api_base_url="https://api.example.invalid",
        retirement_reasons=RetirementReason,
        submit_veto=submit_veto,
        exit_manifest=exit_manifest,
    )
    return _Composition(
        client=client,
        sender=sender,
        events=events,
        clock=clock,
        instrument=instrument,
        latch_cm=latch_cm,
        store_path=store_path,
        ledger=ledger,
    )


@contextmanager
def _controls(*, daily: str | None, position: str | None) -> Iterator[None]:
    """Absence is explicit, then only the ceilings this case needs are set."""
    with (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR),
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR),
    ):
        if daily is None and position is None:
            yield
            return
        if daily is not None and position is not None:
            with (
                operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, daily),
                operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, position),
            ):
                yield
            return
        if daily is not None:
            with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, daily):
                yield
            return
        assert position is not None
        with operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, position):
            yield


def _position_reason() -> str:
    return f"{MAX_POSITION_COST_USD_ENV_VAR} {_POSITION_REFUSAL}{_REFUSAL_SUFFIX}"


def _daily_reason() -> str:
    return f"{MAX_DAILY_BUDGET_USD_ENV_VAR} {_DAILY_REFUSAL}{_REFUSAL_SUFFIX}"


async def _connected(composition: _Composition) -> None:
    await composition.client._connect()


@pytest.mark.asyncio
async def test_the_live_composition_admits_an_order_when_both_controls_are_generous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    try:
        with _controls(daily=_GENEROUS, position=_GENEROUS):
            await _connected(composition)
            await composition.client._submit_order(composition.entry())
            await composition.client._disconnect()
        assert composition.denials() == []
        assert len(composition.sender.calls) == 1
        assert composition.spent() == Decimal(_ORDER_PRICE)
        assert composition.marker() is None
    finally:
        composition.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["neither", "daily_only", "position_only"])
async def test_every_order_is_refused_when_neither_control_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    case: str,
) -> None:
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    daily = _GENEROUS if case == "daily_only" else None
    position = _GENEROUS if case == "position_only" else None
    try:
        with _controls(daily=daily, position=position):
            await _connected(composition)
            before = composition.spent()
            await composition.client._submit_order(composition.entry())
            await composition.client._disconnect()
        denials = composition.denials()
        assert len(denials) == 1
        # Bare comparison — handing the identifier to a helper is layer-A rule A6.
        if case == "daily_only":
            assert denials[0].reason == (
                f"{MAX_POSITION_COST_USD_ENV_VAR} {_ABSENT}{_REFUSAL_SUFFIX}"
            )
        else:
            assert denials[0].reason == (
                f"{MAX_DAILY_BUDGET_USD_ENV_VAR} {_ABSENT}{_REFUSAL_SUFFIX}"
            )
        assert composition.sender.calls == []
        assert composition.spent() == before
        assert composition.marker() is None
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_a_cost_above_the_per_position_ceiling_is_denied_by_that_ceiling_specifically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Exact-message pin plus the differential on the same permit and order.

    ``_submit_order`` catches the plain permission error, so ``type(exc) is``
    is not observable on the event. The reason text is the one only that
    plain branch raises, the day marker stays unset (the two subclasses
    latch), and raising only that ceiling admits the same order.
    """
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    command = composition.entry()
    try:
        with _controls(daily=_GENEROUS, position=_BELOW_ORDER_COST):
            await _connected(composition)
            await composition.client._submit_order(command)
        denials = composition.denials()
        assert len(denials) == 1
        assert denials[0].reason == _position_reason()
        assert composition.sender.calls == []
        assert composition.spent() == Decimal(0)
        assert composition.marker() is None

        composition.events.clear()
        with _controls(daily=_GENEROUS, position=_GENEROUS):
            await composition.client._submit_order(command)
            await composition.client._disconnect()
        assert composition.denials() == []
        assert len(composition.sender.calls) == 1
        assert composition.spent() == Decimal(_ORDER_PRICE)
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_an_order_past_the_daily_budget_raises_daily_budget_exhausted_and_latches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    try:
        with _controls(daily=_GENEROUS, position=_GENEROUS):
            await _connected(composition)
            now_ns = composition.clock.timestamp_ns()
            composition.ledger.seed_spent(
                day=utc_day_for_ns(now_ns),
                spent_usd=Decimal(_GENEROUS),
                now_ns=now_ns,
            )
            await composition.client._submit_order(composition.entry())
            await composition.client._disconnect()
        denials = composition.denials()
        assert len(denials) == 1
        assert denials[0].reason == _daily_reason()
        assert composition.sender.calls == []
        assert composition.spent() == Decimal(_GENEROUS)
        assert composition.marker() == b"1"
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_an_order_past_the_permit_session_notional_raises_session_notional_exhausted_and_latches(  # noqa: E501
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch, session_notional=_SESSION_TOO_SMALL)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    try:
        with _controls(daily=_GENEROUS, position=_GENEROUS):
            await _connected(composition)
            await composition.client._submit_order(composition.entry())
            await composition.client._disconnect()
        denials = composition.denials()
        assert len(denials) == 1
        assert denials[0].reason == _SESSION_REFUSAL
        assert composition.sender.calls == []
        assert composition.spent() == Decimal(0)
        assert composition.marker() == b"1"
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_an_exit_tagged_sell_skips_the_daily_budget_and_leaves_no_booking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Shipped v4 declares no exit rule, so the order never reaches the ledger.

    No booking, no debit, no POST. The denial names the exit-registration
    gate, which is how this composition skips the daily budget.
    """
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    manifest = load_family_manifest(_V4_MANIFEST)
    assert manifest.exit_rule is None
    try:
        with _controls(daily=_GENEROUS, position=_GENEROUS):
            await _connected(composition)
            await composition.client._submit_order(composition.exit_sell(manifest.family_id))
            await composition.client._disconnect()
        denials = composition.denials()
        assert len(denials) == 1
        assert denials[0].reason == _EXIT_UNREGISTERED
        assert composition.sender.calls == []
        assert composition.spent() == Decimal(0)
        assert composition.marker() is None
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_an_untagged_sell_never_reaches_the_exit_side_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    try:
        with _controls(daily=_GENEROUS, position=_GENEROUS):
            await _connected(composition)
            await composition.client._submit_order(composition.naked_sell())
            await composition.client._disconnect()
        denials = composition.denials()
        assert len(denials) == 1
        assert denials[0].reason == _NAKED_SHORT
        assert composition.sender.calls == []
        assert composition.spent() == Decimal(0)
        assert composition.marker() is None
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_a_cost_exactly_at_the_per_position_ceiling_is_admitted_through_the_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    try:
        with _controls(daily=_GENEROUS, position=_ORDER_PRICE):
            await _connected(composition)
            await composition.client._submit_order(composition.entry())
            await composition.client._disconnect()
        assert composition.denials() == []
        assert len(composition.sender.calls) == 1
        assert composition.spent() == Decimal(_ORDER_PRICE)
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_spend_exactly_at_the_daily_budget_is_admitted_through_the_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    try:
        with _controls(daily=_ORDER_PRICE, position=_GENEROUS):
            await _connected(composition)
            await composition.client._submit_order(composition.entry())
            await composition.client._disconnect()
        assert composition.denials() == []
        assert len(composition.sender.calls) == 1
        assert composition.spent() == Decimal(_ORDER_PRICE)
    finally:
        composition.close()


@pytest.mark.asyncio
async def test_a_refused_order_leaves_the_daily_counter_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch)
    permit = issue_live_trading_permit(clock=LiveClock())
    composition = _compose(tmp_path, permit=permit)
    seeded = Decimal(_SEEDED_SPENT)
    try:
        with _controls(daily=_GENEROUS, position=_BELOW_ORDER_COST):
            await _connected(composition)
            now_ns = composition.clock.timestamp_ns()
            composition.ledger.seed_spent(
                day=utc_day_for_ns(now_ns),
                spent_usd=seeded,
                now_ns=now_ns,
            )
            await composition.client._submit_order(composition.entry())
            await composition.client._disconnect()
        assert len(composition.denials()) == 1
        assert composition.sender.calls == []
        assert composition.spent() == seeded
    finally:
        composition.close()
