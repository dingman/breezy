# D-PREREG: Execution-design pre-registration for EXEC-PAR activation at K>1

**r2 (2026-10-10), supersedes r1 259e825f**

- **Status:** DRAFT, not frozen. §13 gives the freeze procedure.
- **Governs:** every node boot where the configured K (`runtime/exec_par_constants.py:EXEC_PAR_MAX_CONCURRENT_INTENTS`) is greater than 1.
- **Source plans:** `EXEC-PAR-parallel-intents_plan_r5.md` §3.6, §3.9, §6, §7, §8, plus `..._r5_1_delta.md` E1–E14.
- **Code basis:** HEAD `259e825f`. Where this document and the code disagree, the code value is cited and wins.
- **Labels:** PROPOSED marks a threshold the plan left open. BUILD-GAP (BG-n) marks enforcement code that does not exist yet.

**Honest prior.** M1-v3's own prior disclosure puts P(WINNER) near zero, so this ramp may never execute. The build is still justified because a working K>1 path is a precondition of T1 (§14.4).

## Changes from r1

| Change | Ruling |
|---|---|
| New §1a. Every stop ends in an automatic entries-only halt; a demotion commit is only cleanup. Rules are classified in a table. | R1 |
| BG-8: a durable force-K1 flag, checked at boot | R2 |
| BG-2 dead-man stamp; BG-2 fails closed on bad input; its first scheduled run must be proven | R3 |
| BG-9: per-climate-day counters persisted to the store; BG-2 reads the store, not logs | R4 |
| BG-1 withdrawn and replaced by the automatic K-epoch ledger (BG-13) | R5 |
| §5 thresholds rewritten; Clopper-Pearson promotion bound; days are the effective n; BG-10 | R6 |
| §1 promotion is evaluated once; one 5-day extension; 15-day stage cap; windows reset at every K change; §3 always at K=6 | R7 |
| §6 stop: pooled trailing-5-day share, two consecutive daily evaluations | R8 |
| §7: exact per-fill fee rule, ±1 cent per 10 fills, K=1 pre-boot parity | R9 |
| New §15: P&L safety stops | R10 |
| §9: absolute station-day stop plus an intraday halt; 5 s rule only on days with ≥6 orders; BG-7 becomes a test | R11 |
| §4: reset only at the 16:50Z respawn; BG-11; BG-12 | R12 |
| §14 items 1, 8 and 9 expanded; new decision record; artefact hashes | R13 |
| §10: notes on how independent the parallel fills are from M1-v3 | R14 |
| §3: WP0 margin stated; three-seed re-run | R15 |
| BG-5 reads the frozen doc and checks its hash; anchors fixed; §8 rule at the 15-day cap | R16 |

## 0. Binding invariants

- Nautilus Trader is immutable.
- `allow_short` stays `False`.
- The two operator caps (max daily budget, max per position) are read only. This document never states or assigns them. Every threshold is a fraction of the daily budget, checked by value-free ledger predicates.
- Nothing in this document changes the halt drop-in or `BREEZY_ORDERS_ENABLED`. K>1 changes concurrency only. It is never a decision to enable orders.
- This document is independent of `docs/evidence/m1v3/PREREG.json` and never edits it. It uses no data from climate days 2026-10-07..11-28 and none from the F13 sealed holdout.

## 1. K schedule

| Stage | K | Entry condition | Minimum to promote |
|---|---|---|---|
| S0 | 1 | Today | Every item in the §14 checklist passes |
| S1 | 2 | §14 complete | ≥5 climate days with ≥1 K>1 entry fill, ≥30 posted entry orders, and every §5–§9 and §15 check green over the stage |
| S2 | 4 | S1 promoted, plus the §8 gate passed | The same minimums as S1 |
| S3 | 6 | S2 promoted, plus the §3 re-run passing | Terminal stage. K≥7 needs an amendment. |

