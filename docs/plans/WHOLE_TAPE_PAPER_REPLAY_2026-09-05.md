Commit: 8f76ecc9a3bb519b61db2e119aa5b05c8c315c58

# [DESIGN] Whole-tape PAPER REPLAY (rev 2)

GOAL: classify every captured quote-tape instance; paper-replay each `(station, climate_day)` once (winner CLEAN tape) at lags 30 and 45 as live family `current_rung_hold`; settle on highest-`revision_seq` FINAL NWS CLI; paper-only report headed `MECHANISM TEST -- NO VERDICT`. Claims: plumbing, take-rate, L2 fill-realism — not edge. Zero paper rows in `derived/scored_trials` or PREREG v2. No live venue I/O. `allow_short` stays False.

WALK: classify → peek-convert CLEAN → `_select_capture_instruments` station-days → de-dup/winner/tie-refuse **before** replay → per-station coverage gate → wrap `main()` × lags → one output dir per `(station, climate_day, lag)` → additive report.

## L-1 (nautilus-trader 1.231.0)

Multi-run: **NATIVE — insufficient.** `BacktestNode(configs)` (`node.py:79-107,459-490`) sequences configs; Breezy paper path is one `BacktestEngine` via `backtest_harness.build_backtest_engine:663` + `backtest:1027` (L2_MBP, `FillModel()`, `liquidity_consumption=True`). Do not invent a Node fan-out.

Convert/select/score/IOC: **NATIVE — reuse** inside the single-instance driver.

Whole-tape loop, pre-replay de-dup, additive report: **GENUINELY ABSENT.** Wrap `current_rung_hold_paper_replay.main:646`.

## Orchestration

New CLI `scripts/analysis/whole_tape_paper_replay.py`.

**Classify.** `list_instance_ids` (`feather_preflight.py:488`) under `live/`. Per id: `scan_instance:501` then `classify_instance` (`cli_basis_offer_gate_scan.py:386`). Do **not** copy `_classify_all_instances:863` (`except PreflightError: continue`). PreflightError is a listed failure. EMPTY/LIVE skipped by name. CORRUPT listed, not replayed. Catalog dir count 16 vs brief 15: UNVERIFIED (`breezy-quote-tape-preflight`).

**Station-days (CLEAN).** Peek-convert each CLEAN instance to a throwaway empty work catalog (`_convert_live_capture:1240`). List via wrapped `_select_capture_instruments:1287` + `read_weather_bucket_facts` (`weather_bucket_facts.py:90`). **Do not** use `_instrument_facts:549` (open-upper-tail; drops in-window 2F m=0 books). Replay convert uses a different empty `--work-catalog`.

**De-dup BEFORE replay.** Key `(station, climate_day)` only — never `instance_id`. Measure that station's `[12:00,17:00)` LST Depth10 span (`_WINDOW_START/END:111-112`). Winner = CLEAN instance with the longest span. If two or more CLEAN instances each cover **≥30 min**, REFUSE the pair (no first-list, stitch, or union). Then × `K_B_REQUIRED_LAGS_LIVE=(30,45)` (`mb_current_rung_edge_study.py:195`).

**Coverage.** Refuse `(instance, station, day)` when **that station's** window Depth10 is empty. `assert_decision_window_has_coverage:226` unions all instruments — SFO quotes must not launder an LAX-empty capture. Do not call `main()` for an empty-window station.

**CORRUPT-only days.** `station_days_only_on_corrupt_tape:436`. List them. **Exclude from take-rate denominator.**

**Wrap `main()`.** Required flags only (`:647-660`). Do **not** pass precision_mode (`:696` loops `PRECISION_ARMS`). Fresh empty `--work-catalog` each call.

**Crash-safe:** `--output-dir={paper_replay}/scored_trials/{station}/{climate_day}/lag_{L}/`. Skip iff that dir already has `scored_trials_*.parquet`. Shared lag-wide stores clobber (tape-clock `_stamp`, `scored_trial_store.py:79-90`; `trial_id` omits lag, `paper_replay.py:347`).

