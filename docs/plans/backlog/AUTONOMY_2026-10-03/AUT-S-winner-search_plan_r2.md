# Implementation Plan: F10 AUT-S-PLAN, the AUT-S automated winner-search plan (r2)

**Target path when filed:** `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r2.md`. This is the F10 deliverable (`FQ-LOSS-RESPONSE_plan_r3.md:479-482`). It supersedes r1. **No file was written.**

**F11-list exception (recorded per AS-R10):**
- Step 4 changes `scripts/analysis/market_calibration_scan.py`, which is outside the F11 file list. It replaces `_bootstrap_stats`/`_max_tests` with imports from `spa.py`.
- The exception is accepted on two conditions:
  - the lift is verbatim, with the RNG call order preserved;
  - the M1 evidence JSON is byte-identical before and after.
- The lift happens only if Phase 2 is reached (AS-R3).

**Citation status:**
- Code citations V13–V22 were re-verified on 2026-10-06 with codegraph (`projectPath=/home/jon/breezy`) or a direct read.
- V1–V12 and every document line citation (`r2:`, `r3:`, `ARCH-ERRATA-rev9_2.md:`) are carried unchanged from r1. They were not re-verified in this round.

## Changes from r1

| Ruling | What changed | r2 sections |
|---|---|---|
| **AS-R1** (blocking) | Lane S folds are blocked within each NBM version. There is a per-version STOP stated in climate days, plus a computed MDE on Δ. The "n-rich" claim for v5 is withdrawn: v5 has 58 climate days. | Verified facts V14; Phase 0 step 0.1; §Lane S; §Feasibility; tests |
| **AS-R2** | Lane S is one-shot per (grammar version, data window), and its result is immutable. K is permanent per archive and never reset. The data window is pinned in the grammar hash. The K ledger is hash-chained, committed, and stores per-day Δ vectors. The run refuses if the ledger is missing or broken. Nightly runs never re-select. | §Grammar (K cap); §Multiplicity; steps 1 and 5; tests |
| **AS-R3** | **Phase 0 runs first and is read-only.** `spa.py` and Lane S are built only if G2 is non-empty. The unit is deferred. The harness step moves to Phase 4. Freeze serialisation is built now. The `c3_writer` call waits for the F5 GAP-13 ruling. | §Implementation steps (restructured); §Architecture changes |
| **AS-R4** | Brier is a necessary filter only. Δ on the take-eligible band is the primary statistic. The resolution gain is reported. Every fold must have the same sign. Both arms use the identical refit. A positive control (sha reproduction) and a negative control (shuffled labels) are added. A Δ above the fold spread becomes `HELD_LEAK_AUDIT`. | §Lane S; Phase 0 steps 0.2 and 0.7; §Schema; tests |
| **AS-R5** | The dual rule gains an effect-size floor (Δ mapped to ¢/contract). A candidate below the forward detectable scale is flagged `unlikely_to_confirm`. At most 1 mint per cycle. | §Mint rule; OPEN-R2-2; tests |
| **AS-R6** | S1 is accepted, and Lane E output never enters model-variant evidence. S4 is amended: `selection_window_end` is the latest day read by any input. `correction_form` is pinned. G2 requires `available_at < decision instant`. Only G1 is deployable before KILL. | §Conflicts; §Grammar G1/G2; §Forward-freeze handoff; §Feasibility; tests |
| **AS-R7** | X1 stays paper-only and needs its own erratum. Restrict-only is defined per decision. The schema is closed. The policy sits inside the artefact hash. A subset property test is specified. | §Grammar G3; Phase 4 step 12; tests |
| **AS-R8** | The bwrap row is a blocking dependency of Phase 3. Network is denied. Mounts are scoped. Time guards are `ExecCondition` plus an in-run watchdog. No exec or venue `Environment=` line. Alerts go to an outbox file. | §Unit; Phase 3; OPEN-R2-3; tests |
| **AS-R9** | HELD is the fail-closed default. Directories are writable only through `c3_writer`. The frozen JSON carries no manifest, allowlist, cap or permit fields. AUT-S has no nomination or promotion path. | §Forward-freeze handoff; tests |
| **AS-R10** | The `spa.py` lift is verbatim. The stationary bootstrap is a separate function. M1 JSON byte parity is required. The F11 exception is recorded in the header. A name-collision test is added to the harness step. | Header; step 4; step 9; OPEN-R2-1; tests |
| **AS-R11** | Lane E reports power with every verdict. The usable-day STOP rises from 14 to **28**, with a justification. | Phase 0 step 0.4; §Lane E; tests |
| r1 correction (found during verification) | r1 claimed "a stationary bootstrap at block length 1 reproduces M1 exactly". That is false. M1 draws `rng.multinomial` day weights (`market_calibration_scan.py:581-582`), and a stationary bootstrap consumes the RNG differently. M1 parity now binds to the lifted day-block function. | §Multiplicity; step 4 |
| r1 correction | The r1 unit template cited `breezy-replay-daily.service`. That unit also sets `Environment=POLYMARKET_US_EXEC_STATE_DB=…` at `:58`. This line is **explicitly not copied** (AS-R8). | §Unit |

## Overview

AUT-S is a standing search that never trades. It works in five stages:
1. It generates strategy variants from a closed, hash-pinned grammar.
2. It screens them once, against an immutable pre-holdout archive, using statistics that can only reject and that control multiplicity.
3. It serialises at most one frozen survivor per cycle.
4. Once F5 rules on GAP-13, it hands that survivor to AUT-3 `c3_writer`.
5. α is charged only at the AUT-4 C5 nomination, on forward days after the freeze. AUT-S has no path to nomination or promotion.

**r2 reorders the build around the one fact that decides AUT-S's value.** Is there a US weather source (G2) with archive coverage inside each NBM version's folds?
- Phase 0 answers that question, read-only, before any search code is written.
- If the answer is "none", AUT-S ships only Phase 1: the grammar, freeze serialisation and M1 routing. New-source acquisition (F13) then becomes the binding programme item.

## Requirements

- **Directive (2026-10-04):** keep optimizing toward winning trades. AUT-S never trades, never writes C5, and spends no α at screening (`r3:582`).
- **r2 grammar and controls are kept** (`r2:267-276`, `r3:480`):
  - a K cap;
  - native `backtest()`/`BacktestEngine` plus `PortfolioAnalyzer.register_statistic` (FQ-R12; Phase 4 only);
  - reject only when UB < 0;
  - Hansen SPA / White reality check;
  - a usable-day list;
  - survivors minted as C3 `variant_spec`, feeding AUT-4 OFFLINE_CHALLENGER.
- **E-26** (`ARCH-ERRATA-rev9_2.md:673-725`):
  - variation lives in the artefact only;
  - `params` keys are bounded by what the FQ live loader reads;
  - `taker_fee_coefficient`, `composition_kind` and `stations` never change;
  - a nomination with a manifest diff outside the allowlist is refused;
  - `spec_freeze_sha` and `nomination_days_after_spec_freeze` are carried.
