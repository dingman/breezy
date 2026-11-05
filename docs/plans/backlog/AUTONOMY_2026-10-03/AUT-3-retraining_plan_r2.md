# AUT-3 — Retraining (refit pipeline): area plan

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-3 |
| Title | Retraining: scheduled, lineage-complete, leakage-guarded refits for every live composition kind, including one identifiable, de-risking-only model class that consumes the bot's own labelled outcomes |
| Round | **r2 (2026-10-03)**. r1 is kept unchanged at `AUT-3-retraining_plan_r1.md`. This round disposes R1–R16 of `reviews/AUT-3-r1-merged.md` (§R2). |
| ARCH consumed | `ARCH_rev4.md` (Rev 4), sha256 `175310117eec39b22fc8229788a7d6182c6395438db23ec65ceb78b964dd508e` (the sha scored in `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-r4-merged.md`), plus that review's W1–W16 as pending Rev 5 deltas. Holdout semantics: `reviews/HOLDOUT-decision.md`, consumed by the ruling name `RULING_holdout_freeze_and_forward_window_2026-10-03` (ARCH-owned; AUT-3 does not restate it). Repo HEAD `4b8347a6`. |
| Current score | 0 |
| Target | 3 |
| Upstream | ARCH-0 (`persistence/autonomy/`: schemas, C6 Protocols and registries, `pins.py`, the resolver as a read-only fold, the forward-window epoch function); AUT-1 (C1 `DecisionRecord`: `p_hat`, `p_lower`, `p_upper`, `side`, `rung_id`, `eval_ns`, `forecast_input_sha256`, `artefact_sha256`, `decision_id`); AUT-2 (C2 `label/v1`, `label_outcomes_ok_<date>` marker); AUT-5 (registry fold, MINT from C3, mint ceiling); AUT-6 (`deliver_with_proof`, the `refit_freshness` and `refit_repro` detectors) |
| Downstream | AUT-4 (consumes every C3 candidate and every `refit_run/v2` record); AUT-5 (MINT ∅→SHADOW from C3); AUT-7 (rollback re-verifies C3 bytes) |
| Planning only | Nothing here is implemented. No commit, stash, `uv`/`pip` or `systemctl` was used to write it. |

**Evidence tags.** `file:line` was checked at `4b8347a6` with codegraph (projectPath `/home/jon/breezy`) and read-only reads (`/usr/bin/grep` where `.venv` matters). **INFERRED** means not verified against running code; each such item is cleared by a named WP0 check before the slice that relies on it starts.

---

## 1. Goal state

**README score-3 criterion, verbatim (AUT-3):**
> - Scheduled, unattended refits produce versioned candidate artefacts for each family's model class. Each candidate records its lineage: data window hashes, code sha, parameters and seed.
> - Each refit runs on a rolling window of external weather data **plus** the bot's own labelled outcomes and execution data (fill, slippage and refusal), where the model class consumes them.
> - Leakage guards are asserted in code (`ref.ts < take.ts`; holdout bounds).
> - Refits are reproducible bit for bit from their lineage.
> - Each run has a stall watch and a memory cap.
> - The loader accepts every recalibration form the pipeline can emit, each covered by parity tests.

**README live proof, verbatim:**
> at least 7 consecutive scheduled refits, each producing a lineage-complete candidate that the evaluator (AUT-4) consumes automatically, with at least one candidate whose training set includes the bot's own labelled outcomes.

**ARCH Rev 4 §10 obligations for AUT-3, verbatim:**
> the refit cadence and windows; the mint path honouring `MAX_MINTS_PER_LINEAGE_PER_DAY`; the ablation and leakage assertions; the reproducibility sample; the G11 widening with parity tests; its unit's `MemoryMax`, `RuntimeMaxSec` and flock wait.

**ARCH Rev 4 C3 obligations, verbatim excerpts:** "`ablation_artefact_sha256` is the same refit with that set left out, and the writer refuses the lineage if it is non-null and equals `artefact_sha256`"; "**The C2-consuming model class** is `forecast_quantile_ladder:rung_recalibration`, fitted on C2 `(p_at_decision, settled_outcome)`; it needs the G11 loader widening with parity tests. `forecast_quantile_ladder:density_table` consumes external weather only." C4 Y13: "The k-th candidate evaluated in a lineage against an overlapping forward window is tested at α_k = α_total·2^−k. At most `K_max` candidates per lineage per forward window may be evaluated, and at most one MINT per lineage per day."

**How the live proof is counted (R6; amendment drafted in R14's ruling, §3.10).** Under ARCH Y13 a run that mints every day spends AUT-4's α budget on near-duplicates, so this plan counts **7 consecutive scheduled refit runs, each lineage-complete and consumed by AUT-4**, where the run outcome is one of `CANDIDATE`, `NO_CHANGE(below_delta)`, `NOT_FITTABLE(<reason>)` or `MINT_REFUSED_CEILING`, every outcome recorded in `refit_run/v2` and acknowledged by AUT-4, **with at least one minted `rung_recalibration` candidate whose training set includes own labels and which meets the X22 thresholds (§3.4)**. The 7 runs share most of their training data and are **not independent samples**: they prove the machinery runs reliably, not seven replications of a result. WP9 also reports the strict README count (`STREAK_CANDIDATES`). Score 3 is claimed on the run count only after the README-alignment ruling (§3.10) is reviewed SOUND. Until then the strict count is the claim (§6).

Where this plan reaches each line is mapped in §7.

---

## 2. L-1 null hypothesis and reuse

| New component | Nautilus or Breezy capability checked | Verdict |
|---|---|---|
| Offline refit scheduler | Nautilus has no artefact registry, refit or scheduled job (`WORK_BREAKDOWN:288`; ARCH §2 L-1). systemd timers are the repo convention (`deploy/systemd/breezy-nbp-learning-nightly.timer`). | BUILD one notify-type unit. No in-node fitting: the node keeps loading sha-pinned bytes only (`fq/config.py:90-96`, "There is no live refitting", stays true). |
| EMOS refit (`density_table`) | `fit_calibration` (`analysis/nbp_calibration.py:1280-1334`), `fit_hierarchical_emos` (`:1166-1253`), seeded `bootstrap_emos_draws` (`:1070-1153`, `BOOTSTRAP_SEED` `:451`), `artefact_from_calibration_fit` (`:2550-2632`), `artefact_json`/`artefact_sha256`/`write_artefact` (`:2635-2665`); row join `build_version_rows` (`scripts/analysis/nbp_skill_study.py:661`); `Splits`/`split_for_date` (`nbp_calibration.py:248-270`), `DEFAULT_SPLITS` (`:273-278`). | REUSE unchanged. AUT-3 adds only window selection and split tagging. |
| Recalibration form and application | `ProbabilityRecalibrationForm` (`:1508-1511`); `_apply_recalibration_scalar` (`:1560-1577`: `clip(intercept + slope·p)`); `apply_probability_recalibration` (`:1647-1662`: per-rung scalar map, then divide by the total, then assert the sum is 1); artefact fields `recalibration_affine` (`:2381-2382`, `:2438-2445`, `:2531-2537`). | REUSE the `affine` form and both functions. **Identifiability finding (R2).** Rung partitions sum to 1 (`quantile_density.py:386-388`). So for slope b > 0 with no clipping, `(a + b·p_i)/Σ_j(a + b·p_j) = (c + p_i)/(1 + K·c)` with `c = a/b` and K = the rung count. The map depends on (a, b) only through c: `(λa, λb)` emit identical probabilities, and every `(0, b)` is the identity. The 2-parameter `_fit_affine` (`:1535-1544`) is therefore unidentified after renormalisation, and r1's scalar-grid X22 probe would have accepted an identity map. The emitted form is pinned to **slope = 1 exactly, intercept c** (§3.4). |
| Recalibration estimator | `_fit_affine` is unweighted OLS with no penalty; `minimize_scalar(method="bounded")` is already used deterministically (`nbp_calibration.py:840`). | ADD one 1-D penalised estimator that reuses `apply_probability_recalibration` inside its objective, so renormalisation is part of the fit (R2). No new form. |
| Base partitions for own labels | `rung_probability_interval` (`strategy/ladder_ev/quantile_density.py:392-442`) gives `(p_point, p_lower, p_upper)` from the forecast `Percentiles` and the artefact draws. `ArtefactBoundsProvider` (`fq/artefact_bounds.py:38-60`) returns `p_hat` = the per-draw **mean** of the YES-rung probability. The FQ gate uses only `p_lower` (YES) and `1 − p_upper` (NO) (`fq/decision.py:331,349`; `ladder_ev/scoring.py:59-82`). The quantity is the literal `QTY = 1` (`fq/decision.py:73`). | REUSE to **recompute** each label's full per-draw partition, and verify it against the captured C1 `p_hat` (§3.4). Nothing is substituted: a mismatch excludes the label by name. |
| Live recalibration application | `LiveCalibration` (`fq/calibration_artefact.py:118-172`) refuses any `recalibration` other than `none` (`:68`, `:281-287`). | WIDEN (L-12): the accepted set becomes exactly the emit set `{none, affine(slope=1, |c| ≤ C_BOX)}`. Add a strategy-layer `RungRecalibration` applied per draw, plus the **parent envelope** (§3.8), which makes every accepted map de-risking on both legs. |
| Candidate store | G13 candidate root guard `_resolve_candidate_root` (`scripts/analysis/nbp_learning_nightly.py:708-719`); ARCH C3 content-addressed layout. | GENERALISE to `derived/artefacts/<model_class>/<sha>/` and keep the out-of-repo refusal. |
| Lineage schema, epoch, counters | ARCH-0 `persistence/autonomy/` (C3 `lineage/v1`; `lineage_counters`; the forward-window epoch from W7). | CONSUME. AUT-3 owns only the C3 writer and `refit_run/v2`. It never computes an epoch or charges α. |
| Plug-in dispatch | C6 `Refitter` plus `OFFLINE_PLUGINS` keyed by `CompositionKind` (`family_manifest.py:115-121`). | IMPLEMENT `FqRefitter`. `RefusingPlugin` stays for the three non-live kinds. |
| Studies lock, slice, failure notifier | `breezy-studies.slice` (12G/16G), `breezy-study-failed@.service`, `breezy-studies.lock` (`deploy/systemd/replay-daily-run.sh:101`, `station-candidate-register-run.sh:44-47`). | REUSE. The flock is taken in Python so the watchdog keeps pinging during the wait. |
| Stall watch and runtime bound | No unit uses `RuntimeMaxSec` or `WatchdogSec` (G29; `/usr/bin/grep` for `WATCHDOG=1`/`NOTIFY_SOCKET` in `src scripts deploy`: 0 hits). `man systemd.service`: "`RuntimeMaxSec=` … does not have any effect on Type=oneshot services … (use TimeoutStartSec= to limit their activation)". | BUILD `Type=notify` with `WatchdogSec`. After `READY=1` the unit is active, so `RuntimeMaxSec` applies. Before READY, `TimeoutStartSec` applies. stdlib `NOTIFY_SOCKET`, no new dependency (R13). |
| Alert delivery | `emit_alert` swallows failures (G25). `deliver_with_proof` (ARCH §4.6) is owned by AUT-6. | CONSUME for every CRITICAL. |
| P_HOLD (CRH) refit | `P_HOLD_LOWER/UPPER` are code constants (`strategy/current_rung_hold/archive_table.py:37-41`). Every CRH kind is RETIRED and carries `RefusingPlugin` (ARCH C5/C6). | NOT IN SCOPE, stated. `refit_run` records `NOT_FITTABLE(refusing_plugin)`. |
| Execution-data refit | No FQ component takes fill, slippage or refusal as an input. Operator ruling 09-29 (memory `prediction-from-weather-venues-for-cost`): venue prices are execution cost only. WP-23 uses the ask as a predictor (`WORK_BREAKDOWN:481`). | NOT BUILT. A README amendment is drafted (R14, §3.10). Execution data enters AUT-4's EV-net-of-cost evaluation, never a refit. |

---

## 3. Design

### 3.1 Model classes for `forecast_quantile_ladder` (the only kind in `LIVE_GATE_ROUTED_KINDS`, G19)

One FQ artefact is one `NbpCalibrationArtefact` JSON (`nbp_calibration.py:2355-2453`). The champion is `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`, sha `9c0b6d6e…923a5e`, with `recalibration=none`, `correction_form=linear_lst_day_length`, versions v4.0–v5.0 and 200 draws. A child may differ from its root only in `density_artefact_path/sha` (ARCH §4.2), so every candidate is a complete artefact.

| `model_class` | What changes vs the parent | Inputs | Own outcomes |
|---|---|---|---|
| `forecast_quantile_ladder:density_table` | v5.0 `(a, γ)`, its draws, κ (LOVO) and per-draw δ. v4.x rows are fixed. Correction form and coefficients are carried. `recalibration=none`. | External only: `derived/nbp` (`KLAX KMDW KMIA KSFO`) ⨝ `settlement-truth/settlement_truth.parquet` FINAL rows | `own_outcome_label_set_sha256 = null` |
| `forecast_quantile_ladder:rung_recalibration` | Only `recalibration="affine"` and `recalibration_affine=(c, 1.0)`. Every other field is byte-equal to the parent (asserted). | C2 labels, oriented and verified (§3.4) | non-null; ablation and the X22 thresholds required |

**Naming note.** `density_table` here means the NBP EMOS calibration artefact, not `strategy/ladder_ev/density_table.py` (the RETIRED `forecast_ladder` kind). It is a contract literal.

### 3.2 `rung_recalibration`: hypothesis, mechanism, competing evidence (R2, R10)

- **Hypothesis H-R (not a claim).** On rungs the gate *selects* (YES where `p_lower − ask − fee > margin`; NO where `(1 − p_upper) − no_ask − fee > margin`, `fq/decision.py:17-18,349`), the realised win rate of the bought leg differs from the forecast's probability. A one-parameter partition map fitted on those selected outcomes estimates that selection-conditioned miscalibration.
- **Mechanism.** The 09-20 terminal finding: market resolution is 1.98× the forecast's (memory `forecast-edge-closed-pmus-rungs`). Selecting where the forecast disagrees most with a better-resolving market concentrates forecast errors in the selected set (winner's curse). This is the same train/serve population skew as memory `archive-table-train-serve-skew`.
- **Competing evidence, stated.** (1) The traded-rung calibration leg was **under-confident**, not over-confident (memory `bss-headline-is-the-wrong-family`), which predicts c < 0 (sharpen), not shrinkage. The estimator is therefore sign-free within a ruling box, and the de-risking guarantee comes from the envelope, not from the sign (§3.8). (2) A LOSO Platt fit made the mid **worse** (memory `forecast-edge-closed-pmus-rungs`). (3) The pinned nightly's latest `bss_vs_m1 = −0.0399`.
- **Effect under the envelope.** The gate's bounds can only become more conservative on both legs, so a candidate can only **remove** takes, never add one. The quantity is the literal 1 (`fq/decision.py:73`), so "smaller positions" in r1 was wrong and is withdrawn. "Fewer takes" is a consequence of the envelope, not evidence of learning.
- **Evidence class: machinery proven, edge unproven (R10).** A recalibration adds no resolution and cannot reopen the closed edge. **A recalibration candidate is expected to show no edge.** AUT-4's FORWARD_SHADOW verdict on it is expected to be `UNDERPOWERED` before the 2027-01-25 KILL. The NBP PM.us confirmatory leg is infeasible (`RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md`).
- **Rejected alternative:** fitting on all C1 decisions ⨝ settlement (refusals included). That carries the same information as the external rows `density_table` already uses, and it is not the selected population.

