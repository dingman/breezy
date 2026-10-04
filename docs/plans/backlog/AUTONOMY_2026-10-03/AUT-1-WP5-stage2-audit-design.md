# AUT-1 WP5 stage 2: daily completeness audit, module design (code-architect, 2026-10-04)

Base `a1475c6e`. Every leg is a pure function over one `AuditInputs` value, and all I/O happens in one builder's modules. Every module is ≤ 800 lines.

## Stage 2a: one builder, serial, lands first

### 1. `src/breezy/analysis/capture_audit_model.py` (about 350 lines, non-writer)

**Enums**
- `DayStatus`: PASS, INCONCLUSIVE, NO_INPUT, PRE_CAPTURE, PARTIAL_EPOCH, ERROR, FAIL.
- `Leg`: L, D, B, I, E, P, S, R1–R7, W, O, F, T, N, PC.
- `LegOutcome`: PASS, FAIL, PENDING, INFO, ERROR, SKIPPED.

**Results**
- `Finding(leg, outcome, cause, subject, detail)`. `subject` is an id or sha, never a path.
- `LegResult(leg, outcome, findings, metrics)`.
- `FillAudit(client_order_id, trade_id, family_id, source, drill, attributed, legs, causes)`.
- `AuditResult(day, family_id, status, cause, legs, fills, metrics, watchdog_evidence_gaps, duplicate_decision_lines)`.

**`AuditInputError(.cause ∈ ERROR_CAUSES)`.** `ERROR_CAUSES` is a closed set:
- `exec_snapshot_failed`, `exec_key_prefix_unknown`, `exec_record_undecodable`;
- `node_log_unreadable`, `node_log_unparseable`, `node_log_missing`, `node_log_blind`;
- `journal_failed`;
- `epoch_missing`, `epoch_rewritten`, `epoch_unlogged`, `epoch_unreadable`;
- `stream_unreadable`, `capture_projection_failed`;
- `recorder_watchdog_unarmed`;
- `bus_snapshot_missing`, `bus_snapshot_stale`;
- `funnel_missing`.

**Input types**
- `MarkerLine`.
- `LogMarkers(capture_refused, order_submitted, order_denied, nbp_published, fq_vector_complete, nbp_cycle_missed)`.
- `ReplayResult`.
- `BootEvidence(instance_id, source, stream, c1, log_name, scan, markers, replay, started_ns, last_line_ts_ns, ended, disposed, overlap_s, subscribed)`.
- `ExecFill`, `ExecOrder`, `ResolverContext`.
- `ExecView(fills, fill_by_day, fill_by_fingerprint, orders, resolvers, advisory=True)`.
- `FunnelRow`.
- `TapeIndex` (a Protocol): `lookup`, `quote_rows`, `depth_rows`, `best_ask_at`.
- `IngestLine`, `RecorderJournalEntry`, `RecorderProps`, `StallRecord`, `NotifierProof`.
- `AuditInputs(day, family_id, epoch, boots, exec, settlements, std_offsets, tape, ingest_lines, ingest_exited_after_rotation, recorder_journal, recorder_props, stall_records, notifier_proofs, now_ns)`.
- `LogSink` (a Protocol): `feed(event)`.

**Wire format and constants**
- `AUDIT_SCHEMA = "capture_audit/v2"`, with `audit_to_wire` / `audit_from_wire`.
- `METRIC_NAMES` is a closed set (r8 l.593, r12 l.825).
- Constants:

  | Name | Value |
  |---|---|
  | `STREAM_GAP_FAIL_S` | 180 |
  | `FLUSH_WINDOW_S` | 61 |
  | `R6_BASELINE` | 0.923 |
  | `SETTLEMENT_PENDING_H` | 36 |
  | `SETTLEMENT_ALERT_H` | 48 |
  | `BACKFILL_DAYS` | 8 |
  | `LIVE_PROOF_MAX_AGE_H` | 26 |
  | `PC_MIN_OVERLAP_S` | 1200 |

  Also `AUDIT_DIR_REL`, `LIVE_PROOF_NAME_RE` and `AUDIT_CACHE_DIR`.

### 2. Stub modules
For every W1–W3 file, a docstring plus signatures that raise `NotImplementedError`. Add all `AUT1_WRITE_AUTHORITY`, one-writer and `NAUTILUS_PERMITTED` rows now, so no parallel worktree touches the shared tables.

### 3. Additive edits to merged files
- `scan_node_log(..., sinks=(), raw_sink=None)` gives a single pass with online consumers.
- `domain.exec_intent.utc_day_for_ns`, with a parity test against `operator_controls.py:183`.
- Public `capture_settlement.read_settlement_day`.

