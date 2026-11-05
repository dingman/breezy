**Verdict: NOT-READY (confidence 74/100).** The direction is sound: slot key, K=1 default, behaviour-neutral merges, and WP0 as a hard gate. But r1 over-claims the exposure invariant, leaves the breaker unspecified, and misframes the pre-registration question. I made no edits. I read nothing dated on or after 2026-10-07, and I did not open `docs/evidence/m1v3/`, so §5's numbers are reviewed from the plan text only.

## HIGH

**H-1. "AMBIGUOUS counts at full notional until retired" is false across the UTC day roll.**
- Evidence:
  - `DailySpendLedger.authorize_order_cost` (`operator_controls.py:403-417`) drops prior-day bookings and resets `_spent_usd = 0` when the day changes.
  - `_require_open_booking` (:443) refuses to release or true-up a prior-day booking ("the spend is gone").
  - The plan's own stuck order (96,824 s, about 27 h) therefore stops counting against the budget at 00:00Z while its slot and exposure persist.
- Failure: with a serial latch this was at most one cap of uncounted exposure. With K=6 and up to ceil(K/2)-1 = 2 stuck slots below the breaker, up to 2 × cap is uncounted on the new day. After a restart the plan's re-booking path has the same problem.
- Required change:
  - State the true invariant: per-UTC-day submitted notional ≤ budget, plus open-AMBIGUOUS notional carried across the day roll.
  - Add a RED test for an AMBIGUOUS booking across 00:00Z.
  - Implement either a carried-over floor (`ledger.seed_spent` or a new carry-in of all OPEN notionals regardless of creation day) or a stuck-slot count that is deducted from admission headroom.
  - Reword F13/§3 ("the in-process ledger already satisfies the invariant"), which over-claims.

**H-2. The WP3 restart re-booking has gaps the plan does not name.**
- Evidence:
  - `_seed_spend_from_durable_fills` returns early when `count == 0` (`client.py:2422`) and `seed_spent` is one-shot (`_seeded`). Adding open-intent notionals to the fill total must run even when there are zero fills.
  - Re-booked notional has no `SpendBooking`, so a later zero-fill retire cannot `release_booking`. Budget is lost for the day. That is conservative, but K × cap can silently starve the day.
  - The arm-to-context-write window is real: step 5 `arm` precedes step 6 `_note_ambiguous_open`. A crash in between leaves a context-less slot. The plan's "assume full per-order cap" is right, but it calls `operator_max_position_cost_usd()`, which raises if the control is unset. That branch must resolve to deny-all, not to a crash.
  - If re-booked open notional plus fills already exceeds the daily budget, the plan says `_intent_reconciled` stays False. It must also be shown that the resolver still runs in that state, or those slots can never retire and the node deadlocks, the same shape as the 09-24 terminal-leaves deadlock.
  - A with-id partial fill is counted twice (open notional plus its durable fill). That is acceptable if it is documented as conservative.
- Required change: add RED tests for each of these cases: zero fills with open slots, an open slot with no context, over-budget on boot with the resolver still live, and the double-count.

**H-3. The breaker is unspecified, and it is the only bound on K stuck slots.**
- Evidence:
  - Open-notional trip: "a stated fraction of the daily budget". No number is given.
  - Duplicate-order signal: no definition. With no client-order-id, the only available definition is a holdings delta exceeding the expected delta.
  - Stuck definition: §3 says "age > floor + 600 s", but the sample has 2 never-resolved orders out of 39 posted (about 5%), and 1 of the 7 AMBIGUOUS orders stuck for 27 h.
  - The stuck rate compounds: at roughly 10 candidates a day, expected stuck slots are about 0.5 a day. Stuck slots only leave through an operator clear, so K=6 with a trip at 3 trips in roughly a week.
  - Trip at ceil(K/2) is too lax for the first rollout.
- Required change:
  - Freeze concrete numbers in the plan.
    - Stuck definition: an AMBIGUOUS slot older than the floor plus 600 s.
    - Trip at ≥ 2 stuck slots for the first K>1 deployment.
    - Open-AMBIGUOUS notional ≤ one stated Breezy-owned fraction of the daily budget, derived at runtime from the ledger and never assigned as a cap.
    - A defined duplicate-order test.
  - Count a CONTRADICTION outcome as stuck. Show that a tripped breaker still allows the resolver to retire slots.
  - Resolve the open question on a second unresolved-notional bound: yes, add it. The ledger bounds spend, not open AMBIGUOUS exposure (see H-1).

**H-4. `_post_in_flight_intent_id` is a K>1 correctness hazard, not just an open question.**
- Evidence: it is a single field set at `client.py:6325` and cleared in the `finally` at :6349. Slot B's POST completing clears the guard while slot A's POST is still in flight. The no-id path uses it at :3747 to skip an in-flight intent.
- Failure: the only backstop is the 300 s no-id floor, against a POST that may stall on a transport timeout. Whether a stall can outlast 300 s needs checking against the sender timeout. If it can, the resolver could classify a live POST as zero-fill and release its booking, producing a doubled position.
- Required change: make the guard a per-intent set, in WP4 H-hunk scope, with a RED test (concurrent POSTs, the first still in flight after the second completes, resolver skips the first). Do not leave it to "audit readers".

## MEDIUM

