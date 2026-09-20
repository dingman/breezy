"""A REAL loopback HTTPS receiver for alert-egress delivery tests.

WP-B0. Every alert Breezy has ever emitted went to a log file nobody reads.
The acceptance for fixing that is an **out-of-process artefact**, not a log
line and not a mocked transport: this module stands up an actual TCP
listener on ``127.0.0.1``, wrapped in an actual ``ssl`` server context using
a freshly generated self-signed certificate, and records the bytes a sink
actually put on the wire.

**Why real TLS and not plain http.** ``WebhookAlertSink`` refuses any URL
whose scheme is not ``https`` (``health._validate_webhook_url``), and that
validation must not be weakened to make a test convenient. So the receiver
speaks TLS for real; the ONLY concession to running off-box-free is the
trust anchor -- the client is given the throwaway CA this module just
minted instead of the system store. Everything else (URL validation,
scheme, hostname check, ``CERT_REQUIRED``, TLS>=1.2, JSON serialisation,
the HTTP request/response round trip) is production behaviour.

The certificate is minted at RUN time with ``openssl`` rather than
committed: a private key in the repo is a credential-shaped artefact even
when it is worthless, and a committed cert eventually expires and rots the
suite. ``openssl`` missing is a hard failure, never a skip -- a guard that
silently does not run is not a guard.
"""

from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Final

#: Loopback only. There is no code path in this module that can name any
#: other host, so it cannot become an egress channel by accident.
LOOPBACK_HOST: Final[str] = "127.0.0.1"

_CERT_VALID_DAYS: Final[str] = "1"


@dataclass(frozen=True)
class TlsMaterial:
    """Paths to a throwaway self-signed cert/key plus its own CA file."""

    cert_path: Path
    key_path: Path

    @property
    def ca_path(self) -> Path:
        """The self-signed cert IS its own trust anchor."""
        return self.cert_path


def generate_loopback_tls_material(directory: Path) -> TlsMaterial:
    """Mint a self-signed cert for ``IP:127.0.0.1`` into ``directory``."""
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError(
            "openssl is required for the alert-egress delivery test; refusing to "
            "skip -- a delivery guard that does not run is not a guard."
        )
    cert_path = directory / "loopback-cert.pem"
    key_path = directory / "loopback-key.pem"
    subprocess.run(  # fixed argv, no shell, binary resolved via shutil.which.
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            _CERT_VALID_DAYS,
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={LOOPBACK_HOST}",
            "-addext",
            f"subjectAltName=IP:{LOOPBACK_HOST}",
        ],
        check=True,
        capture_output=True,
    )
    return TlsMaterial(cert_path=cert_path, key_path=key_path)


def client_ssl_context(material: TlsMaterial) -> ssl.SSLContext:
    """A client context identical to production's except the trust anchor.

    Mirrors ``health._build_webhook_ssl_context``: hostname checking ON,
    ``CERT_REQUIRED``, TLS 1.2 floor. Only ``cafile`` differs.
    """
    context = ssl.create_default_context(cafile=str(material.ca_path))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


@dataclass
class ReceivedRequest:
    """One request the receiver actually took off the socket."""

    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes

    def json_body(self) -> dict[str, object]:
        decoded = json.loads(self.body.decode("utf-8"))
        if not isinstance(decoded, dict):  # pragma: no cover - defensive
            raise TypeError("alert payload must be a JSON object")
        return decoded


class LoopbackHttpsReceiver:
    """A running TLS listener plus the requests it has received."""

    def __init__(self, server: HTTPServer, received: list[ReceivedRequest]) -> None:
        self._server = server
        self.received = received

    @property
    def url(self) -> str:
        host, port = self._server.server_address[0], self._server.server_address[1]
        return f"https://{host}:{port}/alerts"


@contextmanager
def loopback_https_receiver(
    material: TlsMaterial,
    *,
    status_code: int = 200,
    response_delay_s: float = 0.0,
) -> Iterator[LoopbackHttpsReceiver]:
    """Serve TLS on an ephemeral loopback port for the duration of the block."""
    received: list[ReceivedRequest] = []

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            received.append(
                ReceivedRequest(
                    method="POST",
                    path=self.path,
                    headers={k.lower(): v for k, v in self.headers.items()},
                    body=body,
                )
            )
            if response_delay_s:
                threading.Event().wait(response_delay_s)
            self.send_response(status_code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            """Silence the stderr access log."""

    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(
        certfile=str(material.cert_path), keyfile=str(material.key_path)
    )

    server = HTTPServer((LOOPBACK_HOST, 0), _Handler)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield LoopbackHttpsReceiver(server, received)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
