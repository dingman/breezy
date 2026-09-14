"""RED-first tests for E3-8/E4-5/E4-1 (S5 plan Rev 3/4, Track B commit 3):
the boot-reconcile write of `NO_SIDE_FIRST_LIVE_ORDER_KEY`.

Fail-closed equivalent trigger to the (Track A) create-path write: if, at
exec-client connect, a NO-leg `DurableFillRecord` exists while the key is
still absent (e.g. a crash between submission and the create-path write),
the node writes the key during boot reconciliation -- immediately after
`_seed_spend_from_durable_fills`, via `self._store_set` (no flock, same
unlocked pattern as `_reconcile_submit_intent`/`record_fill`).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.adapters.polymarket_us.exec.no_side_keys import NO_SIDE_FIRST_LIVE_ORDER_KEY
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.unit.polymarket_us_exec_shapes import RAW, TS_INIT
from tests.unit.test_polymarket_us_exec_client import _build_rig


def _no_leg_instrument():
    market = json.loads((RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8"))
    yes, no = parse_binary_option_pair(market, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    assert no is not None
    return yes, no


@pytest.mark.asyncio
async def test_a_no_leg_fill_with_no_key_on_record_writes_it_at_boot(tmp_path: Path) -> None:
    _yes, no_instrument = _no_leg_instrument()
    store_path = tmp_path / "exec_state.db"
    store = SqliteStateStore(store_path)
    store.close()

    boot1 = _build_rig(tmp_path, store_path=store_path)
    boot1.client._instrument_provider.add(no_instrument)
    boot1.cache.add_instrument(no_instrument)
    await boot1.client._connect()
    boot1.client.record_fill(
        DurableFillRecord(
            venue_order_id="V-NO-1",
            client_order_id="O-19700101-000000-001-001-1",
            instrument_id=str(no_instrument.id),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.15"),
            cumulative_fee=Decimal("0.00"),
            fee_reconciled=True,
            ts_event=TS_INIT,
        ),
    )
    await boot1.client._disconnect()

    pre_store = SqliteStateStore(store_path)
    assert pre_store.get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is None
    pre_store.close()

    boot2 = _build_rig(tmp_path, store_path=store_path)
    boot2.client._instrument_provider.add(no_instrument)
    boot2.cache.add_instrument(no_instrument)
    await boot2.client._connect()
    raw = boot2.client._store_get(NO_SIDE_FIRST_LIVE_ORDER_KEY)
    await boot2.client._disconnect()
    assert raw is not None
    payload = json.loads(raw)
    assert payload["instrumentId"] == str(no_instrument.id)


@pytest.mark.asyncio
async def test_a_no_leg_fill_with_the_key_already_present_is_left_untouched(
    tmp_path: Path,
) -> None:
    _yes, no_instrument = _no_leg_instrument()
    store_path = tmp_path / "exec_state.db"
    store = SqliteStateStore(store_path)
    sentinel = json.dumps({"instrumentId": "already-there"}).encode("utf-8")
    store.set(NO_SIDE_FIRST_LIVE_ORDER_KEY, sentinel)
    store.close()

    boot = _build_rig(tmp_path, store_path=store_path)
    boot.client._instrument_provider.add(no_instrument)
    boot.cache.add_instrument(no_instrument)
    await boot.client._connect()
    boot.client.record_fill(
        DurableFillRecord(
            venue_order_id="V-NO-2",
            client_order_id="O-19700101-000000-001-001-1",
            instrument_id=str(no_instrument.id),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.15"),
            cumulative_fee=Decimal("0.00"),
            fee_reconciled=True,
            ts_event=TS_INIT,
        ),
    )
    raw_after_fill = boot.client._store_get(NO_SIDE_FIRST_LIVE_ORDER_KEY)
    await boot.client._disconnect()
    assert raw_after_fill == sentinel

    boot2 = _build_rig(tmp_path, store_path=store_path)
    boot2.client._instrument_provider.add(no_instrument)
    boot2.cache.add_instrument(no_instrument)
    await boot2.client._connect()
    raw = boot2.client._store_get(NO_SIDE_FIRST_LIVE_ORDER_KEY)
    await boot2.client._disconnect()
    assert raw == sentinel


@pytest.mark.asyncio
async def test_a_yes_only_fill_history_never_writes_the_no_side_key(tmp_path: Path) -> None:
    store_path = tmp_path / "exec_state.db"
    boot1 = _build_rig(tmp_path, store_path=store_path)
    await boot1.client._connect()
    boot1.client.record_fill(
        DurableFillRecord(
            venue_order_id="V-YES-1",
            client_order_id="O-19700101-000000-001-001-1",
            instrument_id=str(boot1.instrument.id),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal("0.00"),
            fee_reconciled=True,
            ts_event=TS_INIT,
        ),
    )
    await boot1.client._disconnect()

    boot2 = _build_rig(tmp_path, store_path=store_path)
    await boot2.client._connect()
    raw = boot2.client._store_get(NO_SIDE_FIRST_LIVE_ORDER_KEY)
    await boot2.client._disconnect()
    assert raw is None
