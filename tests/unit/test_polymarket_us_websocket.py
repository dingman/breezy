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
from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
from breezy.adapters.polymarket_us.websocket import (
    DEFAULT_SUBSCRIPTION_CONFIRMATION_SECS,
    MAX_SUBSCRIPTIONS_PER_CONNECTION,
    SUBSCRIPTION_TYPE_MARKET_DATA,
    WS_PATH,
    PolymarketUSMarketsWebSocket,
    PolymarketUSMarketsWebSocketPool,
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


def _make_pool(
    *,
    ws_url: str,
    signer: Ed25519RequestSigner | None,
    handler: Callable[[bytes], None] | None = None,
    cap: int = MAX_SUBSCRIPTIONS_PER_CONNECTION,
    request_id_factory: Callable[[], str] | None = None,
    logger: Any = None,
    **overrides: Any,
) -> PolymarketUSMarketsWebSocketPool:
    settings: dict[str, Any] = {
        "supervisor_poll_secs": 0.02,
        "reconnect_max_attempts": 2,
        "reconnect_delay_initial_ms": 20,
        "reconnect_delay_max_ms": 40,
        "reconnect_backoff_factor": 2,
    }
    settings.update(overrides)
    kwargs: dict[str, Any] = {}
    if request_id_factory is not None:
        kwargs["request_id_factory"] = request_id_factory
    return PolymarketUSMarketsWebSocketPool(
        ws_url=ws_url,
        signer=signer,
        handler=handler if handler is not None else (lambda _raw: None),
        loop=asyncio.get_running_loop(),
        heartbeat_secs=10,
        idle_timeout_secs=60,
        logger=logger if logger is not None else Logger("test-polymarket-us-ws-pool"),
        cap=cap,
        **kwargs,
        **settings,
    )


def _weather_slugs(count: int) -> list[str]:
    return [f"tc-temp-market{i:03d}-2026-08-30-lt79f" for i in range(count)]


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


# --------------------------------------------------------------------------
# venue error frames (single connection) -- DEFECT: an error frame carries no
# `marketSlug`, so PolymarketUSDataClient._handle_ws_frame would otherwise
# treat it as a routine "missing routing key" frame and it would look exactly
# like a quiet market. It must be impossible to miss.
# --------------------------------------------------------------------------


def test_max_subscriptions_per_connection_matches_the_measured_venue_cap() -> None:
    """Pinned to the live 2026-08-30 capture: the venue accepts exactly 10."""
    assert MAX_SUBSCRIPTIONS_PER_CONNECTION == 10


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_a_pushed_error_frame_is_recorded_and_still_reaches_the_handler() -> None:
    received: list[bytes] = []
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer, handler=received.append)
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)
            await server.push_text(
                '{"error":"max subscriptions per connection reached",'
                '"requestId":"11111111111111111111111111111111"}'
            )
            await _wait_until(lambda: len(ws.subscription_errors) == 1)
        finally:
            await ws.close()

    error = ws.subscription_errors[0]
    assert error.error == "max subscriptions per connection reached"
    assert error.request_id == "11111111111111111111111111111111"
    # Never silently swallowed: the raw frame still reaches the caller's handler.
    assert len(received) == 1
    assert json.loads(received[0])["error"] == "max subscriptions per connection reached"


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_a_non_error_frame_never_populates_subscription_errors() -> None:
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(ws_url=server.url, signer=signer)
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)
            await server.push_text('{"marketSlug":"tc-temp-nychigh-2026-08-25-lt79f"}')
            await asyncio.sleep(0.05)
        finally:
            await ws.close()

    assert ws.subscription_errors == ()


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_a_confirmed_slug_never_becomes_a_silent_subscription() -> None:
    """Positive confirmation: an inbound frame naming the slug clears the pending timer."""
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(
            ws_url=server.url,
            signer=signer,
            confirmation_window_secs=0.05,
        )
        try:
            await ws.connect()
            slug = "tc-temp-nychigh-2026-08-25-lt79f"
            await ws.subscribe_market_data([slug])
            await server.push_text(json.dumps({"marketSlug": slug}))
            await asyncio.sleep(0.2)  # outlive the confirmation window
        finally:
            await ws.close()

    assert ws.silent_subscriptions == ()


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_silent_truncation_is_flagged_even_though_no_error_frame_ever_arrives() -> None:
    """Live probe, 2026-08-30, pattern 2: N slugs subscribed ONE PER ENVELOPE past the
    cap -- exactly how `_subscribe_quote_ticks` actually subscribes -- produced ZERO
    error frames on the real venue; the excess slugs were just never sent data.
    Absence of an error frame must never be read as "healthy": positive per-slug
    confirmation is the only detection that catches this.
    """
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(
            ws_url=server.url,
            signer=signer,
            confirmation_window_secs=0.05,
            request_ids=(f"req-{i}" for i in range(len(slugs))),
        )
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)

            # One-slug-per-envelope, exactly as `_subscribe_quote_ticks` does --
            # NOT the bulk multi-slug envelope that draws an explicit error.
            for slug in slugs:
                await ws.subscribe_market_data([slug])
            await _wait_until(lambda: len(server.messages) == len(slugs))

            # Simulate the measured venue behaviour for this pattern: data for
            # only the first MAX_SUBSCRIPTIONS_PER_CONNECTION slugs, and NO
            # error frame at all for the rest.
            for slug in slugs[:MAX_SUBSCRIPTIONS_PER_CONNECTION]:
                await server.push_text(json.dumps({"marketSlug": slug}))

            await _wait_until(
                lambda: any(w.slug == slugs[-1] for w in ws.silent_subscriptions),
                timeout=5.0,
            )
        finally:
            await ws.close()

    # The defect this pins: healthy-looking on the error channel...
    assert ws.subscription_errors == ()
    # ...yet the truncated slug is caught, and the confirmed ones are not.
    silent_slugs = {warning.slug for warning in ws.silent_subscriptions}
    assert slugs[-1] in silent_slugs
    assert silent_slugs.isdisjoint(slugs[:MAX_SUBSCRIPTIONS_PER_CONNECTION])


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_pool_aggregates_silent_subscriptions_across_shards() -> None:
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer, confirmation_window_secs=0.05)
        try:
            await pool.connect()
            await pool.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.messages) == 2)

            # Confirm every slug except the lone one on the second shard.
            for slug in slugs[:MAX_SUBSCRIPTIONS_PER_CONNECTION]:
                await server.push_text(json.dumps({"marketSlug": slug}))

            await _wait_until(
                lambda: any(w.slug == slugs[-1] for w in pool.silent_subscriptions),
                timeout=5.0,
            )
        finally:
            await pool.close()

        assert pool.subscription_errors == ()
        silent_slugs = {warning.slug for warning in pool.silent_subscriptions}
        assert silent_slugs == {slugs[-1]}


