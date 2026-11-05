# AUT-3 — Retraining (refit pipeline): area plan

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-3 |
| Title | Retraining: scheduled, lineage-complete, leakage-guarded refits for every live composition kind, including one identifiable, de-risking-only model class that consumes the bot's own labelled outcomes |
| Round | **r3 (2026-10-03)**. r2 is kept unchanged at `AUT-3-retraining_plan_r2.md` and r1 at `AUT-3-retraining_plan_r1.md`. This round disposes S1–S11 of `reviews/AUT-3-r2-merged.md`, including its coordinator ruling on X22 (§R3). |
| ARCH consumed | **Rev 5**: `reviews/snapshots/ARCH_rev5.md`, sha256 `5d2b75fa77e2c0abaaa478bd38d32e7e06ac98c8057ce50a5045f0dd0eff8403` (re-hashed at planning time). Plus the coordinator decisions `reviews/ALPHA-decision.md` (two counters `k_life` / `mints_in_window`, `K_LIFETIME_EFFECTIVE`, the window-cap feasibility rule; binding on ARCH Rev 7, AUT-3 and AUT-4) and `reviews/HOLDOUT-decision.md`, consumed by the ruling name `RULING_holdout_freeze_and_forward_window_2026-10-03` (ARCH-owned; AUT-3 does not restate it). README §AUT-3 live proof as amended by the coordinator on 2026-10-03 (`README.md:116`). Repo HEAD `4b8347a6`. |
| Current score | 0 |
| Target | 3 |
| Upstream | ARCH-0 (`src/breezy/persistence/autonomy/`: schemas, C6 Protocols and registries, `pins.py`, the read-only resolver fold); AUT-1 (C1 `DecisionRecord`: `kind`, `p_hat`, `p_lower`, `p_upper`, `ev_net`, `ask_px`, `side`, `rung_id`, `eval_ns`, `forecast_input_sha256`, `artefact_sha256`, `manifest_sha256`, `decision_id`); AUT-2 (C2 `label/v1` with `p_at_decision` = P(bought leg wins), AUT-2 r2 §3.4.4; the `label_outcomes_ok_<date>` marker); AUT-4 (`forward_window_index` in `src/breezy/analysis/autonomy/alpha_ledger.py`, AUT-4 r2 §3.3/§3.5); AUT-5 (registry fold, MINT from C3, mint ceilings, the `autonomy-policy/v1` block's K_max); AUT-6 (`deliver_with_proof`, the `refit_freshness` and `refit_repro` detectors) |
| Downstream | AUT-4 (consumes every C3 candidate and every `refit_run/v3` record); AUT-5 (MINT ∅→SHADOW from C3); AUT-7 (rollback re-verifies C3 bytes) |
| Planning only | Nothing here is implemented. No commit, stash, `uv`/`pip` or `systemctl` was used to write it. |

**Evidence tags.** Every `file:line` is a repo-relative path from `/home/jon/breezy` (S10), checked at `4b8347a6` with codegraph (projectPath `/home/jon/breezy`) and read-only reads (`/usr/bin/grep` where `.venv` matters). **INFERRED** means not verified against running code; each such item is cleared by a named WP0 check before the slice that relies on it starts.

**Short names used below** (full paths, S10): `FQ/` = `src/breezy/strategy/forecast_quantile_ladder/`; `LEV/` = `src/breezy/strategy/ladder_ev/`; `CAL` = `src/breezy/analysis/nbp_calibration.py`; `AR/` = `src/breezy/analysis/autonomy_refit/` (new).

---

## 1. Goal state

**README score-3 criterion, verbatim (AUT-3):**
> - Scheduled, unattended refits produce versioned candidate artefacts for each family's model class. Each candidate records its lineage: data window hashes, code sha, parameters and seed.
> - Each refit runs on a rolling window of external weather data **plus** the bot's own labelled outcomes and execution data (fill, slippage and refusal), where the model class consumes them.
> - Leakage guards are asserted in code (`ref.ts < take.ts`; holdout bounds).
> - Refits are reproducible bit for bit from their lineage.
> - Each run has a stall watch and a memory cap.
> - The loader accepts every recalibration form the pipeline can emit, each covered by parity tests.

**README live proof, verbatim (coordinator amendment 2026-10-03, `README.md:116`):**
> 7 consecutive scheduled refit runs, each lineage-complete and consumed automatically by AUT-4. A run's outcome may be a minted candidate, `NO_CHANGE(below_delta)`, `NOT_FITTABLE` or `MINT_REFUSED_CEILING`, each recorded as a lineage record (reconciles with the ARCH K_max-per-window mint limit, Y13/W7). At least one minted candidate's training set must include the bot's own labelled outcomes and meet the non-vacuous X22 thresholds (`MIN_NEFF_TO_EMIT`, `MIN_PROBE_DELTA`). Coordinator amendment 2026-10-03, per the AUT-3 r1 review R6.

**ARCH Rev 5 §10 obligations for AUT-3, verbatim:**
> the refit cadence and windows; the mint path honouring `MAX_MINTS_PER_LINEAGE_PER_DAY` and K_max MINTs per lineage per forward window (W7); the ablation and leakage assertions; the reproducibility sample; the G11 widening with parity tests; its unit's `MemoryMax`, `RuntimeMaxSec` and flock wait.

**ARCH Rev 5 C3/C4 excerpts, verbatim:** "`ablation_artefact_sha256` is the same refit with that set left out, and the writer refuses the lineage if it is non-null and equals `artefact_sha256`"; "**The C2-consuming model class** is `forecast_quantile_ladder:rung_recalibration`, fitted on C2 `(p_at_decision, settled_outcome)`; it needs the G11 loader widening with parity tests. `forecast_quantile_ladder:density_table` consumes external weather only." C4: "**Chosen rule: AUT-3 mints at most K_max candidates per lineage per window** (and ≤ 1 per day): the store refuses a MINT row once the window holds K_max, so a candidate past K_max never exists".

**ALPHA decision, binding excerpt:** "`mints_in_window`: the rate limiter. At most K_max MINTs per forward window (ARCH W7 mint limit). AUT-3 records `NO_CHANGE(k_max_reached)`, which counts toward its live-proof streak." "`k_life` … **never resets**."

**Coordinator ruling on X22 (review `AUT-3-r2-merged.md`), binding:** X22 proves own outcomes are **consumed**, not edge. Its threshold is **functional**: the candidate must change at least `MIN_GATE_DECISIONS_CHANGED` (proposed 1) probe gate decisions, comparing the envelope `p_lower`/`p_upper` against `ask+fee` on the probe set, relative to the parent. Power, MDE and edge belong to AUT-4. WP0 simulates reachability at n_eff 30, 60 and 120, and that sets N0.

**How the live proof is counted.** 7 consecutive scheduled runs, each lineage-complete and acknowledged by AUT-4. Per-lineage run outcomes are `CANDIDATE`, `NO_CHANGE(k_max_reached | existing_sha)`, `NOT_FITTABLE(<reason>)` (including `gate_noop`) and `MINT_REFUSED_CEILING`; only `SKIPPED_LOCK` and `FAILED` break the streak. **Plus at least one minted `rung_recalibration` candidate whose training set includes own labels and that meets the functional X22 threshold** (§3.4(h)). The README text still names `NO_CHANGE(below_delta)` and `MIN_PROBE_DELTA`; the coordinator ruling replaces the p_hat-delta threshold with the gate-decision count, so r3 uses `NOT_FITTABLE(gate_noop)` for a threshold miss (README-text mismatch R-README-1, §8, coordinator edit). The 7 runs share most of their training data and are **not independent samples**: they prove the machinery runs reliably, not seven replications of a result.

Where this plan reaches each line is mapped in §7.

---

## 2. L-1 null hypothesis and reuse

| New component | Nautilus or Breezy capability checked | Verdict |
|---|---|---|
| Offline refit scheduler | Nautilus has no artefact registry, refit or scheduled job (ARCH Rev 5 §2 L-1). systemd timers are the repo convention (`deploy/systemd/breezy-nbp-learning-nightly.timer`). | BUILD one notify-type unit. No in-node fitting: the node keeps loading sha-pinned bytes only (`FQ/config.py:90-96`, "There is no live refitting", stays true). |
| EMOS refit (`density_table`) | `fit_calibration` (`CAL:1280`), `fit_hierarchical_emos` (`CAL:1166`), `select_kappa_by_lovo_crps` (`CAL:1004`), seeded `bootstrap_emos_draws` (`CAL:1070`, `BOOTSTRAP_SEED` `CAL:451`), `artefact_from_calibration_fit` (`CAL:2550`), `artefact_json`/`artefact_sha256`/`write_artefact` (`CAL:2635-2665`); row join `build_version_rows` (`scripts/analysis/nbp_skill_study.py:661`); `Splits`/`split_for_date` (`CAL:237-271`), `DEFAULT_SPLITS` (`CAL:273`). | **REUSE with one behaviour-neutral widening (S6):** a keyword-only `progress` callback on `fit_calibration`, `fit_hierarchical_emos` (pass-through), `select_kappa_by_lovo_crps` and `bootstrap_emos_draws`. None of them has a progress hook today (`/usr/bin/grep -n "progress\|callback" CAL`: 0 hits), so r2's "REUSE unchanged" was wrong and is withdrawn. Default `None` is bit-identical (§3.4, WP4). |
| Recalibration form and application | `ProbabilityRecalibrationForm` (`CAL:1508-1511`); `_apply_recalibration_scalar` (`CAL:1560-1577`); `apply_probability_recalibration` (`CAL:1647-1662`: per-rung scalar, divide by the total summed in dict-insertion order, assert the sum is 1); artefact fields `recalibration_affine` (`CAL:2381-2382`). | REUSE the `affine` form. **Identifiability (r2 R2, kept):** rung partitions sum to 1 (`LEV/quantile_density.py:386-388`), so for slope b > 0 without clipping the renormalised affine map depends on (a, b) only through c = a/b, and `(0, b)` is the identity. The emitted form is pinned to **slope = 1 exactly, intercept c**. |
| Recalibration estimator | `_fit_affine` (`CAL:1535`) is unweighted OLS with no penalty; `minimize_scalar(method="bounded")` is already used deterministically (`CAL:840`). | ADD one 1-D penalised estimator whose objective uses the **live statistic** (§3.4(b)). No new form. |
| Base partitions and the live statistic | `rung_probability_interval` (`LEV/quantile_density.py:392-442`): per-draw rung probabilities, `p_point = statistics.fmean` (exactly rounded, order-independent), `p_lower`/`p_upper` = order statistics at `level=0.95`. `ArtefactBoundsProvider` (`FQ/artefact_bounds.py:38-60`). The FQ gate: YES `p_lower − ask − fee(ask) > margin`; NO `(1 − p_upper) − no_ask − fee(no_ask) > margin` (`FQ/decision.py:17-18,349`); `edge_after_costs` is affine in `model_p` with slope 1 (`src/breezy/strategy/weather_common/risk.py:745-765`); `margin = forecast_margin(h_hours, cfg)` (`FQ/margin.py:30`, `hours_to_settlement` `:40`). Quantity is the literal `QTY = 1` (`FQ/decision.py:73`). | REUSE. **Split, bit-identically,** `rung_probability_interval` into `per_draw_rung_probabilities(...)` and `interval_from_per_draw(per_draw, level, recalibration)` so the live provider, the refitter, the writer and the reproducer compute every statistic through one code path (S5). |
| Live recalibration application | `LiveCalibration` (`FQ/calibration_artefact.py:118`) refuses any `recalibration` other than `none` (`_SUPPORTED_RECALIBRATION` `:68`, check `:281-287`). | WIDEN (L-12): accepted set = emit set `{none, affine(slope=1, C_IDENTITY_EPS ≤ |c| ≤ C_BOX)}`; strategy-layer `RungRecalibration` applied per draw; unconditional envelope against the artefact's own `none` base (§3.8). |
| Gate-decision measurement | No component counts how a candidate changes FQ gate decisions. C1 records `ask_px`, `ev_net`, `p_lower`, `p_upper`, `side`, `eval_ns` for every `Take`/`TrySubmit` (ARCH Rev 5 C1). | BUILD `AR/gate_probe.py` (S3): exact re-evaluation of each probe record's gate under the candidate, using the slope-1 affinity of `edge_after_costs`; never feeds the fit objective. |
| Candidate store | G13 root guard `_resolve_candidate_root` (`scripts/analysis/nbp_learning_nightly.py:708-719`); ARCH C3 layout. | GENERALISE to `derived/artefacts/<model_class>/<sha>/`; keep the out-of-repo refusal. |
| Lineage schema, counters, window index | ARCH-0 `src/breezy/persistence/autonomy/` (C3 `lineage/v1`, `lineage_counters`); AUT-4 r2 `alpha_ledger.forward_window_index` (anchored 2026-10-02, `FORWARD_WINDOW_DAYS` from the policy block). | CONSUME. AUT-3 owns only the C3 writer and `refit_run/v3`. It never computes a window index of its own, never assigns `k_life`, never charges α and never writes a counter. |
| Plug-in dispatch | `CompositionKind` (`src/breezy/persistence/family_manifest.py:115-119`); ARCH-0 `OFFLINE_PLUGINS` (C6). | IMPLEMENT `FqRefitter`; `RefusingPlugin` for the three non-live kinds. |
| Studies lock, slice, failure notifier | `deploy/systemd/breezy-studies.slice`, `breezy-study-failed@.service`, `breezy-studies.lock` (`deploy/systemd/replay-daily-run.sh:101`). | REUSE; flock taken in Python so the watchdog pings during the wait. |
| Stall watch and runtime bound | No unit uses `RuntimeMaxSec` or `WatchdogSec` (ARCH G29). `man systemd.service`: `RuntimeMaxSec=` has no effect on `Type=oneshot`. | BUILD `Type=notify` + `WatchdogSec`; stdlib `NOTIFY_SOCKET`. |
| Alert delivery | `emit_alert` swallows failures (G25); `deliver_with_proof` is AUT-6's. | CONSUME for every CRITICAL. |
| P_HOLD (CRH) refit | `P_HOLD_LOWER/UPPER` are code constants (`src/breezy/strategy/current_rung_hold/archive_table.py:37-41`); every CRH kind is RETIRED. | NOT IN SCOPE; `NOT_FITTABLE(refusing_plugin)`. |
| Execution-data refit | No FQ component takes fill, slippage or refusal as an input; operator ruling 09-29 (venue prices are execution cost only). | NOT BUILT; README clause amendment drafted (§3.10 item 2). The gate probe reads `ask_px`/`ev_net` **as execution cost** to count gate decisions, never as a predictor (§3.4(h)). |

---

## 3. Design

### 3.1 Model classes for `forecast_quantile_ladder` (the only kind in `LIVE_GATE_ROUTED_KINDS`)

One FQ artefact is one `NbpCalibrationArtefact` JSON (`CAL:2355`). The champion is `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`, sha `9c0b6d6e…923a5e`, `recalibration=none`, `correction_form=linear_lst_day_length`, versions v4.0–v5.0, 200 draws. A child may differ from its root only in `density_artefact_path/sha` (ARCH §4.2), so every candidate is a complete artefact.

| `model_class` | What changes vs the parent | Inputs | Own outcomes | Gate effect vs parent |
|---|---|---|---|---|
| `forecast_quantile_ladder:density_table` | v5.0 `(a, γ)`, its draws, κ (LOVO) and per-draw δ; v4.x fixed; correction carried; `recalibration=none` | External only: `derived/nbp` ⨝ `settlement-truth/settlement_truth.parquet` FINAL rows | `own_outcome_label_set_sha256 = null` | Either direction (adds or removes takes); not a de-risking class (S8) |
| `forecast_quantile_ladder:rung_recalibration` | Only `recalibration="affine"`, `recalibration_affine=(c, 1.0)`; every other field byte-equal to the parent (asserted). **Fitted only when the parent's `recalibration` is `none`** (S2). | C2 labels, oriented and verified (§3.4) | non-null; ablation and X22 required | Per (rung, side) gate decision: can only remove takes (§3.8) |

**Naming note.** `density_table` here means the NBP EMOS calibration artefact, not `LEV/density_table.py` (the RETIRED `forecast_ladder` kind). It is a contract literal.

### 3.2 `rung_recalibration`: hypothesis, population, competing evidence

- **Hypothesis H-R (not a claim).** On rungs the gate *selects*, the realised win rate of the bought leg differs from the forecast's probability. A one-parameter partition map fitted on those outcomes estimates that selection-conditioned miscalibration.
- **Selection population (S7).** c is an estimate **conditional on one population**, recorded in `params.selection_population` (§3.5): filled `entry` takes, decided by the parent's gate (YES selected on `p_lower` vs the ask, NO on `1 − p_upper` vs the NO ask, plus fee and `forecast_margin`), from IOC orders that filled. **IOC misses are AMBIGUOUS** (memory `strict-zero-fill-is-unreachable`) and produce no C2 label, so the population excludes every take that did not fill; it also excludes takes that the daily budget or an AMBIGUOUS latch suppressed. c says nothing about rungs or decisions outside that population, and AUT-4 must not read it as a calibration of the full forecast.
- **Mechanism.** The 09-20 terminal finding: market resolution is 1.98× the forecast's (memory `forecast-edge-closed-pmus-rungs`). Selecting where the forecast disagrees most with a better-resolving market concentrates forecast errors in the selected set (winner's curse); the same train/serve population skew as memory `archive-table-train-serve-skew`.
- **Competing evidence.** (1) The traded-rung calibration leg was **under-confident** (memory `bss-headline-is-the-wrong-family`), which predicts c < 0 (sharpen); the estimator is sign-free in a ruling box, and de-risking comes from the envelope (§3.8). (2) A LOSO Platt fit made the mid **worse**. (3) The pinned nightly's latest `bss_vs_m1 = −0.0399`.
- **Effect under the envelope (S8, scoped).** Per (rung, side) gate decision, the candidate's gate input is never more favourable than the parent's, so the candidate's set of gate-eligible `(decision, rung, side)` tuples is a subset of the parent's. That is a statement about **gate eligibility of each decision in isolation**, not about the realised path of orders: see §3.8 for the budget and AMBIGUOUS-latch interactions.
- **Evidence class: machinery proven, edge unproven.** A recalibration adds no resolution and cannot reopen the closed edge. A recalibration candidate is expected to show no edge; under ALPHA §3 its FORWARD_SHADOW verdict is `INCONCLUSIVE(window_cap_below_n_min)` by construction under today's σ.
- **Rejected alternative:** fitting on all C1 decisions ⨝ settlement (refusals included). That is the external-row information `density_table` already uses, and not the selected population.

