# EXEC-PAR D-PREREG r4: consolidated pre-registration for activating parallel intents at K>1

**r4 (2026-10-11), consolidates r3 + r3.1–r3.4 + I1–I2; supersedes all**

- **Status:** DRAFT, not frozen. §13 gives the freeze procedure.
- **Governs:** every node boot where the configured K (`runtime/exec_par_constants.py:EXEC_PAR_MAX_CONCURRENT_INTENTS`) is above 1.
- **Source plans:** `EXEC-PAR-parallel-intents_plan_r5.md` §3.6, §3.9, §6, §7, §8, and `..._r5_1_delta.md` E1–E14.
- **Code basis:** HEAD `c3974aa6`.
  - The code line anchors were taken at `7ec83778`. The §11 hashes were computed at `d3588ece`.
  - Both are re-verified at freeze (§13).
  - Where this document and the code disagree, the code value is cited and wins.
- **Labels:**
  - PROPOSED marks a threshold the plan left open.
  - BUILD-GAP (BG-n, r3 numbering) marks enforcement code that does not exist yet.
  - Proposed store keys, alert names and halt reasons are placeholders until the BG build (C2).
- **Lineage:** every r3 ruling (S1–S11, C1–C6) and every later ruling (D, E, G, H, I) is applied in place. The Rulings index at the end gives each one's location.

**Honest prior.** M1-v3's own prior disclosure puts P(WINNER) near zero, so this ramp may never execute. The build is still justified because a working K>1 path is a precondition of T1 (§14.5).

**Coordinator rulings on the r4 consolidation residuals (J1–J2).**
- **J1.** Epoch stratification for M1-v3 separation (§10) stays on fill `ts_event`; it answers "when did a parallel-era fill happen". Evaluator windows use arm time (I2). No conflict.
- **J2 (unclean shutdown).** If the latest epoch row has no `stop_ts`, the CLI, having acquired the exclusive flock (which proves the node is down), writes `stop_ts = lock-acquire ts` with cause `unclean_cli` **before** `--dry-eval`. H4 freshness then applies normally. A BG-4 test pins this.

## 0. Binding invariants

- Nautilus Trader is immutable.
- `allow_short` stays `False`.
- **Operator caps.** The two operator caps (max daily budget, max per position) are read-only.
  - This document never states or assigns them.
  - Every threshold is a fraction of the daily budget, checked by value-free ledger predicates.
  - No tool prints a cap value.
- **Orders.** Nothing here changes the halt drop-in or `BREEZY_ORDERS_ENABLED`. K>1 changes concurrency only. It is never a decision to enable orders.
- **Independence from M1-v3.**
  - This document is independent of `docs/evidence/m1v3/PREREG.json` and never edits it.
  - It uses no data from climate days 2026-10-07..11-28 and none from the F13 sealed holdout.
- **Layering.**
  - `runtime` may import `adapters`; `adapters` never import `runtime`.
  - The import-linter layers contract has two pinned `ignore_imports` exceptions for `runtime.settings`, and none is added.
  - `runtime` never imports `breezy.analysis` (`pyproject.toml:152-160`), so the evaluator's pure function lives in `runtime`.

## 1. K schedule

| Stage | K | Entry condition | Minimum to promote |
|---|---|---|---|
| S0 | 1 | Today | Every §14 item marked "for S1" passes |
| S1 | 2 | §14 complete | All of: ≥5 climate days with ≥1 K>1 entry fill; ≥30 posted entry orders; ≥8 climate days in the stage (§5); every §5–§9 and §15 check green over the stage |
| S2 | 4 | S1 promoted, §8 gate passed, BG-10(b) merged | Same as S1 |
| S3 | 6 | S2 promoted, §3 re-run passing, BG-11 merged | Terminal. K≥7 needs an amendment. |

- **Ceiling (PROPOSED).** K=6 is the smallest K that passed the gate arm at bucket 0.05 on main4+nyc (WP0 Headline). The no-id variant needed K=7 and is not authorised.

**Looks.**
1. **First look.** BG-5 evaluates promotion once, on the first climate day when the stage minima above are all met.
2. **First FAIL.** This is not a demotion. It opens exactly one 5-day extension.
3. **Re-look.** Exactly one, on all stage data since the latest `stage_reset`, cumulatively. It is not limited to the extension days.
4. **Second FAIL.** A demotion verdict.
5. **Stage cap.** A stage lasts at most **15 climate days**, counted from its `stage_reset`.
   - Excluded days (§10a) count toward this cap.
   - If the re-look would fall after day 15, it happens on day 15.
   - A stage that reaches the cap with its minima unmet holds at its K. It is never promoted without an amendment.
6. **Excluded days and the minima.** Excluded days are skipped by every window, so they never count toward the ≥5-day or ≥8-day minima.

**Windows and the floor.**
- **The floor record.** One store record, `exec_par/stage_reset {ts, cause, halt_ts}` (PROPOSED key), is the floor for every window. It is written only:
  - **(a)** by `--clear-force-k1` (cause `stop_clear`, §1b); and
  - **(c)** at a K change, meaning a boot whose effective K differs from the last epoch row's (cause `k_change`, written by BG-2).

  Nothing else writes it. In particular, excluding a day does not.
- **What the floor covers.**
  - These read only data after the latest `stage_reset.ts`: the §5, §6, §7 and §9 windows, §15-stage, the promotion looks, and the excluded-day counter.
  - **§15-cumulative is exempt.**
  - A stop verdict computed only from pre-floor data therefore cannot set the flag again.
- **Arm-time attribution (I2).**
  - "Data after `stage_reset.ts`", the climate-day attribution, and every window boundary (trailing-5-day, 2-of-5, 60-minute burst, stage) are defined on the entry's **arm time** (`arm_slot` `created_ns`).
  - They are never defined on record, fill, classification or settlement time.
  - An entry's fill, AMBIGUOUS resolution and settlement all belong to the window that holds its arm time.
- **Positions armed before a reset.**
  - A position armed before a reset and settled after it counts in the closed pre-reset windows and in §15-cumulative, never in the new stage. The stage report lists such settlements.
  - **While it is still open, it is covered only by §15-cumulative and by the §9 intraday station-day open-cost guard**, which counts all open positions regardless of arm time.

**Mechanics of a K change.**
1. Make one commit that edits only `EXEC_PAR_MAX_CONCURRENT_INTENTS` and cites the frozen SHA and the stage.
2. Run `scripts/ci/run_tests_no_egress.sh` and read EXIT=0.
3. Restart the supervisor, because it reads K.
4. Respawn the node. The boot writes the `k_change` `stage_reset`.

**Code-enforced forced-to-1 conditions** (effective K, logged at ERROR, alert `EXEC_PAR_K_FORCED_TO_1`):
1. **Supervisor marker.** `node_config.force_k1_without_supervisor_marker` (`node_config.py:756`), called at `app/trade.py:1078`. A read that raises counts as not admitted.
2. **Bucket guard.** `exec/client.py:_apply_slot_boot_guards` → `_bucket_force_reason`. It forces K=1 when any of these holds:
   - the label is not configured;
   - there is no ledger;
   - `cost_budget_bucket()` raises;
   - the live label ranks above the frozen label.
3. **Durable force-K1 flag (BG-3, §1b).**
4. **Restart over a v2 table.** A restart with K forced to 1 over a v2 table still resolves every open slot (r5.1 E7).

**After a halt.**

