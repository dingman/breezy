"""AUT-1 WP1 part A: the five ``@customdataclass`` capture records (plan r12 section 3.4.1)."""

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.persistence.funcs import class_to_filename
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer, list_schemas

from breezy.persistence.autonomy import capture_records
from breezy.persistence.autonomy.capture_records import (
    CAPTURE_RECORD_TYPES,
    NULL_STR,
    CaptureHeartbeat,
    DecisionRecord,
    DetectorEvent,
    FrameCopy,
    OrderEventRecord,
    make_record,
)

_S, _I, _B, _D = str, int, bool, dict

#: Section 3.4.1 table, verbatim. ``ts_event`` / ``ts_init`` are the decorator's own.
EXPECTED: dict[type, dict[str, type]] = {
    DecisionRecord: {
        "schema": _S, "decision_id": _S, "family_id": _S, "node_boot_id": _S, "build_sha": _S,
        "registry_seq": _I, "drill": _B, "source": _S, "kind": _S, "reason": _S,
        "eval_ns": _I, "eval_seq": _I, "wall_ns": _I, "station": _S, "climate_day": _S,
        "rung_id": _S, "side": _S, "instrument": _S, "ask_px": _S, "frame_kind": _S,
        "frame_ts_event": _I, "p_hat": _S, "p_hat_raw": _S, "p_lower": _S, "p_upper": _S,
        "ev_net": _S, "margin": _S, "forecast_station": _S, "forecast_cycle_ns": _I,
        "forecast_available_at_ns": _I, "artefact_sha256": _S, "manifest_sha256": _S,
    },
    FrameCopy: {
        "schema": _S, "decision_id": _S, "frame_kind": _S, "instrument": _S,
        "frame_ts_event": _I, "frame_body": _D,
    },
    OrderEventRecord: {
        "schema": _S, "decision_id": _S, "event_type": _S, "client_order_id": _S,
        "venue_order_id_sha256": _S, "reason": _S, "node_boot_id": _S, "drill": _B,
        "source": _S,
    },
    DetectorEvent: {
        "schema": _S, "detector": _S, "observation_sha256": _S, "state": _S,
        "node_boot_id": _S, "drill": _B, "source": _S,
    },
    CaptureHeartbeat: {
        "schema": _S, "node_boot_id": _S, "seq": _I, "final": _B, "records_written": _I,
        "written_by_type": _D, "write_failures": _I, "write_drops": _I, "health_ok": _B,
        "health_cause": _S,
    },
}  # fmt: skip


def _field_types(cls: type) -> dict[str, Any]:
    return {f.name: f.type for f in dataclasses.fields(cls)}


def test_capture_record_field_sets_are_exact() -> None:
    """Names AND types equal the section 3.4.1 table, so an added, dropped or retyped field fails.

    MUTATION: adding any field (for example ``intent_id``) or retyping ``eval_seq`` is red.
    """
    assert set(CAPTURE_RECORD_TYPES) == set(EXPECTED)
    for cls, expected in EXPECTED.items():
        assert _field_types(cls) == expected, cls.__name__


def test_no_capture_record_field_is_named_instrument_id() -> None:
    """ER-4: a field named ``instrument_id`` makes the native writer route per instrument and
    silently drop rows for an uncached instrument (``writer.py:210-239``)."""
    for cls in CAPTURE_RECORD_TYPES:
        names = {f.name for f in dataclasses.fields(cls)}
        assert "instrument_id" not in names, cls.__name__
        assert not hasattr(cls(), "instrument_id"), cls.__name__
    assert "instrument" in _field_types(DecisionRecord)
    assert "instrument" in _field_types(FrameCopy)


def test_null_encoding_is_empty_string_and_zero() -> None:
    """No ``Optional``: a default record carries ``""`` / ``0`` / ``False`` / ``{}`` everywhere."""
    assert NULL_STR == ""
    for cls in CAPTURE_RECORD_TYPES:
        record = cls()
        for name, annotation in _field_types(cls).items():
            value = getattr(record, name)
            expected = {str: "", int: 0, bool: False, dict: {}}[annotation]
            assert value == expected and type(value) is annotation, (cls.__name__, name)
        assert record.ts_event == 0 and record.ts_init == 0


def test_dict_defaults_are_not_shared_between_instances() -> None:
    first, second = (
        make_record(
            FrameCopy,
        ),
        make_record(
            FrameCopy,
        ),
    )
    first.frame_body["x"] = 1
    assert second.frame_body == {}
    beat_a, beat_b = (
        make_record(
            CaptureHeartbeat,
        ),
        make_record(
            CaptureHeartbeat,
        ),
    )
    beat_a.written_by_type["t"] = 1
    assert beat_b.written_by_type == {}


