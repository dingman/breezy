# LEAK-NULL plan r1 (2026-11-03) — multi-seed outcome-blind null study of F13's shuffled-label control (M3 vs M0prime)

Purpose: discharge or confirm `f13_verdict=HELD_LEAK_AUDIT` from run `gap1_j3_2026-11-02` without a second look at the
GAP-1 primary (L-34). Planner: planner agent; peer review: architect + python-reviewer + prediction-market-reviewer.

## Code findings that fix the premises
1. The current shuffle (`multisource_blend_folds.py:396-415`, called at `multisource_blend_skill.py:538-542`) permutes one
   label per (version, station, climate_day) across stations/days/seasons/segments/folds within the version; one draw,
   seed = F13 `pins.bootstrap_seed` 20261006; both arms (levels (0,3), no champion) refit inside the same fold plan.
   It cannot detect a feature that carries the label (feature leakage is covered by `assert_row_leakage_free` and the
   +60 min lag twin; NBP availability is not — KNYC-DROP/NBP pin remain open).
2. Rows where M3 sits at level 0 contribute exactly zero (`multisource_blend_fit.py:189-195`, deterministic L-BFGS-B), so
   all of the shuffled delta comes from D0 rows at prefix ≥ 1 (every D-1 row is LAMP-missing).
3. Benign mechanism is exact: penalty `lam*n*(Σw−1)²` (`multisource_blend_fit.py:156`, λ=1). On noise labels the best fit
   is w=0, forbidden by the penalty; M0prime's D0 cell has 2 regressors (q50, obs), M3's `(3,True)` cell has 5, so M3 has
   more ways to satisfy Σw≈1 while flattening μ → "skill in noise". Fold/scoring path never changes with λ.
4. B=5000 stationary bootstrap costs seconds; J3's 18m50s is fits (8 `fit_blend` + 2 `fit_calibration` per fold).

## Trade-offs — nulls
| Option | Verdict | Why |
|---|---|---|
| N1 within-version shuffle, K seeds | RUN | Is J3's lb>0 typical or a one-seed fluke; pairing base for N2/N3 |
| station×month permutation / circular shift | REJECT | Keeps more structure; λ-flattening still works; cannot separate benign from leak |
| N2 same permutations, `weight_sum_lambda=0` | RUN (discriminator) | Only the benign channel removed; benign predicts lb ≤ 0, a pipeline leak persists |
| N3 same permutations + M3's LAMP/PFM/MOS each permuted within (version, horizon) among present rows | RUN (sufficiency) | Noise regressors with realistic marginals; no fit-code change |

Reuse: `multisource_blend_skill.py` has no seed/null-only/λ flag; a thin driver calls `prepare_run` (load + fold plan,
nothing fitted) and `msb.out_of_fold_scores` directly. Compute: ≤ 6/8 × 1130 s ≈ 14 min per seed upper bound; K=20 →
≤ ~4.7 h; the real figure comes from the L-82 timing probe before the freeze.

## Acceptance Criteria
1. Driver writes only under `/mnt/storage/breezy/derived/gap1_source_resolution/leak_null_<YYYY-MM-DD>/`; refuses any path
   with a `gap1_j3_*` component, any path under `~/.local/share/breezy` (raw and `.resolve()`d), and a basename not
   matching `^leak_null_\d{4}-\d{2}-\d{2}$`.
2. No `out_of_fold_scores` call ever receives original labels; every scored row set has ≥ `min_permuted_fraction` (0.5)
   keys relabelled; output schema is an allowlist with no unpermuted M3−M0prime statistic.
3. Inputs are exactly the prereg-pinned paths, sha256-verified; basenames `result.json`, `murphy.json`, `stage_a.json`,
   `oof_rows.jsonl` are refused.
4. Prereg frozen (`check_frozen_blob` + `check_not_refrozen`); `provenance.json` write-once with prereg digest, code_sha,
   input shas; digest mismatch at start, on resume, or before result write → refusal, no result.
5. Seed list K ≥ 20 distinct ints, excludes 20261006; same seed → byte-identical output (excluding `wall_s`).
6. Per-seed delta uses the J3 estimator: `msb.delta_summary(msb.delta_by_day(scored,"M0prime","M3"), n_boot=5000,
   seed=20261006, mean_block=fixed.mean_block_days)`; positive iff `lb > 0.0` (copied from `_leak_reasons:230`).
7. Invariants (breach → INVALID): rows with `levels["M3"]==0` have |delta| ≤ 1e-9; N3's M0prime CRPS equals N1's row for
   row; prefix_level preserved under scrambling; ≤ 2 failed seeds per null.
