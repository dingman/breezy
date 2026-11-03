# LEAK-NULL plan r2 delta (2026-11-03) — WINS over plan_r2.md where they differ

Round-2 verdicts: python-reviewer APPROVE (9/8/8/8/8/8, HIGH); architect REQUEST_CHANGES (one mechanical item, AC4);
prediction-market-reviewer REQUEST_CHANGES (three small items, "with these applied I APPROVE"). No design change; the
coordinator applied the items below and declared HIGH without a round 3.

## Binding changes
D1 (architect, AC4 code pin). `pinned_blobs` are full repo-relative paths: `src/breezy/analysis/leak_null.py`,
`src/breezy/analysis/leak_null_decide.py`, `src/breezy/analysis/multisource_blend_fit.py`, `…_folds.py`, `…_stats.py`,
`…_features.py`, `src/breezy/analysis/multisource_blend.py`, `scripts/analysis/leak_null_guards.py`,
`scripts/analysis/leak_null_study.py`, `scripts/analysis/multisource_blend_skill.py`. Hash with
`git -C ROOT hash-object -- <path>` and compare to `git -C ROOT rev-parse <code_sha>:<path>`. `check_code_pin` ALSO asserts
for every pinned module that is loaded (`sys.modules`) that `Path(module.__file__).resolve() == (ROOT / path).resolve()`;
mismatch → Refusal (guards against the editable install resolving `src/` to the other tree). New test:
`code_pin_refuses_module_loaded_outside_repo`. The run is launched from the tree whose HEAD carries `code_sha`
(primary tree on `feat/data-capture-and-risk` after merge) with `PYTHONPATH=<that tree>/src:<that tree>`; the sidecar
lists the helper modules deliberately outside the pin (`multisource_blend_pin_guards`, `_sidecar`, `_lag_arm`,
`_inputs_*`, `prereg_precommit_check`, `memory_cap`) as non-score-affecting.

D2 (PM, AC8 R2). R2 DISCHARGED_FLUKE additionally requires `n_completed_N1 == 20`; R2 uses completed-seed bounds only.
Prereg `decision_rule` text carries this.

D3 (PM, AC12 F13 floor). `floor` is not a code constant: `decide_acceptance` computes `minimum_effect_floor =
floor_multiple × sd(M0 fold CRPS)` with `floor_multiple = 0.25` pinned in F13_prereg_blend_v1.json:59. The coordinator
transcribes `floor` from J3's recorded acceptance report (`j3/result.json` → the acceptance `floor` field) into
`f13_record` before freeze, with `source` naming the exact file and field and the file's sha256; likewise `m0p_vs_m3_mean`
and `m0p_vs_m3_lb` are transcribed from the J3 report's real (unshuffled) M0prime−M3 fields, not from the sidecar prose.
The driver never opens J3 artefacts. If `floor` cannot be sourced, `f13_record.floor = null`, the validator still freezes,
AC12 PASS iff `adj_lb > 0` with `floor_check: "unavailable"`, and R4 is then unreachable (acceptable: weakest discharge).

D4 (PM, AC11 positive control). The PC record logs `L_PC`, `M_PC`, per-seed means, and `plant_mask_rate` = fraction of
planted rows where `rem_max_f > obs` (the `lamp_input_f = max(obs, rem_max_f)` pass-through rate). The sidecar reports
`M_PC` as a "should be large" sanity figure. No change to the flag rule (`L_PC > 0 and M_PC ≥ 0.005`).

## Authoring-brief items (python, non-blocking, adopted)
P1. `train_set_rederivation_matches_out_of_fold_scores` patches `breezy.analysis.multisource_blend_folds.fit_blend`
(folds.py:25 imports it by name); signature `(train, level=, settings=)`.
P2. e2e designs use K=3 and `pc_k=3` (t=4.30 at df=2), never K=2; `across_seed_bound` handles n=1 (`statistics.stdev`
raises) by returning `sd=0, L=M` with a trace note, and n=0 by raising a Refusal.
P3. `apply_address_space_cap` is imported from `breezy.analysis.memory_cap`, not via skill.
P4. Line budgets are soft (800-line ceiling binds); split `decide()` into `_invalid_reasons(...)` and `_verdict(...)`.
P5. N3 permutes `pfm_mu_f`/`mos_mu_f` only among non-None values; None positions unchanged (presence test).
P6. `fold_disjointness_flags_planted_overlap` corrupts the plan (moves a held day into `train_days`) so (a) is non-vacuous.
P7. Typing: `Mapping[str, tuple[SeedSummary, ...]]` on `decide`; `SeedSummary` frozen with `slots=True`, tuple day_values.

## Architect non-blocking, adopted
A1. Probe projection "largest-train fold × n_folds" is a conservative overestimate — recorded in `probe_record`.
A2. Run from the tree that owns `code_sha` (see D1); never switch the primary tree's branch during the run.
