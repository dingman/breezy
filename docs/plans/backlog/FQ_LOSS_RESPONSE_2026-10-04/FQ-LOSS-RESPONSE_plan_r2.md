# FQ loss response, plan r2

Planner draft, 2026-10-04. It replaces r1 and designs in rulings FQ-R1..FQ-R12 and the coordinator's Step-0 evidence of 10-04. Nothing has been built. This plan goes to the peer loop.

## 0. Overview

FQ (`pm_us_crh_fq_v1`) is losing, and the system can neither see the losses nor stop them. r2 does not build parallel machinery. It pulls early slices of AUT-2, AUT-4, AUT-5 and AUT-3 forward and adds four true-prerequisite rows (FQ-R2):
- **R-B v2**, the PREREG v2 amendment;
- **truth fetch**;
- **interim stop bridge**;
- **FQ v2 repair**.

FQ v1 goes terminal. The repaired model is a new family, v2 (FQ-R4). The plan's end state is the standing loop of FQ-R10, which runs with no human or agent commit:

AUT-S/AUT-3 generation → AUT-4 nomination → capped live trial → AUT-5 promotion/demotion.

**Evidence class throughout:** machinery proven, edge unproven, until an e-process crossing is filed.

## 1. Verified premises (file:line)

| # | Premise | Evidence |
|---|---|---|
| P1 | The fee-drift halt is a durable `record_policy_halt` reached through a closure in the node | `src/breezy/app/trade.py:461-476` |
| P2 | `record_policy_halt` is idempotent, first cause wins, and it is "Cleared only by `clear_family_halt` via the operator CLI" | `trial_day_latch.py:1155-1191` |
| P3 | FQ has a single `submit_veto` slot, run after the permit check and before `fee_verified` | `strategy.py:629-644`; that slot is today's family-halt veto (`trade.py:506-543`) |
| P4 | The set and status CLI refuses any manifest whose kind is not `continuous_rung_hold`, so `--status` cannot read FQ | `family_id_arg.py:38-41`, called at `set_family_halt_cli.py:390-394` |
| P5 | The live-orders allowlist holds exactly one row, for `pm_us_crh_fq_v1`; any other family is refused `not_allowlisted` | `live_orders_gate.py:80-88,193-206` |
| P6 | Manifests support `terminal_climate_day` | `family_manifest.py:250-253,394-411` |
| P7 | A shadow Take line has no ask and no depth, and a non-Take line has no `p_hat`. Shadow evidence at the executable ask therefore needs C1 records (AUT-1b). The log-field route was dropped by FQ-R11 | `strategy.py:603-627` |
| P8 | The funnel counts are keyed (station, side, kind, reason) | `decision_funnel.py:52-93` |
| P9 | `settlement_truth_dataset.py` is offline: a cache miss is a refusal | `:11-14` |
| P10 | `fetch_text_cached` caches per URL forever | `settlement_alignment_study.py:359-371` |
| P11 | The AUT-1a settlement writer reads the catalog CLI and fetches nothing | `capture_settlement.py:3-7`; AUT-1 r12 `:860-866` |
| P12 | The holdout `[2026-07-01, 2026-10-02)` is sealed for one confirmatory use, and changing it is an ARCH change | `RULING_holdout_freeze_and_forward_window_2026-10-03.md:5-8,14` |
| P13 | Today the AUT-4 nomination α is geometric, α_k = α·2^−k_life, with K_LIFETIME 4. Every nomination is infeasible (n_min_eff ≥ 403 > n_cap 89) | AUT-4 r11 `:561-568,581` |
| P14 | FORWARD_SHADOW is single-look; LIVE_SEQUENTIAL is LD-OBF | AUT-4 r11 `:605-610`, `:587` |
| P15 | AUT-2a rows are pre-epoch `unattributed` and never admissible; `family_id` on a `decision_id=null` row is a storage key only (AST test) | AUT-2 r7 `:589,:653` |
| P16 | C2 `label/v1` is exact, and AUT-2 adds no column | AUT-2 r7 `:63,:636` |
| P17 | AUT-5's `entry_veto` slot is in WP5, the drawdown producer is in WP11, and the producer may be filed `halt_inert` | AUT-5 r7 `:414,:79,:782` |
| P18 | AUT-5 WP9's lineage allowlist row literally names `pm_us_crh_fq_v1` | AUT-5 r7 `:926` |
| P19 | ARCH C3 lists exactly two FQ model classes, `density_table` and `rung_recalibration` | AUT-3 r6 `:42,:61-67` |
| P20 | PROGRESS has a hard budget of 250 lines / 12 KB, and the AUTONOMY QUEUE Needs column is binding | `PROGRESS.md:9,61-77` |
| P21 | L-40 amendment: (i) a mixed-side day has Var_H0 = S − (q_y − q_n)² ≤ 1; (ii) a validation Monte-Carlo replays the live look loop verbatim | `LESSONS.md:1399-1401` |
| P22 | L-41: the H0 simulation is the registered null verbatim | `LESSONS.md:1414` |
| P23 | L-38: a stop is MISSING until a positive control shows its counter increments | `LESSONS.md:1362-1366` |
| P24 | **Step-0 evidence, coordinator 10-04.** I have not re-verified it; the coordinator ran `scratchpad/loss-triage/lax/recompute.py` | see the coordinator message |

## 2. RULING-CONFLICTs (each with a proposed amendment; all go to the peer loop)

- **RC-1 (FQ-R7 against ARCH C4/C5 and AUT-4 r11).**
  - **Conflict.** e-processes and e-LOND replace single-look FORWARD_SHADOW, LD-OBF LIVE_SEQUENTIAL and the ALPHA-decision bookkeeping (P13, P14). Those are frozen in ARCH Rev 9.2 and AUT-4 r11.
  - **Amendment E-15.** C4 verdicts gain `test_kind ∈ {fixed_n, e_process}`.
  - For `e_process`, `n_min_eff` becomes the residual-derived projected look floor (§6.6), and `nomination_feasible` becomes `eta ≤ window_end`.
  - α_k = e-LOND(γ_k = 2^−k, discoveries). With zero discoveries this equals today's α_total·2^−k_life exactly.
  - K_LIFETIME ≤ 4 is kept as a ceiling.
  - Followed by AUT-4 r12 and AUT-5 r8 deltas.
- **RC-2 (FQ-R7 "N from holdout residuals" against P12).**
  - **Conflict.** Reading residuals inside the sealed holdout spends its single use.
  - **Amendment.** N comes from **out-of-fold** residuals on archive days before 2026-07-01, the same source AUT-4 WP0 (xi) already uses.
  - The contaminated window `[07-01, 10-01)` may be reported as a disclosed sensitivity only.
  - `open_holdout` is never called.
