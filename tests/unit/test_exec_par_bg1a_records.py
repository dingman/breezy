"""EXEC-PAR BG-1a: the pure durable-record codec round-trips and fails closed."""

from __future__ import annotations

import json
from typing import Any

import pytest

from breezy.runtime.exec_par_records import (
    Amendment,
    CleanupDemotion,
    EpochRow,
    ExcludedDay,
    ExecParRecordError,
    ForceK1Cleared,
    ForceK1Flag,
    StageEvalDry,
    StageReset,
    StopVerdict,
    decode_excluded_days,
    decode_force_k1_flag,
    decode_pointer,
    decode_record,
    encode_excluded_days,
    encode_force_k1_tombstone,
    encode_pointer,
    encode_record,
)
from breezy.runtime.submit_intent_slots import SlotTableError

SAMPLES: list[object] = [
    StageReset(ts=5, cause="stop_clear", halt_ts=4),
    StageReset(ts=5, cause="k_change", halt_ts=None),
    EpochRow(commit_sha="abc123", effective_k=2, force_reason=None, boot_ts=9),
    EpochRow(commit_sha="abc123", effective_k=1, force_reason="flag", boot_ts=9, stop_ts=10),
    Amendment(ts_ns=3, commit_sha="abc", note="A1"),
    StageEvalDry(verdict="PASS", input_complete=True, ts=7),
    StageEvalDry(verdict="FAIL", input_complete=False, ts=7),
    ForceK1Cleared(ts=8, halt_ts=4, incident_report="docs/x.md"),
    StopVerdict(reason="s5_cp", ts_ns=11),
    CleanupDemotion(from_k=4, to_k=2, ts_ns=12, reason="low_volume"),
    ForceK1Flag(reason="s5_cp", ts_ns=13, set_by="watcher"),
]


@pytest.mark.parametrize("record", SAMPLES, ids=lambda r: type(r).__name__)
def test_record_round_trips_and_bytes_are_deterministic(record: object) -> None:
    raw = encode_record(record)
    assert decode_record(type(record), raw) == record
    assert encode_record(decode_record(type(record), raw)) == raw
    assert raw == json.dumps(json.loads(raw), sort_keys=True).encode()


@pytest.mark.parametrize("record", SAMPLES, ids=lambda r: type(r).__name__)
@pytest.mark.parametrize(
    "garbage",
    [b"", b"\xff\xfe", b"not json", b"[]", b"null", b'{"v":2}', b'{"v":true}', b"{}"],
)
def test_garbled_bytes_raise_typed_error_never_a_default(record: object, garbage: bytes) -> None:
    with pytest.raises(ExecParRecordError):
        decode_record(type(record), garbage)


def test_error_is_a_slot_table_error_so_existing_mapping_applies() -> None:
    assert issubclass(ExecParRecordError, SlotTableError)


def test_extra_missing_or_wrongly_typed_fields_are_rejected() -> None:
    good = json.loads(encode_record(StopVerdict(reason="r", ts_ns=1)))
    for bad in (
        {**good, "extra": 1},
        {k: v for k, v in good.items() if k != "reason"},
        {**good, "ts_ns": True},
        {**good, "ts_ns": "1"},
        {**good, "ts_ns": 1.5},
        {**good, "reason": ""},
        {**good, "reason": None},
    ):
        with pytest.raises(ExecParRecordError):
            decode_record(StopVerdict, json.dumps(bad).encode())


def test_encode_refuses_invalid_fields() -> None:
    wrong: Any = 1
    with pytest.raises(ExecParRecordError):
        encode_record(StopVerdict(reason="", ts_ns=1))
    with pytest.raises(ExecParRecordError):
        encode_record(StageEvalDry(verdict="PASS", input_complete=wrong, ts=1))
    with pytest.raises(ExecParRecordError):
        encode_record(object())


def test_decode_rejects_unknown_record_class() -> None:
    with pytest.raises(ExecParRecordError):
        decode_record(dict, b'{"v":1}')


def test_pointer_round_trip_and_garbage() -> None:
    assert decode_pointer(encode_pointer(42)) == 42
    for bad in (b"", b'{"v":1}', b'{"v":1,"ts_ns":"x"}', b'{"v":1,"ts_ns":1,"z":1}'):
        with pytest.raises(ExecParRecordError):
            decode_pointer(bad)


def test_excluded_days_round_trip_sorted_and_rejects_duplicates() -> None:
    days = (ExcludedDay("2026-12-02", "unreconciled", 2), ExcludedDay("2026-12-01", "gappy", 1))
    raw = encode_excluded_days(days)
    assert decode_excluded_days(raw) == tuple(sorted(days, key=lambda d: d.day))
    assert encode_excluded_days(decode_excluded_days(raw)) == raw
    assert decode_excluded_days(encode_excluded_days(())) == ()
    dup = json.dumps(
        {"v": 1, "days": [{"day": "d", "cause": "c", "ts": 1}, {"day": "d", "cause": "c", "ts": 2}]}
    ).encode()
    for bad in (b"", b"{}", b'{"v":1,"days":{}}', b'{"v":1,"days":[1]}', dup):
        with pytest.raises(ExecParRecordError):
            decode_excluded_days(bad)


def test_force_k1_flag_set_cleared_and_garbled() -> None:
    flag = ForceK1Flag(reason="r", ts_ns=1, set_by="w")
    assert decode_force_k1_flag(encode_record(flag)) == flag
    assert decode_force_k1_flag(encode_force_k1_tombstone(5)) is None
    for bad in (b"", b'{"v":1}', b'{"v":1,"cleared_ts_ns":"x"}', b"garbage"):
        with pytest.raises(ExecParRecordError):
            decode_force_k1_flag(bad)
