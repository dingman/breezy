# D-PREREG: Execution-design pre-registration for EXEC-PAR activation at K>1

- **Status:** DRAFT. It is not frozen. §13 gives the freeze procedure.
- **Governs:** every node boot where the configured K (`runtime/exec_par_constants.py:EXEC_PAR_MAX_CONCURRENT_INTENTS`) is greater than 1.
- **Source plans:** `EXEC-PAR-parallel-intents_plan_r5.md` §3.6, §3.9, §6, §7, §8, plus `..._r5_1_delta.md` E1–E14.
- **Code basis:** HEAD `d3588ece`. Where this document and the code disagree, the code value is cited and wins.
- **Labels:** PROPOSED marks a threshold that the plan left open. BUILD-GAP marks enforcement code that does not exist yet.

## 0. Binding invariants

- Nautilus Trader is immutable.
- `allow_short` stays `False`.
- The two operator caps (max daily budget, max per position) are read only. This document never states or assigns them.
- The halt drop-in and `BREEZY_ORDERS_ENABLED` are never changed by anything in this document. K>1 changes concurrency only. It is never an order-enablement decision.
- This document is independent of `docs/evidence/m1v3/PREREG.json`. It does not edit that file. It uses no data from climate days 2026-10-07..11-28 and none from the F13 sealed holdout.

## 1. K schedule

| Stage | K | Entry condition | Minimum to promote |
|---|---|---|---|
| S0 | 1 | Today (`EXEC_PAR_MAX_CONCURRENT_INTENTS = 1`) | Every item in the §14 checklist passes |
| S1 | 2 | §14 complete | ≥5 climate days with ≥1 K>1 entry fill, ≥30 posted entry orders, and every §5–§9 check green over the stage |
| S2 | 4 | S1 promoted, plus the §8 hold-time gate passed | The same minimums as S1 |
| S3 | 6 | S2 promoted, plus the §3 re-run passing at K=6 | Terminal stage. K≥7 needs an amendment. |

- **Ceiling (PROPOSED):** K=6 is the smallest K that passed the gate arm at the 0.05 bucket in the production universe, main4+nyc (WP0 findings, Headline). The no-id variant needed K=7 on main4+nyc and is not authorised.
- **Mechanics:** each K change is one commit that edits only `EXEC_PAR_MAX_CONCURRENT_INTENTS`. The commit message cites this document's frozen SHA and the stage.
  - Run the full gate (`scripts/ci/run_tests_no_egress.sh`) and read EXIT=0.
  - Restart the supervisor, because it reads K from `exec_par_constants`. Then respawn the node.
- **Code-enforced forced-to-1 conditions.** These are effective K, logged at ERROR and alerted as `EXEC_PAR_K_FORCED_TO_1`:
  1. The supervisor decode marker does not admit slot schema v2 (`node_config.force_k1_without_supervisor_marker`, `EXEC_PAR_MARKER_ABSENT_REASON`). A raising marker read counts as not admitted.
  2. The bucket guard (`exec/client.py:_bucket_force_reason`, called from the `_connect` post-reconcile step, ~:2551-2563) forces K=1 when:
     - the frozen label is not configured;
     - there is no ledger;
     - `cost_budget_bucket()` raises; or
     - the live label's rank is above the frozen label's rank (`operator_controls.cost_budget_bucket_rank`).
  3. If the node restarts with K forced to 1 over a v2 table, it still resolves every open slot and denies entries until at most one slot is open (r5.1 E7).
- **Procedural demotion to K=1** (a commit that sets the constant back to 1, after the §4 drain). Any one of these triggers it:
  - any breaker trip (§4);
  - the AMBIGUOUS-rate halt (§5);
  - the dropped-share stop at S3 (§6);
  - a slippage or fee parity failure (§7);
  - a concentration stop (§9);
  - a fee-θ drift (§7).
  - After a demotion the ramp restarts at S1, and only after an incident report is written in `docs/incident-reports/`.
- **No post-hoc K.** No K outside {1, 2, 4, 6} is ever set under this document.

