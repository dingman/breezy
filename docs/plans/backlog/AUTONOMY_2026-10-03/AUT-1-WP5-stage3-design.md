# AUT-1 WP5 stage 3 design (code-architect draft, 2026-10-04; under peer review)

## Architecture: AUT-1 WP5 stage 3 (heal, live-proof, units, sandbox rows, stage-3 carry-overs)

Base `afb225d0`. This is a read-only design; no file was written. I read everything the brief lists, plus the code: `table.py`, `unit_lint.py`, the `capture_audit*` modules, `capture_closure_lint.py`, `capture_settlement_cli.py` and the live unit links.

### 0. Facts checked on the tree and host (each one drives a decision below)
- **F1. New unit files are inert until linked.** Every live repo unit is linked one file at a time into `~/.config/systemd/user`. Nothing links `breezy-capture-*`, and no bulk-link script exists. A new file in `deploy/systemd/` therefore does nothing until someone runs `systemctl --user link`.
- **F2. Editing an already-linked file is one `daemon-reload` from live.** That covers `breezy-quote-tape.service`, `-rotate.*`, `breezy-studies.slice` and `breezy-study-failed@.service`.
- **F3. The unit lint refuses an `OnFailure=` target that is not in scope** (`unit_lint.py:446-448` `onfailure_scope`). `breezy-autonomy-failed@` (AUT-6) is in no row and in no owned set, so any capture unit carrying the E-7e(f) `OnFailure=` line turns the gate red today. The WP3 precedent is `tests/fixtures/recorder_watchdog/pending_recorder_unit.service`.
- **F4. `BwrapRow` has no E-15 network field.** Nothing in `autonomy_sandbox/` emits `--unshare-net`. The existing non-egress stop-hook row (`table.py:243-250`) has no network declaration.
- **F5. The settlement catalog is already readable in the sandbox.** The catalog base is `~/.local/share/breezy/catalog` (`breezy.env:9`), which sits under the data root that E-7e(c) already re-binds read-only.
  - The settlement write target is `catalog/quote_tape/decisions` (`capture_audit_inputs.py:129` `DECISIONS_REL`).
  - `~/.local/share/breezy/evidence/` does not exist. The wrapper never creates a bind source, so the bind directories must be provisioned first.
- **F6. The studies lock is `/run/user/1000/breezy-studies.lock`.** It exists, and it equals `%t`, which every study script uses first (`LOCK_DIR=${XDG_RUNTIME_DIR}`). Seam B already re-binds it into `E7_STUDIES_LOCK` rows (`run_mounts.py:105-113`).
- **F7. The audit CLI already consumes the bus snapshot first** (`capture_audit_cli.py:78`). It goes stale only because the planned ExecStart wraps the whole process in `flock -w 600`. The reader's stale bound is `budget_s + 60` (B9-R2), so 70 s.
- **F8. `CAPTURE_WATCHDOG_EVIDENCE_GAP` is never sent today.** `leg_w` only computes the gaps (S2-R14), and `_Delivery.send` records acceptance, not a delivered proof.
- **F9. R5 reads `write_drops` by re-opening the whole stream** (`capture_audit_stream_legs.py:169-175`). The heartbeat record already carries `write_drops` (`capture_records.py:175`).
- **F10. The WP0-R9 test name is already used.** `test_boot_count_matches_by_instance_id_not_time_window` exists for the node census (`test_capture_node_log.py:605`). Stage 3 adds the recorder/heal counterpart under a new name.
- **F11. `decisions_retention.py:76` only gzips `offer_tape_*` and `diagnostics_summary_*`.** `settlement_*` and `fq_funnel_*` are already safe; S2-R13 only needs that pinned.
- **F12. E-14, E-23 and E-24 are registry and resolver errata, and none applies here.** The only constraint they put on stage 3: no new module may import `breezy.persistence.autonomy.resolver` (A8c-R2 import-linter contract).

### 1. Design decisions (each cites what it reuses)
- **D1. Unit files are authored now as fixtures and promoted to `deploy/systemd/` only in the AUT-6 hookup commit.**
  - Where: `tests/fixtures/capture_units/*.service|*.timer`, following the WP3 `pending_recorder_unit.service` precedent.
  - Why: F3 blocks them at the lint, and F1 makes promotion itself harmless.
  - Stage 3 edits no linked file (F2). Activation is a separate step (§8).
- **D2. S2-R8 is resolved with an in-process studies flock, taken after the snapshot is consumed.**
  - The audit row sets `studies_lock=True` with `E7_STUDIES_LOCK`, reusing seam B's re-bind (F6) and the lint's exact `TOUCH_LINE` (`unit_lint.py:50`). ExecStart is `timeout -k 5 1490 → wrapper` with no `flock`.
  - `main` does three things in order:
    1. consumes the snapshot;
    2. runs `launch_window_guard` (600 + 1500, unchanged);
    3. opens the lock with `O_RDONLY|O_NOFOLLOW|O_CLOEXEC` and polls `flock(LOCK_EX|LOCK_NB)` against a 600 s monotonic deadline (`lock_timeout` → exit 0 deferral, logged).
  - This satisfies E-7a rule 1's "pre-created and opened O_RDONLY" lock alternative. No ARCH-0 code changes.
  - Rejected alternatives:
    - drop the lock: studies run at 10–24 GB, so it would risk OOM contention;
    - bus read after the lock: impossible, because bus reads exist only as unsandboxed `ExecStartPre` (E-7e(h));
    - widen B9-R2: that bound is ARCH-0's.
  - Needs ruling **R-1**: E-7e(f)'s AUT-1 bullet "l.881 `flock -w %t/breezy-studies.lock`" becomes "in-process".