- **RC-3 (FQ-R6 "every line carries `source`" against P16).**
  - **Conflict.** C2 cannot gain a column without an ARCH change.
  - **Amendment.** C2 rows are `source=live` by construction (canary and drill rows already live in separate stores). The tag lives on a new evaluator input record, `evidence_row/v1`, which is the union boundary. Every reader of that record fails closed when the tag is absent.
  - Shadow and backtest records are born tagged.
- **RC-4 (FQ-R12 "`--status` check of the halt after each respawn" against P4).**
  - **Conflict.** The CLI refuses FQ.
  - **Amendment.** L-12 widening by one reviewed row: the set and status paths accept `forecast_quantile_ladder`.
  - The clear path stays restricted to CRH, so an FQ durable halt is terminal for that family. That matches FQ-R3 ("clearing human-only") and AUT-5 TERMINAL semantics.
- **RC-5 (FQ-R4 against P5 and P18).**
  - **Conflict.** v2 as a new root can never send. The allowlist names only v1, and AUT-5 WP9's single lineage row names v1.
  - **Amendment.**
    - A peer-reviewed `RULING_fq_v2_live_orders_<date>` scoped by the operator's 10-01 FQ ruling (current caps), filed only after the v2 resume bar passes (F9).
    - One reviewed allowlist row for v2.
    - AUT-5 r8 retargets the WP9 lineage row to the v2 root.
  - The operator gives no input beyond the two caps (memory `operator-controls-are-budget-and-position`).
- **RC-6 (FQ-R10 new weather sources and AUT-S variants against P19).**
  - **Conflict.** C3 admits only two FQ model classes, so neither a new source nor an AUT-S variant spec can be minted.
  - **Amendment E-16.** Add the model classes `forecast_quantile_ladder:density_table_multisource` and `forecast_quantile_ladder:variant_spec`, both written by AUT-3's `c3_writer`. The rule of 1 mint per lineage per day is unchanged.

## 3. Step-0 diagnostics and STOP rules (row F0; read-only)

| ID | Diagnostic | Result / method | STOP rule |
|---|---|---|---|
| S0-1 | LAX p̂ 0.992 | **DONE 10-04: GENUINE.** Recomputed exactly; vector from NBM 13Z, 44 s before the take; F(96.5) direction correct (P24) | LEAK or INPUT_DEFECT would block W2. **Did not fire.** |
| S0-2 | MIA p̂ 0.6368, repeated (FQ-R8) | **DONE 10-04.** It is NBM's own tight published spread, not integer-quantile geometry; MIA and MDW recompute exactly | Code collapse would block W2. **Did not fire.** W2's target becomes forecast-error variance (regime: LAX q50 +4.4 and +5.4 °F cold on 10-03 and 10-04) |
| S0-3 | v1 halt and sending state | Read-only `read_family_halt_rows_readonly` (`trial_day_latch.py:354`), the sending-family env, and the newest node log permit line. Check whether a `terminal_climate_day` stops composition (verify `settlement/family_barrier.assert_family_only`) | **If v1 can still mint a permit and is not halted, STOP all other rows.** F3 lands first, and the sending family moves to v2-shadow at the next respawn |
| S0-4 | NO-side funnel (FQ-R11, L-11) | Sum `fq_funnel_*.jsonl` by side per station (P8) | If the NO-side `kind=Take` plus `Refuse` evaluations per station are within 10% of YES, there is no NO wiring work. Otherwise F8 gets a scoped NO-subscription item, with the funnel table as evidence |
| S0-5 | Truth L-1 | Catalog CLI finals (P11) current to D−1? AFOS cache (P9) last day? | Decides the input source for F8's regime term: the catalog if current, otherwise F8 Needs F2 |
| S0-6 | Market calibration scan (FQ-R9) | Built as slice M1. For each (side, ask bin), across all rungs: realised minus (ask + fee). Ask = Depth10 best ask at a fixed hour window, scoped by date **and** hour; `ref.ts < settlement`; calendar-day block bootstrap | **(a) Validity STOP:** if a look-ahead assert fails or join coverage is below 95% of tape station-days, no conclusion is drawn and the scan is fixed. **(b)** A cell with LB > 0 becomes an AUT-S grammar candidate (spends α only at nomination) and is never traded directly. **(c)** If every cell's UB ≤ 0 and model Brier is worse than market, F8 is capped at the regime-variance variant, and effort goes to F11 new-information search. This is not a programme stop |

## 4. Workstreams as slices

**Conventions.**
- **Gate after every merge (L-43):** `scripts/ci/run_tests_no_egress.sh` with `EXIT=0` read; `cd <tree> && .venv/bin/lint-imports` reporting "N kept, 0 broken"; the mypy ratchet; the exact interpreter; `PYTHONPATH=<wt>/src`; never `uv`, `pip` or stash.
- **Every brief carries the invariants:** Nautilus is immutable; `allow_short=False`; no cap is read or assigned; no enablement, permit or NO-SEND change; no weakened test.
- **Tests on store-reading gates** write their fixtures through the real writer (L-42), plus one production-default test (L-55).
- **Timer owner:** the **coordinator session** symlinks, runs `daemon-reload` and `enable --now`, and records all three in that slice's evidence file.
- **Node respawn:** happens outside [16:30Z, 17:10Z) and is followed by `breezy-set-family-halt --status` for the sending family (after RC-4) and the permit-line check.

### W1: Measure (early AUT-2 and new rows)

**F2 FQ-TRUTH (FQ-R5).**
- **Acceptance.** The AFOS cache is filled daily for every venue station through D−1. A public GET to `mesonet.agron.iastate.edu` is the only egress; there is no venue credential and only `alerts.env` is read. The unit is the cache's only writer. The dataset unit, still offline, regenerates `settlement_truth.csv` and writes an explicit coverage-gap field.
- **Cache staleness (P10).** Each run uses a day-bounded URL keyed by fetch date. The reader takes the latest revision, and this is pinned by a test.
- **Files.**
  - NEW: `scripts/archive/iem_cli_fetch.py` (reuses `afos_url`, `cache_path_for_url`, `require_settlement_alignment_cache_dir`); `deploy/systemd/breezy-truth-fetch.{service,timer}` and `breezy-truth-dataset.{service,timer}` (`MemoryMax`, `TimeoutStartSec`, `OnFailure=`); `tests/unit/test_iem_cli_fetch.py`; `tests/unit/test_truth_units.py`.
  - EXISTING: `deploy/systemd/README.md` (a unit row); `tests/unit/test_probe_containment.py` (verify first; widen by one reviewed row only if it enumerates egress scripts).
