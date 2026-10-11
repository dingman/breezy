[PLAN] TE-2: Root-cause the FQ v1 0/25 result (delta over F0 and FQ_LOSS_TRIAGE)

Status: r1, from a blind planner. The plan is read-only analysis. The only code is one analysis script and its tests, plus one evidence artifact. Nothing here arms, halts or edits strategy code. Per README the coordinator saves this to `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r1.md` and runs the peer loop.

## 0. What F0 and the triage already covered (do not redo)

| Covered | Source | Scope |
|---|---|---|
| S0-1 LAX 10-05 `<97`, p̂ 0.992, ask 0.64: GENUINE, no leak or input defect. The bot's own code recomputes it exactly from the NBM 13Z cycle, published 44 s before the take. | `FQ-LOSS-RESPONSE_plan_r3.md:87`, `FQ_LOSS_TRIAGE_2026-10-04.md:30-32` | 1 take |
| S0-2 MIA p̂ 0.6368: NBM's own tight spread. | plan r3 `:88` | 1 take |
| Aggregate triage: 11 settled fills (5 station-days) plus 3 locked 10-04 losses, n=14, 1 win. Model Brier 0.075 vs market 0.048. Mean p̂ 0.287 vs mean ask 0.142. NBM spread about 2 °F vs realised misses of 3–8 °F. Stacking of 2–3 exclusive rungs per station-day. | `FQ_LOSS_TRIAGE_2026-10-04.md:9-23` | 14 of 25 fills, hand-assembled |
| Fee, side, sizing and fee-θ drift ruled out; latency race ruled out. | triage `:25-28` | do not revisit |
| M1 market scan: no model-free cell survives. Cheap YES (ask < 0.10) is a "reliable loser" filter input. | `M1_MARKET_SCAN_2026-10-04.md` | market-side only |
| The 25-fill, −4.17 re-score comes from the 10-11 audit. | `TRADE_EFFECTIVENESS_2026-10-11.md:13-20` | coordinator recipe, not a committed script |

**The delta TE-2 owns:**
1. Per-fill classification of all 25 fills into one pre-declared taxonomy. Today there is only an aggregate narrative. The 10-05 and 10-06 settlements are new since the triage.
2. An exact, pre-declared variance test with its power.
3. The split into fixable defect, source limitation, and variance. Triage says "overconfident" but never tests location bias vs spread vs artefact extrapolation.
4. A committed, reproducible script. The audit's re-score was hand-run.
5. A consumer mapping for every finding.

## 1. Verified premises

Checked against the repo and data on 2026-10-11.

- **P1. FQ is D+1 only and prices YES off `p_lower`.**
  - `src/breezy/strategy/forecast_quantile_ladder/decision.py:216-218` and `:277-281` (`NotDPlus1`).
  - `:349` is `ev_net(p_lower, cost)` for YES.
  - `:353-355` takes iff `net > forecast_margin(h)`.
  - `:331` sets `p_hat = bounds.p_hat`, the mean of per-draw rung probabilities.
- **P2. The Take log line does not carry the ask or the forecast vector.**
  - `decision.py:200-212` logs `now_ns, station, climate_day, rung_id, side, instrument_id, qty, ev_net, p_hat, p_lower, p_upper` only.
  - Consequence: the ask must be proxied by the fill's `cumulativeCost`. The audit verified slippage = 0 on 34 of 34 (`TRADE_EFFECTIVENESS…md:27`). The vector must be reconstructed.
- **P3. Take lines exist in the node logs.**
  - I counted 32 `SHADOW_DECISION … 'kind': 'Take'` lines across `logs/breezy-trade-202610*.log`.
  - I counted 25 `OrderFilled` lines in the same logs and 25 FQ fill rows in the durable store (34 total fills).
  - So 7 Takes did not fill (IOC miss). Fills must join to Takes by `client_order_id`.
  - `breezy-trade-20261003T165045Z.log` alone holds about 4.0 M `SHADOW_DECISION` lines. A whole-log scan is expensive.
- **P4. The traded ladder is recoverable.**
  - `SHADOW_DECISION` lines at the same `now_ns` list the station-day's other rungs, so the complete partition can be rebuilt.
