"""Unit tests for the archived backfill catalog readers and root separation."""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.archived_climate_day import (
    ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION,
    ArchivedClimateDay,
)
from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.persistence.archive_catalog import (
    archive_catalog_path,
    assert_archive_base_disjoint,
    read_archived_climate_days,
)
from breezy.persistence.catalog import (
    CatalogPathError,
    open_station_catalog,
    read_climate_day_as_of_settlement,
    read_climate_days,
    station_catalog_path,
    write_records,
)

_DAY = dt.date(2026, 8, 22)
_ISSUED_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
_ARCHIVE_RETRIEVED_NS = (
    int(dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
)
_SHA = hashlib.sha256(b"archive-catalog").hexdigest()


def make_archived_day(**overrides: Any) -> ArchivedClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "is_correction_bbb": False,
        "revision_seq": 1,
        "issuing_office": "KOKX",
        "wmo_transmission_sequence": "100",
        "wmo_bbb_token": None,
        "issuance_time_ns": _ISSUED_NS,
        "issuance_time_source": "wmo_filename",
        "archive_retrieved_at_ns": _ARCHIVE_RETRIEVED_NS,
        "archive_source_url": "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?<redacted>",
        "archive_job_version": "breezy-archive-backfill@stage2-test",
        "parser_version": "breezy.normalize.cli_parse@0.1.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "station_year_yield": 0.9836,
        "admission_era": "modern",
        "schema_version": ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION,
    }
    kwargs.update(overrides)
    return ArchivedClimateDay(**kwargs)


def make_live_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _ISSUED_NS + 300_000_000_000,
        "parser_version": "breezy.normalize.cli_parse@0.1.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp())
        * 1_000_000_000,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def test_archive_catalog_path_reuses_station_path_validation(tmp_path: Path) -> None:
    base = tmp_path / "archive"

    assert archive_catalog_path(base, "polymarket_us", "NYC") == station_catalog_path(
        base,
        "polymarket_us",
        "NYC",
    )

    with pytest.raises(CatalogPathError):
        archive_catalog_path(base, "polymarket_us", "../escape")


def test_archive_catalog_path_refuses_symlinked_derived_components(tmp_path: Path) -> None:
    base = tmp_path / "archive"
    (base / "polymarket_us" / "MDW").mkdir(parents=True)
    (base / "polymarket_us" / "NYC").symlink_to(base / "polymarket_us" / "MDW")

    with pytest.raises(CatalogPathError, match="symlink"):
        archive_catalog_path(base, "polymarket_us", "NYC")


def test_archive_base_nested_inside_settlement_base_fails_before_mkdir(tmp_path: Path) -> None:
    """Separation mutant: checking only settlement-in-archive direction."""
    settlement_base = tmp_path / "settlement"
    archive_base = settlement_base / "archive"

    with pytest.raises(CatalogPathError, match="must be disjoint"):
        assert_archive_base_disjoint(archive_base=archive_base, settlement_base=settlement_base)

    assert not settlement_base.exists()


def test_settlement_base_nested_inside_archive_base_fails_before_mkdir(tmp_path: Path) -> None:
    """Separation mutant: checking only archive-in-settlement direction."""
    archive_base = tmp_path / "archive"
    settlement_base = archive_base / "settlement"

    with pytest.raises(CatalogPathError, match="must be disjoint"):
        assert_archive_base_disjoint(archive_base=archive_base, settlement_base=settlement_base)

    assert not archive_base.exists()


def test_equal_archive_and_settlement_base_fails_before_mkdir(tmp_path: Path) -> None:
    base = tmp_path / "catalog"

    with pytest.raises(CatalogPathError, match="must be disjoint"):
        assert_archive_base_disjoint(archive_base=base, settlement_base=base)

    assert not base.exists()


def test_read_archived_climate_days_unwraps_and_filters_bounds(tmp_path: Path) -> None:
    root = archive_catalog_path(tmp_path / "archive", "polymarket_us", "NYC")
    root.mkdir(parents=True)
    catalog = ParquetDataCatalog(path=root)
    first = make_archived_day(climate_day=dt.date(2026, 8, 21))
    second = make_archived_day(
        climate_day=_DAY,
        issuance_time_ns=_ISSUED_NS + 60_000_000_000,
    )
    write_records(catalog, [first, second])

    records = read_archived_climate_days(
        catalog,
        station="NYC",
        start=second.ts_init,
        end=second.ts_init,
    )

    assert [record.to_dict() for record in records] == [second.to_dict()]


def test_read_archived_climate_days_raises_when_station_root_is_missing(tmp_path: Path) -> None:
    root = archive_catalog_path(tmp_path / "archive", "polymarket_us", "NYC")
    catalog = ParquetDataCatalog(path=root)

    with pytest.raises(FileNotFoundError, match="archived catalog root"):
        read_archived_climate_days(catalog, station="NYC")


def test_read_archived_climate_days_returns_empty_for_existing_empty_root(tmp_path: Path) -> None:
    root = archive_catalog_path(tmp_path / "archive", "polymarket_us", "NYC")
    root.mkdir(parents=True)
    catalog = ParquetDataCatalog(path=root)

    assert read_archived_climate_days(catalog, station="NYC") == []


def test_read_archived_climate_days_requires_the_requested_station(tmp_path: Path) -> None:
    root = archive_catalog_path(tmp_path / "archive", "polymarket_us", "NYC")
    root.mkdir(parents=True)
    catalog = ParquetDataCatalog(path=root)
    write_records(catalog, [make_archived_day()])

    with pytest.raises(ValueError, match="station"):
        read_archived_climate_days(catalog, station="MDW")


def test_no_settlement_shaped_archive_as_of_accessor_exists() -> None:
    """Separation mutant: adding the misuse-inviting settlement-shaped name."""
    from breezy.persistence import archive_catalog

    assert not hasattr(archive_catalog, "read_archived_climate_day_as_of_settlement")
    assert "read_archived_climate_day_as_of_settlement" not in archive_catalog.__all__


def test_settlement_reader_annotation_stays_live_only() -> None:
    """Separation mutant: widening settlement readers to return archived rows."""
    annotation = inspect.signature(read_climate_day_as_of_settlement).return_annotation

    assert annotation == "NwsClimateDay | None"


def test_settlement_readers_cannot_return_archived_rows_at_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separation mutant: any union of live and archived streams."""
    catalog = open_station_catalog(tmp_path / "settlement", "polymarket_us", "NYC")
    archived = make_archived_day()

    def foreign_result(*_args: object, **_kwargs: object) -> list[ArchivedClimateDay]:
        return [archived]

    monkeypatch.setattr(catalog, "custom_data", foreign_result)

    with pytest.raises(TypeError, match="ArchivedClimateDay"):
        read_climate_days(catalog)


def test_settlement_reader_ignores_archived_rows_written_to_the_same_root(tmp_path: Path) -> None:
    """Runtime attempt: even a wrong-root archived write is not read as settlement data."""
    catalog = open_station_catalog(tmp_path / "settlement", "polymarket_us", "NYC")
    write_records(catalog, [make_archived_day()])

    assert (
        read_climate_day_as_of_settlement(
            catalog,
            station="NYC",
            climate_day=_DAY,
            as_of_ts_init=_ISSUED_NS,
        )
        is None
    )

    write_records(catalog, [make_live_day()])
    selected = read_climate_day_as_of_settlement(
        catalog,
        station="NYC",
        climate_day=_DAY,
        as_of_ts_init=_ISSUED_NS + 300_000_000_000,
    )
    assert selected is not None
    assert selected.to_dict() == make_live_day().to_dict()
