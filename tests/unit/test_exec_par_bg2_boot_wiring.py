"""EXEC-PAR BG-2: ``app.trade.run`` writes the epoch row before ``node.run`` and ``stop_ts`` after.

Reuses the WP5b wiring harness. The ledger is read back through the same read-only
reader the analysis scripts use.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from breezy.app import trade as app_trade
from breezy.app.trade import run
from breezy.runtime import node_config
from breezy.runtime.build_sha import BUILD_REVISION_ENV_VAR
from breezy.runtime.exec_par_epochs import EpochLedger, read_epoch_ledger
from breezy.runtime.trade_cli import EXIT_OK
from tests.unit.test_exec_par_wp5b_wiring import _env
from tests.unit.test_trade_cli_current_rung_hold import (
    RecordingNode,
    _operator_order_ceiling,  # noqa: F401 -- autouse fixture
)

REVISION = "deadbeef1234"


@pytest.fixture(autouse=True)
def _revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BUILD_REVISION_ENV_VAR, REVISION)


def _ledger(env: dict[str, str]) -> EpochLedger:
    return read_epoch_ledger(Path(env["POLYMARKET_US_EXEC_STATE_DB"]))


def _store_bytes(env: dict[str, str]) -> dict[str, bytes]:
    import sqlite3

    conn = sqlite3.connect(env["POLYMARKET_US_EXEC_STATE_DB"])
    try:
        return {k: bytes(v) for k, v in conn.execute("SELECT key, value FROM state")}
    finally:
        conn.close()


def test_k1_boot_writes_the_epoch_row_and_closes_it_at_disposal(tmp_path: Path) -> None:
    env = _env(tmp_path)

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    (row,) = _ledger(env).epochs
    assert (row.commit_sha, row.effective_k, row.force_reason) == (REVISION, 1, None)
    assert row.stop_ts is not None and row.stop_ts >= row.boot_ts


def test_k1_boot_writes_no_stage_reset_and_only_the_epoch_key_is_new(tmp_path: Path) -> None:
    env = _env(tmp_path)

    run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    exec_par_keys = sorted(k for k in _store_bytes(env) if "/exec_par/" in k)
    assert len(exec_par_keys) == 1 and "/exec_par/epoch/" in exec_par_keys[0]


class _InspectingNode(RecordingNode):
    seen_at_run: EpochLedger | None = None
    env: dict[str, str] | None = None

    def run(self) -> None:
        assert _InspectingNode.env is not None
        _InspectingNode.seen_at_run = _ledger(_InspectingNode.env)
        super().run()


def test_the_row_exists_before_node_run_without_a_stop_ts(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _InspectingNode.env = env

    run(env=env, node_factory=_InspectingNode, stderr=io.StringIO())

    seen = _InspectingNode.seen_at_run
    assert seen is not None
    (row,) = seen.epochs
    assert row.stop_ts is None


def test_an_unclean_prior_is_closed_by_the_next_boot_and_a_same_k_reboot_resets_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_trade, "EXEC_PAR_MAX_CONCURRENT_INTENTS", 2)
    monkeypatch.setattr(node_config, "supervisor_admits_slot_schema", lambda _path: True)
    env = _env(tmp_path)
    _InspectingNode.env = env
    run(env=env, node_factory=_InspectingNode, stderr=io.StringIO())  # first boot
    first = _ledger(env).epochs[0]
    # simulate the crash: the first row never got its stop_ts
    import sqlite3

    conn = sqlite3.connect(env["POLYMARKET_US_EXEC_STATE_DB"])
    try:
        from breezy.runtime.exec_par_records import EXEC_PAR_PREFIX, encode_record

        key = f"{EXEC_PAR_PREFIX}epoch/{first.boot_ts}"
        from dataclasses import replace

        conn.execute(
            "UPDATE state SET value = ? WHERE key = ?",
            (encode_record(replace(first, stop_ts=None)), key),
        )
        conn.commit()
    finally:
        conn.close()

    run(env=env, node_factory=RecordingNode, stderr=io.StringIO())  # reboot, same K

    ledger = _ledger(env)
    assert [r.effective_k for r in ledger.epochs] == [2, 2]
    assert ledger.epochs[0].stop_ts is None
    assert not any(k.endswith("/stage_reset") for k in _store_bytes(env))


def test_a_k_change_boot_writes_the_k_change_stage_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(tmp_path)
    run(env=env, node_factory=RecordingNode, stderr=io.StringIO())  # K=1
    monkeypatch.setattr(app_trade, "EXEC_PAR_MAX_CONCURRENT_INTENTS", 2)
    monkeypatch.setattr(node_config, "supervisor_admits_slot_schema", lambda _path: True)

    run(env=env, node_factory=RecordingNode, stderr=io.StringIO())  # K=2

    stored = _store_bytes(env)
    (reset_key,) = [k for k in stored if k.endswith("/exec_par/stage_reset")]
    assert b"k_change" in stored[reset_key]
    assert [r.effective_k for r in _ledger(env).epochs] == [1, 2]


def test_a_forced_to_1_boot_records_the_force_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_trade, "EXEC_PAR_MAX_CONCURRENT_INTENTS", 2)
    monkeypatch.setattr(node_config, "supervisor_admits_slot_schema", lambda _path: False)
    env = _env(tmp_path)

    run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    (row,) = _ledger(env).epochs
    assert row.effective_k == 1
    assert row.force_reason == node_config.EXEC_PAR_MARKER_ABSENT_REASON


def test_the_k_gt_1_watcher_is_armed_with_the_build_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.runtime.breaker_watcher import BreakerWatcherActor

    monkeypatch.setattr(app_trade, "EXEC_PAR_MAX_CONCURRENT_INTENTS", 2)
    monkeypatch.setattr(node_config, "supervisor_admits_slot_schema", lambda _path: True)

    run(env=_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    watchers = [
        a for a in RecordingNode.instances[-1].trader.actors if isinstance(a, BreakerWatcherActor)
    ]
    assert len(watchers) == 1
    assert watchers[0]._commit_sha == REVISION
