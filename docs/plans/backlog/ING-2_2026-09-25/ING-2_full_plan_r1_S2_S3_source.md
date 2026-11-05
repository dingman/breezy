# ING-2 durable plan r1 — bounded-memory quote-tape ingest, instruments first

## Findings (planner, read-only)
F1 [HIGH] DEFAULT_DATA_TYPES (node_config.py:280) lists BinaryOption LAST; ingest_instance (quote_tape_ingest_cli.py:855) converts in list order; used for every dead untruncated instance (run_ingest :1273,:1302). Kill mid-OrderBookDepth10 → zero instruments for that instance; instances sequential → all later instances too. Only _ingest_instance_per_file (:1155) orders definitions first.
F2 [HIGH] Fast path writes the per-(instance,type) marker only after the full type (:872). Nautilus convert_stream_to_data (parquet.py:2638-2654) read_all()s each feather file BEFORE the exists check (:2683) → a killed run re-reads everything → "17 runs, zero progress" (L-49).
F3 [MED, suspected dominant] ING-1 EXTEND path materialises whole-file object lists (_extend_overlapping_stream :633; per-file fallback :1071); write_fresh_capture_rows → _drop_already_landed_unfiltered (quote_tape_salvage.py:156) loads ALL already-landed rows of the type across the file's [lo,hi].
F4 [MED] Cross-file retention (pyarrow pool / allocator) unmeasured; "5G on a larger backlog" comment suggests growth with backlog.
Native bounded path: conversion is per-file natively but no chunked read/deadline/row budget. Only native + pyarrow APIs used below.
(L-38 is stop-rule counters, not interval collision; ING-1 collision logic protected by regression tests.)

## Acceptance criteria
AC1 peak RSS independent of backlog size: child-process ingest N=4 vs N=16 equal files, peak(16) ≤ peak(4)+64MiB; pa.total_allocated_bytes() ≤ baseline+16MiB after run.
AC2 EXTEND holds one chunk: no call to _handle_table_nautilus / write_fresh_capture_rows receives > EXTEND_CHUNK_ROWS; dedupe window = chunk [lo,hi].
AC3 definitions of every eligible instance converted before ANY tick type in the run (both paths).
AC4 convert_fn raising KeyboardInterrupt on first tick type → catalog.instruments() already returns BinaryOptions; .converted-binary_option marker exists.
AC5 run_ingest(deadline_ns=…) starts no new (instance,type) unit after deadline → results 'deferred-deadline', exit 0; next run converts deferred units without duplicate rows.
AC6 ING-1 non-regression: all non-disjoint/EXTEND tests + TestTheMixedCatalogLayoutIsPinned green unchanged; chunked EXTEND lands identical row set.
AC7 unit: default deadline ≤ TimeoutStartSec−300; MemoryHigh < MemoryMax; contract test pins both.

## Edge cases
non-disjoint (skip_disjoint_check=True only with dedupe, as today; native stays one parquet per feather); idempotent rerun via markers / exists-skip / EXTEND dedupe; crash mid-chunk (T8b); kill during native pq.write_table leaves truncated parquet (existing risk R4, not fixed); open definitions file in live instance stays skipped-open; deadline in definitions phase — ≥1 unit always runs; empty backlog unchanged.

## Trade-offs
A raise MemoryHigh only — rejected as sole fix (L-29), kept as sizing. B instruments-first + deadline + chunked EXTEND + release pyarrow pool per file — CHOSEN. C subprocess per instance — fallback if Stage 0 shows unreleasable retention (breaks convert_fn injection, 47 callers). D batch-chunked native writes — reserve if one daily file > budget. E SIZE rotation — rejected (recorder test pin).

## Files
Stage 0 (measure, read-only vs prod): largest live/ instance converted into a scratch catalog under /usr/bin/time -v; peak RSS single-file vs all; largest feather size; pyarrow version (MemoryPool.release_unused).
1. src/breezy/runtime/quote_tape_ingest_cli.py: `_definitions_first(data_types)` stable partition via _is_instrument_definition, used in ingest_instance and _ingest_instance_per_file (replaces :1155-1156). run_ingest two-phase (defs for all eligible instances, then ticks), liveness/open-file/preflight cached per instance in frozen `_InstancePlan`. `deadline_ns: int|None=None` + injectable clock (monotonic_ns); ≥1 unit; outcome "deferred" not a failure. CLI --deadline-seconds (DEFAULT_DEADLINE_SECONDS=1500); print "backlog deferred: <n> unit(s)" (count only). `_release_arrow_pool()` after each unit/file. New `_extend_table_chunked(catalog, write_target, data_cls, table) -> tuple[int,bool]` iterating table.to_batches(max_chunksize=EXTEND_CHUNK_ROWS=50_000 provisional) used by _extend_overlapping_stream and per-file EXTEND (:1071-1072). Docstring.
2. quote_tape_salvage.py: no change (window bounded by objects passed).
3. deploy/systemd/breezy-quote-tape-ingest.service: ExecStart += --deadline-seconds 1500; MemoryHigh=max(4G,1.5×Stage0 peak) cap 6G, MemoryMax=High+2G (provisional 5G/7G); TimeoutStartSec=1800 stays.
4. LESSONS.md L-49 How-to-apply amended (lessons skill).

## Tests (new tests/unit/test_quote_tape_ingest_bounded_memory.py)
T1 test_fast_path_converts_definitions_before_any_tick_type (RED); T2 test_definitions_for_every_instance_precede_any_tick_conversion (RED); T3 test_kill_during_tick_conversion_leaves_instruments_resolvable (RED); T4 test_extend_never_holds_more_than_one_chunk (RED); T5 test_peak_rss_is_independent_of_backlog_file_count + test_arrow_pool_retention_is_bounded_after_run (slow, subprocess; RED unknown until Stage 0 — record honestly); T6 test_deadline_defers_remaining_units_and_exits_ok + test_deferred_units_convert_on_next_run_without_duplicates (RED); T7 test_deadline_always_runs_at_least_one_unit; T8a test_chunked_extend_lands_same_row_set_as_unchunked; T8b test_crash_after_chunk_k_rerun_lands_exact_row_set; T9 unit contract test_ingest_deadline_below_timeout_start_sec, test_ingest_memory_high_below_memory_max. Existing outcome assertions gain one reviewed value "deferred".

## Risks
R1 single file > budget → option D slice. R2 release_unused absent/ineffective → option C. R3 silent long-lived deferral → count line now; follow-up streak alert via OnFailure after K deferred runs. R4 truncated parquet never repaired (existing). R5 outcome token greps in scripts/deploy. R6 two-phase restructure drift (47 callers) → pure reordering + full gate. Deploy (copy unit + daemon-reload) is coordinator step.
Confidence MEDIUM (HIGH on F1/F2 ordering; F3 vs F4 mechanism pending Stage 0). Unknowns: U1 largest file peak; U2 list_instance_ids ordering stable; U3 open live defs file delays same-day instruments.
