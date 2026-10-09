"""``install_resolver_contradiction_alert``: turn a resolver evidence
contradiction into exactly one operator alert per intent id.

EDGE-2 slice D (silent-failure review, 75b9008): the resolver's
``resolver_evidence_contradiction`` CRITICAL was recorded on
``PolymarketUSExecutionClient.resolver_evidence_contradictions`` but had no
subscriber anywhere -- a detector without delivery is not a control (the
2026-09-20 alerts-reach-nobody incident this repo already paid 3 days for).
This module closes that gap the same way ``install_stale_intent_alert``
already does for the sibling ``stale_ambiguous_intent_alerts`` surface: the
execution client cannot dispatch its own alert (barrier E0-TRANSPORT /
E0-NOSEND-RESOLVER), so this is the one place with both an ``AlertSink`` and
permission to import ``breezy.runtime.health``.

Mirrors ``test_component_health_watch_stale_intent_alert.py``'s shape
exactly: a recording sink, a real ``MessageBus``, and the topic driven by
hand.
"""

from __future__ import annotations

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.identifiers import ClientId, TraderId

from breezy.runtime.component_health_watch import (
    COMPONENT_STATE_TOPIC,
    RESOLVER_CONTRADICTION_ALERT_EVENT,
    RESOLVER_CONTRADICTION_ALERT_SEVERITY,
    install_resolver_contradiction_alert,
)
from breezy.runtime.health import AlertPayload

TRADER_ID = TraderId("BREEZY-CONTRADICTION-001")


