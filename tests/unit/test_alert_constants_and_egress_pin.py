"""AUT-6 WP1 fix round 1 (A5, C2): runtime constants respect the pins; the egress import pin."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy import pins
from breezy.runtime import alert_delivery, alert_drain, alert_outbox, alert_proof
from tests.support.entry_points import SRC_DIR

_BREEZY: Final = SRC_DIR / "breezy"
_NETWORK_ROOTS: Final = frozenset(
    {"httpx", "socket", "urllib", "http", "requests", "aiohttp", "websockets", "websocket"}
)
#: The modules under src/breezy that import a network client, EXACTLY as discovered at AUT-6 WP1
#: (2026-10-08). The AUT-6 alert layer adds ``alert_proof`` and ``alert_delivery`` (httpx, for the
#: one webhook POST and its client type) beside ``health`` (the sink they wrap). A new importer is a
#: reviewed change to this pin, never a silent one.
PINNED_NETWORK_IMPORTERS: Final[dict[str, tuple[str, ...]]] = {
    "adapters/polymarket_us/config.py": ("urllib.parse",),
    "adapters/polymarket_us/http.py": ("urllib.parse",),
    "adapters/polymarket_us/recorder_watchdog.py": ("socket",),
    "ingest/http.py": ("httpx", "urllib.parse"),
    "ingest/mdl_lamp_transport.py": ("httpx", "urllib.parse"),
    "ingest/nbm_quantile_transport.py": ("httpx",),
    "ingest/nws_observation_actor.py": ("urllib.parse",),
    "ingest/probe_transport.py": ("urllib.parse",),
    "runtime/alert_delivery.py": ("httpx",),
    "runtime/alert_proof.py": ("httpx",),
    "runtime/autonomy_sandbox/self_probe.py": ("socket",),
    "runtime/autonomy_sandbox/wal_snapshot.py": ("urllib.parse",),
    "runtime/health.py": ("httpx", "urllib.parse"),
}
_ALERT_MODULES: Final = (
    "runtime/alert_outbox.py",
    "runtime/alert_proof.py",
    "runtime/alert_drain.py",
    "runtime/alert_delivery.py",
    "runtime/alert_redeliver_cli.py",
)
_WEBHOOK_VAR: Final = "BREEZY_ALERT_WEBHOOK_URL"


def network_importers(root: Path) -> dict[str, tuple[str, ...]]:
    found: dict[str, tuple[str, ...]] = {}
    for path in sorted(root.rglob("*.py")):
        mods: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names if a.name.split(".")[0] in _NETWORK_ROOTS)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.level == 0
                and node.module.split(".")[0] in _NETWORK_ROOTS
            ):
                mods.add(node.module)
        if mods:
            found[path.relative_to(root).as_posix()] = tuple(sorted(mods))
    return found


def string_literals(source: str) -> list[str]:
    return [
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_alert_egress_import_pin() -> None:
    assert network_importers(_BREEZY) == PINNED_NETWORK_IMPORTERS


def test_alert_egress_import_pin_fires_on_a_planted_importer(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("import json\n")
    (tmp_path / "bad.py").write_text("import socket\n")
    (tmp_path / "bad2.py").write_text("from urllib.request import urlopen\n")
    assert network_importers(tmp_path) == {"bad.py": ("socket",), "bad2.py": ("urllib.request",)}


def test_alert_modules_hold_no_url_literal_and_no_webhook_variable_name() -> None:
    for relative in _ALERT_MODULES:
        for text in string_literals((_BREEZY / relative).read_text(encoding="utf-8")):
            assert "://" not in text, (relative, text)
            assert _WEBHOOK_VAR not in text, relative


def test_alert_literal_scan_fires_on_planted_url_and_variable_name() -> None:
    assert any("://" in t for t in string_literals("U = 'https://x.invalid/h'\n"))
    assert any(_WEBHOOK_VAR in t for t in string_literals(f"V = '{_WEBHOOK_VAR}'\n"))


def test_runtime_alert_constants_respect_the_pins_ceilings() -> None:
    assert alert_proof.ALERT_DELIVERY_TIMEOUT_S <= pins.ALERT_DELIVERY_TIMEOUT_S
    assert alert_outbox.ALERT_CLAIM_STALE_S >= 3 * alert_proof.ALERT_DELIVERY_TIMEOUT_S
    assert alert_outbox.ALERT_OUTBOX_MAX <= pins.ALERT_OUTBOX_MAX
    assert alert_outbox.ALERT_OUTBOX_CRITICAL_RESERVED < alert_outbox.ALERT_OUTBOX_MAX
    assert alert_drain.ALERT_OUTBOX_STALE_S <= pins.ALERT_OUTBOX_STALE_S
    assert alert_delivery.ALERT_DELIVERY_TIMEOUT_S == alert_proof.ALERT_DELIVERY_TIMEOUT_S


def test_the_sink_factory_passes_the_delivery_timeout_to_the_client() -> None:
    sink = alert_delivery.JournalingWebhookAlertSink("https://alerts.example.test/h")
    try:
        timeout = sink._client.timeout
        assert timeout.read == float(alert_proof.ALERT_DELIVERY_TIMEOUT_S)
    finally:
        sink.close()
