"""Markets WebSocket client -- plan revision 2, sections 5.3, 6 and 9 Step 10.

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md``.

The load-bearing fact this suite exists to pin (plan section 5.3, verified
against ``core/nautilus_pyo3.pyi:5530-5566``): ``WebSocketConfig.headers`` is
FIXED at construction, ``WebSocketClient.connect`` is a classmethod taking that
config, the Rust layer re-handshakes internally REUSING those headers, and
``post_reconnection`` fires only AFTER a handshake has already succeeded.
A native reconnect therefore replays a STALE ``X-PM-Timestamp``, which the
venue rejects outside its +/-30s window. So native reconnect is disabled
(``reconnect_max_attempts=0``) whenever the socket is authenticated and Breezy
supervises reconnection itself, signing fresh headers each time.

That claim is only worth anything if it is proven end to end, so the reconnect
tests here run against a REAL loopback WebSocket server
(``tests/support/loopback_ws.py``) under ``@pytest.mark.allow_socket``. Without
that marker ``tests/conftest.py`` replaces ``nautilus_pyo3.WebSocketClient``
with a raising sentinel and nothing below would exercise the transport at all.

No real credential is used anywhere: every Ed25519 key is generated in-process,
and no test contacts any polymarket.us host.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable, Iterable
from typing import Any

import pytest
from nacl.signing import SigningKey, VerifyKey
from nautilus_trader.common.component import LiveClock, Logger, TestClock
from nautilus_trader.core.nautilus_pyo3 import WebSocketConfig

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
from breezy.adapters.polymarket_us.websocket import (
    SUBSCRIPTION_TYPE_MARKET_DATA,
    WS_PATH,
    PolymarketUSMarketsWebSocket,
    build_subscribe_envelope,
    build_unsubscribe_envelope,
)
from tests.support.loopback_ws import LoopbackWebSocketServer, ServerMode

_KEY_ID = "11111111-2222-3333-4444-555555555555"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class _RecordingSigner(Ed25519RequestSigner):
    """A signer that keeps every header set it produced, for freshness assertions."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # `Ed25519RequestSigner` defines `__slots__`; the subclass does not, so
        # it gets a `__dict__` and this attribute is legal.
        self.signed: list[list[tuple[str, str]]] = []

    def sign_headers(self, *args: Any, **kwargs: Any) -> list[tuple[str, str]]:
        headers = super().sign_headers(*args, **kwargs)
        self.signed.append(headers)
        return headers


def _new_signer(
    *,
    clock: LiveClock | TestClock | None = None,
    signer_cls: type[Ed25519RequestSigner] = Ed25519RequestSigner,
) -> tuple[Ed25519RequestSigner, VerifyKey]:
    """Build a signer over an ephemeral in-process Ed25519 key."""
    key = SigningKey.generate()
    credentials = PolymarketUSCredentials(
        key_id=RedactedSecureString(_KEY_ID),
        secret_key=RedactedSecureString(base64.b64encode(bytes(key)).decode("ascii")),
    )
    return (
        signer_cls(credentials, clock=clock if clock is not None else LiveClock()),
        key.verify_key,
    )


def _make_ws(
    *,
    ws_url: str,
    signer: Ed25519RequestSigner | None,
    handler: Callable[[bytes], None] | None = None,
    request_ids: Iterable[str] = ("req-1", "req-2", "req-3", "req-4"),
    **overrides: Any,
) -> PolymarketUSMarketsWebSocket:
    ids = iter(request_ids)
    settings: dict[str, Any] = {
        "supervisor_poll_secs": 0.02,
        "reconnect_max_attempts": 2,
        "reconnect_delay_initial_ms": 20,
        "reconnect_delay_max_ms": 40,
        "reconnect_backoff_factor": 2,
    }
    settings.update(overrides)
    return PolymarketUSMarketsWebSocket(
        ws_url=ws_url,
        signer=signer,
        handler=handler if handler is not None else (lambda _raw: None),
        loop=asyncio.get_running_loop(),
        heartbeat_secs=10,
        idle_timeout_secs=60,
        logger=Logger("test-polymarket-us-ws"),
        request_id_factory=lambda: next(ids),
        **settings,
    )


