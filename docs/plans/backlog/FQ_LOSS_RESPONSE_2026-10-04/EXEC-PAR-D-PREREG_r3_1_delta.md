# D-PREREG r3.1 delta: coordinator rulings on the r3 confirm reviews

- **Base:** `EXEC-PAR-D-PREREG_draft.md` r3, commit 8e3e040c.
- **Reviews:**
  - failure-mode: NOT-READY 82;
  - architecture: READY-WITH-FIXES 89;
  - market/stats: READY-WITH-FIXES 80.
- **No reviewer found a structural blocker.**
- **Binding:** these rulings are binding and amend r3. At freeze they are folded into `EXEC-PAR-D-PREREG.md` (§13).
- **Header fix:** code basis = HEAD 8e3e040c.

## D1. Boot-pass entry gate (failure-mode HIGH-1)
- At configured K>1, `SubmitIntentLatch._breaker_denial` adds the reason `stage_eval_boot_pending`. It denies entries until a stage-eval stamp **written by this boot** is present.
  - A stamp from a previous boot does not count.
  - Compare the stamp's `boot_ts_ns` with the current epoch row (BG-2).
- Exits and the resolver are never blocked.
- Owner: BG-5 + BG-6.

## D2. BG-1 write failures and gappy days (failure-mode HIGH-2)
- **A failed write is a trip.** If a BG-1 counter write fails, the watcher writes an integrity halt `telemetry_write_fail`. This halt does not set the flag (§1a).
- **Missed coverage makes the day gappy.** Any interval where the watcher was not ticking, or the node was down, during a governed climate day marks that day **gappy** in BG-1:
  - between respawns;
  - watcher death (heartbeat gap > 60 s).
- **The evaluator fails on a gappy day.** It returns FAIL for any rule whose window includes a gappy day, which produces an integrity halt.
- **Boot reconciliation.** At boot, BG-1 counters for open climate days are reconciled against three sources:
  - the slot table;
  - `DailySpendLedger` registry;
  - durable fill records (`fill_index`).
  
  Any mismatch marks the day gappy.

## D3. Evaluator liveness and halt-write failure (failure-mode MEDIUM-3, architecture MEDIUM)
- **The pass is a detached task.** It is never awaited inside `tick()`, so the 5 s heartbeat cannot stall.
- **Liveness is recorded in the breaker record.** The heartbeat record carries `stage_eval_last_start_ns` and `stage_eval_last_ok_ns`.
- **Integrity halt `stage_eval_stuck`:**
  - a pass running longer than 2 × timeout (240 s); or
  - no completed pass by boot + 300 s.
  
  An executor thread cannot be killed. The halt is the containment, and the next pass is not started while one is outstanding.
- **If `write_breaker_halt` raises:**
  - the watcher **stops writing heartbeats**;
  - the existing 60 s heartbeat-staleness denial then fails closed;
  - the watcher logs ERROR;
  - the supervisor alerts through the existing WATCHER_DEAD path.

## D4. `LedgerPredicatePort` raises (failure-mode MEDIUM-4)
- Any raise, or any non-bool return, from a ledger predicate counts as **tripped**.
- This applies in both BG-6 `_persist` and BG-5.

## D5. Reset hardening (failure-mode MEDIUM-5 and Check 3)
BG-4 `--reset-entry-halt` refuses in either of these cases:
- **(a)** The latched halt reason is a stop-rule reason (§5/§6/§7/§9/§15) and the force-K1 flag is unset. A lost flag write must be repaired first, with `--set-force-k1 --reason <stop>`.
- **(b)** A **dry evaluator pass** has not succeeded. The CLI runs the pure evaluator itself:
  - against the store, read under the lock it already holds with the node down;
  - it requires a `PASS` or `STOP-ACKNOWLEDGED` verdict with complete inputs;
  - it records the verdict in the incident-report path.

This turns "input repaired" from a procedure into a code check.

## D6. Flag keyed on the verdict (architecture MEDIUM)
- `write_breaker_halt` keeps the first reason (sticky). A transient `stage_eval_fail` halt could therefore mask a later stop-rule reason.
- **The flag is written from the evaluator's verdict**, independent of whether a halt write latched a new reason.
- The re-assert keys on the **verdict of each pass**, not on the latched reason.

