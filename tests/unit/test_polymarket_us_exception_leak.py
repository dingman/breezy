"""Raw transport exception text must never reach a log record or an error message.

Why this suite exists
---------------------
An authenticated ``WebSocketConfig`` carries ``X-PM-Access-Key`` and
``X-PM-Signature`` in its handshake headers. Every failure the ``nautilus_pyo3``
transport raises at that moment arrives as a ``WebSocketClientError`` whose
``str()`` is, verbatim, whatever string the Rust layer chose to construct --
``WebSocketClientError`` is a plain ``create_exception!`` type with no Python-side
``__str__``, so ``args[0]`` passes through untouched.

Empirically (2026-08-25, ``nautilus-trader`` 1.231.0, five offline failure paths
driven against ``127.0.0.1``/``.invalid``): connection-refused, invalid header
VALUE, invalid header NAME, DNS failure and malformed URL all produced messages
that did NOT echo header content -- but the malformed-URL path DID echo the URL
verbatim (``'invalid URL: not-a-url: relative URL without a base'``). So the
transport demonstrably interpolates caller-supplied request material into its
message text, and the set of paths that could reach a header is not enumerable
from outside the crate (TLS errors, proxy errors and venue-sent close reasons
were not reachable offline).

Breezy therefore does not depend on that audit. The rule is structural and is
the same one the HTTP path already follows at ``transport.py:246-249``:
**a raw transport exception is rendered as its type name and nothing else.**
``redaction.py`` cannot help here -- it redacts header maps and known secret
values, and free-form exception text passing through an f-string is neither.

The canaries below are locally generated strings, never real credentials.
"""

from __future__ import annotations

import asyncio
import base64
import traceback
from typing import Any

import pytest
from nacl.signing import SigningKey
from nautilus_trader.common.component import LiveClock, Logger
from nautilus_trader.core.nautilus_pyo3 import WebSocketClientError

from breezy.adapters.polymarket_us import websocket as ws_module
from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
from breezy.adapters.polymarket_us.websocket import PolymarketUSMarketsWebSocket

_KEY_ID = "11111111-2222-3333-4444-555555555555"

#: Stand-ins shaped like the real header values, generated here and used nowhere
#: else. ``SIGNATURE_CANARY`` is base64-shaped like an Ed25519 signature;
#: ``ACCESS_KEY_CANARY`` is UUID-shaped like a key id.
SIGNATURE_CANARY = "c2lnbmF0dXJlQ0FOQVJZZG9Ob3RMZWFrTWVBQUFBQkJCQkNDQ0M9PQ=="
ACCESS_KEY_CANARY = "deadbeef-cafe-4bad-9999-c0ffeec0ffee"

#: A message shaped the way a Rust transport error that DID echo the handshake
#: would look. The point is not that this exact text occurs today; it is that
#: the adapter must be incapable of republishing it if it ever does.
LEAKY_TRANSPORT_MESSAGE = (
    "handshake failed: rejected request "
    f"[X-PM-Access-Key: {ACCESS_KEY_CANARY}, X-PM-Signature: {SIGNATURE_CANARY}]"
)


def _assert_no_canary(text: str, *, context: str) -> None:
    assert SIGNATURE_CANARY not in text, f"{context} leaked the signature: {text!r}"
    assert ACCESS_KEY_CANARY not in text, f"{context} leaked the access key: {text!r}"


def _new_signer() -> Ed25519RequestSigner:
    key = SigningKey.generate()
    return Ed25519RequestSigner(
        PolymarketUSCredentials(
            key_id=RedactedSecureString(_KEY_ID),
            secret_key=RedactedSecureString(base64.b64encode(bytes(key)).decode("ascii")),
        ),
        clock=LiveClock(),
    )


class _RecordingLogger(Logger):
    """A ``Logger`` that keeps every message it was handed.

    Subclasses rather than mocks the real type so the client under test is
    exercised through its genuine logging surface.
    """

    def __init__(self) -> None:
        super().__init__("test-polymarket-us-leak")
        self.records: list[str] = []

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.records.append(message)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.records.append(message)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.records.append(message)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.records.append(message)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.records.append(message)


