"""EXEC-PAR BG-1b: the strict codec for the durable per-climate-day counter rows."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    DenialRow,
    ExecParRecordError,
    FillRow,
    GappyMark,
    OpenCostFlag,
    OrderAnchor,
    WindowPeak,
    decode_record,
    encode_record,
)

ANCHOR = OrderAnchor(
    client_order_id="O-1",
    slug="aec-nyc-high-2026-10-11-t70",
    day="2026-10-11",
    arm_ns=1_700_000_000_000_000_000,
    decision_ask="0.40",
    qty="10",
    notional="4.00",
    window_start_ns=1_700_000_000_000_000_000,
)
FILL = FillRow(
    trade_id="TR-1",
    client_order_id="O-1",
    day="2026-10-11",
    arm_ns=5,
    qty="10",
    px="0.41",
    decision_ask="0.40",
    slippage="0.01",
    fee_realized="0.17",
    fee_exact="0.1681545",
    fee_theta="0.0695",
)
ROWS = (
    ANCHOR,
    DenialRow(client_order_id="O-2", reason="k-full", day="2026-10-11", arm_ns=7),
    AmbiguousRow(
        intent_id="a1", source="unknown", day="2026-10-11", arm_ns=5, attribution="slot", ts_ns=9
    ),
    FILL,
    OpenCostFlag(station_day="NYC@2026-10-11", day="2026-10-11", exceeded=True, ts_ns=3),
    WindowPeak(day="2026-10-11", window_start_ns=5, orders=2, notional="8.00"),
    GappyMark(day="2026-10-11", cause="heartbeat_lapse", ts_ns=4, cleared_ts=None),
    GappyMark(day="2026-10-12", cause="heartbeat_lapse", ts_ns=4, cleared_ts=8),
)


@pytest.mark.parametrize("row", ROWS)
def test_round_trip_is_exact_and_bytes_are_canonical(row: object) -> None:
    raw = encode_record(row)
    assert decode_record(type(row), raw) == row
    assert encode_record(decode_record(type(row), raw)) == raw
    assert raw.startswith(b'{"')
    assert b'"v": 1' in raw


@pytest.mark.parametrize("row", ROWS)
def test_extra_missing_or_wrong_version_keys_are_refused(row: object) -> None:
    raw = encode_record(row)
    for bad in (
        raw.replace(b'"v": 1', b'"v": 2'),
        raw[:-1] + b',"extra":1}',
        b"[]",
        b"\xff",
    ):
        with pytest.raises(ExecParRecordError):
            decode_record(type(row), bad)


def test_none_and_empty_and_bool_as_int_never_coerce() -> None:
    nothing: Any = None
    one: Any = 1
    with pytest.raises(ExecParRecordError):
        encode_record(replace(ANCHOR, decision_ask=nothing))
    with pytest.raises(ExecParRecordError):
        encode_record(DenialRow(client_order_id="O", reason="", day="d", arm_ns=1))
    with pytest.raises(ExecParRecordError):
        encode_record(DenialRow(client_order_id="O", reason="r", day="d", arm_ns=True))
    with pytest.raises(ExecParRecordError):
        encode_record(OpenCostFlag(station_day="s", day="d", exceeded=one, ts_ns=1))
