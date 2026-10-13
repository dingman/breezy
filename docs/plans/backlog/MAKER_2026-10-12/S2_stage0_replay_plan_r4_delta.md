# S2 plan r4: DELTA against `S2_stage0_replay_plan_r3.md` (2026-10-12)

**S2 plan r4 = r3 + this delta (rev 1), 2026-10-13; status READY-PENDING-VERIFICATION.**

r3 stays in force except at the anchors named here. "r3 Lnn" means a line of `docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`.

Sources:
- `docs/plans/backlog/MAKER_2026-10-12/reviews/S2-r3-pmr-verification.md` (F-1..F-15, E-1..E-3);
- `docs/plans/backlog/MAKER_2026-10-12/reviews/S2-r3-mle-verification.md` (F1..F10, required edits 1–7);
- spec v0.3 `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` §3 (:69-136), §6.0 (:211-230), §6.1 (:232-247), §6.9 (:290-304);
- consumer: `S3_loss_floor_reachability_plan_r3.md:41-42,142,149`, `S3_loss_floor_reachability_plan_r4_delta.md` (a)(h)(j), `docs/evidence/RULING_MAKER-S3_loss_stop_window_2026-10-13.md` O-4;
- licence: `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md:29-32,38-42`, `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md:89-92` (B-3), and the new `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md`.

## Verified at dd811c3b (codegraph + line reads)
- **S1 census, `src/breezy/analysis/maker_tape_census.py`.**
  - `REASONS` at `:126-134`.
  - `COVERED` means plan-window coverage ≥ `COVERAGE_MIN` 0.90 and longest hole ≤ `LONGEST_HOLE_MAX_MIN` 60 min (`:92-93`; `classify` `:640-656`).
  - `covered_bidlive` applies the same gates to the bid-live window, D−1 16:50Z → D 02:50Z (`:119-124`; `_bidlive` `:540-547`; row field `:584`).
  - Rows are read through `read_censused_days` / `CensusedDay.from_dict` (`:490-521`).
- **S1 effective n.** `n_eff_ub = Σ_d m_d/(1+(m_d−1)·RHO_ASSUMED)`, with `RHO_ASSUMED` 0.5 and `N_EFF_FLOOR` 30 (`:96-97`, `:689-690`). S1's stop S-1 is UNDERPOWERED (`:715-716`; S1 plan r3 :55).
- **Fit window.** `DEFAULT_SPLITS.v5_fit_slice` = 2026-05-04..06-30 and `holdout_start` = 07-01 (`src/breezy/analysis/nbp_calibration.py:273-278`). `docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md:116-134` records each era's split window; the latest `last_climate_day` is 2026-06-30 (:131).
- **Spec already covers r3's six "Spec inputs".** They are at spec :221-222, :222-224, :88, :85, :239-240 and :105-118.