- **Tests.**
  - `test_fetch_get_only_to_iem_host`
  - `test_fetch_reads_no_venue_or_operator_env`
  - `test_fetch_is_single_cache_writer`
  - `test_refetch_window_picks_latest_revision`
  - `test_dataset_never_fetches_cache_miss_refused` (existing behaviour, pinned)
  - `test_truth_units_bounded_and_outside_launch_window`
  - `test_coverage_gap_reported_not_zero`
- **Needs:** 5@WP5s3, F1.
- **Live path:** no; no respawn or restart.
- **Timer owner:** coordinator.
- **No sandbox claim** for user units (FQ-R5; memory `user-unit-sandbox-not-enforced`).

**F4 AUT-2a-FQ (FQ-R1, FQ-R5, FQ-R11).** This is AUT-2 r7 WP0, WP1, WP2, WP3, WP5 and WP6, taken verbatim with their RED lists (AUT-2 r7 `:591-852`).
- **Acceptance.**
  - `ForecastQuantileLadderScorer` labels every FQ fill on C2 `label/v1`.
  - `portfolio_roi --status-only` prints `GATED_UNLABELLED_FQ` until labels land (`test_gated_unlabelled_fq_publishes_no_roi_figure`), then `roi_status=OK` behind `labels_consumable`.
  - Settlement-leg reconciliation against NWS CLI final runs per station.
  - Realised P&L comes only from exec-store fills and settlement.
- **Added (FQ-R11):** `tests/unit/test_aut2_net_position.py::test_no_leg_sign_reconciles_through_real_record_fill_writer` and `tests/unit/test_aut2_reconcile.py::test_no_leg_venue_short_yes_sign_applied_before_compare` (memory `venue-nets-no-holding-as-short-yes`).
- **Files:** as AUT-2 r7 WP0–WP6. The EXISTING files include `scripts/analysis/portfolio_roi_report.py`, `scripts/analysis/position_monitor_nightly_report.py`, `src/breezy/analysis/plugins.py` and `deploy/systemd/README.md`. The NEW files are under `src/breezy/analysis/labeling/`, `src/breezy/persistence/autonomy/{label_store,net_position}.py`, `src/breezy/runtime/venue_positions_read.py` and `deploy/systemd/breezy-label-outcomes.*`.
- **Needs:** 4 (DONE), 5@WP5s3, F1.
- **Live path:** no.
- **Timer owner:** coordinator (label unit, per AUT-2 WP6 activation).
- **WP7/WP8/WP9** stay in queue row 9 (AUT-2b and the remainder).

**M1 market calibration scan (FQ-R9).** This is part of F0's run, committed so it can be repeated.
- **Files.** NEW `scripts/analysis/market_calibration_scan.py`, a thin reader over the tape catalog and `settlement_truth.csv` that reuses the `forecast_conditional_scoring.py:303` binning and the `roi_bound.py:93,97` B and seed. NEW `tests/unit/test_market_calibration_scan.py`.
- **Tests.**
  - `test_scan_scopes_windows_by_date_and_hour`
  - `test_scan_asserts_ref_ts_lt_settlement`
  - `test_scan_uses_depth10_ask_not_quote_tick`
  - `test_scan_bootstrap_by_calendar_day`
  - `test_scan_reports_join_coverage`
  - `test_scan_reads_no_model_output` (model-free)
- **Needs:** none (truth to 09-28 is enough for a first read; re-run after F2).
- **Live path:** no. **Timer:** none.

### W2: Stop and repair (new rows plus early AUT-4)

**F3 FQ-V1-TERMINAL and RC-4.**
- **Acceptance.**
  - `breezy-set-family-halt --status --family-id pm_us_crh_fq_v1` reports the true state, and set works for FQ.
  - The clear CLI still refuses FQ.
  - The v1 manifest carries `terminal_climate_day`.
  - Pre-repair and post-repair rows never share an α sequence (FQ-R4).
- **Files.** EXISTING `src/breezy/strategy/current_rung_hold/family_id_arg.py` (a kind allowlist parameter; set and status pass {CRH, FQ}; clear passes {CRH}); EXISTING `set_family_halt_cli.py` and `clear_family_halt_cli.py` (call sites only); EXISTING `deploy/families/pm_us_crh_fq_v1.json`; tests EXISTING `tests/unit/test_set_family_halt_cli.py` and `tests/unit/test_clear_family_halt_cli.py` (additions only).
- **Verify first.** Grep for tests that pin the v1 manifest sha, for example `test_fq_s8_registration_artefacts.py`. If one pins it, widen that pin by one reviewed row, never relax it.
- **Tests.**
  - `test_status_reads_fq_halt_row`
  - `test_set_accepts_forecast_quantile_ladder`
  - `test_clear_still_refuses_fq` (FQ-R3)
  - `test_v1_manifest_terminal_day_parses`
  - `test_fq_family_halt_key_matches_trade_preamble` (write through the real `record_policy_halt`, read by `--status`)
- **Needs:** F1. If S0-3 fired, it Needs nothing and runs first.
- **Live path:** the manifest is read at node boot, so a **node respawn** is needed (FQ-R12; the supervisor reads no manifests).

**F5 FQ-PREREG: PREREG v2 amendment and R-B for v2 (FQ-R6, FQ-R7).** Content is in §6.
- **Acceptance.** The amendment is filed under `docs/evidence/` through the peer loop. The design JSON is frozen at a 40-hex SHA. `prereg_precommit_check.py` exits 0, and the N Monte-Carlo record is committed.
- **Files.**
  - NEW: `docs/evidence/RULING_prereg_v2_amendment_shadow_eprocess_<date>.md`; `docs/evidence/PREREG_FQ_v2_design_<date>.json`; `scripts/analysis/prereg_precommit_check.py` (AUT-4 WP7a, `:1340`); `scripts/analysis/fq_resume_n_mc.py`; tests `tests/unit/test_prereg_precommit_check.py` (WP7a names) and `tests/unit/test_fq_resume_n_mc.py`.
  - AUT-4 WP0 (xi)/(xiv) measurements go to `docs/evidence/AUT4_WP0_<date>.md`.
  - EXISTING: `reviews/ARCH-ERRATA-rev9_2.md` gains E-15 and E-16 (RC-1, RC-6).
- **Tests.**
  - `test_h0_mc_outcomes_bernoulli_exactly_at_be` (L-41)
  - `test_mc_replays_live_daily_loop_verbatim` (L-40 ii)
  - `test_mc_includes_mixed_side_days` (L-40 i)
  - `test_n_uses_out_of_fold_pre_20260701_only` (RC-2)
  - `test_mc_never_calls_open_holdout`