**M-1. Attribution (risk R1): cross-slug contamination is not the issue; same-slug temporal bleed is.**
- Evidence:
  - The no-id baseline is the slug-level `netPosition`, plus the instrument's durable net, the wire echo, and `manual_leg_net_effect(slug=echo.slug, ...)` (`client.py:3858-3913`).
  - Two different slugs on one station or event do not share holdings, so a station-day correlation does not cause misattribution. The plan's per-slug claim is correct.
  - The residual risk is a late fill. An order that is zero-fill-classified at 120 s but fills afterwards lands while a new slot on the same slug is already armed. Its baseline then folds the old fill into the new delta, which gives a false CONTRADICTION (safe) or, worse, a false match.
  - This risk already existed under the singleton, but K>1 allows the same slug to be re-armed sooner relative to other activity.
- Required change:
  - Add a WP7 test for a late fill after zero-fill retire, then a re-arm on the same slug.
  - Consider a per-slug cool-off after a zero-fill retire (beyond `_REARM_MIN_DELAY_SECS`) so the baseline is read only after settle.
  - Also test that an exit SELL sharing the base-slug slot with an entry is serialised in both orders.

**M-2. Correlation and concentration: the slot key is correct for attribution, but concentration needs reporting.**
- The base slug is the right unit. A coarser station-day key would contradict the 2026-09-14 operator ruling, and the YES/NO legs of one market must share a slot because the venue nets NO as short YES.
- Concentration is asymmetric. With mutually exclusive rungs on one station-day, NO baskets have a max loss of one leg (at most one rung can resolve YES). YES baskets lose the sum of costs minus one payout. The plan must state worst-case station-day loss per side so the operator is not surprised, and must not turn it into a new cap.
- The 5/s bucket and clustered arrivals mean 42% of candidates land within 5 s. That is a model-cycle repricing event, correlated across stations. Parallelism lets the whole daily budget deploy into one correlated instant, which changes the "single-day stop" semantics. Add station-day and cycle-clustering exposure telemetry, plus a WP0 arm that shows the daily budget fraction deployed in the first 5 s.

**M-3. Viability simulation (§5): sound in structure, weak as a go/no-go.**
- Method issues:
  - With about 10 candidates a day over 33 days, d̂_p90 is roughly the 3rd-worst day on tiny, quantised per-day shares. Report the bootstrap CI on p90 or add a pooled share, and set the STOP rule on the CI upper bound.
  - First-row-only, take-all candidates, with no timestamp ties, understate same-slug collisions (ladder retries of one rung) and overstate fill opportunities.
  - The K=1 reproduction (p0 → 0.491) is a good regression anchor. Keep it.
  - The acceptance condition "p_amb = 0.33 with one stuck slot" reduces K=6 to an effective 5, which is above the table's K=4 (0.203). It passes, but the table itself does not yet include the 5/s bucket or the stuck-slot arms. Do not rely on K=6 until they run.
- Caveats: n_amb=7 and YES-only, low-price hold inputs are not disqualifying for a build gate. The Wilson-upper p_amb already covers the small sample. They are disqualifying for any claim about NO≥0.90 ambiguity or hold times, because those inputs come from an off-population sample. R9 is correctly deferred, but the plan must say the result is a build gate only.
- The native 5/s `max_order_submit_rate`: verify in WP0 whether Nautilus queues (Throttler) or denies. A queue adds delay and staleness to IOC limits. The plan only says "denies" in R8.

**M-4. K=6 is a Breezy-owned constant, not an operator cap. That is acceptable.** Do not tie it to the budget or the position cap. Require the K constant to be frozen before any 12-07 read, so it cannot be tuned post-hoc.

## Pre-registration (open question 9)

I disagree with the plan's "no". Building the capability needs no prereg (it makes no screen claim and `PREREG.json` stays untouched). Trading a 12-07 WINNER through it does. The shelving ruling requires "a new plan and prereg for a different execution design". The screen scored drops as losses (conservative), while parallel execution fills the dropped candidates and changes slippage, timing, ambiguity mix, and rate-limit behaviour. None of those is validated by the screen.

Required: before the 12-07 read, freeze a separate execution-design prereg. It covers K, the breaker thresholds, the stuck definition, and the live-small ramp and stop criteria under parallel execution. It must never be edited after the read. The plan's own text should record that WP0-WP7 are a capability build only.

## LOW
- L-1: Add a rollback drill for the v2 tombstone. A stranded operator is the risk if `probe_open_intent_resolvable` returns False on a tombstone, so test that the operator can clear it. The tombstone-versus-mirror choice is reasonable.
- L-2: Round-robin resolution latency of (K−1) × 5 s is immaterial against the 120 s floor. Per-intent failure counters (H7) are required, as the plan says, because of the global backoff.
- L-3: `_refuse` with a keyword-only slug may still shift ordinals in `test_exec_refusal_health_surface.py`. Verify in WP4 before the pin moves.
- L-4: The "no await between the H1 check and `arm_slot`" argument is fragile. Make `arm_slot`, which holds the mutex and flock, the sole arbiter. A race loser must release both its booking and its permit slot (the F8 waste).

## Verified clean
- `authorize_order_cost` is atomic under one lock, and Decimal throughout. The cost check against the position cap precedes the budget check. Both controls are read before either is applied.
- Operator caps are only read, never assigned.
- K=1 is bit-identical to today's behaviour, so every merge before the final proposal is behaviour-neutral.
- Nothing in the plan enables orders. The `allow_short=False` invariant is untouched.

Relevant files:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r1.md`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py`
