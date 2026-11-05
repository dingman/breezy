"""Shared Arrow-tape-file mechanics for `k1_cheap_open_settlement.py` and
`cli_basis_offer_gate_scan.py`'s streaming readers.

Both modules stream `order_book_depths`/`quote_tick` feather/parquet files
column-projected rather than materializing full `OrderBookDepth10`/
`QuoteTick` Python objects for the whole tape (K1's measured 14.9-23.6 GB
peak; the offer-gate scan's measured 14-17 GB nightly peak, both driven by
the SAME pattern -- `ArrowSerializer.deserialize` building twenty `BookOrder`
objects per depth row for data neither consumer needs at that granularity).

Only the mechanics common to BOTH readers live here: opening one tape file
regardless of subtree, reading one file's `(instrument_id, price_precision,
size_precision)` identity once from its schema metadata, and decoding one
raw fixed-point cell. Each caller's own row-level PREDICATE -- K1 wants only
the winning ask per row; the offer-gate scan wants every level, because its
consumption is a genuine per-instant time series, not a single per-instrument
reduction -- is NOT shared, because it differs by consumer and sharing it
would smuggle one consumer's shape into the other.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

__all__ = [
    "decode_raw_fixed_point",
    "read_arrow_table",
    "table_identity",
]


def read_arrow_table(path: Path) -> pa.Table:
    """Open one tape file, whichever subtree it came from.

    `data/` holds catalog Parquet; `live/<run-id>/` holds the streaming
    Feather the recorder writes. Both are read here DIRECTLY rather than
    through `ParquetDataCatalog`, so a truncated file raises instead of
    silently contributing zero rows.
    """
    if path.suffix == ".parquet":
        return pq.read_table(path)
    with pa.ipc.open_stream(pa.memory_map(str(path))) as reader:
        return reader.read_all()


def table_identity(table: pa.Table) -> tuple[str, int, int]:
    """`(instrument_id, price_precision, size_precision)` for one tape file.

    One batch of either a depth or quote stream can only ever hold ONE
    instrument at one precision -- `ArrowSerializer.serialize_batch` itself
    raises `Mixed metadata` the moment two are combined -- so these are read
    ONCE per file from the schema metadata, never per row.
    """
    metadata = table.schema.metadata or {}
    return (
        metadata[b"instrument_id"].decode(),
        int(metadata[b"price_precision"]),
        int(metadata[b"size_precision"]),
    )


def decode_raw_fixed_point(value: bytes) -> int:
    """The undecoded raw integer behind one `fixed_size_binary[16]` cell.

    A plain byte->int conversion, NOT a scale factor: the scale (10**9 vs
    10**16 depending on build) is Nautilus' internal concern and is never
    re-derived here -- callers decode it via `Price.from_raw`/
    `Quantity.from_raw`.
    """
    return int.from_bytes(value, "little", signed=True)
