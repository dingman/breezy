# AUD-18 round-5 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: 99b95223debe99d7300f507031009ed0016bf956a63e94d4130fd229ae881f41
Round: 5
Reviewer: mle-reviewer (independent, blind). §13 self-score text ignored per instruction.

## Round-4 MATERIAL defect (no stated variance input; caller-supplied MDE) — verification: FIXED

`register_hypothesis` no longer trusts a caller-supplied MDE; `recompute_mde` derives it from recorded, outcome-free inputs and refuses on mismatch/off-pin input. The `roi_bound.py`/`current_rung_hold_v2.py` citations are correctly WITHDRAWN for the power-check purpose with an accurate technical reason stated (`ROIBoundUnderpowered` is a post-hoc `n`-floor computing no effect size; `combine_station_day`/`score_combined` operate on realized rows, not prospective draws) — and CONFIRMED still correctly cited, unchanged, at §6.4 step 4 for the real (post-data) confirmatory computation. No stale citation found.

**Formula and all worked numbers independently recomputed (Python `statistics.NormalDist`), exact match:**
- `z_(1-0.003125) = 2.734369` (plan: 2.7344) ✓
- `z_0.80 = 0.841621` (plan: 0.8416) ✓
- `n=300: 3.5760 / (2·√300) = 3.5760/34.6410 = 0.10323` (plan: 0.1032) ✓
- `n=600: 3.5760 / (2·√600) = 3.5760/48.9898 = 0.07299` (plan: 0.0730) ✓
- `BE = 0.30 + 0.0695·0.30·0.70 + 0.01 = 0.324595` (plan: 0.324595) ✓

Form is the standard one-sided, one-sample MDE: `(z_alpha + z_beta)·σ/√n` with `σ = √(VARIANCE_BOUND) = 0.5` — correct derivation, correctly reduces to the stated `.../(2√n)`. `I_MAX`/`PREREG_v2` citations for the Bernoulli `1/4` convention (`gs_boundary_artefact.py:75-78`; `PREREG_v2...:55-60`) CONFIRMED accurate.

## New MATERIAL defect — the `1/4` variance bound is conservative only under an unstated `qty=1` assumption

`combine_station_day`'s actual variance formula (`current_rung_hold_v2.py:298-341`, read this session) is `variance = Σ qty_i²·q_i(1-q_i) − Σ_{i<j} 2·qty_i·qty_j·sign_i·sign_j·q_i·q_j`. The admission gate refuses only `Σ q_i > 1`; **it does not bound `qty`.** With `qty_i = 1` (the live family's own pinned convention — `PREREG_v2 §2.2`: "Quantity 1, first filled take") the per-leg term is bounded by the Bernoulli maximum `q(1-q) ≤ 1/4`, so the plan's variance bound is exact/conservative. But at `qty_i = 2`, a single leg alone already contributes `4·q(1-q)`, up to `1.0` — four times the assumed ceiling. §6.1 states "one effective observation per station-day" (the **count** dimension, `n` = station-days) is correct and exact — CONFIRMED it matches `score_combined`'s own documented trial unit ("never the number of constituent fills"). But nothing in §6.1/§6.2/§7 pins `qty=1` as a requirement for hypotheses registered under this item, so the claim that `VARIANCE_BOUND=0.25` is "genuinely conservative... for multiple takes" is **only true if every registered hypothesis also trades at quantity 1** — an assumption inherited implicitly from the live family's own design but never stated or enforced here. If a future hypothesis's design allows `qty > 1` per rung/leg, the true variance could exceed the pinned bound, making the MDE computation UNDER-state the true MDE — the unsafe direction (a hypothesis could look adequately powered when it is not). **Required change:** either state and mechanically enforce `qty=1, first-filled-take` as a mandatory design constraint on every AUD-18-registered hypothesis (citing `PREREG_v2 §2.2` as the reused convention, with a refusal in `register_hypothesis` for any other declared position-sizing rule), or generalize `VARIANCE_BOUND` to scale by the hypothesis's own declared maximum `qty` so the conservatism claim holds regardless of position sizing.

## Other checks

- Length: §13 states 961 lines — CONFIRMED via `wc -l` (961). Factual, consistent with rounds 3-4's pattern of accurate self-reporting once corrected.
- `theta` staleness guard (`0.0695` vs `config.py:226`'s stale `0.06`) — consistent with the repo's own `FEE_SCHEDULE_PIN_2026-09-18.md`, correctly enforced by refusal (vi-c).
- AUD-12 slippage-placeholder dependency is named honestly (unmeasured one-tick placeholder, with an explicit obligation to re-run the check when AUD-12 lands) — no overclaiming.

## Per-criterion scoring (round 5, whole plan, fresh)

- Fidelity to audit gap and completeness: 19/20 — power check is now comprehensive, mechanically enforced and honestly illustrated; docked 1 for the unstated `qty=1` dependency.
- Technical correctness and evidence grounding: 17/20 — formula, citations and all worked numbers independently verified correct; docked for the unexamined variance-bound conservatism gap under `qty > 1`.
- Implementation specificity and feasibility: 13/15 — `recompute_mde`, the pinned constants, and the refusal conditions are fully concrete and buildable as specified.
- Acceptance criteria and validation quality: 18/20 — D13's five clauses are thorough, numerically exact and testable; no criterion tests or asserts the `qty=1` constraint the variance bound's soundness depends on.
- Autonomous operation, failure handling and recovery: 14/15 — unchanged strength from round 4.
- Portfolio objective alignment, scope and dependencies: 8/10 — length grew again (832→961) but is accurately reported; scope/derivation remain tight and well-grounded.

**Total: 89/100**

## Blockers

- None requiring external/operator input. The `qty=1` conservatism gap is author-fixable (a stated constraint plus a refusal, or a generalized variance-bound formula).
