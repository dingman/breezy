# GAP-1 review status (2026-11-01)
- plan_r1.md + plan_r2_delta.md (delta wins) — architect: APPROVE at r2; prediction-market-reviewer: APPROVE at r2. Peer review CLOSED at r2.
- Notes accepted as binding PREREG_GAP1 text at S0 (no re-review needed):
  1. Cell-outcome precedence: UNDERPOWERED > obs-driven (D0) > FAIL (clause 1) > RES_ONLY_MISCALIBRATED > PASS; test `test_oof_murphy_outcome_precedence`. r1 §5 FAIL line reads "clause 1 fails with n ≥ n_min_adj, or a D0 cell is obs-driven".
  2. The D0 M0prime test (R2-4) applies only to a D0 cell that would otherwise PASS clauses 1–3; a clause-2 failure stays RES_ONLY_MISCALIBRATED. M0prime is scored on the same 3-rung ladder and the same distribution family as the R2-3 baseline.
  3. PREREG pins which nu the t-family M0 baseline uses. S5 refuses if the J3 dir name ≠ the PREREG run_id.
