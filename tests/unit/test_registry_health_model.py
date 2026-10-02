"""R1.5b C1: the pure health data types live in ``breezy.registry.health_model``.

They sit below ``ingest`` (layer) and import-light (``registry`` loads no
Nautilus/httpx), and ``breezy.runtime.health`` re-exports them verbatim.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path
from typing import Final

import pytest

from breezy.registry import health_model
from breezy.runtime import health

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MODEL_PATH: Final[Path] = REPO_ROOT / "src" / "breezy" / "registry" / "health_model.py"

MOVED_NAMES: Final[tuple[str, ...]] = (
    "SCHEMA_VERSION",
    "ALLOWED_ALERT_PAYLOAD_KEYS",
    "MAX_ALERT_DETAIL_CHARS",
    "UA_TRAP_LATCHED",
    "SITE_BLOCKED",
    "FINAL_OVERDUE",
    "GAP_RETENTION_WARNING",
    "POLL_STALE",
    "POST_SETTLEMENT_REVISION",
    "GapSummary",
    "SiteHealth",
    "HealthSnapshot",
    "AlertPayload",
    "AlertSink",
    "AlertConditionKey",
    "AlertCondition",
)

#: ``__all__`` of ``runtime.health``: the pre-move set plus C2's ``new_alert_state``.
EXPECTED_HEALTH_ALL: Final[frozenset[str]] = frozenset(
    {
        "ALERT_EGRESS_UNCONFIGURED_EVENT",
        "ALERT_WEBHOOK_URL_ENV_VAR",
        "ALLOWED_ALERT_PAYLOAD_KEYS",
        "DEFAULT_RENOTIFY_AFTER_NS",
        "MAX_ALERT_DETAIL_CHARS",
        "SCHEMA_VERSION",
        "SNAPSHOT_DIR_MODE",
        "SNAPSHOT_FILE_MODE",
        "AlertCondition",
        "AlertConditionKey",
        "AlertPayload",
        "AlertSink",
        "AlertState",
        "GapSummary",
        "HealthSnapshot",
        "LoggingAlertSink",
        "SiteHealth",
        "WebhookAlertSink",
        "alert_egress_configured",
        "emit_alert",
        "log_alert_egress_status",
        "new_alert_state",
        "resolve_alert_sink",
        "write_snapshot_atomic",
    }
)

#: Snapshot JSON captured from ``runtime.health`` BEFORE the move.
GOLDEN_SNAPSHOT_JSON: Final[str] = (
    '{"alerts_emitted_this_cycle": 4, "process_started_at_ns": 1, "schema_version": 2, '
    '"sites": [{"acknowledged_lost_count": 2, "blocking_causes": ["a", "b"], "city": "NYC", '
    '"cursor": "cur", "gate_reason": "ok", "gate_state": "OPEN", "last_successful_poll_ns": 5, '
    '"ledger_unavailable": null, "open_gaps": [{"climate_day": "2026-09-01", '
    '"days_until_retention_loss": 3, "severity": "WARN", "state": "OPEN"}], '
    '"venue": "polymarket_us"}, {"acknowledged_lost_count": 0, "blocking_causes": [], '
    '"city": "SFO", "cursor": null, "gate_reason": "ua", "gate_state": "BLOCKED", '
    '"last_successful_poll_ns": null, "ledger_unavailable": "ledger x", "open_gaps": [], '
    '"venue": "polymarket_us"}], "snapshot_at_ns": 2, "trader_id": "T-1", '
    '"ua_trap_latched": true}'
)
GOLDEN_SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "process_started_at_ns",
        "snapshot_at_ns",
        "trader_id",
        "sites",
        "ua_trap_latched",
        "alerts_emitted_this_cycle",
    }
)

ALLOWED_MODEL_IMPORTS: Final[frozenset[str]] = frozenset(
    {"__future__", "dataclasses", "typing", "collections", "collections.abc", "pathlib"}
)

ALLOWED_BREEZY_MODULES: Final[frozenset[str]] = frozenset(
    {"breezy", "breezy.registry", "breezy.registry.sites", "breezy.registry.health_model"}
)


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_runtime_health_reexports_the_identical_object(name: str) -> None:
    assert getattr(health, name) is getattr(health_model, name)


def test_runtime_health_all_is_the_pre_move_set_plus_new_alert_state() -> None:
    assert frozenset(health.__all__) == EXPECTED_HEALTH_ALL


def test_alert_payload_allowlist_equals_dataclass_fields() -> None:
    assert health_model.ALLOWED_ALERT_PAYLOAD_KEYS == {
        f.name for f in fields(health_model.AlertPayload)
    }


def _golden_snapshot() -> health_model.HealthSnapshot:
    gap = health_model.GapSummary("2026-09-01", "OPEN", "WARN", 3)
    return health_model.HealthSnapshot(
        schema_version=health_model.SCHEMA_VERSION,
        process_started_at_ns=1,
        snapshot_at_ns=2,
        trader_id="T-1",
        sites=(
            health_model.SiteHealth(
                "polymarket_us", "NYC", "OPEN", "ok", ("a", "b"), 5, "cur", (gap,), 2, None
            ),
            health_model.SiteHealth(
                "polymarket_us", "SFO", "BLOCKED", "ua", (), None, None, (), 0, "ledger x"
            ),
        ),
        ua_trap_latched=True,
        alerts_emitted_this_cycle=4,
    )


def test_snapshot_json_bytes_match_the_pre_move_golden() -> None:
    snapshot = _golden_snapshot()
    rendered = json.dumps(snapshot.to_dict(), sort_keys=True)
    assert rendered == GOLDEN_SNAPSHOT_JSON
    assert frozenset(snapshot.to_dict()) == GOLDEN_SNAPSHOT_KEYS


def test_health_model_imports_only_allowlisted_stdlib() -> None:
    tree = ast.parse(MODEL_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    assert imported <= ALLOWED_MODEL_IMPORTS, imported - ALLOWED_MODEL_IMPORTS


def test_health_model_import_is_light_in_a_fresh_interpreter() -> None:
    code = (
        "import sys, json\n"
        "import breezy.registry.health_model\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'nautilus_trader', 'httpx', 'ssl', 'pyarrow'})\n"
        "mine = sorted(m for m in sys.modules if m == 'breezy' or m.startswith('breezy.'))\n"
        "print(json.dumps({'heavy': heavy, 'mine': mine}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    reason = (
        "registry hosts the health data types for layer AND import weight: "
        "ingest/domain load Nautilus, which would break runtime import isolation"
    )
    assert loaded["heavy"] == [], f"{reason}: {loaded['heavy']}"
    assert set(loaded["mine"]) <= ALLOWED_BREEZY_MODULES, f"{reason}: {loaded['mine']}"