| Halt | Outcome |
|---|---|
| §4 breaker trip; §5; §7; §15 day stop | The ramp restarts at S1. |
| §15-cumulative | K=1. Cumulative is never floored, so any later K>1 boot would trip it again; resuming K>1 needs an amendment. |
| §6 at S3 | K>1 programme suspended until an amendment re-runs WP0 with live hold data. |
| **Demotion verdicts:** second failed promotion; §9 station-day 2-of-5; §9 5 s window; §15 stage stop; more than 2 excluded days in a stage | Down exactly one stage. |
| Integrity halt (§1a) | Reset per §4. The stage continues, with no K change. |

- **Resuming** requires all of:
  - an incident report in `docs/incident-reports/`;
  - the §4 reset;
  - the lower-K commit when K changes.
- **A §4 breaker trip at S1.** It sets no flag and writes no `stage_reset`.
  - At S2 or S3, its restart at S1 is a K change, so the floor moves at boot.
  - At S1, the stage and its windows continue.
- **No post-hoc K.** No K outside {1, 2, 4, 6} is ever set.

## 1a. Real-time enforcement

- **Every rule ends in an automatic entries-only halt.** It is written through the node's own latch, `SubmitIntentLatch.write_breaker_halt` (`submit_intent.py:1098`): under `_require_held()` and `_mutex`, and sticky (the first reason wins).
- The halt is the stop. A demotion commit is deferred cleanup.

| Rule | Class | Enforcer | Sets flag |
|---|---|---|---|
| Stuck slots, AMBIGUOUS notional, contradictions, duplicates (§4) | Intraday | `BreakerWatcherActor._persist` (existing) | No |
| §5 Clopper-Pearson halt and 60-min burst | Intraday | BG-6 | Yes |
| §9 station-day open cost > 0.25 of budget (all open positions) | Intraday | BG-6 | Yes |
| Stamp stale or never written | Intraday integrity | BG-6, with supervisor alert BG-8 | No |
| Boot pass pending (`stage_eval_boot_pending`) | Entry denial, not a halt | BG-6 | No |
| Integrity halts (table below) | Integrity | BG-1, BG-5, BG-6 | No |
| §6; §7; §9 2-of-5 and 5 s; §15 day, stage and cumulative; promotion looks; more than 2 excluded days | Daily, in-node | BG-5 | Yes |
| Cross-check and promotion report | Read-only | BG-7 | Never writes |
| Breaker reset, §8 hold-time gate | Procedural, code-gated by BG-4 | Coordinator | — |

**Flag semantics.**
- **Who sets it.** The force-K1 flag is set **only** by:
  - stop rules (§5, §6, §7, §9, §15) evaluated on complete inputs; and
  - demotion verdicts.
- **Transient and integrity conditions only halt.** A ledger-predicate raise counts as tripped but is integrity-class.
- **Keyed on the verdict.** The flag is written from each pass's **verdict**, whether or not the halt write latched a new reason. A sticky transient reason may already be latched. Re-assertion keys on every pass's verdict.
- **Write order.** Halt first, then flag. The flag write is attempted even if the halt write raised. A flag-write failure is logged at ERROR; a lost flag write is tolerated by §1b and §4 step 4.

**Integrity halts** (no flag; reset evidence is a dry pass, §4):

| Condition | Halt reason (PROPOSED) |
|---|---|
| Evaluator exception, timeout, or a missing, None or non-monotonic input | `stage_eval_fail:<kind>` |
| A still-gappy (unreconciled) day inside a window (§10a) | `stage_eval_fail:gappy` |
| A pass running longer than 2 × timeout (240 s), or no completed pass by boot + 300 s | `stage_eval_stuck` |
| Evaluator task died: its done-callback sees an exception or cancellation; **or**, on any watcher tick, the outstanding task is `done()` with no stamp for that pass (this check runs regardless of the callback, so it catches death before the callback is attached) | `stage_eval_task_died` |
| BG-1 write failure | `telemetry_write_fail` |
| A `LedgerPredicatePort` raise or non-bool return (BG-5 and BG-6) | Integrity trip naming the predicate |
| An unreconcilable gappy day added to `excluded_days` | `day_excluded` (plus `EXEC_PAR_DAY_EXCLUDED`) |

**In-node evaluator (BG-5).**
- **Logic.** A pure function in new `runtime/exec_par_stage_eval.py`.
  - Inputs: one immutable snapshot of BG-1 counters, BG-2 epochs, `stage_reset`, `excluded_days`, latch state and `LedgerPredicatePort` booleans.
  - Output: a verdict.
- **Threading.**
  - `SqliteStateStore` uses `check_same_thread=True` (`sqlite_store.py:122`).
  - The **loop thread** gathers the snapshot; the executor runs only the pure function.
  - All writes happen on the loop thread, through new latch methods that never nest the non-reentrant `_mutex`.
- **Scheduling.** A `BreakerWatcherActor` sub-task runs a pass:
  - at boot, which covers hand relaunches;
  - at the first tick after every governed station's climate day closes (the daily pass);
  - on the tick that first observes a new settled-P&L value (§15).

  Boot passes and daily passes reconcile first (§10a).
- **Execution.**
  - A **detached task**, never awaited inside `tick()`, so the 5 s heartbeat never stalls.
  - `loop.run_in_executor` inside `asyncio.wait_for`, timeout 120 s (PROPOSED).
  - At most one pass is outstanding. No new pass starts while one is outstanding.
  - An executor thread cannot be killed; the `stage_eval_stuck` halt is the containment.
- **Liveness.** The heartbeat record carries `stage_eval_last_start_ns` and `stage_eval_last_ok_ns`.
- **Stamp.**
  - A successful pass writes `exec/polymarket_us/exec_par/stage_eval/stamp` (PROPOSED) = `{ts_ns, boot_ns}` through the store-writer port.
  - `boot_ns` comes from a new public read-only `SubmitIntentLatch.boot_ns` property over `_boot_ns` (`submit_intent.py:560`).
  - Stale means older than 26 h, or never written after the first K>1 climate day.
- **Boot-pass gate.**
  - At configured K>1, `_breaker_denial` denies entries with `stage_eval_boot_pending` until both hold:
    - `stamp.boot_ns == latch.boot_ns`; and
    - `stamp.ts_ns ≥ latch.boot_ns`.
  - A stamp from a previous boot never counts.
  - Exits and the resolver are never blocked.
- **If `write_breaker_halt` raises:**
  - the watcher stops **only** its heartbeat writes;
  - it keeps writing counters, alerts and the flag;
  - the existing 60 s heartbeat-staleness denial fails closed, for entries only;
  - the watcher logs ERROR;
  - the supervisor alerts `WATCHER_DEAD` and never respawns or kills the node.
- **No lock gap.** Every write comes from the single lock-holding process: the node, or the §4 CLI while the node is down.
- **Latency bound.**
  - Daily rules act within one climate-day close of the day they measure.
  - §15 stops act on the first pass after the settlement is ingested.
  - No rule waits for a respawn.

## 1b. Durable force-K1 flag (BG-3; CLI in BG-4)

- **Key:** `exec/polymarket_us/exec_par/force_k1` = `{reason, ts_ns, set_by}`.
- **Written** through a single-writer latch method behind the store-writer port, under the held latch, on the loop thread.
- **Set** per §1a.
- **Manual set.** `clear_submit_intent_cli --set-force-k1 --reason <stop-rule reason> --incident-report <existing path>`.
  - Preconditions: the node is down (CLI lock), the reason is a §5/§6/§7/§9/§15 stop reason, and the report file exists.
  - It only tightens. It never clears or floors anything, and it is not a required reset step.
