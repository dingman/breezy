"""Unit tests for archived CLI backfill record types."""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from nautilus_trader.common.component import is_matching_py

from breezy.domain.archived_climate_day import (
    ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION,
    ArchivedClimateDay,
)
from breezy.domain.archived_raw_product import (
    ARCHIVED_RAW_PRODUCT_SCHEMA_VERSION,
    ArchivedRawProduct,
)
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.domain.strict_arrow import SchemaDriftError
from breezy.persistence.catalog import _read, open_station_catalog, write_records

_ROOT = Path(__file__).resolve().parents[2]
_RAW_TEXT = (
    "000\nCDUS41 KOKX 230627\nCLINYC\n"
    "CLIMATE REPORT\nNATIONAL WEATHER SERVICE NEW YORK NY\n"
    "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 22 2026...\n"
    "MAXIMUM         84\nMINIMUM         63\nAVERAGE         74\n"
)
_RAW_SHA = hashlib.sha256(_RAW_TEXT.encode()).hexdigest()
_ALT_RAW_TEXT = _RAW_TEXT.replace("AVERAGE         74", "AVERAGE         74   ")
_ALT_RAW_SHA = hashlib.sha256(_ALT_RAW_TEXT.encode()).hexdigest()
_ISSUANCE_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_ARCHIVE_RETRIEVED_NS = int(
    dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000,
)


def make_archived_climate_day(**overrides: Any) -> ArchivedClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": dt.date(2026, 8, 22),
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
        "wmo_transmission_sequence": "000",
        "wmo_bbb_token": None,
        "issuance_time_ns": _ISSUANCE_NS,
        "issuance_time_source": "wmo_filename",
        "archive_retrieved_at_ns": _ARCHIVE_RETRIEVED_NS,
        "archive_source_url": "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?<redacted>",
        "archive_job_version": "breezy-archive-backfill@stage1-test",
        "parser_version": "breezy.normalize.cli_parse@0.1.0",
        "registry_version": "1.0.0",
        "raw_sha256": _RAW_SHA,
        "station_year_yield": 0.9836,
        "admission_era": "modern",
        "schema_version": ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION,
    }
    kwargs.update(overrides)
    return ArchivedClimateDay(**kwargs)


def make_archived_raw_product(**overrides: Any) -> ArchivedRawProduct:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "product_code": "CLI",
        "issuing_office": "KOKX",
        "wmo_collective_id": "CDUS41",
        "awips_pil": "CLINYC",
        "wmo_bbb_token": None,
        "issuance_time_ns": _ISSUANCE_NS,
        "issuance_time_source": "wmo_filename",
        "archive_retrieved_at_ns": _ARCHIVE_RETRIEVED_NS,
        "climate_day": dt.date(2026, 8, 22),
        "raw_text": _RAW_TEXT,
        "raw_sha256": _RAW_SHA,
        "archive_source_url": "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?<redacted>",
        "archive_job_version": "breezy-archive-backfill@stage1-test",
        "registry_version": "1.0.0",
        "schema_version": ARCHIVED_RAW_PRODUCT_SCHEMA_VERSION,
    }
    kwargs.update(overrides)
    return ArchivedRawProduct(**kwargs)


def test_archived_climate_day_timestamps_are_issuance_and_not_constructor_params() -> None:
    """Record mutant: adding `ts_init`/`ts_event` constructor parameters."""
    record = make_archived_climate_day()
    assert record.ts_init == record.ts_event == record.issuance_time_ns == _ISSUANCE_NS

    with pytest.raises(TypeError):
        make_archived_climate_day(ts_init=1)
    with pytest.raises(TypeError):
        make_archived_climate_day(ts_event=1)


@pytest.mark.parametrize("column", ["ts_init", "ts_event"])
def test_archived_climate_day_from_dict_rejects_timestamp_disagreement(column: str) -> None:
    """Record mutant: deleting the decode-time equality check."""
    values = make_archived_climate_day().to_dict()
    values[column] += 1

    with pytest.raises(ValueError, match=column):
        ArchivedClimateDay.from_dict(values)


def test_archived_climate_day_rejects_retrieval_before_issuance() -> None:
    """Record mutant: flipping or removing the archived receipt comparison."""
    with pytest.raises(ValueError, match="archive_retrieved_at_ns"):
        make_archived_climate_day(archive_retrieved_at_ns=_ISSUANCE_NS - 1)


