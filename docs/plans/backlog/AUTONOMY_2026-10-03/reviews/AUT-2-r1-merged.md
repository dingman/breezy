# AUT-2 r1: merged review (coordinator). silent-failure-hunter 82, prediction-market-reviewer 80. Final 80, NOT READY.
No contradictions between reviewers. Duplicates merged.

## HIGH
- **A1 [sf1]: completeness denominator.** Each run and the proof assert `labelled + explicitly-excluded == durable fill count` from the exec store, with `unattributed == 0`. Legacy CRH fills are covered too. Add `test_labelled_plus_excluded_equals_durable_count`, with a positive control (delete one label → FAIL).
- **A2 [sf2, sf3]: label_lag.**
  - Measure lag against the first admissible or finally-excluded label.
  - `window_incomplete` older than 48 h → FAIL.
  - Alert on every live `fee_unreconciled` fill.
  - The lag clock starts at the venue settlement time derived from the climate day, not at CLI ingest. Add a test with no CLI final, which must FAIL at 24 h.
- **A3 [sf5]: no "skipped" success.**
  - NO_INPUT is allowed only when the durable count of unlabelled settled fills is 0.
  - The marker carries the pending, excluded and labelled counts. Consumers go GATED when pending > 0.
  - An unreadable store never yields NO_INPUT or exit 0. Test it.
- **A4 [pm1, sf6]: position-leg coverage.**
  - Add a pre-settlement snapshot (about 11:00Z, or a post-fill pull). A settled label inherits from the last snapshot at or after its fill and before settlement. No such snapshot is a coverage FAIL, not UNKNOWN.
  - A missing or stale snapshot is INCONCLUSIVE plus an alert. Report `fills_never_position_compared`. Alert after k consecutive INCONCLUSIVE days, with the same rule for BALANCE_UNKNOWN.
- **A5 [pm2]**: `p_at_decision` is the probability of the BOUGHT leg. Give the conversion rule from the Take side. Add tests for a NO-leg Take in both the pre-C1 bridge and C1 modes.
- **A6 [pm3]**: The compared set is ledger slugs ∪ venue-page slugs. A venue slug with no ledger fill is a FAIL. A ledger slug that is open and missing from the page compares as venue 0. "Open" comes from market status and settlement time. Add tests.
- **A7 [sf4, pm10]**: The slippage-defect reason is a persisted column, with a C2 enum widening that must land before any label write. An `unattributed` fill writes a durable HEALTH event.

## MEDIUM
- **A8 [pm4]: cash leg.** Use the cumulative net identity with open cost held out, and the correct `per_day_tolerance` argument. Add a test with a mixed day.
- **A9 [pm5]**: A venue fallback settlement sets `realized_pnl` to null and the row to pending until the payout is read. Test it.
- **A10 [pm6]**: Own a cross-plan acceptance test: an armed family composed with a RefusingPlugin scorer is refused. This is a hard prerequisite on AUT-5a.
- **A11 [pm7]**: `cost_basis` and the hold counterfactual are fee-inclusive. Partial exits are pro rata. Test a partial NO-leg exit.
- **A12 [pm8]**: Canary-only days are dropped from the proof window, or the canary verdict is defined explicitly. A canary never satisfies "every live fill labelled".
- **A13 [sf7]**: Attribute by registration status at `ts_event`. Label RETIRED families until their last fill is labelled. Add a RED test.
- **A14 [sf8]**: The canary AST tests get a positive control. The wrapper-exit tests prove that a genuine failure still exits non-zero.
- **A15 [sf9]**: Pin the label_lag horizon numerically, under the ARCH `MAX_VERDICT_VALIDITY_H`, and add a test.

## LOW
- **A16 [pm9]**: The log bridge matches on `client_order_id` within a bounded window, not on line adjacency.
- **A17 [pm11]**: The WP1 note explains why only 1 of the 3 v4 fills appears as a monitor row.
- **A18 [sf10]**: Until AUT-5a journaling exists, Z19 `unknown` is a metric only and is not alerted.

## ARCH changes since r1 (absorb)
ARCH Rev 5 is in progress, with deltas W1–W16 in reviews/ARCH-r4-merged.md. W8 is yours: a post-STOP RECONCILIATION producer at 16:41–16:43Z, with its own lock and a bounded runtime, and the §4.4 horizon defined as "produced after STOP that day". W1 is yours too: intraday HEALTH and RECONCILIATION verdicts with 8 h validity for ATTEST.
