# D-PREREG r4.2 delta: rulings on the r4.1 failure-mode confirm

**Base:** r4 (01ef0b2f) + r4.1 (3cbd4f07).

**Review:** NOT-READY, 84/100. K1–K4 closed the r4 findings. One HIGH finding remains on path (b), plus one MEDIUM and one LOW.

**Status:** these rulings are binding and supersede r4.1 where they conflict.

## L1. A latched stop-class reason always requires the stop path (F1, HIGH)

This amends K1.

- **Reset rule.** `--reset-entry-halt` path (a) (PASS) is permitted **only when the latched halt reason is not stop-class**.
  - A latched stop-class reason always requires path (b): a `force_k1_cleared` record whose `halt_ts` equals this halt, and therefore a `stage_reset`.
  - This holds whatever the dry verdict is. A PASS dry verdict on a stop-class latched reason is accepted by `--clear-force-k1` as evidence, alongside STOP-ACKNOWLEDGED.
- **Dry-pass scope.** The dry evaluator also recomputes the intraday stop rules: §5 Clopper-Pearson, §5 burst, and §9 station-day 0.25 over open positions. It reports them in its verdict.
- **Result.** Path (b) "flag write lost + PASS" now always goes through the stop path, and the ramp restarts at S1 (§1).

## L2. Detecting a hung non-CPU pass (F2, MEDIUM)

This amends K5. `stage_eval_stuck` is restored in a cheap form.

- **Check.** On each watcher tick, if a pass is outstanding and `now − stage_eval_last_start_ns > 60 s` with no newer `last_ok`, the watcher writes the integrity halt `stage_eval_stuck`.
- **Coverage.** This catches a pass hung on an await while the loop is still running.
- **What it cannot catch.** A pass that blocks the loop itself stalls the tick and the heartbeat, so that case is covered by L4.
- **Test.** §14.10 adds an "await-hung pass" case.

## L3. Stage cap with the look minimum unmet (F3, LOW)

If the 15-day cap arrives before the look minimum (≥30 posted orders and ≥8 non-excluded days) is met:

- the stage **holds at its K**;
- there is no look, no promotion and no demotion verdict;
- it is reported in the stage report;
- it is never promoted without an amendment.

This is the same as r4 §1's "minima unmet" rule, which now explicitly includes the look minimum.

## L4. Loop-stall consequence documented (K5)

A pass that blocks the event loop stalls entries and also exits and the resolver, because they share the loop.

- **Entries** fail closed through the 60 s heartbeat denial.
- **Supervisor.** It alerts `WATCHER_DEAD`. It never kills or respawns the node (BG-8 pin).
- **Remedy.** A human hand-relaunch (hand-relaunch mechanics), followed by the §4 reset.
- **Why this is accepted.** The inline pass is bounded: about 15 days of counters with O(n) arithmetic. `stage_eval_slow` (2 s, post-hoc) catches regressions before they become stalls.
- **Recorded risk.** For the duration of a stall, exits and the resolver are unavailable.