- **E-25 rule 8** (`:617-620`): backtest-only or archive-only input yields at most UNDERPOWERED or a screen rejection. It never yields PASS.
- **FQ-R14** (`r3:441-445`): screen and scan days never become nomination evidence. Nomination uses forward climate days strictly after the freeze.
- **FQ-R27** (`r3:665-668`): Bonferroni LB > 0 **and** SPA p < 0.05. AS-R5 adds an effect-size flag.
- **Data scope:**
  - Model output is read only on archive climate days before `DEFAULT_SPLITS.holdout_start` = 2026-07-01 (`src/breezy/analysis/nbp_calibration.py:273-278`).
  - `open_holdout` (`nbp_calibration.py:353-399`) is never called.
  - Folds are blocked **within each NBM version** (AS-R1).
- **Prediction inputs are US weather sources only.** Venue prices are execution cost only (Lane E, model-free).
- Neither operator-reserved control is read, named or assigned anywhere in AUT-S code, units or evidence.

## Verified facts this plan rests on

| # | Fact | Evidence |
|---|---|---|
| V1–V12 | Carried from r1 unchanged: the allowlist, the loader keys, decision knobs from code defaults, D+1-only trading, the M1 windows, the existing FQ-in-`BacktestEngine` shadow, `register_statistic` being unused, the harness entry points, the lineage caps, and the missing `c3_writer`/`elond`/`evidence_row`. | r1 table |
| V13 | `murphy_decomposition(probs, outcomes, bins)` returns REL/RES/UNC/Brier. `resolution_difference` refuses `bin_by_value` for cross-model comparison, and its docstring requires a station-day cluster bootstrap for any CI. | `src/breezy/analysis/brier_decomposition.py:177-229`, `:232-268` (refusal at `:261-265`) |
| V14 | The splits are: train 2021-01-01..2024-12-31; validate 2025-01-01..2026-05-03; **`v5_fit_slice` 2026-05-04..2026-06-30 (58 climate days)**; holdout from 2026-07-01. | `nbp_calibration.py:273-278` |
| V15 | The NBM version eras are v3.2, v4.0, v4.1, v4.2, v4.3 and v5.0. The module never hardcodes era boundaries; the version comes from `VersionRow.version`. | `nbp_calibration.py:465-468`, `:471-489` |
| V16 | M1's bootstrap is an iid day-weight resample: `rng = np.random.default_rng(seed)` then `rng.multinomial(n_days, …, size=resamples)`. RC and SPA are in `_max_tests`. The seed and B are imported from `roi_bound`. | `scripts/analysis/market_calibration_scan.py:568-600`, `:603-612`, `:63`, call sites `:668`, `:683-699` |
| V17 | M1 writes `market_calibration_scan.json` under `--out` with `sort_keys=True`. The committed evidence is the `.md`; no JSON sits beside `docs/evidence/M1_MARKET_SCAN_2026-10-04.md`. | `market_calibration_scan.py:848-857`; glob of `docs/evidence/` |
| V18 | `B_RESAMPLES = 10_000` and `SEED = 20260904`. | `src/breezy/settlement/roi_bound.py:93`, `:97` |
| V19 | The paired champion (`p_m2`) and NBS M1 (`p_m1`) probabilities already exist per pre-holdout station-day, and holdout days are refused. | `scripts/analysis/nbp_learning_nightly.py:510-551` |
| V20 | The replay unit sets `MemoryHigh=3G`/`MemoryMax=4G` (`:36-37`), `Slice` (`:39`), `UMask=0077` (`:41`), `OnFailure` (`:21`) and `EnvironmentFile=-…alerts.env` (`:50`). **It also sets `Environment=POLYMARKET_US_EXEC_STATE_DB=…` (`:58`)** and `TimeoutStartSec=1800` (`:62`), with no `RuntimeMaxSec`. The NBP-learning unit has the same caps at `:7`, `:16-17` and `:19-20`. | `deploy/systemd/breezy-replay-daily.service`; `breezy-nbp-learning-nightly.service` |
| V21 | `BwrapRow` has a required `network: Literal["none","egress"]` (`"none"` unshares the network namespace), plus `studies_lock`, `binds` and `config_ro_binds`. The wrapper is `breezy-autonomy-bwrap ROW CMD…`. No existing unit uses `PrivateNetwork`, `IPAddressDeny` or `ExecCondition`. | `src/breezy/runtime/autonomy_sandbox/table.py:165-190`; `deploy/systemd/breezy-autonomy-bwrap:4`; grep of `deploy/systemd/` |
| V22 | A file-outbox alert convention exists: `<ts_ns>_<event>.json`, `ALERT_OUTBOX_MAX=256`, `ALERT_OUTBOX_STALE_S=300`. The event set is a closed capture tuple. | `src/breezy/persistence/autonomy/capture_alerts.py:3-7`, `:60`; `persistence/autonomy/pins.py:64-65` |
| V23 | An IEM MOS archive backfill exists. It is the G2 candidate that Phase 0 inspects. | `scripts/archive/iem_mos_backfill.py` (`main` `:1054`) |

## Conflicts, gaps and open items

**Accepted conflicts and gaps:**
- **CONFLICT-S1 (accepted, AS-R6):** there are two lanes.
  - Lane S covers model variants on the pre-07-01 archive against CLI truth.
  - Lane E covers model-free cells on tape days.
  - **Lane E output never enters model-variant evidence.** Lane S and Lane E run as separate processes with separate input manifests (`test_lane_e_output_never_enters_model_variant_evidence`).
- **CONFLICT-S2 (kept):** the r2 grammar is cut to tiers G1 and G2. G3 needs X1; G4 is a new family only.
- **CONFLICT-S3 (kept):** `D_12Z` and `D_17Z` cells are G4 only. `D-1_18Z` cells need G3.
- **CONFLICT-S4 (amended, AS-R6):**
  - `selection_window_end` is the **latest climate day read by any input of the run that selected the spec**, including ingested M1 scan windows.
  - Lane S runs never open M1 JSON, so their `selection_window_end` is ≤ 2026-06-30.
  - Lane E/M1-routed freezes carry M1's last scan day.
- **OPEN-S5 (resolved by AS-R5):** see §Mint rule.
- **GAP-S6 (kept):** the cell backtest strategy and, with it, the harness statistics registration (AS-R3) are Phase 4, trigger-gated.
- **GAP-S7 (now blocking, AS-R8):** the ARCH-0 bwrap row is a hard dependency of Phase 3.
- **DEP-S8 (kept):** nomination of a non-champion is infeasible until F5 rules GAP-13. The `c3_writer` call is Phase 4 behind that ruling. Freezing is not blocked, so the forward clock can start early (§Forward-freeze handoff).

**Remaining OPEN items:**

| ID | Item | Why it is open | Blocks |
|---|---|---|---|
| **OPEN-R2-1** | Location of the 2026-10-04 M1 JSON used for AS-R10 byte parity. | V17: the script writes the JSON under `--out`, and only the `.md` is committed. Verification found no committed JSON. Proposed resolution (Phase 0 step 0.6): locate the original `--out` JSON. If it cannot be found, regenerate it from the pinned M1 input at the pre-lift commit and commit that JSON as the parity fixture. A regenerated fixture proves lift parity but not historical identity; that is stated in the evidence. | Step 4 |
| **OPEN-R2-2** | The exact Δ→¢/contract mapping for the AS-R5 effect-size floor. | No mapping exists in code. The proposed default is in §Mint rule. The stats peer must confirm it in r2 review, because it decides the `unlikely_to_confirm` flag. It is non-blocking for Phases 0–1. | Step 8 flag semantics |
| **OPEN-R2-3** | The forwarder for the outbox of a network-less unit. | The outbox file convention exists (V22). Its event set is the closed capture tuple, and I did not verify that any forwarding unit would accept `BREEZY_AUT_S_STALLED`. Resolution: extend the forwarder's allowlist through its own reviewed change, or add a dedicated forwarder. | Phase 3 |
| **OPEN-R2-4** | Re-selection of `correction_form`. | AS-R6 pins it to the champion's form "unless a ruling allows re-selection". No ruling exists, so it stays pinned. This is open by design. | Nothing (default = pinned) |

