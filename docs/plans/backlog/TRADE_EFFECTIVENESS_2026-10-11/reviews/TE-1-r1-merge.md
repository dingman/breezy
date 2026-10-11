# TE-1 r1 review merge — coordinator rulings (binding on r2)

Scores: python 72 RWC · domain 74 NOT-READY · architecture 78 RWC · codex 58 NOT-READY. Every finding below is accepted unless it is marked otherwise.

## Contradictions resolved
- **Codex F2 (P12 "BLOCKER")** is downgraded to a wording fix (HIGH). F2's AFOS comparison checks the NWS CLI against itself (catalog vs AFOS). It is not a venue cross-check. In r2, P12 must say exactly that. The venue cross-check is UNAVAILABLE, so rows are labelled `SETTLED_NWS_IMPLIED` (domain F6).
- **Score-live-trials wrapper change.** Architecture A6 says drop it; the other reviewers are silent. **Ruled: drop it.** The 9 CRH fills settled before 10-01, and the frozen scored trials already exist. Only the portfolio-roi wrapper changes. A7 (ordering) is accepted as stale-safe, and r2 must state that explicitly.
- **P14.** Architecture says the lag start is an injected dependency and the 24 h FAIL still holds; Codex calls it a BLOCKER. Both are right. **Ruled now (no peer deferral): option (a).** In the wiring, `lag_start_ns` = max(`verdicts.lag_start_ns` rule, activation_ns) for fills whose tsEvent < activation, tagged `backlog`. A positive-control test must show that a post-activation fill is still lag-checked. Option (b), retiring v1 in `families()`, is rejected because it changes family semantics.

## Required r2 changes (from all reviewers)
1. **Accounting row set.** Define it explicitly: entry role, non-legacy scorer, final, reason ∈ {UNATTRIBUTED, none}. Exclude CANARY, DRILL, DUPLICATE_FILL, VOIDED_PAIR, SLIPPAGE_DEFECT and QTY_NOT_ONE (py F1, domain F4, arch A5).
   - Add an `accounting_rows` selector beside `admissible_rows` in `label_store`.
   - Add an AST guard so AUT-3/4/5 import only `admissible_rows`.
   - File an AUT-2 D3 erratum that narrows D3 to statistics (arch A1).
   - Add a new field `realised_pnl_accounting_total`. `realised_pnl_c2_total` stays admissible-only (domain F5).
2. **`fill_pnl`.** One row per ledger fill, with a fixed source order: legacy, then residual, then C2. `family_pnl` is derived from `fill_pnl`. The overlap guard is widened to cover accounting rows (arch A5).
3. **Fee-unreconciled fills (SFO 09-11, MIA 09-13).**
   - The acceptance figure is −4.63 at the recorded fee, plus a `fee_unverified` disclosure that shows the modelled fee separately. FU-3d is the precedent.
   - Add S0-4b covering these two fills (domain F1/F2).
   - Settle how the C2 path treats `FEE_UNRECONCILED` against the legacy path, so the numbers reproduce.
4. **S0-5.** Map each of the 9 legacy fills to scored or residual and reconcile the total to −0.46. Specifically, explain the residual +0.08 against the fill-level decomposition (domain F3). The join does not exist in production yet (py F4). The move of `dedupe_scored_trials` and its helpers into `src/breezy/analysis/` must keep re-exports.
5. **NO_INPUT alert.**
   - Alert only for fills older than settlement deadline + `LABEL_LAG_MAX_H` that still have no P&L. A normal pending day does not page (arch A2).
   - AUT-6 co-signs this as an erratum.
   - Enumerate every contract test the change widens, with positive controls (codex F3, py F6). An absent marker still exits 1.
6. **Rollback.** Never revert WP-B alone.
   - Order: disable the timer, revert WP-C, unlink the label pair.
   - If WP-B must go, move the labels root aside first (arch A3/A4).
7. **Activation (WP-E).**
   - Gate on the branch, then merge, symlink the label pair, run preflight, then `daemon-reload`, all in one window.
   - The window must avoid 13:55–14:30Z, [16:30, 17:10)Z and [01:00, 04:30)Z (arch A4).
   - The S0-6 peak measurement moves into WP-D (arch A8).
8. **PRODUCER pin.** Decide with evidence: either a new `aut2.label` id with a closure entry and a reviewed widening of `test_autonomy_pins.py:101`, or no pin, naming where `producer_code_sha` comes from (py F2).
9. **Schema.** The reader known-set lives at `portfolio_roi_report.py:2208`. List the four `== 4` test assertions as reviewed widenings. v5 strict-rejects any payload missing the new keys (py F3).
10. **RED tests.** For each test, state its failure mode (stub first, so it fails on an assertion). Add positive controls: P&L present → OK; null-P&L final row → alert; unbridgeable fill → UNRESOLVED (py F5).
11. **Focused gate.** Name the files: firewall guards, exec import pin, every `test_autonomy_*`, `test_autonomy_units_programme.py`, `test_aut2_attribution.py`, `test_runtime_import_isolation.py`, `test_run_tests_no_egress_phases.py`, `lint-imports` (py F6).
12. **S0-1.** Use the `mode=ro` URI. Note that the store's `BUY` is post-normalisation (NO legs are `^no` instruments) (py F7, domain F6).
13. **Disclosures.** Add `n_ambiguous_no_fill` (09-05 SFO, 09-23 MIA) and state that venue positions are not reconciled (domain F7). S0-3 must use corrections-aware reads (domain F8).
14. **Dependencies.**
    - The POST_EPOCH switch is added to AUT-1b acceptance.
    - Row 9's WP6-promote is marked DONE-by-TE-1 on merge.
    - The ruling states why Needs 3 and 8 do not apply to pre-epoch fills (arch A9).
15. **File size.** Selection and accounting logic go in `src/`, not into the 4,400-line script (arch A10).
