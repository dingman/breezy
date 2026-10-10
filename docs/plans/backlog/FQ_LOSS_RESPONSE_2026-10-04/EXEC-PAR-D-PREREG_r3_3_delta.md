# D-PREREG r3.3 delta: coordinator rulings on the r3.2 confirm reviews

**Base:** r3 (8e3e040c), r3.1 (85cf0af1) and r3.2 (aeeee581).

**Reviews of r3.2:**
- failure-mode: NOT-READY, 80 (one new deadlock, one regression);
- market/stats: READY-WITH-FIXES, 86.

These rulings are binding and supersede earlier text where they conflict. All four documents fold into `EXEC-PAR-D-PREREG.md` at freeze.

## G1. Stage-reset record (failure-mode F1, HIGH: case (d) deadlock)

**One window floor.** Every window reset is driven by a single store record:

- `exec_par/stage_reset {ts, cause, halt_ts}`

It is written in three situations:
- (a) by `--clear-force-k1` (replacing E2's use of `force_k1_cleared.ts`);
- (b) by the integrity abort for an unreconcilable gappy day (E3);
- (c) at every K change (boot with a different effective K than the last epoch row).

**What the floor covers.** The evaluator reads §5, §7, §9 and §15-stage windows only from data after the latest `stage_reset.ts`. §15-cumulative is exempt.

**The unreconcilable gappy day is outside every window.** After a gappy-day abort (b), that day falls before the floor, so the boot pass no longer sees it. That ends the deadlock.

**Ordering.** The abort writes `stage_reset` **before** it writes the integrity halt. If the `stage_reset` write fails, the outcome falls back to D3: heartbeat stop, which fails closed.

## G2. Every reset is code-gated on a dry pass (failure-mode F2, MEDIUM: regression)

`--reset-entry-halt` refuses unless a `stage_eval_dry` record exists that meets all of these:
- it is newer than the latched halt;
- its inputs are complete;
- its verdict is PASS, or STOP-ACKNOWLEDGED for a stop-rule halt.

This applies to **every** halt reason: stop-rule, integrity and existing breaker trips.

The E1 order therefore applies to every reset. Step 4 (`--clear-force-k1`) is the only conditional step.

## G3. Case (b) and task death (failure-mode F3, MEDIUM)

**`--clear-force-k1` when the flag is unset.** It **succeeds** and records `force_k1_cleared` and `stage_reset`. That is how a stop-rule halt whose flag write was lost passes E1 step 5.

**Task death before its callback is attached.** The E5 per-tick check is:

> outstanding task `done()` and no stamp for that pass → integrity halt.

This runs regardless of the callback. It catches a task that dies before its done-callback is attached.

## G4. E3 premise reworded (failure-mode F4, MEDIUM)

**Old premise:** "No order can exist while the node is down."

**New premise:** entries are IOC, so no entry rests at the venue across a node outage. An AMBIGUOUS IOC can still have filled unseen.

**Ordering requirement.** Boot reconciliation runs **after** the Nautilus mass-status ingest, so that `generate_fill_reports` fills (including fills an AMBIGUOUS order produced while the node was down) are in the durable records before BG-1 counters are compared.

**Pinning.** A BG-1 test pins this ordering.

## G5. Attribution after a reset (failure-mode F5, LOW)

**Attribution rule.** Fills and settlements are attributed to windows by the **entry's `arm_slot` `created_ns`**, not by the settlement time.

**Consequence.** A position armed before `stage_reset.ts` and settled after it counts in the pre-reset (closed) windows and in §15-cumulative, never in the new stage.

**Visibility.** Such post-reset settlements are reported in the stage report.

## G6. Viability check uses the floored ICC and the two-look schedule (stats F1, MEDIUM)

This replaces the E8 80% clause.

**Rule.** BG-10 computes the promotion pass probability at p = 0.18 with:
- ICC = max(0.1, the ANOVA estimate from pre-window data);
- the **full E9 two-look schedule**.

It must be **≥ 80%**.

**Reviewer arithmetic (to be reproduced by BG-10):** at level 0.33, ICC 0.1 gives a first look of about 74% and an overall pass of about 86%.

**Unchanged.** The 0.33 level floor stands.

## G7. Re-look data and two-look false pass (stats F2, MEDIUM)

**Re-look data.** The E9 re-look uses **all stage data since the latest `stage_reset`**, cumulatively. It is not limited to the extension days.

**Pre-registered false-pass check.** BG-10 records the two-look false-pass probability at a true p = 0.30. It must be **≤ 20%**; otherwise the programme is not viable without an amendment.

## G8. Integrity aborts cannot erase evidence (stats F3, LOW–MEDIUM)

**Scope.** Integrity aborts (G1(b)) reset only the **gappy-day exclusion**. §5 and §7 counters from reconciled days carry across them.

**What the floor means in this case.** For cause `gappy_abort`, the floor applies only to the unreconcilable day. Reconciled days before it remain in §5 and §7.

**Cap on aborts.** More than **2 integrity aborts in one stage** is a demotion verdict, and sets the flag.

## G9. Reconciliation mismatch visibility (stats F4, LOW)

Every E3(c) rebuild emits an alert `EXEC_PAR_COUNTER_REBUILT`, carrying the day and the mismatch kinds.

Rebuilt days are listed in the stage report. The alert is added to the §14.9 positive controls.

## G10. Stamp accessor (failure-mode note)

`SubmitIntentLatch._boot_ns` is private and in-memory. BG-5/BG-6 add a public read-only `boot_ns` property, and the E7 check uses it.

BG-8 pins with a test that the supervisor never respawns or kills the node on any breaker alert.