- **Needs:** F0, F1.
- **Live path:** no.

**F6 FQ-BRIDGE: interim stop (FQ-R3; TEMPORARY BRIDGE).**
- **Acceptance.**
  - An in-node probe modelled on `FeeDriftProbeActor`/`trade.py:461-476` reads the pinned artefact `$STATE/derived/fq-loss-stop/latest.json` (`loss_stop/v1`). It checks sha, schema, `as_of` age ≤ `MAX_AGE_H` and the truth-coverage field.
  - **PASS:** no veto.
  - **FAIL** (venue-level realised net P&L crosses the pre-registered floor): `record_policy_halt` (sets only), a CRITICAL, and the entry veto.
  - **UNKNOWN_STALE:** a CRITICAL on every probe. Beyond `STALE_VETO_H` (pre-registered), the entry veto is applied, fail-closed per L-38. It is a computed veto, not a stored halt, so no clear exists.
  - The statistic is **venue-level**, so it never reads `family_id` from pre-epoch rows (P15). It is a safety floor, not inference.
  - It acts through FQ's `submit_veto` slot, composed in `trade.py` as the first non-None of (family halt, loss stop). `strategy.py` is untouched, and the only FQ order path is `try_submit` (P3).
  - L-38 positive control: the counter `included_settled_fills` increments on the first labelled day.
- **Files.**
  - NEW: `src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py` (reader; no analysis import); `src/breezy/analysis/fq_loss_stop.py` (producer over C2 and the AUT-2 marker); `deploy/systemd/breezy-fq-loss-stop.{service,timer}`; tests `tests/unit/test_fq_loss_stop_probe.py`, `tests/unit/test_fq_loss_stop_producer.py`, `tests/unit/test_app_trade_fq_loss_stop_wiring.py`, `tests/contract/test_loss_stop_schema_writer_reader_agree.py`.
  - EXISTING: `src/breezy/app/trade.py` (`_compose_forecast_quantile_ladder` only); `pyproject.toml` (console script).
- **Tests.**
  - `test_probe_never_references_clear` (AST over the module and wiring: no `clear_family_halt`, `clear_legacy_family_halt` or `clear_family_halt_cli`)
  - `test_fail_sets_policy_halt_through_real_latch`
  - `test_stale_alerts_every_probe_then_vetoes_past_bound`
  - `test_missing_artefact_is_unknown_never_pass`
  - `test_schema_or_sha_mismatch_is_unknown`
  - `test_producer_reads_no_family_id_of_pre_epoch_rows`
  - `test_counter_increments_positive_control` (L-38)
  - `test_fq_has_no_exit_order_path` (AST)
  - `test_floor_read_from_prereg_never_from_operator_controls`
  - `test_production_default_paths` (L-55)
- **Needs:** F4, F5. Code may merge after F1. Before F4, the probe reads UNKNOWN and vetoes fail-closed, which is harmless while v1 is halted or terminal.
- **Live path:** **yes**; node respawn. The supervisor is not touched.
- **Timer owner:** coordinator.
- **Retirement:** when AUT-5a's `entry_veto` and an **EVALUATED** (non-`halt_inert`) `live.drawdown` are accepted for the sender. The retirement commit deletes the probe and its wiring, and AUT-5a's row text carries this.

**F7 AUT-4-EARLY: `FqEvaluator`, e-process and e-LOND (FQ-R1, FQ-R7).**
- **Acceptance.**
  - AUT-4 r11 WP1 (the G36 move and its W1–W5 cut set, with its supervisor-restart runbook `:1281-1282`) and WP2 (pure core, `sample_size`) are merged as written.
  - Added on top: the e-process, confidence sequence and e-LOND cores (§6), the `evidence_row/v1` union with fail-closed `source` (RC-3), and `FqEvaluator`. `FqEvaluator` reuses the moved `forecast_conditional_scoring` functions (`:110,139,237,267,278,303,392,428`) and computes:
    - BSS on **takes** and on all decisions;
    - per-rung-position PIT (FQ-R8);
    - the reliability slope and Spiegelhalter Z;
    - net P&L per calendar day.
- **Files.**
  - AUT-4 WP1/WP2 files (`:1255-1263,1304`).
  - NEW: `src/breezy/analysis/autonomy/{eprocess,confidence_sequence,elond,evidence_row,fq_evaluator}.py`.
  - EXISTING: `src/breezy/analysis/plugins.py` (`FqEvaluator` registration). This file is shared with F4, so it is serialised.
  - Tests NEW: `tests/unit/autonomy/test_eprocess.py`, `test_elond.py`, `test_evidence_row.py`, `test_fq_evaluator.py`.
- **Tests.**
  - `test_capital_nonnegative_bets_predictable`
  - `test_h0_crossing_rate_le_alpha_exact_null` (L-41)
  - `test_cs_reject_only_when_ub_lt_0`
  - `test_elond_equals_geometric_at_zero_discoveries`
  - `test_untagged_row_refused`
  - `test_shadow_rows_never_enter_live_sequential`
  - `test_backtest_rows_reject_only`
  - `test_bss_on_takes_uses_ask_comparator` (L-21)
  - `test_bootstrap_clusters_by_calendar_day`
  - `test_pit_per_rung_position`
- **Needs:** F1 and E-15 filed, F4.
- **Live path:** WP1 W1–W5 touch `forecast_quantile_ladder/strategy.py` and `composition.py`. Follow AUT-4's runbook: a supervisor restart in [01:00Z, 16:40Z), then the next boot, then the permit check. The new modules are offline.

**F8 FQ-V2: repair as a new family, shadow only (FQ-R4, FQ-R7, FQ-R8, FQ-R11, plus the 10-04 evidence).**
- **Acceptance.**
  1. `pm_us_crh_fq_v2` is REGISTERED with **no** `live_orders_ruling`, so every Take is shadow (P5). Its d0 is after the design-freeze SHA, so the sample is fresh: the 5 losing station-days are excluded by construction.
  2. **Regime-aware forecast-error variance.** At boot, a causal per-station term is computed from the last k forward days' (CLI final − NBM q50) residuals: a bias shift plus variance inflation. Its source is the catalog CLI via `breezy.persistence.catalog`, so the node never imports analysis (S0-5).
     - k and the half-life are chosen only by rolling-origin CRPS on out-of-fold archive days before 2026-07-01 (RC-2), then pinned in the design JSON. There is no live refitting: the rule is fixed and only the data move (AUT-3 r6 `:60`).
     - PIT 80% coverage must fall in [0.75, 0.85] on that archive and on forward screening days.
  3. **Model-intrinsic surprise gate**, registered as an α-spending variant and default OFF in the v2 root. It refuses when |NBM q50 − persistence (last final)| exceeds a pinned quantile of the family's own pre-freeze distribution. This is weather only, and the ask is never a predictor (FQ-R8). An ev_net-outlier variant is registered only as a cost filter.
  4. **RISK LIMIT, not a repair (FQ-R11).** One rung per station-day: max-net-edge at one snapshot. Occupancy is a separate read through AUT-5 WP2's `FillReader`. The latch and trial_id grammar are unchanged (FQ-R4). In shadow it is simulated by the evaluator. It binds live only after AUT-5a.
  5. NO-side wiring only if S0-4 requires it.
