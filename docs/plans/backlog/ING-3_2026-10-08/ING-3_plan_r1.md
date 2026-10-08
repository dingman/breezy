# ING-3 plan r1: bound the first post-rotation ingest, prove it, remove the TEMPORARY drop-in (2026-10-08)

**Status:** r1. Author: planner. Awaiting peer review: architect, python-reviewer, and a Nautilus-native reviewer.

**Origin.** The ING-2-AMEND2 live proof (9730f1e) is met only in its letter, and fails in intent. From 09-30 to 10-08, the FIRST post-rotation run of `breezy-quote-tape-ingest.service` failed every day:
- elapsed 606–705 s, against a limit of 600;
- `deferred_instances` 1–63, against a limit of 0;
- cgroup `memory.peak` 4.3–9.8G, against a limit of 2G.

The second run passes on some days (10-01: 149 s, 1.8G; 10-05: 141 s, 1.9G) and not on others (3.4–4.7G). No-op quarter-hourly runs grew from 349M/14 s to 2.1G/33 s on 10-08. The drop-in `zz-memory-containment-TEMPORARY.conf` (12G/14G) masks all of this; the unit's own limits are 4G/6G.

## Code facts (HEAD bd32de69)
- **F-a.** `_open_files_for_instance` treats only the newest file per type as open. Intact files without EOS in a live instance are `skipped-unclosed` (`_convert_one_tick_type_per_file`). Rotation marks the instance dead (`instance_is_dead`), and every such file becomes convertible at once.
- **F-b.** `run_ingest` sends a dead, non-truncated instance down the whole-instance path: `ingest_instance` → `default_convert` → `_convert_stream_natively`.
  - That path checks only the per-type marker, so it re-reads every feather file of the type, including files already converted per file during the day. `_instance_has_pending_work` admits that nothing promotes a fully per-file-converted type.
  - One interval collision sends the whole type to `_extend_overlapping_stream`, which re-reads everything and dedupes in 50K-row chunks. 10-01's `custom_depth_truncation:110` works out to about 5.5M rows.
- **F-c.** `_instance_is_fully_converted` does not skip marker dotfiles, while `_instance_has_pending_work` does. The result is a rescan on every run.
- **F-d.** `_salvage_one_file` is unbounded. It runs `salvage_feather_file(collect=True)`, then `list(_handle_table_nautilus(whole table))`, then one whole-file dedupe query. It does not use `_extend_table_chunked`.
- **F-e.** The deadline is checked once per type, so a run can overrun by a whole type. After expiry, the loop-top `can_admit()` defers every remaining instance, even ones with no pending work.
- **F-f.** `convert_instrument_definitions` runs an unfiltered all-time `query(data_cls)` plus a whole-instance read.
- **F-g.** cgroup v2 charges page cache to the unit, so `memory.peak` grows with the bytes the run touches.

## Hypotheses (ranked)
| ID | Hypothesis | Evidence needed |
|---|---|---|
| H1 | Held-back work lands at rotation | File counts and bytes by state (EOS / intact-no-EOS / truncated); `skipped-unclosed` counts across the day |
| H2 | Whole-instance path re-reads and re-extends per-file-converted files | Path taken; native "already exists" prints; EXTEND chunks per type; bytes read vs unconverted |
| H3 | Salvage builds whole files | Preflight truncated count; salvage lines; salvage-only anon peak |
| H4 | `memory.peak` is mostly page cache; growing live files force cold memo rescans | `memory.stat` anon vs file; the same run at MemoryMax=2G has similar wall time |
| H5 | Deadline granularity is too coarse | Per-unit durations; deferred split into pending vs not-pending |
| H6 | Definitions all-time query | Time and anon memory of that call alone; definition row count |

## Stage 0: measure first (offline, read-only, no repo change)
- **S0.1 Snapshot.** Write it under `~/.cache/breezy-ing3-s0/<date>/`, on the same filesystem as the catalog (`stat -f`).
  - At T1 (after the last pre-rotation frequent run exits, before the rotation): copy the live instance's markers, attempt files and memo files, and `cp -al` the `data/` tree (write-once parquet).
  - After rotation: `cp -al` the rotation instance's feather tree and the new instance's directory.
  - Record link counts, sizes and the T1→rotation fidelity gap.