def test_pool_enables_positive_confirmation_by_default() -> None:
    """The pool is the production path -- unlike the bare class, it must default ON."""
    assert DEFAULT_SUBSCRIPTION_CONFIRMATION_SECS > 0


# --------------------------------------------------------------------------
# subscription sharding pool -- THE DEFECT: the venue accepts only
# MAX_SUBSCRIPTIONS_PER_CONNECTION subscriptions per socket and silently drops
# the rest. `PolymarketUSMarketsWebSocketPool` shards N slugs across
# ceil(N / cap) connections so no single connection ever crosses the cap.
# --------------------------------------------------------------------------


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_subscribing_60_slugs_opens_6_connections_of_at_most_10() -> None:
    slugs = _weather_slugs(60)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        try:
            await pool.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)
            await pool.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.handshakes) == 6)
            await _wait_until(lambda: len(server.messages) == 6)
        finally:
            await pool.close()

        sizes = [len(payload.get("marketSlugs", [])) for payload in _subscribe_payloads(server)]
        assert len(sizes) == 6
        assert all(size <= MAX_SUBSCRIPTIONS_PER_CONNECTION for size in sizes)
        assert sum(sizes) == 60
        assert pool.shard_count == 6
        assert server.connection_attempts == 6


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_subscribing_exactly_the_cap_opens_one_connection() -> None:
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        try:
            await pool.connect()
            await pool.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.messages) == 1)
            await asyncio.sleep(0.05)
        finally:
            await pool.close()

        assert server.connection_attempts == 1
        assert pool.shard_count == 1
        assert set(pool.subscriptions) == set(slugs)


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_subscribing_cap_plus_one_opens_two_connections() -> None:
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        try:
            await pool.connect()
            await pool.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.messages) == 2)
        finally:
            await pool.close()

        sizes = sorted(
            len(payload.get("marketSlugs", [])) for payload in _subscribe_payloads(server)
        )
        assert sizes == [1, MAX_SUBSCRIPTIONS_PER_CONNECTION]
        assert pool.shard_count == 2


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_every_slug_is_subscribed_exactly_once_across_incremental_calls() -> None:
    """No slug dropped, none duplicated -- including re-requesting an already-live slug."""
    slugs = _weather_slugs(25)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        try:
            await pool.connect()
            await pool.subscribe_market_data(slugs[:7])
            await pool.subscribe_market_data(slugs[:12])  # first 7 already live: must be a no-op
            await pool.subscribe_market_data(slugs[12:25])
            await _wait_until(
                lambda: sum(
                    len(json.loads(m)["subscribe"].get("marketSlugs", [])) for m in server.messages
                )
                == 25
            )
        finally:
            await pool.close()

        sent_slugs: list[str] = []
        for payload in _subscribe_payloads(server):
            sent_slugs.extend(payload.get("marketSlugs", []))
        assert sorted(sent_slugs) == sorted(slugs)
        assert len(sent_slugs) == len(set(sent_slugs))  # no duplicate on the wire
        assert set(pool.subscriptions) == set(slugs)
        assert len(pool.subscriptions) == 25
        for shard in pool._shards:
            assert len(shard.subscriptions) <= MAX_SUBSCRIPTIONS_PER_CONNECTION


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_unsubscribe_routes_to_the_owning_shard_only() -> None:
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        try:
            await pool.connect()
            await pool.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.messages) == 2)

            last_slug = slugs[-1]
            request_id = pool.subscriptions[last_slug]
            await pool.unsubscribe(request_id)
            await _wait_until(lambda: len(server.messages) == 3)
        finally:
            await pool.close()

        assert last_slug not in pool.subscriptions
        assert len(pool.subscriptions) == MAX_SUBSCRIPTIONS_PER_CONNECTION


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_unsubscribe_of_an_unknown_request_id_raises_loudly() -> None:
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        try:
            await pool.connect()
            with pytest.raises(VenueTransportError):
                await pool.unsubscribe("does-not-exist")
        finally:
            await pool.close()


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_one_shard_degrading_does_not_orphan_another_shards_subscriptions() -> None:
    """Reconnect/supervision is per shard: one dead connection must not silently

    take another shard's live slugs down with it.
    """
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(
            ws_url=server.url,
            signer=signer,
            reconnect_max_attempts=1,
            reconnect_delay_initial_ms=10,
            reconnect_delay_max_ms=10,
        )
        try:
            await pool.connect()
            await pool.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.messages) == 2)
            assert len(server.handshakes) == 2

            shard0, shard1 = pool._shards
            shard0_slugs_before = dict(shard0.subscriptions)

            server.mode = ServerMode.REFUSE_HANDSHAKE
            server._writers[-1].transport.abort()

            await _wait_until(lambda: shard1.is_degraded, timeout=10.0)

            assert shard0.is_degraded is False
            assert shard0.is_connected is True
            assert dict(shard0.subscriptions) == shard0_slugs_before
            assert pool.is_degraded is True
        finally:
            await pool.close()