- **Cleared only** by `--clear-force-k1 --incident-report <existing path>`, which refuses unless:
  1. the flag is set, **or** the latched halt reason is a stop-rule reason. It never moves the floor when there is no stop.
  2. a `stage_eval_dry` record exists that:
     - is newer than both the latched halt and the latest epoch `stop_ts`; and
     - has complete inputs and a verdict of PASS or STOP-ACKNOWLEDGED.

  **It succeeds with the flag unset when the latched halt is a stop rule.** That is the repair path for a lost flag write.

  It writes `force_k1_cleared {ts, halt_ts, incident_report}` and `stage_reset {ts, cause: stop_clear, halt_ts}`.
- **Boot check.** A new `node_config.force_k1_on_durable_flag(latch, store)`, called beside `force_k1_without_supervisor_marker` at `app/trade.py:1078`.
  - When the flag is set, it calls `latch.force_k1(reason)` (`submit_intent.py:850`).
  - An unreadable flag counts as set.
- This is not a byte-pinned file, and `_bucket_force_reason` is unchanged.

## 2. Exposure fractions

All values are fractions of the operator's **daily budget**, never dollars.

| Constant | Value | Anchor |
|---|---|---|
| `f_adm` | 0.50 | `node_config.OPEN_EXPOSURE_BOUND_FRACTION`, enforced by `DailySpendLedger._require_exposure_headroom_locked` and `exposure_admission_refusal`. It raises `OpenExposureBoundExceeded` and is not a day-stop. |
| `f_breaker` | 0.25 | `node_config.BREAKER_OPEN_AMBIGUOUS_FRACTION` via `DailySpendLedger.breaker_fraction_exceeded` (`operator_controls.py:934`). Any raise, or any AMBIGUOUS entry of unknown size, counts as tripped. |

At cost = cap and bucket 0.05:
- one order is at most 0.05 of the budget;
- AMBIGUOUS exposure at K=6 is at most 0.30, which is below `f_adm`;
- the breaker trips once more than 5 cap-sized orders are AMBIGUOUS;
- exits never enter the registry (E4).

## 3. Frozen cost/budget bucket and the activation re-run

- **Frozen label `0.05`.** The unit is cap / daily budget.
  - Anchor: `node_config.EXEC_PAR_FROZEN_BUCKET = "0.05"` (`:748`), passed to the client as `frozen_cost_budget_bucket` (`:1105`).
  - Ladder: `operator_controls._COST_BUDGET_BUCKETS` = {`≤0.02`, `0.05`, `0.10`, `0.25`, `0.50`}, with the sentinel `>0.50`.
- **Why 0.05.** WP0 passed it at K=6.
  - main4: CI upper bound 0.2755.
  - main4+nyc: **0.2905**, a margin of 0.0095, on one seed with 2,000 resamples (`RESAMPLES`, `exec_parallel_dhat.py:70`).
  - The simulated cost/budget ratio is about 0.0505, against a live label of 0.05, so the sim is slightly conservative.
- **Why not 0.10.** It passes only on main4 at K=7, driven by free-balance arm B, and fails on main4+nyc (0.420).
- **Clustering is unmodelled.** WP0 drew p_amb independently per order, with a per-day seed (`random.Random(f"wp0|{p_amb}|{no_id}|{day}")`, `:376`). This favours a pass.

**Procedure:**
1. The operator sets the caps. This document assigns no value.
2. The coordinator derives the label only through the BG-10(a) label-only reader and records only the label.
3. Re-run `exec_parallel_dhat.py` (BG-10 version) on pre-2026-10-07 inputs, at cost = cap, on the **actual** label's row. Use the gate arm:
   - p_amb 0.33;
   - one stuck slot;
   - the 5/s throttle (`TRADE_RISK_MAX_ORDER_SUBMIT_RATE = "5/00:00:01"`);
   - `f_adm`;
   - the worse free-balance arm.
4. **Resampling.** Use ≥20,000 bootstrap resamples and 3 seeds. Each seed varies **both**:
   - `BOOT_SEED` (`:71`, used at `:416`); and
   - the draw seed (a component added to the `:376` string).
5. **Stop rule.** At K=6 and the actual label, **every** seed's day-clustered bootstrap CI upper bound of the day-level p90 d̂ must be ≤ **0.30**. Otherwise K stays 1.
6. **Overdispersion arm** (report-only). Add a day-overdispersed p_amb arm (ρ = 0.1, beta-binomial by day). It does not gate.
7. Store the result JSON under `docs/evidence/exec_par/`, with the sha256 of the result and of the BG-10 script version.
8. **A label of `≤0.02` is admissible.** It ranks below the frozen label, and main4+nyc passes it at K=6.

**Freeze enforcement (BG-9)** in `tests/unit/test_exec_par_wp5b_config.py`:
- **At configured K=1:** skip.
- **At K>1:** fail if any of these holds:
  - the frozen `EXEC-PAR-D-PREREG.md` is missing;
  - the `EXEC-PAR-D-PREREG.sha256` sibling is missing or does not match the doc's bytes;
  - the §3 label in the frozen doc differs from `EXEC_PAR_FROZEN_BUCKET`.
- The same file asserts the single-family boot invariant (§9).

## 4. Breaker: triggers, reset and rollback

**Trip triggers.** `BreakerWatcherActor._persist` (`breaker_watcher.py:453`) runs every 5 s and is registered only at K>1 (`build_exec_watcher`, `:542`). It trips on:
- ≥2 open intents older than `STUCK_AGE_NS` = 900 s (the code uses 900 s for both the with-id and no-id shapes);
- AMBIGUOUS notional above `f_breaker`;
- any increase in `contradiction_events_total`;
- any increase in `duplicate_suspect_total`;
- the BG-6 reasons and BG-5 verdicts (§1a).

**Duplicate detector.** It only backs up the stuck-slot check.
- It runs after the `L_feed` = 300 s lag guard and needs confirmation on a second consecutive pass.
- A duplicate on an order that resolves normally is caught only by the 120 s cool-off and position reconciliation.

**Halt.** Entries only, sticky, held in `BREAKER_KEY`. Exits and the resolver are never blocked; a BG-6 test pins this.

**Entry denials** (`SubmitIntentLatch._breaker_denial`):
- the record is absent more than 60 s after boot;
- the record is garbled;
- the halt is set;
- the heartbeat is older than 60 s;
- the resolver pass is older than 600 s;
- a stamp is more than 5 s in the future;
- `stage_eval_boot_pending` (§1a).

**Supervisor** (`breaker_supervisor_watch.decide_breaker_alerts`).
- **Existing alerts:** watcher dead, resolver stale, halt latched, unreadable slot. They repeat hourly.
- **BG-8.** `trade_supervisor.py:3155` currently returns before probing at `configured_exec_par_k() <= 1`. Change it so that every 10 min, read-only:
  - it probes `halted` and unreadable slots at **any** K;
  - at configured K>1, it probes the BG-5 stamp and alerts `TRADE_SUPERVISOR_EXEC_PAR_STAGE_STAMP_STALE`. This fires even when the node is down.
- **No respawn.** On every breaker alert, including `WATCHER_DEAD`, the supervisor **only alerts**. It never respawns or kills the node; a BG-8 test pins this.

**Reset.** Done by the coordinator under the standing pre-authorisation. The operator gets the alert and is not asked.
- **Timing.** Only at the 16:50Z daily respawn.
- **Pre-check.** No held-position exit is due within 30 min.
- **Order.** The steps below apply to **every** halt reason: stop-rule, integrity and existing breaker trips. Step 4 is the only conditional step.