- **S0.2 Driver.** A scratchpad driver runs `run_ingest(snapshot_root, now_ns=<first-run time>, service_active_probe=lambda: False, deadline=RunDeadline(600))`. Variant B uses the second-run time; variant C uses `deadline=None`. It records per-unit timing, `extend_dedupe_counters.summary_line()`, and the native "already exists" count.
- **S0.3 Census.**
  - files and bytes per type, state and layout;
  - whether DepthTruncation feather files carry `instrument_id` metadata;
  - flat files at each type root;
  - definition row counts.
- **S0.4 Runs.** Every run uses `systemd-run --user --wait --collect -p MemoryMax=<X> -p MemoryHigh=<X-10%> -p LimitNOFILE=524288 --nice=10`, with a 1 s sidecar logging cgroup `memory.peak` and `memory.stat` (anon/file/file_dirty). Never use RSS. Restore markers and hardlinks before each run.
  - **A1:** 14G, variant A. Reproduces the failure.
  - **A2:** 2G, variant A. Tests H4.
  - **A3:** isolations: (i) skipped-unclosed files only; (ii) forced whole-instance path; (iii) salvage only; (iv) definitions only.
  - **A4:** a no-op run on a live-instance copy (H4 memo cold scans).
- **S0.5 Window.**
  - Never during 16:30–17:10Z or 08:45–09:30Z.
  - Never concurrent with a nightly study, replay, scorer, AUD-07 or other heavy job.
  - Start right after a production frequent run exits.
  - Never touch the node, supervisor or recorder.
- **S0.6 Exit.** Write `docs/plans/backlog/ING-3_2026-10-08/STAGE0_findings.md`. Phase 1 builds only fixes whose hypothesis carries ≥15% of anon peak or wall time.
  - **STOP:** if the unavoidable native table-only conversion (A3-i at 2G) needs more than ~450 s, the 600 s / deferred=0 acceptance cannot be met by scheduling. That goes to the peer-review loop, not to the operator.

## Nautilus gap proof (before any build)
- **Native already covers:**
  - table-only per-file conversion (`_convert_feather_table_to_parquet`);
  - `convert_stream_to_data(identifiers=)`;
  - `write_data(skip_disjoint_check)`;
  - `query(identifiers, start, end)`.
- **Native lacks:**
  - per-file idempotency or resume markers;
  - EOS or liveness awareness;
  - batch-streamed single-feather reads (`_read_feather_file` uses `read_all`; Breezy mirrors it with `read_feather_coalesced`);
  - row-level dedupe extend.
- The reviewer confirms this against `.venv/.../nautilus_trader/persistence/catalog/parquet.py` (~2604–2800), and checks whether native query or DataFusion can stream batches for dedupe.
- **Rule:** route more work through the native table-only path, and less through object-building paths.

## Phase 1: minimal fix (each item gated by Stage 0; each can merge on its own)
- **P1 (H2; F-b, F-c).** `quote_tape_ingest_core.py`:
  - (a) Instances that carry per-file markers always take `_ingest_instance_per_file`.
  - (b) Promote a per-type marker when every file of a dead instance's type is per-file-marked or salvage-marked.
  - (c) `_instance_is_fully_converted` skips dotfiles.
- **P2 (H5).** Peek `deadline.can_admit()` before every file after the first, so an overrun is at most one file. Loop-top deferral counts only instances where `_instance_has_pending_work` is true.
- **P3 (H3).** `quote_tape_salvage.py` routes `_salvage_one_file` through `_extend_table_chunked`, with a parity test on transforms (`convert_bar_type_to_external`).
- **P4 (H6).** Bound the definitions dedupe query to the streamed min/max `ts_init`. The dedupe key includes `ts_init`, so the result is unchanged. It stays unfiltered by identifier (mixed layout pin).
- **P5 (H4, only if A2 shows page cache dominates).**
  - `preflight_memo.py` classifies live, non-open, no-EOS files from `_read_tail`, without a full decode.
  - Dead instances are still fully scanned.
  - Optionally add `posix_fadvise(DONTNEED)` in `feather_read.py`.