- **P5. Durable fills and the existing join and score modules.**
  - Fill rows are JSON with `instrumentId`, `cumulativeCost`, `cumulativeFee`, `tsEvent`, `clientOrderId`.
  - `src/breezy/analysis/labeling/fill_source.py:58` `read_durable_fills` opens the store with `mode=ro`.
  - `labeling/decision_link.py:1-17` joins a fill to its Take by `client_order_id` in bounded windows, reading log files only. Its docstring says it runs for PRE_EPOCH fills only, so the epoch class of the 25 fills is unchecked (S0-B).
  - `labeling/fq_scorer.py:1-14` reuses `score_trial` as the settlement oracle (TE-1 territory). `instrument_facts.py` parses buckets.
- **P6. The FQ calibration artefact is a validate-stage candidate.**
  - Manifest: `deploy/families/pm_us_crh_fq_v1.json`. Artefact sha256 `9c0b6d6e…23a5`. d0 is 2026-10-02, terminal take day 2026-10-05, stations LAX, MDW, MIA, SFO, θ=0.0695.
  - `NBP_S2_VALIDATE_RESULT_2026-09-30.md` shows these facts.
    - Location correction `linear_lst_day_length`, coefficients [−0.398, 4.281].
    - G2.0 FAIL (n=11604); G2.1–G2.3 FAIL, in-sample only.
    - Fit data ends 2026-05-03 (validate), and v5.0 parameters come from the 05-04..06-30 fit slice.
    - Shrinkage weights v4.2/v4.3/v5.0 = 0.
  - Consequence: an October take rests on a day-length extrapolation from spring and early summer. This is a hypothesis class to test (LOC_ARTEFACT), not a finding.
- **P7. Every FQ live day is a sealed-holdout-split day.**
  - `src/breezy/analysis/nbp_calibration.py:277` has `holdout_start=dt.date(2026, 7, 1)`.
  - Open question: does any ruling forbid diagnostic forecast-vs-truth reads on live-traded post-07-01 days? Resolved at S0-E.
- **P8. The SL-13p parity harness cannot be reused for the October days.**
  - `scripts/analysis/nbp_shadow_parity_pure.py:98-132` raises `PostFreezeTapeRefusedError` outside 08-30..09-25.
  - Recompute with production `decision.evaluate` plus `load_live_calibration` and an injected clock, never the parity harness.
- **P9. Which vector the strategy sees.**
  - `src/breezy/ingest/nbm_quantile_actor.py:210-218` keeps the nearest-valid-start (D+1) TXN window per station and variable.
  - `available_at_ns = cycle_runtime_ns + measured_lag` (`:221-233`).
  - The TXN window length for NBP is UNVERIFIED (`NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md`, part (a)).
- **P10. Truth file overlaps M1-v3's window.**
  - `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` has columns `station,city,climate_day,tmax_f,tmax_flag,correction_flag,issued_at_utc,…`. It runs to 2026-10-10 (LAX last row 10-10, 283 final days, `catalog_disagreement: false` in `coverage.json`).
  - The M1-v3 forward screen window starts 10-07 (project memory; confirm only the window field in the frozen PREREG plan, never outcomes).
  - The loader must clip to `climate_day <= 2026-10-06`, the last FQ settlement day. That day is SFO 10-06 per the audit.
- **P11. The derived NBP store has no October rows.**
  - `derived/nbp/2026/` and `derived/nbp5/2026/` stop at month 09 and month 06 respectively.
  - `us_source_archive/us-nbp-avail/poll_ledger.jsonl` records availability and sha256 per cycle, not the payload.
  - Decision-time vectors must be re-fetched from the public cycle bulletins (S3 primary, NOMADS fallback). The existing tool is `scripts/analysis/nbp_backfill.py` (default `--dry-run`; `--apply` needs `BREEZY_LIVE=1` and a monitored `BREEZY_USER_AGENT`).
