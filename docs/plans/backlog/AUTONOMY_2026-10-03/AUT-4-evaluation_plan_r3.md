# AUT-4: Evaluation (offline challenger, forward shadow, live sequential). Plan r3

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-4 |
| Title | Evaluation: the OFFLINE_CHALLENGER, FORWARD_SHADOW and LIVE_SEQUENTIAL C4 producers; lifetime α (`k_life`) and per-window mint accounting (`mints_in_window`); the feasibility record with the window cap; evaluator self-monitoring |
| Round | **r3** (2026-10-03). r2 stays unchanged at `AUT-4-evaluation_plan_r2.md`. This round disposes F1–F14 of `reviews/AUT-4-r2-merged.md` and adopts the binding `reviews/ALPHA-decision.md` (§R3) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 5**: the snapshot `reviews/snapshots/ARCH_rev5.md`, 94 743 B, sha256 `5d2b75fa77e2c0abaaa478bd38d32e7e06ac98c8057ce50a5045f0dd0eff8403`, **plus** `reviews/ALPHA-decision.md` (binding on ARCH Rev 7) and `reviews/HOLDOUT-decision.md` (consumed by name only). The directory copy is now Rev 6 (sha256 `89d3e7a5…0f1e`). It is **not** consumed. One fact it records (G32: `RuntimeMaxSec` has no effect on `Type=oneshot`) was checked independently against `man systemd.service` on the host (systemd 259) and is used in §3.9 |
| Repo HEAD read | `4b8347a6` (branch `feat/data-capture-and-risk`) |
| Current score | 2 |
| Target | 3 |
| Upstream | ARCH-0 (C1–C6 types, verdict writer, registry read API, `pins.py`); AUT-1 (C1 including `forecast_input_sha256` and `LifecycleEvent`); AUT-2 (C2, RECONCILIATION, the 14:15Z label slot); AUT-3 (C3 candidates; mint limit K_max per forward window; `NO_CHANGE(k_max_reached)`); AUT-5 (policy ruling; engine input journal writer; fixture-registry engine pass, §6.1); AUT-6 (`deliver_with_proof`; the intraday producer that runs `eval_staleness`); AUT-7 (the drill child, §6.1) |
| Downstream | AUT-5 (consumes every C4 verdict; files the policy ruling whose AUT-4 sections are drafted in §3.10); AUT-7 (an accepted LIVE_SEQUENTIAL FAIL is a demote or rollback cause) |
| Status | PLANNING. Nothing is implemented. Every ruling text below is a DRAFT for the peer-review loop; none is decided here |

**Headline (read first).**
- AUT-4 can reach score 3 as *machinery* before the 2027-01-25 KILL. The live-proof window may start only after the hard prerequisites in §6.4: three rulings (holdout, R-B `PREREG_FQ_v1`, the AUT-5 policy ruling) and the ARCH Rev 7 items (the ALPHA decision, P4-7, P4-9, P4-10, P4-11, P4-12).
- If R-B is not filed by **2026-12-01**, AUT-4 is declared **score 2**, because "every live family is evaluated on pre-registered sequential tests" would be false for FQ.
- **(r3, F1) Every FORWARD_SHADOW verdict is `INCONCLUSIVE(window_cap_below_n_min)` by construction under today's σ and X.** Its n_min_eff (≥ 403 independent station-days) exceeds the window cap n_cap = 4 stations × 28 days × uptime floor ≤ 112, and it would still exceed the cap at the 120-day maximum window (480). The verdicts still flow every day, so the machinery is exercised, but **no promotable path is claimed**. This agrees with `promote_enabled=false`.
- OFFLINE stage 2 is weather-only, so its cap is 4 × 28 = 112. A recalibration child (σ_oof ≈ 0.02) fits under that cap, but it is expected to FAIL against X = 0.0152.
- **(r3, F1)** Lifetime α never resets (`k_life`). A candidate with `k_life > K_LIFETIME_EFFECTIVE` (proposed 6) is evaluated **nominally**: it is descriptive, its α is still charged, and it never PASSes. At K_max = 4 MINTs per 28-day window, the lineage reaches k_life = 6 in about two windows. After that, every new candidate is nominal.
- The only verdict that can reach a decisive terminal state before the KILL is LIVE_SEQUENTIAL on FQ under R-B. Its probability of reaching n_max = 160 is 0.67–0.89 at node uptime ≥ 70% (§6.3). At n = 160 the power is ≈ 0.69 against a +0.10 effect, and the 80%-power MDE is ≈ +0.113 (F14).
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

**ARCH Rev 5 §10 obligations for AUT-4 (verbatim; unchanged from Rev 4).**
> the replay-sufficiency check that admits forward-shadow tape days; station-day clustering; the measured qualifying station-days per day; the feasibility record (`n_min`, MDE at α_K, `eta_date`) handed to the policy ruling; K_max accounting; the slippage source and its `assumptions` tag; the live-sequential producer over admissible labels.

Also absorbed:
- Rev 5 §4.5: Z4 (`MAX_VERDICT_VALIDITY_H` ≤ 26); W1 (`ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H`, where L_max is 60 min + 150 s); W7 (`forward_window_days` between 28 and 120, tumbling windows, the store-enforced mint cap); W8 (the 16:41–16:43Z RECONCILIATION slot).
- **ALPHA decision:** `k_life` is separate from `mints_in_window`; `K_LIFETIME_EFFECTIVE`; B is capped; `n_min_eff` and `n_cap` are recorded, with `INCONCLUSIVE(window_cap_below_n_min)` when n_min_eff > n_cap.
- **Rev 5 obligation text "MDE at α_K".** Under ALPHA this is reported at both α_{k_life} of each candidate **and** α_{K_LIFETIME_EFFECTIVE}, the deepest promotable index (§3.8).

| Obligation | Section / WP |
|---|---|
| Replay sufficiency | §3.4, WP3 |
| Clustering | §3.2, WP2 |
| Measured qualifying rate | §6.3, WP0 |
| Feasibility record (incl. `n_cap`) | §3.8, WP7b |
| K_max / α accounting (`k_life`, `mints_in_window`) | §3.5, WP5 |
| Slippage source | §3.7, WP6 |
| Live-sequential producer | §3.6, WP4 |
| Z4, W1, W7, W8 | §3.1, §3.9, §3.5, §3.9 |

---

## 2. L-1 null hypothesis and reuse

The null hypothesis is that Nautilus or existing Breezy already provides each need. Rows unchanged from r2 are listed briefly; rows new in r3 are marked **(r3)**.