def test_archived_climate_day_is_not_live_climate_day_subclass_in_either_direction() -> None:
    """Record mutant: subclassing across the archive/live separation barrier."""
    assert not issubclass(ArchivedClimateDay, NwsClimateDay)
    assert not issubclass(NwsClimateDay, ArchivedClimateDay)


def test_archived_climate_day_missing_column_raises_key_error() -> None:
    """Record mutant: replacing a direct subscript with `.get(...)`."""
    values = make_archived_climate_day().to_dict()
    del values["station_year_yield"]

    with pytest.raises(KeyError):
        ArchivedClimateDay.from_dict(values)


def test_archived_modules_register_arrow_once_each() -> None:
    """Record mutant: adding a second module-scope `register_arrow` call."""
    for relative in (
        "src/breezy/domain/archived_climate_day.py",
        "src/breezy/domain/archived_raw_product.py",
        "src/breezy/domain/station_observation.py",
    ):
        tree = ast.parse((_ROOT / relative).read_text())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "register_arrow"
        ]
        assert len(calls) == 1, relative


def test_archived_climate_day_arrow_round_trip_preserves_every_field() -> None:
    """Record mutant: loosening the strict decoder or coercing value/flag pairs."""
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_archived_climate_day(tmax_f=None, tmax_flag="M")
    batch = ArrowSerializer.serialize(original, ArchivedClimateDay)
    assert batch.schema == ArchivedClimateDay.schema()

    (restored,) = ArrowSerializer.deserialize(ArchivedClimateDay, pa.Table.from_batches([batch]))
    assert restored.to_dict() == original.to_dict()


def test_archived_climate_day_arrow_decode_rejects_missing_fragment_column() -> None:
    """Record mutant: letting a missing column default during catalog decode."""
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    batch = ArrowSerializer.serialize(make_archived_climate_day(), ArchivedClimateDay)
    drifted = pa.Table.from_batches([batch]).drop_columns(["admission_era"])

    with pytest.raises(SchemaDriftError, match="admission_era"):
        ArrowSerializer.deserialize(ArchivedClimateDay, drifted)


def test_archived_climate_day_rejects_none_station_year_yield() -> None:
    """Record mutant: routing `station_year_yield` through the optional-float
    helper without re-adding the required-ness check (Finding 3 regression)."""
    with pytest.raises(TypeError, match="station_year_yield"):
        make_archived_climate_day(station_year_yield=None)


def test_archived_climate_day_rejects_non_numeric_station_year_yield() -> None:
    """Record mutant: dropping the type-coercion guard inherited from
    `require_optional_float` when Finding 3's `require_float` was introduced."""
    with pytest.raises(TypeError, match="station_year_yield"):
        make_archived_climate_day(station_year_yield="0.98")


def test_station_year_yield_and_admission_era_are_non_null_round_trip_fields() -> None:
    """Record mutant: omitting Revision 2's unaddable bias-analysis covariates."""
    restored = ArchivedClimateDay.from_dict(make_archived_climate_day().to_dict())

    assert restored.station_year_yield == 0.9836
    assert isinstance(restored.station_year_yield, float)
    assert restored.admission_era == "modern"
    assert "station_year_yield" in ArchivedClimateDay.schema().names
    assert "admission_era" in ArchivedClimateDay.schema().names


@pytest.mark.parametrize("admission_era", ["modern", "transitional"])
def test_admission_era_accepts_only_the_backfill_plan_vocabulary(admission_era: str) -> None:
    record = make_archived_climate_day(admission_era=admission_era)

    assert record.admission_era == admission_era


@pytest.mark.parametrize("admission_era", ["Modern", "legacy"])
def test_archived_climate_day_rejects_unknown_admission_era(admission_era: str) -> None:
    with pytest.raises(ValueError, match="admission_era"):
        make_archived_climate_day(admission_era=admission_era)


def test_archived_climate_day_from_dict_rejects_unknown_admission_era() -> None:
    values = make_archived_climate_day().to_dict()
    values["admission_era"] = "legacy"

    with pytest.raises(ValueError, match="admission_era"):
        ArchivedClimateDay.from_dict(values)


@pytest.mark.parametrize(
    ("wmo_bbb_token", "is_correction_bbb"),
    [(None, False), ("CCA", True), ("CCC", True), ("RRA", False), ("AAA", False)],
)
def test_is_correction_bbb_must_agree_with_wmo_bbb_token(
    wmo_bbb_token: str | None,
    is_correction_bbb: bool,
) -> None:
    record = make_archived_climate_day(
        wmo_bbb_token=wmo_bbb_token,
        is_correction_bbb=is_correction_bbb,
    )

    assert record.wmo_bbb_token == wmo_bbb_token
    assert record.is_correction_bbb is is_correction_bbb


