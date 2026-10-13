# S2 plan r4: DELTA against `S2_stage0_replay_plan_r3.md` (2026-10-12)

**MAKER-S2 plan r4 = r3 + this delta (rev 2 + final-round edits, §(p)), 2026-10-13; status READY.**

r3 stays in force except at the anchors named here. "r3 Lnn" means a line of `docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`. "MAKER-S2" is this study; "NBP S2" is the calibration study named in holdout clause 3. They are different studies.

Sources:
- r3 round: `reviews/S2-r3-pmr-verification.md` (F-1..F-15, E-1..E-3); `reviews/S2-r3-mle-verification.md` (F1..F10, edits 1–7).
- r4 round: `reviews/S2-r4-pmr-verification.md` (H-1..H-3, M-1..M-7, L-1..L-7); `reviews/S2-r4-mle-verification.md` (H1, M1–M6, L1–L4, table check).
- Spec v0.3 `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` §3 (:69-136), §6.0 (:211-230), §6.1 (:232-247), §6.9 (:290-304).
- Consumer: `S3_loss_floor_reachability_plan_r3.md:41-42,142,149`, `S3_loss_floor_reachability_plan_r4_delta.md` (a)(g)(h)(j), `docs/evidence/RULING_MAKER-S3_loss_stop_window_2026-10-13.md` O-4.
- Licence: `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md:29-32,38-42`, `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md:89-92` (B-3), `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md` (rev 2), `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` clauses 1–3, `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r10.md:574`.

## Verified (rev 1 at dd811c3b; rev 2 additions at 9ef53d17; codegraph + line reads)
- **S1 census, `src/breezy/analysis/maker_tape_census.py`.**
  - `REASONS` is at `:126-134`. `COVERED` means plan-window coverage ≥ `COVERAGE_MIN` 0.90 and longest hole ≤ `LONGEST_HOLE_MAX_MIN` 60 min (`:92-93`; `classify` `:640-656`).
  - `covered_bidlive` applies the same gates to D−1 16:50Z → D 02:50Z (`:119-124`, `:170-175`, row field `:584`). Rows are read with `read_censused_days` / `CensusedDay.from_dict` (`:490-521`).