### 4. `tests/support/capture_audit_fixtures.py`
Pure `AuditInputs` builders, plus real-writer stream fixtures.

## Stage 2b: three parallel worktrees

| Worktree | Files | API |
|---|---|---|
| W1, fill legs | `capture_audit_fill_legs.py` | `audit_fills(inp)` covers legs L D B I E P S. Also `leg_o`, `leg_f`, `leg_r6`, `tape_marks`. |
| W2, reconciliation | `capture_audit_replay.py`, `capture_audit_stream_legs.py`, `capture_audit_log_markers.py` | `BootReplay(LogSink)` is an online R2 reducer. Also `leg_r1`/`r2`/`r3`, `leg_r4`/`r5`/`r7`/`w`/`t`/`n`, `positive_control`, `MarkerParser`. |
| W3, I/O and orchestration | `capture_audit_inputs.py`, `capture_audit_host.py`, `capture_audit.py`, `capture_audit_cli.py` | `gather_inputs`, `boot_census`, `read_exec_view`, the journal templates plus `run_journal` (30 s), `read_recorder_props` via the bus snapshot, `RecorderCatalogTape`, `audit_day` (a pure status table), `days_to_audit`, `run_audit`, `main`. |

**Test files**
- W1: `test_capture_audit_fill_legs.py`.
- W2: `test_capture_audit_recon_legs.py`.
- W3: `test_capture_audit.py`.

Test names stay verbatim. Splitting them across three files follows the WP0-R10 precedent.

**Stage 3** depends on: `RecorderJournalEntry`, `StallRecord`, `NotifierProof`, `AuditResult.watchdog_evidence_gaps`, `audit_from_wire`, `AlertOffer`, `host.run_journal`, `DayStatus`, `AUDIT_DIR_REL`, `LIVE_PROOF_NAME_RE`, the CLI module path, the argv templates, `AUDIT_BUS_READS` and `AUDIT_CACHE_DIR`.

## Inputs

| Input | How it is read | Error handling |
|---|---|---|
| Ingest, supervisor and recorder journals | In-sandbox `journalctl` using r8's literal templates. Only the two time slots are substituted, and both are regex-validated. Timeout 30 s. | ERROR `journal_failed`. WP0-R1 shows journalctl works under bwrap. |
| Recorder `systemctl show` | Seam B's bus snapshot (`ExecStartPre=-…--bus-snapshot`), then `read_bus_snapshot`. | Missing or stale is ERROR. |
| Exec store | `exec_snapshot(take_flock=False)`. Advisory only. | |
| Everything else | Single-read, `O_NOFOLLOW`, under the data root. | |

The catalog is read with `pyarrow.dataset`, column-projected.

**Write binds:** audit, heal, `heal_alert_abandoned`, `derived/verdicts`, `evidence/alerts`, and the cache. `resolves_dns=True`.

## Gaps for coordinator rulings (C1–C18)

### High severity
- **C1.** Deduping before the R2 replay would shift `eval_seq`. Proposal: replay without dedupe, and report duplicates as INFO.
- **C2.** Which TrySubmit lines enter the R2 filter? WP0-R7b says drop them, r8 l.569 says vetoes enter as EntryVeto, and `ALWAYS_ADMITTED_KINDS` contains TrySubmit.
- **C3.** `entry_lines` is capped at 1000, so R1 and R2 must use sinks.
- **C4.** Runtime. One log pass takes 274 s, and an 8-day backfill is more than 1500 s. Proposal: scan each log once per run, partition by day, and add a `deadline_ns` guard.

### Other gaps
- **C5.** Bus-read grammar: `-p WatchdogUSec,NotifyAccess,Type -- breezy-quote-tape.service`.
- **C6.** A second `BusRead` is needed for the ingest unit's `ExecMainExitTimestamp`.
- **C7.** `recorder_watchdog_unarmed` makes every day ERROR until WP3 step 2. The precedence between PRE_CAPTURE and ERROR is also unspecified.
- **C8.** No `CAPTURE_EPOCH_START` emitter exists.
- **C9.** AUT-6 notifier and delivery formats have not been built. Build against r12's marker path, the injected `AlertOffer`, and a contract test.
- **C10.** r8's verdict names are not `VerdictKind` values. Only `health.capture_join` exists, `PRODUCER_SOURCE_SHA256` is empty, and the metrics need AUT-5 prereg.
- **C11.** Orphaned r8 tests: `registry_seq_zero_after_resolver_live_fails`, quote-Take vs `quote_tick`, and retention gzip. Retire with named counterparts: `payload_rehash_mismatch_fails` → `frame_copy_mismatch_with_tape_fails`; `forecast_payload_without_vector_complete_line_fails` → the R-B test; `partial_line_fails_r4` → the r12 replacement.
- **C12.** The WP0-R9 boot-count test belongs to heal (stage 3).
- **C13.** `utc_day_for_ns` lives only in adapters.
- **C14.** There is no public settlement reader.
- **C15.** The `_MARKER_RE` regex is missing markers. `NBP_CYCLE_MISSED` exists only on the unmerged WP4 branch.
- **C16.** Unit text must follow E-7e(f). This is stage 3.
- **C17.** Census source: the supervisor journal or its log file. The recommendation is the journal.
- **C18.** Leg W's daily re-send needs heal machinery. This is stage 3.

