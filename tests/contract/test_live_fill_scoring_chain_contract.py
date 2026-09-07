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
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

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
from breezy.settlement.trial_scorer import ScoreRefusal

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import family_tally_v2
import fill_time_count
from score_live_trials import (
    _EXCLUDED_FILLS_ARTEFACT_NAME,
    _UNRESOLVED_TAKES_ARTEFACT_NAME,
    find_unresolved_takes,
    main,
    score_live_trials,
)

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
    _BASE_NS,
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


# ---------------------------------------------------------------------------
# L-27, recursive: guard BOTH real trees this module's production defaults
# point at (`DEFAULT_DERIVED_DIR`/`DEFAULT_NWS_CATALOG_BASE` in
# `scripts/analysis/score_live_trials.py`) -- every test in this module
# passes an explicit `--catalog-base`/`derived_dir` under `tmp_path`, so
# neither tree should ever change; this is the module's own proof of that,
# not a test of behaviour. `Path.home()` is resolved once, at import time.
# ---------------------------------------------------------------------------

_REAL_HOME = Path.home()
_REAL_SCORED_TRIALS_DIR = _REAL_HOME / ".local/share/breezy/derived/scored_trials"
_REAL_CATALOG_DIR = _REAL_HOME / ".local/share/breezy/catalog"

#: `quote_tape/` is the LIVE recorder's own continuous capture namespace
#: (`src/breezy/persistence/catalog.py` never writes there -- confirmed by
#: grep; `open_station_catalog`/`write_records`, the only catalog writers
#: this driver or `trial_scorer.py` ever call, land under a wholly separate
#: `<venue>/<city>/...` layout). On this host the recorder runs continuously
#: under systemd (`g14-capture-is-systemd-now`) and appends to it every few
#: seconds regardless of anything this test module does -- confirmed
#: empirically (11/11 runs) by a byte-for-byte diff always isolated to one
#: actively-growing `quote_tape/.../instrument_status_*.feather` file, never
#: to a path this suite could write. Excluded here so the guard still catches
#: this suite's own mutations to the parts of the catalog it CAN reach,
#: without flaking on a concurrent, unrelated writer (`one-tree-many-agents-
#: fakes-test-failures`).
_LIVE_RECORDER_SUBTREE = "quote_tape"


def _tree_snapshot(
    root: Path, *, exclude_top_level: str | None = None
) -> tuple[tuple[str, int, int], ...] | None:
    """A recursive `(relpath, st_size, st_mtime_ns)` snapshot of every path
    under `root`, or `None` when `root` does not exist at all. Paths whose
    top-level component under `root` equals `exclude_top_level` are skipped."""
    if not root.exists():
        return None
    rows = []
    for p in root.rglob("*"):
        relpath = p.relative_to(root)
        if exclude_top_level is not None and relpath.parts[:1] == (exclude_top_level,):
            continue
        rows.append((relpath.as_posix(), p.stat().st_size, p.stat().st_mtime_ns))
    return tuple(sorted(rows))


@pytest.fixture(scope="module", autouse=True)
def _guard_real_derived_and_catalog_trees_untouched() -> Iterator[None]:
    before_scored = _tree_snapshot(_REAL_SCORED_TRIALS_DIR)
    before_catalog = _tree_snapshot(_REAL_CATALOG_DIR, exclude_top_level=_LIVE_RECORDER_SUBTREE)
    yield
    assert _tree_snapshot(_REAL_SCORED_TRIALS_DIR) == before_scored, (
        "a test in test_live_fill_scoring_chain_contract.py modified the REAL "
        f"derived tree at {_REAL_SCORED_TRIALS_DIR}"
    )
    assert (
        _tree_snapshot(_REAL_CATALOG_DIR, exclude_top_level=_LIVE_RECORDER_SUBTREE)
        == before_catalog
    ), (
        "a test in test_live_fill_scoring_chain_contract.py modified the REAL "
        f"catalog tree at {_REAL_CATALOG_DIR} (outside quote_tape/)"
    )

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
    # `score_trial` (trial_scorer.py ~:150-208): pnl = 1{held} - fill_px - fee,
    # Decimal arithmetic throughout; held is True here, so 1{held} == 1.
    assert row.pnl == Decimal(1) - row.fill_px - row.fee
    assert row.settlement_basis == "nws_final"

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

    # (6) `find_unresolved_takes` keys on FILL PRESENCE (a `DurableFillRecord`
    # whose `instrument_id` matches the taken latch's), never the account-wide
    # submit-intent singleton (that is only carried as diagnostic context on
    # an `UnresolvedTake` row, F1) -- this trial's fill is present in the same
    # store the latch lives in, so it is filtered out of the unresolved set
    # and `unresolved_takes.jsonl` (I4, VISIBILITY ONLY) is never written.
    assert not (derived_dir / _UNRESOLVED_TAKES_ARTEFACT_NAME).exists()
    assert (
        find_unresolved_takes(
            rig.store_path,
            family_prefix=_FAMILY_PREFIX,
            city=_CITY,
            since_climate_day=_DAY_ISO,
        )
        == ()
    )


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