- **D3. Add the E-15 network field.**
  - Shape: `BwrapRow.network: Literal["none","egress"]`, required, with no default.
  - `"none"` emits `--unshare-net` in `bwrap.py`.
  - `validate_table` refuses `network=="none" and resolves_dns`.
  - Assignments: every AUT-1 row (the three new rows plus the stop hook) is `"none"`. Seam B's selftest rows declare their current behaviour (`"egress"` for the DNS row, `"none"` for the other two).
  - E-15 says the field lands in the first consumer WP that adds a non-egress row, and this is that WP. It touches seam-B-owned files, so a SEC review is mandatory. **R-4** confirms the ownership carve-out.
- **D4. No `evidence/alerts` bind and no egress until AUT-6.**
  - `deliver_with_proof` does not exist yet, and the CLIs use `_undeliverable_offer`.
  - One later "AUT-6 hookup" commit does all of the following together:
    - flips each row to `network="egress"` and `resolves_dns=True`;
    - adds the `evidence/alerts` bind;
    - injects the outbox;
    - promotes the units;
    - activates the pending contract tests.
  - This is least privilege, and it holds the brief's "no egress beyond what the plan names" literally. It deviates from the §3.13 bind lists, so it needs ruling **R-2**.
- **D5. The settlement catalog read-only bind is met by the data-root re-bind (F5).**
  - The unit passes `--catalog-base %h/.local/share/breezy/catalog` explicitly, because `~` is a tmpfs and `breezy.env` is invisible in the sandbox.
  - The write bind is `catalog/quote_tape/decisions` only.
  - A test pins that the catalog base resolves under the data root and is never a writable bind.
- **D6. Heal is a pure planner plus thin I/O, run as a fourth audit duty** in `_run_duties`, in its own `try` (H7).
  - Reuses:
    - `run_journal(RECORDER_JOURNAL_ARGV)` and `parse_recorder_journal`, read once over [today−9 d, now];
    - the `_stall_records` reader;
    - `single_read.write_once`;
    - `capture_alerts.healed_event` and `abandoned_event`;
    - `audit_from_wire`.
  - **Confirmation (§3.10.3).**
    - A later invocation is matched to the kill by the `instance_id` logged in its own journal lines, then to `catalog/quote_tape/polymarket_us/live/<instance_id>/config.json`. It is never matched by time window (WP0-R5). `config.json` mtime is an ordering check only.
    - Growth means the newest entry mtime minus the `config.json` mtime is at least 900 s.
    - There is no further `UNIT_RESULT=watchdog` within 1800 s.
    - `MESSAGE` may be a byte array with ANSI codes (the WP3 note), so it is decoded.
  - **Heal records.**
    - The file name comes from the kill's journal `ts_ns`, and the body is deterministic, so a rerun is `EXISTS_EQUAL`; `EXISTS_DIFFERENT` makes the duty fail.
    - A kill with no stall record has no sha, so no heal is written; leg W carries it instead.
    - `injected=true` is set from `evidence/capture/drill/<date>.json` when present. Heal pins that format, and WP9 conforms to it.
  - **NBP heal records** (`decided_by:"nbm_quantile_actor"`) are read using the WP4 `2608599c` format, pinned as a literal fixture (S2-R2 precedent).
  - **Delivery truth** comes from a `DeliveryLedger` Protocol (`delivered(event, first_date, last_date) -> bool`). Its default, `NoDeliveryLedger`, always returns False, so it fails toward re-sending. AUT-6 supplies the real one.
- **D7. Leg-W sending and re-sending live in the same heal duty.**
  - It reads `watchdog_evidence_gaps` from the last 8 days' audit files and re-checks the evidence now (stall record, notifier marker).
  - While a gap stands and is undelivered, it sends `CAPTURE_WATCHDOG_EVIDENCE_GAP`. That covers both the first send and the daily re-sends.
  - After `HEAL_ALERT_RETRY_DAYS`, it follows the §3.11.6 abandon order.
  - The gap abandon key is `sha256("breezy-quote-tape.service\0"+InvocationID)`, so the event is `CAPTURE_HEAL_ALERT_ABANDONED_<sha>` and the marker is `heal_alert_abandoned/gap_<sha>.json`. The plan leaves this unspecified, so it needs ruling **R-3**.
- **D8. Live proof is a pure roll-up of §6 plus the §3.11.5 dead-man checks, and a CLI.**
  - Reuses `audit_from_wire`, `LIVE_PROOF_NAME_RE`, `families_by_construction` and `launch_window_guard`.
  - Output: `live_proof_<family>_<asof>.json`, written by `single_read.replace_atomic` at mode 0444, because both the `OnSuccess=` run and the 14:35 fallback can run on the same date.
- **D9. S2-R20.**
  - `HeartbeatSummary` gains `write_drops`, filled in at `capture_audit_inputs.py:396`.
  - `leg_r5` reads the newest summary and deletes `_write_drops`, so no full stream read remains.
  - If `StreamSummary` is in the scan cache, bump the codec (`scan-cache/3`).
