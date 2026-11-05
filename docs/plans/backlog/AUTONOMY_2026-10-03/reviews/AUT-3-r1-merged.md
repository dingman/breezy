# AUT-3 r1: merged review (coordinator). mle-reviewer 75 (2 CRITICAL), prediction-market-reviewer 77. Final 75, NOT READY.
Duplicates merged; the reviewers converge. Note: ARCH-r4-merged.md exists at
/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-r4-merged.md. Use the absolute path.

## CRITICAL / HIGH
- **R1 [mle1, pm3]: X22 must be non-vacuous.**
  - Probe real rung partitions drawn from the training labels' C1 `p_hat`. Apply `apply_probability_recalibration`, including partition renormalisation (`nbp_calibration.py:1647-1662`).
  - Require max |Δp| ≥ a ruling constant `MIN_PROBE_DELTA` (for example 1e-3) and n_eff ≥ `MIN_NEFF_TO_EMIT`. Below either, return `NOT_FITTABLE(underpowered)`, which is not an own-outcome candidate.
  - Add `test_affine_that_is_identity_after_renorm_fails_x22`. WP9 requires the thresholds to be met.
- **R2 [mle2, pm1]: identifiability and selection bias.**
  - Replace the 2-parameter affine fit with a one-parameter logit shift, or with a ridge penalty on the function-space deviation over the probe grid. Fit through `apply_probability_recalibration`, so renormalisation is inside the fit.
  - Add minimum clusters and minimum p-spread support checks, or return `NOT_FITTABLE(unidentified)`.
  - Restrict the applied map to the support of the training p, or gate the distortion of non-traded rungs in the writer.
  - Recast "fewer, smaller positions" as a hypothesis with its mechanism stated.
- **R3 [pm2, mle5]: monotone de-risking only.** Until an AUT-4 PASS, the map may only lower confidence.
  - Require g(p) ≤ p on the grid, and require that the post-renormalisation maximum rung `p_lower` is ≤ the parent's. Enforce both in the writer AND the loader.
  - Clamp the slope or shift sign in the estimator so the writer never refuses an estimator output. Test it.
  - Correct §9: p feeds the gate and sizing; the caps are never read or assigned.
- **R4 [pm4, mle8]: the probability being fitted.**
  - Name the fitted statistic: `p_hat` point estimate versus per-draw then `p_lower`.
  - Test end to end that the map applied per draw yields a `p_lower` consistent with the training definition.
  - Orient labels to the bought leg (NO = 1−p; consistent with AUT-2, which pins `p_at_decision` as bought-leg probability). Exclude exit labels from training. Add RED tests.
- **R5 [mle3]: rebase on ARCH Rev 4 plus reviews/ARCH-r4-merged.md.** Reconcile with `holdout_opens` (at most once per lineage) and with α halving per candidate. Adopt reviews/HOLDOUT-decision.md, which is the coordinator's single holdout ruling and replaces your own freeze text.
- **R6 [mle4, pm5]: cadence and multiplicity.**
  - Mint only when the θ delta against the last C3 exceeds a threshold; otherwise record `NO_CHANGE(below_delta)`. Honour the AUT-4 K_max and mint ceiling (ARCH W7).
  - Add a `MINT_REFUSED_CEILING` case to the proof and WP9.
  - Restate the live proof as "7 consecutive scheduled refit RUNS, each lineage-complete and consumed (minted, NO_CHANGE or NOT_FITTABLE all recorded and consumed by AUT-4)", with at least one minted own-outcome candidate meeting R1.
  - State that the samples are not independent.
- **R7 [mle6]**: Seasonal gap. WP0 measures the effect of training on 05-04..06-30 plus forward days with July–September sealed, and the ruling states whether the gap is accepted.

## MEDIUM
- **R8 [pm6]**: Add a time-blocked own-label holdout (train on days ≤ D−k, score on the last k), recorded in the lineage as advisory.
- **R9 [pm7]**: State in §6 and the ruling that no fresh weather holdout remains for `density_table` after the freeze; forward shadow is the only confirmation left.
- **R10 [pm8]**: Evidence honesty. A recalibration candidate is expected to have no edge. The LOSO Platt prior worsened the mid, and AUT-4 is likely UNDERPOWERED.
- **R11 [mle7]**: WP8 re-runs every leakage assertion from the snapshot bytes. `no_sealed_holdout_rows_in_train` checks the rows that actually enter the fit.
- **R12 [mle8]**: Reproducibility. Pin `OPENBLAS_CORETYPE`, record the CPU model, require a clean tree for producer files, and give the repro unit the same thread and hash-seed environment.
- **R13 [mle9]**: Memory and schedule. WP0 measures per-unit peaks and states which units take which lock. Move repro after the AUT-4 slot. Gate WP7 on the measured peak. Systemd note: `RuntimeMaxSec` does nothing on `Type=oneshot`; use `TimeoutStartSec`.
- **R14 [mle10, pm9]**: Draft a ruling amending the README execution-data clause (no FQ model class consumes execution data), and cite it in §7.

## LOW
- **R15 [mle11]**: The label-bound parent rule stops own-outcome refits after the first promoted recalibration. State this as a known limit, or carry the raw pre-recalibration p in C2 (ARCH feedback P3-3) to remove it.
- **R16 [mle12]**: Measure snapshot disk growth.