- **Files.**
  - NEW: `deploy/families/pm_us_crh_fq_v2.json`; `deploy/families/artefacts/<v2 density artefact>`; `deploy/families/artefacts/eprocess_design_pm_us_crh_fq_v2.json` (the "boundary" pin); `src/breezy/strategy/forecast_quantile_ladder/{regime_inflation,forecast_surprise}.py`; tests `tests/strategy/forecast_quantile_ladder/test_regime_inflation.py`, `test_forecast_surprise.py`, `test_v2_manifest.py`.
  - EXISTING: `src/breezy/analysis/nbp_calibration.py` (new artefact version builder); `forecast_quantile_ladder/{artefact_bounds,decision,composition}.py`.
- **Tests.**
  - `test_regime_term_causal_only_days_before_decision`
  - `test_regime_params_pinned_from_pre_20260701_archive`
  - `test_ask_never_enters_p_hat` (property)
  - `test_surprise_gate_reads_no_venue_field` (AST)
  - `test_v2_without_ruling_never_sends`
  - `test_existing_check_order_pin_extended`
  - `test_v1_rows_never_in_v2_sequence`
  - Firewall guards and the exec import pin in the focused gate (memory `focused-gates-miss-the-exec-import-pin`).
- **Needs:** F5, F7 (WP1 merged on the same files), S0-5.
- **Live path:** **yes.** Node respawn, and the sending family changes to v2. Verify whether the env is in the supervisor unit (symlinked, memory `supervisor-unit-is-symlinked-into-the-repo`); if it is, a supervisor restart in [01:00Z, 16:40Z) is needed as well.

**F9 FQ-V2-RESUME: decided by the bar alone.**
- **Acceptance.** All three conditions hold, on `source=shadow` C1 records only (§6.5). The coordinator then files the RC-5 ruling and allowlist row, and v2 is armed into a capped live trial under LIVE_SEQUENTIAL. No v1 halt is cleared.
- **Needs:** F8, **queue row 8 (AUT-1b)** (C1 ask and depth; P7), F6.
- **Live path:** the allowlist plus manifest, then a node respawn.

### W3: Standing search loop (FQ-R10)

**F10 AUT-S-PLAN.**
- **Acceptance.** `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r1.md` is peer-reviewed READY. It covers:
  - **grammar:** family × side × execution mode (taker IOC or resting) × horizon (lead, hour window) × observation conditioning × station subset × weather source;
  - a K cap per cycle;
  - the screen on native `backtest()`/`BacktestEngine` (`src/breezy/runtime/backtest_harness.py`) with `PortfolioAnalyzer.register_statistic` (FQ-R12);
  - reject-only rejection when UB < 0;
  - Hansen SPA / White reality-check multiplicity;
  - a usable-day list (replay-sufficient tape only; memory `quote-tape-is-not-replay-sufficient`);
  - survivors minted as C3 `variant_spec` (RC-6), feeding AUT-4 OFFLINE_CHALLENGER and never retraining directly.
- **Files:** that plan doc only. **Needs:** F1.

**F11 AUT-S-BUILD.**
- **Files.** NEW `src/breezy/analysis/autonomy/search/{grammar,generator,screen,spa}.py` and `deploy/systemd/breezy-autonomy-search.{service,timer}`. EXISTING `src/breezy/runtime/backtest_harness.py` (statistics registration only).
- **Tests.**
  - `test_generator_deterministic_and_k_capped`
  - `test_screen_schema_has_no_win_token`
  - `test_screen_rejects_only_ub_lt_0`
  - `test_screen_refuses_non_replay_sufficient_day`
  - `test_screen_rows_source_backtest`
  - `test_spa_pvalue_reported`
  - `test_screen_spends_no_alpha` (AST: no `elond` import)
  - `test_register_statistic_parity_with_fq_evaluator`
- **Needs:** F10, F7, E-16.
- **Live path:** no.
- **Timer owner:** coordinator. The timer takes the studies flock, `MemoryMax`, a stall watch, one heavy job at a time.

**AUT-3 new source.** Queue row 13 is unchanged. Its existing gate ("or a new source exists") is met by a new **US** weather source minted as `density_table_multisource` (E-16). A screen PASS only feeds nomination (FQ-R10).

## 5. Proposed AUTONOMY QUEUE changes

Rows 1–13 keep their numbers and Needs. Only the text of rows 7, 9 and 10 changes.

**New Needs token `5@WP5s3`** means "AUT-1a WP5 stage 3 merged" (FQ-R2). `/execute-backlog` treats it as DONE when row 5's status records that merge.

| # | ID | Work | Needs | Status |
|---|---|---|---|---|
| F0 | FQ-STEP0 | RUN S0-1..S0-6 read-only (LAX, MIA DONE 10-04) | — | IN PROGRESS |
| F1 | FQ-PLAN | PLAN this r2 → peer loop; file errata E-15/E-16; AUT-4 r12 and AUT-5 r8 deltas | F0 | OPEN |
| F2 | FQ-TRUTH | BUILD IEM CLI fetch + dataset units | 5@WP5s3, F1 | OPEN |
| F3 | FQ-V1-TERM | BUILD RC-4 CLI widening + v1 terminal (first if S0-3 fires) | F1 | OPEN |
| F4 | AUT-2a-FQ | BUILD AUT-2 WP0,1,2,3,5,6 + NO leg-sign tests | 4, 5@WP5s3, F1 | OPEN |
| F5 | FQ-PREREG | PLAN+RUN PREREG v2 amendment, R-B v2, AUT-4 WP0/WP7a, N MC | F0, F1 | OPEN |
| F6 | FQ-BRIDGE | BUILD interim stop (TEMPORARY) | F4, F5 | OPEN |
| F7 | AUT-4-EARLY | BUILD AUT-4 WP1, WP2 + e-process/e-LOND/`FqEvaluator` | F1, F4 | OPEN |
| F8 | FQ-V2 | BUILD v2 family, shadow only | F5, F7 | OPEN |
| F9 | FQ-V2-RESUME | RUN resume bar → RC-5 ruling → capped live trial | F8, 8, F6 | GATED |
| F10 | AUT-S-PLAN | PLAN AUT-S | F1 | OPEN |
| F11 | AUT-S | BUILD search + screen + unit | F10, F7 | OPEN |

