"""``install_stale_intent_alert``: turn a stale OPEN AMBIGUOUS intent into
exactly one operator alert per intent id.

2026-09-11 incident addendum, item 3. The Polymarket.us execution client
cannot dispatch its own alert (barrier E0-TRANSPORT / E0-NOSEND-RESOLVER,
see ``PolymarketUSExecutionClient.stale_ambiguous_intent_alerts``'s own
docstring); it only RECORDS the condition on a read-only property. This
module -- the same one that already turns ``trading_refusals`` into a
``component_degraded`` alert -- is the one place with both an ``AlertSink``
and permission to import ``breezy.runtime.health``, so the dispatch lives
here, wired onto the SAME ``COMPONENT_STATE_TOPIC`` heartbeat
``current_rung_hold.composition.install_current_rung_hold_refusal_watch``
already uses as a poll proxy: every event on that topic re-checks the
surface, exactly like a timer would, with no new ``LiveClock`` dependency.

Mirrors ``test_exec_refusal_health_surface.py``'s shape for
``install_component_degraded_alert``: a recording sink, a real
``MessageBus``, and the topic driven by hand.
"""

from __future__ import annotations

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.identifiers import ClientId, TraderId

from breezy.runtime.component_health_watch import (
    COMPONENT_STATE_TOPIC,
    STALE_INTENT_ALERT_EVENT,
    STALE_INTENT_ALERT_SEVERITY,
    install_stale_intent_alert,
)
from breezy.runtime.health import AlertPayload

TRADER_ID = TraderId("BREEZY-STALE-001")


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
    ``install_current_rung_hold_refusal_watch``'s ``_on_event`` uses the
    same topic as a poll proxy rather than as a signal to interpret.
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
    age_minutes: str = "16",
    last_failure_kind: str = "get_exception",
) -> dict[str, str]:
    return {
        "severity": "CRITICAL",
        "event": "open_intent_stale",
        "site": "global",
        "intent_id": intent_id,
        "venue_order_id": venue_order_id,
        "age_minutes": age_minutes,
        "last_failure_kind": last_failure_kind,
    }


def test_the_watch_subscribes_the_shared_component_state_topic() -> None:
    """The same heartbeat as the degraded-alert watch -- no second topic."""
    assert COMPONENT_STATE_TOPIC == "events.system.*"


def test_an_empty_surface_never_alerts() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    install_stale_intent_alert(msgbus, stale_alerts=lambda: (), sink=sink)

    _tick(msgbus)
    _tick(msgbus)

    assert sink.payloads == []


def test_one_stale_entry_emits_one_alert_with_the_expected_fields() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface: tuple[dict[str, str], ...] = (_alert(),)
    install_stale_intent_alert(msgbus, stale_alerts=lambda: surface, sink=sink)

    _tick(msgbus)

    assert len(sink.payloads) == 1, sink.payloads
    payload = sink.payloads[0]
    assert payload.severity == STALE_INTENT_ALERT_SEVERITY == "CRITICAL"
    assert payload.event == STALE_INTENT_ALERT_EVENT == "open_intent_stale"
    assert payload.site == "global"
    assert "intent-1" in payload.detail
    assert "vo-1" in payload.detail
    assert "16" in payload.detail
    assert "get_exception" in payload.detail


def test_the_same_entry_on_a_later_poll_does_not_re_alert() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface: tuple[dict[str, str], ...] = (_alert(),)
    install_stale_intent_alert(msgbus, stale_alerts=lambda: surface, sink=sink)

    _tick(msgbus)
    _tick(msgbus)
    _tick(msgbus)

    assert len(sink.payloads) == 1, sink.payloads


def test_an_entry_that_disappears_is_forgotten_and_a_new_intent_alerts_again() -> None:
    """Retirement clears the client's own bookkeeping (`_retire`); the watch
    must mirror that rather than latching an intent id forever."""
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface: list[dict[str, str]] = [_alert(intent_id="intent-1")]
    install_stale_intent_alert(msgbus, stale_alerts=lambda: tuple(surface), sink=sink)

    _tick(msgbus)
    assert len(sink.payloads) == 1

    surface.clear()  # intent-1 retired
    _tick(msgbus)
    assert len(sink.payloads) == 1, "retirement must not itself alert"

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
    install_stale_intent_alert(msgbus, stale_alerts=_boom, sink=sink)

    _tick(msgbus)  # must not raise

    assert sink.payloads == []


def test_a_failing_sink_never_unwinds_into_the_message_bus() -> None:
    """`emit_alert` contains any sink failure; this is the proof the watch
    actually routes through it rather than calling `sink.emit` bare."""

    class _BrokenSink:
        def emit(self, payload: AlertPayload) -> None:
            raise RuntimeError("sink down")

    msgbus = _new_bus()
    install_stale_intent_alert(msgbus, stale_alerts=lambda: (_alert(),), sink=_BrokenSink())

    _tick(msgbus)  # must not raise
