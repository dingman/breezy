# LEAK-NULL plan r1 — peer review round 1 (2026-11-03), merged by the coordinator

Verdicts: architect REQUEST_CHANGES; python-reviewer MEDIUM (8/8/7/8/8/7); prediction-market-reviewer REQUEST_CHANGES.
No LESSONS violation found by any reviewer. Module + thin driver (not flags on the J3 script) confirmed as the right shape.
API premises verified: `BlendSettings.weight_sum_lambda` (fit.py:41,50); `levels["M3"]`; `delta_summary(day_values, *,
n_boot, seed, mean_block=7.0)`; `delta_by_day(scored, first, second)`; `shuffle_labels(rows, *, seed)`; `prepare_run(*,
prereg, features, lag_features, c1_evidence, out_dir, anchor_variant=...)` fits nothing, writes only
`<out_dir>/prereg_record.json`; `ctx.fixed` is a dict → `float(ctx.fixed["mean_block_days"])` (skill:560); facade exports
`shuffle_labels, out_of_fold_scores, delta_by_day, delta_summary, merge_scored, FitNotConvergedError, BlendSettings`.

## Blocking (all must be addressed in r2)

B1. **Decision statistic (PM).** Per-seed `lb > 0` counts are miscalibrated: per-day deltas are autocorrelated at fold scale
(one fold's fit covers all its days), so the stationary bootstrap SE is too small and the effective per-seed α exceeds
0.025; "P(R1|clean) ≈ 1.4%" is wrong under dependence and power vs a 0.10-rate leak is ≈ 32%. Change: the gating statistic
per null N is the across-seed mean `M_N` of the per-seed day-mean deltas with one-sided 97.5% t lower bound
`L_N = M_N − 2.093·sd/√20` (19 df). Per-seed lb>0 counts become descriptive only. Bootstrap seed per study seed is derived
by the sha256 sub-seed scheme (never the shared 20261006, which would correlate resample paths); estimator identity does not
require seed identity.

B2. **Decision rule (PM + architect).** Freeze:
- R0 INVALID (HELD stands): any invariant breach (level-0 |delta| > 1e-9; fold-disjointness check B3; N3 M0prime ≠ N1
  M0prime row for row); positive control (B4) not flagged; < 18 completed seeds in any null; prereg digest changed.
  Failed seeds count as non-positive and the denominator stays K.
- R1 LEAK_CONFIRMED: `L_N2 > 0` and `M_N2 ≥ 0.005` → GAP-1 PASS withdrawn to UNRESOLVED-LEAK. If `L_N2 > 0` but
  `M_N2 < 0.005` → HELD_INCONCLUSIVE (no discharge).
- R2 DISCHARGED_FLUKE: `L_N1 ≤ 0` and N1 per-seed positives ≤ 2/20.
- R3 DISCHARGED_BENIGN_DOF: `L_N1 > 0`, `L_N2 ≤ 0`, `M_N2 ≤ 0.25·M_N1`, `L_N3 > 0`, `M_N3 ≥ 0.5·M_N1`.
- R4 DISCHARGED_PENALTY_MEDIATED only if `L_N1 > 0`, `L_N2 ≤ 0`, `M_N2 ≤ 0`, and the bias-adjusted check B5 passes;
  otherwise HELD.
- Anything else HELD. Every discharge conditional on R0 passing. K == 20 exactly (not ≥), no successor study on
  INVALID/HELD/R4.

B3. **Fold-disjointness invariant (PM).** Permutation nulls cannot see fold/embargo leaks (shuffled labels have no temporal
autocorrelation; common-mode own-day leak through M0prime cancels in the delta). Add a deterministic outcome-blind check on
the `prepare_run` context: for every scored row its key is absent from its fold's training and recalibration sets, and
training days lie outside the embargo window around each test day. Breach → R0. The sidecar must state what the nulls
cannot see.

B4. **Positive control (architect + PM).** Before any verdict, plant a known label-carrying regressor in M3 (shuffled label
+ noise into the LAMP slot) and run 5 seeds under N2 settings; the rule must flag it (`L > 0`). Not flagged → R0.
Also a unit/e2e test that a planted leak drives R1.

B5. **Bias-adjusted check (PM).** Pre-register: F13's published real delta (0.165, CRPS M0prime vs M3) minus `M_N1` must
still clear F13's own acceptance floor (`decide_acceptance`); report it. Coordinator note: this is F13's CRPS statistic, not
GAP-1's Brier dRES — state explicitly that it adjusts F13's verdict and that GAP-1's PASS is withdrawn only via R1; do not
apply a CRPS bias to the 0.0152 RES threshold. Uses numbers already on record (L-34 safe).

B6. **Timing probe (architect).** `prepare_run` always writes `prereg_record.json`, so "writes nothing" is false and
`guard_out_dir` would refuse a scratch dir: the probe uses a fresh tempdir in the agent scratchpad OUTSIDE `out_root`,
deleted after; test renamed `timing_probe_writes_nothing_under_out_root`. The probe must time one fold of EACH of
N1/N2/N3 (N2 at λ=0 may iterate more) and report `projected_seed_s` as their sum; envelope then widen-only (L-12).

B7. **Code pin (architect).** Prereg carries `code_sha`; the driver refuses unless that commit is HEAD or an ancestor
(reuse the ancestry check pattern in gap1_oof_murphy.py:520-530) AND the `leak_null*.py` blobs at HEAD equal those at
`code_sha` (HEAD moves during a ~5 h run under concurrent agents).

B8. **Testability (python + architect).** Driver core = `run_study(ctx, prereg_leak, out)`; `prepare_run` called only in
`main` through ONE module-level seam the e2e test monkeypatches with a synthetic `RunContext`; a separate test covers the
real freeze path with the tmp-git `_git` fixture from tests/unit/test_multisource_blend_skill.py:86. The driver calls
`msb.out_of_fold_scores(...)` as an attribute lookup at call time (never `from … import`) so the spy works; the spy also
asserts `skill.run_stage_a/run_stage_b/_score` are never called and that ≥ 50% of `cli_tmax_f` KEYS (by key, not value —
integer-°F ties) differ from the originals.

B9. **Fixture (python + architect).** Reuse the `FeatureRow` builders in tests/unit/test_multisource_blend.py (and
test_multisource_blend_featbuild_review_fixes.py), NOT the ScoredRow dict builders in test_gap1_oof_murphy.py. `Percentiles`
needs positive sd; `LampFeature` has 7 fields. The fixture must satisfy `build_folds` minimums (block_days 28,
min_train_days, min_blocks) → ≥ 2 folds per version; size it accordingly (≈ 2 seeds, small K in the gate; test K==20 via the
validator, not by running 20).

B10. **scramble_sources (python).** `lamp` is a nested frozen `LampFeature`: `replace` twice; permute only `rem_max_f`
(keeps `missing=False`, presence and `prefix_level`); `lamp_input_f` = max(obs, rem_max_f) moves automatically — say so;
other LampFeature fields stay with the row (not model inputs); add a test that `_assert_admissible` accepts scrambled rows.

## Non-blocking (adopt if complexity stays flat)
- Frozen dataclasses for thresholds and `SeedSummary`; `NULL_IDS` as StrEnum; `random.Random(subseed)` instances only.
- Scripts import siblings via `sys.path.insert(ROOT)` + `from scripts.analysis import …` (gap1_oof_murphy:65); copy it.
  Editable `breezy` install points at the primary tree → set PYTHONPATH in the gate and pytest for the worktree.
- N2's λ=0 applies to both arms (shared settings) — state in sidecar. Level-0 zero-delta invariant depends on
  `fit_blend` building the `(0, obs)` cell identically at levels 0 and 3 (fit.py:189-195) — note in sidecar.
- Committed result copy goes under `docs/evidence/gap1_source_resolution/`.
- N3 largely duplicates N1 (labels already independent of sources); it tests source–q50 collinearity dependence; judge
  relatively (as R3 now does).
- Freeze ordering: probe values written while UNFROZEN → commit → single stamp commit, both on the run branch after the
  code merge, from the primary tree; never stamp in the worktree then rebase (`check_not_refrozen` allows exactly one
  non-UNFROZEN commit).
