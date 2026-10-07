## Architecture: F13 Phase A feature assembly (`multisource_blend_features_build.py`)

I worked read-only, starting from codegraph. Line anchors are from the current tree.

### Design decisions
- **The builder lives in `scripts/`, not `src/`.** The NBP, truth and MOS readers it needs are under `scripts/analysis/`, and OPEN-1 (plan:550) says `src/` may not import `scripts/`. Every row goes through the existing `assemble_feature_row` (`multisource_blend_features.py:298`). The builder never writes a `FeatureRow` itself, so the leakage checks at `:340` and `:344-368` always run.
- **One anchor per horizon.** `HORIZONS = ("D0","D-1")` (`:26`), and the runner keys rows on `(station, climate_day, horizon)` (`multisource_blend_skill.py:366`). r3 only names D-1 18Z (R35:705, R37:736). r1:70 listed three anchors (D-1 18Z, D 12Z, D 17Z), and those don't fit two horizons. **Gap:** add a prereg pin `anchors_utc`. My recommendation is `{"D-1":"18:00","D0":"17:00"}`, because 17Z falls in the FQ hunt window (hours 10–11 LST). D0 12Z can be built as a separate sensitivity file pair, never mixed into the main pair.
- **The feature file has no header line.** `_load_rows` parses every line as a row (`skill.py:269-274`), so a header line would get the run refused. Provenance goes in a sidecar `<features>.manifest.json`.
- **The +60 min twin shifts LAMP, PFM, MOS and obs, but not NBP or CLI.** For the three model sources this is `extra_lag_ns=LAG_SHIFT_NS` (`:23`, `:312`). Obs is shifted by adding `LAG_SHIFT_NS` to each `ObsReading.available_at_ns` before the call, because `_eligible_obs` has no lag argument (`:263`). Shifting NBP could change or drop the champion row, which breaks the runner's same-keys check (`skill.py:367`). Peer review should test this choice.
- **Availability** = `max(manifest/observed available_at, run_ts + frozen_lag[source])`. The frozen lag is at least the R29 conservative lag (LAMP ≥60 min, GFS MOS ≥5 h) and at least the C1-measured maximum with `late` rows excluded. **Gap:** add a pin `source_lags_ns` covering lamp-mdl, lav-iem, pfm, mos-gfs and obs. The PFM lag and the obs lag are not in the plan.
- **Folds need no row tag.** `build_folds` derives segments from `pins.source_breaks` (`folds.py:87-93`), and the version is the NBP `nbm_version_era`. The manifest reports where each source's basis changes (for example MDL to LAV at 2026-01) so the coordinator can pin `source_breaks`.

### Inputs per source
| Source | Path / reader | Availability rule |
|---|---|---|
| NBP percentiles | `derived/nbp` → `iter_nbp_derived_rows` (`nbp_skill_study.py:463`), `complete_percentile_windows` (`:488`), `_select_d1_window` (`:624`), cycles 13/19/01Z (`:340`) | **Gap:** `NbpPercentileWindow` drops `available_at_ns`. The builder keeps a side index of max(`DerivedNbpRow.available_at_ns`, `nbp_derived_store.py:126`). It uses the latest qualifying cycle whose D+1 target is the climate day and whose availability is before the anchor. |
| LAMP archive | `us_source_archive/us-lamp-mdl` raw `-r0` via `UsSourceRevisionStore` (read-only) → `iter_plain_lines` + `iter_lamp_blocks` (`lamp_parse.py:243`) → `LampRun` | Taken from the `availability_manifest.jsonl` row (`lamp_archive_runs.py:281-310`). Rows with `holdout_sealed` set are skipped. |
| LAV gap-fill | `us-lav-iem` CSV | **Gap: no LAV→`LampRun` reader exists.** `split_lav_runs` (`:234`) only splits. A new `lav_csv_to_lamp_run` is needed. The store is not on disk yet. |
| `us-lamp-live` | — | Every row is ≥2026-10, so all of it is sealed. It feeds C1 lag evidence only, never rows. |
| PFM | `us-pfm-afos` first revision → `parse_pfm_product` (`pfm_parse.py:363`) → `SourceVintage(mu_f=max_by_day[day])` | WMO issuance + the frozen PFM lag |
| GFS MOS | `parse_mos_txn_rows` + `climate_day_for_txn(kind="max")`, following `forecasts_from_mos_payload` (`forecast_conditional_corpus.py:566`) but keeping `runtime_ns` | runtime + ≥5 h. **Gap: no GFS data on disk.** `iem-mos/coverage.json` holds only NBS for 4 stations (no KNYC). Until the GFS backfill runs, M3 collapses to M2. |
| obs_so_far | `iem-asos-1min` via the `observations_from_asos_payload` pattern (`:617`), keeping `(ts, tmpf)` | ts + the obs lag pin. **Gap/risk:** the archive is whole-°F 1-min ASOS, while the live path is METAR. This is the train/serve skew from the earlier lesson (the archive table was calibrated on tenths METAR while live used a coarse feed). Pin `obs_source` and report it. |
| CLI truth | `settlement_truth.parquet` → `read_settlement_truth_rows(climate_day_before=HOLDOUT_START)` (`:551`) + `final_rows_for_gate` | This is the champion's own truth, so the M0 positive control can match. Two problems with the F2 dataset: `fq-truth` starts 2026-01-01 (`iem_cli_fetch.py:157`), and its unit has been **failed since 10-06 12:40Z**. |

