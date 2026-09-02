"""Unit tests for `scripts/analysis/cli_basis_offer_gate_settlement.py`.

Item 1: did a qualifying offer-gate event actually WIN, and what would the
realized paper P&L have been? Everything here is exercised PURE, against
hand-built `NwsClimateDay` / `StationDayResult` / `AskLevel` fixtures -- no
network, no live catalog, no live tape. `resolve_settlement_record` (the one
function that touches a real `ParquetDataCatalog` directory) is exercised
against an isolated `tmp_path` catalog root instead.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from cli_basis_offer_gate_scan import AskLevel, StationDayResult
from cli_basis_offer_gate_settlement import (
    VENUE,
    aggregate_realized_pnl,
    is_settlement_grade,
    realized_pnl_for_event,
    resolve_settlement_record,
    settlement_outcome,
)

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.persistence.catalog import open_station_catalog, write_records

_BASE_NS = int(dt.datetime(2026, 9, 1, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"cli-basis-offer-gate-settlement-test").hexdigest()


def _climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "LAX",
        "climate_day": dt.date(2026, 8, 31),
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


def _station_day_result(**overrides: Any) -> StationDayResult:
    kwargs: dict[str, Any] = {
        "station": "LAX",
        "climate_day": dt.date(2026, 8, 31),
        "dense": True,
        "admissible": True,
        "event": True,
        "n_qualifying_instants": 1630,
        "best_ask": Decimal("0.01"),
        "best_ask_size": Decimal(160),
        "max_notional": Decimal("185.57"),
        "blocked_reason": None,
        "strike_f": 80,
        "peak_instrument_id": "tc-temp-laxhigh-2026-08-31-gte80f.POLYMARKET_US",
        "peak_levels": (AskLevel(price=Decimal("0.01"), size=Decimal(160)),),
        "fee_coefficient": Decimal("0.06"),
        "quote_currency_precision": 2,
    }
    kwargs.update(overrides)
    return StationDayResult(**kwargs)


# ---------------------------------------------------------------------------
# is_settlement_grade
# ---------------------------------------------------------------------------


def test_is_settlement_grade_true_for_a_real_final() -> None:
    assert is_settlement_grade(_climate_day()) is True


def test_is_settlement_grade_false_for_none() -> None:
    assert is_settlement_grade(None) is False


def test_is_settlement_grade_false_for_a_preliminary() -> None:
    assert is_settlement_grade(_climate_day(is_final=False)) is False


def test_is_settlement_grade_false_for_a_superseded_final() -> None:
    assert is_settlement_grade(_climate_day(is_superseded=True)) is False


def test_is_settlement_grade_false_for_a_final_with_sentinel_tmax() -> None:
    assert is_settlement_grade(_climate_day(tmax_f=None, tmax_flag="M")) is False


# ---------------------------------------------------------------------------
# settlement_outcome -- the decisive join, YES / NO / PENDING
# ---------------------------------------------------------------------------


def test_settlement_outcome_no_when_final_tmax_is_below_the_open_tail_strike() -> None:
    """THE decisive real-world case: LAX 2026-08-31 final tmax_f=79, the
    qualifying event's open-tail strike was `>= 80`. 79 < 80: the offer LOST.
    """
    record = _climate_day(station="LAX", climate_day=dt.date(2026, 8, 31), tmax_f=79)
    assert settlement_outcome(record=record, strike_f=80) == "NO"


def test_settlement_outcome_yes_when_final_tmax_meets_the_strike() -> None:
    record = _climate_day(tmax_f=80)
    assert settlement_outcome(record=record, strike_f=80) == "YES"


def test_settlement_outcome_yes_when_final_tmax_exceeds_the_strike() -> None:
    record = _climate_day(tmax_f=85)
    assert settlement_outcome(record=record, strike_f=80) == "YES"


def test_settlement_outcome_pending_when_no_record_exists() -> None:
    assert settlement_outcome(record=None, strike_f=80) == "PENDING"


def test_settlement_outcome_pending_when_not_yet_final() -> None:
    record = _climate_day(is_final=False, tmax_f=85)
    assert settlement_outcome(record=record, strike_f=80) == "PENDING"


def test_settlement_outcome_pending_never_reads_as_a_loss_or_a_win() -> None:
    """A PENDING record must never be conflated with NO just because a
    numeric tmax happens to be present on a non-final record.
    """
    record = _climate_day(is_final=False, tmax_f=50, tmin_f=40)  # would be NO if trusted
    outcome = settlement_outcome(record=record, strike_f=80)
    assert outcome == "PENDING"


# ---------------------------------------------------------------------------
# realized_pnl_for_event -- fee applied PER LEVEL
# ---------------------------------------------------------------------------


def test_realized_pnl_for_a_losing_event_is_negative_the_full_premium_plus_fee() -> None:
    result = _station_day_result()
    record = _climate_day(tmax_f=79)  # < strike 80 -> NO
    outcome = realized_pnl_for_event(result=result, record=record)
    assert outcome.outcome == "NO"
    assert outcome.contracts == Decimal(160)
    assert outcome.notional_paid == Decimal("0.01") * Decimal(160)
    # fee = theta * C * p * (1-p) = 0.06 * 160 * 0.01 * 0.99 = 0.09504,
    # banker's-rounded to the nearest cent -> 0.10
    assert outcome.fee_paid == Decimal("0.10")
    assert outcome.realized_pnl == Decimal(0) - outcome.notional_paid - outcome.fee_paid


def test_realized_pnl_for_a_winning_event_pays_one_dollar_per_contract() -> None:
    result = _station_day_result()
    record = _climate_day(tmax_f=82)  # >= strike 80 -> YES
    outcome = realized_pnl_for_event(result=result, record=record)
    assert outcome.outcome == "YES"
    assert outcome.fee_paid is not None
    assert outcome.realized_pnl == outcome.contracts - outcome.notional_paid - outcome.fee_paid


def test_realized_pnl_is_none_when_settlement_is_pending() -> None:
    result = _station_day_result()
    outcome = realized_pnl_for_event(result=result, record=None)
    assert outcome.outcome == "PENDING"
    assert outcome.realized_pnl is None
    assert outcome.settlement_tmax_f is None


def test_realized_pnl_is_none_when_fee_coefficient_is_unknown() -> None:
    """An unknown fee must never silently become a zero fee."""
    result = _station_day_result(fee_coefficient=None)
    record = _climate_day(tmax_f=79)
    outcome = realized_pnl_for_event(result=result, record=record)
    assert outcome.fee_paid is None
    assert outcome.realized_pnl is None


def test_realized_pnl_sums_fee_per_level_not_off_the_aggregate_notional() -> None:
    """theta*C*p*(1-p) is concave in p -- summing per-level fees must differ
    from (incorrectly) pricing one blended average price across all size.
    """
    levels = (
        AskLevel(price=Decimal("0.01"), size=Decimal(100)),
        AskLevel(price=Decimal("0.05"), size=Decimal(100)),
    )
    result = _station_day_result(peak_levels=levels, max_notional=Decimal("6.00"))
    outcome = realized_pnl_for_event(result=result, record=_climate_day(tmax_f=79))
    per_level_fee = Decimal("0.06") * Decimal(100) * Decimal("0.01") * Decimal(
        "0.99"
    ) + Decimal("0.06") * Decimal(100) * Decimal("0.05") * Decimal("0.95")
    assert outcome.fee_paid == per_level_fee.quantize(Decimal("0.01"))


def test_realized_pnl_for_event_raises_for_a_result_with_no_strike() -> None:
    result = _station_day_result(event=False, strike_f=None, peak_levels=())
    with pytest.raises(ValueError, match="no strike recorded"):
        realized_pnl_for_event(result=result, record=None)


# ---------------------------------------------------------------------------
# aggregate_realized_pnl
# ---------------------------------------------------------------------------


def test_aggregate_realized_pnl_sums_only_resolved_outcomes() -> None:
    result = _station_day_result()
    losing = realized_pnl_for_event(result=result, record=_climate_day(tmax_f=79))
    pending = realized_pnl_for_event(result=result, record=None)
    total = aggregate_realized_pnl((losing, pending))
    assert total == losing.realized_pnl


def test_aggregate_realized_pnl_is_none_when_nothing_is_resolved() -> None:
    result = _station_day_result()
    pending = realized_pnl_for_event(result=result, record=None)
    assert aggregate_realized_pnl((pending,)) is None


def test_aggregate_realized_pnl_is_none_for_an_empty_sequence() -> None:
    assert aggregate_realized_pnl(()) is None


# ---------------------------------------------------------------------------
# resolve_settlement_record -- real (isolated) catalog I/O, zero network
# ---------------------------------------------------------------------------


def test_resolve_settlement_record_returns_none_for_an_empty_catalog(tmp_path: Path) -> None:
    assert (
        resolve_settlement_record(
            catalog_base=tmp_path,
            venue=VENUE,
            station="LAX",
            climate_day=dt.date(2026, 8, 31),
        )
        is None
    )


def test_resolve_settlement_record_returns_the_written_final(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, VENUE, "LAX")
    record = _climate_day(station="LAX", climate_day=dt.date(2026, 8, 31), tmax_f=79)
    write_records(catalog, [record])

    resolved = resolve_settlement_record(
        catalog_base=tmp_path, venue=VENUE, station="LAX", climate_day=dt.date(2026, 8, 31)
    )
    assert resolved is not None
    assert resolved.tmax_f == 79
    assert resolved.is_final is True
