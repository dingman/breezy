# LEAK-NULL plan r2 (2026-11-03): multi-seed outcome-blind null study of F13's shuffled-label control (M3 vs M0prime)

Purpose: decide whether `f13_verdict=HELD_LEAK_AUDIT` (run `gap1_j3_2026-11-02`) is cleared or confirmed, without a second
look at the GAP-1 primary (L-34). r1 premises §1–§4 still hold (see plan_r1.md). r2 WINS over r1 where they conflict.
Checked against code on 2026-11-03 (primary tree). Peer review r1: review_r1.md (B1–B10 binding).

## Changes from r1
| Item | Resolution (where) |
|---|---|
| B1 statistic | Per-null across-seed mean `M_N` with one-sided t lower bound `L_N` decides; per-seed `lb>0` counts descriptive except R2; per-seed bootstrap sub-seed (AC6, AC7) |
| B2 rule | Frozen R0–R4 with numbers; failed seeds handled; K == 20 exact; no successor (AC8, AC9) |
| B3 fold-disjointness | `fold_disjointness_defects` on ctx before any fit; breach = R0 (AC10); sidecar states what nulls cannot see (AC14) |
| B4 positive control | Planted LAMP-slot leak under N2 on seeds[:5] must be flagged else R0 (AC11); planted-leak→R1 e2e test |
| B5 bias-adjusted | F13-scoped `adj_lb = 0.150 − M_N1` from numbers on record; required by R4, reported always, never applied to GAP-1 dRES (AC12) |
| B6 probe | Tempdir outside out_root, deleted after; times one fold of each N1/N2/N3; `projected_seed_s` = sum × n_folds (AC13) |
| B7 code pin | Prereg `code_sha` ancestor-of-HEAD + blob-equality refusal on pinned files (AC4) |
| B8 seam | `run_study(ctx, design, out)` core; `prepare_run` only via `_prepare_context`; attribute-call rule for the spy (AC15) |
| B9 fixture | `make_rows`/`_row`/`_pct`/`_lamp_feature` from tests/unit/test_multisource_blend.py; 2 versions × 84 days → 3 folds/version |
| B10 scramble | Nested `replace` on `lamp.rem_max_f` only; `lamp_input_f` follows; `_assert_admissible` test (AC3) |
| Correction | r1 hard-coded `n_boot=5000`; J3's `_delta` (skill:553-561) uses `ctx.pins["bootstrap_n"]` and `ctx.fixed["mean_block_days"]` → r2 reads both from ctx. F13 `embargo_days` = 3 |
| Non-blocking (all adopted) | Frozen dataclasses (`Thresholds`, `SeedSummary`, `LeakNullDesign`); `NullId` StrEnum; only `random.Random(subseed)`; `sys.path.insert(ROOT)` + `from scripts.analysis import …`; PYTHONPATH = worktree; sidecar notes N2 λ=0 on both arms and the level-0 cell dependency (fit.py:189-195); result copy under docs/evidence/gap1_source_resolution/; freeze ordering (Execution 5) |

## Trade-offs
| Option | Verdict | Why |
|---|---|---|
| N1 within-version shuffle (`msb.shuffle_labels(rows, seed=s)`), 20 seeds, λ=1 | RUN | Is J3's NC lb>0 typical; gives the bias term for B5 |
| N2 = N1's labels, `weight_sum_lambda=0.0` | RUN (discriminator) | Removes only the benign penalty channel; a pipeline leak persists |
| N3 = N1's labels + LAMP/PFM/MOS each permuted within (version, horizon) | RUN (relative to N1) | Noise regressors with realistic marginals; tests dependence on source–q50 collinearity |
| Station×month permutation / circular shift | REJECT | Keeps more structure; λ-flattening still works |
| Per-seed `lb>0` count as the gate (r1) | REJECT (B1) | Fold-scale autocorrelation → per-seed α > 0.025; power ≈ 32% at a 0.10 leak rate |
| Across-seed t bound on per-seed day-mean deltas | ADOPT | Seeds are the replication unit; dependence only through shared features |
| Positive control on 5 seeds under N2 | ADOPT (B4) | Proves the rule can fire; +5 N2 seed-units |