1. **Gather evidence.**
   - The trip reason and held list from `EXEC_PAR_BREAKER_TRIPPED`.
   - A venue positions GET that reconciles every held slug, with the NO-as-short-YES sign applied.
   - `clear_submit_intent_cli --list`.
   - Every stuck slot resolved, or cleared with `--intent-id --resolution --evidence`.
   - Venue order history for a contradiction or duplicate trip.
   - An incident report recording the repair of any integrity cause.
2. **Take the node down** (hand-relaunch mechanics).
   - A clean disposal writes the epoch `stop_ts`.
   - The CLI refuses while the node holds the lock.
   - While the node is down there is no resolver and no exits. Target ≤10 min (PROPOSED).
3. **Dry pass:** `--dry-eval --incident-report <path>`, run from the **node launch environment**.
   - **Caps.** It never prints cap values. If the caps are absent, it returns FAIL with `operator caps not present: run --dry-eval from the node launch environment`.
   - **(i) Print counts.** It prints the current window counts from the store, before any reset. The incident report records them.
   - **(ii) Reconcile.** It runs the §10a reconciliation for every day in the windows. Each day is either rebuilt (`EXEC_PAR_COUNTER_REBUILT`) or added to `excluded_days`.
   - **(iii) Evaluate.** It runs the pure evaluator. Verdicts:

     | Verdict | Meaning |
     |---|---|
     | PASS | Complete inputs; no stop rule fires. |
     | STOP-ACKNOWLEDGED | Complete inputs; a stop rule fires; the incident report names that reason and its remediation. |
     | FAIL | An input is incomplete or unreadable, or the caps are absent. |

     Because reconciliation runs first, heartbeat-lapse and `telemetry_write_fail` halts always reach a verdict on complete, non-gappy inputs. An unreadable store is FAIL; the remedy is store repair, recorded in the incident report.
   - **(iv) Record.** It writes `stage_eval_dry {verdict, input_complete, ts}` and appends the verdict to the incident report.
4. **Clear the flag** — only if the flag is set or the halt is a stop rule: `--clear-force-k1 --incident-report <path>`, with the §1b preconditions.
5. **Reset the halt:** `--reset-entry-halt --ack-held-positions-reviewed --incident-report <path>`, which calls `SubmitIntentLatch.reset_breaker_halt` (`submit_intent.py:1167`). Use the exact venv interpreter. It **refuses** unless all of these hold:
   - the incident report file exists;
   - a `stage_eval_dry` record:
     - is newer than both the latched halt and the latest epoch `stop_ts`;
     - has complete inputs; and
     - has a verdict of PASS, or STOP-ACKNOWLEDGED for a stop-rule halt;
   - the flag is unset, **or** the configured K is 1;
   - for a stop-rule halt, a `force_k1_cleared` record exists whose `halt_ts` equals this halt.
6. **Demote** (a cleanup commit plus the gate), then relaunch.

**Floor moved without a halt.** If a `stage_reset` was written but the halt that should have followed it never latched (the heartbeat-stop fallback, §1a), the incident report must record:
- the pre-floor window counts from step 3(i); and
- the fact that the floor moved without a latched halt.

**Rollback drill** (before the first K>1 boot and after any code rollback; green at the activation SHA):
- `test_rollback_drill_after_drain_and_reset_old_reader_sees_valid_v1_retired` (`test_exec_par_wp5a_decode.py:298`).
- `test_drain_then_reset_then_rollback_drill` (WP7, merged d5e5568d, `tests/unit/test_exec_par_wp7_rollback_drill.py`).
- `test_restart_with_k_forced_1_over_open_v2_table_resolves_all_slots_and_downgrades` (`test_submit_intent_slots.py:620`, `test_exec_par_wp4_boot.py:467`).

**Rollback order:**
1. Review held positions.
2. Run reset steps 1–5.
3. Drain to at most one open slot (the table rewrites as v1).
4. Set K=1.
5. Verify `halted: null` before reverting any code.

## 5. AMBIGUOUS rate (PROPOSED)

**Metric.**
- AMBIGUOUS entries over posted entries (BG-1 counts).
- Taken over the stage window: arm time ≥ the latest `stage_reset.ts`, with excluded days skipped.
- Outcomes may be day-clustered, so the effective n is nearer the number of days than the number of orders.

**Halt** (intraday, BG-6, sets the flag) when either holds:
- n ≥ 20 and the one-sided Clopper-Pearson lower bound at α = 0.01 exceeds **0.18** (≈ the WP0 hold-input point estimate 7/39 = 0.179);
- **burst:** ≥ **5** AMBIGUOUS entries whose **arm times** fall within any 60 minutes, at any n.
  - If BG-10(c)'s 15-day false-alarm rate for ≥5 at p = 0.18 and ρ = 0 exceeds 10%, the threshold becomes **≥6** before freeze.
  - This is the only permitted adjustment.
  - The frozen §5 states which threshold applies.
- There is no per-day guard.

**Promotion** requires both:
- the stage's one-sided **90% Wilson upper bound** on the pooled rate is ≤ the **BG-10 level**, using n_eff = n / DEFF:
  - DEFF = 1 + (m̄ − 1)·ICC;
  - m̄ = mean entries per climate day over the stage;
  - ICC = one-way ANOVA ICC with n₀ weighting, n₀ = (N − Σmᵢ²/N)/(k − 1), floored at 0.1 (a negative estimate becomes 0.1);
- no §5 halt fired in the stage.

The look schedule is §1: first look at ≥8 days, one cumulative re-look. If the I1 switch below triggers, **both looks use a 95% bound.**

**BG-10 level.**
- The p_amb at which the §3 stop rule (K=6, one stuck slot, p90 CI upper bound) reaches 0.30. It is derived by BG-10(c).
- It is never a §3 input (§8). The 0.33 Wilson upper bound of 7/39 remains only the §3 gate-arm proxy.

**Viability.** The programme is not viable without an amendment unless all three hold:

| # | Condition | Requirement |
|---|---|---|
| V1 | BG-10 level | ≥ **0.33** |
| V2 | Promotion pass probability at true p = 0.18, under the full two-look schedule, with ICC = max(0.1, the ANOVA estimate from pre-window data) | ≥ **80%** |
| V3 | Two-look false-pass probability at true p = **the BG-10 level**, each look using the one-sided 90% Wilson-DEFF upper bound | ≤ **20%** |

- **If V3 fails at 90%:**
  - both looks switch to a one-sided **95%** bound;
  - V2 and V3 are recomputed under the 95% bound.
- That switch is the only permitted adjustment. If V2 or V3 still fails, the programme is not viable without an amendment.

**Recorded in the frozen §5** (BG-10(c) outputs; all TBD until freeze):

| Item | Value |
|---|---|
| BG-10 level (V1) | TBD |
| Pre-window ANOVA ICC estimate; ICC used | TBD |
| V2 at first look and overall | TBD |
| V3, and the bound level in force (90% or 95%) | TBD |
| Burst 15-day false alarm at p = 0.18 for ≥5 and ≥6, at ρ = 0 and ρ = 0.1; threshold applied | TBD |
| Clopper-Pearson + burst operating characteristics: 15-day false alarm at p = 0.18 (ρ = 0, ρ = 0.1); power within 5 days at p = 0.33 and 0.45 | TBD |
| **Pinned simulation assumptions:** entries/day distribution; empirical intraday entry-time distribution (pre-2026-10-07 candidates); ICC model; seeds; number of runs | TBD |