**Placement and text changes.**
- F0 and F1 sit above row 3. F2–F7 sit after row 5. F8–F9 sit after row 8. F10 sits after F1. F11 sits after row 10.
- Row 7 text gets "+ retires F6 when `entry_veto` + EVALUATED drawdown".
- Row 9 becomes "AUT-2 remainder (2b, WP7–9)".
- Row 10 becomes "AUT-4 remainder (WP3–WP9)".
- Each row is ≤ 120 characters to stay inside the 12 KB gate (P20).

## 6. PREREG v2 amendment: content outline (F5)

1. **Scope and supersession (FQ-R6).** Shadow decisions at the executable ask become evidence for SCREENING and RESUME only. "Shadow never feeds a verdict" stays in force for every other use. A live trial is still required and validates fill realism and execution. Backtest only ever rejects.
2. **The `source` field (RC-3).**
   - `evidence_row/v1` = {`source ∈ {live, shadow, backtest}`, `decision_id`, station, climate_day, side, ask_exec, fee, h, p_hat, `ref_ts < take_ts`}.
   - **Shadow eligibility:** a C1 Take with a Depth10 best ask of size ≥ 1, qty 1, and fee θ·p·(1−p) cent-rounded at the manifest θ. The risk limit is simulated.
   - **Mixing ban:** shadow is never in LIVE_SEQUENTIAL, live is never in the resume bar, and backtest is only in screen rejection.
   - Every reader refuses an absent or unknown tag.
3. **E-process (FQ-R7).**
   - **Unit.** Calendar day t. Y_t = Σ_i (h_i − BE_i) / Σ_i BE_i, with BE_i = ask_i + fee_i. Within-day dependence (L-40) needs only the conditional mean, never the variance. Y_t ≥ −1.
   - **H0:** E[Y_t | F_{t−1}] ≤ 0.
   - **Capital:** K_t = Π(1 + λ_s·Y_s), with λ_s predictable in [0, λ_max ≤ 0.5]. The betting rule (aGRAPA or ONS) is pinned in the design JSON.
   - **Decisions:** WIN when K_t ≥ 1/α_k (Ville). The two-sided hedged betting CS gives KILL only when UB < 0 (conservative, FQ-R12).
   - **BSS on takes** is a betting CS over the calendar-day mean of (Brier_ask − Brier_model), which lies in [−1, 1]. The comparator is the ask (L-21).
   - **Validation.** H0 Monte-Carlo with h ~ Bernoulli(BE) exactly (L-41), replaying the live daily loop verbatim (L-40 ii) and including mixed-side days (L-40 i). The crossing rate must be ≤ α + MC slack. Sensitivity runs (quote noise, staleness) are labelled separately.
4. **Online FDR (RC-1).**
   - e-LOND over nominations: reject nomination t when e_t ≥ 1/α_t, with α_t = α·γ_t·(|R_{t−1}| + 1), γ_t = 2^−t and α = 0.025.
   - It equals ARCH's geometric α_k when no discovery has been made. K_LIFETIME ≤ 4 is kept as a ceiling.
   - Screening spends no α, and α is charged at the C5 nomination row (written by `compute_nomination_columns`).
   - This replaces the fixed Bonferroni split (`hypothesis_register`) for this programme. FDR control is stated explicitly, replacing FWER.
5. **Resume bar: three conditions, all required (FQ-R7).**
   - (a) Shadow net-P&L CS LB > 0 at the executable ask, at α_k.
   - (b) BSS-on-takes CS LB > 0.
   - (c) Calibration guard: reliability slope 95% CI ∋ 1 and Spiegelhalter Z not rejected at 0.05, using a calendar-day block bootstrap (B = `B_RESAMPLES`, seed `derive_seed`), evaluated at the look. It can only block.
   - **Fresh sample.** Only climate days after v2 d0, and d0 is after the design-freeze SHA. The repairs were data-dependent on the 5 losing days, so those days never count.
6. **N from residuals: method, not a number (RC-2).**
   1. Take out-of-fold (CLI final − NBM) residual vectors on archive days before 2026-07-01, grouped by calendar day to preserve cross-station correlation ρ̂ (AUT-4 WP0 (xi)).
   2. Resample whole calendar days.
   3. Map them through the v2 predictive and the rung ladder to obtain take sets and outcomes. Costs come from the forward-only tape ask distribution (replay-sufficient days). Under H1, μ = δ_h.
   4. Run the pinned e-process.
   5. N = the smallest number of calendar days with P(K_N ≥ 1/α_1) ≥ 0.8, where the take rate per day comes from the shadow funnel.
   - **Use of N:** (i) the earliest look for (c); (ii) the ETA and feasibility against the 2027-01-25 KILL (`PROGRESS.md:47`); (iii) E-15's `n_min_eff`.
   - Seed, B, the residual-source sha and `sigma_source_contaminated=false` are recorded.
7. **Bridge floor.** A venue-level realised net-P&L floor in contract units, calibrated by an H0 Monte-Carlo (L-41). It is never derived from either operator cap, and the plan names neither cap's variable (L-39).
8. **Live trial.** v2 LIVE_SEQUENTIAL runs the same e-process on `source=live` C2-admissible rows only, under its own α (bound by `family_prereg_sha256`). A shadow-versus-live slippage parity check is reported.

## 7. Disjoint parallel groups

These were checked against the file lists in §4. A "shared" file means the groups touching it run in series.

| Wave | Groups in parallel | Shared files → order |
|---|---|---|
| A (now) | {F0/M1: `scripts/analysis/market_calibration_scan.py`, its test} ∥ {F1: docs only} ∥ {F10: plan doc} | none |
| B (after F1, 5@WP5s3) | {F2: `scripts/archive/iem_cli_fetch.py`, truth units} ∥ {F3: `family_id_arg.py`, halt CLIs, v1 manifest} ∥ {F4: AUT-2 files} ∥ {F5: evidence + `prereg_precommit_check.py`, `fq_resume_n_mc.py`} | `deploy/systemd/README.md` (F2, F4): append-only rows, F4 first. `pyproject.toml`: none in B |
| C | {F6: `loss_stop_probe.py`, `fq_loss_stop.py`, `app/trade.py`} ∥ {F7: AUT-4 WP1 files incl. `fq/strategy.py`, `fq/composition.py`, `plugins.py`} | `plugins.py`: F4 then F7. `pyproject.toml`: F6 then F7. `app/trade.py` is F6 only, landing before queue row 7 (AUT-5a owns it after) |
| D | {F8: `fq/{decision,composition,artefact_bounds}.py`, `nbp_calibration.py`} ∥ {F11: `analysis/autonomy/search/*`, `backtest_harness.py`} | F8 after F7 (`composition.py`). F8 against AUT-5a WP5 (`strategy.py`, `composition.py`, `calibration_artefact.py`) and AUT-3 WP2 (`calibration_artefact.py`, `artefact_bounds.py`, `composition.py`): strictly serial, whichever lands second rebases, full gate |

