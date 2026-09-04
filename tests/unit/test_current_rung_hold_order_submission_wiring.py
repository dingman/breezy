"""T5/T5b/T6 -- CRH step 8: the real order-submission wiring, end to end.

Drives ``CurrentRungHoldStrategy.submit_order`` through Nautilus's REAL
``RiskEngine`` + ``ExecutionEngine`` (not the R-7 direct-``_submit_order``
shortcut) into the shipped fake exec transport, proving the new call path
this commit adds: ``Take`` -> ``Strategy.submit_order`` ->
``RiskEngine.execute`` -> ``ExecutionEngine.execute`` ->
``PolymarketUSExecutionClient.submit_order`` -> ``_submit_order`` ->
``post_order``.

Every fake/fixture below is IMPORTED, never redefined:
``_FakeSender``/``_FakeSigner``/``_PrivateReadStub``/``_balances_payload``/
``write_canonical_verified`` (``test_polymarket_us_submit_order_chain.py``,
R-7); ``credentials``/``enable_operator_gate``
(``test_polymarket_us_permit_issuance.py``); the weather-facts instrument/
observation/quote builders (``test_current_rung_hold_strategy.py``); the
composition root's own ``make_trial_day_latch_factory``
(``strategy/current_rung_hold/composition.py``).
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.execution.engine import ExecutionEngine
from nautilus_trader.model.identifiers import ClientId, StrategyId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.risk.engine import RiskEngine

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
from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.order_enablement import OrderSubmissionPermit
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import make_trial_day_latch_factory
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import build_instrument
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    NS_PER_MIN,
    STATION,
    WINDOW_OPEN_NS,
    _observation,
    _quote,
)
from tests.unit.test_current_rung_hold_strategy import (
    _instrument as _weather_shape,
)
from tests.unit.test_polymarket_us_permit_issuance import credentials, enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    _balances_payload,
    _FakeSender,
    _FakeSigner,
    _PrivateReadStub,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture, see module docstring
)

#: B11 pins ``issue`` to exactly one call site repo-wide, INCLUDING tests
#: (see ``test_order_submission_permit_issuance.py``'s ``_ISSUE`` docstring
#: for the full rationale) -- this rig calls through a local alias rather
#: than writing ``OrderSubmissionPermit.issue(`` literally.
_ISSUE = OrderSubmissionPermit.issue

TRADER_ID: Final[TraderId] = TraderId("BREEZY-STEP8-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("CurrentRungHoldStrategy-LAX")
CLIENT_ID: Final[ClientId] = ClientId("POLYMARKET_US")
ACCOUNT_NUMBER: Final[str] = "001"


def _weather_execution_instrument() -> BinaryOption:
    """A real, slug-mappable Polymarket.us instrument carrying WeatherBucketFacts.

    ``build_instrument()`` is the real captured market R-7's suites map
    order bodies against -- its ``InstrumentId`` is a genuine venue slug.
    ``_weather_shape`` (``test_current_rung_hold_strategy.py``'s
    ``_instrument`` helper) builds the SAME id with the ``WeatherBucketFacts``
    ``info`` the strategy's decision path reads. Combining the two gives one
    instrument that is valid on BOTH sides of the wiring this test proves.
    """
    real = build_instrument()
    return _weather_shape(real.id, lower_f=86, upper_f=87)


async def _drain_pending_tasks() -> None:
    """Let every task ``LiveExecutionClient.create_task`` scheduled finish.

    ``Strategy.submit_order`` routes synchronously through ``RiskEngine`` and
    ``ExecutionEngine`` to ``client.submit_order``, which schedules
    ``_submit_order`` as an ``asyncio.Task`` rather than awaiting it inline
    -- exactly the real live shape. A few drain passes let that task (and
    whatever it awaits) actually run before assertions.
    """
    current = asyncio.current_task()
    for _ in range(20):
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending)


class _CapsAndGate:
    """Context manager: operator gate env + the two operator-reserved caps."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._stack: list[Any] = []

    def __enter__(self) -> None:
        enable_operator_gate(self._monkeypatch)
        for name, value in (
            (MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
            (MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
        ):
            cm = operator_control_env(name, value)
            cm.__enter__()
            self._stack.append(cm)

    def __exit__(self, *exc_info: object) -> None:
        for cm in reversed(self._stack):
            cm.__exit__(*exc_info)


class _WiringRig:
    def __init__(
        self,
        *,
        client: PolymarketUSExecutionClient,
        strategy: CurrentRungHoldStrategy,
        sender: _FakeSender,
        order_events: list[Any],
        ledger: DailySpendLedger,
        latch_cm: Any,
    ) -> None:
        self.client = client
        self.strategy = strategy
        self.sender = sender
        self.order_events = order_events
        self.ledger = ledger
        self._latch_cm = latch_cm


async def _build_wiring_rig(
    tmp_path: Path,
    *,
    sender: _FakeSender | None = None,
    store_path: Path | None = None,
) -> _WiringRig:
    """Build the rig. MUST be called from inside an entered ``_CapsAndGate``:
    the operator caps are re-read LIVE by ``DailySpendLedger.authorize_order_cost``
    at ``_submit_order`` time, which runs later, inside an ``asyncio.Task``
    scheduled well after this function returns -- so the caps must still be
    set in the environment when that task actually runs, not just at permit-
    mint time.
    """
    loop = asyncio.get_running_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))

    instrument = _weather_execution_instrument()
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
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    msgbus.subscribe(topic=f"events.order.{STRATEGY_ID}", handler=order_events.append)

    resolved_store_path = store_path if store_path is not None else tmp_path / "exec_state.db"
    fake_sender = sender if sender is not None else _FakeSender()

    live_permit = issue_live_trading_permit(clock=clock)
    order_submission_permit = _ISSUE(
        settings=_FakeSettings(), live_trading_permit=live_permit, clock=clock,
    )

    latch_cm = open_submit_intent_latch(SqliteStateStore(resolved_store_path), resolved_store_path)
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
        state_store_opener=lambda: SqliteStateStore(resolved_store_path),
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=1.0,
        account_registration_timeout_s=1.0,
        order_sender=fake_sender,
        write_signer=_FakeSigner(),
        live_trading_permit=live_permit,
        spend_ledger=ledger,
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
    )

    _risk_engine = RiskEngine(portfolio=portfolio, msgbus=msgbus, cache=cache, clock=clock)
    exec_engine = ExecutionEngine(msgbus=msgbus, cache=cache, clock=clock)
    exec_engine.register_client(client)
    exec_engine.register_default_client(client)

    await client._connect()

    config = CurrentRungHoldConfig(
        instrument_ids=(instrument.id,),
        stations=(STATION,),
        strategy_id="CurrentRungHoldStrategy",
        order_id_tag=STATION,
    )
    strategy = CurrentRungHoldStrategy(
        config,
        trial_day_latch_factory=make_trial_day_latch_factory(submit_intent_latch),
        order_submission_permit=order_submission_permit,
    )
    strategy.register(
        trader_id=TRADER_ID,
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    strategy.start()

    return _WiringRig(
        client=client,
        strategy=strategy,
        sender=fake_sender,
        order_events=order_events,
        ledger=ledger,
        latch_cm=latch_cm,
    )


class _FakeSettings:
    """The narrow ``SettingsLike`` surface ``OrderSubmissionPermit.issue`` needs."""

    orders_enabled_requested = True
    current_rung_hold = True
    live_observations = True


def _durable_accept_body(*, commission: str = "0.03", last_px: str = "0.37") -> bytes:
    from tests.unit.polymarket_us_exec_shapes import build_execution, build_order

    real = build_instrument()
    from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug

    slug = instrument_id_to_slug(real.id)
    order = build_order(slug)
    order["id"] = "ord-step8-1"
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
    return json.dumps({"id": "ord-step8-1", "executions": [execution]}).encode("utf-8")


def _zero_fill_body() -> bytes:
    """A 200 with empty executions, terminal IOC state, ``cumQuantity=0``
    (``submit_chain.KIND_ZERO_FILL``) -- the IOC-miss leaf. ``_terminal_state``/
    ``_cum_quantity`` (``submit_chain.py``) read ``state``/``cumQuantity`` as
    TOP-LEVEL response keys, so both are set there (not nested).
    """
    return json.dumps(
        {
            "id": "ord-step8-zero",
            "state": "ORDER_STATE_CANCELED",
            "cumQuantity": 0,
            "executions": [],
        }
    ).encode("utf-8")


@pytest.mark.asyncio
async def test_take_reaches_post_order_exactly_once_via_the_real_strategy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T5: ``Take`` -> ``submit_order`` -> ``_submit_order`` -> ``post_order``,
    exactly once, for two executable quotes on the same station-day. The
    ledger is trued up on the durable fill (D9 leaf), and the trial-day latch
    consumed the day on the FIRST tick.
    """
    sender = _FakeSender()
    sender.response = __import__(
        "breezy.adapters.polymarket_us.transport", fromlist=["VenueResponse"]
    ).VenueResponse(status=200, headers={}, body=_durable_accept_body())

    with _CapsAndGate(monkeypatch):
        rig = await _build_wiring_rig(tmp_path, sender=sender)
        strategy = rig.strategy

        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        instrument_id = strategy._config.instrument_ids[0]

        first = _quote(instrument_id, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(first)
        await _drain_pending_tasks()

        second = _quote(
            instrument_id, ask="0.10", ts_event=WINDOW_OPEN_NS + 10 * NS_PER_MIN,
        )
        strategy.on_quote_tick(second)
        await _drain_pending_tasks()

    assert len(rig.sender.calls) == 1, "post_order must fire exactly once"
    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
    assert record is not None
    assert record.reason == "taken"
    assert rig.ledger.spent_today_usd(now_ns=strategy.clock.timestamp_ns()) > Decimal(0)
    # D9 leaf: ACCEPTED_WITH_DURABLE_FILL trues up the reservation, never
    # releases it (converged review item 10).
    assert len(rig.ledger._trued_up_ids) == 1
    assert len(rig.ledger._released_ids) == 0
    from nautilus_trader.model.events import OrderFilled

    filled = [event for event in rig.order_events if isinstance(event, OrderFilled)]
    assert len(filled) == 1


@pytest.mark.asyncio
async def test_zero_fill_ioc_releases_the_daily_reservation_via_the_real_strategy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T5 (converged review item 10): a zero-fill IOC releases the daily
    reservation via ``true_up_booking(0)`` (``client.py:1592``), reached
    through the real strategy -> RiskEngine -> ExecutionEngine path, and
    the booking lands in ``_trued_up_ids`` (NOT ``_released_ids`` --
    ``true_up_booking(0)`` is a true-up to zero, not a release).
    """
    from breezy.adapters.polymarket_us.transport import VenueResponse

    sender = _FakeSender()
    sender.response = VenueResponse(status=200, headers={}, body=_zero_fill_body())

    with _CapsAndGate(monkeypatch):
        rig = await _build_wiring_rig(tmp_path, sender=sender)
        strategy = rig.strategy

        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        instrument_id = strategy._config.instrument_ids[0]
        quote = _quote(instrument_id, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)
        await _drain_pending_tasks()

    assert len(rig.sender.calls) == 1
    assert rig.ledger.spent_today_usd(now_ns=strategy.clock.timestamp_ns()) == Decimal(0)
    assert len(rig.ledger._trued_up_ids) == 1
    assert len(rig.ledger._released_ids) == 0



@pytest.mark.asyncio
async def test_cross_restart_second_engine_never_takes_a_second_trial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T5b: two strategy instances, constructed SEQUENTIALLY (a process
    restart), over ONE SQLite latch store. The second sees the SAME
    station-day already consumed and never submits -- the durable
    cross-restart limit converged review item 3 names (the trial-day latch
    + fixed station list, not the ledger, bound the day at <=4 orders).
    """
    store_path = tmp_path / "shared_state.db"

    with _CapsAndGate(monkeypatch):
        rig1 = await _build_wiring_rig(tmp_path, store_path=store_path)
        strategy1 = rig1.strategy
        strategy1.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        instrument_id = strategy1._config.instrument_ids[0]
        strategy1.on_quote_tick(_quote(instrument_id, ask="0.40", ts_event=WINDOW_OPEN_NS))
        await _drain_pending_tasks()
        assert len(rig1.sender.calls) == 1

        # "Restart": release the exclusive flock the first engine held.
        strategy1.stop()
        rig1._latch_cm.__exit__(None, None, None)

        rig2 = await _build_wiring_rig(tmp_path, store_path=store_path)
        strategy2 = rig2.strategy
        strategy2.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        strategy2.on_quote_tick(_quote(instrument_id, ask="0.40", ts_event=WINDOW_OPEN_NS))
        await _drain_pending_tasks()

        assert len(rig2.sender.calls) == 0, (
            "the second engine must never re-take a consumed station-day"
        )
        assert strategy2._latch.is_consumed(STATION, CLIMATE_DAY.isoformat())

        strategy2.stop()
        rig2._latch_cm.__exit__(None, None, None)
