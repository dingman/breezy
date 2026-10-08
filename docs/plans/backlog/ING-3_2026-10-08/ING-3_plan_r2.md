# ING-3 plan r2: bound the whole post-rotation ingest window, prove it, remove the TEMPORARY drop-in (2026-10-08)

**Status:** r2. It applies all three r1 reviews (architect, python-reviewer, Nautilus-native; each SOUND-WITH-CHANGES) and the coordinator rulings CR-1..CR-4. It awaits a convergence review.

**Tags:** A# = architect, P# = python-reviewer, N# = Nautilus-native, P-n# = python RED-test notes, CR# = coordinator ruling. r1's fix packages P1–P5 are renamed **W1–W5**.

**Line numbers** were re-verified on HEAD d53f655f, whose code equals bd32de69.

## Origin
The ING-2-AMEND2 proof (9730f1e) is met in letter, not in intent. From 09-30 to 10-08, the first post-rotation run failed every day:
- elapsed 606–705 s;
- `deferred_instances` 1–63;
- `memory.peak` 4.3–9.8G.

No-op runs grew from 349M/14 s to 2.1G/33 s. The TEMPORARY drop-in (12G/14G) masks this. The unit's own limits are MemoryHigh=4G and MemoryMax=6G (`deploy/systemd/breezy-quote-tape-ingest.service:42-43`).

**Goal state.** Every run from rotation to rotation+grace+2 timer periods is bounded (A3). Then the drop-in is removed, and the same window is confirmed under the unit's own limits.

## Code facts (verified)
- **F-a. Which file counts as open.** `_open_files_for_instance` (`quote_tape_ingest_core.py:1003-1044`) can treat only the newest-mtime file of each type as open (`:1040`).
  - That file is open if written within grace (`:1041`, `DEFAULT_LIVE_GRACE_MINUTES=30` `:211`), or if its instance is the newest and the service is active (`:1037`).
  - A live instance's intact file with no EOS is `skipped-unclosed` (`:1368-1375`).
  - `instance_is_dead` is set at `:1743`.
- **F-b. Path depends on time since rotation (A1).**
  - Inside grace, the dead instance's newest files are still in `open_files`. The first post-rotation run therefore takes `_ingest_instance_per_file` with `instance_is_dead=True`, and every held-back no-EOS file converts at once. This is **H1**.
  - From rotation+30 min, `open_files` is empty and nothing is truncated (`:1792`). The path becomes `ingest_instance` (`:1801`) → `default_convert` (`:736`) → `_convert_stream_natively` (`:698-733`). It checks only the per-type marker (`:1132`), so it re-reads every feather file, including per-file-converted ones. This is **H2**.
    - Native's exists-skip happens only after a full read and transform (`parquet.py:2683-2685`, N1).
    - Any non-disjoint refusal sends the whole type to `_extend_overlapping_stream` (`:867-945`), which re-reads and runs EXTEND in 50K-row chunks (`EXTEND_CHUNK_ROWS` `:269`).
  - Nothing ever promotes a per-file-converted type to a type marker (docstring `:377-379`).
- **F-c. Dotfiles defeat the fully-converted check.** `_instance_is_fully_converted` (`:335-349`) does not skip dotfiles. The `*.feather` glob matches the `.converted-file-` markers (`:233`), so the check returns False and the instance is rescanned every run. `_instance_has_pending_work` does skip dotfiles (`:384`).
- **F-d. Salvage is unbounded and has a correctness bug (N4).** `_salvage_one_file` (`quote_tape_salvage.py:573-628`):
  - loads the whole table from `salvage_feather_file` (`feather_preflight.py:487-490`);
  - runs `list(_handle_table_nautilus(whole table))` (`:595`);
  - dedupes with `_drop_already_landed` (`:199-210`), an all-time, identifier-filtered query that omits FLAT rows;
  - writes with raw `write_data` (`:612`), whose exists-skip (`parquet.py:378-380`) can silently drop rows.
- **F-e. Deadline checks are per type.**
  - The per-file path calls `admit()` once per type (`:1379-1384`), and `ingest_instance` once per type (`:1136-1139`).
  - The loop-top `can_admit()` (`:1733`) defers every remaining instance, including ones with nothing pending.
