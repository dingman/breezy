"""Turn a component's DEGRADED transition into exactly ONE operator alert.

EXEC SPINE R-6c (``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md``). **PORTABLE**:
nothing here names a venue, and the same subscriber serves Kalshi unchanged.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before this module was written:

* **The state transition is already native and already published.**
  ``Component.degrade()`` (``$NT/common/component.pyx:2098-2127``) drives the
  FSM ``RUNNING -> DEGRADING -> DEGRADED`` and publishes a
  ``ComponentStateChanged`` on ``events.system.<component_id>`` for EACH of
  those two transitions (``:2210-2225``). Nothing here reimplements, wraps or
  replaces it -- the execution client simply CALLS it.
* **The subscription mechanism is already native.** ``MessageBus.subscribe``
  with the ``*`` glob covers every component in the run, exactly as
  ``runtime/backtest_order_guard.install_live_order_guard`` uses it for
  ``events.order.*``. One wiring idiom, not two.
* **The alert seam already exists.** ``runtime/health.AlertSink`` /
  ``resolve_alert_sink`` / ``emit_alert`` are shipped and tested
  (``tests/unit/test_runtime_health.py``). This module constructs no sink of
  its own and opens no socket.

**What genuinely did not exist** is the join between those three: the native
event is published to a topic **nothing native and nothing in Breezy
subscribes**, so before R-6c a degraded execution client was an event with no
reader. That join -- and only that join -- is what this module is.

WHY THIS IS NOT AN ``Actor``, AND NOT UNDER ``exec/``
------------------------------------------------------
An ``Actor`` would have to be registered through ``actors=[]`` in
``runtime/node_config.build_trade_node_config``, which is a deliberate empty
literal, and it would buy nothing: this subscriber holds one boolean,
subscribes once, and emits. A plain ``msgbus.subscribe`` after ``node.build()``
is the shape R-6a already established.

It lives under ``runtime/`` rather than beside the execution client because it
MAY NOT live beside it: ``breezy.runtime.health`` is named in
``tests/unit/test_execution_egress_firewall_guard.BANNED_EXEC_TRANSPORT_
MODULES``, so no module under the venue adapter's ``exec/`` package may import
it -- it owns an ``httpx`` client. That is a barrier, not a preference, and it
is also why this module names no venue at all.

DEGRADED IS AN INDICATOR, NEVER A KILL SWITCH
----------------------------------------------
Seven of the execution client's twenty-five refusal producers are ROUTINE on an
account an operator has also traded by hand (the full triage is in
``tests/unit/test_exec_refusal_health_surface.py``'s module docstring). So
this module alerts and does nothing else: it calls no stop verb, publishes no
``ShutdownSystem``, writes no fault latch, and touches no exit code. A node
that has degraded keeps running and keeps refusing, which is the state an
operator can actually act on.

CONTAINMENT
-----------
The handler runs ON the message bus, synchronously, inside whatever component
published the event. Two consequences are designed for rather than hoped for:

* the reasons reader is called inside a ``try`` -- a broken reader must not
  cost the operator the alert itself;
* the sink is always reached through ``emit_alert``, never called bare, so a
  dead webhook cannot unwind into the publishing component
  (``health.py``'s ``emit_alert`` catches ``BaseException`` deliberately).

``AlertPayload`` truncates ``detail`` to ``MAX_ALERT_DETAIL_CHARS``, which
bounds -- but does not by itself sanitise -- what a refusal reason carries to
a configured webhook. Refusal reasons are venue-state sentences the client
already emits at ERROR into the operator's log stream; they carry no
credential and no ``user_agent_contact``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged

from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncio
    from collections.abc import Callable, Mapping, Sequence

    from nautilus_trader.common.component import Clock, MessageBus, TimeEvent

    from breezy.runtime.health import AlertSink

logger = logging.getLogger(__name__)

#: The topic ``Component._trigger_fsm`` publishes every state change to
#: (``$NT/common/component.pyx:2222-2225``). ``*`` is a ``MessageBus`` glob
#: matching one or more characters, so ONE subscription covers every component
#: in the run, including components built after this is installed.
COMPONENT_STATE_TOPIC: Final[str] = "events.system.*"

#: The ``AlertPayload.event`` this module emits. One value: an operator
#: filtering on it gets every degraded component and nothing else.
DEGRADED_ALERT_EVENT: Final[str] = "component_degraded"

#: CRITICAL, not WARN. A degraded execution client is not trading, and the
#: operator has to decide whether that is a foreign position to resolve or a
#: venue outage to wait out. Either way it is not something to notice next
#: week.
DEGRADED_ALERT_SEVERITY: Final[str] = "CRITICAL"

#: ``AlertPayload.site`` is ``"<venue>/<city>"`` or ``"global"``; a component
#: is process-wide, so it is ``"global"``. The component's identity travels in
#: ``detail``, which is the only field free enough to carry it.
DEGRADED_ALERT_SITE: Final[str] = "global"

#: One hour. Caps a storm of NON-AMBIGUOUS repeat episodes at one identical
#: CRITICAL per hour. AMBIGUOUS episodes are exempt (F3): each one alerts.
#: Same units/name as health.AlertState.
DEGRADED_ALERT_RENOTIFY_AFTER_NS: Final[int] = 60 * 60 * 1_000_000_000

#: Stands in for the reasons when the reader itself fails. The alert still
#: goes out: the fact of degradation is the operator's signal, and the reasons
#: are already in the log stream regardless.
REASONS_UNAVAILABLE: Final[str] = "reasons unavailable (the refusal reader failed)"


def _detail(component_id: str, reasons: Sequence[str]) -> str:
    if not reasons:
        return f"{component_id} DEGRADED; no refusal reason recorded"
    return f"{component_id} DEGRADED after {len(reasons)} refusal(s): " + "; ".join(reasons)


#: The ``AlertPayload.event`` for a still-OPEN, still-unresolved AMBIGUOUS
#: intent whose age has crossed an execution client's staleness threshold.
#: See the ``stale_ambiguous_intent_alerts`` health property (2026-09-11
#: incident addendum, item 3): that property only RECORDS the condition --
#: this module is the one place with both an ``AlertSink`` and permission to
#: import it that can actually dispatch the alert.
STALE_INTENT_ALERT_EVENT: Final[str] = "open_intent_stale"

#: CRITICAL, matching the client's own pre-built detail mapping: an OPEN
#: intent an operator cannot see the outcome of is exactly the kind of thing
#: that must not wait for next week's log review.
STALE_INTENT_ALERT_SEVERITY: Final[str] = "CRITICAL"

#: Same convention as ``DEGRADED_ALERT_SITE``: the condition is process-wide,
#: not per-market, so the intent's identity travels in ``detail`` instead.
STALE_INTENT_ALERT_SITE: Final[str] = "global"


def _alert_key(alert: Mapping[str, str]) -> str:
    """FAILURE-KIND-PERSIST (r2/r3): dedupe/forget key for one surface entry.

    A follow-up entry carries the SAME ``intent_id`` as its original stale
    entry (deliberately -- it renders as that intent's cause, per
    :func:`_stale_intent_detail`), so keying dedupe on ``intent_id`` alone
    would skip it forever (it is never a NEW id) and `_retire` dropping the
    original would never forget it either (the id lookup would still find
    the follow-up's identical id). ``alert_key`` -- present only on a
    follow-up -- disambiguates the two; a legacy entry with no ``alert_key``
    (every non-follow-up entry, past and present) falls back to
    ``intent_id`` unchanged. A ``def``, not a lambda (ruff E731).
    """
    return alert.get("alert_key", alert.get("intent_id", ""))


def _stale_intent_detail(alert: Mapping[str, str]) -> str:
    intent_id = alert.get("intent_id", "<unknown>")
    venue_order_id = alert.get("venue_order_id", "<unknown>")
    age_minutes = alert.get("age_minutes", "<unknown>")
    last_failure_kind = alert.get("last_failure_kind", "<unknown>")
    base = (
        f"intent {intent_id} (venue order {venue_order_id}) has been OPEN "
        f"AMBIGUOUS and unresolved for {age_minutes} minute(s); last "
        f"resolver failure: {last_failure_kind}"
    )
    if alert.get("followup") == "cause":
        # FAILURE-KIND-PERSIST (r2/r3): marks the SECOND CRITICAL for this
        # intent as what it is, rather than looking like an unrelated repeat.
        return f"{base}; cause identified after the first alert"
    return base


def install_stale_intent_alert(
    msgbus: MessageBus,
    *,
    stale_alerts: Callable[[], Sequence[Mapping[str, str]]],
    sink: AlertSink | None = None,
) -> Callable[[object], None]:
    """Subscribe one operator alert per intent id that goes stale.

    Wired onto the SAME ``COMPONENT_STATE_TOPIC`` heartbeat
    ``install_component_degraded_alert`` subscribes -- exactly the "secondary
    path" idiom ``current_rung_hold.composition.
    install_current_rung_hold_refusal_watch`` already uses to re-check a
    non-event-driven surface on every state change in the run. FU-8b adds a
    SECOND trigger, :func:`install_refusal_repoll_timer`, a native
    ``LiveClock`` timer that calls the SAME handler this function returns on
    a fixed interval -- so a latch appearing between state changes is still
    alerted. Both triggers share this closure's own dedupe set unchanged.

    Parameters
    ----------
    msgbus
        A LIVE node's ``node.kernel.msgbus``, after ``build()``.
    stale_alerts
        Reads the execution client's ``stale_ambiguous_intent_alerts``
        health property at the moment of the poll. A callable, exactly like
        ``install_component_degraded_alert``'s ``reasons``, so this module
        never pins the client object into its own closure and never names
        the venue it came from.
    sink
        Defaults to :func:`~breezy.runtime.health.resolve_alert_sink`.

    Returns
    -------
    The subscribed handler, so a caller (and a test) can hold it.

    Notes
    -----
    Dedupe is by :func:`_alert_key` (``alert_key`` when present, else
    ``intent_id``), never by call count: a key already alerted on is skipped
    on every later poll, and a key that drops out of the surface (the exec
    client's ``_retire`` clears its own bookkeeping the moment the intent
    retires) is forgotten here too, so a LATER intent that happens to reach
    the same age alerts again -- exactly the semantics the property's own
    docstring documents. FAILURE-KIND-PERSIST (r2/r3): a follow-up entry
    carries the SAME ``intent_id`` as its original but a DIFFERENT
    ``alert_key`` (``f"{intent_id}:cause"``), so it is never conflated with
    -- and never suppressed by -- the original's own dedupe entry: one
    intent can therefore surface as two separate CRITICALs.
    """
    active_sink = resolve_alert_sink() if sink is None else sink
    alerted_intent_ids: set[str] = set()

    def _on_component_state(event: object) -> None:
        # Every event on the shared topic is just a poll trigger; the stale-
        # intent surface, unlike the DEGRADED transition, carries no signal
        # of its own to inspect on the event itself.
        del event
        try:
            current = tuple(stale_alerts())
        # Broad, deliberately: a broken reader must not crash the component
        # publishing the triggering event (CONTAINMENT, module docstring).
        except Exception:
            logger.exception("failed to read stale_ambiguous_intent_alerts")
            return

        current_ids = {_alert_key(alert) for alert in current}
        alerted_intent_ids.intersection_update(current_ids)

        for alert in current:
            key = _alert_key(alert)
            if key in alerted_intent_ids:
                continue
            alerted_intent_ids.add(key)
            emit_alert(
                active_sink,
                AlertPayload(
                    severity=STALE_INTENT_ALERT_SEVERITY,
                    event=STALE_INTENT_ALERT_EVENT,
                    site=STALE_INTENT_ALERT_SITE,
                    detail=_stale_intent_detail(alert),
                ),
            )

    msgbus.subscribe(topic=COMPONENT_STATE_TOPIC, handler=_on_component_state)
    return _on_component_state


#: The ``AlertPayload.event`` for EDGE-2 slice D's
#: ``resolver_evidence_contradiction`` health-surface entry: a GET-terminal
#: zero-fill whose own create-time evidence or activities trade join
#: disagrees with it. See
#: ``resolver_evidence_contradictions`` on the venue execution client (AC4):
#: that property only RECORDS the condition -- the client may not import
#: this layer (barrier E0-TRANSPORT), so this is where it is dispatched,
#: exactly like :data:`STALE_INTENT_ALERT_EVENT` immediately above. A
#: detector that only records and never delivers is not a control (the
#: 2026-09-20 alerts-reach-nobody incident, module docstring precedent).
RESOLVER_CONTRADICTION_ALERT_EVENT: Final[str] = "resolver_evidence_contradiction"

#: CRITICAL: an intent that CANNOT resolve as zero-fill on its own evidence
#: needs an operator, not next week's log review -- same severity as the
#: stale-intent watch immediately above.
RESOLVER_CONTRADICTION_ALERT_SEVERITY: Final[str] = "CRITICAL"

#: Process-wide, like every other watch in this module: the intent's
#: identity travels in ``detail``.
RESOLVER_CONTRADICTION_ALERT_SITE: Final[str] = "global"


def _resolver_contradiction_detail(alert: Mapping[str, str]) -> str:
    intent_id = alert.get("intent_id", "<unknown>")
    if alert.get("no_id") == "true":
        # AMBIG-LATCH-RESUME (plan r6 2.10): a no-id entry has no venue order
        # id, no GET and no zero-fill claim. It names its closed reason token
        # and the AUTOMATED next action -- never a hand step.
        manual = alert.get("manual_reconcile")
        manual_part = f" manual_reconcile={manual}" if manual else ""
        return (
            f"intent {intent_id} (no venue order id) stays AMBIGUOUS: "
            f"reason={alert.get('reason', '<unknown>')}{manual_part}; "
            f"next={alert.get('next', '<unknown>')}"
        )
    venue_order_id = alert.get("venue_order_id", "<unknown>")
    trade_count = alert.get("trade_count", "<unknown>")
    create_fill_evidence = alert.get("create_fill_evidence", "<unknown>")
    return (
        f"intent {intent_id} (venue order {venue_order_id}) reports a GET "
        "terminal zero-fill that disagrees with the resolver's own evidence "
        f"(trade_count={trade_count}, create_fill_evidence={create_fill_evidence}); "
        "stays AMBIGUOUS pending an operator review"
    )


def install_resolver_contradiction_alert(
    msgbus: MessageBus,
    *,
    contradictions: Callable[[], Sequence[Mapping[str, str]]],
    sink: AlertSink | None = None,
) -> Callable[[object], None]:
    """Subscribe one operator alert per intent id whose resolver evidence
    contradicts a GET-reported zero-fill.

    Mirrors :func:`install_stale_intent_alert` EXACTLY: the same
    ``COMPONENT_STATE_TOPIC`` heartbeat trigger,
    :func:`install_refusal_repoll_timer` as the SAME second (fixed-interval)
    trigger, and dedupe by ``intent_id`` with the identical forget-on-
    disappearance semantics -- ``_retire`` clears the venue execution
    client's own bookkeeping the moment an intent stops contradicting (a
    later pass resolves it, or an operator clears it), so a LATER intent
    that happens to reach the same shape alerts again.

    Parameters
    ----------
    msgbus
        A LIVE node's ``node.kernel.msgbus``, after ``build()``.
    contradictions
        Reads the execution client's ``resolver_evidence_contradictions``
        health property at the moment of the poll. A callable, exactly like
        ``stale_alerts`` above, so this module never pins the client object
        into its own closure and never names the venue it came from.
    sink
        Defaults to :func:`~breezy.runtime.health.resolve_alert_sink`.

    Returns
    -------
    The subscribed handler, so a caller (and a test) can hold it -- and pass
    it to :func:`install_refusal_repoll_timer` alongside the other watches.
    """
    active_sink = resolve_alert_sink() if sink is None else sink
    alerted_intent_ids: set[str] = set()

    def _on_component_state(event: object) -> None:
        del event
        try:
            current = tuple(contradictions())
        # Broad, deliberately: a broken reader must not crash the component
        # publishing the triggering event (CONTAINMENT, module docstring).
        except Exception:
            logger.exception("failed to read resolver_evidence_contradictions")
            return

        current_ids = {alert.get("intent_id", "") for alert in current}
        alerted_intent_ids.intersection_update(current_ids)

        for alert in current:
            intent_id = alert.get("intent_id", "")
            if intent_id in alerted_intent_ids:
                continue
            alerted_intent_ids.add(intent_id)
            emit_alert(
                active_sink,
                AlertPayload(
                    severity=RESOLVER_CONTRADICTION_ALERT_SEVERITY,
                    event=RESOLVER_CONTRADICTION_ALERT_EVENT,
                    site=RESOLVER_CONTRADICTION_ALERT_SITE,
                    detail=_resolver_contradiction_detail(alert),
                ),
            )

    msgbus.subscribe(topic=COMPONENT_STATE_TOPIC, handler=_on_component_state)
    return _on_component_state


#: AUD-13b: the event every latched durable-reconciliation refusal of an
#: execution client is delivered under (plan §6, "emit a WARN alert"). The
#: client only RECORDS the refusal on ``reconciliation_refusals`` -- it may not
#: import this layer (barrier E0-TRANSPORT) -- so this is where it is sent.
RECONCILIATION_REFUSAL_ALERT_EVENT: Final[str] = "reconciliation_refusal"

#: WARN, as the plan names it: every such refusal falls CLOSED to the engine's
#: existing inference and the node still boots and hunts; the one
#: reconciliation outcome that halts the boot is AUD-13d's CRITICAL.
RECONCILIATION_REFUSAL_ALERT_SEVERITY: Final[str] = "WARN"

#: Process-wide, like the other two watches.
RECONCILIATION_REFUSAL_ALERT_SITE: Final[str] = "global"

#: The ruled ``detail`` members (plan §6/§8 item 17). Anything else on the
#: surface is sent as the generic member -- the surface's own free text never
#: travels, so no id, date or exception text can reach the sink.
_RECONCILIATION_REFUSAL_DETAILS: Final[frozenset[str]] = frozenset(
    {
        "POSITIONS_READ_FAILED",
        "RECORD_VENUE_DISAGREEMENT",
        "FEE_COEFFICIENT_AMBIGUOUS",
        "DURABLE_REPORTS_BUILD_FAILED",
        # FU-8 r2/r2.1: informational only (a runtime latch, never a boot-pass
        # refusal) -- named here so it is never sent as the generic
        # `RECONCILIATION_REFUSAL_UNKNOWN` member.
        "RESOLVER_FILL_NOT_BOOKED",
    }
)
_RECONCILIATION_REFUSAL_UNKNOWN_DETAIL: Final[str] = "RECONCILIATION_REFUSAL_UNKNOWN"


def install_reconciliation_refusal_alert(
    msgbus: MessageBus,
    *,
    refusals: Callable[[], Sequence[Mapping[str, str]]],
    sink: AlertSink | None = None,
) -> Callable[[object], None]:
    """Emit one WARN alert per NEW latched durable-reconciliation refusal.

    Rides the SAME ``COMPONENT_STATE_TOPIC`` heartbeat as
    :func:`install_stale_intent_alert`. The poll is guaranteed to run after
    the startup reconciliation: ``NautilusKernel.start_async`` awaits the
    reconciliation (``system/kernel.py:1027-1029``) and only then starts the
    ``OrderEmulator`` (``:1033``) and the trader (``:1039``), each of which
    publishes a ``ComponentStateChanged`` on ``events.system.*``. The shipped
    ``LiveExecEngineConfig`` enables no periodic reconciliation
    (``open_check_interval_secs``/``position_check_interval_secs`` stay
    ``None``), and any later state change re-polls regardless. FU-8b adds a
    SECOND trigger, :func:`install_refusal_repoll_timer`, a native
    ``LiveClock`` timer that calls the SAME handler this function returns on
    a fixed interval, so a latch added at runtime is alerted without waiting
    for an unrelated component's state change. Both triggers share this
    closure's own dedupe set unchanged.

    Dedupe is by ``(latch, subject)`` -- the client latches each once per
    process -- but only the fixed-enum ``detail`` is sent.
    """
    active_sink = resolve_alert_sink() if sink is None else sink
    alerted: set[tuple[str, str]] = set()

    def _on_component_state(event: object) -> None:
        del event
        try:
            current = tuple(refusals())
        # Broad, deliberately: a broken reader must not crash the component
        # publishing the triggering event (CONTAINMENT, module docstring).
        except Exception:
            logger.exception("failed to read reconciliation_refusals")
            return
        for refusal in current:
            key = (refusal.get("latch", ""), refusal.get("subject", ""))
            if key in alerted:
                continue
            alerted.add(key)
            detail = refusal.get("detail", "")
            emit_alert(
                active_sink,
                AlertPayload(
                    severity=RECONCILIATION_REFUSAL_ALERT_SEVERITY,
                    event=RECONCILIATION_REFUSAL_ALERT_EVENT,
                    site=RECONCILIATION_REFUSAL_ALERT_SITE,
                    detail=(
                        detail
                        if detail in _RECONCILIATION_REFUSAL_DETAILS
                        else _RECONCILIATION_REFUSAL_UNKNOWN_DETAIL
                    ),
                ),
            )

    msgbus.subscribe(topic=COMPONENT_STATE_TOPIC, handler=_on_component_state)
    return _on_component_state


#: FU-8b: the ``Clock.set_timer`` name this module's re-poll timer is armed
#: under. A single, fixed name -- one timer, never a per-caller name -- so a
#: duplicate ``install_refusal_repoll_timer`` call on the SAME clock fails
#: loudly at install time (``Condition.not_in``, a ``KeyError``) rather than
#: silently doubling the poll rate.
REFUSAL_REPOLL_TIMER_NAME: Final[str] = "breezy-refusal-repoll"

#: 60 seconds. The stale-intent threshold this re-poll shortens is 15 minutes
#: (``exec/client.py:569``), so this adds at most 6.7% latency to that
#: signal; the surfaces it reads change at most once per resolver pass (5 s,
#: ``exec/client.py:551``); and minute granularity is what an operator reads
#: a log timestamp at. The cost -- two small tuple copies and a handful of
#: set lookups per minute -- is negligible.
REFUSAL_REPOLL_INTERVAL: Final[timedelta] = timedelta(seconds=60)

#: 60 ticks of the 60 s :data:`REFUSAL_REPOLL_INTERVAL` -- hourly. A low-rate
#: positive liveness signal, distinct from the one-time "armed" INFO line:
#: without it an operator reading the log cannot tell a dead timer (Rust/tokio
#: thread wedged, or silently uninstalled) from a quiet interval with nothing
#: to alert on. Emitted from ``_poll`` -- the loop-thread function, never
#: ``_on_timer`` -- so the signal only fires once the ``call_soon_threadsafe``
#: hop actually lands, which is the same liveness the alert handlers depend
#: on. Not per-tick: a 60 s INFO line would drown the log for no operator
#: benefit.
REFUSAL_REPOLL_HEARTBEAT_TICKS: Final[int] = 60


def install_refusal_repoll_timer(
    clock: Clock,
    *,
    loop: asyncio.AbstractEventLoop,
    handlers: Sequence[Callable[[object], None]],
    interval: timedelta = REFUSAL_REPOLL_INTERVAL,
) -> Callable[[], None]:
    """Arm a native ``Clock`` timer that re-polls ``handlers`` on an interval.

    FU-8b. :func:`install_reconciliation_refusal_alert` and
    :func:`install_stale_intent_alert` alert only when SOMETHING ELSE
    publishes a ``ComponentStateChanged`` -- a runtime latch (for example
    ``RESOLVER_FILL_NOT_BOOKED``) or a newly-stale intent between two state
    changes stays unalerted until an unrelated component happens to
    transition. This function is the second trigger: it calls the SAME
    handler closures those two installers already return, on a fixed
    interval, sharing their existing dedupe sets unchanged. No synthetic
    ``ComponentStateChanged`` is ever published.

    Thread model (measured, ``tests/contract/test_live_timer_thread_
    affinity.py``): a ``LiveClock`` timer callback runs on a Rust/tokio
    thread, never the asyncio loop thread, and a raise inside it is silently
    discarded by the pyo3 wrapper. So ``_on_timer`` -- the callback armed
    directly on ``clock`` -- does almost nothing itself: wrapped in
    ``try/except BaseException``, it checks whether ``loop`` is already
    closed (a fire racing ``dispose()``) and, if not, hops to the loop thread
    via ``loop.call_soon_threadsafe``. Any failure to schedule -- including
    the closed-loop race between the check and the call -- is logged at
    ERROR with the exception TYPE only, mirroring ``health.emit_alert``'s own
    discipline. "At most one ERROR" holds only for the loop-CLOSING race:
    once ``loop.is_closed()`` answers ``True``, every later tick returns
    before scheduling anything, so that failure mode logs once. A
    PERSISTENT, non-closing ``call_soon_threadsafe`` failure (the loop stays
    open but scheduling keeps raising for some other reason) is not
    contained the same way and re-logs one ERROR every interval for as long
    as the failure persists -- still bounded to one per tick, but loud.

    ``_poll`` -- the function handed to the loop -- runs each handler inside
    its OWN ``try/except Exception``, so one raising handler is logged (named,
    so an operator can tell which of ``handlers`` failed) and neither blocks
    its sibling in the same tick nor any later tick. Every
    :data:`REFUSAL_REPOLL_HEARTBEAT_TICKS` th tick, after the handlers run,
    ``_poll`` also emits one low-rate INFO heartbeat so a dead timer is
    distinguishable from a quiet interval.

    Parameters
    ----------
    clock
        A LIVE node's ``node.kernel.clock``, after ``build()``.
    loop
        The SAME node's ``node.kernel.loop`` -- the asyncio loop the msgbus
        trigger's handlers already run on, so both triggers stay mutually
        serial with no lock needed on the shared dedupe sets.
    handlers
        The handler closures :func:`install_reconciliation_refusal_alert`
        and :func:`install_stale_intent_alert` already returned. Called in
        the given order on every fire.
    interval
        Defaults to :data:`REFUSAL_REPOLL_INTERVAL`. Overridable only for
        tests (the contract test injects 50 ms).

    Returns
    -------
    ``cancel``: an idempotent callable that removes the timer if it is still
    armed. Safe to call more than once, and safe to call after the clock
    already removed it (a live kernel's own ``_cancel_timers`` on stop).

    Notes
    -----
    A duplicate call on the SAME clock is NOT contained -- ``clock.set_timer``
    raises ``KeyError`` (``Condition.not_in``) synchronously, at install
    time, never inside a callback -- so a caller arming this twice by mistake
    fails loudly rather than doubling the poll rate.
    """

    tick_count = 0

    def _poll(event: object) -> None:
        nonlocal tick_count
        for index, handler in enumerate(handlers):
            try:
                handler(event)
            # Broad, deliberately: one broken handler must not block its
            # sibling in this tick, or any later tick (CONTAINMENT, module
            # docstring).
            except Exception:
                handler_name = (
                    getattr(handler, "__qualname__", None)
                    or getattr(handler, "__name__", None)
                    or f"handlers[{index}]"
                )
                logger.exception("refusal re-poll handler failed handler=%s", handler_name)

        tick_count += 1
        if tick_count % REFUSAL_REPOLL_HEARTBEAT_TICKS == 0:
            logger.info(
                "refusal re-poll alive name=%s ticks=%d",
                REFUSAL_REPOLL_TIMER_NAME,
                tick_count,
            )

    def _on_timer(event: TimeEvent) -> None:
        try:
            if loop.is_closed():
                return
            loop.call_soon_threadsafe(_poll, event)
        # BaseException, deliberately: this callback runs on a foreign
        # (Rust/tokio) thread where a raise is silently discarded (L-16), so
        # nothing may escape it, for any reason.
        except BaseException as exc:  # noqa: BLE001
            logger.error(
                "failed to schedule refusal re-poll exception_type=%s",
                type(exc).__name__,
            )

    clock.set_timer(
        name=REFUSAL_REPOLL_TIMER_NAME,
        interval=interval,
        callback=_on_timer,
        fire_immediately=False,
    )
    logger.info(
        "refusal re-poll timer armed name=%s interval_s=%s",
        REFUSAL_REPOLL_TIMER_NAME,
        int(interval.total_seconds()),
    )

    def cancel() -> None:
        if REFUSAL_REPOLL_TIMER_NAME not in clock.timer_names:
            return
        try:
            clock.cancel_timer(REFUSAL_REPOLL_TIMER_NAME)
        except (KeyError, ValueError):
            logger.debug("refusal re-poll timer already cancelled")

    return cancel


def install_component_degraded_alert(
    msgbus: MessageBus,
    *,
    component_id: str,
    reasons: Callable[[], Sequence[str]],
    sink: AlertSink | None = None,
    renotify_after_ns: int = DEGRADED_ALERT_RENOTIFY_AFTER_NS,
    ambiguous_reason: str | None = None,
    ambiguous_clears: Callable[[], int] | None = None,
) -> Callable[[object], None]:
    """Subscribe one operator alert to ``component_id`` reaching ``DEGRADED``.

    Parameters
    ----------
    msgbus
        A LIVE node's ``node.kernel.msgbus``, after ``build()``.
    component_id
        The component whose degradation is the operator's business, as the
        string form of its ``Component.id``. Every other component's
        transitions are ignored rather than alerted on: one alert about the
        thing that stopped trading is worth more than an alert about
        everything.
    reasons
        Reads the current refusal reasons at the moment of the alert. A
        callable rather than a value because the component records its
        reasons before it degrades, and the reader must not pin the component
        object into this module's closure any earlier than it has to.
    sink
        Defaults to :func:`~breezy.runtime.health.resolve_alert_sink`, which
        returns the logging sink unless ``BREEZY_ALERT_WEBHOOK_URL`` is set.
    renotify_after_ns
        The throttle window for a repeat NON-AMBIGUOUS episode whose reasons
        are a subset of the last alert's. A ``bool``, a non-int or a value
        <= 0 raises ``ValueError``.
    ambiguous_reason
        The AMBIGUOUS refusal reason; episodes carrying it are never
        throttled (F3). Passed by the caller so this module imports nothing
        from the venue adapter.
    ambiguous_clears
        Reads the count of AMBIGUOUS refusals cleared so far. With
        ``ambiguous_reason`` it lets a re-poll tick alert an episode that
        was added without a state transition (F6).

    Returns
    -------
    The subscribed handler, so a caller (and a test) can hold it. The node
    holds only the bound function.

    Notes
    -----
    ``degrade()`` publishes DEGRADING and then DEGRADED. Only the second is
    alerted on -- alerting on both would double every alert -- and only the
    FIRST DEGRADED per episode is. ``RUNNING`` re-arms the component, so a
    refusal after a resume is a new episode; a repeat episode is throttled
    unless it is AMBIGUOUS or carries a reason the last alert did not.
    """
    if (
        isinstance(renotify_after_ns, bool)
        or not isinstance(renotify_after_ns, int)
        or renotify_after_ns <= 0
    ):
        raise ValueError(f"renotify_after_ns must be a positive int, got {renotify_after_ns!r}")
    active_sink = resolve_alert_sink() if sink is None else sink
    alerted: set[str] = set()
    last_alert: list[tuple[int, frozenset[str]]] = []
    ambiguous_alerted = [0]

    def _read_reasons() -> Sequence[str]:
        try:
            return tuple(reasons())
        # Broad, deliberately: a broken reader must not cost the operator the
        # alert itself, which is the part that carries the signal.
        except Exception:
            logger.exception("failed to read refusal reasons for %s", component_id)
            return (REASONS_UNAVAILABLE,)

    def _emit(recorded: Sequence[str]) -> None:
        emit_alert(
            active_sink,
            AlertPayload(
                severity=DEGRADED_ALERT_SEVERITY,
                event=DEGRADED_ALERT_EVENT,
                site=DEGRADED_ALERT_SITE,
                detail=_detail(component_id, recorded),
            ),
        )

    def _episodes(recorded: Sequence[str]) -> int | None:
        if ambiguous_reason is None or ambiguous_clears is None:
            return None
        try:
            cleared = int(ambiguous_clears())
        except Exception:
            logger.exception("failed to read ambiguous clears for %s", component_id)
            return None
        return cleared + (1 if ambiguous_reason in recorded else 0)

    def _on_tick() -> None:
        recorded = _read_reasons()
        episodes = _episodes(recorded)
        if episodes is None or episodes <= ambiguous_alerted[0]:
            return
        owed = episodes - ambiguous_alerted[0]
        ambiguous_alerted[0] = episodes
        for _ in range(owed):
            _emit(recorded)

    def _on_degraded(ts_event: int) -> None:
        alerted.add(component_id)
        recorded = _read_reasons()
        reason_set = frozenset(recorded)
        is_ambiguous = ambiguous_reason is not None and ambiguous_reason in reason_set
        if is_ambiguous:
            episodes = _episodes(recorded)
            ambiguous_alerted[0] = episodes if episodes is not None else ambiguous_alerted[0] + 1
        elif last_alert and REASONS_UNAVAILABLE not in reason_set:
            elapsed = ts_event - last_alert[0][0]
            if 0 <= elapsed < renotify_after_ns and reason_set <= last_alert[0][1]:
                logger.warning(
                    "component_degraded alert throttled component=%s reasons=%d since_last_s=%d",
                    component_id,
                    len(recorded),
                    elapsed // 1_000_000_000,
                )
                return
        last_alert[:] = [(ts_event, reason_set)]
        _emit(recorded)

    def _on_component_state(event: object) -> None:
        if not isinstance(event, ComponentStateChanged):
            _on_tick()
            return
        if str(event.component_id) != component_id:
            return
        if event.state == ComponentState.RUNNING:
            alerted.discard(component_id)
            return
        if event.state != ComponentState.DEGRADED:
            return
        if component_id in alerted:
            return
        _on_degraded(event.ts_event)

    msgbus.subscribe(topic=COMPONENT_STATE_TOPIC, handler=_on_component_state)
    return _on_component_state