- **Ceiling (PROPOSED).** K=6 is the smallest K that passed the gate arm at the 0.05 bucket on main4+nyc (WP0 Headline). The no-id variant needed K=7 and is not authorised.
- **Looks (R7).**
  - Promotion is evaluated **once**, on the first climate day both minimums are met.
  - If that evaluation fails, the stage holds for exactly one 5-day extension and is evaluated once more. A second fail demotes one stage.
  - A stage lasts at most **15 climate days**, and the extension ends at that cap.
  - A stage that reaches the cap with its minimums unmet holds at its current K. It is never promoted without an amendment.
  - Every rolling window (§5, §6, §9, §15) resets at every K change.
- **Mechanics.** Each K change is one commit that edits only `EXEC_PAR_MAX_CONCURRENT_INTENTS` and cites the frozen SHA and the stage. Then:
  1. Run `scripts/ci/run_tests_no_egress.sh` and read EXIT=0.
  2. Restart the supervisor, because it reads K.
  3. Respawn the node.
- **Code-enforced forced-to-1 conditions** (effective K, logged at ERROR, alert `EXEC_PAR_K_FORCED_TO_1`):
  1. **Supervisor marker.** The supervisor decode marker does not admit slot schema v2: `node_config.force_k1_without_supervisor_marker` (`node_config.py:756`), called at `app/trade.py:1078`. A raising read counts as not admitted.
  2. **Bucket guard.** `exec/client.py:_apply_slot_boot_guards` (~2534-2563) runs once per `_connect` (`:2283`) after the latch reconciles. It calls `_bucket_force_reason` (`:2565`), which forces K=1 when:
     - the frozen label is not configured;
     - there is no ledger;
     - `cost_budget_bucket()` raises; or
     - the live label ranks above the frozen label.
  3. **Durable force-K1 flag (BG-8).** See §1b.
  4. **Restart over a v2 table.** A restart with K forced to 1 over a v2 table still resolves every open slot (r5.1 E7).
- **After any stop:** the ramp restarts at S1, and only after an incident report is written in `docs/incident-reports/`.
- **No post-hoc K.** No K outside {1, 2, 4, 6} is ever set.

## 1a. Real-time enforcement principle (R1)

- Every stop rule ends in an **automatic** entries-only halt, written through the existing breaker record (`submit_intent_slots.BREAKER_KEY`, the `halted` field; sticky; entries only).
- The same write sets the BG-8 flag.
- The halt is the stop. The demotion commit is deferred cleanup, never the stop mechanism.

| Rule | Class | Enforcer |
|---|---|---|
| Stuck slots, AMBIGUOUS notional, contradictions, duplicates (§4) | AUTOMATIC-intraday | `breaker_watcher` (existing) |
| AMBIGUOUS rate: n-based, per-day and 60-minute guards (§5) | AUTOMATIC-intraday | `breaker_watcher` trip reason (BG-14) |
| Single-day P&L stop, from realized fills (§15) | AUTOMATIC-intraday | BG-14 |
| Station-day open cost above 0.25 of the budget, current day (§9) | AUTOMATIC-intraday | BG-14 |
| BG-2 stamp stale or never written (§5) | AUTOMATIC-intraday | BG-14 |
| Dropped share (§6), fee/slippage (§7), station-day 2-of-5 and 5 s window (§9), settled P&L and stage/cumulative P&L (§15), promotion evaluations | AUTOMATIC-daily | BG-2 |
| Breaker reset (§4), §8 hold-time gate | PROCEDURAL | Coordinator |

- **BG-2 write timing.** BG-2 cannot write while the node holds the store lock (§4). Its write step therefore runs in the daily 16:50Z respawn gap: it reads the store, evaluates the last complete climate day, writes the halt, the BG-8 flag and its stamp, then allows the boot.
- Every US station's climate day has closed by 16:50Z.
- **BUILD-GAP BG-14:** new trip reasons in `runtime/breaker_watcher.py:BreakerWatcherActor._persist`:
  - Inputs are BG-9 counters, the actor's native `portfolio` realized P&L, and value-free `DailySpendLedger` fraction predicates (for example, "is this fraction of the daily budget exceeded"). No value leaves the ledger.
  - It does not edit the byte-pinned client.

## 1b. Durable force-K1 flag (R2, BUILD-GAP BG-8)

