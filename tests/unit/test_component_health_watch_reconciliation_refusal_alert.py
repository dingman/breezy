"""``install_reconciliation_refusal_alert``: deliver the exec client's latched
AUD-13b durable-reconciliation refusals through the existing alert path.

The Polymarket.us execution client may not import ``breezy.runtime.health``
(barrier E0-TRANSPORT), so it only RECORDS each named refusal on the read-only
``reconciliation_refusals`` surface. This runtime-side watch rides the SAME
``COMPONENT_STATE_TOPIC`` heartbeat as ``install_stale_intent_alert``: the
kernel publishes ``ComponentStateChanged`` for the ``OrderEmulator`` and the
trader AFTER the startup reconciliation returns (``system/kernel.py:1028-1039``),
so the first poll after the pass sees every refusal it latched -- no timer.

Plan: AUD-13 §6 -- WARN alert, ``event="reconciliation_refusal"``, ``detail`` a
fixed enum member, never an id or a date.
"""

from __future__ import annotations

from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.identifiers import ClientId, TraderId

from breezy.runtime.component_health_watch import (
    COMPONENT_STATE_TOPIC,
    RECONCILIATION_REFUSAL_ALERT_EVENT,
    RECONCILIATION_REFUSAL_ALERT_SEVERITY,
    install_reconciliation_refusal_alert,
)
from breezy.runtime.health import AlertPayload

TRADER_ID = TraderId("BREEZY-A13B-ALERT-001")


class _RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _new_bus() -> MessageBus:
    return MessageBus(trader_id=TRADER_ID, clock=LiveClock())


def _tick(msgbus: MessageBus) -> None:
    msgbus.publish(
        topic="events.system.OrderEmulator",
        msg=ComponentStateChanged(
            trader_id=TRADER_ID,
            component_id=ClientId("OrderEmulator"),
            component_type="OrderEmulator",
            state=ComponentState.RUNNING,
            config={},
            event_id=UUID4(),
            ts_event=0,
            ts_init=0,
        ),
    )


def _refusal(latch: str, detail: str, subject: str) -> dict[str, str]:
    return {
        "event": "reconciliation_refusal",
        "detail": detail,
        "latch": latch,
        "subject": subject,
    }


def test_the_watch_subscribes_the_shared_component_state_topic() -> None:
    msgbus = _new_bus()
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: (), sink=_RecordingSink())
    assert any(topic == COMPONENT_STATE_TOPIC for topic in msgbus.topics())


def test_no_refusal_emits_no_alert() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: (), sink=sink)
    _tick(msgbus)
    _tick(msgbus)
    assert sink.payloads == []


def test_one_refusal_emits_exactly_one_alert_with_a_fixed_enum_detail() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface = (_refusal("fee_coefficient_ambiguous", "FEE_COEFFICIENT_AMBIGUOUS", "CEBP…"),)
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: surface, sink=sink)

    _tick(msgbus)
    _tick(msgbus)
    _tick(msgbus)

    (payload,) = sink.payloads
    assert payload.event == RECONCILIATION_REFUSAL_ALERT_EVENT == "reconciliation_refusal"
    assert payload.severity == RECONCILIATION_REFUSAL_ALERT_SEVERITY
    assert payload.detail == "FEE_COEFFICIENT_AMBIGUOUS"
    assert "CEBP" not in f"{payload.detail}{payload.site}", "no id travels in the alert"


def test_each_distinct_refusal_alerts_once_and_a_new_one_later_still_alerts() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface = [
        _refusal("positions_read_failed", "POSITIONS_READ_FAILED", ""),
        _refusal("record_venue_disagreement", "RECORD_VENUE_DISAGREEMENT", "a.POLYMARKET_US"),
    ]
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: tuple(surface), sink=sink)

    _tick(msgbus)
    surface.append(
        _refusal("record_venue_disagreement", "RECORD_VENUE_DISAGREEMENT", "b.POLYMARKET_US")
    )
    _tick(msgbus)

    assert [p.detail for p in sink.payloads] == [
        "POSITIONS_READ_FAILED",
        "RECORD_VENUE_DISAGREEMENT",
        "RECORD_VENUE_DISAGREEMENT",
    ]


def test_an_unknown_detail_is_never_forwarded_verbatim() -> None:
    """The surface is trusted for its latch, not for free text: a detail
    outside the three ruled members is sent as the generic member."""
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface = (_refusal("positions_read_failed", "id=CEBPX0EVTTMX", ""),)
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: surface, sink=sink)
    _tick(msgbus)
    (payload,) = sink.payloads
    assert payload.detail == "RECONCILIATION_REFUSAL_UNKNOWN"


def test_a_durable_reports_build_failed_refusal_alerts_under_its_own_name() -> None:
    """AUD-13b review fix: the fourth latch (``durable_reports_build_failed``,
    added when the per-position build loop got its own catch) must reach the
    sink with ITS detail, never collapsed to the generic UNKNOWN member."""
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface = (
        _refusal(
            "durable_reports_build_failed", "DURABLE_REPORTS_BUILD_FAILED", "a.POLYMARKET_US"
        ),
    )
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: surface, sink=sink)
    _tick(msgbus)
    (payload,) = sink.payloads
    assert payload.detail == "DURABLE_REPORTS_BUILD_FAILED"


def test_a_resolver_fill_not_booked_refusal_alerts_under_its_own_name() -> None:
    """FU-8 r2/r2.1, test 8: the runtime-only, informational latch
    (`resolver_fill_not_booked`) reaches the sink with ITS OWN detail,
    never collapsed to the generic `RECONCILIATION_REFUSAL_UNKNOWN` member
    -- the same treatment every OTHER named refusal already gets, even
    though this one is never summed on the boot pass's own `refusals` line
    (`_BOOT_PASS_REFUSAL_LATCHES`, `exec/client.py`)."""
    msgbus = _new_bus()
    sink = _RecordingSink()
    surface = (
        _refusal("resolver_fill_not_booked", "RESOLVER_FILL_NOT_BOOKED", "ord…"),
    )
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: surface, sink=sink)
    _tick(msgbus)
    (payload,) = sink.payloads
    assert payload.detail == "RESOLVER_FILL_NOT_BOOKED"


def test_a_broken_surface_reader_does_not_crash_the_handler() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()

    def _boom() -> tuple[dict[str, str], ...]:
        raise RuntimeError("reader broke")

    install_reconciliation_refusal_alert(msgbus, refusals=_boom, sink=sink)
    _tick(msgbus)  # must not raise
    assert sink.payloads == []


def test_a_failing_sink_never_unwinds_into_the_message_bus() -> None:
    class _BrokenSink:
        def emit(self, payload: AlertPayload) -> None:
            raise RuntimeError("sink down")

    msgbus = _new_bus()
    surface = (_refusal("positions_read_failed", "POSITIONS_READ_FAILED", ""),)
    install_reconciliation_refusal_alert(msgbus, refusals=lambda: surface, sink=_BrokenSink())
    _tick(msgbus)  # must not raise
