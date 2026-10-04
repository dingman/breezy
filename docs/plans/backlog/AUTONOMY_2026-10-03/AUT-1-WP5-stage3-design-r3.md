# AUT-1 WP5 stage 3 design — r3 BUILD SPEC (code-architect consolidation, 2026-10-04)

Consolidates r2 (`AUT-1-WP5-stage3-design-r2.md`) with RC-1/RC-2, S3-R24..R40 and S3-R41..R47, on top of r1 + S3-R1..R23 (`AUT-1-WP5-stage3-design.md`). **No new decisions.** Later rulings amend earlier ones; the latest wins. Ruling IDs are cited in brackets. Where a ruling fixed semantics but not an identifier or a file placement, r3 says so with **[editorial]** or **[derived: …]**; the coordinator may rename without changing the design.

Base `afb225d0`. HEAD `ea7e32f7` adds only the two plan docs (`git diff --name-only afb225d0..HEAD`), so the code is identical. Every line count in §3 was taken with `git show afb225d0:<path> | wc -l`.

---

## Coordinator rulings on the r3 CONFLICT notes (2026-10-04; binding, applied throughout this file)
- **C1 → S3-R48.**
  - The lint's pre-line bound is authoritative: 5 + 5 + 15 = **25** s.
  - The audit ExecStart becomes `timeout -k 5 1470`, so 25 + 5 + 1470 = **1500** ≤ `TimeoutStartSec` 1500, and the relation-pin test holds exactly.
  - `AUDIT_EXEC_TIMEOUT_S = 1470`.
  - `DEADLINE = min(lock_acquired + 840, exec_start + 1470 − 60)`, which is ≤ exec_start + 1410.
  - The latest end is still 14:16:00, or 14:16:05 including the stop time.
- **C2 → S3-R49.** "(90)" was a misstatement of the product: `JOURNAL_TIMEOUT_S` is 30 in the tree. The pin is 3 × 30 + 30 = 120 ≤ `HEAL_BUDGET_S` (180) ≤ 1470 − 60 − 600 = **810**.
- **O-1 → S3-R50.** `AUDIT_EXEC_TIMEOUT_S` lives in `src/breezy/analysis/capture_audit_model.py`, next to `AUDIT_WORK_BUDGET_S`. It is in 3a's edit set, pinned in `test_capture_audit_model.py`.
- **N1 and N2 are accepted.** There are six unit fixtures.

---

## §0 Facts checked on the tree and the host
- **F1. New unit files do nothing until linked.** Every live repo unit is linked one file at a time. Nothing links `breezy-capture-*`.
- **F2. An already-linked file is one `daemon-reload` from live.** `breezy-quote-tape.service`, `-rotate.*`, `breezy-studies.slice` and `breezy-study-failed@.service` are linked. `breezy-quote-tape.service` has no `ExecStopPost=`, so the stop-hook row is not live yet.
- **F3.** The unit lint refuses `OnFailure=breezy-autonomy-failed@` (`unit_lint.py:446-448`, `onfailure_scope`). The unit files therefore stay fixtures until stage 4.
- **F4.** `BwrapRow` (`table.py:161-183`) has no network field. `NOTIFIER_FALLBACK_ROWS` is `frozenset()` (`table.py:39`). `validate_table` (`table.py:496`) takes no fallback set.
- **F5.**
  - The catalog base `~/.local/share/breezy/catalog` (`breezy.env:9`) is under the data root that E-7e(c) re-binds read-only.
  - The settlement write target is `catalog/quote_tape/decisions` (`capture_audit_inputs.py:129`, `DECISIONS_REL`).
- **F6.** The studies lock is `/run/user/1000/breezy-studies.lock` (`%t`). Seam B re-binds it into `E7_STUDIES_LOCK` rows (`run_mounts.py:105-113`).
- **F7 [S3-R1, corrected by S3-R33].**
  - `parse_recorder_journal` reads only `INVOCATION_ID` and `_SYSTEMD_INVOCATION_ID` (`capture_audit_host.py:305`).
  - The recorder's real `UNIT_RESULT` lines on this host carry only `USER_INVOCATION_ID`. There are 30 since 2026-09-02: oom-kill 2, timeout 1, exit-code 27.
  - The host journal holds **44 real `UNIT_RESULT=watchdog` lines, all for other units**. None is for the recorder, because the recorder is not `Type=notify` yet.
  - The recorder's stdout lines carry `_SYSTEMD_INVOCATION_ID`. Their `MESSAGE` may be a byte array with ANSI codes (`tests/fixtures/recorder_watchdog/deferred_journal_line.json`).
- **F8 [S3-R2, wording corrected by S3-R40].** `_Delivery.send` indexes `CAPTURE_ALERT_SEVERITIES[event]` (`capture_audit.py:491`). The `HEALED_`/`ABANDONED_` prefixed events are not keys (`capture_alerts.py:36-57`), although `is_capture_alert_event` (`:77`) accepts them. The `KeyError` is caught and counted as a delivery failure.
- **F9 [S3-R8 defect].**
  - `run_audit` sets `DEADLINE` on every call, once per family (`capture_audit.py:699`), and resets it (`:712`). With N families, the run can last N × 840 s, past the ExecStart bound.
  - `_run_duties` runs `settlement_missing` once per family (`capture_audit.py:679-683`), after the reset, outside any deadline.
- **F10 (leg N defect).** `_NOTIFY_NAME_RE` requires a 32-hex id (`capture_audit_inputs.py:146-148`), but leg N expects a decimal `str(cycle_ns)` (`capture_audit_stream_legs.py:15-18,378-382`). A delivered `NBP_CYCLE_MISSED__<cycle_ns>` marker can never be seen, so this fails closed today. S2 fixes it through D11 [RC rulings, F10 note].
- **F11.** `_stall_records` never fills `StallRecord.heal_sha256` (`capture_audit_inputs.py:519`). The hook writes `observation_sha256` (`capture_recorder_hook_cli.py:162`). S1 reads stall records itself.
- **F12.** `_notifier_proofs` (`capture_audit_inputs.py:526-542`) is the single-read pattern that S3-R9 reuses: `list_names`, then a `ReadPolicy.REPO` read, with unreadable treated as not delivered.
- **F13.** AUT-6 per-attempt records are `evidence/alerts/<date>/<ts_ns>_<writer>_<d|f>.json`, carrying `event`, `delivered` and `schema:"alert_delivery/v1"` (AUT-6 r15 §3.6.2).
- **F14.** `HeartbeatSummary` has 4 fields (`capture_audit_input_types.py:101-107`). It is built at `capture_audit_inputs.py:398`, in `tests/support/capture_audit_fixtures.py` and in `test_capture_audit_stream_legs.py`. `_CACHE_TYPES` is at `capture_audit_cache.py:83`.
- **F15.** The journal argv[0] is the bare `"journalctl"` in three places: the templates (`capture_audit_host.py:62-97`), the `Popen` literals (`:180-215`) and the lint rows (`capture_closure_lint.py:133-138`). `/usr/bin/journalctl` exists.
- **F16 [RC-1].** Settlement writes through `replace_atomic`, plus the lock file `.capture_settlement.lock` (`capture_settlement.py:83,212,405`; lint row `capture_closure_lint.py:164-167`). WP5-R2 governs the settlement writer.
- **F17.** The C4 HEALTH verdict is skipped while the producer is unpinned (`capture_audit.py:447-450`).
- **F18.** On the host, `~/.local/share/breezy/evidence/` and `derived/verdicts/` are absent.
- **F19.** `instance_id` is logged as `BREEZY-001.TradingNode: instance_id: <uuid>`. It is followed by a decoy line, `MessageBus: config.use_instance_id=False`. The node-census matcher is `_INSTANCE_MSG_RE = ^instance_id: (?P<id>[0-9A-Za-z-]{8,64})$` (`capture_node_log_decisions.py:97`).
- **F20 [RC-2].** Three test files are over 800 lines at base: `test_autonomy_bwrap_argv.py` (1021), `test_autonomy_self_probe.py` (892) and `test_autonomy_units_wrapped.py` (829).
- **F21.** WP4 commit `2608599c` puts `injected` inside the NBP heal body, under the sha (`nbm_quantile_actor.py:540-549` @2608599c).
- **F22 (E-9 inputs).**
  - `start_phase_bound_s` sums each pre line's K+T, or `TimeoutStartSec` for an unwrapped line (`unit_lint.py:229-238`).
  - The lint also requires each pre-line bound to be below `TimeoutStartSec` (`:403-419`), and requires `TimeoutStartSec ≥ budget + 10` on a bus row (`:498-512`).
  - The snapshot line form and 2/+3 constants: `unit_lint.py:55-56,332-336`. The install and touch forms are `timeout -k 1 4` (`:50,340`).
- **F23.** `JOURNAL_TIMEOUT_S = 30.0` (`capture_audit_host.py:59`). `AUDIT_WORK_BUDGET_S = 1500 − 600 − 60` (`capture_audit_model.py:76`), pinned at `test_capture_audit.py:576` and `test_capture_audit_model.py:76`.
- **F24.**
  - `DEADLINE` is a `ContextVar[float | None]`, with `MONOTONIC = time.monotonic` (`capture_audit_inputs.py:157-158`) and `ScanDeadline` at `:152`. `list_names` is at `:207` and `_read_file` at `:182`.
  - `RAISED_FLOORS` pins `capture_audit_inputs` at 250, `capture_audit` at 150 and `capture_audit_cli` at 22, and a floor is never lowered (`test_capture_audit_stubs.py:145-159`).
  - `REAL_MODULES = {fill_legs} | W2_REAL` is at `:172`.

## §1 Design decisions
- **D1. Units are fixtures until stage 4** [S3-R19]. They live in `tests/fixtures/capture_units/` (six files, N2). No file under `deploy/systemd/` changes.

