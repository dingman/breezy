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

Note on the per-connection subscription cap (live probes, 2026-08-30)
-----------------------------------------------------------------------
The venue enforces :data:`MAX_SUBSCRIPTIONS_PER_CONNECTION` (measured: 10) on
every markets WebSocket connection, and rejects the excess in TWO OBSERVABLY
DIFFERENT ways depending on how the caller batches its ``subscribe`` calls:

1. **One ``subscribe`` envelope carrying many slugs at once.** Subscribing 60
   slugs in a single envelope on one connection returned 50 explicit
   ``{"error": "max subscriptions per connection reached", "requestId":
   "<32-hex>"}`` frames -- one per rejected slug past the first 10.

2. **One ``subscribe`` envelope per slug** (the shape
   :meth:`~breezy.adapters.polymarket_us.data.PolymarketUSDataClient._subscribe_quote_ticks`
   actually sends -- each incoming ``SubscribeQuoteTicks`` command calls
   :meth:`PolymarketUSMarketsWebSocket.subscribe_market_data` with exactly one
   slug). Subscribing 60 slugs this way on one connection produced **ZERO**
   error frames of any kind, and data arrived for EXACTLY the first 10 slugs
   subscribed, in subscribe order. The other 50 were silently dropped with no
   signal on the wire distinguishing them from a market that is simply quiet.

Pattern 2 is why :meth:`PolymarketUSMarketsWebSocket.subscription_errors`
(built from pattern 1) is NOT sufficient on its own: its emptiness proves
nothing about whether every subscribed slug is actually live. Absence of an
error frame is not evidence of a healthy subscription -- only an observed
inbound frame naming that slug is. That is what
:attr:`PolymarketUSMarketsWebSocket.silent_subscriptions` exists to catch: a
POSITIVE, frame-arrival-based check, independent of whether the venue ever
sends an error at all. :class:`PolymarketUSMarketsWebSocketPool` still exists
to keep every connection's subscription COUNT under the cap in the first
place (the only fix for pattern 1, and the reason pattern 2 should never
arise from Breezy's own subscribe calls); the confirmation window is the
belt-and-suspenders check for whatever the count-based fix does not catch --
a future bug in the sharding math, or a slug the venue drops for a reason
unrelated to the cap.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
    "DEFAULT_SUBSCRIPTION_CONFIRMATION_SECS",
    "MAX_SUBSCRIPTIONS_PER_CONNECTION",
    "SUBSCRIPTION_TYPE_MARKET_DATA",
    "WS_PATH",
    "PolymarketUSMarketsWebSocket",
    "PolymarketUSMarketsWebSocketPool",
    "SilentSubscriptionWarning",
    "WebSocketErrorFrame",
    "build_subscribe_envelope",
    "build_unsubscribe_envelope",
]

#: ``sdk_snapshot/polymarket_us_0.1.2/websocket/markets.py:17``.
WS_PATH: Final[str] = "/v1/ws/markets"

#: ``sdk_snapshot/polymarket_us_0.1.2/websocket/markets.py:25``.
SUBSCRIPTION_TYPE_MARKET_DATA: Final[str] = "SUBSCRIPTION_TYPE_MARKET_DATA"

_MS_PER_SECOND: Final[int] = 1_000

#: Empirically measured against the LIVE Polymarket.us venue on 2026-08-30,
#: confirmed by TWO INDEPENDENT probes (module docstring, "Note on the
#: per-connection subscription cap"):
#:
#: * Many slugs in one ``subscribe`` envelope: the venue rejects every slug
#:   past the 10th with ``{"error": "max subscriptions per connection
#:   reached", "requestId": "<32-hex>"}`` -- 50 such frames were observed for
#:   60 slugs subscribed this way on one connection.
#: * One slug per ``subscribe`` envelope (how this adapter actually
#:   subscribes): the SAME 10-slug limit applies, but the venue emits NO
#:   error frame at all -- it silently accepts exactly the first 10 slugs (in
#:   subscribe order) and never sends data for the rest.
#:
#: Either way, nothing on the wire reliably distinguishes a dropped
#: subscription from a quiet market UNLESS you check by BOTH mechanisms: the
#: explicit error (:attr:`PolymarketUSMarketsWebSocket.subscription_errors`)
#: and positive frame-arrival confirmation
#: (:attr:`PolymarketUSMarketsWebSocket.silent_subscriptions`). This constant
#: is the hard per-connection cap that subscription sharding
#: (:class:`PolymarketUSMarketsWebSocketPool`) exists to respect so that
#: NEITHER failure mode can arise from Breezy's own subscribe calls.
#: This is UNDOCUMENTED venue behaviour, not a value from any spec.
MAX_SUBSCRIPTIONS_PER_CONNECTION: Final[int] = 10

