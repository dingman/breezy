# REPLAY-BIGINST plan r1 (2026-09-27, planner): bounded-memory spans for a single large instance

**Goal:** the census completes inside the replay unit's normal 3G/4G memory limits. The TEMPORARY 10G/12G drop-in is containment only (L-29, L-49, L-53).

**Measured baseline:** warm run 2 converted `ea485c90` (8.2G on disk) with an 8.1G cgroup peak in 5m48s, under 10G. The census completed.

## Where the 8.1G almost certainly goes
The objects are built after conversion, not during it.

- **Conversion builds no objects.**
  - Native `_convert_feather_table_to_parquet` uses table-only transforms (`.venv/.../persistence/catalog/parquet.py:2664-2700`).
  - It handles one feather file at a time (`src/breezy/runtime/quote_tape_ingest_cli.py:830-844`).
- **Object building happens in the selection step.**
  - `_select_capture_instruments` pulls every instrument's full depth, quote and close lists through the Rust query, which builds a Python object per row (`parquet.py:1698-1720,1774-1786`; `scripts/analysis/run_weather_strategy_backtests.py:1392-1410`).
  - `by_station_day` keeps every day's `TapeInstrument`s alive at once (`scripts/analysis/replay_sufficiency_census.py:644-648`).

Stage 0 confirms this split before any code is written.

## What the census actually uses (`census:650-679`)
1. The book-backed ids per (station, day): the ids whose ALL-TIME depth count is above 0 (`scripts/analysis/weather_strategy_backtest_lib.py:492-513`).
2. The min and max `ts_event` of depth rows that fall inside the window and have any ask level with size above 0.
   - `best_order` scans all 10 levels (`src/breezy/strategy/depth10.py:31-41`).
3. The min and max in-window `ts_event` of quotes, for book-backed ids only.
4. `distinct_instruments`, the number of book-backed ids.
5. `span_ns = last - first` (`src/breezy/analysis/replay_sufficiency.py:248-253`), so a streaming min/max fold gives the same result.

## Options
- **(a) Scope conversion per day. REJECTED.**
  - `default_convert` does not expose identifiers (`parquet.py:2907-2939`; `ingest_cli:847-881`).
  - The peak would equal the largest day. That still grows with capture density, so it cannot be shown to fit under 3G.
