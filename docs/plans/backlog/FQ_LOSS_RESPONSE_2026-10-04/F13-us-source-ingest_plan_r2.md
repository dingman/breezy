# F13 FQ-SRC-INGEST, plan r2

[DESIGN] US source ingest: C1 collector, timing study, offline blend skill, C2/D gate statement

Status: PLAN r2. Nothing is built. It applies F13-R1..R9 exactly, and it is for the convergence round of the peer loop. Everything here is build-time design.

## 0. Verdict

- **Expected edge from a static public-US blend: about zero against the market, and likely below it once ECMWF is gone.**
  - The survey's roughly 2.25 against 2.44 RMSE is unverified and used ECMWF.
  - The ask-side hurdle is the θ=0.0695 fee, the 0.01 slippage floor and `margin(h)` ≥ 0.02.
  - Phase A's real value is "does the blend beat NBP on CLI" and the veto analysis (F13-R8). It is a loss-reduction tool, not an edge.
- **The timing hypothesis is the only path with a plausible positive edge, and it is cheap to falsify.**
  - B1 is offline, model-free, CLI-free and runs on existing tape.
  - B2 is only a futility screen (F13-R3). About 1,500 trades would be needed to confirm a 3¢ edge, and we will not have them.
- **F13-C1 is the one time-critical item.** Forward availability times and the hourly LAMP archive cannot be backfilled. C1 gets its own queue row and does not wait for Phase A or row 7.
- **KILL is 2027-01-25, 111 days from 2026-10-06.**
  - Settleable by KILL: the Phase A ACCEPT or STOP, B1 GO / NO-GO / UNDERPOWERED, the veto descriptives, the B2 futility result, and 3+ months of C1 data.
  - Not settleable by KILL: confirming a 3–8¢ edge, and any CHAMPION `density_table_multisource` (AUT-S r2 line 172, E-26 rule 4).
- **Cut from r2 (F13-R1):** A2 HRRR, the NAM ablation, MEX, GFS MOS in C1, and the C2/D file and test lists.

## 1. Facts (verified this round with codegraph; corrections marked)

| Item | Where (verified) | Use |
|---|---|---|
| IEM host policy | `scripts/venue/iem_mos_probe_transport.py:50-60`. `IEM_ALLOWED_HOSTS` is `{mesonet.agron.iastate.edu}` (`:53`). `IEM_MIN_INTERVAL_NS` = 1 s (`:54`). Body cap 32 MiB. Stations KLAX/KMDW/KMIA/KSFO. Models NBS/GFS. | Add KNYC and the LAV/AFOS paths by closed-set edits only. |
| **`PacedIemTransport`** | `scripts/venue/iem_mos_probe_transport.py:171-261`, extends `HttpTransport`. The constructor refuses any host set other than `IEM_ALLOWED_HOSTS` and any other base URL (`:198-203`). It refuses settlement hosts (`:189-197`). The NWS methods are closed with `NotImplementedError` (`:222-244`). `_fetch` consumes the budget and awaits the pacer (`:246-261`). One consumer exists today (`scripts/archive/iem_asos1min_backfill.py`). `IemMosProbeTransport` subclasses it at `:264`. | **AFOS and LAV are new subclass methods on this class (F13-R6).** A second transport to IEM would bypass the pacer and budget. Because it lives under `scripts/`, the IEM-facing code lives under `scripts/` too. See the OPEN-1 import-direction note. |
| Hardened S3/NOMADS client | `src/breezy/ingest/nbm_quantile_transport.py`. **Correction:** the single-pass sha256 digest is at `:449`, not `:439`. The shape is: fixed allowlist, https only, no redirects, `trust_env=False`, a streaming filter with the digest. | Mirror it for the MDL transport only. |
| Archive cache | `src/breezy/persistence/archive_cache.py`. `ArchiveRequest` (`:96`) has exactly `source, station, product, window_start, window_end, model` (windows in UNIX ns). Payload path is `<root>/<source>/<cache_key>.csv` (`:393`). `IEM_MOS_MODEL_PRODUCTS` is MOS-only at `:59`. | **Do not edit `:59` (F13-R6).** Add a separate `US_SOURCE_PRODUCTS` table. Key freeze is OPEN-2. |
| **`available_at` floor rule** | **Correction:** `src/breezy/persistence/nbp_derived_store.py:142-153`, not `src/breezy/ingest/`. `available_at_ns(*, cycle_runtime_ns, last_modified_ns)` returns `max(last_modified, cycle + PUBLICATION_LAG_FLOOR_NS)`. It falls back to the floor when the header is absent or unparseable. | The reuse target for F13-R5. |
| **`crps_numerical`** | `src/breezy/analysis/nbp_calibration.py:529`. Takes `(cdf callable, observed, *, center=...)`. Fixed 0.1 °F grid, ±40 °F around `center` (`:523-524`). | The blend scorer. Pass the blend μ as `center`. A new fit never reuses the champion's Q50 centre. |
| `crps_normal` | `nbp_calibration.py:510`. **Correction (F13-R6):** the docstring says it is kept only as a test oracle for the fit path. It is also used in the separate correction scorer at `:1451`, which this plan does not touch. | Test oracle for the Student-t and normal limits. Not in the fit path. |
| Champion fit entry points | `fit_hierarchical_emos` `:1166`, `fit_calibration` `:1280`, `open_holdout` `:353` (single look). | **Untouched (F13-R4).** M0 = `fit_calibration`. `open_holdout` is never called. |
| Transport error routing contract | `tests/contract/test_transport_error_routing_contract.py`. A new `TransportError` subclass needs a route in `breezy.ingest.routing.TRANSPORT_ERROR_ROUTES` and a recipe in `TRANSPORT_ERROR_CONSTRUCTORS` (`:65`). Tests at `:148`, `:155`, `:197`, `:246` fail loudly otherwise. | Every new error class from the MDL transport, the parsers and the revision store registers in both places in the same change (F13-R6). |
| Firewall guard helpers | `find_write_transport_importers` is at `tests/unit/test_polymarket_us_write_transport.py:92`. It is an import and dotted-string scan for the write-transport token. `find_exec_transport_violations` is at `tests/unit/test_execution_egress_firewall_guard.py:2298`, with `BANNED_EXEC_TRANSPORT_MODULES` at `:1862`. `find_order_sender_reference_violations` is at `tests/unit/test_execution_egress_firewall_guard.py:4242`. | **Correction:** the last helper only scans `self._order_sender` references inside functions. It is not an import scan, so it cannot be the M6(a) check. The M6 guard reuses the first helper's pattern and `BANNED_EXEC_TRANSPORT_MODULES`. It does not edit the firewall. |
| Launch window | `src/breezy/persistence/autonomy/capture_schedule.py:3`, [16:30Z, 17:10Z). | Collector and backfills stay outside it. |
| C3 invariants | `src/breezy/persistence/autonomy/lineage.py:73-74`. | Phase D only (gate statement). |

