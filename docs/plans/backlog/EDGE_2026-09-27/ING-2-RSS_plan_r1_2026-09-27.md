# Plan: ING-2-RSS, a key-only EXTEND dedupe that still sees FLAT files

## Diagnosis: confirmed, with one sharpening

- **Unfiltered and deliberate.** `write_fresh_capture_rows` calls `_drop_already_landed_unfiltered` for every chunk (quote_tape_salvage.py:343). That function queries `write_target.query(data_cls, start=lo, end=hi)` with no identifiers (quote_tape_salvage.py:223-226). The comment explaining why is at :216-219.
- **Once per chunk.** It runs for every 50k-row chunk: quote_tape_ingest_cli.py:381, :958-968. The two EXTEND entry points are :1014 and :1596.
- **FLAT files are why a filtered query is wrong.** `filter_files` takes the identifier from `path.split("/")[-2]` (parquet.py:2249-2257). For a FLAT file that segment is the type directory, so an identifier-filtered query drops it. `TestTheMixedCatalogLayoutIsPinned` pins this (test_quote_tape_ingest_cli.py:751-781). Passing `identifiers=` would reintroduce duplicates. Confirmed.
- **Full deserialization.** OrderBookDepth10 goes through the Rust path (parquet.py:1698-1720). That path registers the whole directory of every matching file (:1901-1914), then builds a full Python list of Data objects (:1774-1786). Nothing in it selects only certain columns.
- **Sharpening: where instrument_id lives.** For OrderBookDepth10, QuoteTick and TradeTick, `instrument_id` is not a column and not the path. It is the parquet schema metadata key: the v2 wrangler reads it in `from_schema` (wranglers_v2.py:64-69, used at serializer.py:349). Native conversion places the file by that metadata key (parquet.py:2674-2678, :2777-2778). So a key-only reader gets `instrument_id` from each file's footer, and that works the same for FLAT and per-instrument files.
- **Why memory and time blow up (inference, not measured).** Feather files are per instrument. One chunk's [lo,hi] therefore pulls the landed rows of all 60 instruments in that window, each object carrying 20 BookOrders. That is about 60× the chunk in objects, which fits 7.4G. Across a whole file it adds up to about 60× the total rows deserialized, which fits 773 s. Confirm this with the RED memory test below.
- **Nautilus has no native key-only read, so the gap is real.**
  - `query(where=…)` filters rows but still deserializes them (:1648-1746).
  - `backend_session` produces full objects (:1795-1916).
  - `query_first_timestamp` / `query_last_timestamp` / `get_intervals` return filename intervals only (:2314-2342).
  - The public building blocks do exist: `get_file_list_from_data_cls` (:2286-2312) and `filter_files` (:2205-2284).

## Options considered

| Opt | Idea | For | Against | Verdict |
|---|---|---|---|---|
| (a) key-only | List files with public `get_file_list_from_data_cls` + `filter_files(identifiers=None, lo, hi)`, which include FLAT files by construction. Read footer metadata for `instrument_id` and skip files whose id is not in the chunk. Read only the `ts_init` column, filtered to [lo,hi] | No Data objects are built. Memory is about 8 B per row of this chunk's own instruments only. Uses no private Nautilus API. Small | Must match the Rust path's directory-scope and inclusive-bound behaviour exactly (pinned by the equivalence test) | **PICK** |
| (b) filtered ∪ FLAT-only unfiltered | Split the query | Keeps native deserialization | Still builds full objects for the chunk's own instrument (about 1×). Needs a FLAT-only file list, which is the same enumeration as (a) anyway. Two paths to keep in sync | Reject |
| (c) hoist key set | One key set per file or type | Fewer calls | Changes the chunk-local dedupe that T4 (bounded_read.py:582-612) and the tie-run proof (ingest_cli.py:919-929) rely on. Memory becomes the whole type's keys. The gain is small once (a) is in | Reject (YAGNI) |

## Design for (a) (quote_tape_salvage.py only)

1. Add `_KEY_ONLY_TYPES = frozenset({QuoteTick, TradeTick, OrderBookDepth10})`. These are the metadata-keyed Rust types whose `_object_key` is `(instrument_id.value, ts_init)` (:189-191).
   - Every other type keeps today's query exactly, including InstrumentStatus, custom types and definitions. So T4 and the tie-run spy tests (bounded_read.py:582-612, :784-797), which use InstrumentStatus, keep passing without edits.
2. Add `_landed_keys_key_only(write_target, data_cls, ids, lo, hi) -> set | None`:
   - `files = write_target.filter_files(data_cls, write_target.get_file_list_from_data_cls(data_cls), None, lo, hi)`.
   - To match the directory registration at parquet.py:1903-1914, expand to `⋃ _parquet_set(dirname(f))` (reuses :272-286).
   - For each file, read `pq.ParquetFile(f, filesystem=fs).schema_arrow.metadata[b"instrument_id"]`, a footer-only read. Skip the file if that id is not in `ids`.
   - Otherwise run `pq.read_table(f, columns=["ts_init"], filters=[ts_init >= lo, ts_init <= hi])` and add `(id, ts)` to the key set. The bounds are inclusive, as at :2152-2156.
   - Fail closed: if any in-window file has no `instrument_id` metadata, return `None`. The caller then uses the legacy query, which is behaviour-identical, and never skips the file.
3. Split `_drop_already_landed_unfiltered` (:212-227):
   - Extract today's body into `_landed_keys_by_query`, with no behaviour change.
   - Dispatch: if `data_cls in _KEY_ONLY_TYPES`, try key-only first; if it returns `None`, fall back to the query.
   - Update the docstring to say why FLAT files stay visible: the enumeration never passes identifiers, and footer ids are matched against the chunk's ids.