- **S1 effective n.** `_n_eff(per_date) = Σ_d m_d/(1+(m_d−1)·RHO_ASSUMED)` (`:689-690`), with `RHO_ASSUMED` 0.5 and `N_EFF_FLOOR` 30 (`:96-97`). S-1 fires when n_eff < N_EFF_FLOOR (`:715-716`).
- **S3 ICC contract, `scripts/analysis/fq_loss_floor_mc_maker_templates.py`.**
  - `FILL_ICC` = 0.5/7 per rung-trial (MAKER-S2's unit) and `FILL_ICC_SD` = 0.5/3 (`:79-85`). `station_day_icc` maps ×7/3 (`:104-110`).
  - `MakerMix.__post_init__` refuses `fill_icc` < 0.5/7 or a mapped value ≥ 1 (`:144`). An input of 0.5 maps to 1.167 and is refused.
- **Poll interval.** `DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS: Final[int] = 900` (`src/breezy/ingest/nbm_quantile_actor.py:126`).
- **Fit window.** `DEFAULT_SPLITS.v5_fit_slice` = 2026-05-04..06-30 and `holdout_start` = 07-01 (`src/breezy/analysis/nbp_calibration.py:273-278`). The evidence doc `NBP_S2_VALIDATE_RESULT_2026-09-30.md` carries `artefact_sha256` at :7 and :39; its latest `last_climate_day` is 2026-06-30 (:131).
- **Holdout.** Frozen [2026-07-01, 2026-10-02) (clause 1). Clause 3 discloses contamination of [07-01, 10-01) only, so 2026-10-01 is sealed. AUT-4 forward windows are anchored 2026-10-02 (AUT-4 r10 :574).
- **`select_rungs` does not exist at HEAD.** It is a WP3 deliverable (`maker_stage0_rule.py`).

## (a) Verdict row V0 UNDERPOWERED-WAIT (r3 L30-45, L50, L59, L258-265, L274-278)
- **r3 §1.1 gains V0 ahead of V1:** `| V0 | n_eff_gov < 30 (spec §6.0 :222-224) | UNDERPOWERED-WAIT |`. **V3 cell:** "`NO-GO (stress)`, spec §6.0 :221-222".
- **Governing estimator (frozen; S1's outcome-independent form).**
  - `n_sd` = covered bid-bearing station-days per (e); `m_d` = their count on climate date d; `n0` = number of dates.
  - `n_eff_gov = Σ_d m_d/(1+(m_d−1)·RHO_ASSUMED)`. `RHO_ASSUMED` and `N_EFF_FLOOR` are **imported** from `breezy.analysis.maker_tape_census`, never copied.
  - `test_n_eff_gov_equals_s1_n_eff_on_same_per_date` asserts equality against the public `summarise(rows).n_eff_ub` on all-COVERED generated `CensusedDay` rows; `_n_eff` is neither imported nor aliased (final round, MLE E-1).
  - n_sd is fixed before any fill, so V0 never depends on a fill outcome.
- **Fitted ICC: REPORT-ONLY, never decides V0.**
  - Data: y_dj ∈ {0,1}, the **base-rule** station-day fill indicator; clusters = climate dates; N = n_sd, k = n0.
  - SSB = Σ_d m_d(ȳ_d−ȳ)², SSW = Σ_d Σ_j (y_dj−ȳ_d)². MSB = SSB/(n0−1), MSW = SSW/(n_sd−n0). m0 = (n_sd − Σ_d m_d²/n_sd)/(n0−1).
  - `rho_hat` = (MSB−MSW)/(MSB+(m0−1)·MSW), truncated to [0, 1]. It is printed as `fill_icc_station_day`.
  - **Undefined** when n0 < 2, when n_sd = n0 (MSW has 0 df), or when the denominator is 0 (no fills or all fills). Undefined prints "undefined" with no substitute value.
  - Also printed: `deff_hat = 1+(m0−1)·rho_hat` and `n_eff_hat = Σ_d m_d/(1+(m_d−1)·rho_hat)`.
  - **Banner** `FITTED-ICC DISAGREES ON THE FLOOR` when (n_eff_hat ≥ 30) ≠ (n_eff_gov ≥ 30). It is report-only.
- **Order of evaluation.**
  - V0 is evaluated first, on the **minimum n_eff_gov over unit hypotheses**. It is identical across hypotheses when n_sd is common; the minimum is the rule regardless.
  - If V0 does not fire, the r3 severity order applies across hypotheses: NO-GO > NOT-KILLED-UNSCREENED > NOT-KILLED.
  - Ties go to the hypothesis with the lower `r_lo` (f).
- **Under V0:**
  - The report prints n_sd, n0, n_eff_gov, the fitted block, and base and stressed rates with cluster-bootstrap intervals (f).
  - V1–V5 are printed as **threshold comparisons** (e.g. "stressed 0.07 < 0.10"), never as NO-GO strings, under "descriptive, not a label".
  - S-1 (programme) does not fire. No build starts (spec :224). S3's binding run is refused per (n).
- **E1 (r3 L50) gains** "…and S1's summary carries no `S-1` (`maker_tape_census.py:715-716`)". This is necessary, not sufficient, because n_sd ⊆ covered gives n_eff_gov ≤ S1's n_eff_ub.
- **S-4 (r3 L59) is replaced by:** "the sample floor (spec :222-224) is enforced by V0; n_sd = 0 is degenerate (no rate computable): report and stop."
- **"Spec inputs" (r3 L258-265) is deleted** and replaced by: "None. v0.3 covers all six (spec :221-222, :222-224, :88, :85, :239-240, :105-118)." The body pointers at r3 L38, L142 and L163 become those cites.
- **Conformance table.**
  - R4: "V3 = spec :221-222; V0 added (r4 (a))".
  - R8: "r3 claimed 'pruned to gaps v0.3 does not cover'; all six were in v0.3; deleted in r4 (a)".
  - R2: drop "spec input 5 dropped".
- **WP5 RED tests:**
  - `test_verdict_table_rows_v0_to_v5`;
  - `test_v0_is_decided_by_rho_assumed_not_by_fill_outcomes` (same days, fills flipped, V0 unchanged);
  - `test_n_eff_gov_equals_s1_n_eff_on_same_per_date`;
  - `test_below_effective_n_floor_is_underpowered_wait_not_no_go`;
  - `test_underpowered_wait_prints_v1_to_v5_as_threshold_comparisons`;
  - `test_fitted_icc_matches_hand_anova_is_report_only_and_undefined_when_n_sd_equals_n0`;
  - `test_v0_first_on_min_n_eff_gov_then_r3_severity_order`.

## (b) Licence: entry criterion E5 (r3 L49-53, L67, L111)
- **E5.** MAKER-S2's reads of `~/.local/share/breezy/derived/nbp/` are licensed only by the amendment rev 2, **FINAL** and committed.
  - `pins.json` pins the sha of the **FINAL** bytes, never the DRAFT.
  - Its fenced `FROZEN_DATE_SET` block must be filled before P2 and before any MAKER-S2 read other than WP0 step 2.
  - Every read the plan performs is one of the amendment's §1 items 1–5. Any other read is unlicensed.
- **Frozen-set rule** (mechanical; applied once after the S1 run, before P2):
  - The range is the first replayable day (WP0 step 2: global first print instant, which reads print timestamps only) .. min(2026-10-13, last day with a FINAL row in the truth CSV whose sha is pinned in the block). 2026-10-01 and NYC are excluded.
  - A day lacking FINAL at run time is excluded from §6.9 and counted (i)6, never added.
  - The set is never re-chosen after any MAKER-S2 number exists.
- **The driver parses the block.** It refuses:
  - an unfilled `<FILL…>` placeholder;
  - a date outside the rule, 2026-10-01, or a date > 2026-10-13;
  - an NYC row;
  - a (station, day) outside the set;
  - an amendment sha mismatch.
- **Tests:**
  - `test_replay_refuses_day_outside_frozen_set_or_amendment_sha_mismatch` is extended to every refusal above;
  - `test_frozen_set_equals_rule_applied_to_pinned_census_and_truth`.
- **Without E5** the set is 2026-09-18..09-25 (pre-freeze; NBP read under clause 3 as descriptive). S1's n_eff_ub there is ≤ 8 × 4/(1+3·0.5) = 12.8 < 30, so the outcome is necessarily V0. The report states this.
- **r3 L67** becomes "SEARCH days 09-26..10-13 except 10-01 enter only through E5".
- **WP0 positive control (r3 L111):** the SFO sample is dated inside the frozen set (never 10-01). It runs only after E5.

## (c) Code-freeze clause (new §5.1; r3 L28, L193, L199-204)
- **One committed sha.** The verdict run executes from one committed sha (`code_sha` in `run_manifest.json` and `s3_inputs.json`).
  - The driver refuses unless `git status --porcelain -- scripts/analysis src tests pyproject.toml uv.lock` is empty. `tests` includes `tests/fixtures`.
  - Any code, threshold or constant change after the run starts voids it.
- **Verdict ledger** (amendment §3). The driver keeps `~/.local/share/breezy/derived/maker_stage0/verdict_ledger.jsonl`, keyed by the amendment sha; its path is in `pins.json`.
  - The entry is appended **after every preflight refusal** (clean tree, frozen block, amendment sha, E4, subset flags) **and before the S-7 pre-pass**, so a launch refused for a trivial reason never burns the ledger (final round, MLE E-2).
  - A verdict run refuses when an entry exists, unless the sha of a dated addendum naming the voided `run_id` is supplied. The driver refuses an addendum unless the named `run_id` directory is `.void`-renamed and contains none of `scored_episodes.csv`, `s3_inputs.json`, `verdict.*` (test `test_ledger_refuses_addendum_for_run_with_result_files`). The same addendum form may name a substitute verify-first day (on or before 2026-06-30, by date, before run-time step 5) (final round, PMR E-D).
  - Re-runs are allowed only for runs void for non-result reasons: S-5, S-6, S-7, E4, OOM, crash, host kill. Result-driven re-runs are forbidden (PMR M-4).
- **Abort handling.**
  - There is no resume. A run that dies is void: its directory is renamed `<run_id>.void`, sha-pinned, and its `episodes.jsonl` is never opened.
  - `progress.jsonl` carries no fill, rate or label field, so a code fix after a crash follows no fill number.
- **Subset flags.**
  - The verdict run refuses `--stations`, `--days`, `--tail-only` and `--bench`.
  - Only `--bench` accepts `--stations/--days`. It skips scoring and writes **no** `episodes.jsonl` or fill file (i)8.
  - `--tail-only` is a separate report-only unit on the same `code_sha` (r3 L203), writing only `tail_reliability.csv`.
- **Tests:**
  - `test_verdict_run_refuses_subset_flags`;
  - `test_verdict_run_refuses_dirty_tree_incl_pyproject_lock_and_fixtures`;
  - `test_verdict_ledger_refuses_second_run_without_void_addendum`;
  - `test_progress_events_carry_no_fill_or_rate_fields`;
  - `test_tail_only_is_report_only_and_records_code_sha`.

## (d) One schedule source (r3 L124, L217, L254)
- **PRIMARY schedule on every day:** nominal `permit_window_for_day` [16:50Z, 02:50Z); `STOP_PRIOR_UTC`; the UTC-midnight GTD cut.
- **The logged-relaunch overlay is a report-only second pass** (`process_schedule_overlay.json`, `overlay_station_days.csv`), computed inside the same verdict invocation (one ledger entry; amendment §1) (final round, PMR E-A).
  - It never sets the label. Its V-row outcome is printed beside the primary, with the count of days it changed.
- **Full-day outage** = no boot line and no permit line inside [16:50Z, 02:50Z) in node-log files (Popen stdout, never journald) whose span **fully** covers that window.
  - Outage days leave numerator and denominator alike, and are listed and counted.
  - A day with no covering file, **or with a file covering only part of the window**, is `node_log_absent`. It stays in, on PRIMARY, and is counted.
- **WP1 pins the boot/permit line patterns** as constants, tested against real log lines. The fixtures include a node booted before 16:50Z (no in-window boot line, permit line present).
- **r3 L124 is replaced by the above.** r3 L217: "nominal schedule everywhere; logs feed only the overlay and outage exclusion". Node-log files (path, size, sha256, byte range) go in `pins.json`. r3 Q1 is closed.
- **Tests:**
  - `test_logged_relaunch_adds_a_cut_in_overlay_only`;
  - `test_nominal_schedule_is_primary_on_every_day`;
  - `test_full_day_outage_needs_covering_log_without_boot_or_permit_line`;
  - `test_outage_day_leaves_numerator_and_denominator`;
  - `test_absent_or_partial_node_log_keeps_day_on_primary_schedule`.

## (e) Denominator, direction, MAX_RUNGS=1 (r3 L111, L143, L175, L256)
- **Covered** = S1 `censused_days.jsonl` row `reason == "COVERED"` **and** `covered_bidlive` true, read with `read_censused_days`.
  - MAKER-S2 never re-derives coverage.
  - Non-COVERED rows are counted by reason. The "≥ 1 depth frame" rate is report-only. r3 Q3 is closed.
- **Bid-bearing** is defined before the marketability guard: a covered station-day with ≥ 1 §3 attempt, refused or not.
  - An attempt is a decision instant inside the PRIMARY process-live window where `select_rungs` (WP3 deliverable; absent at HEAD) returns ≥ 1 rung with bid ≥ B_FLOOR.
  - Bid-bearing is decided by whether a **first** attempt exists, so it precedes every fill.
  - Days where every attempt was guard-refused stay in the denominator as unfilled (`guard_refused_only`).
- **WP0 direction (r3 L111).** Agreement ≤ 0.1 ("inverted") is an **S-2 STOP** back to the spec, never a recorded flip. Test: `test_inverted_agreement_raises_stop_s2`.
- **MAX_RUNGS = 1 subset (r3 L143).**
  - The K1 rung is the rung `select_rungs` ranks first (lowest p_YES passing P_MIN, non-modal, non-adjacent) at the station-day's first attempt instant, held for the day.
  - K1 rates count only that rung's episodes, on the same denominator, under base and stressed rules.
  - Test: `test_k1_rung_is_first_attempt_rung_held_for_day_with_stressed_pass`.
- **More tests:** `test_bid_bearing_counts_guard_refused_attempts`, `test_covered_is_s1_covered_and_covered_bidlive`.

## (f) S3 interface: `s3_inputs.json` (goal r3 L21, L28)
- **Goal item 2 (r3 L21).** Beside each rate: the climate-date cluster-bootstrap 95% two-sided percentile interval as **primary** (`bootstrap_cluster_draws` / `percentile_interval`, `scoring_core.py:216,246`; seed 20260919 × 2000), with Wilson as sidecar.
  - With fewer than 5 clusters the interval prints "not estimable" and its key is `null`.
- **Cross-hypothesis rule** (final round, PMR E-B).
  - `r_lo`, `r_lo_station_day`, `r_lo_position`, `r_lo_k1`, `r_lo_lcb_cluster_boot` and `r_lo_k1_lcb_cluster_boot` are each the **minimum over unit hypotheses**. `r_lo_by_hypothesis` and `r_lo_lcb_by_hypothesis` are maps (tested). `r_lo_se_cluster_boot` is the SD of the draws of the hypothesis that attains the minimum `r_lo_lcb_cluster_boot` (never the smallest SD). The "governing" (more severe) hypothesis never carries a higher value.
  - All other keys come from the governing hypothesis (a).
  - The rule is stressed (2 × (size ahead + 1)) unless the key says `base`. The unit is the station-day unless the key says `position`/`rung_trial`.

| Key | Definition |
|---|---|
| `verdict` | exact string: `UNDERPOWERED-WAIT`, `NO-GO (fill)`, `NO-GO (adverse selection)`, `NO-GO (stress)`, `NOT-KILLED-UNSCREENED`, `NOT-KILLED` |
| `r_lo` | = `r_lo_station_day` (S3 `f_kill`; S3 r4 (h)) |
| `r_lo_station_day`, `r_lo_position` | stressed point, each unit, min over hypotheses |
| `r_lo_by_hypothesis` | {hypothesis: stressed station-day point} |
| `r_lo_lcb_cluster_boot` | 2.5th percentile of the two-sided 95% stressed station-day bootstrap (S3 `f_pass`); not a one-sided bound |
| `r_lo_se_cluster_boot` | SD of those draws |
| `r_lo_k1`, `base_k1` | K1 station-day rates (e); `r_lo_k1` min over hypotheses |
| `r_lo_k1_lcb_cluster_boot` | 2.5th percentile of the stressed K1 station-day bootstrap, min over hypotheses (S3 `f_pass` at k = 1) (PMR E-C) |
| `fill_icc_rung_trial_k1` | the (a) ANOVA on stressed-rule K1 positions only (≤ 4 per date); `null` when undefined (PMR E-C) |
| `base_station_day_rate`, `base_station_day_rate_ci_cluster_boot` | base point; [2.5, 97.5] percentiles |
| `two_fill_share` | filled station-days with 2 filled positions ÷ filled station-days |
| `bid_bearing_share_of_covered_listed` | n_sd ÷ covered station-days |
| `fill_icc_rung_trial` | **the only ICC S3 reads.** The (a) ANOVA on stressed-rule 0/1 indicators, one per posted position (station-day × rung, ≤ 8 per date), clusters = climate dates, truncated to [0, 1]. `null` when undefined, **never 0.5** |
| `fill_icc_station_day` | report: the (a) fitted base-rule station-day value, or `null` |
| `n0_climate_dates`, `n_eff_gov` | (a) |
| `b` | lower median (sorted index ⌊(n−1)/2⌋, on-tick) of realised bid, $, one stressed-rule fill per filled position; `null` if none |
| `realised_bid_iqr` | [q1, q3], $, same fills, `numpy.quantile(method="inverted_cdf")` |
| `n_stressed_fills`, `realised_bid_median_base` | count behind `b`; base-rule lower median |
| `max_rungs_hypothesis` | 2 (the K1 keys carry the 1 hypothesis). **No `k` key**: S3 takes k from the admission ruling, else brackets {2, 1} (n) |
| `unit_hypothesis`, `code_sha` | governing hypothesis; the (c) sha |

- **Test:** `test_s3_inputs_json_has_every_named_key`. It asserts:
  - `k` is absent;
  - `r_lo == min(r_lo_by_hypothesis.values())`;
  - `fill_icc_rung_trial` is null when undefined, never 0.5;
  - `b` ∈ [0.70, 0.80] or null.

## (g) Reproducibility (r3 L28, L122-125, L197)
- **`station_days.csv`.** One row per (station, climate_day, unit_hypothesis) for **every census day in the frozen set**, including non-COVERED, outage and `node_log_absent`; replay fields are null where not replayed. Columns:
  - identity and status: `station`, `climate_day`, `cluster_id`, `unit_hypothesis`, `census_reason`, `covered_bidlive`, `covered`, `outage_excluded`, `node_log_absent`, `bid_bearing`, `guard_refused_only`;
  - depth: `n_depth_frames`, `has_depth_frame`;
  - counts: `n_attempts`, `n_episodes`, `n_refused`, `n_process_cuts`, `n_gtd_cuts`, `rung_trials_posted`, `rung_trials_filled_base`, `rung_trials_filled_stress`;
  - hours: `process_live_h`, `forecast_valid_h`, `gap_h`, `covered_live_h`, `gap_share` (= gap_h / forecast_valid_h; null if 0);
  - fills: `filled_pairs_base`, `filled_pairs_stress`, `k1_rung_id`, `k1_filled_base`, `k1_filled_stress`, `bid_median_fills_stress`;
  - `nogo_driving` = included in the denominator and unfilled under the stressed rule;
  - days-to-200 inputs: `positions_filled_k2_base`, `positions_filled_k2_stress`, `positions_filled_k1_base`, `positions_filled_k1_stress`; days-to-200 divides by distinct `climate_day` among rows with `covered` true, per hypothesis (MLE E-3);
  - clock and scoring: `delta_ns`, `truth_final`, `truth_tmax_f`, `void`, `unresolved_d14`, `theta`.
- **`test_stats_rerun_on_scored_csv_reproduces_tables`** reads `scored_episodes.csv` + `station_days.csv` + `tail_reliability.csv`.
  - It byte-compares: V0 and fitted-ICC blocks, V1–V5, intervals, the S3 block, Tests A/B, tail, Δ distribution, coverage sensitivity, non-COVERED-by-reason, ≥ 1-frame rate, gap-share-of-NO-GO-driving table and days-to-200.
  - It asserts every other block is labelled "run-time only, sha-pinned" and that its sidecar sha matches `pins.json`. Those sidecars are:
    - `overlay_station_days.csv` (d);
    - `wp0_agreement.json`;
    - `stress_plus60_station_days.csv` and `stress_poll_lag_station_days.csv` (i)1;
    - `progress.jsonl` and the bench output.
  - `scored_episodes.csv` columns (MLE E-3): `position_id`, `rung_trial_id`, `station`, `climate_day`, `unit_hypothesis`, `bid`, `filled_base`, `filled_stress`, `p_yes_point_live`, `truth_final`.
- **`pin_inputs` (r3 L125) gains:**
  - the clean-tree assertion and its scope (c);
  - the installed-package-set sha (sorted `importlib.metadata` `name==version`);
  - the full argv;
  - the node-log files (d);
  - the truth cross-check parquet;
  - the truth CSV sha from the frozen block (b);
  - the amendment FINAL sha;
  - the ledger path (c);
  - the run-time-only sidecars;
  - the θ 0.0695 pin site, named.
- **`load_model` (r3 L123)** pins the evidence doc's sha. It asserts, refusing on any failure or an unparseable block:
  1. doc `artefact_sha256` (:7, :39) == sha256 of the loaded artefact;
  2. the v5.0 era's `v5_fit_slice` `last_climate_day` (:131) == `DEFAULT_SPLITS.v5_fit_slice.end` == 2026-06-30;
  3. no era's `last_climate_day` > 2026-06-30.
- **Tests:**
  - `test_load_model_asserts_artefact_sha_and_fit_window_from_evidence_doc` (RED: a doc with a different artefact sha);
  - `test_pins_include_clean_tree_package_set_argv_node_logs_ledger_and_sidecars`.

## (h) Test B relabel (r3 L180-181)
- r3 L180 "conditional exact rate-ratio test" becomes **"Poisson-conditional rate-ratio test (approximation, valid at p ≤ 0.06)"** everywhere.
- Printed beside it, descriptive: the stratum-mix-adjusted rate ratio, and the climate-date cluster count next to each Test A/B p-value. r3 Q2 is closed.

## (i) WP-time items (frozen now; each lands in its named WP before that WP merges)
1. **WP2, poll lag.** A report-only stress delays every `available_at_ns` by `DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS` (900 s), **imported** from `breezy.ingest.nbm_quantile_actor` (`:126`). It sits beside the P2 +60 min stress; both are computed inside the verdict invocation (one ledger entry) and write only the (g) stress sidecars (PMR E-A). Test: `test_poll_lag_stress_delays_available_at_by_actor_poll_interval`.
2. **WP2, 07Z note "moot"** (r3 L221). A 07Z D−1 cycle (≈ 08:10Z) is 8 h-stale by ≈ 16:10Z, before launch. A 07Z D cycle arrives after the 02:50Z permit end. A late 13Z (max 137 min, valid by 15:17Z) is also pre-launch. The live-side bias runs the other way (replay `available_at` = Last-Modified/floor), and item 1 measures it.
3. **WP0/WP4, clock offset.**
   - Δ is computed per recorder instance-day as max |offset_ns| in the station-day's process-live window. A station-day spanning two instances takes the max over both.
   - Δ is applied as a magnitude in the pessimistic direction.
   - **S-7:** any Δ > 10 min aborts the whole run in a pre-pass **before any scoring**. The run is void for a non-result reason (c). The Δ distribution is reported.
   - Test: `test_delta_is_per_instance_day_max_over_instances_and_over_10min_aborts_before_scoring_s7`.
4. **WP5, coverage sensitivity (report-only).** Rates restricted to days with `covered_live_h ≥ 0.5 × process_live_h`, plus the share of `nogo_driving` days with `gap_share` > 0.5. Test: `test_coverage_sensitivity_threshold_half_of_process_live_is_report_only`.
5. **WP5, intervals.** The cluster bootstrap prints beside Wilson for both units, labelled "interval is n_eff-adjusted". Test: `test_fewer_than_five_clusters_prints_not_estimable_and_null_key`.
6. **WP5, §6.9 notes.**
   - UNSCREENED-TERMINAL (spec :300-302) is not a Stage 0 object; the report says so.
   - Test A's p is `p_yes_point_live`.
   - A day lacking CLI FINAL is excluded from §6.9 for filled and unfilled rows alike and counted. Test: `test_day_without_cli_final_is_excluded_from_s69_for_filled_and_unfilled_and_counted`.
7. **WP2/WP4, truth isolation.** The WP2 verify-first (r3 L135, S-6) runs only on climate day **2026-06-30** (amendment §1 item 3), in a function the simulator cannot reach. Test: `test_simulator_transitive_import_closure_excludes_truth` (it walks the transitive import closure, catching shared helpers).
8. **WP6, CLI and driver.**
   - `--bench` writes timing and RSS only: `test_bench_mode_skips_scoring_and_writes_no_episode_or_rate_output`.
   - The driver streams episodes: `test_driver_streams_episodes_without_accumulating` is structural (a consumed-iterator spy, not a tracemalloc slope).
   - `test_driver_refuses_existing_run_dir`.
9. **Run plan (r3 L201-202).**
   - Bench at 4 and then 8 station-days of the frozen set, chosen as the **heaviest by catalog bytes** (outcome-blind).
   - Per-station-day RSS goes in the progress events. An in-run RSS watch aborts under S-5 at 4 GiB.
   - Linear extrapolation to the set size is a screen, not a proof; S-5 fires if the projection exceeds 4 GiB or 6 h.
   - `MemoryMax` = min(2 × peak, 4G) is containment. The Monitor is re-armed on expiry.
10. **WP3, GTD re-post note.** The 00:00Z cut re-posts at the same instant; live waits for the next event. This is immaterial and stated in the report.

## (j) Stale facts corrected
| r3 anchor | r3 said | r4 says |
|---|---|---|
| L53 E4, L219 | "Today 4.2 GB, so S2 is blocked" | 2026-10-13: 108 GB free; E4 satisfied. Still checked before P2, every gate, the bench and the run |
| L67 | "~8 dates × 4; more needs S1's SEARCH declaration" | Pre-freeze 09-18..09-25 (8 × 4). SEARCH 09-26..10-13 minus 10-01 = 17 dates / 68 station-days, via E5 only. Ceiling 25 dates / 100 station-days (24 / 96 if the first day is 09-19) |
| L218 | S1 outputs "not delivered" | S1 run 2026-10-14 10:00–15:00Z; then E1 |
| L215 | truth "to 10-11" | Frozen by the (b) rule against the pinned truth CSV |
| L272-278 | R2/R4/R8 rows | as (a) |

## (k) Build-now WP list
- **Build now with fixtures** (none needs S1 output, P2, disk or E5):
  - WP3, including the new `select_rungs`;
  - WP4 (pure, synthetic events, incl. K1 and per-instance Δ);
  - WP1: census loader, unit loader, truth, `pin_inputs`, ledger, frozen-block parser, schedule + overlay + outage, tmp git repo for the clean-tree tests;
  - WP2: `DerivedNbpRow` store + `tests/fixtures/nbm/nbptx_t{13,19,01}z_excerpt.txt`;
  - WP0: synthetic catalog;
  - WP5: fixture CSVs;
  - WP6: fake catalog + store, incl. `--bench`.
- **Order:** WP3 ∥ WP4 ∥ WP1 ∥ WP2 ∥ WP0 → WP5 → WP6. Each WP passes the r3 L102 focused gate.
- **Shared fixture.** It is **generated** from `CensusedDay.to_dict` and its field set (never hand-typed) plus the unit-verdict set {CONTRACTS, USD_NOTIONAL_YES, USD_NOTIONAL_TAKER}, so an S1 schema change fails MAKER-S2 loudly. The fixture test also round-trips `write_censused_days` → `read_censused_days` (MLE E-4).
- **Run-time steps, in order:**
  1. S1 run (10-14), then E1.
  2. WP0 step 2: first print instant.
  3. Pin the truth CSV, apply the (b) rule, fill the block, commit the amendment FINAL + RA-13-FW ledger line (E5).
  4. P1/P2.
  5. WP2 verify-first on 2026-06-30 (S-6).
  6. WP0 direction check + SFO positive control.
  7. Bench at 4 + 8 station-days.
  8. Verdict run (ledger entry, committed sha).
  9. `--tail-only`.
  10. Commit the evidence by explicit paths.

## (l) Disposition of review findings (r3 and r4 rounds)
| Round | Finding | Disposition |
|---|---|---|
| r3 | PMR F-1/F-2/E-1, MLE F1/edit 1: no V0; Spec inputs false; R4/R8 | (a) |
| r3 | PMR F-3/E-3: S3 interface unnamed | (f) |
| r3 | PMR F-4/E-2: forecast-store read unlicensed | (b) + amendment |
| r3 | PMR F-5a/b: bid-bearing after guard; two covered definitions | (e) |
| r3 | PMR F-6/F-7, MLE F2/edit 2: mixed schedule; outage contradiction | (d); overlay never governs |
| r3 | PMR F-8, LOW-15: no code freeze; subset flags | (c) |
| r3 | PMR F-9: inverted direction flips the rule | (e) S-2 |
| r3 | PMR F-10: MAX_RUNGS1 ill-defined | (e), (f) `r_lo_k1` |
| r3 | PMR F-11, LOW-12: Test B "exact"; cluster count | (h) |
| r3 | PMR LOW-13, MLE F8/edit 7: Wilson on clustered data | (f), (i)5 |
| r3 | PMR LOW-14: GTD re-post | (i)10 |
| r3 | PMR §5 path 7: stricter unit | (f) min over hypotheses |
| r3 | MLE F3/edit 3, F4/edit 4: fit window, pins, rerun | (g) |
| r3 | MLE F5/edit 5, F6/edit 6, F7: poll lag/07Z; covered; global Δ | (i)1–2, (e)+(i)4, (i)3 |
| r3 | MLE F9, F10: §6.9 notes; truth/bench peeking | (i)6, (i)7–8 |
| r3 | MLE run plan; build-before-run; r3 Q1–Q3 | (i)8–9; (k); (d)/(h)/(e) |
| r4 | MLE H1, PMR M-1: outcome-dependent ICC floor | (a): V0 on S1's RHO_ASSUMED form; fitted ICC report-only with banner. PMR's `max(rho_hat, 0.5/7)` option is superseded by the coordinator ruling |
| r4 | PMR M-5, MLE H1(iii): bracket order with V0 | (a) |
| r4 | PMR H-1: ICC unit for S3 | (f) `fill_icc_rung_trial` (null, never 0.5) + `fill_icc_station_day`; (n)3 |
| r4 | PMR H-2, MLE M3: reads beyond licence; "once"; ledger; abort | amendment §1/§3, (b), (c), (i)7–8 |
| r4 | PMR H-3, MLE M5 (cite): 10-01 sealed; AUT-4; name collision | amendment §2, (b), header naming |
| r4 | PMR M-2: `k` alias | (f) deleted; (n)2 |
| r4 | PMR M-3: r_lo across hypotheses | (f) min per `r_lo*` key |
| r4 | PMR M-4, L-6: re-run contradiction; S-7 mid-run | (c), amendment §3, (i)3 |
| r4 | PMR M-6, MLE M5: frozen-set rule; machine-readable | (b), amendment block |
| r4 | PMR M-7: S3 allowlist | (n)1 |
| r4 | PMR L-1..L-4: IQR, lower median, n/base median, 2.5th pct | (f) |
| r4 | PMR L-5: V1–V5 under V0 | (a) |
| r4 | PMR L-7: `select_rungs` absent | Verified block, (e), (k) |
| r4 | PMR §4: pin FINAL sha | (b) |
| r4 | MLE M1, M2, table check (1)–(5) | (g) |
| r4 | MLE M4: artefact sha; "≤ … ==" wording | (g) |
| r4 | MLE M6: four unnamed tests | (i)1, (i)4, (i)5, (i)6 |
| r4 | MLE L1, L2, L3, L4 | (i)3; (d); (c); (i)7 |
| r4 | MLE items 5–6: first-attempt bid-bearing; heaviest bench days, RSS watch | (e); (i)9 |
| r4 | MLE build-now caveats (a)(b) | (i)8, (k) |

## (m) Rev 1 open points
All are resolved: 1 → (a); 2 → (f) and (n)2; 3 → (n)1; 4 → amendment §2; 5 → (d) and (i)1.

## (n) S3 plan amendment (carried to the S3 WP4 brief; an S3 r4 (g) dependency)
1. **Allowlist.** S3 WP4 binding mode admits MAKER-S2 `verdict` only by exact-string allowlist {"NOT-KILLED", "NOT-KILLED-UNSCREENED"}. Every other value is refused: `UNDERPOWERED-WAIT`, any `NO-GO (…)`, missing, or unknown. Test `test_binding_mode_refuses_any_label_outside_allowlist` supersedes `test_binding_mode_refuses_s2_no_go`. MAKER-S2 does not claim this refusal is in force until that S3 WP4 test is merged.
2. **k.** S3 takes k from the MAX_RUNGS admission ruling, else brackets {2, 1}. MAKER-S2 emits only `max_rungs_hypothesis`.
3. **ICC.** S3 reads only `fill_icc_rung_trial`. Null handling, flooring at `FILL_ICC` (0.5/7) and the `MakerRefusal` on a mapped value ≥ 1 (`fq_loss_floor_mc_maker_templates.py:144`) are S3's. MAKER-S2 never pre-clips or substitutes. The S3 WP4 brief must apply the floor rather than pass the raw value to `MakerMix`.
4. **f.** S3 `f_kill` = `r_lo` and `f_pass` = `r_lo_lcb_cluster_boot`, both minimum over unit hypotheses (f). For k = 1: `f_kill` = `r_lo_k1`, `f_pass` = `r_lo_k1_lcb_cluster_boot`, ICC = `fill_icc_rung_trial_k1` (PMR E-C). A rung-trial ICC above 3/7 maps to ≥ 1 and trips `MakerRefusal` (templates :144); the S3 WP4 brief must define that outcome, never clip it.

## (p) Final-round disposition (2026-10-13; `reviews/S2-r4-pmr-final.md`, `reviews/S2-r4-mle-final.md`)
Both READY-WITH-EDITS, text only. Applied by the coordinator: MLE E-1 → (a); E-2 → (c); E-3 → (g); E-4 → (k). PMR E-A → (d), (i)1, amendment §1; E-B → (f); E-C → (f), (n)4; E-D → (c), amendment §3; E-E → amendment §2; E-F → amendment §1. (o)2 resolved by E-1 (public `summarise` API). **Status: READY.** Build on the (k) list may start; the amendment goes FINAL only after the frozen block is filled.

## (o) Rev 2 residual notes (for the verification round)
1. Verify-first day fixed at 2026-06-30 (last fit-slice day); whether the NBP store and truth CSV hold rows for it is checked at run-time step 5 and fails closed (dated addendum before step 5 if missing).
2. `_n_eff` is private in S1; the plan imports only `RHO_ASSUMED`/`N_EFF_FLOOR` and tests equality against `_n_eff`. If a lint rule blocks a test importing a private name, S1 needs a public alias (S1-owned code).
3. `fill_icc_rung_trial` comes from the governing hypothesis while `r_lo*` are minima across hypotheses; S3 may pair an f and an ICC from different hypotheses (accepted for rule uniformity).
4. The AUT-4 disclosure binds AUT-4 only through the amendment's text; the AUT-4 plan carries no line recording it.
