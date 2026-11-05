**Verdict: NOT-READY (70/100).** r2 resolves most of my r1 findings in design. Reviewing the §3.5 and §3.6 additions against the code turned up four new defects, listed first below. All are fixable in an r3, and none changes the architecture.

## New findings

**HIGH-1. The new ledger fraction bound denies after the permit is consumed.**
- Evidence: in `client.py:6238-6285` the permit `consume()` runs at step 4, before `authorize_order_cost` at step 5.
  - §3.5 puts `OpenExposureBoundExceeded`, the `_unbounded` refusal and the uncharged `DailyBudgetExhausted` inside `authorize_order_cost`. They would fire after the permit has already spent an order-count slot and notional.
  - The only permit give-back, `restore_live_trading_budget`, is wired only to the confirmed zero-fill path (D3). The deny at :6284-6285 does not call it.
  - r1 H-b and S-H6 asked for admission before spend. r2 moves `admit` earlier (§3.3) but leaves the exposure bound behind the permit.
- Failure: at K>1 this denial is a routine WAIT, not a rare event. Each one burns permit slots and notional. Exhausting the permit notional raises `SessionNotionalExhausted`, which calls `_mark_budget_exhausted` (:6255-6256). That writes the durable single-day stop marker, so a recoverable exposure hold becomes a false day stop.
- Required change: add a read-only ledger pre-check, for example `ledger.exposure_admission_refusal(cost)`. It runs inside the same no-await span, before the permit spend, with a named allowlist row. The in-lock check in `authorize_order_cost` stays as the authority. Add a RED test: a bound denial leaves the permit remaining count and notional unchanged and does not write the budget-exhausted marker.

**HIGH-2. Boot permit seeding with open notionals creates a false day stop (open question 2).**
- Evidence:
  - `seed_permit_budget_from_prior_spend` (`safety.py:799-841`) is once per permit and subtracts from `remaining_notional_usd`.
  - A boot-registered intent has `booking is None`, so D3 never restores it. The plan itself says "stays debited for the process".
  - The ledger releases headroom when the intent retires, but the permit does not.
- Failure: restart with 2 stuck slots, 0.4 of the budget in notional. The permit is seeded 0.4 low. The slots resolve zero-fill at 130 s and the ledger shows full headroom. The permit still refuses with `SessionNotionalExhausted`, which writes the durable day-stop marker for a day with real headroom. A restart is needed to recover.
- This is not acceptable lost capacity. The plan's own F19 says "the ledger is the only daily-budget authority", and the uncharged-exposure term in `authorize_order_cost` already bounds the exposure.
- Required change: seed the permit with durable fills only, as today. Open exposure is enforced by the ledger alone. If the operator wants a double bound, add a reversible permit hold API, but do not reuse the one-way seed. Update `test_boot_zero_fill_retire_no_permit_restore_d3` to assert the permit is unchanged by open-intent registration.

**HIGH-3. The fraction bound applies to all open intents, which defeats K and invalidates §6.**
- Evidence: §3.5 says `open_other + cost > f × budget` (all open intents, "as built"). Normal in-flight orders occupy a slot for about 0.3 s.
  - Max concurrency is about floor(f×B/c). At c/B = 0.25 and f = 0.5 that is 2, whatever K is.
  - §6.1's model calls the production `admit` (WP0 `test_admit_used_by_simulation_is_the_production_admit`), but the bound lives in the ledger, not in `admit`. So the d̂ numbers for K = 6 describe a concurrency that real c/B values may never allow. c/B is swept only in the first-5s arm, which is "not a gate".
- Answer to open question 3: apply the admission bound to unresolved AMBIGUOUS notional only. Concurrent normal POSTs are already bounded by K × cap, by the ledger, and by the throttle.
- Required change: either restrict the bound to AMBIGUOUS-only, which needs a `mark_ambiguous(key)` ledger transition, or put the bound into `admit` and the WP0 simulation with a c/B sweep as a stop-rule dimension. Reconcile the c/B assumption with the operator's actual caps without reading or assigning them. Using the live caps as a read-only input to the simulation is safe, but the plan must say so.

**HIGH-4. The breaker's notional trigger is a dead condition (open question 3).**
- Evidence: §3.6 trips when open-AMBIGUOUS notional > 0.50 × budget. §3.5 already denies any entry once `open_other + cost > 0.50 × budget`, using the same f and the same quantity (or a superset of it). The total therefore never exceeds f × B, and the strict `>` never fires.
- f = 0.50 is also too loose as a halt point. Half of the day's budget is held in orders of unknown fate, against a single-day stop designed to trip at 100%.
- Required change: set a lower breaker fraction (suggest 0.25–0.33, or rely on "≥2 stuck" and remove the notional trigger), distinct from the admission fraction. State both numbers in the prereg. Make the CONTRADICTION trigger sticky, latched until an operator reset, so it cannot flap when a later read clears it.

## Status of my r1 findings