## 8. Trade-offs

- **e-process against LD-OBF.** An e-process is anytime-valid and fits a loop with no horizon. It needs no Var_H0 for multi-rung days. The cost is a little power at a fixed n, plus an ARCH erratum (RC-1). Chosen per FQ-R7.
- **Calendar-day betting units against per-fill units.** Per-day units keep the supermartingale valid under within-day and cross-station dependence (the LAX/MIA regime is shared). The cost is fewer, coarser bets.
- **e-LOND against alpha-investing.** e-LOND is valid with e-values under arbitrary dependence and equals the current geometric α while there are no discoveries. Alpha-investing needs independence assumptions.
- **Bridge through the composed `submit_veto` against AUT-5's `entry_veto` slot.** It needs zero `strategy.py` edits and no collision with AUT-5a WP5. It is temporary and retired by that slot.
- **Venue-level against family-level loss floor.** Venue-level obeys P15. With one sender per venue the two are equivalent.
- **v2 root plus a filed ruling (RC-5) against a lineage child `fq_v1_r0001`.** A child would need AUT-5 L2 (far off) and would share v1's lineage. FQ-R4 requires separation.
- **Boot-time regime term against an AUT-3 daily mint.** AUT-3 is GATED and far away. The boot term is a fixed rule over causal data. Overfitting risk is bounded by tuning only before 07-01.
- **Waiting for AUT-1b for shadow evidence against adding log fields.** Log fields were rejected by FQ-R11. The consequence is stated: no FQ resume before AUT-1b.
- **Weather-only surprise gate against an ev_net-outlier gate.** The ask enters ev_net, so the ev_net form is allowed only as a registered cost filter.

## 9. Risk register

| Risk | Sev | Mitigation |
|---|---|---|
| v1 can still send today (unverified) | CRIT | S0-3 STOP; F3 first |
| RC-1/RC-2/RC-5/RC-6 rejected in the peer loop | HIGH | F7, F8 and F11 code is gated on the errata. F2–F6 do not depend on them |
| No resume before AUT-1b, which is behind AUT-5a and AUT-6 | HIGH | Stated, not hidden. The loop proves itself through the AUT-7b drill path ("machinery proven, edge unproven") |
| W2 edge is likely absent (09-20 terminal finding; 10-04 cold-regime evidence) | HIGH | The S0-6 (c) cap; F11 new-information search is never blocked by F8 |
| Regime-term overfitting | MED | Tuned only on pre-07-01 archive; PIT and CRPS gates; registered variant |
| Bridge reports a stale PASS | HIGH | Age bound; UNKNOWN never PASS; fail-closed veto; L-38 positive control |
| e-process misspecified (non-predictable λ) | HIGH | `test_capital_nonnegative_bets_predictable`; exact-null Monte-Carlo (L-41, L-40 ii) |
| Shadow fill realism (no queue or latency) | MED | Depth-checked qty 1; live trial validates; slippage parity reported |
| AFOS cache never refreshes after a correction (P10) | MED | Fetch-date-keyed URLs; latest-revision test |
| CLI widening widens the clear path | HIGH | `test_clear_still_refuses_fq` |
| Contention on FQ files across F7/F8/AUT-5a/AUT-3 | MED | §7 serialisation; full gate after every merge |
| PROGRESS 12 KB gate | LOW | Short rows; detail lives in this plan |
| New timer overlaps [16:30Z, 17:10Z) or memory | MED | Bound tests; studies flock; `MemoryMax` |
| Exec import pin or firewall tripped | MED | Guards in every focused gate; widen, never relax |

## 10. Success criteria: the standing loop running (FQ-R10)

Each criterion is scored by an independent reviewer from artefacts. Every line is required over one 14-day window with **zero human or agent commits inside the loop**. The README live-proof window rule applies.

- [ ] **AUT-S** ran on schedule every night. Each record lists usable days, reject-only outcomes (rejected only when UB < 0), the SPA p-value, and no change to α.
- [ ] **AUT-3** ran its scheduled refit including `density_table_multisource`. It was lineage-complete, and AUT-4 consumed every record.
- [ ] **AUT-4** gave an OFFLINE_CHALLENGER verdict for every minted candidate within 24 h, and the AUT-5 engine consumed it (`engine_input/v1` citation).
- [ ] **Nomination.** An accepted PASS produced a C5 SHADOW→CHALLENGER row whose α_k equals the e-LOND value (contract test plus live row). If no real candidate passed, the AUT-7b drill child stands in, with that disclosed.
- [ ] **FORWARD_SHADOW** e-process verdicts were written daily from `source=shadow` rows. An injected untagged row was refused live, with the alert delivered.
- [ ] **PROMOTE.** CHALLENGER→CHAMPION was executed by the engine. The node picked it up at LAUNCH (permit line), and the capped live trial's first fill was labelled by AUT-2 within 24 h.
- [ ] **LIVE_SEQUENTIAL** e-process ran daily on the champion. A real or injected UB < 0 produced a DEMOTE through the live path.
- [ ] **Drawdown** reached EVALUATED, and the F6 bridge was retired. Otherwise the bridge is still live, with its positive control shown.
- [ ] **Halt clearing never automated:** AST tests are green and zero clear events came from any unit.
- [ ] **Gate:** every merge in the window shows a full gate with `EXIT=0` and `lint-imports` "N kept, 0 broken".

Key paths:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r1.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/{README.md,AUT-2-outcome-labeling_plan_r7.md,AUT-4-evaluation_plan_r11.md,AUT-5-promotion-demotion_plan_r7.md,AUT-3-retraining_plan_r6.md}`
- `/home/jon/breezy/src/breezy/app/trade.py`
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/{strategy,decision_funnel}.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/{family_id_arg,set_family_halt_cli,trial_day_latch,fee_drift_probe}.py`
- `/home/jon/breezy/src/breezy/persistence/{live_orders_gate,family_manifest}.py`
- `/home/jon/breezy/scripts/analysis/{settlement_truth_dataset,settlement_alignment_study}.py`
- `/home/jon/breezy/src/breezy/analysis/capture_settlement.py`
- `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md`
- `/home/jon/breezy/docs/core/{PROGRESS,LESSONS}.md`