- **Store key:** a flag in the exec-state store, `exec/polymarket_us/exec_par/force_k1`, holding `{reason, ts_ns, set_by}`.
- **Set** automatically by every halt in §1a (watcher or BG-2) and by every demotion.
- **Cleared** only by `clear_submit_intent_cli --clear-force-k1 --incident-report <existing path>`.
- **Checked at boot** by a new `node_config.force_k1_on_durable_flag(latch, store)`, called next to `force_k1_without_supervisor_marker` at `app/trade.py:1078`. When the flag is set, it calls `latch.force_k1(reason)`.
- An unreadable flag counts as set.
- This is the smallest seam: it is not a byte-pinned file, and the bucket guard (`_bucket_force_reason`) is unchanged.

## 2. Exposure fractions

All values are fractions of the operator's **daily budget**, never dollars.

| Constant | Value | Anchor |
|---|---|---|
| `f_adm` | 0.50 | `node_config.OPEN_EXPOSURE_BOUND_FRACTION`, enforced by `DailySpendLedger._require_exposure_headroom_locked` and `exposure_admission_refusal`. It raises `OpenExposureBoundExceeded` and is not a day-stop. |
| `f_breaker` | 0.25 | `node_config.BREAKER_OPEN_AMBIGUOUS_FRACTION`, through `DailySpendLedger.breaker_fraction_exceeded`. Any raise, or any AMBIGUOUS entry of unknown size, counts as tripped. |

At cost = cap and bucket 0.05:
- One order is at most 0.05 of the budget.
- AMBIGUOUS exposure at K=6 is at most 0.30, below `f_adm`.
- The breaker trips once more than 5 cap-sized orders are AMBIGUOUS.
- Exits never enter the registry (E4).

## 3. Frozen cost/budget bucket and the activation re-run

- **Frozen label: `0.05`.** The unit is cap / daily budget (E6).
  - Anchor: `node_config.EXEC_PAR_FROZEN_BUCKET = "0.05"` (`:748`), passed to the client as `frozen_cost_budget_bucket` (`:1105`).
  - Ladder: `operator_controls._COST_BUDGET_BUCKETS` = {`≤0.02`, `0.05`, `0.10`, `0.25`, `0.50`}, with the sentinel `>0.50`.
- **Why 0.05.** WP0 passed it at K=6.
  - main4: CI upper bound 0.2755.
  - main4+nyc: CI upper bound **0.2905**. That is a **margin of 0.0095** against 0.30, on a **single bootstrap seed**.
- **The sim is slightly conservative.** The simulated cost/budget ratio is about 0.0505, against a live label of 0.05.
- **0.10 is not frozen.** It passes only on main4 at K=7, driven by free-balance arm B, and fails on main4+nyc at 0.420.
- **Procedure:**
  1. The operator sets the caps. This document assigns no value.
  2. The coordinator derives the label only through `cost_budget_bucket()` (via BG-4) and records only the label.
  3. Re-run `exec_parallel_dhat.py` on pre-2026-10-07 inputs at cost = cap, using the row of the **actual** label. Use the gate arm:
     - p_amb 0.33 (the BG-10 value once derived);
     - one stuck slot;
     - the 5/s throttle (`TRADE_RISK_MAX_ORDER_SUBMIT_RATE = "5/00:00:01"`);
     - `f_adm`;
     - the worse free-balance arm.
     - Use **≥3 bootstrap seeds** and report the Monte Carlo spread.
  4. **Stop rule.** The day-clustered bootstrap CI upper bound of the day-level p90 d̂ must be ≤ 0.30 at **K=6** (the terminal stage), at the actual label, **for every seed**. If any seed fails, K stays 1.
  5. Store the result JSON under `docs/evidence/exec_par/` and record its sha256 (§14.6).
  6. A label of `≤0.02` is admissible: it ranks below the frozen label, and main4+nyc passes it at K=6.
- **BUILD-GAP BG-4.** Add a module-level, label-only reader in `operator_controls.py` with no new importer of `operator_controls`. Add a test that dhat prints only a ladder label.
- **BUILD-GAP BG-5.** Extend `tests/unit/test_exec_par_wp5b_config.py`:
  - read the §3 label from the **frozen** doc;
  - assert `EXEC_PAR_FROZEN_BUCKET` equals it;
  - assert the `EXEC-PAR-D-PREREG.sha256` sibling matches the doc's bytes.
  - Either mismatch fails, which blocks K>1. This makes the freeze code-enforced.

