# Grok adversarial review — WHOLE_TAPE_PAPER_REPLAY_2026-09-05 plan

Run: run-mtoh3h1f-061d1y (read-only, fresh session). Plan commit 8f76ecc.

**Verdict: APPROVE-WITH-AMENDMENTS**

Nautilus stays untouched; `allow_short` stays False (`config.py:231`); wrap `main()`, do not invent a Node fan-out. Cite-check is mostly true. De-dup and wrap-`main()` take-rate are the blockers.

### Findings

1. **[CRITICAL] De-dup longest-span + refuse both ≥30 min is the wrong rule.** `CurrentRungHoldStrategy` takes **the first in-window quote** on the current rung (`strategy.py:18–32`, gate `135–136` / `385`). Longest Depth10 span optimizes later-afternoon book coverage, not that tick. RED 7 (`10 vs 40 → 40`) will replay a 12:25–17:00 tape and **drop a 12:00–12:20 first snapshot**. Dual ≥30 min is not a rare tie: `quote_tape_cli.py:156` and `feed_fault.py:39` document `Restart=on-failure`; a clean mid-window rotate is two CLEAN complementary spans (e.g. 12:00–14:30 and 14:30–17:00), both ≥30 min — the plan **refuses the station-day**. That will discard restart-split afternoons, not “ties.” **Amendment:** winner = CLEAN instance that **contains the earliest in-window QuoteTick (or Depth10) for that station**; refuse only if two CLEAN instances both contain that same first instant. Complementary non-overlap: pick the earlier-open instance (stitching is unnecessary — latch consumes after first decision). Do not use longest span. List dual-cover refuses as blocked, not no-take.

2. **[HIGH] Wrapping `main()` forces both `PRECISION_ARMS`.** There is no `--precision-mode` flag; `main` always loops `("nws_integer_c", "archive_metar")` at **`:698`**, not `:696`. Both arms share `trial_id` (`paper_replay.py:347`, lag omitted) and `score_seq=0`. Pooled take-rate double-counts a station-day. **Amendment:** call `run_one_precision_arm` for `nws_integer_c` only, or report take-rate **per arm**. Do not pool.

3. **[HIGH] Crash retry vs empty work catalog.** `_convert_live_capture:1263–1268` refuses a non-empty `--work-catalog` (native convert silently skips). Output-dir parquet skip (`scored_trial_store.py:79–90`) does not clear a dirty work root. **Amendment:** unique work catalog per attempt, or delete/recreate before retry.

4. **[HIGH] Look-ahead still lands in parquet.** Caveat is honest for markdown. `main:727–731` still `score_trials` + `write_scored_trials` with FINAL `held`/`pnl` (`climate_day_records_to_settlement:582`). Discarding Wilson/ROI from the report is right; the file still carries edge columns. **Amendment:** persist fill-vs-ask/L2 only, or stamp the caveat on every parquet/header; never let `held`/`pnl` be the claim surface.

5. **[MED] Coverage union is real; wrapper-only gate leaves a driver footgun.** `assert_decision_window_has_coverage:236` is `for ti in tape_instruments for quote in ti.quotes` — **not** filtered by `facts.settlement_station`. `_select_capture_instruments:1287–1312` is climate-day only. An SFO quote **does** launder an LAX-empty capture. Per-station refusal before `main()` is correct. **Also** filter `quote_ts` (and de-dup span) to that station’s instruments. Span metric should match the strategy (**QuoteTick**), not Depth10-only.

6. **[MED] Take-rate denom.** Eligible = replayable CLEAN unique-winner station-days with in-window coverage. Exclude EMPTY/LIVE/CORRUPT-only (`station_days_only_on_corrupt_tape:436`), empty-window, and dual-cover refuses as **blocked**. Do not count them as no-take.

7. **[LOW] `:696` is `now_ns=max(...)`; PRECISION loop is `:698`. 11.5h is credible for the written wrap; findings 1–3 add ~2–4h. Missing REDs: 20-vs-255 first-snapshot; dirty work-catalog; `derived/scored_trials` refused **and** `derived/paper_replay/scored_trials` still passes (substring).

### Q1 L-1 — Node insufficient: **TRUE**

`BacktestNode.__init__:79–107` stores `list[BacktestRunConfig]`; `run:459–490` sequences `_run` per config. Breezy paper path is `build_backtest_engine:663` + `backtest:1027` with live `Strategy` objects, `FillModel()`, `BookType.L2_MBP`, `liquidity_consumption=True` (`:731–746`). Harness `:967–970`: ImportableStrategyConfig JSON **cannot carry** a latch factory. Node would not shrink convert/select/score/IOC. Do not fan out on Node.

### Q3 Paper containment — widen is necessary, not sufficient

Real live store is `DEFAULT_DERIVED_DIR = ~/.local/share/breezy/derived/scored_trials` (`score_live_trials.py:131`), **not** `derived/live/scored_trials` (`_LIVE_STORE_MARKER:122`). Test `:1016–1022` only hits the live-shaped path. Widen to **two exact fragments**; `"derived/scored_trials" in path` does **not** match `derived/paper_replay/scored_trials` (good). Independent barriers still hold if rows stay under paper dirs: `PAPER_TRIAL_ID_PREFIX:92`, `assert_live_only:148` (`current_rung_hold/trial/`), `_assert_live_provenance:325` (no sidecar / not `"live"`), `assert_family_only:47`. Missed: latch sqlite in `--work-catalog` (must not be the live node store); `main` never writes `provenance.json`; do not mint live prefixes. Keep `test_paper_rows_never_pool_into_the_live_tally` unmodified.

### Claims

**TRUE:** `node.py:79–107,459–490`; `build_backtest_engine:663` / `backtest:1027`; `main:646–660`; `list_instance_ids:488`; `scan_instance:501`; `classify_instance:386`; `_classify_all_instances:863` swallows `PreflightError`; `_convert_live_capture:1240`; `_select_capture_instruments:1287`; `read_weather_bucket_facts:90`; `_instrument_facts:549`; `_WINDOW_*:111–112`; `K_B_REQUIRED_LAGS_LIVE:195`; coverage union `:226/:236`; `station_days_only_on_corrupt_tape:436`; stamp `:79–90`; trial_id omits lag `:347`; header `:175/:130`; FINAL `:582`; `backtest_only.py:71,120–128`; marker `:122`; path guard `:277–282`; tests `:811/:1016`; `allow_short:231`; `assert_live_only:148`; `_assert_live_provenance:325`; `assert_family_only:47`; `score_trials:245`; quote-only refuse `paper_replay.py:257`.

**FALSE:** PRECISION loop at `:696` (actual `:698`).