## Architecture changes

**Phase 1 (unconditional):**
- NEW `src/breezy/analysis/autonomy/search/__init__.py`.
- NEW `src/breezy/analysis/autonomy/search/grammar.py`. It holds the closed, versioned grammar (frozen dataclasses) with tier tags.
  - The hash covers the grammar **and the pinned data window**: the date range plus the Phase 0 archive inventory content hash (AS-R2).
- NEW `src/breezy/analysis/autonomy/search/freeze.py`. It does frozen-spec serialisation and the handoff state machine, with HELD as the fail-closed default (AS-R9).
  - It has no `c3_writer` import. The handoff always returns `HELD(f5_gap13_unruled)` until Phase 4.
- NEW `src/breezy/analysis/autonomy/search/m1_ingest.py`. It covers M1 JSON ingestion, the routing table, the `avoid_cells` export, and power reporting (AS-R11).

**Phase 2 (only if Phase 0 finds G2 ≠ ∅):**
- NEW `search/spa.py`:
  - `day_block_bootstrap` and `max_tests`, lifted verbatim from `market_calibration_scan.py:568-612`;
  - a separate `stationary_bootstrap`;
  - the Bonferroni LB and UB.
- NEW `search/generator.py`: deterministic enumeration plus the K ledger. The ledger is hash-chained, append-only JSONL with per-day Δ vectors, committed under `aut_s/ledger/`.
- NEW `search/screen.py`: Lane S fold scoring, the outcome vocabulary, the mint selector, and the evidence writer.
- EXISTING `scripts/analysis/market_calibration_scan.py`: imports from `spa.py` (the F11 exception above).

**Phase 3 (deferred):**
- NEW `deploy/systemd/breezy-autonomy-search.service` and `.timer`.
- A row in `AUTONOMY_BWRAP_TABLE` (`table.py`), owned by ARCH-0.

**Phase 4 (trigger-gated):**
- EXISTING `src/breezy/runtime/backtest_harness.py`: a keyword-only `statistics` argument. The default registers nothing.
- The GAP-S6 cell strategy.
- The `c3_writer` wiring in `freeze.py`.
- The AUT-S-X1 build.

**Evidence:** `docs/evidence/AUT_S_PHASE0_<date>.md` and `docs/evidence/AUT_S_SCREEN_<date>.md`, each with a JSON beside it.

**Native-first justification:**
- The search reuses `murphy_decomposition`/`resolution_difference` (V13), the `score_learning_row` pairing (V19), `compute_roi_bound` constants (V18), `assert_split_disjoint`, M1's bootstrap (lifted, not rewritten), and native `BacktestEngine` + `register_statistic` (Phase 4).
- New code is only what nothing provides: a closed grammar, a hash-chained K ledger, the freeze state machine, and the screen glue.

## The search grammar

**Tier G1 (`variant_spec`, artefact-only; the only tier deployable before KILL):**

| Knob | Values | Artefact key |
|---|---|---|
| CDF family | `normal`, `pchip_normal_tails`, `skew_normal` | `cdf_method` |
| EMOS fit window | all in-version pre-fold, trailing 365 d, trailing 730 d | `emos_params_by_version`, `emos_draws_by_version` |
| Draw construction | `resample_delta` True / False | `emos_draws_by_version` |
| Location correction | **pinned to the champion's `correction_form` and coefficients** (AS-R6, OPEN-R2-4) | `correction_form` |

- That is 3·3·2 = **18 specs**. One is the champion's own combination, which is the baseline and is not counted in K, leaving **17 challengers**.
- `recalibration` is fixed at `"none"`.
- A G1 child equals its root on every manifest key except `density_artefact_path` and `density_artefact_sha256` (E-24).
- Within v5.0 (58 days), the 365 d and 730 d windows collapse to "all in-version". The generator detects identical fitted artefact parameters **before scoring** (a deterministic, outcome-blind check) and records `DUPLICATE_OF(<spec>)`. Duplicates still consume K, the conservative choice.

**Tier G2 (`density_table_multisource`; screen-only until F13):**
- The knob is the source set: the champion's NBP plus at most one added US source, at the champion's calibration settings. That is one spec per eligible source.
- A source qualifies only if Phase 0 step 0.3 shows coverage in every included version's folds **and** row-level `available_at < decision instant` (AS-R6; `test_g2_source_available_at_lt_decision_instant`).
- There is no international data and no venue or execution input.
- CHAMPION status needs F13 live plus a G11-style loader acceptance (E-26 rule 4). **A G2 result informs F13 prioritisation. It cannot be deployed before KILL.**

**Tier G3 (not expressible; AUT-S-X1 is paper-only, AS-R7):**
- Knobs: side mask, decision-hour window, ask floor and ceiling, and margins.
- X1 is a third route beyond E-26's two, because it widens ARCH `:806`. It needs **its own erratum** before any build.
- Binding X1 constraints:
  - **Restrict-only is defined per decision, with state-dependent limits held fixed.** On any (state, quote), the child's take is a take the root would also make.
  - The schema is closed: mask and floor fields only, no size fields, and margins ≥ the `LadderEvConfig()` code default (V3).
  - An unknown key or wrong type is refused.
  - The policy object sits inside the byte-bound artefact hash.
  - Property test: the child's take set ⊆ the root's take set on a shared fixture.
- **Build trigger:** the first FQ-R27 survivor in a `D-1_18Z` cell, or a mint candidate whose takes concentrate in M1 reliable-loser cells.
- One new family per survivor stays rejected, because it is uncontrolled α-shopping across lineages.

**Tier G4 (new family only; never AUT-S output):** same-day windows, resting execution, observation conditioning, and station subsets. These are recorded to `new_family_queue` with a programme count.

**K cap (AS-R2):**
- `K_UNIVERSE = 48` is **permanent per archive**. A grammar version bump inherits the count, and nothing resets it (`test_k_reset_refused`).
- **The Bonferroni divisor is the cap (48), not the running count.** This is stricter than r1 and removes any incentive to test early.
- The SPA universe is every spec tested so far, evaluated jointly over the persisted day vectors.
- `K_CYCLE = 12` new specs per run, and at most 1 mint candidate per cycle.
- Budget: G1 (17) + G2 (|sources|) ≤ 48. The remainder is reserved for future grammar versions on the same archive.

## The screen

### Lane S (skill; model variants; built only if G2 ≠ ∅)

**One-shot (AS-R2):**
- Lane S runs once per (grammar version, data window), and its outcome rows are immutable.
- The run refuses to start if the K ledger is missing, its hash chain is broken, or the data-window hash differs from the grammar's.
- A later run may only score **specs not yet in the ledger**. It never re-scores or re-selects a tested spec.

