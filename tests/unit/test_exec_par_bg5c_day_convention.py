"""EXEC-PAR BG-5c WP-C: the ``exec_par/day_convention {v:2}`` row and the station-carrying rows."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.exec_par_day_convention import (
    DAY_CONVENTION_REASON,
    DayConventionDetail,
    enforce_day_convention_at_boot,
)
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    AmbiguousRow,
    DenialRow,
    ExecParRecordError,
    FillRow,
    OrderAnchor,
    decode_day_convention,
    decode_record,
    encode_day_convention,
    encode_record,
)
from breezy.runtime.submit_intent import open_submit_intent_latch

# -- the codec -----------------------------------------------------------------------------------


def test_day_convention_row_is_exactly_v2() -> None:
    assert json.loads(encode_day_convention()) == {"v": 2}
    assert decode_day_convention(encode_day_convention()) == 2


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'{"v": 2, "extra": 1}',
        b'{"v": true}',
        b'{"v": "2"}',
        b'{"w": 2}',
        b"{}",
    ],
)
def test_day_convention_decode_is_strict(raw: bytes) -> None:
    with pytest.raises(ExecParRecordError):
        decode_day_convention(raw)


def test_day_convention_decode_reports_a_foreign_version_instead_of_hiding_it() -> None:
    assert decode_day_convention(b'{"v": 1}') == 1
    assert decode_day_convention(b'{"v": 3}') == 3


SAMPLES: tuple[Any, ...] = (
    OrderAnchor("O-1", "slug", "2026-10-11", 5, "0.40", "10", "4", 5, "event_time", "MIA"),
    DenialRow("O-2", "k-full", "2026-10-11", 7, "MIA"),
    AmbiguousRow("a1", "armed_pre_boot", "2026-10-11", 5, "slot", 9, "MIA"),
    FillRow(
        "T-1",
        "O-1",
        "2026-10-11",
        5,
        "10",
        "0.41",
        "0.40",
        "0.01",
        "0.17",
        "0.168",
        "0.0695",
        "MIA",
    ),
)


@pytest.mark.parametrize("row", SAMPLES, ids=lambda r: type(r).__name__)
def test_every_per_entry_row_round_trips_with_its_station(row: Any) -> None:
    assert decode_record(type(row), encode_record(row)) == row
    assert json.loads(encode_record(row))["station"] == "MIA"


@pytest.mark.parametrize("row", SAMPLES, ids=lambda r: type(r).__name__)
def test_decoding_an_old_row_without_a_station_fails_loudly(row: Any) -> None:
    payload = json.loads(encode_record(row))
    del payload["station"]
    with pytest.raises(ExecParRecordError):
        decode_record(type(row), json.dumps(payload, sort_keys=True).encode())


@pytest.mark.parametrize("row", SAMPLES, ids=lambda r: type(r).__name__)
def test_an_empty_or_non_text_station_is_refused_on_encode(row: Any) -> None:
    with pytest.raises(ExecParRecordError):
        encode_record(replace(row, station=""))
    with pytest.raises(ExecParRecordError):
        encode_record(replace(row, station=None))


# -- the boot check -------------------------------------------------------------------------


class _Sink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, payload: Any) -> None:
        self.events.append(payload)


class _FakeLatch:
    def __init__(
        self,
        *,
        slots: int,
        row: int | None = None,
        read_raises: bool = False,
        write_raises: bool = False,
    ) -> None:
        self.slots = slots
        self.row = row
        self.read_raises = read_raises
        self.write_raises = write_raises
        self.calls: list[str] = []
        self.forced: list[str] = []

    def max_slots(self) -> int:
        return self.slots

    def read_day_convention(self) -> int | None:
        self.calls.append("read")
        if self.read_raises:
            raise OSError("read")
        return self.row

    def write_day_convention(self) -> bool:
        self.calls.append("write")
        if self.write_raises:
            raise OSError("write")
        self.row = 2
        return True

    def force_k1(self, reason: str) -> None:
        self.forced.append(reason)


def _alerts(sink: Any) -> list[tuple[str, str]]:
    return [(p.severity, p.detail) for p in sink.events]


def test_k1_boot_touches_nothing() -> None:
    latch, sink = _FakeLatch(slots=1), _Sink()
    assert enforce_day_convention_at_boot(latch, alert_sink=sink) is False
    assert latch.calls == [] and latch.forced == [] and sink.events == []


def test_the_first_k_gt1_boot_writes_the_v2_row_and_does_not_force() -> None:
    latch, sink = _FakeLatch(slots=2), _Sink()
    assert enforce_day_convention_at_boot(latch, alert_sink=sink) is False
    assert latch.row == 2 and latch.calls == ["read", "write"]
    assert latch.forced == [] and sink.events == []


def test_a_matching_v2_row_is_left_alone() -> None:
    latch, sink = _FakeLatch(slots=4, row=2), _Sink()
    assert enforce_day_convention_at_boot(latch, alert_sink=sink) is False
    assert latch.calls == ["read"] and latch.forced == [] and sink.events == []


@pytest.mark.parametrize("version", [1, 3, 99])
def test_a_foreign_version_refuses_k_gt1_with_a_critical_alert(version: int) -> None:
    latch, sink = _FakeLatch(slots=2, row=version), _Sink()
    assert enforce_day_convention_at_boot(latch, alert_sink=sink) is True
    assert latch.forced == [DAY_CONVENTION_REASON]
    assert _alerts(sink) == [("CRITICAL", DayConventionDetail.MISMATCH.value)]
    assert latch.row == version  # never overwritten


def test_an_unreadable_row_forces_k1_alerts_then_reraises() -> None:
    latch, sink = _FakeLatch(slots=2, read_raises=True), _Sink()
    with pytest.raises(OSError):
        enforce_day_convention_at_boot(latch, alert_sink=sink)
    assert latch.forced and _alerts(sink) == [("CRITICAL", DayConventionDetail.UNREADABLE.value)]


def test_a_failed_first_write_forces_k1_alerts_then_reraises() -> None:
    latch, sink = _FakeLatch(slots=2, write_raises=True), _Sink()
    with pytest.raises(OSError):
        enforce_day_convention_at_boot(latch, alert_sink=sink)
    assert latch.forced and _alerts(sink) == [("CRITICAL", DayConventionDetail.WRITE_FAILED.value)]


def test_the_real_latch_round_trips_the_row_and_pins_the_key(tmp_path: Path) -> None:
    class Store:
        def __init__(self) -> None:
            self.data: dict[str, bytes] = {}

        def get(self, key: str) -> bytes | None:
            return self.data.get(key)

        def set(self, key: str, value: bytes) -> None:
            self.data[key] = value

        def keys_with_prefix(self, prefix: str) -> list[str]:
            return sorted(k for k in self.data if k.startswith(prefix))

        def delete(self, key: str) -> bool:
            return self.data.pop(key, None) is not None

    store = Store()
    with open_submit_intent_latch(
        store, tmp_path / "s.db", max_slots=2, v2_predicate=lambda: True, clock_ns=lambda: 1
    ) as latch:
        assert latch.read_day_convention() is None
        assert latch.write_day_convention() is True
        assert latch.write_day_convention() is False  # identical rewrite is a no-op
        assert latch.read_day_convention() == 2
        sink = _Sink()
        assert enforce_day_convention_at_boot(latch, alert_sink=sink) is False
    assert json.loads(store.data[EXEC_PAR_PREFIX + "day_convention"]) == {"v": 2}