### Per-row derivation
- `version` comes from the chosen NBP window's era, `station` is the settlement station, and `std_utc_offset_hours` comes from the registry.
- `lamp_runs` = the latest eligible run under the unshifted rule plus the latest under the shifted rule. That makes the function's own selection (`:220-223`) exact for both files.
- The leakage checks come from existing code:
  - run `available_at` < anchor (`:203`)
  - LAMP `valid_ts` > anchor (`:229`, `:364`)
  - obs `available_at` < anchor, never from LAMP (`:268-270`)
  - `max(available_at) < anchor` (`:344`)
- D-1 rows on archive days get LAMP MISSING (R37). That is expected and gets counted.
- Add a builder-level check: exactly one row per key, and identical key sets across the two files.

### Holdout
1. `--end` ≥ 2026-07-01 is refused.
2. NBP windows targeting the holdout are dropped before the truth join.
3. Truth is filtered as it is read.
4. Manifest rows with `holdout_sealed` set are skipped.
5. `assert_pre_holdout` (`:371`) runs before writing.
6. No `open_holdout` import, enforced by an AST test.

### Memory, CLI and exit codes
- **Memory.** `apply_address_space_cap` with a 4 GiB default. Work is streamed station → year → month: one ASOS station-year at a time, reduced to per-day readings before the anchor. LAMP builds a run index from the manifest and parses on demand with a small LRU. Launch under `systemd-run … MemoryMax`.
- **Flags.** `--prereg --nbp-root --us-source-root --mos-root --asos-root --truth --start --end --stations --out-features --out-lag-features --report-json --max-memory-gib`.
- **Writes.** Refused under `~/.local/share/breezy` (`market_calibration_scan.py:840` pattern) and under any input root. Writes go to temp files, then `os.replace`. Existing outputs are refused (write-once).
- **Report.** Always written. It holds counts per source and horizon (missing, refused, LAMP MISSING by horizon), the input sha256s, the prereg digest, the anchors and the lags.
- **Exit codes.** 0 = complete. 1 = degraded (some payloads unreadable; outputs still written). 2 = refused or leak (nothing written).
- **Output.** `json.dumps(feature_row_to_json(row), sort_keys=True)` per line (`multisource_blend_io.py:21-46`). These are exactly the fields `feature_row_from_json` reads (`:49-65`).

### Files
| File | Change |
|---|---|
| NEW `scripts/analysis/multisource_blend_inputs.py` | Readers: NBP+availability, LAMP MDL, LAV, PFM, GFS MOS, ASOS obs |
| NEW `scripts/analysis/multisource_blend_features_build.py` | CLI, loops, sidecar, report |
| EDIT `F13_prereg_blend_v1.json` | Add pins `anchors_utc`, `source_lags_ns`, `obs_source` (still UNFROZEN) |
| Optional EDIT `multisource_blend_skill.py` | Check that the sidecar's prereg digest matches the prereg |
| NEW `tests/unit/test_multisource_blend_features_build.py` | — |

