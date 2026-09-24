# AUD-18 round-8 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: 3a261176f22884b1041e85efe741f0f257307d26c9f68760ec4c1ecfc4d1d50c
Round: 8
Reviewer: mle-reviewer (independent, blind). §13 self-score text ignored per instruction.

## Round-7 MATERIAL defect (mine: `m_d=0` unaddressed) — verification: FIXED

Zero-take (`fills=0`) `COMPLETED` rows are now excluded at a named filter stage (§6.4 step 4's draw-set construction, before the first `combine_station_day` call), so that primitive's empty-day refusal is unreachable by construction — citation `current_rung_hold_v2.py:318-319` (`if not rows: raise ValueError(...)`) CONFIRMED exact. Both `n_station_days_observed` and `n_station_days_with_takes` are recorded on the look row with `take_rate`; every `n`/`min_station_days` in the item is explicitly redefined as the with-takes count, so a starved take-rate is caught by the existing horizon/KILL machinery rather than silently diluting the confirmatory sample. The selection caveat (conditioning on a take is conditioning on the strategy's own trigger; the estimand is "edge per take given a take," silent on trade frequency) is stated honestly and `take_rate` travels with the estimate to H5/H6. This closes my round-7 finding correctly and completely.

## Round-7 MATERIAL defect (other reviewer: MEAN can CONFIRM on negative pooled P&L) — verification: FIXED, Type-I argument correct

The veto-only design is mathematically sound: `CONFIRMED` requires the primary CI to exclude zero **AND** `pooled_net_pnl_per_contract > 0` strictly **AND** `max_single_day_leg_share` within the pinned cap — the set of outcomes reaching `CONFIRMED` is a strict subset of the primary test's own rejection region. Since `P(A ∩ B | H0) ≤ P(A | H0)` for any event `B`, intersecting with an additional condition can only shrink the probability of a false positive, regardless of what that condition tests — so Type-I error stays bounded by `per_variant_alpha` with no alpha re-spend needed. This is correct and requires no independence or distributional assumption about the veto condition. Citations verified: `combine_station_day`'s `x = sum(...)` at `current_rung_hold_v2.py:337-340` CONFIRMED exact; `break_even_row` at `:76-84` CONFIRMED exact. The round-7 counterexample (nine 1-leg winners vs. one 100-leg loser) is correctly reused as the RED fixture (vi-j).

## New finding (MINOR) — `MAX_SINGLE_DAY_LEG_SHARE = 0.20` is asserted, not derived

§6.1 claims `0.20` "is the coarsest bound under which no single station-day can carry a pooled result on its own." This is not actually proven: leg-count SHARE does not bound P&L-DOLLAR share, since each leg's contribution to `pooled_net_pnl_per_contract` depends on its entry ask (via `W_i - BE_i`, bounded in `[-1,1]` per leg but not uniform), not merely its count — a station-day with a leg-share just under 0.20 could still carry a disproportionate share of the pooled dollars if its per-leg outcomes are extreme relative to the rest of the sample. The number is a reasonable, cheap, precedent-free heuristic guardrail (and the actual Type-I safety comes from the strict `>0` pooled-P&L requirement, which is separately and correctly argued), but the specific "0.20 is the coarsest bound achieving X" claim overstates what the pin actually guarantees. **Required change:** soften the claim to state `0.20` is a pragmatic, pre-registered concentration guardrail (analogous to `POWER=0.80`'s conventional-value status) rather than asserting an unproven "coarsest sufficient bound" property, or provide the missing derivation.

## New finding (MATERIAL) — power statements are not honestly qualified now that the veto exists

`POWER = 0.80` and the worked MDE figures (`0.1032`/`0.0730`) describe only the PRIMARY test's design power (P(CI excludes zero | true effect = MDE)). The mandatory pooled-P&L veto introduced this round means the actual probability of reaching a final `CONFIRMED` disposition at the assigned MDE is **strictly lower** than 0.80 — some true-positive primary draws will fail the veto (exactly the round-7 counterexample's shape), yet nothing in §6.1, §9, §11, D13, or the §7 step 8 ruling clause states this distinction or quantifies/bounds the gap. §13's revision-8 row explicitly asserts the worked MDE numbers are "UNCHANGED" and needed no edit, which is true of the *formula* but glosses over what those numbers now represent to a reader (a ruling author or AUD-02/A1) who would reasonably read "`POWER = 0.80`" as "80% chance of a real edge reaching CONFIRMED" — no longer accurate. **Required change:** state explicitly, wherever `POWER`/MDE are presented (§6.1, §9, §11, the D13 clause, the ruling's clause (v)), that `POWER=0.80` is the primary test's design power only, that the composite probability of reaching `CONFIRMED` at the assigned MDE is strictly lower and unquantified by this design, and that the ruling's plausibility bound should be read with that in mind (or, if feasible, note a direction for narrowing the gap, e.g. requiring a larger MDE margin or a simulation-based composite-power estimate in a future amendment).

## Other checks

- No new inconsistency found elsewhere in the diff; the `PRIMARY_PASSED_PNL_VETO` status, `veto_reason` enum, and the "veto never promotes, never rescues a failed primary" asymmetry are all correctly and consistently threaded through §6.2, §6.4 step 6, §7, D13, and §9's failure cases.
- Length: 1372 lines, confirmed via `wc -l`; §13's claim is factual.

## Per-criterion scoring (round 8, whole plan, fresh)

- Fidelity to audit gap and completeness: 18/20 — both round-7 defects closed correctly and thoroughly; docked for the unaddressed power-honesty gap this round's own addition introduces.
- Technical correctness and evidence grounding: 16/20 — all citations verified accurate, the Type-I subset argument is rigorous and correct, the zero-take mechanism is sound; docked for the unsubstantiated `0.20` property claim and the power-honesty gap.
- Implementation specificity and feasibility: 13/15 — new fields, refusals, and fixtures are concrete and directly testable.
- Acceptance criteria and validation quality: 17/20 — (vi-i)/(vi-j) and D13 (viii)/(ix) are precisely targeted; no criterion addresses the composite-power characterization or the `0.20` derivation gap.
- Autonomous operation, failure handling and recovery: 14/15 — unchanged strength; the two new failure cases in §9 are clear and mechanically grounded.
- Portfolio objective alignment, scope and dependencies: 8/10 — length grew again (1112→1372) but accurately reported; scope remains coherent and well-cited.

**Total: 86/100**

## Blockers

- None requiring external/operator input. Both new findings are author-fixable (a qualifying statement for power/MDE, and either a softened claim or a derivation for the `0.20` cap).
