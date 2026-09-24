# AUD-18 — Round 8 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: 3a261176f22884b1041e85efe741f0f257307d26c9f68760ec4c1ecfc4d1d50c
Round: 8

## Round-7 MATERIAL (mean statistic can CONFIRM a money-losing hypothesis) — verified CLOSED

Citations re-verified exact: `break_even_row` (`:76-84`), the empty-rows `ValueError` (`:318-319`), `x = sum(qty*((1.0 if held else 0)-be)...)` (`:337-340`), AUD-09's `replay_results.jsonl` schema (`trials, fills`, `outcome` independent of `fills`, `AUD-09...md:697-702`).

**Re-ran my round-7 counterexample against the new gate.** Nine 1-leg winners (`ask=0.02`) + one 100-leg loser (`ask=0.98`): primary MEAN test still excludes zero (`Sum_d X_d≈+7.5`), but `pooled_net_pnl_per_contract = Sum_d CombinedDraw.x ≈ 8.46-98 ≈ -89.5 < 0` — the veto fires, disposition is `PRIMARY_PASSED_PNL_VETO`, not `CONFIRMED`. Defeated.

**Tried to construct a new counterexample** by spreading the losing legs across multiple days to stay under the 20% concentration cap (e.g., 5 losing days x 20 legs instead of 1 x 100). Pooled SUM is invariant to how legs are distributed across days — it is `Sum` over every admitted leg regardless of clustering — so it is still `≈-89.5`, still vetoed. **This is not a coincidence: `pooled_net_pnl_per_contract` at `qty=1` is definitionally the exact realized dollar P&L of the sample** (win: `1-entry_ask-fee`; lose: `-entry_ask-fee`, summed). Requiring it `>0` strictly is exactly the condition "the sample was actually profitable in dollars" — no construction can satisfy both a MEAN-based CONFIRM and a genuinely money-losing sample, because the veto checks the ground truth directly rather than a proxy for it. I could not construct a counterexample, and do not believe one exists within this design.

**Fee/BE netting: no double-counting.** The veto reuses the SAME `BE_i` (hence the same `theta=0.0695`/slippage netting) already computed for the primary test's numerator — `x_d` is aggregated as a MEAN (`/m_d`) for the primary test and as a plain SUM for the veto; one fee application, two aggregations, not two cost models.

**`MAX_SINGLE_DAY_LEG_SHARE=0.20`:** a reasonable, explicitly-pinned (not per-hypothesis) defense-in-depth constant, but — unlike `VARIANCE_BOUND=0.25` (Popoviciu-derived) or `POWER=0.80` (textbook convention) — it is asserted ("the coarsest bound under which no single station-day can carry a pooled result on its own") rather than derived. This is a MINOR observation, not a material defect: the pooled-P&L veto alone already provably closes my round-7 gap independent of this cap, so the cap is genuinely supplementary (it guards bootstrap-CI validity against single-day domination, a separate and legitimate concern), not load-bearing for the finding it's being credited alongside.

**Consistency with `PINNED_ORDER_QUANTITY=1`:** no conflict — `CombinedDraw.x` is already qty-scaled (`qty*(...)`), so the pooled-P&L sum is correct dollar P&L for any `qty`; the unit-quantity pin remains independently necessary for `VARIANCE_BOUND`'s validity (round 6), and the two constraints are orthogonal and compatible.

## Round-7 (other reviewer) zero-take fix — sound from this lens

Excluding `fills=0` days from `n` before computing MEAN/veto is necessary (the primitive would otherwise raise) and correctly deferred to the existing horizon/KILL machinery when take-rate is too low, rather than diluting `n`. The selection caveat (estimand is edge-per-take *given a take*) is honestly disclosed via `take_rate` reported alongside every look, consistent with this repo's existing disclosure discipline elsewhere.

## Scoring (20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — a `CONFIRMED` pack is now both statistically significant and provably realized-profitable in-sample; the round-7 gap is closed at the root, not patched around.
- Technical correctness and evidence grounding: 20/20 — all citations verified exact; independently re-derived that the veto is mathematically airtight against the counterexample class.
- Implementation specificity and feasibility: 15/15 — concrete constants, fields, refusal names, and two REDs (vi-i, vi-j) pinning both directions.
- Acceptance criteria and validation quality: 20/20 — D13(viii)/(ix) test the exact counterexample fixture and the never-rescues-a-failed-primary direction.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected.
- Portfolio alignment, scope and dependencies: 10/10 — unaffected; strengthens AUD-06b's input further.

**Total: 100/100.**

## Blockers

None.
