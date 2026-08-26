"""Loader-side enforcement for quote-tape gap partitioning."""

from __future__ import annotations

from pathlib import Path

import pytest
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap
from breezy.persistence.quote_tape_gaps import (
    GapPartitionKey,
    UnpartitionedQuoteTapeGapReadError,
    load_partitioned_quote_tape_gaps,
)

INSTANCE = "11111111-1111-1111-1111-111111111111"
INSTRUMENT_A = InstrumentId.from_str("tc-temp-nyhigh-2026-08-25-lt80.POLYMARKET_US")
INSTRUMENT_B = InstrumentId.from_str("tc-temp-denhigh-2026-08-25-lt61f.POLYMARKET_US")


def gap(
    instrument_id: InstrumentId,
    *,
    seq: int,
    start: int,
    end: int,
    resolved: bool,
    instance: str = INSTANCE,
) -> QuoteTapeGap:
    return QuoteTapeGap(
        instrument_id=instrument_id,
        gap_seq=seq,
        started_ns=start,
        ended_ns=end,
        resolved=resolved,
        recorder_instance_id=instance,
        ts_event=start,
        ts_init=end or start,
    )


def raw_gap_rows(catalog: ParquetDataCatalog) -> list[QuoteTapeGap]:
    return [row.data for row in catalog.query(data_cls=QuoteTapeGap)]


def naive_flat_seq_collapse(rows: list[QuoteTapeGap]) -> list[QuoteTapeGap]:
    """The exact wrong shape: `gap_seq` alone is not a partition key."""
    by_seq: dict[int, QuoteTapeGap] = {}
    for row in rows:
        existing = by_seq.get(row.gap_seq)
        if existing is None or (row.resolved and not existing.resolved):
            by_seq[row.gap_seq] = row
    return [by_seq[key] for key in sorted(by_seq)]


def write_colliding_gaps(tmp_path: Path) -> ParquetDataCatalog:
    catalog = ParquetDataCatalog(tmp_path)
    catalog.write_data(
        [
            gap(INSTRUMENT_A, seq=1, start=100, end=0, resolved=False),
            gap(INSTRUMENT_B, seq=1, start=900, end=950, resolved=True),
        ]
    )
    return catalog


def test_loader_partitions_colliding_gap_seq_rows_from_the_catalog(tmp_path: Path) -> None:
    catalog = write_colliding_gaps(tmp_path)

    wrongly_collapsed = naive_flat_seq_collapse(raw_gap_rows(catalog))
    assert len(wrongly_collapsed) == 1
    assert wrongly_collapsed[0].instrument_id == INSTRUMENT_B
    assert wrongly_collapsed[0].covers(10_000) is False

    partitions = load_partitioned_quote_tape_gaps(catalog)

    assert set(partitions.keys()) == {
        GapPartitionKey(INSTANCE, INSTRUMENT_A),
        GapPartitionKey(INSTANCE, INSTRUMENT_B),
    }
    instrument_a_gap = partitions[GapPartitionKey(INSTANCE, INSTRUMENT_A)][0]
    instrument_b_gap = partitions[GapPartitionKey(INSTANCE, INSTRUMENT_B)][0]
    assert instrument_a_gap.resolved is False
    assert instrument_a_gap.covers(10_000) is True
    assert instrument_b_gap.resolved is True
    assert instrument_b_gap.started_ns == 900
    assert instrument_b_gap.ended_ns == 950


def test_sanctioned_loader_refuses_to_return_flat_gap_rows(tmp_path: Path) -> None:
    partitions = load_partitioned_quote_tape_gaps(write_colliding_gaps(tmp_path))

    with pytest.raises(UnpartitionedQuoteTapeGapReadError, match="partitioned"):
        partitions.flat()


def test_sanctioned_loader_refuses_accidental_iteration(tmp_path: Path) -> None:
    partitions = load_partitioned_quote_tape_gaps(write_colliding_gaps(tmp_path))

    with pytest.raises(UnpartitionedQuoteTapeGapReadError, match="partitioned"):
        list(partitions)