- **P12. Route-back policy.** `RULING_FQ-v2-NO-TRADE_2026-10-08.md:44-50`: T1 (M1-v3 CONFIRM, read ≥ 12-07), T2 (new family and prereg), T3 (a new US source that changes the take rate, i.e. F13). F13 freezes ≥ 10-21 (`PROGRESS.md:104`; `F13-source-breaks-proposal…:54`).
- **P13. Lessons.** L-18 (a counterfactual is a claim about a mechanism), L-40 (mutually exclusive rungs have exact variance), L-52 (a read counts only if it can tell the outcomes apart), L-2 (a native substitution is a unit change), L-1 (null hypothesis). The memory entry "implausible result is a leak" applies to the decision-time vs issuance check.

**Not verified; Stage 0 must check these:**
- The epoch class of the 25 fills.
- That S3 still serves the 10-01..10-05 cycles.
- That a second truth source covers the 4 stations over the 6 days.
- That venue-resolved outcomes can be read.
- The number of distinct station-days. I expect roughly 11–14, but have not counted.

## 2. Stage 0: STOP conditions

All read-only. Any STOP is reported verbatim and halts the plan, with no partial verdict.

- **S0-A. Re-score reproduction.**
  - The new loader (`read_durable_fills`) must reproduce the audit: FQ 25 fills, 0 wins, net −4.17 (cost + fee − payout, to ±0.005), and total 34 / 2 / −4.63.
  - Mismatch: STOP. The audit's rejected seam result (4 wins, keyed to order date) shows the failure mode. Outcomes key on the instrument climate day.
- **S0-B. Parse and epoch.**
  - Every FQ `instrumentId` parses to (station, climate day, band).
  - `n_undecodable == 0`, else `FillStoreCorruption`, STOP.
  - Record the PRE_EPOCH or POST_EPOCH class. If POST_EPOCH, the C1 attribution path replaces `decision_link`, so re-plan the join before building.
- **S0-C. Fill to Take join.**
  - All 25 fills join to exactly one Take by `client_order_id`, using the `decision_link` windows (`BRIDGE_INIT_TO_FILL_MAX_S`, `BRIDGE_TAKE_TO_INIT_MAX_S`).
  - More than 2 unjoined: STOP.
  - The 7 unfilled Takes are kept as a separate census: their p̂ vs fills, to describe selection into fills. They carry no P&L.
- **S0-D. Reproduction gate.**
  - Re-fetch the decision-time cycle for each Take into a scratch directory (never `derived/nbp`).
  - Rebuild the vector, ladder and calibration with production code, and recompute p̂, p_lower, p_upper.
  - Fewer than 23 of 25 matching the logged p̂ to 1e-9: STOP the classification.
  - Every miss becomes class K1 (INPUT_DEFECT) with the delta recorded.
  - Also verify `available_at_ns <= now_ns` (no leak). Compare the bulletin sha256 to the ledger sha256 where the ledger covers the cycle. A mismatch flags a reissued bulletin.
- **S0-E. Holdout and M1-v3 guards.**
  - Grep the rulings under `docs/evidence/` for any prohibition on diagnostic reads of post-07-01 live-traded days.
  - If one exists, or the question is open, the coordinator files a short ruling under `docs/evidence/` before WP2. The ruling should say: diagnostic only, non-confirmatory, no `open_holdout`, no marker write, no G2.x metric.
  - The script must not import `open_holdout` or any holdout path. A unit test pins the import set.
  - The truth loader hard-clips to `<= 2026-10-06` and a test asserts later rows are never held. No path under an M1-v3 directory may be opened.
- **S0-F. Truth quality.**
  - `coverage.json` shows `last_final_day >= 2026-10-06` for all 4 stations, `coverage_gap_days == 0` and `catalog_disagreement == false`.
  - `correction_flag` is False and `tmax_flag` is empty on the 25 settlement days. Any flag means that day is `TRUTH_UNSETTLED`: report it and exclude it from the tests, with the exclusion count stated.
- **S0-G. Second truth and venue source.**
  - Look for a METAR, ASOS or 1-min series covering the 4 stations over the settlement days (`us_source_archive/metar-routine`, `asos-cache`).
  - Also look for a venue-resolved outcome per instrument. If a source is absent, K3 or K4 is reported UNTESTABLE for those days. That is not zero evidence, and a verdict must not treat it as zero.
