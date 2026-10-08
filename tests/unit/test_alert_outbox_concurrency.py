"""E-1: four drainers race 50 entries; one stalled claimant is reclaimed once."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_delivery import (
    ALERT_CLAIM_STALE_S,
    AlertOutbox,
    DeliveryRecordWriter,
    drain_outbox,
)
from breezy.runtime.health import LoggingAlertSink, TeeAlertSink, WebhookAlertSink

pytestmark = pytest.mark.allow_socket

_URL = "https://alerts.example.test/hook"


def _python() -> str:
    return os.environ.get("BREEZY_PYTHON", sys.executable)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    return env


def _seed(root: Path, count: int) -> None:
    outbox = AlertOutbox(root)
    now = time.time_ns()
    for index in range(count):
        outbox.write_entry(
            AlertPayload(
                severity="CRITICAL",
                event=f"RACE_{index}",
                site="race",
                detail="closed",
            ),
            writer="node",
            drill=False,
            ts_ns=now - (120 + index) * 1_000_000_000,
        )


def test_concurrent_drainers_send_at_most_once_per_claim_window(tmp_path: Path) -> None:
    """4 drainers x 50 entries, then one claimant stalled past the claim window."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    root = tmp_path / "alerts"
    root.mkdir()
    _seed(root, 50)
    posts: list[bytes] = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            with lock:
                posts.append(body)
            self.send_response(204)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = textwrap.dedent(
        """
        import os, sys
        import httpx
        from pathlib import Path
        from breezy.runtime.alert_delivery import AlertOutbox, DeliveryRecordWriter, drain_outbox
        from breezy.runtime.health import LoggingAlertSink, TeeAlertSink, WebhookAlertSink

        root = Path(sys.argv[1])
        drainer = sys.argv[2]
        port = sys.argv[3]

        def handler(request: httpx.Request) -> httpx.Response:
            httpx.post(f"http://127.0.0.1:{port}/count", content=request.content)
            return httpx.Response(204)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sink = TeeAlertSink(
            LoggingAlertSink(), WebhookAlertSink("https://alerts.example.test/hook", client=client)
        )
        try:
            drain_outbox(
                drainer=drainer,
                outbox=AlertOutbox(root),
                sink=sink,
                records=DeliveryRecordWriter(root),
                min_age_s=60,
            )
        finally:
            sink.close()
        """
    )
    procs = [
        subprocess.Popen(
            [_python(), "-c", script, str(root), f"drainer{index}", str(port)],
            env=_env(),
        )
        for index in range(4)
    ]
    for proc in procs:
        assert proc.wait(timeout=60) == 0, proc.returncode
    server.shutdown()
    events = [json.loads(body.decode())["event"] for body in posts]
    assert sorted(events) == sorted(f"RACE_{index}" for index in range(50))
    delivered = [path.name for path in root.rglob("*_d.json")]
    assert len(delivered) == 50
    assert AlertOutbox(root).occupancy() == 0

    stall_root = tmp_path / "stall"
    stall_root.mkdir()
    outbox = AlertOutbox(stall_root)
    entry = outbox.write_entry(
        AlertPayload(severity="CRITICAL", event="STALL_ONE", site="race", detail="closed"),
        writer="node",
        drill=False,
        ts_ns=time.time_ns() - 180 * 1_000_000_000,
    )
    child = textwrap.dedent(
        """
        import sys, time
        from pathlib import Path
        from breezy.runtime.alert_delivery import AlertOutbox
        root = Path(sys.argv[1])
        ready = Path(sys.argv[2])
        outbox = AlertOutbox(root)
        entry = next((root / "outbox").glob("*.json"))
        claimed = outbox.claim(entry, "stall")
        ready.write_text(str(claimed))
        go = ready.with_name("go")
        deadline = time.time() + 30
        while not go.exists() and time.time() < deadline:
            time.sleep(0.02)
        if outbox.restamp(Path(ready.read_text())):
            ready.with_name("sent").write_text("sent")
        else:
            ready.with_name("enoent").write_text("enoent")
        """
    )
    ready = stall_root / "ready"
    proc = subprocess.Popen([_python(), "-c", child, str(stall_root), str(ready)], env=_env())
    deadline = time.time() + 10
    while time.time() < deadline and not ready.is_file():
        time.sleep(0.05)
    assert ready.is_file()
    claimed = Path(ready.read_text())
    old = time.time() - (ALERT_CLAIM_STALE_S + 1)
    os.utime(claimed, (old, old))
    posts.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def handler(request: httpx.Request) -> httpx.Response:
        import httpx as httpx_mod

        httpx_mod.post(f"http://127.0.0.1:{port}/count", content=request.content)
        return httpx.Response(204)

    import httpx

    sink = TeeAlertSink(
        LoggingAlertSink(),
        WebhookAlertSink(_URL, client=httpx.Client(transport=httpx.MockTransport(handler))),
    )
    try:
        summary = drain_outbox(
            drainer="rescue",
            outbox=outbox,
            sink=sink,
            records=DeliveryRecordWriter(stall_root),
            min_age_s=60,
        )
    finally:
        sink.close()
    (stall_root / "go").write_text("go", encoding="utf-8")  # release the stalled claimant
    assert proc.wait(timeout=30) == 0
    server.shutdown()
    assert summary.reclaims == 1
    assert len(posts) == 1
    assert AlertOutbox(stall_root).occupancy() == 0
    assert (stall_root / "enoent").is_file()
    assert not (stall_root / "sent").exists()
    del entry
