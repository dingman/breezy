# SIZE-UNDER-CAPS plan r4 — delta over r3 (architect re-review 2026-11-02: 3 open items; prediction-market r3: APPROVE, 2 S0 notes folded)

Applies on top of `plan_r1.md` + `plan_r3_delta.md`; where they differ this delta wins. Status: r4 — architect confirmation pending.

## R4-1 Read all three caps before applying any
In `authorize_order_cost` the `:538` comment becomes "Read ALL THREE before applying ANY"; `month_cap = operator_max_monthly_budget_usd()` (name frozen by OPERATOR-CONTROLS-MONTHLY-CAP r1) is read immediately after `:541`, before the `:543` check. RED test `test_missing_month_cap_refuses_like_missing_day_or_position`: with MONTH unset the order is refused with the SAME error type as a missing DAY or POSITION cap and nothing is booked.

## R4-2 Maker remaining quantity has a home
§3 gains `ladder_state.py:57,100`. `Rest` (`:57-67`) gains `remaining_qty: Decimal`; `Ladder.departed` (`:100`) becomes a `(cents, qty, frame)` tuple; `remaining_qty` is cut on each partial `OrderFilled`; that value (never `ORDER_QTY`) is passed at `strategy.py:524`/`:531` to `own_excluded`. RED test `test_own_excluded_depth_equals_remaining_resting_qty` (partial fill, then own-order exclusion).

## R4-3 Position-cap check under the lock, cumulative, restart-safe
The per-order `:543` comparison moves inside `with self._lock` next to `:561` and becomes a cumulative headroom check: committed cost of the open position (prior fills + live rests on the same instrument/leg) + this order ≤ position cap. The running total is NOT a new persistence unit: at boot it is re-seeded through the same durable-fills walk that seeds daily spend (`_seed_spend_from_durable_fills`) plus the resting sweep already performed at startup; the plan's "no new persistence unit" line stands. RED test `test_two_orders_each_under_position_cap_but_together_over_are_refused`.

## R4-4 (PM S0 notes) `c_guard ≥ max over admissible q of (p_bar(q) + fee_total(q)/q)`, rounded up; it is a clamp bound only and the final test uses exact `fee_total(q)/q`. Gross commitments and `H_B` are fee-inclusive Decimal USD; S0 names the reconciliation with the monthly ledger's pre-fee unit as a deliverable with RED test `test_pre_fee_month_ledger_never_overstates_headroom`.

## R4-5 Housekeeping: "UNVERIFIED" tags in §3 and the "CodeGraph unavailable" line in §9 are removed; all locators were confirmed by the architect (strategy.py:159-160/524/531/681; operator_controls.py:540-541/543/561-569).