def test_records_round_trip_through_registered_arrow() -> None:
    """Every type is registered at import, serialises to one row and decodes back equal (the dict
    fields travel as canonical JSON strings)."""
    samples: list[Any] = [
        make_record(
            DecisionRecord,
            ts_event=11,
            ts_init=12,
            schema="capture_decision/v2",
            decision_id="d" * 32,
            registry_seq=3,
            drill=True,
            kind="Take",
            eval_ns=11,
            eval_seq=1,
            wall_ns=13,
            station="KLAX",
            instrument="tc-x.POLYMARKET_US",
            frame_kind="depth10",
            frame_ts_event=11,
            p_hat="0.31",
            margin="0.02",
            forecast_cycle_ns=5,
            forecast_available_at_ns=6,
        ),
        make_record(
            FrameCopy,
            ts_event=11,
            ts_init=12,
            schema="capture_frame_copy/v1",
            decision_id="d" * 32,
            frame_kind="quote",
            instrument="tc-x.POLYMARKET_US",
            frame_ts_event=11,
            frame_body={"ask": "0.15", "bid": "0.14", "ts_event": 11},
        ),
        make_record(
            OrderEventRecord,
            ts_event=1,
            ts_init=2,
            schema="s",
            event_type="OrderDenied",
            reason="r",
        ),
        make_record(DetectorEvent, ts_event=1, ts_init=2, schema="s", detector="md", state="AGREE"),
        make_record(
            CaptureHeartbeat,
            ts_event=9,
            ts_init=9,
            schema="h",
            seq=4,
            final=True,
            records_written=7,
            written_by_type={"custom_decision_record": 5, "order_filled": 2},
            health_ok=True,
        ),
    ]
    assert {type(s) for s in samples} == set(CAPTURE_RECORD_TYPES)
    for sample in samples:
        cls = type(sample)
        assert cls in list_schemas(), cls.__name__
        batch = ArrowSerializer.serialize_batch([sample], data_cls=cls)
        assert batch.num_rows == 1
        [decoded] = ArrowSerializer.deserialize(cls, batch)
        assert decoded.to_dict() == sample.to_dict(), cls.__name__
        assert decoded.ts_event == sample.ts_event and decoded.ts_init == sample.ts_init


def test_table_names_and_class_names_are_unique() -> None:
    tables = {class_to_filename(cls) for cls in CAPTURE_RECORD_TYPES}
    assert tables == {
        "custom_decision_record",
        "custom_frame_copy",
        "custom_order_event_record",
        "custom_detector_event",
        "custom_capture_heartbeat",
    }
    assert len({cls.__name__ for cls in CAPTURE_RECORD_TYPES}) == 5


def test_schema_strings_are_versioned() -> None:
    assert capture_records.DECISION_SCHEMA == "capture_decision/v2"
    assert capture_records.FRAME_COPY_SCHEMA == "capture_frame_copy/v1"
    assert capture_records.ORDER_EVENT_SCHEMA == "capture_order_event/v1"
    assert capture_records.DETECTOR_SCHEMA == "capture_detector_event/v2"
    assert capture_records.HEARTBEAT_SCHEMA == "capture_heartbeat/v1"
    versioned = {
        capture_records.DECISION_SCHEMA,
        capture_records.FRAME_COPY_SCHEMA,
        capture_records.ORDER_EVENT_SCHEMA,
        capture_records.DETECTOR_SCHEMA,
        capture_records.HEARTBEAT_SCHEMA,
    }
    assert all(s.rsplit("/v", 1)[1].isdigit() for s in versioned)


def test_closed_vocabularies_match_the_plan() -> None:
    assert capture_records.DECISION_KINDS == (
        "Take", "Refuse", "NotExecutable", "NotDPlus1", "TrySubmit", "EntryVeto", "Exit",
    )  # fmt: skip
    assert capture_records.SOURCES == ("live", "canary")
    assert capture_records.DETECTOR_STATES == ("AGREE", "DISAGREE", "UNKNOWN")
    assert capture_records.FRAME_KINDS == ("depth10", "quote", "")


def test_record_module_has_no_future_annotations() -> None:
    """WP0 finding: stringified annotations make ``@customdataclass`` raise."""
    tree = ast.parse(Path(capture_records.__file__).read_text(encoding="utf-8"))
    future = [
        n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "__future__"
    ]
    assert future == []


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(TypeError):
        make_record(DecisionRecord, intent_id="x")
