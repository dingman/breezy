# AUD-18 — Round 1 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: b88c72daed16d16fe544c5ee46aee7b7d252ee9df7bcb90da2d7e64f81f214ad
Round: 1

## Claims verified against artefact

- G-02 wording (`AUTONOMY_ROI_AUDIT_2026-09-21.md:37-43`): CONFIRMED, verdict FALSE as cited.
- `PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md` §1 (i-v): CONFIRMED matches plan's paraphrase (bounded K=12, Holm-Bonferroni at selection, declared-cap escalation, full logging, freeze-date firewall).
- AUD-02 "fresh LD-OBF α" citation (line 83/368): CONFIRMED.
- `combine_station_day`/`score_combined` signatures (`current_rung_hold_v2.py:298,348`): CONFIRMED, fee-aware per-row via `break_even_row`, mutual-exclusivity/admission-gate logic matches plan's description.
- AUD-09 B18 / AUD-10 C19 "named script set" property: CONFIRMED the mechanism exists, but REFUTED as applied — AUD-09 §6b.3 states verbatim "an unnamed fourth still fails," naming exactly three sanctioned scripts (census, runner, and AUD-10b's `promotion_proposal.py` as "the sanctioned third invocation"). AUD-18 §6.4/§7 step 5 asserts `hypothesis_triage.py` becomes a fourth sanctioned invocation without amending AUD-09's or AUD-10's plan text to add it to that named set. AUD-18's own §13 flags this as "un-verified," but the cited source is not silent — it is contradictory to the plan's claim as written.
- AUD-02 §12/§518 "operator budget ceiling" blocker: CONFIRMED AUD-18 §12 restates it verbatim ("exactly as AUD-02 §12 states").

## Defects

**MATERIAL — cross-plan invocation-set contradiction not resolved (§6.4, §7 step 5, D5).** Adding `hypothesis_triage.py` as a fourth `"$PY"` invocation to AUD-09a's wrapper requires amending AUD-09's B18 and AUD-10's C19 named-script sets in those plan bodies; AUD-18 does not add this as a dependency/step, and as currently specified elsewhere the test suite would fail on an unnamed fourth invocation. Required change: add an explicit step (and a named dependency in §4) to amend AUD-09 §6b.3/B18 and AUD-10's C19 to include `hypothesis_triage.py` as the sanctioned fourth invocation, or restate D5 so it is executable without editing sibling plans.

**MATERIAL — external blockers should be internal peer-ruling steps (§7 step 8, §12, §6.6).** Per operator delegation, the "strategy-lead-set horizon" for first-intake registrations is left as an open external blocker ("this plan specifies the mechanism, not the horizon value") rather than a named peer-ruling step producing a `docs/evidence/` artefact. Required change: replace the strategy-lead blocker with a concrete step dispatching the horizon decision to the engineering peers (e.g., trading-bot-architect + prediction-market-reviewer), writing a dated ruling artefact under `docs/evidence/`, then registering — matching how this repo already handles PREREG-semantics rulings elsewhere.

**MATERIAL — stale "operator budget ceiling" blocker (§12).** The operator states the budget ceiling is already established (two caps in `operator.env`); restating "arms nothing without an operator budget ceiling this plan never values" is stale unless it specifically means live-trading enablement for a new family, which the plan does not say. Required change: remove the line or reword it to name live-trading enablement specifically as the operator-reserved gate, distinct from budget.

**MINOR — length.** 473 lines vs the stated 120-250 target; the §6.3 disposition table and citation density are load-bearing, not padding, but the plan could trim §11 (portfolio-alignment prose largely restates §3).

No duplication of AUD-09/10/11/12 found; Kalshi exclusion is justified by existing memory/PROGRESS state; PREREG semantics, `allow_short`, and the NO-SEND firewall are untouched; no operator cap is assigned a value.

## Scoring (20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 15/20 — leaves horizon-setting external rather than as an internal peer-ruling step, undercutting the "closed loop" claim.
- Technical correctness and evidence grounding: 13/20 — the B18/C19 fourth-invocation claim is contradicted by the cited source text, not merely unverified.
- Implementation specificity and feasibility: 11/15 — Holm-Bonferroni bootstrap CI inside `hypothesis_triage.py` is cited by primitive, not specified; cross-plan amendment step missing.
- Acceptance criteria and validation quality: 14/20 — D1-D4,D6-D8 are objective and testable; D5 is not achievable as written without editing sibling plans.
- Autonomous operation, failure handling, recovery: 10/15 — first intake (step 8) is gated on an external, unconverted blocker rather than an in-plan ruling step.
- Portfolio alignment, scope and dependencies: 9/10 — dependencies named by id, Kalshi/strategy-code exclusions well-scoped.

**Total: 72/100.**

## Blockers

None that are genuinely external. The two items AUD-18 frames as blockers (strategy-lead horizon, operator budget ceiling) are, per operator context supplied to this review, plan defects to fix internally (peer-ruling step + evidence artefact; remove stale budget line) — not legitimate external blockers.
