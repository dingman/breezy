"""FLAG-OFF (shadow-mode) runtime wiring of ``CurrentRungHoldStrategy``.

RED 1-9 of ``docs/plans/CRH_RUNTIME_WIRING_BRIEF_2026-09-04.md`` (converged
peer review). The composition root is ``breezy.app.trade.run``; ``orders_enabled``
stays unreachable from env; ``build_trade_node_config`` keeps ``strategies=[]``.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.app.trade import run
from breezy.domain.climate_day import climate_day_for_instant
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.registry.sites import default_registry
from breezy.runtime.settings import (
    CURRENT_RUNG_HOLD_VAR,
    LIVE_OBSERVATIONS_VAR,
    TRADE_CATALOG_ROOT_VAR,
    TRADE_TRADER_ID_VAR,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockHeld,
    hold_submit_intent_process_lock,
    open_submit_intent_latch,
)
from breezy.runtime.trade_cli import EXIT_CONFIG_ERROR, EXIT_OK, EXIT_RUNTIME_ERROR
from breezy.strategy.current_rung_hold.config import (
    SUPPORTED_STATIONS,
    CurrentRungHoldConfig,
    OrdersEnabledNotPermittedError,
)
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy

_VENUE = "polymarket_us"
_POLYMARKET_VENUE = Venue("POLYMARKET_US")
OPERATOR_ORDER_CEILING_USD = "25"


def _trade_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        TRADE_TRADER_ID_VAR: "BREEZYTRADE-001",
        "POLYMARKET_US_ALLOW_FOREIGN_ORIGIN": "1",
        "POLYMARKET_US_API_BASE": "https://api.example.invalid",
        "POLYMARKET_US_GATEWAY_BASE": "https://gateway.example.invalid",
        "POLYMARKET_US_WS_URL": "wss://ws.example.invalid",
        "POLYMARKET_US_USER_AGENT": "breezy-test/1.0 (+mailto:ops@example.invalid)",
        "POLYMARKET_US_ACCOUNT_NUMBER": "001",
        "POLYMARKET_US_EXEC_STATE_DB": str(tmp_path / "exec_state.db"),
    }
    env.update(overrides)
    return env


def _today_by_station() -> dict[str, object]:
    registry = default_registry()
    now = datetime.now(tz=UTC)
    return {
        station: climate_day_for_instant(
            now, registry.climate_day_window(_VENUE, station).std_utc_offset_hours
        )
        for station in SUPPORTED_STATIONS
    }


def _instrument(
    *,
    station: str,
    climate_day: object,
    lower_f: int = 80,
    upper_f: int = 81,
) -> BinaryOption:
    day = climate_day.isoformat()  # type: ignore[union-attr]
    slug = f"tc-temp-{station.lower()}high-{day}-gte{lower_f}lt{upper_f}f"
    instrument_id = InstrumentId(Symbol(slug), _POLYMARKET_VENUE)
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description=f"{station} daily high",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: station,
            CLIMATE_DAY_KEY: day,
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: lower_f,
            STRIKE_UPPER_F_KEY: upper_f,
        },
    )


def _write_today_catalog(catalog_root: Path) -> None:
    catalog = ParquetDataCatalog(str(catalog_root))
    catalog.write_data(
        [
            _instrument(station=station, climate_day=day)
            for station, day in _today_by_station().items()
        ]
    )


class _FakeMsgBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, Any]] = []

    def subscribe(self, *, topic: str, handler: Any) -> None:
        self.subscriptions.append((topic, handler))


class _FakeGuardPortfolio:
    def net_position(self, instrument_id: InstrumentId) -> Decimal:
        del instrument_id
        return Decimal(0)


class _FakeGuardCache:
    account: ClassVar[object] = object()

    def orders(self, *, instrument_id: InstrumentId | None = None) -> tuple[Any, ...]:
        del instrument_id
        return ()

    def order(self, client_order_id: object) -> None:
        del client_order_id

    def account_for_venue(self, venue: Venue) -> object | None:
        del venue
        return self.account


class _FakeRiskEngine:
    def __init__(self) -> None:
        self.states: list[object] = []

    def set_trading_state(self, state: object) -> None:
        self.states.append(state)


class _FakeKernel:
    def __init__(self) -> None:
        self.portfolio = _FakeGuardPortfolio()
        self.cache = _FakeGuardCache()
        self.msgbus = _FakeMsgBus()
        self.risk_engine = _FakeRiskEngine()


class _RecordingTrader:
    def __init__(self, calls: list[str]) -> None:
        self.actors: list[Any] = []
        self.strategies: list[Any] = []
        self._calls = calls

    def add_actor(self, actor: Any) -> None:
        self.actors.append(actor)
        self._calls.append("add_actor")

    def add_strategy(self, strategy: Any) -> None:
        self.strategies.append(strategy)
        self._calls.append("add_strategy")


class RecordingNode:
    instances: ClassVar[list[RecordingNode]] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.data_client_factories: list[tuple[str, type]] = []
        self.exec_client_factories: list[tuple[str, type]] = []
        self.calls: list[str] = []
        self.kernel = _FakeKernel()
        self.trader = _RecordingTrader(self.calls)
        RecordingNode.instances.append(self)

    def add_data_client_factory(self, name: str, factory: type) -> None:
        self.data_client_factories.append((name, factory))

    def add_exec_client_factory(self, name: str, factory: type) -> None:
        self.exec_client_factories.append((name, factory))

    def build(self) -> None:
        self.calls.append("build")

    def run(self) -> None:
        self.calls.append("run")

    def dispose(self) -> None:
        self.calls.append("dispose")


class RaisingNode(RecordingNode):
    def run(self) -> None:
        self.calls.append("run")
        raise RuntimeError("the socket exploded")


@pytest.fixture(autouse=True)
def _operator_order_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_ORDER_CEILING_USD)


@pytest.fixture(autouse=True)
def _clean_nodes() -> Iterator[None]:
    RecordingNode.instances.clear()
    yield
    RecordingNode.instances.clear()


def test_flag_absent_registers_zero_strategies_and_config_stays_empty(
    tmp_path: Path,
) -> None:
    code = run(env=_trade_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[0]
    assert node.trader.strategies == []
    assert "add_strategy" not in node.calls
    assert node.config.strategies == []


def test_current_rung_hold_without_live_observations_exits_two(
    tmp_path: Path,
) -> None:
    err = io.StringIO()
    env = _trade_env(tmp_path, **{CURRENT_RUNG_HOLD_VAR: "1"})

    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    message = err.getvalue()
    assert CURRENT_RUNG_HOLD_VAR in message
    assert LIVE_OBSERVATIONS_VAR in message
    assert RecordingNode.instances == []


def test_both_flags_on_empty_catalog_refuses_to_start(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    err = io.StringIO()
    env = _trade_env(
        tmp_path,
        **{
            CURRENT_RUNG_HOLD_VAR: "1",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )

    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    message = err.getvalue()
    assert "LAX=0" in message
    assert "MDW=0" in message
    assert "MIA=0" in message
    assert "SFO=0" in message
    assert RecordingNode.instances == []


def test_both_flags_on_populated_catalog_registers_one_strategy_per_station_before_build(
    tmp_path: Path,
) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            CURRENT_RUNG_HOLD_VAR: "1",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[0]
    strategies = node.trader.strategies
    assert len(strategies) == len(SUPPORTED_STATIONS)
    assert all(isinstance(strategy, CurrentRungHoldStrategy) for strategy in strategies)
    stations = {strategy._config.stations for strategy in strategies}
    assert stations == {(station,) for station in SUPPORTED_STATIONS}
    ids = [str(strategy.id) for strategy in strategies]
    tags = [strategy.order_id_tag for strategy in strategies]
    assert len(set(ids)) == len(ids)
    assert len(set(tags)) == len(tags)
    assert node.config.strategies == []
    add_indexes = [i for i, call in enumerate(node.calls) if call == "add_strategy"]
    actor_indexes = [i for i, call in enumerate(node.calls) if call == "add_actor"]
    build_index = node.calls.index("build")
    assert add_indexes
    assert all(index < build_index for index in add_indexes)
    assert all(index < build_index for index in actor_indexes)
    last_registration = max([*add_indexes, *actor_indexes])
    assert last_registration < build_index


def test_trial_day_latch_is_the_shared_binding_opened_once(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            CURRENT_RUNG_HOLD_VAR: "1",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    store_path = Path(env["POLYMARKET_US_EXEC_STATE_DB"])
    opened: list[object] = []
    real_open = open_submit_intent_latch

    def _spy(store: object, path: Path) -> object:
        ctx = real_open(store, path)
        opened.append(ctx)
        return ctx

    class _Capture(RecordingNode):
        def run(self) -> None:
            assert len(opened) == 1
            with pytest.raises(SubmitIntentLockHeld):
                other = SqliteStateStore(store_path)
                with real_open(other, store_path):
                    pass
            intent = None
            for strategy in self.trader.strategies:
                factory = strategy._latch_factory
                assert factory is not None
                with factory() as trial:
                    binding = trial._store, trial._lock
                    if intent is None:
                        intent = binding
                    else:
                        assert trial._store is intent[0]
                        assert trial._lock is intent[1]
            super().run()

    with patch("breezy.app.trade.open_submit_intent_latch", _spy):
        code = run(env=env, node_factory=_Capture, stderr=io.StringIO())

    assert code == EXIT_OK
    assert len(opened) == 1


def test_orders_enabled_cannot_be_set_from_env(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    for extra in (
        {"BREEZY_CURRENT_RUNG_HOLD_ORDERS_ENABLED": "1"},
        {"ORDERS_ENABLED": "true"},
        {"1": "1"},
    ):
        RecordingNode.instances.clear()
        env = _trade_env(
            tmp_path,
            **{
                CURRENT_RUNG_HOLD_VAR: "1",
                LIVE_OBSERVATIONS_VAR: "1",
                TRADE_CATALOG_ROOT_VAR: str(catalog_root),
                **extra,
            },
        )
        code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())
        assert code == EXIT_OK
        for strategy in RecordingNode.instances[0].trader.strategies:
            assert strategy._config.orders_enabled is False

    with pytest.raises(OrdersEnabledNotPermittedError):
        CurrentRungHoldConfig(orders_enabled=True)


def test_exit_stack_releases_the_flock_on_success_and_on_exception(
    tmp_path: Path,
) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            CURRENT_RUNG_HOLD_VAR: "1",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    store_path = Path(env["POLYMARKET_US_EXEC_STATE_DB"])

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())
    assert code == EXIT_OK
    with hold_submit_intent_process_lock(store_path) as lock:
        assert lock.held is True

    RecordingNode.instances.clear()
    code = run(env=env, node_factory=RaisingNode, stderr=io.StringIO())
    assert code == EXIT_RUNTIME_ERROR
    with hold_submit_intent_process_lock(store_path) as lock:
        assert lock.held is True


def test_two_stations_never_share_a_component_id(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            CURRENT_RUNG_HOLD_VAR: "1",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    run(env=env, node_factory=RecordingNode, stderr=io.StringIO())
    strategies = RecordingNode.instances[0].trader.strategies
    ids = [str(strategy.id) for strategy in strategies]
    tags = [strategy.order_id_tag for strategy in strategies]
    assert len(ids) == len(set(ids))
    assert len(tags) == len(set(tags))


def test_tape_recorder_settings_never_read_the_current_rung_hold_flag(
    tmp_path: Path,
) -> None:
    from breezy.runtime.settings import load_quote_tape_settings

    settings = load_quote_tape_settings(
        {
            "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": str(tmp_path / "tape"),
            CURRENT_RUNG_HOLD_VAR: "1",
        },
        total_bytes_probe=lambda _path: 500 * 1024**3,
    )
    assert not hasattr(settings, "current_rung_hold")
    assert "current_rung_hold" not in getattr(settings, "__dataclass_fields__", {})
