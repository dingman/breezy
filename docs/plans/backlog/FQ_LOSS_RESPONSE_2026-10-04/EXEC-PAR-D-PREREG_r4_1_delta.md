# D-PREREG r4.1 delta: coordinator rulings on the r4 final reviews

- **Base:** r4 (01ef0b2f).
- **Reviews:**
  - failure-mode NOT-READY 80 (one reset deadlock);
  - architecture READY-WITH-FIXES 86;
  - market/stats READY-WITH-FIXES 86.
- **Binding.** These rulings supersede r4 where they conflict, and fold into `EXEC-PAR-D-PREREG.md` at freeze.
- **Code basis:** HEAD 01ef0b2f (d5e5568d added tests only).
- **Rulings index:** add rows for J1, J2 and K1–K12.

## K1. Reset path keyed on the dry verdict, not the latched reason (failure-mode HIGH-1)

**Definition: stop-class reason.** Any §5/§6/§7/§9/§15 stop-rule reason, or any demotion verdict. Demotion verdicts include a second failed promotion and more than 2 excluded days in a stage. This term replaces "stop-rule" wherever §1b, §4 and §14 use it.

**`--clear-force-k1` is permitted when any one of these holds:**
- (i) the flag is set;
- (ii) the latched halt reason is stop-class;
- (iii) the latest fresh, complete `stage_eval_dry` verdict is STOP-ACKNOWLEDGED. Fresh means newer than the halt and the epoch `stop_ts`.

Case (iii) covers two situations: an integrity halt whose repaired dry pass reaches STOP, and a stop verdict masked by a sticky transient reason.

**`--reset-entry-halt` requires** a fresh, complete dry record, plus one of these:
- **(a)** verdict PASS, with the flag unset or configured K = 1;
- **(b)** verdict STOP-ACKNOWLEDGED, and a `force_k1_cleared` record whose `halt_ts` equals this halt.

The latched reason no longer selects the path. The dry verdict does. No combination of a latched reason and a verdict deadlocks:
- PASS goes down path (a).
- STOP goes through `--clear-force-k1` (iii), then path (b).
- FAIL is repaired and re-run.

**`--set-force-k1`** accepts any stop-class reason.

## K2. §14.10 additions (failure-mode MEDIUM-3)

Add failure-injection cases for each of the following:
- an injected flag-write failure, followed by the (b) repair path;
- flag re-assertion when a sticky transient reason is already latched;
- each existing §4 trip: stuck slots, AMBIGUOUS notional, contradiction, duplicate;
- a stamp that was never written after the first K>1 day;
- non-monotonic input;
- None input;
- a BG-6 intraday predicate raise;
- the J2 `unclean_cli` write;
- the K1 integrity-halt-then-STOP path.

## K3. J2 scope and owners (failure-mode LOW-4, architecture F4)

**`unclean_cli`.** `unclean_cli` `stop_ts` is written by **any** CLI invocation that acquires the exclusive lock when the latest epoch row has no `stop_ts`. Owner: BG-4.

**Owners of other missing writers:**

| Writer | Owner |
|---|---|
| epoch `stop_ts` at clean disposal | BG-2 |
| "flag set" alert | BG-3 |
| decision-ask persistence for §7 slippage | BG-1b; see note below |
| K=1 pre-boot fill-ledger read for §7 parity | BG-1c |

Note on decision ask: the BG-1b build verifies where the decision ask is available. If no durable decision ask exists today, BG-1b adds it to the durable record.

## K4. §1 "After a halt" table (failure-mode LOW-5)

Add the §9 intraday station-day 0.25 halt as a stop rule: halt, set flag, restart at S1.

## K5. Inline evaluation replaces the executor (architecture F3, F2)

**Change.** The pure function over at most about 15 days of counters is cheap. BG-5 therefore evaluates **inline on the loop thread**, in a dedicated watcher coroutine that is never inside `tick()`. A strong reference is held to the task, and it is cancelled in `on_stop`.