## 4. Breaker: triggers, reset and rollback drill

**Trip triggers.** `BreakerWatcherActor._persist` runs every 5 s and is registered only at K>1 (`build_exec_watcher`). It trips on:
- ≥2 open intents older than `STUCK_AGE_NS` = 900 s. The code uses 900 s for both the with-id and no-id shapes; the code wins, which gives a later trip, never a false one.
- AMBIGUOUS notional above `f_breaker`.
- Any increase in `contradiction_events_total` (E14.5).
- Any increase in `duplicate_suspect_total`.
- The BG-14 reasons (§1a).

**Duplicate detector.** It only backs up the stuck-slot check. It runs after the `L_feed` = 300 s lag guard and needs confirmation on a second consecutive pass. A duplicate on an order that resolves normally is caught only by the 120 s cool-off and position reconciliation.

**Halt.** Entries only, sticky, in `BREAKER_KEY`. Exits and the resolver are never blocked. The halt is the real-time stop; the demotion commit is deferred cleanup.

**Entry denials** (`SubmitIntentLatch._breaker_denial`):
- the record is absent more than 60 s after boot;
- the record is garbled;
- the halt is set;
- the heartbeat is older than 60 s;
- the resolver pass is older than 600 s;
- a stamp is more than 5 s in the future.

**Supervisor alerts** (`breaker_supervisor_watch.decide_breaker_alerts`): watcher dead, resolver stale, halt latched, unreadable slot. They repeat hourly.
- **BUILD-GAP BG-12.** `trade_supervisor.py:3155` returns before probing when K≤1. Change this so the supervisor probes `halted` and unreadable slots read-only every 10 min at any K. A halt left over at K=1 then raises an alert.

**Reset.** Done by the coordinator under the standing pre-authorisation. The operator gets the alert and is not asked.
- **Timing.** Only at the **16:50Z daily respawn**, never mid-day.
- **Pre-check.** No held-position exit is due within 30 min.
- **Steps:**
  1. **Gather evidence.**
     - The trip reason and held list from `EXEC_PAR_BREAKER_TRIPPED`.
     - A venue positions GET that reconciles every held slug, with the NO-as-short-YES sign applied.
     - `clear_submit_intent_cli --list`.
     - Every stuck slot resolved, or cleared with `--intent-id --resolution --evidence`.
     - For a contradiction or duplicate trip: venue order history.
     - An incident report.
  2. **Take the node down** (hand-relaunch mechanics). The CLI refuses while the node holds the lock. Recorded cost: no resolver or exits while it is down. Target ≤10 min (PROPOSED).
  3. **Reset:** `breezy.runtime.clear_submit_intent_cli --reset-entry-halt --ack-held-positions-reviewed --incident-report <path>`, run with the exact venv interpreter. This calls `SubmitIntentLatch.reset_breaker_halt`.
     - **BUILD-GAP BG-11.** The CLI refuses without `--incident-report` pointing to an existing file. It also refuses while the BG-8 flag is set and the configured K is above 1.
  4. **Demote** (cleanup commit). Relaunch.

**Rollback drill** (before the first K>1 boot and after any code rollback; green at the activation SHA):
- `test_rollback_drill_after_drain_and_reset_old_reader_sees_valid_v1_retired` (WP5a; `test_exec_par_wp5a_decode.py:298`).
- `test_drain_then_reset_then_rollback_drill` (**WP7, pending: not in `tests/` at HEAD**).
- `test_restart_with_k_forced_1_over_open_v2_table_resolves_all_slots_and_downgrades` (`test_submit_intent_slots.py:620`, `test_exec_par_wp4_boot.py:467`).

**Rollback order:**
1. Review held positions.
2. Reset the breaker.
3. Drain to at most one open slot (the table rewrites as v1).
4. Set K=1.
5. Verify `halted: null` before reverting any code.

## 5. AMBIGUOUS-rate halt (PROPOSED)

