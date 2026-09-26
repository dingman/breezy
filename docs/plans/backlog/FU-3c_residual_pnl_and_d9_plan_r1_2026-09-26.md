# FU-3c plan: residual-fill P&L in the ROI rollup, and D9 no longer gating on settled residuals (r1, 2026-09-26)

Both parts of the row are still unimplemented, so the row should stay open. I did not run the tests. The facts below come from reading `scripts/analysis/portfolio_roi_report.py` at HEAD 442a93d.

## What is still missing
| Question | Finding | Status |
|---|---|---|
| Does the rollup count P&L from residual fills? | No. `_run` sets `total_pnl = total_realised_pnl_all_settled(scored_trials)` (:3299), which only sees ScoredTrials. FU-3b's `ResidualSettlement` (:1013) has `payout` and no P&L, and it only feeds `reconcile_daily` (:3386-3393). Residual *cost* is in the ROI denominator (`total_capital_deployed(fills)`, :3300) but residual P&L is never in the numerator, so `roi`, `roi_minus_b0` and `roi_minus_b1` are biased. The I3 docstring at :682-691 promises the opposite. The only test backing it (:991) feeds a residual as a ScoredTrial, which production never creates (L-24). | **MISSING** |
| What is D9 GATED_UNSETTLED_CAPITAL? | It is the AUD-04 §6 D9 check for filled positions that never settled. `permanently_unsettled_trials` (:1721) keeps every FilledTrial whose `trial_id` has no ScoredTrial and where `now > scheduled_release + 7d + 3d`. If any are kept, `roi_status` becomes GATED (:2240-2242), the D7 reader raises `UnsettledCapitalRoiError` on `roi*`, and the `.unsettled_positions.json` alert fires (:2829). | defined as specified |
| How D9 behaves now | `_run` (:3412) passes `scored_trial_ids=scored_ids` only. A residual never gets a ScoredTrial, so every residual is flagged 10 days after its release even when FU-3b has already settled it. CFJ485874TMM (release 09-14 12:00Z) passed its horizon on 09-24. The FU-3b r1.1 note records the latest report as GATED. | **DEFECT** (the gate never clears) |

## Acceptance Criteria
1. **AC1.** Each settled residual adds `qty × (1{held} − fill_px − fee)` to a new `realised_pnl_residual_total`. `fill_px` and `fee` come from the FilledTrial and are per-contract. With the fixture fill_px 0.70, fee 0, the CFJ485874TMM case gives +0.30.
2. **AC2.** `roi` and the baselines use `realised_pnl_after_fees_total + realised_pnl_residual_total` as the numerator. The denominator is unchanged.
3. **AC3.** `realised_pnl_after_fees_total` and `trial_rows` stay scored-only and unchanged, so the sum identity at test :1839 and AUD-07's hold-P&L check (`current_rung_hold_exit_window_study.py:335-354`) stay exact.
4. **AC4.** D9 treats a trial as settled if it is in `scored_ids ∪ {s.trial_id for s in residual_settlements}`. Residuals that are pending or unresolved and past their horizon are **still flagged**, so the gate stays fail-closed.
5. **AC5.** PREREG is untouched. Residual P&L never reaches `admissible_scored_trials`, `n_scored`, `trial_rows`, the `lags` sample, the scored-trial store or `family_tally_v2`.
6. **AC6.** With no residual inputs the output matches today's, apart from the new keys and the version stamp. Every settlement and contract test passes unmodified.
7. **AC7.** No journal or D6 line carries an amount. Only the PRIVATE JSON and MD do.

## Edge cases
- **A trial that is both scored and residual** (the 09-15 MIA `^no` contradiction). It is already dropped from residual resolution (`residual_ids − scored_ids`, :3378), so it is neither counted twice nor has its P&L added twice.
- **A NO-leg residual.** `held` comes from `score_trial`'s leg logic, and both legs must be tested (L-44).
- **Multi-contract residuals.** P&L scales with qty. The scored path does *not* scale with qty (`trial_scorer.py:206`); see Risks.
- **A fee_unverified residual.** P&L uses the ledger fee (0 for CFJ485874TMM), consistent with `capital_deployed`. The venue's true fee was 0.01, so this row reads up to 1¢ high. This is noted, not corrected; correcting it would need venue egress.
- **Pending or unresolved residuals.** They contribute no P&L and are counted by the existing `n_residual_*` fields. Past the horizon they remain in D9, which is correct.
- **A residual with a SELL fill.** FU-3b skips these, so they contribute no P&L and D9 still flags them past the horizon. That is the conservative outcome; it is noted in the report and needs no new logic.
- **Venue-fallback basis.** A residual settled on `venue_last_fair_price_fallback` counts as settled for D9, the same as the scored path.

