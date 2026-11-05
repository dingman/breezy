# FU-3b: residual-fill settlement payouts in `reconcile_daily` (plan r1, 2026-09-26; UNDER PEER REVIEW)

**Defect.** Verified in `docs/evidence/FU-3_capital_flow_attribution_2026-09-26.md`. `scripts/analysis/portfolio_roi_report.py` counts settlement proceeds only from ScoredTrials. A RESIDUAL fill (for example one excluded as `fee_unverified`, recorded in `excluded_fills.jsonl`) has its cost counted in capital, but its payout is never counted. The result was a false +$0.99 `UNEXPLAINED_CAPITAL_FLOW` for the window ending 09-14, from order CFJ485874TMM (MIA 09-13, gte91lt92, YES, won).

**Scope.** Cash reconciliation only. No change to `src/`, `trial_scorer.py`, `score_live_trials.py` or `residual_fills.py`, and no live-path change.

## Acceptance criteria
1. The 09-14 window with CFJ485874TMM classifies as `OK`: |unexplained| ≤ 0.01. Depending on the ledger fee it comes out at 0.00 or −0.01.
2. A residual's payout is `qty × 1{held}`, where `held` comes from `score_trial` and is computed for both the YES and the NO leg.
3. Residual payouts never reach `ScoredTrial`, the scored-trial store, `admissible_scored_trials`, `n_scored`, `trial_rows`, the `lags` sample (`compute_settled_through`), or `total_realised_pnl_*`.
4. A residual with no settlement-grade record adds no payout. From release day through today it is tagged `UNEXPLAINED_PROXY_LAG`, never `UNEXPLAINED_CAPITAL_FLOW`, and it is counted.
5. With no residual inputs, the output is byte-identical to today's, and every existing test passes unmodified.

## Options considered
| Option | Verdict |
|---|---|
| **(a) In-report pure re-score.** Call `score_trial(FilledTrial, NwsClimateDay)` (`trial_scorer.py:163-227`: pure, AST-guarded). `_run` already holds the residual FilledTrials (:2959), with `scheduled_release_at_ns` (:2808). | **CHOSEN** |
| (a2) The scorer persists a `residual_settlements.jsonl` sidecar | Rejected. It adds a writer next to a PREREG-adjacent store that `family_tally_v2` reads. |
| (b) Use venue POSITION_RESOLUTION | Rejected. The record carries no cash, and it would need venue egress from an analysis script. |
| (c) Back the payout out of the balance delta | Rejected as circular. |

**Dating.** Date the payout at `scheduled_release_at_ns`, never at `scored_at_ns=now_ns`. The venue can pay later than the scheduled release, so release_day and release_day+1 are proxy-lag candidates; this reuses `UNEXPLAINED_PROXY_LAG_LABEL`, so there is no schema bump.

## Design (all in `portfolio_roi_report.py`)
**Pure core, near :955.**
- New frozen types `ResidualSettlement(trial_id, climate_day, payout, dated_at_ns, settlement_basis)` and `ResidualPending(trial_id, release_day)`.
- New function `residual_settlement(trial, record, *, now_ns)`. It calls `score_trial` and keeps the ScoredTrial local. It computes the payout as qty × held, not `settlement_payout()`, which is per-contract.

**Cash accounting.**
- `_cash_between` (:891): new kwarg `residual_settlements=()`. It sums payouts with `after_ts < dated_at_ns <= through_ts` and keeps the same 3-tuple return.
- `reconcile_daily` (:1257): new kwargs `residual_settlements=()` and `residual_pending=()`. Pass them into both `_cash_between` calls (the window loop and the G1 opening row), then merge into `proxy_lag_days`:
  - settled: {release_day, release_day+1}
  - pending: release_day through today

**Resolution shell, near :2823: `_resolve_residual_settlements(...)`.**
- Rung: `_read_bucket_facts_by_instrument_id`, falling back to `_bucket_facts_from_instrument_id`.
- Record: `read_climate_day_including_corrections(open_station_catalog(catalog_base, venue, station), ...)`.
- Best-effort per trial. An unresolved trial increments `n_residual_unresolved` and is logged by type name only.
- A residual with any SELL fill is skipped and counted.

**Population.**
- `buckets[FillBucket.RESIDUAL]`, deduplicated by trial_id.
- If a trial_id is in both `scored_ids` and the residual set, skip it here, because the scored row already pays it.

