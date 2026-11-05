# AUD-18 round-9 review — mle-reviewer (RECONCILED)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: 3da81edd563a9b64814c574a7e8ac9b231c0aed27321384463217a9bc43627ba
Round: 9
Reviewer: mle-reviewer (independent, blind). §13 self-score text ignored per instruction.
Status: RECONCILED — original record withheld 7 points without a named-defect-plus-exact-change
for 5 criteria, contrary to the reviewer brief's rule. Each is re-adjudicated below: restored
where no such defect exists, kept only where one can be cited precisely.

## Round-8 findings — verification (unchanged from original record)

Both round-8 findings (power statements not honestly qualified now that the pooled-P&L veto
exists; the `MAX_SINGLE_DAY_LEG_SHARE=0.20` "coarsest bound" claim) are verified FIXED,
correctly and rigorously. The upper-bound argument `P(CONFIRMED|MDE) <= 0.80` is a valid
application of the same subset/containment argument already verified for the veto's
alpha-freeness; the shortfall is honestly left unquantified rather than fabricated, and handled
conservatively (refusal safe a fortiori; admitting verdicts labelled primary-only). The `0.20`
cap's unproven property claim is withdrawn and correctly reframed as a pragmatic guardrail,
with the strict `pooled_net_pnl_per_contract > 0` condition correctly identified as what
actually closes the money-losing-CONFIRM gap. No defect in either fix.

## Reconciliation of the five withheld-point criteria

**Technical correctness and evidence grounding (was 19/20).** The withheld point was justified
as "the composite-power shortfall remains fundamentally unquantified" — but my own write-up
called this "honestly disclosed, appropriately handled." That is not a defect: the brief
requires explaining a genuinely inapplicable criterion rather than penalizing it, and refusing
to fabricate a number for an analytically unbounded quantity is the scientifically correct
choice, not a gap needing a fix. No exact required change exists (there is nothing to change).
**RESTORED to 20/20.**

**Implementation specificity and feasibility (was 14/15).** No defect was named in the original
record — only praise ("fully concrete and directly testable"). **RESTORED to 15/15.**

**Acceptance criteria and validation quality (was 19/20).** No defect was named — only praise
for D13 clause (i)'s extension. **RESTORED to 20/20.**

**Autonomous operation, failure handling and recovery (was 14/15).** The original record gave
no round-9-specific defect, only "unchanged strength from round 8." Checked directly for a
citable carryover: a crash DURING look computation (before the atomic write) leaves no
`HypothesisLook` row, so the variant is untouched and simply eligible for a fresh look on the
next scheduled run — safe by construction, since `SINGLE_LOOK` eligibility is keyed off the
row's existence, not off any partial state. A crash DURING the write is covered by the
documented atomic temp+`os.replace` discipline (`docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md:1289-1291`).
Both failure timings are covered by construction; no exact required change identified.
**RESTORED to 15/15.**

**Portfolio objective alignment, scope and dependencies (was 7/10, withheld 3).** The brief's
rubric has no standalone "length" criterion; length was folded into this one as a proxy for
scope control. Per the coordinator's test: length alone, with no concrete harm, is not a rubric
defect. Re-checked for concrete harm rather than line count alone — found one: the round-9
"`POWER=0.80` is primary-test-only, `P(CONFIRMED|MDE) <= 0.80`" claim is restated as a full,
near-verbatim normative paragraph in **four** separate locations rather than stated once and
cross-referenced: `AUD-18-strategy-design-backtest-iterate-programme.md:454-466` (§6.1, the
canonical definition), `:1254-1269` (§9), `:1338-1346` (§11), `:1421-1431` (§12). This is
concrete, present-tense harm of exactly the kind the brief names as an example ("duplicated
normative text that can drift"): four independently-editable copies of one binding claim is a
real drift risk for a plan already nine revision rounds deep, and is distinct from mere page
count. It does not affect §6.2's record-field definition or D13/§7's test clauses, which
correctly state the rule once each in their own structural role (schema comment, RED
assertion) rather than re-deriving the argument. **Required change:** keep the full derivation
at §6.1 (`:454-466`) as the single canonical statement; replace the §9, §11 and §12 occurrences
with a one-sentence cross-reference ("primary-test power only, upper-bounds `P(CONFIRMED)` —
see §6.1") rather than restating the argument. This is a targeted consolidation of four
specific paragraphs, not a scope cut — no requirement, test, or acceptance criterion is
removed. **Kept, but reduced: 8/10** (withheld 2, not 3, since this is one specific,
narrow, exactly-cited duplication pattern, not a defect for the document's length overall).

## Per-criterion scoring (reconciled)

- Fidelity to audit gap and completeness: 20/20 — unchanged, no defect found in the original review.
- Technical correctness and evidence grounding: 20/20 — restored.
- Implementation specificity and feasibility: 15/15 — restored.
- Acceptance criteria and validation quality: 20/20 — restored.
- Autonomous operation, failure handling and recovery: 15/15 — restored.
- Portfolio objective alignment, scope and dependencies: 8/10 — one named, cited, fixable duplication defect.

**Total: 98/100**

## Blockers

- None. The one remaining deduction is author-fixable (a four-location consolidation, exact
  spans cited above) and requires no operator/external input or unavailable evidence.