## 2. Exposure fractions

All values are fractions of the operator's **daily budget**. They are never dollar values.

| Constant | Value | Anchor |
|---|---|---|
| `f_adm` | 0.50 | `runtime/node_config.py:OPEN_EXPOSURE_BOUND_FRACTION`. The ledger enforces it in `DailySpendLedger._require_exposure_headroom_locked` / `exposure_admission_refusal` and raises `OpenExposureBoundExceeded` (not a day-stop). |
| `f_breaker` | 0.25 | `runtime/node_config.py:BREAKER_OPEN_AMBIGUOUS_FRACTION`, through `DailySpendLedger.breaker_fraction_exceeded`. Any raise or any unknown-sized AMBIGUOUS entry counts as tripped. |

**What these mean in cap/budget units** (at cost = cap, frozen bucket 0.05):
- A single order is at most 0.05 of the budget, so the per-order `f_adm` test never binds.
- AMBIGUOUS exposure at K=6 is at most 6 × 0.05 = 0.30 of the budget, which is below `f_adm`. This matches WP0, where `f_adm` did not bind at 0.05.
- The notional breaker trips once more than 5 cap-sized orders are AMBIGUOUS at the same time (> 0.25).
- Exits never enter the registry (r5.1 E4), so they count toward neither fraction.

## 3. Frozen cost/budget bucket and the activation re-run

- **Frozen label: `0.05`.** The unit is per-position cap / daily budget (r5.1 E6).
  - The code anchor is `runtime/node_config.py:EXEC_PAR_FROZEN_BUCKET = "0.05"`, which reaches the client through the config field `frozen_cost_budget_bucket`.
  - The ladder is `operator_controls._COST_BUDGET_BUCKETS` = {`≤0.02`, `0.05`, `0.10`, `0.25`, `0.50`}, with the sentinel `>0.50` above all of them.
- **Why 0.05:** WP0 passed the 0.05 bucket at K=6:
  - main4: CI upper bound 0.2755;
  - main4+nyc: CI upper bound 0.2905.
- **The 0.10 pass is not frozen.** It holds only on main4 at K=7, it is driven by free-balance arm B, and it fails on main4+nyc at 0.420.
- **Procedure:**
  1. The operator sets the caps. This document assigns no value.
  2. The coordinator derives the live label using only `DailySpendLedger.cost_budget_bucket()`. Only the label is printed or recorded.
  3. Re-run `docs/evidence/m1v3/exec_parallel_dhat.py` on the pre-2026-10-07 inputs, at cost = cap. Read the row of the **actual** live label, not the frozen one. Use the gate arm: p_amb 0.33 (Wilson upper), one stuck slot, the 5/s throttle (`node_config.TRADE_RISK_MAX_ORDER_SUBMIT_RATE = "5/00:00:01"`), `f_adm`, and the worse free-balance arm.
  4. **Stop rule:** the day-clustered bootstrap CI upper bound of the day-level p90 d̂ must be ≤ 0.30 at the target K. If it is not, K stays 1.
  5. A live label of `≤0.02` is admissible, because its rank is below the frozen label and main4+nyc passes `≤0.02` at K=6.
- **BUILD-GAP BG-4:** WP0 finding 7 says the dhat `--bucket-reader module:callable` flag has no value-free callable to point at. `cost_budget_bucket` is a ledger method.
  - Fix: add a module-level, label-only reader in `src/breezy/adapters/polymarket_us/operator_controls.py`. It must not create a new `operator_controls` importer.
  - Add a test that the dhat script prints only a ladder label.
- **BUILD-GAP BG-5:** no test ties `EXEC_PAR_FROZEN_BUCKET` to this document. Add one to `tests/unit/test_exec_par_wp5b_config.py` that asserts the constant equals this document's §3 label.

## 4. Breaker: triggers, reset and rollback drill