def _make_ws(
    *,
    logger: Logger,
    handler: Any = None,
) -> PolymarketUSMarketsWebSocket:
    return PolymarketUSMarketsWebSocket(
        ws_url="ws://127.0.0.1:1",
        signer=_new_signer(),
        handler=handler if handler is not None else (lambda _raw: None),
        loop=asyncio.get_running_loop(),
        heartbeat_secs=10,
        idle_timeout_secs=60,
        logger=logger,
        request_id_factory=lambda: "req-1",
        supervisor_poll_secs=0.02,
        reconnect_max_attempts=1,
        reconnect_delay_initial_ms=1,
        reconnect_delay_max_ms=2,
        reconnect_backoff_factor=2,
    )


class _LeakyClient:
    """Stands in for ``nautilus_pyo3.WebSocketClient`` on the failure paths."""

    def __init__(self, *, closed: bool = False) -> None:
        self._closed = closed

    @classmethod
    async def connect(cls, **_kwargs: Any) -> _LeakyClient:
        raise WebSocketClientError(LEAKY_TRANSPORT_MESSAGE)

    def is_closed(self) -> bool:
        return self._closed

    def is_reconnecting(self) -> bool:
        return False

    async def send_text(self, _payload: bytes) -> None:
        raise WebSocketClientError(LEAKY_TRANSPORT_MESSAGE)

    async def disconnect(self) -> None:
        raise WebSocketClientError(LEAKY_TRANSPORT_MESSAGE)


# --------------------------------------------------------------------------
# The pyo3 contract this suite is built on
# --------------------------------------------------------------------------


def test_pyo3_websocket_error_str_is_its_argument_verbatim() -> None:
    """Contract test: no Python-side ``__str__`` sanitises the Rust message.

    If a future ``nautilus-trader`` gains one, this fails RED and the
    type-name-only rule can be revisited deliberately rather than by drift.
    """
    error = WebSocketClientError(LEAKY_TRANSPORT_MESSAGE)

    assert str(error) == LEAKY_TRANSPORT_MESSAGE
    assert f"{error}" == LEAKY_TRANSPORT_MESSAGE


# --------------------------------------------------------------------------
# connect / send / close must not republish the transport's text
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_failure_does_not_leak_signed_header_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = _RecordingLogger()
    ws = _make_ws(logger=logger)
    monkeypatch.setattr(ws_module, "WebSocketClient", _LeakyClient)

    with pytest.raises(VenueTransportError) as caught:
        await ws.connect()

    _assert_no_canary(str(caught.value), context="connect error message")
    assert "WebSocketClientError" in str(caught.value)
    for record in logger.records:
        _assert_no_canary(record, context="connect log record")


@pytest.mark.asyncio
async def test_send_failure_does_not_leak_signed_header_material() -> None:
    logger = _RecordingLogger()
    ws = _make_ws(logger=logger)
    ws._client = _LeakyClient()  # type: ignore[assignment]

    with pytest.raises(VenueTransportError) as caught:
        await ws.subscribe_market_data(["tc-temp-nychigh-2026-08-25-lt79f"])

    _assert_no_canary(str(caught.value), context="send error message")
    assert "WebSocketClientError" in str(caught.value)
    for record in logger.records:
        _assert_no_canary(record, context="send log record")


@pytest.mark.asyncio
async def test_disconnect_failure_does_not_leak_signed_header_material() -> None:
    logger = _RecordingLogger()
    ws = _make_ws(logger=logger)
    ws._client = _LeakyClient()  # type: ignore[assignment]

    await ws.close()

    assert logger.records, "close() must report the failed disconnect, not swallow it"
    for record in logger.records:
        _assert_no_canary(record, context="close log record")
    assert any("WebSocketClientError" in record for record in logger.records)


@pytest.mark.asyncio
async def test_rendered_traceback_cannot_republish_the_transport_text() -> None:
    """``raise ... from exc`` would put the raw text back into every traceback.

    Redacting the message while keeping the pyo3 exception as ``__cause__``
    achieves nothing: ``logging.exception`` and the default excepthook both
    render the chain. ``from None`` sets ``__suppress_context__``, which is
    exactly what ``traceback`` consults -- so this asserts against the RENDERED
    traceback rather than walking ``__context__`` by hand, because the rendered
    text is what actually reaches a terminal or a log file.
    """
    logger = _RecordingLogger()
    ws = _make_ws(logger=logger)
    ws._client = _LeakyClient()  # type: ignore[assignment]

    with pytest.raises(VenueTransportError) as caught:
        await ws.subscribe_market_data(["tc-temp-nychigh-2026-08-25-lt79f"])

    error = caught.value
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))

    _assert_no_canary(rendered, context="rendered traceback")
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
