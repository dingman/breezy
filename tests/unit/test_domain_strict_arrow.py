"""Unit tests for the strict Arrow encoder/decoder seam.

The strict decoder is the ONLY reliable schema-drift detection point in the
1.231.0 read path: `_query_pyarrow` builds `pds.dataset(file_list, schema=None)`
(`persistence/catalog/parquet.py:2145`), so pyarrow infers the schema from
whichever fragment sorts first and silently coerces the rest.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pyarrow as pa
import pytest

from breezy.domain.strict_arrow import SchemaDriftError, make_strict_decoder, make_strict_encoder


class _Rec:
    def __init__(self, d: dt.date, v: int | None) -> None:
        self.d = d
        self.v = v

    def to_dict(self) -> dict[str, Any]:
        return {"d": self.d, "v": self.v}

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> _Rec:
        # Matches `ArrowRecord.from_dict`'s own `dict[str, Any]` signature
        # (src/breezy/domain/strict_arrow.py) so this double cannot drift
        # from the Protocol it models.
        return cls(values["d"], values["v"])


_SCHEMA = pa.schema(
    [
        pa.field("d", pa.date32(), nullable=False),
        pa.field("v", pa.int64(), nullable=True),
    ],
)


def test_encoder_round_trips_a_null_value() -> None:
    encoder = make_strict_encoder(_SCHEMA)
    batch = encoder(_Rec(dt.date(2026, 8, 22), None))
    assert isinstance(batch, pa.RecordBatch)
    assert batch.to_pylist() == [{"d": dt.date(2026, 8, 22), "v": None}]


def test_encoder_accepts_a_list_of_records() -> None:
    encoder = make_strict_encoder(_SCHEMA)
    batch = encoder([_Rec(dt.date(2026, 8, 22), 84), _Rec(dt.date(2026, 8, 23), 85)])
    assert batch.num_rows == 2


def test_encoder_raises_when_to_dict_omits_a_column() -> None:
    """pyarrow silently writes NULL into a ``nullable=False`` field on this path.

    Verified: ``pa.RecordBatch.from_pylist([{"v": 1}], schema=...)`` yields
    ``{"d": None, "v": 1}`` with no error even though ``d`` is declared not-null.
    The encoder must therefore reject the dict itself.
    """
    encoder = make_strict_encoder(_SCHEMA)

    class _Broken(_Rec):
        def to_dict(self) -> dict[str, object]:
            return {"v": 1}

    with pytest.raises(SchemaDriftError, match="d"):
        encoder(_Broken(dt.date(2026, 8, 22), 1))


def test_encoder_raises_on_an_unexpected_column() -> None:
    encoder = make_strict_encoder(_SCHEMA)

    class _Broken(_Rec):
        def to_dict(self) -> dict[str, object]:
            return {"d": self.d, "v": self.v, "surprise": 1}

    with pytest.raises(SchemaDriftError, match="surprise"):
        encoder(_Broken(dt.date(2026, 8, 22), 1))


def test_decoder_raises_naming_every_missing_column() -> None:
    decoder = make_strict_decoder(_Rec, _SCHEMA)
    drifted = pa.Table.from_pylist([{"v": 84}], schema=pa.schema([pa.field("v", pa.int64())]))

    with pytest.raises(SchemaDriftError) as excinfo:
        decoder(drifted)

    message = str(excinfo.value)
    assert "_Rec" in message
    assert "'d'" in message


def test_decoder_raises_on_unexpected_columns() -> None:
    decoder = make_strict_decoder(_Rec, _SCHEMA)
    drifted_schema = pa.schema(
        [
            pa.field("d", pa.date32(), nullable=False),
            pa.field("v", pa.int64(), nullable=True),
            pa.field("surprise", pa.string(), nullable=True),
        ],
    )
    drifted = pa.Table.from_pylist(
        [{"d": dt.date(2026, 8, 22), "v": 84, "surprise": "x"}],
        schema=drifted_schema,
    )

    with pytest.raises(SchemaDriftError, match="surprise"):
        decoder(drifted)


def test_decoder_raises_on_a_type_change() -> None:
    decoder = make_strict_decoder(_Rec, _SCHEMA)
    drifted_schema = pa.schema(
        [
            pa.field("d", pa.date32(), nullable=False),
            pa.field("v", pa.string(), nullable=True),
        ],
    )
    drifted = pa.Table.from_pylist(
        [{"d": dt.date(2026, 8, 22), "v": "84"}],
        schema=drifted_schema,
    )

    with pytest.raises(SchemaDriftError, match="int64"):
        decoder(drifted)


def test_decoder_accepts_a_matching_table() -> None:
    decoder = make_strict_decoder(_Rec, _SCHEMA)
    table = pa.Table.from_pylist([{"d": dt.date(2026, 8, 22), "v": None}], schema=_SCHEMA)
    (record,) = decoder(table)
    assert record.d == dt.date(2026, 8, 22)
    assert record.v is None
