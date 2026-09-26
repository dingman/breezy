"""`PositionReportingLag` -- domain record type (R-7-IMPL).

Moved from ``breezy.runtime`` to ``breezy.domain`` (R-7-IMPL, ``git mv``) so
``breezy.adapters.polymarket_us.exec.client`` -- BELOW ``breezy.runtime`` in
the import-linter layer contract -- can import it. See the module docstring
for the full layering rationale.
"""

from __future__ import annotations

import dataclasses

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.domain.position_reporting_lag import (
    FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
    PositionReportingLag,
)

INSTRUMENT_ID = InstrumentId.from_str("lax-86-87.POLYMARKET_US")


def test_a_consistent_record_constructs_and_exposes_its_five_fields() -> None:
    record = PositionReportingLag(
        instrument_id=INSTRUMENT_ID,
        fill_ts_event=1_000,
        first_eof_read_ts_showing_long=1_500,
        delta_ns=500,
        fill_ts_event_source=FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
    )
    assert record.instrument_id == INSTRUMENT_ID
    assert record.fill_ts_event == 1_000
    assert record.first_eof_read_ts_showing_long == 1_500
    assert record.delta_ns == 500
    assert record.fill_ts_event_source == "venue_transactTime"


def test_delta_ns_must_equal_the_read_minus_the_fill() -> None:
    with pytest.raises(ValueError, match="delta_ns"):
        PositionReportingLag(
            instrument_id=INSTRUMENT_ID,
            fill_ts_event=1_000,
            first_eof_read_ts_showing_long=1_500,
            delta_ns=999,
            fill_ts_event_source=FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
        )


def test_the_confirming_read_cannot_precede_the_fill() -> None:
    with pytest.raises(ValueError, match="precedes"):
        PositionReportingLag(
            instrument_id=INSTRUMENT_ID,
            fill_ts_event=1_500,
            first_eof_read_ts_showing_long=1_000,
            delta_ns=-500,
            fill_ts_event_source=FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
        )


def test_a_zero_lag_read_is_valid() -> None:
    record = PositionReportingLag(
        instrument_id=INSTRUMENT_ID,
        fill_ts_event=1_000,
        first_eof_read_ts_showing_long=1_000,
        delta_ns=0,
        fill_ts_event_source=FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
    )
    assert record.delta_ns == 0


def test_the_record_is_frozen() -> None:
    record = PositionReportingLag(
        instrument_id=INSTRUMENT_ID,
        fill_ts_event=1_000,
        first_eof_read_ts_showing_long=1_500,
        delta_ns=500,
        fill_ts_event_source=FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.delta_ns = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# T1 (R-7-IMPL plan r1 section 5): the source field is required, and the old
# import path (``breezy.runtime.position_reporting_lag``) is gone.
# ---------------------------------------------------------------------------


def test_the_record_requires_the_fill_ts_event_source_field() -> None:
    with pytest.raises(TypeError, match="fill_ts_event_source"):
        PositionReportingLag(  # type: ignore[call-arg]
            instrument_id=INSTRUMENT_ID,
            fill_ts_event=1_000,
            first_eof_read_ts_showing_long=1_500,
            delta_ns=500,
        )


def test_a_source_other_than_venue_transact_time_is_refused() -> None:
    with pytest.raises(ValueError, match="fill_ts_event_source"):
        PositionReportingLag(
            instrument_id=INSTRUMENT_ID,
            fill_ts_event=1_000,
            first_eof_read_ts_showing_long=1_500,
            delta_ns=500,
            fill_ts_event_source="local_clock",
        )


def test_the_old_runtime_import_path_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        import breezy.runtime.position_reporting_lag  # noqa: F401