- **S0-H. Outcome-blind freeze (the anti-overfit gate).**
  - Phase A (S0-C, S0-D, power) uses no outcome. It produces a per-fill table of p̂, ask proxy, cycle age, newest-visible flag, rung geometry and per-station-day P_d.
  - Commit `TE2_PREDECLARATION.json` before any truth join. It holds: the taxonomy, thresholds, tests, α allocation, verdict rules, consumer map, the Phase A table sha256, and the script commit sha.
  - Phase B refuses to run unless that file's sha matches and its commit precedes the first Phase B run in git history.
  - Disclosed contamination: the 10-11 audit summary and the 10-04 triage already showed the headline direction (0 wins, LAX heat bust, five 1 °F losses). Pre-declaration therefore constrains classification and thresholds, not the prior.
- **S0-I. Power gate (outcome-blind).**
  - From the Phase A P_d vector, compute the test power to reject H0-M (model calibrated) when the truth is H0-K (ask-implied).
  - Power below 0.5 means the verdict space excludes VARIANCE; the possible results are INCONCLUSIVE or a defect (L-52).

## 3. Taxonomy (pre-declared; frozen in `TE2_PREDECLARATION.json`)

Eight classes plus the variance residual.

**Per-fill descriptors (computed, not judged):**
- `p_hat`, `ask_proxy` (fill cost), `edge_dist_f` (integer °F distance from `tmax` to the nearest edge of the bought band).
- `PIT` (mid-PIT of `tmax` under the corrected model CDF) and signed standardised error `z`.
- Raw NBM median error vs corrected median error, and `correction_f`.
- Cycle age at decision, and the newest visible cycle at `now_ns` from the availability ledger.
- Alternative-truth delta, and the venue-resolved outcome where available.
- Rungs bought on the same station-day.

**Primary class, first match wins (K1 to K8 in the first-match order below; K9 is the residual):**

| # | Class | Rule |
|---|---|---|
| K1 | INPUT_DEFECT / LEAK | S0-D reproduction miss, or `available_at > now`, or `vector.climate_day != instrument climate day`. |
| K2 | STALE_CYCLE | The cycle used is not the newest with `available_at <= now_ns`, or cycle age exceeds the pinned maximum. The maximum is set in the declaration from the NBP cadence (13Z, 19Z, 01Z) and the 16:50Z decision time. It is a number the declaration must name. |
| K3 | TRUTH_BASIS (CLI vs METAR/ASOS) | The outcome flips when the alternative pre-declared truth replaces CLI `tmax`. Includes the integer-°C to °F reachability check: whether the CLI °F value is reachable from an integer-°C observation. |
| K4 | VENUE_SEMANTICS (rung-edge) | The venue-resolved outcome differs from the slug-parsed outcome (`lt` / `gteLlt H`, inclusive or exclusive edge, integer °F). |
| K5 | BOUNDARY_ROUNDING | `edge_dist_f == 1` and PIT in [0.05, 0.95] (the model called it plausible). |
| K6 | TAIL_MISS | PIT outside [0.05, 0.95]. Attributed at the aggregate level (see tests): to LOCATION_BIAS if T-LOC rejects, else to SPREAD_MISCAL. |
| K7 | BAND_SELECTION | The station-day bought two or more rungs, and `tmax` is inside the model's central 80% but outside every bought band. |
| K8 | (reserved) | Unassigned; if unused, state "no K8" in the report rather than renumbering. |
| K9 | VARIANCE | Residual: body miss, `edge_dist_f >= 2`, no class above. |

Each fill also gets **secondary flags** (multi-label), counted separately and never in the primary share:
- `LOC_ARTEFACT`: the corrected median error is larger than the raw NBM median error. This points at the artefact's day-length correction or season extrapolation (P6).
- `LOC_SOURCE`: the raw NBM median error alone is beyond ±1 sd. This points at the source (F13).
- `FLANK_CHEAP`: ask below 0.10, consistent with the M1 "reliable loser" finding.

## 4. Test specification (pre-declared; exact tests only)

**Independent unit:** the station-day. Rungs inside it are mutually exclusive (L-40), so a station-day yields W_d ∈ {0, 1} with P_d = Σ p_i over the bought rungs. This is exact and needs no normal approximation. Total wins W are Poisson-binomial over station-days. Implement the dynamic-programming recursion in pure Python and verify it against brute-force enumeration in tests.