- **D2. Audit run structure and the in-process studies lock** [R-1, S3-R13, S3-R14, S3-R22, S3-R24, S3-R25, S3-R26, S3-R41, S3-R46].
  - `_main` (`capture_audit_cli.py`) runs, in this order:
    1. Record `exec_start = MONOTONIC()`.
    2. Consume the bus snapshot (`read_recorder_props`). The snapshot keeps its own `now`.
    3. Run `launch_window_guard(now, 600, 1500)` (kept conservative). A deferral exits **0** with no work.
    4. Take the studies lock with `acquire_studies_lock` (wait ≤ 600 s). `StudiesLockMissing` (ENOENT) and `StudiesLockTimeout` exit **1** with no writes, so `OnFailure=` pages.
    5. **Re-read the clock and `today`** [S3-R26]. This fresh clock drives heal's 1800 s and 600 s boundaries, the audit file's `ts_ns`, and `today`.
    6. **Set the single ContextVar `DEADLINE` once** [S3-R41]: `min(lock_acquired + AUDIT_WORK_BUDGET_S (840), exec_start + AUDIT_EXEC_TIMEOUT_S (1470) − AUDIT_MARGIN_S (60))`, in float monotonic seconds [S3-R8, S3-R27, S3-R45].
    7. **Heal runs first** [S3-R25]. `heal_deadline = min(MONOTONIC() + HEAL_BUDGET_S, DEADLINE.get())` is passed to `run_heal_duty`. Heal never writes `DEADLINE`. A `ScanDeadline` inside heal, or a run past `heal_deadline`, is a duty **FAILURE**, giving exit 1 [S3-R41]. This is wired in 3c [S3-R18].
    8. Enumerate families (`families_by_construction`). The early return moves to after heal. With **zero families** the run still has run heal; only the per-family work and the settlement duty are skipped. It exits 0 only if the lock and the journal were readable [S3-R46]. No heal write happens without a stall record.
    9. The family loop: `run_audit` per family, running to `DEADLINE − DUTY_RESERVE_S (60)` [S3-R41].
    10. The once-per-run duties, such as `_check_settlements` / `CAPTURE_SETTLEMENT_MISSING`, run **once** per run, in `_main`, inside `DEADLINE`. `_main` owns their `_Delivery`, and their `failed` count is folded into the exit code. A duty that reaches `DEADLINE` is a failure [S3-R24, S3-R41].
    11. Exit 1 on any ERROR day, failed day, failed delivery, duty failure, or heal failure.
  - `run_audit` takes **no** deadline parameter. It only reads `DEADLINE` and never sets or resets it [S3-R41].
  - Per-family duties (`stuck_inconclusive`, `live_proof_stale`) stay in `run_audit`.
  - Staging [derived: S3-R17/R41 assign the single deadline to 3a, and r2 §6 assigns the lock and budget to S3]:
    - 3a: `_main` sets `DEADLINE` once, initially `MONOTONIC() + AUDIT_WORK_BUDGET_S`, and moves the settlement duty;
    - S3: adds steps 1, 4, 5 and the `min()` value of step 6;
    - 3c: adds step 7 and moves the step-8 early return after heal.
  - **Lock helper.** New `src/breezy/runtime/autonomy_sandbox/studies_lock.py`, reusable by AUT-6's `IN_PROCESS_STUDIES_LOCK_UNITS` [S3-R13]. `acquire_studies_lock(path, *, wait_s, poll_s, monotonic, sleep) -> int`:
    - opens `O_RDONLY|O_NOFOLLOW|O_CLOEXEC`, and **never `O_CREAT`**;
    - checks with `fstat` for a regular file, owned by the euid, with `st_nlink == 1` [S3-R38];
    - polls `flock(LOCK_EX|LOCK_NB)`;
    - its fd is `O_CLOEXEC` and is never passed to a child process [S3-R38].
  - The lock path is `default_roots().run_user / STUDIES_LOCK_NAME`, the path seam B re-binds (`run_mounts.py:105-113`).

- **D3. E-15 network field** [R-4, S3-R10, S3-R11, S3-R12, S3-R34, S3-R38; reason codes per the RC ruling].
  - `BwrapRow.network: Literal["none","egress"]` is required, with no default.
  - `bwrap.argv_for` appends `--unshare-net` **unless `row.network == "egress"` exactly**, so emission fails closed.
  - `validate_table` checks, in this order:
    1. `network` is a `str` [S3-R38];
    2. it is exactly `"none"` or `"egress"`;
    3. it refuses `network == "none"` with `resolves_dns`;
    4. it refuses `network == "none"` on a fallback row, meaning `row.notifier_fallback` or a name in the new keyword `fallback_rows=NOTIFIER_FALLBACK_ROWS` [S3-R12].
  - Row values:
    - the three seam-B selftest rows are `"egress"`, their true behaviour, and are not tightened [S3-R11];
    - the AUT-1 stop hook (not live, F2) and the three capture rows are `"none"`.
  - Self-probe: `_net_failures(row, fs)` runs on `none` rows.
    - A `SOCK_DGRAM` connect, with a short timeout, to the literal `198.51.100.7:80` must give `ENETUNREACH`; otherwise the failure is `net_reachable` [S3-R34]. UDP sends no packet even when isolation is broken.
    - `/proc/net/dev` must list only `lo`; otherwise the failure is `net_iface_visible`.
    - The fact `net_ifaces` is recorded on every row.
    - `ProbeFs` gains an injectable `connect_errno`.
  - The codes `net_reachable` and `net_iface_visible` are filed as an erratum to the E-7e(d) vocabulary. The R-4 carve-out covers `self_probe.py` and `studies_lock.py`, and SEC review is mandatory [RC ruling "New reason codes ACCEPTED"].
  - The phase-2 harness (`bwrap_harness.py:163`) is untouched (MUST NOT be weakened) [S3-R10].
  - The isolation proof is the phase-1 argv test plus host V3. There is no egress-resolve test.
  - Inside a fresh netns, `127.0.0.53:53` gives `ECONNREFUSED`.

- **D4. No alerts bind and no egress in stage 3** [R-2 as amended by S3-R19]. Stage 4 adds the `evidence/alerts` spool bind. The rows stay `none`, and an AUT-6 egress unit sends from the spool. Any later flip to `egress` needs its own SEC review and an exfiltration test.

- **D5. Settlement** [WP5-R2, RC-1, S3-R16, S3-R35].
  - The catalog is read-only through the data-root re-bind. The unit passes `--catalog-base %h/.local/share/breezy/catalog` explicitly.
  - The only write bind is `catalog/quote_tape/decisions`. The residual risk is recorded: that bind is shared with the live node's decisions directory.
  - **Write pin.** The settlement closure's only writes are:
    - `replace_atomic` onto names from `settlement_file_name` (`settlement_\d{4}-\d{2}-\d{2}\.jsonl`), with the old bytes kept as a prefix of the new bytes and the temp file in the same directory;
    - an `O_CREAT` of the literal `LOCK_FILE` only.
  - There is no other name and no `write_once` claim [RC-1].
  - The pin is enforced by a runtime test through the `replace` seam (`capture_settlement.py:405`) [S3-R35].
  - The audit and live-proof write only capture-family verdicts into `derived/verdicts` [S3-R16, S3-R35].

- **D6. Heal** [S3-R3..R6, S3-R9, S3-R25, S3-R26, S3-R29, S3-R32, S3-R33, S3-R41, S3-R42, S3-R46]. A pure planner `capture_heal.py` plus I/O `capture_heal_io.py`.
  - **Constants (frozen in 3a, readable by S3)** [S3-R29, S3-R42]:
    - `HEAL_BUDGET_S = 180`;
    - `HEAL_JOURNAL_DAYS = 3`;
    - pin: `HEAL_JOURNAL_DAYS × JOURNAL_TIMEOUT_S + 30 ≤ HEAL_BUDGET_S ≤ AUDIT_EXEC_TIMEOUT_S − 60 − 600`. With the tree value it is 3 × 30 + 30 = 120 ≤ 180 ≤ 810. [S3-R49]
  - **When it runs:** once per audit run, from `_main`, after the lock and the fresh clock and **before the family loop**. It also runs with zero families. It is wired in 3c [S3-R18, S3-R25, S3-R46].
  - **Time box** [S3-R29, S3-R41]. The check lives in `run_heal_duty(…, heal_deadline)` (S1); 3c only calls it. Overrunning, or `ScanDeadline`, is a FAILURE (exit 1). There is no floor, no reserve, and no deferral.
  - **Journal** [S3-R3]. `run_journal(RECORDER_JOURNAL_ARGV)` reads one UTC day at a time over the last `HEAL_JOURNAL_DAYS` days. Each read is under the 256 MiB cap (`capture_audit_host.py:133`). Write-once records make the older days idempotent.
  - **Matching** [S3-R5, S3-R33].
    - Watchdog kills are parsed `UNIT_RESULT=watchdog` entries, keyed by `USER_INVOCATION_ID` through the fixed host parser.
    - The restart is the **FIRST** later invocation (`_SYSTEMD_INVOCATION_ID`) that meets both conditions:
      - its decoded `MESSAGE` (byte array, ANSI codes and timestamp prefix stripped) matches `TradingNode: instance_id: <id>`, using `_INSTANCE_MSG_RE`'s character set (F19), and never the `use_instance_id` decoy;
      - it has `live/<id>/config.json`.
    - Matching is never by time window.
  - **Confirmation** [S3-R4, S3-R32, S3-R26]. All three must hold, on the fresh post-lock clock:
    - `now ≥ restart_ns + 1800 s`;
    - **growth ≥ 900 s**, where growth is the newest entry mtime minus the `config.json` mtime, taken **only over non-dot entries**: `*.feather` files of size > 0, plus the data subdirectories. `.preflight-memo-v1.json`, `.salvaged-*`, `.converted-*` and every other dot-file are excluded;
    - no later watchdog kill within 1800 s of the restart.
  - **Record.** `evidence/capture/heal/<kill-date>/<kill_ts_ns>_audit_breezy-quote-tape.json`, written with `write_once`. It carries the stall record's `observation_sha256`, `invocation_id`, `unit_result:"watchdog"` (copied from the parsed entry) and `decided_by:"systemd_watchdog"`.
  - **`injected`** [S3-R6]: read at first write only. A record whose name exists is never rebuilt; only its invariant fields are verified. A later drill file never causes `EXISTS_DIFFERENT`.
  - **No stall record:** no heal is written, and leg W carries the kill [S3-R46].
  - **Delivery truth** [S3-R9, D11]. `capture_aut6_contract.delivered_events(data_root, first, last)`:
    - scans `evidence/alerts/<date>/` for `DELIVERY_RECORD_NAME_RE` (`…_d.json`) records with `schema:"alert_delivery/v1"` and `delivered is True`, and returns their events;
    - uses the F12 single-read pattern;
    - treats a missing or unreadable record as not delivered, so it fails closed toward a re-send.
    An uncollected pending contract pins AUT-6's writer.
  - **Sender** [S3-R2]. Heal I/O receives `HealSender.send(event, detail, attempt_kind) -> bool` and never imports `_Delivery`. Until stage 4, the 3c adapter carries `attempt_kind` in `detail` (§9).