**Trip triggers.** `runtime/breaker_watcher.py:BreakerWatcherActor._persist` runs every `WATCHER_INTERVAL_SECONDS` = 5 s. The watcher is registered only when K>1 (`build_exec_watcher`). It trips on any of:
- `STUCK_TRIP_COUNT` = 2 or more open intents older than `STUCK_AGE_NS` = 900 s.
  - The code uses 900 s for both the with-id and the no-id shape. Plan r5 said 720 s for with-id; the code wins. The effect is a later trip, never a false one.
- `ambiguous_notional_breaker_tripped`, meaning AMBIGUOUS notional is above `f_breaker`.
- Any increase in `contradiction_events_total`, as defined in r5.1 E14.5.
- Any increase in `duplicate_suspect_total`.

**Duplicate detector framing.** It is a belt for stuck slots only:
- It runs after the lag guard `L_feed` = 300 s (WP0 §5: the 300 s default, not measured) plus confirmation on a second consecutive pass.
- A duplicate on an order that resolves normally is caught only by the 120 s cool-off and positions reconciliation.

**Halt behaviour:**
- The halt is entries-only and sticky, recorded in the breaker record `submit_intent_slots.BREAKER_KEY`.
- Exits and the resolver are never blocked.

**Entry denials** (`SubmitIntentLatch._breaker_denial`). Entries are denied when:
- the record is absent more than `BREAKER_ABSENT_GRACE_NS` = 60 s after boot;
- the record is garbled;
- the halt is set;
- the heartbeat is older than `BREAKER_HEARTBEAT_MAX_AGE_NS` = 60 s;
- the resolver pass is older than `BREAKER_RESOLVER_PASS_MAX_AGE_NS` = 600 s;
- a stamp is more than 5 s in the future.

**Supervisor alerts** (`runtime/breaker_supervisor_watch.py:decide_breaker_alerts`):
- watcher dead: record absent for more than 120 s, or the heartbeat stale after the 600 s boot grace;
- resolver pass stale;
- halt latched;
- unreadable slot.
- Alerts repeat every hour while the condition holds.

**Reset.** The coordinating session performs the reset under the standing pre-authorisation. The operator is notified by the alert and is not asked. Order:
1. **Evidence first.**
   - The trip reason and the held-position list from `EXEC_PAR_BREAKER_TRIPPED`.
   - A venue positions GET that reconciles every held slug, with the NO-as-short-YES sign applied.
   - `clear_submit_intent_cli --list` output.
   - Every stuck slot resolved, or cleared by `--intent-id` with `--resolution`/`--evidence`.
   - For a contradiction or duplicate trip: the venue order history proving that each POST either matched once or that the duplicate is accounted for.
   - An incident report in `docs/incident-reports/`.
2. **Node down.** Use the hand-relaunch mechanics. The CLI refuses while the node holds the flock.
   - *Recorded cost:* the resolver and exits are unavailable for the whole down window.
   - Do not take the node down while a held position has an exit due. The halt itself is safe to leave in place.
   - Target window ≤ 10 min (PROPOSED).
3. **Reset.** Run `breezy.runtime.clear_submit_intent_cli --reset-entry-halt --ack-held-positions-reviewed` with the exact venv interpreter. This calls `SubmitIntentLatch.reset_breaker_halt`, which clears `halted` and keeps the stamps.
4. **Demote.** Commit K=1 per §1. Relaunch.

**Rollback drill** (before the first K>1 boot, and after any code rollback). These must be green at the activation SHA:
- `test_rollback_drill_after_drain_and_reset_old_reader_sees_valid_v1_retired` (WP5a);
- `test_drain_then_reset_then_rollback_drill` (WP7);
- `test_restart_with_k_forced_1_over_open_v2_table_resolves_all_slots_and_downgrades` (E7).

Live order for a rollback:
1. Review held positions.
2. Reset the breaker.
3. Drain to at most one open slot (the table rewrites as v1).
4. Set K=1.
5. Verify `halted: null` before reverting any code. Old code ignores the breaker record, so a stale halt would persist undetected.

## 5. AMBIGUOUS-rate halt (PROPOSED)

