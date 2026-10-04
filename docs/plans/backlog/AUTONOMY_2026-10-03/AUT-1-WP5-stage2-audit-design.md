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
