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
import threading
from collections.abc import Callable, Coroutine
from datetime import timedelta
from decimal import Decimal
from typing import Final, Protocol

from nautilus_trader.common.actor import Actor
from nautilus_trader.model.events import OrderDenied, OrderSubmitted
from nautilus_trader.model.identifiers import ClientId

from breezy.adapters.polymarket_us.symbology import base_slug_of
from breezy.runtime.exec_par_counter_ingest import (
    AmbiguousMarkSource,
    ExecParCounterError,
    ExecParCounterIngest,
    IntentView,
    reason_label,
)
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    Amendment,
    CleanupDemotion,
    DenialRow,
    EpochRow,
    ExcludedDay,
    FillRow,
    ForceK1Cleared,
    ForceK1Flag,
    SettledPnlDay,
    GappyMark,
    OpenCostFlag,
    OrderAnchor,
    StageEvalDry,
    StageReset,
    StopVerdict,
    WindowPeak,
)
from breezy.runtime.exec_par_telemetry import ExecParDigest
from breezy.runtime.health import AlertPayload, AlertSink
from breezy.runtime.submit_intent_slots import BREAKER_HEARTBEAT_MAX_AGE_NS

__all__ = [
    "COUNTER_RESEND_MIN_NS",
    "DIGEST_EVERY_TICKS",
    "NO_CLIENT_ERROR_TICKS",
    "REALERT_INTERVAL_NS",
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

#: A condition that keeps holding is re-alerted this often (fire-and-forget
#: sinks can lose a send; this bounds the silence).
REALERT_INTERVAL_NS: Final[int] = 3600 * 1_000_000_000

#: A monotonic counter that keeps rising re-alerts at most this often (the first
#: >0 value always sends at once); the hourly re-alert above is unconditional.
COUNTER_RESEND_MIN_NS: Final[int] = 300 * 1_000_000_000

#: Consecutive ticks with no registered exec client before it is an ERROR.
NO_CLIENT_ERROR_TICKS: Final[int] = 5

_SITE: Final[str] = "exec_par_watcher"
_ORDER_EVENT_TOPIC: Final[str] = "events.order.*"

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
    @property
    def no_fill_retire_refusals_total(self) -> int: ...


class BreakerLatchPort(Protocol):
    """The two single-writer breaker-record methods of ``SubmitIntentLatch``."""

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None: ...
    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None: ...


class ExecParStorePort(Protocol):
    """BG-1a store writer: the durable D-PREREG records (spec 10a, K9, M3, N4).

    Implemented by single-writer ``SubmitIntentLatch`` methods that each run
    under ``_require_held()`` and never nest the latch ``_mutex``. Readers on
    the latch (``read_*``) are not part of this write port. A write failure
    propagates (the caller maps it to ``telemetry_write_fail`` or, for the
    marker, ``stop_marker_write_fail``).
    """

    def write_stage_reset(self, record: StageReset) -> None: ...
    def add_excluded_day(self, record: ExcludedDay) -> bool: ...
    def write_epoch_row(self, record: EpochRow) -> None: ...
    def write_epoch_stop_ts(self, boot_ts: int, stop_ts: int) -> bool: ...
    def write_amendment(self, record: Amendment) -> None: ...
    def write_stage_eval_dry(self, record: StageEvalDry) -> None: ...
    def write_force_k1_cleared(self, record: ForceK1Cleared) -> None: ...
    def write_stop_verdict(self, record: StopVerdict) -> None: ...
    def write_cleanup_demotion(self, record: CleanupDemotion) -> None: ...
    def write_force_k1_flag(self, record: ForceK1Flag) -> None: ...
    def clear_force_k1_flag(self, cleared_ts_ns: int) -> None: ...
    def write_settled_pnl_day(self, record: SettledPnlDay) -> None: ...
    def mark_flag_write_failed(self) -> None: ...
    def clear_flag_write_failed(self) -> None: ...

    # BG-1b per-climate-day counter rows (event-sourced, exclusive, idempotent).
    def write_order_anchor(self, record: OrderAnchor) -> bool: ...
    def read_order_anchor(self, client_order_id: str) -> OrderAnchor | None: ...
    def read_intent(self, intent_id: str) -> IntentView | None: ...
    def write_denial(self, record: DenialRow) -> bool: ...
    def write_ambiguous(self, record: AmbiguousRow) -> bool: ...
    def write_fill(self, record: FillRow) -> bool: ...
    def write_open_cost_flag(self, record: OpenCostFlag) -> OpenCostFlag: ...
    def add_window_order(self, day: str, window_start_ns: int, notional: Decimal) -> WindowPeak: ...
    def write_gappy_mark(self, record: GappyMark) -> bool: ...


class LedgerPredicatePort(Protocol):
    """Value-free ledger predicates (K6): aggregates in, ``bool`` only out.

    The caller (loop thread) passes already-aggregated Decimals; the port
    compares them against budget fractions and returns a bool. Currency
    values never leave the port's caller and are never logged. A raise or a
    non-bool return counts as tripped. ``DailySpendLedger`` implements this
    structurally (BG-1e). The 5 s window share and the 2-of-5 day counts are
    pure ratios / counts that need no budget, so the caller compares them
    itself and they are deliberately not on this port.
    """

    def pnl_breaches_budget_fraction(
        self, *, aggregate_pnl: Decimal, fraction: Decimal
    ) -> bool: ...
    def open_cost_exceeds_budget_fraction(
        self, *, aggregate_open_cost: Decimal, fraction: Decimal
    ) -> bool: ...


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
        #: condition key -> (value alerted, when). Set only after the send
        #: succeeded; pruned when the condition ends.
        self._alerted: dict[str, tuple[object, int]] = {}
        self._conditions: dict[str, tuple[object, str, str, str, bool]] = {}
        self._no_client_streak = 0
        self._no_client_logged_ns: int | None = None

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
        if self._wants_order_events():
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

    def _wants_order_events(self) -> bool:
        return self._digest is not None

    def _subscribe_order_events(self) -> None:
        if not self._wants_order_events():
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
                digest.record_denial(reason_label(str(event.reason)))
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
        """Evaluate once. ``True`` iff the whole evaluation completed. Never raises.

        Order: read facts, PERSIST (the breaker halt) first, then alert (every
        alert contained on its own), then the heartbeat. A fault before the
        persist withholds the heartbeat; a fault in an alert never does.
        """
        try:
            client = self._client_getter()
            now_ns = self.clock.timestamp_ns()
            if client is None:
                self._note_no_client(now_ns)
                return False
            self._no_client_streak = 0
            self._no_client_logged_ns = None
            self._conditions = {}
            self._persist(client, now_ns)
            self._collect_conditions(client, now_ns)
            self._deliver_conditions(now_ns)
            self._complete(client, now_ns)
        except Exception as exc:  # noqa: BLE001 - contained; the missing heartbeat is the signal
            logger.error("%s evaluation failed (heartbeat withheld): %s", _SITE, type(exc).__name__)
            return False
        self._emit_digest(now_ns)
        return True

    def _note_no_client(self, now_ns: int) -> None:
        self._no_client_streak += 1
        if self._no_client_streak < NO_CLIENT_ERROR_TICKS:
            return
        last = self._no_client_logged_ns
        if last is None or now_ns - last >= REALERT_INTERVAL_NS:
            self._no_client_logged_ns = now_ns
            logger.error(
                "%s: no registered exec client for %d consecutive ticks; nothing is being watched",
                _SITE,
                self._no_client_streak,
            )

    def _persist(self, client: ExecClientView, now_ns: int) -> None:
        """State the node must keep even if every alert is lost (the base keeps none)."""

    def _collect_conditions(self, client: ExecClientView, now_ns: int) -> None:
        reason = client.k_forced_to_1_reason
        if reason is not None:
            self._condition("k_forced", reason, EVENT_K_FORCED, f"k_forced_to_1 reason={reason}")
        counters = (
            (
                EVENT_STUCK_REFUSAL,
                "stuck_refusals_after_settle_failure_total",
                client.stuck_refusals_after_settle_failure_total,
            ),
            (
                EVENT_NO_FILL_REFUSAL,
                "no_fill_retire_refusals_total",
                client.no_fill_retire_refusals_total,
            ),
        )
        for event, label, value in counters:
            if value > 0:
                self._condition(event, value, event, f"{label}={value}", rate_limited=True)

    def _condition(
        self, key: str, value: object, event: str, detail: str, *, rate_limited: bool = False
    ) -> None:
        self._conditions[key] = (value, "CRITICAL", event, detail, rate_limited)

    def _deliver_conditions(self, now_ns: int) -> None:
        """Alert each live condition that is new, changed, or due its hourly re-alert.

        A rising counter (``rate_limited``) re-sends on a change only after
        ``COUNTER_RESEND_MIN_NS`` since its last successful send.

        A condition is recorded as alerted ONLY after the sink accepted the send;
        a raising sink is retried on the next tick. A key whose condition ended
        is forgotten, so a later episode alerts afresh.
        """
        for key in [k for k in self._alerted if k not in self._conditions]:
            del self._alerted[key]
        for key, (value, severity, event, detail, rate_limited) in self._conditions.items():
            previous = self._alerted.get(key)
            if previous is not None:
                age = now_ns - previous[1]
                changed = previous[0] != value
                min_gap = COUNTER_RESEND_MIN_NS if rate_limited else 0
                if age < REALERT_INTERVAL_NS and not (changed and age >= min_gap):
                    continue
            if self._send(severity, event, detail):
                self._alerted[key] = (value, now_ns)

    def _send(self, severity: str, event: str, detail: str) -> bool:
        payload = AlertPayload(severity=severity, event=event, site=_SITE, detail=detail)
        try:
            self._alert_sink.emit(payload)
        except Exception as exc:  # noqa: BLE001 - one lost alert must not stop the others
            logger.error("%s: alert %s not sent (%s); will retry", _SITE, event, type(exc).__name__)
            return False
        return True

    def _complete(self, client: ExecClientView, now_ns: int) -> None:
        """Runs only after a fully evaluated tick (the base writes nothing)."""

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
        counters: ExecParCounterIngest | None = None,
        ambiguous_marks: AmbiguousMarkSource | None = None,
    ) -> None:
        super().__init__(alert_sink=alert_sink, digest=digest, interval_seconds=interval_seconds)
        self._latch = latch
        self._counters = counters
        self._ambiguous_marks = ambiguous_marks
        self._ingest_fault_count = 0
        self._last_ingest_fault: ExecParCounterError | None = None
        self._halt_written = False
        self._trip_reason: str | None = None
        self._seen_contradictions = 0
        self._seen_duplicates = 0
        self._stuck: tuple[tuple[str, str], ...] = ()
        self._last_hb_ns: int | None = None
        self._denied_at_last_hb = 0

    # -- BG-1b counter ingestion (loop thread; K > 1 only) -----------------------

    @property
    def ingest_fault_count(self) -> int:
        """Typed counter-ingestion failures seen so far (BG-6 turns these into a halt)."""
        return self._ingest_fault_count

    @property
    def last_ingest_fault(self) -> ExecParCounterError | None:
        return self._last_ingest_fault

    def _wants_order_events(self) -> bool:
        return self._digest is not None or self._counters is not None

    def _on_order_event(self, event: object) -> None:
        super()._on_order_event(event)
        counters = self._counters
        if counters is None:
            return
        try:
            counters.on_event(event, self.cache.order)
        except ExecParCounterError as exc:
            self._ingest_fault_count += 1
            self._last_ingest_fault = exc
            logger.error("%s: counter ingestion failed: %s", _SITE, type(exc).__name__)

    def _ingest_ambiguous_marks(self, now_ns: int) -> None:
        """Count pending ever-AMBIGUOUS marks (a fault is counted, never a withheld heartbeat)."""
        counters, marks = self._counters, self._ambiguous_marks
        if counters is None or marks is None:
            return
        try:
            counters.ingest_ambiguous_marks(marks, now_ns=now_ns)
        except ExecParCounterError as exc:
            self._ingest_fault_count += 1
            self._last_ingest_fault = exc
            logger.error("%s: ambiguous-mark ingestion failed: %s", _SITE, type(exc).__name__)

    def _persist(self, client: ExecClientView, now_ns: int) -> None:
        """Compute the trip reasons and latch the halt BEFORE anything can fail."""
        self._ingest_ambiguous_marks(now_ns)
        ages = client.open_intent_ages
        self._stuck = tuple((iid, slug) for iid, slug, age in ages if age > STUCK_AGE_NS)
        contradictions = client.contradiction_events_total
        duplicates = client.duplicate_suspect_total
        reasons: list[str] = []
        if len(self._stuck) >= STUCK_TRIP_COUNT:
            reasons.append("stuck_slots")
        if client.ambiguous_notional_breaker_tripped:
            reasons.append("ambiguous_notional")
        if contradictions > self._seen_contradictions:
            reasons.append("contradiction")
        if duplicates > self._seen_duplicates:
            reasons.append("duplicate_suspect")
        if reasons and not self._halt_written:
            reason = ",".join(reasons)
            # A raise leaves the seen-counters behind, so the next tick sees the
            # same event again and retries the write.
            self._latch.write_breaker_halt(reason, ts_ns=now_ns)
            self._halt_written = True
            self._trip_reason = reason
        self._seen_contradictions = max(self._seen_contradictions, contradictions)
        self._seen_duplicates = max(self._seen_duplicates, duplicates)

    def _collect_conditions(self, client: ExecClientView, now_ns: int) -> None:
        super()._collect_conditions(client, now_ns)
        held = self._held(client)
        listing = "unknown" if held is None else (",".join(held) or "none")
        if self._trip_reason is not None:
            self._condition(
                "tripped",
                self._trip_reason,
                EVENT_BREAKER_TRIPPED,
                f"entry halt latched reason={self._trip_reason} held_positions={listing}",
            )
        keys = self._unreadable(client)
        if keys:
            self._condition(
                "unreadable",
                keys,
                EVENT_UNREADABLE_SLOT,
                f"unreadable slots={','.join(sorted(keys))}",
            )
        for intent_id, slug in self._stuck:
            if held is not None and slug and slug in held:
                self._condition(
                    f"held_stuck:{intent_id}",
                    slug,
                    EVENT_STUCK_ON_HELD,
                    f"stuck entry blocks the exit of a held position slug={slug}",
                )

    @staticmethod
    def _held(client: ExecClientView) -> tuple[str, ...] | None:
        """The held-position list, or ``None`` (alerted as "unknown") if unreadable."""
        try:
            return client.held_position_slugs
        except Exception as exc:  # noqa: BLE001 - the halt is already written; alert degraded
            logger.error("%s: held positions unreadable (%s)", _SITE, type(exc).__name__)
            return None

    @staticmethod
    def _unreadable(client: ExecClientView) -> tuple[str, ...]:
        try:
            return client.unreadable_slot_keys
        except Exception as exc:  # noqa: BLE001 - an alert input must not stop the tick
            logger.error("%s: unreadable-slot keys unreadable (%s)", _SITE, type(exc).__name__)
            return ()

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
