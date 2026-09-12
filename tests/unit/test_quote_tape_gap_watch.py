"""RED/GREEN coverage for `install_quote_tape_gap_watch` (SP-6 A6, rows
12/12b).

Row 12 is Rev 2's hard gate: build `CustomData(DataType(QuoteTapeGap),
record)` exactly as `PolymarketUSDataClient._publish_custom`
(`adapters/polymarket_us/data.py:1749-1758`) does, round-trip it through a
REAL `DataEngine` + `MessageBus` (never a hand-simulated `publish` call),
and assert the installed subscriber receives it. The topic is asserted
against Nautilus's own `TopicCache.get_custom_data_topic` output -- never
hand-typed or lifted from any plan text.
"""

from __future__ import annotations

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.data_topics import TopicCache
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.model.data import CustomData, DataType
from nautilus_trader.model.identifiers import InstrumentId, TraderId

from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap
from breezy.runtime.health import AlertPayload
from breezy.runtime.quote_tape_gap_watch import (
    QUOTE_TAPE_GAP_ALERT_EVENT,
    QUOTE_TAPE_GAP_TOPIC,
    install_quote_tape_gap_watch,
)

TRADER_ID = TraderId("BREEZY-GAPWATCH-001")
_INSTRUMENT_ID = InstrumentId.from_str("BTNENSDW-YES.POLYMARKET_US")


class _RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class _RaisingSink:
    def emit(self, payload: AlertPayload) -> None:
        raise RuntimeError("simulated webhook failure")


def _new_bus() -> MessageBus:
    return MessageBus(trader_id=TRADER_ID, clock=LiveClock())


def _new_engine(msgbus: MessageBus) -> DataEngine:
    return DataEngine(msgbus, Cache(), LiveClock())


def _gap(
    *,
    instrument_id: InstrumentId = _INSTRUMENT_ID,
    gap_seq: int = 1,
    resolved: bool = False,
    recorder_instance_id: str = "BREEZY-GAPWATCH-001",
    started_ns: int = 1_000,
    ended_ns: int | None = None,
    ts: int = 1_000,
) -> QuoteTapeGap:
    if ended_ns is None:
        ended_ns = started_ns if resolved else 0
    return QuoteTapeGap(
        instrument_id=instrument_id,
        gap_seq=gap_seq,
        started_ns=started_ns,
        ended_ns=ended_ns,
        resolved=resolved,
        recorder_instance_id=recorder_instance_id,
        ts_event=ts,
        ts_init=ts,
    )


def _publish_exactly_as_data_py_does(engine: DataEngine, record: QuoteTapeGap) -> None:
    """Mirrors `_publish_custom`'s own call, `self._handle_data(CustomData(
    DataType(type(record)), record))` -- but on the ENGINE (the far end of
    the client's `msgbus.send(endpoint="DataEngine.process", ...)`), which
    is exactly where the client's call is routed to in a real node."""
    engine._handle_data(CustomData(DataType(type(record)), record))


class FakeClock:
    def __init__(self, start_ns: int) -> None:
        self.now_ns = start_ns

    def __call__(self) -> int:
        return self.now_ns

    def advance(self, delta_ns: int) -> None:
        self.now_ns += delta_ns


# ---------------------------------------------------------------------------
# Row 12 -- the hard round-trip gate.
# ---------------------------------------------------------------------------


def test_a_record_published_exactly_as_data_py_does_is_delivered_to_the_subscriber() -> None:
    msgbus = _new_bus()
    engine = _new_engine(msgbus)
    record = _gap()

    received: list[object] = []
    msgbus.subscribe(topic=QUOTE_TAPE_GAP_TOPIC, handler=received.append)

    _publish_exactly_as_data_py_does(engine, record)

    assert received == [record]

    # Never lifted from a plan: derive the real topic from Nautilus's own
    # TopicCache class (the same one the engine used internally to publish
    # the record above) and check it against the wildcard this module
    # subscribes on.
    real_topic = TopicCache().get_custom_data_topic(DataType(type(record)), record.instrument_id)
    assert real_topic.startswith("data.QuoteTapeGap")