- **D10. Lint hardening (S2-R33 note).** An argv-matched `subprocess` call is admitted only if:
  - it has no `*`/`**` splat;
  - its keywords are a subset of a closed `ALLOWED_SUBPROCESS_KWARGS`, which the builder sets to exactly the keywords the three `_run_template` sites use today (`stdout`, `stderr`, plus any already present), with values from `STDIO_CONSTANT_REFERENCES` or literals.
  - `shell`, `env`, `executable`, `cwd`, `preexec_fn`, `pass_fds`, `user`, `group`, `extra_groups`, `umask` and `process_group` are each refused, and each gets a mutation.
- **D11. S2-R19 (leg N) before AUT-6.**
  - One contract module holds both key shapes:
    - `<unit>__<InvocationID>.delivered.json`;
    - `NBP_CYCLE_MISSED__<cycle_ns>`, already the constant `NBP_MISSED_PROOF_UNIT` at `stream_legs:65`.
  - Fixture tests pin the reader for both shapes.
  - An uncollected pending file asserts that AUT-6's real writer emits those keys (S2-R11 / WP2-R1 precedent).
  - The AUT-6 WP brief is amended to match.
  - Until then, leg N and leg W fail closed (no marker means a gap).
- **D12. Units are oneshot `TimeoutStartSec` units (never `RuntimeMaxSec`), timers are non-`Persistent`, with `UMask=0077` and the exact `/home/jon/breezy/.venv/bin/python3 -I -m …` interpreter (V10 form).** E-9 sums assume the default 60 s accuracy and 5 s per pre line:

| Unit | OnCalendar | Pre lines | ExecStart | TimeoutStartSec | Memory | Latest end |
|---|---|---|---|---|---|---|
| `breezy-capture-settlement` | 13:35 | install -d | `timeout -k 5 290` → `flock -w 30 %t/breezy-capture-settlement.lock` → wrapper | 300 | `MemoryMax=512M` (WP5-R2) | 13:41:05 |
| `breezy-capture-audit` (`Slice=breezy-studies.slice`) | 13:50 | install -d, touch, bus snapshot (B=10, so 15 s) | `timeout -k 5 1490` → wrapper (in-process lock) | 1500 | `MemoryHigh=768M`, `MemoryMax=1G` | 14:16:30 |
| `breezy-capture-live-proof` | audit `OnSuccess=` + fallback 14:35 | install -d | `timeout -k 5 290` → `flock -w 30 %t/…live-proof.lock` → wrapper | 300 | `MemoryMax=256M` | 14:41:05 |

None of these meets [16:30Z, 17:10Z).

The audit's `AUDIT_WORK_BUDGET_S` becomes `min(840, start + 1490 − 60 − now)`, measured at lock acquisition. One pure function derives it, and a test reads the unit literal. **R-5** restates §3.13 (512M, the end times above).

**Rows** (`network="none"`, `resolves_dns=False`):
- settlement: `catalog/quote_tape/decisions`;
- audit: `evidence/capture/audit`, `evidence/capture/heal`, `evidence/capture/heal_alert_abandoned`, `derived/verdicts`, `cache/capture_audit` (E-8 snapshot and scan cache, `AUDIT_CACHE_DIR`), and `cache/capture_audit_bus` as `bus_snapshot_bind` (S2-R16, distinct and not nested). It also carries the two `AUDIT_BUS_READS` named `AUDIT_BUS_READ_NAMES`, and `studies_lock`;
- live-proof: `evidence/capture/live_proof`.

### 2. Acceptance criteria
1. `validate_table` accepts the three new rows. Every row in the table declares `network`, and a missing field, or `none` together with `resolves_dns`, raises `TableError`.
2. `argv_for` emits `--unshare-net` exactly for `network="none"` rows. A phase-2 namespace test proves that a `none` row cannot connect to `127.0.0.53:53` or to an abstract socket, while an `egress` row can resolve. `BWRAP_HOST_EXPECTED_TESTS` is widened in the same commit.
3. Every fixture unit passes `lint_units` against the real table plus a test-only stand-in `breezy-autonomy-failed@` row. The same fixtures against the real table alone produce exactly `onfailure_scope` errors, which proves the blocker is AUT-6 only.
4. The §3.13 calendar tests pass over the fixture directory: no launch-window overlap, `TimeoutStartSec` not `RuntimeMaxSec`, no `Persistent`, every unit and `OnFailure=` target wrapped, and the E-9 sums equal the table above.
5. The audit consumes the snapshot before the in-process lock. A 600 s lock wait no longer produces `bus_snapshot_stale`. A lock not acquired by the deadline defers with exit 0 and writes nothing.
6. Heal confirms a kill only when all three §3.10.3 conditions hold, matching by `instance_id`, never by a time window.
7. Heal records are write-once and idempotent across runs. The drill file sets `injected=true`.
8. Every unmatched heal (the audit's and the NBP actor's) is re-sent daily for 8 days. The abandon marker is written only after `delivered=true`. Heals older than 30 days produce a `CAPTURE_HEAL_UNABANDONED` line and `heal_alert_unabandoned_count`.
9. Each standing leg-W gap is sent on its first run and re-sent daily until delivered, then follows the abandon order. A gap whose evidence later appears is not re-sent.
10. The live-proof roll-up implements §6: qualifying days, 7 days and at least 5 real fills, and a heal with a delivered `CAPTURE_HEALED_<sha>`.
11. Live proof sends `CAPTURE_AUDIT_DEADMAN` and `CAPTURE_AUDIT_FILE_MISSING`, each in its own `try`, and exits 1 on a failed delivery.
12. R5 reads `write_drops` from `HeartbeatSummary` without calling `boot.stream()`.
13. The closure lint refuses every listed keyword and splat on an argv-matched call. Every pre-existing lint test passes unedited.
14. Leg N and leg W read both AUT-6 key shapes from fixtures. The pending AUT-6 contract file fails when run by path.
15. `settlement_` and `fq_funnel_` names never match the retention gzip regexes.
16. The heal and live-proof closures import no `breezy.adapters.*`, no `httpx`, no `breezy.ingest` and no `…autonomy.resolver`.
17. No file under `deploy/systemd/` changes, and no linked unit changes (reviewer checks `git diff --stat`).
18. The full gate gives `EXIT=0`. `lint-imports` prints "N kept, 0 broken". The exec client sha is unchanged, and the firewall and operator-control tests are unedited.

