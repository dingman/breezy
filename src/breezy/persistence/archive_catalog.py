"""Parquet catalog readers for structurally separate archived backfill records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nautilus_trader.model.data import CustomData
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.archived_climate_day import ArchivedClimateDay
from breezy.persistence.catalog import CatalogPathError, station_catalog_path

__all__ = [
    "archive_catalog_path",
    "assert_archive_base_disjoint",
    "read_archived_climate_days",
]


def assert_archive_base_disjoint(*, archive_base: Path, settlement_base: Path) -> None:
    """Fail unless archive and settlement catalog bases are resolved-disjoint.

    This must run at archive-job startup before any mkdir. `station_catalog_path`
    deliberately does not validate `base` itself, so this assertion is the ONLY
    check on those base values, not defence in depth.
    """
    resolved_archive = Path(archive_base).resolve()
    resolved_settlement = Path(settlement_base).resolve()

    if (
        resolved_archive == resolved_settlement
        or resolved_archive.is_relative_to(resolved_settlement)
        or resolved_settlement.is_relative_to(resolved_archive)
    ):
        raise CatalogPathError(
            f"archive base {resolved_archive} and settlement base {resolved_settlement} "
            f"must be disjoint; neither may equal, contain, or live inside the other",
        )


def archive_catalog_path(base: Path, venue: str, city: str) -> Path:
    """Return the archived catalog root for one `(venue, city)` site.

    This reuses the settlement path validator unchanged: allowlisted components,
    containment re-check and symlink refusal all stay in one implementation. Only
    the caller-supplied base differs, and the archive-vs-settlement base
    assertion is intentionally separate because that check needs both roots.
    """
    return station_catalog_path(base, venue, city)


def read_archived_climate_days(
    catalog: ParquetDataCatalog,
    *,
    station: str,
    start: int | None = None,
    end: int | None = None,
) -> list[ArchivedClimateDay]:
    """Return unwrapped archived climate-day rows for `station` within optional bounds."""
    return [
        record
        for record in _read_archive_records(catalog, ArchivedClimateDay, start=start, end=end)
        if record.station == station
    ]


def _read_archive_records[RecordT: ArchivedClimateDay](
    catalog: ParquetDataCatalog,
    data_cls: type[RecordT],
    *,
    start: int | None,
    end: int | None,
) -> list[RecordT]:
    results: list[Any] = catalog.custom_data(cls=data_cls, start=start, end=end)
    records: list[RecordT] = []

    for result in results:
        record = result.data if isinstance(result, CustomData) else result

        if not isinstance(record, data_cls):
            raise TypeError(
                f"catalog at {catalog.path} returned {type(record).__name__} when "
                f"queried for {data_cls.__name__}",
            )

        records.append(record)

    return records
