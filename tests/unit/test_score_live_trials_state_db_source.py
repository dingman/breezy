"""RED-first tests for the live state-DB fill reader (I2, `docs/plans/
LIVE_FILL_SCORING_CHAIN_2026-09-05.md`): `read_filled_trials_state_db`, the
widened `_admit_fill` (`fill_below_ask`/`fee_unverified`), the store positive
control (BLOCK-1.2), the node-env pre-flight (REVISE-1/REVISE-4), the
`excluded_fills.jsonl` artefact (3.0(c)), and the CLI's two-source contract
(3.0(a)).

Every fixture seeds the exec `SqliteStateStore` with the SHIPPED encoders --
`DurableFillRecord.to_bytes()` (`breezy.adapters.polymarket_us.exec.client`)
and `TrialDayRecord.to_bytes()` (`breezy.strategy.current_rung_hold.
trial_day_latch`) -- never a hand-written JSON blob, so this suite proves
the real on-disk encoding, not a second copy of it (I5 X1 mandate).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

# module ref (for monkeypatching DEFAULT_NWS_CATALOG_BASE) + the public API
import score_live_trials as slt_module
from score_live_trials import (
    _EXCLUDED_FILLS_ARTEFACT_NAME,
    FillSourceUnreadableError,
    NodeStorePreflightRefused,
    StorePositiveControlFailedError,
    _with_scheduled_release_at_ns,
    main,
    read_filled_trials_state_db,
    score_live_trials,
)

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
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
from breezy.registry.settlement_clock import settlement_deadline_ns
from breezy.registry.sites import default_registry
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

_BASE_NS = int(dt.datetime(2026, 9, 5, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"score-live-trials-state-db-test").hexdigest()
_STATION = "LAX"
_CITY = "LAX"
_VENUE = "polymarket_us"
_DAY = dt.date(2026, 9, 5)
_DAY_ISO = _DAY.isoformat()
_FAMILY_PREFIX = "current_rung_hold/trial/"
_INSTRUMENT_ID = "LAX-2026-09-05-gte78lt80f"

_MANIFEST_PAYLOAD: dict[str, Any] = {
    "family_id": "pm_us_crh_v2",
    "venue": _VENUE,
    "trial_id_prefix": _FAMILY_PREFIX,
    "d0_climate_day": _DAY_ISO,
    "boundary_artefact_path": "deploy/families/gs_boundary_pm_us_crh_v2.json",
    "boundary_inputs_sha256": "a" * 64,
    "stations": [_STATION],
    "status": "REGISTERED",
}


def _write_manifest(tmp_path: Path, **overrides: Any) -> Path:
    payload = dict(_MANIFEST_PAYLOAD, **overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _latch_key(station: str, climate_day: str) -> str:
    return f"{_FAMILY_PREFIX}{station}/{climate_day}"


def _seed_latch(
    store: SqliteStateStore,
    *,
    station: str = _STATION,
    climate_day: str = _DAY_ISO,
    instrument_id: str = _INSTRUMENT_ID,
    ask: Decimal = Decimal("0.40"),
    reason: str = "taken",
    latched_at_ns: int = _BASE_NS,
) -> str:
    key = _latch_key(station, climate_day)
    record = TrialDayRecord(
        latched_at_ns=latched_at_ns, instrument_id=instrument_id, ask=ask, reason=reason
    )
    store.set(key, record.to_bytes())
    return key


def _seed_fill(
    store: SqliteStateStore,
    *,
    venue_order_id: str,
    instrument_id: str = _INSTRUMENT_ID,
    cumulative_qty: Decimal = Decimal(1),
    cumulative_cost: Decimal = Decimal("0.42"),
    cumulative_fee: Decimal = Decimal("0.01"),
    fee_reconciled: bool = True,
    ts_event: int = _BASE_NS,
) -> None:
    record = DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"c-{venue_order_id}",
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=cumulative_qty,
        cumulative_cost=cumulative_cost,
        cumulative_fee=cumulative_fee,
        fee_reconciled=fee_reconciled,
        ts_event=ts_event,
    )
    store.set(f"{FILL_KEY_PREFIX}{venue_order_id}", record.to_bytes())


def _reader_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "family_prefix": _FAMILY_PREFIX,
        "city": _CITY,
        "cli_location": _STATION,
        "since_climate_day": _DAY_ISO,
        "stations": (_STATION,),
    }
    kwargs.update(overrides)
    return kwargs


def _driver_kwargs(tmp_path: Path, store_path: Path, **overrides: Any) -> dict[str, Any]:
    proc_root = tmp_path / "proc"
    proc_root.mkdir(exist_ok=True)
    kwargs: dict[str, Any] = {
        "fill_source_path": store_path,
        "family_prefix": _FAMILY_PREFIX,
        "since_climate_day": _DAY_ISO,
        "stations": (_STATION,),
        "catalog_base": tmp_path / "catalog",
        "venue": _VENUE,
        "city": _CITY,
        "derived_dir": tmp_path / "derived",
        "now_ns": _BASE_NS,
        "proc_root": proc_root,
    }
    kwargs.update(overrides)
    return kwargs


def _write_cmdline(proc_root: Path, pid: int, argv_parts: list[bytes]) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / "cmdline").write_bytes(b"\0".join(argv_parts) + b"\0")


def _write_environ(proc_root: Path, pid: int, env: dict[str, str]) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True, exist_ok=True)
    payload = b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0"
    (pid_dir / "environ").write_bytes(payload)


def _seed_instrument_and_final(catalog_base: Path) -> str:
    """Writes the instrument + FINAL climate day, returns `str(instrument.id)`
    -- the JOIN key `score_live_trials.py` actually uses (`_read_bucket_facts_
    by_instrument_id`), which is NOT the bare symbol string."""
    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    instrument = BinaryOption(
        instrument_id=InstrumentId(symbol=Symbol(_INSTRUMENT_ID), venue=Venue("POLYUS")),
        raw_symbol=Symbol(_INSTRUMENT_ID),
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
            SETTLEMENT_STATION_KEY: _STATION,
            CLIMATE_DAY_KEY: _DAY_ISO,
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: 78,
            STRIKE_UPPER_F_KEY: 80,
        },
    )
    catalog.write_data([instrument], skip_disjoint_check=True)
    write_records(
        catalog,
        [
            NwsClimateDay(
                station=_STATION,
                climate_day=_DAY,
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
    return str(instrument.id)


# ---------------------------------------------------------------------------
# the join: instrument_id -> taken latch -> FilledTrial
# ---------------------------------------------------------------------------


def test_one_fill_and_one_taken_latch_yields_one_filled_trial(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    latch_key = _seed_latch(store, ask=Decimal("0.40"))
    _seed_fill(
        store, venue_order_id="v1", cumulative_cost=Decimal("0.42"), cumulative_fee=Decimal("0.01")
    )
    store.close()

    trials, exclusions, fee_map = read_filled_trials_state_db(store_path, **_reader_kwargs())

    assert exclusions == ()
    assert len(trials) == 1
    trial = trials[0]
    assert trial.trial_id == latch_key
    assert trial.station == _STATION
    assert trial.climate_day == _DAY_ISO
    assert trial.entry_ask == Decimal("0.40")
    assert trial.fill_px == Decimal("0.42")
    assert trial.fee == Decimal("0.01")
    assert trial.qty == Decimal(1)
    assert fee_map[latch_key] == (True, "v1")

    # correct scheduled_release_at_ns, assert against the promoted helper for
    # a known city/day (LAX, 2026-09-05).
    resolved = _with_scheduled_release_at_ns(trial, venue=_VENUE, city=_CITY)
    expected_deadline = default_registry().settlement_deadline(_VENUE, _CITY)
    assert resolved.scheduled_release_at_ns == settlement_deadline_ns(expected_deadline, _DAY)


def test_no_taken_latch_is_excluded_with_blank_identity_fields(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    # A decoy latch for a DIFFERENT instrument/day so the store positive
    # control passes -- this test is about the join missing, not the store.
    _seed_latch(store, climate_day="2026-09-01", instrument_id="decoy-instrument")
    _seed_fill(store, venue_order_id="v1")
    store.close()

    trials, exclusions, fee_map = read_filled_trials_state_db(store_path, **_reader_kwargs())

    assert trials == ()
    assert fee_map == {}
    assert len(exclusions) == 1
    exclusion = exclusions[0]
    assert exclusion.reason == "no_taken_latch"
    assert exclusion.trial_id == ""
    assert exclusion.station == ""
    assert exclusion.climate_day == ""
    assert exclusion.venue_order_id == "v1"


def test_two_fill_records_on_one_latch_excludes_both_as_duplicate(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    latch_key = _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")
    _seed_fill(store, venue_order_id="v2")
    store.close()

    trials, exclusions, fee_map = read_filled_trials_state_db(store_path, **_reader_kwargs())

    assert trials == ()
    assert fee_map == {}
    assert len(exclusions) == 2
    assert {e.venue_order_id for e in exclusions} == {"v1", "v2"}
    for exclusion in exclusions:
        assert exclusion.reason == "duplicate_fill_for_latch"
        assert exclusion.trial_id == latch_key
        assert exclusion.station == _STATION
        assert exclusion.climate_day == _DAY_ISO


def test_an_instrument_matching_more_than_one_taken_latch_is_ambiguous(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store, climate_day=_DAY_ISO, instrument_id=_INSTRUMENT_ID)
    _seed_latch(store, climate_day="2026-09-06", instrument_id=_INSTRUMENT_ID)
    _seed_fill(store, venue_order_id="v1")
    store.close()

    trials, exclusions, fee_map = read_filled_trials_state_db(store_path, **_reader_kwargs())

    assert trials == ()
    assert fee_map == {}
    assert len(exclusions) == 1
    assert exclusions[0].reason == "ambiguous_latch"
    assert exclusions[0].venue_order_id == "v1"


def test_a_paper_replay_latch_key_never_matches(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    paper_key = f"paper_replay/{_latch_key(_STATION, _DAY_ISO)}"
    record = TrialDayRecord(
        latched_at_ns=_BASE_NS, instrument_id=_INSTRUMENT_ID, ask=Decimal("0.40"), reason="taken"
    )
    store.set(paper_key, record.to_bytes())
    _seed_latch(store)  # the REAL latch -- so the positive control still passes
    _seed_fill(store, venue_order_id="v1")
    store.close()

    trials, _exclusions, _fee_map = read_filled_trials_state_db(store_path, **_reader_kwargs())

    assert len(trials) == 1  # only the real latch joins; the paper key is inert


def test_an_open_writer_connection_does_not_block_the_read(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)  # left OPEN across the read
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")

    trials, exclusions, _fee_map = read_filled_trials_state_db(store_path, **_reader_kwargs())

    assert exclusions == ()
    assert len(trials) == 1
    store.close()


# ---------------------------------------------------------------------------
# store readability and the positive control (BLOCK-1.2)
# ---------------------------------------------------------------------------


def test_an_absent_store_raises_fill_source_unreadable(tmp_path: Path) -> None:
    store_path = tmp_path / "does-not-exist.sqlite"
    with pytest.raises(FillSourceUnreadableError):
        read_filled_trials_state_db(store_path, **_reader_kwargs())


def test_an_unreadable_store_raises_fill_source_unreadable(tmp_path: Path) -> None:
    store_path = tmp_path / "not-a-db.sqlite"
    store_path.write_text("not a sqlite file", encoding="utf-8")
    with pytest.raises(FillSourceUnreadableError):
        read_filled_trials_state_db(store_path, **_reader_kwargs())


def test_a_zero_cumulative_qty_fill_raises_fill_source_unreadable(tmp_path: Path) -> None:
    """F1: a fill record that DECODES but carries `cumulative_qty == 0` would
    divide by zero computing `fill_px`/`fee` -- that is store corruption, not
    a fill-level exclusion, so the reader refuses the whole run rather than
    joining it or silently dropping it."""
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1", cumulative_qty=Decimal(0))
    store.close()

    with pytest.raises(FillSourceUnreadableError):
        read_filled_trials_state_db(store_path, **_reader_kwargs())


def test_a_negative_cumulative_qty_fill_raises_fill_source_unreadable(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1", cumulative_qty=Decimal(-1))
    store.close()

    with pytest.raises(FillSourceUnreadableError):
        read_filled_trials_state_db(store_path, **_reader_kwargs())


def test_an_empty_but_valid_store_fails_the_positive_control(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    store.close()  # a real, empty, readable state table -- no latch at all

    with pytest.raises(StorePositiveControlFailedError):
        read_filled_trials_state_db(store_path, **_reader_kwargs())


def test_a_latch_for_another_census_station_passes_the_positive_control(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store, station="MDW", climate_day=_DAY_ISO, instrument_id="mdw-instr")
    store.close()

    trials, exclusions, _fee_map = read_filled_trials_state_db(
        store_path, **_reader_kwargs(stations=("LAX", "MDW", "MIA", "SFO"))
    )

    # positive control passes (no refusal); the run's own city (LAX) has no
    # latch or fill, so the join is empty -- an honest, valid result.
    assert trials == ()
    assert exclusions == ()


# ---------------------------------------------------------------------------
# the admission gate, fed by the reader's fee_reconciled/venue_order_id map
# ---------------------------------------------------------------------------


def test_a_partial_fill_from_the_state_db_is_excluded(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(
        store,
        venue_order_id="v1",
        cumulative_qty=Decimal("0.37"),
        cumulative_cost=Decimal("0.1554"),
    )
    store.close()

    _scored, _refused, excluded = score_live_trials(**_driver_kwargs(tmp_path, store_path))

    assert len(excluded) == 1
    assert excluded[0].reason == "partial_fill"
    assert excluded[0].venue_order_id == "v1"


def test_a_fill_more_than_one_tick_below_the_ask_is_excluded(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store, ask=Decimal("0.40"))
    _seed_fill(store, venue_order_id="v1", cumulative_cost=Decimal("0.38"))
    store.close()

    _scored, _refused, excluded = score_live_trials(**_driver_kwargs(tmp_path, store_path))

    assert len(excluded) == 1
    assert excluded[0].reason == "fill_below_ask"


def test_a_fill_exactly_one_tick_below_the_ask_is_not_excluded_by_the_ask_gate(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store, ask=Decimal("0.40"))
    _seed_fill(store, venue_order_id="v1", cumulative_cost=Decimal("0.39"))
    store.close()

    _scored, _refused, excluded = score_live_trials(**_driver_kwargs(tmp_path, store_path))

    assert not any(f.reason == "fill_below_ask" for f in excluded)


def test_an_unreconciled_fee_is_excluded_as_fee_unverified(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1", fee_reconciled=False)
    store.close()

    _scored, _refused, excluded = score_live_trials(**_driver_kwargs(tmp_path, store_path))

    assert len(excluded) == 1
    assert excluded[0].reason == "fee_unverified"
    assert excluded[0].venue_order_id == "v1"


# ---------------------------------------------------------------------------
# scoring idempotence through the state-DB source (unaffected by I2)
# ---------------------------------------------------------------------------


def test_two_runs_of_the_same_fill_write_one_scored_row(tmp_path: Path) -> None:
    # Seeds a FINAL climate-day record through the shipped catalog writer
    # (`write_records`) rather than asserting a refusal path -- the more
    # thorough proof that the state-DB source reaches an actual SCORED row,
    # not just an admitted one.
    catalog_base = tmp_path / "catalog"
    resolved_instrument_id = _seed_instrument_and_final(catalog_base)

    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store, ask=Decimal("0.40"), instrument_id=resolved_instrument_id)
    _seed_fill(store, venue_order_id="v1", instrument_id=resolved_instrument_id)
    store.close()

    kwargs = _driver_kwargs(tmp_path, store_path, catalog_base=catalog_base)
    scored_1, _refused_1, excluded_1 = score_live_trials(**kwargs)
    assert excluded_1 == ()
    assert len(scored_1) == 1

    scored_2, _refused_2, _excluded_2 = score_live_trials(**kwargs)
    assert scored_2 == ()  # `_unchanged_since_last_score` skips the repeat

    rows = list(read_scored_trials(tmp_path / "derived"))
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# node-env pre-flight (REVISE-1/REVISE-4)
# ---------------------------------------------------------------------------


def test_node_preflight_mismatch_makes_the_driver_refuse(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")
    store.close()

    proc_root = tmp_path / "proc"
    _write_cmdline(proc_root, 111, [b"/home/jon/breezy/.venv/bin/breezy-trade"])
    _write_environ(proc_root, 111, {"POLYMARKET_US_EXEC_STATE_DB": str(tmp_path / "OTHER.sqlite")})

    with pytest.raises(NodeStorePreflightRefused) as exc_info:
        score_live_trials(**_driver_kwargs(tmp_path, store_path, proc_root=proc_root))
    assert exc_info.value.reason == "node_store_mismatch"


def test_node_preflight_no_node_warns_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")
    store.close()

    proc_root = tmp_path / "proc"
    proc_root.mkdir()  # scannable, empty -- the scan succeeds, matches nothing

    with caplog.at_level(logging.WARNING):
        _scored, _refused, excluded = score_live_trials(
            **_driver_kwargs(tmp_path, store_path, proc_root=proc_root)
        )

    assert any("no anchored breezy-trade node" in r.message for r in caplog.records)
    assert excluded == ()  # continued past the warning


def test_node_preflight_match_continues_silently(tmp_path: Path) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")
    store.close()

    proc_root = tmp_path / "proc"
    _write_cmdline(proc_root, 111, [b"/home/jon/breezy/.venv/bin/breezy-trade"])
    _write_environ(proc_root, 111, {"POLYMARKET_US_EXEC_STATE_DB": str(store_path)})

    _scored, _refused, excluded = score_live_trials(
        **_driver_kwargs(tmp_path, store_path, proc_root=proc_root)
    )
    assert excluded == ()


def test_node_preflight_unknown_token_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: `node_store_path_check`'s closed enum is not enforced by the
    interpreter across the import boundary -- an unrecognised token must
    never silently fall through to the MATCH ("continue") branch. Fails
    closed via the existing `NodeStorePreflightRefused` channel, never the
    unexpected token itself."""
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")
    store.close()

    monkeypatch.setattr(slt_module, "node_store_path_check", lambda *a, **k: "SOME_UNKNOWN_TOKEN")

    with pytest.raises(NodeStorePreflightRefused) as exc_info:
        score_live_trials(**_driver_kwargs(tmp_path, store_path))
    assert "SOME_UNKNOWN_TOKEN" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# CLI: two-source contract, the artefact, the binding wrapper argv