### 3.3 Windows, holdout, cadence and the mint limit

**Holdout (`HOLDOUT-decision.md` by reference).** The archive holdout is frozen at **[2026-07-01, 2026-10-02)**, sealed for one final confirmatory use that belongs to AUT-4, never AUT-3. Days ≥ 2026-10-02 are forward data; AUT-3 trains only on days before each forward evaluation window. AUT-3 consumes `RULING_holdout_freeze_and_forward_window_2026-10-03` by name. `AR/windows.py` holds `SEALED_HOLDOUT_START` / `SEALED_HOLDOUT_END_EXCLUSIVE` as `Final` literals, and a test asserts they equal that ruling's machine block. Until the ARCH ruling is filed, WP1's pin test is RED and no post-06-30 row is eligible.
- AUT-3 never calls `open_holdout` (`CAL:353`; AST test) and never writes `lineage_counters`.
- **No fresh weather holdout for `density_table`.** Its only confirmation is AUT-4's forward evaluation on days ≥ `forward_eval_start_utc`.

**`RefitWindow` for a run on UTC day D** (`AR/windows.py::compute_refit_window`):
- `train_end_exclusive_utc = D 00:00Z`; only FINAL CLI rows with `issued_at_utc < train_end` and NBP rows with `available_at_ns < train_end` are eligible.
- `forward_eval_start_utc = (D+1) 00:00Z` (≥ `created_at`).
- `window_index = alpha_ledger.forward_window_index(forward_eval_start_utc.date())` (AUT-4's function, imported, never re-implemented; identity test).
- density_table: v4.x rows on their `DEFAULT_SPLITS` days (unchanged); v5.0 rows on `v5_fit_slice` (2026-05-04..06-30) **∪** forward days `[max(2026-10-02, train_end − ROLLING_V5_DAYS), train_end)`. A sealed day is never eligible.
- rung_recalibration: C2 labels admitted by §3.4(a), settlement `climate_day ≥ 2026-10-02`, `labelled_at_ns < train_end`, from files covered by a `label_outcomes_ok_<date>` marker. AUT-2 r2 writes labels by 14:45Z (AUT-2 r2 §5), so a run at 06:00Z on D uses labels written on D−1.

**Seasonal gap (r2 R7, unchanged).** WP0 (vii) measures, on pre-holdout v4.3 rows only, Fit A (`[2025-05-27, 2025-06-30] ∪ [2025-10-02, +F)`) vs Fit B (contiguous) scored on `[2025-10-02 + F, +28 d)` for F ∈ {14, 28, 56}: ΔCRPS, Δ rung Brier (station-day cluster bootstrap, `roi_bound.SEED`), `(a, γ)` shift. Accepted iff the upper 95% bound of ΔCRPS(A − B) at F = 28 is ≤ `SEASONAL_GAP_MAX_DCRPS` (proposed 0.02 °F); else density refits wait for `MIN_FORWARD_DAYS_FOR_DENSITY`. rung_recalibration is unaffected.

**Cadence, mint limit and gates (S1, S3).** One run a day at 06:00Z. Per lineage, in order:
1. **Mint limit first (ALPHA decision 1; ARCH Rev 5 C4).** The driver reads from the verified fold `mints_in_window(lineage, window_index)` = non-drill MINT rows of the lineage in that forward window, plus C3 records AUT-3 wrote for that window whose MINT is still `pending` (so a pending C3 reserves a slot). `K_max_effective` = the filed `autonomy-policy/v1` block's K_max if filed, else the `pins.py` ceiling `MAX_CANDIDATES_PER_LINEAGE_PER_FORWARD_WINDOW` (≤ 4). If `mints_in_window ≥ K_max_effective`, **every component of the lineage records `NO_CHANGE(k_max_reached)`**: AUT-3 builds the input snapshot (so `data_windows` hashes exist and the record is lineage-complete), skips the fit and writes no C3. This counts toward the streak. The window rolls over only when `window_index` advances; `mints_in_window` restarts per window by definition, while `k_life` (AUT-4/C4's lifetime index) **never resets** and AUT-3 never writes it.
2. **Ordering.** The component whose last C3 is older goes first; a tie goes to `rung_recalibration`.
3. **Fit and functional gate.** The component is fitted. Its candidate qualifies only if it passes every writer check **and** `gate_decisions_changed(candidate, reference) ≥ MIN_GATE_DECISIONS_CHANGED` on its probe set (§3.4(h)), where the reference is the lineage's last C3 of the same `model_class` that was minted, else the parent. Below threshold the component's status is **`NOT_FITTABLE(gate_noop)`** (S3, the coordinator ruling). This single measure replaces r2's `functional_delta`/`MIN_MINT_DELTA` and `probe_max_delta`/`MIN_PROBE_DELTA`.
4. **One C3 a day.** The first qualifying candidate is written; the other component records `DEFERRED_DAILY_CEILING`. This honours `MAX_MINTS_PER_LINEAGE_PER_DAY ≤ 1`, which the engine also enforces.
5. **Mint refusal.** If the engine refuses the MINT of a written C3 (daily ceiling, window K_max, a drill child that day), the next run reads the fold and records `MINT_REFUSED_CEILING` in `refit_run/v3.prior_mint_status[]`; the refused C3 releases its reserved slot.
6. **Run outcomes.** Per lineage: `CANDIDATE`, `NO_CHANGE(k_max_reached | existing_sha)`, `NOT_FITTABLE(<reason>)`, `MINT_REFUSED_CEILING`, `SKIPPED_LOCK` or `FAILED`. Only the last two break the streak.

**Lifetime α horizon (ALPHA decision 2).** AUT-3 does not stop minting at `K_LIFETIME_EFFECTIVE`. Each `results[]` entry records `k_life_at_run` (read-only from `lineage_counters.candidates_evaluated`) and `nominal_only = (k_life_at_run + 1 > K_LIFETIME_EFFECTIVE)`, so the scorer can see that such a candidate is descriptive only at AUT-4 and can never PASS. Its α is charged by AUT-4, never by AUT-3.

**Window-cap feasibility (ALPHA decision 3).** Under today's σ every FORWARD_SHADOW verdict is `INCONCLUSIVE(window_cap_below_n_min)` by construction. That verdict still "consumes" the candidate for this plan's live proof (§6). No promotable path is claimed.

### 3.4 Estimators

