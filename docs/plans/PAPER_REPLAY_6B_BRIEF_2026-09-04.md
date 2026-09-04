# 6b paper-replay harness build brief (2026-09-04) — DRAFT, under peer review

Authored by code-architect against `74cfa7c`. Blueprint build-order item 6b. Coordinator note: `CurrentRungHoldConfig` refuses `orders_enabled=True` (L-22 pin); how a BACKTEST-ONLY engine can exercise the fill path without offering a production toggle is an open question for the reviewers (candidate: a backtest-scoped subclass/config constructed only inside `runtime/backtest_harness.py`, pinned by a one-caller scan).

## Brief: `current_rung_hold` paper-replay harness (blueprint 6b)

Repo `/home/jon/breezy` @ 74cfa7c. Read-only design; no Nautilus edit proposed, none needed.

### Verdict on the hard question (fill semantics): NATIVE, no custom fill model
"1-contract IOC BUY at the displayed ask, filled only when displayed size ≥ 1, no queue" is **fully expressible by the venue config already shipped** in `/home/jon/breezy/src/breezy/runtime/backtest_harness.py:713-786`:
- `book_type=BookType.L2_MBP` + `liquidity_consumption=True` + `queue_position=False` + `fill_model=FillModel()` (defaults `prob_fill_on_limit=1.0`, `prob_slippage=0.0`; `prob_slippage` is inert under L2).
- IOC remainder is cancelled natively: `.venv/lib/python3.13/site-packages/nautilus_trader/backtest/engine.pyx:7432-7434` ("IOC order has filled all available size" → `cancel_order`).
- Size < 1 / no liquidity → **no fill, order cancelled, no fabricated print**: `engine.pyx:6737-6748` (`if not fills and self._liquidity_consumption: … IOC → cancel_order; return`).
- Marketable limit fills walk the real book: `determine_limit_fills_with_simulation` (`engine.pyx:6760+`), consumption tracked per price level (`engine.pyx:4314-4319`).
- `BestPriceFillModel` must never be used (returns 1_000_000 units at best ask — `backtest/models/fill.pyx:170-180`), already documented at `backtest_harness.py:733-735`.

**The one real trap:** `SimulatedExchange.process_quote_tick` does **not** mutate the book when `book_type != L1_MBP` (`engine.pyx:4509,4551`). The strategy consumes `QuoteTick` (`strategy.py:251`), but the *fillable* book must come from `OrderBookDepth10`. Both are in the capture (`run_weather_strategy_backtests.py:1290-1296`), so the replay feeds **both** streams for every replayed instrument. A quote-only run would decide identically and fill *never*, silently — that is RED test #2 below.

Remaining native gaps: none in Nautilus. Two repo-side items are genuinely absent and are what this harness authors: (a) a `StationObservation` replay source (nothing under `src/breezy/persistence` or `runtime` persists them — the live NWS actor publishes and drops), (b) a fills→`FilledTrial` adapter (`trial_scorer.py:83-86` explicitly defers it to R-7/R-8; 6b needs its own).

### Data availability (measured today, epoch mtimes per the freshness memory)
Converted partition `~/.local/share/breezy/catalog/quote_tape/polymarket_us/data`: 1631 files, newest mtime **1788437904** (2026-09-03 12:18, 15.2 h). Live/unconverted `…/live`: 8.1 G, 10 instance ids, newest **1788474670** (2026-09-03 22:31, 5.0 h).

| Partition | station-days (all) | **excl. NYC (L-13)** | days present |
|---|---|---|---|
| `data/quote_tick` | 13 | **10** | 08-30, 08-31, 09-01, 09-03 |
| `data/order_book_depths` | 17 | **13** | 08-30, 08-31, 09-01, 09-03 |

**2026-09-02 is absent from `data/` entirely** while `live/` holds 5 h-fresh feather — textbook **L-20**: the converted catalog is not the tape. The harness must therefore read `live/<instance_id>` through `ParquetDataCatalog.convert_stream_to_data` into a fresh work root, reusing `_convert_live_capture` (`scripts/analysis/run_weather_strategy_backtests.py:1224-1262`), and must **print both counts (data/ vs live/) and refuse silently-partial conversion**.