## Architecture
All changes are in the analysis script. There is no `src/` change, Nautilus is untouched, and there is no live-path change.

**Decision 1 (P&L carrier).** Add a required `realised_pnl: Decimal` field to `ResidualSettlement` and compute it inside `residual_settlement()`, next to the payout.
- Rejected: a separate function over (trial, settlement) pairs, because `_resolve_residual_settlements` would then have to return the trials as well.
- Cost: the one direct construction at test :3155 gains a kwarg. That is an additive fixture edit, not a weakened assertion.

**Decision 2 (ROI semantics). The key trade-off.**
- **R1 (chosen):** fold residual P&L into the `roi` numerator and bump `PORTFOLIO_ROI_SCHEMA_VERSION` to 3. D7 requires a bump for any semantic change. The reader accepts {1, 2, 3}.
  - For: `roi` becomes the account ROI that AUD-04 I3 specifies.
  - Cost: tests that pin `schema_version == 2` need updating, and the AUD-06b and AUD-07 readers need a {1, 2, 3} check.
- **R2 (fallback if peer review rejects the bump):** leave `roi` scored-only and add `roi_portfolio` as an additive v2 field. This means no bump, but the headline stays biased and every consumer has to opt in.
- **Rejected:** folding residual P&L into `realised_pnl_after_fees_total`, because it breaks the `trial_rows` sum identity and the AUD-07 reconciliation.

**Decision 3 (D9).** Change only the call site at :3412. The pure `permanently_unsettled_trials` and its horizon constants stay unchanged. "Settled" is defined as "`score_trial` produced an outcome", the same rule on both paths.

## File-by-File
1. **`scripts/analysis/portfolio_roi_report.py`**
   - Add `ResidualSettlement.realised_pnl` and set it in `residual_settlement()` (:1047-1074) as `trial.qty * (held − fill_px − fee)`.
   - Add a pure `total_realised_pnl_residual(settlements) -> Decimal` next to :682.
   - In `_run`, move the `roi_against_baselines` call (:3301) after `_resolve_residual_settlements` (:3375) and pass `total_realised_pnl=total_pnl + residual_pnl`. It must stay inside the same `UnknownOrderSideError` try block.
   - At :3412, pass `scored_trial_ids=scored_ids | frozenset(s.trial_id for s in residual_settlements)`.
   - `PortfolioRoiReportData` and `build_portfolio_roi_report_data` get new fields `realised_pnl_residual_total` (default 0) and `realised_pnl_portfolio_total`.
   - Update the JSON writer, the reader view (absent key → `None` for v1/v2), the markdown P&L block (both lines side by side), the version bump to 3 and `_KNOWN_…` to {1, 2, 3}.
2. **`tests/unit/test_portfolio_roi_report.py`**
   - Add the tests below.
   - Add the kwarg at :3155.
   - Update the schema-version pins to 3.
3. **`scripts/analysis/current_rung_hold_exit_window_study.py`**
   - Check only that its reader path accepts v3. No logic change.
4. **`docs/core/PROGRESS.md`**
   - Close FU-3c on merge.
   - Add an FU-3d row for the scored-path qty issue (see Risks).

## Test Strategy (RED first; class `TestResidualPnlAndD9`)
- `test_a_winning_yes_residual_realised_pnl_is_qty_times_one_minus_px_minus_fee`: RED because the field does not exist yet.
- `test_a_losing_no_leg_residual_realised_pnl_is_negative_cost` (L-44).
- `test_a_multi_contract_residual_pnl_scales_with_qty`.
- `test_roi_numerator_includes_residual_realised_pnl`: RED today because `roi` misses the +0.30.
- `test_trial_rows_sum_still_equals_realised_pnl_after_fees_total_with_residuals`: an invariant guard (AC3).
- `test_residual_pnl_never_enters_admissible_or_n_scored`: a characterisation test, backed by mutation evidence (L-33). The mutant that folds residual P&L into `scored_trials` must be killed.
- `test_d9_does_not_flag_a_settled_residual_past_horizon`: RED today, because it is GATED at release + 11 days.
- `test_d9_still_flags_a_pending_residual_past_horizon`: the negative half. Ungating everything would fail it.
- `test_d9_still_flags_an_unresolved_residual_past_horizon`.
- `test_a_trial_both_scored_and_residual_contributes_pnl_once`.
- `test_reader_accepts_v3_and_reads_absent_residual_pnl_as_none_on_v2`.
- `test_run_cfj485874tmm_shape_is_roi_ok_with_residual_pnl_through_real_writers`: an end-to-end `_run` test using `_append_excluded_fills`, the real NWS catalog writer and the exec-state fixtures (L-42). It asserts `roi_status == "OK"` and the residual total is +0.30.
- **Gate:** `scripts/ci/run_tests_no_egress.sh`, lint-imports, and the settlement purity guard untouched. Read the exit code, not `-q` output.