**Reference figures.** BG-10 reproduces these; they are not cited as fact, and BG-10's run is authoritative. At level 0.33, ICC 0.1, p = 0.18:
- reviewer A: about 77% at day 8 and about 92% over both looks;
- reviewer B: about 74% and about 86%.

## 6. Live dropped-candidate-share stop (PROPOSED)

- **Metric:** denied candidates over all candidates. Denials counted:
  - `OpenExposureBoundExceeded`;
  - K-full;
  - cool-off (`DEFAULT_COOLOFF_NS` = 120 s);
  - throttle;
  - free balance;
  - BG-11 pre-filter WAITs.

  Breaker and stale denials are reported separately and excluded.
- **Stop at S3** (daily, BG-5): the pooled trailing-5-day share (arm-time window, floored, excluded days skipped) is above 0.30 on two consecutive daily evaluations. The programme is then suspended (§1).
- **S1/S2:** report only. This is why BG-11 is required only before S3.
- A missing counter means FAIL.
- The day-level p90 appears only in the stage report (≥15 days).
- **BG-11.**
  - Today, `continuous_strategy._admission_refusal` (`:2602`) calls `TrialDayLatch.admission_would_refuse` (`trial_day_latch.py:784`), which returns a WAIT without an `OrderDenied`.
  - So `ExecParDigest.record_denial` never sees it.
  - BG-11 adds per-reason pre-filter counters in `continuous_strategy.py` and `continuous_no_side.py`, persisted through BG-1.

## 7. Slippage and fee parity (PROPOSED)

**Fee** (daily, BG-5; stage window):
- **Coefficient.** On every K>1 fill, `fee_coefficient_at_fill` (stamped by `exec/client.py:record_fill`) must equal θ = 0.0695 (`PREREG.json` `theta`) exactly. A mismatch or a None halts.
- **Per order.** Σ realized cents must equal `ROUND_HALF_EVEN(θ·Σ C·p(1−p))` at currency precision (`fees.py:597-605`).
  - Single-fill orders must match exactly; multi-fill orders are allowed ±1 c.
  - A violation halts.
- **Per stage.** Halt when |Σ realized − Σ unrounded exact| > max(2 c, 0.5 c × orders).
- **Per fill.** Mismatches are **report-only**; `fees.py` documents per-fill rounding as an approximation.
- **Reconciliation.** A `fee_reconciled=False` share above 10% blocks promotion.

**Slippage** per fill is `fill_px − decision ask`. A missing decision ask means FAIL. Promotion requires:
- a stage mean ≤ **0.005**; and
- ≤10% of fills above 0.02.

**Parity** is measured against the K=1 pre-boot fill ledger of the same family: mean parallel minus serial ≤ 0.005 when there are ≥20 K=1 fills; otherwise report-only.

**Note.** Together the slippage and parity tolerances allow about 1 c of slack, against an edge of about +2 c.

## 8. NO≥0.90 hold-time ramp gate (S1→S2)

WP0's hold inputs contain no NO≥0.90 order, and every AMBIGUOUS order was YES. The hold mixture is assumed, not measured.

- **Gate** (procedural; needs BG-10(b)):
  1. Collect ≥20 posted NO≥0.90 entries at S1.
  2. Measure arm→retire hold times and the AMBIGUOUS share.
  3. Re-run §3 with the empirical holds and p_amb = max(0.33, measured Wilson upper bound).
  4. It must pass the §3 stop rule at K=6 and the actual label.
- **The BG-10 level is never a §3 input.** It is the boundary at which §3 reaches 0.30, so using it as an input would be circular. It serves only as the §5 promotion bound.
- **15-day cap.** If 20 such orders are not reached within the S1 cap, K holds at 2 and there is no promotion to S2.
- **BG-10(b)** adds a hold-input-only mode. It reads live K>1 hold times dated on or after 2026-11-29; candidates still come only from the pre-window set.

## 9. Concentration

| Scope | Limit | Enforcement |
|---|---|---|
| Per slug | 1 open slot (YES and NO share it) plus a 120 s cool-off | `domain/exec_slots.admit`; `DEFAULT_COOLOFF_NS` |
| Per order | Per-position cap | `DailySpendLedger.authorize_order_cost` |
| Station-day, intraday | Open cost above 0.25 of the budget → halt plus flag. **Counts all open positions regardless of arm time or floor.** | BG-6 (value-free predicate) |
| Station-day, stop (PROPOSED) | Above 0.25 on 2 of the last 5 days (arm-time days, floored, excluded days skipped) → halt, demotion verdict | BG-5 over BG-1. No cap: the 2026-09-14 ruling stands. |
| 5 s window (PROPOSED) | On days with ≥6 orders, more than 0.50 of the day's entry notional inside one `WINDOW_NS` = 5 s window, on 2 of the last 5 days → halt, demotion verdict | BG-5 over BG-1 |
| Per family | Exactly one entry family | `app/trade.py:1047` loads only `settings.sending_family_id`; `:1066-1070` raises `SettingsError` on a mismatch. Asserted by BG-9. |

A predicate raise or non-bool return counts as tripped and is integrity-class (§1a).

## 10. Parallel fills never feed the M1-v3 verdict

**What M1-v3 reads (verified).** `scripts/analysis/no_longshot_pooled_test.py` reads only:
- the recorder Depth10 tape (`RecorderCatalogTape`, first row in [12:00, 13:00) UTC); and
- the CLI finals.

It reads no exec store and no fills.

**Ways K>1 could leak into it:**
- depth consumption (negligible at about 1 contract per order);
- the shared WS subscription cap (10 per connection);
- node or recorder restarts that leave gaps in the tape.

**Rules:**
1. No K>1 boot before 2026-11-29T00:00Z. §14.5 also blocks K>1 until the M1-v3 read (on or after 12-07).
2. One look only. No K>1 statistic ever enters the M1-v3 report.
3. No recorder-gap day may be attributable to a K change.
4. Every K>1 fill is reported in a separate stratum.

**BG-2 (K-epoch ledger):**
- At boot, before `node.run`, `app/trade.py` appends `{commit_sha, effective_k, force_reason, boot_ts}` under `exec/polymarket_us/exec_par/epoch/<boot_ts_ns>`.
- If the effective K differs from the last row's, it writes the `k_change` `stage_reset` (§1).
- The watcher appends an amendment row when the bucket guard forces K=1.
- `stop_ts` is written at disposal or halt. A crash is closed by the next `boot_ts`.
- **Epoch stratification** attributes fills by `ts_event`. A configured K>1 epoch with no forced row counts as parallel. This applies to M1-v3 separation only; evaluator windows use arm time (§1).
- BG-7 exports the rows to `docs/evidence/exec_par/k_epochs.jsonl`.
- `score_live_trials.py` and `family_tally_v2.py` stratify on the epoch.

## 10a. Durable telemetry, reconciliation and ports (BG-1)

`ExecParDigest` is in memory: it resets at every respawn, keys by UTC day, and overflows at `MAX_REASONS` = 32 (`exec_par_telemetry.py:35`). BG-1 replaces it as the source of record.

**Per-climate-day records.** BG-1 persists these to the exec-state store. The watcher writes them on its tick (loop thread), fed by its `events.order.*` subscription (`breaker_watcher.py:99`) and by the durable records:
- posted entries;
- AMBIGUOUS;
- denials by reason;
- BG-11 WAITs;
- fills;
- realized fees;
- unrounded exact fees;
- slippage per fill;
- open cost per station-day, as a value-free fraction flag;
- 5 s window peaks;
- gappy marks;
- the **settled-P&L accumulator.**

