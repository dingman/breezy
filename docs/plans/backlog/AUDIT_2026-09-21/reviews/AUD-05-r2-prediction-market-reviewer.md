# AUD-05 — Round 2 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md
SHA256: 171f40d32865d19ac19c3531e78eb5bc889149d41973601bce59478542f054f1
Round: 2
Reviewer: prediction-market-reviewer (independent, blind)

## Round-1 defect disposition verification

- D-B causes not pre-ranked (my MINOR): CONFIRMED fixed. §6 D-B and §7 step 0(b) now name
  `symbology.no_leg_instrument_id:277`, `leg_of:289`, `sibling_instrument_id:318`,
  `parsing.LEG_NO:1471` and make the composite-`^no`-form comparison the first check.
- D-A field-level fix location unpinned (both reviewers): CONFIRMED, §6 D-A names the stratum
  builder's `side`/`BE`/`held` carriers around `current_rung_hold_v2.py:380-430`, and §7 step 0(f)
  requires the dataclass's field list in the evidence pack.
- Alert wiring left as a choice (both): CONFIRMED closed, §6 D-F — one option, `FAMILY_TALLY_FAILED`
  CRITICAL through `resolve_alert_sink`/`emit_alert`, latched per `(family_id, UTC day)`.
- "Portfolio objective alignment" indirectness (both, low score): §11 now states the explicit
  evidence chain, a numeric baseline (0 reports, n=0, ≥3 consecutive failures), and concedes zero
  direct ROI contribution rather than inflating it — this is the correct disposition, not a defect.

Re-verified independently this round, against live source (not merely trusting §13's claim):
- `build_stratum_v2`'s raise site at `current_rung_hold_v2.py:414-419`: byte-identical to the plan's
  quote, including "fix-first review of 87278dd, item 3".
- `pm_us_crh_v4.json:4` / `pm_us_crh_cont.json:4` `trial_id_prefix`: byte-identical collision,
  reconfirmed.

## Fresh review of the full revision (new defects)

**MINOR — the amendment's registered variance formula is quoted with a sign convention
(`s_i` per leg) that the plan must additionally prove is applied to `qty_i` and not just to the
`(held_i − BE_i)` term, and no test isolates that specific placement.**
File: AUD-05 §6 D-A, §7 step 1.
Issue: the registered formula (quoted accurately from the amendment) is
`Var_H0(x_sd) = Σ qty_i² q_i(1−q_i) − 2 Σ_{i<j} qty_i qty_j s_i s_j q_i q_j`. The plan's
step-1 test `test_a_mixed_side_station_day_matches_the_registered_variance_formula` asserts the
cross term is POSITIVE for a YES/NO pair — good, that catches a sign error in the *product*
`s_i s_j`. It does not by itself distinguish "sign applied to the pair product" from "sign applied
inside `q_i` itself" (i.e. an implementer could satisfy the positive-cross-term assertion by
flipping `q_i` for NO rows rather than by carrying `s_i` as amendment §3 specifies), which would
still pass the one asserted numeric case at a symmetric `qty_i=qty_j` but diverge at unequal
`qty_i≠qty_j` on the `qty_i² q_i(1−q_i)` diagonal term. This is exactly the class of "plausible but
wrong" implementation the amendment's own history note (one misspecified null already superseded)
warns about.
Failure: a diagonal-term sign/placement error would under- or over-state `Var_H0` specifically for
asymmetric mixed-qty station-days once AUD-06b ships qty>1, silently mis-calibrating the sequential
test's type-I rate on exactly the population AUD-06a is validating separately.
Fix: extend `test_a_mixed_side_station_day_matches_the_registered_variance_formula` (or add a
second case) with `qty_i ≠ qty_j`, asserting both the diagonal terms and the cross term
independently against hand-computed values, not only the aggregate `Var_H0`.

**MINOR — D-E orphan-unit cleanup has no regression guard against re-accumulation (self-conceded,
verified still open).**
File: AUD-05 §6 D-E, §8 AC#6.
Issue: AC#6 proves the two named orphans are gone today; nothing in §7/§8 prevents a future retire
from leaving a third orphan (the same WP-11b failure mode that created these two). Low severity —
it is observability debt, not a money-accounting defect — but it is a real, fixable gap in a plan
whose whole subject is "a failing measurement unit silently persists."
Fix: add a test enumerating `deploy/systemd/breezy-family-tally@*` (or the unit directory) that
fails if an installed timer's target family is not `REGISTERED` in `deploy/families/`.

No MATERIAL defect. From the portfolio-accounting/risk lens specifically: D-A's registered-formula
grounding, the guard-preservation discipline (byte-unchanged `combine_station_day`, the two "guard
must still fire" tests), and the store-contamination refusal are all sound and correctly prioritise
not drifting the registered statistic over closing the blackout quickly.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **19** — every element of G-04 covered, plus D-D and D-F
  which G-04 did not name; R-4 correctly deferred to the named BLOCKER-2 rather than silently
  resolved. −1 only because the item cannot itself close R-4/BLOCKER-2 (structural, see Blockers).
- Technical correctness and evidence grounding (20): **18** — both tracebacks and the prefix
  collision re-verified byte-for-byte against live source this round; the registered formula is
  quoted accurately. −2 for the diagonal-vs-cross-term sign-placement gap above, which is a real
  correctness risk the current test set does not close.
- Implementation specificity and feasibility (15): **13** — seams, call sites, the alert latch and
  the field-list evidence step are all named with file:line. −2 for the still-open D-B two-hypothesis
  discrimination (correctly deferred to step 0, but it is a genuine discovery step inside the plan)
  and the unequal-qty test gap above.
- Acceptance criteria and validation quality (20): **18** — measurable; guard-preservation and
  statistic-invariance are each proven by test; AC#4's live half is honestly split from its fixture
  half. −2 for the missing unequal-qty variance assertion (ties to the correctness finding above).
- Autonomous operation, failure handling, recovery (15): **14** — the real autonomy defect (3 days
  silent failure) is closed by a specified, latched, delivering alert. −1 for the orphan
  re-accumulation gap.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 states the explicit,
  concrete evidence chain to the only money-moving item, a numeric baseline, a falsifier and the
  dependency stage, and honestly concedes zero direct ROI contribution. The genuinely indirect
  nature of the contribution is a fact about this item's charter, not a plan defect, and per this
  round's scoring guidance is not deducted; D-D's gating on BLOCKER-1 is named below as a BLOCKER,
  not scored down here.

**Total: 92/100**

## Required changes to reach 100

1. Extend the mixed-side variance RED test to unequal `qty_i ≠ qty_j`, asserting the diagonal and
   cross terms independently rather than only the aggregate value.
2. Add a regression test that fails if any installed `breezy-family-tally@` timer targets a
   non-`REGISTERED` family, to prevent a future orphan of the same class as D-E.

## Blockers

BLOCKER-1 and BLOCKER-2 (strategy-lead/PREREG-authority rulings on re-issuing `pm_us_crh_v4`'s
`trial_id_prefix` and on retiring `pm_us_crh_cont`) are genuine and correctly named. They gate only
D-D; D-A, D-B and D-F are executable and evaluable today. Per this round's instruction, these are
named as BLOCKERs rather than scored down, since no change to the plan text can resolve them.
