# D-PREREG: Execution-design pre-registration for EXEC-PAR activation at K>1

**r3 (2026-10-11), supersedes r2 7ec83778**

- **Status:** DRAFT, not frozen. Coordinator rulings C1–C6 on the r3 drafting notes are applied inline (C1: BG-7 opens the store with a sqlite `mode=ro` URI, the same as the WP5b supervisor probe; C2: proposed names are placeholders until BG build; C3: an evaluator-level failure (exception, timeout, missing input) halts only and never sets the flag; demotions in S2 mean automatic verdicts; C4: §8 circularity removed; C5: restart-at-S1 vs one-stage demotion split in §1; C6: the WP0 dhat hash stays pinned and the BG-10 version is hashed separately). §13 gives the freeze procedure.
- **Governs:** every node boot where the configured K (`runtime/exec_par_constants.py:EXEC_PAR_MAX_CONCURRENT_INTENTS`) is greater than 1.
- **Source plans:** `EXEC-PAR-parallel-intents_plan_r5.md` §3.6, §3.9, §6, §7, §8, plus `..._r5_1_delta.md` E1–E14.
- **Code basis:** HEAD `7ec83778` (the r2 commit). The §11 artefact hashes stay as computed at `d3588ece`; none of those paths changed between the two commits. Where this document and the code disagree, the code value is cited and wins.
- **Labels:** PROPOSED marks a threshold the plan left open. BUILD-GAP (BG-n) marks enforcement code that does not exist yet. **The BG IDs are renumbered in r3.** The mapping from r2 IDs is in the BUILD-GAP section.

**Honest prior.** M1-v3's own prior disclosure puts P(WINNER) near zero, so this ramp may never execute. The build is still justified because a working K>1 path is a precondition of T1 (§14.5).

## Changes from r2

| Change | Ruling |
|---|---|
| The daily evaluator runs inside the node as a `breaker_watcher` sub-task: at boot, after each climate-day close, and on settlement ingest. It runs off-loop and bounded, writes through the latch, and fails closed. The 16:50Z script becomes read-only. A new stamp probe is added to the supervisor. The latency bound is stated. | S1 |
| The force-K1 flag is set only by stop rules and demotion verdicts. Transient conditions only halt. Reset order is: clear the flag, then reset the halt. The CLI items are merged. | S2 |
| Durable counters are extended. Missing or None counts as a trip. Two new ports are named. The layering rule is stated. | S3 |
| §15 is resized (−0.15 / −0.40 / −1.0), settlement-lagged, and shows its arithmetic. | S4 |
| §5 becomes a Clopper-Pearson lower-bound halt plus a 60-minute burst guard. The per-day guard and the 0.45 bound are dropped. Promotion uses the day-clustered upper bound against the BG-10 level. | S5 |
| §7 fee rules are per order and per stage. Per-fill checks are report-only. Slippage mean ≤ 0.005. | S6 |
| §3 re-run: ≥20,000 resamples, 3 seeds varying both seeds, mean ≤ 0.30 and max ≤ 0.305, plus an overdispersion arm. | S7 |
| The config test skips at K=1 and is strict at K>1. The single-family test folds in. §14 is reordered. | S8 |
| The offline writer is removed. | S9 |
| The BUILD-GAP list is consolidated and renumbered, with each item's gating stage. | S10 |
| §14 gains a failure injection, the flag→reset tabletop and the stamp-probe control. The header is fixed. | S11 |

## 0. Binding invariants

- Nautilus Trader is immutable.
- `allow_short` stays `False`.
- The two operator caps (max daily budget, max per position) are read-only. This document never states or assigns them. Every threshold is a fraction of the daily budget, checked by value-free ledger predicates.
- Nothing in this document changes the halt drop-in or `BREEZY_ORDERS_ENABLED`. K>1 changes concurrency only. It is never a decision to enable orders.
- This document is independent of `docs/evidence/m1v3/PREREG.json` and never edits it. It uses no data from climate days 2026-10-07..11-28 and none from the F13 sealed holdout.
- **Layering.** `runtime` may import `adapters`; `adapters` never import `runtime`. The import-linter layers contract in `pyproject.toml` has two pinned `ignore_imports` exceptions for `runtime.settings`, and no new exception is added. `runtime` never imports `breezy.analysis` (`pyproject.toml:152-160`), so the evaluator's pure function lives in `runtime`.

## 1. K schedule

| Stage | K | Entry condition | Minimum to promote |
|---|---|---|---|
| S0 | 1 | Today | Every §14 item marked "for S1" passes |
| S1 | 2 | §14 complete | ≥5 climate days with ≥1 K>1 entry fill, ≥30 posted entry orders, and every §5–§9 and §15 check green over the stage |
| S2 | 4 | S1 promoted, the §8 gate passed, and BG-10(b) merged | The same minimums as S1 |
| S3 | 6 | S2 promoted, the §3 re-run passing, and BG-11 merged | Terminal stage. K≥7 needs an amendment. |

- **Ceiling (PROPOSED).** K=6 is the smallest K that passed the gate arm at the 0.05 bucket on main4+nyc (WP0 Headline). The no-id variant needed K=7 and is not authorised.
- **Looks.**
  - The in-node evaluator (BG-5) evaluates promotion **once**, on the first climate day both minimums are met.
  - A fail holds the stage for exactly one 5-day extension, after which it is evaluated once more. A second fail is a demotion verdict (§1a).
  - A stage lasts at most **15 climate days**, and the extension ends at that cap. A stage that reaches the cap with its minimums unmet holds at its current K and is never promoted without an amendment.
  - Every rolling window (§5, §6, §9, §15) resets at every K change.