- **Metric.** AMBIGUOUS entries over posted entries, counting only entries made in a K>1 epoch (BG-13). Counts come from BG-9.
- **Halt** (AUTOMATIC-intraday, BG-14) when any of these holds:
  - n ≥ 20 and the rate is ≥ 7/20;
  - n ≥ 30 and the count is ≥ 11/30 over the rolling window;
  - ≥4 AMBIGUOUS on one climate day;
  - ≥3 AMBIGUOUS within 60 minutes.
- **Below n=20, only the per-day and 60-minute guards apply.**
- **Clustering.** AMBIGUOUS outcomes are day-clustered, so the effective n is the number of days, not orders. WP0 drew p_amb independently per order, which favours a pass.
- **Promotion** requires:
  - the stage Clopper-Pearson 90% upper bound ≤ 0.45; and
  - no halt fired during the stage.
- **Level.** 0.33 is the Wilson upper bound of the WP0 hold inputs (7/39, 0.3267). It is only a **proxy**.
  - **BUILD-GAP BG-10:** derive the halt level from the dhat grid as the p_amb at which the K=6, stuck=1 p90 CI upper bound reaches 0.30. Record the result before the freeze.
- **BUILD-GAP BG-2.** `scripts/analysis/exec_par_stage_gate.py` evaluates §5–§9 and §15 from the store (BG-9, BG-13) only, never from log lines.
  - It runs daily in the 16:50Z respawn gap (§1a), alerts through the `alerts.env` sink, writes the halt and the BG-8 flag on a stop, and writes a **last-success stamp**.
  - **Fails closed.** Any missing, gappy or non-monotonic input makes it FAIL; it never passes with a value of 0. This includes a missing `fee_coefficient_at_fill` and a missing decision ask.
  - **Dead-man.** BG-14 halts when the stamp is older than 26 h, or was never written after the first K>1 day. The supervisor alerts on a stale stamp.

## 6. Live dropped-candidate-share stop (PROPOSED)

- **Metric:** denied candidates over all candidates. Denials counted:
  - `OpenExposureBoundExceeded`;
  - K-full;
  - cool-off (`DEFAULT_COOLOFF_NS` = 120 s);
  - throttle;
  - free balance;
  - **BG-3 pre-filter WAITs**.
  - Breaker and stale denials are reported separately and excluded.
- **Stop at S3** (AUTOMATIC-daily). The pooled trailing-5-day share is above 0.30 on two consecutive daily evaluations. The K>1 programme is then suspended until an amendment re-runs WP0 with live hold data.
- **S1/S2:** reported only. A lower K is expected to drop more.
- A missing counter means FAIL.
- The day-level p90 appears only in the stage report (≥15 days).
- **BUILD-GAP BG-3.** `continuous_strategy._admission_refusal` → `TrialDayLatch.admission_would_refuse` returns a WAIT without an `OrderDenied`, so `ExecParDigest.record_denial` never sees it. Add per-reason pre-filter counters in `strategy/current_rung_hold/continuous_strategy.py` and `continuous_no_side.py`, persisted through BG-9.

## 7. Slippage and fee parity (PROPOSED)

- **Fee, per K>1 fill** (AUTOMATIC-daily; any violation halts):
  - `fee_coefficient_at_fill` (stamped by `exec/client.py:record_fill`) equals θ = 0.0695 (`PREREG.json` `theta`) exactly.
  - Realized cents equal `round(θ·C·p(1−p))` using the code's banker's rounding. `fees.polymarket_us_fee` quantises at currency precision with `ROUND_HALF_EVEN` (`fees.py:597-605`).
  - The stage sum is within ±1 cent per 10 fills.
  - `fees.py` documents per-fill rounding as an approximation of the venue's cumulative fee, so a mismatch reveals a gap in the fee model. That is a correct halt, not a false one.
  - A `fee_reconciled=False` share above 10% blocks promotion.
- **Slippage, per fill** (`fill_px − decision ask`). Promotion requires:
  - a stage mean ≤ 0.01 (the M1-v3 `slippage`); and
  - ≤10% of fills above 0.02.
- **Parity** is measured against the **K=1 pre-boot fill ledger** of the same family: mean parallel minus serial ≤ 0.005 when there are ≥20 K=1 fills, otherwise report-only. No concurrent serial fills are assumed.
- **Note.** Together these tolerances allow about 1.5 c of slack, which is large against an edge of about +2 c.