**Report** (markdown+csv under `derived/paper_replay/`): reuse `build_provenance_header:175` / `:130`. Per-trial take/no-take, fill vs ask vs L2. Take-rate over eligible CLEAN station-days only. Discard `main()` Wilson/ROI. Never write `provenance.json` `"live"`. Never mint `current_rung_hold/trial/` ids.

Interval rule stays in `CurrentRungHoldBacktestStrategy` (`backtest_only.py:71`, IOC BUY `:120-128`).

## Files

**Add:** `scripts/analysis/whole_tape_paper_replay.py`. `tests/unit/test_whole_tape_paper_replay.py` (prose names, importlib, capsys, tmp_path).

**Patch (wrap, don't rewrite):** Widen `_LIVE_STORE_MARKER:122` / `assert_paper_write_path_is_not_live:277-282` to refuse `derived/scored_trials` **and** `derived/live/scored_trials`; `derived/paper_replay/scored_trials` must pass. Extend `:1016`. Add wrapper stdout test; do **not** rewrite header test `:811`.

**Do not change:** Nautilus; `allow_short=False` (`config.py:231`); `assert_live_only:148`; `_assert_live_provenance:325`; `assert_family_only` (`family_barrier.py:47`); `score_trials:245`; FINAL join `:582`; `PRECISION_ARMS`; `PAPER_TRIAL_ID_PREFIX:92`; quote-only refuse `:257`. Existing tests unmodified.

## RED tests (`scripts/ci/run_tests_no_egress.sh`)

1. Wrapper stdout carries `MECHANISM TEST -- NO VERDICT`.
2. `main()` twice (lags 30, 45); precision_mode never in argv.
3. EMPTY skipped; CORRUPT listed; PreflightError not silent; CORRUPT-only days listed via `station_days_only_on_corrupt_tape` and absent from take-rate denom.
4. Refuse both live markers; paper default dir ok (widen `:1016`).
5. Distinct dirs per `(station, climate_day, lag)`; skip when parquet present; crash mid-`main()` does not double-write.
6. No live sidecar / live trial prefix; `assert_live_only` / v2 still refuse. `test_paper_rows_never_pool_into_the_live_tally` unmodified.
7. De-dup key is `(station, climate_day)` not `instance_id`. Spans 10 vs 40 min → `main()` only with the 40-min instance. Both ≥30 min → refuse, `main()` not called. `_instrument_facts` not used as lister.
8. Report has look-ahead sentence, take-rate, fill-vs-book; **no** Wilson/ROI. Empty-window station refused even if another station on the same instance quotes in-window.

## Build order

1. Widen live-path refuse + RED 4 — **1.0h**.
2. Classify + CORRUPT-only listing + RED 3 — **2.0h**.
3. Peek-convert + wrap `_select_capture_instruments` + winner/tie/coverage + RED 7,8 — **3.0h**.
4. Wrap `main()` × lags + per-triple dirs + crash skip + RED 2,5,6 — **3.0h**.
5. Additive report (no Wilson/ROI) + RED 1,8 — **1.5h**.
6. One CLEAN dry-run (no egress) + gate — **1.0h**.

**Total 11.5h** (band 8–15h).

## Look-ahead caveat (verbatim in every report)

> Settlement joins the highest-`revision_seq` FINAL NWS CLI record (`climate_day_records_to_settlement:582`). Those corrections are unpublished at decision time. This run is a plumbing / take-rate / L2 fill-realism mechanism test — not a backtest of edge. MECHANISM TEST -- NO VERDICT.

## Top 3 risks

1. **Live-store trap.** Marker misses `derived/scored_trials`. Contain: widen `:277`; write only under `derived/paper_replay/`; never live sidecar; v2 + `assert_live_only` keep refusing.
2. **Overlap without a unique winner.** Two CLEAN tapes ≥30 min on the same station-day. Contain: refuse the pair before `main()`; RED 7.
3. **FINAL look-ahead.** Hold/PnL uses post-decision CLI. Contain: caveat; no KILL/SURVIVE; take-rate and fill-vs-book only; discard driver Wilson/ROI.