Recorded constraints:
- E-26 rules 2 and 4 stand.
- AUT-S Phase 0: G2 is empty.
- M1: MDE is far above a realistic edge.
- NBM spread was too narrow (about 2 °F, against 3–8 °F misses).

Not verified, and so an A0 probe item: the survey's arXiv figures, the LAMP/AFOS/MDL URLs and timings, and the PFM point-to-station mapping.

## 2. Data contract (F13-R5)

Normalised CSV row: `source, source_version, station_icao, run_ts_utc, valid_ts_utc, variable, value, unit, available_at_utc, available_miss_utc, available_at_basis, host_tag, revision, raw_sha256, fetched_at_utc`.

- **`available_at_basis` ∈ {`measured_header`, `wmo_header`, `first_seen`, `nominal_plus_conservative_lag`}.**
  - `first_seen` is new.
  - Mirror hosts are tagged in `host_tag` and in the basis suffix, for example `measured_header@iem`.
  - IEM/MDL `Last-Modified` is the **mirror ingest time**, not NWS issuance. It is never labelled `wmo_header`.
- **Interval, not a point.** Availability is recorded as `(available_miss_utc, available_at_utc]`.
  - `available_miss_utc` is the last poll that did not see the product.
  - `available_at_utc` is the first poll that did.
  - Backtest anchors use the upper bound.