**Folds (AS-R1):**
- Folds are blocked **within each NBM version era** (V15), as contiguous calendar blocks.
- For each held block, both arms are refit on the other blocks **of the same version**, since `emos_params_by_version` is per version, and scored on the held block.
- `assert_split_disjoint` is reused. Any day ≥ 2026-07-01 is refused.
- **Per-version STOP, in climate days:** a version enters Lane S only if it has ≥ 2 blocks, each with ≥ 28 held climate days **and** ≥ 28 training climate days.
  - v5.0 (58 days) qualifies at exactly 2 × 29, with a large MDE.
  - Versions that fail are excluded and listed.
  - If the version that live FQ reads fails, Lane S cannot produce a deployable G1 candidate, and the evidence says so.
- **MDE on Δ:** reported per version as MDE₈₀ = (z_{1−α/(2·48)} + z_{0.80}) · SE_boot(mean Δ).
  - Phase 0 estimates SE from the existing paired `p_m2` − `p_m1` Brier difference (V19) as the variance-scale proxy.
  - The final SE comes from the run itself.

**Identical procedure (AS-R4):** the champion and the variant go through the same refit function, with the same seeds and inputs. Only the grammar knob differs.

**Statistics (AS-R4):**
1. **Whole-ladder Brier Δ** on the forecast-centred 2 °F ladder (the `_forecast_centered_ladder` convention). This is a **necessary-condition filter only**.
2. **Take-eligible-band Δ** is the **primary statistic**.
   - It covers rungs in the band FQ's live decision can take. Phase 0 step 0.7 pins the band from `LadderEvConfig()` and the decision module.
   - Δ_d = score(champion) − score(variant), paired per climate day across stations.
3. **Resolution gain** `resolution_difference(p_var, p_champ, y, bin_by_edges(…))`, with one pre-declared common binning (V13). It is reported.
4. **Fold-wise mean Δ** on the take band, reported per fold. A **mint candidate needs the same sign in every fold.**
- **Decision instants:** FQ's pinned live D+1 hour windows, scoped by date **and** hour. Every row asserts `available_at_ns < decision instant < settlement`.

**Controls (AS-R4):**
- **Positive control:** the champion, refit on its own window, reproduces the committed artefact sha256. A mismatch makes the whole run UNUSABLE, because the identical-procedure claim cannot be made. Phase 0 step 0.2 checks this before Lane S is built.
- **Negative control:** a shuffled-label run (days permuted within version, seeded). Its take-band Δ bootstrap 95% interval must cover 0, or the run is UNUSABLE.
- **Leak flag:** a variant whose mean Δ exceeds the champion's fold-to-fold spread (max − min of per-fold mean Brier within that version) becomes **`HELD_LEAK_AUDIT`**. It never becomes a finding, and it never silently becomes UNUSABLE.

**Outcomes (closed vocabulary):**

| Outcome | Rule |
|---|---|
| `REJECTED_UB_LT_0` | The Bonferroni (K=48) UB of whole-ladder Δ < 0, **or** of take-band Δ < 0 |
| `HELD_LEAK_AUDIT` | The leak flag above fires |
| `UNUSABLE` | Fold coverage < 95%, a control fails, or a leak assert fires (the run also exits non-zero) |
| `NOT_REJECTED` | Otherwise |

### Lane E (execution; model-free; Phase 1 ingestion only)

- Lane E ingests M1's JSON. A cell is a candidate only on M1's validity flag plus the FQ-R27 dual rule.
- **Every Lane E verdict carries power (AS-R11):** M1's `median_cell_mde_80`/`pooled_mde_80`, the per-cell MDE, and n days.
- **Usable days:** settled FINAL, Depth10 coverage of every rung in the window, and no overlapping `QuoteTapeGap`.
- **The usable-day STOP is raised from 14 to 28** for the Phase 4 `BacktestEngine` path:
  - M1's median per-cell MDE is 19.8¢ at 26 days. At 14 days it would be about 19.8 · √(26/14) ≈ 27¢, which is above any plausible cell edge, so a non-rejection there would carry no information.
  - At 28 days the MDE is at or below M1's own scale.
- Lane E output is never read by `screen.py` (AS-R6).

### Multiplicity

- `spa.py` provides two bootstraps:
  - **`day_block_bootstrap`**, a verbatim lift of M1's multinomial day weights, with the RNG call order preserved. M1 uses it, and Lane E parity binds to it.
  - **`stationary_bootstrap`**, a separate function with a pinned mean block length of 7 days, used by Lane S, where serial correlation is real.
- SPA and RC are **joint over the persisted per-day Δ vectors** of every spec in the ledger.
  - They are aligned on the immutable data window's climate-day index, with one seeded index draw applied to all columns.
  - Seed and B come from `roi_bound.py:93,97`.
- Resampling whole climate days (all stations together) satisfies the station-day cluster requirement of V13.

### Mint rule (AS-R5)

1. A spec is a **mint candidate** only if all of the following hold:
   - it is `NOT_REJECTED`;
   - take-band Bonferroni (K=48) LB > 0;
   - joint SPA p < 0.05;
   - the same sign in every fold;
   - it is not `HELD_LEAK_AUDIT`.
2. At most **1 per cycle**. Ties break by the highest take-band t, then by spec id.
3. **Effect-size floor (flag; OPEN-R2-2 proposed default):**
   - **Synthetic-ask edge proxy.** On each take-eligible rung-day, price the market at the champion's probability plus fee (`EVIDENCED_FEE_THETA`).
   - The variant "takes" where p_var − p_champ exceeds the `LadderEvConfig()` default margin, and realises y − ask per contract.
   - The mean over these synthetic takes, in ¢/contract, is an **optimistic upper bound**: the real market resolves 1.98× better than the champion.
   - If that bound is below the forward e-process detectable scale at the projected forward n (`r3:561`; recomputed with `compute_roi_bound` at n = 55–70), the candidate is flagged **`unlikely_to_confirm`**.
   - It may still be frozen, and the flag travels in `lineage.json`.

### Schema

- No `WIN`, `PASS`, `WINNER` or `SURVIVOR` token appears.
- Every row carries `source="archive"` (Lane S) or `source="backtest"` (Lane E). E-25 rule 8 applies.
- The screen imports no `elond`, `RegistryStore`, verdict writer, nomination module or promotion module.

## Forward-freeze handoff (AS-R9)

1. **Freeze (Phase 1; usable now):**
   - The mint candidate is serialised as `aut_s/frozen/<variant_id>.json`.
   - **It contains** the grammar knobs, artefact params, `selection_window_end`, the ledger head hash and the flags.
   - **It contains no** manifest, allowlist, cap or permit field.
   - Until the coordinator commits the file, its state is `HELD(uncommitted)`. Once committed, `spec_freeze_sha` is that commit and the freeze day is its LST climate day.
   - **The forward clock starts at the freeze, not at the handoff.** Forward days d > freeze day accrue even while the handoff is HELD.
2. **Handoff state machine (fail-closed):** the default is `HELD(<reason>)`. Any of the following yields HELD:
   - any exception;
   - E-26 unconsumed;
   - `c3_writer` absent;
   - the F5 GAP-13 ruling absent;
   - `HELD_LEAK_AUDIT`;
   - `uncommitted`.
   Nothing is ever silently dropped.