- **F-f. Definitions query is unbounded.** `convert_instrument_definitions` (`:585-695`) runs an unfiltered, all-time `query(data_cls)` (`:662`) plus a whole-instance read.
- **F-g. Page cache.** cgroup v2 charges page cache to the unit. Stage 0's `memory.stat` file bytes are therefore a lower bound (A7).
- **F-h. Stall predicate.** `_count_pending_deferral_units` (`:2076-2133`). Exit 4 fires after `STALL_MIN_CONSECUTIVE_RUNS=4` (`ingest_deferral_streak.py:87`).
- **F-i. Timers.**
  - The frequent timer fires every 15 min, except a 16:15→17:15Z hole (`breezy-quote-tape-ingest-frequent.timer:15-30`).
  - The service sets `TimeoutStartSec=780` and `--deadline-seconds 600` (`.service:87,97`).
- **F-j. Sizes.** `quote_tape_ingest_core.py` is 2,277 lines (A16). The CLI `__all__` starts at `quote_tape_ingest_cli.py:372`, and `_extend_table_chunked` is at `:429`.

## Hypotheses
| ID | Hypothesis | Evidence |
|---|---|---|
| H1 | Held-back no-EOS files land in the in-grace run | Files and bytes by state; day-long `skipped-unclosed` counts; variant A |
| H2 | Post-grace whole-instance path re-reads and re-extends per-file-converted files | Variant D: path taken, "already exists" prints, EXTEND chunks |
| H3 | Salvage builds whole files | Truncated count; largest truncated file (P7); A3-iii |
| H4 | `memory.peak` is mostly page cache, plus cold memo rescans | anon vs file; A2 vs A1 |
| H5 | Deadline granularity is too coarse | Per-unit durations; deferred split pending vs not |
| H6 | Definitions all-time query | A3-iv; definition row counts |

## Stage 0: measure first (offline, no repo change, production-safe)
### S0.1 Snapshot (CR-1, A7)
Root is `~/.cache/breezy-ing3-s0/<date>/`, on the same filesystem as the catalog (`stat -f`).
- **Hardlink** only the recorder `*.feather` files (non-dot) of DEAD instances, and `data/**/*.parquet`.
- **Copy** every dotfile: markers, attempts, and `.preflight-memo-v1.json` (in the instance dir, `preflight_memo.py:27,182`).
- **Copy** the new LIVE instance's feather files with `cp --preserve=timestamps`. Never hardlink them, because the recorder is still appending.
- **Never chmod any link.** P8 is rejected.
- **Timing:**
  - Read `T_rot` from the journal.
  - At T1 (after the last pre-rotation production run exits, before rotation): copy the live instance's dotfiles and hardlink `data/`.
  - After rotation and before the first post-rotation fire: hardlink the rotation instance's feather tree and copy the new instance's dir.
- **Inode manifest:** write `(path, inode, size, mtime_ns)` for every linked file.
- Snapshotting may happen inside 08:45–09:30Z. Runs may not.

### S0.2 Driver (A2, P1, CR-1)
- A scratchpad script, run with `/home/jon/breezy/.venv/bin/python` and `PYTHONPATH=/home/jon/breezy/src`.
- It asserts the resolved `catalog_root` is under `~/.cache/breezy-ing3-s0/`.
- It calls `run_ingest(root, now_ns=<t>, service_active_probe=lambda: True, convert_fn=default_convert, deadline=RunDeadline(budget_ns=600*10**9))`, constructing the deadline immediately before the call.
- It records:
  - per-unit timings;
  - `extend_dedupe_counters.summary_line()`;
  - "already exists" prints;
  - `deadline.admitted` and `deadline.scans_started`;
  - deferred counts.
- After every run it re-checks the inode manifest. Any change to a linked inode means a production-safety ABORT: stop Stage 0 and report.

### Variants (A1, A6, CR-4)
| Variant | `t` / setup |
|---|---|
| A | First post-rotation fire (in grace) |
| B | Second fire |
| C-a / C-d | `deadline=None`, at A's time and at D's time |
| D | `T_rot` + 30 min + 15 min, chained on A's output state |
| D′ | Same state as D, with every non-truncated dead instance forced per-file (in-process monkeypatch in the driver only) |

### S0.3 Census
- Files and bytes by type, state and layout.
- DepthTruncation `instrument_id` metadata.
- Flat files at type roots.
- Definition row counts.
- The largest single feather file and the largest truncated file, by rows and bytes (P7, A11).