### 3.3 Windows, holdout and cadence

**Holdout (R5; `HOLDOUT-decision.md` adopted verbatim by reference).** The archive holdout is frozen at **[2026-07-01, 2026-10-02)**, sealed for one final confirmatory use only. That use is AUT-4's, never AUT-3's. Days ≥ 2026-10-02 are forward data, and AUT-3 trains only on days before each forward evaluation window. AUT-3 consumes `RULING_holdout_freeze_and_forward_window_2026-10-03` by name. `windows.py` holds `SEALED_HOLDOUT_START = 2026-07-01` and `SEALED_HOLDOUT_END_EXCLUSIVE = 2026-10-02` as `Final` literals, and a test asserts they equal the bounds in that ruling's machine block (the block tag is the one ARCH defines). The r1 AUT-3 freeze ruling and its Option B are **withdrawn**. Until the ARCH ruling is filed, WP1's pin test is RED and no post-06-30 row is eligible.
- **`holdout_opens`.** AUT-3 never opens the sealed holdout and never calls `open_holdout` (`nbp_calibration.py:353`). An AST test enforces it. Refits leave `lineage_counters.holdout_opens` untouched.
- **α.** AUT-3 charges no α and assigns no k. Every C3 it writes may become an AUT-4 candidate at α_k = α_total·2^−k (ARCH C4 Y13), which is why minting is delta-gated (below).
- **No fresh weather holdout for `density_table` (R9).** After the freeze, the sealed set's one use is the root's confirmatory S2. No sealed weather data remains to confirm a refit `density_table` candidate. Its only confirmation is AUT-4's forward evaluation on days ≥ `forward_eval_start_utc` (forward shadow). The same text goes into the README-alignment ruling (§3.10).

**`RefitWindow` for a run on UTC day D** (`analysis/autonomy_refit/windows.py::compute_refit_window`):
- `train_end_exclusive_utc = D 00:00Z`. Only FINAL CLI rows with `issued_at_utc < train_end` and NBP rows with `available_at_ns < train_end` are eligible.
- `forward_eval_start_utc = (D+1) 00:00Z`, which is ≥ `created_at`.
- density_table: v4.x rows on their `DEFAULT_SPLITS` train/validate days (unchanged). v5.0 rows on `v5_fit_slice` (2026-05-04..06-30) **∪** forward days `[max(2026-10-02, train_end − ROLLING_V5_DAYS), train_end)`. A sealed day is never eligible.
- rung_recalibration: C2 labels admitted by §3.4, with settlement `climate_day ≥ 2026-10-02` and `labelled_at_ns < train_end`, from label files covered by a `label_outcomes_ok_<date>` marker (AUT-2 §5).

**The seasonal gap (R7).** v5.0 trains on May–June plus forward days from October, with July–September sealed, so the fit has no summer-to-autumn transition rows. WP0 item (vii) measures the effect on pre-holdout v4.3 rows only (no sealed contact):
- Fit A = v4.3 rows `[2025-05-27, 2025-06-30] ∪ [2025-10-02, 2025-10-02 + F)`.
- Fit B = contiguous `[2025-05-27, 2025-10-02 + F)`.
- Score both on `[2025-10-02 + F, +28 d)`, for F ∈ {14, 28, 56}.
- Report ΔCRPS, Δ rung Brier (station-day cluster bootstrap, `roi_bound.SEED`) and the `(a, γ)` shift.

The AUT-3 policy ruling (§3.10) states whether the gap is accepted, under a pre-declared rule: accepted iff the upper 95% bound of ΔCRPS(A − B) at F = 28 is ≤ `SEASONAL_GAP_MAX_DCRPS`, proposed 0.02 °F. If it is not accepted, density_table refits wait until F days of forward data exist (`MIN_FORWARD_DAYS_FOR_DENSITY`), and rung_recalibration, which uses own labels only, is unaffected.

