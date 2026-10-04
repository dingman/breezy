# FQ loss response, build spec r3 (consolidation of r2 + FQ-R13..R22)

Consolidated 2026-10-04 from `FQ-LOSS-RESPONSE_plan_r2.md` and its binding round-2 rulings FQ-R13..FQ-R22. Rulings FQ-R1..R12 from r1 still apply where nothing later supersedes them. Where rulings conflict, the latest one wins. This document makes no new decisions. Items marked **[OPEN]** are things the rulings leave undecided, for the peer loop to settle. Test names marked † were named during consolidation because the ruling required the behaviour but gave no name.

## CONFLICT notes (unresolved; I have not chosen between them)

- **CONFLICT-1: is shadow/live parity a gate before resume, or a check after it?**
  - FQ-R16 says "Shadow/live parity is a resume GATE".
  - FQ-R6 says shadow decides RESUME, and "Live real-order trials **then** validate fill realism and execution". r2 §6.2 (planner text) adds "live is never in the resume bar".
  - P5 and RC-5 mean v2 cannot send before F9, so no v2 live rows can exist when the resume decision is made. The only live FQ rows are v1's, and FQ-R4 says pre- and post-repair rows never share an α sequence. It does not say whether they may share a parity check.
  - Open question: which live rows feed the parity gate, or whether parity moves after arming. F9 cannot be specified until this is settled.
- **Fact discrepancy (not a conflict between rulings).**
  - FQ-R13 says to adopt `fad3e819`/`6b3ce675`. The coordinator's fact names `80323838` and `6b3ce675`.
  - Both objects exist under `.git/objects`, and branch `backlog/fq-halt-cli-2026-10-04` points at `6b3ce6755472…`.
  - This r3 cites the coordinator's pair. Whether `fad3e819` is the pre-rebase SHA is unverified.

## 0. Overview

FQ (`pm_us_crh_fq_v1`) is losing money, and the system can neither see the losses nor stop them.

The response does not build parallel machinery [FQ-R1]. It pulls early slices of AUT-2, AUT-4, AUT-5 and AUT-3 forward and adds four prerequisite rows [FQ-R2]:
- R-B v2 (the PREREG v2 amendment);
- the truth fetch;
- the interim stop bridge;
- the FQ v2 repair.

On v1:
- **Sending stops** at the 10-05 16:40–16:50Z node gap, by a halt set through the widened halt CLI, with an env backstop (coordinator fact).
- **Terminality** belongs to the v1 manifest's `terminal_climate_day` and the AUT-5 registry, never to the halt row [FQ-R13].
- The repaired model is a new family, v2 [FQ-R4].

**Primary winner-search path** is the model-free M1 market scan, which heads W3 [FQ-R14].

**End state** is the standing loop below, running with no human or agent commit [FQ-R10]. It is conditional on rows F12 and F13 [FQ-R21]:

M1 / AUT-S / AUT-3 generation → AUT-4 nomination on forward post-freeze days → capped live trial → AUT-5 promotion or demotion.

**Evidence class:** machinery proven, edge unproven, until an e-process crossing is filed.

## 1. Verified premises

P1–P24 are kept from r2 §1, with these amendments:
- **P4 is superseded.** The halt CLI widening is built (`80323838`, `6b3ce675`), and set, status and clear all accept `forecast_quantile_ladder` [FQ-R13]. Its full gate is running, and it merges before r3 is built.
- **P25 (path check, 10-04).**
  - `IEM_ALLOWED_HOSTS` is at `scripts/venue/iem_mos_probe_transport.py:53`.
  - `roi_bound.py` is at `src/breezy/settlement/roi_bound.py`.
  - `WIDENING_KINDS` is in `src/breezy/persistence/autonomy/transitions.py`.
  - `forecast_conditional_scoring.py` is at `scripts/analysis/`.
  - `src/breezy/analysis/plugins.py` is **absent** on `feat/data-capture-and-risk`. r2 called it EXISTING. **[OPEN]** Confirm which AUT-2 or AUT-4 WP creates it.
  - The v1 manifest has `live_orders_ruling` at line 19 and no `terminal_climate_day`.

## 2. RULING-CONFLICTs: amendments as ruled

- **RC-1, as amended by FQ-R20.**
  - C4 verdicts gain `test_kind ∈ {fixed_n, e_process}`, `eta_ns` and `window_end`.
  - `n_min_eff` is **not redefined**; it is `null` for `e_process`.
  - `test_nominee_single_look_never_reopened` is scoped to `fixed_n`.
  - `nomination_feasible` = MC power ≥ 0.8 within the window, and an infeasible nomination burns no K slot [FQ-R15].
  - α schedule per FQ-R15 (see §6.4). K_LIFETIME ≤ 4 stays as a ceiling.
  - E-15 is filed by F1 only [FQ-R19].
- **RC-2: unchanged.** N's variance and ρ̂ come from out-of-fold residuals on archive days before 2026-07-01. `open_holdout` is never called.
- **RC-3, as amended by FQ-R20.**
  - `evidence_row/v1` is an **in-memory typed adapter**, with `source` set from the store the row came from.
  - Every consumer has its own untagged and unknown-tag tests, plus a single-loader contract test.
  - `ref_ts < take_ts` is enforced at load.
  - C2 gains no column.
- **RC-4: REJECTED [FQ-R13].** It is replaced by the merged halt CLI widening:
  - set **and** clear both accept FQ;
  - an FQ set proceeds when positions are open;
  - clearing is human-only through the CLI, with an audit record.
- **RC-5, as amended by FQ-R20.**
  - A peer-reviewed `RULING_fq_v2_live_orders_<date>` is filed after the resume bar, plus one allowlist row for v2.
  - The AUT-5 r8 delta covers every `fq_v1` reference (19 in AUT-5, 28 in AUT-7).
  - F9 arms v2 through registry ROOT_ADMIT/RESUME.
  - The operator gives no input beyond the two caps.
