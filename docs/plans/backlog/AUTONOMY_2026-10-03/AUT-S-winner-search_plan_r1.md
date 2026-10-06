# Implementation Plan: F10 AUT-S-PLAN, the AUT-S automated winner-search plan (r1)

Target path when filed: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r1.md`. This is the F10 deliverable (`FQ-LOSS-RESPONSE_plan_r3.md:479-482`). Nothing was written to disk.

## Overview

AUT-S is a standing, never-trading search. It generates strategy variants from a closed grammar, screens them with reject-only, multiplicity-controlled statistics, and hands a frozen survivor to AUT-3 `c3_writer` as a `variant_spec` (or `density_table_multisource`) candidate. α is charged only at the AUT-4 C5 nomination, on forward days after the freeze.

Before writing this plan I checked the binding inputs against the code. That check found four conflicts that cut the r2 grammar down sharply. Under E-26 today, the only variation a child can carry is in the **calibration artefact**. Venue tape exists only on holdout-period days. The plan makes those limits explicit rather than planning around them.

## Requirements

- **Directive (2026-10-04):** keep optimizing toward winning trades. AUT-S never trades, never writes C5, and spends no α at screening (`r3:582`).
- **r2 grammar and controls are kept** (`r2:267-276`, `r3:480`):
  - a K cap;
  - native `backtest()`/`BacktestEngine` plus `PortfolioAnalyzer.register_statistic` (FQ-R12);
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
- **E-25 rule 8** (`:617-620`): backtest-only input yields at most UNDERPOWERED or a screen rejection. It never yields PASS.
- **FQ-R14** (`r3:441-445`): screen and scan days never become nomination evidence. Nomination uses forward climate days strictly after the freeze.
- **FQ-R27** (`r3:665-668`): an M1 cell survives only if its Bonferroni LB > 0 **and** SPA p < 0.05.
- **Data scope:** model output is read only on out-of-fold data before 2026-07-01 (`DEFAULT_SPLITS.holdout_start`, `src/breezy/analysis/nbp_calibration.py:273-278`). `open_holdout` (`nbp_calibration.py:353`) is never called.
- **Prediction inputs are US weather sources only.** Venue prices are execution cost only.
- Neither operator-reserved cap is read, named or assigned.

## Verified facts this plan rests on

| # | Fact | Evidence |
|---|---|---|
| V1 | The child-manifest allowlist is `family_id`, `trial_id_prefix`, `d0_climate_day`, `density_artefact_path`, `density_artefact_sha256`, `live_orders_ruling`. A child's only behavioural lever is a new density artefact. | `src/breezy/persistence/autonomy/byte_binding.py:82-91`, `:124-144` |
| V2 | The FQ live loader reads only calibration keys: `delta`, `cdf_method`, `correction_form` ∈ {none, linear_lst_day_length}, `correction_linear_coefficients`, `correction_month_offsets`, `emos_params_by_version`, `emos_draws_by_version`, `fit_status` (OK), `recalibration` ("none" only), `converged_by_version`. | `src/breezy/strategy/forecast_quantile_ladder/calibration_artefact.py:66-71`, `:187-224`, `:264-292` |
| V3 | Decision knobs (margin m0/m24/h0, slippage floor) come from the code default `LadderEvConfig()`, not from the manifest or artefact. | `src/breezy/strategy/forecast_quantile_ladder/composition.py:188`; `margin.py:30-37` |
| V4 | FQ trades D+1 only, so same-day takes are structurally refused. | `src/breezy/strategy/forecast_quantile_ladder/decision.py:277-281` |
| V5 | M1 windows are `D-1_18Z`, `D_12Z` and `D_17Z`. | `scripts/analysis/market_calibration_scan.py:152-156` |
| V6 | M1 already implements a day-block bootstrap, White's RC and Hansen's SPA. | `market_calibration_scan.py:578-612` |
| V7 | Venue tape starts 2026-08-30, after the holdout boundary. | `scripts/analysis/nbp_shadow_parity_pure.py:99-100` |
| V8 | A native FQ-in-`BacktestEngine` shadow replay that never submits already exists. | `scripts/analysis/nbp_shadow_parity.py:275-383` |
| V9 | Nautilus provides `PortfolioAnalyzer.register_statistic`, and no repo code calls it yet. | `.venv/.../nautilus_trader/analysis/analyzer.py:59-71`; grep of `src/` is empty |
| V10 | The harness entry points are `run_backtest`/`backtest`, and both run `engine.run()` inside. | `src/breezy/runtime/backtest_harness.py:956-1022`, `:1025-1058` |
| V11 | The lifetime and window caps are 4 nominations per lineage, 1 per forward window, and 1 mint per lineage per day. | `src/breezy/persistence/autonomy/pins.py:38-41` |
| V12 | `c3_writer`, `elond`, `evidence_row` and an FQ backtest-only strategy do not exist yet. | glob of `persistence/autonomy/`; grep of `strategy/forecast_quantile_ladder/` |
| V13 | Reusable scoring and bounds code exists: `murphy_decomposition`; `compute_roi_bound` (B=10000, SEED=20260904); and `assert_split_disjoint`. | `src/breezy/analysis/brier_decomposition.py:177`; `src/breezy/settlement/roi_bound.py:93,97,173`; `scripts/analysis/forecast_conditional_corpus.py:358` |

## Conflicts and gaps (each needs a coordinator ruling; a default is proposed)

- **CONFLICT-S1: a pre-07-01-only screen against tape that starts 08-30 (V7).**
  - No venue ask exists before 2026-07-01, so a P&L backtest of a *model* variant on out-of-fold data is impossible.
  - **Default:** split the screen into two lanes.
    - **Lane S (skill).** Model variants are scored on pre-07-01 archive against CLI truth, paired against the champion. No venue data is used.
    - **Lane E (execution).** **Model-free** cells only, on tape days, reading no model output. This follows the M1 precedent (`r3:469`, `test_scan_reads_no_model_output`).
  - If the ruling forbids tape days altogether, Lane E is dropped.
- **CONFLICT-S2: the r2 grammar against E-26 (V1-V3).**
  - side, execution mode, horizon/hour window, observation conditioning and station subset are expressible as neither artefact nor manifest.
  - `stations` is explicitly frozen (E-26 rule 5).
  - Weather source belongs to the other new class, `density_table_multisource`, not to `variant_spec`.
  - **Default:** the grammar is tiered (§Grammar). Only tier G1 (calibration) and tier G2 (source set) are buildable now.
- **CONFLICT-S3: most M1 cells are unreachable by FQ.**
  - `D_12Z` and `D_17Z` are same-day windows, and FQ is D+1-only (V4). Those cells can only become a **new family**.
  - Only `D-1_18Z` cells map onto FQ, and even they need the side and ask-bin filter (tier G3).
- **CONFLICT-S4: the M1 nightly re-scan against "scan days never count as evidence".**
  - Once M1 runs nightly (FQ-R27), every forward day becomes a scan day, and forward n would be 0 forever.
  - **Default:** "screen day" is defined **per spec** as that spec's `selection_window_end` (≤ freeze day). Days after a spec's freeze may be re-scanned for *other* specs but never re-select that spec.
- **OPEN-S5: the mint-candidacy rule.** Reject-only decides REJECTED. Becoming a mint candidate should use the FQ-R27 dual rule (Bonferroni LB > 0 AND SPA p < 0.05), because only 4 lifetime nominations exist (V11). **Default:** adopt it.
- **GAP-S6: no backtest strategy for model-free cells (V12).** Lane E's `BacktestEngine` re-pricing needs a backtest-only cell strategy, which is a file outside the F11 list. **Default:** defer it to a trigger (the first FQ-R27 M1 survivor). Until then Lane E ingests M1's own JSON.
- **GAP-S7: the bwrap table row.** E-7a rule 1 needs a row in the ARCH-0-owned table (E-7e). This is a dependency, not an AUT-S file.
- **DEP-S8: nomination is infeasible today.**
  - Every `e_process` nomination of a non-champion is infeasible until F5 rules a forward-only shadow source (E-25 rule 6(b), GAP-13).
  - AUT-S can freeze and mint, but no survivor can be feasibly nominated before that ruling.

## Architecture changes

- NEW `src/breezy/analysis/autonomy/search/__init__.py`.
- NEW `src/breezy/analysis/autonomy/search/grammar.py`: the closed, versioned, hash-pinned grammar (frozen dataclasses), with tier tags.
- NEW `src/breezy/analysis/autonomy/search/generator.py`: deterministic enumeration, a cumulative K ledger, and emission of `VariantSpec` (artefact params only).
- NEW `src/breezy/analysis/autonomy/search/spa.py`: day-block or stationary bootstrap, White RC, Hansen SPA and Bonferroni. Lifted from `market_calibration_scan.py:578-612`, which then imports it (DRY, parity-tested).
- NEW `src/breezy/analysis/autonomy/search/screen.py`:
  - Lane S fold scoring and Lane E ingestion;
  - outcome vocabulary {`REJECTED_UB_LT_0`, `NOT_REJECTED`, `UNUSABLE`};
  - the mint-candidate selector;
  - the evidence JSON writer.
- NEW `deploy/systemd/breezy-autonomy-search.service` and `breezy-autonomy-search.timer`.
- EXISTING `src/breezy/runtime/backtest_harness.py`, **statistics registration only**:
  - add a keyword-only `statistics: Sequence[PortfolioStatistic] = ()` to `run_backtest` and `backtest`;
  - register each on `engine.portfolio.analyzer` between `add_strategy` and `engine.run()` (`:1006-1008`);
  - the default registers nothing, so every existing caller is byte-unchanged.
- EXISTING `scripts/analysis/market_calibration_scan.py`: replace `_bootstrap_stats`/`_max_tests` with imports from `spa.py`. This is a refactor with a parity test. It is a file outside the F11 list and is flagged for ruling; the alternative is to duplicate the code, which the plan rejects.
- Evidence: `docs/evidence/AUT_S_SCREEN_<date>.md` plus the JSON beside it (the FQ-R27 convention).

Native-first justification:
- The screen reuses `backtest()`, `BacktestEngine`, `PortfolioAnalyzer.register_statistic`, the `run_live_parity` shadow pattern (V8), `murphy_decomposition`, `compute_roi_bound` and `assert_split_disjoint`.
- New code is only what no existing module provides: a closed grammar, a K ledger, a reusable SPA library, and the screen glue.

## The search grammar

**Tier G1 (artefact-expressible today, `variant_spec`, V2):**

| Knob | Values | Artefact key |
|---|---|---|
| CDF family | `normal`, `pchip_normal_tails`, `skew_normal` (`quantile_density.py:88-90`) | `cdf_method` |
| Location correction | `none`, `linear_lst_day_length` | `correction_form` (+ coefficients) |
| EMOS fit window | all pre-fold, trailing 365 d, trailing 730 d | `emos_params_by_version`, `emos_draws_by_version` |
| Draw construction | `resample_delta` True / False | `emos_draws_by_version` |

- That is 3·2·3·2 = **36 specs, one of which is the champion's own**.
- `recalibration` is fixed at "none", because the loader refuses anything else.
- A G1 child equals its root on every manifest key except `density_artefact_path` and `density_artefact_sha256` (E-24).

**Tier G2 (`density_table_multisource`, E-26 rule 4):**
- The knob is the source set: the champion's NBP plus at most one added US source.
- A source qualifies only if it has archive covering every Lane S fold before 07-01. Phase 0 verifies this. The IEM MOS archive is a candidate (memory `iem-mos-archive-overlaps-tape-and-cli`).
- Screening is allowed. CHAMPION status also needs F13 live plus a separate G11-style loader acceptance (E-26 rule 4).
- There is no international data and no venue or execution input (`test_multisource_consumes_no_execution_data`).

**Tier G3 (NOT expressible; needs a separately reviewed change):**
- Knobs: side mask, decision-hour window (LST), ask floor and ceiling (this is the M1 `D-1_18Z` mapping), and margin m0/m24/h0.
- **Recommendation:** propose **no FQ manifest-schema extension**. A manifest change forces new-family registration (E-26 rule 6), and the manifest is immutable per family (E-24).
  - Instead, pre-draft a paper-only plan **AUT-S-X1, a restrict-only `policy` object read by the FQ live loader from the artefact.** That makes G3 artefact-expressible under the allowlist that already exists.
  - It is restrict-only: every field can only remove takes the root would make, so a child can never widen exposure.
  - It widens ARCH `:806` (the loader key set), so it needs its own erratum, live-loader parity tests and a node respawn.
  - **Build trigger:** the first FQ-R27 survivor in a `D-1_18Z` cell, or a G1/G2 mint candidate whose take set is concentrated in M1 reliable-loser cells. Draft the plan now, so the review lead time does not consume the forward window. Do not build until the trigger fires (YAGNI).
- The alternative, one new family per survivor, is rejected as the default. Each new lineage gets a fresh e-LOND budget, and E-25 rule 5 controls nothing across lineages, so a new family per cell is uncontrolled α-shopping.

**Tier G4 (new family only; never AUT-S output):** same-day windows (`D_12Z`, `D_17Z`), resting execution, observation conditioning, and station subsets. AUT-S writes these to a `new_family_queue` section of the evidence file with a programme-level count. It never registers a family.

**K cap:**
- `K_CYCLE = 12` specs per nightly cycle.
- `K_UNIVERSE = 48` cumulative per (grammar version, data window). The SPA universe and the Bonferroni K are the cumulative count, never the per-cycle count.
- The generator refuses past the cap. A grammar version bump keeps counting against the same data window.
- At most **1 mint candidate per cycle**, which matches `MAX_MINTS_PER_LINEAGE_PER_DAY=1`.

## The screen

**Lane S (skill, model variants):**
- **Data:** archive climate days before 2026-07-01 only.
  - Out-of-fold means blocked folds by calendar year (2021…2025, 2026H1).
  - The variant **and the champion** are refit per fold on the other folds and scored on the held fold.
  - `assert_split_disjoint` is reused.
  - Any day ≥ `DEFAULT_SPLITS.holdout_start` is refused.
- **Statistic:** the per-station-day Brier score of rung probabilities on the forecast-centred 2 °F ladder (the `nbp_learning_nightly._forecast_centered_ladder` convention).
  - Δ_d = score(champion) − score(variant), so positive means the variant is better. It is paired by day.
- **Decision instants:** the pinned hour windows that FQ's live D+1 trading uses, scoped by **date and hour**. The screen asserts forecast `available_at_ns < decision instant < settlement`.
- **Outcomes:**
  - `REJECTED_UB_LT_0` if the Bonferroni-adjusted UB of mean Δ < 0;
  - `UNUSABLE` if fold coverage < 95% or a leak assert fires;
  - otherwise `NOT_REJECTED`.

**Lane E (execution, model-free):**
- It ingests M1's JSON. A cell is a candidate only on M1's validity flag and the FQ-R27 dual rule.
- **Usable days:** settled FINAL, Depth10 coverage of every rung in the window, and no overlapping `QuoteTapeGap`. Otherwise `test_screen_refuses_non_replay_sufficient_day` applies (memory `quote-tape-is-not-replay-sufficient`).
- On the GAP-S6 trigger, a `BacktestEngine` re-price runs one station-day per engine (nbp_shadow_parity memory envelope) with `liquidity_consumption=True`. It can only reject, because M1's ask is an optimistic upper bound.

**Multiplicity:**
- `spa.py` provides White RC and Hansen SPA over the cumulative universe, plus a Bonferroni per-variant LB and UB.
- The stationary bootstrap has a pinned mean block length (7 days for Lane S, where serial correlation is real; 1 day reproduces M1 exactly).
- Seed and B come from `roi_bound.py:93,97`.

**Schema:**
- The closed key set has **no `WIN`, `PASS`, `WINNER` or `SURVIVOR` token**.
- Every row carries `source="backtest"` (Lane E) or `source="archive"` (Lane S), and E-25 rule 8 applies.
- The screen imports no `elond`, `RegistryStore` or `verdict` writer.

**Statistic parity:** a `PortfolioStatistic` subclass computes the clipped daily Y_d. It is registered through the harness change and must equal F7b `FqEvaluator`'s Y_d on a shared fixture.

## Forward-freeze handoff

1. The mint candidate (OPEN-S5 rule; ≤ 1 per cycle) is serialised as `aut_s/frozen/<variant_id>.json` and committed. Its commit SHA becomes **`spec_freeze_sha`**, and its LST climate day becomes the freeze day.
2. AUT-S calls AUT-3 `c3_writer.write_candidate`, the only writer allowed by E-26 rule 2:
   - `model_class` is `variant_spec` or `density_table_multisource`;
   - `lineage.json` carries `spec_freeze_sha` and `selection_window_end`;
   - `leakage_assertions` includes `nomination_days_after_spec_freeze`, `ref_ts_lt_take_ts` and `no_sealed_holdout_rows_in_train`.
3. AUT-4 OFFLINE_CHALLENGER screens it, and nomination follows. Nomination evidence is only forward climate days d > freeze day, with every decision instant on d later than the freeze commit time.
4. The handoff refuses while E-26 is unconsumed (`c3_writer` fail-closed) or while DEP-S8 holds (the nomination would be infeasible). The record is `HELD(<reason>)`, never a silent drop.

## M1 survivor ingestion

| M1 survivor | Route |
|---|---|
| `D-1_18Z` × side × ask bin | G3. Trigger the AUT-S-X1 plan. Until X1 is built, record it as `HELD(needs_x1)`. Never mint it. |
| `D_12Z` / `D_17Z` | G4 `new_family_queue` only. |
| Any reliable-loser cell (CI entirely below 0) | Exported as an `avoid_cells` list for F8's take rule (as decided in the M1 evidence). It is never a search candidate. |
| Invalid scan (validity flag false) | Refused. No ingestion. |

## Implementation steps

### Phase 0: verify-first (read-only; STOP gates)

1. **Archive inventory.** List, per station and source, the climate days before 07-01 with NBP and CLI FINAL rows. Confirm the champion artefact's fit window, so folds are truly out-of-fold. **STOP** Lane S if any fold has fewer than 150 station-days.
2. **G2 source eligibility.** List which US sources have per-fold archive. An empty result gives G2 = ∅, and that is stated.
3. **Usable tape days.** Run a census with the predicate above. **STOP** the Lane E `BacktestEngine` path if there are fewer than 14 usable days (mirroring `MIN_PRE_FREEZE_DAYS`, `nbp_shadow_parity_pure.py:101`).
4. **Benchmark.** Profile one G1 spec × one fold under `systemd-run -p MemoryMax=4G -p LimitNOFILE=524288`, and pin `RuntimeMaxSec` from the result.
- Risk: Low. Dependencies: none.

### Phase 1: minimum viable, Lane S by hand (mergeable alone; Needs F10 READY)

5. **`spa.py`**, lifted from M1, with M1 importing it. Run the parity test first (RED→GREEN). Risk: Medium (it touches a merged script).
6. **`grammar.py`** with G1 only, closed and hash-pinned. A test asserts the G1 keys ⊆ the loader-parsed keys (V2). Risk: Low.
7. **`generator.py`**: deterministic order, the cumulative K ledger (append-only JSONL beside the evidence), and refusal past the cap. Risk: Low.
8. **`screen.py`** Lane S plus the evidence writer, with the leak asserts and the holdout refusal. Risk: Medium (leakage).

### Phase 2: core loop (Needs F7b, E-26 consumed, AUT-3 r7 `c3_writer`)

9. **Harness statistics registration** in `backtest_harness.py`, plus the parity statistic. Risk: Low (default inert).
10. **Lane E M1 ingestion** and the routing table. Risk: Low.
11. **Freeze and handoff to `c3_writer`**, with HELD reasons. Risk: Medium.
12. **G2 grammar tier**, only if step 2 is non-empty. Risk: Medium.

### Phase 3: standing unit (Needs GAP-S7 bwrap row)

13. **`breezy-autonomy-search.service` and `.timer`** (see the next section). The coordinator symlinks, runs `daemon-reload` and `enable --now`, and records all three in the evidence file. Risk: Low.

### Phase 4: conditional (separate reviewed changes)

14. The AUT-S-X1 plan is drafted now and built on its trigger.
15. The GAP-S6 cell backtest strategy is built on its trigger.

## Memory and runtime caps (the unit)

- `Type=oneshot`, `Slice=breezy-studies.slice`, `MemoryHigh=3G`, `MemoryMax=4G`, `UMask=0077`, `OnFailure=breezy-study-failed@%n.service`. These are the same values as `breezy-replay-daily.service:36-41` and `breezy-nbp-learning-nightly.service:16-19`, and the unit joins `tests/unit/test_analysis_units_memory_capped.py`.
- `ExecStart` runs `deploy/systemd/breezy-autonomy-bwrap <row> flock -w 1800 <studies lock> <exact .venv python> -m …`. That gives E-7a bwrap, the E-15 no-network namespace and E-7c scratch.
- `LimitNOFILE=524288`. Any temporary base directory goes on `~/.cache`.
- `RuntimeMaxSec=7200`, so `TimeoutStartSec` covers the flock wait (E-9).
- **Stall watch:**
  - log one `AUT_S_PROGRESS i/K` line per spec;
  - if no spec completes within 20 min, raise `BREEZY_AUT_S_STALLED` through `alerts.env` and exit non-zero.
- **Timer:** `OnCalendar=*-*-* 04:10:00 UTC`, `Persistent=false`.
  - A guard refuses to start in [16:00Z, 17:30Z), which keeps it outside 16:30–17:10Z with margin.
  - Worst case is a 04:10 start + 30 min flock + 2 h run, ending by 06:40Z.
- **One heavy job at a time:** the shared flock enforces this. If the grammar is exhausted, the run writes a `NO_WORK` heartbeat and exits 0.
- **Environment:** only `EnvironmentFile=-%h/.config/breezy/alerts.env`. Never `operator.env`, venue credentials or trade env.

## Testing strategy

**r2/r3 names (kept):**
- `test_generator_deterministic_and_k_capped`
- `test_screen_schema_has_no_win_token`
- `test_screen_rejects_only_ub_lt_0`
- `test_screen_refuses_non_replay_sufficient_day`
- `test_screen_rows_source_backtest`
- `test_spa_pvalue_reported`
- `test_screen_spends_no_alpha` (AST: no `elond`, registry or verdict import)
- `test_register_statistic_parity_with_fq_evaluator`

**Additions:**
- Grammar and generator:
  - `test_grammar_closed_and_hash_pinned`
  - `test_grammar_g1_keys_subset_of_live_loader_keys`
  - `test_generator_child_manifest_diff_only_allowlisted` (via `manifest_equal_modulo_allowlist`)
  - `test_generator_never_varies_stations_fee_or_composition_kind`
  - `test_generator_k_universe_cumulative_across_cycles_and_grammar_versions`
  - `test_generator_order_independent_of_hash_seed_and_wall_clock`
- Leakage:
  - `test_screen_refuses_holdout_day_for_model_variant`
  - `test_screen_never_calls_open_holdout` (AST)
  - `test_screen_asserts_ref_ts_lt_take_ts`
  - `test_screen_scopes_windows_by_date_and_hour`
  - `test_screen_folds_blocked_and_disjoint`
  - `test_lane_e_reads_no_model_output`
- Outcomes:
  - `test_screen_outcome_vocabulary_closed`
  - `test_screen_positive_control_injected_loser_rejected_injected_edge_not_rejected` (L-38)
- SPA:
  - `test_spa_matches_m1_scan_at_block_length_one`
  - `test_spa_universe_and_bonferroni_k_cumulative`
  - `test_spa_seed_deterministic`
- Mint and handoff:
  - `test_mint_candidate_requires_bonferroni_lb_gt_0_and_spa_lt_005`
  - `test_at_most_one_mint_candidate_per_cycle`
  - `test_handoff_writes_spec_freeze_sha_and_selection_window_end`
  - `test_handoff_held_when_e26_unconsumed_or_nomination_infeasible`
  - `test_nomination_days_strictly_after_spec_freeze` (paired with E-26 `test_variant_spec_nomination_days_after_spec_freeze`)
- M1 ingestion:
  - `test_m1_ingest_routes_same_day_cells_to_new_family_queue`
  - `test_m1_ingest_refuses_invalid_scan`
  - `test_m1_reliable_loser_cells_exported_never_candidates`
- Harness:
  - `test_backtest_registers_statistics_before_run`
  - `test_backtest_default_registers_nothing` (L-55 production default)
- Isolation:
  - `test_search_imports_no_exec_or_adapter` (plus the firewall guards and the exec import pin in the focused gate)
  - `test_unit_memory_capped`
  - `test_unit_bwrap_wrapped`
  - `test_unit_reads_no_operator_env`
  - `test_timer_outside_1630_1710z`
  - `test_stall_watch_alerts_and_exits_nonzero`

**Gate after every merge:**
- `scripts/ci/run_tests_no_egress.sh`, reading `EXIT=0`;
- `cd <tree> && .venv/bin/lint-imports`, reporting "N kept, 0 broken";
- the mypy ratchet;
- `PYTHONPATH=<wt>/src`;
- never `uv`, `pip` or stash.

## Risks and mitigations

- **Multiplicity and data snooping** (HIGH). Nightly cycles over a fixed archive invite garden-of-forking-paths selection.
  - Mitigations: the cumulative K universe in both SPA and Bonferroni; a closed, hash-pinned grammar; mint candidacy needs the dual FQ-R27 rule; ≤ 4 lifetime nominations (V11) is the final backstop; a new family per survivor is refused as the default route (E-25 rule 5 gap).
- **Leakage** (HIGH). An implausible result is a leak.
  - Mitigations: assert `ref_ts < take_ts` (and `available_at < decision instant`) at load; scope windows by date **and** hour; fold disjointness; refuse holdout days; never call `open_holdout`. Any Δ improvement larger than the champion's own fold-to-fold spread is treated as `UNUSABLE` pending a leak audit, never as a finding.
- **Overfitting** (HIGH).
  - Mitigations: blocked out-of-fold refits of both arms; the stationary bootstrap (serial correlation); reject-only semantics; backtest or archive evidence can never PASS (E-25 rule 8); forward-only confirmation.
- **Optimistic execution** (MEDIUM). M1's ask is top-of-book at size ≥ 1. Lane E `BacktestEngine` re-pricing with L2 and liquidity consumption can only reject.
- **Holdout contamination through Lane E** (MEDIUM). Lane E is model-free only, and it is ruling-gated (CONFLICT-S1).
- **Shared-tree and memory hazards** (MEDIUM). Mitigations: flock, `MemoryMax=4G`, one station-day per engine, the stall watch, and a per-agent scratchpad for builders.
- **The infrastructure lands, but nothing is nominable** (HIGH, DEP-S8). The plan states this in every evidence record as HELD reasons.

## Feasibility (honest)

**Arithmetic:**
- Today is 2026-10-06, so 111 days remain to the 2027-01-25 KILL.
- Realistic F11 Phase 1–2 completion, plus E-26 consumption, AUT-3 `c3_writer` and the F5 GAP-13 ruling, puts the earliest freeze around early November. That leaves at most about 80 forward days.
- At ≤ 1 take/day, with uptime below 1 and m_cap dilution, n is at most about 55–70.
- The e-process confirms only about 50–80% ROI (`r3:561`). M1's median per-cell MDE is 19.8¢ at 26 days.

**What AUT-S can realistically deliver before KILL:**
1. Reject-only pruning of G1 and G2 variants on an n-rich archive. That stops reliably worse variants from shipping. It is cheap and valid.
2. At most one or two frozen candidates with their forward clock started. The most likely verdict for them is `INCONCLUSIVE(window_end_no_crossing)`, not PASS.
3. A standing, multiplicity-honest loop and a frozen queue that outlast the KILL date.

**What it will almost certainly not deliver:** a forward-confirmed winner from G1 calibration tweaks. The memory finding `forecast-edge-closed-pmus-rungs` says the market's resolution is 1.98× the forecast's. Re-tuning the CDF or the correction of the same NBP information cannot close a gap that size.

**Where effort goes first: new US data sources (G2) before rule variants (G1/G3).**
- Only new information can close a resolution gap.
- Lane S is the one n-rich place where a source's skill gain is measurable, with years × stations of out-of-fold archive.
- Rule variants re-slice information the market already prices. M1's only robust finding is loser avoidance (cheap YES), which belongs to F8's take rule, not to search.
- The order is therefore: Phase 0 step 2 (source archive inventory) → G2 screening → G1 as a cheap by-product. AUT-S-X1 is drafted on paper in parallel so its review lead time does not hold up a triggered survivor.
- If step 2 finds no source with archive, the plan says so: AUT-S then provides pruning only, and new-source acquisition (F13) is the binding programme item.

## Success criteria

- [ ] Phase 0 inventory, usable-day census and benchmark are committed, and every STOP gate is evaluated.
- [ ] Lane S evidence lists, for each spec: the outcome in the closed vocabulary; the Bonferroni LB/UB; the SPA p over the cumulative K; and the folds used. No day is ≥ 2026-07-01.
- [ ] `spa.py` reproduces M1's RC/SPA exactly at block length 1.
- [ ] The harness default is byte-inert, and statistic parity with `FqEvaluator` is green.
- [ ] Every mint candidate carries `spec_freeze_sha` and `selection_window_end`, and its nomination counts only post-freeze days. Otherwise it is recorded as HELD with a reason.
- [ ] The unit runs nightly at 04:10Z: bwrap-wrapped, `MemoryMax=4G`, stall-watched, outside 16:30–17:10Z, with `alpha_spent` unchanged.
- [ ] Every merge shows `EXIT=0` and `lint-imports` reporting "N kept, 0 broken".

Key files:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md`
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/docs/evidence/M1_MARKET_SCAN_2026-10-04.md`
- `/home/jon/breezy/src/breezy/persistence/autonomy/byte_binding.py`
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/calibration_artefact.py`
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/composition.py`
- `/home/jon/breezy/src/breezy/runtime/backtest_harness.py`
- `/home/jon/breezy/scripts/analysis/market_calibration_scan.py`
- `/home/jon/breezy/scripts/analysis/nbp_shadow_parity.py`
- `/home/jon/breezy/scripts/analysis/nbp_shadow_parity_pure.py`
- `/home/jon/breezy/src/breezy/analysis/nbp_calibration.py`
- `/home/jon/breezy/deploy/systemd/breezy-replay-daily.service`