# --------------------------------------------------------------------------
# DEFECT 1 [CRITICAL] -- a detected silent subscription must reach a signal
# an automated consumer actually polls. `PolymarketUSDataClient.sample_feed_health`
# (data.py :1285-1319) polls ONLY `self._feed.is_degraded` on a fixed cadence
# and fails closed (safe mode, disconnect) the moment it is True. Before this
# fix, `silent_subscriptions`/`subscription_errors` were populated but never
# read anywhere outside this module and its tests -- `is_connected` stayed
# True and `is_degraded` stayed False forever, so a silently-truncated feed
# looked identical to a healthy one to every automated consumer.
# --------------------------------------------------------------------------


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_a_confirmed_silent_subscription_sets_is_degraded() -> None:
    """A slug that outlives the confirmation window with no inbound frame must
    flip `is_degraded`, the one property `sample_feed_health` polls -- not
    just populate `silent_subscriptions`, which nothing in production reads.
    """
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        ws = _make_ws(
            ws_url=server.url,
            signer=signer,
            confirmation_window_secs=0.05,
            request_ids=(f"req-{i}" for i in range(len(slugs))),
        )
        try:
            await ws.connect()
            await _wait_until(lambda: len(server.handshakes) == 1)
            for slug in slugs:
                await ws.subscribe_market_data([slug])
            await _wait_until(lambda: len(server.messages) == len(slugs))

            assert ws.is_degraded is False  # not yet -- no silent slug observed

            for slug in slugs[:MAX_SUBSCRIPTIONS_PER_CONNECTION]:
                await server.push_text(json.dumps({"marketSlug": slug}))

            await _wait_until(lambda: ws.is_degraded is True, timeout=5.0)
        finally:
            await ws.close()

    assert len(ws.silent_subscriptions) == 1


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_pool_is_degraded_when_any_shard_has_a_silent_subscription() -> None:
    """The pool aggregates `is_degraded` from its shards (`any(...)`); a
    silent subscription on ONE shard must therefore degrade the whole pool,
    exactly like a shard's reconnect abandonment already does.
    """
    slugs = _weather_slugs(MAX_SUBSCRIPTIONS_PER_CONNECTION + 1)
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer, confirmation_window_secs=0.05)
        try:
            await pool.connect()
            await pool.subscribe_market_data(slugs)
            await _wait_until(lambda: len(server.messages) == 2)

            assert pool.is_degraded is False

            for slug in slugs[:MAX_SUBSCRIPTIONS_PER_CONNECTION]:
                await server.push_text(json.dumps({"marketSlug": slug}))

            await _wait_until(lambda: pool.is_degraded is True, timeout=5.0)
        finally:
            await pool.close()

        assert len(pool.silent_subscriptions) == 1