**Settled-P&L accumulator.**
- Computed at settlement ingest as durable fill records × the CLI-final outcome, net of realized fees.
- An AMBIGUOUS entry counts as a full-cost loss until it is resolved.
- `DailySpendLedger` tracks spend, not P&L, so it is not the source.
- Nautilus portfolio realized P&L is at most a cross-check, used only if the BG-1 build proves it realizes at weather settlement. It never gates.

**Other store records:**
- `stage_reset`;
- `excluded_days {day, cause, ts}`;
- `stage_eval_dry`;
- `force_k1_cleared`;
- rebuild records.

**Failure handling.**
- **A missing day or a None value counts as FAIL/trip, never 0.**
- **A failed write** is the integrity halt `telemetry_write_fail`.
- **Currency values** stay in the local store. They are never logged or alerted, and are compared with budget fractions only through `LedgerPredicatePort`.

**Gappy days.**
- **Premise.** Entries are IOC, so no entry rests at the venue across a node outage. An AMBIGUOUS IOC can still have filled unseen.
- **Event-sourcing.** Counters are event-sourced from durable records: fills (`fill_index`), the slot table, and the `DailySpendLedger` registry.
- **A recorded outage is not a gap.** That is the span from an epoch `stop_ts` to the next `boot_ts`, which includes the 16:50Z respawn.
- **A day is gappy only when:**
  - (a) the node was up, with an epoch open, and the watcher heartbeat lapsed for more than 60 s;
  - (b) there was an unclean shutdown with no `stop_ts`: the span from the last heartbeat to the next boot is a gap until boot reconciliation matches;
  - (c) reconciliation mismatches.

**Reconciliation.**
- **When it runs:**
  - at boot, **after** the Nautilus mass-status ingest, so that `generate_fill_reports` fills are durable before the counters are compared (pinned by a BG-1 test);
  - at every daily evaluator pass;
  - inside `--dry-eval`.
- **What it compares:** BG-1 counters against the durable fill records, the slot table and the ledger registry.
- **If the durable sources are consistent:**
  - the day's counters are rebuilt from them;
  - the gappy mark is cleared;
  - the rebuild is recorded;
  - alert `EXEC_PAR_COUNTER_REBUILT {day, mismatch_kinds}` fires.
- **If they cannot be reconciled:**
  - the day is added to `excluded_days`;
  - the integrity halt `day_excluded` is raised;
  - alert `EXEC_PAR_DAY_EXCLUDED` fires.
- **An unreconciled gappy day** inside any window makes the pass return FAIL (`stage_eval_fail:gappy`).

**Excluded days.**
- **The evaluator skips them in every window.** All other days, and their §5/§7 counters, carry forward.
- **The stage carries on.** Exclusion is not a K change, writes no `stage_reset`, and does not restart the stage.
- **Exclusion is not free:**
  - an excluded day still counts toward the 15-day stage cap;
  - §15-cumulative still counts its settled P&L once its durable fill records reconcile at a later boot.
- **Cap.** More than **2 excluded days in a stage** (counted from the latest `stage_reset.ts`) is a demotion verdict and sets the flag.

**Injected ports**, declared in `runtime/breaker_watcher.py`:
- **`ExecParStorePort`** (store writer).
  - Methods cover counters, the stamp, liveness fields, epoch rows and amendments, the flag, `stage_reset`, `excluded_days` and rebuild records.
  - Implemented by single-writer `SubmitIntentLatch` methods under `_require_held()`, without nesting `_mutex`.
  - Users: the watcher, BG-2, BG-3, BG-4 and BG-5.
- **`LedgerPredicatePort`** (value-free).
  - Returns booleans only, for example "is P&L ≤ −f × budget" and "is station-day open cost > f × budget".
  - Implemented over `DailySpendLedger`.
  - A raise or a non-bool return counts as tripped.
- **`ExecClientView`** (`:111`) stays read-only and gains no writer.

## 11. WP0 artefacts

Hashes computed at HEAD d3588ece; re-verify at freeze.

| Path | sha256 |
|---|---|
| `docs/evidence/m1v3/exec_parallel_wp0_findings.md` | `f4a5b8de1c856fa5ffb423fd783a2601bf2a3f4ad54ecd28f099ff907c67efb7` |
| `docs/evidence/m1v3/exec_parallel_dhat_results.json` | `5c1f29b0df248da74c4ed5c1ca364f93d8ab4256581dfb4db0aad2c3cb4f63f1` |
| `docs/evidence/m1v3/exec_parallel_dhat_results_main4_nyc.json` | `822460ede994cf8ac2169b33e5e6100beb2b3311a809f32d7422f8840fd9a6d3` |
| `docs/evidence/m1v3/exec_parallel_dhat_cands.json` | `55951aaf9147f4e295842865cd8672a8f0797bd801aa65ab224c8e3da003243d` |
| `docs/evidence/m1v3/exec_parallel_dhat.py` | `37bc13cc26ef796b1b5dfb5c3cd134e20e4f274940debf98d39e2a81a9f312eb` |

- **WP0 tree:** `b86ebf37` + `12d7ae78`.
- **Chosen K's CI:** at bucket 0.05, K=6, main4+nyc, the upper bound is 0.2905 on one seed. Verify against the JSON.
- **The script hash pins the WP0 version.** BG-10 changes the script, so the §3 re-run hashes the new version separately. This row is never re-pinned.

## 12. Permit-notional non-debit for boot fills (E14.6)

- A fill on an intent registered at boot (H6) does not debit the permit's session notional.
- **Accepted, because:**
  - the ledger counts it exactly once;
  - the undercount is at most `f_adm` = 0.50 of the budget per carry-over set;
  - it does not add up across respawns.
- **Anchors:** `test_boot_permit_untouched_by_open_intent_registration`, `test_boot_zero_fill_retire_no_permit_restore_d3`.

## 13. Freeze and amendment

**Freeze:**
1. Commit this document alone as `EXEC-PAR-D-PREREG.md`, with `Status: FROZEN`. At that point:
   - §11 and the code anchors are re-verified;
   - the §5 recorded table is filled;
   - V1–V3 are met.

   That commit's SHA is the frozen SHA.
2. A second commit adds `EXEC-PAR-D-PREREG.sha256`. BG-9 checks it at K>1.
3. **Deadline:** before the first K>1 boot, and no later than 2026-12-06T23:59Z.
4. Push only after the full gate reads EXIT=0.

**Amendment:**
- The frozen file is never edited. A change is a new doc, `EXEC-PAR-D-PREREG-A<n>.md`, peer-reviewed and frozen the same way. It applies only forward.
- **Tightening** can be applied immediately.
- **Loosening** needs a frozen amendment whose justification uses no data from the stage whose stop it loosens.

## 14. Activation checklist (in order)

**1. Build items merged.**
- **(a) For S1:**
  - WP-DR..WP7 (all merged; WP7 at d5e5568d);
  - BG-1 to BG-9;
  - BG-10(a), (c), (d) and (e).
- **(b) Before promotion:**
  - BG-10(b) before S1→S2;
  - BG-11 before S2→S3.

**2. Freeze (process step).**
- The §5 recorded table is filled, including the pinned simulation assumptions.
- V1–V3 hold (after the 95% switch if it was triggered).
- The burst threshold is stated.
- The document is frozen per §13, §11 re-verified, and the `.sha256` sibling committed.

**3. Gate at the activation SHA.**
- The full gate reads EXIT=0, including the frozen doc.
- `lint-imports` (console script, run from the tree) reports "N kept, 0 broken".

