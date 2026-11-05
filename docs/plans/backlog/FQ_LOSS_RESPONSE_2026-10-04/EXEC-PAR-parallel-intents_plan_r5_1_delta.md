# EXEC-PAR r5.1 delta (errata to r5): coordinator, 2026-10-10

This delta applies on top of `EXEC-PAR-parallel-intents_plan_r5.md`. Where they conflict, this delta wins. It closes the three r5 final-check findings:

- `reviews/EXEC-PAR-r5-review-{market,safety,architecture}.md`: market READY 91, safety 84 (1 HIGH), architecture 90 (1 HIGH).
- No other part of r5 changes.

## E1. Settle ordering at the zero-fill and no-id sites (safety r5 HIGH-1)

**Defect in r5.** `_retire` ran an idempotent `settle` that removed the charged entry before the handler's own `settle`. The handler's call then saw an unregistered key carrying a booking, which raises by r5's own contract. That raise skipped the cancel, the permit restore and the AMBIGUOUS clear.

**Ruling:**
- **All six post-booking sites call `settle` BEFORE `_retire`:**
  - resolver: zero-fill, accept-fill and no-id;
  - post-POST: accept-fill, zero-fill and reject.
  - This changes today's order at the zero-fill site (`client.py` ~:3223-3231) and the no-id site (~:4070-4072). Each now does `get` booking → `settle` → `pop` booking → `_retire` → the rest of the body, unchanged.
- **`_retire` makes no ledger call.** The `_retire`-time `settle` from r5 is removed.
- **Leak backstop.** `_retire` asserts nothing; it reads `has_open_exposure(key)`. If an entry is still open after a handler retires, `_retire` logs ERROR once and counts it via `_note_resolver_error`. The entry stays, which is conservative because headroom stays held.
  - Test: `test_every_retire_path_leaves_no_open_exposure`, a property over all retire paths.
- Tests:
  - `test_zero_fill_and_no_id_settle_before_retire_then_cancel_restore_clear_no_raise`
  - `test_zero_fill_releases_headroom`

## E2. Abandon is a separate, non-raising call (architecture r5 condition 1)

- Add `DailySpendLedger.abandon_open_exposure(key) -> bool`. It removes the entry if present and adds no spend. A charged booking stays charged, which is conservative. It **never raises** and returns whether an entry existed.
- The accept-fill integrity-error path uses `abandon_open_exposure`, not `settle(booking=None, ...)`. The `settle` contract is unchanged: a registered charged key with a mismatched or absent booking still raises.
- New named resolver-allowlist row: `self._ledger.abandon_open_exposure`. Check it against the banned-word scan.
- `test_settle_over_cost_retry_does_not_self_heal` must assert that abandon was called, that no raise escaped, that the UNBUDGETED latch was reached on the over-cost path, and that no later pass adds the realized amount.

## E3. Over-cost wording (market r5 §9 Q1)

Replace r5's "the authorized cost stays charged, which is conservative" with the following:

> For an over-cost fill (realized > authorized), the day's in-process spend undercounts by (realized − authorized) until respawn. This is harmless because the global DURABLE UNBUDGETED latch halts all trading, and the respawn seed counts the durable fill record.

## E4. Exits never enter the exposure registry (architecture r5 HIGH)

- **Arm time:** register only when `not is_exit_side`. Exits never call `authorize_order_cost` (`client.py` ~:6272-6274) and never debit the daily counter.
- **H6 boot:** register only when `context.order_side != "SELL"`.
  - A legacy context without `order_side` is treated as BUY. This matches the existing `test_legacy_context_without_order_side_refuses_as_a_buy` semantics and errs conservative.
- **Defence in depth inside the ledger:** `register_open_exposure` takes a keyword `side`. It refuses (raises) on `side == "SELL"`.
- **Totals:**
  - `uncharged_open_total` and `ambiguous_open_total` therefore count BUY entries only.
  - `mark_ambiguous` on an unregistered (exit) key is a no-op.
- The exactly-once property (r5 §3.5) is BUY-only by construction. State this in the property docstring.
- Tests:
  - `test_exit_fill_never_adds_daily_spend_or_exposure`, at K=1 and at K>1
  - `test_stuck_exit_does_not_count_toward_f_adm_or_f_breaker`
  - `test_register_open_exposure_refuses_sell`

## E5. Create-path accept-fill failure (safety r5 non-blocking note)

**Behaviour.** At ~:6467 a `settle` raise still escapes the task, as today. Because bookings are now get-then-pop, the booking and the registry entry remain. The intent stays OPEN. The resolver's next pass then takes the same accept-fill path, hits the same integrity error, and takes the E2 abandon, retire and latch path.

**Outcome.** The two paths converge on the same visible end state within one poll. No new `_refuse` site is needed.

Test: `test_create_path_settle_raise_converges_to_resolver_latch`.

## E6. Bucket guard units (market r5 §9 Q4)

