"""EXEC-PAR WP5b: the breaker watcher, a native Nautilus ``Actor`` on a timer.

NULL HYPOTHESIS, checked: Nautilus already provides everything but the policy.
A plain ``Actor`` with ``Clock.set_timer`` is the exact shape
``strategy.current_rung_hold.fee_drift_probe.FeeDriftProbeActor`` uses. The
timer callback runs on a foreign clock thread, so (the same L-16 bridge) it
only schedules the evaluation coroutine onto the node's event loop with
``asyncio.run_coroutine_threadsafe``; every read of the exec client and every
write through the latch therefore happens on the loop that owns them.

Two classes, split by the K the node runs at:

* :class:`ExecRefusalAlertActor` is registered at EVERY K. It only reads the
  exec client's counters and alerts (a stuck refusal after a ledger settle
  failure, a no-fill retire refusal, a forced-to-1 K). It writes nothing to the
  store, so at K=1 the store write sequence is exactly today's. A stuck refusal
  halts entries at K=1 too, which is why its alerts are not K>1-only.
* :class:`BreakerWatcherActor` extends it and is registered ONLY when K>1. Every
  5 s it evaluates the breaker triggers, latches the entry halt through the
  latch's breaker-record methods, and writes the heartbeat (plus the resolver's
  last pass time) only AFTER the whole evaluation completed without raising.
  A watcher that dies, wedges or raises therefore lets the heartbeat go stale,
  which the latch's admission gate treats as a denial of new entries.

Triggers (r5 3.6): at least two STUCK slots (older than the no-id resolver floor
plus 600 s), the ledger's ``breaker_fraction_exceeded`` (via the client
property, so this module reads no operator control), any increase of the
client's monotonic ``contradiction_events_total`` (r5.1 E14.5), or a
duplicate-suspect trip. The halt is entries-only and sticky: no family-halt key
and no veto are used, exits stay allowed, and only the operator reset CLI (node
down) clears it. Alerts carry the held-position list. Alert details are
value-free: slugs, labels and counts only.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import threading
from collections.abc import Callable, Coroutine
from datetime import timedelta
from decimal import Decimal
from typing import Final, Protocol

from nautilus_trader.common.actor import Actor
from nautilus_trader.model.events import OrderDenied, OrderSubmitted
from nautilus_trader.model.identifiers import ClientId

from breezy.adapters.polymarket_us.symbology import base_slug_of
from breezy.runtime.exec_par_telemetry import ExecParDigest
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert
from breezy.runtime.submit_intent_slots import BREAKER_HEARTBEAT_MAX_AGE_NS

__all__ = [
    "DIGEST_EVERY_TICKS",
    "STUCK_AGE_NS",
    "STUCK_TRIP_COUNT",
    "WATCHER_INTERVAL_SECONDS",
    "BreakerLatchPort",
    "BreakerWatcherActor",
    "ExecClientView",
    "ExecRefusalAlertActor",
    "build_exec_watcher",
    "cross_day_settles_of",
    "exec_client_getter",
]

logger = logging.getLogger(__name__)

#: Latch latency is at most one poll: the resolver polls at 5 s as well.
WATCHER_INTERVAL_SECONDS: Final[int] = 5

#: A slot is STUCK past the no-id resolver floor (300 s) plus 600 s. The client
#: exposes ages but not the with-id / no-id shape (with-id would be 720 s), so
#: the larger bound is used for both: a late trip, never a false one.
STUCK_AGE_NS: Final[int] = 900 * 1_000_000_000
STUCK_TRIP_COUNT: Final[int] = 2

#: One digest line per minute at the 5 s tick.
DIGEST_EVERY_TICKS: Final[int] = 12

_SITE: Final[str] = "exec_par_watcher"
_ORDER_EVENT_TOPIC: Final[str] = "events.order.*"
_REASON_LABEL_MAX: Final[int] = 48
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"[0-9$.]+")

EVENT_BREAKER_TRIPPED: Final[str] = "EXEC_PAR_BREAKER_TRIPPED"
EVENT_UNREADABLE_SLOT: Final[str] = "EXEC_PAR_UNREADABLE_SLOT"
EVENT_STUCK_ON_HELD: Final[str] = "EXEC_PAR_STUCK_SLOT_ON_HELD_SLUG"
EVENT_K_FORCED: Final[str] = "EXEC_PAR_K_FORCED_TO_1"
EVENT_STUCK_REFUSAL: Final[str] = "EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE"
EVENT_NO_FILL_REFUSAL: Final[str] = "EXEC_PAR_NO_FILL_RETIRE_REFUSAL"


class ExecClientView(Protocol):
    """The exec client's watcher-facing, read-only surface (all properties)."""

    @property
    def contradiction_events_total(self) -> int: ...
    @property
    def duplicate_suspect_total(self) -> int: ...
    @property
    def ambiguous_notional_breaker_tripped(self) -> bool: ...
    @property
    def resolver_last_pass_ns(self) -> int: ...
    @property
    def open_intent_ages(self) -> tuple[tuple[str, str, int], ...]: ...
    @property
    def held_position_slugs(self) -> tuple[str, ...]: ...
    @property
    def unreadable_slot_keys(self) -> tuple[str, ...]: ...
    @property
    def k_forced_to_1_reason(self) -> str | None: ...
    @property
    def stuck_refusals_after_settle_failure_total(self) -> int: ...


