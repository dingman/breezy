"""RED-first regression suite for L-38 (2026-09-16, `derived/
score_live_trials.log`): the scheduled scorer was run against ONLY the
retired v2 family's manifest (`deploy/families/pm_us_crh_v2.json`, trial-id
prefix `current_rung_hold/trial/`), so every fill under the LIVE
`pm_us_crh_cont` family's prefix (`continuous_rung_hold/trial/`) came back
`no_taken_latch` -- the latch was real, just never looked up under the
family's own prefix.

This fixture reproduces the real 2026-09-16 live-store shape (venue order
ids, prices, fees, instrument ids all copied from a read-only copy of the
live `exec_polymarket_us.sqlite`, decoded via the shipped encoders -- never
a hand-written JSON blob) for the five fills currently on that store:

  * MDW `tc-temp-mdwhigh-2026-09-15-gte80lt81f` -- admitted, scores.
  * MDW `tc-temp-mdwhigh-2026-09-15-gte82lt83f` -- admitted, scores.
  * SFO `tc-temp-sfohigh-2026-09-15-gte71lt72f` -- admitted, scores.
  * MIA `tc-temp-miahigh-2026-09-15-gte92lt93f^no` -- admitted-but-excluded,
    `no_side_first_order_residual` (NO-SIDE S5 bounded containment window).
  * MIA `tc-temp-miahigh-2026-09-13-gte91lt92f` -- admitted-but-excluded,
    `fee_unverified` (a resolver/GET-FILLED fill, pinned fee-unreconciled
    residual by PREREG v3).

`score_live_trials()` is called once per (city, manifest) pair -- exactly
what the fixed `deploy/systemd/score-live-trials-run.sh` now does (see
`test_score_live_trials_deploy.py::test_scorer_argv_pinned_per_family` for
the wrapper-level argv pin) -- proving the join now succeeds under the
family's OWN prefix while the v2 manifest's run over the SAME store still
correctly finds nothing (no v2-prefix latch exists for any of these five
fills), reproducing 2026-09-16's real log byte-for-byte in shape.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from score_live_trials import FillExclusion, score_live_trials

from breezy.adapters.polymarket_us.exec.client import (
    FILL_KEY_PREFIX,
    DurableFillRecord,
)
from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
)
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
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.settlement.trial_scorer import ScoredTrial, ScoreRefusal
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

_VENUE = "polymarket_us"
_V2_PREFIX = "current_rung_hold/trial/"
_CONT_PREFIX = "continuous_rung_hold/trial/"
_SHA = hashlib.sha256(b"l38-family-prefix-fixture").hexdigest()
_BASE_NS = int(dt.datetime(2026, 9, 15, 20, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


def _seed_latch(
    store: SqliteStateStore,
    *,
    station: str,
    climate_day: str,
    instrument_id: str,
    ask: Decimal,
    venue_order_id: str,
) -> None:
    key = f"{_CONT_PREFIX}{station}/{climate_day}/{instrument_id}"
    record = TrialDayRecord(
        latched_at_ns=_BASE_NS,
        instrument_id=instrument_id,
        ask=ask,
        reason="taken",
        venue_order_id=venue_order_id,
    )
    store.set(key, record.to_bytes())


def _seed_fill(
    store: SqliteStateStore,
    *,
    venue_order_id: str,
    instrument_id: str,
    cost: Decimal,
    fee: Decimal,
    fee_reconciled: bool,
    ts_event: int,
) -> None:
    record = DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"c-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=cost,
        cumulative_fee=fee,
        fee_reconciled=fee_reconciled,
        ts_event=ts_event,
    )
    store.set(f"{FILL_KEY_PREFIX}{venue_order_id}", record.to_bytes())


def _seed_instrument_and_final(
    catalog_base: Path,
    *,
    station: str,
    instrument_id: str,
    climate_day_iso: str,
    lower_f: int,
    upper_f: int,
    tmax_f: int,
) -> None:
    # `instrument_id` (the argument) is the FULL dotted string carried by
    # `DurableFillRecord.instrument_id`/`TrialDayRecord.instrument_id`
    # (e.g. "...gte80lt81f.POLYMARKET_US") -- a plain field, not a Nautilus
    # `InstrumentId`. `InstrumentId(symbol, venue).__str__` appends its OWN
    # ".{venue}" suffix, so the bare `Symbol` must be the slug WITHOUT that
    # trailing ".POLYMARKET_US" or `str(instrument.id)` would double it and
    # never match a fill's `instrument_id` at the bucket-facts join.
    bare_symbol = instrument_id.removesuffix(".POLYMARKET_US")
    catalog = open_station_catalog(catalog_base, _VENUE, station)
    instrument = BinaryOption(
        instrument_id=InstrumentId(symbol=Symbol(bare_symbol), venue=Venue("POLYMARKET_US")),
        raw_symbol=Symbol(bare_symbol),
        outcome="Yes",
        description="fixture",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=Price.from_str("0.01").precision,
        price_increment=Price.from_str("0.01"),
        size_precision=Quantity.from_str("1").precision,
        size_increment=Quantity.from_str("1"),
        activation_ns=0,
        expiration_ns=86_400_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: station,
            CLIMATE_DAY_KEY: climate_day_iso,
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: lower_f,
            STRIKE_UPPER_F_KEY: upper_f,
        },
    )
    catalog.write_data([instrument], skip_disjoint_check=True)
    write_records(
        catalog,
        [
            NwsClimateDay(
                station=station,
                climate_day=dt.date.fromisoformat(climate_day_iso),
                tmax_f=tmax_f,
                tmin_f=tmax_f - 15,
                tavg_f=tmax_f - 7,
                tavg_flag=None,
                tmax_flag=None,
                tmin_flag=None,
                is_final=True,
                correction_flag=False,
                revision_seq=1,
                is_superseded=False,
                issuing_office="TEST",
                issuance_time_ns=_BASE_NS - 240_000_000_000,
                retrieved_at_ns=_BASE_NS,
                parser_version="test",
                registry_version="test",
                raw_sha256=_SHA,
                source_channel="test",
                schema_version=CLIMATE_DAY_SCHEMA_VERSION,
                ts_event=_BASE_NS,
            )
        ],
    )


def _seed_unrelated_v2_positive_control(store: SqliteStateStore) -> None:
    """One genuine, pre-existing v2-prefix latch with no matching fill --
    mirrors the real store's own `current_rung_hold/trial/...` history
    (e.g. `current_rung_hold/trial/MDW/2026-09-04`) and exists ONLY to
    satisfy `read_filled_trials_state_db`'s store positive control
    (BLOCK-1.2) for the v2 manifest -- the v2-prefix census check scans the
    WHOLE store, not just these five fills, and a store with zero v2-prefix
    keys at all would refuse before ever reaching the join this suite is
    testing."""
    key = "current_rung_hold/trial/MDW/2026-09-04"
    record = TrialDayRecord(
        latched_at_ns=_BASE_NS - 900_000_000_000,
        instrument_id="tc-temp-mdwhigh-2026-09-04-gte70lt71f.POLYMARKET_US",
        ask=Decimal("0.30"),
        reason="taken",
        venue_order_id=None,
    )
    store.set(key, record.to_bytes())


def _seed_five_real_fills(store: SqliteStateStore) -> None:
    """Mirrors the five fills on the real 2026-09-16 live store copy
    exactly (venue order ids, prices, fees, instrument ids) -- decoded via
    `DurableFillRecord.from_bytes`/`TrialDayRecord.from_bytes` against a
    read-only copy of `exec_polymarket_us.sqlite`."""
    # MDW gte80lt81f, 2026-09-15 -- admitted, scores.
    _seed_latch(
        store,
        station="MDW",
        climate_day="2026-09-15",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte80lt81f.POLYMARKET_US",
        ask=Decimal("0.11"),
        venue_order_id="CGW2XWZQRVBA",
    )
    _seed_fill(
        store,
        venue_order_id="CGW2XWZQRVBA",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte80lt81f.POLYMARKET_US",
        cost=Decimal("0.11"),
        fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1789495204346084927,
    )
    # MDW gte82lt83f, 2026-09-15 -- admitted, scores.
    _seed_latch(
        store,
        station="MDW",
        climate_day="2026-09-15",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte82lt83f.POLYMARKET_US",
        ask=Decimal("0.24"),
        venue_order_id="CGWDCNJGEVB5",
    )
    _seed_fill(
        store,
        venue_order_id="CGWDCNJGEVB5",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte82lt83f.POLYMARKET_US",
        cost=Decimal("0.24"),
        fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1789496613740243932,
    )
    # SFO gte71lt72f, 2026-09-15 -- admitted, scores.
    _seed_latch(
        store,
        station="SFO",
        climate_day="2026-09-15",
        instrument_id="tc-temp-sfohigh-2026-09-15-gte71lt72f.POLYMARKET_US",
        ask=Decimal("0.44"),
        venue_order_id="CGY02FK3PVB7",
    )
    _seed_fill(
        store,
        venue_order_id="CGY02FK3PVB7",
        instrument_id="tc-temp-sfohigh-2026-09-15-gte71lt72f.POLYMARKET_US",
        cost=Decimal("0.44"),
        fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1789503126244713950,
    )
    # MIA gte92lt93f^no, 2026-09-15 -- admitted-but-excluded, NO-SIDE residual.
    _seed_latch(
        store,
        station="MIA",
        climate_day="2026-09-15",
        instrument_id="tc-temp-miahigh-2026-09-15-gte92lt93f^no.POLYMARKET_US",
        ask=Decimal("0.09"),
        venue_order_id="CGW8DJ23PVB2",
    )
    _seed_fill(
        store,
        venue_order_id="CGW8DJ23PVB2",
        instrument_id="tc-temp-miahigh-2026-09-15-gte92lt93f^no.POLYMARKET_US",
        cost=Decimal("0.09"),
        fee=Decimal("0.00"),
        fee_reconciled=True,
        ts_event=1789495939244552293,
    )
    store.set(
        NO_SIDE_FIRST_LIVE_ORDER_KEY,
        json.dumps(
            {
                "instrumentId": "tc-temp-miahigh-2026-09-15-gte92lt93f^no.POLYMARKET_US",
                "tsNs": 1789495939034652122,
                "venueOrderId": None,
            }
        ).encode("utf-8"),
    )
    # MIA gte91lt92f, 2026-09-13 -- admitted-but-excluded, resolver/GET-FILLED
    # fill pinned fee-unreconciled residual (PREREG v3).
    _seed_latch(
        store,
        station="MIA",
        climate_day="2026-09-13",
        instrument_id="tc-temp-miahigh-2026-09-13-gte91lt92f.POLYMARKET_US",
        ask=Decimal("0.70"),
        venue_order_id="CFJ485874TMM",
    )
    _seed_fill(
        store,
        venue_order_id="CFJ485874TMM",
        instrument_id="tc-temp-miahigh-2026-09-13-gte91lt92f.POLYMARKET_US",
        cost=Decimal("0.70"),
        fee=Decimal("0.00"),
        fee_reconciled=False,
        ts_event=1789319029809353347,
    )


def _score(
    tmp_path: Path,
    *,
    family_prefix: str,
    city: str,
    store_path: Path,
    catalog_base: Path,
) -> tuple[tuple[ScoredTrial, ...], tuple[ScoreRefusal, ...], tuple[FillExclusion, ...]]:
    proc_root = tmp_path / "proc" / city
    proc_root.mkdir(parents=True, exist_ok=True)
    return score_live_trials(
        fill_source_path=store_path,
        family_prefix=family_prefix,
        since_climate_day="2026-09-01",
        stations=("LAX", "MDW", "MIA", "SFO"),
        catalog_base=catalog_base,
        venue=_VENUE,
        city=city,
        derived_dir=tmp_path / "derived" / family_prefix.split("/")[0] / city,
        now_ns=_BASE_NS,
        proc_root=proc_root,
    )


def test_cont_manifest_scores_the_three_2026_09_15_takes_and_excludes_the_two_residuals(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_five_real_fills(store)
    _seed_unrelated_v2_positive_control(store)
    store.close()

    catalog_base = tmp_path / "catalog"
    _seed_instrument_and_final(
        catalog_base,
        station="MDW",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte80lt81f.POLYMARKET_US",
        climate_day_iso="2026-09-15",
        lower_f=80,
        upper_f=81,
        tmax_f=85,
    )
    _seed_instrument_and_final(
        catalog_base,
        station="MDW",
        instrument_id="tc-temp-mdwhigh-2026-09-15-gte82lt83f.POLYMARKET_US",
        climate_day_iso="2026-09-15",
        lower_f=82,
        upper_f=83,
        tmax_f=85,
    )
    _seed_instrument_and_final(
        catalog_base,
        station="SFO",
        instrument_id="tc-temp-sfohigh-2026-09-15-gte71lt72f.POLYMARKET_US",
        climate_day_iso="2026-09-15",
        lower_f=71,
        upper_f=72,
        tmax_f=73,
    )

    all_scored: list[ScoredTrial] = []
    all_refused: list[ScoreRefusal] = []
    all_excluded: list[FillExclusion] = []
    for city in ("LAX", "MDW", "MIA", "SFO"):
        scored, refused, excluded = _score(
            tmp_path,
            family_prefix=_CONT_PREFIX,
            city=city,
            store_path=store_path,
            catalog_base=catalog_base,
        )
        all_scored.extend(scored)
        all_refused.extend(refused)
        all_excluded.extend(excluded)

    assert all_refused == [], all_refused

    # Three genuine scored takes, climate_day 2026-09-15, all held=False --
    # the CLI FINAL tmax (85 MDW, 73 SFO) falls outside all three narrow
    # rungs, so this suite's own fixture settles every one a loss regardless
    # of bucket-boundary inclusivity.
    assert len(all_scored) == 3
    scored_by_trial_id = {row.trial_id: row for row in all_scored}
    assert len(scored_by_trial_id) == 3
    for row in all_scored:
        assert row.climate_day == "2026-09-15"
        assert row.held is False
        assert row.settlement_basis == "nws_final"
    scored_instruments = {row.instrument_id for row in all_scored}
    assert scored_instruments == {
        "tc-temp-mdwhigh-2026-09-15-gte80lt81f.POLYMARKET_US",
        "tc-temp-mdwhigh-2026-09-15-gte82lt83f.POLYMARKET_US",
        "tc-temp-sfohigh-2026-09-15-gte71lt72f.POLYMARKET_US",
    }

    # NO fill: excluded as NO-SIDE S5 residual, never scored.
    no_side_exclusions = [
        e for e in all_excluded if e.reason == "no_side_first_order_residual"
    ]
    assert len(no_side_exclusions) == 1
    assert no_side_exclusions[0].venue_order_id == "CGW8DJ23PVB2"
    assert no_side_exclusions[0].climate_day == "2026-09-15"
    assert no_side_exclusions[0].station == "MIA"

    # MIA 2026-09-13 fill: excluded fee_unverified -- the resolver/GET-FILLED
    # fill PREREG v3 pins as fee-unreconciled residual (matches the real
    # 2026-09-16 log line for this exact venue_order_id).
    fee_unverified = [e for e in all_excluded if e.reason == "fee_unverified"]
    assert len(fee_unverified) == 1
    assert fee_unverified[0].venue_order_id == "CFJ485874TMM"
    assert fee_unverified[0].climate_day == "2026-09-13"
    assert fee_unverified[0].station == "MIA"

    assert len(all_excluded) == 2


def test_v2_manifest_over_the_same_store_finds_none_of_the_five_v3_fills(
    tmp_path: Path,
) -> None:
    """Reproduces the L-38 defect signature itself: scoring the SAME store
    under the RETIRED v2 prefix still finds no genuine v2 latch for any of
    these five fills (they are all v3/cont latches) -- every one comes back
    `no_taken_latch`, exactly like 2026-09-16's real
    `derived/score_live_trials.log`. This is the OLD (broken) behaviour,
    kept as a regression pin so a future change cannot silently make v2
    swallow v3's fills instead of the reverse."""
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_five_real_fills(store)
    _seed_unrelated_v2_positive_control(store)
    store.close()

    catalog_base = tmp_path / "catalog"
    scored, refused, excluded = _score(
        tmp_path,
        family_prefix=_V2_PREFIX,
        city="MDW",
        store_path=store_path,
        catalog_base=catalog_base,
    )
    assert scored == ()
    assert refused == ()
    assert len(excluded) == 5
    assert all(e.reason == "no_taken_latch" for e in excluded)
    assert all(f"under {_V2_PREFIX!r}" in e.detail for e in excluded)