# --------------------------------------------------------------------------
# DEFECT 2 [HIGH] -- `subscribe_market_data` reads `len(shard.subscriptions)`
# to compute available room, then `await`s the shard's own `subscribe_market_data`.
# Two overlapping pool-level calls (exactly what `PolymarketUSDataClient`
# produces: Nautilus's `LiveMarketDataClient.subscribe_quote_ticks` fires each
# `_subscribe_quote_ticks` coroutine via unawaited `create_task`, so N
# `SubscribeQuoteTicks` commands run concurrently) can both read the same
# free room and both commit into it, pushing a shard above `cap`.
# --------------------------------------------------------------------------


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_concurrent_subscribe_calls_never_push_a_shard_over_cap() -> None:
    """Two overlapping `subscribe_market_data` calls, each well under `cap` on
    their own, must never combine onto one shard past `cap` -- and every slug
    from both calls must still end up subscribed somewhere.
    """
    cap = MAX_SUBSCRIPTIONS_PER_CONNECTION
    batch_a = _weather_slugs(6)
    batch_b = [f"tc-temp-market{i:03d}b-2026-08-30-lt79f" for i in range(6)]
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer, cap=cap)
        try:
            await pool.connect()
            await asyncio.gather(
                pool.subscribe_market_data(batch_a),
                pool.subscribe_market_data(batch_b),
            )
            await _wait_until(lambda: len(pool.subscriptions) == 12)
        finally:
            await pool.close()

        for shard in pool._shards:
            assert len(shard.subscriptions) <= cap
        assert set(pool.subscriptions) == set(batch_a) | set(batch_b)


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_concurrent_resubscribe_of_the_same_slug_routes_to_one_shard_only() -> None:
    """`pending` is computed from `_slug_to_shard` before the await boundary,
    and `_slug_to_shard[slug] = shard` is written after it -- a near-simultaneous
    re-request of the SAME slug from two callers must not route it to two
    different shards. Uses ``cap=1`` with the sole shard already full so both
    concurrent calls must decide, independently, whether to open a new shard
    -- exactly the branch of ``_shard_with_room`` where a stale read causes
    each caller to build and subscribe its OWN new shard for the same slug.
    """
    filler = "tc-temp-filler-2026-08-30-lt79f"
    slug = "tc-temp-nychigh-2026-08-25-lt79f"
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer, cap=1)
        try:
            await pool.connect()
            await pool.subscribe_market_data([filler])  # fills the sole shard to cap=1

            await asyncio.gather(
                pool.subscribe_market_data([slug]),
                pool.subscribe_market_data([slug]),
            )
            await _wait_until(lambda: slug in pool.subscriptions)
        finally:
            await pool.close()

        owners = [shard for shard in pool._shards if slug in shard.subscriptions]
        assert len(owners) == 1