- **Mechanics.** Each K change is one commit that edits only `EXEC_PAR_MAX_CONCURRENT_INTENTS` and cites the frozen SHA and the stage. Then:
  1. Run `scripts/ci/run_tests_no_egress.sh` and read EXIT=0.
  2. Restart the supervisor, because it reads K.
  3. Respawn the node.
- **Code-enforced forced-to-1 conditions** (effective K, logged at ERROR, alert `EXEC_PAR_K_FORCED_TO_1`):
  1. **Supervisor marker.** `node_config.force_k1_without_supervisor_marker` (`node_config.py:756`), called at `app/trade.py:1078`. A raising read counts as not admitted.
  2. **Bucket guard.** `exec/client.py:_apply_slot_boot_guards` → `_bucket_force_reason`. It forces K=1 when the label is not configured, there is no ledger, `cost_budget_bucket()` raises, or the live label ranks above the frozen label.
  3. **Durable force-K1 flag (BG-3).** See §1b.
  4. **Restart over a v2 table.** A restart with K forced to 1 over a v2 table still resolves every open slot (r5.1 E7).
- **After a stop (coordinator ruling C5, r3):** a stop-rule halt (§4 breaker trips, §5, §7, §15 day and cumulative) restarts the ramp at S1. A **demotion verdict** (§9 2-of-5 stops, §15 stage stop, a second failed promotion) moves down exactly one stage. Either way, resuming requires an incident report in `docs/incident-reports/`, the flag cleared by a human (§4), and the lower-K commit.
- **No post-hoc K.** No K outside {1, 2, 4, 6} is ever set.

## 1a. Real-time enforcement principle

- Every rule ends in an **automatic** entries-only halt, written through the node's own latch: `SubmitIntentLatch.write_breaker_halt` (`submit_intent.py:1098`). It runs under `_require_held()` and `_mutex`, and is sticky (the first reason wins).
- The halt is the stop. A demotion commit is deferred cleanup.
- **The force-K1 flag (BG-3) is set ONLY by** §5, §6, §7, §9 and §15 stop rules evaluated on complete inputs, and by demotion verdicts (a second failed promotion, the §9 demotions).
- **Transient or integrity conditions only halt; they never set the flag.** These are: a stale stamp, a stale heartbeat, a stale resolver, an evaluator exception or timeout, and missing, None or gappy inputs. Their reset evidence must show that the input or process was repaired.
- **Write order:** halt first, then the flag. On its next pass the evaluator re-asserts a missing flag when the latched halt reason is a stop rule.

| Rule | Class | Enforcer | Sets flag |
|---|---|---|---|
| Stuck slots, AMBIGUOUS notional, contradictions, duplicates (§4) | AUTOMATIC-intraday | `BreakerWatcherActor._persist` (existing) | No |
| AMBIGUOUS Clopper-Pearson halt and 60-minute burst (§5) | AUTOMATIC-intraday | BG-6 | Yes |
| Station-day open cost above 0.25 of the budget, current day (§9) | AUTOMATIC-intraday | BG-6 | Yes |
| Evaluator stamp stale or never written | AUTOMATIC-intraday | BG-6, plus the supervisor alert BG-8 | No |
| Evaluator exception, timeout, or bad input | AUTOMATIC on the evaluator pass | BG-5 | No |
| Dropped share (§6), fee/slippage (§7), station-day 2-of-5 and 5 s window (§9), all §15 P&L stops, promotion evaluations | AUTOMATIC-daily (in-node) | BG-5 | Yes |
| Independent cross-check and promotion report | READ-ONLY | BG-7 | Never writes |
| Breaker reset (§4), §8 hold-time gate | PROCEDURAL | Coordinator | — |

**In-node evaluator (BG-5).**
- **Logic.** A pure function in a new `runtime/exec_par_stage_eval.py`. Its inputs are BG-1 counters, BG-2 epochs and `LedgerPredicatePort` booleans. It returns a verdict.
- **Scheduling.** It is run by a `BreakerWatcherActor` sub-task:
  - **at boot**, which covers hand relaunches;
  - at the first tick after every governed station's climate day has closed;
  - on the tick that first observes a new settled-P&L counter (§15).
- **Execution.** The watcher runs it through `loop.run_in_executor` inside `asyncio.wait_for`, with a timeout of 120 s (PROPOSED). Only one pass is in flight at a time. A pass still running after its timeout blocks new passes until it returns. The watcher, not the executor thread, writes the halt, the flag and the stamp through the latch.
- **Fails closed.** An exception, a timeout, or a missing, None, gappy or non-monotonic input writes the halt with reason `stage_eval_fail:<kind>`.
- **Stamp.** A successful pass writes `exec/polymarket_us/exec_par/stage_eval/stamp` (PROPOSED key) through the store-writer port. Stale means older than 26 h, or never written after the first K>1 climate day.
- **No lock gap and no timer race.** Every write comes from the single lock-holding process.
- **Latency bound.**
  - Daily rules act within one climate-day close of the day they measure.
  - §15 stops act on the first pass after the settlement is ingested.
  - No rule waits for a respawn.