- **RC-6, as amended by FQ-R20.** E-16 adds the model classes `density_table_multisource` and `variant_spec`.
  - `variant_spec` carries only parameters an FQ manifest can express. Cross-family variants go through new-family registration.
  - E-16 is filed by F1 only [FQ-R19].
- **RC-7, new [FQ-R17].**
  - AUT-5 grants an ownership carve-out for the composed veto in `_compose_forecast_quantile_ladder` (`src/breezy/app/trade.py`).
  - An AUT-5 r8 note records that WP5 rebases over it.

## 3. Step-0 diagnostics and STOP rules (row F0; read-only)

| ID | Diagnostic | Result / method | STOP rule |
|---|---|---|---|
| S0-1 | LAX p̂ 0.992 | **DONE 10-04: GENUINE** | Did not fire |
| S0-2 | MIA p̂ 0.6368 [FQ-R8] | **DONE 10-04.** NBM's own tight spread. W2's target is forecast-error variance | Did not fire |
| S0-3 | v1 halt state | **Halt row only [FQ-R13]**, read with `read_family_halt_rows_readonly` (`trial_day_latch.py:354`) after the halt set at the 10-05 16:40–16:50Z gap; env backstop (coordinator fact) | If the v1 halt row is absent after the 10-05 gap, STOP all other rows until the halt is set through the CLI. `terminal_climate_day` is **not** a send stop [FQ-R13] |
| S0-4 | NO-side funnel [FQ-R11] | Unchanged from r2 | Unchanged from r2 |
| S0-5 | Truth L-1 | Unchanged from r2 | Unchanged from r2 |
| S0-6 | Market scan | **Now slice M1, the head of W3 [FQ-R14]** (§4 W3) | (a) Validity STOP. (b) A surviving cell becomes an AUT-S candidate, with nomination on forward post-freeze days only. (c) Unchanged from r2 |

## 4. Workstreams as slices

**Conventions.** Unchanged from r2: the L-43 gate after every merge, the invariants in every brief, L-42 and L-55 fixture rules, and node respawn outside [16:30Z, 17:10Z).

Additions:
- **Timers.** No commit that carries a timer auto-enables. Units stay parked until the gate reads `EXIT=0` [FQ-R18]. The coordinator then symlinks, runs `daemon-reload` and `enable --now`, and records all three in the slice's evidence file [FQ-R12].
- **Post-respawn checks [FQ-R22].**
  - The permit is UNEXPIRED.
  - The `fq_live_orders enabled=` line is present.
  - `breezy-set-family-halt --status` is run for the sending family. It is now usable for FQ [FQ-R13].
- **Focused gates** include the firewall and exec-import-pin guards on every slice that touches FQ or exec.

### Built prerequisite (outside the queue): halt CLI widening

- **Branch:** `backlog/fq-halt-cli-2026-10-04`, commits `80323838` and `6b3ce675`. The full gate is running, and it merges before r3 is built.
- **Contents per FQ-R13:**
  - set and clear accept FQ;
  - `test_clear_fq_requires_audit_record_and_is_cli_only` replaces `test_clear_still_refuses_fq`.
- **[OPEN]** I could not confirm that this test is present on the branch. The coordinator should check it at merge.
- **Live path:** CLI only, no respawn. It is used to halt v1 at the 10-05 gap.

### W1: Measure

**F2 FQ-TRUTH [FQ-R5, FQ-R18]**

Acceptance:
- The AFOS CLI cache is filled daily for every venue station through D−1.
- The only egress is a GET to hosts in `IEM_ALLOWED_HOSTS`, following the `iem_mos_probe_transport` pattern.
- There is no venue credential, and only `alerts.env` is read.

Cache writes and revisions:
- Writes use flock, a temp file and an atomic rename.
- A body must parse to a CLI product. A body that fails to parse, or that reduces coverage, never replaces a valid revision.
- Each body's SHA is recorded.
- Each run uses a day-bounded URL keyed by fetch date. The reader takes the latest valid revision.

Writers and checks:
- The single-writer claim is scoped to AFOS CLI URLs. The legacy writers become cache-read-only for those paths.
- Results are cross-checked against the catalog CLI finals, with a disagreement flag.
- The dataset unit stays offline and writes an explicit coverage-gap field.
- No sandbox claim is made.

Files:
- NEW:
  - `scripts/archive/iem_cli_fetch.py`
  - `deploy/systemd/breezy-truth-fetch.{service,timer}`
  - `deploy/systemd/breezy-truth-dataset.{service,timer}` (`MemoryMax`, `RuntimeMaxSec`/`TimeoutStartSec`, `OnFailure=`)
  - `tests/unit/test_iem_cli_fetch.py`
  - `tests/unit/test_truth_units.py`
- EXISTING:
  - `scripts/analysis/settlement_alignment_study.py` (`fetch_text_cached` becomes read-only for AFOS CLI paths; P10, FQ-R18)
  - `scripts/venue/iem_mos_probe_transport.py` (import only)
  - `deploy/systemd/README.md` (unit row)
  - `tests/unit/test_probe_containment.py` (verify first; widen by one reviewed row only)

Tests:
- `test_fetch_get_only_to_iem_host`
- `test_fetch_reads_no_venue_or_operator_env`
- `test_fetch_is_single_cache_writer`
- `test_refetch_window_picks_latest_revision`
- `test_bad_body_never_becomes_latest` [FQ-R18]
- `test_dataset_never_fetches_cache_miss_refused`
- `test_truth_units_bounded_and_outside_launch_window`
- `test_coverage_gap_reported_not_zero`
- †`test_cache_write_is_flocked_atomic_rename`
- †`test_body_sha_recorded_and_catalog_disagreement_flagged`
- †`test_legacy_writers_cache_read_only_for_afos_cli`

Live path: no; no respawn or restart. Timer owner: coordinator, units parked until the gate reads `EXIT=0`.