3. **Phase 4 only:** `c3_writer.write_candidate` is the only writer (E-26 rule 2).
   - `model_class` is `variant_spec` (G1) or `density_table_multisource` (G2).
   - `lineage.json` carries `spec_freeze_sha`, `selection_window_end` and `unlikely_to_confirm`.
   - `leakage_assertions` includes `nomination_days_after_spec_freeze`, `ref_ts_lt_take_ts` and `no_sealed_holdout_rows_in_train`.
   - The candidate and registry directories cannot be written by AUT-S except through `c3_writer`. A test proves it.
4. **Nomination and promotion are separate reviewed acts** (AUT-4 C5, then promotion). AUT-S has no code path to either, and an AST test enforces this.

## M1 survivor ingestion (Phase 1, `m1_ingest.py`)

| M1 result | Route |
|---|---|
| `D-1_18Z` × side × ask bin passing FQ-R27 | G3: trigger the X1 paper and erratum, and freeze as `HELD(needs_x1)`. Never minted. `selection_window_end` = M1's last scan day. |
| `D_12Z` / `D_17Z` | G4 `new_family_queue` only. |
| Reliable-loser cell (CI entirely < 0) | Exported to `avoid_cells` for F8's take rule. Never a candidate. |
| Invalid scan | Refused. No ingestion. |

Every routed row carries M1's power fields (AS-R11).

## Implementation steps

### Phase 0: verify-first (FIRST; read-only on repo code and state; STOP gates)

**Output:** `docs/evidence/AUT_S_PHASE0_<date>.md` plus JSON. Everything else is scratch only. No search code is written. Mergeable alone.

- **0.1 Per-version archive inventory.**
  - For each (NBM version from `VersionRow.version`, station, split), count climate days before 07-01 with NBP + CLI FINAL.
  - Lay out folds per §Lane S.
  - Evaluate the per-version STOP (≥ 2 blocks; ≥ 28 held and ≥ 28 training climate days).
  - Compute the MDE₈₀ on Δ per version (V19 proxy).
  - Confirm which version(s) live FQ reads (expected v5.0) and the champion artefact's fit window.
  - Emit the inventory content hash, which becomes the data window.
- **0.2 Champion reproducibility (positive-control precheck).** Refit the champion on its own window in scratch and compare the sha256. A mismatch is a **STOP for Lane S**.
- **0.3 G2 source eligibility.**
  - Per US source (the IEM MOS archive, V23, first): check per-version fold coverage and per-row `available_at` versus FQ decision instants.
  - **An empty result means G2 = ∅. AUT-S then stops after Phase 1 (AS-R3), and F13 is the binding item.**
- **0.4 Usable tape-day census** with the predicate above. **STOP < 28** for the Phase 4 `BacktestEngine` path. Report the count and the implied MDE.
- **0.5 Benchmark.**
  - Profile one G1 spec × one fold (the largest version) under `systemd-run -p MemoryMax=4G -p LimitNOFILE=524288`, with the base temp directory on `~/.cache`.
  - Record peak RSS and per-spec wall time.
  - **A peak over 4G blocks Phase 3.**
  - Derive the stall timeout (3 × the per-spec p95, rounded up to the minute, minimum 10 min) and `RuntimeMaxSec`.
- **0.6 M1 parity fixture (OPEN-R2-1).** Locate or regenerate the 2026-10-04 `market_calibration_scan.json`. Record its sha256 and its source commit.
- **0.7 Take-eligible band.** Pin the band from `LadderEvConfig()` and the decision module, and cite the lines in the evidence.
- Risk: Low. Dependencies: none.

### Phase 1: grammar, freeze and M1 routing (unconditional; mergeable alone)

1. **`grammar.py`.** G1 (correction pinned) and G2 tier declarations, with G3/G4 as non-generable tags. The hash covers the grammar plus the data window from 0.1. Risk: Low.
2. **`freeze.py`.** Serialisation, the fail-closed HELD state machine, and a field denylist. No `c3_writer` import. Risk: Medium (it is a fail-closed boundary).
3. **`m1_ingest.py`.** Routing, `avoid_cells`, power fields, and `selection_window_end` coverage. Risk: Low.

### Phase 2: Lane S (ONLY if 0.3 finds G2 ≠ ∅ and 0.1/0.2 pass; mergeable alone)

4. **`spa.py` lift (AS-R10), RED→GREEN.**
   - First write the byte-parity test against the 0.6 fixture, and the RNG-order test.
   - Then lift the code verbatim, switch M1 to import it, and add the separate `stationary_bootstrap`.
   - Risk: Medium (it touches a merged script).
5. **`generator.py` and the K ledger.** Deterministic order, hash chain, per-day Δ vectors, refusal past the cap, refusal on reset, refusal when the ledger is missing or broken, and duplicate detection. Risk: Medium.
6. **`screen.py` Lane S.** Version-aware folds, the identical refit, the four statistics, the controls, the leak flag, the outcome vocabulary, and the evidence writer. Risk: High (leakage). Every test listed under Phase 2 is RED first.
7. **One-shot Lane S run**, by hand, under the 0.5 caps. G2 specs first, then G1 as a by-product. The coordinator commits the ledger and the evidence. Risk: Medium.
8. **Mint selection and freeze**, using step 2's code. The handoff stays `HELD(f5_gap13_unruled)`. Risk: Low.

### Phase 3: standing unit (deferred)

**Preconditions, all required:** Phase 2 shipped; the GAP-S7 bwrap row landed; benchmark peak ≤ 4G; OPEN-R2-3 resolved.

9. **`breezy-autonomy-search.service` and `.timer`** (§Unit). The coordinator symlinks, runs `daemon-reload` and `enable --now`, and records all three in the evidence file. Risk: Medium.
   - A nightly run only adds unscored specs inside the cap, plus Lane E re-ingestion of the latest M1 JSON.
   - If the grammar is exhausted, it writes a `NO_WORK` heartbeat and exits 0.

### Phase 4: trigger-gated (separate reviewed changes)

10. **Harness statistics registration** in `backtest_harness.py`, plus the parity statistic and the name-collision refusal. **Trigger:** GAP-S6. Risk: Low (the default is inert).
11. **GAP-S6 cell backtest strategy.**
    - **Trigger:** the first FQ-R27 M1 survivor, with 0.4 ≥ 28 usable days.
    - One station-day per engine, `liquidity_consumption=True`, reject-only.
12. **AUT-S-X1.** The paper and its erratum are drafted now. The build waits for the G3 trigger.
13. **`c3_writer` wiring** in `freeze.py`. **Trigger:** E-26 consumed + AUT-3 `c3_writer` exists + the F5 GAP-13 ruling.

## The unit (Phase 3; AS-R8)

**Resource and failure settings:**
- `Type=oneshot`, `Slice=breezy-studies.slice`, `MemoryHigh=3G`, `MemoryMax=4G`, `UMask=0077`, `OnFailure=breezy-study-failed@%n.service`.
  - These match V20.
  - The unit joins `tests/unit/test_analysis_units_memory_capped.py`.
- `LimitNOFILE=524288`. Any base temp directory goes on `~/.cache`.

**Network and sandbox:**
- `PrivateNetwork=yes` **and** `IPAddressDeny=any` are set as defence-in-depth.
- **The enforcing layer is the bwrap row's `network="none"`** (V21). systemd `--user` sandbox directives may be no-ops on this host (errata E-7/E-8). The test therefore asserts the **effect**, that a socket connect fails inside the run, not just the directive's presence.
- `ExecStart` = `…/breezy-autonomy-bwrap <aut-s row> flock -w 1800 <studies lock> <exact .venv python> -I -m breezy.analysis.autonomy.search.<entry>`.
- Proposed row (ARCH-0 owns it):
  - `network="none"`, `resolves_dns=False`, `studies_lock=True`;
  - writable binds: exactly `aut_s/` (including `aut_s/outbox/`) and `docs/evidence/`;
  - `src/` and `.venv` read-only;
  - masked: the exec and trade state DBs, `operator.env`, `~/.config/breezy/**` and the node logs.