class BreakerLatchPort(Protocol):
    """The two single-writer breaker-record methods of ``SubmitIntentLatch``."""

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None: ...
    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None: ...


def _count(client: object, name: str) -> int:
    """A non-negative int counter, ``0`` when the client predates it."""
    value: object = getattr(client, name, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _reason_label(reason: str) -> str:
    """A bounded, number-free denial label (never a dollar value)."""
    return _NUMBER_RE.sub("#", reason.strip().lower())[:_REASON_LABEL_MAX] or "unspecified"


class ExecRefusalAlertActor(Actor):
    """Counter / K-forced alerts and digest telemetry; writes nothing to the store."""

    def __init__(
        self,
        *,
        alert_sink: AlertSink,
        digest: ExecParDigest | None = None,
        interval_seconds: int = WATCHER_INTERVAL_SECONDS,
    ) -> None:
        super().__init__()
        if interval_seconds <= 0:
            raise ValueError("`interval_seconds` must be positive")
        self._alert_sink = alert_sink
        self._digest = digest
        self._interval_seconds = interval_seconds
        self._client_getter: Callable[[], ExecClientView | None] = lambda: None
        self._cross_day_getter: Callable[[], int] = lambda: 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._timer_armed = False
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._ticks = 0
        self._counter_alerted: dict[str, int] = {}
        self._k_forced_alerted: str | None = None

    # -- wiring -----------------------------------------------------------

    def bind_client(
        self,
        getter: Callable[[], ExecClientView | None],
        *,
        cross_day_settles_total: Callable[[], int] | None = None,
    ) -> None:
        """Late-bind the exec client (it exists only after ``node.build()``)."""
        self._client_getter = getter
        if cross_day_settles_total is not None:
            self._cross_day_getter = cross_day_settles_total

    # -- observability ----------------------------------------------------

    @property
    def interval_seconds(self) -> int:
        return self._interval_seconds

    @property
    def inflight(self) -> int:
        with self._inflight_lock:
            return self._inflight

    @property
    def timer_armed(self) -> bool:
        return self._timer_armed

    # -- lifecycle ----------------------------------------------------------

    def on_start(self) -> None:
        """Capture the loop, evaluate once, arm the 5 s timer (no loop: inert)."""
        self._subscribe_order_events()
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
            logger.info("no running event loop for %s: no polling armed", _SITE)
            return
        self._submit(self.tick())
        self._arm_timer()

    def on_stop(self) -> None:
        if self._digest is not None:
            try:
                self.msgbus.unsubscribe(topic=_ORDER_EVENT_TOPIC, handler=self._on_order_event)
            except (KeyError, ValueError):  # pragma: no cover - defensive
                logger.debug("order-event handler was already unsubscribed")
        if not self._timer_armed:
            return
        try:
            self.clock.cancel_timer(self._timer_name)
        except (KeyError, ValueError):  # pragma: no cover - defensive
            logger.debug("timer %s was already cancelled", self._timer_name)
        self._timer_armed = False

    @property
    def _timer_name(self) -> str:
        return f"{_SITE}-{type(self).__name__}-timer"

    def _arm_timer(self) -> None:
        if self._timer_armed:
            return
        self.clock.set_timer(
            name=self._timer_name,
            interval=timedelta(seconds=self._interval_seconds),
            callback=self._on_timer,
        )
        self._timer_armed = True

    def _on_timer(self, event: object) -> None:
        """Timer callback (clock thread): schedule and return. Never raises."""
        self._submit(self.tick())

    def _submit(self, coro: Coroutine[object, object, bool]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        with self._inflight_lock:
            self._inflight += 1
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:  # pragma: no cover - shutdown race
            coro.close()
            self._settle()
            return
        future.add_done_callback(self._on_tick_done)

    def _settle(self) -> None:
        with self._inflight_lock:
            self._inflight -= 1

    def _on_tick_done(self, future: concurrent.futures.Future[bool]) -> None:
        self._settle()
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:  # pragma: no cover - tick() contains its own faults
            logger.error("%s tick died unexpectedly: %s", _SITE, type(exc).__name__)

    # -- order events (digest only) -------------------------------------------

    def _subscribe_order_events(self) -> None:
        if self._digest is None:
            return
        try:
            self.msgbus.subscribe(topic=_ORDER_EVENT_TOPIC, handler=self._on_order_event)
        except Exception as exc:  # noqa: BLE001 - telemetry must never block boot
            logger.warning(
                "%s: digest order-event subscription failed: %s", _SITE, type(exc).__name__
            )

    def _on_order_event(self, event: object) -> None:
        digest = self._digest
        if digest is None:
            return
        try:
            if isinstance(event, OrderDenied):
                digest.record_denial(_reason_label(str(event.reason)))
            elif isinstance(event, OrderSubmitted):
                self._record_submitted(digest, event)
        except Exception as exc:  # noqa: BLE001 - a telemetry fault is never a trading fault
            logger.debug("%s: digest event skipped: %s", _SITE, type(exc).__name__)

    def _record_submitted(self, digest: ExecParDigest, event: OrderSubmitted) -> None:
        order = self.cache.order(event.client_order_id)
        if order is None or not order.has_price:
            return
        notional = order.price.as_decimal() * order.quantity.as_decimal()
        try:
            slug = base_slug_of(order.instrument_id)
        except Exception:  # noqa: BLE001 - an unmappable id still counts, under its raw name
            slug = str(order.instrument_id)
        digest.record_submitted(slug, Decimal(notional), self.clock.timestamp_ns())

    # -- the tick -----------------------------------------------------------

    async def tick(self) -> bool:
        """Evaluate once. ``True`` iff the whole evaluation completed. Never raises."""
        client = self._client_getter()
        if client is None:
            return False
        now_ns = self.clock.timestamp_ns()
        try:
            self._evaluate(client, now_ns)
            self._complete(client, now_ns)
        except Exception as exc:  # noqa: BLE001 - contained; the missing heartbeat is the signal
            logger.error("%s evaluation failed (heartbeat withheld): %s", _SITE, type(exc).__name__)
            return False
        self._emit_digest(now_ns)
        return True

    def _evaluate(self, client: ExecClientView, now_ns: int) -> None:
        self._alert_k_forced(client)
        self._alert_counter(
            EVENT_STUCK_REFUSAL,
            _count(client, "stuck_refusals_after_settle_failure_total"),
            "stuck_refusals_after_settle_failure_total",
        )
        self._alert_counter(
            EVENT_NO_FILL_REFUSAL,
            _count(client, "no_fill_retire_refusals_total"),
            "no_fill_retire_refusals_total",
        )

    def _complete(self, client: ExecClientView, now_ns: int) -> None:
        """Runs only after a fully evaluated tick (the base writes nothing)."""

    def _alert(self, severity: str, event: str, detail: str) -> None:
        emit_alert(
            self._alert_sink,
            AlertPayload(severity=severity, event=event, site=_SITE, detail=detail),
        )

    def _alert_k_forced(self, client: ExecClientView) -> None:
        reason = client.k_forced_to_1_reason
        if reason is None or reason == self._k_forced_alerted:
            return
        self._k_forced_alerted = reason
        self._alert("CRITICAL", EVENT_K_FORCED, f"k_forced_to_1 reason={reason}")

    def _alert_counter(self, event: str, value: int, label: str) -> None:
        """Alert when ``value`` > 0 and differs from the last alerted value."""
        if value <= 0 or self._counter_alerted.get(event) == value:
            return
        self._counter_alerted[event] = value
        self._alert("CRITICAL", event, f"{label}={value}")

    def _emit_digest(self, now_ns: int) -> None:
        digest = self._digest
        if digest is None:
            return
        self._ticks += 1
        if self._ticks % DIGEST_EVERY_TICKS != 0:
            return
        try:
            digest.set_cross_day_settles_total(self._cross_day_getter())
            logger.info(digest.snapshot(now_ns).render())
        except Exception as exc:  # noqa: BLE001 - telemetry only
            logger.debug("%s: digest skipped: %s", _SITE, type(exc).__name__)


class BreakerWatcherActor(ExecRefusalAlertActor):
    """The K>1 breaker: evaluate every trigger, latch the halt, then heartbeat."""

    def __init__(
        self,
        *,
        latch: BreakerLatchPort,
        alert_sink: AlertSink,
        digest: ExecParDigest | None = None,
        interval_seconds: int = WATCHER_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(alert_sink=alert_sink, digest=digest, interval_seconds=interval_seconds)
        self._latch = latch
        self._halt_written = False
        self._seen_contradictions = 0
        self._seen_duplicates = 0
        self._unreadable_alerted: set[str] = set()
        self._held_stuck_alerted: set[str] = set()
        self._trip_alerted: set[str] = set()
        self._last_hb_ns: int | None = None
        self._denied_at_last_hb = 0

    def _evaluate(self, client: ExecClientView, now_ns: int) -> None:
        super()._evaluate(client, now_ns)
        ages = client.open_intent_ages
        stuck = tuple((iid, slug) for iid, slug, age in ages if age > STUCK_AGE_NS)
        contradictions = client.contradiction_events_total
        duplicates = client.duplicate_suspect_total
        reasons: list[str] = []
        if len(stuck) >= STUCK_TRIP_COUNT:
            reasons.append("stuck_slots")
        if client.ambiguous_notional_breaker_tripped:
            reasons.append("ambiguous_notional")
        if contradictions > self._seen_contradictions:
            reasons.append("contradiction")
        if duplicates > self._seen_duplicates:
            reasons.append("duplicate_suspect")
        held = client.held_position_slugs
        self._alert_unreadable(client.unreadable_slot_keys)
        self._alert_stuck_on_held(stuck, held)
        if reasons:
            self._trip(",".join(reasons), held, now_ns)
        self._seen_contradictions = max(self._seen_contradictions, contradictions)
        self._seen_duplicates = max(self._seen_duplicates, duplicates)

    def _trip(self, reason: str, held: tuple[str, ...], now_ns: int) -> None:
        if not self._halt_written:
            # A raise here leaves the seen-counters behind, so the next tick
            # sees the same event again and retries the write.
            self._latch.write_breaker_halt(reason, ts_ns=now_ns)
            self._halt_written = True
        if reason in self._trip_alerted:
            return
        self._trip_alerted.add(reason)
        listing = ",".join(held) if held else "none"
        self._alert(
            "CRITICAL",
            EVENT_BREAKER_TRIPPED,
            f"entry halt latched reason={reason} held_positions={listing}",
        )

    def _alert_unreadable(self, keys: tuple[str, ...]) -> None:
        fresh = [key for key in keys if key not in self._unreadable_alerted]
        if not fresh:
            return
        self._unreadable_alerted.update(fresh)
        self._alert(
            "CRITICAL", EVENT_UNREADABLE_SLOT, f"unreadable slots={','.join(sorted(fresh))}"
        )

    def _alert_stuck_on_held(
        self, stuck: tuple[tuple[str, str], ...], held: tuple[str, ...]
    ) -> None:
        for intent_id, slug in stuck:
            if slug and slug in held and intent_id not in self._held_stuck_alerted:
                self._held_stuck_alerted.add(intent_id)
                self._alert(
                    "CRITICAL",
                    EVENT_STUCK_ON_HELD,
                    f"stuck entry blocks the exit of a held position slug={slug}",
                )

    def _complete(self, client: ExecClientView, now_ns: int) -> None:
        """The heartbeat: written only after the whole evaluation succeeded."""
        self._note_heartbeat_gap(now_ns)
        self._latch.write_breaker_heartbeat(
            hb_ns=now_ns, resolver_pass_ns=client.resolver_last_pass_ns
        )
        self._last_hb_ns = now_ns
        if self._digest is not None:
            self._denied_at_last_hb = self._digest.denied_total()

    def _note_heartbeat_gap(self, now_ns: int) -> None:
        """Entries denied while the heartbeat was stale: counted from this tick gap."""
        digest = self._digest
        if digest is None or self._last_hb_ns is None:
            return
        if now_ns - self._last_hb_ns > BREAKER_HEARTBEAT_MAX_AGE_NS:
            digest.record_heartbeat_stale_denials(digest.denied_total() - self._denied_at_last_hb)


def build_exec_watcher(
    max_slots: int,
    *,
    latch: BreakerLatchPort,
    alert_sink: AlertSink,
    digest: ExecParDigest | None = None,
) -> ExecRefusalAlertActor:
    """The watcher for an effective K: the breaker only when K>1, else alerts only."""
    if max_slots > 1:
        return BreakerWatcherActor(latch=latch, alert_sink=alert_sink, digest=digest)
    return ExecRefusalAlertActor(alert_sink=alert_sink, digest=digest)


def exec_client_getter(node: object, client_name: str) -> Callable[[], ExecClientView | None]:
    """A lazy reader of the node's registered exec client (``None`` until it exists).

    Reaches into ``ExecutionEngine._clients`` (``cdef readonly``; the engine has
    no public accessor), the same idiom as ``trade_cli._exec_client_refusal_reader``,
    with ``getattr`` at every hop so a Nautilus rename degrades to ``None``.
    """

    def _get() -> ExecClientView | None:
        kernel = getattr(node, "kernel", None)
        exec_engine = getattr(kernel, "exec_engine", None)
        clients = getattr(exec_engine, "_clients", None)
        if clients is None:
            return None
        client: ExecClientView | None = clients.get(ClientId(client_name))
        return client

    return _get


def cross_day_settles_of(client_getter: Callable[[], ExecClientView | None]) -> Callable[[], int]:
    """The ledger's ``cross_day_settles_total`` through the client's ledger handle.

    The client exposes no such property and is byte-pinned, so the digest reads
    its ``_ledger`` with ``getattr`` and a ``0`` fallback; telemetry only.
    """

    def _read() -> int:
        ledger = getattr(client_getter(), "_ledger", None)
        value: object = getattr(ledger, "cross_day_settles_total", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    return _read
