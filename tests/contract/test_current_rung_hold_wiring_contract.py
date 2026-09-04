"""Native pins for current_rung_hold shadow-mode wiring (RED 8, 11 + layer AST).

Cites installed nautilus_trader 1.231.0:
``Trader.add_strategy`` at ``trading/trader.py:375-420`` (duplicate ``strategy.id``
raises ``RuntimeError`` at :400; duplicate ``order_id_tag`` at :416).
``TradingNode.run`` drives the loop on the calling thread (``live/node.py:298``).
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.identifiers import TraderId

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch

_REPO_SRC = Path(__file__).resolve().parents[2] / "src"


def _strategy(station: str) -> CurrentRungHoldStrategy:
    return CurrentRungHoldStrategy(
        CurrentRungHoldConfig(
            instrument_ids=(),
            stations=(station,),
            strategy_id="CurrentRungHoldStrategy",
            order_id_tag=station,
        )
    )


def test_duplicate_strategy_id_on_a_real_trader_raises_runtime_error() -> None:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("TEST-001"),
            logging=LoggingConfig(log_level="ERROR"),
        )
    )
    engine.trader.add_strategy(_strategy("LAX"))
    with pytest.raises(RuntimeError, match="Already registered a strategy with ID"):
        engine.trader.add_strategy(_strategy("LAX"))


def test_distinct_stations_register_on_a_real_trader() -> None:
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("TEST-001"),
            logging=LoggingConfig(log_level="ERROR"),
        )
    )
    engine.trader.add_strategy(_strategy("LAX"))
    engine.trader.add_strategy(_strategy("MDW"))
    assert len(engine.trader.strategies()) == 2


def test_composition_store_is_confined_to_the_calling_thread(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    store = SqliteStateStore(store_path)
    errors: list[BaseException] = []

    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial = open_trial_day_latch(intent_latch)
        assert trial._store is store

        def _cross_thread() -> None:
            try:
                trial.record("LAX", "2026-09-04")
            except BaseException as exc:  # noqa: BLE001 - we assert the type below
                errors.append(exc)

        worker = threading.Thread(target=_cross_thread)
        worker.start()
        worker.join()

    assert errors
    assert isinstance(errors[0], RuntimeError)
    assert "_check_thread" in errors[0].args[0] or "different thread" in errors[0].args[0]


def test_runtime_package_has_zero_imports_of_breezy_strategy() -> None:
    runtime_root = _REPO_SRC / "breezy" / "runtime"
    offenders: list[str] = []
    for path in sorted(runtime_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module == "breezy.strategy" or node.module.startswith(
                    "breezy.strategy."
                ):
                    offenders.append(f"{path}:{node.lineno}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "breezy.strategy" or alias.name.startswith(
                        "breezy.strategy."
                    ):
                        offenders.append(f"{path}:{node.lineno}: import {alias.name}")
    assert offenders == []