## 8. NO≥0.90 hold-time ramp gate (S1→S2)

WP0's hold inputs contain no NO≥0.90 order, and every AMBIGUOUS order was YES. The hold mixture is assumed, not measured.

- **Gate (PROCEDURAL).**
  - Collect ≥20 posted NO≥0.90 entries at S1.
  - Measure arm→retire hold times and the AMBIGUOUS share.
  - Re-run §3 with the empirical holds and p_amb = max(BG-10 level, measured Wilson upper bound).
  - It must pass at K=6 at the actual label.
- **15-day cap.** If 20 such orders are not reached within the 15-day S1 cap, hold K=2. There is no promotion to S2.
- **BUILD-GAP BG-6.** Add a hold-input-only mode to `exec_parallel_dhat.py`. It reads live K>1 hold times dated on or after 2026-11-29; candidates still come only from the pre-window set.

## 9. Concentration

| Scope | Limit | Enforcement |
|---|---|---|
| Per slug | 1 open slot (YES/NO share it) plus a 120 s cool-off | `domain/exec_slots.admit`; `DEFAULT_COOLOFF_NS` |
| Per order | Per-position cap | `DailySpendLedger.authorize_order_cost` |
| Station-day, intraday | Open cost above 0.25 of the daily budget → halt | BG-14 (value-free ledger predicate) |
| Station-day, stop (PROPOSED) | Open cost above 0.25 of the daily budget on 2 of the last 5 days → halt, demote one stage | BG-2 over BG-9. No cap: the 2026-09-14 ruling stands. |
| 5 s window (PROPOSED) | On days with ≥6 orders, more than 0.50 of the day's entry notional inside one `WINDOW_NS` = 5 s window on 2 of the last 5 days → halt, demote one stage | BG-2 over BG-9 |
| Per family | Exactly one entry family | Verified: `app/trade.py:1047` loads only `settings.sending_family_id`, and `:1066-1070` raises `SettingsError` when `manifest.family_id` differs. **BG-7** = a test that asserts this single-family boot invariant. |

## 10. Parallel fills never feed the M1-v3 verdict

**What M1-v3 reads (verified).** The statistic is market-only: `scripts/analysis/no_longshot_pooled_test.py` reads only the recorder Depth10 tape (`RecorderCatalogTape`, first row in [12:00, 13:00) UTC) and the CLI finals. It reads no exec store and no fills.

**Ways K>1 could leak into it:**
- **Depth consumption.** At about 1 contract per order the effect is negligible. If it were not, K=1 live orders would contaminate the tape too.
- **The shared WS subscription cap** (10 per connection).
- **Node or recorder restarts** that leave gaps in the tape.

**Rules:**
1. No K>1 boot before 2026-11-29T00:00Z (`last_forward_day_rule` → 11-28). §14.4 already blocks K>1 until the M1-v3 read (on or after 12-07). The 11-29 rule matters only for another family. Both rules are kept.
2. One look only. No K>1 statistic ever enters the M1-v3 report.
3. No recorder-gap day may be attributable to a K change.
4. Every K>1 fill is reported in a separate stratum.

- **BG-1 is WITHDRAWN.** The byte-pinned client is not edited.
- **BUILD-GAP BG-13 (K-epoch ledger).**
  - At boot, `app/trade.py` appends `{commit_sha, effective_k, force_reason, boot_ts}` under the store prefix `exec/polymarket_us/exec_par/epoch/<boot_ts_ns>`, before `node.run`. Any order is therefore preceded by its row.
  - The watcher appends an amendment row when the bucket guard forces K=1 at `_connect`.
  - `stop_ts` is written at disposal or halt. A crash is closed by the next `boot_ts`.
  - Fills are attributed by `ts_event`. A configured K>1 epoch with no forced row counts as parallel, so tagging errs towards too many.
  - BG-2 exports the rows to `docs/evidence/exec_par/k_epochs.jsonl`.
  - `score_live_trials.py` and `family_tally_v2.py` stratify on the epoch.