- The frozen D-PREREG bucket label, the boot guard (r5 §3.9) and the activation re-run (r5 §6) all use **one unit: per-position cap / daily budget**.
- The activation re-run evaluates the stop rule at cost = cap.
- A ratio above 0.50 maps to a sentinel label `>0.50` that orders above every bucket, so it always forces K=1.
- WP0 prints the per-bucket order-cost distribution in both units: realized cost / budget and cap / budget.
- Tests:
  - `test_bucket_label_above_0_50_is_sentinel_forcing_k1`
  - `test_frozen_label_and_guard_share_cap_over_budget_units`

## E7. Restart forced to K=1 over an open v2 table (market r5 note)

**Requirements:**
- Resolver selection (`next_open_for_resolution`) does not depend on `max_slots()`.
- A node that boots with K forced to 1 over a v2 table left by a K>1 run still resolves every open slot.
- Admission denies all new entries until ≤1 slot is open. This follows from `admit(k=1)`, which denies while any slot is open.
- The table downgrades to v1 on drain.

Test: `test_restart_with_k_forced_1_over_open_v2_table_resolves_all_slots_and_downgrades`.

## E8. Focused-list addition (safety r5)

Add `test_polymarket_us_exec_client.py` (~:4735, the discovery-clock `ts_event` pin) to WP4's focused list. It must stay green under the shared-stamp change (r5 M5), with an injected fixed clock.

## Allowlist delta vs r5

- Resolver coroutine: add `self._ledger.abandon_open_exposure`.
- Nothing else changes.

## E9. Settle raise at the zero-fill and no-id sites (architecture r5.1 MEDIUM-a)

**Problem.** Under E1 the `settle` raise at these two sites now comes before `_retire`. Without handling, the intent would stay OPEN forever.

**Rule.** These sites mirror the E2 failure path:
- On a `settle` raise, call `_note_resolver_error`, then `abandon_open_exposure`, then pop the booking, then `_retire`.
- The cancel and the permit restore still run.
- The AMBIGUOUS clear is skipped, as today, which is the conservative choice.

**Test:** `test_zero_fill_and_no_id_settle_raise_abandons_and_retires`.

## E10. Create-path convergence, made concrete (architecture r5.1 MEDIUM-b)

This supersedes the E5 mechanism. The E5 claim is not relied on, because the create-path context carries no venue order id, so the resolver would take the no-id route rather than accept-fill.

**Rule.** The create-path accept-fill catch (~:6467) does the following on a `settle` raise:
1. Logs ERROR.
2. Calls `abandon_open_exposure`.
3. Pops the booking.
4. Re-raises, as today. The intent stays OPEN.

**What the resolver then does.** The next resolver pass, on whichever route it takes (no-id adoption or with-id), finds an unregistered key with no booking:
- `settle(booking=None)` returns False (a no-op), so `registered` is False and `booking` is None.
- The existing single UNBUDGETED producer therefore latches.
- No new `_refuse` site is needed.

**Test:** `test_create_path_settle_raise_converges_to_resolver_latch` must drive the real route:
- a pre-POST context with no venue id;
- the no-id adoption, after the 300 s floor, of the recorded fill;
- the assertions: the latch is reached, the intent is retired, and no spend is self-healed.

## E10′. Create-path convergence via the with-id route (supersedes E5 and E10; safety r5.1)

**Facts (safety r5.1):**
- The create-path booking at ~:6467 is local to `_submit_order`. It is never in `_ambiguous_bookings`.
- The pre-POST context has `NO_VENUE_ORDER_ID`, so a resolver would take the 300 s no-id route.
- That route has no reliable latch, and could retire the order as NO_FILL against the already-recorded fill.

**Rule.** On a `settle` raise at the create-path accept-fill site, before re-raising, do these steps in order:
1. Log ERROR.
2. Call `abandon_open_exposure(key)`. The key is now unregistered.
3. **Upgrade the context to with-id** via the existing `_note_ambiguous_open` with-id overwrite (the same call already made at ~:6628 inside `_submit_order`, so it is already permitted; no new callee). The upgraded context carries the venue order id from the POST response.
4. Do **not** put the booking into `_ambiguous_bookings`.
5. Re-raise, as today. The intent stays OPEN.

**Why the latch then fires.** The fill record is already durable and the intent is now with-id. On the next pass after the 120 s floor, the resolver takes the with-id **accept-fill** path:
- `settle(booking=None)` on the unregistered key returns False (a no-op);
- so `registered` is False and `booking` is None;
- so the **existing single UNBUDGETED producer** (~:3466) latches, and the intent retires.

No new `_refuse` site is added.

**Test.** `test_create_path_settle_raise_converges_to_resolver_latch` must drive the real resolver after the floor, with the durable fill present. It must assert:
- the with-id route is taken;
- the latch is reached;
- the intent is retired;
- no spend self-heals;
- timing ≤ floor + one poll.

## E11. Registration failure after `arm_slot` (safety r5.1 MEDIUM, E4)

`register_open_exposure` runs after `arm_slot` and before `_note_ambiguous_open` and the POST. If it raises (a bug, for example the SELL refusal firing on a mis-tagged side):
1. Release the booking (same-task, no `await`; the existing pre-POST release pattern).
2. Retire the just-armed slot.
3. Deny the order.