- A test opens each masked path and expects failure.

**Environment:**
- There is **no `EnvironmentFile`**: the unit has no network, so it needs no webhook.
- There is no `Environment=` line naming an exec or venue path.
- The replay unit's `POLYMARKET_US_EXEC_STATE_DB` line (V20 `:58`) is **not copied**.

**Time guards:**
- `ExecCondition=` refuses any start in [16:00Z, 17:30Z), including manual starts.
- An in-run watchdog exits non-zero at ≥ 16:00Z.
- The timer is `OnCalendar=*-*-* 04:10:00 UTC` with `Persistent=false`.
- `RuntimeMaxSec` comes from 0.5 (≤ 7200). `TimeoutStartSec` covers the flock wait (E-9).

**Stall watch:**
- One `AUT_S_PROGRESS i/K` line per spec, plus a total-runtime heartbeat.
- If no spec completes within the 0.5-derived timeout, the run writes `BREEZY_AUT_S_STALLED` to `aut_s/outbox/<ts_ns>_<event>.json` (V22 convention; forwarded per OPEN-R2-3) and exits non-zero.

**Concurrency:** one heavy job at a time, enforced by the shared studies flock.

## Testing strategy

**Markers:**
- **KEPT**: the r1 test, unchanged.
- **KEPT+**: the r1 test name, made stricter. Nothing is weakened.
- **ADD (AS-Rn)**: new, required by that ruling.
- **[Pn]**: the phase where the test is built.

**Grammar, generator and ledger:**
- KEPT [P2] `test_generator_deterministic_and_k_capped`
- KEPT [P1] `test_grammar_closed_and_hash_pinned`
- KEPT [P1] `test_grammar_g1_keys_subset_of_live_loader_keys`
- KEPT [P2] `test_generator_child_manifest_diff_only_allowlisted`
- KEPT [P2] `test_generator_never_varies_stations_fee_or_composition_kind`
- KEPT [P2] `test_generator_k_universe_cumulative_across_cycles_and_grammar_versions`
- KEPT [P2] `test_generator_order_independent_of_hash_seed_and_wall_clock`
- ADD (AS-R2) [P2] `test_k_ledger_append_only_hash_chained`
- ADD (AS-R2) [P2] `test_k_reset_refused` (grammar bump, changed inventory hash, truncated ledger)
- ADD (AS-R2) [P2] `test_run_refuses_missing_or_broken_ledger`
- ADD (AS-R2) [P1] `test_data_window_pinned_in_grammar_hash`
- ADD (AS-R2) [P2] `test_lane_s_one_shot_per_grammar_version_and_data_window`
- ADD (AS-R2) [P2] `test_nightly_never_reselects_tested_specs`
- ADD (AS-R2) [P2] `test_generator_duplicate_specs_consume_k`
- ADD (AS-R6) [P1] `test_correction_form_knob_ruling_gated`

**Lane S folds, statistic and controls:**
- ADD (AS-R1) [P2] `test_lane_s_folds_version_aware_with_training_data`
- ADD (AS-R1) [P2] `test_lane_s_per_version_stop_in_climate_days`
- ADD (AS-R1) [P2] `test_lane_s_reports_mde_on_delta_per_version`
- ADD (AS-R3) [P2] `test_lane_s_refuses_without_phase0_nonempty_g2_inventory`
- ADD (AS-R4) [P2] `test_lane_s_brier_is_necessary_filter_only`
- ADD (AS-R4) [P2] `test_lane_s_reports_resolution_gain_with_common_binning`
- ADD (AS-R4) [P2] `test_lane_s_gates_on_take_eligible_band_delta`
- ADD (AS-R4) [P2] `test_lane_s_requires_same_sign_every_fold`
- ADD (AS-R4) [P2] `test_lane_s_identical_refit_procedure_both_arms`
- ADD (AS-R4) [P2] `test_lane_s_positive_control_champion_refit_reproduces_artefact_sha`
- ADD (AS-R4) [P2] `test_lane_s_negative_control_shuffled_labels_delta_covers_zero`
- ADD (AS-R4) [P2] `test_lane_s_delta_above_fold_spread_is_held_leak_audit`
- ADD (AS-R6) [P2] `test_g2_source_available_at_lt_decision_instant`

**Leakage and isolation of the lanes:**
- KEPT [P2] `test_screen_refuses_holdout_day_for_model_variant`
- KEPT [P2] `test_screen_never_calls_open_holdout` (AST)
- KEPT [P2] `test_screen_asserts_ref_ts_lt_take_ts`
- KEPT [P2] `test_screen_scopes_windows_by_date_and_hour`
- KEPT [P2] `test_screen_folds_blocked_and_disjoint`
- KEPT [P1] `test_lane_e_reads_no_model_output`
- ADD (AS-R6) [P2] `test_lane_e_output_never_enters_model_variant_evidence`
- ADD (AS-R6) [P1] `test_selection_window_end_covers_ingested_m1_scan`

**Outcomes and schema:**
- KEPT [P2] `test_screen_schema_has_no_win_token`
- KEPT [P2] `test_screen_rejects_only_ub_lt_0`
- KEPT [P4] `test_screen_refuses_non_replay_sufficient_day`
- KEPT [P2] `test_screen_rows_source_backtest` (Lane E rows) and its archive counterpart
- KEPT+ [P2] `test_screen_outcome_vocabulary_closed`: now exactly {`REJECTED_UB_LT_0`, `NOT_REJECTED`, `UNUSABLE`, `HELD_LEAK_AUDIT`}
- KEPT [P2] `test_screen_positive_control_injected_loser_rejected_injected_edge_not_rejected` (L-38)
- KEPT [P2] `test_screen_spends_no_alpha` (AST)

**SPA:**
- KEPT [P2] `test_spa_pvalue_reported`
- KEPT+ [P2] `test_spa_matches_m1_scan_at_block_length_one`: now bound to `day_block_bootstrap` and byte-exact
- KEPT+ [P2] `test_spa_universe_and_bonferroni_k_cumulative`
- ADD [P2] `test_bonferroni_divisor_is_k_universe_cap`
- KEPT [P2] `test_spa_seed_deterministic`
- ADD (AS-R2) [P2] `test_spa_joint_over_persisted_day_vectors`
- ADD (AS-R10) [P2] `test_spa_lift_preserves_rng_call_order`
- ADD (AS-R10) [P2] `test_m1_scan_json_byte_identical_before_and_after_lift`
- ADD (AS-R10) [P2] `test_stationary_bootstrap_is_separate_from_day_block`

