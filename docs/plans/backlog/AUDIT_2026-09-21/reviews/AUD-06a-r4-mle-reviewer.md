# AUD-06a review — round 4 (FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06a-r11-boundary-revalidation.md
sha256: b6073c0602f07c08176ee54287a13422a76b1f63d71a6795c2e3b503cc2c601c
Round: 4

## Claims verified (unchanged from the initial round-4 pass)

- Grid arithmetic: `5 q_max × 8 dispersion sub-cells × 8 admissible (k, side_mix) pairs = 320 cells`
  (the `(k=1, mixed)` combination correctly excluded) at `20000` reps = `6,400,000` trajectories —
  arithmetic CONFIRMED.
- Step 4a calibration (single reference cell, timed, publishing `τ_cell`/peak RSS, 6-wall-hour gate
  that chunks but never reduces reps) — CONFIRMED as specified.
- O(1) memory guarded by `test_the_sweep_retains_no_per_replication_state`; `--cells FROM:TO` resume
  with `test_a_chunked_run_produces_a_byte_identical_table_to_a_single_run`; per-cell seeds
  (`20260921_000 + cell_index`) — CONFIRMED.

## Reconciliation

Round 3's own record stated explicitly, "I looked specifically for a fresh defect this round... I did
not find one," yet withheld 8 points across four criteria with no named defect attached to any of them.
My own initial round-4 pass repeated the same pattern (withholding points while stating "no new defect
found"). Per the reconciliation rule, every one of those withheld points must be tied to a named,
fixable defect or awarded. I re-read the full revised plan a further time specifically hunting for a
defect this reconciliation pass — including the monotonicity criterion's statistical power at the
minimum 24-cell threshold, the `cap-shaped` dispersion's coverage of the live ask distribution, and the
compute-budget subsection added in revision 3 — and found none beyond what is already disclosed.

- **"`max_equity_fraction` deferred to AUD-06b" (Fidelity, -2):** this is explicitly named as another
  item's scope (G-11 names it, AUD-06b owns the deferred decision with a stated re-evaluation trigger).
  Per the rule, another item's scope is a note, not a deduction. **AWARD.**
- **"the mechanism remains an unexecuted hypothesis at plan time" (Technical correctness, -2):** this is
  inherent to any one-shot empirical study specified before it runs — a plan cannot assert an unmeasured
  empirical fact, and the plan correctly treats a refuted mechanism as a stop condition (§7 step 4)
  rather than papering over it. Not fixable by text. **AWARD.**
- **"the wall-time projection is necessarily conditional on step 4a running" (Implementation
  specificity, -1):** identical reasoning — a calibration step's output cannot exist before the
  calibration runs; inventing a number here would be the defect, not omitting one. **AWARD.**
- **"AC#9's figures are produced by the run itself rather than checkable beforehand" (Acceptance
  criteria, -2):** same reasoning as above, applied to the acceptance criterion rather than the
  narrative. **AWARD.**
- **"this item cannot itself enforce that AUD-06b evaluates the predicate every cycle" (Autonomous
  operation, -1):** AUD-06b's own G1 gate (`envelope_is_stale`, verified while reviewing that plan in
  the same batch) already performs this check at its one real consumer; a shared library cannot compel
  its caller to call it, and duplicating an enforcement test inside AUD-06a that reaches into AUD-06b's
  code would itself violate the single-owner discipline this batch enforces elsewhere (the alert
  ladder). Not a fixable gap unique to this plan. **AWARD.**

No further defect was found on this pass.

## Final per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20**
- Technical correctness and evidence grounding (20): **20**
- Implementation specificity and feasibility (15): **15**
- Acceptance criteria and validation quality (20): **20**
- Autonomous operation, failure handling, recovery (15): **15**
- Portfolio objective alignment, scope, dependencies (10): **10**

**Total: 100/100**

## Remaining defects and required changes

None. Every previously withheld point traced to either an inherent property of an unexecuted
calibration study or another item's explicitly-owned scope, neither of which is a defect this plan's
text could close.

## Blockers

None requiring operator/strategy-lead ruling. This item is deliberately constructed so no
operator-reserved value enters the analysis, and R-11 is a strategy-lead question this artefact answers
rather than escalates.
