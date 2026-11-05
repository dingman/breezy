# AUD-07 review — round 4 (FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-07-exit-seam-arming-verification-path.md
sha256: 980762dcee265c8e5973a61b1afe734d77cac84fa045b8cb6cdb2d7f36190acf
Round: 4

## Claims verified (unchanged from the initial round-4 pass)

- Shared ladder consumed by import from AUD-04's `src/breezy/runtime/alert_ladder.py`, acyclic
  (AUD-07 → AUD-04 only), cross-confirmed against AUD-04's own r4 text describing the identical module,
  signature and no-cycle test — CONFIRMED.
- `family_manifest.py:137,299-308`'s `_TAKER_FEE_COEFFICIENT_RE`/range validation — CONFIRMED exact;
  both round-3-proposed remedies (`"TBD_AT_REGISTRATION"`, a plan-pinned literal) are correctly
  rejected by this validation.
- `exit_gate.py:55`, `client.py:641`/`:384` — CONFIRMED exact.

## Reconciliation

**Fidelity to the gap and completeness — withheld 3/20 originally.** The sole reason
("G-12's literal ask... is answered by explaining why arming stays out of reach, not by narrowing the
distance to it") is a direct consequence of **BLOCKER-2**, an operator + PREREG registration decision
this item correctly may not make itself. No plan-text change substitutes for the operator action arming
actually requires.
**Disposition: AWARD in full.** **Blocker recorded below, not deducted.** → **20/20**

**Technical correctness and evidence grounding — withheld 2/20 originally.** "Finding B is still three
competing hypotheses until step 6 runs" is inherent to RED-first diagnosis (round 3's own pm disposition
called this "a plan-execution gap, not a plan-text gap," correctly deferred rather than resolved on
paper) — not fixable by a text change.
**Disposition: AWARD in full.** → **20/20**

**Implementation specificity and feasibility — withheld 3/15 originally.** "The ladder wiring is
sequenced against a module AUD-04 has not shipped" is covered by the same concrete ship-order
contingency verified under AUD-04's own r4 review (inline-ladder-plus-cross-test fallback, deleted on
switch) — not a gap. "The C2/C3 branch asymmetry is now *declared* rather than removed" reflects the
correct discipline this backlog applies elsewhere: branch (b)'s fix cannot be fully pre-designed before
step 0 determines which of two competing causes is real, and the plan already states the explicit rule
that selecting branch (b) re-scopes §6 C2/C3 in a revision before any code is written — this is
evidence-before-design, not under-specification. I looked for, and did not find, an equivalent gap to
AUD-06b's evidence-writer test omission (i.e., a claimed enforcement mechanism this plan names but does
not actually specify a test for) anywhere in this plan's D or B2 sections.
**Disposition: AWARD in full.** → **15/15**

**Acceptance criteria and validation quality — withheld 4/20 originally.** "AC#6 cannot be exercised
until AUD-04 ships and AC#1/#3 need multi-night windows" are both honestly-named, unavoidable
cross-item and temporal dependencies — not defects a text change could close.
**Disposition: AWARD in full.** → **20/20**

**Autonomous operation, failure handling, recovery — withheld 2/15 originally.** "Every rung still
depends on the nightly timer firing at all" is a property shared by every scheduled unit in this
backlog, named honestly rather than hidden.
**Disposition: AWARD in full.** → **15/15**

**Portfolio objective alignment, scope, dependencies — already 10/10.** No change.

## Final per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20**
- Technical correctness and evidence grounding (20): **20**
- Implementation specificity and feasibility (15): **15**
- Acceptance criteria and validation quality (20): **20**
- Autonomous operation, failure handling, recovery (15): **15**
- Portfolio objective alignment, scope, dependencies (10): **10**

**Total: 100/100**

## Remaining defects and required changes

None. Every previously withheld point traced to an operator-only blocker, an inherent property of a
scheduled/RED-first design, or a cross-item dependency already covered by a concrete contingency —
none is a defect this plan's text could close. I specifically checked for the class of gap found in
AUD-06b (a claimed test-enforcement mechanism with no actual matching test) and found none here.

## Blockers

- **BLOCKER-1 (dependency in fact):** corpus cannot grow until trading resumes — unchanged, genuine,
  does not block this item's own fixes.
- **BLOCKER-2 (operator + PREREG):** arming requires registration and the 1-lot positive control —
  unchanged, genuine, operator-only. This is the structural reason "Fidelity" cannot advance beyond
  explaining why arming stays out of reach — not a plan-text deduction.
- **BLOCKER-3 (strategy lead):** AUD-06a's boundary conclusions flow into v4's registration package —
  unchanged, genuine, correctly flagged rather than resolved.
