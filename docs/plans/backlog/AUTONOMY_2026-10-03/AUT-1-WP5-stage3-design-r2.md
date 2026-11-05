# AUT-1 WP5 stage 3 design — r2 (code-architect, 2026-10-04; all of S3-R1..R23 designed in)

Base: `afb225d0`. HEAD is `5bc48253`, which adds only one docs commit, so the code is identical. This is read-only: no file was written. Every `file:line` below was checked on this tree.

## §0 Facts checked on the tree and the host
- **F1/F2** (unchanged from r1). New unit files do nothing until linked. Editing an already-linked file is one `daemon-reload` from live. `breezy-quote-tape.service` is linked but has no `ExecStopPost=`, so the stop-hook row is not live yet.
- **F3.** The unit lint refuses `OnFailure=breezy-autonomy-failed@` (`unit_lint.py:446-448`). Unit files therefore stay fixtures until stage 4.
- **F4.** `BwrapRow` (`table.py:161-184`) has no network field. `NOTIFIER_FALLBACK_ROWS` is `frozenset()` (`table.py:39`). `validate_table` (`table.py:496`) takes no fallback set.
- **F5/F6** (unchanged). The data-root re-bind makes the catalog readable inside the sandbox. The studies lock is `/run/user/1000/breezy-studies.lock`.
- **F7 (S3-R1, confirmed).** `parse_recorder_journal` reads only `INVOCATION_ID` and `_SYSTEMD_INVOCATION_ID` (`capture_audit_host.py:305`).
  - Every real `UNIT_RESULT` line on this host carries only `USER_INVOCATION_ID`. The journal holds 30 such lines since 2026-09-02 (oom-kill 2, timeout 1, exit-code 27).
  - **No `UNIT_RESULT=watchdog` line has ever been logged**, because the recorder is not `Type=notify` yet.
  - The recorder's own stdout lines carry `_SYSTEMD_INVOCATION_ID`, and their `MESSAGE` may be a byte array with ANSI codes (`tests/fixtures/recorder_watchdog/deferred_journal_line.json`).
- **F8 (S3-R2, confirmed).** `_Delivery.send` indexes `CAPTURE_ALERT_SEVERITIES[event]` (`capture_audit.py:491`). The `HEALED_`/`ABANDONED_` prefixed events are not keys (`capture_alerts.py:36-57`), so the lookup raises `KeyError`. `is_capture_alert_event` (`:77`) accepts them.
- **F9 (S3-R8, confirmed defect).** `run_audit` re-arms `DEADLINE` on every call, once per family (`capture_audit.py:699,712`). With N families, the run can last N×840 s, past the 1490 s ExecStart bound.
- **F10 (new defect, leg N).**
  - `_NOTIFY_NAME_RE` requires a 32-hex id (`capture_audit_inputs.py:146-148`).
  - Leg N expects `invocation_id == str(cycle_ns)`, a decimal (`capture_audit_stream_legs.py:15-18,378-382`).
  - So a delivered `NBP_CYCLE_MISSED__<cycle_ns>` marker can never be seen. This fails closed today; S2 fixes it through D11.
- **F11.** `_stall_records` never fills `StallRecord.heal_sha256` (`capture_audit_inputs.py:519`). The hook writes `observation_sha256` (`capture_recorder_hook_cli.py:162`), so S1 reads stall records itself.
- **F12.** `_notifier_proofs` (`capture_audit_inputs.py:526-542`) is the single-read pattern S3-R9 reuses: `list_names`, then a `ReadPolicy.REPO` read, then "unreadable means not delivered".
- **F13.** AUT-6 per-attempt records are `evidence/alerts/<date>/<ts_ns>_<writer>_<d|f>.json`, with `event`, `delivered` and `schema:"alert_delivery/v1"` (AUT-6 r15 §3.6.2; plan §7(d)).
- **F14.** `HeartbeatSummary` has 4 fields (`capture_audit_input_types.py:101-107`). It is built at `capture_audit_inputs.py:398` and in `tests/support/capture_audit_fixtures.py` and `test_capture_audit_stream_legs.py`. `_CACHE_TYPES` is at `capture_audit_cache.py:83`.
- **F15.** The journal argv[0] is the bare `"journalctl"` in the templates (`capture_audit_host.py:62-97`), the `Popen` literals (`:180-215`) and the lint rows (`capture_closure_lint.py:133-138`). `/usr/bin/journalctl` exists.
- **F16 (S3-R16).** Settlement writes through `replace_atomic` plus the lock file `.capture_settlement.lock` (`capture_settlement.py:19-21,83,211,405`; lint row `capture_closure_lint.py:164-167`). This is the design WP5-R2 accepted. See RULING-CONFLICT RC-1.
- **F17.** The C4 HEALTH verdict is skipped while the producer is unpinned (`capture_audit.py:447-450`).
- **F18.** On the host, `~/.local/share/breezy/evidence/` and `derived/verdicts/` are both absent.
- **F19.** `instance_id` appears in the log as `BREEZY-001.TradingNode: instance_id: <uuid>`. A decoy line, `MessageBus: config.use_instance_id=False`, follows it.
- **F20.** `test_autonomy_bwrap_argv.py` is 1021 lines, `test_autonomy_self_probe.py` is 892 and `test_autonomy_units_wrapped.py` is 829: all three are over 800 at base. See RC-2.
- **F21.** The WP4 commit `2608599c` (branch `backlog/aut1-wp4-2026-10-04`) puts `injected` inside the NBP heal body, and that field is covered by the sha (`nbm_quantile_actor.py:540-549` @2608599c).

## §1 Design decisions
- **D1. Units are fixtures until stage 4** (S3-R19). They live in `tests/fixtures/capture_units/`; no file under `deploy/systemd/` changes.
- **D2. In-process studies lock** (R-1 ACCEPTED: S3-R13, S3-R14, S3-R22).
  - `_main` runs in this order:
    1. consumes the snapshot;
    2. runs `launch_window_guard(600, 1500)` (kept conservative);
    3. enumerates families, returning 0 when there are none;
    4. takes the lock;
    5. runs one absolute deadline over the family loop and then heal.
  - New helper `runtime/autonomy_sandbox/studies_lock.py`, reusable by AUT-6's `IN_PROCESS_STUDIES_LOCK_UNITS`. `acquire_studies_lock(path, *, wait_s, poll_s, monotonic, sleep) -> int`:
    - opens with `O_RDONLY|O_NOFOLLOW|O_CLOEXEC` and **never `O_CREAT`**;
    - checks with `fstat` that the target is a regular file owned by the euid;
    - polls `flock(LOCK_EX|LOCK_NB)`.
  - Failure modes:
    - `StudiesLockMissing` (ENOENT) and `StudiesLockTimeout` both make the CLI exit **1** (S3-R14), so `OnFailure=` pages.
    - Only a launch-window deferral exits 0.
  - The lock path is `default_roots().run_user / STUDIES_LOCK_NAME`, the path seam B re-binds (`run_mounts.py:105-113`).
- **D3. E-15 field** (R-4 ACCEPTED: S3-R10, S3-R11, S3-R12).
  - `BwrapRow.network: Literal["none","egress"]` is required, with no default.
  - `bwrap.argv_for` appends `--unshare-net` **unless `row.network == "egress"`**, so emission fails closed (S3-R11).
  - `validate_table` refuses a row when:
    - `network` is any other value;
    - `network == "none"` and `resolves_dns`;
    - `network == "none"` and the row is in a fallback set (`row.notifier_fallback` or a name in the new `fallback_rows=NOTIFIER_FALLBACK_ROWS` keyword) (S3-R12).
  - Row values:
    - the three seam-B selftest rows are `"egress"`, their true behaviour, and are not tightened (S3-R11);
    - the AUT-1 stop hook (not live, F2) and the three capture rows are `"none"`.
  - The self-probe gains `_net_failures(row, fs)` on `none` rows (S3-R10):
    - a connect to `198.51.100.7:80` must give `ENETUNREACH`, else `net_reachable`;
    - `/proc/net/dev` must list only `lo`, else `net_iface_visible`;
    - the fact `net_ifaces` is recorded on every row.
    - `ProbeFs` gains an injectable `connect_errno`.
  - The phase-2 harness (`bwrap_harness.py:163`) is untouched.
  - The isolation proof is the phase-1 argv test plus host V-step V3. No egress-resolve test is added.
  - Expectation corrected: `127.0.0.53:53` inside a fresh netns gives `ECONNREFUSED`.