## 1b. Durable force-K1 flag (BG-3, CLI in BG-4)

- **Store key:** `exec/polymarket_us/exec_par/force_k1`, holding `{reason, ts_ns, set_by}`.
- **Written** through a new single-writer latch method behind the store-writer port, under the held latch.
- **Set** only per §1a.
- **Cleared** only by `clear_submit_intent_cli --clear-force-k1 --incident-report <existing path>` (BG-4).
- **Checked at boot** by a new `node_config.force_k1_on_durable_flag(latch, store)`, called next to `force_k1_without_supervisor_marker` at `app/trade.py:1078`. When the flag is set, it calls `latch.force_k1(reason)` (`submit_intent.py:850`).
- An unreadable flag counts as set.
- This is not a byte-pinned file, and `_bucket_force_reason` is unchanged.

## 2. Exposure fractions

All values are fractions of the operator's **daily budget**, never dollars.

| Constant | Value | Anchor |
|---|---|---|
| `f_adm` | 0.50 | `node_config.OPEN_EXPOSURE_BOUND_FRACTION`, enforced by `DailySpendLedger._require_exposure_headroom_locked` and `exposure_admission_refusal`. It raises `OpenExposureBoundExceeded` and is not a day-stop. |
| `f_breaker` | 0.25 | `node_config.BREAKER_OPEN_AMBIGUOUS_FRACTION`, through `DailySpendLedger.breaker_fraction_exceeded` (`operator_controls.py:934`). Any raise, or any AMBIGUOUS entry of unknown size, counts as tripped. |

At cost = cap and bucket 0.05:
- one order is at most 0.05 of the budget;
- AMBIGUOUS exposure at K=6 is at most 0.30, below `f_adm`;
- the breaker trips once more than 5 cap-sized orders are AMBIGUOUS;
- exits never enter the registry (E4).

## 3. Frozen cost/budget bucket and the activation re-run

- **Frozen label: `0.05`.** The unit is cap / daily budget (E6).
  - Anchor: `node_config.EXEC_PAR_FROZEN_BUCKET = "0.05"` (`:748`), passed to the client as `frozen_cost_budget_bucket` (`:1105`).
  - Ladder: `operator_controls._COST_BUDGET_BUCKETS` = {`≤0.02`, `0.05`, `0.10`, `0.25`, `0.50`}, with the sentinel `>0.50`.
- **Why 0.05.** WP0 passed it at K=6.
  - main4: CI upper bound 0.2755.
  - main4+nyc: CI upper bound **0.2905**, a margin of 0.0095 against 0.30, on a single seed with 2,000 resamples (`RESAMPLES`, `exec_parallel_dhat.py:70`).
- **The sim is slightly conservative.** The simulated cost/budget ratio is about 0.0505, against a live label of 0.05.
- **0.10 is not frozen.** It passes only on main4 at K=7, driven by free-balance arm B, and fails on main4+nyc at 0.420.
- **Clustering is unmodelled.** WP0 drew p_amb independently per order, with a per-day seeded draw (`random.Random(f"wp0|{p_amb}|{no_id}|{day}")`, `:376`). Day-level clustering of AMBIGUOUS is not modelled, which favours a pass.
- **Procedure:**
  1. The operator sets the caps. This document assigns no value.
  2. The coordinator derives the label only through the BG-10(a) label-only reader and records only the label.
  3. Re-run `exec_parallel_dhat.py` (BG-10 version) on pre-2026-10-07 inputs at cost = cap, using the row of the **actual** label. Use the gate arm:
     - p_amb 0.33;
     - one stuck slot;
     - the 5/s throttle (`TRADE_RISK_MAX_ORDER_SUBMIT_RATE = "5/00:00:01"`);
     - `f_adm`;
     - the worse free-balance arm.
  4. **Resampling.** Use **≥20,000** bootstrap resamples and **3 seeds**. Each seed varies BOTH:
     - `BOOT_SEED` (fixed at `:71`; used at `:416`); and
     - the draw seed (a seed component added to the `:376` string).
  5. **Stop rule.** The day-clustered bootstrap CI upper bound of the day-level p90 d̂ must meet both conditions at **K=6** and at the actual label:
     - the **mean across seeds ≤ 0.30**; and
     - the **max ≤ 0.305**.
     
     Otherwise K stays 1.
  6. **Overdispersion arm (report-only).** Add a day-overdispersed p_amb arm (ρ = 0.1, beta-binomial by day) and report it. It does not gate.
  7. Store the result JSON under `docs/evidence/exec_par/`, with the sha256 of both the result and the BG-10 script version (§14.7).
  8. A label of `≤0.02` is admissible: it ranks below the frozen label, and main4+nyc passes it at K=6.
- **Freeze enforcement (BG-9).** `tests/unit/test_exec_par_wp5b_config.py`:
  - **At configured K = 1:** skip.
  - **At K > 1:** fail if any of these holds:
    - the frozen `EXEC-PAR-D-PREREG.md` is missing;
    - the `EXEC-PAR-D-PREREG.sha256` sibling is missing;
    - the sibling does not match the doc's bytes;
    - the §3 label in the frozen doc differs from `EXEC_PAR_FROZEN_BUCKET`.
  - The same file asserts the single-family boot invariant (§9).