**Run wiring and outputs.**
- `_run`/`main`: add a `catalog_base` parameter, defaulting to `score_live_trials.DEFAULT_NWS_CATALOG_BASE`.
- Add additive counts `n_residual_settlements`, `n_residual_pending`, `n_residual_unresolved`. The reader tolerates their absence, the same way it does for `n_duplicate_scored_trials`.
- The D6 journal line carries counts only.

## Tests (`tests/unit/test_portfolio_roi_report.py::TestResidualSettlementCash`)
- `test_a_winning_yes_residual_pays_qty_times_one`
- `test_a_no_leg_residual_holds_when_high_is_outside_the_rung` (L-44)
- `test_a_multi_fill_residual_payout_scales_with_qty` (RED: reusing `settlement_payout` pays 1.00)
- `test_a_residual_payout_is_dated_at_scheduled_release_not_scored_at`
- `test_fu3b_0914_cfj485874tmm_residual_payout_reconciles_ok`: the regression case. Synthetic balances 100.00→100.29; RED today because it yields `UNEXPLAINED_CAPITAL_FLOW` +0.99.
- `test_a_pending_residual_past_release_is_proxy_lag_not_capital_flow`
- `test_a_trial_both_scored_and_residual_pays_once`
- `test_residual_settlements_never_enter_scored_statistics`: a characterisation guard. Back it with mutation evidence (L-33).
- `test_run_reconciles_a_residual_written_through_the_real_writers` (L-42): uses `_append_excluded_fills`, the real NWS catalog writer, and the `_run` fixtures.

## Risks
- **[HIGH] Verify two premises before implementing.** These are read-only lookups:
  - (i) MIA 09-13's `scheduled_release_at_ns` falls between the 09-13 and 09-14 snapshots.
  - (ii) CFJ485874TMM's ledger `cumulative_fee` (0.00 or 0.01) fixes the fixture's exact expected value.
- **[MED] A proxy-lag tag can mask a real flow on those days.** It only reclassifies. The amount stays in the cumulative figure, and the tag is bounded.
- **[MED] Each fee-unverified fill leaves up to 1¢ of residual,** which sits at the tolerance edge. Noted, not fixed. Widening the tolerance would be a PREREG-adjacent relaxation (L-12).
- **[MED] Adjacent defects, proposed as FU-3c:**
  - (1) `total_realised_pnl_all_settled` never sees residual P&L. In production a residual never produces a ScoredTrial (`score_live_trials.py:1465-1467`), and the test at :974 uses a fixture shape production never creates (L-24).
  - (2) Unverified inference: D9 `permanently_unsettled_trials` flags every residual past its horizon, so the ROI may be GATED right now. Verify `roi_status`.
- **[LOW] Importing private names script-to-script** from `score_live_trials`.

**Confidence.** HIGH that option (a) is correct and PREREG-safe. MEDIUM on the exact fixture values until premises (i) and (ii) are checked.

## r1.1 (peer review converged: prediction-market-reviewer APPROVE; python-reviewer MEDIUM → blockers applied)
- **Premises verified.**
  - (i) MIA 09-13 `scheduled_release_at_ns` = 2026-09-14T12:00:00Z. It falls between the snapshots at 09-13 16:50:13Z and 09-14 16:50:24Z.
  - (ii) Ledger for CFJ485874TMM: `cumulativeCost=0.70`, `cumulativeFee=0`, `feeReconciled=false`. The venue cost was 0.71.
- **Regression fixture.** Capital 0.70, payout 1.00, Δbalance +0.29, so unexplained = −0.01, which classifies as OK because it is within the one-fill tolerance.
- **Blocker (a).** The resolution shell catches a CLOSED, named exception tuple, modelled on `station_candidate_register._READ_ERRORS`. It never uses a broad `except Exception`.
- **Blocker (b).** Log `trial_id`, `type(exc).__name__` and the message, matching `_run`'s existing handlers. Amounts never appear in the log.
- **Wiring.** `_resolve_residual_settlements` runs after `filled_trials` is materialized (≈:3070-3072), not at :2823. It takes the RESIDUAL-bucket trials from that list, and its results feed `reconcile_daily`.
- **Context.** The latest report's `roi_status` = `GATED_UNSETTLED_CAPITAL`. This is FU-3c, out of scope here.