- **D4. No alerts bind and no egress in stage 3** (R-2 ACCEPTED as amended by S3-R19).
  - Stage 4 adds the `evidence/alerts` spool bind.
  - The rows stay `none`. An AUT-6 egress unit sends from the spool.
  - Any later flip to `egress` needs its own SEC review and an exfiltration test.
- **D5. Settlement catalog** (WP5-R2). The catalog is read-only through the data-root re-bind; the unit passes `--catalog-base` explicitly. The only write bind is `catalog/quote_tape/decisions`. Residual risk is recorded per S3-R16 / RC-1.
- **D6. Heal** (S3-R3..R6, S3-R8, S3-R9). Pure planner `capture_heal.py` plus I/O `capture_heal_io.py`.
  - **When it runs:** once per audit run, from `_main` after the family loop. It is wired in 3c (S3-R18).
  - **Journal (S3-R3):** `run_journal(RECORDER_JOURNAL_ARGV)` one UTC day at a time over the last `HEAL_JOURNAL_DAYS=3` days. Each read is under the 256 MiB cap (`capture_audit_host.py:133`).
  - **Matching (S3-R5):** S1's own parser takes `UNIT_RESULT=watchdog` entries keyed by `USER_INVOCATION_ID` (through the fixed host parser). The restart is the FIRST later invocation (`_SYSTEMD_INVOCATION_ID`) whose decoded `MESSAGE` matches `TradingNode: instance_id: <uuid>` (F19) and that has `live/<uuid>/config.json`.
  - **Confirmation (S3-R4):** `now ≥ restart_ns + 1800 s`; growth ≥ 900 s, where growth is the newest entry mtime minus the `config.json` mtime, excluding `.converted-*`; and no later watchdog kill within 1800 s of the restart.
  - **Record:** `evidence/capture/heal/<kill-date>/<kill_ts_ns>_audit_breezy-quote-tape.json`, via `write_once`. It carries the stall record's `observation_sha256`, `invocation_id`, `unit_result:"watchdog"` (copied from the parsed entry) and `decided_by:"systemd_watchdog"`.
  - **`injected` (S3-R6):** read at first write only. A record whose name already exists is never rebuilt; only its invariant fields are verified. A later drill file can therefore never cause `EXISTS_DIFFERENT`.
  - **No stall record:** no heal is written; leg W carries the kill.
  - **Delivery ledger (S3-R9):** `capture_aut6_contract.delivered_events(data_root, first, last)` scans `evidence/alerts/<date>/` for names matching `DELIVERY_RECORD_NAME_RE` (`…_d.json`), with schema `alert_delivery/v1`, `delivered is True`, and returns their events. It reuses F12's pattern. A missing or unreadable file means not delivered, which fails closed toward a re-send. An uncollected pending contract pins AUT-6's writer.
  - **Sender (S3-R2):** heal I/O receives `HealSender.send(event, detail, attempt_kind) -> bool` and never imports `_Delivery`. Before stage 4, the 3c adapter passes `attempt_kind` in `detail` (§9 item 5).
- **D7. Re-send and abandon** (plan §3.11.6, S3-R7, R-3 ACCEPTED).
  - Re-sends carry `attempt_kind="retry"`. Node (NBP) records are re-sent only once they are older than 600 s.
  - Gaps come from `watchdog_evidence_gaps` in audit files over [today−30, today−1], re-checked now against the stall record and the notifier marker. A gap whose evidence has since appeared is dropped.
  - The gap key is `sha256("breezy-quote-tape.service\0"+InvocationID)`. The event is `CAPTURE_HEAL_ALERT_ABANDONED_<key>` with `detail` marked `gap=…`, and the marker is `heal_alert_abandoned/gap_<key>.json`.
  - The §3.16 row is updated (S3-R22).
  - Age-out at 30 days applies to heals and to gaps: `CAPTURE_HEAL_UNABANDONED heal=|gap=<sha>`, plus `heal_alert_unabandoned_count` and `gap_alert_unabandoned_count`.