## Risks
- **[HIGH] Premise to check first (read-only).** Confirm that the latest PRIVATE report's `permanently_unsettled` trial_ids are all residual ids with a settlement-grade NWS FINAL.
  - If any are scored-path or have no FINAL, this fix does **not** clear GATED, and that trial is a separate stuck-position finding.
  - The report path is outside the repo; my Glob found no copy.
- **[MED] Adjacent defect, outside this scope (FU-3d).** Scored `pnl` is per-contract (`trial_scorer.py:206`, no `qty`), while capital is per-fill. Any scored trial with qty>1 understates the numerator.
  - Residual P&L deliberately uses qty to stay consistent with cash, so the two paths differ until FU-3d lands.
  - Fixing it needs care: it touches `trial_rows` and AUD-07.
- **[MED] Schema bump ripple (R1).** Every v2 pin and consumer has to accept v3. If peer review prefers fewer moving parts, switch to R2.
- **[LOW] Fee-unverified residual P&L can be off by ≤1¢.** Stated in the report.
- **[LOW] Masking.** D9 only un-flags residuals that have a settlement record. A residual that never settles still gates, so the control is not weakened.

## LESSONS compliance
I checked these headers exist in `docs/core/LESSONS.md` before citing them:
- **L-12** (620): no tolerance or barrier is relaxed.
- **L-24** (1069): the new end-to-end test uses the production shape instead of the ScoredTrial-residual fixture at :991.
- **L-33** (1282): mutation evidence for the characterisation guard.
- **L-42** (1419): the `_run` test writes through the real writers.
- **L-44** (1452): both legs tested.
- **L-51** (1582): if this is built in a worktree, never run `uv sync` or `git stash`.

## Confidence
- **HIGH** that both gaps are real and that the D9 call-site fix is correct and PREREG-safe.
- **MEDIUM-HIGH** on R1 over R2; this is a judgement call for peer review.
- **MEDIUM** that this alone clears today's GATED status, until the premise check is done.
- Peer review needed: prediction-market-reviewer (P&L maths, leg, fee basis) and python-reviewer (schema and reader).

## r1.1: peer review converged (2026-09-26)
- **prediction-market-reviewer: HIGH, no blockers.** The formula is leg-correct: `FilledTrial.fill_px` is already the leg price and `fee` is per-contract. R1 is correct under AUD-04 I3. D9 fails closed. PREREG is preserved.
- **python-reviewer: HIGH, APPROVE.** All citations were verified. Moving the ordering is safe. The only importer of the schema is `current_rung_hold_exit_window_study.py`, and it needs no logic change.
- **Premise check: CONFIRMED.** The 09-25 report's two gating ids are MIA 09-13 and SFO 09-11. Both are residuals (`fee_unverified`) that settle on `nws_final`, so the fix clears GATED.

Amendments folded in:
- **Correction.** AUD-06b has no current consumer, so "update the AUD-06b reader" is dropped. The v3 ripple is `read_portfolio_roi_report`'s version gate and the test pins, nothing else.
- **Divergence label.** The markdown P&L block must label the qty divergence (FU-3d) in the report output itself: "residual P&L is qty-scaled; scored P&L is per-contract until FU-3d".
- **FU-3d** is added to PROGRESS as its own row (scored-path qty scaling), with a note to track the residual bias from `fee_unverified` (≤1¢ per contract).

## r1.2 erratum (FU-3d, 2026-09-26)
- **"≤1¢ per contract" is false for p in [~0.326, ~0.674].** The fee rounds
  to 0.02, not 0.01, whenever `theta * p * (1-p) >= 0.015`. At the post-drift
  `theta=0.0695`, that band is p in [~0.326, ~0.674], which contains p=0.5.
  Worked examples: at theta=0.0695, p=0.5, the exact fee is 0.017375, which
  rounds half-even to **0.02**; the pre-drift `theta=0.06`, p=0.5 case is
  0.015, which also rounds half-even to 0.02. The original CFJ485874TMM
  example (theta=0.0695, p=0.70) is 0.014595, which rounds to 0.01 and is
  outside the band -- that specific worked example was never wrong, but the
  general "≤1¢" claim it was generalised into is. See FU-3d AC4 (the
  Markdown-only `fee_unverified residuals` disclosure line), which reports
  the modelled-minus-recorded delta as a signed, per-run-computed quantity
  rather than repeating this now-corrected bound.