# --------------------------------------------------------------------------
# DEFECT 3 [CRITICAL] -- `PolymarketUSMarketsWebSocketPool.connect`/`close`
# are bare sequential loops with no per-shard fault isolation. One shard
# raising during `close()` abandons every shard after it (orphaned socket +
# supervisor + confirmation tasks); one shard raising during `connect()`
# leaves every earlier shard connected with nothing to close it, since the
# caller never got a pool reference back.
# --------------------------------------------------------------------------


class _RaisingConnectShard(PolymarketUSMarketsWebSocket):
    """A shard whose `connect()` always fails, never touching the network."""

    async def connect(self) -> None:
        raise VenueTransportError("simulated connect failure")


class _RaisingCloseShard(PolymarketUSMarketsWebSocket):
    """A shard whose `close()` always fails, never touching the network."""

    async def close(self) -> None:
        raise VenueTransportError("simulated close failure")


def _extra_shard(
    cls: type[PolymarketUSMarketsWebSocket],
    *,
    ws_url: str,
    signer: Ed25519RequestSigner | None,
    label: str,
) -> PolymarketUSMarketsWebSocket:
    return cls(
        ws_url=ws_url,
        signer=signer,
        handler=lambda _raw: None,
        loop=asyncio.get_running_loop(),
        heartbeat_secs=10,
        idle_timeout_secs=60,
        logger=Logger("test-polymarket-us-ws-pool"),
        supervisor_poll_secs=0.02,
        reconnect_max_attempts=2,
        reconnect_delay_initial_ms=20,
        reconnect_delay_max_ms=40,
        reconnect_backoff_factor=2,
        connection_label=label,
    )


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_pool_connect_closes_already_connected_shards_when_a_later_shard_fails() -> None:
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        shard0 = pool._shards[0]
        failing = _extra_shard(
            _RaisingConnectShard, ws_url=server.url, signer=signer, label="shard-1"
        )
        pool._shards.append(failing)
        try:
            with pytest.raises(VenueTransportError):
                await pool.connect()

            assert shard0.is_connected is False
        finally:
            await pool.close()


@pytest.mark.allow_socket
@pytest.mark.asyncio
async def test_pool_close_closes_every_shard_even_when_one_raises() -> None:
    async with LoopbackWebSocketServer() as server:
        signer, _ = _new_signer()
        pool = _make_pool(ws_url=server.url, signer=signer)
        good_shard = _extra_shard(
            PolymarketUSMarketsWebSocket, ws_url=server.url, signer=signer, label="shard-2"
        )
        raising_shard = _extra_shard(
            _RaisingCloseShard, ws_url=server.url, signer=signer, label="shard-1"
        )
        pool._shards.extend([raising_shard, good_shard])
        await pool.connect()
        assert good_shard.is_connected is True

        with pytest.raises(VenueTransportError):
            await pool.close()

        assert good_shard.is_connected is False