## Peer-review resolution (coordinator, 2026-10-04; ARCH and python both REQUEST_CHANGES; binding)
ARCH scored correctness 7, fit 7, tests 6, risk 6, minimality 7, feasibility 6. Every blocking item from both reviews is resolved below. Contradictions are resolved against the code.

### Layering and module split
- **S2-R1, LogSink placement (py H1).** `LogSink` and the marker event types live in the node-log package (`capture_node_log_io.py` or a new `capture_node_log_sinks.py`), never in the audit model. That keeps the layering free of cycles.
  - `scan_node_log(..., sinks=())` calls each sink with every event before `_absorb`, so sinks see every event uncapped.
  - The LogSink contract requires each sink to hold bounded state.
  - A sink that raises aborts the scan with `AuditInputError(node_log_sink_failed)`. Add that cause to the closed set.
  - `BootReplay` switches its per-boot filter and counter on each `InstanceIdLine`.
- **S2-R2, marker grammar (C3, C15, B8, py H2).** There is no `raw_sink`. `classify_line` and `_MARKER_RE` are extended with marker events: `CAPTURE_REFUSED`, `OrderSubmitted`, `OrderDenied`, `NBM_NBP_PUBLISHED`, `FQ_VECTOR_COMPLETE`, `NBP_CYCLE_MISSED` and `CAPTURE_EPOCH_START`.
  - An unparseable marker line is ERROR `node_log_unparseable`.
  - The `NBP_CYCLE_MISSED` format is pinned from WP4 a77a8f85 as a literal fixture. Its cross-check test lands in WP8's merge train.
- **S2-R3, model split (py M5).** Three modules:
  - `capture_audit_model.py`: enums, results, `AuditInputError`, constants, and the shared `is_guard_entry_veto` predicate (B7);
  - `capture_audit_input_types.py`: `AuditInputs`, `BootEvidence` and the other input types;
  - `capture_audit_wire.py`: `audit_to_wire` and `audit_from_wire`, with a round-trip test.

  Stage 3 depends only on the wire module and the results. `BootEvidence` holds reduced summaries or a lazy stream handle, never fully materialised tables.

### Replay rules
- **S2-R4 (C1). Amends WP5-R5(2).** R2 replays WITHOUT dedupe. `EvalSeqCounter.next` runs once per evaluation (`capture_ids.py:128-155`), and the quote and depth twins are real evaluations. Dedupe stays an INFO count and an R3 metric only. R3 compares only Take and TrySubmit, which are never twins.
  - Add test `test_r2_replay_keeps_quote_and_depth_twins_and_matches_node_counter`.
  - Add an oracle test: drive the real `FqCaptureAdapter` with generated sequences, render the log lines, replay them, and get identical admitted sets and `eval_seq`.
  - The replay reuses the real `OnChangeFilter` and `EvalSeqCounter`. It does not reimplement them.
  - Where the log carries `eval_seq`, use it. Report any mismatch against the stream as the R2 finding.
  - WP7 obligation: after the once-per-frame fix, `counter.next` runs if and only if a decision line is logged.
- **S2-R5 (C2). The architect is correct, verified at `capture_adapter.py:261`.** `follow_up` admits TrySubmit, EntryVeto and Refuse to the node's `OnChangeFilter` under `take.eval_ns`.
  - Replay rule: TrySubmit lines never advance `EvalSeqCounter`, because WP0-R7b's "drop" applies to the counter only.
  - They DO enter the filter. A submitted line enters as `TrySubmit`. A `VetoReason` line enters as `EntryVeto`, using the paired Take's `eval_ns`.
  - Guard EntryVetos are excluded on both sides.
  - `drop_try_submits` is never used on R2's filter path.
  - The python review's claim that TrySubmit never reaches the filter is rejected; it is contradicted by the code.