class _RecordingSink:
    """An `AlertSink` that keeps every payload it is handed."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _new_bus() -> MessageBus:
    return MessageBus(trader_id=TRADER_ID, clock=LiveClock())


def _tick(msgbus: MessageBus) -> None:
    """Publish one ``ComponentStateChanged`` on the watch topic.

    The handler under test ignores the event's own contents -- it exists
    only to trigger a fresh read of the surface, exactly the way
    ``install_stale_intent_alert``'s own handler uses the same topic as a
    poll proxy rather than as a signal to interpret.
    """
    msgbus.publish(
        topic="events.system.SOME_COMPONENT",
        msg=ComponentStateChanged(
            trader_id=TRADER_ID,
            component_id=ClientId("SOME_COMPONENT"),
            component_type="SomeComponent",
            state=ComponentState.RUNNING,
            config={},
            event_id=UUID4(),
            ts_event=0,
            ts_init=0,
        ),
    )


def _alert(
    *,
    intent_id: str = "intent-1",
    venue_order_id: str = "vo-1",
    trade_count: str = "1",
    create_fill_evidence: str = "none",
) -> dict[str, str]:
    return {
        "severity": "CRITICAL",
        "event": "resolver_evidence_contradiction",
        "site": "global",
        "intent_id": intent_id,
        "venue_order_id": venue_order_id,
        "trade_count": trade_count,
        "create_fill_evidence": create_fill_evidence,
    }


def test_the_watch_subscribes_the_shared_component_state_topic() -> None:
    """The same heartbeat as the other watches -- no second topic."""
    assert COMPONENT_STATE_TOPIC == "events.system.*"


def test_an_empty_surface_never_alerts() -> None:
    """Negative control: no contradiction means no alert."""
    msgbus = _new_bus()
    sink = _RecordingSink()
    install_resolver_contradiction_alert(msgbus, contradictions=lambda: (), sink=sink)

    _tick(msgbus)
    _tick(msgbus)

    assert sink.payloads == []


def test_one_contradiction_emits_one_alert_with_the_expected_fields() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface: tuple[dict[str, str], ...] = (_alert(),)
    install_resolver_contradiction_alert(msgbus, contradictions=lambda: surface, sink=sink)

    _tick(msgbus)

    assert len(sink.payloads) == 1, sink.payloads
    payload = sink.payloads[0]
    assert payload.severity == RESOLVER_CONTRADICTION_ALERT_SEVERITY == "CRITICAL"
    assert (
        payload.event == RESOLVER_CONTRADICTION_ALERT_EVENT == "resolver_evidence_contradiction"
    )
    assert payload.site == "global"
    assert "intent-1" in payload.detail
    assert "vo-1" in payload.detail
    assert "1" in payload.detail
    assert "none" in payload.detail
    # Never a price, quantity or amount -- only closed-set tokens and counts.
    assert "$" not in payload.detail


def test_the_same_entry_on_a_later_poll_does_not_re_alert() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface: tuple[dict[str, str], ...] = (_alert(),)
    install_resolver_contradiction_alert(msgbus, contradictions=lambda: surface, sink=sink)

    _tick(msgbus)
    _tick(msgbus)
    _tick(msgbus)

    assert len(sink.payloads) == 1, sink.payloads


def test_an_entry_that_disappears_is_forgotten_and_a_new_intent_alerts_again() -> None:
    """Clearing (a later consistent pass, or an operator clearing path)
    resets the client's own bookkeeping (`_retire`); the watch must mirror
    that rather than latching an intent id forever."""
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface: list[dict[str, str]] = [_alert(intent_id="intent-1")]
    install_resolver_contradiction_alert(msgbus, contradictions=lambda: tuple(surface), sink=sink)

    _tick(msgbus)
    assert len(sink.payloads) == 1

    surface.clear()  # intent-1 cleared
    _tick(msgbus)
    assert len(sink.payloads) == 1, "clearing must not itself alert"

    surface.append(_alert(intent_id="intent-2"))  # a later, distinct intent
    _tick(msgbus)
    assert len(sink.payloads) == 2, sink.payloads
    assert "intent-2" in sink.payloads[1].detail


def test_a_broken_surface_reader_does_not_crash_the_handler() -> None:
    """CONTAINMENT: the handler runs synchronously on the message bus; a
    broken reader must not unwind into the publishing component."""

    def _boom() -> tuple[dict[str, str], ...]:
        raise RuntimeError("surface read failed")

    msgbus = _new_bus()
    sink = _RecordingSink()
    install_resolver_contradiction_alert(msgbus, contradictions=_boom, sink=sink)

    _tick(msgbus)  # must not raise

    assert sink.payloads == []


def test_a_failing_sink_never_unwinds_into_the_message_bus() -> None:
    """`emit_alert` contains any sink failure; this is the proof the watch
    actually routes through it rather than calling `sink.emit` bare."""

    class _BrokenSink:
        def emit(self, payload: AlertPayload) -> None:
            raise RuntimeError("sink down")

    msgbus = _new_bus()
    install_resolver_contradiction_alert(
        msgbus, contradictions=lambda: (_alert(),), sink=_BrokenSink(),
    )

    _tick(msgbus)  # must not raise


def test_a_no_id_contradiction_names_its_reason_and_the_automated_next_action() -> None:
    """AMBIG-LATCH-RESUME (plan r6 2.10): a no-id entry carries no GET and no
    zero-fill claim, so its alert must say what it is -- the closed reason
    token and the automated ``next`` -- and must not tell anyone to review it
    by hand."""
    msgbus = _new_bus()
    sink = _RecordingSink()
    entry = {
        "severity": "CRITICAL",
        "event": "resolver_evidence_contradiction",
        "site": "global",
        "intent_id": "intent-9",
        "venue_order_id": "none",
        "no_id": "true",
        "reason": "unexplained_holding_delta",
        "next": "no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution",
        "manual_reconcile": "straddles_snapshot",
    }
    install_resolver_contradiction_alert(msgbus, contradictions=lambda: (entry,), sink=sink)

    _tick(msgbus)

    assert len(sink.payloads) == 1
    detail = sink.payloads[0].detail
    assert "intent-9" in detail
    assert "unexplained_holding_delta" in detail
    assert "straddles_snapshot" in detail
    assert "no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution" in detail
    assert "operator" not in detail.lower()
    assert "terminal zero-fill" not in detail


def test_the_retire_blocked_entry_is_delivered_with_its_next_action() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    entry = {
        "severity": "CRITICAL",
        "event": "resolver_no_id_retire_blocked",
        "site": "global",
        "intent_id": "intent-9",
        "venue_order_id": "none",
        "no_id": "true",
        "reason": "supervisor_decode_marker_absent",
        "next": "next_node_boot_rereads_supervisor_marker",
    }
    install_resolver_contradiction_alert(msgbus, contradictions=lambda: (entry,), sink=sink)

    _tick(msgbus)

    assert len(sink.payloads) == 1
    assert "supervisor_decode_marker_absent" in sink.payloads[0].detail
    assert "next_node_boot_rereads_supervisor_marker" in sink.payloads[0].detail