**F4 AUT-2a-FQ [FQ-R1, FQ-R5, FQ-R11, FQ-R19]**

Scope: AUT-2 r7 WP0, WP1, WP2, WP3, WP5, WP6 **and WP8** [FQ-R19], with their RED lists taken verbatim.

Acceptance:
- `ForecastQuantileLadderScorer` labels every FQ fill on C2 `label/v1`.
- `portfolio_roi` prints `GATED_UNLABELLED_FQ` until labels land.
- Settlement-leg reconciliation runs per station.
- Realised P&L comes only from exec-store fills and settlement.
- **If the label job's peak memory exceeds 4G, WP6 holds until AUT-6** [FQ-R19].

Files:
- As in AUT-2 r7 WP0–WP6 and WP8.
- EXISTING: `scripts/analysis/portfolio_roi_report.py`, `scripts/analysis/position_monitor_nightly_report.py`, `deploy/systemd/README.md`.
- `src/breezy/analysis/plugins.py`: P25 **[OPEN]**.
- NEW:
  - `src/breezy/analysis/labeling/` (including `fq_scorer.py`)
  - `src/breezy/persistence/autonomy/{label_store,net_position}.py`
  - `src/breezy/runtime/venue_positions_read.py`
  - `deploy/systemd/breezy-label-outcomes.*`

Tests: the AUT-2 r7 RED lists, plus:
- `test_gated_unlabelled_fq_publishes_no_roi_figure`
- `tests/unit/test_aut2_net_position.py::test_no_leg_sign_reconciles_through_real_record_fill_writer`
- `tests/unit/test_aut2_reconcile.py::test_no_leg_venue_short_yes_sign_applied_before_compare`

Live path: no. Timer owner: coordinator (label unit, under the WP6 rule above).

### W2: Stop and repair

**F3 FQ-V1-TERM (shrunk) [FQ-R13]**

Acceptance:
- The v1 manifest carries `terminal_climate_day`. This is **tally closure only, not a send stop**.
- The halt key written by the real `record_policy_halt` is the same key `--status` reads.

Files:
- EXISTING: `deploy/families/pm_us_crh_fq_v1.json`.
- Test file: EXISTING `tests/unit/test_set_family_halt_cli.py` (additions only).
- Verify first: does any test pin the v1 manifest SHA (for example `test_fq_s8_registration_artefacts.py`)? If so, widen that pin by one reviewed row; never relax it.

Tests:
- `test_v1_manifest_terminal_day_parses`
- `test_fq_family_halt_key_matches_trade_preamble`

Live path: the manifest is read at boot, so a **node respawn** follows, with the post-respawn checks. Timer: none.

**F5 FQ-PREREG [FQ-R6, FQ-R7, FQ-R14, FQ-R15, FQ-R16]** (content in §6)

Acceptance:
- The amendment is filed through the peer loop.
- The design JSON is frozen at a 40-hex SHA.
- `prereg_precommit_check.py` exits 0.
- The N Monte-Carlo record is committed. It states the **n-starvation outcome** and **pre-registers the M1 fallback** [FQ-R14]. It also reports N as a function of δ_h and of the take-rate interval [FQ-R15].
- **E-15 and E-16 are not filed here** [FQ-R19].

Files:
- NEW:
  - `docs/evidence/RULING_prereg_v2_amendment_shadow_eprocess_<date>.md`
  - `docs/evidence/PREREG_FQ_v2_design_<date>.json`
  - `scripts/analysis/prereg_precommit_check.py`
  - `scripts/analysis/fq_resume_n_mc.py`
  - `tests/unit/test_prereg_precommit_check.py`
  - `tests/unit/test_fq_resume_n_mc.py`
  - `docs/evidence/AUT4_WP0_<date>.md`

Tests:
- `test_h0_mc_outcomes_bernoulli_exactly_at_be`
- `test_mc_replays_live_daily_loop_verbatim`
- `test_mc_includes_mixed_side_days`
- `test_n_uses_out_of_fold_pre_20260701_only`
- `test_mc_never_calls_open_holdout`
- †`test_h1_outcomes_from_delta_h_at_sampled_asks_residuals_only_for_rho_var`
- †`test_n_reported_over_delta_h_and_take_rate_interval`
- †`test_design_json_pins_ask_floor_ymax_haircut_theta_rounding`

Live path: no.

**F6 FQ-BRIDGE: interim stop (TEMPORARY BRIDGE) [FQ-R3, FQ-R17]**

Acceptance: an in-node probe reads `$STATE/derived/fq-loss-stop/latest.json` (`loss_stop/v1`) and gives one of three verdicts.
- **PASS:** no veto.
- **FAIL:** `record_policy_halt` (it sets only), a CRITICAL alert, and the entry veto.
- **UNKNOWN_STALE:** a CRITICAL on every probe. Past `STALE_VETO_H`, the entry veto applies, and that veto requires a delivered alert.

Integrity [FQ-R17]:
- The digest can be recomputed from the inputs: the C2 high-water mark and the truth SHA.
- Owner, mode and mtime are checked.
- `as_of` must be monotonic, held in memory.

Timing:
- The probe runs on an actor timer and caches its verdict. The veto reads the cache only.
- Any exception means UNKNOWN.

Composition:
- The composed veto evaluates the family halt **and** the loss stop on every call and returns the halt reason first.
- The same callable reaches both the strategy and the exec client.
- `strategy.py` is untouched.

Floor:
- Time-uniform, −c·√t, with a stated horizon.
- The window starts at the arming-ruling timestamp.
- It is venue-level and never reads pre-epoch `family_id` (P15). It is never derived from either cap.
- The fill-to-label lag is bounded only by the operator caps; this is stated without naming them.

Until F5's floor and F4's labels exist, the probe reads UNKNOWN and vetoes fail-closed. That follows from the "Needs F1 only" ordering [FQ-R17].

Retirement: on the **first accepted non-inert `live.drawdown` PASS**, with a named re-calibration trigger owner. **[OPEN]** The ruling does not name the owner. The retirement commit deletes the probe and its wiring.

