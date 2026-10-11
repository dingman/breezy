"""EXEC-PAR BG-1c: the pure settled-P&L accumulator (spec 10a, 15, K9)."""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from breezy.runtime import exec_par_settled_pnl as mod
from breezy.runtime.exec_par_records import SettledPnlDay
from breezy.runtime.exec_par_settled_pnl import (
    SETTLEMENT_DEADLINE_DAYS,
    EntryInput,
    SettledPnlInputError,
    SettledPnlMissing,
    settled_pnl_or_fail,
)

NS = 1_000_000_000
D = Decimal


@dataclass(frozen=True)
class DurableFillRecord:
    """Structural stand-in for the exec client's record (tests never import exec/)."""

    venue_order_id: str
    client_order_id: str
    instrument_id: str
    order_side: str
    cumulative_qty: Decimal
    cumulative_cost: Decimal
    cumulative_fee: Decimal
    fee_reconciled: bool
    ts_event: int
    fee_coefficient_at_fill: Decimal | None = None


def settled_pnl_by_day(
    entries: Any, outcomes: Any, day_of_ns: Any, today: str = "2026-10-12"
) -> dict[str, SettledPnlDay]:
    return mod.settled_pnl_by_day(entries, outcomes, day_of_ns, today=today)


def utc_day(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / NS, tz=dt.UTC).strftime("%Y-%m-%d")


def at(day: str, hh: int = 12) -> int:
    d = dt.datetime.fromisoformat(f"{day}T{hh:02d}:00:00+00:00")
    return int(d.timestamp()) * NS


def fill(
    inst: str = "A",
    qty: str = "10",
    cost: str = "9",
    fee: str = "0.2",
    side: str = "BUY",
    ts_event: int = 1,
    reconciled: bool = True,
    theta: str | None = None,
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=f"v-{inst}",
        client_order_id=f"c-{inst}",
        instrument_id=inst,
        order_side=side,
        cumulative_qty=D(qty),
        cumulative_cost=D(cost),
        cumulative_fee=D(fee),
        fee_reconciled=reconciled,
        ts_event=ts_event,
        fee_coefficient_at_fill=None if theta is None else D(theta),
    )


def entry(
    day: str = "2026-10-12", f: DurableFillRecord | None = None, ambiguous: bool = False
) -> EntryInput:
    return EntryInput(arm_ns=at(day), fill=f or fill(), ambiguous_unresolved=ambiguous)


