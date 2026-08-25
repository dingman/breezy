"""Polymarket.us live market-data client (read-only slice).

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 6 ``data.py`` (``:830-881``) and section 8.3 quote flow
(``:1059-1073``).

Null hypothesis first -- what Nautilus 1.231.0 already provides, and is
therefore NOT rebuilt here:

* subscription bookkeeping and command dispatch: the sync ``subscribe_*`` /
  ``unsubscribe_*`` methods on ``LiveMarketDataClient`` record the
  subscription and schedule the coroutine (``live/data_client.py:608-616``,
  ``:743-751``);
* task creation, error capture and shutdown cancellation: ``create_task`` /
  ``_on_task_completed`` / ``cancel_pending_tasks``
  (``live/data_client.py:459-505``, ``:242-249``);
* delivery: ``_handle_data`` sends to the ``DataEngine.process`` endpoint
  (``data/client.pyx:1262-1263``), which caches the tick and publishes it on
  ``data.quotes.<venue>.<symbol>`` (``common/data_topics.pyx:117-124``);
* transport reconnect, heartbeat and idle timeout: owned by
  ``websocket.PolymarketUSMarketsWebSocket``.

What genuinely has to be authored, with evidence:

1. **client_id / venue derivation.** ``LiveMarketDataClient.__init__`` takes
   ``client_id`` and ``venue`` POSITIONALLY (``live/data_client.py:349-360``)
   and ``PyCondition.type`` checks the instrument provider immediately after
   (``:361``), while ``LiveDataClientFactory.create`` (``live/factories.py:33``)
   is handed ``name`` and no venue at all. :func:`build_data_client` makes the
   derivation explicit and a test pins it.
2. **Frame routing.** Nothing native maps a venue frame onto an
   ``InstrumentId``; :meth:`PolymarketUSDataClient._handle_ws_frame` does, via
   ``symbology``.
3. **Fail-closed safe mode.** ``LiveDataEngine`` calls ``connect()`` exactly
   once and has no notion of a feed that stopped arriving (grep
   ``reconnect|resubscribe`` in ``live/*.py`` and ``data/engine.pyx`` -> zero
   hits). Once the socket's own supervisor gives up, this client marks itself
   disconnected rather than letting a strategy trade off a frozen book.

Two deliberate deviations from the section 6 sketch, both forced:

* The sketch passes a constructed ``ws``. The socket takes its frame handler
  at construction time and this client IS that handler, so the client accepts
  a ``feed_factory`` and calls it with its own bound handler. Passing a
  pre-built socket would require mutating its private handler slot afterwards.
* The sketch also passes ``http_client``. Nothing on the read path uses it --
  instrument loading goes through the provider, quotes through the socket --
  so it is omitted rather than carried as a dead reference to a POST-capable
  object inside a read-only client.

This module is READ-ONLY by construction: it holds no HTTP client, and the
only egress it can cause is a subscribe/unsubscribe envelope on the markets
socket.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import LogColor
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.data.messages import SubscribeQuoteTicks, UnsubscribeQuoteTicks
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.identifiers import ClientId, Venue
from nautilus_trader.model.instruments import Instrument

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.errors import PolymarketUSError
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    instrument_id_to_slug,
    slug_to_instrument_id,
)

__all__ = [
    "MARKET_SLUG_KEY",
    "MISSING_ROUTING_KEY_WARN_EVERY",
    "POLYMARKET_US_VENUE",
    "FrameDiagnostic",
    "MarketsFeed",
    "MarketsFeedFactory",
    "PolymarketUSDataClient",
    "QuoteTickParser",
    "build_data_client",
    "derive_client_id",
    "diagnose_frame_payload",
    "frame_class_counts",
    "should_warn_for_missing_routing_key",
]

# ``POLYMARKET_US_VENUE`` is imported from ``symbology`` and re-exported here:
# this adapter serves exactly one venue, so the venue is a property of the
# adapter and not of the runtime config. (Databento passes ``venue=None`` at
# ``adapters/databento/data.py:138`` because it is multi-venue; that is the
# opposite case and must not be copied.)

#: The frame field carrying the market slug.
#:
#: UNRESOLVED venue fact. The markets WebSocket message schema is undocumented
#: (``polymarket-us-integration`` skill, "Known Contradictions" item 8). The
#: singular of the SDK's ``"marketSlugs"`` subscribe key
#: (``sdk_snapshot/.../websocket/base.py:105-106``) is the only coherent
#: candidate available offline. A frame that does not carry this key is
#: treated as a non-quote frame and never becomes a quote, so a wrong guess
#: degrades to "no quotes" and never to a wrong quote.
#:
#: That degradation is made OBSERVABLE by
#: :attr:`PolymarketUSDataClient.frames_missing_routing_key`, counted on every
#: such frame and surfaced at ``WARN`` (rate limited). Without it a wrong key
#: guess is byte-for-byte indistinguishable from an idle market: zero quotes,
#: zero drops, nothing to alert on. Subscription acknowledgements legitimately
#: land in the same bucket, so the alertable signal is *sustained growth of
#: this counter while* :attr:`PolymarketUSDataClient.quotes_published`
#: *stays at zero*, not the first few frames after connect.
#:
#: Confirmation is a live-probe question for ``polymarket-us-discovery``.
MARKET_SLUG_KEY: Final[str] = "marketSlug"

#: WARN on the first frame missing the routing key, then once every N frames.
#: Rate limited because on a wrong key guess EVERY frame lands there, and a
#: log line per frame is a denial of service against the operator's attention.
MISSING_ROUTING_KEY_WARN_EVERY: Final[int] = 100

#: How often the safe-mode watchdog samples the socket's degraded flag.
DEFAULT_FEED_WATCH_INTERVAL_SECS: Final[float] = 5.0


@dataclass(frozen=True, slots=True)
class FrameDiagnostic:
    """Redaction-safe structure captured for one inbound markets frame."""

    frame_class: str
    keys: tuple[str, ...]
    structure_paths: tuple[str, ...]
    value_types: Mapping[str, str]
    safe_values: Mapping[str, str]
    slug_bearing_keys: tuple[str, ...]


@runtime_checkable
class MarketsFeed(Protocol):
    """The markets-socket surface this client depends on.

    Structurally satisfied by
    :class:`~breezy.adapters.polymarket_us.websocket.PolymarketUSMarketsWebSocket`.
    Declared as a Protocol so the client can be exercised without constructing
    a ``nautilus_pyo3.WebSocketClient``.
    """

    @property
    def is_connected(self) -> bool: ...

    @property
    def is_degraded(self) -> bool: ...

    @property
    def subscriptions(self) -> Mapping[str, str]: ...

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None: ...

    async def unsubscribe(self, request_id: str) -> None: ...


#: Builds the markets feed around the client's bound frame handler.
MarketsFeedFactory = Callable[[Callable[[bytes], None]], MarketsFeed]


class QuoteTickParser(Protocol):
    """The parsing seam (``parsing.parse_quote_tick``, plan Step 7)."""

    def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        instrument: Instrument,
        ts_init: int,
    ) -> QuoteTick: ...


def should_warn_for_missing_routing_key(count: int) -> bool:
    """Rate-limit policy for the missing-routing-key WARN.

    A separate pure function because ``Component._log`` is
    ``cdef readonly`` (``common/component.pxd:226``) and therefore cannot be
    substituted in a test -- the policy would otherwise be unverifiable, and
    an unverifiable rate limiter is how a WARN quietly becomes silence.

    Warns on the FIRST occurrence (so a wrong key guess is visible within one
    frame, not after a hundred), then once every
    :data:`MISSING_ROUTING_KEY_WARN_EVERY` frames.
    """
    if count <= 0:
        return False
    return count == 1 or count % MISSING_ROUTING_KEY_WARN_EVERY == 0


def _classify_frame(payload: Mapping[str, Any]) -> str:
    if "subscribed" in payload:
        return "acknowledgement"
    if "heartbeat" in payload:
        return "heartbeat"
    if "error" in payload:
        return "error"
    if "marketData" in payload:
        return "market_data"
    if "marketDataLite" in payload:
        return "market_data_lite"
    if "trade" in payload:
        return "trade"
    return "unknown"


def _walk_structure(
    value: object,
    *,
    prefix: str,
    paths: list[str],
    value_types: dict[str, str],
    safe_values: dict[str, str],
) -> None:
    paths.append(prefix)
    value_types[prefix] = type(value).__name__
    if isinstance(value, str | int | float | bool) or value is None:
        safe_values[prefix] = str(value)
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _walk_structure(
                child,
                prefix=f"{prefix}.{key}",
                paths=paths,
                value_types=value_types,
                safe_values=safe_values,
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, child in enumerate(value):
            _walk_structure(
                child,
                prefix=f"{prefix}[{index}]",
                paths=paths,
                value_types=value_types,
                safe_values=safe_values,
            )


def _find_slug_paths(payload: Mapping[str, Any], slugs: set[str]) -> tuple[str, ...]:
    paths: list[str] = []

    def walk(value: object, *, prefix: str) -> None:
        if isinstance(value, str) and value in slugs:
            paths.append(prefix)
            return
        if isinstance(value, Mapping):
            for key, child in value.items():
                walk(child, prefix=f"{prefix}.{key}" if prefix else str(key))
            return
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            for index, child in enumerate(value):
                walk(child, prefix=f"{prefix}[{index}]")

    walk(payload, prefix="")
    return tuple(paths)


def diagnose_frame_payload(payload: Mapping[str, Any], slugs: Sequence[str]) -> FrameDiagnostic:
    """Return redaction-safe class, key and value diagnostics for a frame payload."""
    value_types: dict[str, str] = {}
    safe_values: dict[str, str] = {}
    structure_paths: list[str] = []
    for key, value in payload.items():
        _walk_structure(
            value,
            prefix=str(key),
            paths=structure_paths,
            value_types=value_types,
            safe_values=safe_values,
        )
    return FrameDiagnostic(
        frame_class=_classify_frame(payload),
        keys=tuple(sorted(str(key) for key in payload)),
        structure_paths=tuple(sorted(structure_paths)),
        value_types=value_types,
        safe_values=safe_values,
        slug_bearing_keys=_find_slug_paths(payload, set(slugs)),
    )


def _mapping_value(payload: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else None


def _market_slug_from_payload(payload: Mapping[str, Any]) -> Any:
    slug = payload.get(MARKET_SLUG_KEY)
    if slug is not None:
        return slug
    for container_key in ("marketData", "marketDataLite", "trade"):
        nested = _mapping_value(payload, container_key)
        if nested is not None and MARKET_SLUG_KEY in nested:
            return nested[MARKET_SLUG_KEY]
    return None


def frame_class_counts(diagnostics: Sequence[FrameDiagnostic]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for diagnostic in diagnostics:
        counts[diagnostic.frame_class] = counts.get(diagnostic.frame_class, 0) + 1
    return counts


def derive_client_id(name: str) -> ClientId:
    """Derive the client ID from the registered factory name.

    ``name`` is the key under which the client is registered in
    ``data_clients`` and passed to ``add_data_client_factory``
    (``live/node.py:230``), so deriving the ``ClientId`` from it keeps routing
    consistent by construction. Precedent: ``adapters/databento/data.py:137``.
    """
    if not name or not name.strip():
        raise ValueError("client name must be a non-empty string")
    return ClientId(name)


class PolymarketUSDataClient(LiveMarketDataClient):
    """Read-only market data for Polymarket.us weather markets."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        venue: Venue,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: InstrumentProvider,
        config: PolymarketUSDataClientConfig,
        *,
        feed_factory: MarketsFeedFactory,
        quote_parser: QuoteTickParser,
        feed_watch_interval_secs: float = DEFAULT_FEED_WATCH_INTERVAL_SECS,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=venue,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            config=config,
        )
        if feed_watch_interval_secs <= 0:
            raise ValueError("feed_watch_interval_secs must be positive")

        self._venue_config: PolymarketUSDataClientConfig = config
        self._quote_parser: QuoteTickParser = quote_parser
        self._feed: MarketsFeed = feed_factory(self._handle_ws_frame)
        self._feed_watch_interval_secs: float = feed_watch_interval_secs
        self._feed_watchdog: asyncio.Task[None] | None = None
        self._safe_mode: bool = False
        self._dropped_frames: int = 0
        self._frames_missing_routing_key: int = 0
        self._quotes_published: int = 0
        self._frame_diagnostics: list[FrameDiagnostic] = []

    # -- state ------------------------------------------------------------

    @property
    def is_safe_mode(self) -> bool:
        """True once the markets feed was lost and will not come back."""
        return self._safe_mode

    @property
    def dropped_frames(self) -> int:
        """Frames received but not delivered (unroutable or unparseable)."""
        return self._dropped_frames

    @property
    def frames_missing_routing_key(self) -> int:
        """Frames carrying no :data:`MARKET_SLUG_KEY` at all.

        Its own metric rather than part of :attr:`dropped_frames`, because the
        two mean different things: a dropped frame WAS a quote we could not
        use, while these are frames we could not recognise as quotes. Conflating
        them would hide the wrong-key-guess failure inside normal drop noise.
        Alert on this growing while :attr:`quotes_published` stays at zero.
        """
        return self._frames_missing_routing_key

    @property
    def quotes_published(self) -> int:
        """Quotes successfully handed to the data engine. The alert denominator."""
        return self._quotes_published

    @property
    def frame_diagnostics(self) -> tuple[FrameDiagnostic, ...]:
        """Return redaction-safe diagnostics for every inbound dict frame."""
        return tuple(self._frame_diagnostics)

    # -- lifecycle --------------------------------------------------------

    async def _connect(self) -> None:
        self._safe_mode = False
        self._log.info("Initializing instruments...")
        await self._instrument_provider.initialize()
        self._send_all_instruments_to_data_engine()

        await self._feed.connect()

        # One subscribe call per slug, so one requestId maps to exactly one
        # slug and an unsubscribe cannot silently drop a sibling market.
        for slug in self._venue_config.market_slugs:
            await self._feed.subscribe_market_data([slug])

        self._feed_watchdog = self._loop.create_task(
            self._watch_feed(),
            name="polymarket-us-feed-watchdog",
        )

    async def _disconnect(self) -> None:
        await self._cancel_feed_watchdog()
        await self._feed.close()

    async def _cancel_feed_watchdog(self) -> None:
        task = self._feed_watchdog
        self._feed_watchdog = None
        if task is None or task.done():
            return
        current = asyncio.current_task()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Never swallow a cancellation aimed at the CALLER; only the one
            # this method just requested.
            if current is not None and current.cancelling() > 0:
                raise

    def _send_all_instruments_to_data_engine(self) -> None:
        """Publish loaded instruments so the engine and cache both see them.

        Adapter-authored by convention, not a base-class helper: the bundled
        adapters each define their own (``adapters/kraken/data.py:337-342``).
        """
        for instrument in self._instrument_provider.get_all().values():
            self._handle_data(instrument)
        for currency in self._instrument_provider.currencies().values():
            self._cache.add_currency(currency)

    # -- subscriptions ----------------------------------------------------

    async def _subscribe_quote_ticks(self, command: SubscribeQuoteTicks) -> None:
        instrument_id = command.instrument_id
        try:
            slug = instrument_id_to_slug(instrument_id)
        except PolymarketUSError as exc:
            self._log.error(f"Refusing quote subscription for {instrument_id}: {exc}")
            return
        if slug in self._feed.subscriptions:
            self._log.debug(f"Already subscribed to {slug}")
            return
        await self._feed.subscribe_market_data([slug])

    async def _unsubscribe_quote_ticks(self, command: UnsubscribeQuoteTicks) -> None:
        instrument_id = command.instrument_id
        try:
            slug = instrument_id_to_slug(instrument_id)
        except PolymarketUSError as exc:
            self._log.error(f"Refusing quote unsubscription for {instrument_id}: {exc}")
            return
        request_id = self._feed.subscriptions.get(slug)
        if request_id is None:
            self._log.warning(f"No live subscription for {slug}; nothing to unsubscribe")
            return
        await self._feed.unsubscribe(request_id)

    # -- inbound frames ---------------------------------------------------

    def _handle_ws_frame(self, raw: bytes) -> None:
        """Handle one inbound socket frame. Runs on the event-loop thread.

        A malformed or unroutable frame is counted and dropped: one bad frame
        must never take down a live feed, and it must never be settled on
        either.
        """
        try:
            decoded = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            self._drop_frame(f"undecodable frame: {type(exc).__name__}")
            return
        if not isinstance(decoded, dict):
            self._drop_frame(f"unexpected frame type {type(decoded).__name__}")
            return

        payload: Mapping[str, Any] = decoded
        self._frame_diagnostics.append(
            diagnose_frame_payload(payload, self._venue_config.market_slugs)
        )
        slug = _market_slug_from_payload(payload)
        if slug is None:
            # Subscription acknowledgements legitimately share the socket with
            # quotes -- but so does EVERY quote frame if MARKET_SLUG_KEY (an
            # UNRESOLVED venue fact) is guessed wrong. Counting is what makes
            # those two cases distinguishable to an operator.
            self._note_missing_routing_key()
            return
        try:
            instrument_id = slug_to_instrument_id(slug)
        except PolymarketUSError as exc:
            self._drop_frame(f"invalid {MARKET_SLUG_KEY}: {exc}")
            return

        instrument = self._instrument_provider.find(instrument_id)
        if instrument is None:
            instrument = self._cache.instrument(instrument_id)
        if instrument is None:
            self._drop_frame(f"no instrument loaded for {instrument_id}")
            return

        try:
            quote = self._quote_parser(
                payload,
                instrument=instrument,
                ts_init=self._clock.timestamp_ns(),
            )
        except (PolymarketUSError, ValueError, KeyError, TypeError) as exc:
            self._drop_frame(f"unparseable quote for {instrument_id}: {type(exc).__name__}")
            return

        self._handle_data(quote)
        self._quotes_published += 1

    def _drop_frame(self, reason: str) -> None:
        self._dropped_frames += 1
        self._log.error(f"Dropped market-data frame: {reason}")

    def _note_missing_routing_key(self) -> None:
        """Count -- and periodically WARN about -- a frame with no routing key.

        WARN rather than DEBUG because this is the observable symptom of the
        one failure mode the routing-key guess can produce: no quotes, ever,
        looking exactly like a quiet market. Rate limited to the first frame
        and then every :data:`MISSING_ROUTING_KEY_WARN_EVERY` frames, because
        on a wrong guess the rate is the full frame rate of the feed.
        """
        self._frames_missing_routing_key += 1
        count = self._frames_missing_routing_key
        if not should_warn_for_missing_routing_key(count):
            return
        self._log.warning(
            f"{count} inbound market-data frame(s) carried no {MARKET_SLUG_KEY!r} key; "
            f"{self._quotes_published} quote(s) published so far. Subscription "
            "acknowledgements account for a small, bounded number of these. Sustained "
            "growth with no quotes published means the routing-key guess is wrong for "
            "this venue's undocumented WebSocket schema and this feed is delivering "
            "nothing -- treat it as a feed outage, not a quiet market."
        )

    # -- operability ------------------------------------------------------

    async def _watch_feed(self) -> None:
        """Fail closed once the socket's own supervisor has given up.

        The socket owns reconnection, heartbeat and idle timeout. When it
        reports ``is_degraded`` it has stopped retrying, so no further quotes
        are coming and the client must stop presenting itself as connected.
        """
        while True:
            await asyncio.sleep(self._feed_watch_interval_secs)
            if not self._feed.is_degraded:
                continue
            self._safe_mode = True
            self._set_connected(False)
            self._log.error(
                "Markets feed lost and not recoverable; entering safe mode "
                "(client marked disconnected, no further quotes)",
            )
            return


