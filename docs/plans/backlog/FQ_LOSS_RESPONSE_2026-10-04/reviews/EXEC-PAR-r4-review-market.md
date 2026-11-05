**Verdict: READY (87/100).** All of my r3 findings are resolved in design. The remaining items are MEDIUM or LOW spec edits that don't change the architecture, and none of them blocks WP-DR or WP0 starting. Two or three of the MEDIUM edits should be made before WP3/WP0 begin.

## r3 findings: status
| r3 finding | r4 status |
|---|---|
| HIGH-1: `qty_est` wrong on the NO leg | Resolved. §3.6 uses `Decimal(wire_quantity)` directly with no price division. F10 cites `submit_chain.py:363-373`: the wire price is YES-denominated and the body quantity is hard-coded to 1. Eight per-leg tests run at price 0.08 and 0.92. |
| HIGH-2: "created today" settle predicate | Resolved. `settle` adds `max(R − seeded_partial, 0)` iff the fill `ts_event` day equals `eff_day`, which is the seed's own predicate (F13). The correct reasoning: resolver fills are stamped with discovery time (`client.py:3383`). |
| MEDIUM-1: unreadable-caps worst-bucket STOP | Resolved. Per-bucket reporting, with no worst-bucket fallback (but see M-1 below). |
| MEDIUM-2: arm from empty drops cool-off | Resolved by `test_arm_from_empty_preserves_unexpired_cooloff`. |
| MEDIUM-3: D-PREREG gaps | Resolved. §8 now carries the reset procedure, M1-v3 independence, the WP0 hash with its CI, the cool-off scope, and the detector definition. |
| Open questions 4 and 5 | Answered: synthetic boot cool-off for every slug OPEN at boot, and `L_feed` else 300 s with confirm-twice. |

The WP-DR spec matches what I required. There is no blanket `except`, same-day integrity errors still raise, and the prior-day accept-fill fails closed through the existing UNBUDGETED latch. That latch is a global DURABLE refusal at K=1, but it is rare and it clears on respawn, so it is acceptable.

## Checks requested

**§3.5 settle and the in-process = seed property: sound, with two caveats on the property.**
- The prior-day and ts-day logic is correct. A create-path fill stamped day D settling on D+1 adds nothing, and the seed also excludes it. A resolver fill stamped D+1 adds R, and the seed includes it.
- `eff_now = max(now_ns, _last_ns, _registry_last_ns)` makes stale concurrent clocks safe. Same-day integrity errors keep raising.
- Caveat 1 (**MEDIUM-2**): `test_in_process_spend_equals_seed_after_restart` will fail on fixtures the plan has not addressed. In-process `true_up_booking` rounds realized cost up to the cent (`operator_controls.py:508`). The seed sums raw `record.cumulative_cost` (`client.py:2420`). The seed also does not filter on `order_side`, so durable SELL records (INC-E2 exits) are summed into "spent", while in-process never books exits. Restrict the property to BUY records and round identically, or document the seed's pre-existing conservative bias as an accepted exception. Do not let hypothesis discover it.
- Caveat 2 (**MEDIUM-3**): `seeded_partial_usd` must be exactly the amount the seed included in its total, which is zero if the partial record's `ts_event` day is not today. If it is the raw partial P, a prior-day partial is subtracted but never seeded, which undercounts. Specify `seeded_partial = 0` when `ts_event` day is not the seeding day, and add a test with a prior-day partial and a today final fill.

**§3.6 detector, `L_feed`, heartbeat: adequate.**
- Using `wire_quantity` is correct. The threshold `delta > 1` is exact for a hard-coded quantity of 1: a normal fill gives delta = 1 and a doubled one gives 2. The constant-versus-field question (open question 5): add the field, but also assert the body quantity equals the order quantity at both call sites, so the two cannot drift.
- Side effect (**LOW-1**): the age gate is `L_feed`, with 300 s the default, but most AMBIGUOUS intents retire at about 125-144 s. In practice the detector evaluates only stuck or no-id intents. That is fine as a belt on stuck slots, but D-PREREG and R-notes should not present it as a general double-POST detector. A duplicate on a normally resolving order is only caught by the cool-off and positions reconciliation.
- Heartbeat 60 s against a 5 s poll (12 polls) is fine. **LOW-2:** write the heartbeat only after a poll that fully evaluated every trigger, not at poll start. A watcher that reads the client properties, raises, and still beats would defeat the fail-closed design. Add `test_heartbeat_not_written_when_poll_evaluation_raises`.
- It also guards only the watcher task, not the node process, which is correct since a dead node submits nothing.

**§6 cost/budget gate: partly gameable (MEDIUM-1).**
- The build gate passes if some bucket passes at K ≤ 8. The ≤0.02 bucket makes `f_adm` irrelevant (ambiguous notional never reaches 50% of the budget), so nearly any K ≥ 4 passes there. The build gate is therefore close to vacuous whenever the bucket is unreadable.
- The harm is bounded: the activation gate re-runs at the actual bucket, and K defaults to 1.
- But the activation gate is procedural. The caps are operator-reserved and can change after D-PREREG freezes K. A budget or cost change that moves the real ratio into a failing bucket would not be caught.
- Required changes:
  - Freeze the passing bucket label in D-PREREG.
  - Add a machine check at node boot: when K>1, the node reads the existing readers and derives the bucket label only. It forces K=1 and alerts if the bucket exceeds the frozen passing bucket.
  - Optionally restrict the build-gate pass to buckets ≥0.05 so it is not satisfied by the trivial bucket.
- WP0 should also print, per bucket, the distribution of actual order-cost values (the per-order cost is price × 1 contract), since the bucket input is realized cost and not the cap.

**§8 D-PREREG: complete in structure.** The remaining gaps are all MEDIUM:
- **MEDIUM-4:** no live check of the simulation. Add a stop criterion for the realized dropped-candidate share (OpenExposureBound, K-full and throttle denials) against the 0.30 bar. Otherwise the build-gate metric has no live counterpart.
- **MEDIUM-5:** the frozen bucket label and the cap-drift rule above (suspend K>1 if the ratio leaves the frozen bucket, with no prereg edit).
- Add the heartbeat-stale event count and `cross_day_settles_total` as monitored halt or alert inputs.

## LOW
- LOW-3: `settle` increments `cross_day_settles_total`. Make sure the digest alert has a nonzero-rate threshold in D-PREREG, not just a counter.
- LOW-4: the pre-check and in-lock `OpenExposureBoundExceeded` race is benign (a plain deny, and the permit slot may burn once). Say so in the test notes and add `test_inlock_bound_race_after_passing_precheck_is_plain_deny`.
- LOW-5: the rollback note (§7.4) is correct that old code makes the breaker inert. Add this to the K=1-at-rollback step: verify `entry_halt` and the heartbeat keys are cleared or ignored by old code, so a stale halt flag cannot persist undetected.

## Open questions
1. D1 is an acceptable, non-weakening supersession: it replaces WP-DR's latch only for registered intents, and the retained unregistered variant stays.
2. `L_feed` plus confirm-twice is right.
3. A 60 s heartbeat is fine.
4. The pre-POST sites can stay on `release_booking`, since they are same-task with no `await`. The plan's own AST pin should assert that no `await` occurs between `authorize_order_cost` and each pre-POST release site, not only before `register_open_exposure`.
5. Add `wire_quantity`, plus the equality assertion with the order quantity.

Files checked:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r4.md`
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/WP-DR-day-roll-settle_spec.md`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (:932-966, :2370-2429, :3372-3408)
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py` (:348-523)
