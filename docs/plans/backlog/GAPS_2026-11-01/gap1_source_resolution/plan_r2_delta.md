# GAP-1 plan r2 — delta over r1 (architect + prediction-market re-reviews 2026-11-01: REVISE)

Applies on top of `plan_r1.md`; where they differ the delta wins. Status: r2 — confirmation by both reviewers pending.

## R2-1 (PM-1 HIGH / A-1 MED) n_min at the Bonferroni α
`compute_n_min` (`nbp_calibration.py:330-347`) hard-codes z = 1.96. PREREG_GAP1 pins instead
`n_min_adj = ceil(((z_{1−0.05/12} + z_{0.80}) · σ_d / 0.0152)^2)` with z_{1−0.05/12} ≈ 2.64, σ_d from the cell's own paired Brier differences. The S5 reader computes it inline (no change to the byte-pinned `nbp_calibration.py`); `compute_n_min` is reported beside it for reference only. §5 PASS clause 3 and the UNDERPOWERED rule use n_min_adj. New test `test_oof_murphy_n_min_uses_bonferroni_z`.

## R2-2 (PM-2 MED) clause-2 failure is not KILL
A cell that passes clause 1 (resolution) but fails clause 2 (REL_arm > REL_M0) gets the outcome **RES_ONLY_MISCALIBRATED**. It counts toward UNRESOLVED (operator programme decision: recalibrate the source), never toward FAIL or KILL. §5 "Cell outcomes" gains this fourth value; the overall KILL requires every cell FAIL with no PASS, UNDERPOWERED or RES_ONLY_MISCALIBRATED cell.

## R2-3 (PM-3 MED) like-for-like distribution family
If `oof_rows.jsonl` carries an M0 `arm_predictions` entry (unverified #1), M0 is scored from it with its own nu. Otherwise the M0 baseline is scored from the champion spec under BOTH the Normal CDF and the same Student-t family as the arms; ΔRES is reported against both and the PASS rule uses the t-family baseline. The choice is settled at S1 (first RED test pins the schema) and frozen in PREREG_GAP1 before D1 text is frozen.

## R2-4 (A-2 MED) D0 obs-credit rule
At the D0 horizon a cell PASSes only if the arm also beats **M0prime** with point ΔRES > 0 on the same events. Otherwise the cell is labelled "obs-driven, not source" and is treated as FAIL for the source question (it does not contribute to UNRESOLVED). m stays 6.

## R2-5 (A-3 LOW) one look = one run_id
PREREG_GAP1 names the single fixed `<run_id>` for J3. S6 (and the S5 reader) refuse if more than one J3 directory exists under `~/.local/share/breezy/derived/gap1_source_resolution/`. Test `test_gap1_refuses_second_j3_dir`.

## R2-6 (PM LOW) unverified #5 (`resolution_difference` over generic (p, outcome) sequences) is settled at S1, before S3.