8. Decision rule, in order, on this study's numbers only: R0 invariant breach → INVALID (HELD stands); R1 N2 positives
   ≥ 3/20 → LEAK_CONFIRMED (GAP-1 PASS withdrawn to UNRESOLVED-LEAK; #10 held); R2 N1 positives ≤ 2 → DISCHARGED_FLUKE;
   R3 N3 positives ≥ 10 → DISCHARGED_BENIGN_DOF; R4 otherwise → DISCHARGED_PENALTY_MEDIATED (pipeline clean; sufficiency
   not shown — reported caveat). P(R1 | clean null, p=0.025) ≈ 1.4%.
9. J3's `result.json` never edited; DISCHARGED recorded only in a new sidecar + PROGRESS; follow-up NC-FIX (DoF-matched
   negative control) filed; no threshold relaxed.

## Edge cases & NFRs
- N2 non-convergence (`FitNotConvergedError`): catch per seed, record failed + reason, continue; > 2 → INVALID.
- Near-identity permutation refused per seed. N3 cell drop-outs reported per seed (non-gating).
- Restart: per-seed files `open("x")`; resume skips completed files after checking `prereg_sha256`; torn file refused.
- Memory: `--max-memory-gib 3.5`, `MemoryMax=6G`, `LimitNOFILE=524288`, L-83 thread env; never alongside the nightly study.
- Determinism: sub-seeds `int(sha256(f"leak_null:{seed}:{name}").hexdigest()[:16],16)`; no global RNG.
- Persist per-seed day-level delta vectors (~1968 floats); shuffled rows not persisted.

## Architecture & data flow
`PREREG_LEAK_NULL_<date>.json` (frozen) → `scripts/analysis/leak_null_study.py`: guard out dir → verify input shas →
write `provenance.json` → `prepare_run(prereg=F13, features, lag_features, c1_evidence, out_dir=<out>/f13_context)`
(writes only `f13_context/prereg_record.json`, returns ctx) → per seed: `L = null_label_rows(ctx.rows, seed)`;
N1 = oof(L, settings); N2 = oof(L, null_settings(N2)); N3 = oof(scramble_sources(L, seed), settings), levels (0,3),
champion=False; `seed_summary` → `seeds/<null>_<seed>.json` → `decide()` → `leak_null_result.json` (write-once after
digest re-check). Pure logic in `src/breezy/analysis/leak_null.py`; all I/O in the script.

## File-by-file
| Path | | Exact changes |
|---|---|---|
| src/breezy/analysis/leak_null.py | new | Pure, ≤ 250 lines, imports the `breezy.analysis.multisource_blend` facade only. `NULL_IDS=("N1_within_version","N2_penalty_off","N3_scrambled_sources")`; `LeakNullVerdict(StrEnum)` (5 verdicts); `null_label_rows(rows, seed)` = `msb.shuffle_labels` + `permuted_fraction(orig, null)`; `scramble_sources(rows, seed)` permutes `lamp.rem_max_f`/`pfm_mu_f`/`mos_mu_f` within (version, horizon) among present rows via `dataclasses.replace`, touching no label/q50/obs/`*_available_at_ns`; `null_settings(settings, null_id)` (N2 → `replace(weight_sum_lambda=0.0)`); `seed_summary(scored, *, n_boot, boot_seed, mean_block)` → mean, lb, n_days, by_horizon, by M3 effective level, day_values, level0_max_abs; `decide(summaries, thresholds)` → (verdict, trace) |
| scripts/analysis/leak_null_study.py | new | Thin driver ≤ 300 lines. argparse `--prereg --out-dir --max-memory-gib --timing-probe-folds N`. `load_leak_prereg` mirrors `gap1_oof_murphy.load_prereg`/`_digest`; `guard_out_dir`; `verify_inputs` (sha256 + forbidden basenames); `record_provenance` (write-once); seed loop with resume; `assemble_result` (allowlist keys); `apply_address_space_cap`. Timing probe: UNFROZEN allowed only in this mode; scores N1 on first N folds with a probe seed outside the list; prints only `folds=<n> wall_s=<x> projected_seed_s=<y>`; writes nothing, emits no statistic. Exit 2 on `Refusal` |
| docs/plans/backlog/GAPS_2026-11-01/gap1_source_resolution/PREREG_LEAK_NULL_<date>.json | new | `frozen_sha`; `inputs` (F13 prereg path + content_sha256 1e9db7ac… + frozen_sha 205fd542… copied from GAP-1 PREREG :178-182; f.jsonl/fl.jsonl shas from `build.json.output_sha256`; c1 path + sha 792ff2a8…); `nulls`; `seeds` (20); `bootstrap`; `thresholds` (`lb_gt:0.0`, `source:"multisource_blend_stats.py:230"`, `leak_count_min:3`, `fluke_count_max:2`, `dof_count_min:10`, `invariant_tol:1e-9`, `max_failed_seeds:2`, `min_permuted_fraction:0.5`); `decision_rule` R0–R4; `envelope` (from probe); `forbidden_inputs`; `out_root`; `probe_record` |
| tests/unit/test_leak_null.py | new | pure-function tests (below) |
| tests/unit/test_leak_null_study.py | new | driver contract tests (below) |
| docs/evidence/LEAK_NULL_<date>.md + committed result copy | new, after run | sidecar + byte-identical `leak_null_result.json` (L-75) |
| docs/core/PROGRESS.md | modified, after run | disposition of HELD_LEAK_AUDIT and #10 unlock state |
No change to `multisource_blend_*.py`, `multisource_blend_skill.py`, or any J3 artefact.