Files:
- NEW:
  - `src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py`
  - `src/breezy/analysis/fq_loss_stop.py`
  - `deploy/systemd/breezy-fq-loss-stop.{service,timer}`
  - `tests/unit/test_fq_loss_stop_probe.py`
  - `tests/unit/test_fq_loss_stop_producer.py`
  - `tests/unit/test_app_trade_fq_loss_stop_wiring.py`
  - `tests/contract/test_loss_stop_schema_writer_reader_agree.py`
- EXISTING:
  - `src/breezy/app/trade.py` (`_compose_forecast_quantile_ladder` only; RC-7 carve-out)
  - `pyproject.toml` (console script)

Tests:
- `test_probe_never_references_clear`
- `test_fail_sets_policy_halt_through_real_latch`
- `test_stale_alerts_every_probe_then_vetoes_past_bound`
- `test_missing_artefact_is_unknown_never_pass`
- `test_schema_or_sha_mismatch_is_unknown`
- `test_probe_exception_is_unknown_not_pass` [FQ-R17]
- `test_producer_reads_no_family_id_of_pre_epoch_rows`
- `test_counter_increments_positive_control`
- `test_fq_has_no_exit_order_path`
- `test_floor_read_from_prereg_never_from_operator_controls`
- `test_production_default_paths`
- †`test_digest_recomputable_from_c2_hwm_and_truth_sha`
- †`test_owner_mode_mtime_checked_and_as_of_monotonic`
- †`test_veto_reads_cached_verdict_only`
- †`test_composed_veto_evaluates_both_returns_halt_first`
- †`test_same_veto_callable_reaches_strategy_and_exec_client`
- †`test_floor_time_uniform_from_arming_timestamp`
- †`test_stale_veto_requires_delivered_alert`

Live path: **yes**, a node respawn. The supervisor is not touched. Timer owner: coordinator.

**F7a AUT-4-EARLY-A: WP1 + WP2 [FQ-R19]**

Acceptance:
- AUT-4 r11 WP2 (pure core, `sample_size`) merges as written.
- **The rulings prefer an AUT-4 r12 delta that moves only `analysis/stats/*`.**
- If WP1 (the G36 move, cut set W1–W5) stays, it runs **strictly serially with AUT-5a WP5/WP6**.

Files: AUT-4 WP1/WP2 files (r11 `:1255-1263,1304`); under the preferred delta, `analysis/stats/*` only.

Tests: the AUT-4 r11 WP1/WP2 RED lists.

Live path:
- Stats-only delta: offline, no respawn.
- If WP1 stays (it touches `forecast_quantile_ladder/strategy.py` and `composition.py`): AUT-4's runbook applies. That means a supervisor restart in [01:00Z, 16:40Z), then the next boot, then the permit check.

Timer: none.

**F7b AUT-4-EARLY-B: e-process, e-LOND, `evidence_row`, `FqEvaluator` [FQ-R7, FQ-R15, FQ-R19, FQ-R20]**

Acceptance:
- The cores in §6 are built.
- `evidence_row/v1` per RC-3 as amended.
- `FqEvaluator` reuses the `forecast_conditional_scoring` functions. It computes:
  - BSS on takes and on all decisions;
  - per-rung-position PIT;
  - the reliability slope and Spiegelhalter Z, with a minimum sample, blocking on "insufficient";
  - net P&L per calendar day.
- C4 fields per RC-1 as amended.

Files:
- NEW:
  - `src/breezy/analysis/autonomy/{eprocess,confidence_sequence,elond,evidence_row,fq_evaluator}.py`
  - `tests/unit/autonomy/{test_eprocess,test_elond,test_evidence_row,test_fq_evaluator}.py`
- EXISTING or NEW: `src/breezy/analysis/plugins.py` (registration; P25 **[OPEN]**; serialised after F4).

Tests:
- `test_capital_nonnegative_bets_predictable`
- `test_h0_crossing_rate_le_alpha_exact_null`
- `test_cs_reject_only_when_ub_lt_0`
- `test_elond_equals_geometric_at_zero_discoveries` **[OPEN]**: this may not survive FQ-R15's heavy-tailed γ_t, so it needs peer reconciliation.
- `test_untagged_row_refused`
- `test_shadow_rows_never_enter_live_sequential`
- `test_backtest_rows_reject_only`
- `test_bss_on_takes_uses_ask_comparator`
- `test_bootstrap_clusters_by_calendar_day`
- `test_pit_per_rung_position`
- `test_nominee_single_look_never_reopened` (scoped to `fixed_n`)
- †`test_lambda_uses_settled_days_only_denominator_fixed_at_decision`
- †`test_alpha_frozen_at_test_start_per_lineage_no_pooling`
- †`test_gamma_heavy_tailed_normalised`
- †`test_cs_range_normalised_kill_side_lambda_usable`
- †`test_calibration_guard_insufficient_blocks`
- †`test_infeasible_nomination_burns_no_k_slot`
- †`test_c4_e_process_n_min_eff_null_with_eta_ns_window_end`
- †`test_evidence_row_single_loader_contract`
- †`test_ref_ts_lt_take_ts_enforced_at_load`
- per-consumer `test_<consumer>_refuses_untagged` and `test_<consumer>_refuses_unknown_tag`

Live path: no (offline modules). Timer: none.

**F8 FQ-V2: repair as a new family, shadow only [FQ-R4, FQ-R7, FQ-R8, FQ-R11, FQ-R22]**

Acceptance:
1. `pm_us_crh_fq_v2` is REGISTERED with no `live_orders_ruling`. Its d0 falls after the design-freeze SHA, so the 5 losing days are excluded.
2. **Regime-aware variance.** A causal per-station bias and inflation term is computed at boot from catalog CLI finals.
   - Assert that the boot day equals the decision day [FQ-R22].
   - k and the half-life are tuned by rolling-origin CRPS that replicates live CLI latency, uses nested out-of-fold, and states its season window. The data are archive days before 2026-07-01 [FQ-R22, RC-2].
   - The values are pinned in the design JSON, with no live refit.
   - PIT 80% coverage must fall in [0.75, 0.85].
