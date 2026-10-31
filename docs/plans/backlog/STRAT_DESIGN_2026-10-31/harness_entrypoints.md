# Existing backtest harness — entry points (2026-10-31)

Read-only inventory for STRAT-DESIGN r0. No new runner. Paths are the ones on
this host today. The home quote-tape path and the `/mnt/storage` path resolve
to the same directory (`/mnt/storage/breezy/catalog/quote_tape/polymarket_us`).

## 1. The engine

Nautilus is used, not wrapped. `src/breezy/runtime/backtest_harness.py` says so
in its module docstring (lines 12–20): the object returned is `BacktestEngine`.

| What | Where |
|---|---|
| Venue arguments, fixed by spec | `build_backtest_engine` line 661; `engine.add_venue` line 711 |
| Venue name | `POLYMARKET_US` at lines 711–712 |
| `book_type` | `BookType.L2_MBP` line 729 |
| Fee | `PolymarketUSFeeModel()` line 737. Quadratic θ·C·p·(1−p). Settlement at 0 or 1 charges 0 |
| Latency | `latency_model=None` line 740. Documented overstatement |
| Queue | `queue_position=False` line 752. Requires `trade_execution=True`, which is False (line 747) because the harness does not consume the trade tape |
| Liquidity | `liquidity_consumption=True` line 743, so one stale depth frame cannot refill forever |
| Settlement price | `settlement_prices=dict(config.settlement_prices)` line 773. `InstrumentClose.close_price` is not read by the engine (spec `docs/specs/BACKTEST_VENUE_CONFIG.md` §0; harness docstring lines 27–34) |
| Run | `run_backtest` line 956: build, `install_order_guard`, `add_strategy`, `engine.run()`, then refuse rejected orders, open positions, and idle strategies unless the matching flag is set |
| Dispose | `backtest` context manager line 1026 |

Spec authority: `docs/specs/BACKTEST_VENUE_CONFIG.md`, named at harness line 3.
Pinned from source by `tests/unit/test_runtime_backtest_harness.py` (harness
lines 5–7). Account is `CASH`, OMS `NETTING`, `allow_cash_borrowing=False`
(line 766). A naked sell is refused by the submit-time guard
(`breezy.runtime.backtest_order_guard`, referenced at lines 997–999), which is
how `allow_short = false` is kept inside a cash account that would otherwise
not stop a sell.

Call site the paper driver actually uses:

```
scripts/analysis/current_rung_hold_paper_replay.py:1332
    with backtest(config, strategies=(strategy,), allow_idle_strategies=True) as engine:
```

Weather records must be wrapped and subscribed with `client_id=NWS_BACKTEST_CLIENT_ID`.
Put in `market_data`, they are dropped and `on_data` never runs (harness lines
631–639). Every strategy in the run sees every city's weather and must filter
`record.station` (lines 70–81).

## 2. Commands that already drive it

Working directory is the repo root. Interpreter: `/home/jon/breezy/.venv/bin/python`.
These are the existing modules. Flags below are the ones the parsers require,
not a new recipe.

### One station-day, engine, mechanism only

`scripts/analysis/current_rung_hold_paper_replay.py` `main` line 1458.

Required flags (lines 1460–1472): `--climate-day`, `--station`,
`--tape-instance-id`, `--quote-catalog`, `--work-catalog`, `--asos-cache-csv`,
`--weather-catalog-root`, `--lag-minutes`. Optional `--strategy`
`current_rung_hold|continuous_rung_hold` (line 1474) and `--family-manifest`
(line 1501). The docstring (lines 6–9) forbids a family-tally verdict: the
print is `MECHANISM TEST -- NO VERDICT`. n from one day cannot meet the old
PREREG floors.

Strategies it can construct: `CurrentRungHoldStrategy` (line 235 of
`src/breezy/strategy/current_rung_hold/strategy.py`) and
`ContinuousRungHoldBacktestStrategy` (line 88 of `continuous_backtest_only.py`).
Not the maker.

### Whole tape, still the same engine, still mechanism only

`scripts/analysis/whole_tape_paper_replay.py` `main` line 887. Picks one CLEAN
instance per `(station, climate_day)` and calls `run_one_precision_arm` from
the paper driver. Reports stay under `derived/paper_replay/`.

### Scheduled one-day replay of the armed family