### RED-first tests (synthetic fixtures)
- `test_output_line_roundtrips_feature_row_from_json_and_has_no_header`
- `test_lag_file_has_identical_keys_and_one_row_per_key`
- `test_lag_shift_moves_lamp_pfm_mos_obs_not_nbp`
- `test_lamp_run_available_at_uses_max_of_manifest_and_frozen_lag`
- `test_holdout_sealed_manifest_rows_never_read`
- `test_end_on_or_after_2026_07_01_refused_exit_2`
- `test_truth_read_filtered_before_holdout`
- `test_open_holdout_never_imported_ast`
- `test_dm1_archive_row_lamp_missing_r37`
- `test_d0_row_lamp_rem_hours_after_anchor_only`
- `test_obs_reading_after_anchor_excluded_and_never_lamp`
- `test_pfm_first_revision_only`
- `test_mos_runtime_plus_5h_conservative`
- `test_lag_below_conservative_refused`
- `test_nbp_window_availability_carried_and_latest_cycle_before_anchor`
- `test_refuses_live_root_and_existing_output`
- `test_report_written_on_refusal`
- `test_leakage_error_writes_nothing`
- `test_station_year_streaming_peak_bounded` (fake 1-min payload)

### Build sequence
1. Prereg pins.
2. Readers, each with RED tests.
3. Builder core and twin.
4. CLI, path guards, report.
5. Optional runner digest check.
6. Gate: `run_tests_no_egress.sh` plus `lint-imports`.

### Blockers before a real run
- No GFS MOS archive.
- No `us-lav-iem` store.
- The 2021–2025 MDL tars are not backfilled (the manifest has 940 runs, all 2026-01/02).
- C1 does not yet have the 14 days of measured lags.
---
## r2 rulings FB-R1..R12 (coordinator, 2026-10-07). BINDING over the r1 design above.

Round-1 reviews: prediction-market-reviewer REQUEST_CHANGES and architect REQUEST_CHANGES. Each fix below is adopted as the reviewer stated it, or reconciled where the two reviewers disagreed.

- **FB-R1, anchors.** D-1 stays at **18:00Z**, bound by R35/R37. The D0 anchor is **10:00 LST per station**, using fixed standard-time offsets and never DST: EST 15Z, CST 16Z, PST 18Z. The sensitivity pair is D0 **12:00 LST**, built as a separate file pair and never mixed into the primary pair. Pin `anchors` as LST hours plus the offset rule.
- **FB-R2, the +60 min twin.** This reconciles the two reviews. Every source lag shifts, **including NBP**, as plan item 8 says ("every source"). The CLI truth is a label and is never shifted.
  - The runner compares the two arms on the **intersection of keys** and reports rows lost per horizon. This is a small, tested change to `multisource_blend_skill.py`, which replaces its same-keys requirement only for the lag arm.
  - The report states that `obs_available_at_ns` is shifted in the lag file.
- **FB-R3, obs (L-13, train/serve skew).** The primary `obs_so_far` emulates the **live observation path**.
  - The builder first cites, via codegraph, the live path's obs source, cadence and quantisation function. It then downsamples the 1-min ASOS archive to that cadence: sample at the station's routine report minute, or the existing `OBS_CADENCE_SECONDS` if that is what live uses. It quantises with the **same function** the live path uses.
  - Pins: `obs_source` and `obs_cadence_seconds`. The 1-min raw running max is a **descriptive arm only**.
  - If the live quantisation cannot be reproduced from the archive, STOP and report. Never proceed silently on 1-min data.
- **FB-R4, lags.** Pin `source_lags_ns` with these **provisional** values:
  - `lamp-mdl`: nominal + max(60 min, C1 max).
  - `lav-iem`: the same + 30 min.
  - `pfm`: WMO issuance + 60 min, or the IEM-entered time if that is later.
  - `mos-gfs`: runtime + 5 h.
  - `obs`: report time + 15 min.
  The final values are frozen only after ≥14 days of C1 measurement (R29). The basis of every value is flagged in the report.
- **FB-R5, NBP.** Add `available_at_ns`, the max over the group, to `NbpPercentileWindow` inside `complete_percentile_windows`. Do not keep a separate index. Verify that every other caller is unaffected.
  - Reuse `_select_d1_window` and `QUALIFYING_CYCLE_HOURS`.
  - The cycle selected for each row must equal the one the champion M0 uses. A test asserts this.
  - Climate days are assigned with `climate_day_for_txn`.
  - The NBP availability basis is nominal and flagged.
