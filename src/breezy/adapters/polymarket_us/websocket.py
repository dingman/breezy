"""Markets WebSocket client for Polymarket.us (plan revision 2, sections 5.3 and 6).

Why Breezy owns reconnection here
---------------------------------
``nautilus_pyo3`` ships a complete WebSocket transport -- heartbeat, idle
timeout, exponential reconnect backoff with jitter -- and the null hypothesis
is to use all of it. For an UNAUTHENTICATED socket that is exactly what this
module does.

For an AUTHENTICATED socket it cannot be, and the reason is structural
(``core/nautilus_pyo3.pyi:5530-5566``): ``WebSocketConfig.headers`` is fixed at
construction (``:5531-5544``); ``WebSocketClient.connect`` is a **classmethod**
taking that config (``:5547-5556``), and the Rust layer performs every
subsequent reconnect handshake internally, reusing those same headers; and
``post_reconnection`` fires only AFTER a handshake has already succeeded, so it
cannot contribute headers to the handshake it is notified about.

The venue rejects a signature whose ``X-PM-Timestamp`` is more than 30 seconds
from server time, so a native reconnect after that window replays a dead
timestamp and every attempt fails identically. ``reconnect_max_attempts``
cannot help; it only decides how many times the same dead timestamp is sent.

So when a signer is present, native reconnect is DISABLED
(``reconnect_max_attempts=0``) and :meth:`PolymarketUSMarketsWebSocket._supervise`
polls ``is_closed()``/``is_reconnecting()`` and rebuilds a fresh
``WebSocketConfig`` with FRESHLY signed headers before reconnecting. The two
mechanisms are never both live, so they cannot race.

Whether ``/v1/ws/markets`` requires authentication AT ALL is unresolved. The
venue SDK signs it (``sdk_snapshot/.../websocket/base.py:51``), so this module
assumes it does. If smoke step E1 shows the markets stream is public, the fix
is one line at the call site -- pass ``signer=None`` -- and this class then
uses the native reconnect unmodified.

What is reused rather than rebuilt: ``WebSocketConfig.heartbeat`` and
``idle_timeout_ms`` (no hand-rolled staleness watchdog),
``nautilus_trader.live.retry.RetryManager`` (bounded attempts, exponential
backoff, jitter) and ``nautilus_trader.live.cancellation.cancel_tasks_with_timeout``
(task teardown). Only re-subscription replay and the fresh-header reconnect are
Breezy's, and only because nothing native can supply them.

Note on transport exception text (SEC, 2026-08-25)
--------------------------------------------------
An authenticated handshake carries ``X-PM-Access-Key`` and ``X-PM-Signature``.
Any ``WebSocketClientError`` raised at that moment renders, via ``str()``,
whatever string the Rust layer built -- it is a plain ``create_exception!`` type
with no Python-side ``__str__``, so ``args[0]`` passes through verbatim. Five
offline failure paths were audited (connection refused, invalid header value,
invalid header name, DNS failure, malformed URL) and none echoed a header, but
the malformed-URL path DID echo the URL verbatim, proving the layer does
interpolate caller-supplied request material. TLS, proxy and venue-sent
close-reason paths are not reachable offline and remain unaudited.

So this module never interpolates a transport exception, only
``type(exc).__name__`` -- the same rule ``transport.py:246-249`` already applies
on the HTTP side -- and re-raises ``from None`` so the raw text cannot return
through ``__cause__`` in a traceback or a ``Logger.exception`` render.
``redaction.py`` cannot cover this: it redacts header maps and known secret
values, and free-form exception text is neither.

Note on ``RetryManager`` and cancellation: ``RetryManager.run`` catches
``asyncio.CancelledError`` and returns ``None`` rather than re-raising
(``live/retry.py:187-189``), which would leave a cancelled supervisor task
running. Nautilus is IMMUTABLE, so this module re-raises on the caller's side
instead, keyed on ``asyncio.Task.cancelling()``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from nautilus_trader.common.component import Logger
from nautilus_trader.core.nautilus_pyo3 import (
    WebSocketClient,
    WebSocketClientError,
    WebSocketConfig,
)
from nautilus_trader.live.cancellation import cancel_tasks_with_timeout
from nautilus_trader.live.retry import RetryManager

from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner

__all__ = [
    "SUBSCRIPTION_TYPE_MARKET_DATA",
    "WS_PATH",
    "PolymarketUSMarketsWebSocket",
    "build_subscribe_envelope",
    "build_unsubscribe_envelope",
]

#: ``sdk_snapshot/polymarket_us_0.1.2/websocket/markets.py:17``.
WS_PATH: Final[str] = "/v1/ws/markets"

#: ``sdk_snapshot/polymarket_us_0.1.2/websocket/markets.py:25``.
SUBSCRIPTION_TYPE_MARKET_DATA: Final[str] = "SUBSCRIPTION_TYPE_MARKET_DATA"

_MS_PER_SECOND: Final[int] = 1_000


def build_subscribe_envelope(
    *,
    request_id: str,
    subscription_type: str,
    market_slugs: Sequence[str],
) -> dict[str, Any]:
    """Build the venue's subscribe envelope.

    ``marketSlugs`` is present ONLY when the slug list is non-empty. That is
    not a nicety: the SDK guards the key with ``if market_slugs:``
    (``websocket/base.py:105-106``) and the key is absent otherwise, so an
    empty list must not be serialised as ``"marketSlugs": []``.
    """
    envelope: dict[str, Any] = {
        "subscribe": {"requestId": request_id, "subscriptionType": subscription_type}
    }
    if market_slugs:
        envelope["subscribe"]["marketSlugs"] = list(market_slugs)
    return envelope


def build_unsubscribe_envelope(*, request_id: str) -> dict[str, Any]:
    """Build the venue's unsubscribe envelope (``websocket/base.py:110-117``)."""
    return {"unsubscribe": {"requestId": request_id}}