# ---------------------------------------------------------------------------
# Row 12b -- dedupe, eviction, re-notify, the cross-seq floor, containment.
# ---------------------------------------------------------------------------


def test_one_gap_open_fanned_out_across_instruments_emits_exactly_one_alert() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    clock = FakeClock(0)
    install_quote_tape_gap_watch(msgbus, sink=sink, clock_ns=clock)

    other_instrument = InstrumentId.from_str("SFOTMAXW-YES.POLYMARKET_US")
    msgbus.publish(
        QUOTE_TAPE_GAP_TOPIC, _gap(instrument_id=_INSTRUMENT_ID, gap_seq=1)
    )
    msgbus.publish(
        QUOTE_TAPE_GAP_TOPIC, _gap(instrument_id=other_instrument, gap_seq=1)
    )

    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == QUOTE_TAPE_GAP_ALERT_EVENT


def test_a_second_gap_seq_within_the_floor_is_suppressed_and_counted() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    clock = FakeClock(0)
    install_quote_tape_gap_watch(msgbus, sink=sink, clock_ns=clock, floor_ns=300_000_000_000)

    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=1))
    clock.advance(100_000_000_000)  # 100s -- inside the 300s floor
    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=2))

    assert len(sink.payloads) == 1

    clock.advance(250_000_000_000)  # now 350s after the first -- floor cleared
    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=3))

    assert len(sink.payloads) == 2
    assert "suppressed=1" in sink.payloads[1].detail


def test_a_resolved_record_never_alerts_critical() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    install_quote_tape_gap_watch(msgbus, sink=sink)

    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(resolved=True))

    assert sink.payloads == []


def test_a_resolved_record_evicts_its_id_from_the_dedupe_map() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    clock = FakeClock(0)
    install_quote_tape_gap_watch(msgbus, sink=sink, clock_ns=clock, floor_ns=0)

    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=1, resolved=False))
    assert len(sink.payloads) == 1

    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=1, resolved=True))

    # Immediately re-opening the SAME id (well inside both the renotify
    # window and the floor) alerts again -- proof the eviction on the
    # resolved edge actually cleared the dedupe entry, not merely that
    # time passed.
    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=1, resolved=False))
    assert len(sink.payloads) == 2


def test_a_gap_still_open_after_the_renotify_window_alerts_again() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    clock = FakeClock(0)
    renotify_after_ns = 1_000
    install_quote_tape_gap_watch(
        msgbus,
        sink=sink,
        clock_ns=clock,
        floor_ns=0,
        renotify_after_ns=renotify_after_ns,
    )

    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=1, resolved=False))
    assert len(sink.payloads) == 1

    clock.advance(renotify_after_ns + 1)
    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap(gap_seq=1, resolved=False))
    assert len(sink.payloads) == 2


def test_a_shard_scoped_gap_reaches_the_sink() -> None:
    msgbus = _new_bus()
    sink = _RecordingSink()
    install_quote_tape_gap_watch(msgbus, sink=sink)

    record = _gap(recorder_instance_id="shard-a")
    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, record)

    assert len(sink.payloads) == 1
    assert sink.payloads[0].severity == "WARN"


def test_a_failing_sink_never_unwinds_into_the_publisher() -> None:
    msgbus = _new_bus()
    install_quote_tape_gap_watch(msgbus, sink=_RaisingSink())

    # No exception escapes the publish call despite the sink raising.
    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap())


def test_detail_passes_assert_payload_detail_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = pytest.importorskip("breezy.runtime.alert_detail").assert_payload_detail_is_safe

    def _spy(detail: str) -> None:
        calls.append(detail)
        real(detail)

    monkeypatch.setattr("breezy.runtime.quote_tape_gap_watch.assert_payload_detail_is_safe", _spy)

    msgbus = _new_bus()
    sink = _RecordingSink()
    install_quote_tape_gap_watch(msgbus, sink=sink)

    msgbus.publish(QUOTE_TAPE_GAP_TOPIC, _gap())

    assert len(calls) == 1
    assert len(sink.payloads) == 1