**4. Date.** On or after 2026-11-29. Decision recorded: a delay of at least 7 weeks is accepted.

**5. WINNER.** An eligible frozen-prereg WINNER exists (the M1-v3 read on or after 12-07, or another), and exactly one entry family is enabled.

**6. Caps and label.** The operator caps are set, the label is ≤ `0.05`, and only the label is recorded.

**7. §3 stop rule.**
- ≥20k resamples and 3 seeds; **every** seed ≤ 0.30 at K=6.
- The overdispersion arm is reported.
- The result, the script sha256s and the artefact are recorded.

**8. Supervisor restart.** The supervisor is restarted on WP5a or later and on BG-8.
- **Proof artefact:** `post(d) ok slot_schema_v2_admitted` plus `RESULT=OK` in `~/.local/share/breezy/run-reports-*/sup_restart_activation_*.txt`.

**9. Alert positive controls.** Through the live sink, one per kind. The sink control is re-run on every K>1 boot.
- `EXEC_PAR_K_FORCED_TO_1`
- `EXEC_PAR_BREAKER_TRIPPED`
- `TRADE_SUPERVISOR_BREAKER_WATCHER_DEAD`
- `TRADE_SUPERVISOR_BREAKER_RESOLVER_PASS_STALE`
- `TRADE_SUPERVISOR_BREAKER_ENTRY_HALT_LATCHED`
- `TRADE_SUPERVISOR_SLOT_TABLE_UNREADABLE_SLOT`
- `EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE`, `EXEC_PAR_NO_FILL_RETIRE_REFUSAL`, `EXEC_PAR_UNREADABLE_SLOT`, `EXEC_PAR_STUCK_SLOT_ON_HELD_SLUG`
- `TRADE_SUPERVISOR_EXEC_PAR_STAGE_STAMP_STALE`, shown firing with the node down
- the BG-8 halted-at-K=1 probe
- the BG-5 integrity-halt alert (`stage_eval_fail`)
- flag set
- **`EXEC_PAR_COUNTER_REBUILT`**
- **`EXEC_PAR_DAY_EXCLUDED`**

**10. Failure injection.** Gate tests against the **real** latch admission path. Each test asserts that a real submit is denied at submit time.
- **(a) Stop rules — each sets the flag:**
  - §5 Clopper-Pearson;
  - §5 burst (counted on arm time);
  - §6;
  - §7 coefficient, per-order and per-stage;
  - §9 intraday 0.25, 2-of-5 and 5 s;
  - §15 day, stage and cumulative.
- **(b) Demotion verdicts — each sets the flag:**
  - second failed promotion (re-look on cumulative data);
  - more than 2 excluded days.
- **(c) Integrity — each latches the expected reason and leaves the flag unset:**
  - evaluator exception;
  - evaluator timeout;
  - a thread hung past 240 s;
  - no completed pass by boot + 300 s;
  - BG-1 write failure;
  - `LedgerPredicatePort` raise;
  - `LedgerPredicatePort` non-bool return;
  - `write_breaker_halt` raise: the heartbeat stops, entries are denied, exits and the resolver are unaffected, and the flag write is still attempted;
  - task death via the done-callback;
  - task death before the callback is attached (per-tick check);
  - entries before the boot pass (`stage_eval_boot_pending`);
  - a previous-boot stamp, which must not clear the boot-pending denial;
  - a stale stamp;
  - an unreconciled gappy day;
  - an unreconcilable day → `excluded_days`, halt and alert; the stage is **not** restarted and no `stage_reset` is written.
- **(d) Pins:**
  - BG-1: reconciliation runs after the mass-status ingest;
  - BG-8: the supervisor never respawns or kills the node on any breaker alert;
  - BG-6: the breaker denial is entries-only;
  - BG-5/6: the `boot_ns` accessor;
  - window floor and arm-time attribution: a position armed before the reset and settled after it lands in the old windows and in cumulative;
  - the §9 intraday guard counts positions armed before the reset.
- **(e) Supporting only:** a dry boot on a backup copy of the store, with orders disabled.

**11. Rollback drill and CLI.** The rollback drill is green. BG-4 gate tests plus a tabletop on a backup store copy cover:
- `--list`.
- `--dry-eval`:
  - FAIL when the caps are absent;
  - cap values are never printed;
  - pre-floor counts are printed;
  - reconciliation runs first, with both a rebuild case and an exclusion case.
- `--reset-entry-halt` refused in each of these cases:
  - no dry record;
  - the dry record is older than the halt;
  - the dry record is older than the epoch `stop_ts`;
  - the flag is set at K>1;
  - a stop-rule halt has no matching `force_k1_cleared`;
  - an integrity halt has only a STOP-ACKNOWLEDGED verdict.
- `--clear-force-k1`:
  - refused when the flag is unset and the halt is not a stop rule;
  - succeeds when the flag is unset on a stop-rule halt, writing `force_k1_cleared` and `stage_reset`.
- `--set-force-k1`: preconditions enforced.
- The full step-1→6 sequence is accepted at the end.

**12. Evaluator and cross-check.**
- BG-5 wrote a stamp with `boot_ns` = the latch's `boot_ns` on a dry boot.
- BG-7's **first scheduled** read-only run (sqlite `mode=ro` URI) succeeded and agrees with the in-node verdict.

**13. Epoch row.** The BG-2 epoch row is written on a dry boot.

**14. Clean pre-boot state.**
- No OPEN or AMBIGUOUS intent.
- `halted: null`.
- Flag clear.
- No unreadable slot.
- Permit unexpired.

**15. Commit K=2.**
- Its gate run shows the BG-9 config test **PASSED, not SKIPPED**.
- Restart the supervisor in the 01:00–16:40Z window, then respawn the node.

**16. Post-boot checks.**
- No `EXEC_PAR_K_FORCED_TO_1`.
- The heartbeat appears within 60 s and carries the liveness fields.
- The permit line is in the node log.
- The epoch row shows effective_k=2.
- A `stage_reset` with cause `k_change` is present.
- The boot-pass stamp matches this boot and `stage_eval_boot_pending` has cleared.

Any failure → halt, then demote.

## 15. P&L safety stops (PROPOSED)

These are safety stops, not an edge test. Thirty entries cannot validate an edge, so promotion proves execution parity only.

- **Units.** Daily-budget units, **net of fees**, from the BG-1 settled-P&L accumulator, checked only through `LedgerPredicatePort`.
- **AMBIGUOUS entries** count as a full-cost loss until resolved. The overlap with §5 is accepted as conservative.
- **Attribution.** P&L is attributed by arm time (§1).

| Rule | Window | Action | Enforcer |
|---|---|---|---|
| Single climate-day net P&L ≤ −0.15 | Arm-time day, floored | Halt, flag; restart at S1 | BG-5 |
| Stage cumulative ≤ −0.40 | Since the latest `stage_reset`, excluded days skipped | Halt, flag, demotion verdict | BG-5 |
| Cumulative since the first K>1 boot ≤ −1.0 | Never floored; includes excluded days once reconciled | Halt, flag, K=1 | BG-5 |

- **Settlement-lagged.** Losses realize at settlement, so these stops act on the first pass after ingest. AMBIGUOUS entries count at once.
- **The intraday exposure guard** is the §9 station-day 0.25 halt. With §15-cumulative, it is the only cover for positions armed before a reset that are still open.

**Arithmetic.** Cap/budget 0.05, p ≈ 0.9: a win ≈ +0.0052 and a loss = −0.05.