def _cfg(config: WebSocketConfig, name: str) -> Any:
    """Read a ``WebSocketConfig`` attribute that the shipped ``.pyi`` omits.

    NOT a drift waiver. All five attributes read below
    (``url``, ``header_names``, ``heartbeat``, ``idle_timeout_ms``,
    ``reconnect_max_attempts``) were verified present at runtime with correct
    values on nautilus-trader 1.231.0; it is ``core/nautilus_pyo3.pyi`` that is
    incomplete. That is a KNOWN property of this version --
    ``nautilus-trader-patterns`` trap 12, "`.pyi` stubs are incomplete":
    grepping the stub to prove a symbol is absent yields false negatives.

    Routed through one documented seam instead of seven scattered
    ``# type: ignore[attr-defined]`` comments, so that if a future version
    genuinely REMOVES one of these, the failure is a real ``AttributeError``
    at runtime rather than a silently-still-suppressed static error.
    """
    assert hasattr(config, name), f"WebSocketConfig lost attribute {name!r}"
    return getattr(config, name)


def _verified_timestamp(headers: dict[str, str], verify_key: VerifyKey) -> int:
    """Assert the handshake carries a valid signature; return its timestamp."""
    timestamp = headers["x-pm-timestamp"]
    assert headers["x-pm-access-key"] == _KEY_ID
    verify_key.verify(
        f"{timestamp}GET{WS_PATH}".encode(),
        base64.b64decode(headers["x-pm-signature"]),
    )
    return int(timestamp)


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


def _subscribe_payloads(server: LoopbackWebSocketServer) -> list[dict[str, Any]]:
    return [json.loads(message)["subscribe"] for message in server.messages]


# --------------------------------------------------------------------------
# envelope schema (pure, no socket)
# --------------------------------------------------------------------------


def test_subscribe_envelope_matches_the_sdk_schema() -> None:
    envelope = build_subscribe_envelope(
        request_id="req-1",
        subscription_type=SUBSCRIPTION_TYPE_MARKET_DATA,
        market_slugs=["tc-temp-nychigh-2026-08-25-lt79f"],
    )

    assert envelope == {
        "subscribe": {
            "requestId": "req-1",
            "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
            "marketSlugs": ["tc-temp-nychigh-2026-08-25-lt79f"],
        }
    }


def test_subscribe_omits_market_slugs_key_when_the_list_is_empty() -> None:
    """The SDK guards the key with ``if market_slugs:`` (``websocket/base.py:105``)."""
    envelope = build_subscribe_envelope(
        request_id="req-1",
        subscription_type=SUBSCRIPTION_TYPE_MARKET_DATA,
        market_slugs=[],
    )

    assert "marketSlugs" not in envelope["subscribe"]
    assert envelope == {
        "subscribe": {"requestId": "req-1", "subscriptionType": SUBSCRIPTION_TYPE_MARKET_DATA}
    }


def test_unsubscribe_envelope_matches_the_sdk_schema() -> None:
    assert build_unsubscribe_envelope(request_id="req-9") == {"unsubscribe": {"requestId": "req-9"}}


# --------------------------------------------------------------------------
# WebSocketConfig construction (no socket)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_headers_are_a_list_of_pairs() -> None:
    """``WebSocketConfig.headers`` takes ``list[tuple[str, str]]`` (pyi:5531-5544)."""
    signer, _ = _new_signer()
    ws = _make_ws(ws_url="ws://127.0.0.1:1", signer=signer)

    headers = signer.sign_headers("GET", WS_PATH)

    assert isinstance(headers, list)
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in headers)
    config = ws._build_config()
    assert isinstance(config, WebSocketConfig)
    assert _cfg(config, "header_names") == ["X-PM-Access-Key", "X-PM-Timestamp", "X-PM-Signature"]