3. **Surprise gate.** It is registered as an α-spending variant and defaults to OFF, with its take-rate cost pre-registered [FQ-R22]. It is weather-only. The ev_net-outlier form is allowed only as a cost filter.
4. **RISK LIMIT.** One rung per station-day, chosen by max-net-edge at one snapshot. It is simulated in shadow and binds live only after AUT-5a.
5. NO-side wiring is built only if S0-4 requires it.

Files:
- NEW:
  - `deploy/families/pm_us_crh_fq_v2.json`
  - `deploy/families/artefacts/<v2 density artefact>`
  - `deploy/families/artefacts/eprocess_design_pm_us_crh_fq_v2.json`
  - `src/breezy/strategy/forecast_quantile_ladder/{regime_inflation,forecast_surprise}.py`
  - `tests/strategy/forecast_quantile_ladder/{test_regime_inflation,test_forecast_surprise,test_v2_manifest}.py`
- EXISTING:
  - `src/breezy/analysis/nbp_calibration.py`
  - `src/breezy/strategy/forecast_quantile_ladder/{artefact_bounds,decision,composition}.py`

Tests:
- `test_regime_term_causal_only_days_before_decision`
- `test_regime_params_pinned_from_pre_20260701_archive`
- `test_ask_never_enters_p_hat`
- `test_surprise_gate_reads_no_venue_field`
- `test_v2_without_ruling_never_sends`
- `test_existing_check_order_pin_extended`
- `test_v1_rows_never_in_v2_sequence`
- †`test_boot_day_equals_decision_day`
- †`test_crps_tuning_replicates_cli_latency_nested_oof`
- †`test_surprise_gate_default_off`
- firewall and exec-pin guards

Live path: **yes**. A node respawn, and the sending family changes to v2 shadow. If the env is in the symlinked supervisor unit, a supervisor restart in [01:00Z, 16:40Z) is also needed. Post-respawn checks per FQ-R22. Timer: none.

**F9 FQ-V2-RESUME: decided by the bar alone [FQ-R7, FQ-R15, FQ-R16, FQ-R20]**

Acceptance:
- The bar (§6.5) is evaluated on `source=shadow` C1 records, combined as min(e_a, e_b), with the calibration guard and the parity gate. **The parity gate's rows are unresolved: CONFLICT-1.**
- The coordinator then files the RC-5 ruling and allowlist row.
- v2 is armed through registry ROOT_ADMIT/RESUME into a capped LIVE_SEQUENTIAL trial.
- No v1 halt is cleared.

Files:
- NEW: `docs/evidence/RULING_fq_v2_live_orders_<date>.md`
- EXISTING:
  - `src/breezy/persistence/live_orders_gate.py` (one reviewed allowlist row)
  - `deploy/families/pm_us_crh_fq_v2.json` (`live_orders_ruling`)

Tests: †`test_v2_allowlist_row_single_reviewed`, plus the existing `live_orders_gate` tests unchanged.

Live path: allowlist and manifest change, then a node respawn and the post-respawn checks. Timer: none.

### W3: Standing search loop [FQ-R10, FQ-R14]

**M1 MARKET-SCAN: the head of W3 and the primary winner-search path [FQ-R9, FQ-R14]**

Purpose: a model-free, n-rich scan over all rungs × sides × days. Shadow adds no n, because it evaluates the same Takes [FQ-R14].

Method:
- Cells are (side, ask bin). The value per cell is realised − (ask + fee).
- The ask is the Depth10 best ask in a fixed hour window, scoped by date **and** hour. `ref.ts < settlement` is asserted.
- Calendar-day block bootstrap, with B and the seed from `src/breezy/settlement/roi_bound.py:93,97`. Binning reuses `scripts/analysis/forecast_conditional_scoring.py:303`.

Multiplicity control [FQ-R14]:
- Across all cells: a Hansen SPA (reality-check) p-value, and a Bonferroni-adjusted per-cell lower bound.
- **[OPEN]** The ruling text is "SPA/Bonferroni". The design JSON must pin which one decides survival, or require both.
- The scan spends no α.

Forward-freeze rule for nomination [FQ-R14]:
- Scan data **never** doubles as nomination evidence.
- Surviving cell specs are frozen at a committed SHA. Nomination evidence is only forward climate days strictly after that freeze.
- A survivor enters AUT-S as a candidate (`variant_spec`, manifest-expressible only [FQ-R20]) and α is charged only at the C5 nomination.
- No cell is ever traded directly.

STOP rules (S0-6):
- (a) If a look-ahead assert fails or join coverage is below 95%, no conclusion is drawn.
- (c) If every cell's UB ≤ 0 and the model is worse than the market, F8 is capped at the regime variant and effort goes to new-information search.

Outputs:
- A per-cell table: n, mean, CI, adjusted LB/UB, survivor flag.
- The SPA p-value.
- Join coverage and the validity flag.
- The frozen survivor-spec SHA.
- The S0-6 (b)/(c) outcome.
- A pointer consumed by F5's N record (the fallback).
- **[OPEN]** The evidence-file path is not specified.

Files:
- NEW: `scripts/analysis/market_calibration_scan.py`, `tests/unit/test_market_calibration_scan.py`.

Tests:
- `test_scan_scopes_windows_by_date_and_hour`
- `test_scan_asserts_ref_ts_lt_settlement`
- `test_scan_uses_depth10_ask_not_quote_tick`
- `test_scan_bootstrap_by_calendar_day`
- `test_scan_reports_join_coverage`
- `test_scan_reads_no_model_output`
- †`test_scan_reports_spa_and_bonferroni`
- †`test_scan_spends_no_alpha`
- †`test_survivor_spec_frozen_before_forward_days`
- †`test_scan_days_never_enter_nomination_evidence`