class PolymarketUSMarketsWebSocket:
    """The markets stream: signed connect, subscribe, supervised reconnect.

    Parameters
    ----------
    ws_url : str
        Base URL WITHOUT the path, e.g. ``wss://api.polymarket.us``. The path
        appended is :data:`WS_PATH`, and it is the same string that is signed,
        so the connected path and the signed path cannot drift apart.
    signer : Ed25519RequestSigner or None
        ``None`` means the stream is public: no headers are sent and the native
        reconnect is left enabled.
    handler : Callable[[bytes], None]
        Receives each raw inbound frame. Must not block the event loop.
    """

    __slots__ = (
        "_backoff_factor",
        "_client",
        "_closing",
        "_degraded",
        "_delay_initial_ms",
        "_delay_max_ms",
        "_handler",
        "_heartbeat_secs",
        "_idle_timeout_secs",
        "_log",
        "_loop",
        "_poll_secs",
        "_reconnect_max_attempts",
        "_request_id_factory",
        "_retry_manager",
        "_signer",
        "_subscriptions",
        "_supervisor",
        "_tasks",
        "_ws_url",
    )

    def __init__(
        self,
        *,
        ws_url: str,
        signer: Ed25519RequestSigner | None,
        handler: Callable[[bytes], None],
        loop: asyncio.AbstractEventLoop,
        heartbeat_secs: int,
        idle_timeout_secs: int,
        logger: Logger,
        supervisor_poll_secs: float = 1.0,
        reconnect_max_attempts: int = 10,
        reconnect_delay_initial_ms: int = 2_000,
        reconnect_delay_max_ms: int = 30_000,
        reconnect_backoff_factor: int = 2,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if heartbeat_secs <= 0:
            raise ValueError("heartbeat_secs must be positive")
        if idle_timeout_secs <= 0:
            raise ValueError("idle_timeout_secs must be positive")
        if supervisor_poll_secs <= 0:
            raise ValueError("supervisor_poll_secs must be positive")
        if reconnect_max_attempts < 0:
            raise ValueError("reconnect_max_attempts must not be negative")

        self._ws_url: str = ws_url.rstrip("/")
        self._signer: Ed25519RequestSigner | None = signer
        self._handler: Callable[[bytes], None] = handler
        self._loop: asyncio.AbstractEventLoop = loop
        self._heartbeat_secs: int = heartbeat_secs
        self._idle_timeout_secs: int = idle_timeout_secs
        self._log: Logger = logger
        self._poll_secs: float = supervisor_poll_secs
        self._reconnect_max_attempts: int = reconnect_max_attempts
        self._delay_initial_ms: int = reconnect_delay_initial_ms
        self._delay_max_ms: int = reconnect_delay_max_ms
        self._backoff_factor: int = reconnect_backoff_factor
        self._request_id_factory: Callable[[], str] = (
            request_id_factory if request_id_factory is not None else _new_request_id
        )

        self._client: WebSocketClient | None = None
        #: slug -> requestId. One subscribe call covers many slugs under one id.
        self._subscriptions: dict[str, str] = {}
        self._supervisor: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any] | asyncio.Future[Any]] = set()
        self._retry_manager: RetryManager[bool] | None = None
        self._closing: bool = False
        self._degraded: bool = False

    # -- state ------------------------------------------------------------

    @property
    def requires_auth(self) -> bool:
        return self._signer is not None

    @property
    def is_connected(self) -> bool:
        client = self._client
        return client is not None and not client.is_closed()

    @property
    def is_degraded(self) -> bool:
        """True once reconnection has been abandoned; the feed is not coming back.

        This is the fail-closed signal a data client must act on: the socket is
        gone, Breezy stopped retrying, and no further quotes will arrive.
        """
        return self._degraded

    @property
    def subscriptions(self) -> Mapping[str, str]:
        return dict(self._subscriptions)

    # -- lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Open the socket and, when authenticated, start the reconnect supervisor."""
        if self.is_connected:
            return
        self._closing = False
        self._degraded = False
        await self._open()
        if self.requires_auth and self._supervisor is None:
            self._supervisor = self._loop.create_task(
                self._supervise(), name="polymarket-us-ws-supervisor"
            )

    async def close(self) -> None:
        """Stop supervising, cancel every owned task, and disconnect."""
        self._closing = True
        retry_manager = self._retry_manager
        if retry_manager is not None:
            retry_manager.cancel()

        supervisor = self._supervisor
        self._supervisor = None
        if supervisor is not None:
            self._tasks.add(supervisor)
        await cancel_tasks_with_timeout(self._tasks, self._log)
        self._tasks.clear()

        client = self._client
        self._client = None
        if client is not None and not client.is_closed():
            try:
                await client.disconnect()
            except (WebSocketClientError, OSError) as exc:
                # Type name only. See the module note on transport exception text.
                self._log.warning(
                    f"Polymarket.us markets websocket disconnect failed: {type(exc).__name__}"
                )

    # -- subscriptions ----------------------------------------------------

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        """Subscribe to full market data for slugs not already subscribed."""
        pending = [slug for slug in dict.fromkeys(market_slugs) if slug not in self._subscriptions]
        if not pending:
            return
        request_id = self._request_id_factory()
        await self._send(
            build_subscribe_envelope(
                request_id=request_id,
                subscription_type=SUBSCRIPTION_TYPE_MARKET_DATA,
                market_slugs=pending,
            )
        )
        for slug in pending:
            self._subscriptions[slug] = request_id

    async def unsubscribe(self, request_id: str) -> None:
        """Cancel one subscription request and forget every slug it covered."""
        await self._send(build_unsubscribe_envelope(request_id=request_id))
        for slug in [s for s, rid in self._subscriptions.items() if rid == request_id]:
            del self._subscriptions[slug]

    async def _replay_subscriptions(self) -> None:
        """Re-send every live subscription: exactly one envelope per request id."""
        groups: dict[str, list[str]] = {}
        for slug, request_id in self._subscriptions.items():
            groups.setdefault(request_id, []).append(slug)
        for request_id, slugs in groups.items():
            await self._send(
                build_subscribe_envelope(
                    request_id=request_id,
                    subscription_type=SUBSCRIPTION_TYPE_MARKET_DATA,
                    market_slugs=slugs,
                )
            )

    # -- transport --------------------------------------------------------

    def _build_config(self) -> WebSocketConfig:
        """Build a config with FRESHLY signed headers. Never cache the result."""
        headers: list[tuple[str, str]] = (
            self._signer.sign_headers("GET", WS_PATH) if self._signer is not None else []
        )
        return WebSocketConfig(
            url=f"{self._ws_url}{WS_PATH}",
            headers=headers,
            heartbeat=self._heartbeat_secs,
            idle_timeout_ms=self._idle_timeout_secs * _MS_PER_SECOND,
            # 0 disables the native reconnect, which would replay these exact
            # headers (and so this exact timestamp) forever. `None` restores
            # the native default, which is correct only for a public stream.
            reconnect_max_attempts=0 if self.requires_auth else None,
        )

    async def _open(self) -> None:
        config = self._build_config()
        try:
            self._client = await WebSocketClient.connect(
                loop_=self._loop,
                config=config,
                handler=self._handler,
                post_reconnection=None if self.requires_auth else self._on_native_reconnection,
            )
        except (WebSocketClientError, OSError) as exc:
            # `from None`, not `from exc`: keeping the pyo3 error as `__cause__`
            # would put its raw text back into every traceback and every
            # `Logger.exception` render, defeating the redaction entirely.
            raise VenueTransportError(
                f"Polymarket.us markets websocket connect failed for {WS_PATH}: "
                f"{type(exc).__name__}"
            ) from None

    async def _send(self, envelope: Mapping[str, Any]) -> None:
        client = self._client
        if client is None or client.is_closed():
            raise VenueTransportError(
                "Polymarket.us markets websocket is not connected; cannot send envelope"
            )
        payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        try:
            await client.send_text(payload)
        except (WebSocketClientError, OSError) as exc:
            raise VenueTransportError(
                f"Polymarket.us markets websocket send failed: {type(exc).__name__}"
            ) from None

    def _on_native_reconnection(self) -> None:
        """Public-stream path: the native layer re-handshook, so replay subscriptions.

        Re-subscription is never native (nautilus-trader-patterns, "What you
        MUST build"), so it is wired here even though the handshake was not.
        """
        task = self._loop.create_task(self._replay_subscriptions(), name="polymarket-us-ws-replay")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- supervision ------------------------------------------------------

    async def _supervise(self) -> None:
        """Poll for a dead socket and reconnect with freshly signed headers."""
        while not self._closing:
            await asyncio.sleep(self._poll_secs)
            client = self._client
            if self._closing or client is None:
                continue
            if client.is_reconnecting() or not client.is_closed():
                continue
            self._log.warning(
                "Polymarket.us markets websocket closed; reconnecting with fresh signature"
            )
            if not await self._reconnect_with_backoff():
                self._degraded = True
                self._log.error(
                    "Polymarket.us markets websocket reconnection abandoned after "
                    f"{self._reconnect_max_attempts} retries; the market data feed is down"
                )
                return

    async def _reconnect_with_backoff(self) -> bool:
        retry_manager: RetryManager[bool] = RetryManager(
            max_retries=self._reconnect_max_attempts,
            delay_initial_ms=self._delay_initial_ms,
            delay_max_ms=self._delay_max_ms,
            backoff_factor=self._backoff_factor,
            logger=self._log,
            exc_types=(VenueTransportError,),
        )
        self._retry_manager = retry_manager
        try:
            result = await retry_manager.run(
                "polymarket_us_ws_reconnect", [WS_PATH], self._reconnect_once
            )
        finally:
            self._retry_manager = None
        _reraise_if_cancelled()
        return result is True

    async def _reconnect_once(self) -> bool:
        await self._open()
        await self._replay_subscriptions()
        self._log.info("Polymarket.us markets websocket reconnected and re-subscribed")
        return True


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _reraise_if_cancelled() -> None:
    """Restore cancellation that ``RetryManager.run`` swallowed.

    ``RetryManager.run`` catches ``asyncio.CancelledError`` and returns ``None``
    (``live/retry.py:187-189``). Without this, a cancelled supervisor task would
    keep looping and outlive :meth:`PolymarketUSMarketsWebSocket.close`.
    """
    task = asyncio.current_task()
    if task is not None and task.cancelling() > 0:
        raise asyncio.CancelledError