Observations: ASOS 5-minute cache `~/.local/share/breezy/archive/settlement-alignment-cache`, 64 files, newest **1788475547** (2026-09-03 22:45, 4.7 h), `station,valid,metar` rows from 2026-08-30 for LAX/MDW/MIA (+MDW/SFO), parseable verbatim by `iem_asos_rows_to_station_observations` (`src/breezy/ingest/iem_observations.py:55-110`). Settlement truth: `~/.local/share/breezy/catalog/polymarket_us/{LAX,MDW,MIA,SFO,NYC}/data/custom_nws_climate_day` exists for all five.

**Realistic overlap: ≈10 station-days (4 stations × ~2-3 days), i.e. n ≤ 10.** This harness is a *mechanism* test, never evidence about the edge — it can never reach the 60/150 PREREG floors. State that in the report header.

### Two declared fidelity divergences (must be printed in every run header, never defaulted away)
1. **Receipt time is synthesized.** IEM archive rows carry `valid`, not receipt; `iem_asos_rows_to_station_observations` takes one caller-supplied `received_at_ns`. The replay sets `received_at_ns = observed_at_ns + L_extra` per row. `--lag-minutes` is **required, no default**, and the run is repeated at **30 and 45** (PREREG §3 — both arms must agree). This is not a price fabrication; it is the same assumption the archive arms already make.
2. **Precision.** Archive METAR gives `precision_c_tenths=5`; the live NWS 5-minute feed gives integer °C (10). Replaying at 5 *under-counts* `observation_ambiguous` versus live. Default `--observation-precision nws_integer_c` (pessimistic, faithful); `archive_metar` is a labelled sensitivity arm only.

### Files to create
| Path | Purpose | ~lines |
|---|---|---|
| `/home/jon/breezy/src/breezy/runtime/paper_replay.py` | Library: `PaperReplayInputs`, `load_replay_observations()`, `build_paper_replay_config()` → `BreezyBacktestConfig`, `filled_trials_from_engine(engine, entry_asks)` → `FilledTrial` rows, `PAPER_PROVENANCE`/`PAPER_TRIAL_ID_PREFIX`. No argparse, no network. | 260 |
| `/home/jon/breezy/scripts/analysis/current_rung_hold_paper_replay.py` | CLI driver: convert `live/` → work catalog, select instruments, load ASOS, run `backtest()`, score via `score_trials`, write parquet, print the per-station-day trial table + strata/Wilson/BCa lines. | 320 |
| `/home/jon/breezy/tests/unit/test_current_rung_hold_paper_replay.py` | RED tests 1-8 below. | 400 |
| `/home/jon/breezy/tests/unit/test_live_family_tally_provenance.py` | RED tests 9-10. | 120 |

### Files to modify
| Path | Change |
|---|---|
| `scripts/analysis/live_family_tally.py` | Add `--provenance {live,paper_replay}` (default `live`). Add `assert_paper_only()` mirroring `assert_live_only` (`:130-147`) and refusing any `current_rung_hold/trial/`-prefixed row. `build_live_family_tally` gains `provenance: str = "live"` and dispatches to the matching assertion. Header gains the provenance line. **`assert_live_only` itself is not weakened** — paper rows already fail it because their `trial_id` does not start with `_LIVE_TRIAL_ID_PREFIX` (`:78`). |
| `src/breezy/persistence/scored_trial_store.py` | **No schema change.** Provenance is derived from the `trial_id` namespace, not stored, so `SCORED_TRIAL_SCHEMA` stays byte-compatible with existing live files (adding a column would make `pq.read_table(path, schema=…)` fail on already-written rows). |

**Provenance design (L-22 — exclusion must be unforgeable, not offered):** paper trial ids are `paper_replay/current_rung_hold/trial/{station}/{climate_day}`. Two independent barriers: (i) the *unmodified* `assert_live_only` refuses them by prefix; (ii) they are written to a separate default dir `~/.local/share/breezy/derived/paper_replay/scored_trials/`. Forging a paper row into the live tally requires rewriting its `trial_id`, not flipping a flag.

