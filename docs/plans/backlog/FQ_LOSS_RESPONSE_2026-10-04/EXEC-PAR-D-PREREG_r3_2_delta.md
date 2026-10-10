# D-PREREG r3.2 delta: coordinator rulings on the r3.1 confirm reviews

- **Base:** r3 (8e3e040c) + r3.1 delta (85cf0af1).
- **Reviews of r3.1:**
  - failure-mode NOT-READY 78, on two new deadlocks plus refinements;
  - market/stats READY-WITH-FIXES 84.
- **Status:** these rulings are binding. Where they conflict with r3 or r3.1, they supersede both. All three documents fold into `EXEC-PAR-D-PREREG.md` at freeze.

## E1. Reset order — resolves the D5(a) / §4 deadlock (failure-mode HIGH-1)

Replaces r3 §4 steps 3–4 and r3.1 D5. The canonical order is:

1. **Gather evidence**, as r3 §4 step 1.
2. **Take the node down**, as r3 §4 step 2.
3. **Dry evaluator pass.** Run `clear_submit_intent_cli --dry-eval --incident-report <path>`.
   - Inputs: the pure evaluator over the store, read under the lock the CLI holds.
   - It writes a `stage_eval_dry` record to the store: verdict, input-completeness, ts.
   - It appends the verdict to the incident report.
4. **Clear the flag**, if set: `--clear-force-k1 --incident-report <path>`.
   - It **refuses** unless a `stage_eval_dry` record exists that is newer than the latched halt. That record must show complete inputs and a verdict of PASS or STOP-ACKNOWLEDGED (E4).
   - It writes `force_k1_cleared {ts, halt_ts, incident_report}`.
5. **Reset the halt:** `--reset-entry-halt --ack-held-positions-reviewed --incident-report <path>`. It refuses in either of these cases:
   - the flag is set and the configured K is above 1 (r3);
   - the latched halt reason is a stop-rule reason, and no `force_k1_cleared` record has `halt_ts` equal to this halt.

   This replaces D5(a). A lost flag write is now harmless: a stop-rule halt can only be reset after passing through step 4, and step 4 does not require the flag to be set.
6. **Demote**, then relaunch.

## E2. No re-trip from old evidence (failure-mode 3, D6 interplay)

- `force_k1_cleared.ts` resets **every rolling and stage window** (§5, §6, §7, §9, §15 stage). The evaluator reads only data after that ts.
- §15 cumulative is the exception. It is not reset, because it is the programme-level backstop.
- A stop verdict computed only from pre-clear data cannot re-set the flag.
- After a stop, the ramp restarts at S1 under r3 C5. That restart is a K change, so the windows reset in any case.

## E3. Gappy days — replaces r3.1 D2 (failure-mode HIGH-2)

**Node-down is not a gap.**
- Counters are event-sourced from durable records: fills, the slot table and the ledger registry.
- No order can exist while the node is down.
- An interval between a recorded epoch `stop_ts` and the next `boot_ts` is therefore a **recorded outage, not a gap**. The planned 16:50Z respawn is covered by this.

**A day is gappy only in these cases:**
- (a) The node was up, with an epoch row open, and the watcher heartbeat lapsed for more than 60 s.
- (b) There was an unclean shutdown, meaning no `stop_ts`. The interval from the last heartbeat to the next boot is a gap until boot reconciliation matches.
- (c) Reconciliation mismatches. Reconciliation runs at boot **and at every daily evaluator pass**: BG-1 counters are compared against durable fill records, the slot table and the ledger registry.

**Clearing:**
- A matching reconciliation **rebuilds** that day's counters from the durable sources and clears the mark. The rebuild is recorded.
- An unreconcilable gappy day **aborts the stage**: an integrity halt fires, the ramp restarts at S1, and the windows reset. This fails closed with no permanent deadlock, because a past gap never blocks a later fresh stage.
- The r3.1 D2 telemetry-write-fail integrity halt stands.

## E4. Dry pass definition and inputs (failure-mode HIGH-3)

**Verdicts:**

| Verdict | Meaning |
|---|---|
| PASS | Complete inputs; no stop rule fires. |
| STOP-ACKNOWLEDGED | Complete inputs; a stop rule fires; the incident report names that stop reason and its remediation. |
| FAIL | Any input is incomplete, gappy or unreadable. |

- The flag may only be cleared on PASS or STOP-ACKNOWLEDGED. After a stop, the next stage starts fresh at S1 with windows reset (E2).

**Budget-fraction predicates need the operator caps.** The caps exist only in the node launch environment.
- `--dry-eval` must run in that launch environment, with the same env as the node launch, and must never print the cap values.
- If the caps are absent, it fails loudly: `operator caps not present: run --dry-eval from the node launch environment`. That is a FAIL verdict.

## E5. Evaluator sub-task death (failure-mode MEDIUM-4)

- The evaluator pass task gets a done-callback. Any exception or cancellation raises an integrity halt `stage_eval_task_died`.
- Each watcher tick also checks: if the outstanding task is `done()` and no stamp was written for that pass, raise an integrity halt.

## E6. Heartbeat-stop specifics (failure-mode MEDIUM-5)

When `write_breaker_halt` raises (r3.1 D3):
- Only the heartbeat write stops. The watcher keeps ticking its other duties: counters, alerts and the flag write. The flag write is attempted independently and its failure is logged at ERROR.
- The breaker denial applies to **entries only**. Exits and the resolver are unaffected. This is existing behaviour, and a BG-6 test pins it.
- The supervisor's `WATCHER_DEAD` handling **alerts only and never respawns or kills the node**. Verify this in the BG-8 build and pin it with a test.

## E7. Boot-pass stamp identity (failure-mode MEDIUM-6)

- Replaces the epoch-row comparison in r3.1 D1.
- The stage-eval stamp carries the latch's `_boot_ns` (`submit_intent.py:560`).
- `stage_eval_boot_pending` clears only when **both** hold:
  - `stamp.boot_ns == latch._boot_ns`;
  - `stamp.ts_ns ≥ latch._boot_ns`.

## E8. Viability floor (stats MEDIUM-1)

- Replaces r3.1 D10's "level ≥ 0.30". The BG-10(c) level must be **≥ 0.33**, which is the §3 gate-arm proxy.
- BG-10 must also record the promotion pass probability at the derived level for p = 0.18 at 8 days, and it must be **≥ 80%**.
- If either condition fails, the K>1 programme is not viable without an amendment.
- Reference figures from the reviewer: 82% at a level of 0.33, ICC 0, 8 days; 69% at ICC 0.15.
- If BG-10's true ICC estimate from pre-window data exceeds 0.1, the 80% check uses that estimate.

## E9. Promotion look (stats MEDIUM-2)

- The first look happens at ≥ 8 climate days (r3.1 D10). A first FAIL is **not** a demotion. It opens the r3 §1 5-day extension, followed by exactly one re-look.
- A demotion verdict follows only a second FAIL.
- The 15-day cap still applies. If the re-look would fall after day 15, it happens on day 15.

## E10. ICC estimator (stats LOW-3)

- **Estimator:** one-way ANOVA ICC with n₀ weighting, where n₀ = (N − Σ mᵢ²/N)/(k − 1).
- A negative estimate is set to the floor of 0.1.
- m̄ is the mean entries per climate day over the stage.

## E11. D9 record (stats LOW-4)

The frozen §5 records the BG-10(c) simulated 15-day false-alarm rates for both the ≥5 and ≥6 guards (ρ = 0 and 0.1), and states which threshold applies.
