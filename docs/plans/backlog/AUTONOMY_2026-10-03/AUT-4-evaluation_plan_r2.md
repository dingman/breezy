# AUT-4: Evaluation (offline challenger, forward shadow, live sequential). Plan r2

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-4 |
| Title | Evaluation: the OFFLINE_CHALLENGER, FORWARD_SHADOW and LIVE_SEQUENTIAL C4 producers; α and K_max accounting; feasibility record; evaluator self-monitoring |
| Round | **r2** (2026-10-03). r1 stays unchanged at `AUT-4-evaluation_plan_r1.md`. This round disposes E1–E22 of `reviews/AUT-4-r1-merged.md` (§R2) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 4**, sha256 `175310117eec39b22fc8229788a7d6182c6395438db23ec65ceb78b964dd508e` (scratchpad `ARCH_rev4.md`, identical bytes to the directory copy at 84 485 B). Pending deltas from `reviews/ARCH-r4-merged.md` are absorbed: **W1** (ATTEST every 6 h), **W7** (forward window and mint limit) and **W8** (post-STOP RECONCILIATION slot). Also `reviews/HOLDOUT-decision.md`, consumed by name only |
| Repo HEAD read | `4b8347a6` (branch `feat/data-capture-and-risk`) |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (C1–C6 types, verdict writer, registry read API, `pins.py`); AUT-1 (C1 including `forecast_input_sha256` and `LifecycleEvent`); AUT-2 (C2, RECONCILIATION, the 14:15Z label slot); AUT-3 (C3 candidates; mint limit per forward window); AUT-5 (policy ruling; engine input journal writer); AUT-6 (`deliver_with_proof`; the intraday producer that runs `eval_staleness`) |
| Downstream | AUT-5 (consumes every C4 verdict; files the policy ruling whose AUT-4 sections are drafted in §3.10); AUT-7 (an accepted LIVE_SEQUENTIAL FAIL is a demote/rollback cause) |
| Status | PLANNING. Nothing is implemented. Every ruling text below is a DRAFT for the peer-review loop; none is decided here |

**Headline (read first).**
- AUT-4 can reach score 3 as *machinery* before the 2027-01-25 KILL, but **only if three rulings are filed first** (§6.4):
  1. `RULING_holdout_freeze_and_forward_window_2026-10-03` (owned by ARCH);
  2. R-B `PREREG_FQ_v1` (drafted here);
  3. the AUT-5 policy ruling.
- If R-B is not filed by **2026-12-01**, AUT-4 is declared **score 2**, because "every live family is evaluated on pre-registered sequential tests" would be false for FQ.
- A FORWARD_SHADOW PASS before the KILL is **impossible by arithmetic**. The binding n_min (≥ 403 independent station-days) exceeds the maximum accrual (4 stations × 72 days = 288).
- An OFFLINE_CHALLENGER PASS at materiality X = 0.0152 is implausible for any recalibration child.
- The only verdict that can reach a decisive terminal state before the KILL is LIVE_SEQUENTIAL on FQ under R-B. Its probability of doing so is 0.67–0.89 if node uptime is at least 70% (§6.3).
- Evidence class for any DONE claim: **"machinery proven, edge unproven"**.

---

## 1. Goal state

**README AUT-4 score-3 criterion (verbatim).**
> - Every candidate from AUT-3 is evaluated automatically against the current champion on pre-registered, cost-aware metrics: out-of-sample Brier/CRPS, traded-rung calibration, and EV net of fees and slippage.
> - Every live family is evaluated daily on AUT-2 labels with the pre-registered sequential tests.
> - Every result is a machine-readable, schema-versioned verdict that AUT-5 consumes.
> - Every verdict states its own power or `n_min` and its time to verdict.
>
> **Live proof:** 7 consecutive days of automatic offline and live verdicts for every live family and every new candidate, each consumed by the AUT-5 policy engine as its input record.

The plan also meets README "Scale" criteria (a)–(f) and the ARCH §5.3 window rule:
- a day counts only if it has ≥ 1 real fill or a tagged canary fill;
- a window needs ≥ 5 real fills;
- canary and drill fills never count.

**ARCH Rev 4 §10 obligations for AUT-4 (verbatim).**
> the replay-sufficiency check that admits forward-shadow tape days; station-day clustering; the measured qualifying station-days per day; the feasibility record (`n_min`, MDE at α_K, `eta_date`) handed to the policy ruling; K_max accounting; the slippage source and its `assumptions` tag; the live-sequential producer over admissible labels.

Also absorbed: Z4 (`MAX_VERDICT_VALIDITY_H`); W1 (an ATTEST cadence with no expiry gap); W7 (the forward window and the mint limit); W8 (no contention with the 16:41–16:43Z RECONCILIATION slot).

Where each obligation is met:

| Obligation | Section / WP |
|---|---|
| Replay sufficiency | §3.4, WP3 |
| Clustering | §3.2, WP2 |
| Measured qualifying rate | §6.3, WP0 |
| Feasibility record | §3.8, WP7b |
| K_max accounting | §3.5, WP5 |
| Slippage source | §3.7, WP6 |
| Live-sequential producer | §3.6, WP4 |
| Z4 | §3.1 |
| W1 | §3.9 |
| W7 | §3.5 |
| W8 | §3.9 |

---

## 2. L-1 null hypothesis and reuse

The null hypothesis is that Nautilus or existing Breezy already provides each need. r1 rows that are unchanged are listed briefly; rows new in r2 are marked **(r2)**.