### S0.4 Runs (A6)
**Unit setup.** Each run uses `systemd-run --user --wait --collect -p MemoryMax=<X> -p MemoryHigh=<X−10%> -p LimitNOFILE=524288 -p RuntimeMaxSec=780`.
- Copy Nice, CPUQuota, IOWeight and TimeoutStartSec from `systemctl --user show breezy-quote-tape-ingest.service`. Do not pass `--nice=10`.
- A 1 s sidecar logs cgroup `memory.peak`, `memory.stat` (anon/file/file_dirty) and `memory.events`. Never use RSS.
- Before each run, restore the dotfiles and delete any non-manifest files under `data/`.

| Run | Memory | What it tests |
|---|---|---|
| A1 | 14G, variant A | Reproduce the failure |
| A2 | 2G, variant A | H4 |
| A3 | 2G and 14G each | Isolations: (i) skipped-unclosed only; (ii) forced whole-instance; (iii) salvage only; (iv) definitions only |
| A4 | — | No-op on the live copy |
| A5 | 14G and 2G | Variants D and D′ |

A variant C run that hits the 780 s cap is recorded as censored (≥780 s).

### S0.5 Window
- Never run during 16:30–17:10Z or 08:45–09:30Z.
- Never run concurrently with any study, replay, scorer, AUD-07 or other heavy job.
- Start right after a production run exits. `RuntimeMaxSec=780` is below the 900 s timer period, so runs cannot overlap.
- Never touch the node, supervisor or recorder.

### S0.6 Exit
Write `docs/plans/backlog/ING-3_2026-10-08/STAGE0_findings.md`. The rules below decide what Phase 1 builds.
- **Build gate.** W1, W2, W4 and W5 are built only if their hypothesis carries ≥15% of anon peak or wall time. W3 is exempt, because it is a correctness fix (N4).
- **Native streaming dedupe.** Revisit only if dedupe queries carry ≥15% of anon peak (N2).
- **W1 scope (CR-4).** If D′ is no worse than D on wall time and anon peak, and no worse than 1.1× on a dead instance the per-file path never touched, then every non-truncated dead instance goes per-file. Otherwise W1(a) applies only to instances that carry per-file markers.

### S0.7 STOP and post-STOP branches (A5, A6)
Memory and time are judged separately.
- **Memory:** pass means anon peak ≤2G and `oom_kill=0`. Memory acceptance alone gates drop-in removal.
- **Time STOP:** A3-i needs more than about 450 s at 2G or at 14G.
- If the time STOP fires, the peer loop (never the operator) chooses a pre-declared branch:
  - **(a) Bounded multi-run drain.**
    - `deferred_units` > 0 only for pending work.
    - The backlog drains within N ≤ 3 runs (< `STALL_MIN_CONSECUTIVE_RUNS=4`).
    - Exit 0, no `DEFERRAL_STALLED`.
    - The drop-in is still removable on memory.
  - **(b) Native rotation lever.** Shorten `QUOTE_TAPE_ROTATION_INTERVAL` (`node_config.py:446-448`). It is pinned by `tests/contract/test_quote_tape_streaming_contract.py` and needs a recorder restart. It needs a separate peer-reviewed plan and is never done inside ING-3.

## Nautilus gap proof (N1–N3)
- **Native already provides:**
  - per-file table-only conversion (`parquet.py:2656-2693`);
  - `convert_stream_to_data(identifiers=)`;
  - `write_data(skip_disjoint_check)`;
  - `query(identifiers, start, end)` with inclusive file bounds (`:2966`);
  - a streaming session (`backend_session` `:1795`, `DataBackendSession()` `:1874`, `to_query_result` `:1768`).
- **Native lacks:**
  - a per-file marker checked before the read. Its filename-equality exists-skip (`:2683-2685`, `:378-380`) runs only after the read and transform (N1);
  - truncated-prefix salvage. `_read_feather_file` returns None on ArrowInvalid (`:2799-2800`), and the stream loop skips it silently (`:2645-2646`) (N3);
  - row-level windowed dedupe EXTEND.
- **Streaming session:** not adopted in Phase 1 (N2). Windowed per-chunk dedupe already bounds the cost, and `ORDER BY ts_init` (`:2114`) may buffer.
- **Rule:** route more work through the native table-only path, and less through object-building paths.

