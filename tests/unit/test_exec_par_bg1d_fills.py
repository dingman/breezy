"""EXEC-PAR BG-1d R1: only entry fills count, attributed by the entry's arm day."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from breezy.runtime.exec_par_reconcile import (
    DayCounts,
    FillRecord,
    SlotDayCounts,
    UnattributableFill,
    entry_fills_by_day,
    reconcile_day,
)

S = 1_000_000_000
H = 3_600 * S
DAY = 24 * H
D0 = 20_000 * DAY  # 2024-10-04T00:00Z


def _utc_day(ns: int) -> str:
    return datetime.fromtimestamp(ns // S, UTC).date().isoformat()


def _buy(order_id: str, arm_ns: int | None) -> FillRecord:
    return FillRecord(order_id=order_id, side="BUY", arm_ns=arm_ns)


def _sell(order_id: str) -> FillRecord:
    return FillRecord(order_id=order_id, side="SELL", arm_ns=None)


def test_exit_only_day_has_no_entry_fills_and_is_not_excluded() -> None:
    counts = entry_fills_by_day([_sell("x1"), _sell("x2")], day_of=_utc_day)
    assert counts == {}
    verdict = reconcile_day(
        "2024-10-04",
        stored=DayCounts(0, 0, 0, Decimal(0)),
        fills=counts.get("2024-10-04", 0),
        slots=SlotDayCounts(0, 0),
        spend=Decimal(0),
        gappy=False,
        expected_counters=True,
        pending=None,
    )
    assert verdict.reason is None
    assert verdict.kind.value == "unchanged"


def test_fill_after_midnight_is_attributed_to_its_arm_day() -> None:
    arm = D0 + 23 * H + 59 * 60 * S  # armed 23:59Z; the fill lands after midnight
    counts = entry_fills_by_day([_buy("o1", arm)], day_of=_utc_day)
    assert counts == {"2024-10-04": 1}


def test_repeated_partial_fills_of_one_order_count_once() -> None:
    records = [_buy("o1", D0 + H), _buy("o1", D0 + H), _buy("o1", D0 + H), _buy("o2", D0 + 2 * H)]
    assert entry_fills_by_day(records, day_of=_utc_day) == {"2024-10-04": 2}


def test_sell_records_never_count_even_with_an_arm_time() -> None:
    records = [FillRecord(order_id="o9", side="SELL", arm_ns=D0), _buy("o1", D0)]
    assert entry_fills_by_day(records, day_of=_utc_day) == {"2024-10-04": 1}


def test_entry_fill_without_arm_time_is_unattributable() -> None:
    with pytest.raises(UnattributableFill):
        entry_fills_by_day([_buy("o1", None)], day_of=_utc_day)


def test_same_order_with_two_arm_days_is_unattributable() -> None:
    with pytest.raises(UnattributableFill):
        entry_fills_by_day([_buy("o1", D0), _buy("o1", D0 + DAY)], day_of=_utc_day)


def test_unknown_side_is_unattributable() -> None:
    with pytest.raises(UnattributableFill):
        entry_fills_by_day([FillRecord(order_id="o1", side="HOLD", arm_ns=D0)], day_of=_utc_day)
