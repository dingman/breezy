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
from typing import TYPE_CHECKING, Final

from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged

from breezy.runtime.health import AlertPayload, emit_alert, resolve_alert_sink

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Mapping, Sequence

    from nautilus_trader.common.component import MessageBus

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


def _stale_intent_detail(alert: Mapping[str, str]) -> str:
    intent_id = alert.get("intent_id", "<unknown>")
    venue_order_id = alert.get("venue_order_id", "<unknown>")
    age_minutes = alert.get("age_minutes", "<unknown>")
    last_failure_kind = alert.get("last_failure_kind", "<unknown>")
    return (
        f"intent {intent_id} (venue order {venue_order_id}) has been OPEN "
        f"AMBIGUOUS and unresolved for {age_minutes} minute(s); last "
        f"resolver failure: {last_failure_kind}"
    )


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
    non-event-driven surface on every state change in the run, rather than
    adding a second timer.

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
    Dedupe is by ``intent_id``, never by call count: an id already alerted
    on is skipped on every later poll, and an id that drops out of the
    surface (the exec client's ``_retire`` clears its own bookkeeping the
    moment the intent retires) is forgotten here too, so a LATER intent
    that happens to reach the same age alerts again -- exactly the
    semantics the property's own docstring documents.
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
                    severity=STALE_INTENT_ALERT_SEVERITY,
                    event=STALE_INTENT_ALERT_EVENT,
                    site=STALE_INTENT_ALERT_SITE,
                    detail=_stale_intent_detail(alert),
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
    :func:`install_stale_intent_alert` -- no timer. The poll is guaranteed to
    run after the startup reconciliation: ``NautilusKernel.start_async``
    awaits the reconciliation (``system/kernel.py:1027-1029``) and only then
    starts the ``OrderEmulator`` (``:1033``) and the trader (``:1039``), each
    of which publishes a ``ComponentStateChanged`` on ``events.system.*``.
    The shipped ``LiveExecEngineConfig`` enables no periodic reconciliation
    (``open_check_interval_secs``/``position_check_interval_secs`` stay
    ``None``), and any later state change re-polls regardless.

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


def install_component_degraded_alert(
    msgbus: MessageBus,
    *,
    component_id: str,
    reasons: Callable[[], Sequence[str]],
    sink: AlertSink | None = None,
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

    Returns
    -------
    The subscribed handler, so a caller (and a test) can hold it. The node
    holds only the bound function.

    Notes
    -----
    ``degrade()`` publishes DEGRADING and then DEGRADED. Only the second is
    alerted on -- alerting on both would double every alert -- and only the
    FIRST DEGRADED per component is, so a component that re-enters the state
    cannot bury the operator under a repeat. That mirrors the dedupe the
    execution client's own ``_refuse`` already applies to its ERROR log.
    """
    active_sink = resolve_alert_sink() if sink is None else sink
    alerted: set[str] = set()

    def _on_component_state(event: object) -> None:
        if not isinstance(event, ComponentStateChanged):
            return
        if str(event.component_id) != component_id:
            return
        if event.state != ComponentState.DEGRADED:
            return
        if component_id in alerted:
            return
        alerted.add(component_id)

        try:
            recorded: Sequence[str] = tuple(reasons())
        # Broad, deliberately: a broken reader must not cost the operator the
        # alert itself, which is the part that carries the signal.
        except Exception:
            logger.exception("failed to read refusal reasons for %s", component_id)
            recorded = (REASONS_UNAVAILABLE,)

        emit_alert(
            active_sink,
            AlertPayload(
                severity=DEGRADED_ALERT_SEVERITY,
                event=DEGRADED_ALERT_EVENT,
                site=DEGRADED_ALERT_SITE,
                detail=_detail(component_id, recorded),
            ),
        )

    msgbus.subscribe(topic=COMPONENT_STATE_TOPIC, handler=_on_component_state)
    return _on_component_state
