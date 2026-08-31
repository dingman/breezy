# Breezy / Nautilus Strategy Handoff
## `lagged_anomaly_tail`

Status: DESIGN ONLY — implement against the Breezy plug-in contract. Do not modify Nautilus internals. Do not add `__init__.py` or `pyproject.toml` registration.

Package path: `src/breezy/strategy/lagged_anomaly_tail/`
Files: `config.py` · `decision.py` · `strategy.py`

Related (do not clone): `forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`

Build order: third. Implement after the two observation-lock strategies are live or killed. This is the only new strategy that still *looks* like probability-vs-ask; the mechanism difference is the engine and the contract filter, not the inequality.

---

### 1. Name and one-sentence summary

Before any same-day official observation exists, buy YES only on the open-ended tail bucket when the historical frequency of landing in that tail — conditioned on yesterday’s finalized anomaly tercile at the same station — exceeds the live ask by more than costs.

---

### 2. Edge hypothesis (falsifiable)

Named inefficiency: **point-forecast anchoring on open tails**.

Retail and forecast-bots pile mass onto the 1–2° interior buckets around “the high will be 86.” The unbounded tail is an option on the error distribution. Conditional climatology

```
P(Tmax >= X | station, month, doy-window, yesterday’s finalized anomaly tercile)
```

is a better tail price than a deterministic high. The market systematically under-pays that tail after a same-sign anomaly yesterday (persistence) or after a large opposing anomaly (mean-reversion of extremes). Which sign dominates is an empirical property of the table, not an assumption in code.

The other side converts a single-number forecast into a tight interior distribution. They are structurally wrong about tail mass.

---

### 3. Why this persists

Open tails are cheap, so vig and fees eat a large fraction of naive size and deter crowded arb. Breezy currently ingests no forecast feed, so the existing `forecast_*` family cannot harvest this from the observation record. Mapping persistence onto *this station’s* 1° tail contract needs a station-level table most participants will not maintain. Exclusive-bucket plus max-event notional stop anyone from buying the whole distribution.

---

### 4. Loss conditions (unhedged)

1. Regime-break days the table does not contain (fronts; marine-layer collapse at KSFO / KLAX; dry-slot heat at KNYC / KMDW).
2. Climate-change drift if lookback is long and unweighted.
3. Yesterday’s anomaly itself was a bad sensor later corrected — **hard gate**: lagged day must be `is_final=True`.
4. Tail ask already rich versus the table.
5. Trading interior buckets with this rule (out of spec; interiors are where forecast-bots are densest).

---

### 5. Falsification test

Settlement-only. No prices required to kill.

1. Build the conditional frequency table on years of NWS finals for the five Polymarket.us stations, leave-one-year-out.
2. For each historical day, take the tail contract definition that would have been listed, or a fixed “≥ climatological P90” proxy if historical listings are unknown. If a proxy is used, write it down; do not hide it.
3. Compare Brier / log-loss of: conditional table vs unconditional monthly climatology vs persistence dummy (`T_today = T_yesterday`).
4. **Dead if** the conditional table does not beat unconditional climatology by `>= 0.01` in mean daily tail log-loss on a held-out year, **or** if realized tail frequency in the “buy” cells is within 2 percentage points of a flat monthly rate (conditioning adds nothing).
5. Economic overlay, using only **in-life** asks from the harness (not expired tapes): **dead if** mean `table_p - ask - c` on emitted signals `<= 0` over a season.

Do not inject synthetic forecasts into this test. That tests a different strategy.

---

### 6. Data dependencies

**Works with data Breezy has today**

- Historical NWS climate-day finals by station-date (venue-portable settlement truth; usable for Kalshi later)
- Yesterday’s record with `is_final=True` before today’s decision
- Live `OrderBookDepth10` on the open-tail instrument
- Bucket bounds from `WeatherBucketFacts`

**Requires data Breezy would first have to acquire**

- None for the core signal.
- A real forecast feed would **contaminate** the claim and collapse this into `forecast_mispricing`. Do not add one.
- Optional later upgrade, not required: NCEI 1991–2020 normals by station to define anomaly vs a published normal rather than a sample mean.
- Intra-day updates of this signal **this requires data Breezy does not have** (forecasts or running METAR). The spec forbids using them here. Same-day preliminaries belong to `running_extreme_lock`.

---

### 7. Holding period and settlement timing

Enter once yesterday’s final is in and the tail ask is live — typically morning of the observation day. Hold to next-morning settlement (~24 hours).

Edge is front-loaded: the lagged official anomaly is stale by late afternoon, when `running_extreme_lock` should own incremental size. Do **not** refresh this signal off today’s preliminary CLI.

If a same-day official extreme later locks the tail, `running_extreme_lock` is the correct owner of incremental size, subject to exclusive-bucket and max-event payout caps. This strategy must not fight that strategy for a second bucket on the same event.

---