### Runtime budget and scheduling
- **S2-R6 (C4, B2, py H6).** One `scan_node_log` per log per run. Sinks partition outputs by the UTC day of each line, and reducer state carries across midnight.
  - **Per-log cache.** Rotated or disposed logs are immutable. Their per-day reducer outputs are cached in `AUDIT_CACHE_DIR`, keyed by `(name, size, mtime_ns, head-sha)`. In steady state only yesterday's log is scanned.
  - **Budget.** `AUDIT_WORK_BUDGET_S = 1500 − 600 (flock -w, E-7e(f)) − 60 margin = 840`, measured from process start. `time.monotonic()` is checked every 65,536 lines and raises `ScanDeadline`.
  - **No partial-day verdicts.** A day is written only when every log covering it has been fully scanned.
  - **Run order:** yesterday first, then INCONCLUSIVE re-audits, then the backfill oldest-first. Oldest-first means a day never ages out of the 8-day window. Python's order is adopted over the architect's newest-first, because the cache makes scans cheap and aging out is unrecoverable.
  - **Deferral.** A day the run does not reach gets no file and is listed in `audit_deferred_days`. It is not a reason to exit 1.
  - **Runtime evidence.** Prove steady state: 4 logs, plus the leg-T catalog scan, under `MemoryMax=1G`.