**Removed:**
- the executor;
- the 120 s `wait_for`;
- `stage_eval_stuck`;
- the outstanding-pass rule;
- the 240 s / 300 s thresholds.

**Kept:**
- `stage_eval_task_died`, triggered by the done-callback plus the per-tick `done()` check;
- `stage_eval_fail` for exceptions;
- the liveness fields.

**New integrity halt `stage_eval_slow`:** a pass whose measured wall time exceeds **2 s**. It is a performance-regression tripwire.

**Supporting changes:** §14.10 drops the hung-thread case and adds the slow-pass case. The D7 threading text simplifies to "everything on the loop thread".

## K6. Snapshot builder and predicate port (architecture F1)

**The snapshot builder is pure.** It takes the store reads and the predicates as injected callables.

**`LedgerPredicatePort` takes aggregates.** It accepts aggregated quantities — summed Decimals and ratios such as stage-cumulative P&L, the 2-of-5 day flags and the 5 s window share — and returns booleans against budget fractions. Currency values never leave the port's caller, which runs on the loop thread, and they are never logged.

## K7. BG-11 counters before S3 (architecture F5)

Before S3, §6 is report-only, and so are BG-11's counters. "A missing counter means FAIL" applies to §6 only at S3.

## K8. Dry boot timing (architecture §14)

§14 steps 12 and 13 use a dry boot at **configured K = 2 with orders disabled**:
- `BREEZY_ORDERS_ENABLED=0`, so no permit is minted;
- on a **backup copy** of the store;
- **on or after 2026-11-29**, so §10 rule 1 is respected.

Step 12's agreement check compares BG-7's read-only verdict with the in-node verdict on that dry boot. On empty data, a PASS/PASS match is the expected result.

Step 4 is kept: it is redundant with step 5 but harmless.

## K9. BG-1 split (architecture)

| Package | Scope | Depends on |
|---|---|---|
| BG-1a | the two ports; single-writer latch methods; store records (`stage_reset`, `excluded_days`, epoch rows, `stage_eval_dry`, `force_k1_cleared`) | — |
| BG-1b | counters and watcher ingestion, including decision-ask persistence | 1a |
| BG-1c | settled-P&L accumulator and the K=1 fill-ledger read | 1a |
| BG-1d | reconciliation, gappy marks, rebuild/exclusion, mass-status ordering test | 1a |
| BG-1e | `operator_controls` aggregate predicates (K6) | 1a |

Downstream dependencies:
- BG-2 and BG-3 depend on BG-1a.
- BG-5 depends on BG-1b through BG-1e.

## K10. Stats: V2 failure, the m̄ definition, the look minimum, the day-stop rate (stats findings)

- **V2 failure.** If **V2 fails at the 90% bound, the programme is not viable without an amendment**. The 95% switch is triggered **only** by V3, and nothing else may be tuned after the result is seen.
- **m̄ is pinned.** m̄ = total posted entries in the stage window ÷ the number of non-excluded climate days in it.
- **BG-10's entries-per-day assumption is pinned.** It is the empirical pre-2026-10-07 per-day candidate count multiplied by the simulated K=2 admission rate. It is recorded in the frozen §5.
- **Look minimum.** A Wilson promotion look requires **≥30 posted orders and ≥8 climate days**. A look never fires on fewer orders; it waits, subject to the 15-day cap.
- **Day-stop false-trip rate over a 15-day stage:**

| Loss rate | Per day | Over 15 days |
|---|---|---|
| 10% | ≈ 0.3% | ≈ 4.4% |
| 18% | ≈ 2.3% | ≈ 30% |

  This is stated in §15 and accepted as conservative.

## K11. Housekeeping

Header: code basis 01ef0b2f.

## K12. Freeze path

The remaining freeze inputs are:
- the BG-10 numbers (the §5 TBD table);
- BG builds landing per §14.1.

No further design review is required unless a BG build contradicts this text. If one does, the build stops and an amendment is raised.