## 4. Breaker: triggers, reset and rollback drill

**Trip triggers.** `BreakerWatcherActor._persist` (`breaker_watcher.py:453`) runs every 5 s and is registered only at K>1 (`build_exec_watcher`, `:542`). It trips on:
- ≥2 open intents older than `STUCK_AGE_NS` = 900 s. The code uses 900 s for both the with-id and no-id shapes; the code wins.
- AMBIGUOUS notional above `f_breaker`.
- Any increase in `contradiction_events_total` (E14.5).
- Any increase in `duplicate_suspect_total`.
- The BG-6 reasons, and BG-5 verdicts (§1a).

**Duplicate detector.** It only backs up the stuck-slot check. It runs after the `L_feed` = 300 s lag guard and needs confirmation on a second consecutive pass. A duplicate on an order that resolves normally is caught only by the 120 s cool-off and position reconciliation.

**Halt.** Entries only, sticky, in `BREAKER_KEY`. Exits and the resolver are never blocked.

**Entry denials** (`SubmitIntentLatch._breaker_denial`):
- the record is absent more than 60 s after boot;
- the record is garbled;
- the halt is set;
- the heartbeat is older than 60 s;
- the resolver pass is older than 600 s;
- a stamp is more than 5 s in the future.

**Supervisor alerts** (`breaker_supervisor_watch.decide_breaker_alerts`): watcher dead, resolver stale, halt latched, unreadable slot. They repeat hourly.
- **BG-8.** `trade_supervisor.py:3155` currently returns before probing when `configured_exec_par_k() <= 1`. Change it so that every 10 min, read-only:
  - it probes `halted` and unreadable slots at **any** K;
  - when configured K > 1, it probes the BG-5 **stamp** and alerts `TRADE_SUPERVISOR_EXEC_PAR_STAGE_STAMP_STALE` (PROPOSED name) when the stamp is stale per §1a.
  
  This alerts even when the node, and so the watcher, is down.

**Reset.** Done by the coordinator under the standing pre-authorisation. The operator gets the alert and is not asked.
- **Timing.** Only at the **16:50Z daily respawn**, never mid-day.
- **Pre-check.** No held-position exit is due within 30 min.
- **Steps (in this order):**
  1. **Gather evidence.**
     - The trip reason and held list from `EXEC_PAR_BREAKER_TRIPPED`.
     - A venue positions GET that reconciles every held slug, with the NO-as-short-YES sign applied.
     - `clear_submit_intent_cli --list`.
     - Every stuck slot resolved, or cleared with `--intent-id --resolution --evidence`.
     - Venue order history for a contradiction or duplicate trip.
     - For a `stage_eval_fail` or stale-stamp halt: proof that the input or process was repaired.
     - An incident report.
  2. **Take the node down** (hand-relaunch mechanics). The CLI refuses while the node holds the lock. Recorded cost: no resolver or exits while it is down. Target ≤10 min (PROPOSED).
  3. **Clear the flag**, if it is set: `breezy.runtime.clear_submit_intent_cli --clear-force-k1 --incident-report <path>`.
  4. **Reset the halt:** `... --reset-entry-halt --ack-held-positions-reviewed --incident-report <path>`, which calls `SubmitIntentLatch.reset_breaker_halt` (`submit_intent.py:1167`).
     - **BG-4** refuses without `--incident-report` pointing to an existing file.
     - It also **refuses while the flag is set and the configured K > 1**, which is why step 3 comes first.
     - Use the exact venv interpreter.
  5. **Demote** (cleanup commit plus gate). Relaunch.

**Rollback drill** (before the first K>1 boot and after any code rollback; green at the activation SHA):
- `test_rollback_drill_after_drain_and_reset_old_reader_sees_valid_v1_retired` (`test_exec_par_wp5a_decode.py:298`).
- `test_drain_then_reset_then_rollback_drill` (**WP7, pending**).
- `test_restart_with_k_forced_1_over_open_v2_table_resolves_all_slots_and_downgrades` (`test_submit_intent_slots.py:620`, `test_exec_par_wp4_boot.py:467`).

**Rollback order:**
1. Review held positions.
2. Clear the flag.
3. Reset the breaker.
4. Drain to at most one open slot (the table rewrites as v1).
5. Set K=1.
6. Verify `halted: null` before reverting any code.

## 5. AMBIGUOUS-rate halt (PROPOSED)

- **Metric.** AMBIGUOUS entries over posted entries.
  - The window is all K>1 entries since the last K change (stage-cumulative, BG-2 epochs).
  - Counts come from BG-1.
- **Halt** (AUTOMATIC-intraday, BG-6; sets the flag) when either holds:
  - n ≥ 20 and the one-sided **Clopper-Pearson lower bound at α = 0.01** of the AMBIGUOUS rate exceeds **0.18**;
  - **≥4 AMBIGUOUS within any 60 minutes** (burst guard, at any n).
- There is no per-day guard. For reference, 0.18 ≈ the WP0 hold-input point estimate 7/39 = 0.179.
- **Clustering.** AMBIGUOUS outcomes may be day-clustered, so the effective n is nearer the number of days than the number of orders.
- **Operating characteristics.** These are reviewer simulations; BG-10 must reproduce and record them before the freeze.
  - Model: Poisson(7) entries/day, independent outcomes.
  - False alarm over 15 days at p = 0.18: about **4%**, or about **13%** with day overdispersion ρ = 0.1.
  - Power within 5 days: about **47%** at p = 0.33 and about **89%** at p = 0.45.
