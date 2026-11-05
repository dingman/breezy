# F13 FQ-SRC-INGEST, plan r1

[DESIGN] New US weather source ingest, offline skill, timing study, collector, `density_table_multisource`

Status: PLAN r1, for the mandatory peer loop (FQ-R28). Nothing is built. Everything here is build-time design.

## 0. Verdict up front (honest feasibility, summary)

- **A static blend of public US products is not expected to beat the market.**
  - The survey's reported blend (about 2.25 against the market's 2.44 at the evening point) is unverified. It also used ECMWF, which we cannot use.
  - Without ECMWF the plausible result is "about market-level on RMSE". The venue's fee (θ=0.0695) and take margin (0.02+) then make a pure blend negative-EV at the ask.
  - Phase A's realistic value is a better fair-value and veto signal. It is not a standalone edge.
- **The timing hypothesis (the market lags new releases) is the only path with a plausible positive edge.** It is also the cheaper one to test.
  - Phase B1 is model-free and offline, and needs no new source archive except PFM issue times.
  - Build B0/B1 first. Start the C1 collector the same week, because forward data cannot be backfilled.
- **The KILL date is 2027-01-25, about 111 days away.**
  - Scaling M1's MDE (19.8¢ at 26 days, `docs/evidence/M1_MARKET_SCAN_2026-10-04.md`) by √(26/111) gives about 9–10¢.
  - A realistic 3–8¢ edge against the market therefore cannot be confirmed by KILL.
  - What can be settled by KILL:
    - whether the blend beats NBP on CLI (Phase A);
    - whether the market visibly moves after releases (B1);
    - whether the post-release move is exploitable at our latency (B2, directional only).
  - A CHAMPION `density_table_multisource` is not deployable before KILL (AUT-S plan r2 line 172, E-26 rule 4).

## 1. Context: what exists (verified)

| Item | Where | Use |
|---|---|---|
| IEM MOS transport | `scripts/venue/iem_mos_probe_transport.py:50-60`. Hosts closed to `mesonet.agron.iastate.edu`, 1 s min interval, 32 MiB body cap, stations KLAX/KMDW/KMIA/KSFO (no KNYC), models NBS/GFS only. | Reuse. Add KNYC and the LAV/AFOS endpoints. |
| Archive cache | `src/breezy/persistence/archive_cache.py:335` `ArchiveCache`. Hit/miss, sha256 manifest, flock single writer, disjointness from the backed-up archive (`:309`). Payload is `*.csv` (`:393`). Entries carry `fetched_at_ns`, no `available_at` (`:516`). | Reuse unchanged. Normalise every source to CSV with an explicit `available_at` column before caching. |
| MOS backfill | `scripts/archive/iem_mos_backfill.py` (plan builders, `validate_payload`, closed-day guard keyed to the 18Z NBS run). | GFS MOS ingest already supported. Not on disk (Phase 0 §0.3). |
| Hardened S3-then-NOMADS GET-only client | `src/breezy/ingest/nbm_quantile_transport.py:248-441`. Fixed allowlist (`:278`), https-only, port 443, no redirects, `trust_env=False`, streaming station filter plus sha256 in one pass (`:439`). | Copy the shape for MDL, AFOS and HRRR. |
| Live actor pattern | `src/breezy/ingest/nbm_quantile_actor.py:171-337`. Config, timer, `run_coroutine_threadsafe` bridge. Vintage is measured: `available_at_ns = cycle_runtime_ns + lag_ns` (`:237`). Lag comes from `Last-Modified` (`:487-497`), and it publishes nothing rather than assume a vintage. | The collector must meet the same "measured, never assumed" rule. |
| Node wiring | `src/breezy/app/trade.py:44,720` (row 7 owns this file). | Only Phase C2 and D touch it. |
| Calibration machinery | `src/breezy/analysis/nbp_calibration.py`: `crps_normal` `:510`, `fit_hierarchical_emos` `:1166`, `fit_calibration` `:1280`, `open_holdout` `:353` (single-look marker). | The blend is a pure extension of this. |
| Launch window | `src/breezy/persistence/autonomy/capture_schedule.py:3`: [16:30Z, 17:10Z). | Collector and backfills stay outside it. |
| C3 invariants | `src/breezy/persistence/autonomy/lineage.py:73-74` (`no_sealed_holdout_rows_in_train`, `ref_ts_lt_take_ts`). | Phase D reuses them. |

Recorded facts that bind the design:
- E-26 rule 4: US sources only. `data_windows` has one entry per source with `content_sha256`.
- E-26 rule 2: `c3_writer` is the single writer.
- E-26 fail-closed: until E-26 is consumed, `c3_writer` refuses the class.
- AUT-S Phase 0: G2 is empty today. Only NBS is on disk, and it is NBM-family with no per-row `available_at`.
- M1: no cell survives; MDE is far above a realistic edge.
- FQ triage: the model's Brier on its taken trades was 0.075 against 0.048 for the market ask. The model was overconfident (NBM spread about 2 °F, realised misses 3–8 °F).

Not verified: the survey's arXiv figures, LAMP/AFOS/MDL URLs and timings, and the PFM point-to-station mapping. Each is a Phase A0 probe item.

## 2. Cross-cutting design

### 2.1 Data contract (all sources)

Normalised CSV row: `source, source_version, station_icao, run_ts_utc, valid_ts_utc, variable, value, unit, available_at_utc, available_at_basis, raw_sha256`.

`available_at_basis` ∈ {`measured_header`, `wmo_header`, `nominal_plus_conservative_lag`}.

