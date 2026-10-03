# AUT-4 — Evaluation (offline challenger + forward shadow + live sequential): plan r1

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-4 |
| Title | Evaluation: OFFLINE_CHALLENGER, FORWARD_SHADOW, LIVE_SEQUENTIAL C4 verdict producers, α/K_max accounting, feasibility record |
| Round | r1 (2026-10-03) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` Rev 3, sha256 `66002f49ca33515e3515102d9dbb4134935e0573f85a98a5c41f1352f91361af`, with the Rev 4 deltas Z1–Z20 of `reviews/ARCH-r3-merged.md` treated as applied (Z1 bound-sha acceptance, Z2 drill path, Z4 validity ceilings, Z12 stagger/SLO, Z13 CRITICAL delivery, Z14 canary store) |
| Repo HEAD read | `4b8347a6` (branch `feat/data-capture-and-risk`) |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (C1–C6 types, verdict writer, registry read API, `pins.py`); AUT-1 (C1); AUT-2 (C2, RECONCILIATION); AUT-3 (C3 candidates, `Refitter`); AUT-6 (`deliver_with_proof`, `RuntimeMaxSec` rule) |
| Downstream | AUT-5 (consumes every C4 verdict; files the policy ruling whose AUT-4 sections are drafted in §3.9); AUT-7 (rollback triggers on accepted FAIL) |
| Status | PLANNING. Nothing implemented. Every ruling text below is a PROPOSAL for the peer-review loop; none is decided here. |

**Honest headline (read first).** AUT-4 can reach score 3 as *machinery* before the 2027-01-25 KILL.
It **cannot** produce an edge-proving FORWARD_SHADOW PASS before the KILL, and an OFFLINE_CHALLENGER
PASS at the pinned materiality is implausible for any recalibration child (§6.3). The only verdict
that can reach a decisive terminal state before the KILL is LIVE_SEQUENTIAL on the FQ champion, and
only if a PREREG_FQ ruling is filed by about 2026-11-10. Even then its MDE is about +0.10 hold-rate
per one-lot station-day (§6.3). Evidence class for any DONE claim: **"machinery proven, edge unproven"**.

---

## 1. Goal state

**README AUT-4 score-3 criterion (verbatim).**
> - Every candidate from AUT-3 is evaluated automatically against the current champion on pre-registered, cost-aware metrics: out-of-sample Brier/CRPS, traded-rung calibration, and EV net of fees and slippage.
> - Every live family is evaluated daily on AUT-2 labels with the pre-registered sequential tests.
> - Every result is a machine-readable, schema-versioned verdict that AUT-5 consumes.
> - Every verdict states its own power or `n_min` and its time to verdict.
>
> **Live proof:** 7 consecutive days of automatic offline and live verdicts for every live family and every new candidate, each consumed by the AUT-5 policy engine as its input record.

Plus scale criteria (a)–(f) of README "Scale", and the §5.3 window rule (a day counts only with ≥1
real fill or a tagged canary fill; ≥5 real fills per window; canary and drill fills never count).

**ARCH §10 obligations for AUT-4 (verbatim).**
> the replay-sufficiency check that admits forward-shadow tape days; station-day clustering; the measured qualifying station-days per day; the feasibility record (`n_min`, MDE at α_K, `eta_date`) handed to the policy ruling; K_max accounting; the slippage source and its `assumptions` tag; the live-sequential producer over admissible labels.

Plus Z4 (assigned to AUT-4 by the brief): bounded verdict validity, `MAX_VERDICT_VALIDITY_H`.

Where each obligation is met: replay-sufficiency §3.4/WP3; clustering §3.2; measured rate §6.3/WP0;
feasibility record §3.8/WP7; K_max §3.5/WP5; slippage §3.7; live-sequential §3.6/WP4; Z4 §3.1.

---

## 2. L-1 null hypothesis and reuse

Null: Nautilus or existing Breezy already provides it. Verdict per component.

| Need | Checked | Verdict |
|---|---|---|
| Statistical evaluation, sequential tests, Brier/calibration, α ledger | `nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer` + `statistic.py` compute realised-PnL statistics over *filled* positions. Shadow runs never fill (submit veto refuses), and nothing native does Brier, cluster bootstrap, LD-OBF or α spending | **Gap is real** for the statistics; build only the verdict assembly, reuse Breezy primitives below |
| Forward-shadow replay of the live strategy | Native `BacktestEngine` composition already exists: `scripts/analysis/nbp_shadow_parity.py:275` `run_live_parity` composes the real `ForecastQuantileStateActor` + `ForecastQuantileLadderStrategy` with an always-refusing submit veto, driven by `on_order_book_depth` (Depth10, so the empty-bid QuoteTick hole of L-35 does not apply) | **Reuse** (extract the composition into `breezy.*`, WP1; parity harness keeps calling it) |
| Tape read | `ParquetDataCatalog` (native), as used by `nbp_shadow_parity.py:512` | **Reuse** |
| Sequential statistic and boundaries | `settlement/current_rung_hold_v2.py:296` `combine_station_day`, `:346` `score_combined`, `:365` `information_fraction`, `:433` `look_verdict`, `:470` `terminal_look`; `persistence/gs_boundary_artefact.py:219` `load_boundary_artefact`; look loop `scripts/analysis/family_tally_v2.py:625` `run_sequential_looks` (golden-pinned by `tests/unit/test_family_tally_v2_look_loop_golden.py`) | **Reuse**; extract the loop verbatim into `breezy.analysis` (WP1) because §4.3 pins cover only the `breezy.*` import closure |
| Boundary generation and H0 validation | `scripts/analysis/crh_group_sequential_boundaries.py:243`; `scripts/analysis/aud07_live_rule_crossing_sim.py:158,210` (live-loop replay, `StreamingBoundary`) | **Reuse** for the PREREG_FQ boundary package (L-40 ii, L-41) |
| Admission of fills | `src/breezy/analysis/prereg_admission.py:124,627` (`_admit_fill`, `_admit_one_fill`) | **Reuse** semantics; AUT-4 reads C2 `admissible` only (AUT-2 owns admission) |
| Brier, reliability, calibration leg, cluster bootstrap, degenerate-cluster refusal | `scripts/analysis/forecast_conditional_scoring.py:110,139,237,267,278,303,392,428` | **Reuse**; extract into `src/breezy/analysis/scoring_core.py`, script re-exports (WP1) |
| Murphy decomposition (resolution vs market) | `src/breezy/analysis/brier_decomposition.py` | **Reuse** |
| Market-implied baseline, look-ahead guard | `scripts/analysis/wp7b_market_as_forecaster.py:169` `LookAheadError`, `:232` `first_liftable_at_or_after`, `:372` `build_station_day_events`, `:475` `paired_brier_ci`, `:707` `compute_qualifying_rate` | **Reuse**; extract the pure event builder (WP1) |
| Replay sufficiency | `src/breezy/analysis/replay_sufficiency.py:651` `is_replayable_whole_day`, `:694` `classify_station_day(window_start_ns, window_end_ns)` (already window-parameterised), `:207` `decision_window_ns` (hard-wired 12:00–17:00 LST on the climate day, `:150-151`) | **Reuse** classifier; **gap**: no FQ window. FQ decides on D−1 (`fq/decision.py:216-218` `_is_d_plus_1`), so add a kind-keyed window function; the CRH constant stays untouched (KILL-clock B21 contract) |
| FQ permit window | `scripts/analysis/nbp_shadow_parity_pure.py:151` `permit_window_for_day` (uses `trade_supervisor_core.LAUNCH_UTC`, `PERMIT_TTL_NS`) | **Reuse** the definition; re-express in `breezy.*` with a parity test |
| n_min, holdout single look | `nbp_calibration.py:309` `compute_n_min` (two-sided 0.05, power 0.8, X = 0.0152, ceiling 520); `:353` `open_holdout`; `:273` `DEFAULT_SPLITS` | **Reuse** `open_holdout` and the X anchor; generalise n_min to α_k one-sided in `eval_stats` (a formula, not a new semantic) |
| Recalibration selection | `nbp_calibration.py:1589` `select_probability_recalibration`; `scripts/analysis/nbp_skill_study.py:2005-2007` selects on the **validate split only** | **Reuse** per fold for the archive-CV stability pre-screen (§3.5); fixes the single-split gap without re-fitting EMOS |
| Promotion predicates | `promotion_criteria.py:195-613` (`evaluate_c_kill`, `evaluate_c_paired`, `evaluate_c_validity`, `evaluate_c_n`, `assemble_outcome`) | **Reuse** `evaluate_c_validity` logic (whole-day + drift refusal) and `champion_kill_clock_path`; the PROPOSAL generator stays advisory (G14) and is not a C4 producer |
| Pinned bootstrap | `src/breezy/settlement/roi_bound.py:93,97` (`B_RESAMPLES=10_000`, `SEED=20260904`) | **Reuse**; at α_K = 0.0015625 the one-sided tail holds 15.6 draws, so a test pins `α_k·B ≥ 10` |
| Verdict writer, registry reader, plug-in registries | ARCH-0 `persistence/autonomy/` (C4 writer, `resolve_champion`, `OFFLINE_PLUGINS`, `RefusingPlugin`) | **Consume**; AUT-4 writes no new store |

---

## 3. Design

### 3.1 Contracts consumed and provided; verdict rules common to all producers

- **Consumes** C1 (`DecisionRecord` Take/TrySubmit with `eval_ns`, `depth_ref`, `p_hat`; `drill`, `source`), C2 (`label/v1`, admissible rows only), C3 (`lineage/v1`: `forward_eval_start_utc`, `train_end_exclusive_utc`, `leakage_assertions`, `ablation_artefact_sha256`), C5 read-only (fold at `now`, `lineage_counters.candidates_evaluated`, `holdout_opens`, `alpha_spent`), C6 (`Evaluator` slot of `OFFLINE_PLUGINS`; `Refitter` for per-fold re-selection only).
- **Provides** C4 `verdict/v1` of kinds `OFFLINE_CHALLENGER`, `FORWARD_SHADOW`, `LIVE_SEQUENTIAL`, and `HEALTH` with detectors `eval_completeness` and `feasibility_consistency`.
- **Bound subject sha (Z1).** Every verdict's `subject_artefact_sha256` is the family's bound artefact sha from its BOOTSTRAP/MINT row (one immutable artefact per family id), read from the fold, never from the newest row.
- **Validity (Z4).** `valid_until_ns = produced_at_ns + VERDICT_VALIDITY_H·3600·10⁹` with `VERDICT_VALIDITY_H = 26` for all three kinds (24 h cadence + 2 h for flock wait and timer jitter). Proposed code ceiling in `pins.py`: `MAX_VERDICT_VALIDITY_H = 26` (strictly below `DEADMAN_HORIZON_H = 30`, so a dead producer surfaces as `registry_attest_expired` before `registry_chain_stale`). Producers refuse to write a verdict above the ceiling; the engine rejects one (ARCH Z4).
- **Single-look discipline.** OFFLINE_CHALLENGER and FORWARD_SHADOW are evaluated confirmatorily **once**, at the first run where `n ≥ n_min`. Before that the verdict is `UNDERPOWERED` and its `metrics` carry **no effect estimate, interval or p-value**, only counts, so the daily recomputation is not a stream of uncorrected looks. A FAIL at the single look is final for that candidate (no re-look; a new candidate is a new k). LIVE_SEQUENTIAL uses the registered group-sequential looks instead.
- **Fail-closed outcomes.** Any missing, stale, unknown-version or unverifiable input, any failed leakage assertion, or any producer exception yields `ERROR` (never PASS) plus a CRITICAL routed through `deliver_with_proof` (Z13). `UNDERPOWERED`, `INCONCLUSIVE` and `ERROR` never promote (ARCH C4).
- **Units of n.** OFFLINE_CHALLENGER and FORWARD_SHADOW: independent station-days (Y14). LIVE_SEQUENTIAL: combined station-day draws (`combine_station_day`, L-40). The unit is written into `metrics.n_unit`.
- **Payload hygiene.** No paths in verdicts: `inputs[]` is `{path_role, sha256}`; `test_autonomy_payload_hygiene_scan` (ARCH §4.7) covers the AUT-4 writers.

### 3.2 Clustering and the family pin

- **Station-day is the unit of n and of the decision CI** (ARCH Y14). A take set within one `(station, climate_day)` is one cluster. `assert_nondegenerate_clustering` is applied; a degenerate key refuses (ERROR).
- **Date-clustered sensitivity.** The four FQ stations share synoptic regimes (LAX/SFO especially). Every interval is also computed with `cluster=date`; if the station-day and date decisions disagree, the outcome is `INCONCLUSIVE(cluster_sensitivity)`, never PASS.
- **Family pin (bss-headline lesson).** `metric_registry.py` defines a closed set of metric names, each tagged `event_family="rung_2f_traded"`. Any metric on the median binary or any other family is refused at write time (`test_verdict_metrics_rung_family_only`). The traded-rung calibration leg and the under-confidence signal (`underconfidence_signal`, mean signed deviation) are always reported, because the rung family is known to fail the leg and to be under-confident (FC_0b: 3/5 buckets failing, worst 0.176, mean signed +0.079).

### 3.3 Modules (all analysis layer; never imported by live packages, G15)

| Path | Purpose |
|---|---|
| `src/breezy/analysis/scoring_core.py` | Extracted verbatim from `forecast_conditional_scoring.py`: `Trial`, `brier`, `reliability`, `bootstrap_cluster_draws`, `percentile_interval`, `assert_nondegenerate_clustering`, `bootstrap_brier_difference_ci`, `CalibrationLeg`, `evaluate_calibration_leg`, `underconfidence_signal`. The script re-imports them (byte behaviour pinned) |
| `src/breezy/analysis/sequential_looks.py` | `run_sequential_looks` extracted verbatim from `family_tally_v2.py:625-780`; `family_tally_v2.py` and `aud07_live_rule_crossing_sim.py` import it |
| `src/breezy/analysis/market_events.py` | Pure parts of `wp7b_market_as_forecaster.py` (`assert_complete_partition`, `first_liftable_at_or_after`, `mu_sigma_at_instant`, `build_station_day_events`, `to_trials`, `paired_brier`, `paired_brier_ci`, `LookAheadError`); the script re-imports |
| `src/breezy/analysis/autonomy/shadow_replay.py` | Extracted engine composition of `run_live_parity` (actor + strategy + refusing submit veto + `_NowBox` + `_depth_clocked_at_decision_instant`), parameterised by a resolved family (manifest + artefact bytes). `nbp_shadow_parity.py` calls it; its pre-freeze guard (`PostFreezeTapeRefusedError`) is unchanged |
| `src/breezy/analysis/autonomy/eval_stats.py` | `alpha_k(alpha_total, k)`, `n_min_one_sided(sigma_d, x, alpha, power)`, `mde_one_sided(sigma_d, n, alpha, power)`, `eta_days(n_min, n, rate)`, `eta_date(...)`; z-quantiles as pinned literals (the `nbp_calibration.py:288-289` convention) |
| `src/breezy/analysis/autonomy/metric_registry.py` | Closed metric names per verdict kind, `n_unit`, family tag (§3.2) |
| `src/breezy/analysis/autonomy/windows.py` | `decision_window_ns(kind, climate_day, std_utc_offset_hours)`: CRH kinds delegate to `replay_sufficiency.decision_window_ns` unchanged; `forecast_quantile_ladder` returns the D−1 local-standard-day window intersected with the permit window (`permit_window_for_day` semantics). `assert_instant_in_window(kind, climate_day, ts_ns)` checks **local date and hour together** (implausible-result lesson) |
| `src/breezy/analysis/autonomy/leakage.py` | `assert_ref_before_take(ref_ts_ns, take_ts_ns)` (strict `<`), `assert_forward_day(day, lineage)`, `assert_not_sealed(day, sealed_bounds)`, `assert_prescreen_pre_holdout(fold)`. Each raises `LeakageError`; the producer converts it to ERROR + CRITICAL |
| `src/breezy/analysis/autonomy/tape_admission.py` | FQ replay-sufficiency (§3.4) |
| `src/breezy/analysis/autonomy/alpha_ledger.py` | k assignment, forward-window epoch, pre-screen accounting, sealed-holdout counter read (§3.5) |
| `src/breezy/analysis/autonomy/evaluators/forecast_quantile_ladder.py` | `FqEvaluator` implementing C6 `Evaluator.offline / forward_shadow / live`; registered in `OFFLINE_PLUGINS[CompositionKind.FORECAST_QUANTILE_LADDER]`. CRH kinds keep `RefusingPlugin` (C6 YAGNI) |
| `src/breezy/analysis/autonomy/feasibility.py` | Feasibility record builder (§3.8) |
| `src/breezy/analysis/autonomy/producers/eval_live.py` | Entry module (`python -m`), LIVE_SEQUENTIAL for every family in {CHAMPION, HALTED} on the fold, plus `eval_completeness` HEALTH |
| `src/breezy/analysis/autonomy/producers/eval_offline.py` | Entry module, OFFLINE_CHALLENGER for every SHADOW/CHALLENGER candidate, FORWARD_SHADOW for every CHALLENGER, feasibility record, `feasibility_consistency` HEALTH |

Entry modules live in `breezy.*` so the §4.3 producer pins (`PRODUCER_SOURCE_SHA256["eval_live"]`, `["eval_offline"]`) cover every statistic they use.

### 3.4 Replay-sufficiency check for forward-shadow tape days (ARCH §10)

A `(station, climate_day)` is an **admissible FORWARD_SHADOW day** only if all hold, each refusal named in `metrics.days_excluded_by_reason`, never imputed:
1. `FINAL` settlement label present (CLI final; pending until then, so a day is never scored on a provisional label).
2. FQ-window census row (below) passes `is_replayable_whole_day` (SUFFICIENT, `window_complete=True`, `coverage_kind=WHOLE`); `window_complete=False` rows are pending, not failures (census-rows lesson).
3. Not in the replay drift set (`replay/replay_drift.jsonl`, as `evaluate_c_validity` requires).
4. **Largest-item guard (L-53).** The day's Depth10 bytes for the station's instruments ≤ `FORWARD_SHADOW_MAX_DAY_BYTES` (set in WP0 from the measured worst case, e.g. the MIA 2026-09-29 day that hit `DRIVER_TIMEOUT` at 360 s); above it the day is excluded `TAPE_DAY_OVERSIZE` with an alert, so one oversized day can never fail the job forever.
5. **Replay fidelity.** The champion replayed on that day must reproduce every live C1 `Take` (live ⊆ replay, matched on `DecisionKey` via `nbp_shadow_parity_pure.diff_decision_keys`). Replay takes absent from live are allowed only if a live C1 `EntryVeto`/`TrySubmit` refusal or the venue budget stop explains them. Otherwise `REPLAY_PARITY_MISMATCH`.
6. `day ≥ forward_eval_start_utc` of the candidate and outside the sealed-holdout bounds as fixed by ruling R-A (§3.9).

**FQ census.** `tape_admission.classify_fq_station_day` calls the existing `classify_station_day(..., window_start_ns, window_end_ns)` with the FQ window from `windows.py`, writing `derived/replay/replay_sufficiency_fq.jsonl` (same `ReplaySufficiency` schema, separate file, so the CRH census that feeds the KILL clock is untouched and there is no L-50 two-writer race). It runs inside `eval_offline` before scoring.

### 3.5 OFFLINE_CHALLENGER and K_max accounting

**Stage 1: pre-screen (no α).** Evaluated for every new candidate the day it is minted, on pre-holdout archive data only (`DEFAULT_SPLITS`: days < 2026-07-01):
- *Archive-CV stability* (fixes "recalibration choice rests on a single validation split"). Rolling-origin folds by date over 2023-01-01..2026-06-30, F = 6 blocks; for each fold, `select_probability_recalibration` and `select_correction_form` run on the fold's training blocks and are scored on the next block. Metric `prescreen_fold_wins` = number of folds whose selected form equals the candidate's `recalibration`/`correction_form`. EMOS is not re-fitted (cost); only the selection step that the single split decided is re-run.
- *Distinctness.* Paired per-station-day Brier difference candidate − champion on the archive; if every |difference| < 1e-6 the candidate is `NOT_DISTINCT`.
- *Leakage.* `assert_prescreen_pre_holdout` on every fold; C3 `leakage_assertions` all `passed`.
- Outcomes: `FAIL(stage=prescreen)` if `prescreen_fold_wins < PRESCREEN_MIN_FOLD_WINS` (policy value, proposed 4 of 6); `INCONCLUSIVE(NOT_DISTINCT)`; otherwise the candidate is **nominated** and stage 2 starts. No α and no `candidates_evaluated` charge in stage 1. (Archive reuse across candidates is selection, not confirmation, which is why it carries no α and can never alone promote.)

**Stage 2: confirmatory on the rolling forward holdout.**
- k assignment: `k = 1 + |{nominated candidates in this lineage and forward-window epoch with k assigned}|`. **Epoch** = [effective ts of the current CHAMPION row, next CHAMPION change) on the venue fold. The ledger cross-checks the registry's `candidates_evaluated`; any disagreement → ERROR.
- If `k > K_max`: no test; verdict `INCONCLUSIVE(K_MAX_EXHAUSTED)`, `alpha_spent` unchanged. The producer never emits a k > K_max test, so the engine's ERROR rule (ARCH C4) is never the path.
- `alpha_k = alpha_total·2^−k` (one-sided). `alpha_spent` (lineage, cumulative) = Σ α over assigned k.
- `n_min = n_min_one_sided(σ_d, X, alpha_k, 0.80)`, where σ_d is the station-day SD of the paired Brier difference candidate − champion **measured on the archive** (pre-mint, so measuring it does not peek at the forward window) and X = `G22_TARGET_DIFFERENCE_X` = 0.0152 unless the ruling sets another X.
- Metrics at the single look: `brier_rung_diff_vs_champion` (one-sided upper bound at α_k, cluster bootstrap B = 10 000, seed `roi_bound.SEED`), `crps_tmax_diff_vs_champion` (non-inferiority, reported), `calibration_leg_rung`, `underconfidence_mean_signed_dev`, plus the date-cluster sensitivity.
- PASS iff the upper bound < 0 (candidate better), the calibration leg passes under the rule R-C registers, and the sensitivity agrees. FAIL otherwise.
- **Sealed holdout.** Routine evaluation never opens `DEFAULT_SPLITS` holdout rows. `open_holdout` is called at most once per lineage, only by an explicit policy action, and the ledger reads `holdout_opens`; the proposed ruling R-A reserves that one opening for the root's weather-only S2 look.
- **Drill children (Z2).** A no-new-lineage child (byte-identical artefact) gets `INCONCLUSIVE(NOT_DISTINCT)` with `drill=true` in `assumptions`, never a k and never α.

### 3.6 LIVE_SEQUENTIAL producer over admissible labels

- Input: C2 rows for the family with `admissible=True` (so no canary, no drill, no unreconciled, no q≠1), `window_complete` only. Rows are combined per station-day with `combine_station_day` (sign-aware; mixed YES/NO days use the exact variance of the L-40 amendment (i)).
- Statistic and looks: the extracted `run_sequential_looks` with the family's **registered** boundary artefact (`load_boundary_artefact` with its pinned sha), `total_pnl` from C2 `realized_pnl`, the loss stop and truncation clocks as registered. No new α-spend is defined (ARCH C4).
- Mapping: `CONTINUE` → `UNDERPOWERED` (n = draws so far, `n_min` = registered `n_max`, `eta`); efficacy crossing (`SURVIVE`) → `PASS`; `KILL` (loss stop, structural dead, or terminal non-crossing) → `FAIL`; tally refusal → `ERROR`; n = 0 → `UNDERPOWERED` with `n=0`.
- **FQ today has no registered boundary**: `deploy/families/pm_us_crh_fq_v1.json` carries `boundary_artefact_path: deploy/families/artefacts/not_applicable_boundary.json`, and its fills started 2026-10-02 before any registration. Until ruling R-B is filed and its boundary sha is committed, the FQ verdict is `INCONCLUSIVE` with `n_min` absent and the literal reason `NO_REGISTERED_PREREG` (ARCH C4 invariant). This is produced daily, so the live-proof cadence is unaffected; it is honestly not an edge test.
- Family coverage: the producer enumerates families from the verified fold (`resolve_champion` plus HALTED), never from a list; a family whose kind has a `RefusingPlugin` evaluator gets `ERROR(NO_EVALUATOR)`, which also blocks its ATTEST (fail-closed).
- `declared_action_class` is copied from the policy block's `detector → action_class` map (`live_sequential/forecast_quantile_ladder` → proposed DEMOTE).

### 3.7 FORWARD_SHADOW and the slippage source

- Applies to every CHALLENGER-state family. Per admissible day (§3.4): replay the challenger with `shadow_replay` (one station-day per subprocess, per-item timeout, memory-capped), replay the champion for the fidelity check, collect shadow `Take`s.
- **Predicates (ARCH C4, all required):** (a) `brier_rung_diff_vs_market` < 0 at α_k on traded-rung events, market = ask-implied probability at the decision instant via `market_events` with `assert_ref_before_take`; (b) `ev_net_per_take` lower bound > 0, where `ev_net = held − ask − θ·ask·(1−ask) − slippage_proxy` and θ comes from the manifest (`taker_fee_coefficient` 0.0695); (c) calibration leg passes (rule R-C); (d) `n ≥ n_min` in independent station-days. `resolution_diff_vs_market` (Murphy) is reported, because the 09-20 terminal finding was a resolution deficit (−0.0152, CI [−0.0323, −0.0037]).
- **Slippage source.** `slippage_proxy` = mean of C2 `slippage` (fill_px − entry_ask) over the champion's admissible fills in the trailing 28 days, matched to the same Depth10 rows via C1 `depth_ref`. Replay cannot measure slippage (fills at displayed ask), so every FORWARD_SHADOW verdict carries `assumptions: [slippage_champion_proxy]`. Without the ruling statement R-E accepting the proxy for the challenger's policy class, the verdict is `INCONCLUSIVE` (ARCH Y12). For FQ, children differ from the root only in the artefact (§4.2 manifest equality), so they are the same policy class (qty 1, IOC at ask).
- n for (a)/(c) = admissible station-days with ≥1 scorable rung event; n for (b) = station-days with ≥1 challenger take. `n_min` and ETA are computed for (a), the binding predicate; (b) is reported with its own n.

### 3.8 Feasibility record (handed to the policy ruling)

`evidence/autonomy/feasibility/feasibility_<YYYY-MM-DD>.json` (0444), written by `eval_offline` daily:
`{schema: "feasibility/v1", alpha_total, k_max, alpha_K, x, sigma_d_fs, sigma_d_source_sha256, n_min_fs_k1, n_min_fs_K, rate_qualifying_station_days_per_day, rate_window_days, rate_source_sha256, mde_at_alpha_K_by_kill, eta_date_k1, eta_date_K, kill_date: "2027-01-25", promote_feasible: bool}`.
- `rate` = trailing-28-day count of admissible FQ-window station-days / 28, `window_complete` only.
- `sigma_d_fs` = station-day SD of `Brier_fc − Brier_mkt` measured only on tape days **before** the earliest live `forward_eval_start_utc` (initially the AUD02/WP-7b corpus).
- **HEALTH `feasibility_consistency`:** FAIL if the policy block has `promote_enabled=true` and the measured `eta_date_k1 ≥ kill_date`; policy maps it to ALERT (proposed). This keeps the ARCH §4.2 rule true after filing, not only at filing.

### 3.9 Proposed ruling text (NOT decided; for the AUT-5 policy ruling's peer review)

- **R-A Sealed-holdout end.** "The v5.0 sealed holdout is the fixed interval [2026-07-01, 2026-10-01). Days on or after 2026-10-01 are not holdout days. S2 runs once on that interval at its realised n with the MDE stated; it is weather-only skill evidence and not a confirmatory edge test. Rolling forward windows, refit windows and live labels may use days ≥ 2026-10-01." Rationale: today the holdout is open-ended (`DEFAULT_SPLITS.holdout_start` only; `nbp_learning_nightly.py:274-283,524` refuse every post-07-01 day), so ARCH's forward windows, AUT-3's rolling refits and AUT-2's live labels all fall inside it. Alternative R-A′: keep it open-ended and forbid any champion-side forward score. R-A′ blocks FORWARD_SHADOW and LIVE_SEQUENTIAL outright, so it is not recommended.
- **R-B PREREG_FQ_v1 (sequential).** "Statistic S_k/I_k as `combine_station_day`/`score_combined`; LD-OBF, one-sided α = 0.025, a look every 10 station-days, n_max = 160; loss stop ΣPnL ≤ −60 contract-units; D0′ = the climate day after this ruling is filed; fills before D0′ are a diagnostic prefix, never in n. The boundary artefact is produced by `crh_group_sequential_boundaries.py` and validated by a seeded H0 Monte-Carlo replaying the live look loop verbatim (L-40 ii, L-41), including mixed YES/NO station-days; it is used only if Var(S_terminal) ≈ 1 and the one-sided crossing rate ≤ α + MC slack. KILL → FAIL → DEMOTE." The 09-04 rule that a family registers before its first fill was not met for FQ, which is why D0′ is post-filing.
- **R-C Calibration leg as a gate.** "The leg (`evaluate_calibration_leg`, ε = 0.05) is evaluated only on buckets with n ≥ 30; a bucket fails only if |obs − pred| > ε **and** its Holm-adjusted two-sided binomial p < 0.05 across evaluated buckets." Rationale: the module's own note says about half a miss is expected per 10 buckets under perfect calibration.
- **R-D α and candidates.** "α_total = 0.025 one-sided; K_max = 4 (the code ceiling); the forward-window epoch resets only when the venue's CHAMPION changes; stage-1 pre-screen and NOT_DISTINCT verdicts spend no α and assign no k; `PRESCREEN_MIN_FOLD_WINS` = 4 of 6; X = 0.0152 for both OFFLINE_CHALLENGER and FORWARD_SHADOW."
- **R-E Slippage proxy.** "`slippage_champion_proxy` is accepted for challengers whose manifest equals the root's except for the §4.2 allowlist (same policy class); refused otherwise."
- **R-F Feasibility.** The feasibility record of §3.8 (values at filing) goes in the block; with today's numbers `promote_enabled=false` (§6.3).

---

## 4. Work packages

Gate commands for every WP, run by the coordinator, never trusted from an agent:
`PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python` as the exact interpreter; `scripts/ci/run_tests_no_egress.sh` (full gate after every merge, L-43; units launched with `-p LimitNOFILE=524288`, basetemp on `~/.cache`); `cd <tree> && lint-imports` must print "N kept, 0 broken"; mypy ratchet `tests/unit/test_mypy_ratchet.py` (in the gate). Never `uv`/`pip` (L-51), never `git stash`. Activation: immediately on merge unless stated.

**AUT-4.WP0: measurements and L-1 confirmations (read-only, no code).**
Scope: (i) FQ-window replay-sufficient station-days per day for LAX/MDW/MIA/SFO over the last 28 closed days; (ii) FQ station-days with ≥1 admissible fill per day since 2026-10-02 (from the exec store and C2 once present); (iii) σ_d of `Brier_fc − Brier_mkt` on the pre-forward corpus; (iv) worst per-station-day Depth10 bytes and a capped single-day `shadow_replay` peak RSS and wall time (the MIA 09-29 day first, L-53); (v) confirm that `on_order_book_depth` is the FQ trigger in both live and replay (L-34). Output: `docs/evidence/AUT4_WP0_MEASUREMENTS_<date>.md` with commands and raw numbers. GREEN: every number has a command and a source sha. Activation: none.

**AUT-4.WP1: extraction, characterisation-pinned (L-33).**
Files: new `src/breezy/analysis/{scoring_core,sequential_looks,market_events}.py`, `src/breezy/analysis/autonomy/shadow_replay.py`; edit `scripts/analysis/{forecast_conditional_scoring,family_tally_v2,aud07_live_rule_crossing_sim,wp7b_market_as_forecaster,nbp_shadow_parity}.py` to import from them. `live_family_tally.py` is not touched (byte-frozen by PREREG v2 §2).
Tests first: existing `tests/unit/test_family_tally_v2_look_loop_golden.py`, `tests/unit/test_wp7b_market_as_forecaster.py`, `tests/unit/test_forecast_conditional_model_study.py`, `tests/unit/test_nbp_shadow_parity_contract.py`, `tests/unit/test_aud07_live_rule_crossing_sim.py` stay byte-unchanged and green; new `tests/unit/test_aud4_extraction_identity.py::test_extracted_functions_are_the_script_objects` and `::test_shadow_replay_parity_harness_unchanged_on_prefreeze_fixture`. Since extraction has no RED, mutation evidence is required: flip one comparison in each extracted function and show the golden test fails.
GREEN: gate green, lint-imports clean, no behaviour diff. Activation: immediate (no runtime effect).

**AUT-4.WP2: pure evaluation core.**
Files: `src/breezy/analysis/autonomy/{eval_stats,metric_registry,windows,leakage}.py`.
RED first:
- `tests/unit/autonomy/test_eval_stats.py::test_alpha_k_halves_and_sums_below_total`, `::test_n_min_one_sided_matches_compute_n_min_at_two_sided_005`, `::test_mde_inverts_n_min`, `::test_bootstrap_tail_draws_at_alpha_K_at_least_10`
- `tests/unit/autonomy/test_windows.py::test_fq_window_is_d_minus_1_lst_within_permit`, `::test_crh_window_delegates_unchanged`, `::test_fq_window_matches_parity_pure_permit_window`
- `tests/unit/autonomy/test_leakage.py::test_ref_ts_equal_to_take_ts_refused`, `::test_prior_local_day_same_hour_refused` (the 09-20 date/hour leak shape), `::test_forward_day_before_eval_start_refused`, `::test_sealed_day_refused`, `::test_prescreen_fold_touching_holdout_refused`
- `tests/unit/autonomy/test_metric_registry.py::test_verdict_metrics_rung_family_only`, `::test_unknown_metric_name_refused`
- `tests/unit/autonomy/test_verdict_validity.py::test_validity_never_exceeds_max_verdict_validity_h`, `::test_validity_ceiling_below_deadman_horizon`
GREEN: all pass. Activation: immediate (library only).

**AUT-4.WP3: FQ tape admission.**
Files: `src/breezy/analysis/autonomy/tape_admission.py`.
RED first: `tests/unit/autonomy/test_tape_admission.py::test_window_incomplete_is_pending_not_excluded`, `::test_fragment_row_excluded`, `::test_drift_key_excluded`, `::test_oversize_day_excluded_and_alerted_not_failed`, `::test_replay_missing_a_live_take_excludes_day`, `::test_replay_extra_take_explained_by_entry_veto_admitted`, `::test_fq_census_writes_separate_file_not_crh_census`, `::test_provisional_label_day_pending`. Fixtures are written through the real writers (L-42).
GREEN: pass; a dry run over 2026-09-08..09-29 tape reproduces the WP0 FQ rate within ±0. Activation: runs as part of WP6's unit.

**AUT-4.WP4: LIVE_SEQUENTIAL producer and unit.**
Files: `evaluators/forecast_quantile_ladder.py` (`live`), `producers/eval_live.py`; `deploy/systemd/breezy-autonomy-eval-live.{service,timer}`: `OnCalendar=*-*-* 14:45:00 UTC`, `Slice=breezy-studies.slice`, `flock -w 600 breezy-studies.lock`, `MemoryMax=2G`, `RuntimeMaxSec=1200` (ends ≤ 15:20Z, before the 15:30 engine; Z12 stagger), `OnFailure=breezy-study-failed@%n`, `EnvironmentFile=-%h/.config/breezy/alerts.env`, `ReadOnlyPaths=` registry, `ReadWritePaths=` `derived/verdicts`.
RED first:
- `tests/unit/autonomy/test_eval_live.py::test_fq_without_registered_prereg_is_inconclusive_with_reason`, `::test_canary_and_drill_labels_never_enter_n`, `::test_unreconciled_label_excluded`, `::test_continue_maps_to_underpowered_with_eta`, `::test_kill_maps_to_fail_with_declared_demote`, `::test_mixed_side_day_uses_exact_variance`, `::test_families_enumerated_from_fold_not_list`, `::test_refusing_plugin_family_gets_error`, `::test_subject_sha_is_bound_sha_after_attest` (Z1)
- `tests/unit/autonomy/test_eval_live.py::test_look_loop_identical_to_family_tally_v2_on_v2_fixture`
- `tests/unit/autonomy/test_eval_completeness.py::test_missing_family_verdict_is_health_fail`
- `tests/contract/test_autonomy_units.py::test_eval_live_unit_runtime_bound_before_1630`
GREEN: pass; the first live run writes one verdict per fold family. Activation: install and enable the timer on merge (no node or supervisor restart needed; study unit). The R-B boundary, once ruled, lands as a separate reviewed commit of `deploy/families/gs_boundary_pm_us_crh_fq_v1.json` plus the H0 MC evidence; that is the only path that turns FQ from INCONCLUSIVE to a real test.

**AUT-4.WP5: OFFLINE_CHALLENGER (pre-screen + confirmatory) and α ledger.**
Files: `alpha_ledger.py`, `evaluators/forecast_quantile_ladder.py` (`offline`).
RED first:
- `tests/unit/autonomy/test_alpha_ledger.py::test_k_assigned_only_to_nominated`, `::test_k_beyond_kmax_is_inconclusive_no_alpha`, `::test_epoch_resets_on_champion_change_only`, `::test_ledger_registry_disagreement_is_error`, `::test_drill_child_never_assigned_k` (Z2)
- `tests/unit/autonomy/test_offline_challenger.py::test_prescreen_uses_pre_holdout_folds_only`, `::test_single_split_form_failing_folds_fails_prescreen`, `::test_not_distinct_candidate_inconclusive`, `::test_underpowered_verdict_carries_no_effect_estimate`, `::test_single_look_at_n_min_then_final`, `::test_cluster_sensitivity_disagreement_inconclusive`, `::test_sealed_holdout_never_opened_by_routine_eval`, `::test_failed_lineage_leakage_assertion_is_error`
GREEN: pass. Activation: runs in WP6's unit.

**AUT-4.WP6: FORWARD_SHADOW producer and the offline unit.**
Files: `evaluators/forecast_quantile_ladder.py` (`forward_shadow`), `producers/eval_offline.py`; `deploy/systemd/breezy-autonomy-eval-offline.{service,timer}`: `OnCalendar=*-*-* 11:00:00 UTC`, studies slice and flock `-w 1800`, `MemoryMax=12G`, `RuntimeMaxSec=14400` (11:00 + 0:30 + 4:00 ends ≤ 15:30Z), a no-progress stall event per station-day, `OnFailure`, alerts env; per-station-day child processes with `timeout` and a per-child `MemoryMax` share from WP0.
RED first:
- `tests/unit/autonomy/test_forward_shadow.py::test_market_reference_strictly_before_decision`, `::test_window_scoped_by_date_and_hour`, `::test_slippage_proxy_tagged_assumption`, `::test_proxy_without_ruling_acceptance_inconclusive`, `::test_ev_net_uses_manifest_theta_curve_not_flat_fee`, `::test_n_counts_station_days_not_takes`, `::test_excluded_days_named_never_imputed`, `::test_all_four_predicates_required_for_pass`
- `tests/unit/autonomy/test_shadow_replay.py::test_submit_veto_always_refuses_no_order_reaches_exec`
- existing `test_execution_egress_firewall_guard` stays green unchanged (shadow replay never constructs an exec client)
GREEN: pass; a dry run on fixtures produces one OFFLINE_CHALLENGER per candidate and one FORWARD_SHADOW per CHALLENGER. Activation: enable the timer on merge.

**AUT-4.WP7: feasibility record, `feasibility_consistency`, ruling drafts.**
Files: `feasibility.py`; `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-ruling-drafts.md` (the §3.9 text, handed to AUT-5).
RED first: `tests/unit/autonomy/test_feasibility.py::test_rate_counts_window_complete_only`, `::test_sigma_d_uses_pre_forward_days_only`, `::test_promote_enabled_with_eta_after_kill_is_health_fail`, `::test_record_keys_match_policy_block_feasibility_keys`.
GREEN: pass; the first record reproduces §6.3 within the WP0 numbers. Activation: immediate.

**AUT-4.WP8: live-proof run.** No code. Runs the §6 protocol and writes the evidence file. The scorer is independent (§6).

---

## 5. Association

| Contract | From → AUT-4 | AUT-4 → |
|---|---|---|
| C1 | AUT-1: `DecisionRecord` Take/TrySubmit (`eval_ns`, `depth_ref`, `p_hat`, `drill`, `source`), `EntryVeto` | — |
| C2 | AUT-2: `label/v1` admissible rows, `slippage`, `realized_pnl`, `settled_outcome`, `p_at_decision`; RECONCILIATION verdicts gate admissibility | — |
| C3 | AUT-3: `lineage/v1` windows and assertions; `Refitter` not used for EMOS, only the selection functions per fold | — |
| C4 | — | AUT-5 engine (daily 15:30Z consumption, ATTEST `cause_verdict_ids`), AUT-7 (accepted LIVE_SEQUENTIAL FAIL as rollback/demote cause) |
| C5 | AUT-5: read-only fold, `lineage_counters`, bound sha | — (AUT-4 never writes the registry) |
| C6 | ARCH-0: `Evaluator` Protocol, `OFFLINE_PLUGINS`, `RefusingPlugin` | AUT-4 supplies `FqEvaluator` |
| Policy block | AUT-5 files the ruling | AUT-4 supplies R-A…R-F drafts and the feasibility record |
| Delivery | AUT-6: `deliver_with_proof` | AUT-4 CRITICALs use it |

**Order.** WP0 and WP1 can start now in parallel (no ARCH-0 dependency). WP2 and WP3 follow WP1 and run in parallel. WP4 needs ARCH-0 + AUT-2a labels (Wave 2). WP5 and WP6 need AUT-3 candidates and AUT-5a (Wave 3). WP7 follows WP0 and WP6. R-A and R-B should be filed as early as possible, because R-B's D0′ starts the only clock that can finish before the KILL.

---

## 6. Live-proof protocol

### 6.1 Artefact
`docs/evidence/AUT4_LIVE_PROOF_<start>_<end>.md`, produced by a read-only script run by an agent that did not build AUT-4. For each of 7 consecutive **qualifying** days (§5.3: ≥1 real fill; ≥5 real fills across the window; canary fills qualify the day but never count):
- per live family (fold CHAMPION/HALTED): the LIVE_SEQUENTIAL `verdict_id`, outcome, `n`, `n_min` or reason, `eta_to_verdict_days`;
- per candidate minted that day: the OFFLINE_CHALLENGER `verdict_id` (stage, k or none, `alpha_spent`); per CHALLENGER: the FORWARD_SHADOW `verdict_id`;
- the engine's consumption evidence for each id (its input journal or ATTEST/transition `cause_verdict_ids` in the chain export `evidence/registry/registry_polymarket_us_<date>.jsonl`);
- the `eval_completeness` HEALTH verdict = PASS each day; journal lines from both units showing `ActiveState` success and no manual start (`journalctl --user -u breezy-autonomy-eval-*.service`);
- commit SHAs of the units and `producer_code_sha` values matching `pins.py`.

### 6.2 Drills (for (d), where natural failures are rare)
- Kill `eval_offline` mid-run once (SIGKILL inside the window) → `OnFailure` fires, the CRITICAL appears in `evidence/alerts/delivery_<date>.jsonl` with `delivered=true`, the next day's run recovers, and the missing day's verdict expires at 26 h, so the engine cannot ATTEST on it.
- Inject one oversize tape day (fixture copy in a test catalog root, never the production catalog) → `TAPE_DAY_OVERSIZE` exclusion plus alert, job still succeeds.

### 6.3 Accrual ETA and power, stated honestly

Measured inputs (2026-10-03):
- Replay-sufficient CRH-window station-days for the 4 FQ stations, 2026-09-08..09-29: 80 SUFFICIENT of 80 closed rows, 3.64 per calendar day (`derived/replay/replay_sufficiency.jsonl`; absent rows are venue skips). The FQ-window rate is measured in WP0; 3.6/day is used below. The older "only SFO 09-01 is clean" finding described the 09-01..09-10 tape before the per-file ingest fix and is superseded by this census.
- σ_d(Brier_fc − Brier_mkt) ≈ 0.099 per station-day: AUD02 WP-7b rerun, ask, 84 clusters, CI [−0.02147, +0.02079] → SE 0.0108 → σ = 0.0108·√84.
- σ_d(M2 − M1) = 0.132 (node-4 ruling) bounds a large model change; a recalibration child's σ_d is smaller and is measured per candidate.
- About 5 one-lot fills a day across 4 stations, so ≤ 4 station-day draws a day for LIVE_SEQUENTIAL.

Power: α_total = 0.025 one-sided, K_max = 4 → α_1 = 0.0125 (z 2.241), α_K = 0.0015625 (z 2.955); power 0.8 (z 0.842); X = 0.0152.

| Verdict | n_min | Rate | ETA from start | Powered before KILL? |
|---|---|---|---|---|
| FORWARD_SHADOW (a), k=1 | ((3.083·0.099)/0.0152)² ≈ 401 st-days | 3.6/day | ≈ 111 days → start 2026-11-01 gives 2027-02-20 | **No.** Even a start of 2026-10-04 lands 2027-01-23, and nothing exists yet |
| FORWARD_SHADOW (a), k=K | ≈ 609 st-days | 3.6/day | ≈ 169 days | **No** |
| FORWARD_SHADOW MDE at the KILL (start 11-01, ≈ 306 st-days) | — | — | — | MDE ≈ 0.017 (k=1), 0.021 (k=K) Brier improvement over the market, against a measured forecast deficit (+0.0009 Brier, −0.0152 resolution). **Implausible** |
| OFFLINE_CHALLENGER, σ_d = 0.132 | k=1 ≈ 717; K ≈ 1087 | 4/day (weather only) | 180 / 272 days | **No** |
| OFFLINE_CHALLENGER, recal child σ_d = 0.02 | K ≈ 25 | 4/day | ≈ 7 days | Powered, but a reliability fix cannot plausibly gain X = 0.0152 (the rung family's total BSS is +0.0252; fixing a +0.079 mean deviation is worth about 0.006). Expected **FAIL/INCONCLUSIVE** |
| LIVE_SEQUENTIAL FQ (after R-B, D0′ ≈ 2026-11-10) | n_max = 160 station-days | ≈ 2–4/day | 40–80 days → 2026-12-20..2027-01-29 | **Terminal verdict possible** at ≥ 2.2 draws/day. MDE ≈ +0.10 hold-rate above break-even per station-day (Z ≈ 2.86 at I ≈ 33.6). A realistic small edge terminates as KILL → FAIL → DEMOTE |

Consequences: `promote_enabled=false` (ARCH §4.2), so PROMOTE stays machinery-proven by the AUT-7b drill only; no edge claim is possible from AUT-4 before the KILL.

**Live-proof ETA (machinery).** WP0/WP1 now; WP2–3 by about 2026-10-20; WP4 after ARCH-0 + AUT-2a (about 2026-10-31); WP5–6 after AUT-3/AUT-5a (about 2026-11-14); then 7 qualifying days. **Earliest 2026-11-23, planning date 2026-11-30, latest acceptable 2026-12-31.** If FQ fills stop (A1-style halt or DEMOTE), the window extends on canary days but still needs ≥5 real fills (§5.3); after a TERMINAL KILL the producers keep running and the window pauses (ARCH §5.3).

**Evidence class: machinery proven, edge unproven.**

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `systemctl --user list-timers 'breezy-autonomy-eval-*'` shows both enabled; `journalctl --user -u breezy-autonomy-eval-live.service -u breezy-autonomy-eval-offline.service --since <start>` shows timer-triggered runs only; `git log --since <start> -- derived/` empty (verdicts never committed); no verdict carries `decided_by`/operator fields |
| (b) family-agnostic | `tests/unit/autonomy/test_eval_live.py::test_families_enumerated_from_fold_not_list` and `::test_refusing_plugin_family_gets_error`; ARCH gate test `test_family_plugin_exact_set` green; the proof file lists one LIVE_SEQUENTIAL per fold family per day |
| (c) fails closed | `test_underpowered_verdict_carries_no_effect_estimate`, `test_failed_lineage_leakage_assertion_is_error`, `test_proxy_without_ruling_acceptance_inconclusive`, `test_validity_never_exceeds_max_verdict_validity_h`; grep the verdict store: no PASS with `n < n_min` (`jq 'select(.outcome=="PASS" and .n < .n_min)'` returns nothing) |
| (d) detected + delivered | `evidence/alerts/delivery_<date>.jsonl` line for the §6.2 SIGKILL drill with `delivered=true`; `eval_completeness` HEALTH verdicts in `derived/verdicts/*/<date>/`; the expired-verdict ATTEST refusal visible in the engine log |
| (e) RED→GREEN | the RED and GREEN outputs of every §4 test name kept in each WP's PR description; `scripts/ci/run_tests_no_egress.sh` exit 0 at each merge SHA; `lint-imports` "N kept, 0 broken" |
| (f) live proof | `docs/evidence/AUT4_LIVE_PROOF_<start>_<end>.md` per §6.1, 7 qualifying days, ≥5 real fills, each verdict id found in the engine's consumption record and chain export |
| Feasibility | `evidence/autonomy/feasibility/feasibility_<date>.json` present daily; its keys equal the policy block's feasibility keys; `promote_enabled` consistent (`feasibility_consistency` PASS) |
| Honesty | the DONE claim states "machinery proven, edge unproven" unless a pre-registered verdict PASSed |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity / KILL 2027-01-25** | §6.3 states what cannot be powered; single-look discipline; R-B filed early is the only lever for a decisive pre-KILL verdict |
| Repeated daily looks inflate type I | Single look at n_min; UNDERPOWERED verdicts carry no estimate; LIVE_SEQUENTIAL uses registered LD-OBF looks only |
| Sealed holdout breached by forward windows, refits or labels | R-A proposed; until filed, `assert_not_sealed` treats days ≥ 2026-07-01 as sealed, so OFFLINE/FORWARD verdicts stay INCONCLUSIVE(`SEALED_WINDOW`), which is honest and blocks nothing restrictive |
| Leakage (09-20 shape) | `assert_ref_before_take` strict; window checks on local date and hour; forward-day and pre-holdout fold assertions; any failure is ERROR + CRITICAL |
| Trigger drift (L-34) | Forward shadow replays the native depth-driven strategy; WP0 (v) confirms the trigger; replay-fidelity exclusion on any live Take the replay misses |
| Mixed-side variance de-calibrates the boundary (L-40 amendment) | R-B requires an H0 MC over mixed days replaying the live loop |
| One oversized tape day fails the job forever (L-53; MIA 09-29 timeout) | Per-day byte guard, per-station-day subprocess with timeout, exclusion by name |
| Memory on the 30 GiB host | `eval_offline` MemoryMax 12G inside the single studies-flock slot; `eval_live` 2G; never during 01:00–04:30Z heavy-job blackout; stop the study, never the node |
| Shared venv / concurrent agents | Exact interpreter path, never `uv`/`pip`; per-agent scratchpads; explicit-path commits; full gate after every merge; worktrees need `PYTHONPATH` |
| Extraction breaks frozen code | `live_family_tally.py` untouched; golden tests byte-unchanged plus mutation evidence |
| Script statistics escape the producer pins | All statistics extracted into `breezy.*`; pins over the import closure |
| Calibration leg false-FAIL | R-C proposal; until ruled, the existing rule applies, which only makes PASS harder (fail-closed) |
| Slippage proxy degenerate (qty-1 IOC at ask ⇒ ≈ 0) | Reported with its n; tagged assumption; INCONCLUSIVE without R-E |
| K_max exhausted by daily refits | Pre-screen + NOT_DISTINCT spend no α; epoch defined; extra candidates INCONCLUSIVE(K_MAX_EXHAUSTED) |
| Producer down silently | `eval_completeness` HEALTH, 26 h validity → ATTEST impossible → node `registry_attest_expired` veto; OnFailure + `deliver_with_proof` |
| An automatic DEMOTE of the only sender at the R-B terminal look | It is the registered consequence of a non-demonstration; entry-only demotion keeps exits live; stated in R-B for the peer review |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native `BacktestEngine`, `ParquetDataCatalog`, `Actor` composition are used; nothing is patched or subclassed beyond existing Breezy strategies.
- **Caps:** AUT-4 never reads or writes the two operator caps; `test_autonomy_never_reads_or_writes_operator_controls` covers `breezy.analysis.autonomy`.
- **allow_short = False:** untouched; shadow replay uses the composed manifest unchanged.
- **NO-SEND:** shadow replay uses an always-refusing submit veto and constructs no exec client; `test_execution_egress_firewall_guard` stays unchanged and green.
- **Master enablement and permit:** never read or written; the shadow permit is the existing parity stub.
- **PREREG via ruling:** R-A…R-F are proposals only; LIVE_SEQUENTIAL for FQ stays INCONCLUSIVE until R-B is filed; no statistical semantics are created at runtime.
- **Safety tests:** no test is weakened or deleted; extraction keeps golden and contract tests byte-unchanged.

---

## 10. Self-score

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity (README + ARCH §10 + Z4) | 20 | 19 | Every §10 obligation mapped; Z4 ceiling proposed. Minus 1: the AUT-5 consumption record format is assumed, not fixed here |
| Correctness | 20 | 18 | Power arithmetic shown; holdout and PREREG gaps surfaced. Minus 2: σ_d(fc−mkt) is derived from a CI, and the FQ-window rate is not yet measured (WP0) |
| Specificity | 15 | 14 | Paths, units, timers, schemas and test names given |
| Acceptance | 20 | 18 | Checklist with commands; ETA honest. Minus 2: depends on upstream waves |
| Autonomy-safety | 15 | 15 | No envelope widening; fail-closed throughout |
| Reuse | 10 | 9 | Extraction instead of rebuild; a new FQ window is unavoidable |
| **Total** | 100 | **93** | |

### Contradictions with ARCH found (for the ARCH owner)
1. The rolling forward holdout (C4) lies entirely inside the open-ended sealed holdout (`DEFAULT_SPLITS.holdout_start` 2026-07-01, no end; the nightly refuses post-07-01 days). This also hits AUT-3's rolling refits and AUT-2's live labels. R-A proposed.
2. LIVE_SEQUENTIAL "reuses boundaries": FQ has none (`not_applicable_boundary.json`), and its fills predate any registration. R-B proposed; FQ is INCONCLUSIVE(NO_REGISTERED_PREREG) until then.
3. The §7 premise that replay-sufficient days are scarce is stale (80/80 closed CRH-window station-days, 3.64/day). The binding limit is power, not tape. The census window is CRH's, not FQ's D−1 window.
4. Statistics cited in place in scripts (`forecast_conditional_scoring.py:392`, `family_tally_v2.py:625`) fall outside the §4.3 `breezy.*` pin closure, so they must be extracted.
5. "K_max per forward window" has no defined epoch. With promotion disabled it caps a lineage at 4 tested candidates until the KILL, against AUT-3's daily refits. Epoch and no-α pre-screen proposed (R-D).
6. The calibration leg as a hard FORWARD_SHADOW predicate has an inflated false-FAIL rate by its own multiplicity note (R-C).