- **Promotion** requires both:
  - the **day-clustered** (bootstrap over climate days) one-sided 90% upper bound of the stage AMBIGUOUS rate is ≤ the **BG-10 level**;
  - no §5 halt fired during the stage.
- **BG-10 level.** The p_amb at which the §3 stop rule (K=6, stuck=1, p90 CI upper bound) reaches 0.30. It is derived by BG-10(c) and recorded here before the freeze. The 0.33 Wilson upper bound of 7/39 remains only the §3 gate-arm proxy.

## 6. Live dropped-candidate-share stop (PROPOSED)

- **Metric:** denied candidates over all candidates. Denials counted:
  - `OpenExposureBoundExceeded`;
  - K-full;
  - cool-off (`DEFAULT_COOLOFF_NS` = 120 s);
  - throttle;
  - free balance;
  - BG-11 pre-filter WAITs.
  - Breaker and stale denials are reported separately and excluded.
- **Stop at S3** (AUTOMATIC-daily, BG-5): the pooled trailing-5-day share is above 0.30 on two consecutive daily evaluations. The K>1 programme is then suspended until an amendment re-runs WP0 with live hold data.
- **S1/S2:** reported only. This is why BG-11 is required only before S3.
- A missing counter means FAIL.
- The day-level p90 appears only in the stage report (≥15 days).
- **BG-11.** `continuous_strategy._admission_refusal` (`:2602`) → `TrialDayLatch.admission_would_refuse` (`trial_day_latch.py:784`) returns a WAIT without an `OrderDenied`, so `ExecParDigest.record_denial` never sees it. Add per-reason pre-filter counters in `continuous_strategy.py` and `continuous_no_side.py`, persisted through BG-1.

## 7. Slippage and fee parity (PROPOSED)

**Fee** (AUTOMATIC-daily, BG-5):
- **Coefficient.** On every K>1 fill, `fee_coefficient_at_fill` (stamped by `exec/client.py:record_fill`) must equal θ = 0.0695 (`PREREG.json` `theta`) exactly. A mismatch or a None halts.
- **Per order.**
  - Σ realized cents must equal `ROUND_HALF_EVEN(θ·Σ C·p(1−p))` at currency precision (`fees.py:597-605`).
  - Single-fill orders must match exactly; multi-fill orders are allowed ±1 cent.
  - A violation halts.
- **Per stage.** Halt when |Σ realized − Σ unrounded exact| > max(2 c, 0.5 c × orders).
- **Per fill.** Mismatches are **report-only**. `fees.py` documents per-fill rounding as an approximation of the venue's cumulative fee.
- **Reconciliation.** A `fee_reconciled=False` share above 10% blocks promotion.

**Slippage**, per fill, is `fill_px − decision ask`. A missing decision ask means FAIL. Promotion requires:
- a stage mean ≤ **0.005**; and
- ≤10% of fills above 0.02.

**Parity** (unchanged from r2) is measured against the **K=1 pre-boot fill ledger** of the same family: mean parallel minus serial ≤ 0.005 when there are ≥20 K=1 fills; otherwise report-only.

**Note.** Together the slippage and parity tolerances allow about 1 c of slack, against an edge of about +2 c.

## 8. NO≥0.90 hold-time ramp gate (S1→S2)

WP0's hold inputs contain no NO≥0.90 order, and every AMBIGUOUS order was YES. The hold mixture is assumed, not measured.

- **Gate (PROCEDURAL; needs BG-10(b)).**
  - Collect ≥20 posted NO≥0.90 entries at S1.
  - Measure arm→retire hold times and the AMBIGUOUS share.
  - Re-run §3 with the empirical holds and p_amb = max(0.33, measured Wilson upper bound). The BG-10 level is never used as a §3 input (coordinator ruling C4, r3): it is the boundary at which §3 reaches 0.30, so using it as an input is circular. It serves only as the §5 promotion bound.
  - It must pass the §3 stop rule at K=6 at the actual label.
- **15-day cap.** If 20 such orders are not reached within the S1 cap, hold K=2. There is no promotion to S2.
- **BG-10(b)** adds a hold-input-only mode to `exec_parallel_dhat.py`. It reads live K>1 hold times dated on or after 2026-11-29; candidates still come only from the pre-window set.

## 9. Concentration

| Scope | Limit | Enforcement |
|---|---|---|
| Per slug | 1 open slot (YES/NO share it) plus a 120 s cool-off | `domain/exec_slots.admit`; `DEFAULT_COOLOFF_NS` |
| Per order | Per-position cap | `DailySpendLedger.authorize_order_cost` |
| Station-day, intraday | Open cost above 0.25 of the budget → halt | BG-6 (value-free predicate) |
| Station-day, stop (PROPOSED) | Above 0.25 on 2 of the last 5 days → halt, demotion verdict | BG-5 over BG-1. No cap: the 2026-09-14 ruling stands. |
| 5 s window (PROPOSED) | On days with ≥6 orders, more than 0.50 of the day's entry notional inside one `WINDOW_NS` = 5 s window, on 2 of the last 5 days → halt, demotion verdict | BG-5 over BG-1 |
| Per family | Exactly one entry family | `app/trade.py:1047` loads only `settings.sending_family_id`, and `:1066-1070` raises `SettingsError` on a mismatch. Asserted by BG-9. |