| r1 | Status |
|---|---|
| H-1 day-roll hole | Resolved in design: open bookings convert to uncharged entries at the roll, the invariant is restated, and there is a test. Residual MEDIUM-2 below. |
| H-2 re-book gaps | Resolved except permit seeding (HIGH-2). Zero-fill boot, context-less slot, no-crash and over-budget-with-live-resolver are all covered. |
| H-3 breaker | Numbers are frozen, CONTRADICTION counts as stuck, there is a duplicate-order test, and a tripped breaker never blocks the resolver. Residual: HIGH-4. |
| H-4 in-flight id | Resolved (frozenset, with a concurrent-POST test). |
| M-1 same-slug bleed | Partial: MEDIUM-1. |
| M-2 concentration | Resolved as telemetry plus the first-5s arm, with no new cap. Acceptable. |
| M-3 viability | Mostly resolved: bootstrap CI on the upper bound, throttle-as-drop, free-balance arm. Residual: MEDIUM-3. |
| M-4 K frozen | Resolved in §8, but see MEDIUM-4. |
| Pre-registration | Resolved in direction. Scope gaps in MEDIUM-4. |

## Direct answers to the focus items
- **Open question 4 (cross-day fill):** ignoring a prior-day fill for budget is consistent with the existing "spend is gone" design. It matches the seed's own `ts_event` day filter, so it is acceptable. Add a test for a fill timestamped just before 00:00Z and resolved just after.
- **§3.6 stuck numbers:** 720 s (with-id) and 900 s (no-id) against observed resolutions of 3–144 s, with 2 of 39 never resolving, are sensible. Tripping at ≥2 stuck is right for the first deployment. The duplicate-order test (`delta > wire quantity`) fails closed on manual trading, which is acceptable (open question 8).
- **Open question 5 (unreadable slot):** safe, because admission quarantine denies everything. Add an alert on the first unreadable slot. Alerts that reach nobody have cost this project days before.
- **Open question 7 (marker stat inside `arm_slot`):** acceptable. flock is already blocking I/O there.
- **§6 stop rule:** acceptable. A 95% upper bound on a 33-day p90 is wide and biased toward STOP, which is the safe direction.

## MEDIUM
- **MEDIUM-1. The cool-off is inconsistent and not restart-safe (§3.8).**
  - §3.1 puts `"cooloff":{...}` in the durable v2 table, while §3.8 says it lives in process memory. A downgrade to a v1 record also drops it.
  - The justification for a memory-only cool-off, "the strategy's durable `_REARM_MIN_DELAY_SECS` covers restarts", holds only for the rung-hold family. The FQ latch is a different latch. Intents retired by the boot-time first resolver pass (F14 step 1) happen before any in-memory cool-off exists.
  - 120 s equal to the zero-fill floor is reasonable. The no-id route retires later, at ≥300 s plus feed lag, so consider 120 s measured from the retire time and not the creation time. State which.
  - Required change: choose one. Either make it durable and put it in the v2 table with a v1 extra key on downgrade, or state that boot-retired slugs get a synthetic cool-off from boot time.
- **MEDIUM-2. Lazy day roll and settle.** The conversion to uncharged runs only inside the next `authorize_order_cost`. Between 00:00Z and the first new-day authorize, the ledger's `_day` is stale, and the existing `release_booking` and `true_up_booking` raise for a prior-day booking. Specify what `settle_open_exposure` does in that window, and add a test: settle after the roll but before the next authorize. Also, `_unbounded` is described as a single flag. It must be per-key (a set or count) so retiring a context-less slot clears it, and two such slots don't clear it early.
- **MEDIUM-3. Free-balance arm direction (§6.1).** The model reduces free balance at accepted-fill time and never for AMBIGUOUS orders. The conservative arm is the opposite: an AMBIGUOUS order may hold buying power for its whole stuck lifetime. Run both arms and let the stop rule use the worse one. Also add the exposure bound (HIGH-3) to the simulation.
- **MEDIUM-4. D-PREREG scope (§8): direction right, content incomplete.**
  - It says K is frozen, yet the ramp starts "for example K=2 first". Freeze the whole K schedule and the promotion criteria now, or the schedule contradicts the freeze.
  - Add:
    - the admission fraction and the breaker fraction as separate values (HIGH-4);
    - the observed AMBIGUOUS rate, and the halt rule if it exceeds the Wilson-upper 0.33;
    - fill-price versus screen-ask slippage tolerance and fee parity, since the screen scored drops as losses and parallel execution adds fills;
    - NO ≥ 0.90 hold-time re-measurement as a ramp stage gate, because the build gate used YES inputs (R10);
    - concentration thresholds for the first-5s deployed budget fraction, as telemetry-based stop criteria.
  - Add a statement that it is independent of `PREREG.json` and uses no data from 2026-10-07 to 11-28.

## LOW
- Boot ordering (F14): the first resolver pass runs before the seed span. A fill that pass resolves is durable and is counted by the seed, so it cannot be double-counted. Add the interleaving to the exactly-once property test.
- Quarantine denies exits as well. That matches today's `is_latched`, but say so explicitly in §3.7.
- Open questions 1 and 6 are acceptable as answered (gate position keeps the `<` chain; cool-off see MEDIUM-1).

## Required for r3
1. Add the ledger pre-check before the permit spend (HIGH-1).
2. Drop permit seeding with open notionals (HIGH-2).
3. Make the admission bound AMBIGUOUS-only, or add it to `admit` and the WP0 simulation (HIGH-3).
4. Separate the breaker fraction from the admission fraction and make the CONTRADICTION trigger sticky (HIGH-4).
5. Resolve the cool-off storage inconsistency, the lazy-roll settle, the free-balance arm direction, and the D-PREREG content.

Files reviewed:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r2.md`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (:6238-6285, :5413)
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/safety.py` (:799-902)
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py`