#: How long a newly (re)subscribed slug may go without ANY inbound frame
#: naming it before :attr:`PolymarketUSMarketsWebSocket.silent_subscriptions`
#: records it. Not yet tuned against live per-market frame cadence -- chosen
#: generous enough to tolerate a genuinely infrequent-but-live market while
#: still catching pattern-2 silent truncation (module docstring) in a bounded
#: time. A one-sided book (a market whose parsed quote/depth is unusable) is
#: NOT the failure this catches: that market still pushes a raw frame naming
#: its slug, which confirms the subscription here even though downstream
#: parsing later drops it for an unrelated reason.
DEFAULT_SUBSCRIPTION_CONFIRMATION_SECS: Final[float] = 60.0

_MIN_CONFIRMATION_SWEEP_SECS: Final[float] = 0.01
_MAX_CONFIRMATION_SWEEP_SECS: Final[float] = 5.0

#: Wire key carrying a slug on a market-data/trade frame
#: (``data.MARKET_SLUG_KEY``, duplicated here narrowly: this transport module
#: must not import the data-client layer). Used ONLY for the positive
#: liveness check below -- never for routing or parsing, which stay owned by
#: :mod:`breezy.adapters.polymarket_us.data`.
_SLUG_KEY: Final[str] = "marketSlug"
_SLUG_BEARING_CONTAINERS: Final[tuple[str, ...]] = ("marketData", "marketDataLite", "trade")


def _slug_from_payload(payload: Mapping[str, Any]) -> str | None:
    """Best-effort slug extraction for the liveness check ONLY.

    A miss here only delays a genuinely-live slug's confirmation to the next
    frame that names it; a false match cannot happen because ``"marketSlug"``
    is not a key any other frame class (``subscribed``, ``heartbeat``,
    ``error``) is documented to carry.
    """
    slug = payload.get(_SLUG_KEY)
    if isinstance(slug, str):
        return slug
    for container_key in _SLUG_BEARING_CONTAINERS:
        nested = payload.get(container_key)
        if isinstance(nested, Mapping):
            nested_slug = nested.get(_SLUG_KEY)
            if isinstance(nested_slug, str):
                return nested_slug
    return None


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


@dataclass(frozen=True, slots=True)
class WebSocketErrorFrame:
    """One venue-pushed ``{"error": ...}`` frame, decoded for operators.

    Surfaced through :attr:`PolymarketUSMarketsWebSocket.subscription_errors`
    rather than left to fall through into the ordinary "frame carried no
    routing key" counter: a dropped subscription and a quiet market look
    IDENTICAL on the wire (neither carries ``marketSlug``), so this frame
    class gets its own loud, distinct, never-silent path instead.
    """

    error: str
    request_id: str | None