## 10. Parallel fills never feed the M1-v3 verdict

**What M1-v3 reads (verified).** `scripts/analysis/no_longshot_pooled_test.py` reads only the recorder Depth10 tape (`RecorderCatalogTape`, first row in [12:00, 13:00) UTC) and the CLI finals. It reads no exec store and no fills.

**Ways K>1 could leak into it:**
- **Depth consumption.** Negligible at about 1 contract per order.
- **The shared WS subscription cap** (10 per connection).
- **Node or recorder restarts** that leave gaps in the tape.

**Rules:**
1. No K>1 boot before 2026-11-29T00:00Z. §14.5 already blocks K>1 until the M1-v3 read (on or after 12-07). Both rules are kept.
2. One look only. No K>1 statistic ever enters the M1-v3 report.
3. No recorder-gap day may be attributable to a K change.
4. Every K>1 fill is reported in a separate stratum.

**BG-2 (K-epoch ledger):**
- At boot, `app/trade.py` appends `{commit_sha, effective_k, force_reason, boot_ts}` under `exec/polymarket_us/exec_par/epoch/<boot_ts_ns>` before `node.run`.
- The watcher appends an amendment row when the bucket guard forces K=1.
- `stop_ts` is written at disposal or halt. A crash is closed by the next `boot_ts`.
- Fills are attributed by `ts_event`. A configured K>1 epoch with no forced row counts as parallel.
- BG-7 exports the rows to `docs/evidence/exec_par/k_epochs.jsonl`.
- `score_live_trials.py` and `family_tally_v2.py` stratify on the epoch.

## 10a. Durable telemetry and ports (BG-1)

`ExecParDigest` is in memory, resets at every respawn, keys by UTC day, and overflows at `MAX_REASONS` = 32 (`exec_par_telemetry.py:35`).

BG-1 persists **per-climate-day** records to the exec-state store. The watcher writes them on its tick, fed by its `events.order.*` subscription (`breaker_watcher.py:99`) and the native `portfolio`. The records are:
- posted entries;
- AMBIGUOUS;
- denials by reason;
- BG-11 WAITs;
- fills;
- realized fees;
- unrounded exact fees;
- slippage per fill;
- settled P&L, net of fees;
- open cost per station-day, as a value-free fraction flag;
- 5 s window peaks.

**A missing day or a None value counts as FAIL/trip, never 0.** Currency values stay in the local store. They are never logged or alerted. They are compared with budget fractions only through `LedgerPredicatePort`.

**New injected ports**, declared beside the existing ones in `runtime/breaker_watcher.py`:
- **`ExecParStorePort`** (store writer). Its methods cover the counters, the stamp, epoch amendments and the flag. It is implemented by new single-writer `SubmitIntentLatch` methods under `_require_held()`. Users: the watcher, BG-2 and BG-3.
- **`LedgerPredicatePort`** (value-free). It returns booleans only, for example "is P&L ≤ −f × budget" and "is station-day open cost > f × budget". It is implemented over `DailySpendLedger`. Users: the watcher, BG-2, BG-3 and BG-5.
- **`ExecClientView`** (`:111`) stays read-only and gains no writer.

## 11. WP0 artefacts

Hashes computed by the coordinator at HEAD d3588ece; re-verify at freeze.

| Path | sha256 |
|---|---|
| `docs/evidence/m1v3/exec_parallel_wp0_findings.md` | `f4a5b8de1c856fa5ffb423fd783a2601bf2a3f4ad54ecd28f099ff907c67efb7` |
| `docs/evidence/m1v3/exec_parallel_dhat_results.json` | `5c1f29b0df248da74c4ed5c1ca364f93d8ab4256581dfb4db0aad2c3cb4f63f1` |
| `docs/evidence/m1v3/exec_parallel_dhat_results_main4_nyc.json` | `822460ede994cf8ac2169b33e5e6100beb2b3311a809f32d7422f8840fd9a6d3` |
| `docs/evidence/m1v3/exec_parallel_dhat_cands.json` | `55951aaf9147f4e295842865cd8672a8f0797bd801aa65ab224c8e3da003243d` |
| `docs/evidence/m1v3/exec_parallel_dhat.py` | `37bc13cc26ef796b1b5dfb5c3cd134e20e4f274940debf98d39e2a81a9f312eb` |

- **WP0 tree:** `b86ebf37` + `12d7ae78`.
- **Chosen K's CI:** at bucket 0.05, K=6, main4+nyc, the upper bound is 0.2905 on one seed. Verify against the JSON.
- **The `exec_parallel_dhat.py` hash pins the WP0 version.** BG-10 changes the script, so the re-run records the new version's hash separately (§3 step 7). This row is never re-pinned.

## 12. Permit-notional non-debit for boot fills (E14.6)

- A fill on an intent registered at boot (H6) does not debit the permit's session notional.
- **Accepted, because:**
  - the ledger counts it exactly once;
  - the undercount is at most `f_adm` = 0.50 of the budget per carry-over set;
  - it does not add up across respawns.
- **Anchors:** `test_boot_permit_untouched_by_open_intent_registration`, `test_boot_zero_fill_retire_no_permit_restore_d3`.