### 3. File-by-file plan (N = new, E = exists)
| File | | Owner | Change |
|---|---|---|---|
| `src/breezy/analysis/capture_heal.py` | N | S1 | Pure: `confirm_heals`, `plan_resends`, `plan_abandons`, `standing_gaps`, `DeliveryLedger`, `NoDeliveryLedger` |
| `src/breezy/analysis/capture_heal_io.py` | N | S1 | Journal window, live-dir growth stat, heal and drill record read/write, `run_heal_duty(data_root, family, today, now_ns, delivery, ledger)` |
| `src/breezy/analysis/capture_live_proof.py` | N | S2 | Pure roll-up and dead-man checks |
| `src/breezy/analysis/capture_live_proof_cli.py` | N | S2 | `main`, launch-window guard, `replace_atomic` |
| `src/breezy/analysis/capture_aut6_contract.py` | N | S2 | Notifier key shapes for leg W and leg N (D11) |
| `src/breezy/analysis/capture_audit_input_types.py` | E | S2 | `HeartbeatSummary.write_drops` |
| `src/breezy/analysis/capture_audit_inputs.py` | E | S2 | Fill `write_drops`; the marker reader imports the D11 shapes |
| `src/breezy/analysis/capture_audit_stream_legs.py` | E | S2 | R5 reads the summary; `NBP_MISSED_PROOF_UNIT` moves to the contract module |
| `tests/support/capture_closure_lint.py` | E | 3a (rows), then S2 (engine) | Rows pre-declared at `min_calls=1`; D10 hardening |
| `src/breezy/runtime/autonomy_sandbox/table.py` | E | S3 | `network` field, validation, three rows |
| `src/breezy/runtime/autonomy_sandbox/bwrap.py` | E | S3 | `--unshare-net` emission |
| `src/breezy/analysis/capture_audit_cli.py` | E | S3 | In-process lock, budget derivation (D2) |
| `src/breezy/analysis/capture_audit.py` | E | 3a | `("heal", …)` duty that calls the `capture_heal_io` stub |
| `tests/fixtures/capture_units/breezy-capture-{settlement,audit,live-proof}.{service,timer}` | N | S3 | D1 and D12 text |
| `tests/unit/autonomy_writer_table.py` | E | 3a | One-writer rows for heal and live-proof |

Test files:
- S1: `tests/unit/test_capture_heal.py` (N), `test_capture_heal_resend.py` (N).
- S2: `test_capture_live_proof.py` (N), `test_capture_live_proof_cli.py` (N), `tests/unit/autonomy/pending_aut6_notifier_proof_contract.py` (N, uncollected), plus edits to `test_capture_audit_stream_legs.py` and `test_capture_closure_slots.py`.
- S3: `tests/unit/test_capture_units.py` (E, extended), `tests/unit/test_autonomy_sandbox_table.py` (E), a new phase-2 file in the bwrap-host registry (outside `tests/unit` and `tests/contract`, per E-7d), and `test_capture_audit_cli.py` (E).

### 4. Tests and their RED expectations
RED is a collection `ImportError` for new modules and an assertion failure on existing ones, unless stated otherwise.

**S1** (`test_capture_heal.py`, `test_capture_heal_resend.py`):
- `test_watchdog_kill_followed_by_streaming_instance_is_healed` and `test_kill_followed_by_second_kill_within_30min_is_not_healed`: ImportError.
- `test_recorder_heal_matches_restart_by_instance_id_not_time_window` (F10; the real 41.2 s pair): fails against a time-window mutant.
- `test_instance_live_dir_grew_under_15min_is_not_healed`.
- `test_heal_record_rerun_is_exists_equal`.
- `test_drill_heal_marked_injected`.
- `test_kill_without_stall_record_writes_no_heal`.
- `test_journal_message_byte_array_with_ansi_is_decoded`.
- `test_nbp_actor_heal_record_fixture_from_wp4_parses`.
- `test_heal_alert_resent_daily_until_delivered`.
- `test_abandoned_marker_written_only_after_delivered_true_proof`.
- `test_unmarked_heal_older_than_30_days_counts_unabandoned`.
- `test_evidence_gap_alert_resent_daily_until_delivered`.
- `test_evidence_gap_sent_on_first_run`: currently nothing sends it (F8).
- `test_gap_with_late_evidence_is_not_resent`.
- `test_gap_abandon_key_is_sha_of_unit_and_invocation`.
- `test_heal_duty_failure_is_isolated` (extends the H7 duty pattern).

