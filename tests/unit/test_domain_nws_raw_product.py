"""Unit tests for `NwsRawProduct` — the immutable verbatim archive record.

api.weather.gov offers no archive guarantee, so the raw text lives in the catalog
(not only on the filesystem) and every settlement read verifies its digest first.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import pyarrow as pa
import pytest

from breezy.domain.nws_raw_product import RAW_PRODUCT_SCHEMA_VERSION, NwsRawProduct
from breezy.domain.strict_arrow import SchemaDriftError

_RAW_TEXT = (
    "000\nCDUS41 KOKX 230627\nCLINYC\n"
    "CLIMATE REPORT\nNATIONAL WEATHER SERVICE NEW YORK NY\n"
    "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 22 2026...\n"
    "MAXIMUM         84\nMINIMUM         63\n"
)
_RAW_SHA = hashlib.sha256(_RAW_TEXT.encode()).hexdigest()
_RESPONSE_SHA = hashlib.sha256(b'{"productText": "..."}').hexdigest()
_ISSUANCE_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_RETRIEVED_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


def make_raw_product(**overrides: Any) -> NwsRawProduct:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "product_uuid": "b6a5f0f6-0c1e-4f2a-9d3f-6b7c8d9e0f11",
        "product_code": "CLI",
        "issuing_office": "KOKX",
        "wmo_collective_id": "CDUS41",
        "awips_pil": "CLINYC",
        "wmo_bbb_token": None,
        "issuance_time_ns": _ISSUANCE_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "climate_day": dt.date(2026, 8, 22),
        "raw_text": _RAW_TEXT,
        "raw_sha256": _RAW_SHA,
        "response_sha256": _RESPONSE_SHA,
        "response_etag": None,
        "response_last_modified": None,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "registry_version": "sites.toml@1",
        "schema_version": RAW_PRODUCT_SCHEMA_VERSION,
    }
    kwargs.update(overrides)
    return NwsRawProduct(**kwargs)


def test_ts_event_is_issuance_and_ts_init_is_retrieval() -> None:
    record = make_raw_product()
    assert record.ts_event == _ISSUANCE_NS
    assert record.ts_init == _RETRIEVED_NS
    assert record.ts_event <= record.ts_init


def test_neither_timestamp_is_a_constructor_parameter() -> None:
    with pytest.raises(TypeError):
        make_raw_product(ts_event=1)
    with pytest.raises(TypeError):
        make_raw_product(ts_init=1)


def test_raw_sha256_must_match_the_raw_text() -> None:
    """The digest is verified at construction, so a mutated archive fails loudly."""
    with pytest.raises(ValueError, match="raw_sha256"):
        make_raw_product(raw_text=_RAW_TEXT + "tampered")


def test_verify_digest_recomputes_from_the_stored_text() -> None:
    record = make_raw_product()
    assert record.verify_digest() is True

    object.__setattr__(record, "raw_text", _RAW_TEXT + "tampered")
    assert record.verify_digest() is False


def test_response_sha256_must_be_64_lowercase_hex() -> None:
    with pytest.raises(ValueError, match="response_sha256"):
        make_raw_product(response_sha256="nope")


def test_empty_raw_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="raw_text"):
        make_raw_product(raw_text="", raw_sha256=hashlib.sha256(b"").hexdigest())


def test_nullable_provenance_fields_round_trip_as_none() -> None:
    record = make_raw_product(climate_day=None, awips_pil=None)
    restored = NwsRawProduct.from_dict(record.to_dict())
    assert restored.climate_day is None
    assert restored.awips_pil is None
    assert restored.wmo_bbb_token is None


def test_correction_token_is_preserved_verbatim() -> None:
    record = make_raw_product(wmo_bbb_token="CCA")
    assert NwsRawProduct.from_dict(record.to_dict()).wmo_bbb_token == "CCA"


def test_schema_field_order_types_and_nullability() -> None:
    schema = NwsRawProduct.schema()
    assert [(f.name, str(f.type), f.nullable) for f in schema] == [
        ("station", "string", False),
        ("product_uuid", "string", False),
        ("product_code", "string", False),
        ("issuing_office", "string", False),
        ("wmo_collective_id", "string", False),
        ("awips_pil", "string", True),
        ("wmo_bbb_token", "string", True),
        ("issuance_time_ns", "int64", False),
        ("retrieved_at_ns", "int64", False),
        ("climate_day", "date32[day]", True),
        ("raw_text", "string", False),
        ("raw_sha256", "string", False),
        ("response_sha256", "string", False),
        ("response_etag", "string", True),
        ("response_last_modified", "string", True),
        ("source_channel", "string", False),
        ("registry_version", "string", False),
        ("schema_version", "int64", False),
        ("ts_event", "int64", False),
        ("ts_init", "int64", False),
    ]


def test_registered_arrow_schema_is_the_classes_own_schema() -> None:
    from nautilus_trader.serialization.arrow.serializer import get_schema

    assert get_schema(NwsRawProduct) == NwsRawProduct.schema()


def test_to_dict_keys_match_the_schema_exactly() -> None:
    assert list(make_raw_product().to_dict()) == NwsRawProduct.schema().names


def test_arrow_round_trip_preserves_the_verbatim_text() -> None:
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_raw_product()
    batch = ArrowSerializer.serialize(original, NwsRawProduct)
    (restored,) = ArrowSerializer.deserialize(NwsRawProduct, pa.Table.from_batches([batch]))
    assert restored.raw_text == _RAW_TEXT
    assert restored.verify_digest() is True


def test_arrow_decoder_rejects_a_drifted_table() -> None:
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    batch = ArrowSerializer.serialize(make_raw_product(), NwsRawProduct)
    dropped = pa.Table.from_batches([batch]).drop_columns(["response_sha256"])

    with pytest.raises(SchemaDriftError, match="response_sha256"):
        ArrowSerializer.deserialize(NwsRawProduct, dropped)


def test_class_name_is_not_a_prefix_of_the_other_record_class() -> None:
    """Trap 5: a `DataType(X)` subscriber matches `XSomething` by msgbus glob."""
    from breezy.domain.nws_climate_day import NwsClimateDay

    a, b = NwsRawProduct.__name__, NwsClimateDay.__name__
    assert not a.startswith(b)
    assert not b.startswith(a)
