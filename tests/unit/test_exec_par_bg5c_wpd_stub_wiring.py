"""EXEC-PAR BG-5c WP-D (N-A): where the floor-stub settled-P&L row is stored and how it is read.

WP-C left ``StageSnapshot.floor_stub_pnl`` with no producer: the builder never filled it. The stub
row therefore needs a store key (``settled_pnl_floor_stub/<label>``, a sibling of the whole-day
``settled_pnl/<day>`` key) and a snapshot read, both pinned here.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.exec_par_records import EXEC_PAR_PREFIX, SettledPnlDay
from breezy.runtime.exec_par_stage_snapshot import build_stage_snapshot
from breezy.runtime.submit_intent import SubmitIntentCorrupt, open_submit_intent_latch
from tests.unit.test_exec_par_bg5c_floor_stub_open_days import (
    FLOOR_LABELS,
    floor_day_reads,
    inputs,
)

D = Decimal
STUB_ROW = SettledPnlDay(
    day=FLOOR_LABELS[0], pnl="-0.4", settled_entries=1, ambiguous_entries=0, unsettled_entries=0
)


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))


def test_stub_row_has_its_own_key_and_never_touches_the_whole_day_row(tmp_path: Path) -> None:
    store = _Store()
    whole = dataclasses.replace(STUB_ROW, pnl="-2", settled_entries=3)
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        assert latch.read_floor_stub_pnl_day(STUB_ROW.day) is None
        latch.write_settled_pnl_day(whole)
        latch.write_floor_stub_pnl_day(STUB_ROW)
        assert latch.read_floor_stub_pnl_day(STUB_ROW.day) == STUB_ROW
        assert latch.read_settled_pnl_day(STUB_ROW.day) == whole
        assert [r.day for r in latch.read_settled_pnl_days()] == [STUB_ROW.day]
    assert f"{EXEC_PAR_PREFIX}settled_pnl_floor_stub/{STUB_ROW.day}" in store.data


def test_stub_row_write_is_monotonic_like_the_whole_day_row(tmp_path: Path) -> None:
    from breezy.runtime.exec_par_settled_pnl import SettledPnlRegression

    with open_submit_intent_latch(_Store(), tmp_path / "s.db") as latch:
        latch.write_floor_stub_pnl_day(STUB_ROW)
        with pytest.raises(SettledPnlRegression):
            latch.write_floor_stub_pnl_day(dataclasses.replace(STUB_ROW, settled_entries=0))


def test_a_stub_row_under_the_wrong_label_is_corrupt(tmp_path: Path) -> None:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        latch.write_floor_stub_pnl_day(STUB_ROW)
        key = f"{EXEC_PAR_PREFIX}settled_pnl_floor_stub/{STUB_ROW.day}"
        store.data[f"{EXEC_PAR_PREFIX}settled_pnl_floor_stub/2026-01-01"] = store.data[key]
        with pytest.raises(SubmitIntentCorrupt):
            latch.read_floor_stub_pnl_day("2026-01-01")


def _snapshot_with_stub_reader(rows: dict[str, SettledPnlDay]):  # type: ignore[no-untyped-def]
    reads, counter_reads = floor_day_reads()
    return build_stage_snapshot(reads, counter_reads, inputs(read_stub_pnl=rows.get))


def test_builder_fills_floor_stub_pnl_from_the_stub_reader_only() -> None:
    snap = _snapshot_with_stub_reader({FLOOR_LABELS[0]: STUB_ROW})
    assert [x.day for x in snap.floor_stub_pnl] == [FLOOR_LABELS[0]]
    reading = snap.floor_stub_pnl[0].reading
    assert reading is not None and reading.pnl == D("-0.4") and reading.settled == 1


def test_builder_without_a_stub_reader_leaves_floor_stub_pnl_empty() -> None:
    reads, counter_reads = floor_day_reads()
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    assert snap.floor_stub_pnl == ()


def test_an_unreadable_stub_row_is_a_none_reading_never_zero() -> None:
    def broken(day: str) -> SettledPnlDay | None:
        raise OSError("boom")

    reads, counter_reads = floor_day_reads()
    reported: list[tuple[str, str, str]] = []
    snap = build_stage_snapshot(
        reads,
        counter_reads,
        inputs(read_stub_pnl=broken, on_read_error=lambda *a: reported.append(a)),
    )
    assert {x.day for x in snap.floor_stub_pnl} == set(FLOOR_LABELS)
    assert all(x.reading is None for x in snap.floor_stub_pnl)
    assert ("settled_pnl_stub", FLOOR_LABELS[0], "OSError") in reported