**density_table** (`AR/fq_density_refitter.py::FqDensityTableRefitter`):
- Rows from `AR/rows.py::rolling_version_rows(...)`, delegating to `build_version_rows` (`scripts/analysis/nbp_skill_study.py:661`). Split tagging is **INFERRED**: `split_for_date` raises outside declared splits (`CAL:270-271`) and `Splits` refuses a v5 slice ending on or after `holdout_start` (`CAL:255-259`). WP0 (i) picks a `Splits` instance with `holdout_start = train_end` and pre-filtered rows, or a post-build `dataclasses.replace(row, split="v5_fit_slice")`.
- `fit_calibration(rows, method=CdfMethod(parent.cdf_method), bootstrap_seed=BOOTSTRAP_SEED, progress=sink.progress)`, then `artefact_from_calibration_fit` with the parent's `CorrectionSelection`; `recalibration=none`; `n_min`/`sigma_d` carried.
- **Progress hook (S6).** New in `CAL`: `FitProgress` (frozen, slotted: `stage: Literal["delta","kappa","unshrunk","bootstrap"]`, `done: int`, `total: int`) and a keyword-only `progress: Callable[[FitProgress], None] | None = None` on `fit_calibration` → `fit_hierarchical_emos` → `select_kappa_by_lovo_crps` (once per κ grid point) and `bootstrap_emos_draws` (every 10 draws and at the end). The callback receives counters only, never data, and its return value is ignored; an exception in it propagates (no swallowing). With `progress=None` every caller is bit-identical: `test_fit_calibration_progress_none_and_callback_bit_identical` asserts the `CalibrationFit` and `artefact_sha256` are equal with `None`, with a recording callback, and through both existing callers (`scripts/analysis/nbp_skill_study.py::run_validate_gates_from_rows` and `tests/unit/test_fq_live_analysis_point_cdf_parity.py`). `CAL` enters the `aut3_refit` closure, so any producer pin whose closure contains `CAL` rotates in the WP4 commit (`test_code_identity_pins_cover_import_closure` turns RED until it does).
- **Fit rows are asserted, not just snapshotted:** the row tuple passed to `fit_calibration` is the object handed to the leakage functions and serialised to the snapshot (`fit_input_sha256 == data_windows[nbp_*].content_sha256`).
- **Contingency** (WP0 decides it): if the full-fit p95 runtime is > 90 min or peak RSS > 12 GiB, use the v5.0-only conditional refit (`fit_version_unshrunk` shrunk toward the frozen LOVO pooled mean at the parent's κ, parent δ kept).
- **Functional gate (S3).** Probe set `P_density` = C1 records decided under the parent artefact in the last 28 forward days that carry a gate evaluation: every `Take` and `TrySubmit`, and `Refuse(reason="below_margin")`. Because `Refuse` is written only on `(key, reason)` change (ARCH C1, L-29), `gate_decisions_changed` for density is a **lower bound**, recorded with `probe_refuse_sparse=true`. Flips in either direction count.

**rung_recalibration** (`AR/fq_rung_recal_refitter.py::FqRungRecalibrationRefitter`):

*(a) Label admission and orientation.*
- **Admitted:** `admissible ∧ reconciled ∧ source=live ∧ ¬drill`, `role == "entry"` (exit labels excluded, reason `exit_label`), non-null `p_at_decision` and `decision_id`.
- **Orientation (resolved upstream; r2 C-1 deleted).** AUT-2 r2 §3.4.4 pins `p_at_decision = p_hat if side == "yes" else 1 − p_hat` = P(bought leg wins), matching `settled_outcome` = the bought leg's win. The refitter converts each label to the YES-rung domain: `leg=yes` → `(p_yes, y_yes) = (p_at_decision, settled_outcome)`; `leg=no` → `(1 − p_at_decision, 1 − settled_outcome)`.
- **Assertion `label_orientation_matches_capture`** (kept as a regression guard): `p_yes` must equal the joined C1 `p_hat` within `P_REPRO_ABS_TOL`. A mismatch fails the run (CRITICAL, no write).

*(b) Fitted statistic: the live statistic (S5).* For label k with per-draw base partitions `π_{k,d}` (d = 0..199 in artefact draw order, rungs in the C1 ladder order), the prediction under map g_c is `p̂_c,k = fmean_d( apply_probability_recalibration(g_c, π_{k,d})[rung_k] )`: map per draw, renormalise per draw, then the exactly rounded mean (`statistics.fmean`), exactly as `LEV/quantile_density.py:441` computes `p_point`. `p_lower`/`p_upper` under g_c are the same order statistics `rung_probability_interval` takes (`:437-440`). Every delta in this plan (gate inputs, off-support, envelope check) uses these live statistics, **never** g applied to a mean partition.

*(c) Base partitions: recomputed, verified, snapshotted (S5).* For each admitted label and each probe record the refitter calls `per_draw_rung_probabilities(percentiles, method, draws, ladder)` with: the deciding artefact's EMOS draws (ignoring its recalibration fields); the forecast `Percentiles` of the NBP cycle visible at `eval_ns`, whose digest must equal C1 `forecast_input_sha256`; the ladder of the `(station, climate_day)` in C1 order. It then recomputes the deciding artefact's own `(p_hat, p_lower, p_upper)` and requires equality with C1 within `P_REPRO_ABS_TOL`.
- **Summation order is fixed (S5).** Renormalisation sums in the C1 ladder order (the order `apply_probability_recalibration` iterates, `CAL:1652-1656`); draws are kept in artefact order; the mean is `fmean` (order-independent); bounds are order statistics (order-independent). The recompute therefore runs the **same float operations in the same order** as the live provider, the expected difference is exactly 0.0, and `P_REPRO_ABS_TOL = 1e-12` is a ceiling that catches any path divergence, not slack for a different algorithm. `params.max_repro_abs_diff` records the observed maximum.
- A label or probe record that fails is excluded by name (`p_unreproducible`) with a WARN; more than 10% failing is CRITICAL. **INFERRED:** the forecast vector can be retrieved by digest; WP0 (viii) proves it on the 10-02/10-03 fills. **Fallback:** C1 extension `rung_partition_p_hat` (§8 C-6). Without either, rung_recalibration is `NOT_FITTABLE(partition_unavailable)` and the own-outcome leg is reported as score 2.
- **Snapshot of per-draw inputs (S5).** The per-draw base partitions of every label and probe record go into the snapshot segment `label_draw_partitions` (columns `decision_id, draw_index, rung_index, rung_id, p`, float64, sorted by those keys), and the forecast `Percentiles` into `label_forecast_percentiles`. Refit reproduction (§3.7) refits **from `label_draw_partitions`** and separately re-verifies the recompute from `label_forecast_percentiles` plus the content-addressed artefact draws. Size: about 200 draws × ≤ 12 rungs × 8 B ≈ 19 KiB per decision; WP0 (ix) measures it against the disk budget.

*(d) Parent binding (S2, S9).*
- **Parent must be unrecalibrated (S2, option 1 of the review).** rung_recalibration is fitted only when the parent artefact's `recalibration == "none"`; otherwise the result is `NOT_FITTABLE(parent_recalibrated)`. The writer recomputes this from the parent bytes and refuses. Reason: the envelope (§3.8) is taken against the artefact's own `none` base. Against an unrecalibrated champion that base **is** the champion, so the per-(rung, side) subset property holds relative to the champion. Against a recalibrated champion it would not. The review's alternative (carry `envelope_parent_shift` and envelope against base and parent) is rejected: one level of parent shift is not enough after a second promotion, because the grandparent's shift can be the binding bound, so it would need the whole ancestor chain in the artefact, a schema widening and a second loader form (YAGNI). **Practical cost now: none.** ALPHA §3 makes every FORWARD_SHADOW verdict INCONCLUSIVE and AUT-5 keeps `promote_enabled=false` before the KILL, so a recalibrated champion cannot arise through PROMOTE; the AUT-7b drill child is byte-identical (`none`). This supersedes r2's R15 removal of the parent-recalibrated stop.
- **EMOS binding.** A label is admitted only if its deciding artefact's EMOS block is byte-equal to the parent's (reason `label_from_other_emos`). After a `density_table` promotion, labels from the older EMOS are excluded (a stated limit).
- **Gate binding (S9).** A label is admitted only if its deciding artefact's `recalibration == "none"`; a label decided under a promoted (or any) recalibration is excluded with reason **`label_from_other_gate`**, because the envelope changed which decisions were selected, so its selection population differs from the parent's (§3.2). Kept and justified: nothing. Each exclusion is counted in `params.exclusions`.

*(e) Estimator `fit_partition_shift`.*
- **Form:** `ProbabilityRecalibrationSelection(form=AFFINE, affine=(c, 1.0))`, c ∈ [−C_BOX, C_BOX].
- **Objective:** `J(c) = Σ_k w_k·(p̂_c,k − y_yes,k)² / n_eff + (N0/n_eff)·R(c)`. Cluster weights (L-40): each `(station, climate_day)` has total weight 1 split equally across its labels; `n_eff` = the cluster count. `R(c)` = mean over the probe records of `Σ_rungs (p̂_c − p̂_0)²` computed with the live statistic.
- **Solver:** `scipy.optimize.minimize_scalar(J, bounds=(−C_BOX, C_BOX), method="bounded", options={"xatol": 1e-9})`, deterministic given inputs (as at `CAL:840`). The estimator clamps into the box; `clamped` is recorded.
- **Canonical identity.** `|c| < C_IDENTITY_EPS` is written as `recalibration="none"`. `C_IDENTITY_EPS = 1e-9` equals the solver's `xatol`, because the solver cannot resolve c below that (r2's 1e-12 was below solver resolution). In practice such a c changes no gate decision and is already `NOT_FITTABLE(gate_noop)`.

*(f) Support checks.* Failing any gives `NOT_FITTABLE(unidentified)`: `n_eff ≥ MIN_NEFF_TO_EMIT` (set by WP0 (x)); `distinct_stations ≥ 2`; inter-quartile range of `p_yes` ≥ `MIN_P_SPREAD` (0.10); ≥ 2 distinct ladder sizes K **or** ≥ 3 distinct rung positions.

*(g) Off-support gate.* S = [min `p_yes`, max `p_yes`] over training labels. `off_support_gate_max_delta` = max over probe records and rungs whose base `p̂_0` lies outside S of the change in the **enveloped gate input** (`p_lower` for YES, `1 − p_upper` for NO). It must be ≤ `MAX_OFF_SUPPORT_DELTA` (0.02), else `NOT_FITTABLE(off_support)`. The writer recomputes it.

*(h) Probe set, gate measurement and X22 (S3, coordinator ruling).*
- **Probe set** `P_recal` = every C1 `Take` and `TrySubmit` decided under the parent artefact with `eval_ns < train_end` and climate day ≥ 2026-10-02, **filled or not** (an IOC miss is still a gate decision). Each carries `(side, rung_id, ask_px, ev_net, eval_ns, p_lower, p_upper)` from C1 and its per-draw base partitions (§3.4(c)). Frozen into the snapshot segment `probe_gate_inputs`.
- **Parent margin recompute.** `margin_k = forecast_margin(hours_to_settlement(eval_ns_k, …), cfg)` (`FQ/margin.py:30,40`), with `cfg` from the lineage root manifest (manifest equality, ARCH §4.2, makes it identical across children). Sanity: `ev_net_k − margin_k > 0` for every `Take`; a record that fails is excluded as `probe_parent_not_qualifying` (WP0 (xi) clears this on the 10-02.. records; **INFERRED** until then; fallback C1 field `margin`, §8 C-6).
- **Candidate gate input, exactly.** `edge_after_costs` is `model_p − ask − cost` (`src/breezy/strategy/weather_common/risk.py:756-760`), slope 1 in `model_p`. So with `g_k = p_lower` (YES) or `1 − p_upper` (NO): `ev_net_cand,k = ev_net_k + (g_cand,k − g_parent,k)`, where `g_cand` is the **enveloped** bound (§3.8). This avoids re-deriving the depth-aware cost.
- `gate_decisions_changed` = #{k ∈ P : (ev_net_k − margin_k > 0) ≠ (ev_net_cand,k − margin_k > 0)}. Under the envelope only true→false flips are possible for rung_recal.
- `gate_probe_max_delta` = max over k of |g_cand,k − g_parent,k| (diagnostic, recorded).
- **X22 passes only if** `artefact_sha256 ≠ ablation_artefact_sha256` **and** `gate_decisions_changed ≥ MIN_GATE_DECISIONS_CHANGED` (proposed 1) **and** `n_eff ≥ MIN_NEFF_TO_EMIT`. Otherwise `NOT_FITTABLE(gate_noop)` (gate miss) or `NOT_FITTABLE(unidentified)` (n_eff miss). Neither is an own-outcome candidate for the live proof. The threshold is functional, **not** a significance bar: it proves the own outcomes reached the gate (non-vacuous: an identity-after-renormalisation map or a sub-resolution c changes 0 decisions).
- **Ablation (S11).** The ablation artefact is **defined** as the parent's bytes with `recalibration="none"` and `recalibration_affine=None`, serialised by `artefact_json`; it is not obtained by running the solver on an empty label set (a bounded solver returns a c of order `xatol`, not exactly 0). Because the parent's recalibration is `none` (§3.4(d)), `ablation_artefact_sha256 == parent_artefact_sha256`, asserted by `test_ablation_sha_equals_parent_sha_when_parent_none`. The writer refuses `ablation == artefact`.

*(i) Time-blocked own-label holdout (advisory).* Fit on labels with `climate_day ≤ D − 1 − OWN_LABEL_HOLDOUT_DAYS` (7) and score the last 7 days' labels: `params.advisory_time_block = {k, n_eff_train, n_eff_test, brier_recal, brier_parent, brier_diff}`. Advisory only; never gates a write or feeds AUT-4.

*(j) Inputs read.* The **estimator** (`fit_partition_shift`) reads exactly `(p_yes, y_yes, cluster_key)` and the per-draw partitions; an AST test asserts no price, fee or slippage field is reachable from it. Only `AR/gate_probe.py` reads `ask_px` and `ev_net`, as execution cost for the functional count, consistent with the 09-29 ruling.