**Mint and handoff:**
- KEPT [P2] `test_mint_candidate_requires_bonferroni_lb_gt_0_and_spa_lt_005`
- KEPT [P2] `test_at_most_one_mint_candidate_per_cycle`
- ADD (AS-R5) [P2] `test_mint_candidate_effect_size_floor_flags_unlikely_to_confirm`
- KEPT [P1] `test_handoff_writes_spec_freeze_sha_and_selection_window_end`
- KEPT [P1] `test_handoff_held_when_e26_unconsumed_or_nomination_infeasible`
- KEPT [P1] `test_nomination_days_strictly_after_spec_freeze`
- ADD (AS-R9) [P1] `test_handoff_held_on_any_exception`
- ADD (AS-R9) [P1] `test_handoff_held_without_f5_gap13_ruling`
- ADD (AS-R9) [P1] `test_frozen_spec_has_no_manifest_allowlist_cap_or_permit_fields`
- ADD (AS-R9) [P1] `test_candidate_and_registry_dirs_unwritable_except_via_c3_writer`
- ADD (AS-R9) [P1] `test_search_has_no_nomination_or_promotion_path` (AST)

**M1 ingestion and Lane E:**
- KEPT [P1] `test_m1_ingest_routes_same_day_cells_to_new_family_queue`
- KEPT [P1] `test_m1_ingest_refuses_invalid_scan`
- KEPT [P1] `test_m1_reliable_loser_cells_exported_never_candidates`
- ADD (AS-R11) [P1] `test_lane_e_verdict_reports_power`
- ADD (AS-R11) [P4] `test_lane_e_usable_day_stop_at_28`

**Harness (Phase 4, AS-R3):**
- KEPT [P4] `test_backtest_registers_statistics_before_run`
- KEPT [P4] `test_backtest_default_registers_nothing` (L-55)
- KEPT [P4] `test_register_statistic_parity_with_fq_evaluator`
- ADD (AS-R10) [P4] `test_register_statistic_name_collision_refused`

**X1 (specified now, built with X1, AS-R7):**
- ADD `test_x1_policy_schema_closed_mask_and_floor_only`
- ADD `test_x1_policy_refuses_unknown_key_or_type`
- ADD `test_x1_margins_ge_code_default`
- ADD `test_x1_policy_inside_artefact_hash`
- ADD `test_x1_restrict_only_per_decision_with_state_limits_fixed`
- ADD `test_x1_child_takes_subset_of_root_takes_property`

**Unit and isolation (Phase 3 unless noted):**
- KEPT [P1+] `test_search_imports_no_exec_or_adapter`, plus the firewall guards and the exec import pin in every focused gate
- KEPT `test_unit_memory_capped`
- KEPT `test_unit_bwrap_wrapped`
- KEPT `test_unit_reads_no_operator_env`
- KEPT `test_timer_outside_1630_1710z`
- KEPT+ `test_stall_watch_alerts_and_exits_nonzero`: now writes to the outbox, with no network
- ADD (AS-R3) `test_unit_deploy_requires_benchmark_peak_le_memory_max`
- ADD (AS-R8) `test_unit_network_denied_connect_fails`
- ADD (AS-R8) `test_unit_masked_paths_unreadable` (exec/trade DBs, `operator.env`, `~/.config/breezy/**`, node logs)
- ADD (AS-R8) `test_unit_src_and_venv_read_only`
- ADD (AS-R8) `test_unit_writable_only_aut_s_and_evidence`
- ADD (AS-R8) `test_unit_exec_condition_refuses_window_including_manual_start`
- ADD (AS-R8) `test_run_deadline_watchdog_exits_at_1600z`
- ADD (AS-R8) `test_timer_persistent_false`
- ADD (AS-R8) `test_stall_timeout_derived_from_benchmark`
- ADD (AS-R8) `test_runtime_heartbeat_emitted`
- ADD (AS-R8) `test_unit_environment_names_no_exec_or_venue_path`

**Gate after every merge:**
- `scripts/ci/run_tests_no_egress.sh`, reading `EXIT=0`;
- `cd <tree> && .venv/bin/lint-imports`, reporting "N kept, 0 broken";
- the mypy ratchet;
- `PYTHONPATH=<wt>/src`;
- never `uv`, `pip` or stash;
- format only the touched files.

## Risks and mitigations

- **Multiplicity and data snooping (HIGH).**
  - One-shot Lane S with immutable outcomes.
  - A permanent K per archive, with the Bonferroni divisor at the cap (48).
  - A hash-chained ledger and joint SPA over persisted vectors.
  - The dual rule plus the same sign in every fold.
  - ≤ 4 lifetime nominations as the backstop.
  - A new family per survivor is refused.
- **Leakage (HIGH).** Version-blocked disjoint folds, `available_at < decision instant`, windows scoped by date and hour, holdout refusal, no `open_holdout`, a positive and a negative control, and `HELD_LEAK_AUDIT` for implausible Δ.
- **Small v5 sample (HIGH).** 58 climate days give a large MDE, so a G1 candidate for the live version is unlikely to clear the dual rule. This is stated in evidence, not hidden.
- **Overfitting (HIGH).** Identical refit in both arms, the stationary bootstrap, reject-only semantics, E-25 rule 8, and forward-only confirmation.
- **Champion not byte-reproducible (MEDIUM).** Phase 0.2 STOPs Lane S, rather than comparing unequal procedures.
- **systemd `--user` sandbox directives being no-ops, or failing to start under the AppArmor userns restriction (MEDIUM).** bwrap `network="none"` is the enforcing layer. Effect-asserting tests and a dry start in Phase 3 check it.
- **Optimistic execution (MEDIUM).** Phase 4 re-pricing with L2 and liquidity consumption can only reject.
- **An undelivered stall alert (MEDIUM; OPEN-R2-3).** Phase 3 is blocked until the forwarder accepts the event.
- **Infrastructure without nominability (HIGH; DEP-S8).** Every frozen record carries its HELD reason. The forward clock still starts at the freeze.

## Feasibility (honest)

**Arithmetic:**
- Today is 2026-10-06, so 111 days remain to the 2027-01-25 KILL.
- Phase 0 is days of work. If G2 ≠ ∅, Phase 2 puts the earliest G1 freeze around early to mid November. That leaves at most about 70–80 forward days.
- Nomination still waits on F5 GAP-13. Forward days accrue from the freeze regardless.
- At ≤ 1 take/day, with uptime below 1, the forward n is at most about 55–70.
- The e-process confirms only about 50–80% ROI (`r3:561`).

**Deployability:**
- **Only G1 is deployable before KILL.**
- **G2 is screen-only until F13** and a G11-style loader acceptance. Its value before KILL is to tell F13 which source to acquire.
- G3 needs the X1 erratum and build. G4 is out of scope.

**What AUT-S can realistically deliver before KILL:**
1. **Reject-only pruning** of G1 and G2 variants on the pre-holdout archive. This happens only if Phase 0 finds G2 ≠ ∅, because otherwise Lane S is not built (AS-R3).
   - It is n-rich only for the v4.x eras. v5.0 is thin (58 days).
2. **At most one or two frozen G1 candidates** with their forward clock started. They are likely flagged `unlikely_to_confirm`, and the most likely verdict is `INCONCLUSIVE(window_end_no_crossing)`, not PASS.
3. M1 routing: the `avoid_cells` export to F8, and `HELD(needs_x1)` freezes.

**What it will almost certainly not deliver:** a forward-confirmed winner. `forecast-edge-closed-pmus-rungs` records the market's resolution at 1.98× the forecast's. Re-tuning the CDF or the fit window of the same NBP information cannot close that gap.

