# TE-2 r2 review merge — coordinator rulings (binding on r3)

Scores: domain 78 RWC · python 82 RWC · architecture 76 NOT-READY · codex 86 NOT-READY. Every finding is accepted unless it is ruled otherwise below.

0. **The band correction (`CORRECTION_2026-10-11_band_semantics.md`) is binding.**
   - FQ is **2/25, −2.17**. Wins: MIA 10-03 `gte86lt87` and MIA 10-05 `gte89lt90`.
   - Restate every "0 wins" and "five 1 °F" premise. T-WIN becomes the exact Poisson-binomial lower tail P(W ≤ 2) at cluster level.
   - `edge_dist_f` and the band tests use the inclusive interval via `bucket_facts_from_instrument_id`.
   - Fixtures include upper-edge-inclusive, `^no` and single-token `ltB`/`gteA` cases.
   - Winning fills get primary class WIN. The loss taxonomy applies only to losing fills.
1. **Deployed-commit pin** (codex BLOCKER, python N1, arch B4). Boot logs carry no commit sha. The rule is:
   - (a) If `git log` shows no change on 10-01..10-06 to `src/breezy/strategy/forecast_quantile_ladder/**`, `src/breezy/strategy/ladder_ev/forecast_state.py`, the `ArtefactBoundsProvider` module, or `deploy/families/**fq_v1**`, the pin is moot. Use one commit, the last before the first boot, and label it `PIN=STABLE`.
   - (b) Otherwise, use the last branch commit with committer time ≤ boot time. Corroborate it: the blob sha256 of the manifest and artefact at that commit must equal the logged `manifest_sha256` and `calibration_sha256`. Label it `PIN=INFERRED`.
   - (c) If no commit can be identified, the fill is UNTESTABLE.
   - **STOP** if fewer than 23 fills match, counting UNTESTABLE as a non-match.
2. **Out-of-scope fills** (arch B1).
   - FIVE fills sit on climate day 10-06, on 3 station-days. They were taken after the failed 10-05 16:40Z halt.
   - K1b covers all five. It routes to the existing failed-halt incident (memory/HALT_POINT_2026-10-04; `fq-v1-halt-scheduled-2026-10-05`). Do not file a new manifest row.
   - Pre-declare a sensitivity analysis that excludes the 10-06 station-days.
   - Never route the batch through `assert_family_only`.
3. **Honest test design** (domain R2-2/R2-3/R2-7, arch B2).
   - Fix P6 to the observed station-event cluster count (the reviewer's count is 7).
   - S0-I runs before the freeze. It computes the minimum attainable p for every test from the cluster count. Any test that cannot reach its α is reported as **NOT-TESTABLE**, never as "did not reject", and the verdict rules treat NOT-TESTABLE as non-informative.
   - Add a pre-declared leave-one-out T-WIN that drops the cluster with the largest P_c (LAX).
   - State in §0 that T-WIN is likely driven by one cluster, and that the information gain is the per-fill flags (K1a/K4/K1b) and the descriptive table.
   - Pre-declare tie handling: drop zeros, and report n after drops.
   - State the sidedness of T-LOC.
   - Clamp P_c ≤ 1 − 1e-9, and report a p-value of exactly 0 as "< bound".
4. **T-SPREAD at cluster level** (domain R2-4, arch B3). Define a cluster-level T-SPREAD using the maximum per-day tail probability within the cluster (a Fréchet lower bound, so the test is conservative). The downgrade rule applies to it. State plainly that SPREAD vs LOCATION attribution is **not identified**.
5. **K1a materiality** (domain R2-5). A K1a counts toward FIXABLE only if it flips the take/no-take decision, or if |Δp̂| > 0.01. A deterministic recompute is not a counterfactual P&L.
6. **H0-K cluster rule** (domain R2-6): use the same max-over-cluster treatment.
7. **Taxonomy fixes** (domain R2-1).
   - Test #5 tests the BOUNDARY vs BAND_SELECTION overlap.
   - Add a mutual-exclusion test for BOUNDARY vs TAIL.
   - Define how K7 applies per fill when `edge_dist_f` differs within a station-day.
8. **Freeze enforcement** (python N2).
   - Pins are the sha256 of the HEAD blob, plus a clean-path check (`git status --porcelain` on the pinned paths).
   - The ancestor check stays.
   - The "result committed later" check moves to a post-hoc verifier test over committed artefacts.
   - Drop the commit-message sha.
   - Add a re-freeze rule: a script bugfix after the freeze requires a new predeclaration commit and a disclosed re-freeze, with no Phase B result consumed in between.
9. **Truth path** (python N4, arch B5).
   - Truth is the catalog via `NwsCliFinal`. Confirm that the catalog holds 10-02..10-06 for the 4 stations, and run the coverage check on the catalog, not the CSV.
   - Add a clipping wrapper that implements the `SettlementSource` protocol.
   - Phase A receives a projection without `tmax_f`. A test record whose `tmax_f` raises on access must pass Phase A.
10. **Citations and reuse** (python N3/N6–N8, arch B7).
    - Correct the sha labels: manifest `8e1217fd…`, artefact `9c0b6d6e…`.
    - Drop `combine_station_day` and give the reason.
    - Fix the `BackfillRefused` line to `:213-214`, and name the `trade_id`/`recalibration` inputs and the `epoch_class` source.
    - Use the full path to `forecast_state`.
    - Drop the "keyed second pass on now_ns".
    - The partition-union reader must include Refuse lines, which `read_log_events` keeps only for Takes.
    - Import pin: `fill_source` and `decision_link` both import `exec.client` transitively. Confirm the pin is direct-import only, or widen its row in the same commit (L-12).
11. **Consumers** (arch B6).
    - TAIL and LOC_ARTEFACT go to a named PROGRESS row, "F13 r-next / T2-T3 candidate input". The F13 ≥10-21 freeze takes only `source_lags_ns`/`source_breaks`.
    - 10-20 is a soft target.
12. **RED test coverage** (python N5). Declare RED as AssertionError or NotImplementedError, never ImportError. Fix the #10 typo. #22 uses tracemalloc or a lazy-generator check. Add tests for:
    - the downgrade rule
    - the FIXABLE positive path
    - the MODEL_LIMITATION sub-labels
    - INCONCLUSIVE
    - the cluster collapse
    - cluster power
    - PARTITION_INCOMPLETE and K7 UNTESTABLE
    - TRUTH_UNSETTLED
    - a T-WIN positive control
    - NOT-TESTABLE
    - leave-one-out
13. **Codex PASS facts to cite as verified premises:** 25/0/0 attribution, all PRE_EPOCH; 32 take, 32 init and 25 filled bridge events; `NBM_NBP_PUBLISHED` lines present in all 5 boot logs.