- **Metric:** AMBIGUOUS entries over posted entries, counting K>1-epoch entry orders only (§10 tag).
- **Halt:** demote to K=1 when either of these holds:
  - the rolling point rate over the last 30 posted entries is above 0.33, evaluated once n ≥ 10;
  - 3 or more AMBIGUOUS entries fall on one climate day. This is the clustering guard: WP0 drew p_amb independently per order, which favours a pass.
- **Rationale:** 0.33 is the Wilson upper bound of the WP0 hold inputs (7/39, `wilson_upper_95` 0.3267 in `exec_parallel_dhat_results_main4_nyc.json`). It is the stress p_amb the gate arm passed at.
- **Promotion** requires a stage-cumulative point rate ≤ 0.33 and no halt fired during the stage.
- **BUILD-GAP BG-2:** no code computes this rate. Create `scripts/analysis/exec_par_stage_gate.py`, a read-only evaluator over the exec-state store, the digest log lines and the BG-1 tag. Run it on a daily timer that alerts through the `alerts.env` sink, and verify its first scheduled run.

## 6. Live dropped-candidate-share stop (PROPOSED)

- **Metric:** the daily share of entry candidates denied by any of:
  - `OpenExposureBoundExceeded`;
  - K-full;
  - cool-off (`submit_intent_slots.DEFAULT_COOLOFF_NS` = 120 s);
  - the throttle;
  - the free balance.
  - Breaker and stale denials are reported separately and excluded.
- **Statistic:** p90 of the daily share over the stage's climate days, with at least 5 days. This is the live counterpart of WP0's day-level p90 d̂.
- **Thresholds:**
  - At S3: a p90 above 0.30, or a rolling 5-day p90 above 0.30, triggers demotion to K=1. The K>1 programme is then suspended until an amendment re-runs WP0 with live hold data.
  - At S1 and S2: reported only, because a lower K is expected to drop more.
- **BUILD-GAP BG-3:** strategy pre-filter WAITs are invisible to the digest.
  - `continuous_strategy._admission_refusal` → `TrialDayLatch.admission_would_refuse` returns a WAIT. It never emits an `OrderDenied`. `ExecParDigest.record_denial` counts only `OrderDenied`.
  - Fix: add a per-candidate, per-reason pre-filter refusal counter in `src/breezy/strategy/current_rung_hold/continuous_strategy.py` and `continuous_no_side.py`, surfaced in `runtime/exec_par_telemetry.py`.

## 7. Slippage and fee parity (PROPOSED)

- **Slippage**, measured per fill as `fill_px − decision ask` on K>1-tagged fills:
  - Promotion requires a stage mean ≤ 0.01, which equals the M1-v3 cost assumption (`PREREG.json` `slippage`), and at most 10% of fills above 0.02.
  - **Parity:** where at least 20 K=1 fills of the same family exist after the window closed, the mean of parallel minus serial must be ≤ 0.005.
- **Fee:**
  - The mean realized fee per contract must be within 0.005 of `max(venue_fee(ask), θ·ask·(1−ask))` with θ = 0.0695 (`PREREG.json` `theta`).
  - Any `fee_coefficient_at_fill` ≠ θ on a K>1 fill (stamped by `exec/client.py:record_fill`) triggers demotion to K=1.
  - A `fee_reconciled=False` share above 10% blocks promotion.
- The same BG-1 tag and the BG-2 evaluator are required here.

## 8. NO≥0.90 hold-time ramp gate (S1→S2)

WP0's hold inputs contain no NO≥0.90 order. Every AMBIGUOUS order was YES. The hold mixture (5 s with p = 0.2, otherwise 150 s; no-id 305 s) is assumed, not measured.

- **Gate:** at S1, collect at least 20 posted NO≥0.90 entry orders. Do not promote until then.
- Measure arm→retire hold times and the AMBIGUOUS share.
- Re-run the §3 stop rule with:
  - the empirical hold distribution;
  - p_amb = max(0.33, the measured Wilson upper bound).