## D7. Threading (architecture HIGH)
`SqliteStateStore` uses `check_same_thread=True` (`sqlite_store.py:122`). Therefore:
- The **loop thread** gathers every input into an immutable snapshot:
  - store reads;
  - latch state;
  - ledger predicate booleans;
  - BG-1 counters.
- The executor runs **only** the pure function over that snapshot.
- All writes happen on the loop thread, through new latch methods. These methods must not nest `_mutex`, which is non-reentrant.

## D8. P&L source (architecture MEDIUM)
- **The ledger is not the source.** `DailySpendLedger` tracks spend, not P&L.
- **BG-1 gains a settled-P&L accumulator per climate day.** It is computed when settlement is ingested, as:
  - durable fill records × the CLI-final settlement outcome;
  - net of realized fees;
  - with AMBIGUOUS entries counted as a full-cost loss until resolved.
- **Units:** values stay local and are compared only through `LedgerPredicatePort` budget-fraction booleans.
- **Nautilus portfolio realized P&L:** at most a cross-check. It is used only if BG-1's build proves it realizes at weather settlement. It never gates.

## D9. Burst guard (stats F1 HIGH)
- **Threshold:** raised to **≥5 AMBIGUOUS within 60 minutes**.
- **Clock:** the **entry arm time** (`arm_slot` `created_ns`), not the classification time.
- **BG-10(c) simulation:** simulates the guard using the **empirical intraday entry-time distribution** from pre-2026-10-07 candidates. It records the 15-day false-alarm rate at p = 0.18, for both ρ = 0 and ρ = 0.1.
- **Pre-registered adjustment:** if the ρ = 0 rate is above 10%, the threshold becomes **≥6** before freeze. No other adjustment is permitted.

## D10. Promotion bound (stats F2 MEDIUM)
- **Minimum days:** the §5 promotion bound needs **≥8 climate days** in the stage. Promotion is evaluated once, on the first day when both the §1 minima and this minimum are met.
- **Method:** the one-sided 90% Wilson upper bound on the pooled rate, with the effective n = n / DEFF. Here DEFF = 1 + (m̄ − 1)·ICC.
  - m̄ is the mean entries per day.
  - ICC is the observed between-day intraclass correlation, floored at 0.1.
- **Viability assertion:** BG-10(c) must record a level of **≥ 0.30**. If it is lower, the K>1 programme is **not viable** and no activation occurs without an amendment.

## D11. §15 arithmetic restated (stats F3 MEDIUM)
These figures net wins at about +0.0052, against losses of −0.05 cap/budget.

| Stop | Losses needed | Loss rate |
|---|---|---|
| Day stop (−0.15) | About 4 losses in 7 entries | Note A |
| Stage stop (−0.40) | About 11 losses at n = 35 | 31% |
| | About 17 losses at n = 105 | 16% |
| Cumulative stop (−1.0) | About 18–20 net losses at n ≥ 200 | — |

- **Note A, day stop:** the false-trip rate is about 0.3% per day at a 10% loss rate, and about 2.3% per day at 18%. AMBIGUOUS-as-loss overlaps with §5; this is accepted as conservative.
- **The stage stop is a 15-day backstop**, not a 5-day look.

## D12. §3 seeds (stats item 6)
- **Rule:** **every** seed's CI upper bound must be ≤ 0.30.
- **Change from r3:** the r3 clause "max ≤ 0.305" is withdrawn. The 0.0095 margin does not justify slack above the bar.

## D13. §14 failure injection (failure-mode Check 4)
§14.10 becomes gate tests against the **real** latch admission path. Each test asserts that a real submit is denied at submit time. They cover:
- **Each stop-rule family:** §5, §6, §7, §9 and §15. Each one sets the flag.
- **Each integrity path**, none of which sets the flag:
  - evaluator exception;
  - evaluator timeout;
  - a thread hung past 2 × timeout;
  - BG-1 write failure;
  - `LedgerPredicatePort` raise;
  - `write_breaker_halt` raise (the heartbeat stops and is then denied);
  - evaluator sub-task death;
  - entries attempted before the boot pass (D1);
  - gappy day (D2).
- **Supporting checks:** the dry boot on a backup store stays as a supporting check only.

## D14. Nit
- BG-9's dependency "§13 freeze" is a process step, not a build dependency. Move it to §14.