**Cadence, delta gate and ceilings (R6).** One run a day at 06:00Z. Per lineage:
1. **Ordering.** The component whose last C3 is older goes first; a tie goes to `rung_recalibration`.
2. **Fit and gate.** The component is fitted. Its candidate qualifies only if it passes every writer check **and** `functional_delta(candidate, last C3 of the same model_class or the parent) ≥ MIN_MINT_DELTA`. That delta is the max |Δp_hat| over the frozen per-model-class probe set (§3.4 for rung_recal; for density_table, the rung partitions of the last 28 forward station-days' NBP rows). If the delta is too small, the component's status is `NO_CHANGE(below_delta)`.
3. **One C3 a day.** The first qualifying candidate is written, and the other component is not fitted that day (`DEFERRED_DAILY_CEILING`). This is how AUT-3 honours `MAX_MINTS_PER_LINEAGE_PER_DAY ≤ 1`, and the engine enforces the same ceiling.
4. **K_max (W7).** AUT-3 does **not** stop writing C3 at K_max. It picks W7's first option: a candidate past K_max is **consumed and counted, with no α spent**, matching AUT-4 r1's `INCONCLUSIVE(K_MAX_EXHAUSTED)` (AUT-4 r1 §3.5). The delta gate is AUT-3's lever on candidate flow. ARCH Rev 5 must make W7's choice binding; see contradiction C-3, §8.
5. **Mint refusal.** If the engine refuses the MINT for a written C3 (the daily mint ceiling, for example when the AUT-7b drill child minted that day), the next run reads the fold and records `MINT_REFUSED_CEILING` for that C3 in `refit_run/v2.prior_mint_status[]`. It counts as a recorded, consumed run (§6).
6. **Run outcomes.** The run's per-lineage outcome is `CANDIDATE`, `NO_CHANGE(below_delta)`, `NOT_FITTABLE(<reason>)`, `MINT_REFUSED_CEILING`, `SKIPPED_LOCK` or `FAILED`. Only the last two break the streak.

### 3.4 Estimators

**density_table** (`fq_density_refitter.py::FqDensityTableRefitter`):
- Rows come from `rolling_version_rows(...)`, which delegates to `nbp_skill_study.build_version_rows` (`:661`). How tagging coexists with `Splits` validation is **INFERRED**: `split_for_date` raises outside declared splits (`nbp_calibration.py:270`), and the v5 slice must end before `holdout_start` (`:255-259`). WP0 (i) picks either a `Splits` instance with `holdout_start = train_end` and pre-filtered rows, or a post-build `dataclasses.replace(row, split="v5_fit_slice")`.
- Then `fit_calibration(rows, method=CdfMethod(parent.cdf_method), bootstrap_seed=BOOTSTRAP_SEED)`, followed by `artefact_from_calibration_fit` with the parent's `CorrectionSelection`. `recalibration=none`. `n_min`/`sigma_d` are carried.
- **Fit rows are asserted, not just snapshotted (R11).** The exact row tuple passed to `fit_calibration` is the object handed to the leakage functions and the object serialised to the snapshot, so `fit_input_sha256 == data_windows[nbp_derived].content_sha256` by construction.
- **Contingency** (WP0 decides it, the ruling records it): if the full-fit p95 runtime is > 90 min or the peak RSS is > 12 GiB, use the v5.0-only conditional refit (`fit_version_unshrunk`, shrunk toward the frozen LOVO pooled mean at the parent's κ, parent δ kept).

**rung_recalibration** (`fq_rung_recal_refitter.py::FqRungRecalibrationRefitter`):

*(a) Label admission and orientation (R4).*
- **Admitted:** `admissible ∧ reconciled ∧ source=live ∧ ¬drill`, `role == "entry"` (**exit labels are excluded**, reason `exit_label`), non-null `p_at_decision` and `decision_id`.
- **Orientation.** C2 is bought-leg oriented: `settled_outcome` = the bought leg wins (ARCH C2; AUT-2 r1 table at line 148), and `p_at_decision` is the bought-leg probability as the merged review pins it. The map acts on the **YES-rung partition** (`apply_probability_recalibration` maps rung probabilities), so each label is converted into that domain: `leg=yes` gives `(p_yes, y_yes) = (p_at_decision, settled_outcome)`; `leg=no` gives `(1 − p_at_decision, 1 − settled_outcome)`.
- **Assertion `label_orientation_matches_capture`.** `p_yes` must equal the joined C1 `DecisionRecord.p_hat` (the YES-rung mean, `artefact_bounds.py:60`; `fq/decision.py:331,366`) within `P_REPRO_ABS_TOL = 1e-12`. A mismatch (for example AUT-2 writing YES-oriented `p_at_decision` on a NO fill; contradiction C-1, §8) **fails the run**: CRITICAL, no write.

*(b) Fitted statistic (R4).* The statistic fitted and evaluated is **`p_hat`**: the mean over the 200 draws of the per-draw rung probability, which is exactly what C1 captures. Under a candidate map g_c, the training prediction for a label is the live statistic `p̂_c = mean_d( apply_probability_recalibration(g_c, partition_d)[rung] )`, so fitting applies the map **per draw, then averages**, exactly as the live path does (§3.8). `p_lower`/`p_upper` under g_c are computed as diagnostics and enveloped (§3.8). They are never fitted.

*(c) Base partitions (recomputed, verified, never substituted).* For each admitted label the refitter recomputes the label's per-draw base partitions from:
- the deciding artefact's EMOS draws, ignoring its `recalibration` fields;
- the forecast `Percentiles` of the NBP cycle visible at `eval_ns`, whose digest must equal C1 `forecast_input_sha256`;
- the ladder of the label's `(station, climate_day)`.

It then recomputes the deciding artefact's own `p_hat` (with that artefact's recalibration, if any) and requires it to equal C1 `p_hat` within `P_REPRO_ABS_TOL`. A label that fails is excluded by name (`p_unreproducible`), with a WARN, and becomes a CRITICAL if more than 10% of labels fail. **INFERRED:** the forecast vector can be retrieved by digest. WP0 (viii) proves it on the 10-02/10-03 fills. **Fallback:** a C1 extension `rung_partition_p_hat` on `Take`/`TrySubmit` (ARCH feedback, §8 C-6). Without either, rung_recalibration is `NOT_FITTABLE(partition_unavailable)` and the own-outcome leg is reported as score 2.

*(d) Parent binding (R15 resolved, not just stated).* The fit's base is the parent artefact P's EMOS block. A label is admitted only if its deciding artefact's EMOS block is byte-equal to P's (reason `label_from_other_emos`). A rung_recalibration child keeps its root's EMOS block byte-equal (`parent_bytes_preserved`), so labels decided under an already recalibrated champion **remain usable**: their base partitions come from the shared EMOS draws, not from the post-recalibration `p_at_decision`. That removes r1's `NOT_FITTABLE(parent_recalibrated)` stop. A recalibration candidate's parent is always the EMOS-bearing artefact with its recalibration replaced, never stacked. **Remaining known limit:** after a `density_table` promotion, labels from the older EMOS are excluded, because their selection population differs. That is a stated limit.

*(e) Estimator `fit_partition_shift` (R2).*
- **Form:** `ProbabilityRecalibrationSelection(form=AFFINE, affine=(c, 1.0))`, with one parameter c ∈ [−C_BOX, C_BOX].
- **Objective:** `J(c) = Σ_k w_k·(p̂_c,k − y_yes,k)² / n_eff + (N0/n_eff)·R(c)`.
  - Cluster weights (L-40): each `(station, climate_day)` has total weight 1, split equally across its labels, so `n_eff` = the cluster count.
  - `R(c)` = the mean over the probe set (below) of `Σ_rungs (apply_probability_recalibration(g_c, π) − π)²`. This is the ridge penalty on the function-space deviation that R2 asked for.
- **Solver:** `scipy.optimize.minimize_scalar(J, bounds=(−C_BOX, C_BOX), method="bounded", options={"xatol": 1e-9})`. It is deterministic given its inputs, as at `nbp_calibration.py:840`. **The estimator clamps into the box**, so the writer never refuses an estimator output on the box (R3). `clamped` is recorded in `params`.
- **Canonical identity.** `|c| < C_IDENTITY_EPS = 1e-12` is written as `recalibration="none"`, `recalibration_affine=None`.

*(f) Support checks (R2).* If any check fails the result is `NOT_FITTABLE(unidentified)`:
- `n_eff ≥ MIN_NEFF_TO_EMIT`, proposed 30 station-days;
- `distinct_stations ≥ 2`;
- the inter-quartile range of `p_yes` over labels is ≥ `MIN_P_SPREAD`, proposed 0.10;
- labels come from ≥ 2 distinct ladder sizes K **or** ≥ 3 distinct rung positions, because c is identified through renormalisation across the partition.

*(g) Off-support gate (R2).* Let S = [min `p_yes`, max `p_yes`] over training labels. Over the probe set, `off_support_max_delta` = max |Δp_hat| on rungs whose base p lies outside S. It must be ≤ `MAX_OFF_SUPPORT_DELTA`, proposed 0.02, else `NOT_FITTABLE(off_support)`. The writer recomputes this.

*(h) Probe set and X22 (R1).*
- **Probe set** = the base `p_hat` partition (the mean over draws, the full ladder) of every distinct training decision. These are real rung partitions, frozen into the snapshot.
- `probe_max_delta` = max over probe partitions π and rungs of `|apply_probability_recalibration(g_c, π) − π|`, including the renormalisation at `nbp_calibration.py:1655-1658`.
- **X22 passes only if** `artefact_sha256 ≠ ablation_artefact_sha256` **and** `probe_max_delta ≥ MIN_PROBE_DELTA` (proposed 1e-3) **and** `n_eff ≥ MIN_NEFF_TO_EMIT`.
- Below either threshold the result is **`NOT_FITTABLE(underpowered)`**, which is **not** an own-outcome candidate for the live proof (WP9 requires the thresholds).
- **Ablation:** the same refit with the label set left out gives an empty data term, so J = the penalty, minimised at c = 0, which canonicalises to `none`. The ablation bytes therefore equal P's bytes with `recalibration=none`, and `ablation_artefact_sha256` is that sha.

*(i) Time-blocked own-label holdout (R8, advisory).* The refitter also fits on labels with `climate_day ≤ D − 1 − OWN_LABEL_HOLDOUT_DAYS` (proposed 7) and scores the last 7 days' labels. It records `params.advisory_time_block = {k, n_eff_train, n_eff_test, brier_recal, brier_parent, brier_diff}`. This is **advisory only**: it never gates a write and never feeds an AUT-4 verdict. The emitted candidate uses all admitted labels.

*(j) Inputs read.* Exactly `(decision_id, leg, role, p_at_decision, settled_outcome, station, climate_day, label_id, label_seq, admissible, reconciled, source, drill, labelled_at_ns)` plus C1 `(p_hat, eval_ns, forecast_input_sha256, artefact_sha256, rung_id, side)`. No ask, fill price, fee or slippage is read (AST test).

### 3.5 Lineage, inputs snapshot and leakage assertions

**Inputs snapshot** (`inputs.py::snapshot_rows`).
- Each source's fit rows are serialised canonically: explicit columns, a sort key, parquet with fixed writer options.
- Files go to `~/.local/share/breezy/derived/refit/inputs/<content_sha256>.parquet` (0444, dir 0500).
- Snapshots are **segmented** so that unchanged segments dedupe by content address: `nbp_v4_fixed` (identical across runs), `nbp_v5_slice`, `nbp_v5_forward`, `settlement_truth`, `c2_labels`, `c1_decisions`, `probe_partitions`.
- `data_windows[]` has one entry per segment. Reproduction reads snapshots only.

**C3 `lineage/v1` fields filled by AUT-3** (schema unchanged):
- `model_class`, `lineage_root_family_id`, `parent_artefact_sha256`;
- `code_git_sha`, `build_sha`, `producer_code_sha` (closure hash for `aut3_refit`, §8 C-8);
- `params`: `{component, cdf_method, seed, bootstrap_draws, rolling_v5_days, n0, c, clamped, n_eff, n_labels, probe_max_delta, off_support_max_delta, mint_delta, advisory_time_block, numpy, scipy, pyarrow, python, uv_lock_sha256, cpu_model, openblas_coretype, thread_env}`;
- `seed`, `fit_status="OK"`, `data_windows`, `own_outcome_label_set_sha256`, `ablation_artefact_sha256`, `train_end_exclusive_utc`, `forward_eval_start_utc`, `leakage_assertions`, `recalibration`, `correction_form`, `created_at_ns`, `runtime_s`, `peak_rss_bytes`.

**`leakage_assertions`** (`leakage.py`). Any `passed=false` means no write, a CRITICAL through `deliver_with_proof`, and exit 2.

| Name | Asserts |
|---|---|
| `ref_ts_lt_take_ts` | density_table: every fit row's NBP `available_at_ns` < the D+1 decision cutoff of its climate day. rung_recal: every label's C1 `eval_ns` < its fill `ts` < the settlement issuance, and the forecast cycle's `available_at_ns` ≤ `eval_ns`. |
| `train_end_lt_forward_eval_start` | `train_end ≤ forward_eval_start` and `forward_eval_start ≥ created_at` |
| `no_sealed_holdout_rows_in_train` | **on the exact row tuple passed to the fitter** (R11), never on the snapshot alone: no `(station, climate_day)` in [2026-07-01, 2026-10-02) |
| `labels_settled_before_train_end` | every row's FINAL issuance < `train_end` |
| `label_orientation_matches_capture` | §3.4(a) |
| `labels_bound_to_parent_emos` | every training label's deciding EMOS block equals the parent's |
| `admissible_entry_only` | `admissible ∧ reconciled ∧ source=live ∧ ¬drill ∧ role=entry` |
| `parent_bytes_preserved` | rung_recal: every non-recalibration field is byte-equal to the parent |
| `own_outcome_x22` | §3.4(h): the sha differs **and** `probe_max_delta ≥ MIN_PROBE_DELTA` **and** `n_eff ≥ MIN_NEFF_TO_EMIT` |
| `envelope_never_more_confident` | over the probe set, the enveloped `p_lower` is ≤ the parent's and the enveloped `p_upper` is ≥ the parent's, for every rung (R3; a regression guard on §3.8) |

### 3.6 C3 writer and store (`c3_writer.py::write_candidate`)

- Atomic `mkstemp` + `os.replace` into `derived/artefacts/<model_class>/<sha>/{artefact.json, lineage.json}`; files 0444, directory 0500; `O_NOFOLLOW` on every path component.
- **Refuses:**
  - `fit_status ≠ OK`, or any failed assertion;
  - `ablation == artefact` when own outcomes are used;
  - `recalibration ∉ REFIT_EMITTABLE_RECALIBRATION_FORMS`, or `affine` with slope ≠ 1.0 or |c| > C_BOX (R3; the same predicate the loader uses, imported from one module);
  - the writer **recomputes** `probe_max_delta`, `off_support_max_delta` and the envelope check from the candidate bytes and the probe snapshot, and refuses on disagreement with the lineage or on a threshold miss, so it never trusts the refitter;
  - `correction_form ∉ _SUPPORTED_CORRECTION_FORMS`;
  - a second C3 for the same lineage on the same UTC day;
  - any root inside the repo or `deploy/families` (the G13 logic).
- **No new lineage for an existing sha** (C3 Y2): the status is `NO_CHANGE(existing_sha)`.
- The artefact bytes come from `artefact_json`, so `sha256(artefact.json) == artefact_sha256`.

### 3.7 Driver, units, stall watch, reproducibility

**Plug-in.** `analysis/autonomy_refit/plugin.py::FqRefitter` implements C6 `Refitter.refit(windows) -> (artefact, Lineage) | NOT_FITTABLE(reason)`, registered in `OFFLINE_PLUGINS[forecast_quantile_ladder]`.

**Driver** (`driver.py::run_daily(now, registry_reader, c1_reader, c2_reader, plugins, sink)`):
1. **Producer pin.** It computes its producer closure hash and refuses unless that hash is in `PRODUCER_SOURCE_SHA256["aut3_refit"]` (CRITICAL, exit 3).
2. **Clean tree (R12).** `git -C <tree> status --porcelain -- <closure files>` must be empty, and `git rev-parse HEAD` is recorded. A dirty closure gives a CRITICAL and exit 3, because `git archive <code_git_sha>` must reproduce the closure.
3. **Fold.** It reads the verified per-venue fold read-only, and for every champion (or the last RETIRED champion after a KILL, ARCH §5.3) and every allowlisted lineage root, resolves the plug-in.
4. **Fit and write.** It applies §3.3's ordering and gates, writes at most one C3 per lineage, writes `evidence/refit/refit_run_<YYYY-MM-DD>.json`, and logs `REFIT_RESULT lineage=<id> model_class=<mc> status=<…> reason=<r|-> artefact_sha256=<sha|-> n_eff=<k> probe_max_delta=<x|->`.
- **Failure handling.** An unreadable registry is CRITICAL with no refit. An unreadable C2 makes rung_recal `NOT_FITTABLE(c2_unreadable)` with a CRITICAL, and density still runs. "Nothing to do" exits 0 with `NO_INPUT`.

**`refit_run/v2`** (non-C evidence record; §8 C-8):
- Fields: `schema`, `run_date`, `started_at_ns`, `finished_at_ns`, `producer_code_sha`, `code_git_sha`, `results[]`, `prior_mint_status[]` (`{artefact_sha256, minted|MINT_REFUSED_CEILING|pending}`), `peak_rss_bytes`, `snapshot_bytes_written`, `drill`.
- Each `results[]` entry: `{lineage_root_family_id, composition_kind, model_class|null, status, reason|null, artefact_sha256|null, data_windows[], params, seed}`. Every outcome, including NO_CHANGE and NOT_FITTABLE, carries the window hashes, parameters and seed, so **every run is lineage-complete**.
- The record is exact-set, atomic, 0444, with no paths or env values.

**CLI entry points (thin):** `scripts/analysis/autonomy_refit_daily.py`, `scripts/analysis/autonomy_refit_reproduce.py`. Interpreter `/home/jon/breezy/.venv/bin/python`.

**Shared environment (R12).** Both units and every drill carry:
`Environment=OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONHASHSEED=0 OPENBLAS_CORETYPE=<WP0 value>`. `OPENBLAS_CORETYPE` is pinned to a kernel valid on the host CPU (`lscpu`: Intel i7-11700K). WP0 (iv) confirms the value and that the sha is identical with and without it. `params.cpu_model` records `/proc/cpuinfo` "model name". A repro on a different `cpu_model` is classified `REPRO_ENV_CHANGED`, never a pass.

**Units** in `deploy/systemd/`:

`breezy-autonomy-refit.service`:
- `Type=notify`, `NotifyAccess=main`, `WatchdogSec=1200`, `TimeoutStartSec=120` (bounds the pre-READY phase).
- `RuntimeMaxSec=12600`. It is effective because a notify unit is *active* after READY; it does not apply to oneshot units (R13).
- `Slice=breezy-studies.slice`, `OnFailure=breezy-study-failed@%n.service`.
- `MemoryHigh`/`MemoryMax` = `max(4G, 1.5 × WP0 peak)` ≤ 16G (provisional 3G/4G).
- The shared environment above, `EnvironmentFile=-%h/.config/breezy/alerts.env` only, `UMask=0077`.

`breezy-autonomy-refit.timer`: `OnCalendar=*-*-* 06:00:00 UTC`, `Persistent=true`, `AccuracySec=1min`. 06:00 + 30 min lock wait + 3 h ends ≤ 09:30Z: after AUT-6's 05:30 producer (ends ≤ 06:00) and before AUT-4's 11:00Z offline slot.

`breezy-autonomy-refit-reproduce.{service,timer}` (**moved after the AUT-4 slots**, R13):
- `OnCalendar=*-*-* 18:00:00 UTC`. That is after AUT-4 offline (11:00, ends ≤ 15:30Z), eval-live (14:45, ends ≤ 15:20Z) and the AUT-6 post-LAUNCH timers (17:12–17:40Z). It is outside [16:30Z, 17:10Z).
- Lock wait 1800 s; `RuntimeMaxSec=21600`, so it ends ≤ 00:30Z, before the 01:00–04:30Z heavy blackout.
- Same shape and environment as the refit unit; `MemoryMax` = the refit's.

**Lock and memory table (R13).** Every value is measured in WP0 before WP7 merges, and WP7's GREEN requires it.

| Unit | Slot (UTC) | Lock | Provisional MemoryMax | Measured peak | Bound |
|---|---|---|---|---|---|
| `breezy-autonomy-refit` | 06:00 | `breezy-studies.lock` (Python flock, wait 1800 s) | 4G | WP0 (ii) | `RuntimeMaxSec=12600` + `WatchdogSec` |
| `breezy-autonomy-refit-reproduce` | 18:00 | `breezy-studies.lock` (wait 1800 s) | = refit | WP0 (ii) (same fit) | `RuntimeMaxSec=21600` + `WatchdogSec` |
| drill runs (`systemd-run --user`) | ad hoc, outside 01:00–04:30Z | `breezy-studies.lock` | 4G | — | `-p RuntimeMaxSec` |
| WP0 benchmark | ad hoc | `breezy-studies.lock` | 16G cap | measured | `-p RuntimeMaxSec=14400` |

**Gate (R13).** WP7 does not merge unless the measured peak × 1.5 ≤ 16G **and** the measured p95 runtime + 1800 s ≤ `RuntimeMaxSec`. Otherwise the contingency estimator (§3.4) is adopted first.

**Stall watch.** The process sends `READY=1`, then takes the lock with a polled `fcntl.flock` for up to 1800 s while pinging `WATCHDOG=1`. A lock timeout gives `SKIPPED_LOCK` with a WARN, which becomes CRITICAL on the second consecutive day. During the fit it pings at every stage boundary and every 10 draws, and logs `REFIT_PROGRESS stage=<s> draws=<k>/<B> rss_mb=<m>`. Watchdog expiry kills the unit (no-progress event), and `OnFailure` alerts. WP0 (iii) drills both `WatchdogSec` and `RuntimeMaxSec` on a throwaway notify unit (**INFERRED** until then).

**Reproducibility** (`reproduce.py`):
- **Sample:** every C3 from the last 7 days whose sha first byte < `REPRO_SAMPLE_BYTE_THRESHOLD` (26), plus the newest C3 of the ISO week if none was sampled that week; at most 1 per run, oldest first.
- **Extract:** `git archive <code_git_sha> | tar -x` into `~/.cache/breezy/refit-repro/<sha>/`, read-only, not a worktree. It runs with `PYTHONPATH` set to the extract and checks that the extract's closure hash equals `producer_code_sha`.
- **Full refit from the snapshot bytes**, then **every leakage assertion re-run from the snapshot bytes** (R11): each assertion is recomputed on the rows deserialised from the snapshot and compared name by name with the lineage's `leakage_assertions`.
- **Outcomes:** an equal sha with every assertion equal gives `REPRO_PASS`. A sha mismatch or an assertion disagreement gives `REPRO_MISMATCH` (CRITICAL, exit 1). A differing `uv_lock_sha256` or `cpu_model` gives `REPRO_ENV_CHANGED` (WARN, not a pass).
- The result goes to `evidence/refit/repro_<date>.json` (`refit_run/v2`, `kind=repro`). "Sampled subset" means a sample of candidates, each refit in full (§8 C-7).

**Disk growth (R16).** `refit_run/v2.snapshot_bytes_written` is recorded on every run. WP0 (ix) measures the first full snapshot and the daily increment. `REFIT_STORE_DISK_BUDGET_BYTES` (proposed 2 GiB through the KILL) is pinned. At 80% of budget a WARN goes through `deliver_with_proof`; at 100% the run writes no snapshot or C3 (`NOT_FITTABLE(disk_budget)`) and raises a CRITICAL. Segmenting (§3.5) keeps the fixed v4.x segment to one file.

### 3.8 Live loader widening (G11) and the parent envelope (R3)

New `src/breezy/strategy/ladder_ev/rung_recalibration.py`:
- `RungRecalibration(form: Literal["none","affine"], shift: float | None)`, frozen and slotted. `affine` always means `(intercept=shift, slope=1.0)`.
- `apply(partition) -> dict[str,float]` mirrors `_apply_recalibration_scalar` and `apply_probability_recalibration` exactly: clip, renormalise, assert the sum is 1 within 1e-12.
- `is_emittable(form, affine) -> bool`: the single predicate the writer and loader share (`form == none ∧ affine is None`, or `form == affine ∧ affine[1] == 1.0 ∧ isfinite(affine[0]) ∧ |affine[0]| ≤ C_BOX ∧ |affine[0]| ≥ C_IDENTITY_EPS`).
- `REFIT_EMITTABLE_RECALIBRATION_FORMS: Final = frozenset({"none","affine"})`. `C_BOX` is a `Final` equal to the AUT-3 ruling block (pinned by test).
- `enveloped_bounds(base: tuple[p,lo,hi], recal: tuple[p,lo,hi]) -> tuple[p,lo,hi]` returns `(recal_p, min(base_lo, recal_lo), max(base_hi, recal_hi))`.

**Why an envelope rather than "g(p) ≤ p" (R3).** Renormalisation (`nbp_calibration.py:1655-1658`) makes a pre-renormalisation scalar test vacuous: `g(p) = 0.9p` satisfies g ≤ p and is the identity after renormalisation. Any non-identity partition map must raise some rung, because the partition sums to 1. Lowering a rung's p **raises** NO-leg confidence there (`ev_net_no` uses `1 − p_upper`, `scoring.py:70-82`), and NO-side hunting is a requirement (memory `no-side-hunting-is-a-requirement`). So "only lower confidence" has to be defined per leg on the gate's inputs. The envelope achieves it for every rung and both legs:
- the YES gate input `p_lower_eff ≤ p_lower_parent`;
- the NO gate input `1 − p_upper_eff ≤ 1 − p_upper_parent`;
- so the set of qualifying takes under the candidate is a subset of the parent's. The quantity is the literal 1.
- It also satisfies R3's second clause literally: the post-renormalisation maximum rung `p_lower` is ≤ the parent's.

The envelope is **unconditional code with no flag**, so no artefact can switch it off. Lifting it (after an AUT-4 PASS) would need a new reviewed form and an L-12 widening, which is out of scope (YAGNI). Under the envelope, `p_hat` is the recalibrated mean. It is recorded in C1 and scored by AUT-4's Brier, and it feeds no gate (`fq/decision.py:331-349`).

`fq/calibration_artefact.py`:
- `_SUPPORTED_RECALIBRATION` becomes `REFIT_EMITTABLE_RECALIBRATION_FORMS` (accepted set **equals** emit set, L-12).
- Acceptance uses `is_emittable` (R3, loader side): it refuses slope ≠ 1, |c| > C_BOX, non-finite values, and `none` with coefficients. `isotonic` and unknown forms stay refused.
- `LiveCalibration` gains `recalibration: RungRecalibration`.

`quantile_density.rung_probability_interval` gains the keyword `recalibration: RungRecalibration | None = None`. It returns the recalibrated interval, with the map applied to each draw's partition before the percentile step. With `None` or `none`, the output is bit-identical to today's.

`ArtefactBoundsProvider.__init__` gains `recalibration`. In one pass over the draws `__call__` computes the base and recalibrated per-draw partitions and returns `enveloped_bounds(...)` as `RungBounds`. `fq/composition.py::build_forecast_quantile_ladder_strategies` and `scripts/analysis/nbp_shadow_parity.py` pass `live_calibration.recalibration`. AUT-4 evaluates candidates through the **same** provider (analysis may import strategy), so the evaluated and traded bounds are one code path.

**Re-targeted safety test.** `test_unsupported_probability_recalibration_is_refused` (`tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py:191-196`) uses `"affine"` as its unsupported example. Under this reviewed **L-12 one-row widening** (the accepted set gains exactly `affine(slope=1, |c| ≤ C_BOX)`), its example is re-pointed to `"platt"` and `"isotonic"`, and it is never deleted or loosened. The re-point needs security-reviewer and python-reviewer sign-off in WP2, and new refusal tests are added for each excluded `affine` shape.

### 3.9 Statistical capacity, stated

About 5 fills a day cluster into fewer station-days (L-40). `MIN_NEFF_TO_EMIT = 30` station-days defers the first own-outcome candidate by weeks after C2 gains `p_at_decision`. The ridge penalty `N0` (proposed 100 pseudo-clusters, carried from r1) keeps c near 0 at small `n_eff`, so early candidates may fall below `MIN_PROBE_DELTA` and be `NOT_FITTABLE(underpowered)`. That is honest, and it is why the live proof needs only one own-outcome candidate meeting the thresholds.

### 3.10 Rulings AUT-3 drafts (peer-reviewed by mle-reviewer and prediction-market-reviewer; not operator decisions)

1. **`docs/evidence/RULING_aut3_refit_policy_<date>.md`**, with one fenced block `aut3-refit/v2` (strict JSON, exact-set keys):
   - `ROLLING_V5_DAYS = 365`, `N0 = 100`, `C_BOX = 0.05`, `C_IDENTITY_EPS = 1e-12`;
   - `MIN_PROBE_DELTA = 1e-3`, `MIN_NEFF_TO_EMIT = 30`, `MIN_P_SPREAD = 0.10`, `MAX_OFF_SUPPORT_DELTA = 0.02`, `MIN_MINT_DELTA = 1e-3`;
   - `P_REPRO_ABS_TOL = 1e-12`, `OWN_LABEL_HOLDOUT_DAYS = 7`;
   - `SEASONAL_GAP_MAX_DCRPS = 0.02`, `MIN_FORWARD_DAYS_FOR_DENSITY`, the seasonal-gap acceptance verdict (R7);
   - `REPRO_SAMPLE_BYTE_THRESHOLD = 26`, `REPRO_MAX_PER_RUN = 1`, `REFIT_STORE_DISK_BUDGET_BYTES = 2147483648`.
   - It states the evidence class (R10) and the absence of a weather holdout for `density_table` (R9). The values are proposals for the ruling's review. `windows.py`/`rung_recalibration.py` hold them as `Final` literals, and a test asserts equality, mirroring `test_live_orders_ruling_deploy_copy_matches_evidence`. **It does not restate the holdout bounds.** Those come from `RULING_holdout_freeze_and_forward_window_2026-10-03`.
2. **`docs/evidence/RULING_aut3_readme_alignment_<date>.md` (R14; also carries R6's counting).** It amends README §AUT-3 in two places:
   - **(a)** "execution data (fill, slippage and refusal), where the model class consumes them" becomes: "no FQ model class consumes execution data (operator ruling 09-29: venue prices are execution cost only); execution data enters AUT-4's EV net of cost, never a refit".
   - **(b)** The live-proof counting rule of §1.
   - The README file is edited only after the ruling is reviewed SOUND. That edit is a coordinator action, not AUT-3's. Cited in §7.

---

## 4. Work packages

**Common gate (G)**, run after every merge (L-43). Read the exit code, never the `-q` output.
- `scripts/ci/run_tests_no_egress.sh` with `/home/jon/breezy/.venv/bin/python` and `PYTHONPATH=<tree>/src:<tree>` in a worktree.
- `cd <tree> && /home/jon/breezy/.venv/bin/lint-imports` → `N kept, 0 broken`.
- `cd <tree> && /home/jon/breezy/.venv/bin/python -m mypy` plus `tests/unit/test_mypy_ratchet.py`. New packages go into `[tool.mypy] files` after grepping `tests/` for pins of that list (L-54).
- **Never** `uv`, `uv run`, `pip` or `git stash`. Each agent uses its own scratchpad.

| WP | Scope and files | RED tests first (path::name) | GREEN criterion | Activation |
|---|---|---|---|---|
| **AUT-3.WP0** L-1 checks and measurement (read-only plus capped runs) | No source change. Evidence goes to `docs/evidence/AUT3_WP0_<date>.md`. **(i)** `Splits` tagging option. **(ii)** A full `fit_calibration` inside `systemd-run --user -p MemoryMax=16G -p RuntimeMaxSec=14400 -p LimitNOFILE=524288`, outside 01:00–04:30Z, with no other study holding the lock: peak RSS, wall time, swap, giving per-unit peaks for the lock table (R13). **(iii)** Watchdog and `RuntimeMaxSec` drill on a throwaway notify unit. **(iv)** Two same-input runs give the same sha under the pinned thread env and `OPENBLAS_CORETYPE` (R12). **(v)** A Python flock helper. **(vi)** Champion = BOOTSTRAP sha. **(vii)** The seasonal-gap experiment (R7). **(viii)** Partition recomputation reproduces C1/shadow-log `p_hat` within 1e-12 for the 10-02/10-03 FQ fills, and the forecast vector is retrievable by digest. **(ix)** Snapshot bytes for the first run and the daily increment (R16). | Characterisation, no RED (L-33). Mutation evidence: a changed seed changes the sha; a perturbed forecast vector fails (viii). | Every number recorded; contingency, lock table and seasonal verdict drafted | none |
| **AUT-3.WP1** Rulings and constants | `RULING_aut3_refit_policy_<date>.md`, `RULING_aut3_readme_alignment_<date>.md`; `analysis/autonomy_refit/__init__.py`, `windows.py` | `tests/unit/autonomy_refit/test_aut3_ruling_pins.py::test_policy_constants_equal_ruling_block`; `::test_ruling_block_is_exact_set_strict_json`; `::test_sealed_bounds_equal_holdout_freeze_ruling`; `tests/unit/autonomy_refit/test_windows.py::test_sealed_days_never_in_density_or_label_window`; `::test_train_end_is_run_day_midnight_and_forward_start_next_day`; `::test_v5_forward_floor_is_seal_end`; `::test_density_waits_for_min_forward_days_when_gap_rejected` | Both rulings SOUND (mle-reviewer, prediction-market-reviewer); the ARCH holdout ruling filed; G green | rulings filed on merge |
| **AUT-3.WP2** G11 widening, envelope, live application | `strategy/ladder_ev/rung_recalibration.py` (new); `fq/calibration_artefact.py`; `strategy/ladder_ev/quantile_density.py`; `fq/artefact_bounds.py`; `fq/composition.py`; `scripts/analysis/nbp_shadow_parity.py` | `tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py::test_affine_shift_recalibration_is_accepted_and_parsed`; `::test_unsupported_probability_recalibration_is_refused` (re-pointed to platt/isotonic, L-12 row); `::test_affine_slope_not_one_is_refused`; `::test_affine_shift_outside_box_is_refused`; `::test_affine_nonfinite_or_missing_is_refused`; `::test_none_with_affine_coefficients_is_refused`; `tests/unit/test_refit_emit_set_equals_live_accept_set.py::test_emittable_recalibration_forms_equal_live_supported`; `::test_writer_and_loader_share_is_emittable`; `tests/unit/test_fq_live_analysis_point_cdf_parity.py::test_live_affine_shift_matches_analysis_apply_probability_recalibration` (≤1e-12 per rung, 200 seeded draws × 3 CDF methods × 2 ladders); `tests/unit/test_ladder_ev_quantile_density.py::test_recalibration_applied_per_draw_before_interval`; `::test_none_recalibration_is_bit_identical`; `tests/unit/test_rung_recalibration_envelope.py::test_enveloped_bounds_never_more_confident_on_either_leg` (10 000 seeded random partitions, draws and c in ±C_BOX); `::test_affine_that_is_identity_after_renorm_yields_zero_delta`; `tests/strategy/forecast_quantile_ladder/test_artefact_bounds.py::test_provider_returns_enveloped_bounds`; `::test_provider_forwards_recalibration`; `tests/strategy/forecast_quantile_ladder/test_sl13_wiring.py::test_composition_passes_artefact_recalibration`; L-55: `::test_committed_champion_loads_through_production_loader_with_none` | Parity ≤1e-12; the champion's bounds bit-identical to before; G green; security-reviewer and python-reviewer sign off the L-12 re-point | Behaviour-neutral for the champion. It takes effect at the next 16:50Z LAUNCH. Stated reason for not relaunching mid-day: no behaviour change, and a hand relaunch carries AMBIGUOUS-intent and permit risk. |
| **AUT-3.WP3** Snapshot, leakage, C3 writer | `analysis/autonomy_refit/inputs.py`, `leakage.py`, `c3_writer.py` | `tests/unit/autonomy_refit/test_inputs_snapshot.py::test_snapshot_sha_independent_of_input_order`; `::test_fixed_segment_dedupes_across_runs`; `::test_snapshot_files_are_0444_and_nofollow`; `tests/unit/autonomy_refit/test_leakage.py::test_sealed_row_injected_after_snapshot_filter_fails` (R11 mutation); `::test_forecast_available_after_cutoff_fails_ref_ts_lt_take_ts`; `::test_label_after_train_end_fails`; `::test_train_end_after_forward_start_fails`; `::test_canary_drill_unreconciled_exit_rows_fail_admissible_entry_only`; `tests/unit/autonomy_refit/test_c3_writer.py::test_writes_content_addressed_0444_0500`; `::test_refuses_any_failed_assertion`; `::test_refuses_ablation_equal_to_artefact`; `::test_affine_that_is_identity_after_renorm_fails_x22` (feeds `(0.0, 0.9)` directly; the writer's recomputed probe delta is 0); `::test_refuses_probe_delta_below_min`; `::test_refuses_neff_below_min`; `::test_refuses_off_support_delta_above_max`; `::test_refuses_slope_not_one_or_shift_outside_box`; `::test_writer_recomputes_and_refuses_lineage_disagreement`; `::test_refuses_non_ok_fit_status`; `::test_existing_sha_writes_no_new_lineage`; `::test_refuses_symlink_anywhere_on_path`; `::test_second_c3_same_lineage_same_utc_day_refused`; `::test_refuses_repo_and_deploy_families_roots`; `::test_disk_budget_exhausted_writes_nothing_critical`; `::test_payload_hygiene_no_paths_or_env` | Every refusal RED→GREEN; G green | library only |
| **AUT-3.WP4** density_table refitter | `analysis/autonomy_refit/rows.py`, `fq_density_refitter.py` | `tests/unit/autonomy_refit/test_fq_density_refitter.py::test_refit_changes_only_v5_params_draws_kappa`; `::test_bit_for_bit_reproducible_from_snapshot`; `::test_fit_rows_object_is_the_asserted_and_snapshotted_object`; `::test_rolling_rows_exclude_sealed_holdout_under_both_paths`; `::test_below_mint_delta_returns_no_change`; `::test_carries_parent_correction_and_recalibration_none`; `::test_lineage_records_windows_code_params_seed_cpu`; `::test_nonconverged_fit_writes_nothing`; `::test_progress_callback_called_per_10_draws` | Fixture fit reproducible; G green | library only |
| **AUT-3.WP5** rung_recalibration refitter (the C2 consumer) | `analysis/autonomy_refit/fq_rung_recal_refitter.py`, `partitions.py` (recomputation) | `tests/unit/autonomy_refit/test_fq_rung_recal_refitter.py::test_leave_labels_out_changes_artefact_sha_and_meets_probe_delta` (X22); `::test_ablation_bytes_equal_parent_with_none`; `::test_fit_is_one_parameter_and_renormalisation_inside_objective`; `::test_estimator_clamps_into_box_writer_never_refuses_it`; `::test_unidentified_when_neff_spread_or_stations_short`; `::test_underpowered_below_min_probe_delta_not_own_outcome_candidate`; `::test_off_support_distortion_gated`; `::test_no_label_oriented_to_yes_domain` (L-44, each leg's terminal state); `::test_yes_oriented_p_on_no_fill_fails_orientation_assertion`; `::test_exit_labels_excluded`; `::test_live_path_p_hat_equals_training_statistic` (refitter p̂_c == `ArtefactBoundsProvider(recalibration)` p_hat on the same inputs; enveloped p_lower == min(parent, recal)); `::test_partition_recompute_mismatch_excludes_label_by_name`; `::test_labels_under_recalibrated_champion_usable_via_shared_emos`; `::test_labels_from_other_emos_excluded`; `::test_cluster_weights_sum_to_one_per_station_day`; `::test_advisory_time_block_recorded_never_gates`; `::test_refitter_reads_no_venue_price_fields` (AST); `::test_refit_never_calls_open_holdout` (AST); `::test_identity_canonicalised_to_none` | C2 fixture written through the real AUT-2 label writer and C1 fixture through the real capture writer (L-42); G green | library only |
| **AUT-3.WP6** Plug-in, driver, CLI | `analysis/autonomy_refit/plugin.py`, `driver.py`, `locks.py`, `sd_notify.py`; `scripts/analysis/autonomy_refit_daily.py`; `pins.py` entry `PRODUCER_SOURCE_SHA256["aut3_refit"]` | `tests/unit/autonomy_refit/test_driver.py::test_every_live_gate_routed_kind_has_a_fitting_refitter`; `::test_refusing_plugin_kind_not_fittable_and_never_writes_c3`; `::test_older_component_first_and_one_c3_per_lineage_per_day`; `::test_below_delta_records_no_change_with_full_lineage`; `::test_past_kmax_still_writes_and_records`; `::test_mint_refused_ceiling_recorded_next_run`; `::test_every_outcome_record_is_lineage_complete`; `::test_dirty_closure_refuses_exit_3`; `::test_registry_unreadable_critical_no_refit`; `::test_c2_unreadable_runs_density_and_alerts`; `::test_nothing_to_do_exits_zero_no_input_line`; `::test_refit_run_v2_exact_set_and_hygiene`; `::test_producer_pin_mismatch_refuses_exit_3`; `::test_critical_alerts_go_through_deliver_with_proof`; L-55: `::test_run_daily_with_production_default_seams`; envelope: `test_autonomy_never_reads_or_writes_operator_controls`, `test_autonomy_never_imports_order_path`, `test_autonomy_payload_hygiene_scan`, `test_code_identity_pins_cover_import_closure` (extended to the new package) | G green; pin committed in the same commit as the closure | library plus CLI |
| **AUT-3.WP7** Units, schedule, stall watch, activation | `deploy/systemd/breezy-autonomy-refit.{service,timer}`; README unit table | `tests/unit/test_analysis_units_memory_capped.py::test_autonomy_refit_units_capped_and_bounded` (Type=notify, WatchdogSec, RuntimeMaxSec, TimeoutStartSec, MemoryMax, Slice, OnFailure, alerts.env only, thread env incl. `OPENBLAS_CORETYPE`); `::test_no_oneshot_unit_relies_on_runtime_max_sec_alone` (R13); `tests/unit/autonomy_refit/test_schedule.py::test_refit_ends_before_aut4_offline_slot_and_avoids_0100_0430`; `::test_sd_notify_pings_watchdog_on_progress` (real socket); `::test_lock_timeout_records_skipped_lock_warn_then_critical` | G green; `systemd-analyze --user verify` clean; **WP0 peak × 1.5 ≤ 16G and p95 + 1800 s ≤ RuntimeMaxSec** (R13) | **Immediate on merge:** symlink, `daemon-reload`, `enable --now breezy-autonomy-refit.timer`; confirm `breezy-studies.slice` MemoryMax ≠ `infinity`. Before C2 exists, rung_recal reports `NOT_FITTABLE(c2_absent)`. |
| **AUT-3.WP8** Reproducibility job | `analysis/autonomy_refit/reproduce.py`; `scripts/analysis/autonomy_refit_reproduce.py`; `deploy/systemd/breezy-autonomy-refit-reproduce.{service,timer}` | `tests/unit/autonomy_refit/test_reproduce.py::test_reproduce_from_snapshot_and_git_archive_matches_sha`; `::test_every_leakage_assertion_rerun_from_snapshot_bytes` (R11); `::test_assertion_disagreement_is_mismatch`; `::test_mismatch_critical_exit_1`; `::test_env_or_cpu_changed_classified_not_pass`; `::test_sample_rule_deterministic_and_weekly_forced`; `::test_extract_closure_hash_must_equal_producer_code_sha`; `::test_repro_unit_env_equals_refit_unit_env` (R12); schedule row `::test_repro_runs_after_aut4_slots_and_before_0100` | G green | Immediate on merge: enable `breezy-autonomy-refit-reproduce.timer` |
| **AUT-3.WP9** Live-proof report | `scripts/analysis/aut3_live_proof_report.py` (read-only) | `tests/unit/autonomy_refit/test_live_proof_report.py::test_streak_counts_recorded_consumed_runs`; `::test_no_change_not_fittable_mint_refused_count_when_consumed`; `::test_skipped_lock_or_failed_breaks_streak`; `::test_requires_minted_own_outcome_candidate_meeting_x22_thresholds`; `::test_underpowered_not_fittable_never_counts_as_own_outcome`; `::test_requires_aut4_ack_for_every_run_and_verdict_for_every_candidate`; `::test_requires_one_repro_pass_in_window`; `::test_reports_strict_readme_candidate_streak_separately` | G green | Run by hand only by the independent scorer; no timer |

---

## 5. Association

| Contract | Direction | Exact interface |
|---|---|---|
| C1 | consumed (AUT-1) | `DecisionRecord.{decision_id, eval_ns, side, rung_id, p_hat, p_lower, p_upper, forecast_input_sha256, artefact_sha256}` via ARCH-0's reader; ARCH-0's `forecast_input_digest` helper (INFERRED name) |
| C2 | consumed (AUT-2) | `label/v1` via ARCH-0's reader, admitted per §3.4(a); the `label_outcomes_ok_<date>` marker. **Request to AUT-2 r2:** pin `p_at_decision` as the bought-leg probability (`1.0 − p_hat` for NO, computed exactly so) to match the merged review; AUT-2 r1 line 135 sets `p_at_decision = DecisionRecord.p_hat` (§8 C-1). |
| C3 | **provided** | `derived/artefacts/<model_class>/<sha>/{artefact.json, lineage.json}`, at most one per lineage per UTC day, delta-gated |
| `refit_run/v2` | **provided** | `evidence/refit/refit_run_<date>.json`: every run outcome, lineage-complete |
| C4 | none written | AUT-6's `refit_freshness` (no `refit_run` by 12:00Z, or `SKIPPED_LOCK`/`FAILED` on 2 consecutive days) and `refit_repro` (`REPRO_MISMATCH`) map to `HEALTH` |
| C5 | consumed (AUT-5) | Read-only fold: champion, `lineage_root_family_id`, bound sha, MINT rows (for `prior_mint_status`). AUT-3 never writes the registry. |
| C6 | **provided** | `Refitter` for `forecast_quantile_ladder`; `RefusingPlugin` for the rest |
| Delivery | consumed (AUT-6) | `deliver_with_proof` |
| AUT-4 | downstream | (1) Reads every new C3 and emits its verdicts; past K_max, `INCONCLUSIVE(K_MAX_EXHAUSTED)`, no α (AUT-4 r1 §3.5, W7 option 1). (2) **Request to AUT-4 r2:** acknowledge every `refit_run/v2` record in its ledger (`refit_run_ack{run_date, lineage, status, consumed_at_ns}`), so non-candidate runs are "consumed" (R6). (3) Evaluates rung_recal candidates through `ArtefactBoundsProvider` with the envelope (§3.8). |
| AUT-7 | downstream | Re-verifies `sha256(artefact.json)` on rollback |

**Execution order.** ARCH-0 first. Wave 1 (disjoint files from AUT-1/5a/6): WP0, WP1, WP3, WP4. Wave 2, after AUT-2b and AUT-1 C1: WP5 and WP6. WP2 follows AUT-1's and AUT-5a's edits to `fq/strategy.py`/`fq/composition.py` and is rebased onto them. WP7 follows WP6 and WP0's measurements. WP8 follows WP7. WP9 follows AUT-4's offline consumer and the run ack. WP3 ∥ WP4; WP5 ∥ WP2.

---

## 6. Live-proof protocol

**Artefacts that prove score 3:**
1. Seven consecutive `evidence/refit/refit_run_<date>.json` records on qualifying days, from timer-started runs (`systemctl --user show -p TriggeredBy`), each status in `{CANDIDATE, NO_CHANGE(below_delta), NOT_FITTABLE, MINT_REFUSED_CEILING}`, each with full `data_windows`, `params`, `seed`.
2. An AUT-4 ledger `refit_run_ack` for each of the 7, and for each `CANDIDATE` a C4 verdict whose `inputs[]` cites the sha (or `INCONCLUSIVE(K_MAX_EXHAUSTED)`), plus the AUT-5 MINT row or the recorded `MINT_REFUSED_CEILING`.
3. Every C3 in the window has `[.leakage_assertions[].passed] | all == true`.
4. At least one **minted** `rung_recalibration` C3 with `own_outcome_label_set_sha256 ≠ null`, `ablation ≠ artefact`, `probe_max_delta ≥ MIN_PROBE_DELTA` and `n_eff ≥ MIN_NEFF_TO_EMIT`.
5. At least one `REPRO_PASS` in the window.
6. The WP9 report `~/.local/share/breezy/evidence/refit/aut3_live_proof_<date>.md`, which reports both `STREAK_RUNS` and `STREAK_CANDIDATES`.

**Claim rule.** If the README-alignment ruling (§3.10 item 2) is SOUND, score 3 = `STREAK_RUNS ≥ 7` plus items 2–5. If it is rejected, score 3 requires `STREAK_CANDIDATES ≥ 7` (strict README). The plan then sets `MIN_MINT_DELTA = 0` for `density_table` only, by ruling: no α cost past K_max, under W7 option 1. Either way an own-outcome candidate meeting the thresholds is required. **The runs are not independent samples (R6).**

**Window rule (ARCH §5.3).** A day counts only with ≥1 real fill or a production-path canary fill, and the window needs ≥5 real fills. `SKIPPED_LOCK` or `FAILED` on a qualifying day breaks the streak. Canary and drill labels never train.

**Failure-mode drills for (d).** Each is a one-shot `systemd-run --user` of the production script with `--drill <kind>`, carrying the shared environment. Drill runs never write C3, tag `refit_run.drill=true`, and are refused without the flag. Kinds: `stall` (watchdog), `runtime` (sleep past a short `-p RuntimeMaxSec`), `lock` (`SKIPPED_LOCK`), `oom` (past `MemoryMax`), `repro-mismatch` (a tampered **copy** of a snapshot), `pin` (an unpinned closure in a scratch extract), `dirty` (a dirty closure file in a scratch copy), `disk` (a budget override in drill mode only). Delivery is proven by AUT-6's `evidence/alerts/delivery_<date>.jsonl` with `delivered=true`.

**Accrual ETA.**
- ARCH-0 by about 10-10. Wave 1 by about 10-17. AUT-2b C2 with `p_at_decision` by about 10-24. AUT-4 offline consumer, run ack and engine MINT by about 11-07.
- `n_eff ≥ 30` station-days of entry labels from 10-02 onward at the current fill rate: about 3–4 weeks of trading, so by about 11-01 if fills continue (labels from 10-02 count once C2 carries them).
- **Earliest DONE 2026-11-14; planning ETA 2026-11-21**, about 9 weeks before the 2027-01-25 KILL.
- If fills stop (an A1-style halt or DEMOTE), the own-outcome leg waits and the window extends. If the partition recomputation (WP0 viii) fails and the C1 fallback is not adopted, the own-outcome leg is unreachable and is reported as **score 2**, never claimed as 3.

**Evidence class: machinery proven, edge unproven.** No edge verdict is pre-registered here. A recalibration candidate is expected to show no edge (R10). Promotion is AUT-4/AUT-5's question and is expected to be UNDERPOWERED.

---

## 7. Score-3 verification checklist (for an independent scorer)

| Criterion | Exact check |
|---|---|
| (a) unattended | `journalctl --user -u breezy-autonomy-refit.service --since <W0> --until <W7> \| /usr/bin/grep -c 'REFIT_RESULT '` ≥ 7 qualifying-day runs, none `SKIPPED_LOCK`/`FAILED`; `systemctl --user show breezy-autonomy-refit.service -p TriggeredBy` = the timer; `git log --since=<W0> -- deploy/families src/breezy/strategy/forecast_quantile_ladder` shows no artefact or manifest commit |
| (b) family-agnostic | `test_driver.py::test_every_live_gate_routed_kind_has_a_fitting_refitter`, `::test_refusing_plugin_kind_not_fittable_and_never_writes_c3`, ARCH-0 `test_family_plugin_exact_set`; each `refit_run_<date>.json` lists every non-RETIRED lineage root |
| (c) fails closed | WP3 `test_c3_writer.py::*refuses*`, `::test_affine_that_is_identity_after_renorm_fails_x22`; WP2 loader refusals and `test_rung_recalibration_envelope.py::test_enveloped_bounds_never_more_confident_on_either_leg`; WP6 `::test_dirty_closure_refuses_exit_3`, `::test_producer_pin_mismatch_refuses_exit_3`; live: `jq '[.leakage_assertions[].passed]\|all' lineage.json` = true for every C3 |
| (d) detected and delivered | For each §6 drill: the journal line (`watchdog`, `timeout`, `SKIPPED_LOCK`, `oom-kill`, `REPRO_MISMATCH`, `PIN_MISMATCH`, `DIRTY_CLOSURE`, `DISK_BUDGET`) and a `delivered=true` row in `evidence/alerts/delivery_<date>.jsonl` |
| (e) RED→GREEN | Per WP: RED and GREEN logs plus commit SHAs; full gate exit 0 after every merge |
| (f) live proof | `aut3_live_proof_report.py --since <W0>` prints `STREAK_RUNS=7 STREAK_CANDIDATES=<n> QUALIFYING_FILLS>=5 AUT4_ACK=7/7 OWN_OUTCOME_CANDIDATE=<sha> PROBE_MAX_DELTA>=1e-3 N_EFF>=30 MINTED=yes REPRO_PASS>=1`; the scorer re-hashes each `artefact.json` and confirms the cited C4 verdicts, MINT rows and acks exist; the claim rule in §6 is applied with the README-alignment ruling's status |
| Execution-data clause | `docs/evidence/RULING_aut3_readme_alignment_<date>.md` exists with SOUND reviews (R14); `test_fq_rung_recal_refitter.py::test_refitter_reads_no_venue_price_fields` green |
| Lineage completeness | every `lineage.json` and every `refit_run/v2.results[]` has non-null `data_windows[].content_sha256`, `code_git_sha`, `producer_code_sha`, `params`, `seed`; every snapshot exists and re-hashes |
| Loader parity | `pytest tests/unit/test_fq_live_analysis_point_cdf_parity.py::test_live_affine_shift_matches_analysis_apply_probability_recalibration tests/unit/test_refit_emit_set_equals_live_accept_set.py tests/unit/test_rung_recalibration_envelope.py` exit 0 |
| Holdout | `test_aut3_ruling_pins.py::test_sealed_bounds_equal_holdout_freeze_ruling`, `::test_refit_never_calls_open_holdout`; the registry's `holdout_opens` is unchanged by any AUT-3 run |

---

## 8. Risks, failure modes and contradictions with ARCH

**Contradictions and gaps (to feed ARCH Rev 5, AUT-2 r2 and AUT-4 r2):**
- **C-1 (NEW, ARCH C2 gap).** C2 does not pin the orientation of `p_at_decision`. `settled_outcome` is bought-leg (ARCH C2), but AUT-2 r1 sets `p_at_decision = DecisionRecord.p_hat` (line 135), and `p_hat` is the YES-rung mean on both legs (`artefact_bounds.py:60`; `fq/decision.py:331,366`). For NO fills the pair is misoriented. The merged review says AUT-2 pins bought-leg; AUT-2 r1 does not. AUT-3 fails closed on mismatch (§3.4(a)), but ARCH C2 must pin it.
- **C-2 (NEW, ARCH §5.2/§10).** "Every study sets `RuntimeMaxSec`" has no effect on `Type=oneshot` units (`man systemd.service`). AUT-4 r1 lists `RuntimeMaxSec` on its oneshot-style units. AUT-3 uses `Type=notify` (§3.7). ARCH should say "`RuntimeMaxSec` on notify/simple units, `TimeoutStartSec` on oneshot units".
- **C-3 (W7 still open).** AUT-3 adopts W7 option 1 (past K_max = consumed, no α), and AUT-4 r1 already emits `INCONCLUSIVE(K_MAX_EXHAUSTED)`, not ARCH's `ERROR`. ARCH Rev 5 must pick one outcome literal.
- **C-4 (README live proof vs Y13).** "Each producing a lineage-complete candidate" conflicts with multiplicity control. The amendment is drafted (§3.10 item 2), and the claim rule in §6 covers both outcomes.
- **C-5 (G11 semantics).** The de-risking envelope is loader semantics that ARCH G11 ("bounded by the loader") does not name. ARCH should name it, so AUT-4 evaluates the same bounds.
- **C-6 (C1 fallback).** If partition recomputation fails WP0 (viii), C1 needs `rung_partition_p_hat` on `Take`/`TrySubmit`.
- **C-7.** "Reproduces the sha on a sampled subset" means a sample of candidates, each refit in full.
- **C-8.** `refit_run/v2` is a non-C record that AUT-4 (ack) and AUT-6 (detectors) consume. §4.3's pins cover only `breezy.*`, but the refit uses `scripts/analysis/{autonomy_refit_daily,nbp_skill_study,settlement_truth_dataset}.py`, which the `aut3_refit` closure must include.
- **C-9.** P_HOLD stays frozen; `density_table` is a naming literal only; WP-23 is rejected (operator 09-29).
- **C-10.** ARCH places AUT-3 in Wave 2, but the live proof needs AUT-4's offline consumer, the run ack and engine MINT (Wave 3).

**Risks and failure modes:**

| Risk | Mitigation |
|---|---|
| Memory on the 31 GB host (studies at 10–24 GB) | One studies-flock holder; MemoryMax from WP0 (≤16G); refit 06:00, repro 18:00, neither in 01:00–04:30Z; stop the study, never the node |
| Hung or slow fit (the 20 h S2 precedent) | WP0 benchmark; `WatchdogSec` per progress; `RuntimeMaxSec` (effective on notify); the WP7 merge gate on the measured p95; the contingency estimator |
| Shared venv | Exact interpreter; never `uv`/`pip`; repro by `git archive` + `PYTHONPATH`; `uv_lock_sha256` and `cpu_model` recorded |
| Concurrent agents | Disjoint Wave 1 files; WP2 serialised behind `fq/composition.py` owners; per-agent scratchpads; no `git stash`; full gate per merge; dirty-closure refusal at runtime |
| Producer-pin churn | `test_code_identity_pins_cover_import_closure` turns RED in the editing commit; a pin refusal is CRITICAL the same morning |
| Statistical capacity | One parameter, a function-space ridge, `MIN_NEFF_TO_EMIT`, spread/station checks, the off-support gate; underpowered is `NOT_FITTABLE`; evidence class stated |
| A recalibration with no edge consumes α | The delta gate; past K_max no α (W7 option 1); AUT-4's no-α pre-screen |
| Envelope suppresses every take for a candidate | That is de-risking by design, and AUT-4 scores it. Promotion of a candidate that never trades is AUT-4's EV predicate failing, not a safety issue |
| Partition recompute drift after a `quantile_density.py` change | Labels excluded by name; >10% excluded is CRITICAL; the C1 fallback (C-6) |
| C2 orientation defect upstream | `label_orientation_matches_capture` fails the run (CRITICAL); RED test per leg |
| Seasonal gap biases v5.0 | WP0 (vii) measured on pre-holdout rows; the ruling accepts it or defers density refits |
| Disk growth | Segmented content-addressed snapshots; budget with WARN at 80% and refusal at 100% |
| KILL 2027-01-25 | ETA 11-21. After a TERMINAL KILL, refits continue on the frozen lineage (MINT allowed, PROMOTE refused, ARCH §5.3) |
| `nbp_learning_nightly` scores a hard-coded path and pre-July rows | Not changed here; AUT-6 retargets it after the holdout ruling |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** no Nautilus file is touched. Refits are offline. The node loads sha-pinned bytes through the existing loader.
- **Caps:** no autonomy-refit module reads, assigns or reads upward any `OPERATOR_RESERVED_CONTROL_ENV_VARS` (`test_autonomy_never_reads_or_writes_operator_controls` extended). The units never load `operator.env`.
- **What p feeds (corrected, R3):** the recalibrated bounds feed the FQ **take gate** (`p_lower` for YES, `1 − p_upper` for NO; `fq/decision.py:349`). Gate eligibility is an exposure decision. The quantity is the literal `QTY = 1` (`fq/decision.py:73`), so p feeds no size in FQ today. r1's "no refit parameter touches sizing" understated the gate path. The envelope (§3.8) guarantees a candidate can only remove takes on both legs. If any future sizing consumes p, it must consume the enveloped bounds.
- **`allow_short=False`:** untouched (`fq/config.py:74-82`). No refit parameter changes sides. §4.2 manifest equality forbids it.
- **NO-SEND:** no new egress host. Alerts use only `alerts.env` through `deliver_with_proof`. `test_execution_egress_firewall_guard` is unchanged. No `exec/`, adapter or order-path import.
- **Master enablement and permit:** never read or written. AUT-3 writes only under `derived/` and `evidence/`.
- **PREREG via ruling:** every AUT-3 constant comes from `RULING_aut3_refit_policy_<date>.md`. The holdout comes from ARCH's `RULING_holdout_freeze_and_forward_window_2026-10-03`. The README amendments come from `RULING_aut3_readme_alignment_<date>.md`. Each is pinned by test. Nothing is invented at runtime.
- **Safety tests never weakened:** one refusal test's example is re-pointed under a reviewed L-12 one-row widening, with security-reviewer and python-reviewer sign-off. Refusal tests are added for every excluded affine shape. No settlement, contract or NO-SEND test is edited.

---

## 10. Self-score (r2)

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 17 | Every §10 and C3 obligation is mapped and rebased on Rev 4 and the holdout decision. The live-proof counting depends on the README-alignment ruling; both outcomes have a defined claim rule. |
| Correctness | 20 | 17 | The identifiability and renormalisation analysis is from code. Orientation, X22 and the envelope are fail-closed. Still INFERRED: partition recomputation by forecast digest (WP0 viii), Splits tagging, watchdog semantics. |
| Specificity | 15 | 14 | Files, functions, units, slots, constants and the lock table are named. Some reader and digest names are ARCH-0's. |
| Acceptance | 20 | 17 | The checklist names commands and paths, and WP9 reports both streaks. It depends on AUT-4's run ack and C2 orientation (requests filed). |
| Autonomy-safety | 15 | 14 | The unconditional envelope on both legs, writer and loader sharing one predicate, the clean-tree and pin refusals, drills with delivery proof. |
| Reuse | 10 | 9 | Reuses the `affine` form, `apply_probability_recalibration`, `rung_probability_interval`, the fitters and the studies infrastructure. One new 1-D estimator and one envelope function. |
| **Total** | 100 | **88** | |

---

## §R2 Disposition (review `reviews/AUT-3-r1-merged.md`)

**16 FIXED, 0 REJECTED.** R3 is fixed with a stronger substitute for one clause, with code evidence given below.

| R | Disposition | Where / evidence |
|---|---|---|
| R1 | FIXED | §3.4(h): the probe set is the real base partitions of the training decisions, through `apply_probability_recalibration` including renormalisation (`nbp_calibration.py:1655-1658`); `MIN_PROBE_DELTA` and `MIN_NEFF_TO_EMIT` (§3.10); `NOT_FITTABLE(underpowered)` is not an own-outcome candidate; the writer recomputes (§3.6); `test_affine_that_is_identity_after_renorm_fails_x22` (WP3); WP9 `::test_requires_minted_own_outcome_candidate_meeting_x22_thresholds` |
| R2 | FIXED | §2 identifiability finding (for slope b > 0 the affine map is a function of a/b alone after renormalisation; `(0, b)` is the identity); §3.4(e) one parameter (slope pinned to 1) **plus** the function-space ridge, with renormalisation inside the objective; §3.4(f) support checks → `NOT_FITTABLE(unidentified)`; §3.4(g) off-support writer gate; §3.2 recast as hypothesis H-R with mechanism and competing evidence ("smaller" withdrawn: `QTY = 1`, `fq/decision.py:73`) |
| R3 | FIXED | §3.8: an unconditional parent envelope gives `p_lower_eff ≤ parent` and `p_upper_eff ≥ parent` on every rung, so takes can only be removed on both legs, and the post-renormalisation maximum rung `p_lower` is ≤ the parent's (R3's second clause holds literally). R3's first clause, "g(p) ≤ p on the grid", is **replaced, with evidence**: renormalisation makes it vacuous (`0.9p` passes it and is the identity, `nbp_calibration.py:1655-1658`), and lowering p raises NO-leg confidence (`scoring.py:70-82`). Enforced in the writer (§3.6, `envelope_never_more_confident`) and the loader (`is_emittable`, the unconditional envelope); the estimator clamps into the box (§3.4(e), `::test_estimator_clamps_into_box_writer_never_refuses_it`); §9 corrected (p feeds the gate; size is the literal 1; caps never read or assigned) |
| R4 | FIXED | §3.4(b): fitted statistic = `p_hat` (per-draw map then mean, as live); `p_lower` is diagnostic and enveloped; §3.4(a): bought-leg labels converted to the YES-rung domain, asserted against C1 `p_hat`; exit labels excluded; RED tests `::test_no_label_oriented_to_yes_domain`, `::test_yes_oriented_p_on_no_fill_fails_orientation_assertion`, `::test_exit_labels_excluded`, end to end `::test_live_path_p_hat_equals_training_statistic`; upstream inconsistency logged as C-1 |
| R5 | FIXED | Header and §3.3: rebased on Rev 4 sha `17531011…dd508e` and ARCH-r4-merged; `HOLDOUT-decision.md` adopted by ruling name with the r1 freeze withdrawn; AUT-3 never opens the holdout (AST test); no α charged; α_k halving drives the delta gate |
| R6 | FIXED | §3.3 delta gate `NO_CHANGE(below_delta)`, daily ceiling, W7 option 1 for K_max, `MINT_REFUSED_CEILING`; §1/§6 live proof restated as 7 consecutive recorded and consumed runs plus a minted own-outcome candidate meeting R1; non-independence stated; WP6/WP9 tests; README tension handled by §3.10 item 2 and the §6 claim rule |
| R7 | FIXED | §3.3 seasonal gap: WP0 (vii) experiment on pre-holdout v4.3 rows only; acceptance rule and fallback in the policy ruling |
| R8 | FIXED | §3.4(i): time-blocked own-label holdout recorded as advisory in `params.advisory_time_block`; never gates a write |
| R9 | FIXED | §3.3 and §3.10 item 1: no fresh weather holdout for `density_table` after the freeze; forward shadow is the only confirmation |
| R10 | FIXED | §3.2 evidence class: a recalibration candidate is expected to show no edge; the LOSO Platt fit worsened the mid; AUT-4 likely UNDERPOWERED; the under-confidence evidence is also stated |
| R11 | FIXED | §3.7 WP8 re-runs every leakage assertion from the snapshot bytes; §3.4/§3.5 `no_sealed_holdout_rows_in_train` runs on the exact fit row tuple (`::test_sealed_row_injected_after_snapshot_filter_fails`, `::test_every_leakage_assertion_rerun_from_snapshot_bytes`) |
| R12 | FIXED | §3.7: pinned `OPENBLAS_CORETYPE`, `cpu_model` recorded (host i7-11700K), clean-tree refusal for closure files, repro unit environment equal to the refit's (`::test_repro_unit_env_equals_refit_unit_env`) |
| R13 | FIXED | §3.7 lock and memory table from WP0 (ii); repro moved to 18:00Z, after the AUT-4 slots; WP7 merge gated on the measured peak and p95; systemd note: RuntimeMaxSec is ineffective on oneshot (`man systemd.service`), so the units are `Type=notify` (active after READY) with `TimeoutStartSec` for the pre-READY phase; `::test_no_oneshot_unit_relies_on_runtime_max_sec_alone`; ARCH gap C-2 |
| R14 | FIXED | §3.10 item 2: `RULING_aut3_readme_alignment_<date>.md` amends the execution-data clause; cited in §7 |
| R15 | FIXED | §3.4(d): base partitions are recomputed from the shared EMOS draws, so labels decided under a recalibrated champion stay usable and the parent-recalibrated stop is removed without a C2 change; the remaining limit (labels from an older EMOS after a density promotion) is stated |
| R16 | FIXED | §3.7 disk growth: `snapshot_bytes_written`, WP0 (ix) measurement, segmented dedupe, pinned budget with WARN/refusal, `::test_disk_budget_exhausted_writes_nothing_critical` |