## Phase 1 (each package gated by Stage 0; each merges independently)
### W1 (H2; F-b, F-c)
- **(a)** Dead-instance routing at `:1792` follows CR-4.
- **(b) Type-marker promotion, new module `quote_tape_ingest_promotion.py` (A8).** Promote only when ALL of these hold:
  - `instance_id != newest_instance_id`;
  - `open_files` is empty;
  - every file of the type is per-file-marked or salvage-marked;
  - there are no unreadable or unreported files.

  Never promote on `service_active == False` alone.
- **(c)** `_instance_is_fully_converted` skips dotfiles.
- **Before W1(b):** grep every consumer of `MARKER_PREFIX` outside ingest (L-46).
  - The comment at `:1756` says truncated instances never earn type markers, and W1(b) changes that.
  - A consumer that reads a type marker as meaning "intact" blocks W1(b) until it is ruled on.

### W2 (H5; P5, A9–A11)
- **Per-file admit.** `_convert_one_tick_type_per_file` calls the consuming `admit()` once per convertible file, after the skip filters (marked, unreported, unreadable, truncated, empty, unclosed). Never call `can_admit()` in the file loop. A no-op never consults the deadline.
- **Breadcrumb (A10).** On a mid-type denial, clear the `_write_attempt` breadcrumb, so `_poison_first_order` (`:462`) does not treat the instance as killed.
- **Pending check (A9).** In `run_ingest`, when `deadline is not None`, run a stat-only pending check (`_open_files_for_instance` + `_instance_has_pending_work`) before the loop-top `can_admit()`.
  - An instance with no pending work is not deferred. It gets a new outcome `skipped-no-pending`, handled in `_ladder_rank`, `_merge_pass_results`, `summary_line` and `_outcome_has_failure`.
  - With `deadline=None`, behaviour is byte-identical.
  - `count_deferred` and `_count_pending_deferral_units` (`:2076-2133`) are unchanged.
- **Overrun bound (A11).** The one-file overrun bound applies to the per-file path only. The native whole-type path stays per-type bounded. Stage 0 sizes the largest unit against 600 s (L-53).

### W3 (H3 and correctness; A12, N4, N5, P2, P7)
- **W3a (behaviour-neutral).** New `quote_tape_extend.py`:
  - `extend_table_chunked(catalog, write_target, data_cls, table, *, write_rows, chunk_rows=EXTEND_CHUNK_ROWS)`, plus `EXTEND_CHUNK_ROWS` and the sort/cut helpers.
  - It imports neither core nor salvage. The writer is injected, to avoid an import cycle.
  - Core keeps `_extend_table_chunked` as a thin wrapper that resolves `write_fresh_capture_rows` from core's globals at call time. This keeps the monkeypatches at `test_quote_tape_ingest_bounded_read.py:685,756,839,875,916` and `test_quote_tape_ingest_cli.py:1874` working.
  - Core and the CLI `__all__` re-export the old names.
  - The extend module wraps `NotImplementedError` from `_handle_table_nautilus` as `ChunkDeserialiseUnsupported(original, chunk_index)`. The core wrapper re-raises `original`.
- **W3b.** `_salvage_one_file` calls `extend_table_chunked(..., write_rows=write_fresh_capture_rows)`.
  - `chunk_index == 0` (before any write) becomes `_UnsupportedSalvageType`, which writes the terminal marker. A later chunk is a retryable isolated error.
  - The switch to the windowed, flat-root-aware `_drop_already_landed_unfiltered` plus the A8 `ExtendWriteMismatch` check is deliberate.
  - `ExtendWriteMismatch` subclasses ValueError (`salvage.py:379`), so `_ISOLATED_ERRORS` (`:103-108`) catches it. The file stays unmarked and its siblings continue.
  - The `collect=True` table stays whole-file, the same bound as native (N6). The bound is on objects deserialised per call (P7).

### W4 (H6; A13, N8)
- Query with `start=min_ts, end=max_ts` (integer ns) of the streamed definitions. Both ends are inclusive.
- The dedupe key includes `ts_init`, so the result is unchanged.
- The query stays unfiltered by identifier.

### W5 (H4, only if A2 shows page cache dominates; A14, P6)
- `preflight_memo.py` classifies live, non-open, no-EOS files from `_read_tail` (`feather_preflight.py:465`).
  - Tail-derived reports are never memoized.
  - Dead instances are still fully scanned.
- **Optional fadvise in `feather_read.py`:**
  - `posix_fadvise(DONTNEED)` on the same fd, in `finally`, ignoring OSError/AttributeError;
  - guard for fsspec backends without `fileno()`;
  - no `pa.memory_map`;
  - never on open or live-instance files.

  If built, security-reviewer is required.