**S2:**
- `test_watchdog_heal_with_delivered_alert_satisfies_stall_leg`, plus the r8 roll-up set re-targeted:
  - `test_seven_pass_days_and_five_fills_is_proven`;
  - `test_fail_or_error_breaks_the_window`;
  - `test_pre_capture_and_partial_epoch_never_count`;
  - `test_canary_only_day_counts_zero_fills`;
  - `test_lost_in_flush_window_day_still_qualifies`.
- `test_live_proof_alerts_audit_deadman_and_missing_files`.
- `test_live_proof_failed_delivery_exits_nonzero`.
- `test_live_proof_cli_defers_inside_launch_window`.
- `test_live_proof_closure_has_no_venue_adapter_module` (extends `test_capture_unit_closures_have_no_venue_adapter_module`).
- `test_r5_reads_write_drops_from_heartbeat_summary_without_stream_read`: RED via a `boot.stream` spy.
- `test_argv_call_with_shell_kwarg_is_refused` and siblings, one per keyword plus splat: RED, the lint passes them today.
- `test_existing_journal_templates_still_admitted`.
- `test_leg_n_reads_nbp_cycle_missed_marker_shape`.
- `test_leg_w_and_leg_n_key_shapes_single_source`.
- `test_retention_never_compresses_settlement_or_funnel_files`.

**S3:**
- `test_unshare_net_emitted_only_for_network_none` and `test_network_none_with_resolves_dns_refused`: ImportError or TypeError, since the field is absent.
- `test_every_row_declares_network`.
- Phase 2: `test_network_none_row_cannot_reach_dns_stub`, `test_egress_row_resolves`.
- `test_capture_rows_bind_exactly_planned_dirs`.
- `test_settlement_catalog_base_is_under_data_root_not_a_bind`.
- `test_audit_bus_reads_equal_audit_bus_read_names`.
- `tests/unit/test_capture_units.py`:
  - `::test_no_unit_overlaps_launch_window`;
  - `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`;
  - `::test_no_capture_timer_is_persistent`;
  - `::test_every_capture_unit_and_onfailure_target_runs_through_bwrap_wrapper` (with the stand-in AUT-6 row);
  - `::test_capture_units_fail_lint_only_on_aut6_scope` (AC 3);
  - `::test_e9_latest_end_matches_table`;
  - `::test_audit_work_budget_derives_from_unit_timeout`.
- `test_capture_audit_cli.py`:
  - `::test_snapshot_consumed_before_studies_lock_wait`;
  - `::test_lock_wait_600s_does_not_stale_snapshot`;
  - `::test_lock_not_acquired_defers_without_writes`.

Every new test needs a named mutation that kills it.