- **D7. Re-send and abandon** [plan §3.11.6, S3-R7, R-3, S3-R22, S3-R47].
  - Re-sends carry `attempt_kind="retry"`. Node (NBP) records are re-sent only once they are older than 600 s, on the fresh clock.
  - Gaps come from `watchdog_evidence_gaps` in audit files over [today−30, today−1], re-checked now against the stall record and the notifier marker. A gap whose evidence has since appeared is dropped. **A gap is first sent on the run after the audit that recorded it** [S3-R47].
  - Gap abandon key: `sha256("breezy-quote-tape.service\0" + InvocationID)`. The event is `CAPTURE_HEAL_ALERT_ABANDONED_<key>`, with `gap=…` in `detail`, and the marker is `heal_alert_abandoned/gap_<key>.json`. The plan's §3.16 row is updated.
  - Abandon order: the marker is written only after `delivered=true`.
  - Age-out at 30 days applies to both heals and gaps. It emits `CAPTURE_HEAL_UNABANDONED heal=|gap=<sha>`, plus `heal_alert_unabandoned_count` and `gap_alert_unabandoned_count`.
  - Leg-W re-sends read audit files and evidence, never the journal [S3-R3].

- **D8. Live proof** [S3-R21; plan §6, §3.11.5].
  - The roll-up per family covers:
    - qualifying days: 7 days and at least 5 real fills;
    - a stale INCONCLUSIVE (age > `BACKFILL_DAYS`) breaks the run, while a fresh one is pending and neither counts nor breaks;
    - a watchdog heal paired with its stall record (same sha and invocation), its `UNIT_RESULT` (the heal record's journal-derived fields) and its AUT-6 marker (contract reader);
    - the NBP-heal alternative;
    - `CAPTURE_HEALED_<sha>` delivered within [heal date, +8 d].
  - DEADMAN reads the newest audit file, not the C4 verdict (F17).
  - DEADMAN and FILE_MISSING are deduped per `asof` by a write-once `live_proof/sent/<asof>/<event>_<family>.json`, written only after `accepted=True`. Each check runs in its own `try`, and a failed delivery exits 1.
  - Output is `live_proof_<family>_<asof>.json`, written through `replace_atomic` at 0444. The CLI defers inside the launch window.

- **D9. R5 summary** [S3-R20].
  - `HeartbeatSummary.write_drops: int` is required, with no default, and is filled at `capture_audit_inputs.py:398`.
  - `leg_r5` reads it, and `_write_drops` is deleted.
  - **No codec bump**, because summaries are not in `_CACHE_TYPES`; a test pins this.
  - `test_nonzero_write_drops_fails_stream_write_dropped` is re-targeted at the summary. This is a re-target, not a weakening.

- **D10. Lint hardening** [S3-R15, S3-R36]. An argv-matched call is admitted only if all of these hold:
  - it is `subprocess.run` or `subprocess.Popen`, by attribute;
  - `len(call.args) == 1`;
  - the argv list has no `Starred` element;
  - it has no `*` or `**`;
  - its keywords are a subset of `ALLOWED_SUBPROCESS_KWARGS = {"stdout","stderr"}`, with values from `STDIO_CONSTANT_REFERENCES`.

  The aliased and `from subprocess import Popen` forms are refused. Calls are matched by `(lineno, col_offset)`, not by line [S3-R36]. argv[0] is `/usr/bin/journalctl` in the templates, the `Popen` literals and the rows; 3a pins it.

- **D11. AUT-6 key shapes** [S2-R19, S3-R9, S3-R30, S3-R44]. `capture_aut6_contract.py` holds:
  - `NOTIFIER_MARKER_RE` (unit plus 32-hex);
  - `NBP_MISSED_MARKER_RE` (`NBP_CYCLE_MISSED__\d{1,20}`), which fixes F10;
  - the delivery-record constants;
  - `read_notifier_proofs` (extracted from `inputs`), which `inputs` imports;
  - `delivered_events`.

  The contract module imports only `capture_audit_io`, `single_read` and the input types, and **never** `capture_audit_inputs`; a test pins that there is no cycle. `capture_audit_io.py` (new, created by 3a) holds `list_names` and `read_file` (formerly `_read_file`), moved from `inputs`. `inputs` re-exports `list_names`. The AUT-6 change is filed as a coordinator erratum against AUT-6 r15 [S3-R23].

- **D12. Units** [R-5, S3-R22, S3-R27, S3-R45].
  - Oneshot units with `TimeoutStartSec` (never `RuntimeMaxSec`) and `TimeoutStopSec=5`.
  - Timers are not `Persistent`, with the default 60 s accuracy.
  - `UMask=0077`, `OnFailure=breezy-autonomy-failed@%n.service`, no `alerts.env` re-bind.
  - Interpreter: `/home/jon/breezy/.venv/bin/python3 -I -m …`.
  - Own-lock memory sum: 512 + 256 + 64 + 64 = **896M** against ARCH §5.2's 4G.

**E-9 table [S3-R45].**
- **Rule:** P + X ≤ S, where:
  - P = `start_phase_bound_s(unit)`, the sum of the pre lines' K+T;
  - X = ExecStart's own K+T;
  - S = `TimeoutStartSec`.
- **Latest end** = OnCalendar + 60 s accuracy + min(P+X, S), with + `TimeoutStopSec` 5 for the kill path. Both columns are shown. S3-R45 states the audit as "14:16:00 (14:16:05 under the merged lint's per-command re-arm reading)".
- The `OnSuccess=` run has no calendar accuracy term.
- Pre-line K+T values come from the lint's dictated forms (F22): install `timeout -k 1 4` = 5, touch `timeout -k 1 4` = 5, snapshot `timeout -k 2 (B+3)` = 2 + 13 = 15 at B = 10.

| Unit | Start | Pre lines → P (lint) | ExecStart → X | S | P+X ≤ S | Memory | Start-phase end | +Stop 5 |
|---|---|---|---|---|---|---|---|---|
| `breezy-capture-settlement` | 13:35 | install 5 → **5** | `timeout -k 5 290` → `flock -w 30 %t/breezy-capture-settlement.lock` → wrapper: 5+290 = **295** | 300 | 300 ≤ 300 ✓ | `MemoryMax=512M` | 13:35:00+60+300 = **13:41:00** | **13:41:05** |
| `breezy-capture-audit` (`Slice=breezy-studies.slice`) | 13:50 | install 5 + touch 5 + snapshot 15 → **25** [S3-R48] | `timeout -k 5 1470` → wrapper (in-process lock): 5+1470 = **1475** | 1500 | 25+1475 = **1500 ≤ 1500 ✓** [S3-R48] | `MemoryHigh=768M`, `MemoryMax=1G` | 13:50:00+60+min(·,1500) = **14:16:00** (both readings, capped by S) | **14:16:05** |
| `breezy-capture-live-proof` (`OnSuccess=`) | audit end, 14:16:00 or 14:16:05 | install 5 → **5** | `timeout -k 5 290` → `flock -w 30 %t/breezy-capture-live-proof.lock` → wrapper: **295** | 300 | 300 ≤ 300 ✓ | `MemoryMax=256M` | 14:16:00+300 = **14:21:00** or 14:16:05+300 = 14:21:05 | **14:21:05 … 14:21:10** |
| `breezy-capture-live-proof` (fallback timer) | 14:35 | install 5 → **5** | **295** | 300 | 300 ≤ 300 ✓ | 256M | 14:35:00+60+300 = **14:41:00** | **14:41:05** |

- Further lint checks:
  - every pre-line bound (5 or 15) < S ✓ (`unit_lint.py:403-419`);
  - audit S = 1500 ≥ B + 10 = 20 ✓ (`:498-512`).
- No unit meets [16:30Z, 17:10Z).
- Tests pin `TimeoutStartSec`, the `timeout` value, the pre-line sum (via `start_phase_bound_s`) and their relation [S3-R45]; see C1.

**In-process budget** [S3-R8, S3-R27, S3-R41, S3-R45].
- `DEADLINE = min(lock_acquired + 840, exec_start + 1470 − 60)`.
- `AUDIT_WORK_BUDGET_S` stays 840 with its existing `1500 − 600 − 60` pin (F23). The effective budget is the `min()`, which makes it smaller.
- Worst case:
  - lock wait 600, so `lock_acquired ≤ exec_start + 600`;
  - the first term ≤ exec_start + 600 + 840 = exec_start + 1440;
  - the second term = exec_start + 1410;
  - so `DEADLINE ≤ exec_start + 1410`, leaving 60 s of margin before the ExecStart `timeout` of 1470.
- After a full 600 s wait the effective work budget is 1410 − 600 = **810** s. That is the S3-R42 upper bound on `HEAL_BUDGET_S`.
- Inside it:
  - heal is bounded by `min(now + 180, DEADLINE)`;
  - the family loop runs to `DEADLINE − 60`;
  - the once-per-run duties use the last 60 s.

**Rows** (`network="none"`, `resolves_dns=False`):
- settlement: `catalog/quote_tape/decisions`;
- audit: `evidence/capture/{audit,heal,heal_alert_abandoned}`, `derived/verdicts` and `cache/capture_audit`, plus `bus_snapshot_bind=cache/capture_audit_bus` and `AUDIT_BUS_READS` named `AUDIT_BUS_READ_NAMES`, with `studies_lock=True`, `E7_STUDIES_LOCK` and `bus_snapshot_budget_s=10`;
- live-proof: `evidence/capture/live_proof`.

## §2 Acceptance criteria
1. **Invocation id** [S3-R1, S3-R33]. `parse_recorder_journal` takes `USER_INVOCATION_ID` first, then the existing fallbacks. An entry with an empty id raises `journal_failed`. Both the real watchdog line (another unit, verbatim) and the real `timeout` line parse.
2. **Severity** [S3-R2, S3-R40]. `severity_for` returns:
   - INFO for HEALED;
   - CRITICAL for ABANDONED;
   - the dict value otherwise;
   - and it raises on an unknown event.

   `_Delivery.send` uses it. A prefixed event gives `failed == 0`, and `offer` is called.
3. **One deadline** [S3-R24, S3-R41]. `_main` sets `DEADLINE` once, and `run_audit` takes no deadline parameter and only reads it. Every family and heal see the same instant. Heal gets a local `heal_deadline`. The family loop stops at `DEADLINE − 60`. Once-per-run duties run once, so N families give one `SETTLEMENT_MISSING` send.
4. **Lock** [S3-R13, S3-R38]. The helper:
   - never creates the file;
   - refuses a symlink;
   - refuses `st_nlink != 1`;
   - takes `LOCK_EX`;
   - uses an `O_CLOEXEC` fd.

   Phase 2: it succeeds alone, and gives `EWOULDBLOCK` while the host holds the lock.
5. **CLI order** [S3-R14, S3-R25, S3-R26, S3-R46]. The order is snapshot → window guard → lock → fresh clock → `DEADLINE` → heal → families → loop → once-per-run duties.
   - A 600 s wait does not stale the snapshot.
   - A lock timeout or missing lock exits 1 with no writes.
   - A window deferral exits 0.
   - Zero families still run heal, and exit 0 only if the lock and the journal are readable.
6. **Network field** [S3-R11, S3-R12, S3-R38]. Every row declares `network`. Emission happens unless the value is exactly `"egress"`. These are refused:
   - a non-`str` value;
   - an unknown value;
   - `none` with `resolves_dns`;
   - `none` in a fallback set.
7. **Self-probe net check** [S3-R10, S3-R34]. On `none` rows the probe (`SOCK_DGRAM` to `198.51.100.7:80`) fails `net_reachable` or `net_iface_visible` (phase 1, injected). The host V3 proves `ENETUNREACH` and `lo` only through the real wrapper. **AC7's V3 cases are the `-proc` row and the audit row.**
8. **Rows.** The three rows validate, bind exactly the planned directories, never bind the catalog base, and their bus reads equal `AUDIT_BUS_READ_NAMES`.
9. **Lint scope.** The fixture units pass `lint_units` with a stand-in AUT-6 row. Against the real table, they fail only on `onfailure_scope`.
10. **Calendar** [S3-R45]. The calendar tests pass. The E-9 values recompute exactly from the fixture files through `start_phase_bound_s`. The relation P + X ≤ S is pinned (see C1).
11. **Budget** [S3-R45]. The work budget derives from the unit literal **1470** (`AUDIT_EXEC_TIMEOUT_S`). The `1500 − 600 − 60 = 840` pin stays, and the effective budget is the `min()`.
12. **Heal confirmation** [S3-R4, S3-R5, S3-R32]. Heal confirms only under §3.10.3 + S3-R4, matching by `instance_id` (the first later invocation). The boundaries at 899/900 s and 1799/1800 s hold. Dot-files and zero-size feathers are not growth.
13. **Heal records** [S3-R6]. Records are write-once, and a rerun is a no-op. A late drill file never causes a difference. `injected` is taken at first write.
14. **Re-send** [S3-R7, S3-R47]. Heals and gaps are re-sent daily with `retry`.
    - A gap is first sent on the run after the audit that recorded it.
    - The node 600 s minimum age holds.
    - Abandon order: the marker is written only after `delivered=true`.
    - Heals and gaps both age out at 30 days.
    - A gap with late evidence is not re-sent.
15. **Heal run** [S3-R3, S3-R25, S3-R41, S3-R46, S3-R47]. Heal runs once per run, **before the family loop**, and also with zero families. It reads 3 days, one day at a time. Exceeding `heal_deadline`, or raising `ScanDeadline`, exits 1.
16. **Live proof** [S3-R21]. It implements §6 and uses DEADMAN on the audit file. It dedupes per `asof`. Each check is in its own `try`, and a failed delivery exits 1.
17. **R5** [S3-R20]. R5 uses `HeartbeatSummary.write_drops`, with no default and no `boot.stream()` call. `_CACHE_TYPES` excludes the summaries.
18. **Lint hardening** [S3-R15, S3-R36]. The lint refuses the D10 set and matches by call position. argv[0] is `/usr/bin/journalctl`. Every pre-existing lint test passes unedited.
19. **AUT-6 shapes** [D11, S3-R30]. Leg N and leg W read both marker shapes, plus the delivery-record shape, from fixtures; F10 is fixed. The contract module has no import cycle with `inputs`. The pending AUT-6 contract fails when run by path.
20. **Retention.** `settlement_` and `fq_funnel_` names never match the retention gzip regexes.
21. **Closures** [S3-R16, S3-R35, S3-R37, RC-1].
    - The new modules import no adapter, `httpx`, `ingest` or `resolver`, and never reference `state/`, the exec store or the permit.
    - A `sys.modules` subprocess closure test (no `breezy.adapters*`, `httpx`, `requests`, `aiohttp` or `urllib3`) passes for `capture_live_proof_cli`, `capture_heal_io`, `capture_aut6_contract` and `studies_lock`.
    - The settlement write pin (D5) holds at runtime.
    - The audit and live-proof write only capture-family verdicts into `derived/verdicts`.
    - The write-scope strict-xfail is removed in 3c with every row narrowed [S3-R31].
22. **No live units.** `git diff --stat -- deploy/systemd` is empty, and no linked unit changes.
23. **Gate.**
    - `EXIT=0`;
    - `lint-imports` prints "N kept, 0 broken";
    - the exec-client sha is unchanged;
    - the firewall and operator-control tests are unedited;
    - no `RAISED_FLOORS` entry is lowered [S3-R44];
    - every file meets the RC-2 size rule (§3).

## §3 File table
Key: N = new, E = exists. Base = line count at `afb225d0`. "→" is r2's estimate after the change, where r2 gave one.

**RC-2 size rule.**
- New files, and files at or under 800 lines at base, stay at or under 800.
- A file over 800 at base takes only its forced lines (at most +6) and no new tests.
- A forced edit of more than +6 lines pulls the file split forward; the limit is never relaxed [S3-R40].
- Splitting the three files over 800 is a follow-up.

| File | | Owner (in order) | Base | Change |
|---|---|---|---|---|
| `src/breezy/analysis/capture_audit_host.py` | E | 3a | 414 → ~425 | S3-R1 parser; argv[0] `/usr/bin/journalctl` |
| `src/breezy/persistence/autonomy/capture_alerts.py` | E | 3a | 83 → ~95 | `severity_for` |
| `src/breezy/analysis/capture_audit.py` | E | 3a | 720 → ~728 | `send` via `severity_for`; `run_audit` reads `DEADLINE` only (no set/reset, no deadline parameter); `_check_settlements` leaves `_run_duties`; loop to `DEADLINE − DUTY_RESERVE_S`. `RAISED_FLOORS` 150 never lowered |
| `src/breezy/analysis/capture_audit_cli.py` | E | 3a → S3 → 3c | 99 → ~175 | 3a: sets `DEADLINE` once, runs the once-per-run duties with its own `_Delivery`. S3: lock, `exec_start`, fresh clock, `min()` deadline. 3c: heal wiring, early return after heal, exit fold |
| `src/breezy/analysis/capture_audit_inputs.py` | E | 3a → S2 | 769 → ~750 | 3a: move `list_names`/`_read_file` out and re-export `list_names` [S3-R44]. S2: extract the marker reader to the contract module; `write_drops` fill. Floor 250 never lowered (STOP if breached) |
| `src/breezy/analysis/capture_audit_io.py` | N | 3a | — | `list_names`, `read_file` [S3-R30, S3-R44] |
| `src/breezy/analysis/capture_heal.py` | N | 3a stub + constants → S1 | → ~330 | pure planner; `HEAL_BUDGET_S=180`, `HEAL_JOURNAL_DAYS=3` frozen by 3a |
| `src/breezy/analysis/capture_heal_io.py` | N | 3a stub → S1 | → ~380 | I/O, `run_heal_duty(…, heal_deadline)` |
| `src/breezy/analysis/capture_live_proof.py` | N | 3a stub → S2 | → ~300 | roll-up |
| `src/breezy/analysis/capture_live_proof_cli.py` | N | 3a stub → S2 | → ~200 | CLI |
| `src/breezy/analysis/capture_aut6_contract.py` | N | 3a constants → S2 | → ~150 | D11 shapes and readers |
| `src/breezy/analysis/capture_audit_model.py` (`AUDIT_EXEC_TIMEOUT_S = 1470`) and `tests/unit/test_capture_audit_model.py` | E | 3a | — | [S3-R50] |
| `src/breezy/analysis/capture_audit_input_types.py` | E | S2 | 314 → ~316 | `write_drops` |
| `src/breezy/analysis/capture_audit_stream_legs.py` | E | S2 | 436 → ~430 | R5; leg N via the contract module |
| `src/breezy/runtime/autonomy_sandbox/table.py` | E | S3 | 513 → ~600 | field, checks, 3 rows |
| `src/breezy/runtime/autonomy_sandbox/bwrap.py` | E | S3 | 517 → ~520 | emission |
| `src/breezy/runtime/autonomy_sandbox/self_probe.py` | E | S3 | 525 → ~565 | net check |
| `src/breezy/runtime/autonomy_sandbox/studies_lock.py` | N | S3 | → ~90 | D2 helper |
| `tests/support/capture_closure_lint.py` | E | 3a rows → S2 engine → 3c narrowing | 536 → ~600 | 3a: 5 rows at `"*"`/`min_calls=1`, `AuthorityRow("breezy.analysis.capture_audit_io", …)`, `_journal_argv` argv[0]. S2: D10 engine. 3c: narrowed scopes and `min_calls` |
| `tests/support/bwrap_host_phase.py` | E | S3 | 469 → ~470 | registry gains the phase-2 file; 34 → 36 tests |
| `tests/support/capture_audit_w3_fixtures.py` | E | S3 (forced) | 561 → ~562 | `network=` |
| `tests/support/capture_audit_fixtures.py` | E | S2 (forced) | 201 → ~202 | `write_drops=` |
| `tests/fixtures/capture_units/breezy-capture-{settlement,audit,live-proof}.{service,timer}` (6) | N | S3 | small | D12 (N2) |
| `tests/fixtures/capture_heal/nbp_heal_wp4_2608599c.json` | N | 3a | small | WP4 literal |
| `tests/fixtures/capture_heal/unit_result_real_timeout.json` | N | 3a | small | the real 2026-09-05 recorder `timeout` line, verbatim |
| `tests/fixtures/capture_heal/unit_result_real_watchdog.json` **[editorial name]** | N | 3a | small | one real `UNIT_RESULT=watchdog` line from another unit, verbatim [S3-R33] |
| `tests/fixtures/capture_heal/recorder_instance_lines.json` | N | 3a | small | real captured `instance_id` lines plus the decoy |
| `tests/unit/autonomy_writer_table.py` | E | 3a | 182 → ~205 | one-writer rows: heal, abandoned, live_proof, verdicts |
| `tests/unit/test_autonomy_bwrap_argv.py` | E | S3 (forced, RC-2) | **1021** → ≤ 1027 | exact set gains `--unshare-net` |
| `tests/unit/test_autonomy_units_wrapped.py` | E | S3 (forced, RC-2) | **829** → ≤ 835 | 6 constructors |
| `tests/unit/test_autonomy_self_probe.py` | E | S3 (forced, RC-2) | **892** → ≤ 898 | `FIXED_REASON_CODES` +2 |
| `tests/unit/test_autonomy_sandbox_table.py` | E | S3 (forced) | 692 → ~695 | row set (`:81`) |
| `tests/unit/test_autonomy_aut1_stop_hook_row.py` | E | S3 (forced) | 110 → ~111 | `network=="none"` |
| `tests/unit/test_capture_audit.py` | E | 3a | 688 → ~710 | `:571` drives `DEADLINE` directly [S3-R41]; deadline and once-per-run tests |
| `tests/unit/test_capture_audit_cli.py` | E | 3a → S3 → 3c | 221 → ~330 | 3a: forced edits only. S3: injected lock, lock, clock and order tests. 3c: heal-wiring tests |
| `tests/unit/test_capture_audit_stream_legs.py` | E | S2 | 609 → ~650 | re-target, F14 |
| `tests/unit/test_capture_audit_host_tape.py` | E | 3a | 503 → ~535 | S3-R1 |
| `tests/unit/autonomy/test_capture_alerts.py` | E | 3a | 115 → ~140 | `severity_for` |
| `tests/unit/test_capture_audit_stubs.py` | E | 3a → S1 (own line) → S2 (own line) → 3c | 313 → ~370 | 3a: `EXPECTED`/`EXPECTED_CONSTANTS` for the five modules; `W3_PINNED[capture_audit_io]={list_names, read_file}`; `list_names` leaves `W3_PINNED[inputs]` and joins `W3_REEXPORTED`; empty `S1_REAL` and `S2_REAL` on separate non-adjacent lines; `REAL_MODULES = frozenset({fill_legs}) \| W2_REAL \| S1_REAL \| S2_REAL`; the S3-R31 strict-xfail **[placement derived]**. S1/S2: add their modules to their own line only. 3c: remove the xfail, verify the union |
| `tests/unit/autonomy/test_capture_read_only_closure.py` | E | S2 | 371 → ~470 | D10 mutations, position matching |
| `tests/unit/test_decisions_retention.py` | E | S2 | 413 → ~430 | retention pin |
| `tests/unit/test_capture_units.py` | E | S3 | 56 → ~260 | calendar, E-9, budget |
| `tests/unit/test_capture_heal.py`, `tests/unit/test_capture_heal_resend.py` | N | S1 | each < 500 | §4 S1 |
| `tests/unit/test_capture_live_proof.py`, `tests/unit/test_capture_live_proof_cli.py`, `tests/unit/test_capture_aut6_contract.py` | N | S2 | each < 500 | §4 S2 |
| `tests/unit/autonomy/pending_aut6_notifier_proof_contract.py` | N | S2 | small | uncollected |
| `tests/unit/test_capture_write_pins.py` **[editorial placement]** | N | S2 **[derived: S2 owns closure hardening]** | < 300 | S3-R35 settlement runtime pin plus the `derived/verdicts` pin |
| `tests/unit/test_autonomy_network_field.py`, `tests/unit/test_autonomy_self_probe_net.py`, `tests/unit/test_studies_lock.py`, `tests/unit/test_capture_sandbox_rows.py` | N | S3 | each < 500 | §4 S3 |
| `tests/integration/test_capture_studies_lock_namespace.py` | N | S3 | small | phase 2 (bwrap-host registry) |

Read-only at base, relevant: `capture_audit_model.py` (278; the 840 pin stays), `test_capture_audit_model.py` (418), `capture_settlement.py` (426), `test_capture_settlement.py` (729), `unit_lint.py`, `bwrap_harness.py` (MUST NOT be edited).

## §4 Tests and their RED reason after 3a
After 3a, a new module raises `NotImplementedError` rather than failing to import. **[editorial]** marks identifiers r3 had to name; the ruling fixed only the behaviour.

**3a**
- `test_unit_result_user_invocation_id_is_read`: fails, `invocation_id == ""`.
- `test_empty_invocation_id_is_journal_failed`: fails, the entry is accepted.
- `test_real_timeout_kill_line_parses`: fails, empty id.
- `test_real_watchdog_kill_line_parses` **[editorial]** [S3-R33]: fails, empty id.
- `test_severity_for_healed_is_info_abandoned_critical`: fails with `AttributeError`.
- `test_delivery_send_accepts_prefixed_events`: asserts `failed == 0` and that `offer` was called. Fails because the `KeyError` is caught, `failed == 1`, and `offer` is not called [S3-R40].
- `test_every_family_sees_one_absolute_deadline`: fails, `run_audit` re-arms per family.
- `test_n_families_one_settlement_missing` [S3-R47; owner derived from S3-R41]: fails, N sends.
- `test_journal_argv0_is_absolute`: fails, bare name.
- The S3-R31 strict-xfail `test_heal_and_live_proof_write_rows_are_narrowed` **[editorial]**: XFAILs (strict) while the rows hold `"*"`.
- GREEN by construction: the stub signature pins, the `W3_PINNED`/`W3_REEXPORTED` surface for `capture_audit_io`, and the `RAISED_FLOORS` pins.

**S1** (RED on `NotImplementedError` unless stated otherwise)
- Matching and confirmation:
  - `test_watchdog_kill_followed_by_streaming_instance_is_healed`
  - `test_recorder_heal_matches_restart_by_instance_id_not_time_window`
  - `test_first_later_invocation_with_config_is_the_restart`
  - `test_use_instance_id_config_line_is_not_an_instance`
  - `test_growth_899s_unconfirmed_900s_confirmed`
  - `test_restart_1799s_old_unconfirmed_1800s_confirmed`
  - `test_restart_younger_than_30min_is_unconfirmed`
  - `test_second_kill_within_1800s_is_not_healed`
  - `test_converted_markers_excluded_from_growth`
  - `test_preflight_memo_and_salvage_markers_are_not_growth` [S3-R32]
  - `test_zero_size_feather_is_not_growth` [S3-R47]
  - `test_ansi_byte_array_message_is_decoded`
- Records:
  - `test_heal_record_rerun_is_noop`
  - `test_late_drill_file_never_exists_different`
  - `test_drill_present_at_first_write_marks_injected`
  - `test_kill_without_stall_record_writes_no_heal`
- Journal and fixtures:
  - `test_journal_read_per_day_over_three_days`
  - `test_nbp_heal_fixture_2608599c_parses`
- Re-send and abandon:
  - `test_heal_resend_daily_with_attempt_kind_retry`
  - `test_node_record_younger_than_600s_not_resent`
  - `test_abandon_marker_only_after_delivered_true`
  - `test_unmarked_heal_older_than_30d_counts_unabandoned`
  - `test_gap_first_sent_on_run_after_recording_audit_and_resent_until_delivered` **[editorial; renamed per S3-R47]**
  - `test_gap_with_late_evidence_not_resent`
  - `test_gap_ages_out_at_30_days`
  - `test_gap_abandon_key_is_sha_of_unit_nul_invocation`
  - `test_ledger_missing_or_unreadable_is_not_delivered`
- Isolation:
  - `test_heal_io_never_imports_delivery_class`
  - `test_capture_heal_io_sys_modules_closure` **[editorial]** [S3-R37]: fails with `NotImplementedError`: the subprocess drives the `run_heal_duty` stub before it inspects `sys.modules`.
- **Deleted** [S3-R47]: `test_heal_below_floor_defers_without_failure`.

**S2**
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
- R5:
  - `test_r5_reads_summary_without_stream_read`: fails on the `boot.stream` spy.
  - `test_heartbeat_summary_requires_write_drops`: fails, the field is absent.
  - `test_summaries_not_in_cache_types`: passes (guard).
  - `test_nonzero_write_drops_fails_stream_write_dropped`: re-targeted at the summary; fails until the summary is filled.
- Contract:
  - `test_leg_n_reads_nbp_cycle_missed_decimal_marker`: fails, F10.
  - `test_marker_shapes_single_source`: fails, `NotImplementedError`.
  - `test_delivery_record_reader_fixture`: fails, `NotImplementedError`.
  - `test_contract_module_never_imports_inputs` **[editorial]** [S3-R30]: fails, the 3a stub carries no reader yet; the assertion covers the import graph of the filled module.
- Lint (each fails because the lint admits the case today):
  - `test_argv_call_refuses_kwarg[shell|env|executable|cwd|stdin|input|close_fds|preexec_fn|start_new_session]`
  - `test_argv_call_refuses_second_positional`
  - `test_argv_call_refuses_starred_element`
  - `test_argv_call_refuses_splat`
  - `test_from_subprocess_import_popen_refused`
  - `test_two_subprocess_calls_on_one_line_matched_by_position` **[editorial]** [S3-R36]
- Lint guards that pass:
  - `test_existing_journal_templates_still_admitted`
  - `test_retention_never_compresses_settlement_or_funnel_files` (pin)
- Closures:
  - `test_new_modules_reference_no_state_exec_or_permit`: fails, `NotImplementedError` (stub source).
  - `test_capture_live_proof_cli_sys_modules_closure` and `test_capture_aut6_contract_sys_modules_closure` **[editorial]** [S3-R37]: fail on `NotImplementedError` at the stub's entry.
- Write pins:
  - `test_settlement_writes_only_settlement_names_prefix_preserved_lock_only_ocreat` **[editorial]** [S3-R35]: passes against the merged writer as a pin; its mutant must be killed.
  - `test_audit_and_live_proof_write_only_capture_family_verdicts` **[editorial]** [S3-R35]: fails, `NotImplementedError` (live-proof stub).

**S3**
- Network field (each fails with `TypeError`, the field is absent):
  - `test_unshare_net_unless_exactly_egress`
  - `test_unknown_network_value_refused`
  - `test_non_str_network_value_refused` **[editorial]** [S3-R38]
  - `test_network_none_with_resolves_dns_refused`
  - `test_network_none_fallback_row_refused`
  - `test_every_row_declares_network`
- Self-probe (each fails, the check is absent):
  - `test_probe_none_row_reachable_fails_net_reachable`
  - `test_probe_none_row_extra_iface_fails`
  - `test_probe_egress_row_skips_net_check_records_fact`
- Studies lock (each fails, no module):
  - `test_lock_never_creates`
  - `test_lock_refuses_symlink`
  - `test_lock_refuses_nlink_not_one` **[editorial]** [S3-R38]
  - `test_lock_times_out_after_wait`
  - `test_studies_lock_sys_modules_closure` **[editorial]** [S3-R37]
- Phase 2 (each fails, the file is absent):
  - `test_studies_lock_in_row_alone_succeeds`
  - `test_studies_lock_in_row_held_by_host_ewouldblock`
- Rows (each fails, the rows are absent):
  - `test_capture_rows_bind_exactly_planned_dirs`
  - `test_settlement_catalog_base_under_data_root_not_a_bind`
  - `test_audit_bus_reads_equal_names`
- `test_capture_units.py` (each fails, the fixtures are absent):
  - `::test_no_unit_overlaps_launch_window`
  - `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`
  - `::test_no_capture_timer_is_persistent`
  - `::test_every_capture_unit_and_onfailure_target_runs_through_bwrap_wrapper`
  - `::test_capture_units_fail_lint_only_on_aut6_scope`
  - `::test_e9_latest_end_matches_table`: pins `TimeoutStartSec`, the `timeout` value, `start_phase_bound_s` and their relation. See C1.
  - `::test_audit_work_budget_derives_from_unit_timeout`: 1470.
- `test_capture_audit_cli.py` (each fails, no lock or fresh clock):
  - `::test_snapshot_consumed_before_studies_lock_wait`
  - `::test_lock_wait_600s_does_not_stale_snapshot`
  - `::test_lock_timeout_exits_one_without_writes`
  - `::test_missing_lock_exits_one_never_created`
  - `::test_clock_reread_after_lock` [S3-R26, S3-R47; owner derived: S3 owns the lock sequence]

**3c** [S3-R18, S3-R47; owner derived: 3c wires heal]. Each fails because heal is not wired.
- `test_capture_audit_cli.py::test_heal_overrun_exits_one`
- `test_capture_audit_cli.py::test_heal_runs_before_family_loop`
- `test_capture_audit_cli.py::test_heal_runs_with_zero_families`: asserts exit 0 only with the lock and the journal readable, and no heal write without a stall record.

## §4a Mutation table (one named mutant or more per test group; every one must be killed)
Mutants marked "(unnamed)" are named by behaviour, because the ruling did not name them.

| Group | Mutants |
|---|---|
| 3a parser | M-INV: drop `USER_INVOCATION_ID` · M-EMPTY: accept `""` |
| 3a severity | M-SEV: HEALED → WARNING · M-SEV2: ABANDONED → INFO, and an unknown event does not raise [S3-R40] |
| 3a deadline | M-REARM: `DEADLINE.set(MONOTONIC()+840)` per family · M-ONCE: settlement duty once per family [S3-R47] |
| 3a argv | M-ARGV0: bare `journalctl` |
| S1 confirmation | M-TIMEWIN: match by time window · M-LASTINV: last later invocation · M-DECOY: substring `instance_id` · M-GROW: `>` 900 · M-AGE: drop the 1800 s age check · M-CONV: count `.converted-*` · M-DOT: count dot-files [S3-R32] · M-ANSI: skip the ANSI/byte-array decode [S3-R40] |
| S1 records | M-INJ: rebuild `injected` on rerun · M-NOSTALL: write without a stall sha |
| S1 re-send / abandon | M-KIND: `attempt_kind="alert"` · M-NODE600: drop the node minimum age · M-EARLYMARK: marker before proof · M-GAPAGE: no gap age-out · M-LATEGAP: re-send after evidence · M-KEY: key without `\0` |
| S1 run | M-9D: one 9-day read · M-LEDGER: unreadable means delivered |
| S2 roll-up | M-6DAYS · M-4FILLS · M-INCPASS: stale INCONCLUSIVE ignored · M-PRECAP: PRE_CAPTURE counted · M-WIN9: +9-day window · M-NBPOFF |
| S2 dead-man | M-VERDICT: DEADMAN on the C4 verdict · M-DEDUPE: re-send on the fallback run · M-ONETRY: shared `try` |
| S2 R5 | M-STREAM: read `boot.stream()` · M-DEFAULT0: `write_drops=0` default · M-CODEC: add the summary to `_CACHE_TYPES` |
| S2 lint | M-KW: admit `env` · M-POS: admit 2 positional · M-STAR · M-ALIAS: admit `from subprocess import Popen` · (unnamed) [S3-R36]: match by line, not `(lineno, col_offset)` |
| S2 contract / retention | M-HEX32: NBP regex 32-hex · M-RET: gzip regex matches `settlement_` · (unnamed) [S3-R30]: contract imports `inputs` |
| S2 write pins | (unnamed) [S3-R35]: settlement writes a non-`settlement_` name, drops the prefix, or `O_CREAT`s a non-`LOCK_FILE` name |
| S3 field | M-EQNONE: emit iff `=="none"` · M-CASE: accept `"None"` · M-DNS · M-FALLBACK · (unnamed) [S3-R38]: accept a non-`str` network value |
| S3 probe | M-SKIPNET · M-ANYIFACE |
| S3 lock / CLI | M-CREAT: `O_CREAT` · M-FOLLOW: drop `O_NOFOLLOW` · (unnamed) [S3-R38]: drop the `st_nlink == 1` check · M-EXIT0: timeout exits 0 · M-ORDER: lock before snapshot · M-STALECLOCK: keep the pre-lock clock [S3-R26, S3-R40] |
| S3 units / budget | M-PERSIST · M-RUNTIMEMAX · M-STOP: drop `TimeoutStopSec` · M-840: ignore the unit literal **1470** [S3-R45] · M-BIND: extra `evidence/alerts` bind |
| 3c wiring | M-SILENT: heal overrun not counted as a failure · M-HEALLAST: heal after the family loop · M-ZEROFAM: zero families skip heal [S3-R47] |

**Deleted** [S3-R25, S3-R47]: M-FLOOR.

## §5 Blocked items
- Unit promotion and the `OnFailure=` scope: blocked by AUT-6.
- Real delivery (outbox, ledger, markers, pending contracts going GREEN): AUT-6, wired in **stage 4** [S3-R19], which supersedes WP5-R2's "WP8 injects".
- Activation: AUT-6, plus V-11 (14 FQ days on or after 2026-10-15).
- Families, live NBP heal records and live-proof accrual: WP8.
- Real recorder watchdog kills: WP3 step 2. No recorder `watchdog` line exists yet (F7).
- Drill `injected`: WP9, which must write `drill/<date>.json` before injecting.

## §6 Build streams
Streams are blind and run serial 3a → parallel S1 / S2 / S3 → serial 3c.

- **3a (serial, lands first).**
  - **EDIT:**
    - `src/breezy/analysis/capture_audit_host.py`
    - `src/breezy/persistence/autonomy/capture_alerts.py`
    - `src/breezy/analysis/capture_audit.py`
    - `src/breezy/analysis/capture_audit_cli.py` (single `DEADLINE` set, once-per-run duties)
    - `src/breezy/analysis/capture_audit_inputs.py` (move `list_names`/`_read_file`, re-export)
    - `src/breezy/analysis/capture_audit_io.py` (N)
    - `capture_audit_model.py` (`AUDIT_EXEC_TIMEOUT_S`) [S3-R50]
    - stubs with real constant values: `capture_heal.py`, `capture_heal_io.py`, `capture_live_proof.py`, `capture_live_proof_cli.py`, `capture_aut6_contract.py`
    - `tests/support/capture_closure_lint.py` (**rows section only**: 5 rows with heal and live-proof `writes=("*",)` at `min_calls=1`; the `capture_audit_io` `AuthorityRow`; `_journal_argv` argv[0])
    - `tests/unit/autonomy_writer_table.py`
    - `tests/fixtures/capture_heal/*` (4)
    - `tests/unit/test_capture_audit_host_tape.py`
    - `tests/unit/autonomy/test_capture_alerts.py`
    - `tests/unit/test_capture_audit.py`
    - `tests/unit/test_capture_audit_stubs.py`
    - `tests/unit/test_capture_audit_cli.py` (forced edits only)
  - **READ-ONLY:** `single_read`, `capture_records.py`, `capture_audit_model.py`, `capture_settlement.py`, `capture_recorder_hook_cli.py`, plan §3.10–§3.16.
  - **STOP rule.** Measure the `ast.Call` sites in `capture_audit_inputs` and `capture_audit` before and after. If the move would breach `RAISED_FLOORS` (250 / 150), STOP [S3-R44].

- **S1 (heal).**
  - **EDIT:** `capture_heal.py`, `capture_heal_io.py`, `tests/unit/test_capture_heal.py` (N), `tests/unit/test_capture_heal_resend.py` (N), and `tests/unit/test_capture_audit_stubs.py` on the **`S1_REAL` line only**.
  - **READ-ONLY:**
    - `capture_audit_host.py` (`run_journal`, `parse_recorder_journal`, `RECORDER_JOURNAL_ARGV`, `JOURNAL_TIMEOUT_S`)
    - `capture_audit_io.py` (`list_names`, `read_file`)
    - `capture_audit_inputs.py` (`DEADLINE`, `MONOTONIC`, `ScanDeadline`)
    - `capture_audit_wire.py`, `capture_audit_model.py`, `capture_alerts.py`, `single_read`
    - `capture_recorder_hook_cli.py` (`STALL_*`)
    - `capture_node_log_decisions.py` (`_INSTANCE_MSG_RE`, `:97`)
    - the 3a constants of `capture_aut6_contract.py` (the ledger is injected in tests)
    - `tests/fixtures/capture_heal/*`, `tests/fixtures/recorder_watchdog/*`
  - Must not change the frozen `HEAL_BUDGET_S` or `HEAL_JOURNAL_DAYS`. Reports its narrowed lint scopes and `min_calls` to 3c.

- **S2 (live proof, contract, hardening).**
  - **EDIT:**
    - `capture_live_proof.py`, `capture_live_proof_cli.py`, `capture_aut6_contract.py`
    - `capture_audit_input_types.py`, `capture_audit_inputs.py`, `capture_audit_stream_legs.py`
    - `tests/support/capture_closure_lint.py` (**engine section only**)
    - `tests/support/capture_audit_fixtures.py`
    - `tests/unit/test_capture_audit_stream_legs.py`, `tests/unit/autonomy/test_capture_read_only_closure.py`, `tests/unit/test_decisions_retention.py`
    - new: `test_capture_live_proof.py`, `test_capture_live_proof_cli.py`, `test_capture_aut6_contract.py`, `test_capture_write_pins.py`, `tests/unit/autonomy/pending_aut6_notifier_proof_contract.py`
    - `tests/unit/test_capture_audit_stubs.py` on the **`S2_REAL` line only**
  - **READ-ONLY:**
    - `capture_heal.py` (3a constants), `capture_audit_io.py`, `capture_audit_wire.py`
    - `capture_audit_cli.py` (`families_by_construction`, `launch_window_guard` use)
    - `capture_audit.py` (verdict writes)
    - `capture_settlement.py` (`replace` seam, `LOCK_FILE`, `settlement_file_name`)
    - `capture_schedule.py`, `capture_audit_cache.py`, `scripts/ops/decisions_retention.py`, `single_read`
    - `tests/fixtures/capture_heal/*`, `tests/support/capture_audit_w3_fixtures.py`
  - Must not change `DEADLINE`, `MONOTONIC` or `ScanDeadline` in `inputs` (S1 reads them). Reports narrowed scopes to 3c.

- **S3 (sandbox, lock, units).**
  - **EDIT:**
    - `src/breezy/runtime/autonomy_sandbox/{table,bwrap,self_probe}.py`, `studies_lock.py` (N)
    - `src/breezy/analysis/capture_audit_cli.py` (lock, `exec_start`, fresh clock, `min()` deadline)
    - `tests/fixtures/capture_units/*` (6)
    - `tests/support/bwrap_host_phase.py`, `tests/support/capture_audit_w3_fixtures.py`
    - `tests/unit/test_autonomy_bwrap_argv.py`, `test_autonomy_units_wrapped.py`, `test_autonomy_self_probe.py` (forced, RC-2, at most +6 each)
    - `tests/unit/test_autonomy_sandbox_table.py`, `test_autonomy_aut1_stop_hook_row.py`
    - `tests/unit/test_capture_audit_cli.py`, `tests/unit/test_capture_units.py`
    - new: `test_autonomy_network_field.py`, `test_autonomy_self_probe_net.py`, `test_studies_lock.py`, `test_capture_sandbox_rows.py`, `tests/integration/test_capture_studies_lock_namespace.py`
  - **READ-ONLY:**
    - `unit_lint.py`, `run_mounts.py`, `binds.py`, `bus_handoff.py`, `selftest_cli.py`
    - `tests/support/bwrap_harness.py` (MUST NOT be edited)
    - `capture_audit_host.py`, `capture_audit_model.py`, `capture_schedule.py`
    - `capture_heal.py` (`HEAL_BUDGET_S`, `HEAL_JOURNAL_DAYS`)
    - `capture_audit_model.py` (`AUDIT_EXEC_TIMEOUT_S`) [S3-R50]
    - `tests/fixtures/recorder_watchdog/pending_recorder_unit.service`

- **Pairwise disjointness of the parallel streams (EDIT ∩ EDIT).**
  - **S1 ∩ S2 = {`tests/unit/test_capture_audit_stubs.py`}.** The shared file is line-disjoint: S1 edits only `S1_REAL` and S2 only `S2_REAL`, on the separate, non-adjacent lines 3a wrote [S3-R28, S3-R43]. Every other file is disjoint.
  - **S1 ∩ S3 = ∅.**
  - **S2 ∩ S3 = ∅.** `capture_audit_cli.py` is S3 EDIT and S2 READ-ONLY (S3 does not touch `families_by_construction`). `capture_audit_w3_fixtures.py` is S3 EDIT (`network=`) and S2 READ-ONLY.
  - **Read-of-edited constraints:**
    - S2 and S3 read 3a's frozen constants in `capture_heal.py` (S1 EDIT);
    - S1 reads 3a's constants in `capture_aut6_contract.py` (S2 EDIT);
    - S1 reads `DEADLINE`/`MONOTONIC`/`ScanDeadline` in `capture_audit_inputs.py` (S2 EDIT).

    None of these symbols may change in-stream.
  - **3a vs the streams.** 3a is serial and lands first, so its overlaps with S1, S2 and S3 are sequential, not concurrent: the stubs and constants, the rows section, `test_capture_audit_stubs.py`, `capture_audit_cli.py`, `capture_audit_inputs.py` and `test_capture_audit_cli.py`.
  - **3c vs the streams.** 3c runs after all three merge.

- **3c (serial integration).** Merge order: S3, then S2, then S1.
  - **EDIT:**
    - `tests/support/capture_closure_lint.py` (narrowed scopes and `min_calls` from the S1/S2 reports)
    - `tests/unit/test_capture_audit_stubs.py` (remove the S3-R31 xfail; verify the `REAL_MODULES` union only [S3-R43])
    - `src/breezy/analysis/capture_audit_cli.py` (heal wiring: `HealSender` adapter over `offer` with `severity_for` and `attempt_kind` in `detail`; `heal_deadline`; the step-8 early return after heal; heal outcome folded into the exit code)
    - `tests/unit/test_capture_audit_cli.py` (the 3c tests)
  - **READ-ONLY:** everything else.
  - **Steps:**
    1. Apply the edits above.
    2. Full gate: `scripts/ci/run_tests_no_egress.sh; echo EXIT=$?`; `lint-imports` from the tree, which must print "N kept, 0 broken"; `git diff --stat -- deploy/systemd`, which must be empty.
    3. Run the §4a mutation table.
    4. SEC review (mandatory for `table.py`, `bwrap.py`, `self_probe.py` and `studies_lock.py`) and python review.

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
| K1 | An edit to a linked unit goes live at the next `daemon-reload` | HIGH | No `deploy/systemd` diff (AC 22); the preflight checks `NeedDaemonReload` |
| K2 | `link`/`enable` reloads implicitly and picks up another agent's pending edits | HIGH | Activation only from a clean primary tree, outside [15:55Z, 17:10Z), with a heads-up (stage 4) |
| K3 | A committed unit pages through a missing notifier | MED | Fixtures only; the lint refuses it (F3) |
| K4 | An AUT-1 row reaches the network | HIGH | `none` with fail-closed emission (D3); self-probe net check (`SOCK_DGRAM`) and V3; closure lints and `sys.modules` closures; the egress flip is outside stage 3 and needs its own SEC review |
| K5 | `--unshare-net` regresses seam B | MED | Seam B rows stay `egress` [S3-R11]; exact-set widening only; SEC review |
| K6 | The stop hook becomes `none` | LOW | Not live (F2); lands before WP3 step 2 |
| K7 | Heal is mis-attributed across fast restarts | MED | Match by `instance_id`, the first later invocation, with a decoy-line test (F19) |
| K8 | Heal starves, or a kill is lost | MED | Heal runs first, before the family loop and with zero families, under its own `HEAL_BUDGET_S`; an overrun is a failure (exit 1, pages) [S3-R25, S3-R41]; write-once records make partial runs safe |
| K9 | Multi-family runs overrun the ExecStart bound (F9) | HIGH | One `DEADLINE` set once by `_main`; `run_audit` only reads it; once-per-run duties run once with a 60 s reserve (AC 3) |
| K10 | Leg N never sees a delivered NBP marker (F10) | MED | D11 regex (AC 19) |
| K11 | The settlement bind is shared with the live node's decisions directory | MED | RC-1 write pin (names, primitive, lock file) with an S3-R35 runtime test; S3-R16 residual recorded |
| K12 | A unit test takes the real host studies lock | MED | Injected lock; brief rule; `test_capture_audit_cli.py` edits |
| K13 | `attempt_kind` is lost before stage 4 | LOW | Detail shim; removed in stage 4 |
| K14 | `open_station_catalog` hits `EROFS` | LOW | V7; read-only-base test |
| K15 | Cold-run memory of 710 MB against 768M | MED | Studies slice; one heavy job at a time |
| K16 | Operator controls, live enablement, permit, NO-SEND | — | Never touched; `test_operator_control_assignment_scan.py` unedited |
| K17 | The E-9 relation pin cannot pass as ruled (C1) | MED | Coordinator ruling on C1 before S3 writes `test_e9_latest_end_matches_table` |

## §8 Host V-steps
Run outside 16:30–17:10Z, with no `daemon-reload` and no unit files.
1. **Preflight.** Run `date -u`. Check `NeedDaemonReload=no` on the linked `breezy-*` units. Confirm `find ~/.config/systemd/user -lname '*breezy-capture*'` is empty.
2. **Provision** [S3-R23].
   - Run `install -d -m 0700 ~/.local/share/breezy/{evidence/capture/{audit,heal,heal_alert_abandoned,live_proof},cache/capture_audit,cache/capture_audit_bus,derived/verdicts}`. `evidence/` and `derived/verdicts/` are absent today (F18).
   - Confirm the mode that seam A's `AutonomyPaths` expects for `derived/verdicts`.
   - Verify that `catalog/quote_tape/decisions` is uid-owned with no 0o022 bits.
3. **Self-probe through the real wrapper** [S3-R10, S3-R34].
   - For each of the three capture rows, and for the `-proc` row (an AC7 V3 case), run `systemd-run --user --wait --pipe --collect --unit=<row> -p TimeoutStartSec=120 deploy/systemd/breezy-autonomy-bwrap <row> .venv/bin/python3 -I -m breezy.runtime.autonomy_sandbox.selftest_cli`.
   - For the `none` rows, the audit row above all, expect `ok:true`, no `net_*` failure, and the facts `198.51.100.7:80 (SOCK_DGRAM) → ENETUNREACH` and `net_ifaces == ["lo"]`.
   - **Negative control:** the `egress` rows record a non-`lo` interface.
4. **Journal access.**
   - In the audit row, a `python3 -I -c` connect to `127.0.0.53:53` should give `ECONNREFUSED`.
   - `/usr/bin/journalctl --user -u breezy-quote-tape.service -o json -n 5` should be readable.
   - Measure the largest single-day recorder journal over the last 14 days; it must be under 128 MiB (half the cap).
   - Retention must be at least 3 days.
5. **Bus handoff and the zero-family run** [S3-R46]. Run this in a **quiet window**, because it takes the real studies lock.
   - Use the seam B V17 transient method, then run the audit CLI with no family.
   - Expect: heal runs; "no family to audit"; exit 0 only if the lock and the journal are readable; no heal write without a stall record; no other writes; the snapshot consumed.
6. **Lock contention** (quiet window, stage-2c overlay, `--family-id` scratch). Another shell holds `%t/breezy-studies.lock` for 120 s. Expect no `bus_snapshot_stale`, and the run to proceed after release.
7. **Settlement row.** Import `capture_settlement_cli`, then run `open_station_catalog` on an existing station against the read-only base. Expect no `EROFS`.
8. **No real writes until activation.** No real settlement or audit `--family-id` writes happen until stage 4.

## §9 Stage-4 hookup checklist [S3-R19, S3-R39] and open items
**Stage 4 (AUT-1 WP5 stage 4)** runs after AUT-6, and before or inside WP8's train, whichever comes first.
1. **Preconditions:**
   - the `breezy-autonomy-failed@` row and unit are merged, and that row is in `NOTIFIER_FALLBACK_ROWS`;
   - `deliver_with_proof`, `AlertOutbox` and the notifier markers are merged;
   - **AUT-6's spool-sender unit is live and draining** [S3-R39(a)];
   - **the AUT-6 marker-shape erratum (item 9) is merged before the real ledger (item 10)** [S3-R39(b)];
   - the V-11 re-measure is done;
   - WP3 step 2 is done, for real leg-W kills.
2. **Promote units.** Move the six fixtures into `deploy/systemd/` and drop the stand-in row. `lint_units(deploy/systemd, AUTONOMY_BWRAP_TABLE) == ()`.
3. **`AUTONOMY_OWNED_UNITS`** gains the three services; `validate_table` passes.
4. **Provision `evidence/alerts`** [S3-R39(c)].
5. **Alerts bind.** Add the `evidence/alerts` spool bind to the three rows. They stay `network="none"` and `resolves_dns=False`. File the E-7e(f) amendment: "`resolves_dns=True` on every row that can deliver" excludes spool-only rows.
6. **Write authority** [S3-R39(d)]. Add AUT-6's outbox module to `WRITE_MODULE_FUNCTIONS`, and grant `write_imports` to the three CLIs.
7. **One-writer rows for the spool** [S3-R39(e)]. AUT-1 writes outbox entries; AUT-6 writes `_d.json`.
8. **Outbox injection.** Replace `_undeliverable_offer` in the three CLIs with AUT-6's outbox offer. `HealSender` passes `attempt_kind` natively, and the detail shim is removed.
9. **Coordinator erratum against AUT-6 r15** [S2-R19 / R-3; filed, never a brief edit; moved ahead of the real ledger by S3-R39(b)]. Marker shapes: `<unit>__<InvocationID>.delivered.json` and `NBP_CYCLE_MISSED__<cycle_ns>.delivered.json`.
10. **Real ledger.** The contract readers run against live `evidence/alerts/<date>/*_d.json` and the notify markers. The pending contract file is renamed `test_*` and goes GREEN against AUT-6's writer.
11. **Re-run host V3 and V4 after the alerts bind** [S3-R39(f)].
12. **Register the audit unit in AUT-6's `IN_PROCESS_STUDIES_LOCK_UNITS`**, if that list is linted [S3-R39(g)].
13. **Any `egress` flip:** its own SEC review plus an exfiltration test.
14. **Reviews.** SEC and python review of the hookup diff.
15. **Activation.** K1/K2 preflight, then link and enable outside the window, with a one-line heads-up. Observe the first 13:35, 13:50 and 14:35 runs.
16. **WP9 contract.** The drill writes `drill/<date>.json` before injecting.

**Open items carried into the build:**
- C1, C2 and O-1: RESOLVED by S3-R48, S3-R49 and S3-R50;
- follow-up: split `test_autonomy_bwrap_argv.py`, `test_autonomy_self_probe.py` and `test_autonomy_units_wrapped.py` [RC-2];
- coordinator errata: E-7e(d) reason codes (`net_reachable`, `net_iface_visible`), and AUT-6 r15 marker shapes [S3-R23].

Key paths:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-WP5-stage3-design.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-WP5-stage3-design-r2.md`
- `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/unit_lint.py`
- `/home/jon/breezy/src/breezy/analysis/capture_audit{,_cli,_host,_inputs,_input_types,_stream_legs,_model}.py`
- `/home/jon/breezy/src/breezy/persistence/autonomy/capture_alerts.py`
- `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/{table,bwrap,self_probe}.py`
- `/home/jon/breezy/tests/support/capture_closure_lint.py`
- `/home/jon/breezy/tests/unit/test_capture_audit_stubs.py`
