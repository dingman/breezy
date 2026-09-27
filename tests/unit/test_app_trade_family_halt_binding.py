"""EDGE-3 §6.2: the boot binds the continuous family's halt latch to the
manifest's OWN ``family_id`` -- never a composition-kind-scoped, cardinality-1
singleton.

Reuses the harness from ``test_trade_cli_current_rung_hold.py`` (env
builder, catalog writer, ``RecordingNode``) and the ``_v4_env``/
``_continuous_env`` builders from ``test_app_trade_fee_drift_probe_wiring.py``
-- the same reuse pattern ``test_app_trade_fee_drift_probe_wiring.py``
itself documents.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from breezy.app.trade import run
from breezy.runtime.health import AlertPayload
from breezy.runtime.settings import SENDING_FAMILY_ID_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.trade_cli import EXIT_CONFIG_ERROR, EXIT_OK
from breezy.strategy.current_rung_hold.trial_day_latch import LEGACY_FAMILY_HALT_KEY
from tests.unit.test_app_trade_fee_drift_probe_wiring import _v4_env
from tests.unit.test_trade_cli_current_rung_hold import (
    RecordingNode,
    _operator_order_ceiling,  # noqa: F401 -- autouse fixture
    _trade_env,
    _write_today_catalog,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "family_halt"
    / "legacy_v4_halt_2026-09-24.bin"
)


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def _state_snapshot(store_path: Path) -> set[tuple[str, bytes]]:
    conn = sqlite3.connect(store_path)
    try:
        return set(conn.execute("SELECT key, value FROM state").fetchall())
    finally:
        conn.close()


def _seed_legacy(store_path: Path, raw: bytes) -> None:
    store = SqliteStateStore(store_path)
    try:
        store.set(LEGACY_FAMILY_HALT_KEY, raw)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 15. test_boot_binds_cont_factory_and_veto_latch_to_the_manifest_family_id
# ---------------------------------------------------------------------------


def test_boot_binds_cont_factory_and_veto_latch_to_the_manifest_family_id(
    tmp_path: Path,
) -> None:
    env = _v4_env(tmp_path)
    from breezy.strategy.current_rung_hold import composition as composition_module
    from breezy.strategy.current_rung_hold import trial_day_latch as latch_module

    recorded_factory_family_ids: list[str | None] = []
    recorded_open_family_ids: list[str | None] = []

    real_make_factory = composition_module.make_trial_day_latch_factory
    real_open = latch_module.open_trial_day_latch

    def _factory_spy(intent_latch, *, key_prefix=None, family_id=None, **kw):
        recorded_factory_family_ids.append(family_id)
        kwargs = {"family_id": family_id}
        if key_prefix is not None:
            kwargs["key_prefix"] = key_prefix
        return real_make_factory(intent_latch, **kwargs)

    def _open_spy(intent_latch, *, key_prefix=None, family_id=None, **kw):
        recorded_open_family_ids.append(family_id)
        kwargs = {"family_id": family_id}
        if key_prefix is not None:
            kwargs["key_prefix"] = key_prefix
        return real_open(intent_latch, **kwargs)

    with (
        patch("breezy.app.trade.make_trial_day_latch_factory", _factory_spy),
        patch("breezy.app.trade.open_trial_day_latch", _open_spy),
    ):
        code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    assert recorded_factory_family_ids == ["pm_us_crh_v4"]
    assert recorded_open_family_ids == ["pm_us_crh_v4"]


# ---------------------------------------------------------------------------
# 16. test_boot_refuses_when_manifest_family_id_differs_from_sending_family_id
# ---------------------------------------------------------------------------


def test_boot_refuses_when_manifest_family_id_differs_from_sending_family_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(Path("deploy/families/pm_us_crh_v4.json").read_text())
    payload["family_id"] = "pm_us_crh_mismatch"
    families = tmp_path / "families"
    families.mkdir()
    (families / "pm_us_crh_v4.json").write_text(json.dumps(payload))
    monkeypatch.setattr("breezy.runtime.settings._FAMILIES_DIR", families)
    monkeypatch.setattr("breezy.app.trade._FAMILIES_DIR", families)

    env = _v4_env(tmp_path)
    err = io.StringIO()
    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    assert "does not match manifest family_id" in err.getvalue()


# ---------------------------------------------------------------------------
# 17. test_v4_boot_with_pinned_legacy_reads_halted_before_composition_and_writes_nothing
# ---------------------------------------------------------------------------


def test_v4_boot_with_pinned_legacy_reads_halted_before_composition_and_writes_nothing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = _v4_env(tmp_path)
    store_path = Path(env["POLYMARKET_US_EXEC_STATE_DB"])
    _seed_legacy(store_path, _fixture_bytes())
    before = _state_snapshot(store_path)

    with caplog.at_level("INFO", logger="breezy.app.trade.boot"):
        code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    after = _state_snapshot(store_path)
    assert before == after, "AC-9: no write at the first new-code boot"

    halt_lines = [r.message for r in caplog.records if "family_halt_state" in r.message]
    assert len(halt_lines) == 1
    assert "family_id=pm_us_crh_v4" in halt_lines[0]
    assert "halted=True" in halt_lines[0]
    assert "source=legacy_attributed" in halt_lines[0]
    assert "legacy=attributable_to_v4" in halt_lines[0]

    node = RecordingNode.instances[-1]
    assert "build" in node.calls, "the boot still reaches build() (L-48: never refuses)"


# ---------------------------------------------------------------------------
# 18. test_fresh_family_boots_unhalted_while_the_pinned_legacy_stays_in_place
# ---------------------------------------------------------------------------


def test_fresh_family_boots_unhalted_while_the_pinned_legacy_stays_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = json.loads(Path("deploy/families/pm_us_crh_v4.json").read_text())
    payload["family_id"] = "pm_us_crh_fresh"
    families = tmp_path / "families"
    families.mkdir()
    (families / "pm_us_crh_fresh.json").write_text(json.dumps(payload))
    monkeypatch.setattr("breezy.runtime.settings._FAMILIES_DIR", families)
    monkeypatch.setattr("breezy.app.trade._FAMILIES_DIR", families)

    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    from breezy.runtime.settings import LIVE_OBSERVATIONS_VAR, TRADE_CATALOG_ROOT_VAR

    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_fresh",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    store_path = Path(env["POLYMARKET_US_EXEC_STATE_DB"])
    pinned = _fixture_bytes()
    _seed_legacy(store_path, pinned)

    with caplog.at_level("INFO", logger="breezy.app.trade.boot"):
        code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    halt_lines = [r.message for r in caplog.records if "family_halt_state" in r.message]
    assert len(halt_lines) == 1
    assert "family_id=pm_us_crh_fresh" in halt_lines[0]
    assert "halted=False" in halt_lines[0]
    assert "source=none" in halt_lines[0]

    # The pinned legacy value is unchanged -- it still exists to protect v4.
    assert _committed_legacy(store_path) == pinned


def _committed_legacy(store_path: Path) -> bytes | None:
    conn = sqlite3.connect(store_path)
    try:
        row = conn.execute(
            "SELECT value FROM state WHERE key = ?",
            (LEGACY_FAMILY_HALT_KEY,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else None


# ---------------------------------------------------------------------------
# 19. test_boot_with_unpinned_legacy_boots_halted_alerts_critical_and_exits_ok
# ---------------------------------------------------------------------------


def test_boot_with_unpinned_legacy_boots_halted_alerts_critical_and_exits_ok(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = _v4_env(tmp_path)
    store_path = Path(env["POLYMARKET_US_EXEC_STATE_DB"])
    _seed_legacy(store_path, b"an-unattributable-corrupt-legacy-value")

    emitted: list[AlertPayload] = []

    def _fake_emit_alert(sink, payload) -> None:
        del sink
        emitted.append(payload)

    with (
        patch("breezy.app.trade.emit_alert", _fake_emit_alert),
        caplog.at_level("INFO", logger="breezy.app.trade.boot"),
    ):
        code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK, "L-48: an unattributable legacy value never refuses to boot"
    critical = [p for p in emitted if p.event == "LEGACY_FAMILY_HALT_UNATTRIBUTABLE"]
    assert len(critical) == 1
    assert critical[0].severity == "CRITICAL"
    assert "pm_us_crh_v4" in critical[0].detail

    halt_lines = [r.message for r in caplog.records if "family_halt_state" in r.message]
    assert len(halt_lines) == 1
    assert "halted=True" in halt_lines[0]
    assert "source=legacy_halts_all" in halt_lines[0]
    assert "legacy=halts_all" in halt_lines[0]

    node = RecordingNode.instances[-1]
    assert "build" in node.calls
