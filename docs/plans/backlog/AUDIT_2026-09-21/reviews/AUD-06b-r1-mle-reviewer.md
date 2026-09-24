# AUD-06b review — round 1 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06b-bounded-allocation-sizing.md
sha256: 17adee53cb96fe92e87fb41a6923a72cba4101b222ac22ef2243389fb410d154
Round: 1

## Claims verified
- `config.py:253-255` refuses `order_quantity != 1` — CONFIRMED verbatim ("order_quantity must be exactly 1, was {self.order_quantity!r}").
- `RiskEngineConfig.max_notional_per_order` is native and wired through `risk/engine.pyx` (`set_max_notional_per_order`, `_max_notional_per_order`, consulted at `:675`) — CONFIRMED against installed nautilus_trader source; the plan's null-hypothesis claim that Breezy builds no equivalent of this control is accurate.
- Dependency chain on AUD-06a (envelope) and AUD-02 (edge) is explicit, hard-gated at §7 step 0 ("If either is absent, stop: the correct outcome is 'not built'"), and correctly treated as a precondition rather than a soft read.

## Defects

**MATERIAL — inherits AUD-06a's unresolved diagnosis/re-validation gap without an independent check.**
File: AUD-06b-bounded-allocation-sizing.md §6 "`Q_MAX_VALIDATED` is new and is AUD-06a's output"
Issue: This plan treats `Q_MAX_VALIDATED` as a trusted, static constant clamp. Per the AUD-06a review (this reviewer, same round), that constant's provenance has two open gaps: (a) the mechanistic diagnosis behind the envelope is not reconciled with the codebase's own existing, more specific diagnosis, and (b) no re-validation trigger exists if the live ask distribution the envelope was derived from drifts. AUD-06b step 5 ("re-run AUD-06a's sweep (ii) at the realised qty distribution... assert that it binds rather than assuming it does not") is a good defensive step and partially mitigates (b) post-hoc, but it runs only *after* sizing has already gone live at least once — it is a detector, not a precondition gate. AC#6 requires the re-run sweep's CI upper bound ≤ 0.025 but does not require it as a *pre*-merge gate; §7 step 5 places it after GREEN S2/S4b, i.e. after the code ships.
Fix: Either (i) make the re-run sweep at the realised qty distribution a merge-gate precondition rather than a post-merge validation step, or (ii) explicitly accept and state the residual risk that the first live sized cohort under a stale envelope is itself part of the validation loop, with a stated maximum exposure bound for that cohort (e.g., N orders or $ notional) before the sweep confirms or refutes the envelope.

## Per-criterion points
- Fidelity to gap and completeness: 16/20
- Technical correctness and evidence grounding: 16/20
- Implementation specificity and feasibility: 12/15
- Acceptance criteria and validation quality: 15/20 (docked below the author's 16 for the post-hoc-not-precondition ordering of the envelope re-check, above)
- Autonomous operation, failure handling, recovery: 11/15
- Portfolio objective alignment, scope, dependencies: 3/10

**Total: 73/100**

## Required changes to reach 100
1. Move the AUD-06a sweep re-run to a merge-gate precondition, or bound first-cohort exposure explicitly if it must stay post-hoc.
2. Once AUD-06a's review is addressed, this plan's §7 step 0 gate check should also assert the specific envelope re-validation trigger AUD-06a is required to add, not just "a non-empty envelope was published at some point."
3. Author-named: specify `Q_MAX_VALIDATED`'s home module and the depth-staleness bound for the clamp.

## Blockers
- **BLOCKER-A (build, not operator):** AUD-06a must ship first, and per this reviewer's AUD-06a findings, is not yet ready.
- **BLOCKER-B (build, not operator):** AUD-02 must publish an edge estimate for this specific family with CI excluding 0.
- **BLOCKER-C (operator, R-12):** the permit's session order-count ceiling vs. the per-position dollar cap, correctly posed and not decided in-plan.
- **BLOCKER-D (operator):** whether the current per-position cap value is still the intended per-order spend once qty is derived from it — correctly posed and not decided in-plan.
All four are already named as blockers in the plan; none are silently resolved.