## 10a. Durable telemetry (BUILD-GAP BG-9)

`ExecParDigest` is in memory, resets at every respawn, keys by UTC day, and overflows at `MAX_REASONS` = 32.

BG-9 persists **per-climate-day** counters to the exec-state store:
- posted entries;
- AMBIGUOUS;
- denials by reason;
- BG-3 WAITs;
- open cost per station-day (as a value-free fraction flag);
- 5 s window peaks.

The watcher writes them on its tick.

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

## 12. Permit-notional non-debit for boot fills (E14.6)

- A fill on an intent registered at boot (H6) does not debit the permit's session notional.
- **Accepted, because:**
  - the ledger counts it exactly once;
  - the undercount is at most `f_adm` = 0.50 of the budget per carry-over set;
  - it does not add up across respawns.
- **Anchors:** `test_boot_permit_untouched_by_open_intent_registration`, `test_boot_zero_fill_retire_no_permit_restore_d3`.

## 13. Freeze and amendment

**Freeze:**
1. Commit this document alone as `EXEC-PAR-D-PREREG.md`, with `Status: FROZEN`, §11 re-verified and the BG-10 result recorded. That commit's SHA is the frozen SHA.
2. A second commit adds `EXEC-PAR-D-PREREG.sha256`. BG-5 checks it against the doc.
3. **Deadline:** before the first K>1 boot, and no later than 2026-12-06T23:59Z.
4. Push only after the full gate reads EXIT=0.

**Amendment:**
- The frozen file is never edited. A change is a new doc, `EXEC-PAR-D-PREREG-A<n>.md`, peer-reviewed and frozen the same way. It applies only forward.
- **Tightening** can be applied immediately.
- **Loosening** needs a frozen amendment whose justification uses no data from the stage whose stop it loosens.

## 14. Activation checklist (all items, in order)

1. WP-DR..WP7 are merged (**WP7 pending**, along with its §4 drill test), and so are BG-2..BG-14 (BG-1 is withdrawn). The full gate reads EXIT=0 at the activation SHA, and `lint-imports` reports "N kept, 0 broken".
2. This document is frozen (§13); §11 and the BG-5 hash are re-verified.
3. The date is on or after 2026-11-29. **Decision recorded:** no K>1 boot happens before then. That is a delay of at least 7 weeks, accepted.
4. An eligible frozen-prereg WINNER exists (M1-v3 read on or after 12-07, or another), and exactly one entry family is enabled.
5. The operator caps are set. The label is ≤ `0.05`, and only the label is recorded.
6. The §3 stop rule passes at K=6 on ≥3 seeds. The result artefact and its sha256 are stored.
7. The BG-5 test passes.
8. The supervisor is restarted on WP5a or later. **Proof artefact:** the line `post(d) ok slot_schema_v2_admitted` plus `RESULT=OK` in the restart report (`~/.local/share/breezy/run-reports-*/sup_restart_activation_*.txt`). The ops script (`~/.local/share/breezy/ops/sup_restart_activation_1011.sh`, outside the repo) emits it after `supervisor_admits_slot_schema(store, 2)` returns True. Coordinator correction to r2 draft: the string exists in the ops script, so no build item is needed.
9. **Alert positive controls** through the live sink, one per kind:
   - `EXEC_PAR_K_FORCED_TO_1`
   - `EXEC_PAR_BREAKER_TRIPPED`
   - `TRADE_SUPERVISOR_BREAKER_WATCHER_DEAD`
   - `TRADE_SUPERVISOR_BREAKER_RESOLVER_PASS_STALE`
   - `TRADE_SUPERVISOR_BREAKER_ENTRY_HALT_LATCHED`
   - `TRADE_SUPERVISOR_SLOT_TABLE_UNREADABLE_SLOT`
   - the `ExecRefusalAlertActor` counters: `EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE`, `EXEC_PAR_NO_FILL_RETIRE_REFUSAL`, `EXEC_PAR_UNREADABLE_SLOT`, `EXEC_PAR_STUCK_SLOT_ON_HELD_SLUG`
   - BG-2 stale and BG-2 fail
   - BG-8 flag set.
   - The sink positive control is re-run on **every** K>1 boot.