| Need | Checked | Verdict |
|---|---|---|
| Statistics over shadow decisions (Brier, permutation, α ledger) | `nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer`: realised-PnL statistics over *filled* positions. Nothing native does Brier, cluster permutation, LD-OBF or α spending | **The gap is real** for the statistics |
| Forward-shadow replay | `scripts/analysis/nbp_shadow_parity.py:275` `run_live_parity` (native `BacktestEngine`, refusing submit veto, Depth10) | **Reuse.** Extract it (WP1) |
| Tape read | Native `ParquetDataCatalog` (`nbp_shadow_parity.py:512`) | **Reuse** |
| Sequential looks and boundaries | `family_tally_v2.py:625` `run_sequential_looks`; `crh_group_sequential_boundaries.py:243`; `aud07_live_rule_crossing_sim.py:158,210`; `settlement/current_rung_hold_v2.py:296,346,365,433,470`; `persistence/gs_boundary_artefact.py:219` | **Reuse**, extracted verbatim |
| Brier, reliability, calibration leg, bootstrap | `forecast_conditional_scoring.py:110,139,237,267,278,303,392,428`; `roi_bound.py:93,97` | **Reuse** in `scoring_core.py`. R-C (§3.10) reuses the reliability binning (`:303`) and the pinned bootstrap seed |
| Market baseline, look-ahead guard | `wp7b_market_as_forecaster.py:169,232,372,475,707` | **Reuse** |
| Replay sufficiency | `analysis/replay_sufficiency.py:651,694,207` | **Reuse**, plus a kind-keyed FQ window |
| Forecast vintage at decision | `strategy/ladder_ev/forecast_state.py:179-221,306-321`; `persistence/nbp_derived_store.py:142-153,196-243` | **Reuse** (r2 E13) |
| Per-child timeout and peak RSS | `replay_daily_runner.py:1014-1085` `_run_subprocess_with_rss`; `:1395-1484` `driver_timeout_s` → `DRIVER_TIMEOUT` | **Reuse**, extracted to `autonomy/subprocess_rss.py` |
| **(r3, F12) Remaining-budget launch rule** | `replay_daily_runner.py:1818-1819` (`remaining = budget_s − elapsed`; `driver_timeout_s = max(0, remaining − reserve_s)`); `deploy/systemd/replay-daily-run.sh:48-50` (the budget is derived from the unit's own `TimeoutStartSec` and elapsed `$SECONDS`) | **Reuse the pattern** in `fs_replay` scheduling: a child is launched only if its timeout fits in the remaining budget |
| **(r3, F8) Oneshot runtime bound** | `man systemd.service` (systemd 259): "`RuntimeMaxSec=` … does not have any effect on `Type=oneshot` services … use `TimeoutStartSec=`". Existing oneshots use `TimeoutStartSec` (`breezy-score-live-trials.service:76`, `breezy-replay-daily.service:62`) | **Reuse `TimeoutStartSec`.** Every r2 `RuntimeMaxSec` becomes `TimeoutStartSec` |
| **(r3, F13) The 360 s child timeout** | `/usr/bin/grep -n 360 scripts/analysis/replay_daily_runner.py` finds no such constant; the runner derives its timeout from the remaining budget (`:1819`). The r2 number had no code origin | **Not reuse.** It is now a named constant **derived** from the budget (§3.12) |
| Slippage floor | `RULING_AUD-12a_slippage_allowance_2026-09-27.md` (0.01) | **Reuse** as the floor (R-E) |
| Live IOC fill outcome | exec store `retirement_reason` (WP0 baseline only); production from C1 `TrySubmit` + `LifecycleEvent` | AUT-4 never imports the exec store |
| Verdict writer, registry reader, `pins.py` | ARCH-0 `persistence/autonomy/` | **Consume.** AUT-4 writes no new verdict store |
| **(r3, F11) Run wall time and peak RSS** | `resource.getrusage` (stdlib); cgroup v2 `memory.peak` (kernel 7.0); systemd `ExecStopPost=` with `$SERVICE_RESULT`/`$EXIT_STATUS` (systemd.service(5)) | **Reuse** stdlib, cgroup and systemd. Only the small run-record writer is new (§3.11) |

---

## 3. Design

### 3.1 Contracts; rules common to every producer

**Contracts.**
- **Consumes:**
  - C1: `DecisionRecord` Take/TrySubmit (`eval_ns`, `depth_ref`, `p_hat`, `forecast_input_sha256`); `LifecycleEvent`; `drill`; `source`.
  - C2: admissible rows only.
  - C3: `forward_eval_start_utc`, `train_end_exclusive_utc`, `leakage_assertions`.
  - C5, read-only: the fold at `now`; `lineage_counters`: under Rev 7, `k_life` (ALPHA §4) and `mints_in_window`; under Rev 5, `candidates_evaluated`; plus `holdout_opens` and `alpha_spent`.
  - C6: the `Evaluator` slot.
- **Provides:**
  - C4 kinds `OFFLINE_CHALLENGER`, `FORWARD_SHADOW`, `LIVE_SEQUENTIAL`;
  - `HEALTH` detectors `eval_completeness`, `feasibility_consistency`, `eval_excluded_fraction`, `eval_n_stalled`, `eval_resource_creep`;
  - the VERDICT-class detector function `eval_staleness`, which the AUT-6 intraday producer runs (§3.9).

**Bound subject sha (Z1).** `subject_artefact_sha256` is the family's bound sha from its BOOTSTRAP or MINT row.

**Validity anchored to the slot (Z4).**
- `valid_until_ns = slot_start_ns(today) + 26·3600·10⁹`, where `SLOT_UTC` equals the unit's `OnCalendar` (contract test).
- The producer refuses (ERROR) if `produced_at_ns < slot_start_ns`, i.e. a manual early start.
- **(r3, F8)** The late bound is `TimeoutStartSec` (the flock wait runs inside `ExecStart`, so it is counted inside `TimeoutStartSec`). Therefore `valid_until − produced_at ≤ 26 h`.
- Timers set `AccuracySec=1s`, `RandomizedDelaySec=0` and `Persistent=false`.
- Tests:
  - `test_validity_anchored_to_slot_never_exceeds_ceiling`;
  - `test_worst_case_start_jitter_bounded` (TimeoutStartSec + AccuracySec, read from the unit file);
  - **(r3, F8)** `test_offline_successor_lands_before_predecessor_expiry`, which asserts `TimeoutStartSec + AccuracySec ≤ 7200 s − 900 s` for every AUT-4 unit.

**Verdict identity (r2 E20; ARCH dependency P4-11; r3 F3 fallback).**
- **Target (Rev 7 adopts P4-11):** `verdict_id = sha256(canonical_body − {verdict_id, produced_at_ns})`. A recompute on identical inputs gives the same id, and the writer treats a byte-equal body as an idempotent no-op.
- **Fallback (Rev 5 rule in force: `verdict_id` = sha of the whole body, including `produced_at_ns`):**
  - The producer computes `recompute_key = sha256(canonical_body − {verdict_id, produced_at_ns})` and stores it in `metrics.recompute_key` (registered in `metric_registry`).
  - Before writing, it scans that family-date's directory. If a verdict with the same `recompute_key` exists, it writes nothing (idempotent no-op).
  - So duplicates never reach the engine journal under either rule.
  - Test `test_recompute_is_noop_under_rev5_identity`.
  - The mode is selected by the ARCH-0 `verdict/v1` schema module's identity function. AUT-4 calls it and does not choose.
- `inputs[]` carries the following roles:
  - `label_set`, `archive_dataset`, `tape_snapshot`, `boundary_artefact`, `family_prereg`, `fs_replay_output`, `sigma_source`;
  - **(r3, F2)** `stage1_verdict`.

**Single-look discipline.**
- OFFLINE stage 2 and FORWARD_SHADOW are evaluated confirmatorily **once**, at the first run where n ≥ n_min_eff for **every** predicate (§3.7). Before that the verdict is `UNDERPOWERED`, with counts only.
- FAIL or INCONCLUSIVE at the look is final.
- **(r3, F1)** If `n_min_eff > n_cap` at nomination, no look is ever scheduled. Every daily verdict for that candidate is `INCONCLUSIVE(window_cap_below_n_min)` with counts only (§3.5).

**Fail-closed.**
- Any missing, stale, unknown-version or unverifiable input, any leakage assertion failure, and any producer exception give `ERROR`, plus a CRITICAL through `deliver_with_proof`.
- `UNDERPOWERED`, `INCONCLUSIVE` and `ERROR` never promote.
- **(r3, F11)** An `ERROR` verdict is never "fresh" for `eval_staleness` (§3.9).

**Payload hygiene.** There are no paths in verdicts. `test_autonomy_payload_hygiene_scan` covers the AUT-4 writers.

### 3.2 Clustering, the design effect, the permutation test and the B cap

- **Unit.** The unit is the independent station-day `(station, climate_day)` (Y14). `assert_nondegenerate_clustering` refuses a degenerate key.
- **Primary statistic.** A studentised **date-cluster sign-flip permutation test**, one-sided at α_k:
  - per-station-day paired differences are summed per climate date;
  - each date's sign is flipped as a block.
- **(r3, F1) B, capped.**
  - `B = min(B_MAX, max(10 000, ⌈200/α_k⌉))`, with `B_MAX = 2¹⁹ = 524 288` (a literal in `autonomy/permutation.py`, pinned by a test).
  - B_MAX ≥ ⌈200/α_6⌉ = 512 000, so every **promotable** index (k_life ≤ K_LIFETIME_EFFECTIVE = 6) gets the full B.
  - Flips are generated in chunks of 16 384 (memory ≤ 16 384 × C × 8 B, i.e. ≈ 16 MB at C = 120).
  - Exact enumeration is used when the number of date clusters C ≤ 20.
- **(r3, F1) Analytic tail beyond the cap.**
  - When `⌈200/α_k⌉ > B_MAX`, which happens only for nominal candidates with k_life ≥ 7, the reported p is the **Hoeffding sub-Gaussian bound** on the unstudentised date-sum sign-flip statistic: `p_H = exp(−T²/(2·Σ_d D_d²))`.
  - This is a valid conservative upper bound on the exact conditional p.
  - Reported as `metrics.p_method = "hoeffding_tail"`. Promotable candidates use `"mc"` or `"exact"`.
  - Test `test_b_capped_and_hoeffding_tail_beyond_cap`.
- **Cluster floor.** The test runs only if `C ≥ C_min(α_k) = ⌈log2(10/α_k)⌉`; otherwise the outcome is `UNDERPOWERED(min_clusters)`. C_min for k = 1…6 is 10, 11, 12, 13, 14, 15.
- **Design effect.**
  - `deff = 1 + (m̄ − 1)·ρ̂`, with ρ̂ measured out-of-fold on archive days before 2026-07-01 (WP0).
  - `n_min_eff` per predicate = `max(⌈deff·n_min⌉, 4·C_min)`.
- **Cluster sensitivity.** The same test is run with station-day blocks. A disagreement gives `INCONCLUSIVE(cluster_sensitivity)`, final at the look.
- **Family pin.** `event_family="rung_2f_traded"`; the median binary is refused. `calibration_leg_rung` and `underconfidence_mean_signed_dev` are always reported.

### 3.3 Modules (analysis layer only; never imported by live packages)

The r2 modules are kept. Changes in r3:

| Path | Purpose |
|---|---|
| `scoring_core.py`, `sequential_looks.py`, `market_events.py`, `autonomy/shadow_replay.py`, `autonomy/subprocess_rss.py` | Verbatim extractions (r2) |
| `autonomy/eval_stats.py` | `alpha_k`, `alpha_spent_lifetime`, `n_min_one_sided`, `mde_one_sided`, `power_one_sided`, `deff`, `n_min_eff`, `c_min`, `eta_days`, `eta_date`; **(r3)** `n_cap(stations, window_days, uptime_floor)` |
| `autonomy/permutation.py` | `date_cluster_signflip(diffs_by_date, alpha, seed, b)`; **(r3)** `B_MAX`, chunking, `hoeffding_tail` |
| **(r3, F5)** `autonomy/calibration_ni.py` | `relative_calibration_ni(cand, champ, dates, alpha, seed, b)` → `(ece_diff_ub, msd_diff_ub, n_buckets_qualifying)` (§3.10 R-C) |
| `autonomy/metric_registry.py` | Closed metric names, the per-kind required-field table (§3.1a), **(r3)** `recompute_key`, `k_life`, `mints_in_window`, `n_cap`, `outcome_reason` |
| `autonomy/windows.py`, `autonomy/leakage.py`, `autonomy/tape_admission.py` | r2 |
| `autonomy/alpha_ledger.py` | **(r3, F1/F2)** `assign_k_life` (stage 1 only), `forward_window_index(day)` (also imported by AUT-3's mint path), `mints_in_window`, registry cross-check on `k_life` |
| `autonomy/fill_model.py` | Live IOC fill rate (an unresolved AMBIGUOUS counts as a miss); slippage proxy; **(r3, F4)** the joint (b) bound at α_k/3 per component; the `N_IOC_MIN` refusal; the worst-case survivorship bound (descriptive) |
| **(r3, F12/F13)** `autonomy/budget.py` | `REPLAY_PARALLELISM` (P, set from WP0), `EVAL_OFFLINE_TIMEOUT_START_S = 6300`, `PRESCREEN_BUDGET_S = 900`, `SCORING_RESERVE_S = 600`, `SAFETY_S = 300`, `FLOCK_WAIT_S = 900`, `FS_REPLAY_CHILD_TIMEOUT_S` (derived, §3.12), `MAX_BACKLOG_DAYS_PER_RUN = 3`. A test asserts the derivation formula |
| **(r3, F11)** `autonomy/run_record.py` | The producer writes a run record at exit; the `ExecStopPost` entry writes the systemd result (§3.11) |
| `autonomy/evaluators/forecast_quantile_ladder.py`, `autonomy/feasibility.py`, `autonomy/health.py` | r2, with the r3 changes in the sections below |
| `autonomy/producers/eval_live.py`, `eval_offline.py`, `fs_replay.py` | r2. **(r3, F9)** The `fs_replay` output path is keyed by closure: `derived/autonomy/fs_replay/<family>/<closure_sha12>/<day>/<station>.jsonl` (0444, written atomically by tmp + rename) |

#### 3.1a Required fields per verdict kind

`—` means null with the literal reason.

| Field | OFFLINE stage 1 | OFFLINE stage 2 | FORWARD_SHADOW | LIVE_SEQUENTIAL | AUT-4 HEALTH |
|---|---|---|---|---|---|
| `n`, `n_unit` | archive station-days | forward station-days | admissible station-days with ≥ 1 scorable rung event | combined station-day draws | — |
| `n_min` | — `PRESCREEN_NO_TEST` | `n_min_eff` (max over predicates) at α_{k_life} | `n_min_eff` (max over (a), (b), (c)) | **(r3, F10) n at the first registered look (10 combined station-days)**; `metrics.n_max` = registered n_max; or reason `NO_REGISTERED_PREREG` | — `HEALTH_NO_TEST` |
| `power` | — | 0.80 (design) | 0.80 (design) | registered design power | — |
| `mde` | — | `mde_one_sided(σ_oof, n_min_eff, α_{k_life})` | the same for (a) | registered MDE at n_max | — |
| `comparator_family_id` | champion | champion | `MARKET_ASK_IMPLIED`; (c) uses the champion | `BREAK_EVEN` | — |
| `alpha_spent` | lineage cumulative **including** this candidate's α_{k_life} if nominated (charged at assignment, §3.5) | unchanged from stage 1 | unchanged from stage 1 (one charge per candidate) | LD-OBF cumulative α at the information fraction (`metrics.alpha_scope="family_prereg"`) | — |
| `prereg_ruling_sha256` | policy ruling sha | policy ruling sha | policy ruling sha | **Rev 7 (P4-10):** family PREREG sha. **Rev 5 fallback (F3):** policy ruling sha, with the family PREREG sha in `inputs[family_prereg]` and `metrics.family_prereg_sha256` | policy ruling sha |
| `eta_to_verdict_days` | 0 | `eta_days(n_min_eff, n, rate)`, or null with reason `window_cap_below_n_min` | the same | from the registered looks | — |
| **(r3)** `metrics.k_life`, `alpha_k`, `mints_in_window`, `n_cap`, `n_min_eff` | written at nomination | copied from stage 1 | copied from stage 1 | — | — |

**Before a ruling is filed.**
- With no policy ruling: `prereg_ruling_sha256 = null` and `assumptions ∋ no_policy_ruling`, so the engine journals the verdict `REJECTED(no_ruling)`.
- With no family PREREG: the outcome is `INCONCLUSIVE(NO_REGISTERED_PREREG)`.
- Test `test_verdict_v1_schema_complete_per_kind`.

### 3.4 Replay sufficiency for forward-shadow tape days

The r2 conditions 1–8 are kept: FINAL label; FQ-window census `is_replayable_whole_day`; not in replay drift; largest-item guard (L-53); replay fidelity on `DecisionKey`; forecast vintage and `forecast_input_sha256` parity; forward day outside the frozen holdout; child completed within its timeout and RSS share. Each refusal is named in `metrics.days_excluded_by_reason`.

**(r3, F9) Condition 9: one closure.**
- A day counts toward n only if its `fs_replay` output was produced under the **current** `fs_replay` closure sha, i.e. the newest sha in `PRODUCER_SOURCE_SHA256["fs_replay"]` that the running child stamps.
- After a pin rotation, the earlier days of a candidate's window are re-queued for re-replay under the new closure, within the §3.12 backlog budget. Until a day is re-replayed it is `PENDING_RECLOSURE`, which is not counted and not excluded.
- **Verdict-level guard:** if the set of cited `fs_replay_output` inputs carries more than one closure sha, the verdict is `INCONCLUSIVE(mixed_closure)` with a CRITICAL. This is a breach detector, because condition 9 makes it unreachable in normal operation.
- Tests: `test_n_counts_current_closure_days_only` and `test_mixed_fs_replay_closure_is_inconclusive`.

**Excluded-day bias guard.**
- `metrics.excluded_fraction_by_station` is reported on every verdict.
- If any station exceeds `EXCLUDED_FRACTION_MAX` (proposed 0.25) at the look, the outcome is `INCONCLUSIVE(exclusion_bias)`.
- **Oversize quarantine** (shared with `replay_daily_runner`, WP3) and the separate FQ census file are as in r2.

### 3.5 OFFLINE_CHALLENGER, α (`k_life`) and the mint limit (`mints_in_window`)

**Stage 1: pre-screen (no test).** This runs on archive days before 2026-07-01 only, as in r2: rolling-origin folds F = 6, `prescreen_fold_wins`, `NOT_DISTINCT`, `assert_prescreen_pre_holdout`, σ_oof and ρ̂ out-of-fold.
- Outcomes: `FAIL(stage=prescreen)`, `INCONCLUSIVE(NOT_DISTINCT)`, or **nominated**.

**(r3, F2) `k_life` is assigned at stage-1 nomination, and only there.**
- `eval_offline` holds the studies flock and is the only process that assigns k. It walks the day's pending stage-1 candidates in ascending MINT `seq` order.
- For each nominee, `k_life = 1 + max(R, S)`, where:
  - R = the registry's lifetime counter (`lineage_counters.k_life` under Rev 7);
  - S = the number of this lineage's **nominated stage-1 verdicts in the verdict store**, including those written earlier in the same run.
- The verdict is written before the next candidate is assigned. A crash between two nominees therefore leaves the first one in the store, and the re-run counts it.
- The stage-1 verdict records `metrics.k_life`, `alpha_k = α_total·2^−k_life`, `mints_in_window`, `n_min_eff` per predicate, `C_min`, `mde`, `n_cap` and `window_cap_feasible`, so the test is pre-registered before any forward day is read.
- Stage 2 and FORWARD_SHADOW cite the stage-1 verdict (`inputs[stage1_verdict]`) and **read k_life from it; they never recompute it**.
- Tests:
  - `tests/unit/autonomy/test_alpha_ledger.py::test_two_pending_nominees_get_distinct_k`;
  - `::test_stage2_reads_k_from_stage1_never_recomputes`;
  - `::test_crash_between_nominees_keeps_k_distinct`.

**Reading of ALPHA §1 ("counts every evaluated MINT").** AUT-4 reads "evaluated" as **nominated into a confirmatory test**. A pre-screen FAIL or NOT_DISTINCT MINT consumes a `mints_in_window` slot (rate limiter) but receives no `k_life` and charges no α. If Rev 7 means every non-drill MINT, the change is a single line in `assign_k_life` and is strictly more conservative. This is raised as **P4-13** (§10).

**(r3, F1) α: lifetime and never reset (ALPHA §1).**
- `α_k = α_total·2^−k_life`, and `alpha_spent(lineage) = α_total·(1 − 2^−k_life_max)`, which is < α_total for the lineage's whole life.
- α is charged at assignment, including for candidates that later become `INCONCLUSIVE(window_cap_below_n_min)` or nominal.
- **Registry cross-check:**
  - `store_count − pending ≤ R ≤ store_count`, and
  - registry `alpha_spent == α_total·(1 − 2^−R)` exactly (`Decimal`).
  - Otherwise ERROR.
- Under Rev 5, until Rev 7 adds `k_life` to `lineage_counters`, R is derived from the fold's MINT rows that carry a nominated stage-1 verdict id (read-only). It is **not** taken from Rev 5's window-scoped `candidates_evaluated`. P4-14 (§10) records this.
- Test `test_alpha_spent_lifetime_never_exceeds_total`.

**(r3, F1) Effective horizon (ALPHA §2).**
- `K_LIFETIME_EFFECTIVE` is a `pins.py` ceiling (proposed 6), owned by ARCH Rev 7.
- For a nominee with `k_life > K_LIFETIME_EFFECTIVE`:
  - `metrics.nominal = true`; the outcome can never be PASS;
  - at the look, the result is `INCONCLUSIVE(nominal_k_beyond_effective_horizon)`, with the descriptive p (Hoeffding tail when `⌈200/α_k⌉ > B_MAX`, §3.2);
  - its α is still charged.
- Test `test_k_beyond_effective_horizon_never_passes_and_charges_alpha`.

**(r3, F1) Mint limit (ALPHA §1, Rev 5 W7).**
- `mints_in_window` = the non-drill MINTs of the lineage in the window `forward_window_index(forward_eval_start_utc)`. Pre-screen failures count; drill MINTs do not.
- AUT-3 refuses MINT number K_max + 1 (store-enforced, Rev 5) and records `NO_CHANGE(k_max_reached)`.
- If `mints_in_window > K_max` ever appears on the AUT-4 side, the verdict is `ERROR(mints_in_window_exceeded)` with a CRITICAL (the engine reject reason is `k_exceeded`). Rev 5 makes this unreachable; it is kept only as a breach detector.
- Windows are tumbling: `FORWARD_WINDOW_DAYS` is set in the policy block (proposed 28, with `pins` bounds 28–120), anchored at `forward_window_anchor_date` = 2026-10-02.
- A candidate uses **no forward day past its window's end** (Rev 5 C4).

**(r3, F1) Window cap feasibility (ALPHA §3).**
- At nomination: `n_cap = stations × FORWARD_WINDOW_DAYS × uptime_floor`.
  - FORWARD_SHADOW: `uptime_floor = FORWARD_SHADOW_UPTIME_FLOOR` (policy, proposed 0.8, ≤ 1).
  - OFFLINE stage 2 (weather-only): `uptime_floor = 1`.
- If `n_min_eff > n_cap`: every daily verdict for that candidate and kind is `INCONCLUSIVE(window_cap_below_n_min)`, by construction, with counts only. It is final in the sense that no look is ever scheduled. The verdicts keep flowing.
- If `n_min_eff ≤ n_cap` but n has not reached n_min_eff when the window ends: `INCONCLUSIVE(window_end_underpowered)`, final.
- **Today:**
  - FORWARD_SHADOW n_min_eff ≥ 403 > n_cap = 4 × 28 × 0.8 = 89 (and > 480 at deff 1.5 even at the 120-day maximum), so it is INCONCLUSIVE by construction for every candidate.
  - OFFLINE stage 2 with σ_oof = 0.132: n_min_eff ≥ 1076 > 112, also INCONCLUSIVE by construction.
  - Recalibration child (σ_oof = 0.02): n_min_eff = max(⌈1.5 × 31⌉, 4 × 15) = 60 at k = 6 (52 at k = 4), which is ≤ 112. Feasible.
- Tests:
  - `test_window_cap_below_n_min_is_inconclusive_by_construction`;
  - `test_no_forward_day_past_window_end`;
  - `test_window_end_underpowered_final`.

**Stage 2: confirmatory on the rolling forward holdout.**
- Forward station-days are ≥ max(`forward_eval_start_utc`, 2026-10-02) and ≤ the window end.
- At the single look: the §3.2 test at α_{k_life} on `brier_rung_diff_vs_champion`; the R-C conjunct (§3.10); cluster sensitivity; the exclusion guard. PASS iff all four hold and `metrics.nominal = false`.
- `crps_tmax_diff_vs_champion` and `underconfidence_mean_signed_dev` are reported.

**Holdout.** As in r2: `RULING_holdout_freeze_and_forward_window_2026-10-03` is consumed by name; `open_holdout` is never called; the contamination is disclosed; `sigma_source_contaminated: true`; until the ruling is filed, `INCONCLUSIVE(SEALED_WINDOW)`.

**Drill child (Z2).** It gets `INCONCLUSIVE(NOT_DISTINCT)` with `assumptions ∋ drill`, no k_life, no α, and no `mints_in_window` slot.

### 3.6 LIVE_SEQUENTIAL over admissible labels

As in r2:
- inputs: admissible `window_complete` C2 rows, combined by `combine_station_day` (L-40);
- the registered boundary;
- mapping: CONTINUE→UNDERPOWERED; SURVIVE→PASS (only at n_max); KILL→FAIL; refusal→ERROR;
- families are enumerated from the fold;
- prefix exclusion (`climate_day < D0′`);
- its own lock, after the 14:15Z label slot.

Changes in r3:
- **(F10)** `n_min` = n at the first registered look (10). A FAIL from the R-B **loss stop** can occur before that look and is labelled `metrics.stop_reason = "loss_stop"`.
- **(F3) Acceptance under both ARCH rules.**
  - Under Rev 7 (P4-10), the verdict carries the family PREREG sha in its own field.
  - Under Rev 5, it carries the policy sha, and the family PREREG sha travels in `inputs[family_prereg]`. The policy ruling's block lists `PREREG_FQ_v1`'s sha in `accepted_family_preregs` (draft key, §3.10 R-D).
  - A FAIL is therefore accepted under either rule, and it DEMOTEs (§4 WP4 test).
  - **Honest gap:** before any policy ruling is filed, no autonomy DEMOTE is possible under either rule. The pre-autonomy controls (A1 halt, the existing PREREG v2 tallies) remain in force.

### 3.7 FORWARD_SHADOW and the slippage source

**Subjects.**
- Every CHALLENGER family, including the AUT-7 drill child while it is CHALLENGER (tagged `drill`, never a promotion input).
- A daily **champion baseline**: subject = champion, comparator `MARKET_ASK_IMPLIED`, `declared_action_class = NONE`, never a promotion input, no α.
- **(r3)** The baseline uses a trailing window of `FORWARD_WINDOW_DAYS` and the same window cap. With n_min ≥ 403, it is `INCONCLUSIVE(window_cap_below_n_min)` with counts and replay-path metrics: admitted days, exclusions by reason, parity results, closure sha. It exists to exercise replay→admission→scoring→verdict→journal every day.

**Replay.** A per-(closure, family artefact, station-day) `fs_replay` child. **(r3)** The cache key includes `artefact_sha256` and the manifest-modulo-allowlist sha. So a byte-identical drill child reuses the champion's replay output, and replays per day stay ≤ 4·(K_max + 1) (§3.12).

**Predicates.** All are required (intersection-union), each at α_{k_life}.
- **(a)** `brier_rung_diff_vs_market < 0` by the §3.2 test.
- **(b) (r3, F4) Joint lower bound on effective EV per take.**
  - `ev_eff = p_fill·ev_cond`, with `ev_cond = held − ask − θ·ask·(1−ask) − slippage_proxy`.
  - Three uncertain components, each bounded at **α_k/3** (Bonferroni, valid under any dependence), so the joint bound holds at level 1 − α_k:
    1. `LB_ev`: the date-cluster sign-flip lower bound on the mean per-station-day ev_cond, computed at α_k/3 with the proxy at its point value;
    2. `UB_slip = mean_slip + z_{1−α_k/3}·SE_slip` (floored at 0.01), so the conservative ev_cond shift is `−(UB_slip − slippage_point)`;
    3. `p_fill_LB`: the Wilson lower bound at 1 − α_k/3 of the live FQ IOC fill rate (trailing 28 days).
  - `LB_eff = (LB_ev − (UB_slip − slippage_point))·p_fill_LB` if that bracket is > 0; otherwise (b) fails.
  - **`N_IOC_MIN` = 30** (policy, R-D): with fewer resolved FQ IOC trials in the trailing window, the result is `INCONCLUSIVE(fill_rate_underpowered)`. At the measured ~7 IOCs a day this clears in about 5 trading days.
  - `N_PROXY_MIN = 30` champion fills as in r2, otherwise `INCONCLUSIVE(PROXY_UNDERPOWERED)`.
  - n_b and `n_min_b` as in r2. The B cap of §3.2 applies at α_k/3. C_min uses α_k/3.
  - Tests: `test_forward_shadow.py::test_b_joint_bound_bonferroni_alpha_over_3`, `::test_fewer_than_n_ioc_min_inconclusive`, `::test_worst_case_survivorship_bound_reported`.
- **(c)** The R-C relative calibration non-inferiority test against the champion (§3.10).
- **(d)** `n ≥ n_min_eff = max(n_min_eff_a, n_min_b, n_min_c, 4·C_min)`, with n_min_c from §3.10 R-C (F5).
- **Look rule:** the look fires only when every predicate's n is met, inside the window. If not, see the §3.5 window-cap and window-end rules. `resolution_diff_vs_market` is reported.

**Slippage source.**
- `slippage_point = max(0.01, mean_slip)`, from C2 `slippage` over admissible champion fills (trailing 28 days, matched via C1 `depth_ref`).
- Tags: `assumptions: [slippage_champion_proxy, slippage_floor_aud12a, fill_survivorship_unmodelled]`. Without R-E acceptance the verdict is `INCONCLUSIVE`.

**(r3, F4) Survivorship: direction stated correctly, with a bound that does not depend on the direction.**
- *Estimator.* ev_cond is computed over **all** shadow takes, which are assumed to fill at the ask. `p_fill` multiplies it as if fills were independent of outcome.
- *Direction.*
  - If the IOC misses are concentrated in the decisions that were favourable to Breezy (informed flow lifts the ask first), then E[ev | fill] < E[ev]. The true realised EV per decision is then **below** p_fill·E[ev_cond], and (b) is **anti-conservative**.
  - If the misses are the unfavourable decisions, (b) is conservative.
  - The review's statement that the bias is conservative when misses are the favourable decisions holds for an estimator computed on *filled* decisions only. That is not this estimator (§R3 F4).
- *Bound.*
  - The verdict also reports `metrics.ev_eff_worst_case`, the Manski-style bound that assigns the misses to the highest-ev_cond decisions: `(1/N)·Σ` of the smallest `⌈p_fill_LB·N⌉` ev_cond values.
  - It is **descriptive**. If `ev_eff_worst_case ≤ 0` while (b) passes, `assumptions ∋ fill_selection_sensitive` is added, and R-E decides whether to accept it.
- An unresolved AMBIGUOUS IOC counts as a miss.

### 3.8 Feasibility record

`evidence/autonomy/feasibility/feasibility_<YYYY-MM-DD>.json` (0444, daily, written by `eval_offline`) carries the r2 keys plus the following **(r3)** keys:
- `n_cap_forward_shadow`, `n_cap_offline_stage2`, `uptime_floor`, `forward_window_days`;
- `k_lifetime_effective`, `b_max`;
- `mde_at_alpha_k_lifetime_effective` (the Rev 5 "MDE at α_K", restated under ALPHA);
- `live_mde_at_n_max` and `live_power_at_n_max_by_delta` (F14);
- `per_candidate: [{family_id, k_life, mints_in_window, alpha_k, nominal, n_min_eff_by_predicate, n_min_eff, n_cap, window_cap_feasible, window_end, eta_date}]`.

Rules:
- **`feasibility_consistency`** FAILs if `promote_enabled = true` and, for any live CHALLENGER, any of these holds:
  - `n_min_eff > n_cap`;
  - `eta_date ≥ kill_date`;
  - `eta_date > window_end`;
  - `nominal = true`.
- Test `test_consistency_uses_assigned_k_and_window_cap`.

### 3.9 Schedule, locks and the ATTEST interaction

| Unit (Type=oneshot) | OnCalendar (UTC) | Lock / `-w` (inside ExecStart) | **TimeoutStartSec** (r3, F8) | Worst end | MemoryMax |
|---|---|---|---|---|---|
| `breezy-autonomy-eval-offline` | 11:00 | `breezy-studies.lock`, 900 s | **6300** (covers the wait; 6300 = 7200 − 900) | **12:45** | 12G (§3.12) |
| `breezy-autonomy-eval-live` | 14:45 | own `breezy-autonomy-eval-live.lock`, 300 s | 1500 | 15:10 | 1G |

Both units add `ExecStopPost=` for the run record (§3.11). Neither sets `RuntimeMaxSec`, which has no effect on oneshot units (host systemd 259; `man systemd.service`).

**(r3, F8) No offline expiry gap.**
- The previous verdict is valid until 11:00 + 26 h = 13:00 the next day.
- The successor lands by 12:45 at worst, so the overlap is ≥ 15 min.
- r2's 45-minute gap is closed without an expiry exemption.

**Neighbouring slots** (owned by other plans): AUT-2 labels at 14:15; engine at 15:30; canary at 15:45; post-STOP RECONCILIATION at 16:41–16:43 (W8); pre-launch at 16:45.

**Margins.**
- `eval_offline` ends 1 h 30 min before the label slot.
- `eval_live` ends 20 min before the engine.

**Contract test** `tests/contract/test_autonomy_units.py::test_units_do_not_contend_on_flock`:
- it parses `OnCalendar`, the lock, `-w` and **`TimeoutStartSec`** (the end of a oneshot);
- the r2 assertions 1–4 hold;
- **(r3)** it asserts that no AUT-4 oneshot unit sets `RuntimeMaxSec` as its only bound.

Also `::test_eval_live_starts_after_label_slot_ends` and `::test_consumption_instants_inside_validity` (no gap now for either unit).

**ATTEST (Rev 5 W1; arithmetic corrected, F1).**
- AUT-4's 26 h verdicts are **not** cited by ATTEST. AUT-4 supplies `health.eval_staleness(fold, verdict_store, now_ns)`; the AUT-6 intraday producer evaluates it and writes a HEALTH verdict with `ATTEST_VERDICT_VALIDITY_H` = 8 h validity.
- **Freshness rule (r3, F11).** A producer's newest verdict is fresh only if it is unexpired **and** its outcome ≠ `ERROR`. `eval_staleness` FAILs if either of these holds:
  - any CHAMPION or HALTED family lacks a fresh LIVE_SEQUENTIAL verdict after `14:45 + 1500 s + 15 min`;
  - any AUT-4 producer's newest verdict is not fresh.
- **Invariant (Rev 5 §4.5):** `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H`, where `L_max = INTRADAY_ATTEST_VERDICT_PERIOD_MIN (≤ 60 min) + 150 s engine offset = 1.04 h`. So 6 + 1.04 + 0.5 = 7.54 ≤ 8, and a newly cited `eval_staleness` verdict outlives the next ATTEST by ≥ 0.46 h. (r2's "5 min + 150 s, ≥ 1.5 h margin" is withdrawn.)
- Test `test_attest_cadence_has_no_expiry_gap_with_eval_staleness`, which uses Rev 5's constants.
- The kind-level `attest_required_verdict_kinds` remains an ARCH dependency (P4-7, §6.4).

### 3.10 Ruling drafts (NOT decided; for the AUT-5 policy ruling and its peer review)

**Holdout.** There is no AUT-4 text; the ARCH ruling is consumed by name.

**R-B `PREREG_FQ_v1` (sequential).** Revised for F6.
> "Statistic S_k/I_k as `combine_station_day`/`score_combined`. LD-OBF spending, one-sided α = 0.025, a look every 10 combined station-days, n_max and loss stop **as derived in the committed design JSON**.
>
> **Derivation (both committed in the design JSON, with every input's source; no input is an FQ outcome):**
> - n_max = the largest multiple of 10 for which the seeded accrual simulation gives P(reach n_max by 2027-01-24 | D0′_planned, node uptime u = 0.7) ≥ 0.80. The simulation uses: per-day station-days ~ Binomial(4, q), q ~ Beta(8, 2) from FQ **take counts**, not PnL; uptime ~ Bernoulli(u); seed 20261003; 4000 runs.
> - The design JSON then states MDE_0.8 = (z_{1−α_final} + z_{0.8})·σ₀/√n_max, with σ₀ = 0.5 (the Bernoulli maximum, data-free) and α_final the LD-OBF final nominal level from `crh_group_sequential_boundaries.py`, plus the power at δ ∈ {0.05, 0.10, 0.15}.
> - Loss stop L = −q_0.05 of min_t ΣPnL_t under H1 (true hold-rate edge = MDE_0.8), from the WP7a Monte-Carlo at qty 1 contract unit. Asks are drawn from the FQ-rung quote tape, which is market data and not FQ PnL. So under a real edge of MDE size the stop fires in at most 5% of runs.
>
> D0′ = the climate day after this ruling is filed. Every FQ fill with climate_day < D0′ is a diagnostic prefix, excluded from n, from every look and from boundary calibration.
>
> The design JSON `docs/evidence/PREREG_FQ_v1_design_<date>.json` (sha256 `<sha>`) was committed before AUT-2a's first FQ label run. `scripts/analysis/prereg_precommit_check.py` attests that every FQ-PnL-bearing artefact whose filesystem birth time precedes the design commit's committer time is listed, with its sha, in the JSON's `pre_commit_pnl_exposure` disclosure. Changing any parameter after the commit voids this ruling.
>
> The boundary is produced by `crh_group_sequential_boundaries.py` and validated by a seeded H0 Monte-Carlo that replays the live look loop verbatim (L-40, L-41). KILL (including the loss stop) → FAIL → DEMOTE (entry-only)."

**Disclosure (F6, honest limit).**
- The precommit check proves which FQ-PnL artefacts **existed** before the commit, and forces each one to be disclosed. It cannot prove that no agent **read** one, because file access times are unreliable under `relatime`.
- Its guarantee is weaker and checkable: no design input is an FQ outcome, every input's source is in the JSON, and every pre-existing PnL exposure is disclosed.
- The r2 author read counts only.
- If the rule yields an n_max other than r2's 160, the rule's value is used.

**R-C, calibration non-inferiority (relative; r3, F5).**
> "On the verdict's own evaluation set, with the reliability bins of `forecast_conditional_scoring.py:303`, define for each model:
> - ECE = the n-weighted mean |obs − pred| over buckets with n ≥ 30 for **both** candidate and champion;
> - MSD = the mean signed deviation.
>
> The conjunct holds iff:
> (i) the one-sided (1 − α_k) upper bound of ΔECE = ECE_cand − ECE_champ is < δ_C = 0.01;
> (ii) the one-sided (1 − α_k) upper bound of |MSD_cand| − |MSD_champ| is < δ_M = 0.005.
>
> Both bounds come from a **paired date-cluster bootstrap** (dates resampled jointly for both models; seed `roi_bound.SEED`; B as §3.2).
> **Fail-closed:** fewer than `N_BUCKETS_MIN` = 3 qualifying buckets → `INCONCLUSIVE(calibration_buckets_insufficient)`.
> **Power in n_min:** `n_min_c` is the smallest n at which, under the out-of-fold archive differences, P(≥ N_BUCKETS_MIN qualifying buckets) ≥ 0.95 **and** the power of (i) ∧ (ii) at true ΔECE = 0, ΔMSD = 0 is ≥ 0.80. It is computed by seeded simulation at stage 1 and enters n_min_eff.
> The absolute leg (`evaluate_calibration_leg`, ε = 0.05) is reported and never gated."

This conflicts with Rev 5 C4 FORWARD_SHADOW (c), which requires the absolute leg (P4-15, §10).

**R-D, α and candidates (r3: ALPHA adopted).**
> "α_total = 0.025 one-sided, spent **lifetime-geometrically** per lineage: α_k = α_total·2^−k_life, where k_life counts nominated candidates over the lineage's life and never resets.
> `K_LIFETIME_EFFECTIVE` = 6 (pins): above it a candidate is nominal (descriptive, α charged, never PASS).
> K_max = 4 MINTs per lineage per forward window (`mints_in_window`; pre-screen failures count, drill MINTs do not).
> `FORWARD_WINDOW_DAYS` = 28 (pins bounds 28–120), anchored at 2026-10-02; no forward day past the window's end.
> `FORWARD_SHADOW_UPTIME_FLOOR` = 0.8; n_min_eff > n_cap → INCONCLUSIVE(window_cap_below_n_min).
> `PRESCREEN_MIN_FOLD_WINS` = 4 of 6. X = 0.0152 (Brier); X_EV = 0.02 per contract.
> `EXCLUDED_FRACTION_MAX` = 0.25; `N_PROXY_MIN` = 30; `N_IOC_MIN` = 30; `N_BUCKETS_MIN` = 3; δ_C = 0.01; δ_M = 0.005.
> `accepted_family_preregs`: {`PREREG_FQ_v1`: `<sha>`} (the Rev 5 acceptance fallback, F3).
> PROMOTE requires OFFLINE stage-2 PASS ∧ FORWARD_SHADOW PASS, one α charge per candidate."

**R-E, slippage (r3).**
> "`slippage_champion_proxy` is accepted for challengers whose manifest equals the root's except for the §4.2 allowlist. The slippage point is max(AUD-12a 0.01, mean). The (b) bound is the Bonferroni joint bound at α_k/3 per component (ev, slippage, fill rate). It is refused below N_PROXY_MIN fills or N_IOC_MIN IOCs. The fill-survivorship bias is disclosed (anti-conservative if misses are the favourable decisions). `fill_selection_sensitive` is [accepted | not accepted]."

**R-F, feasibility (r3, F1).**
> "The §3.8 record at filing, including `n_min_eff`, `n_cap` and `window_cap_feasible` per candidate. With today's σ, X and window, every FORWARD_SHADOW verdict is INCONCLUSIVE(window_cap_below_n_min) by construction, and `promote_enabled=false` (consistent with the AUT-5 feasibility ETA 2027-05-06 > KILL). Evidence class: machinery proven, edge unproven."

**R-G, CHALLENGER admission.** As in r2.

### 3.11 Evaluator self-monitoring

| Detector | Producer | FAIL condition | Proposed action class |
|---|---|---|---|
| `eval_completeness` | each unit | a fold family or candidate lacks today's verdict of a required kind; **(r3)** or `replay_backlog_days > 3 × MAX_BACKLOG_DAYS_PER_RUN` | ALERT |
| `eval_excluded_fraction` | eval_offline | as in r2 | ALERT |
| `eval_n_stalled` | eval_live | as in r2 | ALERT |
| `eval_resource_creep` | each unit | wall > 0.8 × TimeoutStartSec, or peak RSS > 0.8 × MemoryMax (parent/cgroup) or > 0.8 × child share, on 2 of the last 3 runs; **(r3)** a run with no producer record but an `ExecStopPost` record whose `service_result ≠ success` counts as over budget | ALERT |
| `eval_staleness` | AUT-6 intraday producer | §3.9 (ERROR is not fresh) | ATTEST-required |

**(r3, F11) The run-record store.**
- Path: `derived/autonomy/eval_runs/<producer_id>/<YYYY-MM-DD>_<unit_start_ns>.json` (0444, one file per run, single writer, so no L-50 rewrite race).
- Written by:
  1. the producer at exit: `wall_s` (monotonic), `peak_rss_parent_bytes` (`getrusage`), `peak_rss_children_bytes[]` (from `run_with_rss_share`), `verdict_outcomes`;
  2. `ExecStopPost=` (`python -m breezy.analysis.autonomy.run_record --stoppost`): `service_result` (`$SERVICE_RESULT`), `exit_status`, and the cgroup `memory.peak` bytes, written to `<…>_stoppost.json`.
- So a timeout or OOM kill is still recorded.
- `eval_resource_creep` reads only this store.

**Pin mismatch.** As in r2.

### 3.12 Memory and runtime budget

**Memory.** As in r2: `MemoryMax=12G` = parent 2G + max(pre-screen 4G, P·S); S = ⌈1.25·R⌉ from WP0; P = 2 if S ≤ 4G, P = 1 if S ≤ 9G; hard fail above.

**(r3, F12/F13) Per-run replay budget.**
- `deadline = unit_start + EVAL_OFFLINE_TIMEOUT_START_S − SAFETY_S`, the replay-daily pattern (`replay-daily-run.sh:48-50`).
- Replay phase wall budget = deadline − elapsed (including the flock wait) − `PRESCREEN_BUDGET_S` − `SCORING_RESERVE_S`. At the worst wait (900 s) this is 6300 − 900 − 900 − 600 − 300 = **3600 s**.
- **`FS_REPLAY_CHILD_TIMEOUT_S` = ⌊P × 3600 / (4·(K_max + 1))⌋**: 360 s at P = 2 and 180 s at P = 1. Here 4 is the station count, and K_max + 1 is the challengers plus the champion, because the drill child reuses the champion's cache (§3.7).
  - This is the r2 "360 s", now named and derived.
  - Test `test_child_timeout_derived_from_budget` recomputes it from the literals.
  - With more than one live lineage, the denominator becomes 4·Σ(K_max + 1), re-derived in the same reviewed commit.
- **Launch rule:** a child starts only if `now + FS_REPLAY_CHILD_TIMEOUT_S ≤ deadline − SCORING_RESERVE_S − SAFETY_S`.
- **Order:**
  1. today's station-days: champion first, then CHALLENGERs in k_life order;
  2. backlog, oldest first: `PENDING_RECLOSURE` days and missed days, at most `MAX_BACKLOG_DAYS_PER_RUN = 3` days.
- **Partial commit:** each completed (closure, artefact, station-day) output is committed atomically (tmp + rename, 0444) when its child exits. When the budget is exhausted, no new child starts, scoring runs on committed outputs only, and unreplayed days stay queued with `metrics.replay_backlog_days`. A half-written output never exists.
- Backlog days past their candidate's window end are dropped by name (`BACKLOG_EXPIRED`).
- **WP0 hard-fail rule (extended):** `t_p95 ≤ 0.8 × FS_REPLAY_CHILD_TIMEOUT_S` must hold for the chosen P. Otherwise WP6 does not merge and the plan returns to review.
- Tests: `test_memory_budget.py::test_replay_budget_partial_commit_resumes_backlog`, `::test_no_child_launched_past_deadline`, `::test_backlog_expired_past_window_end`.

### 3.13 Engine input journal (AUT-4 owns the schema; AUT-5 writes it)

As in r2: `engine_input/v1`, one JSONL file per pass under `evidence/autonomy/engine_inputs/<venue>/<YYYY-MM-DD>/`, with the contract tests in `tests/contract/test_engine_input_journal_contract.py`. ARCH adoption is P4-9.

**(r3, F7)** The fixture-registry pass (§6.1) writes to `evidence/autonomy/engine_inputs/fixture/<date>/`, so it can never be confused with a venue pass (`test_fixture_journal_never_under_venue_dir`).

---

## 4. Work packages

**Gate commands for every WP** (run by the coordinator, never trusted from an agent):
- interpreter: `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python`;
- `scripts/ci/run_tests_no_egress.sh`, the full gate after every merge (L-43), launched with `-p LimitNOFILE=524288` and basetemp on `~/.cache`;
- `cd <tree> && lint-imports`, which must print "N kept, 0 broken";
- the mypy ratchet.

Never `uv`/`pip` (L-51), never `git stash`. Activation is immediate on merge unless stated otherwise.

**WP0: measurements (read-only).**
- The r2 items (i)–(vii) are kept.
- (iv) adds t_p95 against the derived child timeout (§3.12).
- **(r3)** Additional items:
  - (viii) `n_min_c` inputs (F5) on out-of-fold archive data: bucket occupancy and the ΔECE/ΔMSD variance;
  - (ix) resolved FQ IOC trials per day, for the `N_IOC_MIN` ETA;
  - (x) the trailing node-up fraction, as context for `FORWARD_SHADOW_UPTIME_FLOOR`.
- GREEN: every number is sourced, and the §3.12 hard-fail rules have been evaluated.

**WP1: extraction.** As in r2: verbatim, characterisation-pinned (L-33), with mutation evidence.

**WP2: pure evaluation core.**
- Files: `eval_stats.py`, `permutation.py`, `calibration_ni.py`, `metric_registry.py`, `windows.py`, `leakage.py`, `budget.py`.
- RED first: the r2 names, plus **(r3)**:
  - `tests/unit/autonomy/test_permutation.py::test_b_capped_and_hoeffding_tail_beyond_cap`, `::test_b_max_covers_k_lifetime_effective`;
  - `tests/unit/autonomy/test_calibration_ni.py::test_relative_calibration_one_sided_with_margin`, `::test_fewer_than_n_buckets_min_inconclusive`, `::test_n_min_c_enters_n_min_eff`;
  - `tests/unit/autonomy/test_eval_stats.py::test_n_cap_formula`, `::test_power_at_n_reported`;
  - `tests/unit/autonomy/test_verdict_identity.py::test_recompute_is_noop_under_rev5_identity`;
  - `tests/unit/autonomy/test_verdict_validity.py::test_offline_successor_lands_before_predecessor_expiry`;
  - `tests/unit/autonomy/test_budget.py::test_child_timeout_derived_from_budget`.
- GREEN: all pass.

**WP3: FQ tape admission and oversize quarantine.**
- As in r2, plus **(r3)** `test_tape_admission.py::test_n_counts_current_closure_days_only`, `::test_mixed_fs_replay_closure_is_inconclusive`.

**WP4: LIVE_SEQUENTIAL and the `eval-live` unit.**
- Unit: `TimeoutStartSec=1500` (not `RuntimeMaxSec`), `ExecStopPost=` run record.
- RED first: the r2 names, plus **(r3)**:
  - `test_eval_live.py::test_n_min_is_first_look_n`, `::test_loss_stop_fail_labelled`;
  - `tests/integration/autonomy/test_live_fail_demotes_under_rev5_acceptance.py::test_live_sequential_fail_accepted_and_demotes_with_policy_sha_field` (F3: a fixture AUT-5 engine under the Rev 5 acceptance rule; FAIL → ACCEPTED → DEMOTE, with the verdict in `cause_verdict_ids`);
  - `::test_family_prereg_not_in_accepted_list_is_error`;
  - `::test_live_sequential_fail_accepted_under_two_field_rule` (Rev 7 path, skipped with a named reason until ARCH-0 ships the field).
- Activation: enable the timer on merge.

**WP5: OFFLINE_CHALLENGER and the α ledger.**
- RED first: the r2 names, renamed `k_in_window` → `mints_in_window`, plus **(r3)**:
  - `test_alpha_ledger.py::test_two_pending_nominees_get_distinct_k`, `::test_stage2_reads_k_from_stage1_never_recomputes`, `::test_crash_between_nominees_keeps_k_distinct`, `::test_prescreen_fail_consumes_mint_slot_not_k`, `::test_registry_cross_check_uses_k_life`;
  - `test_offline_challenger.py::test_k_beyond_effective_horizon_never_passes_and_charges_alpha`, `::test_window_cap_below_n_min_is_inconclusive_by_construction`, `::test_no_forward_day_past_window_end`, `::test_window_end_underpowered_final`.

**WP6: FORWARD_SHADOW, the `fs_replay` children and the `eval-offline` unit.**
- Unit: `TimeoutStartSec=6300`, studies flock `-w 900` inside ExecStart, `MemoryMax=12G`, `ExecStopPost=` run record.
- RED first: the r2 names, plus **(r3)**:
  - `test_forward_shadow.py::test_b_joint_bound_bonferroni_alpha_over_3`, `::test_fewer_than_n_ioc_min_inconclusive`, `::test_worst_case_survivorship_bound_reported`, `::test_drill_child_reuses_champion_replay_cache`, `::test_baseline_window_capped_inconclusive_with_path_metrics`;
  - `test_memory_budget.py::test_replay_budget_partial_commit_resumes_backlog`, `::test_no_child_launched_past_deadline`, `::test_backlog_expired_past_window_end`;
  - `test_pins.py::test_aut4_producer_ids_registered_in_pins` (F13: `eval_live`, `eval_offline` and `fs_replay` are keys of `PRODUCER_SOURCE_SHA256`; `eval_offline` refuses an `fs_replay` output whose stamped closure is not in `PRODUCER_SOURCE_SHA256["fs_replay"]`);
  - existing `test_execution_egress_firewall_guard`, unchanged.
- Activation: enable the timer on merge.

**WP7a: R-B design commit, H0 MC and precommit check (docs, evidence and a read-only script; starts NOW).**
- (1) **(r3, F6)** Write `scripts/analysis/prereg_precommit_check.py`. It is read-only: it lists the FQ-PnL-bearing artefacts (FQ `labels_*.parquet`, digest files with FQ PnL fields) with `stat` birth time and sha, and compares them with the design commit's committer time.
  - RED: `tests/unit/test_prereg_precommit_check.py::test_undisclosed_pre_commit_pnl_artefact_fails`, `::test_post_commit_artefact_ignored`, `::test_disclosed_artefact_passes`.
- (2) Compute n_max, MDE_0.8, the power table and L by the §3.10 rules (accrual simulation; H1 MC on tape asks). Write all of them, with their derivations and input shas, into `docs/evidence/PREREG_FQ_v1_design_<date>.json`, together with `pre_commit_pnl_exposure`. Commit before AUT-2a's first FQ label run.
- (3) Boundary plus H0 MC under `TimeoutStartSec`, outside 01:00–04:30Z.
- (4) Hand to the peer loop.
- GREEN: the precommit check exits 0, and the MC meets the R-B criteria.

**WP7b: feasibility.** RED first: `test_feasibility.py::test_consistency_uses_assigned_k_and_window_cap`, `::test_record_includes_n_cap_and_k_life`, `::test_record_reports_live_power_at_n_max` (F14), plus the r2 names.

**WP8: self-monitoring and the journal contract.**
- RED first: the r2 names, plus **(r3)**:
  - `test_health.py::test_error_verdict_is_not_fresh`, `::test_resource_creep_counts_killed_run_from_stoppost_record`, `::test_backlog_growth_fails_completeness`;
  - `test_run_record.py::test_stoppost_writes_service_result_and_memory_peak`;
  - `test_attest_cadence_has_no_expiry_gap_with_eval_staleness` with the Rev 5 constants;
  - `test_engine_input_journal_contract.py::test_fixture_journal_never_under_venue_dir`.

**WP9: live-proof run** (§6). No code.

**Producer-pin rotation runbook.** As in r2: append-only per Z9; closures narrowed. **(r3)** An `fs_replay` rotation also triggers `PENDING_RECLOSURE` re-replay through the §3.12 backlog (F9).

---

## 5. Association

| Contract | From → AUT-4 | AUT-4 → |
|---|---|---|
| C1 | AUT-1: Take/TrySubmit, `forecast_input_sha256` (AUT-1's hashing function), `LifecycleEvent` | — |
| C2 | AUT-2: admissible rows, `slippage`, `realized_pnl`; the label slot ends by 14:40Z | — |
| C3 | AUT-3: lineage windows; **≤ K_max MINTs per window via `alpha_ledger.forward_window_index`**; `NO_CHANGE(k_max_reached)` | `forward_window_index` |
| C4 | — | AUT-5 engine; AUT-7 (accepted FAIL). **(r3)** Fields `k_life`, `alpha_k`, `mints_in_window`, `n_min_eff`, `n_cap` (ALPHA §4) |
| C5 | AUT-5: fold; `lineage_counters` (`k_life` under Rev 7, P4-14); bound sha | — |
| C6 | ARCH-0 | `FqEvaluator`; `eval_staleness` → AUT-6 |
| Engine input journal | AUT-5 writes it; **(r3)** plus the fixture-registry pass (F7) | AUT-4 owns the schema and tests |
| Policy block | AUT-5 files it | AUT-4 drafts R-B…R-G and the keys `FORWARD_WINDOW_DAYS`, `FORWARD_SHADOW_UPTIME_FLOOR`, `X_EV`, `EXCLUDED_FRACTION_MAX`, `N_PROXY_MIN`, `N_IOC_MIN`, `N_BUCKETS_MIN`, δ_C, δ_M, `accepted_family_preregs` |
| `pins.py` | ARCH-0 (Rev 7: `K_LIFETIME_EFFECTIVE`) | AUT-4 registers producer ids `eval_live`, `eval_offline`, `fs_replay` |
| Drill child | AUT-7 | FORWARD_SHADOW verdicts while CHALLENGER (§6.1 coverage path 2) |

**Order.**
- **Now, in parallel:** WP0, WP1, WP7a.
- **After WP1:** WP2 and WP3.
- **After ARCH-0 + AUT-2a:** WP4.
- **After AUT-3 + AUT-5a:** WP5, WP6.
- **After WP0 + WP6:** WP7b.
- **After AUT-6's intraday producer + AUT-5's journal:** WP8.

---

## 6. Live-proof protocol

### 6.1 Artefact

`docs/evidence/AUT4_LIVE_PROOF_<start>_<end>.md` is produced by a read-only script, run by an agent that did not build AUT-4. It covers 7 consecutive qualifying days (≥ 1 real fill per day, ≥ 5 real fills in the window). It records the r2 per-day contents:
- LIVE_SEQUENTIAL per fold family (never `NO_REGISTERED_PREREG`);
- OFFLINE_CHALLENGER per minted candidate (stage, `k_life`, `mints_in_window`, `alpha_spent`, `n_cap`, `window_cap_feasible`);
- FORWARD_SHADOW per CHALLENGER and for the champion baseline;
- consumption through the `engine_input/v1` daily journal;
- `eval_completeness` PASS, the `eval_staleness` HEALTH verdicts in the ATTEST rows, timer-only runs, and `producer_code_sha` values in `pins.py`.

**(r3, F7) Candidate coverage.** At least 3 of the 7 days must carry ≥ 1 candidate verdict, from any of these paths (in order of preference):
1. **Real AUT-3 candidates:** OFFLINE stage-1 verdicts, plus FORWARD_SHADOW for any CHALLENGER.
2. **The AUT-7 drill child** while it is SHADOW or CHALLENGER on the real venue: its stage-1 `INCONCLUSIVE(NOT_DISTINCT)` (tagged `drill`) and daily FORWARD_SHADOW verdicts, journaled by the real engine pass.
3. **The fixture-candidate path:** the same pinned `eval_offline` closure runs on the production host against a fixture registry root holding a deterministic recalibration child of the champion artefact, on real archive and tape days. AUT-5's engine runs a fixture-registry pass that journals under `engine_inputs/fixture/`. Verdicts carry `assumptions ∋ fixture_candidate` and never touch the venue registry.

A day with no candidate verdict is otherwise acceptable only if AUT-3's run journal names a reason (`NO_MINT`, `NO_CHANGE(k_max_reached)`, `NOT_FITTABLE`, `MINT_REFUSED_CEILING`).

**Score if AUT-3 nominates no real candidate.** The target stays **3**. It is reached through path 2 or 3, and the DONE claim states: "machinery proven (drill/fixture candidate path), edge unproven; no real AUT-3 candidate was evaluated in the window". A window with no candidate verdict on any path on ≥ 3 days is not a proof.

### 6.2 Drills

As in r2:
- SIGKILL `eval_offline` → OnFailure CRITICAL `delivered=true`; `eval_staleness` FAIL; ATTEST withheld; recovery. **(r3)** Also the `_stoppost.json` record shows `service_result=signal`.
- Oversize tape day.
- Unpinned producer.

**(r3)** Additional drill: forced `TimeoutStartSec` overrun in a test unit. The partial replay outputs are committed, the backlog is queued, and the next run resumes it.

### 6.3 Accrual, power and pre-KILL probability

**Measured inputs (2026-10-03).** As in r2:
- FQ IOC fill rate 12/14 = 0.857, Wilson 95% [0.601, 0.960];
- 3.5 station-days with a take per climate day (n = 2 days);
- σ(fc − mkt) = 0.099 (contaminated window, disclosed);
- deff is assumed to be 1.5 until WP0 measures it;
- accrual is capped at 4 station-days per day.

| Verdict | n_min_eff (deff 1.5) | **n_cap** (28-day window) | Outcome before the KILL |
|---|---|---|---|
| FORWARD_SHADOW (a), k_life = 1 | 605 (403 at deff 1) | 4 × 28 × 0.8 = 89 | **`INCONCLUSIVE(window_cap_below_n_min)` by construction** |
| FORWARD_SHADOW (a), k_life = 6 | > 605 | 89 | the same |
| OFFLINE, σ_oof = 0.132 | k=1: 1076 | 112 | the same |
| OFFLINE, recalibration child σ_oof = 0.02 | 52 (k=4); 60 (k=6) | 112 | feasible: powered in about 13–15 days, but expected FAIL (gain ≈ 0.006 against X = 0.0152) |
| LIVE_SEQUENTIAL FQ under R-B | registered (n_min = first look 10; n_max per WP7a, r2 value 160) | not windowed | see below |

**LIVE_SEQUENTIAL: probability of reaching n_max = 160** (r2 seeded simulation: seed 20261003, 4000 runs; Binomial(4, q), q ~ Beta(8, 2), uptime Bernoulli(u)):

| D0′ | u = 0.5 | u = 0.6 | u = 0.7 | u = 0.8 |
|---|---|---|---|---|
| 2026-10-25 | 0.34 | 0.73 | 0.89 | 0.96 |
| 2026-11-10 | 0.05 | 0.33 | 0.67 | 0.86 |

**(r3, F14) Power at n = 160.**
- Normal approximation; σ₀ = 0.5 per station-day (Bernoulli maximum); one-sided α = 0.025; LD-OBF final critical value ≈ 2.02.
- Power by true hold-rate edge δ:

| δ | 0.05 | 0.10 | 0.113 | 0.15 |
|---|---|---|---|---|
| Power | ≈ 0.22 | ≈ 0.69 | **0.80 (MDE_0.8)** | ≈ 0.96 |

- So reaching n_max is not the same as detecting a +0.10 edge. The unconditional probability of a SURVIVE given a true δ = 0.10 at D0′ = 10-25, u = 0.7 is ≈ 0.89 × 0.69 ≈ 0.61, ignoring earlier crossings.
- WP7a replaces these approximations with the MC values in the design JSON.

**Consequences.**
- `promote_enabled=false`.
- PROMOTE is machinery-proven by the AUT-7b drill only.
- Filing R-B early is the only lever.
- After about 2 windows, k_life > 6 makes every new candidate nominal.

### 6.4 Hard prerequisites and ETA

**Hard prerequisites before the proof window may start.** None is optional.

| # | Prerequisite | Owner | Target | Interim behaviour until met |
|---|---|---|---|---|
| 1 | `RULING_holdout_freeze_and_forward_window_2026-10-03` filed | ARCH | 2026-10-10 | `INCONCLUSIVE(SEALED_WINDOW)` |
| 2 | R-B `PREREG_FQ_v1` filed; design JSON and boundary committed; precommit check exits 0 | WP7a + peer loop | 2026-10-24 | `INCONCLUSIVE(NO_REGISTERED_PREREG)` |
| 3 | AUT-5 policy ruling filed (with `accepted_family_preregs`) | AUT-5 | — | `REJECTED(no_ruling)` |
| 4 | **ARCH Rev 7 adopts the ALPHA decision**: `k_life` / `mints_in_window`, `K_LIFETIME_EFFECTIVE` pin, C4 fields `n_min_eff` / `n_cap`, C5 `lineage_counters.k_life` (P4-14), and the definition of "evaluated MINT" (P4-13) | ARCH | Rev 7 | R derived read-only from the fold (§3.5); `K_LIFETIME_EFFECTIVE` held as an AUT-4 module literal (6) mirrored by a test |
| 5 | **ARCH P4-10** (two ruling-sha roles for LIVE_SEQUENTIAL) | ARCH | Rev 7 | **Rev 5 fallback**: policy sha in the field, PREREG in `inputs`, `accepted_family_preregs`; `test_live_sequential_fail_accepted_and_demotes_with_policy_sha_field` green, **so a FAIL can still DEMOTE** |
| 6 | **ARCH P4-11** (`verdict_id` without `produced_at_ns`) | ARCH | Rev 7 | **Rev 5 fallback**: producer-side `recompute_key` no-op; `test_recompute_is_noop_under_rev5_identity` green |
| 7 | ARCH P4-7 (detector-level ATTEST set) | ARCH | Rev 7 | `eval_staleness` is unenforceable as an ATTEST citation; the dead-evaluator veto is not live |
| 8 | ARCH P4-9 (`engine_input/v1` in C5) | ARCH | Rev 7 | the journal is written by AUT-5 under the AUT-4 contract test |
| 9 | ARCH P4-12, P4-15 (assumptions enum incl. `fixture_candidate`, `fill_selection_sensitive`; FORWARD_SHADOW (c) = the registered calibration predicate) | ARCH | Rev 7 | verdicts with unknown assumptions are refused by the writer, so they are not written |
| 10 | WP4–WP6 and WP8 merged and active | AUT-4 | — | — |

**ETA.**
- Earliest 2026-11-23; planning date 2026-11-30; latest acceptable 2026-12-31.
- **If R-B is not filed by 2026-12-01**, score 2 is declared in PROGRESS.
- **If Rev 7 has not shipped items 4–9 by 2026-12-15**, the proof window is not opened, and PROGRESS records "blocked on ARCH Rev 7 (items …)". The fallbacks keep demotion live in the meantime.

**Evidence class: machinery proven, edge unproven.**

---

## 7. Score-3 verification checklist (independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `systemctl --user list-timers 'breezy-autonomy-eval-*'`; `journalctl --user -u breezy-autonomy-eval-live.service -u breezy-autonomy-eval-offline.service --since <start>` shows timer-triggered runs only; `ls derived/autonomy/eval_runs/*/` shows one producer record and one `_stoppost.json` per run; no verdict has operator fields |
| (b) family-agnostic | `test_families_enumerated_from_fold_not_list`, `test_refusing_plugin_family_gets_error`, ARCH `test_family_plugin_exact_set`; one LIVE_SEQUENTIAL per fold family per day |
| (c) fails closed (**restated, F10**) | tests `test_underpowered_verdict_carries_no_effect_estimate`, `test_forecast_vintage_after_eval_ns_is_leakage_error`, `test_fewer_than_n_proxy_min_fills_inconclusive`, `test_fewer_than_n_ioc_min_inconclusive`, `test_window_cap_below_n_min_is_inconclusive_by_construction`, `test_k_beyond_effective_horizon_never_passes_and_charges_alpha`, `test_error_verdict_is_not_fresh`. Store queries, each returning nothing: (1) `jq 'select(.n_min != null and (.outcome=="PASS" or .outcome=="FAIL") and .n < .n_min and .metrics.stop_reason != "loss_stop")'`: no decision before n_min, where LIVE n_min = first-look n; (2) `jq 'select(.kind=="LIVE_SEQUENTIAL" and .outcome=="PASS" and .n < .metrics.n_max)'`; (3) `jq 'select(.outcome=="PASS" and (.metrics.nominal==true or .metrics.n_min_eff > .metrics.n_cap))'` |
| (d) detected and delivered | the §6.2 SIGKILL drill: `evidence/alerts/delivery_<date>.jsonl` line `delivered=true`; the `eval_staleness` FAIL; no ATTEST row in that window; the `_stoppost.json` record |
| (e) RED→GREEN | RED and GREEN output per §4 test; the gate exits 0 at each merge sha; `lint-imports` "N kept, 0 broken"; WP1 mutation evidence |
| (f) live proof | the §6.1 file; every verdict id in `evidence/autonomy/engine_inputs/<venue>/<date>/daily_*.jsonl` (fixture-path ids in `engine_inputs/fixture/`); candidate coverage ≥ 3/7 days with the path named; journal contract tests green |
| Prerequisites | the §6.4 table: ruling files dated before `<start>`; `prereg_precommit_check.py` exit 0; ARCH Rev 7 sha cited, or each fallback test green |
| Feasibility | daily record with `n_cap`, `k_life`, `live_power_at_n_max_by_delta`; `feasibility_consistency` PASS |
| Schedule | `test_units_do_not_contend_on_flock`, `test_offline_successor_lands_before_predecessor_expiry`, `test_attest_cadence_has_no_expiry_gap_with_eval_staleness`; `grep -L TimeoutStartSec deploy/systemd/breezy-autonomy-eval-*.service` is empty |
| Honesty | the DONE claim states "machinery proven, edge unproven", and names the candidate-coverage path |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity / KILL 2027-01-25** | Window cap makes FS INCONCLUSIVE by construction (stated, not hidden); k_life horizon; power at n = 160 reported; R-B early is the only lever; score-2 date set |
| Type I inflation across windows | Lifetime `k_life`, never reset (ALPHA); single look; LD-OBF for live |
| Uncomputable deep-k tests | B capped at 2¹⁹; Hoeffding tail beyond; nominal above K_LIFETIME_EFFECTIVE |
| k collision between same-run nominees | k_life assigned sequentially under the studies flock, store-counted, written before the next; stage 2 reads it |
| Joint-bound under-coverage in (b) | Bonferroni α_k/3 per component; `N_IOC_MIN`; worst-case survivorship bound reported; `fill_selection_sensitive` tag |
| Calibration conjunct untestable or underpowered | Paired non-inferiority with margins; `N_BUCKETS_MIN` fail-closed; n_min_c in n_min_eff |
| R-B tuned on the prefix | Data-free σ₀; n_max from take counts, not PnL; L from tape asks; precommit check forces disclosure; honest limit stated (existence, not reads) |
| Strategy edit mid-window mixes closures | Closure-keyed outputs; current-closure n; re-replay backlog; `mixed_closure` breach guard |
| Offline expiry gap | `TimeoutStartSec=6300` → ends ≤ 12:45 < 13:00 expiry |
| Oneshot unbounded by `RuntimeMaxSec` | `TimeoutStartSec` on every AUT-4 unit; contract test |
| Backlog grows without bound | Today-first, deadline launch rule, partial commit, 3 backlog days per run, `BACKLOG_EXPIRED`, completeness alert, WP0 t_p95 hard-fail |
| A killed run leaves no evidence | `ExecStopPost` run record with `service_result` and cgroup `memory.peak` |
| ARCH Rev 7 slips | Fallbacks for P4-10/P4-11 keep DEMOTE and idempotency; the proof window waits (§6.4) |
| Memory on the 30 GiB host | §3.12 inside the 16G studies cap; WP0 hard fail; no heavy job 01:00–04:30Z; stop the study, never the node |
| Shared venv / concurrent agents | Exact interpreter; no `uv`/`pip`/`stash`; worktree `PYTHONPATH`; per-agent scratchpads; explicit-path commits |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** only native `BacktestEngine`, `ParquetDataCatalog` and Actor composition; nothing is patched.
- **Caps:** never read, written or assigned. The R-B loss stop is a PREREG statistic in contract units, not a cap. `test_autonomy_never_reads_or_writes_operator_controls` covers `breezy.analysis.autonomy`.
- **allow_short=False:** untouched.
- **NO-SEND:** the refusing submit veto; no exec client; the exec store is never imported (`prereg_precommit_check.py` reads label and digest files only). `test_execution_egress_firewall_guard` is unchanged.
- **Master enablement and permit:** never touched. The fixture-registry pass never writes the venue registry.
- **PREREG via ruling:** R-B…R-G, including the ALPHA-derived R-D and R-F text, are drafts for the peer loop. The holdout is consumed by name.
- **Safety tests:** none weakened; golden and contract tests stay byte-unchanged; the new tests only add.

---

## 10. Self-score

| Axis | Max | r3 | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | ALPHA, Rev 5 W1/W7/W8 and HOLDOUT adopted; every §10 obligation mapped. −2: six ARCH items open on ARCH's side (prerequisites 4–9) |
| Correctness | 20 | 17 | Window cap, k_life, B cap with a valid tail, Bonferroni (b), survivorship direction derived, no expiry gap, derived child timeout. −3: deff, R and n_min_c unmeasured; the Hoeffding tail is loose; σ₀ = 0.5 power is a normal approximation |
| Specificity | 15 | 14 | Constants named and derived, paths, units, schemas, test names |
| Acceptance | 20 | 17 | Checklist (c) restated, coverage paths, prerequisite table with fallbacks. −3: the proof is gated on ARCH Rev 7 and three rulings |
| Autonomy-safety | 15 | 14 | Fail-closed; ERROR not fresh; killed runs recorded; DEMOTE live under Rev 5. −1: the dead-evaluator veto needs P4-7 |
| Reuse | 10 | 8 | Extraction-first; systemd/cgroup/stdlib for the run record. −2: new permutation, calibration-NI and journal contract |
| **Total** | 100 | **88** | r2 self-scored 86 against reviewers' 78; r3 is scored with that 8-point gap in mind |

### Contradictions with ARCH (for the ARCH owner)

The open r2 items stay open and are now hard prerequisites (§6.4):
- **P4-7** (detector-level ATTEST set);
- **P4-9** (engine input journal);
- **P4-10** (two ruling-sha roles; Rev 5 fallback in §3.6);
- **P4-11** (`verdict_id` identity; Rev 5 fallback in §3.1);
- **P4-12** (assumptions enum; r3 adds `fixture_candidate` and `fill_selection_sensitive`).

**P4-8** is superseded by the ALPHA decision.

**New in r3:**
- **P4-13 (ALPHA §1 wording).** "k_life counts every evaluated MINT" is ambiguous about pre-screen-failed MINTs. F2 requires assignment at stage-1 nomination. AUT-4 reads "evaluated" as nominated. Rev 7 should state it. If it means every MINT, the change is one line and more conservative.
- **P4-14 (C5 counter).** Rev 5 defines `lineage_counters.candidates_evaluated` = MINTs **in the window**, but ALPHA §4 makes the registry cross-check use `k_life`. C5 needs a lifetime `k_life` counter distinct from the window-scoped one.
- **P4-15 (C4 FORWARD_SHADOW (c)).** Rev 5 requires that "the traded-rung calibration leg passes" (absolute, `forecast_conditional_scoring.py:392`). The rung family fails that leg today (FC_0b), so FORWARD_SHADOW could never PASS whatever the ruling says. AUT-4 gates on the relative R-C non-inferiority test and reports the absolute leg. C4 should read "the calibration predicate the policy ruling registers".
- **Not new:** Rev 5 §5.x "every study sets `RuntimeMaxSec`" is wrong for oneshot units. This is already corrected in the Rev 6 directory copy (G32, `TimeoutStartSec`), and r3 applies it.

---

## §R3 Disposition (review `reviews/AUT-4-r2-merged.md` plus `reviews/ALPHA-decision.md`)

**14 FIXED, 0 REJECTED.** One sub-claim inside F4 (the survivorship direction) is not adopted as worded; the evidence is in the F4 row. No README criterion is changed.

The r2 dispositions E1–E22 (and W1/W7/W8/HOLDOUT) are in `AUT-4-evaluation_plan_r2.md` §R2. They stand unless an F row below supersedes them; E1 is superseded by F1/ALPHA, and the E4/E5 `RuntimeMaxSec` usage is superseded by F8.

| F | Disposition | Evidence / where |
|---|---|---|
| ALPHA decision | ADOPTED | §3.5: `k_life` lifetime and never reset; `mints_in_window` rate limiter; `K_LIFETIME_EFFECTIVE` nominal rule; §3.2 B cap and analytic tail; §3.5 window cap; §3.1a C4 fields. Each ARCH dependency is a hard prerequisite (§6.4 #4–9) |
| F1 | FIXED | §3.5/§3.8/R-F: `n_min_eff ≤ n_cap` in the record and in R-F; headline, §3.7 and §6.3 state that every FORWARD_SHADOW is INCONCLUSIVE by construction (n_min_eff ≥ 403 > n_cap 89 at 28 days, > 480 at 120 days with deff 1.5); B capped at 2¹⁹ ≥ ⌈200/α_6⌉ with the Hoeffding tail beyond it; effective horizon 6; W1 arithmetic is now Rev 5's 6 + (60 min + 150 s) + 0.5 = 7.54 ≤ 8 with 0.46 h slack (§3.9) |
| F2 | FIXED | §3.5: k_life assigned only at stage-1 nomination, sequentially under the studies flock, counted in the store including same-run nominees, written before the next assignment; recorded in stage-1 metrics; stage 2 and FS read it via `inputs[stage1_verdict]`; `test_two_pending_nominees_get_distinct_k` + 2 more (WP5) |
| F3 | FIXED | §6.4 #5 and #6: P4-10 and P4-11 are hard prerequisites. Rev 5 fallbacks in §3.6 (policy sha in the field, PREREG in `inputs`, `accepted_family_preregs`) and §3.1 (`recompute_key` no-op); `test_live_sequential_fail_accepted_and_demotes_with_policy_sha_field` proves that a FAIL DEMOTEs under the Rev 5 rule (WP4). Honest gap: there is no autonomy DEMOTE before any policy ruling |
| F4 | FIXED | §3.7(b): Bonferroni α_k/3 across LB_ev, the slippage UB and the Wilson p_fill LB; `N_IOC_MIN = 30`; three RED tests. **Direction sub-claim not adopted:** the estimator scores **all** shadow takes and multiplies by p_fill, so if misses are the favourable decisions then E[ev\|fill] < E[ev], and p_fill·E[ev_cond] overstates the realised EV, i.e. it is anti-conservative. The review's direction holds only for an estimator computed on filled decisions, which this is not. Instead of relying on either direction, r3 reports the Manski worst-case bound and adds `fill_selection_sensitive` for R-E to rule on |
| F5 | FIXED | §3.10 R-C: paired date-cluster bootstrap, one-sided at α_k, margins δ_C = 0.01 (ECE) and δ_M = 0.005 (\|MSD\|); `N_BUCKETS_MIN = 3` fail-closed; n_min_c (bucket occupancy ≥ 0.95 and power ≥ 0.80) enters n_min_eff; `calibration_ni.py`; WP2 tests |
| F6 | FIXED | §3.10 R-B: n_max from the take-count accrual simulation rule; MDE from data-free σ₀; loss stop from the H1 MC on tape asks; all in the design JSON with input shas. `prereg_precommit_check.py` (git committer time vs artefact birth time, with forced disclosure) and RED tests (WP7a). Its honest limit (it proves existence, not reads) is stated |
| F7 | FIXED | §6.1: coverage paths are (1) real, (2) drill child, (3) fixture candidate via a fixture-registry engine pass with its own journal directory; target stays 3 with the "machinery proven (drill/fixture), no real candidate" class stated |
| F8 | FIXED | §3.9: `TimeoutStartSec=6300` (= 7200 − 900, including the flock wait) → worst end 12:45 < 13:00 predecessor expiry; `RuntimeMaxSec` dropped (no effect on oneshot, verified in `man systemd.service`, systemd 259); `test_offline_successor_lands_before_predecessor_expiry`. No expiry exemption needed |
| F9 | FIXED | §3.4 condition 9 + §3.3: closure-keyed `fs_replay` paths; n counts current-closure days only; re-replay backlog after rotation; verdict-level `INCONCLUSIVE(mixed_closure)` breach guard; two RED tests (WP3) |
| F10 | FIXED | §3.1a: LIVE `n_min` = first-look n (10), `metrics.n_max` separate; §7 (c) restated as three store queries, with the loss-stop FAIL exempted from the n_min query |
| F11 | FIXED | §3.11: store `derived/autonomy/eval_runs/<producer_id>/<date>_<start_ns>.json`, plus the `ExecStopPost` `_stoppost.json` (`$SERVICE_RESULT`, cgroup `memory.peak`); §3.9: an ERROR verdict is never fresh; WP8 tests |
| F12 | FIXED | §3.12: deadline-based replay budget (3600 s wall at worst wait); launch rule; today-first then backlog (≤ 3 days); atomic per-output partial commit; `BACKLOG_EXPIRED`; three RED tests |
| F13 | FIXED | §3.12: `FS_REPLAY_CHILD_TIMEOUT_S = ⌊P·3600/(4·(K_max+1))⌋` (360 s at P = 2), named in `autonomy/budget.py` and derived (the r2 value had no code origin; checked with grep); `fs_replay` registered as a key of `PRODUCER_SOURCE_SHA256`; `test_aut4_producer_ids_registered_in_pins` |
| F14 | FIXED | §6.3: power at n = 160 is 0.22 / 0.69 / 0.80 / 0.96 at δ = 0.05 / 0.10 / 0.113 / 0.15, next to the reach-probability table; the joint ≈ 0.61 is stated; recorded in the feasibility record (`live_power_at_n_max_by_delta`) |
