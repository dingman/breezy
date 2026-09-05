"""RED-first tests for `scripts/analysis/score_live_trials.py` (6c driver,
review amendments). Covers: the JSONL reader (happy path + malformed rows
never abort the batch), the `instrument_unavailable` refusal path, the
`_already_fallback_scored` skip, `_next_score_seq`, the review-item-3
re-score-only-on-change skip, the review-item-4 duplicate-instrument-id
warning, one end-to-end fixture run that writes a parquet file the store
reader loads back, and the partial-fill admission gate (binding ruling,
`docs/evidence/grok_partial_fill_ruling_2026-09-04.md` Q1): `qty != 1` is
excluded fail-closed before scoring and reported in an exclusions table;
`qty <= 0` is refused loudly as malformed, never silently scored or dropped.

The shared `_fill_row()` fixture default `qty` is `"1"` (the v1 unit of
observation) -- it was `"10"` before this gate existed, which is now itself
a `multi_fill` exclusion case, so tests that are not about `qty` specifically
rely on the `"1"` default to keep scoring as before.
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

from score_live_trials import (
    FillExclusion,
    ProvenanceConflict,
    _admit_fill,
    _already_fallback_scored,
    _append_fill_order_entries,
    _next_score_seq,
    _read_bucket_facts_by_instrument_id,
    _unchanged_since_last_score,
    _validate_qty,
    _write_or_assert_live_provenance_sidecar,
    main,
    read_filled_trials_jsonl,
    score_live_trials,
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
from breezy.persistence.scored_trial_store import read_scored_trials, write_scored_trials
from breezy.settlement.trial_scorer import FilledTrial, ScoredTrial

_BASE_NS = int(dt.datetime(2026, 9, 1, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"score-live-trials-test").hexdigest()
_STATION = "LAX"
_DAY = dt.date(2026, 8, 31)
_DAY_ISO = _DAY.isoformat()
_VENUE = "polymarket_us"
_CITY = "LAX"


def _fill_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trial_id": "t1",
        "station": _STATION,
        "climate_day": _DAY_ISO,
        "instrument_id": "LAX-2026-08-31-gte78lt80f",
        "fill_px": "0.42",
        "fee": "0.01",
        "qty": "1",
        "filled_at_ns": _BASE_NS,
        "entry_ask": "0.40",
        "scheduled_release_at_ns": _BASE_NS,
        "venue_settlement_tmax_f": None,
        "bucket": {"lower_f": 78, "upper_f": 79},
    }
    row.update(overrides)
    return row


def _climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": _STATION,
        "climate_day": _DAY,
        "tmax_f": 79,
        "tmin_f": 63,
        "tavg_f": 71,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KLAX",
        "issuance_time_ns": _BASE_NS - 240_000_000_000,
        "retrieved_at_ns": _BASE_NS,
        "parser_version": "test",
        "registry_version": "test",
        "raw_sha256": _SHA,
        "source_channel": "test",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _BASE_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def _binary_option(
    symbol: str, *, lower_f: int | None, upper_f: int | None, ts_init: int = 0
) -> BinaryOption:
    price_increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=InstrumentId(symbol=Symbol(symbol), venue=Venue("POLYUS")),
        raw_symbol=Symbol(symbol),
        outcome="Yes",
        description="fixture",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=price_increment.precision,
        price_increment=price_increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=86_400_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=ts_init,
        ts_init=ts_init,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: _STATION,
            CLIMATE_DAY_KEY: _DAY_ISO,
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: lower_f,
            STRIKE_UPPER_F_KEY: upper_f,
        },
    )


# ---------------------------------------------------------------------------
# read_filled_trials_jsonl
# ---------------------------------------------------------------------------


def test_the_reader_parses_every_well_formed_row(tmp_path: Path) -> None:
    path = tmp_path / "fills.jsonl"
    path.write_text(json.dumps(_fill_row()) + "\n", encoding="utf-8")
    trials, refusals = read_filled_trials_jsonl(path)
    assert refusals == ()
    assert len(trials) == 1
    assert isinstance(trials[0], FilledTrial)
    assert trials[0].trial_id == "t1"


def test_a_malformed_row_is_refused_not_fatal_and_the_rest_still_parse(tmp_path: Path) -> None:
    path = tmp_path / "fills.jsonl"
    lines = [
        "{not valid json",
        json.dumps(_fill_row(trial_id="bad-decimal", fill_px="not-a-decimal")),
        json.dumps(_fill_row(trial_id="good")),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    trials, refusals = read_filled_trials_jsonl(path)
    assert len(trials) == 1
    assert trials[0].trial_id == "good"
    assert len(refusals) == 2
    assert all(r.reason == "malformed_input" for r in refusals)
    assert any("bad-decimal" == r.trial_id for r in refusals)


# ---------------------------------------------------------------------------
# _already_fallback_scored / _next_score_seq
# ---------------------------------------------------------------------------


def test_next_score_seq_is_zero_for_an_unscored_trial(tmp_path: Path) -> None:
    assert _next_score_seq(tmp_path, "unseen") == 0


def test_next_score_seq_increments_from_the_latest_stored_row(tmp_path: Path) -> None:
    row = ScoredTrial(
        trial_id="t1",
        station=_STATION,
        climate_day=_DAY_ISO,
        instrument_id="i",
        settlement_tmax_f=79,
        held=True,
        pnl=Decimal("0.5"),
        revision_seq=1,
        raw_sha256=_SHA,
        scored_at_ns=_BASE_NS,
        score_seq=3,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal("0.02"),
        entry_ask=Decimal("0.40"),
        fill_px=Decimal("0.42"),
        fee=Decimal("0.01"),
    )
    write_scored_trials(tmp_path, [row], now_ns=_BASE_NS)
    assert _next_score_seq(tmp_path, "t1") == 4


def test_a_fallback_scored_trial_is_not_re_scored_when_a_later_final_lands(tmp_path: Path) -> None:
    fallback_row = ScoredTrial(
        trial_id="t1",
        station=_STATION,
        climate_day=_DAY_ISO,
        instrument_id="i",
        settlement_tmax_f=79,
        held=True,
        pnl=Decimal("0.5"),
        revision_seq=0,
        raw_sha256="",
        scored_at_ns=_BASE_NS,
        score_seq=0,
        settlement_basis="venue_last_fair_price_fallback",
        excluded_reason="venue_settled_without_nws",
        slippage=Decimal("0.02"),
        entry_ask=Decimal("0.40"),
        fill_px=Decimal("0.42"),
        fee=Decimal("0.01"),
    )
    write_scored_trials(tmp_path, [fallback_row], now_ns=_BASE_NS)
    assert _already_fallback_scored(tmp_path, "t1") is True


# ---------------------------------------------------------------------------
# _unchanged_since_last_score (review item 3)
# ---------------------------------------------------------------------------


def test_unchanged_record_against_an_unscored_trial_is_never_skipped(tmp_path: Path) -> None:
    assert _unchanged_since_last_score(tmp_path, "t1", _climate_day()) is False


def test_an_unchanged_final_record_is_skipped_on_the_second_run(tmp_path: Path) -> None:
    row = ScoredTrial(
        trial_id="t1",
        station=_STATION,
        climate_day=_DAY_ISO,
        instrument_id="i",
        settlement_tmax_f=79,
        held=True,
        pnl=Decimal("0.5"),
        revision_seq=1,
        raw_sha256=_SHA,
        scored_at_ns=_BASE_NS,
        score_seq=0,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal("0.02"),
        entry_ask=Decimal("0.40"),
        fill_px=Decimal("0.42"),
        fee=Decimal("0.01"),
    )
    write_scored_trials(tmp_path, [row], now_ns=_BASE_NS)
    assert _unchanged_since_last_score(tmp_path, "t1", _climate_day(raw_sha256=_SHA)) is True


def test_a_corrected_record_is_not_treated_as_unchanged(tmp_path: Path) -> None:
    row = ScoredTrial(
        trial_id="t1",
        station=_STATION,
        climate_day=_DAY_ISO,
        instrument_id="i",
        settlement_tmax_f=79,
        held=True,
        pnl=Decimal("0.5"),
        revision_seq=1,
        raw_sha256=_SHA,
        scored_at_ns=_BASE_NS,
        score_seq=0,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal("0.02"),
        entry_ask=Decimal("0.40"),
        fill_px=Decimal("0.42"),
        fee=Decimal("0.01"),
    )
    write_scored_trials(tmp_path, [row], now_ns=_BASE_NS)
    corrected_sha = hashlib.sha256(b"corrected").hexdigest()
    assert (
        _unchanged_since_last_score(
            tmp_path, "t1", _climate_day(raw_sha256=corrected_sha, revision_seq=2)
        )
        is False
    )


# ---------------------------------------------------------------------------
# _read_bucket_facts_by_instrument_id (review item 4)
# ---------------------------------------------------------------------------


def test_duplicate_instrument_ids_with_divergent_facts_are_counted_and_warned(
    tmp_path: Path, caplog: Any
) -> None:
    catalog = open_station_catalog(tmp_path, _VENUE, _CITY)
    first = _binary_option("DUP", lower_f=78, upper_f=79)
    second = _binary_option("DUP", lower_f=80, upper_f=81, ts_init=1_000)
    catalog.write_data([first], skip_disjoint_check=True)
    catalog.write_data([second], skip_disjoint_check=True)

    with caplog.at_level(logging.WARNING, logger="score_live_trials"):
        facts = _read_bucket_facts_by_instrument_id(tmp_path, venue=_VENUE, city=_CITY)

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "1" in warnings[0]
    assert str(first.id) in facts
    assert facts[str(first.id)].lower_f == 78


# ---------------------------------------------------------------------------
# end-to-end: score_live_trials writes a parquet run the store reads back
# ---------------------------------------------------------------------------


def test_end_to_end_run_writes_a_parquet_file_the_store_reader_loads_back(
    tmp_path: Path,
) -> None:
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"

    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(catalog, [_climate_day(tmax_f=79)])

    fills_path.write_text(json.dumps(_fill_row()) + "\n", encoding="utf-8")

    scored, refused, excluded = score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )
    assert refused == ()
    assert excluded == ()
    assert len(scored) == 1
    assert scored[0].held is True

    files = sorted(derived_dir.glob("scored_trials_*.parquet"))
    assert len(files) == 1
    reloaded = read_scored_trials(derived_dir)
    assert len(reloaded) == 1
    assert reloaded[0].trial_id == "t1"
    assert reloaded[0].pnl == scored[0].pnl


# ---------------------------------------------------------------------------
# instrument_unavailable refusal path
# ---------------------------------------------------------------------------


def test_a_trial_with_no_bucket_and_no_persisted_instrument_is_refused_unavailable(
    tmp_path: Path,
) -> None:
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"

    open_station_catalog(catalog_base, _VENUE, _CITY)  # empty catalog

    fills_path.write_text(
        json.dumps(_fill_row(trial_id="no-instrument", bucket=None)) + "\n", encoding="utf-8"
    )

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
    assert refused[0].reason == "instrument_unavailable"
    assert refused[0].trial_id == "no-instrument"


def test_a_malformed_climate_day_on_a_parsed_trial_is_refused_not_fatal(tmp_path: Path) -> None:
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"

    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    instrument = _binary_option("BAD-DAY", lower_f=78, upper_f=79)
    catalog.write_data([instrument], skip_disjoint_check=True)
    write_records(catalog, [_climate_day(tmax_f=79)])

    lines = [
        json.dumps(
            _fill_row(
                trial_id="bad-day",
                climate_day="not-a-date",
                instrument_id=str(instrument.id),
                bucket=None,
            )
        ),
        json.dumps(_fill_row(trial_id="good-day")),
    ]
    fills_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    scored, refused, _excluded = score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )
    assert len(scored) == 1
    assert scored[0].trial_id == "good-day"
    assert any(r.trial_id == "bad-day" and r.reason == "malformed_input" for r in refused)


# ---------------------------------------------------------------------------
# partial-fill admission gate (ruling Q1,
# docs/evidence/grok_partial_fill_ruling_2026-09-04.md): qty != 1 is excluded
# fail-closed before score_trial; qty <= 0 is refused loudly as malformed.
# ---------------------------------------------------------------------------


def _admitted_trial(**overrides: Any) -> FilledTrial:
    return FilledTrial(
        trial_id=overrides.pop("trial_id", "t1"),
        station=overrides.pop("station", _STATION),
        climate_day=overrides.pop("climate_day", _DAY_ISO),
        instrument_id=overrides.pop("instrument_id", "i"),
        bucket=overrides.pop("bucket", None),
        fill_px=overrides.pop("fill_px", Decimal("0.42")),
        fee=overrides.pop("fee", Decimal("0.01")),
        qty=overrides.pop("qty", Decimal(1)),
        filled_at_ns=overrides.pop("filled_at_ns", _BASE_NS),
        entry_ask=overrides.pop("entry_ask", Decimal("0.40")),
        scheduled_release_at_ns=overrides.pop("scheduled_release_at_ns", _BASE_NS),
        venue_settlement_tmax_f=overrides.pop("venue_settlement_tmax_f", None),
    )


def test_a_qty_of_exactly_one_is_admitted_not_excluded() -> None:
    # Arrange
    trial = _admitted_trial(qty=Decimal(1))
    # Act
    exclusion = _admit_fill(trial)
    # Assert
    assert exclusion is None


def test_a_fractional_qty_is_excluded_as_partial_fill_with_full_coverage_fields() -> None:
    # Arrange
    trial = _admitted_trial(trial_id="frac", qty=Decimal("0.37"))
    # Act
    exclusion = _admit_fill(trial)
    # Assert
    assert isinstance(exclusion, FillExclusion)
    assert exclusion.reason == "partial_fill"
    assert exclusion.trial_id == "frac"
    assert exclusion.qty == "0.37"
    assert exclusion.station == _STATION
    assert exclusion.climate_day == _DAY_ISO


def test_a_qty_greater_than_one_is_excluded_as_multi_fill() -> None:
    # Arrange
    trial = _admitted_trial(trial_id="multi", qty=Decimal(10))
    # Act
    exclusion = _admit_fill(trial)
    # Assert
    assert isinstance(exclusion, FillExclusion)
    assert exclusion.reason == "multi_fill"
    assert exclusion.trial_id == "multi"
    assert exclusion.qty == "10"


def test_zero_qty_is_refused_as_malformed_not_excluded() -> None:
    # Arrange
    trial = _admitted_trial(trial_id="zero", qty=Decimal(0))
    # Act
    refusal = _validate_qty(trial)
    # Assert
    assert refusal is not None
    assert refusal.reason == "malformed_input"
    assert refusal.trial_id == "zero"
    assert "qty" in refusal.detail


def test_a_missing_qty_field_is_refused_as_malformed_input(tmp_path: Path) -> None:
    # Arrange -- the JSONL row omits "qty" entirely (existing reader
    # behaviour: a KeyError on parse becomes a malformed_input refusal, so
    # this pins that "missing" is already covered, never silently dropped).
    row = _fill_row(trial_id="no-qty")
    del row["qty"]
    path = tmp_path / "fills.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    # Act
    trials, refusals = read_filled_trials_jsonl(path)
    # Assert
    assert trials == ()
    assert len(refusals) == 1
    assert refusals[0].reason == "malformed_input"
    assert refusals[0].trial_id == "no-qty"


def test_the_reader_yields_qty_as_decimal_never_float_or_int(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "fills.jsonl"
    path.write_text(json.dumps(_fill_row(qty="1")) + "\n", encoding="utf-8")
    # Act
    trials, refusals = read_filled_trials_jsonl(path)
    # Assert
    assert refusals == ()
    assert type(trials[0].qty) is Decimal
    assert trials[0].qty == Decimal(1)


def test_end_to_end_a_partial_fill_is_excluded_not_scored_and_reported(tmp_path: Path) -> None:
    # Arrange
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(catalog, [_climate_day(tmax_f=79)])
    fills_path.write_text(
        json.dumps(_fill_row(trial_id="frac", qty="0.37")) + "\n", encoding="utf-8"
    )

    # Act
    scored, refused, excluded = score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )

    # Assert -- never scored, never a plain refusal, reported as an exclusion
    assert scored == ()
    assert refused == ()
    assert len(excluded) == 1
    assert excluded[0].trial_id == "frac"
    assert excluded[0].reason == "partial_fill"
    assert excluded[0].qty == "0.37"
    assert excluded[0].station == _STATION
    assert excluded[0].climate_day == _DAY_ISO
    # never persisted to the scored-trial store
    assert read_scored_trials(derived_dir) == ()


def test_end_to_end_a_multi_fill_is_excluded_not_scored_and_reported(tmp_path: Path) -> None:
    # Arrange
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(catalog, [_climate_day(tmax_f=79)])
    fills_path.write_text(
        json.dumps(_fill_row(trial_id="multi", qty="10")) + "\n", encoding="utf-8"
    )

    # Act
    scored, refused, excluded = score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )

    # Assert
    assert scored == ()
    assert refused == ()
    assert len(excluded) == 1
    assert excluded[0].reason == "multi_fill"
    assert excluded[0].trial_id == "multi"


def test_end_to_end_a_zero_qty_fill_is_refused_loudly_never_scored_never_silently_dropped(
    tmp_path: Path,
) -> None:
    # Arrange -- pins (f): the JSONL placeholder reader parses qty="0" into a
    # FilledTrial (it is valid Decimal syntax), so admission control -- not
    # the reader -- is the only gate that stops a zero-fill (IOC miss) from
    # reaching score_trial. Other FilledTrial construction sites
    # (runtime/paper_replay.py, current_rung_hold_paper_replay.py) are a
    # different fill source entirely and out of scope for this driver.
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(catalog, [_climate_day(tmax_f=79)])
    fills_path.write_text(
        json.dumps(_fill_row(trial_id="zero-fill", qty="0")) + "\n", encoding="utf-8"
    )

    # Act
    scored, refused, excluded = score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )

    # Assert -- never scored, never silently dropped (i.e. it is neither
    # absent from both tuples), refused loudly as malformed
    assert scored == ()
    assert excluded == ()
    assert len(refused) == 1
    assert refused[0].reason == "malformed_input"
    assert refused[0].trial_id == "zero-fill"


def test_main_prints_the_excluded_fills_table(tmp_path: Path, capsys: Any) -> None:
    # Arrange
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"
    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(catalog, [_climate_day(tmax_f=79)])
    fills_path.write_text(
        json.dumps(_fill_row(trial_id="frac", qty="0.37")) + "\n", encoding="utf-8"
    )

    # Act
    exit_code = main(
        [
            "--fills",
            str(fills_path),
            "--city",
            _CITY,
            "--venue",
            _VENUE,
            "--catalog-base",
            str(catalog_base),
            "--derived-dir",
            str(derived_dir),
        ]
    )

    # Assert
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "excluded 1 fill(s)" in out
    assert "excluded fills" in out
    assert "frac" in out
    assert "partial_fill" in out
    assert _STATION in out
    assert _DAY_ISO in out


# ---------------------------------------------------------------------------
# B1: v2-only live-provenance sidecar (ruling Q4: provenance == "live",
# never paper_replay, never a field on ScoredTrial/the 17-column schema).
# ---------------------------------------------------------------------------


def test_a_missing_provenance_sidecar_is_written_as_live(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    _write_or_assert_live_provenance_sidecar(store_dir)
    sidecar = store_dir / "provenance.json"
    assert json.loads(sidecar.read_text()) == {"provenance": "live"}


def test_an_existing_live_sidecar_is_left_unchanged_idempotent(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    _write_or_assert_live_provenance_sidecar(store_dir)
    _write_or_assert_live_provenance_sidecar(store_dir)  # second call: no raise
    sidecar = store_dir / "provenance.json"
    assert json.loads(sidecar.read_text()) == {"provenance": "live"}


def test_a_conflicting_paper_replay_sidecar_is_refused_loudly(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    (store_dir / "provenance.json").write_text(json.dumps({"provenance": "paper_replay"}))
    with pytest.raises(ProvenanceConflict):
        _write_or_assert_live_provenance_sidecar(store_dir)


def test_end_to_end_run_writes_the_live_provenance_sidecar_exactly_once(
    tmp_path: Path,
) -> None:
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"

    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(catalog, [_climate_day(tmax_f=79)])
    fills_path.write_text(json.dumps(_fill_row()) + "\n", encoding="utf-8")

    score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )
    sidecar = derived_dir / "provenance.json"
    assert sidecar.exists()
    assert json.loads(sidecar.read_text()) == {"provenance": "live"}


# ---------------------------------------------------------------------------
# B3: v2-only fill_order.jsonl sidecar (look ordering by fill time).
# ---------------------------------------------------------------------------


def test_append_fill_order_entries_writes_jsonl_rows(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    _append_fill_order_entries(
        store_dir,
        [{"trial_id": "t1", "score_seq": 0, "filled_at_ns": 100}],
    )
    path = store_dir / "fill_order.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"trial_id": "t1", "score_seq": 0, "filled_at_ns": 100}


def test_append_fill_order_entries_is_append_only(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    _append_fill_order_entries(store_dir, [{"trial_id": "t1", "score_seq": 0, "filled_at_ns": 100}])
    _append_fill_order_entries(store_dir, [{"trial_id": "t2", "score_seq": 0, "filled_at_ns": 200}])
    path = store_dir / "fill_order.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 2
    assert {row["trial_id"] for row in lines} == {"t1", "t2"}


def test_append_fill_order_entries_is_idempotent_for_a_re_scored_trial_id_score_seq(
    tmp_path: Path,
) -> None:
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    _append_fill_order_entries(store_dir, [{"trial_id": "t1", "score_seq": 0, "filled_at_ns": 100}])
    # Re-run with the SAME (trial_id, score_seq): must not duplicate.
    _append_fill_order_entries(store_dir, [{"trial_id": "t1", "score_seq": 0, "filled_at_ns": 100}])
    path = store_dir / "fill_order.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 1


def test_end_to_end_run_appends_a_fill_order_entry_for_the_admitted_fill(
    tmp_path: Path,
) -> None:
    catalog_base = tmp_path / "catalog"
    derived_dir = tmp_path / "derived"
    fills_path = tmp_path / "fills.jsonl"

    catalog = open_station_catalog(catalog_base, _VENUE, _CITY)
    write_records(catalog, [_climate_day(tmax_f=79)])
    fills_path.write_text(json.dumps(_fill_row(trial_id="t1")) + "\n", encoding="utf-8")

    score_live_trials(
        fills_path=fills_path,
        catalog_base=catalog_base,
        venue=_VENUE,
        city=_CITY,
        derived_dir=derived_dir,
        now_ns=_BASE_NS,
    )
    path = derived_dir / "fill_order.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["trial_id"] == "t1"
    assert rows[0]["score_seq"] == 0
    assert rows[0]["filled_at_ns"] == _BASE_NS
