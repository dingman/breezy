# AUD-18 — Round 6 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: 1b092bb1176d8fa445d7633bf0376a3f391bf7f5b076ab74382e64c5e150face
Round: 6 (re-confirmation after an edit made for another reviewer's MATERIAL)

## Verification

`combine_station_day`'s `variance = sum(qty*qty*q*(1-q)...)` confirmed at `current_rung_hold_v2.py:341-344`; the admission gate bounds only `sum_i q_i <= 1`, never `qty` — so the pinned `VARIANCE_BOUND=0.25` is genuinely conservative only at `qty=1`, and the fix is correctly diagnosed. `CurrentRungHoldConfig`'s `InvalidOrderQuantityError` ("order_quantity must be exactly 1") confirmed verbatim at `config.py:253-255`; `minimum_displayed_size=1`/`order_quantity=1` (`config.py:229-230`) confirm unit quantity is exactly the venue's own minimum lot, not below it — no conflict. `PREREG_WP7_MULTIPLICITY_RULE §2.2` "Quantity 1" confirmed at lines 110-113. The BE/fee formula from round 5 (`BE = a + theta*a*(1-a) + slippage`) already implicitly assumed unit quantity; this round makes that assumption explicit, pinned, and code-enforced rather than silently relied upon — a genuine strengthening, not a new gap.

Cross-checked against AUD-06b (`AUD-06b-bounded-allocation-sizing.md`): it already treats AUD-18 as the CONFIRMED-edge producer (BLOCKER-B, "AUD-06b cannot be executed until an AUD-18 hypothesis is CONFIRMED and a new family is registered") and already expects that edge denominated "USD of expected P&L per ONE contract" (`:157`). AUD-18's new "sizing belongs to AUD-06a/AUD-06b, never a licence to size" bullet is consistent with, and reinforces, that existing dependency — no contradiction found.

## Sweep of the 8 hunks

All additive and consistent: `§6.1` pinned-quantity bullet, `§6.2`'s `PINNED_ORDER_QUANTITY`/`order_quantity` field, `register_hypothesis`'s `NON_UNIT_ORDER_QUANTITY` refusal, `§7` RED (vi-f) and the step-8 ruling-input addition, `D13`'s new clause (vi), and `§12`'s out-of-scope bullet. No prior citation, number, or acceptance criterion altered or weakened; no operator-reserved value touched. No new defects, MATERIAL or MINOR.

## Score

**Total: 100/100** (20/20 · 20/20 · 15/15 · 20/20 · 15/15 · 10/10) — re-confirmed; zero material or minor defects found this round.

## Blockers

None.
