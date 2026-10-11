# TE-2 r1 review merge: coordinator rulings (binding on r2)

Scores: domain 68 RWC · python 66 NOT-READY · architecture 60 NOT-READY · codex 74 NOT-READY.

## Contradictions resolved
- **P4.** Python says it is WRONG. Codex says it is "verified: every Take now_ns has 2 rows". The two agree: the 2 rows are the Take plus the same rung's `already_latched` Refuse, not the rest of the ladder. **Ruled P4 WRONG.** Rebuild the partition from the union of `rung_id`s per (station, climate_day) across the log, or from the catalog. Reproducing p̂ only needs the bought rung's bounds. K7 and "central 80%" depend on the rebuilt partition.
- **Codex F2** (the "memory entry" in P13) is **rejected as a defect, then fixed anyway.** The entry is in the coordinator's private memory, which a repo reviewer cannot see. r2 must cite only repo-local lessons and evidence.
- **Holdout (arch A1 BLOCKER vs plan P7).** The architecture reviewer is right. `RULING_holdout_freeze_and_forward_window_2026-10-03.md` freezes the holdout at [07-01, 10-02), so every FQ day is forward data. Drop the S0-E ruling step. Keep the `open_holdout` pin, hardened per python F8 (an allowlist that also forbids `ast.Attribute` and string access). Fix the WP4 wording.

## Required r2 changes
1. **Take join (codex F1, python F1).** The join is fill → filled → init by client id, then init → Take by instrument and time window. Use `decision_link.bridge_decision`, `read_log_events` and `bridge_report` directly (arch A7). Require 25/25 attribution. Any miss is a named UNCLASSIFIED outcome and a STOP. There is no "≤ 2 unjoined" tolerance. Log path: `~/.local/share/breezy/logs/breezy-trade-202610*.log`.
2. **Outcome blindness (python F2).** S0-A before the freeze is count-only: 25 fills, parse, join. The P&L reproduction (0 wins, −4.17) moves to Phase B. The S0-F truth-flag read is disclosed as a pre-freeze read.
3. **Freeze enforcement (python F3, arch A10).** Pin the blob sha256 of the script and core module, plus the predeclaration sha. Enforce both by git: the predeclaration is committed and is an ancestor of HEAD, and its commit precedes the commit of the result artefact. Do not store the sha of the predeclaration file inside itself.
4. **Reproduction gate (python F4/F6, arch A3/A5).**
   - Reconstruct with `ForecastQuantileState.push` and `value_at`.
   - The cycle in use and its visibility come from the node log lines (`NBM_NBP_PUBLISHED cycle_ns=`, the FQ-S6 first-evaluable line). The poll ledger starts at 10-06, so the ledger sha check is N/A for 10-01..10-05.
   - Pin to the commit deployed at each boot.
   - Name every `evaluate` input source: manifest, `ArtefactBoundsProvider`, `load_live_calibration(path, sha)`, and the `fq_evaluate_shim` conventions. Do not import `breezy.app`.
   - Class an unavailable or reissued bulletin as UNTESTABLE. A cycle-selection mismatch is CYCLE_AMBIGUOUS. Neither is K1.
5. **Fetch command (python F5).** Give the exact `nbp_backfill` invocation: `--apply`, `--request-budget`, a scratch `--output-dir`, `BREEZY_LIVE=1`. It runs outside 16:30–17:10Z. Correct the "raw bulletins" wording: the backfill writes a parsed store with `raw_sha256`.
6. **Truth (arch A2/A7).** Scope the coverage-gap check to the settlement days only (SFO has a gap on 2026-03-11). Read truth through `settlement_source.NwsCliFinal` + `score_trial`, the same path as TE-1. Reuse the `settlement_alignment_study` ASOS loaders and the `reconcile.py` settlement leg for K4. Reuse `nbp_calibration` Holm (`:1670`) and `combine_station_day`.
7. **Taxonomy restructure (domain S5/S6/S7, arch A4).**
   - The primary partition is the OUTCOME classes: BOUNDARY (K5), TAIL (K6), BAND_SELECTION (K7), VARIANCE (K9).
   - K1 (input defect), K2 (stale cycle), K3 (truth basis) and K4 (venue semantics) become orthogonal flags.
   - K3 is descriptive only, never FIXABLE. CLI is the settlement truth, and K3 is never routed to CF-2/CF-7. Use the F13 source list if a route is needed.
   - Only K4 (venue ≠ CLI) or a K1 that reproduces as a code or data defect can make FIXABLE_DEFECT.
   - Define the integer-°C reachability as an explicit set mapping, or drop it: FQ is a D+1 forecast and has no °C observation input.
8. **Tests (domain S1–S4, S7–S11, python F10).**
   - The station-day cluster is binding: 14 station-days over 5 climate days, with LAX 10-02..10-06 treated as one event. Pre-declare how P_c is built, the T-LOC collapse, and the downgrade rule. Run S0-I power at cluster level too.
   - Label T-LOC and T-SPREAD "conditional on take". T-LOC alone never yields FIXABLE. Add the unfilled-Take contrast.
   - LOC_ARTEFACT gets a pre-declared paired exact test on |corrected error| − |raw error|.
   - T-SPREAD uses a per-station-day null from the model's own pmf (Poisson-binomial), not Binomial(n, 0.10).
   - T-EDGE is exploratory and is removed from Holm. Holm then covers T-LOC and T-SPREAD only.
   - VARIANCE requires power ≥ 0.8.
   - Add MODEL_MISCALIBRATED_UNATTRIBUTED (T-WIN rejects and the secondaries do not).
   - Clamp P_d to ≤ 1.
   - State the overall α allocation.
9. **Consumers (arch A6/A8/A9, domain S10).**
   - Add a consumer for INCONCLUSIVE, and state up front that T-WIN is expected to reject.
   - VARIANCE gets a fixed footer, pinned by a test, naming the T1–T3 re-open rules. It is never permission to re-arm.
   - G2.0/G2.1 and month_10 (−0.20 °F, n=369, p=0.31) are the baseline. LOC_ARTEFACT is reframed as v5.0 May–June extrapolation.
   - Set a delivery date to feed the F13 freeze review (≥ 10-21), or state the slip.
10. **Manifest (arch A11).** Verify what `terminal_climate_day 2026-10-05` means against the SFO 10-06 fill. If it is a climate day, that fill is a K1 candidate.
11. **Test hygiene (python F7–F9, F11).**
    - Write stubs first, and give each RED test's failure mode.
    - Add an S0-D perturbation positive control.
    - Add a streaming test: bounded memory, and a Take split across the prefilter boundary.
    - State that lint-imports does not cover `scripts/`. The AST pin plus `test_execution_egress_firewall_guard` are the enforcement, and both go in the focused gate.
    - Fix the class-count wording.
