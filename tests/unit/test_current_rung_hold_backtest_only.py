"""RED test 12 (`docs/plans/PAPER_REPLAY_6B_BRIEF_2026-09-04.md`, converged
peer review item 2): `CurrentRungHoldBacktestStrategy` has exactly ONE
non-test importer, and refuses to `on_start` against anything but a
`TestClock`.

Fixture pattern lifted from `test_current_rung_hold_strategy.py`'s
`_register_and_start` helper (duplicated narrowly here, not imported, so
this file's collection never depends on that module's).
"""

from __future__ import annotations

import ast
import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

import breezy.strategy.current_rung_hold.backtest_only as backtest_only_module
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.backtest_only import (
    CurrentRungHoldBacktestStrategy,
    NotABacktestClockError,
)
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch, open_trial_day_latch

STATION = "LAX"
CLIMATE_DAY = dt.date(2026, 9, 4)
WINDOW_OPEN_NS = 1_788_552_000_000_000_000
INSTRUMENT_ID = InstrumentId(Symbol("lax-86-87"), Venue("POLYMARKET_US"))

#: One non-test importer only: the paper-replay driver.
_EXPECTED_IMPORTER = "scripts/analysis/current_rung_hold_paper_replay.py"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGET_MODULE = "breezy.strategy.current_rung_hold.backtest_only"
_TARGET_NAME = "CurrentRungHoldBacktestStrategy"


def _imports_backtest_only_strategy(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == _TARGET_MODULE
            and any(alias.name == _TARGET_NAME for alias in node.names)
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name == _TARGET_MODULE for alias in node.names
        ):
            return True
    return False


def test_the_backtest_only_strategy_subclass_has_exactly_one_importer() -> None:
    importers = []
    for root_dir in ("src", "scripts"):
        base = _REPO_ROOT / root_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path == _REPO_ROOT / "src/breezy/strategy/current_rung_hold/backtest_only.py":
                continue
            if _imports_backtest_only_strategy(path):
                importers.append(str(path.relative_to(_REPO_ROOT)))
    assert importers == [_EXPECTED_IMPORTER], (
        f"CurrentRungHoldBacktestStrategy must have exactly one non-test "
        f"importer ({_EXPECTED_IMPORTER!r}); found {importers!r}"
    )


def _facts_info(*, lower_f: int | None, upper_f: int | None) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: STATION,
        CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: lower_f,
        STRIKE_UPPER_F_KEY: upper_f,
    }


def _instrument() -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=INSTRUMENT_ID,
        raw_symbol=INSTRUMENT_ID.symbol,
        outcome="Yes",
        description="LAX daily high",
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
        info=_facts_info(lower_f=86, upper_f=87),
    )


@contextmanager
def _open_latch_context(store_path: Path) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch)


def _open_latch_factory(
    store_path: Path,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _open_latch_context(store_path)


def _register(
    store_path: Path, *, clock: TestClock,
) -> CurrentRungHoldBacktestStrategy:
    instrument = _instrument()
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,))
    strategy = CurrentRungHoldBacktestStrategy(
        cfg, trial_day_latch_factory=_open_latch_factory(store_path),
    )
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    return strategy


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


def test_on_start_succeeds_against_a_real_testclock(store_path: Path) -> None:
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    strategy = _register(store_path, clock=clock)
    strategy.on_start()  # must not raise
    assert strategy._latch is not None


def test_on_start_refuses_a_non_testclock(
    store_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    strategy = _register(store_path, clock=clock)
    # The real registered clock IS a TestClock; force the isinstance check
    # in the module under test to fail without needing a real LiveClock
    # wired through the whole nautilus registration path.
    monkeypatch.setattr(backtest_only_module, "TestClock", str)
    with pytest.raises(NotABacktestClockError):
        strategy.on_start()


def test_backtest_submit_enabled_actually_submits_unlike_the_parent(
    store_path: Path,
) -> None:
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    strategy = _register(store_path, clock=clock)
    strategy.on_start()
    submitted: list[object] = []
    strategy.submit_order = submitted.append
    from breezy.strategy.current_rung_hold.decision import Take

    decision = Take(
        quantity=1,
        limit_price=Decimal("0.40"),
        p_hold_lower=Decimal("0.70"),
        break_even=Decimal("0.42"),
        rung=(86, 87),
    )
    strategy._maybe_submit(str(INSTRUMENT_ID), decision)
    assert len(submitted) == 1