## Test strategy (RED first; synthetic fixture: 2 versions, 2 stations, ~140 days; D0 rows with LAMP/PFM/MOS present plus
prefix-0 rows; D-1 LAMP-missing; reuse `tests/unit/test_gap1_oof_murphy.py` row builders if present)
test_leak_null.py: null_label_rows_equals_shuffle_labels_same_seed; null_label_rows_deterministic_and_seed_sensitive;
permuted_fraction_below_min_is_refused; scramble_preserves_prefix_level_and_presence;
scramble_never_touches_label_q50_obs_or_timestamps; scramble_permutes_only_within_version_horizon;
null_settings_n2_only_changes_lambda; level0_rows_have_exactly_zero_delta; n3_m0prime_equals_n1_m0prime;
seed_summary_lb_equals_msb_delta_summary; lb_exactly_zero_is_not_positive; decide_leak_precedes_benign; decide_fluke /
_benign_dof / _penalty_mediated; decide_invalid_on_invariant_breach / _on_three_failed_seeds;
threshold_other_than_zero_is_refused.
test_leak_null_study.py: refuses_out_dir_inside_gap1_j3_dir (direct, symlink, `..`); refuses_live_data_root_raw_and_resolved;
refuses_out_dir_name_not_leak_null_date; never_scores_unpermuted_labels (spy on `msb.out_of_fold_scores`);
result_never_contains_primary_statistic (allowlist); prereg_digest_mismatch_refuses; prereg_changed_mid_run_writes_no_result;
input_sha_mismatch_refuses; forbidden_input_basenames_refused; seed_list_excludes_f13_seed_and_k_ge_20;
seed_determinism_byte_identical; seed_files_write_once_and_resume_skips_done; unfrozen_refused_outside_timing_probe;
timing_probe_prints_no_statistic_writes_nothing; end_to_end_fixture_emits_verdict.
Gate: `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/leak_null` then `rm -rf`; `lint-imports`;
ruff + mypy on touched files only.

## Execution order
1. Peer review (architect ‖ python-reviewer ‖ prediction-market-reviewer). 2. Codex authors in the worktree
(`/home/jon/breezy-leak-null`, PYTHONPATH to the worktree src, hard invariants in brief, ruff-format touched files only):
RED tests → `leak_null.py` → driver. 3. Claude tdd-guide re-runs the gate on the artifact, reads the diff, commits by path,
merges. 4. L-82 dry-run from the primary tree: `--help` (0), refusal vs a `gap1_j3_*` out dir (2), `--timing-probe-folds 3`
under the systemd envelope; record exit codes + `projected_seed_s` in the prereg. 5. `RuntimeMaxSec = max(14400,
1.5 × 20 × projected_seed_s)`; freeze (commit + stamp). 6. Launch under `systemd-run --user` (MemoryMax=6G, thread env,
LimitNOFILE=524288) with a delegated stall watch. 7. Read verdict → sidecar, sha-matched copy, PROGRESS, lesson if diverged.

## Risk register
Lenient R4 → peer review may tighten before freeze. N2 at λ=0 may converge poorly → failures counted, >2 = INVALID.
Seeds share features → count rule approximate (stated). Compute overrun → probe sets envelope, widen-only (L-12).
`prepare_run` writes `f13_context/prereg_record.json` → confined to out dir. `check_not_refrozen` needs git history → run
from primary tree. Codex may reformat whole dirs → touched files only, diff reviewed. Cannot detect a label-carrying feature
by construction → sidecar states it.

## LESSONS compliance
L-12 thresholds copied never relaxed, envelope widen-only; L-34 not a second look (no result/murphy/stage_a read, never
scores real labels, seeds exclude 20261006); L-75 machine-written write-once results, sha-matched copy, notes in sidecar;
L-66 in-tree basetemp removed after; L-82 launch line dry-run + exit codes recorded before freeze; L-83 thread env.

## Confidence
HIGH on shuffle semantics, zero level-0 contribution, `prepare_run` reuse, negligible bootstrap. MEDIUM-HIGH on N2 as the
discriminator. MEDIUM on per-seed cost (probe) and R3/R4 thresholds (peer review settles).
