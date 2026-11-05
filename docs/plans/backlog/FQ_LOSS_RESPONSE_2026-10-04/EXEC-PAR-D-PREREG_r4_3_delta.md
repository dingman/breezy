# D-PREREG r4.3 delta: rulings on the r4.2 failure-mode confirm

- **Base:** r4 + r4.1 + r4.2 (13826482).
- **Review result:** NOT-READY 88. The prior findings are closed; what remains is wording/consistency plus one double-fault case.
- **Status:** the rulings below are binding.
- **Convergence:** the design is now converged across six review rounds. Architecture and stats were READY-WITH-FIXES at 86, and failure-mode moved 58→72→82→78→80→82→80→84→88. These rulings, and every delta, fold into a single `EXEC-PAR-D-PREREG.md` at freeze (§13). The **freeze-time full review by all three lenses on the folded text is mandatory** and is part of §14.2.

## M1. Path (b) wording (F1, MEDIUM)
This rule replaces K1 path (b) and the r4 §4 step 5 / BG-4 preconditions.

`--reset-entry-halt` path (b) requires all three:
- a fresh, complete dry record;
- a dry verdict of **PASS or STOP-ACKNOWLEDGED**;
- a `force_k1_cleared` record whose `halt_ts` equals this halt.

Path (a) applies **only** to a non-stop-class latched reason with no outstanding stop verdict (see M3).

## M2. The path is forced; the outcome follows the table (F2, MEDIUM)
- L1 forces the **reset path** for stop-class reasons. It does **not** set the post-reset ramp outcome.
- The outcome follows the r4 §1 "After a halt" table, by reason:
  - stop rules → S1;
  - demotion verdicts → down one stage;
  - §15-cumulative → K=1, and resuming needs an amendment;
  - §6 at S3 → the programme is suspended.
- L1's "the ramp restarts at S1" sentence is withdrawn.

## M3. Durable stop-verdict marker (F3, LOW: double fault)
**Write sequence.** Every stop-class verdict from BG-5 or BG-6 writes `exec_par/stop_verdict/<ts_ns> {reason, ts_ns}` **first**, before the halt and before the flag. A failed write of that marker is itself the integrity halt `stop_marker_write_fail`, and the heartbeat stops (D3).

**Flag-write failure.** A failed flag write sets a `flag_write_failed: true` field on the breaker record, via the same single-writer path as the halt.

**Path (a) refusal.** `--reset-entry-halt` path (a) is refused if either of these holds:
- any `stop_verdict` exists with `ts_ns` ≥ the latest `stage_reset.ts` and no `force_k1_cleared` has consumed it (`force_k1_cleared.ts` > marker `ts_ns`);
- `flag_write_failed` is set.

**Double-fault case.** A masked intraday stop plus a lost flag write therefore always takes path (b).

**Clearing.** `--clear-force-k1` (K1 (iv), new) is also permitted when an unconsumed `stop_verdict` exists.

## M4. Threshold scope (F4, LOW)
- **`stage_eval_slow` (2 s)** measures the **pure evaluation step only**, excluding reconciliation.
- **`stage_eval_stuck` (60 s)** applies to the evaluation pass.
- **Reconciliation** (at boot, daily, or in `--dry-eval`) has its own bound of **300 s**. Exceeding it, or an await-hang beyond it, is the integrity halt `reconcile_stuck`.
- **Tests:** §14.10 adds `reconcile_stuck` and `stop_marker_write_fail`.

## M5. Exit from a held stage (F5, LOW)
- **Trigger:** a stage held under L3 for **30 consecutive non-excluded climate days** without meeting the look minimum.
- **Demotion:** it is demoted one stage as a **cleanup demotion**. This needs no flag and no halt: it is a low-volume signal, not a safety signal. The coordinator commits the lower K, with the gate.
- **Held at S1:** demotion goes to K=1, and the programme is paused. Restarting needs an amendment that shows a changed volume premise.
- **Reporting:** the stage report records the hold.
