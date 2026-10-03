# AUT-3 — Retraining (refit pipeline): area plan

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-3 |
| Title | Retraining: scheduled, lineage-complete, leakage-guarded refits for every live composition kind, including one model class that consumes the bot's own labelled outcomes |
| Round | r1 (2026-10-03) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` Rev 3 snapshot, sha256 `66002f49ca33515e3515102d9dbb4134935e0573f85a98a5c41f1352f91361af` (the sha scored in `reviews/ARCH-r3-merged.md`), with the r3 deltas Z1–Z20 treated as applied. Repo HEAD `4b8347a6`. |
| Current score | 0 |
| Target | 3 |
| Upstream | ARCH-0 (`persistence/autonomy/`: schemas, C6 Protocols and registries, `pins.py`, the resolver as a read-only fold); AUT-1 (C1 `DecisionRecord`: `p_hat`, `artefact_sha256`, `eval_ns`, `decision_id`); AUT-2 (C2 `label/v1`); AUT-5 (registry: champion and lineage per venue; MINT from C3); AUT-6 (`deliver_with_proof`, the `refit_freshness` and `refit_repro` detectors, the `RuntimeMaxSec` rule) |
| Downstream | AUT-4 (consumes every C3 candidate as `OFFLINE_CHALLENGER` and `FORWARD_SHADOW` input); AUT-5 (MINT ∅→SHADOW from C3); AUT-7 (rollback re-verifies the C3 bytes) |
| Planning only | Nothing here is implemented. No commit, stash, `uv`/`pip` or `systemctl` was used to write it. |

**Evidence tags.** `file:line` was checked at `4b8347a6` with codegraph (projectPath `/home/jon/breezy`) and read-only reads. **INFERRED** means not verified against running code; each such item is cleared by a named L-1 check in WP0 before the slice that relies on it starts.

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

**ARCH §10 obligations for AUT-3, verbatim:**
> the refit cadence and windows; the mint path honouring `MAX_MINTS_PER_LINEAGE_PER_DAY`; the ablation and leakage assertions; the reproducibility sample; the G11 widening with parity tests; its unit's `MemoryMax`, `RuntimeMaxSec` and flock wait.

**ARCH C3 obligations, verbatim excerpts:** "`ablation_artefact_sha256` is the same refit with that set left out, and the writer refuses the lineage if it is non-null and equals `artefact_sha256`"; "**The C2-consuming model class** is `forecast_quantile_ladder:rung_recalibration`, fitted on C2 `(p_at_decision, settled_outcome)`; it needs the G11 loader widening with parity tests. `forecast_quantile_ladder:density_table` consumes external weather only." X22 (Rev 1 review): "refitting with the label set left out must change the artefact sha. Name the model class that consumes C2."

Where this plan reaches each line is mapped in §7.

---

## 2. L-1 null hypothesis and reuse

| New component | Nautilus or Breezy capability checked | Verdict |
|---|---|---|
| Offline refit scheduler | Nautilus has no artefact registry, refit or scheduled job (`WORK_BREAKDOWN:288`; ARCH §2 L-1). systemd timers are the repo's convention (`deploy/systemd/breezy-nbp-learning-nightly.timer`). | BUILD a oneshot unit. No in-node fitting: the node keeps loading sha-pinned bytes only (`fq/config.py:90-96` "There is no live refitting" stays true). |
| EMOS refit (`density_table`) | `fit_calibration` (`analysis/nbp_calibration.py:1280-1334`), `fit_hierarchical_emos` (`:1166-1253`), seeded `bootstrap_emos_draws` (`:1070-1153`, `BOOTSTRAP_SEED` `:451`), `artefact_from_calibration_fit` (`:2550-2632`), `artefact_json`/`artefact_sha256`/`write_artefact` (`:2635-2665`); the row join `build_version_rows` (`scripts/analysis/nbp_skill_study.py:661`). | REUSE unchanged. AUT-3 adds only window selection and the rolling split tagging. |
| Recalibration fit (`rung_recalibration`) | `_fit_affine` (`nbp_calibration.py:1535-1544`), `_apply_recalibration_scalar` (`:1560-1577`), `apply_probability_recalibration` (`:1647-1662`, which renormalises the rung partition), `ProbabilityRecalibrationForm` (`:1508-1511`), and the artefact fields `recalibration_affine`/`recalibration_isotonic_points` (`:2381-2382`, `:2438-2445`, `:2531-2537`). | REUSE the form and its application. ADD one estimator, cluster-weighted affine shrunk toward identity (§3.4), because `_fit_affine` is unweighted and has no shrinkage, so on n≈tens of labels it overfits. |
| Live recalibration application | `LiveCalibration` (`fq/calibration_artefact.py:118-172`) refuses any `recalibration` other than `none` (`:68`, `:281-287`). `rung_probability_interval` (`strategy/ladder_ev/quantile_density.py:392-442`) has no recalibration step. `ArtefactBoundsProvider` (`fq/artefact_bounds.py:38-60`). | WIDEN (L-12): accepted set becomes exactly `{none, affine}`, the set the AUT-3 pipeline emits. Add a strategy-layer `RungRecalibration`, applied per bootstrap draw before the percentile interval. |
| Candidate store | G13 candidate root guard `_resolve_candidate_root` (`scripts/analysis/nbp_learning_nightly.py:708-719`); ARCH C3 content-addressed layout. | GENERALISE to `derived/artefacts/<model_class>/<sha>/` and keep the out-of-repo refusal. |
| Lineage schema | ARCH-0 `persistence/autonomy/` (C3 `lineage/v1` type). | CONSUME. AUT-3 owns the C3 writer only. |
| Plug-in dispatch | C6 `Refitter` Protocol plus `OFFLINE_PLUGINS` keyed by `CompositionKind` (`family_manifest.py:115-121`). | IMPLEMENT `FqRefitter` for `forecast_quantile_ladder`. `RefusingPlugin` stays for the three non-live kinds. |
| Studies lock, slice, failure notifier | `breezy-studies.slice` (12G/16G), `breezy-study-failed@.service`, the `breezy-studies.lock` convention (`deploy/systemd/replay-daily-run.sh:101`, `station-candidate-register-run.sh:44-47`). | REUSE. The flock is taken in Python so the watchdog keeps pinging during the wait (§3.7). |
| Stall watch | No unit uses `RuntimeMaxSec` or `WatchdogSec` (G29; `/usr/bin/grep` for `WATCHDOG=1`/`NOTIFY_SOCKET` in `src scripts deploy`: 0 hits). | BUILD `Type=notify` plus `WatchdogSec`, with `sd_notify` over the stdlib `NOTIFY_SOCKET` (about 15 lines, no new dependency, never `uv`). |
| Alert delivery | `emit_alert` swallows failures (G25). ARCH §4.6 `deliver_with_proof` is owned by AUT-6. | CONSUME `deliver_with_proof` for CRITICALs (Z13). |
| P_HOLD (CRH) refit | `P_HOLD_LOWER/UPPER` are **code constants** in `strategy/current_rung_hold/archive_table.py:37-41`, generated by `scripts/analysis/generate_current_rung_hold_archive_table.py:197-348`. Every CRH kind has no non-RETIRED family (bootstrap seeds v4, cont and v2 RETIRED; ARCH C5) and so carries `RefusingPlugin` (C6 YAGNI). | NOT IN SCOPE, stated: P_HOLD stays frozen. A CRH kind can be re-admitted only by a change that ships full plug-ins (C6), and its `Refitter` would first have to turn the table into a manifest-pinned artefact (`WORK_BREAKDOWN:314`). The `refit_run` record names the kind `NOT_FITTABLE(refusing_plugin)`. |
| Execution-data refit | No FQ component takes fill, slippage or refusal as a model input. Operator ruling 09-29 (memory `prediction-from-weather-venues-for-cost`): venue prices are execution cost only. WP-23 "market-conditioned recalibration" uses the ask as an input (`WORK_BREAKDOWN:481`). | NOT BUILT, stated: the README's "where the model class consumes them" clause is not met by any FQ class. Execution data enters AUT-4's EV-net-of-cost evaluation, never a refit. WP-23 is rejected because it would make a venue price a predictor. |

---

## 3. Design

### 3.1 Model classes for `forecast_quantile_ladder` (the only kind in `LIVE_GATE_ROUTED_KINDS`, G19)

One FQ artefact is one `NbpCalibrationArtefact` JSON (`nbp_calibration.py:2355-2453`), the file a manifest's `density_artefact_path` names. The champion is `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`, sha `9c0b6d6e…923a5e`, 60,987 bytes. It is byte-identical to the nightly's `nbp_validate_candidate_2026-09-30.json` (checked with `sha256sum`), with `recalibration=none`, `correction_form=linear_lst_day_length`, versions v4.0–v5.0 and 200 draws. A child may differ from its root only in `density_artefact_path/sha` (§4.2), so **every candidate is a complete artefact**. `model_class` names which component was refit:

| `model_class` (ARCH literal) | What changes vs the parent | Inputs | Own outcomes |
|---|---|---|---|
| `forecast_quantile_ladder:density_table` | v5.0 `(a, γ)`, its draws, κ (LOVO) and the per-draw δ. v4.x rows are fixed (NBM v4 is retired, so no new rows exist). Correction form and coefficients are carried from the parent; `recalibration=none`. | External only: `derived/nbp` (4 stations, `KLAX KMDW KMIA KSFO`) ⨝ `settlement-truth/settlement_truth.parquet` FINAL rows | `own_outcome_label_set_sha256 = null` |
| `forecast_quantile_ladder:rung_recalibration` | Only `recalibration`, `recalibration_affine`. Every other field is **byte-equal to the parent** (asserted). | C2 `label/v1` rows `(p_at_decision, settled_outcome)`, admissible only | non-null; ablation required |

**Naming note.** The ARCH string `density_table` here means the NBP EMOS calibration artefact, not `strategy/ladder_ev/density_table.py` (the RETIRED `forecast_ladder` kind). The string is kept because it is a contract literal (contradiction 5, §8).

### 3.2 Why `rung_recalibration` is the C2 consumer, and what it can and cannot do

- **It is the only FQ component whose correct training population is the traded one.** Takes are selected where `p_lower > ask + fee`. Given that the market's resolution is 1.98× the forecast's (memory `forecast-edge-closed-pmus-rungs`), the expected conditional calibration on the **selected** rows is over-confident (winner's curse). The archive-table lesson applies directly: a frozen artefact describes a different population from the one the live gate selects (memory `archive-table-train-serve-skew`). A reliability map fitted on own fills is the only estimator of that selection-conditioned miscalibration. The expected effect is to **lower** `p` where the bot takes, so it takes fewer and smaller positions. That is learning that reduces risk.
- **It cannot reopen the closed edge, and the plan does not claim it does.** Recalibration adds no resolution. A LOSO Platt fit made the mid **worse** (same memory note). The pinned nightly's latest `bss_vs_m1 = −0.0399` says the current EMOS is already worse than its M1 baseline. The NBP PM.us confirmatory leg is infeasible (n_min 592 > 520; `RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md`).
- **Statistical capacity is tiny.** About 5 fills a day, clustered into far fewer independent station-days (L-40). The estimator is therefore shrunk hard toward identity (§3.4). A promotion of any such candidate requires AUT-4's forward-shadow PASS against the market-implied baseline, which will almost surely be `UNDERPOWERED` before the KILL.
- **Evidence class for the AUT-3 DONE claim: "machinery proven, edge unproven".**
- **Rejected alternative:** fitting on all C1 `DecisionRecord`s ⨝ settlement (refusals included). That would be larger, but it carries the same information as the external NBP×CLI rows already used by `density_table`. It is not the bot's trading outcome, and C3 names C2.

### 3.3 Windows, the sealed holdout and cadence

**The sealed-holdout conflict (contradiction 1).** The NBP Rev3 v5.0 holdout is `2026-07-01..last final CLI, growing forward` (`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3:237`; `DEFAULT_SPLITS.holdout_start` `nbp_calibration.py:273-278`). It covers the only 4 ingested stations. Every post-June external row, and **every** C2 label (FQ `d0_climate_day` is 2026-10-02), lies inside it. C3's `no_sealed_holdout_rows_in_train`, a rolling window and own-outcome consumption therefore cannot all hold under the current definition.

**Resolution: ruling `docs/evidence/RULING_aut3_refit_windows_and_holdout_freeze_<date>.md` (WP1).** It is a PREREG-semantics change, so it goes through a ruling, peer-reviewed by mle-reviewer and prediction-market-reviewer. It is not an operator question. It freezes the sealed set as a **fixed** interval:
- `SEALED_HOLDOUT_START = 2026-07-01`, `SEALED_HOLDOUT_END_EXCLUSIVE = 2026-10-02` (= FQ v1 `d0_climate_day`), at the 4 stations: about 93 days × 4 ≈ 372 station-days before gaps.
- Rationale: the PM.us leg is already terminal (node 4), so the set's remaining consumer is the K-2 weather-only S2, which receives a fixed, never-trained-on set. A growing holdout would forbid every refit at these stations forever.
- Fallback if the reviewers reject the freeze: Option B, AUT-1 widens NBP plus CLI ingest to non-traded US stations. EMOS `(a_v, γ_v)` are per-version and pooled across stations, so post-July rows from stations outside the sealed set could train v5.0 without touching it. The ETA moves (§6). The C2 consumer would still be blocked until a freeze.
- The ruling carries one fenced block `aut3-refit/v1` (strict JSON, exact-set keys): the two sealed bounds, `ROLLING_V5_DAYS = 365`, `SHRINK_PRIOR_CLUSTERS_N0 = 100`, `REPRO_SAMPLE_BYTE_THRESHOLD = 26` (about 10%), `REPRO_MIN_PER_ISO_WEEK = 1`, `REPRO_MAX_PER_RUN = 1`, `PROBE_GRID_STEP = 0.01`. The values are proposals for the ruling's own review. `windows.py` holds them as `Final` literals, and a test asserts equality with the ruling block, mirroring `test_live_orders_ruling_deploy_copy_matches_evidence`.

**`RefitWindow` for a run started at `created_at` on UTC day D** (`analysis/autonomy_refit/windows.py::compute_refit_window`):
- `train_end_exclusive_utc = D 00:00Z`. Only FINAL CLI rows whose `issued_at_utc < train_end_exclusive_utc`, and NBP rows whose `available_at_ns < train_end_exclusive_utc`, are eligible.
- `forward_eval_start_utc = (D+1) 00:00Z`, which is ≥ `created_at`.
- density_table rows: v4.x on their DEFAULT_SPLITS train/validate days (unchanged); v5.0 on `v5_fit_slice` (2026-05-04..06-30) **∪** rolling days `[max(SEALED_HOLDOUT_END_EXCLUSIVE, train_end − ROLLING_V5_DAYS), train_end)`. A sealed day is never in either set.
- rung_recalibration rows: C2 labels with `admissible=True`, `source=live`, `drill=false`, `reconciled=True`, settlement `climate_day ≥ SEALED_HOLDOUT_END_EXCLUSIVE`, `labelled_at_ns < train_end_exclusive_utc`, and decision artefact equal to the parent (§3.4).

**Cadence.** One run a day at 06:00Z. Each lineage gets **at most one C3 record per UTC day**, which is how AUT-3 honours `MAX_MINTS_PER_LINEAGE_PER_DAY ≤ 1`: the engine mints every eligible C3 and enforces the same ceiling. The deterministic **component selection rule** (`driver.py::select_component`):
1. Preferred = `rung_recalibration` on odd `date.toordinal()`, else `density_table`.
2. `rung_recalibration` is attempted only if its admissible label set is non-empty **and** its sha differs from that of the most recent `rung_recalibration` C3 in the lineage.
3. If the preferred component returns `NOT_FITTABLE` or `NO_CHANGE` (bytes equal to an existing artefact), the other is attempted.
4. If both do, the day records `NO_CHANGE` (exit 0, INFO), and the live-proof streak breaks; see §6.

### 3.4 Estimators

**density_table** (`fq_density_refitter.py::FqDensityTableRefitter`):
- Rows come from `rolling_version_rows(...)`, which delegates to `nbp_skill_study.build_version_rows` (`:661`) and tags rolling rows `split="v5_fit_slice"`. How the tagging coexists with `Splits` validation (contiguity, `split_for_date` raising, `nbp_calibration.py:270`) is **INFERRED**. WP0 picks either a `Splits` instance with `holdout_start = train_end` and pre-filtered windows, or a post-build `dataclasses.replace(row, split=…)`. A test asserts that no sealed day reaches the fit under either path.
- Then `fit_calibration(rows, method=CdfMethod(parent.cdf_method), bootstrap_seed=lineage.seed)` with `seed = BOOTSTRAP_SEED` (fixed, recorded), followed by `artefact_from_calibration_fit` with the parent's `CorrectionSelection` reconstructed from the parent artefact. Recalibration is `none`. `n_min`/`sigma_d` are carried.
- Contingency, decided in WP0 and recorded in the ruling: if the measured full-fit p95 runtime exceeds 90 min or peak RSS exceeds 12 GiB, use the v5.0-only conditional refit instead. That variant refits v5.0 by `fit_version_unshrunk` and shrinks it toward the frozen LOVO pooled mean at the parent's κ, keeping the parent's δ.

**rung_recalibration** (`fq_rung_recal_refitter.py::FqRungRecalibrationRefitter`):
- **Parent binding.** The parent is the champion artefact P (from the registry fold), with `P.recalibration == "none"`. Labels whose C1 `DecisionRecord.artefact_sha256 ≠ P.sha` are excluded with reason `label_from_other_artefact`. If P is itself recalibrated, its labels' `p_at_decision` are post-recalibration, so the base probability is not recoverable. Those labels are excluded with reason `p_post_recalibration`, and the refitter returns `NOT_FITTABLE(parent_recalibrated)` (contradiction 3, §8).
- **Estimator `fit_shrunk_affine(points, prior_n0)`.** Each station-day cluster c has weight 1, split equally across its labels (L-40), so `n_eff` = the number of clusters. θ_LS = cluster-weighted least squares of `y` on `p` (the weighted analogue of `_fit_affine`; the degenerate `denom=0` case gives `(ȳ_w, 0)`). θ = `(n_eff/(n_eff+N0))·θ_LS + (N0/(n_eff+N0))·(0, 1)`. Output is `recalibration="affine"`, `recalibration_affine=(intercept, slope)`. It is closed-form with no RNG, so it is bit-reproducible. Applied with the existing semantics: clip to [0,1] per rung, then renormalise the partition (`apply_probability_recalibration`).
- **Inputs are exactly `(p_at_decision, settled_outcome, station, climate_day)`.** The ask, fill price, fee and slippage are never read (AST test).
- **Canonical identity.** θ = (0,1) exactly is written as `recalibration="none"`, `recalibration_affine=None`.
- **Ablation (X22).** The same refit with the label set left out gives θ = (0,1), which canonicalises to `none`, so the ablation bytes equal P's bytes and `ablation_artefact_sha256 = P.sha`. The C3 writer refuses if `artefact_sha256 == ablation_artefact_sha256`. It **also** requires the functional assertion `own_outcome_changes_probabilities` (max |g(p) − p| > 0 over the probe grid p ∈ {0.01, …, 0.99}), so a byte-only difference (for example in metadata) can never satisfy X22.

### 3.5 Lineage, inputs snapshot and leakage assertions

**Inputs snapshot** (`inputs.py::snapshot_rows`). Every source's selected rows are serialised canonically: explicit columns, sorted by `(station, climate_day, cycle_runtime_ns)` or `(label_id, label_seq)`, written as parquet with fixed writer options to `~/.local/share/breezy/derived/refit/inputs/<content_sha256>.parquet` (0444, dir 0500), where the sha covers the canonical row bytes. `data_windows[]` = `{source ∈ {nbp_derived, settlement_truth, c2_labels}, start_utc, end_exclusive_utc, rows, content_sha256}`. Sources grow and CLI rows can be revised, so reproduction reads the **snapshot**, never the live source.

**C3 `lineage/v1` fields as filled by AUT-3:**
- `model_class` as in §3.1; `lineage_root_family_id` from the parent's C5 row; `parent_artefact_sha256`.
- `code_git_sha` = HEAD; `build_sha` as ARCH-0 defines it; `producer_code_sha` = the closure hash for producer id `aut3_refit` (§4.3, extended in contradiction 8).
- `params`: `{component, cdf_method, seed, bootstrap_draws, rolling_v5_days, shrink_prior_n0, n_eff, n_labels, estimator_variant, numpy, scipy, pyarrow, python, uv_lock_sha256}`.
- `seed`; `fit_status="OK"`; `data_windows`; `own_outcome_label_set_sha256` (sha of sorted `(label_id, label_seq)`); `ablation_artefact_sha256`; `train_end_exclusive_utc`; `forward_eval_start_utc`.
- `leakage_assertions`; `recalibration` and `correction_form` (members of the live accepted set); `created_at_ns`, `runtime_s`, `peak_rss_bytes` (from `resource.getrusage`).

**`leakage_assertions`** (`leakage.py`). Each returns `{name, passed}`, and **any `passed=false` means no write, a CRITICAL alert and exit 2**:

| Name | Asserts |
|---|---|
| `ref_ts_lt_take_ts` | density_table: every row's NBP `available_at_ns` < the D+1 decision cutoff of its climate day (the `local_standard_date` + 1 rule `build_version_rows` uses); rung_recal: every label's C1 `eval_ns` < its fill `ts`, and the fill `ts` < the settlement issuance |
| `train_end_lt_forward_eval_start` | `train_end_exclusive_utc ≤ forward_eval_start_utc` and `forward_eval_start_utc ≥ created_at` |
| `no_sealed_holdout_rows_in_train` | no `(station, climate_day)` with `climate_day ∈ [SEALED_HOLDOUT_START, SEALED_HOLDOUT_END_EXCLUSIVE)` in any snapshot |
| `labels_settled_before_train_end` | every row's FINAL issuance < `train_end_exclusive_utc` |
| `p_at_decision_matches_capture` | C2 `p_at_decision` is bit-equal to the joined C1 `DecisionRecord.p_hat`, so no p was recomputed after the fact |
| `labels_bound_to_parent_artefact` | every training label's decision artefact equals `parent_artefact_sha256` |
| `admissible_only` | every training label has `admissible ∧ reconciled ∧ source=live ∧ ¬drill` (C2 invariants; canary and drill rows are never training rows) |
| `parent_bytes_preserved` | rung_recal: every non-recalibration field is byte-equal to the parent's JSON |
| `own_outcome_changes_probabilities` | rung_recal: the functional X22 delta from §3.4 is > 0 |

### 3.6 C3 writer and store (`c3_writer.py::write_candidate`)

- Writes `~/.local/share/breezy/derived/artefacts/<model_class>/<artefact_sha256>/{artefact.json, lineage.json}` atomically (`mkstemp` + `os.replace`, then `chmod 0444` on files and `0500` on the directory). Paths go through the single-read rule with `O_NOFOLLOW` on every component.
- **Refuses:** `fit_status ≠ OK`; any failed assertion; `ablation == artefact` when own outcomes are used; `recalibration ∉ REFIT_EMITTABLE_RECALIBRATION_FORMS`; `correction_form ∉ _SUPPORTED_CORRECTION_FORMS`; a second C3 for the same `lineage_root_family_id` on the same UTC day; any path inside the repo or `deploy/families` (reusing the G13 guard logic).
- **No new lineage for an existing sha** (the C3 no-new-lineage rule): if the directory exists, nothing is written and the status is `NO_CHANGE`. That covers the AUT-7b drill child, which never comes through AUT-3.
- Artefact bytes use `artefact_json`, the bytes `write_artefact` writes, so `sha256(artefact.json) == artefact_sha256` by construction.

### 3.7 Driver, units and stall watch

**Plug-in.** `analysis/autonomy_refit/plugin.py::FqRefitter` implements C6 `Refitter.refit(windows) -> (artefact, Lineage) | NOT_FITTABLE(reason)` and returns at most one artefact per call. It is registered in `OFFLINE_PLUGINS[forecast_quantile_ladder]`. Kinds with `RefusingPlugin` return `NOT_FITTABLE(refusing_plugin)`.

**Driver** (`driver.py::run_daily(now, registry_reader, c2_reader, plugins, sink)`):
1. Computes its own producer closure hash and refuses unless it is in `PRODUCER_SOURCE_SHA256["aut3_refit"]` (CRITICAL, exit 3).
2. Reads the verified per-venue fold read-only (resolver, `mode=ro`). For every venue champion, or the last RETIRED champion after a KILL (ARCH §5.3), and for every lineage root in `_LINEAGE_POLICY_ALLOWLIST`, resolves the plug-in by `composition_kind`.
3. Calls `select_component` and then `refit`, writes C3, and writes `evidence/refit/refit_run_<YYYY-MM-DD>.json`.
4. Logs `REFIT_RESULT lineage=<id> model_class=<mc> status=<CANDIDATE|NO_CHANGE|NOT_FITTABLE|SKIPPED_LOCK> artefact_sha256=<sha|-> own_outcome_labels=<n> n_eff=<k>`.
- An unreadable registry is CRITICAL with no refit. An unreadable or unknown-version C2 is CRITICAL, rung_recal becomes `NOT_FITTABLE(c2_unreadable)`, and density_table still runs. "Nothing to do" exits 0 with a `NO_INPUT` line.

**`refit_run/v1`** (new evidence record, contradiction 8). Fields: `schema`, `run_date`, `started_at_ns`, `finished_at_ns`, `producer_code_sha`, `results[]` of `{lineage_root_family_id, composition_kind, model_class|null, status, reason|null, artefact_sha256|null}`, `peak_rss_bytes`. It is exact-set, written atomically at 0444, and carries no paths or env values (payload hygiene).

**CLI entry points (thin):** `scripts/analysis/autonomy_refit_daily.py` and `scripts/analysis/autonomy_refit_reproduce.py`. Both use the exact interpreter `/home/jon/breezy/.venv/bin/python`.

**Units** in `deploy/systemd/`:

`breezy-autonomy-refit.service`:
- `Type=notify`, `NotifyAccess=main`, `WatchdogSec=1200`.
- `Slice=breezy-studies.slice`, `OnFailure=breezy-study-failed@%n.service`.
- `MemoryHigh=3G`, `MemoryMax=4G` initially (same data scale as the 4G nightly; WP0 resizes to `max(4G, 1.5 × measured peak)` ≤ 16G and moves the slot if it exceeds 4G).
- `RuntimeMaxSec=12600` (≤ 30 min lock wait plus ≤ 3 h fit, ending ≤ 09:30Z, before AUT-4's 11:00Z slot and well before 16:30Z).
- `TimeoutStartSec=120` (READY is sent first).
- `Environment=OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONHASHSEED=0`, for bit-reproducibility.
- `EnvironmentFile=-%h/.config/breezy/alerts.env` only, never `operator.env` or venue credentials (G27). `UMask=0077`.

`breezy-autonomy-refit.timer`: `OnCalendar=*-*-* 06:00:00 UTC`, `Persistent=true`, `AccuracySec=1min`.

`breezy-autonomy-refit-reproduce.{service,timer}`: same shape, `09:30Z`, `RuntimeMaxSec=12600`, lock wait 3600 s.

**Stall watch and lock.**
- The process sends `READY=1`, then acquires `breezy-studies.lock` with `fcntl.flock` polled for up to `STUDIES_LOCK_WAIT_S = 1800`, pinging `WATCHDOG=1` throughout. It reuses a repo helper if WP0 finds one, else `analysis/autonomy_refit/locks.py`.
- A lock timeout writes `status=SKIPPED_LOCK`, exits 0 with a WARN, and becomes CRITICAL on the second consecutive day.
- During the fit it pings at every stage boundary and every 10 bootstrap draws via a progress callback, and logs `REFIT_PROGRESS stage=<s> draws=<k>/<B> rss_mb=<m>`.
- With no ping for 1200 s, systemd kills the unit (result `watchdog`), which is the no-progress event, and `OnFailure` alerts. `RuntimeMaxSec` is the backstop.
- Whether `WatchdogSec` behaves as expected for this notify-then-exit batch shape is **INFERRED**. WP0 drills it with a throwaway `systemd-run --user -p Type=notify -p WatchdogSec=30` script that stops pinging.

**Reproducibility sample** (`reproduce.py`):
- Sample = every C3 created in the last 7 days whose `artefact_sha256` first byte < `REPRO_SAMPLE_BYTE_THRESHOLD`, plus the newest C3 of the ISO week if none was sampled that week. Capped at `REPRO_MAX_PER_RUN = 1`, oldest first.
- Reproduction re-runs the **full** refit from the lineage's input **snapshots**, at the recorded `code_git_sha`, extracted with `git archive <sha> | tar -x` into `~/.cache/breezy/refit-repro/<sha>/`. That is read-only, not a worktree. It runs with the shared interpreter and `PYTHONPATH` set to the extract, and first verifies that the extract's closure hash equals `producer_code_sha`.
- An equal sha gives `REPRO_PASS`. A mismatch gives `REPRO_MISMATCH` (CRITICAL through `deliver_with_proof`, exit 1). A differing `uv_lock_sha256` gives `REPRO_ENV_CHANGED` (WARN, not counted as a pass).
- The result goes to `evidence/refit/repro_<date>.json` (inside `refit_run/v1`, `kind=repro`).
- **Interpretation (contradiction 7):** the "sampled subset" is a sample of candidates, each refit in full. A data subset cannot reproduce a sha.

### 3.8 Live loader widening (G11)

New `src/breezy/strategy/ladder_ev/rung_recalibration.py`:
- `@dataclass(frozen=True, slots=True) RungRecalibration(form: Literal["none","affine"], affine: tuple[float,float] | None)`.
- `apply(probabilities: Mapping[str,float]) -> dict[str,float]` mirrors `_apply_recalibration_scalar` and `apply_probability_recalibration` exactly: clip, renormalise, assert the sum is 1 within 1e-12.
- `REFIT_EMITTABLE_RECALIBRATION_FORMS: Final = frozenset({"none","affine"})`.

`fq/calibration_artefact.py`:
- `_SUPPORTED_RECALIBRATION` becomes `frozenset({"none","affine"})`, imported from the constant above, so the accepted set **equals** the emit set (L-12 equality, never a subset test).
- `affine` requires `recalibration_affine` = 2 finite floats with slope ≥ 0.
- `none` with non-null `recalibration_affine` is refused as inconsistent. `isotonic` and every unknown form stay refused.
- `LiveCalibration` gains `recalibration: RungRecalibration`.

`quantile_density.rung_probability_interval` gains keyword `recalibration: RungRecalibration | None = None`, applied to each draw's `rung_probabilities` before the percentile step. With `None` or `form="none"` the output is bit-identical to today's.

`ArtefactBoundsProvider.__init__` gains `recalibration`, and `fq/composition.py::build_forecast_quantile_ladder_strategies` passes `live_calibration.recalibration`. `scripts/analysis/nbp_shadow_parity.py` passes it too.

**The re-targeted safety test (contradiction 10).** `test_unsupported_probability_recalibration_is_refused` (`tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py:191-196`) uses `"affine"` as its unsupported example. Under this reviewed L-12 widening it is **re-targeted** to `"platt"` and `"isotonic"`, and four new refusal tests are added (§4 WP2). It is not deleted, and the refusal comparison is not loosened.

---

## 4. Work packages

**Common gate (G)**, run after every merge, full gate (L-43). Read the exit code, never `-q` output (memory `pytest-q-doubles-into-qq`).
- `scripts/ci/run_tests_no_egress.sh` with `/home/jon/breezy/.venv/bin/python` and `PYTHONPATH=<tree>/src:<tree>` in a worktree (memory `worktree-needs-pythonpath`).
- `cd <tree> && /home/jon/breezy/.venv/bin/lint-imports` must print `N kept, 0 broken`.
- `cd <tree> && /home/jon/breezy/.venv/bin/python -m mypy` plus `tests/unit/test_mypy_ratchet.py`, with new packages added to `[tool.mypy] files`. Grep `tests/` for pins of that list first (L-54).
- **Never** `uv`, `uv run`, `pip` or `git stash`. Each agent uses its own scratchpad.

| WP | Scope and files | RED tests first (path::name) | GREEN criterion | Activation |
|---|---|---|---|---|
| **AUT-3.WP0** L-1 checks and benchmark (read-only plus one capped run) | No source change. Evidence to `docs/evidence/AUT3_WP0_<date>.md`. **(i)** `Splits` invariants and the rolling tagging option (§3.4). **(ii)** One full `fit_calibration` on current rows inside `systemd-run --user -p MemoryMax=16G -p RuntimeMaxSec=14400 -p LimitNOFILE=524288`, outside 01:00–04:30Z and with no other study running: peak RSS, wall time, swap. **(iii)** The `Type=notify`/`WatchdogSec` drill. **(iv)** Two same-input runs give an identical sha with threads=1. **(v)** Whether a Python flock helper exists. **(vi)** That the champion artefact equals the registry BOOTSTRAP sha (`9c0b6d…`). | characterisation item, no RED (L-33); mutation evidence: changing the seed changes the sha | Numbers recorded; contingency decided against the 90 min / 12 GiB thresholds | none |
| **AUT-3.WP1** Window ruling and constants | `docs/evidence/RULING_aut3_refit_windows_and_holdout_freeze_<date>.md` (with the `aut3-refit/v1` block); `src/breezy/analysis/autonomy_refit/__init__.py`, `windows.py` | `tests/unit/autonomy_refit/test_aut3_ruling_pins.py::test_window_constants_equal_ruling_block`; `::test_ruling_block_is_exact_set_strict_json`; `tests/unit/autonomy_refit/test_windows.py::test_sealed_days_never_in_density_or_label_window`; `::test_train_end_is_run_day_midnight_and_forward_start_next_day`; `::test_rolling_v5_window_floor_is_seal_end` | Ruling peer-reviewed by mle-reviewer and prediction-market-reviewer to SOUND; tests green; G green | ruling filed on merge |
| **AUT-3.WP2** G11 widening plus live application | `strategy/ladder_ev/rung_recalibration.py` (new); `fq/calibration_artefact.py`; `strategy/ladder_ev/quantile_density.py`; `fq/artefact_bounds.py`; `fq/composition.py`; `scripts/analysis/nbp_shadow_parity.py` | `tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py::test_affine_recalibration_is_accepted_and_parsed`; `::test_unknown_probability_recalibration_is_refused` (re-targeted); `::test_isotonic_recalibration_is_refused_live`; `::test_affine_missing_or_nonfinite_coefficients_is_refused`; `::test_none_with_affine_coefficients_is_refused`; `tests/unit/test_refit_emit_set_equals_live_accept_set.py::test_emittable_recalibration_forms_equal_live_supported`; `tests/unit/test_fq_live_analysis_point_cdf_parity.py::test_live_affine_recalibration_matches_analysis_apply_probability_recalibration` (≤1e-12 per rung, 200 seeded draws × 3 CDF methods × 2 ladders); `tests/unit/test_ladder_ev_quantile_density.py::test_recalibration_applied_per_draw_before_interval`; `::test_none_recalibration_is_bit_identical`; `tests/strategy/forecast_quantile_ladder/test_artefact_bounds.py::test_provider_forwards_recalibration`; `tests/strategy/forecast_quantile_ladder/test_sl13_wiring.py::test_composition_passes_artefact_recalibration`; L-55: `::test_committed_champion_loads_through_production_loader_with_none` | Parity ≤1e-12; the champion's bounds are bit-identical to pre-change; G green; security-reviewer and python-reviewer sign off the safety-test re-target | Behaviour-neutral for the champion (`recalibration=none`, bit-identical test). It takes effect at the next supervisor LAUNCH (16:50Z). Stated reason for not relaunching mid-day: no behaviour change, and a hand relaunch carries the AMBIGUOUS-intent and permit risk (memories `node-refused-on-terminal-leaves`, `hand-relaunch-mechanics`). |
| **AUT-3.WP3** Snapshot, leakage, C3 writer | `analysis/autonomy_refit/inputs.py`, `leakage.py`, `c3_writer.py` | `tests/unit/autonomy_refit/test_inputs_snapshot.py::test_snapshot_sha_independent_of_input_order`; `::test_snapshot_files_are_0444_and_nofollow`; `tests/unit/autonomy_refit/test_leakage.py::test_sealed_row_fails_no_sealed_holdout_rows_in_train`; `::test_forecast_available_after_cutoff_fails_ref_ts_lt_take_ts`; `::test_label_after_train_end_fails`; `::test_p_at_decision_not_equal_capture_fails`; `::test_train_end_after_forward_start_fails`; `::test_canary_drill_unreconciled_rows_fail_admissible_only`; `tests/unit/autonomy_refit/test_c3_writer.py::test_writes_content_addressed_0444_0500`; `::test_refuses_any_failed_assertion`; `::test_refuses_ablation_equal_to_artefact`; `::test_refuses_own_outcome_without_functional_delta`; `::test_refuses_non_ok_fit_status`; `::test_existing_sha_writes_no_new_lineage`; `::test_refuses_symlink_anywhere_on_path`; `::test_refuses_recalibration_outside_live_accept_set`; `::test_second_c3_same_lineage_same_utc_day_refused`; `::test_refuses_repo_and_deploy_families_roots`; `::test_payload_hygiene_no_paths_or_env` | All refusals proven RED→GREEN; G green | library only |
| **AUT-3.WP4** density_table refitter | `analysis/autonomy_refit/rows.py` (rolling tagging), `fq_density_refitter.py` | `tests/unit/autonomy_refit/test_fq_density_refitter.py::test_refit_changes_only_v5_params_draws_kappa`; `::test_bit_for_bit_reproducible_from_snapshot`; `::test_rolling_rows_exclude_sealed_holdout_under_both_paths`; `::test_no_new_rows_returns_no_change`; `::test_carries_parent_correction_and_recalibration_none`; `::test_lineage_records_windows_code_params_seed`; `::test_nonconverged_fit_writes_nothing`; `::test_progress_callback_called_per_10_draws` | Fixture fit reproducible; G green | library only |
| **AUT-3.WP5** rung_recalibration refitter (the C2 consumer) | `analysis/autonomy_refit/fq_rung_recal_refitter.py` | `tests/unit/autonomy_refit/test_fq_rung_recal_refitter.py::test_leave_labels_out_changes_artefact_sha` (X22); `::test_ablation_bytes_equal_parent_bytes`; `::test_shrunk_affine_matches_closed_form`; `::test_cluster_weights_sum_to_one_per_station_day`; `::test_labels_from_other_artefacts_excluded_by_name`; `::test_parent_recalibrated_returns_not_fittable`; `::test_inadmissible_canary_drill_labels_never_train`; `::test_emos_block_byte_equal_to_parent`; `::test_no_admissible_labels_not_fittable`; `::test_refitter_reads_no_venue_price_fields` (AST: no `entry_ask`, `fill_px`, `slippage`, `fee_reconciled`); `::test_identity_canonicalised_to_none` | C2 fixture **written through the real AUT-2 label writer** (L-42); G green | library only |
| **AUT-3.WP6** Plug-in, driver, CLI | `analysis/autonomy_refit/plugin.py`, `driver.py`, `locks.py`, `sd_notify.py`; `scripts/analysis/autonomy_refit_daily.py`; the `pins.py` entry `PRODUCER_SOURCE_SHA256["aut3_refit"]` | `tests/unit/autonomy_refit/test_driver.py::test_every_live_gate_routed_kind_has_a_fitting_refitter`; `::test_refusing_plugin_kind_not_fittable_and_never_writes_c3`; `::test_select_component_alternates_and_falls_back`; `::test_at_most_one_c3_per_lineage_per_utc_day`; `::test_registry_unreadable_critical_no_refit`; `::test_c2_unreadable_runs_density_and_alerts`; `::test_nothing_to_do_exits_zero_no_input_line`; `::test_refit_run_record_exact_set_and_hygiene`; `::test_producer_pin_mismatch_refuses_exit_3`; `::test_critical_alerts_go_through_deliver_with_proof`; L-55: `::test_run_daily_with_production_default_seams` (tmp store, real resolver on a tmp registry, real NOTIFY_SOCKET); envelope (ARCH-0 tests extended to the new package): `test_autonomy_never_reads_or_writes_operator_controls`, `test_autonomy_never_imports_order_path`, `test_autonomy_payload_hygiene_scan`, `test_code_identity_pins_cover_import_closure` | G green; pin committed in the same commit as the closure | library plus CLI |
| **AUT-3.WP7** Units, schedule, stall watch, activation | `deploy/systemd/breezy-autonomy-refit.{service,timer}`; README unit table | `tests/unit/test_analysis_units_memory_capped.py::test_autonomy_refit_units_capped_and_bounded` (MemoryMax, RuntimeMaxSec, Type=notify, WatchdogSec, Slice, OnFailure, alerts.env only, thread env); `tests/unit/autonomy_refit/test_schedule.py::test_refit_ends_before_1630z_and_avoids_0100_0430`; `::test_sd_notify_pings_watchdog_on_progress` (real socket); `::test_lock_timeout_records_skipped_lock_warn_then_critical` | G green; `systemd-analyze --user verify` clean | **Immediate on merge:** symlink the unit and timer, `daemon-reload`, `enable --now breezy-autonomy-refit.timer`; confirm `breezy-studies.slice -p MemoryMax` is not `infinity` (B4). The timer installs before AUT-2 C2 exists; rung_recal reports `NOT_FITTABLE(c2_absent)`. |
| **AUT-3.WP8** Reproducibility job | `analysis/autonomy_refit/reproduce.py`; `scripts/analysis/autonomy_refit_reproduce.py`; `deploy/systemd/breezy-autonomy-refit-reproduce.{service,timer}` | `tests/unit/autonomy_refit/test_reproduce.py::test_reproduce_from_snapshot_and_git_archive_matches_sha` (tmp git repo fixture); `::test_mismatch_critical_exit_1`; `::test_env_changed_classified_not_pass`; `::test_sample_rule_deterministic_and_weekly_forced`; `::test_extract_closure_hash_must_equal_producer_code_sha`; units test row added to `test_analysis_units_memory_capped.py` | G green | Immediate on merge: install and enable `breezy-autonomy-refit-reproduce.timer` |
| **AUT-3.WP9** Live-proof report | `scripts/analysis/aut3_live_proof_report.py` (read-only) | `tests/unit/autonomy_refit/test_live_proof_report.py::test_streak_counts_only_qualifying_days`; `::test_streak_breaks_on_no_change_or_skip`; `::test_requires_own_outcome_candidate`; `::test_requires_aut4_verdict_citing_candidate_sha`; `::test_requires_one_repro_pass_in_window` | G green | Run by hand only by the independent scorer; no timer (an evidence tool, not a control) |

---

## 5. Association

| Contract | Direction | Exact interface |
|---|---|---|
| C1 | consumed (AUT-1) | `DecisionRecord.{decision_id, eval_ns, p_hat, artefact_sha256}`, read through ARCH-0's C1 reader, read-only |
| C2 | consumed (AUT-2) | `label/v1` via ARCH-0's reader: `{label_id, label_seq, decision_id, station, climate_day, p_at_decision, settled_outcome, admissible, reconciled, excluded_reason, labelled_at_ns}` plus `source`/`drill`. Unknown version means refuse. |
| C3 | **provided** | `derived/artefacts/<model_class>/<sha>/{artefact.json, lineage.json}`, at most one per lineage per UTC day |
| C4 | none written | AUT-3 writes no verdict. AUT-6's `refit_freshness` (no `refit_run` by 12:00Z, or `status ∉ {CANDIDATE}` for 2 consecutive days) and `refit_repro` (`REPRO_MISMATCH`) VERDICT detectors map these to `HEALTH` |
| C5 | consumed (AUT-5) | Read-only fold: per-venue champion, `lineage_root_family_id`, bound `artefact_sha256`. AUT-5's engine writes MINT ∅→SHADOW from each eligible C3, honouring the mint and K_max ceilings. AUT-3 never writes the registry. |
| C6 | **provided** | `Refitter` for `forecast_quantile_ladder` in `OFFLINE_PLUGINS`; `RefusingPlugin` for the rest |
| Delivery | consumed (AUT-6) | `runtime/alert_delivery.py::deliver_with_proof` |
| AUT-4 | downstream | Reads every new C3 (as `inputs[{path_role: candidate_artefact, sha256}]`) and emits `OFFLINE_CHALLENGER` for the minted SHADOW family, and later `FORWARD_SHADOW`, using `forward_eval_start_utc` from the lineage |
| AUT-7 | downstream | Re-verifies `sha256(artefact.json)` on rollback |

**Execution order.** ARCH-0 must merge first. Then:
- Wave 1, in parallel with AUT-1, AUT-6 and AUT-5a, and **disjoint from their files**: WP0, WP1, WP3, WP4.
- Wave 2, after AUT-2b: WP5 and WP6.
- WP2 runs after AUT-1's and AUT-5a's edits to `fq/strategy.py` and `fq/composition.py` merge. It touches `composition.py`, so it is serialised behind them and rebased (memory `agent-worktrees-start-stale`).
- WP7 after WP6. WP8 after WP7. WP9 after the AUT-4 offline consumer is live.
- WP3 and WP4 can run in parallel with each other. WP5 and WP2 can run in parallel.

---

## 6. Live-proof protocol

**Artefacts that prove score 3:**
1. Seven C3 directories, one per qualifying day, under `~/.local/share/breezy/derived/artefacts/forecast_quantile_ladder:{density_table|rung_recalibration}/<sha>/`, each with every `leakage_assertions[].passed = true`.
2. `evidence/refit/refit_run_<date>.json` for each of those days, `status=CANDIDATE`.
3. journald `REFIT_RESULT … status=CANDIDATE` lines from `breezy-autonomy-refit.service`, started by the timer (`systemctl --user show -p TriggeredBy`).
4. For each candidate, an AUT-4 C4 verdict under `derived/verdicts/<family_id>/…` whose `inputs[]` cites the candidate sha, plus the AUT-5 MINT row citing the same `artefact_sha256`.
5. At least one `rung_recalibration` C3 with `own_outcome_label_set_sha256 ≠ null`, `ablation_artefact_sha256 ≠ artefact_sha256` and `own_outcome_changes_probabilities = true`.
6. At least one `REPRO_PASS` in `evidence/refit/repro_<date>.json` inside the window.
7. The WP9 report `~/.local/share/breezy/evidence/refit/aut3_live_proof_<date>.md`.

**Window rule (§5.3).** A day counts only with ≥1 real fill or a production-path canary fill, and the window needs ≥5 real fills. Zero-fill days extend the window. A `NO_CHANGE`, `SKIPPED_LOCK` or failed run on a qualifying day **breaks** consecutiveness. Canary and drill labels never train (`admissible_only`).

**Failure-mode drills for (d).** Each is a one-shot `systemd-run --user` invocation of the production script with a `--drill <kind>` CLI flag. Drill runs never write C3, tag `refit_run.drill=true`, and are refused unless the flag is set:
- `stall`: stops pinging, so the watchdog kills the unit.
- `lock`: a held lock gives `SKIPPED_LOCK`.
- `oom`: allocates past `MemoryMax`.
- `repro-mismatch`: runs on a tampered **copy** of a snapshot.
- `pin`: runs with an unpinned closure in a scratch extract.

Delivery for each is proven by AUT-6's `evidence/alerts/delivery_<date>.jsonl` showing `delivered=true`, a 2xx.

**Accrual ETA.**
- ARCH-0 by about 10-10. Wave 1 by about 10-17. AUT-2b C2 with `p_at_decision` by about 10-24. The AUT-4 offline consumer and engine MINT (Wave 3) by about 11-07.
- At about 5 fills a day most days qualify, so **earliest DONE is 2026-11-14 and the planning ETA is 2026-11-21**, about 9 weeks before the 2027-01-25 KILL.
- The streak cannot count before AUT-4 consumption is live (contradiction 11).
- If the holdout-freeze ruling is rejected and Option B is needed, add AUT-1's ingest widening plus backfill: ETA about 2026-12-15. The C2 consumer then stays blocked until a freeze, so the own-outcome leg of the live proof would be unreachable. That would be reported as score 2, never claimed as 3.

**Evidence class: machinery proven, edge unproven.** No edge verdict is pre-registered for AUT-3. Promotion of any candidate is AUT-4/AUT-5's question and is expected to be UNDERPOWERED.

---

## 7. Score-3 verification checklist (for an independent scorer)

| Criterion | Exact check |
|---|---|
| (a) unattended | `journalctl --user -u breezy-autonomy-refit.service --since <W0> --until <W7> \| /usr/bin/grep -c 'REFIT_RESULT .*status=CANDIDATE'` ≥ 7 on qualifying days; `systemctl --user show breezy-autonomy-refit.service -p TriggeredBy` = the timer; `git log --since=<W0> -- deploy/families src/breezy/strategy/forecast_quantile_ladder` shows no artefact or manifest commit in the window |
| (b) family-agnostic | Gate tests `test_driver.py::test_every_live_gate_routed_kind_has_a_fitting_refitter`, `::test_refusing_plugin_kind_not_fittable_and_never_writes_c3`, ARCH-0 `test_family_plugin_exact_set`; each `refit_run_<date>.json` `results[]` lists every non-RETIRED lineage root |
| (c) fails closed | Gate tests in WP3 (`test_c3_writer.py::*refuses*`), WP2 (loader refusals), WP6 (`::test_registry_unreadable_critical_no_refit`, `::test_producer_pin_mismatch_refuses_exit_3`); live: `jq '[.leakage_assertions[].passed]\|all' lineage.json` = true for every C3 in the window |
| (d) detected and delivered | For each drill kind in §6: the journal line (`watchdog`, `SKIPPED_LOCK`, `oom-kill`, `REPRO_MISMATCH`, `PIN_MISMATCH`), the `breezy-study-failed@` instance log or direct CRITICAL, and a `delivered=true` row in `evidence/alerts/delivery_<date>.jsonl` with the matching `event` |
| (e) RED→GREEN | For each WP: the RED run log and GREEN run log stored with the merge, plus the commit SHAs; the full gate exit 0 after every merge |
| (f) live proof | `scripts/analysis/aut3_live_proof_report.py --since <W0>` outputs `STREAK=7 QUALIFYING_FILLS>=5 OWN_OUTCOME_CANDIDATE=<sha> AUT4_CONSUMED=7/7 REPRO_PASS>=1`; the scorer independently re-hashes each `artefact.json` and confirms that the cited C4 verdicts and MINT rows exist |
| Lineage completeness | each `lineage.json` has non-null `data_windows[].content_sha256` and `code_git_sha`, `producer_code_sha`, `params`, `seed`; each snapshot file exists and re-hashes |
| Loader parity | `pytest tests/unit/test_fq_live_analysis_point_cdf_parity.py::test_live_affine_recalibration_matches_analysis_apply_probability_recalibration tests/unit/test_refit_emit_set_equals_live_accept_set.py` exit 0 |

---

## 8. Risks, failure modes and contradictions with ARCH

**Contradictions with ARCH and the README (to be fed back to ARCH Rev 4):**
1. **Sealed holdout vs rolling and own outcomes.** The growing v5.0 holdout makes `no_sealed_holdout_rows_in_train`, a rolling window and C2 consumption jointly unsatisfiable at the only 4 ingested stations. ARCH is silent on this. It is resolved by the WP1 freeze ruling, with Option B as fallback.
2. **Mint ceiling vs two model classes.** AUT-3 writes ≤1 C3 per lineage per day using the alternation rule (§3.3). Each class is therefore refit every other day at best, not daily.
3. **C2 `p_at_decision` is post-recalibration** when the deciding artefact is recalibrated. Own-outcome refits stop after a recalibrated champion unless C1 and C2 add a `p_base_at_decision` field. That is an ARCH change. Until then, `NOT_FITTABLE(parent_recalibrated)`.
4. **X22 sha-inequality alone is vacuous or gameable.** AUT-3 adds identity canonicalisation and the functional assertion `own_outcome_changes_probabilities`.
5. **`density_table` names the NBP EMOS calibration artefact**, not `ladder_ev/density_table.py`. Only the naming is affected.
6. **P_HOLD stays frozen** (code constants; RETIRED CRH kinds carry `RefusingPlugin`). It is outside AUT-3's score-3 scope.
7. **"Reproduces the sha on a sampled subset"** can only mean a sample of candidates, each refit in full.
8. **Two ARCH gaps.** (a) AUT-3 needs a non-C evidence record `refit_run/v1` for AUT-6's detectors. (b) §4.3's pins cover only the `breezy.*` closure, but the refit entry and `build_version_rows` live in `scripts/analysis/`. The `aut3_refit` closure must include `scripts/analysis/{autonomy_refit_daily,nbp_skill_study,settlement_truth_dataset}.py` and their script imports.
9. **Execution data.** No FQ model class consumes fill, slippage or refusal (operator 09-29), so the README clause is vacuous for FQ. WP-23 is rejected.
10. **The G11 widening re-targets an existing safety test.** It is an L-12 widening with reviewer sign-off, never a loosening.
11. **ARCH lists AUT-3 in Wave 2,** but the live proof needs the AUT-4 offline consumer and engine MINT (Wave 3). The streak cannot start before then.

**Risks and failure modes:**

| Risk | Mitigation |
|---|---|
| Memory on the 31 GB host (studies at 10–24 GB) | One studies-flock holder at a time; `MemoryMax=4G` sized from the WP0 measurement (≤16G); no heavy start 01:00–04:30Z; never co-scheduled with a replay; stop the study, never the node (memory `nightly-studies-run-at-10-24gb`) |
| Hung or slow fit (the 20 h S2 precedent) | WP0 subset benchmark first; `WatchdogSec=1200` per-progress ping; `RuntimeMaxSec`; progress lines; the 90 min / 12 GiB contingency |
| Shared venv | Exact interpreter only; never `uv`/`pip`; repro uses `git archive` plus `PYTHONPATH`, never an install; `uv_lock_sha256` recorded, with `REPRO_ENV_CHANGED` classified |
| Concurrent agents | Wave 1 files disjoint from AUT-1/5a/6; WP2 serialised behind the `fq/composition.py` owners; per-agent scratchpads; no `git stash` (hook-blocked); full gate after every merge; worktrees rebased onto `feat/data-capture-and-risk` first |
| Producer-pin churn: any edit to `nbp_calibration.py` stops refits until pins update | `test_code_identity_pins_cover_import_closure` turns the gate RED in the editing commit; a pin refusal is CRITICAL and visible the same morning |
| Statistical capacity: n_eff tiny, selection-biased labels | Shrinkage N0=100 clusters; cluster weights; evidence class stated; no promotion claim; the global affine map can distort non-traded rungs, which AUT-4's offline Brier on all rungs catches |
| C2 never admissible (reconciliation fails, AUT-2) | The own-outcome leg cannot be proven; reported as score 2 with the AUT-2 blocker named, never padded |
| Feed outage, no new rows | `NO_CHANGE` breaks the streak; AUT-6 freshness alert; the window extends |
| Disk growth | About 61 KB per artefact, ≤1 a day per lineage, plus small snapshots; well under 100 MB by the KILL |
| KILL 2027-01-25 | ETA 11-21 leaves about 9 weeks. After a TERMINAL KILL, refits continue on the frozen lineage (MINT allowed, PROMOTE refused, ARCH §5.3), so AUT-3 stays live |
| `nbp_learning_nightly` keeps scoring a hard-coded path (`breezy-nbp-learning-nightly.service` ExecStart) and only pre-July rows (`final_pre_holdout_rows`) | Not changed here. AUT-6 retargets it to the registry champion and the post-seal window once the freeze ruling lands. Flagged in association. |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** no Nautilus file is touched. Refits are offline. The node keeps loading sha-pinned bytes through the existing loader.
- **Caps:** no autonomy-refit module reads or writes `OPERATOR_RESERVED_CONTROL_ENV_VARS` (`test_autonomy_never_reads_or_writes_operator_controls` extended to the package). The units never load `operator.env`.
- **`allow_short=False`:** untouched (`fq/config.py:74-82`). No refit parameter touches sizing or sides; §4.2 manifest equality forbids it.
- **NO-SEND:** no new egress host. Alerts use only `alerts.env` through `deliver_with_proof`. `test_execution_egress_firewall_guard` is unchanged. The refit package imports no `exec/`, adapter or order path (`test_autonomy_never_imports_order_path`).
- **Master enablement and permit:** never read or written. AUT-3 writes only under `derived/` and `evidence/`.
- **PREREG via ruling:** the holdout freeze and every window and shrinkage constant come from `RULING_aut3_refit_windows_and_holdout_freeze_<date>.md`, pinned by test. No statistical semantics are invented at runtime.
- **Safety tests never weakened:** one refusal test is re-targeted under a reviewed L-12 widening, and four refusals are added. No settlement, contract or NO-SEND test is edited.

---

## 10. Self-score (r1)

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Every §10 and C3 obligation mapped. Two ARCH gaps (8a/8b) need Rev 4 acknowledgment. |
| Correctness | 20 | 17 | Splits tagging and watchdog semantics are still INFERRED (WP0). The holdout freeze depends on reviewer acceptance. |
| Specificity | 15 | 14 | Files, functions, units, schedules and constants named. Some names (C1/C2 reader functions) are ARCH-0's. |
| Acceptance | 20 | 18 | The checklist names commands and paths. The live proof depends on AUT-2/4/5 artefacts. |
| Autonomy-safety | 15 | 14 | Fail-closed writer, pins, drills and delivery proof. The `--drill` flag is production code and is refused without the flag. |
| Reuse | 10 | 9 | Fitters, artefact writer, application semantics and the studies infrastructure reused. One new estimator, justified. |
| **Total** | 100 | **90** | |