- **S2-R7 (C4 catalog).** `RecorderCatalogTape` uses a `pyarrow.dataset` scanner with filters on the day's `ts_event` range ± `FLUSH_WINDOW_S` and `instrument_id.isin(the day's instruments)`.
  - Read only the columns the legs need, and verify the column names first.
  - Set `batch_size=65536`, `batch_readahead=1`, `fragment_readahead=1` and `use_threads=False`. Use `to_batches()`, never `to_table()`.
  - **Tape leak (B7).** The audit loads its index eagerly, inside `gather_inputs`. An I/O failure there is ERROR `tape_unreadable`, a new closed cause.

### Bus reads and status precedence
- **S2-R8 (C5, C6, B4).** The audit row carries two bus reads:
  - `-p WatchdogUSec,NotifyAccess,Type -- breezy-quote-tape.service`;
  - `ingest_show`: `-p ExecMainExitTimestamp -- breezy-quote-tape-ingest.service`.

  Budget is 10. The bus snapshot is read FIRST in `main`, before any scan or lock wait.
  - Add `test_bus_snapshot_read_before_any_scan` and an aged-snapshot test.
  - ARCH-0 heads-up for stage 3: no existing row combines `studies_lock` with `bus_reads`. The snapshot is taken in `ExecStartPre`, before `flock -w 600`, so a lock wait over about 70 s makes it stale, which is ERROR. Stage 3 decides: either take the bus snapshot after the lock, or have the audit take no studies lock, since it is read-only. Escalate to an ARCH-0 ruling if neither fits.
- **S2-R9 (C7, B9). Status precedence.**
  - PRE_CAPTURE beats run-time host-state causes (`recorder_watchdog_unarmed`, `bus_snapshot_*`).
  - Data-integrity causes (exec store, node log, journal, epoch) beat PRE_CAPTURE.
  - Audit activation is gated on AUT-6's notifier.
  - WP8 obligation: the epoch must not be written before WP3 step 2 is deployed.

### Ownership and remaining gaps
- **S2-R10 (C8).** WP8's `CaptureActor.on_start` emits `CAPTURE_EPOCH_START`. W2 pins the line format, and WP8 adds a round-trip test through W2's parser.
- **S2-R11 (C9).** The AUT-6 contract test is an uncollected pending file (the WP2-R1 precedent). The default offer returns False, so the audit exits 1.
- **S2-R12 (C10).** Only `HEALTH` verdicts are written, as `health.capture_join`. Other results go to the audit file and alerts until AUT-5 preregisters them. A refused verdict write is INFO. `PRODUCER_SOURCE_SHA256` is owned by AUT-5 / ARCH-0 activation. The live-proof dead-man reads the audit file.
- **S2-R13 (C11).**
  - Retirements: payload_rehash → `frame_copy_mismatch_with_tape_fails`; forecast_payload → the R-B test; partial_line → r12 l.1154's replacement.
  - `registry_seq_zero_after_resolver_live_fails` is KEPT in W1. It needs a resolver-live input in `AuditInputs`.
  - The quote-Take tests become a leg-B parametrisation over depth10 and quote (WP2-R4).
  - The strictness test becomes `tape_frame_absent` INFO vs unequal FAIL (WP0-R9).
  - Stage 3 pins that `settlement_*.jsonl` is never gzipped within 30 days.
- **S2-R14 (C12–C18).**
  - The boot-count test goes to stage-3 heal. W3 asserts that the node census counts boots by `instance_id`.
  - `utc_day_for_ns` is duplicated, with a parity test that also pins the input `intent_created_ns` (`client.py:4677`).
  - Add a public `read_settlement_day`.
  - Unit text follows E-7e(f) in stage 3 (`breezy-autonomy-failed@%n.service`).
  - The census reads the supervisor JOURNAL. An empty journal on a day with node logs is ERROR `journal_failed`. Verify that journald retention is at least 10 days.
  - The leg-W re-send goes to stage 3. `leg_w` only computes the gaps.

### Build mechanics and stages
- **S2-R15 (B6, py 7). Stub rows.** 2a pre-declares each stub's `AUT1_WRITE_AUTHORITY` row at `min_calls=1`, grouped per worktree with comment separators. Each builder raises only its own floors. W1 and W2 rows declare no writes; only W3 edits its own write scopes. Each worktree has its own fixtures file.
- **S2-R16 (B6). Cache binds.** Two distinct `cache/` binds: one for the bus snapshot, one for E-8. `_sweep` never touches `.bus_snapshot`.
- **S2-R17 (B3, B5). Stage 2c** is serial:
  1. Merge W1, then W2, then W3.
  2. Run the full plan-named suite and the end-to-end W3 tests, which need the real legs.
  3. Produce the S2-R6 runtime evidence.
  4. Run mutations, the full gate and lint-imports.
  5. SEC and python review.

  W3 owns these tests:
  - the moved-duty tests;
  - families by construction;
  - canary/drill;
  - provenance;
  - census;
  - fail-loud;
  - the closure-test extension to the new modules.

## Stage 2a outcome (dc2e7cc7, plus a correction pending)
- **Parser bug fixed.** `_LINE_RE` rejected every WARN and ERROR line: Nautilus puts an ANSI colour code before the level, so all `OrderDenied` and `CAPTURE_REFUSED` lines would have parsed as unparseable. Fixed, and covered by a mutation test. Merged WP5-C code had carried the bug; it never reached a live consumer.
- **Runtime.** Two real logs scan in 248.7 s, about 4% over the old parser. RSS is about 21 MB.
- **Accepted deviations.**
  - `AuditInputs` gains `funnel`, `resolver_live`, `nbp_stations` and `nbp_cycles_ns`. `LogMarkers` gains `capture_epoch_start`.
  - `AuditResult.tape_marks` and the `TapeMark` and `WatchdogGap` types.
  - `BootEvidence.stream` is a lazy callable.
  - `utc_day_for_ns` raises `ValueError` in `domain`.
  - The one-writer table pin goes from 11 to 13.
  - The `capture_node_log_sinks` row has `min_calls=0`, because it is protocol-only.
- **Known limit.** With an `alert_offer` wired, WP4 logs nothing on a missed cycle, so leg N must read delivery evidence, not the log.
- **Corrections ordered.**
  - The node-log package owns `NodeLogSinkFailed`; S2-R1 forbids it importing the audit model.
  - `is_guard_entry_veto` means the capture guard's own refusal reasons. The FQ `VetoReason` EntryVetos enter the filter through `follow_up`.

## Stage 2b, W1 (1293985f)
- **Result.** RED: 115 tests. All mutants are killed; 3 needed added tests.
- **Accepted deviations.**
  - A new `capture_audit_fill_support.py` keeps both modules ≤ 800 lines; it has its own authority row.
  - The stage-2a stub pin moves from `min_calls == 1` to `>= 1`, consistent with S2-R15: builders raise their own floors.
  - Leg I's day is the intent day (`link.ts_ns`).
  - The R6 threshold is `R6_BASELINE` itself.
  - The climate-day end is re-implemented and parity-pinned.
  - Guard constants are pinned locally.
- **Requirements on W3 (forwarded).**
  - `TapeIndex.lookup` returns rows in the WP2-R4 frame-body shape.
  - `std_offsets` is keyed by both the city code and the ICAO id.
  - A `BootEvidence.stream()` failure maps to `capture_projection_failed` / `stream_unreadable` in orchestration.

## Stage 2b, W2 (3c5d1aa7)
- **Oracle.** 12 seeds were run through the real `FqCaptureAdapter` and `EvalSeqCounter`: twins, follow-ups, guard refusals and non-monotone frames. All 7 mutations were killed.
- **RED was weak.** Code was written before tests. The mutation table is the evidence (accepted, same precedent as earlier).
- **Accepted deviations.**
  - The tests are split into two files, for size.
  - `BootDayReplay` carries a bounded hash chain plus a 61 s tail. R2 compares it against the stream's records.
  - `MarkerParser` caps each kind at 50k per boot-day; overflow → `node_log_sink_failed`.
  - The heartbeat table name is a pinned literal, because `analysis` may not import Nautilus.
- **S2-R18, R1/R3 input.**
  - R1/R3 read `scan.entry_lines` (Take and TrySubmit only), which are tens per day.
  - A truncated list (`entry_total > len(entry_lines)`) is ERROR, never a silent pass. Fail-closed is accepted.
  - 2c pins this with a test.
- **S2-R19, AUT-6 contract (leg N).** A missed-cycle delivery proof is `NotifierProof(unit="NBP_CYCLE_MISSED", invocation_id=str(cycle_ns))`. AUT-6 must match it, or the constant changes in the same commit as AUT-6's format.
- **S2-R20, follow-up.** Add `write_drops` to `HeartbeatSummary`, so R5 avoids a full stream read. This is a 2c or later item, not blocking.
- **2c notes.**
  - The stage-2a default fixture is inconsistent: `admitted_total=1` with no decisions. W3's PASS fixtures must be internally consistent.
  - Expect conflicts in `test_capture_audit_stubs.py` and `capture_closure_lint.py`.

## Stage 2b, W3 (d9360e66)
- **Result.** Focused gate `phase1 rc=0 phase2 rc=0`; lint-imports 11 kept / 0 broken; exec client sha unchanged. All 6 mutants killed. The cache-key mutant needed the fixture padded past 64 KiB, because the key hashes only the first 64 KiB.
- **New modules (accepted, size split):** `capture_audit_cache.py`, `capture_audit_exec_view.py`, `capture_audit_tape.py`.
- **Accepted rows:** a one-writer row for `capture_audit_host._run_template`; an X1 "WIDENED, not relaxed" row for `tests/support/capture_audit_w3_fixtures.py` (no `SOCKET_RESTORING_MARKERS`).
- **Deferred to stage 3 (accepted):** the audit row, and the bus-snapshot bind.
- **Pending e2e:** `tests/unit/autonomy/pending_s2c_capture_audit_e2e.py` is RED until it runs against the real W1/W2 code. 2c activates it.

## Stage 2c rulings (coordinator, 2026-10-04; binding)
- **S2-R21, closure lint.** W3 extended the shared closure lint (`tests/support/capture_closure_lint.py`) to accept slot-templated argvs. This is accepted ONLY as a strict extension:
  - every slot must resolve to a value drawn from a closed, pinned set;
  - a template that has a free-form slot, or a slot that could carry a path outside the existing allowlist, is refused;
  - every pre-existing lint test passes unchanged;
  - a mutation (any slot admitted) turns a test red.
  The security review checks this explicitly.
- **S2-R22, settlement cause.** A settlement read failure gets its own cause, `settlement_unreadable`. It must not reuse `capture_projection_failed`. Add the cause to the closed set, and extend the exact-set test. This is an extension, not a weakening.
- **S2-R23, ERROR days.**
  - ERROR is not terminal. A day whose verdict is ERROR is re-audited on the next run.
  - Only PASS and FAIL are cached under the cache key.
  - A test pins both halves.
  - If the design body or plan r12 says ERROR is terminal, STOP and cite the line instead.
- **S2-R24, subscribed set.**
  - If plan r12 §3.11–§3.16 names a source for the subscribed-instrument set, use that source.
  - Deriving the set from tape activity is accepted only if the plan names no source. In that case, note the deviation here.
- **S2-R25, PASS fixtures.** Every PASS fixture is internally consistent. For example, `admitted_total` equals the number of admitted decisions, which replaces the stage-2a default. One test asserts that each PASS fixture audits to PASS through the real legs.

## Stage 2c outcome (8497ca47, b8efcc84, 8224bf57)
- **Done.** S2-R18 and S2-R21..R25 are done.
- **S2-R21 tightening.** The lint had accepted any slot name. Slots are now restricted to `ALLOWED_ARGV_SLOTS = {since, until}`, and each slot must follow its own flag. Two mutations pin this.
- **S2-R23 meaning.** There is no day-level verdict cache. ERROR days re-audit together with INCONCLUSIVE ones, and a scan that errors writes no cache entry.
- **S2-R24.** Plan r12 names no source for the subscribed set. Tape-derived `active_instruments` stands. r8 line 574 says the audit cannot observe subscriptions.
- **Seam found by the real-host run.** `BootDayReplay` was not cacheable: the write failed silently with `TypeError`, so every run re-scanned every log. It is now registered, and the codec is `scan-cache/2`.
- **Runtime evidence** (2026-10-02, 4 logs plus the real tape, `MemoryMax=1G`, bwrap overlay):
  - cold run 317.5 s / 650 MB; warm run 6.8 s / 710 MB;
  - real CLI exit 1, because the undelivered `CAPTURE_LIVE_PROOF_STALE` alert is by design;
  - verdict PRE_CAPTURE, since WP8 is not deployed.
  - The R2 `duplicate_decision_lines` result is the known FQ double evaluation (WP5-R5, fixed in WP7).
- **S2-R26, REJECTED deviation: a lazy import used to dodge the audit CLI's httpx closure test.**
  - The test keeps the audit's import closure free of the HTTP client. A function-level import still loads httpx at run time, which is laundering, the same class as the rejected WP5-A option 2.
  - Fix: `capture_forecast_ref` must not reach `breezy.ingest` or `forecast_subscriber`.
    - Move `local_standard_date` to `breezy.normalize.climate_day`, which `gaps` already imports. Re-export it from `gaps`.
    - Move `NBP_QUANTILE_MODEL` to `strategy/ladder_ev/forecast_state.py`. Re-import it in `forecast_subscriber`.
    - Restore the module-level import in `capture_audit_fill_legs`.
  - Add a closure test: `capture_forecast_ref` loads neither `httpx`, nor `breezy.ingest`, nor `nautilus_trader.common.actor`.
- **S2-R27.** `_check_epoch` reads the row key `"capture_heartbeat"`; the real key is `"custom_capture_heartbeat"`. Fix it, with a test.

## Stage 2c review rulings (security review: APPROVE, 1 MEDIUM-pair and 6 LOW; binding)
- **S2-R28, cache key covers the reducer code.** The key gains a sha256 over the source bytes of the reducer modules: `capture_node_log*`, `capture_audit_replay`, `capture_audit_log_markers` and `capture_audit_cache`. The hash is computed once per process. We use a source hash rather than a hand-bumped constant, because hand bumps drift. A test shows that a changed reducer source changes `log_key`.
- **S2-R29, entries bind their key.** The body embeds its key, and a read compares it; a mismatch is a miss. The docstring says the cache is unauthenticated, trusted as same-uid data.
- **S2-R30, cache-read failures are misses.**
  - `RecursionError` and `OverflowError` are cache misses.
  - `open_root` refusals inside `read_scan_cache` are misses too.
- **S2-R31, the journal cap is enforced while reading.** The journal read stops at `_MAX_JOURNAL_BYTES` bytes, counted in bytes, and an oversize journal raises `journal_failed("oversize")` without buffering the whole journal. A test pins this.
- **S2-R32, slot digits are ASCII.** `_SLOT_RE` uses `[0-9]`.
- **S2-R33, firewall guard reformat reverted.** Revert the incidental ruff reformat of `test_execution_egress_firewall_guard.py`. The only diff against `cab72b46` must be the single WIDENED X1 row.
- **Noted only.** The closure lint ignores kwargs such as `shell=` and `env=`. That predates this stage, and is a stage-3 lint hardening item.

## Stage 2c review rulings (python review of the W1 legs: REQUEST_CHANGES; binding)
- **S2-R34 (HIGH), leg B no-lookahead.**
  - Add `available_at_ns <= take.eval_ns` for the forecast reference, and `frame ts_event <= take.eval_ns` for the frame reference.
  - New causes: `forecast_ref_lookahead` and `frame_ref_lookahead`. Add them to the closed set, with RED tests.
  - We use `<=` rather than `<`: a reference available at the evaluation instant was in hand when the decision was made.
- **S2-R35, leg P after 23:00Z.**
  - First check the tape-mark definition in r8 and r12 and cite the lines.
  - A fill whose next hourly mark falls on D+1 uses D+1's 00:00Z tape mark when the tape has it.
  - When the tape does not have it, the outcome is INCONCLUSIVE, and the day is re-audited. It is never FAIL.
- **S2-R36, leg F.**
  - A truncated scan makes leg F INCONCLUSIVE, with cause `exec_fill_census_truncated`. It is no longer an INFO-only PASS.
  - With no boot scan at all, leg F is also INCONCLUSIVE, with cause `node_scan_missing`.
- **S2-R37, leg S station matching.** Match on the same city-or-ICAO key set that `offset_of` uses, through one shared normaliser, with a KLAX-versus-LAX test.
- **S2-R38.** `test_capture_audit_fill_legs.py` is 1233 lines. Split it by leg group so each file is ≤ 800 lines.
- **S2-R39, LOW items.**
  - Leg D exit detection uses leg semantics, because a NO entry arrives as SELL or BUY_SHORT, so the cause is labelled correctly.
  - `_frames_equal` requires the minimal frame-shape keys.
  - `tape_marks`:
    - nets only fills with `ts <= mark hour`;
    - an unknown side is a per-fill FAIL, not a whole-day ERROR;
    - a fractional quantity is an explicit FAIL, never a truncation.
  - `leg_r6` with zero refusals: verify that the metric's consumers tolerate the missing key. If any does not, emit the metric as null.
  - A `fill_by_day` entry dropped for a cross-day stamp now emits an INFO finding.

## Stage 2c review rulings (python review of replay and orchestration: REQUEST_CHANGES; binding)
- **S2-R40 (HIGH), `_guard_findings` day cut.**
  - Filter guard records and detector events by `_day_of(record.wall_ns) == day`, the same rule `_actual_records` uses.
  - Add a RED test for a boot that straddles midnight, with one guard EntryVeto on each side. It must give no false FAIL for D or D+1.
- **S2-R41, R2 flush-window anchor.**
  - The tail floor is the boot's last log line (`scan.last_line_ts_ns`), not its last decision line.
  - Add a test: a boot that logs for hours after its last decision and loses a record just before that decision. The loss is FAIL `stream_record_lost`, not INFO.
- **S2-R42, stub-pin strength restored.**
  - The authority-row check loops over `{*EXPECTED, *W3_PINNED}`.
  - `min_calls == 1` stays wherever no builder raised a floor.
  - The exact-set assertion `found == pinned` is reinstated for the W3 modules.
  - This reverses a weakening introduced at integration.
- **S2-R43.** Split every test file over 800 lines: `test_capture_audit.py`, `test_capture_audit_fill_legs.py` (see S2-R38) and `test_capture_audit_inputs.py`.
- **S2-R44, re-audit fairness.**
  - Days never audited are ordered BEFORE ERROR re-audits. A missing day must never age out.
  - `CAPTURE_AUDIT_ERROR` is sent once per (day, cause set). First check whether the outbox dedupes, and cite where. Re-send only when the cause set changes.
  - Rewriting the HEALTH verdict for the day is fine.
- **S2-R45, PRE_CAPTURE masking.** ERROR wins over the PRE_CAPTURE mask whenever ANY errored leg has a cause outside `HOST_STATE_CAUSES`, not only the first errored leg. Add a test with a host-state ERROR first and a data ERROR second.
- **S2-R46, LOW items.**
  - `_r3_boot` checks the cap before the `last_ts is None` early return.
  - `entry_lines_capped` joins `ERROR_CAUSES`, and the exact-set test is extended.
  - R2 day bucketing: both sides use the same clock for the day cut. Pick `wall_ns`, matching the streams, or prove the log ts equals `wall_ns`. Add a test with a record within 1 ms of midnight.

## Stage 2c review-fix outcome (fix B 541a8426, fix A 9e45eb60 → 11472df5)
- **Fix B.** S2-R28..R33 and S2-R40..R46 are done, with a mutation for each. R46's shared clock is the line's `now_ns`, already pinned equal to `eval_ns` / `wall_ns`. R44 dedupe is done in the audit, because no outbox dedupes.
- **Fix A.** S2-R34..R38 are done. On S2-R39, two pushbacks are ACCEPTED:
  - leg D: the exec store records Breezy's own side, opens BUY and closes SELL (`exec/reports.py:773-800`), so no change;
  - the new causes are finding causes, not `ERROR_CAUSES`, so the model is untouched.
  The `tape_marks` hour filter and the R6 metric were already right; both are now pinned.
- **S2-R47, REJECTED deviation (fix B, S2-R31).**
  - `capture_audit_host.py` restates `subprocess.PIPE` and `DEVNULL` as the literals -1 and -3, so the one-writer and closure lints don't see them. That is the same laundering class as S2-R26.
  - Use `subprocess.PIPE` and `subprocess.DEVNULL`.
  - Make the lints accept them honestly. Either the lint treats these two stdio constants as non-write references (pinned by a test that `subprocess.run` / `Popen` / `os.*` writes are still caught), or `_run_template`'s row explicitly admits them (WIDENED, not relaxed).
  - Delete the pin test of the literal values.
- **S2-R48, PASS fixtures under S2-R36.**
  - The s2c PASS fixtures (`pass_entry_day`, `pass_exit_day`) must carry a node scan consistent with R1–R3: its decisions, a matching funnel row, and the exit fixture's Exit record present in both the replay and the stream.
  - Leg F's no-scan pending stays. Fix the fixtures, never the leg.
- **S2-R47/R48 outcome (5770d198, rebased to 389fb2b2).**
  - The closure lint exempts exactly the two bare stdio-constant references (`STDIO_CONSTANT_REFERENCES`). Unlisted `subprocess.run`, `Popen`, `os.write` and `os.replace` are still caught, and a laundering test is pinned.
  - The PASS fixtures derive their scan, replay and funnel from their own records.
  - **Accepted correction.** R2 does not replay Exit lines (`_REPLAYED_KINDS`). The exit fixture's Exit record therefore lives in the stream only, and its loss is caught by leg D (`exit_record_missing`).