def test_win_pays_one_per_contract_net_of_cost_and_fee() -> None:
    row = settled_pnl_by_day([entry()], {"A": True}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("10") - D("9") - D("0.2")
    assert (row.settled_entries, row.ambiguous_entries, row.unsettled_entries) == (1, 0, 0)


def test_loss_is_minus_cost_and_fee() -> None:
    row = settled_pnl_by_day([entry()], {"A": False}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("-9.2")


def test_entries_sum_within_a_day() -> None:
    entries = [entry(f=fill("A")), entry(f=fill("B", "5", "4", "0.1"))]
    row = settled_pnl_by_day(entries, {"A": True, "B": False}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("0.8") + D("-4.1")
    assert row.settled_entries == 2


def test_unresolved_ambiguous_is_full_cost_loss_even_if_the_outcome_wins() -> None:
    row = settled_pnl_by_day([entry(ambiguous=True)], {"A": True}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("-9.2")
    assert (row.ambiguous_entries, row.settled_entries) == (1, 0)


def test_unresolved_ambiguous_without_a_fill_uses_declared_cost() -> None:
    e = EntryInput(
        arm_ns=at("2026-10-12"), fill=None, ambiguous_unresolved=True, ambiguous_cost=D("5")
    )
    assert settled_pnl_by_day([e], {}, utc_day)["2026-10-12"].pnl_decimal == D("-5")


def test_unresolved_ambiguous_without_any_cost_fails() -> None:
    e = EntryInput(arm_ns=at("2026-10-12"), fill=None, ambiguous_unresolved=True)
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([e], {}, utc_day)


def test_resolved_ambiguous_is_scored_as_an_ordinary_fill() -> None:
    row = settled_pnl_by_day([entry(ambiguous=False)], {"A": True}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("0.8")


def test_attribution_is_by_arm_time_across_a_day_boundary() -> None:
    late_arm = EntryInput(
        arm_ns=at("2026-10-12", 23) + 59 * 60 * NS, fill=fill("A", ts_event=at("2026-10-13"))
    )
    early_next = EntryInput(arm_ns=at("2026-10-13", 0), fill=fill("B"))
    out = settled_pnl_by_day([late_arm, early_next], {"A": False, "B": False}, utc_day)
    assert set(out) == {"2026-10-12", "2026-10-13"}
    assert out["2026-10-12"].pnl_decimal == D("-9.2")
    assert out["2026-10-13"].pnl_decimal == D("-9.2")


def test_day_is_never_taken_from_fill_time() -> None:
    e = EntryInput(arm_ns=at("2026-10-12"), fill=fill(ts_event=at("2026-10-20")))
    assert set(settled_pnl_by_day([e], {"A": True}, utc_day)) == {"2026-10-12"}


def test_unsettled_entry_is_counted_not_summed() -> None:
    row = settled_pnl_by_day([entry()], {}, utc_day)["2026-10-12"]
    assert row.unsettled_entries == 1
    assert row.pnl_decimal == D(0)
    assert row.settled_entries == 0


@pytest.mark.parametrize(
    "bad",
    [{"fee": "-1"}, {"cost": "-1"}, {"qty": "0"}, {"side": "SELL"}, {"cost": "NaN"}],
)
def test_malformed_fill_fails_closed(bad: dict[str, Any]) -> None:
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([entry(f=fill(**bad))], {"A": True}, utc_day)


def test_none_money_fails_never_zero() -> None:
    class Bare:
        instrument_id = "A"
        order_side = "BUY"
        cumulative_qty = D("1")
        cumulative_cost = D("1")
        cumulative_fee = None
        ts_event = 1

    bare: Any = Bare()
    e = EntryInput(arm_ns=at("2026-10-12"), fill=bare)
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([e], {"A": True}, utc_day)


def test_none_outcome_for_a_listed_instrument_fails() -> None:
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([entry()], {"A": None}, utc_day)


@pytest.mark.parametrize("arm", [0, -1, True, 1.5])
def test_bad_arm_time_fails(arm: Any) -> None:
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([EntryInput(arm_ns=arm, fill=fill())], {"A": True}, utc_day)


def test_missing_fill_for_a_non_ambiguous_entry_fails() -> None:
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([EntryInput(arm_ns=at("2026-10-12"), fill=None)], {}, utc_day)


def test_result_is_deterministic_and_order_independent() -> None:
    entries = [
        entry(day, f=fill(f"I{i}", str(i + 1), "0.37", "0.011"))
        for i, day in enumerate(["2026-10-12", "2026-10-13"] * 8)
    ]
    outcomes = {f"I{i}": bool(i % 3) for i in range(16)}
    first = settled_pnl_by_day(entries, outcomes, utc_day)
    shuffled = list(entries)
    random.Random(7).shuffle(shuffled)
    assert settled_pnl_by_day(shuffled, outcomes, utc_day) == first
    assert settled_pnl_by_day(entries, outcomes, utc_day) == first


def test_settled_pnl_or_fail_treats_missing_as_failure_not_zero() -> None:
    with pytest.raises(SettledPnlMissing):
        settled_pnl_or_fail(None)
    row = settled_pnl_by_day([entry()], {"A": True}, utc_day)["2026-10-12"]
    reading = settled_pnl_or_fail(row)
    assert reading.pnl == D("0.8")
    assert (reading.settled, reading.ambiguous, reading.pending, reading.overdue) == (1, 0, 0, 0)
    assert reading.fee_unreconciled == 0


def test_deadline_constant_is_three_climate_days() -> None:
    assert SETTLEMENT_DEADLINE_DAYS == 3


@pytest.mark.parametrize(
    ("today", "overdue"),
    [("2026-10-12", False), ("2026-10-14", False), ("2026-10-15", True), ("2026-10-30", True)],
)
def test_unsettled_entry_is_pending_until_the_deadline_then_a_full_cost_loss(
    today: str, overdue: bool
) -> None:
    row = settled_pnl_by_day([entry()], {}, utc_day, today=today)["2026-10-12"]
    if overdue:
        assert (row.overdue_entries, row.unsettled_entries) == (1, 0)
        assert row.pnl_decimal == D("-9.2")
    else:
        assert (row.overdue_entries, row.unsettled_entries) == (0, 1)
        assert row.pnl_decimal == D(0)


def test_bad_today_fails() -> None:
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([entry()], {}, utc_day, today="12/10/2026")


def test_unreconciled_fee_uses_the_theta_floor_rounded_up_and_is_counted() -> None:
    # qty 10, cost 9 -> p 0.9; theta*C*p*(1-p) = 0.0695*10*0.09 = 0.06255 -> 0.07 > recorded 0.01
    low = fill(fee="0.01", reconciled=False, theta="0.0695")
    row = settled_pnl_by_day([entry(f=low)], {"A": False}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("-9.07")
    assert row.fee_unreconciled_entries == 1
    assert row.fee_floor_total == "0.07"
    high = fill(fee="0.2", reconciled=False, theta="0.0695")
    row = settled_pnl_by_day([entry(f=high)], {"A": False}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("-9.2")
    assert row.fee_unreconciled_entries == 1
    assert row.fee_floor_total == "0.2"


def test_unreconciled_fee_without_theta_fails() -> None:
    with pytest.raises(SettledPnlInputError):
        settled_pnl_by_day([entry(f=fill(reconciled=False))], {"A": False}, utc_day)


def test_reconciled_fee_is_taken_as_recorded() -> None:
    row = settled_pnl_by_day([entry(f=fill(fee="0.01"))], {"A": False}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("-9.01")
    assert row.fee_unreconciled_entries == 0
    assert row.fee_floor_total == "0"


def test_no_instrument_whose_yes_sibling_lost_is_a_held_side_win() -> None:
    # The caller maps instrument -> held-side outcome (YES resolved NO => the NO leg won).
    no_leg = fill("EVT^no", "10", "6", "0.1")
    row = settled_pnl_by_day([entry(f=no_leg)], {"EVT^no": True}, utc_day)["2026-10-12"]
    assert row.pnl_decimal == D("3.9")
    assert row.pnl_decimal > 0


def test_module_never_logs_or_prints() -> None:
    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != "logging" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "logging"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "print"