@pytest.mark.asyncio
async def test_native_reconnect_is_disabled_when_auth_is_required() -> None:
    signer, _ = _new_signer()
    ws = _make_ws(ws_url="ws://127.0.0.1:1", signer=signer)

    assert _cfg(ws._build_config(), "reconnect_max_attempts") == 0


@pytest.mark.asyncio
async def test_public_mode_leaves_native_reconnect_enabled_and_sends_no_headers() -> None:
    ws = _make_ws(ws_url="ws://127.0.0.1:1", signer=None)

    config = ws._build_config()

    assert _cfg(config, "header_names") == []
    assert _cfg(config, "reconnect_max_attempts") is None


@pytest.mark.asyncio
async def test_websocket_config_sets_heartbeat_and_idle_timeout() -> None:
    """No hand-rolled idle watchdog: staleness detection is native."""
    signer, _ = _new_signer()
    ws = _make_ws(ws_url="ws://127.0.0.1:1", signer=signer)

    config = ws._build_config()

    assert _cfg(config, "heartbeat") == 10
    assert _cfg(config, "idle_timeout_ms") == 60_000
    assert _cfg(config, "url") == f"ws://127.0.0.1:1{WS_PATH}"


@pytest.mark.asyncio
async def test_each_build_config_signs_a_fresh_timestamp() -> None:
    """No cached config, no cached headers: every build re-signs.

    ``WebSocketConfig`` exposes ``header_names`` but not header VALUES, so the
    signature is observed at the signer here and end-to-end at the handshake in
    the loopback tests below.
    """
    clock = TestClock()
    clock.set_time(1_700_000_000_000 * 1_000_000)
    signer, _ = _new_signer(clock=clock, signer_cls=_RecordingSigner)
    signed = signer.signed  # type: ignore[attr-defined]

    ws = _make_ws(ws_url="ws://127.0.0.1:1", signer=signer)

    ws._build_config()
    clock.set_time(1_700_000_005_000 * 1_000_000)
    ws._build_config()

    assert [dict(h)["X-PM-Timestamp"] for h in signed] == ["1700000000000", "1700000005000"]
    assert dict(signed[0])["X-PM-Signature"] != dict(signed[1])["X-PM-Signature"]