### Data flow
`live/<instance_id>` feather → `convert_stream_to_data` → work catalog → `BinaryOption` + `OrderBookDepth10` + `QuoteTick` (real capture, forward-only, no archive price anywhere on this path) → `BreezyBacktestConfig.market_data`; ASOS cache → `StationObservation` → `as_backtest_data(...)` → `weather_data` (`backtest_feed.py:102,127`); → `build_backtest_engine` (`backtest_harness.py:663`) → `add_strategy(CurrentRungHoldStrategy)` → engine `run()` → `OrderFilled` events + the strategy's latch rows (`entry_ask`, decision instant) → `FilledTrial` → `score_trials(pairs, now_ns)` (`trial_scorer.py:245`) against the highest-`revision_seq` **FINAL** `NwsClimateDay` (pattern at `run_weather_strategy_backtests.py:_settled_readings`) → `write_scored_trials` → `live_family_tally --provenance paper_replay`.

Coupling to the sibling's in-flight latch change: take the latch **as an injected factory/context manager parameter of the driver**, never construct it inline; the driver uses a temp-dir store so a replay can never touch live latch state. `orders_enabled` must be `True` for the replay config, and the R-7 standing refusal must be inert in-engine — if `_maybe_submit` (`strategy.py:336-360`) still short-circuits, 6b is blocked on R-7 and must say so rather than stubbing a submit.

### RED tests (all fail first)
1. `test_no_archive_derived_price_ever_enters_the_replay` — AST/source guard: the driver module imports no price-bearing archive symbol (`parse_asos_rows`/`settlement_alignment_study` price paths), and every `QuoteTick`/`OrderBookDepth10` handed to `market_data` carries a `ts_init` inside the converted capture window; an injected synthetic quote whose provenance is not the work catalog raises.
2. `test_a_quote_only_replay_with_no_depth_is_refused_not_silently_fillless` — depth absent for a replayed instrument → explicit refusal citing `engine.pyx:4551`, not a zero-fill run.
3. `test_an_ioc_at_a_displayed_size_below_one_records_not_executable_and_no_fill` — ask size 0 at the decision instant → no `OrderFilled`, trial row reason `not_executable`, `len(scored)+len(refused)==len(trials)`.
4. `test_an_ioc_at_displayed_size_one_fills_exactly_one_contract_at_the_displayed_ask` — `fill_px == entry_ask`, `slippage == 0`, qty 1, no remainder resend.
5. `test_paper_rows_never_pool_into_the_live_tally` — `assert_live_only([paper_row])` raises, **with `live_family_tally.py:130-147` unmodified**.
6. `test_the_paper_tally_refuses_a_live_row` — symmetric `assert_paper_only`.
7. `test_replay_receipt_time_is_synthesized_and_required` — omitting `--lag-minutes` exits non-zero; a quote with `ts_event < received_at_ns` is never priced (mirrors PREREG §3 lag rule).
8. `test_the_run_header_states_lag_precision_and_n_ceiling` — header carries lag arm, precision mode, station-day count, and the "mechanism test, not evidence; n cannot reach 60/150" line.
9. `test_settlement_comes_from_the_final_climate_day_only` — preliminary-only day → `ScoreRefusal`, never a fabricated `held`.
10. `test_the_strategy_object_is_the_shipped_one` — the replay imports `CurrentRungHoldStrategy`/`evaluate_decision` verbatim; no re-implemented decision path (bot trades, Claude builds the bot).
11. `test_a_populated_work_catalog_is_refused` — reuses the `_convert_live_capture` silent-skip guard (L-20).

### Build sequence
1 `paper_replay.py` types + `load_replay_observations` · 2 `build_paper_replay_config` (tests 1,2,7,11) · 3 `filled_trials_from_engine` (tests 3,4) · 4 tally provenance split (tests 5,6) · 5 driver CLI + report (tests 8,9,10) · 6 first real run over the ~10 station-days at lag 30 and 45, memo to `docs/evidence/`.

### Least-confident decisions (odds it survives review)
- **Provenance as a `trial_id` namespace rather than a stored column — 0.75.** Cheapest unforgeable exclusion and zero schema risk, but a reviewer may want the column for queryability; if so, add it *nullable* and default-fill on read.
- **IOC fill fidelity via stock `FillModel()` under L2 + `liquidity_consumption` — 0.85.** Verified by source, unverified by execution; test 4 is the only thing that settles it.
- **Synthesized receipts (valid + L) being honest enough to report — 0.65.** It is the archive arms' own assumption, but a replay labelled "paper" invites over-reading; the header disclaimer is load-bearing.
- **Precision default `nws_integer_c` — 0.7.** Pessimistic and closer to live, but it means the replay's ambiguity rate will not match the archive study's; expect a reviewer to ask for both arms printed side by side.
- **Blocked-on-R-7 risk — 0.5.** If `_maybe_submit` still refuses every submit, 6b produces zero fills and tests 3/4 cannot go GREEN; the fallback is to land 6b's config/observation half now and gate the fill half on R-7 rather than stub a submit path.

