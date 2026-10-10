"""EXEC-PAR WP5b: ``app.trade.run`` wiring of the latch K, the marker gate and the watcher.

Reuses the ``test_trade_cli_current_rung_hold`` harness exactly as the fee-drift
wiring suite does. The shipped constant is K=1, so the default path must
register only the alert-only watcher; the K>1 path is reached by patching the
module constant the composition root reads.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.app import trade as app_trade
from breezy.app.trade import run
from breezy.runtime import node_config
from breezy.runtime.breaker_watcher import BreakerWatcherActor, ExecRefusalAlertActor
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    SubmitIntentLatch,
    open_submit_intent_latch,
)
from breezy.runtime.trade_cli import EXIT_OK
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- reused harness
    RecordingNode,
    _operator_order_ceiling,
    _trade_env,
    _write_today_catalog,
)


def _env(tmp_path: Path) -> dict[str, str]:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    return _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_cont",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )


def _watchers(node: RecordingNode) -> list[ExecRefusalAlertActor]:
    return [a for a in node.trader.actors if isinstance(a, ExecRefusalAlertActor)]


def test_k1_registers_the_alert_only_watcher_and_no_breaker(tmp_path: Path) -> None:
    code = run(env=_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    watchers = _watchers(node)
    assert len(watchers) == 1
    assert not isinstance(watchers[0], BreakerWatcherActor)


def test_k_gt_1_with_the_marker_registers_the_breaker_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_trade, "EXEC_PAR_MAX_CONCURRENT_INTENTS", 2)
    monkeypatch.setattr(node_config, "supervisor_admits_slot_schema", lambda _path: True)

    code = run(env=_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    (watcher,) = _watchers(RecordingNode.instances[-1])
    assert isinstance(watcher, BreakerWatcherActor)


def test_k_gt_1_without_the_marker_is_forced_to_1_and_registers_no_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_trade, "EXEC_PAR_MAX_CONCURRENT_INTENTS", 2)
    monkeypatch.setattr(node_config, "supervisor_admits_slot_schema", lambda _path: False)

    code = run(env=_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    (watcher,) = _watchers(RecordingNode.instances[-1])
    assert not isinstance(watcher, BreakerWatcherActor)


def test_the_bound_watcher_without_a_registered_exec_client_does_not_raise(
    tmp_path: Path,
) -> None:
    """``RecordingNode``'s fake kernel has no exec engine: the lazy getter yields
    ``None`` and a tick reports "not evaluated" instead of raising."""
    run(env=_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())
    (watcher,) = _watchers(RecordingNode.instances[-1])
    watcher.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestClock(),
    )
    assert asyncio.run(watcher.tick()) is False


def test_k1_run_writes_no_breaker_record(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run(env=env, node_factory=RecordingNode, stderr=io.StringIO())
    store_files = list(tmp_path.rglob("*.db")) + list(tmp_path.rglob("*.sqlite3"))
    for path in store_files:
        assert BREAKER_KEY.encode() not in path.read_bytes()


def test_k1_opens_the_latch_with_no_slot_keywords_and_k_gt_1_adds_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[int | None, bool]] = []
    real_open = open_submit_intent_latch

    def spy(
        store: SqliteStateStore,
        path: Path,
        *,
        max_slots: int | None = None,
        v2_predicate: Callable[[], bool] | None = None,
    ) -> AbstractContextManager[SubmitIntentLatch]:
        seen.append((max_slots, v2_predicate is not None))
        if max_slots is None:
            return real_open(store, path)
        return real_open(store, path, max_slots=max_slots, v2_predicate=v2_predicate)

    monkeypatch.setattr(app_trade, "open_submit_intent_latch", spy)
    run(env=_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())
    assert seen == [(None, False)], "K=1 must call the factory exactly as before EXEC-PAR"

    seen.clear()
    monkeypatch.setattr(app_trade, "EXEC_PAR_MAX_CONCURRENT_INTENTS", 2)
    monkeypatch.setattr(node_config, "supervisor_admits_slot_schema", lambda _path: True)
    second = tmp_path / "second"
    second.mkdir()
    run(env=_env(second), node_factory=RecordingNode, stderr=io.StringIO())
    assert seen == [(2, True)]