## (a) Verdict row V0 UNDERPOWERED-WAIT (r3 L30-45, L50, L59, L258-265, L274-278; PMR F-1/F-2/E-1, MLE F1)
- **r3 §1.1 table gains V0 ahead of V1:** `| V0 | n_eff < 30 (spec §6.0 :222-224) | UNDERPOWERED-WAIT |`.
- **V3 cell becomes** "`NO-GO (stress)`, spec §6.0 :221-222 ('Base passes but stressed fails is NO-GO')".
- **Frozen definition** (pinned in WP5 code before any run):
  - `n_sd` = covered bid-bearing station-days per (e). `n0` = distinct climate dates among them. `m̄ = n_sd/n0`.
  - `ρ̂` = one-way ANOVA ICC on the **base-rule** station-day fill indicator (0/1), with climate dates as clusters. Unequal-size form: `ρ̂ = (MSB−MSW)/(MSB+(m₀−1)·MSW)`, where `m₀ = (n_sd − Σm_d²/n_sd)/(n0−1)`. `ρ̂` is truncated to [0, 1].
  - If `ρ̂` is undefined (n0 < 2, or a zero denominator, e.g. no fills or all fills), use `RHO_ASSUMED` = 0.5 (S1's constant, `maker_tape_census.py:96`) and print `icc_fallback`.
  - `deff = 1 + (m̄−1)·ρ`, and `n_eff = n_sd / deff`. The floor is 30 (`N_EFF_FLOOR`).
  - The base unit hypothesis is used. If the unit is bracketed, `n_eff` is computed under each hypothesis and the **smaller** governs (`n_sd` is pre-fill, so only `ρ̂` differs).
  - S1's `n_eff_ub` form (ρ = 0.5) on the same set is printed beside it, report-only.
- **Under V0:**
  - The report prints n_sd, n0, ρ̂, deff, n_eff, and the base and stressed station-day rates with their cluster-bootstrap intervals (f).
  - V1–V5 are evaluated and printed under "descriptive, not a label".
  - S-1 (programme) does **not** fire. No build starts (spec :224).
  - S3's binding run is refused, because S3 r3 §2 item 2 admits only NOT-KILLED*.
- **E1 (r3 L50) gains:** "…and S1's summary carries no `S-1` stop (S1 not UNDERPOWERED, `maker_tape_census.py:715-716`)".
- **S-4 (r3 L59) is replaced by:** "S-4 (sample floor, spec §6.0 :222-224) is enforced by V0. n_eff < 30 gives UNDERPOWERED-WAIT with n, n_eff and interval. n_sd = 0 is the degenerate case: no rate is computable, so report and stop."
- **"Spec inputs" (r3 L258-265) is deleted** and replaced by one line: "None. v0.3 covers all six (spec :221-222, :222-224, :88, :85, :239-240, :105-118)." The body pointers "Spec input n" at r3 L38, L142 and L163 become those spec cites.
- **Conformance table:**
  - R4 row: "V3 recorded as Spec input 1" becomes "V3 = spec :221-222; V0 added (r4 (a))".
  - **R8 row was false.** It now reads: "r3 claimed 'pruned to gaps v0.3 does not cover'. All six were already in v0.3; the section is deleted in r4 (a)."
  - R2 row: drop "spec input 5 dropped".
- **WP5 RED tests:**
  - `test_verdict_table_rows_v1_to_v5` is renamed `…_v0_to_v5`.
  - New: `test_below_effective_n_floor_is_underpowered_wait_not_no_go`, `test_underpowered_wait_prints_v1_to_v5_as_descriptive`, `test_icc_anova_matches_hand_computation_and_falls_back_to_rho_assumed`, `test_bracketed_unit_takes_smaller_n_eff`.

## (b) Licence: entry criterion E5 (r3 L49-53, L67, L111; PMR F-4/E-2)
- **New E5.** S2's read of `~/.local/share/breezy/derived/nbp/` is licensed only by `RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md`, committed, with:
  - its sha256 in `pins.json` (`pin_inputs`);
  - its **frozen replay date set** filled in **before P2 and before any S2 run**.
- `--census-days` is intersected with that set. The driver refuses any (station, day) outside it, and refuses on a sha mismatch: `test_replay_refuses_day_outside_frozen_set_or_amendment_sha_mismatch`.
- **Without E5** the replay set is 2026-09-18..09-25 only (pre-freeze; NBP read under holdout clause 3 as descriptive). The report states this.
- **The set is enumerated once, after the S1 run (2026-10-14 10:00–15:00Z).** It runs from the first replayable day to the last S1-censused day with CLI FINAL truth.
  - The first replayable day comes from WP0 step 2, the global first print instant. That step reads print timestamps only, which the 10-12 declaration already licenses.
  - The set is never re-chosen after any S2 number exists.
- **r3 L67 "more needs S1's SEARCH declaration"** becomes "SEARCH days 09-26..10-13 enter only through E5".
- **WP0 positive control (r3 L111):** the SFO sample must be dated inside the frozen set. It runs only after E5, which also lists Depth10 and `DepthTruncation` as licensed reads.

## (c) Code-freeze clause (new §5.1; r3 L28, L193, L199-204; PMR F-8, F-15)
- **The verdict run executes from one committed sha.** It is recorded as `code_sha` in `run_manifest.json` and `s3_inputs.json`. The driver asserts a clean tree (`git status --porcelain -- scripts/analysis src tests/unit` is empty), or it refuses.
- **Any code, threshold or constant change after the run starts voids the verdict.** A new verdict needs a new run directory, a new sha, and this plan revised.
- **The verdict run refuses `--stations`, `--days` and `--tail-only`.**
  - Only `--bench` accepts `--stations/--days`. It skips scoring (i).
  - `--tail-only` is a separate report-only unit on the same `code_sha` (r3 L203). It never touches the verdict sidecar's tables except its own `tail_reliability.csv`.
- **Benchmark fill outputs are never inspected for rate.**
- **Tests:** `test_verdict_run_refuses_subset_flags`, `test_verdict_run_refuses_dirty_tree`, `test_tail_only_is_report_only_and_records_code_sha`.

## (d) One schedule source (r3 L124, L217, L254; PMR F-6/F-7, MLE F2)
- **PRIMARY schedule on every day:**
  - nominal `permit_window_for_day` [16:50Z, 02:50Z);
  - `STOP_PRIOR_UTC`;
  - the UTC-midnight GTD cut.
- **The logged-relaunch overlay is a report-only second pass** on days with node logs (`process_schedule_overlay.json`).
  - It never sets the label.
  - Its V-row outcome is printed beside the primary, with the count of days it changed.
  - Reason: per-day schedule mixing would let log retention set the rate.
- **Full-day outage** = no boot line and no permit line inside [16:50Z, 02:50Z) in node log files whose span covers that window. Node logs are Popen stdout files, never journald.
  - Outage days are excluded from numerator **and** denominator alike. They are listed and counted.
  - A day with **no** covering log file is `node_log_absent`. It stays in, on the PRIMARY schedule, and is counted.
  - WP1 pins the boot/permit line patterns as constants, tested against one real log line each.
- **r3 L124 is replaced by the bullets above.** r3 L217 then agrees: "nominal schedule everywhere; logs feed only the overlay and outage exclusion".
- **Node-log pins.** The consumed node-log files (path, size, sha256, byte range) go into `pins.json`. r3 Q1 (L254) is closed.
- **Tests:**
  - `test_logged_relaunch_adds_a_cut` is renamed `…_in_overlay_only`.
  - New: `test_nominal_schedule_is_primary_on_every_day`, `test_full_day_outage_needs_covering_log_without_boot_or_permit_line`, `test_outage_day_leaves_numerator_and_denominator`, `test_absent_node_log_keeps_day_on_primary_schedule`.

## (e) Denominator, direction, MAX_RUNGS=1 (r3 L111, L143, L175, L256; PMR F-5/F-9/F-10, MLE F6)
- **Covered.**
  - Covered = S1 census row `reason == "COVERED"` **and** `covered_bidlive` is true. Both come from the S1 `censused_days.jsonl`, read with `read_censused_days`.
  - S2 does not re-derive coverage.
  - Non-COVERED rows are counted by reason.
  - r3's "≥ 1 depth frame" rate is printed report-only. r3 Q3 (L256) is closed.
- **Bid-bearing** is defined **before** the marketability guard: a covered station-day with ≥ 1 §3 attempt, refused or not.
  - An attempt is a decision instant inside the PRIMARY process-live window where `select_rungs` returns ≥ 1 rung with a bid ≥ B_FLOOR.
  - Days where every attempt was guard-refused stay in the denominator as unfilled. They are counted as `guard_refused_only`.
- **WP0 direction (r3 L111).** Agreement ≤ 0.1 ("inverted") is now an **S-2 STOP** back to the spec. It is never a recorded flip. Test: `test_inverted_agreement_raises_stop_s2`.
- **MAX_RUNGS = 1 subset (r3 L143).**
  - The K1 rung of a station-day is the rung `select_rungs` ranks first (lowest p_YES passing P_MIN, non-modal, non-adjacent). It is taken at the station-day's **first attempt instant** and held for the day.
  - The K1 rates are the station-day fill rates counting only that rung's episodes. They use the same denominator, under base **and** stressed rules.
  - Test `test_max_rungs_1_subset_is_lowest_p_yes` is replaced by `test_k1_rung_is_first_attempt_rung_held_for_day_with_stressed_pass`.
- **More tests:** `test_bid_bearing_counts_guard_refused_attempts`, `test_covered_is_s1_covered_and_covered_bidlive`.

## (f) S3 interface: `s3_inputs.json` (goal r3 L21, L28; PMR F-3/E-3, LOW-13, MLE F8)
- **Goal item 2 (r3 L21).** Beside each rate: the climate-date cluster-bootstrap 95% interval as **primary** (`bootstrap_cluster_draws` / `percentile_interval`, `scoring_core.py:216,246`; seed 20260919 × 2000), with Wilson as sidecar.
  - With fewer than 5 clusters the interval prints "not estimable" and its key is `null`.
- **The sidecar gains `s3_inputs.json`.**
  - Values come from the governing unit hypothesis: the more severe verdict, with ties going to the lower `r_lo`.
  - The rule is stressed (2 × (size ahead + 1)) unless the key says `base`.
  - The unit is the station-day (S3's unit) unless the key says `position`.

| Key | Definition |
|---|---|
| `verdict` | V0–V5 label (`UNDERPOWERED-WAIT`/`NO-GO (…)`/`NOT-KILLED-UNSCREENED`/`NOT-KILLED`) |
| `r_lo` | = `r_lo_station_day` (S3 `f_kill`; S3 r4 delta (h)) |
| `r_lo_station_day`, `r_lo_position` | stressed point, each unit |
| `r_lo_lcb_cluster_boot` | 2.5th percentile of the stressed station-day bootstrap (S3 `f_pass`) |
| `r_lo_se_cluster_boot` | SD of those draws |
| `base_station_day_rate`, `base_station_day_rate_ci_cluster_boot` | base point; [2.5, 97.5] percentiles |
| `r_lo_k1`, `base_k1` | K1 station-day rates (e), stressed and base |
| `two_fill_share` | filled station-days with 2 filled pairs ÷ filled station-days |
| `bid_bearing_share_of_covered_listed` | n_sd ÷ covered station-days (COVERED implies listed) |
| `fill_icc_per_date` | ρ as used by V0 (a); the raw ρ̂ and `icc_fallback` sit in the report |
| `n0_climate_dates` | n0 (a) |
| `realised_bid_median`, `realised_bid_iqr` | over stressed-rule filled episodes; `null` if none |
| `max_rungs_hypothesis` | 2 (the K1 keys carry the k = 1 hypothesis) |
| `k`, `b` | S3 (a) names: `k` = `max_rungs_hypothesis`; `b` = `realised_bid_median` |
| `unit_hypothesis`, `code_sha` | governing hypothesis; the (c) sha |

- **Test:** `test_s3_inputs_json_has_every_named_key`. It also checks that `b` lies in [0.70, 0.80] or is null, and that `r_lo == r_lo_station_day`.

## (g) Reproducibility (r3 L28, L122-125, L197; MLE F3/F4)
- **The sidecar gains `station_days.csv`.** One row per (station, climate_day, unit_hypothesis), with these columns:
  - identity and status: `station`, `climate_day`, `cluster_id`, `unit_hypothesis`, `census_reason`, `covered_bidlive`, `covered`, `outage_excluded`, `node_log_absent`, `bid_bearing`, `guard_refused_only`;
  - attempt and episode counts: `n_attempts`, `n_episodes`, `n_refused`, `n_process_cuts`, `n_gtd_cuts`;
  - hours: `process_live_h`, `forecast_valid_h`, `gap_h`, `covered_live_h`;
  - fills: `filled_pairs_base`, `filled_pairs_stress`, `k1_rung_id`, `k1_filled_base`, `k1_filled_stress`, `bid_median_fills_stress`;
  - clock and scoring: `delta_ns`, `truth_final`, `truth_tmax_f`, `void`, `unresolved_d14`, `theta`.
- **`test_stats_rerun_on_scored_csv_reproduces_tables`** (r3 L197) reads `scored_episodes.csv` + `station_days.csv` + `tail_reliability.csv`. It byte-compares **every** table block in the Markdown, including V0, the S3 block and the tail table.
- **`pin_inputs` (r3 L125) gains:**
  - the clean-tree assertion (c);
  - an installed-package-set sha: sha256 of sorted `importlib.metadata` `name==version` lines;
  - the full CLI argv;
  - the node-log files (d);
  - the truth cross-check parquet;
  - the E5 amendment sha;
  - the θ 0.0695 pin site, named.
- **`load_model` (r3 L123).** It also pins the sha of `docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md`. It parses that file's split block and asserts max `last_climate_day` ≤ 2026-06-30 == `DEFAULT_SPLITS.v5_fit_slice.end` (`nbp_calibration.py:273-278`). If either cannot be read, it refuses.
- **New tests:** `test_load_model_asserts_fit_window_from_evidence_doc`, `test_pins_include_clean_tree_package_set_argv_and_node_logs`.

## (h) Test B relabel (r3 L180-181; PMR F-11, LOW-12)
- r3 L180 "conditional exact rate-ratio test" becomes **"Poisson-conditional rate-ratio test (approximation, valid at p ≤ 0.06)"** everywhere.
- Beside it the report prints, descriptively and never deciding:
  - the stratum-mix-adjusted rate ratio (filled-stratum weights applied to unfilled rates);
  - the climate-date cluster count next to each Test A/B p-value.
- r3 Q2 (L255) is closed.

## (i) WP-time items (frozen now; each lands in its named WP before that WP merges; MLE edits 5–7, F9, F10; PMR LOW-14)
1. **WP2, poll lag.** A report-only stress delays every `available_at_ns` by the live actor's NBP poll interval. Read it from `src/breezy/ingest/nbm_quantile_actor.py` at WP2 time and pin the cite. This is beside the P2 +60 min stress.
2. **WP2, 07Z note.** r3 L221's 07Z note is reworded "moot":
   - a 07Z D−1 cycle (available ≈ 08:10Z) is 8 h-stale by ≈ 16:10Z, before the 16:50Z launch;
   - a 07Z D cycle arrives after the 02:50Z permit end;
   - a late 13Z (max 137 min, valid by 15:17Z) is also pre-launch.
   - The live-side bias runs the other way: replay `available_at` is Last-Modified/floor, the actor sees a cycle only after poll plus fetch, so the replay is optimistic. That is what item 1 measures.
3. **WP0/WP4, clock offset.** Δ is computed per recorder instance-day as max |offset_ns| in that station-day's process-live window. That replaces the global Δ of r3 L113/L152.
   - **New S-7:** any Δ > 10 min is a STOP, never a silent shift. The Δ distribution is reported.
   - Test: `test_delta_is_per_instance_day_and_over_10min_raises_s7`.
4. **WP5, coverage sensitivity (report-only).** Rates restricted to days with `covered_live_h ≥ 0.5 × process_live_h` (threshold fixed here). Also the share of NO-GO-driving days with gap share > 50 %.
5. **WP5, intervals.** The cluster bootstrap prints beside Wilson for both units, labelled "interval is n_eff-adjusted". Fewer than 5 clusters prints "not estimable".
6. **WP5, §6.9 notes.**
   - UNSCREENED-TERMINAL (spec :300-302) is not a Stage 0 object; the report says so.
   - Test A's p is `p_yes_point_live`, the spec §3 point estimate.
   - A replayed day lacking CLI FINAL is excluded from §6.9 for filled and unfilled rows alike and counted. Fill rates are unaffected.
7. **WP2/WP4, truth isolation.** The WP2 verify-first truth check (r3 L135) uses a date-alignment check on one day **outside** the replay set, in a function the simulator cannot import. `test_simulator_module_does_not_import_truth` is extended to it.
8. **WP6, CLI and driver.**
   - New `--bench` mode: timing and RSS only, no scoring, no fill-rate or verdict output (`test_bench_mode_skips_scoring_and_prints_no_rate`).
   - The driver streams `episodes.jsonl` and never accumulates episodes (`test_driver_streams_episodes_without_accumulating`).
   - It refuses an existing `<run_id>` dir (`test_driver_refuses_existing_run_dir`).
9. **Run plan (r3 L201-202).**
   - Benchmark at 4 **and** 8 station-days. RSS is extrapolated linearly from the two; S-5 fires if the projection exceeds 4 GiB.
   - `MemoryMax` = min(2 × peak, 4G) is containment, not a budget.
   - The progress Monitor is re-armed on expiry.
10. **WP3, GTD re-post note.** The 00:00Z GTD cut re-posts at the same instant; live waits for the next event. This is immaterial and stated in the report (PMR LOW-14).

## (j) Stale facts corrected
| r3 anchor | r3 said | r4 says |
|---|---|---|
| L53 E4, L219 | "Today 4.2 GB, so S2 is blocked" | 2026-10-13: 108 GB free; E4 satisfied. It is still checked before P2, every gate, the benchmark and the run |
| L67 | "~8 dates × 4 stations; more needs S1's SEARCH declaration" | pre-freeze 09-18..09-25 (8 dates × 4). The S1 WP0 FINAL declaration (6068a00e) covers 72 SEARCH station-days (09-26..10-13), entering S2 only via E5. Ceiling: 26 dates, 104 station-days |
| L218 | S1 outputs "not delivered" | S1 run 2026-10-14 10:00–15:00Z; E1 then checks the census, the unit and the absence of S-1 |
| L215 | truth "to 10-11" | re-read at run time; the last replay day = last censused day with CLI FINAL (b) |
| L272-278 | R2/R4/R8 rows | as (a) |

## (k) Build-now WP list
- **Build now with fixtures** (none needs S1 output, P2, disk or E5):
  - WP3 and WP4 (pure, synthetic events);
  - WP1: census loader via `read_censused_days`, unit loader, truth, `pin_inputs`, schedule + overlay + outage;
  - WP2: synthetic NBP store built from `DerivedNbpRow` and the `tests/fixtures/nbm/nbptx_t{13,19,01}z_excerpt.txt` fixtures;
  - WP0: synthetic catalog;
  - WP5: fixture CSVs;
  - WP6: end-to-end on a fake catalog + store, incl. `--bench`.
- **Order:** WP3 ∥ WP4 ∥ WP1 ∥ WP2 ∥ WP0 → WP5 → WP6.
- **Shared fixture.** One fixture freezes S1's `censused_days.jsonl` row schema and the unit-verdict set {CONTRACTS, USD_NOTIONAL_YES, USD_NOTIONAL_TAKER}, so an S1 schema change fails S2 loudly.
- **Each WP passes the r3 L102 focused gate.**
- **Run-time steps that wait, in this order:**
  1. S1 run (10-14), then E1.
  2. WP0 step 2: first print instant (already licensed).
  3. Enumerate the date set and commit the amendment (E5).
  4. P1/P2 backfill.
  5. WP2 verify-first (S-6).
  6. WP0 direction check + SFO positive control (needs E5).
  7. Benchmark at 4 + 8 station-days.
  8. Verdict run on a committed sha.
  9. `--tail-only` unit.
  10. Copy the evidence and commit by explicit paths.

## (l) Disposition of review findings
| Finding | Severity | Disposition |
|---|---|---|
| PMR F-1 / MLE F1: no V0 floor; S-4 / Spec input 2 false | HIGH | (a) |
| PMR F-2: Spec inputs 1–6 already in v0.3; R4/R8 rows | HIGH | (a) |
| PMR F-3 / E-3: S3 interface unnamed | HIGH | (f) |
| PMR F-4: forecast-store read unlicensed | HIGH | (b) + amendment ruling |
| PMR F-5a / F-5b: bid-bearing after guard; two covered definitions | MED | (e) |
| PMR F-6 / MLE F2: mixed schedule | MED | (d). The overlay is report-only and never governs, which supersedes MLE's "stricter on V1/V3" |
| PMR F-7: outage contradiction (L124 vs L217) | MED | (d) |
| PMR F-8: no code freeze | MED | (c) |
| PMR F-9: inverted direction flips the rule | MED | (e) S-2 STOP |
| PMR F-10: MAX_RUNGS1 ill-defined; no stressed K1 | MED | (e), (f) `r_lo_k1` |
| PMR F-11: Test B "exact"; mix shift | MED | (h) |
| PMR LOW-12: cluster count beside p-values | LOW | (h) |
| PMR LOW-13 / MLE F8: Wilson on clustered data | LOW | (f), (i)5 |
| PMR LOW-14: GTD re-post at the same instant | LOW | (i)10 |
| PMR LOW-15: subset flags on the verdict run | LOW | (c) |
| PMR §5 forking path 7: stricter unit | — | unchanged r3 L175 (min over unit); the governing hypothesis is fixed in (f) |
| MLE F3: fit window not in the artefact | MED | (g) `load_model` |
| MLE F4: pins / rerun incomplete | MED | (g) |
| MLE F5: poll lag; 07Z moot | MED | (i)1–2 |
| MLE F6: weak covered definition; sensitivity | MED | (e) covered = S1 COVERED ∧ covered_bidlive; (i)4 |
| MLE F7: global Δ | MED | (i)3, S-7 |
| MLE F9: UNSCREENED-TERMINAL; p quantity; late truth | LOW | (i)6 |
| MLE F10: truth in verify-first; bench peeking | LOW | (i)7–8 |
| MLE run plan i–iv: streaming, two sizes, MemoryMax, no overwrite, Monitor re-arm | — | (i)8–9 |
| MLE build-before-run: shared S1 schema fixture | — | (k) |
| r3 §9 Q1/Q2/Q3 | — | closed by (d)/(h)/(e) |

## (m) Planner's unresolved points (for the verification round)
1. The ICC estimator in (a) (one-way ANOVA, fallback ρ = 0.5) is this delta's frozen choice; S1 only has the assumed ρ.
2. `k` = `max_rungs_hypothesis` (2) because S3 defines k as the admitted MAX_RUNGS, which S2 does not produce; `b` is defined on stressed-rule fills to match `f_kill`.
3. S3's `test_binding_mode_refuses_s2_no_go` covers NO-GO only; S3 WP4 must also refuse `UNDERPOWERED-WAIT` (add to the S3 WP4 brief).
4. Whether a descriptive NBP read of 10-02..10-13 counts against the AUT-4 rolling forward holdout (`RULING_holdout_freeze_and_forward_window_2026-10-03.md`) is asserted in the amendment without a cite.
5. Node-log boot/permit line patterns and the live actor's NBP poll interval are pinned at WP time.