Needs: carried on the F0 row, since no ruling adds a separate row. First read uses truth to 09-28; it is re-run after F2.

Live path: no. Timer: none. A standing schedule is not ruled **[OPEN]**.

**F10 AUT-S-PLAN.**
- The r2 grammar and controls are kept, including survivors minted as `variant_spec` that is manifest-expressible only [FQ-R20].
- It ingests M1 survivors under the forward-freeze rule [FQ-R14].
- Files: `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r1.md` only.

**F11 AUT-S-BUILD.**
- Files and tests as in r2:
  - NEW: `src/breezy/analysis/autonomy/search/{grammar,generator,screen,spa}.py`, `deploy/systemd/breezy-autonomy-search.{service,timer}`.
  - EXISTING: `src/breezy/runtime/backtest_harness.py` (statistics registration only).
- Tests:
  - `test_generator_deterministic_and_k_capped`
  - `test_screen_schema_has_no_win_token`
  - `test_screen_rejects_only_ub_lt_0`
  - `test_screen_refuses_non_replay_sufficient_day`
  - `test_screen_rows_source_backtest`
  - `test_spa_pvalue_reported`
  - `test_screen_spends_no_alpha`
  - `test_register_statistic_parity_with_fq_evaluator`
- Live path: no.
- Timer owner: coordinator, with the studies flock, `MemoryMax`, a stall watch, and parking until `EXIT=0`.

**F12 FQ-PROMOTE-ENABLE (new row) [FQ-R21].**
- Enables PROMOTE through AUT-5 L2 `WIDENING_KINDS`.
- Files: EXISTING `src/breezy/persistence/autonomy/transitions.py`. Tests: **[OPEN]**, per the AUT-5 L2 plan.
- Live path: the engine transition set. The respawn or restart effect is **[OPEN]**. Timer: none.

**F13 FQ-SRC-INGEST (new row) [FQ-R21].**
- A new US weather source ingest actor plus node wiring [FQ-R10, memory `prediction-from-weather-venues-for-cost`], minted as `density_table_multisource` (E-16).
- Files:
  - Node wiring: `src/breezy/app/trade.py`, owned by row 7 (AUT-5a).
  - Actor module and tests: **[OPEN]**, not named by any ruling.
- Live path: **yes**, a node respawn. Timer owner: coordinator.

**AUT-3 new source:** row 13 is unchanged. Its gate "or a new source exists" is met through F13.

## 5. AUTONOMY QUEUE (corrected; acyclic)

Rows 1–8 and 11–13 keep their Needs. The token `5@WP5s3` is a **literal status string** [FQ-R19]. Token `E-15` and token `E-16` are satisfied only by F1 filing them [FQ-R19].

| # | ID | Work | Needs | Status |
|---|---|---|---|---|
| F0 | FQ-STEP0 | RUN S0-1..S0-6 read-only; M1 scan committed (LAX, MIA DONE 10-04) | — | IN PROGRESS |
| F1 | FQ-PLAN | PLAN r3 → peer loop; file E-15/E-16; AUT-4 r12, AUT-5 r8 deltas | F0 | OPEN |
| F2 | FQ-TRUTH | BUILD IEM CLI fetch + dataset units | 5@WP5s3, F1 | OPEN |
| F3 | FQ-V1-TERM | BUILD v1 `terminal_climate_day` + halt-key test | F1 | OPEN |
| F4 | AUT-2a-FQ | BUILD AUT-2 WP0,1,2,3,5,6,8 + NO leg-sign tests | 4, 5@WP5s3, F1 | OPEN |
| F5 | FQ-PREREG | PLAN+RUN PREREG v2 amendment, R-B v2, AUT-4 WP0/WP7a, N MC | F0, F1 | OPEN |
| F6 | FQ-BRIDGE | BUILD interim stop (TEMPORARY) | F1 | OPEN |
| F7a | AUT-4-EARLY-A | BUILD AUT-4 WP1+WP2 (prefer stats-only delta) | F1 | OPEN |
| F7b | AUT-4-EARLY-B | BUILD e-process/e-LOND/`evidence_row`/`FqEvaluator` | E-15, F4, F7a | OPEN |
| F8 | FQ-V2 | BUILD v2 family, shadow only | F5, F7a, F7b | OPEN |
| F9 | FQ-V2-RESUME | RUN resume bar → RC-5 ruling → capped live trial | F8, 8, F6 | GATED |
| F10 | AUT-S-PLAN | PLAN AUT-S | F1 | OPEN |
| F11 | AUT-S | BUILD search + screen + unit | F10, F7b, E-16 | OPEN |
| 9 | AUT-2 | BUILD AUT-2 remainder (2b, WP7, WP9) | 3, 8, F4 | OPEN |
| 10 | AUT-4 | BUILD AUT-4 remainder (WP3–WP9; + WP1 if F7a is stats-only) | 9, F7a | OPEN |
| F12 | FQ-PROMOTE-ENABLE | BUILD AUT-5 L2 `WIDENING_KINDS` PROMOTE enable | 11 | OPEN |
| F13 | FQ-SRC-INGEST | BUILD new US source ingest actor + node wiring | F1, E-16, 7 | OPEN |

Notes on the table:
- **F8.** r2's "F7" is translated to F7a + F7b by the split [FQ-R19]. S0-5 is reached transitively through F5 → F0.
- **F11.** "F7" is likewise translated to F7b, which already Needs F7a.
- **F12 and F13** are new rows [FQ-R21], but no ruling gives their Needs. The values shown are derived from cited facts and **[OPEN]** for the peer loop:
  - F12 Needs 11, because row 11 reads "PROMOTE stays off".
  - F13 Needs 7 because row 7 owns `app/trade.py`, and Needs E-16 for `density_table_multisource`.