- **(b) Project columns from the converted parquet. PICK.**
  - Read `ts_event` plus `ask_size_0..9` for depth, and `ts_event` for quotes, via `pyarrow.parquet.ParquetFile.iter_batches`. Memory is O(batch) + O(#instruments).
  - Select files with the public `get_file_list_from_data_cls` + `filter_files(identifiers=[id])` (`parquet.py:2205-2312`).
  - Take the schema from the public `NAUTILUS_ARROW_SCHEMA[OrderBookDepth10]` (`.venv/.../serialization/arrow/schema.py:52-71`).
    - Sizes are raw `binary(PRECISION_BYTES)`, so "size > 0" is exactly "any byte != 0". No float decode is needed.
  - Filter on `ts_event`, never on the catalog's `start`/`end`. Those filter on `ts_init`.
- **(c) Reuse the live catalog. REJECTED.**
  - The live catalog carries no instance tag, and the winner rule counts per instance (`census:36-41`).
  - It would also couple the census to ingest.
- **Fallback (b′)**, only if Stage 0 shows conversion alone uses more than 2.5G: project straight from the feather batches (`iter_feather_files` + `read_feather_coalesced`) and skip conversion. That would need a separate r2.

## File-by-file plan
0. **Stage 0 (read-only, run by the coordinator).**
   - Run `_convert_live_capture` alone on `ea485c90` via `systemd-run`, under 3G/4G with `LimitNOFILE=524288`, in a quiet window.
   - Record peak, wall time and CPU/wall.
   - Pass: peak below 2.5G and CPU/wall above 0.3.
1. **`src/breezy/analysis/replay_sufficiency.py`:** add a pure `WindowExtentFold` beside `window_extent` (:240). `window_extent` itself does not change.
2. **New `src/breezy/persistence/catalog_column_scan.py`:**
   - `scan_depth_window(catalog, instrument_id, *, start_ns, end_ns, should_stop, batch_size=65_536) -> (row_count, lo|None, hi|None)`, and `scan_quote_window` with the same shape.
   - It asserts the schema and fails closed if a column is missing.
   - It builds the ask mask with `pc.or_` of `pc.not_equal(ask_size_k, zero_bytes)`.
   - It returns plain Python ints via `.as_py()`.
   - It calls `should_stop()` after every batch.
   - Run `lint-imports` after the change.
3. **`scripts/analysis/replay_sufficiency_census.py`:**
   - Replace the body of `_discover_clean_spans` (:636-679). Keep `_convert_live_capture` and the climate-day loop.
   - Reuse `_capture_instruments_by_id` (backtests:1325), which keeps the dedupe, the `WeatherFactsUnavailableError` and the `TypeError` behaviour the same.
   - Keep the same insertion order: climate day × sorted ids.
   - Add a per-instance `shutil.rmtree(work_catalog)`. This was r1 §3.5, which was never implemented.
   - Remove the imports that become unused. `_select_capture_instruments` itself stays, because the replay drivers use it.
4. **`instance_span_cache.py`:** no change. `SPAN_ALGO_VERSION` stays 1, because the definition of a span is unchanged; E-B6 is the proof.
5. **Tests:** new `tests/unit/test_census_column_scan.py` and `tests/unit/test_census_column_scan_memory.py`. Existing census tests are unchanged.

## Equivalence tests (RED first)
The oracle is the current logic at :644-679, moved verbatim into the test helper `_oracle_spans`.

- **E-B1, multi-day fixture:** 3 days × 2 stations, written with the native `write_data`. It must contain:
  - pad-only rows;
  - a row whose level-0 is pad but which has a real ask at level 2;
  - rows at exactly `start` and exactly `end`;
  - a row with `ts_event` inside the window and `ts_init` outside it;
  - an instrument whose depth rows are all outside the window;
  - a quote-only instrument;
  - a single-row window;
  - duplicate timestamps;
  - files whose timestamp order is non-monotonic.

  The `InstanceSpan` tuples must be equal, and so must the `write_replay_sufficiency` bytes.
- **E-B2:** end to end from live feather, using the existing fixtures and `_convert_live_capture`.
- **E-B3:** a missing `ask_size_3` column raises.
- **E-B4:** an instrument with no weather facts raises the same exception as the oracle.
- **E-B5:** the values are plain Python ints and the JSONL bytes are identical.
- **E-B6:** a cache entry written by the oracle equals a recompute by the new path.

## Memory test (fresh child process, ru_maxrss, L-49)
- Build synthetic catalogs with D ∈ {1, 6} days × 150k depth rows/day. Basetemp goes under `~/.cache`.
- In the child: import, warm up, take a baseline, run the extent pass, and report ΔRSS.
- Assert:
  - Δ(D=6) − Δ(D=1) ≤ 32 MiB;
  - Δ(D=6) ≤ 160 MiB.
- Positive control: the oracle at D=6 must show at least 3× the new path's ΔRSS.

## Mutants
| Mutant | Killed by |
|---|---|
| M1: no ask mask | E-B1 |
| M2: filter on `ts_init` instead of `ts_event` | E-B1 |
| M3: `end` inclusive | E-B1 |
| M4: `start` exclusive | E-B1 |
| M5: check level 0 only | E-B1 |
| M6: use bid sizes | E-B1 |
| M7: quotes from ids that are not book-backed | E-B1 |
| M8: book-backed judged by in-window count | E-B1 `distinct_instruments` |
| M9: first/last taken in file order | non-monotonic files |
| M10: whole type directory instead of `filter_files` | E-B1 |
| M11: no `batch_size` / `read_table` | spy |
| M12: no column projection | spy |
| M13: numpy int leaks into the output | E-B5 |
| M14: skip `should_stop` | SIGTERM test |

## Budget and SIGTERM
- **Time budget.** The new pass decodes about 11 of the ~62 columns and builds no objects, and it avoids the 3G throttle.
  - Each daily 09:00Z rotation creates one new large miss, so this cost recurs every day.
  - The target stays: warm census ≤ 600 s.
- **SIGTERM.** The stop check runs after every batch, so the scan stops in under 1 s.
  - Conversion keeps the r2 I-8 limit of one instance's conversion, as measured in Stage 0.
  - A per-file stop hook would require changing the shared `default_convert`. That is out of scope and goes on the follow-up list.

## Risks
| Risk | Mitigation |
|---|---|
| R1: coupling to Nautilus column names | Schema assert; re-run E-B1/E-B2 on any Nautilus bump |
| R2: conversion alone exceeds 3G | Stage 0 gate; fallback (b′); per-instance rmtree |
| R3: DataFusion directory registration versus our glob | Glob the same directory; E-B1 includes a multi-file directory |
| R4: dict order drift | Same insertion order; E-B6 |
| R5: shared-tree hazards | Worktree + PYTHONPATH; never `uv sync` |

## Firewall compliance
- Unchanged: rows, reasons, `classify_station_day`, the completeness assertion, the winner rule, and the cache key and version.
- Rollout:
  1. Run one capped census at the normal 3G/4G with the cache.
  2. Run one census with `--no-instance-spans-cache` (R3-E).
  3. Diff the rows byte for byte.
  4. Only then retire the drop-in.

## Confidence
- **HIGH:** projection equivalence and the memory bound in D.
- **MEDIUM:** that conversion alone fits in 3G. Stage 0 is mandatory to settle this.
