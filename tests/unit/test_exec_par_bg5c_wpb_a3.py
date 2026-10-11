"""EXEC-PAR BG-5c WP-B (A3): the AMBIGUOUS full-cost term in the BG-1c accumulator.

A3: an AMBIGUOUS intent leaves the full-cost term ONLY when its fill's settled outcome exists;
between fill confirmation and settlement it counts at ``cumulative_cost + fee``; unresolved or
zero-fill it counts at the declared (armed-notional) cost. "Resolved" is the caller's venue
evidence (``ambiguous_unresolved=False``), never the ever-ambiguous mark itself.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from breezy.runtime import exec_par_settled_pnl as mod
from breezy.runtime.exec_par_records import SettledPnlDay
from breezy.runtime.exec_par_settled_pnl import EntryInput

NS = 1_000_000_000
D = Decimal
DAY = "2026-10-12"


class Fill:
    """Structural stand-in for the exec client's durable fill record."""

    instrument_id = "A"
    order_side = "BUY"
    cumulative_qty = D("10")
    cumulative_cost = D("9")
    cumulative_fee = D("0.2")
    fee_reconciled = True
    fee_coefficient_at_fill: Decimal | None = None


def utc_day(station: str, ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / NS, tz=dt.UTC).strftime("%Y-%m-%d")


def arm() -> int:
    return int(dt.datetime.fromisoformat(f"{DAY}T12:00:00+00:00").timestamp()) * NS


def row_for(entry: EntryInput, outcomes: dict[str, bool | None]) -> SettledPnlDay:
    rows: Any = mod.settled_pnl_by_day([entry], outcomes, utc_day, today=DAY)
    row: SettledPnlDay = rows[DAY]
    return row


def test_resolved_ever_ambiguous_fill_counts_at_cost_plus_fee_until_settlement() -> None:
    entry = EntryInput(
        arm_ns=arm(), station="STN", fill=Fill(), ambiguous_unresolved=False, ever_ambiguous=True
    )
    row = row_for(entry, {})
    assert row.pnl_decimal == D("-9.2")
    assert (row.ambiguous_entries, row.unsettled_entries, row.settled_entries) == (1, 0, 0)


def test_ever_ambiguous_leaves_the_full_cost_term_once_settled() -> None:
    entry = EntryInput(
        arm_ns=arm(), station="STN", fill=Fill(), ambiguous_unresolved=False, ever_ambiguous=True
    )
    won = row_for(entry, {"A": True})
    lost = row_for(entry, {"A": False})
    assert won.pnl_decimal == D("0.8")
    assert (won.ambiguous_entries, won.settled_entries) == (0, 1)
    assert lost.pnl_decimal == D("-9.2")
    assert (lost.ambiguous_entries, lost.settled_entries) == (0, 1)


def test_ordinary_unsettled_entry_is_still_pending_not_a_loss() -> None:
    entry = EntryInput(arm_ns=arm(), station="STN", fill=Fill())
    row = row_for(entry, {})
    assert row.pnl_decimal == D("0")
    assert (row.ambiguous_entries, row.unsettled_entries) == (0, 1)


def test_unresolved_zero_fill_counts_at_the_declared_armed_notional() -> None:
    entry = EntryInput(
        arm_ns=arm(),
        station="STN",
        fill=None,
        ambiguous_unresolved=True,
        ever_ambiguous=True,
        ambiguous_cost=D("5"),
    )
    row = row_for(entry, {})
    assert row.pnl_decimal == D("-5")
    assert row.ambiguous_entries == 1


def test_unresolved_with_a_confirmed_fill_counts_at_cost_plus_fee_even_if_it_wins() -> None:
    entry = EntryInput(
        arm_ns=arm(), station="STN", fill=Fill(), ambiguous_unresolved=True, ever_ambiguous=True
    )
    row = row_for(entry, {"A": True})
    assert row.pnl_decimal == D("-9.2")
    assert (row.ambiguous_entries, row.settled_entries) == (1, 0)