## 13. Freeze and amendment

**Freeze:**
1. Commit this document alone as `EXEC-PAR-D-PREREG.md`, with `Status: FROZEN`, §11 re-verified, and both the BG-10 level and the §5 operating characteristics recorded. That commit's SHA is the frozen SHA.
2. A second commit adds `EXEC-PAR-D-PREREG.sha256`. BG-9 checks it at K>1.
3. **Deadline:** before the first K>1 boot, and no later than 2026-12-06T23:59Z.
4. Push only after the full gate reads EXIT=0.

**Amendment:**
- The frozen file is never edited. A change is a new doc, `EXEC-PAR-D-PREREG-A<n>.md`, peer-reviewed and frozen the same way. It applies only forward.
- **Tightening** can be applied immediately.
- **Loosening** needs a frozen amendment whose justification uses no data from the stage whose stop it loosens.

## 14. Activation checklist (all items, in order)

1. **Build items merged.**
   - **(a) Required for S1:**
     - WP-DR..WP7 (**WP7 pending**, with its §4 drill test);
     - BG-1 to BG-9;
     - BG-10(a), (c), (d) and (e).
   - **(b) Required before promotion:**
     - BG-10(b) before S1→S2 (§8);
     - BG-11 before S2→S3 (§6).
2. **Freeze.**
   - The BG-10 level and the reproduced §5 operating characteristics are recorded in §5.
   - This document is frozen (§13).
   - §11 is re-verified and the `.sha256` sibling is committed.
3. **Gate at the activation SHA.** The full gate reads EXIT=0 there (including the frozen doc), and `lint-imports` (console script, run from the tree) reports "N kept, 0 broken".
4. The date is on or after 2026-11-29. **Decision recorded:** no K>1 boot happens before then, a delay of at least 7 weeks, accepted.
5. An eligible frozen-prereg WINNER exists (M1-v3 read on or after 12-07, or another), and exactly one entry family is enabled.
6. The operator caps are set, the label is ≤ `0.05`, and only the label is recorded.
7. The §3 stop rule passes: ≥20k resamples, 3 seeds, mean ≤ 0.30 and max ≤ 0.305, at K=6. The overdispersion arm is reported. The result, the script-version sha256s and the stored artefact are recorded.
8. **Supervisor restart.** The supervisor is restarted on WP5a or later and on BG-8. **Proof artefact:** `post(d) ok slot_schema_v2_admitted` plus `RESULT=OK` in `~/.local/share/breezy/run-reports-*/sup_restart_activation_*.txt`, emitted by the ops script after `supervisor_admits_slot_schema(store, 2)` returns True.
9. **Alert positive controls** through the live sink, one per kind. Re-run the sink control on **every** K>1 boot.
   - `EXEC_PAR_K_FORCED_TO_1`
   - `EXEC_PAR_BREAKER_TRIPPED`
   - `TRADE_SUPERVISOR_BREAKER_WATCHER_DEAD`
   - `TRADE_SUPERVISOR_BREAKER_RESOLVER_PASS_STALE`
   - `TRADE_SUPERVISOR_BREAKER_ENTRY_HALT_LATCHED`
   - `TRADE_SUPERVISOR_SLOT_TABLE_UNREADABLE_SLOT`
   - `EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE`, `EXEC_PAR_NO_FILL_RETIRE_REFUSAL`, `EXEC_PAR_UNREADABLE_SLOT`, `EXEC_PAR_STUCK_SLOT_ON_HELD_SLUG`
   - **the BG-8 stamp probe** (`TRADE_SUPERVISOR_EXEC_PAR_STAGE_STAMP_STALE`), shown firing with the node down;
   - the BG-8 halted-at-K=1 probe;
   - the BG-5 `stage_eval_fail` alert;
   - flag set.
10. **Failure injection** (gate tests, plus one dry boot on a backup copy of the store with orders disabled). Each case must actually latch `halted` with the expected reason, and must leave the flag **unset**:
    - an evaluator exception (FAIL);
    - an evaluator timeout;
    - a stale stamp.
    
    One injected stop-rule trip must set the flag.
11. **Rollback drill and tabletop.** The rollback drill is green. A tabletop on a backup store copy covers:
    - `--list`;
    - the **flag→reset order**: `--reset-entry-halt` refused while the flag is set at K>1, then `--clear-force-k1`, then `--reset-entry-halt` accepted.
12. **Evaluator and cross-check.**
    - BG-5 wrote its stamp on a dry boot.
    - BG-7's **first scheduled** read-only run succeeded and its report agrees with the in-node verdict.
13. The K-epoch row (BG-2) is written on a dry boot.
14. **Clean pre-boot state:**
    - no OPEN or AMBIGUOUS intent;
    - `halted: null`;
    - flag clear;
    - no unreadable slot;
    - permit unexpired.
15. **Commit K=2.** Its gate run shows the BG-9 config test **PASSED, not SKIPPED**. Restart the supervisor in the 01:00–16:40Z window, then respawn the node.
16. **Post-boot checks:**
    - no `EXEC_PAR_K_FORCED_TO_1`;
    - the heartbeat appears within 60 s;
    - the permit line is in the node log;
    - the epoch row shows effective_k=2;
    - the BG-5 boot-pass stamp is present.
    
    Any failure → halt, then demote.

## 15. P&L safety stops (PROPOSED)