### 5. Blocked items
| Item | Blocked by |
|---|---|
| Promoting the unit files to `deploy/systemd/`; `OnFailure=` lint scope (F3) | AUT-6 (`breezy-autonomy-failed@` row and unit) |
| Real delivery: outbox injection, the egress flip, the `evidence/alerts` bind, the real `DeliveryLedger`, the notifier markers, the pending contract tests going GREEN, AUT-5 recording `delivered=true` | AUT-6 |
| Timer activation (S2-R9: activation is gated on AUT-6's notifier) | AUT-6, plus the WP0-R9 V-11 re-measure over 14 FQ days on or after 2026-10-15 (blocks WP5 activation) |
| Any family to audit or prove (epoch file), the `CAPTURE_EPOCH_START` line, live NBP heal records (WP4 merges in WP8's train), live-proof accrual | WP8 |
| Leg W and heal on real kills (recorder `Type=notify` and the stop-hook unit edit) | WP3 step 2 (itself AUT-6-gated) |
| Real drill `injected` evidence | WP9 |
| Nothing in stage 3 | AUT-4 (only WP6 waits on it) |

**What stage 3 can do for S2-R19 before AUT-6:** everything in D11. That is the single-source key constants, the fixture tests for both shapes, the uncollected pending contract file, and the AUT-6 brief amendment. Leg N and leg W fail closed in the meantime.

### 6. Build streams (blind, disjoint)
- **3a, serial (one builder, lands first).**
  - Stubs (raising `NotImplementedError`) for the four new analysis modules.
  - `AUT1_WRITE_AUTHORITY` rows at `min_calls=1`, grouped with separators.
  - One-writer rows.
  - The heal duty hook in `capture_audit.py`.
  - Owned files: `capture_audit.py`, `autonomy_writer_table.py`, and the row section of `capture_closure_lint.py`.
- **S1, heal and leg-W re-send:** `capture_heal{,_io}.py` and their two test files. It may import the host, inputs, wire, `capture_alerts` and `single_read`, but edits none of them.
- **S2, live proof and audit hardening:**
  - `capture_live_proof{,_cli}.py`, `capture_aut6_contract.py`;
  - `capture_audit_input_types.py`, `capture_audit_inputs.py`, `capture_audit_stream_legs.py`;
  - the engine section of `tests/support/capture_closure_lint.py`;
  - its tests, the pending file, and the retention pin.
- **S3, sandbox and units:**
  - `table.py`, `bwrap.py`, `capture_audit_cli.py`;
  - `tests/fixtures/capture_units/*`, `test_capture_units.py`, `test_autonomy_sandbox_table.py`, the phase-2 file;
  - the `BWRAP_HOST_*` pins (`tests/support/bwrap_host_phase.py`), owned by S3 alone.
- **3c, serial integration.**
  1. Merge S3, then S2, then S1. S1 needs S2's contract module only at integration, through 3a's stub import path.
  2. Builders raise their own `min_calls` floors, and the exact-set pins are restored (S2-R42).
  3. Run the full gate and `lint-imports`.
  4. Mutation table.
  5. SEC review (mandatory for `bwrap.py` and `table.py`) and python review.
- **Shared-file owners:**

| File | Owner |
|---|---|
| `capture_audit.py` | 3a |
| `capture_closure_lint.py` | 3a (rows), then S2 (engine) |
| `table.py`, `bwrap.py` | S3 |
| `capture_audit_input_types.py` | S2 |
| `capture_alerts.py` | Nobody: no edit needed, every event already exists |

- Every brief carries:
  - the hard invariants;
  - `PYTHONPATH=<worktree>/src`;
  - "format only your files";
  - the exec-pin and firewall guards in each focused gate;
  - worktrees fast-forwarded onto `feat/data-capture-and-risk` first.

### 7. Risk register
| # | Risk | Severity | Control |
|---|---|---|---|
| K1 | An edit to a linked unit goes live at any agent's `daemon-reload` (F2) | HIGH | Stage 3 edits no linked file (AC 17). Units live as fixtures. Activation preflight checks `NeedDaemonReload=no` on every `breezy-*`. |
| K2 | `systemctl --user link/enable` reloads implicitly and picks up another agent's pending edits | HIGH | Activation runs only from a clean primary tree, after the K1 preflight, outside [15:55Z, 17:10Z), with a one-line heads-up. |
| K3 | A committed unit pages through a missing notifier | MED | The lint refuses it (F3). Promotion happens only alongside AUT-6. |
| K4 | NO-SEND / egress: an AUT-1 row reaches the network | HIGH | `network="none"` → `--unshare-net` (D3, AC 2). No adapter, `httpx` or `ingest` in the closure (AC 16). The firewall and exec-pin tests stay unedited. The egress flip happens only in the AUT-6 hookup, for alert delivery only. |
| K5 | The `--unshare-net` change regresses seam B's selftest rows | MED | Each row declares its current behaviour. Phase-2 tests. SEC review. Real-host V2/V10-form re-run. |
| K6 | The in-process lock deviates from E-7e(f) | MED | Ruling R-1. Same lock file and same semantics. Tests AC 5. |
| K7 | Heal is mis-attributed across fast restarts | MED | Matching by `instance_id` (WP0-R5); the 41.2 s fixture. |
| K8 | Before AUT-6, the default ledger re-sends forever and exits 1 daily | LOW | Units are inactive until AUT-6, by design. Abandon after 8 days. |
| K9 | `open_station_catalog`'s `mkdir(exist_ok)` on a read-only mount | LOW | V-step H6; a test with a read-only base. |
| K10 | Memory: cold audit run measured at 710 MB against `MemoryHigh` 768M | MED | Steady state is warm (6.8 s). Studies slice. One heavy job at a time. |
| K11 | Operator-reserved controls, live enablement, the permit and NO-SEND | — | Not named, read or touched by any stage-3 file. Pinned by the unedited `test_operator_control_assignment_scan.py`. |

### 8. First host verification (outside 16:30–17:10Z, no `daemon-reload`, no unit files)
1. Run `date -u`. List `systemctl --user show -p NeedDaemonReload --value` for the linked `breezy-*` units, read-only. Confirm `find ~/.config/systemd/user -lname '*breezy-capture*'` is empty.
2. Provision the binds, following seam B V1: `install -d -m 0700 ~/.local/share/breezy/{evidence/capture/{audit,heal,heal_alert_abandoned,live_proof},cache/capture_audit,cache/capture_audit_bus}`. Verify that `catalog/quote_tape/decisions` and `derived/verdicts` are owned by the uid with no 0o022 bits.
3. Run the selftest for each new row in the V10 form: `systemd-run --user --wait --pipe --collect --unit=<row> -p TimeoutStartSec=120 deploy/systemd/breezy-autonomy-bwrap <row> .venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli`. Expect `ok:true`, and for `none` rows a DNS connect giving `ENETUNREACH`.
4. In the audit row, run `/usr/bin/journalctl --user -u breezy-quote-tape.service -o json -n 5`. This proves the journal is readable under the final mount set plus `--unshare-net`. Also confirm journald retention covers at least 10 days.
5. Run the bus handoff with the seam B V17 transient method for `breezy-capture-audit`, then the audit CLI with no `--family-id`. Expect "no family to audit", exit 0, no files written, and the snapshot consumed.
6. Repeat step 5 while another shell holds `%t/breezy-studies.lock` for 120 s. Expect no `bus_snapshot_stale`. Do this only in a quiet window.
7. In the settlement row, `-I -c 'import breezy.analysis.capture_settlement_cli'`, then run `open_station_catalog` on an existing station against the read-only base. Expect no `EROFS`.
8. Run no real settlement or audit `--family-id` writes until activation; use the stage-2c overlay for any end-to-end run.

### 9. Rulings requested from the coordinator
- **R-1:** the in-process studies lock (D2), amending E-7e(f)'s AUT-1 bullet for l.881.
- **R-2:** alerts bind and egress deferred to the AUT-6 hookup (D4), amending the §3.13 bind lists.
- **R-3:** the leg-W gap abandon key and marker name (D7).
- **R-4:** the E-15 field lands in AUT-1 stage 3, touching seam-B-owned `table.py` and `bwrap.py` under SEC review (D3).
- **R-5:** settlement `MemoryMax=512M` and the restated latest ends 13:41:05, 14:16:30 and 14:41:05 (D12).

Key paths: `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/{table,bwrap,unit_lint,run_mounts}.py`, `/home/jon/breezy/src/breezy/analysis/capture_audit{,_cli,_host,_inputs,_input_types,_stream_legs}.py`, `/home/jon/breezy/src/breezy/analysis/capture_settlement_cli.py`, `/home/jon/breezy/tests/support/capture_closure_lint.py`, `/home/jon/breezy/tests/fixtures/recorder_watchdog/pending_recorder_unit.service`, `/home/jon/breezy/scripts/ops/decisions_retention.py`, `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-WP5-stage2-audit-design.md`.

---

## Round-1 peer review resolution (coordinator, 2026-10-04; ARCH, SEC and python all REQUEST_CHANGES; binding on revision r2)

### Merged-code defects found by review (fix in 3a, RED first)
- **S3-R1, invocation id.**
  - `parse_recorder_journal` (`capture_audit_host.py:305`) does not read `USER_INVOCATION_ID`. That is the only id carried on the host's real `UNIT_RESULT` line.
  - So a real kill parses with `invocation_id=""`, and stage-2 leg W is affected as well.
  - Accept `USER_INVOCATION_ID` in the parser, and add a fixture copied from the real kill line.
  - Never leave an empty id silently: an empty id is a parse error for that entry.
- **S3-R2, alert severities.**
  - `_Delivery.send` looks up `CAPTURE_ALERT_SEVERITIES[event]` and raises `KeyError` for `CAPTURE_HEALED_<sha>` and `CAPTURE_HEAL_ALERT_ABANDONED_<sha>`.
  - Add `severity_for(event)` in `capture_alerts`, built on `is_capture_alert_event`. HEALED is INFO, as plan §3.16 requires; ABANDONED is CRITICAL. `send` uses it.
  - The heal I/O receives an injected `Sender` Protocol and never imports `_Delivery`.
  - The real names are `heal_alert_event` and `abandoned_alert_event`.

### Heal (D6) corrections
- **S3-R3, journal reads.**
  - Read the journal one day at a time over the last 3 days. A 9-day window is 484 MB on this host, against a 256 MiB cap.
  - Write-once records make the older days idempotent.
  - Leg-W re-sends read audit files and evidence, never the journal.
- **S3-R4, confirmation time.**
  - `confirm_heals(now_ns)` requires `now ≥ restart + 1800 s` and growth ≥ 900 s.
  - Add boundary tests at 899/900 s and 1799/1800 s, plus a test that a restart younger than 30 minutes is unconfirmed.
- **S3-R5, matching the restart.**
  - S1 writes its own `instance_id` line parser: `MESSAGE` may be a byte array carrying ANSI codes and a timestamp prefix. The fixture uses real captured lines.
  - The restart that matches is the FIRST later invocation that logs an `instance_id` and has a `config.json`.
  - The growth stat excludes the `.converted-*` markers.
- **S3-R6, `injected`.** `injected` is not part of the write-once body. It is a sidecar, or is read at first write only, so a drill file that appears later can never cause `EXISTS_DIFFERENT`.
- **S3-R7, re-send rules (plan §3.11.6).** Re-sends carry `attempt_kind="retry"`, keep the 600 s minimum age for node records, and apply the 30-day age-out to gaps as well. Make these part of AC 8 and AC 9.
- **S3-R8, one heal run per audit run.**
  - Heal runs ONCE per audit run, from `_main` after the family loop, never once per family.
  - The whole run has one absolute deadline, with no per-family `DEADLINE.reset` re-arm.
  - The heal duty is time-boxed. Below a floor it defers and is not counted as a failure.
- **S3-R9, delivery ledger.** Replace the `DeliveryLedger` Protocol with D11-style treatment:
  - a constant for the delivery-record shape;
  - a fixture reader that reuses the single-read pattern of `_notifier_proofs`;
  - an uncollected pending contract.
  Until AUT-6 exists the ledger fails closed: not delivered, so the alert is re-sent.

### Sandbox (D3) corrections
- **S3-R10, no harness test of isolation.** The phase-2 harness inserts `--unshare-net` into every child (`bwrap_harness.py:163`), so it cannot test isolation, and it MUST NOT be weakened.
  - Prove argv emission in phase 1.
  - Add a seam-B self-probe check: on `network="none"` rows a connect to `198.51.100.7:80` gives `ENETUNREACH`, and `/proc/net/dev` shows only `lo`. Prove it in a host V-step through the real wrapper, outside the harness.
  - Drop the egress-resolve test.
  - Correct the expectation for `127.0.0.53:53` inside a fresh netns: it is `ECONNREFUSED`, not `ENETUNREACH`.
- **S3-R11, seam B row values.**
  - Seam B's existing rows declare their TRUE current behaviour, `network="egress"`.
  - Tightening any of them is out of scope.
  - Emission fails closed: the flag is added unless `network == "egress"` exactly, and `validate_table` rejects any other value.
  - List every test edit forced by the required field: `test_autonomy_bwrap_argv.py`, `test_autonomy_units_wrapped.py` (6 constructors), `capture_audit_w3_fixtures.py` and `test_autonomy_aut1_stop_hook_row.py`. S3 owns all of them.
- **S3-R12, fallback rows.** `validate_table` refuses a `network="none"` row that is in `NOTIFIER_FALLBACK_ROWS`, because the unwrapped exec would drop the flag. Add a test.
- **S3-R13, lock proof.**
  - A phase-2 test opens the studies lock `O_RDONLY|O_NOFOLLOW` inside an `E7_STUDIES_LOCK` row and takes `LOCK_EX|LOCK_NB`.
  - It succeeds alone, and gives `EWOULDBLOCK` while the host holds the lock.
  - The audit never creates the lock.
  - The helper lives where AUT-6's `IN_PROCESS_STUDIES_LOCK_UNITS` can reuse it.
- **S3-R14, lock timeout.**
  - A lock timeout exits 1 and pages through `OnFailure=`, matching the plan's `flock -w 600` semantics.
  - Only a launch-window deferral exits 0.

### Lint (D10) corrections
- **S3-R15.**
  - `ALLOWED_SUBPROCESS_KWARGS = {stdout, stderr}` exactly, and every other keyword is refused generically. Add mutations for a representative set, including `shell`, `env`, `executable`, `cwd`, `stdin`, `input`, `close_fds`, `preexec_fn` and `start_new_session`.
  - `len(call.args) == 1`, so positional extras are refused.
  - Starred elements inside the argv list are refused.
  - The aliased and `from subprocess import Popen` forms are refused.
  - Pin argv[0] to `/usr/bin/journalctl` in the rows and in the calls.
- **S3-R16, residual write risk.**
  - Record the residual risk on the settlement write bind: it shares `catalog/quote_tape/decisions` with the live node.
  - Pin that the settlement closure writes only `settlement_*` names, and only through `write_once` (O_EXCL).
  - Pin that the audit and live-proof write only capture-family verdicts into `derived/verdicts`.
  - Pin that the new modules never reference exec-store, permit or `state/` path segments.

### Ownership, staging and hookup
- **S3-R17, what 3a owns.**
  - S3-R1 and S3-R2;
  - the `test_capture_audit_stubs.py` `EXPECTED` table for all FIVE new modules, including `capture_aut6_contract`, with its constant names frozen;
  - the `run_audit(..., deadline_ns)` seam and the single absolute deadline;
  - the closure-lint rows with `"*"` scopes for the heal and live-proof modules, which their builders narrow;
  - the one-writer rows.
- **S3-R18, heal-duty wiring.** The heal duty is NOT wired in 3a: a stub would fail every run. 3c wires it, after S1 merges. This keeps S2-R42's stub-raises pin.
- **S3-R19, the AUT-6 hookup.**
  - The hookup is **AUT-1 WP5 stage 4 (hookup)**. Its checklist goes into the build rulings:
    - unit promotion;
    - `AUTONOMY_OWNED_UNITS`;
    - the alerts bind;
    - outbox injection;
    - the real delivery ledger;
    - pending tests to GREEN;
    - SEC review;
    - the E-7e(f) `resolves_dns` amendment.
  - Network: the audit and heal rows stay `none` and use spool-and-send. A separate AUT-6 egress unit sends from `evidence/alerts`. If a row is ever flipped to `egress`, that flip needs its own SEC review and an exfiltration test.
  - Ownership: WP5-R2 said WP8 injects the outbox. Stage 4 now owns that. It runs after AUT-6, and before or inside WP8's train, whichever comes first.
- **S3-R20, D9.**
  - There is NO codec bump: `HeartbeatSummary` and `StreamSummary` are not in `_CACHE_TYPES`. Pin that with a test.
  - `write_drops` has no silent default.
  - Re-point `test_nonzero_write_drops_fails_stream_write_dropped` at the summary explicitly. This is a re-target, not a weakening.
- **S3-R21, live proof (D8) is complete against §6.** It covers:
  - pairing a watchdog heal with its stall record, its `UNIT_RESULT` and its AUT-6 marker;
  - the NBP-heal alternative;
  - the HEALED delivered-date window: heal date to +8 days;
  - a stale INCONCLUSIVE breaking the run;
  - DEADMAN and FILE_MISSING deduped per `asof` across the `OnSuccess=` run and the 14:35 fallback.
- **S3-R22, rulings R-1..R-5.**
  - **R-1:** ACCEPTED, with S3-R13 and S3-R14.
  - **R-2:** ACCEPTED as amended by S3-R19.
  - **R-3:** ACCEPTED. Update the §3.16 row, and mark gaps in `detail`.
  - **R-4:** ACCEPTED, with S3-R10 to S3-R12. SEC review is mandatory.
  - **R-5:** ACCEPTED for 512M. Restate the own-lock memory sum (896M against ARCH §5.2's 4G), and recompute the latest end times after S3-R8.
- **S3-R23, mechanics.**
  - Every file stays ≤ 800 lines. S3's network tests go in a new file. S2's edit to `capture_audit_inputs.py` is net ≤ +30 lines, or extracts code.
  - Each RED expectation is restated against the post-3a stubs.
  - The mutation table lists the named mutants from the python review, finding 8.
  - The WP4 heal format is pinned as a literal fixture copied from `2608599c`.
  - The 3c checklist runs `git diff --stat -- deploy/systemd`.
  - Host provisioning creates `derived/verdicts`.
  - The S2-R19 / R-3 change to the AUT-6 brief is filed as a coordinator erratum against AUT-6 r15, not as an edit to the brief.