## Acceptance Criteria
1. **Out dir.** Writes only under `/mnt/storage/breezy/derived/gap1_source_resolution/leak_null_<YYYY-MM-DD>/`. Refuses any
   path with a `gap1_j3_*` component; any path under `~/.local/share/breezy` (raw and `.resolve()`d); a basename not
   matching `^leak_null_\d{4}-\d{2}-\d{2}$`.
2. **Never real labels.** Every `msb.out_of_fold_scores` call receives `NullLabels.rows` with `moved_fraction ≥ 0.5`.
   `moved_fraction` is counted by KEY: share of (version, station, climate_day) keys whose label source key ≠ itself,
   reproduced from `random.Random(seed)` in `shuffle_labels` insertion order and cross-checked value-for-value against
   `msb.shuffle_labels`; mismatch → Refusal. Output is an allowlist holding no unpermuted M3−M0prime statistic.
3. **Inputs and N3 scramble.** Inputs are exactly the prereg-pinned paths (F13 prereg, f.jsonl, fl.jsonl, c1 evidence),
   sha256-verified; basenames `result.json`, `murphy.json`, `stage_a.json`, `oof_rows.jsonl` refused. N3 scramble =
   nested `replace(row, lamp=replace(row.lamp, rem_max_f=…))` over rows with `lamp.missing=False`, plus `pfm_mu_f` /
   `mos_mu_f` among present rows; never touches `cli_tmax_f`, `percentiles`, `obs_*`, `*_available_at_ns`, other
   LampFeature fields. `lamp_input_f = max(obs, rem_max_f)` moves automatically.
4. **Freeze and code pin.** Prereg frozen (`check_frozen_blob` + `check_not_refrozen`); `provenance.json` write-once with
   prereg digest, code_sha, input shas; digest mismatch at start, on resume, or before the result write → Refusal, no
   result. Code pin: prereg `code_sha` (full lowercase) must be HEAD or an ancestor (`git merge-base --is-ancestor`,
   gap1_oof_murphy.py:521-533 pattern with a `repo` parameter) AND for every `pinned_blobs` path
   `git hash-object <path>` == `git rev-parse <code_sha>:<path>`. `pinned_blobs` = `leak_null.py`, `leak_null_decide.py`,
   `leak_null_study.py`, `leak_null_guards.py`, `multisource_blend_{fit,folds,stats,features}.py`, `multisource_blend.py`,
   `multisource_blend_skill.py`. Otherwise Refusal, exit 2. Runs at start, on resume, before the result write.
5. **Seeds.** `seeds` is exactly 20 distinct ints (`K == 20`; ≠ → Refusal); excludes 20261006 and `probe_seed`;
   `pc_seeds = seeds[:5]`. Same seed → byte-identical seed file; `wall_s` only in `timing.jsonl` (non-gating).
6. **Per-seed estimator.** `msb.delta_summary(msb.delta_by_day(scored,"M0prime","M3"), n_boot=int(ctx.pins["bootstrap_n"]),
   seed=boot_seed, mean_block=float(ctx.fixed["mean_block_days"]))`. Sub-seed rule:
   `subseed(seed, tag) = int(sha256(f"leak_null:{seed}:{tag}".encode()).hexdigest()[:16], 16)`;
   `boot_seed = subseed(seed, f"boot:{null_id}")`; scramble tags `scramble:lamp|pfm|mos`; plant tag `plant`; the label
   permutation itself uses `seed`. Per-seed positive iff `lb > 0.0` (copied from stats.py:230).
7. **Across-seed statistic.** For each null N over its `n` completed seeds: `M_N` = mean of per-seed `DeltaSummary.mean`;
   `sd` = `statistics.stdev`; `L_N = M_N − t_{0.975,n−1}·sd/√n` with `t = scipy.special.stdtrit(n−1, 1−ALPHA_ONE_SIDED)`;
   at n = 20 exactly `L_N = M_N − 2.093·sd/√20`. Prereg pins `t_crit_k20: 2.093`, `t_crit_pc5: 2.776`; validator refuses if
   |stdtrit − pin| ≥ 5e-4.
