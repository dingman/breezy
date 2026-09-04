"""Polymarket.us live market-data client (read-only slice).

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
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
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import LogColor
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.data import Data
from nautilus_trader.data.messages import SubscribeQuoteTicks, UnsubscribeQuoteTicks
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.model.data import CustomData, DataType, QuoteTick
from nautilus_trader.model.identifiers import ClientId, InstrumentId, Venue
from nautilus_trader.model.instruments import BinaryOption, Instrument

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.errors import EmptyBookSideError, PolymarketUSError
from breezy.adapters.polymarket_us.feed_fault import record_fatal_feed_fault
from breezy.adapters.polymarket_us.parsing import (
    EXPIRED_MARKET_STATES,
    TERMINAL_SETTLEMENT_METHOD,
    TRADE_CONTAINER_KEY,
    depth_levels_dropped,
    parse_instrument_close,
    parse_instrument_status,
    parse_mark_price,
    parse_order_book_depth10,
    parse_quote_tick,
    parse_settlement_snapshot,
    parse_trade_tick,
    venue_market_state,
    venue_settlement_method,
)
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    instrument_id_to_slug,
    slug_to_instrument_id,
)
from breezy.adapters.polymarket_us.tape_records import (
    DepthTruncation,
    QuoteTapeGap,
    VenueClockOffset,
)

__all__ = [
    "CLOCK_OFFSET_SAMPLE_EVERY",
    "CLOCK_OFFSET_SOURCE",
    "DISCOVERY_RELOAD_CEILING_SECS",
    "DISCOVERY_RELOAD_FLOOR_SECS",
    "FATAL_SHUTDOWN_REQUEST_BUDGET",
    "MARKET_SLUG_KEY",
    "MISSING_ROUTING_KEY_WARN_EVERY",
    "ONE_SIDED_BOOK_SUMMARY_EVERY",
    "POLYMARKET_US_VENUE",
    "FrameDiagnostic",
    "MarketsFeed",
    "MarketsFeedFactory",
    "PolymarketUSDataClient",
    "QuoteTickParser",
    "ReloadDelay",
    "SilentSubscription",
    "SubscriptionChangePlan",
    "build_data_client",
    "derive_client_id",
    "derive_reload_delay_secs",
    "diagnose_frame_payload",
    "frame_class_counts",
    "instrument_boundaries_ns",
    "should_report_at_count",
    "should_warn_at_count",
    "subscription_changes_after_discovery",
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

#: How often the running one-sided-book TOTAL is restated in the log.
#:
#: The per-instrument notice fires once and then never again, so on a long
#: unattended run the last line about a one-sided book would be minutes old
#: while the condition kept occurring tens of thousands of times. This restates
#: the running total at a deliberately coarse cadence -- roughly eight lines an
#: hour at the rate measured on a 60-market weather capture -- so the VOLUME is
#: legible from the log alone, without an operator attaching to the process to
#: read :attr:`PolymarketUSDataClient.one_sided_book_refusals`.
#:
#: Coarser than :data:`MISSING_ROUTING_KEY_WARN_EVERY` on purpose: that alarm
#: signals a possible total feed outage and must be seen early, whereas this
#: one describes a condition that is already known to be benign and handled.
ONE_SIDED_BOOK_SUMMARY_EVERY: Final[int] = 1000

#: How often the safe-mode watchdog samples the socket's degraded flag.
DEFAULT_FEED_WATCH_INTERVAL_SECS: Final[float] = 5.0

#: Topic ``Component.shutdown_system`` publishes on
#: (``common/component.pyx:2182``). Duplicated here for ONE purpose -- a
#: diagnostic that says out loud when nothing is listening, i.e. when the
#: shutdown this client just requested cannot possibly be acted on. Never used
#: to publish: authoring a shutdown command by hand is exactly the
#: reimplementation the native call exists to avoid.
SHUTDOWN_COMMAND_TOPIC: Final[str] = "commands.system.shutdown"

#: How many times ONE unrecoverable feed fault may (re-)issue the native
#: ``ShutdownSystem`` command before the watchdog stops re-checking.
#:
#: More than one, because ``Component.shutdown_system`` only PUBLISHES:
#: ``NautilusKernel._on_shutdown_system`` (``system/kernel.py:613-628``) drops
#: the command on a ``trader_id`` mismatch (warning), when ``not _is_running``
#: (warning) and when ``_is_stopping`` (silently) -- and tells the publisher
#: none of that. A one-shot request that was dropped would get no second
#: chance from anywhere, leaving the node running forever on a dead feed: the
#: exact failure the fail-closed path exists to eliminate, one layer up.
#:
#: Small and BOUNDED, because a dead feed is sampled every few seconds for
#: hours and must never become an unbounded command stream at the kernel.
FATAL_SHUTDOWN_REQUEST_BUDGET: Final[int] = 3

#: How long the missing-instrument alert waits for the data engine to drain
#: its queue before it reports an instrument as absent from the cache (BL-22).
#:
#: Generous on purpose, and free when nothing is wrong: the check returns the
#: instant every instrument resolves, so this ceiling is only ever paid by a
#: cycle that has a genuine problem to report. Being impatient here is what
#: produced 60 spurious ERROR lines per discovery cycle.
INSTRUMENT_CACHE_DRAIN_TIMEOUT_SECS: Final[float] = 5.0

#: Poll interval while waiting for the above. Short enough to be invisible on
#: the connect path, long enough not to spin the loop.
INSTRUMENT_CACHE_DRAIN_POLL_SECS: Final[float] = 0.01

#: Publish one :class:`VenueClockOffset` every N market-data frames carrying a
#: venue timestamp. Frame-driven rather than time-driven so the sampler costs
#: no timer and, more importantly, no extra network egress: the offset is
#: derived from data already on the socket. A silent feed publishes no offset,
#: which is correct -- there is nothing to compare.
CLOCK_OFFSET_SAMPLE_EVERY: Final[int] = 200

#: What the offset series compares. Recorded on every record so a reader never
#: has to guess which two clocks produced the number.
CLOCK_OFFSET_SOURCE: Final[str] = "ws-transact-time"

#: Shortest gap the derived discovery reload is ever allowed to schedule.
#:
#: Reasoning, not taste. (1) Rate limit: the discovery quota is 6 requests per
#: minute (``PolymarketUSDataClientConfig.discovery_requests_per_minute``) and
#: one reload cycle is at least one paginated ``GET /v1/markets``; reloading
#: faster than once a minute spends the whole budget on discovery and starves
#: the instrument and book reads that share the transport. (2) Hot-loop
#: safety: a stale or malformed payload whose boundaries have all already
#: passed derives a delay of zero, and without a floor that is a tight
#: request loop against the venue. Every clamp to this value is logged.
DISCOVERY_RELOAD_FLOOR_SECS: Final[float] = 60.0

#: Longest gap the derived discovery reload is ever allowed to schedule.
#:
#: Reasoning from the captured payloads. Weather markets turn over daily at
#: 05:00Z (``raw/markets_categories_climate.json``: every market carries
#: ``endDate`` at ``T05:00:00Z``), and the venue LISTS the next day's ladder
#: well before that -- ``raw/market_open_510636_by_slug.json`` has
#: ``startDate = 2026-08-24T09:45:21Z`` against ``endDate =
#: 2026-08-26T05:00:00Z``, a ~19 hour lead. A market listed just after a
#: reload would therefore go unseen for most of a day if the derived delay
#: were allowed to run to the next boundary unbounded. Six hours bounds that
#: discovery lag to a small fraction of the listing lead while still costing
#: only four discovery cycles a day. It also makes an absurd boundary -- a
#: corrupt ``endDate`` in the year 2200 -- unable to park the reload loop
#: forever. Every clamp to this value is logged.
DISCOVERY_RELOAD_CEILING_SECS: Final[float] = 6 * 60 * 60.0


@dataclass(frozen=True, slots=True)
class ReloadDelay:
    """The outcome of one cadence derivation.

    Attributes
    ----------
    seconds : float
        How long to wait before the next discovery reload.
    clamped : str | None
        ``None`` when the venue's own boundary was used verbatim; otherwise
        ``"floor"`` or ``"ceiling"``, naming which guard engaged. Carried
        rather than silently applied so the caller can log it loudly.
    boundary_ns : int | None
        The upcoming boundary the delay targets, or ``None`` when every known
        boundary is already in the past (a stale payload).
    """

    seconds: float
    clamped: str | None
    boundary_ns: int | None


def instrument_boundaries_ns(instruments: Sequence[Instrument]) -> tuple[int, ...]:
    """Collect venue turnover instants from NATIVE Nautilus instrument fields.

    Null hypothesis, and it holds: nothing new stores these. The venue's
    ``startDate`` and ``endDate`` are already mapped onto the native
    ``Instrument.activation_ns`` / ``.expiration_ns`` by
    ``parsing.parse_binary_option``, so the discovered market set already
    carries every boundary this derivation needs and no parallel boundary
    store is built.

    ``gameStartTime`` is deliberately NOT a boundary: it marks the start of the
    climate day for a market that is already listed and already discovered, so
    it never changes the discovered SET. Only activation and expiration do.
    """
    boundaries: list[int] = []
    for instrument in instruments:
        for attribute in ("activation_ns", "expiration_ns"):
            value = getattr(instrument, attribute, None)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                boundaries.append(value)
    return tuple(boundaries)


def derive_reload_delay_secs(
    *,
    now_ns: int,
    boundaries_ns: Sequence[int],
) -> ReloadDelay:
    """Derive the next discovery reload delay from the discovered market set.

    The venue states its own turnover instants, so the bot reads them rather
    than being told a cadence (G-19 B2). The next reload targets the SOONEST
    upcoming boundary among the markets currently known.

    An empty boundary set is a RETRY AT THE FLOOR, not a fatal invariant, and
    it is the one sanctioned fallback-on-failure in this adapter. It is
    reachable at a cold start inside a fully-settled window: ``load_all_async``
    refuses only a *zero-discovered* cycle, so if every discovered market
    carries a ``resolved_reason`` it ``continue``s before ``self.add(...)`` and
    SUCCEEDS while ``get_all()`` stays empty. Raising here killed the reload
    task on its first iteration -- permanently, because that loop is the only
    thing that would ever discover the next day's ladder, so the bot went
    quietly and irrecoverably blind. Every other guard in this adapter fails
    shut on purpose; this one must not, because the floor is bounded (a request
    every :data:`DISCOVERY_RELOAD_FLOOR_SECS`, well inside the venue budget)
    while blindness is unbounded.

    The floor is returned with ``clamped="floor"`` so the caller logs it
    loudly. It is never applied silently.
    """
    if not boundaries_ns:
        return ReloadDelay(DISCOVERY_RELOAD_FLOOR_SECS, "floor", None)
    upcoming = [boundary for boundary in boundaries_ns if boundary > now_ns]
    boundary_ns = min(upcoming) if upcoming else None
    raw_secs = 0.0 if boundary_ns is None else (boundary_ns - now_ns) / 1e9
    if raw_secs < DISCOVERY_RELOAD_FLOOR_SECS:
        return ReloadDelay(DISCOVERY_RELOAD_FLOOR_SECS, "floor", boundary_ns)
    if raw_secs > DISCOVERY_RELOAD_CEILING_SECS:
        return ReloadDelay(DISCOVERY_RELOAD_CEILING_SECS, "ceiling", boundary_ns)
    return ReloadDelay(raw_secs, None, boundary_ns)


@dataclass(frozen=True, slots=True)
class FrameDiagnostic:
    """Redaction-safe structure captured for one inbound markets frame."""

    frame_class: str
    keys: tuple[str, ...]
    structure_paths: tuple[str, ...]
    value_types: Mapping[str, str]
    safe_values: Mapping[str, str]
    slug_bearing_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubscriptionChangePlan:
    """Cache-gated subscription changes after one discovery cycle."""

    subscribe: tuple[str, ...]
    unsubscribe: tuple[tuple[str, str], ...]
    blocked_missing_cache: tuple[str, ...]


def subscription_changes_after_discovery(
    *,
    desired_slugs: Sequence[str],
    live_slugs: Sequence[str],
    cached_slugs: frozenset[str],
    resolved_reasons: Mapping[str, str],
) -> SubscriptionChangePlan:
    """Plan WS subscription changes while enforcing cache-before-subscribe."""
    desired = tuple(dict.fromkeys(desired_slugs))
    live = tuple(dict.fromkeys(live_slugs))
    live_set = set(live)
    desired_set = set(desired)

    blocked = tuple(slug for slug in desired if slug not in live_set and slug not in cached_slugs)
    subscribe = tuple(slug for slug in desired if slug not in live_set and slug in cached_slugs)
    unsubscribe = tuple(
        (slug, resolved_reasons.get(slug, "discovery-missing"))
        for slug in live
        if slug not in desired_set or slug in resolved_reasons
    )
    return SubscriptionChangePlan(
        subscribe=subscribe,
        unsubscribe=unsubscribe,
        blocked_missing_cache=blocked,
    )


class SilentSubscription(Protocol):
    """One slug the feed accepted but has never produced a frame for.

    Structurally satisfied by
    :class:`~breezy.adapters.polymarket_us.websocket.SilentSubscriptionWarning`.
    Declared structurally, like :class:`MarketsFeed` itself, so the data-client
    layer can REPORT an unconfirmed subscription without importing the
    transport module.
    """

    @property
    def slug(self) -> str: ...

    @property
    def subscribed_after_secs(self) -> float: ...


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
    def is_degraded(self) -> bool:
        """True when the feed is not FULLY healthy: fatal and non-fatal faults.

        Reporting only. Never a stop condition: it is also raised by a single
        unconfirmed subscription on an otherwise live socket.
        """
        ...

    @property
    def is_fatally_degraded(self) -> bool:
        """The feed is gone and nothing in the process recovers it.

        The ONLY signal this client may end the run over; see
        :meth:`PolymarketUSDataClient.sample_feed_health`.
        """
        ...

    @property
    def silent_subscriptions(self) -> Sequence[SilentSubscription]:
        """Slugs the venue accepted but has never delivered a frame for.

        Loud (reported at ERROR, once per slug) and deliberately not fatal.
        """
        ...

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


def should_report_at_count(count: int, *, every: int) -> bool:
    """Report on the FIRST occurrence, then once every ``every`` occurrences.

    The one rate-limit rule in this module, parameterised by cadence. Reports
    immediately so a new condition is visible within one frame rather than
    after a hundred, then bounds itself so a condition that occurs at the full
    frame rate of the feed cannot become a denial of service against the
    operator's attention.

    A pure function, and separate from the caller, because ``Component._log``
    is ``cdef readonly`` (``common/component.pxd:226``) and therefore cannot
    be substituted in a test -- the policy would otherwise be unverifiable,
    and an unverifiable rate limiter is how a report quietly becomes silence.
    """
    if count <= 0 or every <= 0:
        return False
    return count == 1 or count % every == 0


def should_warn_at_count(count: int) -> bool:
    """Rate-limit policy for a repeating WARN, shared by every such alarm here.

    Named for what it does rather than for its first caller: it now also gates
    the depth-truncation warning, where a name mentioning routing keys would
    actively mislead a reader.

    A separate pure function because ``Component._log`` is
    ``cdef readonly`` (``common/component.pxd:226``) and therefore cannot be
    substituted in a test -- the policy would otherwise be unverifiable, and
    an unverifiable rate limiter is how a WARN quietly becomes silence.

    Warns on the FIRST occurrence (so a wrong key guess is visible within one
    frame, not after a hundred), then once every
    :data:`MISSING_ROUTING_KEY_WARN_EVERY` occurrences.

    Delegates to :func:`should_report_at_count` rather than restating the
    rule, so the one-sided-book summary and this warning cannot drift apart.
    """
    return should_report_at_count(count, every=MISSING_ROUTING_KEY_WARN_EVERY)


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
        quote_parser: QuoteTickParser = parse_quote_tick,
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
        self._update_instruments_task: asyncio.Task[None] | None = None
        self._safe_mode: bool = False
        # Bounds the native shutdown request in `sample_feed_health`. That
        # method is public and callable on a cadence, so without a ceiling a
        # dead feed would spray `ShutdownSystem` commands at the kernel -- and
        # with a ceiling of ONE, a command the kernel dropped would never be
        # re-issued (see `FATAL_SHUTDOWN_REQUEST_BUDGET`).
        self._fatal_shutdown_requests: int = 0
        # Slugs already reported as silent. Reported once per SLUG, never once
        # per sample: the watchdog samples every few seconds for eight hours.
        self._silent_subscription_slugs: set[str] = set()
        # The owning node's NATIVE `instance_id`, threaded via config because
        # neither `MessageBus` nor `LiveDataClientFactory.create` exposes it
        # (see `PolymarketUSDataClientConfig.recorder_instance_id`). Falls back
        # to a per-process UUID4 so a client built OUTSIDE the recorder role
        # still produces partitionable rows -- never to a blank, which
        # `QuoteTapeGap` refuses outright.
        self._recorder_instance_id: str = (
            config.recorder_instance_id or f"unmanaged-{uuid.uuid4()}"
        )
        self._dropped_frames: int = 0
        self._frames_missing_routing_key: int = 0
        self._quotes_published: int = 0
        self._frame_diagnostics: list[FrameDiagnostic] = []
        # Tape-gap accounting. `None` for "never sampled yet", so the very
        # first sample cannot be mistaken for a transition.
        self._feed_was_connected: bool | None = None
        self._gap_opened_ns: int | None = None
        self._tape_gaps: int = 0
        self._tape_gap_seconds_total: float = 0.0
        self._trades_published: int = 0
        self._depth_levels_truncated: int = 0
        self._clock_offset_samples: int = 0
        self._quote_parse_failures: int = 0
        # One-sided-book accounting. Reported once per INSTRUMENT, never once
        # per frame -- the same shape as `_silent_subscription_slugs` above,
        # for the same reason: the condition recurs at the full frame rate.
        self._one_sided_book_instruments: set[str] = set()
        self._one_sided_book_refusals: int = 0
        self._expired_without_terminal_settlement: int = 0
        self._missing_cache_alerts: int = 0

    # -- state ------------------------------------------------------------

    @property
    def is_safe_mode(self) -> bool:
        """True once the markets feed was lost and will not come back."""
        return self._safe_mode

    @property
    def silent_subscription_alerts(self) -> int:
        """Distinct slugs the feed accepted but never delivered a frame for.

        Counted, and logged at ERROR once each, because the quotes for those
        slugs are being lost and this venue's weather markets cannot be
        backfilled. Deliberately NOT a stop condition: the socket is alive and
        every other slug is still recording (see
        :attr:`~breezy.adapters.polymarket_us.websocket.PolymarketUSMarketsWebSocket.is_degraded`).
        Alert on it; investigate it; never end the capture over it.
        """
        return len(self._silent_subscription_slugs)

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
    def quote_parse_failures(self) -> int:
        """Market-data frames that arrived but yielded no quote.

        Its own counter rather than part of :attr:`dropped_frames`, because
        such a frame is usually NOT dropped: a settled market publishes an
        empty book alongside its settlement price, and that settlement record
        is kept. The two facts mean different things -- "the book stopped being
        quotable" versus "the frame was unusable" -- and conflating them would
        hide a tape that has silently stopped carrying prices while still
        looking busy.

        The two counters OVERLAP and must never be summed. A frame that yields
        no quote AND nothing else -- a truncated payload carrying only its
        routing key -- increments BOTH. The increment is deliberately NOT gated
        on other records having been published: that would zero this counter in
        exactly the total-garbage case where it is most diagnostic. Pinned by
        ``tests/unit/test_quote_tape_consumer_contract.py::TestCounterSemantics``.
        """
        return self._quote_parse_failures

    @property
    def one_sided_book_refusals(self) -> int:
        """Quote refusals caused by an empty book side. The VOLUME, at a glance.

        This is the routine, expected case and carries NO data loss: the
        populated side is still recorded as ``OrderBookDepth10`` (BL-18), and
        the venue's state, mark price and settlement provenance are still
        recorded beside it. What is lost is only the two-sided ``QuoteTick``,
        which the venue did not supply the inputs for.

        Counts REFUSALS, not frames or markets -- it is exactly the number of
        log lines this condition used to emit at ERROR, one per frame, so an
        operator comparing this against :attr:`one_sided_book_instruments`
        sees both how loud the old reporting was and how few distinct markets
        are behind it.

        A SUBSET of :attr:`quote_parse_failures`, never a separate population:
        every refusal counted here also increments that counter, because the
        frame genuinely yielded no quote. The two must never be summed.
        """
        return self._one_sided_book_refusals

    @property
    def one_sided_book_instruments(self) -> int:
        """Distinct instruments seen with a one-sided book. The REPORT count.

        Exactly the number of log lines the condition has produced, because
        the notice fires once per instrument on first sighting and never
        again for that instrument. A market that goes one-sided for the first
        time therefore still produces a fresh line, while a market that has
        been one-sided for eight hours produces none.

        Deliberately NOT reset when a market recovers to a two-sided book:
        the question this answers is "which markets have ever failed to
        quote", and re-reporting a market that flaps would reintroduce the
        per-frame noise this replaces.
        """
        return len(self._one_sided_book_instruments)

    @property
    def expired_without_terminal_settlement(self) -> int:
        """Frames whose market is EXPIRED but whose method is not TIER_1.

        The provenance record lands on disk either way
        (``VenueSettlementSnapshot`` with ``is_terminal=False``), so this is a
        convenience for spotting the condition from the running process rather
        than the record of it. A market stuck here has expired without the
        venue publishing a terminally-computed price, and no ``InstrumentClose``
        will be written until it does.

        Counts FRAMES, not markets: a market that republishes while stuck
        increments this repeatedly. It is a smoke signal, not a population.
        """
        return self._expired_without_terminal_settlement

    @property
    def trades_published(self) -> int:
        """Executed prints handed to the data engine."""
        return self._trades_published

    @property
    def depth_levels_truncated(self) -> int:
        """Book levels the ten-per-side native carrier could not keep.

        Non-zero is EXPECTED, not an error: the committed capture carries 12
        bid and 14 offer levels. It is surfaced because slippage measured from
        this tape is valid only down to the tenth level, and an analyst has no
        other way to learn where the recorded book ends.
        """
        return self._depth_levels_truncated

    @property
    def frame_diagnostics(self) -> tuple[FrameDiagnostic, ...]:
        """Return redaction-safe diagnostics for every inbound dict frame."""
        return tuple(self._frame_diagnostics)

    @property
    def tape_gaps(self) -> int:
        """Observed interruptions of the quote feed. **A LOWER BOUND.**

        Quotes that occur while the socket is down are lost permanently --
        Polymarket.us weather markets cannot be backfilled. The socket's
        supervisor reconnects and replays subscriptions, so the recorded tape
        RESUMES and nothing in the resulting parquet says it ever stopped.
        This counter is the only thing that does.

        Why it is explicitly a lower bound, and not corrected to be exact:

        * a gap shorter than the watchdog's sample interval is not seen at all;
        * a gap still open when the process exits is counted, but its duration
          stops accruing at the last sample;
        * the socket's own internal retry may complete between two samples.

        Analysis that joins this tape to anything else must treat an absence
        of quotes as unknown, not as an absence of trading. Publishing a number
        that is honestly a floor is what makes that possible; publishing one
        that pretends to be exact is how a hole becomes a conclusion.
        """
        return self._tape_gaps

    @property
    def tape_gap_seconds_total(self) -> float:
        """Wall-clock seconds observed with the feed down. Lower bound, as above."""
        return self._tape_gap_seconds_total

    @property
    def is_tape_gap_open(self) -> bool:
        """True while the feed is down RIGHT NOW and quotes are being lost."""
        return self._gap_opened_ns is not None

    @property
    def missing_cache_alerts(self) -> int:
        """Instruments reported absent from the cache after an engine push.

        Non-zero means a discovered market that the streaming writer cannot
        resolve, and therefore quotes that would be silently dropped from the
        tape (``persistence/writer.py:212-232`` returns without writing when
        the instrument is absent). It counts REPORTS, not distinct markets: a
        slug missing on three discovery cycles increments three times.

        Deliberately NOT incremented for an instrument the data engine has
        merely not drained from its queue yet -- see
        :meth:`_alert_on_missing_cache_after_push`.
        """
        return self._missing_cache_alerts

    # -- lifecycle --------------------------------------------------------

    async def _connect(self) -> None:
        self._safe_mode = False
        self._log.info("Initializing instruments...")
        await self._instrument_provider.initialize()
        self._send_all_instruments_to_data_engine()
        await self._alert_on_missing_cache_after_push(self._provider_active_slugs())

        try:
            await self._feed.connect()
        except Exception as exc:  # noqa: BLE001 - any connect failure is fatal here
            # Nautilus's own `LiveDataClient.connect()` wrapper
            # (`live/data_client.py:222-234`) runs `_connect` in a task whose
            # completion callback (`:190-210`) does nothing on failure but
            # `self._log.exception(...)`: it never marks the client
            # connected, never re-raises, and never asks the node to stop.
            # `NautilusKernel.start_async` then only WARNS on the resulting
            # connection timeout and returns (`system/kernel.py:1021-1023`,
            # `:1298-1313`) -- so an unhandled `_connect` failure here would
            # leave the node "RUNNING" forever, connected to nothing. Reuse
            # the SAME fatal-fault latch and native shutdown request the
            # feed-loss watchdog already uses below, from the one place a
            # connect failure is actually observed.
            self._safe_mode = True
            self._set_connected(False)
            reason = f"Polymarket.us markets feed failed to connect: {exc}"
            self._request_fatal_shutdown(reason)
            return

        await self._reconcile_discovered_subscriptions(cycle="initial")

        self._update_instruments_task = self.create_task(
            self._update_instruments(),
            log_msg="update_instruments",
        )

        self._feed_watchdog = self._loop.create_task(
            self._watch_feed(),
            name="polymarket-us-feed-watchdog",
        )

    async def _disconnect(self) -> None:
        await self._cancel_update_instruments()
        await self._cancel_feed_watchdog()
        await self._feed.close()

    async def _cancel_update_instruments(self) -> None:
        task = self._update_instruments_task
        self._update_instruments_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

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

    def _next_reload_delay_secs(self) -> float:
        """Seconds until the next discovery reload.

        An explicit ``instrument_reload_interval_mins`` is an OPTIONAL
        operator override (staging host, test double) and wins when present.
        With it unset -- the default -- the cadence is DERIVED from the venue's
        own turnover instants on the currently-discovered market set, so no
        human has to recite a number the payload already states (G-19 B2).
        """
        override = self._venue_config.instrument_reload_interval_mins
        if override is not None:
            return float(override) * 60.0

        outcome = derive_reload_delay_secs(
            now_ns=self._clock.timestamp_ns(),
            boundaries_ns=instrument_boundaries_ns(
                list(self._instrument_provider.get_all().values())
            ),
        )
        if outcome.clamped is not None:
            self._log.warning(
                "Polymarket.us discovery reload cadence clamped to the "
                f"{outcome.clamped} of {outcome.seconds:.0f}s; soonest upcoming "
                f"venue boundary was {outcome.boundary_ns!r} against clock "
                f"{self._clock.timestamp_ns()}. A stale or malformed market "
                "payload is the usual cause.",
                LogColor.YELLOW,
            )
        return outcome.seconds

    async def _update_instruments(self) -> None:
        """Reload discovered instruments forever; exit ONLY on cancellation.

        Nautilus calls ``connect()`` once and provides no reconnection and no
        rediscovery, so this loop is the sole path by which the bot ever learns
        about the next day's market ladder. An exception escaping it is
        therefore not a failed cycle -- it is permanent, silent blindness.
        The derivation below already falls back to the floor rather than
        raising; this handler is the structural guarantee that a FUTURE
        derivation which raises for a new reason cannot blind the bot either.
        """
        try:
            while True:
                try:
                    delay_secs = self._next_reload_delay_secs()
                except PolymarketUSError as exc:
                    delay_secs = DISCOVERY_RELOAD_FLOOR_SECS
                    self._log.error(
                        "Polymarket.us reload cadence could not be derived "
                        f"({type(exc).__name__}: {exc}); retrying at the "
                        f"{delay_secs:.0f}s floor. The reload loop is never "
                        "allowed to exit: it is the only path to the next "
                        "day's market ladder.",
                        LogColor.RED,
                    )
                self._log.debug(
                    "Scheduled task 'update_instruments' to run in "
                    f"{delay_secs:.0f} seconds"
                )
                await asyncio.sleep(delay_secs)
                try:
                    await self._run_one_reload_cycle()
                except Exception as exc:  # noqa: BLE001 - deliberate: see below
                    # `asyncio.CancelledError` derives from `BaseException`, so
                    # cancellation still propagates to the handler below and
                    # shutdown is unaffected. A FAILED CYCLE, by contrast, is
                    # only ever a failed cycle: a venue outage, a malformed
                    # discovery payload, or a rejected status must not end the
                    # one loop that would recover from it on the next pass.
                    self._log.error(
                        "Polymarket.us discovery reload cycle failed "
                        f"({type(exc).__name__}: {exc}); the reload loop "
                        "continues and will retry on the next scheduled pass.",
                        LogColor.RED,
                    )
        except asyncio.CancelledError:
            self._log.debug("Canceled task 'update_instruments'")

    async def _run_one_reload_cycle(self) -> None:
        """One discovery reload pass. Extracted so the loop can survive it."""
        before = len(self._provider_active_slugs())
        await self._instrument_provider.initialize(reload=True)
        self._send_all_instruments_to_data_engine()
        after_slugs = self._provider_active_slugs()
        self._alert_on_discovery_counts(before=before, after=len(after_slugs))
        await self._alert_on_missing_cache_after_push(after_slugs)
        await self._reconcile_discovered_subscriptions(cycle="reload")

    async def _reconcile_discovered_subscriptions(self, *, cycle: str) -> None:
        desired = self._provider_active_slugs()
        live = tuple(self._feed.subscriptions)
        cached = frozenset(
            slug
            for slug in desired
            if self._cache.instrument(slug_to_instrument_id(slug, self.venue)) is not None
        )
        resolved = self._provider_resolved_reasons()
        plan = subscription_changes_after_discovery(
            desired_slugs=desired,
            live_slugs=live,
            cached_slugs=cached,
            resolved_reasons=resolved,
        )
        for slug in plan.blocked_missing_cache:
            self._log.error(
                "Polymarket.us discovery found slug "
                f"{slug!r} but cache.instrument is None after engine push; "
                "refusing to subscribe before the streaming writer can resolve it"
            )
        for slug, reason in plan.unsubscribe:
            request_id = self._feed.subscriptions.get(slug)
            if request_id is None:
                continue
            self._log.warning(
                f"Polymarket.us discovery cycle {cycle}: unsubscribing {slug} ({reason})"
            )
            await self._feed.unsubscribe(request_id)
        for slug in plan.subscribe:
            self._log.info(f"Polymarket.us discovery cycle {cycle}: subscribing {slug} (new)")
            await self._feed.subscribe_market_data([slug])
        self._log.info(
            "Polymarket.us discovery cycle "
            f"{cycle}: subscribed={plan.subscribe!r} unsubscribed={plan.unsubscribe!r} "
            f"blocked_missing_cache={plan.blocked_missing_cache!r}"
        )

    def _provider_active_slugs(self) -> tuple[str, ...]:
        value = getattr(self._instrument_provider, "active_market_slugs", ())
        return tuple(value) if isinstance(value, Sequence) else ()

    def _provider_market_slugs(self) -> tuple[str, ...]:
        value = getattr(self._instrument_provider, "market_slugs", ())
        return tuple(value) if isinstance(value, Sequence) else ()

    def _provider_resolved_reasons(self) -> Mapping[str, str]:
        value = getattr(self._instrument_provider, "resolved_market_reasons", {})
        return dict(value) if isinstance(value, Mapping) else {}

    def _alert_on_discovery_counts(self, *, before: int, after: int) -> None:
        resolved = self._provider_resolved_reasons()
        self._log.info(
            f"Polymarket.us discovery count before={before} after={after} "
            f"resolved={len(resolved)}"
        )
        if after == 0:
            self._log.error(
                "Polymarket.us discovery produced zero active markets this cycle; "
                "this is not treated as a quiet tape"
            )
        if after < before and not resolved:
            self._log.error(
                "Polymarket.us discovery active market count dropped "
                f"from {before} to {after} without a resolved-market explanation"
            )

    async def _alert_on_missing_cache_after_push(self, slugs: Sequence[str]) -> None:
        """Report discovered markets the data engine never put in the cache.

        The condition is real and worth an ERROR: an instrument absent from
        the cache is one ``StreamingFeatherWriter.write`` cannot resolve, and
        it returns without writing rather than complaining
        (``persistence/writer.py:212-232``) -- so that market's quotes leave
        the tape silently.

        What was wrong (BL-22) was the TIMING, not the alert. This ran
        immediately after ``_send_all_instruments_to_data_engine()`` with no
        ``await`` in between, and ``DataClient._handle_data`` only
        ``_msgbus.send``s to the ``DataEngine.process`` endpoint
        (``data/client.pyx:1262-1263``). On a live node that endpoint is
        ``LiveDataEngine.process`` (``live/data_engine.py:324-343``), which
        ENQUEUES onto an ``asyncio.Queue`` drained by the ``_run_data_queue``
        task (``:477-497``). Until the loop yields, nothing has been cached
        and EVERY instrument looks missing: 60 ERROR lines per discovery
        cycle, every cycle, for the whole run. In an eight-hour unattended log
        that is where a real error goes to hide.

        So this now OBSERVES the engine's post-processing state instead of
        racing it: it waits, bounded, for the cache to reflect the push and
        alerts only on what is still absent when the engine has had its
        chance. Bounded rather than open-ended because a stalled engine must
        delay the connect path, never deadlock it.
        """
        for slug, instrument_id in await self._await_instrument_cache(slugs):
            self._missing_cache_alerts += 1
            self._log.error(
                "Polymarket.us discovery found slug "
                f"{slug!r} but cache.instrument({instrument_id}) is None "
                f"{INSTRUMENT_CACHE_DRAIN_TIMEOUT_SECS:.0f}s after publishing "
                "instruments to the data engine; the streaming writer cannot "
                "resolve it and its quotes would be dropped from the tape"
            )

    async def _await_instrument_cache(
        self, slugs: Sequence[str]
    ) -> tuple[tuple[str, InstrumentId], ...]:
        """Wait, bounded, for pushed instruments to appear. Return the absent.

        Returns as soon as every slug resolves, so a healthy cycle costs at
        most one event-loop turn. Only a genuinely missing instrument pays the
        full deadline, and it pays it once per discovery cycle.

        The cache is polled rather than awaited on an event because Nautilus
        offers no completion signal for the queue: ``LiveDataEngine`` exposes
        ``data_qsize()`` but the engine is not reachable from a ``DataClient``,
        and an empty queue would in any case not prove the last item had
        finished being handled. The cache IS the post-processing state this
        alert is about, so it is the thing observed.
        """
        pending = tuple(
            (slug, slug_to_instrument_id(slug, self.venue)) for slug in slugs
        )
        deadline_ns = self._clock.timestamp_ns() + int(
            INSTRUMENT_CACHE_DRAIN_TIMEOUT_SECS * 1_000_000_000
        )
        first_pass = True
        while True:
            pending = tuple(
                entry for entry in pending if self._cache.instrument(entry[1]) is None
            )
            if not pending:
                return ()
            if self._clock.timestamp_ns() >= deadline_ns:
                return pending
            # One bare loop turn first: on a live node that is normally all
            # the queue drain needs, so the happy path adds no fixed delay.
            await asyncio.sleep(0 if first_pass else INSTRUMENT_CACHE_DRAIN_POLL_SECS)
            first_pass = False

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
        if self._cache.instrument(instrument_id) is None:
            self._log.error(
                f"Refusing quote subscription for {instrument_id}: cache.instrument is "
                "None, so streaming persistence would silently drop the first quote"
            )
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
        """Turn one inbound frame into EVERY record it can support.

        A market-data frame carries far more than a top-of-book quote: ten-plus
        levels of depth per side, the venue's ``state``, and the venue's own
        ``settlementPx``. Publishing only the quote discarded the rest, and
        Polymarket.us weather markets have no history, so each discarded field
        was a permanent per-frame loss.

        The record types are INDEPENDENT. A frame whose book is empty -- which
        is exactly what a settled market looks like -- still yields the
        settlement value, which is the single most valuable record the venue
        ever sends. Conversely a frame that yields nothing at all is dropped and
        counted, so a schema change cannot become silence.
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
            diagnose_frame_payload(payload, self._provider_market_slugs())
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

        ts_init = self._clock.timestamp_ns()
        published = 0
        if TRADE_CONTAINER_KEY in payload:
            published += self._publish_trade(payload, instrument, ts_init)
        else:
            published += self._publish_market_data(payload, instrument, ts_init)

        if published == 0:
            self._drop_frame(f"frame for {instrument_id} yielded no usable record")

    def _publish_market_data(
        self, payload: Mapping[str, Any], instrument: Instrument, ts_init: int
    ) -> int:
        """Publish quote, depth, state and mark/close from one market-data frame.

        Each is attempted separately and a failure in one never suppresses the
        others: the failure modes are genuinely independent (an empty book is
        normal at settlement, a missing ``settlementPx`` is normal early in a
        market's life), and coupling them would make the most common benign
        case delete the most valuable record.
        """
        published = 0
        quote = self._try_parse(
            payload, instrument, ts_init, self._quote_parser, "quote", required=True
        )
        if quote is None:
            self._quote_parse_failures += 1
        else:
            self._handle_data(quote)
            self._quotes_published += 1
            published += 1

        if isinstance(instrument, BinaryOption):
            depth = self._try_parse(
                payload, instrument, ts_init, parse_order_book_depth10, "depth", required=False
            )
            if depth is not None:
                self._handle_data(depth)
                published += 1
                published += self._note_depth_truncation(payload, depth, ts_init)

            for parser, label in (
                (parse_instrument_status, "state"),
                (parse_mark_price, "mark price"),
                (parse_instrument_close, "settlement"),
                (parse_settlement_snapshot, "settlement provenance"),
            ):
                record = self._try_parse(
                    payload, instrument, ts_init, parser, label, required=False
                )
                if record is None:
                    continue
                # The settlement-provenance record is a custom type and must be
                # wrapped; the other three are native and must not be.
                if isinstance(record, Data) and type(record).__module__.endswith(
                    "tape_records"
                ):
                    self._publish_custom(record)
                else:
                    self._handle_data(record)
                published += 1

            if (
                venue_market_state(payload) in EXPIRED_MARKET_STATES
                and venue_settlement_method(payload) != TERMINAL_SETTLEMENT_METHOD
            ):
                self._expired_without_terminal_settlement += 1

        self._sample_clock_offset(quote, ts_init)
        return published

    def _publish_trade(
        self, payload: Mapping[str, Any], instrument: Instrument, ts_init: int
    ) -> int:
        """Publish an executed print.

        Executed prints are the only ground truth for what actually traded
        rather than what was merely quoted, and they cannot be reconstructed
        from a quote tape afterwards.
        """
        if not isinstance(instrument, BinaryOption):
            return 0
        trade = self._try_parse(
            payload, instrument, ts_init, parse_trade_tick, "trade", required=False
        )
        if trade is None:
            return 0
        self._handle_data(trade)
        self._trades_published += 1
        return 1

    def _try_parse(
        self,
        payload: Mapping[str, Any],
        instrument: Instrument,
        ts_init: int,
        parser: Callable[..., Any],
        label: str,
        *,
        required: bool,
    ) -> Any:
        """Run one parser, converting any venue-payload failure into ``None``.

        ``required=True`` logs at ERROR (the quote is the record everything else
        is measured against); the rest log at DEBUG, because their absence is
        routinely legitimate and an ERROR per frame would drown the operator.
        Nothing is ever substituted for a value the venue did not send.

        **One refusal is exempt from that ERROR, by TYPE.** An empty book side
        is the venue's normal state on a thin weather market, is already fully
        handled (depth is still recorded), and arrives here at the full frame
        rate: a live 60-market capture produced 85 ERROR lines in its first
        minute, roughly 50,000 over a ten-hour run, which buries the one real
        error an unattended operator needs to see. It is therefore routed to
        :meth:`_note_one_sided_book`, which reports it once per instrument at
        INFO. The routing is on
        :class:`~breezy.adapters.polymarket_us.errors.EmptyBookSideError`, not
        on the message text, so a malformed level, an out-of-range price, a
        crossed book or a moved schema all still take the ERROR branch below.
        """
        try:
            return parser(payload, instrument=instrument, ts_init=ts_init)
        except EmptyBookSideError as exc:
            self._note_one_sided_book(instrument, exc)
            return None
        except (PolymarketUSError, ValueError, KeyError, TypeError) as exc:
            message = (
                f"Could not parse {label} for {instrument.id}: {type(exc).__name__}"
            )
            if required:
                self._log.error(message)
            else:
                self._log.debug(message)
            return None

    def _note_one_sided_book(self, instrument: Instrument, exc: EmptyBookSideError) -> None:
        """Report an expected, already-handled one-sided book. Once per instrument.

        **Severity is INFO, and that is the fix.** The condition is routine
        (the repo's measured median top-of-book bid on these markets is 0.3
        contracts), it is fully handled (the populated side is still recorded
        as depth), and it needs no operator action. Logging it at ERROR once
        per frame is what BL-22 was, in a different file: a log an operator
        cannot read is a log that hides the failure it exists to surface.

        **Cadence follows the precedent already in this class.**
        :meth:`_report_new_silent_subscriptions` reports once per SLUG rather
        than once per sample, for the same reason -- a per-occurrence line is
        emitted at the rate of the feed, not at the rate of new information.
        The set is what bounds it, and it is also what guarantees a market
        that goes one-sided for the FIRST time still produces a fresh line.

        **Volume stays legible** through :attr:`one_sided_book_refusals`, which
        is restated in the log every
        :data:`ONE_SIDED_BOOK_SUMMARY_EVERY` refusals so an unattended run does
        not go hours with no indication of the rate.

        Nothing about capture changes here: this method only counts and logs.
        """
        self._one_sided_book_refusals += 1
        instrument_key = str(instrument.id)
        if instrument_key not in self._one_sided_book_instruments:
            self._one_sided_book_instruments.add(instrument_key)
            self._log.info(
                f"Order book for {instrument_key} has an empty {exc.side!r} side, so no "
                "two-sided QuoteTick can be formed. EXPECTED and HANDLED: the populated "
                "side IS still being recorded as depth, along with the venue state, mark "
                "price and settlement provenance. Reported once per instrument -- "
                f"{self._one_sided_book_refusals} refusal(s) across "
                f"{len(self._one_sided_book_instruments)} instrument(s) so far. A payload "
                "malformed for any other reason is a different condition and is still "
                "reported at ERROR."
            )
            return
        if should_report_at_count(
            self._one_sided_book_refusals, every=ONE_SIDED_BOOK_SUMMARY_EVERY
        ):
            self._log.info(
                f"{self._one_sided_book_refusals} quote(s) refused so far because a book "
                f"side was empty, across {len(self._one_sided_book_instruments)} "
                f"instrument(s); {self._quotes_published} quote(s) published. Running "
                "total only -- the condition is expected on thin weather markets and "
                "depth capture is unaffected."
            )

    def _note_depth_truncation(
        self, payload: Mapping[str, Any], depth: Any, ts_init: int
    ) -> int:
        """Record -- to the TAPE -- how much of this snapshot did not fit.

        A process-memory counter cannot answer the question an analyst actually
        asks: *was THIS snapshot, the one beside my crossing event, truncated?*
        Runtime logs may never reach the study; the archive does. So the marker
        is a record of its own, stamped with the same ``ts_event`` as the depth
        record it describes, giving an exact join rather than a
        nearest-neighbour guess.

        Deliberately NOT stuffed into ``OrderBookDepth10.flags``: that is a
        Nautilus-defined bitfield with documented meanings, and overloading it
        would make Breezy's tape misread by any standard Nautilus consumer.

        Emitted only when something was dropped, so absence means "nothing was
        dropped" -- which is the common case for a quiet market.

        Returns the number of records published (0 or 1).
        """
        dropped = depth_levels_dropped(payload)
        if dropped <= 0:
            return 0

        market_data = payload.get("marketData")
        bids_seen = asks_seen = 0
        if isinstance(market_data, Mapping):
            for key, attr in (("bids", "bid"), ("offers", "ask")):
                side = market_data.get(key)
                count = (
                    len(side)
                    if isinstance(side, Sequence) and not isinstance(side, str | bytes | bytearray)
                    else 0
                )
                if attr == "bid":
                    bids_seen = count
                else:
                    asks_seen = count

        self._depth_levels_truncated += dropped
        self._publish_custom(
            DepthTruncation(
                instrument_id=depth.instrument_id,
                bid_levels_seen=bids_seen,
                ask_levels_seen=asks_seen,
                levels_dropped=dropped,
                ts_event=depth.ts_event,
                ts_init=ts_init,
            )
        )
        if should_warn_at_count(self._depth_levels_truncated):
            self._log.warning(
                f"{self._depth_levels_truncated} book level(s) discarded so far: the "
                "venue is publishing more than the 10 levels per side that "
                "OrderBookDepth10 carries. Slippage measured from this tape is "
                "valid only up to the tenth level; the per-snapshot "
                "DepthTruncation records say exactly which snapshots are affected."
            )
        return 1

    def _sample_clock_offset(self, quote: QuoteTick | None, ts_init: int) -> None:
        """Publish the host-vs-venue clock offset every N timestamped frames.

        Derived from frames already on the socket -- ``ts_init`` (host receipt)
        minus ``ts_event`` (the venue's ``transactTime``) -- so it costs no
        extra request and does not widen this client's read-only surface. The
        read-only auth smoke measured a ~131 second host offset; without a
        recorded series, a crossing-time join against host-stamped weather data
        cannot be reconciled after the fact.
        """
        if quote is None or quote.ts_event <= 0:
            return
        self._clock_offset_samples += 1
        if self._clock_offset_samples % CLOCK_OFFSET_SAMPLE_EVERY != 0:
            return
        self._publish_custom(
            VenueClockOffset(
                source=CLOCK_OFFSET_SOURCE,
                offset_ns=ts_init - quote.ts_event,
                samples=self._clock_offset_samples,
                ts_event=quote.ts_event,
                ts_init=ts_init,
            )
        )

    def _publish_custom(self, record: Data) -> None:
        """Publish a custom record through the engine.

        ``DataEngine._handle_data`` dispatches custom types only on
        ``isinstance(data, CustomData)`` (``data/engine.pyx:2570``); a bare
        payload falls through to the error branch and is never delivered. The
        engine then republishes the UNWRAPPED object
        (``engine.pyx:2848``), which is what the streaming writer records.
        """
        self._handle_data(CustomData(DataType(type(record)), record))

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
        if not should_warn_at_count(count):
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
        """Sample the feed's health on a fixed cadence until it is beyond saving.

        The loop is deliberately empty of policy: every decision lives in
        :meth:`sample_feed_health`, which is synchronous and therefore
        directly testable. A watchdog whose logic can only be exercised by
        racing an event loop is a watchdog nobody verifies.
        """
        while True:
            await asyncio.sleep(self._feed_watch_interval_secs)
            if not self.sample_feed_health():
                return

    def sample_feed_health(self) -> bool:
        """Record one observation of the feed. Returns False to stop watching.

        Two jobs, both of which must happen on every sample:

        **Tape-gap accounting.** The socket reconnects and replays
        subscriptions by itself, so quotes resume and the parquet tape carries
        no marker of the interruption. Counting the transitions here is the
        only record that the archive has a hole in it. See :attr:`tape_gaps`
        for why the count is explicitly a lower bound.

        **Report the unconfirmed subscriptions.** A slug the venue accepted
        and never delivered is real, unbackfillable loss for that slug, and it
        is reported at ERROR, once each. It is NOT a stop condition -- the
        socket is alive and the rest of the ladder is still recording.

        **Fail closed on the FATAL class only.** When the socket reports
        ``is_fatally_degraded`` its supervisor has stopped retrying, or died:
        no further quotes of any kind are coming and nothing in the process
        recovers. The client marks itself disconnected rather than presenting
        a frozen book as live, and asks the node to stop.

        Polling ``is_degraded`` here instead would conflate the two: that flag
        is the UNION and is also raised by a single silent subscription, so at
        05:00Z the first of ~60 thin overnight weather markets to go quiet for
        60s would have ended the whole eight-hour capture in its first minute.
        """
        connected = self._feed.is_connected
        previous = self._feed_was_connected
        self._feed_was_connected = connected
        now_ns = self._clock.timestamp_ns()

        if previous is not False and not connected:
            # Falling edge -- including the first sample if it finds the feed
            # already down, because that is still an interval with no quotes.
            self._open_tape_gap(now_ns)
        elif previous is False and connected:
            self._close_tape_gap(now_ns)

        self._report_new_silent_subscriptions()

        if not self._feed.is_fatally_degraded:
            return True

        self._safe_mode = True
        self._set_connected(False)
        reason = (
            "Polymarket.us markets feed lost and not recoverable; "
            f"{self._tape_gaps} tape gap(s) observed, "
            f"{self._tape_gap_seconds_total:.1f}s of quotes lost so far -- "
            "this final gap remains OPEN and its quotes are unrecoverable"
        )
        return self._request_fatal_shutdown(reason)

    def _report_new_silent_subscriptions(self) -> None:
        """Log every newly unconfirmed slug once, at ERROR, and keep recording.

        The escalation decision lives here rather than in the transport that
        detects it: the socket knows one slug is quiet, only the client knows
        that ending the run over it would discard everything the other slugs
        are still delivering.
        """
        for warning in self._feed.silent_subscriptions:
            if warning.slug in self._silent_subscription_slugs:
                continue
            self._silent_subscription_slugs.add(warning.slug)
            self._log.error(
                f"Polymarket.us subscription {warning.slug!r} produced NO inbound frame "
                f"within {warning.subscribed_after_secs:.1f}s of being subscribed: treat "
                "it as UNCONFIRMED, never as a quiet market. Its quotes are being lost "
                "and this venue's weather markets cannot be backfilled. "
                f"{len(self._silent_subscription_slugs)} of "
                f"{len(self._feed.subscriptions)} subscription(s) are now unconfirmed. "
                "NOT fatal: the socket is alive and the rest keep recording.",
                LogColor.RED,
            )

    def _request_fatal_shutdown(self, reason: str) -> bool:
        """Ask the node to stop, cleanly. True while it is worth asking again.

        Before this, losing the feed ended the socket's supervisor coroutine
        and nothing else: the node kept running, subscribed to nothing,
        writing an empty tape, while systemd reported ``active (running)``.
        Attended runs had a human to notice. The unattended run does not.

        **The shutdown is NATIVE.** ``Component.shutdown_system``
        (``common/component.pyx:2162-2182``) publishes ``ShutdownSystem``,
        which ``NautilusKernel._on_shutdown_system``
        (``system/kernel.py:613-638``) turns into a clean ``stop_async()``.
        Nothing here reimplements a shutdown.

        **It must NOT be a hard exit.** A clean stop is what runs
        ``StreamingFeatherWriter.close()`` (``persistence/writer.py:596-611``)
        and appends the Arrow end-of-stream marker. Killing the process
        instead can leave a truncated trailing message, which
        ``ParquetDataCatalog._read_feather_file``
        (``persistence/catalog/parquet.py:2795-2800``) swallows -- converting
        the ENTIRE day's tape to zero rows in silence. Measured in
        ``tests/contract/test_quote_tape_unclean_shutdown.py``. Exiting hard
        to report a lost feed would destroy the tape recorded before it.

        **Only the exit STATUS is authored.** ``TradingNode.run()`` returns
        ``None`` and the kernel keeps no shutdown reason, so a fatal fault and
        an operator SIGTERM are indistinguishable to the caller. The latch in
        :mod:`breezy.adapters.polymarket_us.feed_fault` carries that one bit
        out to the CLI, which turns it into a non-zero exit code.

        **The request is NOT one-shot, because delivery is not confirmable.**
        ``shutdown_system`` publishes and returns; ``_on_shutdown_system``
        drops the command outright when the kernel is not running or is
        already stopping, and the publisher is told nothing either way. So the
        return value keeps the CALLER (``_watch_feed``, the only thing left
        that could ask again) alive across that window, and the request is
        re-issued up to :data:`FATAL_SHUTDOWN_REQUEST_BUDGET` times. When the
        command IS honoured, the kernel stops this client, ``_disconnect``
        cancels the watchdog, and the loop ends without ever spending the rest
        of the budget -- that cancellation is the only confirmation available.
        """
        record_fatal_feed_fault(str(self.id), reason)

        if self._fatal_shutdown_requests >= FATAL_SHUTDOWN_REQUEST_BUDGET:
            return False

        if self._fatal_shutdown_requests == 0:
            self._log.error(
                f"{reason}. Entering safe mode (client marked disconnected, no "
                "further quotes) and shutting the node down.",
            )
        else:
            self._log.error(
                "The node is STILL RUNNING after a fatal feed shutdown was "
                f"requested (attempt {self._fatal_shutdown_requests + 1} of "
                f"{FATAL_SHUTDOWN_REQUEST_BUDGET}); re-issuing the native "
                "ShutdownSystem command.",
            )
        if not self._msgbus.has_subscribers(SHUTDOWN_COMMAND_TOPIC):
            self._log.error(
                f"NOTHING is subscribed to {SHUTDOWN_COMMAND_TOPIC!r}: this "
                "shutdown request cannot be acted on by any kernel. The fatal "
                "fault is latched, so the exit status will still report it if "
                "this process is stopped by other means.",
            )

        self._fatal_shutdown_requests += 1
        self.shutdown_system(reason)

        if self._fatal_shutdown_requests >= FATAL_SHUTDOWN_REQUEST_BUDGET:
            self._log.error(
                f"That was the LAST of {FATAL_SHUTDOWN_REQUEST_BUDGET} shutdown "
                "requests this watchdog will make for a dead feed; it now stops "
                "sampling. If the node is still running after this, nothing "
                "further will ask it to stop -- but the fault stays latched, so "
                "the exit status reports it whenever this process does stop. A "
                "hard exit is deliberately NOT attempted: it would truncate the "
                "day's Arrow stream and silently discard the whole tape.",
            )
            return False
        return True

    def _open_tape_gap(self, now_ns: int) -> None:
        if self._gap_opened_ns is not None:
            return
        self._gap_opened_ns = now_ns
        self._tape_gaps += 1
        self._log.error(
            f"Quote tape gap #{self._tape_gaps} OPENED: the markets feed is down. "
            "Quotes occurring from now until it returns are permanently lost -- "
            "this venue's weather markets cannot be backfilled.",
        )
        self._publish_gap_records(started_ns=now_ns, ended_ns=0, resolved=False, ts_init=now_ns)

    def _close_tape_gap(self, now_ns: int) -> None:
        opened_ns = self._gap_opened_ns
        self._gap_opened_ns = None
        if opened_ns is None:
            return
        seconds = max(0.0, (now_ns - opened_ns) / 1_000_000_000)
        self._tape_gap_seconds_total += seconds
        self._log.info(
            f"Quote tape gap #{self._tape_gaps} CLOSED after ~{seconds:.1f}s "
            f"(observed total {self._tape_gap_seconds_total:.1f}s across "
            f"{self._tape_gaps} gap(s)). The tape resumes here; it is NOT "
            "continuous across this point.",
        )
        self._publish_gap_records(
            started_ns=opened_ns, ended_ns=now_ns, resolved=True, ts_init=now_ns
        )

    def _publish_gap_records(
        self, *, started_ns: int, ended_ns: int, resolved: bool, ts_init: int
    ) -> None:
        """Write the outage to the TAPE, not only to the log.

        A log line is invisible to a study reading parquet. One record per
        subscribed instrument, because a socket outage affects every market on
        that socket and a per-instrument key is what lets a join exclude or
        flag the contaminated interval.

        Emitted on BOTH edges: the ``resolved=False`` record on open means an
        outage in progress when the process dies is still on disk, which is the
        gap most likely to be missed and the one that contaminates everything
        after it.
        """
        for instrument_id in self._subscribed_instrument_ids():
            self._publish_custom(
                QuoteTapeGap(
                    instrument_id=instrument_id,
                    gap_seq=self._tape_gaps,
                    started_ns=started_ns,
                    ended_ns=ended_ns,
                    resolved=resolved,
                    recorder_instance_id=self._recorder_instance_id,
                    ts_event=started_ns,
                    ts_init=ts_init,
                )
            )

    def _subscribed_instrument_ids(self) -> list[InstrumentId]:
        """Instruments this client is recording, resolved from latest discovery."""
        resolved: list[InstrumentId] = []
        for slug in self._provider_active_slugs():
            try:
                resolved.append(slug_to_instrument_id(slug))
            except PolymarketUSError:  # pragma: no cover - config is validated upstream
                continue
        return resolved


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
    quote_parser: QuoteTickParser = parse_quote_tick,
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