`src/breezy/ingest/us_source_availability.py` is one pure function table, `available_at(source, version, run_ts, observed_header) -> (ts, basis)`:
- **PFM:** the WMO header time (exact).
- **LAMP:** run time plus a conservative pre-registered lag, 60 min.
  - The survey says about HH:30; the margin is a coordinator default.
  - Live collection replaces it with measured values.
- **GFS MOS:** run time plus 4 h 30 min (survey: 00Z ready about 04:15Z).
  - 18Z is unverified. Use a lag of at least 5 h, then tighten from measured live data.
- **HRRR (A2):** run time plus a conservative lag, a probe item.

Backtest `available_at` is never earlier than the measured live value. The conservative rule can only throw away usable data, never leak.

### 2.2 Anchors and scope (leakage control)

- Decision anchors are the M1 windows: D-1 18Z, D 12Z, D 17Z.
- Every feature is `source rows where available_at < anchor_instant`, scoped by climate date AND hour (the implausible-result-is-a-leak rule).
- An assertion runs on every scored row: `max(available_at) < anchor` and `valid_ts` within the climate-day window.
- **LAMP horizon (flagged by the survey):** a 25 h run at D-1 18Z does not reach the D afternoon peak.
  - A feature is "available" only when the covered hours include the full climate-day peak window.
  - Otherwise it is a missing-indicator. Weights are fit per anchor, never imputed.

### 2.3 Truth

Use CLI truth via the existing alignment (`scripts/analysis/forecast_txn_climate_day_cli_alignment.py`, `forecast_climate_day_map.py`). Do not re-derive it. Official CLI truth ends 09-28 in some sets (triage), so pre-07-01 is unaffected.

## 3. Holdout handling: recommendation

**Adopt a hybrid of options 3 and 2. Never use option 1 (a one-shot holdout open).**

1. **Phase A uses only days < 2026-07-01, scored against CLI.** The market is never an input. This is RMSE/CRPS/Brier versus CLI, out-of-fold, version-aware.
2. **Any blend-versus-market comparison is forward-only shadow.**
   - It starts after a committed freeze (the sha-pinned prereg plus fitted weights).
   - Only days strictly after the freeze count as evidence (the same rule as E-26 rule 7 and FQ-R14).
3. **Phase B1 (timing) is model-free.**
   - It uses only release timestamps and venue quotes. It reads no model output value, so it does not touch the sealed model-output holdout.
   - Tape days 08-30 onward are fine for it.
   - The result is pre-registered and read once. Flag it as a coordinator ruling for the peer loop to confirm.
4. **Phase B2 (sign-aware) is forward-only.**
   - Sign-aware means "does the market move toward the new forecast". It needs forecast values and so cannot touch sealed days.
   - It uses only collector data after the freeze.
5. **Reason for not using option 1:** `open_holdout` is a single look (`nbp_calibration.py:353`). It is also a v5.0 NBP marker. A blend that first sees days ≥ 07-01 on a market comparison with MDE above 19 ¢ would spend the only look on a test that cannot answer the question.
6. **Consequence of the 07-01 to 08-29 gap.** No tape exists there. All tape days that touch the market are ≥ 07-01, so no Phase A fold ever overlaps the market.

## 4. Phase A: archives and offline skill

### 4.1 Scope
- **A0 (probe, read-only):** confirm every URL, tar layout, member mtimes, PFM point names, and the rate limit, on one day per source. It writes a feasibility record, not data.
- **A1 (archives):** LAMP, PFM and GFS MOS, five stations (NYC KNYC, MDW, MIA, LAX, SFO), runs on days < 2026-07-01 for the blend. Archives are also kept past 07-01 for the forward feed, but are never scored in Phase A.
- **A2 (optional):** HRRR. It is cut first if time is short, because the 2 m TMP field is about 35 MB per run (survey).

### 4.2 Sources
- **LAMP:**
  - Source: MDL tars 2006–2025 (about 3.8 GB per year, so about 76 GB over 20 years of download).
  - Download is streamed through `tarfile` in stream mode, filtered to the five stations. Raw tars are never retained, only the filtered CSV and the raw-tar sha256 (as `nbm_quantile_transport.py:439` does).
  - A 2026 gap exists in MDL. Fill it with IEM LAV (00/06/12/18Z only, from 2020-07), then with the live collector (C1).
  - The runs differ in freshness between the two paths. Flag the basis per row.
- **PFM:** IEM AFOS `retrieve.py?pil=PFM{OKX,LOT,MFL,LOX,MTR}`. About 2000 onward, a few KB per issue. Use 2021 onward, because the survey's exact-issue-time claim is only stated back to 2021.
- **GFS MOS:** the existing backfill. Add KNYC. Add MEX only if A0 shows it helps D+1 anchors.
- **NAM MOS:** excluded from the blend (retires 2026-11-03). Optionally backtest-only as an ablation.

### 4.3 Pre-registered blend (one form, K small)
- **Target:** the climate-day maximum temperature (CLI). Rung probabilities derive from the predictive CDF at the venue rung boundaries (reuse the FQ rung mapping; implementer must verify the mapping module).
- **Form:** per-anchor, hierarchical (stations pooled, per-station intercept) normal EMOS.
  - μ = a_s + w₀·NBP_μ + Σ wₖ·xₖ, with xₖ ∈ {LAMP_max, PFM_max, GFS-MOS_max}.
  - w ≥ 0, Σw = 1 is not forced. The weight sum is constrained to [0.8, 1.2] to prevent bias absorption.
  - σ = exp(c + d·log NBP_spread), floored (the FQ overconfidence lesson).
  - CRPS-minimisation through the existing `fit_hierarchical_emos` and `crps_normal` path (`nbp_calibration.py:510,1166`).
  - Extend it to k features; do not reimplement.
