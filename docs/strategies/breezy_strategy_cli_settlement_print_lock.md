# Breezy / Nautilus Strategy Handoff
## `cli_settlement_print_lock`

Status: DESIGN ONLY — implement against the Breezy plug-in contract. Do not modify Nautilus internals. Do not add `__init__.py` or `pyproject.toml` registration.

Package path: `src/breezy/strategy/cli_settlement_print_lock/`
Files: `config.py` · `decision.py` · `strategy.py`

Related (do not clone): `forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`

---

### 1. Name and one-sentence summary

Buy YES on the single bucket that contains the already-published NWS CLI value for that station / climate_day, in the window after the settlement source prints and before the venue settles (08:00 ET the following calendar morning, or 11:00 ET if METAR review is invoked).

---

### 2. Edge hypothesis (falsifiable)

Named inefficiency: **settlement-source lag**.

Polymarket.us weather contracts settle on the local WFO Daily Climate Report (CLI), not on a weather app and not on the venue clock. The first mandatory CLI for climate day D is issued 12:30–05:00 **local** time on D+1 and describes the previous LST climate day (midnight–midnight Local Standard Time). Venue settlement is 08:00 ET on D+1 (11:00 ET if CLI disagrees with the 24-hour METAR).

Hypothesis: after that CLI is in the Breezy NWS client, the live ask on the printed bucket remains below `1 - cost - revision_haircut` because overnight flow watches apps / METAR spots or waits for the 08:00 ET event. The other side is thin overnight retail and bots that reprice on trades or on settlement, not on the CLI text product. They are structurally slow.

Stations in scope (Polymarket.us):

| City | Station | CLI product | Timezone vs 08:00 ET settlement |
|---|---|---|---|
| New York City | KNYC | CLINYC | ET — typical window 3–7.5 h |
| Miami | KMIA | CLIMIA | ET — typical window 3–7.5 h |
| Chicago | KMDW | CLIMDW | CT — typical window 2–6.5 h |
| Los Angeles | KLAX | CLILAX | PT — window may be 0–4.5 h; often tight vs halt |
| San Francisco | KSFO | CLISFO | PT — same as LA |

---

### 3. Why this persists

Overnight top-of-book on these binaries is thin (the same fact that makes shorts unexecutable). Reading CLI, mapping station → climate_day → bucket → instrument is operational work most flow will not do at 02:00 local. Exclusive-bucket rules stop a single participant from buying every name and forcing 0/1. Ask size caps how fast a correct buyer can pull the printed bucket to 1.00.

---

### 4. Loss conditions (unhedged)

The strategy loses money when:

1. A later CLI correction / `revision_seq` increment moves `tmax_f` or `tmin_f` across a bucket boundary before settlement.
2. CLI vs 24-hour METAR inconsistency triggers the 11:00 ET review and the reviewed number leaves the traded bucket.
3. Station or climate-day is mapped wrong (LST day, not civil clock during DST).
4. The ask is so close to 1.00 that one revision wipes `edge_after_costs`.
5. Shared risk halt fires (`hours_to_settlement` below `halt_hours_before_settlement` / `min_hours_to_settlement`) — path never trades.

---

### 5. Falsification test

Prices are not required to kill the idea.

Using historical NWS climate-day records already stored by Breezy (`revision_seq`, timestamps, first non-null extreme vs last value available before 08:00 ET):

- `p_stable` = fraction of station-days where the first morning CLI bucket equals the last pre-settlement value.
- **Dead if** `p_stable < 0.97` on the five stations, **or** if bucket-change rate times full payout loss exceeds ~3¢/trade after a 2¢ cost assumption. Required ask ceiling: `p_stable - c - 0.03`. If the median in-life ask on the printed bucket in the post-print window already sits above that ceiling, the idea is dead.
- Operational kill: fraction of station-days where first morning CLI timestamp still leaves `hours_to_settlement` above the current halt. **Dead if** that fraction `< 0.20`.
- Economic confirmation uses **in-life** `OrderBookDepth10` only. Do not reconstruct bid/ask of expired markets.

---

### 6. Data dependencies

**Works with data Breezy has today**

