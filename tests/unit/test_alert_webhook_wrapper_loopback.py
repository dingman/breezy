"""Acceptance 8(a) (SP-6 A9, row 16c): the `OnFailure=` chain EXECUTED
end-to-end against a REAL loopback listener -- never a routable address.
The one sanctioned `@pytest.mark.allow_socket` exception `tests/conftest.py`
documents.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import ClassVar

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "deploy" / "systemd" / "alert-webhook-run.sh"


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    received_bodies: ClassVar[list[bytes]] = []
    #: Small deliberate delay before responding, so a concurrent `ps`
    #: snapshot has a real chance of catching curl still in flight.
    response_delay_s: float = 0.3

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        type(self).received_bodies.append(body)
        time.sleep(self.response_delay_s)
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence -- this is a test fixture, not a real server


@pytest.mark.allow_socket
def test_the_wrapper_delivers_to_a_loopback_listener(tmp_path: Path) -> None:
    _RecordingHandler.received_bodies = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    port = server.server_port
    host_fragment = f"127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    ps_snapshot_path = tmp_path / "ps_snapshot.txt"

    def _snapshot_ps_mid_flight() -> None:
        time.sleep(0.1)  # give curl time to be spawned and connecting
        try:
            snapshot = subprocess.run(
                ["ps", "-eo", "args"], capture_output=True, text=True, timeout=5, check=False
            ).stdout
        except OSError:
            snapshot = ""
        ps_snapshot_path.write_text(snapshot)

    snapshotter = threading.Thread(target=_snapshot_ps_mid_flight, daemon=True)
    snapshotter.start()

    try:
        env = {**os.environ, "BREEZY_ALERT_WEBHOOK_URL": f"http://{host_fragment}/webhook"}
        result = subprocess.run(
            [str(_WRAPPER), "some.service"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        snapshotter.join(timeout=5)

        assert result.returncode == 0
        assert _RecordingHandler.received_bodies, "the listener never received a request"
        assert b"unit_failed:some.service" in _RecordingHandler.received_bodies[0]

        ps_snapshot = ps_snapshot_path.read_text() if ps_snapshot_path.exists() else ""
        assert host_fragment not in ps_snapshot
    finally:
        server.shutdown()
        thread.join(timeout=5)