@pytest.mark.parametrize(
    ("wmo_bbb_token", "is_correction_bbb"),
    [("CCA", False), ("CCC", False), ("RRA", True), (None, True)],
)
def test_archived_climate_day_rejects_correction_bbb_disagreement(
    wmo_bbb_token: str | None,
    is_correction_bbb: bool,
) -> None:
    with pytest.raises(ValueError, match="is_correction_bbb"):
        make_archived_climate_day(
            wmo_bbb_token=wmo_bbb_token,
            is_correction_bbb=is_correction_bbb,
        )


def test_archived_climate_day_from_dict_rejects_correction_bbb_disagreement() -> None:
    values = make_archived_climate_day(wmo_bbb_token="CCA", is_correction_bbb=True).to_dict()
    values["is_correction_bbb"] = False

    with pytest.raises(ValueError, match="is_correction_bbb"):
        ArchivedClimateDay.from_dict(values)


def test_archived_record_topics_do_not_prefix_collide_with_live_record_topics() -> None:
    """Record mutant: adding an archived type whose class name shares the live prefix."""
    pairs = (
        (ArchivedClimateDay, NwsClimateDay),
        (NwsClimateDay, ArchivedClimateDay),
        (ArchivedRawProduct, NwsRawProduct),
        (NwsRawProduct, ArchivedRawProduct),
    )

    for publisher, subscriber in pairs:
        assert not is_matching_py(f"data.{publisher.__name__}*", f"data.{subscriber.__name__}*")


def test_archived_raw_product_has_no_product_uuid_and_verifies_digest() -> None:
    """Record mutant: inventing IEM product UUID provenance."""
    record = make_archived_raw_product()

    assert not hasattr(record, "product_uuid")
    assert record.verify_digest() is True
    with pytest.raises(TypeError):
        make_archived_raw_product(product_uuid="invented")


def test_archived_raw_product_rejects_digest_mismatch() -> None:
    """Record mutant: trusting the stored digest without recomputing it."""
    with pytest.raises(ValueError, match="raw_sha256"):
        make_archived_raw_product(raw_text=_ALT_RAW_TEXT, raw_sha256=_RAW_SHA)


def test_archived_raw_product_arrow_round_trip_preserves_verbatim_text() -> None:
    """Record mutant: normalising archived text before hashing or writing."""
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_archived_raw_product()
    batch = ArrowSerializer.serialize(original, ArchivedRawProduct)
    (restored,) = ArrowSerializer.deserialize(ArchivedRawProduct, pa.Table.from_batches([batch]))

    assert restored.to_dict() == original.to_dict()
    assert restored.raw_text == _RAW_TEXT
    assert restored.verify_digest() is True


def test_value_identical_byte_different_archive_records_coexist_and_select_deterministically(
    tmp_path: Path,
) -> None:
    """Record mutant: collapsing byte-different retransmissions into one row."""
    first = make_archived_climate_day(revision_seq=1, raw_sha256=_RAW_SHA)
    second = make_archived_climate_day(revision_seq=2, raw_sha256=_ALT_RAW_SHA)
    raw_first = make_archived_raw_product(raw_text=_RAW_TEXT, raw_sha256=_RAW_SHA)
    raw_second = make_archived_raw_product(raw_text=_ALT_RAW_TEXT, raw_sha256=_ALT_RAW_SHA)
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    outcome = write_records(catalog, [first, second, raw_first, raw_second])
    restored_days = _read(catalog, ArchivedClimateDay)
    restored_raw = _read(catalog, ArchivedRawProduct)

    assert len(outcome.written) == 4
    assert {record.raw_sha256 for record in restored_days} == {_RAW_SHA, _ALT_RAW_SHA}
    assert {record.raw_sha256 for record in restored_raw} == {_RAW_SHA, _ALT_RAW_SHA}
    selected = max(
        restored_days,
        key=lambda record: (record.is_final, record.ts_init, record.revision_seq),
    )
    assert selected.raw_sha256 == _ALT_RAW_SHA
    assert (selected.tmax_f, selected.tmin_f, selected.tavg_f) == (84, 63, 74)
