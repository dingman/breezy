"""T5' (ING-2 S3, byte-residency): white-box ``peak_pending_bytes`` bound for
``BatchCoalescer``.

Why this metric: ``pa.default_memory_pool().bytes_allocated()`` is a proven
dead end for this purpose (Stage-0 F3, "after read") -- it is only sampled
once pyarrow's C++ allocator has already reclaimed transient buffers, so it
never captures a genuine in-flight peak and cannot serve as a residency
guarantee. ``peak_pending_bytes`` is instead plain Python arithmetic: a
running int, updated inside ``BatchCoalescer.add()``, equal to the running
max over every ``add()`` call of ``sum(b.nbytes for b in self._pending)``.
Because it is derived from the batches' own reported sizes rather than any
allocator or OS counter, it is immune to OS page eviction, allocator
bookkeeping lag, and concurrent host memory pressure -- the same failure
mode that forced the chunk-count redesign of
``test_quote_tape_ingest_bounded_rss.py``.
"""

from __future__ import annotations

import pyarrow as pa

from breezy.persistence.feather_read import BatchCoalescer

_SCHEMA = pa.schema([("v", pa.int64())])


def _row_batch(value: int) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays([pa.array([value], type=pa.int64())], schema=_SCHEMA)


_BATCH_NBYTES = _row_batch(0).nbytes

#: Small coalesce group for a fast unit test. Same derivation as
#: feather_read.py's ~43MB budget comment (COALESCE_ROWS x per-message
#: bytes), scaled down to this fixture's own tiny per-message size instead
#: of the production ~5.3KB.
_TEST_COALESCE_ROWS = 500
_SLACK = 1.25
_PEAK_BUDGET_BYTES = int(_TEST_COALESCE_ROWS * _BATCH_NBYTES * _SLACK)


def _feed(coalescer: BatchCoalescer, n_rows: int) -> None:
    for i in range(n_rows):
        coalescer.add(_row_batch(i))


def test_peak_pending_bytes_stays_within_one_coalesce_groups_budget() -> None:
    coalescer = BatchCoalescer(_SCHEMA, coalesce_rows=_TEST_COALESCE_ROWS)
    _feed(coalescer, _TEST_COALESCE_ROWS * 3 + 17)
    coalescer.to_table()

    assert coalescer.peak_pending_bytes <= _PEAK_BUDGET_BYTES, (
        f"peak_pending_bytes ({coalescer.peak_pending_bytes}) exceeded the "
        f"one-group budget ({_PEAK_BUDGET_BYTES}) derived from "
        f"COALESCE_ROWS x per-message bytes x {_SLACK} slack -- pending "
        f"batches are not being bounded to a single coalesce group"
    )


def test_peak_pending_bytes_is_far_below_a_single_shot_table() -> None:
    n_rows = _TEST_COALESCE_ROWS * 4
    coalescer = BatchCoalescer(_SCHEMA, coalesce_rows=_TEST_COALESCE_ROWS)
    batches = [_row_batch(i) for i in range(n_rows)]
    for batch in batches:
        coalescer.add(batch)
    coalescer.to_table()

    # Control: a single-shot accumulation retaining every batch uncoalesced,
    # as one chunked table -- mirrors native `_read_feather_file`, which
    # calls `read_all()` and never combines chunks.
    control_table = pa.Table.from_batches(batches, schema=_SCHEMA)

    assert coalescer.peak_pending_bytes < control_table.nbytes / 2, (
        f"peak_pending_bytes ({coalescer.peak_pending_bytes}) is not far "
        f"below the uncoalesced control table's nbytes "
        f"({control_table.nbytes}) -- residency is not actually bounded"
    )


class _NeverClearsPendingCoalescer(BatchCoalescer):
    """Mutation: ``_flush`` combines and records the group, but forgets to
    reset ``_pending``/``_pending_bytes`` -- every later group accumulates on
    top of the last, so pending residency grows without bound instead of
    capping at one coalesce group.
    """

    def _flush(self) -> None:
        if not self._pending:
            return
        table = pa.Table.from_batches(self._pending, schema=self._schema).combine_chunks()
        self._done.extend(table.to_batches())
        self._pending_rows = 0
        # BUG (intentional, for the mutation test below): self._pending and
        # self._pending_bytes are never reset.


def test_mutation_retaining_flushed_batches_would_fail_the_budget_bound() -> None:
    """Proves the budget assertion above has teeth: a coalescer that forgets
    to clear ``_pending`` on flush blows the same one-group budget that
    ``test_peak_pending_bytes_stays_within_one_coalesce_groups_budget``
    enforces, confirming that regression would be caught.
    """
    mutant = _NeverClearsPendingCoalescer(_SCHEMA, coalesce_rows=_TEST_COALESCE_ROWS)
    _feed(mutant, _TEST_COALESCE_ROWS * 3 + 17)
    mutant.to_table()

    assert mutant.peak_pending_bytes > _PEAK_BUDGET_BYTES, (
        f"expected the never-clears-pending mutant to exceed the one-group "
        f"budget ({_PEAK_BUDGET_BYTES}) by accumulating across flushes, but "
        f"peak_pending_bytes was only {mutant.peak_pending_bytes} -- this "
        f"mutation no longer demonstrates that the real bound has teeth"
    )