- **T-WIN (primary, α = 0.05, one-sided lower tail).**
  - H0-M: P(win_d) = P_d (model calibrated). The p-value is P(W ≤ observed) = Π(1 − P_d) when observed = 0.
  - Companion H0-K: P(win_d) = Σ ask-implied probability net of θ·p·(1−p) fees, reported to say whether bad luck at the price paid is plausible.
  - Report the power of T-WIN against H1-K from S0-I.
- **Secondary family (Holm, family α = 0.05, three tests):**
  - **T-LOC.** Exact sign test on signed (tmax − corrected median) over station-days. Companion: the same on raw NBM median error. It separates LOC_ARTEFACT from LOC_SOURCE.
  - **T-SPREAD.** Exact binomial count of station-days with PIT outside [0.05, 0.95] against Binomial(n, 0.10). Companion: mean z² against 1 as a descriptive value only.
  - **T-EDGE.** Expected number of `edge_dist_f == 1` losses under the model's own density, as a Poisson-binomial over fills. Observed is 5. Exact upper tail P(X ≥ 5).
- **Clustering sensitivity (descriptive, not a test):** regional events correlate stations, so there are fewer independent days than station-days. Re-run T-WIN and T-LOC collapsed to climate-day clusters and report whether the verdict changes. If it does, the verdict is downgraded to a stated range.
- **Aggregate verdict, deterministic:**
  - **FIXABLE_DEFECT:** any K1, K2, K3 or K4 fill that flips the outcome class and is preventable by a code or data change; or LOC_ARTEFACT holds with T-LOC rejecting.
  - **MODEL_LIMITATION (source):** T-LOC or T-SPREAD rejects with LOC_SOURCE, and no K1–K4 fill and no LOC_ARTEFACT.
  - **VARIANCE:** T-WIN fails to reject, the secondary family fails to reject, and S0-I power ≥ 0.5.
  - **INCONCLUSIVE:** anything else, with the reason stated.
  - Mixed results are reported as a ranked list with share of loss, never one label. The verdict names the evidence class and states "diagnostic, post-hoc, n = N station-days, non-confirmatory".
- **Forbidden:** no counterfactual P&L such as "would have won with the 19Z cycle" as a finding. A later-cycle comparison is descriptive only (L-18).
- **All numbers come from the script. No hand arithmetic anywhere in the output.**

## 5. Work packages

All build work follows the repo's native-first rule. No new infrastructure: reuse `read_durable_fills`, `decision_link` windows and constants, `bucket_facts_from_instrument_id`, `score_trial`, `load_live_calibration`, `decision.evaluate` with an injected clock, `NbmQuantileTransport` and `parse_nbp_bulletin` via `nbp_backfill`. Statistics code is standard library only.

**Layout (each file below 400 lines; the 800 limit is a hard stop):**
- `scripts/analysis/fq_v1_loss_taxonomy.py` is the CLI with Phase A and Phase B modes.
- `scripts/analysis/fq_loss_taxonomy_core.py` is pure and has no I/O: descriptors, the first-match classifier, Poisson-binomial, tests, verdict.
- `scripts/analysis/fq_loss_taxonomy_inputs.py` holds the I/O: fills, Take join, ladder rebuild, truth clip, cycle fetch wrapper.
- Tests: `tests/unit/test_fq_loss_taxonomy_core.py` and `tests/unit/test_fq_loss_taxonomy_inputs.py`.

**Outputs (committed):**
- `docs/evidence/te2/TE2_PREDECLARATION.json` (Phase A hash, thresholds, rules).
- `docs/evidence/te2/fq_v1_loss_taxonomy_<date>.json` and `.md`. The `.md` is generated by the script like `NBP_S2_VALIDATE_RESULT`, not hand-written.
- Raw bulletins stay in scratch. Commit only per-cycle sha256s and the small reconstructed-vector table.

