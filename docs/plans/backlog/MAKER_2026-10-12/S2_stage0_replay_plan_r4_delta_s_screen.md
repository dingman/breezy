# S2 plan r4 delta (S-5 memory screen): a leak-growth projection a flat process can pass

Status: PROPOSED for blind review (2026-10-14). Touches only the `--bench` screen arithmetic. `S5_MAX_SECONDS` (6 h), `RSS_ABORT_BYTES` (4 GiB) and the in-run per-pass RSS abort are unchanged. The plan text it must honour (r3/r4): "linear extrapolation to the set size is a screen, not a proof; S-5 fires if the projection exceeds 4 GiB or 6 h".

## Observed (bench 4, code d563e702, 4 GiB unit cap)
| Row | end-of-row RSS | process peak | `rss_peak_delta` |
|---|---|---|---|
| SFO 2026-10-03 | 1.448 GB | 1.902 GB | 1.191 GB |
| SFO 2026-10-04 | 1.940 GB | 2.838 GB | 0.936 GB |
| MDW 2026-10-09 | 2.125 GB | 2.838 GB | 0 |
| MDW 2026-10-11 | 2.100 GB | 2.838 GB | 0 |

## Why the old formula is unpassable
`projected = peak + mean(rss_peak_delta) * (88 - 4)` = 2.838 + 0.532 * 84 = 47.5 GB. `ru_maxrss` is a ratchet: rows 1-2 raise the high-water mark once (allocator warm-up plus the heaviest day), later rows add 0. The mean of a ratchet delta is the warm-up cost spread over the rows, not a growth rate, so the projection scales with the number of rows left. Even a process whose RSS is flat after row 2 projects far above 4 GiB, so `s5_exceeded` could never be false.

## New formula (`scripts/analysis/maker_stage0_bench_screen.py`, `project_bench`)
`projected_peak = max(peak_rss over rows) + slope * (n_replayable - n_rows)`.
- `slope` = least-squares slope of END-OF-ROW `rss_bytes` over run order, fitted on the rows after the first `WARMUP_ROWS = 2`, floored at 0, truncated to whole bytes.
- With fewer than two rows after warm-up no slope can be fitted: the observed peak alone is projected (recorded as slope 0; the screen cannot see a leak there and does not invent one).
- `s5_exceeded = projected_total_s > S5_MAX_SECONDS or projected_peak > RSS_ABORT_BYTES`. `projected_total_s = mean(elapsed_s) * n_replayable` is unchanged. `bench.json` gains `rss_slope_bytes_per_row`; every existing key keeps its meaning.
- Why two warm-up rows, not one: with the observed rows a one-row warm-up fits rows 2-4 (1.94, 2.13, 2.10 GB), slope +0.08 GB/row, projection 9.6 GB, i.e. the row that carries the heaviest day is still read as growth. Rows 1-2 are where the working set is built; the screen measures what happens after.
- Caveat (stated, not hidden): a day heavier than every earlier day that lands after row 2 raises end-of-row RSS legitimately and can read as growth (a false alarm in the safe direction). It is a screen, not a proof.

## Result on the observed rows
Rows after warm-up: 2.125, 2.100 GB, slope -0.025 GB/row floored to 0, so `projected_peak` = 2.838 GB < 4 GiB; `s5_exceeded` then depends on time alone.

## Tests (`tests/unit/test_maker_stage0_bench_screen.py`)
- Flat process (the table above): projected <= 4 GiB, >= observed peak, not exceeded.
- Genuine leak (+100 MB per row, 88 rows): exceeded; leak after warm-up on an 8-row bench: exceeded.
- Noisy flat tail (+-40 MB wobble): not exceeded; shrinking process: slope floored at 0.
- Fewer than 3 rows / empty: no raise, slope 0, observed peak projected.
- `projected_total_s == mean_s * n` unchanged; either limit alone fires `s5_exceeded`.
- `_write_bench` writes the new key and keeps the old ones (RED before the wiring).