`scripts/analysis/replay_daily_runner.py` `main` line 1955. One invocation
replays at most one `(station, climate_day)` unless `--max-targets` is raised
(parser line 1904; default 1). Requires `--quote-catalog`,
`--weather-catalog-root`, `--family-manifest`, `--output-root` when it is a
real run (lines 1936–1947). The armed family's `composition_kind` selects the
strategy. A comment at lines 1879–1881 records that `forecast_quantile_ladder`
has no replay. This runner is not a maker backtest.

Census it reads: `scripts/analysis/replay_sufficiency_census.py` `main` line
1221. Default catalog line 156:

`Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"`

Default output: `~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl`
(line 159).

### Maker fill simulator — not the engine

`python -m scripts.analysis.maker_stage0_replay` (`maker_stage0_replay.py`
lines 1–15). Default catalog line 40 is the same home quote-tape path.
Default NBP line 41: `~/.local/share/breezy/derived/nbp`. Default truth line
42: `~/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet`.
Ledger (derived, not a flag) line 45:
`~/.local/share/breezy/derived/maker_stage0/verdict_ledger.jsonl`.

A verdict run claims that ledger once. `--bench N` (N = 4 or 8), `--tail-only`,
and `--verify-first` do not. Exit 0 done, 2 refused before the claim, 3 voided.
The simulator is `scripts/analysis/maker_stage0_fill_pass.py` (`queue_sizes`
line 79). It is pure: no `BacktestEngine`.

Design arms, same simulator, fenced days, no edit of `maker_stage0_*`:
`scripts/analysis/maker_design_nobid.py` `main` line 468. Arms in
`maker_design_config.py` lines 75–85: `control`, `control_noabst`, `nbp_deep`
(cap 0.84), `spike_bid`, `sharp` (cap 0.89, p_min 0.97, e_min 0.04),
`sharp_cap84`. `NO_BID_CEILING = 0.90` at line 55 so a design run cannot bid
into the frozen M1-v3 population.

### Studies that read the catalog and do not start the engine

| Module | `main` | Question it already answers |
|---|---|---|
| `scripts/analysis/market_calibration_scan.py` | line 860 | Model-free taker excess by ask bin. Windows fixed at lines 152–156 (D−1 18Z, D 12Z, D 17Z UTC). `--catalog` defaults to the quote-tape root (line 111) |
| `scripts/analysis/wp7b_market_as_forecaster.py` | line 1287 | Forecast vs market, including Σask on complete partitions |
| `scripts/analysis/p2_nbp_ask_murphy.py` | module docstring line 8 | NBP vs YES ask. Depth root hardcoded line 361 under `/mnt/storage/breezy/catalog/quote_tape/polymarket_us/data/order_book_depths`. Scored days end 2026-10-13 (line 29) |
| `scripts/analysis/no_longshot_pooled_test.py` | line 990 | M1-v3 forward screen, NO ask ≥ 0.90. Read-once. Refuses a verdict unless the frozen blob matches |
| `scripts/analysis/nbp_revision_latency.py` | docstring lines 1–6 | LAT-1. Refuses while its prereg sha is unfrozen, and refuses D ≥ 2026-10-28 |
| `scripts/analysis/k1_cheap_open_settlement.py` | cited by `docs/evidence/k1_cheap_open_2026-09-01.md` | Descriptive settlement frequency. The note says Nautilus owns backtesting and this script does not simulate fills |

## 3. Catalogs and dates actually present

Checked 2026-10-31 by listing directories, not by scanning row timestamps.

| Root | What is there |
|---|---|
| `/mnt/storage/breezy/catalog` | `quote_tape/` only |
| `quote_tape/polymarket_us/data` | `binary_option`, `order_book_depths` (2,041 dirs), `quote_tick`, `trade_tick` (1,478 dirs), `instrument_status`, `mark_price_update`, `custom_depth_truncation`, `custom_quote_tape_gap`, `custom_venue_clock_offset`, `custom_venue_settlement_snapshot` |
| `quote_tape/polymarket_us/live` | 101 instance directories. Directory mtimes 2026-09-02 through 2026-10-31 |
| Depth directory names | 63 distinct `YYYY-MM-DD` tokens, 2026-08-30 through 2026-11-01. 204 names contain `low`. 2026-11-01 is listed, not settled, as of this note |
| `~/.local/share/breezy/catalog/polymarket_us` | Per-station weather catalogs: `LAX`, `MDW`, `MIA`, `NYC`, `SFO` |
| `~/.local/share/breezy/derived/nbp` | Directory exists |
| `~/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet` | File exists (~1.1 MB). Contents not read |
| `/mnt/storage/breezy/us_source_archive` | `metar-routine`, `us-lamp-live`, `us-lamp-mdl`, `us-lav-iem`, `us-lav-iem-avail`, `us-mos-gfs-avail`, `us-nbp-avail`, `us-obs-avail`, `us-pfm-afos` |
| `~/.local/share/breezy/kalshi` | `candles.jsonl`, `k1_kalshi_2026-09-02.md`, and `markets_KXHIGH{CHI,LAX,MIA,NY,TSFO}.json` only. No depth tree. No LOW series. No catalog entry under `/mnt/storage/breezy/catalog` |

