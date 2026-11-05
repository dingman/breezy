# AUD-18 round-6 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: 1b092bb1176d8fa445d7633bf0376a3f391bf7f5b076ab74382e64c5e150face
Round: 6
Reviewer: mle-reviewer (independent, blind). §13 self-score text ignored per instruction.

## Round-5 MATERIAL defect (`1/4` bound conservative only at `qty=1`) — verification: FIXED, citations correct

`PINNED_ORDER_QUANTITY=1`, the `order_quantity` record field, `register_hypothesis`'s `NON_UNIT_ORDER_QUANTITY` refusal, RED (vi-f), D13 clause (vi), and the AUD-06a/AUD-06b out-of-scope carve-out are all present and mechanically enforced as claimed. Citations CONFIRMED against source: `current_rung_hold_v2.py:341` is exactly `variance = sum(qty * qty * q * (1.0 - q) ...)`; `config.py:253-255` is exactly `CurrentRungHoldConfig`'s `order_quantity must be exactly 1` refusal; `PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md:110-113` §2.2 is exactly "Trial unit one station-day, first filled take... Quantity 1." **My round-5 citation ("PREREG_v2 §2.2") was wrong** — confirmed by grep that `PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` has no such section; the correct source is WP7's, and the plan's correction (§13 row 6) states this accurately. This portion of the fix is sound.

## New MATERIAL defect — the `1/4` bound is not conservative for mixed-side (YES+NO) station-days, even at `qty=1`

`combine_station_day`'s covariance term (`current_rung_hold_v2.py:342-344`) is `variance -= 2·qty_i·qty_j·sign_i·sign_j·q_i·q_j`. For SAME-side legs (`sign_i·sign_j = +1`) this SUBTRACTS, correctly keeping variance conservative (verified numerically: `q=[0.5,0.5]`, `qty=1` same-side → variance `0.0`). For **OPPOSITE-side legs** (`sign_i·sign_j = -1`, i.e. a YES fill on one rung and a NO fill on another — explicitly supported and "mixed-side aware" per the function's own docstring), the term **ADDS**: recomputed in Python, `q=[0.5,0.5]`, `qty=1`, opposite sides → **`variance = 1.0`** — four times `VARIANCE_BOUND=0.25`, entirely within the admission gate (`Σq_i = 1.0`, not `> 1.0`, so not refused). `_cell_probability` (`current_rung_hold_v2.py:225-227`, `q = BE` for YES, `q = 1-BE` for NO) confirms both values are legitimately reachable at once for different rungs. **This directly implicates the plan's own primary use case**: NO-side hunting is one of only three open, registerable hypothesis classes §6.3 lists (and one of the four `MAX_HYPOTHESES` slots §6.1 reserves for it) — a mixed-side design is not a hypothetical edge case here, it is exactly what that class needs to register. Round 6's fix (pinning `order_quantity=1`) closes the quantity-scaling half of the round-5 finding but leaves this side-mixing half entirely unaddressed: nothing in §6.1/§6.2/§7 restricts, bounds, or even mentions mixed-side designs for the purpose of the power check, so a NO-side-hunting registration's stated MDE could be computed from an UNDER-stated variance (the unsafe direction, same failure mode as round 5's finding), invalidating the "genuinely conservative" claim for exactly the class most likely to need it first. **Required change:** either (a) derive and pin a variance bound that correctly covers the admissible mixed-side configuration space (e.g. a worst-case bound as a function of the number of legs and the `Σq_i ≤ 1` gate, verified the way `I_MAX` was), or (b) restrict the `1/4`-bound power check to YES-only (single-side) designs and require a NO-side-hunting registration to use a stated, larger, justified variance bound before `register_hypothesis` will accept it — and add a RED proving the mixed-side case is caught, not silently under-bounded.

## Other checks

- Length: 1004 lines, confirmed via `wc -l`; §13's "1004 (was 961)" claim is factual.
- No other new defects found in this round's diff; the AUD-06a/AUD-06b scope carve-out is accurate and appropriately cited by id only.

## Per-criterion scoring (round 6, whole plan, fresh)

- Fidelity to audit gap and completeness: 17/20 — the round-5 fix is clean and honestly self-corrected; docked because the power check's central conservatism claim still fails for the NO-side-hunting class the programme is explicitly built to register.
- Technical correctness and evidence grounding: 14/20 — all citations in this round's diff verified accurate; the newly-found mixed-side variance gap is a genuine, numerically-confirmed correctness failure in the same mechanism this round claimed to have closed.
- Implementation specificity and feasibility: 11/15 — the quantity constraint is concretely implementable; the mixed-side gap has no proposed fix (formula or scope restriction) yet.
- Acceptance criteria and validation quality: 15/20 — D13(vi) tests the quantity constraint well; no criterion catches or guards the mixed-side variance blow-up.
- Autonomous operation, failure handling and recovery: 14/15 — unchanged strength.
- Portfolio objective alignment, scope and dependencies: 8/10 — length grew again (961→1004) but accurately reported; scope and dependency citations remain tight.

**Total: 79/100**

## Blockers

- None requiring external/operator input. The mixed-side variance gap is author-fixable (a derived bound or a registration-time scope restriction plus a test).