8. **Frozen decision rule, in order, on this study's numbers only.**
   - **R0 INVALID** (HELD stands) on any of: level-0 invariant |CRPS(M0prime)−CRPS(M3)| > 1e-9 on rows with
     `levels["M3"]==0`; fold-disjointness defect (AC10); N3 M0prime ≠ N1 M0prime row for row (> 1e-9); `prefix_level`
     changed by scramble or plant; positive control not flagged (AC11); < 18 completed seeds in any null; prereg digest or
     code pin changed.
   - **R1:** `L_N2 > 0` and `M_N2 ≥ 0.005` → **LEAK_CONFIRMED** (GAP-1 PASS withdrawn to UNRESOLVED-LEAK; #10 held).
     `L_N2 > 0` and `M_N2 < 0.005` → **HELD_INCONCLUSIVE**.
   - **R2:** `L_N1 ≤ 0` and N1 per-seed positives ≤ 2/20 → **DISCHARGED_FLUKE**.
   - **R3:** `L_N1 > 0`, `L_N2 ≤ 0`, `M_N2 ≤ 0.25·M_N1`, `L_N3 > 0`, `M_N3 ≥ 0.5·M_N1` → **DISCHARGED_BENIGN_DOF**.
   - **R4:** `L_N1 > 0`, `L_N2 ≤ 0`, `M_N2 ≤ 0`, and AC12 passes → **DISCHARGED_PENALTY_MEDIATED** (pipeline clean;
     sufficiency not shown).
   - **Anything else → HELD.** Every discharge requires R0 to pass.
   - **Failed seeds:** `FitNotConvergedError` in a null marks that (seed, null) failed with reason; counts as non-positive
     with denominator K = 20; excluded from `M_N` / `sd` / `n`.
9. **No edits to J3 or GAP-1.** J3 `result.json` and GAP-1 PREREG never edited; verdict only in a new sidecar + PROGRESS;
   NC-FIX (DoF-matched negative control) filed; no threshold relaxed; no successor study on INVALID / HELD /
   HELD_INCONCLUSIVE / R4 (L-34).
10. **Fold-disjointness (outcome-blind).** Before any fit, for every fold in `ctx.plan`, recompute the effective train set
    independently as out_of_fold_scores (folds.py:310-317) builds it: same version, day ∈ `train_days`, |day − h| >
    `ctx.embargo_days` for every held h (window re-derived here, not imported from `_blocked_days`). Check (a) no held key
    (version, station, climate_day, horizon) in train keys; (b) min |train_day − held_day| > embargo_days; (c) each
    (version, climate_day) held in exactly one fold; after scoring (d) every `ScoredRow.climate_day` ∈ its `fold_id`'s
    held_days. Champion/M0 pool out of scope (`champion=False`); M0prime's recalibration is inside `fit_blend` on the same
    train set.
11. **Positive control.** For s ∈ seeds[:5]: `plant_leak(null_label_rows(rows, s), seed=s, noise_sd_f=1.0)` sets
    `lamp.rem_max_f = cli_tmax_f(null) + gauss(0, 1.0)` on LAMP-present rows, scored under N2 settings. Flagged iff
    `L_PC = M_PC − 2.776·sd/√5 > 0` and `M_PC ≥ 0.005`. Any PC seed failure or no flag → INVALID, written immediately. PC
    runs before the 20 study seeds.
12. **Bias-adjusted check (F13-scoped).** Prereg `f13_record = {m0p_vs_m3_mean: 0.165, m0p_vs_m3_lb: 0.150, floor: <copied
    from decide_acceptance>, source: "docs/evidence/GAP1_SOURCE_RESOLUTION_2026-11-03.md"}`; null `floor` → cannot freeze;
    driver never opens J3 artefacts. `adj_lb = 0.150 − M_N1`; PASS iff `adj_lb > 0.0 and adj_lb ≥ floor` (mirrors
    `_lb_failures`, stats.py:208-214, M0prime−M3 line only). Reported as `f13_bias_adjusted` for every verdict; adjusts
    F13's verdict only; GAP-1 PASS withdrawn only via R1; never applied to the 0.0152 RES threshold.
13. **Timing probe** (`--timing-probe --probe-parent <dir>`). UNFROZEN LEAK prereg allowed only here; code pin still
    applies. `<dir>` must be outside out_root (`.resolve()`) → `tempfile.mkdtemp(dir=…)` → `prepare_run(out_dir=tmp)` →
    largest-train fold only; scores N1, N2, N3 on `probe_seed` (outside the seed list) → `shutil.rmtree` in `finally`.
    Prints exactly `folds=<n> n1_s=<a> n2_s=<b> n3_s=<c> projected_seed_s=<(a+b+c)·n> projected_pc_s=<5·b·n>`. Never calls
    `seed_summary`/`decide`, emits no CRPS/delta, writes nothing under out_root.
14. **Sidecar** states what the nulls cannot see: a label-carrying feature; NBP availability (KNYC-DROP / NBP pin);
    temporal/embargo leaks beyond AC10; a common-mode own-day leak through M0prime (cancels in the delta).
15. **Seam.** `run_study(ctx: skill.RunContext, design: LeakNullDesign, out: Path) -> dict[str, Any]`. `main` calls the
    module-level `_prepare_context(design) -> RunContext`, the only `skill.prepare_run` call site. Scoring is
    `msb.out_of_fold_scores(...)` looked up as a module attribute at call time (never `from … import`), with
    `levels=(0,3)`, `champion=False`, `embargo_days=ctx.embargo_days`.

## Edge Cases & NFRs
- N2 λ=0 non-convergence: caught per (seed, null); other exceptions propagate (no result; resume continues); > 2 failed →
  R0 via n < 18.
- Restart unit = one seed: `seeds/seed_<s>.json` (N1+N2+N3 summaries + invariants) and `seeds/pc_<s>.json`, each
  `open("x")`; resume skips a file only if its `prereg_sha256` and `code_sha` match; torn/unparsable → Refusal.
- Fixed-key `moved_fraction` < 0.5 → Refusal (fail closed). N3 cell drop-outs reported (non-gating).
- `sd == 0` → `L_N = M_N`. `M_N1 ≤ 0` makes R3 ratio tests fail naturally (no division).
- Memory: `--max-memory-gib 3.5` (`skill.apply_address_space_cap`), `MemoryMax=6G`, `LimitNOFILE=524288`, L-83 thread
  env; never alongside the nightly study.
- Persist per-seed day-level delta vectors (~1968 floats per null); shuffled/scrambled rows never persisted.

## Architecture & Data Flow
1. `PREREG_LEAK_NULL_<date>.json` → `leak_null_guards.load_leak_prereg` → `LeakNullDesign`.
2. `guard_out_dir` → `verify_inputs` → `check_code_pin(ROOT, …)` → `record_provenance`.
3. `_prepare_context` (`skill.prepare_run`, writes only `<out>/f13_context/prereg_record.json`) → `run_study(ctx, design,
   out)`: `fold_disjointness_defects(ctx.rows, ctx.plan, ctx.embargo_days)` non-empty → write INVALID; PC loop →
   `pc_flagged` false → write INVALID; per seed `L = null_label_rows(ctx.rows, s)`; N1 = score(L, ctx.settings);
   N2 = score(L, null_settings(ctx.settings, N2)); N3 = score(scramble_sources(L, s), ctx.settings); `seed_summary` +
   invariants → seed file; `decide(summaries, pc, defects, f13_record, THRESHOLDS)` → `assert_unchanged` (digest + code
   pin) → `leak_null_result.json` (write-once, allowlist).
4. Pure logic in `src/breezy/analysis/leak_null*.py` (facade `breezy.analysis.multisource_blend` only); all I/O and git
   in scripts.

## File-by-File Plan
| Path | | Contents (signatures; budget) |
|---|---|---|
| src/breezy/analysis/leak_null.py | new, ≤ 230 | `NullId(StrEnum)` N1_within_version/N2_penalty_off/N3_scrambled_sources; `subseed(seed:int, tag:str)->int`; `@dataclass(frozen) NullLabels(rows: tuple[FeatureRow,...], moved_fraction: float)`; `null_label_rows(rows, seed:int)->NullLabels` (shuffle + key-permutation replay + cross-check); `scramble_sources(labels:NullLabels, seed:int)->NullLabels`; `plant_leak(labels:NullLabels, *, seed:int, noise_sd_f:float)->NullLabels`; `null_settings(settings:BlendSettings, null_id:NullId)->BlendSettings`; `fold_disjointness_defects(rows, plan:FoldPlan, embargo_days:int)->tuple[str,...]`; `scored_fold_defects(scored, plan)->tuple[str,...]`; `level0_max_abs(scored)->float`; `m0prime_max_abs(a, b)->float`; `prefix_preserved(before, after)->bool` |
| src/breezy/analysis/leak_null_decide.py | new, ≤ 190 | `@dataclass(frozen) Thresholds` (lb_gt 0.0, leak_mean_min 0.005, fluke_count_max 2, benign_n2_ratio_max 0.25, benign_n3_ratio_min 0.5, invariant_tol 1e-9, max_failed_seeds 2, min_moved_fraction 0.5, k 20, pc_k 5, t_crit_k20 2.093, t_crit_pc5 2.776, plant_noise_sd_f 1.0); `THRESHOLDS: Final`; `@dataclass(frozen) SeedSummary(seed, null_id, mean, lb, n_days, by_horizon, by_m3_level, day_values, failed: str\|None)`; `seed_summary(scored, *, seed, null_id, n_boot, boot_seed, mean_block)->SeedSummary`; `@dataclass(frozen) Bound(m, sd, n, t, l)`; `across_seed_bound(summaries)->Bound`; `pc_flagged(pc, th)->bool`; `f13_bias_adjusted(record, m_n1)->dict`; `LeakNullVerdict(StrEnum)` (INVALID, LEAK_CONFIRMED, HELD_INCONCLUSIVE, DISCHARGED_FLUKE, DISCHARGED_BENIGN_DOF, DISCHARGED_PENALTY_MEDIATED, HELD); `decide(by_null, pc, invariant_defects, f13_record, th)->tuple[LeakNullVerdict, tuple[str,...]]` |
| scripts/analysis/leak_null_guards.py | new, ≤ 200 | `Refusal = skill.Refusal`; `@dataclass(frozen) LeakNullDesign`; `load_leak_prereg(path, *, allow_unfrozen:bool)->LeakNullDesign` (mirrors `gap1_oof_murphy.load_prereg`; refuses K≠20, duplicates, 20261006, probe_seed in seeds, thresholds ≠ `THRESHOLDS`, null `f13_record.floor`, t-pin drift); `guard_out_dir(path, out_root)->Path`; `verify_inputs(design)->dict[str,str]`; `code_ok(repo, older, newer)->bool`; `check_code_pin(repo, code_sha, paths)->None`; `record_provenance(out, design, shas)->None`; `assert_unchanged(out, prereg_path, design, repo)->None` |
| scripts/analysis/leak_null_study.py | new, ≤ 280 | `sys.path.insert(ROOT)` + `from scripts.analysis import multisource_blend_skill as skill, leak_null_guards as g`; `import breezy.analysis.multisource_blend as msb`; `_prepare_context(design)->skill.RunContext`; `_score(ctx, labels, settings)->list[ScoredRow]` (the only `msb.out_of_fold_scores` caller); `run_seed(ctx, design, seed)->dict`; `run_pc(ctx, design)->list[SeedSummary]`; `run_study(ctx, design, out)->dict`; `run_probe(design, probe_parent)->str`; `assemble_result(...)->dict` (allowlist); `main(argv)->int` (argparse `--prereg --out-dir --max-memory-gib --timing-probe --probe-parent`; exit 2 on Refusal) |
| docs/plans/backlog/GAPS_2026-11-01/gap1_source_resolution/PREREG_LEAK_NULL_<date>.json | new | `frozen_sha`, `code_sha`, `pinned_blobs`, `inputs` (F13 prereg path + content_sha256 1e9db7ac… + frozen_sha 205fd542…; f/fl shas from `build.json.output_sha256`; c1 path + sha 792ff2a8…), `nulls`, `seeds` (20), `probe_seed`, `thresholds` (= `THRESHOLDS`, `source:"multisource_blend_stats.py:230"`), `decision_rule` (AC8 verbatim), `f13_record`, `envelope`, `probe_record`, `forbidden_inputs`, `out_root` |
| tests/unit/test_leak_null.py, test_leak_null_decide.py, test_leak_null_study.py | new | below |
| docs/evidence/gap1_source_resolution/LEAK_NULL_<date>.md + byte-identical `leak_null_result.json` | new, after run | sidecar (AC14 + notes), L-75 sha-matched copy |
| docs/core/PROGRESS.md | modified, after run | HELD_LEAK_AUDIT disposition, #10 state, NC-FIX filed |

No change to `multisource_blend_*.py`, `multisource_blend_skill.py`, or any J3 artefact.

## Test Strategy (RED first; PYTHONPATH=<worktree>/src:<worktree>)
**Fixture** `_null_fixture()` in test_leak_null.py: `make_rows(days=84, start=dt.date(2025,1,1), version="v4.2",
horizons=("D-1","D0"), seed=11)` + same for `"v4.3"` starting 2025-03-26, no label ties; post-processed with
`dataclasses.replace`: D-1 rows → `lamp=msb.MISSING_LAMP`; every 3rd D0 station-day → `MISSING_LAMP` (prefix 0, keeps the
(0,obs) cell ≥ `min_cell_rows` 20). Plan: `msb.build_folds(msb.days_by_version(rows), source_breaks=[], block_days=28,
min_train_days=28, min_blocks=2)` → 3 folds per version. Settings from `_PINS` (`from tests.unit.test_multisource_blend_skill
import _PINS, _git, _freeze`). `_tied_rows()` = `_row(...)` with integer `y`. Synthetic `skill.RunContext(design={"pins":
_PINS, "fixed_by_plan": {"mean_block_days": 7}, "frozen_sha": …}, out_dir, rows, rows, settings, plan, 3,
skill.split_lag_keys(rows, rows))`. e2e designs use K=2, pc_k=2 by constructing `LeakNullDesign` directly (K==20 tested on
the validator).

**test_leak_null.py:** null_label_rows_equals_shuffle_labels_same_seed; moved_fraction_counts_keys_not_values_under_integer_ties;
moved_fraction_replay_mismatch_refuses; below_min_moved_fraction_refused; scramble_nested_replace_only_rem_max_pfm_mos;
scramble_preserves_prefix_level_presence_and_timestamps; scramble_permutes_within_version_horizon_only;
scrambled_rows_pass_assert_admissible; lamp_input_f_follows_rem_max; plant_only_on_lamp_present_rows_and_from_null_labels;
null_settings_n2_only_changes_lambda; subseed_distinct_per_tag_and_stable; fold_disjointness_clean_on_fixture;
fold_disjointness_flags_planted_overlap; fold_disjointness_flags_embargo_violation; scored_fold_defect_flags_wrong_fold_id;
level0_rows_have_exactly_zero_delta; n3_m0prime_equals_n1_m0prime; train_set_rederivation_matches_out_of_fold_scores (spy on
`fit_blend` row keys).

**test_leak_null_decide.py** (synthetic `SeedSummary` lists, K=20): bound_equals_2093_formula_at_k20; stdtrit_matches_pins;
seed_summary_matches_msb_delta_summary; lb_exactly_zero_is_not_positive; decide_r0_each_trigger (7 parametrized);
decide_r1_leak; decide_r1_small_mean_held_inconclusive; decide_r2_fluke; decide_r2_blocked_by_three_positives;
decide_r3_benign_dof; decide_r4_requires_bias_check; decide_else_held; failed_seeds_non_positive_denominator_k;
seventeen_completed_is_invalid; pc_flag_requires_both_bound_and_floor; f13_bias_adjusted_mirrors_lb_failures.

**test_leak_null_study.py:** refuses_out_dir_inside_gap1_j3_dir (direct, symlink, `..`); refuses_live_data_root_raw_and_resolved;
refuses_bad_basename; k_not_20_refused; duplicate_or_f13_or_probe_seed_refused; thresholds_other_than_frozen_refused;
null_f13_floor_refused; input_sha_mismatch_refuses; forbidden_basenames_refused; real_freeze_path_accepts_and_refreeze_refused
(tmp repo via `_git`/`_freeze`); prereg_digest_mismatch_refuses; prereg_changed_mid_run_writes_no_result;
code_pin_refuses_non_ancestor; code_pin_refuses_worktree_blob_drift; code_pin_refuses_head_blob_drift; never_scores_unpermuted_labels
(patches `msb.out_of_fold_scores` on the facade; `skill.run_stage_a/run_stage_b/_score` patched to raise; ≥ 50% of keys'
`cli_tmax_f` differ on every call); result_allowlist_has_no_primary_statistic; seed_determinism_byte_identical;
seed_files_write_once_and_resume_skips_done; torn_seed_file_refused; unfrozen_refused_outside_probe;
timing_probe_writes_nothing_under_out_root; probe_prints_only_timing_keys_and_sums_three_nulls; probe_parent_inside_out_root_refused;
fold_breach_short_circuits_invalid; pc_unflagged_short_circuits_invalid (plant noise_sd_f=1e3 via design);
planted_leak_in_n2_drives_leak_confirmed (N2 scores `plant_leak(...)` rows → `LEAK_CONFIRMED`);
end_to_end_fixture_emits_verdict_equal_to_decide (`_prepare_context` monkeypatched).

**Gate:** `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy-leak-null/.pytest-tmp/leak_null`, read exit code, `rm -rf`
the basetemp; `lint-imports`; ruff check + ruff format + mypy on touched files only.

## Execution Order & Parallelism
1. r2 peer review (architect ‖ python-reviewer ‖ prediction-market-reviewer).
2. Author in `/home/jon/breezy-leak-null` (route per cycle: grok → Codex → Claude; hard invariants in the brief). Two
   parallel seams: (a) `leak_null.py` + `leak_null_decide.py` with RED tests; (b) `leak_null_guards.py` with RED tests;
   then the driver + study tests (depends on a and b).
3. Claude tdd-guide reads the diff, re-runs the gate on the artifact, commits by path, merges.
4. From the primary tree on the run branch: draft the prereg with `code_sha` = merge sha (UNFROZEN), then the L-82
   dry-run: `--help` → 0; a `gap1_j3_*` out dir → 2; `--timing-probe --probe-parent <scratchpad>` under the systemd
   envelope. Record exit codes, the probe line and `RuntimeMaxSec = max(14400, 1.5·(20·projected_seed_s +
   projected_pc_s))` (widen-only).
5. Commit the probe values (UNFROZEN), then exactly one stamp commit. Never stamp in the worktree and rebase.
6. `systemd-run --user` (MemoryMax=6G, LimitNOFILE=524288, thread env) with a delegated stall watch.
7. Verdict → sidecar + sha-matched copy + PROGRESS + NC-FIX + a lesson if the run diverged.

## Risk Register
| Risk | Mitigation |
|---|---|
| Seeds share features → t bound approximate | Stated in sidecar; the fold-scale dependence that broke r1 is inside each seed's mean, not across seeds |
| N2 λ=0 non-convergence | Failed seeds counted; n < 18 → INVALID |
| Positive control too weak through the `max(obs, ·)` mask | Noise sd 1.0 °F; e2e test proves it flags; unflagged PC → INVALID, never a discharge |
| `f13_record.floor` not on record | Prereg cannot freeze |
| Compute overrun (+5 PC seeds) | Probe envelope, widen-only (L-12); seed-granular resume |
| HEAD moves under concurrent agents | Blob-equality pin at start, on resume, before result write |
| `prepare_run` writes `prereg_record.json` | Confined to `<out>/f13_context` or the probe tempdir |
| Codex reformats whole dirs | Touched files only; diff reviewed |
| Independent train-set re-derivation diverges from folds.py | Unit test asserts equality on the fixture (spy on `fit_blend` row keys) |

## LESSONS Compliance
L-12 thresholds copied never relaxed, envelope widen-only. L-34 one look: real labels never scored (type-enforced
`NullLabels`); no result/murphy/stage_a/oof read; seeds exclude 20261006; no successor. L-75 machine-written write-once
result, sha-matched copy, notes only in sidecar. L-66 in-tree basetemp removed. L-82 launch line dry-run + exit codes
before freeze. L-83 thread env. Nautilus untouched; `_leak_reasons` untouched.

## Confidence Self-Assessment
HIGH: shuffle replay and key-level moved fraction, zero level-0 contribution, the seam, the code pin, fixture meeting
`build_folds` minimums. MEDIUM-HIGH: across-seed t bound calibration, N2 as discriminator, PC flag rate. MEDIUM: per-seed
cost (probe settles it); whether R3/R4 trigger given N3's similarity to N1. `msb.ALPHA_ONE_SIDED` facade export is
assumed; a RED test pins 0.025.