- **FB-R6, truth.** The champion's `settlement_truth.parquet` is used for every arm. F2 truth is a concordance diagnostic on the 2026 overlap, with a disagreement count. The `embargo_days` pin must be ≥ 2.
- **FB-R7, GFS MOS.** Reuse `forecast_cycles_from_mos_payload` (`forecast_cheap_screen_wp7.py:926`, adding a `model` parameter if needed) and `resolve_mos_coverage`/`read_mos_windows` (`forecast_conditional_corpus.py:497/555`).
  - `MosCoverageGapError` is reported, not fatal.
  - A GFS/NBS mix is refused, following the `refuse_model_mix` pattern (L-13).
- **FB-R8, leak items.**
  - LAMP availability uses nominal + lag. A manifest `available_at` that is a download time is never used.
  - The MDL→LAV basis break goes into `source_breaks`.
  - PFM uses the first revision, keyed on WMO issuance. COR/CCA never replaces it, and the first stored row is asserted to be the earliest.
  - The 1-min QC revision risk is reported.
  - `valid_ts > anchor` and the LST climate-day window are both tested.
- **FB-R9, files.** `scripts/analysis/multisource_blend_inputs_lamp.py` (LAMP + LAV, including the new `lav_csv_to_lamp_run`), `…_inputs_forecast.py` (NBP, PFM, MOS), `…_inputs_obs.py`, and `multisource_blend_features_build.py`. Each must be under 800 lines.
- **FB-R10, sidecar.**
  - `<features>.manifest.json` records the prereg digest, the **sha256 of each feature file**, the anchors, the lags, the cadence and the source breaks observed.
  - The runner check is **required** when a sidecar is present. A sha or digest mismatch refuses the run.
  - The feature files themselves stay header-free.
- **FB-R11, tests.** Add these to the r1 list:
  - L-42: fixtures go through the production writers.
  - L-55: one `main()` run with the default readers against tmp stores.
  - End to end: the builder output loads through `_load_rows`.
  - A sidecar mismatch is refused.
  - L-13 cadence downsample.
  - MOS model-mix refusal, and a coverage gap that is reported, not fatal.
  - A degraded run exits 1 with its outputs written.
  - LAV RED against a real CSV sample.
  - Champion-cycle equality.
  - Lag-arm key intersection and rows-lost report.
  - `lint-imports` in the focused gate.
- **FB-R12, run blockers.** These are recorded here, and the code may be built now:
  - GFS MOS backfill, including KNYC (`us_source_backfill --legs gfs`).
  - The `us-lav-iem` store.
  - The 2021–2025 MDL yearly tars.
  - ≥14 days of C1 lags.

**STATUS: READY to build (2026-10-07).**

### Build rulings FB-R13..R14 (coordinator, 2026-10-07, after the builder's FB-R3 finding)
- **FB-R13 (supersedes the FB-R3 cadence).** The live path mixes METAR-exact rows with NWS integer-°C interval rows, at a 5-min cadence. The interval rows cannot be reproduced from the whole-°F 1-min archive. The feature is therefore **defined on routine METAR readings only, for training and for any future serving**:
  - `obs_so_far` is the running max of the station's **routine hourly METAR** values. Each value is taken from the 1-min archive at the station's routine report minute, which is derived per station from the archive and pinned.
  - Values are quantised with `round_half_up_f` through the METAR T-group path (identity on whole °F).
  - `available_at` is the report time plus the obs lag.
  - Pins: `obs_cadence_seconds = 3600` and `obs_routine_minute_by_station`.
  - Interval rows and specials are excluded on both sides. **Phase C/D requirement:** any live consumer of this blend computes `obs_so_far` the same way, from routine METARs only, never through `RunningExtremeAccumulator`'s interval rows.
  - The 1-min raw running max and the 5-min whole-°F max remain descriptive arms.
- **FB-R14 (tightens FB-R10).** For a real scoring run the runner **requires** the sidecar, and refuses without one, so the features are always bound to the prereg. Runner tests provide sidecars through a fixture helper. Only a `--allow-no-sidecar` flag that is test-only, or the absence of any real data, may bypass it. Prefer no bypass.
