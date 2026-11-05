# PLAN — ING-2-AMEND2 (r1)

Author: Claude performance-optimizer (read-only). The Codex r1 output was only a preamble, and the Codex re-run hit a credit-exhausted empty completion. Saved by the coordinator.

## 1. Verified problem
The 09-28 09:45Z run of `breezy-quote-tape-ingest.service` logged:
```
deadline budget=600s elapsed=610s deferred_units=0 deferred_instances=45 instances=65 rss_peak_mb=2593
extend_dedupe: chunks=324 filtered=224 unfiltered=100 by_type=custom_depth_truncation:0/100,order_book_depths:129/0,quote_tick:95/0
Consumed 10min 31.626s CPU over 10min 13.152s wall, 6G memory peak
```

`custom_depth_truncation` was 100% unfiltered. Every chunk ran the full-catalog cross-instrument `write_target.query(data_cls=DepthTruncation, start=lo, end=hi)` (`quote_tape_salvage.py:311`).

`DepthTruncation` (`tape_records.py:450`) is a pyarrow-path custom type. `filter_files` derives the identifier from `file_path.split("/")[-2]` for every class (`nautilus parquet.py:2250`).

Measured live: `data/custom_depth_truncation/` has 839 per-instrument subdirectories and 0 depth-1 files. That is the same layout ING-2-RSS proved for `order_book_depths` (815/0) and `quote_tick` (778/0).

The overrun past 600 s is a consequence: the deadline is checked only between instances (`ingest_cli.py:1295-1299`).

## 2. L-1 verdict
The gap is real, and Nautilus has no native bound. Breezy already owns the guarded filtered dispatch (`quote_tape_salvage.py:212-314`), including the `_type_root_has_flat_files` fail-safe. It is simply scoped to `_TICK_TYPES`.

## 3. Design
Rename `_TICK_TYPES` → `_ID_FILTERABLE_TYPES` and set it to `frozenset({QuoteTick, TradeTick, OrderBookDepth10, DepthTruncation})`. Update the docstring and comments at `:212-218` and `:287-297`, and the reference at `:304`. Add the import of `DepthTruncation`.

No change to chunking, `EXTEND_CHUNK_ROWS`, the deadline, or any operator-reserved value.

## 4. Files
`src/breezy/runtime/quote_tape_salvage.py`, plus tests.

## 5. RED tests
Tests 1–3 are in `tests/unit/test_extend_dedupe_filtered.py`; test 4 is in `test_quote_tape_ingest_cli.py`.

1. Extend the parametrize at `:101` with `DepthTruncation`. The filtered drop set must equal the unfiltered oracle, AND a spy asserts `query` is called with `identifiers=`.
2. Extend the flat-file fail-safe parametrizes at `:189` and `:215` with `DepthTruncation`.
3. `test_filtered_extend_dedupe_rss_does_not_scale_with_other_instruments_depth_truncation` (`@pytest.mark.memory`): ΔRSS(K=20)/ΔRSS(K=1) ≤ 1.5 + slack.
4. `extend_dedupe:` `by_type` shows `custom_depth_truncation:<n>/0` after an EXTEND run seeded with `DepthTruncation` rows sharing a window with other instruments.

## 6. Acceptance
1. The RED tests go GREEN.
2. The existing mixed-layout, T4 and tie-run tests stay green unchanged.
3. The full gate and `lint-imports` are green.
4. The next post-rotation run with `chunks>0` shows `custom_depth_truncation:<f>/0`, deferred_instances=0, elapsed ≤600 s and cgroup peak ≤2G. Only then does the TEMPORARY drop-in come off.

## 7. Risks
Scope is one dispatch set inside a private function (EXTEND dedupe and salvage). A future flat `DepthTruncation` file is backstopped by the existing runtime check. No safety test is touched.

## 8. Rollout
The fix loads at the next oneshot ingest run (15-minute timer). No node impact.

## 9. Open questions
1. Is the criterion reachable? Yes, per the quiet-run evidence (7–18 s, 150 MB–1.2 GB). Measure before any change to the criterion.
2. Should other custom types be widened? No: there is no measured unfiltered chunk for them (YAGNI).
3. Rename? Yes: 3 in-file references, and the old name is now wrong.
