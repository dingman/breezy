# AUD-18 — Round 7 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: bba51be19582c343291fbb549049ad2f7a285dc0156416458112ec755a3045e1
Round: 7

## Round-6 MATERIAL (mixed-side variance blow-up) — statistically FIXED, but exposes a NEW gap

The Popoviciu derivation is verified correct and well-cited. `combine_station_day`'s covariance term (`current_rung_hold_v2.py:342-344`) confirmed to ADD for opposite-side legs (`signs[i]*signs[j]=-1`); at `q=[0.5,0.5]`, `qty=1` the SUM's variance is exactly `0.25+0.25+0.5=1.0`, and the admission gate (`:331`, `sum(qs)>1.0`) does NOT refuse it (sum is exactly `1.0`). Each `W_i-BE_i` term does lie in a width-1 interval, and the mean of terms each in a (possibly differently-located, since `BE_i` is leg-specific) width-1 interval is itself confined to `[-mean(BE_i), 1-mean(BE_i)]`, width exactly 1 — so `Var(X_d) <= 1/4` by Popoviciu holds for ANY side mix, leg count, or dependence. This is mathematically sound.

## New MATERIAL finding (this reviewer's lens): the MEAN statistic can CONFIRM a hypothesis with negative pooled dollar P&L

At `qty=1`, each leg's face value is $1, so `W_i - BE_i` **is exactly that leg's realized dollar P&L per contract** (win: `1 - entry_ask_i - fee_i`; lose: `-entry_ask_i - fee_i`). Within ONE station-day, `MEAN_d = SUM_d / m_d`, so sign is preserved (`m_d > 0`) — no gap there; this is the "already net of that leg's own price-dependent break-even" defence, and it is sufficient WITHIN a day.

**It is not sufficient ACROSS days**, because the confirmatory test (`score_combined`, station-day-clustered) equal-weights each day's `MEAN_d` regardless of `m_d`, while real pooled P&L is a leg-weighted (≈dollar-weighted, since face value is fixed at $1/contract) SUM. Concrete counterexample: 9 station-days each with **1** cheap winning leg (`ask≈0.02`, `X_d≈+0.94`) and 1 station-day with **100** expensive losing legs (`ask≈0.98` each, all lose, `X_d≈-0.98` — the MEAN is capped in `[-1,1]` regardless of `m_d`, so a 100-leg losing day contributes the SAME order of magnitude to `sum_d(X_d)` as a 1-leg day). `sum_d(X_d) ≈ 9(0.94) - 0.98 ≈ +7.5` — strongly CONFIRMS. Actual pooled dollar P&L: `9(1)(0.94) + 1(100)(-0.98) ≈ 8.5 - 98 ≈ -89.5` — **decisively negative**. A hypothesis can therefore reach `CONFIRMED` (CI excludes zero on average edge per take) while losing money in aggregate, precisely because a day's leg count is uncorrelated with its weight in the confirmatory statistic but fully determines its weight in real P&L. §12's own "accepted limitation" text calls this choice "CONSERVATIVE for this purpose" — that claim is **not shown and is false in the direction that matters**: it is conservative for Type-I error control on the per-take estimand, not for whether a CONFIRMED result implies real money edge, which is what AUD-06b/A1 actually need as input. No guard against this exists anywhere in the plan (grepped for "pooled"/"net P&L"/"veto" — zero matches).

**Required change (exact):** add a mandatory, pre-registered, mechanically-enforced **secondary check**, evaluated at the same look as the primary confirmatory test, using `combine_station_day`'s existing SUM (already reused for ROI accounting, §6.1 item (c) — no new estimator): pooled dollar P&L per contract across every admissible station-day draw in the variant (`sum_d SUM_d`, or equivalently `sum` over every included leg of `W_i-BE_i`) must be `> 0`. This check can only **VETO** — a hypothesis whose primary MEAN-based test clears its CI-excludes-zero bar is downgraded to a new terminal status (e.g. `CONFIRMED_MEAN_ONLY_POOLED_PNL_NEGATIVE`, not handed to AUD-02/AUD-06b as evidence) if pooled SUM P&L is non-positive; it must never be used to promote a hypothesis whose primary test fails. It consumes **no alpha** (a directional consistency gate, not a second hypothesis test), needs no new field beyond a boolean/value recorded alongside the `HypothesisLook` row, and needs one RED pinning both directions (primary passes + pooled SUM positive → CONFIRMED; primary passes + pooled SUM non-positive → refused, naming both numbers).

## Scoring (20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 15/20 — a CONFIRMED pack is not yet guaranteed to correspond to actual profitability, which is exactly what the audit gap (a trustworthy independent edge estimate) requires.
- Technical correctness and evidence grounding: 15/20 — the Popoviciu derivation is correct, but the plan's own "conservative for this purpose" claim about the mean estimand is unsupported and wrong in the economically relevant direction.
- Implementation specificity and feasibility: 13/15 — the missing guard is simple to add (reuses the existing SUM) but is currently entirely unspecified.
- Acceptance criteria and validation quality: 14/20 — no criterion (D1-D13) tests that CONFIRMED implies non-negative pooled dollar P&L.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected.
- Portfolio alignment, scope and dependencies: 10/10 — unaffected; strengthens rather than conflicts with AUD-06b's dependency on a genuinely profitable CONFIRMED edge.

**Total: 82/100.**

## Blockers

None external. The pooled-P&L veto is an in-plan fix (reuses the existing SUM primitive), not an operator/strategy ruling or unavailable evidence.
