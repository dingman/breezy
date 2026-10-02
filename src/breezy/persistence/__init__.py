"""Parquet catalog persistence for domain records, plus filesystem safety.

Re-exports :mod:`breezy.persistence.catalog`'s already-curated public
surface (that module owns its own ``__all__``). This package is not a
single submodule: the other modules are imported directly, not through
this facade.
"""

from breezy.persistence.catalog import (
    NETWORK_FILESYSTEM_TYPES,
    WRITER_LOCK_FILENAME,
    CatalogPathError,
    CatalogWriteError,
    ConcurrentWriterError,
    FilesystemLocality,
    FilesystemProbe,
    NonMonotonicWriteError,
    WriteOutcome,
    WriterLockError,
    WriterLockFilesystemError,
    assert_writer_lock_filesystem_supported,
    open_station_catalog,
    probe_filesystem,
    read_climate_day_as_of_settlement,
    read_climate_day_including_corrections,
    read_climate_days,
    read_raw_products,
    station_catalog_path,
    write_records,
)

__all__ = [
    "NETWORK_FILESYSTEM_TYPES",
    "WRITER_LOCK_FILENAME",
    "CatalogPathError",
    "CatalogWriteError",
    "ConcurrentWriterError",
    "FilesystemLocality",
    "FilesystemProbe",
    "NonMonotonicWriteError",
    "WriteOutcome",
    "WriterLockError",
    "WriterLockFilesystemError",
    "assert_writer_lock_filesystem_supported",
    "open_station_catalog",
    "probe_filesystem",
    "read_climate_day_as_of_settlement",
    "read_climate_day_including_corrections",
    "read_climate_days",
    "read_raw_products",
    "station_catalog_path",
    "write_records",
]