| Stop | Losses needed | Loss rate |
|---|---|---|
| Day (−0.15) | About 4 in 7 entries | False trip about 0.3%/day at a 10% loss rate; about 2.3%/day at 18% |
| Stage (−0.40) | About 11 at n = 35; about 17 at n = 105 | 31%; 16% |
| Cumulative (−1.0) | About 18–20 net losses at n ≥ 200 | — |

The stage stop is a 15-day backstop, not a 5-day look.

---

## Rulings index

| ID | Where it now lives | Note |
|---|---|---|
| D1 | §1a boot-pass gate; §4 denials | Identity check replaced by E7 |
| D2 | §10a (`telemetry_write_fail`, gappy FAIL) | Gappy definition replaced by E3/H1 |
| D3 | §1a execution, liveness, `stage_eval_stuck`, halt-write raise | |
| D4 | §1a, §9, §10a | Integrity-class |
| D5 | §4 reset | Replaced by E1/G2; `--set-force-k1` kept as a tightening tool in §1b |
| D6 | §1a flag semantics | |
| D7 | §1a threading | |
| D8 | §10a accumulator; §15 | |
| D9 | §5 burst | |
| D10 | §1, §5 Wilson-DEFF, ≥8 days | Level floor replaced by E8 |
| D11 | §15 | |
| D12 | §3 step 5; §14.7 | |
| D13 | §14.10 | |
| D14 | BG-9 row; §14.2 | |
| E1 | §4 reset steps | |
| E2 | §1 windows | Record replaced by G1 |
| E3 | §10a gappy days | Abort replaced by H1; premise reworded by G4 |
| E4 | §4 step 3; §1b | |
| E5 | §1a integrity table | |
| E6 | §1a; §4; BG-6; BG-8 | |
| E7 | §1a boot-pass gate | |
| E8 | §5 V1 | 80% clause replaced by G6 |
| E9 | §1 looks | |
| E10 | §5 | |
| E11 | §5 recorded table | |
| G1 | §1 windows | G1(b) and its ordering clause replaced by H1 |
| G2 | §4 step 5 | |
| G3 | §1b; §1a | |
| G4 | §10a | |
| G5 | §1 windows | Generalised by I2 |
| G6 | §5 V2 | |
| G7 | §1 re-look | False-pass criterion replaced by I1 |
| G8 | — | Replaced by H1 |
| G9 | §10a; §14.9 | |
| G10 | §1a stamp; §4 supervisor; BG-5/6/8 | |
| H1 | §10a excluded days; §1 | |
| H2 | §4 step 3 | |
| H3 | §1b | |
| H4 | §1b; §4 step 5 | |
| H5 | §4 "Floor moved without a halt"; step 3(i) | |
| I1 | §5 V3 and the 95% switch; recorded table | |
| I2 | §1 windows; §9; §15 | |

## BUILD-GAP table (r3 IDs)

| ID | File | Purpose | Depends on | Gates |
|---|---|---|---|---|
| BG-1 | `runtime/exec_par_telemetry.py`, `runtime/breaker_watcher.py` (ports), `runtime/submit_intent.py` (single-writer methods), `adapters/polymarket_us/operator_controls.py` (predicates) | Per-climate-day counters and the settled-P&L accumulator; missing or None counts as a trip; `telemetry_write_fail`; gappy marks; reconciliation at boot (**after mass-status ingest, with an ordering test**), at the daily pass and in dry-eval; rebuild + `EXEC_PAR_COUNTER_REBUILT`; `stage_reset` and `excluded_days` record writers; `day_excluded` halt + `EXEC_PAR_DAY_EXCLUDED`; the two ports; predicate raise or non-bool counts as tripped | — | S1 |
| BG-2 | `app/trade.py` (boot row), `runtime/breaker_watcher.py` (forced/stop rows), `score_live_trials.py`, `family_tally_v2.py` | K-epoch ledger and stratification; `k_change` `stage_reset` at boot | BG-1 | S1 |
| BG-3 | `runtime/node_config.py` (`force_k1_on_durable_flag`), `app/trade.py:~1078`, latch flag writer | Durable flag; verdict-keyed write; boot check; unreadable counts as set | BG-1 | S1 |
| BG-4 | `runtime/clear_submit_intent_cli.py` | `--dry-eval` (launch environment, caps never printed, FAIL when caps absent, prints pre-floor counts, reconciles then evaluates, writes `stage_eval_dry`, appends to the report); `--clear-force-k1` preconditions (flag set or stop-rule halt; fresh complete PASS or STOP-ACKNOWLEDGED dry record) and its `force_k1_cleared` + `stage_reset` writes; `--set-force-k1` preconditions; `--reset-entry-halt` preconditions (§4 step 5) | BG-1, BG-3, BG-5 | S1 |
| BG-5 | new `runtime/exec_par_stage_eval.py` (pure), `runtime/breaker_watcher.py` (sub-task), `submit_intent.py` (public `boot_ns`) | Evaluator: loop-thread snapshot, detached task, executor-run, one outstanding pass; liveness fields; `stage_eval_fail`, `stage_eval_stuck` and `stage_eval_task_died` (callback plus per-tick check); stamp `{ts_ns, boot_ns}`; floor, arm-time attribution, excluded-day skip; Wilson-DEFF with ANOVA ICC; looks; §6, §7, §9 daily, §15; more than 2 excluded days → demotion | BG-1, BG-2, BG-3 | S1 |
| BG-6 | `runtime/breaker_watcher.py:_persist`, `SubmitIntentLatch._breaker_denial` | §5 Clopper-Pearson and burst (arm time, ≥5 or ≥6); §9 0.25 over all open positions; stale stamp; `stage_eval_boot_pending` denial via `boot_ns`; heartbeat-stop on halt-write raise; entries-only pin test | BG-1, BG-3, BG-5 | S1 |
| BG-7 | `scripts/analysis/exec_par_stage_gate.py` + timer | Read-only cross-check via sqlite `mode=ro`; promotion and stage report (rebuilt days, excluded days, post-reset settlements of entries armed before the reset); `k_epochs.jsonl`; never writes `BREAKER_KEY` | BG-5, BG-2 | S1 |
| BG-8 | `runtime/trade_supervisor.py:~3155` | `halted` and unreadable-slot probes at any K; stamp probe at K>1; **pin test: never respawns or kills the node on any breaker alert, including `WATCHER_DEAD`** | BG-5 | S1 |
| BG-9 | `tests/unit/test_exec_par_wp5b_config.py` | Skips at K=1; at K>1 fails on a missing or mismatched frozen doc or `.sha256`, or a label mismatch; asserts the single-family invariant | — (the freeze is §14.2) | S1 |
| BG-10 | `operator_controls.py`, `docs/evidence/m1v3/exec_parallel_dhat.py` | (a) label-only reader plus a test that only the label prints; (b) hold-input mode; (c) **simulation outputs**: level (V1); pre-window ANOVA ICC; two-look pass probability at p = 0.18 (V2); two-look false pass at p = level (V3) with the 90→95% switch and V2 recompute; burst false alarm (≥5 and ≥6, ρ = 0 and 0.1, empirical intraday entry times) and the threshold applied; Clopper-Pearson + burst operating characteristics; pinned entries/day distribution, ICC model, seeds and runs; (d) ≥20k resamples, both seeds varied; (e) ρ = 0.1 arm | (b) needs BG-2 | (a)(c)(d)(e): S1; (b): S1→S2 |
| BG-11 | `continuous_strategy.py`, `continuous_no_side.py` | Per-reason pre-filter WAIT counters via BG-1 | BG-1 | S2→S3 |