- **D8. Live proof** (S3-R21; plan §6, §3.11.5).
  - The roll-up per family covers:
    - qualifying days;
    - a stale INCONCLUSIVE (age > `BACKFILL_DAYS`) breaking the run, while a fresh one is pending and neither counts nor breaks;
    - a watchdog heal paired with its stall record (same sha and invocation), its `UNIT_RESULT` (the heal record's journal-derived fields), and its AUT-6 marker (contract reader);
    - the NBP-heal alternative;
    - `CAPTURE_HEALED_<sha>` delivered in [heal date, +8 d].
  - DEADMAN reads the newest audit file, not the C4 verdict (F17).
  - DEADMAN and FILE_MISSING are deduped per `asof` by a write-once `live_proof/sent/<asof>/<event>_<family>.json`, written only after `accepted=True`. Each check runs in its own `try`.
  - Output goes through `replace_atomic` at 0444.
- **D9. R5 summary** (S3-R20).
  - `HeartbeatSummary.write_drops: int` is required, with no default.
  - `leg_r5` reads it, and `_write_drops` is deleted.
  - **No codec bump** (summaries are not in `_CACHE_TYPES`); a test pins that.
  - `test_nonzero_write_drops_fails_stream_write_dropped` is re-targeted at the summary.
- **D10. Lint hardening** (S3-R15). An argv-matched call is admitted only if all of these hold:
  - it is `subprocess.run` or `subprocess.Popen`, by attribute;
  - `len(call.args)==1`;
  - the argv list has no `Starred` element;
  - it has no `*`/`**`;
  - its keywords ⊆ `ALLOWED_SUBPROCESS_KWARGS = {"stdout","stderr"}` with `STDIO_CONSTANT_REFERENCES` values.

  Aliased and `from subprocess import Popen` forms are refused. argv[0] is `/usr/bin/journalctl` in the templates, the `Popen` literals and the rows (pinned in 3a).
- **D11. AUT-6 key shapes** (S2-R19, S3-R9). `capture_aut6_contract.py` holds:
  - `NOTIFIER_MARKER_RE` (unit plus 32-hex);
  - `NBP_MISSED_MARKER_RE` (`NBP_CYCLE_MISSED__\d{1,20}`), which fixes F10;
  - the delivery-record constants;
  - `read_notifier_proofs` (extracted from `inputs`), which `inputs` imports.

  To avoid a cycle, the contract module imports only `single_read` and the input types. The AUT-6 change is filed as a coordinator erratum against AUT-6 r15 (S3-R23).
- **D12. Units** (R-5 ACCEPTED; E-9 per E-7e(f): each pre line counted at T+K, `TimeoutStopSec=5`, 60 s accuracy).
  - Oneshot with `TimeoutStartSec`, timers not `Persistent`, `UMask=0077`, `OnFailure=breezy-autonomy-failed@%n.service`, no `alerts.env` re-bind.
  - The interpreter is `/home/jon/breezy/.venv/bin/python3 -I -m …`.
  - Own-lock memory sum: 512 + 256 + 64 + 64 = **896M** against ARCH §5.2's 4G (S3-R22).

**E-9 latest-end table (restated after S3-R8).** S3-R8 changes only the in-process budget; every unit literal is unchanged.

| Unit | Start | Pre lines (T+K) | ExecStart bound | Start/Stop s | Memory | Latest end |
|---|---|---|---|---|---|---|
| settlement | 13:35 | install-d 5 | `timeout -k 5 290` → `flock -w 30` → wrapper = 295 | 300 / 5 | `MemoryMax=512M` | 13:35+60+5+295+5 = **13:41:05** |
| audit (studies slice) | 13:50 | install-d 5, touch 5, snapshot B=10 → 15 | `timeout -k 5 1490` → wrapper = 1495 | 1500 / 5 | `MemoryHigh=768M`, `MemoryMax=1G` | 13:50+60+25+1495+5 = **14:16:25** (E-7e(f) bound ≤ 14:16:25 ✓) |
| live-proof (`OnSuccess=`) | ≤ 14:16:25 | install-d 5 | 295 | 300 / 5 | `MemoryMax=256M` | **14:21:30** |
| live-proof (fallback) | 14:35 | install-d 5 | 295 | 300 / 5 | 256M | **14:41:05** |

None of these meets [16:30Z, 17:10Z). r1's 14:16:30 used `TimeoutStartSec` instead of T+K and is superseded.

**In-process budget (S3-R8):**
- `run_deadline = min(lock_acquired + AUDIT_WORK_BUDGET_S (840), exec_start + AUDIT_EXEC_TIMEOUT_S (1490) − AUDIT_MARGIN_S (60))`, in `time.monotonic`.
- The family loop uses `run_deadline − HEAL_RESERVE_S (120)`.
- Heal runs only while `remaining ≥ HEAL_FLOOR_S (120)`. Otherwise it logs `heal_deferred`, which is not counted as a failure.
- Worst case: 600 lock wait + 830 work + 60 margin = 1490 ✓.

**Rows** (`network="none"`, `resolves_dns=False`):
- settlement: `catalog/quote_tape/decisions`;
- audit: `evidence/capture/{audit,heal,heal_alert_abandoned}`, `derived/verdicts`, `cache/capture_audit`, plus `bus_snapshot_bind=cache/capture_audit_bus` and `AUDIT_BUS_READS` named `AUDIT_BUS_READ_NAMES`, with `studies_lock=True` and `E7_STUDIES_LOCK`;
- live-proof: `evidence/capture/live_proof`.

## §2 Acceptance criteria
1. **Invocation id.** `parse_recorder_journal` takes `USER_INVOCATION_ID` first, then the existing fallbacks. An entry with an empty id raises `journal_failed`. A real line fixture parses.
2. **Severity.** `severity_for` returns INFO for HEALED, CRITICAL for ABANDONED and the dict value otherwise, and raises on an unknown event. `_Delivery.send` uses it.
3. **One deadline.** The run has one absolute deadline. Every family and heal see the same instant, and nothing re-arms it.
4. **Lock.** The lock helper never creates the file, refuses a symlink, and takes `LOCK_EX`. Phase 2: it succeeds alone and gives `EWOULDBLOCK` while the host holds the lock.
5. **CLI order.** The CLI consumes the snapshot before the lock. A 600 s wait does not stale it. A lock timeout or missing lock exits 1 with no writes. A window deferral exits 0.
6. **Network field.** Every row declares `network`. Emission happens unless the value is exactly `"egress"`. These are refused:
   - an unknown value;
   - `none` with `resolves_dns`;
   - `none` in a fallback set.
7. **Self-probe net check.** On `none` rows the probe fails `net_reachable` or `net_iface_visible` (phase 1, injected). The host V-step proves `ENETUNREACH` and `lo`-only through the real wrapper.
8. **Rows.** The three rows validate, bind exactly the planned directories, never bind the catalog base, and their bus reads equal `AUDIT_BUS_READ_NAMES`.
9. **Lint scope.** The fixture units pass `lint_units` with a stand-in AUT-6 row. Against the real table they fail only on `onfailure_scope`.
10. **Calendar.** The calendar tests pass, and the E-9 sums recompute exactly from the fixture files.
11. **Budget.** The work budget derives from the unit literal 1490.
12. **Heal confirmation.** Heal confirms only under §3.10.3 + S3-R4. It matches by `instance_id` (first later invocation). The boundaries at 899/900 s and 1799/1800 s hold.
13. **Heal records.** Records are write-once. A rerun is a no-op. A late drill file never makes a difference, and `injected` is taken at first write.
14. **Re-send.** Heals and gaps are re-sent daily with `retry`. The node 600 s floor holds. Abandon order: the marker is written only after `delivered=true`. Both heals and gaps age out at 30 days. A gap with late evidence is not re-sent.
15. **Heal journal.** It runs once per run, reads 3 days one day at a time, and defers below the floor without counting a failure.
16. **Live proof.** It implements §6 per S3-R21, uses DEADMAN on the audit file, and dedupes per `asof`. Each check is in its own `try`, and a failed delivery exits 1.
17. **R5.** R5 uses `HeartbeatSummary.write_drops` with no default and no `boot.stream()` call. `_CACHE_TYPES` excludes the summaries.
18. **Lint hardening.** It refuses the D10 set. argv[0] is `/usr/bin/journalctl`. Every pre-existing lint test passes unedited.
19. **AUT-6 shapes.** Leg N and leg W read both marker shapes plus the delivery-record shape from fixtures; F10 is fixed. The pending AUT-6 contract fails when run by path.
20. **Retention.** `settlement_` and `fq_funnel_` names never match the retention gzip regexes.
21. **Closures (S3-R16).** The new modules import no adapter, `httpx`, `ingest` or `resolver`, and never reference `state/`, the exec store or the permit. The settlement and audit write pins follow RC-1.
22. **No live units.** `git diff --stat -- deploy/systemd` is empty, and no linked unit changes.
23. **Gate.** `EXIT=0`. `lint-imports` prints "N kept, 0 broken". The exec-client sha is unchanged. The firewall and operator-control tests are unedited.

## §3 File table
N = new, E = exists. Lines are base → estimate after the change.

| File | | Owner | Lines | Change |
|---|---|---|---|---|
| `src/breezy/analysis/capture_audit_host.py` | E | 3a | 414→425 | S3-R1, argv[0] |
| `src/breezy/persistence/autonomy/capture_alerts.py` | E | 3a | 83→95 | `severity_for` |
| `src/breezy/analysis/capture_audit.py` | E | 3a | 720→728 | `send` via `severity_for`; `run_audit(…, deadline_ns)` |
| `src/breezy/analysis/capture_audit_cli.py` | E | 3a → S3 → 3c | 99→~175 | deadline seam; lock and budget; heal wiring |
| `src/breezy/analysis/capture_heal.py` | N | 3a stub → S1 | →~330 | pure planner |
| `src/breezy/analysis/capture_heal_io.py` | N | 3a stub → S1 | →~380 | I/O, `run_heal_duty` |
| `src/breezy/analysis/capture_live_proof.py` | N | 3a stub → S2 | →~300 | roll-up |
| `src/breezy/analysis/capture_live_proof_cli.py` | N | 3a stub → S2 | →~200 | CLI |
| `src/breezy/analysis/capture_aut6_contract.py` | N | 3a constants → S2 | →~150 | D11 shapes and readers |
| `src/breezy/analysis/capture_audit_input_types.py` | E | S2 | 314→316 | `write_drops` |
| `src/breezy/analysis/capture_audit_inputs.py` | E | S2 | 769→~750 | extract the marker reader (net negative) |
| `src/breezy/analysis/capture_audit_stream_legs.py` | E | S2 | 436→~430 | R5; leg N via contract |
| `tests/support/capture_closure_lint.py` | E | 3a rows → S2 engine → 3c narrowing | 536→~600 | rows, D10 |
| `src/breezy/runtime/autonomy_sandbox/table.py` | E | S3 | 513→~600 | field, checks, 3 rows |
| `src/breezy/runtime/autonomy_sandbox/bwrap.py` | E | S3 | 517→520 | emission |
| `src/breezy/runtime/autonomy_sandbox/self_probe.py` | E | S3 | 525→~565 | net check |
| `src/breezy/runtime/autonomy_sandbox/studies_lock.py` | N | S3 | →~90 | D2 helper |
| `tests/fixtures/capture_units/*.{service,timer}` (5 files) | N | S3 | small | D12 |
| `tests/fixtures/capture_heal/{nbp_heal_wp4_2608599c.json, unit_result_real_timeout.json, unit_result_watchdog_derived.json, recorder_instance_lines.json}` | N | 3a | small | the real `timeout` line copied verbatim; the watchdog variant differs only in `UNIT_RESULT` and is labelled derived (F7) |
| `tests/unit/autonomy_writer_table.py` | E | 3a | 182→~205 | one-writer rows: heal, abandoned, live_proof, verdicts |
| `tests/support/bwrap_host_phase.py` | E | S3 | 469→470 | add the file; 34 → 36 |
| `tests/support/capture_audit_w3_fixtures.py` | E | S3 (forced) | 561→562 | `network=` |
| `tests/support/capture_audit_fixtures.py` | E | S2 (forced) | 201→202 | `write_drops=` |
| `tests/unit/test_autonomy_bwrap_argv.py` | E | S3 (forced, RC-2) | 1021→1022 | exact set gains `--unshare-net` |
| `tests/unit/test_autonomy_units_wrapped.py` | E | S3 (forced, RC-2) | 829→835 | 6 constructors |
| `tests/unit/test_autonomy_self_probe.py` | E | S3 (forced, RC-2) | 892→894 | `FIXED_REASON_CODES` +2 |
| `tests/unit/test_autonomy_sandbox_table.py` | E | S3 (forced) | 692→695 | row set (`:81`) |
| `tests/unit/test_autonomy_aut1_stop_hook_row.py` | E | S3 (forced) | 110→111 | `network=="none"` |
| `tests/unit/test_capture_audit.py` | E | 3a (forced) | 688→~710 | `:571` absolute deadline; `_run` helper |
| `tests/unit/test_capture_audit_cli.py` | E | 3a, then S3 | 221→~330 | inject the lock (otherwise the real host lock is taken); lock tests |
| `tests/unit/test_capture_audit_stream_legs.py` | E | S2 | 609→~650 | re-target, F14 |
| `tests/unit/test_capture_audit_host_tape.py` | E | 3a | 503→~535 | S3-R1 |
| `tests/unit/autonomy/test_capture_alerts.py` | E | 3a | 115→~140 | `severity_for` |
| `tests/unit/test_capture_audit_stubs.py` | E | 3a, then 3c | 313→~370 | `EXPECTED` + `EXPECTED_CONSTANTS` for the five modules; `REAL_MODULES` in 3c |
| `tests/unit/autonomy/test_capture_read_only_closure.py` | E | S2 | 371→~470 | D10 mutations |
| `tests/unit/test_decisions_retention.py` | E | S2 | 413→~430 | pin |
| New tests, S1 | N | S1 | each < 500 | `test_capture_heal.py`, `test_capture_heal_resend.py` |
| New tests, S2 | N | S2 | | `test_capture_live_proof.py`, `test_capture_live_proof_cli.py`, `test_capture_aut6_contract.py`, `tests/unit/autonomy/pending_aut6_notifier_proof_contract.py` (uncollected) |
| New tests, S3 | N | S3 | | `test_autonomy_network_field.py`, `test_autonomy_self_probe_net.py`, `test_studies_lock.py`, `test_capture_sandbox_rows.py`, `tests/integration/test_capture_studies_lock_namespace.py`; `test_capture_units.py` (E, 56→~260) |

## §4 Tests and their RED reason after 3a
After 3a, a new module raises `NotImplementedError` rather than failing to import.

- **3a:**
  - `test_unit_result_user_invocation_id_is_read` fails: `invocation_id == ""`.
  - `test_empty_invocation_id_is_journal_failed` fails: the entry is accepted.
  - `test_real_timeout_kill_line_parses` fails: empty id.
  - `test_severity_for_healed_is_info_abandoned_critical` fails: `AttributeError`.
  - `test_delivery_send_accepts_prefixed_events` fails: `KeyError`.
  - `test_every_family_sees_one_absolute_deadline` fails: re-armed per family.
  - `test_journal_argv0_is_absolute` fails: bare name.
  - The stub-signature pins pass, because this is the GREEN-by-construction step.
- **S1 (all RED on `NotImplementedError`):**
  - `test_watchdog_kill_followed_by_streaming_instance_is_healed`
  - `test_recorder_heal_matches_restart_by_instance_id_not_time_window`
  - `test_first_later_invocation_with_config_is_the_restart`
  - `test_use_instance_id_config_line_is_not_an_instance`
  - `test_growth_899s_unconfirmed_900s_confirmed`
  - `test_restart_1799s_old_unconfirmed_1800s_confirmed`
  - `test_restart_younger_than_30min_is_unconfirmed`
  - `test_second_kill_within_1800s_is_not_healed`
  - `test_converted_markers_excluded_from_growth`
  - `test_ansi_byte_array_message_is_decoded`
  - `test_heal_record_rerun_is_noop`
  - `test_late_drill_file_never_exists_different`
  - `test_drill_present_at_first_write_marks_injected`
  - `test_kill_without_stall_record_writes_no_heal`
  - `test_journal_read_per_day_over_three_days`
  - `test_nbp_heal_fixture_2608599c_parses`
  - `test_heal_resend_daily_with_attempt_kind_retry`
  - `test_node_record_younger_than_600s_not_resent`
  - `test_abandon_marker_only_after_delivered_true`
  - `test_unmarked_heal_older_than_30d_counts_unabandoned`
  - `test_gap_sent_first_run_and_resent_until_delivered`
  - `test_gap_with_late_evidence_not_resent`
  - `test_gap_ages_out_at_30_days`
  - `test_gap_abandon_key_is_sha_of_unit_nul_invocation`
  - `test_ledger_missing_or_unreadable_is_not_delivered`
  - `test_heal_below_floor_defers_without_failure`
  - `test_heal_io_never_imports_delivery_class`
- **S2:**
  - Live proof (RED on `NotImplementedError`):
    - `test_seven_pass_days_and_five_fills_is_proven`
    - `test_fail_or_error_breaks_the_window`
    - `test_stale_inconclusive_breaks_fresh_is_pending`
    - `test_pre_capture_and_partial_epoch_never_count`
    - `test_canary_only_day_counts_zero_fills`
    - `test_lost_in_flush_window_day_still_qualifies`
    - `test_watchdog_heal_pairs_stall_unit_result_and_marker`
    - `test_nbp_heal_alternative_satisfies_stall_leg`
    - `test_healed_delivered_outside_plus8_window_does_not_count`
    - `test_deadman_reads_audit_file_not_c4_verdict`
    - `test_deadman_and_missing_deduped_per_asof`
    - `test_each_deadman_check_isolated`
    - `test_live_proof_failed_delivery_exits_nonzero`
    - `test_live_proof_cli_defers_inside_launch_window`
  - `test_r5_reads_summary_without_stream_read` fails on the `boot.stream` spy.
  - `test_heartbeat_summary_requires_write_drops` fails: the field is absent.
  - `test_summaries_not_in_cache_types` passes; it is a guard.
  - `test_nonzero_write_drops_fails_stream_write_dropped` is re-targeted, and fails until the summary is filled.
  - `test_leg_n_reads_nbp_cycle_missed_decimal_marker` fails: F10.
  - `test_marker_shapes_single_source` fails: `NotImplementedError`.
  - `test_delivery_record_reader_fixture` fails: `NotImplementedError`.
  - Lint tests fail because the lint admits each case today:
    - `test_argv_call_refuses_kwarg[shell|env|executable|cwd|stdin|input|close_fds|preexec_fn|start_new_session]`
    - `test_argv_call_refuses_second_positional`
    - `test_argv_call_refuses_starred_element`
    - `test_argv_call_refuses_splat`
    - `test_from_subprocess_import_popen_refused`
  - `test_existing_journal_templates_still_admitted` passes.
  - `test_retention_never_compresses_settlement_or_funnel_files` passes (pin).
  - `test_new_modules_reference_no_state_exec_or_permit` fails: `NotImplementedError` (stub source).
- **S3:**
  - Network field (all fail with `TypeError`: field absent):
    - `test_unshare_net_unless_exactly_egress`
    - `test_unknown_network_value_refused`
    - `test_network_none_with_resolves_dns_refused`
    - `test_network_none_fallback_row_refused`
    - `test_every_row_declares_network`
  - Self-probe (fail: the check is absent):
    - `test_probe_none_row_reachable_fails_net_reachable`
    - `test_probe_none_row_extra_iface_fails`
    - `test_probe_egress_row_skips_net_check_records_fact`
  - Studies lock (fail: no module):
    - `test_lock_never_creates`
    - `test_lock_refuses_symlink`
    - `test_lock_times_out_after_wait`
  - Phase 2 (fail: file absent):
    - `test_studies_lock_in_row_alone_succeeds`
    - `test_studies_lock_in_row_held_by_host_ewouldblock`
  - Rows (fail: rows absent):
    - `test_capture_rows_bind_exactly_planned_dirs`
    - `test_settlement_catalog_base_under_data_root_not_a_bind`
    - `test_audit_bus_reads_equal_names`
  - `test_capture_units.py` (fail: fixtures absent):
    - `::test_no_unit_overlaps_launch_window`
    - `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`
    - `::test_no_capture_timer_is_persistent`
    - `::test_every_capture_unit_and_onfailure_target_runs_through_bwrap_wrapper`
    - `::test_capture_units_fail_lint_only_on_aut6_scope`
    - `::test_e9_latest_end_matches_table`
    - `::test_audit_work_budget_derives_from_unit_timeout`
  - `test_capture_audit_cli.py` (fail: no lock):
    - `::test_snapshot_consumed_before_studies_lock_wait`
    - `::test_lock_wait_600s_does_not_stale_snapshot`
    - `::test_lock_timeout_exits_one_without_writes`
    - `::test_missing_lock_exits_one_never_created`

## §4a Mutation table (one named mutant per test group; python review finding 8)

| Group | Mutant (must be killed) |
|---|---|
| 3a parser | M-INV: drop `USER_INVOCATION_ID` · M-EMPTY: accept `""` |
| 3a severity | M-SEV: HEALED → WARNING |
| 3a deadline | M-REARM: `DEADLINE.set(MONOTONIC()+840)` per family |
| 3a argv | M-ARGV0: bare `journalctl` |
| S1 confirmation | M-TIMEWIN: match by time window · M-LASTINV: last later invocation · M-DECOY: substring `instance_id` · M-GROW: `>` 900 · M-AGE: drop 1800 s age check · M-CONV: count `.converted-*` |
| S1 records | M-INJ: rebuild `injected` on rerun · M-NOSTALL: write without stall sha |
| S1 re-send / abandon | M-KIND: `attempt_kind="alert"` · M-NODE600: drop node floor · M-EARLYMARK: marker before proof · M-GAPAGE: no gap age-out · M-LATEGAP: re-send after evidence · M-KEY: key without `\0` |
| S1 run | M-9D: one 9-day read · M-FLOOR: deferral counted as failure · M-LEDGER: unreadable means delivered |
| S2 roll-up | M-6DAYS · M-4FILLS · M-INCPASS: stale INCONCLUSIVE ignored · M-PRECAP: PRE_CAPTURE counted · M-WIN9: +9-day window · M-NBPOFF |
| S2 dead-man | M-VERDICT: DEADMAN on the C4 verdict · M-DEDUPE: re-send on the fallback run · M-ONETRY: shared `try` |
| S2 R5 | M-STREAM: read `boot.stream()` · M-DEFAULT0: `write_drops=0` default · M-CODEC: add the summary to `_CACHE_TYPES` |
| S2 lint | M-KW: admit `env` · M-POS: admit 2 positional · M-STAR · M-ALIAS: admit `from subprocess import Popen` |
| S2 contract / retention | M-HEX32: NBP regex 32-hex · M-RET: gzip regex matches `settlement_` |
| S3 field | M-EQNONE: emit iff `=="none"` · M-CASE: accept `"None"` · M-DNS · M-FALLBACK |
| S3 probe | M-SKIPNET · M-ANYIFACE |
| S3 lock / CLI | M-CREAT: `O_CREAT` · M-FOLLOW: drop `O_NOFOLLOW` · M-EXIT0: timeout exits 0 · M-ORDER: lock before snapshot |
| S3 units / budget | M-PERSIST · M-RUNTIMEMAX · M-STOP: drop `TimeoutStopSec` · M-840: ignore the unit literal · M-BIND: extra `evidence/alerts` bind |

## §5 Blocked items
These are unchanged from r1 except where noted.
- Unit promotion and `OnFailure=` scope: blocked by AUT-6.
- Real delivery (outbox, ledger, markers, pending contracts GREEN): AUT-6, wired in **stage 4** (S3-R19), which supersedes WP5-R2's "WP8 injects".
- Activation: AUT-6, plus V-11 (14 FQ days on or after 2026-10-15).
- Families, live NBP heal records and accrual: WP8.
- Real watchdog kills: WP3 step 2. No real `watchdog` line exists yet (F7).
- Drill `injected`: WP9, which must write `drill/<date>.json` before injecting.

## §6 Build streams (blind; disjoint edit sets; serial 3a → parallel S1/S2/S3 → serial 3c)
- **3a (serial, lands first).**
  - **Edits:** `capture_audit_host.py`, `capture_alerts.py`, `capture_audit.py`, `capture_audit_cli.py` (deadline seam only); the 5 new modules as stubs with real constant values; the rows section of `capture_closure_lint.py` (5 rows; heal and live-proof `writes=("*",)` at `min_calls=1`; `_journal_argv` argv[0]); `autonomy_writer_table.py`; `tests/fixtures/capture_heal/*`; `test_capture_audit_host_tape.py`, `test_capture_alerts.py`, `test_capture_audit.py`, `test_capture_audit_stubs.py`, `test_capture_audit_cli.py` (forced signature only).
  - **Reads only:** `capture_audit_inputs.py`, `single_read`, `capture_records.py`, plan §3.10–§3.16.
- **S1 (heal).**
  - **Edits:** `capture_heal.py`, `capture_heal_io.py`, `test_capture_heal.py`, `test_capture_heal_resend.py`.
  - **Reads only:** `capture_audit_host.py` (`run_journal`, `parse_recorder_journal`, `RECORDER_JOURNAL_ARGV`); `capture_audit_inputs.py` (`list_names`, `DEADLINE`, `MONOTONIC`, `ScanDeadline`); `capture_audit_wire.py`; `capture_audit_model.py`; `capture_alerts.py`; `single_read`; `capture_recorder_hook_cli.py` (`STALL_*`); the 3a stub constants of `capture_aut6_contract.py` (the ledger is injected in tests); `tests/fixtures/capture_heal/*`; `tests/fixtures/recorder_watchdog/*`.
  - Reports its narrowed lint scopes and `min_calls` to 3c.
- **S2 (live proof, contract, hardening).**
  - **Edits:** `capture_live_proof.py`, `capture_live_proof_cli.py`, `capture_aut6_contract.py`, `capture_audit_input_types.py`, `capture_audit_inputs.py`, `capture_audit_stream_legs.py`, the engine section of `capture_closure_lint.py`, `capture_audit_fixtures.py`, `test_capture_audit_stream_legs.py`, `test_capture_read_only_closure.py`, `test_decisions_retention.py`, the S2 new tests, the pending file.
  - **Reads only:** `capture_heal.py` (3a constants), `capture_audit_wire.py`, `capture_audit_cli.py` (`families_by_construction`), `capture_schedule.py`, `capture_audit_cache.py`, `scripts/ops/decisions_retention.py`, `single_read`, `tests/fixtures/capture_heal/*`, `capture_audit_w3_fixtures.py`.
  - Reports narrowed scopes to 3c.
- **S3 (sandbox, lock, units).**
  - **Edits:** `table.py`, `bwrap.py`, `self_probe.py`, `studies_lock.py`, `capture_audit_cli.py` (lock and budget), `tests/fixtures/capture_units/*`, `bwrap_host_phase.py`, `capture_audit_w3_fixtures.py`, the S3 new tests and every S3 forced edit in §3.
  - **Reads only:** `unit_lint.py`, `run_mounts.py`, `binds.py`, `bus_handoff.py`, `selftest_cli.py`, `bwrap_harness.py` (MUST NOT be edited), `capture_audit_host.py`, `capture_audit_model.py`, `capture_schedule.py`, `tests/fixtures/recorder_watchdog/pending_recorder_unit.service`.
- **3c (serial integration).** Merge order is S3, then S2, then S1. Then:
  1. Apply the narrowed lint scopes and `min_calls`, and set `REAL_MODULES` in the stubs test (S2-R42).
  2. Wire heal in `_main` after the family loop: the `HealSender` adapter over `offer` with `severity_for`, and the heal outcome folded into the exit code (S3-R18).
  3. Run the full gate (`scripts/ci/run_tests_no_egress.sh; echo EXIT=$?`), `lint-imports` from the tree, and `git diff --stat -- deploy/systemd` (must be empty).
  4. Run the §4a mutation table.
  5. SEC review (mandatory: `table.py`, `bwrap.py`, `self_probe.py`, `studies_lock.py`) and python review.

**Every brief carries:**
- the invariants: Nautilus is immutable; `allow_short=False`; no safety, settlement or contract test is weakened; no operator cap is assigned; no change to live enablement or the NO-SEND firewall;
- `PYTHONPATH=<worktree>/src`;
- "format only your files";
- the exec-pin and firewall guards in each focused gate;
- the worktree fast-forwarded onto `feat/data-capture-and-risk`;
- "never take the real studies lock in a unit test".

## §7 Risk register
| # | Risk | Severity | Control |
|---|---|---|---|
| K1 | An edit to a linked unit goes live at the next `daemon-reload` | HIGH | No `deploy/systemd` diff (AC 22). Preflight checks `NeedDaemonReload`. |
| K2 | `link`/`enable` reloads implicitly and picks up another agent's pending edits | HIGH | Activation only from a clean primary tree, outside [15:55Z, 17:10Z), with a heads-up (stage 4). |
| K3 | A committed unit pages through a missing notifier | MED | Fixtures only; the lint refuses it (F3). |
| K4 | An AUT-1 row reaches the network | HIGH | `none`, with fail-closed emission (D3), the self-probe net check and V3. The closure lints. The egress flip is outside stage 3 and needs its own SEC review. |
| K5 | `--unshare-net` regresses seam B | MED | Seam B rows stay `egress` (S3-R11). Exact-set widening only. SEC review. |
| K6 | The stop hook becomes `none` | LOW | Not live (F2). Lands before WP3 step 2. |
| K7 | Heal is mis-attributed across fast restarts | MED | Matching by `instance_id`, first later invocation, decoy-line test (F19). |
| K8 | Heal never runs because the family loop consumes the budget | MED | `HEAL_RESERVE_S` carve-out. Deferral is logged. Write-once records make partial runs safe. |
| K9 | Multi-family runs overrun the ExecStart bound (F9) | HIGH | One absolute deadline (S3-R8, AC 3). |
| K10 | Leg N never sees a delivered NBP marker (F10) | MED | D11 regex; AC 19. |
| K11 | The settlement bind is shared with the live node's decisions directory | MED | RC-1 pins (names, primitive, lock file) and S3-R16 residual recorded. |
| K12 | A unit test takes the real host studies lock | MED | Injected lock; brief rule; `test_capture_audit_cli.py` forced edit. |
| K13 | `attempt_kind` is lost before stage 4 | LOW | Detail shim; stage-4 item 5. |
| K14 | `open_station_catalog` hits `EROFS` | LOW | V7; read-only-base test. |
| K15 | Cold-run memory of 710 MB against 768M | MED | Studies slice; one heavy job at a time. |
| K16 | Operator controls, live enablement, permit, NO-SEND | — | Never touched. `test_operator_control_assignment_scan.py` unedited. |

## §8 Host V-steps
Run outside 16:30–17:10Z, with no `daemon-reload` and no unit files.
1. **Preflight.** `date -u`. Check `NeedDaemonReload=no` on the linked `breezy-*` units. Confirm `find ~/.config/systemd/user -lname '*breezy-capture*'` is empty.
2. **Provision (S3-R23).** `install -d -m 0700 ~/.local/share/breezy/{evidence/capture/{audit,heal,heal_alert_abandoned,live_proof},cache/capture_audit,cache/capture_audit_bus,derived/verdicts}`. `evidence/` and `derived/verdicts/` are absent today (F18). Confirm the mode seam A's `AutonomyPaths` expects for `derived/verdicts`, and verify `catalog/quote_tape/decisions` is uid-owned with no 0o022 bits.
3. **Self-probe through the real wrapper (S3-R10).** For each of the three rows: `systemd-run --user --wait --pipe --collect --unit=<row> -p TimeoutStartSec=120 deploy/systemd/breezy-autonomy-bwrap <row> .venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli`. Expect `ok:true`, no `net_*` failure, and the facts `198.51.100.7:80 → ENETUNREACH` and `net_ifaces == ["lo"]`.
   - **Negative control:** the `breezy-autonomy-selftest` (`egress`) row records a non-`lo` interface.
4. **Journal access.** In the audit row: `python3 -I -c` connect to `127.0.0.53:53` should give `ECONNREFUSED`. `/usr/bin/journalctl --user -u breezy-quote-tape.service -o json -n 5` should be readable.
   - Measure the largest single-day recorder journal over the last 14 days; it must be under 128 MiB (half the cap).
   - Retention is at least 3 days (the oldest entry is 2026-09-02).
5. **Bus handoff.** Use the seam B V17 transient method, then run the audit CLI with no family. Expect "no family to audit", exit 0, no writes and the snapshot consumed.
6. **Lock contention (quiet window, stage-2c overlay, `--family-id` scratch).** Another shell holds `%t/breezy-studies.lock` for 120 s. Expect no `bus_snapshot_stale` and the run to proceed after release.
7. **Settlement row.** Import `capture_settlement_cli`, then run `open_station_catalog` on an existing station against the read-only base. Expect no `EROFS`.
8. **No real writes until activation.** No real settlement or audit `--family-id` writes until stage 4.

## §9 Stage-4 hookup checklist (S3-R19; recorded in the build rulings) and open items
**Stage 4 (AUT-1 WP5 stage 4)** runs after AUT-6, and before or inside WP8's train, whichever comes first.
1. **Preconditions:**
   - the `breezy-autonomy-failed@` row and unit merged, and that row in `NOTIFIER_FALLBACK_ROWS`;
   - `deliver_with_proof`, `AlertOutbox` and the notifier markers merged;
   - the V-11 re-measure;
   - WP3 step 2 for real leg-W kills.
2. **Promote units.** Move the fixtures into `deploy/systemd/` and drop the stand-in row. `lint_units(deploy/systemd, AUTONOMY_BWRAP_TABLE) == ()`.
3. **`AUTONOMY_OWNED_UNITS`** gains the three services; `validate_table` passes.
4. **Alerts bind.** Add the `evidence/alerts` spool bind to the three rows. They stay `network="none"` and `resolves_dns=False`. File the E-7e(f) amendment: "`resolves_dns=True` on every row that can deliver" excludes spool-only rows.
5. **Outbox injection.** Replace `_undeliverable_offer` in the three CLIs with AUT-6's outbox offer. `HealSender` passes `attempt_kind` natively, and the detail shim is removed.
6. **Real ledger.** The contract readers run against live `evidence/alerts/<date>/*_d.json` and the notify markers. The pending contract file is renamed `test_*` and goes GREEN against AUT-6's writer.
7. **Coordinator erratum against AUT-6 r15** (S2-R19 / R-3, filed, never a brief edit): marker shapes `<unit>__<InvocationID>.delivered.json` and `NBP_CYCLE_MISSED__<cycle_ns>.delivered.json`.
8. **Any `egress` flip:** its own SEC review plus an exfiltration test.
9. **Reviews.** SEC and python review of the hookup diff.
10. **Activation.** K1/K2 preflight, then link and enable outside the window, with a one-line heads-up. Observe the first 13:35, 13:50 and 14:35 runs.
11. **WP9 contract.** The drill writes `drill/<date>.json` before injecting.

**RULING-CONFLICT RC-1 (S3-R16, "settlement writes only through `write_once` (O_EXCL)").**
- Evidence:
  - the merged settlement writer rewrites each day through `replace_atomic` and creates `.capture_settlement.lock` (`capture_settlement.py:19-21,47,83,211,405`);
  - the lint row admits `_acquire_lock` and `replace_atomic` (`capture_closure_lint.py:164-167`);
  - WP5-R2 accepted both.
- **Proposed amendment.** Pin that the settlement closure's only writes are:
  - `replace_atomic` onto names from `settlement_file_name` (`settlement_<ISO date>.jsonl`), with the existing bytes preserved as a prefix and the temp file in the same directory;
  - an `O_CREAT` of the literal `LOCK_FILE` only.

  No other name and no `write_once` claim.

**RULING-CONFLICT RC-2 (S3-R23, "every file stays ≤ 800 lines").**
- Evidence: three files are already over 800 at base: `test_autonomy_bwrap_argv.py` 1021, `test_autonomy_self_probe.py` 892, `test_autonomy_units_wrapped.py` 829. S3-R10 and S3-R11 force edits to all three.
- **Proposed amendment.** New files, and files at or under 800 at base, stay at or under 800. A file over 800 at base takes only its forced lines (at most +6) and no new tests. Splitting those three files is filed as a follow-up.

**Note on S3-R1's real-line fixture.** No real `UNIT_RESULT=watchdog` line exists on this host (F7). The fixture copies the real 2026-09-05 `timeout` kill line verbatim; the watchdog variant changes only `UNIT_RESULT` and is labelled derived. This meets S3-R1 as written, so it is not a conflict.

**Erratum needed (S3-R10).** The new `net_reachable` and `net_iface_visible` codes extend the E-7e(d) vocabulary. File a coordinator erratum. The R-4 carve-out extends to `self_probe.py` and `studies_lock.py`, under mandatory SEC review.

Key paths:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-WP5-stage3-design.md`
- `/home/jon/breezy/src/breezy/analysis/capture_audit{,_cli,_host,_inputs,_input_types,_stream_legs}.py`
- `/home/jon/breezy/src/breezy/persistence/autonomy/capture_alerts.py`
- `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/{table,bwrap,self_probe}.py`
- `/home/jon/breezy/tests/support/capture_closure_lint.py`

---

## Coordinator rulings on r2 (2026-10-04)
- **RC-1 ACCEPTED.** The settlement pin is: `replace_atomic` onto `settlement_file_name` names only, keeping the existing bytes as a prefix, plus an `O_CREAT` of the literal `LOCK_FILE`. This amends S3-R16. WP5-R2 governs the settlement writer.
- **RC-2 ACCEPTED.** Files over 800 lines at base take only their forced lines, at most +6, and no new tests. Splitting `test_autonomy_bwrap_argv.py`, `test_autonomy_self_probe.py` and `test_autonomy_units_wrapped.py` is a follow-up.
- **New reason codes ACCEPTED.** `net_reachable` and `net_iface_visible` are filed as an erratum to the E-7e(d) vocabulary. The R-4 carve-out covers `self_probe.py` and `studies_lock.py`, with SEC review mandatory.
- **F10, leg N cannot see a decimal NBP marker.** This is a merged-code defect. It fails closed today, and S2 fixes it through D11.

## Round-2 peer review resolution (coordinator, 2026-10-04; SEC APPROVE, ARCH and python REQUEST_CHANGES; binding, amends r2)

### Run structure (replaces r2's D2 steps 3–5, the S3-R8 placement and the heal floor and reserve)
- **S3-R24, one deadline owner.**
  - `_main` owns a single `DEADLINE` token in float monotonic seconds. It covers heal, the family loop and the duties.
  - The `run_audit(..., deadline_s: float)` seam is renamed from `deadline_ns`, and `run_audit` never sets or resets `DEADLINE`.
  - Duties that do not depend on the family, such as `_check_settlements` / `CAPTURE_SETTLEMENT_MISSING`, run ONCE per run, inside the deadline.
  - Add a test: N families give one `SETTLEMENT_MISSING` send.
- **S3-R25, heal runs first.**
  - Heal runs BEFORE the family loop, after the lock is taken. It runs even with ZERO families: the family-enumeration early return moves after heal.
  - Heal has its own time box, `HEAL_BUDGET_S`, inside the run deadline. Exceeding it is a duty FAILURE (exit 1, paging through `OnFailure=`), never a silent deferral.
  - `HEAL_FLOOR_S`, `HEAL_RESERVE_S`, M-FLOOR and the deferral concept are deleted.
  - This removes both starvation and the lost-kill window.
- **S3-R26, fresh clock after the lock.** Re-read the clock and `today` after the lock is acquired. That fresh clock drives heal's 1800 s and 600 s boundaries, audit-file `ts_ns`, and `today`. The snapshot keeps its own `now`. Add a test with an injected clock that advances during the wait, and the mutant M-STALECLOCK.
- **S3-R27, E-9 corrected.**
  - For a oneshot unit, `TimeoutStartSec` covers the ExecStartPre lines. The audit's pre lines bound to 5 + 5 + 10 = 20 s, so ExecStart is `timeout -k 5 1475`, giving 20 + 1475 + 5 ≤ 1500.
  - The in-process bound is `exec_start + 1475 − 60`. `AUDIT_WORK_BUDGET_S` stays, with its existing pin. Document that `min(...)` makes the effective budget smaller.
  - Recompute the E-9 table and the latest ends with this rule for every unit. Tests pin BOTH literals, `TimeoutStartSec` and the `timeout` value, and their relation.

### Streams and ownership
- **S3-R28, stub pins per stream.** 3a adds empty `S1_REAL` and `S2_REAL` sets to `test_capture_audit_stubs.py`, on separate, non-adjacent lines, following the `W2_REAL` precedent. Each stream edits only its own line. 3c unions them into `REAL_MODULES`.
- **S3-R29, heal constants.** 3a freezes `HEAL_BUDGET_S` and `HEAL_JOURNAL_DAYS` in `capture_heal.py`, and S3 may read them. The time-box check lives in `run_heal_duty` (S1); 3c only calls it.
- **S3-R30, D11 extraction.**
  - 3a moves `list_names` and `_read_file` (as the public `read_file`) out of `capture_audit_inputs.py` into a new `src/breezy/analysis/capture_audit_io.py`.
  - `inputs` re-exports `list_names`, so its pinned surface stays unchanged.
  - The contract module imports `capture_audit_io`, `single_read` and the input types, and never imports `inputs`. A test pins that there is no import cycle.
  - S1 reads `list_names` from `capture_audit_io`.
- **S3-R31, write-scope gate.** 3a adds a strict-xfail test that fails while any `AUT1_WRITE_AUTHORITY` row for the heal or live-proof modules still holds `"*"`. 3c narrows the rows and removes the xfail.

### Heal correctness
- **S3-R32, growth (HIGH).**
  - Growth is measured only over non-dot entries: `*.feather` files of size > 0, plus the data subdirectories.
  - `.preflight-memo-v1.json`, `.salvaged-*`, `.converted-*` and every other dot-file are excluded.
  - Add `test_preflight_memo_and_salvage_markers_are_not_growth`, plus the mutant M-DOT.
- **S3-R33, real fixtures.**
  - F7 is corrected: the host journal holds 44 real `UNIT_RESULT=watchdog` lines, for other units. None is for the recorder.
  - The S3-R1 fixture is one real watchdog line, taken verbatim from another unit. Keep the real `timeout` line as well. Drop the "derived" variant.
  - The instance matcher reuses `_INSTANCE_MSG_RE`'s character set from `capture_node_log_decisions.py:97`.

### Security build conditions (all ACCEPTED)
- **S3-R34, probe connect.** The self-probe connect uses `SOCK_DGRAM` to the literal `198.51.100.7:80`, with a short timeout. UDP sends no packet even if isolation is broken. AC7 names the `-proc` and audit rows as the V3 cases.
- **S3-R35, settlement writes (RC-1).** Add a runtime test through the `replace` seam (`capture_settlement.py:405`). Every target must match `settlement_\d{4}-\d{2}-\d{2}\.jsonl`, the old bytes must be a prefix of the new bytes, and the only `O_CREAT` must be `LOCK_FILE`. Add a mutant.
  - Also add a test that the audit and live-proof write only capture-family verdicts into `derived/verdicts`.
- **S3-R36, lint by call position.** D10 matches calls by `(lineno, col_offset)`, not by line. Add a mutation test for two subprocess calls on one line.
- **S3-R37, closure tests.** Add a `sys.modules` subprocess closure test (no `breezy.adapters*`, `httpx`, `requests`, `aiohttp` or `urllib3`) for each of: `capture_live_proof_cli`, `capture_heal_io`, `capture_aut6_contract` and `studies_lock`.
- **S3-R38, lock helper.**
  - `acquire_studies_lock` also requires `st_nlink == 1`. Its fd is `O_CLOEXEC` and is never passed to a child process.
  - Validate `network` by type (`str`) before the DNS and fallback checks.
  - Mutants: nlink, and a non-str network value.

### Stage 4 and tests
- **S3-R39, the stage-4 checklist gains:**
  - (a) Precondition: AUT-6's spool-sender unit is live and draining.
  - (b) Precondition: the AUT-6 marker-shape erratum is merged before the real ledger (item 7 moves ahead of item 6).
  - (c) Provision `evidence/alerts`.
  - (d) Add AUT-6's outbox module to `WRITE_MODULE_FUNCTIONS`, and grant `write_imports` to the three CLIs.
  - (e) One-writer rows for the spool: AUT-1 writes outbox entries, AUT-6 writes `_d.json`.
  - (f) Re-run host V3 and V4 after the alerts bind.
  - (g) Register the audit unit in AUT-6's `IN_PROCESS_STUDIES_LOCK_UNITS` if that list is linted.
- **S3-R40, mutation and test fixes.**
  - Add the mutants M-SEV2 (ABANDONED → INFO, and an unknown event not raising), M-ANSI and M-STALECLOCK.
  - `test_delivery_send_accepts_prefixed_events` asserts `failed == 0` and that `offer` was called. F8's wording is corrected: the `KeyError` is caught and counted as a failure.
  - RC-2 addendum: a forced edit over +6 lines pulls the file split forward. The limit is never relaxed.

## Round-3 convergence resolution (coordinator, 2026-10-04; ARCH and python REQUEST_CHANGES on doc-level contradictions only, convergent; binding)
- **S3-R41, the deadline carrier** (amends S3-R24 and S3-R25).
  - `_main` sets the single ContextVar `DEADLINE` once. `run_audit` takes NO deadline parameter and only reads `DEADLINE`. The forced edit at `test_capture_audit.py:571` drives `DEADLINE` directly.
  - Heal receives a local bound, `heal_deadline = min(MONOTONIC() + HEAL_BUDGET_S, DEADLINE.get())`, passed into `run_heal_duty`. Heal never writes `DEADLINE`. A `ScanDeadline` raised inside heal, or a run past `heal_deadline`, is a duty FAILURE: exit 1.
  - Once-per-run duties, such as `_check_settlements` (currently `capture_audit.py:679`), move into `_main`. `_main` owns their `_Delivery`, and their `failed` count is folded into the exit code.
  - The family loop runs to `DEADLINE − DUTY_RESERVE_S (60)`, so the once-per-run duties keep their own reserve. A duty that hits `DEADLINE` is a failure.
- **S3-R42, the heal budget.**
  - `HEAL_BUDGET_S = 180`, frozen in 3a.
  - A pin test checks `HEAL_JOURNAL_DAYS × JOURNAL_TIMEOUT_S (90) + 30 ≤ HEAL_BUDGET_S ≤ AUDIT_EXEC_TIMEOUT_S − 60 − 600`.
  - 3a owns `AUDIT_EXEC_TIMEOUT_S = 1475`.
- **S3-R43, the stub pin union** (amends S3-R28). 3a writes `REAL_MODULES = frozenset({fill_legs}) | W2_REAL | S1_REAL | S2_REAL` now. Each stream adds its own modules to its own line. 3c only verifies.
- **S3-R44, the `capture_audit_io` surface** (amends S3-R30).
  - 3a moves `list_names` from `W3_PINNED[inputs]` to a new `W3_PINNED[capture_audit_io] = {list_names, read_file}`.
  - `list_names` is added to `W3_REEXPORTED`.
  - A new `AuthorityRow("breezy.analysis.capture_audit_io", min_calls=…)`.
  - `capture_audit_inputs.py` and `test_capture_audit_stubs.py` join 3a's EDIT set.
  - 3a measures `inputs` `ast.Call` sites before and after. The `RAISED_FLOORS` 250 is never lowered; if a move would breach it, STOP.
- **S3-R45, E-9 restated.**
  - Rule: the pre-lines' T+K (via `start_phase_bound_s`, M35) plus ExecStart's own K+T must be ≤ `TimeoutStartSec`.
  - Audit: pre lines 5 + 5 + 10 = 20, ExecStart `timeout -k 5 1475`. Latest end is 14:16:00 (it is 14:16:05 under the merged lint's per-command re-arm reading). Live-proof `OnSuccess` ends by 14:21:05 to 14:21:10. Recompute the other units the same way.
  - Tests pin `TimeoutStartSec`, the `timeout` value, the pre-line sum and their relation.
  - AC11 and M-840 use 1475. The `1500−600−60 = 840` pin stays; the effective budget is the `min()`.
- **S3-R46, zero-family runs** (amends AC5 and V5).
  - A run with no family still runs heal; only the per-family work and the settlement duty are skipped.
  - It exits 0 only if the lock and the journal are readable.
  - No heal write happens without a stall record.
  - V5 runs in a quiet window.
- **S3-R47, deletions and additions to the test and mutant lists.**
  - DELETE: `test_heal_below_floor_defers_without_failure`, M-FLOOR, AC15's deferral clause, and every "after the family loop" or "defers below the floor" wording.
  - ADD tests:
    - `test_heal_overrun_exits_one` (3c);
    - `test_heal_runs_before_family_loop`;
    - `test_heal_runs_with_zero_families`;
    - `test_n_families_one_settlement_missing`;
    - `test_clock_reread_after_lock`;
    - `test_zero_size_feather_is_not_growth`.
  - ADD mutants: M-SILENT, M-HEALLAST, M-ZEROFAM, M-ONCE.
  - Rename `test_gap_sent_first_run…`, because a gap is first sent on the run AFTER the audit that recorded it.
- **Convergence.** Three rounds have run, and all remaining items are doc-level and convergent. Next, a code-architect consolidates r2 plus S3-R24..R47 into a single build spec, r3, with no new decisions. Building follows r3.