10. The rollback drill is green. A tabletop of the CLI `--list`, `--reset-entry-halt` (BG-11) and `--clear-force-k1` has been run on a backup copy of the store.
11. BG-2's **first scheduled** run succeeded (not a manual run), and its stamp is present.
12. The K-epoch row (BG-13) is written on a dry boot.
13. Clean pre-boot state:
    - no OPEN or AMBIGUOUS intent;
    - `halted: null`;
    - BG-8 flag clear;
    - no unreadable slot;
    - permit unexpired.
14. Commit K=2. Restart the supervisor in the 01:00–16:40Z window, then respawn the node.
15. **Post-boot checks:**
    - no `EXEC_PAR_K_FORCED_TO_1`;
    - the heartbeat appears within 60 s;
    - the permit line is in the node log;
    - the epoch row shows effective_k=2.
    - Any failure → halt, then demote.

## 15. P&L safety stops (R10)

These are safety stops, not an edge test. Thirty entries cannot validate an edge, so promotion proves execution parity only.

All values are in daily-budget units, never dollars, and are evaluated by value-free ledger predicates.

| Rule | Action | Class |
|---|---|---|
| Single climate-day net P&L ≤ −0.5 | Halt | Intraday from realized fills (BG-14); otherwise BG-2 |
| Stage cumulative ≤ −1.0 | Halt, demote one stage | BG-2 |
| Cumulative since the first K>1 boot ≤ −2.0 | Halt, K=1, BG-8 flag | BG-2 |

---

## Consolidated BUILD-GAP table

| ID | File | Purpose | Depends on |
|---|---|---|---|
| BG-1 | — | WITHDRAWN; replaced by BG-13 | — |
| BG-2 | `scripts/analysis/exec_par_stage_gate.py` + timer in the 16:50Z respawn gap | Daily §5–§9/§15 evaluator; writes halt, BG-8 flag and dead-man stamp; fails closed | BG-9, BG-13, BG-8 |
| BG-3 | `strategy/current_rung_hold/continuous_strategy.py`, `continuous_no_side.py` | Per-reason pre-filter WAIT counters | BG-9 |
| BG-4 | `adapters/polymarket_us/operator_controls.py` | Module-level label-only bucket reader for dhat; test that dhat prints only a label | — |
| BG-5 | `tests/unit/test_exec_par_wp5b_config.py` | Constant == frozen-doc §3 label; `.sha256` == doc bytes | §13 freeze |
| BG-6 | `docs/evidence/m1v3/exec_parallel_dhat.py` | Hold-input-only mode for live K>1 holds | BG-13 |
| BG-7 | `tests/unit/` (new test on `app/trade.py:1047-1070`) | Assert the single-family boot invariant | — |
| BG-8 | `runtime/node_config.py` (`force_k1_on_durable_flag`), `app/trade.py:~1078`, `runtime/clear_submit_intent_cli.py` (`--clear-force-k1`) | Durable force-K1 flag: auto-set, human-cleared with an incident report | — |
| BG-9 | `runtime/exec_par_telemetry.py`, `runtime/breaker_watcher.py` | Per-climate-day counters persisted to the exec store | — |
| BG-10 | `exec_parallel_dhat.py` grid run; result recorded in §5 before freeze | Derive the AMBIGUOUS halt level | BG-4 |
| BG-11 | `runtime/clear_submit_intent_cli.py` | `--reset-entry-halt` requires `--incident-report <existing file>`; refuses while BG-8 is set and configured K>1 | BG-8 |
| BG-12 | `runtime/trade_supervisor.py:~3155` | Read-only `halted`/unreadable probe every 10 min at any K | — |
| BG-13 | `app/trade.py` (boot row), `runtime/breaker_watcher.py` (forced/stop rows), `score_live_trials.py`, `family_tally_v2.py` | K-epoch ledger and stratification | — |
| BG-14 | `runtime/breaker_watcher.py:_persist`, plus value-free `DailySpendLedger` fraction predicates | Intraday trip reasons: AMBIGUOUS rate/day/60-min, day P&L, station-day 0.25, BG-2 stamp stale | BG-9, BG-2 (stamp), BG-8 |
