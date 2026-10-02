"""CT-4: `_persist_batch` nudges a colliding or preceding `ts_init` to `existing_max+1`.

Entry point: `NwsIngestActor.poll_once` (the persist path, `nws_actor.py`
`_persist_batch`) writing through the real `write_records` into a real
`ParquetDataCatalog` under `tmp_path`. The actor, clock, and catalog wiring
are the fixtures from `tests/unit/test_ingest_nws_actor.py`; the synthetic
CLI products are the helpers from `tests/contract/test_ingest_backlog_drain.py`.

A fetch whose `retrieved_at_ns` is less than or equal to the catalog's
current maximum `ts_init` must come back as `existing_max + 1` on both the
`NwsClimateDay` and the `NwsRawProduct`. That is the whole pin: removing
the `+ 1` makes the nudged stamp equal the existing interval, and the real
writer then skips the batch.

A second test nudges two products of ONE climate day and pins their
`revision_seq` at 1 then 2.

Red mutations in `_persist_batch`: `existing_max_ts_init + 1` loses the `+ 1`;
or the `seq_by_day` increment is removed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import open_station_catalog, read_climate_days, read_raw_products
from breezy.registry.sites import default_registry
from tests.contract.test_ingest_backlog_drain import (
    backlog_day,
    mock_synthetic_discovery,
    mock_synthetic_product,
    synthetic_entry,
    synthetic_product_payload,
    synthetic_product_url,
    synthetic_uuid,
)
from tests.unit.test_ingest_nws_actor import (
    ALL_SITES,
    CITY,
    DISCOVERY_URL,
    VENUE,
    FakeClock,
    _local_probe,
    build_actor,
    discovery_payload,
    durable_store_pair,
)


@pytest.fixture
def wired_actor(tmp_path: Path) -> Iterator[tuple[NwsIngestActor, FakeClock]]:
    """Same actor/catalog wiring as `test_ingest_nws_actor.py`'s `actor` fixture."""
    clock = FakeClock()
    store, store_opener = durable_store_pair()
    state = SharedIngestState(
        registry=default_registry(),
        sites=ALL_SITES,
        catalog_base=tmp_path / "nws",
        store=store,
        clock=clock,
        store_opener=store_opener,
        probe=_local_probe,
        check_proxy_env=False,
    )
    instance = build_actor(state)
    try:
        yield instance, clock
    finally:
        instance.shutdown_executor()
        state.dispose()


def _catalog(tmp_path: Path) -> ParquetDataCatalog:
    return open_station_catalog(tmp_path / "nws", VENUE, CITY)


def _one_climate_day(records: list[NwsClimateDay], day: dt.date) -> NwsClimateDay:
    matched = [record for record in records if record.climate_day == day]
    assert len(matched) == 1, (
        f"{day.isoformat()} climate-day rows={len(matched)}; a fetch that collides with or "
        "precedes the catalog interval must persist at existing_max+1"
    )
    return matched[0]


def _one_raw(records: list[NwsRawProduct], day: dt.date) -> NwsRawProduct:
    product_uuid = synthetic_uuid(day.isoformat())
    matched = [record for record in records if record.product_uuid == product_uuid]
    assert len(matched) == 1, (
        f"{product_uuid} raw-product rows={len(matched)}; the nudged stamp is "
        "written through the real catalog, not only held in memory"
    )
    return matched[0]


async def _poll(actor: NwsIngestActor, day: dt.date) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_synthetic_discovery(mock, day)
        mock_synthetic_product(mock, day)
        await actor.poll_once()


@pytest.mark.asyncio
async def test_colliding_or_preceding_ts_init_persists_as_existing_max_plus_one(
    wired_actor: tuple[NwsIngestActor, FakeClock],
    tmp_path: Path,
) -> None:
    """Preceding (`<`) and colliding (`==`) fetch stamps both land at max+1.

    The first poll establishes the catalog interval at the un-nudged fetch
    stamp. The second poll's clock is strictly earlier than that maximum.
    The third poll's clock equals the maximum the second poll just wrote.
    """
    actor, clock = wired_actor
    day_a = backlog_day(3)
    day_b = backlog_day(2)
    day_c = backlog_day(1)

    actor.on_start()
    baseline = clock.now
    await _poll(actor, day_a)

    catalog = _catalog(tmp_path)
    first = _one_climate_day(read_climate_days(catalog), day_a)
    existing_max = int(first.ts_init)
    assert existing_max == baseline
    assert int(_one_raw(read_raw_products(catalog), day_a).ts_init) == baseline

    precede_stamp = existing_max - 1
    clock.now = precede_stamp
    await _poll(actor, day_b)

    catalog = _catalog(tmp_path)
    preceded = _one_climate_day(read_climate_days(catalog), day_b)
    assert int(preceded.ts_init) == existing_max + 1
    assert preceded.revision_seq == 1
    assert int(preceded.ts_init) != precede_stamp
    assert int(_one_raw(read_raw_products(catalog), day_b).ts_init) == existing_max + 1

    collide_stamp = existing_max + 1
    clock.now = collide_stamp
    await _poll(actor, day_c)

    catalog = _catalog(tmp_path)
    collided = _one_climate_day(read_climate_days(catalog), day_c)
    assert int(collided.ts_init) == collide_stamp + 1
    assert collided.revision_seq == 1
    assert int(collided.ts_init) != collide_stamp
    assert int(_one_raw(read_raw_products(catalog), day_c).ts_init) == collide_stamp + 1


async def _poll_labelled(actor: NwsIngestActor, day: dt.date, label: str) -> None:
    """One poll whose single product is a distinct uuid for the SAME climate day."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(
                200, json=discovery_payload(synthetic_entry(day, label=label))
            )
        )
        mock.get(synthetic_product_url(day, label=label)).mock(
            return_value=httpx.Response(200, json=synthetic_product_payload(day, label=label))
        )
        await actor.poll_once()


@pytest.mark.asyncio
async def test_nudged_second_product_of_one_climate_day_gets_revision_seq_two(
    wired_actor: tuple[NwsIngestActor, FakeClock],
    tmp_path: Path,
) -> None:
    """Two products of one climate day, the second fetched at a stamp that
    precedes the catalog maximum: nudged AND counted as revision 2."""
    actor, clock = wired_actor
    day = backlog_day(3)

    actor.on_start()
    await _poll_labelled(actor, day, "first")
    first_stamp = clock.now
    clock.now = first_stamp - 1
    await _poll_labelled(actor, day, "second")

    rows = sorted(
        (r for r in read_climate_days(_catalog(tmp_path)) if r.climate_day == day),
        key=lambda r: r.revision_seq,
    )
    assert [r.revision_seq for r in rows] == [1, 2]
    assert [int(r.ts_init) for r in rows] == [first_stamp, first_stamp + 1]