- `OrderBookDepth10` (execution price; never QuoteTick alone)
- NWS climate-day records via `subscribe_data(..., client_id=NWS_BACKTEST_CLIENT_ID)`
- Mandatory filter: `WeatherBucketFacts.applies_to(station, climate_day)` from `read_weather_bucket_facts(instrument.info)`
- Fields: `tmax_f` / `tmin_f` / `tavg_f`, `is_final`, `correction_flag`, `revision_seq`, `issuing_office`, timestamps
- Historical settlement / CLI outcomes by station-date for `p_stable`
- Instrument bucket bounds

**Requires data Breezy would first have to acquire**

- None for the core lock **if and only if** the NWS client delivers the morning CLI for climate_day D before 08:00 ET on D+1 while the D market is still open.
- If the client only emits a climate-day record after venue settlement, **this requires data Breezy does not have**: a CLI/AFOS feed with issuance time ahead of settlement (NWS AFOS `CLI*` or IEM parsed CLI).
- Do not assume a forecast feed exists. Do not add one.

---

### 7. Holding period and settlement timing

Minutes to a few hours. Enter only after the settlement source for that climate_day has printed. Edge dies at settlement or at a bucket-changing revision. Do not enter before the print. Edge strengthens as the print ages with no `revision_seq` increment and with `correction_flag` clear.

Halt-hours is the binding interaction. This strategy is late-cycle by construction. PT stations may have no legal window.

---

### 8. Distinctiveness vs existing strategies and vs “model_p > ask”

No temperature model. The decision is an event: the public document that **is** the resolution source has printed a number that falls in bucket B. `model_probability` is `1 - p_revise_out_of_B`, not a forecast CDF.

- `forecast_mispricing` / `forecast_revision` need an exogenous forecast (synthetic in current backtests).
- `calibration_mean_reversion` fades a price toward a calibrated mean and, as deployed, is short-oriented.
- This strategy emits only `LONG_YES` on the printed bucket and is silent otherwise.
- `allow_short` stays `False`. Never emit `SHORT_YES`.

---

### 9. Nautilus null-hypothesis check

| Need | Where it lives |
|---|---|
| Wake in CLI window | Nautilus `Clock` time alerts (native) |
| Latest book + custom data | `subscribe_order_book_depth`, `subscribe_data`, `Cache` (native) |
| Portfolio / account | Nautilus `Portfolio` (native) |
| Order submit after risk | existing Breezy `RiskManager.evaluate_order` then Nautilus order (do not reimplement risk) |
| CLI → bucket map, `p_stable` table, applies_to filter | **new Breezy-side** in `decision.py` |
| Nautilus internals | **do not touch** |

---

### Plug-in contract (implement exactly)

**Config** — `frozen` subclass of `nautilus_trader.trading.config.StrategyConfig` (that import path; the strategy-module import breaks construction).

Suggested fields (all tunable; do not invent dollar figures for the two operator-reserved caps):

```
allow_short: bool = False          # MUST remain False
min_stable_prob: float = 0.97
min_edge_after_costs: float        # pass-through intent; RiskManager also enforces min_model_edge
max_quote_age_minutes: float
require_correction_flag_clear: bool = True
use_tmax: bool = True              # primary
use_tmin: bool = False             # only if instrument is a min bucket
```

Do not put `max_daily_trading_budget` or `max_notional_per_position` numbers in config. Size as a function of those caps **when the operator assigns them**, plus existing payout-dollar caps (`max_event_notional`, `max_location_notional`, `max_position_contracts`, `max_equity_fraction`, `max_simultaneous_positions`).

**decision.py** — PURE. No I/O, no order submit.

Inputs (conceptual): instrument facts, latest applicable NWS record, live L2 ask/bid, hours_to_settlement, quote age, `p_stable` lookup, cost.

Output: `SignalDecision | None` from `src/breezy/strategy/weather_common/models.py`:

```
instrument_id: str
intent: SideIntent                 # LONG_YES or FLAT only
model_probability: float           # 1 - p_revise_out_of_bucket
market_probability: float          # ask_p for a long
edge: float                        # model_p - ask_p - cost
conviction: float
quantity: float                    # payout-notional aware; clip later in risk
reason: str
metadata: Mapping[str, float | str | int | None]
```

