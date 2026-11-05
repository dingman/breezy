# STRAT-DESIGN r2 — pre-registration of runs 1 and 2 (2026-10-31)

Frozen before either run. Later cards (A, LOW, C, B, and D's bid test) are specified in
`design_r2.md` and are not started by this note. No budget, no per-position size, no
live order. `allow_short` stays false.

sha256 of `design_r2.md`: PENDING — the coordinator fills this line with the 64-hex
digest of the committed file. Do not start run 1 while it still says PENDING.

Multiplicity. Run 1 is 48 station-sides (24 × HIGH/LOW). Bonferroni α = 0.05/48.
Run 2 is one coverage fraction. It does not also compute a bid median.

## Run 1 — Card E

Mechanism, the only one: Kalshi public `expiration_value` integer °F minus the IEM CLI
calendar-day extremum (tmax HIGH, tmin LOW). Amendments and voids are mismatches.
Hourly-max, DST, and amendment-rule cuts are not tested.

Stations: the 24 CLI ids and the HIGH/LOW series in
`docs/evidence/venue/kalshi/KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md`
lines 17–40. A missing series is missing, not replaced. Do not pool stations.

Window: 2026-07-05..2026-10-30 (118 climate days). Halves, calendar order:
2026-07-05..2026-09-01 and 2026-09-02..2026-10-30 (59 and 59). A day missing either
label is missing, not a match.

PASS: some station-side has ≥ 3 mismatches in each half, and mean (Kalshi − CLI) has
the same sign in both. H0 = true mismatch rate 1%. Bin(59, 0.01): P(X ≥ 2) = 0.118
and both-halves same sign ≈ 0.007 (family-wise ≈ 0.28 at m = 48). P(X ≥ 3) = 0.0215;
both halves × ½ ≈ 2.3×10⁻⁴; family-wise ≈ 0.011. k = 3 is the smallest integer with
per-test probability ≤ 0.05/48. **P(PASS under H0) ≈ 0.011.**

KILL: every station-side has fewer than 2 mismatches in the 118 days, or every
mismatch is an amendment or a void. A side with n < 118 is INCONCLUSIVE, not a zero.

Power, not a reason to change k: at a true 2% rate P(both halves ≥ 3) ≈ 0.013; at 5%
≈ 0.33. The single-test n = 118 (6.19 × 0.05 × 0.95 / 0.05²) does not carry over.
Prize if a PASS is later sized, q unset: 137 × 0.02 = $2.74, and $1.93 after 84/119
on a PM.us leg only. $6.85 is 137 × 0.05, the alternative, not the floor. Kalshi fees
absent. No own-order exclusion (no PM.us book).

Entry: **NEW EVALUATOR, not in the tree.** No existing script and no flag. Do not call
`k1_kalshi_prior.py`. The evaluator, once built, takes this file as its only threshold
source and writes only the artefact below. No `--truth`, no catalog, no auth.

Artefact: `docs/evidence/STRAT_DESIGN_2026-10-31/card_e_cli_vs_twc.md`

## Run 2 — Card D, G0 only

Does not start in the same process as run 1. Does not start if run 1's PASS handed
the operator the size question (`design_r2.md` §5).

Window: 2026-09-21..2026-10-30. Hour: 10:00–11:00 LST, except where 10:00 LST is
17:00 UTC (PDT), then 11:00–12:00 LST. Not 17:00–18:00 UTC.

Denominator: station-days with a Depth10 frame in that hour, after dropping any
instrument in the §4.0 set of `design_r2.md` (trial-record instrument ids under
REGISTERED `deploy/families/pm_us_*.json` prefixes, taker fills included, from that
instrument's first own order). If that set cannot be built, REFUSE. Do not use a date
cut. The artefact lists instrument ids and a count, never order ids.

PASS: ≥ 90% of that denominator have a METAR max row covering the hour. Coverage only.
**Not an edge rate.** KILL: none. Below 90% is INCONCLUSIVE and the bid test does not run.

The bid test (YES bid, median ≥ 0.10 / ≤ 0.03) is frozen in `design_r2.md` §4.D and is
not computed by this invocation.

Entry: **NEW EVALUATOR, not in the tree**, one exception, flag `--g0-only`.
`sum_ask_row` and `queue_sizes` are the wrong functions (a subset is not a partition;
`queue_sizes` takes no METAR). No `settlement_truth`. No second flag.

Artefact: `docs/evidence/STRAT_DESIGN_2026-10-31/card_d_g0.md`