## Converged peer review (2026-09-04) — BINDING over the draft above

Reviewers: trading-bot-architect (APPROVE-WITH-AMENDMENTS; all four Nautilus cites confirmed), prediction-market-reviewer (APPROVE-WITH-AMENDMENTS). Coordinator decisions:

1. **6b is NOT blocked on R-7.** The backtest fills through `SimulatedExchange`, never through `PolymarketUSExecutionClient._submit_order` (the R-4 refusal). The sole blocker is `CurrentRungHoldConfig.__post_init__` refusing `orders_enabled=True` unconditionally (`config.py:237-241`) — that pin and `OrdersEnabledNotPermittedError` stay BYTE-UNMODIFIED.
2. **Backtest-only subclass, not a config toggle.** New `CurrentRungHoldBacktestStrategy(CurrentRungHoldStrategy)` in `src/breezy/runtime/paper_replay.py` (its only importer is the paper-replay driver + its tests; pinned by a one-importer AST scan, RED test 12 `test_the_backtest_only_strategy_subclass_has_exactly_one_importer_and_refuses_a_live_clock`); it carries its OWN internal submit flag and asserts `isinstance(self.clock, TestClock)` in `on_start` so a mis-wiring into a live node fails at start. Build step 0 lands this before step 2.
3. **No verdict vocabulary in paper output.** The driver prints, verbatim, near the top of stdout and every artefact: `PROVENANCE: paper_replay — mechanism test only, NOT the live_small evidence family. n<=10 station-days cannot reach PREREG v1 kill (n>=60) or survive (n>=150) floors. This run computes no KILL, SURVIVE, or UNDERPOWERED verdict; it verifies the fill/scoring mechanism only.` and prints `MECHANISM TEST — NO VERDICT` in place of any verdict. RED test 8 asserts the literal tokens `KILL`, `SURVIVE`, `UNDERPOWERED` never appear in paper stdout or artefact text (absence, not just disclaimer presence). The paper tally never reads `build_live_family_tally`'s outcome field.
4. **Lag anchor stated honestly (HIGH).** The archive study lags relative to the decision instant (`find_lagged_entry(rows, not_before=t+lag)` with R at `t` unlagged, `mb_current_rung_edge_study.py:480-490`); the replay's `received = valid + L` then `quote.ts_event >= received` is PREREG §3 / A1's LIVE rule (receipt of the R-setting observation), NOT the archive arm's rule. Drop the "same assumption the archive arms make" sentence; add a RED test on a fixture where R is stale (held from an earlier row) demonstrating the two anchors diverge, and print which rule the run applied in the header.
5. **Both precision arms printed unconditionally** (`nws_integer_c` and `archive_metar`), side by side, every run.
6. **Unforgeable provenance (L-22).** `filled_trials_from_engine`/the paper `FilledTrial` builder accept NO `trial_id` argument — the `paper_replay/current_rung_hold/trial/{station}/{climate_day}` id is derived internally. The paper writer RAISES if its output path resolves under the live `scored_trials/` directory (not merely defaults elsewhere). Provenance stays a `trial_id` namespace; no schema column.
7. **Venue-skip days.** RED test: the replay's station-day set is a subset of the tape's listed days; an explicitly requested unlisted day raises (L-23), never a silent zero.
8. **No hand computation in the reporting layer.** RED test (AST guard): the driver imports `score_trials`, `compute_roi_bound`/`format_roi_bound`, and the study's Wilson helper, and contains no inline Wilson/bootstrap arithmetic.
9. Data-availability counts (13/10 quote-tick, 17/13 depth station-days; 09-02 only in `live/`) are plausible but unverified by the reviewers — the driver prints both counts at run time and refuses a silently partial conversion (L-20).

Build gate: lands after the strategy review amendments (latch factory as context manager + `on_stop`) are on the branch; the driver takes the latch factory by injection.