- **Acyclicity check.** The Needs chains, read left to right:
  - F0 → F1 → {F2, F3, F5, F6, F7a, F10}
  - F4 → {F7b, 9}
  - F7a → {F7b, 10}
  - F7b → {F8, F11}
  - 8 → {F9, 9}
  - 9 → 10 → {11, 13}
  - 11 → {12, F12}
  - 7 → {8, F13}
  - No row Needs a descendant of itself.
- **Placement:** F0 and F1 sit above row 3. F2–F7b sit after row 5. F8–F9 sit after row 8. F10 sits after F1. F11 sits after row 10. F12 sits after row 11. F13 sits after row 7. Each row text is ≤ 120 characters [P20].
- **Row 7 text** gains: "+ RC-7 carve-out; retires F6 on first accepted non-inert live.drawdown PASS" [FQ-R17].

## 6. PREREG v2 amendment: content (F5)

1. **Scope [FQ-R6].** Shadow at the executable ask counts for SCREENING and RESUME only. Backtest only rejects.
   - The timing of fill-realism validation is in CONFLICT-1.
   - n-starvation: at ≤ 1 take/day, the e-process confirms only an ROI edge of about 50% or more before KILL. That is stated, and M1 is the pre-registered fallback [FQ-R14].
2. **Source tag** per RC-3 as amended. Shadow eligibility [FQ-R16]:
   - a C1 Take with a Depth10 best ask of size ≥ 1, at qty 1;
   - a pre-registered **haircut** on `ask_exec` (one tick, or a miss rate);
   - θ and rounding **pinned by day**, failing closed on drift;
   - **NO-side Takes with an empty YES bid are ineligible**;
   - the risk limit is simulated.

   Mixing ban: shadow is never in LIVE_SEQUENTIAL, and backtest is used only for screen rejection. The live/resume-bar clause is subject to CONFLICT-1.
3. **E-process [FQ-R7, FQ-R15].**
   - The unit is the calendar day: Y_t = Σ(h−BE)/ΣBE, with BE = ask + fee.
   - An **ask floor** and **Y_max** are pinned in the design JSON, and the CS range is normalised so the KILL side has usable λ.
   - **Filtration:** λ_t uses settled days only, and the denominator is fixed at decision time.
   - Capital is K_t = Π(1 + λ_s·Y_s), with λ ∈ [0, λ_max ≤ 0.5]. The betting rule is pinned.
   - WIN when K_t ≥ 1/α_k. KILL only when the hedged CS has UB < 0.
   - The BSS-on-takes CS uses the ask as comparator.
   - Validation: an exact-null Monte-Carlo (L-41), replaying the live loop verbatim (L-40 ii), with mixed-side days included (L-40 i).
4. **Online FDR [RC-1, FQ-R15].**
   - e-LOND, run **per lineage, with no pooling**.
   - γ_t is heavy-tailed, ∝ 1/(t·log²(t+1)) normalised, or uses per-epoch budgets.
   - α_t is **frozen at test start**, using R at that moment. α = 0.025, and K_LIFETIME ≤ 4 is a ceiling.
   - Screening, M1 and AUT-S spend no α; α is charged at C5 nomination.
   - FDR replaces FWER for this programme.
5. **Resume bar.** All of the following are required:
   - (a) the shadow net-P&L CS LB > 0 at the haircut ask;
   - (b) the BSS-on-takes CS LB > 0;
   - (a) and (b) are combined as **min(e_a, e_b)** [FQ-R15];
   - (c) the calibration guard, with a **minimum sample, blocking on insufficient**;
   - (d) the **shadow/live parity gate** [FQ-R16], per CONFLICT-1.

   Only climate days after v2 d0 count, and d0 falls after the freeze.
6. **N [RC-2, FQ-R15].**
   - Residuals are used only for ρ̂ and the variance. Under H1, outcomes are generated from δ_h at the sampled asks.
   - δ_h is a pinned design effect with a stated rationale.
   - N is reported over δ_h and the take-rate interval. It is used for the earliest look in (c), the ETA against the 2027-01-25 KILL, and `nomination_feasible` (MC power ≥ 0.8).
   - The record states the n-starvation outcome and the M1 fallback.
7. **Bridge floor [FQ-R17].** Time-uniform −c·√t with a stated horizon, starting at the arming-ruling timestamp. It is calibrated by an H0 Monte-Carlo, derived from no cap, and names no cap variable.
8. **Live trial.** v2 LIVE_SEQUENTIAL runs on `source=live` rows that are C2-admissible, under its own α.

## 7. Disjoint parallel groups (re-derived from the §5 Needs)

| Wave | Groups in parallel | Shared files → order |
|---|---|---|
| A | {F0/M1} ∥ {F1} ∥ {F10} | none |
| B | {F2} ∥ {F3} ∥ {F4} ∥ {F5} ∥ {F6} ∥ {F7a} | `deploy/systemd/README.md`: F4, then F2, then F6, append-only. `pyproject.toml`: F6 first. `app/trade.py`: F6 only, before row 7 (RC-7). F7a with WP1 → `fq/{strategy,composition}.py`: serial with AUT-5a WP5/WP6 |
| C | {F7b} | `plugins.py`: F4 then F7b. `pyproject.toml`: F6 then F7b |
| D | {F8} ∥ {F11} | F8 runs after F7a on `composition.py`. F8 against AUT-5a WP5 and AUT-3 WP2 is strictly serial: whichever lands second rebases and runs the full gate |
| E | {F9} ∥ {F12} ∥ {F13} | `app/trade.py`: F13 after row 7 |

## 8. Trade-offs

The r2 trade-offs are kept, except:
- The bridge composition now evaluates both parts on every call [FQ-R17].
- "Waiting for AUT-1b" stands, and F9 Needs 8.
- Added: **M1 as the primary path against the e-process on Takes.** M1 is n-rich but needs forward-frozen confirmation. The Takes e-process is n-starved, at about 50% ROI detectability [FQ-R14].

