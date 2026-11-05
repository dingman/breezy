# STRAT-DESIGN r1 — merged peer review (2026-10-31 ~05:30Z)

Two blind re-reviews of `design_r1.md`: trading-bot-architect REVISE (E1–E9), prediction-market-reviewer REVISE (F1–F10). §1
arithmetic VERIFIED (f = 0.91×84/119 = 0.642; B $0.078/mo; E 137×5%×$1 = $6.85, $4.83 after coverage; 2,476 fills; n=118).
Verdict: **REVISE → r2**. Binding deltas, coordinator-merged, severity order.

## G1 Fee (E1, F1) — rewrite §2, §0 R8 row, §4.B breakeven, §6
Maker Tier 1 fee = 0, no rebate (venue schedule 2026-10-19; review_r0.md R8 RESOLVED). Delete the −0.0125 tables and the
"UNRESOLVED wire sign" framing. Maker breakeven p* = b exactly (0.89/0.97/0.98/0.99); taker gap = θ·b(1−b) = 0.202/0.136/0.069¢ at
0.97/0.98/0.99. All "flips if rebate" clauses are moot; nothing reopens; the post-only refusal now rests on the `fees.py` defect.

## G2 Truth-free paths and exceptions (E3, E4, F5)
Card A: ONE `--census-only` flag on the EXISTING `wp7b_market_as_forecaster.py` main that never loads settlement/corpus and never
constructs `RungEvent` with a `settled`/`p_fc` shim (`sum_ask_row` requires both → not truth-free as written; `SumAskRow` has ask
fields only). Σbid, the pair test and BUYER-print counts are DISCLOSED EXTENSIONS of that evaluator, not new runners. Card B: one
flag on `maker_stage0_catalog_read` or the `--bench` path (never the verdict ledger); own-order exclusion by MANIFEST instrument set
covering taker fills too, not a date window. Card E: declare its Kalshi-fetch + IEM-CLI join as a NEW EVALUATOR exception (do not
write "not requested"). C and D: at most one exception each, with reasons.

## G3 Engine amendment (E2) — evaluate, do not park
State with a verdict whether Nautilus `trade_execution=True` + `queue_position=True` can consume catalog `TradeTick` through
`backtest()`; the "mis-signed maker fill" refusal is void under fee 0; the unit question is resolved by census C3, so sequence it.

## G4 Card A criteria (F2, F3, F10)
Leg 3 (HIGH/LOW pair) is vacuous (P(PASS|H0)≈1; pays 0/1/2, not a lock): require summed-ask-plus-fees < 1 under the exclusivity
payoff, or drop the leg. Leg 2 (Σbid NO basket): taker fee on the basket ≈ 0.0695·(1−Σb²) ≈ 5–6¢ → hurdle Σbid ≳ 1.075 while
published min Σask = 1.05 → only crossed/stale frames can pass: add max frame age, non-crossed requirement, state P(PASS|H0)≈0 for
legs 1–2. Sampling: "nearest 18:00Z" needs a max offset/age; "≥30 days" = station-days AND ≥7 distinct dates; state the fee-rounding
rule in `overround_with_fee`; verify Depth10 size units (not only trade_tick); set the −0.02 margin against a one-tick-per-leg slippage
bound (6–10 legs ≈ 6–10¢) before any PASS reaches the size question. Freeze a date window.

## G5 Card B (F4, F5, E6, E7)
σ = √(p(1−p)): b=0.97 → 7,240 fills for 0.5¢ (≈55,700 days), 805 for 1.5¢; b=0.98 → 4,850 / 539; 2,476 is the p≈0.99 best case.
Window must start ≥ 2026-10-19 13:00 ET (fee change) and be L-65-clean by manifest, not by date. PASS/KILL gate only on queue size
and markout is a mid change, not fill payoff: label the census "confirmatory kill of the touch-queue prior", remove the venue-wide
"ends maker variants" KILL. Move B after the cheap kills.

## G6 Card C (F6, E6)
Δmid at 120 ms on a 1¢ tick has median 0 → PASS unreachable, KILL by construction. Use cluster MEAN with a one-sided sign test or
bootstrap at α=0.05; define direction when several bands move. Window 10-14..10-23 is NOT "before own orders" (taker fills since
09-13, FQ live since 10-01): manifest exclusion.

## G7 Card D (F7)
Monetising a dead YES band = buying NO at 1 − YES bid → estimand is the YES BID, not the ask; σ=0.10 for ask levels is invented;
state P(PASS|H0) (dead-band asks ≤0.03 → KILL expected).

## G8 Card LOW (F8) — PASS as written is a coverage gate (P≈1): relabel, or reuse leg 1/2 overround hurdles.

## G9 Card E (F9, E5, E7)
"d ≥ 0.02 in each half" = ≥2 misses/59 days: at a true 1% rate P(half)=0.118, both halves same sign ≈0.007; across 24 stations × 2
sides ≈ 0.3 family-wise → Bonferroni. Pre-register ONE mechanism. Prize at the 2% PASS floor = 137×0.02 = $2.74 ($1.93 after
coverage); $6.85 is the 5% alternative; Kalshi fees absent. E is the cheapest decisive test (settles the venue question): run FIRST.

## G10 Prereg and order (E5, E7, E8, E9)
Freeze a prereg note (thresholds, windows, sha of design_r2.md) BEFORE run 1; every card gets a window (L-34). Order: E → D G0 → A
(once `--census-only` exists) → LOW → C → B. End state: never "do not open another cell"; the defined next state is the operator
size question or the Kalshi venue question (R11). Remove P4's 0.13/day and thick-touch as inputs in §6 (P4 is neither input nor output).

Accepted as-is: §1 arithmetic; §3 map additions; §4.0 checklist items C1–C5; R-table structure.