**WP0. Outcome-blind scaffolding and RED tests (tdd-guide).**
RED tests, all failing first:
1. `test_poisson_binomial_matches_bruteforce_enumeration`.
2. `test_zero_wins_pvalue_equals_product_of_complements`.
3. `test_station_day_collapses_exclusive_rungs_to_single_bernoulli`.
4. `test_classifier_first_match_order_is_pinned` (a fill that matches K1 and K5 gets K1).
5. `test_edge_dist_counts_integer_f_to_nearest_band_edge`, including the open `lt` band and `gteLltH`.
6. `test_pit_midpoint_for_integer_outcome`.
7. `test_verdict_inconclusive_when_power_below_half`.
8. `test_holm_family_of_three`.
9. `test_truth_loader_clips_after_2026_10_06_and_never_holds_later_rows`.
10. `test_script_imports_no_holdout_or_m1v3_symbol` (an AST pin).
11. `test_phase_b_refuses_without_matching_predeclaration_sha`.
12. `test_reproduces_audit_25_fills_zero_wins_minus_4_17` (fixture-based, built through the real writer path, L-42).
13. `test_unjoined_fill_is_reported_not_dropped`.
14. `test_alt_truth_unavailable_marks_untestable_not_zero`.

Per L-55, run the production default path once where a fake dependency is injected.

**WP1. Phase A (outcome-blind).**
- Implement the loader, the join, the ladder rebuild and the vector reconstruction.
- Run S0-A..D, G and I. Emit the Phase A table.
- Log scanning is streaming with a prefilter on `'kind': 'Take'`, then a keyed second pass on `now_ns`.
- The coordinator runs it under `systemd-run --user -p MemoryMax=4G`, with `--basetemp` under `~/.cache` and `-p LimitNOFILE=524288`.
- The cycle fetch is a separate coordinator-run step: `nbp_backfill --apply` into a scratch directory with `BREEZY_LIVE=1`. Tests never touch the network, in line with the NO-SEND firewall.

**WP2. Freeze.**
- The coordinator commits `TE2_PREDECLARATION.json`.
- Peer review: prediction-market-reviewer for statistics, python-reviewer for code, plus an adversarial Codex review. The review checks that no Phase B quantity leaked into the declaration.

**WP3. Phase B and classification.**
- Join truth (clipped), alternative truth and venue outcomes.
- Classify, run the tests, apply the verdict rules, and write the JSON and `.md`.
- Add a reconciliation block that compares the per-fill P&L to the TE-1 ledger once TE-1 exists. If TE-1 is not merged, report "TE-1 cross-check pending". Do not wait on it and do not build a second scorer.

**WP4. Findings and consumers.**
Each finding maps to exactly one named consumer. The map is pre-declared, and the coordinator turns each into a row in `docs/core/PROGRESS.md`.
- **K1 or K2:** bug row against the named module. This blocks any FQ re-open (T2).
- **K3:** the station-selection and truth-basis lane (CF-2/CF-7, `cli_basis_*` studies).
- **K4:** venue-semantics row; settlement alignment must be fixed before any family trades this venue.
- **K5:** FQ-v2 / T2 input for an integer-edge reachability screen. If T-EDGE does not reject, closed "no action: within model-expected near-misses".
- **K6, LOC_SOURCE or SPREAD_MISCAL:** F13 / T3 input. It becomes a stratification or regime hypothesis for the F13 freeze review (≥ 10-21), validated forward only. It is never tuned on these 25 days, which sit in the holdout split.
- **K6, LOC_ARTEFACT:** a bug or calibration row against `nbp_calibration` (correction form and season extrapolation), as input to the F13 blend design.
- **K7:** T2 take-rule input (rung stacking, minimum-ask filter, consistent with the M1 reliable-loser cells).
- **K9 / VARIANCE:** closed "no action", with the test, p-value and power stated.

## 6. Dependencies

- **Hard:** `fq-truth` timers (live, F2); the node logs 10-01..10-06; the durable fill store; S3 availability of the 10-01..10-05 cycles; `nbp_backfill` and `parse_nbp_bulletin`.
- **Soft:** TE-1 per-fill ledger (cross-check only); a second truth series (S0-G); a venue-resolved outcome source (S0-G).
- **Sequencing:** WP0 → WP1 → WP2 (freeze) → WP3 → WP4. WP2 is a hard stage boundary: nothing in WP3 may start before the freeze commit exists.
- **Routing:** Grok then Codex then Claude tdd-guide for implementation. The coordinator runs `scripts/ci/run_tests_no_egress.sh` and reads the exit code before any push.
- **Worktree:** if the build runs in a worktree, set `PYTHONPATH=<wt>/src`. Never run `uv`, `pip` or any installer. Do not use `git stash`.
- **Focused gate must include:** the exec-import pin, the firewall guards, the citation map, and `lint-imports` ("N kept, 0 broken"), run from the repo root. Import `fill_source`, not `exec.client`, to avoid tripping the x1 set-equality pin.
- **Independence:** the TE-2 reviewer must not be the TE-1 or script author.