## 9. Risk register (changes from r2)

| Risk | Sev | Mitigation |
|---|---|---|
| v1 sends until the 10-05 16:40–16:50Z gap | CRIT | Halt set through the CLI at the gap, with env backstop; S0-3 checks the halt row (coordinator fact, FQ-R13) |
| Clear path now accepts FQ | HIGH | `test_clear_fq_requires_audit_record_and_is_cli_only`; human-only CLI; audit record; `test_probe_never_references_clear` [FQ-R13] |
| Bridge reports a stale PASS, or is forged | HIGH | Recomputable digest, owner/mode/mtime, monotonic `as_of`, UNKNOWN on exception, alert-gated veto [FQ-R17] |
| e-process has no usable KILL side | HIGH | Pinned ask floor and Y_max, normalised CS range [FQ-R15] |
| n-starvation (≤ 1 take/day) | HIGH | M1 as primary; fallback pre-registered in F5 [FQ-R14] |
| Shadow optimism | MED | Haircut, θ pinned by day, NO/empty-bid ineligibility, parity gate (CONFLICT-1) [FQ-R16] |
| Label job memory | MED | WP6 holds until AUT-6 if peak > 4G [FQ-R19] |
| Timer auto-enabled on a red gate | MED | Units parked until `EXIT=0` [FQ-R18] |

The r2 rows "v1 can still send today (unverified)" and "CLI widening widens the clear path / `test_clear_still_refuses_fq`" are deleted [FQ-R13]. All other r2 rows are kept.

## 10. Success criteria: the standing loop running (FQ-R10; conditional per FQ-R21)

**These criteria can only be met once rows F12 (PROMOTE enable) and F13 (new-source ingest) are DONE [FQ-R21].** The PROMOTE, LIVE_SEQUENTIAL-on-champion and AUT-3-multisource lines below depend on them. Until both rows are DONE, the loop's end state is not claimed. The conditions are scored by an independent reviewer from artefacts, over one 14-day window with zero human or agent commits inside the loop. The README live-proof window rule applies.

- [ ] **M1** survivors are frozen at a SHA, and nomination used only forward post-freeze days [FQ-R14].
- [ ] **AUT-S** ran nightly, with usable days, reject-only outcomes (UB < 0), the SPA p-value and no α change.
- [ ] **AUT-3** refit included `density_table_multisource` and was lineage-complete. AUT-4 consumed every record. *(Conditional on F13.)*
- [ ] **AUT-4** gave an OFFLINE_CHALLENGER verdict per candidate within 24 h, and the engine consumed it.
- [ ] **Nomination.** The C5 row's α_k equals the per-lineage e-LOND value frozen at test start, and infeasible nominations burned no K slot. If no real candidate passed, the AUT-7b drill stands in, with that disclosed.
- [ ] **FORWARD_SHADOW** verdicts were written daily from `source=shadow` rows. An injected untagged row was refused, with the alert delivered.
- [ ] **PROMOTE.** CHALLENGER→CHAMPION was executed by the engine. The node picked it up at LAUNCH (permit line), and the first fill was labelled within 24 h. *(Conditional on F12.)*
- [ ] **LIVE_SEQUENTIAL** ran daily on the champion. A real or injected UB < 0 produced a DEMOTE. *(Conditional on F12.)*
- [ ] **Drawdown.** The first accepted non-inert `live.drawdown` PASS occurred and F6 was retired. Otherwise the bridge is live, with its positive control shown [FQ-R17].
- [ ] **Halt clearing never automated.** AST tests are green, zero clear events came from any unit, and every clear carries a CLI audit record [FQ-R13].
- [ ] **Gate.** Every merge shows a full gate with `EXIT=0` and `lint-imports` reporting "N kept, 0 broken".

Key paths:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r2.md`
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r1.md`
- `/home/jon/breezy/scripts/venue/iem_mos_probe_transport.py`
- `/home/jon/breezy/src/breezy/persistence/autonomy/transitions.py`
- `/home/jon/breezy/src/breezy/settlement/roi_bound.py`
- `/home/jon/breezy/scripts/analysis/forecast_conditional_scoring.py`
- `/home/jon/breezy/deploy/families/pm_us_crh_fq_v1.json`
- `/home/jon/breezy/src/breezy/app/trade.py`

---

## Coordinator rulings on r3 CONFLICT and OPEN items (2026-10-04; binding)
- **FQ-R23, CONFLICT-1.** The resume decision uses the shadow bar (a) to (c) only. Shadow/live parity (d) is a gate on CONTINUING the capped live trial: v2 is armed under the caps, and the parity check runs on v2's own early live fills. If parity fails at the pre-registered look, DEMOTE (AUT-5) or apply the F6 veto. v1 rows never feed v2 parity.
- **FQ-R24, SHAs.** The halt CLI merged as `ce0c07bb` and `04eaa013`. `test_clear_fq_requires_audit_record_and_is_cli_only` is added in F3 if it is absent from the merged tests.
- **FQ-R25, `plugins.py`.** It is created by the first slice that needs it (F4, which follows AUT-2 r7's naming). F7b registers into it.
- **FQ-R26, the `elond` test.** `test_elond_equals_geometric_at_zero_discoveries` is replaced by `test_elond_alpha_matches_pinned_gamma_schedule`.
- **FQ-R27, M1 survival.**
  - A cell survives only if BOTH hold: its Bonferroni-adjusted LB > 0, and the SPA p-value < 0.05 (screening level, spends no α).
  - Evidence goes to `docs/evidence/M1_MARKET_SCAN_<date>.md`, with the JSON beside it.
  - A standing nightly schedule follows after F2, timer owner coordinator.
- **FQ-R28, owners and planning.**
  - The F6 retirement and re-calibration trigger owner is the AUT-5a row owner (coordinator).
  - F12's tests and F13's actor module are planned inside their own rows: PLAN first, then the peer loop.
  - The F12/F13 Needs, as derived, are accepted.