- It must pass at K=6 at the actual label.
- **BUILD-GAP BG-6:** `exec_parallel_dhat.py` refuses every input on or after 2026-10-07. Add a hold-input-only mode that:
  - reads live K>1 hold times dated on or after 2026-11-29;
  - still takes candidates only from the pre-window set.

## 9. Concentration

| Scope | Limit | Enforcement |
|---|---|---|
| Per slug | 1 open slot, YES and NO sharing one slot, plus a 120 s entries-only cool-off | Code: `domain/exec_slots.admit` (same-slug deny); `DEFAULT_COOLOFF_NS` |
| Per order | The per-position cap | Code: `DailySpendLedger.authorize_order_cost` |
| Per station-day (PROPOSED stop) | Demote one stage if a station-day carries more than 0.50 of the day's deployed entry notional on 2 or more of the last 5 days | Telemetry: `ExecParDigest` per-station-day exposure, evaluated by BG-2. There is no cap: the operator ruling of 2026-09-14 (no one-position-per-station) stands. |
| Per 5 s window (PROPOSED stop) | Demote one stage if more than 0.50 of a day's entry notional is submitted inside one `WINDOW_NS` = 5 s window on 2 or more of the last 5 days | `runtime/exec_par_telemetry.py`, evaluated by BG-2 |
| Per family | Exactly one entry family is manifest-enabled while K>1 | Procedural check in §14. **BUILD-GAP BG-7:** a boot assertion in `src/breezy/app/trade.py` that forces K=1 when more than one entry family is enabled. |

## 10. Parallel fills never feed the M1-v3 verdict

**Structural fact (verified).** The M1-v3 statistic is market-only. It is computed by `scripts/analysis/no_longshot_pooled_test.py` from:
- the recorder Depth10 tape (`RecorderCatalogTape`, the first row in [12:00, 13:00) UTC);
- the CLI finals.

It reads no exec-state store and no fill record.

**The only contamination channel** is Breezy's own orders consuming depth inside the tape window.

**Rules:**
1. **No K>1 boot before 2026-11-29T00:00Z.** The window ends on `last_forward_day_rule` = first_forward_day + 52 d, which is 2026-11-28.
2. One look only. No K>1 statistic is ever added to the M1-v3 report, its look schedule or its sensitivities.
3. Every fill made at effective K>1 is tagged and reported in a separate stratum in any family tally.

**BUILD-GAP BG-1:** neither `DurableFillRecord` nor the resolver context carries a K or slot tag.
- Fix: add trailing-optional fields `k_effective_at_arm` and `open_slots_at_arm`, written at arm time, in `src/breezy/adapters/polymarket_us/exec/client.py`. This is a byte-pinned file, so it needs a re-pin under the §4 procedure of r5.
- Teach `scripts/analysis/score_live_trials.py` and `family_tally_v2.py` to stratify on the new fields.
- **Interim, if BG-1 is not merged:** the coordinator keeps an append-only K-epoch ledger `docs/evidence/exec_par/k_epochs.jsonl` with `{commit_sha, effective_k, boot_ts, stop_ts}`. A fill whose `ts_event` falls in a K>1 epoch is "parallel".

## 11. WP0 artefacts

Hashes computed by the coordinator at HEAD d3588ece (2026-10-10); re-verify at freeze.

| Path | sha256 |
|---|---|
| `docs/evidence/m1v3/exec_parallel_wp0_findings.md` | `f4a5b8de1c856fa5ffb423fd783a2601bf2a3f4ad54ecd28f099ff907c67efb7` |
| `docs/evidence/m1v3/exec_parallel_dhat_results.json` | `5c1f29b0df248da74c4ed5c1ca364f93d8ab4256581dfb4db0aad2c3cb4f63f1` |
| `docs/evidence/m1v3/exec_parallel_dhat_results_main4_nyc.json` | `822460ede994cf8ac2169b33e5e6100beb2b3311a809f32d7422f8840fd9a6d3` |
| `docs/evidence/m1v3/exec_parallel_dhat_cands.json` | `55951aaf9147f4e295842865cd8672a8f0797bd801aa65ab224c8e3da003243d` |
| `docs/evidence/m1v3/exec_parallel_dhat.py` | `37bc13cc26ef796b1b5dfb5c3cd134e20e4f274940debf98d39e2a81a9f312eb` |