---

## Round-2 peer review resolution (coordinator, 2026-10-04; domain, ARCH and SEC all REQUEST_CHANGES; binding on r3)
- **FQ-R13, RC-4 REJECTED (all three reviewers agree).** Adopt `fad3e819`/`6b3ce675` as merged: set AND clear both accept FQ, and the FQ set proceeds with open positions. Clearing is human-only through the CLI, with its audit record. Terminality belongs to the manifest and the AUT-5 registry, never to the halt row.
  - Replace `test_clear_still_refuses_fq` with `test_clear_fq_requires_audit_record_and_is_cli_only`.
  - F3 shrinks to two items: the v1 manifest `terminal_climate_day` (tally closure ONLY, not a send stop) and `test_fq_family_halt_key_matches_trade_preamble`.
  - S0-3 checks the halt row only.
- **FQ-R14, the M1 market scan becomes the PRIMARY winner-search path (domain finding).**
  - Why: at ≤1 take/day the honest e-process confirms only an ROI edge of about 50% or more before KILL. Shadow adds no n, because it evaluates the same Takes.
  - The model-free scan covers all rungs × sides × days. It is the n-rich lever.
  - M1 is promoted from a diagnostic to the head of W3. Its cells carry SPA/Bonferroni multiplicity control. Its data NEVER doubles as nomination evidence: nomination uses forward days after a freeze.
  - F5's N record states the n-starvation outcome and pre-registers this fallback.
- **FQ-R15, statistics fixes.**
  - Pin an ask floor and Y_max in the design JSON, and normalise the CS range so the KILL side has usable λ.
  - Define the filtration: λ_t uses only settled days, and the denominator is fixed at decision time.
  - γ_t is heavy-tailed, ∝ 1/(t·log²(t+1)) normalised, or uses per-epoch budgets. α_t is frozen at test start, using R at that moment. The e-LOND stream runs per lineage, with no pooling.
  - The resume-bar combination is min(e_a, e_b).
  - The calibration guard needs a minimum sample size, and blocks on "insufficient".
  - δ_h is a pinned design effect with a rationale, and N is reported as a function of δ_h and of the take-rate interval.
  - Under H1, outcomes are generated from δ_h at the sampled asks. Residuals are used only for ρ̂ and variance.
  - `nomination_feasible` means MC power ≥ 0.8 within the window, so an infeasible nomination burns no K slot.
- **FQ-R16, shadow realism.** Apply a pre-registered haircut to `ask_exec` (one tick, or a miss rate). Pin θ and the rounding by day, failing closed on drift. Shadow/live parity is a resume GATE. NO-side Takes with an empty YES bid are ineligible.
- **FQ-R17, the F6 bridge.**
  - **Integrity.** The artefact digest is recomputable from its inputs: the C2 high-water mark and the truth sha. Check owner, mode and mtime, and enforce a monotonic `as_of` held in memory.
  - **Timing.** The probe runs on an actor timer and caches its verdict. The veto reads the cache only. Any exception means UNKNOWN (`test_probe_exception_is_unknown_not_pass`).
  - **Composition.** The composed veto evaluates both parts on every call and returns the halt reason first. The same callable reaches both the strategy and the exec client (wiring test).
  - **Floor.** Time-uniform (−c·√t), with a stated horizon. The window starts at the arming-ruling timestamp.
  - **Stale veto.** It needs a delivered alert. The lag window between fill and label is bounded only by the operator caps; state that without naming them.
  - **Ordering.** F6 Needs F1 only.
  - **RC-7 (new).** An AUT-5 ownership carve-out for the composed veto in `_compose_forecast_quantile_ladder`, plus an AUT-5 r8 note that WP5 rebases over it.
  - **Retirement.** On the first accepted non-inert `live.drawdown` PASS, with a named re-calibration trigger owner.
  - The firewall and exec-pin guards are in its focused gate.
- **FQ-R18, F2 truth.**
  - Reuse `IEM_ALLOWED_HOSTS` and the `iem_mos_probe_transport` pattern.
  - Writes are flock + tmp + atomic rename.
  - Validate that the body parses to a CLI product. A parse-failing or coverage-regressing body never replaces a valid revision (`test_bad_body_never_becomes_latest`).
  - Record the body sha, and cross-check against the catalog CLI finals with a disagreement flag.
  - The single-writer claim is scoped to AFOS CLI URLs, and the legacy writers are made cache-read-only for those paths.
  - No timer-bearing commit auto-enables. Units are parked until the gate reads EXIT=0.
- **FQ-R19, queue edges.**
  - Split F7 into F7a (WP1+WP2, Needs F1) and F7b (e-process, e-LOND, `evidence_row`, FqEvaluator; Needs E-15, F4, F7a). Prefer an AUT-4 r12 delta that moves only `analysis/stats/*`. If WP1 stays, it runs strictly serially with AUT-5a WP5/WP6.
  - Row 10 Needs += F7a. Row 9 Needs += F4.
  - F4 adds WP8. If the label peak exceeds 4G, WP6 holds until AUT-6.
  - E-15 and E-16 are filed by F1 only.
  - `5@WP5s3` is a literal status string.
- **FQ-R20, RC amendments.**
  - **RC-1:** do not redefine `n_min_eff`. Add `test_kind`, `eta_ns` and `window_end`, with `n_min_eff=null` for `e_process`. Scope `test_nominee_single_look_never_reopened` to `fixed_n`.
  - **RC-3:** `evidence_row/v1` is an in-memory typed adapter, with `source` set from the store the row came from. Every consumer has its own untagged and unknown-tag tests and a single-loader contract test. `ref_ts < take_ts` is enforced at load.
  - **RC-5:** the AUT-5 r8 delta covers every `fq_v1` reference (19 in AUT-5, 28 in AUT-7). F9 arms v2 through registry ROOT_ADMIT/RESUME.
  - **RC-6:** `variant_spec` carries FQ-manifest-expressible parameters only. Cross-family variants go through new-family registration.
- **FQ-R21, the end state.**
  - Add the row that enables PROMOTE (AUT-5 L2 `WIDENING_KINDS`).
  - Add the row for a new-source ingest actor plus node wiring.
  - §10 becomes conditional on those rows, and says so.
- **FQ-R22, F8 details.**
  - Assert that the boot day equals the decision day.
  - CRPS tuning replicates live CLI latency, uses nested out-of-fold, and states its season window.
  - The surprise gate defaults OFF, with its take-rate cost pre-registered.
  - Post-respawn checks: the permit is UNEXPIRED, the `fq_live_orders enabled=` line, and the halt `--status`.