**Order of effort:**
- Phase 0 step 0.3 (source inventory) decides everything.
- If G2 = ∅, AUT-S stops at Phase 1 and **F13 new-source acquisition becomes the binding programme item.**
- If G2 ≠ ∅, G2 screening comes first and G1 runs as a by-product. X1 stays on paper in parallel.

## Success criteria

- [ ] Phase 0 evidence is committed, covering: per-version inventory and STOPs; MDE; the champion sha reproduction; G2 eligibility with `available_at`; the ≥ 28 usable-day census; the benchmark peak and derived timeouts; the M1 parity fixture (OPEN-R2-1 resolved); and the take band.
- [ ] Phase 1 is merged with every [P1] test green. Every freeze is HELD with a reason, and no frozen JSON carries a manifest, allowlist, cap or permit field.
- [ ] (If G2 ≠ ∅) `spa.py` makes the M1 JSON byte-identical before and after. The ledger is hash-chained and committed.
- [ ] (If G2 ≠ ∅) Lane S evidence is one-shot. For each spec it lists:
  - the outcome in the closed vocabulary;
  - Bonferroni (K=48) LB and UB on both Δs;
  - the joint SPA p;
  - the resolution gain;
  - fold-wise Δ;
  - both controls.
  No day in it is ≥ 2026-07-01.
- [ ] (If Phase 3) The unit runs at 04:10Z: bwrap `network="none"`, `MemoryMax=4G`, `ExecCondition` plus the watchdog, the outbox alert, and `alpha_spent` unchanged.
- [ ] Every merge shows `EXIT=0` and `lint-imports` reporting "N kept, 0 broken".
- [ ] OPEN-R2-1..R2-4 are each resolved or still marked open, with a reason.

**Key files:**
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r1.md`
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/src/breezy/analysis/nbp_calibration.py`
- `/home/jon/breezy/src/breezy/analysis/brier_decomposition.py`
- `/home/jon/breezy/scripts/analysis/market_calibration_scan.py`
- `/home/jon/breezy/scripts/analysis/nbp_learning_nightly.py`
- `/home/jon/breezy/src/breezy/settlement/roi_bound.py`
- `/home/jon/breezy/deploy/systemd/breezy-replay-daily.service`
- `/home/jon/breezy/deploy/systemd/breezy-nbp-learning-nightly.service`
- `/home/jon/breezy/deploy/systemd/breezy-autonomy-bwrap`
- `/home/jon/breezy/src/breezy/runtime/autonomy_sandbox/table.py`
- `/home/jon/breezy/src/breezy/persistence/autonomy/capture_alerts.py`
- `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py`
- `/home/jon/breezy/scripts/archive/iem_mos_backfill.py`
- `/home/jon/breezy/src/breezy/runtime/backtest_harness.py`

---

## Coordinator notes (outside the plan body)

r2 applies all 11 rulings. No file was written. Things you should know before filing it:

- **r1 had a factual error.** It said a stationary bootstrap at block length 1 reproduces M1 exactly. It does not: M1 draws day weights with `rng.multinomial` at `market_calibration_scan.py:581-582`. r2 ties M1 parity to the verbatim day-block lift instead.
- **The template unit carries an exec path.** `breezy-replay-daily.service:58` sets `Environment=POLYMARKET_US_EXEC_STATE_DB=…`. r1 used that unit as its template, so copying it would have broken AS-R8. r2 says explicitly not to copy that line.
- **AS-R10's parity target may not exist.** Only the M1 `.md` is committed. The script writes its JSON to whatever `--out` was given. This is OPEN-R2-1.
- **Two choices in r2 are stricter than the rulings require:**
  - The Bonferroni divisor is the cap (48), not the running count.
  - AS-R8's network denial is tested by its effect (a socket connect fails), because systemd `--user` sandbox directives may be no-ops on this host.
- **The effect-size mapping needs stats-peer confirmation.** The AS-R5 synthetic-ask edge proxy has no existing code to match. This is OPEN-R2-2.
- **The alert forwarder is unconfirmed.** I did not verify that any forwarding unit accepts a non-capture outbox event. This is OPEN-R2-3, and it blocks Phase 3.
---

## Convergence review (stats, 2026-10-06) and coordinator rulings AS-R12..R16 (binding; these supersede conflicting r2 text)

- **AS-R12 (B1), negative control: an aggregate criterion.**
  - The shuffled-label control runs `S_neg` = 20 pre-declared seeds per spec.
  - The run is UNUSABLE only if more than `ceil(0.05·S_neg·K_tested) + 3·sqrt(0.05·0.95·S_neg·K_tested)` of the take-band Δ 95% intervals exclude 0 across all (seed, spec) pairs.
  - This replaces r2's "every per-spec interval covers 0". That rule gave a false-UNUSABLE rate of about 58%.
  - Test: `test_negative_control_aggregate_binomial_tolerance`.
- **AS-R13 (B2), mint statistic and family α.**
  - The mint rule's LB, SPA and same-sign tests run on the **take-band Δ of the live NBM version** (v5.0 today).
  - Other versions are reported but are informational only.
  - The family α is **0.05 one-sided** for the LB, Bonferroni at the cap: α/48 one-sided.
  - The MDE formula uses the same one-sided α/48: `(z_{1−0.05/48} + z_{0.80})·SE`.
  - Test: `test_mint_statistic_is_live_version_take_band_one_sided`.
- **AS-R14 (B3): Lane S never mints for v5 under the current data window.**
  - v5 has 58 climate days, split into 2 folds of 29. That is a different estimator regime from the deployed 58-day fit. Same-sign across 2 folds is about a 25% coin-flip under the null, and an MDE of about 4 SE is far beyond any CDF or window tweak.
  - §Lane S and §Feasibility are read to say: **for the live version, Lane S is G2-informational and reject-only. The mint rule cannot fire until a new data window is separately ruled.** A new window would touch post-07-01 holdout days, so it needs its own ruling.
  - The r2 "unlikely to clear" wording is withdrawn as too soft.
- **AS-R15 (B4): restore `test_multisource_consumes_no_execution_data`** (r1 line 120) as a [P2] test for every G2 spec.
- **AS-R16, the non-blocking items:**
  - **OPEN-R2-2 is resolved.** The synthetic-ask proxy is a flag only, with these properties:
    - it is measured in ROI against the `compute_roi_bound` detectable ROI at projected forward takes;
    - the fee is charged at the ask, with the ask rounded up to the tick;
    - it covers both sides;
    - it flags on the day-cluster bootstrap UB;
    - absence of the flag implies nothing.
  - **Phase 0 runs 0.3 first.** Steps 0.2 and 0.5 run only if G2 ≠ ∅.
  - **The 28-day Lane E STOP is a floor, not a sufficiency claim.**
  - **The leak flag needs a fold-count floor:** at least 3 folds, otherwise it reports `HELD_LEAK_AUDIT` on any Δ beyond 2 SE of the champion.
  - **Two stale test names are renamed** to match their content: `test_spa_matches_m1_scan_day_block` and `test_timer_outside_1600_1730z`.

**Status: READY.** Build starts at Phase 0, and only the read-only steps run first. Phase 1 may build after Phase 0 evidence is committed. Phase 2 and later remain conditional, per AS-R3.

**Programme consequence (coordinator):** AUT-S cannot produce a live-deployable winner before the 2027-01-25 KILL. The binding winner-search lever is **new US weather data (F13 / G2)**. F13 planning is raised accordingly once Phase 0 step 0.3 reports.