- **WP0 tree:** `b86ebf37` + `12d7ae78`.
- **Chosen K's CI:** at bucket 0.05, K=6, main4+nyc, the p90 CI upper bound is 0.2905 (findings Headline). The coordinator verifies this against the JSON.

## 12. Permit-notional non-debit for boot fills (r5.1 E14.6)

- A fill on an intent registered at boot (H6) does **not** debit the live-trading permit's session notional.
- **Accepted, because:**
  - the daily ledger counts it (the exactly-once property);
  - the undercount is bounded by `f_adm` × budget = 0.50 of the budget per boot carry-over set;
  - the same intents carry across respawns, so the undercount is not additive.
- **Anchors:** `test_boot_permit_untouched_by_open_intent_registration` and `test_boot_zero_fill_retire_no_permit_restore_d3`.

## 13. Freeze and amendment

**Freeze:**
1. Commit this document alone, at `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-D-PREREG.md` with `Status: FROZEN` and the §11 hashes filled in. That commit's SHA is the **frozen SHA**.
2. A second commit adds `EXEC-PAR-D-PREREG.sha256`, which holds the sha256 of the frozen bytes. A document cannot contain its own hash, so it follows the `first_forward_day` precedent in `PREREG.json`.
3. **Deadline:** before the first K>1 boot, and no later than 2026-12-06T23:59Z. That is strictly before the M1-v3 read, which happens on or after 2026-12-07.
4. Push only after the full gate reads EXIT=0.

**Amendment:**
- The frozen file is never edited.
- A change is a new document, `EXEC-PAR-D-PREREG-A<n>.md`, peer-reviewed and frozen the same way. It is effective only forward. It never reclassifies past fills.
- **Tightening** (a lower K, a stricter threshold, a demotion) can be applied immediately as an operational action without an amendment.
- **Loosening** needs a frozen amendment before it takes effect. Its justification must not use data from the stage whose stop it loosens.

## 14. Activation checklist (all items, in order, before K>1 is set)

1. WP-DR through WP7 are merged, and every BUILD-GAP (BG-1 … BG-7) is merged. The full gate reads EXIT=0 at the activation SHA, and `lint-imports` reports "N kept, 0 broken".
2. This document is frozen per §13, and the §11 hashes are re-verified.
3. The date is on or after 2026-11-29 (§10).
4. An eligible family exists: a WINNER from a frozen prereg (the M1-v3 read on or after 12-07, or another). Exactly one entry family is enabled.
5. The operator caps are set. The `cost_budget_bucket()` label is ≤ `0.05`. Only the label is recorded.
6. The §3 stop rule passes at the actual label, cost = cap, K=6.
7. The BG-5 test passes: `EXEC_PAR_FROZEN_BUCKET` equals `"0.05"`.
8. The supervisor is restarted on WP5a or later, and the decode marker admits v2.
9. Alert delivery is proven by a positive control through the live sink (`EXEC_PAR_*` and `TRADE_SUPERVISOR_BREAKER_*`).
10. The rollback drill tests (§4) are green, and a CLI `--list` / `--reset-entry-halt` tabletop has been run on a backup copy of the store.
11. The pre-boot state is clean:
    - no OPEN or AMBIGUOUS intent;
    - breaker record absent or `halted: null`;
    - no unreadable slot;
    - the permit is unexpired.
12. Commit K=2 (S1). Restart the supervisor in the 01:00–16:40Z window, then respawn the node.
13. Post-boot checks:
    - no `EXEC_PAR_K_FORCED_TO_1`;
    - the breaker heartbeat is present within 60 s;
    - the permit line is in the node log.
    - If any check fails, demote to K=1.
