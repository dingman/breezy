"""Strict Arrow encode/decode helpers for Breezy's hand-written Nautilus `Data` types.

Why this module exists
----------------------
NautilusTrader 1.231.0 gives us serialization for free through
``register_arrow``, and Breezy does not reimplement any of it. What it does not
give us is *drift detection*, and drift here is silent:

* On read, ``ParquetDataCatalog._query_pyarrow`` builds
  ``pds.dataset(file_list, filesystem=..., schema=None)``
  (``persistence/catalog/parquet.py:2145``). With ``schema=None`` pyarrow infers
  the dataset schema from the **first fragment only**; every later fragment is
  coerced to it. Whichever file sorts first wins, permanently and
  non-deterministically. A column that disappeared comes back as ``None``.
* The bundled ``make_dict_deserializer``
  (``serialization/arrow/serializer.py:374``) calls ``data_cls.from_dict(d)`` on
  each row, so a class with per-field defaults absorbs the missing column
  silently. That is precisely why Breezy does not use ``@customdataclass``.
* On write, ``make_dict_serializer`` funnels into ``dicts_to_record_batch``
  (``:379``), which catches **every** exception, ``print``\\ s it, and returns
  ``None`` -- the caller then fails an opaque ``assert isinstance(batch,
  pa.RecordBatch)`` with the original error lost to stdout.
* Also on write: ``pa.RecordBatch.from_pylist`` does **not** honour
  ``nullable=False``. Verified on the pinned install --
  ``from_pylist([{"v": 1}], schema=<d not null, v>)`` yields ``{"d": None, "v":
  1}`` with no error. Arrow nullability is documentation on this path, not a
  constraint, so the encoder validates the payload itself.

Both helpers therefore fail loudly and name the offending columns.

Known limit of the read-side guard
----------------------------------
The decoder sees the *dataset* schema, which pyarrow has already unified from the
first fragment. Both real version-drift directions are caught, because the first
fragment is the oldest (``get_file_list_from_data_cls`` globs, and filenames are
zero-padded nanosecond ranges) and it is the oldest fragment that disagrees with
the newly registered schema. What this check cannot see is a *later*
fragment diverging while the first still matches -- its missing column is coerced
to NULL before the decoder runs.

The record constructors close most of that gap as defence in depth: a coerced NULL
raises wherever it contradicts a non-nullable field guard or a paired value/sentinel
flag column. The residual hole is narrow -- a genuinely nullable column whose NULL
is legitimate in isolation, i.e. a ``*_flag`` beside a present value. The strict
encoder makes even that unreachable through Breezy's own write path, so the
exposure is a foreign or corrupted fragment. Pinned by
``tests/contract/test_catalog_nws_records.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import pyarrow as pa


class ArrowRecord(Protocol):
    """The surface a Breezy record class exposes to the Arrow (de)serializers."""

    def to_dict(self) -> dict[str, Any]:
        """Return the record as Arrow-native values, keyed in `schema()` order."""
        ...

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> Any:
        """Rebuild a record from `to_dict` output, raising on any missing key."""
        ...


class SchemaDriftError(RuntimeError):
    """Raised when an Arrow payload does not match its registered schema exactly.

    Never downgrade this to a warning, and never repair the payload. A settlement
    value silently defaulted to ``None`` is indistinguishable from a genuine NWS
    ``M`` sentinel once it has been written.
    """


def _format_columns(columns: set[str]) -> str:
    return ", ".join(repr(name) for name in sorted(columns))


def make_strict_encoder(
    schema: pa.Schema,
) -> Callable[[ArrowRecord | list[ArrowRecord]], pa.RecordBatch]:
    """Build an encoder that rejects any payload whose keys differ from `schema`.

    The returned callable accepts either a single record or a list of records,
    matching the two ways ``ArrowSerializer`` invokes an encoder
    (``serialize`` passes one object; a batch encoder would receive a list).
    """
    expected = list(schema.names)
    expected_set = set(expected)

    def encode(data: ArrowRecord | list[ArrowRecord]) -> pa.RecordBatch:
        records = data if isinstance(data, list) else [data]
        rows: list[dict[str, Any]] = []

        for record in records:
            row = record.to_dict()
            keys = set(row)

            missing = expected_set - keys
            unexpected = keys - expected_set

            if missing or unexpected:
                raise SchemaDriftError(
                    f"`{type(record).__name__}.to_dict()` does not match its registered "
                    f"Arrow schema: "
                    f"missing columns [{_format_columns(missing)}]; "
                    f"unexpected columns [{_format_columns(unexpected)}]. "
                    f"Refusing to encode -- pyarrow would write NULL into the missing "
                    f"columns even where the schema declares them non-nullable.",
                )

            rows.append({name: row[name] for name in expected})

        return pa.RecordBatch.from_pylist(rows, schema=schema)

    return encode


def make_strict_decoder(
    data_cls: type[ArrowRecord],
    schema: pa.Schema,
) -> Callable[[pa.Table | pa.RecordBatch], list[Any]]:
    """Build a decoder that raises `SchemaDriftError` instead of defaulting.

    Checks column presence, absence of unexpected columns, and per-column Arrow
    type. Any of the three indicates the fragment on disk was written by a
    different version of the record class.
    """
    expected_types = {field.name: field.type for field in schema}
    expected_set = set(expected_types)

    def decode(table: pa.Table | pa.RecordBatch) -> list[Any]:
        if not isinstance(table, pa.Table | pa.RecordBatch):
            raise TypeError(
                f"expected a `pyarrow.Table` or `pyarrow.RecordBatch`, was {type(table)!r}",
            )

        actual_types = {field.name: field.type for field in table.schema}
        actual_set = set(actual_types)

        missing = expected_set - actual_set
        unexpected = actual_set - expected_set

        if missing or unexpected:
            raise SchemaDriftError(
                f"Arrow schema drift reading `{data_cls.__name__}`: "
                f"missing columns [{_format_columns(missing)}]; "
                f"unexpected columns [{_format_columns(unexpected)}]. "
                f"Refusing to decode -- missing columns would otherwise be "
                f"silently substituted with default values.",
            )

        mismatched = [
            f"{name!r} expected {expected_types[name]} but found {actual_types[name]}"
            for name in sorted(expected_set)
            if actual_types[name] != expected_types[name]
        ]

        if mismatched:
            raise SchemaDriftError(
                f"Arrow column type drift reading `{data_cls.__name__}`: "
                + "; ".join(mismatched)
                + ". Refusing to decode -- pyarrow would coerce the values silently.",
            )

        return [data_cls.from_dict(row) for row in table.to_pylist()]

    return decode