def build_data_client(
    *,
    loop: asyncio.AbstractEventLoop,
    name: str,
    config: PolymarketUSDataClientConfig,
    msgbus: MessageBus,
    cache: Cache,
    clock: LiveClock,
    instrument_provider: InstrumentProvider,
    feed_factory: MarketsFeedFactory,
    quote_parser: QuoteTickParser,
    feed_watch_interval_secs: float = DEFAULT_FEED_WATCH_INTERVAL_SECS,
) -> PolymarketUSDataClient:
    """Wire a data client from the arguments a ``LiveDataClientFactory`` has.

    This is the seam a ``LiveDataClientFactory.create`` staticmethod calls
    after it has resolved credentials and built the signer, transport, HTTP
    client, instrument provider and socket. It exists separately so the
    ``client_id`` / ``venue`` derivation is testable without constructing any
    network object.
    """
    client = PolymarketUSDataClient(
        loop,
        derive_client_id(name),
        POLYMARKET_US_VENUE,
        msgbus,
        cache,
        clock,
        instrument_provider,
        config,
        feed_factory=feed_factory,
        quote_parser=quote_parser,
        feed_watch_interval_secs=feed_watch_interval_secs,
    )
    client._log.info(
        f"Wired {type(client).__name__} as {client.id} for {POLYMARKET_US_VENUE}",
        LogColor.BLUE,
    )
    return client
