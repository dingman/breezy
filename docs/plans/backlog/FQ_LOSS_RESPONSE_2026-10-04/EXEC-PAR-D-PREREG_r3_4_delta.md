# D-PREREG r3.4 delta: coordinator rulings on the r3.3 failure-mode confirm

**Base:** r3 (8e3e040c) plus r3.1, r3.2 and r3.3 (ece3261f).

**Review:** the r3.3 failure-mode review came back NOT-READY at 82. All r3.2 findings are closed. What remains is internal inconsistency in the gappy-day path, plus three LOW items.

**Status:** the rulings below are binding. They supersede E3, G1(b) and G8 where those conflict. Next step: consolidate into r4.

## H1. Gappy days use an excluded-days set, not the floor
This replaces E3's "aborts the stage … ramp restarts at S1", G1(b) and G8.

**Exclusion mechanism.**
- An unreconcilable gappy day is added to a store set, `exec_par/excluded_days {day, cause, ts}`.
- Adding it raises an integrity halt and the alert `EXEC_PAR_DAY_EXCLUDED`.
- The evaluator skips excluded days in every window. All other days, and their §5/§7 counters, carry forward.

**The stage carries on.**
- Exclusion is **not** a K change.
- It writes **no** `stage_reset`.
- It does **not** restart the stage.

**Exclusion is not free.**
- An excluded day still counts toward the r3 §1 15-climate-day stage cap.
- §15-cumulative still counts its settled P&L, from durable fill records once they are reconciled at a later boot.

**Cap.** More than **2 excluded days in one stage** is a demotion verdict and sets the flag. The counter is scoped from the latest `stage_reset.ts`, so a demotion or K change resets it.

**What `stage_reset` is for.** It is written only by:
- (a) `--clear-force-k1`, on the stop path;
- (c) a K change.

## H2. `--dry-eval` reconciles before it evaluates (finding 2: other integrity halts)

`--dry-eval` runs under the CLI's lock, with the node down. It works in three steps:

1. **Reconcile.** First it runs the E3(c) reconciliation for every day in the windows, using the durable fill records, the slot table and the ledger registry. Each day either:
   - rebuilds and clears its gappy mark, raising `EXEC_PAR_COUNTER_REBUILT`; or
   - stays unreconcilable, and is added to `excluded_days` under H1.
2. **Evaluate.** Only after that does it evaluate.
3. **Result.** Heartbeat-lapse halts and telemetry-write-fail halts therefore always reach a PASS, FAIL or STOP-ACKNOWLEDGED verdict on complete, non-gappy inputs. The only exception is a store that cannot be read at all: that is FAIL, and the remedy is store repair, recorded in the incident.

## H3. `--clear-force-k1` preconditions (LOW-3)

It refuses unless one of these holds:
- the flag is set; or
- the latched halt reason is a stop-rule reason.

It never clears or floors windows when there is no stop.

## H4. Dry-pass freshness (LOW-4)

The `stage_eval_dry` record must be newer than **both**:
- the latched halt; and
- the latest epoch `stop_ts` (the node going down for this reset).

## H5. Erased evidence recorded (LOW-5)

When `stage_reset` is written but the following halt write fails (D3 heartbeat-stop fallback), the reset procedure must record two things in the incident report:
- the pre-floor window counts, which the CLI prints from the store before any reset;
- the fact that the floor moved without a latched halt.
