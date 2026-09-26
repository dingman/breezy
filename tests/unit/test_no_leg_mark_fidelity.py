"""RED-first tests for the FU-1d S3 offline measurement script
(`no_leg_mark_fidelity.py`).

Every "derived" expectation is computed by CALLING the real
`walk_exit_vwap` inside the test (L-42) -- never a hand-written formula --
and every `DurableFillRecord` fixture goes through its own real
`to_bytes()`/`from_bytes()` round trip into a throwaway sqlite `state`
table, the exact schema `fill_time_count._open_readonly` reads.
"""

from __future__ import annotations

import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Final

from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.strategy.current_rung_hold.monitor_decision import _BOOK_STALE_NS
from breezy.strategy.current_rung_hold.monitor_evidence import walk_exit_vwap
from tests.unit.polymarket_us_exec_shapes import build_instrument, build_no_leg_instrument

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from no_leg_mark_fidelity import (
    STATUS_MEASURED,
    STATUS_NO_FRAME,
    STATUS_NOT_A_BUY,
    STATUS_ONE_SIDED,
    STATUS_STALE_FRAME,
    FillMarkComparison,
    main,
    measure_fill,
    read_fill_records,
    render_markdown,
    select_frame,
    summarise,
)

_YES_ID: Final[InstrumentId] = build_instrument().id
_NO_ID: Final[InstrumentId] = build_no_leg_instrument().id
_T: Final[int] = 1_800_000_000_000_000_000
_MINUTE_NS: Final[int] = 60_000_000_000


def _fill(
    *,
    venue_order_id: str = "V-1",
    instrument_id: InstrumentId = _YES_ID,
    order_side: str = "BUY",
    px: str = "0.40",
    qty: int = 1,
    ts_event: int = _T,
    trade_id: str | None = "trd-1",
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"client-{venue_order_id}",
        instrument_id=str(instrument_id),
        order_side=order_side,
        cumulative_qty=Decimal(qty),
        cumulative_cost=Decimal(px) * qty,
        cumulative_fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=ts_event,
        trade_id=trade_id,
    )


def _pad(side: OrderSide, levels: tuple[tuple[str, int], ...]) -> tuple[list[BookOrder], list[int]]:
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    counts = [1] * len(orders)
    while len(orders) < 10:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _depth(
    *,
    instrument_id: InstrumentId = _YES_ID,
    bids: tuple[tuple[str, int], ...] = (("0.30", 10),),
    asks: tuple[tuple[str, int], ...] = (("0.70", 10),),
    ts_init: int,
) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, bids)
    ask_orders, ask_counts = _pad(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_init,
        ts_init=ts_init,
    )


def _write_state_db(path: Path, rows: dict[str, bytes]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB)")
    conn.executemany("INSERT INTO state (key, value) VALUES (?, ?)", rows.items())
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# measure_fill: the derivation, computed by calling walk_exit_vwap (L-42)
# ---------------------------------------------------------------------------


def test_no_buy_derived_entry_is_one_minus_walked_yes_bid() -> None:
    """A NO buy walks the YES BIDS: `derived_entry_px = 1 - yes_bid_vwap`.
    Decoy asks present but irrelevant to the entry calculation."""
    frame = _depth(
        instrument_id=_YES_ID,
        bids=(("0.30", 5), ("0.28", 5)),
        asks=(("0.90", 5),),
        ts_init=_T - _MINUTE_NS,
    )
    fill = _fill(instrument_id=_NO_ID, order_side="BUY", px="0.66", qty=1, ts_event=_T)

    expected_bid_vwap, ok = walk_exit_vwap(frame, "YES", 1)
    assert ok is True
    assert expected_bid_vwap is not None
    expected_entry = Decimal(1) - expected_bid_vwap

    row = measure_fill(fill, sibling_yes_frames=(frame,))

    assert row.status == STATUS_MEASURED
    assert row.leg == "NO"
    assert row.derived_entry_px == expected_entry
    assert row.fill_px is not None
    assert row.residual == row.fill_px - expected_entry


def test_yes_buy_derived_entry_is_walked_yes_ask() -> None:
    """A YES buy's outer `1 -` undoes `walk_exit_vwap(..., "NO", ...)`'s own
    internal complement, landing on the plain ask VWAP. Decoy bids present
    but irrelevant to the entry calculation."""
    frame = _depth(
        instrument_id=_YES_ID,
        bids=(("0.10", 5),),
        asks=(("0.55", 5), ("0.60", 5)),
        ts_init=_T - _MINUTE_NS,
    )
    fill = _fill(instrument_id=_YES_ID, order_side="BUY", px="0.55", qty=1, ts_event=_T)

    complemented_ask_walk, ok = walk_exit_vwap(frame, "NO", 1)
    assert ok is True
    assert complemented_ask_walk is not None
    expected_entry = Decimal(1) - complemented_ask_walk

    row = measure_fill(fill, sibling_yes_frames=(frame,))

    assert row.status == STATUS_MEASURED
    assert row.leg == "YES"
    assert row.derived_entry_px == expected_entry


def test_derived_exit_mark_equals_monitor_walk_exit_vwap_for_the_leg() -> None:
    frame = _depth(
        instrument_id=_YES_ID,
        bids=(("0.30", 5),),
        asks=(("0.70", 5),),
        ts_init=_T - _MINUTE_NS,
    )
    fill = _fill(instrument_id=_NO_ID, order_side="BUY", px="0.30", qty=1, ts_event=_T)

    expected_mark, ok = walk_exit_vwap(frame, "NO", 1)
    assert ok is True

    row = measure_fill(fill, sibling_yes_frames=(frame,))

    assert row.derived_exit_mark == expected_mark


