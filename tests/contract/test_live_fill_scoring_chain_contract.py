"""I5 -- end-to-end contract test (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md`).

Drives the REAL chain under `tmp_path`, never a hand-written JSON blob for the
fill record: a schema-shaped 200 create-order response through the real
`_submit_order` accept-fill branch (`exec/client.py`'s `record_fill`, FIRST
effectful action of that branch, I1b) -> the exec `SqliteStateStore` ->
`read_filled_trials_state_db` (I2) -> `score_trial` -> a scored parquet row,
`provenance.json` and `fill_order.jsonl` (I3/I3c). Otherwise each increment
is proven green in isolation only, and the chain itself is unproven (I5,
was O6).

Fixtures are reused from the shipped rigs, never re-implemented: the R-7
accept-fill rig (`tests/unit/test_polymarket_us_exec_client.py`'s
`_build_accept_fill_rig`/`_AcceptFillRig`) drives the real client to a real
`SqliteStateStore`; the state-DB seeding helpers
(`tests/unit/test_score_live_trials_state_db_source.py`'s `_seed_latch`,
`_write_manifest`, `_write_cmdline`, `_write_environ`, and the shared LAX/
2026-09-05 constants) seed the taken trial-day latch and the node-env
pre-flight fixture the exact same way I2's own suite proves works. This
module imports `DurableFillRecord` from `exec.client` directly (I5 X1
mandate) rather than seeding from a second, drifting encoding.

No commit, no network, no real `/proc` and no real state DB: every store,
manifest and `/proc` tree lives under `tmp_path`, and `--catalog-base` is
always pointed at a temp directory -- the production default
(`DEFAULT_NWS_CATALOG_BASE`) is a real user path this suite must never touch.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.events import OrderFilled, OrderSubmitted
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.persistence.catalog import open_station_catalog, write_records
from breezy.persistence.scored_trial_store import read_scored_trials
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import SubmitIntentState

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import family_tally_v2
import fill_time_count
from score_live_trials import _EXCLUDED_FILLS_ARTEFACT_NAME, main

from tests.unit.polymarket_us_exec_shapes import build_execution, build_order
from tests.unit.test_polymarket_us_exec_client import (
    _accept_fill_body,
    _accept_fill_caps,
    _build_accept_fill_rig,
    _FakeOrderSender,
    _reopened_fill_record,
    _slug,
    write_canonical_verified,  # noqa: F401 -- fixture import, never a second setattr site
)
from tests.unit.test_score_live_trials_state_db_source import (
    _CITY,
    _DAY_ISO,
    _FAMILY_PREFIX,
    _STATION,
    _VENUE,
    _seed_latch,
    _write_cmdline,
    _write_environ,
    _write_manifest,
)

pytestmark = pytest.mark.contract

#: The fake /proc node this suite's REVISE-1 pre-flight matches against --
#: never the real `/proc`.
_NODE_PID = 111
_NODE_CMDLINE = [b"/home/jon/breezy/.venv/bin/breezy-trade"]


def _partial_fill_body(
    slug: str,
    *,
    order_id: str = "ord-i5-partial",
    last_px: str = "0.37",
    filled_qty: str = "0.37",
    commission: str = "0.01",
) -> bytes:
    """A 200 create-order body classifying as `KIND_ACCEPT_FILL` with a
    fractional order-level `cumQuantity` -- a real partial IOC fill, never a
    `qty <= 0` miss. The record is still written in full (I1b: the record is
    evidence, not a filter); `_admit_fill` is what excludes it (ruling Q1)."""
    order = build_order(slug)
    order["id"] = order_id
    order["quantity"] = 1
    order["cumQuantity"] = filled_qty
    order["leavesQuantity"] = "0.63"
    order["state"] = "ORDER_STATE_PARTIALLY_FILLED"
    order["price"] = {"value": last_px, "currency": "USD"}
    order["avgPx"] = {"value": last_px, "currency": "USD"}
    execution = build_execution(order)
    execution["type"] = "EXECUTION_TYPE_PARTIAL_FILL"
    execution["lastShares"] = filled_qty
    execution["lastPx"] = {"value": last_px, "currency": "USD"}
    execution["commissionNotionalCollected"] = {"value": commission, "currency": "USD"}
    return json.dumps({"id": order_id, "executions": [execution]}).encode("utf-8")


def _seed_weather_instrument_and_final(catalog_base: Path, *, instrument: BinaryOption) -> None:
    """Persist a weather-bucket-facts copy of `instrument` (SAME instrument_id
    the fill/latch carry) plus a FINAL NWS climate-day record for LAX/
    2026-09-05, tmax_f=79 -- inside the seeded [78, 80] bucket, so `held` is
    decidable and `True`. Mirrors `test_score_live_trials_state_db_source.py`'s
    `_seed_instrument_and_final`, parameterized on the REAL rig instrument
    (a captured NYC market) rather than a synthetic id, since the fill and
    the latch both carry the rig's real `instrument.id`."""
    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    weather_instrument = BinaryOption(
        instrument_id=instrument.id,
        raw_symbol=instrument.raw_symbol,
        outcome=instrument.outcome,
        description=instrument.description,
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=instrument.price_precision,
        price_increment=instrument.price_increment,
        size_precision=instrument.size_precision,
        size_increment=instrument.size_increment,
        activation_ns=instrument.activation_ns,
        expiration_ns=instrument.expiration_ns,
        max_quantity=instrument.max_quantity,
        min_quantity=instrument.min_quantity,
        maker_fee=instrument.maker_fee,
        taker_fee=instrument.taker_fee,
        ts_event=instrument.ts_event,
        ts_init=instrument.ts_init,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: _STATION,
            CLIMATE_DAY_KEY: _DAY_ISO,
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: 78,
            STRIKE_UPPER_F_KEY: 80,
        },
    )
    catalog.write_data([weather_instrument], skip_disjoint_check=True)
    write_records(
        catalog,
        [
            NwsClimateDay(
                station=_STATION,
                climate_day=dt.date(2026, 9, 5),
                tmax_f=79,
                tmin_f=63,
                tavg_f=71,
                tavg_flag=None,
                tmax_flag=None,
                tmin_flag=None,
                is_final=True,
                correction_flag=False,
                revision_seq=1,
                is_superseded=False,
                issuing_office="KLAX",
                issuance_time_ns=instrument.ts_init - 240_000_000_000,
                retrieved_at_ns=instrument.ts_init,
                parser_version="test",
                registry_version="test",
                raw_sha256="b" * 64,
                source_channel="test",
                schema_version=CLIMATE_DAY_SCHEMA_VERSION,
                ts_event=instrument.ts_init,
            )
        ],
    )


