# AUD-06a — Round 1 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06a-r11-boundary-revalidation.md
SHA256: efb219f8319ebf6ab53843007456e11480527ba3b396fa3cebffbb50a03a6fda
Round: 1
Reviewer: prediction-market-reviewer (independent, blind)

## Claims verified

- The registered H0 formulas quoted in §6 (`X_sd = Σ_i qty_i·(held_i − BE_i)`;
  `Var_H0(X_sd) = Σ_i qty_i²·BE_i(1−BE_i) − 2·Σ_{i<j} qty_i·qty_j·BE_i·BE_j`; `I = Σ_sd Var_H0(X_sd)`;
  `S = Σ_sd X_sd/√I`) are CONFIRMED verbatim against `MULTI_POSITION_PER_STATION_2026-09-14.md:130-132`
  (R3-3). No drift between what the plan claims is registered and what the MP plan actually
  registers.
- The admission gate "`Σ_i BE_i ≤ 1` enforced at draw construction, never post-hoc" is CONFIRMED
  against the same source line.

## Defects

From my lens (sizing vs. demonstrated edge, statistical soundness of any envelope that would later
gate real money), this item is a pure offline type-I-error validation with no capital at risk — most
of my checklist does not apply. Two points worth naming:

**MINOR — CI method and replication count for the crossing rate are unspecified.**
File: AUD-06a §6 "Sweep axes", §8 AC #2.
Issue: the plan requires "an upper Monte-Carlo CI bound ≤ α=0.025" but does not pin the CI
construction (Wilson? normal-approximation? Clopper-Pearson?) or the replication count, both of
which materially change whether a borderline cell (crossing rate near 0.025) is judged inside or
outside the envelope — the exact quantity AUD-06b will later trust with real qty. Author already
self-docked this; I confirm it is real and matters more than a typical "implementation specificity"
gap because the envelope is a safety boundary, not a cosmetic output.
Fix: pin the CI method (Clopper-Pearson recommended for a rate near a small-count boundary) and a
minimum replication count sized to resolve 0.025 vs 0.059 with reasonable power, stated in the
Amendment C text itself, not left to the implementer.

**MINOR — no re-validation trigger if the ask (`BE`) distribution shifts.**
File: AUD-06a §9.
Issue: correctly identified by the author as a self-scored weakness; from a risk-review lens this
matters because a validated envelope that "silently expires" is exactly the class of stale-quote /
stale-calibration risk this domain checklist flags elsewhere (HIGH: stale quotes / calibration
staleness). Given this artefact is explicitly a one-shot, non-timer study (§9), the mitigation cannot
be automated re-validation — but the plan should name a concrete trigger condition (e.g., "if the
observed live ask distribution's mean/variance moves outside the sweep's sampled range, the envelope
must be re-validated before AUD-06b consumes it further") rather than leaving it unstated.
Fix: add one sentence naming the trigger condition to §9 or §12.

No MATERIAL defect: the H0 formulas are reproduced exactly, the admission gate is enforced at draw
construction (not post-hoc) as claimed, and the item correctly refuses to touch α/n_max/i_max/
look_step or read the operator cap.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): 16 — squarely addresses R-11/G-11's blocker; `max_equity_
  fraction` correctly deferred to AUD-06b rather than silently ignored.
- Technical correctness and evidence grounding (20): 17 — registered formulas verified verbatim
  against source; diagnosis of the over-crossing mechanism remains a stated hypothesis, appropriately
  flagged as such rather than asserted as fact.
- Implementation specificity and feasibility (15): 10 — sweep axes and outputs named; CI method,
  replication count and `Var(S)≈1` tolerance unpinned (three material numbers, one directly gating
  future capital exposure via AUD-06b).
- Acceptance criteria and validation quality (20): 16 — measurable, reproduce-first gate, honest
  empty-envelope branch; `q_max ≥ 2` threshold in AC #3 is asserted without justification.
- Autonomous operation, failure handling, recovery (15): 11 — correctly forbids adding a timer; no
  re-validation trigger stated for `BE`-distribution drift.
- Portfolio objective alignment, scope, dependencies (10): 5 — honest zero-ROI-by-itself framing,
  correct independence from AUD-02, tight exclusions.

**Total: 75/100**

## Required changes to reach 100

1. Pin the CI construction method and minimum replication count in Amendment C.
2. State a concrete re-validation trigger for `BE`-distribution drift.
3. Justify (or remove) the `q_max ≥ 2` threshold in AC #3.

## Blockers

None. Fully actionable offline with no operator input required, as the plan itself argues and this
review confirms.
