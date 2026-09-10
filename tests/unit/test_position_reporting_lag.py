"""`PositionReportingLag` -- Phase 0b artefact (record type only).

Authority: `v3plan_rev6.md` Resolution F, "Lag measurement (new Phase 0b
artefact)": Phase 0b ships ONLY this record type; the emission plumbing lives
on the ambiguous-intent resolver, which is Phase 1 work pending the live
positions read (`read_startup_position_evidence`, same plan's "Never-arm
gate" section) -- neither exists in `src/` yet. This module has zero
producers by design; wiring it into the resolver is out of scope here.
"""

from __future__ import annotations

import dataclasses

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.runtime.position_reporting_lag import PositionReportingLag

INSTRUMENT_ID = InstrumentId.from_str("lax-86-87.POLYMARKET_US")


def test_a_consistent_record_constructs_and_exposes_its_four_fields() -> None:
    record = PositionReportingLag(
        instrument_id=INSTRUMENT_ID,
        fill_ts_event=1_000,
        first_eof_read_ts_showing_long=1_500,
        delta_ns=500,
    )
    assert record.instrument_id == INSTRUMENT_ID
    assert record.fill_ts_event == 1_000
    assert record.first_eof_read_ts_showing_long == 1_500
    assert record.delta_ns == 500


def test_delta_ns_must_equal_the_read_minus_the_fill() -> None:
    with pytest.raises(ValueError, match="delta_ns"):
        PositionReportingLag(
            instrument_id=INSTRUMENT_ID,
            fill_ts_event=1_000,
            first_eof_read_ts_showing_long=1_500,
            delta_ns=999,
        )


def test_the_confirming_read_cannot_precede_the_fill() -> None:
    with pytest.raises(ValueError, match="precedes"):
        PositionReportingLag(
            instrument_id=INSTRUMENT_ID,
            fill_ts_event=1_500,
            first_eof_read_ts_showing_long=1_000,
            delta_ns=-500,
        )


def test_a_zero_lag_read_is_valid() -> None:
    record = PositionReportingLag(
        instrument_id=INSTRUMENT_ID,
        fill_ts_event=1_000,
        first_eof_read_ts_showing_long=1_000,
        delta_ns=0,
    )
    assert record.delta_ns == 0


def test_the_record_is_frozen() -> None:
    record = PositionReportingLag(
        instrument_id=INSTRUMENT_ID,
        fill_ts_event=1_000,
        first_eof_read_ts_showing_long=1_500,
        delta_ns=500,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.delta_ns = 0  # type: ignore[misc]
