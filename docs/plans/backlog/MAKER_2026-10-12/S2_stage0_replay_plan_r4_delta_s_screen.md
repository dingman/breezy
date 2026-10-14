# S2 plan r4 delta (S-5 screen): a repeat-day leak test and an affine time projection

Status: PROPOSED for blind review (2026-10-14). Touches only the `--bench` screen arithmetic and one extra bench row. `S5_MAX_SECONDS` (6 h), `RSS_ABORT_BYTES` (4 GiB), the in-run per-pass RSS abort and the 4 GiB unit cap are unchanged and remain the real backstop. Plan text honoured (r3/r4): "linear extrapolation to the set size is a screen, not a proof; S-5 fires if the projection exceeds 4 GiB or 6 h".

## Observed (bench 4, code d563e702, 4 GiB unit cap)
| Row | end-of-row RSS | process peak | `rss_peak_delta` |
|---|---|---|---|
| SFO 2026-10-03 | 1.448 GB | 1.902 GB | 1.191 GB |
| SFO 2026-10-04 | 1.940 GB | 2.838 GB | 0.936 GB |
| MDW 2026-10-09 | 2.125 GB | 2.838 GB | 0 |
| MDW 2026-10-11 | 2.100 GB | 2.838 GB | 0 |

## Memory: why the old formula is unpassable
`peak + mean(rss_peak_delta) * (88 - 4)` = 2.838 + 0.532 * 84 = 47.5 GB. `ru_maxrss` is a ratchet: rows 1-2 raise the high-water mark once, later rows add 0, so the mean is warm-up spread over the rows, not a growth rate. A slope of end-of-row RSS over run order is also confounded (a heavy day landing early reads as growth: 9.6 GB here).

## Memory: new screen (`maker_stage0_bench_screen.py`)
The bench replays its heaviest station-day a SECOND time as the final row (N -> N+1 rows; `repeat_of_first: true` in `progress.jsonl` / `bench.json`, excluded from every time figure). A leak is growth that persists when the same work is repeated:
`leak_rate = max(0, rss_end(repeat) - rss_end(first replay)) / (rows between + 1)`; `projected_peak = max(peak_rss over rows) + leak_rate * remaining station-days`. Without a repeat row the observed peak alone is projected. `rss_slope_bytes_per_row` (rows after the first 2) is reported with `n_fit_rows` as a diagnostic only; it does not decide `s5_exceeded`. Recorded: `leak_rate_bytes_per_row`.

## Time projection
Bench rows are the heaviest days by catalog bytes, so `mean_s * n` (kept as `projected_total_s_by_count`) charges every remaining day at a heavy-day cost. `projected_total_s = max(proportional, affine)`:
- proportional = `(sum elapsed_s / sum bench bytes) * sum bytes of all replayable days` (falls back to by-count when a weight is 0 or sums are degenerate);
- affine, with >= 4 non-repeat rows: least squares `elapsed = a + b * bytes`, projected `a * n_days + b * total_bytes`; used only when `a >= 0` and `b >= 0` (`n_time_fit_rows` records the rows used, 0 otherwise).
`by_count_exceeds_cap` is true when the by-count figure alone exceeds `S5_MAX_SECONDS`, so the reviewer sees what the weighting changed. `s5_exceeded` = projected time > cap or projected peak > `RSS_ABORT_BYTES`. The procedure's `+ 2 x T_FP` term is unchanged.

## Caveats (verbatim)
- the memory screen can false-pass a masked leak only if the leak does not show on a repeated identical day.
- by-weight is optimistic for fixed per-day costs; the affine fit addresses that.
- It is a screen, not a proof. The repeat row adds one more read + simulate of the heaviest day to the bench wall time (size `RuntimeMaxSec` accordingly).

## Tests
`tests/unit/test_maker_stage0_bench_screen.py`: flat repeat (+30 MB) not exceeded; repeat +2 GB exceeded over 88 rows; no repeat row -> peak only; slope never decides S-5; repeat row excluded from time; equal weights = by-count; 4x weights = 1/4; degenerate weights fall back; affine above proportional with a fixed per-day cost; proportional wins when larger; negative a or b -> proportional; < 4 rows -> proportional; `by_count_exceeds_cap`; `bench.json` fields. Driver test expects the extra flagged row.
