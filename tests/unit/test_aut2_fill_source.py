"""AUT-2 r7 WP2: the durable-fill reader (``analysis/labeling/fill_source.py``).

Fixtures are written into a real exec store through the real record serialiser; the WAL case copies
a live writer's on-disk image (db plus -wal, no checkpoint) to model a writer that exited uncleanly.
"""

from __future__ import annotations

import shutil
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.fill_source import (
    FillRead,
    FillStoreCorruption,
    leg_fill_of,
    net_by_base_slug,
    read_durable_fills,
)
from breezy.persistence.autonomy.net_position import LegFill
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.support.aut2_fixtures import FILL_KEY_PREFIX, durable_fill, seed_fills

YES = "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US"
NO = "tc-temp-laxhigh-2026-10-02-gte89lt90f^no.POLYMARKET_US"


def test_reads_every_fill_through_ro_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "exec.db"
    seed_fills(
        store,
        [
            durable_fill(venue_order_id="vo-1"),
            durable_fill(venue_order_id="vo-2", instrument_id=NO),
            durable_fill(venue_order_id="vo-3", order_side="SELL"),
        ],
    )
    writer = SqliteStateStore(store)
    try:  # keys that share a prefix with, but are not, durable fills
        writer.set("exec/polymarket_us/fill_index/" + YES, b'["vo-1"]')
        writer.set("exec/polymarket_us/intent/current", b"{}")
    finally:
        writer.close()
    opened: list[str] = []
    real_connect = sqlite3.connect

    def _spy(database: str, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        opened.append(database)
        conn: sqlite3.Connection = real_connect(database, *args, **kwargs)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _spy)

    result = read_durable_fills(store)

    assert result.n_keys == 3
    assert result.n_undecodable == 0
    assert sorted(f.venue_order_id for f in result.fills) == ["vo-1", "vo-2", "vo-3"]
    assert len(opened) == 1
    assert opened[0].startswith("file:") and opened[0].endswith("?mode=ro")


def test_undecodable_fill_is_store_corruption_not_skip(tmp_path: Path) -> None:
    store = tmp_path / "exec.db"
    seed_fills(store, [durable_fill(venue_order_id="vo-1")])
    writer = SqliteStateStore(store)
    try:
        writer.set(f"{FILL_KEY_PREFIX}vo-bad", b"{not json")
        writer.set(f"{FILL_KEY_PREFIX}vo-short", b'{"venueOrderId": "x"}')
    finally:
        writer.close()

    result = read_durable_fills(store)

    assert result.n_keys == 3
    assert result.n_undecodable == 2
    assert [f.venue_order_id for f in result.fills] == ["vo-1"]
    with pytest.raises(FillStoreCorruption):
        result.require_clean()
    assert FillRead(fills=(), n_keys=0, n_undecodable=0).require_clean().n_keys == 0


def test_fill_source_reads_wal_store_after_writer_exit(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    writer = SqliteStateStore(live / "exec.db")
    for index in range(3):
        fill = durable_fill(venue_order_id=f"vo-{index}")
        writer.set(f"{FILL_KEY_PREFIX}vo-{index}", fill.to_bytes())
    image = tmp_path / "image"
    image.mkdir()
    for name in ("exec.db", "exec.db-wal"):  # the unchecked-pointed WAL a killed writer leaves
        shutil.copy(live / name, image / name)
    assert (image / "exec.db-wal").stat().st_size > 0
    writer.close()

    result = read_durable_fills(image / "exec.db")

    assert result.n_keys == 3
    assert result.n_undecodable == 0


def test_real_default_reader_against_tmp_store(tmp_path: Path) -> None:
    store = tmp_path / "exec.db"
    seed_fills(store, [durable_fill(venue_order_id="vo-1", qty=Decimal(2), cost=Decimal("0.80"))])

    result = read_durable_fills(store)  # no seam: the production reader on a real store

    (fill,) = result.fills
    assert (fill.cumulative_qty, fill.cumulative_cost, fill.order_side) == (
        Decimal(2),
        Decimal("0.80"),
        "BUY",
    )
    with pytest.raises(FileNotFoundError):  # an absent store is never an empty ledger
        read_durable_fills(tmp_path / "absent.db")


def test_leg_fill_and_net_by_base_slug_apply_the_leg_sign() -> None:
    fills = [
        durable_fill(venue_order_id="a", instrument_id=YES, qty=Decimal(4), ts_event=1),
        durable_fill(
            venue_order_id="b", instrument_id=YES, order_side="SELL", qty=Decimal(1), ts_event=2
        ),
        durable_fill(venue_order_id="c", instrument_id=NO, qty=Decimal(2), ts_event=3),
    ]

    assert leg_fill_of(fills[2]) == LegFill(leg="no", side="BUY", qty=Decimal(2), ts_event_ns=3)
    assert net_by_base_slug(fills) == {"tc-temp-laxhigh-2026-10-02-gte89lt90f": Decimal(1)}
    with pytest.raises(ValueError, match="BUY or SELL"):
        leg_fill_of(durable_fill(venue_order_id="d", order_side="HOLD"))