**WP0 (x): reachability simulation (S4, coordinator ruling).** Seeded (`REACH_SIM_SEED`), run inside `systemd-run --user -p MemoryMax=4G -p RuntimeMaxSec=7200`, outside 01:00–04:30Z, holding the studies lock.
- **Pools (real data only, no invented edge; L-41).** Decision pool: every FQ `Take`/`TrySubmit` from node logs and C1 since 2026-10-01 with its recomputed per-draw partitions, `ask_px`, `ev_net` and margin slack `ev_net − margin`. If the pool has < 40 records, it is augmented by champion-artefact partitions on pre-holdout NBP rows (2026-05-04..06-30) paired with slack values resampled from the real pool, and the report flags `pool_augmented=true`.
- **Grid.** n_eff ∈ {30, 60, 120} station-day clusters; N0 ∈ {10, 25, 50, 100}; true shift c* ∈ {0, −0.02, +0.02}; `REACH_SIM_REPS = 2000` per cell. Each replicate resamples clusters (1–3 decisions per cluster, as observed), draws outcomes `y ~ Bernoulli(p̂_{c*})` from the live statistic, runs the full §3.4(e)–(h) pipeline (support, off-support, envelope, gate count) and records whether X22 passes.
- **Output:** `P_reach(n_eff, N0, c*)` with Wilson 95% intervals; `docs/evidence/AUT3_WP0_<date>.md` section (x).
- **Selection rule (pre-declared, written into the policy ruling):** `N0` = the largest grid value with `P_reach(60, N0, c*=0) ≥ REACH_TARGET` (0.8); if none qualifies, the smallest grid value. `MIN_NEFF_TO_EMIT` = the smallest n_eff in {30, 60, 120} with `P_reach(n_eff, N0, 0) ≥ REACH_TARGET` under that N0. c* = 0 is the primary case because R10 expects no edge.
- **Accrual rate.** WP0 (x) also measures `r` = admissible entry station-day clusters per calendar day since 2026-10-02 (from C2, or node-log fills before C2), and projects `date(n) = 2026-10-02 + n / r`.
- **Unreachability rule (stated now).** If no n_eff ≤ 120 reaches `REACH_TARGET`, or `date(MIN_NEFF_TO_EMIT) > 2027-01-11` (the KILL minus 14 days for the mint, AUT-4 ack and the 7-run window), the policy ruling states that the own-outcome leg is **unreachable before 2027-01-25**, gives the earliest n_eff that reaches the target and its projected date, and AUT-3 reports the own-outcome leg as **score 2**. It is never claimed as 3.

**Projection before WP0 (honest, not a measurement):**

| r (clusters/day) | n_eff 30 | n_eff 60 | n_eff 120 |
|---|---|---|---|
| 2.0 | 2026-10-17 | 2026-11-01 | 2026-12-01 |
| 1.0 | 2026-11-01 | 2026-12-01 | 2027-01-30 (after the KILL) |
| 0.5 | 2026-12-01 | 2027-01-30 (after the KILL) | unreachable |

PM.us lists 5 cities × HIGH only (memory `polymarket-us-surface-is-5-cities-high-only`), so r ≤ 5, and fill-free days (halts, refusals) lower it. If WP0 sets `MIN_NEFF_TO_EMIT = 120` and r ≤ 1, the leg is unreachable before the KILL under the rule above.

### 3.5 Lineage, inputs snapshot and leakage assertions

**Inputs snapshot** (`AR/inputs.py::snapshot_rows`). Canonical serialisation (explicit columns, sort key, parquet with fixed writer options) to `~/.local/share/breezy/derived/refit/inputs/<content_sha256>.parquet` (0444, dir 0500). Segments dedupe by content address: `nbp_v4_fixed`, `nbp_v5_slice`, `nbp_v5_forward`, `settlement_truth`, `c2_labels`, `c1_decisions`, **`label_draw_partitions`**, **`label_forecast_percentiles`**, **`probe_gate_inputs`** (S5, S3). `data_windows[]` has one entry per segment. Reproduction reads snapshots only.

**C3 `lineage/v1` fields filled by AUT-3** (schema unchanged):
- `model_class`, `lineage_root_family_id`, `parent_artefact_sha256`; `code_git_sha`, `build_sha`, `producer_code_sha`;
- `params`: `{component, cdf_method, seed, bootstrap_draws, rolling_v5_days, n0, c, clamped, n_eff, n_labels, exclusions, gate_decisions_changed, gate_probe_max_delta, probe_n, probe_refuse_sparse, off_support_gate_max_delta, max_repro_abs_diff, selection_population, window_index, mints_in_window, k_max_effective, k_life_at_run, nominal_only, advisory_time_block, numpy, scipy, pyarrow, python, uv_lock_sha256, cpu_model, openblas_coretype, thread_env}`;
- **`selection_population` (S7)**: `{unit: "filled_entry_take", gate: "fq_v1_gate(p_lower|1-p_upper vs ask+fee+forecast_margin)", decided_under_artefact_sha256: <parent>, ioc_miss_policy: "AMBIGUOUS_no_label_excluded", budget_or_latch_suppressed: "excluded_unobserved", label_window: [start, end_exclusive], statement: "c is conditional on this population"}`;
- `seed`, `fit_status="OK"`, `data_windows`, `own_outcome_label_set_sha256`, `ablation_artefact_sha256`, `train_end_exclusive_utc`, `forward_eval_start_utc`, `leakage_assertions`, `recalibration`, `correction_form`, `created_at_ns`, `runtime_s`, `peak_rss_bytes`.

**`leakage_assertions`** (`AR/leakage.py`). Any `passed=false`: no write, CRITICAL through `deliver_with_proof`, exit 2.

| Name | Asserts |
|---|---|
| `ref_ts_lt_take_ts` | density: every fit row's NBP `available_at_ns` < the D+1 decision cutoff of its climate day. rung_recal: every label's C1 `eval_ns` < fill `ts` < settlement issuance, and the forecast cycle's `available_at_ns` ≤ `eval_ns` |
| `train_end_lt_forward_eval_start` | `train_end ≤ forward_eval_start` and `forward_eval_start ≥ created_at` |
| `no_sealed_holdout_rows_in_train` | on the exact row tuple passed to the fitter: no `(station, climate_day)` in [2026-07-01, 2026-10-02) |
| `labels_settled_before_train_end` | every row's FINAL issuance < `train_end` |
| `probe_before_train_end` | every probe record's `eval_ns` < `train_end` |
| `label_orientation_matches_capture` | §3.4(a) |
| `labels_bound_to_parent_emos` | every training label's deciding EMOS block equals the parent's |
| `labels_bound_to_parent_gate` | every training label's deciding artefact has `recalibration == "none"` (S9) |
| `parent_unrecalibrated` | rung_recal: parent `recalibration == "none"` (S2) |
| `admissible_entry_only` | `admissible ∧ reconciled ∧ source=live ∧ ¬drill ∧ role=entry` |
| `parent_bytes_preserved` | rung_recal: every non-recalibration field byte-equal to the parent |
| `own_outcome_x22` | §3.4(h): sha differs **and** `gate_decisions_changed ≥ MIN_GATE_DECISIONS_CHANGED` **and** `n_eff ≥ MIN_NEFF_TO_EMIT` |
| `envelope_never_more_confident` | over the probe set, enveloped `p_lower` ≤ parent and enveloped `p_upper` ≥ parent, every rung |

### 3.6 C3 writer and store (`AR/c3_writer.py::write_candidate`)