- **Nested ladder:**
  - M0 = NBP-only EMOS (the baseline, refit by the identical procedure per AS-R4).
  - M1 = M0 + LAMP.
  - M2 = M1 + PFM.
  - M3 = M2 + GFS MOS (the full blend).
- **Primary hypothesis:** M3 versus M0 (K = 1).
- **Secondary:** the marginal contributions, descriptive only, with no mint.
- **Not in v1:** a quantile blend. It is a later grammar version (the K ledger of AS-R2 applies).
- The prereg JSON (form, anchors, lags, folds, thresholds, seeds) is committed and its sha256 recorded before any scoring.

### 4.4 Folds
- **Version-aware, blocked within each NBM version** (AS-R1). Versions are v4.0, v4.1, v4.2, v4.3 and v5.0 per the NBP era table.
  - A version enters only if it has ≥ 2 blocks of ≥ 28 held and ≥ 28 training climate days.
  - v5.0 has at most 57 days, so it is borderline, and v5 never mints (AS-R14).
- LAMP v2.7 and GFS MOS/GFS-model upgrades are additional break dates (SCN25-62). Fold boundaries must not straddle a break. Pre-register the break list from A0.
- Positive control: M0 refit reproduces the committed champion sha (AS-R4, Phase 0 step 0.2). Negative control: shuffled labels give Δ ≈ 0.