### Dependency direction (P3, A16)
- `core → promotion → salvage` and `core → extend`.
- Promotion never imports core; helpers are passed in. Move a helper down only if no test monkeypatches it on core.
- Bind the new modules into core and into the CLI `__all__`.
- Extend `tests/unit/test_quote_tape_ingest_core_boundary.py`: the new modules never reference `quote_tape_ingest_cli`, and promotion and extend never import core.
- `lint-imports` (console script, CWD = tree) must report "N kept, 0 broken".

## RED tests
### New `tests/unit/test_quote_tape_ingest_rotation_burst.py`
- `test_dead_instance_with_per_file_markers_takes_the_per_file_path`
  - Fixture: dead instance, no truncation, no open files; reaches `:1801` today.
  - Spies on `read_feather_coalesced` (P-n1).
- `test_whole_instance_path_never_rereads_a_per_file_marked_feather`
- `test_dead_instance_per_file_path_treats_newest_file_as_closed` (N9)
- `test_fully_per_file_converted_type_in_superseded_instance_is_promoted_to_type_marker`
- `test_promotion_never_fires_while_a_file_is_open_or_unclosed_in_a_live_instance`
- `test_promotion_never_fires_for_newest_instance_when_service_inactive` (A8)
- `test_new_file_after_type_marker_is_detected_or_promotion_refused` (A8)
- `test_instance_is_fully_converted_ignores_marker_dotfiles`
- `test_noop_run_after_promotion_never_calls_scan_instance_memoized`, which also asserts `deadline.scans_started == 0` (P-n2)
- `test_n_unclosed_files_converted_per_file_never_surface_a_non_disjoint_failure` (P-n3, corrected)
  - The per-file write runs native's disjoint check (`parquet.py:2687-2693`), and a refusal routes to `_extend_table_chunked` (`core:1422-1434`).
  - Asserts every file ends marked and no outcome is `failed`.

### Extend `tests/unit/test_quote_tape_ingest_deadline.py`
- `test_per_file_loop_admits_once_per_convertible_file`
- `test_marked_skip_never_consults_the_deadline`, which asserts `admitted` is unchanged
- `test_overrun_is_bounded_by_one_file_on_the_per_file_path`
  - Setup: 3 convertible files; the budget expires after the 1st.
  - Expect: 1 converted, `deferred_units=1`, `deferred_instances=0`.
- `test_mid_type_deferral_clears_breadcrumb_and_is_not_poisoned_next_run`
- `test_loop_top_deferral_skips_instances_with_no_pending_work`
  - Setup: one pending and one fully-marked instance, after expiry.
  - Expect: `deferred_instances=1`.
- `test_stall_alert_still_fires_only_on_real_pending_work`
- `test_deadline_none_is_byte_identical`

### New `tests/unit/test_quote_tape_salvage_chunked.py`
- `test_salvage_never_deserialises_more_than_extend_chunk_rows_plus_run_objects`: rows per `_handle_table_nautilus` call ≤ `EXTEND_CHUNK_ROWS + R − 1`
- `test_chunked_salvage_lands_same_rows_as_unchunked`
- `test_salvage_dedupe_window_is_per_chunk`
- `test_salvage_transform_defaults_match` (`convert_bar_type_to_external=False` on both paths)
- `test_salvage_with_flat_root_present_lands_no_duplicates`
- `test_salvage_unsupported_type_still_writes_unsupported_marker` (on the first chunk, before any write)
- `test_salvage_extend_write_mismatch_leaves_file_unmarked`

### Extend `tests/unit/test_quote_tape_ingest_definitions_first.py`
- `test_definition_dedupe_query_bounded_to_streamed_ts_window`
  - Fixture: mixed flat + nested layout.
  - One landed definition sits exactly at each bound.

### W5 only, `tests/unit/test_preflight_memo.py`
- `test_live_unclosed_file_classified_from_tail_without_full_decode`
- `test_tail_report_is_never_memoized`
- `test_dead_instance_file_still_full_scanned`

### Bounded memory (CR-2, A15, P4)
`test_rotation_burst_fixture_rss_ratio_bounded`:
- Run in a fresh child process; measure ΔRSS (`ru_maxrss`) over a warmed baseline, with ≥20k rows per file.
- Pass: ΔRSS(K-file burst) ≤ 1.5 × ΔRSS(largest single file). The 1.5 is proposed by r2 and must be confirmed by the convergence reviewer.
- `max_memory()` is diagnostic only. Never use tracemalloc (L-49).
- Mark `@pytest.mark.memory` and gate it on `BREEZY_RUN_SLOW`.