Trade prints in the maker spec start 2026-09-17 (`docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` §2). Not re-counted from `ts_event` here.

Fee eras the replay already knows (`P2_NBP_VS_ASK_MURPHY_2026-10-22.md` §Gate): θ = 0.06 before 2026-09-17T00:00Z, refused until 17:00Z that day, then 0.0695.

## 4. Replay-sufficiency caveats already in the docs

These are properties of the harness and the tape, not of a new strategy.

1. **The engine does not model queue or latency.** Any maker fill count taken from `run_backtest` is an upper bound. The queue model that exists is the Stage 0 pass, and it has its own holes: no placement latency in the original pass (P1 measured that separately; the 17 fills survived 5 s), BUYER prints only, `NO_AGGRESSOR` never credited, empty NO bid never implied (`maker_stage0_fill_pass.py` lines 6–11 and the spec §6.1).

2. **The tape does not contain our orders.** A live book does. Replaying a family onto post-arm tape double-counts or misses the self-ratchet (L-65, `docs/core/LESSONS.md`). The Stage 0 pass also omits the order-count budget, the intent latch, and cancel-ack delay. P4's constrained replay kept 9 of 17 fills once those were applied (`docs/core/PROGRESS.md` P4 paragraph).

3. **QuoteTicks hide an empty bid.** Depth comes from Depth10 (L-35). A one-sided book is a normal weather state, not a quiet market (L-8).

4. **Settlement is the `settlement_prices` dict.** A missing key closes at the prevailing book and compresses PnL toward a better Sharpe (harness lines 31–34; spec §0). A price inside (0, 1) also invents a settlement fee the venue does not charge (harness lines 35–37). `BinaryOption` is not in the engine's expiring classes, so time-based expiry never fires; `InstrumentClose` of type `CONTRACT_EXPIRED` is the only trigger (lines 45–50).

5. **A close stamped before the last market record kills the rest of the instrument** (`_expiration_processed` is one-shot; harness lines 38–42).

6. **Sufficiency is per instance and per climate day.** The 2026-09-25 v2 census (`docs/evidence/AUD-09b_replay_sufficiency_v2_census_2026-09-25.md`) date-scoped the window. v1 had counted D−1 depth as if it were D. Three rows stayed ambiguous: MDW, MIA, NYC on 2026-09-14 (same-day fragments, a few minutes apart). Eighteen rows flipped from sufficient to insufficient once D−1 depth was excluded. Replay artefacts of any validity tag are not a promotion input for the old PREREG v3 covered-day count (`docs/evidence/replay_sufficiency_census_2026-09-24.md` lines 9–14).

7. **The catalog reader swallows a bad feather.** `ParquetDataCatalog` turning `ArrowInvalid` into an empty stream is why `k1_cheap_open_2026-09-01.md` opened files itself and split mid-write from corrupt. A 0-row day is not a quiet day until that preflight has been done (L-8).

8. **Maker design days are fenced.** `maker_design_nobid.py` lines 19–21: climate days stop at `LAST_ALLOWED_DAY`, truth is read only after simulation, stations are the four maker stations. The sharp nomination tape was 2026-09-18..2026-10-13 skipping 2026-10-01 (leakage audit). A new arm that reuses those settlements is not a new sample (L-56).

9. **M1-v3 is sealed.** `no_longshot_pooled_test.py` lines 21–30: 53 forward days, counts only until the read date, a READ report is never overwritten. Do not join NO prices ≥ 0.90 to truth on that window in a side study.

10. **Paper replay is the wrong object for a maker.** It builds a current-rung strategy, one station-day, IOC-style hold. Pointing it at a resting NO rule would be a new strategy inside an old driver, which is still the same engine, but the fill would ignore the queue (caveat 1). The maker's own driver is the Stage 0 pass, and its verdict ledger is one-shot.

11. **Kalshi is not a harness input.** Historical JSON for five HIGH series is not a `ParquetDataCatalog` of depth. `k1_kalshi_prior.py` is frozen by the WA-2 draft. There is no `add_venue` for Kalshi in `build_backtest_engine`.