# ---------------------------------------------------------------------------
# Frame selection (leak guard)
# ---------------------------------------------------------------------------


def test_frame_selection_is_strictly_before_the_fill() -> None:
    before = _depth(ts_init=_T - _MINUTE_NS)
    at = _depth(ts_init=_T)
    after = _depth(ts_init=_T + _MINUTE_NS)

    assert select_frame((before, at, after), _T) is before
    assert select_frame((at, after), _T) is None


def test_stale_frame_is_reported_and_excluded_from_aggregate() -> None:
    stale_ts = _T - (_BOOK_STALE_NS + 1)
    frame = _depth(bids=(("0.30", 5),), asks=(("0.70", 5),), ts_init=stale_ts)
    fill = _fill(instrument_id=_YES_ID, order_side="BUY", px="0.70", qty=1, ts_event=_T)

    row = measure_fill(fill, sibling_yes_frames=(frame,))

    assert row.status == STATUS_STALE_FRAME
    assert row.frame_age_ns == _T - stale_ts

    summary = summarise([row])
    assert row not in summary.included


def test_fill_better_than_displayed_is_flagged_not_aggregated() -> None:
    frame = _depth(
        instrument_id=_YES_ID,
        bids=(("0.30", 5),),
        asks=(("0.90", 5),),
        ts_init=_T - _MINUTE_NS,
    )
    fill = _fill(instrument_id=_NO_ID, order_side="BUY", px="0.05", qty=1, ts_event=_T)

    row = measure_fill(fill, sibling_yes_frames=(frame,))

    assert row.flagged is True
    assert row.fill_px < row.derived_entry_px

    summary = summarise([row])
    assert row not in summary.included
    assert row in summary.flagged


def test_no_frame_and_one_sided_statuses() -> None:
    fill = _fill(instrument_id=_YES_ID, order_side="BUY", px="0.55", qty=1, ts_event=_T)

    no_frame_row = measure_fill(fill, sibling_yes_frames=())
    assert no_frame_row.status == STATUS_NO_FRAME

    empty_asks_frame = _depth(
        instrument_id=_YES_ID, bids=(("0.30", 5),), asks=(), ts_init=_T - _MINUTE_NS,
    )
    one_sided_row = measure_fill(fill, sibling_yes_frames=(empty_asks_frame,))
    assert one_sided_row.status == STATUS_ONE_SIDED


def test_sell_record_is_not_a_buy() -> None:
    fill = _fill(instrument_id=_NO_ID, order_side="SELL", px="0.30", qty=1, ts_event=_T)

    row = measure_fill(fill, sibling_yes_frames=())

    assert row.status == STATUS_NOT_A_BUY
    assert row.fill_px is None
    assert row.flagged is False


# ---------------------------------------------------------------------------
# Report: measurement, not a verdict
# ---------------------------------------------------------------------------


def test_report_states_no_leg_exit_fills_n_zero_and_no_verdict() -> None:
    no_buy = FillMarkComparison(
        venue_order_id="V-NO",
        instrument_id=str(_NO_ID),
        leg="NO",
        order_side="BUY",
        fill_px=Decimal("0.12"),
        qty=Decimal(1),
        frame_ts_init=_T - _MINUTE_NS,
        frame_age_ns=_MINUTE_NS,
        derived_entry_px=Decimal("0.12"),
        residual=Decimal(0),
        derived_exit_mark=Decimal("0.12"),
        status=STATUS_MEASURED,
        flagged=False,
        ts_provenance="create",
    )
    summary = summarise([no_buy])
    assert summary.n_no_exit_fills == 0

    doc = render_markdown(summary, run_date="2026-09-26")

    assert "n(NO EXIT fills)=0" in doc
    assert "NOT EVALUABLE" in doc
    assert "no verdict" in doc.lower()


# ---------------------------------------------------------------------------
# Read-only discipline and fail-closed exit code
# ---------------------------------------------------------------------------


def test_unreadable_store_exits_2_without_writing(tmp_path: Path) -> None:
    out_path = tmp_path / "out.md"
    exit_code = main(
        [
            "--exec-state-db", str(tmp_path / "does-not-exist.sqlite"),
            "--catalog-root", str(tmp_path / "catalog"),
            "--run-date", "2026-09-26",
            "--out", str(out_path),
        ]
    )

    assert exit_code == 2
    assert not out_path.exists()


def test_store_opened_read_only(tmp_path: Path) -> None:
    db_path = tmp_path / "exec_state.sqlite"
    fill = _fill(instrument_id=_YES_ID, order_side="BUY", px="0.40", qty=1, ts_event=_T)
    _write_state_db(db_path, {f"exec/polymarket_us/fill/{fill.venue_order_id}": fill.to_bytes()})
    mtime_before = db_path.stat().st_mtime_ns

    fills = read_fill_records(db_path)

    assert len(fills) == 1
    assert db_path.stat().st_mtime_ns == mtime_before
    assert not db_path.with_name(db_path.name + "-wal").exists()
    assert not db_path.with_name(db_path.name + "-journal").exists()
    assert not db_path.with_name(db_path.name + "-shm").exists()