Hard gates inside the pure function (return `None` if any fail):

1. Record does not `applies_to` this instrument’s station + climate_day.
2. No printed extreme yet (`tmax_f` / `tmin_f` is None).
3. Printed value is not inside this instrument’s bucket bounds.
4. `correction_flag` set and config requires it clear.
5. Record timestamp is in the future relative to decision time (clock bug / look-ahead).
6. Intent would be short.

Executable edge is **never** midpoint. Long YES: `model_p - ask_p - cost`.

**strategy.py** — Nautilus `Strategy` subclass.

- `on_start`: subscribe `OrderBookDepth10` for targeted instruments; subscribe NWS climate-day data client-scoped; optionally set clock alerts for expected CLI windows.
- `on_order_book_depth`: call decision; pass result through `RiskManager.evaluate_order(...)`; submit only if the gate returns an executable order.
- `on_data`: if the payload is an NWS climate-day record, store latest-by-(station, climate_day) in strategy state (or Cache), then re-evaluate instruments that `applies_to` that pair. Ignore every other city’s record.
- Do not drive execution from `QuoteTick`.
- Do not handle `InstrumentClose` unless the harness requires it; settlement is harness-owned.
- NETTING / CASH / L2 / venue fee model are harness concerns. Assume every fill is a **taker against the live ask**. No post-only, no maker-rebate dependence.

**RiskManager.evaluate_order order of checks** (do not reorder, do not bypass):

1. hours_to_settlement vs halt / min hours  
2. forecast_age_hours vs stale_forecast_hours — this strategy has **no forecast**. Pass a sentinel the risk layer already accepts for “no forecast”, or the observation-record age if that is what the gate measures. Do not invent a synthetic forecast age of 0 to sneak past the gate. If the existing gate is forecast-only and blocks observation strategies, raise that as an implementation blocker; do not patch Nautilus.  
3. abs(edge) vs min_model_edge  
4. short open refused unless `allow_short` — keep False  
5. live uncrossed bid **and** ask, spread, min liquidity, quote not stale/future  
6. exclusive-bucket conflict  
7. max_position_contracts  
8. max_event_notional and max_location_notional in **MAX-PAYOUT dollars** (`contract.contract_size × contracts`, grouped by `event_key = "{settlement_station}:{climate_day}"` and `location_id = settlement_station`)  
9. max_simultaneous_positions  
10. max_equity_fraction  

---

### Look-ahead rule (non-negotiable)

Known at decision time: live book; NWS records with `timestamp <= now`; the morning CLI already sitting in the client.

Not known / not usable: today’s final before that record’s timestamp; any synthetic forecast; any reconstructed bid/ask from a market that has already expired; tomorrow’s settlement number.

---

### Sizing

`quantity` is the largest integer contract count that still clears risk after conviction scaling, expressed as a function of:

- remaining room under `max_position_contracts`
- remaining `max_event_notional / contract_size`
- remaining `max_location_notional / contract_size`
- `max_equity_fraction * equity / contract_size`
- `max_simultaneous_positions`
- operator-reserved **maximum daily trading budget** (unset — do not hardcode)
- operator-reserved **maximum notional per position** (unset — do not hardcode)

Reason in payout dollars, never in current market value.

---

### Implementation notes for the Nautilus / Breezy agent

1. Copy the folder layout of `src/breezy/strategy/forecast_mispricing/` for imports, logging, and how risk is called. Swap the decision.
2. Registration is “new files imported by direct name.” Zero changes to `pyproject.toml` or any `__init__.py`.
3. Backtest via existing `BreezyBacktestConfig` / `run_backtest` / `scripts/analysis/run_weather_strategy_backtests.py`.
4. First experiment is not a full backtest: compute `p_stable` and halt-window hit rate on stored NWS history.
5. If halt-window hit rate is below 20%, stop. Do not loosen shared risk by patching Nautilus or the global RiskManager “just for this strategy” unless the operator explicitly adds a per-strategy halt override that already exists as a config hook.
