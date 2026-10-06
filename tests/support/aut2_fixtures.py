"""Shared builders for the AUT-2 labelling tests: durable fills written into a real exec store.

This module imports ``exec.client`` for ``DurableFillRecord`` and ``FILL_KEY_PREFIX`` only, so every
AUT-2 test file reaches the exec package through this one registered module (the X1 pin names it).
Nothing is constructed from the client and no socket is opened.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.runtime.sqlite_store import SqliteStateStore

__all__ = ["FILL_KEY_PREFIX", "DurableFillRecord", "durable_fill", "seed_fills"]

FQ_YES_SLUG = "tc-temp-laxhigh-2026-10-02-gte89lt90f"


def durable_fill(
    *,
    venue_order_id: str = "vo-1",
    client_order_id: str | None = None,
    instrument_id: str = f"{FQ_YES_SLUG}.POLYMARKET_US",
    order_side: str = "BUY",
    qty: Decimal = Decimal(1),
    cost: Decimal = Decimal("0.40"),
    fee: Decimal = Decimal("0.03"),
    fee_reconciled: bool = True,
    ts_event: int = 1_790_000_000_000_000_000,
    trade_id: str | None = "T-1",
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=client_order_id or f"O-{venue_order_id}",
        instrument_id=instrument_id,
        order_side=order_side,
        cumulative_qty=qty,
        cumulative_cost=cost,
        cumulative_fee=fee,
        fee_reconciled=fee_reconciled,
        ts_event=ts_event,
        trade_id=trade_id,
    )


def seed_fills(store_path: Path, fills: Iterable[DurableFillRecord]) -> None:
    """Write ``fills`` under the real durable-fill key prefix with the real record serialiser."""
    store = SqliteStateStore(store_path)
    try:
        for fill in fills:
            store.set(f"{FILL_KEY_PREFIX}{fill.venue_order_id}", fill.to_bytes())
    finally:
        store.close()
