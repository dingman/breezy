# ING-2-RSS plan r2: DELTA over plan_r1.md (BINDING; overrides r1 where they conflict)
Peers (blind): architect REQUEST_CHANGES; python-reviewer MEDIUM (C 8 / I 8 / T 7 / R 6 / S 9 / F 8). Coordinator merge below.

## Verified facts (coordinator, 2026-09-27)
- Nautilus files OrderBookDepth10 under `data/order_book_depths/`. That directory is not `order_book_depth10`, which is where the python-reviewer looked when it reported "not found".
- Production: 815 per-instrument subdirectories and **0** depth-1 (FLAT) parquet files. Every footer checked carries `instrument_id` metadata. quote_tick has 778 per-instrument dirs and 0 FLAT files.
- The native tick-type writers never produce a FLAT file that carries `instrument_id` metadata (architect: parquet.py:2773-2786, :2678; `write_data` always files per instrument). The pinned FLAT hazard is BinaryOption definitions (test_quote_tape_ingest_cli.py:751-781).

## Design change: adopt the architect's (b'') guarded native filtered query, and drop (a)
In `_drop_already_landed_unfiltered` (quote_tape_salvage.py:212-227):
- **Tick types (QuoteTick, TradeTick, OrderBookDepth10)**, when `_parquet_set(<catalog>/data/<type-dir>)` is EMPTY (no FLAT files at the type root):
  - call `write_target.query(data_cls=data_cls, identifiers=sorted(chunk ids), start=lo, end=hi)`;
  - derive the type-dir name from Nautilus's own class-to-dir mapping (find the native helper, e.g. `class_to_filename`). Never hard-code it.
- **Otherwise**, including every non-tick type and any root that has FLAT files: today's unfiltered query, byte-identical.
- Drop from r1: the footer reader, the directory expansion, and the `_KEY_ONLY_TYPES` key-only helpers. They are no longer needed.
- **Read errors propagate.** `ArrowInvalid`, `FileNotFoundError` and any other exception are never turned into an empty key set, because an empty key set means silent duplicates.
- **Observability** (L-30/L-52):
  - Count per data_cls within a run: EXTEND chunks, filtered calls and unfiltered calls.
  - Emit ONE INFO summary line per ingest run through the ingest's existing logger:
    `extend_dedupe: chunks=<n> filtered=<n> unfiltered=<n> by_type=<cls:f/u,...>`
    Counts only; never instrument ids or values.
  - If there were no EXTEND chunks, still emit the line with zeros. That makes "EXTEND never ran" distinguishable from a pass.

## Test changes
- **T-MEM (L-49)** measures ΔRSS via `ru_maxrss` in a FRESH CHILD PROCESS per K (K=1 vs K=20 other instruments), taken over a post-import, post-warm-up baseline. tracemalloc and `pa.total_allocated_bytes` sampling are banned as the pass criterion.
  - Assert ΔRSS(K=20) ≤ 1.5 × ΔRSS(K=1) + a small absolute slack; the slack is a named constant with a stated rationale.
  - Keep the structural spy: the filtered path passes `identifiers` for tick types when the root holds no FLAT files.
  - RED against the base: the unfiltered call scales with K.
- **Fixtures (L-42)** are built only through the real writers: `ParquetDataCatalog.write_data`, and native `convert_stream_to_data` from a real feather where a FLAT file is needed. No hand-rolled `pq.write_table` catalog files.
- **T-EQ.** On a per-instrument-only catalog, the drop set equals the legacy unfiltered oracle across these cases:
  - rows landed / fresh;
  - the same ts_init on a different instrument, which must NOT be dropped;
  - rows exactly at lo and at hi, and 1 ns outside;
  - a chunk spanning 2 instruments.

  Parametrize over QuoteTick and OrderBookDepth10.
- **T-FLAT-GUARD (negative control, L-24/L-33).** With a FLAT file present at a tick-type root (made by the real native writer, from a feather WITHOUT instrument_id metadata), the code takes the unfiltered path and the FLAT row IS dropped.
  - Mutation proof: monkeypatch the guard to always choose filtered, and assert that the FLAT-landed row then leaks (is NOT dropped). This proves the guard is load-bearing.
- **T-ERR.** A read error from `query` propagates. It never comes back as "no rows landed".
- **Regression tests, unchanged and green:**
  - TestTheMixedCatalogLayoutIsPinned;
  - the EXTEND duplicate-drop tests;
  - A8 / ExtendWriteMismatch (`test_a8_*`, `test_per_file_extend_fallback_*`);
  - T4 and the tie-run tests in test_quote_tape_ingest_bounded_read.py.

## Drop-in removal criterion (replaces the unobservable anon ≤2G wording)
- The journal's `memory peak` is cgroup memory.peak, which is anon plus page cache.
- Adopt **memory.peak ≤ 2G on the first post-rotation run whose `extend_dedupe` line shows chunks > 0**, plus elapsed ≤ 600 s and deferred_instances = 0. It is a conservative proxy: it can only over-state anon.
- Only then remove `zz-memory-containment-TEMPORARY.conf` and daemon-reload. Never edit a cap value.
- Residual, recorded rather than fixed: sibling-EXTEND same-key race; A8 plus the disjoint check cover it.

## Scope
- quote_tape_salvage.py (about 15 lines plus a counter);
- quote_tape_ingest_cli.py (the one INFO summary line, plus a docstring note);
- new tests/unit/test_extend_dedupe_filtered.py.