def _seed_fake_node(tmp_path: Path, *, store_path: Path) -> Path:
    """A fake `/proc` tree, never the real one, whose one node's environ
    names `store_path` so the REVISE-1 pre-flight returns MATCH."""
    proc_root = tmp_path / "proc"
    _write_cmdline(proc_root, _NODE_PID, _NODE_CMDLINE)
    _write_environ(proc_root, _NODE_PID, {"POLYMARKET_US_EXEC_STATE_DB": str(store_path)})
    return proc_root


# ---------------------------------------------------------------------------
# happy walk: fill -> record -> latch join -> scored row -> both consumers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_fill_chain_scores_a_real_taker_fill_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    order_id = "ord-i5-happy"
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_accept_fill_body(slug, order_id=order_id, last_px="0.37", commission="0.03"),
    )

    # (1) drive the REAL accept-fill branch: record_fill -> retire -> publish.
    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    record = _reopened_fill_record(rig.store_path, order_id)
    assert record is not None
    assert isinstance(record, DurableFillRecord)
    assert record.fee_reconciled is True
    assert record.cumulative_qty == Decimal(1)
    assert record.cumulative_cost == Decimal("0.37")
    assert record.cumulative_fee == Decimal("0.03")

    current = rig.submit_intent_latch.current()
    assert current is not None
    assert current.state is SubmitIntentState.RETIRED

    submitted = [e for e in rig.order_events if isinstance(e, OrderSubmitted)]
    filled = [e for e in rig.order_events if isinstance(e, OrderFilled)]
    assert len(submitted) == 1
    assert len(filled) == 1

    # (2) the taken trial-day latch (LAX, 2026-09-05, entry_ask 0.35) + the
    # FINAL NWS climate day the join needs to decide `held`.
    instrument_id = str(rig.instrument.id)
    entry_ask = Decimal("0.35")
    store = SqliteStateStore(rig.store_path)
    latch_key = _seed_latch(store, instrument_id=instrument_id, ask=entry_ask)
    store.close()

    catalog_base = tmp_path / "catalog"
    _seed_weather_instrument_and_final(catalog_base, instrument=rig.instrument)

    # (3) the BINDING wrapper argv, plus an explicit --catalog-base (the
    # production default is a real user path this test must never touch),
    # and a fake /proc node so the node-env pre-flight returns MATCH.
    manifest_path = _write_manifest(tmp_path)
    derived_dir = tmp_path / "derived"
    proc_root = _seed_fake_node(tmp_path, store_path=rig.store_path)
    argv = [
        "--city",
        _CITY,
        "--family-manifest",
        str(manifest_path),
        "--derived-dir",
        str(derived_dir),
        "--fill-source",
        str(rig.store_path),
        "--catalog-base",
        str(catalog_base),
    ]
    assert main(argv, proc_root=proc_root) == 0

    scored = read_scored_trials(derived_dir)
    assert len(scored) == 1
    row = scored[0]
    assert row.trial_id == latch_key
    expected_fill_px = record.cumulative_cost / record.cumulative_qty
    expected_fee = record.cumulative_fee / record.cumulative_qty
    assert row.fill_px == expected_fill_px
    assert row.fee == expected_fee
    assert row.entry_ask == entry_ask
    assert row.slippage == row.fill_px - entry_ask
    assert row.held is True  # tmax_f=79 inside the seeded closed [78, 80] bucket

    provenance = json.loads((derived_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance == {"provenance": "live"}

    fill_order_path = derived_dir / "fill_order.jsonl"
    fill_order_lines = [
        json.loads(line)
        for line in fill_order_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(fill_order_lines) == 1
    assert fill_order_lines[0]["trial_id"] == latch_key
    assert fill_order_lines[0]["filled_at_ns"] == record.ts_event

    excluded_path = derived_dir / _EXCLUDED_FILLS_ARTEFACT_NAME
    assert not excluded_path.exists()

    fill_order_text_before = fill_order_path.read_text(encoding="utf-8")
    provenance_text_before = (derived_dir / "provenance.json").read_text(encoding="utf-8")

    # (4) idempotent re-run: still exactly one row, sidecars unchanged,
    # excluded_fills.jsonl still absent.
    assert main(argv, proc_root=proc_root) == 0
    assert len(read_scored_trials(derived_dir)) == 1
    assert fill_order_path.read_text(encoding="utf-8") == fill_order_text_before
    assert (derived_dir / "provenance.json").read_text(encoding="utf-8") == provenance_text_before
    assert not excluded_path.exists()

    # (5) v1's fill-time numerator and v2's own reader both see the fill.
    assert (
        fill_time_count.count_filled_takes(
            rig.store_path, family_prefix=_FAMILY_PREFIX, since_climate_day=_DAY_ISO
        )
        == 1
    )
    v2_rows = family_tally_v2.read_scored_trials(derived_dir)
    assert any(r.trial_id == latch_key for r in v2_rows)


# ---------------------------------------------------------------------------
# a partial fill: recorded in full, excluded before scoring (ruling Q1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_partial_fill_is_recorded_but_excluded_from_scoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    slug = _slug(rig.instrument)
    order_id = "ord-i5-partial"
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_partial_fill_body(slug, order_id=order_id),
    )

    with _accept_fill_caps():
        await rig.client._connect()
        await rig.client._submit_order(rig.limit_buy())
        await rig.client._disconnect()

    record = _reopened_fill_record(rig.store_path, order_id)
    assert record is not None
    assert isinstance(record, DurableFillRecord)
    assert record.cumulative_qty == Decimal("0.37")

    instrument_id = str(rig.instrument.id)
    store = SqliteStateStore(rig.store_path)
    _seed_latch(store, instrument_id=instrument_id, ask=Decimal("0.37"))
    store.close()

    manifest_path = _write_manifest(tmp_path)
    derived_dir = tmp_path / "derived"
    proc_root = _seed_fake_node(tmp_path, store_path=rig.store_path)
    argv = [
        "--city",
        _CITY,
        "--family-manifest",
        str(manifest_path),
        "--derived-dir",
        str(derived_dir),
        "--fill-source",
        str(rig.store_path),
        "--catalog-base",
        str(tmp_path / "catalog"),
    ]

    assert main(argv, proc_root=proc_root) == 0
    assert read_scored_trials(derived_dir) == ()

    excluded_path = derived_dir / _EXCLUDED_FILLS_ARTEFACT_NAME
    lines = [
        json.loads(line)
        for line in excluded_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["reason"] == "partial_fill"
    assert lines[0]["venue_order_id"] == order_id

    excluded = family_tally_v2.read_excluded_fills(derived_dir)
    assert len(excluded) == 1
    assert excluded[0].venue_order_id == order_id
    assert excluded[0].reason == "partial_fill"

    coverage = family_tally_v2.coverage_rows(excluded, frozenset())
    assert len(coverage) == 1
    assert coverage[0].reason == "partial_fill"
    assert coverage[0].count == 1
