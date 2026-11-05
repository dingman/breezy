# AUT-4 r4 (final round): merged review (coordinator). prediction-market-reviewer 94, mle-reviewer 91. Final 91; zero CRITICAL or HIGH.
Both reviewers endorse I-1 (forward shadow for nominees only) and the location in I-2. Polish to r5.

- **K1 [pm M1]**: Add `n_min_c`, `alpha_total`, `stations` and the per-predicate MDEs for (b) and (c) to the §5 policy keys, as pinned block values. `compute_nomination_columns` does arithmetic only.
- **K2 [pm M2]**: Define `n_min_one_sided`, `c_min` and `deff` once, in `src/breezy/persistence/autonomy/` (stdlib `NormalDist`). `eval_stats.py` imports them. Add a test that the feasibility-record projections equal the engine-written columns.
- **K3 [pm M3]**: Make an explicit AUT-5 request in §5: `compute_nomination_columns` is called inside the `BEGIN IMMEDIATE` transaction with the named keys. Add a contract test that fails if the columns are written without calling it.
- **K4 [mle 1]**: The 15:25Z `eval_staleness` check requires the newest verdict's `slot_start` date to be today (UTC) for every producer. The engine consumes the newest verdict per (family, kind).
- **K5 [mle 2]**: Set `EVAL_OFFLINE_TIMEOUT_START_S = 6299`, or assert ≤ 7200 − 840. Recompute the replay budget and the "worst end" column.
- **K6 [mle 3]**: NO_INPUT is OFFLINE_CHALLENGER with the champion as subject. The forward-shadow lane writes nothing when there is no nominee. Cover this in `eval_completeness`.
- **K7 [mle 4]**: Set the permutation and bootstrap seed to `SEED XOR int(sha256(subject_sha ‖ slot_date ‖ role)[:8])`. Add a test that a same-slot recompute is bit-identical.
- **K8 [mle 5]**: Add a contract test that every studies unit scheduled before 11:00 ends by 10:45Z (the 09:30 reproducibility rerun), or widen the flock wait.
- **K9 [pm LOW]**: State that `INCONCLUSIVE(fill_rate_underpowered)` at the single look is final by design, or have the look wait for `N_IOC_MIN` inside the window. Pin the Decimal serialization in checklist query (3).
- **K10 [mle 6]**: Re-score, excluding the unmeasurable values.
