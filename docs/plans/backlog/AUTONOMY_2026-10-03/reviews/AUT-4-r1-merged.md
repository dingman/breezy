# AUT-4 r1: merged review (coordinator). mle-reviewer 81, prediction-market-reviewer 84. Final 81, NOT READY.
Duplicates merged. No contradictions.

## HIGH
- **E1 [pm1]: no reset of k across epochs.** Keep Σα ≤ α_total per lineage for its whole life, or use a declared Bonferroni split over a fixed maximum number of epochs. This must be consistent with the registry `alpha_spent` cross-check.
- **E2 [pm2, mle14]: the live proof cannot rest on optional rulings.**
  - Filing R-B (the FQ sequential prereg) and the holdout ruling are hard prerequisites for the proof window. Otherwise FQ is declared score 2.
  - Add a fixture or drill candidate path so FORWARD_SHADOW and OFFLINE verdicts flow while `promote_enabled=false`.
  - Recompute the proof ETA.
- **E3 [pm3]: slippage.**
  - Measure the live IOC fill rate (every IOC miss is AMBIGUOUS), and haircut EV by the fill probability.
  - Widen the EV lower bound by the proxy's standard error.
  - Refuse `ev_net` when there are fewer than N proxy fills.
  - Disclose the survivorship bias.
- **E4 [mle1]: schedule.** `eval_live` gets its own lock or runs before offline. Offline `RuntimeMaxSec` ≤ 3 h, with margin before the 15:30 engine run. Add `test_units_do_not_contend_on_flock`. Align with ARCH W1 (6-hourly ATTEST) and W8.
- **E5 [mle2]: validity jitter.** Anchor validity to the scheduled cycle, or bound the worst-case jitter with a test, under ARCH `MAX_VERDICT_VALIDITY_H`.
- **E6 [mle3]: verdict schema per kind.**
  - Add a table of required fields per kind: power, MDE, comparator, `alpha_spent`, `prereg_ruling_sha256`.
  - Define the pre-ruling `prereg_ruling_sha256` value and how the engine treats it.
  - Add `test_verdict_v1_schema_complete_per_kind`.
- **E7 [mle4, pm12]: consumability.** Fix the engine's input-journal schema (the `cause_verdict_ids` it records) as a cross-AUT contract test that this plan owns, so the live-proof check (f) is concrete.
- **E8 [mle5]: memory.** The cap comes from the WP0 peak RSS, with per-child MemoryMax and a PRESCREEN budget. Show the arithmetic under the 16 G studies cap. Hard-fail if the peak exceeds the share.

## MEDIUM
- **E9 [mle8, pm4]: bootstrap at α_K.** Use a sign-flip permutation test, or B ≥ 200/α_K with a minimum cluster count.
- **E10 [pm5]**: Inflate n_min by the measured intra-date design effect (stations are correlated). An `INCONCLUSIVE(cluster_sensitivity)` at the single look is final.
- **E11 [pm6]: R-C.** Use a relative calibration conjunct (not worse than the champion; under-confidence reduced), never an absolute leg loosened after the failure was seen.
- **E12 [pm7]: holdout.** Adopt the coordinator decision in reviews/HOLDOUT-decision.md, which replaces your R-A. Disclose the contamination and downgrade S2 to descriptive.
- **E13 [mle10, pm8]**: Add `assert_forecast_available_at` (`issued_at ≤ eval_ns`) and `forecast_input_sha256` parity, with a RED test.
- **E14 [pm9]**: `feasibility_consistency` tests the ETA at the assigned k.
- **E15 [pm10]**: Derive the fill rate from the exec store (WP0). State the pre-KILL probability of a terminal verdict.
- **E16 [pm11]**: Pre-commit the R-B design parameters to a hash before anyone reads the prefix PnL. Exclude the prefix explicitly.
- **E17 [mle6]**: Report the excluded-day fraction per station, INCONCLUSIVE above a threshold. Assign the replay-daily MIA timeout fix to a WP.
- **E18 [mle7]**: Predicate (b) gets its α or confidence level and a PASS rule for an n mismatch.
- **E19 [mle9]**: Use an out-of-fold σ_d.
- **E20 [mle11]**: `verdict_id` excludes the timestamp. Add `test_producer_recompute_identical_modulo_time`. Put dataset and tape snapshot shas in `inputs`.
- **E21 [mle12]**: Add a producer-pin rotation runbook, or narrow the import closure (consistent with ARCH Y17/Z9: pins are append-only).
- **E22 [mle13]**: Add evaluator self-monitoring detectors: excluded fraction, n=0 for N days, runtime and RSS creep, pin mismatch.

## ARCH deltas to absorb
reviews/ARCH-r4-merged.md W1 (ATTEST every 6 h) and W7 (forward window, and either `ERROR(k_exceeded)` or a mint limit; coordinate this with AUT-3 by choosing the mint limit). reviews/HOLDOUT-decision.md.
