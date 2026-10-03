# AUT-2 r4 (final round): merged review (coordinator). prediction-market-reviewer 93, silent-failure-hunter 90. Final 90; zero CRITICAL or HIGH. Polish to r5.
Duplicates merged: pm M1 and sf M5 are the same defect.

- **P1 [pm M1, sf M5]**: A comparison governs a label, or counts toward `fills_never_position_compared`, only if `snapshot_ns ≥ max(ts_event of the slug's fills) + POSITION_SETTLE_GRACE_S`. Define `fills_never_position_compared`. A label with no governing comparison is `reconciled=False`. Add `test_comparison_before_fill_does_not_reconcile_label`.
- **P2 [pm M2]**: The settlement leg compares the venue YES resolution against `held` for a YES leg and `not held` for a NO leg. Add `test_no_leg_settlement_compare_inverts`.
- **P3 [pm M3]**: `LegacyCrhScorer` with a SELL either asserts that no CRH family has SELL fills, or labels such rows `unattributed` with null P&L. Test it.
- **P4 [pm M4]**: Remove the one-tick tolerance on `slippage_defect`; ARCH L-25 means any fill better than the ask.
- **P5 [pm M5]**: Scope the `realized_pnl == ScoredTrial.pnl × qty` assertion to q=1 entry rows held to settlement. Exits and remainders belong to WP4.
- **P6 [pm M6]**: Add a test that `13:55 + the tally's TimeoutStartSec ≤ 14:15 + LABEL_FLOCK_WAIT_S`, or state the measured tally runtime.
- **P7 [sf M1]**: The intraday and post-STOP timers use `AccuracySec=1s`, `RandomizedDelaySec=0` and `Persistent=false`. Add a deploy test, and have the window arithmetic include the accuracy term.
- **P8 [sf M2]**: `venue_positions_read` has a per-request timeout and an overall deadline (about 60 s post-STOP). On expiry it returns `READ_FAILED, complete=false`, and an INCONCLUSIVE verdict is still written and delivered. Test it.
- **P9 [sf M3]**: The real MISSING_LABEL control is a Scorer that silently drops a fill. A `durable_fill_count` lower than the previous marker's means `FAILED_IDENTITY`.
- **P10 [sf M4]**: A missing or unreadable `capture_epoch_start` while C1 OrderLinks exist, or an OrderLink with `ts_event` before the epoch, makes the fill UNRESOLVED with a CRITICAL `epoch_inconsistent_with_c1`.
- **P11 [sf M6]**: Add a durable write-once skip journal for flock skips. A `venue_only_slug` FAIL fails every family's verdict on that venue. Add a dedup rule for repeated CRITICALs.
- **P12 [sf L1]**: Size `MemoryMax` from the measured scorer peak (about 4 GB), not the skip path.