# ---------------------------------------------------------------------------
# driver-level refusals: no NWS record at all, and a preliminary-only record
# (`score_trial`'s `_pending_reason`, trial_scorer.py ~:264-271)
# ---------------------------------------------------------------------------

_GL9_DAY = dt.date(2026, 9, 6)
_GL9_DAY_ISO = _GL9_DAY.isoformat()


def _gl9_fill_row(
    *,
    trial_id: str,
    climate_day: str = _GL9_DAY_ISO,
    fill_px: str = "0.42",
    entry_ask: str = "0.40",
) -> dict[str, Any]:
    """A `read_filled_trials_jsonl`-shaped row (`_filled_trial_from_json`,
    score_live_trials.py ~:447-471) carrying its own `bucket` inline, so
    these driver-level tests need no persisted `BinaryOption` instrument --
    only the NWS settlement record under test is written to the catalog."""
    return {
        "trial_id": trial_id,
        "station": _STATION,
        "climate_day": climate_day,
        "instrument_id": f"{trial_id}-instrument",
        "fill_px": fill_px,
        "fee": "0.01",
        "qty": "1",
        "filled_at_ns": _BASE_NS,
        "entry_ask": entry_ask,
        "scheduled_release_at_ns": _BASE_NS,
        "venue_settlement_tmax_f": None,
        "bucket": {"lower_f": 78, "upper_f": 80},
    }


def _write_climate_day(
    catalog_base: Path, *, climate_day: dt.date, is_final: bool, tmax_f: int = 79
) -> None:
    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(
        catalog,
        [
            NwsClimateDay(
                station=_STATION,
                climate_day=climate_day,
                tmax_f=tmax_f,
                tmin_f=63,
                tavg_f=71,
                tavg_flag=None,
                tmax_flag=None,
                tmin_flag=None,
                is_final=is_final,
                correction_flag=False,
                revision_seq=1,
                is_superseded=False,
                issuing_office="KLAX",
                issuance_time_ns=_BASE_NS - 240_000_000_000,
                retrieved_at_ns=_BASE_NS,
                parser_version="test",
                registry_version="test",
                raw_sha256="c" * 64,
                source_channel="test",
                schema_version=CLIMATE_DAY_SCHEMA_VERSION,
                ts_event=_BASE_NS,
            )
        ],
    )


def test_a_missing_final_climate_day_refuses_no_record(tmp_path: Path) -> None:
    """No NWS record at all for the trial's station-day: `_pending_reason`
    returns `"no_record"` when `record is None`. Exercised at the driver
    level (`score_live_trials`) -- the pure-function case is already pinned
    by `test_settlement_trial_scorer.py`; this proves the DRIVER reaches that
    same refusal when its own catalog read comes back empty."""
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    open_station_catalog(catalog_base, _VENUE, _CITY)  # no NwsClimateDay written
    trial_id = "gl9-no-record"
    fills_path.write_text(json.dumps(_gl9_fill_row(trial_id=trial_id)) + "\n", encoding="utf-8")

    scored, refused, excluded = score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )

    assert scored == ()
    assert excluded == ()
    assert len(refused) == 1
    refusal = refused[0]
    assert isinstance(refusal, ScoreRefusal)
    assert refusal.reason == "no_record"
    assert refusal.trial_id == trial_id
    assert read_scored_trials(derived_dir) == ()

    # `main` itself must exit 0 for a refused-but-not-erroring run -- exit
    # code only, no stdout/log-text assertion (that belongs to
    # `test_main_prints_the_excluded_fills_table` in test_score_live_trials.py).
    manifest_path = _write_manifest(tmp_path)
    cli_derived_dir = tmp_path / "derived_cli"
    argv = [
        "--city",
        _CITY,
        "--family-manifest",
        str(manifest_path),
        "--derived-dir",
        str(cli_derived_dir),
        "--fills",
        str(fills_path),
        "--catalog-base",
        str(catalog_base),
    ]
    assert main(argv, proc_root=tmp_path / "unused_proc") == 0