It never POSTs.

**Test:** `test_register_failure_after_arm_releases_booking_retires_slot_no_post`.

## E12. Documented side effect of E1 + E9

With E9, a same-day integrity error at the zero-fill or no-id site abandons the entry and retires the intent; it does not leave the slot stuck. The event is visible through the ERROR log, the resolver error count, and the stale-intent alert path. These two sites have no latch producer, which is unchanged from today.

## E13. E10′ and E11 conditions from the safety r5.1 final check (binding)

### E10′ timing
- An accept-fill is resolved on the first pass after the GET shows FILLED.
- The 120 s floor gates only the terminal zero-fill branch.
- Convergence therefore takes at most one poll. The test asserts that bound, not "floor + poll".

### Degraded fill record (documented)
- The resolver rewrites the fill record with a synthetic one: `fee_reconciled=False` and the discovery time.
- This is accepted for this rare integrity-error case.

### The `_note_ambiguous_open` call in the E10′ path
- Pass `register_booking=False` and `booking=None`, so no stale booking enters `_ambiguous_bookings`.
- Wrap the call in `try/except`. A store failure must not mask the original exception.
  - If the upgrade fails, log ERROR.
  - The intent then stays no-id and falls back to the 300 s route.

### Emit `OrderSubmitted` before re-raising
- Call `self._generate_submitted(order, now_ns)` (already allowlisted) before re-raising.
- Without it, Nautilus drops the resolver's `OrderFilled` on an INITIALIZED order.

### E10′ test assertions
The test asserts:
- `OrderSubmitted` is emitted exactly once;
- `OrderFilled` is emitted exactly once;
- the durable record is rewritten with the documented degradation.

### E11 retirement reason
- The slot retired in E11 uses the existing `DEFINITIVE_REJECT` reason.
- No new reason is added, since a new one is gated by the supervisor decode marker.

## Status

Final peer verdicts on r5 + r5.1:
- architecture: READY 92;
- market: READY 91;
- safety: READY 91.

**The plan is READY.** Build order: WP-DR (merging) → WP0 → WP1 → WP2 → WP3 → WP5a → WP4 → WP5b → WP6 → WP7.

K stays 1 until D-PREREG is frozen and WP0 and the activation gates pass.

## E14. WP4 review rulings (coordinator, 2026-10-10)

1. **Settle failure at zero-fill/no-id (E9).** The AMBIGUOUS refusal stays latched (fail-closed). This must be visible:
   - log an ERROR that names the stuck refusal and its slug;
   - expose a client counter, `stuck_refusals_after_settle_failure_total`.
2. **Resolver fairness.** A slot's failure penalty in `next_open_for_resolution` expires once the slot has had no new failure for 300 s (the global backoff cap). Within that window, failing slots are ordered after healthy ones. After it, ordering is by last-served, then created. Required test: no slot waits more than (K × poll) + 300 s while healthy slots cycle.
3. **Post-booking settle sites (zero-fill terminal, reject, and the pre-POST context-failure handler).** Each gets a local guard in the E9 pattern:
   - log ERROR, `abandon_open_exposure`, then retire (or deny, pre-POST);
   - in the pre-POST handler the ORIGINAL store error is preserved and re-raised or denied as today; a secondary settle error is logged, never substituted.
4. **E10′ hardening.**
   - `abandon_open_exposure` sits inside the guarded block.
   - A test proves the resolver's `record_fill`, with its synthetic trade id, is idempotent against the create-path record (no double fill record).
   - If the with-id upgrade fails, the no-id route must NOT retire as NO_FILL while a durable fill record exists for the intent. Add the guard if it is missing, and a test.
5. **`contradiction_events_total`** counts:
   - DUPLICATE_SUSPECT trips;
   - holding-bearing contradictions: `unexplained_holding*`, and terminal-zero with a LONG holding and no fill.
   
   It does NOT count ordinary consistent holding deltas. Fix the docstring. Add a test for an event that is observed and then retired: it is still counted, and the counter is monotonic. Manual trades that trip it fail closed (§9.8, accepted).
6. **Permit session notional for boot-registered fills** is NOT debited. Recorded as accepted:
   - it is bounded by `f_adm × budget`;
   - the daily ledger counts it;
   - D-PREREG must restate it.
7. **The duplicate detector also acts at K=1.** That is more conservative and accepted. Document it in the K=1 differential notes. The consecutive-pass counter resets on an INCOMPLETE pass.
8. **Early return on `is_open_intent == False`:** call `abandon_open_exposure` before returning, so no registry entry leaks.
9. **Leak backstop counter.** The direct `_resolver_error_count` increment is kept if routing it through `_note_resolver_error` would need a new callee; a comment says why. The pin comment on `SUBMIT_PREFIX_SHA256` cites "EXEC-PAR r5 §5 WP4 + r5.1 E14", not "reviewer-approved". The six repeated failure-counter increments get a comment naming the SIM401/callee constraint.
