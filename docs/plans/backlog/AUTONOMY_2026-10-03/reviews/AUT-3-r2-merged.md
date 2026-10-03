# AUT-3 r2: merged review (coordinator). mle-reviewer 83, prediction-market-reviewer 82. Final 82, NOT READY.

**Coordinator ruling on X22 reachability.** X22 proves that own outcomes are **consumed**; it does not prove edge. Its threshold is therefore
**functional**: the candidate must change at least `MIN_GATE_DECISIONS_CHANGED` (proposed 1) probe gate decisions, comparing the
envelope `p_lower`/`p_upper` against `ask+fee` on the probe set, relative to the parent. It is NOT a statistical-significance bar. That keeps
score 3 reachable and rules out a vacuous pass. Power, MDE and edge belong to AUT-4. WP0 simulates the probability of reaching the
functional threshold at n_eff 30, 60 and 120, and that sets N0. If the simulation shows the threshold is unreachable before 2027-01-25,
the plan says so explicitly and gives the earliest n_eff and date.

## HIGH
- **S1 [mle N3, pm N1]: rebase on ARCH Rev 5** (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev5.md`, sha 5d2b75fa…) **and** the coordinator α decision `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ALPHA-decision.md`.
  - Stop at K_max MINTs per window and record `NO_CHANGE(k_max_reached)`, which counts toward the streak.
  - k_life never resets.
  - Re-point `test_past_kmax_still_writes_and_records`.
  - Delete C-1, C-3 and C-4 as open items (resolved: AUT-2 pins the bought leg; ARCH chose the mint limit; the README is amended).
- **S2 [mle N1]: the envelope is relative to the parent.** Fit `rung_recalibration` only when the parent recalibration is `none`; otherwise return `NOT_FITTABLE(parent_recalibrated)`. Alternatively, carry `envelope_parent_shift` and have the loader envelope against both the base and the parent. Add `test_candidate_never_adds_takes_vs_recalibrated_champion`.
- **S3 [pm N2]: measure gate inputs, not p_hat.**
  - Compute `gate_probe_max_delta` over the envelope bounds, and count gate decisions changed versus the parent.
  - Apply this to X22, `functional_delta` and WP9, per the ruling above. Below threshold the result is `NOT_FITTABLE(gate_noop)`.
- **S4 [mle N2, pm N8]: power and reachability.** Add WP0 (x), a seeded simulation per the ruling above. Set N0 and the thresholds in the ruling from it, and state the fallback ETA honestly.

## MEDIUM
- **S5 [mle N4, pm N3]: snapshot.** Store per-draw partitions (a `label_draw_partitions` or probe segment, or snapshot the forecast Percentiles and EMOS draws). Compute every delta with the live statistic (the mean of g over draws, then the percentile). Fix the summation order so `P_REPRO_ABS_TOL = 1e-12` is meaningful.
- **S6 [mle N5]: progress hook.** Add a keyword-only `progress` callback to `fit_calibration`, `select_kappa_by_lovo_crps` and `bootstrap_emos_draws`, with a bit-identity test across callers. Correct the "REUSE unchanged" claim.
- **S7 [pm N4]**: Add a `selection_population` field. State that c is conditional on that population (filled entries, selection on `p_lower` and the ask, with IOC misses AMBIGUOUS).
- **S8 [pm N5]**: Scope "only removes takes" to per-(rung, side) gating. Disclose the interaction with the daily budget and the AMBIGUOUS latch.
- **S9 [pm N6]**: Add a `label_from_other_gate` exclusion for labels decided under a promoted recalibration, or justify keeping them.

## LOW
- **S10 [pm N7]**: Fix the citation paths to `src/breezy/strategy/forecast_quantile_ladder/…`.
- **S11 [mle N6]**: The ablation is the none-recalibration bytes.