# ---------------------------------------------------------------------------


def test_fills_and_fill_source_together_is_a_bad_flag_combination(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    exit_code = main(
        [
            "--fills",
            str(tmp_path / "fills.jsonl"),
            "--fill-source",
            str(tmp_path / "state.sqlite"),
            "--family-manifest",
            str(manifest_path),
            "--city",
            _CITY,
        ]
    )
    assert exit_code != 0


def test_missing_family_manifest_flag_is_non_zero(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--fill-source", str(tmp_path / "state.sqlite"), "--city", _CITY])
    assert exc_info.value.code != 0


def test_excluded_fills_artefact_has_exactly_eight_keys_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1", fee_reconciled=False)
    store.close()

    manifest_path = _write_manifest(tmp_path)
    derived_dir = tmp_path / "derived"
    monkeypatch.setenv("POLYMARKET_US_EXEC_STATE_DB", str(store_path))
    proc_root = tmp_path / "proc"
    proc_root.mkdir()  # scannable, empty -- NO_NODE, never the real /proc

    argv = [
        "--city",
        _CITY,
        "--family-manifest",
        str(manifest_path),
        "--derived-dir",
        str(derived_dir),
        "--catalog-base",
        str(tmp_path / "catalog"),
    ]
    assert main(argv, proc_root=proc_root) == 0
    assert main(argv, proc_root=proc_root) == 0  # re-run -- idempotent, appends nothing new

    artefact = derived_dir / _EXCLUDED_FILLS_ARTEFACT_NAME
    raw_lines = artefact.read_text(encoding="utf-8").splitlines()
    lines = [json.loads(line) for line in raw_lines if line.strip()]
    assert len(lines) == 1
    assert set(lines[0]) == {
        "trial_id",
        "station",
        "climate_day",
        "venue_order_id",
        "qty",
        "reason",
        "filled_at_ns",
        "scored_run_utc",
    }


def test_a_zero_cumulative_qty_fill_makes_main_refuse_without_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """F1, end to end through the CLI: `main()` exits non-zero, prints a
    value-free refusal line, writes no scored row and no artefact line --
    never the raw traceback a bare `decimal.DivisionByZero` would produce."""
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(
        store,
        venue_order_id="v1",
        cumulative_qty=Decimal(0),
        cumulative_cost=Decimal("0.42"),
        cumulative_fee=Decimal("0.01"),
    )
    store.close()

    manifest_path = _write_manifest(tmp_path)
    derived_dir = tmp_path / "derived"
    monkeypatch.setenv("POLYMARKET_US_EXEC_STATE_DB", str(store_path))
    proc_root = tmp_path / "proc"
    proc_root.mkdir()  # scannable, empty -- NO_NODE, never the real /proc

    exit_code = main(
        [
            "--city",
            _CITY,
            "--family-manifest",
            str(manifest_path),
            "--derived-dir",
            str(derived_dir),
            "--catalog-base",
            str(tmp_path / "catalog"),
        ],
        proc_root=proc_root,
    )

    assert exit_code != 0
    captured = capsys.readouterr()
    assert "score_live_trials: refused" in captured.err
    # value-free: neither the seeded cost/fee nor a raw traceback leaks
    assert "0.42" not in captured.err
    assert "0.01" not in captured.err
    assert "Traceback" not in captured.err
    assert not (derived_dir / _EXCLUDED_FILLS_ARTEFACT_NAME).exists()
    assert read_scored_trials(derived_dir) == ()


def test_the_binding_wrapper_argv_parses_and_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The BINDING command line (`score-live-trials-run.sh`): `--city
    --family-manifest --derived-dir` -- no `--fills`, no `--fill-source`, no
    `--catalog-base` (the production default)."""
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")
    store.close()

    manifest_path = _write_manifest(tmp_path)
    monkeypatch.setenv("POLYMARKET_US_EXEC_STATE_DB", str(store_path))
    monkeypatch.setattr(slt_module, "DEFAULT_NWS_CATALOG_BASE", tmp_path / "catalog")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()  # scannable, empty -- NO_NODE, never the real /proc

    exit_code = main(
        [
            "--city",
            _CITY,
            "--family-manifest",
            str(manifest_path),
            "--derived-dir",
            str(tmp_path / "derived"),
        ],
        proc_root=proc_root,
    )
    assert exit_code == 0


def test_a_sentinel_env_value_never_appears_in_stdout_stderr_or_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    store_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(store_path)
    _seed_latch(store)
    _seed_fill(store, venue_order_id="v1")
    store.close()

    manifest_path = _write_manifest(tmp_path)
    sentinel = "sentinel-9f3c7d-do-not-leak"
    monkeypatch.setenv("POLYMARKET_US_EXEC_STATE_DB", str(store_path))
    monkeypatch.setenv("BREEZY_TEST_SENTINEL_SECRET", sentinel)
    proc_root = tmp_path / "proc"
    proc_root.mkdir()  # scannable, empty -- NO_NODE, never the real /proc

    with caplog.at_level(logging.DEBUG):
        exit_code = main(
            [
                "--city",
                _CITY,
                "--family-manifest",
                str(manifest_path),
                "--derived-dir",
                str(tmp_path / "derived"),
                "--catalog-base",
                str(tmp_path / "catalog"),
            ],
            proc_root=proc_root,
        )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert sentinel not in captured.out
    assert sentinel not in captured.err
    assert all(sentinel not in record.getMessage() for record in caplog.records)