These are safety stops, not an edge test. Thirty entries cannot validate an edge, so promotion proves execution parity only.

- Values are in daily-budget units, **net of fees**, and are checked only through `LedgerPredicatePort`.
- An AMBIGUOUS entry counts as a **full-cost loss until it is resolved**.

| Rule | Action | Enforcer |
|---|---|---|
| Single climate-day net P&L ≤ −0.15 | Halt, flag | BG-5 |
| Stage cumulative ≤ −0.40 | Halt, flag, demotion verdict | BG-5 |
| Cumulative since the first K>1 boot ≤ −1.0 | Halt, flag, K=1 | BG-5 |

- **Settlement-lagged.** Entry losses realize at settlement, so these stops are not truly intraday. BG-5 evaluates them as settlements ingest, while AMBIGUOUS entries count at once.
- **The intraday exposure guard** is the §9 station-day open-cost 0.25 halt.
- **Arithmetic** (cap/budget 0.05, p ≈ 0.9):
  - At most about 7 entries/day × 0.05 = 0.35 deployed per day.
  - One loss ≈ −0.05.
  - One win ≈ +0.05 × (1−0.9)/0.9 ≈ +0.0056.
  - Day stop: about 3 cap-sized losses. With 4 wins on the same day (+0.022) it needs a 4th loss.
  - Stage stop: about 8 net losses.
  - Cumulative stop: about 20 net losses, or one full daily budget.

---

## Consolidated BUILD-GAP table (r3 IDs)

| ID | File | Purpose | Depends on | Gates |
|---|---|---|---|---|
| BG-1 | `runtime/exec_par_telemetry.py`, `runtime/breaker_watcher.py` (`ExecParStorePort`, `LedgerPredicatePort`), `runtime/submit_intent.py` (single-writer methods), `adapters/polymarket_us/operator_controls.py` (predicates) | Durable per-climate-day counters (§10a); missing counts as trip; the two new ports | — | S1 |
| BG-2 | `app/trade.py` (boot row), `runtime/breaker_watcher.py` (forced/stop rows), `scripts/analysis/score_live_trials.py`, `family_tally_v2.py` | K-epoch ledger and stratification | BG-1 | S1 |
| BG-3 | `runtime/node_config.py` (`force_k1_on_durable_flag`), `app/trade.py:~1078`, latch flag writer | Durable force-K1 flag: boot check and stop-rule-only set | BG-1 | S1 |
| BG-4 | `runtime/clear_submit_intent_cli.py` | `--clear-force-k1 --incident-report`; `--reset-entry-halt` requires an existing incident report and refuses while the flag is set at configured K>1 | BG-3 | S1 |
| BG-5 | new `runtime/exec_par_stage_eval.py` (pure), `runtime/breaker_watcher.py` (sub-task) | In-node evaluator: boot, climate-day close and settlement passes; executor-run and bounded; fails closed; writes halt, flag and stamp through the latch; §5 promotion, §6, §7, §9 daily, §15 | BG-1, BG-2, BG-3 | S1 |
| BG-6 | `runtime/breaker_watcher.py:_persist` | Intraday trips: §5 Clopper-Pearson and burst, §9 station-day 0.25, stale stamp | BG-1, BG-3, BG-5 | S1 |
| BG-7 | `scripts/analysis/exec_par_stage_gate.py` + timer | READ-ONLY cross-check and promotion report; `k_epochs.jsonl` export; never writes `BREAKER_KEY` | BG-5, BG-2 | S1 |
| BG-8 | `runtime/trade_supervisor.py:~3155` | Probes `halted` and unreadable slots at any K; stamp probe at K>1 | BG-5 | S1 |
| BG-9 | `tests/unit/test_exec_par_wp5b_config.py` | Skips at K=1. At K>1, fails on a missing or mismatched frozen doc or `.sha256`, or a label mismatch. Also asserts the single-family boot invariant. | §13 freeze | S1 |
| BG-10 | `adapters/polymarket_us/operator_controls.py`, `docs/evidence/m1v3/exec_parallel_dhat.py` | dhat tooling: (a) label-only reader plus a test that only a label is printed; (b) hold-input mode; (c) halt-level derivation plus §5 operating characteristics; (d) ≥20k resamples and controls for both `BOOT_SEED` and the draw seed; (e) ρ=0.1 overdispersion arm | (b) needs BG-2 | (a)(c)(d)(e): S1; (b): S1→S2 |
| BG-11 | `strategy/current_rung_hold/continuous_strategy.py`, `continuous_no_side.py` | Per-reason pre-filter WAIT counters | BG-1 | S2→S3 |

**Mapping from r2 IDs:**

| r2 ID | r3 ID |
|---|---|
| BG-1 | Withdrawn |
| BG-2 | BG-5 (logic, in-node) + BG-7 (read-only script); offline writes removed |
| BG-3 | BG-11 |
| BG-4 | BG-10(a) |
| BG-5 | BG-9 |
| BG-6 | BG-10(b) |
| BG-7 | BG-9 |
| BG-8 | BG-3 (flag) + BG-4 (CLI) |
| BG-9 | BG-1 |
| BG-10 | BG-10(c) |
| BG-11 | BG-4 |
| BG-12 | BG-8 |
| BG-13 | BG-2 |
| BG-14 | BG-6 (day P&L moved to BG-5) |