def test_a_preliminary_only_climate_day_refuses_preliminary_only(tmp_path: Path) -> None:
    """A record exists for the station-day but `is_final` is `False`:
    `_pending_reason` returns `"preliminary_only"`."""
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    _write_climate_day(catalog_base, climate_day=_GL9_DAY, is_final=False)
    trial_id = "gl9-preliminary-only"
    fills_path.write_text(json.dumps(_gl9_fill_row(trial_id=trial_id)) + "\n", encoding="utf-8")

    scored, refused, excluded = score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )

    assert scored == ()
    assert excluded == ()
    assert len(refused) == 1
    refusal = refused[0]
    assert isinstance(refusal, ScoreRefusal)
    assert refusal.reason == "preliminary_only"
    assert refusal.trial_id == trial_id
    assert read_scored_trials(derived_dir) == ()


# ---------------------------------------------------------------------------
# admit-gate boundary (`_admit_fill`, score_live_trials.py ~:351-397). The
# enforced relation is `fill_px >= entry_ask - tick` -- a LOWER bound only:
# a fill strictly worse than one tick below the latch ask is excluded
# (`"fill_below_ask"`); a fill exactly at that bound, or anywhere at or
# above it (including far BETTER than the ask itself), is admitted. This is
# deliberately not the same rule as L-25's `fill_px <= ask` check, which is
# the PAPER-REPLAY guard (an upper bound, in a different execution model,
# in a different module) -- `_admit_fill` never rejects a fill for being
# too good.
# ---------------------------------------------------------------------------

_ADMIT_GATE_DAY = dt.date(2026, 9, 6)
_ADMIT_GATE_DAY_ISO = _ADMIT_GATE_DAY.isoformat()
_ADMIT_GATE_ENTRY_ASK = "0.37"


def test_a_fill_exactly_one_tick_below_the_ask_is_admitted_and_scored(tmp_path: Path) -> None:
    """entry_ask=0.37, tick=_TICK=0.01 (default): last_px=0.36 sits exactly
    on the boundary `entry_ask - tick`. `_admit_fill`'s test is strict `<`,
    so a fill AT the bound is not below it and is admitted."""
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    _write_climate_day(catalog_base, climate_day=_ADMIT_GATE_DAY, is_final=True, tmax_f=79)
    trial_id = "gl9-admit-boundary-admitted"
    fills_path.write_text(
        json.dumps(
            _gl9_fill_row(
                trial_id=trial_id,
                climate_day=_ADMIT_GATE_DAY_ISO,
                fill_px="0.36",
                entry_ask=_ADMIT_GATE_ENTRY_ASK,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = _write_manifest(tmp_path)
    argv = [
        "--city",
        _CITY,
        "--family-manifest",
        str(manifest_path),
        "--derived-dir",
        str(derived_dir),
        "--fills",
        str(fills_path),
        "--catalog-base",
        str(catalog_base),
    ]

    assert main(argv, proc_root=tmp_path / "unused_proc") == 0

    scored = read_scored_trials(derived_dir)
    assert len(scored) == 1
    row = scored[0]
    assert row.trial_id == trial_id
    assert row.slippage == Decimal("-0.01")
    assert not (derived_dir / _EXCLUDED_FILLS_ARTEFACT_NAME).exists()


def test_a_fill_two_ticks_below_the_ask_is_excluded_fill_below_ask(tmp_path: Path) -> None:
    """last_px=0.35 is one further tick below the `entry_ask - tick`
    boundary -- strictly below it, so `_admit_fill` excludes the fill with
    `"fill_below_ask"` before it ever reaches `score_trial`."""
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    _write_climate_day(catalog_base, climate_day=_ADMIT_GATE_DAY, is_final=True, tmax_f=79)
    trial_id = "gl9-admit-boundary-excluded"
    fills_path.write_text(
        json.dumps(
            _gl9_fill_row(
                trial_id=trial_id,
                climate_day=_ADMIT_GATE_DAY_ISO,
                fill_px="0.35",
                entry_ask=_ADMIT_GATE_ENTRY_ASK,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = _write_manifest(tmp_path)
    argv = [
        "--city",
        _CITY,
        "--family-manifest",
        str(manifest_path),
        "--derived-dir",
        str(derived_dir),
        "--fills",
        str(fills_path),
        "--catalog-base",
        str(catalog_base),
    ]

    assert main(argv, proc_root=tmp_path / "unused_proc") == 0

    assert read_scored_trials(derived_dir) == ()
    excluded_path = derived_dir / _EXCLUDED_FILLS_ARTEFACT_NAME
    lines = [
        json.loads(line)
        for line in excluded_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["reason"] == "fill_below_ask"
    assert lines[0]["trial_id"] == trial_id
