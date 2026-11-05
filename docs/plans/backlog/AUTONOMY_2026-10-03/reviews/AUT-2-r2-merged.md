# AUT-2 r2: merged review (coordinator). prediction-market-reviewer 92, silent-failure-hunter 90. Final 90; 0 CRITICAL/HIGH. NOT READY (bar 95).
All MEDIUM. No contradictions.

## Fold-in items
- **B1 [pm N1]: position-leg fence and grace.**
  - Fence at `ts_event ≤ snapshot_ns − POSITION_SETTLE_GRACE_S`, pinned.
  - `reconciled` is recomputed from the latest compared snapshot, at label_seq+1.
  - Add tests `test_fill_inside_grace_not_compared` and `test_transient_mismatch_clears_on_next_snapshot`.
  - Persist the per-snapshot compare results (`position_compared_snapshot_ns`) as a C2 widening item [sf A4].
- **B2 [pm N2]**: When both legs of a base slug are held, date the offset proceeds at the venue netting event. If that event is not observable, the day is INCONCLUSIVE, never FAIL. Add `test_yes_and_no_same_rung_cash_timing`.
- **B3 [pm N3]**: The fallback trigger is exactly `score_trial`'s basis (`trial_scorer.py:240-250`). Map `venue_settled_without_nws` to `venue_fallback_settlement`. The 7-day pending period raises `aut2.label_lag` by design, pinned by a test.
- **B4 [pm N4]**: Exit-to-entry matching follows the same rule (average-cost or FIFO) as `net_signed_qty` and `reconcile_daily`. Test two entries and one partial exit.
- **B5 [pm N5]**: The proof window starts only after WP7 (C1 live), or the plan states the expected bridge match rate. Add `bridge_match_rate` to the proof artefact.
- **B6 [sf 1, 2, A1, A3]**: Add a `MISSING_LABEL` bucket that counts as failure, so the delete-one-label control has somewhere to land. Add `run_outcome=FAILED_IDENTITY`. Consumers gate on `pending + unattributed > 0`, or an identity breach.
- **B7 [sf 3]**: WP1's `noinput` admits a run only with an explicit `GATED_UNLABELLED_FQ` status in the report. No silent exit 0 over unlabelled FQ fills.
- **B8 [sf 4]**: A pending settlement leg maps to INCONCLUSIVE.
- **B9 [sf 5]**: The cash leg either unions legacy CRH proceeds and capital, or starts its cumulative window after the last legacy settlement.
- **B10 [sf 6]**: In post-STOP mode, run `assert_no_live_node`. A live node means an INCONCLUSIVE verdict and Z19 `unknown`.
- **B11 [sf 7]**: A lock-contention skip in post-STOP mode raises a CRITICAL.
- **B12 [sf 8]**: A `deliver_with_proof` failure exits non-zero.
- **B13 [sf 9]**: Add `p_null_count` to the metrics; above 0 fails the proof day.