- **Floor rule.** `us_source_availability.available_at(source, version, run_ts, observed) -> (ts, basis, miss_ts)` is a pure function that reuses the `max(observed, run + floor)` pattern of `nbp_derived_store.py:142-153`. It does not import from the NBP store. Test `test_floor_rule_matches_nbp_available_at_ns_on_shared_fixtures` pins the parity.
  - PFM: the WMO header time is exact.
  - LAMP: run + 60 min until measured.
  - GFS MOS: run + at least 5 h until measured (the survey's 4 h 30 min is for 00Z only).
- **Frozen backtest lags ≥ the maximum observed by C1 over ≥ 14 days** (F13-R5). Until C1 has 14 days, Phase A scoring does not run. Phase A cannot score on nominal lags alone.
- Clock: NTP offset is recorded with `fetched_at` on every cycle. A cycle with an offset above the pre-registered bound refuses and alerts (LOW).

## 3. Holdout

1. **Phase A scores only days < 2026-07-01 against CLI.** It never uses a market input and never calls `open_holdout`.
2. **Any blend-versus-market comparison is forward-only shadow,** and only on days strictly after a committed freeze (sha-pinned prereg plus fitted weights).
3. **B1 (F13-R2)** is model-free and CLI-free. Its days are "scan" days that never count as evidence, and its single read is pre-registered. B1 reads no model value and no CLI value, so it does not touch the sealed model-output days.
4. **B2** is forward-only on C1 data after the freeze.
5. **No tape exists for 07-01 to 08-29,** so no Phase A fold overlaps the market.
6. **Veto analysis (F13-R8) tension.** Real FQ takes exist only from 2026-08-30, which is after 07-01. The blend applied to those days is a forward descriptive shadow on scan days, never evidence. The pre-07-01 version uses a model-side proxy of the FQ rule. See Phase A1/A.

## F13-C1: live collector (own queue row)

**Scope (F13-R1).**
- (a) The hourly LAMP live archive.
- (b) Measured availability times for NBP, PFM and LAMP.

GFS MOS and PFM *history* are backfilled from IEM, not collected. HRRR, MEX and the NAM ablation are cut.

**Form.** A systemd user timer fires a oneshot unit per source and cycle. It runs to completion and is idempotent. The key is `(source, run_ts, revision)`, written through `ArchiveCache`'s flock single writer. C1 is a separate domain, and the node never reads it. C1 reads NBP only as a **header-only availability observation** of the file the node's own actor also reads. It does not write NBP rows into the NBP store.

**Cadence.**
- LAMP: hourly, a poll burst around HH:30–HH:50. The first poll that sees the product sets `available_at`, and the last poll without it sets `available_miss`.
- PFM: polls around the two issue windows.
- NBP: the cycle times.

**Firing rules.** Never past 16:30Z (H5, `RuntimeMaxSec` is capped to the window start). A firing that would overlap [16:30Z, 17:10Z) is skipped and rerun at 17:10Z flagged `late`.

**Files.**

| Status | File |
|---|---|
| NEW | `src/breezy/ingest/mdl_lamp_transport.py` (MDL only: exact host frozenset, M8 binding) |
| NEW | `scripts/venue/iem_afos_lav.py` (or `PacedIemTransport` subclass methods `fetch_afos_pfm`, `fetch_lav`; F13-R6) |
| NEW | `src/breezy/ingest/us_source_availability.py`, `lamp_parse.py`, `pfm_parse.py` |
| NEW | `src/breezy/persistence/us_source_revision_store.py` (append-only revisions, H4) |
| NEW | `scripts/collect/us_source_collector.py` (the cycle driver) |
| NEW | `ops/systemd/us-source-collector@.service` and `.timer`, plus the bwrap profile |
| NEW | `tests/contract/test_us_source_ingest_egress_guard.py` (M6) |
| EDIT (closed sets only) | `scripts/venue/iem_mos_probe_transport.py` `:58` (KNYC), `:60` (LAV and AFOS paths). Registers in `TRANSPORT_ERROR_ROUTES` and `TRANSPORT_ERROR_CONSTRUCTORS`. |
| EDIT (additive) | `src/breezy/persistence/archive_cache.py`: a **new** `US_SOURCE_PRODUCTS` table. `IEM_MOS_MODEL_PRODUCTS` is unedited. |

**Security requirements (F13-R7), each with a test.**

*H1, every new transport.*
- Exact-match host frozenset, https and port 443.
- `follow_redirects=False`: any 3xx is an error.
- `trust_env=False` plus the proxy-env check.
- GET only, explicit connect and read timeouts, and a per-source byte cap.
- 429 honours `Retry-After`. The IEM 1 s interval is kept by reusing the pacer.

Tests:
- `test_transport_refuses_3xx_to_allowed_host`
- `test_transport_refuses_3xx_to_disallowed_host`
- `test_transport_refuses_non_exact_host_suffix_and_subdomain`
- `test_transport_refuses_non_https_and_non_443`
- `test_transport_refuses_proxy_env`
- `test_transport_is_get_only`
- `test_oversize_body_refused_by_cap`
- `test_rate_limit_429_backoff_respects_retry_after`
- `test_afos_and_lav_use_paced_iem_transport_not_a_second_transport`

*H2, tar handling.*
- Stream mode `r|`. Never `extract` or `extractall`.
- `isreg()` members only.
- Output path derived from `(source, run_ts)` only, never from a member name.
- Caps on member count, per-member size and total decompressed bytes.

Tests:
- `test_tar_rejects_dotdot_member`
- `test_tar_rejects_absolute_member`
- `test_tar_rejects_symlink_and_hardlink_members`
- `test_tar_rejects_oversize_member_and_total_and_member_count`
- `test_tar_stream_filters_stations_without_buffering_whole_tar`
- `test_output_path_never_derived_from_member_name`

*H3, parsers.*
- Bounded line and field counts, strict UTF-8 decode, and physical range and unit checks.
- A bad row **refuses the run and alerts**. It is never skipped.
- Closed station and point maps. An unmapped point is refused.

Tests:
- `test_parser_refuses_row_out_of_physical_range`
- `test_parser_refuses_non_utf8`
- `test_parser_refuses_line_and_field_count_over_bound`
- `test_pfm_unmapped_point_refused`
- `test_pfm_parse_selects_station_point_and_max_row`
- `test_lamp_daily_max_uses_climate_day_lst_window`
- `test_bad_row_refuses_run_and_emits_alert`

*H4, integrity.*
- A changed payload for the same key appends a **new revision**. Overwrite is impossible.
- The first-seen revision anchors timing. An unconfirmed change is never promoted.
- An outlier more than N °F from every other source is quarantined. N is pre-registered.

Tests:
- `test_changed_payload_for_same_key_appends_revision_not_overwrite`
- `test_unconfirmed_outlier_not_promoted`
- `test_first_seen_revision_is_the_anchor_revision`
- `test_quarantined_outlier_excluded_from_features_and_counted`

*H5, the C1 unit.*
- No credentials. Only `alerts.env` through `EnvironmentFile`.
- **bwrap no-credential profile.** Only the archive output is writable, and `~/.config/breezy` is not mounted.
- `MemoryMax`, `RuntimeMaxSec` (never past 16:30Z), `LimitNOFILE` (set via the unit; the `systemd-run` soft limit is 1024) and `TasksMax`.
- A unit-level `flock`, so an overlapping run is skipped.
- Boundary clock tests at 16:29:59, 16:30:00, 17:09:59 and 17:10:00.

Tests:
- `test_unit_has_no_credential_env_or_config_mount`
- `test_unit_sets_memory_runtime_nofile_tasks_caps`
- `test_runtime_max_never_extends_past_16_30z`
- `test_overlapping_run_skipped_by_flock`
- `test_clock_boundary_16_29_59_runs`
- `test_clock_boundary_16_30_00_skips`
- `test_clock_boundary_17_09_59_skips`
- `test_clock_boundary_17_10_00_runs_late_flagged`

*M6, NO-SEND ruling (decided now; the firewall is not touched).*
- Data transports in `breezy.ingest.*` and the IEM transports are outside the execution-egress guard. A new guard test enforces that with three checks, and it runs under the no-egress gate with `MockTransport` and no live fetch in CI.
- Because the IEM transports live under `scripts/`, the scan covers `src/breezy/ingest/` (new files), `scripts/venue/` (new files) and `scripts/collect/`.
- Live fetches run only from offline tools or the C1 units, never from the node or from pytest.
- The exec import pin x1 is extended by WIDENED rows only, never a relaxed `==`.

Tests:
- `test_data_transports_do_not_import_write_transport_order_sender_permit_runtime_or_exec_client` (reuses the `find_write_transport_importers` pattern and `BANNED_EXEC_TRANSPORT_MODULES`)
- `test_data_transports_use_only_http_get` (AST)
- `test_no_polymarket_kalshi_or_exec_host_in_any_allowlist`
- `test_guard_runs_with_mock_transport_and_no_live_fetch`
- `test_exec_import_pin_x1_unchanged_or_widened_only`

*M8.*
- Exact S3 bucket FQDNs are pinned, with a host-to-path-prefix binding. `*.amazonaws.com` is never used.
- `test_s3_host_bound_to_its_path_prefix`
- `test_wildcard_amazonaws_host_refused`

*LOW.*
- `redact_url` on every logged URL.
- A project-alias User-Agent contact, not the operator's email.
- NTP offset recorded with `fetched_at`.
- The disk guard is a hard refusal.

Tests:
- `test_user_agent_contains_project_alias_not_operator_email`
- `test_logged_urls_are_redacted`
- `test_disk_guard_refuses_below_threshold`
- `test_ntp_offset_recorded_and_excess_refuses`

*Reuse and registration (F13-R6).*
- `test_new_transport_errors_have_routes_and_constructors` (via the contract test's existing walks)
- `test_us_source_products_table_does_not_modify_iem_mos_model_products`
- `test_normalised_csv_roundtrips_through_archive_cache_with_digest`

*Idempotency and observability.*
- `test_cycle_is_idempotent_after_midwrite_kill`
- `test_rerun_never_duplicates_payload_or_manifest_entry`
- `test_available_at_is_observed_header_never_assumed`
- `test_first_seen_basis_and_miss_interval_recorded`
- `test_mirror_host_tagged_in_basis`
- `test_stale_source_alerts_after_deadline`

**Acceptance (C1).**
- 14 consecutive days with ≥ 95 % of expected cycles captured.
- Zero duplicate payloads.
- Every row has an observed `available_at` with a basis and an interval.
- The measured maximum lag per source is published as an A0 table. It freezes the Phase A backtest lags (F13-R5).

**Dependencies:** none. C1 needs no node respawn and no row 7. It needs the security review of the new egress hosts before the first live firing.

## Phase A0 / B0 (week 1; F13-R1)

**A0 (read-only probe, one day per source, writes a feasibility record).**
- Confirm every URL and the tar layout.
- Confirm PFM point names, with a closed station map for KNYC `NYZ072` and the other four.
- Confirm LAMP timing, the rate limit, and the member mtimes.
- Confirm that the MDL tars end in 2025.

**B0 (offline, days).**
- **MDE from the empirical tape SD.** The minimum detectable effect is computed first, from the empirical SD of the matched-rung panel statistic. It is not scaled from M1. A STOP rule applies: if the MDE exceeds the plausible effect, B1 records UNDERPOWERED.
- **Placebo feasibility check.** Count the available no-update days at the same clock time, and the days with METAR-offset matches. If the placebo pool is too thin, B1 reports descriptive only.
- **Tape inventory.** Depth10 cadence and coverage per station-window since 08-30. QuoteTicks cannot show an empty bid.
- **Release census.** PFM WMO times from IEM AFOS, NBP measured vintages from the catalog if present (verify), LAMP nominal until C1 has data.
- **Backfills (F13-R1).** PFM history (2021 onward) and GFS MOS (including KNYC) come from IEM through `PacedIemTransport`.

Tests:
- `test_mde_reported_before_any_effect_estimate`
- `test_b0_stops_underpowered_when_mde_exceeds_plausible_effect`
- `test_placebo_pool_feasibility_counted_per_stratum`
- `test_pfm_wmo_header_time_is_available_at`
- `test_available_at_never_precedes_run_ts_for_any_source`
- `test_conservative_lag_not_earlier_than_measured_live_lag`
- `test_gfs_mos_closed_day_guard_does_not_apply_to_lav_or_pfm`

## Phase B1: timing event study (F13-R2)

**Fixed rules.** Model-free and CLI-free. Its days are scan days that never count as evidence. The single read is pre-registered.

- **Release time = measured first public availability** from C1 or the PFM WMO header. It is never the nominal run time. For days before C1 started, only PFM has an exact time. NBP uses measured vintages if the catalog has them. Otherwise it is omitted.
- **Primary family (Holm over 2):** {PFM at the WMO time, the NBP cycle at its measured vintage} × the 60-min window.
- **Descriptive only:** the 15-min window (nested), and LAMP (hourly).
- **Outcome.**
  - The **signed** change in the ladder-implied expected daily max.
  - It is computed on a **matched-rung panel fixed before the release**: only rungs with both sides quoted at t and at t+Δ.
  - It is regressed on the forecast delta, and the slope is the primary statistic.
  - Dropout is reported per arm. Differential missingness is itself an outcome.
- **Placebos and controls.**
  - The same clock time on days the source did not update.
  - Matching on minute offset from the METAR release (:51–:56).
  - A within-day pre-window, [t−60, t] versus [t, t+60].
- **Interpretation limit.** A significant slope says the market reacts around releases. It does not establish a tradable lag.

Files: NEW `src/breezy/analysis/release_timing.py` (pure), NEW `scripts/analysis/release_timing_event_study.py` (read-only, memory-capped), NEW `scripts/analysis/release_census.py`.

Tests:
- `test_event_study_uses_no_model_or_cli_values`
- `test_release_time_is_measured_first_availability_never_nominal`
- `test_matched_rung_panel_fixed_before_release`
- `test_dropout_and_differential_missingness_reported_per_arm`
- `test_signed_change_regressed_on_forecast_delta`
- `test_placebo_same_clock_time_on_no_update_days`
- `test_placebo_matched_on_metar_minute_offset`
- `test_pre_window_control_runs_for_every_event`
- `test_holm_over_exactly_two_primary_tests`
- `test_fifteen_minute_and_lamp_results_labelled_descriptive`
- `test_empty_bid_rungs_excluded_and_counted`
- `test_event_windows_never_cross_16_30_17_10z_without_flag`
- `test_release_timestamp_provenance_recorded_per_event`
- `test_b1_stops_when_b0_mde_exceeds_plausible_effect`
- `test_b1_prereg_sha_recorded_and_single_read_enforced`

## Phase B2: realised-EV futility screen (F13-R3)

- **Outcome.** Realised EV per take at settlement, **net of** the θ fee, the 0.01 slippage floor and `margin(h)`, at the actual fill price. Drift is a diagnostic only.
- **Execution detail.**
  - A lag curve at 0, 30, 60, 120 and 300 s after the measured release.
  - A measured latency distribution from fetch to decision, never the single 44 s LAX case.
  - Depth at the ask for each simulated take.
- **Stop rules.**
  - It is a futility screen, not a confirmation (about 1,500 trades would be needed for 3¢).
  - It STOPs if the market adjusts in under 60 s.
  - If F7b is not merged, it reports a descriptive fixed-n result with no verdict.
- **Data.** C1 forward data after the freeze. No scan day and no sealed day counts.

Tests:
- `test_b2_outcome_is_realised_ev_net_of_fee_slippage_and_margin`
- `test_b2_lag_curve_points_exactly_0_30_60_120_300`
- `test_b2_latency_is_a_distribution_not_a_constant`
- `test_b2_depth_at_ask_limits_simulated_size`
- `test_b2_stops_when_market_adjusts_under_60s`
- `test_b2_labelled_futility_screen_never_confirmation`
- `test_b2_refuses_days_before_freeze`
- `test_ref_ts_lt_decision_ts_for_every_b2_row`

## Phase A1 / A: archives, the blend and the veto analysis (F13-R4, F13-R8)

**Archives (A1; HRRR, MEX and NAM are cut).**
- PFM: IEM AFOS for the five offices, 2021 onward.
- GFS MOS: the existing backfill plus KNYC.
- LAMP: MDL tars to 2025, streamed through the H2 handler. IEM LAV fills the 2026 gap, with the basis flagged. C1 supplies it going forward.
- Only days < 2026-07-01 reach the fit or the score. Later archives are kept for the forward feed.

**Procedure (F13-R4).**
- **The champion is untouched.** M0 = `fit_calibration`. A test asserts `nbp_calibration.py` is byte-unchanged (`test_nbp_calibration_module_is_byte_unchanged`, pinned to a recorded sha).
- M1–M3 are fit in a new `src/breezy/analysis/multisource_blend.py`, scored with `crps_numerical` (`:529`) and `center` = the blend μ.
- **M0′** is the new procedure with k = 0. It must match M0's CRPS within a pre-registered tolerance. This is the procedure-equivalence control.
- **Test statistic: Δ = CRPS(M0′) − CRPS(M3).**
- **Distribution.** Student-t, with `log σ = c + d·log(NBP spread) + e·log(sd of the sources' μ)`, floored. **The primary comparison uses an identical σ treatment on both arms.** The disagreement-σ term is a separate, later ladder step.
- **Weights.** Shrinkage toward a sum of 1, not a hard box.
- **Ladder.** M0′, then M1 (+LAMP), M2 (+PFM) and M3 (+GFS MOS).
- **K = 1.** The primary hypothesis is M3 versus M0′. RMSE is descriptive only.
- **v5 never mints (AS-R14).**

**Acceptance.**
1. Paired ΔCRPS with a day-block bootstrap CI (stationary, mean block 7 days, by climate day across stations), with LB > 0.
2. **Plus a minimum-effect floor** derived from the fold SE and pre-registered. The r1 "3 %" figure is withdrawn.
3. The same sign in ≥ ⌈0.75·n_folds⌉ folds.
4. A Δ above the fold spread becomes `HELD_LEAK_AUDIT`.
5. No station degraded beyond a pre-registered tolerance.
6. **Co-reported diagnostics:** PIT, 80 % and 95 % coverage, the log score on the rung ladder, and RMSE (descriptive).

Otherwise **STOP:** record NO_SKILL, stop Phase D, and keep B1 and C1 running.

**Folds.** Blocked within each NBM version. A version enters only with ≥ 2 blocks of ≥ 28 held and ≥ 28 train days. No fold straddles a source break (the pre-registered list from A0). The positive control is that M0 reproduces the committed champion. The negative control is a shuffled-label Δ ≈ 0.

**Veto analysis (F13-R8).**
- *Question:* how many FQ-style takes would the blend have refused, and what were their CLI outcomes.
- *Pre-07-01 descriptive proxy.*
  - No tape exists before 08-30, so no historical FQ take has a price before 07-01.
  - The take set is therefore a **model-side proxy of the FQ rule** using only champion output and a pre-registered reference.
  - It reports refusal rate, and CLI outcomes of refused versus kept takes, by station.
  - It is descriptive and carries no verdict.
- *Real FQ takes (≥ 08-30)* get a forward shadow veto count only. They are scan days and never evidence.
- *Forward use is shadow only.*
- **OPEN-3:** the exact FQ take rule that the proxy mirrors must be copied from the FQ-LOSS-RESPONSE plan r3 and frozen in the prereg. It was not re-verified this round, so the proxy definition is open until the implementer cites the rule's file and line.
- **Out of F13 scope (F13-R8).** The pooled NO-side favourite-longshot test goes to a separate M1-v3 item. Maker and resting orders go to the existing resting-bid line. A Kalshi lead-lag signal is **rejected** (the operator ruled that venue prices are execution cost only).

Files:

| Status | File |
|---|---|
| NEW | `src/breezy/analysis/multisource_blend.py` (pure) |
| NEW | `scripts/analysis/multisource_blend_skill.py` (runner, memory-capped) |
| NEW | `scripts/analysis/blend_veto_descriptive.py` |
| NEW | `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13_prereg_blend_v1.json` |

Tests:
- `test_nbp_calibration_module_is_byte_unchanged`
- `test_blend_m0_prime_matches_champion_crps_within_tolerance`
- `test_blend_uses_crps_numerical_with_blend_mu_as_center`
- `test_blend_identical_sigma_treatment_across_primary_arms`
- `test_blend_student_t_log_sigma_includes_source_disagreement_only_in_separate_step`
- `test_blend_sigma_floor_prevents_overconfidence`
- `test_blend_weight_sum_shrinks_toward_one_not_hard_box`
- `test_blend_nonfinite_input_refused_not_imputed`
- `test_lamp_peak_window_not_covered_is_missing_not_imputed`
- `test_feature_rows_all_available_before_anchor`
- `test_folds_blocked_within_version_and_never_straddle_source_break`
- `test_negative_control_shuffled_labels_gives_zero_delta`
- `test_no_row_on_or_after_2026_07_01_reaches_the_fit_or_score`
- `test_open_holdout_is_never_called`
- `test_prereg_sha_is_recorded_before_scoring_and_run_refuses_if_changed`
- `test_acceptance_requires_minimum_effect_floor_and_lb_gt_zero`
- `test_acceptance_stops_when_ci_lower_bound_not_positive`
- `test_fold_sign_rule_is_ceil_075_n_folds`
- `test_pit_coverage_and_log_score_are_reported`
- `test_phase_a_refuses_to_score_until_c1_has_14_days_of_measured_lags`
- `test_veto_report_uses_no_market_price_before_2026_08_30`
- `test_veto_forward_shadow_never_feeds_a_verdict`

**Gates:** `scripts/ci/run_tests_no_egress.sh` after every merge. `lint-imports` from the tree with the "N kept, 0 broken" line. Firewall guards in every focused gate. Adapters never import `breezy.runtime`. Interpreter path exact, `PYTHONPATH` set in worktrees, no `uv sync`.

## C2 / D: gate statement only (F13-R9)

C2 (a node-resident `DataActor`) and D (`density_table_multisource`) are **not planned here**. They need all of the following:

- Phase A ACCEPT.
- The forward B2 result **not futile**. This restates the earlier "B2 positive" gate.
- F1 (E-26 filed), F4 and F7b (evaluator and e-process), F5 (PREREG amendment).
- AUT-3 (`c3_writer`).
- Row 7 (node wiring).
- **F6** (C2 composes inside `_compose_forecast_quantile_ladder`, E-28).
- The **ARCH-0 owner** for `pins.py:96`.
- The **AUT-4 OFFLINE_CHALLENGER screen**.
- The F12 PROMOTE enable for the CHAMPION step.

When the gate opens, M7 applies: an AST transitive import-closure check, a bridge with a hard timeout, activation only at the 16:50Z LAUNCH, and the activation commit parked on a branch until the gates pass. Not reachable before KILL.

## Risk register

| Risk | Containment |
|---|---|
| Leakage (`available_at` ≥ anchor) | The interval basis. Upper-bound anchors. Frozen lags ≥ the C1 maximum over ≥ 14 days. A scored-row assertion `max(available_at) < anchor`. Date AND hour scoping. Controls. A Δ above the fold spread becomes `HELD_LEAK_AUDIT`. |
| Mirror time mistaken for issuance | `host_tag` and a basis suffix. The WMO header is the only exact PFM time. |
| Tar-borne path or size attacks | The H2 stream handler and its tests. |
| Poisoned or garbled payloads | H3 refusal. H4 append-only revisions and outlier quarantine. |
| C1 compromise or credential reach | The bwrap no-credential profile. Only `alerts.env`. The `~/.config/breezy` mount is absent. |
| C1 overrunning the launch window | `RuntimeMaxSec` never past 16:30Z, a skip-and-late rule, boundary tests. |
| Second IEM client breaking pacing | AFOS and LAV are `PacedIemTransport` methods. A test asserts no second transport. |
| Routing contract breaks | The new `TransportError` classes are registered in the same change. |
| Underpowered B1 or B2 | The B0 MDE and the STOP rule. B2 is labelled futility only. |
| B1 timing is a mirror artefact | Release time = measured first availability from C1 or the WMO header. |
| LAMP horizon too short for D-1 | A missing-indicator, never imputed. |
| LAMP 2026 gap | IEM LAV with the basis flagged, then C1. |
| Version breaks | A pre-registered break list. v5 never mints. |
| Veto proxy not equal to the real FQ rule | OPEN-3. The proxy is descriptive only. |
| Memory pressure | Streaming parsers, unit caps, one heavy job at a time, a stall watch. Never SIGKILL the node. |
| Disk | A hard-refusal disk guard. Raw tars not retained. |
| Operator-reserved controls, live enablement, permit, firewall, Nautilus | Named or assigned nowhere. None touched. M6 is a guard test and widens pins only. |

## Feasibility

- **Doable in week 1:** A0, B0 (MDE and placebo feasibility), and the C1 unit with LAMP archive and availability timing. C1 first firing needs the security review done.
- **Doable by KILL:** Phase A verdict (it can start only after 14 days of C1 measured lags), B1, the veto descriptives, B2 futility, and 3+ months of C1.
- **Not feasible by KILL:** confirming a 3–8¢ edge or fielding a CHAMPION blend.
- **Edge expectation:** the blend is near zero against the market. A positive result is more likely from B1 and B2, but each has large risks. Those are thin books, an empty bid side, our latency of tens of seconds, and a market that may already be faster than us.
- **Terminal outcome if A is STOP and B1 is NO-GO:** F13's candidate space is exhausted for US public sources. That is recorded as the result.

## Build order

1. **F13-C1 row opens (parallel start).**
   - Prereg JSON skeleton and the A0 probe records (read-only).
   - `us_source_availability.py` with its tests, RED first.
   - Parsers (H3), the revision store (H4), and the MDL transport (H1, H2, M8) with its routing registrations.
   - AFOS and LAV as `PacedIemTransport` methods.
   - The M6 guard test.
   - The unit file, bwrap profile and clock-boundary tests (H5).
   - Security review. Then start the live timers (LAMP, availability observation) outside the launch window.
2. **B0** (MDE, placebo feasibility, tape inventory, release census), in parallel with step 1. PFM and GFS MOS history backfill through `PacedIemTransport`, one heavy job at a time.
3. **B1** after B0 passes its STOP rule. One pre-registered read.
4. **A1 and A.** LAMP archive backfill. The blend runs only after C1 has 14 days of measured lags. The freeze commit comes before any forward comparison. The veto descriptives follow OPEN-3.
5. **B2** on C1 data after the freeze.
6. **C2 / D:** only per the gate statement.

Each implementer brief carries these constraints:
- Nautilus is immutable.
- `allow_short` stays False.
- No weakened safety or contract tests.
- No operator-reserved control is named or set.
- No touching of live enablement, the permit or the NO-SEND firewall.
- The exact interpreter path.
- `PYTHONPATH` in worktrees, `lint-imports` from the tree, and the gate EXIT code read before any push.
- Format only your own files.

Reviewers: `python-reviewer` for code, `prediction-market-reviewer` for the statistics and the market comparison, and `security-reviewer` for the new egress and the unit.

## OPEN items (with reasons)

- **OPEN-1 (import direction).** `PacedIemTransport` lives under `scripts/venue/`. `src/breezy/` cannot import `scripts/`, so the IEM-facing code and the collector driver live under `scripts/`. The MDL transport under `src/breezy/ingest/` is separate. Whether `lint-imports` permits the collector driver to import both was not checked, so the implementer must confirm it before freezing file locations.
- **OPEN-2 (`ArchiveRequest` keys).** The dataclass has no office or point field. A PFM key such as `source="us-pfm"`, `station=<ICAO>`, `product="pfm"`, `model=<WFO>`, and a LAMP per-run tar key with a fixed `station` token, must be frozen in the prereg before any cache is built. This is open because it needs the A0 probe's layout.
- **OPEN-3 (FQ rule).** See the veto analysis. The take rule was not re-read this round.
- **OPEN-4 (A0 facts).** The survey figures, URLs, timings, the 60-min LAMP and 5 h GFS lags, and the NBP measured-vintage rows in the catalog are all unverified until A0 and C1 produce them.
- **OPEN-5 (numerics).** The minimum-effect floor, the outlier threshold N, the NTP bound and the M0′ tolerance are numbers frozen in the prereg after B0 and A0, not guessed here.

## Changes from r1

| # | r1 | r2 | Ruling |
|---|---|---|---|
| 1 | One F13 row (actor plus node wiring). | **F13-C1 is its own row.** C2 and D are a gate statement only. | R1, R9 |
| 2 | C1 included GFS MOS and PFM polling. | C1 is the hourly LAMP archive and NBP/PFM/LAMP availability only. GFS MOS and PFM history are IEM backfills. | R1 |
| 3 | A2 HRRR, NAM ablation, MEX. | Cut. | R1 |
| 4 | B0 scaled the MDE from M1. | MDE from the empirical tape SD, plus a placebo feasibility check. | R1 |
| 5 | B1 primary was 6 tests, absolute change. | Model-free and CLI-free. Primary is 2 tests (PFM and NBP at the 60-min window), Holm over 2. Signed change on a fixed matched-rung panel, regressed on the forecast delta. | R2 |
| 6 | Nominal release times were acceptable. | Measured first public availability only. | R2 |
| 7 | One placebo type. | Three controls: same clock time on no-update days, METAR-offset match, and a pre-window. Dropout is reported per arm. | R2 |
| 8 | B2 outcome was drift. | Realised EV per take net of fee, slippage and margin. Lag curve at 0/30/60/120/300 s. Futility screen. | R3 |
| 9 | Blend extended `fit_hierarchical_emos`. | Champion untouched, byte-unchanged test. New fits via `crps_numerical`. M0′ equivalence control. | R4 |
| 10 | Normal EMOS. | Student-t with source-disagreement σ. The primary comparison has identical σ. | R4 |
| 11 | 3 % CRPS and 4 % RMSE acceptance. | A paired day-block LB > 0 plus a minimum-effect floor. RMSE descriptive. K = 1. Same sign in ≥ ⌈0.75·n⌉ folds. | R4 |
| 12 | Hard weight box [0.8, 1.2]. | Shrinkage toward a sum of 1. | R4 |
| 13 | Basis enum of three. | Adds `first_seen`. Availability is an interval. Mirror tags. The floor rule reuses `nbp_derived_store.py:142-153`. Lags frozen from ≥ 14 days of C1. | R5 |
| 14 | Edit the MOS products map. | A separate product table. `ArchiveRequest` keys frozen first. AFOS and LAV go through `PacedIemTransport`. Only MDL is new. Routing contract registered. | R6 |
| 15 | sha256 at `nbm_quantile_transport.py:439`. `nbp_derived_store` under `ingest/`. | `:449`. `src/breezy/persistence/nbp_derived_store.py:142-153`. `crps_normal` is an oracle. `find_order_sender_reference_violations` is not an import scan. | R6, §1 |
| 16 | Transport hardening was a general description. | H1–H5, M6, M8 and LOW, each with a named test. | R7 |
| 17 | The NO-SEND scope was an open question. | Decided: M6, a guard test under the no-egress gate. The firewall is untouched. | R7 |
| 18 | No veto analysis. | The blend as a veto on FQ-style takes (a pre-07-01 proxy, forward shadow only). Out of scope: the NO-side test and maker orders. Rejected: a Kalshi signal. OPEN-3. | R8 |
| 19 | D needed F1, F4, F5, F7b, AUT-3, row 7 and F12. B2 had to be positive. | Adds F6, the ARCH-0 owner, and the AUT-4 screen. The B2 gate is "not futile". | R9 |

Relevant paths (all under `/home/jon/breezy`):
- `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r1.md`
- `scripts/venue/iem_mos_probe_transport.py` (`PacedIemTransport` `:171-261`)
- `src/breezy/ingest/nbm_quantile_transport.py` (digest `:449`)
- `src/breezy/persistence/nbp_derived_store.py` (`:142-153`)
- `src/breezy/persistence/archive_cache.py` (`:59`, `:96`, `:393`)
- `src/breezy/analysis/nbp_calibration.py` (`crps_numerical` `:529`)
- `tests/contract/test_transport_error_routing_contract.py`
- `tests/unit/test_polymarket_us_write_transport.py` (`:92`)
- `tests/unit/test_execution_egress_firewall_guard.py` (`:1862`, `:2298`, `:4242`)
- `src/breezy/persistence/autonomy/capture_schedule.py`

I wrote no files.