### 8. Distinctiveness vs existing strategies and vs “model_p > ask”

Closer to the “model_p vs ask” *shape* than the other two new strategies. Mechanism difference is the **probability engine and the contract filter**:

- Engine: non-parametric frequency table on lagged official observations only. No NWS forecast, no ensemble, no synthetic scaffold.
- Filter: open-ended tail instruments only. Interiors hard-excluded.
- Gate: lagged climate day must be `is_final=True`.

`forecast_mispricing` cannot run on data that exists today without the scaffold. `forecast_revision` is a delta in a forecast time series this strategy does not read. `calibration_mean_reversion` is a price-process claim and short in current form. If you stripped the forecast feed out of the existing three, you would not obtain this decision.

`allow_short = False`. Never emit `SHORT_YES`.

---

### 9. Nautilus null-hypothesis check

| Need | Where it lives |
|---|---|
| Rolling price indicators | Irrelevant — do not use |
| Historical frequency table and tercile lookup | **new Breezy-side** (Nautilus has no climate calendar) |
| “Yesterday final known at decision time” | Breezy-side timestamp discipline in `decision.py` |
| Sizing / exposure | `RiskManager` + Nautilus `Portfolio` |
| Nautilus internals | **do not touch** |

---

### Plug-in contract (implement exactly)

**Config** — `frozen` subclass of `nautilus_trader.trading.config.StrategyConfig`.

```
allow_short: bool = False
open_tail_only: bool = True          # required for v1
lookback_years: int                  # table construction; not a live lookback of prices
doy_window_days: int = 15            # ± window around day-of-year
n_anomaly_bins: int = 3              # terciles
min_table_p: float
min_edge_after_costs: float
require_lagged_is_final: bool = True
max_hours_after_local_midnight: float  # optional decay / stop issuing new entries late day
```

Do not invent dollar figures for maximum daily trading budget or maximum notional per position.

**decision.py** — PURE.

Algorithm:

1. Instrument must be the open-ended tail for that event. Else `None`.
2. Resolve station + climate_day from `WeatherBucketFacts`.
3. Load lagged climate day D-1 for that station. Require `is_final=True` and `timestamp <= now`. Else `None`.
4. Compute lagged anomaly vs the table’s normal (sample month/doy mean from **prior** years only — no current-year leak).
5. Look up `table_p = P(tail | station, month, doy-window, anomaly bin)`.
6. `market_p = ask_p` from L2 book. `edge = table_p - ask_p - cost`.
7. If edge and `table_p` clear mins, emit `LONG_YES`. Else `None`.

No I/O in this module. Table is loaded by the strategy at start and passed in (or closed over as an immutable mapping). Building the table from files is `on_start` work, not decision work.

**strategy.py**

- `on_start`: load / cache the frequency table from historical NWS finals already in the runtime; subscribe depth for tail instruments only; subscribe client-scoped NWS data so D-1 finals arrive.
- `on_data`: if a record is a **final** for station S on day D-1, mark that lag ready and re-evaluate S’s **today** tail. Ignore other cities. Ignore today’s preliminaries for this strategy’s signal.
- `on_order_book_depth`: re-evaluate that tail if lag is ready.
- Risk then submit. Taker vs live ask only.

**Risk gate:** the standard 10 checks. Freshness: use lagged-observation age, not a fake forecast age. Exclusive-bucket: one long YES per `event_key`. Notional caps in max-payout dollars.

---

### Look-ahead rule (non-negotiable)

Known at decision time: live book; yesterday’s **already-final** NWS record; historical finals from years / days strictly before the climate_day being traded.

Not usable: today’s official high; any record dated after `now`; synthetic forecasts; reconstructed bid/ask of expired markets; current-year days after the decision day inside the climatology table (walk-forward the table).

---

### Sizing

Quantity is residual room under:

- `max_position_contracts`
- `max_event_notional / contract_size`
- `max_location_notional / contract_size`
- `max_equity_fraction * equity / contract_size`
- `max_simultaneous_positions`
- operator-reserved maximum daily trading budget (unset — do not hardcode)
- operator-reserved maximum notional per position (unset — do not hardcode)

Conviction scales toward those caps. Reason in payout dollars (`contract_size × contracts`), never in market value of the fill.

---

### Implementation notes for the Nautilus / Breezy agent

1. Do not implement this first. Kill or ship `running_extreme_lock` and measure `cli_settlement_print_lock` halt-window hit rate first.
2. Table construction is the actual research. If leave-one-year-out does not clear the falsification thresholds, delete the package. Do not “tune until it backtests green” against synthetic forecasts.
3. Copy layout from an existing strategy folder. Keep `allow_short=False`.
4. Registration: new files, imported by direct name. No `pyproject.toml` / `__init__.py` edits.
5. If this strategy and `running_extreme_lock` are both registered, exclusive-bucket + max-event notional must make them share one payout budget per `event_key`, not stack two tails.