### Observability (A17, L-52)
Tests assert the changed `deferred_instances=` and `extend_dedupe:` stdout lines. Check the journal after the first live run.

### Guards that must stay unweakened, in every focused gate
- `tests/contract/test_quote_tape_truncation_preflight.py`
- `tests/contract/test_quote_tape_ingest_native_pin.py` (N7)
- `test_quote_tape_ingest_unit_contract.py`
- `TestTheMixedCatalogLayoutIsPinned` (`test_quote_tape_ingest_cli.py:946`)
- `test_quote_tape_ingest_core_boundary.py`
- `test_quote_tape_ingest_launch_window.py`
- all `test_autonomy_*`
- the import, exec-pin and firewall guards

## Sequencing
- Stage 0 can start now; it is offline.
- Phase 1 waits for DEFER-STREAK-LOAD to merge, because it touches the same files. Then fast-forward the worktree and re-gate.
- Merge order: W3a → W1 → W2 → W3b → W4 (→ W5).
- Run the full gate after each merge, and read EXIT before every push.
- The oneshot timer picks up new code on its next fire.

## Acceptance (A3, A4, A17)
**Window.** Every run from `T_rot` to `T_rot` + 30 min + 2×15 min. If the window spans the 16:15→17:15Z hole, extend it to the next two actual fires.

**Daily proof.** For 3 consecutive days, with the drop-in still present, every run in the window must show all of the following. A read-only `systemd-run` sidecar samples the production cgroup's `memory.stat` and `memory.events` at 1 s.
- anon peak ≤2G and `oom_kill=0`;
- elapsed ≤600 s;
- `deferred_instances=0` (or the branch (a) form);
- `extend_dedupe` chunks filtered with `flat_root=none`, or no EXTEND at all;
- exit 0 and no `DEFERRAL_STALLED`.

`memory.peak` is diagnostic only. The AMEND2 wording (anon metric; "or no EXTEND") is amended by peer-review ruling.

**Secondary.** No-op runs stay ≤500M anon and ≤20 s.

**Drop-in removal gate.** Memory acceptance, plus one replica variant-A run at the unit's own 4G/6G with CPU/wall ≥0.3 (L-49).

**Removal procedure.**
1. Back up the drop-in to `~/.cache/breezy-ing3-s0/dropin.bak`.
2. Check `NeedDaemonReload` on every breezy user unit; abort if any other unit is pending. The supervisor unit is symlinked into the repo.
3. Remove the drop-in, `daemon-reload`, and post a one-line heads-up.
4. Confirm every run in the window under the unit's own limits.

**Rollback.** On `oom_kill > 0` or a non-zero exit, restore the backup and `daemon-reload`.

## Risks
| Risk | Mitigation |
|---|---|
| A snapshot write reaches production through a hardlink | Copy dotfiles; inode manifest; root-prefix assert |
| A live-instance hardlink keeps growing | Copy live files instead of linking |
| A promoted marker hides a later file | A8 predicate plus tests |
| Chunked salvage changes rows | N5 parity tests plus A8 |
| `skipped-no-pending` breaks merge or rank | Tests |
| Import cycle | Injected writer plus boundary test |
| daemon-reload side effects | `NeedDaemonReload` gate |
| Disk use | Hardlinks plus cleanup |

## Reviewers
- architect
- python-reviewer
- Nautilus-native (gap-proof sign-off)
- security-reviewer, only if fadvise is built

## Change log r1 → r2
- **Architect:**
  - A1: timing split and variant D.
  - A2: `service_active_probe=True`.
  - A3: acceptance window.
  - A4: anon metric and the replica run.
  - A5: memory and time judged separately, plus post-STOP branches.
  - A6: unit properties; `RuntimeMaxSec`; STOP judged at 2G and 14G.
  - A7: link/copy rules.
  - A8: promotion predicate.
  - A9: stall predicate unchanged; pending check.
  - A10: breadcrumb.
  - A11: per-file bound; L-53.
  - A12: unsupported-type wrap and deliberate dedupe switch.
  - A13: mixed-layout W4 test.
  - A14: no memo of tail reports.
  - A15: ΔRSS ratio test.
  - A16: sizes; L-46; `__all__`; lint-imports.
  - A17: observability.
