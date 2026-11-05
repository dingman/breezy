# TE-1 r2 review merge: coordinator rulings (binding on r3)

Scores: domain 86 RWC · python 78 RWC · architecture 81 RWC · codex 78 NOT-READY. The codex result is driven entirely by the band correction.

0. **Apply the band correction (`CORRECTION_2026-10-11_band_semantics.md`) everywhere.**
   - Delete P19, the S0-5(ii) STOP, Risks bullet 1 and the DISAGREE identity.
   - Live-proof 2 targets: 34 / **4 wins / −2.63** / FQ **−2.17** / crh **−0.46** / fees 0.27, `n_settlement_disagree=0`, all 9 legacy rows `cli_final_check=AGREE`, `booked_total == cli_final_net_total`.
   - State the totals at the recorded fee, with `n_fee_unverified=2` and the FU-3d Markdown delta cited (domain N6).
   - Fix the non-goal to "FQ 2/25".
   - S0-5 becomes "legacy store agrees with the corrections-aware CLI final for all 9". Positive controls: MIA 09-13 (tmax 92 ∈ [91,92], YES wins) and MIA 09-15 NO (tmax 93 ∈ [92,93], NO loses).
   - DISAGREE/WARN is tested only with a synthetic correction fixture.
   - Every expected value in every fixture goes through `bucket_facts_from_instrument_id`. Fixtures cover upper-edge inclusive YES and `^no`, single-token `ltB` (≤ B−1) and `gteA` (domain N4/N5).
1. **R1 cannot be built in `persistence` (arch H1).**
   - Make `accounting_rows(rows, *, legacy_scorer_ids)` a static predicate: role ENTRY, scorer ∉ legacy ids, reason ∈ {UNATTRIBUTED, None}, and (admissible, or UNATTRIBUTED, or `settled_outcome is not None`).
   - Test that it equals `is_final_row` on the selected set.
   - No `breezy.analysis` import from `persistence`.
   - Guard: an import-linter forbidden contract (no `breezy.*` imports `labeling.accounting` except the sanctioned path), plus an AST guard that also covers attribute access (arch M4).
2. **Re-pin choreography (arch H2, python G1/G8).**
   - WP-A is sequenced before WP-B. They are not parallel.
   - Each WP re-pins every affected producer (`aut6.health` and `aut2.label`) in its own commit. AUT-6 co-signs the `aut6.health` re-pins. Rollback reverts carry the matching re-pins.
   - Widenings to add:
     - `test_autonomy_closure.py:90` (`CLOSURE_MODULES` set)
     - `test_committed_manifest_is_exactly_the_regen_output` (:745)
     - `test_closure_manifest_equals_grimp_closure` (:688)
   - S0-9 also greps `CLOSURE_MODULES`.
3. **E-TE1-b amends AUT-6 r15:929, :1189, :1235 and :1471** (arch M1).
4. **Labels gate closed (arch M2).** GATED_UNSETTLED_CAPITAL books the final rows and marks only the pending fill. GATED_IDENTITY books nothing and alerts IDENTITY, not NO_INPUT. Test both cases.
5. **No second ledger attribution (arch M3).**
   - `build_fill_pnl` consumes `bucket_ledger_fills`.
   - Assert that the LEGACY+RESIDUAL sum in `fill_pnl` equals the existing per-source totals.
   - `legacy_join` adds a trial-id agreement check against the manifest attribution: an S0-5 check plus a runtime refusal.
6. **Schema widening list (python G3).** Lines 283, 423, 2234, 2295, 4424, 5165, 5187, 5909, 5921, 5922, plus the `frozenset({1,2,3,4})` assertion at 5910. Rename `test_schema_version_is_four…`.
7. **RED hygiene (python G4/G5/G6/G7).**
   - The moved-dedupe test asserts `fn.__module__ == "breezy.analysis.scored_trial_dedupe"`. Pre-green tests are labelled regression pins.
   - Stub `factory` returns a `LabelRunDeps` with sentinel fields.
   - `__main__` lazy-imports the default factory, or it lives in a third module, with standalone-import tests.
   - Write full test paths: only `test_autonomy_units_programme.py` is under `tests/contract/`.
8. **Status vocabulary (domain N7).**
   - `cli_final_check` compares the booked `settlement_tmax_f` with a fresh corrections-aware read.
   - Define the trigger for every `fill_pnl` status, including UNPRICED.
   - `win` and `payout` are null, not 0, for non-settled rows.
9. **LAG_BACKLOG n (domain N8).** It counts lag-checked non-retired FQ fills: n=25. State this explicitly (arch confirms).
10. **Low items.**
    - `oldest_marker_ns` reuses `_marker_ns` so a corrupt marker raises (L1).
    - WP-E abort path: revert WP-C before 16:30Z if activation fails, and pre-declare the expected `verify` warning for `breezy-autonomy-failed@` (L2).
    - Update the D3 docstring (L3).
    - Optionally place `scored_trial_dedupe` in `persistence` beside `read_scored_trials_pooled`, if layering allows (L4).
    - R8 pin: no quote-tape module in the `aut2.label` closure manifest (L5).
