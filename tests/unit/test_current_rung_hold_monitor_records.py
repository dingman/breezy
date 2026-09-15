"""RED-first tests for `PositionMarkRecord` and `PositionMonitorSummary` (INC-4).

Catalog round-trip and schema-drift coverage per
`docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md` Sec 6 INC-4. This module
never imports `monitor_evidence.py`/`monitor_decision.py` (built concurrently
by another agent) -- `thesis_state`/`verdict` are plain strings here.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.strict_arrow import SchemaDriftError, make_strict_decoder
from breezy.persistence.catalog import write_records
from breezy.strategy.current_rung_hold.monitor_records import (
    PositionMarkRecord,
    PositionMonitorSummary,
)

_INSTRUMENT_ID = InstrumentId.from_str("sfo-86-87.POLYMARKET_US")


def _mark_record(**overrides: object) -> PositionMarkRecord:
    base: dict[str, object] = {
        "instrument_id": _INSTRUMENT_ID,
        "station": "SFO",
        "climate_day": "2026-09-01",
        "leg": "YES",
        "entry_context": "live",
        "thesis_state": "ALIVE",
        "verdict": "HOLD",
        "mark_vwap": Decimal("0.62"),
        "mark_source": "depth_walk",
        "unrealized_pnl": Decimal("1.50"),
        "recoverable_value": Decimal("0.60"),
        "running_max_lower": Decimal(80),
        "running_max_upper": Decimal(84),
        "staleness_ns": 5_000_000_000,
        "book_staleness_ns": 2_000_000_000,
        "held_qty": Decimal(1),
        "reason_codes": ("dead_candidate",),
        "ts_event": 1_700_000_000_000_000_000,
        "ts_init": 1_700_000_000_500_000_000,
    }
    base.update(overrides)
    return PositionMarkRecord(**base)  # type: ignore[arg-type]


def _summary(**overrides: object) -> PositionMonitorSummary:
    base: dict[str, object] = {
        "trial_id": "continuous_rung_hold/trial/SFO/2026-09-01/sfo-86-87.POLYMARKET_US",
        "instrument_id": "sfo-86-87.POLYMARKET_US",
        "station": "SFO",
        "climate_day": "2026-09-01",
        "leg": "YES",
        "entry_context": "live",
        "monitor_seq": 1,
        "fill_px": Decimal("0.55"),
        "held_qty": Decimal(1),
        "mae": Decimal("0.10"),
        "mfe": Decimal("0.25"),
        "first_signal_ts_ns": 1_700_000_000_000_000_000,
        "first_signal_hour_lst": 14,
        "first_signal_state": "THREATENED",
        "verdict_at_signal": "REDUCE_RECOMMENDED",
        "recoverable_value_at_signal": Decimal("0.40"),
        "held_duration_ns": 3_600_000_000_000,
        "total_frames": 42,
        "mark_missing_frames": 3,
        "settled_pnl": None,
        "settled_held": None,
    }
    base.update(overrides)
    return PositionMonitorSummary(**base)  # type: ignore[arg-type]


class TestPositionMarkRecordConstruction:
    def test_a_record_carries_its_leg_aware_mark_and_thesis_state(self) -> None:
        record = _mark_record()

        assert record.instrument_id == _INSTRUMENT_ID
        assert record.thesis_state == "ALIVE"
        assert record.verdict == "HOLD"
        assert record.mark_vwap == Decimal("0.62")

    def test_a_reason_code_containing_a_comma_is_refused_at_construction(self) -> None:
        """A comma inside one code would corrupt the comma-joined round-trip."""
        with pytest.raises(ValueError, match="comma"):
            _mark_record(reason_codes=("bad,code",))

    def test_a_non_instrument_id_is_refused_at_construction(self) -> None:
        with pytest.raises(TypeError):
            _mark_record(instrument_id="sfo-86-87.POLYMARKET_US")


class TestPositionMarkRecordRoundTrip:
    def test_an_empty_reason_codes_tuple_round_trips_without_a_blank_entry(self) -> None:
        record = _mark_record(reason_codes=())

        assert record.to_dict()["reason_codes"] == ""
        rebuilt = PositionMarkRecord.from_dict(record.to_dict())
        assert rebuilt.reason_codes == ()

    def test_multiple_reason_codes_round_trip_comma_joined(self) -> None:
        record = _mark_record(reason_codes=("dead_candidate", "p_hold_undefined"))
        rebuilt = PositionMarkRecord.from_dict(record.to_dict())

        assert rebuilt.reason_codes == ("dead_candidate", "p_hold_undefined")

    def test_decimal_fields_round_trip_without_precision_loss(self) -> None:
        record = _mark_record(
            mark_vwap=Decimal("0.1234567890123456789"),
            held_qty=Decimal(3),
        )
        rebuilt = PositionMarkRecord.from_dict(record.to_dict())

        assert rebuilt.mark_vwap == Decimal("0.1234567890123456789")
        assert isinstance(rebuilt.mark_vwap, Decimal)
        assert rebuilt.held_qty == Decimal(3)
        assert isinstance(rebuilt.held_qty, Decimal)

    def test_nullable_decimal_fields_round_trip_as_none(self) -> None:
        record = _mark_record(
            mark_vwap=None,
            unrealized_pnl=None,
            recoverable_value=None,
            running_max_lower=None,
            running_max_upper=None,
        )
        rebuilt = PositionMarkRecord.from_dict(record.to_dict())

        assert rebuilt.mark_vwap is None
        assert rebuilt.unrealized_pnl is None
        assert rebuilt.recoverable_value is None
        assert rebuilt.running_max_lower is None
        assert rebuilt.running_max_upper is None

    def test_from_dict_raises_on_a_missing_column_rather_than_defaulting(self) -> None:
        record = _mark_record()
        incomplete = record.to_dict()
        del incomplete["staleness_ns"]

        with pytest.raises(KeyError):
            PositionMarkRecord.from_dict(incomplete)


class TestPositionMarkRecordCatalogRoundTrip:
    def test_a_mark_record_round_trips_through_write_records_and_the_catalog(
        self, tmp_path: Path
    ) -> None:
        catalog = ParquetDataCatalog(path=str(tmp_path))
        record = _mark_record()

        write_records(catalog, [record])

        rows = [item.data for item in catalog.query(data_cls=PositionMarkRecord)]

        assert len(rows) == 1
        assert rows[0].to_dict() == record.to_dict()

    def test_a_wrong_typed_column_raises_a_schema_drift_error_on_read(self) -> None:
        """Simulates a foreign/older fragment whose `staleness_ns` column is a
        string rather than the registered `int64` -- the strict decoder must
        raise rather than let pyarrow coerce it silently (trap 18)."""
        good_row = _mark_record().to_dict()
        good_row["staleness_ns"] = "5000000000"
        drifted_schema = pa.schema(
            [
                field
                if field.name != "staleness_ns"
                else pa.field("staleness_ns", pa.string(), nullable=False)
                for field in PositionMarkRecord.schema()
            ]
        )
        table = pa.Table.from_pylist([good_row], schema=drifted_schema)

        decoder = make_strict_decoder(PositionMarkRecord, PositionMarkRecord.schema())
        with pytest.raises(SchemaDriftError):
            decoder(table)

    def test_a_missing_column_raises_a_schema_drift_error_on_read(self) -> None:
        good_row = _mark_record().to_dict()
        del good_row["reason_codes"]
        drifted_schema = pa.schema(
            [field for field in PositionMarkRecord.schema() if field.name != "reason_codes"]
        )
        table = pa.Table.from_pylist([good_row], schema=drifted_schema)

        decoder = make_strict_decoder(PositionMarkRecord, PositionMarkRecord.schema())
        with pytest.raises(SchemaDriftError):
            decoder(table)


class TestPositionMonitorSummary:
    def test_a_summary_round_trips_its_decimal_and_optional_fields(self) -> None:
        summary = _summary()
        rebuilt = PositionMonitorSummary.from_dict(summary.to_dict())

        assert rebuilt == summary

    def test_a_summary_with_no_signal_yet_round_trips_all_nones(self) -> None:
        summary = _summary(
            first_signal_ts_ns=None,
            first_signal_hour_lst=None,
            first_signal_state=None,
            verdict_at_signal=None,
            recoverable_value_at_signal=None,
        )
        rebuilt = PositionMonitorSummary.from_dict(summary.to_dict())

        assert rebuilt == summary

    def test_settled_fields_round_trip_once_the_nightly_join_populates_them(self) -> None:
        summary = _summary(settled_pnl=Decimal("-0.45"), settled_held=False)
        rebuilt = PositionMonitorSummary.from_dict(summary.to_dict())

        assert rebuilt.settled_pnl == Decimal("-0.45")
        assert rebuilt.settled_held is False

    def test_monitor_intervened_true_is_refused_at_construction(self) -> None:
        """CUT: no `on_position_closed` logic exists that could ever produce
        `True` -- a `True` value is a defect, not data (plan Sec 2/4)."""
        with pytest.raises(ValueError, match="monitor_intervened"):
            _summary(monitor_intervened=True)

    def test_monitor_intervened_defaults_to_false(self) -> None:
        summary = _summary()

        assert summary.monitor_intervened is False
