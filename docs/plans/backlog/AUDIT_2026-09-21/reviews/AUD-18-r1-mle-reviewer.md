# AUD-18 round-1 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: b88c72daed16d16fe544c5ee46aee7b7d252ee9df7bcb90da2d7e64f81f214ad
Round: 1
Reviewer: mle-reviewer (independent, blind)

## Claims verified

- `combine_station_day`/`score_combined` at `settlement/current_rung_hold_v2.py:298,348` — CONFIRMED (`src/breezy/settlement/current_rung_hold_v2.py:298,348`).
- `resolve_alert_sink`/`emit_alert` at `runtime/health.py:579,668` — CONFIRMED (`src/breezy/runtime/health.py:579,668`).
- `load_realized_draws` at `settlement/current_rung_hold_v2.py:249` — REFUTED. It is defined at `src/breezy/persistence/realized_draws.py:249` — a different file, same line number by coincidence. The plan's §6.4 step 4 citation misattributes the file.
- PREREG_WP7_MULTIPLICITY_RULE precedent (bounded enumeration, Holm-Bonferroni at the *selection* decision, declared cap, freeze-date firewall) — CONFIRMED as described.
- `src/breezy/analysis/` does not yet exist and AUD-09 already reserves the third `"$PY"` wrapper-invocation slot (AUD-09 §6b.4/B18) — CONFIRMED; AUD-18 would be a fourth invocation into the same wrapper, a claim the plan's own §13 admits is unverified.
- AUD-02 §12 operator-budget-ceiling blocker — CONFIRMED as concerning live arming/enablement, so retained per operator carve-out (a); not a defect.

## Defects

1. **MATERIAL — mis-cited source file (§6.4 step 4).** `load_realized_draws` is attributed to `current_rung_hold_v2.py:249`; it lives in `persistence/realized_draws.py:249`. Required change: fix the citation before an implementer wires the wrong import.
2. **MATERIAL — no "already-looked" guard specified for per-variant evaluation (§6.4 steps 3–4, §8 D2/D3).** `min_station_days` sufficiency is recomputed nightly for `EVALUATING` hypotheses, and a `HypothesisLook` row is keyed on `(hypothesis_id, variant_id, looked_at)` — distinct timestamps are not rejected. Nothing in the spec states a variant already looked at is skipped on a later run. Holm-Bonferroni (fixed-sample, multi-comparison) is the only correction named; it is not a valid substitute for group-sequential/alpha-spending control (the repo's own LD-OBF precedent, cited from AUD-02 §3) if the same variant can be re-tested as its station-day count keeps growing. Required change: state explicitly that a variant with an existing `HypothesisLook` row is never re-evaluated (one look, ever, per variant), or specify an alpha-spending boundary for repeated looks — and add a RED test for whichever is chosen.
3. **MATERIAL — §12 "strategy lead" blocker not converted per operator instruction.** Per this review's operator context, a "strategy lead must set X" blocker should be a named peer-ruling step producing a `docs/evidence/` artefact, not an open external blocker. The plan leaves the first-intake horizon (§7 step 8, §12) as an undecided external blocker. Required change: replace it with a named peer-ruling step (who rules, what artefact, default value absent a ruling) mirroring this backlog's own `RULING_*` convention.
4. **MINOR — length.** 473 lines vs the 120–250 target; §6.3's evidence table and the embedded §13 self-review (pre-scored baseline inside the plan body, unusual placement — review records belong under `reviews/`) are the main excess. Recommend trimming §6.3 to reference existing docs and moving/removing the embedded self-score.
5. **MINOR — D6 is a one-time hand check** ("observed by hand once"), not an automated/repeatable gate for "zero live-path state changes." Acceptable for a governance-layer item but weaker than the plan's other criteria.

## Per-criterion scoring

- Fidelity to audit gap and completeness: 16/20 — correctly scopes AUD-18 as the evidence engine AUD-02 needs and honestly allows programme KILL as a valid terminal state; docked for defect 3 (operator-directed blocker conversion missed).
- Technical correctness and evidence grounding: 14/20 — one verified mis-citation (defect 1) and one unaddressed statistical-soundness gap (defect 2) in the plan's central mechanism.
- Implementation specificity and feasibility: 10/15 — ledger/triage script are concretely specified but the per-variant re-look guard (defect 2) and the fourth-wrapper-slot question are left for the implementer to resolve.
- Acceptance criteria and validation quality: 15/20 — D1–D8 are objective and testable but omit a criterion covering the "no re-look" invariant; D6 is weak (defect 5).
- Autonomous operation, failure handling and recovery: 12/15 — reuses existing lock/slice/atomic-write discipline and a PARKED-horizon alert; crash-mid-look recovery is asserted, not independently tested (plan's own admission).
- Portfolio objective alignment, scope and dependencies: 8/10 — dependencies named by id, exclusions (Kalshi, no new strategy code, no new unit) are crisp; docked slightly for scope bloat (defect 4).

**Total: 75/100**

## Blockers

- Defect 3 requires an operator/peer-ruling artefact under `docs/evidence/` before the first-intake horizon can be registered — this is a blocker, not a waivable deduction, per the reviewer brief's operator context.
- No other unavailable-evidence blockers found; defects 1 and 2 are author-fixable without external input.
