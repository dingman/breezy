"""Sanctioned loader for venue quote-tape gap records.

The storage and read mechanism remain Nautilus-native:
``ParquetDataCatalog.query(data_cls=QuoteTapeGap)`` is the source of truth.
This module only enforces Breezy's consumer-side join contract after the rows
come back from the catalog.
"""

from __future__ import annotations

from collections.abc import ItemsView, KeysView, ValuesView
from dataclasses import dataclass
from typing import NoReturn

from nautilus_trader.model.data import CustomData
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap, resolved_gaps_by_seq

__all__ = [
    "GapPartitionKey",
    "PartitionedQuoteTapeGaps",
    "UnpartitionedQuoteTapeGapReadError",
    "load_partitioned_quote_tape_gaps",
]


@dataclass(frozen=True, slots=True)
class GapPartitionKey:
    """The only safe partition for applying quote-tape gaps to observations."""

    recorder_instance_id: str
    instrument_id: InstrumentId


class UnpartitionedQuoteTapeGapReadError(RuntimeError):
    """Raised when a consumer asks the sanctioned loader for flat gap rows."""


class PartitionedQuoteTapeGaps:
    """Immutable partitioned view over resolved quote-tape gaps."""

    def __init__(self, partitions: dict[GapPartitionKey, tuple[QuoteTapeGap, ...]]) -> None:
        self._partitions = dict(partitions)

    def __getitem__(self, key: GapPartitionKey) -> tuple[QuoteTapeGap, ...]:
        return self._partitions[key]

    def __contains__(self, key: object) -> bool:
        return key in self._partitions

    def __len__(self) -> int:
        return len(self._partitions)

    def __iter__(self) -> NoReturn:
        raise UnpartitionedQuoteTapeGapReadError(
            "quote-tape gaps must be consumed partitioned by "
            "(recorder_instance_id, instrument_id); use .items(), .keys(), "
            ".values(), .get(), or __getitem__ with GapPartitionKey"
        )

    def get(
        self,
        key: GapPartitionKey,
        default: tuple[QuoteTapeGap, ...] | None = None,
    ) -> tuple[QuoteTapeGap, ...] | None:
        return self._partitions.get(key, default)

    def keys(self) -> KeysView[GapPartitionKey]:
        return self._partitions.keys()

    def items(self) -> ItemsView[GapPartitionKey, tuple[QuoteTapeGap, ...]]:
        return self._partitions.items()

    def values(self) -> ValuesView[tuple[QuoteTapeGap, ...]]:
        return self._partitions.values()

    def flat(self) -> NoReturn:
        raise UnpartitionedQuoteTapeGapReadError(
            "quote-tape gaps are only exposed as partitioned rows keyed by "
            "(recorder_instance_id, instrument_id)"
        )


def load_partitioned_quote_tape_gaps(
    catalog: ParquetDataCatalog,
) -> PartitionedQuoteTapeGaps:
    """Read gap rows through Nautilus and return only safe partitions."""
    collapsed = resolved_gaps_by_seq(_query_gap_rows(catalog))
    partitions: dict[GapPartitionKey, list[QuoteTapeGap]] = {}
    for gap in collapsed:
        key = GapPartitionKey(gap.recorder_instance_id, gap.instrument_id)
        partitions.setdefault(key, []).append(gap)

    frozen = {
        key: tuple(sorted(gaps, key=lambda gap: gap.gap_seq))
        for key, gaps in sorted(
            partitions.items(),
            key=lambda item: (
                item[0].recorder_instance_id,
                item[0].instrument_id.value,
            ),
        )
    }
    return PartitionedQuoteTapeGaps(frozen)


def _query_gap_rows(catalog: ParquetDataCatalog) -> list[QuoteTapeGap]:
    rows: list[QuoteTapeGap] = []
    for item in catalog.query(data_cls=QuoteTapeGap):
        if isinstance(item, QuoteTapeGap):
            rows.append(item)
        elif isinstance(item, CustomData) and isinstance(item.data, QuoteTapeGap):
            rows.append(item.data)
        else:  # pragma: no cover - defensive against Nautilus API drift
            raise TypeError(
                "expected QuoteTapeGap rows from Nautilus catalog query, "
                f"got {type(item).__name__}"
            )
    return rows