- **Python reviewer:**
  - P1: `RunDeadline(budget_ns=…)`.
  - P2: extend module, adjusted to dependency injection.
  - P3: dependency direction.
  - P5 / CR-3: consuming `admit()`.
  - P6: fadvise constraints.
  - P7: object bound.
  - P-n1–n4.
- **Nautilus reviewer:**
  - N1–N3: gap proof.
  - N4: W3 is a correctness fix.
  - N5 / N6: parity and naming.
  - N7: `native_pin` guard.
  - N8: inclusive bounds.
  - N9: newest file treated as closed.
- **Coordinator:**
  - CR-1: no chmod; copy dotfiles.
  - CR-2: bounded-memory test.
  - CR-4: W1 scope decided from D/D′.
- **r2's own additions:** live instance copied, inode manifest, `NeedDaemonReload` gate.

## Not applied as written
- **P8** is rejected (chmod on a hardlink changes production).
- **P2 taken literally** would create a salvage↔extend import cycle. It is applied as dependency injection.
- **The P-n3 premise is wrong.** The per-file path runs the disjoint check rather than skipping it, so the test is re-specified.
- **Reviewer line citations** are corrected, as listed in the facts above.
- **N2's `chunk_size` keyword** is unverified; it is a Rust binding, and streaming is not adopted anyway.
- **The 1.5× ratio** is proposed by r2 and must be confirmed in convergence.
- **Branch (b)** goes to a separate plan.
- **`T_rot`** is read from the journal, presumably around 09:00Z.

---
## Convergence amendments (BINDING), architect review of r2, 2026-10-08: CONVERGED-WITH-NITS

All A/P/N/CR items were applied. The P-n3 correction is confirmed, and so is the dependency-injection approach (it keeps the monkeypatch targets working). The following text edits are binding.

**C1. W2 pending check.** This replaces the "Pending check (A9)" text.
- Run the check only when `deadline.can_admit()` returns False:
  1. Call `_open_files_for_instance` with the same arguments as `core:1744-1753`.
  2. Then call `_instance_has_pending_work`.
  3. If there is no pending work, append `skipped-no-pending`. Otherwise append `DEFERRED_DEADLINE` "not evaluated", as today.
- When budget remains, the path is unchanged, so W1(b) promotion still runs on fully per-file-marked instances.
- The new outcome is handled in four places:
  - `_OUTCOME_LADDER`: insert at index 0 (least significant).
  - `InstanceIngestResult.summary_line` (`core:1079`): return the reason, as `skipped-live` does.
  - The outcome comment at `core:1064`.
  - The exit table in `quote_tape_ingest_cli.py:225`.
- `_outcome_has_failure` (`core:1156`) is type-level only, so it is not touched.

**C2. S0.7 adds branch (c), memory fail.** Branch (c) applies in either case:
- anon peak stays above 2G after every package that Stage 0 gated in; or
- no hypothesis carries ≥15%.

Then:
- The drop-in stays, relabelled TEMPORARY with a date.
- STAGE0_findings names the dominant anon consumer.
- An r3 targets that consumer under the same acceptance window.
- ING-3 does not close.

**C3. Bounded memory.** The 1.5× ratio is confirmed, under these conditions:
- K ≥ 8 files;
- separate fresh children for the single run and the burst run;
- identical warmup.

If the test passes on HEAD, it is a regression guard, not RED.

**C4. Smaller items.**
- **Dependency direction:** add `salvage → extend` (W3b). Core call sites keep calling `_extend_table_chunked` by its core name, never `extend_table_chunked` directly.
- **Before creating `quote_tape_extend.py` / `quote_tape_ingest_promotion.py`:** grep the import-linter contracts and the module-placement pins (L-46).
- **Removal procedure step 3:** prefix it with "Immediately after a production run exits and outside the window:".
- **Rollback:** do it "after the same NeedDaemonReload gate".
- **Monkeypatch list:** add `test_quote_tape_ingest_bounded_read.py:610-611`. Tests also read `cli_module._extend_table_chunked` and `cli_module.write_fresh_capture_rows` (`:744, 827, 863, 903`), so keep both names in the CLI `__all__`.

**Verdict after amendments: READY.**
- Stage 0 next: the snapshot is taken around the 09:00Z rotation; runs start after 09:30Z, alone.
- Phase 1 starts after DEFER-STREAK-LOAD merges.