@dataclass(frozen=True, slots=True)
class SilentSubscriptionWarning:
    """A slug that was subscribed but produced NO inbound frame within the window.

    This is the POSITIVE half of the two-sided check the module docstring
    describes: an empty :attr:`PolymarketUSMarketsWebSocket.subscription_errors`
    proves nothing, because one-slug-per-envelope subscriptions past the
    venue's cap are dropped with no error frame at all (pattern 2). This
    warning is generated purely from the ABSENCE of a confirming frame, never
    from the presence or absence of an error.
    """

    slug: str
    subscribed_after_secs: float


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
    connection_label : str
        Identifies this connection in logs. Used by
        :class:`PolymarketUSMarketsWebSocketPool` to distinguish its shards
        (``"shard-0"``, ``"shard-1"``, ...); irrelevant for a standalone
        connection.
    confirmation_window_secs : float or None
        Enables :attr:`silent_subscriptions` when set: a subscribed slug that
        produces no inbound frame within this many seconds is flagged.
        ``None`` (the default here) disables it -- POSITIVE liveness checking
        is opt-in on a bare connection and defaults ON only at
        :class:`PolymarketUSMarketsWebSocketPool`, the actual production path
        (module docstring, "Note on the per-connection subscription cap").
    """

    __slots__ = (
        "_backoff_factor",
        "_client",
        "_closing",
        "_confirmation_task",
        "_confirmation_window_secs",
        "_connection_label",
        "_degraded",
        "_delay_initial_ms",
        "_delay_max_ms",
        "_handler",
        "_heartbeat_secs",
        "_idle_timeout_secs",
        "_log",
        "_loop",
        "_pending_confirmation",
        "_poll_secs",
        "_reconnect_max_attempts",
        "_request_id_factory",
        "_retry_manager",
        "_signer",
        "_silent_subscriptions",
        "_subscription_errors",
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
        connection_label: str = "single",
        confirmation_window_secs: float | None = None,
    ) -> None:
        if heartbeat_secs <= 0:
            raise ValueError("heartbeat_secs must be positive")
        if idle_timeout_secs <= 0:
            raise ValueError("idle_timeout_secs must be positive")
        if supervisor_poll_secs <= 0:
            raise ValueError("supervisor_poll_secs must be positive")
        if reconnect_max_attempts < 0:
            raise ValueError("reconnect_max_attempts must not be negative")
        if confirmation_window_secs is not None and confirmation_window_secs <= 0:
            raise ValueError("confirmation_window_secs must be positive")

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
        self._connection_label: str = connection_label
        self._confirmation_window_secs: float | None = confirmation_window_secs

        self._client: WebSocketClient | None = None
        #: slug -> requestId. One subscribe call covers many slugs under one id.
        self._subscriptions: dict[str, str] = {}
        self._supervisor: asyncio.Task[None] | None = None
        self._confirmation_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any] | asyncio.Future[Any]] = set()
        self._retry_manager: RetryManager[bool] | None = None
        self._closing: bool = False
        self._degraded: bool = False
        self._subscription_errors: list[WebSocketErrorFrame] = []
        #: slug -> loop time it was (re)subscribed. Popped the moment ANY
        #: frame naming that slug arrives; a survivor at sweep time becomes a
        #: `SilentSubscriptionWarning`.
        self._pending_confirmation: dict[str, float] = {}
        self._silent_subscriptions: list[SilentSubscriptionWarning] = []

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
        """True once this connection can no longer be trusted to deliver every
        subscription it was asked to carry.

        This is the ONE fail-closed signal a data client actually polls
        (:meth:`~breezy.adapters.polymarket_us.data.PolymarketUSDataClient.sample_feed_health`
        reads only this property, on a fixed cadence, and enters safe mode the
        moment it is True). Two independent conditions set it, both
        unrecoverable by waiting:

        1. Reconnection was abandoned (:meth:`_supervise`) -- the socket is
           gone and no further quotes of ANY kind will arrive.
        2. A subscribed slug was confirmed silently dropped by the venue
           (:meth:`_watch_for_silent_subscriptions`) -- the socket is alive,
           but at least one slug the caller believes is live is not, and
           Polymarket.us weather markets cannot be backfilled. Reusing this
           same signal, rather than adding a second one nothing polls, is
           deliberate: see :attr:`silent_subscriptions` for the raw detail
           and the module docstring's "Note on the per-connection
           subscription cap" for why a quiet market and a dropped
           subscription must never look identical.
        """
        return self._degraded

    @property
    def subscriptions(self) -> Mapping[str, str]:
        return dict(self._subscriptions)

    @property
    def subscription_errors(self) -> tuple[WebSocketErrorFrame, ...]:
        """Every venue ``{"error": ...}`` frame received on this connection.

        Never populated by anything else and never cleared: a frame here means
        the venue explicitly rejected a subscription, which is not
        recoverable by waiting -- it must be investigated, not just logged.
        Empty does NOT mean every subscription is live -- see
        :attr:`silent_subscriptions` and the module docstring's pattern 2.
        """
        return tuple(self._subscription_errors)

    @property
    def silent_subscriptions(self) -> tuple[SilentSubscriptionWarning, ...]:
        """Every slug that outlived ``confirmation_window_secs`` with no inbound frame.

        Populated ONLY by positive evidence (or its absence), never by
        ``subscription_errors``: the venue's silent-truncation failure mode
        (module docstring, pattern 2) sends no error frame at all, so a check
        keyed on errors would report a fully healthy connection while
        silently capturing nothing for the dropped slugs. Empty forever when
        ``confirmation_window_secs`` was not set at construction.
        """
        return tuple(self._silent_subscriptions)

    # -- lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Open the socket and start the reconnect supervisor and/or confirmation watch."""
        if self.is_connected:
            return
        self._closing = False
        self._degraded = False
        await self._open()
        if self.requires_auth and self._supervisor is None:
            self._supervisor = self._loop.create_task(
                self._supervise(), name="polymarket-us-ws-supervisor"
            )
        if self._confirmation_window_secs is not None and self._confirmation_task is None:
            self._confirmation_task = self._loop.create_task(
                self._watch_for_silent_subscriptions(),
                name="polymarket-us-ws-confirmation-watch",
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
        confirmation_task = self._confirmation_task
        self._confirmation_task = None
        if confirmation_task is not None:
            self._tasks.add(confirmation_task)
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
        self._arm_confirmation(pending)

    async def unsubscribe(self, request_id: str) -> None:
        """Cancel one subscription request and forget every slug it covered."""
        await self._send(build_unsubscribe_envelope(request_id=request_id))
        for slug in [s for s, rid in self._subscriptions.items() if rid == request_id]:
            del self._subscriptions[slug]
            self._pending_confirmation.pop(slug, None)

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
            # A resubscribe on a NEW connection needs its own confirmation:
            # frames observed on the old connection do not prove this one
            # accepted the replay.
            self._arm_confirmation(slugs)

    def _arm_confirmation(self, slugs: Sequence[str]) -> None:
        if self._confirmation_window_secs is None:
            return
        now = self._loop.time()
        for slug in slugs:
            self._pending_confirmation[slug] = now

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
                handler=self._on_frame,
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

    def _on_frame(self, raw: bytes) -> None:
        """Inspect every inbound frame for a venue error or a slug confirmation.

        The frame still reaches ``self._handler`` unchanged either way -- this
        never suppresses or rewrites what the data client sees. It only ADDS
        two loud, distinct, queryable records: an explicit rejection
        (``subscription_errors``, pattern 1) and, independently, positive
        confirmation that a subscribed slug is actually producing frames
        (``silent_subscriptions`` catches the ABSENCE of this, pattern 2 --
        see the module docstring). Decoded once and shared between both
        checks rather than parsing the frame twice.
        """
        decoded = self._decode_frame(raw)
        if decoded is not None:
            self._record_subscription_error_if_present(decoded)
            self._record_confirmation_if_present(decoded)
        self._handler(raw)

    @staticmethod
    def _decode_frame(raw: bytes) -> dict[str, Any] | None:
        try:
            decoded = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        return decoded if isinstance(decoded, dict) else None

    def _record_subscription_error_if_present(self, decoded: Mapping[str, Any]) -> None:
        error = decoded.get("error")
        if error is None:
            return
        request_id = decoded.get("requestId")
        frame = WebSocketErrorFrame(
            error=str(error),
            request_id=str(request_id) if request_id is not None else None,
        )
        self._subscription_errors.append(frame)
        self._log.error(
            f"Polymarket.us markets websocket ({self._connection_label}) rejected a "
            f"subscription request: {frame.error!r} (requestId={frame.request_id!r}). "
            "The venue did NOT apply this subscription -- treat every slug on this "
            "connection as unverified, never as a quiet market."
        )

    def _record_confirmation_if_present(self, decoded: Mapping[str, Any]) -> None:
        if not self._pending_confirmation:
            return
        slug = _slug_from_payload(decoded)
        if slug is not None:
            self._pending_confirmation.pop(slug, None)

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
        """Poll for a dead socket and reconnect with freshly signed headers.

        Every exit from this coroutine other than a deliberate close is FATAL
        for the feed: nothing else in the process reconnects this socket, and
        Nautilus has no notion of a data client that stopped producing
        (``LiveDataEngine.connect`` calls ``client.connect()`` once and never
        looks again). So both fatal exits -- retry exhaustion and an
        unexpected exception -- must set ``is_degraded``, which is the signal
        ``PolymarketUSDataClient.sample_feed_health`` already polls and now
        escalates to a clean node shutdown with a non-zero exit status.

        Before this, only exhaustion set it. An exception ended the task
        silently: ``is_connected`` stayed True, ``is_degraded`` stayed False,
        and an unattended recorder kept a healthy-looking, permanently
        unsupervised socket for the rest of the capture window.

        Cancellation is deliberately NOT degradation and is re-raised
        untouched -- ``close()`` sets ``_closing`` before it cancels, and a
        cancelled supervisor is a shutdown, not a feed failure.
        """
        try:
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - deliberate: see below
            # Type name only, never the message: transport exception text is
            # venue-controlled and must not reach a log record.
            self._degraded = True
            self._log.error(
                "Polymarket.us markets websocket supervisor died unexpectedly "
                f"({type(exc).__name__}); no further reconnection will be "
                "attempted and the market data feed is down"
            )

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

    # -- confirmation -------------------------------------------------------

    async def _watch_for_silent_subscriptions(self) -> None:
        """Periodically flag any pending slug that has outlived the confirmation window.

        POSITIVE detection only: this task never looks at
        ``subscription_errors`` and never treats their absence as success.
        The 2026-08-30 live probe proved that reading absence-of-error as
        health is exactly how pattern-2 silent truncation goes unnoticed --
        one-slug-per-envelope subscriptions past the cap draw NO error frame
        at all. A slug is confirmed the instant ANY frame names it; if none
        arrives within the window it is reported once, here, and left in
        place -- re-subscribing or escalating is a data-client/operator
        decision, not this transport's.

        A confirmed silent slug also sets :attr:`is_degraded`. Before this,
        ``silent_subscriptions``/``subscription_errors`` were populated but
        read by nothing outside this module and its tests: ``is_connected``
        stayed True and ``is_degraded`` stayed False forever, so a silently
        truncated feed was indistinguishable from a healthy one to every
        automated consumer. Reusing ``is_degraded`` -- the same fail-closed
        signal reconnect-abandonment already sets -- costs no new wiring in
        :class:`~breezy.adapters.polymarket_us.data.PolymarketUSDataClient`,
        whose ``sample_feed_health`` already polls exactly this property on a
        fixed cadence and enters safe mode the moment it is True (data.py
        ``sample_feed_health``). A distinct signal would need its own
        consumer wired into that client -- a parallel alerting path for a
        codebase whose whole point is that a dropped slug must never look
        healthy to whatever already watches for "not healthy".
        """
        window = self._confirmation_window_secs
        if window is None:  # pragma: no cover -- only ever scheduled when set
            return
        sweep_interval = max(
            min(window, _MAX_CONFIRMATION_SWEEP_SECS), _MIN_CONFIRMATION_SWEEP_SECS
        )
        while not self._closing:
            await asyncio.sleep(sweep_interval)
            if self._closing:
                return
            now = self._loop.time()
            stale = [
                slug
                for slug, subscribed_at in self._pending_confirmation.items()
                if now - subscribed_at >= window
            ]
            for slug in stale:
                elapsed = now - self._pending_confirmation.pop(slug)
                warning = SilentSubscriptionWarning(slug=slug, subscribed_after_secs=elapsed)
                self._silent_subscriptions.append(warning)
                # Fail closed on the SAME signal reconnect-abandonment already
                # sets -- see the docstring above for why this reuses
                # `is_degraded` instead of adding a second, unpolled signal.
                self._degraded = True
                self._log.error(
                    f"Polymarket.us markets websocket ({self._connection_label}): "
                    f"{slug!r} was subscribed {elapsed:.1f}s ago and has produced NO "
                    "inbound frame since. Absence of an error frame is NOT proof this "
                    "subscription is live (see the module docstring's silent-truncation "
                    "note) -- treat this slug as UNCONFIRMED, never as a quiet market. "
                    "Marking this connection degraded so the data client fails closed."
                )


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


class PolymarketUSMarketsWebSocketPool:
    """Shard market-data subscriptions across connections to respect the venue cap.

    Polymarket.us enforces :data:`MAX_SUBSCRIPTIONS_PER_CONNECTION`
    subscriptions per WebSocket connection (see that constant's docstring for
    the live 2026-08-30 measurement). Subscribing more on one connection does
    not queue or error visibly at the caller -- the venue accepts exactly the
    cap and silently drops the rest, which for Polymarket.us weather markets
    (no history, no vendor backfill) means a PERMANENT, unrecoverable data
    loss with no local symptom.

    This pool is a :class:`~breezy.adapters.polymarket_us.data.MarketsFeed`
    that owns one or more :class:`PolymarketUSMarketsWebSocket` connections
    ("shards"), each capped at ``cap`` subscriptions, and opens exactly
    ``ceil(N / cap)`` of them for ``N`` distinct subscribed slugs. A slug is
    assigned to exactly one shard for its lifetime; :meth:`subscribe_market_data`
    fills the newest shard before opening another.

    Reconnection is per shard BY CONSTRUCTION: each shard is a fully
    independent ``PolymarketUSMarketsWebSocket`` with its own supervisor task
    and retry state (module docstring), so one shard degrading never touches
    another shard's connection, subscriptions, or in-flight frames.

    Positive liveness confirmation (:data:`DEFAULT_SUBSCRIPTION_CONFIRMATION_SECS`)
    defaults ON here, unlike on a bare ``PolymarketUSMarketsWebSocket``: this
    pool is the actual production feed, and the count-based sharding above is
    the fix for pattern-1 over-subscription, not for pattern-2 silent
    truncation, which produces no error frame to react to (module docstring).

    UNPROVEN AGAINST THE LIVE VENUE (as of 2026-08-30)
    --------------------------------------------------
    This pool has NEVER been observed carrying a live ``QuoteTick``. The only
    end-to-end evidence attempt --
    ``docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_2026-08-30T155317+0000.md``
    -- reported 0 frames, but its WebSocket step failed authentication
    (finding E1: ``/v1/ws/markets`` requires authentication), so those zeros
    are evidence about the PROBE, not about this pool. Everything above is
    therefore verified only by unit tests and by venue documentation, never by
    a live quote. Remove this statement ONLY when authenticated end-to-end
    evidence exists showing a ``QuoteTick`` reaching the ``DataEngine`` for
    EVERY subscribed slug.
    """

    __slots__ = (
        "_backoff_factor",
        "_cap",
        "_confirmation_window_secs",
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
        "_shards",
        "_signer",
        "_slug_to_shard",
        "_subscribe_lock",
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
        cap: int = MAX_SUBSCRIPTIONS_PER_CONNECTION,
        confirmation_window_secs: float | None = DEFAULT_SUBSCRIPTION_CONFIRMATION_SECS,
    ) -> None:
        if cap <= 0:
            raise ValueError("cap must be positive")

        self._ws_url: str = ws_url
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
        # ONE factory shared by every shard: request ids stay unique pool-wide,
        # which `unsubscribe` depends on to find the shard that owns one.
        self._request_id_factory: Callable[[], str] = (
            request_id_factory if request_id_factory is not None else _new_request_id
        )
        self._cap: int = cap
        self._confirmation_window_secs: float | None = confirmation_window_secs

        #: Built eagerly (never connected) so configuration -- URL, signer --
        #: is inspectable before `connect()`, exactly like a bare
        #: `PolymarketUSMarketsWebSocket`. Preserves existing <= cap behaviour:
        #: one shard, opened by `connect()`, subscribed to incrementally.
        self._shards: list[PolymarketUSMarketsWebSocket] = [self._build_shard(0)]
        self._slug_to_shard: dict[str, PolymarketUSMarketsWebSocket] = {}
        #: Serializes `subscribe_market_data` end to end -- see that method's
        #: docstring for the race this closes.
        self._subscribe_lock: asyncio.Lock = asyncio.Lock()

    # -- state --------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return bool(self._shards) and all(shard.is_connected for shard in self._shards)

    @property
    def is_degraded(self) -> bool:
        """True once ANY shard has abandoned reconnection.

        Fail-closed like the single-connection signal it aggregates: one lost
        shard means that shard's slugs stop flowing, which is enough to say
        the feed as a whole is no longer fully healthy.
        """
        return any(shard.is_degraded for shard in self._shards)

    @property
    def subscriptions(self) -> Mapping[str, str]:
        merged: dict[str, str] = {}
        for shard in self._shards:
            merged.update(shard.subscriptions)
        return merged

    @property
    def subscription_errors(self) -> tuple[WebSocketErrorFrame, ...]:
        errors: list[WebSocketErrorFrame] = []
        for shard in self._shards:
            errors.extend(shard.subscription_errors)
        return tuple(errors)

    @property
    def silent_subscriptions(self) -> tuple[SilentSubscriptionWarning, ...]:
        """Every slug, on any shard, unconfirmed by an inbound frame in time.

        See :attr:`PolymarketUSMarketsWebSocket.silent_subscriptions`: this is
        the POSITIVE check that catches pattern-2 truncation, which produces
        no entry in :attr:`subscription_errors` at all.
        """
        warnings: list[SilentSubscriptionWarning] = []
        for shard in self._shards:
            warnings.extend(shard.silent_subscriptions)
        return tuple(warnings)

    @property
    def shard_count(self) -> int:
        return len(self._shards)

    # -- lifecycle ------------------------------------------------------------

    async def connect(self) -> None:
        """Connect every shard that is not already connected.

        On the very first call this is exactly one shard -- new shards are
        opened lazily, only once :meth:`subscribe_market_data` needs the room.

        A later shard's ``connect()`` raising must not leave an earlier shard
        in THIS call connected-and-orphaned: the caller only learns of the
        failure via the raised exception and never gets a reference back to
        close what already succeeded, so this method closes its own partial
        work before re-raising. Pre-existing already-connected shards (from a
        prior successful call) are left untouched -- they were never part of
        this attempt.
        """
        newly_connected: list[PolymarketUSMarketsWebSocket] = []
        try:
            for shard in self._shards:
                if not shard.is_connected:
                    await shard.connect()
                    newly_connected.append(shard)
        except BaseException:
            await asyncio.gather(
                *(shard.close() for shard in newly_connected), return_exceptions=True
            )
            raise

    async def close(self) -> None:
        """Close every shard, even if an earlier one raises or is cancelled.

        A bare sequential loop would abandon every shard after the first
        failure, orphaning its socket and its supervisor/confirmation tasks --
        for a venue whose weather markets cannot be backfilled, an
        unsupervised leaked shard is exactly the kind of silent, unrecoverable
        loss this module exists to prevent. ``asyncio.gather(...,
        return_exceptions=True)`` guarantees every shard's ``close()`` is
        attempted before this method returns or raises.
        """
        results = await asyncio.gather(
            *(shard.close() for shard in self._shards), return_exceptions=True
        )
        cancelled: asyncio.CancelledError | None = None
        errors: list[BaseException] = []
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                cancelled = result
            elif isinstance(result, BaseException):
                errors.append(result)
        for error in errors:
            # Type name only. See the module note on transport exception text.
            self._log.error(
                "Polymarket.us markets websocket pool: a shard failed to close "
                f"cleanly: {type(error).__name__}"
            )
        if cancelled is not None:
            # Cancellation must propagate, never be swallowed by cleanup --
            # but every shard above still got its close() attempted first.
            raise cancelled
        if errors:
            raise VenueTransportError(
                f"Polymarket.us markets websocket pool: {len(errors)} of "
                f"{len(self._shards)} shard(s) failed to close cleanly"
            ) from errors[0]

    # -- subscriptions ------------------------------------------------------

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None:
        """Subscribe every not-yet-subscribed slug, sharded at the venue cap.

        Fills the most recently opened shard to ``cap`` before opening
        another, so ``N`` distinct slugs open exactly ``ceil(N / cap)`` shards
        regardless of whether they arrive in one call or many.

        The entire read-room -> commit-batch sequence runs under
        ``_subscribe_lock``. Without it, ``_shard_with_room`` reads
        ``len(shard.subscriptions)`` and this method reads ``_slug_to_shard``
        BEFORE the ``await shard.subscribe_market_data(batch)`` boundary, and
        both are written only AFTER it returns. Two overlapping calls --
        exactly what happens in production, since Nautilus's
        ``LiveMarketDataClient.subscribe_quote_ticks`` fires each
        ``SubscribeQuoteTicks`` command via an unawaited ``create_task`` --
        can then both observe the same stale room or the same
        not-yet-routed slug and both commit into it: either pushing one
        shard's live subscription count above ``cap`` (silently reproducing
        the exact over-cap truncation this pool exists to prevent), or
        routing the SAME slug onto two different shards. A single
        ``asyncio.Lock`` serializing the whole method is the smallest fix
        that closes both: this pool is not on Breezy's hot path (subscribe
        calls are infrequent, discovery-driven events, not a per-tick loop),
        so pool-wide serialization costs nothing worth a finer-grained
        reservation scheme.
        """
        async with self._subscribe_lock:
            pending = [
                slug for slug in dict.fromkeys(market_slugs) if slug not in self._slug_to_shard
            ]
            if not pending:
                return
            index = 0
            while index < len(pending):
                shard = await self._shard_with_room()
                room = self._cap - len(shard.subscriptions)
                batch = pending[index : index + room]
                await shard.subscribe_market_data(batch)
                for slug in batch:
                    self._slug_to_shard[slug] = shard
                index += len(batch)

    async def unsubscribe(self, request_id: str) -> None:
        """Cancel one subscription request on whichever shard owns it."""
        for shard in self._shards:
            removed_slugs = [
                slug for slug, rid in shard.subscriptions.items() if rid == request_id
            ]
            if not removed_slugs:
                continue
            await shard.unsubscribe(request_id)
            for slug in removed_slugs:
                self._slug_to_shard.pop(slug, None)
            return
        raise VenueTransportError(
            f"Polymarket.us markets websocket pool: no shard owns requestId {request_id!r}"
        )

    # -- internal -------------------------------------------------------------

    def _build_shard(self, index: int) -> PolymarketUSMarketsWebSocket:
        return PolymarketUSMarketsWebSocket(
            ws_url=self._ws_url,
            signer=self._signer,
            handler=self._handler,
            loop=self._loop,
            heartbeat_secs=self._heartbeat_secs,
            idle_timeout_secs=self._idle_timeout_secs,
            logger=self._log,
            supervisor_poll_secs=self._poll_secs,
            reconnect_max_attempts=self._reconnect_max_attempts,
            reconnect_delay_initial_ms=self._delay_initial_ms,
            reconnect_delay_max_ms=self._delay_max_ms,
            reconnect_backoff_factor=self._backoff_factor,
            request_id_factory=self._request_id_factory,
            connection_label=f"shard-{index}",
            confirmation_window_secs=self._confirmation_window_secs,
        )

    async def _shard_with_room(self) -> PolymarketUSMarketsWebSocket:
        last = self._shards[-1]
        if len(last.subscriptions) < self._cap:
            if not last.is_connected:
                await last.connect()
            return last
        shard = self._build_shard(len(self._shards))
        await shard.connect()
        self._shards.append(shard)
        return shard
