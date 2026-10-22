"""ARM B7: delivery of the resting-order alert surfaces (S4 r4 WP6 / ARM r1 row B7).

The execution client RECORDS value-free CRITICAL entries on ``resting_cancel_alerts`` and
``resting_commission_alerts`` (it may not import the alert sink: barrier E0-TRANSPORT). A
detector with no subscriber is not a control (the 2026-09-20 alerts-reach-nobody incident), so
``install_resting_alert`` is the SAME idiom as ``install_resolver_contradiction_alert``: the
shared ``COMPONENT_STATE_TOPIC`` heartbeat plus the re-poll timer, one dedupe set, no new unit.

``resting_no_id_fill_while_down`` is carried by the resolver-contradiction surface (its
``reason`` token), so it is delivered by the existing contradiction watch; one test pins that.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.identifiers import ClientId, TraderId

from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.runtime import trade_cli
from breezy.runtime.component_health_watch import (
    RESTING_ALERT_SEVERITY,
    RESTING_ALERT_SITE,
    install_resolver_contradiction_alert,
    install_resting_alert,
)
from breezy.runtime.health import AlertPayload
from tests.unit.ambig_latch_rig import PolymarketUSExecutionClient

TRADER_ID = TraderId("BREEZY-RESTING-001")
RESTING_EVENTS = (
    "resting_cancel_alert",
    "commission_bps_drift",
    "resting_commission_out_of_envelope",
    "commission_unreadable",
    "resting_fill_mismatch",
)


class _RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _bus() -> MessageBus:
    return MessageBus(trader_id=TRADER_ID, clock=LiveClock())


def _tick(msgbus: MessageBus) -> None:
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


def _entry(event: str, *, vid: str = "ABCD...1234", **extra: str) -> dict[str, str]:
    return {
        "severity": "CRITICAL",
        "event": event,
        "venue_order_id": vid,
        "slug": "tc-temp-nychigh-2026-10-23-lt71f",
        "next": "new_rests_refused_cancels_continue_restart_after_review_clears",
        **extra,
    }


def test_an_empty_surface_never_alerts() -> None:
    bus, sink = _bus(), _RecordingSink()
    install_resting_alert(bus, alerts=lambda: (), sink=sink)
    _tick(bus)
    assert sink.payloads == []


@pytest.mark.parametrize("event", RESTING_EVENTS)
def test_each_resting_event_is_delivered_once_as_critical_under_its_own_event(event: str) -> None:
    bus, sink = _bus(), _RecordingSink()
    surface = (_entry(event),)
    install_resting_alert(bus, alerts=lambda: surface, sink=sink)
    _tick(bus)
    _tick(bus)
    assert len(sink.payloads) == 1, sink.payloads
    payload = sink.payloads[0]
    assert payload.severity == RESTING_ALERT_SEVERITY == "CRITICAL"
    assert payload.event == event
    assert payload.site == RESTING_ALERT_SITE == "global"
    assert "ABCD...1234" in payload.detail
    assert "tc-temp-nychigh-2026-10-23-lt71f" in payload.detail


def test_distinct_orders_and_events_alert_separately() -> None:
    bus, sink = _bus(), _RecordingSink()
    surface = (
        _entry("commission_unreadable", vid="A"),
        _entry("commission_unreadable", vid="B"),
        _entry("resting_fill_mismatch", vid="A"),
    )
    install_resting_alert(bus, alerts=lambda: surface, sink=sink)
    _tick(bus)
    assert len(sink.payloads) == 3


def test_a_cancel_re_alert_with_a_new_age_is_delivered_again() -> None:
    """The client re-alerts a still-open cancel every RETRY_REALERT_S with a new ``age_s``."""
    bus, sink = _bus(), _RecordingSink()
    state: dict[str, tuple[Mapping[str, str], ...]] = {
        "now": (_entry("resting_cancel_alert", age_s="600"),)
    }
    install_resting_alert(bus, alerts=lambda: state["now"], sink=sink)
    _tick(bus)
    _tick(bus)
    state["now"] = (_entry("resting_cancel_alert", age_s="2400"),)
    _tick(bus)
    assert len(sink.payloads) == 2
    assert "2400" in sink.payloads[1].detail


def test_a_cleared_entry_is_forgotten_so_a_later_one_alerts_again() -> None:
    bus, sink = _bus(), _RecordingSink()
    state: dict[str, tuple[Mapping[str, str], ...]] = {"now": (_entry("commission_unreadable"),)}
    install_resting_alert(bus, alerts=lambda: state["now"], sink=sink)
    _tick(bus)
    state["now"] = ()
    _tick(bus)
    state["now"] = (_entry("commission_unreadable"),)
    _tick(bus)
    assert len(sink.payloads) == 2


def test_a_broken_reader_never_raises_into_the_bus() -> None:
    bus, sink = _bus(), _RecordingSink()

    def _boom() -> tuple[Mapping[str, str], ...]:
        raise RuntimeError("reader down")

    install_resting_alert(bus, alerts=_boom, sink=sink)
    _tick(bus)
    assert sink.payloads == []


def test_an_unknown_event_is_sent_under_the_generic_name_never_its_free_text() -> None:
    bus, sink = _bus(), _RecordingSink()
    surface = (_entry("surprise_event_with_values_12.34"),)
    install_resting_alert(bus, alerts=lambda: surface, sink=sink)
    _tick(bus)
    assert [p.event for p in sink.payloads] == ["resting_alert_unknown"]
    assert "12.34" not in sink.payloads[0].detail


def test_the_detail_carries_only_closed_keys_and_never_a_commission_figure() -> None:
    """Value-free: a stray ``commission`` / ``venue_fee_raw`` key (or a value that is not a
    plain token) on an entry never reaches the sink."""
    bus, sink = _bus(), _RecordingSink()
    surface = (
        _entry(
            "commission_unreadable",
            commission="-0.0123",
            venue_fee_raw="-0.0123",
            fields="commissionBps,feeBps",
        ),
        _entry("resting_fill_mismatch", vid="Z", next="booked at -0.0456 USD, see order"),
    )
    install_resting_alert(bus, alerts=lambda: surface, sink=sink)
    _tick(bus)
    text = " ".join(p.detail for p in sink.payloads)
    assert "0.0123" not in text
    assert "0.0456" not in text
    assert "commissionBps,feeBps" in text


def test_the_no_id_fill_while_down_entry_is_delivered_by_the_contradiction_watch() -> None:
    bus, sink = _bus(), _RecordingSink()
    surface = (
        {
            "severity": "CRITICAL",
            "event": "resolver_evidence_contradiction",
            "site": "global",
            "intent_id": "intent-1",
            "venue_order_id": "none",
            "no_id": "true",
            "reason": "resting_no_id_fill_while_down",
            "next": "operator_clear_after_review",
        },
    )
    install_resolver_contradiction_alert(bus, contradictions=lambda: surface, sink=sink)
    _tick(bus)
    assert len(sink.payloads) == 1
    assert "resting_no_id_fill_while_down" in sink.payloads[0].detail


def test_the_exec_client_exposes_both_resting_surfaces_the_readers_read() -> None:
    assert isinstance(PolymarketUSExecutionClient.resting_cancel_alerts, property)
    assert isinstance(PolymarketUSExecutionClient.resting_commission_alerts, property)


def test_the_trade_cli_reader_joins_both_client_surfaces_at_poll_time() -> None:
    cancel = _entry("resting_cancel_alert", age_s="600")
    commission = _entry("commission_unreadable")
    clients: dict[object, object] = {}
    node = SimpleNamespace(kernel=SimpleNamespace(exec_engine=SimpleNamespace(_clients=clients)))
    read = trade_cli._exec_client_resting_alert_reader(node)

    assert read() == ()
    clients[ClientId(POLYMARKET_US_CLIENT_NAME)] = SimpleNamespace()
    assert read() == ()
    clients[ClientId(POLYMARKET_US_CLIENT_NAME)] = SimpleNamespace(
        resting_cancel_alerts=(cancel,), resting_commission_alerts=(commission,)
    )
    assert read() == (cancel, commission)


# ------------------------------------------------------------ B7 review T3 / P-3 / P-2


def test_a_non_string_value_never_raises_out_of_the_handler_and_other_alerts_still_go() -> None:
    """T3: the msgbus handler must not raise on a malformed entry (non-str values, a non-mapping
    entry); a good entry in the same poll is still delivered."""
    bus, sink = _bus(), _RecordingSink()
    surface: tuple[Any, ...] = (
        _entry("resting_cancel_alert", vid="OK1"),
        {"event": "commission_unreadable", "venue_order_id": 12345, "age_s": None, "slug": 7},
        "not-a-mapping",
        _entry("resting_fill_mismatch", vid="OK2"),
    )
    handler = install_resting_alert(bus, alerts=lambda: surface, sink=sink)
    handler(None)  # direct call: a raise here would propagate into the publishing component
    delivered = {p.event for p in sink.payloads}
    assert {"resting_cancel_alert", "resting_fill_mismatch"} <= delivered, sink.payloads
    count = len(sink.payloads)
    handler(None)
    assert len(sink.payloads) == count, "a second poll adds nothing"


def test_alerts_differing_only_in_fields_or_next_are_not_collapsed() -> None:
    """P-3: the dedupe key covers every forwarded detail key, so a changed ``fields`` or ``next``
    on the same order is a new alert."""
    bus, sink = _bus(), _RecordingSink()
    surface = (
        _entry("commission_unreadable", fields="commissionBps"),
        _entry("commission_unreadable", fields="feeBps"),
        _entry("resting_fill_mismatch", next="review_a"),
        _entry("resting_fill_mismatch", next="review_b"),
    )
    install_resting_alert(bus, alerts=lambda: surface, sink=sink)
    _tick(bus)
    assert len(sink.payloads) == 4, [p.detail for p in sink.payloads]


def test_distinct_unknown_events_are_not_collapsed_into_one_generic_alert() -> None:
    """P-3: two different raw events that both map to the generic name stay two alerts."""
    bus, sink = _bus(), _RecordingSink()
    surface = (_entry("surprise_one"), _entry("surprise_two"))
    install_resting_alert(bus, alerts=lambda: surface, sink=sink)
    _tick(bus)
    assert [p.event for p in sink.payloads] == ["resting_alert_unknown"] * 2


def test_the_trade_cli_reader_does_not_hide_an_attribute_error_raised_inside_the_property() -> None:
    """P-2: ``getattr(client, name, ())`` swallowed an AttributeError raised INSIDE the property
    and read it as "no alerts". A declared surface that blows up must reach the caller."""

    class _Client:
        @property
        def resting_cancel_alerts(self) -> tuple[Mapping[str, str], ...]:
            raise AttributeError("inner bug")

        resting_commission_alerts = ()

    clients: dict[object, object] = {ClientId(POLYMARKET_US_CLIENT_NAME): _Client()}
    node = SimpleNamespace(kernel=SimpleNamespace(exec_engine=SimpleNamespace(_clients=clients)))
    with pytest.raises(AttributeError, match="inner bug"):
        trade_cli._exec_client_resting_alert_reader(node)()


def test_a_failing_surface_reaches_logger_exception_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from breezy.runtime import component_health_watch as watch

    logged: list[str] = []
    monkeypatch.setattr(watch.logger, "exception", lambda msg, *a, **k: logged.append(msg))

    class _Client:
        @property
        def resting_cancel_alerts(self) -> tuple[Mapping[str, str], ...]:
            raise AttributeError("inner bug")

        resting_commission_alerts = ()

    clients: dict[object, object] = {ClientId(POLYMARKET_US_CLIENT_NAME): _Client()}
    node = SimpleNamespace(kernel=SimpleNamespace(exec_engine=SimpleNamespace(_clients=clients)))
    bus, sink = _bus(), _RecordingSink()
    install_resting_alert(bus, alerts=trade_cli._exec_client_resting_alert_reader(node), sink=sink)
    _tick(bus)
    assert sink.payloads == []
    assert len(logged) == 1