4. Leave these untouched: the warning text (:346-352), the A8 detector (:289-325), `ExtendWriteMismatch`, `_drop_already_landed` (:198-209, the salvage path) and `EXTEND_CHUNK_ROWS`.

## Acceptance tests (write first, confirm RED, then GREEN)

New file: tests/unit/test_extend_dedupe_key_only.py. Build a synthetic OrderBookDepth10 catalog in tmp_path:
- Per-instrument dirs written with `write_data`.
- One FLAT file: `pq.write_table` of a depth table carrying `instrument_id` metadata, written at `data/order_book_depth10/<ts>_<ts>.parquet`. This is the layout from parquet.py:2678-2681.

The tests:
- **T-MEM (RED today).** Target instrument A with a fixed 2k landed rows. Run `_drop_already_landed_unfiltered` on a 2k-row A chunk under `tracemalloc` together with `pa.total_allocated_bytes()` sampling.
  - Compare peak with K=1 against K=20 other instruments (each 2k rows in the same window).
  - Pass condition: `peak(K=20) / peak(K=1) < 1.5`.
  - Also spy that `ParquetDataCatalog.query` and `_handle_table_nautilus` are not called for depth. That catches a regression structurally even if the memory numbers are noisy.
  - Do not use ru_maxrss: it only rises within a process, so it is useless inside pytest.
- **T-EQ (must be GREEN before and after).** On the mixed layout, compare the new drop set with the oracle `_landed_keys_by_query`. The cases:
  - rows landed only in FLAT
  - rows landed only per-instrument
  - rows landed in both
  - fresh rows
  - a same-`ts_init` row on a different instrument, which must NOT be dropped
  - rows exactly at lo and at hi
  - a row one ns outside [lo,hi]
  - a chunk spanning 2 instruments

  Parametrize over QuoteTick and OrderBookDepth10.
- **T-NEG (negative control).** Monkeypatch the enumeration to leave out depth-1 files under the type root. Assert that the FLAT-only row is then NOT dropped, which proves T-EQ would notice FLAT files being skipped. A companion assertion checks the unpatched run does drop it.
- **T-FALLBACK.** A FLAT file with no `instrument_id` metadata sends the call to `_landed_keys_by_query`, checked by spy.
- **Regression gate.** These must pass unchanged:
  - `TestTheMixedCatalogLayoutIsPinned`
  - the EXTEND duplicate-drop tests
  - the A8 tests (`test_a8_*`, `test_per_file_extend_fallback_*`)
  - T4 and the tie-run tests in tests/unit/test_quote_tape_ingest_bounded_read.py

  Run the full gate with `scripts/ci/run_tests_no_egress.sh` and `lint-imports`.

## Deadline and drop-in

- **Deadline.** `deadline.admit` only gates starting a type (ingest_cli.py:1295-1299) and the lazy first-file start (:1541-1545). This fix makes each chunk cost scale with the chunk's own instrument, so wall time should fall well under 600 s without touching the gate. Stopping a conversion mid-way when it overruns is out of scope: it would need a partial-type marker design.
- **Drop-in removal criterion (ING-2-AMEND).** Remove the containment drop-in only after the next post-rotation run meets all three: anon peak ≤2G, CPU/wall ≥0.8, and `memory.events` high <1/s. Until then it stays. No memory cap value is edited in any step.

## Files

- src/breezy/runtime/quote_tape_salvage.py:189-227 — the dispatch and the two key-set helpers (about 45 lines). Also update the module docstring at :39-53 to note the key-only EXTEND path. The file stays under 800 lines.
- src/breezy/runtime/quote_tape_ingest_cli.py:919-940 — docstring only: the dedupe is now key-only for tick types. No logic change.
- tests/unit/test_extend_dedupe_key_only.py — new: T-MEM, T-EQ, T-NEG, T-FALLBACK.
- docs/core/PROGRESS.md — update the ING-2-RSS row with the fix and the drop-in criterion.

## Risks

| Risk | Sev | Mitigation |
|---|---|---|
| DataFusion directory scan may recurse or differ from the depth-1 `_parquet_set` expansion (parquet.py:1903-1914) | M | T-EQ uses a mixed layout with a FLAT root plus subdirs. If they differ, widen to a recursive listing (the result is a set, so over-reading is safe) |
| A future Nautilus moves `instrument_id` out of metadata | M | Fail-closed fallback (T-FALLBACK). The equivalence test fires the day the wrangler changes (wranglers_v2.py:64) |
| Metadata string does not match `InstrumentId.value` (urisafe encoding) | L | T-EQ compares keys against the native-deserialized oracle. `_make_path` does its own encoding only for paths (quote_tape_salvage.py:256-258) |
| Unsorted or odd filename intervals | L | Directory expansion reads every file in each matched directory, with the row filter applied |
| Concurrent agents mutate the tree and fake a failure | L | Use a per-agent scratchpad and PYTHONPATH in the worktree |

## Confidence

- **High (about 85%)** on the diagnosis. The code path and the `instrument_id` metadata finding are verified at the lines cited.
- **About 75%** that (a) alone meets anon ≤2G. The memory model is inferred and still has to be confirmed by T-MEM on the next post-rotation run.
- One thing is unverified: I could not check on disk whether the production depth catalog contains any FLAT files. The 60 per-instrument subdirs suggest there are none, but the design does not depend on the answer.