# --------------------------------------------------------------------------
# shard-close logging must not republish venue-controlled exception text
#
# The pool's `close()` reports each shard that failed. The exception it holds
# is transport- and venue-controlled text (module note "Note on transport
# exception text"), and this recorder is destined to run signed and unattended
# under systemd, logging to journald. So the shard-close report obeys the same
# rule the connect/disconnect/send paths already do: TYPE NAME ONLY.
# --------------------------------------------------------------------------


#: Shaped like handshake material a transport error might echo. Generated here,
#: used nowhere else, and never a real credential.
_CLOSE_ERROR_SENTINEL = "X-PM-Signature: c2VudGluZWwtZG8tbm90LWxvZy1tZUFBQUE9PQ=="


class _RecordingPoolLogger:
    """Captures what the pool logged.

    Deliberately NOT a ``Logger`` subclass: ``Logger`` is a compiled Cython
    class, and the pool only ever calls the methods below on it.
    """

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.messages.append(message)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.messages.append(message)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.messages.append(message)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.messages.append(message)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.messages.append(message)


class _SecretLeakingCloseShard(PolymarketUSMarketsWebSocket):
    """A shard whose `close()` fails with secret-shaped text, touching no socket."""

    async def close(self) -> None:
        raise VenueTransportError(f"shard close rejected [{_CLOSE_ERROR_SENTINEL}]")


@pytest.mark.asyncio
async def test_pool_close_logs_the_exception_type_and_never_the_venue_error_text() -> None:
    recorder = _RecordingPoolLogger()
    pool = _make_pool(ws_url="ws://127.0.0.1:1", signer=None, logger=recorder)
    leaking = _extra_shard(
        _SecretLeakingCloseShard, ws_url="ws://127.0.0.1:1", signer=None, label="shard-1"
    )
    pool._shards.clear()
    pool._shards.append(leaking)

    with pytest.raises(VenueTransportError):
        await pool.close()

    logged = "\n".join(recorder.messages)
    assert "a shard failed to close cleanly" in logged
    assert "VenueTransportError" in logged, f"the exception type must be named: {logged!r}"
    assert _CLOSE_ERROR_SENTINEL not in logged, (
        f"venue-controlled exception text reached a log record: {logged!r}"
    )


# --------------------------------------------------------------------------
# supervisor death -- the OTHER way the reconnect loop stops silently
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_supervisor_that_dies_unexpectedly_is_reported_as_degraded() -> None:
    """An exception must not end supervision in silence.

    Exhausting the retry budget already sets ``is_degraded``, and the data
    client's watchdog turns that into safe mode and a non-zero process exit.
    An UNEXPECTED exception took a different route: the supervisor task ended,
    ``_degraded`` stayed False, ``is_connected`` stayed True, and nothing
    downstream could tell the feed had stopped being supervised. For an
    unattended run that is the same fatal outcome as exhaustion -- no further
    reconnection will ever be attempted -- so it must produce the same signal.

    Nothing here reconnects or retries on the client's behalf; it only makes
    an already-fatal state legible to the watchdog that already polls for it.
    """
    signer, _ = _new_signer()
    ws = _make_ws(ws_url="wss://api.example.invalid", signer=signer)

    class ExplodingClient:
        """A native client whose state probe raises, as a broken FFI call would."""

        def is_reconnecting(self) -> bool:
            raise RuntimeError("native websocket state probe failed")

        def is_closed(self) -> bool:  # pragma: no cover - never reached
            return True

    ws._client = ExplodingClient()  # type: ignore[assignment]

    await ws._supervise()

    assert ws.is_degraded is True, "an unexpected supervisor death must fail closed"