### 4.5 Metrics and acceptance
- **Primary:** mean CRPS on rung probabilities (the E-25 unit is the climate day), Δ = CRPS(M0) − CRPS(M3).
- **Co-primary:** Brier on rung probabilities, and daily-max RMSE.
- **CI:** stationary bootstrap, mean block 7 days (the AS-R pinned function), resampling by climate day across stations.
- **ACCEPT only if all of:**
  1. Δ CRPS ≥ 3 % relative improvement, with the lower 95 % CI bound > 0.
  2. Daily-max RMSE improves by ≥ 4 % with CI lower bound > 0. (The 3–4 % figures are coordinator defaults, chosen against the survey's reported 9–10 % with ECMWF; the peer loop may tighten them. They must be frozen in the prereg before scoring.)
  3. The sign is the same in every fold block (AS-R4).
  4. No Δ above the fold spread (that becomes `HELD_LEAK_AUDIT`).
  5. No station degraded beyond a pre-registered tolerance.
- **Otherwise STOP.** Record NO_SKILL, stop Phases D and the A2 HRRR leg, and keep B and C1 running as the timing-hypothesis path.
- **A pass says the blend beats NBP, not the market.** It is a necessary condition for any further build, not sufficient.

### 4.6 Files

| Status | File |
|---|---|
| NEW | `src/breezy/ingest/us_source_availability.py` |
| NEW | `src/breezy/ingest/lamp_parse.py`, `src/breezy/ingest/pfm_parse.py` |
| NEW | `src/breezy/ingest/mdl_lamp_transport.py` (MDL host allowlist, GET-only, streaming tar, mirror of `nbm_quantile_transport.py`) |
| NEW | `src/breezy/ingest/afos_pfm_transport.py` (or an IEM extension, if A0 shows the same host policy fits) |
| NEW | `scripts/archive/lamp_mdl_backfill.py`, `scripts/archive/pfm_afos_backfill.py` |
| NEW | `src/breezy/analysis/multisource_blend.py` (pure fit/predict) |
| NEW | `scripts/analysis/multisource_blend_skill.py` (offline runner, memory-capped) |
| NEW | `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13_prereg_blend_v1.json` |
| EXISTING | `scripts/venue/iem_mos_probe_transport.py` (`:58` add KNYC; `:60` add LAV; keep the closed sets) |
| EXISTING | `src/breezy/persistence/archive_cache.py` (`:59` product map: `mos-lav`, `pfm`; nothing else) |
| EXISTING | `scripts/archive/iem_mos_backfill.py` (plan builders for KNYC, GFS; the closed-day guard assumes the 18Z NBS run and must not apply to LAV/PFM) |

### 4.7 RED-first tests (named)
- `test_available_at_never_precedes_run_ts_for_any_source`
- `test_conservative_lag_not_earlier_than_measured_live_lag` (fixture from A0)
- `test_feature_rows_all_available_before_anchor` (scored-row assertion)
- `test_lamp_peak_window_not_covered_is_missing_not_imputed`
- `test_pfm_parse_selects_station_point_and_max_row`
- `test_pfm_wmo_header_time_is_available_at`
- `test_lamp_daily_max_uses_climate_day_lst_window`
- `test_mdl_transport_refuses_non_allowlisted_host_redirect_and_post`
- `test_mdl_tar_stream_filters_stations_without_buffering_whole_tar` (memory bound)
- `test_normalised_csv_roundtrips_through_archive_cache_with_digest`
- `test_blend_m0_equals_champion_refit_within_1e_12`
- `test_blend_weights_sum_constraint_and_nonnegativity`
- `test_blend_sigma_floor_prevents_overconfidence`
- `test_folds_blocked_within_version_and_never_straddle_source_break`
- `test_negative_control_shuffled_labels_gives_zero_delta`
- `test_no_row_on_or_after_2026_07_01_reaches_the_fit_or_score`
- `test_prereg_sha_is_recorded_before_scoring_and_run_refuses_if_changed`
- `test_acceptance_stops_when_ci_lower_bound_not_positive`

### 4.8 Gates and dependencies
- **Gates:**
  - `scripts/ci/run_tests_no_egress.sh` (full gate after every merge).
  - `lint-imports` console script from the repo CWD, with a "N kept, 0 broken" line.
  - Adapters must not import `breezy.runtime`.
  - The exec import pin x1 (set-equality) must not be affected. Put the firewall guards in every focused gate.
- **Egress for A0/A1 fetches:** the new transports are GET-only and host-allowlisted. They are not in the order-egress path. They need the same NO-SEND test as the NBP transport. Confirm the NO-SEND guard's scope with the firewall owner. Do not touch the firewall.
- **Live path:** none (offline). Unit: `systemd-run --user` with a memory cap, a runtime limit and `LimitNOFILE=524288`. Basetemp on `~/.cache`. A stall watch with a no-progress event and a subset benchmark first. Run outside 16:30–17:10Z. One heavy job at a time.
- **Dependencies:**
  - F1 (errata filing) for E-26 numbering.
  - F2 (the IEM CLI fetch and dataset units) is the truth path. Phase A can use the existing alignment sets for pre-07-01 truth, so F2 is not blocking. Re-verify against F2 when it lands.
  - F5 (PREREG v2) supplies the e-process/freeze conventions and the K-ledger. A's prereg JSON mirrors them, but A does not wait on F5.
  - F4 and F7b feed the forward evidence unit (Phase D), not A.
  - AUT-3 is needed only in D. Row 7 only in C2/D.

## 5. Phase B: timing study

### 5.1 Question
After a release time, do quoted prices move, and by how much, how fast?

### 5.2 B0 (go/no-go, offline, days)
- Tape inventory: cadence and coverage of Depth10 snapshots per station-window since 08-30. QuoteTicks cannot show an empty bid; use Depth10 (memory).
- Census of release timestamps:
  - PFM from IEM AFOS (exact, retrievable retroactively).
  - NBM/NBS from IEM nominal run times. If the live NBP actor's measured vintage rows are in the catalog for 08-30 onward, use them (verify; not confirmed here).
  - LAMP only nominal until C1 has data.
- **MDE calculation first (the M1 lesson).** If the MDE for B1's primary statistic exceeds the plausible effect, record UNDERPOWERED and rely on forward accrual.

### 5.3 B1 (model-free event study)
- **Unit:** (station, climate day, release event).
- **Outcome:** the absolute change in the ladder-implied expected daily max (a ladder-wide statistic, to reduce per-rung noise), measured over [t, t+15 min] and [t, t+60 min], from the executable Depth10 ask/bid mid where both sides exist. Rungs with an empty bid are excluded and counted.
- **Control:** placebo times matched on station, local hour and day type, but not on release events.
- **Test:** event minus matched-placebo mean, with a day-block bootstrap (blocks of climate days across stations).
- **Multiplicity:** primary family = {NBM, LAMP, PFM} × {15 min, 60 min} = 6 tests, Holm-corrected. Everything else is descriptive.
- **Holdout treatment:** it uses no model values, so it is allowed on tape days. One pre-registered single read.
- **Interpretation limit:** a significant move says the market reacts to something around release times. It does not say there is a tradable lag.

### 5.4 B2 (exploitability, forward-only)
- After the C1 freeze, the collector gives the new forecast and the old forecast per source.
- **Statistic:** the signed "post-release drift toward the forecast change", measured from the executable ask at t_release + our measured latency.
  - The ask is taken at the actual fill price (edge must clear θ·p(1−p), the 0.01 slippage floor, and `margin(h)`).
  - It uses no mid.
- The measured latency is the real fetch-to-decision gap. In the LAX case the NBM cycle was published 44 s before the take.
- **Pre-register:** a single primary (the most-powered source from B1), one look at a pre-registered n, with the e-process conventions from E-25 (F5/F7b).
- **Decision-relevant:** the median adjustment time of the market is compared against our latency. If the market adjusts in under about 60 s, B2 stops.

### 5.5 Files and tests
- NEW `scripts/analysis/release_timing_event_study.py` (read-only, memory-capped); NEW `src/breezy/analysis/release_timing.py` (pure statistics); NEW the B0 census script.
- EXISTING reads: the tape catalog readers and the existing market-scan statistics helpers (`scripts/analysis/market_calibration_scan.py` on its branch; verify what is merged).
- **Tests:**
  - `test_event_study_uses_no_model_values`
  - `test_placebo_matched_on_station_hour_and_excludes_release_windows`
  - `test_empty_bid_rungs_excluded_and_counted`
  - `test_holm_over_exactly_six_primary_tests`
  - `test_event_windows_never_cross_16_30_17_10z_launch_gap_without_flag`
  - `test_release_timestamp_provenance_recorded_per_event`
  - `test_ref_ts_lt_decision_ts_for_every_b2_row`
  - `test_b2_refuses_days_before_freeze`
  - `test_mde_reported_before_any_effect_estimate`
- **Live path:** offline. B2 uses C1 output only.
- **Dependencies:** none of F2/F4/F5/F7b for B1. B2's e-process conventions mirror F5/F7b. If F7b is not merged, B2 reports a descriptive fixed-n result only (no verdict).

## 6. Phase C: live collector

**Recommendation: two stages.**
- **C1: a scheduled run-to-completion ingest unit, outside the node.** Start first.
- **C2: a Nautilus `DataActor` in the node.** Built only if Phase D is reached. E-26 rule 4 requires it for CHAMPION.

### 6.1 C1 (the early-evidence collector)
- **Form:**
  - A systemd user timer, oneshot per cycle, run-to-completion, per source.
  - Idempotent: keyed on `(source, run_ts)` through `ArchiveCache`'s flock single writer.
  - A crash and re-run never duplicates a payload.
- **Per cycle:** fetch, validate shape/range/units (trust boundary), normalise, record the raw sha256, and record `available_at` as observed (`Last-Modified` or the WMO header, never assumed). Where only the fetch time is observable, `available_at` is the first-seen time with basis `first_seen`. That is a later bound, safe for leakage.
- **Cadence:** LAMP hourly at about HH:35 (verify). PFM polled for new issues around 3:30–4:20 PM local and about 4 AM local. GFS MOS at 04:20/10:20/16:20/22:20Z (16:20Z is inside the 16:30 stop window's neighbourhood and ends before 16:30). Skip any firing that would run inside 16:30–17:10Z, and run it at 17:10 instead, flagged late.
- **Caps:** MemoryMax and RuntimeMaxSec are set on the unit (engineering caps, not operator caps). A no-progress watch. Stall alert through the existing alerts path.
- **Egress:** GET-only, allowlisted hosts: the MDL host, `mesonet.agron.iastate.edu`, and later AWS/NOMADS for LAMP/HRRR. HTTPS only, no redirects, no proxy env. User-Agent with a contact. Honour 429 `Retry-After`; keep the IEM min interval of 1 s (`iem_mos_probe_transport.py:53`).
- **Output:** the same normalised CSV archive plus a catalog-compatible record. C1 writes a separate domain (single-writer discipline), and the node never reads it.
- **Why C1 first:**
  - No node respawn and no row 7 dependency.
  - The time-sensitive part (forward data accrual, LAMP's missing 2026 data) starts now.
  - It can be accepted offline.

### 6.2 C2 (DataActor, node-resident)
- A `UsSourceIngestActor` modelled on `NbmQuantileActor` (`nbm_quantile_actor.py:171-337`): a frozen `ActorConfig`, a timer with the native `start_time=` stagger, and `run_coroutine_threadsafe` supervision.
- A custom Nautilus `DataType` publishes `ForecastPoint`-like records with `available_at_ns` (the `nbm_forecast_point_data_type` pattern, `nbm_forecast_data_type.py:30`).
- It is composed in `src/breezy/app/trade.py` next to the existing NBM actor (`:720`). That file is owned by row 7, so C2 must wait for it.
- **Live path:** yes, a node respawn. Activation only at the 16:50Z LAUNCH. Never a mid-day hand relaunch (AMBIGUOUS-intent and permit risk). Do not touch the permit or submit path.

### 6.3 Tests
- C1:
  - `test_cycle_is_idempotent_after_midwrite_kill`
  - `test_rerun_never_duplicates_payload_or_manifest_entry`
  - `test_available_at_is_observed_header_never_assumed`
  - `test_first_seen_basis_is_flagged`
  - `test_collector_skips_launch_window_and_runs_late_flagged`
  - `test_stale_source_alerts_after_deadline`
  - `test_transport_is_get_only_and_allowlisted`
  - `test_oversize_body_refused_by_cap`
  - `test_memory_bounded_on_large_tar` (streaming)
  - `test_rate_limit_429_backoff_respects_retry_after`
- C2:
  - `test_actor_publishes_nothing_when_vintage_unmeasurable` (mirror of the NBM test)
  - `test_actor_composition_does_not_alter_champion_decisions` (bit-identical replay)
  - `test_actor_cannot_reach_execution_or_permit_paths` (import and firewall guards)
- **Acceptance (C1):** 14 consecutive days with ≥ 95 % of expected cycles captured, zero duplicate payloads, and every row with an observed `available_at`.
- **Dependencies:** C1 has none beyond the transport tests. C2 needs row 7, F1 (E-26 filed) and AUT-3 (for D).

## 7. Phase D: `density_table_multisource`

Gate: Phase A ACCEPT, plus forward B2/shadow evidence that the blend adds value against the ask.

| Step | Mapping |
|---|---|
| Class | E-26 rule 1: `forecast_quantile_ladder:density_table_multisource`. `MODEL_CLASS_COMPONENTS` is append-only (`pins.py:96`, owned by ARCH-0). |
| Inputs | E-26 rule 4: US sources only. `data_windows` has one entry per source with `content_sha256`. Never prices or execution data (`test_multisource_consumes_no_execution_data`). |
| Writer | E-26 rule 2: only AUT-3 `c3_writer.write_candidate`. Fresh `derived/artefacts/<model_class>/<sha>/`, `lineage/v1`, `refit_run/v1`. |
| Invariants | `ref_ts_lt_take_ts` and `no_sealed_holdout_rows_in_train` (`lineage.py:73-74`). |
| Mint slot | E-26 rule 3: ≤ 1 MINT per lineage per day across all four classes. |
| Evaluation | E-25 e-process, e-LOND. Forward shadow only on days after the freeze. Scan and screen days never count. |
| Loader | G11-style live-loader acceptance with parity tests (E-26 rule 4). The model: AUT-3.WP2's parity ≤ 1e-12 per rung, 200 seeded draws. Needs a new loader that reads multi-source feature rows with `available_at`, and a refusal for any source missing at decision time. |
| Fail-closed | Until E-26 is consumed, `c3_writer` refuses and the replay probe refuses. |

- **Train/serve skew (the archive-table lesson, memory):** the live loader must apply the same availability and missing-data rules as the archive fit. Parity tests run archive rows through the live loader and compare.
- **Missing source at decision time:** the live path degrades to M0 (champion), never to a partial blend. This is pre-registered.
- **Files:**
  - NEW `src/breezy/strategy/ladder_ev/multisource_density.py` (loader);
  - EXISTING `fq/calibration_artefact.py`, `fq/artefact_bounds.py`, `fq/composition.py`, `pins.py` (by their owners);
  - the AUT-3 `c3_writer` call (from AUT-3 r7);
  - the C2 actor.
- **Tests:**
  - `test_multisource_loader_matches_archive_fit_to_1e_12`
  - `test_missing_source_degrades_to_champion_not_partial_blend`
  - `test_multisource_loader_refuses_unavailable_source_rows`
  - E-26's list, including `test_model_class_components_append_only_four` and `test_c3_writer_only_writer_of_new_classes`.
- **Dependencies:** F1 (E-26 filed); F4 and F7b (the evaluator and e-process); F5 (PREREG amendment); AUT-3 (writer); row 7 (node wiring); the F12 PROMOTE enable for the CHAMPION step.
- **Live path:** C2 plus the loader is a respawn at the next 16:50Z LAUNCH. It is not reachable before KILL.

## 8. Risk register

| Risk | Containment |
|---|---|
| **Leakage** (`available_at` ≥ decision instant) | The conservative-lag table. Scored-row assertion `max(available_at) < anchor`. Scope by date AND hour. Positive and negative controls. A Δ larger than the fold spread triggers `HELD_LEAK_AUDIT` and is not celebrated. |
| LAMP 2026 gap (MDL tars end at 2025) | IEM LAV (4 runs, from 2020-07) stopgap. C1 live collection. Basis flagged per row. The blend is scored only on < 07-01, so the 2026 gap affects only forward use. |
| LAMP horizon too short for D-1 anchors | Missing-indicator, not imputation. |
| NAM MOS retires 2026-11-03 | Excluded from the blend and the live design. Backtest ablation only. |
| Version breaks (NBM v5.0 straddle, IEM NBS/NBE cycle change from 2026-05-05, LAMP v2.7, GFS upgrades) | Fold boundaries respect a pre-registered break list. v5 never mints (AS-R14). |
| Storage | Raw tars are streamed and not retained. Filtered CSV is small. 235 GB free today (74 % used). Disk guard in the backfill. |
| IEM rate limits / bans | 1 s minimum interval, a conservative request budget, resumable through the manifest, a User-Agent contact. |
| PFM point-to-station mismatch (KNYC `NYZ072` and the others) | A0 probe; a station-map test. Refuse unmapped points. |
| Memory pressure (tars, 10–24 GB nightly studies) | The streaming parser, a unit memory cap as containment, one heavy job at a time, and a stall watch. Never SIGKILL the node. |
| Multiple comparisons | K small. The K ledger (AS-R2). Holm over 6 tests. Descriptive extras are labelled as such. |
| Sealed holdout contamination | §3. Test `no_row_on_or_after_2026_07_01...`. `open_holdout` is never called. |
| Survey figures are unverified (arXiv 2609.23969) | Re-check the paper before any threshold is justified from it. The acceptance thresholds are frozen from our own prereg, not from the paper. |
| Overfit to NBP's quirks / small n | Nested ladder, the sum-of-weights constraint, shrinkage and the sigma floor. |
| Operator-reserved controls | The plan names and assigns none. No live enablement, permit or firewall change anywhere. |

## 9. Honest feasibility

- **Expected edge from the blend:** about zero against the market.
  - The reported public-blend result is about market-level, with ECMWF included.
  - Minus ECMWF it is likely below the market.
  - Fee at the ask is up to about 1.7¢ at p = 0.5.
  - Add the 0.01 slippage floor and the `margin(h)` of at least 0.02.
  - FQ v1 lost because it picked the largest model/market disagreements, which are mostly the model's errors.
  - A better blend narrows that error, so it reduces losses, but it does not itself create a winner.
- **Timing path:**
  - It is the more promising path for a positive edge, because it exploits the market's information-processing speed, not forecast skill.
  - Its risks are large: thin PM.us books, the sparse bid side, our own latency (tens of seconds), and the possibility that the market is already faster than us.
  - It is cheap to falsify: B1 is offline, on existing tape.
- **Achievable by KILL (2027-01-25):**
  - Phase A: ACCEPT or STOP on CLI. Yes.
  - B0/B1: yes.
  - B2 (forward): descriptive and directional; probably underpowered to confirm a 3–8¢ edge.
  - C1: yes (running 3+ months).
  - C2/D CHAMPION: not before KILL.
- **Recommended order (fastest decision-relevant evidence):**
  1. **Week 1:** A0 probes and B0 (MDE, tape cadence, release-time census). Start the **C1 collector** in parallel, because forward data cannot be recovered later.
  2. **Weeks 1–3:** B1, the cheapest direct test of the one hypothesis that can produce an edge. Verdict: GO, NO-GO or UNDERPOWERED. UNDERPOWERED means "keep collecting".
  3. **Weeks 2–5:** A1 archives in the order PFM (smallest), GFS MOS (existing code), LAMP (largest). Then the Phase A fit and acceptance. HRRR (A2) only if A passes.
  4. **After the A/B1 verdicts:** B2 on the C1 forward data, with a freeze.
  5. **Only if A is ACCEPT and B2 is positive:** C2 and Phase D (after row 7, F1, F4, F5, F7b, AUT-3).
  6. If A is STOP and B1 is NO-GO, F13's candidate space is exhausted for US public sources. Record that as the result.

## 10. Build order for implementers

1. Prereg JSON and A0 probe records (read-only).
2. `us_source_availability.py` with its tests (RED first).
3. Transports and parsers, then the backfills (PFM, GFS MOS, LAMP).
4. C1 collector unit (parallel with 3).
5. B0, then B1 scripts.
6. Blend module and the offline runner (Phase A scoring after the prereg sha is committed).
7. B2, then D, then C2, each gated as in §4.8 to §7.

Brief every implementer with: Nautilus is immutable, `allow_short` stays False, no weakening of safety or contract tests, no touching the live enablement, permit or NO-SEND firewall, and the exact interpreter path (no `uv sync` in a worktree). Set `PYTHONPATH` in worktrees, run `lint-imports` from the tree, and read the gate EXIT code before any push. Reviews: python-reviewer for code, prediction-market-reviewer for the statistics and the market comparison, and security-reviewer for the new egress hosts.

## 11. Open items for the peer loop

- Ratify the §3 holdout treatment, in particular whether B1 as "model-free" may use tape days ≥ 07-01.
- Confirm the acceptance thresholds (3 % CRPS, 4 % RMSE) and the lag defaults.
- Confirm that the PFM, MDL and LAMP URLs, timings and station points hold (A0).
- Decide whether C1 needs its own row, since F13 is currently framed as an actor plus node wiring (row 7).
- Verify the exact venue rung mapping module and `ArchiveRequest` field shape before the CSV normalisation is frozen.

Relevant paths (all under `/home/jon/breezy`):
- `docs/evidence/F13_US_SOURCE_SURVEY_2026-10-06.md`
- `docs/evidence/AUT_S_PHASE0_2026-10-06.md`
- `docs/evidence/M1_MARKET_SCAN_2026-10-04.md`
- `docs/evidence/FQ_LOSS_TRIAGE_2026-10-04.md`
- `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md`
- `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r2.md`
- `src/breezy/ingest/nbm_quantile_transport.py`
- `src/breezy/ingest/nbm_quantile_actor.py`
- `src/breezy/persistence/archive_cache.py`
- `scripts/venue/iem_mos_probe_transport.py`
- `scripts/archive/iem_mos_backfill.py`
- `src/breezy/analysis/nbp_calibration.py`
- `src/breezy/persistence/autonomy/capture_schedule.py`
- `src/breezy/persistence/autonomy/lineage.py`
- `src/breezy/app/trade.py`
---

## Peer-review round 1 rulings (coordinator, 2026-10-06; binding for r2)

**Reviews:**
- Architect: REQUEST_CHANGES.
- Stats: SOUND-WITH-CAVEATS (1 bug).
- Security: CONDITIONAL APPROVE.

- **F13-R1, order and scope.**
  - **Week 1** covers four things:
    - the A0 probes;
    - B0, which is the MDE from the empirical tape SD plus a placebo-feasibility check;
    - **C1 limited to** (a) the hourly LAMP live archive, and (b) measured availability times for NBP, PFM and LAMP;
    - GFS MOS and PFM history, which are backfilled from IEM rather than collected.
  - **Cut from r2:** A2 HRRR, the NAM ablation, MEX, GFS MOS in C1, and the detailed C2/D file and test lists. C2/D become a gate statement only.
  - **C1 gets its own queue row, F13-C1.** It is time-critical, needs the egress security review, and does not wait for Phase A or row 7.
- **F13-R2, B1 redesign** (stats BUG; architect).
  - **Rules that stay:**
    - model-free and **CLI-free**;
    - its days are "scan" days that never count as evidence;
    - its single read is pre-registered.
  - **Primary family:** {PFM at the exact WMO time, the NBP cycle at its measured vintage} × the 60-min window, Holm over 2. The 15-min window and LAMP are descriptive, because the windows are nested and LAMP is hourly.
  - **Release time:** the *measured first public availability*, never the nominal run time.
  - **Outcome:**
    - a **matched-rung panel fixed before the release**: rungs with both sides at t and at t+Δ. Dropout is reported per arm, and differential missingness is itself an outcome;
    - the **signed** change, regressed on the forecast delta.
  - **Placebos and controls:**
    - the same clock time on days the source did not update;
    - matching on minute offset from the METAR release (:51–:56);
    - a within-day pre-window, [t−60, t] versus [t, t+60].
  - **Run order:** compute the MDE first, and STOP if it exceeds a plausible effect.
- **F13-R3, B2 becomes a realised-EV futility screen.**
  - **Outcome:** realised EV per take at settlement, net of θ fee, 0.01 slippage and margin(h). Drift is a diagnostic only.
  - **Execution detail:** a lag curve at 0/30/60/120/300 s, a measured latency distribution (not one 44 s case), and depth at the ask.
  - **Stop rules:**
    - It is a futility screen, not confirmation (about 1,500 trades would be needed to confirm 3¢).
    - It STOPs if the market adjusts in under 60 s.
- **F13-R4, the Phase A blend** (architect REJECT on extending `fit_hierarchical_emos`).
  - **The champion is untouched.** M0 = `fit_calibration`, unchanged.
  - **New fits:** M1–M3 are fit in a new `multisource_blend.py` with `crps_numerical`.
  - **Procedure-equivalence control:** M0′ is the new procedure with k = 0, and must match M0's CRPS within tolerance. The test statistic is Δ = M0′ − M3.
  - **Byte-unchanged test:** `nbp_calibration.py` is asserted byte-unchanged by a test.
  - **Predictive distribution:** Student-t, with σ driven by source disagreement:
    `log σ = c + d·log(NBP spread) + e·log(sd of the sources' μ)`, floored.
  - **Ladder:** the primary comparison uses an identical σ treatment, and the disagreement-σ gain is a separate ladder step.
  - **Primary test:** a paired ΔCRPS day-block CI with LB > 0, **plus a minimum-effect floor** derived from the fold SE, pre-registered.
  - **Descriptive only:** RMSE, so K = 1.
  - **Co-reported diagnostics:** PIT and 80/95% coverage, and the log score on the rung ladder.
  - **Fold sign:** the same sign in ≥ ⌈0.75·n_folds⌉ folds.
  - **Weight sum:** shrinkage toward 1, not a hard box.
  - v5 never mints (AS-R14).
- **F13-R5, the data contract.**
  - Add `first_seen` to the basis enum.
  - Record availability as the interval (last miss, first_seen].
  - Reuse the existing floor rule `max(observed, run + floor)` (`nbp_derived_store.py:142-153`).
  - Tag mirror hosts in `available_at_basis`. IEM/MDL `Last-Modified` is the mirror ingest time, not NWS issuance.
  - The frozen backtest lags are ≥ the maximum observed by C1 over ≥ 14 days.
- **F13-R6, reuse.**
  - Use a separate product table for PFM and LAMP. Do not edit `IEM_MOS_MODEL_PRODUCTS` (it is MOS-only).
  - Freeze the `ArchiveRequest` keys for PFM (office/point) and LAMP (per-run tar) before building.
  - AFOS and LAV go through the existing **`PacedIemTransport`**. A second transport to the same host would break IEM pacing.
  - Only MDL gets a new transport.
  - Register the new routes in `tests/contract/test_transport_error_routing_contract.py`.
  - Fix the citations: sha256 is at `nbm_quantile_transport.py:449`, and `crps_normal` is a test oracle only.
- **F13-R7, security (mandatory requirements, each tested).**
  - **H1, every new transport:**
    - exact-match host frozenset, https/443, `follow_redirects=False` (3xx = error), `trust_env=False` plus the proxy-env check;
    - GET only, explicit timeouts, and a per-source byte cap;
    - tests: a 3xx to an allowed host and a 3xx to a disallowed host.
  - **H2, tar handling:** stream mode `r|`, never `extract`, `isreg()` members only, and paths derived from `(source, run_ts)` only. Cap the member count, the per-member size and the total decompressed bytes. Tests: `../`, absolute path, symlink, oversize.
  - **H3, parsers:** bounded line and field counts, strict decode, and physical range checks. A bad row refuses the run and alerts. Closed station and point maps.
  - **H4, integrity:** F2-style append-only revisions. A changed payload for the same key becomes a new revision; the first-seen revision is used for anchors; an unconfirmed change is never promoted. An outlier more than N °F from every other source is quarantined. Tests: `test_changed_payload_for_same_key_appends_revision_not_overwrite`, `test_unconfirmed_outlier_not_promoted`.
  - **H5, the C1 unit:**
    - no credentials, only `alerts.env` via `EnvironmentFile`;
    - **bwrap no-credential profile**, with only the archive output writable and `~/.config/breezy` unmounted;
    - `MemoryMax`, `RuntimeMaxSec` (never past 16:30Z), `LimitNOFILE` and `TasksMax`;
    - a unit-level `flock`, so overlap is skipped;
    - boundary clock tests at 16:29:59, 16:30, 17:09:59 and 17:10.
  - **M6, the NO-SEND ruling (decided now; the firewall is not touched).** Data transports in `breezy.ingest.*` are outside the execution-egress guard. A guard test enforces it with three checks, and the guard runs under the no-egress gate with MockTransport and no live fetch in CI:
    - (a) no import of the write transport, order sender, permit, `breezy.runtime` or exec client;
    - (b) AST check that only GET is used;
    - (c) no polymarket, kalshi or exec-client host in any allowlist.
  - **M6, live fetches** run only from offline tools or the C1 units, never from the node or from pytest. The exec import pin x1 is extended by WIDENED rows only.
  - **M7, C2 later:** an AST transitive import-closure check, a bridge with a hard timeout, activation only at the 16:50Z LAUNCH, and the activation commit parked on a branch until the gates pass.
  - **M8:** exact S3 bucket FQDNs pinned, with host-to-path-prefix binding. Never `*.amazonaws.com`.
  - **LOW:**
    - an NTP check, with `fetched_at` recorded;
    - `redact_url`, and a project-alias User-Agent contact (not the operator's email);
    - the disk guard is a hard refusal.
- **F13-R8, loss reduction (stats).**
  - **Added to Phase A:** the **blend as a veto on FQ-style takes.** Measure how many historical FQ-rule takes the blend would refuse, and their CLI outcomes (pre-07-01 descriptive). Forward use is shadow only.
  - **Out of F13 scope:**
    - the pooled NO-side favourite-longshot structural test becomes a separate M1-v3 item;
    - maker/resting orders go to the existing resting-bid line.
  - **Rejected:** a Kalshi lead-lag signal. The operator ruled that venue prices are execution cost only, never a predictor (memory `prediction-from-weather-venues-for-cost`).
- **F13-R9, Phase D/C2 gate statement.** D needs, in addition:
  - F6 (C2 composes inside `_compose_forecast_quantile_ladder`, E-28);
  - the ARCH-0 owner for `pins.py:96`;
  - the AUT-4 OFFLINE_CHALLENGER screen.
  The "B2 positive" gate is restated as "B2 not futile".