| Need | Checked | Verdict |
|---|---|---|
| Statistics over shadow decisions (Brier, permutation, α ledger) | `nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer` computes realised-PnL statistics over *filled* positions. Shadow runs never fill, and nothing native does Brier, cluster permutation, LD-OBF or α spending | **The gap is real** for the statistics. Only the verdict assembly is built |
| Forward-shadow replay | `scripts/analysis/nbp_shadow_parity.py:275` `run_live_parity` (native `BacktestEngine`, real actor and strategy, refusing submit veto, Depth10-driven) | **Reuse.** Extract it (WP1) |
| Tape read | Native `ParquetDataCatalog` (`nbp_shadow_parity.py:512`) | **Reuse** |
| Sequential looks and boundaries | `settlement/current_rung_hold_v2.py:296,346,365,433,470`; `persistence/gs_boundary_artefact.py:219`; `scripts/analysis/family_tally_v2.py:625` `run_sequential_looks` (golden-pinned); `crh_group_sequential_boundaries.py:243`; `aud07_live_rule_crossing_sim.py:158,210` | **Reuse.** Extract the loop verbatim (WP1). The R-B boundary is produced and H0-validated with the existing scripts |
| Brier, reliability, calibration leg, bootstrap, degenerate-cluster refusal | `scripts/analysis/forecast_conditional_scoring.py:110,139,237,267,278,303,392,428` | **Reuse.** Extract into `scoring_core.py` |
| Market baseline, look-ahead guard | `wp7b_market_as_forecaster.py:169,232,372,475,707` | **Reuse.** Extract the pure parts |
| Replay sufficiency | `analysis/replay_sufficiency.py:651,694,207` (classifier already window-parameterised) | **Reuse.** The gap is the FQ D−1 window: add a kind-keyed window. The CRH census stays untouched |
| n_min, holdout, recalibration selection, promotion predicates | `nbp_calibration.py:309,353,273,1589`; `promotion_criteria.py:195-613` | **Reuse** as in r1 |
| **(r2) Forecast vintage at decision** | `strategy/ladder_ev/forecast_state.py:179-221` `ForecastQuantileVector.available_at_ns` (the max of the 7 variables' vintages); `:306-321` `value_at` admits only `available_at_ns <= now_ns`; `persistence/nbp_derived_store.py:142-153` `available_at_ns = max(LastModified, cycle + floor)`; `:196-243` `dedupe_rows` (a retransmission can change the archived winner) | **Reuse** the vintage. `leakage.assert_forecast_available_at` is a thin assertion over it. The C1 field `forecast_input_sha256` (ARCH C1) is the parity key (E13) |
| **(r2) Per-child timeout and peak RSS** | `scripts/analysis/replay_daily_runner.py:1014-1085` `_run_subprocess_with_rss` (returns peak RSS); `:1395-1484` `driver_timeout_s` → `exception_type="DRIVER_TIMEOUT"` (L-53) | **Reuse.** Extract it verbatim into `breezy.analysis.autonomy.subprocess_rss` so the code falls under the producer pins. Add the share watchdog (E8) |
| **(r2) Slippage floor** | `docs/evidence/RULING_AUD-12a_slippage_allowance_2026-09-27.md`: 0.01 conservative allowance; live qty-1 slippage measured as 0 on all 8 fills; scoped to `current_rung_hold` | **Reuse** as the floor of the proxy. Extending it to FQ needs ruling text (R-E) |
| **(r2) Live IOC fill outcome** | The exec store `exec/polymarket_us/intent/history/*` field `retirement_reason` (`ACCEPTED_WITH_DURABLE_FILL`, `STATUS_REPORT_ZERO_FILL_TERMINAL`); `fill_by_day/<date>` index | WP0 baseline only (read-only). In production the fill rate comes from C1 `TrySubmit` + `LifecycleEvent` and C2. **AUT-4 never imports the exec store** (lint-imports) |
| Verdict writer, registry reader, plug-in registries | ARCH-0 `persistence/autonomy/` | **Consume.** AUT-4 writes no new store |

---

## 3. Design

### 3.1 Contracts; rules common to every producer

**Contracts.**
- **Consumes:**
  - C1: `DecisionRecord` Take/TrySubmit with `eval_ns`, `depth_ref`, `p_hat` and `forecast_input_sha256`; `LifecycleEvent`; `drill`; `source`.
  - C2: admissible rows only.
  - C3: `forward_eval_start_utc`, `train_end_exclusive_utc`, `leakage_assertions`.
  - C5, read-only: fold at `now`; `lineage_counters.candidates_evaluated`, `holdout_opens`, `alpha_spent`.
  - C6: the `Evaluator` slot.
- **Provides:**
  - C4 kinds `OFFLINE_CHALLENGER`, `FORWARD_SHADOW`, `LIVE_SEQUENTIAL`;
  - `HEALTH` detectors `eval_completeness`, `feasibility_consistency`, `eval_excluded_fraction`, `eval_n_stalled`, `eval_resource_creep` (§3.11);
  - the VERDICT-class detector function `eval_staleness`, which the AUT-6 intraday producer runs (§3.9).

**Bound subject sha (Z1).** Every verdict's `subject_artefact_sha256` is the family's bound sha from its BOOTSTRAP or MINT row in the fold.

**Validity anchored to the slot (Z4, E5).**
- Each producer has a module constant `SLOT_UTC`. A contract test asserts it equals the unit's `OnCalendar`.
- `valid_until_ns = slot_start_ns(today) + VERDICT_VALIDITY_H·3600·10⁹`, with `VERDICT_VALIDITY_H = 26`.
- The producer refuses (ERROR) if `produced_at_ns < slot_start_ns`, which would mean a manual early start. A late start is bounded by `flock -w` + `RuntimeMaxSec`.
- Therefore `valid_until_ns − produced_at_ns ≤ 26 h = MAX_VERDICT_VALIDITY_H` always, independent of jitter.
- Timers set `AccuracySec=1s`, `RandomizedDelaySec=0` and `Persistent=false`. A missed run is not caught up late; `eval_staleness` reports it instead.
- Tests: `test_validity_anchored_to_slot_never_exceeds_ceiling` and `test_worst_case_start_jitter_bounded` (`W + RuntimeMaxSec + AccuracySec` per unit, read from the unit file).

**Verdict identity (E20).**
- `verdict_id = sha256(canonical_body − {verdict_id, produced_at_ns})`. `valid_until_ns` is slot-anchored, so it is deterministic and stays in the hash.
- A recompute on the same inputs therefore yields the same id. The append-only writer treats a byte-equal body (modulo `produced_at_ns`) as an idempotent no-op, and refuses a differing body under the same id.
- `inputs[]` carries `{path_role, sha256}` for every dataset:
  - `label_set` (sha over the sorted C2 file shas);
  - `archive_dataset` (NBP derived partitions);
  - `tape_snapshot` (sha over the sorted `(instrument_id, file sha)` of the Depth10 parquet read);
  - `boundary_artefact`;
  - `family_prereg`;
  - `fs_replay_output` (§3.7);
  - `sigma_source`.
- Test `test_producer_recompute_identical_modulo_time`. This deviates from ARCH C4's "sha of the canonical body"; see P4-11 in §10.

**Single-look discipline.**
- OFFLINE stage 2 and FORWARD_SHADOW are evaluated confirmatorily **once**, at the first run where the deff-inflated `n_min` is met (and, for FORWARD_SHADOW, both predicate n's, §3.7).
- Before that the verdict is `UNDERPOWERED`, with counts only: no estimate, interval or p-value.
- FAIL or INCONCLUSIVE at the single look is final for that candidate.

**Fail-closed.**
- Any missing, stale, unknown-version or unverifiable input, any failed leakage assertion, and any producer exception all yield `ERROR`, plus a CRITICAL through `deliver_with_proof` (Z13).
- `UNDERPOWERED`, `INCONCLUSIVE` and `ERROR` never promote.

**Payload hygiene.** There are no paths in verdicts. `test_autonomy_payload_hygiene_scan` covers the AUT-4 writers.

### 3.2 Clustering, the design effect and the family pin

- **The unit is the independent station-day** (Y14). A `(station, climate_day)` is one cluster, and `assert_nondegenerate_clustering` refuses a degenerate key.
- **Primary decision statistic (E9).** A **studentised date-cluster sign-flip permutation test**, one-sided at α_k:
  - Paired per-station-day differences are summed within each climate date. Each date's sign is flipped as a block, which preserves the intra-date correlation across stations.
  - B = max(10 000, ⌈200/α_k⌉) seeded flips (seed `roi_bound.SEED`), or exact enumeration when the number of date clusters C ≤ 20.
  - A test runs only if `C ≥ C_min(α_k) = ⌈log2(10/α_k)⌉`, so that the smallest attainable p is ≤ α_k/10. Otherwise the outcome is `UNDERPOWERED(min_clusters)`.
  - Example values: C_min = 10 at α_1 = 0.0125 and 13 at α_4 = 0.0015625.
  - The pinned percentile bootstrap (`roi_bound.py:93,97`) is kept for the **descriptive** CI only.
  - Stated assumption: the sign-flip null is symmetric about 0 under H0. Studentising makes it robust to a variance difference.
- **Design effect (E10).**
  - `deff = 1 + (m̄ − 1)·ρ̂`, where m̄ is the mean number of admissible station-days per date and ρ̂ is the intra-date correlation of the paired difference.
  - ρ̂ is measured in WP0 on **out-of-fold** archive differences before 2026-07-01.
  - `n_min_eff = max(⌈deff·n_min⌉, 4·C_min)` station-days. It is fixed at nomination and written into the stage-1 verdict; it is never recomputed on forward data.
- **Cluster sensitivity.** The same test is also run with station-day blocks. If the two decisions disagree, the outcome is `INCONCLUSIVE(cluster_sensitivity)`, and **at the single look that is final** (E10).
- **Family pin.** The closed `metric_registry` tags every metric `event_family="rung_2f_traded"`, and the median binary is refused (bss-headline lesson). `calibration_leg_rung` and `underconfidence_mean_signed_dev` are always reported.

### 3.3 Modules (all in the analysis layer; never imported by live packages)

r1 modules are kept. Changes in r2:

| Path | Purpose |
|---|---|
| `src/breezy/analysis/scoring_core.py`, `sequential_looks.py`, `market_events.py`, `autonomy/shadow_replay.py` | Verbatim extractions, as in r1 |
| `src/breezy/analysis/autonomy/subprocess_rss.py` **(r2)** | Verbatim extraction of `_run_subprocess_with_rss`; `replay_daily_runner.py` re-imports it. New `run_with_rss_share(argv, timeout_s, rss_share_bytes)`: a 1 s RSS poll that kills the child at its share (§3.12) |
| `autonomy/eval_stats.py` | `alpha_k`, `alpha_spent_lifetime`, `n_min_one_sided`, `mde_one_sided`, `deff`, `n_min_eff`, `c_min`, `eta_days`, `eta_date`. z-quantiles are pinned literals |
| `autonomy/permutation.py` **(r2)** | `date_cluster_signflip(diffs_by_date, alpha, seed, b)` → `(stat, p, n_dates)` |
| `autonomy/metric_registry.py` | Closed metric names, `n_unit`, family tag; **per-kind required-field table** (§3.1a) |
| `autonomy/windows.py` | `decision_window_ns(kind, …)`. FQ uses the D−1 local-standard-day window ∩ the permit window. `assert_instant_in_window` checks local date **and** hour |
| `autonomy/leakage.py` | `assert_ref_before_take` (strict `<`); `assert_forward_day`; `assert_not_sealed(day, bounds)`, with bounds from the named holdout ruling; `assert_prescreen_pre_holdout`; **(r2)** `assert_forecast_available_at(vintage_ns, eval_ns)` (`vintage_ns ≤ eval_ns`, else `LeakageError`) |
| `autonomy/tape_admission.py` | FQ replay sufficiency, largest-item guard and **oversize quarantine** shared with `replay_daily_runner` (E17) |
| `autonomy/alpha_ledger.py` | Lifetime k, `forward_window_index(day)` (also imported by AUT-3's mint path), k_in_window, registry cross-check (§3.5) |
| `autonomy/fill_model.py` **(r2)** | Live IOC fill rate from C1 TrySubmit + LifecycleEvent; an unresolved AMBIGUOUS counts as a miss. Slippage proxy with floor and SE (§3.7) |
| `autonomy/evaluators/forecast_quantile_ladder.py` | `FqEvaluator` (C6) |
| `autonomy/feasibility.py` | Feasibility record (§3.8) |
| `autonomy/health.py` **(r2)** | `eval_staleness` (VERDICT detector run by AUT-6) and the self-monitoring HEALTH builders (§3.11) |
| `autonomy/producers/eval_live.py` | LIVE_SEQUENTIAL + `eval_completeness`(live) + `eval_n_stalled` |
| `autonomy/producers/eval_offline.py` | OFFLINE_CHALLENGER, FORWARD_SHADOW scoring, feasibility, the remaining HEALTH detectors. **Imports no strategy module** (E21) |
| `autonomy/producers/fs_replay.py` **(r2)** | Child entry: replays one (family, station-day) through `shadow_replay` and writes `derived/autonomy/fs_replay/<family>/<day>/<station>.jsonl` (0444) stamped with its own closure sha. It is a separate pin, `PRODUCER_SOURCE_SHA256["fs_replay"]` |

#### 3.1a Required fields per verdict kind (E6)

`—` means the field is null and carries the literal reason given.

| Field | OFFLINE stage 1 | OFFLINE stage 2 | FORWARD_SHADOW | LIVE_SEQUENTIAL | AUT-4 HEALTH |
|---|---|---|---|---|---|
| `n`, `n_unit` | archive station-days | forward station-days | admissible station-days (a); `n_b` in metrics | combined station-day draws | — |
| `n_min` | — `PRESCREEN_NO_TEST` | `n_min_eff` at α_k | `n_min_eff` for (a); `n_min_b` in metrics | registered `n_max` (or reason `NO_REGISTERED_PREREG`) | — `HEALTH_NO_TEST` |
| `power` | — | 0.80 (design) | 0.80 (design) | registered design power | — |
| `mde` | — | `mde_one_sided(σ_oof, n_min_eff, α_k)` | the same for (a) | registered MDE | — |
| `comparator_family_id` | champion | champion | literal `MARKET_ASK_IMPLIED`; (c) uses the champion in metrics | literal `BREAK_EVEN` | — |
| `alpha_spent` | lineage cumulative, unchanged | lineage cumulative including this candidate's α_k | **same α_k as stage 2**: PROMOTE needs both PASSes (intersection-union), so one charge per candidate | LD-OBF cumulative α at the current information fraction (`metrics.alpha_scope="family_prereg"`) | — |
| `prereg_ruling_sha256` | policy ruling sha | policy ruling sha | policy ruling sha | **family PREREG sha (R-B)** | policy ruling sha |
| `eta_to_verdict_days` | 0 | `eta_days(n_min_eff, n, rate)` | max over predicates | from registered looks | — |

**Before a ruling is filed (E6).**
- With no policy ruling, `prereg_ruling_sha256 = null` and `assumptions ∋ no_policy_ruling`.
- With no family PREREG, the LIVE_SEQUENTIAL outcome is `INCONCLUSIVE(NO_REGISTERED_PREREG)` with `prereg_ruling_sha256 = null`.
- **Engine treatment (contract to AUT-5):** a null sha fails acceptance. The verdict is journaled `REJECTED(no_ruling)` (§3.13) and never acts.
- Test: `test_verdict_v1_schema_complete_per_kind`.
- ARCH conflict: LIVE_SEQUENTIAL carries the family PREREG sha, not the policy sha (P4-10).

### 3.4 Replay sufficiency for forward-shadow tape days

A `(station, climate_day)` is admissible only if all eight conditions hold. Each refusal is named in `metrics.days_excluded_by_reason`, never imputed:
1. `FINAL` label present.
2. The FQ-window census row passes `is_replayable_whole_day`. A `window_complete=False` row is pending.
3. The day is not in `replay/replay_drift.jsonl`.
4. **Largest-item guard (L-53):** Depth10 bytes ≤ `FORWARD_SHADOW_MAX_DAY_BYTES` (from WP0). Above it, the day is excluded as `TAPE_DAY_OVERSIZE` with an alert.
5. **Replay fidelity:** live C1 Takes ⊆ replay Takes on `DecisionKey`. Replay-only takes need a live `EntryVeto`/`TrySubmit` refusal or the budget stop to explain them. Otherwise the day is `REPLAY_PARITY_MISMATCH`.
6. **(r2, E13) Forecast parity:**
   - For every replay Take, `assert_forecast_available_at(vector.available_at_ns, eval_ns)` must hold. A failure is a `LeakageError` → ERROR + CRITICAL.
   - For every live-matched Take, the replay `forecast_input_sha256` must equal the live C1 value. A mismatch excludes the day as `FORECAST_INPUT_MISMATCH`, for example when an archive retransmission winner differs from what live saw (`nbp_derived_store.py:196-243`).
7. The day is ≥ `forward_eval_start_utc` and ≥ 2026-10-02. It is outside the frozen holdout [2026-07-01, 2026-10-02) of `RULING_holdout_freeze_and_forward_window_2026-10-03`.
8. **(r2) The child completed within its timeout and RSS share.** Otherwise the day is excluded as `REPLAY_TIMEOUT` / `REPLAY_RSS_SHARE`.

**Excluded-day bias guard (E17).**
- Every verdict reports `metrics.excluded_fraction_by_station`.
- At the single look, if any station's excluded fraction exceeds `EXCLUDED_FRACTION_MAX` (proposed 0.25), the outcome is `INCONCLUSIVE(exclusion_bias)`, which is final. Exclusions may correlate with outcome; for example, volatile days have the largest tapes.

**Oversize quarantine (E17).**
- `tape_admission.quarantine_oversize(station, day, reason)` appends to `derived/replay/oversize_quarantine.jsonl`. It is append-only, single-writer per file, and has one file per consumer, so it raises no L-50 race.
- WP3 adopts it in `replay_daily_runner.run_batch` as well. A `DRIVER_TIMEOUT` station-day (the MIA 2026-09-29 shape) is quarantined by name with an alert, and it is not retried on every run.
- The CRH census that feeds the KILL clock is untouched.

**FQ census.** As in r1: `derived/replay/replay_sufficiency_fq.jsonl` is a separate file, written inside `eval_offline`.

### 3.5 OFFLINE_CHALLENGER, α and K_max accounting

**Stage 1: pre-screen (no α, no k).** This runs on archive days before 2026-07-01 only.
- *Archive-CV stability:* rolling-origin folds by date, F = 6. Selection is re-run per fold. Metric: `prescreen_fold_wins`.
- *Distinctness:* `NOT_DISTINCT` if every |paired difference| < 1e-6.
- *Leakage:* `assert_prescreen_pre_holdout`; every C3 assertion is `passed`.
- **(r2, E19)** `σ_oof` is the station-day SD of the **out-of-fold** paired Brier difference (candidate − champion) across the 6 folds' held-out blocks. It is never an in-sample SD. `ρ̂` (§3.2) comes from the same out-of-fold differences.
- **(r2, E6)** Stage 1 writes `n_min_eff`, `mde` and `C_min` for its future k into `metrics`, so the test is pre-registered per candidate before any forward day is read.
- **Outcomes:**
  - `FAIL(stage=prescreen)` if `prescreen_fold_wins < PRESCREEN_MIN_FOLD_WINS`;
  - `INCONCLUSIVE(NOT_DISTINCT)`;
  - otherwise **nominated**.

**α spending (E1): lifetime geometric, never reset.**
- `k` is the **lifetime** index of nominated candidates in the lineage:
  - `α_k = α_total·2^−k`;
  - `alpha_spent(lineage) = α_total·(1 − 2^−k_max_assigned)`;
  - Σα < α_total for the whole life of the lineage. There is no epoch and no reset.
- `k_in_window` counts nominated candidates within the candidate's forward window (below) and is checked against K_max.
- Both fields go in `metrics`; `alpha_spent` goes in the C4 field.
- **k assignment** = 1 + max(the registry's `lineage_counters.candidates_evaluated`, the count of this lineage's stage-2-assigned verdicts in the append-only verdict store).
- **Cross-check.** The registry value must satisfy `store_count − pending ≤ registry ≤ store_count`, where `pending` counts store verdicts produced after the last engine pass in the journal (§3.13). The registry's `alpha_spent` must equal `α_total·(1 − 2^−registry_count)` exactly (`Decimal`). Any other value is an ERROR.
- Mints are ≤ 1 per lineage per day (code ceiling), so there is never a same-day k collision.
- Test `test_alpha_spent_lifetime_never_exceeds_total`.

**Forward window and K_max (W7; the mint-limit option chosen, coordinated with AUT-3).**
- The window length is `FORWARD_WINDOW_DAYS`, set in the policy block. Proposed: 28.
- The new `pins.py` ceiling `FORWARD_WINDOW_DAYS_MIN = 28` permits the policy only to lengthen it (the stricter direction; the Y22 test treats "shorter" as looser).
- Windows are anchored to the fixed origin 2026-10-02: `forward_window_index(day) = (day − 2026-10-02).days // FORWARD_WINDOW_DAYS`.
- **AUT-3 limits mints to K_max per lineage per window**, using this same function imported from `alpha_ledger`. Pre-screen failures consume mint slots. So `k_in_window ≤ K_max` by construction, and the engine's C4 "k > K_max → ERROR" rule is never the normal path.
- **Defensive guard:** if `k_in_window > K_max` ever appears (a contract breach), the verdict is `ERROR(k_exceeded)` with a CRITICAL, it counts as consumed, and no test runs. This is a breach detector, not a second policy option.

**Stage 2: confirmatory on the rolling forward holdout.**
- Forward station-days are ≥ max(`forward_eval_start_utc`, 2026-10-02), weather-only: all 4 stations every day.
- At the single look the test is the §3.2 permutation test at α_k on `brier_rung_diff_vs_champion`.
- Also reported: `crps_tmax_diff_vs_champion` (non-inferiority), the calibration conjunct (R-C, §3.10), `underconfidence_mean_signed_dev`, and cluster sensitivity.
- PASS iff:
  - p ≤ α_k with the effect in the candidate's favour,
  - the R-C relative calibration conjunct holds,
  - cluster sensitivity agrees,
  - the exclusion guard passes.

**Holdout (E12).**
- AUT-4 consumes `RULING_holdout_freeze_and_forward_window_2026-10-03` by name and restates no version of it. The archive holdout is frozen at [2026-07-01, 2026-10-02) and sealed for one final confirmatory use, which AUT-4 never makes. Its producers never call `open_holdout` (test `test_producers_never_open_holdout`).
- **Contamination disclosure.** The September tape studies (WP-7b, AUD-02, the 09-20 terminal finding) already touched [07-01, 10-01). Any S2 on that window is descriptive only.
- AUT-4's FORWARD_SHADOW planning σ (0.099) comes from the **published** AUD-02 figure on that window, with no new read. The feasibility record carries `sigma_source_contaminated: true`.
- Until the ruling is filed, `assert_not_sealed` treats every day ≥ 2026-07-01 as sealed, and OFFLINE stage 2 and FORWARD_SHADOW verdicts are `INCONCLUSIVE(SEALED_WINDOW)`.

**Drill child (Z2).** A byte-identical child gets `INCONCLUSIVE(NOT_DISTINCT)` with `assumptions ∋ drill`. It never receives a k and never spends α.

### 3.6 LIVE_SEQUENTIAL over admissible labels

As in r1:
- Inputs: admissible, `window_complete` C2 rows, combined with `combine_station_day` (L-40 exact variance).
- The extracted `run_sequential_looks` runs with the family's **registered** boundary artefact.
- Mapping: CONTINUE→UNDERPOWERED; SURVIVE→PASS; KILL→FAIL; refusal→ERROR.
- Families are enumerated from the fold. A `RefusingPlugin` kind gets ERROR.

Changes in r2:
- **R-B is a hard prerequisite of the live proof (E2).** Until R-B is filed and its boundary sha is committed, FQ is `INCONCLUSIVE(NO_REGISTERED_PREREG)`. This is honest, but a window of such verdicts **does not count toward the live proof** (§6.4).
- **Prefix exclusion (E16).** FQ fills with `climate_day < D0′` never enter n, any look, or boundary calibration. They are tagged `metrics.prefix_excluded_count`.
- **Schedule (E4).** The unit has its own lock (§3.9). It runs after the AUT-2 14:15Z label slot and records the label-set sha it read.

### 3.7 FORWARD_SHADOW and the slippage source

**Subjects (E2).** Every CHALLENGER-state family, plus a daily **champion baseline**: subject = the champion, comparator = `MARKET_ASK_IMPLIED`, `declared_action_class = NONE`, never a promotion input. The baseline exercises the full replay→score→verdict path on live tape every day while `promote_enabled=false`.

**Replay.** A per-(family, station-day) `fs_replay` child (§3.12) writes the shadow Takes. `eval_offline` scores them and cites `fs_replay_output` and `shadow_replay_code` (the child's closure sha, which must be in the `fs_replay` pin set) in `inputs`.

**Predicates.** All are required (an intersection-union test, so each is tested at the same α_k with no split).
- **(a)** `brier_rung_diff_vs_market < 0` by the §3.2 permutation test at α_k. n = admissible station-days with ≥ 1 scorable rung event.
- **(b) (E18)** Effective EV per take has a one-sided (1 − α_k) lower bound > 0.
  - The statistic is `ev_eff = p̂_fill·ev_cond`, with `ev_cond = held − ask − θ·ask·(1−ask) − slippage_proxy`. θ is the manifest `taker_fee_coefficient`.
  - The per-station-day mean ev_cond goes through the date-cluster sign-flip test at α_k, giving a lower bound LB_ev.
  - Then `LB_eff = (LB_ev − z_{α_k}·SE_proxy)·p_fill_LB` if `LB_ev − z·SE_proxy > 0`; otherwise (b) fails.
  - `p_fill_LB` is the Wilson lower bound at (1 − α_k) of the live FQ IOC fill rate (trailing 28 days, C1/C2).
  - n_b = station-days with ≥ 1 challenger take. `n_min_b = n_min_eff(σ_ev, X_EV, α_k)`, with `X_EV` = 0.02 per contract (policy value, R-D) and σ_ev measured out-of-fold on champion replay days before the candidate's forward start.
  - **n mismatch rule:** the single look fires only when `n_a ≥ n_min_a` **and** `n_b ≥ n_min_b`. Until then the verdict is UNDERPOWERED, with `eta = max(eta_a, eta_b)`. If (a) is powered but (b) cannot be powered before the candidate's window ends, the outcome is `INCONCLUSIVE(b_underpowered)`, final.
- **(c)** The relative calibration conjunct (R-C) against the champion on the same admissible days.
- **(d)** `n ≥ n_min_eff` in independent station-days.
- `resolution_diff_vs_market` (Murphy) is reported.

**Slippage source (E3).**
- `slippage_proxy = max(0.01, mean_slip + z_{α_k}·SE_slip)`. The 0.01 floor is the AUD-12a ruled allowance. `mean_slip` and `SE_slip` come from C2 `slippage` over the champion's admissible fills in the trailing 28 days, matched via C1 `depth_ref`.
- With fewer than `N_PROXY_MIN = 30` admissible champion fills in the window, the verdict is `INCONCLUSIVE(PROXY_UNDERPOWERED)` and no `ev_net` is computed. At the measured ~6 fills/day (§6.3) this clears in about a week of uninterrupted trading.
- Tags:
  - `assumptions: [slippage_champion_proxy, slippage_floor_aud12a, fill_survivorship_unmodelled]`;
  - without R-E acceptance → `INCONCLUSIVE`.
- **Survivorship disclosure.** Slippage and ev_cond are observed only on IOCs that filled. A miss (the ask moved or vanished) yields no position, and misses may be disproportionately the favourable decisions (informed flow lifted the ask first). The `p_fill` haircut scales the EV but does **not** correct this adverse selection. So (b) can overstate EV, and the verdict says so.
- An unresolved AMBIGUOUS IOC counts as a miss in `p_fill` (strict-zero-fill lesson).

### 3.8 Feasibility record

`evidence/autonomy/feasibility/feasibility_<YYYY-MM-DD>.json` (0444), written daily by `eval_offline`, carries the r1 keys plus:
- `deff`, `rho_hat`, `rho_source_sha256`;
- `c_min_k1`, `c_min_K`;
- `fill_rate_live`, `fill_rate_wilson95`, `n_ioc`;
- `n_proxy_fills`;
- `forward_window_days`, `windows_before_kill`;
- `sigma_source_contaminated`;
- `p_terminal_live_sequential_by_kill` at `u ∈ {0.5, 0.6, 0.7, 0.8, 0.9}`;
- `per_candidate: [{family_id, k, k_in_window, alpha_k, n_min_eff, eta_date}]`.

Rules:
- `rate` = trailing-28-day admissible FQ-window station-days / 28, `window_complete` only.
- **`feasibility_consistency` (E14):** FAIL if the policy block has `promote_enabled=true` and, for **any** live CHALLENGER, `eta_date(its assigned k) ≥ kill_date`. The check is per assigned k, not at k = 1.
- The record also reports MDE at the deepest k reachable before the KILL: `K_max × windows_before_kill`, which is 20 at 28-day windows. See P4-8.

### 3.9 Schedule, locks and the ATTEST interaction (E4, E5, W1, W8)

| Unit | OnCalendar (UTC) | Lock / `-w` | RuntimeMaxSec | Worst end | MemoryMax |
|---|---|---|---|---|---|
| `breezy-autonomy-eval-offline` | 11:00 | `breezy-studies.lock`, 900 s | **9000 (2.5 h ≤ 3 h)** | 13:45 | 12G (§3.12) |
| `breezy-autonomy-eval-live` | 14:45 | **own** `breezy-autonomy-eval-live.lock`, 300 s | 1200 | 15:10 | 1G (counted in the §5.2 ≤ 4G own-lock budget) |

The neighbouring slots are owned by other plans:
- AUT-2 labels, 14:15 (studies lock);
- daily engine, 15:30;
- canary, 15:45;
- AUT-2 post-STOP RECONCILIATION, 16:41–16:43 (own lock, W8);
- pre-launch pass, 16:45.

Margins:
- `eval_offline` ends 30 min before the 14:15 label slot and 1 h 45 min before the engine.
- `eval_live` ends 20 min before the engine and 1 h 20 min before the 16:30 study cut-off, so it never meets the W8 slot.

**Contract test (E4):** `tests/contract/test_autonomy_units.py::test_units_do_not_contend_on_flock`. It parses every `deploy/systemd/breezy-*.{service,timer}` for `OnCalendar`, the flock lock name, `-w` and `RuntimeMaxSec`, and asserts:
1. No two units sharing a lock have overlapping `[start, start + W + RuntimeMaxSec]` windows.
2. Every study ends before 16:30Z.
3. Every AUT-4 unit ends ≤ 15:15Z (15 min before the engine).
4. No AUT-4 window intersects 16:30–17:00Z or the W8 slot.

Also `::test_eval_live_starts_after_label_slot_ends`.

**Consumption invariant (E5).** For each AUT-4 kind, every consuming pass instant t must satisfy `slot + W + RuntimeMaxSec ≤ t ≤ slot + 26 h`.
- Daily engine at 15:30: holds for both units.
- Pre-launch pass at 16:45: holds for offline (11:00 + 26 h = 13:00 next day > 16:45 today).
- `eval_offline`'s next-day verdict can land after its predecessor's 13:00 expiry, leaving a gap of up to 45 min with no valid offline verdict. **Stated and harmless:** OFFLINE and FORWARD_SHADOW only gate PROMOTE, which the daily pass evaluates at 15:30, and nothing restrictive depends on them.
- Test `test_consumption_instants_inside_validity`.

**ATTEST (W1).**
- AUT-4's daily verdicts (26 h) are **not** cited by ATTEST. Citing them would recreate the W1 expiry gap under a 6-hourly ATTEST with 8 h validity.
- Instead AUT-4 supplies `health.eval_staleness(fold, verdict_store, now_ns)`, a C6 `VERDICT` detector of the freshness class. The **AUT-6 intraday producer** evaluates it each pass and writes a HEALTH verdict with 8 h validity.
- It FAILs if any CHAMPION/HALTED family lacks a valid LIVE_SEQUENTIAL verdict after `14:45 + W + RuntimeMaxSec + 15 min`, or if any producer's newest verdict has expired.
- The policy proposal puts `eval_staleness` in the ATTEST-required set, so a dead evaluator blocks ATTEST. The node's `registry_attest_expired` then vetoes entries within one ATTEST validity. This is fail-closed.
- Invariant (W1): the ATTEST period (6 h) + the production→ATTEST lag (≤ 5 min intraday cadence + 150 s stagger) ≤ 8 h validity, with ≥ 1.5 h margin.
- Test `test_attest_cadence_has_no_expiry_gap_with_eval_staleness`, which AUT-4 contributes over the schedule table.
- ARCH conflict: ARCH's `attest_required_verdict_kinds` is kind-level (P4-7).

### 3.10 Ruling drafts (NOT decided; for the AUT-5 policy ruling and its peer review)

**Holdout.** There is no AUT-4 text. AUT-4 consumes `RULING_holdout_freeze_and_forward_window_2026-10-03` (ARCH-owned). r1's R-A is **withdrawn**.

**R-B `PREREG_FQ_v1` (sequential).**
> "Statistic S_k/I_k as `combine_station_day`/`score_combined`. LD-OBF spending, one-sided α = 0.025, a look every 10 combined station-days, n_max = 160, loss stop ΣPnL ≤ −60 contract-units.
>
> D0′ = the climate day after this ruling is filed. Every FQ fill with climate_day < D0′ (from the first FQ LAUNCH, 2026-10-01 ~16:00Z, climate day 2026-10-02) is a diagnostic prefix. It is excluded from n, from every look and from boundary calibration.
>
> The design parameters above were committed as `docs/evidence/PREREG_FQ_v1_design_<date>.json`, sha256 `<sha>`, before AUT-2a's first FQ label run and before any agent drafting this ruling queried FQ realised PnL. Changing any parameter after that commit voids this ruling and requires a new design commit and a new D0′.
>
> The boundary artefact is produced by `crh_group_sequential_boundaries.py` and validated by a seeded H0 Monte-Carlo that replays the live look loop verbatim, including mixed YES/NO station-days (L-40 ii, L-41). It is used only if Var(S_terminal) ≈ 1 and the one-sided crossing rate ≤ α + MC slack.
>
> KILL → FAIL → DEMOTE (entry-only)."

**Disclosure (E16).**
- FQ prefix PnL may already be visible in the existing daily digests.
- The parameters are copied from the PREREG v2 design (LD-OBF, α 0.025, looks every 10). n_max and the loss stop were set in r1 from the pre-KILL accrual arithmetic, not from FQ outcomes, so no free parameter is chosen after seeing the prefix.
- The r2 author read **counts only** from the exec store (no price, cost or PnL field).

**R-C, the calibration conjunct (relative; E11).** This replaces r1's absolute-leg loosening.
> "On the verdict's own evaluation set, the candidate's calibration is **not worse than the champion's**:
> (i) the max over buckets with n ≥ 30 of |obs − pred| for the candidate ≤ the champion's + 0.01;
> (ii) |mean signed deviation| for the candidate ≤ the champion's (under-confidence reduced or unchanged).
> The absolute leg (`evaluate_calibration_leg`, ε = 0.05) is reported, never gated."

The conjunct is fixed before any forward data exists. It never relaxes an absolute threshold after the rung family's known failure (FC_0b: 3/5 buckets failing).

**R-D, α and candidates (E1, W7).**
> "α_total = 0.025 one-sided, spent **lifetime-geometrically per lineage**: α_k = α_total·2^−k over all nominated candidates for the lineage's whole life, with no reset.
> K_max = 4 nominated candidates per lineage per forward window.
> `FORWARD_WINDOW_DAYS` = 28 (≥ the pins floor), anchored at 2026-10-02.
> AUT-3 mints ≤ K_max per lineage per window.
> Pre-screen and NOT_DISTINCT verdicts spend no α and assign no k.
> `PRESCREEN_MIN_FOLD_WINS` = 4 of 6.
> X = 0.0152 (Brier), X_EV = 0.02 per contract.
> `EXCLUDED_FRACTION_MAX` = 0.25; `N_PROXY_MIN` = 30.
> PROMOTE requires OFFLINE stage-2 PASS ∧ FORWARD_SHADOW PASS, one α_k charge per candidate."

**R-E, slippage (E3).**
> "`slippage_champion_proxy` is accepted for challengers whose manifest equals the root's except for the §4.2 allowlist. The proxy is max(AUD-12a 0.01, mean + z_{α_k}·SE). EV is haircut by the Wilson lower bound of the live IOC fill rate. The fill-survivorship bias is disclosed and unmodelled. Refused below N_PROXY_MIN fills."

**R-F, feasibility.** The §3.8 record at filing. With today's numbers, `promote_enabled=false`.

**R-G, CHALLENGER admission (E2).**
> "SHADOW→CHALLENGER (non-sender, non-widening, never counted) is admitted on an OFFLINE stage-1 *nominated* verdict with no ERROR. CHALLENGER→CHAMPION needs R-D's PROMOTE conjunction and `promote_enabled`."

This lets FORWARD_SHADOW verdicts flow for real candidates while promotion is disabled.

### 3.11 Evaluator self-monitoring (E22)

Every row below is a HEALTH verdict, written daily by the named unit unless stated.

| Detector | Producer | FAIL condition | Proposed action class |
|---|---|---|---|
| `eval_completeness` | each unit | a fold family or a candidate lacks today's verdict of a required kind | ALERT |
| `eval_excluded_fraction` | eval_offline | trailing-7-day excluded fraction > 0.5 overall or > `EXCLUDED_FRACTION_MAX` for any station | ALERT |
| `eval_n_stalled` | eval_live | a CHAMPION family with ≥ 1 real fill per day for 5 consecutive qualifying days has had LIVE_SEQUENTIAL n unchanged for those 5 days (labels not flowing) | ALERT |
| `eval_resource_creep` | each unit | wall time > 0.8 × RuntimeMaxSec, or peak RSS > 0.8 × MemoryMax (parent) or > 0.8 × child share, on 2 of the last 3 runs | ALERT |
| `eval_staleness` | AUT-6 intraday producer (function from AUT-4) | §3.9 | ATTEST-required → entries vetoed on expiry |

**Pin mismatch.** A producer whose closure sha is unpinned refuses to start. It sends a CRITICAL through `deliver_with_proof`, and `eval_staleness` then FAILs, because an unpinned producer cannot write an acceptable verdict.

### 3.12 Memory and runtime budget (E8)

**Budget.**
- Host studies cap: 16G per studies-flock holder (ARCH §5.2).
- `eval_offline` `MemoryMax=12G`, split as:
  - parent ≤ 2G;
  - pre-screen phase ≤ 4G, run **sequentially before** any replay child;
  - replay phase: P concurrent `fs_replay` children with RSS share S each.
- Constraint: 2G + max(4G, P·S) ≤ 12G ≤ 16G.
- **Default** P = 2, S = 4G (the existing `breezy-replay-daily.service` single-day cap: `MemoryMax=4G`, `MemoryHigh=3G`) → 2 + 8 = 10G, 2G margin.

**WP0-derived values.** R = the measured worst single-station-day `shadow_replay` peak RSS, starting with MIA 2026-09-29.
- S = ⌈1.25·R⌉.
- If S ≤ 4G: P = 2.
- If 4G < S ≤ 9G: P = 1.
- **If S > 9G: hard fail.** WP6 does not merge, and the plan returns to review (largest-item guard tightened, or day-splitting designed).

**Enforcement.**
- The share is enforced in-process by `run_with_rss_share`, which kills at S and excludes the day as `REPLAY_RSS_SHARE`.
- The hard bound is the service cgroup's 12G. Children stay inside the service cgroup (no `systemd-run` scope that could escape the slice).
- Pre-screen RSS is measured in WP0. If the pre-screen peak exceeds 4G, the plan hard-fails the same way.

**Runtime.**
- Replays per day = 4·(C + 1) (C challengers plus the champion, which serves both fidelity and the baseline).
- Budget: 9000 s × P ≥ 4·(C + 1)·t_p95 + prescreen_s + scoring_s.
- At t = 360 s (the timeout) and P = 2: C ≤ 10. CHALLENGERs are bounded by K_max per window, so C ≤ 4 per lineage.
- A missed day queues: oldest first, at most 3 backlog days per run. Backlog is reported in `eval_completeness`.

### 3.13 Engine input journal: the cross-AUT contract AUT-4 owns (E7)

ARCH defines no record of what the engine *read*. This plan fixes the schema; AUT-5 writes it. The ARCH gap is reported as P4-9.

**`engine_input/v1`.** One JSONL file per pass: `evidence/autonomy/engine_inputs/<venue>/<YYYY-MM-DD>/<pass_mode>_<pass_ts_ns>.jsonl`, 0444. The row fields are:
- `schema`, `pass_id`, `pass_mode` (`daily`|`intraday`|`prelaunch`), `venue`, `ts_ns`;
- `verdict_id`, `kind`, `subject_family_id`, `detector`;
- `acceptance` (`ACCEPTED`|`REJECTED`), `reject_reason` (closed enum: `expired`, `unpinned_producer`, `sha_mismatch`, `no_ruling`, `action_class_mismatch`, `subject_unbound`, `k_exceeded`, `input_unresolved`);
- `acted` (bool), `transition_id` (str|null).

**Contract.**
- Every verdict in `derived/verdicts/**` with `produced_at_ns` < pass start and `valid_until_ns` > pass start, for a family in the fold, appears exactly once in that pass's journal.
- Every `cause_verdict_ids` entry of a transition appears with `acted=true`.

**Tests.** `tests/contract/test_engine_input_journal_contract.py`, owned by AUT-4, runs against the AUT-5 engine on fixtures:
- `::test_every_live_verdict_journaled_once_per_daily_pass`
- `::test_cause_verdict_ids_subset_of_acted_rows`
- `::test_rejected_verdict_carries_reason`
- `::test_journal_schema_exact_keys`

Live-proof check (f) reads this journal (§6.1).

---

## 4. Work packages

**Gate commands for every WP**, run by the coordinator and never trusted from an agent:
- interpreter: `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python`;
- `scripts/ci/run_tests_no_egress.sh`, the full gate after every merge (L-43). Units are launched with `-p LimitNOFILE=524288`, with basetemp on `~/.cache`;
- `cd <tree> && lint-imports`, which must print "N kept, 0 broken";
- the mypy ratchet (in the gate).

Never `uv`/`pip` (L-51), never `git stash`. Activation is immediate on merge unless stated otherwise.

**WP0: measurements (read-only).** Output: `docs/evidence/AUT4_WP0_MEASUREMENTS_<date>.md`, with a command and source sha for every number. Items:
- (i) FQ-window replay-sufficient station-days per day, last 28 closed days.
- (ii) **Live IOC fill rate:**
  - r2 baseline, already measured read-only: 14 FQ IOC intents, 12 `ACCEPTED_WITH_DURABLE_FILL` and 2 `STATUS_REPORT_ZERO_FILL_TERMINAL`. p̂ = 0.857, Wilson 95% [0.601, 0.960];
  - FQ trials with a take: 3 station-days on climate day 10-02 and 4 on 10-03;
  - WP0 re-measures over ≥ 14 days.
- (iii) Out-of-fold σ and ρ̂ on archive days before 07-01.
- (iv) Worst Depth10 bytes per station-day; R (peak RSS) and t_p95 for capped single-day replays (MIA 09-29 first); pre-screen peak RSS.
- (v) The FQ trigger is `on_order_book_depth` in both live and replay (L-34).
- (vi) Per-station excluded fraction on the 09-08..09-29 dry run.
- (vii) The AUT-2 label-slot end time distribution, if available.

GREEN: every number is sourced, and the §3.12 hard-fail rule has been evaluated.

**WP1: extraction, characterisation-pinned (L-33).**
- Files:
  - r1 files;
  - **plus** `src/breezy/analysis/autonomy/subprocess_rss.py`, extracted from `replay_daily_runner.py:1014-1085`, which re-imports it;
  - **plus** `autonomy/producers/fs_replay.py`.
  - `live_family_tally.py` is untouched.
- Tests first:
  - the existing golden and contract tests, byte-unchanged;
  - `tests/unit/test_aud4_extraction_identity.py::test_extracted_functions_are_the_script_objects`, `::test_shadow_replay_parity_harness_unchanged_on_prefreeze_fixture`, `::test_subprocess_rss_extraction_identical`;
  - **mutation evidence** for each extracted function.
- GREEN: the gate is green and there is no behaviour diff.

**WP2: pure evaluation core.**
- Files: `eval_stats.py`, `permutation.py`, `metric_registry.py`, `windows.py`, `leakage.py`.
- RED first (r1 names kept), plus:
  - `tests/unit/autonomy/test_eval_stats.py::test_alpha_spent_lifetime_never_exceeds_total`, `::test_n_min_eff_applies_deff_and_cluster_floor`, `::test_c_min_makes_min_p_below_alpha_over_10`;
  - `tests/unit/autonomy/test_permutation.py::test_signflip_flips_dates_as_blocks`, `::test_signflip_exact_enumeration_at_small_c`, `::test_signflip_b_at_least_200_over_alpha`, `::test_below_c_min_is_underpowered`;
  - `tests/unit/autonomy/test_leakage.py::test_forecast_vintage_after_eval_ns_is_leakage_error`, `::test_forecast_vintage_equal_eval_ns_admitted`;
  - `tests/unit/autonomy/test_metric_registry.py::test_verdict_v1_schema_complete_per_kind`, `::test_pre_ruling_sha_null_with_assumption`;
  - `tests/unit/autonomy/test_verdict_validity.py::test_validity_anchored_to_slot_never_exceeds_ceiling`, `::test_worst_case_start_jitter_bounded`, `::test_early_manual_start_refused`;
  - `tests/unit/autonomy/test_verdict_identity.py::test_producer_recompute_identical_modulo_time`, `::test_differing_body_same_id_refused`, `::test_inputs_carry_dataset_and_tape_snapshot_sha`.
- GREEN: all pass.

**WP3: FQ tape admission and oversize quarantine.**
- Files: `tape_admission.py`; edit `scripts/analysis/replay_daily_runner.py` to quarantine on `DRIVER_TIMEOUT` (E17).
- RED first (r1 names kept), plus:
  - `test_tape_admission.py::test_forecast_input_sha_mismatch_excludes_day`, `::test_excluded_fraction_reported_per_station`, `::test_station_over_excluded_max_is_inconclusive_at_look`, `::test_replay_rss_share_exceeded_excludes_day`;
  - `tests/unit/test_replay_daily_runner_oversize.py::test_driver_timeout_day_quarantined_not_retried`, `::test_quarantine_never_touches_crh_census`.
- GREEN: pass. A dry run over 09-08..09-29 reproduces the WP0 rate exactly. Activation: replay-daily adopts the quarantine on merge.

**WP4: LIVE_SEQUENTIAL and the `eval-live` unit.**
- Files: `evaluators/forecast_quantile_ladder.py` (`live`), `producers/eval_live.py`, `deploy/systemd/breezy-autonomy-eval-live.{service,timer}` (§3.9 row: own lock, 14:45, `RuntimeMaxSec=1200`, `MemoryMax=1G`, `OnFailure`, `AccuracySec=1s`).
- RED first (r1 names kept), plus:
  - `test_eval_live.py::test_prefix_fills_before_d0_prime_excluded`, `::test_prereg_sha_is_family_prereg`, `::test_label_set_sha_in_inputs`;
  - `test_eval_n_stalled.py::test_unchanged_n_with_fills_five_days_fails`;
  - `tests/contract/test_autonomy_units.py::test_units_do_not_contend_on_flock`, `::test_eval_live_starts_after_label_slot_ends`, `::test_consumption_instants_inside_validity`.
- GREEN: pass, and the first live run writes one verdict per fold family. Activation: enable the timer on merge.
- The R-B boundary lands later as a separate reviewed commit.

**WP5: OFFLINE_CHALLENGER and the α ledger.**
- RED first:
  - `test_alpha_ledger.py::test_k_is_lifetime_never_reset`, `::test_k_in_window_uses_forward_window_index`, `::test_k_in_window_over_kmax_is_error_k_exceeded`, `::test_registry_count_within_pending_band_else_error`, `::test_registry_alpha_spent_exact_decimal`, `::test_drill_child_never_assigned_k`;
  - `test_offline_challenger.py::test_sigma_from_out_of_fold_only`, `::test_n_min_eff_fixed_at_nomination`, `::test_relative_calibration_conjunct`, `::test_cluster_sensitivity_disagreement_final_at_look`, `::test_producers_never_open_holdout`, `::test_unfiled_holdout_ruling_gives_sealed_window_inconclusive` (r1 names kept).
- Activation: runs inside WP6's unit.

**WP6: FORWARD_SHADOW, `fs_replay` children and the `eval-offline` unit.**
- Files: `evaluators/forecast_quantile_ladder.py` (`forward_shadow`), `producers/eval_offline.py`, `fill_model.py`, `deploy/systemd/breezy-autonomy-eval-offline.{service,timer}` (11:00, studies flock `-w 900`, `RuntimeMaxSec=9000`, `MemoryMax=12G`, P and S from WP0).
- RED first (r1 names kept), plus:
  - `test_forward_shadow.py::test_ev_haircut_by_fill_rate_lower_bound`, `::test_ev_lb_widened_by_proxy_se`, `::test_proxy_floor_is_aud12a_allowance`, `::test_fewer_than_n_proxy_min_fills_inconclusive`, `::test_unresolved_ambiguous_counts_as_miss`, `::test_survivorship_assumption_tagged`, `::test_look_waits_for_both_predicate_n`, `::test_b_unpowerable_in_window_is_inconclusive`, `::test_champion_baseline_never_promotion_input`;
  - `test_fs_replay.py::test_child_closure_sha_must_be_pinned`, `::test_eval_offline_imports_no_strategy_module` (an AST/grimp check, E21);
  - `test_memory_budget.py::test_rss_share_kill_excludes_day`, `::test_budget_arithmetic_within_studies_cap`;
  - `tests/integration/autonomy/test_eval_flow_promote_disabled.py::test_fixture_candidate_gets_offline_and_forward_shadow_verdicts_with_promote_disabled` (E2: a fixture registry with a nominated child admitted to CHALLENGER under R-G and a fixture tape; both verdict kinds are written and journaled);
  - existing `test_execution_egress_firewall_guard`, unchanged.
- Activation: enable the timer on merge.

**WP7a: R-B design commit and H0 MC (docs and evidence only; starts NOW, E16).**
- (1) Write `docs/evidence/PREREG_FQ_v1_design_<date>.json` with the R-B parameters and commit it **before** AUT-2a's first FQ label run. The commit message attests that no FQ PnL was read.
- (2) Produce the boundary with `crh_group_sequential_boundaries.py` and run the H0 MC (`aud07_live_rule_crossing_sim.py`) under `RuntimeMaxSec`, outside 01:00–04:30Z.
- (3) Hand the R-B text plus the evidence to the peer loop.
- GREEN: the design sha predates the first `labels_*.parquet` for FQ (`git log` vs file mtime), and the MC meets the R-B criteria.

**WP7b: feasibility.** RED first: `test_feasibility.py::test_consistency_uses_assigned_k`, `::test_record_includes_deff_fill_rate_and_p_terminal`, `::test_sigma_source_contaminated_flag` (r1 names kept). The ruling drafts move to `AUT-4-ruling-drafts.md`, minus R-A.

**WP8: self-monitoring and the journal contract (E7, E22).**
- Files: `health.py`.
- RED first:
  - `test_health.py::test_eval_staleness_fails_when_live_verdict_missing_after_deadline`, `::test_eval_staleness_fails_on_expired_newest`, `::test_excluded_fraction_detector`, `::test_resource_creep_two_of_three`;
  - `tests/contract/test_engine_input_journal_contract.py::*` (§3.13);
  - `test_attest_cadence_has_no_expiry_gap_with_eval_staleness`.
- Activation: AUT-6 registers `eval_staleness` in the FQ `DriftDetectors` tuple.

**WP9: live-proof run** (§6). No code.

**Producer-pin rotation runbook (E21; consistent with ARCH Z9 append-only pins).**
- Any merge that changes a module in a producer's `breezy.*` closure must, in the same commit, **append** the new closure sha to `PRODUCER_SOURCE_SHA256[<id>]`, keeping the old ones. The value is printed by `test_code_identity_pins_cover_import_closure` on failure.
- Removing a sha means moving it to `REVOKED_SOURCE_SHA256`.
- The closure is narrowed:
  - `eval_live` and `eval_offline` import no strategy module, so strategy edits rotate only `fs_replay`.
  - `fs_replay` rotates on any FQ strategy edit. This is expected, and the gate forces it.
- A merge that rotates a pin is followed by the full gate and the next scheduled run's verdicts showing the new `producer_code_sha`. There is no restart: the units are oneshot.

---

## 5. Association

| Contract | From → AUT-4 | AUT-4 → |
|---|---|---|
| C1 | AUT-1: Take/TrySubmit with `eval_ns`, `depth_ref`, `p_hat`, `forecast_input_sha256` (**AUT-4 uses AUT-1's hashing function, not a copy**); `LifecycleEvent` (fill-rate denominator) | — |
| C2 | AUT-2: admissible rows, `slippage`, `realized_pnl`; label slot 14:15Z must end by 14:40Z | — |
| C3 | AUT-3: lineage windows; **mint limit K_max per forward window via `alpha_ledger.forward_window_index`** (W7) | AUT-4 → AUT-3: `forward_window_index` |
| C4 | — | AUT-5 engine (daily 15:30); AUT-7 (accepted FAIL) |
| C5 | AUT-5: fold, `lineage_counters`, bound sha | — |
| C6 | ARCH-0 Protocols | `FqEvaluator`; `eval_staleness` detector → AUT-6 intraday producer (8 h HEALTH, ATTEST-cited) |
| Engine input journal | AUT-5 writes `engine_input/v1` | AUT-4 owns the schema and the contract test (§3.13) |
| Policy block | AUT-5 files it | AUT-4 drafts R-B…R-G and the feasibility record, plus the policy keys `FORWARD_WINDOW_DAYS`, `X_EV`, `EXCLUDED_FRACTION_MAX`, `N_PROXY_MIN` |
| Holdout ruling | ARCH files it | consumed by name |
| Delivery | AUT-6 `deliver_with_proof` | CRITICALs |

**Order.**
- **Now, in parallel:** WP0, WP1, WP7a.
- **After WP1, in parallel:** WP2, WP3.
- **After ARCH-0 + AUT-2a:** WP4.
- **After AUT-3 + AUT-5a:** WP5, WP6.
- **After WP0 + WP6:** WP7b.
- **After AUT-6's intraday producer + AUT-5's engine journal:** WP8.

---

## 6. Live-proof protocol

### 6.1 Artefact

`docs/evidence/AUT4_LIVE_PROOF_<start>_<end>.md` is produced by a read-only script, run by an agent that did not build AUT-4. It covers 7 consecutive qualifying days (≥ 1 real fill per day, ≥ 5 real fills in the window). For each day it records:
- per fold family: the LIVE_SEQUENTIAL `verdict_id`, outcome, n, n_min, `eta`. **Under R-B, never `NO_REGISTERED_PREREG`**;
- per candidate minted that day: the OFFLINE_CHALLENGER verdict (stage, k, `k_in_window`, `alpha_spent`);
- per CHALLENGER and the champion baseline: the FORWARD_SHADOW verdict;
- **consumption:** every verdict id appears in that day's `engine_input/v1` daily-pass journal (`acceptance` and reason shown), and every `cause_verdict_ids` entry in the chain export appears with `acted=true`;
- `eval_completeness` PASS; the `eval_staleness` HEALTH verdicts in the ATTEST rows; journal lines showing timer-triggered runs only; `producer_code_sha` values in `pins.py`.

**Candidate coverage.** At least 3 of the 7 days must carry ≥ 1 AUT-3 candidate verdict, and at least 1 day must carry a non-drill CHALLENGER FORWARD_SHADOW. A day with no mint counts only if AUT-3's run journal shows a named `NO_MINT` reason.

### 6.2 Drills

- **SIGKILL `eval_offline` mid-run.** Expected:
  - `OnFailure` → CRITICAL `delivered=true`;
  - `eval_staleness` FAILs at the next intraday pass;
  - ATTEST is withheld;
  - the next day recovers.

  This replaces r1's claim that ATTEST fails on the 26 h expiry.
- **Oversize tape day** in a test catalog root → `TAPE_DAY_OVERSIZE` plus quarantine, and the job succeeds.
- **Unpinned producer** in a fixture tree → the producer refuses and sends a CRITICAL.

### 6.3 Accrual, power and pre-KILL probability (E15)

**Measured inputs (2026-10-03).**
- CRH-window replay-sufficient station-days: 80/80, 3.64 per day. The FQ-window rate comes from WP0.
- **FQ IOC fill rate:** 12/14 = 0.857, Wilson 95% [0.601, 0.960]. Station-days with a take: 3.5 per climate day (n = 2 days, which is thin).
- σ(fc − mkt) = 0.099 (published AUD-02, contaminated window, disclosed).
- ρ̂ and deff are not yet measured. An **assumed deff = 1.5** is used below and replaced in WP0.
- The four stations cap accrual at 4 station-days per day.

| Verdict | n_min_eff (deff 1.5) | Max accrual before KILL | Pre-KILL probability of a terminal verdict |
|---|---|---|---|
| FORWARD_SHADOW (a), k = 1 | 1.5 × 403 = 605 (403 even at deff 1) | first CHALLENGER ≈ 2026-11-14 → 72 days × ≤ 4 = 288 | **0** (deterministic shortfall) |
| FORWARD_SHADOW (a), k = 4 | 918 | 288 | **0** |
| OFFLINE, σ_oof = 0.132 | k=1: 1076; k=4: 1630 | 4/day × ~72 days = 288 | **0** |
| OFFLINE, recalibration child σ_oof = 0.02 | max(1.5 × 25, 4 × 13) = 52 (k=4) | 4/day → about 13 days | **≈ 1** (powered), but expected FAIL: the gain is worth ≈ 0.006 against X = 0.0152 |
| LIVE_SEQUENTIAL FQ under R-B, n_max = 160 | registered | 4/day × uptime u | **D0′ = 10-25:** 0.34 / 0.73 / 0.89 / 0.96 at u = 0.5 / 0.6 / 0.7 / 0.8. **D0′ = 11-10:** 0.05 / 0.33 / 0.67 / 0.86 |

About the LIVE_SEQUENTIAL row:
- These probabilities are for reaching n_max, from a seeded simulation (seed 20261003, 4000 runs). Per-day station-days ~ Binomial(4, q), with q ~ Beta(8, 2) from 7 of 8 observed station-days, times Bernoulli(u) node uptime.
- An earlier efficacy or futility crossing only raises them.
- MDE ≈ +0.10 hold-rate per station-day.

**Consequences.**
- `promote_enabled=false`.
- PROMOTE is machinery-proven by the AUT-7b drill only.
- The only lever for a decisive pre-KILL verdict is **filing R-B early**: each week of delay costs about 0.1–0.2 of terminal probability at u = 0.7.

### 6.4 Prerequisites and ETA (E2)

**Hard prerequisites before the proof window may start.** These are not optional:
1. `RULING_holdout_freeze_and_forward_window_2026-10-03` is filed (ARCH; target 2026-10-10).
2. R-B is filed and its boundary sha committed (WP7a; target 2026-10-24).
3. The AUT-5 policy ruling is filed, so verdicts can be ACCEPTED rather than `REJECTED(no_ruling)`.
4. WP4–WP6 and WP8 are merged and active.

**ETA.**
- Earliest 2026-11-23; planning date 2026-11-30; latest acceptable 2026-12-31.
- **If R-B is not filed by 2026-12-01, AUT-4 is declared score 2** in PROGRESS, with the reason "no pre-registered sequential test for FQ". The machinery verdicts keep running.
- If fills stop, the window extends; after a TERMINAL KILL it pauses (ARCH §5.3).

**Evidence class: machinery proven, edge unproven.**

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `systemctl --user list-timers 'breezy-autonomy-eval-*'`; `journalctl --user -u breezy-autonomy-eval-live.service -u breezy-autonomy-eval-offline.service --since <start>` shows timer-triggered runs only; `git log --since <start> -- derived/` is empty; no verdict has operator fields |
| (b) family-agnostic | `test_families_enumerated_from_fold_not_list`, `test_refusing_plugin_family_gets_error`, ARCH `test_family_plugin_exact_set`; one LIVE_SEQUENTIAL per fold family per day in the proof |
| (c) fails closed | `test_underpowered_verdict_carries_no_effect_estimate`, `test_forecast_vintage_after_eval_ns_is_leakage_error`, `test_fewer_than_n_proxy_min_fills_inconclusive`, `test_validity_anchored_to_slot_never_exceeds_ceiling`, `test_k_in_window_over_kmax_is_error_k_exceeded`; `jq 'select(.outcome=="PASS" and .n < .n_min)'` over the store returns nothing |
| (d) detected and delivered | The §6.2 SIGKILL drill: the `evidence/alerts/delivery_<date>.jsonl` line `delivered=true`; the `eval_staleness` FAIL verdict; no ATTEST row in that window |
| (e) RED→GREEN | RED and GREEN output per §4 test in the PRs; the gate exits 0 at each merge sha; `lint-imports` "N kept, 0 broken"; mutation evidence for WP1 |
| (f) live proof | the §6.1 file; every verdict id is found in `evidence/autonomy/engine_inputs/<venue>/<date>/daily_*.jsonl`; `test_engine_input_journal_contract.py` green |
| Prerequisites | `ls docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md docs/evidence/PREREG_FQ_v1*.md`, both dated before `<start>`; the policy ruling sha in the proof verdicts |
| Feasibility | daily record present; `feasibility_consistency` PASS |
| Schedule | `test_units_do_not_contend_on_flock`, `test_consumption_instants_inside_validity`, `test_attest_cadence_has_no_expiry_gap_with_eval_staleness` green |
| Honesty | the DONE claim says "machinery proven, edge unproven" |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity / KILL 2027-01-25** | §6.3 shows FORWARD_SHADOW and large OFFLINE tests unpowerable; R-B filed early is the only lever; score-2 declaration date set |
| Type I inflation by daily looks or epochs | Single look; UNDERPOWERED carries no estimate; lifetime α never resets; LD-OBF for live |
| Correlated stations understate the variance | Date-block permutation; deff-inflated n_min; cluster-sensitivity final INCONCLUSIVE |
| Leakage (09-20 shape; forecast vintage; archive retransmission) | `assert_ref_before_take`; date-and-hour window; `assert_forecast_available_at`; `forecast_input_sha256` parity |
| Holdout misuse | Named ruling only; `open_holdout` never called; contaminated σ flagged; SEALED_WINDOW until filed |
| R-B design chosen after seeing the prefix | Design hash committed before the first FQ label run; parameters copied from PREREG v2; prefix excluded; disclosure in the ruling |
| Slippage optimism / survivorship | AUD-12a floor; SE widening; fill-rate haircut; `N_PROXY_MIN`; survivorship tagged, not hidden |
| Exclusion bias | Per-station excluded fraction; INCONCLUSIVE above 0.25 |
| One oversized day fails the job (L-53; MIA 09-29) | Byte guard, per-child timeout and RSS share, quarantine shared with replay-daily |
| Memory on the 30 GiB host | §3.12 arithmetic inside the 16G studies cap; hard-fail rule from WP0; no heavy job 01:00–04:30Z; stop the study, never the node |
| Flock contention / running into STOP | §3.9 table + `test_units_do_not_contend_on_flock`; own lock for `eval_live` |
| ATTEST expiry gap (W1) | AUT-4 daily verdicts not ATTEST-cited; `eval_staleness` intraday at 8 h |
| Producer silently dead or unpinned | `eval_staleness` → ATTEST withheld → entry veto; OnFailure CRITICAL; `eval_resource_creep` |
| Pin churn from strategy edits | Closure narrowed; `fs_replay` rotates alone; runbook |
| Shared venv / concurrent agents | Exact interpreter; no `uv`/`pip`/`stash`; worktree `PYTHONPATH`; per-agent scratchpads; explicit-path commits |
| Engine "consumption" unverifiable | `engine_input/v1` contract test owned here |
| Rulings not filed | Hard prerequisites; score-2 fallback stated |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native `BacktestEngine`, `ParquetDataCatalog` and Actor composition are used; nothing is patched.
- **Caps:** never read or written; `test_autonomy_never_reads_or_writes_operator_controls` covers `breezy.analysis.autonomy`.
- **allow_short=False:** untouched.
- **NO-SEND:** the refusing submit veto; no exec client is constructed; the exec store is never imported. `test_execution_egress_firewall_guard` stays unchanged.
- **Master enablement and permit:** never touched.
- **PREREG via ruling:** R-B…R-G are drafts. The holdout is consumed by name. No statistical semantics are created at runtime.
- **Safety tests:** none weakened; golden and contract tests stay byte-unchanged.

---

## 10. Self-score

| Axis | Max | r2 | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Every §10 obligation plus W1/W7/W8 and the holdout decision mapped. −2: four ARCH conflicts (P4-7..P4-10) remain open on ARCH's side |
| Correctness | 20 | 16 | α never resets; permutation at α_k; deff; out-of-fold σ; fill haircut. −4: R, ρ̂/deff and the FQ-window rate are unmeasured (an assumed deff of 1.5 is used); the sign-flip symmetric-null assumption; the fill rate rests on 14 IOCs and 2 days |
| Specificity | 15 | 14 | Paths, slots, budgets, schemas, test names |
| Acceptance | 20 | 16 | The checklist is concrete and the journal makes consumption checkable. −4: the proof is gated on three unfiled rulings and two upstream waves |
| Autonomy-safety | 15 | 14 | Fail-closed throughout. −1: the dead-evaluator veto depends on ARCH accepting a detector-level ATTEST set |
| Reuse | 10 | 8 | Extraction-first. −2: new permutation module and new journal contract |
| **Total** | 100 | **86** | r1 self-scored 93 against reviewers' 81. This is the honest re-score |

### Contradictions with ARCH Rev 4 found in r2 (for the ARCH owner)

- **P4-7 (W1 interaction).** `attest_required_verdict_kinds` is kind-level. AUT-4 also writes daily HEALTH verdicts (26 h), so "an accepted PASS of every kind" is ambiguous: one PASS of HEALTH, or every HEALTH detector? Citing a 26 h verdict re-opens the W1 expiry gap.
  - Proposal: `attest_required_detectors` as a set of (kind, detector) pairs, with AUT-4 represented by the intraday `eval_staleness`.
- **P4-8 (E1 versus C4).** Lifetime α_k = α_total·2^−k breaks C4's "the engine refuses verdict k > K_max" and "MDE at α_K = α_total·2^−K_max", because k exceeds K_max after the first window.
  - Proposal: C4 distinguishes `k` (the lifetime α index) from `k_in_window` (checked against K_max). The feasibility MDE is at the deepest reachable k. Alternatively, ARCH picks the Bonferroni-per-window variant.
- **P4-9 (E7).** C4 and C5 define no engine input journal, so "consumed by the engine as its input record" is untestable. This plan proposes `engine_input/v1` (§3.13); ARCH should adopt it into C5.
- **P4-10 (E6).** C4 has a single `prereg_ruling_sha256` that must equal the policy ruling's sha. A LIVE_SEQUENTIAL test is registered by a family PREREG (R-B), and `test_demotion_never_requires_policy_and_is_immediate` implies a FAIL must act without one.
  - Proposal: LIVE_SEQUENTIAL carries the family PREREG sha, which the engine checks against a policy-block map, or against the committed PREREG list when no policy is filed.
- **P4-11 (E20).** `verdict_id` = sha of the canonical body includes `produced_at_ns`, so a recompute never dedupes. This plan excludes it.
- **P4-12.** The closed `assumptions` enum needs `slippage_floor_aud12a`, `fill_survivorship_unmodelled`, `no_policy_ruling` and `drill`.
- r1 items P4-1 (holdout) and P4-5 (K_max reset) are closed by the HOLDOUT decision and by E1/W7. P4-2, P4-3, P4-4 and P4-6 are absorbed above.

---

## §R2 Disposition (review `reviews/AUT-4-r1-merged.md`, plus the ARCH deltas and the HOLDOUT decision)

**22 FIXED, 0 REJECTED.** No README criterion is changed.

| E | Disposition | Where |
|---|---|---|
| E1 | FIXED | §3.5: lifetime geometric α, never reset; `alpha_spent` exact cross-check against the registry with a pending band; R-D. ARCH conflict P4-8 |
| E2 | FIXED | §6.4: holdout ruling, R-B and policy ruling are hard prerequisites; score-2 declaration if R-B is unfiled by 12-01. §3.7 champion baseline; R-G admission on nomination; WP6 integration test with `promote_enabled=false`; ETA recomputed |
| E3 | FIXED | §3.7: live IOC fill rate (12/14 measured; AMBIGUOUS counts as a miss); EV haircut by the Wilson LB; LB widened by z·SE_proxy; AUD-12a floor; `N_PROXY_MIN=30` refusal; survivorship disclosed and tagged |
| E4 | FIXED | §3.9: `eval_live` own lock; offline `RuntimeMaxSec` 9000 (2.5 h) ending 13:45Z; `test_units_do_not_contend_on_flock`; W1 and W8 aligned |
| E5 | FIXED | §3.1: validity anchored to `SLOT_UTC`; jitter test; consumption-instant test (§3.9) |
| E6 | FIXED | §3.1a: per-kind field table; pre-ruling null plus `no_policy_ruling`, engine `REJECTED(no_ruling)`; `test_verdict_v1_schema_complete_per_kind` |
| E7 | FIXED | §3.13: `engine_input/v1` schema and the contract test owned by AUT-4; §6.1 check (f) |
| E8 | FIXED | §3.12: arithmetic 2 + max(4, P·S) ≤ 12 ≤ 16G; S from the WP0 peak; per-child share watchdog; hard fail at S > 9G |
| E9 | FIXED | §3.2: date-cluster sign-flip, B ≥ 200/α_k, C_min clusters |
| E10 | FIXED | §3.2: deff-inflated n_min_eff; cluster-sensitivity INCONCLUSIVE final at the single look |
| E11 | FIXED | §3.10 R-C: relative conjunct (not worse than champion; under-confidence not increased); absolute leg report-only |
| E12 | FIXED | §3.5/§3.10: R-A withdrawn; named ruling consumed; contamination disclosed; S2 descriptive; σ source flagged |
| E13 | FIXED | §3.3/§3.4: `assert_forecast_available_at` (over `forecast_state.py:306-321`); `forecast_input_sha256` parity; RED tests in WP2/WP3 |
| E14 | FIXED | §3.8: `feasibility_consistency` at each candidate's assigned k |
| E15 | FIXED | §6.3: fill rate from the exec store; pre-KILL terminal probability per verdict kind and uptime |
| E16 | FIXED | §3.10 R-B + WP7a: design hash committed before the first FQ label run; prefix excluded; disclosure |
| E17 | FIXED | §3.4: per-station excluded fraction, INCONCLUSIVE above 0.25; the replay-daily MIA timeout quarantine is assigned to WP3 |
| E18 | FIXED | §3.7(b): α_k level (intersection-union); look waits for both n; `b_underpowered` rule |
| E19 | FIXED | §3.5: σ_oof from out-of-fold differences only |
| E20 | FIXED | §3.1: `verdict_id` excludes `produced_at_ns`; recompute test; dataset and tape snapshot shas in `inputs`. ARCH conflict P4-11 |
| E21 | FIXED | §4 runbook (append-only per Z9) plus closure narrowing (`fs_replay` split; `eval_offline` imports no strategy module) |
| E22 | FIXED | §3.11: excluded fraction, n stalled, runtime/RSS creep, pin mismatch via `eval_staleness` |
| ARCH W1 | ABSORBED | §3.9: AUT-4 verdicts not ATTEST-cited; `eval_staleness` 8 h intraday; invariant and test. ARCH conflict P4-7 |
| ARCH W7 | ABSORBED | §3.5: `FORWARD_WINDOW_DAYS` in the policy, `FORWARD_WINDOW_DAYS_MIN` pin; **mint-limit option chosen** with AUT-3 via the shared `forward_window_index`; `ERROR(k_exceeded)` kept only as a breach guard |
| ARCH W8 | ABSORBED | §3.9: AUT-4 windows end ≤ 15:15Z; test excludes the 16:41–16:43 slot |
| HOLDOUT decision | ADOPTED | §3.4 item 7, §3.5, §3.10: frozen [2026-07-01, 2026-10-02), forward ≥ 2026-10-02, consumed by name |