## 7. Risks

1. **Overfit on 25 points.** Mitigated by the outcome-blind Phase A, the frozen declaration, exact tests, and the Holm family. The headline direction is disclosed as already known (S0-H).
2. **Holdout contamination.** Any fix tuned on these days cannot be validated on them. Mitigated by the S0-E guard and the "forward only" consumer wording for F13 and T3.
3. **Cycle retention or reissue.** S3 may not serve or may have reissued a bulletin. Mitigated by the S0-D reproduction gate and the ledger sha comparison. A miss is class K1, never silently skipped.
4. **Ask proxy.** The fill cost stands in for the decision-time ask. The audit's zero-slippage result supports it, but a decision-time ask remains unauditable (audit "Gaps"). State this in the report.
5. **Unverified TXN window.** The NBP 18-hour window is UNKNOWN (P9). If K3 or K6 attribution depends on window alignment, say so and do not assert it.
6. **Dependence across stations.** A regional heat event makes station-days correlated. The cluster-collapsed sensitivity and the downgrade rule cover it.
7. **Truth basis.** CLI is the settlement truth for the venue by project memory, but the venue-side settlement was not cross-checked. K4 and K3 can stay UNTESTABLE. The report must say so rather than score them as zero.
8. **Resource limits.** Large logs and bulletins (about 35 MB each). Use streaming, a memory cap, a scratch directory for raw bulletins, and `--basetemp` under `~/.cache` (tmpfs fills RAM).
9. **Verdict misuse.** VARIANCE could be read as permission to re-arm. The report text must state it is not.

## 8. Non-goals

- No re-arm, no un-halt, no `BREEZY_ORDERS_ENABLED` change, no permit work. The RULING_FQ-v2-NO-TRADE stays in force and TE-2 only feeds T1–T3 inputs.
- No edits to `src/breezy/strategy/**`, `nbp_calibration`, the artefact, or any manifest. A defect found becomes its own bug row.
- No refit, no recalibration, no new model, no `open_holdout`, no marker write.
- No change to PREREG semantics, F13 pins, or `F13_prereg_blend_v1.json` outside the freeze procedure.
- No M1-v3 outcome data, and no truth row after 2026-10-06 held or printed.
- No second scorer and no TE-1 build. No NO-side analysis (that is TE-3). No venue orders, no live network calls from tests.
- No counterfactual P&L presented as a finding.

## 9. Acceptance (the goal state)

- [ ] All 25 losses carry a primary class and secondary flags from the frozen taxonomy, or an explicit UNTESTABLE or TRUTH_UNSETTLED reason.
- [ ] One aggregate verdict (FIXABLE_DEFECT, MODEL_LIMITATION, VARIANCE or INCONCLUSIVE) with the exact tests, p-values and power stated, and a ranked list when mixed.
- [ ] Every finding maps to one named consumer: a bug row, an F13 or FQ-v2 input, or a closed "no action" with its reason.
- [ ] The result reproduces from a committed script, with the predeclaration sha and the script sha recorded in the artifact.
- [ ] The full gate passes with a read exit code, and no re-arm took place.

Key paths for the implementer:
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/decision.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/fill_source.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/decision_link.py`
- `/home/jon/breezy/src/breezy/analysis/nbp_calibration.py`
- `/home/jon/breezy/scripts/analysis/nbp_backfill.py`
- `/home/jon/breezy/scripts/analysis/nbp_shadow_parity_pure.py`
- `/home/jon/breezy/deploy/families/pm_us_crh_fq_v1.json`
- `/home/jon/breezy/docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md`
- `/home/jon/breezy/docs/evidence/FQ_LOSS_TRIAGE_2026-10-04.md`
- `/home/jon/breezy/docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md`
- `/home/jon/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv`