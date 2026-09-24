# AUD-06b — Round 7 (delta, post-ruling) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06b-bounded-allocation-sizing.md
sha256: 5a75991eec475c719745aebc5fa43a32d3c4b2b62f21fe2b9c940dca425a7ae0
Round: 7 (delta, post-ruling)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Source verification of the market-mechanics claims

- **`_derived_session_order_count()`** (`safety.py:591-606`): `floor(daily/position)`, `max(1, …)` —
  CONFIRMED exact.
- **`authorize_order_cost`** (`operator_controls.py:347-426`): reads both caps, refuses if
  `cost > position_cap`, then under one lock checks `self._spent_usd + cost > daily_budget` →
  `DailyBudgetExhausted` — CONFIRMED. **This function contains no order-count check at all**; the
  count ceiling lives entirely in `safety.py`'s permit budget (`remaining_order_count`, decremented/
  checked at `:1020-1026`, independent of and never read by `authorize_order_cost`). The two
  mechanisms are genuinely orthogonal, confirming "dollar ledger is the only per-day bound" as an
  architectural fact, not an assertion.
- **Durability asymmetry, confirmed exactly.** `DailySpendLedger.seed_spent` (`:306-331`): "Never
  LOWERS an in-memory total that is already higher," seeded from a durable-fill walk, at most once
  per process. `seed_permit_budget_from_prior_spend` (`safety.py:781-792`): "never touching the
  order-count budget" — CONFIRMED verbatim. A fresh mint sets `remaining_order_count` to the **full**
  derived ceiling every time (`:735-738`) — CONFIRMED. So the dollar ledger is durable across
  relaunch (reseeded from the true fill history) while the count ceiling resets to full each mint —
  exactly the per-process/per-day asymmetry both the ruling and the plan state.

## Answering the coordinator's specific questions

1. **"count ceiling = floor(daily/position), per-process, dollar ledger the only per-day bound" —
   CORRECT**, verified above at both cited modules.
2. **"Can depth/lot clamping plus 3×/day relaunch ever let spend exceed the dollar ledger?" — NO,
   and this is a property of the code, not of this plan.** `authorize_order_cost` computes `cost`
   from the actual `price_usd × quantity` of the order being authorized (whatever clamping produced
   it) and checks it against the running `_spent_usd`, which is durably reseeded at every process
   start from the true fill history. Depth/lot clamping only ever makes `cost` **smaller**, never
   larger than the cap, and the count ceiling resetting per-process cannot inflate `_spent_usd` — it
   governs a different, independent counter. Spend cannot exceed the daily budget regardless of how
   many relaunches occur or how orders are sized within the cap.
3. **§9's de-provisionalised exposure bound is right.** `min(daily budget, Σ cost_i)` with every
   `cost_i ≤ per-position cap` is unchanged arithmetic; lifting the "provisional" label is justified
   because RULING 2 keeps the count ceiling as a second, strictly conservative bound (can only stop
   the day earlier) while the dollar ledger — verified above to be the sole per-day, durable,
   relaunch-safe control — remains the binding one. The plan's honesty that the count bound is
   per-process (surviving only within one process, per residual R2-a) is accurate and does not
   contradict the "established" label, since the per-DAY claim rests on the dollar ledger alone.
4. **The first-cap-sized-order event is sufficient notice.** `ORDER_SIZED_TO_POSITION_CAP`, deduped
   to the first occurrence, announces a permanent, intentional state transition (qty=1 → cap-sized
   sizing is now active) rather than an ongoing fault condition — a one-time "this behaviour class has
   begun" notice is the right cadence for that kind of change, distinct from the re-alert ladders
   this backlog uses for ongoing failure conditions (D8/D9 elsewhere in this cluster), which correctly
   remain repeating. No defect: firing once matches exactly what addendum A2 requires and what the
   underlying event represents.
5. **No cap value is stated or implied anywhere in this revision.** Scanned the full diff: every
   reference to the two operator controls is by seam (`authorize_order_cost`, `DailySpendLedger`,
   `_derived_session_order_count`) or by name, never by figure. Confirmed.

## Regression sweep

- BLOCKER-A is untouched and correctly still stands.
- BLOCKER-B's re-grounding to AUD-18 (per the ENDORSED A1 ruling: `pm_us_crh_v4` may not send orders
  on this surface, and the edge estimate is no longer AUD-02's) is accurately reflected everywhere the
  old attribution appeared (§4, §6 G2, §7 step 0/1, §11, §12) — I grep-checked for a stray leftover
  "AUD-02" attribution in a load-bearing (non-historical) sentence and found none; the only surviving
  "AUD-02" references are in §13's historical round table, correctly left as a record of what was
  said at the time.
- The three new RED tests (count-stop distinct-reason/event, first-cap-sized-order event, no
  session-count override in shipped units) are correctly wired to the ruling's actual conditions, not
  to a broader or narrower claim than the ruling makes.
- No statistic, cap, or sizing formula is touched; this is a pure re-grounding of blocker status
  against two ruling artefacts, both independently read and verified above.

No new defect found.

## Defects

None MATERIAL, none MINOR.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — accurately reflects both rulings' scope and
  consequences with no scope creep.
- Technical correctness and evidence grounding (20): **20** — every cited line re-verified exact,
  including the architectural independence of the two per-day/per-process mechanisms.
- Implementation specificity and feasibility (15): **15** — three new tests are concretely specified
  against the ruling's exact conditions (distinct reason/event, first-occurrence dedup, override
  absence).
- Acceptance criteria and validation quality (20): **20** — AC #7e/#7f are objectively checkable and
  map 1:1 to the ruling's binding conditions.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected; the count-stop
  legibility requirement strengthens diagnosability rather than weakening any existing control.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; BLOCKER-A/B correctly
  remain the binding gates and the plan does not overstate what the rulings unblock.

**Total: 100/100**

## Required changes

None.

## Blockers (named separately, not scored as deductions)

- **BLOCKER-A** — AUD-06a's validated qty envelope and staleness predicate.
- **BLOCKER-B** — an AUD-18 CONFIRMED edge hypothesis and a newly registered family to carry it;
  `pm_us_crh_v4` may not send orders per the ENDORSED A1 ruling. Evidence precondition, not
  resolvable by any ruling or plan text.
- **BLOCKER-C, BLOCKER-D** — CLOSED build-side (D conditionally, on the `ORDER_SIZED_TO_POSITION_CAP`
  event landing) per RULING 2 + addendum A2; no longer blockers.
