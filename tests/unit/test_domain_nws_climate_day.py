"""Unit tests for `NwsClimateDay` — the normalized, settlement-grade CLI record."""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import pyarrow as pa
import pytest

from breezy.domain.nws_climate_day import (
    CLIMATE_DAY_SCHEMA_VERSION,
    MISSING_VALUE_FLAGS,
    NwsClimateDay,
)
from breezy.domain.strict_arrow import SchemaDriftError

# Aug 22 2026 24:00 EST (local STANDARD time, never EDT) == Aug 23 05:00 UTC.
_CLIMATE_DAY_END_NS = int(
    dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000,
)
_ISSUANCE_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_RETRIEVED_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
# The ~4:44 PM local preliminary for the same climate day, and the poll that got it.
_PRELIM_ISSUED_NS = int(dt.datetime(2026, 8, 22, 20, 44, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_PRELIM_RETRIEVED_NS = int(
    dt.datetime(2026, 8, 22, 20, 49, tzinfo=dt.UTC).timestamp() * 1_000_000_000,
)
_SHA = hashlib.sha256(b"CDUS41 KOKX 230627").hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": dt.date(2026, 8, 22),
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _ISSUANCE_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "sites.toml@1",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _CLIMATE_DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


# --------------------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------------------


def test_ts_init_is_retrieved_at_ns_and_is_not_a_constructor_parameter() -> None:
    """§4.2: ts_init is stamped once at retrieval and propagated, never re-stamped."""
    record = make_climate_day()
    assert record.ts_init == record.retrieved_at_ns == _RETRIEVED_NS

    with pytest.raises(TypeError):
        make_climate_day(ts_init=123)


def test_ts_event_is_the_caller_supplied_semantic_instant() -> None:
    """The default fixture is final-shaped, so its `ts_event` is the climate-day end."""
    record = make_climate_day()
    assert record.is_final is True
    assert record.ts_event == _CLIMATE_DAY_END_NS
    assert record.ts_event <= record.ts_init


def test_preliminary_ts_event_is_the_issuance_instant_and_precedes_retrieval() -> None:
    """A preliminary's `ts_event` is when it was issued -- never the climate-day end.

    So `ts_event <= ts_init` holds for every preliminary the pipeline can build:
    `NwsRawProduct` rejects `issuance_time_ns > retrieved_at_ns`, and
    `build_climate_day` copies that same issuance instant into `ts_event`.
    Asserting the ordering for preliminaries would therefore be vacuous, which is
    why `build_climate_day` scopes the assertion to finals. Derivation itself is
    pinned in `tests/unit/test_ingest_records.py`.
    """
    preliminary = make_climate_day(
        is_final=False,
        issuance_time_ns=_PRELIM_ISSUED_NS,
        retrieved_at_ns=_PRELIM_RETRIEVED_NS,
        ts_event=_PRELIM_ISSUED_NS,
    )

    assert preliminary.ts_event == preliminary.issuance_time_ns
    assert preliminary.ts_event <= preliminary.ts_init


def test_no_global_ts_event_le_ts_init_invariant_is_enforced() -> None:
    """No ordering check here, for *either* issuance class.

    Not headroom for preliminaries -- a preliminary's `ts_event` is its issuance
    instant and cannot post-date retrieval. The finals-only assertion is an
    ingestion-time classification guard in `build_climate_day`; this type stores
    what it is handed, including on the `from_dict` decode path that must rebuild
    rows already written. Enforcing the ordering here -- globally or for one class
    -- fails this test.
    """
    for is_final in (True, False):
        record = make_climate_day(
            is_final=is_final,
            ts_event=_RETRIEVED_NS + 3_600 * 1_000_000_000,
        )
        assert record.ts_event > record.ts_init


# --------------------------------------------------------------------------------------
# Record invariants
# --------------------------------------------------------------------------------------


def test_missing_value_requires_a_sentinel_flag() -> None:
    with pytest.raises(ValueError, match="tmax_flag"):
        make_climate_day(tmax_f=None, tmax_flag=None)


def test_present_value_forbids_a_sentinel_flag() -> None:
    with pytest.raises(ValueError, match="tmin_flag"):
        make_climate_day(tmin_f=63, tmin_flag="M")


def test_missing_value_with_flag_is_accepted() -> None:
    record = make_climate_day(tmax_f=None, tmax_flag="M")
    assert record.tmax_f is None
    assert record.tmax_flag == "M"


def test_unknown_sentinel_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="XX"):
        make_climate_day(tmax_f=None, tmax_flag="XX")


def test_tmin_above_tmax_is_rejected() -> None:
    with pytest.raises(ValueError, match="tmin_f"):
        make_climate_day(tmax_f=60, tmin_f=70)


def test_revision_seq_starts_at_one() -> None:
    with pytest.raises(ValueError, match="revision_seq"):
        make_climate_day(revision_seq=0)


def test_raw_sha256_must_be_64_lowercase_hex() -> None:
    with pytest.raises(ValueError, match="raw_sha256"):
        make_climate_day(raw_sha256="deadbeef")

    with pytest.raises(ValueError, match="raw_sha256"):
        make_climate_day(raw_sha256=_SHA.upper())


def test_datetime_is_rejected_where_a_date_is_required() -> None:
    """`datetime` subclasses `date`; date32 would silently truncate the time part."""
    with pytest.raises(TypeError, match="climate_day"):
        make_climate_day(climate_day=dt.datetime(2026, 8, 22, 12, tzinfo=dt.UTC))


def test_blank_station_is_rejected() -> None:
    with pytest.raises(ValueError, match="station"):
        make_climate_day(station="")


# --------------------------------------------------------------------------------------
# Arrow schema
# --------------------------------------------------------------------------------------


def test_schema_field_order_types_and_nullability() -> None:
    schema = NwsClimateDay.schema()
    assert [(f.name, str(f.type), f.nullable) for f in schema] == [
        ("station", "string", False),
        ("climate_day", "date32[day]", False),
        ("tmax_f", "int64", True),
        ("tmin_f", "int64", True),
        ("tavg_f", "int64", True),
        ("tmax_flag", "string", True),
        ("tmin_flag", "string", True),
        ("tavg_flag", "string", True),
        ("is_final", "bool", False),
        ("correction_flag", "bool", False),
        ("revision_seq", "int64", False),
        ("is_superseded", "bool", False),
        ("issuing_office", "string", False),
        ("issuance_time_ns", "int64", False),
        ("retrieved_at_ns", "int64", False),
        ("parser_version", "string", False),
        ("registry_version", "string", False),
        ("raw_sha256", "string", False),
        ("source_channel", "string", False),
        ("schema_version", "int64", False),
        ("ts_event", "int64", False),
        ("ts_init", "int64", False),
    ]


def test_schema_returns_an_equal_schema_on_every_call() -> None:
    assert NwsClimateDay.schema() == NwsClimateDay.schema()


def test_registered_arrow_schema_is_the_classes_own_schema() -> None:
    from nautilus_trader.serialization.arrow.serializer import get_schema

    assert get_schema(NwsClimateDay) == NwsClimateDay.schema()


def test_to_dict_keys_match_the_schema_exactly() -> None:
    assert list(make_climate_day().to_dict()) == NwsClimateDay.schema().names


def test_to_dict_from_dict_round_trip_preserves_every_field() -> None:
    original = make_climate_day(
        tmax_f=None,
        tmax_flag="M",
        tavg_f=None,
        tavg_flag="MS",
    )
    restored = NwsClimateDay.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()
    assert restored.ts_event == original.ts_event
    assert restored.ts_init == original.ts_init


def test_from_dict_rejects_a_ts_init_that_disagrees_with_retrieved_at_ns() -> None:
    values = make_climate_day().to_dict()
    values["ts_init"] = values["ts_init"] + 1
    with pytest.raises(ValueError, match="ts_init"):
        NwsClimateDay.from_dict(values)


def test_from_dict_raises_on_a_missing_key_rather_than_defaulting() -> None:
    values = make_climate_day().to_dict()
    del values["tmax_f"]
    with pytest.raises(KeyError):
        NwsClimateDay.from_dict(values)


def test_arrow_encoder_round_trips_through_a_record_batch() -> None:
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_climate_day(tmin_f=None, tmin_flag="MS")
    batch = ArrowSerializer.serialize(original, NwsClimateDay)
    assert batch.schema == NwsClimateDay.schema()

    (restored,) = ArrowSerializer.deserialize(NwsClimateDay, pa.Table.from_batches([batch]))
    assert restored.to_dict() == original.to_dict()


def test_arrow_decoder_rejects_a_drifted_table() -> None:
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_climate_day()
    batch = ArrowSerializer.serialize(original, NwsClimateDay)
    dropped = pa.Table.from_batches([batch]).drop_columns(["tavg_f"])

    with pytest.raises(SchemaDriftError, match="tavg_f"):
        ArrowSerializer.deserialize(NwsClimateDay, dropped)


def test_repr_does_not_leak_the_raw_product_text() -> None:
    text = repr(make_climate_day())
    assert "NwsClimateDay" in text
    assert "station='NYC'" in text


# --------------------------------------------------------------------------------------
# tavg_f is the product's PUBLISHED average, not a computed midpoint
# --------------------------------------------------------------------------------------


def test_tavg_f_is_a_whole_degree_int_not_a_computed_midpoint() -> None:
    """The CLI prints its own AVERAGE line as a whole-degree integer.

    That published integer is the settlement datum. Deriving `(tmax+tmin)/2`
    ourselves would invent a settlement number, which is forbidden in the same
    terms as imputing a sentinel -- so the field cannot hold a `.5` midpoint.
    """
    record = make_climate_day(tavg_f=74)
    assert record.tavg_f == 74
    assert isinstance(record.tavg_f, int)

    with pytest.raises(TypeError, match="tavg_f"):
        make_climate_day(tavg_f=73.5)


def test_tavg_f_matches_the_tmax_tmin_representation() -> None:
    """`tavg` is parsed through the same sentinel machinery as tmax/tmin."""
    schema = NwsClimateDay.schema()
    types = {field.name: (str(field.type), field.nullable) for field in schema}
    assert types["tavg_f"] == types["tmax_f"] == types["tmin_f"]
    assert types["tavg_flag"] == types["tmax_flag"] == types["tmin_flag"]


def test_missing_average_requires_a_sentinel_flag() -> None:
    with pytest.raises(ValueError, match="tavg_flag"):
        make_climate_day(tavg_f=None, tavg_flag=None)


def test_present_average_forbids_a_sentinel_flag() -> None:
    with pytest.raises(ValueError, match="tavg_flag"):
        make_climate_day(tavg_f=74, tavg_flag="M")


def test_unknown_average_sentinel_flag_is_rejected() -> None:
    with pytest.raises(ValueError, match="ZZ"):
        make_climate_day(tavg_f=None, tavg_flag="ZZ")


def test_missing_and_trace_average_are_distinguishable() -> None:
    """ "Missing" and "trace" are different facts; collapsing both to `None` is a bug."""
    missing = make_climate_day(tavg_f=None, tavg_flag="M")
    trace = make_climate_day(tavg_f=None, tavg_flag="T")

    assert missing.tavg_f is None
    assert trace.tavg_f is None
    assert missing.tavg_flag != trace.tavg_flag

    assert NwsClimateDay.from_dict(missing.to_dict()).tavg_flag == "M"
    assert NwsClimateDay.from_dict(trace.to_dict()).tavg_flag == "T"


def test_every_average_sentinel_kind_round_trips() -> None:
    for flag in MISSING_VALUE_FLAGS:
        record = make_climate_day(tavg_f=None, tavg_flag=flag)
        assert NwsClimateDay.from_dict(record.to_dict()).tavg_flag == flag


def test_schema_version_was_bumped_for_the_tavg_layout_change() -> None:
    """`tavg_f` int64 + the new `tavg_flag` column changed the Arrow layout."""
    assert CLIMATE_DAY_SCHEMA_VERSION == 2
    assert make_climate_day().schema_version == CLIMATE_DAY_SCHEMA_VERSION