- Atomic `mkstemp` + `os.replace` into `derived/artefacts/<model_class>/<sha>/{artefact.json, lineage.json}`; files 0444, dir 0500; `O_NOFOLLOW` on every component.
- **Refuses:** `fit_status ≠ OK` or any failed assertion; `ablation == artefact` when own outcomes are used; `recalibration` not `is_emittable` (shared predicate, §3.8); a rung_recal C3 whose parent bytes carry `recalibration ≠ none` (S2); `correction_form` unsupported; a second C3 for the lineage on the same UTC day; **a C3 for a lineage whose `mints_in_window` (fold + pending C3) is ≥ `K_max_effective`** (S1; the producer-side mirror of the store's MINT refusal); a root inside the repo or `deploy/families`.
- **Recomputes, never trusts:** `gate_decisions_changed`, `off_support_gate_max_delta` and the envelope check from the candidate bytes and the `probe_gate_inputs` / `label_draw_partitions` snapshots, refusing on disagreement with the lineage or a threshold miss.
- **No new lineage for an existing sha** (C3 Y2): status `NO_CHANGE(existing_sha)`.
- Bytes come from `artefact_json`, so `sha256(artefact.json) == artefact_sha256`.

### 3.7 Driver, units, stall watch, reproducibility

**Plug-in.** `AR/plugin.py::FqRefitter` implements C6 `Refitter.refit(windows) -> (artefact, Lineage) | NOT_FITTABLE(reason)`, registered in `OFFLINE_PLUGINS["forecast_quantile_ladder"]`.

**Driver** (`AR/driver.py::run_daily(now, registry_reader, c1_reader, c2_reader, window_index_fn, plugins, sink)`):
1. **Producer pin.** Closure hash must be in `PRODUCER_SOURCE_SHA256["aut3_refit"]` (CRITICAL, exit 3).
2. **Clean tree.** `git -C <tree> status --porcelain -- <closure files>` empty; `git rev-parse HEAD` recorded; dirty → CRITICAL, exit 3.
3. **Fold.** Read-only verified per-venue fold: champions (or the last RETIRED champion after a KILL, ARCH §5.3), allowlisted lineage roots, MINT rows, `lineage_counters`.
4. **Mint limit, fit, write** per §3.3; writes `evidence/refit/refit_run_<YYYY-MM-DD>.json`; logs `REFIT_RESULT lineage=<id> model_class=<mc> status=<…> reason=<r|-> artefact_sha256=<sha|-> n_eff=<k> gate_decisions_changed=<n|-> window=<w> mints_in_window=<m>/<K>`.
- **Failure handling.** Registry unreadable → CRITICAL, no refit. C2 unreadable → rung_recal `NOT_FITTABLE(c2_unreadable)` + CRITICAL; density still runs. Nothing to do → exit 0 with `NO_INPUT`.

**`refit_run/v3`** (non-C evidence record; bumped from v2 for the new fields):
- Fields: `schema`, `run_date`, `started_at_ns`, `finished_at_ns`, `producer_code_sha`, `code_git_sha`, `results[]`, `prior_mint_status[]` (`{artefact_sha256, minted|MINT_REFUSED_CEILING|pending}`), `peak_rss_bytes`, `snapshot_bytes_written`, `drill`.
- Each `results[]` entry: `{lineage_root_family_id, composition_kind, model_class|null, status, reason|null, artefact_sha256|null, data_windows[], params, seed, window_index, mints_in_window, k_max_effective, k_life_at_run, nominal_only}`. Every outcome (including `NO_CHANGE(k_max_reached)` and `NOT_FITTABLE`) carries window hashes, parameters and seed, so **every run is lineage-complete**.
- Exact-set, atomic, 0444, no paths or env values.

**CLI entry points:** `scripts/analysis/autonomy_refit_daily.py`, `scripts/analysis/autonomy_refit_reproduce.py`. Interpreter `/home/jon/breezy/.venv/bin/python`.

**Shared environment.** Both units and every drill: `Environment=OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONHASHSEED=0 OPENBLAS_CORETYPE=<WP0 value>`; host CPU i7-11700K; `params.cpu_model` recorded; a repro on a different `cpu_model` is `REPRO_ENV_CHANGED`, never a pass.

**Units** in `deploy/systemd/`:

`breezy-autonomy-refit.service`: `Type=notify`, `NotifyAccess=main`, `WatchdogSec=1200`, `TimeoutStartSec=120`, `RuntimeMaxSec=12600` (effective after READY; the 1800 s lock wait is inside it, so the fit budget is 10 800 s); `Slice=breezy-studies.slice`; `OnFailure=breezy-study-failed@%n.service`; `MemoryHigh`/`MemoryMax` = `max(4G, 1.5 × WP0 peak)` ≤ 16G (provisional 3G/4G); shared environment; `EnvironmentFile=-%h/.config/breezy/alerts.env` only; `UMask=0077`.

`breezy-autonomy-refit.timer`: `OnCalendar=*-*-* 06:00:00 UTC`, `Persistent=true`, `AccuracySec=1min`. Worst end 06:00 + 120 s + 12 600 s ≈ 09:32Z: before ARCH's 16:30Z study bound and AUT-4's 11:00Z offline slot.

`breezy-autonomy-refit-reproduce.{service,timer}` — **slot selected by a pre-declared rule (new ARCH contradiction C-11, §8):**
- **Primary (ARCH-literal):** `OnCalendar=*-*-* 09:35:00 UTC` (ARCH Rev 5 §5.2 indicative "reproducibility rerun … 09:30"), lock wait 600 s, `RuntimeMaxSec=4800`, worst end ≈ 10:57Z, before AUT-4's 11:00Z offline unit (which waits up to 900 s for the lock, AUT-4 r2 §3.9). Each sampled C3 is reproduced only if its lineage `runtime_s × 1.2 + 600 ≤ 4800`; otherwise it is recorded `REPRO_DEFERRED_SLOT`.
- **Secondary (needs ARCH Rev 7):** `OnCalendar=*-*-* 18:00:00 UTC`, lock wait 1800 s, `RuntimeMaxSec=21600` (ends ≤ 00:32Z, before the 01:00–04:30Z heavy blackout), for density_table candidates whose full refit does not fit the primary slot. ARCH Rev 5 §5.2 says every study "ends before 16:30Z", which forbids this slot as written; AUT-6 r2 already uses the window form "no study window intersects [16:30Z, 17:10Z)". The secondary unit is **not enabled** until ARCH Rev 7 adopts that form.
- Consequence if ARCH keeps the literal rule and the WP0 full-fit p95 exceeds about 60 min: density_table candidates are never reproduced in full (`REPRO_DEFERRED_SLOT` every time), the live proof's `REPRO_PASS ≥ 1` must come from a rung_recalibration C3 (cheap: one 1-D fit), and "reproducible bit for bit" is reported as proven for rung_recalibration only.

**Lock and memory table.** Every value is measured in WP0 before WP7 merges.

| Unit | Slot (UTC) | Lock | Provisional MemoryMax | Measured peak | Bound |
|---|---|---|---|---|---|
| `breezy-autonomy-refit` | 06:00 | `breezy-studies.lock` (Python flock, wait 1800 s) | 4G | WP0 (ii) | `RuntimeMaxSec=12600` + `WatchdogSec` |
| `breezy-autonomy-refit-reproduce` | 09:35 (primary) / 18:00 (secondary, gated) | `breezy-studies.lock` (600 s / 1800 s) | = refit | WP0 (ii) | `RuntimeMaxSec=4800` / `21600` + `WatchdogSec` |
| drill runs (`systemd-run --user`) | ad hoc, outside 01:00–04:30Z and [16:30Z, 17:10Z) | `breezy-studies.lock` | 4G | — | `-p RuntimeMaxSec` |
| WP0 benchmark and simulation | ad hoc | `breezy-studies.lock` | 16G / 4G | measured | `-p RuntimeMaxSec=14400` / `7200` |

**Gate.** WP7 does not merge unless measured peak × 1.5 ≤ 16G **and** measured p95 + 1800 s ≤ `RuntimeMaxSec`; otherwise the contingency estimator is adopted first.

**Stall watch.** `READY=1`, then a polled `fcntl.flock` up to the lock wait while pinging `WATCHDOG=1`. Lock timeout → `SKIPPED_LOCK` WARN, CRITICAL on the second consecutive day. During the fit the `FitProgress` callback (S6) pings `WATCHDOG=1` and logs `REFIT_PROGRESS stage=<s> done=<k>/<n> rss_mb=<m>` at every stage boundary, every κ grid point and every 10 draws. Watchdog expiry kills the unit; `OnFailure` alerts. WP0 (iii) drills both bounds on a throwaway notify unit (**INFERRED** until then).

**Reproducibility** (`AR/reproduce.py`):
- **Sample:** every C3 from the last 7 days whose sha first byte < `REPRO_SAMPLE_BYTE_THRESHOLD` (26, ≈ 10%), plus the newest C3 of the ISO week if none was sampled; at most `REPRO_MAX_PER_RUN` (1), oldest first.
- **Extract:** `git archive <code_git_sha> | tar -x` into `~/.cache/breezy/refit-repro/<sha>/`, read-only, not a worktree; `PYTHONPATH` = the extract; extract closure hash must equal `producer_code_sha`.
- **Full refit from snapshot bytes** (rung_recal from `label_draw_partitions` and `probe_gate_inputs`; density from the NBP and settlement segments), then **every leakage assertion and the X22 gate count re-run from the snapshot bytes**, compared name by name. Separately, the partition recompute is re-verified from `label_forecast_percentiles` plus the content-addressed artefact draws (S5).
- **Outcomes:** equal sha and every assertion equal → `REPRO_PASS`; mismatch → `REPRO_MISMATCH` (CRITICAL, exit 1); differing `uv_lock_sha256`/`cpu_model` → `REPRO_ENV_CHANGED` (WARN, not a pass); slot too short → `REPRO_DEFERRED_SLOT` (INFO, not a pass).
- Result: `evidence/refit/repro_<date>.json` (`refit_run/v3`, `kind=repro`).

**Disk growth.** `snapshot_bytes_written` per run; WP0 (ix) measures the first snapshot and the daily increment including `label_draw_partitions`; `REFIT_STORE_DISK_BUDGET_BYTES` (2 GiB through the KILL); WARN at 80%, `NOT_FITTABLE(disk_budget)` + CRITICAL at 100%.

### 3.8 Live loader widening (G11) and the envelope

New `LEV/rung_recalibration.py`:
- `RungRecalibration(form: Literal["none","affine"], shift: float | None)`, frozen, slotted; `affine` means `(intercept=shift, slope=1.0)`.
- `apply(partition)` mirrors `_apply_recalibration_scalar` and `apply_probability_recalibration` exactly (clip, renormalise in the given rung order, assert the sum is 1 within 1e-12).
- `is_emittable(form, affine) -> bool`: the single predicate the writer and loader share (`none ∧ affine is None`, or `affine ∧ affine[1] == 1.0 ∧ isfinite(affine[0]) ∧ C_IDENTITY_EPS ≤ |affine[0]| ≤ C_BOX`).
- `REFIT_EMITTABLE_RECALIBRATION_FORMS: Final = frozenset({"none","affine"})`; `C_BOX`, `C_IDENTITY_EPS` `Final`, pinned to the policy ruling by test.
- `enveloped_bounds(base, recal) -> (recal_p, min(base_lo, recal_lo), max(base_hi, recal_hi))`.

`LEV/quantile_density.py` (bit-identical split, S5): `per_draw_rung_probabilities(percentiles, method, draws, rungs) -> tuple[dict[str, float], ...]` (draw order) and `interval_from_per_draw(per_draw, rungs, *, level=0.95, recalibration=None)`; `rung_probability_interval` becomes their composition and gains `recalibration: RungRecalibration | None = None`. With `None`/`none` the output is bit-identical to today's (`::test_none_recalibration_is_bit_identical`, `::test_split_composition_bit_identical_to_original`).

**Why an envelope.** Renormalisation (`CAL:1655-1658`) makes "g(p) ≤ p" vacuous (`0.9p` is the identity after renormalisation), and any non-identity partition map must raise some rung; lowering a rung raises NO-leg confidence (`ev_net_no` uses `1 − p_upper`, `LEV/scoring.py:70-82`). The envelope gives, per rung: YES gate input `p_lower_eff ≤ p_lower_base`; NO gate input `1 − p_upper_eff ≤ 1 − p_upper_base`.

**Scope of "only removes takes" (S8).** Because the parent is unrecalibrated (§3.4(d)), base = parent = champion, so **per (rung, side) gate decision** a candidate's eligible set is a subset of the champion's. It is **not** a path-wise guarantee about orders, for two disclosed reasons:
1. **Daily budget.** The venue daily budget (an operator cap; never read or assigned by AUT-3) is consumed by earlier takes. If a candidate removes an early take, budget remains for a later decision the champion would have skipped for budget, so the candidate's realised orders can include a take the champion never placed. Each such take still passes the candidate's own (more conservative) gate.
2. **AMBIGUOUS latch.** An OPEN AMBIGUOUS intent denies every order until it is retired (memory `first-live-order-was-ambiguous`; `3eb4a108`). Removing a take that would have gone AMBIGUOUS can leave the latch closed, so later takes occur that the champion's path would have blocked; the reverse (a different take going AMBIGUOUS) is also possible.
Therefore AUT-4 must evaluate candidates path-wise (replay through the real strategy and budget), never by assuming the subset property for P&L or exposure. Caps are unaffected: `QTY = 1` (`FQ/decision.py:73`), and the per-order and daily caps bind every path identically.

The envelope is **unconditional code with no flag**. `p_hat` is the recalibrated mean; it is recorded in C1 and scored by AUT-4's Brier and feeds no gate (`FQ/decision.py:331-349`).

`FQ/calibration_artefact.py`: `_SUPPORTED_RECALIBRATION` becomes `REFIT_EMITTABLE_RECALIBRATION_FORMS`; acceptance uses `is_emittable`; `isotonic` and unknown forms stay refused; `LiveCalibration` gains `recalibration: RungRecalibration`.

`ArtefactBoundsProvider.__init__` gains `recalibration`; `__call__` computes per-draw base partitions once and returns `enveloped_bounds(interval_from_per_draw(base), interval_from_per_draw(base, recalibration))`. `FQ/composition.py::build_forecast_quantile_ladder_strategies` and `scripts/analysis/nbp_shadow_parity.py` pass `live_calibration.recalibration`. AUT-4 evaluates through the same provider.

**Re-targeted safety test.** `test_unsupported_probability_recalibration_is_refused` (`tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py:191`) uses `"affine"` as its unsupported example. Under this reviewed L-12 one-row widening its example is re-pointed to `"platt"` and `"isotonic"`, never deleted or loosened, with security-reviewer and python-reviewer sign-off in WP2, and refusal tests are added for every excluded `affine` shape.

### 3.9 Statistical capacity

About 5 fills a day cluster into fewer station-days (L-40). `MIN_NEFF_TO_EMIT` and `N0` are set by WP0 (x) under the pre-declared rule (§3.4), not chosen here. A large ridge keeps c near 0 at small n_eff, so early candidates are `NOT_FITTABLE(gate_noop)`; the simulation measures how often, and the unreachability rule says what is claimed if the target is not met before the KILL.

### 3.10 Rulings AUT-3 drafts (peer-reviewed by mle-reviewer and prediction-market-reviewer; not operator decisions)

1. **`docs/evidence/RULING_aut3_refit_policy_<date>.md`**, one fenced block `aut3-refit/v3` (strict JSON, exact-set keys):
   - `ROLLING_V5_DAYS = 365`, `C_BOX = 0.05`, `C_IDENTITY_EPS = 1e-9`;
   - `N0` and `MIN_NEFF_TO_EMIT` **from WP0 (x)** under the selection rule; `REACH_TARGET = 0.8`, `REACH_SIM_SEED`, `REACH_SIM_REPS = 2000`, the grid, the measured `r`, the projected dates and the reachability verdict (reachable by date X, or unreachable before 2027-01-25 with the earliest n_eff and date);
   - `MIN_GATE_DECISIONS_CHANGED = 1`, `MIN_P_SPREAD = 0.10`, `MAX_OFF_SUPPORT_DELTA = 0.02`;
   - `P_REPRO_ABS_TOL = 1e-12`, `OWN_LABEL_HOLDOUT_DAYS = 7`;
   - `SEASONAL_GAP_MAX_DCRPS = 0.02`, `MIN_FORWARD_DAYS_FOR_DENSITY`, the seasonal verdict;
   - `REPRO_SAMPLE_BYTE_THRESHOLD = 26`, `REPRO_MAX_PER_RUN = 1`, `REFIT_STORE_DISK_BUDGET_BYTES = 2147483648`.
   - It does **not** restate K_max, `forward_window_days`, `K_LIFETIME_EFFECTIVE` (pins.py / `autonomy-policy/v1`) or the holdout bounds (`RULING_holdout_freeze_and_forward_window_2026-10-03`). It states the evidence class and the absence of a weather holdout for `density_table`. `MIN_PROBE_DELTA` and `MIN_MINT_DELTA` are withdrawn.
2. **`docs/evidence/RULING_aut3_readme_alignment_<date>.md`.** One amendment: README §AUT-3 "execution data (fill, slippage and refusal), where the model class consumes them" becomes "no FQ model class consumes execution data as a predictor (operator ruling 09-29: venue prices are execution cost only); execution data enters AUT-4's EV net of cost, and AUT-3 reads the ask and `ev_net` only as execution cost to count gate decisions". The r2 live-proof counting item is withdrawn: the coordinator already amended the README (`README.md:116`). README edits remain coordinator actions.

---

## 4. Work packages

**Common gate (G)**, after every merge (L-43). Read the exit code, never the `-q` output.
- `scripts/ci/run_tests_no_egress.sh` with `/home/jon/breezy/.venv/bin/python` and `PYTHONPATH=<tree>/src:<tree>` in a worktree.
- `cd <tree> && /home/jon/breezy/.venv/bin/lint-imports` → `N kept, 0 broken`.
- `cd <tree> && /home/jon/breezy/.venv/bin/python -m mypy` plus `tests/unit/test_mypy_ratchet.py`; new packages into `[tool.mypy] files` after grepping `tests/` for pins of that list (L-54).
- **Never** `uv`, `uv run`, `pip` or `git stash`. Each agent uses its own scratchpad.

| WP | Scope and files | RED tests first (path::name) | GREEN criterion | Activation |
|---|---|---|---|---|
| **AUT-3.WP0** L-1 checks, measurement, simulation | No source change. Evidence: `docs/evidence/AUT3_WP0_<date>.md`. **(i)** `Splits` tagging. **(ii)** Full `fit_calibration` in `systemd-run --user -p MemoryMax=16G -p RuntimeMaxSec=14400 -p LimitNOFILE=524288`, outside 01:00–04:30Z, lock held: peak RSS, wall, swap. **(iii)** Watchdog/`RuntimeMaxSec` drill on a throwaway notify unit. **(iv)** Same-input sha identity under the pinned env. **(v)** Python flock helper. **(vi)** Champion = BOOTSTRAP sha. **(vii)** Seasonal-gap experiment. **(viii)** Partition recompute reproduces C1/shadow-log `p_hat`, `p_lower`, `p_upper` with difference exactly 0 (≤ 1e-12) for the 10-02/10-03 FQ fills; forecast vector retrievable by digest. **(ix)** Snapshot bytes incl. `label_draw_partitions`. **(x)** Reachability simulation and accrual rate (§3.4, S4). **(xi)** Margin recompute reproduces every 10-02.. `Take`/`Refuse(below_margin)` classification. | Characterisation, no RED (L-33). Mutation evidence: changed seed changes the sha; perturbed forecast vector fails (viii); a reordered ladder changes the renormalised partition beyond 0 (S5 order sensitivity); a simulation with c*=0 and N0→∞ gives `P_reach ≈ 0` (non-vacuity control) | Every number recorded; N0, `MIN_NEFF_TO_EMIT`, reachability verdict, lock table, repro slot choice and seasonal verdict drafted into the policy ruling | none |
| **AUT-3.WP1** Rulings and constants | the two rulings; `AR/__init__.py`, `AR/windows.py` | `tests/unit/autonomy_refit/test_aut3_ruling_pins.py::test_policy_constants_equal_ruling_block`; `::test_ruling_block_is_exact_set_strict_json`; `::test_ruling_block_has_no_kmax_or_holdout_keys`; `::test_sealed_bounds_equal_holdout_freeze_ruling`; `tests/unit/autonomy_refit/test_windows.py::test_sealed_days_never_in_density_or_label_window`; `::test_train_end_is_run_day_midnight_and_forward_start_next_day`; `::test_v5_forward_floor_is_seal_end`; `::test_density_waits_for_min_forward_days_when_gap_rejected`; `::test_window_index_is_alpha_ledger_function` (identity) | Both rulings SOUND; ARCH holdout ruling filed; G green | rulings filed on merge |
| **AUT-3.WP2** G11 widening, envelope, live application | `LEV/rung_recalibration.py` (new); `FQ/calibration_artefact.py`; `LEV/quantile_density.py`; `FQ/artefact_bounds.py`; `FQ/composition.py`; `scripts/analysis/nbp_shadow_parity.py` | `tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py::test_affine_shift_recalibration_is_accepted_and_parsed`; `::test_unsupported_probability_recalibration_is_refused` (re-pointed to platt/isotonic, L-12 row); `::test_affine_slope_not_one_is_refused`; `::test_affine_shift_outside_box_is_refused`; `::test_affine_shift_below_identity_eps_is_refused`; `::test_affine_nonfinite_or_missing_is_refused`; `::test_none_with_affine_coefficients_is_refused`; `tests/unit/test_refit_emit_set_equals_live_accept_set.py::test_emittable_recalibration_forms_equal_live_supported`; `::test_writer_and_loader_share_is_emittable`; `tests/unit/test_fq_live_analysis_point_cdf_parity.py::test_live_affine_shift_matches_analysis_apply_probability_recalibration` (≤1e-12 per rung, 200 seeded draws × 3 CDF methods × 2 ladders); `tests/unit/test_ladder_ev_quantile_density.py::test_recalibration_applied_per_draw_before_interval`; `::test_none_recalibration_is_bit_identical`; `::test_split_composition_bit_identical_to_original`; `tests/unit/test_rung_recalibration_envelope.py::test_enveloped_bounds_never_more_confident_on_either_leg` (10 000 seeded partitions); `::test_affine_that_is_identity_after_renorm_yields_zero_delta`; `::test_candidate_never_adds_takes_vs_recalibrated_champion` (S2: for a recalibrated champion fixture, a hand-built rung_recal child is refused by the writer predicate and the refitter returns `NOT_FITTABLE(parent_recalibrated)`; for an unrecalibrated champion, over 10 000 seeded partitions, asks and margins, every candidate's eligible `(rung, side)` set ⊆ the champion's); `tests/strategy/forecast_quantile_ladder/test_artefact_bounds.py::test_provider_returns_enveloped_bounds`; `::test_provider_forwards_recalibration`; `tests/strategy/forecast_quantile_ladder/test_sl13_wiring.py::test_composition_passes_artefact_recalibration`; L-55: `::test_committed_champion_loads_through_production_loader_with_none` | Parity ≤1e-12; champion bounds bit-identical; G green; security-reviewer and python-reviewer sign off the L-12 re-point | Behaviour-neutral for the champion; takes effect at the next 16:50Z LAUNCH. Reason for not relaunching mid-day: no behaviour change, and a hand relaunch carries AMBIGUOUS-intent and permit risk. |
| **AUT-3.WP3** Snapshot, leakage, gate probe, C3 writer | `AR/inputs.py`, `AR/leakage.py`, `AR/gate_probe.py`, `AR/c3_writer.py` | `tests/unit/autonomy_refit/test_inputs_snapshot.py::test_snapshot_sha_independent_of_input_order`; `::test_fixed_segment_dedupes_across_runs`; `::test_draw_partitions_segment_round_trips_bit_exact` (S5); `::test_snapshot_files_are_0444_and_nofollow`; `tests/unit/autonomy_refit/test_leakage.py::test_sealed_row_injected_after_snapshot_filter_fails`; `::test_forecast_available_after_cutoff_fails_ref_ts_lt_take_ts`; `::test_label_after_train_end_fails`; `::test_probe_after_train_end_fails`; `::test_train_end_after_forward_start_fails`; `::test_canary_drill_unreconciled_exit_rows_fail_admissible_entry_only`; `tests/unit/autonomy_refit/test_gate_probe.py::test_candidate_ev_net_uses_slope_one_affinity_matches_full_recompute` (vs `edge_after_costs` on fixtures); `::test_gate_flip_counted_true_to_false_only_under_envelope`; `::test_density_flips_counted_both_directions_and_refuse_sparse_flagged`; `::test_parent_not_qualifying_probe_excluded_by_name`; `::test_live_statistic_used_not_mean_partition` (S5: a fixture where g(mean π) ≠ mean g(π_d) changes the count); `tests/unit/autonomy_refit/test_c3_writer.py::test_writes_content_addressed_0444_0500`; `::test_refuses_any_failed_assertion`; `::test_refuses_ablation_equal_to_artefact`; `::test_affine_that_is_identity_after_renorm_fails_x22` (`(0.0, 0.9)`; recomputed gate count 0); `::test_refuses_gate_decisions_below_min`; `::test_refuses_neff_below_min`; `::test_refuses_off_support_gate_delta_above_max`; `::test_refuses_slope_not_one_or_shift_outside_box`; `::test_refuses_rung_recal_with_recalibrated_parent` (S2); `::test_refuses_c3_when_mints_in_window_at_kmax` (S1); `::test_writer_recomputes_and_refuses_lineage_disagreement`; `::test_refuses_non_ok_fit_status`; `::test_existing_sha_writes_no_new_lineage`; `::test_refuses_symlink_anywhere_on_path`; `::test_second_c3_same_lineage_same_utc_day_refused`; `::test_refuses_repo_and_deploy_families_roots`; `::test_disk_budget_exhausted_writes_nothing_critical`; `::test_payload_hygiene_no_paths_or_env` | Every refusal RED→GREEN; G green | library only |
| **AUT-3.WP4** density_table refitter and progress hook | `AR/rows.py`, `AR/fq_density_refitter.py`; `CAL` (keyword-only `progress`, `FitProgress`); `pins.py` rotation for closures containing `CAL` | `tests/unit/test_nbp_calibration.py::test_fit_calibration_progress_none_and_callback_bit_identical` (S6: `CalibrationFit` and `artefact_sha256` equal with None, with a recording callback, and via `run_validate_gates_from_rows`); `::test_progress_reports_kappa_points_and_every_10_draws`; `::test_progress_exception_propagates`; `tests/unit/autonomy_refit/test_fq_density_refitter.py::test_refit_changes_only_v5_params_draws_kappa`; `::test_bit_for_bit_reproducible_from_snapshot`; `::test_fit_rows_object_is_the_asserted_and_snapshotted_object`; `::test_rolling_rows_exclude_sealed_holdout_under_both_paths`; `::test_gate_noop_returns_not_fittable` (S3); `::test_carries_parent_correction_and_recalibration_none`; `::test_lineage_records_windows_code_params_seed_cpu`; `::test_nonconverged_fit_writes_nothing`; `::test_progress_callback_pings_watchdog_sink` | Existing callers bit-identical; fixture fit reproducible; G green | library only |
| **AUT-3.WP5** rung_recalibration refitter (the C2 consumer) | `AR/fq_rung_recal_refitter.py`, `AR/partitions.py` | `tests/unit/autonomy_refit/test_fq_rung_recal_refitter.py::test_leave_labels_out_changes_sha_and_changes_a_gate_decision` (X22, functional); `::test_ablation_sha_equals_parent_sha_when_parent_none` (S11); `::test_ablation_built_from_bytes_not_from_empty_fit` (S11); `::test_fit_is_one_parameter_with_live_statistic_in_objective` (S5); `::test_estimator_clamps_into_box_writer_never_refuses_it`; `::test_unidentified_when_neff_spread_or_stations_short`; `::test_gate_noop_not_own_outcome_candidate` (S3); `::test_off_support_gate_distortion_gated`; `::test_parent_recalibrated_not_fittable` (S2); `::test_label_from_other_gate_excluded` (S9); `::test_labels_from_other_emos_excluded`; `::test_no_label_oriented_to_yes_domain` (L-44); `::test_yes_oriented_p_on_no_fill_fails_orientation_assertion`; `::test_exit_labels_excluded`; `::test_live_path_p_hat_equals_training_statistic`; `::test_recompute_diff_is_exactly_zero_on_live_order` (S5); `::test_partition_recompute_mismatch_excludes_label_by_name`; `::test_cluster_weights_sum_to_one_per_station_day`; `::test_selection_population_recorded` (S7); `::test_advisory_time_block_recorded_never_gates`; `::test_estimator_reads_no_venue_price_fields` (AST; only `gate_probe` may); `::test_refit_never_calls_open_holdout` (AST); `::test_identity_canonicalised_to_none` | C2 fixture through the real AUT-2 label writer and C1 fixture through the real capture writer (L-42); G green | library only |
| **AUT-3.WP6** Plug-in, driver, CLI | `AR/plugin.py`, `AR/driver.py`, `AR/locks.py`, `AR/sd_notify.py`; `scripts/analysis/autonomy_refit_daily.py`; `pins.py` `PRODUCER_SOURCE_SHA256["aut3_refit"]` | `tests/unit/autonomy_refit/test_driver.py::test_every_live_gate_routed_kind_has_a_fitting_refitter`; `::test_refusing_plugin_kind_not_fittable_and_never_writes_c3`; `::test_older_component_first_and_one_c3_per_lineage_per_day`; **`::test_kmax_reached_stops_minting_records_no_change_and_counts_toward_streak`** (re-pointed from r2's `test_past_kmax_still_writes_and_records`, S1); `::test_pending_c3_reserves_a_window_slot`; `::test_window_rollover_resets_mints_in_window_only`; `::test_refit_never_writes_or_resets_lineage_counters` (S1, k_life); `::test_nominal_only_flag_past_k_lifetime_effective`; `::test_gate_noop_records_not_fittable_with_full_lineage`; `::test_mint_refused_ceiling_recorded_next_run_and_releases_slot`; `::test_every_outcome_record_is_lineage_complete`; `::test_dirty_closure_refuses_exit_3`; `::test_registry_unreadable_critical_no_refit`; `::test_c2_unreadable_runs_density_and_alerts`; `::test_nothing_to_do_exits_zero_no_input_line`; `::test_refit_run_v3_exact_set_and_hygiene`; `::test_producer_pin_mismatch_refuses_exit_3`; `::test_critical_alerts_go_through_deliver_with_proof`; L-55: `::test_run_daily_with_production_default_seams`; envelope: `test_autonomy_never_reads_or_writes_operator_controls`, `test_autonomy_never_imports_order_path`, `test_autonomy_payload_hygiene_scan`, `test_code_identity_pins_cover_import_closure` (extended) | G green; pin in the same commit as the closure | library plus CLI |
| **AUT-3.WP7** Units, schedule, stall watch, activation | `deploy/systemd/breezy-autonomy-refit.{service,timer}`; README unit table | `tests/unit/test_analysis_units_memory_capped.py::test_autonomy_refit_units_capped_and_bounded`; `::test_no_oneshot_unit_relies_on_runtime_max_sec_alone`; `tests/unit/autonomy_refit/test_schedule.py::test_refit_ends_before_1630_and_aut4_offline_and_avoids_0100_0430`; `::test_sd_notify_pings_watchdog_on_progress` (real socket); `::test_lock_timeout_records_skipped_lock_warn_then_critical` | G green; `systemd-analyze --user verify` clean; WP0 peak × 1.5 ≤ 16G and p95 + 1800 s ≤ `RuntimeMaxSec` | **Immediate on merge:** symlink, `daemon-reload`, `enable --now breezy-autonomy-refit.timer`; confirm `breezy-studies.slice` MemoryMax ≠ `infinity`. Before C2 exists, rung_recal reports `NOT_FITTABLE(c2_absent)`. |
| **AUT-3.WP8** Reproducibility job | `AR/reproduce.py`; `scripts/analysis/autonomy_refit_reproduce.py`; `deploy/systemd/breezy-autonomy-refit-reproduce.{service,timer}` (09:35Z primary) | `tests/unit/autonomy_refit/test_reproduce.py::test_reproduce_from_snapshot_and_git_archive_matches_sha`; `::test_rung_recal_refit_from_draw_partitions_snapshot` (S5); `::test_partition_recompute_reverified_from_percentiles_snapshot` (S5); `::test_every_leakage_assertion_and_gate_count_rerun_from_snapshot_bytes`; `::test_assertion_disagreement_is_mismatch`; `::test_mismatch_critical_exit_1`; `::test_env_or_cpu_changed_classified_not_pass`; `::test_slot_too_short_is_deferred_not_pass`; `::test_sample_rule_deterministic_and_weekly_forced`; `::test_extract_closure_hash_must_equal_producer_code_sha`; `::test_repro_unit_env_equals_refit_unit_env`; `::test_repro_primary_slot_ends_before_aut4_offline_and_1630` | G green | Immediate on merge: enable the 09:35Z timer. The 18:00Z secondary unit file ships disabled and is enabled only after ARCH Rev 7 adopts the window form (C-11). |
| **AUT-3.WP9** Live-proof report | `scripts/analysis/aut3_live_proof_report.py` (read-only) | `tests/unit/autonomy_refit/test_live_proof_report.py::test_streak_counts_recorded_consumed_runs`; `::test_no_change_kmax_not_fittable_mint_refused_count_when_consumed` (S1); `::test_skipped_lock_or_failed_breaks_streak`; `::test_requires_minted_own_outcome_candidate_meeting_gate_threshold` (S3); `::test_gate_noop_never_counts_as_own_outcome`; `::test_requires_aut4_ack_for_every_run_and_verdict_for_every_candidate`; `::test_inconclusive_window_cap_verdict_counts_as_consumed` (ALPHA §3); `::test_requires_one_repro_pass_in_window`; `::test_reports_reachability_verdict_and_score2_when_unreachable` (S4) | G green | Run by hand only by the independent scorer; no timer |

---

## 5. Association

| Contract | Direction | Exact interface |
|---|---|---|
| C1 | consumed (AUT-1) | `DecisionRecord.{decision_id, kind, reason, eval_ns, side, rung_id, ask_px, ev_net, p_hat, p_lower, p_upper, forecast_input_sha256, artefact_sha256, manifest_sha256}` via ARCH-0's reader; ARCH-0's `forecast_input_digest` helper (INFERRED name) |
| C2 | consumed (AUT-2) | `label/v1` via ARCH-0's reader, admitted per §3.4(a); `p_at_decision` = P(bought leg wins) (AUT-2 r2 §3.4.4); `label_outcomes_ok_<date>` marker |
| C3 | **provided** | `derived/artefacts/<model_class>/<sha>/{artefact.json, lineage.json}`; ≤ 1 per lineage per UTC day; ≤ K_max MINT-bound C3 per lineage per forward window; gate-count gated |
| `refit_run/v3` | **provided** | `evidence/refit/refit_run_<date>.json`: every run outcome, lineage-complete, with `window_index`, `mints_in_window`, `k_max_effective`, `k_life_at_run`, `nominal_only` |
| C4 | none written | AUT-6's `refit_freshness` and `refit_repro` map to `HEALTH`; AUT-4 records `k_life`, `alpha_k`, `mints_in_window`, `n_min_eff`, `n_cap` (ALPHA decision 4) |
| C5 | consumed (AUT-5) | Read-only fold: champion, `lineage_root_family_id`, bound sha, MINT rows (window count, `prior_mint_status`), `lineage_counters.candidates_evaluated` (read for `k_life_at_run`); the `autonomy-policy/v1` K_max. AUT-3 never writes the registry. |
| C6 | **provided** | `Refitter` for `forecast_quantile_ladder`; `RefusingPlugin` for the rest |
| AUT-4 | both | **Consumed:** `alpha_ledger.forward_window_index` (AUT-4 r2 §3.5). **Provided/requested:** AUT-4 reads every new C3 and emits verdicts (expected `INCONCLUSIVE(window_cap_below_n_min)`, ALPHA §3); **request (kept from r2):** acknowledge every `refit_run/v3` record (`refit_run_ack{run_date, lineage, status, consumed_at_ns}`); evaluate rung_recal candidates through `ArtefactBoundsProvider` with the envelope and **path-wise** (budget and latch interactions, §3.8) |
| Delivery | consumed (AUT-6) | `deliver_with_proof` |
| AUT-7 | downstream | Re-verifies `sha256(artefact.json)` on rollback |

**Execution order.** ARCH-0 first. Wave 1 (disjoint files): WP0, WP1, WP3, WP4. Wave 2, after AUT-2b, AUT-1 C1 and AUT-4's `alpha_ledger`: WP5 and WP6. WP2 follows AUT-1's and AUT-5a's edits to `FQ/strategy.py`/`FQ/composition.py` and is rebased onto them. WP7 follows WP6 and WP0's measurements. WP8 follows WP7. WP9 follows AUT-4's offline consumer and the run ack. Parallel: WP3 ∥ WP4; WP5 ∥ WP2.

---

## 6. Live-proof protocol

**Artefacts that prove score 3:**
1. Seven consecutive `evidence/refit/refit_run_<date>.json` records on qualifying days, timer-started (`systemctl --user show -p TriggeredBy`), each per-lineage status in `{CANDIDATE, NO_CHANGE(k_max_reached|existing_sha), NOT_FITTABLE(*), MINT_REFUSED_CEILING}`, each with full `data_windows`, `params`, `seed`.
2. An AUT-4 `refit_run_ack` for each of the 7, and for each `CANDIDATE` a C4 verdict citing the sha (expected `INCONCLUSIVE(window_cap_below_n_min)`), plus the AUT-5 MINT row or the recorded `MINT_REFUSED_CEILING`.
3. Every C3 in the window: `[.leakage_assertions[].passed] | all == true`.
4. At least one **minted** `rung_recalibration` C3 with `own_outcome_label_set_sha256 ≠ null`, `ablation ≠ artefact`, `gate_decisions_changed ≥ MIN_GATE_DECISIONS_CHANGED` and `n_eff ≥ MIN_NEFF_TO_EMIT` (the WP0-set value).
5. At least one `REPRO_PASS` in the window.
6. The WP9 report `~/.local/share/breezy/evidence/refit/aut3_live_proof_<date>.md`, with `STREAK_RUNS`, `STREAK_CANDIDATES` (informational) and the reachability verdict.

**Claim rule.** Score 3 = `STREAK_RUNS ≥ 7` plus items 2–5, under the amended README. If WP0 (x) declares the own-outcome leg unreachable before the KILL, or WP0 (viii) fails without the C1 fallback, AUT-3 reports **score 2** with the earliest n_eff and date, never 3. The runs are not independent samples.

**Window rule (ARCH §5.3).** A day counts only with ≥ 1 real fill or a production-path canary fill; the window needs ≥ 5 real fills. `SKIPPED_LOCK`/`FAILED` on a qualifying day breaks the streak. Canary and drill labels never train.

**Failure-mode drills for (d).** One-shot `systemd-run --user` of the production script with `--drill <kind>` and the shared environment, outside 01:00–04:30Z and [16:30Z, 17:10Z). Drill runs never write C3, tag `refit_run.drill=true`, and are refused without the flag. Kinds: `stall`, `runtime`, `lock`, `oom`, `repro-mismatch` (a tampered copy of a snapshot), `pin`, `dirty`, `disk`, **`kmax`** (a fold fixture copy with `mints_in_window = K_max`; expects `NO_CHANGE(k_max_reached)` and no C3). Delivery proven by AUT-6's `evidence/alerts/delivery_<date>.jsonl` with `delivered=true`.

**Accrual ETA (S4, honest).**
- ARCH-0 by about 10-10; Wave 1 by about 10-17; AUT-2b C2 with `p_at_decision` by about 10-24; AUT-4 offline consumer, run ack and engine MINT by about 11-07.
- Own-outcome candidate: on `date(MIN_NEFF_TO_EMIT)` from WP0 (x) (projection table §3.4). With r = 2 and `MIN_NEFF_TO_EMIT = 30`, labels suffice by about 10-17 and the binding dependency is AUT-4 (11-07): **earliest DONE about 2026-11-14, planning ETA 2026-11-21**. With `MIN_NEFF_TO_EMIT = 60` and r = 1: about 12-01 → DONE about 12-10. With `MIN_NEFF_TO_EMIT = 120` and r ≤ 1, or r ≤ 0.5 at 60: **unreachable before 2027-01-25**, reported as score 2 with the earliest date.
- If fills stop (an A1-style halt or DEMOTE), the own-outcome leg waits; `r` is re-measured and the projection re-issued in the WP9 report.

**Evidence class: machinery proven, edge unproven.** No edge verdict is pre-registered here.

---

## 7. Score-3 verification checklist (for an independent scorer)

| Criterion | Exact check |
|---|---|
| (a) unattended | `journalctl --user -u breezy-autonomy-refit.service --since <W0> --until <W7> \| /usr/bin/grep -c 'REFIT_RESULT '` ≥ 7 qualifying-day runs, none `SKIPPED_LOCK`/`FAILED`; `systemctl --user show breezy-autonomy-refit.service -p TriggeredBy` = the timer; `git log --since=<W0> -- deploy/families src/breezy/strategy/forecast_quantile_ladder` shows no artefact or manifest commit |
| (b) family-agnostic | `test_driver.py::test_every_live_gate_routed_kind_has_a_fitting_refitter`, `::test_refusing_plugin_kind_not_fittable_and_never_writes_c3`, ARCH-0 `test_family_plugin_exact_set`; each `refit_run_<date>.json` lists every non-RETIRED lineage root |
| (c) fails closed | WP3 `test_c3_writer.py::*refuses*`, `::test_affine_that_is_identity_after_renorm_fails_x22`; WP2 loader refusals, `test_rung_recalibration_envelope.py::test_enveloped_bounds_never_more_confident_on_either_leg`, `::test_candidate_never_adds_takes_vs_recalibrated_champion`; WP6 `::test_dirty_closure_refuses_exit_3`, `::test_producer_pin_mismatch_refuses_exit_3`, `::test_kmax_reached_stops_minting_records_no_change_and_counts_toward_streak`; live: `jq '[.leakage_assertions[].passed]\|all' lineage.json` = true for every C3 |
| (d) detected and delivered | For each §6 drill: the journal line (`watchdog`, `timeout`, `SKIPPED_LOCK`, `oom-kill`, `REPRO_MISMATCH`, `PIN_MISMATCH`, `DIRTY_CLOSURE`, `DISK_BUDGET`, `k_max_reached`) and a `delivered=true` row in `evidence/alerts/delivery_<date>.jsonl` where the drill raises an alert |
| (e) RED→GREEN | Per WP: RED and GREEN logs plus commit SHAs; full gate exit 0 after every merge |
| (f) live proof | `aut3_live_proof_report.py --since <W0>` prints `STREAK_RUNS=7 STREAK_CANDIDATES=<n> QUALIFYING_FILLS>=5 AUT4_ACK=7/7 OWN_OUTCOME_CANDIDATE=<sha> GATE_DECISIONS_CHANGED>=<MIN> N_EFF>=<MIN_NEFF_TO_EMIT> MINTED=yes REPRO_PASS>=1 REACHABILITY=<verdict>`; the scorer re-hashes each `artefact.json`, confirms the cited C4 verdicts, MINT rows and acks exist, and recomputes `gate_decisions_changed` from the `probe_gate_inputs` snapshot with `AR/gate_probe.py` |
| Execution-data clause | `docs/evidence/RULING_aut3_readme_alignment_<date>.md` SOUND; `test_fq_rung_recal_refitter.py::test_estimator_reads_no_venue_price_fields` green |
| Lineage completeness | every `lineage.json` and `refit_run/v3.results[]` has non-null `data_windows[].content_sha256`, `code_git_sha`, `producer_code_sha`, `params` (incl. `selection_population` for rung_recal), `seed`; every snapshot exists and re-hashes |
| Loader parity | `pytest tests/unit/test_fq_live_analysis_point_cdf_parity.py::test_live_affine_shift_matches_analysis_apply_probability_recalibration tests/unit/test_refit_emit_set_equals_live_accept_set.py tests/unit/test_rung_recalibration_envelope.py tests/unit/test_ladder_ev_quantile_density.py` exit 0 |
| Holdout | `test_aut3_ruling_pins.py::test_sealed_bounds_equal_holdout_freeze_ruling`, `::test_refit_never_calls_open_holdout`; `holdout_opens` unchanged by any AUT-3 run |
| Mint limit | for each forward window in the proof span, count of non-drill MINT rows per lineage ≤ K_max; every run after the K_max-th MINT in a window shows `NO_CHANGE(k_max_reached)` |

---

## 8. Risks, failure modes and contradictions

**Contradictions and gaps** (r2's C-1, C-3 and C-4 are deleted as resolved, S1: AUT-2 r2 §3.4.4 pins the bought leg; ARCH Rev 5 C4 chose the mint limit; the README is amended at `README.md:116`):
- **C-2 (open, ARCH §5.2/§10).** "Every study sets `RuntimeMaxSec`" has no effect on `Type=oneshot` units. ARCH should say "`RuntimeMaxSec` on notify/simple units, `TimeoutStartSec` on oneshot units".
- **C-5 (open, G11 semantics).** The envelope is loader semantics ARCH §4.2 ("bounded by the loader (G11)") does not name; ARCH should name it, including the per-(rung, side) scope and the path-wise caveat (§3.8), so AUT-4 evaluates the same bounds path-wise.
- **C-6 (C1 fallbacks).** If WP0 (viii) fails, C1 needs `rung_partition_p_hat`; if WP0 (xi) fails, C1 needs the decision's `margin`.
- **C-7.** "Reproduces the sha on a sampled subset" means a sample of candidates, each refit in full.
- **C-8.** `refit_run/v3` is a non-C record consumed by AUT-4 (ack) and AUT-6 (detectors). §4.3's pins cover only `breezy.*`; the `aut3_refit` closure must include `scripts/analysis/{autonomy_refit_daily,nbp_skill_study,settlement_truth_dataset}.py`.
- **C-9.** P_HOLD stays frozen; `density_table` is a naming literal only; WP-23 is rejected (operator 09-29).
- **C-10.** ARCH Rev 5 §5.1 places AUT-3 in Wave 2, but the live proof needs AUT-4's offline consumer, run ack and engine MINT (Wave 3).
- **C-11 (NEW, ARCH Rev 5 §5.2).** "Every study sets `RuntimeMaxSec` such that scheduled start + W + `RuntimeMaxSec` ends before 16:30Z" forbids any post-LAUNCH study slot, yet AUT-6 r2 (R-d) uses the window form "no study window intersects [16:30Z, 17:10Z)" and schedules 17:12Z units. AUT-3 r2's 18:00Z repro slot violated the literal rule. r3 complies (09:35Z primary) and ships the 18:00Z unit disabled pending ARCH Rev 7. Requested ARCH wording: "no study window intersects [16:30Z, 17:10Z) or starts a heavy job in 01:00–04:30Z".
- **C-12 (ALPHA → ARCH Rev 7).** ARCH Rev 5 C4 defines only "the k-th MINT of a lineage in a window", with α_k per window; the ALPHA decision splits that into `k_life` (α) and `mints_in_window` (rate). AUT-3 consumes the ALPHA form; ARCH Rev 7 must restate C4 accordingly (already ordered by ALPHA-decision).
- **R-README-1 (README text, coordinator edit).** `README.md:116` still names `NO_CHANGE(below_delta)` and `MIN_PROBE_DELTA`; the coordinator's X22 ruling replaces them with `NOT_FITTABLE(gate_noop)` and `MIN_GATE_DECISIONS_CHANGED`.

**Risks and failure modes:**

| Risk | Mitigation |
|---|---|
| Memory on the 31 GB host (studies at 10–24 GB) | One studies-flock holder; MemoryMax from WP0 (≤ 16G); refit 06:00, repro 09:35; never 01:00–04:30Z; stop the study, never the node |
| Hung or slow fit (the 20 h S2 precedent) | WP0 benchmark; `WatchdogSec` fed by the `FitProgress` hook; `RuntimeMaxSec`; WP7 merge gate; contingency estimator |
| Progress hook changes fit numerics | Keyword-only, counters only, default None; bit-identity test through both existing callers |
| Shared venv | Exact interpreter; never `uv`/`pip`; repro by `git archive` + `PYTHONPATH`; `uv_lock_sha256`, `cpu_model` recorded |
| Concurrent agents | Disjoint Wave 1 files; WP2 serialised behind `FQ/composition.py` owners; per-agent scratchpads; no `git stash`; full gate per merge; dirty-closure refusal |
| Producer-pin churn (`CAL` edit rotates other closures) | `test_code_identity_pins_cover_import_closure` RED in the editing commit; rotate in the same commit |
| Statistical capacity / unreachable X22 | WP0 (x) simulation sets N0 and `MIN_NEFF_TO_EMIT`; pre-declared unreachability rule → score 2 with date; never a vacuous pass (gate count ≥ 1) |
| Gate count depends on a margin recompute | WP0 (xi); `probe_parent_not_qualifying` exclusion; C1 `margin` fallback |
| Envelope "subset" misread as path-wise | §3.8 disclosure; AUT-4 path-wise evaluation request |
| A recalibrated champion stops rung_recal | `NOT_FITTABLE(parent_recalibrated)`; cannot arise before the KILL (`promote_enabled=false`) |
| K_max reached early in a window | `NO_CHANGE(k_max_reached)` counts toward the streak; pending C3 reserve slots; refused MINTs release them |
| Partition recompute drift after a `quantile_density.py` change | Same-order computation through the split helpers; labels excluded by name; > 10% is CRITICAL; C1 fallback |
| Seasonal gap biases v5.0 | WP0 (vii); ruling accepts or defers |
| Disk growth (per-draw partitions) | Segmented content-addressed snapshots; WP0 (ix); budget WARN/refusal |
| Repro slot too short | `REPRO_DEFERRED_SLOT` (never a pass); rung_recal supplies `REPRO_PASS`; secondary slot after ARCH Rev 7 |
| KILL 2027-01-25 | ETA per §6; after a TERMINAL KILL refits continue on the frozen lineage (MINT allowed, PROMOTE refused, ARCH §5.3) |
| `nbp_learning_nightly` scores a hard-coded path and pre-July rows | Not changed here; AUT-6 retargets it |

---

## 9. Binding-constraint compliance

- **Nautilus immutability:** no Nautilus file touched; refits are offline; the node loads sha-pinned bytes through the existing loader.
- **Caps:** no autonomy-refit module reads, assigns or reads upward any `OPERATOR_RESERVED_CONTROL_ENV_VARS` (`test_autonomy_never_reads_or_writes_operator_controls` extended); units never load `operator.env`. The daily-budget interaction in §3.8 is a disclosure about path effects, not a read of the cap.
- **What p feeds:** the recalibrated, enveloped bounds feed the FQ take gate (`FQ/decision.py:349`); quantity is the literal `QTY = 1` (`FQ/decision.py:73`). The per-(rung, side) gate subset holds against an unrecalibrated champion (§3.4(d), §3.8).
- **`allow_short=False`:** untouched (`FQ/config.py:74-82`); no refit parameter changes sides; manifest equality forbids it.
- **NO-SEND:** no new egress host; alerts only via `alerts.env` through `deliver_with_proof`; no `exec/`, adapter or order-path import.
- **Master enablement and permit:** never read or written. AUT-3 writes only under `derived/` and `evidence/`.
- **PREREG via ruling:** every AUT-3 constant comes from `RULING_aut3_refit_policy_<date>.md` (N0 and `MIN_NEFF_TO_EMIT` by its pre-declared simulation rule); K_max from pins/`autonomy-policy/v1`; holdout from `RULING_holdout_freeze_and_forward_window_2026-10-03`; each pinned by test.
- **Safety tests never weakened:** one refusal test's example is re-pointed under a reviewed L-12 one-row widening, with sign-off; refusal tests added for every excluded affine shape; r2's own planned test `test_past_kmax_still_writes_and_records` (never written) is re-pointed to a stricter behaviour. No settlement, contract or NO-SEND test is edited.

---

## 10. Self-score (r3)

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Rebased on Rev 5 (sha re-hashed), ALPHA and HOLDOUT decisions, the amended README and the X22 ruling; README-text and ARCH residues named (R-README-1, C-11, C-12). |
| Correctness | 20 | 18 | Envelope now relative to the champion (parent unrecalibrated); gate inputs measured exactly via slope-1 affinity; live statistic everywhere; fixed op order makes the 1e-12 tolerance meaningful. Still INFERRED: forecast retrieval by digest, margin recompute, Splits tagging, watchdog semantics. |
| Specificity | 15 | 14 | Files, functions, statuses, constants, slots and tests named; N0 and `MIN_NEFF_TO_EMIT` deliberately deferred to a pre-declared simulation rule. |
| Acceptance | 20 | 18 | Checklist recomputes the gate count from snapshots; reachability verdict and score-2 fallback explicit. Depends on AUT-4's ack and `alpha_ledger`. |
| Autonomy-safety | 15 | 14 | Unconditional envelope with scoped claim and path-wise disclosure; writer-side K_max mirror; shared predicate; pin, clean-tree and drill coverage. |
| Reuse | 10 | 9 | Reuses the affine form, the fitters (one keyword-only hook), `rung_probability_interval` (split bit-identically), `edge_after_costs` affinity and `forecast_margin`. |
| **Total** | 100 | **91** | |

---

## §R3 Disposition (review `reviews/AUT-3-r2-merged.md`)

r2's R1–R16 dispositions remain in `AUT-3-retraining_plan_r2.md` §R2 Disposition (R15's removal of the parent-recalibrated stop is superseded by S2 below).

**11 FIXED, 0 REJECTED.** The review offered two options for S2; option 1 is adopted and option 2 is rejected with evidence (below).

| S | Disposition | Where / evidence |
|---|---|---|
| S1 | FIXED | Header rebased on ARCH Rev 5 sha `5d2b75fa…eff8403` (re-hashed) and `ALPHA-decision.md`. §3.3 step 1: stop at K_max MINT-bound C3 per lineage per forward window (`forward_window_index` imported from AUT-4's `alpha_ledger`; pending C3 reserve slots), record `NO_CHANGE(k_max_reached)`, which counts toward the streak; `k_life` is AUT-4/C4's, never reset and never written by AUT-3 (`::test_refit_never_writes_or_resets_lineage_counters`); `nominal_only` past `K_LIFETIME_EFFECTIVE`. Writer refusal `::test_refuses_c3_when_mints_in_window_at_kmax`. `test_past_kmax_still_writes_and_records` re-pointed to `::test_kmax_reached_stops_minting_records_no_change_and_counts_toward_streak`. C-1, C-3, C-4 deleted as resolved: AUT-2 r2 §3.4.4 (`AUT-2-outcome-labeling_plan_r2.md:147`), ARCH Rev 5 C4 "Chosen rule: AUT-3 mints at most K_max", `README.md:116`. |
| S2 | FIXED (option 1) | §3.4(d): rung_recal fitted only when parent `recalibration == none`, else `NOT_FITTABLE(parent_recalibrated)`; writer refusal and `parent_unrecalibrated` assertion; `::test_candidate_never_adds_takes_vs_recalibrated_champion` (WP2). Option 2 (`envelope_parent_shift`) rejected: a single parent shift is insufficient after a second promotion because the grandparent's bound can bind, so it would need the full ancestor chain in the artefact (schema widening plus a second loader form). No practical cost: `promote_enabled=false` before the KILL (ALPHA §3), and the drill child is byte-identical. |
| S3 | FIXED | §3.4(h) `AR/gate_probe.py`: `gate_decisions_changed` over C1 Take/TrySubmit probe records against `ask+fee+forecast_margin`, exact via the slope-1 affinity of `edge_after_costs` (`src/breezy/strategy/weather_common/risk.py:756-760`), on enveloped bounds; `gate_probe_max_delta` recorded. Applied to X22, the mint gate (replacing `functional_delta`/`MIN_MINT_DELTA`) and WP9; below threshold `NOT_FITTABLE(gate_noop)`. Threshold functional per the coordinator ruling (`MIN_GATE_DECISIONS_CHANGED = 1`). |
| S4 | FIXED | §3.4 WP0 (x): seeded reachability simulation at n_eff 30/60/120 × N0 grid × c*, real decision pools (L-41), pre-declared selection rule for N0 and `MIN_NEFF_TO_EMIT`, measured accrual rate, explicit unreachability rule (score 2 with the earliest n_eff and date); projection table; §6 ETA scenarios including "unreachable before 2027-01-25". |
| S5 | FIXED | §3.4(b)/(c): live statistic (`fmean` over per-draw renormalised partitions; order-statistic bounds) for every delta; per-draw partitions snapshotted (`label_draw_partitions`, `label_forecast_percentiles`, `probe_gate_inputs`); fixed op order (ladder order for renormalisation, draw order, `fmean`), so the expected recompute difference is 0 and `P_REPRO_ABS_TOL = 1e-12` is a divergence ceiling; `interval_from_per_draw` split shared by provider, refitter, writer and reproducer; tests `::test_live_statistic_used_not_mean_partition`, `::test_recompute_diff_is_exactly_zero_on_live_order`, `::test_draw_partitions_segment_round_trips_bit_exact`, `::test_rung_recal_refit_from_draw_partitions_snapshot`. |
| S6 | FIXED | §2 row corrected ("REUSE unchanged" withdrawn; `/usr/bin/grep` shows no progress hook in `CAL`); §3.4 keyword-only `progress: Callable[[FitProgress], None] | None` on `fit_calibration`, `fit_hierarchical_emos` (pass-through), `select_kappa_by_lovo_crps`, `bootstrap_emos_draws`; WP4 `::test_fit_calibration_progress_none_and_callback_bit_identical` across both existing callers; pin rotation noted. |
| S7 | FIXED | §3.2 and §3.5 `params.selection_population`: filled entry takes under the parent gate (p_lower / 1 − p_upper vs ask, fee, margin), IOC misses AMBIGUOUS with no label, budget/latch-suppressed takes unobserved; c stated as conditional on that population; `::test_selection_population_recorded`. |
| S8 | FIXED | §3.2 and §3.8: "only removes takes" scoped to per-(rung, side) gate eligibility against an unrecalibrated champion; daily-budget and AMBIGUOUS-latch path interactions disclosed; AUT-4 asked to evaluate path-wise (§5); density_table marked as not de-risking (§3.1). |
| S9 | FIXED | §3.4(d) `label_from_other_gate` exclusion for labels decided under any recalibration (selection population differs); `labels_bound_to_parent_gate` assertion; `::test_label_from_other_gate_excluded`. |
| S10 | FIXED | Every citation is repo-relative with a stated prefix legend (`FQ/` = `src/breezy/strategy/forecast_quantile_ladder/`, `LEV/` = `src/breezy/strategy/ladder_ev/`, `CAL` = `src/breezy/analysis/nbp_calibration.py`); line anchors re-checked at `4b8347a6` (e.g. `FQ/decision.py:73,331,349`, `FQ/calibration_artefact.py:68,118,281`, `LEV/quantile_density.py:386-442`, `CAL:1004,1070,1166,1280,1647-1662`). |
| S11 | FIXED | §3.4(h): the ablation is **defined** as the parent bytes with `recalibration=none` (not an empty-label solver run, which returns c of order `xatol`); with the parent unrecalibrated, `ablation_artefact_sha256 == parent_artefact_sha256`; `C_IDENTITY_EPS` raised to the solver `xatol` (1e-9); `::test_ablation_sha_equals_parent_sha_when_parent_none`, `::test_ablation_built_from_bytes_not_from_empty_fit`. |
