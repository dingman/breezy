# AUD-07 review — round 1 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-07-exit-seam-arming-verification-path.md
sha256: 6f61ef6ae29b60b25d07fbfff5fc3e3fb254d9f1a35eeb174a52742bc2f8e44e
Round: 1

## Claims verified
- `exit_gate.py:55` `_EXIT_RULE_REGISTERED_FAMILIES = frozenset({"pm_us_crh_exit_v4"})` — CONFIRMED.
- `deploy/families/pm_us_crh_exit_v4.json`: `d0_climate_day: "2099-01-01"`, `boundary_inputs_sha256`/`density_artefact_sha256` all-zero placeholders, `taker_fee_coefficient: "0.06"` (vs live "0.0695"), `composition_kind: "current_rung_hold"` (vs live "continuous_rung_hold"), `status: "DRAFT_NOT_REGISTERED"`, and **no `exit_rule` key present at all** — CONFIRMED on every point.
- Live artefact 0-vs-5 disagreement (§3 finding C): `position_monitor_report_2026-09-20.md` reads `family: pm_us_crh_cont`, `positions: 0 (settled 0, unsettled 0)`, `settled by source: scored_trials=0 summary=0` — CONFIRMED verbatim on disk. `exit_window_study/2026-09-20_nightly/exit_window_study.md` reads `n_positions=5` — CONFIRMED.
- Finding B's drift figures: `sum_r_best_pnl=-0.0400` and `median_minutes_last_executable_to_threatened=-74.11908...` (negative) — CONFIRMED verbatim against the live artefact, matching the plan's citation exactly, including the negative sign the plan flags as needing settlement before any gate reading.

## Task-specific challenge answered
**Does the plan require the drift (finding B) be explained before any arming evidence is accepted?** Yes, and this is well-designed: §7 step 5 requires establishing the drift's cause before Rev 3 is written; AC#4 requires "ONE step-0 table with stated provenance"; and §9's first bullet is an explicit anti-momentum guard: "If the reconciled table shows R-THREAT/R-DEAD passing their gates, that is **not** an arming trigger... a gate passed on N≈4-6 'licenses arming for measurement, never a claim of edge'." This directly forecloses the failure mode of reading a favorable-looking reconciled number as sufficient evidence to arm. No defect found here.

## Defects

**MINOR — the negative `median_minutes_last_executable_to_threatened` is flagged but not diagnosed within this plan's own scope.**
File: AUD-07-exit-seam-arming-verification-path.md §12 "Unresolved"
Issue: The plan correctly identifies that a negative value here is either a real ordering property or a sign-convention bug, and correctly states it "must be settled before the table is read against a gate." But no step in §7 explicitly assigns this to step 5 (the B reconciliation) as a checkable sub-task with its own acceptance test — it is listed only as an open question in §12, which risks the reconciliation being written up without this specific anomaly being resolved (as opposed to merely re-observed).
Fix: Fold "resolve whether the negative `median_minutes_last_executable_to_threatened` is a real ordering property or a sign-convention defect" into §7 step 5 as an explicit sub-step with a test (e.g., a synthetic THREATENED-after-exit-side-empties fixture built through the real writer path asserting the sign the code should produce), not just a Rev 3 narrative note.

No MATERIAL defect found. N=5 sample-size honesty is well handled: §11 states plainly that the "structural ceiling of any exit policy on that tape is small," the item's ROI claim is explicitly protective/near-zero rather than additive, and nothing in the plan treats N=5 as sufficient for a decision — it is used only to detect measurement defects (0-vs-5 binding, drift), which is a legitimate use of a small N.

## Per-criterion points
- Fidelity to gap and completeness: 18/20
- Technical correctness and evidence grounding: 17/20
- Implementation specificity and feasibility: 11/15
- Acceptance criteria and validation quality: 17/20
- Autonomous operation, failure handling, recovery: 12/15
- Portfolio objective alignment, scope, dependencies: 5/10

**Total: 80/100**

## Required changes to reach 100
1. Fold the negative-median resolution into §7 step 5 as a testable sub-step (above).
2. Author-named: locate the position-monitor report's actual position-sourcing code path before step 1, rather than leaving that discovery implicit in "fix the family binding."
3. Author-named: specify the `EXIT_CORPUS_FROZEN` alert's dedupe/latch mechanism concretely.

## Blockers
- **BLOCKER-1 (dependency in fact):** corpus cannot grow until trading resumes (G-01) — correctly named, not owned by this plan.
- **BLOCKER-2 (operator + PREREG):** arming requires PREREG v4 registration and the operator-only 1-lot positive control — correctly out of scope by construction.
- **BLOCKER-3 (strategy lead):** v4's boundary package inherits whatever AUD-06a determines about boundary validity — correctly flagged, not resolved here.
