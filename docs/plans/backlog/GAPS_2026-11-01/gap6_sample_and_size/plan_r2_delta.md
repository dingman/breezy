# GAP-6 plan r2 — delta over r1 (architect + prediction-market re-reviews 2026-11-01: REVISE)

Applies on top of `plan_r1.md`; where they differ the delta wins. Status: r2 — confirmation by both reviewers pending.

## R2-1 (PM HIGH) S0 observations are tail-band only
§4 "S0 observation": an observation exists only where NO ask = 1 − `yes_bid.close` (Decimal) lies in [0.97, 0.99] inclusive; every other rung-hour is counted (`non_tail_rows`) and excluded. The pre cells therefore average excess over the tail objective only. New test `test_s0_only_tail_band_observations` at bid 0.0300, 0.0100 (in), 0.0099, 0.0350 (out). Candle timestamp convention is stated in §4: a candle stamped `end_period_ts` covers (end−1h, end]; the reference-hour observation uses the candle whose END ≤ the reference hour, so the look-ahead assertion `ref < observation-window start` is exact.

## R2-2 (A-1 HIGH) why S0 is not a flag on `k1_kalshi_prior.py`, and what it reuses
`k1_kalshi_prior.py` fetches and caches ONE candle per market — the first D-1 hour — and reads only `yes_ask` (`:971`, docstring `:1-98`). S0 needs `yes_bid` at the D 10:00 LST and D 17:00 LST reference hours (and D-1 18:00 for LOW), i.e. a per-market hourly RANGE fetch. A flag on k1 would change the fetch shape and the cache schema, not only the output, so default byte-identity (the GAP-3 precedent) cannot be kept; this is the concrete reason the §8 D-2 exception covers `s0`. Consequences:
- "read the 5 shared series cache-first" is DELETED; the k1 cache cannot serve the reference hours. S0 fetches ranges for all 48 series; the shared 5 are reported separately as before.
- S0 imports K1's statistic objects — `break_even_probability`, `wilson_interval`, `summarize_stratum` — and adds `test_s0_uses_k1_statistics_same_objects` asserting identity (`is`) with the K1 module's attributes, mirroring `k1_kalshi_prior.py:130-148`. The day-block bootstrap reuses the existing cluster-bootstrap helper already used by the scan family; no new statistic is authored.
- `k1_kalshi_prior.py` stays byte-unchanged.

## R2-3 (A-2 LOW) wrapper retry arithmetic and per-market exits
`max_retries=3` yields sleeps 0.25 s → 0.5 s (corrected from "0.25→1 s"). `get_json` re-raises 404 (`:923-924`) and exhausted `URLError`/`TimeoutError` (`:932-934`); the wrapper maps each to "market missing" and continues; the 5-consecutive-misses INCOMPLETE abort covers them. Test `test_wrapper_404_and_urlerror_mark_market_missing`.

## R2-4 (A-3 LOW) governance
The S1 B-8 successor ruling also answers K-2a open question P4 (`:211`): new-station price history < 07-01 becomes SEARCH-spent by S0, consistent with the comparator corpus at K-2a `:116`.

## R2-5 (PM LOW) the δ=0.02 / σ=0.14 label is restated as "lenient bound (σ at 0.97 would be 0.17; gross edge ≤ 3¢)"; no numeric change.

## R2-6 (architect r2 confirmation, two LOW wording fixes; PM r2: APPROVE)
- R2-2 bootstrap: "reuses the existing cluster-bootstrap helper already used by the scan family" is REPLACED by "reuses `breezy.analysis.stats.scoring_core.bootstrap_cluster_draws` (`:216`), with 2000 resamples and a frozen seed passed in; if that helper does not fit, the plan says so and no new bootstrap is written." The identity test also covers this helper (PM build note).
- R2-2 identity test: the `is` check targets `k1_cheap_open_settlement`, the module that owns `break_even_probability`, `wilson_interval`, `summarize_stratum`; S0 imports them from there, as `k1_kalshi_prior.py:134-148` does. `summarize_stratum` is called with θ=0 explicitly (PM build note).
- R2-3: 0.25→0.5 s is the 429/5xx ladder; the transport ladder is 1→2 s (`:906, :935-936`).