# --------------------------------------------------------------------------
# loopback transport
# --------------------------------------------------------------------------


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_connect_signs_the_handshake_with_a_verifiable_signature() -> None:
    async with LoopbackWebSocketServer() as server:
        signer, verify_key = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer)
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)
        finally:
            await ws.close()

        _verified_timestamp(server.handshakes[0], verify_key)


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_supervised_reconnect_rehandshakes_with_a_strictly_later_timestamp() -> None:
    """Plan section 5.3: a stale ``X-PM-Timestamp`` must never be replayed."""
    async with LoopbackWebSocketServer() as server:
        signer, verify_key = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer)
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)
            first = _verified_timestamp(server.handshakes[0], verify_key)

            server.drop_connections()
            await _wait_until(lambda: len(server.handshakes) == 2)
            second = _verified_timestamp(server.handshakes[1], verify_key)
        finally:
            await ws.close()

        assert second > first
        assert ws.is_degraded is False


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_resubscribes_exactly_once_per_slug_after_reconnect() -> None:
    slugs = ["tc-temp-nychigh-2026-08-25-lt79f", "tc-temp-denhigh-2026-08-25-lt91f"]
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer)
        try:
            await ws.connect()
            await ws.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.messages) == 1)

            server.drop_connections()
            await _wait_until(lambda: len(server.handshakes) == 2)
            await _wait_until(lambda: len(server.messages) == 2)
        finally:
            await ws.close()

        replay = _subscribe_payloads(server)[1]
        assert replay["marketSlugs"] == slugs
        assert replay["subscriptionType"] == SUBSCRIPTION_TYPE_MARKET_DATA
        assert replay["requestId"] == "req-1"


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_subscribe_sends_the_sdk_envelope_over_the_socket() -> None:
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer)
        try:
            await ws.connect()
            await ws.subscribe_market_data(["tc-temp-nychigh-2026-08-25-lt79f"])
            await _wait_until(lambda: len(server.messages) == 1)
            assert ws.subscriptions == {"tc-temp-nychigh-2026-08-25-lt79f": "req-1"}

            await ws.unsubscribe("req-1")
            await _wait_until(lambda: len(server.messages) == 2)
        finally:
            await ws.close()

        assert json.loads(server.messages[1]) == {"unsubscribe": {"requestId": "req-1"}}
        assert ws.subscriptions == {}


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_pushed_frames_reach_the_handler() -> None:
    received: list[bytes] = []
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer, handler=received.append)
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)
            await server.push_text('{"marketSlug":"tc-temp-nychigh-2026-08-25-lt79f"}')
            await _wait_until(lambda: len(received) == 1)
        finally:
            await ws.close()

    assert json.loads(received[0])["marketSlug"] == "tc-temp-nychigh-2026-08-25-lt79f"


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_reconnect_attempts_are_bounded_and_end_in_a_degraded_client() -> None:
    """Fail closed: a socket that will not come back must say so, not spin."""
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer, reconnect_max_attempts=2)
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)

            server.mode = ServerMode.REFUSE_HANDSHAKE
            server.drop_connections()
            await _wait_until(lambda: ws.is_degraded, timeout=10.0)
        finally:
            await ws.close()

        # 1 initial handshake + (1 reconnect attempt + 2 retries) = 4 accepts.
        assert server.connection_attempts == 4
        assert ws.is_connected is False


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_close_during_reconnect_backoff_leaves_no_pending_task() -> None:
    async with LoopbackWebSocketServer() as server:
        baseline = len(asyncio.all_tasks())
        signer, _ = _new_signer()
        ws = _make_ws(
            ws_url=server.url,
            signer=signer,
            reconnect_max_attempts=50,
            reconnect_delay_initial_ms=200,
            reconnect_delay_max_ms=200,
        )
        await ws.connect()
        await _wait_until(lambda: len(server.handshakes) == 1)

        server.mode = ServerMode.REFUSE_HANDSHAKE
        server.drop_connections()
        await _wait_until(lambda: server.connection_attempts >= 2)

        await asyncio.wait_for(ws.close(), timeout=5.0)

        await asyncio.sleep(0.05)
        assert len(asyncio.all_tasks()) <= baseline
        assert ws.is_connected is False


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_cancelling_the_supervisor_is_not_reported_as_degradation() -> None:
    """``RetryManager.run`` swallows ``CancelledError`` (``live/retry.py:187-189``).

    Left unhandled, a cancelled supervisor is indistinguishable from one that
    exhausted its retries, and shutdown would raise a false feed-down alarm.
    """
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(
            ws_url=server.url,
            signer=signer,
            reconnect_max_attempts=50,
            reconnect_delay_initial_ms=200,
            reconnect_delay_max_ms=200,
        )
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)

            server.mode = ServerMode.REFUSE_HANDSHAKE
            server.drop_connections()
            await _wait_until(lambda: server.connection_attempts >= 2)

            supervisor = ws._supervisor
            assert supervisor is not None
            supervisor.cancel()
            with pytest.raises(asyncio.CancelledError):
                await supervisor

            assert ws.is_degraded is False
        finally:
            await ws.close()


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_cancelling_connect_leaves_no_pending_task() -> None:
    async with LoopbackWebSocketServer() as server:
        baseline = len(asyncio.all_tasks())
        signer, _ = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer)

        task = asyncio.ensure_future(ws.connect())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await asyncio.wait_for(ws.close(), timeout=5.0)
        await asyncio.sleep(0.05)
        assert len(asyncio.all_tasks()) <= baseline