- **Module size.** `quote_tape_ingest_core.py` is ~1,850 lines, so new helpers go in `src/breezy/runtime/quote_tape_ingest_promotion.py`. `lint-imports` must stay green; adapters never import `breezy.runtime`.

## RED tests
- **New `tests/unit/test_quote_tape_ingest_rotation_burst.py`:**
  - `test_dead_instance_with_per_file_markers_takes_the_per_file_path`
  - `test_whole_instance_path_never_rereads_a_per_file_marked_feather`
  - `test_fully_per_file_converted_type_in_dead_instance_is_promoted_to_type_marker`
  - `test_promotion_never_fires_while_a_file_is_open_or_unclosed_in_a_live_instance`
  - `test_instance_is_fully_converted_ignores_marker_dotfiles`
  - `test_noop_run_after_promotion_never_calls_scan_instance_memoized`
- **Extend `tests/unit/test_quote_tape_ingest_deadline.py`:**
  - `test_per_file_loop_rechecks_deadline_before_every_file`
  - `test_overrun_is_bounded_by_one_file_not_one_type`
  - `test_loop_top_deferral_skips_instances_with_no_pending_work`
- **New `tests/unit/test_quote_tape_salvage_chunked.py`:**
  - `test_salvage_never_materialises_more_than_extend_chunk_rows_plus_run`
  - `test_chunked_salvage_lands_same_rows_as_unchunked`
  - `test_salvage_dedupe_window_is_per_chunk`
- **Extend `tests/unit/test_quote_tape_ingest_definitions_first.py`:** `test_definition_dedupe_query_bounded_to_streamed_ts_window`
- **P5 only, `tests/unit/test_preflight_memo.py`:**
  - `test_live_unclosed_file_classified_from_tail_without_full_decode`
  - `test_dead_instance_file_still_full_scanned`
- **Bounded-memory test:** `test_rotation_burst_fixture_peak_under_budget`, a child process measuring pyarrow pool and tracemalloc peaks.
- **Unweakened guards:**
  - `tests/contract/test_quote_tape_truncation_preflight.py`
  - `test_quote_tape_ingest_unit_contract.py`
  - `TestTheMixedCatalogLayoutIsPinned`
  - the import, exec-pin and firewall guards

  All of these go in every focused gate.

## Sequencing
- Stage 0 can run now; it is offline.
- Phase 1 waits for DEFER-STREAK-LOAD to merge, because it touches the same files. After that merge, fast-forward the worktree.
- P2 needs a joint check that the stall alert (exit 4) still fires only on real pending work.
- Merge order is P1 → P2 → P3 → P4 (→ P5), with a full gate after each. The timer picks up new code on its next fire.

## Acceptance
- **Daily proof.** For 3 consecutive days, the FIRST post-rotation run shows:
  - every `extend_dedupe` chunk filtered (`<n>/0`) with `flat_root=none`, or no EXTEND at all;
  - `deferred_instances=0`;
  - elapsed ≤600 s;
  - cgroup `memory.peak` ≤2G;
  - exit 0.
- These runs are measured with the drop-in still present.
- **Secondary:** no-op runs stay ≤500M and ≤20 s.
- **Then:** remove the TEMPORARY drop-in, run `daemon-reload`, and confirm one first-post-rotation run under the unit's own limits.
- **AMEND2 proof wording:** the "or no EXTEND" amendment is a peer-review ruling.

## Risks
| Risk | Mitigation |
|---|---|
| Snapshot fidelity gap | Record its size |
| Premature type-marker promotion | Promote only for dead instances where every file is terminal-marked (tested) |
| Chunked salvage changes transforms | Parity test |
| Stage 0 disk use | Clean up `~/.cache` after findings |

## Reviewers required
- architect (plan);
- python-reviewer (stack);
- a Nautilus-native reviewer, seeded with nautilus-trader-patterns, to sign off the gap proof.

security-reviewer is not required unless the I/O surface grows (e.g. fadvise in P5).
