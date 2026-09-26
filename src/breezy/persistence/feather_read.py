"""A coalesced Arrow IPC feather reader (ING-2 S3a).

Null hypothesis, checked before writing this (see the ING-2 S3 plan,
``docs/plans/backlog/ING-2_2026-09-25/ING-2_S3_plan_r2_2026-09-26.md``, Arch
S1): Nautilus' own ``ParquetDataCatalog._read_feather_file``
(``persistence/catalog/parquet.py:2788-2800``) reads a whole stream with one
``reader.read_all()``, which materialises every message's own small
``RecordBatch`` AND the final concatenated table at once. On a one-row-per-
message stream (the recorder's actual shape) that costs about 5.3 KB per
message versus about 110 B per row of logical data -- a measured 48x
overhead (Stage-0 findings). Nautilus offers no batched or streaming
alternative to ``read_all()``; this module is the smallest correct extension
that keeps the SAME reader (``pyarrow.ipc.open_stream``) and the SAME
exception scope, and only changes how the batches are accumulated.

This module is pyarrow-only and must never import ``breezy.runtime``
(enforced by ``lint-imports``): it exists to be usable from the salvage
preflight path as well as the ingest CLI, and importing runtime machinery
here would invert that dependency direction.

The implementation is byte-for-byte the reviewed Phase 0 prototype
(``proto_feather_read.py``, plan P1 fix), diffed against this file before
merge -- see the ING-2 S3 Stage-0 findings, "Phase 0 results".
"""

from __future__ import annotations

import fsspec
import pyarrow as pa

#: At the measured 5.3 KB per message (Stage-0), a pending group of this many
#: one-row messages is at most about 43 MB transient before it flushes. The
#: failure ladder's L1 rung (``COALESCE_ROWS = 1024``) trades that headroom
#: for about 5.4 MB transient if 8192 proves insufficient in Phase 0.
COALESCE_ROWS = 8192


class BatchCoalescer:
    """Accumulate small record batches into fewer, larger ones.

    ``add`` appends a batch to a pending group and flushes once the pending
    row count reaches ``coalesce_rows``. Flushing rebuilds the pending group
    as one table via ``combine_chunks()`` (which physically consolidates the
    underlying buffers) and re-splits it back into batches for storage,
    dropping the many small originals. ``to_table()`` performs a final flush
    and assembles every retained batch into one table with the reader's own
    schema (plan P1: ``pa.Table.from_batches``, never ``pa.concat_tables``,
    which raises on zero tables and would take its schema metadata from the
    first table rather than the reader).
    """

    def __init__(self, schema: pa.Schema, coalesce_rows: int = COALESCE_ROWS) -> None:
        self._schema = schema
        self._coalesce_rows = coalesce_rows
        self._pending: list[pa.RecordBatch] = []
        self._pending_rows = 0
        self._done: list[pa.RecordBatch] = []

    def add(self, batch: pa.RecordBatch) -> None:
        self._pending.append(batch)
        self._pending_rows += batch.num_rows
        if self._pending_rows >= self._coalesce_rows:
            self._flush()

    def _flush(self) -> None:
        if not self._pending:
            return
        table = pa.Table.from_batches(self._pending, schema=self._schema).combine_chunks()
        self._done.extend(table.to_batches())
        self._pending = []
        self._pending_rows = 0

    def to_table(self) -> pa.Table:
        self._flush()
        return pa.Table.from_batches(self._done, schema=self._schema)


def read_feather_coalesced(
    fs: fsspec.AbstractFileSystem,
    path: str,
    *,
    coalesce_rows: int = COALESCE_ROWS,
) -> pa.Table | None:
    """Mirror of native ``_read_feather_file``, coalescing batches while reading.

    Matches native fs-existence and exception-scope parity exactly
    (``parquet.py:2792-2800``): returns ``None`` if ``fs.exists(path)`` is
    false, and returns ``None`` on ``pa.ArrowInvalid`` or ``OSError`` raised
    by opening the file, reading its schema, or reading any batch.
    ``KeyboardInterrupt`` and any other exception propagate, exactly as
    native.
    """
    if not fs.exists(path):
        return None

    try:
        with fs.open(path) as f:
            reader = pa.ipc.open_stream(f)
            coalescer = BatchCoalescer(reader.schema, coalesce_rows)
            while True:
                try:
                    batch = reader.read_next_batch()
                except StopIteration:
                    break
                coalescer.add(batch)
            return coalescer.to_table()
    except (pa.ArrowInvalid, OSError):
        return None
